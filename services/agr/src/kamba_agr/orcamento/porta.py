"""A porta `orcamentos` das `Dependencias`: o envio depois do botao (KAM-123).

O no `confirm` do grafo do dono chama o `confirmar` do KAM-118; com o desfecho
`confirmada`, chama **esta** porta com o mesmo `action_id`. Ela le a accao, e
so se for uma `enviar_proposta` deste dono tranca o pedido e envia a proposta
pelo Outbound — que e o caminho unico para o cliente (§6.2: nenhuma tool envia
por si).

O Outbound visto daqui e a `PortaDeNotificacao` do KAM-038, e nao a
`PortaDeSaida` do grafo: a proposta vai a **outra** conversa (a do cliente), e
pode encontrar a janela fechada — que e o caso do *template*. Por omissao e o
`OutboundPorLigar`, que devolve `sem_template`: hoje nada sai, e o dono e
avisado de que a proposta nao seguiu (credor do Outbound no bloco).

Uma ligacao por envio, aberta e fechada aqui, pela razao da
`PortaDeConfirmacao`: e raro, e uma tomada guardada pedia um trinco para nada.

**A libertacao da janela tambem passa aqui** (KAM-221): o `libertar` e o
`ao_cliente_escrever` do `ExecutorDeTurnos`, e corre em cada mensagem de um
cliente. Uma ligacao por mensagem, como o `leitor_de_contacto` do
`conversa.py` faz para a leitura do contacto. O envio real e o evento de
resposta do KAM-224: quando ele fundir, a `saida` daqui deixa de ser o
`OutboundPorLigar`.
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable
from typing import Any

from ..contexto import PERSONA_CLIENTE
from ..eventos.notificacao import OutboundPorLigar
from ..tls import orcamento as repositorio


class PortaDeOrcamento:
    """`enviar(tenant_id, contact_id, action_id) -> Envio` e `libertar(invocacao)`, assincronos."""

    __slots__ = ("_abrir", "_saida", "_relogio")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        saida: Any | None = None,
        relogio: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._saida = saida if saida is not None else OutboundPorLigar()
        self._relogio = relogio or (lambda: datetime.datetime.now(datetime.UTC))

    def _enviar(self, tenant_id: str, contact_id: str, action_id: str) -> repositorio.Envio:
        ligacao = self._abrir()
        try:
            return repositorio.enviar(
                ligacao, tenant_id, contact_id, action_id, self._saida, self._relogio()
            )
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — o envio ja aconteceu ou ja falhou
                pass

    async def enviar(self, tenant_id: str, contact_id: str, action_id: str) -> repositorio.Envio:
        return await asyncio.to_thread(self._enviar, tenant_id, contact_id, action_id)

    def _libertar(self, tenant_id: str, contact_id: str) -> list[repositorio.Envio]:
        ligacao = self._abrir()
        try:
            return repositorio.libertar_da_janela(
                ligacao, tenant_id, contact_id, self._saida, self._relogio()
            )
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a libertacao ja aconteceu ou ja falhou
                pass

    async def libertar(self, invocacao: Any) -> list[repositorio.Envio]:
        """O `ao_cliente_escrever` do `ExecutorDeTurnos` (KAM-221, criterio 2).

        Uma mensagem de um **cliente** abre-lhe a janela: as propostas dele em
        `aguarda_janela` saem agora. Uma mensagem do dono (outra persona) nao
        abre a janela de cliente nenhum, e nao se vai a base por ela.
        """
        if getattr(invocacao, "persona", None) != PERSONA_CLIENTE:
            return []
        return await asyncio.to_thread(self._libertar, invocacao.tenant_id, invocacao.contact_id)
