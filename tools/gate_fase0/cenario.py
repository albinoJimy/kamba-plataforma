"""O cenário *scriptado* do esqueleto andante, como dados (KAM-108).

O critério G0-1 descreve uma execução: «o cenário *scriptado* cria um pedido
(Vendedor), emite referência, recebe `payment.manual_confirmed` (ou
`payment.confirmed` no *sandbox*), passa a `paga` e a vertical Serviços cria o
lembrete/agenda». Este módulo é essa execução escrita como **dados** e não como
prosa, por duas razões.

**A primeira é que o guião e o traço têm de concordar.** Se os passos vivem num
Markdown e os elos que o `traco.py` procura vivem em código, a demonstração pode
correr os passos certos e o traço medir outra coisa — e ninguém repara, porque os
dois estão certos cada um por si. Aqui o guião do operador **gera-se** desta
tabela (`python -m gate_fase0 cenario`), e há ensaio a exigir que cada elo que o
`traco.py` nomeia tenha um passo que o produz.

**A segunda é o que o cenário não pode ter.** Um passo não leva texto de
mensagem, número de telefone nem nome: leva o **acto** («enviar a primeira
mensagem ao número de teste»), o **observável** por identificador, e o elo da
cadeia que ele produz. O conteúdo do que se escreve ao assistente é escolha do
operador no momento, e não um guião versionado — porque um guião versionado com
frases de conversa é conteúdo de conversa no repositório.

**Este módulo não corre nada.** A demonstração é humana, com a Meta real
(telemóvel -> número de teste ou de coexistência, nunca simulador), e o veredicto
também.
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

#: Os quatro elos da cadeia, pelos nomes com que o `traco.py` os nomeia em
#: `Cadeia.em_falta`. Em tupla e não em `set` porque a **ordem** é o que o
#: cenário prova: um consumo antes do evento não é a mesma demonstração.
ELOS = ("mensagem", "pedido", "evento de pagamento", "consumo por `agr_servicos`")


@dataclasses.dataclass(frozen=True)
class Passo:
    """Um passo do cenário.

    `observavel` diz o que o operador tem de **ver**, por identificador, e nunca
    «a resposta está correcta» — que é opinião e não observação. `elo` é o elo da
    cadeia que este passo produz, ou `None` para um passo de preparação.
    """

    id: str
    actor: str
    acto: str
    observavel: str
    elo: str | None
    fonte: str


#: O cenário, por ordem. Cada passo cita a fonte do que exige.
#:
#: **O passo P0 não é cerimónia.** O critério diz «ambiente com a Meta real
#: (telemóvel -> número de teste ou de coexistência, **nunca simulador**)», e a
#: diferença entre as duas demonstrações é precisamente o que esta linha fixa:
#: com o `tools/meta-sim` a cadeia fecha e não prova nada sobre o canal.
CENARIO: Sequence[Passo] = (
    Passo(
        id="P0",
        actor="operador",
        acto=(
            "confirmar que o número de destino é um número de teste ou de "
            "coexistência da Meta e que o simulador não está no caminho"
        ),
        observavel=(
            "o `KAMBA_META_MODO` do ambiente não é `simulador`; a mensagem sai de "
            "um telemóvel a sério e não de um `curl`"
        ),
        elo=None,
        fonte="EPIC-10, KAM-108, critério G0-1",
    ),
    Passo(
        id="P1",
        actor="operador",
        acto="enviar a primeira mensagem ao número, do telemóvel",
        observavel=(
            "uma linha de *log* com `tenant_id` e `turn_id`/`msg_id` na forma do "
            "`docs/logs.md` §2; nenhuma linha com texto"
        ),
        elo="mensagem",
        fonte="`docs/tecnica/00` §13.2: «uma conversa real»",
    ),
    Passo(
        id="P2",
        actor="operador",
        acto=(
            "percorrer o atendimento do Vendedor até criar um pedido, pelo "
            "caminho que o assistente oferecer"
        ),
        observavel=(
            "um `order_id` novo, ligado ao `turn_id` do P1 pelo "
            "`audit_log(turn_id, entity, entity_id)`"
        ),
        elo="pedido",
        fonte="EPIC-10, KAM-108, critério G0-1: «cria um pedido (Vendedor)»",
    ),
    Passo(
        id="P3",
        actor="sistema",
        acto="emitir a referência de pagamento do pedido",
        observavel="um `payment.reference_issued` com `agregado_id` igual ao `order_id`",
        elo=None,
        fonte="EPIC-10, KAM-108, critério G0-1: «emite referência»",
    ),
    Passo(
        id="P4",
        actor="dono (ou *sandbox* do facilitador)",
        acto=(
            "confirmar o pagamento — pelo `ManualProvider`, dentro do limite de "
            "valor, ou pelo *sandbox* se houver contrato"
        ),
        observavel=(
            "um `payment.manual_confirmed` (ou `payment.confirmed`) com "
            "`agregado_id` igual ao `order_id`, e `autenticacao.authn_ok` verdadeiro"
        ),
        elo="evento de pagamento",
        fonte="`docs/tecnica/00` §13.2; ADR-013",
    ),
    Passo(
        id="P5",
        actor="sistema",
        acto="transitar a encomenda para `paga`",
        observavel=(
            "o estado da encomenda é `paga`, e a transição veio do evento — "
            "nenhum caminho aplicacional a marca (ADR-013)"
        ),
        elo=None,
        fonte="EPIC-10, KAM-108, critério G0-1: «passa a `paga`»",
    ),
    Passo(
        id="P6",
        actor="sistema",
        acto="a vertical Serviços consome o evento de pagamento",
        observavel=(
            "uma linha de `events_consumed` com `consumer = 'agr_servicos'` e o "
            "`event_id` do P4"
        ),
        elo="consumo por `agr_servicos`",
        fonte="`docs/tecnica/00` §13.2: «esse evento é consumido pela vertical Serviços»",
    ),
    Passo(
        id="P7",
        actor="sistema",
        acto="a vertical Serviços cria o lembrete ou a marcação",
        observavel="um `booking_id` novo, ou um `booking.reminder_due` agendado",
        elo=None,
        fonte="EPIC-10, KAM-108, critério G0-1: «cria o lembrete/agenda»",
    ),
)


class CenarioIncoerente(AssertionError):
    """O cenário não produz um elo que o traço procura.

    É erro de programação e não de dados: significa que alguém mexeu num dos dois
    lados sem mexer no outro, que é precisamente o que este módulo existe para
    impedir.
    """


def elos_produzidos() -> tuple[str, ...]:
    """Os elos que o cenário produz, pela ordem dos passos."""
    return tuple(passo.elo for passo in CENARIO if passo.elo is not None)


def verificar() -> None:
    """Cada elo da cadeia tem um passo que o produz, e pela ordem certa."""
    produzidos = elos_produzidos()
    if produzidos != ELOS:
        raise CenarioIncoerente(
            f"o cenário produz {produzidos} e o traço procura {ELOS}"
        )
    vistos = [passo.id for passo in CENARIO]
    if len(set(vistos)) != len(vistos):
        raise CenarioIncoerente(f"ids repetidos no cenário: {vistos}")


def como_markdown() -> str:
    """O guião do operador, gerado do cenário.

    Gera-se em vez de se escrever à mão pela razão do docstring do módulo: duas
    cópias divergem, e a que o operador lê é a que não tem ensaio.
    """
    linhas = [
        "| # | Quem | Acto | O que tem de se observar | Elo | Fonte |",
        "|---|---|---|---|---|---|",
    ]
    for passo in CENARIO:
        elo = f"**{passo.elo}**" if passo.elo else "—"
        linhas.append(
            f"| {passo.id} | {passo.actor} | {passo.acto} | {passo.observavel} "
            f"| {elo} | {passo.fonte} |"
        )
    return "\n".join(linhas)
