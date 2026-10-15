"""`Motor` — o que guarda os bytes, **sem** nocao de tenant (KAM-011).

E a costura por baixo da porta. Um motor recebe chaves ja validadas e faz o que
lhe mandam; nao decide quem pode o que. Essa decisao e de
`ArmazenamentoPorTenant` (`guarda.py`), que e a unica coisa que fala com um
motor.

**Um motor nunca se entrega a um consumidor.** As fabricas (`criar_storage_fake`,
`criar_storage_s3`) devolvem a porta, ja com a guarda. Os metodos aqui nao tem
`ctx` para que a diferenca se veja na assinatura.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MetaBruta:
    """Metadados na forma em que o motor os guarda: pares de texto.

    Nomes em minusculas, com hifen; valores em ASCII imprimivel.
    """

    content_type: str
    metadados: Mapping[str, str]


@dataclass(frozen=True)
class InfoBruta:
    """O que o motor sabe de um objecto."""

    tamanho: int
    content_type: str
    metadados: Mapping[str, str]


@dataclass(frozen=True)
class ItemListado:
    """Uma entrada de listagem."""

    chave: str
    tamanho: int


@dataclass(frozen=True)
class Escrito:
    """Resultado de `put`: o que foi efectivamente escrito."""

    tamanho: int
    #: SHA-256 dos bytes enviados, em hexadecimal minusculo.
    sha256: str


@dataclass(frozen=True)
class Listagem:
    """Ate `maximo` entradas, por ordem de chave; `truncada` diz se havia mais."""

    itens: tuple[ItemListado, ...]
    truncada: bool


class Motor(Protocol):
    #: `fake`, `s3`.
    nome: str

    def put(self, chave: str, corpo: Iterable[bytes], meta: MetaBruta) -> Escrito: ...

    def get(self, chave: str) -> Iterator[bytes]:
        """Levanta `ObjectoInexistenteError`."""
        ...

    def head(self, chave: str) -> InfoBruta:
        """Levanta `ObjectoInexistenteError`."""
        ...

    def delete(self, chave: str) -> None:
        """Idempotente."""
        ...

    def list(self, prefixo: str, maximo: int) -> Listagem: ...

    def sign_url(self, chave: str, ttl_segundos: int) -> str:
        """URL de leitura do objecto, valida durante `ttl_segundos`."""
        ...
