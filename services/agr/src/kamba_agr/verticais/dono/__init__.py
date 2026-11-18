"""A persona Assistente do Dono: o grafo, as suas tools e os seus nos (KAM-118).

O `registry/dono.yaml` aponta o `graph` para `kamba_agr.verticais.dono:build_graph`.
Vive em `verticais/` ao lado do Vendedor e de Servicos sem ser uma vertical de
canal: e uma persona, escolhida pela `contexto.chave_do_registo` quando quem
escreve e o dono. O sitio e o dos grafos, e nao o das verticais de canal —
o `grafos.compilar` le o alvo do registo e nao sabe a diferenca, que e o ponto.

**O `__init__` nao importa os submodulos** alem do alvo, pela razao do Vendedor.
"""

from .grafo import GrafoIncoerenteError, build_graph
from .nos import Dependencias

__all__ = ["Dependencias", "GrafoIncoerenteError", "build_graph"]
