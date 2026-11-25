"""O `release.lock`: gerado antes do deploy, por digest, sem buracos."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from release import lock
from release.tests.apoio import COMMIT, RAIZ, digest, lock_com


class TestGerar(unittest.TestCase):
    def test_build_sem_digest_falha_e_diz_qual(self) -> None:
        with self.assertRaises(lock.LockInvalido) as erro:
            lock.gerar({"gwy": None, "postgres": f"pg@{digest('b')}"}, {}, COMMIT)
        self.assertIn("gwy: servico `build:` sem digest", str(erro.exception))

    def test_terceiros_vem_do_compose_e_build_do_ficheiro(self) -> None:
        gerado = lock.gerar(
            {"gwy": None, "postgres": f"pg@{digest('b')}"},
            {"gwy": f"r/gwy@{digest('a')}"},
            COMMIT,
        )
        self.assertEqual(gerado.servicos["gwy"].origem, "build")
        self.assertEqual(gerado.servicos["postgres"].origem, "terceiros")

    def test_digest_para_servico_inexistente_falha(self) -> None:
        with self.assertRaises(lock.LockInvalido) as erro:
            lock.gerar({"gwy": None}, {"gwy": f"r/gwy@{digest('a')}", "outro": f"r/o@{digest('c')}"}, COMMIT)
        self.assertIn("outro", str(erro.exception))

    def test_build_nao_substitui_imagem_fixada_no_compose(self) -> None:
        with self.assertRaises(lock.LockInvalido):
            lock.gerar({"pg": f"pg@{digest('b')}"}, {"pg": f"r/pg@{digest('c')}"}, COMMIT)

    def test_etiqueta_sem_digest_falha(self) -> None:
        with self.assertRaises(lock.LockInvalido) as erro:
            lock.gerar({"gwy": None}, {"gwy": "r/gwy:1.0"}, COMMIT)
        self.assertIn("@sha256", str(erro.exception))

    def test_commit_curto_falha(self) -> None:
        with self.assertRaises(lock.LockInvalido):
            lock.gerar({"gwy": None}, {"gwy": f"r/gwy@{digest('a')}"}, "abc1234")


class TestLerEEscrever(unittest.TestCase):
    def test_ida_e_volta_e_deterministica(self) -> None:
        original = lock_com(gwy=("a", "build"), postgres=("b", "terceiros"))
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "release.lock"
            caminho.write_text(original.como_json(), encoding="utf-8")
            lido = lock.ler(caminho)
        self.assertEqual(lido, original)
        self.assertEqual(lido.como_json(), original.como_json())

    def test_formato_errado_falha(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "release.lock"
            caminho.write_text(json.dumps({"formato": 2, "servicos": {}}), encoding="utf-8")
            with self.assertRaises(lock.LockInvalido):
                lock.ler(caminho)

    def test_diferencas_so_do_que_mudou(self) -> None:
        anterior = lock_com(gwy=("a", "build"), postgres=("b", "terceiros"))
        novo = lock_com(gwy=("c", "build"), postgres=("b", "terceiros"))
        self.assertEqual(list(novo.diferencas(anterior)), ["gwy"])


class TestComposeDeProducao(unittest.TestCase):
    """Contra o compose real: o leitor e o do gate 11, e tem de concordar."""

    def test_os_servicos_build_sao_os_que_pedem_digest(self) -> None:
        servicos = lock.servicos_do_compose(
            RAIZ / "infra" / "compose" / "docker-compose.prod.yml", RAIZ
        )
        construidos = {n for n, i in servicos.items() if i is None}
        self.assertIn("gwy", construidos)
        self.assertIn("agr", construidos)
        for nome, imagem in servicos.items():
            if imagem is not None:
                self.assertRegex(imagem, lock.REFERENCIA_POR_DIGEST, nome)


if __name__ == "__main__":
    unittest.main()
