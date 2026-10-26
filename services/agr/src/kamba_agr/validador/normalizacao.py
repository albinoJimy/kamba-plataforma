"""Normalizacao monetaria PT-AO: texto -> `value_minor` (`docs/tecnica/02` §9.1).

O criterio 1 do KAM-032 nomeia **nove** formatos e pede um teste por cada:

    12500   12.500   12 500   12,500   12500 Kz
    12.500,00 Kz     Kz 12.500         12,5 mil
    «doze mil e quinhentos»

e manda que «moeda diferente de Kz sem *fact* de moeda e erro».

## A unidade e o centimo, e nao o Kz

O criterio escreve «devolve `value_kz` inteiro». **Nao e o nome nem a unidade**, e
as duas fontes que decidem isso sao mais altas do que o bloco:

* o §2 do dicionario manda dinheiro em unidade menor inteira (`*_minor`), e a
  emenda 1.13 registou `valor_kz` como variante que ele substitui;
* o §9.1 do `docs/tecnica/02` foi **corrigido pelo KAM-139**: o *fact* vem do
  `search_catalog` do `docs/tecnica/05` §6.3, cujo contrato de saida e
  `preco_minor` **em centimos**, e comparar a fala em Kz com um *fact* em
  centimos falha **sempre**, por um factor de cem.

Esta na divida 106 e na emenda 1.39 (§3.30). «12.500 Kz» da 1250000.

## A ambiguidade do separador, que e o coracao deste ficheiro

Em PT-AO o ponto e o espaco separam milhares e a virgula separa decimais — mas o
criterio 1 pede `12,500` = 12500 Kz **e** `12,5 mil` = 12500 Kz, isto e, a mesma
virgula a decidir coisas diferentes. A regra que serve os nove, por ordem:

1. os dois separadores presentes -> o **ultimo** e o decimal (`12.500,00`);
2. so virgula, exactamente tres digitos depois e **sem multiplicador** ->
   milhares (`12,500`);
3. so virgula, o resto -> decimal (`12,5 mil`, `12,50`);
4. so ponto, exactamente tres digitos depois -> milhares (`12.500`);
5. so ponto, o resto -> decimal (`12.5`);
6. espaco -> milhares, sempre.

A regra 2 e a unica que e uma **escolha** e nao uma leitura: `12,500` tambem se
pode ler 12,5. Decide-se por milhares porque e o que o criterio escreve, e a
consequencia esta medida — `12,500` e `12,5 mil` dao os dois 1250000, pelo que a
escolha nao e observavel nestes dois; onde e observavel e em `1,500` (1500 Kz
contra 1,5 Kz), e nao ha moeda em Angola com centimos a circular.
"""

from __future__ import annotations

import re
from typing import Final

#: Um Kz em centimos (`specs/02` §2; EPIC-04, criterio 1: «1 Kz = 100 centimos»).
CENTIMOS_POR_KZ: Final = 100

#: As marcas de moeda que **sao** Kz. Allowlist, e nao uma lista de moedas
#: proibidas: a lista de proibidos protege contra as moedas de que alguem se
#: lembrou, a allowlist protege contra a forma (a licao do `ETIQUETA` do
#: `metricas.py`).
MARCAS_DE_KZ: Final = ("kz", "kwanza", "kwanzas", "aoa")

#: O que conta como marca de moeda ao lado de um numero: um simbolo, ou um
#: codigo de tres maiusculas (ISO 4217). O `KZ` e o `AOA` tambem casam, e nao e
#: defeito: a allowlist e consultada **antes** desta forma.
_MARCA_DE_MOEDA: Final = re.compile(r"^(?:R\$|[$€£¥₦₹]|[A-Z]{3})$")

#: Multiplicadores por extenso. O `mil` e do criterio 1 («12,5 mil»); o
#: `milhao` entra porque sem ele «2 milhoes de Kz» nao se extrai como dinheiro e
#: uma resposta **correcta** era recusada — custa uma linha e nao abre nada, que
#: a recusa ja era *fail-closed* de qualquer maneira.
MULTIPLICADORES: Final = {
    "mil": 1000,
    "milhao": 10**6,
    "milhoes": 10**6,
}

_UNIDADES: Final = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quinze": 15,
    # As quatro com duas grafias: a primeira e a europeia (a do conjunto), e a
    # brasileira aceita-se **a leitura** porque o texto que aqui chega e o do
    # modelo e nao o nosso. Escrever nao: o *renderer* escreve digitos.
    "catorze": 14, "quatorze": 14,
    "dezasseis": 16, "dezesseis": 16,
    "dezassete": 17, "dezessete": 17,
    "dezoito": 18,
    "dezanove": 19, "dezenove": 19,
}
_DEZENAS: Final = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
}
_CENTENAS: Final = {
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400,
    "quinhentos": 500, "quinhentas": 500, "seiscentos": 600, "seiscentas": 600,
    "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
}
#: Todas as palavras que podem fazer parte de um numero por extenso.
PALAVRAS_DE_NUMERO: Final = frozenset(
    set(_UNIDADES) | set(_DEZENAS) | set(_CENTENAS) | set(MULTIPLICADORES) | {"e"}
)

_SEM_ACENTO: Final = str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc")


class NaoEDinheiroError(ValueError):
    """O texto nao tem a forma de um valor monetario."""


class MoedaEstrangeiraError(ValueError):
    """Uma moeda que nao e Kz, e nao ha `kind` de moeda onde a sustentar.

    O criterio 1 diz «moeda diferente de Kz **sem *fact* de moeda** e erro», e o
    `KINDS` do KAM-028 esta fechado em quatro (`price`, `stock`, `total`,
    `datetime`): nao existe nem pode existir hoje um *fact* de moeda. Pelo que
    *qualquer* moeda estrangeira e erro — *fail-closed*, como o ADR-007 manda, e
    com o limite escrito: o lado positivo deste criterio (uma moeda estrangeira
    **com** *fact* a ser aceite) e **inverificavel** ate haver esse `kind`.
    E a divida 105, com credor KAM-031.
    """


def sem_acento(texto: str) -> str:
    """Minusculas sem acentos. O modelo escreve «milhoes» e «milhões»."""
    return texto.lower().translate(_SEM_ACENTO)


def extenso_para_int(texto: str) -> int:
    """«doze mil e quinhentos» -> 12500. Levanta `NaoEDinheiroError`.

    Acumula por escala: o `mil` e o `milhao` fecham o grupo que vem antes deles,
    e o resto soma-se. E a unica forma que lida com «mil e quinhentos» (onde o
    grupo antes do `mil` esta **vazio** e vale 1) e com «dois milhoes e mil».
    """
    palavras = [p for p in re.split(r"[\s-]+", sem_acento(texto).strip()) if p and p != "e"]
    if not palavras:
        raise NaoEDinheiroError("texto vazio")

    total = 0
    grupo = 0
    for palavra in palavras:
        if palavra in _UNIDADES:
            grupo += _UNIDADES[palavra]
        elif palavra in _DEZENAS:
            grupo += _DEZENAS[palavra]
        elif palavra in _CENTENAS:
            grupo += _CENTENAS[palavra]
        elif palavra in MULTIPLICADORES:
            escala = MULTIPLICADORES[palavra]
            # «mil» sozinho vale 1000, nao 0: o grupo vazio vale um.
            if escala == 10**6:
                total += (grupo or 1) * escala
                grupo = 0
            else:
                grupo = (grupo or 1) * escala
                total += grupo
                grupo = 0
        else:
            raise NaoEDinheiroError(f"{palavra!r} nao e palavra de numero")
    return total + grupo


def _digitos_para_decimal(bruto: str) -> tuple[int, int]:
    """`12.500,00` -> (12500, 0): a parte inteira e os centimos.

    As seis regras do cabecalho deste modulo, nesta ordem.
    """
    texto = bruto.strip().replace(" ", " ")
    if not re.fullmatch(r"\d[\d.,\s]*", texto):
        raise NaoEDinheiroError(f"{bruto!r} nao e uma sequencia de digitos")

    tem_ponto = "." in texto
    tem_virgula = "," in texto

    decimal = ""
    if tem_ponto and tem_virgula:
        # Regra 1: o ultimo dos dois e o decimal.
        separador = "," if texto.rindex(",") > texto.rindex(".") else "."
        inteiro, _, decimal = texto.rpartition(separador)
    elif tem_virgula:
        inteiro, _, cauda = texto.rpartition(",")
        # Regras 2 e 3.
        if len(cauda) == 3 and cauda.isdigit():
            inteiro, decimal = texto, ""
        else:
            decimal = cauda
    elif tem_ponto:
        inteiro, _, cauda = texto.rpartition(".")
        # Regras 4 e 5.
        if len(cauda) == 3 and cauda.isdigit():
            inteiro, decimal = texto, ""
        else:
            decimal = cauda
    else:
        inteiro = texto

    # Regra 6: o espaco e sempre separador de milhares, e os separadores de
    # milhares que ficaram na parte inteira saem agora.
    digitos = re.sub(r"[.,\s]", "", inteiro)
    # As duas metades numa guarda so: a da parte inteira **nao se consegue
    # alcancar** com o `fullmatch` acima (que ja exige digito a frente), e
    # separa-las deixava uma linha que nenhum teste podia cobrir. Fica a
    # guarda, porque e ela que vale no dia em que alguem alargar o `fullmatch`.
    if not digitos.isdigit() or (decimal and not decimal.isdigit()):
        raise NaoEDinheiroError(f"{bruto!r}: digitos ilegiveis")
    if len(decimal) > 2:
        # Tres casas decimais nao cabem em centimos, e arredondar dinheiro em
        # silencio e o defeito que o §2 do dicionario existe para nao ter.
        raise NaoEDinheiroError(f"{bruto!r}: mais de duas casas decimais")
    return int(digitos), int(decimal.ljust(2, "0")) if decimal else 0


def para_centimos(texto: str) -> int:
    """Um valor monetario PT-AO em centimos de AOA. Levanta em vez de adivinhar.

    Aceita os nove formatos do criterio 1. A moeda, quando vem, tem de ser Kz.
    """
    bruto = texto.strip().replace(" ", " ")
    if not bruto:
        raise NaoEDinheiroError("texto vazio")

    # A moeda primeiro: ela decide se isto e erro antes de valer a pena ler o
    # numero. `Kz 12.500` e `12.500 Kz` — vem dos dois lados.
    sem_marca = bruto
    for lado in (r"^\s*([^\s\d]+)\s*", r"\s*([^\s\d]+)\s*$"):
        achado = re.search(lado, sem_marca)
        if not achado:
            continue
        marca = achado.group(1).strip()
        if sem_acento(marca) in MARCAS_DE_KZ:
            sem_marca = sem_marca[: achado.start(1)] + sem_marca[achado.end(1) :]
        elif _MARCA_DE_MOEDA.match(marca):
            raise MoedaEstrangeiraError(
                f"{marca!r} nao e Kz, e nao existe `kind` de moeda onde a sustentar "
                "(divida 105; emenda 1.39)"
            )
    sem_marca = sem_marca.strip()

    # Um multiplicador por extenso no fim: «12,5 mil», «2 milhoes».
    escala = 1
    achado = re.search(r"\s+([a-zA-Z]+)\s*$", sem_marca)
    if achado:
        palavra = sem_acento(achado.group(1))
        if palavra in MULTIPLICADORES:
            escala = MULTIPLICADORES[palavra]
            sem_marca = sem_marca[: achado.start()].strip()
        elif palavra in PALAVRAS_DE_NUMERO:
            pass  # e tudo por extenso; trata-se abaixo
        else:
            raise NaoEDinheiroError(f"{achado.group(1)!r} nao e multiplicador")

    # Nao ha guarda de «multiplicador sem numero» porque ela nao podia disparar:
    # o padrao do multiplicador exige espaco antes, e o `strip` garante que esse
    # espaco tem algo a frente. Um `sem_marca` vazio cai no `extenso_para_int`,
    # que levanta «texto vazio» — o mesmo erro, sem a linha a mais.
    if re.match(r"^\d", sem_marca):
        inteiro, centimos = _digitos_para_decimal(sem_marca)
        total = (inteiro * CENTIMOS_POR_KZ + centimos) * escala
    else:
        total = extenso_para_int(sem_marca) * CENTIMOS_POR_KZ * escala
    return total


def kz_display(centimos: int) -> str:
    """Centimos -> «12 500 Kz» (EPIC-04, criterio 2: `precoDisplay`).

    O espaco e o separador de milhares do conjunto, e um valor com centimos
    mostra-os: um preco de 12.500,50 Kz que aparecesse como «12 500 Kz» era um
    numero diferente do *fact*, que e precisamente o que o validador recusa.

    **E um espaco normal e nao um `\\u00a0`**, porque o que sai daqui volta a
    entrar pelo extractor: o `12 500` e um dos nove formatos do criterio 1, e
    duas larguras de espaco eram duas gramaticas a manter.
    """
    if centimos < 0:
        raise ValueError("dinheiro negativo nao se apresenta")
    inteiro, resto = divmod(centimos, CENTIMOS_POR_KZ)
    grupos = f"{inteiro:,}".replace(",", " ")
    return f"{grupos},{resto:02d} Kz" if resto else f"{grupos} Kz"
