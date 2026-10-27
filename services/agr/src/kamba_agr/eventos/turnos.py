"""O turno por evento: `turn_id = event_id`, sob a tranca (KAM-038, criterio 5).

Tres propriedades, e o criterio escreve-as por extenso:

1. **`turn_id = event_id`.** O §3.24 fixou `turn_id` como o `wamid`; um turno por
   evento nao tem `wamid` nenhum, e o que o identifica e o `id` do envelope. A
   consequencia que interessa e a chave de envio `turn_id:seq`: ela fica
   **estavel entre re-entregas do mesmo evento**, e e isso que faz «cinco
   entregas, uma mensagem» ser uma consequencia e nao uma coincidencia.
2. **Corre sob a tranca da conversa.** A mesma `TrancaDeConversas` do KAM-025 e
   a mesma chave — o `thread_id` —, pela razao escrita la: ela tem de travar os
   dois canais do mesmo contacto, senao dois turnos corriam sobre o mesmo
   *thread* do LangGraph. Um turno por evento e um turno: nao pode correr ao
   lado de um turno de conversa da mesma pessoa.
3. **Nao corre se a conversa estiver com um humano.** `mode != 'bot'` (o que
   inclui `pausada`) ou um `handoffs.status = 'waiting'`. O evento **consome-se**
   e o HND e notificado; nao se adia. Repetir seis vezes para dizer sempre o
   mesmo nao e tentar outra vez, e a invariante do `docs/tecnica/02` §11 regra 4
   nao admite entrar num *thread* com `interrupt` pendente.

## A leitura da palavra e **dentro** da tranca, e a ordem nao e indiferente

O KAM-025 ja escolheu assim para o turno de conversa, e a razao vale igual aqui:
entre uma leitura feita fora e o efeito, a conversa pode passar a `pausada` — e
o efeito corria sobre uma conversa que ja esta com um humano. Dentro da tranca,
a transicao de modo (que toma a mesma chave, `SQL_TRANCAR_CONVERSA` do KAM-018)
espera pela nossa vez.

**O que fica fora da tranca e so a resolucao do contacto**, que nao le estado de
conversa nenhum: um `ContactoPorResolver` sobe antes de se tomar a tranca, e com
isso uma entrega que nao tem destinatario nao prende a conversa de ninguem.

## O evento do dono nao toma tranca, e isso esta decidido

Um `stock.low` avisa o dono e nao fala com cliente nenhum: nao ha conversa, nao
ha `thread_id`, e nao ha nada para serializar. Tomar uma tranca sobre uma chave
inventada era inventar contencao; o criterio 5 fala do turno por evento, e um
aviso ao dono nao e um turno.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kamba_core import tenant_guard

from ..contexto import MODO_DO_BOT, thread_id_de
from .consultas import SQL_CONVERSA_DO_CONTACTO


@dataclass(frozen=True, slots=True)
class Conversa:
    """A conversa de um contacto: o `id`, o modo, e se ha *handoff* a espera."""

    id: str
    modo: str
    handoff_a_espera: bool

    @property
    def do_humano(self) -> bool:
        """`True` se o turno por evento **nao** corre. Criterio 5.

        O modo testa-se por **igualdade a `bot`** e nao por desigualdade aos
        outros tres, pela razao do `Palavra.do_humano` do KAM-025: lista de
        permitidos, nao de proibidos. Um modo novo no dominio fecha a porta por
        omissao, que e o lado seguro de errar.
        """
        return self.modo != MODO_DO_BOT or self.handoff_a_espera


def ler_conversa_sincrono(
    ligacao: Any, tenant_id: str, contact_id: str
) -> Conversa | None:
    """A conversa do contacto, com contexto de *tenant*. `None` sem linha.

    O `tenant_id` vem do envelope **validado** e de mais lado nenhum (criterio 4,
    ADR-015): e ele que o `tenant_guard.tx` poe em `app.tenant_id`, e e por isso
    que um envelope forjado nao encontra conversa nenhuma — a RLS so lhe mostra
    as do *tenant* que ele declarou, e o efeito nunca chega ao *tenant* a que o
    agregado pertence.
    """
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_CONVERSA_DO_CONTACTO, (tenant_id, contact_id))
        linha = cursor.fetchone()
    if linha is None:
        return None
    return Conversa(
        id=str(linha[0]), modo=str(linha[1]), handoff_a_espera=bool(linha[2])
    )


class LeitorDeConversas:
    """A leitura da conversa sobre uma ligacao propria, serializada.

    A ligacao abre-se a primeira leitura e fica, como no `conversa.leitor` do
    KAM-025; o `asyncio.Lock` e preciso porque o `pg8000` nao e seguro para uso
    concorrente na mesma ligacao, e duas corrotinas na mesma tomada entrelacam
    as respostas. **E a exclusiva so vale se o cancelamento esperar pela
    *thread*** — ver o `ler`, e o `checkpointer.py` do KAM-026, que pagou este
    defeito primeiro.

    **Uma ligacao quebrada larga-se**, pela razao do `trancas.py`: sem isso, um
    corte de rede fazia **todas** as entregas deste processo falharem ate alguem
    reiniciar o servico — um defeito que nao da erro de arranque.
    """

    __slots__ = ("_abrir", "_ligacao", "_exclusiva")

    def __init__(self, abrir_ligacao: Callable[[], Any]) -> None:
        self._abrir = abrir_ligacao
        self._ligacao: Any | None = None
        self._exclusiva = asyncio.Lock()

    async def ler(self, tenant_id: str, contact_id: str) -> Conversa | None:
        """A conversa, numa *thread*, com a tomada a abrir **dentro** dela.

        **A abertura da tomada tambem vai ao executor**, e a primeira versao
        deixava-a na *event loop*: um `connect` do `pg8000` e uma ida a rede com
        apresentacao e autenticacao, e corre-la na *loop* serializava o processo
        inteiro — que tambem serve o `/internal/turn`. Medido pela revisao
        adversarial.

        **E o cancelamento espera pela *thread*.** O `asyncio.to_thread` nao
        cancela nada: um `CancelledError` no `await` desenrolava o `async with`,
        largava o `asyncio.Lock` e deixava a *thread* a meio do protocolo do
        `pg8000` na **mesma** tomada — e a entrega seguinte entrava e usava-a em
        paralelo, que e a corrupcao que a exclusiva existe para evitar. E o
        tratamento do `checkpointer.py` do KAM-026, pela mesma razao e com a
        mesma forma.
        """
        async with self._exclusiva:
            tarefa = asyncio.ensure_future(
                asyncio.to_thread(self._ler_sincrono, tenant_id, contact_id)
            )
            try:
                return await asyncio.shield(tarefa)
            except asyncio.CancelledError:
                # Espera a *thread* acabar antes de largar a exclusiva. Sem
                # isto o `shield` so adia o problema.
                await asyncio.wait([tarefa])
                raise

    def _ler_sincrono(self, tenant_id: str, contact_id: str) -> Conversa | None:
        """A leitura, na *thread*. Abre a tomada a primeira vez."""
        if self._ligacao is None:
            self._ligacao = self._abrir()
        try:
            return ler_conversa_sincrono(self._ligacao, tenant_id, contact_id)
        except Exception:
            ligacao, self._ligacao = self._ligacao, None
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — ja esta quebrada
                pass
            raise

    async def fechar(self) -> None:
        """Fecha a tomada no encerramento ordenado do processo."""
        async with self._exclusiva:
            ligacao, self._ligacao = self._ligacao, None
            if ligacao is None:
                return
            try:
                await asyncio.to_thread(ligacao.close)
            except Exception:  # noqa: BLE001 — a tomada fechada e o que importa
                pass


def thread_do_evento(tenant_id: str, contact_id: str) -> str:
    """O `thread_id` que a tranca usa: `{tenant_id}:{contact_id}`.

    Chama o `thread_id_de` do KAM-025 e nao reescreve o formato, pela razao
    escrita la: um formato que o dicionario fixa (§3.1) tem **um** dono. Existe
    como funcao deste modulo para que quem leia o turno por evento veja que a
    chave e a **mesma** do turno de conversa — e e isso que faz os dois
    serializarem entre si.
    """
    return thread_id_de(tenant_id, contact_id)
