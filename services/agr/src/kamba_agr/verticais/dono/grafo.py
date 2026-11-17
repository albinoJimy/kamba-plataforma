"""O `build_graph` do Assistente do Dono. E o alvo do `registry/dono.yaml`.

A mesma construcao do grafo de Servicos, e pelas mesmas tres razoes: o mapa de
cada encaminhador deriva-se da tabela de arestas, um no condicional sem
encaminhador levanta, e as tres listas — nos, tabela e funcoes — confrontam-se
antes de compilar. Nao se partilha a funcao com Servicos porque cada uma le as
tabelas do **seu** pacote, e uma funcao parametrizada pelas tabelas era a
extraccao que o KAM-039 decide.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ...estado import ConversaState
from . import arestas as tabela
from .encaminhadores import POR_NO
from .nos import NOS_DO_GRAFO, Dependencias


class GrafoIncoerenteError(RuntimeError):
    """A tabela de arestas e as funcoes dos nos nao batem. Levanta no arranque."""


def build_graph(deps: Dependencias) -> Any:
    """O grafo do dono, compilado."""
    _conferir_coerencia()

    g = StateGraph(ConversaState)
    for nome, fabrica in NOS_DO_GRAFO.items():
        g.add_node(nome, fabrica(deps))
    for de, para in tabela.directas():
        g.add_edge(de, para)
    for no in tabela.condicionais():
        g.add_conditional_edges(no, POR_NO[no], tabela.mapa_de(no))
    return g.compile(checkpointer=deps.checkpointer)


def _conferir_coerencia() -> None:
    """As tres listas tem de bater, e o reaproveitamento tem de estar no piso."""
    declarados = set(tabela.NOS)
    com_funcao = set(NOS_DO_GRAFO)
    if declarados != com_funcao:
        raise GrafoIncoerenteError(
            f"nos sem funcao: {sorted(declarados - com_funcao)}; "
            f"funcoes sem no: {sorted(com_funcao - declarados)}"
        )
    if len(NOS_DO_GRAFO) != len(tabela.NOS):
        raise GrafoIncoerenteError("ha um nome de no repetido numa das duas tabelas")
    na_tabela = {a.de for a in tabela.ARESTAS} | {a.para for a in tabela.ARESTAS}
    desconhecidos = sorted(na_tabela - declarados - {START, END})
    if desconhecidos:
        raise GrafoIncoerenteError(f"a tabela liga nos que nao existem: {desconhecidos}")
    sem_encaminhador = sorted(set(tabela.condicionais()) - set(POR_NO))
    if sem_encaminhador:
        raise GrafoIncoerenteError(f"nos condicionais sem encaminhador: {sem_encaminhador}")
    # O §21.4: um modulo abaixo do piso «e recusado». Recusa-se aqui, no
    # arranque, e nao so num ensaio: e a validacao do arranque que o §21.4 diz
    # que se aplica sem excepcoes.
    if tabela.reaproveitamento() < tabela.REAPROVEITAMENTO_MINIMO:
        raise GrafoIncoerenteError(
            f"reaproveitamento de {tabela.reaproveitamento():.2f} abaixo de "
            f"{tabela.REAPROVEITAMENTO_MINIMO:.2f} (`docs/tecnica/02` §21.4)"
        )
