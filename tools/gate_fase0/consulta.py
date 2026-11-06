"""As consultas de leitura que dão os três elos que os *logs* não dão (KAM-108).

O `traco.py` explica porque é que a cadeia não cabe nos *logs*: a *allowlist* de
doze campos do `docs/logs.md` §2 não tem `order_id`, `event_id` nem
`booking_id`, e o §2.2 recusa o `contact_id` pelo nome. Os três elos de baixo da
cadeia leem-se da base.

## Três propriedades destas consultas, e as três são deliberadas

1. **Projectam só identificadores.** Nenhuma selecciona `envelope`, `nota`,
   `linhas`, `phone_enc`, `bsuid_enc` nem `payload_hash`. É isso que faz de «sem
   conteúdo nem telefone» uma consequência da **projecção**, e não uma promessa
   de quem escreveu o *script*: a coluna que levaria conteúdo não é pedida.
2. **São `SELECT`.** Não criam, não alteram e não apagam. Correm-se com o papel
   que lê — e com o contexto de *tenant* posto, senão a RLS devolve zero linhas
   (que é o comportamento certo e o primeiro sinal de que o contexto falta).
3. **Não vivem num ficheiro `.sql`.** O `ci/canon-lint.yaml` tem uma sentinela
   para `*.sql` em qualquer sítio: um `.sql` tem de ser superfície de DDL do
   *gate* 3b ou ser declarado fora de âmbito. Estas não são DDL — são leitura —, e
   declará-las fora de âmbito era pedir uma dispensa a um portão para um ficheiro
   que não é do género que ele verifica. Ficam como texto deste módulo, e o
   operador recebe-as por `python -m gate_fase0 consulta`.

## O `:tenant_id` e o `:desde`

São os dois parâmetros, e o segundo não é conveniência: sem janela, a consulta do
`events_log` devolve a história toda do *tenant* e a execução de hoje fica
misturada com as de ontem — o que faz uma cadeia parecer completa com elos de
execuções diferentes. A janela é a da demonstração.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Sequence


@dataclasses.dataclass(frozen=True)
class Consulta:
    """Uma consulta, com o elo que ela dá e as colunas que projecta.

    `elo` é `None` na consulta do **efeito** (a marcação), que vem depois da
    cadeia e não é um dos seus elos — ver o comentário do `MARCACAO`.
    """

    nome: str
    elo: str | None
    colunas: tuple[str, ...]
    sql: str
    fonte: str


#: O elo 2: o turno que criou o pedido.
#:
#: A ligação é o `audit_log(turn_id, entity, entity_id)` do dicionário §3 — é a
#: única superfície do conjunto que liga um turno de conversa a uma entidade de
#: comércio. Projecta-se `entity` para que o `traco.py` possa distinguir um
#: pedido de outra entidade, e **não** se projecta `payload_hash` nem `row_hash`:
#: são resumos, não identificadores da cadeia, e um resumo a mais no traço é um
#: valor a mais para alguém tentar inverter.
PEDIDO = Consulta(
    nome="pedido",
    elo="pedido",
    colunas=("tenant_id", "turn_id", "entity", "entity_id", "criado_at"),
    sql=(
        "SELECT tenant_id, turn_id, entity, entity_id, criado_at\n"
        "  FROM audit_log\n"
        " WHERE tenant_id = :tenant_id\n"
        "   AND criado_at >= :desde\n"
        "   AND entity IN ('order', 'encomenda')\n"
        " ORDER BY criado_at"
    ),
    fonte="dicionário §3, `audit_log(…, entity, entity_id, turn_id, …)`",
)

#: O elo 3: o evento de pagamento.
#:
#: `agregado_id` é o `order_id` — é assim que o envelope liga o evento à
#: encomenda —, e é por aí que o `traco.py` fecha o elo. Não se projecta
#: `envelope`: é onde vive o *payload*, e o *payload* de `payment.*` leva
#: `referencia` e `valor_minor`, que não são identificadores da cadeia.
EVENTO = Consulta(
    nome="evento",
    elo="evento de pagamento",
    colunas=("tenant_id", "event_id", "tipo", "versao", "agregado_tipo", "agregado_id", "ocorrido_em"),
    sql=(
        "SELECT tenant_id, event_id, tipo, versao, agregado_tipo, agregado_id,\n"
        "       ocorrido_em\n"
        "  FROM events_log\n"
        " WHERE tenant_id = :tenant_id\n"
        "   AND ocorrido_em >= :desde\n"
        "   AND tipo IN ('payment.manual_confirmed', 'payment.confirmed',\n"
        "                'payment.reference_issued')\n"
        " ORDER BY ocorrido_em"
    ),
    fonte="dicionário §3, `events_log(event_id, tipo, …, agregado_id, …)`",
)

#: O elo 4: o consumo, pela vertical que o critério nomeia.
#:
#: O `consumer` é a chave do `events_consumed` junto com o `event_id`, e é a
#: única prova de que **esta** vertical consumiu **este** evento. Uma contagem
#: de linhas não serve: o critério é «consumido pela vertical Serviços», e com
#: duas verticais subscritas uma contagem de dois não diz qual.
CONSUMO = Consulta(
    nome="consumo",
    elo="consumo por `agr_servicos`",
    colunas=("tenant_id", "consumer", "event_id", "agregado_tipo", "agregado_id", "processado_at"),
    sql=(
        "SELECT tenant_id, consumer, event_id, agregado_tipo, agregado_id,\n"
        "       processado_at\n"
        "  FROM events_consumed\n"
        " WHERE tenant_id = :tenant_id\n"
        "   AND processado_at >= :desde\n"
        " ORDER BY processado_at"
    ),
    fonte="dicionário §3, `events_consumed(consumer, event_id, …, processado_at)`",
)

#: O efeito que o critério pede a seguir ao consumo.
#:
#: Fica **separada** das três de cima de propósito: as três são a cadeia, e esta
#: é o efeito. A diferença aparece na checklist — uma cadeia completa com zero
#: marcações é um resultado diferente de uma cadeia que parou no consumo, e um
#: `UNION` das duas apagava a distinção.
MARCACAO = Consulta(
    nome="marcacao",
    elo=None,
    colunas=("tenant_id", "booking_id", "estado", "criado_at"),
    sql=(
        "SELECT tenant_id, booking_id, estado, criado_at\n"
        "  FROM bookings\n"
        " WHERE tenant_id = :tenant_id\n"
        "   AND criado_at >= :desde\n"
        " ORDER BY criado_at"
    ),
    fonte="dicionário §3, `bookings(booking_id, …, estado, …, criado_at)`",
)

CONSULTAS: Sequence[Consulta] = (PEDIDO, EVENTO, CONSUMO, MARCACAO)

#: As colunas que **nenhuma** consulta deste módulo pode projectar.
#:
#: É a lista das que levam conteúdo, telefone ou um resumo invertível, lida das
#: assinaturas do dicionário §3. O ensaio percorre as consultas e exige que
#: nenhuma delas apareça — que é o que torna a propriedade 1 verificável em vez
#: de afirmada.
PROIBIDAS: frozenset[str] = frozenset(
    {
        "envelope",
        "payload",
        "payload_hash",
        "row_hash",
        "prev_hash",
        "nota",
        "linhas",
        "texto",
        "phone_enc",
        "bsuid_enc",
        "bsuid_hmac",
        "contact_id",
        "referencia",
        "provider_event_id",
    }
)


class ProjeccaoProibida(AssertionError):
    """Uma consulta projecta uma coluna que leva conteúdo ou telefone."""


def verificar() -> None:
    """Nenhuma consulta projecta uma coluna proibida, nem no SQL nem nas colunas.

    Verificam-se **os dois** e não só a tupla `colunas`: a tupla é a declaração e
    o SQL é o que corre, e uma coluna acrescentada ao `SELECT` sem entrar na
    tupla é exactamente a divergência que uma declaração não apanha.
    """
    for consulta in CONSULTAS:
        for coluna in consulta.colunas:
            if coluna in PROIBIDAS:
                raise ProjeccaoProibida(
                    f"a consulta `{consulta.nome}` declara `{coluna}`, que leva "
                    "conteúdo, telefone ou um resumo invertível"
                )
        for proibida in sorted(PROIBIDAS):
            if _no_select(consulta.sql, proibida):
                raise ProjeccaoProibida(
                    f"o SQL da consulta `{consulta.nome}` selecciona `{proibida}`"
                )


def _no_select(sql: str, coluna: str) -> bool:
    """A coluna aparece na lista de projecção desta consulta?

    Lê-se só o trecho entre `SELECT` e `FROM`: uma coluna no `WHERE` é um filtro
    e não sai no resultado, e proibir filtros tirava a janela de `criado_at` e o
    `tipo IN (…)` que impedem a cadeia de misturar execuções.
    """
    inicio = sql.upper().find("SELECT")
    fim = sql.upper().find("FROM")
    if inicio < 0 or fim < 0:
        return False
    projeccao = sql[inicio + len("SELECT") : fim]
    return bool(re.search(rf"(?<![0-9a-z_]){re.escape(coluna)}(?![0-9a-z_])", projeccao))


def como_texto() -> str:
    """As consultas para o operador copiar, com o elo e a fonte de cada uma."""
    partes: list[str] = []
    for consulta in CONSULTAS:
        elo = consulta.elo or "(efeito, não é elo da cadeia)"
        partes.append(
            f"-- {consulta.nome}: {elo}\n"
            f"-- fonte: {consulta.fonte}\n"
            f"{consulta.sql};"
        )
    return "\n\n".join(partes)
