"""O esquema e o `downgrade` da revisao 0012 (KAM-020).

O DoD do ticket pede **pelo nome** «`downgrade` de `media_assets` testado», e
esta bateria e isso. Mas tem mais casos, e cada um existe por uma razao que a
revisao escreveu e que nenhum outro teste confere:

1. **As tres FK, coluna a coluna.** Tem tres FK e duas sao **compostas**
   com o `tenant_id` (a `outbound_messages` da `0010` tem quatro, pelo que
   esta nao e a que tem mais — a primeira versao desta nota dizia que era). A contagem global (`test_catalogo`) ve
   que sao 29; o que ela nao ve e **para onde cada uma aponta** — e uma FK que
   aponta para `contacts (contact_id)` em vez de `(tenant_id, contact_id)`
   passaria a contagem e abria o furo que a `0009` fechou.

2. **A assimetria das unicidades, e e deliberada.** A `media_assets_origem_uq`
   leva o `tenant_id`, pelo que o **mesmo** `(wamid, media_id)` em dois tenants
   e **aceite**. E o contrario da `handoff_accounts_conta_uq` da `0011`, que o
   recusa — e a diferenca nao e descuido: uma conta no provedor e um recurso
   **compartilhavel por erro**, e dois tenants a apontar para ela era uma PME a
   ler as conversas da outra; um `wamid` e um identificador que a Meta emite por
   mensagem, e duas PMEs com o mesmo valor e uma colisao do lado dela, nao um
   furo do nosso.

3. **As restricoes recusam de verdade.** Um teste que so as visse em
   `pg_constraint` nao provava que elas mordem, e a `media_assets_armazenado_ck`
   e a unica do esquema que liga duas colunas por estado.

4. **A ausencia de `CHECK` sobre o `retain_until` e uma assercao.** Era o que
   apetecia — «um prazo de retencao so faz sentido no futuro» — e e o defeito
   que a `outbound_messages_entrega_ck` da `0010` pagou: uma restricao que
   recusa um estado que a propria maquina produz. Aqui seria pior: a purga e
   KAM-071, e uma data passada e exactamente como ela marca um objecto para
   eliminacao imediata. Este teste existe para que acrescentar essa restricao
   **passe por aqui**, e nao em silencio.

**O driver e o `pg8000` e as assercoes sao pelo `sqlstate`**, que e o idioma da
casa (`db/tests/base.py`): dizer «houve erro» nao distingue a restricao que
recusou de um `INSERT` mal escrito, e um `23514` onde se esperava `23505` e um
teste que passa pela razao errada.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao
import pg8000.dbapi
from tests import factories
from tests.base import (
    ComBase,
    TABELAS,
    TABELAS_ATE_0011,
    TABELAS_ATE_0013,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0012_COPIA"

#: As catorze colunas da copia logica, pela ordem do `SELECT` da revisao.
COLUNAS_DA_COPIA = (
    "asset_id",
    "tenant_id",
    "contact_id",
    "conversation_id",
    "wamid",
    "media_id",
    "classe",
    "content_type",
    "size",
    "sha256",
    "storage_ref",
    "estado",
    "retain_until",
    "criado_at",
)

#: Um resumo de 64 digitos hexadecimais minusculos, que e o que o `CHECK` exige
#: e o que o `ObjectRef.sha256` da porta do KAM-011 devolve.
SHA_DE_TESTE = "a" * 64

#: Uma chave de objecto com a forma da porta do KAM-011.
CHAVE_DE_TESTE = "t/00000000-0000-4000-8000-000000000000/media_audio/2026/10/abc"


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'platform' ORDER BY table_name"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class ComMidia(unittest.TestCase):
    """Base da classe que escreve: um tenant limpo por caso."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()
        self.tenants: list[str] = []

    def tearDown(self) -> None:
        try:
            for tenant in self.tenants:
                for tabela in (
                    "media_assets",
                    "conversations",
                    "tenant_channels",
                    "contacts",
                ):
                    self.cursor.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,)
                    )
                self.cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
            self.cursor.execute(
                "DELETE FROM platform.hmac_key_versions WHERE kid = %s",
                (factories.KID_DE_TESTE,),
            )
        finally:
            self.conexao.close()

    def conversa(self) -> tuple[str, str, str]:
        """Um tenant limpo, com contacto e conversa. Devolve os tres."""
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        canal = factories.canal(self.cursor, tenant)
        contacto = factories.contacto(self.cursor, tenant)
        identificador = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO platform.conversations "
            "(id, tenant_id, contact_id, channel_id) VALUES (%s, %s, %s, %s)",
            (identificador, tenant, contacto, canal),
        )
        return tenant, contacto, identificador

    def inserir(self, tenant, contacto, conversa, **campos) -> None:
        valores = {
            "tenant_id": tenant,
            "contact_id": contacto,
            "conversation_id": conversa,
            "wamid": f"wamid.{uuid.uuid4().hex[:12]}",
            "media_id": f"media-{uuid.uuid4().hex[:12]}",
            "classe": "media_audio",
            "estado": "pendente",
        }
        valores.update(campos)
        colunas = ", ".join(valores)
        marcas = ", ".join(["%s"] * len(valores))
        self.cursor.execute(
            f"INSERT INTO platform.media_assets ({colunas}) VALUES ({marcas})",
            tuple(valores.values()),
        )


class TestEsquemaDaMidia(ComBase):
    """O que a `0012` cria, e o que ela **nao** cria."""

    def test_as_tres_fk_sao_as_declaradas_coluna_a_coluna(self) -> None:
        """Tres FK, e duas levam o `tenant_id`.

        A contagem global ve que sao tres; o que ela nao ve e para onde cada uma
        aponta. Uma FK para `contacts (contact_id)` em vez de
        `(tenant_id, contact_id)` passava a contagem e deixava um objecto de A
        apontar para um contacto de B.
        """
        linhas = self.consultar(
            "SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'platform.media_assets'::regclass AND contype = 'f'"
        )
        self.assertEqual(
            dict(linhas),
            {
                "media_assets_tenant_fk": (
                    "FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id)"
                ),
                "media_assets_contact_fk": (
                    "FOREIGN KEY (tenant_id, contact_id) "
                    "REFERENCES platform.contacts(tenant_id, contact_id)"
                ),
                "media_assets_conversation_fk": (
                    "FOREIGN KEY (tenant_id, conversation_id) "
                    "REFERENCES platform.conversations(tenant_id, id)"
                ),
            },
        )

    def test_a_chave_e_a_unicidade_dizem_coisas_diferentes(self) -> None:
        """A primaria identifica a linha; a `UNIQUE` e a idempotencia.

        Sao duas e nao uma porque respondem a perguntas diferentes: o `asset_id`
        e o que o criterio 5 poe em `media://{asset_id}` e tem de ser estavel
        quando a chave do objecto mudar de molde; a `origem_uq` e o que faz «a
        mesma `(tenant_id, wamid, media_id)` processada 3x produzir 1 linha» ser
        uma propriedade da base e nao do codigo.
        """
        linhas = dict(
            self.consultar(
                "SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'platform.media_assets'::regclass "
                "AND contype IN ('p', 'u')"
            )
        )
        self.assertEqual(
            linhas,
            {
                "media_assets_pkey": "PRIMARY KEY (asset_id)",
                "media_assets_origem_uq": "UNIQUE (tenant_id, wamid, media_id)",
            },
        )

    def test_a_midia_tem_indice_que_comeca_por_tenant_id(self) -> None:
        """A chave primaria nao leva `tenant_id`, logo o indice e proprio.

        A RLS le o `tenant_id` em **toda** a consulta, e a convencao que o
        `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` impoe pede que
        **algum** indice comece por ele. A segunda coluna e escolha desta
        revisao, e e o que o painel ordena.
        """
        linhas = self.consultar(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'platform' AND tablename = 'media_assets' "
            "AND indexname = 'media_assets_tenant_idx'"
        )
        self.assertEqual(len(linhas), 1, "o indice por tenant nao existe")
        self.assertIn("tenant_id", linhas[0][0])
        self.assertIn("criado_at DESC", linhas[0][0])

    def test_os_dois_dominios_tem_os_valores_declarados(self) -> None:
        """**Os valores e nao so os nomes**, e a diferenca apanhou uma mutacao.

        A primeira versao desta bateria afirmava a lista de **nomes** de `CHECK`
        e nunca o `pg_get_constraintdef` de nenhum deles. A revisao adversarial
        mostrou o que isso deixava passar: a mutacao que tira `'media_documento'`
        do dominio da classe nao muda nome nenhum, e a cadeia nao existe em
        `db/` fora da propria revisao — nenhum teste desta suite a inseria nem a
        afirmava. Ela sobrevivia, e o relatorio dizia «0 nao apanhadas».

        Quem a apanharia era o gate 3b (que compara o dominio do dicionario com
        o DDL), e o corredor de mutacoes nao corre o 3b: corre a suite declarada
        e exige que **ela** falhe. Logo a assercao tem de viver aqui.
        """
        definicoes = dict(
            self.consultar(
                "SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'platform.media_assets'::regclass "
                "AND conname IN ('media_assets_classe_ck', 'media_assets_estado_ck')"
            )
        )
        for valor in ("media_audio", "media_imagem", "media_documento"):
            with self.subTest(classe=valor):
                self.assertIn(valor, definicoes["media_assets_classe_ck"])
        for valor in ("pendente", "armazenado", "rejeitado", "falhou"):
            with self.subTest(estado=valor):
                self.assertIn(valor, definicoes["media_assets_estado_ck"])
        # **E so esses**: um valor a mais no dominio e tao defeito como um a
        # menos, e o `falhado` e a grafia vizinha que o conjunto usa noutras
        # tabelas.
        self.assertNotIn("falhado", definicoes["media_assets_estado_ck"])

    def test_nao_ha_check_sobre_o_retain_until(self) -> None:
        """**A ausencia e a assercao**, e tem razao escrita na revisao.

        Ver a nota do modulo, ponto 4: uma restricao que obrigasse o
        `retain_until` a ser futuro impedia o KAM-071 de marcar um objecto para
        eliminacao imediata.
        """
        linhas = self.consultar(
            "SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'platform.media_assets'::regclass AND contype = 'c'"
        )
        definicoes = " ".join(d for _, d in linhas)
        self.assertNotIn("retain_until", definicoes)
        # E as sete que **ha**, que e a lista fechada do que a base recusa.
        self.assertEqual(
            sorted(nome for nome, _ in linhas),
            [
                "media_assets_armazenado_ck",
                "media_assets_classe_ck",
                "media_assets_estado_ck",
                "media_assets_media_id_ck",
                "media_assets_sha256_ck",
                "media_assets_size_ck",
                "media_assets_wamid_ck",
            ],
        )


class TestRestricoesQueMordem(ComMidia):
    """As restricoes que um `pg_constraint` nao prova: estas recusam de verdade."""

    def test_a_mesma_origem_duas_vezes_e_recusada(self) -> None:
        """**E a idempotencia do criterio 2, e e da base.**

        O criterio pede «a mesma `(tenant_id, wamid, media_id)` processada 3x
        produz 1 objecto e 1 linha». Esta restricao garante a segunda metade, e
        garante-a contra qualquer codigo — incluindo codigo que se esqueca de
        verificar primeiro.
        """
        tenant, contacto, conversa = self.conversa()
        self.inserir(tenant, contacto, conversa, wamid="wamid.X", media_id="m-1")
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(tenant, contacto, conversa, wamid="wamid.X", media_id="m-1")
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_UNICIDADE)

    def test_a_mesma_origem_em_dois_tenants_e_aceite(self) -> None:
        """**A assimetria com a `0011`, e e deliberada.**

        A `handoff_accounts_conta_uq` recusa a mesma conta do provedor em dois
        tenants; esta **aceita** o mesmo `(wamid, media_id)`. A diferenca nao e
        descuido: uma conta no provedor e um recurso compartilhavel por erro, e
        dois tenants a apontar para ela era uma PME a ler as conversas da outra.
        Um `wamid` e emitido pela Meta por mensagem, e duas PMEs com o mesmo
        valor e uma colisao do lado dela — recusar a segunda fazia a nossa base
        perder uma mensagem por causa de um defeito que nao e nosso.

        Este teste existe para que apertar a `origem_uq` (tirar-lhe o
        `tenant_id`) **falhe aqui**, em vez de perder mensagens em producao.
        """
        um, contacto_um, conversa_um = self.conversa()
        outro, contacto_outro, conversa_outro = self.conversa()
        self.inserir(um, contacto_um, conversa_um, wamid="wamid.Y", media_id="m-2")
        self.inserir(
            outro, contacto_outro, conversa_outro, wamid="wamid.Y", media_id="m-2"
        )
        self.cursor.execute(
            "SELECT count(*)::text FROM platform.media_assets WHERE wamid = 'wamid.Y'"
        )
        self.assertEqual(self.cursor.fetchone()[0], "2")

    def test_armazenado_sem_storage_ref_e_recusado(self) -> None:
        """A unica restricao do esquema que liga duas colunas por estado.

        Um `armazenado` sem `storage_ref` e uma linha que diz que o objecto esta
        la e nao diz onde: o consumidor pede `signUrl` e nao ha o que assinar.
        """
        tenant, contacto, conversa = self.conversa()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(tenant, contacto, conversa, estado="armazenado")
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)

    def test_armazenado_sem_sha256_e_recusado(self) -> None:
        """As tres sao exigidas juntas, e nao so a chave.

        Sem o `sha256` nao se sabe se o que esta la e o que se descarregou.
        """
        tenant, contacto, conversa = self.conversa()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(
                tenant,
                contacto,
                conversa,
                estado="armazenado",
                storage_ref=CHAVE_DE_TESTE,
                size=10,
            )
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)

    def test_armazenado_sem_size_e_recusado(self) -> None:
        """Sem o `size` nao se sabe quanto custa, e a facturacao le-o."""
        tenant, contacto, conversa = self.conversa()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(
                tenant,
                contacto,
                conversa,
                estado="armazenado",
                storage_ref=CHAVE_DE_TESTE,
                sha256=SHA_DE_TESTE,
            )
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)

    def test_armazenado_com_as_tres_passa(self) -> None:
        """E o controlo, e sem ele os tres testes acima valiam menos.

        Um `assertRaises` sozinho nao distingue «a restricao recusou» de «o
        `INSERT` estava mal escrito». Este e o par positivo.
        """
        tenant, contacto, conversa = self.conversa()
        self.inserir(
            tenant,
            contacto,
            conversa,
            estado="armazenado",
            storage_ref=CHAVE_DE_TESTE,
            size=1024,
            sha256=SHA_DE_TESTE,
            content_type="audio/ogg",
        )
        self.cursor.execute(
            "SELECT count(*)::text FROM platform.media_assets "
            "WHERE tenant_id = %s AND estado = 'armazenado'",
            (tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], "1")

    def test_um_sha256_com_outra_forma_e_recusado(self) -> None:
        """Um resumo com outra forma e um resumo de outra coisa.

        A forma vale porque e o que o `ObjectRef.sha256` da porta do KAM-011
        devolve: 64 digitos hexadecimais **minusculos**. Maiusculas tambem
        recusam, e e de proposito — duas grafias do mesmo resumo faziam a
        deduplicacao por conteudo falhar sem ninguem ver.
        """
        tenant, contacto, conversa = self.conversa()
        for invalido in ("curto", SHA_DE_TESTE.upper(), SHA_DE_TESTE + "a"):
            with self.subTest(sha256=invalido[:12]):
                with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                    self.inserir(tenant, contacto, conversa, sha256=invalido)
                self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)

    def test_um_tamanho_negativo_e_recusado(self) -> None:
        """Negativo nao existe em sitio nenhum."""
        tenant, contacto, conversa = self.conversa()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(tenant, contacto, conversa, size=-1)
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)

    def test_um_tamanho_zero_passa(self) -> None:
        """Zero existe: um ficheiro vazio descarrega-se.

        E a *allowlist* de tamanho que o recusa — em configuracao, calibravel —,
        e nao a base. Uma base que recusasse zero tornava impossivel registar o
        que aconteceu.
        """
        tenant, contacto, conversa = self.conversa()
        self.inserir(tenant, contacto, conversa, size=0)

    def test_uma_classe_fora_do_dominio_e_recusada(self) -> None:
        """Tres valores, e o dominio e **qualificado** (`media_assets.classe`).

        Qualificado pela regra da emenda 1.14: um dominio sobre um nome generico
        como `classe` passaria a valer para qualquer coluna com esse nome. E o
        valor que falha aqui e `audio` — o `wa_type` — de proposito: e o erro
        natural de quem esquecer a traducao de vocabulario.
        """
        tenant, contacto, conversa = self.conversa()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(tenant, contacto, conversa, classe="audio")
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)

    def test_um_estado_fora_do_dominio_e_recusado(self) -> None:
        """Quatro valores, e o que falha aqui e a quarta grafia de «falhou».

        No conjunto ha `falhado` (`image_jobs`), `falhada` (`evt_acoes`) e
        `falhou` (esta tabela). Este teste existe para que escolher a grafia
        errada falhe **aqui**, e nao em producao.
        """
        tenant, contacto, conversa = self.conversa()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.inserir(tenant, contacto, conversa, estado="falhado")
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)


class TestDowngradeDa0012(unittest.TestCase):
    """«Migracoes reversiveis — `downgrade` testado», e sem perda em silencio."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()
        self.pasta = tempfile.TemporaryDirectory()
        self.copia = Path(self.pasta.name) / "copia-0012.json"
        self.tenants: list[str] = []
        os.environ.pop(VARIAVEL_DA_COPIA, None)

    def tearDown(self) -> None:
        os.environ.pop(VARIAVEL_DA_COPIA, None)
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self.tenants:
                for tabela in (
                    "media_assets",
                    "conversations",
                    "tenant_channels",
                    "contacts",
                ):
                    self.cursor.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,)
                    )
                self.cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
            self.cursor.execute(
                "DELETE FROM platform.hmac_key_versions WHERE kid = %s",
                (factories.KID_DE_TESTE,),
            )
        finally:
            self.conexao.close()
            self.pasta.cleanup()

    def semear(self) -> list[str]:
        """Dois objectos de dois tenants, um deles **armazenado**.

        O armazenado e o que torna o `downgrade` destrutivo de verdade: e o que
        tem `storage_ref`, isto e, o que aponta para um blob que **fica** no
        armazenamento quando a linha cair.
        """
        chaves: list[str] = []
        for indice in range(2):
            tenant = factories.tenant(self.cursor)
            self.tenants.append(tenant)
            canal = factories.canal(self.cursor, tenant)
            contacto = factories.contacto(self.cursor, tenant)
            conversa = str(uuid.uuid4())
            self.cursor.execute(
                "INSERT INTO platform.conversations "
                "(id, tenant_id, contact_id, channel_id) VALUES (%s, %s, %s, %s)",
                (conversa, tenant, contacto, canal),
            )
            chave = f"t/{tenant}/media_audio/2026/10/{uuid.uuid4().hex[:8]}"
            if indice == 0:
                self.cursor.execute(
                    "INSERT INTO platform.media_assets "
                    "(tenant_id, contact_id, conversation_id, wamid, media_id, "
                    " classe, content_type, size, sha256, storage_ref, estado, "
                    " retain_until) "
                    "VALUES (%s, %s, %s, %s, %s, 'media_audio', 'audio/ogg', "
                    "        4096, %s, %s, 'armazenado', "
                    "        now() + interval '24 hours')",
                    (
                        tenant,
                        contacto,
                        conversa,
                        f"wamid.{uuid.uuid4().hex[:12]}",
                        f"media-{indice}",
                        SHA_DE_TESTE,
                        chave,
                    ),
                )
            else:
                self.cursor.execute(
                    "INSERT INTO platform.media_assets "
                    "(tenant_id, contact_id, conversation_id, wamid, media_id, "
                    " classe, estado) "
                    "VALUES (%s, %s, %s, %s, %s, 'media_imagem', 'pendente')",
                    (
                        tenant,
                        contacto,
                        conversa,
                        f"wamid.{uuid.uuid4().hex[:12]}",
                        f"media-{indice}",
                    ),
                )
            chaves.append(chave)
        return chaves

    def test_com_a_tabela_vazia_desce_e_sobe_sem_pedir_copia(self) -> None:
        """Sem objectos nao ha nada a perder: nao pergunta."""
        self.cursor.execute("SELECT count(*) FROM platform.media_assets")
        self.assertEqual(self.cursor.fetchone()[0], 0, "a base nao esta limpa")

        alembic_ok("downgrade", "0011")
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0011)
        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)

    def test_com_linhas_e_sem_a_variavel_o_downgrade_recusa(self) -> None:
        """**A recusa diz quantos sao, e nao apaga nada.**

        E a politica sai **antes** de se contar: com `FORCE ROW LEVEL SECURITY`
        o dono da tabela esta sujeito a politica, e uma migracao corre **sem**
        contexto de tenant. Se o `disable_tenant_rls` nao fosse a primeira
        instrucao, o `count(*)` via **zero** sobre uma tabela cheia — nao pedia
        copia e apagava em silencio. Foi um defeito medido na `0009` e
        confirmado na `0010` e na `0011`.
        """
        self.semear()

        resultado = alembic("downgrade", "0011")

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        saida = resultado.stdout + resultado.stderr
        self.assertIn("2 objecto(s)", saida)
        self.assertIn(VARIAVEL_DA_COPIA, saida)
        # **A razao da recusa esta na mensagem**, e nao e so a contagem: o que a
        # distingue das outras revisoes e que os blobs ficam.
        self.assertIn("deixa os blobs", saida)
        # **A base ficou em `0012` e nao em `head`, e desde a `0014` a
        # diferenca existe.** O `downgrade` levanta na propria revisao e o
        # Alembic corre uma transaccao por revisao
        # (`transaction_per_migration=True`), pelo que descer de `head` para
        # `0011` passa primeiro pela `0014`, que desce e **compromete**, e so
        # depois a `0012` recusa. A `channel_quality_log` ja caiu quando esta
        # linha corre — e e a mesma nota que a `0011` escreveu para o
        # `TABELAS_ATE_0009` e a `0012` para o `TABELAS_ATE_0011`.
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0013)
        self.cursor.execute("SELECT count(*) FROM platform.media_assets")
        self.assertEqual(self.cursor.fetchone()[0], 2)
        # E o `FORCE` ficou **intacto**: a recusa nao pode trocar uma perda de
        # dados por um furo de isolamento.
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.media_assets'::regclass"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True))

    def test_com_a_variavel_escreve_a_copia_e_desce(self) -> None:
        """A copia leva as catorze colunas, e o `storage_ref` e o que importa.

        **Sem ele a copia nao serve de nada**: os blobs ficam no armazenamento e
        o `storage_ref` e a unica coisa que permite reencontra-los. Uma copia sem
        ele era um registo de que havia objectos, sem dizer quais.
        """
        chaves = self.semear()
        os.environ[VARIAVEL_DA_COPIA] = str(self.copia)

        alembic_ok("downgrade", "0011")

        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0011)
        with open(self.copia, encoding="utf-8") as ficheiro:
            copia = json.load(ficheiro)
        self.assertEqual(list(copia), ["media_assets"])
        linhas = copia["media_assets"]
        self.assertEqual(len(linhas), 2)
        for linha in linhas:
            self.assertEqual(tuple(linha), COLUNAS_DA_COPIA)
        # **O `storage_ref` do armazenado esta la**, que e o que permite
        # reencontrar o blob que ficou.
        refs = {linha["storage_ref"] for linha in linhas}
        self.assertIn(chaves[0], refs)
        # E o do pendente e `None`: ele nunca chegou a escrever.
        self.assertIn("None", refs)
