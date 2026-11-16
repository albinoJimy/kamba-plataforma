"""KAM-058: a revisao da regua de cobranca e o SQL do motor, contra PostgreSQL.

O motor corre como `kamba_batch` e o ciclo completo — D+0 ate a reposicao, com o
`correrRegua` verdadeiro — mede-se em `packages/core-ts/tests_bd/regua.bd.test.ts`
(suite `tests_lote`). O que fica aqui e o que so a revisao e as cadeias SQL
provam, uma a uma:

```text
criterio 1   UNIQUE (billing_cycle_id, passo); o passo e de um ciclo do mesmo tenant
resultado    so a suspensao suspende; so um aviso que saiu tem canal
RLS          FORCE pela tenant_iso: a auditoria ve o seu tenant e nao o dos outros
privilegios  o lote so insere; a aplicacao nao le nem escreve
SQL          os ciclos que a regua olha, a cobranca da mensagem, o estado trancado,
             a transicao pelo transition_tenant, o evento, a reposicao so do que
             a regua suspendeu
downgrade    desce e volta
```

**O nome do ficheiro ordena-o depois do `test_reembolsos_do_pay.py`** (que desce
a `0050`) e antes do `test_subscricao_e_billing.py`, pela razao escrita nele.
"""

from __future__ import annotations

import datetime
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
    VIOLACAO_DE_UNICIDADE,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests_pagamentos.test_subscricao_e_billing import PRECO, ComBilling

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "packages" / "core-ts" / "src" / "pagamentos" / "regua.ts"
#: Por *glob* e nao pelo numero: o numero e provisorio e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_regua_de_cobranca.py"))

PASSOS = ConsultaDoTypeScript("SQL_REGUA_CICLOS", MODULO)
COBRANCA = ConsultaDoTypeScript("SQL_REGUA_COBRANCA", MODULO)
GRAVADO = ConsultaDoTypeScript("SQL_REGUA_PASSO_GRAVADO", MODULO)
GRAVAR = ConsultaDoTypeScript("SQL_REGUA_GRAVAR_PASSO", MODULO)
TRANCAR = ConsultaDoTypeScript("SQL_REGUA_TRANCAR", MODULO)
ESTADO = ConsultaDoTypeScript("SQL_REGUA_ESTADO_DO_TENANT", MODULO)
TRANSITAR = ConsultaDoTypeScript("SQL_REGUA_TRANSITAR", MODULO)
EMITIR = ConsultaDoTypeScript("SQL_REGUA_EMITIR", MODULO)
AUDITAR = ConsultaDoTypeScript("SQL_REGUA_AUDITAR", MODULO)
POR_REPOR = ConsultaDoTypeScript("SQL_REGUA_POR_REPOR", MODULO)
EM_ATRASO = ConsultaDoTypeScript("SQL_REGUA_EM_ATRASO", MODULO)
EM_DIA = ConsultaDoTypeScript("SQL_REGUA_SUBSCRICOES_EM_DIA", MODULO)
SUSPENSOES = ConsultaDoTypeScript("SQL_REGUA_SUSPENSOES_NO_DIA", MODULO)
LISTA = ConsultaDoTypeScript("SQL_REGUA_LISTA_DE_OPS", MODULO)
CONTEXTO = ConsultaDoTypeScript("SQL_BILLING_CONTEXTO", RAIZ / "packages" / "core-ts" / "src" / "pagamentos" / "billing.ts")

#: Os tres passos, pela ordem do `PASSOS_DA_REGUA`. Escritos aqui e confrontados
#: com o modulo e com a revisao, e nao importados: um oraculo importado do alvo
#: nao e oraculo.
OS_PASSOS = ["lembrete", "aviso", "suspensao"]
MOTIVO = "regua_de_cobranca"
TABELA = "platform.billing_dunning_steps"
INSERIR = (
    f"INSERT INTO {TABELA} (tenant_id, billing_cycle_id, passo, executado_at, resultado, "
    "canal, config_versao) VALUES (%s, %s, %s, now(), %s, %s, 'v')"
)


def _anterior() -> str:
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None, "a revisao da regua nao diz o down_revision"
    return achado.group(1)


class ComRegua(ComBilling):
    """Um ciclo emitido, o tenant activo, e as ligacoes do lote e da auditoria."""

    def setUp(self) -> None:
        super().setUp()
        # Desde a `0040` um tenant so fica `ativo` com o aceite dos contratos.
        factories.aceitar_contratos_vigentes(self.semente, self.tenant)
        self.semente.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (self.tenant,))
        self.ciclo = self.abrir()
        self.cobranca = self.cobranca_do_ciclo(self.ciclo)
        self.lote = self.cursor_papel("batch", self.tenant)

    def gravar(self, passo: str, resultado: str, canal: str | None, cursor=None) -> None:
        cursor = self.lote if cursor is None else cursor
        cursor.execute(
            GRAVAR.sql,
            GRAVAR.args(self.tenant, self.ciclo, passo, "2026-12-04T09:00:00Z", resultado, canal, "v1"),
        )

    def sancionar(self, passo: str, recurso_de: str | None = None) -> str:
        """Uma sancao humana de T&S, como o Trust a grava: sem tocar no registo."""
        self.semente.execute(
            "INSERT INTO platform.review_case (tipo, tenant_id, motivo_codigo, motivo_interno, "
            " motivo_publico, recomendacao, sla_alerta_at, sla_due_at) "
            "VALUES ('trust', %s, %s, 'ensaio da regua', 'nao_foi_possivel_validar', 'rejeitar', "
            " now() + interval '19 hours', now() + interval '24 hours') RETURNING id::text",
            (self.tenant, f"sancao_suspensao:{uuid.uuid4().hex[:12]}"),
        )
        caso = self.semente.fetchone()[0]
        chave = f"recurso:{recurso_de}" if recurso_de else f"caso:{caso}"
        self.semente.execute(
            "INSERT INTO platform.ts_sanction (tenant_id, chave, passo, origem, motivo_interno, "
            " motivo_publico, autor, case_id, justificacao_salto, recurso_de, recurso_estado) "
            "VALUES (%s, %s, %s, 'humana', 'ensaio da regua', %s, %s, %s, %s, %s, %s) "
            "RETURNING id::text",
            (
                self.tenant, chave, passo,
                "recurso_aceite" if recurso_de else "loja_suspensa",
                str(uuid.uuid4()), caso,
                None if recurso_de else "ensaio da regua: salto directo a suspensao",
                recurso_de, "provido" if recurso_de else None,
            ),
        )
        return self.semente.fetchone()[0]

    def estado_do_tenant(self) -> str:
        self.semente.execute("SELECT estado FROM platform.tenants WHERE id = %s", (self.tenant,))
        return self.semente.fetchone()[0]

    def suspender(self) -> bool:
        """O passo da suspensao, pela ordem do `correrPasso` do motor."""
        self.lote.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.lote.execute(TRANCAR.sql, TRANCAR.args(self.ciclo))
        self.lote.execute(ESTADO.sql, ESTADO.args(self.tenant))
        self.assertEqual(self.lote.fetchone()[0], "ativo")
        self.lote.execute(TRANSITAR.sql, TRANSITAR.args(self.tenant, "suspenso", MOTIVO, MOTIVO))
        mudou = self.lote.fetchone()[0]
        if mudou:
            self.lote.execute(
                EMITIR.sql,
                EMITIR.args("tenant.suspended", 1, self.tenant, "tenant", self.tenant,
                            json.dumps({"motivo": "falta_de_pagamento"})),
            )
            self.lote.execute(
                AUDITAR.sql,
                AUDITAR.args(self.tenant, "kamba_batch:regua_de_cobranca", f"ativo>suspenso:{MOTIVO}"),
            )
        self.gravar("suspensao", "suspenso" if mudou else "sem_transicao", "ops" if mudou else None)
        self.confirmar(self.lote, self.tenant)
        return mudou


class TestDominios(ComRegua):
    def test_os_passos_sao_os_do_modulo_e_os_da_revisao(self) -> None:
        texto = MODULO.read_text(encoding="utf-8")
        achado = re.search(r"PASSOS_DA_REGUA = \[([^\]]*)\]", texto)
        self.assertIsNotNone(achado)
        self.assertEqual(re.findall(r'"([a-z_]+)"', achado.group(1)), OS_PASSOS)
        for passo in OS_PASSOS:
            self.gravar(passo, "cancelado", None)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.admin, INSERIR,
            (self.tenant, self.ciclo, "d10", "cancelado", None),
        )

    def test_os_resultados_e_os_canais_sao_os_do_modulo(self) -> None:
        texto = MODULO.read_text(encoding="utf-8")
        resultados = re.findall(r'"([a-z_]+)"', re.search(r"RESULTADOS_DO_PASSO = \[([^\]]*)\]", texto).group(1))
        canais = re.findall(r'"([a-z_]+)"', re.search(r"CANAIS_DA_REGUA = \[([^\]]*)\]", texto).group(1))
        revisao = REVISAO.read_text(encoding="utf-8")
        for valor in resultados + canais:
            with self.subTest(valor=valor):
                self.assertIn(f"\"'{valor}'\"", revisao)


class TestCriterio1Unicidade(ComRegua):
    def test_um_passo_por_ciclo(self) -> None:
        self.gravar("lembrete", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, self.admin, INSERIR,
            (self.tenant, self.ciclo, "lembrete", "saltado", None),
        )

    def test_o_gravar_do_modulo_absorve_a_repeticao(self) -> None:
        for _ in range(5):
            self.gravar("lembrete", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        self.semente.execute(f"SELECT count(*) FROM {TABELA} WHERE billing_cycle_id = %s", (self.ciclo,))
        self.assertEqual(self.semente.fetchone()[0], 1)
        self.lote.execute(GRAVADO.sql, GRAVADO.args(self.ciclo, "lembrete"))
        self.assertEqual(len(self.lote.fetchall()), 1)
        self.lote.execute(GRAVADO.sql, GRAVADO.args(self.ciclo, "aviso"))
        self.assertEqual(list(self.lote.fetchall()), [])

    def test_o_passo_e_de_um_ciclo_do_mesmo_tenant(self) -> None:
        outro = self.criar_tenant()
        self.assertErroSql(
            VIOLACAO_DE_FK, self.admin, INSERIR, (outro, self.ciclo, "lembrete", "saltado", None)
        )
        self.assertErroSql(
            VIOLACAO_DE_FK, self.admin, INSERIR, (self.tenant, str(uuid.uuid4()), "lembrete", "saltado", None)
        )


class TestResultado(ComRegua):
    def test_so_a_suspensao_suspende_e_so_um_aviso_que_saiu_tem_canal(self) -> None:
        recusados = (
            ("lembrete", "suspenso", "ops"),
            ("aviso", "sem_transicao", None),
            ("suspensao", "notificado", "ops"),
            ("suspensao", "saltado", None),
            ("lembrete", "notificado", None),
            ("lembrete", "saltado", "ops"),
            ("suspensao", "sem_transicao", "ops"),
            ("lembrete", "notificado", "whatsapp"),
        )
        for passo, resultado, canal in recusados:
            with self.subTest(passo=passo, resultado=resultado, canal=canal):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.admin, INSERIR, (self.tenant, self.ciclo, passo, resultado, canal)
                )
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.admin,
            f"INSERT INTO {TABELA} (tenant_id, billing_cycle_id, passo, executado_at, resultado, "
            "config_versao) VALUES (%s, %s, 'aviso', now(), 'cancelado', '')",
            (self.tenant, self.ciclo),
        )


class TestPrivilegiosERls(ComRegua):
    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        self.semente.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (TABELA,)
        )
        self.assertEqual(tuple(self.semente.fetchone()), (True, True))

    def test_a_auditoria_le_o_seu_tenant_e_nao_o_dos_outros(self) -> None:
        self.gravar("lembrete", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        outro = self.criar_tenant()
        for contexto, esperado in ((self.tenant, 1), (outro, 0), (None, 0)):
            with self.subTest(contexto=contexto):
                auditoria = self.cursor_papel("audit", contexto)
                auditoria.execute(f"SELECT count(*) FROM {TABELA} WHERE billing_cycle_id = %s", (self.ciclo,))
                self.assertEqual(auditoria.fetchone()[0], esperado)
                self.confirmar(auditoria, contexto)

    def test_o_lote_so_insere_e_a_aplicacao_nada(self) -> None:
        self.gravar("lembrete", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        for sql in (
            f"UPDATE {TABELA} SET resultado = 'cancelado' WHERE billing_cycle_id = %s",
            f"DELETE FROM {TABELA} WHERE billing_cycle_id = %s",
        ):
            with self.subTest(sql=sql):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.lote, sql, (self.ciclo,))
        app = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app, f"SELECT count(*) FROM {TABELA} WHERE billing_cycle_id = %s", (self.ciclo,)
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, INSERIR, (self.tenant, self.ciclo, "aviso", "saltado", None))


class TestSqlDoMotor(ComRegua):
    def test_os_ciclos_em_divida_e_os_pagos_com_passos_por_cancelar(self) -> None:
        self.lote.execute(PASSOS.sql, PASSOS.args(OS_PASSOS))
        meus = [l for l in self.lote.fetchall() if str(l[0]) == self.ciclo]
        self.assertEqual(len(meus), 1)
        self.confirmar(self.lote, self.tenant)
        _id, tenant, subscricao, estado, inicio, aviso_em, passos = meus[0]
        # O D+0 e a emissao da cobranca em Luanda, e nao o inicio do periodo
        # (`2026-11-01` no `abrir`): achado 2 da revisao adversarial.
        self.semente.execute(
            "SELECT ((criado_at AT TIME ZONE 'Africa/Luanda')::date)::text "
            "  FROM platform.payment_charges WHERE id = %s",
            (self.cobranca,),
        )
        emissao = self.semente.fetchone()[0]
        self.assertNotEqual(emissao, "2026-11-01")
        self.assertEqual(
            (str(tenant), str(subscricao), estado, inicio, aviso_em),
            (self.tenant, self.subscricao, "cobranca_emitida", emissao, None),
        )
        self.assertEqual(list(passos), [])
        # O aviso notificado da a data de onde se conta o aviso previo.
        self.gravar("aviso", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        self.lote.execute(PASSOS.sql, PASSOS.args(OS_PASSOS))
        meus = [l for l in self.lote.fetchall() if str(l[0]) == self.ciclo]
        self.assertEqual(meus[0][5], "2026-12-04", "o executado_at do gravar, em Luanda")
        self.confirmar(self.lote, self.tenant)

        self.gravar("lembrete", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        pay = self.cursor_papel("pay", self.tenant)
        self.appendar(pay, self.cobranca, self.conta, "pagamento_confirmado",
                      p_valor_minor=PRECO, p_provider_event_id=f"evt-{uuid.uuid4()}")
        self.confirmar(pay, self.tenant)
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "paga")
        # O estado relido sob o trinco ve o pagamento (achado 5).
        estado_do_ciclo = ConsultaDoTypeScript("SQL_REGUA_ESTADO_DO_CICLO", MODULO)
        self.lote.execute(estado_do_ciclo.sql, estado_do_ciclo.args(self.ciclo, self.tenant))
        self.assertEqual(self.lote.fetchone()[0], "paga")
        self.confirmar(self.lote, self.tenant)
        self.lote.execute(PASSOS.sql, PASSOS.args(OS_PASSOS))
        meus = [l for l in self.lote.fetchall() if str(l[0]) == self.ciclo]
        self.assertEqual([(l[3], sorted(l[6])) for l in meus], [("paga", ["aviso", "lembrete"])])
        for passo in ("suspensao",):
            self.gravar(passo, "cancelado", None)
        self.confirmar(self.lote, self.tenant)
        self.lote.execute(PASSOS.sql, PASSOS.args(OS_PASSOS))
        self.assertEqual([l for l in self.lote.fetchall() if str(l[0]) == self.ciclo], [])

    def test_a_cobranca_da_mensagem_e_a_mais_recente_do_ciclo(self) -> None:
        self.lote.execute(COBRANCA.sql, COBRANCA.args(self.ciclo, self.tenant))
        metodo, referencia, valor, moeda, validade = self.lote.fetchone()
        self.assertEqual((metodo, referencia, int(valor), moeda), ("manual", None, PRECO, "AOA"))
        self.assertIsInstance(validade, datetime.datetime)
        outro = self.criar_tenant()
        self.lote.execute(COBRANCA.sql, COBRANCA.args(self.ciclo, outro))
        self.assertEqual(list(self.lote.fetchall()), [], "a cobranca de um ciclo nao se le pelo tenant de outro")

    def test_lembrete_poe_a_subscricao_em_atraso_e_o_pagamento_tira_a(self) -> None:
        self.lote.execute(EM_ATRASO.sql, EM_ATRASO.args(self.subscricao))
        self.gravar("lembrete", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        self.semente.execute("SELECT estado FROM platform.subscriptions WHERE id = %s", (self.subscricao,))
        self.assertEqual(self.semente.fetchone()[0], "em_atraso")
        self.lote.execute(EM_DIA.sql, EM_DIA.args())
        self.assertNotIn(self.subscricao, [str(l[0]) for l in self.lote.fetchall()], "ainda deve")
        self.confirmar(self.lote, self.tenant)
        pay = self.cursor_papel("pay", self.tenant)
        self.appendar(pay, self.cobranca, self.conta, "pagamento_confirmado",
                      p_valor_minor=PRECO, p_provider_event_id=f"evt-{uuid.uuid4()}")
        self.confirmar(pay, self.tenant)
        self.lote.execute(EM_DIA.sql, EM_DIA.args())
        self.assertIn(self.subscricao, [str(l[0]) for l in self.lote.fetchall()])
        self.confirmar(self.lote, self.tenant)

    def test_criterio_2_a_suspensao_pela_porta_do_kam_092_uma_vez_com_registo_e_evento(self) -> None:
        import jsonschema

        from tests_pagamentos.test_fks_e_mapa import esquema, verificador

        self.assertTrue(self.suspender())
        self.assertEqual(self.estado_do_tenant(), "suspenso")
        # A segunda vez nao transita nem emite: o `transition_tenant` devolve `false`.
        self.lote.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.lote.execute(TRANSITAR.sql, TRANSITAR.args(self.tenant, "suspenso", MOTIVO, MOTIVO))
        self.assertIs(self.lote.fetchone()[0], False)
        self.confirmar(self.lote, self.tenant)
        self.semente.execute(
            "SELECT de, para, motivo, actor FROM platform.tenant_state_log WHERE tenant_id = %s", (self.tenant,)
        )
        self.assertEqual([tuple(l) for l in self.semente.fetchall()], [("ativo", "suspenso", MOTIVO, MOTIVO)])
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox WHERE tenant_id = %s AND tipo = 'tenant.suspended'",
            (self.tenant,),
        )
        envelopes = [e[0] if isinstance(e[0], dict) else json.loads(e[0]) for e in self.semente.fetchall()]
        self.assertEqual(len(envelopes), 1)
        jsonschema.validate(envelopes[0], esquema("tenant.suspended", 1), format_checker=verificador())
        self.assertEqual(envelopes[0]["payload"], {"motivo": "falta_de_pagamento"})
        # A transicao no `audit_log`, na cadeia do tenant, pela porta da `0006`
        # como `kamba_batch` (critério 2).
        self.semente.execute(
            "SELECT actor_type, actor_id, action, entity, entity_id, payload_hash "
            "  FROM platform.audit_log WHERE tenant_id = %s AND action = 'batch.run'",
            (self.tenant,),
        )
        linhas = [tuple(l) for l in self.semente.fetchall()]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(
            linhas[0][:5], ("system", "kamba_batch:regua_de_cobranca", "batch.run", "tenant", self.tenant)
        )
        import hashlib

        self.assertEqual(bytes(linhas[0][5]), hashlib.sha256(f"ativo>suspenso:{MOTIVO}".encode()).digest())
        # O CHR le o estado novo pela consulta dele, como `kamba_resolver`.
        canal = ConsultaDoTypeScript(
            "SQL_CANAL", RAIZ / "packages" / "core-ts" / "src" / "chr" / "consultas.ts"
        )
        pnid = f"pnid-{uuid.uuid4()}"
        self.semente.execute(
            "INSERT INTO platform.tenant_channels (tenant_id, waba_id, phone_number_id, channel_mode, "
            "vertical, origem, estado, token_ref) VALUES (%s, 'waba-regua', %s, 'coexistencia', "
            "'vendedor', 'pme', 'ativo', 'ref-opaca/regua')",
            (self.tenant, pnid),
        )
        resolver = self.cursor_papel("resolver")
        resolver.execute(canal.sql, canal.args(pnid))
        linha = resolver.fetchone()
        self.assertEqual(linha[4], "suspenso")
        self.confirmar(resolver, None)
        self.semente.execute("DELETE FROM platform.tenant_channels WHERE phone_number_id = %s", (pnid,))

    def test_criterio_7_a_suspensao_nao_apaga_dados(self) -> None:
        contagens = {}
        tabelas = ("payment_charges", "billing_cycles", "subscriptions", "payment_events", "contacts")
        for t in tabelas:
            self.semente.execute(f"SELECT count(*) FROM platform.{t} WHERE tenant_id = %s", (self.tenant,))
            contagens[t] = self.semente.fetchone()[0]
        self.assertTrue(self.suspender())
        for t in tabelas:
            with self.subTest(tabela=t):
                self.semente.execute(f"SELECT count(*) FROM platform.{t} WHERE tenant_id = %s", (self.tenant,))
                self.assertEqual(self.semente.fetchone()[0], contagens[t])

    def test_a_reposicao_so_levanta_o_que_a_regua_suspendeu(self) -> None:
        self.assertTrue(self.suspender())
        self.lote.execute(POR_REPOR.sql, POR_REPOR.args(MOTIVO, self.tenant))
        self.assertEqual(list(self.lote.fetchall()), [], "o ciclo em divida com o passo da suspensao prende-o")
        self.confirmar(self.lote, self.tenant)
        pay = self.cursor_papel("pay", self.tenant)
        self.appendar(pay, self.cobranca, self.conta, "pagamento_confirmado",
                      p_valor_minor=PRECO, p_provider_event_id=f"evt-{uuid.uuid4()}")
        self.confirmar(pay, self.tenant)
        self.lote.execute(POR_REPOR.sql, POR_REPOR.args(MOTIVO, self.tenant))
        self.assertEqual([str(l[0]) for l in self.lote.fetchall()], [self.tenant])
        # Outro motivo e outro dono da suspensao: nao e da regua.
        self.lote.execute(POR_REPOR.sql, POR_REPOR.args("sancao", self.tenant))
        self.assertEqual(list(self.lote.fetchall()), [])
        self.confirmar(self.lote, self.tenant)
        # Achado 1: uma sancao de T&S de suspensao, escrita pelo Trust **sem**
        # passar pelo registo de estados, prende a reposicao; um recurso
        # provido solta-a.
        sancao = self.sancionar("suspensao")
        self.lote.execute(POR_REPOR.sql, POR_REPOR.args(MOTIVO, self.tenant))
        self.assertEqual(list(self.lote.fetchall()), [], "pagar a assinatura nao levanta a sancao")
        self.confirmar(self.lote, self.tenant)
        self.sancionar("aviso", recurso_de=sancao)
        self.lote.execute(POR_REPOR.sql, POR_REPOR.args(MOTIVO, self.tenant))
        self.assertEqual([str(l[0]) for l in self.lote.fetchall()], [self.tenant])
        # A reposicao pela porta, e depois o tenant ja nao esta por repor.
        self.lote.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.lote.execute(TRANSITAR.sql, TRANSITAR.args(self.tenant, "ativo", "regua_regularizada", MOTIVO))
        self.assertIs(self.lote.fetchone()[0], True)
        self.confirmar(self.lote, self.tenant)
        self.lote.execute(POR_REPOR.sql, POR_REPOR.args(MOTIVO, None))
        self.assertNotIn(self.tenant, [str(l[0]) for l in self.lote.fetchall()])
        self.confirmar(self.lote, self.tenant)

    def test_a_contagem_do_alerta_e_a_lista_de_ops(self) -> None:
        self.gravar("aviso", "notificado", "ops")
        self.confirmar(self.lote, self.tenant)
        self.assertTrue(self.suspender())
        dia = ("2026-12-03T23:00:00Z", "2026-12-04T23:00:00Z")
        self.lote.execute(SUSPENSOES.sql, SUSPENSOES.args(*dia))
        self.assertGreaterEqual(self.lote.fetchone()[0], 1)
        self.lote.execute(LISTA.sql, LISTA.args(*dia))
        meus = [l for l in self.lote.fetchall() if str(l[1]) == self.ciclo]
        self.assertEqual(sorted(l[2] for l in meus), ["aviso", "suspensao"])
        self.assertTrue(all(int(l[7]) == PRECO for l in meus))
        self.confirmar(self.lote, self.tenant)


class TestDowngradeDaRegua(unittest.TestCase):
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

    def _existe(self) -> bool:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT to_regclass('platform.billing_dunning_steps') IS NOT NULL")
            return bool(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertFalse(self._existe())
        finally:
            alembic_ok("upgrade", "head")
        self.assertTrue(self._existe())


if __name__ == "__main__":
    unittest.main()
