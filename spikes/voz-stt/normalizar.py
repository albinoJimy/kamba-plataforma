"""Normalizador do texto para o WER do spike de voz (KAM-107).

A letra do bloco («Detalhes Técnicos»): «minúsculas, sem pontuação, numerais
normalizados da mesma forma na referência e na hipótese ("mil e quinhentos" =
1500); regras versionadas». As regras desta versão são as de `VERSAO_DAS_REGRAS`,
e mudar uma delas muda a versão: um WER medido com a versão 1 não se compara com
um medido com a 2.

Regras da versão 1, por ordem:

1. NFKC e minúsculas. **Os acentos ficam**: a letra do bloco não manda tirá-los,
   e «esta»/«está» é um erro de transcrição. A consequência — uma grafia PT-BR
   («fato», «ação») conta como erro contra uma referência PT-AO — está escrita no
   `H7_Voz_STT.md` §2 como limitação, e não se resolve aqui.
2. Milhares com ponto («1.500», «15.000», «1.500,50») perdem o ponto. A vírgula
   decimal («2,5») fica dentro do *token*.
3. Horas: «14:30» e «14h30» passam a «14 h 30», e «19h00» a «19 h», como
   «19h»; «hora» e «horas» passam a «h».
4. Moeda: «kz», «kwanza(s)», «kuanza(s)», «akz» e «aoa» passam a «kz»; «%»
   passa a «por cento».
5. Pontuação fora: o texto parte-se em *tokens* de algarismos ou de letras, e
   um sinal de pontuação **separa** dois números — «custa mil. Dois sacos» são
   1000 e 2, não 1002.
6. Numerais por extenso passam a algarismos, com as duas grafias que um STT
   treinado sobretudo em PT-BR pode devolver («dezasseis»/«dezesseis»,
   «catorze»/«quatorze»). **«um», «uma» e «cento» só são numerais dentro de um
   número composto** («vinte e um», «um milhão», «cento e vinte»): sozinhos são o
   artigo e o «por cento», e contá-los punha na precisão numérica números que
   ninguém disse.

A regra do «e» é a que decide se «X e Y» é um número ou dois: compõe-se se Y for
menor do que a ordem dos zeros finais de X — «vinte e cinco» (25), «cento e
vinte» (120), «mil e quinhentos» (1500), «dois mil e cinco» (2005) —, e não se
compõe em «catorze e trinta», que fica `14 e 30`. **Isto é uma limitação
conhecida e escrita**: a hora dita «catorze e trinta» não iguala «14h30»
(`14 h 30`), e conta uma substituição. As outras limitações conhecidas — «nove e
meia» contra «9h30», «dez e um quarto» (dá 11 e «quarto»), «2,5 mil», milhares
com espaço («12 500») ou com vírgula à inglesa («7,200»), algarismos sem
multiplicador («1000 500»), «1 saco» contra «um saco», e grafias PT-BR — estão
fixadas em `tests/test_normalizar.py::TestLimitacoes` e declaradas no
`H7_Voz_STT.md` §2.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

VERSAO_DAS_REGRAS: Final = "1"

UNIDADES: Final = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezasseis": 16,
    "dezesseis": 16,
    "dezassete": 17,
    "dezessete": 17,
    "dezoito": 18,
    "dezanove": 19,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "cincoenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}

MULTIPLICADORES: Final = {"mil": 1_000, "milhao": 1_000_000, "milhoes": 1_000_000}

MOEDA: Final = frozenset({"kz", "kwanza", "kwanzas", "kuanza", "kuanzas", "akz", "aoa"})

HORA: Final = frozenset({"h", "hora", "horas"})

#: Um *token* numérico, como o WER o conta para a precisão numérica.
NUMERICO: Final = re.compile(r"\d+(?:,\d+)?")

#: O decimal com vírgula pode seguir-se («1.500,50»); outro ponto com algarismo não.
_MILHARES: Final = re.compile(r"(?<![\d,.])(\d{1,3})((?:\.\d{3})+)(?![\d]|\.\d)")
_HORAS: Final = re.compile(r"(?<!\d)(\d{1,2})\s*[:h]\s*(\d{2})(?!\d)")
#: A pontuação é um *token* de fronteira: separa dois números («custa mil. Dois
#: sacos») e sai antes de comparar.
_TOKEN: Final = re.compile(r"\d+(?:,\d+)?|[^\W\d_]+|[.,;:!?…]")
_FRONTEIRA: Final = "\x00"
#: «um»/«uma» e «cento» só são numerais dentro de um número composto: sozinhos são
#: o artigo («um saco») e o «por cento» de uma percentagem, e contá-los punha na
#: precisão numérica números que ninguém disse (achado 2 da revisão).
_SO_COMPOSTOS: Final = frozenset({"um", "uma", "cento"})


def _horas(m: re.Match[str]) -> str:
    """«14:30» e «14h30» passam a «14 h 30»; «19h00» passa a «19 h», como «19h»."""
    return f"{m.group(1)} h" if m.group(2) == "00" else f"{m.group(1)} h {m.group(2)}"


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def _valor(token: str) -> int | None:
    """O valor de um *token* que é numeral sem multiplicador, ou `None`."""
    if token.isdigit():
        return int(token)
    return UNIDADES.get(_sem_acentos(token))


def _multiplicador(token: str) -> int | None:
    return MULTIPLICADORES.get(_sem_acentos(token))


def _zeros_finais(n: int) -> int:
    z = 0
    while n and n % 10 == 0:
        n //= 10
        z += 1
    return z


def tokens_brutos(texto: str) -> list[str]:
    """Regras 1 a 5: o texto em *tokens*, ainda com os numerais por extenso."""
    t = unicodedata.normalize("NFKC", texto).lower()
    t = _MILHARES.sub(lambda m: m.group(1) + m.group(2).replace(".", ""), t)
    t = _HORAS.sub(_horas, t)
    t = t.replace("%", " por cento ")
    saida: list[str] = []
    for tok in _TOKEN.findall(t):
        chave = _sem_acentos(tok)
        if not tok[0].isalnum():
            saida.append(_FRONTEIRA)
        elif chave in MOEDA:
            saida.append("kz")
        elif chave in HORA:
            saida.append("h")
        else:
            saida.append(tok)
    return saida


def _compor(tokens: list[str]) -> list[str]:
    """Regra 6: os numerais por extenso (e os algarismos com multiplicador)."""
    saida: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        v = _valor(tokens[i])
        m = _multiplicador(tokens[i])
        if v is not None and _sem_acentos(tokens[i]) in _SO_COMPOSTOS:
            seguinte = tokens[i + 1] if i + 1 < n else ""
            # «um milhão», «uma mil», «cento e vinte»: abrem número. Sozinhos, não.
            abre = _multiplicador(seguinte) is not None if tokens[i] != "cento" else seguinte == "e"
            if not abre:
                v = None
        if v is None and m is None:
            saida.append(tokens[i])
            i += 1
            continue
        total = 0
        grupo = 0
        ultimo_mult: int | None = None
        if m is not None:
            total, ultimo_mult = m, m
        else:
            grupo = v  # type: ignore[assignment]
        i += 1
        while i < n:
            tok = tokens[i]
            m = _multiplicador(tok)
            if m is not None:
                total += max(grupo, 1) * m
                grupo = 0
                ultimo_mult = m
                i += 1
                continue
            corrente = total + grupo
            # «e» e não «é»: com o acento é o verbo («dez é pouco»), e tirá-lo
            # antes de comparar compunha «dez é cinco» em 15.
            if tok == "e" and i + 1 < n:
                seguinte = _valor(tokens[i + 1])
                mult_seguinte = _multiplicador(tokens[i + 1])
                if seguinte is not None and mult_seguinte is None and seguinte < 10 ** _zeros_finais(corrente):
                    grupo += seguinte
                    i += 2
                    continue
                break
            v = _valor(tok)
            if v is not None and ultimo_mult is not None and grupo == 0 and v < ultimo_mult:
                grupo = v
                i += 1
                continue
            break
        saida.append(str(total + grupo))
    return saida


def normalizar(texto: str) -> list[str]:
    """O texto como o WER o compara: a mesma função na referência e na hipótese."""
    return [t for t in _compor(tokens_brutos(texto)) if t != _FRONTEIRA]


def numerico(token: str) -> bool:
    return NUMERICO.fullmatch(token) is not None
