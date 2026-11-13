"""KAM-059: o billing da plataforma contra PostgreSQL.

Com o SQL que o TypeScript envia (`packages/core-ts/src/pagamentos/billing.ts`,
pelo `ConsultaDoTypeScript`) e com o papel que corre o billing, o `kamba_pay`.
O que se mede aqui e o que so a base pode dizer:

```text
criterio 1   um ciclo por periodo, a charges_billing_fk composta com o tenant
criterio 2   o job duas vezes: um ciclo e uma cobranca, valida por 72 h
criterio 3   G-1 nos dois sentidos, e a conta da KAMBA so ao papel do billing
criterio 4   o pagamento autenticado leva o ciclo a paga; dez vezes, um evento
criterio 5   ops com motivo e duas pessoas; uma nao conclui; o dono nao entra
criterio 6   o preco novo nao toca no ciclo emitido, e fica no audit_log
criterio 7   so sombra, um por evento, so de pagamento autenticado
criterio 8   o plano e os entitlements numa instrucao; em_atraso mantem
```

**O nome do ficheiro ordena-o depois do `test_reembolsos_do_pay.py`, e isso
conta:** aquele desce a base a `0050`, e o `downgrade` do billing recusa-se
quando ha cobrancas de ciclo — que e o que este ficheiro deixa.
"""

from __future__ import annotations

import datetime
import json
import uuid
from pathlib import Path

from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_UNICIDADE,
    ConsultaDoTypeScript,
    alembic,
)
from tests_pagamentos.base import ComLedger

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "packages" / "core-ts" / "src" / "pagamentos" / "billing.ts"

ABRIR = ConsultaDoTypeScript("SQL_BILLING_ABRIR_CICLO", MODULO)
COBRANCA = ConsultaDoTypeScript("SQL_BILLING_COBRANCA", MODULO)
EMITIR = ConsultaDoTypeScript("SQL_BILLING_EMITIR", MODULO)
EMITIDO = ConsultaDoTypeScript("SQL_BILLING_CICLO_EMITIDO", MODULO)
CONTEXTO = ConsultaDoTypeScript("SQL_BILLING_CONTEXTO", MODULO)
SUBSCRICOES = ConsultaDoTypeScript("SQL_BILLING_SUBSCRICOES", MODULO)
PRECARIO = ConsultaDoTypeScript("SQL_BILLING_PRECARIO", MODULO)
CONFIRMAR_OPS = ConsultaDoTypeScript("SQL_BILLING_CONFIRMAR_OPS", MODULO)
MUDAR_PLANO = ConsultaDoTypeScript("SQL_MUDAR_PLANO", MODULO)
SOMBRA_POR_MEDIR = ConsultaDoTypeScript("SQL_SOMBRA_POR_MEDIR", MODULO)
SOMBRA_GRAVAR = ConsultaDoTypeScript("SQL_SOMBRA_GRAVAR", MODULO)

#: 10 000 Kz, o preco de ensaio. **Nao** e um preco de produto: os precos sao
#: decisao de produto e nao estao decididos (o bloco: «nao inventar»).
PRECO = 1_000_000
INICIO = "2026-11-01"
FIM = "2026-12-01"
ACTOR_DE_PRECO = "ops-de-ensaio"


class ComBilling(ComLedger):
    """Um tenant com subscricao, um plano com preco e a conta da KAMBA."""

    def setUp(self) -> None:
        super().setUp()
        self._precos: list[str] = []
        self._contas_da_kamba: list[str] = []
        self.addCleanup(self._limpar_billing)
        self.tenant = self.criar_tenant()
        self.plano = f"plano_{uuid.uuid4().hex[:10]}"
        self.publicar_preco(self.plano, PRECO, "2026-01-01")
        self.conta = self.criar_conta_da_kamba()
        self.subscricao = self.criar_subscricao(self.tenant, self.plano)
        self.pay = self.cursor_papel("pay", self.tenant)

    # ------------------------------------------------------------ sementes

    def publicar_preco(self, plano: str, valor: int, valido_de: str) -> str:
        self.semente.execute("SELECT set_config('app.actor_id', %s, false)", (ACTOR_DE_PRECO,))
        self.semente.execute(
            "INSERT INTO platform.price_book (plano, valor_minor, valido_de) "
            "VALUES (%s, %s, %s) RETURNING id",
            (plano, valor, valido_de),
        )
        preco = str(self.semente.fetchone()[0])
        self.semente.execute("SELECT set_config('app.actor_id', '', false)")
        self._precos.append(plano)
        return preco

    def criar_conta_da_kamba(self, provider: str = "manual") -> str:
        conta = str(uuid.uuid4())
        self.semente.execute(
            "INSERT INTO platform.payment_accounts "
            "(id, beneficiary_kind, tenant_id, provider, estado, webhook_token) "
            "VALUES (%s, 'plataforma_receita_propria', NULL, %s, 'ativo', %s)",
            (conta, provider, uuid.uuid4().hex),
        )
        self._contas_da_kamba.append(conta)
        return conta

    def criar_subscricao(self, tenant: str, plano: str) -> str:
        self.semente.execute(
            "INSERT INTO platform.subscriptions (tenant_id, plano) VALUES (%s, %s) "
            "RETURNING id",
            (tenant, plano),
        )
        return str(self.semente.fetchone()[0])

    def _limpar_billing(self) -> None:
        """Corre **antes** da limpeza do `ComLedger` (os `addCleanup` sao LIFO).

        Apaga o que nao esta preso ao ledger; o que esta, fica, e com ele o
        tenant — que e o que a limpeza do `ComLedger` ja faz por ele.
        """
        for tenant in self._tenants:
            for tabela in ("commission_accruals", "billing_ops_approvals"):
                self.semente.execute(
                    f"DELETE FROM platform.{tabela} WHERE tenant_id = %s "
                    "  AND NOT EXISTS (SELECT 1 FROM platform.payment_events e "
                    "                   WHERE e.tenant_id = %s)",
                    (tenant, tenant),
                )
            self.semente.execute(
                "DELETE FROM platform.payment_charges WHERE tenant_id = %s "
                "  AND billing_cycle_id IS NOT NULL "
                "  AND id NOT IN (SELECT charge_id FROM platform.payment_events)",
                (tenant,),
            )
            self.semente.execute(
                "DELETE FROM platform.billing_cycles WHERE tenant_id = %s "
                "  AND id NOT IN (SELECT billing_cycle_id FROM platform.payment_charges "
                "                  WHERE billing_cycle_id IS NOT NULL)",
                (tenant,),
            )
            self.semente.execute(
                "DELETE FROM platform.subscriptions WHERE tenant_id = %s "
                "  AND id NOT IN (SELECT subscription_id FROM platform.billing_cycles)",
                (tenant,),
            )
            self.semente.execute(
                "DELETE FROM platform.entitlements WHERE tenant_id = %s", (tenant,)
            )
        for conta in self._contas_da_kamba:
            self.semente.execute(
                "DELETE FROM platform.payment_accounts WHERE id = %s "
                "  AND id NOT IN (SELECT account_id FROM platform.payment_charges)",
                (conta,),
            )

    # ------------------------------------------------------------- o job

    def abrir(self, cursor=None, tenant: str | None = None, subscricao: str | None = None,
              valor: int = PRECO, inicio: str = INICIO, fim: str = FIM,
              agora: datetime.datetime | None = None) -> str | None:
        """Uma volta do `abrirCiclos` para uma subscricao, pela ordem do TS."""
        cursor = self.pay if cursor is None else cursor
        tenant = self.tenant if tenant is None else tenant
        subscricao = self.subscricao if subscricao is None else subscricao
        agora = agora or datetime.datetime.now(datetime.timezone.utc)
        cursor.execute(CONTEXTO.sql, CONTEXTO.args(tenant))
        cursor.execute(ABRIR.sql, ABRIR.args(subscricao, tenant, inicio, fim, valor))
        linha = cursor.fetchone()
        if linha is None:
            self.confirmar(cursor, tenant)
            return None
        ciclo = str(linha[0])
        cobranca = str(uuid.uuid4())
        cursor.execute(
            COBRANCA.sql,
            COBRANCA.args(
                cobranca, tenant, ciclo, self.conta, "manual", "manual", None, valor,
                agora + datetime.timedelta(hours=72),
            ),
        )
        cursor.execute(EMITIR.sql, EMITIR.args(cobranca, self.conta, valor))
        cursor.execute(EMITIDO.sql, EMITIDO.args(ciclo))
        self.confirmar(cursor, tenant)
        return ciclo

    def cobranca_do_ciclo(self, ciclo: str) -> str:
        self.semente.execute(
            "SELECT id FROM platform.payment_charges WHERE billing_cycle_id = %s", (ciclo,)
        )
        return str(self.semente.fetchone()[0])

    def estado_do_ciclo(self, ciclo: str) -> str:
        self.semente.execute("SELECT estado FROM platform.billing_cycles WHERE id = %s", (ciclo,))
        return self.semente.fetchone()[0]

    def eventos_de_ciclo_pago(self, ciclo: str) -> list:
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox "
            " WHERE tipo = 'billing.cycle_paid' AND agregado_id = %s",
            (ciclo,),
        )
        envelopes = [linha[0] for linha in self.semente.fetchall()]
        return [json.loads(e) if isinstance(e, str) else e for e in envelopes]

    def aprovar(self, cobranca: str, actor: str, motivo: str = "extracto bancario",
                valor: int = PRECO) -> tuple:
        self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.pay.execute(CONFIRMAR_OPS.sql, CONFIRMAR_OPS.args(cobranca, actor, motivo, valor))
        resposta = tuple(self.pay.fetchone())
        self.confirmar(self.pay, self.tenant)
        return resposta


class TestCriterio1Tabelas(ComBilling):
    def test_um_ciclo_por_periodo(self) -> None:
        self.abrir()
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, self.semente,
            "INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, "
            "valor_minor) VALUES (%s, %s, daterange(%s::date, %s::date), %s)",
            (self.subscricao, self.tenant, INICIO, FIM, PRECO),
        )

    def test_a_cobranca_aponta_para_um_ciclo_que_existe_e_do_mesmo_tenant(self) -> None:
        ciclo = self.abrir()
        outro = self.criar_tenant()
        for tenant, alvo in ((self.tenant, str(uuid.uuid4())), (outro, ciclo)):
            self.assertErroSql(
                VIOLACAO_DE_FK, self.semente,
                "INSERT INTO platform.payment_charges (tenant_id, billing_cycle_id, "
                "tentativa, account_id, provider, metodo, amount_minor, valid_until) "
                "VALUES (%s, %s, 2, %s, 'manual', 'manual', %s, now())",
                (tenant, alvo, self.conta, PRECO),
            )

    def test_o_ciclo_nao_aponta_para_a_subscricao_de_outro_tenant(self) -> None:
        outro = self.criar_tenant()
        self.assertErroSql(
            VIOLACAO_DE_FK, self.semente,
            "INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, "
            "valor_minor) VALUES (%s, %s, daterange('2026-11-01', '2026-12-01'), %s)",
            (self.subscricao, outro, PRECO),
        )

    def test_dominios_e_limites(self) -> None:
        casos = (
            ("UPDATE platform.subscriptions SET estado = 'pendente' WHERE id = %s",
             (self.subscricao,)),
            ("UPDATE platform.subscriptions SET periodo_dia = 29 WHERE id = %s",
             (self.subscricao,)),
            ("INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, "
             "valor_minor) VALUES (%s, %s, daterange('2027-01-01', '2027-02-01'), 0)",
             (self.subscricao, self.tenant)),
            ("INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, "
             "valor_minor, estado) VALUES (%s, %s, daterange('2027-01-01', '2027-02-01'), "
             "1, 'paga')", (self.subscricao, self.tenant)),
        )
        for sql, parametros in casos:
            with self.subTest(sql=sql[:60]):
                self.assertErroSql(VIOLACAO_DE_CHECK, self.semente, sql, parametros)


class TestCriterio2Job(ComBilling):
    def test_o_job_duas_vezes_da_um_ciclo_e_uma_cobranca_de_72_h(self) -> None:
        agora = datetime.datetime(2026, 11, 13, 10, tzinfo=datetime.timezone.utc)
        ciclo = self.abrir(agora=agora)
        self.assertIsNotNone(ciclo)
        self.assertIsNone(self.abrir(agora=agora), "a segunda volta nao abre nada")
        self.semente.execute(
            "SELECT count(*) FROM platform.billing_cycles WHERE subscription_id = %s",
            (self.subscricao,),
        )
        self.assertEqual(self.semente.fetchone()[0], 1)
        self.semente.execute(
            "SELECT count(*), min(valid_until), min(estado), min(metodo) "
            "  FROM platform.payment_charges WHERE billing_cycle_id = %s",
            (ciclo,),
        )
        n, validade, estado, metodo = self.semente.fetchone()
        self.assertEqual(n, 1)
        self.assertEqual(validade, agora + datetime.timedelta(hours=72))
        self.assertEqual(estado, "emitida")
        self.assertEqual(metodo, "manual")
        self.assertEqual(self.estado_do_ciclo(ciclo), "cobranca_emitida")

    def test_o_billing_le_as_subscricoes_de_todos_e_o_precario(self) -> None:
        outro = self.criar_tenant()
        self.criar_subscricao(outro, self.plano)
        leitor = self.cursor_papel("pay", None)
        leitor.execute(SUBSCRICOES.sql)
        tenants = {str(linha[1]) for linha in leitor.fetchall()}
        self.assertTrue({self.tenant, outro} <= tenants)
        leitor.execute(PRECARIO.sql, PRECARIO.args(self.plano))
        linhas = leitor.fetchall()
        self.assertEqual(len(linhas), 1)
        self.assertEqual((int(linhas[0][2]), linhas[0][3]), (PRECO, "2026-01-01"))


class TestCriterio3BeneficiarioERls(ComBilling):
    def test_uma_cobranca_de_ciclo_numa_conta_de_pme_e_recusada_pelo_g1(self) -> None:
        conta_pme = self.criar_conta(self.tenant)
        self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.pay.execute(ABRIR.sql, ABRIR.args(self.subscricao, self.tenant, INICIO, FIM, PRECO))
        ciclo = str(self.pay.fetchone()[0])
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay, COBRANCA.sql,
            COBRANCA.args(str(uuid.uuid4()), self.tenant, ciclo, conta_pme, "fakeprovider",
                          "referencia", "REF1", PRECO, datetime.datetime.now(datetime.timezone.utc)),
        )

    def test_uma_cobranca_de_encomenda_na_conta_da_kamba_e_recusada_pelo_g1(self) -> None:
        encomenda = self.criar_encomenda(self.tenant)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay,
            "INSERT INTO platform.payment_charges (tenant_id, order_id, account_id, "
            "provider, metodo, amount_minor, valid_until) "
            "VALUES (%s, %s, %s, 'manual', 'manual', %s, now())",
            (self.tenant, encomenda, self.conta, PRECO),
        )

    def test_a_conta_da_kamba_e_visivel_so_ao_papel_do_billing(self) -> None:
        sql = (
            "SELECT count(*) FROM platform.payment_accounts "
            " WHERE beneficiary_kind = 'plataforma_receita_propria' AND id = %s"
        )
        self.pay.execute(sql, (self.conta,))
        self.assertEqual(self.pay.fetchone()[0], 1)
        for papel in ("app", "audit"):
            cursor = self.cursor_papel(papel, self.tenant)
            cursor.execute(sql, (self.conta,))
            self.assertEqual(cursor.fetchone()[0], 0, papel)

    def test_o_billing_nao_le_o_token_nem_as_credenciais(self) -> None:
        for coluna in ("webhook_token", "credenciais_ref"):
            self.assertErroSql(
                PRIVILEGIO_INSUFICIENTE, self.pay,
                f"SELECT {coluna} FROM platform.payment_accounts WHERE id = %s",
                (self.conta,),
            )

    def test_rls_cruzada_nas_subscricoes_e_nos_ciclos(self) -> None:
        ciclo = self.abrir()
        outro = self.criar_tenant()
        vizinho = self.cursor_papel("app", outro)
        for tabela, chave in (("subscriptions", self.subscricao), ("billing_cycles", ciclo)):
            vizinho.execute(f"SELECT count(*) FROM platform.{tabela} WHERE id = %s", (chave,))
            self.assertEqual(vizinho.fetchone()[0], 0, tabela)
        dono = self.cursor_papel("app", self.tenant)
        dono.execute("SELECT count(*) FROM platform.billing_cycles WHERE id = %s", (ciclo,))
        self.assertEqual(dono.fetchone()[0], 1, "o controlo positivo")

    def test_o_billing_nao_escreve_um_ciclo_noutro_tenant(self) -> None:
        outro = self.criar_tenant()
        pay_de_outro = self.cursor_papel("pay", outro)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, pay_de_outro, ABRIR.sql,
            ABRIR.args(self.subscricao, self.tenant, "2027-03-01", "2027-04-01", PRECO),
        )


class TestCriterio4PagamentoAutenticado(ComBilling):
    def setUp(self) -> None:
        super().setUp()
        self.ciclo = self.abrir()
        self.cobranca = self.cobranca_do_ciclo(self.ciclo)

    def test_dez_vezes_o_mesmo_pagamento_da_uma_transicao_e_um_evento(self) -> None:
        import jsonschema

        from tests_pagamentos.test_fks_e_mapa import esquema, verificador

        app = self.cursor_papel("app", self.tenant)
        aceites = 0
        for _ in range(10):
            app.execute("SAVEPOINT tentativa")
            try:
                self.appendar(
                    app, self.cobranca, self.conta, "pagamento_confirmado",
                    p_valor_minor=PRECO, p_provider_event_id="evt-ciclo-1",
                )
                aceites += 1
                app.execute("RELEASE SAVEPOINT tentativa")
            except Exception:  # noqa: BLE001 — a repeticao recusada e o esperado
                app.execute("ROLLBACK TO SAVEPOINT tentativa")
        self.confirmar(app, self.tenant)
        self.assertEqual(aceites, 1, "uma cobranca paga nao volta a pagar")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "paga")
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "paga")
        eventos = self.eventos_de_ciclo_pago(self.ciclo)
        self.assertEqual(len(eventos), 1)
        envelope = eventos[0]
        self.assertEqual(envelope["agregado"]["tipo"], "billing_cycle")
        self.assertEqual(envelope["payload"]["charge_id"], self.cobranca)
        self.assertEqual(envelope["payload"]["valor_minor"], PRECO)
        self.assertEqual(
            (envelope["payload"]["periodo_inicio"], envelope["payload"]["periodo_fim"]),
            (INICIO, FIM),
        )
        jsonschema.validate(envelope, esquema("billing.cycle_paid"), format_checker=verificador())

    def test_o_ciclo_nao_fica_paga_sem_a_cobranca_paga(self) -> None:
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay,
            "UPDATE platform.billing_cycles SET estado = 'paga' WHERE id = %s", (self.ciclo,),
        )
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.semente,
            "UPDATE platform.billing_cycles SET estado = 'paga' WHERE id = %s", (self.ciclo,),
        )

    def test_o_grafo_do_ciclo(self) -> None:
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay,
            "UPDATE platform.billing_cycles SET estado = 'aberto' WHERE id = %s", (self.ciclo,),
        )
        self.pay.execute(
            "UPDATE platform.billing_cycles SET estado = 'em_atraso' WHERE id = %s", (self.ciclo,)
        )
        self.confirmar(self.pay, self.tenant)
        app = self.cursor_papel("app", self.tenant)
        self.appendar(app, self.cobranca, self.conta, "pagamento_confirmado", p_valor_minor=PRECO)
        self.confirmar(app, self.tenant)
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "paga", "em_atraso tambem paga")
        self.assertEqual(len(self.eventos_de_ciclo_pago(self.ciclo)), 1)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay,
            "UPDATE platform.billing_cycles SET estado = 'anulado' WHERE id = %s", (self.ciclo,),
        )

    def test_uma_confirmacao_manual_do_dono_nao_entra_numa_cobranca_de_ciclo(self) -> None:
        contacto = factories.contacto(self.semente, self.tenant)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.semente,
            "INSERT INTO platform.manual_confirmations (tenant_id, charge_id, fase, "
            "actor_contact_id, canal_msg_id) VALUES (%s, %s, 'declaracao_cliente', %s, 'm1')",
            (self.tenant, self.cobranca, contacto),
        )


class TestCriterio5DuplaDeOps(ComBilling):
    def setUp(self) -> None:
        super().setUp()
        self.ciclo = self.abrir()
        self.cobranca = self.cobranca_do_ciclo(self.ciclo)
        self.ops_a = str(uuid.uuid4())
        self.ops_b = str(uuid.uuid4())

    def test_uma_aprovacao_nao_conclui_e_a_segunda_de_outra_pessoa_conclui(self) -> None:
        self.assertEqual(self.aprovar(self.cobranca, self.ops_a), (1, False, False))
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "cobranca_emitida")
        self.assertEqual(self.aprovar(self.cobranca, self.ops_a), (1, False, True),
                         "a mesma pessoa outra vez nao e segunda aprovacao")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

        self.assertEqual(self.aprovar(self.cobranca, self.ops_b, "segunda leitura"), (2, True, False))
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "paga")
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "paga")
        self.assertEqual(len(self.eventos_de_ciclo_pago(self.ciclo)), 1)
        self.semente.execute(
            "SELECT actor_kind, actor_id, authn_method, motivo FROM platform.payment_events "
            " WHERE charge_id = %s AND tipo_evento = 'pagamento_confirmado'",
            (self.cobranca,),
        )
        self.assertEqual(
            [tuple(map(str, linha)) for linha in self.semente.fetchall()],
            [("ops", self.ops_b, "manual", "segunda leitura")],
        )
        self.assertEqual(self.aprovar(self.cobranca, str(uuid.uuid4()))[1:], (True, True),
                         "depois de paga, uma terceira nao escreve nada")

    def test_sem_motivo_ou_com_outro_valor_nao_ha_aprovacao(self) -> None:
        for motivo, valor in (("   ", PRECO), ("extracto", PRECO + 1)):
            with self.subTest(motivo=motivo, valor=valor):
                self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.pay, CONFIRMAR_OPS.sql,
                    CONFIRMAR_OPS.args(self.cobranca, self.ops_a, motivo, valor),
                )

    def test_o_ledger_recusa_a_confirmacao_manual_sem_a_dupla(self) -> None:
        self.aprovar(self.cobranca, self.ops_a)
        casos = (
            {"p_actor_kind": "ops", "p_actor_id": self.ops_a, "p_motivo": "so um"},
            {"p_actor_kind": "dono", "p_actor_id": self.ops_a, "p_motivo": "o dono"},
        )
        for campos in casos:
            with self.subTest(**campos):
                sql, argumentos = self.sql_da_porta(
                    p_charge_id=self.cobranca, p_tipo_evento="pagamento_confirmado",
                    p_account_id=self.conta, p_valor_minor=PRECO, p_authn_method="manual",
                    **campos,
                )
                self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
                self.assertErroSql(VIOLACAO_DE_CHECK, self.pay, sql, argumentos)

    def test_duas_aprovacoes_sem_motivo_no_evento_nao_entram(self) -> None:
        self.semente.execute(
            "INSERT INTO platform.billing_ops_approvals (tenant_id, charge_id, actor_id, "
            "motivo, valor_minor) VALUES (%s, %s, %s, 'a', %s), (%s, %s, %s, 'b', %s)",
            (self.tenant, self.cobranca, self.ops_a, PRECO,
             self.tenant, self.cobranca, self.ops_b, PRECO),
        )
        sql, argumentos = self.sql_da_porta(
            p_charge_id=self.cobranca, p_tipo_evento="pagamento_confirmado",
            p_account_id=self.conta, p_valor_minor=PRECO, p_authn_method="manual",
            p_actor_kind="ops", p_actor_id=self.ops_b, p_motivo=" ",
        )
        self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.pay, sql, argumentos)

    def test_o_app_nao_chama_a_porta_de_ops(self) -> None:
        app = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app, CONFIRMAR_OPS.sql,
            CONFIRMAR_OPS.args(self.cobranca, self.ops_a, "x", PRECO),
        )


class TestCriterio6Preco(ComBilling):
    def test_o_preco_novo_nao_toca_no_ciclo_emitido_e_fica_auditado(self) -> None:
        ciclo = self.abrir()
        novo = self.publicar_preco(self.plano, 1_200_000, "2026-11-15")
        self.semente.execute(
            "SELECT valor_minor, estado FROM platform.billing_cycles WHERE id = %s", (ciclo,)
        )
        self.assertEqual(tuple(self.semente.fetchone()), (PRECO, "cobranca_emitida"))
        self.semente.execute(
            "SELECT actor_type, actor_id, action FROM platform.audit_log "
            " WHERE entity = 'price_book' AND entity_id = %s",
            (novo,),
        )
        self.assertEqual(
            [tuple(linha) for linha in self.semente.fetchall()],
            [("staff", ACTOR_DE_PRECO, "price.update")],
        )
        seguinte = self.abrir(valor=1_200_000, inicio="2026-12-01", fim="2027-01-01")
        self.semente.execute(
            "SELECT valor_minor FROM platform.billing_cycles WHERE id = %s", (seguinte,)
        )
        self.assertEqual(self.semente.fetchone()[0], 1_200_000)

    def test_o_valor_de_um_ciclo_nao_muda_depois_de_abrir(self) -> None:
        ciclo = self.abrir()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.pay,
            "UPDATE platform.billing_cycles SET valor_minor = 1 WHERE id = %s", (ciclo,),
        )
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.semente,
            "UPDATE platform.billing_cycles SET valor_minor = 1 WHERE id = %s", (ciclo,),
        )

    def test_um_preco_sem_actor_nao_entra_e_so_o_lote_escreve(self) -> None:
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.semente,
            "INSERT INTO platform.price_book (plano, valor_minor, valido_de) "
            "VALUES (%s, 1, '2030-01-01')",
            (self.plano,),
        )
        for papel in ("pay", "app"):
            cursor = self.cursor_papel(papel, self.tenant)
            self.assertErroSql(
                PRIVILEGIO_INSUFICIENTE, cursor,
                "INSERT INTO platform.price_book (plano, valor_minor, valido_de) "
                "VALUES (%s, 1, '2030-01-01')",
                (self.plano,),
            )
        lote = self.cursor_papel("batch", None)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, lote,
            "UPDATE platform.price_book SET valor_minor = 1 WHERE plano = %s", (self.plano,),
        )


class TestCriterio7Sombra(ComBilling):
    def setUp(self) -> None:
        super().setUp()
        self.conta_pme = self.criar_conta(self.tenant)
        self.paga = self.criar_cobranca(self.tenant, self.conta_pme, estado="paga")
        self.semente.execute(
            "SELECT id, order_id, valor_minor FROM platform.payment_events "
            " WHERE charge_id = %s AND tipo_evento = 'pagamento_confirmado'",
            (self.paga,),
        )
        evento, encomenda, valor = self.semente.fetchone()
        self.evento, self.encomenda, self.valor = int(evento), str(encomenda), int(valor)

    def gravar(self, cursor, **campos):
        valores = {
            "tenant": self.tenant, "encomenda": self.encomenda, "evento": self.evento,
            "base": self.valor, "taxa": 250, "comissao": self.valor * 250 // 10_000,
        }
        valores.update(campos)
        cursor.execute(
            SOMBRA_GRAVAR.sql,
            SOMBRA_GRAVAR.args(*valores.values()),
        )
        return cursor.rowcount

    def test_a_sombra_mede_o_pagamento_autenticado_uma_vez(self) -> None:
        self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.pay.execute(SOMBRA_POR_MEDIR.sql, SOMBRA_POR_MEDIR.args(100))
        self.assertEqual([int(linha[0]) for linha in self.pay.fetchall()], [self.evento])
        self.assertEqual(self.gravar(self.pay), 1)
        self.assertEqual(self.gravar(self.pay), 0, "o UNIQUE (payment_event_id) absorve")
        self.confirmar(self.pay, self.tenant)
        self.pay.execute(SOMBRA_POR_MEDIR.sql, SOMBRA_POR_MEDIR.args(100))
        self.assertEqual(self.pay.fetchall(), ())
        self.semente.execute(
            "SELECT modo, comissao_minor FROM platform.commission_accruals "
            " WHERE payment_event_id = %s", (self.evento,),
        )
        self.assertEqual(tuple(self.semente.fetchone()), ("sombra", self.valor * 250 // 10_000))

    def test_so_sombra_e_so_o_calculo_da_taxa(self) -> None:
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.semente,
            "INSERT INTO platform.commission_accruals (tenant_id, order_id, "
            "payment_event_id, base_minor, taxa_bps, comissao_minor, modo) "
            "VALUES (%s, %s, %s, %s, 0, 0, 'facturavel')",
            (self.tenant, self.encomenda, self.evento, self.valor),
        )
        self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay, SOMBRA_GRAVAR.sql,
            SOMBRA_GRAVAR.args(self.tenant, self.encomenda, self.evento, self.valor, 250, 1),
        )
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay, SOMBRA_GRAVAR.sql,
            SOMBRA_GRAVAR.args(self.tenant, self.encomenda, self.evento, self.valor + 1, 0, 0),
        )

    def test_a_sombra_nao_deriva_de_um_evento_que_nao_e_pagamento_autenticado(self) -> None:
        self.semente.execute(
            "SELECT id FROM platform.payment_events "
            " WHERE charge_id = %s AND tipo_evento = 'referencia_emitida'", (self.paga,),
        )
        outro = int(self.semente.fetchone()[0])
        self.pay.execute(CONTEXTO.sql, CONTEXTO.args(self.tenant))
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.pay, SOMBRA_GRAVAR.sql,
            SOMBRA_GRAVAR.args(self.tenant, self.encomenda, outro, self.valor, 0, 0),
        )

    def test_o_app_nao_escreve_sombra(self) -> None:
        app = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app, SOMBRA_GRAVAR.sql,
            SOMBRA_GRAVAR.args(self.tenant, self.encomenda, self.evento, self.valor, 0, 0),
        )


class TestCriterio8Plano(ComBilling):
    def test_o_plano_e_os_entitlements_mudam_numa_instrucao(self) -> None:
        factories.entitlement(self.semente, self.tenant, modulo="antigo", limites={})
        lote = self.cursor_papel("batch", None)
        novo = f"plano_{uuid.uuid4().hex[:10]}"
        modulos = [{"modulo": "vendedor", "ativo": True, "limites": {"manual_max_minor": 5}}]
        lote.execute(MUDAR_PLANO.sql, MUDAR_PLANO.args(self.tenant, novo, json.dumps(modulos)))
        self.assertEqual(tuple(lote.fetchone()), (1, 1, 1, 1))
        self.confirmar(lote, None)
        self.semente.execute(
            "SELECT s.plano, t.plano FROM platform.subscriptions s "
            "  JOIN platform.tenants t ON t.id = s.tenant_id WHERE s.tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(tuple(self.semente.fetchone()), (novo, novo))
        self.semente.execute(
            "SELECT modulo, ativo FROM platform.entitlements WHERE tenant_id = %s ORDER BY 1",
            (self.tenant,),
        )
        self.assertEqual(
            [tuple(linha) for linha in self.semente.fetchall()],
            [("antigo", False), ("vendedor", True)],
        )
        self.semente.execute(
            "SELECT platform.ten_tecto(%s, 'manual_max_minor')", (self.tenant,)
        )
        self.assertEqual(self.semente.fetchone()[0], 5)

    def test_em_atraso_mantem_os_limites(self) -> None:
        factories.entitlement(
            self.semente, self.tenant, modulo="vendedor", limites={"manual_max_minor": 7}
        )
        lote = self.cursor_papel("batch", None)
        lote.execute(
            "UPDATE platform.subscriptions SET estado = 'em_atraso' WHERE id = %s",
            (self.subscricao,),
        )
        self.confirmar(lote, None)
        self.semente.execute("SELECT platform.ten_tecto(%s, 'manual_max_minor')", (self.tenant,))
        self.assertEqual(self.semente.fetchone()[0], 7)
        self.pay.execute(SUBSCRICOES.sql)
        self.assertIn(
            self.subscricao, {str(linha[0]) for linha in self.pay.fetchall()},
            "em_atraso continua a abrir ciclo",
        )

    def test_so_o_lote_muda_o_plano(self) -> None:
        for papel in ("app", "pay"):
            cursor = self.cursor_papel(papel, self.tenant)
            self.assertErroSql(
                PRIVILEGIO_INSUFICIENTE, cursor, MUDAR_PLANO.sql,
                MUDAR_PLANO.args(self.tenant, "outro", "[]"),
            )


class TestReversivel(ComBilling):
    def test_o_downgrade_recusa_com_cobrancas_de_ciclo(self) -> None:
        """Nao exige estar na cabeca (licao do KAM-197): so mede a recusa."""
        self.abrir()
        revisao = next(
            (RAIZ / "db" / "migrations" / "versions").glob("*_billing_da_plataforma.py")
        )
        anterior = None
        for linha in revisao.read_text(encoding="utf-8").splitlines():
            if linha.startswith("down_revision = "):
                anterior = linha.split('"')[1]
        self.assertIsNotNone(anterior)
        resultado = alembic("downgrade", anterior)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("downgrade do billing recusado", resultado.stderr + resultado.stdout)
