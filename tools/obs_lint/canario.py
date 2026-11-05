"""A prova de que o *lint* morde — o passo de canario do KAM-080.

Um *lint* verde sobre uma arvore limpa **nao prova nada**: prova que a arvore
esta limpa, ou que o *lint* nao olha. A diferenca so se ve pondo defeitos a
frente dele e exigindo que os veja.

E a disciplina que esta casa ja impoe no `ci-3b`, no `ci-9`, no `ci-11` e no
`log-lint`, e a razao esta escrita na *skill*: «a prova de que o lint morde» e
uma das tres coisas que nao se aceleram. Um teste de `lint_refs` esteve vermelho
durante sete PRs com o gate verde, porque ninguem corria a prova.

## A forma: cada fixture e uma raiz em miniatura

O `log_policy` consegue ter um ficheiro por fixture porque o seu *lint* le um
ficheiro de cada vez. Este le **duas superficies** que se citam uma a outra — o
catalogo e as regras —, pelo que a unidade minima que faz sentido e uma **raiz**
com as duas (mais um *stub* de runbook, para que um `runbook_url` valido possa
resolver).

Cada pasta de `negativas/` chama-se `<regra>__<descricao>` e a regra antes do
primeiro `__` e a que **tem de ser a unica** a morder. Uma fixture que morda
duas regras e tao defeituosa como uma que nao morda nenhuma: quer dizer que o
defeito que ela encena nao esta isolado, e entao o teste nao diz qual das duas
regras o apanhou.
"""

from __future__ import annotations

from pathlib import Path

from . import lint

#: Quantas positivas no minimo. Duas, pela razao do `log_policy`: um *lint* que
#: recusasse **tudo** passaria o canario com zero positivas, porque todas as
#: negativas mordiam.
MINIMO_DE_POSITIVAS = 2


def _raizes(pasta: Path) -> list[Path]:
    return sorted(p for p in pasta.iterdir() if p.is_dir())


def canario(pasta: Path) -> tuple[list[str], dict[str, int]]:
    """Corre o *lint* sobre as fixtures e devolve `(falhas, numeros)`.

    Levanta `lint.ConfiguracaoInvalida` se a pasta nao tiver as duas metades —
    uma pasta de canario vazia nao pode dar «tudo verde».
    """
    negativas_dir = pasta / "negativas"
    positivas_dir = pasta / "positivas"
    if not negativas_dir.is_dir() or not positivas_dir.is_dir():
        raise lint.ConfiguracaoInvalida(
            f"{pasta}: faltam `negativas/` e/ou `positivas/`"
        )

    falhas: list[str] = []
    negativas = _raizes(negativas_dir)
    positivas = _raizes(positivas_dir)

    vistas: set[str] = set()
    for raiz in negativas:
        esperada = raiz.name.split("__", 1)[0]
        vistas.add(esperada)
        try:
            achados, _ = lint.verificar(raiz)
        except lint.ConfiguracaoInvalida as erro:
            falhas.append(f"negativa {raiz.name}: nao se leu ({erro})")
            continue
        encontradas = {a.regra for a in achados}
        if not encontradas:
            falhas.append(
                f"negativa {raiz.name}: o lint NAO mordeu — esperava {esperada}"
            )
        elif encontradas != {esperada}:
            falhas.append(
                f"negativa {raiz.name}: esperava so {{{esperada}}}, "
                f"deu {{{', '.join(sorted(encontradas))}}}"
            )

    for raiz in positivas:
        try:
            achados, _ = lint.verificar(raiz)
        except lint.ConfiguracaoInvalida as erro:
            falhas.append(f"positiva {raiz.name}: nao se leu ({erro})")
            continue
        if achados:
            falhas.append(
                f"positiva {raiz.name}: devia passar e deu "
                f"{{{', '.join(sorted({a.regra for a in achados}))}}}"
            )

    # As obrigatorias vem do **codigo** e nao das fixtures, de proposito. Lidas
    # das fixtures, uma pasta vazia dava «todas cobertas» e o canario ficava
    # verde sem provar nada — e o mesmo argumento do `REGRAS_OBRIGATORIAS` do
    # `log_policy`.
    for regra in lint.REGRAS_OBRIGATORIAS:
        if regra not in vistas:
            falhas.append(f"sem negativa para a regra obrigatoria `{regra}`")

    if len(positivas) < MINIMO_DE_POSITIVAS:
        falhas.append(
            f"so {len(positivas)} positivas; o minimo e {MINIMO_DE_POSITIVAS}, "
            "para que um lint que recusa tudo nao passe"
        )

    return falhas, {"negativas": len(negativas), "positivas": len(positivas)}
