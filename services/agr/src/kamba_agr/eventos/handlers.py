"""Os *handlers* de Piloto: o que cada evento manda dizer, e a quem (KAM-038).

Os Detalhes Tecnicos do bloco dao a lista: «Vendedor — `payment.confirmed` v1,
`order.expired` v1, `stock.low` v1; Servicos — `booking.created` v1,
`booking.reminder_due` v1, `payment.confirmed` v1. Acrescentar
`payment.manual_confirmed` v1 a ambas». Quem decide **o destinatario** e o
`docs/tecnica/03` §12, que o escreve tipo a tipo: «`payment.confirmed` ... AGR
(notifica cliente **e** dono)», «`stock.changed` / `stock.low` ... AGR (aviso ao
dono)», «`order.expired` ... AGR».

## Sao deterministicos, e nao e por economia

Nao ha modelo no caminho de um *handler*: ele escolhe entre textos fixos. Duas
consequencias, e as duas sao desenho:

* **nao ha prosa a validar.** O validador de citacao do ADR-007 existe para a
  prosa de um modelo (§9.2, KAM-032); um texto fixo nao cita nada porque **nao
  traz numero nenhum** — nem valor, nem data, nem quantidade. Ver abaixo;
* **nao ha grafo a invocar.** O criterio 5 pede tres propriedades do turno por
  evento (`turn_id = event_id`, sob a tranca, e nao correr com um humano com a
  palavra) e nenhuma e «invoca o grafo». O `ingest` do grafo do Vendedor
  pressupoe uma mensagem do cliente na janela `messages` (KAM-031, §7), e
  dar-lhe um envelope era mudar o no de entrada de um grafo cujo dono e outro
  ticket. Credores: KAM-031 e KAM-035.

**Nenhum texto leva numeros, e isso e uma regra e nao um estilo.** «O seu
pagamento foi confirmado» e verdade sem citar o valor; «O seu pagamento de
24.500 Kz foi confirmado» obriga a comparar o `valor_minor` do envelope com o da
encomenda, que o AGR nao tem, e um valor citado errado numa confirmacao de
pagamento e pior do que um valor omitido. O cliente que quiser o detalhe
pergunta, e ai ha turno, grafo, *facts* e validador.

## O `contact_id` nao esta em cinco dos seis contratos, e isso e um achado

Os Detalhes Tecnicos do bloco dizem «os *payloads* trazem `contact_id`, nunca
telefone». **Dos seis tipos subscritos, so o `booking.created` o traz**: o
catalogo do KAM-007 publicou `payment.confirmed` com
`(order_id, provider, referencia, valor_minor, currency, autenticacao)`,
`payment.manual_confirmed` sem o `provider` e o `referencia`, `order.expired`
com `(order_id, expira_at)` e `booking.reminder_due` com
`(booking_id, inicio_at)`. Nenhum deles diz **a quem** se fala.

O que se faz com isso e o que o repositorio faz sempre: uma porta. O
`PortaDeContacto` resolve `(agregado.tipo, agregado.id) -> contact_id`, e os
credores estao nomeados — o `order` e do **COM** (KAM-041) e o `booking` e do
modulo `servicos` (KAM-047, §8.3). A implementacao por omissao **levanta**, e
isso nao e uma falha a fingir: enquanto ninguem resolver o contacto, um
`payment.confirmed` esgota a escada do §6.4 e abre entrada na DLQ — que e Sev1
pelo §6.4, e **a classificacao esta certa**: «cliente que pagou sem
confirmacao» e exactamente o que acontece. Um alarme honesto vale mais do que um
desfecho `aplicado` sobre uma notificacao que ninguem recebeu.

**O `correlacao_id` do envelope nao serve de atalho.** O §4 descreve-o como
«Conversa **ou** pedido», e um campo que pode ser duas coisas nao enderece
ninguem: usa-lo era arriscar notificar a conversa errada, que num aviso de
pagamento e falar do pagamento de uma pessoa a outra. Fica registado como o
candidato para quem fechar a lacuna com uma emenda ao §4.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from .envelope import Envelope
from .notificacao import Notificacao


class ContactoPorResolver(RuntimeError):
    """Nao se consegue saber a quem falar. Ver a *docstring* do modulo.

    Sobe, e a entrega e tentada outra vez: ao contrario de um envelope
    invalido, um contacto que hoje nao se resolve passa a resolver-se no dia em
    que o COM existir, pelo que a escada do §6.4 e a semantica certa — e o que
    fica na DLQ e reprocessavel por construcao.
    """


class PortaDeContacto(Protocol):
    """`(agregado.tipo, agregado.id) -> contact_id`. Credores: KAM-041, KAM-047.

    **Nao devolve telefone.** O `contact_id` e a referencia a uma pessoa que o
    ADR-010 admite, e a resolucao dele para um numero e do Outbound («a
    resolucao de destinatario e do Outbound», Detalhes Tecnicos do bloco).
    """

    def contacto_de(self, agregado_tipo: str, agregado_id: str) -> str: ...


class ContactoPorLigar:
    """A porta por omissao: levanta `ContactoPorResolver`.

    E a omissao de proposito, pela razao do `ProvedorPorLigar` do KAM-034: uma
    porta obrigatoria fazia quem monta o consumidor escrever um duplo so para o
    poder construir, e um duplo escrito a pressa e um duplo que mente.
    """

    __slots__ = ()

    def contacto_de(self, agregado_tipo: str, agregado_id: str) -> str:
        raise ContactoPorResolver(f"contacto_por_resolver_{agregado_tipo}")


@dataclass(frozen=True, slots=True)
class AccoesDoEvento:
    """O que um *handler* decide: notificar o cliente, o dono, ou os dois.

    Os dois campos podem vir preenchidos ao mesmo tempo — e o caso dos eventos
    de pagamento, que o `03` §12 manda levar a «cliente **e** dono» —, e podem
    vir os dois vazios, que e o caso de um tipo subscrito cuja accao ainda nao
    esta decidida. Um `AccoesDoEvento` vazio **nao** e silencio: quem o recebe
    conta o desfecho e o evento fica consumido com zero efeitos, o que e visivel
    na diferenca entre `agr_evt_consumidos_total` e
    `agr_evt_notificacoes_total`.

    `dono_por` e o `motivo` que vai ao HND, e e o **tipo do evento**: nao se
    inventa um vocabulario de motivos quando o tipo ja e lista fechada e
    canonica (dicionario §3.5). Quem redige o texto do painel e o KAM-019.
    """

    cliente: Notificacao | None = None
    dono_por: str | None = None

    @property
    def toca_o_cliente(self) -> bool:
        """Precisa de conversa e de contacto? Decide se se le a conversa."""
        return self.cliente is not None


#: O texto de cada notificacao ao cliente, **por vertical**. Sem numeros — ver
#: a *docstring* do modulo.
#:
#: **A chave e `(vertical, tipo)` e nao o tipo, e isso e uma correccao da
#: revisao adversarial.** Com a chave no tipo, um *tenant* com as **duas**
#: verticais activas — que e precisamente o *tenant* do *gate* da Fase 0
#: (ADR-012, KAM-108: o Vendedor produz e os Servicos consomem) — recebia a
#: **mesma** mensagem duas vezes sobre o mesmo pagamento: dois consumidores,
#: duas chaves de idempotencia, e a `UNIQUE (tenant_id, idempotency_key)` de
#: `outbound_messages` sem nada para deduplicar. O criterio 2 ficava violado por
#: construcao, e a justificacao do ADR-012 («as duas fazem coisas **diferentes**
#: com o mesmo evento») nao se aplicava, porque faziam a mesma.
#:
#: Portugues de Angola, segunda pessoa de cortesia, sem emojis: a persona dos
#: dois `registry/*.yaml` escreve «cordial, directo, portugues de Angola; sem
#: emojis em excesso». Num mapa e nao em `if`s porque o que distingue as
#: entradas e so o texto, e um `if` por par convidava a por logica entre eles.
TEXTOS: Final[Mapping[tuple[str, str], str]] = {
    ("vendedor", "payment.confirmed"): (
        "O seu pagamento foi confirmado. Vamos preparar o seu pedido."
    ),
    ("vendedor", "payment.manual_confirmed"): (
        "O seu pagamento foi confirmado. Vamos preparar o seu pedido."
    ),
    ("vendedor", "order.expired"): (
        "O seu pedido expirou e foi libertado. Se ainda quiser, podemos fazer outro."
    ),
    ("servicos", "booking.created"): "A sua marcacao esta confirmada.",
    ("servicos", "booking.reminder_due"): (
        "Lembramos a sua marcacao. Se precisar de mudar, diga-nos."
    ),
}

#: Os pares que notificam o **dono**, alem do cliente ou em vez dele.
#: `docs/tecnica/03` §12: `stock.low` e «AGR (aviso ao dono)» e os dois de
#: pagamento sao «AGR (notifica cliente e dono)» — e quem fala com o dono de uma
#: loja e a vertical que vende, nao a que marca.
AO_DONO: Final = (
    ("vendedor", "payment.confirmed"),
    ("vendedor", "payment.manual_confirmed"),
    ("vendedor", "stock.low"),
)

#: Os pares que notificam o **cliente**. Derivado do `TEXTOS` e nao escrito ao
#: lado: um par com texto e sem entrada aqui — ou o contrario — era um *handler*
#: que decide uma coisa e diz outra.
AO_CLIENTE: Final = tuple(TEXTOS)

#: Os pares em que a vertical **subscreve** o tipo e a accao dela **nao esta
#: escrita**. Lista fechada, com o credor na linha.
#:
#: Sao os dois eventos de pagamento na vertical Servicos. O `03` §12 e o §3.5 do
#: dicionario dizem o que ela tem de fazer com eles — «confirma uma marcacao com
#: sinal» —, e isso e o modulo `servicos` (**KAM-047**, §8.3) e o grafo dela
#: (**KAM-035**), nenhum dos dois escrito. Declara-los aqui, em vez de os deixar
#: fora, e o que distingue «ninguem escreveu isto» de «isto nao existe»: o
#: arranque continua a exigir consumidor para **cada** subscricao (criterio 1), e
#: o desfecho do consumo e `sem_accao` — contado, registado, e com credor.
ACCOES_POR_LIGAR: Final[Mapping[tuple[str, str], str]] = {
    ("servicos", "payment.confirmed"): "KAM-047",
    ("servicos", "payment.manual_confirmed"): "KAM-047",
}

#: Todos os pares com *handler*. **E esta a lista que o arranque confronta com
#: as `subscriptions`** (criterio 1): uma subscricao sem entrada e um consumidor
#: registado que nao faz nada e nao o diz.
PARES_COM_HANDLER: Final = tuple(
    sorted(set(AO_CLIENTE) | set(AO_DONO) | set(ACCOES_POR_LIGAR))
)


class SemHandlerError(RuntimeError):
    """Uma subscricao sem *handler*. O AGR sai com `8`.

    E a outra metade do criterio 1: o `validar_subscriptions` do KAM-027 prova
    que o par `(tipo, versao)` **existe** no catalogo, e isto prova que ha
    **codigo** para o par `(vertical, tipo)`. As duas sao precisas, e nenhuma
    substitui a outra.
    """


def exigir_handlers(pares: tuple[tuple[str, str], ...]) -> None:
    """Levanta se alguma subscricao `(vertical, tipo)` nao tiver *handler*."""
    fora = sorted(set(pares) - set(PARES_COM_HANDLER))
    if fora:
        raise SemHandlerError(
            f"as subscricoes {fora} nao tem handler no AGR; os que ha sao "
            f"{list(PARES_COM_HANDLER)} (`docs/tecnica/03` §12)"
        )


def accao_por_ligar(vertical: str, tipo: str) -> str | None:
    """O credor da accao que falta, ou `None` se ela estiver escrita."""
    return ACCOES_POR_LIGAR.get((vertical, tipo))


def fala_com_o_cliente(vertical: str, tipo: str) -> bool:
    """Este par notifica o cliente? Decide se ha conversa, contacto e tranca.

    Levanta `SemHandlerError` para um par sem *handler*: uma subscricao sem
    codigo nao e «nao faz nada» — e um consumidor que marca o evento como
    consumido e nao notifica ninguem, que e o pior dos dois mundos.
    """
    if (vertical, tipo) not in PARES_COM_HANDLER:
        raise SemHandlerError(f"sem handler para ({vertical}, {tipo})")
    return (vertical, tipo) in AO_CLIENTE


def contacto_do_evento(envelope: Envelope, contactos: PortaDeContacto) -> str:
    """O `contact_id`: do *payload* se o contrato o tiver, senao pela porta.

    **Do *payload* primeiro**, e so ele quando existe: o `booking.created` traz
    `contact_id` no contrato (KAM-007), e ir a porta para o confirmar era pedir
    ao COM o que o produtor ja disse — e abrir um caminho em que os dois
    discordam.

    **Corre fora da tranca**, de proposito: um `ContactoPorResolver` sobe antes
    de se tomar a tranca da conversa, e com isso uma entrega sem destinatario
    nao prende a conversa de ninguem.
    """
    do_payload = envelope.payload.get("contact_id")
    if isinstance(do_payload, str) and do_payload:
        return do_payload
    return contactos.contacto_de(envelope.agregado.tipo, envelope.agregado.id)


def accoes_de(
    envelope: Envelope,
    *,
    vertical: str,
    contact_id: str | None,
    conversation_id: str | None,
) -> AccoesDoEvento:
    """O que **esta vertical** faz com este evento, com a conversa ja lida.

    Recebe o `contact_id` e o `conversation_id` em vez de os ir buscar: quem os
    tem e o consumo, que ja abriu a ligacao e ja poe o contexto de *tenant* do
    envelope **validado** — deixar o *handler* ler a base por sua conta era
    abrir o caminho por onde um `tenant_id` do *payload* poderia entrar.
    """
    par = (vertical, envelope.tipo)
    dono_por = envelope.tipo if par in AO_DONO else None
    if not fala_com_o_cliente(vertical, envelope.tipo):
        return AccoesDoEvento(cliente=None, dono_por=dono_por)
    if not contact_id or not conversation_id:
        # **Nao se inventa uma conversa.** Chegar aqui sem conversa quer dizer
        # que ela nao existe, foi apagada, ou que o contexto de RLS e de outro
        # *tenant* (envelope forjado, criterio 4) — e nas tres o certo e nao
        # notificar ninguem. Sobe, e a entrega e tentada outra vez; um
        # `AccoesDoEvento` vazio aqui dizia que o cliente foi avisado.
        raise ContactoPorResolver("conversa_nao_encontrada")
    return AccoesDoEvento(
        cliente=Notificacao(
            contact_id=contact_id,
            conversation_id=conversation_id,
            texto=TEXTOS[par],
            # O `template` e o **tipo do evento** e nao um nome inventado: o
            # nome Meta de um *template* e por *tenant* (`message_templates`,
            # `PRIMARY KEY (tenant_id, name, lang)`, §3.14) e quem o resolve e
            # o Outbound com o catalogo do KAM-024. Escrever aqui nomes de
            # *template* era inventar canon de outro ticket.
            template=envelope.tipo,
        ),
        dono_por=dono_por,
    )
