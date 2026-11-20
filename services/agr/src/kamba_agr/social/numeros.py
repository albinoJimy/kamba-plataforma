"""A guarda dos numeros de uma legenda (KAM-121, criterio 4): **0 preços ou promoções não-fact**.

    numeros_fora_dos_factos(texto, factos) -> os numeros do texto que nenhum facto tem
    promocao_sem_facto(texto, promocoes)   -> se o texto fala de uma promocao que o dono nao deu

## O que conta como numero, e com que unidade

Toda a sequencia de algarismos — valor, percentagem, data, hora, telefone —,
lida pelos algarismos e sem os separadores («45.000», «45 000» e «45000» sao o
mesmo numero), **com a unidade que a segue** (`%`, dinheiro, ou nenhuma). Um
numero so passa se um facto do dono valido no dia tiver **os mesmos algarismos
com a mesma unidade**: «30 minutos» nos factos nao autoriza «30%» na legenda
(achado I1 da revisao adversarial). Um numero sem unidade na legenda casa com
os mesmos algarismos em qualquer facto.

Os numeros por extenso contam tambem — com unidade («cinquenta por cento»,
«quinze porcento», «dez mil kwanzas», «cinquenta dolares»), como data («trinta
de dezembro») e como sequencia de quatro ou mais algarismos ditos («nove nove
nove...», um telefone). **Comparam-se pela expressao inteira**, e nao por
subcadeia: «cinco mil kwanzas» nao passa por estar dentro de «vinte e cinco mil
kwanzas» (achado I3).

E mais estrito do que o criterio, que nomeia «valor monetario, percentagem,
data de promocao ou telefone»: uma hora ou uma quantidade inventada tambem e um
numero que o dono nao deu, e distinguir os tipos a maquina era abrir a porta a
um que a regra nao viu.

## A promocao sem facto

Cada palavra de promocao da legenda («desconto», «gratis», «brinde», «leve...
pague», «preco especial», «queima de stock», ...) **tem de estar numa promocao
valida do dono** — nao basta haver uma qualquer (achado I1-b): com «10% de
desconto em sapatos» nos factos, «entrega gratis» nao passa. As palavras
genericas («promocao», «promo») passam com qualquer promocao valida. A lista e a
de `regras.PADROES_DE_PROMOCAO`, a mesma que decide se um facto e promocao.

O que a legenda faz quando a guarda recusa **nao e decidido aqui**: o
`geracao.py` devolve `faltam_factos` e o grafo pergunta os dados ao dono.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from .politicas import normalizar
from .regras import PADROES_DE_PROMOCAO, PROMOCAO_GENERICA, palavras_de_promocao

#: Uma sequencia de algarismos com os separadores de um numero: «.», «,», «:»,
#: «/» e «-» entre algarismos, e o espaco **so** antes de um grupo de tres
#: («45 000», «999 456 789»). «1, 2 e 3» sao tres numeros, e nao «12».
_ALGARISMOS: Final = re.compile(r"\d+(?:(?:[.,:/-]|\s(?=\d{3}\b))\d+)*")

#: A unidade que segue um numero (normalizado), ate dois espacos depois.
_UNIDADE_PERCENTAGEM: Final = re.compile(r"\A\s{0,2}(?:%|por\s?cento|porcento)")
_UNIDADE_DINHEIRO: Final = re.compile(
    r"\A\s{0,2}(?:mil\s+)?(?:kz|aoa|kwanzas?|usd|dolar(?:es)?|eur(?:os)?|\$)\b|\A\s{0,2}mil\b"
)

PERCENTAGEM: Final = "pct"
DINHEIRO: Final = "dinheiro"
SEM_UNIDADE: Final = ""

_UNIDADES_EXTENSO: Final = (
    "zero", "um", "uma", "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
    "onze", "doze", "treze", "catorze", "quatorze", "quinze", "dezasseis", "dezesseis", "dezassete",
    "dezessete", "dezoito", "dezanove", "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta",
    "setenta", "oitenta", "noventa", "cem", "cento", "duzentos", "duzentas", "trezentos", "trezentas",
    "quatrocentos", "quatrocentas", "quinhentos", "quinhentas", "seiscentos", "seiscentas", "setecentos",
    "setecentas", "oitocentos", "oitocentas", "novecentos", "novecentas", "mil", "milhao", "milhoes",
    "metade", "dobro", "meio", "meia",
)
_PALAVRA_NUMERO: Final = rf"(?:{'|'.join(_UNIDADES_EXTENSO)})"
_SEQUENCIA: Final = rf"{_PALAVRA_NUMERO}(?:\s+(?:e\s+)?{_PALAVRA_NUMERO})*"
_MESES: Final = r"(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"

#: Os numeros por extenso que contam: com unidade, como data, e como uma
#: sequencia de quatro ou mais algarismos ditos (um telefone).
_EXTENSO_COM_UNIDADE: Final = re.compile(
    rf"\b{_SEQUENCIA}\s*(?:por\s?cento|porcento|%|kz|aoa|kwanzas?|dolar(?:es)?|euros?|do\s+preco|de\s+desconto)\b"
)
_EXTENSO_DATA: Final = re.compile(rf"\b{_SEQUENCIA}\s+de\s+{_MESES}\b")
_DIGITO_DITO: Final = r"(?:zero|um|dois|tres|quatro|cinco|seis|sete|oito|nove)"
_EXTENSO_TELEFONE: Final = re.compile(rf"\b{_DIGITO_DITO}(?:[\s,.-]+{_DIGITO_DITO}){{3,}}\b")


def _so_algarismos(pedaco: str) -> str:
    return re.sub(r"\D", "", pedaco)


def _unidade(depois: str) -> str:
    if _UNIDADE_PERCENTAGEM.match(depois):
        return PERCENTAGEM
    if _UNIDADE_DINHEIRO.match(depois):
        return DINHEIRO
    return SEM_UNIDADE


def numeros_do_texto(texto: str) -> tuple[tuple[str, str], ...]:
    """Os numeros de um texto: `(algarismos, unidade)` por sequencia, e `(expressao, "extenso")`."""
    limpo = normalizar(texto)
    achados: list[tuple[str, str]] = []
    for m in _ALGARISMOS.finditer(limpo):
        digitos = _so_algarismos(m.group(0))
        if digitos:
            achados.append((digitos, _unidade(limpo[m.end() : m.end() + 20])))
    vistos: list[tuple[int, int]] = []
    for padrao in (_EXTENSO_COM_UNIDADE, _EXTENSO_DATA, _EXTENSO_TELEFONE):
        for m in padrao.finditer(limpo):
            if any(a <= m.start() < b for a, b in vistos):
                continue
            vistos.append((m.start(), m.end()))
            achados.append((" ".join(m.group(0).split()), "extenso"))
    return tuple(achados)


def numeros_fora_dos_factos(texto: str, factos: Iterable[str]) -> tuple[str, ...]:
    """Os numeros do texto que nenhum facto tem. Vazio e o unico resultado que entrega."""
    dos_factos: set[tuple[str, str]] = set()
    for facto in factos:
        dos_factos.update(numeros_do_texto(facto))
    so_algarismos = {d for d, u in dos_factos if u != "extenso"}
    fora: list[str] = []
    for valor, unidade in numeros_do_texto(texto):
        if unidade == "extenso":
            if (valor, unidade) not in dos_factos:
                fora.append(valor)
        elif unidade == SEM_UNIDADE:
            if valor not in so_algarismos:
                fora.append(valor)
        elif (valor, unidade) not in dos_factos:
            fora.append(f"{valor}{'%' if unidade == PERCENTAGEM else ' kz'}")
    return tuple(fora)


def fala_de_promocao(texto: str) -> bool:
    return bool(palavras_de_promocao(texto)) or any(u == PERCENTAGEM for _v, u in numeros_do_texto(texto))


def promocao_sem_facto(texto: str, promocoes_validas: Iterable[str]) -> bool:
    """Se o texto fala de uma promocao que o dono nao deu.

    Cada palavra de promocao do texto tem de estar numa promocao valida; as
    genericas passam com qualquer uma. Uma percentagem sem palavra tambem e
    promocao, e o numero dela confere-se na guarda de numeros.
    """
    validas = [normalizar(p) for p in promocoes_validas]
    usadas = palavras_de_promocao(texto)
    if not usadas:
        return fala_de_promocao(texto) and not validas
    for padrao in usadas:
        if padrao in PROMOCAO_GENERICA:
            if not validas:
                return True
            continue
        if not any(PADROES_DE_PROMOCAO[padrao].search(v) for v in validas):
            return True
    return False
