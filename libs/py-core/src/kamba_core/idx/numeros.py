"""Numeros, moeda e restricoes de preco (KAM-062, `docs/tecnica/05` §5.1 passos 2-3 e §5.2).

Duas coisas, ambas puras e sobre a lista de *tokens* que o passo 1 deixou
(minusculas, sem acentos, sem pontuacao):

* **`por_extenso`** e o passo 2: os numeros ditos por extenso passam a
  algarismos («duzentos e cinquenta mil» -> `250000`). **So corre com
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

## O que **nao** esta aqui, e porque

* **`qtd`.** O §5.1 lista-a no passo 3, e nenhum criterio a pede. Um numero
  solto seguido de palavra e tanto quantidade («2 bicicletas») como modelo
  («iphone 13 pro»), e adivinhar e pior do que nao extrair: fica no `q_norm`.
* **Decimais** («1,5 milhoes»). A virgula e pontuacao no passo 1. Fica escrito
  como limite; o dataset do KAM-064 diz se aparece.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

#: Kz -> unidade menor (dicionario §2; §5.2: «daí o factor 100»).
MINOR_POR_KZ: Final = 100

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


def _e_palavra_de_numero(token: str) -> bool:
    return token in _UNIDADES or token in ("mil", "milhao", "milhoes")


def _ler_numero(tokens: Sequence[str], inicio: int) -> tuple[int, int] | None:
    """O numero por extenso que comeca em `inicio`: `(valor, fim)`, ou `None`."""
    primeiro = tokens[inicio]
    if not _e_palavra_de_numero(primeiro):
        return None
    if primeiro in _ARTIGOS:
        seguinte = tokens[inicio + 1] if inicio + 1 < len(tokens) else ""
        if not _e_palavra_de_numero(seguinte):
            return None
    total = 0
    grupo = 0
    i = inicio
    lido = False
    while i < len(tokens):
        token = tokens[i]
        if token in _UNIDADES:
            grupo += _UNIDADES[token]
        elif token == "mil":
            total += (grupo or 1) * 1_000
            grupo = 0
        elif token in ("milhao", "milhoes"):
            total = (total + (grupo or 1)) * 1_000_000
            grupo = 0
        elif (
            token == "e"
            and lido
            and i + 1 < len(tokens)
            and tokens[i + 1] in _UNIDADES
        ):
            # «duzentos e cinquenta»: o «e» so liga duas palavras de numero.
            i += 1
            continue
        else:
            break
        lido = True
        i += 1
    return total + grupo, i


def por_extenso(tokens: Sequence[str]) -> list[str]:
    """Passo 2: os numeros por extenso passam a algarismos.

    >>> por_extenso("ate duzentos e cinquenta mil kz".split())
    ['ate', '250', 'mil', 'kz']
    >>> por_extenso("mil e duzentos".split())
    ['1200']
    """
    saida: list[str] = []
    i = 0
    while i < len(tokens):
        lido = _ler_numero(tokens, i)
        if lido is None:
            saida.append(tokens[i])
            i += 1
            continue
        valor, fim = lido
        palavras = tokens[i:fim]
        i = fim
        # O multiplicador dito fica dito: «duzentos e cinquenta mil» sai como
        # `250 mil`, que e a forma escrita que o passo 3 le como preco. Sem
        # isto, «ate duzentos e cinquenta mil» dava `ate 250000`, um numero
        # solto sem multiplicador, e o tecto perdia-se.
        if palavras[-1] in ("milhao", "milhoes") and valor % 1_000_000 == 0:
            saida.extend((str(valor // 1_000_000), "milhoes"))
        elif palavras[-1] == "mil" and valor % 1_000 == 0:
            saida.extend((str(valor // 1_000), "mil"))
        else:
            saida.append(str(valor))
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
    valor: int  # em Kz, ja multiplicado
    tem_multiplicador: bool
    moeda: str | None  # "AOA", codigo estrangeiro, ou None
    fim: int


def _ler_preco(tokens: Sequence[str], inicio: int) -> _Preco | None:
    """`NUM [mult] [moeda]` a comecar em `inicio`, ou `None`."""
    if inicio >= len(tokens) or not tokens[inicio].isdigit():
        return None
    valor = int(tokens[inicio])
    i = inicio + 1
    multiplicador = False
    if i < len(tokens) and tokens[i] in MULTIPLICADORES:
        valor *= MULTIPLICADORES[tokens[i]]
        multiplicador = True
        i += 1
    moeda: str | None = None
    if i < len(tokens) and tokens[i] in MOEDA_AOA:
        moeda = "AOA"
        i += 1
    elif i < len(tokens) and tokens[i] in MOEDAS_ESTRANGEIRAS:
        moeda = MOEDAS_ESTRANGEIRAS[tokens[i]]
        i += 1
    return _Preco(valor, multiplicador, moeda, i)


def _e_preco(preco: _Preco) -> bool:
    return preco.tem_multiplicador or preco.moeda is not None


def _verbo(tokens: Sequence[str], inicio: int, verbos: tuple[tuple[str, ...], ...]) -> int:
    """O comprimento do verbo de limite em `inicio`, ou 0."""
    for verbo in verbos:
        if tuple(tokens[inicio : inicio + len(verbo)]) == verbo:
            return len(verbo)
    return 0


def _moeda_prefixada(tokens: Sequence[str], inicio: int) -> str | None:
    """`usd 300`, `$300` (o passo 1 da `usd 300`): a moeda antes do numero."""
    token = tokens[inicio] if inicio < len(tokens) else ""
    if token in MOEDAS_ESTRANGEIRAS and inicio + 1 < len(tokens) and tokens[inicio + 1].isdigit():
        return MOEDAS_ESTRANGEIRAS[token]
    return None


def extrair_restricoes(tokens: Sequence[str]) -> tuple[Restricoes, list[str]]:
    """Passo 3: as restricoes de preco e os *tokens* que sobram.

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
                if b is not None and (_e_preco(a) or _e_preco(b)):
                    valor_a = a.valor
                    if not a.tem_multiplicador and b.tem_multiplicador:
                        valor_a *= b.valor // int(tokens[a.fim + 1])
                    moeda = a.moeda or b.moeda
                    if moeda not in (None, "AOA"):
                        estrangeira = moeda
                    else:
                        minimo = min(valor_a, b.valor) * MINOR_POR_KZ
                        maximo = max(valor_a, b.valor) * MINOR_POR_KZ
                    i = b.fim
                    continue
        estrangeira_antes = _moeda_prefixada(tokens, i)
        if estrangeira_antes is not None:
            estrangeira = estrangeira_antes
            i += 2
            continue
        n_max = _verbo(tokens, i, VERBOS_DE_MAXIMO)
        n_min = 0 if n_max else _verbo(tokens, i, VERBOS_DE_MINIMO)
        salto = n_max or n_min
        preco = _ler_preco(tokens, i + salto)
        if preco is not None and _e_preco(preco):
            if preco.moeda not in (None, "AOA"):
                estrangeira = preco.moeda
            elif n_max:
                maximo = preco.valor * MINOR_POR_KZ
            elif n_min:
                minimo = preco.valor * MINOR_POR_KZ
            else:
                alvo = preco.valor * MINOR_POR_KZ
            i = preco.fim
            continue
        resto.append(tokens[i])
        i += 1
    if estrangeira is not None:
        # Um valor noutra moeda nao se converte aqui: nenhum tecto, pergunta-se.
        return Restricoes(moeda=estrangeira), resto
    return Restricoes(maximo, minimo, alvo), resto
