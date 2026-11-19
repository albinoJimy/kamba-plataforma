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
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable
from typing import Any

from ..eventos.notificacao import OutboundPorLigar
from ..tls import orcamento as repositorio


class PortaDeOrcamento:
    """`enviar(tenant_id, contact_id, action_id) -> Envio`, assincrono."""

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
