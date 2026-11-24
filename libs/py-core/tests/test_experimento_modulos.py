"""O experimento dos modulos de entrada: Wilson, limiares e a regra de decisao (KAM-127).

Sem base: as vistas correm contra a base em `db/tests/test_experimento_modulos_schema.py`.
Aqui prova-se a parte pura — o intervalo de Wilson contra valores calculados a
mao, o leitor dos limiares a falhar fechado, e o ensaio de decisao com dados
**ficticios** para cada ramo (manter, ajustar, abater), mais o catalogo que
nunca se abate e a coorte vazia.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from kamba_core.modulos import MODULOS_DE_ENTRADA
from kamba_core.modulos import experimento as ex

RAIZ = Path(__file__).resolve().parents[3]
CONFIG = RAIZ / "config" / "experimento_modulos.yaml"
REGISTO = RAIZ / "registry" / "modulos_entrada.yaml"


def limiares() -> ex.Limiares:
    return ex.ler(CONFIG)


class TestWilson(unittest.TestCase):
    """Valores de referencia calculados a mao pela formula (z = 1,96)."""

    def test_seis_em_dez(self) -> None:
        # p = 0,6; centro = 0,5722; meia = 0,2596 — o exemplo do bloco.
        self.assertEqual(ex.wilson(6, 10), (0.3127, 0.8318))

    def test_os_extremos_ficam_dentro_de_zero_e_um(self) -> None:
        baixo, alto = ex.wilson(0, 10)
        self.assertEqual(baixo, 0.0)
        self.assertAlmostEqual(alto, 0.2775, places=4)
        baixo, alto = ex.wilson(10, 10)
        self.assertAlmostEqual(baixo, 0.7225, places=4)
        self.assertEqual(alto, 1.0)

    def test_sem_coorte_nao_ha_intervalo(self) -> None:
        self.assertIsNone(ex.wilson(0, 0))

    def test_entradas_impossiveis_levantam(self) -> None:
        for n, total in ((3, 2), (-1, 4), (1, -1)):
            with self.subTest(n=n, total=total):
                with self.assertRaises(ValueError):
                    ex.wilson(n, total)
        with self.assertRaises(TypeError):
            ex.wilson(True, 3)  # type: ignore[arg-type]

    def test_o_intervalo_contem_a_proporcao(self) -> None:
        for total in range(1, 31):
            for n in range(total + 1):
                baixo, alto = ex.wilson(n, total)
                self.assertLessEqual(baixo, n / total + 1e-4)
                self.assertGreaterEqual(alto, n / total - 1e-4)


class TestLimiares(unittest.TestCase):
    def test_o_ficheiro_do_repositorio_le_e_traz_os_valores_do_bloco(self) -> None:
        l = limiares()
        self.assertEqual((l.h10_limiar_pct, l.h11_limiar_pct, l.h12_custo_pct, l.h12_pagantes), (60, 30, 15, 3))
        self.assertEqual((l.janela_de_uso_dias, l.janela_de_activacao_dias), (14, 30))
        self.assertEqual(
            (l.abate_uso_minimo_pct, l.abate_custo_maximo_pct, l.abate_semanas_de_custo),
            (20, 15, 2),
        )
        self.assertEqual(
            (l.abate_incidentes_alta, l.abate_incidentes_media, l.abate_janela_de_incidentes_dias),
            (1, 3, 30),
        )
        self.assertEqual(l.ajuste_margem_pct, 10)

    def texto(self) -> str:
        return CONFIG.read_text(encoding="utf-8")

    def test_chave_em_falta_falha(self) -> None:
        with self.assertRaisesRegex(ex.LimiaresInvalidos, "faltam chaves: h12_pagantes"):
            ex.interpretar(re.sub(r"(?m)^h12_pagantes:.*$", "", self.texto()))

    def test_chave_desconhecida_falha(self) -> None:
        with self.assertRaisesRegex(ex.LimiaresInvalidos, "desconhecida"):
            ex.interpretar(self.texto() + "h13_limiar_pct: 10\n")

    def test_valor_nao_inteiro_ou_zero_falha(self) -> None:
        for mau in ("0.6", "zero", "0"):
            with self.subTest(mau=mau):
                with self.assertRaises(ex.LimiaresInvalidos):
                    ex.interpretar(re.sub(r"(?m)^h10_limiar_pct:.*$", f"h10_limiar_pct: {mau}", self.texto()))

    def test_percentagem_acima_de_cem_falha(self) -> None:
        with self.assertRaisesRegex(ex.LimiaresInvalidos, "acima de 100"):
            ex.interpretar(re.sub(r"(?m)^h10_limiar_pct:.*$", "h10_limiar_pct: 160", self.texto()))

    def test_repetida_e_versao_errada_falham(self) -> None:
        with self.assertRaisesRegex(ex.LimiaresInvalidos, "repetida"):
            ex.interpretar(self.texto() + "h12_pagantes: 3\n")
        with self.assertRaisesRegex(ex.LimiaresInvalidos, "version"):
            ex.interpretar(self.texto().replace("version: 1", "version: 2"))


class TestHipoteses(unittest.TestCase):
    def test_seis_em_dez_cumpre_os_sessenta(self) -> None:
        leitura = ex.ler_hipotese("H10", 6, 10, 60)
        self.assertTrue(leitura.cumpre)
        self.assertEqual(leitura.medida.proporcao, 0.6)
        self.assertEqual(leitura.medida.wilson_95, (0.3127, 0.8318))

    def test_cinco_em_dez_nao_cumpre(self) -> None:
        self.assertFalse(ex.ler_hipotese("H10", 5, 10, 60).cumpre)

    def test_sem_coorte_e_nao_medida(self) -> None:
        leitura = ex.ler_hipotese("H11", 0, 0, 30)
        self.assertIsNone(leitura.cumpre)
        self.assertIsNone(leitura.medida.wilson_95)

    def test_a_fronteira_e_exacta_e_nao_de_virgula_flutuante(self) -> None:
        # 3/10 = 0,3 exactamente; em virgula flutuante 0.3 < 0.30000000000000004.
        self.assertTrue(ex.ler_hipotese("H11", 3, 10, 30).cumpre)


class TestDecisao(unittest.TestCase):
    """O ensaio de decisao do bloco: dados ficticios, um caso por ramo."""

    def decidir(self, **campos) -> ex.Decisao:
        base = {"modulo": "social", "usaram": 6, "coorte": 10}
        base.update(campos)
        return ex.decidir(ex.MedicaoDoModulo(**base), limiares())

    def test_manter_com_tudo_dentro(self) -> None:
        d = self.decidir(custo_racios_semanais=(0.05, 0.06))
        self.assertEqual((d.decisao, d.criterios), ("manter", ()))
        self.assertIsNone(d.criterio)

    def test_abater_pelo_uso(self) -> None:
        d = self.decidir(usaram=1, coorte=10)
        self.assertEqual(d.decisao, "abater")
        self.assertEqual(d.criterios, (ex.CRITERIO_USO,))

    def test_abater_por_um_incidente_alto(self) -> None:
        d = self.decidir(incidentes_alta=1)
        self.assertEqual((d.decisao, d.criterios), ("abater", (ex.CRITERIO_INCIDENTES,)))

    def test_abater_por_tres_incidentes_medios_e_nao_por_dois(self) -> None:
        self.assertEqual(self.decidir(incidentes_media=3).decisao, "abater")
        self.assertEqual(self.decidir(incidentes_media=2).decisao, "manter")

    def test_ajustar_por_duas_semanas_de_custo_e_nao_por_uma(self) -> None:
        d = self.decidir(custo_racios_semanais=(0.05, 0.16, 0.17))
        self.assertEqual((d.decisao, d.criterio), ("ajustar", "b_custo,perto_do_limiar"))
        # Uma semana acima, e a anterior dentro: so a proximidade ajusta.
        d = self.decidir(custo_racios_semanais=(0.16, 0.05, 0.16))
        self.assertEqual((d.decisao, d.criterios), ("ajustar", (ex.CRITERIO_PERTO,)))

    def test_a_semana_sem_preco_parte_a_sequencia(self) -> None:
        d = self.decidir(custo_racios_semanais=(0.2, None, 0.05))
        self.assertEqual(d.decisao, "manter")

    def test_ajustar_por_margem_negativa(self) -> None:
        d = self.decidir(margem_negativa=True)
        self.assertEqual((d.decisao, d.criterios), ("ajustar", (ex.CRITERIO_MARGEM,)))

    def test_ajustar_perto_do_limiar_do_uso(self) -> None:
        # 21% < 20% x 1,10 = 22%: dentro do limiar, e a menos de 10% dele.
        d = self.decidir(usaram=21, coorte=100)
        self.assertEqual((d.decisao, d.criterios), ("ajustar", (ex.CRITERIO_PERTO,)))
        self.assertEqual(self.decidir(usaram=22, coorte=100).decisao, "manter")

    def test_ajustar_perto_do_limiar_do_custo(self) -> None:
        # 0,14 > 15% x 0,90 = 0,135.
        self.assertEqual(self.decidir(custo_racios_semanais=(0.14,)).decisao, "ajustar")
        self.assertEqual(self.decidir(custo_racios_semanais=(0.135,)).decisao, "manter")

    def test_o_catalogo_nunca_se_abate(self) -> None:
        d = self.decidir(modulo="catalogo", usaram=0, coorte=10, incidentes_alta=2)
        self.assertEqual(d.decisao, "ajustar")
        self.assertEqual(
            d.criterios, (ex.CRITERIO_USO, ex.CRITERIO_INCIDENTES, ex.CRITERIO_CATALOGO)
        )

    def test_os_outros_tres_abatem_com_a_mesma_medicao(self) -> None:
        for modulo in ("foto", "social", "orcamento"):
            with self.subTest(modulo=modulo):
                self.assertEqual(self.decidir(modulo=modulo, usaram=0, coorte=10).decisao, "abater")

    def test_sem_coorte_nao_ha_decisao(self) -> None:
        d = self.decidir(usaram=0, coorte=0)
        self.assertIsNone(d.decisao)
        self.assertEqual(d.motivo, ex.MOTIVO_SEM_DADOS)
        self.assertIsNone(d.metricas()["uso"]["wilson_95"])

    def test_as_metricas_levam_n_de_N_e_o_intervalo(self) -> None:
        metricas = self.decidir().metricas()
        self.assertEqual(metricas["uso"]["n"], 6)
        self.assertEqual(metricas["uso"]["total"], 10)
        self.assertEqual(metricas["uso"]["wilson_95"], [0.3127, 0.8318])
        self.assertIn("limiares", metricas)

    def test_modulo_desconhecido_e_medicao_impossivel_levantam(self) -> None:
        with self.assertRaises(ValueError):
            ex.MedicaoDoModulo(modulo="arquivo", usaram=0, coorte=1)
        with self.assertRaises(ValueError):
            ex.MedicaoDoModulo(modulo="foto", usaram=3, coorte=2)

    def test_toda_a_decisao_esta_no_dominio_da_tabela(self) -> None:
        for usaram in range(0, 11):
            for alta in (0, 1):
                d = self.decidir(usaram=usaram, incidentes_alta=alta)
                self.assertIn(d.decisao, ex.DECISOES)


class TestRegistoDosModulos(unittest.TestCase):
    """O `registry/modulos_entrada.yaml` fala dos mesmos quatro modulos."""

    def test_os_modulos_do_registo_sao_os_do_nucleo(self) -> None:
        texto = REGISTO.read_text(encoding="utf-8")
        nomes = re.findall(r"(?m)^  - modulo: ([a-z_]+)$", texto)
        self.assertEqual(sorted(nomes), sorted(MODULOS_DE_ENTRADA))


if __name__ == "__main__":
    unittest.main()
