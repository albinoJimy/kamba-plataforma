"""O *handoff* idempotente em dois nos e a retoma por *compare-and-set* (KAM-034).

Os nomes de modulo do bloco do ticket estao em ingles — `kamba/handoff/{service,
nodes,resume_api,timeouts}.py` — e sao do **documento**, nao do codigo: os
modulos deste repositorio tem nomes em portugues (`turno.py`, `trancas.py`,
`admissao.py`, `estado.py`). A correspondencia:

| O bloco escreve | Aqui |
|---|---|
| `service.py` | `servico.py` — o `PortaDeHandoff` do grafo, e a degradacao |
| `nodes.py` | **nao existe**: os tres nos sao do KAM-031, em `verticais/vendedor/nos.py` |
| `resume_api.py` | `retoma.py` (o CAS e o `Command`) + a rota no `api_interna.py` |
| `timeouts.py` | `prazos.py` |

**Os nomes dos nos nao se traduzem.** O `handoff_prepare`, o `handoff_wait` e o
`handoff_close` sao canonicos (dicionario §3.31, e a tabela de 42 arestas do
KAM-031 nomeia-os) e ficam como estao: um nome de no e uma chave do grafo, nao
uma palavra de prosa.

E nao ha `nodes.py` porque nao devia haver: o KAM-031 ja escreveu os tres nos
contra o `Protocol` deste pacote, e uma segunda copia deles aqui — ou um
*wrapper* a chama-los — era duas definicoes do mesmo no e um `build_graph` a
escolher entre elas.

## Por onde se entra

    ServicoDeHandoff   -> `Dependencias(hnd=...)` do `build_graph` (KAM-031)
    Retomador.retomar  -> `rotas(retomar=...)` do `api_interna.py`
    Prazos.varrer      -> quem agenda a varredura de 24 h
"""

from __future__ import annotations

from .autenticacao import CABECALHO_DO_BOT, verificador
from .maquina import (
    DESFECHOS,
    ESTADOS,
    DesfechoInvalidoError,
    estado_do_desfecho,
)
from .portas import (
    HandoffIndisponivel,
    PortaDeGrafos,
    PortaDeModos,
    PortaDoProvedor,
)
from .prazos import PRAZO_SEGUNDOS, Prazos
from .retoma import DESFECHOS_DA_RETOMA, Retomador, ThreadInvalidoError
from .servico import ProvedorPorLigar, ServicoDeHandoff

__all__ = [
    "CABECALHO_DO_BOT",
    "DESFECHOS",
    "DESFECHOS_DA_RETOMA",
    "ESTADOS",
    "DesfechoInvalidoError",
    "HandoffIndisponivel",
    "PRAZO_SEGUNDOS",
    "PortaDeGrafos",
    "PortaDeModos",
    "PortaDoProvedor",
    "Prazos",
    "ProvedorPorLigar",
    "Retomador",
    "ServicoDeHandoff",
    "ThreadInvalidoError",
    "estado_do_desfecho",
    "verificador",
]
