"""A linha de comandos da regra de dois (KAM-039).

```text
python -m reuse_metric medir  --root .            metrica de reaproveitamento
python -m reuse_metric nucleo --root .            criterio (d): nomes no nucleo
```

Codigos de saida, pela convencao dos linters desta casa (`lint_backlog`,
`lint_refs`):

```text
0   a medida passa o limiar / nenhum ramo do nucleo decide por vertical
1   achado: abaixo do limiar, ou `fluxo > 0`
2   a declaracao ou a arvore estao malformadas
```

**Nenhum destes comandos esta ligado a um portao do CI, e e deliberado.** Pôr
`fluxo > 0` ou `reuso < 70%` a falhar o *build* e mudar uma **regra de
bloqueio** — e um *job* novo acrescenta um contexto exigido ao *ruleset* da
`main`, que e a mesma fronteira. O que este ticket entrega e a medicao e a prova
de que ela morde; ligar a maquina a decide quem assina as regras de bloqueio.
A razao por extenso esta em `docs/reuse-metric.md` §5 e na seccao de
verificacao do bloco do KAM-039.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from kamba_yaml import YamlSubsetError, load_file

from . import caminho as caminho_mod
from . import nucleo as nucleo_mod

#: O ficheiro declarado. Um so, para as duas perguntas: a fronteira do nucleo e
#: a classificacao do caminho sao a mesma decisao vista de dois lados, e separa-las
#: em dois ficheiros era deixa-las divergir.
DECLARACAO = Path("ci") / "regra-de-dois.yaml"

#: As chaves de topo que este leitor conhece. **Declaradas, e nao implicitas:**
#: o `test_nenhuma_chave_de_topo_fica_por_declarar` do `lint_arch` confronta
#: cada `ci/*.yaml` com o conjunto do seu leitor, e uma chave acrescentada ao
#: ficheiro sem ninguem a ler fica vermelha em vez de ficar calada — foi o que
#: a `arredondamento` do `ci/thresholds.yaml` custou dois tickets.
CHAVES: Final[frozenset[str]] = frozenset({"version", "nucleo", "caminho"})


class ArvoreInvalidaError(RuntimeError):
    """A raiz dada nao e a raiz do repositorio."""


def ler_declaracao(raiz: Path) -> tuple[dict, str]:
    alvo = raiz / DECLARACAO
    if not alvo.is_file():
        raise ArvoreInvalidaError(
            f"{alvo} nao existe: `--root` tem de apontar para a raiz do repositorio"
        )
    try:
        return load_file(alvo), DECLARACAO.as_posix()
    except YamlSubsetError as erro:
        raise ArvoreInvalidaError(f"{DECLARACAO.as_posix()}: {erro}") from erro


def _escrever(destino: Path | None, mapa: dict) -> None:
    """O artefacto JSON, se o pedirem.

    `sort_keys=False` de proposito: a ordem das chaves do mapa e a ordem em que
    um humano as le — a formula, as parcelas, e so depois a lista. E
    `ensure_ascii=False` porque os caminhos e as razoes sao em portugues.
    """
    if destino is None:
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(mapa, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def medir(raiz: Path, *, destino: Path | None, limiar: float | None) -> int:
    bruto, onde = ler_declaracao(raiz)
    medicao = caminho_mod.medir(raiz, bruto, onde=onde)
    mapa = medicao.como_mapa()
    _escrever(destino, mapa)

    declarado = caminho_mod.Declaracao.de_mapa(bruto, onde=onde).limiar
    alvo = declarado if limiar is None else limiar
    print(
        f"reuso da vertical `{medicao.vertical}`: {medicao.reuso:.2f}% "
        f"(especifico {medicao.especifico}, partilhado {medicao.partilhado}, "
        f"total {medicao.total} linhas com codigo)"
    )
    print(
        f"    {len(medicao.entradas)} entradas na conta, "
        f"{len(medicao.fora)} fora dela (ver `fora_da_conta`)"
    )
    if destino is not None:
        print(f"    artefacto: {destino}")
    if medicao.reuso < alvo:
        print(
            f"ACHADO: {medicao.reuso:.2f}% esta abaixo do limiar de {alvo:.2f}% "
            "(ADR-012, docs/tecnica/02 §5.4)",
            file=sys.stderr,
        )
        return 1
    print(f"    passa o limiar de {alvo:.2f}%")
    return 0


def nucleo(raiz: Path, *, destino: Path | None) -> int:
    bruto, onde = ler_declaracao(raiz)
    veredicto = nucleo_mod.verificar(raiz, bruto, onde=onde)
    _escrever(destino, veredicto.como_mapa())

    print(
        f"nucleo: {veredicto.ficheiros} ficheiros varridos; "
        f"fluxo {veredicto.fluxo}, dominio {veredicto.dominio}, "
        f"conteudo {veredicto.conteudo}, prosa {veredicto.prosa}"
    )
    if destino is not None:
        print(f"    artefacto: {destino}")
    for ocorrencia in veredicto.de_classe("fluxo"):
        print(
            f"ACHADO {ocorrencia.ficheiro}:{ocorrencia.linha}: o nucleo decide por "
            f"`{ocorrencia.nome}` ({ocorrencia.forma}) — {ocorrencia.trecho}",
            file=sys.stderr,
        )
    if not veredicto.passa:
        print(
            "ACHADO: a condicao (d) de `docs/tecnica/02` §5.4 exige 0 ramos do "
            "nucleo decididos por nome de vertical",
            file=sys.stderr,
        )
        return 1
    print("    condicao (d): 0 ramos decididos por nome de vertical")
    if veredicto.conteudo:
        print(
            f"    {veredicto.conteudo} ocorrencia(s) de `conteudo` — tabelas e "
            "identificadores que NOMEIAM uma vertical. Nao reprovam a condicao "
            "(d) por si; ver docs/reuse-metric.md §4 e o relatorio do ticket."
        )
    return 0


def principal(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="python -m reuse_metric",
        description="A regra de dois (ADR-012): reaproveitamento e nucleo sem excepcoes",
    )
    analisador.add_argument(
        "--root",
        default=".",
        help="a raiz do repositorio (onde esta `ci/regra-de-dois.yaml`)",
    )
    analisador.add_argument(
        "--json",
        default=None,
        help="escreve o artefacto JSON neste caminho",
    )
    subcomandos = analisador.add_subparsers(dest="comando", required=True)
    medida = subcomandos.add_parser("medir", help="a metrica de reaproveitamento")
    medida.add_argument(
        "--limiar",
        type=float,
        default=None,
        help="sobrepoe o limiar declarado (em percentagem)",
    )
    subcomandos.add_parser("nucleo", help="o criterio (d): nomes de vertical no nucleo")

    opcoes = analisador.parse_args(argumentos)
    raiz = Path(opcoes.root).resolve()
    destino = Path(opcoes.json).resolve() if opcoes.json else None

    try:
        if opcoes.comando == "medir":
            return medir(raiz, destino=destino, limiar=opcoes.limiar)
        return nucleo(raiz, destino=destino)
    except (
        ArvoreInvalidaError,
        caminho_mod.DeclaracaoInvalidaError,
        caminho_mod.CadeiaInvalidaError,
        nucleo_mod.DeclaracaoDoNucleoInvalidaError,
        caminho_mod.SimboloAusenteError,
    ) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 2
