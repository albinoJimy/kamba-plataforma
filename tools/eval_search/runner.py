"""O executor do `golden_search` e o relatorio (KAM-064, criterios 5, 7 e 8).

O executor **nao sabe pesquisar**: recebe um `Pesquisador`, que e quem chama a
pesquisa real. O que liga isto ao PostgreSQL e ao `kamba_core.idx.pesquisa.
procurar` e o `db/golden_search.py`, que corre no contentor do *gate* 8, como o
`db/desempenho_indice.py`. Separados porque o que se mede aqui (as metricas, o
relatorio, as asercoes deterministicas) corre em milissegundos sem base, e a
descoberta do *gate* 4 corre-o em cada PR.

## As duas asercoes deterministicas (criterio 8)

Cada linha que a pesquisa devolve confere-se com o *snapshot* do catalogo que se
semeou:

* **produto citado inexistente** — um `product_ref` que nao esta no catalogo do
  tenant da consulta (de outro tenant, ou inventado);
* **preco divergente** — um `preco_minor` diferente do semeado: o numero nao
  veio da oferta viva.

As duas tem de dar **zero**, em todas as consultas e nas `adversarial` a parte;
o relatorio conta-as, e o `gate` recusa um relatorio que nao de zero. O stock
nao se confere: a resposta diz `disponivel = None` enquanto nao houver nivel de
stock (KAM-045, D3), e conferir o «nao sei» e conferir nada.
"""

from __future__ import annotations

import json
import platform
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from . import dataset as dataset_mod
from . import metrics

#: Quantas linhas o executor pede a pesquisa: as dez do `recall@10`. As tres
#: primeiras sao as da resposta (`LIMIT 3` do §6.3), porque a ordem e total.
PROFUNDIDADE: Final = 10

MODOS: Final = ("lexical", "hibrido")

#: As metricas que entram no relatorio, pela ordem do §14.2.
METRICAS: Final = (
    "success_at_3",
    "recall_at_10",
    "ndcg_at_3",
    "success_at_3_typo_regionalismo",
    "zero_result_rate",
    "falso_positivo_nao_resolvivel",
)


@dataclass(frozen=True)
class Resposta:
    """O que a pesquisa devolveu para uma consulta.

    `linhas` sao `(linha do §6.3, o_score)`, pela ordem da pesquisa; `modo` e o
    que **correu** (um hibrido que caiu em lexical diz `lexical`).
    """

    linhas: tuple[tuple[Mapping[str, Any], float], ...]
    modo: str
    tokens_nao_resolvidos: tuple[str, ...] = ()


Pesquisador = Callable[[dataset_mod.Registo], Resposta]


@dataclass
class Execucao:
    """Uma passagem do *dataset* num modo."""

    modo: str
    resultados: list[metrics.Resultado] = field(default_factory=list)
    respostas: dict[str, Resposta] = field(default_factory=dict)
    registos: dict[str, dataset_mod.Registo] = field(default_factory=dict)
    citado_inexistente: list[str] = field(default_factory=list)
    preco_divergente: list[str] = field(default_factory=list)
    caiu_em_lexical: int = 0
    duracao_s: float = 0.0


def correr(
    registos: Sequence[dataset_mod.Registo],
    pesquisador: Pesquisador,
    catalogos: Mapping[str, Mapping[str, int | None]],
    *,
    modo: str,
    relogio: Callable[[], float] = time.perf_counter,
) -> Execucao:
    """Corre cada consulta e confere cada linha com o catalogo semeado.

    `catalogos` e `{snapshot: {product_ref: preco_minor}}`, lido dos ficheiros
    que se semearam — e nao da base, que e quem se esta a conferir.
    """
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo!r}")
    execucao = Execucao(modo)
    inicio = relogio()
    for registo in registos:
        resposta = pesquisador(registo)
        execucao.respostas[registo.qid] = resposta
        execucao.registos[registo.qid] = registo
        if modo == "hibrido" and resposta.modo != "hibrido":
            execucao.caiu_em_lexical += 1
        catalogo = catalogos[registo.catalogo]
        ordem: list[str] = []
        for linha, _score in resposta.linhas[:PROFUNDIDADE]:
            ref = str(linha["product_ref"])
            if ref not in catalogo:
                execucao.citado_inexistente.append(f"{registo.qid}:{ref}")
            elif linha.get("preco_minor") != catalogo[ref]:
                execucao.preco_divergente.append(f"{registo.qid}:{ref}")
            ordem.append(ref)
        execucao.resultados.append(
            metrics.Resultado(
                qid=registo.qid,
                catalogo=registo.catalogo,
                tags=registo.tags,
                nao_resolvivel=registo.nao_resolvivel,
                ordem=tuple(ordem),
                graus=registo.graus,
            )
        )
    execucao.duracao_s = round(relogio() - inicio, 3)
    return execucao


def _arredondar(valores: Mapping[str, float | int | None]) -> dict[str, float | int | None]:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in valores.items()}


def _fatias(execucao: Execucao) -> dict[str, dict[str, Any]]:
    resultados = execucao.resultados
    divisoes = {r.qid: execucao.registos[r.qid].divisao for r in resultados}
    saida: dict[str, dict[str, Any]] = {
        "global": _arredondar(metrics.agregar(resultados)),
        "por_divisao": {
            divisao: _arredondar(metrics.agregar([r for r in resultados if divisoes[r.qid] == divisao]))
            for divisao in (dataset_mod.DEV, dataset_mod.TESTE)
        },
        "por_catalogo": {
            catalogo: _arredondar(metrics.agregar([r for r in resultados if r.catalogo == catalogo]))
            for catalogo in sorted({r.catalogo for r in resultados})
        },
    }
    return saida


def _alvos(globais: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    saida = {}
    for nome, (sentido, alvo) in metrics.ALVOS_DO_PILOTO.items():
        valor = globais.get(nome)
        saida[nome] = {
            "alvo": f"{sentido} {alvo}",
            "medido": valor,
            "cumpre": metrics.cumpre(nome, valor),
            "desvio": None if valor is None else round(valor - alvo, 4),
        }
    return saida


def _adversarial(execucao: Execucao) -> dict[str, int]:
    adversariais = {qid for qid, r in execucao.registos.items() if "adversarial" in r.tags}

    def conta(achados: Sequence[str]) -> int:
        return sum(a.split(":", 1)[0] in adversariais for a in achados)

    return {
        "consultas": len(adversariais),
        "produto_citado_inexistente": conta(execucao.citado_inexistente),
        "preco_divergente": conta(execucao.preco_divergente),
    }


def tokens_nao_resolvidos(execucao: Execucao, *, minimo: int = 1) -> list[dict[str, Any]]:
    """Os *tokens* que a normalizacao nao resolveu, agregados pelo *dataset*.

    E o relatorio do criterio 8 do KAM-062 **sobre o dataset sintetico**: conta
    consultas, nao sujeitos — o *dataset* nao tem sujeitos. A versao de producao
    (>= 5 sujeitos distintos) espera pela decisao de privacidade do fundador.
    """
    contagem: Counter[str] = Counter()
    for resposta in execucao.respostas.values():
        contagem.update(set(resposta.tokens_nao_resolvidos))
    return [
        {"token": token, "consultas": n}
        for token, n in sorted(contagem.items(), key=lambda par: (-par[1], par[0]))
        if n >= minimo
    ]


def relatorio(
    execucoes: Mapping[str, Execucao],
    *,
    contexto: Mapping[str, Any],
) -> dict[str, Any]:
    """O relatorio JSON de uma execucao: metricas por modo, divisao e catalogo."""
    modos: dict[str, Any] = {}
    for modo, execucao in execucoes.items():
        fatias = _fatias(execucao)
        modos[modo] = {
            **fatias,
            "alvos_do_piloto": _alvos(fatias["global"]),
            "asercoes": {
                "produto_citado_inexistente": len(execucao.citado_inexistente),
                "preco_divergente": len(execucao.preco_divergente),
                "exemplos": (execucao.citado_inexistente + execucao.preco_divergente)[:10],
                "adversarial": _adversarial(execucao),
            },
            "caiu_em_lexical": execucao.caiu_em_lexical,
            "duracao_s": execucao.duracao_s,
            "tokens_nao_resolvidos": tokens_nao_resolvidos(execucao, minimo=2)[:30],
        }
    comparacao: dict[str, Any] = {}
    if set(MODOS) <= set(execucoes):
        lex, hib = modos["lexical"]["global"], modos["hibrido"]["global"]
        comparacao = {
            nome: None if lex[nome] is None or hib[nome] is None else round(hib[nome] - lex[nome], 4)
            for nome in METRICAS
        }
    return {
        "ticket": "KAM-064",
        **contexto,
        "modos": modos,
        "hibrido_menos_lexical": comparacao,
        "ambiente": {
            "sistema": platform.platform(),
            "python": platform.python_version(),
        },
    }


def varrer_limiar(
    execucao: Execucao,
    limiares: Sequence[float],
    pontuador: Callable[[float], float],
) -> list[dict[str, Any]]:
    """As metricas da resposta (top 3) com o corte `pontuador(score) >= limiar`.

    E a calibracao do par (pontuador, limiar) do `retrieve` do AGR (KAM-061): o
    `pontuador` e o `score_normalizado` de `kamba_agr.tls.idx`, passado por quem
    chama, porque este modulo nao importa o AGR.
    """
    saida = []
    for limiar in limiares:
        cortados = []
        for resultado in execucao.resultados:
            resposta = execucao.respostas[resultado.qid]
            mantidos = tuple(
                str(linha["product_ref"])
                for linha, score in resposta.linhas[:3]
                if pontuador(score) >= limiar
            )
            cortados.append(
                metrics.Resultado(
                    resultado.qid, resultado.catalogo, resultado.tags,
                    resultado.nao_resolvivel, mantidos, resultado.graus,
                )
            )
        agregado = metrics.agregar(cortados)
        saida.append(
            {
                "limiar": limiar,
                "success_at_3": agregado["success_at_3"],
                "zero_result_rate": agregado["zero_result_rate"],
                "falso_positivo_nao_resolvivel": agregado["falso_positivo_nao_resolvivel"],
            }
        )
    return [_arredondar(linha) for linha in saida]


def _celula(valor: Any) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor:.3f}"
    return str(valor)


def markdown(dados: Mapping[str, Any]) -> str:
    """O relatorio em Markdown, a partir do JSON (e so dele)."""
    linhas = [
        f"# Relatório do golden_search — {dados.get('rotulo', '')}".rstrip(" —"),
        "",
        f"Dataset `{dados.get('dataset', '?')}`, {dados.get('consultas', '?')} consultas. "
        "Os alvos são **propostas** do §14.2; um desvio explica-se, não se corrige o alvo.",
        "",
    ]
    for modo, bloco in dados["modos"].items():
        linhas += [f"## Modo {modo}", "", "| Métrica | Global | dev | teste | Alvo | Cumpre |", "|---|---|---|---|---|---|"]
        for nome in METRICAS:
            alvo = bloco["alvos_do_piloto"][nome]
            linhas.append(
                f"| {nome} | {_celula(bloco['global'][nome])} | "
                f"{_celula(bloco['por_divisao']['dev'][nome])} | "
                f"{_celula(bloco['por_divisao']['teste'][nome])} | {alvo['alvo']} | "
                f"{'sim' if alvo['cumpre'] else ('não' if alvo['cumpre'] is False else '—')} |"
            )
        linhas += ["", "| Catálogo | " + " | ".join(METRICAS) + " |", "|---" * (len(METRICAS) + 1) + "|"]
        for catalogo, valores in bloco["por_catalogo"].items():
            linhas.append(f"| {catalogo} | " + " | ".join(_celula(valores[n]) for n in METRICAS) + " |")
        asercoes = bloco["asercoes"]
        linhas += [
            "",
            f"Asserções: produto citado inexistente **{asercoes['produto_citado_inexistente']}**, "
            f"preço divergente **{asercoes['preco_divergente']}** "
            f"(adversarial: {asercoes['adversarial']['produto_citado_inexistente']} e "
            f"{asercoes['adversarial']['preco_divergente']} em {asercoes['adversarial']['consultas']} consultas). "
            f"Caiu em lexical: {bloco['caiu_em_lexical']}. Duração: {bloco['duracao_s']} s.",
            "",
        ]
    if dados.get("hibrido_menos_lexical"):
        linhas += ["## Híbrido menos lexical", "", "| Métrica | Δ |", "|---|---|"]
        linhas += [f"| {n} | {_celula(v)} |" for n, v in dados["hibrido_menos_lexical"].items()]
        linhas.append("")
    for chave in ("fornecedor_hibrido", "nota"):
        if dados.get(chave):
            linhas += [f"**{chave}:** {dados[chave]}", ""]
    return "\n".join(linhas)


def escrever(dados: Mapping[str, Any], caminho_json: Any) -> None:
    """Escreve o JSON e o Markdown lado a lado (`x.json` e `x.md`)."""
    from pathlib import Path

    destino = Path(caminho_json)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    destino.with_suffix(".md").write_text(markdown(dados), encoding="utf-8", newline="\n")
