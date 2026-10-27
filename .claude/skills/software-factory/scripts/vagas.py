"""Tickets que podem arrancar agora, e as vagas seguintes, pelo backlog mestre.

    python .claude/skills/software-factory/scripts/vagas.py

Um ticket conta como **fechado** quando o seu bloco tem a seccao
`### Verificacao dos Criterios de Aceitacao` — que so se escreve no PR que o
entrega. Um ticket esta **pronto** quando todas as suas dependencias estao
fechadas. So le; nao altera nada.

**Os blocos vivem em dois sitios**, porque o repositorio tem duas convencoes em
simultaneo (KAM-155): dentro do `specs/EPIC-*.md` nos dez epics que mantiveram
os blocos, e num ficheiro por ticket em `specs/tickets/KAM-NNN.md` no EPIC-01.
Varrer so um dos dois faz este guiao **responder errado com cara de certa**:
sem `specs/tickets/`, os 27 tickets fechados do EPIC-01 contam como abertos e
aparecem na vaga 1 como «PRONTOS AGORA», com codigo de saida 0 e sem aviso. E a
classe de defeito que o KAM-136 e o KAM-148 existem para fechar — ler mal sem o
dizer — e foi a revisao adversarial do KAM-155 que a apanhou aqui.

O resultado e a lista de *candidatos*: a lista de «Paralelismo» da skill
aplica-se depois (dois tickets que definam o mesmo nome nao correm juntos, e
os que acrescentam revisoes de base de dados entram em serie).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
SPECS = RAIZ / "specs"

# Os titulos do backlog trazem `↔`, `→` e `—`, que uma consola cp1252 (o Windows
# por omissao) nao sabe codificar: sem isto, o guiao morre com
# `UnicodeEncodeError` **a meio da vaga 1**, depois de ja ter impresso parte da
# lista, e devolve 1. Defeito pre-existente, medido igual em `origin/main`;
# corrige-se aqui porque a evidencia do KAM-155 precisa de o correr ate ao fim.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def backlog() -> dict[str, dict]:
    texto = (SPECS / "INDICE.md").read_text(encoding="utf-8")
    seccao = texto[texto.index("\n## 4."):]
    tickets: dict[str, dict] = {}
    for linha in seccao.splitlines():
        if not linha.startswith("| KAM-"):
            continue
        campos = [campo.strip() for campo in linha.split("|")[1:-1]]
        if len(campos) < 7:
            continue
        tickets[campos[0]] = {
            "titulo": campos[1], "tipo": campos[2], "estimativa": campos[3],
            "prioridade": campos[4], "fase": campos[5],
            "dependencias": set(re.findall(r"KAM-[0-9]{3}", campos[6])),
        }
    return tickets


def fontes_de_blocos() -> list[Path]:
    """Os ficheiros onde vivem blocos `## KAM-NNN`, nas duas convencoes.

    Levanta se nenhuma das duas fontes existir: um conjunto vazio faria **todos**
    os tickets contar como abertos, e o guiao anunciaria o backlog inteiro como
    pronto — exactamente o modo de falha silencioso que isto evita.
    """
    fontes = sorted(SPECS.glob("EPIC-*.md")) + sorted((SPECS / "tickets").glob("*.md"))
    if not fontes:
        raise SystemExit(
            f"nao encontrei blocos de ticket: nem {SPECS}/EPIC-*.md nem "
            f"{SPECS}/tickets/*.md existem"
        )
    return fontes


def fechados() -> set[str]:
    resultado: set[str] = set()
    for fonte in fontes_de_blocos():
        actual = None
        for linha in fonte.read_text(encoding="utf-8").splitlines():
            bloco = re.match(r"## (KAM-[0-9]{3}) ", linha)
            if bloco:
                actual = bloco.group(1)
            elif actual and linha.startswith("### Verificação dos Critérios de Aceitação"):
                resultado.add(actual)
    return resultado


def main() -> int:
    tickets = backlog()
    if not tickets:
        print("nao encontrei tickets em specs/INDICE.md §4", file=sys.stderr)
        return 2
    feitos = fechados() & set(tickets)
    orfas = {d for t in tickets.values() for d in t["dependencias"]} - set(tickets)
    if orfas:
        print(f"dependencias que nao existem no backlog: {sorted(orfas)}", file=sys.stderr)
        return 2
    print(f"{len(tickets)} tickets, {len(feitos)} fechados: {' '.join(sorted(feitos))}")
    resto = set(tickets) - feitos
    concluidos = set(feitos)
    vaga = 0
    while resto:
        prontos = sorted(t for t in resto if tickets[t]["dependencias"] <= concluidos)
        if not prontos:
            print(f"ciclo ou bloqueio: {len(resto)} tickets sem vaga possivel", file=sys.stderr)
            return 1
        vaga += 1
        print(f"\nvaga {vaga} — {len(prontos)} ticket(s)" + (" — PRONTOS AGORA" if vaga == 1 else ""))
        if vaga == 1:
            for t in prontos:
                d = tickets[t]
                print(f"  {t}  {d['prioridade']}  fase {d['fase']}  {d['estimativa']:<2} {d['tipo']:<8} {d['titulo'][:70]}")
        else:
            print("  " + " ".join(prontos))
        concluidos |= set(prontos)
        resto -= set(prontos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
