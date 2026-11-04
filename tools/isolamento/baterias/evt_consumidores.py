"""Os consumidores EVT — o que um consumidor de A ve do que e de B.

Criterio 2 do KAM-066 nomeia os «consumidores EVT» entre as quatro superficies
enumeradas, e a enumeracao encontra oito: um por `{tipo, versao}` de cada
vertical, com `consumer = "agr_" + id` (KAM-038, criterio 1). Cada um precisa
de caso, e este modulo escreve-o.

## Qual e a propriedade de isolamento de um consumidor

Um consumidor nao e uma rota: ninguem lhe faz um pedido com identificadores de
outro tenant. O que ele faz e **ler um envelope e escrever uma marca**, e o
`tenant_id` do contexto vem do envelope e nao da fila (`eventos/consumo.ts`: «o
valor vem do envelope e nao da fila: a fila trouxe um ponteiro, e quem diz de
quem e o evento e o arquivo»).

Logo a pergunta certa e: com o contexto de A, o que e que o caminho de consumo
ve das tres tabelas de A e de B?

```text
events_log       o arquivo de onde o envelope se le
events_consumed  a marca de exactamente-uma-vez, com chave (consumer, event_id)
events_dlq       a fila de mortos
```

As tres tem `tenant_id`, `ENABLE`, `FORCE` e a politica `tenant_iso`, e as tres
tem receita de semente — pelo que A e B tem, cada um, uma linha com o seu
canario em cada uma. O caso pergunta, **por consumidor**, se as linhas de B
aparecem com o contexto de A, e se a marca de B aparece quando se procura pela
chave `(consumer, event_id)` dele.

## O que este caso nao prova, e fica dito

Nao levanta Redis nem consome um *job* de verdade: a entrega e do KAM-038 e a
suite dele (`db/tests_eventos_consumo/`) mede-a. O que esta bateria mede e o
que o KAM-066 lhe pede — que nenhum canario de B atravesse pelo caminho do
consumidor — e mede-o na camada onde o canario existe.

**A chave de `events_consumed` nao tem `tenant_id`**, e e isso que torna este
caso necessario em vez de redundante com o X-03: a chave e
`(consumer, event_id)`, pelo que dois tenants que partilhem um `consumer` —
que e exactamente o caso, porque o `consumer` e por vertical — distinguem-se
**so** pela politica. Um `consumer` por vertical com a politica desligada
punha a marca de A a dizer «duplicado» a um evento de B.
"""

from __future__ import annotations

from ..casos import registar_caso

#: Os oito consumidores que a enumeracao encontra. Literais de proposito.
CONSUMIDORES = (
    "consumidor:agr_vendedor:payment.confirmed@1",
    "consumidor:agr_vendedor:payment.manual_confirmed@1",
    "consumidor:agr_vendedor:order.expired@1",
    "consumidor:agr_vendedor:stock.low@1",
    "consumidor:agr_servicos:booking.created@1",
    "consumidor:agr_servicos:booking.reminder_due@1",
    "consumidor:agr_servicos:payment.confirmed@1",
    "consumidor:agr_servicos:payment.manual_confirmed@1",
)

#: As tres tabelas do caminho de consumo.
TABELAS = (
    ("platform", "events_log"),
    ("platform", "events_consumed"),
    ("platform", "events_dlq"),
)


def _nomes_dos_consumidores() -> tuple[str, ...]:
    """Os `consumer` distintos dos itens enumerados: `agr_vendedor`, `agr_servicos`."""
    return tuple(
        sorted({item.split(":")[1] for item in CONSUMIDORES})
    )


def _consumidores(ctx) -> list[str]:  # noqa: ANN001
    if ctx.cursor_de is None:
        return [
            "EVT: o contexto nao traz cursores. Num gate, saltar e falhar."
        ]
    achados: list[str] = []

    for schema, tabela in TABELAS:
        cursor = ctx.cursor_de("app", ctx.a.id)
        cursor.execute(f"SELECT * FROM {schema}.{tabela}")
        linhas = [tuple(linha) for linha in cursor.fetchall()]
        if not linhas:
            achados.append(
                f"EVT {schema}.{tabela}: com o contexto de A a tabela esta "
                "vazia. A afirmacao de «nada de B» seria verde por ausencia."
            )
            continue
        achados.extend(
            f"EVT {schema}.{tabela}: {fuga}"
            for fuga in ctx.oraculo.varrer("corpo", linhas)
        )

    # A pergunta que so esta bateria faz: a marca de B, procurada pela chave
    # `(consumer, event_id)` **do consumidor**, com o contexto de A.
    for consumer in _nomes_dos_consumidores():
        cursor = ctx.cursor_de("app", ctx.a.id)
        cursor.execute(
            "SELECT count(*) FROM platform.events_consumed "
            "WHERE consumer = %s AND tenant_id = %s",
            (consumer, ctx.b.id),
        )
        quantas = cursor.fetchone()[0]
        if quantas:
            achados.append(
                f"EVT consumidor {consumer}: com o contexto de A veem-se "
                f"{quantas} marca(s) de B. A chave de `events_consumed` e "
                "`(consumer, event_id)` e o `consumer` e por **vertical**, "
                "partilhado pelos tenants: o que separa A de B nesta tabela e "
                "so a politica, e ela deixou de separar."
            )

        # A metade positiva: o mesmo `consumer`, o mesmo contexto, as linhas de
        # A. Sem ela, a contagem de zero acima passava com uma tabela a que o
        # papel nao chega.
        cursor.execute(
            "SELECT count(*) FROM platform.events_consumed WHERE tenant_id = %s",
            (ctx.a.id,),
        )
        if cursor.fetchone()[0] == 0:
            achados.append(
                f"EVT consumidor {consumer}: o contexto de A nao ve marca "
                "nenhuma de A. A contagem de zero para B nao prova isolamento."
            )
    return achados


registar_caso(
    id="EVT/consumidores",
    bateria="X-03",
    camada="rls",
    enumeravel=CONSUMIDORES,
    fn=_consumidores,
    precisa="postgres",
    origens=("corpo",),
)
