"""A maquina de estados de uma ingestao do Catalogo AI (KAM-049).

Os nove estados sao os do `CHECK` de `platform.catalog_ingestions.estado`
(`docs/tecnica/03` §8.3, revisao `catalogo_ai`), e as transicoes sao as que o *trigger*
`catalog_ingestions_transicao` da mesma revisao impoe. **As duas superficies
dizem o mesmo e o ensaio de base compara-as par a par** (as 81 combinacoes):
uma transicao que so uma delas aceitasse era um caminho que o Python recusa e a
base deixa passar, ou o contrario.

## A tabela

| De | Para |
|---|---|
| `recebida` | `rejeitada_qualidade`, `bloqueada_gate`, `em_extraccao`, `descartada` |
| `rejeitada_qualidade` | `descartada` |
| `bloqueada_gate` | `em_extraccao` (destino autorizado depois), `descartada` |
| `em_extraccao` | `a_perguntar`, `rascunho`, `bloqueada_categoria`, `descartada` |
| `a_perguntar` | `rascunho`, `bloqueada_categoria`, `descartada` |
| `rascunho` | `a_perguntar` (o dono corrige), `publicada`, `bloqueada_categoria`, `descartada` |
| `bloqueada_categoria` | `a_perguntar`, `rascunho` (decisao humana do T&S), `descartada` |
| `publicada` | — |
| `descartada` | — |

**`publicada` so se alcanca a partir de `rascunho`**, que e o estado em que o
dono viu o resumo: e a metade da maquina do «nada publica sem
`OwnerConfirmation`». A outra metade e o `CHECK` da base, que exige a
confirmacao na propria linha.

Uma foto nova e uma ingestao nova (outro `media_id`): por isso a
`rejeitada_qualidade` nao volta atras.
"""

from __future__ import annotations

from typing import Final

RECEBIDA: Final = "recebida"
REJEITADA_QUALIDADE: Final = "rejeitada_qualidade"
EM_EXTRACCAO: Final = "em_extraccao"
A_PERGUNTAR: Final = "a_perguntar"
RASCUNHO: Final = "rascunho"
PUBLICADA: Final = "publicada"
BLOQUEADA_GATE: Final = "bloqueada_gate"
BLOQUEADA_CATEGORIA: Final = "bloqueada_categoria"
DESCARTADA: Final = "descartada"

#: Pela ordem do `CHECK` do §8.3. Lista **fechada**: um estado novo e uma
#: revisao de base de dados.
ESTADOS: Final = (
    RECEBIDA,
    REJEITADA_QUALIDADE,
    EM_EXTRACCAO,
    A_PERGUNTAR,
    RASCUNHO,
    PUBLICADA,
    BLOQUEADA_GATE,
    BLOQUEADA_CATEGORIA,
    DESCARTADA,
)

TRANSICOES: Final[dict[str, frozenset[str]]] = {
    RECEBIDA: frozenset({REJEITADA_QUALIDADE, BLOQUEADA_GATE, EM_EXTRACCAO, DESCARTADA}),
    REJEITADA_QUALIDADE: frozenset({DESCARTADA}),
    BLOQUEADA_GATE: frozenset({EM_EXTRACCAO, DESCARTADA}),
    EM_EXTRACCAO: frozenset({A_PERGUNTAR, RASCUNHO, BLOQUEADA_CATEGORIA, DESCARTADA}),
    A_PERGUNTAR: frozenset({RASCUNHO, BLOQUEADA_CATEGORIA, DESCARTADA}),
    RASCUNHO: frozenset({A_PERGUNTAR, PUBLICADA, BLOQUEADA_CATEGORIA, DESCARTADA}),
    BLOQUEADA_CATEGORIA: frozenset({A_PERGUNTAR, RASCUNHO, DESCARTADA}),
    PUBLICADA: frozenset(),
    DESCARTADA: frozenset(),
}

#: Os estados de onde nao se sai.
FINAIS: Final = frozenset(e for e, destinos in TRANSICOES.items() if not destinos)


class TransicaoRecusada(ValueError):
    """Uma transicao fora da tabela. O `trigger` da revisao `catalogo_ai` recusa a mesma."""

    def __init__(self, de: str, para: str) -> None:
        super().__init__(f"transicao de catalog_ingestions recusada: {de} -> {para}")
        self.de = de
        self.para = para


def pode(de: str, para: str) -> bool:
    """`True` se `de -> para` esta na tabela. Ficar no mesmo estado nao e transicao."""
    return de == para or para in TRANSICOES.get(de, frozenset())


def exigir_transicao(de: str, para: str) -> None:
    """Levanta `TransicaoRecusada` fora da tabela; um estado desconhecido tambem."""
    if de not in TRANSICOES or para not in TRANSICOES or not pode(de, para):
        raise TransicaoRecusada(de, para)
