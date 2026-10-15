"""A porta `StorageProvider` do lado Python (KAM-011, ADR-014).

Espelho de `packages/core-ts/src/storage/port.ts`. As duas implementacoes tem de
significar o mesmo: a mesma forma de chave, as mesmas recusas pela mesma ordem,
os mesmos nomes de metadados no servidor — um objecto escrito por um servico
Node tem de ser lido por um servico Python, e vice-versa.

Isto e o contrato, e mais nada: nao ha aqui HTTP, nem assinatura, nem memoria.
Quem guarda os bytes e um `Motor` (`motor.py`), e quem impoe o isolamento por
tenant e **uma so** classe, `ArmazenamentoPorTenant` (`guarda.py`), que embrulha
qualquer motor.

Quatro regras atravessam o modulo inteiro:

1. **Toda a operacao leva `ctx.tenant_id`.** Nao ha sobrecarga sem contexto, nem
   valor por omissao, nem "modo administrador".
2. **A chave diz de quem e o objecto**, e a porta confere-o antes de falar com o
   servidor: `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}` (`docs/tecnica/08`
   §3.1 e §3.8).
3. **Uma URL assinada vive no maximo 300 s.**
4. **Nenhuma mensagem de erro contem uma credencial nem uma URL assinada.**
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

#: TTL maximo de uma URL assinada, em segundos (`docs/tecnica/08` §3.8).
TTL_MAXIMO_S = 300

#: Numero maximo de chaves que `list` devolve por omissao.
LIMITE_DE_LISTAGEM = 1000

#: Chave de um objecto: `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`.
ObjectKey = str

#: Corpo de um objecto: os bytes de uma vez, ou um iteravel deles.
Corpo = bytes | bytearray | memoryview | Iterable[bytes]


@dataclass(frozen=True)
class Ctx:
    """Contexto de quem chama.

    `tenant_id` e o UUID do tenant na forma canonica. Vem do estado da conversa
    ou do pedido autenticado, **nunca** de texto do utilizador nem de saida do
    modelo (`docs/tecnica/08` §3.1, camada "Estado").
    """

    tenant_id: str


@dataclass(frozen=True)
class ObjectRef:
    """Referencia a um objecto guardado.

    E isto que um consumidor persiste — nunca uma URL. `sha256` vem preenchido
    de `put` e e `None` numa referencia devolvida por `list`, porque uma
    listagem S3 nao devolve metadados.
    """

    key: ObjectKey
    tamanho: int
    sha256: str | None = None


@dataclass(frozen=True)
class ObjectMeta:
    """Metadados que **todo** o objecto leva (criterio de aceitacao 8).

    `classe` tem de coincidir com o segmento `{classe}` da chave. `retain_until`
    e obrigatorio e tem de ter fuso horario: um instante sem fuso nao e um
    instante. Este modulo so o regista; apagar e do KAM-071.
    """

    content_type: str
    classe: str
    retain_until: datetime


@dataclass(frozen=True)
class ObjectInfo:
    """O que `head` devolve: os metadados tal como o servidor os guardou."""

    key: ObjectKey
    tamanho: int
    content_type: str
    classe: str
    retain_until: datetime


class CtxEmFaltaError(RuntimeError):
    """Pediu-se uma operacao sem dizer de que tenant."""

    def __init__(self) -> None:
        super().__init__(
            "operacao de armazenamento sem `ctx.tenant_id`: nao ha acesso sem tenant"
        )


class TenantInvalidoError(ValueError):
    """O tenant do contexto nao e um UUID canonico. A mensagem nao repete o valor."""

    def __init__(self, tipo: str, comprimento: int) -> None:
        super().__init__(
            "`ctx.tenant_id` tem de ser um UUID na forma canonica "
            f"(recebido: {tipo} com {comprimento} caracteres)"
        )


class ChaveInvalidaError(ValueError):
    """A chave nao tem a forma `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`.

    A mensagem leva o motivo e nunca a chave: uma chave mal formada pode ser um
    valor que alguem passou por engano.
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(f"chave de objecto invalida: {motivo}")


class ChaveForaDoTenantError(PermissionError):
    """A chave, a referencia ou o prefixo e de outro tenant.

    A mensagem nao diz de qual, nem se o objecto existe.
    """

    def __init__(self, operacao: str) -> None:
        super().__init__(
            f"{operacao}: a chave nao pertence ao tenant do contexto; recusado"
        )


class MetaInvalidaError(ValueError):
    """Os metadados nao servem (classe, tipo de conteudo ou prazo)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(f"metadados de objecto invalidos: {motivo}")


class TtlInvalidoError(ValueError):
    """O TTL pedido para uma URL assinada esta fora de `[1, 300]` segundos."""

    def __init__(self) -> None:
        super().__init__(
            f"o TTL de uma URL assinada e um inteiro entre 1 e {TTL_MAXIMO_S} "
            "segundos (docs/tecnica/08 §3.8)"
        )


class ObjectoInexistenteError(LookupError):
    """O objecto nao existe no tenant do contexto."""

    def __init__(self) -> None:
        super().__init__("objecto inexistente no tenant do contexto")


class ListagemTruncadaError(RuntimeError):
    """Ha mais chaves sob o prefixo do que o limite pedido."""

    def __init__(self, limite: int) -> None:
        self.limite = limite
        super().__init__(
            f"ha mais de {limite} objectos sob o prefixo; estreite o prefixo ou "
            "aumente `limite` — a listagem nao se corta em silencio"
        )


class RespostaDoMotorInvalidaError(RuntimeError):
    """O motor devolveu algo que nao devia. **Falha fechada.**

    Uma chave fora do prefixo pedido, ou metadados que nao se conseguem ler: e o
    sinal de um defeito no servidor ou no motor, e devolver "o que se aproveita"
    seria esconder o caso que a segunda camada existe para apanhar.
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(f"resposta do armazenamento recusada: {motivo}")


class ArmazenamentoIndisponivelError(RuntimeError):
    """O servidor de objectos nao respondeu, ou respondeu com um erro.

    Leva o estado HTTP e o codigo de erro S3 quando existem — **nunca** o corpo
    da resposta nem o endereco pedido, que numa URL assinada e uma credencial.
    """

    def __init__(self, operacao: str, estado: int | None, codigo: str | None) -> None:
        self.operacao = operacao
        self.estado = estado
        self.codigo = codigo
        if estado is None:
            detalhe = " (sem resposta)"
        elif codigo:
            detalhe = f" (HTTP {estado}, {codigo})"
        else:
            detalhe = f" (HTTP {estado})"
        super().__init__(f"armazenamento indisponivel em {operacao}{detalhe}")


@runtime_checkable
class StorageProvider(Protocol):
    """A porta.

    O esboco do ticket tem cinco metodos; aqui sao seis. `head` foi acrescentado
    porque sem ele o criterio "cada objecto leva metadados `classe` e
    `retain_until`" so se podia provar do lado de quem os envia — e a purga do
    KAM-071 precisa de os ler.
    """

    #: Nome curto do motor: `fake`, `s3`.
    nome: str

    def put(self, ctx: Ctx, key: ObjectKey, body: Corpo, meta: ObjectMeta) -> ObjectRef:
        """Guarda um objecto."""
        ...

    def get(self, ctx: Ctx, ref: ObjectRef) -> Iterator[bytes]:
        """Devolve o conteudo, em blocos."""
        ...

    def head(self, ctx: Ctx, ref: ObjectRef) -> ObjectInfo:
        """Devolve os metadados que o servidor guardou."""
        ...

    def sign_url(self, ctx: Ctx, ref: ObjectRef, *, ttl_seconds: int) -> str:
        """Devolve uma URL de leitura que expira em `ttl_seconds` (1 a 300)."""
        ...

    def delete(self, ctx: Ctx, ref: ObjectRef) -> None:
        """Apaga. Idempotente."""
        ...

    def list(self, ctx: Ctx, prefix: str, *, limite: int = LIMITE_DE_LISTAGEM) -> list[ObjectRef]:
        """Lista as referencias sob um prefixo **do tenant do contexto**."""
        ...
