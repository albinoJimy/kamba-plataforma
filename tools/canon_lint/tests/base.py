"""Apoio aos testes do `canon_lint`: o repositorio real e copias descartaveis."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from canon_lint.dicionario import Saber

ROOT = Path(__file__).resolve().parents[3]

#: O que uma copia precisa para o `check` correr: as fontes do gate e as
#: superficies que existem hoje.
_COPIAR = (
    "specs/02_Dicionario_de_Dados_Canonico.md",
    "canon",
    "ci/canon-lint.yaml",
    "ci/canon-allow.yaml",
    "db/migrations/versions",
    "db/rls.py",
    "docs/tecnica",
    "tools/canon_lint/tests/fixtures",
)


def saber() -> Saber:
    return Saber.ler(ROOT)


class ComCopia(unittest.TestCase):
    """Cada teste recebe uma copia do que o gate le, num repositorio git proprio.

    As mutacoes fazem-se **na copia**: o repositorio real nunca e tocado, e um
    teste que rebente a meio nao deixa `main` com um `valor_kz` la dentro.
    """

    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="canon-lint-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        for relativo in _COPIAR:
            origem, destino = ROOT / relativo, self.raiz / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            if origem.is_dir():
                shutil.copytree(origem, destino, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy(origem, destino)
        subprocess.run(["git", "init", "-q"], cwd=self.raiz, check=True, capture_output=True)

    def trocar(self, relativo: str, velho: str, novo: str, vezes: int = 1) -> None:
        caminho = self.raiz / relativo
        texto = caminho.read_text(encoding="utf-8")
        self.assertEqual(
            texto.count(velho), vezes, f"a mutacao nao encontrou o que ia mudar em {relativo}: {velho!r}"
        )
        caminho.write_bytes(texto.replace(velho, novo).encode("utf-8"))

    def escrever(self, relativo: str, texto: str) -> None:
        caminho = self.raiz / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(texto.encode("utf-8"))
