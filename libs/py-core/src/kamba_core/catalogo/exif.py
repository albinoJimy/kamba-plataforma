"""Remover EXIF, GPS e o resto dos metadados de uma imagem, em bytes (KAM-049).

O criterio 1 diz «remove EXIF/GPS **antes** de qualquer envio externo», e o
ensaio de seguranca diz «verificada em bytes». Por isso isto e um *parser* de
segmentos e nao uma biblioteca de imagem: o `kamba-core` nao tem dependencias
(`pyproject.toml`), e o que se tem de provar e que **os bytes** que saem nao
levam os metadados — nao que uma biblioteca os esconde na leitura.

## Lista branca, e nao lista negra

Fica so o que e preciso para descodificar a imagem; **sai tudo o resto**. Uma
lista negra («tira o APP1») deixava passar o proximo segmento que alguem
inventar para guardar a localizacao — e ha: o IPTC vai no APP13, o XMP vai
noutro APP1, e ha fabricantes que escrevem a seguir ao `EOI`.

| Formato | Fica | Sai |
|---|---|---|
| JPEG | `SOFn`, `DHT`, `DQT`, `DRI`, `SOS` e os dados, `DAC`, `DNL`, `APP0` (JFIF), `APP14` (Adobe: a transformada de cor), `APP2` so com `ICC_PROFILE` | `APP1` (EXIF, GPS, XMP), `APP13` (IPTC), os outros `APPn`, `COM`, e **tudo depois do `EOI`** |
| PNG | `IHDR`, `PLTE`, `IDAT`, `IEND`, `tRNS`, `gAMA`, `cHRM`, `sRGB`, `iCCP`, `sBIT`, `pHYs`, `bKGD` | `eXIf`, `tEXt`, `zTXt`, `iTXt`, `tIME` e o resto |

## O que nao se aceita

Outro formato levanta `FormatoNaoSuportado`, e a ingestao sai em
`rejeitada_qualidade` com pedido de nova foto: um formato que nao sabemos
limpar **nao sai do pais**. E uma imagem que nao se consegue percorrer ate ao
fim (segmento truncado, comprimento impossivel) levanta `ImagemInvalida`, pela
mesma razao.

## O que isto nao faz

Nao remove o que esta **nos pixeis**: um rosto, uma matricula, um numero de
telefone escrito num papel. Isso e o *gate* de transferencia (criterio 3), e e
por isso que a imagem limpa continua a precisar de destino autorizado.
"""

from __future__ import annotations

import struct
from typing import Final

ASSINATURA_JPEG: Final = b"\xff\xd8"
ASSINATURA_PNG: Final = b"\x89PNG\r\n\x1a\n"

#: Os marcadores JPEG que ficam, alem do SOI/EOI e dos que nao tem comprimento.
_JPEG_FICAM: Final = frozenset(
    {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,  # SOFn
        0xC4,  # DHT
        0xCC,  # DAC
        0xDB,  # DQT
        0xDC,  # DNL
        0xDD,  # DRI
        0xE0,  # APP0 (JFIF)
        0xEE,  # APP14 (Adobe)
    }
)
_JPEG_APP2: Final = 0xE2
_JPEG_SOS: Final = 0xDA
_JPEG_EOI: Final = 0xD9
_JPEG_ICC: Final = b"ICC_PROFILE\x00"

#: Os *chunks* PNG que ficam. Tudo o resto sai.
_PNG_FICAM: Final = frozenset(
    {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"bKGD"}
)


class FormatoNaoSuportado(ValueError):
    """Nem JPEG nem PNG: nao se sabe limpar, logo nao sai."""


class ImagemInvalida(ValueError):
    """A imagem nao se percorre ate ao fim: nao se sabe o que leva."""


def formato(corpo: bytes) -> str | None:
    """`"jpeg"`, `"png"` ou `None`, pela assinatura."""
    if corpo.startswith(ASSINATURA_JPEG):
        return "jpeg"
    if corpo.startswith(ASSINATURA_PNG):
        return "png"
    return None


def limpar_metadados(corpo: bytes) -> bytes:
    """Os bytes da imagem sem metadados. Levanta para formato ou forma invalida."""
    tipo = formato(corpo)
    if tipo == "jpeg":
        return _limpar_jpeg(corpo)
    if tipo == "png":
        return _limpar_png(corpo)
    raise FormatoNaoSuportado("so JPEG e PNG se limpam; outro formato nao sai do pais")


def _limpar_jpeg(corpo: bytes) -> bytes:
    saida = bytearray(ASSINATURA_JPEG)
    i = 2
    n = len(corpo)
    while True:
        # Um marcador e `FF` seguido de um byte que nao e `FF` (os `FF` a mais
        # sao enchimento, B.1.1.2 da norma).
        if i >= n or corpo[i] != 0xFF:
            raise ImagemInvalida("esperava-se um marcador JPEG")
        while i < n and corpo[i] == 0xFF:
            i += 1
        if i >= n:
            raise ImagemInvalida("marcador JPEG truncado")
        marcador = corpo[i]
        i += 1
        if marcador == _JPEG_EOI:
            # **Tudo o que vem depois do EOI sai.** Ha telemoveis que guardam
            # ali uma segunda imagem e os seus metadados.
            saida += b"\xff\xd9"
            return bytes(saida)
        if 0xD0 <= marcador <= 0xD7 or marcador == 0x01:
            # RSTn e TEM nao tem comprimento.
            saida += bytes((0xFF, marcador))
            continue
        if i + 2 > n:
            raise ImagemInvalida("comprimento de segmento JPEG truncado")
        (comprimento,) = struct.unpack(">H", corpo[i : i + 2])
        if comprimento < 2 or i + comprimento > n:
            raise ImagemInvalida("comprimento de segmento JPEG impossivel")
        segmento = corpo[i : i + comprimento]
        fica = marcador in _JPEG_FICAM or marcador == _JPEG_SOS or (
            marcador == _JPEG_APP2 and segmento[2:].startswith(_JPEG_ICC)
        )
        if fica:
            saida += bytes((0xFF, marcador)) + segmento
        i += comprimento
        if marcador == _JPEG_SOS:
            # Os dados entropicos: copiam-se ate ao proximo marcador que nao
            # seja enchimento (`FF 00`) nem RSTn. O JPEG progressivo tem varios
            # SOS, com DHT pelo meio, e por isso o laco continua.
            inicio = i
            while True:
                if i >= n:
                    raise ImagemInvalida("dados JPEG sem EOI")
                if corpo[i] == 0xFF and i + 1 < n:
                    seguinte = corpo[i + 1]
                    if seguinte == 0x00 or 0xD0 <= seguinte <= 0xD7:
                        i += 2
                        continue
                    if seguinte == 0xFF:
                        i += 1
                        continue
                    break
                i += 1
            saida += corpo[inicio:i]


def _limpar_png(corpo: bytes) -> bytes:
    saida = bytearray(ASSINATURA_PNG)
    i = len(ASSINATURA_PNG)
    n = len(corpo)
    while True:
        if i + 8 > n:
            raise ImagemInvalida("chunk PNG truncado")
        (comprimento,) = struct.unpack(">I", corpo[i : i + 4])
        tipo = corpo[i + 4 : i + 8]
        fim = i + 12 + comprimento
        if fim > n:
            raise ImagemInvalida("chunk PNG mais comprido do que a imagem")
        if tipo in _PNG_FICAM:
            saida += corpo[i:fim]
        i = fim
        if tipo == b"IEND":
            # Como no JPEG: o que vem depois do IEND sai.
            return bytes(saida)


def tem_metadados(corpo: bytes) -> bool:
    """`True` se a imagem leva algum segmento que o `limpar_metadados` tiraria.

    Serve o ensaio e a guarda de saida: a imagem que vai ao fornecedor de visao
    passa por aqui **outra vez**, e uma que ainda leve metadados nao sai.
    """
    try:
        return limpar_metadados(corpo) != corpo
    except (FormatoNaoSuportado, ImagemInvalida):
        return True
