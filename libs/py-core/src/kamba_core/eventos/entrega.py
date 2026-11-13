"""A entrega de um evento a um consumidor Python, do lado de quem a recebe (KAM-194).

A fila e TypeScript (BullMQ) e os consumidores com efeito em Python sao dois — o
AGR (KAM-038) e o IDX (KAM-061). Quem os liga e a **casca** do
`packages/core-ts/src/eventos/ponte.ts`, pelo molde do `agr/shim.ts` (ADR-L004,
Decisao 1): tira um *job* de `evt.<consumer>.p<0..15>` e faz `POST` a
`/internal/event` com este corpo. A casca nao decide nada e nao abre ligacao a
base; a decisao toda fica do lado Python, e o que esta aqui e o que os dois
lados Python tem de ler igual.

## O corpo, e os dois ponteiros que nao sao autoridade

    {event_id, tenant_id, envelope, tentativas}

Quatro campos, lista **fechada** (dicionario §3.33). O `event_id` e o `jobId`
do *job*, o `tenant_id` vem dos dados do *job*, e o `tentativas` e o
`attemptsMade + 1` — conta a partir de 1, e e a fila que conta: com duas
replicas um contador nosso contava metade cada uma.

O `envelope` e o que o publicador pos no *job*, **ja convertido** a versao que a
subscricao declara (`evt_subscricoes.versao_max`). Pode vir **nulo**: o
reconciliador (§6.5) repoe *jobs* so com o `tenant_id`, sem envelope, e quem
recebe le-o do arquivo (`SQL_ENVELOPE_DO_ARQUIVO`) — que e o que o
`trabalhador_bullmq.ts` do KAM-006 faz para **todos** os *jobs*.

O `event_id` e o `tenant_id` sao ponteiros da fila: servem para abrir a DLQ
quando o envelope nao se le, e para ler o arquivo com o contexto certo. Quando
o envelope se le, confrontam-se com ele, e o contexto do consumo sai **sempre**
do envelope validado (ADR-015).

## O que nao esta aqui

O AGR tem a sua copia do `ler_entrega` (`kamba_agr/eventos/consumo.py`), mais
antiga do que este modulo. Nao se mudou para aqui porque as receitas de
mutacao do `db/mutacoes.py` apontam para o texto daquele ficheiro, e mudar o
sitio do codigo partia-as sem medir nada. O que impede as duas de divergirem e
o `TestParidadeDaEntrega` da `services/agr/tests/test_eventos.py`.
shortcut: duas copias do leitor do corpo, presas por um ensaio de paridade; revê-se quando o AGR passar a importar daqui.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

#: Os quatro campos do corpo de `/internal/event`. Lista **fechada**.
CAMPOS_DA_ENTREGA: Final = ("event_id", "tenant_id", "envelope", "tentativas")

#: O envelope do arquivo, pelo `event_id`. Corre com o contexto do *tenant* que
#: a fila declarou: o `events_log` tem RLS, e sem contexto devolve zero linhas
#: — que se le «o arquivo nao tem este evento». E o `SQL_ENVELOPE_DO_EVENTO` do
#: `trabalhador_bullmq.ts`, com o marcador do `psycopg`/`pg8000`.
SQL_ENVELOPE_DO_ARQUIVO: Final = """
  SELECT envelope FROM platform.events_log WHERE event_id = %s::uuid
"""


class EntregaInvalidaError(ValueError):
    """O corpo nao e uma entrega de evento. O chamador responde 400.

    O `codigo` tem forma de identificador e **nunca** leva o valor recusado: um
    corpo invalido pode ser qualquer coisa.
    """

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class Entrega:
    """O corpo lido: os dois ponteiros da fila, o envelope cru e a tentativa."""

    event_id: str
    tenant_id: str
    envelope: Any
    tentativas: int


def ler_entrega(corpo: Any) -> Entrega:
    """Le o corpo de `/internal/event`. Levanta `EntregaInvalidaError`.

    Recusa — e nao corrige — por esta ordem: o que nao e objecto, campos a mais,
    campos a menos, campos com a forma errada. O `envelope` pode ser **nulo**
    (o *job* do reconciliador), mas a chave tem de estar.
    """
    if not isinstance(corpo, dict):
        raise EntregaInvalidaError("corpo_nao_e_objecto")
    chaves = set(corpo)
    if chaves - set(CAMPOS_DA_ENTREGA):
        raise EntregaInvalidaError("campo_desconhecido")
    if set(CAMPOS_DA_ENTREGA) - chaves:
        raise EntregaInvalidaError("campo_em_falta")
    for campo in ("event_id", "tenant_id"):
        valor = corpo[campo]
        if not isinstance(valor, str) or not valor:
            raise EntregaInvalidaError(f"campo_invalido_{campo}")
    tentativas = corpo["tentativas"]
    if isinstance(tentativas, bool) or not isinstance(tentativas, int) or tentativas < 1:
        raise EntregaInvalidaError("campo_invalido_tentativas")
    return Entrega(
        event_id=corpo["event_id"],
        tenant_id=corpo["tenant_id"],
        envelope=corpo["envelope"],
        tentativas=tentativas,
    )


def exigir_ponteiros_uuid(entrega: Entrega) -> None:
    """Os dois ponteiros tem de ser UUIDs. Levanta `EntregaInvalidaError`.

    Nao e zelo: as colunas `event_id` e `tenant_id` da `events_dlq` e do
    `events_log` sao `uuid`, e um ponteiro que nao o seja nao abre DLQ nem le o
    arquivo — o `::uuid` rebentava dentro da transaccao, e a entrega repetia
    seis vezes o que se sabia a primeira. Recusa-se a entrada, com 400.

    **Na forma canonica** (minusculas, com hifenes), e nao so «um UUID»: e a
    unica que o `tenant_guard` aceita, e a que o envelope traz. Um ponteiro em
    maiusculas passava aqui e rebentava no `tx` — a mesma repeticao inutil.
    """
    for campo, valor in (("event_id", entrega.event_id), ("tenant_id", entrega.tenant_id)):
        try:
            canonico = str(uuid.UUID(valor))
        except ValueError:
            canonico = None
        if canonico != valor:
            raise EntregaInvalidaError(f"campo_invalido_{campo}")
