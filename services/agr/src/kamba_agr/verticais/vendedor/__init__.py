"""A vertical Vendedor: o grafo de §7, as suas tools e os seus nos.

O `registry/vendedor.yaml` aponta o `graph` para `kamba_agr.verticais.vendedor:
build_graph`, e e este modulo que o resolve. O alvo era *proposta* do KAM-027 —
«quem o ratifica e o KAM-031, que escreve o modulo».

**O `__init__` nao importa os submodulos**, pela mesma razao que o do validador:
quem quer a tabela de arestas importa `arestas`, quem quer os nos importa `nos`.
O `build_graph` entra porque e o alvo que o registo cita pelo nome, e um alvo
que o registo nao consiga resolver reprova o arranque (§5.2, validacao 3).
"""

from .grafo import GrafoIncoerenteError, build_graph
from .nos import Dependencias

__all__ = ["Dependencias", "GrafoIncoerenteError", "build_graph"]
