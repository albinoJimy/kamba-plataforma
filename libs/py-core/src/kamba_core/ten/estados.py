"""A matriz de estados do CHR (KAM-009 criterio 6, `docs/tecnica/01` §7.2).

Espelho de `packages/core-ts/src/ten/estados.ts`. A matriz, a ordem de
precedencia e as listas de estados e de accoes sao confrontadas celula a celula
com as do TypeScript pelo `TestParidadeDoTypeScript`.

## O problema que esta matriz tem, e que este modulo resolve e declara

A tabela do §7.2 tem uma coluna chamada «Estado do tenant/canal» e **funde dois
dominios**:

* os estados do **tenant** sao cinco — `onboarding`, `ativo`, `restrito`,
  `suspenso`, `encerrado` (DDL de `platform.tenants`, `docs/tecnica/03` §5.2, e
  revisao `0001`);
* os estados do **canal** sao seis — `pendente`, `ativo`, `restrito`,
  `desligado`, `suspenso`, `encerrado` (`01` §7.1).

A tabela tem seis linhas porque junta `onboarding` com `pendente` — que sao de
dominios diferentes — e acrescenta `desligado`, que **so** existe no canal. E o
`ChannelContext` que o mesmo §7.2 devolve carrega os **dois** campos:
`estado_tenant` e `estado_canal`.

Consequencia directa: um `tenant_gate(estado, accao)` de **um** parametro, que
e como o criterio 6 do bloco o escreve, nao exprime a matriz. Um tenant `ativo`
com um canal `desligado` nao tem celula nenhuma, e um tenant `suspenso` com um
canal `ativo` tem duas.

## A regra de precedencia — **PROPOSTA**, nao esta em documento nenhum

Este modulo recebe os dois estados e reduz-os a um **regime**, que e a linha da
tabela do §7.2 que se aplica: decide o mais restritivo dos dois.

    desligado > encerrado > suspenso > pendente > restrito > ativo

A regra por extenso, em duas frases que decidem a ordem toda:

1. **`desligado` ganha de tudo, porque nao e um estado de politica: e uma
   afirmacao sobre o TRANSPORTE.** As outras cinco linhas dizem o que a
   plataforma *autoriza*; esta diz que o caminho tecnico ate ao publico **nao
   existe** — «Nenhuma entrada chega (coexistencia removida)», saida
   «Nenhuma». Nenhum estado de politica faz reaparecer um transporte que foi
   removido, e por isso nenhum lhe pode passar a frente. Autorizar um envio
   por um canal `desligado` nao e uma decisao arriscada: e uma decisao sobre
   uma coisa que nao esta la.
2. **As outras cinco ordenam-se do mais restritivo para o menos**, que e a
   leitura directa da tabela.

O fundamento de cada degrau, porque a ordem nao vem de lado nenhum:

* `desligado` primeiro — ver (1). **Foi aqui que a primeira versao deste
  modulo errou**, e a revisao adversarial mediu-o: com a ordem antiga
  (`encerrado > suspenso > desligado > …`), o par tenant `suspenso` + canal
  `desligado` caia no regime `suspenso` e o gate **autorizava** a
  `mensagem_estatica` — um envio por um canal que o §7.2 diz removido. O
  argumento de entao («`suspenso` e causa externa, nao se lhe passa a frente»)
  estava a comparar duas coisas que nao se comparam: `suspenso` responde «a
  plataforma deixa?» e `desligado` responde «ha por onde?».
* `encerrado` a seguir — e o unico terminal nas duas maquinas de estado, e a
  linha da tabela e «Registar e descartar». Um estado do qual nao se sai nao
  pode ser ultrapassado por nenhum do qual se saia.
* `suspenso` depois — a nota da tabela e «Decisao T&S ou falta de pagamento».
  E a unica das linhas de politica cuja causa e externa a plataforma, e
  passar-lhe a frente por o outro dominio estar `ativo` seria continuar a
  servir quem a Meta ou a cobranca mandaram parar.
* `pendente`/`onboarding` antes de `restrito` — `pendente` permite registar e a
  mensagem de teste, e mais nada («nao responder ao publico»); `restrito`
  permite conversar dentro da janela. `pendente` e o mais apertado dos dois.
* `restrito` antes de `ativo` — e o proprio sentido da palavra, e a unica
  relacao de ordem que a tabela torna obvia.

**Uma consequencia que se aceita de olhos abertos:** com `desligado` a cabeca,
um tenant `encerrado` sobre um canal `desligado` tambem **nao** regista a
entrada, embora a linha `encerrado` diga «Registar e descartar». E o certo
pela mesma frase (1): se o canal esta removido, nao chega entrada nenhuma que
houvesse para registar; e se chegar alguma, chegou por um caminho que ja nao
devia existir — a linha `desligado` ja negava `registar_entrada` sozinha, e e
essa a celula que vale.

**Esta ordem e uma proposta deste ticket e a decisao devolve-se ao dono do
`docs/tecnica/01`.** Nao ha documento que a escreva, nem sequer que admita que
os dois dominios se cruzam. O que aqui se faz e nao deixar o cruzamento por
resolver em silencio, que e o que um gate de um parametro faria.

## O que este modulo nao faz

* **Nao limita a frequencia.** A celula de `suspenso` diz «uma vez por
  contacto/24 h»: isto responde «pode» e nao «quantas vezes».
* **Nao le a base.** E uma funcao pura sobre dois estados e uma accao.
* **Nao regista nada.**
"""

from __future__ import annotations

from dataclasses import dataclass

#: Os cinco estados de `platform.tenants.estado` (revisao `0001`).
ESTADOS_DO_TENANT = (
    "onboarding",
    "ativo",
    "restrito",
    "suspenso",
    "encerrado",
)

#: Os seis estados de `platform.tenant_channels.estado` (`01` §7.1).
ESTADOS_DO_CANAL = (
    "pendente",
    "ativo",
    "restrito",
    "desligado",
    "suspenso",
    "encerrado",
)

#: As seis linhas da tabela do §7.2, da mais restritiva para a menos.
#:
#: **A ordem do tuplo e a regra de precedencia**, e nao uma lista alfabetica: o
#: indice de cada regime e a sua posicao na ordem, e `mais_restritivo` compara
#: indices. Escrever a ordem como dado em vez de como cadeia de `if` e o que
#: permite ao teste de paridade confronta-la com a do TypeScript como texto —
#: e e tambem o que faz da correccao da revisao adversarial **uma linha**:
#: `desligado` subiu ao topo porque e transporte e nao politica (docstring do
#: modulo, ponto 1).
REGIMES = (
    "desligado",
    "encerrado",
    "suspenso",
    "pendente",
    "restrito",
    "ativo",
)

#: O regime de cada estado do tenant. `onboarding` e a linha `pendente`.
REGIME_DO_TENANT = {
    "onboarding": "pendente",
    "ativo": "ativo",
    "restrito": "restrito",
    "suspenso": "suspenso",
    "encerrado": "encerrado",
}

#: O regime de cada estado do canal. Um para um: as linhas sao as dele.
REGIME_DO_CANAL = {
    "pendente": "pendente",
    "ativo": "ativo",
    "restrito": "restrito",
    "desligado": "desligado",
    "suspenso": "suspenso",
    "encerrado": "encerrado",
}

#: As accoes que a matriz decide.
#:
#: `registar_entrada`            guardar a mensagem que chegou (coluna «Entrada»)
#: `processar_entrada`           correr o agente sobre ela
#: `responder_sessao`            responder dentro da janela de 24 h
#: `enviar_template_utilidade`   template de utilidade (fora da janela)
#: `enviar_template_marketing`   template de marketing
#: `mensagem_estatica`           a «Loja temporariamente indisponivel»
#: `mensagem_de_teste`           a mensagem de teste do onboarding
ACCOES = (
    "registar_entrada",
    "processar_entrada",
    "responder_sessao",
    "enviar_template_utilidade",
    "enviar_template_marketing",
    "mensagem_estatica",
    "mensagem_de_teste",
)

#: A matriz: seis regimes por sete accoes, escrita por extenso.
#:
#: Por extenso, e nao derivada de regras, pela mesma razao que a lista de
#: colunas da `0007` e literal: quem vem ver o que um estado permite le uma
#: tabela e nao um algoritmo, e um teste pode compara-la celula a celula com a
#: do TypeScript.
#:
#: Onde o §7.2 e explicito, a celula e a dele. Onde nao e, a celula nega e o
#: comentario diz que a tabela nao a escreve.
REGIMES_E_ACCOES = {
    # «Registar; nao responder ao publico» / saida «Nenhuma» / «So mensagem de
    # teste do onboarding».
    "pendente": {
        "registar_entrada": True,
        "processar_entrada": False,
        "responder_sessao": False,
        "enviar_template_utilidade": False,
        "enviar_template_marketing": False,
        "mensagem_estatica": False,
        "mensagem_de_teste": True,
    },
    # «Normal» / «Normal».
    "ativo": {
        "registar_entrada": True,
        "processar_entrada": True,
        "responder_sessao": True,
        "enviar_template_utilidade": True,
        "enviar_template_marketing": True,
        "mensagem_estatica": True,
        "mensagem_de_teste": True,
    },
    # «Normal» / «So respostas dentro da janela; sem templates *marketing*».
    #
    # **Uma ambiguidade, e a leitura escolhida e a fechada.** «So respostas
    # dentro da janela» exclui qualquer template, porque um template e o que se
    # manda fora da janela; a segunda metade da frase — «sem templates
    # marketing» — fica entao a reforcar e nao a abrir uma excepcao. A leitura
    # contraria (templates de utilidade continuam a poder sair) tem um
    # argumento de negocio serio: um aviso de encomenda ou de pagamento e
    # utilidade, e um tenant apenas limitado por qualidade perde-o. **A decisao
    # devolve-se ao dono do `01` §7.2**; ate la nega, porque e o sentido em que
    # falhar custa menos.
    "restrito": {
        "registar_entrada": True,
        "processar_entrada": True,
        "responder_sessao": True,
        "enviar_template_utilidade": False,
        "enviar_template_marketing": False,
        # A tabela nao escreve esta celula. Permite porque a mensagem estatica
        # e uma resposta dentro da janela, e essas estao permitidas na linha.
        "mensagem_estatica": True,
        # A tabela nao escreve esta celula. Nega: a mensagem de teste pertence
        # ao onboarding, e um canal `restrito` ja passou por ele.
        "mensagem_de_teste": False,
    },
    # «Nenhuma entrada chega (coexistencia removida)» / «Nenhuma».
    #
    # `registar_entrada` nega, e e a unica linha em que nega. A tabela descreve
    # um **facto** — nao chega entrada — e nao uma permissao; se mesmo assim
    # chegar uma, chegou por um caminho que ja nao devia existir, e aceita-la
    # seria escrever numa conversa de um canal que a Meta removeu.
    #
    # E a linha toda a `False` e tambem a razao por que este regime esta a
    # cabeca de `REGIMES`: uma linha que nao autoriza nada so pode perder para
    # outra autorizando alguma coisa, e nao ha estado de politica que faca
    # reaparecer o transporte.
    "desligado": {
        "registar_entrada": False,
        "processar_entrada": False,
        "responder_sessao": False,
        "enviar_template_utilidade": False,
        "enviar_template_marketing": False,
        "mensagem_estatica": False,
        "mensagem_de_teste": False,
    },
    # «Registar» / «Mensagem estatica ("Loja temporariamente indisponivel") uma
    # vez por contacto/24 h». O «uma vez por 24 h» nao se decide aqui.
    "suspenso": {
        "registar_entrada": True,
        "processar_entrada": False,
        "responder_sessao": False,
        "enviar_template_utilidade": False,
        "enviar_template_marketing": False,
        "mensagem_estatica": True,
        "mensagem_de_teste": False,
    },
    # «Registar e descartar» / «Nenhuma». O descarte e o que resta de registar
    # e nao poder fazer mais nada; nao ha uma terceira decisao para ele.
    "encerrado": {
        "registar_entrada": True,
        "processar_entrada": False,
        "responder_sessao": False,
        "enviar_template_utilidade": False,
        "enviar_template_marketing": False,
        "mensagem_estatica": False,
        "mensagem_de_teste": False,
    },
}


class EstadoDesconhecido(ValueError):
    """Um estado ou uma accao que nao esta nas listas. Nao se adivinha."""


@dataclass(frozen=True)
class DecisaoDoGate:
    """O que a matriz respondeu, e porque."""

    #: A accao e permitida?
    permitido: bool
    #: A linha da tabela do §7.2 que decidiu.
    regime: str
    #: Qual dos dois dominios impos o regime: `tenant`, `canal` ou `ambos`.
    origem: str


def mais_restritivo(a: str, b: str) -> str:
    """O mais restritivo de dois regimes, pela ordem de `REGIMES`."""
    return a if REGIMES.index(a) <= REGIMES.index(b) else b


def regime_de(estado_tenant: object, estado_canal: object) -> str:
    """O regime que se aplica a um par (estado do tenant, estado do canal).

    E aqui que os dois dominios se cruzam, e e a unica funcao deste modulo que
    depende da precedencia **proposta** da docstring.
    """
    if not isinstance(estado_tenant, str) or estado_tenant not in REGIME_DO_TENANT:
        raise EstadoDesconhecido(
            f"estado_tenant desconhecido: {estado_tenant!r}. Um estado que nao "
            "esta na lista nao se trata como o mais parecido."
        )
    if not isinstance(estado_canal, str) or estado_canal not in REGIME_DO_CANAL:
        raise EstadoDesconhecido(
            f"estado_canal desconhecido: {estado_canal!r}. Um estado que nao "
            "esta na lista nao se trata como o mais parecido."
        )
    return mais_restritivo(
        REGIME_DO_TENANT[estado_tenant], REGIME_DO_CANAL[estado_canal]
    )


def tenant_gate(
    estado_tenant: object, estado_canal: object, accao: object
) -> DecisaoDoGate:
    """A matriz do §7.2, com os **dois** estados do `ChannelContext`.

    Assinatura de tres argumentos, e nao a de dois do criterio 6: ver a
    docstring do modulo. A `origem` existe para quem precisa de explicar a
    recusa sem voltar a correr a precedencia — e, no caso `ambos`, de saber que
    nao ha um unico culpado.
    """
    regime = regime_de(estado_tenant, estado_canal)
    if not isinstance(accao, str) or accao not in REGIMES_E_ACCOES[regime]:
        raise EstadoDesconhecido(
            f"accao desconhecida: {accao!r}. Uma accao que nao esta na lista "
            "nao se trata como a mais parecida."
        )
    do_tenant = REGIME_DO_TENANT[estado_tenant]
    do_canal = REGIME_DO_CANAL[estado_canal]
    if do_tenant == do_canal:
        origem = "ambos"
    elif regime == do_tenant:
        origem = "tenant"
    else:
        origem = "canal"
    return DecisaoDoGate(
        permitido=REGIMES_E_ACCOES[regime][accao], regime=regime, origem=origem
    )
