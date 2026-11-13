"""O *gate* do §14.3 e a linha de base versionada (KAM-064, criterios 6 e 7).

    python -m eval_search.gate verificar <relatorio.json> [--linha-de-base X]
    python -m eval_search.gate registar <relatorio.json> --versao 1.0.0

`verificar` sai com 1 se, em algum modo que a linha de base tem:

* o **nDCG@3** global cai mais de **2 pontos** (0,02);
* o **zero-result rate** global sobe mais de **1 ponto** (0,01);
* ha **um** produto citado inexistente ou **um** preco divergente;
* uma consulta do modo hibrido caiu em lexical;
* o modo falta no relatorio, ou o *dataset* nao e o da linha de base, ou o
  fornecedor do modo hibrido mudou (uma troca de modelo regista linha nova).

**O que o comando nao faz, e e decisao do fundador:** correr como *job* de CI
nas alteracoes de dicionario, pesos, modelo, limiar e `idx.candidatos`, e
juntar-lhe os testes de isolamento do §6.4 e do §7.3 (*gate* 6). Um *job* novo
e um contexto exigido novo no *ruleset* de `main`. Ver o bloco do KAM-064,
criterio 6.

`registar` escreve `eval/search/baseline.json` **so** com um relatorio verde
(as asercoes a zero e os dois modos medidos) e com uma versao SemVer maior do
que a registada.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from . import dataset as dataset_mod
from . import runner

LINHA_DE_BASE: Final = dataset_mod.RAIZ / "eval" / "search" / "baseline.json"

#: As tolerancias do §14.3, em fraccao (2 pontos = 0,02).
QUEDA_MAXIMA_DO_NDCG: Final = 0.02
SUBIDA_MAXIMA_DO_ZERO_RESULT: Final = 0.01

_SEMVER: Final = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

#: O que a linha de base guarda de cada modo: as metricas globais e por divisao.
_CAMPOS_DO_MODO: Final = ("global", "por_divisao")


def _versao(texto: str) -> tuple[int, int, int]:
    achado = _SEMVER.fullmatch(texto)
    if not achado:
        raise ValueError(f"versao nao e SemVer: {texto!r}")
    return tuple(int(x) for x in achado.groups())  # type: ignore[return-value]


def verificar(relatorio: Mapping[str, Any], linha_de_base: Mapping[str, Any]) -> list[str]:
    """As falhas do *gate*. Vazio = verde."""
    falhas: list[str] = []
    if relatorio.get("dataset") != linha_de_base.get("dataset"):
        falhas.append(
            f"o dataset mudou ({linha_de_base.get('dataset')} -> {relatorio.get('dataset')}): "
            "regista uma linha de base nova"
        )
    for modo, base in linha_de_base["modos"].items():
        medido = relatorio.get("modos", {}).get(modo)
        if medido is None:
            falhas.append(f"{modo}: o relatorio nao mede este modo")
            continue
        if modo == "hibrido" and relatorio.get("fornecedor_hibrido") != linha_de_base.get("fornecedor_hibrido"):
            falhas.append(
                "hibrido: o fornecedor de embeddings mudou "
                f"({linha_de_base.get('fornecedor_hibrido')} -> {relatorio.get('fornecedor_hibrido')}); "
                "uma troca de modelo regista linha de base nova"
            )
        if modo == "hibrido" and medido.get("caiu_em_lexical", 0):
            # Um hibrido que caiu em lexical mede o lexical duas vezes, e a
            # comparacao do §14.3 lia Δ = 0 (achado 4 da revisao).
            falhas.append(f"hibrido: {medido['caiu_em_lexical']} consulta(s) cairam em lexical")
        antes, agora = base["global"], medido["global"]
        # Arredondado a seis casas: 0,75 - 0,73 da 0,020000000000000018 em
        # virgula flutuante, e «cai 2 pontos» nao e «cai mais de 2».
        if agora["ndcg_at_3"] is None or round(antes["ndcg_at_3"] - agora["ndcg_at_3"], 6) > QUEDA_MAXIMA_DO_NDCG:
            falhas.append(f"{modo}: nDCG@3 {antes['ndcg_at_3']} -> {agora['ndcg_at_3']} (cai > 2 pontos)")
        if (
            agora["zero_result_rate"] is None
            or round(agora["zero_result_rate"] - antes["zero_result_rate"], 6) > SUBIDA_MAXIMA_DO_ZERO_RESULT
        ):
            falhas.append(
                f"{modo}: zero-result {antes['zero_result_rate']} -> {agora['zero_result_rate']} (sobe > 1 ponto)"
            )
        asercoes = medido["asercoes"]
        for nome in ("produto_citado_inexistente", "preco_divergente"):
            if asercoes[nome] != 0:
                falhas.append(f"{modo}: {nome} = {asercoes[nome]} (tem de ser 0)")
    return falhas


def verde(relatorio: Mapping[str, Any]) -> bool:
    """Um relatorio que pode ser linha de base: os dois modos, as asercoes a zero,
    e o hibrido sem nenhuma consulta caida em lexical."""
    modos = relatorio.get("modos", {})
    return (
        set(runner.MODOS) <= set(modos)
        and all(
            modos[m]["asercoes"]["produto_citado_inexistente"] == 0
            and modos[m]["asercoes"]["preco_divergente"] == 0
            for m in runner.MODOS
        )
        and modos["hibrido"].get("caiu_em_lexical", 0) == 0
    )


def linha_de_base_de(relatorio: Mapping[str, Any], versao: str, anterior: Mapping[str, Any] | None) -> dict[str, Any]:
    """A linha de base nova, ou `ValueError` se nao se pode registar."""
    if not verde(relatorio):
        raise ValueError("so um relatorio verde se regista (os dois modos, e as asercoes a zero)")
    if anterior is not None and _versao(versao) <= _versao(str(anterior["versao"])):
        raise ValueError(f"a versao {versao} nao e maior do que a registada ({anterior['versao']})")
    _versao(versao)
    return {
        "versao": versao,
        "dataset": relatorio["dataset"],
        "fornecedor_hibrido": relatorio.get("fornecedor_hibrido"),
        "registada_de": relatorio.get("rotulo"),
        "nota": (
            "Medida com o golden_search 100% sintetico e, no modo hibrido, com o "
            "fornecedor de embeddings falso: compara regressoes, nao mede um modelo. "
            "Os alvos do Piloto (§14.2) sao propostas; os desvios estao no relatorio."
        ),
        "modos": {
            modo: {campo: bloco[campo] for campo in _CAMPOS_DO_MODO}
            for modo, bloco in relatorio["modos"].items()
        },
    }


def _ler(caminho: Path) -> dict[str, Any]:
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def main(argv: Sequence[str]) -> int:
    analisador = argparse.ArgumentParser(prog="eval_search.gate")
    sub = analisador.add_subparsers(dest="comando", required=True)
    v = sub.add_parser("verificar")
    v.add_argument("relatorio", type=Path)
    v.add_argument("--linha-de-base", type=Path, default=LINHA_DE_BASE)
    r = sub.add_parser("registar")
    r.add_argument("relatorio", type=Path)
    r.add_argument("--versao", required=True)
    r.add_argument("--linha-de-base", type=Path, default=LINHA_DE_BASE)
    argumentos = analisador.parse_args(list(argv))
    relatorio = _ler(argumentos.relatorio)
    if argumentos.comando == "verificar":
        falhas = verificar(relatorio, _ler(argumentos.linha_de_base))
        for falha in falhas:
            print(f"gate golden_search: {falha}", file=sys.stderr)
        print(f"gate golden_search: {'verde' if not falhas else f'{len(falhas)} falha(s)'}")
        return 0 if not falhas else 1
    destino: Path = argumentos.linha_de_base
    anterior = _ler(destino) if destino.is_file() else None
    try:
        nova = linha_de_base_de(relatorio, argumentos.versao, anterior)
    except ValueError as erro:
        print(f"gate golden_search: {erro}", file=sys.stderr)
        return 1
    destino.write_text(json.dumps(nova, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"gate golden_search: linha de base {argumentos.versao} registada")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
