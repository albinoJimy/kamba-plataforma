"""Implementacao *fake* do armazenamento: tudo em memoria (KAM-011).

E o que os consumidores usam nos seus testes unitarios, e e um dos alvos da
suite de contrato — a mesma bateria corre aqui e contra um servidor S3 real.
Espelho de `packages/core-ts/src/storage/fake.ts`.

O que a torna um *fake* e nao um *mock*: **comporta-se**. Guarda bytes, soma
tamanhos, expira URLs pelo relogio e recusa uma URL adulterada. O que nao tem:
persistencia, concorrencia entre processos, e HTTP — a URL que assina tem o
esquema `kamba-fake:` e so `buscar` a sabe resolver.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets as _aleatorio
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlsplit

from .guarda import ArmazenamentoPorTenant
from .motor import Escrito, InfoBruta, ItemListado, Listagem, MetaBruta
from .port import ObjectoInexistenteError, StorageProvider

#: Esquema das URLs que o *fake* assina.
ESQUEMA_FAKE = "kamba-fake"

_BLOCO = 64 * 1024

#: Formas dos dois parametros de uma URL do *fake*, iguais as do lado TypeScript.
_EXPIRA = re.compile(r"[0-9]{1,12}")
_ASSINATURA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class RespostaFake:
    """Resposta de `buscar`: o que um cliente HTTP veria."""

    estado: int
    corpo: bytes


_RECUSADO = RespostaFake(403, b"")


class MotorEmMemoria:
    """Motor em memoria. Ver `criar_storage_fake` para a forma de o usar."""

    nome = "fake"

    def __init__(self, agora: Callable[[], datetime] | None = None) -> None:
        self._objectos: dict[str, tuple[bytes, MetaBruta]] = {}
        self._agora = agora or (lambda: datetime.now(UTC))
        # Chave de assinatura das URLs: aleatoria, por instancia, nunca exposta.
        self._chave_de_assinatura = _aleatorio.token_bytes(32)

    def put(self, chave: str, corpo: Iterable[bytes], meta: MetaBruta) -> Escrito:
        soma = hashlib.sha256()
        blocos: list[bytes] = []
        for bloco in corpo:
            blocos.append(bytes(bloco))
            soma.update(bloco)
        dados = b"".join(blocos)
        self._objectos[chave] = (
            dados,
            MetaBruta(content_type=meta.content_type, metadados=dict(meta.metadados)),
        )
        return Escrito(tamanho=len(dados), sha256=soma.hexdigest())

    def get(self, chave: str) -> Iterator[bytes]:
        dados = self._exigir(chave)[0]
        return (dados[i : i + _BLOCO] for i in range(0, len(dados), _BLOCO))

    def head(self, chave: str) -> InfoBruta:
        dados, meta = self._exigir(chave)
        return InfoBruta(
            tamanho=len(dados),
            content_type=meta.content_type,
            metadados=dict(meta.metadados),
        )

    def delete(self, chave: str) -> None:
        self._objectos.pop(chave, None)

    def list(self, prefixo: str, maximo: int) -> Listagem:
        chaves = sorted(c for c in self._objectos if c.startswith(prefixo))
        itens = tuple(ItemListado(c, len(self._objectos[c][0])) for c in chaves[:maximo])
        return Listagem(itens=itens, truncada=len(chaves) > maximo)

    def sign_url(self, chave: str, ttl_segundos: int) -> str:
        expira = int(self._agora().timestamp()) + ttl_segundos
        return (
            f"{ESQUEMA_FAKE}://objectos/{chave}"
            f"?expira={expira}&assinatura={self._assinar(chave, expira)}"
        )

    def buscar(self, url: str) -> RespostaFake:
        """Resolve uma URL assinada por este motor, como um cliente HTTP faria.

        403 se a assinatura nao bate ou se o prazo passou — os dois casos dao a
        mesma resposta, como num servidor S3. 404 se a URL e valida e o objecto
        ja nao existe.
        """
        try:
            lida = urlsplit(url)
            parametros = parse_qs(lida.query, keep_blank_values=True)
        except (ValueError, AttributeError, TypeError):
            return _RECUSADO
        if lida.scheme != ESQUEMA_FAKE or lida.netloc != "objectos":
            return _RECUSADO
        chave = unquote(lida.path[1:])
        expira_bruto = (parametros.get("expira") or [""])[0]
        assinatura = (parametros.get("assinatura") or [""])[0]
        if _EXPIRA.fullmatch(expira_bruto) is None or _ASSINATURA.fullmatch(assinatura) is None:
            return _RECUSADO
        expira = int(expira_bruto)
        # Em bytes: `compare_digest` levanta `TypeError` com texto nao ASCII.
        if not hmac.compare_digest(
            assinatura.encode(), self._assinar(chave, expira).encode()
        ):
            return _RECUSADO
        if int(self._agora().timestamp()) >= expira:
            return _RECUSADO
        guardado = self._objectos.get(chave)
        if guardado is None:
            return RespostaFake(404, b"")
        return RespostaFake(200, guardado[0])

    @property
    def total(self) -> int:
        """Numero de objectos guardados, de todos os tenants. So para testes."""
        return len(self._objectos)

    def _assinar(self, chave: str, expira: int) -> str:
        return hmac.new(
            self._chave_de_assinatura, f"{chave}\n{expira}".encode(), hashlib.sha256
        ).hexdigest()

    def _exigir(self, chave: str) -> tuple[bytes, MetaBruta]:
        guardado = self._objectos.get(chave)
        if guardado is None:
            raise ObjectoInexistenteError
        return guardado


@dataclass(frozen=True)
class StorageFake:
    """A porta sobre memoria, e o que um teste precisa alem dela.

    O motor nao sai daqui: quem tem o motor le qualquer chave sem contexto, e um
    *fake* que ensina esse atalho nos testes ensina-o para o codigo.
    """

    storage: StorageProvider
    #: Resolve uma URL assinada por este armazenamento.
    buscar: Callable[[str], RespostaFake]
    #: Numero de objectos guardados, de todos os tenants.
    total: Callable[[], int]


def criar_storage_fake(agora: Callable[[], datetime] | None = None) -> StorageFake:
    """Cria um armazenamento *fake*, ja com a guarda de isolamento."""
    motor = MotorEmMemoria(agora)
    return StorageFake(
        storage=ArmazenamentoPorTenant(motor),
        buscar=motor.buscar,
        total=lambda: motor.total,
    )
