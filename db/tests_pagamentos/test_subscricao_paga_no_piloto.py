"""Os ciclos pagos que o `piloto-export` le, pela via certa (KAM-109).

A prova de pagamento de H1 e «evento de pagamento auditado ou comprovativo
bancario conciliado». Na base sao duas vias, e o `piloto-export` tem de as
distinguir: o `pagamento_confirmado` **autenticado pelo facilitador** (`hmac`)
e a **confirmacao de ops com dupla aprovacao** (`manual`, `ops`). Um ciclo
emitido e nao pago nao aparece.

Os pagamentos fazem-se pela maquinaria do KAM-059 (`ComBilling`), e a leitura
pelo papel `kamba_batch`, que e o do comando.

**O nome ordena-o depois do `test_subscricao_e_billing.py`**, pela razao que
esse ficheiro escreve: o `downgrade` do billing recusa-se quando ha cobrancas de
ciclo, e este ficheiro deixa-as, como aquele.
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import piloto_export as pe  # noqa: E402
from tests_pagamentos.test_subscricao_e_billing import FIM, INICIO, PRECO, ComBilling  # noqa: E402


class TestCiclosPagosNoPiloto(ComBilling):
    def setUp(self) -> None:
        super().setUp()
        self.ciclo = self.abrir()
        self.cobranca = self.cobranca_do_ciclo(self.ciclo)
        self.coorte = pe.ler_coorte(f"pme,tenant_id,saida_dia,motivo\nP01,{self.tenant},,\n")

    def _exportar(self, ate: dt.date | None = None) -> list[dict]:
        batch = self.cursor_papel("batch")
        bruto = pe.exportar(batch, self.coorte, sintetico=True, ate=ate)
        return bruto["pmes"][0]["ciclos_pagos"]

    def _hoje(self) -> dt.date:
        self.semente.execute("SELECT (now() AT TIME ZONE 'Africa/Luanda')::date")
        return self.semente.fetchone()[0]

    def test_emitido_e_nao_pago_nao_aparece(self) -> None:
        self.assertEqual(self._exportar(), [])

    def test_pago_pelo_facilitador(self) -> None:
        pay = self.cursor_papel("pay", self.tenant)
        self.appendar(pay, self.cobranca, self.conta, "pagamento_confirmado", p_valor_minor=PRECO)
        self.confirmar(pay, self.tenant)
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "paga")
        hoje = self._hoje()
        # Pago hoje: so aparece numa exportacao que inclua hoje.
        self.assertEqual(self._exportar(), [])
        self.assertEqual(self._exportar(ate=hoje), [
            {"inicio": INICIO, "fim": FIM, "pago_em": hoje.isoformat(),
             "valor_minor": PRECO, "moeda": "AOA", "via": "facilitador"},
        ])

    def test_pago_por_ops_com_dupla_aprovacao(self) -> None:
        self.aprovar(self.cobranca, str(uuid.uuid4()))
        self.aprovar(self.cobranca, str(uuid.uuid4()), "segunda leitura")
        self.assertEqual(self.estado_do_ciclo(self.ciclo), "paga")
        ciclos = self._exportar(ate=self._hoje())
        self.assertEqual([c["via"] for c in ciclos], ["ops"])
        self.assertEqual((ciclos[0]["inicio"], ciclos[0]["fim"]), (INICIO, FIM))
