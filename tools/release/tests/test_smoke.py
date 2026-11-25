"""Gate 15, sem o numero real: a guarda que aborta perante producao, e a classificacao.

Todos os numeros aqui sao do intervalo ficticio `999…` do `tools/meta-sim`,
incluindo o que faz de «numero de producao»: o que se ensaia e a guarda, e um
numero real num repositorio publico seria o defeito que ela existe para evitar.
"""

from __future__ import annotations

import unittest

from release import smoke
from release.tests.apoio import RAIZ

TESTE = "999100000001"
PRODUCAO_FICTICIA = "999200000002"
SIMULADOR = "http://meta-sim:8090"


def _alvo(ambiente: str = "staging", numero: str = TESTE, projecto: str = "staging",
          base: str = "https://graph.facebook.com", pnid: str = "pn-teste") -> smoke.Alvo:
    return smoke.Alvo(ambiente, numero, pnid, projecto, base)


def _producao(numeros=(PRODUCAO_FICTICIA,), ids=("pn-prod",)) -> smoke.Producao:
    return smoke.producao_declarada(RAIZ, numeros, ids)


class TestGuarda(unittest.TestCase):
    def assertAborta(self, alvo: smoke.Alvo, producao: smoke.Producao, contem: str) -> None:
        with self.assertRaises(smoke.SmokeAbortado) as erro:
            smoke.guardar(alvo, producao, RAIZ)
        self.assertIn(contem, str(erro.exception))

    # --- o teste negativo do criterio 8 --------------------------------------

    def test_negativo_aborta_perante_o_numero_de_producao(self) -> None:
        self.assertAborta(_alvo(numero=PRODUCAO_FICTICIA), _producao(), "numero de producao")

    def test_negativo_aborta_com_o_numero_de_producao_noutra_forma(self) -> None:
        self.assertAborta(_alvo(numero="+999 200 000 002"), _producao(), "numero de producao")

    def test_negativo_aborta_perante_o_phone_number_id_de_producao(self) -> None:
        self.assertAborta(_alvo(pnid="pn-prod"), _producao(), "phone_number_id")

    def test_negativo_aborta_com_as_chaves_de_producao(self) -> None:
        self.assertAborta(_alvo(projecto="prod"), _producao(), "chaves do smoke")

    # --- fail-closed ---------------------------------------------------------

    def test_sem_a_lista_de_producao_aborta_em_staging(self) -> None:
        self.assertAborta(_alvo(), _producao(numeros=None), "sem a lista")

    def test_prod_aborta_sempre(self) -> None:
        self.assertAborta(_alvo(ambiente="prod", projecto="outro"), _producao(), "nunca corre em producao")

    def test_ambiente_nao_declarado_aborta(self) -> None:
        self.assertAborta(_alvo(ambiente="qa"), _producao(), "nao declarado")

    def test_o_projecto_de_producao_vem_do_env_yaml(self) -> None:
        self.assertEqual(_producao().projecto, "prod")

    # --- os caminhos que passam ----------------------------------------------

    def test_staging_com_numero_de_teste_passa(self) -> None:
        smoke.guardar(_alvo(), _producao(), RAIZ)

    def test_dev_contra_o_simulador_passa(self) -> None:
        smoke.guardar(_alvo(ambiente="dev", projecto="dev", base=SIMULADOR), _producao(numeros=None), RAIZ)

    def test_dev_fora_do_intervalo_ficticio_aborta(self) -> None:
        self.assertAborta(
            _alvo(ambiente="dev", projecto="dev", base=SIMULADOR, numero="12025550100"),
            _producao(), "intervalo ficticio",
        )

    def test_dev_com_a_graph_da_meta_aborta(self) -> None:
        self.assertAborta(_alvo(ambiente="dev", projecto="dev"), _producao(), "base da Graph")


class TestCorrer(unittest.TestCase):
    def test_um_aborto_nao_envia_nada(self) -> None:
        enviadas: list[smoke.Alvo] = []

        def uma(alvo: smoke.Alvo) -> smoke.Execucao:
            enviadas.append(alvo)
            return smoke.Execucao("ok", 1.0)

        with self.assertRaises(smoke.SmokeAbortado):
            smoke.correr(_alvo(numero=PRODUCAO_FICTICIA), _producao(), RAIZ, uma)
        self.assertEqual(enviadas, [])

    def test_vinte_execucoes_rapidas_sao_verdes(self) -> None:
        veredicto = smoke.correr(_alvo(), _producao(), RAIZ, lambda a: smoke.Execucao("ok", 3.0))
        self.assertEqual(veredicto.estado, smoke.VERDE)


def _execucoes(*pares) -> list[smoke.Execucao]:
    saida = []
    for desfecho, segundos, vezes in pares:
        saida += [smoke.Execucao(desfecho, segundos)] * vezes
    return saida


class TestClassificacao(unittest.TestCase):
    def test_p95_por_posicao(self) -> None:
        self.assertEqual(smoke.p95([float(i) for i in range(1, 21)]), 19.0)

    def test_p95_acima_de_15_e_vermelho(self) -> None:
        # 18 rapidas e 2 lentas: o p95 de 20 e a 19.a, que e lenta.
        v = smoke.classificar(_execucoes(("ok", 2.0, 18), ("ok", 16.0, 2)))
        self.assertEqual(v.estado, smoke.VERMELHO)

    def test_uma_lenta_em_vinte_cabe_no_p95(self) -> None:
        v = smoke.classificar(_execucoes(("ok", 2.0, 19), ("ok", 40.0, 1)))
        self.assertEqual(v.estado, smoke.VERDE)

    def test_meta_indisponivel_e_inconclusivo_e_nao_verde(self) -> None:
        v = smoke.classificar(_execucoes(("ok", 2.0, 20), ("meta_indisponivel", None, 1)))
        self.assertEqual(v.estado, smoke.INCONCLUSIVO)

    def test_menos_de_vinte_medidas_e_inconclusivo(self) -> None:
        v = smoke.classificar(_execucoes(("ok", 2.0, 17), ("meta_indisponivel", None, 3)))
        self.assertEqual(v.estado, smoke.INCONCLUSIVO)

    def test_resposta_errada_e_vermelho_mesmo_com_a_meta_em_baixo(self) -> None:
        v = smoke.classificar(_execucoes(("ok", 2.0, 20), ("resposta_errada", None, 1),
                                         ("meta_indisponivel", None, 1)))
        self.assertEqual(v.estado, smoke.VERMELHO)

    def test_ok_sem_tempo_e_erro_de_quem_mede(self) -> None:
        with self.assertRaises(ValueError):
            smoke.Execucao("ok")

    def test_pagamento(self) -> None:
        self.assertEqual(smoke.classificar_pagamento("paga", 30.0, True).estado, smoke.VERDE)
        self.assertEqual(smoke.classificar_pagamento("paga", 61.0, True).estado, smoke.VERMELHO)
        self.assertEqual(smoke.classificar_pagamento("pendente", 10.0, True).estado, smoke.VERMELHO)
        self.assertEqual(smoke.classificar_pagamento(None, None, False).estado, smoke.INCONCLUSIVO)


if __name__ == "__main__":
    unittest.main()
