"""A vertical Servicos: o grafo de §8, as suas tools e os seus nos.

O `registry/servicos.yaml` aponta o `graph` para
`kamba_agr.verticais.servicos:build_graph`, e e este modulo que o resolve. O
alvo era *proposta* do KAM-027 — «entram com o KAM-035, que escreve o grafo».

**O `__init__` nao importa os submodulos**, pela mesma razao que o do Vendedor:
quem quer a tabela de arestas importa `arestas`, quem quer os nos importa `nos`.
O `build_graph` entra porque e o alvo que o registo cita pelo nome, e um alvo
que o registo nao consiga resolver reprova o arranque (§5.2, validacao 3).

**As `Dependencias` sao as do Vendedor e re-exportam-se daqui.** Nao e um alias
de conveniencia: catorze dos vinte e dois nos deste grafo sao os dele e recebem
aquele tipo, pelo que ou e o mesmo ou se escreve um adaptador por no. A razao
por extenso, e a divida de a classe viver em `verticais/vendedor/` em vez de
`core/`, estao no cabecalho do `nos.py`.
"""

from .grafo import GrafoIncoerenteError, build_graph
from .nos import Dependencias

__all__ = ["Dependencias", "GrafoIncoerenteError", "build_graph"]
