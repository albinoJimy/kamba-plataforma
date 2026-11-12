"""O `downgrade` da `0046` (KAM-050): aditivo, pelos objectos, e com recusa.

O DoD do KAM-050 pede «`downgrade` aditivo e testado». O ciclo da cadeia ja corre
no *gate* 8 (`tests/test_migracao.TestCiclo`); o que este ficheiro mede e o que
aquele nao ve, pela razao escrita no `test_downgrade_0033.py`: que **cada coisa
que a revisao muda volta a ser o que era**, pelo nome, e que a descida
**recusa** em vez de apagar quando ha dados que dependem dela.

```text
em head        21 arestas, 4 excepcoes, a accao nova, o ramo do reembolso,
               o indice parcial                              <- SONDA POSITIVA
downgrade      12 arestas, 3 excepcoes, sem a accao, o corpo da 0030, a
               unicidade da 0033
upgrade        tudo de volta
com dados      uma encomenda com a quarta excepcao, ou duas reservas na mesma
               linha: a descida recusa, e a base fica em head
```

A revisao anterior le-se do proprio ficheiro da `0046` (`down_revision`), e nao
se escreve aqui: a cadeia deste lote numera-se na integracao.

**A linha de `audit_log` com a accao nova nao se mede aqui**, e de proposito: o
registo e *append-only* e ninguem a apaga, pelo que um ensaio que a escrevesse
deixava a base desta suite sem `downgrade` possivel. A recusa por ela e o mesmo
codigo que a das outras duas, e a de `privacy.dsar_*` da `0038` ja e o
precedente medido.
"""

from __future__ import annotations

import importlib.util
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao
from tests.base import alembic, alembic_ok, em_head, exigir_base_descartavel

#: O ficheiro da revisao, lido para saber a anterior.
REVISAO = next(
    (Path(__file__).resolve().parents[1] / "migrations" / "versions").glob(
        "0046_*.py"
    )
)


def _anterior() -> str:
    spec = importlib.util.spec_from_file_location("revisao_0046", REVISAO)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return str(modulo.down_revision)


ANTERIOR = _anterior()


class TestDowngradeDa0046(unittest.TestCase):
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
        self._tenants: list[str] = []

    def tearDown(self) -> None:
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self._tenants:
                for tabela in ("stock_reservations", "orders_mirror"):
                    self.cursor.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                        (tenant,),
                    )
                self.cursor.execute("DELETE FROM platform.contacts WHERE tenant_id = %s", (tenant,))
                self.cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
        finally:
            self.conexao.close()

    def _um(self, sql: str, parametros: tuple = ()) -> object:
        self.cursor.execute(sql, parametros)
        return self.cursor.fetchone()[0]

    def estado(self) -> dict[str, object]:
        """As cinco coisas que a revisao muda, lidas do catalogo e da tabela."""
        return {
            "arestas": self._um("SELECT count(*) FROM platform.order_state_graph"),
            "excepcao": "pagamento_apos_cancelamento"
            in str(
                self._um(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    " WHERE conname = 'orders_mirror_excepcao_ck'"
                )
            ),
            "accao": "order.refund_record"
            in str(
                self._um(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    " WHERE conname = 'audit_log_action'"
                )
            ),
            "ramo": "reembolsada exige"
            in str(
                self._um(
                    "SELECT pg_get_functiondef('platform.order_estado_exige_log()'"
                    "::regprocedure)"
                )
            ),
            "indice_parcial": self._um(
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'platform' "
                "   AND indexname = 'stock_reservations_linha_viva_uq'"
            ),
            "unicidade_da_0033": self._um(
                "SELECT count(*) FROM pg_constraint "
                " WHERE conname = 'stock_reservations_linha_uq'"
            ),
        }

    EM_HEAD = {
        "arestas": 21,
        "excepcao": True,
        "accao": True,
        "ramo": True,
        "indice_parcial": 1,
        "unicidade_da_0033": 0,
    }
    ANTES = {
        "arestas": 12,
        "excepcao": False,
        "accao": False,
        "ramo": False,
        "indice_parcial": 0,
        "unicidade_da_0033": 1,
    }

    def test_em_head_a_revisao_esta_la(self) -> None:
        """A sonda positiva: sem ela, as outras ficavam verdes a ler zero."""
        self.assertEqual(self.estado(), self.EM_HEAD)

    def test_o_downgrade_repoe_o_que_era_e_o_upgrade_volta(self) -> None:
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.estado(), self.ANTES)
        # O corpo da `0030` volta **igual**, e nao so sem o ramo: o `paga`
        # continua a exigir evento autenticado.
        corpo = str(
            self._um(
                "SELECT pg_get_functiondef('platform.order_estado_exige_log()'"
                "::regprocedure)"
            )
        )
        self.assertIn("paga exige evento autenticado do PAY", corpo)
        self.assertNotIn("KAM-050", corpo)
        alembic_ok("upgrade", "head")
        self.assertEqual(self.estado(), self.EM_HEAD)

    def _encomenda(self) -> str:
        tenant = str(uuid.uuid4())
        self._tenants.append(tenant)
        self.cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome) "
            "VALUES (%s, 'pme', 'Loja do downgrade da 0046')",
            (tenant,),
        )
        self.cursor.execute(
            "INSERT INTO platform.contacts (tenant_id) VALUES (%s) RETURNING contact_id",
            (tenant,),
        )
        contacto = str(self.cursor.fetchone()[0])
        self.cursor.execute(
            "INSERT INTO platform.orders_mirror "
            "       (tenant_id, contact_id, intent_key, total_minor, lines_snapshot) "
            "VALUES (%s, %s, %s, 1000, '[]'::jsonb) RETURNING id",
            (tenant, contacto, f"ik-0046-{uuid.uuid4()}"),
        )
        return str(self.cursor.fetchone()[0])

    def _recusa(self, motivo: str) -> None:
        resultado = alembic("downgrade", ANTERIOR)
        self.assertNotEqual(resultado.returncode, 0, "a descida tinha de recusar")
        self.assertIn("downgrade da 0046 recusado", resultado.stderr + resultado.stdout)
        self.assertIn(motivo, resultado.stderr + resultado.stdout)
        self.assertEqual(self.estado(), self.EM_HEAD, "a base ficou em head")

    def test_uma_encomenda_com_a_quarta_excepcao_faz_recusar(self) -> None:
        encomenda = self._encomenda()
        self.cursor.execute(
            "UPDATE platform.orders_mirror SET excepcao = 'pagamento_apos_cancelamento' "
            " WHERE id = %s",
            (encomenda,),
        )
        self._recusa("pagamento_apos_cancelamento")

    def test_duas_reservas_na_mesma_linha_fazem_recusar(self) -> None:
        encomenda = self._encomenda()
        tenant = self._tenants[-1]
        for estado, motivo in (("libertada", "expirada"), ("ativa", None)):
            self.cursor.execute(
                "INSERT INTO platform.stock_reservations "
                "       (tenant_id, order_id, line_no, sku, qty, expira_at, estado, "
                "        motivo, libertada_at) "
                "VALUES (%s, %s, 0, 'arroz-5kg', 1, now() + interval '48 hours', "
                "        %s, %s, CASE WHEN %s = 'libertada' THEN now() END)",
                (tenant, encomenda, estado, motivo, estado),
            )
        self._recusa("mais do que uma reserva")


if __name__ == "__main__":
    unittest.main()
