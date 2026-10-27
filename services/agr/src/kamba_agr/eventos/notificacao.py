"""As duas saidas de uma notificacao por evento (KAM-038, criterios 6 e 7).

Um evento acorda o AGR para dizer uma coisa a alguem, e esse alguem e um de
dois — e as duas notificacoes **nao partilham caminho nenhum**:

| Destinatario | Porta | Canal | Credor da implementacao |
|---|---|---|---|
| cliente | `PortaDeNotificacao` | WhatsApp, pelo Outbound (janela ou *template*) | KAM-015 e KAM-024 |
| dono | `PortaDeAvisoAoDono` | painel/e-mail do Chatwoot, pelo HND | KAM-019 e KAM-115 |

## Porque e que sao duas portas e nao uma com um argumento

Porque a propriedade do criterio 7 e precisamente «a notificacao ao **dono**
nunca usa o numero da propria loja» (`docs/tecnica/01` §11.4 regra 2), e com uma
porta so essa propriedade era uma condicao dentro de uma funcao — isto e, uma
linha que um dia alguem muda sem saber o que esta a mudar. Com duas, o aviso ao
dono **nao tem** como chegar ao Outbound: ha um teste que lhe poe um espiao e
exige zero chamadas.

A razao para a regra e a de sempre: o numero da loja e um canal de atendimento
ao cliente, e uma mensagem do negocio para si mesmo gastava janela e debito e
aparecia na conversa dos clientes.

## A decisao janela/*template* nao e daqui, e isso esta no criterio

«Notificacao ao cliente com janela aberta e mensagem livre (*service*); com
janela fechada, *template utility* aprovado; sem *template* aprovado → nao envia
e alerta (**decisao do Outbound, KAM-015**)». A tabela do §8.2 vive no
`outbound/decisao.ts`, e duplica-la em Python era ter duas implementacoes da
mesma decisao, uma a divergir — a classe de defeito que o dicionario canonico
existe para evitar.

O que e deste codigo sao duas coisas, e as duas sao verificaveis sem o Outbound:

1. **nenhum caminho manda texto livre com a janela fechada.** A porta recebe
   **sempre** o nome de um *template* ao lado do texto, e uma notificacao sem
   *template* nomeado nao se constroi (`NotificacaoSemTemplateError`). Nao e
   zelo: com o *template* opcional, a janela fechada caia no `sem_template` por
   falta de um campo que quem chama se esqueceu de preencher, e o alerta dizia
   «nao ha *template* aprovado» quando o que havia era um defeito nosso;
2. **o desfecho `sem_template` alerta e levanta.** Nao se engole e, sobretudo,
   **nao se converte em sucesso**: levanta `NotificacaoNaoEntregue` dentro da
   transaccao do consumo, pelo que o `ROLLBACK` leva a marca com ela e a entrega
   vai para a DLQ — visivel e reprocessavel. Contar e seguir deixava uma linha em
   `events_consumed` sem mensagem nenhuma, e no dia em que o KAM-024 aprovasse os
   *templates* a re-entrega dava `duplicado` e o cliente nunca era avisado.
   Achado da revisao adversarial, e era o **unico** caminho que hoje corre.

## A chave de idempotencia, e o que ela compra

`{consumer}:{event_id}:{accao}` — a chave do §6.3, cuja forma o dicionario §3.5
ja fixou. E ela que torna «1 mensagem» uma consequencia e nao uma coincidencia:
o Outbound tem `UNIQUE (tenant_id, idempotency_key)` em `outbound_messages`
(revisao `0010`), pelo que a mesma chave na segunda volta nao enfileira nada.
Sao **duas** accoes e nao uma precisamente para que o aviso ao dono nao seja
engolido como repeticao da notificacao ao cliente.

**E e por isso que a chave nao leva o numero da tentativa.** Uma chave com a
tentativa dentro dava chave nova em cada volta, e com ela uma mensagem nova:
seria o oposto do que o criterio 2 mede.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from ..metricas import METRICA_EVT_NOTIFICACOES, MetricasDoAgr
from .desfechos import DESFECHOS_DA_NOTIFICACAO, DESFECHO_QUE_ALERTA

#: As duas `accao` da chave `consumer:event_id:accao` (dicionario §3.33).
ACCAO_AO_CLIENTE: Final = "notificar_cliente"
ACCAO_AO_DONO: Final = "notificar_dono"

#: O desfecho de um aviso ao dono. Um so, porque nao ha janela nem *template*
#: num painel: o HND aceita ou levanta.
DESFECHO_DO_DONO: Final = "dono"


class NotificacaoSemTemplateError(ValueError):
    """Uma notificacao ao cliente sem *template* nomeado.

    Defeito de quem chama e **nao** um `sem_template`: o `sem_template` e «o
    catalogo nao tem este *template* aprovado», que e uma informacao de negocio,
    e confundir os dois fazia o alerta do criterio 6 disparar por um campo
    esquecido. Ver a *docstring* do modulo.
    """


class NotificacaoNaoEntregue(RuntimeError):
    """A mensagem **nao saiu**, e nao vai sair por esperar (criterio 6).

    E o `sem_template`: a janela esta fechada e o catalogo nao tem *template
    utility* aprovado para este tipo. Levanta **dentro** da transaccao do
    consumo, e isso e a correccao que a revisao adversarial obrigou.

    A primeira versao contava o `sem_template` e seguia. O efeito devolvia
    normalmente, a transaccao confirmava, e o desfecho era `aplicado` — **uma
    linha em `events_consumed` e zero mensagens**. No dia em que o KAM-024
    aprovasse os *templates*, as re-entregas desses eventos davam `duplicado` e
    o cliente **nunca** era avisado. E era o unico caminho que hoje corre,
    porque a porta por omissao devolve sempre `sem_template`.

    Levantando, o `ROLLBACK` leva a marca com ela e a entrega vai para a DLQ com
    o motivo `sem_template` — visivel, alertada e **reprocessavel**. Que e o
    unico desfecho honesto de «nao envia e alerta» sobre uma mensagem que ainda
    tem de sair.
    """


class NotificacaoIndisponivel(RuntimeError):
    """A porta nao conseguiu decidir nem enfileirar.

    Distinta de `sem_template`: aquilo e uma decisao tomada, isto e a ausencia
    de decisao. Sobe, e a entrega e tentada outra vez — porque um Outbound em
    baixo passa, e um *template* que nao existe nao.
    """


@dataclass(frozen=True, slots=True)
class Notificacao:
    """O que se diz, a quem, e com que *template* se a janela estiver fechada.

    `texto` e o conteudo de uma mensagem livre e `template` e o nome do
    *template utility* aprovado que o substitui com a janela fechada. Os dois
    sao obrigatorios, pela razao (1) da *docstring* do modulo.

    **Nao ha aqui `tenant_id` nem telefone.** O `tenant_id` vai a parte, do
    envelope validado; o telefone nunca passa por aqui — «a resolucao de
    destinatario e do Outbound» (Detalhes Tecnicos do bloco), e o que se passa e
    o `contact_id`.
    """

    contact_id: str
    conversation_id: str
    texto: str
    template: str

    def __post_init__(self) -> None:
        if not self.template:
            raise NotificacaoSemTemplateError(
                "uma notificacao ao cliente nomeia sempre o *template utility* que "
                "a substitui com a janela fechada (criterio 6)"
            )


class PortaDeNotificacao(Protocol):
    """O Outbound, visto de um consumidor de eventos (KAM-015).

    **Outra forma que a `PortaDeSaida` do grafo**, e de proposito: aquela recebe
    o estado do turno e enfileira um texto, porque o que a chama e o no `send`
    com uma resposta composta; esta recebe uma `Notificacao` com *template* ao
    lado, porque uma notificacao por evento pode encontrar a janela fechada — o
    que uma resposta a uma mensagem do cliente, por construcao, nao pode.

    Devolve um dos tres primeiros `DESFECHOS_DA_NOTIFICACAO`. Levanta
    `NotificacaoIndisponivel` se nao conseguir decidir.
    """

    def notificar(
        self,
        *,
        tenant_id: str,
        notificacao: Notificacao,
        chave: str,
    ) -> str: ...


class PortaDeAvisoAoDono(Protocol):
    """O HND, para o aviso ao dono (KAM-019, painel/e-mail do Chatwoot).

    **Nao tem `contact_id` nem `conversation_id` de cliente, e e isso que a
    torna segura**: o que o dono precisa de saber e que algo aconteceu no seu
    *tenant*, e o `motivo` e de lista fechada. Sem campos de conversa, nao ha
    por onde esta porta cair no canal do cliente.
    """

    def avisar(self, *, tenant_id: str, motivo: str, chave: str) -> None: ...


class OutboundPorLigar:
    """A porta do cliente, por ligar. KAM-015 entrega o Outbound.

    **Devolve `sem_template` e nao levanta**, e isso nao e uma falha a fingir: e
    o estado do sistema hoje. O catalogo de *templates* aprovados e o KAM-024 e
    nao existe, pelo que **nenhum** *template utility* esta aprovado — e o que o
    criterio 6 manda fazer nesse caso e exactamente nao enviar e alertar.

    Levantar aqui era pior em dois sentidos: fazia a entrega ser tentada seis
    vezes e acabar na DLQ, enchendo-a de eventos que nao tem defeito nenhum; e
    escondia o unico desfecho que o sistema sabe produzir hoje atras de um erro
    de infraestrutura.
    """

    __slots__ = ()

    def notificar(
        self, *, tenant_id: str, notificacao: Notificacao, chave: str
    ) -> str:
        return DESFECHO_QUE_ALERTA


class HndPorLigar:
    """A porta do dono, por ligar. KAM-019 entrega o provedor.

    **Nao levanta**, pela razao do `_hnd_por_ligar` do `__main__.py`: o criterio
    7 mede **por onde** o aviso sai, e a parte que este ticket entrega e a
    escolha do canal. Levantar fazia o evento repetir-se seis vezes e cair na
    DLQ por o painel ainda nao estar ligado, o que e um alarme sobre um ticket e
    nao sobre um sistema.
    """

    __slots__ = ()

    def avisar(self, *, tenant_id: str, motivo: str, chave: str) -> None:
        return None


def chave_da_accao(consumidor: str, event_id: str, accao: str) -> str:
    """`{consumer}:{event_id}:{accao}` — a chave do §6.3.

    Funcao e nao f-string em quem chama, pela razao do `chave_de_envio` do
    KAM-025: um formato que o dicionario fixa tem **um** dono, e escrever o
    separador a segunda vez era deixa-los divergir.
    """
    if accao not in (ACCAO_AO_CLIENTE, ACCAO_AO_DONO):
        raise ValueError(f"accao desconhecida: {accao!r}")
    return f"{consumidor}:{event_id}:{accao}"


class Notificador:
    """As duas saidas, com o contador e o alerta. Sem estado de negocio.

    `metricas` e `aviso` sao opcionais pela mesma razao do `ServicoDeHandoff`:
    um duplo escrito a pressa para poder construir o objecto e um duplo que
    mente.
    """

    __slots__ = ("_cliente", "_dono", "_metricas", "_aviso")

    def __init__(
        self,
        cliente: PortaDeNotificacao | None = None,
        dono: PortaDeAvisoAoDono | None = None,
        metricas: MetricasDoAgr | None = None,
        aviso=None,
    ) -> None:
        self._cliente = OutboundPorLigar() if cliente is None else cliente
        self._dono = HndPorLigar() if dono is None else dono
        self._metricas = metricas
        self._aviso = aviso

    def ao_cliente(
        self, *, consumidor: str, event_id: str, tenant_id: str, notificacao: Notificacao
    ) -> str:
        """Notifica o cliente pelo Outbound. Devolve o desfecho e alerta se preciso."""
        desfecho = self._cliente.notificar(
            tenant_id=tenant_id,
            notificacao=notificacao,
            chave=chave_da_accao(consumidor, event_id, ACCAO_AO_CLIENTE),
        )
        if desfecho not in DESFECHOS_DA_NOTIFICACAO or desfecho == DESFECHO_DO_DONO:
            # Uma porta que devolva outra coisa e uma porta que nao satisfaz o
            # contrato, e deixar passar punha uma etiqueta fora da lista fechada
            # a levantar `EtiquetaInvalida` **dentro** do consumo — isto e, um
            # evento na DLQ por um defeito de quem implementou a porta.
            raise NotificacaoIndisponivel(
                f"a porta devolveu um desfecho que nao e de cliente: {desfecho!r}"
            )
        self._contar(desfecho)
        if desfecho == DESFECHO_QUE_ALERTA:
            self._alertar(desfecho)
            # **Conta, alerta, e levanta.** A ordem importa: o contador e o
            # alerta sao o que o criterio 6 pede («nao envia e alerta»), e
            # medem-se mesmo que ninguem apanhe a excepcao. O levantar e o que
            # impede a marca sem efeito — ver `NotificacaoNaoEntregue`.
            raise NotificacaoNaoEntregue(DESFECHO_QUE_ALERTA)
        return desfecho

    def ao_dono(
        self, *, consumidor: str, event_id: str, tenant_id: str, motivo: str
    ) -> str:
        """Avisa o dono pelo HND. **Nunca toca na porta do cliente.**"""
        self._dono.avisar(
            tenant_id=tenant_id,
            motivo=motivo,
            chave=chave_da_accao(consumidor, event_id, ACCAO_AO_DONO),
        )
        self._contar(DESFECHO_DO_DONO)
        return DESFECHO_DO_DONO

    def _contar(self, desfecho: str) -> None:
        if self._metricas is not None:
            self._metricas.contar(METRICA_EVT_NOTIFICACOES, desfecho)

    def _alertar(self, desfecho: str) -> None:
        if self._aviso is not None:
            self._aviso("evt_notificacao", desfecho)
