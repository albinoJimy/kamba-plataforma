"""A fila de fecho: que PR funde agora, e o que cada um dos outros tem de tomar.

    python .claude/skills/software-factory/scripts/fila.py            # mede e diz
    python .claude/skills/software-factory/scripts/fila.py --fundir   # e funde a cabeca

**O `MERGEABLE` do GitHub nao diz que a `main` fica verde depois de fundir.** As tres
superficies do `superficies.py` sao restricoes **semanticas**: dois PRs com a mesma
`0037` fundem-se os dois sem conflito de texto e partem a cadeia; um piso certo no
ramo fica errado na arvore da fusao. Medido a 2026-11-08: o #159 estava `MERGEABLE`
com o cabecalho do dicionario atras da propria emenda, e o #158 com uma `0038`
sobre uma `0037` que a `main` nao tinha.

Por isso a fila mede, para cada PR aberto:

1. **contra a `main` de agora** — a arvore do `merge-tree`, sem tocar em nada: os
   conflitos, a cadeia do alembic, as tabelas de versoes que o PR toca (com o parser
   do gate 3c) e o piso do `lint_bloco` *daquela arvore*;
2. **pela ordem da fila** — o numero de revisao, as versoes e o piso que ele tem de
   tomar quando integrar, **contando com os que estao a frente** (a `Reserva`).

**O que um PR acrescenta mede-se da `main` a arvore da fusao**, e nao da base do
ramo: um ramo empilhado sobre outro ja fundido por *squash* tem na sua base o que a
`main` ja tem, e a primeira versao mandava-o renumerar uma revisao que ja estava na
`main` (achado da revisao adversarial). So com conflitos, onde a arvore da fusao tem
marcadores, se cai para a base do ramo — e o relatorio diz que caiu.

**A ordem e a prontidao, e depois o numero do PR:** PRONTO, PENDENTE, INTEGRAR,
RASCUNHO, VERMELHO. Pela ordem do numero, um PR vermelho a frente ficava com a emenda
do piso e o seguinte esperava por ele para sempre — medido no estado vivo, sobre o
proprio PR deste ticket.

O `--fundir` funde **so a cabeca**, so se ela estiver `PRONTO`, e so se a `main` e a
ponta forem as que se mediram (`--match-head-commit`, e o `ls-remote` da `main`).
Nunca liga o *auto-merge*.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fonte  # noqa: E402
import superficies as sup  # noqa: E402

VERSIONS = "db/migrations/versions"

#: O GitHub diz `UNSTABLE` quando so falham verificacoes nao exigidas — os dois
#: vermelhos de desenho desta casa (`gate 5 — reservado`, `vigia`). E o estado
#: fundivel. `BLOCKED` e exigido vermelho **ou pendente**; `DIRTY` e conflito.
FUNDIVEIS = {"CLEAN", "UNSTABLE", "HAS_HOOKS"}
POR_INTEGRAR = {"DIRTY", "BEHIND"}
ORDEM = {"PRONTO": 0, "PENDENTE": 1, "INTEGRAR": 2, "RASCUNHO": 3, "VERMELHO": 4}

#: Ficheiros gerados: um conflito neles nao se resolve a mao, regenera-se depois de
#: resolver a fonte. Medido a 2026-11-08 no #157: o conflito do `.yaml` vinha so do
#: `.md`, e quem o resolvesse a mao ficava com o *gate* 3b a dar verde falso se
#: corresse so o `canon_lint` (sao tres comandos).
GERADOS = {
    "canon/dicionario.yaml": "gerado do §3 do dicionario: resolve o `.md` e regenera com "
                             "`make dict-export` (ou o `dict_export.cli` sem `--check`)",
}

Medidor = Callable[[str], tuple[int, int]]


@dataclass
class PR:
    numero: int
    titulo: str
    ponta: str
    estado: str = "REPLAY"          # mergeStateStatus, ou REPLAY sem GitHub
    fundivel: str = "UNKNOWN"       # mergeable
    rascunho: bool = False
    verificacoes: dict[str, int] = field(default_factory=dict)
    vermelhas: list[str] = field(default_factory=list)

    @property
    def ticket(self) -> str:
        achado = re.search(r"KAM-\d{3}", self.titulo)
        return achado.group(0) if achado else "?"


@dataclass
class Avaliacao:
    pr: PR
    revisoes_novas: list[str]                 # caminhos de revisoes que o PR acrescenta
    emendas: dict[str, list[str]]             # ficheiro -> versoes que o PR acrescenta
    delta_medidos: int
    conflitos: list[str] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    instrucoes: list[str] = field(default_factory=list)
    depois_de: str = "main"
    pela_base_do_ramo: bool = False

    @property
    def pronto(self) -> bool:
        pr = self.pr
        github_ok = (pr.estado in FUNDIVEIS or pr.estado == "REPLAY") and not pr.rascunho
        return github_ok and not pr.vermelhas and not self.conflitos and not self.problemas

    @property
    def veredicto(self) -> str:
        pr = self.pr
        if self.pronto:
            return "PRONTO"
        if pr.vermelhas:
            return "VERMELHO"          # esperar nao poe verde uma verificacao vermelha
        if self.conflitos or self.problemas or pr.estado in POR_INTEGRAR:
            return "INTEGRAR"
        if pr.rascunho or pr.estado == "DRAFT":
            return "RASCUNHO"
        if (pr.verificacoes.get("pending") or pr.estado == "UNKNOWN"
                or pr.fundivel == "UNKNOWN"):
            return "PENDENTE"          # o UNKNOWN e o que o GitHub da logo a seguir a uma fusao
        return "VERMELHO"


# --- leitura ----------------------------------------------------------------

def revisoes_em(ref: str) -> dict[str, str]:
    arvore = fonte.Arvore(ref)
    return {caminho: arvore.ler(caminho) or ""
            for caminho in arvore.listar(VERSIONS) if caminho.endswith(".py")}


def acrescentado(antes: str, depois: str) -> tuple[list[str], dict[str, list[str]]]:
    """`(revisoes novas, emendas por ficheiro)` de `antes` para `depois`.

    Com `antes` na `main`, isto e o que o ramo traz de seu **esteja ele a frente ou
    atras dela**: o que a `main` tem e o ramo nao sai como `D` ou como linha so do
    lado de `antes`, e nenhum dos dois conta.
    """
    mudancas = fonte.mudados(antes, depois)
    revisoes = sorted(c for estado, c in mudancas
                      if estado == "A" and sup.numero_de_revisao(c))
    emendas: dict[str, list[str]] = {}
    for estado, caminho in mudancas:
        if estado == "D" or not caminho.endswith(".md"):
            continue
        novas = sup.acrescentadas(fonte.Arvore(antes).ler(caminho),
                                  fonte.Arvore(depois).ler(caminho))
        if novas:
            emendas[caminho] = novas
    return revisoes, emendas


def avaliar(pr: PR, main: str, medir: Medidor) -> Avaliacao:
    """Sem conflitos, tudo se mede da `main` a arvore da fusao. Com conflitos a arvore
    tem marcadores: as revisoes e as emendas medem-se da `main` a ponta (o mesmo, pela
    razao do `acrescentado`), e so as seccoes caem para a base do ramo, que num ramo
    empilhado as conta a mais — e o relatorio di-lo."""
    arvore, conflitos = fonte.fundir(main, pr.ponta)
    if not conflitos:
        revisoes, emendas = acrescentado(main, arvore)
        avaliacao = Avaliacao(pr, revisoes, emendas, medir(arvore)[0] - medir(main)[0])
    else:
        base = fonte.base_comum(main, pr.ponta)
        if base is None:
            avaliacao = Avaliacao(pr, [], {}, 0)
            avaliacao.problemas.append("o ramo nao tem antepassado comum com a main: nasceu "
                                       "na linha do `origin` (KAM-180)")
            return avaliacao
        revisoes, emendas = acrescentado(main, pr.ponta)
        avaliacao = Avaliacao(pr, revisoes, emendas, medir(pr.ponta)[0] - medir(base)[0],
                              pela_base_do_ramo=True)
    medir_contra(avaliacao, arvore, conflitos, medir)
    return avaliacao


def medir_contra(av: Avaliacao, arvore: str, conflitos: list[str], medir: Medidor) -> None:
    """Mede a arvore da fusao com a `main` de agora: conflitos e as tres superficies."""
    problemas: list[str] = []
    if not conflitos:
        problemas += sup.problemas_da_cadeia(revisoes_em(arvore))
        for caminho in av.emendas:
            texto = fonte.Arvore(arvore).ler(caminho)
            if texto is not None:
                problemas += sup.problemas_de_versoes(caminho, texto)
        medidos, piso = medir(arvore)
        problema = sup.problema_do_piso(medidos, piso)
        if problema:
            problemas.append(problema)
    av.conflitos, av.problemas = conflitos, problemas


@dataclass
class Reserva:
    """O que os PRs **antes** deste na fila vao tomar quando fundirem.

    E o que impede a colisao de se repetir na renumeracao: a 2026-11-08 o KAM-070 e o
    KAM-184 foram ambos mandados para a «versao seguinte» do dicionario, e a seguinte
    de um e a de outro era a mesma 1.69. Os numeros dao-se pela ordem da fila, que e a
    ordem de fusao, e cada um conta com os que fundem antes dele.
    """

    revisoes: int = 0
    versoes: dict[str, int] = field(default_factory=dict)
    medidos: int = 0
    piso: int = 0


def instrucoes(av: Avaliacao, main: str, medir: Medidor, reserva: Reserva,
               piso_do_ramo: Callable[[str], int | None]) -> list[str]:
    """Os numeros que o PR tem de tomar para fundir **depois dos que estao a frente**."""
    linhas: list[str] = []
    topo = sup.cabeca(revisoes_em(main))
    proxima = (int(topo) if topo else 0) + reserva.revisoes
    for caminho in av.revisoes_novas:
        proxima += 1
        reserva.revisoes += 1
        pai = f"{proxima - 1:04d}"
        numero = sup.numero_de_revisao(caminho)
        if numero != f"{proxima:04d}":
            linhas.append(f"revisao `{caminho}` -> `{proxima:04d}`, com "
                          f"`down_revision = \"{pai}\"` (e o texto que cita {numero})")
        else:
            linhas.append(f"revisao {numero} fica, com `down_revision = \"{pai}\"`")
    for caminho, novas in sorted(av.emendas.items()):
        texto_main = fonte.Arvore(main).ler(caminho) or ""
        topo_v = sup.maximo(sup.versoes(texto_main))
        if topo_v is None:
            continue
        actual = topo_v
        for _ in range(reserva.versoes.get(caminho, 0)):
            actual = sup.seguinte(actual)
        esperadas: list[str] = []
        for _ in novas:
            actual = sup.seguinte(actual)
            esperadas.append(actual)
        reserva.versoes[caminho] = reserva.versoes.get(caminho, 0) + len(novas)
        if novas != esperadas:
            com_cabecalho = " e o cabecalho" if sup.cabecalho(texto_main) else ""
            linhas.append(f"`{caminho}`: {', '.join(novas)} -> {', '.join(esperadas)}"
                          f"{com_cabecalho}")
    medidos_main, piso_main = medir(main)
    piso_antes = max(piso_main, reserva.piso)
    reserva.medidos += av.delta_medidos
    medidos = medidos_main + reserva.medidos
    piso = max(sup.piso_exigido(medidos), piso_antes)
    declarado = piso_do_ramo(av.pr.ponta)
    nota = "o ramo ja tem" if declarado == piso else f"o ramo tem {declarado}"
    if piso > piso_antes:
        linhas.append(f"piso do `lint_bloco`: {medidos} medidos -> sobe para {piso}, e o "
                      f"literal par em `{sup.PAR_DO_PISO}`; e este PR que escreve a emenda "
                      f"({nota})")
    elif av.delta_medidos:
        linhas.append(f"piso do `lint_bloco`: {medidos} medidos -> fica em {piso}; nao lhe "
                      f"mexas, e num conflito fica o da main ({nota})")
    reserva.piso = piso
    return linhas


# --- a fila -----------------------------------------------------------------

def ordenar(avaliacoes: list[Avaliacao]) -> list[Avaliacao]:
    """Pela prontidao, e dentro de cada grupo pelo numero do PR."""
    return sorted(avaliacoes, key=lambda av: (ORDEM[av.veredicto], av.pr.numero))


def montar(prs: list[PR], main: str, medir: Medidor,
           piso_do_ramo: Callable[[str], int | None] = fonte.piso_declarado) -> list[Avaliacao]:
    fila = ordenar([avaliar(pr, main, medir) for pr in prs])
    reserva = Reserva()
    for posicao, av in enumerate(fila):
        av.depois_de = "main" if posicao == 0 else " e ".join(f"#{a.pr.numero}" for a in fila[:posicao])
        av.instrucoes = instrucoes(av, main, medir, reserva, piso_do_ramo)
    return fila


def relatorio(fila: list[Avaliacao], main: str) -> str:
    linhas = [f"fila sobre a main {main[:8]} — {len(fila)} PR(s) abertos", ""]
    for posicao, av in enumerate(fila, start=1):
        pr = av.pr
        cont = pr.verificacoes
        linhas.append(f"{posicao}. #{pr.numero} {pr.ticket}  {av.veredicto}   "
                      f"[{pr.fundivel} {pr.estado}{' DRAFT' if pr.rascunho else ''}]  "
                      f"ponta {pr.ponta[:8]}")
        if cont:
            linhas.append(f"   verificacoes: {cont.get('pass', 0)} verdes, "
                          f"{cont.get('desenho', 0)} de desenho, {cont.get('fail', 0)} vermelhas, "
                          f"{cont.get('pending', 0)} pendentes")
        for nome in pr.vermelhas:
            linhas.append(f"   vermelha: {nome}")
        for caminho in av.conflitos:
            nota = f" — {GERADOS[caminho]}" if caminho in GERADOS else ""
            linhas.append(f"   conflito com a main: {caminho}{nota}")
        for problema in av.problemas:
            linhas.append(f"   na arvore da fusao com a main de agora: {problema}")
        if av.instrucoes:
            base = " (com conflitos: as seccoes contam-se pela base do ramo)" if av.pela_base_do_ramo else ""
            linhas.append(f"   ao integrar, na posicao {posicao} (depois de {av.depois_de}){base}:")
            linhas += [f"     - {texto}" for texto in av.instrucoes]
        linhas.append("")
    cabeca_da_fila = fila[0] if fila and fila[0].pronto else None
    linhas.append(f"FUNDIR AGORA: #{cabeca_da_fila.pr.numero}" if cabeca_da_fila
                  else "FUNDIR AGORA: nenhum")
    linhas.append("Os numeros de cada um contam com os de cima a fundir primeiro. Se a "
                  "ordem mudar, corre a fila outra vez.")
    return "\n".join(linhas)


# --- GitHub -----------------------------------------------------------------

def prs_abertos() -> list[PR]:
    _, saida = fonte.correr("gh", "pr", "list", "--repo", fonte.REPO, "--state", "open",
                            "--limit", "200", "--json",
                            "number,title,headRefOid,mergeable,mergeStateStatus,isDraft")
    prs = []
    for dado in json.loads(saida):
        pr = PR(dado["number"], dado["title"], dado["headRefOid"],
                dado["mergeStateStatus"], dado["mergeable"], bool(dado.get("isDraft")))
        fonte.git("fetch", "-q", fonte.REMOTO,
                  f"pull/{pr.numero}/head:refs/remotes/{fonte.REMOTO}/pr/{pr.numero}", "--force")
        ler_verificacoes(pr)
        prs.append(pr)
    return prs


def ler_verificacoes(pr: PR) -> None:
    """Conta as verificacoes. O `gh pr checks` sai com nao-zero **por desenho**."""
    _, saida = fonte.correr("gh", "pr", "checks", str(pr.numero), "--repo", fonte.REPO,
                            "--json", "name,bucket", aceitar=(0, 1, 8))
    for dado in json.loads(saida or "[]"):
        balde = dado["bucket"]
        if balde == "fail" and "nao bloqueia" in dado["name"]:
            balde = "desenho"
        elif balde == "fail":
            pr.vermelhas.append(dado["name"])
        pr.verificacoes[balde] = pr.verificacoes.get(balde, 0) + 1


def fundir_cabeca(fila: list[Avaliacao], main_medida: str) -> int:
    if not fila or not fila[0].pronto or fila[0].pr.estado == "REPLAY":
        print("\nnada fundido: a cabeca da fila nao esta PRONTO")
        return 1
    pr = fila[0].pr
    remota = fonte.git("ls-remote", fonte.REMOTO, "refs/heads/main").split()[0]
    if remota != main_medida:
        print(f"\nnada fundido: a main mexeu-se desde a medicao ({main_medida[:8]} -> "
              f"{remota[:8]}). Corre a fila outra vez.")
        return 1
    for tentativa in (1, 2):
        codigo, _ = fonte.correr("gh", "pr", "merge", str(pr.numero), "--repo", fonte.REPO,
                                 "--squash", "--match-head-commit", pr.ponta, aceitar=(0, 1))
        if codigo == 0:
            break
        print(f"  a fusao do #{pr.numero} falhou (tentativa {tentativa}); vejo o estado")
    _, estado = fonte.correr("gh", "pr", "view", str(pr.numero), "--repo", fonte.REPO,
                             "--json", "state", "--jq", ".state")
    if estado.strip() != "MERGED":
        print(f"\no #{pr.numero} nao fundiu (estado {estado.strip()})")
        return 1
    nova = fonte.actualizar_base()
    print(f"\nfundido: #{pr.numero} -> main {nova[:8]}. Corre a fila outra vez: os numeros "
          f"dos outros mudaram.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="mede sobre esta ref em vez da publico/main")
    parser.add_argument("--pr", action="append", default=[], metavar="N=SHA",
                        help="reproduz a fila com estas pontas, sem GitHub")
    parser.add_argument("--sem-fetch", action="store_true")
    parser.add_argument("--fundir", action="store_true", help="funde a cabeca, se PRONTO")
    args = parser.parse_args(argv)
    if args.fundir and (args.pr or args.base):
        parser.error("--fundir nao se usa com --pr nem com --base: so funde o que mediu na main")
    if not args.sem_fetch and not args.base:
        fonte.actualizar_base()
    main_ref = fonte.git("rev-parse", args.base or fonte.BASE).strip()
    if args.pr:
        prs = []
        for item in args.pr:
            numero, ponta = item.split("=", 1)
            sha = fonte.git("rev-parse", ponta).strip()
            prs.append(PR(int(numero), fonte.git("log", "-1", "--format=%s", sha).strip(), sha))
    else:
        prs = prs_abertos()
    fila = montar(prs, main_ref, fonte.medir_piso)
    print(relatorio(fila, main_ref))
    if args.fundir:
        return fundir_cabeca(fila, main_ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
