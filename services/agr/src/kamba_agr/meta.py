"""Identidade do servico.

A versao vem dos metadados do pacote instalado e nao de uma constante escrita a
mao: duas versoes em dois sitios divergem. Quando o pacote nao esta instalado
(execucao directa da arvore de fontes), cai para a versao declarada no
`pyproject.toml`.
"""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

SERVICE = "agr"

#: Porta de escuta por omissao, coerente com infra/compose e com o .env.example.
DEFAULT_PORT = 8000

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _version() -> str:
    try:
        return metadata.version("kamba-agr")
    except metadata.PackageNotFoundError:
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        return str(data["project"]["version"])


VERSION = _version()
