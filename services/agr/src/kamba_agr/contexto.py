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

#: Os nove campos do contrato `agent_invocation` (dicionario §3.13), pela ordem
#: em que o dicionario os escreve. E lista **fechada**: um campo a mais no
#: corpo e um corpo que nao conhecemos, e recusa-se.
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
VERTICAIS: Final = ("vendedor", "servicos")

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
    if chaves - set(CAMPOS):
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

    return InvocacaoDoAgente(**valores)


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
