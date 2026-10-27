"""O `HandoffService` do §11: a abertura idempotente e a degradacao (KAM-034).

Implementa o `Protocol` `PortaDeHandoff` que o `verticais/vendedor/nos.py`
declarou (KAM-031) e que o no `handoff_prepare` chama. Nao se inventa outra
forma e nao se muda a assinatura: os seis argumentos nomeados sao os do §11, e a
razao de serem seis — e nao o estado inteiro — esta escrita na *docstring* do
`Protocol` (a janela `messages` atravessava para o HND com o texto do cliente
dentro, achado 11 da revisao do KAM-031).

## Onde esta a idempotencia, e porque e que este modulo nao a implementa

O criterio 1 pede que cinco execucoes de `handoff_prepare` — **incluindo uma
falha injectada entre o `openHandoff` e o enfileiramento da mensagem** — dem uma
conversa no HND e uma mensagem ao cliente. Ha tres pecas, e nenhuma e um
contador aqui:

| Peca | Quem a garante |
|---|---|
| o `handoff_id` ser o mesmo em todas as execucoes | o no (`sha256(thread_id:handoff_seq)`, KAM-031) |
| uma conversa no provedor | o `ON CONFLICT (handoff_id) DO NOTHING` do `SQL_ABRIR_HANDOFF` do HND |
| uma mensagem ao cliente | a `UNIQUE (tenant_id, idempotency_key)` de `outbound_messages`, com a chave `{hid}:msg` |

**E e por isso que este servico nao guarda estado.** Um `dict` de
`handoff_id`s ja vistos tornava a propriedade uma propriedade **deste
processo** — perdida no reinicio, invisivel a segunda replica — e, pior, fazia
os ensaios passarem por ele em vez de pela chave. A idempotencia e da base nos
dois sitios, que e a mesma licao que o `SQL_ABRIR_HANDOFF` e o
`SQL_GUARDAR_CONTA` do HND escreveram («verificar primeiro com um `SELECT` e
inserir depois perdia a corrida»).

O que este servico acrescenta e o que nenhuma das tres tem: **o que fazer
quando o provedor nao responde**.

## A degradacao, e as suas tres metades

O §14 do `docs/tecnica/02` escreve-as juntas: «HND/Chatwoot indisponivel ->
`degraded` -> mensagem ao cliente, conversa `pausada`, notificacao ao dono por
canal alternativo». Deste lado:

* o **estado** `degraded` e a **mensagem** sao do no — o `_degradado` do KAM-031
  devolve as duas, e este servico so tem de levantar `HandoffIndisponivel` para
  que a aresta 37 corra;
* a conversa `pausada` e a `PortaDeModos`, chamada **antes** de a excepcao subir
  (ver `abrir`);
* a notificacao ao dono e o **KAM-115** (`docs/tecnica/01` §11.4 regra 2: nao
  pode usar o numero da propria loja), e nao entra aqui.

**A excepcao sobe depois do efeito e nao antes**, e isso e deliberado: se a
pausa levantasse por sua vez, o `handoff_prepare` apanhava `HandoffIndisponivel`
e nao a falha da pausa — a conversa ficava em `bot` com uma passagem degradada,
isto e, o bot a responder a uma conversa que pediu um humano. Por isso a falha
da pausa **substitui** a excepcao original e conta, em vez de ser engolida.
"""

from __future__ import annotations

from typing import Final

from ..metricas import METRICA_HANDOFF, METRICA_HANDOFF_DEGRADADO, MetricasDoAgr
from .maquina import ESTADO_INICIAL
from .portas import HandoffIndisponivel, PortaDeModos, PortaDoProvedor

#: O `motivo` com que a conversa e pausada numa degradacao. E o unico valor que
#: este servico passa a `PortaDeModos`, e existe para que o registo do outro
#: lado diga **porque** e que a conversa parou — uma pausa sem motivo e
#: indistinguivel de um `opt-out` do cliente (§10.2, «qualquer -> pausada»).
MOTIVO_DA_PAUSA: Final = "handoff_degradado"


class ProvedorPorLigar:
    """O `openHandoff` do HND, por ligar. O KAM-019 entrega o provedor.

    **Levanta `HandoffIndisponivel`, e isso nao e uma falha a fingir.** E
    exactamente a linha que o `docs/tecnica/01` §11.5 escreve para «Chatwoot
    indisponivel»: a passagem degrada, o cliente recebe a mensagem de
    degradacao, e o turno acaba sem excepcao nao tratada — que e o criterio 6
    deste ticket, pela aresta 37 da tabela do KAM-031.

    A alternativa — devolver um identificador externo inventado — punha uma
    passagem em `waiting` sem conversa nenhuma no provedor, e nessa o cliente
    ficava a espera de um humano que nunca seria avisado. E a mesma escolha que
    o `_hnd_por_ligar` do `__main__.py` fez do outro lado: a porta existe, a
    decisao esta tomada, e o que falta e o cliente HTTP.

    E a **omissao** do `ServicoDeHandoff`, de proposito: um `provedor`
    obrigatorio fazia quem monta o servico escrever um duplo para o poder
    construir, e um duplo escrito a pressa e um duplo que mente. Assim, o
    servico por omissao degrada — que e o estado honesto do sistema hoje.
    """

    __slots__ = ()

    def abrir(self, **_argumentos: object) -> str:
        raise HandoffIndisponivel("provedor_por_ligar")


class ServicoDeHandoff:
    """A porta `hnd` do `Dependencias` do grafo (KAM-031, §7.4).

    `provedor` e o `openHandoff` do HND (KAM-019). `modos` e a porta que pausa a
    conversa; por omissao e `None`, e nesse caso a degradacao **nao pausa** e
    conta-se de qualquer maneira — que e o estado em que o KAM-018 ainda nao
    ligou a sua ponta. Um `None` silencioso seria pior do que a porta nao
    existir, e por isso ha um contador: `agr_handoff_degradado_total` sobe nos
    dois casos, e o que distingue um painel do outro e a conversa ficar ou nao
    em `pausada`.
    """

    __slots__ = ("_provedor", "_modos", "_metricas")

    def __init__(
        self,
        provedor: PortaDoProvedor | None = None,
        modos: PortaDeModos | None = None,
        metricas: MetricasDoAgr | None = None,
    ) -> None:
        self._provedor = ProvedorPorLigar() if provedor is None else provedor
        self._modos = modos
        self._metricas = metricas

    def abrir(
        self,
        *,
        handoff_id: str,
        tenant_id: str,
        contact_id: str,
        conversation_id: str,
        motivo: str,
        resumo: str,
    ) -> str:
        """Abre a passagem no provedor e devolve o identificador externo.

        Levanta `HandoffIndisponivel` quando o provedor nao aceitou, **depois**
        de pausar a conversa. A ordem importa e esta na *docstring* do modulo.
        """
        try:
            referencia = self._provedor.abrir(
                handoff_id=handoff_id,
                tenant_id=tenant_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                motivo=motivo,
                resumo=resumo,
            )
        except HandoffIndisponivel:
            self._degradar(tenant_id=tenant_id, conversation_id=conversation_id)
            raise
        self._contar(METRICA_HANDOFF, ESTADO_INICIAL)
        return referencia

    def _degradar(self, *, tenant_id: str, conversation_id: str) -> None:
        """Conta a degradacao e pausa a conversa, se houver quem a pause.

        **Conta antes de pausar**, e nao e indiferente: uma pausa que levante
        faz a excepcao subir daqui, e o contador que ficasse depois nunca
        registava a degradacao que **aconteceu** — o provedor falhou de
        qualquer maneira. O que o `agr_handoff_degradado_total` mede e a falha do
        provedor, nao o sucesso da pausa.
        """
        self._contar(METRICA_HANDOFF_DEGRADADO, None)
        self._contar(METRICA_HANDOFF, "degraded")
        if self._modos is None:
            return
        self._modos.pausar(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            motivo=MOTIVO_DA_PAUSA,
        )

    def _contar(self, metrica: str, etiqueta: str | None) -> None:
        if self._metricas is not None:
            self._metricas.contar(metrica, etiqueta)
