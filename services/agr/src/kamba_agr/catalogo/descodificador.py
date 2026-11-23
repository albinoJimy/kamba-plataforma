"""O `Descodificador` do KAM-049 sobre o Pillow (KAM-231, criterio 2).

**A biblioteca e decisao do fundador**: o Pillow foi aprovado no KAM-122
(2026-11-21, D1 opcao A), e a licenca que o gate 11 compara e a `MIT-CMU` do
`pillow` 13.0.0 (`ci/licenses.yaml`). Este modulo nao abre excepcao nominal:
usa o mesmo pin do `services/agr/requirements/runtime.in`.

## O que entra e o que sai

Entram os bytes **ja limpos** pelo `exif.limpar_metadados` da etapa 1 do
pipeline: o EXIF sai antes de o descodificador os ver, e nada daqui volta a
sair do processo. Sai a matriz em tons de cinzento que o `imagem.analisar`
mede. Qualquer falha de leitura e `ImagemIlegivel`, que o pipeline grava como
`rejeitada_qualidade` com `ilegivel` — antes de qualquer custo de LLM.

## As tres barreiras, todas antes de descodificar os pixeis

| Barreira | Valor | Porque |
|---|---|---|
| So `JPEG` e `PNG` | `FORMATOS` | sao os dois que o `exif.limpar_metadados` sabe limpar; outro formato nunca chega aqui limpo |
| Pixeis declarados | `PIXEIS_MAXIMOS`, 50 MP (*proposta*) | o cabecalho le-se sem descodificar; uma «bomba» de 5 MiB que declara 100 000 x 100 000 recusa-se sem alocar nada |
| Ficheiro truncado | o omissao do Pillow (`LOAD_TRUNCATED_IMAGES` falso) | um JPEG cortado a meio e ilegivel, e nao meia imagem cinzenta |

**Nao se mexe em estado global do Pillow** (`Image.MAX_IMAGE_PIXELS`,
`ImageFile.LOAD_TRUNCATED_IMAGES`): o processo do AGR partilha-o com o desenho
das artes do social (KAM-122), e o tecto daqui e verificado a parte.

## A reducao, e porque nao muda a decisao

O `imagem.analisar` e Python puro e percorre a matriz inteira: uma foto de
12 MP eram dezenas de milhoes de operacoes por ingestao, contra o tecto de
25 s do criterio 3. Por isso o lado **menor** fica, no maximo, em
`LADO_DA_ANALISE` (512 px), pela media de area (`BOX`), que e a mesma reducao
que o `imagem.reduzir` faz a seguir; num JPEG, o `draft` pede ao libjpeg a
escala inteira mais proxima por cima, e a memoria fica na da imagem reduzida.

O `LADO_MINIMO` da recusa (320 px) fica abaixo do alvo: uma foto com o lado
menor ate 512 px chega **sem** reducao, e a decisao «pequena» e a mesma que
sobre a original. Acima disso, a nitidez ja era medida sobre 256 px, o
contraste sobre 64 e o *phash* sobre 32: todos sobre uma reducao maior do que a
daqui.
"""

from __future__ import annotations

import io
from typing import Final

from PIL import Image

from kamba_core.catalogo.imagem import ImagemIlegivel, Matriz

#: Os formatos que a etapa 1 sabe limpar (`kamba_core.catalogo.exif`).
FORMATOS: Final = ("JPEG", "PNG")

#: *Proposta*. Uma foto de telemovel tem 12 a 48 MP; acima disto recusa-se pelo
#: cabecalho, antes de descodificar.
PIXEIS_MAXIMOS: Final = 50_000_000

#: O lado menor maximo da matriz que vai ao `imagem.analisar`. Fica acima do
#: `LADO_MINIMO` (320), para a recusa por tamanho nao mudar.
LADO_DA_ANALISE: Final = 512


class DescodificadorPillow:
    """Bytes limpos (JPEG ou PNG) -> matriz em tons de cinzento, reduzida."""

    def __init__(self, *, pixeis_maximos: int = PIXEIS_MAXIMOS, lado: int = LADO_DA_ANALISE) -> None:
        self._pixeis_maximos = pixeis_maximos
        self._lado = lado

    def cinzento(self, corpo: bytes) -> Matriz:
        if not corpo:
            raise ImagemIlegivel("imagem vazia")
        try:
            with Image.open(io.BytesIO(corpo), formats=FORMATOS) as imagem:
                largura, altura = imagem.size
                if largura <= 0 or altura <= 0:
                    raise ImagemIlegivel("imagem sem dimensoes")
                if largura * altura > self._pixeis_maximos:
                    raise ImagemIlegivel("imagem com pixeis a mais")
                alvo = _alvo_com(largura, altura, self._lado)
                if imagem.format == "JPEG" and alvo != (largura, altura):
                    imagem.draft("L", alvo)
                cinzenta = imagem.convert("L")
                if cinzenta.size != alvo:
                    cinzenta = cinzenta.resize(alvo, Image.Resampling.BOX)
        except ImagemIlegivel:
            raise
        except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError) as erro:
            # `UnidentifiedImageError` e um `OSError`; um PNG com CRC errado e
            # `SyntaxError`; um JPEG truncado e `OSError`; o `Image.open` recusa
            # por si um cabecalho acima do dobro do `MAX_IMAGE_PIXELS` dele.
            raise ImagemIlegivel(f"o Pillow nao leu a imagem ({type(erro).__name__})") from None
        w, _h = cinzenta.size
        niveis = cinzenta.tobytes()
        return [niveis[i : i + w] for i in range(0, len(niveis), w)]


def _alvo_com(largura: int, altura: int, lado: int) -> tuple[int, int]:
    menor = min(largura, altura)
    if menor <= lado:
        return largura, altura
    return max(1, round(largura * lado / menor)), max(1, round(altura * lado / menor))


__all__ = ["DescodificadorPillow", "FORMATOS", "LADO_DA_ANALISE", "PIXEIS_MAXIMOS"]
