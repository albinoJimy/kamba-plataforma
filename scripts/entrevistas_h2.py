#!/usr/bin/env python3
"""Mede H2 e o sinal de H1 a partir da ficha das entrevistas (KAM-106).

O bloco do KAM-106 (EPIC-10) encomenda-o assim:

    o *script* calcula, por PME, a percentagem dos 20 produtos em `fixo` ou
    `a partir de`; H2 `confirmada` se >= 15 de 30 PMEs (>= 50%) tiverem >= 70%
    (>= 14 de 20).

e pede-lhe tambem o sinal de H1 (faixas de preco e PMEs disponiveis para um
piloto gratuito), a % de PMEs em categoria vedada (entrada do KAM-088), o n.o
com cartao internacional (entrada do KAM-102 e de D5) e o resumo por canal.

## O que o script decide, e o que nao decide

Calcula o **estado que o limiar da**: `confirmada`, `refutada` ou
`inconclusiva`. **Nao decide H2.** A decisao e humana e regista-se no
`Registo_Hipoteses.md` com dono e data (EPIC-10 §1: «nenhuma decisao e
automatica»). O relatorio di-lo em todas as saidas.

## Tres leituras da letra, escritas para nao ficarem escondidas

1. **n diferente de 30.** A letra fixa «>= 15 de 30 (>= 50%)». Com n = 30 as
   duas formas coincidem; com mais de 30 entrevistas completas o script aplica
   os 50% sobre n, que e a forma de `14` §2. Com menos de 30, o estado e
   `inconclusiva`: a caixa pede 30 completas, e uma amostra mais pequena nao
   confirma nem refuta.
2. **PME com menos de 20 produtos.** A letra mede «dos 20 produtos». Uma linha
   sem os 20 classificados conta como **incompleta**, e as incompletas nao
   contam. E fail-closed e e a letra; se o dono do limiar quiser outra regra,
   muda-a por emenda registada antes da primeira entrevista.
3. **«Disponiveis para piloto».** As PMEs de categoria vedada entrevistam-se,
   mas nao entram no piloto (Detalhes Tecnicos do bloco), e o Piloto aceita so
   o segmento A, com NIF obrigatorio (`docs/tecnica/10_Onboarding_Governanca.md`
   §9 e §12). Por isso o relatorio da as duas contagens, e a regra dos «< 10»
   aplica-se as **elegiveis** (disponivel S, vedada N e formal S, que no guiao
   quer dizer «tem NIF»).
4. **Prazo da semana 4.** O estado de H2 conta todas as completas; com
   `--inicio`, o relatorio diz quantas ficaram fora do prazo e assinala quando
   as de dentro nao chegam a 30. Se o dono do limiar quiser H2 so sobre as de
   dentro, e emenda.

## Os dados nao vivem no repositorio

A ficha preenchida e dado bruto: vive no arquivo controlado e passa-se pelo
caminho. No repositorio ficam so o modelo vazio
(`docs/tecnica/evidencia/validacao/Entrevistas_Ficha.csv`) e uma ficha
**sintetica** de ensaio. Uma ficha com ids `SINT-` sai com um aviso em cada
relatorio, para que o ensaio nunca se leia como resultado.

    python scripts/entrevistas_h2.py FICHA.csv [--rondas RONDAS.csv]
        [--lista LISTA.csv] [--inicio AAAA-MM-DD] [--resumo]

Codigos de saida: 0 relatorio produzido (seja qual for o estado de H2);
2 ficha ilegivel ou com valor invalido — corrige-se a ficha, nao se le o
relatorio.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

#: Os limiares de H2 (EPIC-10 §KAM-106, proposta fixada antes de medir).
PRODUTOS = 20
ITENS_MINIMOS = 14  # 70% de 20
AMOSTRA = 30
CANAL_MAXIMO_PERMILAGEM = 400  # no maximo 40% de um so canal (proposta)
ELEGIVEIS_MINIMAS = 10
REPETIVEL_PMES = 6
REPETIVEL_RONDAS = 2

COLUNAS_PRODUTO = tuple(f"produto_{i:02d}" for i in range(1, PRODUTOS + 1))

#: As colunas da ficha, pela ordem do criterio 1, com a data acrescentada para
#: se poder medir o «ate ao fim da semana 4» do criterio 2.
COLUNAS = (
    "id_anonimo",
    "data_entrevista",
    "categoria",
    "formal",
    "n_empregados",
    "canal_origem",
    "dor",
    "comprovativos_semana",
    "faixa_preco",
    "cartao_internacional",
    "categoria_vedada",
    "disponivel_piloto",
    "consentimento",
) + COLUNAS_PRODUTO

CANAIS = ("C1", "C2", "C3", "C4", "C5")
SIM_NAO = ("S", "N")
FAIXAS = ("<15", "15-30", "30-60", ">60")  # mil Kz
CLASSES = ("fixo", "a partir de", "sob consulta")
ACEITES = ("fixo", "a partir de")
CONSENTIMENTOS = ("escrito", "gravado", "nao")

COLUNAS_RONDAS = ("canal", "ronda", "data", "pmes_alvo_entregues")
COLUNAS_LISTA = ("id_anonimo", "categoria", "categoria_vedada", "canal_origem", "papel")
PAPEIS = ("alvo", "suplente")

PREFIXO_SINTETICO = "SINT-"


class FichaInvalida(Exception):
    """A ficha nao se le, ou tem um valor fora do dominio."""


@dataclass
class Entrevista:
    id_anonimo: str
    data: dt.date
    canal: str
    faixa: str
    cartao: bool
    vedada: bool
    disponivel: bool
    formal: bool
    aceites: int

    @property
    def passa_h2(self) -> bool:
        return self.aceites >= ITENS_MINIMOS


@dataclass
class Leitura:
    completas: list[Entrevista] = field(default_factory=list)
    incompletas: list[str] = field(default_factory=list)
    sem_consentimento: list[str] = field(default_factory=list)


def _ler_csv(caminho: Path, esperadas: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise FichaInvalida(f"{caminho}: nao se le ({e})") from e
    primeira = texto.splitlines()[0] if texto.strip() else ""
    delim = ";" if ";" in primeira else ","
    leitor = csv.DictReader(texto.splitlines(), delimiter=delim)
    cabecalho = tuple((c or "").strip() for c in (leitor.fieldnames or ()))
    if cabecalho != esperadas:
        faltam = [c for c in esperadas if c not in cabecalho]
        a_mais = [c for c in cabecalho if c not in esperadas]
        raise FichaInvalida(
            f"{caminho}: cabecalho diferente do modelo"
            f" (em falta: {faltam or '-'}; a mais: {a_mais or '-'};"
            " ou a ordem trocada)"
        )
    linhas = []
    for n, bruta in enumerate(leitor, start=2):
        if None in bruta:
            raise FichaInvalida(f"{caminho}:{n}: mais celulas do que colunas")
        linha = {k.strip(): (v or "").strip() for k, v in bruta.items()}
        if any(linha.values()):
            linha["_linha"] = str(n)
            linhas.append(linha)
    return linhas


def _inteiro(valor: str, onde: str, minimo: int, maximo: int | None = None) -> int:
    try:
        n = int(valor)
    except ValueError as e:
        raise FichaInvalida(f"{onde}: «{valor}» nao e um inteiro") from e
    if n < minimo or (maximo is not None and n > maximo):
        raise FichaInvalida(f"{onde}: {n} fora de [{minimo}, {maximo or '...'}]")
    return n


def _dominio(valor: str, onde: str, dominio: tuple[str, ...]) -> str:
    if valor not in dominio:
        raise FichaInvalida(f"{onde}: «{valor}» nao e um de {list(dominio)}")
    return valor


def _data(valor: str, onde: str) -> dt.date:
    try:
        return dt.date.fromisoformat(valor)
    except ValueError as e:
        raise FichaInvalida(f"{onde}: «{valor}» nao e uma data AAAA-MM-DD") from e


def ler_ficha(caminho: Path) -> Leitura:
    """Le e valida a ficha. Celula vazia: incompleta. Valor invalido: erro."""
    leitura = Leitura()
    vistos: set[str] = set()
    for linha in _ler_csv(caminho, COLUNAS):
        onde = f"{caminho.name}:{linha['_linha']}"
        ident = linha["id_anonimo"]
        if not ident:
            raise FichaInvalida(f"{onde}: linha sem id_anonimo")
        if ident in vistos:
            raise FichaInvalida(f"{onde}: id_anonimo «{ident}» repetido")
        vistos.add(ident)
        # Os valores preenchidos validam-se sempre, mesmo numa linha incompleta:
        # um erro de digitacao corrige-se, nao se deixa cair calado.
        for col in COLUNAS[1:]:
            v = linha[col]
            if not v:
                continue
            o = f"{onde} [{col}]"
            if col == "data_entrevista":
                _data(v, o)
            elif col in ("formal", "cartao_internacional", "categoria_vedada", "disponivel_piloto"):
                _dominio(v, o, SIM_NAO)
            elif col == "n_empregados" or col == "comprovativos_semana":
                _inteiro(v, o, 0)
            elif col == "dor":
                _inteiro(v, o, 1, 5)
            elif col == "canal_origem":
                _dominio(v, o, CANAIS)
            elif col == "faixa_preco":
                _dominio(v, o, FAIXAS)
            elif col == "consentimento":
                _dominio(v, o, CONSENTIMENTOS)
            elif col in COLUNAS_PRODUTO:
                _dominio(v, o, CLASSES)
        if linha["consentimento"] == "nao":
            # Sem consentimento nao ha notas: uma resposta registada aqui e um
            # tratamento sem base, e apaga-se — nao se conta em silencio.
            if any(linha[c] for c in COLUNAS[1:] if c != "consentimento"):
                raise FichaInvalida(
                    f"{onde}: consentimento `nao` com respostas registadas; apaga-as"
                )
            leitura.sem_consentimento.append(ident)
            continue
        if any(not linha[c] for c in COLUNAS[1:]):
            leitura.incompletas.append(ident)
            continue
        leitura.completas.append(
            Entrevista(
                id_anonimo=ident,
                data=_data(linha["data_entrevista"], onde),
                canal=linha["canal_origem"],
                faixa=linha["faixa_preco"],
                cartao=linha["cartao_internacional"] == "S",
                vedada=linha["categoria_vedada"] == "S",
                disponivel=linha["disponivel_piloto"] == "S",
                formal=linha["formal"] == "S",
                aceites=sum(linha[c] in ACEITES for c in COLUNAS_PRODUTO),
            )
        )
    return leitura


def estado_h2(n: int, passam: int) -> str:
    """O estado que o limiar da. Nao e a decisao: essa e humana."""
    if n < AMOSTRA:
        return "inconclusiva"
    return "confirmada" if 2 * passam >= n else "refutada"


def ler_rondas(caminho: Path) -> dict[str, tuple[int, int]]:
    """Por canal: (PMEs-alvo entregues no total, rondas com entrega)."""
    total: dict[str, int] = {}
    rondas: dict[str, set[str]] = {}
    for linha in _ler_csv(caminho, COLUNAS_RONDAS):
        onde = f"{caminho.name}:{linha['_linha']}"
        if any(not linha[c] for c in COLUNAS_RONDAS):
            raise FichaInvalida(f"{onde}: linha de ronda com celula vazia")
        canal = _dominio(linha["canal"], f"{onde} [canal]", CANAIS)
        _data(linha["data"], f"{onde} [data]")
        n = _inteiro(linha["pmes_alvo_entregues"], f"{onde} [pmes_alvo_entregues]", 0)
        total[canal] = total.get(canal, 0) + n
        if n > 0:
            rondas.setdefault(canal, set()).add(linha["ronda"])
    return {c: (total.get(c, 0), len(rondas.get(c, ()))) for c in CANAIS}


def repetivel(entregues: int, n_rondas: int) -> bool:
    """>= 6 PMEs-alvo em >= 2 rondas (proposta do criterio 5)."""
    return entregues >= REPETIVEL_PMES and n_rondas >= REPETIVEL_RONDAS


def ler_lista(caminho: Path) -> tuple[int, int, int]:
    """(alvo, suplentes, vedadas) da lista de PMEs-alvo."""
    alvo = suplentes = vedadas = 0
    for linha in _ler_csv(caminho, COLUNAS_LISTA):
        onde = f"{caminho.name}:{linha['_linha']}"
        if any(not linha[c] for c in COLUNAS_LISTA):
            raise FichaInvalida(f"{onde}: linha da lista com celula vazia")
        papel = _dominio(linha["papel"], f"{onde} [papel]", PAPEIS)
        _dominio(linha["canal_origem"], f"{onde} [canal_origem]", CANAIS)
        if _dominio(linha["categoria_vedada"], f"{onde} [categoria_vedada]", SIM_NAO) == "S":
            vedadas += 1
        if papel == "alvo":
            alvo += 1
        else:
            suplentes += 1
    return alvo, suplentes, vedadas


def _de(k: int, n: int) -> str:
    """«k de n (p%)», e «0 de 0 (nao medido)» — zero de zero nao e zero por cento."""
    if n == 0:
        return f"{k} de 0 (não medido)"
    return f"{k} de {n} ({100 * k / n:.1f}%)"


def relatorio(
    leitura: Leitura,
    rondas: dict[str, tuple[int, int]] | None = None,
    lista: tuple[int, int, int] | None = None,
    inicio: dt.date | None = None,
) -> list[str]:
    """As linhas do relatorio, em Markdown, com contagens absolutas."""
    c = leitura.completas
    n = len(c)
    passam = sum(e.passa_h2 for e in c)
    estado = estado_h2(n, passam)
    out: list[str] = []
    ids = [e.id_anonimo for e in c] + leitura.incompletas + leitura.sem_consentimento
    if any(i.startswith(PREFIXO_SINTETICO) for i in ids):
        out += [
            "> **FICHA SINTÉTICA — isto é um ensaio, não é resultado.** Os ids",
            f"> `{PREFIXO_SINTETICO}` não são PMEs. Nada daqui entra no Registo de Hipóteses.",
            "",
        ]
    out += [
        "> **n = 30 é direccional.** As contagens dão um sinal, não uma estimativa",
        "> com margem de erro. O estado abaixo é o que o limiar dá; **a decisão",
        "> sobre H2 é humana** e regista-se no `Registo_Hipoteses.md` com dono e data.",
        "",
        "## Amostra",
        "",
        f"- Entrevistas completas: **{n}** (exigidas: {AMOSTRA}).",
        f"- Incompletas, que não contam: **{len(leitura.incompletas)}**.",
        f"- Linhas com consentimento `nao`, que não contam e **não deviam ter notas**: "
        f"**{len(leitura.sem_consentimento)}**.",
    ]
    if inicio is not None:
        fim = inicio + dt.timedelta(days=28)
        dentro = sum(e.data < fim for e in c)
        out.append(
            f"- Completas até ao fim da semana 4 (antes de {fim.isoformat()}): **{dentro}**;"
            f" fora do prazo: **{n - dentro}**."
        )
        if dentro < AMOSTRA:
            out.append(
                f"- **Critério 2 por cumprir**: menos de {AMOSTRA} completas dentro do prazo."
                " O estado de H2 abaixo conta todas as completas."
            )
    out += ["", "## H2 — preço publicável", ""]
    out.append(
        f"- PMEs com ≥ {ITENS_MINIMOS} de {PRODUTOS} produtos em `fixo` ou `a partir de`: "
        f"**{_de(passam, n)}** (limiar: ≥ 50% das PMEs, com n ≥ {AMOSTRA})."
    )
    out.append(f"- Estado que o limiar dá: **{estado}**.")
    if estado == "refutada":
        out += [
            "- Pivô de `14` §6: reposicionar para atendimento e disponibilidade, não",
            "  comparação de preço. Impacto a listar na decisão: **KAM-043**, **KAM-061**",
            "  e a mensagem comercial.",
        ]
    elif estado == "inconclusiva":
        out.append(f"- Amostra abaixo de {AMOSTRA}: o limiar não confirma nem refuta.")
    out += ["", "## Sinal de H1", "", "| Faixa (mil Kz) | PMEs |", "|---|---|"]
    for faixa in FAIXAS:
        out.append(f"| {faixa} | {sum(e.faixa == faixa for e in c)} |")
    disp = sum(e.disponivel for e in c)
    eleg = sum(e.disponivel and not e.vedada and e.formal for e in c)
    out += [
        "",
        f"- Disponíveis para piloto gratuito de 30 dias: **{_de(disp, n)}**.",
        f"- Elegíveis (disponíveis, com NIF e fora de categoria vedada): **{_de(eleg, n)}**.",
    ]
    if n < AMOSTRA:
        out.append(f"- Regra dos < {ELEGIVEIS_MINIMAS}: só se aplica depois das {AMOSTRA} entrevistas.")
    elif eleg < ELEGIVEIS_MINIMAS:
        out += [
            f"- **Problema de distribuição**: menos de {ELEGIVEIS_MINIMAS} elegíveis. Aplica-se a",
            "  última linha da tabela de `14` §6: antes de construir mais, resolver a",
            "  distribuição (parceiro de banco, associação ou contratar comercial).",
        ]
    out += [
        "",
        "## Entradas para outros tickets",
        "",
        f"- Em categoria vedada pela Meta ou pela lei (KAM-088): **{_de(sum(e.vedada for e in c), n)}**.",
        f"- Com cartão internacional (KAM-102, D5): **{_de(sum(e.cartao for e in c), n)}**.",
    ]
    if lista is not None:
        alvo, sup, ved = lista
        out.append(
            f"- Lista de PMEs-alvo: **{alvo}** alvo e **{sup}** suplentes; "
            f"em categoria vedada: **{_de(ved, alvo + sup)}**."
        )
    out += ["", "## Por canal", ""]
    maximo = max((sum(e.canal == k for e in c) for k in CANAIS), default=0)
    if rondas is None:
        out += ["| Canal | Entrevistas completas |", "|---|---|"]
        for k in CANAIS:
            out.append(f"| {k} | {sum(e.canal == k for e in c)} |")
    else:
        out += [
            "| Canal | Entrevistas completas | PMEs-alvo entregues | Rondas com entrega | Repetível |",
            "|---|---|---|---|---|",
        ]
        for k in CANAIS:
            ent, nr = rondas[k]
            out.append(
                f"| {k} | {sum(e.canal == k for e in c)} | {ent} | {nr} | "
                f"{'sim' if repetivel(ent, nr) else 'não'} |"
            )
        if not any(repetivel(*rondas[k]) for k in CANAIS):
            out.append(
                "\n- **Nenhum canal repetível.** À semana 6, isto pede a decisão escrita de "
                "resolver a distribuição antes de construir mais, com dono e data."
            )
    if n:
        ok = maximo * 1000 <= CANAL_MAXIMO_PERMILAGEM * n
        out.append(
            f"\n- Maior canal: {_de(maximo, n)} das completas — "
            + ("dentro do tecto de 40% (proposta)." if ok else "**acima do tecto de 40% (proposta)**.")
        )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mede H2 e o sinal de H1 (KAM-106).")
    p.add_argument("ficha", type=Path)
    p.add_argument("--rondas", type=Path, help="CSV das rondas por canal")
    p.add_argument("--lista", type=Path, help="CSV da lista de PMEs-alvo")
    p.add_argument("--inicio", help="primeiro dia da semana 1, AAAA-MM-DD")
    p.add_argument("--resumo", action="store_true", help="sai como modelo do resumo")
    a = p.parse_args(argv)
    try:
        leitura = ler_ficha(a.ficha)
        rondas = ler_rondas(a.rondas) if a.rondas else None
        lista = ler_lista(a.lista) if a.lista else None
        inicio = _data(a.inicio, "--inicio") if a.inicio else None
    except FichaInvalida as e:
        print(f"ficha invalida: {e}", file=sys.stderr)
        return 2
    linhas = relatorio(leitura, rondas, lista, inicio)
    if a.resumo:
        linhas = ["# H1 e H2 — resumo das entrevistas (KAM-106)", ""] + linhas
    print("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
