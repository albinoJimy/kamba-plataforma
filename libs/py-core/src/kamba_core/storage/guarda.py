"""`ArmazenamentoPorTenant` — a guarda de isolamento do armazenamento (KAM-011).

E a **unica** implementacao de `StorageProvider`. O *fake* e o S3 sao motores
diferentes por baixo da mesma guarda, e por isso recusam exactamente as mesmas
coisas pela mesma ordem. Espelho de `packages/core-ts/src/storage/guarda.ts`.

O que esta classe garante, por operacao:

- `put`: contexto, forma da chave, dono da chave, metadados, classe igual ao
  segmento da chave — tudo **antes** de falar com o motor;
- `get`, `head`, `delete`, `sign_url`: contexto, forma, dono; no `head`, a classe
  devolvida tem de ser a da chave;
- `list`: o prefixo comeca por `t/{tenant}/`, e **cada** chave devolvida esta
  sob o prefixo pedido.

A verificacao "depois" da listagem e a segunda camada do X-08 (`docs/tecnica/08`
§3.7): se um motor ou um servidor devolver uma chave de outro tenant, a listagem
**falha inteira** em vez de devolver o que nao devia.

**Nao regista nada**: nem o tenant, nem a chave, nem o erro. O DoD proibe
associar `tenant_id` a conteudo em *logs*, e uma chave contem o `tenant_id`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from .chave import chave_do_ctx, prefixo_do_ctx, validar_classe
from .motor import MetaBruta, Motor
from .port import (
    LIMITE_DE_LISTAGEM,
    TTL_MAXIMO_S,
    Corpo,
    Ctx,
    ListagemTruncadaError,
    MetaInvalidaError,
    ObjectInfo,
    ObjectKey,
    ObjectMeta,
    ObjectRef,
    RespostaDoMotorInvalidaError,
    TtlInvalidoError,
)

#: Nome do metadado que guarda a classe.
META_CLASSE = "classe"

#: Nome do metadado que guarda `retain_until`. Com hifen e nao com sublinhado:
#: vai num cabecalho HTTP (`x-amz-meta-…`), e ha *proxies* que descartam
#: cabecalhos com sublinhado sem avisar.
META_RETAIN_UNTIL = "retain-until"

#: Tecto do `limite` de uma listagem.
LIMITE_MAXIMO_DE_LISTAGEM = 10_000

#: Forma aceite de um tipo de conteudo: `tipo/subtipo`, com parametros
#: opcionais. Lista fechada de caracteres, porque o valor vai num cabecalho.
_TIPO_DE_CONTEUDO = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,62}"
    r"(; ?[A-Za-z0-9_-]{1,32}=[A-Za-z0-9_.+-]{1,64}){0,4}"
)

#: `2026-10-13T08:30:00.000Z` — a forma que o `toISOString()` do JavaScript
#: escreve, e **so** essa: ano de quatro digitos, milissegundos, `Z`. Os dois
#: lados escrevem-na e os dois so leem o que, relido, da a mesma cadeia — um
#: 30 de Fevereiro ou uma hora 24 nao passam em nenhum.
_INSTANTE = re.compile(
    r"[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z"
)


def formatar_instante(instante: datetime) -> str:
    """Um instante em UTC, com milissegundos e `Z`."""
    em_utc = instante.astimezone(UTC)
    return (
        f"{em_utc.year:04d}-{em_utc.month:02d}-{em_utc.day:02d}"
        f"T{em_utc.hour:02d}:{em_utc.minute:02d}:{em_utc.second:02d}"
        f".{em_utc.microsecond // 1000:03d}Z"
    )


def ler_instante(texto: object) -> datetime | None:
    """O instante de uma cadeia na forma canonica, ou `None`."""
    if type(texto) is not str or _INSTANTE.fullmatch(texto) is None:
        return None
    try:
        instante = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return instante if formatar_instante(instante) == texto else None


def _so_bytes(corpo: Iterable[object]) -> Iterator[bytes]:
    """Passa os blocos adiante, e recusa o primeiro que nao seja de bytes.

    Sem isto, um bloco de texto rebentava dentro do motor com um `TypeError`
    cru — a meio de um envio em partes, se calhasse.
    """
    for bloco in corpo:
        if not isinstance(bloco, (bytes, bytearray, memoryview)):
            raise MetaInvalidaError("o corpo tem de ser bytes ou um iteravel de bytes")
        yield bytes(bloco)


def _como_fluxo(body: object) -> Iterable[bytes]:
    if isinstance(body, (bytes, bytearray, memoryview)):
        return (bytes(body),)
    if isinstance(body, str) or not isinstance(body, Iterable):
        raise MetaInvalidaError("o corpo tem de ser bytes ou um iteravel de bytes")
    return _so_bytes(body)


def _chave_da_ref(ref: object) -> object:
    return getattr(ref, "key", None)


class ArmazenamentoPorTenant:
    """A porta, sobre um motor."""

    def __init__(self, motor: Motor) -> None:
        self._motor = motor

    @property
    def nome(self) -> str:
        return self._motor.nome

    def put(self, ctx: Ctx, key: ObjectKey, body: Corpo, meta: ObjectMeta) -> ObjectRef:
        partes = chave_do_ctx(ctx, key, "put")
        if not isinstance(meta, ObjectMeta):
            raise MetaInvalidaError("faltam os metadados (content_type, classe, retain_until)")
        classe = validar_classe(meta.classe)
        if classe != partes.classe:
            raise MetaInvalidaError("a classe dos metadados nao coincide com a da chave")
        if (
            not isinstance(meta.content_type, str)
            or _TIPO_DE_CONTEUDO.fullmatch(meta.content_type) is None
        ):
            raise MetaInvalidaError("content_type tem de ser tipo/subtipo")
        prazo = meta.retain_until
        if not isinstance(prazo, datetime) or prazo.tzinfo is None:
            raise MetaInvalidaError(
                "retain_until e obrigatorio e tem de ser um datetime com fuso"
            )
        try:
            prazo_texto = formatar_instante(prazo)
        except (OverflowError, ValueError):
            prazo_texto = ""
        # So se escreve o que se consegue ler de volta: um prazo que o `head`
        # recusasse era um objecto que a purga nunca veria.
        if ler_instante(prazo_texto) is None:
            raise MetaInvalidaError("retain_until tem de ter o ano entre 1000 e 9999, em UTC")
        escrito = self._motor.put(
            key,
            _como_fluxo(body),
            MetaBruta(
                content_type=meta.content_type,
                metadados={
                    META_CLASSE: classe,
                    META_RETAIN_UNTIL: prazo_texto,
                },
            ),
        )
        return ObjectRef(key=key, tamanho=escrito.tamanho, sha256=escrito.sha256)

    def get(self, ctx: Ctx, ref: ObjectRef) -> Iterator[bytes]:
        key = _chave_da_ref(ref)
        chave_do_ctx(ctx, key, "get")
        return self._motor.get(key)  # type: ignore[arg-type]

    def head(self, ctx: Ctx, ref: ObjectRef) -> ObjectInfo:
        key = _chave_da_ref(ref)
        partes = chave_do_ctx(ctx, key, "head")
        info = self._motor.head(key)  # type: ignore[arg-type]
        classe = info.metadados.get(META_CLASSE)
        prazo_bruto = info.metadados.get(META_RETAIN_UNTIL)
        if classe != partes.classe:
            raise RespostaDoMotorInvalidaError("o objecto nao traz a classe da sua chave")
        prazo = ler_instante(prazo_bruto)
        if prazo is None:
            raise RespostaDoMotorInvalidaError("o objecto nao traz um retain_until legivel")
        return ObjectInfo(
            key=key,  # type: ignore[arg-type]
            tamanho=info.tamanho,
            content_type=info.content_type,
            classe=classe,
            retain_until=prazo,
        )

    def sign_url(self, ctx: Ctx, ref: ObjectRef, *, ttl_seconds: int) -> str:
        key = _chave_da_ref(ref)
        chave_do_ctx(ctx, key, "sign_url")
        # `type(...) is int`, e nao `isinstance`: `True` e um `int`, e uma
        # subclasse de `int` pode responder as comparacoes como quiser e valer
        # outra coisa quando o motor a usa (`ANALISE-09`, A2).
        if (
            type(ttl_seconds) is not int
            or ttl_seconds < 1
            or ttl_seconds > TTL_MAXIMO_S
        ):
            raise TtlInvalidoError
        return self._motor.sign_url(key, ttl_seconds)  # type: ignore[arg-type]

    def delete(self, ctx: Ctx, ref: ObjectRef) -> None:
        key = _chave_da_ref(ref)
        chave_do_ctx(ctx, key, "delete")
        self._motor.delete(key)  # type: ignore[arg-type]

    def list(
        self, ctx: Ctx, prefix: str, *, limite: int | None = LIMITE_DE_LISTAGEM
    ) -> list[ObjectRef]:
        prefixo = prefixo_do_ctx(ctx, prefix)
        if limite is None:
            limite = LIMITE_DE_LISTAGEM
        if (
            type(limite) is not int
            or limite < 1
            or limite > LIMITE_MAXIMO_DE_LISTAGEM
        ):
            raise MetaInvalidaError(
                f"limite tem de ser um inteiro entre 1 e {LIMITE_MAXIMO_DE_LISTAGEM}"
            )
        listagem = self._motor.list(prefixo, limite)
        refs: list[ObjectRef] = []
        for item in listagem.itens:
            # Segunda camada: o que o motor devolve e conferido, e nao so o que
            # se lhe pediu. Uma chave fora do prefixo falha a listagem inteira.
            if type(item.chave) is not str or not item.chave.startswith(prefixo):
                raise RespostaDoMotorInvalidaError(
                    "a listagem devolveu uma chave fora do prefixo pedido"
                )
            refs.append(ObjectRef(key=item.chave, tamanho=item.tamanho, sha256=None))
        if listagem.truncada or len(refs) > limite:
            raise ListagemTruncadaError(limite)
        return refs
