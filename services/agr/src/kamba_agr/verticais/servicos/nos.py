"""Os nos do grafo de Servicos: os oito proprios, e a tabela com os reutilizados.

## O que este ficheiro NAO escreve, e e a maior parte dele

Catorze dos vinte e dois nos vem do `verticais/vendedor/nos.py` tal como estao —
`ingest`, `stt`, `guard_in`, `tools_info`, `validate`, `guard_out`, `send`,
`ask_repeat`, `safe_reply`, os tres `handoff_*` e os dois do concierge. Nao se
copiam e nao se envolvem: importam-se, e a tabela `NOS_DO_GRAFO` do fim poe lado
a lado os importados e os nossos. **E o ponto do ticket** (ADR-012), e a lista
esta no `NOS_REUTILIZADOS` do `arestas.py`, de onde o KAM-039 a vai medir.

Dois dos oito proprios estao na coluna «Partilhado (core)» do §5.4 e **nao se
conseguem reutilizar tal como estao** — o `compose`, porque explica avisos por um
dicionario indexado pelo dominio do Vendedor, e o `confirm_gate`, porque le o
`cart` em vez do `hold`. A razao por extenso esta no `NOS_REUTILIZADOS`.

## O `deps` e o do Vendedor, e isso e deliberado

As `Dependencias` sao as do `verticais/vendedor/nos.py`: as mesmas portas
(`tools`, `saida`, `hnd`, `concierge`, `rascunho`, `degradacao`), o mesmo
relogio, a mesma admissao. **Um `Dependencias` proprio era a primeira
divergencia**: os catorze nos importados recebem-no, pelo que ou e o mesmo tipo
ou se escreve um adaptador para cada um. O que muda por vertical e a
`tools_permitidas` e a `persona`, e os dois sao campos — nao tipos.

**O que isto deixa em divida** e o nome do modulo onde a classe vive: um
`Dependencias` que serve as duas verticais devia estar em `core/`, e esta em
`verticais/vendedor/`. Nao se move neste ticket — mover uma classe importada por
catorze nos e por 1 161 ensaios e a extraccao que o **KAM-039** faz quando medir
o reuso. Fica em `docs/dividas-documentais.md`, com credor.

## «Nao me disse qual» nao e «nao existe»

O `cancel_booking` pedido sem referencia devolve `REFERENCIA_EM_FALTA` e nao
`NOT_FOUND`. E a licao que o KAM-037 pagou no `order_status` (achado C2 da
`ANALISE-39`): a ausencia de um campo nao e a inexistencia dele, e confundir os
dois dizia «nao encontrei essa marcacao» a quem nunca deu referencia nenhuma. O
`slots_collect` e a mesma classe inteira — e por isso que ele **pergunta**.

## Um identificador de botao sobrevive ao turno; o estado nao

O `classify` honra um `confirm:*` em **todos** os turnos, qualquer que seja o
estado, e nao so quando o estado diz que esta a espera de confirmacao. O botao
fica no ecra do WhatsApp indefinidamente: um cliente que o toque tres turnos
depois tem de ser reconhecido, e quem decide se a confirmacao ainda vale e o
`confirm_gate` — que responde `stale`, com frase propria. Foi o achado critico
C1 da revisao adversarial do KAM-037, e a mesma licao que o `_CANCELAMENTO` do
KAM-031 ja tinha pago.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from ...tls.contexto import Confirmation, ToolContext
from ...tls.erros import (
    HOLD_EXPIRED,
    LIMIT_EXCEEDED,
    NOT_FOUND,
    SLOT_TAKEN,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    VALIDATION_ERROR,
)

# Os catorze reutilizados, e as utilitarias que eles ja tem. **Importar e nao
# copiar** — ver o cabecalho.
from ..vendedor.nos import (
    MSG_CARTAO,
    Dependencias,
    draft_prepare,
    draft_wait,
    guard_in,
    guard_out,
    handoff_close,
    handoff_prepare,
    handoff_wait,
    ingest,
    send,
    stt,
    tools_info,
    validate,
)
from ..vendedor.nos import (
    MOTIVO_PEDIDO,
    MOTIVO_UPSTREAM,
    REPETICOES_DE_UPSTREAM,
    _resposta_estatica,
    _texto_do_cliente,
)
from . import datas
from .arestas import (
    AVISOS,
    HORA_AMBIGUA,
    INTENCOES,
    INTENCOES_DE_SLOTS,
    MAXIMO_DE_OPCOES,
    PERGUNTA_DO_SLOT,
    PERGUNTAS,
    PREFIXO_DE_CONFIRMACAO,
    REFERENCIA_EM_FALTA,
    SEM_DISPONIBILIDADE,
    SEM_VAGA_NENHUMA,
    SLOTS,
    STALE_CONFIRMATION,
    VERSAO_DO_GRAFO,
    obrigatorios_de,
)

# --------------------------------------------------------------------- tectos

#: As tools que este grafo pode chamar. E a lista fechada do
#: `registry/servicos.yaml`, e o passo 1 do `invoke` recusa qualquer outra.
#:
#: O `get_store_info` esta nas **duas** verticais (§6.2, «ambas») e e a unica
#: `ligada` do catalogo — e o que faz o `tools_info` funcionar aqui sem uma
#: linha nova.
TOOLS_DE_SERVICOS: Final = (
    "list_services",
    "get_availability",
    "book_slot",
    "cancel_booking",
    "reschedule_booking",
    "get_store_info",
)

#: O `seq` do unico envio de um turno. **Zero, e nao e atalho**: o §15.1 fixa
#: «uma so mensagem por turno». O mesmo valor do Vendedor, e pela mesma razao.
SEQ_DO_ENVIO: Final = 0

#: O que o `compose` diz por cada aviso. **Uma entrada por valor do dominio
#: fechado** (`AVISOS`), e ha ensaio que o prova: um aviso sem frase era um
#: aviso que o cliente nunca via, e o §6.5 manda explicar.
#:
#: **Nenhuma frase leva digitos.** O *renderer* levanta num bloco `text` com
#: numeros (§9.1), e por isso «dez opcoes» ou «dez minutos» nao cabem aqui: o
#: que tem numero cita-se por bloco `datetime`, e o que nao se pode citar nao se
#: diz. E a regra do ADR-007 a decidir a redaccao, e nao o contrario.
FRASE_DO_AVISO: Final = {
    NOT_FOUND: "Nao encontrei esse servico nem essa marcacao.",
    LIMIT_EXCEEDED: (
        "A loja chegou ao limite de marcacoes deste periodo. Um colega pode ajudar."
    ),
    VALIDATION_ERROR: "Nao consegui tratar esse pedido como estava escrito.",
    UPSTREAM_TIMEOUT: "A agenda da loja demorou a responder.",
    UPSTREAM_DOWN: "A agenda da loja nao responde neste momento.",
    SLOT_TAKEN: (
        "Essa hora foi ocupada entre eu mostrar-lha e o seu toque. Posso mostrar "
        "outras."
    ),
    HOLD_EXPIRED: (
        "A reserva dessa hora expirou enquanto esperava. Posso voltar a procurar."
    ),
    STALE_CONFIRMATION: (
        "Essa confirmacao ja nao esta valida. Vou mostrar-lhe as horas outra vez."
    ),
    REFERENCIA_EM_FALTA: "Diga-me qual e a marcacao e eu trato dela.",
    SEM_DISPONIBILIDADE: (
        "Nao tenho vaga nessa altura. Veja se alguma destas lhe serve."
    ),
    HORA_AMBIGUA: "",  # a frase da pergunta vem do `FRASE_DA_PERGUNTA`
    SEM_VAGA_NENHUMA: (
        "Nao tenho vaga nenhuma nesse dia. Diga-me outro dia e eu procuro."
    ),
}

#: O que o `compose` pergunta por cada pergunta do `slots_collect`. **Uma
#: entrada por valor do dominio fechado** (`PERGUNTAS`), e ha ensaio que o
#: prova.
#:
#: A `DESAMBIGUAR_HORA` **nao enumera as horas possiveis**, e e por falta de
#: bloco e nao por escolha de redaccao: «de manha ou de tarde?» nao leva
#: digitos, e «as 5 ou as 17?» levava dois — e um bloco `text` com digitos
#: levanta no *renderer* (§9.1). A pergunta sem numeros e a que o canal aceita,
#: e e tao desambiguadora como a outra.
FRASE_DA_PERGUNTA: Final = {
    "PEDIR_SERVICO": "Que servico quer marcar?",
    "PEDIR_DATA": "Para que dia?",
    "PEDIR_HORA": "A que horas lhe da jeito?",
    "DESAMBIGUAR_HORA": "Essa hora e de manha ou de tarde?",
}

#: Os botoes do turno de confirmacao. **Tres e nao mais**, e o numero nao e
#: nosso: o `MAXIMO_DE_BOTOES` do `packages/core-ts/src/outbound/contrato.ts` e
#: **3** (CONFIRMADO, `E1` §5), e o `PortaDeSaida.enfileirar` recebe so
#: identificadores — sem rotulo e sem tipo de corpo —, pelo que o Outbound nao
#: tem como saber que uma lista de dez linhas nao e uma lista de dez botoes.
#:
#: **E por isso que as dez opcoes de disponibilidade NAO saiem como botoes.**
#: Ver a nota do `compose`.
BOTAO_CANCELAR: Final = "cancelar"
BOTAO_HUMANO: Final = "falar_com_humano"

#: As palavras que decidem cada intencao, **pela ordem em que correm**, e a
#: ordem e a decisao: «quero falar com uma pessoa sobre a marcacao» e um pedido
#: de humano e nao um pedido de marcacao. O §15.1 manda as regras primeiro e o
#: modelo so se elas nao decidirem, e e por isso que a lista e curta — cada
#: padrao que entra aqui e um caso que o modelo deixa de ver, e tambem um caso
#: que ninguem reve.
REGRAS_DE_INTENCAO: Final = (
    ("humano", ("falar com uma pessoa", "falar com alguem", "atendente", "humano")),
    ("cancelar", ("cancelar", "desmarcar", "anular")),
    ("remarcar", ("remarcar", "mudar a marcacao", "mudar a hora", "adiar", "trocar a hora")),
    ("disponibilidade", ("tem vaga", "ha vaga", "quando tem", "que horas tem", "disponibilidade")),
    ("servicos_precos", ("que servicos", "quanto custa", "precos", "preco", "tabela")),
    ("info_loja", ("horario", "onde fica", "morada", "endereco", "aberto")),
    ("marcar", ("marcar", "agendar", "queria uma hora", "quero uma hora")),
)


# ----------------------------------------------------------------- utilitarias


def contexto_de_tool(estado: Mapping[str, Any]) -> ToolContext:
    """O `ToolContext` do turno, com o `graph_version` **deste** grafo.

    **Nao se reutiliza o do Vendedor**, e e a unica utilitaria onde isso vale: o
    dele fixa `graph_version=VERSAO_DO_GRAFO` do pacote dele, e uma linha de
    `tool_audit` de uma marcacao a dizer `1.2.0` dizia que grafo correu — e
    dizia o do Vendedor. O `run_id` e derivado do `thread_id` e do `turn_id` e
    **nao** e aleatorio, pela razao que o do Vendedor escreve: a `tool_audit` e
    append-only e duas linhas do mesmo turno tem de se poder juntar.
    """
    cru = f"{estado['thread_id']}:{estado['turn_id']}".encode()
    return ToolContext.de_estado(
        dict(estado),
        run_id=hashlib.sha256(cru).hexdigest()[:32],
        graph_version=VERSAO_DO_GRAFO,
    )


def chave_do_turno(estado: Mapping[str, Any]) -> str:
    """`idempotency_key = turn_id:seq` (dicionario §3.24)."""
    from ...contexto import chave_de_envio

    return chave_de_envio(estado["turn_id"], SEQ_DO_ENVIO)


def avisos_com(estado: Mapping[str, Any], *codigos: str) -> tuple[str, ...]:
    """Junta avisos aos que ja estao no estado, sem repetir e sem inventar.

    Um codigo fora do dominio fechado **levanta**: e a forma de uma cadeia livre
    chegar ao `compose`, que decide por valor conhecido. O do Vendedor valida
    contra o dominio dele, e por isso nao serve aqui — e o mesmo corpo com outra
    lista, que e exactamente o caso em que duas funcoes tem de existir.
    """
    fora = [c for c in codigos if c not in AVISOS]
    if fora:
        raise ValueError(f"{fora} nao sao avisos do dominio fechado: {list(AVISOS)}")
    juntos = list(estado.get("avisos") or ())
    for codigo in codigos:
        if codigo not in juntos:
            juntos.append(codigo)
    return tuple(juntos)


#: O aviso que corresponde a cada codigo de erro. As tres violacoes **nao** tem
#: aviso proprio: caem em `VALIDATION_ERROR`, que diz ao cliente que o pedido
#: nao se pode tratar e nao lhe diz mais nada. E deliberado — o §6.5 manda
#: bloquear e levantar alerta de seguranca, e uma mensagem especifica era um
#: oraculo sobre a fronteira.
_AVISO_DO_CODIGO: Final = {
    NOT_FOUND: NOT_FOUND,
    LIMIT_EXCEEDED: LIMIT_EXCEEDED,
    VALIDATION_ERROR: VALIDATION_ERROR,
    UPSTREAM_TIMEOUT: UPSTREAM_TIMEOUT,
    UPSTREAM_DOWN: UPSTREAM_DOWN,
    SLOT_TAKEN: SLOT_TAKEN,
    HOLD_EXPIRED: HOLD_EXPIRED,
}


def _aviso_do_erro(resultado: Any) -> str:
    """O aviso que o `compose` recebe por um `ToolResult` que falhou."""
    codigo = getattr(resultado.error, "codigo", "") if resultado.error else ""
    return _AVISO_DO_CODIGO.get(codigo, VALIDATION_ERROR)


def _e_upstream(resultado: Any) -> bool:
    return bool(
        resultado.error is not None
        and resultado.error.codigo in (UPSTREAM_TIMEOUT, UPSTREAM_DOWN)
    )


async def _com_retry(chamar) -> Any:
    """Uma tool, com **um** retry se o erro for `UPSTREAM_*` (§6.5).

    Nao repete nada que nao seja `UPSTREAM_*`: um `SLOT_TAKEN` repetido da o
    mesmo — o intervalo continua ocupado —, e um `ENTITLEMENT_DENIED` repetido e
    uma segunda tentativa de atravessar fronteira.
    """
    resultado = await chamar()
    for _ in range(REPETICOES_DE_UPSTREAM):
        if resultado.ok or resultado.error is None:
            return resultado
        if resultado.error.codigo not in (UPSTREAM_TIMEOUT, UPSTREAM_DOWN):
            return resultado
        resultado = await chamar()
    return resultado


async def _invocar(
    deps: Dependencias,
    estado: Mapping[str, Any],
    nome: str,
    argumentos: dict[str, Any],
    *,
    confirmacao: Confirmation | None = None,
    chave: str | None = None,
) -> Any:
    """Uma tool, pela ToolLayer, com o contexto deste turno.

    A lista de permitidos vai **sempre**: o passo 1 do `invoke` confronta o nome
    com ela, e omiti-la era pedir a camada que confiasse no chamador.
    """
    return await deps.tools.invoke(
        contexto_de_tool(estado),
        nome,
        argumentos,
        allowed=tuple(deps.tools_permitidas),
        confirmation=confirmacao,
        idempotency_key=chave,
    )


def referencia_a_confirmar(slots: Mapping[str, Any]) -> str | None:
    """O que o botao `confirm:` deste turno cita, ou `None` se nao ha nada.

    ## Tem um dono so, e a razao foi medida

    Tres sitios precisam desta resposta — o `compose`, que **emite** o botao; o
    `confirm_gate`, que **compara** o botao com ela; e os nos de escrita, que a
    passam a `Confirmation`. Escrita tres vezes, divergiu: o `compose` emitia
    `confirm:{hold_id}` e o `reschedule_booking` cita `booking_id`, pelo que o
    passo 4 do `invoke` comparava duas coisas diferentes e **toda** a remarcacao
    saia `VALIDATION_ERROR`. Apanhado pela revisao adversarial (`ANALISE-40`,
    achado 6), que mediu os dois botoes lado a lado.

    ## A ordem e a das tres escritas, e e exclusiva

    Um cancelamento, uma remarcacao e uma marcacao nova estao em caminhos
    disjuntos do grafo e nao coexistem; a ordem esta aqui para que, se um dia
    coexistirem, **um** identificador saia e nao dois a competir pelo mesmo
    prefixo.

    O `cancelar` e o `remarcar` citam o `booking_id` — e o que identifica o que
    se altera, e e o `campo_de_confirmacao` das duas tools (`tls/servicos.py`).
    Uma marcacao nova cita o `hold_id`, que e o que o §8.2 escreve.
    """
    cancelar = slots.get("cancelar")
    if isinstance(cancelar, str) and cancelar:
        return cancelar
    remarcar = slots.get("remarcar")
    if isinstance(remarcar, str) and remarcar:
        return remarcar
    hold = slots.get("hold")
    if isinstance(hold, Mapping):
        hold_id = hold.get("hold_id")
        if isinstance(hold_id, str) and hold_id:
            return hold_id
    return None


def _slots_de(estado: Mapping[str, Any]) -> dict[str, Any]:
    """Os `slots` do estado como `dict`, **sem nunca indexar a chave**.

    O `slots` saiu do `estado_inicial` (ver a nota la) para poder atravessar
    turnos, pelo que no primeiro turno a chave **nao existe**. Um
    `estado["slots"]` dava `KeyError` no primeiro turno de toda a conversa.
    """
    actuais = estado.get("slots")
    return dict(actuais) if isinstance(actuais, Mapping) else {}


def _botao_do_turno(estado: Mapping[str, Any]) -> str:
    """O identificador do botao tocado, quando a entrada e interactiva."""
    if estado.get("input_kind") != "interactive":
        return ""
    return _texto_do_cliente(estado).strip()


def intencao_por_regras(texto: str) -> str | None:
    """A intencao pelas palavras, ou `None` se nenhuma regra decidir."""
    limpo = datas.sem_acentos(texto)
    for intencao, palavras in REGRAS_DE_INTENCAO:
        if any(datas.sem_acentos(p) in limpo for p in palavras):
            return intencao
    return None


#: A referencia de uma marcacao no texto do cliente: um identificador opaco que
#: o cliente copia da mensagem anterior.
_REFERENCIA_DE_MARCACAO: Final = re.compile(r"\b([A-Za-z]{1,4}[-_]?\d{2,})\b")

#: O profissional que o cliente pede pelo nome. Ver o `_profissional_no_texto`.
_PROFISSIONAL: Final = re.compile(r"\bcom\s+(?:o|a|ao?)\s+([A-Za-zÀ-ÿ]{3,20})\b")


# ---------------------------------------------------------------- o classify


def classify(deps: Dependencias):
    """Transicoes 11 a 17: a intencao. Regras primeiro, modelo so se preciso.

    **Um botao de confirmacao nunca passa por modelo**, e e honrado em qualquer
    estado — ver a nota do cabecalho sobre identificadores que sobrevivem ao
    turno.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        botao = _botao_do_turno(estado)
        if botao.startswith(PREFIXO_DE_CONFIRMACAO):
            return {"intent": "confirmar"}
        if botao == BOTAO_HUMANO:
            return {"intent": "humano", "handoff_motivo": MOTIVO_PEDIDO}
        if botao == BOTAO_CANCELAR:
            return {"intent": "cancelar"}

        texto = _texto_do_cliente(estado)
        intencao = intencao_por_regras(texto)

        # **Uma pergunta no ecra sobrevive ao turno, tal como um botao.** E a
        # outra metade da licao C1 do KAM-037, e a primeira versao deste no
        # deixava-a de fora: as respostas naturais as tres perguntas do
        # `slots_collect` — «amanha», «as 9h», «corte de cabelo» — nao casam
        # regra nenhuma, pelo que caiam em `outro` e sairam por `safe_reply`. O
        # cliente respondia exactamente o que lhe foi perguntado e recebia «so
        # posso ajudar com ...». Medido pela revisao adversarial (`ANALISE-40`,
        # achado 2), em cinco turnos.
        #
        # A intencao que abriu o preenchimento fica nos `slots` (que atravessam
        # turnos) e nao no `intent` (que e do turno, `CAMPOS_DO_TURNO`). Enquanto
        # houver pergunta pendente, uma mensagem que nenhuma regra reclame **e a
        # resposta a essa pergunta** — e nao uma intencao nova.
        #
        # **As regras continuam a vencer**, e e o que deixa o cliente mudar de
        # assunto a meio: «esqueca, quero cancelar» casa a regra do cancelamento
        # e sai do preenchimento. So a ausencia de regra herda.
        slots_actuais = _slots_de(estado)
        if intencao is None and slots_actuais.get("pergunta"):
            herdada = slots_actuais.get("intencao")
            if herdada in INTENCOES_DE_SLOTS:
                intencao = herdada

        if intencao is None and deps.classificador is not None:
            escolhida = deps.classificador(texto)
            # Um valor fora das nove **nao** entra no estado: o `r_intent`
            # mandava-o a `other` de qualquer maneira, e escrever no estado uma
            # intencao que o dicionario nao tem punha-a a viajar no checkpoint.
            intencao = escolhida if escolhida in INTENCOES else None
        resolvida = intencao or "outro"
        delta: dict[str, Any] = {"intent": resolvida}
        if resolvida == "humano":
            delta["handoff_motivo"] = MOTIVO_PEDIDO

        slots = dict(slots_actuais)
        mudou = False
        if resolvida in INTENCOES_DE_SLOTS:
            # Guarda-se a intencao que abriu o preenchimento, para a herdar nos
            # turnos das respostas — ver a nota acima.
            if slots.get("intencao") != resolvida:
                slots["intencao"] = resolvida
                mudou = True
        if resolvida == "remarcar":
            # **A remarcacao marca-se no estado e nao numa intencao sozinha.** O
            # `slots_collect` e o `book_slot` servem os dois casos, e o que os
            # distingue e haver uma marcacao a substituir — que e o que o
            # `reschedule_booking` precisa de saber (criterio 7).
            #
            # **Sem referencia no texto, pergunta-se.** A primeira versao punha
            # `True` aqui, e o `book_slot` — que exige uma cadeia — caia no ramo
            # da marcacao nova: o cliente acabava com **duas** marcacoes, que e
            # o inverso exacto do que o criterio 7 protege. Medido pela revisao
            # adversarial (`ANALISE-40`, achado 8). A referencia de um turno
            # anterior continua a valer; sem nenhuma, o aviso e
            # `REFERENCIA_EM_FALTA` e o cliente ouve a pergunta.
            achado = _REFERENCIA_DE_MARCACAO.search(texto)
            if achado is not None:
                slots["remarcar"] = achado.group(1)
                mudou = True
        if mudou:
            delta["slots"] = slots
        return delta

    return no


# ----------------------------------------------------------- o slots_collect


def slots_collect(deps: Dependencias):
    """Transicoes 18 e 19: recolhe os slots, **uma pergunta por mensagem**.

    O criterio 3 pede «pergunta **uma** coisa por mensagem (`servico`, `data`,
    `hora`, `profissional?`)» e «hora ambigua ("as 5") gera pergunta de
    desambiguacao, **nunca palpite**».

    **Uma pergunta por mensagem e estrutural e nao disciplinar.** O que vai para
    o estado e `slots["pergunta"]` — **um** campo, nao uma lista —, pelo que duas
    perguntas no mesmo turno nao sao uma regra que alguem tenha de respeitar: nao
    ha onde as escrever. O `compose` escreve a frase de uma pergunta e de mais
    nenhuma.

    **A ordem das perguntas e decisao:** `servico`, depois `data`, depois `hora`.
    O servico decide a duracao e por isso decide que horas existem na grelha;
    perguntar a hora primeiro era perguntar sobre uma grelha desconhecida.

    **O `profissional` nunca se pergunta.** O §8.2 escreve-o com `?` — e
    opcional —, e a agenda consulta-se sem ele. Guarda-se quando o cliente o
    disser por iniciativa propria, e e tudo.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        slots = _slots_de(estado)
        texto = _texto_do_cliente(estado)
        agora = _agora_utc(deps)

        # **Uma remarcacao precisa de saber QUAL marcacao, e isso vem primeiro.**
        # Sem referencia, nao se recolhem slots: recolhe-los levava a tomar um
        # *hold* e a confirmar uma marcacao **nova**, deixando a original de pe —
        # o inverso do criterio 7. O `classify` ja tentou ler a referencia do
        # texto; aqui pergunta-se, com a frase do `REFERENCIA_EM_FALTA` («nao me
        # disse qual» nao e «nao existe»).
        if estado.get("intent") == "remarcar" and not isinstance(
            slots.get("remarcar"), str
        ):
            referencia = _REFERENCIA_DE_MARCACAO.search(texto)
            if referencia is None:
                return {"slots": slots, "avisos": avisos_com(estado, REFERENCIA_EM_FALTA)}
            slots["remarcar"] = referencia.group(1)

        # **O que o turno trouxe, sem apagar o que os turnos anteriores deram.**
        # Um `data` que este turno nao mencione mantem o do turno passado: e o
        # que faz o preenchimento ao longo de varios turnos funcionar.
        if not slots.get("servico"):
            vistos = await _servicos_vistos(deps, estado, slots)
            servico = _servico_no_texto(texto, vistos)
            if servico:
                slots["servico"] = servico

        nova_data = datas.ler_data(texto, agora)
        if nova_data:
            slots["data"] = nova_data

        # **A resposta a desambiguacao resolve-se aqui, e nao se pergunta outra
        # vez.** O turno anterior guardou as candidatas; «de tarde» nao tem
        # digitos, pelo que o `ler_hora` nao ve hora nenhuma nele — e sem este
        # passo o cliente que respondesse exactamente o que lhe foi perguntado
        # entrava em ciclo. Ver o `resolver_candidatas`.
        candidatas = slots.get("hora_candidatas")
        if candidatas and not slots.get("hora"):
            escolhida = datas.resolver_candidatas(texto, candidatas)
            if escolhida is not None:
                slots["hora"] = escolhida
                slots.pop("hora_candidatas", None)
                slots.pop("pergunta", None)

        hora = datas.ler_hora(texto)
        if hora.ambigua:
            # **Nao se escolhe e nao se guarda.** O criterio diz «nunca
            # palpite», e guardar uma das candidatas para «confirmar depois» era
            # um palpite com uma pergunta por cima.
            slots["pergunta"] = "DESAMBIGUAR_HORA"
            slots["hora_candidatas"] = hora.candidatas
            return {
                "slots": slots,
                "avisos": avisos_com(estado, HORA_AMBIGUA),
            }
        if hora.lida:
            slots["hora"] = hora.minutos
            slots.pop("hora_candidatas", None)

        profissional = _profissional_no_texto(texto)
        if profissional:
            slots["profissional"] = profissional

        # O primeiro obrigatorio em falta, pela ordem do conjunto **da
        # intencao**: quem pergunta pela agenda nao tem de dar hora.
        for campo in obrigatorios_de(estado.get("intent")):
            if slots.get(campo) in (None, "", ()):
                slots["pergunta"] = PERGUNTA_DO_SLOT[campo]
                return {"slots": slots}

        slots.pop("pergunta", None)
        return {"slots": slots}

    return no


def _agora_utc(deps: Dependencias) -> datetime.datetime:
    """O instante do turno, em UTC, a partir do relogio das `Dependencias`.

    O `relogio` e `time.time` e nao `monotonic`, pela razao que as
    `Dependencias` escrevem: o `expira_at` de um *hold* atravessa turnos e
    processos, e um relogio monotono nao e comparavel entre dois.
    """
    return datetime.datetime.fromtimestamp(deps.relogio(), tz=datetime.timezone.utc)


async def _servicos_vistos(
    deps: Dependencias, estado: Mapping[str, Any], slots: dict[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    """O catalogo de servicos, **da tool**, guardado nos `slots`.

    ## Porque e que isto nao le as `ofertas` do estado

    Era o que a primeira versao fazia, e **nao podia funcionar**: o `ingest`
    chama o `reiniciar()`, que poe as `ofertas` a vazio em **cada** turno
    (§5.3: «so deste turno»). A lista que o `list_services` mostrou no turno
    anterior ja nao esta ca quando o cliente responde «quero o corte de
    cabelo» — medido: o `servico` ficava `None` para sempre e o
    `slots_collect` repetia «que servico quer marcar?» a cada turno.

    E os `facts` tem a mesma regra, pelo que a lista nao se pode guardar neles.
    O que atravessa turnos sao os `slots`, e e la que ela fica.

    ## E porque e que a lista vem da tool e nao do texto

    «Nao se adivinha um servico do texto livre»: inventar um `service_id` a
    partir de «quero cortar o cabelo» era passar a tool um argumento que nenhuma
    tool devolveu — a classe de defeito que o `quantidade_pedida` do Vendedor
    pagou. A unica fonte de nomes de servico e o `list_services`, que e `read` e
    barato, e chama-se **uma vez por conversa**: depois disso a lista esta nos
    `slots`.

    Uma falha da tool devolve a lista vazia e **nao** escreve nada nos `slots`:
    o `slots_collect` pergunta, e o turno seguinte volta a tentar. Um `()`
    guardado era uma lista vazia a valer como «ja perguntei».
    """
    guardados = slots.get("servicos_vistos")
    if guardados:
        return tuple(guardados)
    resultado = await _com_retry(lambda: _invocar(deps, estado, "list_services", {}))
    if not resultado.ok:
        return ()
    vistos = tuple(
        {"sku": str(s["service_id"]), "nome": str(s.get("nome", ""))}
        for s in resultado.data.get("servicos") or ()
    )
    if vistos:
        slots["servicos_vistos"] = vistos
    return vistos


def _servico_no_texto(
    texto: str, vistos: tuple[Mapping[str, Any], ...]
) -> str | None:
    """O `service_id` que o cliente nomeou, **da lista que a tool devolveu**.

    Compara o nome mais longo primeiro: com «Corte de cabelo» e «Corte», um
    texto que diga o primeiro casa os dois, e o que o cliente nomeou foi o mais
    especifico. Sem ordenacao, a resposta dependia da ordem do catalogo.
    """
    limpo = datas.sem_acentos(texto)
    por_tamanho = sorted(vistos, key=lambda o: -len(str(o.get("nome") or "")))
    for oferta in por_tamanho:
        nome = oferta.get("nome")
        if nome and datas.sem_acentos(str(nome)) in limpo:
            return str(oferta.get("sku"))
    for oferta in vistos:
        sku = oferta.get("sku")
        if sku and str(sku).lower() in limpo:
            return str(sku)
    return None


def _profissional_no_texto(texto: str) -> str | None:
    """O profissional que o cliente pediu, quando o nomeia com «com o/a ...».

    Devolve o **texto do cliente**, e e ele que a tool recusa se nao existir:
    nao ha lista de profissionais no estado, e inventar uma era desenhar o
    `resources` daqui. O `get_availability` ignora um profissional desconhecido
    e devolve a agenda do recurso que houver — e o §8.2 poe o campo com `?`.
    """
    achado = _PROFISSIONAL.search(texto)
    return achado.group(1) if achado else None


# ------------------------------------------------------ o check_availability


def check_availability(deps: Dependencias):
    """Transicoes 20 e 40: as opcoes da agenda, **no maximo dez**.

    O criterio 4 pede «propoe no maximo **10** opcoes (limite de linhas de lista
    interactiva da Meta, CONFIRMADO, `E1` §7); sem disponibilidade responde com
    *fact* de indisponibilidade e alternativas».

    **O corte e nosso e tambem e da tool**, e as duas verificacoes olham para a
    mesma regra por dois lados: o `MAXIMO_DE_OPCOES` do modulo `servicos`
    (KAM-047) corta no backend, e este corta aqui. Confiar so no backend era
    deixar o limite da Meta a depender de um componente que nao e nosso; cortar
    so aqui era receber onze pela rede para deitar uma fora.

    **«Sem disponibilidade» nao e `NOT_FOUND`.** A tool respondeu, e a resposta
    foi «zero opcoes neste intervalo»: o aviso e `SEM_DISPONIBILIDADE` e as
    alternativas sao as opcoes que a tool devolve **fora** do intervalo pedido,
    cada uma com o seu *fact* `datetime`. Tratar isto como `NOT_FOUND` dizia
    «esse servico nao existe» a quem perguntou por uma terca-feira cheia.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        slots = _slots_de(estado)
        intervalo = _intervalo_de(slots)
        resultado = await _com_retry(
            lambda: _invocar(
                deps,
                estado,
                "get_availability",
                {"service_id": str(slots.get("servico") or ""), **intervalo},
            )
        )
        if not resultado.ok:
            delta: dict[str, Any] = {
                "avisos": avisos_com(estado, _aviso_do_erro(resultado))
            }
            if _e_upstream(resultado):
                delta["handoff_motivo"] = MOTIVO_UPSTREAM
            return delta

        cruas = tuple(resultado.data.get("opcoes") or ())
        # **O corte e aqui e e por `MAXIMO_DE_OPCOES`**, nao por um numero
        # escrito a mao: ver a nota da constante.
        opcoes = tuple(dict(o) for o in cruas[:MAXIMO_DE_OPCOES])
        slots["opcoes"] = opcoes
        delta: dict[str, Any] = {"slots": slots, "facts": tuple(resultado.facts)}
        if not opcoes:
            # **Zero opcoes e zero alternativas: aviso proprio.** O
            # `SEM_DISPONIBILIDADE` diz «veja se alguma destas lhe serve», e com
            # a lista vazia apontava para nada. Ver o `SEM_VAGA_NENHUMA`.
            return {**delta, "avisos": avisos_com(estado, SEM_VAGA_NENHUMA)}
        if resultado.data.get("fora_do_intervalo"):
            # A tool nao tinha vaga no intervalo pedido e devolveu alternativas:
            # diz-se as duas coisas, porque mostrar horas sem dizer que sao
            # doutro dia era deixar o cliente a achar que eram do dia que pediu.
            return {**delta, "avisos": avisos_com(estado, SEM_DISPONIBILIDADE)}

        # **O *hold* so entra no estado quando uma opcao bate a hora pedida.**
        # Sem hora, ou com a hora a bater mais do que uma opcao, o que se faz e
        # propor — e nao escolher por ele. O `stage` fica `awaiting_confirm`
        # apenas aqui, e e o que o `confirm_gate` exige na primeira das suas
        # tres perguntas.
        escolhida = _unica_na_hora(opcoes, slots.get("hora"))
        if escolhida is not None and escolhida.get("hold_id"):
            slots["hold"] = {
                "hold_id": str(escolhida["hold_id"]),
                "slot_id": str(escolhida.get("slot_id") or ""),
                "fact_id": escolhida.get("fact_id"),
                "expira_at": float(escolhida.get("expira_at") or 0),
            }
            return {**delta, "stage": "awaiting_confirm"}
        return delta

    return no


def _unica_na_hora(
    opcoes: Sequence[Mapping[str, Any]], hora: Any
) -> Mapping[str, Any] | None:
    """A opcao que bate a hora pedida, **se for exactamente uma**.

    Duas opcoes a mesma hora — dois profissionais livres — nao escolhem uma: o
    criterio 3 diz «nunca palpite», e escolher o primeiro da lista era um
    palpite sobre com quem o cliente quer ser atendido. Devolve `None`, e o
    cliente ve as duas.
    """
    if not isinstance(hora, int):
        return None
    batem = [o for o in opcoes if o.get("minutos_em_luanda") == hora]
    return batem[0] if len(batem) == 1 else None


def _intervalo_de(slots: Mapping[str, Any]) -> dict[str, str]:
    """O intervalo `de_at`/`ate_at` em UTC, do dia e da hora que o cliente deu.

    **Com hora, pede-se a hora; sem hora, o dia inteiro** — e as duas metades
    sao os dois caminhos do criterio 4:

    * `marcar` traz hora, o intervalo estreita a esse instante, a agenda
      devolve **uma** opcao e toma-se o *hold*: o cliente recebe o botao de
      confirmacao e nao uma lista de dez que ele nao pediu;
    * `disponibilidade` nao traz hora (`SLOTS_PARA_DISPONIBILIDADE`), o
      intervalo e o dia, e a agenda devolve **ate dez** — que e a proposta que o
      criterio 4 pede.

    Sem isto os dois caminhos colapsavam num: pedir sempre o dia inteiro fazia
    uma marcacao com hora exacta receber dez opcoes e nunca um *hold*; pedir
    sempre a hora exacta fazia as «ate 10» ser codigo morto. Medido nas duas
    direccoes.
    """
    data = slots.get("data")
    if not isinstance(data, str) or not data:
        return {}
    hora = slots.get("hora")
    if isinstance(hora, int):
        return {
            "de_at": datas.instante_utc(data, hora),
            "ate_at": datas.instante_utc(data, hora),
        }
    return {
        "de_at": datas.instante_utc(data, 0),
        "ate_at": datas.instante_utc(data, datas.MINUTOS_DO_DIA - 1),
    }


# -------------------------------------------------------------- o list_services


def list_services(deps: Dependencias):
    """Transicao 21: os servicos e os precos da loja.

    Cada servico sai como uma `Oferta` do *renderer* — `sku` = `service_id`,
    `nome`, `preco_tipo` — e o preco vem de um *fact* `price` vinculado ao mesmo
    `sku`. **E reuso exacto e nao analogia**: a `Oferta` tem os tres campos de um
    servico, e o `item` do §9.1 cita-a com a mesma regra de vinculo que cita um
    produto.

    **A duracao nao se cita, e e uma lacuna declarada e nao uma omissao.** O
    criterio 6 fala de *facts* `datetime`/`duration`, e o `KINDS` do
    `tls/erros.py` tem quatro valores — `price`, `stock`, `total`, `datetime` —
    e **nao** tem `duration`; o `BLOCOS` do *renderer* tem cinco e **nao** tem
    um bloco de duracao. Sem os dois, uma duracao escrita era um numero em prosa
    que o *renderer* recusa, de propria regra (§9.1). Logo esta vertical **nao
    diz** quanto tempo um servico leva, e o criterio 6 cumpre-se por nao haver
    duracao nenhuma a citar — nao por haver *fact* para ela. Esta em
    `docs/dividas-documentais.md`, e a decisao de quem o paga e devolvida ao
    fundador: o credor natural seria o KAM-032, que esta **fechado**.

    shortcut: esta vertical nao diz quanto tempo um servico leva, porque nao ha
    `kind` `duration` nem bloco de duracao no §9.1; revê-se quando o fundador
    nomear quem os acrescenta (a hipotese esta na `ANALISE-40`)
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        resultado = await _com_retry(
            lambda: _invocar(deps, estado, "list_services", {})
        )
        if not resultado.ok:
            return {"avisos": avisos_com(estado, _aviso_do_erro(resultado))}
        ofertas = tuple(
            {
                "sku": str(s["service_id"]),
                "nome": str(s.get("nome", "")),
                "preco_tipo": str(s.get("preco_tipo", "fixo")),
            }
            for s in resultado.data.get("servicos") or ()
        )
        return {"ofertas": ofertas, "facts": tuple(resultado.facts)}

    return no


# ------------------------------------------------------------- o confirm_gate


def confirm_gate(deps: Dependencias):
    """Transicoes 24 e 25: as tres perguntas, e as tres por `and`.

    **A mesma logica do Vendedor sobre outro campo** (§8.1: «a mesma logica,
    `cart_id` <-> `slot_hold_id`»): o do Vendedor le `cart["cart_id"]` e este le
    `slots["hold"]["hold_id"]`.

    **Nao se devolve qual delas falhou** — a mensagem ao cliente e a mesma, e
    dizer qual era um oraculo, pela razao que o `Confirmation.autoriza` do
    KAM-028 ja tinha escrito.

    ## O duplo toque da **uma** marcacao, e e aqui que isso se decide

    O criterio 5 pede «duplo toque em `confirm:{hold_id}` produz exactamente 1
    marcacao». Sao **duas** barreiras independentes, e nenhuma sozinha:

    1. o `stage` volta a `browsing` neste no quando a confirmacao nao vale — sem
       isso, um segundo toque encontrava `awaiting_confirm` outra vez e o unico
       obstaculo passava a ser a referencia, e dois toques no **mesmo** botao
       citam a **mesma** referencia;
    2. o `confirmBooking` do modulo `servicos` devolve `confirmou: false` quando
       encontra a marcacao **ja** confirmada, e quem serializa dois toques
       concorrentes e a restricao de exclusao da revisao `0025` — nao e codigo
       aplicacional (KAM-047, criterio 1, por escrito).

    **Eram "tres" e sao duas, e a terceira nao existia.** A versao anterior desta
    nota contava a `idempotency_key` do KAM-029 como barreira, e a revisao
    adversarial mediu que ela **nao se aplica a este caso** (`ANALISE-40`, achado
    9): a chave e `turn_id:seq`, e dois toques no mesmo botao sao duas mensagens
    de WhatsApp, dois `wamid`, dois `turn_id` — logo **duas** chaves diferentes.
    Ela protege a reexecucao do **mesmo** turno (um *job* repetido), que e outro
    caso e tambem conta; o que ela nao faz e o que o criterio 5 nomeia. Afirmar
    tres barreiras onde ha duas e, nesta casa, um defeito.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        slots = _slots_de(estado)
        botao = _botao_do_turno(estado)
        no_estagio = estado.get("stage") == "awaiting_confirm"

        # **A referencia vem do `referencia_a_confirmar`**, que e o mesmo dono
        # que o `compose` usou para emitir o botao: comparar com uma referencia
        # derivada aqui era deixar as duas divergirem (achado 6).
        referencia = referencia_a_confirmar(slots)
        cita_a_referencia = bool(referencia) and botao == (
            f"{PREFIXO_DE_CONFIRMACAO}{referencia}"
        )

        # **A validade so se pergunta a um *hold*.** Um `booking_id` nao expira:
        # exigir-lhe um `expira_at` fazia **todo** o cancelamento e **toda** a
        # remarcacao sairem `stale`, porque nenhum dos dois tem *hold*.
        hold = slots.get("hold")
        tem_hold = isinstance(hold, Mapping) and bool(hold.get("hold_id"))
        espera_por_hold = tem_hold and not (
            slots.get("cancelar") or isinstance(slots.get("remarcar"), str)
        )
        esta_valido = (not espera_por_hold) or (
            float(hold.get("expira_at", 0)) > deps.relogio()
        )

        if no_estagio and cita_a_referencia and esta_valido:
            return {}
        return {
            "avisos": avisos_com(estado, STALE_CONFIRMATION),
            "stage": "browsing",
        }

    return no


# ----------------------------------------------------------------- o book_slot


def book_slot(deps: Dependencias):
    """Transicoes 26 e 41: a tool `write`, com o botao que o cliente tocou.

    Serve **os dois** casos do criterio 7: uma marcacao nova chama `book_slot`, e
    uma remarcacao chama `reschedule_booking`, «que e atomico (cancela e marca na
    mesma transacao)». A atomicidade e do modulo `servicos` (KAM-047) e nao
    deste no — o que aqui se garante e que se chama **uma** tool e nao duas: um
    `cancel_booking` seguido de um `book_slot` daqui era precisamente o que o
    criterio proibe, porque uma falha a meio deixava o cliente sem nenhuma das
    duas marcacoes.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        slots = _slots_de(estado)
        hold = slots.get("hold") or {}
        confirmacao = Confirmation(
            # **O botao que o cliente tocou, e nao um reconstruido do hold.**
            # Reconstrui-lo fazia o passo 4 do `invoke` comparar o `hold_id`
            # consigo mesmo e dar sempre verdadeiro — a verificacao da
            # confirmacao ficava decorativa numa tool de escrita.
            botao=_botao_do_turno(estado),
            contact_id=estado["contact_id"],
            turn_id=estado["turn_id"],
        )
        remarcar = slots.get("remarcar")
        if isinstance(remarcar, str) and remarcar:
            nome, argumentos = (
                "reschedule_booking",
                {"booking_id": remarcar, "slot_id": str(hold.get("slot_id") or "")},
            )
        else:
            nome, argumentos = (
                "book_slot",
                {"hold_id": str(hold.get("hold_id") or "")},
            )

        resultado = await _com_retry(
            lambda: _invocar(
                deps,
                estado,
                nome,
                argumentos,
                confirmacao=confirmacao,
                chave=chave_do_turno(estado),
            )
        )
        if not resultado.ok:
            delta: dict[str, Any] = {
                "avisos": avisos_com(estado, _aviso_do_erro(resultado))
            }
            if _e_upstream(resultado):
                delta["handoff_motivo"] = MOTIVO_UPSTREAM
            return delta
        # O `hold` fica no estado: o `compose` precisa do `fact_id` do instante
        # para o poder citar, e um segundo toque e barrado pelo estagio e nao
        # pela ausencia do `hold`.
        slots["hold"] = dict(hold, confirmada=True)
        slots.pop("remarcar", None)
        return {
            "stage": "done",
            "slots": slots,
            "facts": tuple(resultado.facts),
            "draft": {"dados": dict(resultado.data)},
        }

    return no


# ------------------------------------------------------------ o cancel_booking


def cancel_booking(deps: Dependencias):
    """Transicoes 23, 42 e 43: o cancelamento, em **dois turnos**.

    ## Porque e que sao dois turnos, e nao foi escolha

    O §6.2 poe o `cancel_booking` em classe `write` com «botao» na coluna da
    confirmacao, e o passo 4 do `invoke` recusa uma tool de escrita sem botao.
    Mas o §8.1 liga o `classify` directamente a este no e nao desenha portao
    nenhum para ele.

    **Medido:** com uma chamada so, um «quero cancelar a B-12» corria a tool sem
    botao e recebia `VALIDATION_ERROR` — o cliente ouvia «nao consegui tratar
    esse pedido» a um pedido perfeitamente legivel, e **nenhum** cancelamento era
    possivel nesta vertical. A derivacao esta na aresta 43 do `arestas.py`.

    Logo:

    * **turno 1** (chegou pelo `classify`): guarda o `booking_id` em
      `slots["cancelar"]`, poe o `stage` em `awaiting_confirm` e o `compose`
      mostra `confirm:{booking_id}`. Nao se chama tool nenhuma;
    * **turno 2** (chegou pelo `confirm_gate`, que ja comparou o botao com a
      referencia): chama a tool com o botao que o cliente tocou.

    **«Nao me disse qual» nao e «nao existe».** Sem referencia no texto e sem
    cancelamento pendente, o aviso e `REFERENCIA_EM_FALTA` e o cliente ouve a
    pergunta — ver a nota do cabecalho.

    O isolamento por contacto nao e deste no: e da tool, que so ve marcacoes do
    proprio contacto (§6.2, «tenant + contacto»), e da RLS. Tres barreiras, e
    nenhuma sozinha.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        slots = _slots_de(estado)
        pendente = slots.get("cancelar")
        botao = _botao_do_turno(estado)
        # O mesmo dono que o `compose` e o `confirm_gate` usam (achado 6).
        confirmado = bool(pendente) and botao == (
            f"{PREFIXO_DE_CONFIRMACAO}{referencia_a_confirmar(slots)}"
        )

        if not confirmado:
            # Turno 1: identifica e **pergunta**. O `booking_id` sai do texto, e
            # um cancelamento pendente de um turno anterior continua a valer —
            # o cliente nao tem de repetir a referencia.
            achado = _REFERENCIA_DE_MARCACAO.search(_texto_do_cliente(estado))
            referencia = achado.group(1) if achado else pendente
            if not referencia:
                return {"avisos": avisos_com(estado, REFERENCIA_EM_FALTA)}
            slots["cancelar"] = referencia
            return {"slots": slots, "stage": "awaiting_confirm"}

        resultado = await _com_retry(
            lambda: _invocar(
                deps,
                estado,
                "cancel_booking",
                {"booking_id": str(pendente)},
                confirmacao=Confirmation(
                    # O botao que o cliente tocou, e nao um reconstruido: ver a
                    # nota do `book_slot`.
                    botao=botao,
                    contact_id=estado["contact_id"],
                    turn_id=estado["turn_id"],
                ),
                chave=chave_do_turno(estado),
            )
        )
        if not resultado.ok:
            delta: dict[str, Any] = {
                "avisos": avisos_com(estado, _aviso_do_erro(resultado))
            }
            if _e_upstream(resultado):
                delta["handoff_motivo"] = MOTIVO_UPSTREAM
            return delta
        # O pendente sai: sem isto, um `confirm:` repetido encontrava-o outra vez
        # e a unica barreira passava a ser a chave de idempotencia.
        slots.pop("cancelar", None)
        return {
            "slots": slots,
            "stage": "done",
            "draft": {"dados": dict(resultado.data)},
            "facts": tuple(resultado.facts),
        }

    return no


# ------------------------------------------------------------------- o compose


def ask_repeat(deps: Dependencias):
    """Transicao 6 -> 33: a nota de voz que nao se percebeu (§10).

    **Proprio, pelo texto e nao pela logica** — ver o `MSG_FORA_DE_AMBITO`. O
    `_resposta_estatica` e o do Vendedor: e ele que garante que estes textos nao
    passam pelo `validate` e por isso nao levam digitos.
    """

    async def no(_estado: dict[str, Any]) -> dict[str, Any]:
        return _resposta_estatica(MSG_REPETIR)

    return no


def safe_reply(deps: Dependencias):
    """Transicoes 9, 17 e 32 -> 34: o texto seguro, escolhido pelo veredicto.

    **Proprio, pelo texto e nao pela logica.** O do Vendedor diz «so posso
    ajudar com os produtos, os precos e os pedidos desta loja», que e a resposta
    errada numa vertical de marcacoes — e e a resposta que a transicao 17 da a
    toda a intencao `outro`. Ver o `MSG_FORA_DE_AMBITO`.

    O `MSG_CARTAO` **reutiliza-se**, e e a assimetria certa: o §8.4 manda avisar
    o cliente de que a loja nunca pede dados de cartao nesta conversa, e essa
    frase nao fala de catalogo nem de agenda — e da plataforma, e e a mesma nas
    duas verticais.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        guarda = estado.get("guard")
        veredicto = guarda.get("veredicto") if isinstance(guarda, Mapping) else None
        if veredicto == "card_data":
            return _resposta_estatica(MSG_CARTAO)
        return _resposta_estatica(MSG_FORA_DE_AMBITO)

    return no


def compose(deps: Dependencias):
    """Transicao 27: os blocos. **Nenhum numero em prosa** (ADR-007, DoD).

    ## As dez opcoes NAO saiem como botoes, e o credor esta nomeado

    O criterio 4 fala de «10 opcoes (limite de linhas de **lista interactiva**)»,
    e e uma lista — nao botoes. Mas o `PortaDeSaida.enfileirar` recebe
    `botoes: Sequence[str]`: **so identificadores**, sem rotulo e sem tipo de
    corpo. Do outro lado, o `packages/core-ts/src/outbound/contrato.ts` distingue
    um `CorpoDeBotoes` (`MAXIMO_DE_BOTOES = 3`) de um `CorpoDeLista`
    (`MAXIMO_DE_LINHAS = 10`, e cada linha leva `{id, titulo}`), e o
    `outbound/decisao.ts` recusa um corpo de botoes com mais de tres **antes** de
    qualquer chamada HTTP.

    Dez identificadores por esta porta chegavam ao Outbound como dez **botoes** e
    eram recusados — um corpo que se sabe invalido antes de o produzir. Por isso:

    * as opcoes saiem como blocos **`datetime`**, um por opcao, cada um citado
      pelo `fact_id` do *slot* — o que cumpre o criterio 6 e cabe no corpo;
    * os **botoes** sao os tres que o canal aceita: confirmar, cancelar, humano.

    O cliente escolhe por escrita, e o `slots_collect` le a hora que ele
    escrever. **O credor e o KAM-015** (Outbound), que tem de dar a
    `PortaDeSaida` um tipo de corpo e um rotulo por linha para uma lista de ate
    dez linhas poder chegar ao canal. Esta em `docs/dividas-documentais.md`.

    shortcut: as opcoes saem como blocos `datetime` no corpo e nao como linhas
    de uma lista interactiva, pelo que o cliente escolhe por escrita; revê-se
    quando o KAM-015 der a `PortaDeSaida` um tipo de corpo e um rotulo por linha

    ## O botao de confirmacao sai **com** um *hold*, e so com um

    Um `confirm:{hold_id}` sem *hold* no estado era um botao que o
    `confirm_gate` ia recusar sempre — e o cliente ficava com um botao morto no
    ecra, que e pior do que nenhum.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        facts = tuple(estado.get("facts") or ())
        ofertas = tuple(estado.get("ofertas") or ())
        avisos = tuple(estado.get("avisos") or ())
        slots = _slots_de(estado)
        rascunho = estado.get("draft") or {}
        blocos: list[dict[str, Any]] = []

        for aviso in avisos:
            frase = FRASE_DO_AVISO[aviso]
            if frase:
                blocos.append({"type": "text", "text": frase})

        pergunta = slots.get("pergunta")
        if pergunta in PERGUNTAS:
            # **Uma e so uma.** O `slots["pergunta"]` e um campo singular, pelo
            # que nao ha caminho por onde duas perguntas cheguem aqui.
            blocos.append({"type": "text", "text": FRASE_DA_PERGUNTA[pergunta]})

        for oferta in ofertas:
            blocos.append(
                {
                    "type": "item",
                    "sku": oferta["sku"],
                    "show": _mostrar_de(oferta, facts),
                }
            )

        # As opcoes de disponibilidade, uma linha por opcao, **citadas**. So as
        # que tem *fact* deste turno: uma opcao de um turno anterior nao tem
        # *fact* para citar (§5.3, «so deste turno») e o *renderer* levantava.
        por_id = {f.fact_id for f in facts if f.kind == "datetime"}
        citados: set[str] = set()
        for opcao in slots.get("opcoes") or ():
            fact_id = opcao.get("fact_id")
            if fact_id in por_id and fact_id not in citados:
                blocos.append({"type": "datetime", "fact_id": fact_id})
                citados.add(fact_id)

        # **Todo o *fact* `datetime` deste turno sai citado, e nao so os das
        # opcoes.** Sem isto, o turno em que a marcacao se confirma dizia «a sua
        # marcacao ficou registada» **sem dia nem hora**: o instante que a tool
        # de escrita devolveu nao tinha caminho para o corpo, e o `fact_id` que
        # o `book_slot` guardava «para o `compose` citar» nunca era citado.
        # Medido pela revisao adversarial (`ANALISE-40`, achado 13).
        for fact in facts:
            if fact.kind == "datetime" and fact.fact_id not in citados:
                blocos.append({"type": "datetime", "fact_id": fact.fact_id})
                citados.add(fact.fact_id)

        # **A referencia vem do `referencia_a_confirmar`, que tem um dono so** —
        # ver a nota dele. Escrita aqui a mao, o botao citava o `hold_id` numa
        # remarcacao cuja tool cita o `booking_id`.
        referencia = referencia_a_confirmar(slots)
        if referencia and estado.get("stage") == "awaiting_confirm":
            blocos.append(
                {
                    "type": "buttons",
                    "ids": [
                        f"{PREFIXO_DE_CONFIRMACAO}{referencia}",
                        BOTAO_CANCELAR,
                        BOTAO_HUMANO,
                    ],
                }
            )
        elif any(a in AVISOS_QUE_OFERECEM_HUMANO for a in avisos):
            # **A oferta de handoff e um botao e nao uma frase.** O §6.5 manda
            # «mensagem honesta + **oferta** de handoff» para o
            # `LIMIT_EXCEEDED`, e «Um colega pode ajudar» sem nada em que
            # carregar nao e uma oferta: nao abre *handoff* nenhum. Medido pela
            # revisao adversarial (`ANALISE-40`, achado 11), que viu o `compose`
            # a produzir **um** bloco de texto e zero botoes.
            blocos.append({"type": "buttons", "ids": [BOTAO_HUMANO]})

        dados = rascunho.get("dados") if isinstance(rascunho, Mapping) else None
        if isinstance(dados, Mapping) and dados.get("booking_id"):
            # **Decide-se pelo `estado` e nao pela presenca do `booking_id`.** O
            # `cancel_booking` tambem devolve um `booking_id`, pelo que a
            # condicao anterior dizia «A sua marcacao ficou registada» a quem
            # acabou de **cancelar**. Medido pela revisao adversarial
            # (`ANALISE-40`, achado 12).
            frase = _FRASE_DO_DESFECHO.get(str(dados.get("estado") or ""))
            if frase:
                blocos.append({"type": "text", "text": frase})

        if not blocos:
            blocos.append({"type": "text", "text": MSG_NAO_ENTENDI})
        # **Preserva o rascunho em vez de o substituir** — a licao do achado 9 da
        # revisao do KAM-031: um `dict` novo apagava o `dados` que os nos de tool
        # deixaram, e na segunda passagem do ciclo da transicao 29 o `compose`
        # perdia o que tinha para dizer e produzia uma frase de omissao que
        # **passa** o validador e **e enviada**.
        return {"draft": dict(rascunho, blocos=tuple(blocos))}

    return no


def _mostrar_de(oferta: Mapping[str, str], facts: Sequence[Any]) -> list[str]:
    """Que campos de um servico se podem mostrar, **dados os *facts* que ha**.

    O `renderizar` levanta se o bloco pedir `price` e nao houver *fact* `price`
    para aquele `sku`. Pedir sempre era mandar o `compose` produzir um bloco
    invalido sempre que a tool nao tivesse corrido — e o turno acabava em
    *handoff* por um defeito nosso. **Nao se pede `stock`**: um servico nao tem
    unidades.
    """
    mostrar = ["name"]
    sku = oferta["sku"]
    tem = {(f.kind, f.sku) for f in facts}
    if oferta.get("preco_tipo") == "sob_consulta" or ("price", sku) in tem:
        mostrar.append("price")
    return mostrar


#: O que se diz por cada desfecho de uma escrita na agenda. **Sem digitos**: o
#: instante sai no bloco `datetime`, citado, e nao nestas frases.
#:
#: **Duas entradas e nao uma**, e e a correccao do achado 12: o `cancel_booking`
#: tambem devolve um `booking_id`, pelo que uma condicao pela **presenca** dele
#: dizia «a sua marcacao ficou registada» a quem acabou de cancelar. Decide-se
#: pelo `estado`, que e o campo que diz o que aconteceu.
#:
#: O `hold` e o `expirada` **nao** estao aqui de proposito: nenhum deles e
#: desfecho de uma escrita que este grafo faca — o `hold` e intermedio e a
#: expiracao e do varrimento (`servicos.expirar_holds`, KAM-048).
_FRASE_DO_DESFECHO: Final = {
    "confirmada": (
        "A sua marcacao ficou registada. Vai receber um aviso antes da hora."
    ),
    "cancelada": "A sua marcacao foi cancelada.",
}

#: O que a Rececionista diz quando a intencao sai das nove, ou quando a guarda
#: de entrada recusa o turno.
#:
#: **Nao se reutiliza o texto do Vendedor, e isso e uma correccao.** O
#: `safe_reply` dele escreve «So posso ajudar com os **produtos**, os **precos**
#: e os **pedidos** desta loja», e a revisao adversarial mediu-o a sair da
#: Rececionista (`ANALISE-40`, achado 10) — pela transicao 17, que e o caminho
#: mais comum que ha. O §5.4 separa «Estrutura de prompt e *compose* com
#: placeholders» (partilhada) de «Texto de persona e exemplos» (propria), e um
#: assistente de marcacoes a falar de catalogo nao e um defeito de estilo: e a
#: resposta errada, e contradiz a `apresentacao` do `registry/servicos.yaml`.
#:
#: **Sem digitos**, pela regra do bloco `text` (§9.1).
MSG_FORA_DE_AMBITO: Final = (
    "So posso tratar de marcacoes e dar informacoes desta loja. Prefere falar "
    "com um colega?"
)

#: O que se diz quando a nota de voz nao se entendeu (§10, `ask_repeat`).
MSG_REPETIR: Final = (
    "Nao consegui ouvir bem essa mensagem. Pode escrever o que precisa?"
)

#: Os avisos que, por si, abrem a oferta de um colega. **Nao sao todos**: um
#: `SLOT_TAKEN` ou um `SEM_DISPONIBILIDADE` resolvem-se mostrando outras horas,
#: e um botao de humano ali empurrava para uma pessoa o que a agenda resolve. Os
#: tres que entram sao os que o §6.5 manda tratar assim — o limite do plano e os
#: dois de backend indisponivel.
AVISOS_QUE_OFERECEM_HUMANO: Final = (
    LIMIT_EXCEEDED,
    UPSTREAM_TIMEOUT,
    UPSTREAM_DOWN,
)

#: O que se diz quando nao ha nada para dizer.
MSG_NAO_ENTENDI: Final = (
    "Nao percebi o que precisa. Posso tratar de marcacoes e dar informacoes da loja."
)


#: Os vinte e dois nos pelo nome: os catorze importados do Vendedor e os oito
#: deste ficheiro. E a tabela que o `build_graph` percorre, e e ela que faz «um
#: no na tabela de arestas sem funcao» ser impossivel — o `build_graph` levanta
#: se as duas listas nao baterem.
NOS_DO_GRAFO: Final = {
    # Reutilizados sem uma linha nova (ADR-012).
    "ingest": ingest,
    "stt": stt,
    "guard_in": guard_in,
    "tools_info": tools_info,
    "validate": validate,
    "guard_out": guard_out,
    "send": send,
    "handoff_prepare": handoff_prepare,
    "handoff_wait": handoff_wait,
    "handoff_close": handoff_close,
    "draft_prepare": draft_prepare,
    "draft_wait": draft_wait,
    # Proprios desta vertical.
    "ask_repeat": ask_repeat,
    "safe_reply": safe_reply,
    "classify": classify,
    "slots_collect": slots_collect,
    "check_availability": check_availability,
    "list_services": list_services,
    "confirm_gate": confirm_gate,
    "book_slot": book_slot,
    "cancel_booking": cancel_booking,
    "compose": compose,
}
