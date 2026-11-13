"""Qualidade e *hash* perceptual de uma foto de produto (KAM-049, criterios 1 e 2).

**O que esta aqui e o calculo, e nao a descodificacao.** O `kamba-core` nao tem
dependencias, e descodificar um JPEG em Python puro nao e trabalho deste
ticket. A fronteira e a porta `Descodificador`: recebe os bytes **ja limpos** e
devolve a imagem em tons de cinzento, como matriz de linhas. Tudo o que vem
depois — o *phash*, a nitidez, o contraste e a decisao — e funcao pura daqui, e
e o que os ensaios medem com matrizes sinteticas.

O descodificador de producao nao existe ainda e **nao ha omissao**: o
`ServicoDeIngestao` exige-o no construtor. Sem ele nao se avalia a qualidade, e
sem qualidade avaliada nao se gasta LLM (criterio 2). O credor esta no bloco do
ticket.

## Os tres numeros, todos *proposta*

| Limiar | Valor | O que recusa |
|---|---|---|
| `LADO_MINIMO` | 320 px | foto pequena demais para ler marca e etiqueta |
| `NITIDEZ_MINIMA` | 60,0 | variancia do laplaciano abaixo disto: desfocada |
| `CONTRASTE_MINIMO` | 12,0 | desvio-padrao dos niveis de cinzento: imagem lisa, sem produto visivel |

Calibram-se contra o conjunto de avaliacao do bloco (>= 50 fotos), que nao
existe ainda. Ate la sao valores de partida da literatura de deteccao de
desfoque (NAO VERIFICADO contra fotos de PME angolanas).

## O *phash*

O classico: reduzir a 32x32, DCT bidimensional, ficar com os 8x8 coeficientes
de frequencia mais baixa, e cada bit diz se o coeficiente esta acima da mediana
(sem o termo DC). Oito bytes, que e o `CHECK (octet_length(phash) = 8)` da
`catalogo_ai`. Duas fotos do mesmo produto, uma delas recomprimida ou reduzida, dao o
mesmo *hash* ou um a poucos bits; o criterio pede «`phash` igual», e e a
igualdade que a ingestao pergunta.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

#: Uma imagem em tons de cinzento: linhas de niveis entre 0 e 255.
Matriz = Sequence[Sequence[float]]

LADO_MINIMO: Final = 320
NITIDEZ_MINIMA: Final = 60.0
CONTRASTE_MINIMO: Final = 12.0

#: O lado da reducao antes do laplaciano. Sem tecto, uma foto de 12 MP eram 12
#: milhoes de operacoes em Python puro por ingestao.
LADO_DA_NITIDEZ: Final = 256

_LADO_DO_PHASH: Final = 32
_LADO_DO_BLOCO: Final = 8

MOTIVO_PEQUENA: Final = "pequena"
MOTIVO_DESFOCADA: Final = "desfocada"
MOTIVO_SEM_PRODUTO: Final = "sem_produto"


class ImagemIlegivel(ValueError):
    """O descodificador nao conseguiu ler a imagem."""


@runtime_checkable
class Descodificador(Protocol):
    """Bytes limpos -> matriz em tons de cinzento. Levanta `ImagemIlegivel`."""

    def cinzento(self, corpo: bytes) -> Matriz: ...


@dataclass(frozen=True)
class Analise:
    """O que a etapa 2 sabe de uma foto."""

    largura: int
    altura: int
    nitidez: float
    contraste: float
    phash: bytes

    @property
    def motivo_de_recusa(self) -> str | None:
        """O primeiro motivo de recusa, ou `None` se a foto serve."""
        if min(self.largura, self.altura) < LADO_MINIMO:
            return MOTIVO_PEQUENA
        if self.contraste < CONTRASTE_MINIMO:
            return MOTIVO_SEM_PRODUTO
        if self.nitidez < NITIDEZ_MINIMA:
            return MOTIVO_DESFOCADA
        return None


def _dimensoes(matriz: Matriz) -> tuple[int, int]:
    altura = len(matriz)
    if altura == 0 or len(matriz[0]) == 0:
        raise ImagemIlegivel("imagem vazia")
    largura = len(matriz[0])
    if any(len(linha) != largura for linha in matriz):
        raise ImagemIlegivel("linhas de comprimento diferente")
    return largura, altura


def reduzir(matriz: Matriz, lado: int) -> list[list[float]]:
    """Reduz por media de area a `lado` x `lado` (amplia por repeticao se for menor)."""
    largura, altura = _dimensoes(matriz)
    saida: list[list[float]] = []
    for y in range(lado):
        y0 = y * altura // lado
        y1 = max(y0 + 1, (y + 1) * altura // lado)
        linha: list[float] = []
        for x in range(lado):
            x0 = x * largura // lado
            x1 = max(x0 + 1, (x + 1) * largura // lado)
            soma = 0.0
            for yy in range(y0, y1):
                fila = matriz[yy]
                for xx in range(x0, x1):
                    soma += fila[xx]
            linha.append(soma / ((y1 - y0) * (x1 - x0)))
        saida.append(linha)
    return saida


def _dct_1d(valores: Sequence[float], cossenos: Sequence[Sequence[float]]) -> list[float]:
    return [sum(v * c for v, c in zip(valores, linha_k)) for linha_k in cossenos]


def phash(matriz: Matriz) -> bytes:
    """O *hash* perceptual de 64 bits, em oito bytes."""
    n = _LADO_DO_PHASH
    pequena = reduzir(matriz, n)
    cossenos = [[math.cos(math.pi * k * (2 * i + 1) / (2 * n)) for i in range(n)] for k in range(_LADO_DO_BLOCO)]
    # So os primeiros oito coeficientes de cada eixo interessam: as linhas
    # primeiro, depois as colunas do resultado.
    por_linha = [_dct_1d(linha, cossenos) for linha in pequena]
    bloco = [
        _dct_1d([por_linha[y][k] for y in range(n)], cossenos) for k in range(_LADO_DO_BLOCO)
    ]
    # `bloco[kx][ky]`; fica por ordem de linhas para os bits.
    coeficientes = [bloco[kx][ky] for ky in range(_LADO_DO_BLOCO) for kx in range(_LADO_DO_BLOCO)]
    sem_dc = sorted(coeficientes[1:])
    meio = len(sem_dc) // 2
    mediana = (sem_dc[meio - 1] + sem_dc[meio]) / 2
    bits = 0
    for c in coeficientes:
        bits = (bits << 1) | (1 if c > mediana else 0)
    return bits.to_bytes(8, "big")


def distancia(a: bytes, b: bytes) -> int:
    """A distancia de Hamming entre dois *phash*."""
    if len(a) != len(b):
        raise ValueError("phash de comprimentos diferentes")
    return bin(int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).count("1")


def nitidez(matriz: Matriz) -> float:
    """A variancia do laplaciano (4 vizinhos), sobre a imagem reduzida."""
    largura, altura = _dimensoes(matriz)
    lado = min(LADO_DA_NITIDEZ, largura, altura)
    if lado < 3:
        return 0.0
    m = reduzir(matriz, lado)
    valores = [
        m[y - 1][x] + m[y + 1][x] + m[y][x - 1] + m[y][x + 1] - 4 * m[y][x]
        for y in range(1, lado - 1)
        for x in range(1, lado - 1)
    ]
    media = sum(valores) / len(valores)
    return sum((v - media) ** 2 for v in valores) / len(valores)


def contraste(matriz: Matriz) -> float:
    """O desvio-padrao dos niveis, sobre a imagem reduzida."""
    largura, altura = _dimensoes(matriz)
    m = reduzir(matriz, min(64, largura, altura))
    valores = [v for linha in m for v in linha]
    media = sum(valores) / len(valores)
    return math.sqrt(sum((v - media) ** 2 for v in valores) / len(valores))


def analisar(matriz: Matriz) -> Analise:
    """A etapa 2 inteira sobre uma matriz ja descodificada."""
    largura, altura = _dimensoes(matriz)
    return Analise(
        largura=largura,
        altura=altura,
        nitidez=nitidez(matriz),
        contraste=contraste(matriz),
        phash=phash(matriz),
    )
