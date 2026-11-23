"""O desenho da arte em JPEG (KAM-122, criterios 1 e 4): Pillow e a Noto Sans.

    RenderizadorPillow(fontes).desenhar(composicao, cores, fundo) -> bytes JPEG

O texto e o da `Composicao` (o compositor de `arte.py`), letra a letra; este
modulo so decide onde e com que tamanho. Pela decisao do fundador de
2026-11-21 (D1, opcao A) a biblioteca e o Pillow e a fonte e a **Noto Sans**,
pelo pacote Debian `fonts-noto-core` da imagem do AGR — nenhum binario de fonte
vive no repositorio.

## O fundo

| Fundo | De onde |
|---|---|
| `gerado` | a cena do gerador de fundos (`fundos.py`), recortada ao formato, **so** depois do OCR sem texto |
| `gradiente` | o *template* (liso ou gradiente), nas cores do perfil |

Sobre um fundo gerado vai sempre uma faixa escura por baixo do texto: o texto
tem de se ler, seja qual for a cena.

## O que sai, e o que nao sai

**JPEG**, o unico formato que a API do Instagram aceita (`E5`), sem EXIF: o
Pillow nao escreve metadados de captura, e o resultado passa ainda pelo
`limpar_metadados` do KAM-120. **As marcas de IA de um fundo gerado ficam**
(criterio 4: «nao remover SynthID/metadados»): a marca de agua do SynthID vive
nos pixeis e passa com a cena; os segmentos C2PA (`APP11`) e o XMP da cena
voltam a entrar no JPEG final (`preservar_marcas`), e sem XMP na cena entra o
nosso, com o `DigitalSourceType` do IPTC de composicao com media gerada. O
manifesto C2PA da cena **nao** se reassina sobre a composicao: assina o fundo,
e nao a arte — o reassinar e do adaptador real do fornecedor (credor no bloco).
"""

from __future__ import annotations

import io
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kamba_core.catalogo.exif import limpar_metadados

from .arte import Composicao, Recusa

#: Os ficheiros da Noto Sans no pacote Debian `fonts-noto-core` (trixie).
DIRECTORIA_DAS_FONTES: Final = Path("/usr/share/fonts/truetype/noto")
REGULAR: Final = "NotoSans-Regular.ttf"
NEGRITO: Final = "NotoSans-Bold.ttf"

#: O tamanho de partida de cada papel, em pixeis, no formato quadrado (*proposta*).
TAMANHOS: Final = {"nome": 84, "destaque": 54, "preco": 112, "contacto": 46}
#: O papel que leva negrito.
EM_NEGRITO: Final = frozenset({"nome", "preco"})
#: O menor tamanho a que um papel desce antes de a arte se recusar.
TAMANHO_MINIMO: Final = 28
MARGEM: Final = 72
ENTRELINHA: Final = 1.25
QUALIDADE_JPEG: Final = 90

COR_POR_OMISSAO: Final = ("#1F3A5F", "#3C6E91")

#: O XMP que entra quando a cena gerada nao traz o seu (IPTC, `DigitalSourceType`).
TIPO_DE_FONTE_DIGITAL: Final = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
)
_XMP_NS: Final = b"http://ns.adobe.com/xap/1.0/\x00"
_JUMBF: Final = b"JP"  # os segmentos APP11 do C2PA comecam por "JP"


class FontesEmFaltaError(RuntimeError):
    """A Noto Sans nao esta onde a imagem do AGR a poe: a arte nao se desenha."""


@dataclass(frozen=True)
class Fontes:
    """Os dois ficheiros de fonte. Em producao, os do pacote Debian."""

    regular: Path
    negrito: Path

    @classmethod
    def do_sistema(cls, directoria: Path = DIRECTORIA_DAS_FONTES) -> Fontes:
        fontes = cls(directoria / REGULAR, directoria / NEGRITO)
        for caminho in (fontes.regular, fontes.negrito):
            if not caminho.is_file():
                raise FontesEmFaltaError(f"fonte em falta: {caminho.name}")
        return fontes


def _rgb(cor: str) -> tuple[int, int, int]:
    return int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)


def _cores(cores: Sequence[str]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    validas = [c for c in cores if isinstance(c, str) and len(c) == 7 and c.startswith("#")]
    primeira = validas[0] if validas else COR_POR_OMISSAO[0]
    segunda = validas[1] if len(validas) > 1 else (COR_POR_OMISSAO[1] if not validas else primeira)
    return _rgb(primeira), _rgb(segunda)


def _luminancia(cor: tuple[int, int, int]) -> float:
    r, g, b = cor
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class RenderizadorPillow:
    """O `Renderizador` de `arte.py` sobre o Pillow."""

    def __init__(self, fontes: Fontes | None = None, *, carregar_fonte: Any = None) -> None:
        # `carregar_fonte(papel, tamanho)` existe para os ensaios sem a Noto
        # instalada (a fonte por omissao do Pillow); em producao e `None`.
        self._fontes = fontes
        self._carregar = carregar_fonte

    def _fonte(self, papel: str, tamanho: int) -> Any:
        from PIL import ImageFont

        if self._carregar is not None:
            return self._carregar(papel, tamanho)
        fontes = self._fontes or Fontes.do_sistema()
        caminho = fontes.negrito if papel in EM_NEGRITO else fontes.regular
        return ImageFont.truetype(str(caminho), tamanho)

    def _fundo(self, composicao: Composicao, cores: Sequence[str], fundo: bytes | None) -> Any:
        from PIL import Image, ImageOps

        largura, altura = composicao.dimensoes
        if fundo is not None:
            cena = Image.open(io.BytesIO(fundo))
            cena.load()
            return ImageOps.fit(cena.convert("RGB"), (largura, altura))
        primeira, segunda = _cores(cores)
        if composicao.template.fundo == "liso":
            return Image.new("RGB", (largura, altura), primeira)
        # Uma coluna com o gradiente e um `resize` sem interpolacao na largura:
        # o mesmo resultado que pixel a pixel, sem um milhao de escritas em Python.
        coluna = Image.new("RGB", (1, altura))
        for y in range(altura):
            t = y / max(altura - 1, 1)
            coluna.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(primeira, segunda, strict=True)))
        return coluna.resize((largura, altura), Image.Resampling.NEAREST)

    def _medidas(self, composicao: Composicao, largura_util: int) -> list[tuple[str, Any, int]]:
        """`(texto, fonte, altura da linha)` de cada linha, ja com o tamanho que cabe."""
        escala = composicao.dimensoes[0] / 1080
        saida: list[tuple[str, Any, int]] = []
        for linha in composicao.linhas:
            tamanho = round(TAMANHOS[linha.papel] * escala)
            while True:
                fonte = self._fonte(linha.papel, tamanho)
                esquerda, _topo, direita, _baixo = fonte.getbbox(linha.texto)
                if direita - esquerda <= largura_util:
                    break
                tamanho -= 2
                if tamanho < TAMANHO_MINIMO:
                    # Nunca se corta uma palavra nem um preco: a arte recusa-se.
                    raise Recusa("texto_nao_cabe")
            saida.append((linha.texto, fonte, round(tamanho * ENTRELINHA)))
        return saida

    def desenhar(self, composicao: Composicao, cores: Sequence[str], fundo: bytes | None = None) -> bytes:
        from PIL import Image, ImageDraw

        imagem = self._fundo(composicao, cores, fundo)
        largura, altura = imagem.size
        medidas = self._medidas(composicao, largura - 2 * MARGEM)
        total = sum(h for _t, _f, h in medidas)
        if total > altura - 2 * MARGEM:
            raise Recusa("texto_nao_cabe")
        topo = (altura - total) // 2
        if fundo is not None:
            # A faixa por baixo do texto: legivel sobre qualquer cena.
            faixa = Image.new("RGBA", (largura, total + MARGEM), (0, 0, 0, 150))
            base = imagem.convert("RGBA")
            base.alpha_composite(faixa, (0, max(topo - MARGEM // 2, 0)))
            imagem = base.convert("RGB")
            cor_do_texto = (255, 255, 255)
        else:
            primeira, segunda = _cores(cores)
            media = (_luminancia(primeira) + _luminancia(segunda)) / 2
            cor_do_texto = (255, 255, 255) if media < 150 else (20, 20, 20)
        desenho = ImageDraw.Draw(imagem)
        y = topo
        centro = composicao.template.alinhamento == "centro"
        for texto, fonte, altura_da_linha in medidas:
            esquerda, _t, direita, _b = fonte.getbbox(texto)
            x = (largura - (direita - esquerda)) // 2 - esquerda if centro else MARGEM - esquerda
            desenho.text((x, y), texto, font=fonte, fill=cor_do_texto)
            y += altura_da_linha
        saida = io.BytesIO()
        imagem.save(saida, "JPEG", quality=QUALIDADE_JPEG, optimize=True)
        limpa = limpar_metadados(saida.getvalue())
        return preservar_marcas(fundo, limpa) if fundo is not None else limpa


# ------------------------------------------------------------------ as marcas de IA


def _segmentos_antes_da_imagem(jpeg: bytes) -> list[tuple[int, bytes]]:
    """Os `(marcador, corpo)` dos segmentos entre o SOI e o primeiro SOF/SOS."""
    if jpeg[:2] != b"\xff\xd8":
        return []
    segmentos: list[tuple[int, bytes]] = []
    i = 2
    while i + 4 <= len(jpeg) and jpeg[i] == 0xFF:
        marcador = jpeg[i + 1]
        if marcador == 0xDA or 0xC0 <= marcador <= 0xCF and marcador not in (0xC4, 0xC8, 0xCC):
            break
        (comprimento,) = struct.unpack(">H", jpeg[i + 2 : i + 4])
        segmentos.append((marcador, jpeg[i + 4 : i + 2 + comprimento]))
        i += 2 + comprimento
    return segmentos


def _segmento(marcador: int, corpo: bytes) -> bytes:
    return bytes((0xFF, marcador)) + struct.pack(">H", len(corpo) + 2) + corpo


def xmp_de_composicao() -> bytes:
    """O XMP minimo com o `DigitalSourceType` do IPTC de uma composicao com media gerada."""
    pacote = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">'
        f"<Iptc4xmpExt:DigitalSourceType>{TIPO_DE_FONTE_DIGITAL}</Iptc4xmpExt:DigitalSourceType>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    return _XMP_NS + pacote.encode("utf-8")


def marcas_de_ia(jpeg: bytes) -> tuple[bytes, ...]:
    """Os segmentos C2PA (`APP11` JUMBF) e o XMP (`APP1`) de um JPEG, como vieram."""
    return tuple(
        _segmento(m, corpo)
        for m, corpo in _segmentos_antes_da_imagem(jpeg)
        if (m == 0xEB and corpo.startswith(_JUMBF)) or (m == 0xE1 and corpo.startswith(_XMP_NS))
    )


def preservar_marcas(cena: bytes, arte: bytes) -> bytes:
    """A `arte` com as marcas de IA da `cena` logo depois do SOI.

    O EXIF da cena **nao** entra (so o C2PA e o XMP). Sem XMP na cena, entra o
    nosso (`xmp_de_composicao`): a arte leva sempre a indicacao de media gerada.
    """
    marcas = list(marcas_de_ia(cena))
    if not any(m[1] == 0xE1 for m in marcas):
        marcas.append(_segmento(0xE1, xmp_de_composicao()))
    return arte[:2] + b"".join(marcas) + arte[2:]
