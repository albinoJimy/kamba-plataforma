"""A revisao do screening contra a base: screening_decision (KAM-088).

O que so uma base prova, e por isso este ficheiro existe:

1. **As listas fechadas sao as do codigo.** A `decisao`, a `origem` e o
   `sujeito_tipo` contra o `packages/core-ts/src/screening/tipos.ts`.
2. **A ordem das decisoes e a do `criado_at`, e ele avanca dentro da mesma
   transaccao** (F17 da revisao adversarial): com `now()`, duas decisoes na
   mesma transaccao empatavam e o `id` aleatorio decidia qual valia.
3. **Append-only, tambem para o dono**: a aplicacao nao tem `UPDATE` nem
   `DELETE`, e o *trigger* recusa-os ao administrador.
4. **As restricoes**: a FK composta que impede o caso de um com o tenant de
   outro, o resumo de 32 octetos, a versao com o metadado do motor.
5. **O SQL do modulo de TypeScript**, executado tal como esta escrito: gravar,
   ler as decisoes de uma chave pela ordem, e os produtos por re-analisar com a
   categoria declarada mais recente.
6. **RLS pela ligacao da aplicacao**: um tenant nao ve nem escreve o de outro.
7. **O `downgrade`**, o da `0044` e o da revisao do sujeito das condicoes
   (KAM-222), que apaga as decisoes `condicoes` e repoe o dominio de dois.
8. **O emissor da violacao** (KAM-191): o `SQL_EMITIR_VIOLACAO` na transaccao
   da decisao, o envelope contra o contrato `v1`, e a decisao desfeita quando a
   escrita no *outbox* e recusada.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unittest
import uuid
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
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
TIPOS = RAIZ / "packages" / "core-ts" / "src" / "screening" / "tipos.ts"
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "screening" / "sql.ts"

EMISSOR_TS = RAIZ / "packages" / "core-ts" / "src" / "screening" / "emissor.ts"
#: A operacao do `screen` do COM (KAM-222), que le a categoria declarada do tenant.
SCREEN_DO_COM_TS = RAIZ / "services" / "com" / "src" / "screening" / "index.ts"
#: A revisao do sujeito das condicoes (KAM-222). Por *glob* e nao pelo numero, e o
#: `down_revision` le-se dela: muda na integracao, e o ensaio segue-o.
REVISAO_DAS_CONDICOES = next(
    (RAIZ / "db" / "migrations" / "versions").glob("*_sujeito_das_condicoes.py")
)
TIPO_VIOLACAO = "screening.violation_detected"
CONTRATO_V1 = RAIZ / "contratos" / "eventos" / TIPO_VIOLACAO / "v1.schema.json"

TABELA = "platform.screening_decision"
VERSAO = "1.0.0+m.2"
#: O `RAISE` do *trigger* de imutabilidade (`object_not_in_prerequisite_state`).
RECUSADO_PELO_TRIGGER = "55000"


def _lista_ts(nome: str) -> tuple[str, ...]:
    texto = TIPOS.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {TIPOS.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def _dominio(cursor, restricao: str) -> tuple[str, ...]:
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
        (restricao,),
    )
    return tuple(sorted(re.findall(r"'([a-z0-9_]+)'", cursor.fetchone()[0])))


def _sha(texto: str) -> bytes:
    return hashlib.sha256(texto.encode("utf-8")).digest()


def gravar(cursor, tenant_id: str, **campos) -> None:
    """Uma decisao pelo `SQL_GRAVAR` do modulo, na numeracao dele."""
    valores = {
        "tenant_id": tenant_id,
        "onboarding_id": None,
        "sujeito_tipo": "produto",
        "sujeito_ref": "sku-1",
        "decisao": "permitida",
        "regras": ["moda"],
        "versao_politica": VERSAO,
        "origem": "regra",
        "conteudo_sha256": _sha("camisola"),
    }
    valores.update(campos)
    q = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
    cursor.execute(q.sql, q.args(*valores.values()))


def _base32(resumo: bytes) -> str:
    """O `sha256EmBase32` do `emissor.ts`, pela biblioteca padrao: RFC 4648."""
    return base64.b32encode(resumo).decode("ascii").lower().rstrip("=")


def caso(cursor) -> tuple[str, str]:
    """Um caso de onboarding minimo. Devolve `(id, tenant_id)`."""
    cursor.execute(
        "INSERT INTO platform.onboarding_case "
        "(origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac) "
        "VALUES ('convite', 'negocio de ensaio', 'moda', '\\x01', %s, '\\x02', %s) "
        "RETURNING id::text, tenant_id::text",
        (_sha(str(uuid.uuid4())), _sha(str(uuid.uuid4()))),
    )
    linha = cursor.fetchone()
    return linha[0], linha[1]


class TestDominios(ComBase):
    def test_os_dominios_sao_os_do_modulo(self) -> None:
        cursor = self.ligar("admin").cursor()
        self.assertEqual(
            _dominio(cursor, "screening_decision_decisao_ck"), tuple(sorted(_lista_ts("DECISOES")))
        )
        self.assertEqual(
            _dominio(cursor, "screening_decision_origem_ck"), tuple(sorted(_lista_ts("ORIGENS")))
        )
        self.assertEqual(
            _dominio(cursor, "screening_decision_sujeito_tipo_ck"),
            tuple(sorted(_lista_ts("SUJEITOS"))),
        )

    def test_o_criado_at_e_do_relogio_e_nao_da_transaccao(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        for decisao in ("condicional", "bloqueada", "permitida"):
            gravar(cursor, tenant, decisao=decisao)
        cursor.execute(
            f"SELECT count(DISTINCT criado_at) FROM {TABELA} WHERE tenant_id = %s", (tenant,)
        )
        self.assertEqual(cursor.fetchone()[0], 3)
        q = ConsultaDoTypeScript("SQL_DECISOES", SQL_TS)
        cursor.execute(q.sql, q.args(tenant, "produto", "sku-1", VERSAO, _sha("camisola")))
        self.assertEqual(
            [tuple(l) for l in cursor.fetchall()],
            [("condicional", "regra"), ("bloqueada", "regra"), ("permitida", "regra")],
        )


class TestRestricoes(ComBase):
    def test_o_resumo_tem_32_octetos(self) -> None:
        cursor = self.ligar("admin").cursor()
        q = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
        args = q.args(
            str(uuid.uuid4()), None, "produto", "s", "permitida", ["x"], VERSAO, "regra", b"\x00" * 31
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, q.sql, args)

    def test_a_versao_leva_o_metadado_do_motor(self) -> None:
        cursor = self.ligar("admin").cursor()
        q = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
        for versao in ("1.0.0", "1.0", "1.0.0+", "v1.0.0+m.2"):
            with self.subTest(versao=versao):
                args = q.args(
                    str(uuid.uuid4()), None, "produto", "s", "permitida", ["x"], versao, "regra",
                    _sha("x"),
                )
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, q.sql, args)
        gravar(cursor, str(uuid.uuid4()), versao_politica="1.0.0+t.0a1b2c3d.m.2")

    def test_a_referencia_nao_e_vazia(self) -> None:
        cursor = self.ligar("admin").cursor()
        q = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
        args = q.args(
            str(uuid.uuid4()), None, "categoria", "", "permitida", ["x"], VERSAO, "regra", _sha("x")
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, q.sql, args)

    def test_o_caso_tem_de_ser_do_tenant_da_linha(self) -> None:
        cursor = self.ligar("admin").cursor()
        onboarding_id, tenant_do_caso = caso(cursor)
        gravar(cursor, tenant_do_caso, onboarding_id=onboarding_id, sujeito_tipo="categoria",
               sujeito_ref="moda")
        q = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
        args = q.args(
            str(uuid.uuid4()), onboarding_id, "categoria", "moda", "permitida", ["moda"], VERSAO,
            "regra", _sha("moda"),
        )
        self.assertErroSql(VIOLACAO_DE_FK, cursor, q.sql, args)


class TestAppendOnly(ComBase):
    def test_ninguem_emenda_nem_apaga(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        gravar(admin, tenant, decisao="bloqueada", regras=["armas"])
        self.assertErroSql(
            RECUSADO_PELO_TRIGGER, admin,
            f"UPDATE {TABELA} SET decisao = 'permitida' WHERE tenant_id = %s", (tenant,),
        )
        self.assertErroSql(
            RECUSADO_PELO_TRIGGER, admin, f"DELETE FROM {TABELA} WHERE tenant_id = %s", (tenant,)
        )
        app = self.ligar("app").cursor()
        factories.contexto(app, tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app, f"UPDATE {TABELA} SET decisao = 'permitida'"
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, f"DELETE FROM {TABELA}")


class TestAplicacao(ComBase):
    def test_a_aplicacao_escreve_no_seu_tenant_e_nao_ve_o_dos_outros(self) -> None:
        app = self.ligar("app").cursor()
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        factories.contexto(app, a)
        gravar(app, a)
        q = ConsultaDoTypeScript("SQL_DECISOES", SQL_TS)
        app.execute(q.sql, q.args(a, "produto", "sku-1", VERSAO, _sha("camisola")))
        self.assertEqual([tuple(l) for l in app.fetchall()], [("permitida", "regra")])
        factories.contexto(app, b)
        app.execute(q.sql, q.args(a, "produto", "sku-1", VERSAO, _sha("camisola")))
        self.assertEqual(list(app.fetchall()), [])
        q_gravar = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
        args = q_gravar.args(
            a, None, "produto", "sku-2", "permitida", ["moda"], VERSAO, "regra", _sha("x")
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, q_gravar.sql, args)


class TestReanalise(ComBase):
    def test_o_lote_ve_os_publicados_sem_decisao_com_a_categoria_mais_recente(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        for sku, estado in (("ja-decidido", "publicado"), ("por-decidir", "publicado"),
                            ("rascunho", "rascunho")):
            admin.execute(
                "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, estado) "
                "VALUES (%s, %s, %s, 'fixo', 100, %s)",
                (tenant, sku, f"produto {sku}", estado),
            )
        gravar(admin, tenant, sujeito_ref="ja-decidido")
        gravar(admin, tenant, sujeito_tipo="categoria", sujeito_ref="moda")
        gravar(admin, tenant, sujeito_tipo="categoria", sujeito_ref="electronica")
        q = ConsultaDoTypeScript("SQL_POR_REANALISAR", SQL_TS)
        admin.execute(q.sql, q.args(VERSAO, 100))
        linhas = [tuple(l) for l in admin.fetchall() if l[0] == tenant]
        self.assertEqual(linhas, [(tenant, "por-decidir", "produto por-decidir", "electronica")])
        # Outra versao da politica: os dois publicados voltam a precisar de decisao.
        admin.execute(q.sql, q.args("1.1.0+m.2", 100))
        skus = sorted(l[1] for l in admin.fetchall() if l[0] == tenant)
        self.assertEqual(skus, ["ja-decidido", "por-decidir"])


class TestCategoriaDoTenantDoCom(ComBase):
    """KAM-222: o `SQL_CATEGORIA_DO_TENANT` le a ultima decisao `categoria` do tenant.

    E a categoria com que o COM faz o `screen` das condicoes de um orcamento. A
    ordem e o filtro do sujeito so se medem aqui: o duplo do `screening.test.ts`
    nao corre SQL.
    """

    def test_a_ultima_categoria_e_so_a_categoria_e_so_deste_tenant(self) -> None:
        # Tudo pela mesma ligacao da aplicacao, como o COM: o `kamba_app` grava
        # no seu tenant e le com a RLS.
        app = self.ligar("app").cursor()
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        factories.contexto(app, a)
        gravar(app, a, sujeito_tipo="categoria", sujeito_ref="moda")
        gravar(app, a, sujeito_tipo="categoria", sujeito_ref="electronica")
        # Depois da ultima categoria: uma decisao de produto e outra de outro
        # tenant. Nenhuma das duas pode passar por categoria deste.
        gravar(app, a, sujeito_tipo="produto", sujeito_ref="sku-depois")
        factories.contexto(app, b)
        gravar(app, b, sujeito_tipo="categoria", sujeito_ref="servicos")
        q = ConsultaDoTypeScript("SQL_CATEGORIA_DO_TENANT", SCREEN_DO_COM_TS)
        factories.contexto(app, a)
        app.execute(q.sql, q.args(a))
        self.assertEqual([tuple(l) for l in app.fetchall()], [("electronica",)])
        # Com o contexto de B, a RLS nao deixa ler as de A.
        factories.contexto(app, b)
        app.execute(q.sql, q.args(a))
        self.assertEqual(list(app.fetchall()), [])


class TestViolacao(ComBase):
    """KAM-191: o `SQL_EMITIR_VIOLACAO` do `emissor.ts`, na transaccao da decisao.

    O que so a base prova: o `evt_emitir` escreve no *outbox* **dentro** da
    transaccao de quem chama — a decisao e o evento confirmam ou desfazem-se
    juntos —, o envelope que ele constroi e o que o contrato `v1` descreve, e
    uma escrita recusada aborta a transaccao com a decisao dentro.
    """

    def _emitir(
        self, cursor, tenant: str, sku: str = "sku-1", resumo: str | None = None
    ) -> tuple[str, dict]:
        payload = {
            "sku": sku,
            "regras": ["armas"],
            "versao_politica": VERSAO,
            "sha256": _base32(_sha("camisola")) if resumo is None else resumo,
        }
        q = ConsultaDoTypeScript("SQL_EMITIR_VIOLACAO", EMISSOR_TS)
        cursor.execute(
            q.sql,
            q.args(TIPO_VIOLACAO, 1, tenant, "product", sku, json.dumps(payload), "P0", ["transacao"]),
        )
        return str(cursor.fetchone()[0]), payload

    def _contar(self, tenant: str) -> tuple[int, int]:
        admin = self.ligar("admin").cursor()
        admin.execute(f"SELECT count(*) FROM {TABELA} WHERE tenant_id = %s", (tenant,))
        decisoes = admin.fetchone()[0]
        admin.execute(
            "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s AND tipo = %s",
            (tenant, TIPO_VIOLACAO),
        )
        return decisoes, admin.fetchone()[0]

    def test_a_bloqueada_e_o_evento_ficam_na_mesma_transaccao(self) -> None:
        import jsonschema

        conexao = self.ligar("app")
        app = conexao.cursor()
        tenant = str(uuid.uuid4())
        factories.contexto(app, tenant)
        gravar(app, tenant, decisao="bloqueada", regras=["armas"])
        event_id, payload = self._emitir(app, tenant)

        app.execute(
            "SELECT tipo, versao, agregado_tipo, agregado_id, envelope "
            "FROM platform.events_outbox WHERE event_id = %s",
            (event_id,),
        )
        tipo, versao, agregado_tipo, agregado_id, envelope = app.fetchone()
        envelope = envelope if isinstance(envelope, dict) else json.loads(envelope)
        self.assertEqual((tipo, versao, agregado_tipo, agregado_id), (TIPO_VIOLACAO, 1, "product", "sku-1"))
        self.assertEqual(envelope["tenant_id"], tenant)
        self.assertEqual(envelope["payload"], payload)
        self.assertEqual((envelope["classe_pii"], envelope["finalidades"]), ("P0", ["transacao"]))
        # O envelope real, e nao o exemplo, contra o contrato publicado: um
        # contrato que o produtor nao consegue satisfazer passava o gate 7.
        esquema = json.loads((CONTRATO_V1).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(esquema).validate(envelope)

        # A outra metade: desfeita a transaccao, nao fica nem a decisao nem o
        # evento. Um `evt_emitir` que confirmasse por conta propria deixava aqui
        # um evento orfao.
        conexao.rollback()
        self.assertEqual(self._contar(tenant), (0, 0))

    def test_o_resumo_em_base32_passa_a_guarda_onde_o_hexadecimal_caia(self) -> None:
        """Achado F1: o hexadecimal do resumo casava a guarda de telefone.

        O conteudo e o que a revisao adversarial encontrou, e o resumo e
        calculado aqui (o JSON canonico do `conteudoSha256`). Com hexadecimal o
        `evt_emitir` recusava (`23514`), a decisao desfazia-se e a re-analise
        parava no mesmo produto em todas as execucoes; com base32, passa.
        """
        resumo = hashlib.sha256(
            json.dumps(["moda", ["vinho tinto 65521"]], separators=(",", ":")).encode("utf-8")
        ).digest()
        app = self.ligar("app").cursor()
        tenant = str(uuid.uuid4())
        factories.contexto(app, tenant)
        q = ConsultaDoTypeScript("SQL_EMITIR_VIOLACAO", EMISSOR_TS)
        payload_hex = json.dumps(
            {"sku": "s", "regras": ["alcool"], "versao_politica": VERSAO, "sha256": resumo.hex()}
        )
        self.assertErroSql(
            VIOLACAO_DE_CHECK, app, q.sql,
            q.args(TIPO_VIOLACAO, 1, tenant, "product", "s", payload_hex, "P0", ["transacao"]),
        )
        event_id, _ = self._emitir(app, tenant, sku="s", resumo=_base32(resumo))
        self.assertTrue(event_id)

    def test_uma_escrita_recusada_desfaz_a_decisao(self) -> None:
        import pg8000.dbapi

        conexao = self.ligar("app")
        app = conexao.cursor()
        tenant, outro = str(uuid.uuid4()), str(uuid.uuid4())
        factories.contexto(app, tenant)
        gravar(app, tenant, decisao="bloqueada", regras=["armas"])
        # O evento de outro tenant: a RLS `WITH CHECK` do outbox recusa-o, como
        # recusaria qualquer escrita que a base nao aceite. Sem `SAVEPOINT`, de
        # proposito: e a transaccao inteira que tem de cair.
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self._emitir(app, outro)
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        conexao.rollback()
        self.assertEqual(self._contar(tenant), (0, 0))
        self.assertEqual(self._contar(outro), (0, 0))


class TestDowngrade(unittest.TestCase):
    """«Migracao reversivel»: desce com linhas e volta a subir."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _existe(self) -> tuple[int, int]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                "AND tablename = 'screening_decision'"
            )
            tabelas = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'screening_decision_imutavel'")
            return tabelas, c.fetchone()[0]
        finally:
            conexao.close()

    def test_desce_com_linhas_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            gravar(conexao.cursor(), str(uuid.uuid4()))
            conexao.commit()
        finally:
            conexao.close()
        # Para a `0043` e nao `-1`: quem puser uma revisao por cima nao parte isto.
        alembic_ok("downgrade", "0043")
        self.assertEqual(self._existe(), (0, 0))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), (1, 1))


class TestSujeitoDasCondicoes(ComBase):
    """O sujeito das condicoes de um orcamento (KAM-222, revisao do fundador de 2026-11-19)."""

    def test_a_aplicacao_grava_as_condicoes_do_seu_tenant_e_so_ele_as_le(self) -> None:
        app = self.ligar("app").cursor()
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        quote_id = str(uuid.uuid4())
        factories.contexto(app, a)
        gravar(app, a, sujeito_tipo="condicoes", sujeito_ref=quote_id, regras=["moda"])
        app.execute(
            f"SELECT sujeito_ref FROM {TABELA} WHERE sujeito_tipo = 'condicoes' AND tenant_id = %s",
            (a,),
        )
        self.assertEqual([tuple(linha) for linha in app.fetchall()], [(quote_id,)])
        factories.contexto(app, b)
        app.execute(f"SELECT count(*) FROM {TABELA} WHERE sujeito_tipo = 'condicoes'")
        self.assertEqual(app.fetchone()[0], 0)

    def test_um_sujeito_mal_escrito_e_recusado(self) -> None:
        app = self.ligar("app").cursor()
        a = str(uuid.uuid4())
        factories.contexto(app, a)
        q = ConsultaDoTypeScript("SQL_GRAVAR", SQL_TS)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            app,
            q.sql,
            tuple(q.args(a, None, "condicao", "q-1", "permitida", ["moda"], VERSAO, "regra", _sha("x"))),
        )


class TestDowngradeDoSujeitoDasCondicoes(unittest.TestCase):
    """Desce para a revisao anterior, lida da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro. Afirma a revisao em que a base fica.
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

    @staticmethod
    def _anterior() -> str:
        achado = re.search(
            r'^down_revision = "(\d{4})"$', REVISAO_DAS_CONDICOES.read_text(encoding="utf-8"), re.M
        )
        assert achado is not None
        return achado.group(1)

    def _contar(self, tenant: str) -> dict[str, int]:
        conexao = ligacao.ligar("app")
        try:
            c = conexao.cursor()
            factories.contexto(c, tenant)
            c.execute(f"SELECT sujeito_tipo, count(*) FROM {TABELA} GROUP BY sujeito_tipo")
            return {tipo: int(n) for tipo, n in c.fetchall()}
        finally:
            conexao.close()

    def _estado(self) -> tuple[str, tuple[str, ...]]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT version_num FROM public.alembic_version")
            versao = c.fetchone()[0]
            return versao, _dominio(c, "screening_decision_sujeito_tipo_ck")
        finally:
            conexao.close()

    def test_desce_apagando_so_as_condicoes_e_volta(self) -> None:
        tenant = str(uuid.uuid4())
        conexao = ligacao.ligar("app")
        try:
            c = conexao.cursor()
            factories.contexto(c, tenant)
            gravar(c, tenant, sujeito_tipo="condicoes", sujeito_ref=str(uuid.uuid4()))
            gravar(c, tenant, sujeito_tipo="produto", sujeito_ref="sku-fica")
            conexao.commit()
        finally:
            conexao.close()
        self.assertEqual(self._contar(tenant), {"condicoes": 1, "produto": 1})

        anterior = self._anterior()
        alembic_ok("downgrade", anterior)
        self.assertEqual(self._estado(), (anterior, ("categoria", "produto")))
        # **So as condicoes**: a decisao de produto fica, e o *trigger* volta.
        self.assertEqual(self._contar(tenant), {"produto": 1})
        admin = ligacao.ligar("admin")
        try:
            c = admin.cursor()
            c.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgname = 'screening_decision_imutavel'"
            )
            self.assertEqual(c.fetchone()[0], "O")
            c.execute(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid = 'platform.screening_decision'::regclass"
            )
            self.assertIs(c.fetchone()[0], True)
        finally:
            admin.close()

        alembic_ok("upgrade", "head")
        self.assertEqual(self._estado()[1], ("categoria", "condicoes", "produto"))


if __name__ == "__main__":
    unittest.main()
