import dataclasses
import json
import unittest
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from autorizacao import Autorizacao, EnvioRecusado
from falso import RelogioFalso, SttFalso, resumo
from fornecedores import VAR_CHAVE, construir, ler_groq, ler_openai, multipart
from harness import RAIZ_DO_REPOSITORIO, DentroDoRepositorio, correr
from manifesto import ManifestoInvalido
from porta import ErroStt

from tests.apoio import corpus, escrever_audio, pasta_temporaria

HOJE = date(2026, 12, 10)


def autorizacao_completa(falantes, fornecedores=("groq", "openai")) -> dict:
    return {
        "consentimentos": {f: {"data": "2026-12-01", **{x: True for x in fornecedores}} for f in falantes},
        "x1": {
            "via": "risco_aceite",
            "referencia": "registo de aceitação n.º 1 (fictício)",
            "data": "2026-12-02",
            "permite_envio": True,
        },
        "fornecedores": {
            f: {"retencao_zero": True, "sem_treino": True, "verificado_em": "2026-12-03", "fonte": "página do fornecedor (fictício)"}
            for f in fornecedores
        },
    }


class Agora:
    def __init__(self):
        self.t = datetime(2026, 12, 10, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


class TestHarnessComDuplo(unittest.TestCase):
    def setUp(self):
        self.tmp = pasta_temporaria()
        self.d = Path(self.tmp.name)
        self.clips = corpus()[:12]
        self.audio = escrever_audio(self.clips, self.d / "audio")
        self.relogio = RelogioFalso()
        respostas = {resumo(self.audio[c.clip_id]): c.ref for c in self.clips}
        self.lento = resumo(self.audio[self.clips[3].clip_id])
        self.partido = resumo(self.audio[self.clips[4].clip_id])
        self.stt = SttFalso(
            respostas,
            self.relogio,
            latencia_s=lambda a: 40.0 if resumo(a) == self.lento else 1.25,
            falhas={self.partido: "erro"},
            confiancas={resumo(self.audio[self.clips[0].clip_id]): 0.9},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def correr(self, **kw):
        destino = self.d / "r.jsonl"
        n = correr(self.clips, self.d / "audio", self.stt, destino, relogio=self.relogio, agora=Agora(), **kw)
        return n, [json.loads(l) for l in destino.read_text(encoding="utf-8").splitlines()]

    def test_uma_linha_por_execucao_com_os_campos_certos(self):
        n, linhas = self.correr()
        self.assertEqual(n, 12)
        self.assertEqual(
            set(linhas[0]),
            {"clip_id", "tipo", "fornecedor", "modelo", "inicio_utc", "latencia_ms", "estado", "hipotese", "confianca", "duracao_s", "regras"},
        )
        self.assertEqual(linhas[0]["latencia_ms"], 1250.0)
        self.assertEqual(linhas[0]["hipotese"], self.clips[0].ref)
        self.assertEqual(linhas[0]["confianca"], 0.9)
        self.assertIsNone(linhas[1]["confianca"])

    def test_timeout_e_erro_ficam_registados_sem_hipotese(self):
        _, linhas = self.correr(tecto_s=30.0)
        self.assertEqual((linhas[3]["estado"], linhas[3]["latencia_ms"], linhas[3]["hipotese"]), ("timeout", 30000.0, None))
        self.assertEqual((linhas[4]["estado"], linhas[4]["hipotese"]), ("erro", None))

    def test_a_linha_nao_leva_falante_nem_ficheiro_nem_audio(self):
        _, linhas = self.correr()
        texto = json.dumps(linhas, ensure_ascii=False)
        self.assertNotRegex(texto, r"\bF\d{2}\b")
        self.assertNotIn(".ogg", texto)
        self.assertNotIn("RIFF", texto)

    def test_repeticoes(self):
        n, linhas = self.correr(repeticoes=3)
        self.assertEqual(n, 36)
        self.assertEqual(len(self.stt.chamadas), 36)
        self.assertEqual({c[1:] for c in self.stt.chamadas}, {("audio/ogg", "pt")})

    def test_recusa_outro_repositorio_git(self):
        outro = self.d / "outro-checkout"
        (outro / ".git").mkdir(parents=True)
        with self.assertRaises(DentroDoRepositorio):
            correr(self.clips, self.d / "audio", self.stt, outro / "r.jsonl")
        self.assertEqual(self.stt.chamadas, [])

    def test_ficheiro_fora_da_pasta_do_falante_nao_se_envia(self):
        for ficheiro in ("F02/C0001.ogg", "../fora.ogg", "F01/../F02/x.ogg"):
            clips = [dataclasses.replace(self.clips[0], ficheiro=ficheiro)] + self.clips[1:]
            with self.subTest(ficheiro=ficheiro), self.assertRaises(ManifestoInvalido):
                correr(clips, self.d / "audio", self.stt, self.d / "r.jsonl", relogio=self.relogio)
        self.assertEqual(self.stt.chamadas, [])

    def test_recusa_destino_e_audio_dentro_do_repositorio(self):
        dentro = RAIZ_DO_REPOSITORIO / "spikes" / "voz-stt" / "nao-criar.jsonl"
        with self.assertRaises(DentroDoRepositorio):
            correr(self.clips, self.d / "audio", self.stt, dentro)
        self.assertFalse(dentro.exists())
        with self.assertRaises(DentroDoRepositorio):
            correr(self.clips, RAIZ_DO_REPOSITORIO, self.stt, self.d / "r.jsonl")


class TestAutorizacao(unittest.TestCase):
    FALANTES = ["F01", "F02"]

    def faltas(self, dados, fornecedor="groq"):
        return Autorizacao(dados).faltas(fornecedor, self.FALANTES, HOJE)

    def test_completa_passa(self):
        self.assertEqual(self.faltas(autorizacao_completa(self.FALANTES)), [])

    def test_vazia_diz_tudo_de_uma_vez(self):
        faltas = self.faltas({})
        self.assertTrue(any("consentimentos" in f for f in faltas))
        self.assertTrue(any("X1" in f for f in faltas))
        self.assertTrue(any("retenção" in f for f in faltas))

    def test_cada_condicao_morde(self):
        casos = {
            "consentimento em falta": lambda d: d["consentimentos"].pop("F02"),
            "consentimento futuro": lambda d: d["consentimentos"]["F01"].update(data="2027-01-01"),
            "consentimento só para outro fornecedor": lambda d: d["consentimentos"]["F02"].update(groq=False),
            "consentimento na forma antiga": lambda d: d["consentimentos"].update(F01="2026-12-01"),
            "X1 com data futura": lambda d: d["x1"].update(data="2027-01-01"),
            "X1 com data ilegível": lambda d: d["x1"].update(data="ontem"),
            "X1 que não permite o envio": lambda d: d["x1"].update(permite_envio=False),
            "X1 sem sentido escrito": lambda d: d["x1"].pop("permite_envio"),
            "verificação futura": lambda d: d["fornecedores"]["groq"].update(verificado_em="2027-01-01"),
            "verificação sem data": lambda d: d["fornecedores"]["groq"].pop("verificado_em"),
            "X1 por responder": lambda d: d.pop("x1"),
            "X1 com via inventada": lambda d: d["x1"].update(via="conversa"),
            "X1 sem referência": lambda d: d["x1"].update(referencia=" "),
            "retenção": lambda d: d["fornecedores"]["groq"].update(retencao_zero=False),
            "treino": lambda d: d["fornecedores"]["groq"].update(sem_treino="sim"),
            "sem fonte": lambda d: d["fornecedores"]["groq"].pop("fonte"),
            "outro fornecedor": lambda d: d["fornecedores"].pop("groq"),
        }
        for nome, estragar in casos.items():
            dados = autorizacao_completa(self.FALANTES)
            estragar(dados)
            with self.subTest(caso=nome):
                self.assertTrue(self.faltas(dados))

    def test_nome_em_vez_de_pseudonimo(self):
        dados = autorizacao_completa(["Maria"])
        self.assertTrue(Autorizacao(dados).faltas("groq", ["Maria"], HOJE))

    def test_ficheiro_ilegivel_recusa(self):
        with pasta_temporaria() as d:
            p = Path(d) / "a.json"
            p.write_text("{", encoding="utf-8")
            with self.assertRaises(EnvioRecusado):
                Autorizacao.ler(p)
            with self.assertRaises(EnvioRecusado):
                Autorizacao.ler(Path(d) / "nao-existe.json")


class AbrirFalso:
    def __init__(self, estado=200, corpo=b'{"text": "ok"}'):
        self.estado, self.corpo, self.pedidos = estado, corpo, []

    def __call__(self, pedido: urllib.request.Request, tecto_s: float):
        self.pedidos.append(pedido)
        return self.estado, self.corpo


class TestFornecedores(unittest.TestCase):
    FALANTES = ["F01"]
    CHAVE = "chave-de-ensaio-que-nao-e-segredo"

    def construir(self, nome="groq", dados=None, ambiente=None, abrir=None):
        return construir(
            nome,
            Autorizacao(dados if dados is not None else autorizacao_completa(self.FALANTES)),
            self.FALANTES,
            ambiente={VAR_CHAVE[nome]: self.CHAVE} if ambiente is None else ambiente,
            abrir=abrir or AbrirFalso(),
            hoje=HOJE,
        )

    def test_sem_autorizacao_nao_ha_stt_real(self):
        abrir = AbrirFalso()
        with self.assertRaises(EnvioRecusado):
            self.construir(dados={}, abrir=abrir)
        self.assertEqual(abrir.pedidos, [])

    def test_sem_chave_nao_ha_stt_real(self):
        with self.assertRaises(EnvioRecusado) as ctx:
            self.construir(ambiente={})
        self.assertIn(VAR_CHAVE["groq"], str(ctx.exception))

    def test_pedido_leva_modelo_idioma_e_audio(self):
        for nome, modelo in (("groq", b"whisper-large-v3-turbo"), ("openai", b"gpt-4o-mini-transcribe")):
            abrir = AbrirFalso()
            stt = self.construir(nome, abrir=abrir)
            stt.transcrever(b"AUDIO-SINTETICO", mime="audio/ogg", idioma="pt", tecto_s=5)
            corpo = abrir.pedidos[0].data
            with self.subTest(fornecedor=nome):
                self.assertIn(modelo, corpo)
                self.assertIn(b'name="language"\r\n\r\npt', corpo)
                self.assertIn(b"AUDIO-SINTETICO", corpo)
                self.assertEqual(abrir.pedidos[0].get_header("Authorization"), f"Bearer {self.CHAVE}")

    def test_a_chave_nao_aparece_em_repr_nem_em_erro(self):
        stt = self.construir(abrir=AbrirFalso(estado=401, corpo=b""))
        self.assertNotIn(self.CHAVE, repr(stt))
        with self.assertRaises(ErroStt) as ctx:
            stt.transcrever(b"x", mime="audio/ogg", idioma="pt", tecto_s=5)
        self.assertEqual(ctx.exception.tipo, "erro")
        self.assertNotIn(self.CHAVE, str(ctx.exception))

    def test_resposta_ilegivel_e_erro(self):
        stt = self.construir(abrir=AbrirFalso(corpo=b"<html>"))
        with self.assertRaises(ErroStt):
            stt.transcrever(b"x", mime="audio/ogg", idioma="pt", tecto_s=5)

    def test_leitura_da_confianca(self):
        g = ler_groq({"text": "a", "segments": [{"avg_logprob": 0.0}, {"avg_logprob": -0.6931471805599453}]})
        self.assertAlmostEqual(g.confianca, 0.5)
        self.assertIsNone(ler_groq({"text": "a"}).confianca)
        o = ler_openai({"text": "a", "logprobs": [{"logprob": 0.0}, {"logprob": -1.3862943611198906}]})
        self.assertAlmostEqual(o.confianca, 0.5)
        self.assertIsNone(ler_openai({"text": "a", "logprobs": []}).confianca)
        with self.assertRaises(ErroStt):
            ler_groq({"segments": []})

    def test_redireccionamento_nao_se_segue(self):
        import fornecedores

        self.assertTrue(any(isinstance(h, fornecedores._SemRedireccionar) for h in fornecedores._ABRIDOR.handlers))
        self.assertIsNone(fornecedores._SemRedireccionar().redirect_request(None, None, 302, "", {}, "https://outro/"))

    def test_multipart_bem_formado(self):
        tipo, corpo = multipart([("model", "m")], "clip.ogg", "audio/ogg", b"\x00\x01")
        fronteira = tipo.split("boundary=")[1].encode()
        self.assertTrue(corpo.startswith(b"--" + fronteira))
        self.assertTrue(corpo.endswith(b"--" + fronteira + b"--\r\n"))
        self.assertIn(b'filename="clip.ogg"\r\nContent-Type: audio/ogg\r\n\r\n\x00\x01\r\n', corpo)


if __name__ == "__main__":
    unittest.main()
