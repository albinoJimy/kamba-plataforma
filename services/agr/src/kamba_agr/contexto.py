"""O vocabulario do AGR (KAM-025) e a leitura do `agent_invocation`.

Num ficheiro so, pela razao que o `chr/contrato.ts` ja escreveu: dois
escritores sobre o mesmo desenho, sem um nome canonico para seguir, produzem
dois nomes para a mesma coisa. Os nomes aqui sao os do dicionario §3.13
(contrato `agent_invocation`, emenda 1.20) e §3.24 (o que este ticket
acrescenta).

## O `tenant_id` vem daqui e de nenhum outro sitio

E o criterio do DoD, o ADR-015 e a razao de este modulo existir separado da
API. O `ChannelContext` e resolvido pelo CHR contra `tenant_channels`, com um
`phone_number_id` de um corpo **assinado**; o que chega ao AGR e o resultado
dessa resolucao. O texto da mensagem **nao esta neste contrato** — nem o
`wamid` o traz — e por isso nao ha caminho por onde um `tenant_id=...` escrito
por um cliente possa substituir o do contexto: `InvocacaoDoAgente` e imutavel
(`frozen=True`) e o `turno.py` nunca lhe reescreve um campo.

A bateria `test_isolamento.py` confirma-o pelo lado de fora: injecta
`tenant_id`, `thread_id` e `vertical` falsos num campo de texto do corpo e
confere que o que sai e o do contexto.

## Sem Pydantic, e a razao e a do `app.py` do KAM-001

O AGR serve-se de Starlette e nao de FastAPI porque no KAM-001 nao havia
esquemas de pedido para validar (`ADR-L001`). Agora ha **um**, com nove campos
de forma fechada, e trazer o Pydantic para o validar era pagar uma arvore de
dependencias em producao por um `TypedDict` com nove `isinstance`. O que se
perde e a mensagem de erro bonita; o que se ganha e um fecho que nao cresce.

**A validacao e por forma e nao por lista de proibidos.** Um `tenant_id` tem a
forma de um UUID canonico ou nao entra; um `thread_id` tem de ser exactamente
`{tenant_id}:{contact_id}` **dos campos que vieram ao lado**, e nao so «dois
UUID com dois pontos no meio» — senao um `thread_id` coerente com ele mesmo e
incoerente com o `tenant_id` passava, e o que decide a tranca e o `thread_id`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

#: Os nove campos **obrigatorios** do contrato `agent_invocation` (dicionario
#: §3.13), pela ordem em que o dicionario os escreve. E lista **fechada**: um
#: campo a mais no corpo e um corpo que nao conhecemos, e recusa-se. O unico
#: opcional — a `persona`, do KAM-118 — esta no `CAMPOS_OPCIONAIS`.
CAMPOS: Final = (
    "tenant_id",
    "contact_id",
    "conversation_id",
    "channel_id",
    "wamid",
    "type",
    "modo",
    "thread_id",
    "vertical",
)

#: Os modos de uma conversa. E o `CHECK` de `conversations.mode` (§3.13) e o
#: espelho de `MODOS` em `packages/core-ts/src/chr/contrato.ts`.
MODOS: Final = ("bot", "dono", "humano", "pausada")

#: O unico modo em que um turno entra no grafo. Os outros tres vao ao HND, e e
#: o criterio 6 — a invariante do `docs/tecnica/02` §11 regra 4.
MODO_DO_BOT: Final = "bot"

#: As verticais do Piloto. Espelho de `VERTICAIS_DO_PILOTO` do
#: `chr/contrato.ts` e de `fluxo_piloto.py`; lista de **permitidas**, pela
#: razao do criterio 5 do KAM-014 — `assistente` por igualdade nao via
#: `assistente_v2`.
#:
#: **O `dono` nao entra aqui, e e a decisao do KAM-118 e nao um esquecimento.**
#: A divida 98 previa que a persona do dono chegasse pela `vertical`, e a lista
#: tivesse de crescer. Chega pela `persona`, que e outro campo: a vertical e do
#: **canal** (`tenant_channels.vertical`, que nao muda quando quem escreve e o
#: dono) e a persona e de **quem escreve** (`contacts.papel`). Pondo o `dono`
#: aqui, o CHR podia escrever `vertical: dono` num canal e a porta aceitava um
#: canal que nao existe; e o dicionario recusa «persona» como sinonimo de
#: vertical.
VERTICAIS: Final = ("vendedor", "servicos")

#: Os campos opcionais do contrato: a `persona` (KAM-118) e o `botao`
#: (KAM-211). **Aditivos da v1**: um CHR anterior nao os escreve, e a porta le
#: entao a omissao. Ficam fora do `CAMPOS` de proposito — o `CAMPOS` e a lista
#: dos **obrigatorios**, e ha ensaios que a percorrem a apagar um campo de cada
#: vez e a esperar `campo_em_falta`.
CAMPOS_OPCIONAIS: Final = ("persona", "botao")

#: O `wa_type` da resposta a um botao ou a uma lista (`button_reply`,
#: `list_reply`). So ele leva `botao`.
TIPO_INTERACTIVO: Final = "interactive"

#: A forma do `botao`: o `reply.id` que **nos** emitimos — `confirm:{uuid}`,
#: `falar_com_humano`, os `id` do aviso do §3.19 —, e nunca o titulo. Alfabeto
#: fechado e sem espaco: um `id` nao e texto do cliente, e um valor com outra
#: forma e um CHR a escrever mal o campo. O tecto e o do `id` de um botao na
#: Cloud API (256), pela razao do `WAMID_MAXIMO`. Espelho de `FORMA_DO_BOTAO`
#: em `packages/core-ts/src/entrada/contrato.ts`.
BOTAO_MAXIMO: Final = 256
_BOTAO = re.compile(r"\A[A-Za-z0-9_.:-]{1,%d}\Z" % BOTAO_MAXIMO)

#: Quem escreve: o `CHECK` de `contacts.papel` e o `enum` do campo `persona` do
#: `agent_invocation.v1.json`. Lista **fechada**, pela razao do `VERTICAIS`.
PERSONAS: Final = ("cliente", "dono")
PERSONA_CLIENTE, PERSONA_DONO = PERSONAS

#: A persona de uma invocacao sem o campo. **`cliente` e a omissao segura**: um
#: corpo de um CHR que nao saiba do dono e o de um cliente, e o contrario — ler
#: a ausencia como `dono` — dava as tools do dono a quem nao provou ser dono.
PERSONA_POR_OMISSAO: Final = PERSONA_CLIENTE

#: A chave do `AgentRegistry` quando quem escreve e o dono: o `id` de
#: `registry/dono.yaml`. Um so registo para a persona, seja qual for a vertical
#: do canal — o Assistente do Dono e o mesmo numa loja e num salao.
CHAVE_DO_DONO: Final = "dono"

_UUID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

#: A forma de um `wamid`. Tecto de comprimento porque o valor vem da Meta e um
#: campo sem tecto e memoria ilimitada a custa de outrem — a razao do
#: `PAYLOAD_MAXIMO` da revisao `0008`. O alfabeto e o do base64url mais o `=`,
#: que e o que os `wamid` observados usam (`docs/logs.md` §2.1).
WAMID_MAXIMO: Final = 256
_WAMID = re.compile(r"\A[A-Za-z0-9_=+/.:-]{8,%d}\Z" % WAMID_MAXIMO)

#: A forma de `agent_invocation.type` — o `wa_type` do dicionario §3.12. Nao se
#: valida o **dominio** aqui, e e deliberado: a lista dos doze valores vive na
#: `inbound_events.kind` e e o CHR que a respeita; repeti-la aqui criava uma
#: segunda copia que divergia no dia em que a Meta acrescentasse um tipo. O que
#: aqui se exige e a forma, porque o valor **e etiqueta de metrica**.
_TYPE = re.compile(r"\A[a-z][a-z0-9_]{0,30}\Z")


class InvocacaoInvalidaError(ValueError):
    """O corpo nao e um `agent_invocation`.

    O `codigo` e o que vai para `error_code` do *logger* e para a etiqueta da
    metrica: tem a forma de identificador da *allowlist* e **nunca** leva o
    valor recusado. Um corpo invalido pode ser qualquer coisa, incluindo um
    telefone no sitio de um UUID, e e exactamente por isso que a mensagem nao o
    repete (`docs/logs.md` §5; e a licao do `arranque_invalido` do KAM-001).
    """

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class InvocacaoDoAgente:
    """O *job* que o CHR entrega ao AGR. Contrato `agent_invocation` (§3.13).

    `frozen=True` nao e zelo: e onde o «o `tenant_id` e imutavel» do
    `docs/tecnica/02` §5.3 deixa de ser uma frase e passa a ser uma propriedade
    do tipo. Uma tentativa de reescrever `tenant_id` levanta
    `FrozenInstanceError`, e ha um teste que a provoca.
    """

    tenant_id: str
    contact_id: str
    conversation_id: str
    channel_id: str
    wamid: str
    type: str
    modo: str
    thread_id: str
    vertical: str
    #: KAM-118. Com omissao, e por isso o ultimo: quem constroi a invocacao com
    #: os nove campos — os ensaios, o `golden.py` — continua a construir a de um
    #: cliente sem saber que o campo existe.
    persona: str = PERSONA_POR_OMISSAO
    #: KAM-211. O `reply.id` de uma resposta interactiva, ou `None`. So existe
    #: num `type` `interactive`: um texto que imite um botao chega como texto, e
    #: o CHR nao lhe da `botao` nenhum.
    botao: str | None = None

    @property
    def chave_do_registo(self) -> str:
        """A chave do `AgentRegistry` para este turno. Ver `chave_do_registo`."""
        return chave_do_registo(self.persona, self.vertical)

    @property
    def turn_id(self) -> str:
        """O identificador do turno. E o `wamid` (dicionario §3.24).

        Propriedade derivada e **nao** campo: o §3.13 diz, por escrito, que
        duplicar o mesmo valor com dois nomes num contrato era pedir que
        divergissem. O nome `turn_id` existe porque e o que a *allowlist* do
        `kamba_core.logger` conhece e o que a `idempotency_key = turn_id:seq`
        do criterio 4 nomeia; o valor e um so.
        """
        return self.wamid

    def chave_de_envio(self, seq: int) -> str:
        """`idempotency_key = turn_id:seq` — criterio 4.

        Esta aqui, e nao em quem envia, porque a chave e uma propriedade do
        turno: dois `seq` iguais no mesmo turno **tem** de dar a mesma chave,
        corra o turno uma vez ou cinco. E o que torna «0 duplicados» uma
        consequencia da repeticao e nao uma coincidencia.

        O `seq` e por turno e comeca em 0; nao e o `handoff_seq` do estado, que
        conta *handoffs* e e do KAM-034.
        """
        return chave_de_envio(self.turn_id, seq)


def _texto(corpo: dict[str, Any], campo: str) -> str:
    valor = corpo.get(campo)
    if not isinstance(valor, str):
        raise InvocacaoInvalidaError(f"campo_invalido_{campo}")
    return valor


def ler_invocacao(corpo: Any) -> InvocacaoDoAgente:
    """Le um `agent_invocation` de um corpo JSON ja descodificado.

    Recusa — e nao corrige — por esta ordem: o que nao e objecto, o que tem
    campos a mais, o que tem campos a menos, e o que tem um campo com a forma
    errada. **Campos a mais recusam-se**, em vez de se ignorarem, porque o
    contrato do dicionario e fechado: um campo que o AGR nao conhece e, no
    melhor caso, uma versao do CHR a frente desta, e correr um turno com metade
    de um contrato novo e pior do que recusar o *job* e deixar o BullMQ repetir.
    """
    if not isinstance(corpo, dict):
        raise InvocacaoInvalidaError("corpo_nao_e_objecto")

    chaves = set(corpo)
    if chaves - set(CAMPOS) - set(CAMPOS_OPCIONAIS):
        # O nome do campo a mais **nao** entra no codigo: vem de fora, e um
        # dicionario espalhado em argumentos trazia conteudo nas chaves (e a
        # razao do `MOTIVO_DESCONHECIDO` de `logger/politica.py`).
        raise InvocacaoInvalidaError("campo_desconhecido")
    if set(CAMPOS) - chaves:
        raise InvocacaoInvalidaError("campo_em_falta")

    valores = {campo: _texto(corpo, campo) for campo in CAMPOS}

    for campo in ("tenant_id", "contact_id", "conversation_id", "channel_id"):
        if not _UUID.fullmatch(valores[campo]):
            raise InvocacaoInvalidaError(f"campo_invalido_{campo}")
    if not _WAMID.fullmatch(valores["wamid"]):
        raise InvocacaoInvalidaError("campo_invalido_wamid")
    if not _TYPE.fullmatch(valores["type"]):
        raise InvocacaoInvalidaError("campo_invalido_type")
    if valores["modo"] not in MODOS:
        raise InvocacaoInvalidaError("campo_invalido_modo")
    if valores["vertical"] not in VERTICAIS:
        raise InvocacaoInvalidaError("campo_invalido_vertical")
    if valores["thread_id"] != thread_id_de(valores["tenant_id"], valores["contact_id"]):
        # Nao se recalcula em silencio: um `thread_id` que nao case com o par
        # que vem ao lado e um contrato incoerente, e a tranca depende dele.
        raise InvocacaoInvalidaError("thread_id_incoerente")

    # **Presente, tem de ser um dos dois; ausente, e `cliente`.** Um `null` ou
    # um `""` nao sao ausencia: sao um CHR a escrever o campo mal, e recusar
    # faz o defeito aparecer no primeiro turno em vez de o tornar num cliente
    # que era dono.
    persona = corpo.get("persona", PERSONA_POR_OMISSAO)
    if not isinstance(persona, str) or persona not in PERSONAS:
        raise InvocacaoInvalidaError("campo_invalido_persona")

    # **O `botao` so vem com `type: interactive`, e so com a forma de um `id`.**
    # Um `botao` num texto e o que o criterio do KAM-211 chama «texto que imita
    # um botao»: o CHR nao o escreve, e um corpo que o traga e incoerente — o
    # mesmo raciocinio do `thread_id_incoerente`. Recusa-se em vez de se
    # ignorar, pela razao da `persona`: um `null` e um CHR a escrever mal.
    botao = None
    if "botao" in corpo:
        botao = corpo["botao"]
        if (
            not isinstance(botao, str)
            or not _BOTAO.fullmatch(botao)
            or valores["type"] != TIPO_INTERACTIVO
        ):
            raise InvocacaoInvalidaError("campo_invalido_botao")

    return InvocacaoDoAgente(**valores, persona=persona, botao=botao)


def chave_do_registo(persona: object, vertical: object) -> str:
    """A chave do `AgentRegistry`: `dono` se quem escreve e o dono, senao a vertical.

    **E o unico sitio onde a regra vive** (KAM-118), e tem dois leitores: o
    `AgentRegistry.resolve`, no turno, e a `PortaDeGrafos.da_thread`, que le a
    `persona` e a `vertical` do *checkpoint* para reencontrar o grafo de uma
    *thread* interrompida. Escrita duas vezes, a retoma de um *handoff* do dono
    podia acordar o grafo do Vendedor.

    So a igualdade exacta a `dono` muda a chave. Qualquer outro valor — a
    omissao, um `None` de um *checkpoint* anterior ao campo — da a vertical, que
    e o comportamento de antes do KAM-118.
    """
    if persona == PERSONA_DONO:
        return CHAVE_DO_DONO
    return vertical if isinstance(vertical, str) else ""


def thread_id_de(tenant_id: str, contact_id: str) -> str:
    """`thread_id` de um par (tenant, contacto). Dicionario §3.1.

    Espelho exacto de `threadIdDe` em `packages/core-ts/src/chr/contrato.ts`.
    O telefone nunca entra aqui (ADR-010): o exploratorio escrevia
    `msisdn_hash+tenant` e o `docs/tecnica/02` §12 corrige-o por escrito.
    """
    return f"{tenant_id}:{contact_id}"


def chave_de_envio(turn_id: str, seq: int) -> str:
    """`idempotency_key = {turn_id}:{seq}` — dicionario §3.24.

    Funcao de modulo **e** metodo da invocacao, e o metodo chama esta: o grafo
    (KAM-031) tem o `turn_id` do estado e nao a `InvocacaoDoAgente`, e escrever
    o formato a segunda vez era deixar as duas divergirem no dia em que alguem
    mudasse o separador. Um formato que o dicionario fixa tem **um** dono.
    """
    if seq < 0:
        raise ValueError("seq negativo")
    return f"{turn_id}:{seq}"
