"""WER e precisão numérica do spike de voz (KAM-107).

O WER é a distância de edição em palavras entre a referência e a hipótese, as
duas pela mesma `normalizar.normalizar`, a dividir pelo número de palavras da
referência: `(S + D + I) / N`.

**O WER de um conjunto é micro, e não a média dos WER por clip** (leitura
proposta, escrita no `H7_Voz_STT.md` §2): somam-se os erros e as palavras de
todos os clips e divide-se uma vez. A média por clip daria a um clip de cinco
palavras o mesmo peso que a um de sessenta.

**Precisão numérica** (leitura proposta, mesma secção): dos *tokens* numéricos
da referência, a fracção que o alinhamento dá como acerto. Um número inventado
pela hipótese onde a referência não tem nenhum não entra no denominador; conta-se
à parte, em `insercoes_numericas`, para que não desapareça.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from normalizar import normalizar, numerico

ACERTO = "="
SUBSTITUICAO = "S"
OMISSAO = "D"
INSERCAO = "I"


@dataclass(frozen=True)
class Alinhamento:
    """O resultado de alinhar uma referência com uma hipótese."""

    operacoes: tuple[tuple[str, str | None, str | None], ...]

    def _conta(self, op: str) -> int:
        return sum(1 for o, _, _ in self.operacoes if o == op)

    @property
    def substituicoes(self) -> int:
        return self._conta(SUBSTITUICAO)

    @property
    def omissoes(self) -> int:
        return self._conta(OMISSAO)

    @property
    def insercoes(self) -> int:
        return self._conta(INSERCAO)

    @property
    def erros(self) -> int:
        return self.substituicoes + self.omissoes + self.insercoes

    @property
    def n_referencia(self) -> int:
        return sum(1 for o, r, _ in self.operacoes if o != INSERCAO)

    @property
    def wer(self) -> float:
        if self.n_referencia == 0:
            raise ValueError("referência vazia: o WER não está definido")
        return self.erros / self.n_referencia

    @property
    def numericos_na_referencia(self) -> int:
        return sum(1 for o, r, _ in self.operacoes if o != INSERCAO and r is not None and numerico(r))

    @property
    def numericos_certos(self) -> int:
        return sum(1 for o, r, _ in self.operacoes if o == ACERTO and r is not None and numerico(r))

    @property
    def insercoes_numericas(self) -> int:
        return sum(1 for o, _, h in self.operacoes if o == INSERCAO and h is not None and numerico(h))


def alinhar_tokens(ref: list[str], hip: list[str]) -> Alinhamento:
    """Levenshtein com recuo. Em empate, diagonal, depois omissão, depois inserção."""
    n, m = len(ref), len(hip)
    custo = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        custo[i][0] = i
    for j in range(1, m + 1):
        custo[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = custo[i - 1][j - 1] + (0 if ref[i - 1] == hip[j - 1] else 1)
            custo[i][j] = min(diag, custo[i - 1][j] + 1, custo[i][j - 1] + 1)
    ops: list[tuple[str, str | None, str | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            igual = ref[i - 1] == hip[j - 1]
            if custo[i][j] == custo[i - 1][j - 1] + (0 if igual else 1):
                ops.append((ACERTO if igual else SUBSTITUICAO, ref[i - 1], hip[j - 1]))
                i, j = i - 1, j - 1
                continue
        if i > 0 and custo[i][j] == custo[i - 1][j] + 1:
            ops.append((OMISSAO, ref[i - 1], None))
            i -= 1
            continue
        ops.append((INSERCAO, None, hip[j - 1]))
        j -= 1
    ops.reverse()
    return Alinhamento(tuple(ops))


def alinhar(referencia: str, hipotese: str) -> Alinhamento:
    """As duas pela mesma normalização, e depois o alinhamento."""
    return alinhar_tokens(normalizar(referencia), normalizar(hipotese))


@dataclass(frozen=True)
class Agregado:
    clips: int
    palavras: int
    erros: int
    numericos: int
    numericos_certos: int
    insercoes_numericas: int

    @property
    def wer(self) -> float | None:
        return None if self.palavras == 0 else self.erros / self.palavras

    @property
    def precisao_numerica(self) -> float | None:
        return None if self.numericos == 0 else self.numericos_certos / self.numericos


def agregar(alinhamentos: Iterable[Alinhamento]) -> Agregado:
    """O WER micro e a precisão numérica de um conjunto de clips."""
    lista = list(alinhamentos)
    return Agregado(
        clips=len(lista),
        palavras=sum(a.n_referencia for a in lista),
        erros=sum(a.erros for a in lista),
        numericos=sum(a.numericos_na_referencia for a in lista),
        numericos_certos=sum(a.numericos_certos for a in lista),
        insercoes_numericas=sum(a.insercoes_numericas for a in lista),
    )
