#!/usr/bin/env python3
"""Valida ficheiros de evidencia e o Registo de Hipoteses (KAM-100).

O bloco do KAM-100 encomenda-o assim:

    Um validador (`scripts/validar_evidencia.py`) falha se faltar um campo ou se
    um ficheiro de evidencia nao declarar `Estado` (CONFIRMADO, INDICIO, NAO
    VERIFICADO), `Fonte`, `Data` e `Dono`.

E e citado pelos «Testes Requeridos» do KAM-101, KAM-103, KAM-104 e KAM-105, que
e a razao de ele viver em `scripts/` e nao dentro do spike: o `spikes/h3/` e
descartavel e estes quatro tickets nao sao.

## «Falta um campo» tem duas leituras, e as duas se cumprem — em modos distintos

Um registo de hipoteses **nasce vazio**: o KAM-100 entrega as nove linhas por
preencher, e as celulas enchem-se a medida que cada hipotese morre ou sobrevive.
Logo um validador que falhasse sobre uma celula vazia recusava o artefacto no dia
em que ele nasce, e seria desligado na primeira semana.

Por isso ha dois modos, e a distincao e a parte util:

    check       falha se faltar uma **coluna**, se as linhas nao forem H1..H9,
                ou se um `estado` preenchido nao for um dos tres valores.
                Conta as celulas vazias e **diz quantas**, sem falhar.
    completo    falha tambem sobre celula vazia. E o modo do fim do spike, e o
                que a caixa do criterio de saida do EPIC-10 exige («9 de 9
                linhas completas»).

Um `check` verde sobre um ficheiro recem-nascido **nao** quer dizer «as hipoteses
estao decididas»: quer dizer «a folha tem a forma certa». A saida do `check`
imprime sempre a contagem de vazias, para que ninguem leia uma coisa pela outra.

## O que o validador nao faz

Nao julga se um `Estado` esta **certo**. Dizer que a elegibilidade de Angola e
NAO VERIFICADA em vez de CONFIRMADA e uma leitura de fonte, e nenhuma expressao
regular a faz. O validador verifica que a declaracao **existe** e que o valor
pertence aos tres; promover um INDICIO a facto continua a ser um acto humano, e
e esse o defeito mais comum nesta casa.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

#: Os tres estados da escala de verificacao do conjunto.
ESTADOS = ("CONFIRMADO", "INDÍCIO", "NÃO VERIFICADO")

#: As quatro declaracoes que um ficheiro de evidencia tem de ter.
DECLARACOES = ("Estado", "Fonte", "Data", "Dono")

#: As doze colunas do Registo de Hipoteses, pela ordem que o EPIC-10 §KAM-100
#: fixa nos «Detalhes Tecnicos». A ordem **conta**: uma folha com as colunas
#: trocadas lê-se errada por quem a preencher a mao.
COLUNAS_DO_REGISTO = (
    "H",
    "enunciado",
    "limiar",
    "método",
    "amostra n",
    "resultado",
    "estado",
    "fonte",
    "decisão",
    "pivô aplicável",
    "dono",
    "data",
)

#: Os estados de uma hipotese. Sao os do criterio de saida do EPIC-10 §2, e
#: **nao** os tres da escala de verificacao: uma hipotese confirma-se, refuta-se
#: ou fica inconclusiva; uma afirmacao sobre o mundo e que e CONFIRMADO,
#: INDICIO ou NAO VERIFICADO. Confundi-los era o erro facil.
ESTADOS_DE_HIPOTESE = ("confirmada", "refutada", "inconclusiva")

#: As nove hipoteses que o criterio de saida do EPIC-10 §2 exige na folha.
#:
#: **O `14` §2 tem doze** (H10, H11 e H12 sao as dos modulos de entrada, do
#: EPIC-11). A divergencia e real e esta registada no §4 do
#: `Registo_Hipoteses.md`, devolvida ao fundador: o criterio diz «H1–H9 (…) 9 de
#: 9 linhas completas», e alargar a folha a doze mudava o criterio de saida de um
#: epic — que nao e gesto de executor. O validador segue o criterio.
HIPOTESES = tuple(f"H{n}" for n in range(1, 10))

#: O que se escreve numa celula ainda por medir. Uma celula com isto **nao** e
#: vazia: e uma afirmacao de que se olhou e nao se mediu.
POR_MEDIR = "NÃO MEDIDO"


class Achado:
    """Um defeito encontrado. Imprime-se como `ficheiro: onde: porque`."""

    def __init__(self, ficheiro: str, onde: str, porque: str):
        self.ficheiro = ficheiro
        self.onde = onde
        self.porque = porque

    def __str__(self) -> str:
        return f"{self.ficheiro}: {self.onde}: {self.porque}"


def _celulas(linha: str) -> list[str]:
    """As celulas de uma linha de tabela Markdown, sem as barras das pontas."""
    nua = linha.strip()
    if not nua.startswith("|"):
        return []
    partes = nua.split("|")
    # A primeira e a ultima sao vazias, por causa das barras das pontas.
    return [p.strip() for p in partes[1:-1]]


def _e_separador(linha: str) -> bool:
    celulas = _celulas(linha)
    return bool(celulas) and all(re.fullmatch(r":?-{2,}:?", c) for c in celulas)


def declaracoes(texto: str) -> dict[str, str]:
    """As quatro declaracoes do ficheiro, onde quer que estejam.

    Aceitam-se **duas** formas, porque o conjunto usa as duas e recusar uma era
    recusar metade dos ficheiros:

        | Estado | CONFIRMADO |        numa tabela de cabecalho
        **Estado:** CONFIRMADO          numa linha de prosa

    Devolve so as que encontrou. Quem decide se falta algo e `verificar_ficheiro`.
    """
    achadas: dict[str, str] = {}
    for linha in texto.splitlines():
        celulas = _celulas(linha)
        if len(celulas) == 2 and celulas[0] in DECLARACOES:
            achadas.setdefault(celulas[0], celulas[1])
            continue
        m = re.match(r"\s*\*{0,2}(" + "|".join(DECLARACOES) + r")\*{0,2}\s*:\s*(.+)", linha)
        if m:
            achadas.setdefault(m.group(1), m.group(2).strip())
    return achadas


def verificar_ficheiro(caminho: Path) -> list[Achado]:
    """As quatro declaracoes existem, e o `Estado` e um dos tres."""
    nome = caminho.as_posix()
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as e:
        return [Achado(nome, "leitura", str(e))]

    achados: list[Achado] = []
    achadas = declaracoes(texto)
    for campo in DECLARACOES:
        valor = achadas.get(campo, "")
        if not valor:
            achados.append(
                Achado(
                    nome,
                    campo,
                    f"nao declarado. Escreva `| {campo} | <valor> |` na tabela de "
                    f"cabecalho ou `**{campo}:** <valor>` no corpo",
                )
            )
    estado = achadas.get("Estado", "")
    if estado and not any(e in estado.upper() for e in ("CONFIRMADO", "INDÍCIO", "NÃO VERIFICADO")):
        achados.append(
            Achado(
                nome,
                "Estado",
                f"{estado!r} nao e nenhum de {ESTADOS}. Um quarto estado faz a "
                "escala deixar de dizer o que diz",
            )
        )
    return achados


def _tabela_do_registo(texto: str) -> tuple[list[str], list[list[str]], int]:
    """O cabecalho, as linhas e o numero da linha do cabecalho.

    Procura a **primeira** tabela cuja primeira celula do cabecalho seja `H`.
    Uma folha pode ter outras tabelas — a de aprovacao, a de versoes — e
    apanhar a primeira tabela do ficheiro era fragil.
    """
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        celulas = _celulas(linha)
        if not celulas or celulas[0] != "H":
            continue
        if i + 1 >= len(linhas) or not _e_separador(linhas[i + 1]):
            continue
        corpo: list[list[str]] = []
        for seguinte in linhas[i + 2 :]:
            if not seguinte.strip().startswith("|"):
                break
            corpo.append(_celulas(seguinte))
        return celulas, corpo, i + 1
    return [], [], 0


def verificar_registo(caminho: Path, completo: bool) -> tuple[list[Achado], int, int]:
    """A folha de hipoteses: colunas, linhas e celulas.

    Devolve `(achados, vazias, total_de_celulas)`. As vazias contam-se sempre,
    mesmo em `check`, e imprimem-se — e o que impede alguem de ler «a forma esta
    certa» como «as hipoteses estao decididas».
    """
    nome = caminho.as_posix()
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as e:
        return ([Achado(nome, "leitura", str(e))], 0, 0)

    cabecalho, corpo, numero = _tabela_do_registo(texto)
    if not cabecalho:
        return (
            [
                Achado(
                    nome,
                    "tabela",
                    "nao se encontrou nenhuma tabela cuja primeira coluna seja `H`",
                )
            ],
            0,
            0,
        )

    achados: list[Achado] = []
    # As colunas comparam-se por **prefixo normalizado**: o cabecalho real leva
    # «pivô aplicável (`14` §6)», e exigir a cadeia exacta obrigava a repetir a
    # pontuacao e as cercas aqui.
    def normal(c: str) -> str:
        return re.sub(r"[`*]", "", c).strip().lower()

    reais = [normal(c) for c in cabecalho]
    for i, esperada in enumerate(COLUNAS_DO_REGISTO):
        alvo = esperada.lower()
        if i >= len(reais):
            achados.append(
                Achado(nome, f"linha {numero}", f"falta a coluna {esperada!r}")
            )
        elif not reais[i].startswith(alvo):
            achados.append(
                Achado(
                    nome,
                    f"linha {numero}, coluna {i + 1}",
                    f"esperava {esperada!r} e esta {cabecalho[i]!r}; a **ordem** das "
                    "doze colunas e a do esquema do EPIC-10",
                )
            )
    if len(reais) > len(COLUNAS_DO_REGISTO):
        achados.append(
            Achado(
                nome,
                f"linha {numero}",
                f"{len(reais)} colunas e o esquema tem {len(COLUNAS_DO_REGISTO)}: "
                f"a mais, {cabecalho[len(COLUNAS_DO_REGISTO):]}",
            )
        )

    presentes = [normal(l[0]) if l else "" for l in corpo]
    for h in HIPOTESES:
        if h.lower() not in presentes:
            achados.append(Achado(nome, "linhas", f"falta a linha {h}"))
    extra = [p for p in presentes if p and p not in [h.lower() for h in HIPOTESES]]
    if extra:
        achados.append(
            Achado(
                nome,
                "linhas",
                f"linhas a mais: {extra}. O criterio de saida do EPIC-10 §2 pede "
                "H1–H9; alargar a folha muda o criterio de um epic",
            )
        )

    vazias = 0
    total = 0
    for i, celulas in enumerate(corpo):
        etiqueta = celulas[0] if celulas else "?"
        for j, celula in enumerate(celulas):
            total += 1
            if celula in ("", "—", "-"):
                vazias += 1
                if completo:
                    coluna = (
                        COLUNAS_DO_REGISTO[j]
                        if j < len(COLUNAS_DO_REGISTO)
                        else f"coluna {j + 1}"
                    )
                    achados.append(
                        Achado(nome, f"{etiqueta}/{coluna}", "celula vazia")
                    )
        estado = celulas[6] if len(celulas) > 6 else ""
        if estado and estado not in ("", "—", "-", POR_MEDIR):
            if normal(estado) not in ESTADOS_DE_HIPOTESE:
                achados.append(
                    Achado(
                        nome,
                        f"{etiqueta}/estado",
                        f"{estado!r} nao e nenhum de {ESTADOS_DE_HIPOTESE}",
                    )
                )
    return (achados, vazias, total)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="validar_evidencia",
        description="Valida ficheiros de evidencia e o Registo de Hipoteses (KAM-100).",
        epilog="Codigo de saida: 0 conforme, 1 achados, 2 erro de uso.",
    )
    p.add_argument(
        "ficheiros",
        nargs="*",
        help="os ficheiros a validar. Um deles pode ser o Registo de Hipoteses, "
        "que se reconhece pelo nome ou se nomeia com --registo",
    )
    p.add_argument(
        "--registo",
        action="append",
        default=[],
        metavar="FICHEIRO",
        help="valida este ficheiro como Registo de Hipoteses (repetivel)",
    )
    p.add_argument(
        "--completo",
        action="store_true",
        help="falha tambem sobre celula vazia do registo. O modo do fim do spike",
    )
    a = p.parse_args(argv)

    registos = [Path(f) for f in a.registo]
    simples: list[Path] = []
    for f in a.ficheiros:
        caminho = Path(f)
        if "registo_hipoteses" in caminho.name.lower().replace("-", "_"):
            registos.append(caminho)
        else:
            simples.append(caminho)

    if not registos and not simples:
        p.error("nenhum ficheiro: diga quais, ou use --registo")

    em_falta = [c for c in registos + simples if not c.is_file()]
    if em_falta:
        for c in em_falta:
            print(f"ERRO: {c} nao existe", file=sys.stderr)
        return 2

    achados: list[Achado] = []
    for caminho in simples:
        achados.extend(verificar_ficheiro(caminho))
    for caminho in registos:
        seus, vazias, total = verificar_registo(caminho, a.completo)
        achados.extend(seus)
        if total:
            print(
                f"{caminho.as_posix()}: {total - vazias} de {total} celula(s) "
                f"preenchida(s); **{vazias} por preencher**"
                + ("" if a.completo else " (nao falha em `check`; use --completo)")
            )

    for achado in achados:
        print(f"  . {achado}", file=sys.stderr)
    alvos = len(simples) + len(registos)
    if achados:
        print(
            f"validar_evidencia: {len(achados)} achado(s) em {alvos} ficheiro(s)",
            file=sys.stderr,
        )
        return 1
    print(f"validar_evidencia: conforme — {alvos} ficheiro(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
