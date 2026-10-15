"""Tickets que podem arrancar agora, e as vagas seguintes, pelo backlog mestre.

    python .claude/skills/agentic-engineering/scripts/vagas.py

Um ticket conta como **fechado** quando o seu bloco no epic tem a seccao
`### Verificacao dos Criterios de Aceitacao` — que so se escreve no PR que o
entrega. Um ticket esta **pronto** quando todas as suas dependencias estao
fechadas. So le; nao altera nada.

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


def fechados() -> set[str]:
    resultado: set[str] = set()
    for epic in sorted(SPECS.glob("EPIC-*.md")):
        actual = None
        for linha in epic.read_text(encoding="utf-8").splitlines():
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
