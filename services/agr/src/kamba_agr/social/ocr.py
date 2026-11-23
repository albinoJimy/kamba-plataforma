"""O OCR local dos fundos gerados (KAM-122, criterio 3): o fundo nao traz texto.

    TesseractOcr().tem_texto(imagem) -> bool

O modelo de imagem gera **so o fundo**, e um fundo com letras e texto gerado por
IA na arte — uma marca inventada, um preco que ninguem deu. Antes de um fundo
gerado entrar numa arte, o OCR le-o; com texto, regera-se ate duas vezes e
depois a arte cai no fundo do *template* (`fundos.py`).

Pela decisao do fundador de 2026-11-21 (D2, opcao B) o OCR e o **tesseract**,
pelo pacote Debian da imagem do AGR (`tesseract-ocr` e `tesseract-ocr-por`,
Apache-2.0), chamado como processo: **sem rede**, a imagem nao sai do
contentor. Sem *binding* Python — o `pytesseract` so embrulhava o mesmo
processo.

## Falha fechada

Um OCR que nao corre (binario em falta, tempo esgotado, saida nao zero)
**levanta** `OcrIndisponivelError`, e quem chama trata-o como «tem texto»: o
fundo gerado nao entra, e a arte usa o do *template*. Dizer «nao tem texto»
sem ter lido era deixar passar o que este modulo existe para travar.

## O que conta como texto (*proposta*)

Pelo menos `MINIMO_DE_CARACTERES` letras ou algarismos em palavras de dois ou
mais caracteres. Um caracter solto e o ruido tipico do tesseract sobre uma
textura; duas letras seguidas ja sao o comeco de uma palavra.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Final, Protocol

BINARIO: Final = "tesseract"
IDIOMA: Final = "por"
#: Segmentacao esparsa: procura texto em qualquer sitio da cena, sem esperar paragrafos.
SEGMENTACAO: Final = "11"
TEMPO_MAXIMO_S: Final = 20.0
MINIMO_DE_CARACTERES: Final = 3

_PALAVRA: Final = re.compile(r"[^\W_]{2,}")


class OcrIndisponivelError(RuntimeError):
    """O OCR nao leu a imagem. Quem chama trata a imagem como tendo texto."""


class VerificadorDeTexto(Protocol):
    def tem_texto(self, imagem: bytes) -> bool: ...


def ha_texto_em(lido: str, minimo: int = MINIMO_DE_CARACTERES) -> bool:
    """Se a saida do OCR tem texto: `minimo` caracteres em palavras de dois ou mais."""
    return sum(len(p) for p in _PALAVRA.findall(lido)) >= minimo


@dataclass(frozen=True)
class TesseractOcr:
    """O `VerificadorDeTexto` sobre o binario do tesseract, por `stdin`/`stdout`."""

    binario: str = BINARIO
    idioma: str = IDIOMA
    tempo_maximo_s: float = TEMPO_MAXIMO_S

    def ler(self, imagem: bytes) -> str:
        # `Popen` e `communicate`, e nao o `run`: o que se le vem no tuplo, e o
        # `log_policy` recusa qualquer `.stdout` no codigo de servico.
        comando = [self.binario, "stdin", "stdout", "-l", self.idioma, "--psm", SEGMENTACAO]
        try:
            processo = subprocess.Popen(  # noqa: S603 — binario fixo, sem shell
                comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except OSError as erro:
            raise OcrIndisponivelError(type(erro).__name__) from None
        with processo:
            try:
                lido, _erros = processo.communicate(imagem, timeout=self.tempo_maximo_s)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.communicate()
                raise OcrIndisponivelError("TimeoutExpired") from None
        if processo.returncode != 0:
            raise OcrIndisponivelError(f"tesseract saiu com {processo.returncode}")
        return lido.decode("utf-8", errors="replace")

    def tem_texto(self, imagem: bytes) -> bool:
        return ha_texto_em(self.ler(imagem))
