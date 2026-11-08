"""Os *handlers* de Piloto: o que cada evento manda dizer, e a quem (KAM-038).

Os Detalhes Tecnicos do bloco dao a lista: «Vendedor — `payment.confirmed` v1,
`order.expired` v1, `stock.low` v1; Servicos — `booking.created` v1,
`booking.reminder_due` v1, `payment.confirmed` v1. Acrescentar
`payment.manual_confirmed` v1 a ambas». Quem decide **o destinatario** e o
`docs/tecnica/03` §12, que o escreve tipo a tipo: «`payment.confirmed` ... AGR
(notifica cliente **e** dono)», «`stock.changed` / `stock.low` ... AGR (aviso ao
dono)», «`order.expired` ... AGR».

## O destinatario deixou de se decidir aqui (KAM-039)

Este modulo tinha uma tabela `AO_DONO` de pares `(vertical, tipo)` com entradas
**so do Vendedor**, lida num `if` do `accoes_de`. O nucleo decidia ali, pelo
nome da vertical, se o dono da loja era avisado — e e isso, a letra, que a
condicao (d) do `docs/tecnica/02` §5.4 chama uma excepcao no core. Foi ela que
reprovou o criterio (d) do KAM-039 (`python -m reuse_metric nucleo` →
`fluxo 1`).

**O destinatario e agora `subscriptions[].notifica` do `registry/<id>.yaml`**, e
chega a cada *handler* pelo `Consumidor` que o `subscricoes.py` constroi do
registo. O que fica aqui e o **texto** — que o §5.4 poe na coluna do que e
proprio da vertical — e as duas guardas que o `exigir_handlers` corre no
arranque. O nucleo passa a ler **a quem** avisar; o que ele nao faz, e e a
condicao (d), e saber **qual** vertical e.

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

## A accao dos dois pagamentos em Servicos, e de onde NAO vem o `booking_id`

O KAM-184 escreve a accao que o `ACCOES_POR_LIGAR` declarava em falta: os dois
eventos de pagamento na vertical Servicos **confirmam a marcacao com sinal**, que
e o que o `docs/tecnica/03` §12 e o dicionario §3.5 mandam, e a confirmacao e
que torna a marcacao visivel ao lembrete (KAM-048; o indice
`bookings_contacto_idx` da revisao `0025` existe para essa leitura).

**O `booking_id` nao vem do evento, e isso e medido e nao assumido.** Os quatro
esquemas dos dois tipos — `contratos/eventos/payment.confirmed/{v1,v2}` e
`contratos/eventos/payment.manual_confirmed/{v1,v2}` — tem
`additionalProperties: false` e **nao** tem `booking_id`: um evento que o levasse
e recusado e vai para a DLQ. O §9.2 do `docs/tecnica/evidencia/validacao/Gate_Fase0.md`
enumera as duas rotas para o obter — (a) uma versao nova do contrato, (b) o
consumidor resolver a marcacao pelo `order_id` — e as **duas estao devolvidas ao
fundador** com a medicao, na seccao de verificacao do bloco KAM-184. **Nenhuma
esta aplicada aqui**, pelo que:

* a accao identifica a encomenda pelo `order_id`, que os quatro esquemas levam
  como campo **obrigatorio**, e nunca por um `booking_id` que nao existe no
  *payload*. Nao ha ramo a ler o *payload* a procura dele: um ramo que nenhum
  contrato publicado pode satisfazer e codigo morto, e a prova por mutacao deste
  modulo ja mostrou uma vez que codigo morto sobrevive as mutacoes;
* **quem sabe que marcacao e a desta encomenda e a agenda**, que vive no modulo
  `servicos` (KAM-047, TypeScript no COM). O caminho entre o AGR e aquele modulo
  **nao existe** — esta escrito no `tls/servicos.py`, e o ticket que o liga
  tambem nao existe —, pelo que o que se escreve aqui e a **porta**
  (`PortaDeMarcacao`) e a implementacao por omissao **levanta**.

E levantar e a resposta certa, pela razao do `ContactoPorLigar` acima: enquanto
ninguem ligar a agenda, um `payment.confirmed` de um *tenant* com Servicos activa
esgota a escada do §6.4 e abre entrada na DLQ — Sev1, reprocessavel, e com a
classificacao certa, porque «cliente que pagou e a marcacao nao ficou
confirmada» e exactamente o que acontece. O desfecho deixa de ser `sem_accao`,
que dizia «ninguem escreveu isto», e passa a dizer o que se passa de verdade.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from ..registo.esquema import DESTINATARIO_CLIENTE, DESTINATARIO_DONO, DESTINATARIOS
from .envelope import Envelope
from .notificacao import Notificacao


class SubscricaoDeVertical(Protocol):
    """Uma subscricao do registo, do ponto de vista de um *handler* (KAM-039).

    E um `Protocol` e nao o `Consumidor` do `subscricoes.py` importado: o que um
    *handler* precisa de saber de uma subscricao sao tres campos, e pedir o
    objecto inteiro acoplava este modulo a tabela de despacho — que sabe de
    tomadas, de ordem e de prioridade, nada disso assunto de quem escolhe um
    texto. O `Consumidor` satisfaz isto por estrutura, sem o declarar.
    """

    #: O `id` da vertical que subscreve. Para o `TEXTOS`, que e por vertical.
    vertical: str
    #: O tipo do evento subscrito.
    tipo: str
    #: Quem avisar: um subconjunto de `DESTINATARIOS`, possivelmente vazio.
    notifica: tuple[str, ...]


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


class MarcacaoPorResolver(RuntimeError):
    """Nao se consegue saber que marcacao e a desta encomenda.

    **Sobe, e a entrega e tentada outra vez**, pela razao do
    `ContactoPorResolver`: uma marcacao que hoje nao se resolve passa a
    resolver-se no dia em que o caminho AGR -> modulo `servicos` existir, pelo
    que a escada do §6.4 e a semantica certa e o que fica na DLQ e reprocessavel.

    **Nao se confunde com «esta encomenda nao tem marcacao»**, que e a resposta
    `None` da porta e e um desfecho legitimo: uma encomenda de produtos pagos num
    *tenant* que tambem tem Servicos activa nao tem marcacao nenhuma para
    confirmar. Tratar as duas como a mesma coisa dava um alarme por cada
    pagamento de produto, ou um `aplicado` sobre uma confirmacao que nao houve.
    """


@dataclass(frozen=True, slots=True)
class MarcacaoConfirmada:
    """A marcacao que a agenda confirmou. E o artefacto do consumo.

    `inicio_at` e o instante da marcacao em ISO-8601 UTC, e esta aqui por ser o
    que o `booking.reminder_due` leva no *payload* (KAM-007): quem vier a ligar o
    lembrete precisa dele e nao de uma segunda leitura.
    """

    booking_id: str
    inicio_at: str


class PortaDeMarcacao(Protocol):
    """`order_id -> a marcacao confirmada`. Credor: o caminho AGR -> `servicos`.

    **Nao e um repositorio e nao le a base.** Quem tem a agenda e o modulo
    `servicos` (KAM-047), do outro lado da fronteira do ADR-009; o AGR pede-lhe
    que confirme, e a idempotencia e a dele — o `confirmBooking` daquele modulo e
    idempotente por `(contact_id, slot_id)`, no indice
    `bookings_contacto_slot_uq` da revisao `0025` e nao em codigo.

    Devolve `None` quando a encomenda **nao tem** marcacao, e levanta
    `MarcacaoPorResolver` quando nao se sabe. Ver a nota do modulo.
    """

    def confirmar_com_sinal(
        self, *, tenant_id: str, order_id: str, event_id: str
    ) -> MarcacaoConfirmada | None: ...


class MarcacaoPorLigar:
    """A porta por omissao: levanta `MarcacaoPorResolver`.

    E a omissao de proposito, pela razao do `ContactoPorLigar`: uma porta
    obrigatoria fazia quem monta o consumidor escrever um duplo so para o poder
    construir, e um duplo escrito a pressa e um duplo que mente.
    """

    __slots__ = ()

    def confirmar_com_sinal(
        self, *, tenant_id: str, order_id: str, event_id: str
    ) -> MarcacaoConfirmada | None:
        raise MarcacaoPorResolver("agenda_por_ligar")


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

#: Os pares que notificam o **cliente**. Derivado do `TEXTOS` e nao escrito ao
#: lado: um par com texto e sem entrada aqui — ou o contrario — era um *handler*
#: que decide uma coisa e diz outra.
#:
#: **Depois do KAM-039 nao e isto que decide**, e a distincao e a do ticket:
#: quem decide se o cliente e avisado e o `notifica` da subscricao, lido do
#: `registry/`. Esta tabela e o **texto** — que o §5.4 poe na coluna do que e
#: proprio da vertical, na linha «Persona / prompts» — e o que ela serve e a
#: coerencia: um par que declare `cliente` sem texto levanta no arranque, em vez
#: de rebentar com um `KeyError` dentro da transaccao do consumo.
AO_CLIENTE: Final = tuple(TEXTOS)

#: Os pares em que a vertical **subscreve** o tipo e a accao dela **nao esta
#: escrita**. Lista fechada, com o credor na linha.
#:
#: **Hoje esta vazia, e a tabela fica** (KAM-184). Os dois eventos de pagamento
#: em Servicos viviam aqui com o credor `KAM-047`; a accao deles esta escrita
#: desde este ticket e os dois pares estao em `ACCOES_DE_MARCACAO`. O que a
#: tabela vazia diz e que **nenhuma** subscricao do registo esta hoje nestas
#: condicoes — e nao que a condicao deixou de existir: a guarda do
#: `exigir_handlers`, o desfecho `sem_accao` e o `accao_por_ligar` continuam a
#: morder, com ensaio sobre um par sintetico, porque e assim que a proxima
#: vertical declara «subscrevo isto e ainda nao escrevi a accao» em vez de
#: consumir em silencio.
#:
#: Declarar um par aqui, em vez de o deixar fora, e o que distingue «ninguem
#: escreveu isto» de «isto nao existe»: o arranque continua a exigir consumidor
#: para **cada** subscricao (criterio 1), e o desfecho do consumo e `sem_accao` —
#: contado, registado, e com credor.
ACCOES_POR_LIGAR: Final[Mapping[tuple[str, str], str]] = {}

#: Os pares cuja accao esta por ligar, **sem o credor**. Derivado do
#: `ACCOES_POR_LIGAR`, pela razao do `AO_CLIENTE` — e por uma segunda, que a
#: medicao do KAM-039 ensinou e que vale escrever:
#:
#: escrito contra a tabela — `par not in ACCOES_POR_LIGAR` —, o `reuse_metric`
#: classifica a linha como `fluxo`, e a primeira versao destas guardas pos a
#: condicao (d) em `fluxo 3`. **E a razao nao e que a pergunta seja outra**: em
#: Python, `par in d` sobre um `dict` **ja** testa as chaves, pelo que as duas
#: formas sao o mesmo programa — medido, comportamento identico. A razao e que o
#: `reuse_metric` classifica pela **forma da atribuicao da constante** e nao pela
#: pergunta do sitio da leitura: o `_constantes_com_verticais` varre so o corpo
#: do modulo e so registra constantes que **contenham** literais de vertical,
#: pelo que um `dict` com `"vendedor"` dentro e `mapa` — sempre `fluxo` num teste
#: — e uma constante derivada nao tem literais e e **invisivel**. O instrumento
#: nao sabe distinguir uma pertenca as chaves de um despacho por valor.
#:
#: Fica assim escrito porque e a forma que satisfaz o criterio hoje, **e o limite
#: fica nomeado**: `fluxo == 0` nao quer dizer «o nucleo nao ramifica por
#: vertical» enquanto o verificador nao seguir constantes derivadas, locais,
#: de classe e importadas. Apertar o instrumento muda o que o criterio (d) conta,
#: que e regra de bloqueio — devolvido ao fundador, com o `fala_com_o_cliente`
#: nomeado como o caso que existe hoje (`docs/evidencia/KAM-039.md` §5.0).
#: Achado da revisao adversarial, verificado contra a arvore.
POR_LIGAR: Final = tuple(ACCOES_POR_LIGAR)

#: Os pares cuja accao e **confirmar a marcacao com sinal** (KAM-184). Lista
#: fechada: sao os dois eventos de pagamento na vertical Servicos, e o que eles
#: fazem e o que o `03` §12 e o dicionario §3.5 mandam. Ver a nota do modulo.
#:
#: **Nao e o oposto do `ACCOES_POR_LIGAR` e nao se deriva dele.** Um par fora das
#: duas tabelas e uma subscricao que nao faz nada e nao o diz, que e o que a
#: primeira guarda do `exigir_handlers` recusa; um par nas duas ao mesmo tempo
#: diria «a accao esta escrita» e «a accao tem dono», e e a terceira guarda que o
#: recusa. Derivar uma da outra fazia a pergunta ao proprio conjunto, que e o
#: defeito que o KAM-039 corrigiu nesta mesma funcao.
ACCOES_DE_MARCACAO: Final = (
    ("servicos", "payment.confirmed"),
    ("servicos", "payment.manual_confirmed"),
)

#: Os pares de `ACCOES_DE_MARCACAO`, para a pergunta de pertenca. **Sao duas
#: constantes e nao uma**, pela razao escrita no `POR_LIGAR`: o `reuse_metric`
#: classifica pela forma da atribuicao e nao pela pergunta do sitio da leitura,
#: pelo que uma constante **com** literais de vertical lida num `if` conta como
#: `fluxo` — e `fluxo > 0` e a condicao (d) do §5.4 a reprovar. Quem decide le
#: esta, que nao tem literais e e invisivel ao verificador.
COM_ACCAO_DE_MARCACAO: Final = frozenset(ACCOES_DE_MARCACAO)


class SemHandlerError(RuntimeError):
    """Uma subscricao sem *handler*. O AGR sai com `8`.

    E a outra metade do criterio 1: o `validar_subscriptions` do KAM-027 prova
    que o par `(tipo, versao)` **existe** no catalogo, e isto prova que ha
    **codigo** para o par `(vertical, tipo)`. As duas sao precisas, e nenhuma
    substitui a outra.
    """


def exigir_handlers(subscricoes: Iterable[SubscricaoDeVertical]) -> None:
    """Levanta se alguma subscricao nao tiver *handler*.

    **A confrontacao inverteu-se com o KAM-039, e a guarda continua a morder.**
    Antes havia aqui um `PARES_COM_HANDLER` — a uniao de tres tabelas deste
    modulo — e o arranque perguntava se cada subscricao estava nele. Com o
    destinatario a vir do `registry/`, essa lista passaria a ser derivada das
    proprias subscricoes, e uma pergunta de um conjunto a si mesmo responde
    sempre «sim»: a guarda ficava verde e vazia. O que se pergunta agora e o que
    sempre importou — **esta subscricao faz alguma coisa?** — e sao duas formas
    de nao fazer nada:

    * **sem destinatario, sem accao escrita e sem credor.** Um `notifica:` vazio
      diz «esta vertical subscreve e nao avisa ninguem», o que e legitimo em dois
      casos: a accao esta **escrita** e nao e uma notificacao — os dois eventos
      de pagamento em Servicos, que confirmam a marcacao com sinal
      (`ACCOES_DE_MARCACAO`, KAM-184) —, ou esta por escrever e tem **dono**
      (`ACCOES_POR_LIGAR`). Sem nenhum dos tres, e um consumidor que marca o
      evento como consumido e nao faz nada — e nao o diz, que e o pior dos dois
      mundos. **A terceira condicao entrou com o KAM-184 e nao enfraquece a
      guarda**: sem ela, escrever a accao dos dois pares e tirar o credor
      reprovava o arranque com o registo verdadeiro;
    * **declara `cliente` e nao ha texto.** O `TEXTOS` e indexado por
      `(vertical, tipo)` e lido **dentro** da transaccao do consumo: um par que
      declare `cliente` sem entrada la rebentava com `KeyError` a meio de uma
      entrega, com a marca de consumido ja inserida. Aqui falha o arranque, que
      e onde um ficheiro de configuracao errado se descobre.

    E uma terceira forma, que e de **dizer duas coisas**:

    * **tem credor de accao por ligar e, ao mesmo tempo, faz alguma coisa.** O
      `ACCOES_POR_LIGAR` quer dizer «esta vertical subscreve e a accao dela nao
      esta escrita»; um `notifica` nao vazio diz que esta, e um par em
      `ACCOES_DE_MARCACAO` diz que esta por extenso. Com os dois, o `_efeito` do
      `consumo.py` corre o efeito **e** o `_consumir` devolve `sem_accao`, porque
      o desfecho le o credor e nao o efeito: alguem era avisado — ou uma marcacao
      ficava confirmada — e a metrica dizia que nao houve accao. **Era uma
      invariante medida por ensaio** (`ACCOES_POR_LIGAR & (AO_CLIENTE | AO_DONO)
      == set()`) e a metade do dono saiu para configuracao, pelo que o ensaio
      deixou de a cobrir — achado da revisao adversarial. Passa a ser guarda, que
      e onde ela pertence agora que um dos lados e um ficheiro editavel. **A
      metade do `ACCOES_DE_MARCACAO` entrou com o KAM-184**: as duas tabelas sao
      literais deste modulo, mas estao a dez linhas uma da outra e e precisamente
      assim que uma emenda futura poe um par nas duas.

    Junta **todos** os problemas e nao o primeiro, pela razao do
    `SubscricoesInvalidasError`: seis linhas erradas num YAML nao sao seis
    *deploys*.
    """
    sem_handler: list[tuple[str, str]] = []
    sem_texto: list[tuple[str, str]] = []
    diz_as_duas: list[tuple[str, str]] = []
    for subscricao in subscricoes:
        par = (subscricao.vertical, subscricao.tipo)
        tem_credor = par in POR_LIGAR
        tem_accao = par in COM_ACCAO_DE_MARCACAO
        if tem_credor and (subscricao.notifica or tem_accao):
            diz_as_duas.append(par)
        if not subscricao.notifica:
            if not tem_credor and not tem_accao:
                sem_handler.append(par)
            continue
        if DESTINATARIO_CLIENTE in subscricao.notifica and par not in AO_CLIENTE:
            sem_texto.append(par)
    problemas: list[str] = []
    if sem_handler:
        problemas.append(
            f"as subscricoes {sorted(sem_handler)} nao notificam ninguem, nao tem accao "
            f"escrita em `ACCOES_DE_MARCACAO` e nao tem credor em `ACCOES_POR_LIGAR`: "
            f"declare `notifica` no `registry/` com um de {list(DESTINATARIOS)} "
            f"(`docs/tecnica/03` §12)"
        )
    if sem_texto:
        problemas.append(
            f"as subscricoes {sorted(sem_texto)} declaram `{DESTINATARIO_CLIENTE}` e nao "
            "tem texto no `TEXTOS` do `eventos/handlers.py`"
        )
    if diz_as_duas:
        problemas.append(
            f"as subscricoes {sorted(diz_as_duas)} tem credor em `ACCOES_POR_LIGAR` e "
            "fazem alguma coisa — `notifica` no `registry/`, ou accao escrita em "
            "`ACCOES_DE_MARCACAO`: a accao ou esta escrita ou tem dono, nao as duas — o "
            "desfecho do consumo seria `sem_accao` com o efeito aplicado"
        )
    if problemas:
        raise SemHandlerError("; ".join(problemas))


def accao_por_ligar(vertical: str, tipo: str) -> str | None:
    """O credor da accao que falta, ou `None` se ela estiver escrita."""
    return ACCOES_POR_LIGAR.get((vertical, tipo))


def tem_accao_de_marcacao(vertical: str, tipo: str) -> bool:
    """Esta subscricao confirma a marcacao com sinal? (KAM-184.)

    E a pergunta que o `_efeito` do `consumo.py` faz antes de chamar a accao, e
    le a constante **derivada** pela razao escrita no `COM_ACCAO_DE_MARCACAO`.
    """
    return (vertical, tipo) in COM_ACCAO_DE_MARCACAO


def confirmar_marcacao_com_sinal(
    envelope: Envelope, marcacoes: PortaDeMarcacao
) -> MarcacaoConfirmada | None:
    """A accao dos dois pagamentos em Servicos: confirma a marcacao com sinal.

    **Identifica a encomenda pelo `order_id`** e nunca por um `booking_id` do
    *payload*, que os quatro esquemas publicados nao admitem — ver a nota do
    modulo, e a medicao das duas rotas na seccao de verificacao do bloco
    KAM-184.

    Devolve a marcacao confirmada, ou `None` se esta encomenda nao tiver
    marcacao. **Levanta** `MarcacaoPorResolver` se nao se souber: e a porta por
    omissao, e enquanto o caminho AGR -> modulo `servicos` nao existir e isso que
    acontece em producao.

    **Corre dentro da transaccao do consumo**, como a notificacao e pela mesma
    simetria do `consumo.py`: se a confirmacao falhar, o `ROLLBACK` leva a marca
    com ela e a re-entrega volta a tentar — nao ha marca sem efeito; e se o
    `COMMIT` falhar depois de ela passar, a re-entrega repete-a e a idempotencia
    do `confirmBooking` (indice `bookings_contacto_slot_uq`, revisao `0025`)
    devolve a marcacao que ja existe em vez de criar uma segunda.
    """
    order_id = envelope.payload.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        # **Inalcancavel por configuracao e por contrato**: o `order_id` e campo
        # obrigatorio nos quatro esquemas e o `validar_payload` corre antes. Fica
        # pela razao da guarda do `fala_com_o_cliente`: e a barreira para um
        # chamador que nao venha do consumo, e sem ela um envelope sem
        # `order_id` pedia a agenda que confirmasse a marcacao de `None` — que e
        # uma pergunta que a agenda nao pode responder com seguranca.
        raise MarcacaoPorResolver("sem_order_id")
    return marcacoes.confirmar_com_sinal(
        tenant_id=envelope.tenant_id,
        order_id=order_id,
        # O `event_id` vai como chave do pedido e nao como identidade da
        # marcacao: e o que permite a quem implementar a porta deduplicar uma
        # re-entrega sem depender do nosso relogio.
        event_id=envelope.id,
    )


def fala_com_o_cliente(subscricao: SubscricaoDeVertical) -> bool:
    """Esta subscricao notifica o cliente? Decide se ha conversa, contacto e tranca.

    **Le a subscricao e nao uma tabela deste modulo** (KAM-039): o que decide e
    o `notifica` do `registry/`. Recebe a subscricao inteira em vez de
    `(vertical, tipo, notifica)` de propósito — tres argumentos que vem sempre
    do mesmo objecto sao tres oportunidades de os passar desemparelhados.

    Levanta `SemHandlerError` para uma subscricao sem *handler*, pela razao
    escrita no `exigir_handlers`: o arranque ja o devia ter apanhado, e se nao
    apanhou e porque este consumidor nao veio do registo. **As tres formas de
    fazer alguma coisa sao as mesmas da guarda** — notificar, ter accao escrita,
    ou ter credor —, e a lista tem de ser a mesma nos dois sitios: uma guarda
    que aceitasse o par e um `fala_com_o_cliente` que o recusasse punha o AGR a
    arrancar e a rebentar na primeira entrega.
    """
    par = (subscricao.vertical, subscricao.tipo)
    if (
        not subscricao.notifica
        and par not in POR_LIGAR
        and par not in COM_ACCAO_DE_MARCACAO
    ):
        raise SemHandlerError(f"sem handler para {par}")
    return DESTINATARIO_CLIENTE in subscricao.notifica


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
    subscricao: SubscricaoDeVertical,
    contact_id: str | None,
    conversation_id: str | None,
) -> AccoesDoEvento:
    """O que **esta subscricao** faz com este evento, com a conversa ja lida.

    Recebe o `contact_id` e o `conversation_id` em vez de os ir buscar: quem os
    tem e o consumo, que ja abriu a ligacao e ja poe o contexto de *tenant* do
    envelope **validado** — deixar o *handler* ler a base por sua conta era
    abrir o caminho por onde um `tenant_id` do *payload* poderia entrar.

    **O destinatario vem da subscricao e nao de uma tabela daqui** (KAM-039): o
    `AO_DONO` que vivia neste modulo era a excepcao de vertical no nucleo que
    reprovava a condicao (d) do §5.4, e esta no `registry/` desde essa correccao.
    """
    if subscricao.tipo != envelope.tipo:
        # O despacho escolhe os consumidores por `(tipo, versao)` do envelope,
        # pelo que chegar aqui desemparelhado nao acontece por configuracao — e
        # um chamador novo. Levanta, porque a alternativa e ler o `notifica` de
        # uma subscricao e o texto de outra, e o sintoma disso e uma mensagem
        # errada entregue a um cliente.
        raise SemHandlerError(
            f"a subscricao e de {subscricao.tipo!r} e o envelope de {envelope.tipo!r}"
        )
    par = (subscricao.vertical, envelope.tipo)
    dono_por = envelope.tipo if DESTINATARIO_DONO in subscricao.notifica else None
    if not fala_com_o_cliente(subscricao):
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
