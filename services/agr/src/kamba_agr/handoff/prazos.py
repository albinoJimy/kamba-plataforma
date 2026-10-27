"""O prazo de 24 h: a varredura que retoma com `outcome=timeout` (criterio 7).

«Sem resposta humana em 24 h o *scheduler* retoma com `outcome=timeout` e o
`handoff_close` envia a mensagem de alternativas (telefone/e-mail/loja) uma so
vez (`key = {hid}:timeout`).»

## Tres pecas, e duas ja existiam

| Peca | Onde |
|---|---|
| achar as passagens que passaram das 24 h | `SQL_HANDOFFS_EXPIRADOS`, aqui |
| retomar com `timeout`, uma so vez por passagem | o CAS do `retoma.py` |
| mandar a mensagem de alternativas, uma so vez | o `handoff_close` do KAM-031, com a chave `{hid}:timeout` |

**A «uma so vez» nao e deste modulo**, e vale dizer onde esta: duas varreduras
a correr ao mesmo tempo — duas replicas, ou uma a demorar mais de um periodo —
veem a **mesma** passagem, e o que as separa e o CAS. A segunda ve zero linhas,
devolve `repetido`, e nao chega ao grafo; o `handoff_close` nem corre. E se
correr duas vezes por outra via (uma repeticao do no apos uma falha), a chave
`{hid}:timeout` do Outbound fecha o resto. Sao duas barreiras independentes,
e e por isso que nao ha coluna de controlo a manter.

## Porque e que a listagem corre como `kamba_batch` e a retoma como `kamba_app`

A listagem atravessa *tenants*: com contexto de um, a RLS devolvia so as
passagens desse, e a varredura teria de saber a lista de *tenants* antes de
varrer. Corre em `tenant_guard.tx_batch`, que e o caminho que o `kamba_core`
abre para os trabalhos de lote e que exige um nome de *job* — o que impede «uso
sem nome nem sem contagem».

A **retoma** de cada passagem corre no caminho normal: contexto do *tenant* da
passagem, sob a tranca da conversa, com o CAS a decidir. Nao se funde a
listagem com a escrita num `UPDATE ... RETURNING` em lote, e e deliberado: um
lote escrevia `timeout` em N passagens antes de retomar grafo nenhum, e a
primeira falha do `Command` deixava as outras N-1 em `timeout` sem o cliente ter
recebido mensagem nenhuma. Uma a uma, cada uma paga a sua falha.

## O relogio e de parede e vem de fora

`relogio` devolve segundos desde a epoca (`time.time`) e nao `monotonic`, pela
razao do `Dependencias` do KAM-031: o `opened_at` esta na base, escrito pelo
`now()` do servidor, e um relogio monotonico nao e comparavel com ele. Vem
injectado porque o ensaio das 24 h corre com relogio simulado, que e o que os
Testes Requeridos do bloco pedem por extenso.

**O limite calcula-se aqui e nao no SQL.** Um `now() - interval '24 hours'`
dentro da consulta era mais curto e tornava o ensaio impossivel: nao ha forma de
simular o relogio **do servidor** de PostgreSQL sem mexer na base. Com o
instante como parametro, a mesma consulta corre contra a base real com o tempo
que o ensaio quiser.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

from kamba_core import tenant_guard

from ..consultas import SQL_HANDOFFS_EXPIRADOS
from ..contexto import thread_id_de
from .maquina import DESFECHO_DO_PRAZO

#: O prazo do `docs/tecnica/01` §11.4 regra 4 e do criterio 7, em segundos.
#: **24 h, e nao e parametro de calibracao**: e a exigencia da Messaging Policy
#: que o §11.4 cita, e nao um numero que o Piloto afine.
PRAZO_SEGUNDOS: Final = 24 * 60 * 60

#: Quantas passagens uma varredura trata, no maximo.
#:
#: *Proposta*. Existe porque uma varredura sem tecto, no dia em que o provedor
#: esteve em baixo um fim de semana, trazia dezenas de milhares de linhas para
#: memoria e falhava — e uma varredura que falha nao retoma nenhuma. Com tecto,
#: trata as mais antigas e a seguinte trata o resto. Calibra-se em KAM-084.
TECTO_POR_VARREDURA: Final = 500

#: O nome do *job* para o `tx_batch`. Snake_case, que e o que ele exige.
JOB: Final = "agr_handoff_prazos"


class Prazos:
    """A varredura das passagens que passaram das 24 h.

    `abrir_ligacao` devolve uma ligacao DB-API **do papel `kamba_batch`** — e
    nao a do `kamba_app` que o `Retomador` usa: sao dois papeis e duas ligacoes,
    porque a listagem atravessa *tenants* e a escrita nao.

    `trancas` e o `TrancaDeConversas` e `retomar` e o `Retomador.retomar`. Os
    dois sao os **mesmos** que a rota usa, de proposito: o criterio 7 diz «o
    *scheduler* retoma», e uma segunda via de retoma que nao passasse pelo CAS
    nem pela tranca era uma segunda implementacao do criterio 3.
    """

    __slots__ = ("_abrir", "_trancas", "_retomar", "_relogio", "_tecto")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        trancas: Any,
        retomar: Callable[[str, str, str], Awaitable[str]],
        relogio: Callable[[], float] = time.time,
        tecto: int = TECTO_POR_VARREDURA,
    ) -> None:
        self._abrir = abrir_ligacao
        self._trancas = trancas
        self._retomar = retomar
        self._relogio = relogio
        self._tecto = tecto

    def limite(self) -> dt.datetime:
        """O instante antes do qual uma passagem a espera ja expirou.

        Em UTC e com fuso, porque a coluna e `timestamptz`: um `datetime` sem
        fuso comparado com `timestamptz` e interpretado no `TimeZone` da sessao,
        e a varredura passava a depender de uma configuracao do servidor.
        """
        return dt.datetime.fromtimestamp(
            self._relogio() - PRAZO_SEGUNDOS, tz=dt.timezone.utc
        )

    def expiradas(self, ligacao: Any) -> list[tuple[str, str, str]]:
        """As passagens expiradas: `(handoff_id, tenant_id, contact_id)`.

        Sincrona e com a ligacao de fora, para que a *suite* do *gate* 8 a corra
        contra a base com a sua propria ligacao — a mesma forma do
        `ler_palavra_sincrono` do `conversa.py`.
        """
        with tenant_guard.tx_batch(ligacao, JOB) as cursor:
            cursor.execute(SQL_HANDOFFS_EXPIRADOS, (self.limite(), self._tecto))
            return [
                (str(linha[0]), str(linha[1]), str(linha[2]))
                for linha in cursor.fetchall()
            ]

    async def varrer(self) -> dict[str, int]:
        """Uma passagem pela varredura. Devolve a contagem por desfecho.

        **Uma falha numa passagem nao para as outras.** Uma base a recusar uma
        retoma, ou um grafo que levante, nao pode impedir as restantes N-1 de
        serem retomadas: a excepcao conta-se como `falhou` e a varredura
        continua. O que se perde e a passagem dessa volta, e a varredura
        seguinte volta a encontra-la — porque a compensacao do `retoma.py` a
        devolveu a `waiting`.

        Devolve um `dict` e nao `None` para que quem a agenda consiga registar o
        que ela fez. Uma varredura que trate zero passagens devolve um `dict`
        com zeros, que e diferente de nao ter corrido.
        """
        ligacao = self._abrir()
        try:
            pendentes = await asyncio.to_thread(self.expiradas, ligacao)
        finally:
            # A ligacao de lote abre-se e fecha-se **por varredura**, ao
            # contrario da do `Retomador`: a varredura corre de hora a hora e
            # uma tomada aberta nesse intervalo e uma tomada que o PostgreSQL
            # conta no `max_connections` para nada.
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a varredura acabou de qualquer forma
                pass

        contagem = {desfecho: 0 for desfecho in ("retomado", "repetido", "recusado")}
        contagem["falhou"] = 0
        for handoff_id, tenant_id, contact_id in pendentes:
            thread_id = thread_id_de(tenant_id, contact_id)
            try:
                async with self._trancas.tomar(thread_id):
                    desfecho = await self._retomar(
                        thread_id, handoff_id, DESFECHO_DO_PRAZO
                    )
            except asyncio.CancelledError:
                raise
            except BaseException:  # noqa: BLE001 — ver docstring
                contagem["falhou"] += 1
                continue
            contagem[desfecho] = contagem.get(desfecho, 0) + 1
        return contagem
