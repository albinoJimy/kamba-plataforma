"""A linha de comandos: 0 passa, 1 recusa, 2 nao se leu — e 2 nunca e verde."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from release import cli
from release.tests.apoio import COMMIT, RAIZ, lock_com


def _correr(*argv: str) -> tuple[int, str]:
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
        codigo = cli.main(["--root", str(RAIZ), *argv])
    return codigo, saida.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pasta = Path(tmp.name)

    def _escrever(self, nome: str, conteudo) -> str:
        caminho = self.pasta / nome
        texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo)
        caminho.write_text(texto, encoding="utf-8")
        return str(caminho)

    def test_lock_gerar_sem_digests_do_build_recusa(self) -> None:
        codigo, texto = _correr("lock", "gerar", "--commit", COMMIT)
        self.assertEqual(codigo, 1)
        self.assertIn("gwy: servico `build:` sem digest", texto)

    def test_lock_verificar_e_diferencas(self) -> None:
        a = self._escrever("a.lock", lock_com(gwy=("a", "build")).como_json())
        b = self._escrever("b.lock", lock_com(gwy=("b", "build")).como_json())
        self.assertEqual(_correr("lock", "verificar", a)[0], 0)
        codigo, texto = _correr("lock", "diferencas", b, a)
        self.assertEqual(codigo, 0)
        self.assertIn("gwy:", texto)

    def test_lock_sem_ficheiro_e_erro_de_utilizacao(self) -> None:
        self.assertEqual(_correr("lock", "verificar")[0], 2)

    def test_aprovacao_por_ficheiro(self) -> None:
        pr = {"author": {"login": "a"}, "headRefOid": "c" * 40, "labels": [{"name": "dinheiro"}],
              "reviews": [{"author": {"login": "b"}, "state": "APPROVED", "commit": {"oid": "c" * 40}}],
              "files": [], "changedFiles": 0}
        codigo, texto = _correr("aprovacao", "--pr-json", self._escrever("pr.json", pr))
        self.assertEqual(codigo, 1)
        self.assertIn("1 de 2", texto)

    def test_smoke_guarda_aborta_com_1(self) -> None:
        producao = self._escrever("prod.json", {"numeros": ["999200000002"]})
        codigo, texto = _correr(
            "smoke-guarda", "--ambiente", "staging", "--numero", "999200000002",
            "--projecto", "staging", "--graph-base", "https://graph.facebook.com",
            "--producao", producao,
        )
        self.assertEqual(codigo, 1)
        self.assertIn("ABORTADO", texto)

    def test_reconciliar(self) -> None:
        ids = [f"m{i}" for i in range(3)]
        ensaio = self._escrever("ensaio.json", {
            "enviados": ids, "processados": ids, "respostas": ids, "acks_ms": {i: 10 for i in ids},
        })
        self.assertEqual(_correr("reconciliar", "--ensaio", ensaio, "--esperadas", "3")[0], 0)
        self.assertEqual(_correr("reconciliar", "--ensaio", ensaio)[0], 1)

    def test_tag_com_verificacao_vermelha_recusa(self) -> None:
        lock = self._escrever("release.lock", lock_com(gwy=("a", "build")).como_json())
        verificacao = self._escrever("v.json", {"healthz": False, "taxa_de_erro_do_ingress": 0,
                                                "idade_da_fila_s": 1, "sonda_externa": True})
        codigo, _ = _correr("tag", "--tipo", "menor", "--anterior", "v0.1.0", "--lock", lock,
                            "--sboms", str(self.pasta), "--verificacao", verificacao,
                            "--destino", str(self.pasta / "arq"))
        self.assertEqual(codigo, 1)
        self.assertFalse((self.pasta / "arq").exists())

    def test_imagem_sem_material_de_assinatura_e_erro(self) -> None:
        lock = self._escrever("release.lock", lock_com(gwy=("a", "build")).como_json())
        codigo, _ = _correr("imagem", "--lock", lock, "--artefactos", str(self.pasta))
        self.assertEqual(codigo, 2)

    def test_imagem_com_lock_que_nao_cobre_o_compose_recusa(self) -> None:
        lock = self._escrever("release.lock", lock_com(gwy=("a", "build")).como_json())
        codigo, texto = _correr("imagem", "--lock", lock, "--artefactos", str(self.pasta),
                                "--cosign-chave", "k.pub")
        self.assertEqual(codigo, 1)
        self.assertIn("origem-trocada", texto)

    def test_ficheiro_inexistente_e_2(self) -> None:
        self.assertEqual(_correr("reconciliar", "--ensaio", str(self.pasta / "nao.json"))[0], 2)


if __name__ == "__main__":
    unittest.main()
