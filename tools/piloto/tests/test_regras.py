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
#: Um ultimo dia em que toda a coorte ja passou o dia 60 e o prazo da conversao.
FIM = f.INICIO + 70 * D


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

    def test_4_de_10_com_o_prazo_aberto_nao_e_refutada(self) -> None:
        # Ultimo dia no dia 35: o prazo da conversao (dia 40) ainda esta aberto.
        resultado = regras.h1(_coorte_h1(4, ultimo_dia=f.INICIO + 35 * D), f.MENSALIDADE)
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(len(resultado.detalhe["pendentes"]), 6)

    def test_o_prazo_fecha_no_dia_40_inclusive(self) -> None:
        aberto = regras.h1(_coorte_h1(4, ultimo_dia=f.INICIO + 39 * D), f.MENSALIDADE)
        fechado = regras.h1(_coorte_h1(4, ultimo_dia=f.INICIO + 40 * D), f.MENSALIDADE)
        self.assertEqual(aberto.estado, regras.INCONCLUSIVA)
        self.assertEqual(fechado.estado, regras.REFUTADA)

    def test_um_ciclo_antes_do_dia_30_nao_conta(self) -> None:
        pmes = [f.pme(n, ciclos=[f.ciclo_pago(f.INICIO, dia=29)]) for n in range(1, 11)]
        self.assertEqual(regras.h1(f.coorte(pmes, FIM), f.MENSALIDADE).resultado, "0 de 10")

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
        # 4 pagantes em 6: as 4 vagas por preencher ainda podem dar a 5.a.
        resultado = regras.h1(_coorte_h1(4, total=6), f.MENSALIDADE)
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(resultado.detalhe["vagas_na_coorte"], 4)

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

    def test_auditoria_de_fora_da_coorte_e_erro(self) -> None:
        exportacao = f.coorte([f.pme(1)], FIM)
        with self.assertRaises(ValueError):
            regras.h8(exportacao, [regras.Auditoria("P02", 20, 20)])


class TestH6(unittest.TestCase):
    def setUp(self) -> None:
        self.exportacao = f.coorte([f.pme(n) for n in range(1, 11)], FIM)

    def _h6(self, custo_por_mes: int, amostra: int = 500):
        meses = [(f.tenant(n), "2027-02", custo_por_mes) for n in range(1, 11)]
        return regras.h6(f.h6_export(meses, amostra), self.exportacao, f.MENSALIDADE)

    def test_15_1_por_cento_refuta(self) -> None:
        resultado = self._h6(453_000)
        self.assertEqual(resultado.estado, regras.REFUTADA)
        self.assertEqual(resultado.detalhe["racio_agregado"], "15.10%")
        self.assertEqual(len(resultado.detalhe["cenarios"]), 3)

    def test_14_9_por_cento_nao_confirma_sem_stt(self) -> None:
        resultado = self._h6(447_000)
        self.assertEqual(resultado.estado, regras.INCONCLUSIVA)
        self.assertEqual(resultado.detalhe["motivo"], "stt_nao_medido")
        self.assertEqual(resultado.detalhe["cenarios"], [])

    def test_exactamente_15_por_cento_nao_e_acima(self) -> None:
        self.assertEqual(self._h6(450_000).detalhe["motivo"], "stt_nao_medido")

    def test_499_conversas_e_inconclusiva_mesmo_acima(self) -> None:
        resultado = self._h6(453_000, amostra=499)
        self.assertEqual((resultado.estado, resultado.detalhe["motivo"]),
                         (regras.INCONCLUSIVA, "amostra_abaixo_de_500"))

    def test_o_mes_incompleto_e_os_tenants_fora_da_coorte_nao_contam(self) -> None:
        bruto = f.h6_export([(f.tenant(1), "2027-02", 447_000), (f.tenant(99), "2027-02", 3_000_000)])
        bruto["racio_por_tenant_e_mes"].append(
            {**bruto["racio_por_tenant_e_mes"][0], "mes": "2027-03", "mes_completo": False,
             "custo_aoa_minor": 3_000_000})
        resultado = regras.h6(bruto, self.exportacao, f.MENSALIDADE)
        self.assertEqual(resultado.detalhe["racio_agregado"], "14.90%")

    def test_o_preco_minimo_do_cenario_arredonda_para_cima(self) -> None:
        cenarios = self._h6(453_000).detalhe["cenarios"]
        # 453 000 / 0,15 = 3 020 000 exactos.
        self.assertEqual(cenarios[0]["necessario"], "mensalidade >= 3020000 AOA minor")

    def test_outra_mensalidade_no_h6_export_e_erro(self) -> None:
        bruto = f.h6_export([(f.tenant(1), "2027-02", 1)], mensalidade=f.MENSALIDADE + 1)
        with self.assertRaises(ValueError):
            regras.h6(bruto, self.exportacao, f.MENSALIDADE)

    def test_o_llm_isolado_sai_da_exportacao(self) -> None:
        activada = dt.date(2027, 2, 1)
        dias = f.dias_activos(activada, dt.date(2027, 2, 28))  # 0,01 USD de LLM por dia
        exportacao = f.coorte([f.pme(1, activada=activada, dias=dias)], dt.date(2027, 3, 31))
        resultado = regras.h6(f.h6_export([(f.tenant(1), "2027-02", 447_000)]), exportacao,
                              f.MENSALIDADE)
        # 28 x 0,01 USD x 913 = 255,64 Kz = 25 564 minor; / 3 000 000 = 0,85%.
        self.assertEqual(resultado.detalhe["llm_isolado_p50"], "0.85%")


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
