"""O *gate* local de minimizacao de imagem, antes de qualquer envio (KAM-120).

Corre **no anfitriao e sem chamada externa** (criterios 3 e 4), sobre os bytes
do original, e devolve ou os bytes que podem sair ou a razao por que nao saem.
Quatro passos, por esta ordem, e **cada um falha fechado**:

1. **Forma e tamanho.** So JPEG e PNG (o `limpar_metadados` do KAM-049), ate
   `TAMANHO_MAXIMO` bytes e `PIXEIS_MAXIMOS` pixeis lidos do **cabecalho**,
   antes de qualquer descodificacao: uma imagem de 60 000 x 60 000 com poucos
   *kilobytes* comprimidos e uma bomba de descompressao, e o cabecalho e o
   unico sitio onde ela se ve sem a detonar.
2. **Metadados.** `limpar_metadados` e, depois, a segunda guarda independente
   (`tem_metadados`) sobre o resultado.
3. **Lado maior <= `LADO_MAXIMO`.** Se for maior, o `Redimensionador` reduz; e
   o resultado volta aos passos 1 e 2, porque um redimensionador que escrevesse
   um APP1 punha os metadados de volta.
4. **Rostos, matriculas, documentos e ecras.** O `DetectorLocal`. Qualquer
   deteccao e recusa com pedido de outra foto; um erro do detector e
   **bloqueio**, nunca passagem.

## Recusar em vez de desfocar, e porque

O criterio 3 aceita «desfocadas/recortadas **ou** rejeitadas com pedido de
outra foto». Desfocar e reescrever pixeis, e o `kamba-core` nao tem
dependencias — nao descodifica um JPEG. **A rejeicao e a forma que se entrega**,
e e a mais segura das duas: uma desfocagem que falhe um rosto deixa-o sair, uma
recusa nao deixa sair nada.

## O que este modulo nao tem, e e dito

As duas portas — `Redimensionador` e `DetectorLocal` — **nao tem implementacao
de producao**, pela razao do `Descodificador` do KAM-049: uma biblioteca de
imagem e um detector *open-source* entram pelo inventario do `supply_chain`,
com licenca, e sao uma decisao propria. O `ServicoDeFoto` exige as duas no
construtor e **nao ha omissao**: sem detector, nenhuma foto sai. Os
**falsos negativos e positivos** do criterio 3 medem-se com o detector real,
sobre o conjunto de >= 50 imagens com rostos e >= 30 com matriculas; o que os
ensaios daqui medem e que **o *gate* respeita o que o detector disser**.

## Os limites, todos *proposta*

| Limite | Valor | Porque |
|---|---|---|
| `LADO_MAXIMO` | 2048 px | o do criterio 4 |
| `TAMANHO_MAXIMO` | 20 MiB | uma foto de telemovel de 12 MP em JPEG anda pelos 3 a 8 MiB |
| `PIXEIS_MAXIMOS` | 50 MP | acima disto nao e uma foto de telemovel |
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from ..catalogo.exif import (
    FormatoNaoSuportado,
    ImagemInvalida,
    formato,
    limpar_metadados,
    tem_metadados,
)
from . import estados

LADO_MAXIMO: Final = 2048
TAMANHO_MAXIMO: Final = 20 * 1024 * 1024
PIXEIS_MAXIMOS: Final = 50_000_000

_SOF: Final = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})


def dimensoes(corpo: bytes) -> tuple[int, int]:
    """`(largura, altura)` lidas do cabecalho, sem descodificar. Levanta `ImagemInvalida`.

    JPEG: o primeiro `SOFn`. PNG: o `IHDR`, que tem de ser o primeiro *chunk*.
    """
    tipo = formato(corpo)
    if tipo == "png":
        if len(corpo) < 24 or corpo[12:16] != b"IHDR":
            raise ImagemInvalida("PNG sem IHDR em primeiro lugar")
        largura, altura = struct.unpack(">II", corpo[16:24])
        return largura, altura
    if tipo == "jpeg":
        i = 2
        n = len(corpo)
        while i + 4 <= n:
            if corpo[i] != 0xFF:
                raise ImagemInvalida("esperava-se um marcador JPEG")
            marcador = corpo[i + 1]
            if marcador == 0xFF:
                i += 1
                continue
            if 0xD0 <= marcador <= 0xD9 or marcador == 0x01:
                i += 2
                continue
            (comprimento,) = struct.unpack(">H", corpo[i + 2 : i + 4])
            if comprimento < 2:
                raise ImagemInvalida("comprimento de segmento JPEG impossivel")
            if marcador in _SOF:
                if i + 9 > n:
                    raise ImagemInvalida("SOF truncado")
                altura, largura = struct.unpack(">HH", corpo[i + 5 : i + 9])
                return largura, altura
            i += 2 + comprimento
        raise ImagemInvalida("JPEG sem SOF")
    raise FormatoNaoSuportado("so JPEG e PNG")


@dataclass(frozen=True)
class Deteccao:
    """O que o detector local encontrou. Contagens, nunca coordenadas nem recortes."""

    rostos: int = 0
    matriculas: int = 0
    documentos: int = 0
    ecras: int = 0

    @property
    def vazia(self) -> bool:
        return self.rostos == self.matriculas == self.documentos == self.ecras == 0


@runtime_checkable
class DetectorLocal(Protocol):
    """Rostos, matriculas, documentos e ecras, no anfitriao, em CPU, sem rede."""

    def detectar(self, imagem: bytes) -> Deteccao: ...


@runtime_checkable
class Redimensionador(Protocol):
    """Reduz para que o lado maior fique <= `lado_maximo`. Devolve JPEG ou PNG."""

    def reduzir(self, imagem: bytes, lado_maximo: int) -> bytes: ...


@dataclass(frozen=True)
class Minimizada:
    """O desfecho do *gate*: os `bytes` que podem sair, ou o estado e o motivo."""

    imagem: bytes | None
    estado: str | None = None
    motivo: str | None = None

    @property
    def pode_sair(self) -> bool:
        return self.imagem is not None


def _recusa(estado: str, motivo: str) -> Minimizada:
    return Minimizada(imagem=None, estado=estado, motivo=motivo)


def _forma_que_sai(corpo: bytes) -> bytes | None:
    """Passos 1 e 2. `None` se a imagem nao tem a forma que pode sair."""
    if len(corpo) > TAMANHO_MAXIMO:
        return None
    largura, altura = dimensoes(corpo)
    if largura <= 0 or altura <= 0 or largura * altura > PIXEIS_MAXIMOS:
        return None
    limpo = limpar_metadados(corpo)
    if tem_metadados(limpo):
        return None
    return limpo


def pode_sair(corpo: bytes) -> bool:
    """A verificacao **em bytes** do corpo de um pedido (criterio 4).

    Independente do caminho que o produziu: forma minima sem metadados e lado
    maior <= `LADO_MAXIMO`. E a guarda que o servico corre sobre os bytes
    imediatamente antes de os entregar ao adaptador.
    """
    try:
        if len(corpo) > TAMANHO_MAXIMO or tem_metadados(corpo):
            return False
        largura, altura = dimensoes(corpo)
    except (FormatoNaoSuportado, ImagemInvalida):
        return False
    return 0 < largura <= LADO_MAXIMO and 0 < altura <= LADO_MAXIMO


def minimizar(corpo: bytes, detector: DetectorLocal, redimensionador: Redimensionador) -> Minimizada:
    """Os quatro passos da nota do modulo. Nunca levanta: devolve a recusa."""
    try:
        limpo = _forma_que_sai(corpo)
    except (FormatoNaoSuportado, ImagemInvalida):
        return _recusa(estados.FALHADO, estados.MOTIVO_FORMATO)
    if limpo is None:
        return _recusa(estados.FALHADO, estados.MOTIVO_FORMATO)

    # Passo 3: reduzir, e o resultado volta a passar pelos passos 1 e 2.
    if max(dimensoes(limpo)) > LADO_MAXIMO:
        try:
            reduzida = _forma_que_sai(redimensionador.reduzir(limpo, LADO_MAXIMO))
        except Exception:  # noqa: BLE001 — falha fechada: o que nao se reduz nao sai
            reduzida = None
        if reduzida is None or max(dimensoes(reduzida)) > LADO_MAXIMO:
            return _recusa(estados.BLOQUEADA_GATE, estados.MOTIVO_MINIMIZACAO)
        limpo = reduzida

    # Passo 4: o detector, **sobre os bytes que vao sair**, e nao sobre o
    # original — o que o fornecedor recebe e isto.
    try:
        deteccao = detector.detectar(limpo)
    except Exception:  # noqa: BLE001 — falha fechada: detector em baixo nao e «sem rostos»
        return _recusa(estados.BLOQUEADA_GATE, estados.MOTIVO_MINIMIZACAO)
    if not isinstance(deteccao, Deteccao):
        return _recusa(estados.BLOQUEADA_GATE, estados.MOTIVO_MINIMIZACAO)
    if not deteccao.vazia:
        return _recusa(estados.FALHADO, estados.MOTIVO_DADOS_PESSOAIS)

    if not pode_sair(limpo):  # pragma: no cover — a soma dos passos ja o garante
        return _recusa(estados.BLOQUEADA_GATE, estados.MOTIVO_MINIMIZACAO)
    return Minimizada(imagem=limpo)


__all__ = [
    "LADO_MAXIMO",
    "PIXEIS_MAXIMOS",
    "TAMANHO_MAXIMO",
    "Deteccao",
    "DetectorLocal",
    "Minimizada",
    "Redimensionador",
    "dimensoes",
    "minimizar",
    "pode_sair",
]
