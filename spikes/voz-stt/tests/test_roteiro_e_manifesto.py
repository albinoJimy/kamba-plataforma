import dataclasses
import re
import unittest
from decimal import Decimal
from pathlib import Path

from manifesto import ler, ler_roteiro, verificar
from normalizar import UNIDADES, normalizar
from roteiro import em_ruido, folhas, marcadas, palavras

from tests.apoio import corpus, escrever_manifesto, pasta_temporaria


class TestRoteiro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roteiro = ler_roteiro()

    def test_cerca_de_220(self):
        self.assertEqual(len(self.roteiro), 220)

    def test_ids_seguidos(self):
        self.assertEqual(sorted(self.roteiro), [f"E{i:03d}" for i in range(1, 221)])

    def test_proporcoes_do_roteiro_acima_das_quotas(self):
        n = len(self.roteiro)
        self.assertGreaterEqual(sum(e.numeros for e in self.roteiro.values()) / n, 0.40)
        self.assertGreaterEqual(sum(e.linguas for e in self.roteiro.values()) / n, 0.20)

    def test_marca_de_linguas_bate_com_a_lista(self):
        for e in self.roteiro.values():
            with self.subTest(id=e.id):
                self.assertEqual(bool(marcadas(e.texto)), e.linguas, marcadas(e.texto))

    def test_marca_de_numeros_bate_com_o_texto(self):
        # «um»/«uma» são artigo na maior parte das frases e não contam aqui.
        nomes = set(UNIDADES) - {"um", "uma"} | {"mil", "milhao", "milhoes"}
        for e in self.roteiro.values():
            com = bool(re.search(r"\d", e.texto)) or any(p in nomes for p in palavras(e.texto))
            with self.subTest(id=e.id):
                self.assertEqual(com, e.numeros)

    def test_tamanho_para_5_a_30_segundos(self):
        # 12 a 45 palavras escritas, a 2 a 3 palavras por segundo lidas.
        for e in self.roteiro.values():
            with self.subTest(id=e.id):
                self.assertTrue(12 <= len(e.texto.split()) <= 45, len(e.texto.split()))

    def test_sem_nada_com_forma_de_dado_pessoal(self):
        for e in self.roteiro.values():
            with self.subTest(id=e.id):
                self.assertIsNone(re.search(r"\d{5,}|\+\d|@|\bIBAN\b|\bNIF\b", e.texto))
                self.assertTrue(normalizar(e.texto))

    def test_folhas_cada_uma_cumpre_as_quotas(self):
        fs = folhas(self.roteiro)
        self.assertEqual([len(f) for f in fs], [22] * 10)
        self.assertEqual(sorted(e.id for f in fs for e in f), sorted(self.roteiro))
        for k, f in enumerate(fs, start=1):
            with self.subTest(folha=k):
                self.assertGreaterEqual(sum(e.numeros for e in f) / len(f), 0.40)
                self.assertGreaterEqual(sum(e.linguas for e in f) / len(f), 0.20)
                self.assertGreaterEqual(sum(em_ruido(i) for i in range(len(f))) / len(f), 0.20)


class TestManifesto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roteiro = ler_roteiro()

    def test_corpus_que_cumpre_da_zero_achados(self):
        self.assertEqual(verificar(corpus(), self.roteiro), [])

    def test_ida_e_volta_pelo_csv(self):
        clips = corpus()
        with pasta_temporaria() as d:
            caminho = Path(d) / "m.csv"
            escrever_manifesto(clips, caminho)
            self.assertEqual(ler(caminho), clips)

    def test_cada_quota_morde(self):
        base = corpus()
        casos = {
            "falantes": [dataclasses.replace(c, falante_id="F01") if c.falante_id == "F10" else c for c in base],
            "enunciados": base[:150],
            "ruido": [dataclasses.replace(c, ambiente="silencioso") for c in base],
            "duracao": [dataclasses.replace(base[0], duracao_s=Decimal("4.9"))] + base[1:],
            "divergencia": [dataclasses.replace(c, ref_b="nada a ver com isto") for c in base],
        }
        esperado = {
            "falantes": "falantes",
            "enunciados": "enunciados, mínimo",
            "ruido": "ambiente ruidoso",
            "duracao": "fora de 5 a 30 s",
            "divergencia": "divergência",
        }
        for nome, clips in casos.items():
            with self.subTest(caso=nome):
                achados = verificar(clips, self.roteiro)
                self.assertTrue(any(esperado[nome] in a for a in achados), achados)

    def test_quota_de_numeros_e_de_linguas_morde(self):
        sem = [e.id for e in self.roteiro.values() if not e.numeros and not e.linguas]
        clips = [dataclasses.replace(c, enunciados=(sem[i % len(sem)],)) for i, c in enumerate(corpus())]
        achados = verificar(clips, self.roteiro)
        self.assertTrue(any("com números" in a for a in achados), achados)
        self.assertTrue(any("línguas nacionais" in a for a in achados), achados)

    def test_falante_com_nome_e_recusado(self):
        c = dataclasses.replace(corpus()[0], falante_id="Maria")
        self.assertTrue(any("pseudónimo" in a for a in verificar([c], self.roteiro)))

    def test_ficheiro_que_sai_da_pasta_e_recusado(self):
        for f in ("../fora.ogg", "/abs/x.ogg", "C:\\x.ogg", "F01/x.wav"):
            c = dataclasses.replace(corpus()[0], ficheiro=f)
            with self.subTest(ficheiro=f):
                self.assertTrue(any("ficheiro" in a for a in verificar([c], self.roteiro)))

    def test_clip_de_latencia_fora_dos_tres_tamanhos(self):
        c = dataclasses.replace(corpus()[0], tipo="latencia", enunciados=("E001", "E002"), duracao_s=Decimal("10"))
        self.assertTrue(any("latência" in a for a in verificar([c], self.roteiro)))
        ok = dataclasses.replace(c, duracao_s=Decimal("15.0065"))
        self.assertFalse(any("latência" in a for a in verificar([ok], self.roteiro)))


if __name__ == "__main__":
    unittest.main()
