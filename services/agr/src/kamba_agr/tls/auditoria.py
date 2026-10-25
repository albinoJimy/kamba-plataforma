"""A linha de `tool_audit`: o passo 7 do `docs/tecnica/02` §6.1.

«Linha em `tool_audit`» por **cada** invocacao, de qualquer classe. O critero 5
do bloco mede-o para `write` e `money` («1 linha, cobertura 100%»), e a tabela
cobre tambem as leituras — e a diferenca entre ela e a `audit_log` do KAM-012
(§6.4).

## O que nao vai na linha, e porque isso se prova por varrimento

Nem texto de mensagem, nem telefone, nem valores de argumento. O que vai e:

* `args_hash`   — `sha256` da forma canonica dos argumentos, 32 octetos;
* `args_redacted` — a **forma**: `{"<argumento>": "<tipo>"}`, nunca o valor;
* `fact_ids`    — os identificadores dos *facts*, nunca os valores.

**Isto nao se prova a ler o DDL.** O KAM-026 escreveu um varrimento de
privacidade que dava zero porque procurava texto num campo `msgpack`, e o
critero passava pela razao errada. Aqui o varrimento corre contra os dados, com
canarios no `query` de uma chamada, e e `db/tests_agr/test_tool_audit.py`.

## A forma canonica e ordenada, e sem isso o hash nao serve

`sha256` de `{"a": 1, "b": 2}` e de `{"b": 2, "a": 1}` tem de ser o mesmo, senao
«foi a mesma chamada» depende da ordem em que o Pydantic serializou o modelo. O
`json.dumps` vai com `sort_keys=True` e separadores sem espaco; os valores que o
JSON nao sabe escrever (um `Decimal`, uma data) passam por `default=str`, que e
determinista para os tipos que um argumento de tool pode ter.

## O `ts` e o `id` nao sao de quem escreve

O `INSERT` da revisao `0021` e **por coluna** e nao inclui nenhum dos dois: o
instante de uma linha de auditoria nao e do chamador, e o `id` e de identidade.
E o mesmo desenho da `audit_log`, e e por isso que esta funcao nao os menciona.

## Falhar a escrever e falhar a invocacao

A ordem do §6.1 poe o registo **depois** da chamada ao backend (passo 7, depois
do 6), pelo que uma escrita que falhe deixa um efeito sem registo. A camada faz
duas coisas por isso, e nenhuma delas e esconder:

1. o arranque confirma que esta escrita funciona, e recusa arrancar se nao
   (codigo de saida **6**, dicionario §3.27). Isso retira a causa de longe mais
   provavel, que e configuracao;
2. em execucao, uma falha de registo **nao se engole**: levanta
   `AuditoriaIndisponivelError`, o turno falha e o *job* volta a fila. Para uma
   tool `read` isso custa uma repeticao; para uma `write` ou `money` o efeito
   ficou feito e o registo nao — e e precisamente por isso que levanta em vez de
   devolver `ok`, para que o alerta exista.

O que fecha a janela por inteiro e a idempotencia do KAM-029: com a chave, a
repeticao do turno reencontra o resultado em vez de repetir o efeito. Esta
camada entrega o ponto de extensao e a regra de que `write`/`money` nunca correm
sem chave; o resto e desse ticket.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final

from kamba_core import tenant_guard

from .contexto import ToolContext
from .erros import ErroDeTool, Fact

#: Os dois desfechos de uma invocacao, no registo (`CHECK tool_audit_status`).
STATUS_OK: Final = "ok"
STATUS_ERRO: Final = "erro"

#: As dezoito colunas que quem invoca escreve, pela ordem do `INSERT`. E a mesma
#: lista do `GRANT` da revisao `0021` e do `COLUNAS_POR_PAPEL` do
#: `test_privilegios`; se divergirem, o `INSERT` rebenta por privilegio e nao em
#: silencio.
COLUNAS: Final = (
    "tenant_id",
    "contact_id",
    "conversation_id",
    "turn_id",
    "run_id",
    "vertical",
    "graph_version",
    "tool",
    "tool_version",
    "klass",
    "args_hash",
    "args_redacted",
    "idempotency_key",
    "status",
    "error_code",
    "result_hash",
    "fact_ids",
    "latency_ms",
)

SQL_ESCREVER = (
    "INSERT INTO platform.tool_audit (" + ", ".join(COLUNAS) + ") VALUES ("
    + ", ".join(["%s"] * len(COLUNAS))
    + ")"
)


class FactIdDerivadoError(ValueError):
    """Um `fact_id` cunhado a partir de um argumento.

    Levanta e nao e um dos dez erros do §6.5: nenhum deles descreve isto, e nao
    e uma resposta de negocio — e a tool a cunhar mal um identificador, que e
    defeito de quem a escreveu.
    """


class AuditoriaIndisponivelError(RuntimeError):
    """Nao se conseguiu escrever a linha de `tool_audit`.

    Nao e um dos dez erros do §6.5 de proposito: nenhum deles descreve «a
    invocacao correu e nao se conseguiu registar», e devolver `UPSTREAM_DOWN`
    fazia o grafo tratar isso como um backend em baixo — que o §6.5 manda
    repetir uma vez. Repetir uma escrita cujo efeito ja aconteceu e o contrario
    do que se quer.
    """


def impressao(valor: Any) -> bytes:
    """`sha256` da forma canonica. 32 octetos, que e o que o `CHECK` exige."""
    texto = json.dumps(
        valor, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(texto.encode("utf-8")).digest()


#: A chave que agrega os argumentos que o esquema nao declara.
NAO_DECLARADOS: Final = "<nao_declarados>"


def redigir(args: dict[str, Any], declarados: Collection[str] = ()) -> dict[str, Any]:
    """A **forma** dos argumentos: nome -> nome do tipo. Nunca o valor, **nem o nome**.

    O tipo e o nome da classe Python e nao o valor convertido em texto: um
    `{"query": "str"}` nao diz o que o cliente escreveu, e um
    `{"query": "sapatos"}` diria.

    **E os nomes tambem sao do modelo, e nao de quem chamou.** As chaves de
    `args` vem do modelo de linguagem, e um nome e texto tanto como um valor:
    `{"contacto 999123456789": "x"}` punha um telefone na `tool_audit` pela
    coluna que o critero 5 fecha para os valores. A primeira versao desta funcao
    escrevia-os em claro — incluindo no caminho `VALIDATION_ERROR`, que e
    precisamente onde um argumento inventado chega. Apanhado pela revisao
    adversarial.

    Por isso so passam os nomes que o esquema **declara**; o resto conta-se:
    `{"<nao_declarados>": 2}`. A contagem e informacao util — houve argumentos a
    mais, e quantos — e nao e um canal: nao leva nada de quem a provocou.

    Sem `declarados`, **nenhum** nome passa. Falha fechada: a alternativa era
    confiar num nome por nao se saber de onde veio.
    """
    permitidos = frozenset(declarados)
    redigido: dict[str, Any] = {}
    fora = 0
    for nome, valor in sorted(args.items()):
        if nome in permitidos:
            redigido[nome] = type(valor).__name__
        else:
            fora += 1
    if fora:
        redigido[NAO_DECLARADOS] = fora
    return redigido


@dataclass(frozen=True, slots=True)
class LinhaDeAuditoria:
    """Uma linha de `tool_audit`, montada e ainda nao escrita."""

    ctx: ToolContext
    tool: str
    tool_version: str
    klass: str
    args: dict[str, Any]
    status: str
    latency_ms: int
    error: ErroDeTool | None = None
    data: dict[str, Any] | None = None
    facts: tuple[Fact, ...] = ()
    idempotency_key: str | None = None
    #: Os campos que o esquema da tool declara. Vazio significa «nao se sabe», e
    #: nesse caso **nenhum** nome de argumento entra na linha.
    campos_declarados: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Um `fact_id` que leve um argumento dentro **nao** se escreve.

        «Um `fact_id` e opaco» era uma regra escrita para o KAM-031 e o KAM-032,
        e uma regra escrita nao e imposta por ninguem: a revisao adversarial
        notou-o. Esta e a parte que a camada **pode** impor sem saber nada sobre
        os *facts* de cada tool — se um `fact_id` contem um valor de argumento,
        ele deriva de texto do cliente, e a coluna `fact_ids` passava a levar o
        que o critero 5 fecha para as outras.

        Foi exactamente o defeito que o varrimento com canarios apanhou no
        executor de ensaio (`fact_id=f"f-{cart_id}"`), e levanta em vez de
        redigir: um `fact_id` que se redigisse deixava de resolver a citacao que
        ele existe para resolver. E defeito de quem cunha o *fact*.
        """
        valores = {
            str(valor) for valor in self.args.values() if isinstance(valor, str) and valor
        }
        for facto in self.facts:
            for valor in valores:
                if valor in facto.fact_id:
                    raise FactIdDerivadoError(
                        f"o `fact_id` {facto.fact_id!r} de `{self.tool}` contem o valor "
                        "de um argumento: um `fact_id` e opaco, senao a coluna "
                        "`fact_ids` leva texto do cliente (critero 5, ADR-007)"
                    )

    def parametros(self) -> tuple[Any, ...]:
        """Os dezoito valores, pela ordem de `COLUNAS`."""
        return (
            self.ctx.tenant_id,
            self.ctx.contact_id,
            self.ctx.conversation_id,
            self.ctx.turn_id,
            self.ctx.run_id,
            self.ctx.vertical,
            self.ctx.graph_version,
            self.tool,
            self.tool_version,
            self.klass,
            impressao(self.args),
            json.dumps(
                redigir(self.args, self.campos_declarados),
                sort_keys=True,
                ensure_ascii=False,
            ),
            self.idempotency_key,
            self.status,
            self.error.codigo if self.error is not None else None,
            # O `CHECK tool_audit_resultado_so_em_ok` recusa um `result_hash`
            # numa linha de erro, e e por isso que isto olha para o `status` e
            # nao so para o `data`: uma invocacao que falhou e devolveu dados
            # parciais nao tem resultado.
            impressao(self.data) if self.status == STATUS_OK and self.data is not None
            else None,
            [facto.fact_id for facto in self.facts] if self.facts else None,
            self.latency_ms,
        )


#: A guarda de arranque: o papel desta ligacao consegue escrever a linha?
#:
#: Pergunta-se **por coluna** e nao por tabela, porque o `GRANT` da revisao
#: `0021` e por coluna: um `has_table_privilege(..., 'INSERT')` devolve falso
#: com privilegios de coluna concedidos, e um que devolvesse verdadeiro nao
#: dizia **quais** colunas. Uma coluna em falta e um `INSERT` que rebenta no
#: passo 7, depois de o efeito de uma tool `money` ter acontecido.
SQL_CONFIRMAR = (
    "SELECT "
    + ", ".join(
        f"has_column_privilege('platform.tool_audit', '{coluna}', 'INSERT')"
        for coluna in COLUNAS
    )
)


def confirmar(ligacao: Any) -> None:
    """Confirma que esta ligacao escreve `tool_audit`. Levanta se nao.

    Corre no arranque, e **nao escreve nada**: a tabela e *append-only* e uma
    linha de ensaio ficava la para sempre, a contar como invocacao numa tabela
    cuja cobertura e um critero de aceitacao.

    Nao prova que o esquema esta na revisao certa — isso e do *gate* 8 — nem
    fecha a janela do passo 7 por completo (ver a *docstring* do modulo). O que
    prova e as duas metades que a configuracao erra: a tabela existe, e o papel
    tem `INSERT` nas dezoito colunas.
    """
    cursor = ligacao.cursor()
    try:
        cursor.execute(SQL_CONFIRMAR)
        linha = cursor.fetchone()
        ligacao.commit()
    except Exception as erro:  # noqa: BLE001 — a razao vai na mensagem
        ligacao.rollback()
        raise AuditoriaIndisponivelError(
            f"nao se conseguiu confirmar a `platform.tool_audit`: {erro}"
        ) from erro
    finally:
        cursor.close()
    sem_privilegio = [
        coluna for coluna, permitido in zip(COLUNAS, linha, strict=True) if not permitido
    ]
    if sem_privilegio:
        raise AuditoriaIndisponivelError(
            f"o papel desta ligacao nao tem `INSERT` em {sem_privilegio} de "
            "`platform.tool_audit`; uma tool `money` corria sem registo (ADR-015)"
        )


def escrever(ligacao: Any, linha: LinhaDeAuditoria) -> None:
    """Escreve a linha sob o contexto de tenant. Levanta se nao conseguir.

    **Chama-se `escrever` e nao `registar`**, e nao e preferencia: o `log_policy`
    lint do *gate* 2 proibe `.registar(...)` no codigo de servico, porque e a
    porta sem tipos do *logger* (`kamba_core.logger`). Um nome que colide com
    uma regra de lint por acidente custa um ciclo de CI a quem vier depois.

    O `tenant_guard.tx` poe o `app.tenant_id` **do contexto**, e e o `WITH
    CHECK` da politica `tenant_iso` que impede uma linha de auditoria no nome de
    outro tenant. Nao e redundante com o `tenant_id` do parametro: o parametro e
    o que se escreve e a politica e quem o confronta com a sessao.
    """
    try:
        with tenant_guard.tx(ligacao, linha.ctx.tenant_id) as cursor:
            cursor.execute(SQL_ESCREVER, linha.parametros())
    except Exception as erro:  # noqa: BLE001 — a razao vai na mensagem
        raise AuditoriaIndisponivelError(
            f"nao se registou a invocacao de `{linha.tool}` em `tool_audit`: {erro}"
        ) from erro
