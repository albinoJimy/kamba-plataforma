"""A substituicao de um rascunho pendente quando o humano toma a palavra.

E o criterio 5: «*Echo* do dono (modo `dono`) ou handoff com rascunho `pendente`
marca-o `substituido`; em 100 intercalacoes aleatorias, 0 envios do bot depois
disso».

**O gatilho vive fora do grafo, e tem de viver.** Quem sabe que o humano tomou a
palavra e o `ExecutorDeTurnos`: o `SQL_PALAVRA_DA_CONVERSA` do KAM-025 le o
`conversations.mode` e a existencia de um `handoffs` em `waiting` **na mesma
leitura**, e o `Palavra.do_humano` e o veredicto. Nesse instante o grafo esta
**interrompido** no `draft_wait` — nao ha nó a correr que pudesse marcar nada —,
pelo que a substituicao e uma operacao de fora, como a varredura dos prazos.

**E passa pelo mesmo CAS e pela mesma retoma que um clique**, pela razao que o
`decidir_pelo_sistema` escreve: a corrida e real e nao hipotetica. O dono
responde no WhatsApp no mesmo instante em que o operador carrega em «aprovar»,
e o CAS e o que garante que **um** dos dois vence — se o operador vencer, a
mensagem sai (e foi aprovada); se a substituicao vencer, nao sai nada. O que
nao pode acontecer e as duas valerem.

**E retoma o grafo**, que e a metade que nao se pode esquecer: um rascunho
marcado `substituido` sem retoma deixava o *thread* com um `interrupt` pendente
para sempre, e a invariante do §11 proibe invocar o grafo com *input* novo nesse
estado — a conversa ficava **muda** em vez de passar ao humano.

## O que isto nao cobre, e esta medido

Uma **mensagem nova do cliente** com um rascunho pendente **nao** passa por aqui:
o `Palavra.do_humano` e `False` (a conversa continua em `bot`), o turno entra no
grafo, e o `draft_prepare` abre um rascunho **novo** — medido: duas linhas
`pendente` e dois pedidos de aprovacao para a mesma conversa, com o primeiro
orfao. **Nao sai mensagem nenhuma** (a barreira do criterio 1 aguenta: `envios=0`
nas duas), e o prazo das 24 h fecha o orfao como `expirado`.

Fechar isso pedia que a invariante do §11 soubesse de rascunhos pendentes, e ela
le `conversations.mode` e `handoffs.status` — um rascunho pendente nao aparece em
nenhuma das duas. Acrescentar-lhe uma terceira leitura e mexer no
`SQL_PALAVRA_DA_CONVERSA`, que e do **KAM-025**, e substituir o rascunho a
entrada de cada turno quebrava a reentrega do *job* (o `ON CONFLICT` nao
recriaria o rascunho que a substituicao acabou de fechar). Fica dito, com o
credor, em vez de ficar por dizer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from kamba_core import tenant_guard

from ..handoff.retoma import partes
from .consultas import SQL_PENDENTES_DO_THREAD


class Substituidor:
    """Marca `substituido` os rascunhos pendentes de um *thread*.

    `abrir_ligacao` devolve uma ligacao DB-API do papel `kamba_app`;
    `decidir_pelo_sistema` e o do `Decisor`, o **mesmo** que a varredura usa.

    **A tranca e de quem chama**, como no `Decisor`: o `ExecutorDeTurnos` ja a
    detem quando le a palavra da conversa, e tomar outra aqui dentro era
    aninhar — os *advisory locks* de sessao sao contados e o alcance ficava
    errado (a licao do `Retomador` do KAM-034).
    """

    __slots__ = ("_abrir", "_decidir", "_ligacao", "_exclusiva")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        decidir_pelo_sistema: Callable[[str, str, str], Awaitable[str]],
    ) -> None:
        self._abrir = abrir_ligacao
        self._decidir = decidir_pelo_sistema
        self._ligacao: Any | None = None
        self._exclusiva = asyncio.Lock()

    async def substituir(self, thread_id: str) -> int:
        """Substitui os pendentes deste *thread*. Devolve quantos fechou.

        Devolve **zero** quando nao ha nenhum, que e o caso da vasta maioria das
        conversas (as que nao estao no Piloto concierge, e as que estao sem
        rascunho a espera). Zero nao e erro.

        **Uma falha num rascunho nao para os outros**, pela razao da varredura:
        um *thread* pode ter mais do que um pendente se um turno anterior ficou
        orfao, e deixar os restantes por fechar porque o primeiro falhou era
        perder a propriedade em todos.
        """
        tenant_id, _contact_id = partes(thread_id)
        pendentes = await self._listar(tenant_id, thread_id)
        fechados = 0
        for draft_id in pendentes:
            try:
                await self._decidir(thread_id, draft_id, "substituido")
            except asyncio.CancelledError:
                raise
            except BaseException:  # noqa: BLE001 — ver docstring
                continue
            fechados += 1
        return fechados

    async def _listar(self, tenant_id: str, thread_id: str) -> list[str]:
        async with self._exclusiva:
            try:
                return await asyncio.to_thread(self._sincrono, tenant_id, thread_id)
            except Exception:
                # A razao do `Decisor`: uma ligacao quebrada que fique guardada
                # faz **todas** as substituicoes deste processo falharem.
                ligacao, self._ligacao = self._ligacao, None
                if ligacao is not None:
                    try:
                        ligacao.close()
                    except Exception:  # noqa: BLE001 — ja esta quebrada
                        pass
                raise

    def _sincrono(self, tenant_id: str, thread_id: str) -> list[str]:
        if self._ligacao is None:
            self._ligacao = self._abrir()
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(SQL_PENDENTES_DO_THREAD, (tenant_id, thread_id))
            return [str(linha[0]) for linha in cursor.fetchall()]

    async def fechar(self) -> None:
        """Fecha a ligacao, no encerramento ordenado do processo."""
        async with self._exclusiva:
            ligacao, self._ligacao = self._ligacao, None
            if ligacao is None:
                return
            try:
                await asyncio.to_thread(ligacao.close)
            except Exception:  # noqa: BLE001 — a tomada fecha de qualquer forma
                pass


__all__ = ["Substituidor"]
