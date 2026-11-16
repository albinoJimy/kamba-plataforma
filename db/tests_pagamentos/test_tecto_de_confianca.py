"""O tecto de confianca na cobranca, contra a base (KAM-096, criterio 6).

A barreira e o *trigger* `payment_charges_dentro_do_tecto` da revisao da
confianca gradual: uma cobranca de **encomenda** acima do tecto do tenant, ou de
um tenant sem nivel, nao entra — na mesma instrucao que a escreve. O
`assertWithinTrustCeiling` do TypeScript e a mensagem que o agente mostra; isto e
o que vale quando alguem escrever um segundo caminho de codigo.

```text
no limite         tecto entra, tecto + 1 centimo nao          (adversarial g)
por pedido        um total acima do tecto nao se cobra as prestacoes
sem nivel         recusa: sem K1 nao ha nivel, nem producao   (criterio 2)
descida           na mesma transaccao, a cobranca seguinte ja nao cabe
isolamento        o tecto de B nao vale para A                (ADR-015)
ciclo de billing  nao le o tecto: e receita da plataforma, nao venda da PME
```

**Nenhum ensaio faz `commit` de uma alteracao do nivel.** O nascimento pelas
sementes e do administrador (superutilizador), que a revisao nao audita; uma
mudanca *committed* escrevia uma linha `trust.tecto` no `audit_log`
*append-only*, e o `test_downgrade` desta suite deixava de poder descer a `0028`.
A concorrencia, que precisa de *commit*, mede-se na `tests_lote`.
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path

from tests import factories
from tests.base import VIOLACAO_DE_CHECK, ConsultaDoTypeScript
from tests_pagamentos.base import PROVIDER, ComLedger
from tests_pagamentos.test_subscricao_e_billing import ComBilling

SQL_TS = Path(__file__).resolve().parents[2] / "packages" / "core-ts" / "src" / "confianca" / "sql.ts"

#: 50 000 Kz, o tecto do nivel 0 das sementes. 1 Kz = 100 centimos.
TECTO = factories.TECTO_DO_NIVEL_ZERO


class ComTecto(ComLedger):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)

    def tenant_no_nivel(self, nivel: int, tecto: int) -> tuple[str, str]:
        """Um tenant semeado directamente num nivel, com conta. Devolve `(tenant, conta)`."""
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        factories.confianca(self.semente, tenant, nivel=nivel, tecto=tecto)
        return tenant, self.criar_conta(tenant)

    def cobrar(self, cursor, tenant: str, conta: str, valor: int,
               total: int | None = None) -> tuple[str, tuple]:
        """O `INSERT` de uma cobranca de encomenda, como a aplicacao a escreve."""
        return (
            "INSERT INTO platform.payment_charges (id, tenant_id, account_id, order_id, provider, "
            "metodo, referencia, amount_minor, valid_until) "
            "VALUES (%s, %s, %s, %s, %s, 'referencia', %s, %s, %s)",
            (
                str(uuid.uuid4()), tenant, conta,
                self.criar_encomenda(tenant, total_minor=valor if total is None else total),
                PROVIDER, f"REF{uuid.uuid4().hex[:12]}", valor,
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
            ),
        )


class TestTectoNaCobranca(ComTecto):
    def test_adversarial_g_no_limite_entra_e_um_centimo_acima_nao(self) -> None:
        app = self.cursor_papel("app", self.tenant)
        app.execute(*self.cobrar(app, self.tenant, self.conta, TECTO))
        self.assertEqual(app.rowcount, 1)
        self.assertErroSql(VIOLACAO_DE_CHECK, app, *self.cobrar(app, self.tenant, self.conta, TECTO + 1))

    def test_o_tecto_e_do_pedido_e_nao_da_cobranca(self) -> None:
        """Uma encomenda de 200 000 Kz nao se cobra as prestacoes de 50 000.

        A `payment_charges_activa_uq` so cobre os estados activos: depois de
        `paga` ou `expirada` entra outra tentativa da mesma encomenda. Por isso o
        *trigger* le o `total_minor` do pedido, e nao so o montante.
        """
        app = self.cursor_papel("app", self.tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, app,
                           *self.cobrar(app, self.tenant, self.conta, TECTO, total=TECTO * 4))
        app.execute(*self.cobrar(app, self.tenant, self.conta, TECTO - 1, total=TECTO))
        self.assertEqual(app.rowcount, 1)

    def test_sem_nivel_nenhuma_cobranca_de_encomenda_entra(self) -> None:
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        conta = self.criar_conta(tenant)
        app = self.cursor_papel("app", tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, app, *self.cobrar(app, tenant, conta, 1))
        # O administrador tambem: o *trigger* e `ENABLE ALWAYS` e vale para todos.
        admin = self.cursor_papel("admin", tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, *self.cobrar(admin, tenant, conta, 1))

    def test_a_descida_vale_para_a_cobranca_seguinte_na_mesma_transaccao(self) -> None:
        tenant, conta = self.tenant_no_nivel(1, 15_000_000)
        cursor = self.cursor_papel("admin", tenant)
        cursor.execute("SET LOCAL ROLE kamba_app")
        cursor.execute("SAVEPOINT antes")
        cursor.execute(*self.cobrar(cursor, tenant, conta, 6_000_000))
        cursor.execute("ROLLBACK TO SAVEPOINT antes")
        cursor.execute("RESET ROLE")
        cursor.execute("SET LOCAL ROLE kamba_batch")
        q = ConsultaDoTypeScript("SQL_DEFINIR_NIVEL", SQL_TS)
        cursor.execute(q.sql, q.args(tenant, 0, str(TECTO), "sancao", "sistema:2026-11-16.1", "2026-11-16.1"))
        self.assertEqual(len(cursor.fetchall()), 1)
        cursor.execute("RESET ROLE")
        cursor.execute("SET LOCAL ROLE kamba_app")
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, *self.cobrar(cursor, tenant, conta, 6_000_000))
        cursor.execute(*self.cobrar(cursor, tenant, conta, TECTO))
        self.assertEqual(cursor.rowcount, 1)


class TestIsolamentoDoTecto(ComTecto):
    def test_o_tecto_de_b_nao_vale_para_a(self) -> None:
        b, conta_b = self.tenant_no_nivel(1, 15_000_000)
        app_a = self.cursor_papel("app", self.tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, app_a, *self.cobrar(app_a, self.tenant, self.conta, 6_000_000))
        app_b = self.cursor_papel("app", b)
        app_b.execute(*self.cobrar(app_b, b, conta_b, 6_000_000))
        self.assertEqual(app_b.rowcount, 1)


class TestCicloNaoLeOTecto(ComBilling):
    def test_um_tenant_sem_nivel_paga_a_subscricao(self) -> None:
        """A cobranca de um ciclo e receita da plataforma: o tecto da PME nao a limita."""
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        subscricao = self.criar_subscricao(tenant, self.plano)
        pay = self.cursor_papel("pay", tenant)
        self.assertIsNotNone(self.abrir(cursor=pay, tenant=tenant, subscricao=subscricao))
