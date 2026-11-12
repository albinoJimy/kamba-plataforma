"""Numeros, moeda e restricoes de preco (KAM-062, `docs/tecnica/05` §5.1 passos 2-3 e §5.2).

Duas coisas, ambas puras e sobre a lista de *tokens* que o passo 1 deixou
(minusculas, sem acentos, sem pontuacao):

* **`por_extenso`** e o passo 2: os numeros ditos por extenso passam a
  algarismos («duzentos e cinquenta mil» -> `250 mil`). **So corre com
  `origem = 'voz'`** (criterio 3): numa mensagem escrita, «cinco» e mais
  provavelmente parte de um nome do que uma quantia, e a transcricao do STT
  (KAM-036) e que escreve os numeros por extenso.
* **`extrair_restricoes`** e o passo 3: o preco que o cliente diz e
  **restricao**, nao texto de indice. Sai da pergunta e vai, em unidade menor
  inteira (dicionario §2: `1 Kz = 100`), para a oferta viva (§6.3). Os *tokens*
  que formavam a restricao **saem** da lista: nao chegam ao `q_norm` nem ao
  `q_or`, e portanto nunca ao indice.

## O que e preco, e o que nao e

Um numero **so e preco** se levar multiplicador (`mil`, `k`, `milhao`,
`milhoes`) ou moeda (`kz`, `kwanza(s)`, `akz`, `kuanza`, `aoa`, ou estrangeira)
— ele ou o seu par num «entre X e Y». «250 litros», «2 bicicletas» e «iphone 13»
ficam como estao. Sem esta regra, o `13` do «iphone 13» virava um tecto de
preco e a pesquisa filtrava tudo.

| Forma (§5.2) | Saida |
|---|---|
| verbo de maximo + preco («ate», «no maximo», «menos de», «abaixo de») | `max_preco_minor` |
| verbo de minimo + preco («mais de», «acima de», «pelo menos», «no minimo», «a partir de») | `min_preco_minor` |
| «entre» preco «e» preco | `min_preco_minor` e `max_preco_minor` |
| preco sem verbo | `alvo_preco_minor` (ordena por proximidade, nao filtra) |
| moeda que nao e AOA | `moeda` com o codigo, e **nenhum** valor: a conversao nao e nossa, pergunta-se |

## As formas angolanas de escrever um valor

O passo 1 entrega os decimais com ponto e os milhares ja juntos: «250.000» e
`250000`, «250.000,00» e `250000.00`, «1,5 milhoes» e `1.5 milhoes`. Aqui
juntam-se ainda os milhares separados por espaco («250 000 kz») — so quando o
grupo acaba em multiplicador ou moeda, porque «quero 2 300» nao diz se e um
numero ou dois. A moeda pode vir depois de «de» («1 milhao de dolares»), e a
estrangeira antes do numero («$300», que o passo 1 da `usd 300`). Um valor
acima do `bigint` fica no tecto do `bigint`, que e «sem filtro» e nao um erro
da base.

## O que **nao** esta aqui, e porque

* **`qtd`.** O §5.1 lista-a no passo 3, e nenhum criterio a pede. Um numero
  solto seguido de palavra e tanto quantidade («2 bicicletas») como modelo
  («iphone 13 pro»), e adivinhar e pior do que nao extrair: fica no `q_norm`.
* **Um multiplicador seguido de unidade** («250 mil litros») le-se como preco.
  As unidades sao lexico (passo 4) e este passo corre antes dele; o dataset do
  KAM-064 diz se a forma aparece.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

#: Kz -> unidade menor (dicionario §2; §5.2: «daí o factor 100»).
MINOR_POR_KZ: Final = 100

#: O maior valor que a coluna `bigint` da oferta viva compara. Um tecto acima
#: disto e «sem tecto», e nao um `out of range` na base.
MAXIMO_BIGINT: Final = 2**63 - 1

#: Um numero como o passo 1 o entrega: inteiro ou com ponto decimal.
NUMERO: Final = re.compile(r"\d+(?:\.\d+)?")

#: As formas de AOA do §5.2, ja sem acentos.
MOEDA_AOA: Final = frozenset({"kz", "kwanza", "kwanzas", "akz", "kuanza", "kuanzas", "aoa"})

#: Moedas que nao sao AOA, pelo codigo que a pergunta mostra. O passo 1
#: converte `$` em `usd` e `€` em `eur` antes de apagar a pontuacao.
MOEDAS_ESTRANGEIRAS: Final = {
    "usd": "USD",
    "dolar": "USD",
    "dolares": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "real": "BRL",
    "reais": "BRL",
    "rand": "ZAR",
    "rands": "ZAR",
}

#: Os multiplicadores.
MULTIPLICADORES: Final = {
    "mil": 1_000,
    "k": 1_000,
    "milhao": 1_000_000,
    "milhoes": 1_000_000,
}

#: Os verbos de limite, como sequencias de *tokens*. A mais comprida primeiro,
#: para que «no maximo» ganhe a «maximo».
VERBOS_DE_MAXIMO: Final = (
    ("nao", "mais", "de"),
    ("no", "maximo"),
    ("menos", "de"),
    ("abaixo", "de"),
    ("inferior", "a"),
    ("maximo",),
    ("ate",),
)
VERBOS_DE_MINIMO: Final = (
    ("a", "partir", "de"),
    ("pelo", "menos"),
    ("no", "minimo"),
    ("mais", "de"),
    ("acima", "de"),
    ("superior", "a"),
    ("minimo",),
)

# ---------------------------------------------------------------- passo 2

_UNIDADES: Final = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
    "quinze": 15, "dezasseis": 16, "dezesseis": 16, "dezassete": 17,
    "dezessete": 17, "dezoito": 18, "dezanove": 19, "dezenove": 19,
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300, "quatrocentos": 400,
    "quatrocentas": 400, "quinhentos": 500, "quinhentas": 500,
    "seiscentos": 600, "seiscentas": 600, "setecentos": 700,
    "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
}

#: «um» e «uma» sao artigo antes de serem numero: so abrem um numero quando a
#: palavra seguinte tambem e de numero («um milhao»). «quero um telemovel»
#: fica como esta.
_ARTIGOS: Final = frozenset({"um", "uma"})


def _peso(token: str) -> int:
    """O peso de uma palavra de numero, para a regra da descida (`_ler_numero`)."""
    if token in ("milhao", "milhoes"):
        return 1_000_000
    if token == "mil":
        return 1_000
    return _UNIDADES[token]


def _e_palavra_de_numero(token: str) -> bool:
    return token in _UNIDADES or token in ("mil", "milhao", "milhoes")


def _ler_numero(tokens: Sequence[str], inicio: int) -> tuple[int, int, int] | None:
    """O numero por extenso em `inicio`: `(valor, fim, maior_multiplicador)`.

    **Cada palavra junta-se so a uma maior do que ela.** «duzentos e
    cinquenta», «cento e vinte», «mil e duzentos» descem; «cem e duzentos» sobe,
    e por isso sao dois numeros — e o «entre cem e duzentos mil» da voz fica
    `entre 100 e 200 mil`, e nao `300000` (achado 3 da revisao adversarial). Os
    multiplicadores (`mil`, `milhao`) multiplicam o que ficou para tras.
    """
    primeiro = tokens[inicio]
    if not _e_palavra_de_numero(primeiro):
        return None
    if primeiro in _ARTIGOS:
        seguinte = tokens[inicio + 1] if inicio + 1 < len(tokens) else ""
        if not _e_palavra_de_numero(seguinte):
            return None
    total = 0
    grupo = 0
    ultimo = 0  # o peso da ultima palavra lida; 0 antes da primeira
    maior = 1
    i = inicio
    while i < len(tokens):
        token = tokens[i]
        if token == "e" and ultimo and i + 1 < len(tokens) and tokens[i + 1] in _UNIDADES:
            if _UNIDADES[tokens[i + 1]] >= ultimo:
                break  # «cem e duzentos»: dois numeros, e o «e» fica
            i += 1
            continue
        if token in _UNIDADES:
            if ultimo and _UNIDADES[token] >= ultimo:
                break  # «cinco seis» sao dois numeros
            grupo += _UNIDADES[token]
        elif token == "mil":
            total += (grupo or 1) * 1_000
            grupo = 0
            maior = max(maior, 1_000)
        elif token in ("milhao", "milhoes"):
            total = (total + (grupo or 1)) * 1_000_000
            grupo = 0
            maior = 1_000_000
        else:
            break
        ultimo = _peso(token)
        i += 1
    return total + grupo, i, maior


def _decimal_em_texto(valor: Decimal) -> str:
    texto = format(valor, "f")
    return texto.rstrip("0").rstrip(".") if "." in texto else texto


def por_extenso(tokens: Sequence[str]) -> list[str]:
    """Passo 2: os numeros por extenso passam a algarismos.

    **O multiplicador dito fica dito**, em decimal se for preciso: «duzentos e
    cinquenta mil» sai `250 mil` e «dois mil e quinhentos» sai `2.5 mil`, que
    sao as formas escritas que o passo 3 le como preco. Sem isto, «ate dois mil
    e quinhentos» dava `ate 2500`, um numero solto sem multiplicador, e o tecto
    perdia-se (achado 4 da revisao adversarial).

    >>> por_extenso("ate duzentos e cinquenta mil kz".split())
    ['ate', '250', 'mil', 'kz']
    >>> por_extenso("mil e duzentos".split())
    ['1.2', 'mil']
    >>> por_extenso("entre cem e duzentos mil".split())
    ['entre', '100', 'e', '200', 'mil']
    """
    saida: list[str] = []
    i = 0
    while i < len(tokens):
        lido = _ler_numero(tokens, i)
        if lido is None:
            saida.append(tokens[i])
            i += 1
            continue
        valor, i, maior = lido
        if maior == 1:
            saida.append(str(valor))
        else:
            palavra = "milhoes" if maior == 1_000_000 else "mil"
            saida.extend((_decimal_em_texto(Decimal(valor) / maior), palavra))
    return saida


def valor_por_extenso(texto: str) -> int | None:
    """O valor de um numero dito por inteiro, ou `None` se nao for so isso.

    >>> valor_por_extenso("duzentos e cinquenta mil")
    250000
    """
    tokens = texto.split()
    if not tokens:
        return None
    lido = _ler_numero(tokens, 0)
    if lido is None or lido[1] != len(tokens):
        return None
    return lido[0]


# ---------------------------------------------------------------- passo 3


@dataclass(frozen=True)
class Restricoes:
    """As restricoes de preco da pergunta, em unidade menor inteira (AOA).

    `moeda` e o codigo da moeda **estrangeira** quando o cliente a usou; nesse
    caso nenhum valor e preenchido e o AGR pergunta (§5.2).
    """

    max_preco_minor: int | None = None
    min_preco_minor: int | None = None
    alvo_preco_minor: int | None = None
    moeda: str | None = None

    def como_dict(self) -> dict[str, object]:
        """So os campos preenchidos, por ordem fixa."""
        campos = (
            ("max_preco_minor", self.max_preco_minor),
            ("min_preco_minor", self.min_preco_minor),
            ("alvo_preco_minor", self.alvo_preco_minor),
            ("moeda", self.moeda),
        )
        return {nome: valor for nome, valor in campos if valor is not None}


@dataclass(frozen=True)
class _Preco:
    valor: Decimal  # em Kz, ja multiplicado
    multiplicador: int  # 1 sem multiplicador
    moeda: str | None  # "AOA", codigo estrangeiro, ou None
    fim: int

    @property
    def e_preco(self) -> bool:
        return self.multiplicador != 1 or self.moeda is not None

    @property
    def minor(self) -> int:
        bruto = (self.valor * MINOR_POR_KZ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return min(int(bruto), MAXIMO_BIGINT)


def _moeda_em(tokens: Sequence[str], i: int) -> tuple[str | None, int]:
    """A moeda em `i`, ou depois de um «de» em `i`: `(codigo, fim)`."""
    j = i + 1 if i < len(tokens) and tokens[i] == "de" else i
    if j < len(tokens) and tokens[j] in MOEDA_AOA:
        return "AOA", j + 1
    if j < len(tokens) and tokens[j] in MOEDAS_ESTRANGEIRAS:
        return MOEDAS_ESTRANGEIRAS[tokens[j]], j + 1
    return None, i


def _ler_preco(tokens: Sequence[str], inicio: int) -> _Preco | None:
    """`NUM [mult] [de] [moeda]` a comecar em `inicio`, ou `None`.

    O `NUM` e um numero do passo 1, os grupos de milhares separados por espaco
    («250 000», so se o que vem a seguir for multiplicador ou moeda), ou o
    `mil` sozinho seguido de moeda («ate mil kz»).
    """
    if inicio >= len(tokens):
        return None
    primeiro = tokens[inicio]
    if primeiro == "mil":
        moeda, fim = _moeda_em(tokens, inicio + 1)
        return _Preco(Decimal(1_000), 1_000, moeda, fim) if moeda else None
    if not NUMERO.fullmatch(primeiro):
        return None
    texto, i = primeiro, inicio + 1
    if primeiro.isdigit() and len(primeiro) <= 3:
        j = i
        while j < len(tokens) and len(tokens[j]) == 3 and tokens[j].isdigit():
            j += 1
        seguinte = tokens[j] if j < len(tokens) else ""
        if j > i and (seguinte in MULTIPLICADORES or _moeda_em(tokens, j)[0]):
            texto, i = "".join(tokens[inicio:j]), j
    valor = Decimal(texto)
    multiplicador = 1
    if i < len(tokens) and tokens[i] in MULTIPLICADORES:
        multiplicador = MULTIPLICADORES[tokens[i]]
        valor *= multiplicador
        i += 1
    moeda, i = _moeda_em(tokens, i)
    return _Preco(valor, multiplicador, moeda, i)


def _verbo(tokens: Sequence[str], inicio: int, verbos: tuple[tuple[str, ...], ...]) -> int:
    """O comprimento do verbo de limite em `inicio`, ou 0."""
    for verbo in verbos:
        if tuple(tokens[inicio : inicio + len(verbo)]) == verbo:
            return len(verbo)
    return 0


def _moeda_prefixada(tokens: Sequence[str], inicio: int) -> str | None:
    """`usd 300`, `$300` (o passo 1 da `usd 300`): a moeda antes do numero."""
    token = tokens[inicio] if inicio < len(tokens) else ""
    seguinte = tokens[inicio + 1] if inicio + 1 < len(tokens) else ""
    if token in MOEDAS_ESTRANGEIRAS and NUMERO.fullmatch(seguinte):
        return MOEDAS_ESTRANGEIRAS[token]
    return None


def extrair_restricoes(tokens: Sequence[str]) -> tuple[Restricoes, list[str]]:
    """Passo 3: as restricoes de preco e os *tokens* que sobram.

    Uma restricao posterior substitui a anterior do mesmo tipo, e um minimo
    acima do maximo cai (o cliente corrigiu-se; o tecto e o que fica).

    >>> r, resto = extrair_restricoes("geleira ate 250 mil".split())
    >>> r.max_preco_minor, resto
    (25000000, ['geleira'])
    """
    maximo: int | None = None
    minimo: int | None = None
    alvo: int | None = None
    estrangeira: str | None = None
    resto: list[str] = []
    i = 0
    while i < len(tokens):
        # «entre X e Y»: o multiplicador e a moeda do Y valem para o X.
        if tokens[i] == "entre":
            a = _ler_preco(tokens, i + 1)
            if a is not None and a.fim < len(tokens) and tokens[a.fim] == "e":
                b = _ler_preco(tokens, a.fim + 1)
                if b is not None and (a.e_preco or b.e_preco):
                    if a.multiplicador == 1 and b.multiplicador != 1:
                        a = _Preco(a.valor * b.multiplicador, b.multiplicador, a.moeda, a.fim)
                    moeda = a.moeda or b.moeda
                    if moeda not in (None, "AOA"):
                        estrangeira = moeda
                    else:
                        minimo, maximo = sorted((a.minor, b.minor))
                    i = b.fim
                    continue
        n_max = _verbo(tokens, i, VERBOS_DE_MAXIMO)
        n_min = 0 if n_max else _verbo(tokens, i, VERBOS_DE_MINIMO)
        salto = n_max or n_min
        prefixada = _moeda_prefixada(tokens, i + salto)
        if prefixada is not None:
            # «ate $300»: o verbo, a moeda e o numero saem juntos.
            estrangeira = prefixada
            i += salto + 2
            continue
        preco = _ler_preco(tokens, i + salto)
        if preco is not None and preco.e_preco:
            if preco.moeda not in (None, "AOA"):
                estrangeira = preco.moeda
            elif n_max:
                maximo = preco.minor
            elif n_min:
                minimo = preco.minor
            else:
                alvo = preco.minor
            i = preco.fim
            continue
        resto.append(tokens[i])
        i += 1
    if estrangeira is not None:
        # Um valor noutra moeda nao se converte aqui: nenhum tecto, pergunta-se.
        return Restricoes(moeda=estrangeira), resto
    if minimo is not None and maximo is not None and minimo > maximo:
        minimo = None
    return Restricoes(maximo, minimo, alvo), resto
