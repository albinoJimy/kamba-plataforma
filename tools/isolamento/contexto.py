"""O que um caso recebe para correr. Construido pela suite, nunca pelos casos.

Um caso de isolamento nao abre ligacoes nem semeia nada: recebe dois tenants ja
semeados com canarios, dois contactos do **mesmo** tenant, um oraculo ja
confirmado, e as portas para atacar cada camada. E o que permite declarar os
casos sem PostgreSQL (`baterias/` importa-se a seco) e executa-los com ele.

Os campos que um caso nao precisa ficam `None`, e o corredor nao lhe chama o
`fn` se o que ele declarou em `precisa` nao estiver presente — e **falha** nesse
caso, em vez de o saltar.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .oraculo import Oraculo

RAIZ = Path(__file__).resolve().parents[2]


@dataclasses.dataclass(frozen=True)
class Contacto:
    """Um contacto semeado, com o canario que o nomeia em cada tabela."""

    id: str
    tenant_id: str
    #: `(schema, tabela) -> canario deste contacto nessa tabela`.
    canarios: Mapping[tuple[str, str], str]
    #: `(schema, tabela) -> id da linha deste contacto nessa tabela`.
    #:
    #: Existe porque **ha leituras que nao projectam a coluna do canario**, e
    #: isso mediu-se: a `SQL_PEDIDO_POR_PAGAR` do COM projecta
    #: `(id, numero_publico, estado, total_minor, currency, criado_at)` e nao o
    #: `intent_key`, que e onde o canario de `orders_mirror` cabe. Comparar o
    #: canario naquela leitura era impossivel; comparar o **identificador da
    #: linha** e a mesma afirmacao — a linha de Y nao pode sair na leitura de X.
    ids: Mapping[tuple[str, str], str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Contexto:
    """Tudo o que um caso pode precisar. O que falta e `None`."""

    raiz: Path = RAIZ

    #: Os dois tenants. `a` ataca, `b` e a vitima. Tipados como `Any` para nao
    #: obrigar este pacote a importar `db/tests_isolamento/sementes.py`, que
    #: precisa das dependencias da base.
    a: Any = None
    b: Any = None

    #: Os dois contactos, **ambos em A** (criterio 6). `x` ataca, `y` e a vitima.
    x: Contacto | None = None
    y: Contacto | None = None

    #: O oraculo de B (canarios de B e o `tenant_id` dele), ja confirmado.
    oraculo: Oraculo | None = None
    #: O oraculo de Y, para o eixo do contacto.
    oraculo_de_y: Oraculo | None = None

    #: `cursor_de(papel, tenant_id)` — um cursor com o contexto pedido.
    cursor_de: Callable[..., Any] | None = None
    #: `ligar(papel)` — uma ligacao nova, que o caso fecha. O P-01 precisa de
    #: dez, e um cursor nao serve: o que ele mede e a **ligacao** reutilizada.
    ligar: Callable[..., Any] | None = None
    #: `abrir_ligacao()` — uma ligacao de `kamba_app` sem contexto, para a
    #: ToolLayer. A camada e que define o contexto, por `tenant_guard.tx`.
    abrir_ligacao: Callable[[], Any] | None = None
    #: Os cursores de semente, por identidade (`admin`, `batch`).
    cursores: Mapping[str, Any] | None = None
    #: `(schema, tabela, coluna, receita)` das tabelas isoladas.
    tabelas: Sequence[tuple[str, str, str, Any]] = ()

    #: `True` quando o pacote do AGR e importavel (starlette, pydantic, yaml).
    agr: bool = False

    #: `node(guiao, argumentos) -> dict` — corre o condutor de TypeScript e
    #: devolve o relatorio JSON dele. `None` quando nao ha `node`.
    node: Callable[..., Any] | None = None

    #: Para onde o caso escreve o que o oraculo tem de varrer. A suite esvazia
    #: isto antes de cada caso; um caso que produza logs ou spans junta-os aqui.
    logs: list[str] = dataclasses.field(default_factory=list)
    spans: list[dict] = dataclasses.field(default_factory=list)

    def tem(self, precisa: str) -> bool:
        if precisa == "nada":
            return True
        if precisa == "agr":
            return self.agr
        if precisa == "postgres":
            return self.cursor_de is not None and self.a is not None
        if precisa == "node":
            return self.node is not None
        return False
