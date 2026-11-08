"""O proximo lote: N tickets que podem correr em paralelo sem se serializarem na fusao.

    python .claude/skills/software-factory/scripts/lote.py -n 5 --ocupados KAM-060,KAM-086

**«Um ticket por epic» nao evita colisoes.** Medido a 2026-11-08: cinco tickets em
cinco epics colidiram nas tres superficies do `superficies.py`, que atravessam os
epics, e fundiram um de cada vez. Este guiao escolhe pelas superficies:

1. **candidatos** — os da vaga 1 do `vagas.py`, lidos da `publico/main`;
2. **fora** os reclamados: titulo de PR aberto, ramo empurrado (`ls-remote`) e o
   `--ocupados`, que e onde entram as sessoes a correr — a lista de sessoes e um
   instrumento da aplicacao, e este guiao nao a ve (SKILL §0);
3. **a ler, e nao a escolher**, os que tem *commit* na `main` com o ID no assunto:
   a seccao de verificacao e o *commit* falham em direccoes opostas (o KAM-137
   estava fundido sem seccao, o KAM-051 tinha *commit* «sem entregar o ticket»), e
   quem decide e o assunto, que se le;
4. **no maximo uma migracao prevista** no lote, e zero se ja houver um PR aberto
   com revisao nova — a cadeia do alembic so aguenta uma por fundir.

**A previsao de migracao e INDICIO, e mede-se.** O texto do bloco (antes da seccao
de verificacao) que fala de `RLS` ou de `trigger`: dentro da amostra em que o
padrao foi escolhido (PRs #119 a #159) apanhou 8 de 9 migracoes, com 3 alarmes
falsos em 31; **fora dela** (PRs #58 a #118) apanhou 6 de 8, com 11 em 50. Falha
uma em quatro, e por isso a regra do *briefing* continua — «se precisares de esquema
novo, para e diz-me» — e o `fila.py` apanha o resto na fusao. O dicionario **nao**
entra no limite: o mesmo texto so previa 9 das 19 emendas fora da amostra, e as
colisoes dele custam uma renumeracao, que o `fila.py` da.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fonte  # noqa: E402
import superficies as sup  # noqa: E402
import vagas  # noqa: E402

PREVE_MIGRACAO = re.compile(r"\bRLS\b|\btrigger")
ORDEM_DE_PRIORIDADE = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
ORDEM_DE_ESTIMATIVA = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}


@dataclass
class Candidato:
    ticket: str
    dados: dict
    migracao: bool = False
    componentes: set[str] = field(default_factory=set)
    assuntos: list[str] = field(default_factory=list)
    motivo: str = ""

    def chave(self) -> tuple:
        d = self.dados
        return (ORDEM_DE_PRIORIDADE.get(d["prioridade"], 9), str(d["fase"]),
                ORDEM_DE_ESTIMATIVA.get(d["estimativa"], 9), self.ticket)


def antes_da_verificacao(bloco: str) -> str:
    """O texto do ticket sem a seccao de verificacao, que nomeia ficheiros que mudaram."""
    corte = bloco.find("### Verificação dos Critérios")
    return bloco[:corte] if corte >= 0 else bloco


def componentes_de(texto: str) -> set[str]:
    """Os componentes que o bloco nomeia: `services/x`, `packages/x`, `libs/x`, `tools/x`, `db`."""
    achados = set(re.findall(r"\b((?:services|packages|libs|tools)/[a-z0-9_-]+)", texto))
    if re.search(r"\bdb/", texto):
        achados.add("db")
    return achados


def prever(ticket: str, dados: dict, bloco: str | None) -> Candidato:
    texto = antes_da_verificacao(bloco or "")
    return Candidato(ticket, dados, migracao=bool(PREVE_MIGRACAO.search(texto)),
                     componentes=componentes_de(texto))


def escolher(candidatos: list[Candidato], n: int, migracoes_abertas: int) -> tuple[list[Candidato], list[Candidato]]:
    """Guloso pela prioridade, com o limite de uma migracao por fundir.

    Devolve `(lote, preteridos)`. Um preterido leva o motivo — o limite que o tirou —,
    para que quem le saiba que nao foi esquecido.
    """
    lote: list[Candidato] = []
    preteridos: list[Candidato] = []
    vaga_de_migracao = 1 - migracoes_abertas
    ocupados: set[str] = set()
    for c in sorted(candidatos, key=Candidato.chave):
        if len(lote) >= n:
            break
        if c.migracao and vaga_de_migracao <= 0:
            c.motivo = ("preve migracao, e a vaga esta tomada"
                        + (" por um PR aberto" if migracoes_abertas else " no lote"))
            preteridos.append(c)
            continue
        partilhados = c.componentes & ocupados
        if partilhados:
            c.motivo = f"partilha {', '.join(sorted(partilhados))} com o lote"
            preteridos.append(c)
            continue
        if c.migracao:
            vaga_de_migracao -= 1
        ocupados |= c.componentes
        lote.append(c)
    return lote, preteridos


# --- leitura da origem --------------------------------------------------------

def reclamados() -> tuple[set[str], int, list[str]]:
    """`(tickets com PR ou ramo, PRs abertos com revisao nova, linhas para o relatorio)`."""
    _, saida = fonte.correr("gh", "pr", "list", "--repo", fonte.REPO, "--state", "open",
                            "--json", "number,title,files")
    tickets: set[str] = set()
    migracoes = 0
    linhas: list[str] = []
    for pr in json.loads(saida):
        tickets |= set(re.findall(r"KAM-\d{3}", pr["title"]))
        revisoes = [f["path"] for f in pr["files"] if sup.numero_de_revisao(f["path"])]
        if revisoes:
            migracoes += 1
            linhas.append(f"#{pr['number']} tem revisao nova: {', '.join(revisoes)}")
    ramos = fonte.git("ls-remote", "--heads", fonte.REMOTO)
    tickets |= set(re.findall(r"KAM-\d{3}", ramos))
    return tickets, migracoes, linhas


def assuntos(ticket: str) -> list[str]:
    """Os *commits* da `main` com o ID **no assunto**.

    O `--grep` casa o corpo tambem, e um corpo cita tickets vizinhos: a primeira
    versao pos o KAM-033 «a ler» por um *commit* do KAM-032 que o nomeava no corpo.
    """
    saida = fonte.git("log", fonte.BASE, "-E", f"--grep={ticket}([^0-9]|$)",
                      "--format=%h %s")
    no_assunto = re.compile(rf"\b{ticket}\b")
    return [linha for linha in saida.splitlines()
            if linha and no_assunto.search(linha.split(" ", 1)[1])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=5, help="tamanho do lote")
    parser.add_argument("--ocupados", default="",
                        help="KAM-NNN separados por virgula: as sessoes a correr")
    parser.add_argument("--sem-fetch", action="store_true")
    args = parser.parse_args(argv)
    if not args.sem_fetch:
        fonte.actualizar_base()
    leitor = fonte.Arvore(fonte.BASE)
    tickets = vagas.backlog(leitor)
    feitos = vagas.fechados(leitor) & set(tickets)
    blocos = vagas.blocos(leitor)
    prontos = sorted(t for t in set(tickets) - feitos if tickets[t]["dependencias"] <= feitos)

    tomados, migracoes_abertas, notas = reclamados()
    tomados |= set(re.findall(r"KAM-\d{3}", args.ocupados))

    candidatos: list[Candidato] = []
    a_ler: list[Candidato] = []
    fora: list[str] = []
    for t in prontos:
        if t in tomados:
            fora.append(t)
            continue
        c = prever(t, tickets[t], blocos.get(t))
        c.assuntos = assuntos(t)
        (a_ler if c.assuntos else candidatos).append(c)

    lote, preteridos = escolher(candidatos, args.n, migracoes_abertas)

    print(f"base {fonte.git('rev-parse', '--short', fonte.BASE).strip()} — "
          f"{len(prontos)} prontos, {len(fora)} reclamados, {len(a_ler)} a ler, "
          f"{len(candidatos)} candidatos")
    for nota in notas:
        print(f"  {nota}")
    print(f"\nLOTE ({len(lote)}):")
    for c in lote:
        d = c.dados
        marca = "  MIGRACAO prevista: leva a vaga" if c.migracao else ""
        print(f"  {c.ticket}  {d['prioridade']} fase {d['fase']} {d['estimativa']:<2} "
              f"{d['titulo'][:60]}{marca}")
    if preteridos:
        print("\nPRETERIDOS (pelo limite, nao pela prioridade):")
        for c in preteridos:
            print(f"  {c.ticket}  {c.motivo}")
    if a_ler:
        print("\nA LER ANTES DE ESCOLHER — ja ha commit na main com o ID no assunto:")
        for c in a_ler:
            print(f"  {c.ticket}  {c.dados['titulo'][:60]}")
            for assunto in c.assuntos[:3]:
                print(f"      {assunto[:100]}")
    if fora:
        print(f"\nRECLAMADOS: {' '.join(fora)}")
    print("\nNo briefing de cada um: «se precisares de esquema novo e nao levas a vaga, "
          "para e diz-me». A previsao falha uma migracao em quatro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
