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

    def _com_ligacao(self, funcao: Callable[..., Any], *argumentos: Any) -> Any:
        ligacao = self._abrir()
        try:
            return funcao(ligacao, *argumentos)
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a operacao ja aconteceu ou ja falhou
                pass

    async def enviar(self, tenant_id: str, contact_id: str, action_id: str) -> repositorio.Envio:
        return await asyncio.to_thread(
            self._com_ligacao,
            repositorio.enviar,
            tenant_id,
            contact_id,
            action_id,
            self._saida,
            self._relogio(),
        )

    # ------------------------------------------------------------ KAM-220
    #
    # As duas leituras que os grafos fazem fora da ToolLayer. **Sao leituras**:
    # a escrita do pedido e da resposta e das tools (`request_quote`,
    # `submit_quote`), que passam pelos oito passos do §6.1. Os pendentes sao o
    # que o dono ve na primeira mensagem (criterio 2 do KAM-123); o ultimo
    # pedido e o que decide o «aceito» do cliente (criterio 9).

    async def pendentes(self, tenant_id: str, limite: int = 5) -> list[repositorio.Pendente]:
        return await asyncio.to_thread(
            self._com_ligacao, repositorio.pendentes, tenant_id, limite
        )

    async def ultimo_pedido(
        self, tenant_id: str, contact_id: str
    ) -> repositorio.UltimoPedido | None:
        return await asyncio.to_thread(
            self._com_ligacao, repositorio.ultimo_pedido, tenant_id, contact_id
        )

    async def por_referencia(self, tenant_id: str, referencia: str) -> str | None:
        """O `quote_id` de um `ORC-…` aberto deste tenant, ou `None` (o dono escolhe)."""
        return await asyncio.to_thread(
            self._com_ligacao, repositorio.por_referencia, tenant_id, referencia
        )

    def agora(self) -> datetime.datetime:
        """O relogio da porta, para o grafo julgar a validade com o mesmo instante."""
        return self._relogio()
