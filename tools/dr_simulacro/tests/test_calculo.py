"""A folha de passos e o calculo de RPO e RTO (KAM-085).

    TestFolha        o que a folha recusa, e porque
    TestRto          medido contra composto, por rubrica, e as fronteiras
    TestRpo          a diferenca entre marcadores, buracos e sem confirmacao
    TestPitr         anteriores a T presentes, nenhum posterior, a fronteira
    TestReplica      a regra do criterio 6, as duas metades
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dr_simulacro import calculo, folha
from dr_simulacro.folha import Carimbo, FolhaInvalida

T0 = datetime(2026, 11, 8, 10, 0, 0, tzinfo=timezone.utc)


def _medido(passo: str, inicio_s: float, fim_s: float, cenario: str = "A") -> list[Carimbo]:
    return [Carimbo(cenario, passo, "inicio", T0 + timedelta(seconds=inicio_s)),
            Carimbo(cenario, passo, "fim", T0 + timedelta(seconds=fim_s))]


def _nao(passo: str, cenario: str = "A") -> list[Carimbo]:
    return [Carimbo(cenario, passo, "nao_medido", None, "humano")]


def _folha_a(restauro_s: float = 600, replay_s: float = 60) -> list[Carimbo]:
    """Deteccao, decisao e DNS por medir; o resto medido."""
    return (_nao("deteccao") + _nao("decisao") + _medido("iac", 0, 5)
            + _medido("restauro", 5, 5 + restauro_s)
            + _medido("replay", 5 + restauro_s, 5 + restauro_s + replay_s)
            + _medido("verificacao", 1000, 1120) + _nao("dns"))


class TestFolha(unittest.TestCase):
    def test_o_que_se_escreve_le_se_igual(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "f.jsonl"
            relogio = iter([T0, T0 + timedelta(seconds=90)])
            f = folha.Folha(caminho, "A", relogio=lambda: next(relogio))
            f.inicio("restauro", "nota")
            f.fim("restauro")
            f.nao_medido("dns", "nao ha DNS")
            lidos = folha.ler(caminho)
        self.assertEqual([c.evento for c in lidos], ["inicio", "fim", "nao_medido"])
        self.assertEqual(lidos[1].em - lidos[0].em, timedelta(seconds=90))
        self.assertEqual(lidos[2].nota, "nao ha DNS")

    def test_nao_medido_sem_razao_recusa(self):
        with self.assertRaises(FolhaInvalida):
            folha.Folha(Path("x"), "A").nao_medido("dns", "  ")

    def test_passo_desconhecido_recusa(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "f.jsonl"
            caminho.write_text(json.dumps({"cenario": "A", "passo": "cafe", "evento": "inicio",
                                           "em": "2026-11-08T10:00:00Z"}) + "\n")
            with self.assertRaises(FolhaInvalida):
                folha.ler(caminho)

    def test_instante_sem_fuso_recusa(self):
        with self.assertRaises(FolhaInvalida):
            folha.ler_instante("2026-11-08T10:00:00")
        with self.assertRaises(FolhaInvalida):
            folha.formatar(datetime(2026, 11, 8))

    def test_json_ilegivel_e_linha_que_nao_e_objecto(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "f.jsonl"
            caminho.write_text("{nao e json\n")
            with self.assertRaises(FolhaInvalida):
                folha.ler(caminho)
            caminho.write_text("[1, 2]\n")
            with self.assertRaises(FolhaInvalida):
                folha.ler(caminho)

    def test_um_passo_que_falta_recusa_em_vez_de_contar_zero(self):
        carimbos = [c for c in _folha_a() if c.passo != "replay"]
        with self.assertRaisesRegex(FolhaInvalida, "replay"):
            calculo.duracoes(carimbos, "A")

    def test_inicio_sem_fim_recusa(self):
        carimbos = [c for c in _folha_a() if not (c.passo == "replay" and c.evento == "fim")]
        with self.assertRaises(FolhaInvalida):
            calculo.duracoes(carimbos, "A")

    def test_medido_e_nao_medido_ao_mesmo_tempo_recusa(self):
        with self.assertRaises(FolhaInvalida):
            calculo.duracoes(_folha_a() + _nao("restauro"), "A")

    def test_fim_antes_do_inicio_recusa(self):
        carimbos = [c for c in _folha_a() if c.passo != "iac"] + _medido("iac", 10, 5)
        with self.assertRaises(FolhaInvalida):
            calculo.duracoes(carimbos, "A")

    def test_outro_cenario_nao_conta(self):
        with self.assertRaises(FolhaInvalida):
            calculo.duracoes(_folha_a(), "B")


class TestRto(unittest.TestCase):
    def test_medido_so_soma_o_que_se_cronometrou(self):
        rto = calculo.rto(calculo.duracoes(_folha_a(600, 60), "A"))
        self.assertEqual(rto.medido_segundos, 5 + 600 + 60 + 120)

    def test_composto_acrescenta_o_orcamento_que_sobra_e_di_lo(self):
        rto = calculo.rto(calculo.duracoes(_folha_a(600, 60), "A"))
        # deteccao 10 + decisao 10 inteiros; a rubrica verificacao_e_dns tem 15
        # min, a verificacao gastou 2, sobram 13 para o DNS.
        self.assertEqual(rto.composto_segundos, rto.medido_segundos + (10 + 10 + 13) * 60)
        self.assertEqual(len(rto.orcamento_no_composto), 3)
        self.assertIn("verificacao_e_dns: 13.0 min", rto.orcamento_no_composto[2])

    def test_rubrica_gasta_alem_do_orcamento_nao_acrescenta_negativo(self):
        carimbos = [c for c in _folha_a() if c.passo != "verificacao"] + _medido(
            "verificacao", 0, 20 * 60)
        rto = calculo.rto(calculo.duracoes(carimbos, "A"))
        rubrica = {r.nome: r for r in rto.rubricas}["verificacao_e_dns"]
        self.assertEqual(rubrica.medido_segundos, 20 * 60)
        self.assertEqual(rto.composto_segundos, rto.medido_segundos + 20 * 60)

    def test_divergencia_so_com_a_rubrica_inteira_medida(self):
        rto = calculo.rto(calculo.duracoes(_folha_a(600, 60), "A"))
        rubricas = {r.nome: r for r in rto.rubricas}
        self.assertAlmostEqual(rubricas["restauro"].divergencia_pct, (600 - 1800) / 1800 * 100)
        self.assertIsNone(rubricas["verificacao_e_dns"].divergencia_pct)
        self.assertIsNone(rubricas["deteccao"].divergencia_pct)

    def test_a_fronteira_das_duas_horas_e_inclusiva(self):
        lista = [calculo.Duracao("restauro", "restauro", 7200.0)]
        self.assertTrue(calculo.rto(lista, {"restauro": 30}).dentro_do_alvo)
        lista = [calculo.Duracao("restauro", "restauro", 7200.001)]
        self.assertFalse(calculo.rto(lista, {"restauro": 30}).dentro_do_alvo)

    def test_repetir_o_a_entre_100_e_120_min_nas_duas_pontas(self):
        def com(minutos):
            return calculo.rto([calculo.Duracao("restauro", "restauro", minutos * 60)],
                               {"restauro": 30}).repetir_cenario_a

        self.assertFalse(com(99.99))
        self.assertTrue(com(100))
        self.assertTrue(com(120))
        self.assertFalse(com(120.01))

    def test_o_orcamento_soma_os_105_min_do_paragrafo_8_2(self):
        self.assertEqual(sum(v for k, v in folha.ORCAMENTO_MIN.items() if k != "cofre"), 105)

    def test_o_cofre_e_rto_adicional_sem_orcamento(self):
        carimbos = _folha_a() + _medido("cofre", 0, 30)
        lista = calculo.duracoes(carimbos, "A")
        self.assertEqual(lista[-1].passo, "cofre")
        rto = calculo.rto(lista)
        cofre = {r.nome: r for r in rto.rubricas}["cofre"]
        self.assertEqual(cofre.medido_segundos, 30)
        self.assertIsNone(cofre.divergencia_pct)
        sem = calculo.rto(calculo.duracoes(_folha_a(), "A"))
        self.assertEqual(rto.composto_segundos - sem.composto_segundos, 30)


def _marcadores(*numeros: int, inicio: datetime = T0) -> list[tuple[int, datetime]]:
    return [(n, inicio + timedelta(seconds=n)) for n in numeros]


class TestRpo(unittest.TestCase):
    def test_a_diferenca_entre_o_ultimo_confirmado_e_o_ultimo_restaurado(self):
        r = calculo.rpo(_marcadores(*range(1, 101)), _marcadores(*range(1, 41)))
        self.assertEqual(r.segundos, 60)
        self.assertEqual(r.perdidos, 60)
        self.assertEqual(r.buracos, ())
        self.assertTrue(r.dentro_do_alvo)

    def test_um_buraco_a_meio_poe_fora_do_alvo_mesmo_com_rpo_zero(self):
        restaurados = _marcadores(*[n for n in range(1, 101) if n != 57])
        r = calculo.rpo(_marcadores(*range(1, 101)), restaurados)
        self.assertEqual(r.segundos, 0)
        self.assertEqual(r.buracos, (57,))
        self.assertFalse(r.dentro_do_alvo)

    def test_restaurado_sem_confirmacao_nao_e_rpo_negativo(self):
        r = calculo.rpo(_marcadores(*range(1, 11)), _marcadores(*range(1, 12)))
        self.assertEqual(r.segundos, 0)
        self.assertEqual(r.sem_confirmacao, 1)
        self.assertEqual(r.perdidos, 0)

    def test_fronteira_dos_300_s(self):
        self.assertTrue(calculo.rpo(_marcadores(301), _marcadores(1)).dentro_do_alvo)
        self.assertFalse(calculo.rpo(_marcadores(302), _marcadores(1)).dentro_do_alvo)

    def test_listas_vazias_recusam(self):
        with self.assertRaises(ValueError):
            calculo.rpo([], _marcadores(1))
        with self.assertRaises(ValueError):
            calculo.rpo(_marcadores(1), [])

    def test_a_ordem_de_entrada_nao_importa(self):
        r = calculo.rpo(list(reversed(_marcadores(*range(1, 11)))), _marcadores(5, 1, 3, 2, 4))
        self.assertEqual(r.ultimo_restaurado[0], 5)
        self.assertEqual(r.segundos, 5)


class TestPitr(unittest.TestCase):
    def test_provado_com_os_anteriores_e_sem_os_posteriores(self):
        alvo = T0 + timedelta(seconds=50.5)
        prova = calculo.prova_pitr(_marcadores(*range(1, 101)), _marcadores(*range(1, 51)), alvo)
        self.assertTrue(prova.provado)

    def test_um_posterior_presente_e_sempre_defeito(self):
        alvo = T0 + timedelta(seconds=50.5)
        prova = calculo.prova_pitr(_marcadores(*range(1, 101)), _marcadores(*range(1, 52)), alvo)
        self.assertEqual(prova.posteriores_presentes, (51,))
        self.assertFalse(prova.provado)

    def test_o_marcador_exactamente_em_t_e_posterior(self):
        alvo = T0 + timedelta(seconds=50)
        prova = calculo.prova_pitr(_marcadores(*range(1, 101)), _marcadores(*range(1, 51)), alvo)
        self.assertEqual(prova.posteriores_presentes, (50,))

    def test_um_anterior_em_falta_e_defeito_fora_da_fronteira(self):
        alvo = T0 + timedelta(seconds=50.3)
        prova = calculo.prova_pitr(_marcadores(*range(1, 101)), _marcadores(*range(1, 49)), alvo)
        self.assertEqual(prova.anteriores_em_falta, (49,))
        self.assertEqual(prova.na_fronteira, (50,))
        self.assertFalse(prova.provado)

    def test_na_fronteira_nao_conta_como_defeito(self):
        alvo = T0 + timedelta(seconds=50.2)
        prova = calculo.prova_pitr(_marcadores(*range(1, 101)), _marcadores(*range(1, 50)), alvo)
        self.assertEqual(prova.na_fronteira, (50,))
        self.assertTrue(prova.provado)


class TestReplica(unittest.TestCase):
    def test_rto_extrapolado_acima_das_duas_horas_pede_replica(self):
        d = calculo.decisao_replica(rto_extrapolado_segundos=7201, bd_prevista_gb=None)
        self.assertEqual(d.estado, "necessaria")

    def test_bd_prevista_acima_de_40_gb_pede_replica(self):
        d = calculo.decisao_replica(rto_extrapolado_segundos=60, bd_prevista_gb=40.1)
        self.assertEqual(d.estado, "necessaria")
        d = calculo.decisao_replica(rto_extrapolado_segundos=60, bd_prevista_gb=40)
        self.assertEqual(d.estado, "nao_necessaria")

    def test_sem_previsao_e_por_decidir_e_nao_nao_necessaria(self):
        d = calculo.decisao_replica(rto_extrapolado_segundos=60, bd_prevista_gb=None)
        self.assertEqual(d.estado, "por_decidir")

    def test_extrapolacao_linear_com_o_debito_medido(self):
        e = calculo.extrapolar(bytes_medidos=20 * 10 ** 9, segundos_medidos=400,
                               bytes_alvo=50 * 10 ** 9)
        self.assertEqual(e.segundos_extrapolados, 1000)
        self.assertEqual(e.debito_mbps, 400)

    def test_a_rede_de_100_mbps_impoe_os_1600_s_do_orcamento(self):
        self.assertEqual(
            calculo.restauro_em_rede_segundos(bytes_no_repositorio=20 * 10 ** 9, mbps=100), 1600)
        with self.assertRaises(ValueError):
            calculo.restauro_em_rede_segundos(bytes_no_repositorio=1, mbps=0)

    def test_duplicados_conta_so_os_repetidos(self):
        self.assertEqual(calculo.duplicados(["a", "b", "a", "c", "a"]), {"a": 3})
        self.assertEqual(calculo.duplicados([]), {})


if __name__ == "__main__":
    unittest.main()
