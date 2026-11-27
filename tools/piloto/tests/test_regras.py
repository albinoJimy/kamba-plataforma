"""As regras de H1, H6, H8 e H9 nas fronteiras que o bloco nomeia (KAM-109).

«Testes Requeridos»: fronteiras 4 e 5 de 10 (H1); 14,9% e 15,1% (H6); 5 e 6 de
10 (H8); 7 de 10 em H9. Cada fronteira tem os **dois** lados: um ensaio so do
lado verde passa com a regra a dizer sempre «confirmada».
"""

from __future__ import annotations

import datetime as dt
import unittest

from piloto import regras
from piloto.tests import fabrica as f

D = dt.timedelta(days=1)
#: Um ultimo dia em que toda a coorte ja passou o dia 60 e a janela da conversao
#: (dia 30 + 41 = dia 71).
FIM = f.INICIO + 75 * D


def _coorte_h1(pagantes: int, total: int = 10, ultimo_dia: dt.date = FIM):
    pmes = [
        f.pme(n, ciclos=[f.ciclo_pago(f.INICIO)] if n <= pagantes else [])
        for n in range(1, total + 1)
    ]
    return f.coorte(pmes, ultimo_dia)


class TestEstadoPorContagem(unittest.TestCase):
    def test_os_tres_estados(self) -> None:
        self.assertEqual(regras.estado_por_contagem(5, 0, 5), regras.CONFIRMADA)
        self.assertEqual(regras.estado_por_contagem(5, 5, 5), regras.CONFIRMADA)
        self.assertEqual(regras.estado_por_contagem(4, 0, 5), regras.REFUTADA)
        self.assertEqual(regras.estado_por_contagem(4, 1, 5), regras.INCONCLUSIVA)
        self.assertEqual(regras.estado_por_contagem(0, 4, 5), regras.REFUTADA)

    def test_recusa_negativos(self) -> None:
        with self.assertRaises(ValueError):
            regras.estado_por_contagem(-1, 0, 5)


class TestH1(unittest.TestCase):
    def test_fronteira_4_e_5_de_10(self) -> None:
        self.assertEqual(regras.h1(_coorte_h1(5), f.MENSALIDADE).estado, regras.CONFIRMADA)
        quatro = regras.h1(_coorte_h1(4), f.MENSALIDADE)
        self.assertEqual(quatro.estado, regras.REFUTADA)
        self.assertEqual(quatro.resultado, "4 de 10")
        self.assertEqual(quatro.amostra_n, 10)

    def test_4_de_10_com_a_janela_aberta_nao_e_refutada(self) -> None:
        resultado = regras.h1(_coorte_h1(4, ultimo_dia=f.INICIO + 35 * D), f.MENSALIDADE)
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(len(resultado.detalhe["pendentes"]), 6)

    def test_a_janela_fecha_no_dia_71_inclusive(self) -> None:
        aberto = regras.h1(_coorte_h1(4, ultimo_dia=f.INICIO + 70 * D), f.MENSALIDADE)
        fechado = regras.h1(_coorte_h1(4, ultimo_dia=f.INICIO + 71 * D), f.MENSALIDADE)
        self.assertEqual(aberto.estado, regras.INCONCLUSIVA)
        self.assertEqual(fechado.estado, regras.REFUTADA)

    def test_o_ciclo_alinhado_pelo_periodo_dia_que_cobre_o_dia_30_conta(self) -> None:
        # Os ciclos abrem no `periodo_dia` da subscricao, e nao na activacao: um
        # que comeca no dia 22 e cobre o dia 30 conta (a revisao adversarial, A3).
        pmes = [f.pme(1, ciclos=[f.ciclo_pago(f.INICIO, dia=22, pago_no_dia=31)])]
        self.assertEqual(regras.h1(f.coorte(pmes, FIM), f.MENSALIDADE).detalhe["pagantes"], ["P01"])

    def test_um_ciclo_que_so_cobre_o_periodo_gratuito_nao_conta(self) -> None:
        pmes = [f.pme(n, ciclos=[f.ciclo_pago(f.INICIO, dia=0, dias_do_periodo=30)])
                for n in range(1, 11)]
        self.assertEqual(regras.h1(f.coorte(pmes, FIM), f.MENSALIDADE).resultado, "0 de 10")

    def test_um_pagamento_depois_da_janela_nao_desfaz_a_refutada(self) -> None:
        # A revisao adversarial (A4): sem o dia do pagamento, uma `refutada` no
        # dia 71 virava `confirmada` quando a P05 pagasse tarde o ciclo do dia 60.
        pmes = [f.pme(n, ciclos=[f.ciclo_pago(f.INICIO)]) for n in range(1, 5)]
        pmes.append(f.pme(5, ciclos=[f.ciclo_pago(f.INICIO, dia=60, pago_no_dia=72)]))
        pmes += [f.pme(n) for n in range(6, 11)]
        tarde = regras.h1(f.coorte(pmes, f.INICIO + 90 * D), f.MENSALIDADE)
        self.assertEqual((tarde.estado, tarde.resultado), (regras.REFUTADA, "4 de 10"))
        pmes[4] = f.pme(5, ciclos=[f.ciclo_pago(f.INICIO, dia=60, pago_no_dia=71)])
        self.assertEqual(regras.h1(f.coorte(pmes, f.INICIO + 90 * D), f.MENSALIDADE).estado,
                         regras.CONFIRMADA)

    def test_um_ciclo_a_outro_preco_nao_conta_e_sai_no_detalhe(self) -> None:
        pmes = [f.pme(1, ciclos=[f.ciclo_pago(f.INICIO, valor=f.MENSALIDADE - 1)])]
        resultado = regras.h1(f.coorte(pmes, FIM), f.MENSALIDADE)
        self.assertEqual(resultado.detalhe["pagantes"], [])
        self.assertEqual(resultado.detalhe["pagos_a_outro_preco"], ["P01"])

    def test_a_via_de_ops_conta(self) -> None:
        pmes = [f.pme(n, ciclos=[f.ciclo_pago(f.INICIO, via="ops")]) for n in range(1, 6)]
        self.assertEqual(regras.h1(f.coorte(pmes, FIM), f.MENSALIDADE).detalhe["pagantes"],
                         ["P01", "P02", "P03", "P04", "P05"])

    def test_uma_coorte_incompleta_deixa_vagas_pendentes(self) -> None:
        resultado = regras.h1(_coorte_h1(4, total=6), f.MENSALIDADE)
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(resultado.detalhe["vagas_na_coorte"], 4)

    def test_uma_coorte_de_mais_de_10_e_recusada(self) -> None:
        # A revisao adversarial (A5): 5 de 12 nao e «5 de 10».
        exportacao = _coorte_h1(5, total=12)
        for regra in (lambda e: regras.h1(e, f.MENSALIDADE), regras.h9,
                      lambda e: regras.h8(e, [])):
            with self.subTest(), self.assertRaises(ValueError):
                regra(exportacao)

    def test_as_substituidas_nao_contam_e_sao_reportadas(self) -> None:
        pmes = [f.pme(n, ciclos=[f.ciclo_pago(f.INICIO)]) for n in range(1, 5)]
        pmes += [f.pme(n) for n in range(5, 11)]
        pmes.append(f.pme(11, ciclos=[f.ciclo_pago(f.INICIO)], na_coorte=False))
        resultado = regras.h1(f.coorte(pmes, FIM), f.MENSALIDADE)
        self.assertEqual(resultado.resultado, "4 de 10")
        self.assertEqual(resultado.detalhe["substituidas"],
                         [{"pme": "P11", "motivo": "sem_uso_semana_2"}])

    def test_mensalidade_nao_positiva_e_erro(self) -> None:
        with self.assertRaises(ValueError):
            regras.h1(_coorte_h1(5), 0)


class TestUsoNaSemana2(unittest.TestCase):
    def test_dias_7_a_13(self) -> None:
        base = f.dias_activos(f.INICIO, f.INICIO)  # so o dia 0
        sem = f.coorte([f.pme(1, dias=base)], FIM).coorte[0]
        self.assertFalse(regras.usou_na_semana_2(sem))
        for dia, esperado in ((6, False), (7, True), (13, True), (14, False)):
            data = (f.INICIO + dia * D).isoformat()
            dias = {data: {"conversas": 1, "accoes_dono": 0, "actualizacoes_catalogo": 0,
                           "handoffs": 0, "custo_llm_usd": "0", "custo_meta_usd": "0"}}
            pme = f.coorte([f.pme(1, dias=dias)], FIM).coorte[0]
            self.assertEqual(regras.usou_na_semana_2(pme), esperado, dia)


def _dia(conversas: int, accoes: int) -> dict[str, object]:
    return {"conversas": conversas, "accoes_dono": accoes, "actualizacoes_catalogo": 0,
            "handoffs": 0, "custo_llm_usd": "0", "custo_meta_usd": "0"}


class TestActiva(unittest.TestCase):
    FIM_JANELA = f.INICIO + 60 * D

    def _pme(self, dias: dict[int, dict[str, object]]):
        bruto = {(self.FIM_JANELA - n * D).isoformat(): v for n, v in dias.items()}
        return f.coorte([f.pme(1, dias=bruto)], FIM).coorte[0]

    def test_cinco_conversas_e_uma_accao_por_semana_e_activa(self) -> None:
        self.assertTrue(regras.activa_em(self._pme({0: _dia(5, 1), 13: _dia(0, 1)}), self.FIM_JANELA))

    def test_quatro_conversas_nao_e(self) -> None:
        self.assertFalse(regras.activa_em(self._pme({0: _dia(4, 1), 13: _dia(0, 1)}), self.FIM_JANELA))

    def test_sem_accao_na_primeira_semana_nao_e(self) -> None:
        # Dia 7 antes do fim ja e a segunda semana: a primeira fica vazia.
        self.assertFalse(regras.activa_em(self._pme({0: _dia(5, 1), 7: _dia(0, 0)}), self.FIM_JANELA))
        self.assertTrue(regras.activa_em(self._pme({0: _dia(5, 1), 7: _dia(0, 1)}), self.FIM_JANELA))

    def test_o_corte_entre_as_semanas_e_no_dia_7_antes_do_fim(self) -> None:
        # Os dias 6 e 0 antes do fim estao **os dois** na segunda semana: falta
        # a primeira. A revisao adversarial (A6) mediu que esta mutacao vivia.
        self.assertFalse(regras.activa_em(self._pme({0: _dia(5, 1), 6: _dia(0, 1)}), self.FIM_JANELA))
        self.assertTrue(regras.activa_em(self._pme({0: _dia(5, 1), 13: _dia(0, 1)}), self.FIM_JANELA))

    def test_fora_da_janela_nao_conta(self) -> None:
        self.assertFalse(regras.activa_em(self._pme({0: _dia(4, 1), 13: _dia(0, 1), 14: _dia(9, 0)}),
                                          self.FIM_JANELA))


def _coorte_h9(activas: int, elegiveis: int = 10, total: int = 10):
    pmes = []
    for n in range(1, total + 1):
        activada = f.INICIO if n <= elegiveis else FIM  # as outras nao chegam ao dia 60
        dias = f.dias_activos(activada, activada + 60 * D) if n <= activas else {}
        pmes.append(f.pme(n, activada=activada, dias=dias))
    return f.coorte(pmes, f.INICIO + 60 * D)


class TestH9(unittest.TestCase):
    def test_7_de_10_confirma_e_6_de_10_refuta(self) -> None:
        sete = regras.h9(_coorte_h9(7))
        self.assertEqual((sete.estado, sete.resultado), (regras.CONFIRMADA, "7 de 10 (70.00%)"))
        self.assertEqual(regras.h9(_coorte_h9(6)).estado, regras.REFUTADA)

    def test_com_8_elegiveis_a_fraccao_e_sobre_8(self) -> None:
        self.assertEqual(regras.h9(_coorte_h9(6, elegiveis=8)).estado, regras.CONFIRMADA)  # 75%
        self.assertEqual(regras.h9(_coorte_h9(5, elegiveis=8)).estado, regras.REFUTADA)  # 62,5%

    def test_menos_de_8_elegiveis_e_inconclusiva_com_data(self) -> None:
        pmes = [f.pme(n, activada=f.INICIO + (n - 1) * D,
                      dias=f.dias_activos(f.INICIO, f.INICIO + 80 * D)) for n in range(1, 11)]
        resultado = regras.h9(f.coorte(pmes, f.INICIO + 66 * D))  # P01..P07 elegiveis
        self.assertEqual(resultado.amostra_n, 7)
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        # A 8.a activacao (P08, no dia 7) faz 60 dias a INICIO + 67.
        self.assertEqual(resultado.detalhe["data_de_seguimento"], (f.INICIO + 67 * D).isoformat())

    def test_7_de_7_elegiveis_nao_confirma(self) -> None:
        resultado = regras.h9(_coorte_h9(7, elegiveis=7))
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)

    def test_o_indicador_do_dia_30_sai_a_parte(self) -> None:
        resultado = regras.h9(_coorte_h9(7))
        self.assertEqual(len(resultado.detalhe["indicador_dia_30"]["elegiveis"]), 10)


class TestH8(unittest.TestCase):
    def _auditorias(self, correctas: int, total: int = 10):
        return [
            regras.Auditoria(f"P{n:02d}", 20, 18 if n <= correctas else 17)
            for n in range(1, total + 1)
        ]

    def test_fronteira_5_e_6_de_10(self) -> None:
        exportacao = f.coorte([f.pme(n) for n in range(1, 11)], FIM)
        self.assertEqual(regras.h8(exportacao, self._auditorias(6)).estado, regras.CONFIRMADA)
        self.assertEqual(regras.h8(exportacao, self._auditorias(5)).estado, regras.REFUTADA)

    def test_o_catalogo_correcto_e_90_por_cento_dos_itens(self) -> None:
        self.assertTrue(regras.Auditoria("P01", 20, 18).correcto)
        self.assertFalse(regras.Auditoria("P01", 20, 17).correcto)
        self.assertTrue(regras.Auditoria("P01", 10, 9).correcto)
        self.assertFalse(regras.Auditoria("P01", 0, 0).correcto)

    def test_sem_auditoria_e_pendente(self) -> None:
        exportacao = f.coorte([f.pme(n) for n in range(1, 11)], FIM)
        resultado = regras.h8(exportacao, self._auditorias(5, total=9))
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(resultado.detalhe["pendentes"], ["P10"])

    def test_uma_coorte_incompleta_deixa_vagas_pendentes(self) -> None:
        # 5 correctos em 6: as 4 vagas ainda podem dar o 6.o (A6).
        exportacao = f.coorte([f.pme(n) for n in range(1, 7)], FIM)
        resultado = regras.h8(exportacao, self._auditorias(5, total=6))
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(resultado.detalhe["vagas_na_coorte"], 4)

    def test_auditoria_de_fora_da_coorte_e_erro(self) -> None:
        exportacao = f.coorte([f.pme(1)], FIM)
        with self.assertRaises(ValueError):
            regras.h8(exportacao, [regras.Auditoria("P02", 20, 20)])


FEV = dt.date(2027, 2, 28)


def _dia_h6(custo_llm: str, custo_meta: str = "0", conversas: int = 50) -> dict[str, object]:
    return {"2027-02-01": {"conversas": conversas, "accoes_dono": 0, "actualizacoes_catalogo": 0,
                           "handoffs": 0, "custo_llm_usd": custo_llm, "custo_meta_usd": custo_meta}}


def _coorte_h6(custo_llm: str, custo_meta: str = "0", activada: dt.date = f.INICIO,
               ultimo_dia: dt.date = FEV, conversas_p01: int = 50):
    """10 PMEs com Fevereiro de 2027 inteiro, o custo todo no dia 1."""
    return f.coorte(
        [f.pme(n, activada=activada,
               dias=_dia_h6(custo_llm, custo_meta, conversas_p01 if n == 1 else 50))
         for n in range(1, 11)],
        ultimo_dia,
    )


class TestH6(unittest.TestCase):
    # Cambio de ensaio 1000: o racio e o custo do mes em USD a dividir por 30.

    def _h6(self, exportacao):
        return regras.h6(exportacao, f.MENSALIDADE, f.h6_export())

    def test_15_1_por_cento_refuta(self) -> None:
        resultado = self._h6(_coorte_h6("4.53"))
        self.assertEqual(resultado.estado, regras.REFUTADA)
        self.assertEqual(resultado.detalhe["racio_agregado"], "15.10%")
        self.assertEqual(resultado.amostra_n, 500)
        self.assertEqual(len(resultado.detalhe["cenarios"]), 3)

    def test_14_9_por_cento_nao_confirma_sem_stt(self) -> None:
        resultado = self._h6(_coorte_h6("4.47"))
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(resultado.detalhe["motivo"], "stt_nao_medido")
        self.assertEqual(resultado.detalhe["cenarios"], [])

    def test_exactamente_15_por_cento_nao_e_acima(self) -> None:
        self.assertEqual(self._h6(_coorte_h6("4.5")).detalhe["motivo"], "stt_nao_medido")

    def test_499_conversas_e_inconclusiva_mesmo_acima(self) -> None:
        resultado = self._h6(_coorte_h6("4.53", conversas_p01=49))
        self.assertEqual((resultado.estado, resultado.detalhe["motivo"], resultado.amostra_n),
                         (regras.INCONCLUSIVA, "amostra_abaixo_de_500", 499))

    def test_so_contam_meses_inteiros_depois_da_activacao(self) -> None:
        # Activadas a 2 de Fevereiro: Fevereiro nao e um mes inteiro do Piloto.
        tarde = self._h6(_coorte_h6("9", activada=dt.date(2027, 2, 2)))
        self.assertEqual((tarde.resultado, tarde.amostra_n), ("NAO MEDIDO", 0))
        # E um mes que ainda nao acabou tambem nao conta.
        cedo = self._h6(_coorte_h6("9", ultimo_dia=dt.date(2027, 2, 27)))
        self.assertEqual(cedo.resultado, "NAO MEDIDO")

    def test_os_tenants_fora_da_coorte_nao_contam(self) -> None:
        # A revisao adversarial (A2): a amostra do h6-export e da plataforma; a
        # daqui e so da coorte. Uma substituida com custo enorme nao entra.
        pmes = [f.pme(n, dias=_dia_h6("4.47")) for n in range(1, 11)]
        pmes.append(f.pme(11, na_coorte=False, dias=_dia_h6("900", conversas=900)))
        resultado = self._h6(f.coorte(pmes, FEV))
        self.assertEqual((resultado.detalhe["racio_agregado"], resultado.amostra_n), ("14.90%", 500))

    def test_o_preco_minimo_do_cenario_arredonda_para_cima(self) -> None:
        cenarios = self._h6(_coorte_h6("4.53")).detalhe["cenarios"]
        # 453 000 / 0,15 = 3 020 000 exactos.
        self.assertEqual(cenarios[0]["necessario"], "mensalidade >= 3020000 AOA minor")

    def test_outra_mensalidade_no_h6_export_e_erro(self) -> None:
        # O protocolo antigo passava o mesmo numero aos dois (A7): o h6-export
        # multiplica por 100, e a recusa e o que o apanha.
        with self.assertRaises(ValueError):
            regras.h6(_coorte_h6("1"), f.MENSALIDADE, f.h6_export(mensalidade=f.MENSALIDADE * 100))

    def test_o_llm_isolado_sai_ao_lado(self) -> None:
        resultado = self._h6(_coorte_h6("1.5", custo_meta="3.03"))
        self.assertEqual(resultado.detalhe["racio_agregado"], "15.10%")
        self.assertEqual(resultado.detalhe["llm_isolado_p50"], "5.00%")


class TestPreCondicoes(unittest.TestCase):
    def test_self_service_e_dpa(self) -> None:
        pmes = [f.pme(n, self_service=n <= 8) for n in range(1, 11)]
        pmes.append(f.pme(11, self_service=None, dpa=False))
        resultado = regras.pre_condicoes(f.coorte(pmes, FIM))
        self.assertEqual(resultado["self_service"], "80.00%")
        self.assertTrue(resultado["self_service_cumpre_carta"])
        self.assertEqual(resultado["self_service_desconhecido"], ["P11"])
        self.assertEqual(resultado["dpa_em_falta"], ["P11"])


if __name__ == "__main__":
    unittest.main()
