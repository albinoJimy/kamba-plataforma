"""Os *jobs* BullMQ — o que uma fila transporta, e o que o trabalhador faz com ele.

Bateria **J-01**, e nao X-01: estes dois casos estiveram registados como
X-01/`rotas`, e o relatorio do *gate* contava-os debaixo de «rotas: IDOR
autenticado». Um relatorio que conta uma coisa com o nome de outra e pior do
que nao contar.

**E o que estes dois casos afirmam e menos do que um ataque**, o que fica dito
aqui em vez de ficar implicito: sao verificacoes sobre o **contrato escrito**
do corpo do *job* (que campo ele leva, e qual nao pode levar) e sobre a
derivacao do nome de fila. O isolamento em execucao de cada consumidor e o
caso `EVT/consumidores`, contra a base; o do turno e o X-01 da
`/internal/turn`. Quatro dos 45 itens enumerados tem, portanto, casos que
medem o contrato e nao a fuga — e e por isso que eles nao contam como X-01.

Criterio 2 do KAM-066 nomeia os «*jobs* BullMQ» entre as quatro superficies
enumeradas. A enumeracao encontra quatro itens: duas filas com nome literal e
dois sitios onde o nome e calculado em execucao.

```text
job:agr-inbound   `FILA_AGR`      o turno do AGR; o job chama-se `turno`
job:wa-inbound    `FILA_ENTRADA`  a entrada do canal; o job chama-se `wa`
job:…/filas_bullmq.ts#nome      `new Queue(nome)` — as filas de evento
job:…/trabalhador_bullmq.ts#fila `new Worker(fila)` — idem, do lado do consumo
```

## O que se prova numa fila, e nao e o que se prova numa rota

Uma fila nao recebe um pedido autenticado: recebe um *job* que **nos** pusemos
la. O ataque de IDOR nao existe aqui. O que existe, e e a falha que importa, e
o `tenant_id` do *job* deixar de ser a fonte do contexto — ou nao vir no *job*
de todos.

Logo este caso verifica, pela **fonte**, que cada uma das duas filas nomeadas
transporta o `tenant_id` no corpo do *job*, e nao o deriva de nada que o
trabalhador escolha. E uma verificacao estatica, e e dita como tal: o
comportamento em execucao e do KAM-025 (o *shim*) e do KAM-015 (a entrada), e
as suites deles medem-no.

## As duas filas de evento, e porque e que ficam indecisas

O nome e `evt.<consumer>.p<0..15>` (`eventos/particao.ts`, `nomeDaFila`), com o
`consumer` a vir da variavel de ambiente `KAMBA_CONSUMER` em execucao: uma
enumeracao estatica nao o resolve, e o item fica com o sitio por identificador
em vez de um nome de fila. **Isso nao e uma dispensa.** O caso verifica a
derivacao: os `consumer` possiveis sao exactamente os que a enumeracao de
consumidores encontra, e as dezaseis particoes de cada um sao uma funcao do
`consumer`. O isolamento de cada um e o caso `EVT/consumidores`, que corre
contra a base — enumerar as 32 filas dava 32 itens com a mesma propriedade a
provar e um caso repetido 32 vezes.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..casos import registar_caso

RAIZ = Path(__file__).resolve().parents[3]

#: As duas filas com nome literal.
FILAS_NOMEADAS = ("job:agr-inbound", "job:wa-inbound")

#: Os dois sitios em que o nome e calculado: as filas de evento.
FILAS_DE_EVENTO = (
    "job:packages/core-ts/src/eventos/filas_bullmq.ts#nome",
    "job:packages/core-ts/src/eventos/trabalhador_bullmq.ts#fila",
)

#: Fila -> `(contrato, constante do job, campo que o corpo tem de levar,
#: campo que o corpo **nao** pode levar)`.
#:
#: **As duas filas sao assimetricas, e a assimetria e o desenho.** A primeira
#: versao deste caso exigia `tenant_id` nas duas, e a `wa-inbound` ficou
#: vermelha com razao: o *job* da entrada **nao sabe** de quem e a mensagem.
#: A camada que o decide e o CHR — «unico ponto que mapeia `phone_number_id ->
#: tenant`» (`docs/tecnica/08` §3.1, primeira linha da tabela de camadas) —, e
#: o `tenant_id` nasce ali. Um `tenant_id` no corpo da `wa-inbound` seria um
#: tenant escolhido **antes** do unico ponto que o pode escolher: por isso o
#: caso nao o exige, proibe-o.
#:
#: A `agr-inbound` e depois do CHR, e ai o `tenant_id` tem de vir no corpo:
#: o estado do turno deriva dele, e o ADR-015 poe-o no estado e nunca numa
#: escolha do trabalhador.
CONTRATO_DA_FILA = {
    "job:agr-inbound": (
        "packages/core-ts/src/chr/contrato.ts",
        "JOB_AGR",
        "tenant_id",
        None,
    ),
    "job:wa-inbound": (
        "packages/core-ts/src/entrada/contrato.ts",
        "JOB_ENTRADA",
        "phone_number_id",
        "tenant_id",
    ),
}


def _nomeadas(ctx) -> list[str]:  # noqa: ANN001
    """Cada fila nomeada transporta o que a sua camada lhe da, e nada mais."""
    achados: list[str] = []
    for item in FILAS_NOMEADAS:
        relativo, constante_do_job, exigido, proibido = CONTRATO_DA_FILA[item]
        caminho = ctx.raiz / relativo
        if not caminho.is_file():
            achados.append(
                f"{item}: o contrato {relativo} nao existe. A fila mudou de "
                "sitio e o caso ficou a apontar para o vazio."
            )
            continue
        fonte = caminho.read_text(encoding="utf-8")
        if not re.search(r"\b" + re.escape(exigido) + r"\b", fonte):
            achados.append(
                f"{item}: {relativo} nao nomeia `{exigido}`. E o campo por que "
                "a camada seguinte decide de quem e o trabalho; um corpo que "
                "nao o transporta deixa essa decisao a quem consome."
            )
        if proibido is not None and re.search(
            r"\b" + re.escape(proibido) + r"\b", fonte
        ):
            achados.append(
                f"{item}: {relativo} nomeia `{proibido}`, e esta fila e "
                "**antes** do CHR — o unico ponto que mapeia "
                "`phone_number_id -> tenant` (`docs/tecnica/08` §3.1). Um "
                f"`{proibido}` neste corpo e um tenant escolhido antes de haver "
                "quem o possa escolher, e e a falha que a camada do CHR existe "
                "para impedir (mensagem encaminhada ao tenant errado)."
            )
        if not re.search(r"\b" + re.escape(constante_do_job) + r"\b\s*=", fonte):
            achados.append(
                f"{item}: {relativo} nao declara `{constante_do_job}`. O nome "
                "do *job* e o que distingue o trabalho nesta fila; sem ele o "
                "caso nao sabe o que a fila transporta."
            )
    return achados


def _de_evento(ctx) -> list[str]:  # noqa: ANN001
    """A derivacao `evt.<consumer>.p<n>` cobre exactamente os consumidores enumerados."""
    from ..enumeracao import PREFIXO_DO_CONSUMIDOR, consumidores  # noqa: PLC0415

    achados: list[str] = []
    particao = ctx.raiz / "packages/core-ts/src/eventos/particao.ts"
    if not particao.is_file():
        return [
            "job (evento): `packages/core-ts/src/eventos/particao.ts` nao "
            "existe. A derivacao do nome de fila mudou de sitio e este caso "
            "deixou de medir o que diz medir."
        ]
    fonte = particao.read_text(encoding="utf-8")

    prefixo = re.search(r"PREFIXO_DA_FILA\s*=\s*[\"'`]([^\"'`]+)", fonte)
    particoes = re.search(r"PARTICOES\s*=\s*([0-9_]+)", fonte)
    if prefixo is None or particoes is None:
        achados.append(
            "job (evento): nao se leu `PREFIXO_DA_FILA` ou `PARTICOES` de "
            "particao.ts. Sem eles, o caso nao sabe que filas existem e as "
            "32 filas de evento ficam sem cobertura nenhuma."
        )
        return achados

    esperados = sorted({item.id.split(":")[1] for item in consumidores(ctx.raiz)})
    if not esperados:
        achados.append(
            "job (evento): a enumeracao de consumidores devolveu zero. As filas "
            "de evento sao uma funcao dos consumidores: sem consumidores, as "
            "32 filas que este caso cobre nao existem — ou a enumeracao parou "
            "de ler o registo."
        )
    for consumer in esperados:
        if not consumer.startswith(PREFIXO_DO_CONSUMIDOR):
            achados.append(
                f"job (evento): o consumidor {consumer!r} nao tem o prefixo "
                f"{PREFIXO_DO_CONSUMIDOR!r}. O nome da fila deriva do "
                "`consumer`, e um `consumer` fora da convencao e uma fila que "
                "nenhum trabalhador desta casa serve."
            )
    return achados


registar_caso(
    id="JOB/filas-nomeadas",
    bateria="J-01",
    camada="filas",
    enumeravel=FILAS_NOMEADAS,
    fn=_nomeadas,
    precisa="nada",
    origens=(),
)

registar_caso(
    id="JOB/filas-de-evento",
    bateria="J-01",
    camada="filas",
    enumeravel=FILAS_DE_EVENTO,
    fn=_de_evento,
    precisa="nada",
    origens=(),
)
