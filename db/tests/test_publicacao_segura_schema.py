"""A revisao da publicacao segura e do teste em producao contra a base (KAM-202).

O que so uma base prova, e por isso este ficheiro existe:

1. **O `conteudo_sha256` da base e o do KAM-088**, byte a byte: a funcao SQL da
   os valores da fixture que o `conteudoSha256` de TypeScript tambem tem de dar
   (`packages/core-ts/tests/publicacao_segura.test.ts`).
2. **A publicacao e protegida pela base**, com o SQL do COM tal como esta
   escrito e pela ligacao da aplicacao: sem decisao, com `bloqueada`, com
   `condicional`, com a decisao de outro nome, de outro `sku` ou de outro
   tenant, o `SQL_PUBLICAR` afecta zero linhas — e com `permitida`, ou com o
   recurso humano, publica.
3. **Cada caminho de escrita do COM continua a passar**, e o nome novo num
   publicado sem decisao tira-o de `publicado`, sem `23514`.
4. **O sinal do teste**: a aplicacao escreve o `teste_recebido_at` e so ele, e
   o observador le os quatro factos pela ligacao da aplicacao.
5. **A decisao humana so do lote** (criterio 6).
6. **A conversa de teste fora das cinco leituras do criterio 3**: o
   `churn_sinais`, a guarda do *job* (`SQL_CLIENTES_NA_JANELA`), a
   `v_draft_metrics`, os candidatos a golden e as queixas do `risco_ts`.
7. **O `downgrade`**, pelo numero lido da revisao.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ligacao

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

import golden_candidates  # noqa: E402
from kamba_core.kpis import churn  # noqa: E402
from tests import factories  # noqa: E402
from tests.test_catalogo_minimo_schema import caso  # noqa: E402
from tests.base import (  # noqa: E402
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

FIXTURE = _RAIZ / "packages" / "core-ts" / "tests" / "fixtures" / "conteudo_sha256.json"
COM = _RAIZ / "services" / "com" / "src" / "produtos" / "consultas.ts"
CHR = _RAIZ / "packages" / "core-ts" / "src" / "chr" / "consultas.ts"
OBSERVADOR = _RAIZ / "packages" / "core-ts" / "src" / "activacao" / "observador_sql.ts"
SCREENING = _RAIZ / "packages" / "core-ts" / "src" / "screening" / "sql.ts"
TRUST = _RAIZ / "packages" / "core-ts" / "src" / "trust" / "sql.ts"
#: Por *glob* e nao pelo numero: o numero e da fila de migracoes.
REVISAO = next((_RAIZ / "db" / "migrations" / "versions").glob("*_publicacao_segura_e_teste_em_producao.py"))

OFERTA = "platform.offer_terms"
DECISAO = "platform.screening_decision"
VERSAO = "1.0.0+m.2"
AGORA = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
LIMIARES = {
    "dono_sem_actividade_dias": 7,
    "sem_pedidos_dias": 14,
    "pagamento_em_atraso_dias": 5,
    "catalogo_desactualizado_dias": 28,
    "dormente_dias": 60,
    "dormente_janela_clientes_dias": 30,
    "dormente_aviso_dias": 7,
}
D = timedelta(days=1)


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def sha(cursor, categoria: str, nome: str) -> bytes:
    cursor.execute("SELECT platform.conteudo_sha256_do_produto(%s, %s)", (categoria, nome))
    return bytes(cursor.fetchone()[0])


def decidir(cursor, tenant: str, sujeito_tipo: str, ref: str, decisao: str, *,
            origem: str = "regra", conteudo: bytes | None = None, versao: str = VERSAO) -> None:
    cursor.execute(
        f"INSERT INTO {DECISAO} (tenant_id, sujeito_tipo, sujeito_ref, decisao, regras, "
        "versao_politica, origem, conteudo_sha256) VALUES (%s, %s, %s, %s, ARRAY[]::text[], %s, %s, %s)",
        (tenant, sujeito_tipo, ref, decisao, versao, origem,
         conteudo if conteudo is not None else hashlib.sha256(ref.encode()).digest()),
    )


def oferta(cursor, tenant: str, sku: str, nome: str, estado: str = "rascunho") -> None:
    # Com categoria (KAM-209): sem ela a base nao publica, e aqui mede-se o screening.
    cursor.execute(
        f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, estado, categoria) "
        "VALUES (%s, %s, %s, 'fixo', 100000, %s, 'moda')",
        (tenant, sku, nome, estado),
    )


def estado_de(cursor, tenant: str, sku: str) -> tuple[str, str]:
    cursor.execute(f"SELECT estado, nome FROM {OFERTA} WHERE tenant_id = %s AND sku = %s", (tenant, sku))
    linha = cursor.fetchone()
    return linha[0], linha[1]


def correr(cursor, ficheiro: Path, nome: str, *valores):
    """Corre a constante `nome` do TypeScript, tal como esta escrita."""
    q = ConsultaDoTypeScript(nome, ficheiro)
    cursor.execute(q.sql, q.args(*valores))
    return cursor


def com(cursor, nome: str, *valores) -> int:
    return correr(cursor, COM, nome, *valores).rowcount


class TestConteudo(ComBase):
    def test_o_sha256_da_base_e_o_do_kam088_byte_a_byte(self) -> None:
        casos = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(casos), 9)
        cursor = self.ligar("admin").cursor()
        for c in casos:
            with self.subTest(nome=c["nome"]):
                self.assertEqual(sha(cursor, c["categoria"], c["nome"]).hex(), c["sha256"])

    def test_e_estrita_e_imutavel(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute("SELECT platform.conteudo_sha256_do_produto(NULL, 'x')")
        self.assertIsNone(cursor.fetchone()[0])
        cursor.execute("SELECT provolatile, proisstrict FROM pg_proc WHERE proname = 'conteudo_sha256_do_produto'")
        self.assertEqual(tuple(cursor.fetchone()), ("i", True))


class _Oferta(ComBase):
    """Um tenant com a categoria `moda` decidida, numa transaccao so, que o ensaio desfaz."""

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.admin)
        decidir(self.admin, self.tenant, "categoria", "moda", "permitida")

    def produto(self, decisao: str | None, *, sku: str = "sku-1", nome: str = "Camisola de malha",
                estado: str = "rascunho", origem: str = "regra") -> str:
        oferta(self.admin, self.tenant, sku, nome, estado)
        if decisao is not None:
            decidir(self.admin, self.tenant, "produto", sku, decisao, origem=origem,
                    conteudo=sha(self.admin, "moda", nome))
        return sku

    def como(self, papel: str, tenant: str | None = None):
        """A mesma transaccao, com o papel e o contexto do tenant: ve o que o admin semeou."""
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, tenant or self.tenant)
        return self.admin


class TestPublicacao(_Oferta):
    """O `SQL_PUBLICAR` do COM, pela aplicacao."""

    def test_sem_decisao_zero_linhas_e_continua_rascunho(self) -> None:
        sku = self.produto(None)
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 0)
        self.assertEqual(estado_de(app, self.tenant, sku)[0], "rascunho")

    def test_com_permitida_publica(self) -> None:
        sku = self.produto("permitida")
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 1)
        self.assertEqual(estado_de(app, self.tenant, sku)[0], "publicado")

    def test_bloqueada_ou_condicional_nao_publicam_mesmo_com_uma_permitida_ao_lado(self) -> None:
        for decisao in ("bloqueada", "condicional"):
            with self.subTest(decisao=decisao):
                sku = self.produto("permitida", sku=f"sku-{decisao}")
                decidir(self.admin, self.tenant, "produto", sku, decisao,
                        conteudo=sha(self.admin, "moda", "Camisola de malha"))
                self.admin.execute("SAVEPOINT p")
                app = self.como("kamba_app")
                self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 0)
                self.admin.execute("ROLLBACK TO SAVEPOINT p")
                self.admin.execute("RESET ROLE")

    def test_o_recurso_humano_levanta_a_bloqueada_como_no_assert_publishable(self) -> None:
        sku = self.produto("bloqueada")
        decidir(self.admin, self.tenant, "produto", sku, "permitida", origem="humano",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 1)

    def test_a_decisao_de_outro_nome_de_outro_sku_ou_de_outro_tenant_nao_serve(self) -> None:
        sku = self.produto(None)
        decidir(self.admin, self.tenant, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola"))
        decidir(self.admin, self.tenant, "produto", "outro-sku", "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        outro = factories.tenant(self.admin)
        decidir(self.admin, outro, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 0)

    def test_mudar_a_categoria_declarada_muda_o_conteudo_e_a_decisao_antiga_deixa_de_valer(self) -> None:
        sku = self.produto("permitida")
        decidir(self.admin, self.tenant, "categoria", "bebidas", "permitida")
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 0)

    def test_uma_humana_numa_versao_antiga_nao_levanta_a_bloqueada_da_versao_do_motor(self) -> None:
        """Achado 2: a versao e a da decisao mais recente do motor, e nao a da linha mais recente.

        Em v1 o produto ficou `condicional` e foi a fila; em v2 o motor bloqueou-o; a
        T&S aprovou depois o caso antigo, com a versao dele. O `assertPublishable`
        em v2 da `bloqueada`, e a base tambem.
        """
        conteudo = sha(self.admin, "moda", "Camisola de malha")
        sku = self.produto(None)
        decidir(self.admin, self.tenant, "produto", sku, "condicional", conteudo=conteudo, versao="1.0.0+m.1")
        decidir(self.admin, self.tenant, "produto", sku, "bloqueada", conteudo=conteudo, versao="1.0.0+m.2")
        decidir(self.admin, self.tenant, "produto", sku, "permitida", origem="humano", conteudo=conteudo,
                versao="1.0.0+m.1")
        self.admin.execute("SELECT platform.oferta_publicavel(%s, %s, %s)", (self.tenant, sku, "Camisola de malha"))
        self.assertEqual(self.admin.fetchone()[0], "bloqueada")
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 0)

    def test_o_lote_que_ignora_a_rls_nao_le_a_decisao_nem_a_categoria_de_outro_tenant(self) -> None:
        """Achado 4: o `kamba_batch` tem `BYPASSRLS`, e ai o predicado de tenant e a unica barreira."""
        sku = self.produto(None)
        outro = factories.tenant(self.admin)
        decidir(self.admin, outro, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        lote = self.como("kamba_batch")
        self.assertEqual(com(lote, "SQL_PUBLICAR", self.tenant, sku), 0, "a decisao de outro tenant nao serve")
        self.admin.execute("RESET ROLE")
        # A categoria tambem e a do tenant: uma decisao de categoria mais recente
        # noutro tenant nao muda o conteudo deste.
        decidir(self.admin, self.tenant, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        decidir(self.admin, outro, "categoria", "bebidas", "permitida")
        lote = self.como("kamba_batch")
        self.assertEqual(com(lote, "SQL_PUBLICAR", self.tenant, sku), 1)

    def test_republicar_um_publicado_com_o_mesmo_nome_passa(self) -> None:
        sku = self.produto(None, estado="publicado")
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 1)

    def test_a_decisao_que_o_screen_grava_e_a_que_a_base_le(self) -> None:
        """O `SQL_GRAVAR` do KAM-088, pela aplicacao, com o resumo da funcao: publica."""
        sku = self.produto(None)
        conteudo = sha(self.admin, "moda", "Camisola de malha")
        app = self.como("kamba_app")
        correr(app, SCREENING, "SQL_GRAVAR", self.tenant, None, "produto", sku, "permitida", [],
               VERSAO, "regra", conteudo)
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 1)


class TestCaminhosDoCom(_Oferta):
    """Os caminhos de escrita do COM, pela aplicacao, sobre um publicado."""

    def test_os_termos_com_o_mesmo_nome_o_stock_e_o_preco_nao_tiram_de_publicado(self) -> None:
        sku = self.produto("permitida")
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 1)
        self.assertEqual(com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Camisola de malha", "fixo",
                             150000, None, "indicativo", AGORA, "moda"), 1)
        self.assertEqual(com(app, "SQL_AJUSTAR_STOCK", self.tenant, sku, "garantido"), 1)
        self.assertEqual(estado_de(app, self.tenant, sku), ("publicado", "Camisola de malha"))

    def test_um_nome_novo_sem_decisao_tira_de_publicado_sem_erro_e_o_returning_diz_o_estado(self) -> None:
        sku = self.produto("permitida")
        app = self.como("kamba_app")
        com(app, "SQL_PUBLICAR", self.tenant, sku)
        q = ConsultaDoTypeScript("SQL_ACTUALIZAR_TERMOS", COM)
        app.execute(q.sql, q.args(self.tenant, sku, "Whisky velho 12 anos", "fixo", 100000, None,
                                  "indicativo", AGORA, "moda"))
        colunas = [d[0] for d in app.description]
        linha = dict(zip(colunas, app.fetchone()))
        self.assertEqual(linha["estado"], "rascunho", "o COM le o estado de depois no RETURNING")
        self.assertEqual(estado_de(app, self.tenant, sku), ("rascunho", "Whisky velho 12 anos"))

    def test_um_nome_novo_com_decisao_permitida_continua_publicado(self) -> None:
        sku = self.produto("permitida")
        decidir(self.admin, self.tenant, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha azul"))
        app = self.como("kamba_app")
        com(app, "SQL_PUBLICAR", self.tenant, sku)
        com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Camisola de malha azul", "fixo",
            100000, None, "indicativo", AGORA, "moda")
        self.assertEqual(estado_de(app, self.tenant, sku), ("publicado", "Camisola de malha azul"))

    def test_o_rascunho_do_com_nasce_rascunho_sem_decisao(self) -> None:
        app = self.como("kamba_app")
        app.execute(
            f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor) "
            "VALUES (%s, 'sku-novo', 'Saia', 'fixo', 1000)", (self.tenant,))
        self.assertEqual(estado_de(app, self.tenant, "sku-novo")[0], "rascunho")

    def test_um_insert_ja_publicado_de_um_papel_de_servico_sem_decisao_recusa(self) -> None:
        for papel in ("kamba_app", "kamba_batch"):
            with self.subTest(papel=papel):
                app = self.como(papel)
                self.assertErroSql(VIOLACAO_DE_CHECK, app,
                                   f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, estado) "
                                   "VALUES (%s, 'sku-x', 'Vodka', 'fixo', 1000, 'publicado')", (self.tenant,))
                self.admin.execute("RESET ROLE")

    def test_o_dono_da_tabela_semeia_publicados_sem_decisao(self) -> None:
        oferta(self.admin, self.tenant, "semente", "produto semente", "publicado")
        self.assertEqual(estado_de(self.admin, self.tenant, "semente")[0], "publicado")

    def test_o_trigger_esta_sempre_ligado(self) -> None:
        self.admin.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = 'offer_terms_publicacao_segura'")
        self.assertEqual(self.admin.fetchone()[0], "A")


class _Conversa(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.admin)
        self.canal = factories.canal(self.admin, self.tenant)

    def conversa(self, *, teste: bool = False, inbound: datetime | None = None,
                 recebido: datetime | None = None, tenant: str | None = None) -> tuple[str, str]:
        tenant = tenant or self.tenant
        canal = self.canal if tenant == self.tenant else factories.canal(self.admin, tenant)
        contacto = factories.contacto(self.admin, tenant)
        self.admin.execute(
            "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id, last_inbound_at, "
            "window_expires_at) VALUES (%s, %s, %s, %s, %s) RETURNING id::text",
            (tenant, contacto, canal, inbound, None if inbound is None else inbound + D),
        )
        conversa = self.admin.fetchone()[0]
        if teste or recebido is not None:
            self.admin.execute(
                "UPDATE platform.conversations SET is_test = %s, teste_recebido_at = %s WHERE id = %s",
                (teste, recebido, conversa))
        return conversa, contacto

    def como(self, papel: str, tenant: str | None = None):
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, tenant or self.tenant)
        return self.admin


class TestSinalDoTeste(_Conversa):
    def test_a_coluna_e_um_instante_anulavel(self) -> None:
        self.admin.execute(
            "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'conversations' AND column_name = 'teste_recebido_at'")
        self.assertEqual(tuple(self.admin.fetchone()), ("timestamp with time zone", "YES", None))

    def test_a_aplicacao_grava_o_instante_pelo_sql_do_chr_e_nao_o_is_test(self) -> None:
        conversa, _ = self.conversa(inbound=AGORA)
        app = self.como("kamba_app")
        self.assertEqual(correr(app, CHR, "SQL_MARCAR_TESTE_RECEBIDO", self.tenant, conversa, AGORA).rowcount, 1)
        app.execute("SELECT teste_recebido_at FROM platform.conversations WHERE id = %s", (conversa,))
        self.assertEqual(app.fetchone()[0], AGORA)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           "UPDATE platform.conversations SET is_test = true WHERE id = %s", (conversa,))

    def test_o_observador_le_os_factos_pela_aplicacao(self) -> None:
        """Do sinal aos quatro factos, com o SQL do observador e o papel da aplicacao."""
        onb, tenant = caso(self.admin)
        # O caso em `aguarda_teste` ja tem o tenant provisionado (KAM-092).
        factories.tenant(self.admin, id=tenant)
        conversa, contacto = self.conversa(inbound=AGORA, recebido=AGORA, tenant=tenant)
        self.admin.execute(
            "INSERT INTO platform.agent_replies (tenant_id, chave, contact_id, conversation_id, canal, texto, "
            "criado_at) VALUES (%s, 'r1', %s, %s, 'whatsapp', 'Sou o assistente automatico de ensaio.', %s)",
            (tenant, contacto, conversa, AGORA + timedelta(seconds=5)))
        app = self.como("kamba_app", tenant)
        linhas = correr(app, OBSERVADOR, "SQL_FACTOS_DO_TESTE", onb, AGORA - D, AGORA + D).fetchall()
        self.assertEqual(len(linhas), 1)
        colunas = [d[0] for d in app.description]
        f = dict(zip(colunas, linhas[0]))
        self.assertEqual(f["conversation_id"], conversa)
        self.assertEqual(list(f["respostas"]), ["Sou o assistente automatico de ensaio."])
        self.assertIs(f["entregue"], False, "sem statuses ligados, nada escreve o delivered_at")
        self.assertIs(f["consentimento"], False, "sem ConsentGate montado, nada grava o consent_event")
        # Fora da janela, nada; e o caso de outro tenant nao ve esta conversa.
        self.assertEqual(len(correr(app, OBSERVADOR, "SQL_FACTOS_DO_TESTE", onb, AGORA + D, AGORA + 2 * D).fetchall()), 0)

    def test_o_observador_nao_ve_a_conversa_de_outro_tenant(self) -> None:
        """Como administrador, que ignora a RLS: o predicado do tenant do caso e que decide."""
        onb, _tenant = caso(self.admin)
        self.conversa(inbound=AGORA, recebido=AGORA)  # do tenant da classe, nao do caso
        self.assertEqual(len(correr(self.admin, OBSERVADOR, "SQL_FACTOS_DO_TESTE", onb, AGORA - D, AGORA + D).fetchall()), 0)

    def test_duas_conversas_com_o_teste_na_janela_nao_dao_nenhuma(self) -> None:
        """Achado 6: um cliente que escreve «teste» no mesmo minuto nao e marcado de teste."""
        onb, tenant = caso(self.admin)
        factories.tenant(self.admin, id=tenant)
        self.conversa(inbound=AGORA, recebido=AGORA, tenant=tenant)
        self.conversa(inbound=AGORA, recebido=AGORA + timedelta(seconds=3), tenant=tenant)
        app = self.como("kamba_app", tenant)
        self.assertEqual(len(correr(app, OBSERVADOR, "SQL_FACTOS_DO_TESTE", onb, AGORA - D, AGORA + D).fetchall()), 0)

    def test_o_consentimento_de_antes_da_janela_conta(self) -> None:
        """Achado 11: o aviso de 1.o contacto sai uma vez por contacto, e a repeticao nao tem outro."""
        onb, tenant = caso(self.admin)
        factories.tenant(self.admin, id=tenant)
        _, contacto = self.conversa(inbound=AGORA, recebido=AGORA, tenant=tenant)
        self.admin.execute(
            "INSERT INTO platform.consent_event (tenant_id, contact_id, purpose, text_version, accepted, canal, "
            "evidence_hash, registado_em) VALUES (%s, %s, 'atendimento', 'v1', true, 'whatsapp', %s, %s)",
            (tenant, contacto, hashlib.sha256(uuid.uuid4().bytes).digest(), AGORA - 30 * D))
        app = self.como("kamba_app", tenant)
        linhas = correr(app, OBSERVADOR, "SQL_FACTOS_DO_TESTE", onb, AGORA - D, AGORA + D).fetchall()
        colunas = [d[0] for d in app.description]
        self.assertIs(dict(zip(colunas, linhas[0]))["consentimento"], True)


class TestHumanoSoDoLote(_Oferta):
    def test_a_aplicacao_nao_grava_a_humana_e_grava_a_do_motor(self) -> None:
        conteudo = sha(self.admin, "moda", "Camisola de malha")
        app = self.como("kamba_app")
        q = ConsultaDoTypeScript("SQL_GRAVAR", SCREENING)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, q.sql,
                           q.args(self.tenant, None, "produto", "sku-1", "permitida", [], VERSAO, "humano", conteudo))
        correr(app, SCREENING, "SQL_GRAVAR", self.tenant, None, "produto", "sku-1", "permitida", [],
               VERSAO, "regra", conteudo)
        self.assertEqual(app.rowcount, 1)

    def test_o_lote_grava_a_humana(self) -> None:
        conteudo = sha(self.admin, "moda", "Camisola de malha")
        lote = self.como("kamba_batch")
        correr(lote, SCREENING, "SQL_GRAVAR", self.tenant, None, "produto", "sku-1", "permitida",
               ["revisao_humana"], VERSAO, "humano", conteudo)
        self.assertEqual(lote.rowcount, 1)

    def test_o_trigger_esta_sempre_ligado(self) -> None:
        self.admin.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = 'screening_decision_humano_so_do_lote'")
        self.assertEqual(self.admin.fetchone()[0], "A")


class TestTesteForaDasLeituras(_Conversa):
    """As cinco leituras do criterio 3, cada uma com uma conversa de teste que nao conta."""

    def ativo(self) -> None:
        factories.aceitar_contratos_vigentes(self.admin, self.tenant)
        self.admin.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (self.tenant,))
        self.admin.execute(
            "INSERT INTO platform.tenant_state_log (tenant_id, de, para, motivo, actor, em) "
            "VALUES (%s, 'onboarding', 'ativo', 'ensaio', 'ensaio', %s)", (self.tenant, AGORA - 100 * D))

    def sinais(self) -> set[str]:
        self.admin.execute(
            "SELECT sinal FROM platform.churn_sinais(%s, %s::jsonb) WHERE tenant_id = %s",
            (AGORA, json.dumps(LIMIARES), self.tenant))
        return {linha[0] for linha in self.admin.fetchall()}

    def test_o_churn_nao_conta_a_conversa_de_teste_como_cliente(self) -> None:
        self.ativo()
        self.conversa(teste=True, inbound=AGORA - 2 * D)
        self.assertIn("dormente", self.sinais(), "a conversa de teste nao e um cliente")
        self.conversa(inbound=AGORA - 2 * D)
        self.assertNotIn("dormente", self.sinais())

    def test_a_guarda_do_job_nao_conta_a_conversa_de_teste(self) -> None:
        self.conversa(teste=True, inbound=AGORA - 2 * D)
        self.admin.execute(churn.SQL_CLIENTES_NA_JANELA, (self.tenant, AGORA - 30 * D, AGORA))
        self.assertIs(self.admin.fetchone()[0], False)
        self.conversa(inbound=AGORA - 2 * D)
        self.admin.execute(churn.SQL_CLIENTES_NA_JANELA, (self.tenant, AGORA - 30 * D, AGORA))
        self.assertIs(self.admin.fetchone()[0], True)

    def _rascunho(self, contacto: str, decisao: str = "rejeitado") -> None:
        self.admin.execute(
            "INSERT INTO platform.draft_decisions (draft_id, tenant_id, thread_id, turn_seq, turn_id, "
            "graph_version, decisao, decidido_at) VALUES (%s, %s, %s, 0, 'wamid.HBgLensaio', '1.0.0', %s, %s)",
            (uuid.uuid4().hex * 2, self.tenant, f"{self.tenant}:{contacto}", decisao, AGORA))

    def test_a_vista_do_concierge_nao_conta_a_conversa_de_teste(self) -> None:
        _, de_teste = self.conversa(teste=True, inbound=AGORA)
        _, real = self.conversa(inbound=AGORA)
        self._rascunho(de_teste)
        self._rascunho(real)
        # Os dois papeis que a leem: o lote atravessa tenants, a auditoria le com
        # o contexto do tenant e precisa das tres colunas da conversa.
        for papel in ("kamba_batch", "kamba_audit"):
            with self.subTest(papel=papel):
                self.admin.execute("SAVEPOINT v")
                c = self.como(papel)
                c.execute("SELECT draft_total FROM platform.v_draft_metrics WHERE tenant_id = %s", (self.tenant,))
                self.assertEqual([tuple(x) for x in c.fetchall()], [(1,)])
                self.admin.execute("ROLLBACK TO SAVEPOINT v")

    def test_os_candidatos_a_golden_nao_contam_a_conversa_de_teste(self) -> None:
        _, de_teste = self.conversa(teste=True, inbound=AGORA)
        _, real = self.conversa(inbound=AGORA)
        self._rascunho(de_teste)
        self._rascunho(real)
        lote = self.como("kamba_batch")
        # O `SQL_CANDIDATOS` tal como esta escrito, sobre esta transaccao: o
        # desta classe e o unico tenant com rascunhos que ela ve a mais.
        lote.execute("SELECT count(*) FROM platform.draft_decisions WHERE decisao IN ('editado', 'rejeitado')")
        antes = int(lote.fetchone()[0])
        lote.execute(golden_candidates.SQL_CANDIDATOS, (antes + 10,))
        self.assertEqual(len(lote.fetchall()), antes - 1, "o rascunho da conversa de teste nao e candidato")

    def test_as_queixas_do_risco_nao_contam_a_conversa_de_teste(self) -> None:
        de_teste, _ = self.conversa(teste=True, inbound=AGORA)
        real, contacto_real = self.conversa(inbound=AGORA)
        for conversa in (de_teste, real):
            self.admin.execute(
                "INSERT INTO platform.events_log (event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
                "agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) VALUES "
                "(%s, 'query.handoff', 1, %s, 'conversation', %s, 1, %s, %s, 'nenhuma', %s::jsonb)",
                (str(uuid.uuid4()), self.tenant, conversa, AGORA, AGORA,
                 json.dumps({"payload": {"motivo": "reclamacao_grave"}})))
        app = self.como("kamba_app")
        linhas = correr(app, TRUST, "SQL_QUEIXAS", self.tenant, AGORA - D).fetchall()
        self.assertEqual([linha[0] for linha in linhas], [contacto_real])


class TestDowngradeDaPublicacaoSegura(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('conteudo_sha256_do_produto', "
                      "'oferta_publicavel', 'offer_terms_publicacao_segura', "
                      "'screening_decision_humano_so_do_lote')")
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                      "AND table_name = 'conversations' AND column_name = 'teste_recebido_at'")
            n += int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_views WHERE schemaname = 'platform' "
                      "AND viewname = 'v_draft_metrics' AND definition LIKE '%is_test%'")
            n += int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'churn_sinais' AND prosrc LIKE '%is_test%'")
            return n + int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._objectos(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), 7)
