"""A porta do spike para os dois STT (KAM-107).

**Não é a `SttProvider` de produção.** Essa é do KAM-036, que implementa o nó
`stt` e escolhe o fornecedor pela decisão deste spike; aqui o nome é o mesmo para
que a leitura dos dois tickets não se desencontre, e a forma é a mínima que o
*harness* precisa: transcrever um ficheiro com um tecto de tempo e devolver o
texto e, se a API o der, um sinal de confiança.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

TIMEOUT = "timeout"
ERRO = "erro"
TIPOS_DE_ERRO = (TIMEOUT, ERRO)


@dataclass(frozen=True)
class Transcricao:
    """O texto, e um resumo do sinal de confiança por clip.

    `confianca` é `None` quando a resposta não trouxe sinal nenhum, e esse `None`
    é o que o critério 3 lê como «a API não devolve sinal de confiança». Um zero
    seria uma confiança medida e baixa, que é outra coisa.
    """

    texto: str
    confianca: float | None = None


class ErroStt(Exception):
    """Uma chamada que não devolveu transcrição.

    A mensagem **nunca** leva o corpo da resposta: uma API pode ecoar o pedido, e
    o pedido é áudio de uma pessoa.
    """

    def __init__(self, tipo: str, detalhe: str) -> None:
        if tipo not in TIPOS_DE_ERRO:
            raise ValueError(f"tipo de erro desconhecido: {tipo!r}")
        self.tipo = tipo
        super().__init__(f"{tipo}: {detalhe}")


class SttProvider(Protocol):
    """O que o *harness* chama. Duas implementações reais e um duplo."""

    nome: str
    modelo: str

    def transcrever(self, audio: bytes, *, mime: str, idioma: str, tecto_s: float) -> Transcricao: ...
