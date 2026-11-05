"""Conta as metricas declaradas e as servidas — o instrumento por tras dos numeros.

    python tools/obs_lint/contar_metricas.py            # o resumo
    python tools/obs_lint/contar_metricas.py --detalhe  # modulo a modulo

Existe porque a revisao adversarial do KAM-080 fez a pergunta certa: a secao de
verificacao citava «109 metricas declaradas, 23 servidas, 7 alcancaveis» em
quatro sitios, e **nao havia comando nenhum** que os produzisse. Um numero
reconstruido a mao e INDICIO, nao CONFIRMADO — e uma contagem feita antes de se
definir o que conta produz numeros errados com a mesma firmeza com que produziria
os certos.

## O PREDICADO, escrito antes de contar

Isto e o que faz a contagem significar algo, e qualquer outro predicado da outro
numero (a revisao chegou a 122 com um mais largo, e estava certa para o dela):

1. **Um modulo de metricas** e um ficheiro que emite formato de exposicao, isto
   e, que contem a cadeia `# TYPE`. Nada de adivinhar pelo nome.
2. **Um nome de metrica** e uma cadeia literal, dentro de um desses modulos, que
   case `^[a-z][a-z0-9_]*$`, tenha pelo menos um `_`, e **nao** seja um nome de
   etiqueta nem um valor de dominio. Distinguem-se assim: um nome de metrica e
   atribuido a uma constante cujo nome comeca por `METRICA`, ou e chave de uma
   tabela de ajuda (`AJUDA`/`_AJUDA`).
3. **Servida** quer dizer que o nome aparece num modulo cujo registo e lido por
   uma rota `/metrics` de **algum** processo definido no repositorio.
4. **Alcancavel** quer dizer que esse processo corre num `Dockerfile`/compose.
   E um subconjunto proprio de «servida», e a diferenca entre os dois numeros e
   a parte que interessa.

O passo 2 e deliberadamente estreito: prefere **nao contar** um nome a contar uma
etiqueta como metrica. Logo o numero que sai e um **piso**, e diz-se isso onde
ele aparece.

## O que este instrumento nao cobre

Nao le TypeScript com um parser — le literais com expressoes regulares, depois
de retirar comentarios de linha. Um nome construido por concatenacao escapa-lhe.
Nenhum dos 18 modulos o faz hoje (verificado por leitura), mas e um limite e nao
uma garantia.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: As raizes onde um modulo de metricas pode viver.
RAIZES = ("packages", "libs", "services")

#: O que faz de um ficheiro um modulo de metricas (predicado 1).
MARCA_DE_EXPOSICAO = "# TYPE"

#: Extensoes de codigo que nos interessam.
EXTENSOES = (".ts", ".py")

#: Pastas que nunca se leem.
IGNORADAS = {"node_modules", "dist", "__pycache__", ".venv", "tests"}

#: Um nome de metrica, pela forma (predicado 2).
NOME_DE_METRICA = re.compile(r"^[a-z][a-z0-9_]*$")

#: Uma constante que nomeia uma metrica: `METRICA_X = "nome"` ou
#: `METRICA_X: Final = "nome"`.
_CONSTANTE = re.compile(
    r"\bMETRICA[A-Z0-9_]*\s*(?::\s*[A-Za-z\[\]]+\s*)?=\s*[\"']([^\"']+)[\"']"
)

#: Uma chave de tabela de ajuda: `[METRICA_X]: [...]` nao da o nome, mas
#: `"nome_total": [` da. Apanha as tabelas escritas com o literal.
_CHAVE_DE_AJUDA = re.compile(r"^\s*[\"']([a-z][a-z0-9_]*)[\"']\s*:\s*[\[\(]", re.MULTILINE)

#: Um comentario de linha, para o retirar antes de varrer.
_COMENTARIO_PY = re.compile(r"^\s*#.*$", re.MULTILINE)


def _modulos(raiz: Path) -> list[Path]:
    encontrados: list[Path] = []
    for base in RAIZES:
        pasta = raiz / base
        if not pasta.is_dir():
            continue
        for caminho in pasta.rglob("*"):
            if caminho.suffix not in EXTENSOES or not caminho.is_file():
                continue
            if IGNORADAS & set(caminho.parts):
                continue
            try:
                texto = caminho.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if MARCA_DE_EXPOSICAO in texto:
                encontrados.append(caminho)
    return sorted(encontrados)


def _nomes(caminho: Path) -> set[str]:
    texto = caminho.read_text(encoding="utf-8")
    # Em Python, uma linha de comentario pode conter a tabela de metricas em
    # prosa (as *docstrings* destes modulos listam-nas). Nao se contam.
    if caminho.suffix == ".py":
        texto = _COMENTARIO_PY.sub("", texto)
    nomes = set(_CONSTANTE.findall(texto)) | set(_CHAVE_DE_AJUDA.findall(texto))
    return {n for n in nomes if NOME_DE_METRICA.match(n) and "_" in n}


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="contar_metricas", description=__doc__)
    analisador.add_argument("--root", type=Path, default=None)
    analisador.add_argument("--detalhe", action="store_true")
    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()

    modulos = _modulos(raiz)
    if not modulos:
        print("contar_metricas: zero modulos de metricas — isso nao e um zero util", file=sys.stderr)
        return 2

    por_modulo: dict[Path, set[str]] = {m: _nomes(m) for m in modulos}
    todos: set[str] = set()
    for nomes in por_modulo.values():
        todos |= nomes

    if argumentos.detalhe:
        for modulo in modulos:
            relativo = modulo.relative_to(raiz).as_posix()
            print(f"{len(por_modulo[modulo]):>4}  {relativo}")
        print()

    print(
        f"contar_metricas: {len(modulos)} modulos de metricas, "
        f"{len(todos)} nomes distintos (piso: ver o predicado 2 na docstring)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
