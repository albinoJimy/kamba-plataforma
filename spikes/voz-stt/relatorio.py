"""As tabelas do `H7_Voz_STT.md` a partir das medições (KAM-107).

    python relatorio.py --manifesto M.csv R1.jsonl [R2.jsonl ...] > tabelas.md

Escreve em Markdown as secções 4 a 6 do relatório — corpus, resultados por STT,
custo — e a avaliação contra os limiares, mais a **indicação mecânica** do ramo
da regra de decisão. **A decisão não é esta**: tem dono e data, e escreve-a uma
pessoa no §7 do relatório. O *script* diz o que a regra dá com os números; quem
decide pode ter razões que a regra não vê, e se as tiver escreve-as.

Duas guardas, as dos «Testes Requeridos» do bloco, e as duas recusam em vez de
avisar:

1. **Os limiares estão datados antes da primeira medição.** O
   `limiares.json` tem `registado_em`, e tem de ser um dia **anterior** ao da
   primeira execução registada (UTC). O limiar de confiança tem data própria,
   porque se fixa depois dos outros. A prova forte é o histórico do `git`, que
   este *script* não lê; esta é a que se verifica sem ele.
2. **O texto que sai não contém áudio nem identificação de falantes**: nenhum
   pseudónimo `F00`, nenhum `clip_id`, nenhum nome de ficheiro de áudio, nenhuma
   sequência longa de algarismos nem bloco com forma de base64. As hipóteses e as
   referências **nunca** entram no relatório — só contagens e proporções.

Leituras propostas, escritas no `H7_Voz_STT.md` §2: o WER usa a **primeira**
execução de cada clip por fornecedor, e uma execução falhada conta como hipótese
vazia (todas as palavras omitidas) — um STT que não responde não transcreveu bem.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

import custo
import latencia
from harness import DentroDoRepositorio, exigir_fora_do_repositorio
from manifesto import Clip, Enunciado, grupos, ler, ler_roteiro, verificar
from wer import Agregado, agregar, alinhar

AQUI = Path(__file__).resolve().parent
LIMIARES = AQUI / "limiares.json"
GRUPOS = ("global", "numeros", "linguas", "ruidoso", "silencioso")

_PROIBIDO = (
    ("pseudónimo de falante", re.compile(r"\bF\d{2}\b")),
    ("identificador de clip", re.compile(r"\bC\d{4}\b")),
    ("ficheiro de áudio", re.compile(r"\.(?:ogg|opus|oga|wav|mp3|m4a|aac|flac)\b", re.I)),
    ("sequência longa de algarismos", re.compile(r"\d{9,}")),
    ("bloco com forma de base64", re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")),
)


class RelatorioRecusado(ValueError):
    pass


def exigir_sem_identificacao(texto: str) -> None:
    achados = [nome for nome, padrao in _PROIBIDO if padrao.search(texto)]
    if achados:
        raise RelatorioRecusado("o relatório levaria " + ", ".join(achados))


def exigir_limiares_antes(limiares: Mapping, resultados: Iterable[Mapping]) -> date:
    datas = [datetime.fromisoformat(r["inicio_utc"]).date() for r in resultados]
    if not datas:
        raise RelatorioRecusado("sem medições")
    primeira = min(datas)
    registado = limiares.get("registado_em")
    if not isinstance(registado, str) or date.fromisoformat(registado) >= primeira:
        raise RelatorioRecusado(f"limiares registados a {registado}, não antes da primeira medição ({primeira})")
    conf = limiares.get("confianca", {})
    if any(v is not None for v in conf.get("limiar", {}).values()):
        r = conf.get("registado_em")
        if not isinstance(r, str) or date.fromisoformat(r) >= primeira:
            raise RelatorioRecusado(f"limiar de confiança registado a {r}, não antes da primeira medição ({primeira})")
    return primeira


def pct(x: float | None, casas: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{casas}f}%".replace(".", ",")


def ms(x: float | None) -> str:
    return "—" if x is None else f"{x / 1000:.2f} s".replace(".", ",")


def _primeiras(resultados: Iterable[Mapping], fornecedor: str) -> dict[str, Mapping]:
    primeira: dict[str, Mapping] = {}
    for r in sorted(resultados, key=lambda r: r["inicio_utc"]):
        if r["fornecedor"] == fornecedor and r["tipo"] == "enunciado":
            primeira.setdefault(r["clip_id"], r)
    return primeira


def wer_por_grupo(
    clips: list[Clip], roteiro: Mapping[str, Enunciado], resultados: list[Mapping], fornecedor: str
) -> tuple[dict[str, Agregado], dict[str, float], int]:
    """Agregados por grupo, a WER de cada clip medido, e os clips sem execução."""
    primeiras = _primeiras(resultados, fornecedor)
    por_grupo: dict[str, list] = {g: [] for g in GRUPOS}
    wer_clip: dict[str, float] = {}
    sem = 0
    for c in clips:
        if c.tipo != "enunciado":
            continue
        r = primeiras.get(c.clip_id)
        if r is None:
            sem += 1
            continue
        a = alinhar(c.ref, r["hipotese"] if r["estado"] == "ok" else "")
        wer_clip[c.clip_id] = a.wer
        for g in grupos(c, roteiro):
            por_grupo[g].append(a)
    return {g: agregar(v) for g, v in por_grupo.items()}, wer_clip, sem


def avaliar_confianca(
    resultados: list[Mapping], wer_clip: Mapping[str, float], fornecedor: str, limiares: Mapping
) -> tuple[str, Decimal | None, str]:
    """(há sinal S/N, fracção assinalada ou `None`, o texto para a tabela).

    A fracção é dos enunciados com WER acima do corte que o sinal assinala — os
    que têm confiança abaixo do limiar do fornecedor. Sem sinal, a fracção é
    `None` e o limiar fica «não medido»: um sinal que não existe não assinala
    nada, mas também não se mediu a falhar.
    """
    primeiras = _primeiras(resultados, fornecedor)
    ok = [r for r in primeiras.values() if r["estado"] == "ok"]
    if not ok:
        return "não medido", None, "não medido"
    sinal = "S" if any(r.get("confianca") is not None for r in ok) else "N"
    conf = limiares["confianca"]
    limiar = conf["limiar"].get(fornecedor)
    if sinal == "N":
        return sinal, None, "não aplicável (a API não devolveu sinal)"
    if limiar is None:
        return sinal, None, "por calcular: limiar de confiança por fixar"
    alto = Decimal(conf["wer_alto"])
    altos = [r for r in ok if r["clip_id"] in wer_clip and Decimal(str(wer_clip[r["clip_id"]])) > alto]
    if not altos:
        return sinal, None, "não medido (nenhum enunciado com WER acima do corte)"
    corte = Decimal(str(limiar))  # o limiares.json escreve números como texto
    assinalados = sum(1 for r in altos if r.get("confianca") is not None and Decimal(str(r["confianca"])) < corte)
    frac = Decimal(assinalados) / Decimal(len(altos))
    return sinal, frac, f"{pct(float(frac))} ({assinalados} de {len(altos)})"


def estado_do_fornecedor(
    ag: Agregado, linhas_lat: list[latencia.Linha], conf_frac: Decimal | None, sem: int, limiares: Mapping
) -> dict[str, str]:
    """`passa`, `falha` ou `não medido` por limiar."""
    est: dict[str, str] = {}
    if sem or ag.wer is None:
        est["wer"] = "não medido"
    else:
        est["wer"] = "passa" if Decimal(str(ag.wer)) <= Decimal(limiares["wer_global_max"]) else "falha"
    if sem or ag.precisao_numerica is None:
        est["numeros"] = "não medido"
    else:
        est["numeros"] = (
            "passa" if Decimal(str(ag.precisao_numerica)) >= Decimal(limiares["precisao_numerica_min"]) else "falha"
        )
    tecto_ms = Decimal(limiares["latencia_p95_max_s"]) * 1000
    if any(l.faltas or l.p95_ms is None for l in linhas_lat):
        est["latencia"] = "não medido"
    else:
        est["latencia"] = "passa" if all(Decimal(str(l.p95_ms)) <= tecto_ms for l in linhas_lat) else "falha"
    if conf_frac is None:
        est["confianca"] = "não medido"
    else:
        est["confianca"] = "passa" if conf_frac >= Decimal(limiares["confianca"]["assinala_min"]) else "falha"
    return est


def ramo_da_regra(estados: Mapping[str, Mapping[str, str]], custo_hora: Mapping[str, Decimal]) -> str:
    """A regra de decisão do bloco, aplicada mecanicamente. Não é a decisão."""
    if any("não medido" in e.values() for e in estados.values()):
        return "não aplicável: há limiares não medidos"
    passam = [f for f, e in estados.items() if all(v == "passa" for v in e.values())]
    if len(passam) >= 2:
        primario = min(passam, key=lambda f: custo_hora[f])
        outros = ", ".join(f for f in passam if f != primario)
        return f"ambos passam: {primario} primário (menor custo medido), {outros} fallback"
    if len(passam) == 1:
        return f"só um passa: {passam[0]} primário"
    so_numeros = [
        f for f, e in estados.items() if e["numeros"] == "falha" and all(v == "passa" for k, v in e.items() if k != "numeros")
    ]
    if so_numeros:
        return "falha apenas nos números (" + ", ".join(so_numeros) + "): voz activa só com eco e confirmação dos números"
    return "nenhum passa: voz só em handoff a humano no Piloto, e sai da promessa comercial"


def gerar(clips: list[Clip], resultados: list[Mapping], limiares: Mapping, precos: custo.Tabela, roteiro) -> str:
    primeira = exigir_limiares_antes(limiares, resultados)
    fornecedores = sorted({r["fornecedor"] for r in resultados})
    enunciados = [c for c in clips if c.tipo == "enunciado"]
    s: list[str] = []
    s.append(f"<!-- gerado por spikes/voz-stt/relatorio.py; regras de normalização v{limiares['regras_normalizacao']}; "
             f"primeira medição {primeira}; limiares de {limiares['registado_em']} -->")
    s.append("")
    s.append("### Corpus")
    s.append("")
    achados = verificar(clips, roteiro)
    n = len(enunciados)
    cont = {g: sum(1 for c in enunciados if g in grupos(c, roteiro)) for g in ("numeros", "linguas", "ruidoso")}
    s.append("| Falantes | Enunciados | Com números | Com línguas nacionais ou mistura | Em ruído | Achados do manifesto |")
    s.append("|---|---|---|---|---|---|")
    s.append(
        f"| {len({c.falante_id for c in enunciados})} | {n} | {cont['numeros']} ({pct(cont['numeros'] / n if n else None)}) "
        f"| {cont['linguas']} ({pct(cont['linguas'] / n if n else None)}) | {cont['ruidoso']} ({pct(cont['ruidoso'] / n if n else None)}) "
        f"| {len(achados)} |"
    )
    estados: dict[str, dict[str, str]] = {}
    custo_hora: dict[str, Decimal] = {}
    duracoes = [c.duracao_s for c in enunciados]
    for f in fornecedores:
        ags, wer_clip, sem = wer_por_grupo(clips, roteiro, resultados, f)
        lat = latencia.resumir(resultados, f)
        fal = latencia.falhas(resultados, f)
        sinal, conf_frac, conf_txt = avaliar_confianca(resultados, wer_clip, f, limiares)
        estados[f] = estado_do_fornecedor(ags["global"], lat, conf_frac, sem, limiares)
        s += ["", f"### {f}", ""]
        s.append(f"Enunciados sem execução: **{sem}**. Taxa de erro ou *timeout*: **{pct(fal.taxa)}** "
                 f"({fal.erros} erros e {fal.timeouts} *timeouts* em {fal.execucoes} execuções).")
        s += ["", "| Grupo | Clips | Palavras | WER |", "|---|---|---|---|"]
        for g in GRUPOS:
            a = ags[g]
            s.append(f"| {g} | {a.clips} | {a.palavras} | {pct(a.wer)} |")
        g = ags["global"]
        s += ["", "| Precisão numérica | Números na referência | Certos | Inventados pela hipótese |", "|---|---|---|---|"]
        s.append(f"| {pct(g.precisao_numerica)} | {g.numericos} | {g.numericos_certos} | {g.insercoes_numericas} |")
        s += ["", "| Tamanho | Execuções | Manhã / tarde / noite | Erros | *Timeouts* | p50 | p95 | Falta |",
              "|---|---|---|---|---|---|---|---|"]
        for l in lat:
            mom = " / ".join(str(l.por_momento[m]) for m, _, _ in latencia.MOMENTOS)
            s.append(f"| {l.tamanho_s} s | {l.execucoes} | {mom} | {l.erros} | {l.timeouts} | {ms(l.p50_ms)} "
                     f"| {ms(l.p95_ms)} | {'; '.join(l.faltas) or '—'} |")
        s += ["", f"Sinal de confiança devolvido pela API: **{sinal}**. Enunciados com WER acima do corte que o sinal assinala: **{conf_txt}**."]
        preco = precos.precos.get(f)
        if preco is not None and duracoes:
            custo_hora[f] = custo.por_hora(preco, duracoes)
            est = custo.ESTIMATIVA_DOC09_USD.get(f)
            s += ["", "| Preço (lido em) | USD por hora de áudio | USD por PME/mês (300 min) | Estimativa do doc 09 §14.3 |",
                  "|---|---|---|---|"]
            s.append(f"| {preco.modelo}, {preco.estado}; mínimo {preco.minimo_s} s ({preco.minimo_estado}); lido em {precos.lido_em} "
                     f"| {custo.usd(custo_hora[f])} | {custo.usd(custo.por_pme_mes(preco, duracoes))} "
                     f"| {'—' if est is None else custo.usd(est)} |")
    s += ["", "### Limiares", "", "| Limiar (proposta) | " + " | ".join(fornecedores) + " |",
          "|---|" + "---|" * len(fornecedores)]
    for chave, rotulo in (
        ("wer", f"WER global ≤ {pct(float(limiares['wer_global_max']), 0)}"),
        ("numeros", f"Precisão numérica ≥ {pct(float(limiares['precisao_numerica_min']), 0)}"),
        ("latencia", f"Latência p95 ≤ {limiares['latencia_p95_max_s']} s nos três tamanhos"),
        ("confianca", f"Sinal assinala ≥ {pct(float(limiares['confianca']['assinala_min']), 0)} dos enunciados com WER > "
                      f"{pct(float(limiares['confianca']['wer_alto']), 0)}"),
    ):
        s.append(f"| {rotulo} | " + " | ".join(estados[f][chave] for f in fornecedores) + " |")
    s += ["", f"**Indicação mecânica da regra de decisão** (não é a decisão; ver §7): {ramo_da_regra(estados, custo_hora)}."]
    texto = "\n".join(s) + "\n"
    exigir_sem_identificacao(texto)
    return texto


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="relatorio.py")
    p.add_argument("--manifesto", required=True, type=Path)
    p.add_argument("--limiares", type=Path, default=LIMIARES)
    p.add_argument("--precos", type=Path, default=custo.PRECOS)
    p.add_argument("resultados", nargs="+", type=Path)
    a = p.parse_args(argv)
    try:
        for caminho in (a.manifesto, *a.resultados):
            exigir_fora_do_repositorio(caminho)
        texto = gerar(
            ler(a.manifesto),
            latencia.ler_resultados(a.resultados),
            json.loads(a.limiares.read_text(encoding="utf-8")),
            custo.ler_precos(a.precos),
            ler_roteiro(),
        )
    except (RelatorioRecusado, DentroDoRepositorio) as exc:
        print(f"recusado: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
