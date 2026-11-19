"""A `PortaDeNotificacao` pela resposta do AGR (KAM-221, sobre o KAM-224).

A porta do cliente do KAM-038 era o `OutboundPorLigar`: devolvia sempre
`sem_template`, e nada saia. Desde o KAM-224 a resposta do AGR sai como uma
linha da `platform.agent_replies` e um `agent.replied`, que o consumidor
`outbound` do `worker-canal` entrega pelo `Saida` do KAM-015. Esta porta e
essa saida, vista de quem notifica um cliente fora de um turno dele: a
proposta do Orcamento expresso, a libertacao da janela e a mensagem das 24 h.

## Quem escolhe entre o texto e o *template* e o AGR (opcao A)

Decisao da coordenacao do lote 13, de 2026-11-19 (bloco do KAM-221). O estado
do pedido depende do desfecho — `enviado` com o texto, `aguarda_janela` com o
*template* — e escreve-se **antes** de o consumidor saber da janela. Por isso a
porta le a `conversations.window_expires_at` e escolhe aqui, com uma margem de
cinco minutos (*proposta*): uma janela que fecha antes disso conta como fechada.
O consumidor obedece e **nunca troca sozinho**.

Se o `Saida` ainda assim recusar o texto por janela fechada — a corrida da
margem —, o `efeitoDoOutbound` regista a resposta como `recusada` e a linha
fica sem `entregue_at`. Voltar a emitir essa resposta com o *template* e da
revisao deste ticket sobre a `agent_replies` (`template_nome`,
`template_parametros`), que espera pela fila das migracoes do lote.

## Sem essa revisao, a janela fechada nao envia nada

A `agent_replies` do KAM-224 so leva texto livre. Com a janela fechada (ou
perto disso) esta porta devolve `sem_template`, que e o desfecho do
`OutboundPorLigar` e o do criterio 6 do KAM-038: nao envia, e o pedido fica
como estava. E o mesmo para uma conversa fora do modo `bot`: o `PreSendGuard`
do KAM-018 recusava o envio do bot, e a proposta ficava `enviado` sem ter
saido.

## A repeticao

A chave da notificacao e a `agent_replies.chave`, e o `UNIQUE (tenant_id,
chave)` faz o segundo `INSERT` nao inserir nem emitir. Uma chave que ja tinha
resposta devolve `livre`: hoje so ha respostas de texto livre.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any, Final

from kamba_core import tenant_guard

from ..saida import RespostaInvalidaError, emitir_resposta
from .notificacao import Notificacao, NotificacaoIndisponivel

#: Quanto antes do fim da janela a porta ja a da por fechada. *Proposta* da
#: coordenacao do lote 13 (2026-11-19): cobre o caminho entre a escolha aqui e
#: o envio no `worker-canal`, que le a mesma coluna com o seu relogio.
MARGEM_DA_JANELA: Final = datetime.timedelta(minutes=5)

#: O unico modo em que o bot envia (`MODO_POR_OMISSAO` do `modos/guarda.ts`).
MODO_DO_BOT: Final = "bot"

#: A janela e o modo da conversa, com a RLS do tenant. As mesmas duas colunas
#: que o `SQL_JANELA` do Outbound le (`outbound/consultas.ts`).
SQL_JANELA_DA_CONVERSA: Final = (
    "SELECT window_expires_at, mode FROM platform.conversations "
    "WHERE tenant_id = %s AND id = %s"
)

LIVRE: Final = "livre"
SEM_TEMPLATE: Final = "sem_template"


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def janela_aberta(
    linha: tuple | None,
    agora: datetime.datetime,
    margem: datetime.timedelta = MARGEM_DA_JANELA,
) -> bool:
    """Se o texto livre pode sair: conversa em modo `bot`, janela aberta alem da margem.

    Uma conversa que nao existe, ou que nunca recebeu nada (`window_expires_at`
    nulo), nao tem janela.
    """
    if linha is None:
        return False
    expira, modo = linha
    if modo != MODO_DO_BOT or expira is None:
        return False
    return expira - margem > agora


class NotificacaoPelaResposta:
    """`notificar(tenant_id, notificacao, chave) -> desfecho`, pela `agent_replies`.

    Uma ligacao `kamba_app` por notificacao, aberta e fechada aqui, pela razao
    da `SaidaPorEvento`: o `tenant_guard` recusa uma segunda transaccao na
    mesma ligacao, e quem chama esta a segurar a sua (o `enviar` do orcamento
    tem a tranca de sessao do pedido).
    """

    __slots__ = ("_abrir", "_relogio", "_margem")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        *,
        relogio: Callable[[], datetime.datetime] = _agora,
        margem: datetime.timedelta = MARGEM_DA_JANELA,
    ) -> None:
        self._abrir = abrir_ligacao
        self._relogio = relogio
        self._margem = margem

    def notificar(self, *, tenant_id: str, notificacao: Notificacao, chave: str) -> str:
        agora = self._relogio()
        try:
            ligacao = self._abrir()
        except Exception as erro:  # noqa: BLE001 — a base em baixo nao e uma decisao
            raise NotificacaoIndisponivel("sem ligacao para a resposta") from erro
        try:
            with tenant_guard.tx(ligacao, tenant_id) as cursor:
                cursor.execute(SQL_JANELA_DA_CONVERSA, (tenant_id, notificacao.conversation_id))
                linha = cursor.fetchone()
            if not janela_aberta(linha, agora, self._margem):
                # shortcut: o *template* com a janela fechada espera pela revisao
                # do KAM-221 sobre a `agent_replies` (`template_nome`); ate la
                # nada sai, como com o `OutboundPorLigar`.
                return SEM_TEMPLATE
            estado = {
                "tenant_id": tenant_id,
                "contact_id": notificacao.contact_id,
                "conversation_id": notificacao.conversation_id,
                "thread_id": f"{tenant_id}:{notificacao.contact_id}",
            }
            emitir_resposta(
                ligacao, estado, notificacao.texto, chave=chave, turno_iniciado_em=agora
            )
            return LIVRE
        except (NotificacaoIndisponivel, RespostaInvalidaError):
            # Uma resposta sem a forma da tabela e defeito de quem chama, e nao
            # uma base em baixo: sobe com o nome dela.
            raise
        except Exception as erro:  # noqa: BLE001 — sobe como ausencia de decisao
            raise NotificacaoIndisponivel("a resposta nao ficou gravada") from erro
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a resposta ja ficou ou ja falhou
                pass


__all__ = [
    "LIVRE",
    "MARGEM_DA_JANELA",
    "MODO_DO_BOT",
    "NotificacaoPelaResposta",
    "SEM_TEMPLATE",
    "SQL_JANELA_DA_CONVERSA",
    "janela_aberta",
]
