"""A maquina de estados da encomenda, e o contrato que o consumidor usa.

Espelho de `packages/core-ts/src/eventos/estados.ts`. O grafo e o do
`docs/tecnica/00_Arquitectura_Solucao.md` §6.1, transcrito **inteiro** e nao so
a parte do pagamento: um subconjunto convidava a tratar um estado desconhecido
como «pode», que e o erro que fecha a porta ao contrario.

O `paga` so e alcancavel por evento autenticado (ADR-013), e a transicao que
importa e `aguarda_pagamento -> paga` por `payment.confirmed`. Um consumidor que
aplicasse `paga` a partir de `criada` estaria a confirmar um pagamento sobre uma
encomenda sem referencia emitida — e e por isso que a verificacao nao e um
detalhe do consumidor: e uma pre-condicao dele.

O consumidor fala com o protocolo `MaquinaDeEstados`, nao com esta tabela: o
teste de contrato usa uma maquina **falsa** que diz «nao» a tudo, e e assim que
se prova que a transicao invalida nunca se aplica sem depender do grafo real
estar certo.

**A diferenca de forma face ao TypeScript, que e deliberada:** la os metodos sao
`async` porque o cliente de base de dados o e; aqui sao sincronos, como o
`tenant_guard` e o `storage`. A semantica — o que se le, o que se recusa, e a
ordem — e a mesma, e `TestParidadeDoTypeScript` confronta os numeros dos dois
lados.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Protocol

#: Os estados da encomenda (`docs/tecnica/00` §6.1). Lista fechada.
ESTADOS_DA_ENCOMENDA: tuple[str, ...] = (
    "criada",
    "aguarda_pagamento",
    "pendente_confirmacao",
    "paga",
    "expirada",
    "cancelada",
    "em_entrega",
    "entregue",
    "entrega_falhada",
    "em_disputa",
    "reembolso_pendente",
    "reembolsada",
)

#: As transicoes do §6.1: `{estado: (estados alcancaveis)}`.
#:
#: Transcrita do diagrama, aresta a aresta. O `expirada -> paga` esta la de
#: proposito («pagamento tardio confirmado»): e um caso real do Multicaixa por
#: referencia, e tira-lo daqui fazia o consumidor mandar para a DLQ um pagamento
#: que o negocio aceita.
TRANSICOES: Mapping[str, tuple[str, ...]] = {
    "criada": ("aguarda_pagamento",),
    "aguarda_pagamento": ("paga", "pendente_confirmacao", "expirada"),
    "pendente_confirmacao": ("paga", "aguarda_pagamento"),
    "paga": ("em_entrega", "entregue", "reembolso_pendente"),
    "expirada": ("aguarda_pagamento", "cancelada", "paga"),
    "cancelada": (),
    "em_entrega": ("entregue", "entrega_falhada"),
    "entregue": ("em_disputa",),
    "entrega_falhada": ("em_entrega", "reembolso_pendente"),
    "em_disputa": ("reembolso_pendente", "entregue"),
    "reembolso_pendente": ("reembolsada",),
    "reembolsada": (),
}

#: Que estado cada tipo de evento **causa**.
#:
#: O criterio e um so, e e esse que decide a lista: estao aqui os eventos cujo
#: consumo **aplica** a transicao, e e por isso que precisam da pre-condicao de
#: estado. Sao os dois de pagamento, e a razao e o ADR-013 — o `paga` so e
#: alcancavel por evento autenticado.
#:
#: **Nao** estao aqui: `order.expired`, `order.delivered` e `order.paid`. Esses
#: sao emitidos pelo COM **depois** da transicao (`docs/tecnica/03` §6): quem os
#: consome esta a ser informado, nao a decidir. Pedir-lhes uma pre-condicao de
#: estado era exigir que a replica do consumidor ja tivesse o estado **novo**
#: para aceitar a noticia dele — e isso adiava toda a primeira entrega.
#:
#: Um tipo que nao esteja aqui **nao** tem pre-condicao de estado, e o consumidor
#: trata-o sem consultar a maquina — nao e «pode tudo», e «isto nao e uma
#: transicao de encomenda».
ESTADO_PRETENDIDO: Mapping[str, str] = {
    "payment.confirmed": "paga",
    "payment.manual_confirmed": "paga",
}


class EstadoDesconhecidoError(ValueError):
    """Um estado que nao esta na maquina do §6.1."""

    def __init__(self, estado: str) -> None:
        super().__init__(f"estado fora da maquina do §6.1: {estado}")
        self.estado = estado


def e_estado(estado: object) -> bool:
    """`estado` e um dos doze?"""
    return isinstance(estado, str) and estado in ESTADOS_DA_ENCOMENDA


def pode_transitar(de: str, para: str) -> bool:
    """A transicao `de -> para` existe no §6.1?

    Um estado desconhecido **levanta**, em vez de devolver `False`: um `False`
    silencioso aqui era indistinguivel de «a transicao nao existe», e a
    diferenca decide entre adiar (estado por chegar) e DLQ (transicao invalida).
    """
    if not e_estado(de):
        raise EstadoDesconhecidoError(de)
    if not e_estado(para):
        raise EstadoDesconhecidoError(para)
    return para in TRANSICOES[de]


class MaquinaDeEstados(Protocol):
    """O que o consumidor pergunta antes de aplicar um efeito de transicao."""

    def estado_de(self, agregado_tipo: str, agregado_id: str) -> str | None:
        """O estado actual do agregado, ou `None` se nao existir.

        `None` **nao** e «pode»: um `payment.confirmed` sobre uma encomenda que
        ainda nao existe na replica do consumidor e exactamente o caso que se
        manda adiar.
        """
        ...


class LeituraSql(Protocol):
    """O minimo de uma leitura: as linhas que voltaram."""

    linhas: Sequence[Mapping[str, object]]


class ClienteDeLeitura(Protocol):
    """O minimo de um cliente que so le.

    Protocolo proprio, e nao o `ClienteSql` do `consumo`: a maquina nao escreve
    nem conta linhas, e pedir-lhe um cliente que o faca era pedir mais poder do
    que ela usa. (O TypeScript separa os dois pela mesma razao.)
    """

    def executar(
        self, sql: str, parametros: Sequence[object] = ()
    ) -> LeituraSql: ...


#: Forma aceite de um nome de tabela ou de coluna. Lista fechada de caracteres:
#: o nome vai para dentro da consulta, e um nome vindo de fora nao se interpola.
_NOME_DE_TABELA = re.compile(r"[a-z][a-z0-9_]{1,62}")


class MaquinaNaBase:
    """A maquina real, sobre a tabela de encomendas do consumidor.

    `COM` (o core de comercio) e o KAM-041 e ainda nao existe; esta
    implementacao le a coluna de estado da tabela que lhe for dada, para que o
    consumidor nao fique a espera dela. O `agregado_id` vai como **parametro**;
    o nome da tabela e validado contra uma forma fechada.
    """

    def __init__(
        self,
        bd: ClienteDeLeitura,
        tabela: str = "orders",
        coluna_id: str = "id",
        coluna_estado: str = "estado",
    ) -> None:
        for nome in (tabela, coluna_id, coluna_estado):
            if not isinstance(nome, str) or _NOME_DE_TABELA.fullmatch(nome) is None:
                raise ValueError(f"nome invalido: {nome!r}")
        self._bd = bd
        self._tabela = tabela
        self._coluna_id = coluna_id
        self._coluna_estado = coluna_estado

    def estado_de(self, agregado_tipo: str, agregado_id: str) -> str | None:
        if agregado_tipo != "order":
            return None
        leitura = self._bd.executar(
            f"SELECT {self._coluna_estado} AS estado FROM platform.{self._tabela} "
            f"WHERE {self._coluna_id} = %s",
            (agregado_id,),
        )
        linhas = leitura.linhas
        if not linhas:
            return None
        estado = linhas[0]["estado"]
        if not e_estado(estado):
            raise EstadoDesconhecidoError(str(estado))
        return str(estado)
