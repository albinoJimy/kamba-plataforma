"""O `build_graph` do grafo de Servicos. E o alvo do `registry/servicos.yaml`.

## Nada aqui esta escrito duas vezes

Este modulo percorre a **tabela de arestas** (`arestas.py`) e constroi as
ligacoes a partir dela, pelas tres razoes que o grafo do Vendedor mediu:

1. **Um `path_map` escrito a mao pode divergir da tabela sem o teste de
   contrato dar por isso.** Dois destinos trocados no mapa de um encaminhador
   dao exactamente o mesmo **conjunto** de arestas — e o conjunto e o que o
   teste compara. Derivando o mapa da tabela, a troca deixa de ser escrivel.
2. **Um no sem encaminhador deixa de ser possivel.** A tabela diz quais sao
   condicionais; o `POR_NO` diz quem os encaminha; faltar um e um erro no
   arranque, nao um grafo que compila e cai no primeiro turno.
3. **Um no na tabela sem funcao, ou uma funcao sem no, levanta.** Sao duas
   listas que tem de bater, e e aqui que se confrontam.

## Porque e que nao ha `NOS_COMPLETOS` como no Vendedor

O `grafo.py` do Vendedor junta **duas** tabelas de nos — a do §7.4 e a do
sub-grafo deterministico — e levanta numa colisao de nome. Aqui ha **uma**: o
`NOS_DO_GRAFO` do `nos.py` ja traz os catorze importados e os oito proprios
numa tabela so, porque nenhum deles vem de um sub-pacote que importe o `nos.py`
de volta (foi o ciclo que obrigou o Vendedor a juntar no `grafo.py`).

**A guarda contra a colisao nao desaparece por isso**: um nome repetido num
literal de `dict` e silenciosamente o ultimo, pelo que o `_conferir_coerencia`
compara o **tamanho** da tabela com o numero de nomes declarados em `NOS`. Com
`{"a": x, "a": y}` o `dict` tem um elemento e o `NOS` tem dois, e levanta.

## O modo degradado **nao** esta aqui, e e escopo

O KAM-037 entregou o sub-grafo deterministico do **Vendedor**
(`verticais/vendedor/degradado/`), e o bloco dele escreve por extenso que o
perfil de Servicos e ticket proprio. Este grafo nao tem `degraded_menu` e o seu
`classify` nao consulta o detector: um turno de Servicos com o LLM em baixo cai
nas regras do `REGRAS_DE_INTENCAO` e, se nenhuma decidir, em `outro` ->
`safe_reply`. Fica dito aqui porque a ausencia de um no e invisivel a quem leia
a tabela do que ha.

## O `checkpointer` e obrigatorio para o `handoff_wait` e para o `draft_wait`

Nenhum dos dois funciona sem *saver* duravel (§11: «sem checkpointer duravel o
`interrupt()` perde-se»). Este modulo **nao** o impoe, e a diferenca e de
ambito: o arranque e do `__main__.py` (KAM-026, com o codigo de saida 4), e um
`build_graph` que recusasse compilar sem *saver* impedia a bateria de medir os
vinte nos que nao precisam dele.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph

from ...estado import ConversaState
from . import arestas as tabela
from .encaminhadores import POR_NO
from .nos import NOS_DO_GRAFO, Dependencias


class GrafoIncoerenteError(RuntimeError):
    """A tabela de arestas e as funcoes dos nos nao batem.

    Levanta no arranque e nao em execucao: e defeito de quem escreveu a tabela,
    e um grafo com um no sem funcao compila e so rebenta quando um cliente lhe
    chegar.
    """


def build_graph(deps: Dependencias) -> Any:
    """O grafo de Servicos, compilado. E o alvo do `registry/servicos.yaml`."""
    _conferir_coerencia()

    g = StateGraph(ConversaState)
    for nome, fabrica in NOS_DO_GRAFO.items():
        g.add_node(nome, fabrica(deps))

    for de, para in tabela.directas():
        g.add_edge(de, para)

    for no in tabela.condicionais():
        encaminhador = POR_NO.get(no)
        if encaminhador is None:
            raise GrafoIncoerenteError(
                f"o no `{no}` tem arestas condicionais na tabela de §8.1 e nao tem "
                "encaminhador em `POR_NO`"
            )
        g.add_conditional_edges(no, encaminhador, tabela.mapa_de(no))

    return g.compile(checkpointer=deps.checkpointer)


def _conferir_coerencia() -> None:
    """As tres listas — nos, tabela e encaminhadores — tem de bater."""
    declarados = set(tabela.NOS)
    com_funcao = set(NOS_DO_GRAFO)
    if declarados != com_funcao:
        raise GrafoIncoerenteError(
            f"nos sem funcao: {sorted(declarados - com_funcao)}; "
            f"funcoes sem no: {sorted(com_funcao - declarados)}"
        )
    # **A guarda contra o nome repetido no literal de `dict`** — ver o cabecalho.
    # Um `{"a": x, "a": y}` da um `dict` de um elemento, e a comparacao de
    # conjuntos acima nao o ve.
    if len(NOS_DO_GRAFO) != len(tabela.NOS):
        raise GrafoIncoerenteError(
            f"a tabela de nos tem {len(NOS_DO_GRAFO)} entradas e o `NOS` declara "
            f"{len(tabela.NOS)}: ha um nome repetido numa das duas"
        )
    # O `START` e o `END` aparecem na tabela e **nao** sao nos nossos: e a
    # mutacao «os sentinelas do LangGraph passam a contar como nos» que o
    # KAM-027 ja pagou.
    na_tabela = {a.de for a in tabela.ARESTAS} | {a.para for a in tabela.ARESTAS}
    desconhecidos = sorted(na_tabela - declarados - {tabela.START, tabela.END})
    if desconhecidos:
        raise GrafoIncoerenteError(
            f"a tabela de §8.1 liga nos que nao existem: {desconhecidos}"
        )
    sem_encaminhador = sorted(set(tabela.condicionais()) - set(POR_NO))
    if sem_encaminhador:
        raise GrafoIncoerenteError(
            f"nos condicionais sem encaminhador: {sem_encaminhador}"
        )
