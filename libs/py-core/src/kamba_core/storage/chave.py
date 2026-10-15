"""Chaves de objecto e a sua relacao com o tenant (KAM-011).

`t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}` — e mais nenhuma forma. Espelho de
`packages/core-ts/src/storage/chave.ts`: as mesmas expressoes, as mesmas
recusas, pela mesma ordem.

A validacao e por **lista fechada de caracteres**, nao por lista de caracteres
proibidos: nao ha `..`, `//`, `%2f`, espaco, maiuscula nem byte nulo que passe,
porque nenhum deles esta no alfabeto.

Uma nota que so existe deste lado: usa-se `fullmatch` e nunca `match` com `$`.
Em Python, `$` casa **antes de um `\\n` final** — `re.match(r"^a$", "a\\n")`
da verdadeiro — e uma chave terminada em mudanca de linha passava a validacao.

E outra: o que e texto confere-se com `type(x) is str`, nunca com
`isinstance`. Uma subclasse de `str` pode ter um `__format__` ou um `__eq__`
seus — passava a validacao com um valor e entrava na chave com outro. A
revisao adversarial reproduziu-o (`ANALISE-09`, A2).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from .port import (
    ChaveForaDoTenantError,
    ChaveInvalidaError,
    Ctx,
    CtxEmFaltaError,
    MetaInvalidaError,
    ObjectKey,
    TenantInvalidoError,
)

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_CANONICO = re.compile(_UUID)

#: Forma de uma classe: `snake_case` minusculo, 2 a 32 caracteres. A **lista**
#: de classes nao e deste ticket (cada consumidor traz as suas, e a politica de
#: retencao por classe e do KAM-071); aqui fixa-se so a forma.
_CLASSE = r"[a-z][a-z0-9_]{1,31}"
_CLASSE_INTEIRA = re.compile(_CLASSE)

_CHAVE = re.compile(rf"t/({_UUID})/({_CLASSE})/([0-9]{{4}})/(0[1-9]|1[0-2])/({_UUID})")

#: Alfabeto do resto de um prefixo de listagem, depois de `t/{tenant_id}/`.
_RESTO_DE_PREFIXO = re.compile(r"[a-z0-9_/-]*")

#: Comprimento maximo de um prefixo de listagem: o de uma chave completa.
_COMPRIMENTO_MAXIMO = 2 + 36 + 1 + 32 + 1 + 4 + 1 + 2 + 1 + 36


@dataclass(frozen=True)
class PartesDaChave:
    """As partes de uma chave valida."""

    tenant_id: str
    classe: str
    ano: str
    mes: str
    id: str


def tenant_do_ctx(ctx: object) -> str:
    """O tenant do contexto como UUID canonico, ou levanta.

    Aceita so a forma textual canonica, em minusculas: aqui o tenant vira
    **texto de uma chave**, e `T/…AB…` e `t/…ab…` sao dois prefixos diferentes
    num servidor de objectos.
    """
    tenant = getattr(ctx, "tenant_id", None)
    if tenant is None or tenant == "":
        raise CtxEmFaltaError
    if type(tenant) is not str or _UUID_CANONICO.fullmatch(tenant) is None:
        raise TenantInvalidoError(
            type(tenant).__name__, len(tenant) if type(tenant) is str else 0
        )
    return tenant


def prefixo_do_tenant(ctx: Ctx) -> str:
    """O prefixo de tudo o que e de um tenant: `t/{tenant_id}/`."""
    return f"t/{tenant_do_ctx(ctx)}/"


def validar_classe(classe: object) -> str:
    """Valida a forma de uma classe e devolve-a."""
    if type(classe) is not str or _CLASSE_INTEIRA.fullmatch(classe) is None:
        raise MetaInvalidaError(
            "a classe e snake_case minusculo, de 2 a 32 caracteres, comecada por letra"
        )
    return classe


def nova_chave(ctx: Ctx, classe: str, agora: datetime | None = None) -> ObjectKey:
    """Cunha uma chave nova para o tenant do contexto.

    `{aaaa}/{mm}` sao o ano e o mes **UTC** do instante dado. O `{uuid}` e
    aleatorio (v4): a chave nao codifica o contacto, a conversa nem o nome
    original do ficheiro — nenhum dado pessoal entra numa chave.
    """
    tenant = tenant_do_ctx(ctx)
    c = validar_classe(classe)
    if agora is None:
        agora = datetime.now(UTC)
    if not isinstance(agora, datetime) or agora.tzinfo is None:
        raise ChaveInvalidaError("o instante de criacao tem de ser um datetime com fuso")
    em_utc = agora.astimezone(UTC)
    return f"t/{tenant}/{c}/{em_utc.year:04d}/{em_utc.month:02d}/{uuid.uuid4()}"


def partes_da_chave(key: object) -> PartesDaChave:
    """Valida a forma de uma chave, sem olhar para o contexto."""
    if type(key) is not str:
        raise ChaveInvalidaError("nao e texto")
    m = _CHAVE.fullmatch(key)
    if m is None:
        raise ChaveInvalidaError(
            "esperava t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}, em minusculas"
        )
    return PartesDaChave(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))


def chave_do_ctx(ctx: Ctx, key: object, operacao: str) -> PartesDaChave:
    """A pergunta de isolamento: a chave tem a forma canonica **e** e do tenant
    do contexto?

    A ordem das recusas e deliberada: contexto, depois forma, depois dono.
    """
    tenant = tenant_do_ctx(ctx)
    partes = partes_da_chave(key)
    if partes.tenant_id != tenant:
        raise ChaveForaDoTenantError(operacao)
    return partes


def prefixo_do_ctx(ctx: Ctx, prefix: object) -> str:
    """Valida um prefixo de listagem contra o contexto e devolve-o.

    O prefixo tem de **comecar por `t/{ctx.tenant_id}/`, com a barra final**.
    `t/` sozinho, o prefixo vazio e `t/{tenant}` sem barra sao recusados.
    """
    base = prefixo_do_tenant(ctx)
    if type(prefix) is not str:
        raise ChaveInvalidaError("o prefixo nao e texto")
    if not prefix.startswith(base):
        raise ChaveForaDoTenantError("list")
    resto = prefix[len(base) :]
    if (
        len(prefix) > _COMPRIMENTO_MAXIMO
        or _RESTO_DE_PREFIXO.fullmatch(resto) is None
        or "//" in resto
        or resto.startswith("/")
    ):
        raise ChaveInvalidaError(
            "o prefixo tem caracteres fora de [a-z0-9_/-] ou segmentos vazios"
        )
    return prefix
