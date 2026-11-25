"""As nove linhas do `Registo_Hipoteses.md`, lidas pelo esquema do KAM-100.

O esquema é o dos «Detalhes Técnicos» do KAM-100, e é o mesmo que o
`scripts/validar_evidencia.py` verifica: doze colunas, por esta ordem, numa
tabela cuja primeira célula do cabeçalho é `H`. **Não se reimplementa a
validação da forma** — essa é do validador —; aqui recusa-se só o que impede de
ler: a tabela não está lá, as colunas não são estas, falta uma das nove linhas,
ou um estado não é nenhum dos três.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

COLUNAS = (
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

#: Os estados de uma hipótese (EPIC-10 §2). Não são os três da escala de
#: verificação do conjunto, e confundi-los faz uma hipótese parecer decidida por
#: haver uma fonte.
ESTADOS = ("confirmada", "refutada", "inconclusiva")

#: As nove do critério de saída do EPIC-10 §2. H10–H12 vivem na folha do EPIC-11
#: e, pela Carta §5, não bloqueiam o gate.
HIPOTESES = tuple(f"H{n}" for n in range(1, 10))

#: O que o Registo manda escrever numa célula que se olhou e não se mediu.
POR_MEDIR = "NÃO MEDIDO"


class RegistoIlegivel(ValueError):
    """O Registo não se deixa ler. Sai com o código 2, e não com o 1."""


@dataclass(frozen=True)
class Linha:
    h: str
    enunciado: str
    limiar: str
    metodo: str
    amostra: str
    resultado: str
    estado: str
    fonte: str
    decisao: str
    pivo: str
    dono: str
    data: str


def _celulas(linha: str) -> list[str]:
    nua = linha.strip()
    if not nua.startswith("|"):
        return []
    return [p.strip() for p in nua.split("|")[1:-1]]


def _separador(linha: str) -> bool:
    celulas = _celulas(linha)
    return bool(celulas) and all(re.fullmatch(r":?-{2,}:?", c) for c in celulas)


def _sem_marcas(celula: str) -> str:
    """O cabeçalho do Registo cita o `14` entre crases: compara-se sem elas."""
    return re.sub(r"\s*\(.*\)$", "", celula.replace("`", "")).strip()


def ler_texto(texto: str) -> dict[str, Linha]:
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        celulas = _celulas(linha)
        if not celulas or celulas[0] != "H":
            continue
        if i + 1 >= len(linhas) or not _separador(linhas[i + 1]):
            continue
        cabecalho = tuple(_sem_marcas(c) for c in celulas)
        if cabecalho != COLUNAS:
            raise RegistoIlegivel(
                f"as colunas são {cabecalho}, e o esquema do KAM-100 é {COLUNAS}"
            )
        resultado: dict[str, Linha] = {}
        for seguinte in linhas[i + 2 :]:
            if not seguinte.strip().startswith("|"):
                break
            corpo = _celulas(seguinte)
            if len(corpo) != len(COLUNAS):
                raise RegistoIlegivel(
                    f"a linha {corpo[:1]} tem {len(corpo)} células, e não {len(COLUNAS)}"
                )
            if corpo[0] in resultado:
                raise RegistoIlegivel(f"{corpo[0]} aparece duas vezes")
            estado = corpo[6].lower()
            if estado and estado not in ESTADOS:
                raise RegistoIlegivel(
                    f"{corpo[0]}: o estado {corpo[6]!r} não é nenhum de {ESTADOS}"
                )
            resultado[corpo[0]] = Linha(*corpo[:6], estado, *corpo[7:])
        em_falta = [h for h in HIPOTESES if h not in resultado]
        if em_falta:
            raise RegistoIlegivel(f"faltam as linhas {', '.join(em_falta)}")
        return {h: resultado[h] for h in HIPOTESES}
    raise RegistoIlegivel("não há tabela com a primeira coluna `H` seguida de separador")


def ler(caminho: Path) -> dict[str, Linha]:
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as erro:
        raise RegistoIlegivel(f"{caminho}: {erro}") from erro
    return ler_texto(texto)
