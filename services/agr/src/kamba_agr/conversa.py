"""Quem tem a palavra: a leitura que o criterio 6 obriga.

Uma consulta, contra a base, dentro de `kamba_core.tenant_guard.tx`. O SQL esta
em `consultas.py` e e **esse** que a *suite* do *gate* 8 corre; aqui esta so o
que o chama.

## Porque e que esta num modulo proprio

Porque e a unica coisa que o turno le da base antes de decidir, e porque e o
sitio onde tres coisas se juntam e nenhuma delas e obvia:

1. **O contexto de RLS vem do `tenant_id` da invocacao e de nenhum outro sitio.**
   E o ADR-015 e o DoD deste ticket. O `tenant_guard.tx` recusa um `tenant` que
   nao seja um UUID e nao escreve o valor em registo nenhum.
2. **Zero linhas nao e `bot`.** Devolve-se `None`, e o `turno.py` trata-o como
   «nao entra no grafo». Tres situacoes dao zero linhas — a conversa nao
   existe, foi apagada, ou o contexto e de outro *tenant* — e as tres tem a
   mesma resposta certa. Um `or 'bot'` aqui era o furo de isolamento mais
   barato que este ticket podia ter: bastava o contexto estar trocado para o
   AGR correr um turno sobre a conversa de outro.
3. **O driver e sincrono e o AGR e `asyncio`.** O `pg8000` e a escolha da casa
   (`db/requirements/migrations.in`) e e sincrono; a consulta vai a um
   *executor*, com uma ligacao por *worker*. Chamar o driver na *event loop*
   serializava o AGR inteiro na latencia da base.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from kamba_core import tenant_guard

from .consultas import SQL_PALAVRA_DA_CONVERSA
from .contexto import InvocacaoDoAgente
from .turno import Palavra


def ler_palavra_sincrono(ligacao: Any, invocacao: InvocacaoDoAgente) -> Palavra | None:
    """A leitura, com uma ligacao DB-API transaccional. Devolve `None` sem linha.

    Os quatro `%s` sao posicionais e a ordem e a do texto do SQL: o `EXISTS`
    aparece primeiro, pelo que os dois primeiros argumentos sao dele. Trocar
    dois aqui nao da erro — da a resposta de outra conversa, e e por isso que
    esta ordem esta escrita na *docstring* da consulta e ha um teste que a
    confronta contra a base.
    """
    with tenant_guard.tx(ligacao, invocacao.tenant_id) as cursor:
        cursor.execute(
            SQL_PALAVRA_DA_CONVERSA,
            (
                invocacao.tenant_id,
                invocacao.conversation_id,
                invocacao.tenant_id,
                invocacao.conversation_id,
            ),
        )
        linha = cursor.fetchone()
    if linha is None:
        return None
    return Palavra(modo=str(linha[0]), handoff_a_espera=bool(linha[1]))


def leitor(abrir_ligacao: Callable[[], Any]) -> Callable[[InvocacaoDoAgente], Any]:
    """A porta `ler_palavra` do `ExecutorDeTurnos`, sobre uma ligacao propria.

    A ligacao abre-se a primeira leitura e fica. Nao ha *pool* aqui: um
    *worker* faz uma leitura por turno e os turnos do *worker* sao em serie, pelo
    que um *pool* era uma caixa vazia com um nome grande. O `asyncio.Lock`
    continua a ser preciso — o `pg8000` nao e seguro para uso concorrente na
    mesma ligacao, e duas corrotinas na mesma tomada entrelacam as respostas.
    """
    estado: dict[str, Any] = {"ligacao": None}
    exclusiva = asyncio.Lock()

    async def ler(invocacao: InvocacaoDoAgente) -> Palavra | None:
        async with exclusiva:
            if estado["ligacao"] is None:
                estado["ligacao"] = abrir_ligacao()
            try:
                return await asyncio.to_thread(
                    ler_palavra_sincrono, estado["ligacao"], invocacao
                )
            except Exception:
                # A mesma razao do `trancas.py`: uma ligacao quebrada que fique
                # guardada faz **todos** os turnos deste processo falharem ate
                # alguem reiniciar o servico. Larga-se, a excepcao sobe (o *job*
                # volta a fila) e a tentativa seguinte abre outra.
                ligacao, estado["ligacao"] = estado["ligacao"], None
                try:
                    ligacao.close()
                except Exception:  # noqa: BLE001 — ja esta quebrada
                    pass
                raise

    return ler
