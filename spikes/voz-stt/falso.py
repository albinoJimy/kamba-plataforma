"""O duplo determinístico da porta, para ensaiar o *harness* sem rede.

Responde pelo resumo SHA-256 do áudio, avança um relógio falso pela latência que
lhe disserem e falha onde lhe disserem. Não lê o áudio de outra forma: não há
nada de uma voz que ele precise de ouvir, porque os ensaios não usam voz.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Mapping

from porta import TIMEOUT, ErroStt, Transcricao


class RelogioFalso:
    """Um `time.monotonic` que só anda quando alguém o manda andar."""

    def __init__(self, inicio: float = 1000.0) -> None:
        self.agora = inicio

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        if segundos < 0:
            raise ValueError("o relógio não anda para trás")
        self.agora += segundos


def resumo(audio: bytes) -> str:
    return hashlib.sha256(audio).hexdigest()


@dataclass
class SttFalso:
    respostas: Mapping[str, str]
    relogio: RelogioFalso
    latencia_s: Callable[[bytes], float] = lambda audio: 0.5
    confiancas: Mapping[str, float] = field(default_factory=dict)
    falhas: Mapping[str, str] = field(default_factory=dict)
    nome: str = "falso"
    modelo: str = "falso-1"
    chamadas: list[tuple[str, str, str]] = field(default_factory=list)

    def transcrever(self, audio: bytes, *, mime: str, idioma: str, tecto_s: float) -> Transcricao:
        chave = resumo(audio)
        self.chamadas.append((chave, mime, idioma))
        demora = self.latencia_s(audio)
        if demora > tecto_s:
            self.relogio.avancar(tecto_s)
            raise ErroStt(TIMEOUT, f"sem resposta em {tecto_s} s")
        self.relogio.avancar(demora)
        if chave in self.falhas:
            raise ErroStt(self.falhas[chave], "falha encenada")
        if chave not in self.respostas:
            raise ErroStt("erro", "clip desconhecido do duplo")
        return Transcricao(self.respostas[chave], self.confiancas.get(chave))
