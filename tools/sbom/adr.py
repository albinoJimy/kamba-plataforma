"""Os ADR que existem — para que «excepcao registada em ADR» nao aceite um inventado.

Dois sitios, e so esses: a tabela de `docs/tecnica/00_Arquitectura_Solucao.md`
§8 (ADR-NNN) e os ficheiros de `docs/adr/` (ADR-LNNN, locais).

Le-se da fonte em cada execucao, nunca de uma constante: um ADR novo passa a
valer no dia em que entra na tabela, e um identificador que la nao esta nao
vale por se parecer com um.
"""

from __future__ import annotations

import re
from pathlib import Path

ARQUITECTURA = "docs/tecnica/00_Arquitectura_Solucao.md"
LOCAIS = "docs/adr"

_LINHA = re.compile(r"^\|\s*\*{0,2}(ADR-[0-9]{3})\*{0,2}\s*\|", re.MULTILINE)
_FICHEIRO = re.compile(r"^(ADR-L[0-9]{3})\b")


def existentes(raiz: Path) -> frozenset[str]:
    """Os identificadores de ADR que as duas fontes definem. Vazio se faltarem."""
    encontrados: set[str] = set()
    arquitectura = raiz / ARQUITECTURA
    if arquitectura.is_file():
        encontrados.update(_LINHA.findall(arquitectura.read_text(encoding="utf-8", errors="replace")))
    locais = raiz / LOCAIS
    if locais.is_dir():
        for ficheiro in locais.iterdir():
            correspondencia = _FICHEIRO.match(ficheiro.name)
            if correspondencia and ficheiro.suffix == ".md":
                encontrados.add(correspondencia.group(1))
    return frozenset(encontrados)


def existe(raiz: Path, identificador: str) -> bool:
    return identificador in existentes(raiz)
