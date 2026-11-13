"""Remover EXIF, GPS e o resto dos metadados de uma imagem, em bytes (KAM-049).

O criterio 1 diz «remove EXIF/GPS **antes** de qualquer envio externo», e o
ensaio de seguranca diz «verificada em bytes». Por isso isto e um *parser* de
segmentos e nao uma biblioteca de imagem: o `kamba-core` nao tem dependencias
(`pyproject.toml`), e o que se tem de provar e que **os bytes** que saem nao
levam os metadados — nao que uma biblioteca os esconde na leitura.

## Lista branca por marcador **e por conteudo**

Fica so o que e preciso para descodificar a imagem; **sai tudo o resto**. Uma
lista negra («tira o APP1») deixava passar o proximo segmento que alguem
inventar para guardar a localizacao — e ha: o IPTC vai no APP13, o XMP vai
noutro APP1, e ha fabricantes que escrevem a seguir ao `EOI`.

**E a lista branca e tambem de conteudo.** A primeira versao deixava ficar um
segmento pelo marcador, e a revisao adversarial pos GPS em seis sitios que
passavam: um APP0 com `Exif` em vez de `JFIF`, um APP0 `JFXX` com uma miniatura
que leva o seu proprio EXIF, texto a mais no APP14, texto num perfil ICC, bytes
a mais no fim de um DQT, e o nome de um `iCCP`. Hoje:

| Formato | Fica | Sai |
|---|---|---|
| JPEG | `SOFn`, `DHT`, `DQT`, `DRI`, `DAC`, `DNL` e `SOS`, **cada um com o comprimento exacto que a sua estrutura da**; o APP0 `JFIF` **reescrito** sem miniatura; o APP14 `Adobe` so com os seus doze bytes | todos os outros `APPn` (EXIF, GPS, XMP, IPTC, ICC, `JFXX`), `COM`, qualquer marcador desconhecido, e **tudo depois do `EOI`** |
| PNG | `IHDR`, `PLTE`, `IDAT`, `IEND`, `tRNS`, `gAMA`, `cHRM`, `sRGB`, `sBIT`, `pHYs`, `bKGD`, os de comprimento fixo com o comprimento certo | `eXIf`, `tEXt`, `zTXt`, `iTXt`, `tIME`, `iCCP` (leva um nome de texto) e o resto, e tudo depois do `IEND` |

Um segmento que fica mas nao tem a forma da sua estrutura **nao se corta**:
levanta `ImagemInvalida`, porque os bytes a mais de um DQT nao se sabe o que
sao.

O perfil ICC sai: leva texto (`desc`, `cprt`) e a cor de uma foto de produto
nao depende dele para a extraccao.

## A segunda guarda e independente

`tem_metadados` **nao** e `limpar(x) != x`: e outro percurso dos mesmos bytes,
que so aceita a forma minima que o `limpar_metadados` produz. A primeira versao
era o mesmo *parser* chamado duas vezes, e falhava exactamente nos mesmos casos.

## O que nao se aceita

Outro formato levanta `FormatoNaoSuportado`, e a ingestao sai em
`rejeitada_qualidade` com pedido de nova foto: um formato que nao sabemos
limpar **nao sai do pais**.

## O que isto nao faz

Nao remove o que esta **nos pixeis**: um rosto, uma matricula, um numero de
telefone escrito num papel. Isso e o *gate* de transferencia (criterio 3), e e
por isso que a imagem limpa continua a precisar de destino autorizado.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from typing import Final

ASSINATURA_JPEG: Final = b"\xff\xd8"
ASSINATURA_PNG: Final = b"\x89PNG\r\n\x1a\n"

_SOF: Final = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_DHT: Final = 0xC4
_DAC: Final = 0xCC
_DQT: Final = 0xDB
_DNL: Final = 0xDC
_DRI: Final = 0xDD
_SOS: Final = 0xDA
_EOI: Final = 0xD9
_APP0: Final = 0xE0
_APP14: Final = 0xEE

_JFIF: Final = b"JFIF\x00"
#: O APP0 que sai: `JFIF\0`, versao (2), unidades (1), densidades (2+2) e a
#: miniatura a zero (1+1). Catorze bytes, sempre.
_TAMANHO_DO_JFIF: Final = 14
_ADOBE: Final = b"Adobe"
_TAMANHO_DO_ADOBE: Final = 12

#: Os *chunks* PNG que ficam, com o comprimento que tem de ter (`None` = livre,
#: mas so dados de imagem ou numeros).
_PNG_FICAM: Final[dict[bytes, tuple[int, ...] | None]] = {
    b"IHDR": (13,),
    b"PLTE": None,
    b"IDAT": None,
    b"IEND": (0,),
    b"tRNS": None,
    b"gAMA": (4,),
    b"cHRM": (32,),
    b"sRGB": (1,),
    b"sBIT": (1, 2, 3, 4),
    b"pHYs": (9,),
    b"bKGD": (1, 2, 6),
}


class FormatoNaoSuportado(ValueError):
    """Nem JPEG nem PNG: nao se sabe limpar, logo nao sai."""


class ImagemInvalida(ValueError):
    """A imagem nao se percorre ate ao fim, ou um segmento nao tem a sua forma."""


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


# ---------------------------------------------------------------- JPEG


def _segmentos_jpeg(corpo: bytes) -> Iterator[tuple[int, bytes, bytes]]:
    """`(marcador, corpo do segmento, dados entropicos a seguir)` ate ao EOI.

    O corpo nao leva os dois bytes do comprimento. O EOI sai como
    `(0xD9, b"", resto)`, com o que vem depois dele em `resto`.
    """
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
        if marcador == _EOI:
            yield marcador, b"", corpo[i:]
            return
        if 0xD0 <= marcador <= 0xD7 or marcador == 0x01:
            # RSTn e TEM nao tem comprimento.
            yield marcador, b"", b""
            continue
        if i + 2 > n:
            raise ImagemInvalida("comprimento de segmento JPEG truncado")
        (comprimento,) = struct.unpack(">H", corpo[i : i + 2])
        if comprimento < 2 or i + comprimento > n:
            raise ImagemInvalida("comprimento de segmento JPEG impossivel")
        segmento = corpo[i + 2 : i + comprimento]
        i += comprimento
        dados = b""
        if marcador == _SOS:
            # Os dados entropicos: ate ao proximo marcador que nao seja
            # enchimento (`FF 00`) nem RSTn. O JPEG progressivo tem varios SOS,
            # com DHT pelo meio, e por isso o laco continua.
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
            dados = corpo[inicio:i]
        yield marcador, segmento, dados


def _exacto(marcador: int, corpo: bytes) -> bool:
    """O segmento tem o comprimento exacto que a sua estrutura da."""
    if marcador in _SOF:
        return len(corpo) >= 6 and len(corpo) == 6 + 3 * corpo[5]
    if marcador == _SOS:
        return len(corpo) >= 1 and len(corpo) == 1 + 2 * corpo[0] + 3
    if marcador in (_DRI, _DNL):
        return len(corpo) == 2
    if marcador == _DAC:
        return len(corpo) % 2 == 0 and len(corpo) > 0
    if marcador == _DQT:
        i = 0
        while i < len(corpo):
            i += 1 + 64 * (1 + (corpo[i] >> 4))
        return i == len(corpo) and len(corpo) > 0
    if marcador == _DHT:
        i = 0
        while i < len(corpo):
            if i + 17 > len(corpo):
                return False
            i += 17 + sum(corpo[i + 1 : i + 17])
        return i == len(corpo) and len(corpo) > 0
    return False


_ESTRUTURAIS: Final = _SOF | {_DHT, _DAC, _DQT, _DNL, _DRI, _SOS}


def _segmento(marcador: int, corpo: bytes) -> bytes:
    return bytes((0xFF, marcador)) + struct.pack(">H", len(corpo) + 2) + corpo


def _limpar_jpeg(corpo: bytes) -> bytes:
    saida = bytearray(ASSINATURA_JPEG)
    for marcador, segmento, dados in _segmentos_jpeg(corpo):
        if marcador == _EOI:
            # **Tudo o que vem depois do EOI sai.** Ha telemoveis que guardam
            # ali uma segunda imagem e os seus metadados.
            saida += b"\xff\xd9"
            return bytes(saida)
        if not segmento and marcador != _SOS and (0xD0 <= marcador <= 0xD7 or marcador == 0x01):
            saida += bytes((0xFF, marcador))
            continue
        if marcador in _ESTRUTURAIS:
            if not _exacto(marcador, segmento):
                raise ImagemInvalida(f"segmento JPEG 0x{marcador:02X} sem a forma da sua estrutura")
            saida += _segmento(marcador, segmento) + dados
        elif marcador == _APP0 and segmento.startswith(_JFIF) and len(segmento) >= 12:
            # Reescrito: versao, unidades e densidades, e a miniatura a zero.
            saida += _segmento(_APP0, _JFIF + segmento[5:12] + b"\x00\x00")
        elif marcador == _APP14 and segmento.startswith(_ADOBE) and len(segmento) == _TAMANHO_DO_ADOBE:
            saida += _segmento(_APP14, segmento)
        # Tudo o resto sai: APP1..APP15 (menos o APP14 Adobe), o APP0 que nao e
        # JFIF, o COM e os marcadores que nao se conhecem.
    raise ImagemInvalida("JPEG sem EOI")  # pragma: no cover — o gerador levanta antes


def _jpeg_minimo(corpo: bytes) -> bool:
    for marcador, segmento, dados in _segmentos_jpeg(corpo):
        if marcador == _EOI:
            return dados == b""
        if not segmento and (0xD0 <= marcador <= 0xD7 or marcador == 0x01):
            continue
        if marcador in _ESTRUTURAIS:
            if not _exacto(marcador, segmento):
                return False
        elif marcador == _APP0:
            if not (segmento.startswith(_JFIF) and len(segmento) == _TAMANHO_DO_JFIF and segmento[-2:] == b"\x00\x00"):
                return False
        elif marcador == _APP14:
            if not (segmento.startswith(_ADOBE) and len(segmento) == _TAMANHO_DO_ADOBE):
                return False
        else:
            return False
    return False  # pragma: no cover


# ---------------------------------------------------------------- PNG


def _chunks_png(corpo: bytes) -> Iterator[tuple[bytes, bytes, bytes]]:
    """`(tipo, chunk inteiro, resto depois do IEND)`."""
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
        yield tipo, corpo[i:fim], (corpo[fim:] if tipo == b"IEND" else b"")
        i = fim
        if tipo == b"IEND":
            return


def _png_fica(tipo: bytes, chunk: bytes) -> bool:
    if tipo not in _PNG_FICAM:
        return False
    tamanhos = _PNG_FICAM[tipo]
    comprimento = len(chunk) - 12
    if tamanhos is not None and comprimento not in tamanhos:
        raise ImagemInvalida(f"chunk PNG {tipo!r} com comprimento {comprimento}")
    return True


def _limpar_png(corpo: bytes) -> bytes:
    saida = bytearray(ASSINATURA_PNG)
    for tipo, chunk, _resto in _chunks_png(corpo):
        if _png_fica(tipo, chunk):
            saida += chunk
        if tipo == b"IEND":
            # Como no JPEG: o que vem depois do IEND sai.
            return bytes(saida)
    raise ImagemInvalida("PNG sem IEND")  # pragma: no cover


def _png_minimo(corpo: bytes) -> bool:
    for tipo, chunk, resto in _chunks_png(corpo):
        if not _png_fica(tipo, chunk):
            return False
        if tipo == b"IEND":
            return resto == b""
    return False  # pragma: no cover


def tem_metadados(corpo: bytes) -> bool:
    """`True` se a imagem nao for **exactamente** da forma minima que sai daqui.

    Serve o ensaio e a guarda de saida: a imagem que vai ao fornecedor de visao
    passa por aqui **outra vez**, por um percurso diferente do da limpeza, e uma
    que ainda leve um segmento fora da forma minima nao sai.
    """
    try:
        tipo = formato(corpo)
        if tipo == "jpeg":
            return not _jpeg_minimo(corpo)
        if tipo == "png":
            return not _png_minimo(corpo)
    except ImagemInvalida:
        return True
    return True
