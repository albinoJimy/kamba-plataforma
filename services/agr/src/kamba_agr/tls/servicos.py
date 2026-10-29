"""Os argumentos das cinco tools de Servicos (§6.2), e so os argumentos.

## Porque e que os modelos estao aqui e os executores nao

A razao e a do `tls/vendedor.py`, palavra por palavra: o que falta para uma
entrada do catalogo passar de `declarada` a `ligada` sao duas coisas — o
**modelo** dos argumentos, que e contrato e nasce do canon, e o **executor**, que
fala com o COM. Entregar as cinco `ligadas` com executores de ensaio punha o
`catalogo_do_piloto()` a servir horas inventadas a quem o chamasse em producao, e
o `invoke` nao tem como distinguir um executor de ensaio de um real: dava um
`ToolResult` `ok` com *facts* `datetime` que nenhuma agenda tem, e o validador de
citacao **aceita-os** — sao *facts* de uma tool. Seria confirmar a um cliente uma
marcacao que nao existe.

Por isso: os modelos aqui, as cinco entradas continuam `declaradas` no
`catalogo.py`, e os executores de ensaio vivem em `verticais/servicos/fakes.py`,
de onde nenhum arranque os importa.

## O credor destas cinco entradas, e porque e que ele nao se consegue corrigir

O `catalogo.py` poe `CREDOR_DE_SERVICOS = "KAM-035"`, e a regra da casa e que o
credor de uma entrada `declarada` e «o ticket que a **liga**». O KAM-031 corrigiu
o dele de `KAM-031` para os tickets que ligam cada backend (KAM-043, KAM-044,
KAM-046, KAM-061).

**Para Servicos nao ha ticket equivalente, e mediu-se:** o modulo que faz a
agenda existir e o **KAM-047**, que fundiu — pelo que apontar para ele era um
ponteiro morto. E o que falta nao e o modulo: e o caminho entre o AGR (Python) e
o modulo `servicos` (TypeScript, no COM). Nenhuma linha do §4 do
`specs/INDICE.md` o nomeia; o KAM-048 e lembretes e o KAM-046 e o analogo do
Vendedor, para encomendas.

O credor fica, portanto, **a apontar para este ticket**, e isso **nao** e
conformidade: e a declaracao de que falta um ticket. Esta escrito na seccao de
verificacao do bloco e na hipotese devolvida ao fundador — abrir o ticket e
alterar o backlog mestre, que e L1 e nao cabe neste PR.

## O `slot_id` e o `hold_id` nao levam padrao, e isso e decisao

Os dois sao **opacos** (KAM-047: o `VALIDATION_ERROR` do modulo e «o `slot_id`
nao foi emitido por este backend»), e um padrao adivinhado aqui recusava um
identificador real no dia em que ele chegasse. Quem valida a **proveniencia** e o
backend, que e quem os emitiu. O que se verifica aqui e o comprimento, que e o
que impede um argumento absurdo de atravessar a rede.

## O `book_slot` recebe `hold_id` e o §6.2 escreve `slot_id`

O §6.2 escreve `book_slot(slot_id, serviço)` e o §8.2 escreve «botao
`confirm:{hold_id}`; `book_slot` mantem *hold* curto e e idempotente por
`(contact, slot_id)`». Lidas juntas, as duas linhas pedem que a **mesma** tool
crie o *hold* e o confirme — e nao pode: o passo 4 do `invoke` exige que uma tool
de classe `write` traga o botao de confirmacao, e no momento de criar o *hold*
ainda nao existe `hold_id` nenhum para o botao citar.

**Isto e uma lacuna de desenho que nenhum dos dois tickets resolve**, e vai como
hipotese ao fundador em vez de se decidir aqui em silencio. O que este ticket
implementa, declarado como ***proposta***, e a leitura que o canon ja suporta sem
tool nova:

* o `get_availability` (classe `read`) devolve as opcoes e, **quando o pedido
  estreita a um unico intervalo**, devolve essa opcao ja com `hold_id` e
  `expira_at` — o *hold* curto do §8.2, tomado pelo backend que ja tem o
  `holdSlot` (KAM-047);
* o `book_slot` (classe `write`, botao `confirm:{hold_id}`) **confirma** esse
  *hold*, e e o `confirmBooking` do modulo.

A alternativa — uma setima tool `hold_slot` — acrescenta um **nome** ao catalogo
do §6.2 e ao dicionario §3.26, que e canon desde a emenda 1.35. Escolher entre as
duas e decisao do fundador, e ambas estao escritas na hipotese.

shortcut: o `get_availability` (classe `read`) devolve `hold_id` quando o pedido
estreita a um intervalo, o que faz uma tool de leitura ter efeito de escrita;
revê-se quando o fundador escolher entre isto e uma setima tool `hold_slot` (a
hipotese esta na `ANALISE-40`)
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from .especificacoes import EspecificacaoDeTool, Executor

#: O comprimento maximo de um identificador opaco do modulo `servicos`. Tem
#: **um dono so**, e e esta constante: os quatro modelos abaixo leem-na daqui.
LIMITE_DE_ID: Final = 64

#: O credor que falta. **Nao e um `KAM-NNN`**, e e de proposito: o `CREDOR` do
#: `especificacoes.py` exige a forma `KAM-\\d{3}`, pelo que esta constante nao
#: entra num campo `credor` — existe para que a lacuna tenha um nome no codigo e
#: nao so em prosa. Ver a nota do modulo.
CREDOR_EM_FALTA: Final = (
    "falta o ticket que liga o AGR ao modulo `servicos` do COM (ver tls/servicos.py)"
)


class ArgumentosDeListServices(BaseModel):
    """`list_services()` — §6.2, sem argumentos.

    **Sem campos e com `extra="forbid"`**: o `__post_init__` do
    `EspecificacaoDeTool` recusa um modelo sem ele, e aqui ele e o que faz um
    argumento inventado pelo modelo dar `VALIDATION_ERROR` no passo 3 em vez de
    ser ignorado em silencio.
    """

    model_config = ConfigDict(extra="forbid")


class ArgumentosDeGetAvailability(BaseModel):
    """`get_availability(serviço, intervalo)` — devolve *facts* `datetime`.

    O `intervalo` do §6.2 entra como **dois campos anulaveis** e nao como um
    objecto: o `getAvailability` do modulo recebe `{deAt?, ateAt?}` com os dois
    opcionais, e um objecto obrigatorio com campos opcionais dentro obrigava o
    modelo a produzir `{}` para dizer «sem intervalo» — que e um argumento a
    mais a dizer nada.

    **Os dois sao instantes UTC em ISO-8601**, e a validacao e de forma e nao de
    semantica: `de_at` depois de `ate_at` e um intervalo vazio e o backend
    devolve zero opcoes, que e a resposta certa. Recusa-lo aqui obrigava este
    modulo a saber o que e um intervalo valido para uma agenda.
    """

    model_config = ConfigDict(extra="forbid")

    service_id: str = Field(min_length=1, max_length=LIMITE_DE_ID)
    de_at: str | None = Field(default=None, min_length=1, max_length=40)
    ate_at: str | None = Field(default=None, min_length=1, max_length=40)


class ArgumentosDeBookSlot(BaseModel):
    """`book_slot(hold_id)` — classe `write`, botao `confirm:{hold_id}`.

    **`hold_id` e nao `slot_id`**, pela normalizacao que os *Detalhes Tecnicos*
    do bloco mandam e pela leitura que a nota do modulo escreve: esta tool
    confirma um *hold* que o `get_availability` tomou, e o campo que o botao cita
    tem de ser o campo que a tool recebe — senao o passo 4 do `invoke` compara
    duas coisas diferentes e a verificacao da confirmacao fica decorativa.
    """

    model_config = ConfigDict(extra="forbid")

    hold_id: str = Field(min_length=1, max_length=LIMITE_DE_ID)


class ArgumentosDeCancelBooking(BaseModel):
    """`cancel_booking(id)` — ambito tenant **e** contacto (§6.2)."""

    model_config = ConfigDict(extra="forbid")

    booking_id: str = Field(min_length=1, max_length=LIMITE_DE_ID)


class ArgumentosDeRescheduleBooking(BaseModel):
    """`reschedule_booking(id, novo_slot)` — atomica (cancela e marca).

    A atomicidade e do modulo `servicos` (KAM-047, `rescheduleBooking`), e nao
    de dois argumentos: o que este modelo garante e que a operacao se pede
    **numa** chamada. Dois argumentos em duas tools eram duas transacoes, e uma
    falha a meio deixava o cliente sem nenhuma das duas marcacoes — que e o que
    o criterio 7 proibe pelo nome.
    """

    model_config = ConfigDict(extra="forbid")

    booking_id: str = Field(min_length=1, max_length=LIMITE_DE_ID)
    slot_id: str = Field(min_length=1, max_length=LIMITE_DE_ID)


#: O modelo de cada tool de Servicos, pelo nome canonico. **Cinco e nao seis**:
#: o `get_store_info` e das duas verticais (§6.2, «ambas») e e a unica `ligada`
#: do catalogo — o modelo e o executor dele estao em `tls/get_store_info.py`.
MODELOS: Final = {
    "list_services": ArgumentosDeListServices,
    "get_availability": ArgumentosDeGetAvailability,
    "book_slot": ArgumentosDeBookSlot,
    "cancel_booking": ArgumentosDeCancelBooking,
    "reschedule_booking": ArgumentosDeRescheduleBooking,
}

#: O backend de cada uma (§6.2), que e a unidade do disjuntor (§6.5). As cinco
#: falam com o COM, onde vive o modulo `servicos`.
BACKENDS: Final = {nome: "com" for nome in MODELOS}

#: A classe de cada uma. **Nenhuma e `money`**: um sinal de marcacao usa o PAY
#: «como no Vendedor» (§8.2), e quem cobra e o `criar_pedido` — nao estas. As
#: tres de escrita exigem botao de confirmacao (§6.1 passo 4).
CLASSES: Final = {
    "list_services": "read",
    "get_availability": "read",
    "book_slot": "write",
    "cancel_booking": "write",
    "reschedule_booking": "write",
}

#: O campo que o botao de confirmacao cita, por tool. `None` nas de leitura.
#:
#: **O `cancel_booking` e o `reschedule_booking` citam o `booking_id`** e nao um
#: `hold_id`: nao ha *hold* numa marcacao que ja existe, e o §6.2 escreve «botao»
#: para as duas sem dizer qual. O que o passo 4 exige e que o botao cite o
#: **argumento** que identifica o que se altera, e nas duas ele e o `booking_id`.
CAMPO_DE_CONFIRMACAO: Final = {
    "list_services": None,
    "get_availability": None,
    "book_slot": "hold_id",
    "cancel_booking": "booking_id",
    "reschedule_booking": "booking_id",
}


def especificacoes_de_servicos(
    executores: dict[str, Executor],
) -> tuple[EspecificacaoDeTool, ...]:
    """As cinco `ligadas`, com os executores que quem chama fornecer.

    Levanta se faltar um executor: uma especificacao com modelo e sem executor
    nao e construivel (o invariante do `EspecificacaoDeTool`), e um catalogo meio
    ligado era pior do que nenhum — a tool aparecia ao modelo e recusava.
    """
    faltam = sorted(set(MODELOS) - set(executores))
    if faltam:
        raise KeyError(f"sem executor para {faltam}")
    return tuple(
        EspecificacaoDeTool(
            nome=nome,
            klass=CLASSES[nome],
            backend=BACKENDS[nome],
            modelo=modelo,
            executor=executores[nome],
            campo_de_confirmacao=CAMPO_DE_CONFIRMACAO[nome],
        )
        for nome, modelo in MODELOS.items()
    )
