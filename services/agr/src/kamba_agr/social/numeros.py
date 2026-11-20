"""A guarda dos numeros de uma legenda (KAM-121, criterio 4): **0 preços ou promoções não-fact**.

    numeros_fora_dos_factos(texto, factos) -> os numeros do texto que nenhum facto tem
    promocao_sem_facto(texto, factos)      -> se o texto fala de promocao sem uma valida

## O que conta como numero

Toda a sequencia de algarismos — valor, percentagem, data, hora, telefone —,
lida pelos algarismos e sem os separadores («45.000», «45 000» e «45000» sao o
mesmo numero), e os numeros por extenso que um gerador escreve para fugir aos
algarismos («cinquenta por cento», «dez mil kwanzas»). **Um numero so passa se
estiver num facto** do dono valido no dia, ou no tema do proprio item (que veio
de um facto). E mais estrito do que o criterio, que nomeia «valor monetario,
percentagem, data de promocao ou telefone»: uma hora ou uma quantidade inventada
tambem e um numero que o dono nao deu, e distinguir os quatro tipos a maquina
era abrir a porta a um quinto que a regra nao viu.

## A promocao sem facto

Uma legenda que fala de promocao («desconto», «promocao», «gratis», «leve dois»)
sem nenhuma promocao valida nos factos do dono **nao se entrega**, mesmo sem
numero nenhum: «grande desconto esta semana» e uma promocao inventada.

O que a legenda faz quando a guarda recusa **nao e decidido aqui**: o
`geracao.py` devolve `faltam_factos` e o grafo pergunta os dados ao dono.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from .politicas import normalizar
from .regras import PALAVRAS_DE_PROMOCAO

#: Uma sequencia de algarismos com os separadores de um numero: «.», «,», «:»,
#: «/» e «-» entre algarismos, e o espaco **so** antes de um grupo de tres
#: («45 000», «999 456 789»). «1, 2 e 3» sao tres numeros, e nao «12».
_ALGARISMOS: Final = re.compile(r"\d+(?:(?:[.,:/-]|\s(?=\d{3}\b))\d+)*")

#: Os numeros por extenso que contam. Sem acentos.
_POR_EXTENSO: Final = (
    "zero", "um", "uma", "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
    "onze", "doze", "treze", "catorze", "quinze", "dezasseis", "dezassete", "dezoito", "dezanove", "vinte",
    "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa", "cem", "cento", "duzentos",
    "trezentos", "quinhentos", "mil", "milhao", "milhoes", "metade", "dobro",
)

#: Um numero por extenso so conta ao lado de uma unidade de dinheiro ou de
#: percentagem: «um produto» nao e um numero, «cinquenta por cento» e.
_UNIDADES: Final = r"(?:por cento|%|kz|kwanzas?|aoa|mil|milhoes|milhao|do preco|de desconto)"
_EXTENSO_COM_UNIDADE: Final = re.compile(
    rf"\b(?:{'|'.join(_POR_EXTENSO)})(?:\s+e\s+(?:{'|'.join(_POR_EXTENSO)}))*\s+{_UNIDADES}"
)


def _so_algarismos(pedaco: str) -> str:
    return re.sub(r"\D", "", pedaco)


def numeros_do_texto(texto: str) -> tuple[str, ...]:
    """Os numeros de um texto: os algarismos de cada sequencia, e os por extenso com unidade."""
    limpo = normalizar(texto)
    achados = [_so_algarismos(m.group(0)) for m in _ALGARISMOS.finditer(limpo)]
    achados.extend(m.group(0) for m in _EXTENSO_COM_UNIDADE.finditer(limpo))
    return tuple(a for a in achados if a)


def numeros_fora_dos_factos(texto: str, factos: Iterable[str]) -> tuple[str, ...]:
    """Os numeros do texto que nenhum facto tem. Vazio e o unico resultado que entrega.

    Um numero em algarismos esta num facto se os algarismos dele aparecem, como
    sequencia inteira, nos algarismos de um numero do facto: «45.000 Kz» casa
    com «45 000 kwanzas», e «5» **nao** casa com «45». Um por extenso so casa
    se o facto tiver o mesmo texto.
    """
    dos_factos: set[str] = set()
    textos_dos_factos = [normalizar(f) for f in factos]
    for facto in textos_dos_factos:
        dos_factos.update(numeros_do_texto(facto))
    fora: list[str] = []
    for numero in numeros_do_texto(texto):
        if numero.isdigit():
            if numero not in dos_factos:
                fora.append(numero)
        elif not any(numero in f for f in textos_dos_factos):
            fora.append(numero)
    return tuple(fora)


def fala_de_promocao(texto: str) -> bool:
    limpo = normalizar(texto)
    return any(re.search(rf"\b{re.escape(p)}", limpo) for p in PALAVRAS_DE_PROMOCAO)


def promocao_sem_facto(texto: str, promocoes_validas: Iterable[str]) -> bool:
    """Se o texto fala de promocao e o dono nao deu nenhuma valida."""
    return fala_de_promocao(texto) and not any(True for _ in promocoes_validas)
