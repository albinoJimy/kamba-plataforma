"""O classificador de screening pelo *gate* real, contra PostgreSQL (KAM-195, criterio 2).

O `services/agr/tests/test_llm_screening.py` prova a mesma coisa com o leitor
da tabela num duplo. Aqui **so o transporte para o proxy e duplo**: a porta e a
`PortaSobreDestinos` do nucleo, a ler `platform.tenant_destinations` como
`kamba_app` (o `arrancar` do AGR com ligacao), e a linha vai para
`dat.llm_call_log` pelo `registo.escrever` como `kamba_app`. E o que prova as
duas metades do criterio contra a base:

* com o destino `autorizado` para a `classificacao_de_catalogo`, a chamada
  passa o *gate* e a linha `ok` entra, com o custo — o `CHECK` da `0047` aceita o
  papel e o da `finalidade_do_screening` aceita a finalidade do destino;
* com o destino autorizado so para a `conversa`, a chamada do screening sai em
  `destino_negado`, e nada vai para o proxy.

Canario: `test_o_controlo_sem_destino_nenhum_nega`. Uma porta que negasse
sempre passava a metade negativa; uma que autorizasse sempre, a positiva. As
duas juntas so passam com a porta a ler a finalidade do papel.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import ligacao
from tests_agr.test_llm_call_log import TABELA, _ComLlm

from kamba_agr import metricas as metricas_mod  # noqa: E402
from kamba_agr.llm import aliases as aliases_mod  # noqa: E402
from kamba_agr.llm import destinos as llm_destinos  # noqa: E402
from kamba_agr.llm import precos as precos_mod  # noqa: E402
from kamba_agr.llm import screening  # noqa: E402
from kamba_agr.llm.cliente import ClienteDeLlm  # noqa: E402
from kamba_agr.llm.erros import DestinoNegado  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[2]
REAIS = aliases_mod.ler(RAIZ / "llm")

#: Os mesmos da `test_destinos_schema.py`: um destino `autorizado` exige-os.
APD_REF = "APD/2026/000-TESTE"
CONTRATO_REF = "contratos/2026/teste"

#: O preco do modelo do alias real (`por_decidir`), para a linha levar custo.
PRECOS = {
    ("anthropic", "por_decidir"): precos_mod.Preco(
        "anthropic", "por_decidir",
        Decimal("0.10"), Decimal("0.01"), Decimal("0.50"), "CONFIRMADO", "ensaio",
    ),
}


class _Transporte:
    """O proxy, em duplo: conta as chamadas e responde um veredicto."""

    def __init__(self) -> None:
        self.chamadas = 0

    def __call__(self, _url, _cabecalhos, _corpo, _timeout):  # noqa: ANN001, ANN204
        self.chamadas += 1
        return (
            200,
            {
                "model": "anthropic/por_decidir",
                "choices": [{"message": {"content": '{"decisao":"permitida","confianca":0.9}'}}],
                "usage": {"prompt_tokens": 400, "completion_tokens": 12},
            },
            {},
        )


class TestOScreeningPeloGateReal(_ComLlm):
    def setUp(self) -> None:
        super().setUp()
        # Depois do `super().setUp()`: os `addCleanup` correm em LIFO, pelo que
        # os destinos saem **antes** do tenant que referenciam.
        self.addCleanup(self._limpar_destinos)

    def _limpar_destinos(self) -> None:
        # Uma linha `classificacao_de_catalogo` que ficasse fazia o `downgrade`
        # da `finalidade_do_screening` recusar-se nas baterias de descida.
        self.semente.execute(
            "DELETE FROM platform.tenant_destinations WHERE tenant_id = %s", (self.tenant,)
        )

    def _destino(self, finalidade: str) -> None:
        self.semente.execute(
            "INSERT INTO platform.tenant_destinations "
            "(tenant_id, provider, country, purpose, status, apd_ref, contrato_ref, "
            " retencao_zero, sem_treino, autorizado_em) "
            "VALUES (%s, 'anthropic', 'US', %s, 'autorizado', %s, %s, true, true, "
            " now() - interval '1 day')",
            (self.tenant, finalidade, APD_REF, CONTRATO_REF),
        )

    def _classificar(self) -> tuple[_Transporte, metricas_mod.MetricasDoAgr]:
        transporte = _Transporte()
        metricas = metricas_mod.MetricasDoAgr()
        cliente = ClienteDeLlm(
            aliases={"screening": REAIS["screening"]},
            tabela_de_precos=PRECOS,
            # A porta real: `arrancar` com ligacao devolve a `PortaDoNucleo`
            # sobre a tabela. O ambiente nao a afrouxa — so a sem ligacao o le.
            porta_de_destinos=llm_destinos.arrancar(
                llm_destinos.AMBIENTE_PROD, lambda: ligacao.ligar("app")
            ),
            abrir_ligacao=lambda: ligacao.ligar("app"),
            chave_virtual=lambda _t: "chave-de-ensaio-do-screening",
            metricas=metricas,
            transporte=transporte,
        )
        pedido = screening.PedidoDeScreening(
            tenant_id=self.tenant,
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            categoria_declarada="moda",
            textos=("camisola de algodao",),
        )
        try:
            screening.ClassificadorDeScreening(cliente, REAIS["screening"])(pedido)
        finally:
            self.transporte, self.metricas = transporte, metricas
        return transporte, metricas

    def _linhas(self) -> list[tuple]:
        return self.consultar(
            f"SELECT papel, resultado, no_grafo, custo_usd, tokens_in FROM {TABELA} "
            "WHERE tenant_id = %s",
            (self.tenant,),
        )

    def test_com_a_finalidade_autorizada_passa_o_gate_e_deixa_a_linha(self) -> None:
        self._destino("classificacao_de_catalogo")
        transporte, metricas = self._classificar()
        self.assertEqual(transporte.chamadas, 1)
        self.assertIsNone(metricas.ler().get(metricas_mod.METRICA_LLM_REGISTO_FALHOU))
        ((papel, resultado, no_grafo, custo, tokens),) = self._linhas()
        self.assertEqual((papel, resultado, no_grafo), ("screening", "ok", screening.NO_DO_GRAFO))
        self.assertEqual(tokens, 400)
        self.assertEqual(custo, Decimal("0.000046"))

    def test_so_com_a_conversa_autorizada_sai_em_destino_negado(self) -> None:
        self._destino("conversa")
        with self.assertRaises(DestinoNegado):
            self._classificar()
        self.assertEqual(self.transporte.chamadas, 0)
        ((papel, resultado, _, custo, tokens),) = self._linhas()
        self.assertEqual((papel, resultado), ("screening", "destino_negado"))
        self.assertIsNone(custo)
        self.assertIsNone(tokens)

    def test_o_controlo_sem_destino_nenhum_nega(self) -> None:
        with self.assertRaises(DestinoNegado):
            self._classificar()
        self.assertEqual(self.transporte.chamadas, 0)
        self.assertEqual([r[1] for r in self._linhas()], ["destino_negado"])
