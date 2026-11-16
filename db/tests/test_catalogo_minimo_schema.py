"""A revisao do catalogo minimo contra a base: publicacao segura, is_test e onboarding_smoke (KAM-094).

O que so uma base prova, e por isso este ficheiro existe:

1. **O `conteudo_sha256` da base e o do KAM-088**, byte a byte: a funcao SQL
   da os valores da fixture que o `conteudoSha256` de TypeScript tambem tem de
   dar (`packages/core-ts/tests/activacao.test.ts`), com os casos dificeis do
   escape de JSON.
2. **A publicacao e protegida pela base**, com o SQL do COM tal como esta
   escrito e pela ligacao da aplicacao: sem decisao, com `bloqueada`, com
   `condicional`, com a decisao de outro nome, de outro `sku` ou de outro
   tenant, o `SQL_PUBLICAR` afecta zero linhas — e com `permitida`, ou com o
   recurso humano, publica.
3. **Cada caminho de escrita do COM continua a passar**: o rascunho, os termos
   com o mesmo nome, o stock, o preco, a republicacao. E o nome novo num
   publicado sem decisao tira-o de `publicado` (criterio 3), sem `23514`.
4. **O dono da tabela fica de fora**, e as sementes dele continuam a inserir
   ofertas ja publicadas.
5. **A `conversations.is_test`**, e quem a pode escrever.
6. **A `onboarding_smoke`**: a aplicacao abre e so o lote fecha; a tentativa
   fechada nao muda; as restricoes; o SQL do `activacao/sql.ts`; RLS.
7. **O SQL dos gates e da maquina** do `activacao/sql.ts`.
8. **O `downgrade`.**
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    ComBase,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "packages" / "core-ts" / "tests" / "fixtures" / "conteudo_sha256.json"
CONTRATO = RAIZ / "packages" / "core-ts" / "src" / "activacao" / "contrato.ts"
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "activacao" / "sql.ts"
COM = RAIZ / "services" / "com" / "src" / "produtos" / "consultas.ts"
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_catalogo_minimo_e_teste.py"))

OFERTA = "platform.offer_terms"
DECISAO = "platform.screening_decision"
TENTATIVA = "platform.onboarding_smoke"
CASO = "platform.onboarding_case"
VERSAO = "1.0.0+m.2"
ESTADO_INVALIDO = "55000"

AGORA = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def _lista_ts(nome: str) -> tuple[str, ...]:
    texto = CONTRATO.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {CONTRATO.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def sha(cursor, categoria: str, nome: str) -> bytes:
    cursor.execute("SELECT platform.conteudo_sha256_do_produto(%s, %s)", (categoria, nome))
    return bytes(cursor.fetchone()[0])


def decidir(cursor, tenant: str, sujeito_tipo: str, ref: str, decisao: str, *,
            origem: str = "regra", conteudo: bytes | None = None) -> None:
    cursor.execute(
        f"INSERT INTO {DECISAO} (tenant_id, sujeito_tipo, sujeito_ref, decisao, regras, "
        "versao_politica, origem, conteudo_sha256) VALUES (%s, %s, %s, %s, ARRAY[]::text[], %s, %s, %s)",
        (tenant, sujeito_tipo, ref, decisao, VERSAO, origem,
         conteudo if conteudo is not None else hashlib.sha256(ref.encode()).digest()),
    )


def oferta(cursor, tenant: str, sku: str, nome: str, estado: str = "rascunho") -> None:
    cursor.execute(
        f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, estado) "
        "VALUES (%s, %s, %s, 'fixo', 100000, %s)",
        (tenant, sku, nome, estado),
    )


def estado_de(cursor, tenant: str, sku: str) -> tuple[str, str]:
    cursor.execute(f"SELECT estado, nome FROM {OFERTA} WHERE tenant_id = %s AND sku = %s", (tenant, sku))
    linha = cursor.fetchone()
    return linha[0], linha[1]


def com(cursor, nome: str, *valores) -> int:
    """Corre a constante `nome` do COM, tal como esta escrita, e devolve as linhas afectadas."""
    q = ConsultaDoTypeScript(nome, COM)
    cursor.execute(q.sql, q.args(*valores))
    return cursor.rowcount


def activacao(cursor, nome: str, *valores):
    q = ConsultaDoTypeScript(nome, SQL_TS)
    cursor.execute(q.sql, q.args(*valores))
    return cursor


def caso(cursor, fase: str = "aguarda_teste") -> tuple[str, str]:
    """Um caso minimo na `fase`. Devolve `(id, tenant_id)`."""
    cursor.execute(
        f"INSERT INTO {CASO} (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, "
        "phone_enc, phone_hmac) VALUES (%s, 'convite', 'negocio de ensaio', 'moda', '\\x01', %s, '\\x02', %s) "
        "RETURNING id::text, tenant_id::text",
        (fase, hashlib.sha256(uuid.uuid4().bytes).digest(), hashlib.sha256(uuid.uuid4().bytes).digest()),
    )
    linha = cursor.fetchone()
    return linha[0], linha[1]


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

    def como(self, papel: str):
        """A mesma transaccao, com o papel e o contexto do tenant: ve o que o admin semeou."""
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, self.tenant)
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
        # Outro nome (o titulo neutro que se decidiu, e nao o que se publica).
        decidir(self.admin, self.tenant, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola"))
        # Outro sku, com o mesmo conteudo.
        decidir(self.admin, self.tenant, "produto", "outro-sku", "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        # Outro tenant, com o mesmo sku e o mesmo conteudo.
        outro = factories.tenant(self.admin)
        decidir(self.admin, outro, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        self.admin.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 0)

    def test_mudar_a_categoria_declarada_muda_o_conteudo_e_a_decisao_antiga_deixa_de_valer(self) -> None:
        sku = self.produto("permitida")
        decidir(self.admin, self.tenant, "categoria", "bebidas", "permitida")
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 0)

    def test_republicar_um_publicado_com_o_mesmo_nome_passa(self) -> None:
        sku = self.produto(None, estado="publicado")
        self.assertEqual(com(self.como("kamba_app"), "SQL_PUBLICAR", self.tenant, sku), 1)


class TestCaminhosDoCom(_Oferta):
    """Os caminhos de escrita do COM, pela aplicacao, sobre um publicado."""

    def test_os_termos_com_o_mesmo_nome_o_stock_e_o_preco_nao_tiram_de_publicado(self) -> None:
        sku = self.produto("permitida")
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 1)
        self.assertEqual(com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Camisola de malha", "fixo",
                             150000, None, "indicativo", AGORA), 1)
        self.assertEqual(com(app, "SQL_AJUSTAR_STOCK", self.tenant, sku, "garantido"), 1)
        app.execute(f"SELECT atualizado_at FROM {OFERTA} WHERE tenant_id = %s AND sku = %s", (self.tenant, sku))
        versao = app.fetchone()[0]
        self.assertEqual(com(app, "SQL_ALTERAR_OFERTA", self.tenant, sku, "fixo", 160000,
                             versao.isoformat(), True), 1)
        self.assertEqual(estado_de(app, self.tenant, sku), ("publicado", "Camisola de malha"))

    def test_um_nome_novo_sem_decisao_tira_de_publicado_sem_erro(self) -> None:
        sku = self.produto("permitida")
        app = self.como("kamba_app")
        com(app, "SQL_PUBLICAR", self.tenant, sku)
        self.assertEqual(com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Whisky velho 12 anos", "fixo",
                             100000, None, "indicativo", AGORA), 1, "a escrita do COM passa")
        self.assertEqual(estado_de(app, self.tenant, sku), ("rascunho", "Whisky velho 12 anos"))

    def test_um_nome_novo_com_decisao_permitida_continua_publicado(self) -> None:
        sku = self.produto("permitida")
        decidir(self.admin, self.tenant, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha azul"))
        app = self.como("kamba_app")
        com(app, "SQL_PUBLICAR", self.tenant, sku)
        com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Camisola de malha azul", "fixo",
            100000, None, "indicativo", AGORA)
        self.assertEqual(estado_de(app, self.tenant, sku), ("publicado", "Camisola de malha azul"))

    def test_o_rascunho_do_com_nasce_rascunho_sem_decisao(self) -> None:
        app = self.como("kamba_app")
        app.execute(
            f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor) "
            "VALUES (%s, 'sku-novo', 'Saia', 'fixo', 1000)", (self.tenant,))
        self.assertEqual(estado_de(app, self.tenant, "sku-novo")[0], "rascunho")

    def test_um_insert_ja_publicado_de_um_papel_de_servico_sem_decisao_recusa(self) -> None:
        app = self.como("kamba_app")
        self.assertErroSql(VIOLACAO_DE_CHECK, app,
                           f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, estado) "
                           "VALUES (%s, 'sku-x', 'Vodka', 'fixo', 1000, 'publicado')", (self.tenant,))

    def test_o_dono_da_tabela_semeia_publicados_sem_decisao(self) -> None:
        oferta(self.admin, self.tenant, "semente", "produto semente", "publicado")
        self.assertEqual(estado_de(self.admin, self.tenant, "semente")[0], "publicado")

    def test_o_trigger_esta_sempre_ligado(self) -> None:
        self.admin.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = 'offer_terms_publicacao_segura'")
        self.assertEqual(self.admin.fetchone()[0], "A")


class TestConversaDeTeste(ComBase):
    def test_a_coluna_nasce_falsa_e_nao_nula(self) -> None:
        [(tipo, anulavel, omissao)] = self.consultar(
            "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'conversations' AND column_name = 'is_test'")
        self.assertEqual((tipo, anulavel, omissao), ("boolean", "NO", "false"))

    def test_o_lote_marca_e_a_aplicacao_nao(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        canal = factories.canal(admin, tenant)
        contacto = factories.contacto(admin, tenant)
        admin.execute(
            "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id) VALUES (%s, %s, %s) "
            "RETURNING id::text", (tenant, contacto, canal))
        conversa = admin.fetchone()[0]
        admin.execute("SAVEPOINT a")
        admin.execute("SET LOCAL ROLE kamba_app")
        factories.contexto(admin, tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, admin,
                           "UPDATE platform.conversations SET is_test = true WHERE id = %s", (conversa,))
        admin.execute("ROLLBACK TO SAVEPOINT a")
        admin.execute("SET LOCAL ROLE kamba_batch")
        factories.contexto(admin, tenant)
        activacao(admin, "SQL_MARCAR_CONVERSA_DE_TESTE", tenant, conversa)
        self.assertEqual(admin.rowcount, 1)
        admin.execute("SELECT is_test FROM platform.conversations WHERE id = %s", (conversa,))
        self.assertIs(admin.fetchone()[0], True)


class TestTentativas(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()
        self.onb, self.tenant = caso(self.admin)

    def _papel(self, papel: str, tenant: str | None = None):
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, tenant or self.tenant)
        return self.admin

    def _iniciar(self, inicio: datetime) -> None:
        self._papel("kamba_app")
        activacao(self.admin, "SQL_INICIAR_TENTATIVA", self.onb, inicio, inicio + timedelta(seconds=60))
        self.admin.execute("RESET ROLE")

    def _fechar(self, resultado: str, causa: str | None) -> int:
        self._papel("kamba_batch")
        n = activacao(self.admin, "SQL_FECHAR_TENTATIVA", self.onb, resultado, causa).rowcount
        self.admin.execute("RESET ROLE")
        return n

    def _falhas(self) -> int:
        self._papel("kamba_batch")
        n = int(activacao(self.admin, "SQL_FALHAS_SEGUIDAS", self.onb).fetchone()[0])
        self.admin.execute("RESET ROLE")
        return n

    def test_os_dominios_sao_os_do_contrato(self) -> None:
        self.admin.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'onboarding_smoke_causa_ck'")
        self.assertEqual(tuple(sorted(re.findall(r"'([a-z_]+)'", self.admin.fetchone()[0]))),
                         tuple(sorted(_lista_ts("CAUSAS_DO_TESTE"))))

    def test_a_aplicacao_abre_pendente_e_nao_escreve_o_resultado(self) -> None:
        self._iniciar(AGORA)
        self.admin.execute(f"SELECT resultado, causa, fechada_em FROM {TENTATIVA} WHERE onboarding_id = %s", (self.onb,))
        self.assertEqual(tuple(self.admin.fetchone()), ("pendente", None, None))
        app = self._papel("kamba_app")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em, resultado, fechada_em) "
                           "VALUES (%s, %s, now() + interval '1 minute', 'ok', now())", (self.onb, self.tenant))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"UPDATE {TENTATIVA} SET resultado = 'ok', fechada_em = now() WHERE onboarding_id = %s",
                           (self.onb,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, f"DELETE FROM {TENTATIVA} WHERE onboarding_id = %s", (self.onb,))

    def test_o_lote_fecha_e_a_tentativa_fechada_nao_muda(self) -> None:
        self._iniciar(AGORA)
        self.assertEqual(self._fechar("falhou", "sem_inbound"), 1)
        self.assertEqual(self._fechar("ok", None), 0, "so a pendente se fecha")
        lote = self._papel("kamba_batch")
        self.assertErroSql(ESTADO_INVALIDO, lote,
                           f"UPDATE {TENTATIVA} SET resultado = 'ok', causa = NULL WHERE onboarding_id = %s", (self.onb,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote, f"DELETE FROM {TENTATIVA} WHERE onboarding_id = %s", (self.onb,))

    def test_as_restricoes(self) -> None:
        for sql, args in (
            (f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em) VALUES (%s, %s, now() + interval '11 minutes')", ()),
            (f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em) VALUES (%s, %s, now())", ()),
            (f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em, causa) VALUES (%s, %s, now() + interval '1 minute', 'sem_inbound')", ()),
            (f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em, resultado) VALUES (%s, %s, now() + interval '1 minute', 'ok')", ()),
            (f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em, resultado, fechada_em, levou_a_fila) VALUES (%s, %s, now() + interval '1 minute', 'ok', now(), true)", ()),
            (f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em, resultado, causa, fechada_em) VALUES (%s, %s, now() + interval '1 minute', 'falhou', 'sem_rede', now())", ()),
        ):
            with self.subTest(sql=sql):
                self.assertErroSql(VIOLACAO_DE_CHECK, self.admin, sql, (self.onb, self.tenant) + args)

    def test_o_caso_de_um_com_o_tenant_de_outro_e_recusado(self) -> None:
        _, outro = caso(self.admin)
        self.assertErroSql(VIOLACAO_DE_FK, self.admin,
                           f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em) "
                           "VALUES (%s, %s, now() + interval '1 minute')", (self.onb, outro))

    def test_as_falhas_seguidas_recomecam_num_ok_e_na_ida_a_fila(self) -> None:
        for i, (resultado, causa) in enumerate((("falhou", "sem_inbound"), ("falhou", "sem_resposta"),
                                                ("ok", None), ("falhou", "sem_entrega"))):
            self._iniciar(AGORA + timedelta(minutes=i))
            self._fechar(resultado, causa)
        self.assertEqual(self._falhas(), 1)
        self._iniciar(AGORA + timedelta(minutes=10))
        self._fechar("falhou", "sem_inbound")
        self.assertEqual(self._falhas(), 2)
        self._papel("kamba_batch")
        self.assertEqual(activacao(self.admin, "SQL_ZERAR_FALHAS", self.onb).rowcount, 1)
        self.admin.execute("RESET ROLE")
        self.assertEqual(self._falhas(), 0)
        lote = self._papel("kamba_batch")
        self.assertErroSql(ESTADO_INVALIDO, lote,
                           f"UPDATE {TENTATIVA} SET levou_a_fila = false WHERE onboarding_id = %s", (self.onb,))

    def test_a_corrente_e_a_mais_recente(self) -> None:
        self._iniciar(AGORA)
        self._fechar("falhou", "sem_inbound")
        self._iniciar(AGORA + timedelta(minutes=5))
        app = self._papel("kamba_app")
        linha = activacao(app, "SQL_TENTATIVA_CORRENTE", self.onb).fetchone()
        self.assertEqual(linha[3], "pendente")

    def test_rls_forcada_e_b_nao_ve_nem_escreve_a_tentativa_de_a(self) -> None:
        [(ligada, forcada)] = self.consultar(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (TENTATIVA,))
        self.assertEqual((ligada, forcada), (True, True))
        self._iniciar(AGORA)
        b = str(uuid.uuid4())
        app = self._papel("kamba_app", b)
        app.execute(f"SELECT count(*) FROM {TENTATIVA} WHERE onboarding_id = %s", (self.onb,))
        self.assertEqual(app.fetchone()[0], 0)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"INSERT INTO {TENTATIVA} (onboarding_id, tenant_id, expira_em) "
                           "VALUES (%s, %s, now() + interval '1 minute')", (self.onb, self.tenant))
        app = self._papel("kamba_app")
        app.execute(f"SELECT count(*) FROM {TENTATIVA} WHERE onboarding_id = %s", (self.onb,))
        self.assertEqual(app.fetchone()[0], 1)


class TestSqlDaActivacao(ComBase):
    """O SQL dos gates, da maquina, do catalogo e da categoria, como o `activacao/sql.ts` o escreve."""

    def test_gates_e_maquina_ate_aguarda_teste(self) -> None:
        admin = self.ligar("admin").cursor()
        onb, tenant = caso(admin, "aguarda_catalogo")
        admin.execute("SET LOCAL ROLE kamba_batch")
        factories.contexto(admin, tenant)
        activacao(admin, "SQL_MARCAR_GATE", onb, "catalogo_minimo", False, "elegiveis:4/5")
        activacao(admin, "SQL_MARCAR_GATE", onb, "catalogo_minimo", True, "elegiveis:5/5")
        em_falta = activacao(admin, "SQL_GATES_EM_FALTA", onb).fetchone()[0]
        self.assertNotIn("catalogo_minimo", em_falta)
        self.assertIn("e2e", em_falta)
        self.assertEqual(activacao(admin, "SQL_AVANCAR", onb, "catalogo_minimo", "kamba_batch:activacao").fetchone()[0],
                         "aguarda_teste")
        self.assertEqual(activacao(admin, "SQL_LER_CASO", onb).fetchone()[2], "aguarda_teste")

    def test_os_produtos_com_a_confirmacao_da_ingestao_e_a_categoria_declarada(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        decidir(admin, tenant, "categoria", "moda", "permitida")
        oferta(admin, tenant, "sku-a", "Camisola", "publicado")
        oferta(admin, tenant, "sku-b", "Saia", "publicado")
        admin.execute(
            "INSERT INTO platform.catalog_ingestions (tenant_id, media_ref, estado, extraido, sku, "
            "confirmado_at, confirmado_por) VALUES (%s, %s, 'rascunho', %s, 'sku-a', NULL, NULL) RETURNING id",
            (tenant, f"t/{tenant}/catalogo/2026/11/{uuid.uuid4()}",
             json.dumps({"categoria": {"valor": "roupa"}})))
        ingestao = admin.fetchone()[0]
        admin.execute(
            "UPDATE platform.catalog_ingestions SET estado = 'publicada', confirmado_at = now(), "
            "confirmado_por = 'mensagem de ensaio' WHERE id = %s", (ingestao,))
        # Pela aplicacao: o `kamba_batch` nao le a `catalog_ingestions` (0050).
        admin.execute("SET LOCAL ROLE kamba_app")
        factories.contexto(admin, tenant)
        linhas = {l[1]: l for l in activacao(admin, "SQL_PRODUTOS", tenant).fetchall()}
        self.assertEqual((linhas["sku-a"][7], linhas["sku-a"][8]), ("roupa", True))
        self.assertEqual((linhas["sku-b"][7], linhas["sku-b"][8]), (None, False))
        self.assertEqual(activacao(admin, "SQL_CATEGORIA_DECLARADA", tenant).fetchone()[0], "moda")


class TestDowngradeDoCatalogoMinimo(unittest.TestCase):
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
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' AND tablename = 'onboarding_smoke'")
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('conteudo_sha256_do_produto', "
                      "'oferta_publicavel', 'offer_terms_publicacao_segura', 'onboarding_smoke_transicao')")
            n += int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                      "AND table_name = 'conversations' AND column_name = 'is_test'")
            return n + int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._objectos(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), 6)


if __name__ == "__main__":
    unittest.main()
