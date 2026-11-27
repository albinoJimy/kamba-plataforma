"""Apoio aos ensaios: áudio sintético e um corpus falso que cumpre as quotas.

**Nenhuma voz.** O áudio é um tom puro gerado aqui com o módulo `wave`, com uma
frequência diferente por clip para que cada ficheiro tenha um resumo SHA-256
diferente; é o que o duplo usa para escolher a resposta. Os textos de referência
saem do `roteiro.tsv`.
"""

from __future__ import annotations

import csv
import io
import math
import struct
import tempfile
import wave
from decimal import Decimal
from pathlib import Path

from manifesto import CABECALHO, Clip, ler_roteiro
from roteiro import em_ruido, folhas


def tom(frequencia: float, segundos: float = 0.2, taxa: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        n = int(segundos * taxa)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * frequencia * i / taxa))) for i in range(n)))
    return buf.getvalue()


def corpus(n_folhas: int = 10, duracao: str = "8.0") -> list[Clip]:
    """Um clip por enunciado do roteiro: 10 falantes, 220 enunciados, quotas cumpridas."""
    roteiro = ler_roteiro()
    clips = []
    k = 1
    for f, folha in enumerate(folhas(roteiro)[:n_folhas], start=1):
        for i, e in enumerate(folha):
            clips.append(
                Clip(
                    clip_id=f"C{k:04d}",
                    tipo="enunciado",
                    falante_id=f"F{f:02d}",
                    enunciados=(e.id,),
                    ficheiro=f"F{f:02d}/C{k:04d}.ogg",
                    duracao_s=Decimal(duracao),
                    ambiente="ruidoso" if em_ruido(i) else "silencioso",
                    ref_a=e.texto,
                    ref_b=e.texto,
                    ref=e.texto,
                )
            )
            k += 1
    return clips


def escrever_manifesto(clips: list[Clip], caminho: Path) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CABECALHO)
        for c in clips:
            w.writerow([c.clip_id, c.tipo, c.falante_id, "+".join(c.enunciados), c.ficheiro, c.duracao_s, c.ambiente, c.ref_a, c.ref_b, c.ref])


def escrever_audio(clips: list[Clip], pasta: Path) -> dict[str, bytes]:
    por_clip = {}
    for n, c in enumerate(clips):
        audio = tom(200 + n)
        destino = pasta / c.ficheiro
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(audio)
        por_clip[c.clip_id] = audio
    return por_clip


def pasta_temporaria() -> tempfile.TemporaryDirectory:
    """Em `%TEMP%`, que fica fora do repositório — o *harness* recusa o contrário."""
    return tempfile.TemporaryDirectory(prefix="kamba-voz-")
