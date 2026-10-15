"""O CI nao usa chaves estaticas (KAM-067, criterio 8; `docs/tecnica/08` §4.8).

A autenticacao do pipeline e por OIDC. Uma referencia ao cofre de segredos do
GitHub num workflow e, por definicao, uma chave de longa vida guardada fora do
repositorio e injectada em cada execucao — o que o criterio proibe.

O `docs/ci.md` §6 dizia que «um grep devolve zero». Isto e esse grep, a falhar.
Varre o texto inteiro, comentarios incluidos: um passo comentado com a
referencia la dentro e um passo a um caractere de voltar.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Achado, ler_texto, percorrer, relativo

#: As expressoes do GitHub nao distinguem maiusculas (`SECRETS.X` e o mesmo
#: contexto), e o contexto usa-se de mais formas do que `secrets.X`:
#: `secrets['X']`, `toJSON(secrets)`, `secrets: inherit`.
_REFERENCIA = re.compile(
    r"\bsecrets\s*(?:\.\s*[A-Za-z_]|\[)"
    r"|\bsecrets\s*:\s*inherit\b"
    r"|\$\{\{.*?\bsecrets\b",
    re.IGNORECASE,
)


def verificar(raiz: Path) -> tuple[list[Achado], dict]:
    achados: list[Achado] = []
    ficheiros = 0
    for caminho in percorrer(raiz):
        partes = caminho.relative_to(raiz).parts
        if not (len(partes) >= 3 and partes[0] == ".github" and caminho.suffix in (".yml", ".yaml")):
            continue
        ficheiros += 1
        for numero, linha in enumerate(ler_texto(caminho).split("\n"), start=1):
            if _REFERENCIA.search(linha):
                achados.append(
                    Achado(
                        "chave-estatica-no-ci", relativo(caminho, raiz), numero,
                        "referencia ao cofre de segredos do GitHub. O pipeline "
                        "autentica-se por OIDC (`id-token: write`); uma chave de "
                        "longa vida no cofre e o que o criterio proibe.",
                    )
                )
    return achados, {"ficheiros": ficheiros}
