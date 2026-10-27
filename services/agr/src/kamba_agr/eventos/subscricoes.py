"""Das `subscriptions` do registo aos consumidores do AGR (KAM-038, criterio 1).

«As verticais nao se chamam entre si: subscrevem eventos do EVT» (ADR-009), e o
que cada uma subscreve esta no seu `registry/<id>.yaml` (KAM-027, §5.1). Este
modulo le essa lista e produz a tabela de consumidores: **um consumidor por cada
`{tipo, versao}` de cada vertical**, e um arranque que falha se algum `tipo` ou
alguma `versao` nao tiver contrato publicado.

## A validacao e a do KAM-027, e nao uma segunda

O criterio 1 pede que «`tipo`/`versao` desconhecidos reprovam o arranque
(**partilha a validacao de KAM-027**)», e a palavra e essa: o
`registo.validar.validar_subscriptions` ja confronta cada par com o
`kamba_core.eventos.contratos.CATALOGO` e ja e a validacao (4) do §5.2. Escrever
aqui uma segunda era ter duas a dizer o mesmo, e a divergir no dia em que o
catalogo mudasse — a classe de defeito que o `ten/consultas.py` nomeia por
extenso.

O que este modulo acrescenta e o que aquela nao faz: **recusar o arranque**
quando o registo valida mas nao ha consumidor nenhum para uma subscricao, e dar
a tabela por `(tipo, versao)` que o despacho le.

## O `consumer` e por vertical, e isso decide o que «uma linha» quer dizer

O `consumer` e a primeira metade da chave de `platform.events_consumed` e de
`platform.events_dlq`. Com um consumidor por `(vertical, tipo)`, o mesmo
`payment.confirmed` entregue as duas verticais dava **quatro** linhas e quatro
efeitos; com um por vertical, da duas — uma por vertical, que e o que a regra de
dois do ADR-012 exige e o que torna verdadeira a contagem «1 linha em
`events_consumed`» do criterio 2. Dicionario §3.33.

O nome e `agr_` mais o `id` da vertical, **derivado** e nao escrito a mao: e a
licao do `metricas.py` do KAM-027 («uma lista literal transforma uma invariante
num numero»), e e o que faz o `agr_evt_lag_ms` ganhar um eixo novo no dia em que
uma vertical nascer, sem passar por aqui.

## `exige_ordem` nao e opcao nossa

«Os consumidores de `payment.*` sao **sempre** com ordem» (§6.3), e a revisao
`0005` escreve-o como restricao de base
(`evt_subscricoes_payment_exige_ordem`). Deriva-se do prefixo do tipo e nao se
le de ficheiro nenhum: um `exige_ordem: false` escrito num YAML para um
`payment.*` seria uma configuracao que a base recusa e que este processo
aceitava.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ..registo.esquema import VerticalDoRegisto
from ..registo.validar import AmbienteDoRegisto, validar_subscriptions

#: O prefixo do `consumer` de uma vertical. Dicionario §3.33.
PREFIXO_DO_CONSUMIDOR: Final = "agr_"

#: O prefixo dos tipos que exigem ordem (§6.3) e que tem prioridade (§15.2
#: regra 2). **E o mesmo prefixo para as duas coisas, e nao por coincidencia**:
#: o que obriga a ordem e o que da prioridade e a mesma frase — um pagamento e
#: dinheiro de um cliente, e um pagamento fora de ordem ou atrasado e um cliente
#: que pagou sem confirmacao (§6.4, «Sev1»).
PREFIXO_DE_PAGAMENTO: Final = "payment."


class SubscricoesInvalidasError(RuntimeError):
    """O registo tem subscricoes que nao se podem consumir. O AGR sai com `8`.

    A mensagem junta **todos** os problemas e nao o primeiro, pela razao do
    `RegistoInvalidoError` do KAM-027: quem corrige um ficheiro de configuracao
    quer a lista, e um arranque que falha seis vezes por seis linhas erradas sao
    seis *deploys*.
    """


@dataclass(frozen=True, slots=True)
class Consumidor:
    """Um consumidor registado: a vertical, o par `(tipo, versao)` e o regime.

    `nome` e o `consumer` das duas tabelas de eventos; `prioritario` e o que o
    criterio 8 pede, e sai do prefixo do tipo e nao de configuracao.
    """

    nome: str
    vertical: str
    #: O `entitlements.modulo` da vertical. E o que decide se **este** *tenant*
    #: tem esta vertical activa: a `evt_subscricoes` e configuracao global (por
    #: `consumer`, nao por *tenant*), e o §5.2 da «uma so vertical principal por
    #: numero no Piloto». Sem esta verificacao, o mesmo `payment.confirmed`
    #: notificava o cliente **duas** vezes num *tenant* que so tem uma vertical.
    modulo: str
    tipo: str
    versao: int
    exige_ordem: bool
    prioritario: bool


def nome_do_consumidor(vertical: str) -> str:
    """`agr_<vertical>` — o `consumer` das tabelas de eventos."""
    return f"{PREFIXO_DO_CONSUMIDOR}{vertical}"


def e_de_pagamento(tipo: str) -> bool:
    """O tipo e um evento de pagamento? Decide a ordem e a prioridade."""
    return tipo.startswith(PREFIXO_DE_PAGAMENTO)


def consumidores(
    verticais: Mapping[str, VerticalDoRegisto], env: AmbienteDoRegisto
) -> tuple[Consumidor, ...]:
    """A tabela de consumidores do registo carregado. Levanta se alguma reprova.

    Corre a validacao (4) do §5.2 — a **mesma** funcao do KAM-027 — sobre cada
    vertical, junta os problemas e so depois constroi. Validar e construir em
    passagens separadas e o que faz a mensagem trazer a lista inteira.

    **Uma vertical sem `subscriptions` nao e um problema**, e isso fica dito: o
    §5.1 da `subscriptions` como opcional e o `VerticalDoRegisto` tem omissao
    vazia. Uma vertical que nao subscreve nada nao acorda por evento, e isso e
    uma escolha legitima de quem escreve o registo — recusa-la aqui era inventar
    uma regra que nenhum documento tem.
    """
    problemas: list[str] = []
    for identificador in sorted(verticais):
        for problema in validar_subscriptions(verticais[identificador], env):
            problemas.append(f"{identificador}: {problema}")
    if problemas:
        raise SubscricoesInvalidasError(
            "subscricoes sem contrato publicado (`docs/tecnica/02` §5.2 validacao 4): "
            + "; ".join(problemas)
        )

    tabela: list[Consumidor] = []
    for identificador in sorted(verticais):
        vertical = verticais[identificador]
        for subscricao in vertical.subscriptions:
            tabela.append(
                Consumidor(
                    nome=nome_do_consumidor(vertical.id),
                    vertical=vertical.id,
                    modulo=vertical.entitlements.modulo,
                    tipo=subscricao.tipo,
                    versao=subscricao.versao,
                    exige_ordem=e_de_pagamento(subscricao.tipo),
                    prioritario=e_de_pagamento(subscricao.tipo),
                )
            )
    return tuple(tabela)


def por_tipo_e_versao(
    tabela: tuple[Consumidor, ...],
) -> Mapping[tuple[str, int], tuple[Consumidor, ...]]:
    """`(tipo, versao) -> consumidores`, que e o que o despacho pergunta.

    Devolve um `dict` simples e nao um `defaultdict`: um `defaultdict` responde a
    uma chave desconhecida com uma lista vazia, e uma lista vazia lia-se «nao ha
    nada a fazer com este evento» — que e exactamente o silencio que o criterio 3
    proibe. Com o `dict`, a ausencia e `None` e quem pergunta tem de decidir.
    """
    agrupado: dict[tuple[str, int], list[Consumidor]] = {}
    for consumidor in tabela:
        agrupado.setdefault((consumidor.tipo, consumidor.versao), []).append(consumidor)
    return {chave: tuple(valor) for chave, valor in agrupado.items()}


def versoes_subscritas(tabela: tuple[Consumidor, ...]) -> Mapping[str, frozenset[int]]:
    """`tipo -> versoes subscritas`, para distinguir as duas recusas do criterio 3.

    Um tipo que ninguem subscreve e um `tipo_desconhecido`; um tipo subscrito
    numa versao que ninguem subscreve e uma `versao_desconhecida`. Sao dois
    motivos de DLQ diferentes porque mandam olhar para sitios diferentes — o
    primeiro para a configuracao de entrega (`evt_subscricoes`, KAM-005) e o
    segundo para a ordem de *deploy* do §6.6 («consumidores antes de produtores»).
    """
    por_tipo: dict[str, set[int]] = {}
    for consumidor in tabela:
        por_tipo.setdefault(consumidor.tipo, set()).add(consumidor.versao)
    return {tipo: frozenset(versoes) for tipo, versoes in por_tipo.items()}


def nomes(tabela: tuple[Consumidor, ...]) -> tuple[str, ...]:
    """Os `consumer` distintos, por ordem. E o eixo de `agr_evt_lag_ms`."""
    return tuple(sorted({consumidor.nome for consumidor in tabela}))
