"""Padroes de deteccao, por classe.

A classe importa tanto como o padrao: `ci/secrets-allow.yaml` permite **classes
por area**, e nao areas inteiras. Um `.env.example` pode conter placeholders e
exemplos; nao pode conter uma chave de API com forma real.
"""

from __future__ import annotations

import dataclasses
import math
import re

#: Classes de achado. Sao o vocabulario que `ci/secrets-allow.yaml` usa.
CLASSES = ("chave_api", "chave_privada", "credencial_em_url", "atribuicao", "digests")


@dataclasses.dataclass(frozen=True)
class Padrao:
    nome: str
    classe: str
    expressao: re.Pattern[str]
    razao: str
    #: Entropia minima do valor capturado. `None` dispensa a verificacao, para
    #: padroes cujo prefixo ja e prova suficiente (`-----BEGIN ... KEY-----`).
    entropia_minima: float | None = None


def entropia_de_shannon(texto: str) -> float:
    """Bits por caractere. Um valor baixo indica texto, nao segredo."""
    if not texto:
        return 0.0
    total = len(texto)
    return -sum(
        (n / total) * math.log2(n / total)
        for n in (texto.count(c) for c in set(texto))
    )


#: Chaves com prefixo publicado pelo emissor. O prefixo e a prova: nenhum texto
#: normal comeca por `ghp_` seguido de 36 caracteres.
PADROES: tuple[Padrao, ...] = (
    Padrao(
        nome="openai",
        classe="chave_api",
        expressao=re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        razao="Chave da OpenAI (prefixo `sk-`).",
    ),
    Padrao(
        nome="anthropic",
        classe="chave_api",
        expressao=re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        razao="Chave da Anthropic (prefixo `sk-ant-`).",
    ),
    Padrao(
        nome="github",
        classe="chave_api",
        expressao=re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
        razao="Token do GitHub.",
    ),
    Padrao(
        nome="aws",
        classe="chave_api",
        expressao=re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        razao="Identificador de chave de acesso da AWS.",
    ),
    Padrao(
        nome="google",
        classe="chave_api",
        expressao=re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        razao="Chave de API da Google.",
    ),
    Padrao(
        nome="slack",
        classe="chave_api",
        expressao=re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"),
        razao="Token do Slack.",
    ),
    Padrao(
        nome="stripe",
        classe="chave_api",
        expressao=re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{20,}\b"),
        razao="Chave do Stripe.",
    ),
    Padrao(
        nome="meta_token_longo",
        classe="chave_api",
        expressao=re.compile(r"\bEAA[A-Za-z0-9]{60,}\b"),
        razao=(
            "Token de acesso da Meta (prefixo `EAA`). E o que da acesso ao WABA "
            "do cliente — ver docs/tecnica/evidencia/E1_Meta_WhatsApp.md."
        ),
    ),
    Padrao(
        nome="jwt",
        classe="chave_api",
        expressao=re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        razao="JWT com tres segmentos. Pode ser de curta duracao e nao deixa de ser credencial.",
    ),
    Padrao(
        nome="chave_privada",
        classe="chave_privada",
        expressao=re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
        razao="Bloco de chave privada.",
    ),
    Padrao(
        nome="credencial_em_url",
        classe="credencial_em_url",
        expressao=re.compile(
            r"\b(?:postgres|postgresql|redis|rediss|amqp|mongodb|mysql|https?)://"
            r"[^\s:@/]+:(?P<valor>[^\s:@/]{8,})@"
        ),
        razao="Credencial embutida num URL de ligacao.",
        entropia_minima=2.5,
    ),
    Padrao(
        nome="atribuicao",
        classe="atribuicao",
        expressao=re.compile(
            # O nome pode trazer prefixo e sufixo, e **tem** de poder.
            #
            # A primeira versao usava `\b(?:...|token|...)\b`. O `_` e
            # caractere de palavra, pelo que nao existe fronteira `\b` entre
            # `_` e a palavra: `POSTGRES_PASSWORD=`, `META_ACCESS_TOKEN=` e
            # `AWS_SECRET_ACCESS_KEY=` nao batiam em nada. E a forma dominante
            # de variavel de ambiente, e e a forma que o `.env.example` deste
            # repositorio usa — o gate passava nesse ficheiro por nao o saber
            # ler, e nao por o permitir.
            #
            # A fronteira passa a ser o inicio de linha ou um caractere que nao
            # pertence a um identificador, com prefixo e sufixo opcionais. Um
            # `secretariat=` com 16 caracteres de entropia alta tambem bate, e
            # isso e falhar fechado: a entropia minima ja descarta prosa.
            r"(?i)(?:^|[^A-Za-z0-9_-])[A-Za-z0-9_-]{0,40}?"
            r"(?:api[_-]?key|secret|token|passwd|password|senha|"
            r"private[_-]?key|access[_-]?key|client[_-]?secret|auth[_-]?token)"
            r"[A-Za-z0-9_-]{0,40}?"
            r"\s*[:=]\s*[\"']?(?P<valor>[A-Za-z0-9+/=_-]{16,})[\"']?"
        ),
        razao=(
            "Atribuicao a um nome que significa segredo, com valor de entropia "
            "suficiente para nao ser uma palavra."
        ),
        entropia_minima=3.2,
    ),
)

#: Padroes que **nao** sao segredos mas tem a forma de um. Reconhecem-se para
#: poderem ser classificados como `digests` e permitidos por area, em vez de
#: serem um falso positivo sem nome.
PADROES_DIGEST: tuple[Padrao, ...] = (
    Padrao(
        nome="sha256",
        classe="digests",
        expressao=re.compile(r"\bsha256[:-][0-9a-fA-F]{64}\b"),
        razao="Digest sha256. Publico por desenho: serve para verificar, nao para autenticar.",
    ),
    Padrao(
        nome="sha512_base64",
        classe="digests",
        expressao=re.compile(r"\bsha512[.-][A-Za-z0-9+/=]{40,}\b"),
        razao="Integrity do npm ou hash do Corepack. Publicado pelo registo.",
    ),
    Padrao(
        nome="hash_de_pip",
        classe="digests",
        expressao=re.compile(r"--hash=sha256:[0-9a-f]{64}\b"),
        razao="Hash de distribuicao do pip (`--require-hashes`).",
    ),
    Padrao(
        nome="sha_de_commit",
        classe="digests",
        expressao=re.compile(r"\b[0-9a-f]{40}\b"),
        razao="SHA de commit do git.",
    ),
)
