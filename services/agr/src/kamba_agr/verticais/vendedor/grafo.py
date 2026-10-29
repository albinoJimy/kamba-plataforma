"""O `build_graph` do §7.4 — o grafo do Vendedor, montado a partir da tabela.

## Nada aqui esta escrito duas vezes

O esqueleto do §7.4 escreve as arestas a mao, uma `add_conditional_edges` por
no, com o `path_map` em linha. Esta versao percorre a **tabela de arestas**
(`arestas.py`) e constroi as mesmas ligacoes a partir dela, por tres razoes que
foram medidas e nao supostas:

1. **Um `path_map` escrito a mao pode divergir da tabela sem o teste de
   contrato dar por isso.** Dois destinos trocados no mapa de um encaminhador
   dao exactamente o mesmo **conjunto** de arestas — e o conjunto e o que o
   teste compara. Derivando o mapa da tabela, a troca deixa de ser escrivel.
2. **Um no sem encaminhador deixa de ser possivel.** A tabela diz quais sao
   condicionais; o `POR_NO` diz quem os encaminha; faltar um e um `KeyError` no
   arranque, nao um grafo que compila e cai no primeiro turno.
3. **Um no na tabela sem funcao, ou uma funcao sem no, levanta.** Sao duas
   listas que tem de bater, e e aqui que se confrontam.

## O `checkpointer` e obrigatorio para o `handoff_wait`, e nao para o resto

O §11 diz que «sem checkpointer duravel o `interrupt()` perde-se: o arranque do
AGR falha se o saver nao estiver configurado». Este modulo **nao** o impoe, e a
diferenca e de ambito: o arranque e do `__main__.py` (KAM-026 ja la poe a
guarda, com o codigo de saida 4), e um `build_graph` que recusasse compilar sem
saver impedia a bateria de medir os dezanove nos que nao precisam dele. O que
nao se pode e chegar ao `handoff_wait` sem saver — e isso quem o garante e o
LangGraph, que levanta no `interrupt`.
"""

from __future__ import annotations

from typing import Any, Final

from langgraph.graph import StateGraph

from ...estado import ConversaState
from . import arestas as tabela
from .degradado.nos import NOS_DEGRADADOS
from .encaminhadores import POR_NO
from .nos import NOS_DO_GRAFO, Dependencias

#: Os nos do grafo: os do §7.4 e do concierge (`nos.py`) mais os do sub-grafo
#: deterministico (`degradado/nos.py`). **A juncao faz-se aqui e nao no
#: `NOS_DO_GRAFO`**, e e o que mantem o pacote sem ciclo: o `nos.py` nao importa
#: o `degradado/`, porque o `degradado/` importa o `nos.py` (ver a nota do
#: `degradado/intencoes.py`).
#:
#: **Uma colisao de nome levanta aqui e nao sobrescreve em silencio.** Com um
#: `{**a, **b}`, um no do sub-grafo com o nome de um do §7.4 substituia-o e o
#: grafo compilava: o `_conferir_coerencia` compara **conjuntos** de nomes, e os
#: dois conjuntos continuavam a bater. O efeito seria o `order_status` do modo
#: degradado a correr em todos os turnos.
NOS_COMPLETOS: Final = {}
for _tabela in (NOS_DO_GRAFO, NOS_DEGRADADOS):
    for _nome, _fabrica in _tabela.items():
        if _nome in NOS_COMPLETOS:
            raise RuntimeError(
                f"o no `{_nome}` esta declarado em duas tabelas de nos"
            )
        NOS_COMPLETOS[_nome] = _fabrica


class GrafoIncoerenteError(RuntimeError):
    """A tabela de arestas e as funcoes dos nos nao batem.

    Levanta no arranque e nao em execucao: e defeito de quem escreveu a tabela,
    e um grafo com um no sem funcao compila e so rebenta quando um cliente lhe
    chegar.
    """


def build_graph(deps: Dependencias) -> Any:
    """O grafo do Vendedor, compilado. E o alvo do `registry/vendedor.yaml`."""
    _conferir_coerencia()

    g = StateGraph(ConversaState)
    for nome, fabrica in NOS_COMPLETOS.items():
        g.add_node(nome, fabrica(deps))

    for de, para in tabela.directas():
        g.add_edge(de, para)

    for no in tabela.condicionais():
        encaminhador = POR_NO.get(no)
        if encaminhador is None:
            raise GrafoIncoerenteError(
                f"o no `{no}` tem arestas condicionais na tabela de §7.3 e nao tem "
                "encaminhador em `POR_NO`"
            )
        g.add_conditional_edges(no, encaminhador, tabela.mapa_de(no))

    return g.compile(checkpointer=deps.checkpointer)


def _conferir_coerencia() -> None:
    """As tres listas — nos, tabela e encaminhadores — tem de bater."""
    declarados = set(tabela.NOS)
    com_funcao = set(NOS_COMPLETOS)
    if declarados != com_funcao:
        raise GrafoIncoerenteError(
            f"nos sem funcao: {sorted(declarados - com_funcao)}; "
            f"funcoes sem no: {sorted(com_funcao - declarados)}"
        )
    # O `START` e o `END` aparecem na tabela e **nao** sao nos nossos: a
    # diferenca e a mutacao `os sentinelas do LangGraph passam a contar como
    # nos` que o KAM-027 ja pagou.
    na_tabela = {a.de for a in tabela.ARESTAS} | {a.para for a in tabela.ARESTAS}
    desconhecidos = sorted(na_tabela - declarados - {tabela.START, tabela.END})
    if desconhecidos:
        raise GrafoIncoerenteError(
            f"a tabela de §7.3 liga nos que nao existem: {desconhecidos}"
        )
    sem_encaminhador = sorted(set(tabela.condicionais()) - set(POR_NO))
    if sem_encaminhador:
        raise GrafoIncoerenteError(
            f"nos condicionais sem encaminhador: {sem_encaminhador}"
        )
