"""Latência, custo, relatório e apagamento, sobre medições fabricadas."""

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import custo
import latencia
from apagamento import apagar, atrasados
from manifesto import ler_roteiro
from relatorio import (
    LIMIARES,
    RelatorioRecusado,
    exigir_limiares_antes,
    exigir_sem_identificacao,
    gerar,
    ramo_da_regra,
)

from tests.apoio import corpus, escrever_audio, pasta_temporaria


def execucao(clip_id, fornecedor, tipo, duracao, quando, latencia_ms, estado="ok", hipotese="", confianca=None):
    return {
        "clip_id": clip_id,
        "tipo": tipo,
        "fornecedor": fornecedor,
        "modelo": "m",
        "inicio_utc": quando.isoformat(),
        "latencia_ms": latencia_ms,
        "estado": estado,
        "hipotese": hipotese if estado == "ok" else None,
        "confianca": confianca,
        "duracao_s": str(duracao),
        "regras": "1",
    }


#: 08h, 14h e 20h em Luanda são 07h, 13h e 19h UTC.
MOMENTOS_UTC = (7, 13, 19)
DIA = datetime(2026, 12, 10, tzinfo=timezone.utc)


def execucoes_de_latencia(fornecedor, latencias_ms, por_momento=10):
    linhas = []
    for t in (5, 15, 30):
        k = 0
        for h in MOMENTOS_UTC:
            for i in range(por_momento):
                quando = DIA + timedelta(hours=h, minutes=i)
                linhas.append(execucao("C9001", fornecedor, "latencia", f"{t}.0065", quando, latencias_ms[k % len(latencias_ms)]))
                k += 1
    return linhas


class TestLatencia(unittest.TestCase):
    def test_percentil_posto_mais_proximo(self):
        valores = list(range(1, 31))
        self.assertEqual(latencia.percentil(valores, 0.50), 15)
        self.assertEqual(latencia.percentil(valores, 0.95), 29)
        self.assertEqual(latencia.percentil([7.0], 0.95), 7.0)
        with self.assertRaises(ValueError):
            latencia.percentil([], 0.5)

    def test_momento_na_hora_de_luanda(self):
        self.assertEqual(latencia.momento("2026-12-10T05:30:00+00:00"), "manha")  # 06h30 em Luanda
        self.assertIsNone(latencia.momento("2026-12-10T04:30:00+00:00"))  # 05h30
        self.assertEqual(latencia.momento("2026-12-10T22:59:00+00:00"), "noite")  # 23h59
        with self.assertRaises(ValueError):
            latencia.momento("2026-12-10T05:30:00")

    def test_trinta_em_tres_momentos_chega(self):
        linhas = latencia.resumir(execucoes_de_latencia("g", [1000.0]), "g")
        self.assertEqual([l.tamanho_s for l in linhas], [5, 15, 30])
        for l in linhas:
            self.assertEqual((l.execucoes, l.faltas, l.p95_ms), (30, [], 1000.0))

    def test_falta_um_momento_ou_execucoes(self):
        so_manha = [r for r in execucoes_de_latencia("g", [1000.0]) if r["inicio_utc"][11:13] == "07"]
        for l in latencia.resumir(so_manha, "g"):
            self.assertTrue(any("tarde" in f for f in l.faltas))
            self.assertTrue(any("mínimo 30" in f for f in l.faltas))

    def test_timeout_entra_na_latencia_e_erro_nao(self):
        rs = execucoes_de_latencia("g", [1000.0])
        rs[0] = dict(rs[0], estado="timeout", latencia_ms=30000.0)
        rs[1] = dict(rs[1], estado="timeout", latencia_ms=30000.0)
        rs[2] = dict(rs[2], estado="erro", latencia_ms=5.0)
        l5 = latencia.resumir(rs, "g")[0]
        self.assertEqual((l5.timeouts, l5.erros), (2, 1))
        self.assertEqual(l5.p95_ms, 30000.0)  # 2 em 29 acima do posto 28
        self.assertEqual(latencia.falhas(rs, "g").taxa, 3 / 90)


class TestCusto(unittest.TestCase):
    def setUp(self):
        self.t = custo.ler_precos()

    def test_le_os_precos_de_e4_com_data(self):
        self.assertEqual(self.t.lido_em, "2026-10-08")
        self.assertEqual(self.t.precos["groq"].usd_por_segundo * 3600, Decimal("0.04"))
        self.assertEqual(self.t.precos["openai"].usd_por_segundo * 60, Decimal("0.003"))

    def test_sem_minimo_bate_com_a_estimativa_do_doc_09(self):
        duracoes = [Decimal(30)] * 600  # 300 min de clips de 30 s
        self.assertEqual(custo.por_pme_mes(self.t.precos["groq"], duracoes).quantize(Decimal("0.01")), Decimal("0.20"))
        self.assertEqual(custo.por_pme_mes(self.t.precos["openai"], duracoes).quantize(Decimal("0.01")), Decimal("0.90"))

    def test_minimo_de_10_s_do_groq_pesa_em_clips_curtos(self):
        groq = self.t.precos["groq"]
        self.assertEqual(custo.custo_clip(groq, Decimal(5)), custo.custo_clip(groq, Decimal(10)))
        # clips de 5 s pagam o dobro por hora de áudio
        self.assertEqual(custo.por_hora(groq, [Decimal(5)] * 10), Decimal("0.08"))
        self.assertEqual(custo.por_hora(self.t.precos["openai"], [Decimal(5)] * 10), Decimal("0.18"))


class TestRelatorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roteiro = ler_roteiro()
        cls.clips = corpus()
        cls.limiares = json.loads(Path(LIMIARES).read_text(encoding="utf-8"))
        cls.precos = custo.ler_precos()

    def resultados(self, fornecedor, estragar_numeros=False, latencia_ms=(1200.0,)):
        rs = []
        for i, c in enumerate(self.clips):
            hip = c.ref
            # à cabeça e não ao fim: depois de «mil», o «7» compunha-se em «mil e
            # sete» pelas regras, e deixava de ser um número inventado
            if estragar_numeros and i % 3 == 0:
                hip = "7 " + hip
            rs.append(execucao(c.clip_id, fornecedor, "enunciado", c.duracao_s, DIA + timedelta(hours=8, seconds=i), 900.0, hipotese=hip))
        return rs + execucoes_de_latencia(fornecedor, list(latencia_ms))

    def test_limiares_de_hoje_e_medicao_amanha_passa(self):
        self.assertEqual(self.limiares["registado_em"], "2026-11-25")
        primeira = exigir_limiares_antes(self.limiares, self.resultados("groq"))
        self.assertEqual(str(primeira), "2026-12-10")

    def test_limiares_no_dia_da_medicao_ou_depois_sao_recusados(self):
        for registado in ("2026-12-10", "2026-12-11", None):
            lim = dict(self.limiares, registado_em=registado)
            with self.subTest(registado=registado), self.assertRaises(RelatorioRecusado):
                exigir_limiares_antes(lim, self.resultados("groq"))

    def test_limiar_de_confianca_tem_data_propria(self):
        lim = copy.deepcopy(self.limiares)
        lim["confianca"]["limiar"]["groq"] = 0.5
        with self.assertRaises(RelatorioRecusado):
            exigir_limiares_antes(lim, self.resultados("groq"))
        lim["confianca"]["registado_em"] = "2026-12-01"
        exigir_limiares_antes(lim, self.resultados("groq"))

    def test_gera_sem_identificacao(self):
        texto = gerar(self.clips, self.resultados("groq") + self.resultados("openai"), self.limiares, self.precos, self.roteiro)
        self.assertIn("### groq", texto)
        self.assertIn("| global | 220 |", texto)
        self.assertNotRegex(texto, r"\bF\d{2}\b|\bC\d{4}\b|\.ogg")
        for c in self.clips[:20]:
            self.assertNotIn(c.ref, texto)
        # sem sinal devolvido, o limiar de confiança fica não medido e a regra não se aplica
        self.assertIn("não aplicável (a API não devolveu sinal)", texto)
        self.assertIn("não aplicável: há limiares não medidos", texto)
        self.assertIn("| $0,0500 | $0,2500 | $0,2000 |", texto)  # o mínimo de 10 s do Groq com clips de 8 s

    def test_sinal_sem_limiar_fixado_fica_por_calcular(self):
        rs = self.resultados("groq")
        for r in rs:
            r["confianca"] = 0.9
        texto = gerar(self.clips, rs, self.limiares, self.precos, self.roteiro)
        self.assertIn("**S**", texto)
        self.assertIn("por calcular: limiar de confiança por fixar", texto)

    def test_guarda_de_identificacao_morde(self):
        for proibido in ("F03 disse", "o C0012", "clip.ogg", "923" + "456" + "789", "QUJD" * 12):
            with self.subTest(proibido=proibido), self.assertRaises(RelatorioRecusado):
                exigir_sem_identificacao(f"| x | {proibido} |")
        exigir_sem_identificacao("| WER | 12,5% | 2026-12-10 |")

    def test_ramo_da_regra(self):
        passa = {"wer": "passa", "numeros": "passa", "latencia": "passa", "confianca": "passa"}
        so_num = dict(passa, numeros="falha")
        falha = dict(passa, wer="falha")
        custo_h = {"groq": Decimal("0.05"), "openai": Decimal("0.18")}
        self.assertIn("groq primário", ramo_da_regra({"groq": passa, "openai": passa}, custo_h))
        self.assertIn("só um passa: openai", ramo_da_regra({"groq": falha, "openai": passa}, custo_h))
        self.assertIn("eco e confirmação", ramo_da_regra({"groq": so_num, "openai": falha}, custo_h))
        self.assertIn("handoff", ramo_da_regra({"groq": falha, "openai": falha}, custo_h))
        self.assertIn("não aplicável", ramo_da_regra({"groq": dict(passa, latencia="não medido"), "openai": passa}, custo_h))

    def test_numeros_estragados_falham_a_precisao(self):
        lim = copy.deepcopy(self.limiares)
        texto = gerar(self.clips, self.resultados("groq", estragar_numeros=True), lim, self.precos, self.roteiro)
        linha = next(l for l in texto.splitlines() if l.startswith("| Precisão numérica ≥"))
        self.assertIn("passa", linha)  # um número inventado não tira acertos: conta à parte
        self.assertRegex(texto, r"\| 100,0% \| \d+ \| \d+ \| 7\d \|")

    def test_confianca_com_limiar_fixado(self):
        lim = copy.deepcopy(self.limiares)
        lim["confianca"]["limiar"]["groq"] = 0.5
        lim["confianca"]["registado_em"] = "2026-12-01"
        rs = self.resultados("groq")
        for r in rs[:10]:
            r["hipotese"] = "nada que ver"
            r["confianca"] = 0.2
        for r in rs[10:15]:
            r["hipotese"] = "nada que ver"
            r["confianca"] = 0.9
        for r in rs[15:220]:
            r["confianca"] = 0.95
        texto = gerar(self.clips, rs, lim, self.precos, self.roteiro)
        self.assertIn("66,7% (10 de 15)", texto)
        linha = next(l for l in texto.splitlines() if l.startswith("| Sinal assinala"))
        self.assertIn("falha", linha)


class TestApagamento(unittest.TestCase):
    def test_atrasados_e_apagar(self):
        clips = corpus()[:4]
        with pasta_temporaria() as d:
            pasta = Path(d) / "audio"
            escrever_audio(clips, pasta)
            ontem = DIA - timedelta(hours=30)
            rs = [
                execucao(clips[0].clip_id, "g", "enunciado", 8, ontem, 1.0, hipotese="x"),
                execucao(clips[1].clip_id, "g", "enunciado", 8, DIA - timedelta(hours=2), 1.0, hipotese="x"),
                execucao(clips[2].clip_id, "g", "enunciado", 8, ontem, 1.0, estado="erro"),
            ]
            achados = atrasados(clips, pasta, rs, DIA)
            self.assertEqual(len(achados), 1)
            self.assertIn(clips[0].clip_id, achados[0])
            estranho = pasta / "nao-e-do-manifesto.ogg"
            estranho.write_bytes(b"x")
            self.assertEqual(apagar(clips, pasta), (4, 0))
            self.assertTrue(estranho.exists())
            self.assertEqual(apagar(clips, pasta), (0, 4))
            self.assertEqual(atrasados(clips, pasta, rs, DIA), [])


if __name__ == "__main__":
    unittest.main()
