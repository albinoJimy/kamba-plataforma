"""Que vertical esta activa para este *tenant* (KAM-038).

A `evt_subscricoes` e configuracao **global** de entrega — por `consumer` e nao
por *tenant* (revisao `0004`) —, e os dois `registry/*.yaml` subscrevem os
**mesmos** dois eventos de pagamento. Sem esta leitura, um `payment.confirmed`
de um *tenant* que so tem o Vendedor era consumido tambem pelo consumidor de
Servicos: duas linhas em `events_consumed`, duas chaves de idempotencia
diferentes, e **duas mensagens ao mesmo cliente** sobre o mesmo pagamento.

O que decide e o que o §5.2 ja decidiu para o turno de conversa — «uma so
vertical principal por numero no Piloto» —, e a leitura e a **mesma**: o
`check_entitlement` do KAM-009, que falha fechada (sem linha, inactivo, ou
*tenant* em `onboarding`/`suspenso`/`encerrado` nega). Duas leituras diferentes
davam uma vertical activa num caminho e inactiva no outro.

## Falha fechada tambem quando ninguem liga a porta

O `ConsumidorDeEventos` exige um leitor; o que **nao** tem e um leitor por
omissao que permita. Um `lambda: permitido=True` escrito para poder construir o
objecto fazia o caminho de producao consumir por todas as verticais, e o defeito
so aparecia como mensagens a dobrar na conversa de um cliente.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from kamba_core import tenant_guard
from kamba_core.ten import Entitlement, check_entitlement


@dataclass(frozen=True, slots=True)
class _Leitura:
    """O `Resultado` que o `check_entitlement` espera: so as linhas."""

    linhas: Sequence[Mapping[str, object]] = ()
    contagem: int | None = None


class _ClienteDeCursor:
    """Um `ClienteSql` sobre um cursor DB-API ja dentro de `tenant_guard.tx`.

    O `check_entitlement` fala com um cliente que **executa e devolve linhas**;
    o `tenant_guard.tx` entrega um cursor. Este adaptador junta os dois sem dar
    ao TEN uma ligacao inteira — o que ele precisa e de uma leitura, e dar-lhe a
    ligacao era dar-lhe o poder de abrir outra transaccao.
    """

    __slots__ = ("_cursor",)

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> _Leitura:
        self._cursor.execute(sql, tuple(parametros))
        if self._cursor.description is None:
            return _Leitura()
        colunas = [
            coluna[0].decode() if isinstance(coluna[0], bytes) else str(coluna[0])
            for coluna in self._cursor.description
        ]
        linhas = [
            dict(zip(colunas, linha, strict=True)) for linha in self._cursor.fetchall()
        ]
        return _Leitura(linhas=linhas)


class LeitorDeEntitlements:
    """`(tenant_id, modulo) -> Entitlement`, sobre uma ligacao por leitura.

    Uma ligacao por leitura e nao uma guardada: a leitura acontece uma vez por
    entrega e uma tomada guardada entre duas entregas e uma tomada que o
    servidor pode ter fechado — a mesma escolha que o `llm/cliente.py` do
    KAM-030 fez.

    **O contexto de *tenant* e o do envelope validado**, que e quem chama: a
    leitura corre em `tenant_guard.tx` com esse valor, pelo que um envelope
    forjado le os entitlements do *tenant* que declarou e nao os de outro.
    """

    __slots__ = ("_abrir",)

    def __init__(self, abrir_ligacao: Callable[[], Any]) -> None:
        self._abrir = abrir_ligacao

    def ler(self, tenant_id: str, modulo: str) -> Entitlement:
        ligacao = self._abrir()
        try:
            with tenant_guard.tx(ligacao, tenant_id) as cursor:
                return check_entitlement(_ClienteDeCursor(cursor), tenant_id, modulo)
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a leitura ja aconteceu
                pass
