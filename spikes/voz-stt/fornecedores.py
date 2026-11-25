"""Os dois STT do spike atrás da porta (KAM-107): Groq e OpenAI.

**Nenhum ensaio deste spike chama estes *endpoints*.** Os ensaios passam um
`abrir` falso que devolve respostas fabricadas; a primeira chamada real é um acto
do operador, depois de a `Autorizacao` passar.

## O que está NÃO VERIFICADO, e se reconfirma antes da primeira chamada

Os *endpoints*, os nomes dos campos e a forma das respostas abaixo são os da
documentação pública dos dois fornecedores como o executor os conhece, **sem
releitura de fonte primária nesta sessão** — o spike não pode fazer chamadas
pagas nem ler com chave. Estado: **NÃO VERIFICADO**. Em particular:

- Groq: `response_format=verbose_json` devolve `segments[].avg_logprob`.
- OpenAI: `gpt-4o-mini-transcribe` aceita `include[]=logprobs` com
  `response_format=json` e devolve `logprobs[].logprob`.

Se a resposta real não trouxer esses campos, a transcrição continua a valer e a
`confianca` fica `None` — que é a resposta «N» do critério 3, e não um erro. Os
preços e o modelo vêm de `../../docs/tecnica/evidencia/E4_Stack_Licencas.md` §3.2 e
§3.4, consultados a 2026-10-08, e relêem-se com data (critério 6).
"""

from __future__ import annotations

import json
import math
import os
import secrets
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable, Mapping

from autorizacao import Autorizacao, EnvioRecusado
from porta import ERRO, TIMEOUT, ErroStt, Transcricao

ENDPOINT_GROQ = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELO_GROQ = "whisper-large-v3-turbo"
ENDPOINT_OPENAI = "https://api.openai.com/v1/audio/transcriptions"
MODELO_OPENAI = "gpt-4o-mini-transcribe"

#: As chaves leem-se do ambiente, postas lá pelo operador a partir do cofre. Nunca
#: de um ficheiro do repositório, e nunca impressas.
VAR_CHAVE = {"groq": "KAMBA_VOZ_CHAVE_GROQ", "openai": "KAMBA_VOZ_CHAVE_OPENAI"}

Abrir = Callable[[urllib.request.Request, float], tuple[int, bytes]]


def multipart(campos: Iterable[tuple[str, str]], nome_ficheiro: str, mime: str, conteudo: bytes) -> tuple[str, bytes]:
    """O corpo `multipart/form-data` com os campos e um ficheiro."""
    fronteira = "kamba" + secrets.token_hex(12)
    partes: list[bytes] = []
    for nome, valor in campos:
        partes.append(
            f'--{fronteira}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n{valor}\r\n'.encode()
        )
    partes.append(
        (
            f"--{fronteira}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{nome_ficheiro}\"\r\nContent-Type: {mime}\r\n\r\n"
        ).encode()
        + conteudo
        + b"\r\n"
    )
    partes.append(f"--{fronteira}--\r\n".encode())
    return f"multipart/form-data; boundary={fronteira}", b"".join(partes)


def abrir_http(pedido: urllib.request.Request, tecto_s: float) -> tuple[int, bytes]:
    """O `urlopen` de verdade. O corpo de um erro HTTP descarta-se sem ser lido.

    O `timeout` do `urllib` é por operação de *socket* e não total; o *harness*
    mede o tempo de relógio de fora e é esse que entra na latência.
    """
    try:
        with urllib.request.urlopen(pedido, timeout=tecto_s) as resposta:  # noqa: S310 (URL fixa acima)
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (socket.timeout, TimeoutError):
        raise ErroStt(TIMEOUT, f"sem resposta em {tecto_s} s") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise ErroStt(TIMEOUT, f"sem resposta em {tecto_s} s") from None
        raise ErroStt(ERRO, f"ligação falhou ({type(exc.reason).__name__})") from None


def ler_groq(obj: Mapping[str, Any]) -> Transcricao:
    """`text` e, se houver, o mínimo de `exp(avg_logprob)` pelos segmentos."""
    texto = obj.get("text")
    if not isinstance(texto, str):
        raise ErroStt(ERRO, "resposta sem texto")
    probs = [
        math.exp(s["avg_logprob"])
        for s in obj.get("segments") or []
        if isinstance(s, dict) and isinstance(s.get("avg_logprob"), (int, float)) and not isinstance(s.get("avg_logprob"), bool)
    ]
    return Transcricao(texto, min(probs) if probs else None)


def ler_openai(obj: Mapping[str, Any]) -> Transcricao:
    """`text` e, se houver, `exp` da média dos `logprob` por *token*."""
    texto = obj.get("text")
    if not isinstance(texto, str):
        raise ErroStt(ERRO, "resposta sem texto")
    lps = [
        x["logprob"]
        for x in obj.get("logprobs") or []
        if isinstance(x, dict) and isinstance(x.get("logprob"), (int, float)) and not isinstance(x.get("logprob"), bool)
    ]
    return Transcricao(texto, math.exp(sum(lps) / len(lps)) if lps else None)


@dataclass
class SttHttp:
    nome: str
    modelo: str
    endpoint: str
    campos: tuple[tuple[str, str], ...]
    ler: Callable[[Mapping[str, Any]], Transcricao]
    _chave: str = field(repr=False)
    _abrir: Abrir = field(default=abrir_http, repr=False)

    def transcrever(self, audio: bytes, *, mime: str, idioma: str, tecto_s: float) -> Transcricao:
        campos = (("model", self.modelo), ("language", idioma)) + self.campos
        tipo, corpo = multipart(campos, "clip.ogg", mime, audio)
        pedido = urllib.request.Request(
            self.endpoint,
            data=corpo,
            method="POST",
            headers={"Authorization": f"Bearer {self._chave}", "Content-Type": tipo},
        )
        estado, resposta = self._abrir(pedido, tecto_s)
        if estado != 200:
            raise ErroStt(ERRO, f"HTTP {estado}")
        try:
            obj = json.loads(resposta)
        except ValueError:
            raise ErroStt(ERRO, "resposta ilegível") from None
        if not isinstance(obj, dict):
            raise ErroStt(ERRO, "resposta sem objecto")
        return self.ler(obj)


_FICHAS = {
    "groq": (MODELO_GROQ, ENDPOINT_GROQ, (("response_format", "verbose_json"), ("temperature", "0")), ler_groq),
    "openai": (MODELO_OPENAI, ENDPOINT_OPENAI, (("response_format", "json"), ("include[]", "logprobs")), ler_openai),
}

FORNECEDORES = tuple(_FICHAS)


def construir(
    nome: str,
    autorizacao: Autorizacao,
    falantes: Iterable[str],
    *,
    ambiente: Mapping[str, str] | None = None,
    abrir: Abrir = abrir_http,
    hoje: date | None = None,
) -> SttHttp:
    """Um STT real, **só** depois de a autorização passar para estes falantes."""
    if nome not in _FICHAS:
        raise ValueError(f"fornecedor desconhecido: {nome!r} (há {', '.join(FORNECEDORES)})")
    autorizacao.exigir(nome, falantes, hoje)
    env = os.environ if ambiente is None else ambiente
    chave = env.get(VAR_CHAVE[nome], "")
    if not chave.strip():
        raise EnvioRecusado([f"{VAR_CHAVE[nome]} vazia: a chave vem do cofre para o ambiente"])
    modelo, endpoint, campos, ler = _FICHAS[nome]
    return SttHttp(nome, modelo, endpoint, campos, ler, chave, abrir)
