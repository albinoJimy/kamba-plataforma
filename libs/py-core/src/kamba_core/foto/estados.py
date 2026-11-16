"""A maquina de estados de um trabalho de imagem (KAM-120).

Os cinco estados sao os do `CHECK` de `platform.image_jobs.estado` (revisao
`foto_de_produtos`), e as transicoes sao as que o *trigger*
`image_jobs_transicao` da mesma revisao impoe. **As duas superficies dizem o
mesmo e o ensaio de base compara-as par a par** (as 25 combinacoes).

| De | Para |
|---|---|
| `pendente` | `a_processar`, `bloqueada_gate`, `falhado` |
| `a_processar` | `concluido`, `bloqueada_gate` (o processo morreu a meio e o *gate* mudou), `falhado` |
| `bloqueada_gate` | `a_processar` (destino, carta ou detector chegaram), `falhado` |
| `concluido` | — (so a `escolhida` muda) |
| `falhado` | — |

E cada motivo vive num estado so: os de `bloqueada_gate` sao retomaveis, os de
`falhado` sao finais. O `CHECK` `image_jobs_motivo_ck` amarra os dois.
"""

from __future__ import annotations

from typing import Final

PENDENTE: Final = "pendente"
A_PROCESSAR: Final = "a_processar"
CONCLUIDO: Final = "concluido"
BLOQUEADA_GATE: Final = "bloqueada_gate"
FALHADO: Final = "falhado"

#: Pela ordem do `CHECK`. Lista **fechada**: um estado novo e uma revisao.
ESTADOS: Final = (PENDENTE, A_PROCESSAR, CONCLUIDO, BLOQUEADA_GATE, FALHADO)

TRANSICOES: Final[dict[str, frozenset[str]]] = {
    PENDENTE: frozenset({A_PROCESSAR, BLOQUEADA_GATE, FALHADO}),
    A_PROCESSAR: frozenset({CONCLUIDO, BLOQUEADA_GATE, FALHADO}),
    BLOQUEADA_GATE: frozenset({A_PROCESSAR, FALHADO}),
    CONCLUIDO: frozenset(),
    FALHADO: frozenset(),
}

FINAIS: Final = frozenset(e for e, destinos in TRANSICOES.items() if not destinos)

# ---------------------------------------------------------------- motivos

#: Sem destino `imagem` autorizado com `apd_ref` para nenhum fornecedor.
MOTIVO_SEM_DESTINO: Final = "sem_destino"
#: Fora de `prod`, e o pedido nao declarou a imagem sintetica.
MOTIVO_SO_SINTETICAS: Final = "so_sinteticas"
#: Imagem real, e nenhum fornecedor autorizado tem a carta de nao-treino
#: (`real_data_ok=false`).
MOTIVO_SEM_CARTA: Final = "sem_carta"
#: O detector local falhou, ou a imagem nao se reduz a forma que pode sair.
MOTIVO_MINIMIZACAO: Final = "minimizacao"

#: Rostos, matriculas, documentos ou ecras: pede-se outra foto ao dono.
MOTIVO_DADOS_PESSOAIS: Final = "dados_pessoais"
#: O original nao e JPEG nem PNG que se saiba limpar, ou e grande demais.
MOTIVO_FORMATO: Final = "formato"
#: O primario e a contingencia falharam; o original fica.
MOTIVO_FORNECEDOR: Final = "fornecedor"
#: O fornecedor devolveu bytes que nao sao imagem.
MOTIVO_RESULTADO_INVALIDO: Final = "resultado_invalido"

MOTIVOS_DO_BLOQUEIO: Final = (MOTIVO_SEM_DESTINO, MOTIVO_SO_SINTETICAS, MOTIVO_SEM_CARTA, MOTIVO_MINIMIZACAO)
MOTIVOS_DA_FALHA: Final = (MOTIVO_DADOS_PESSOAIS, MOTIVO_FORMATO, MOTIVO_FORNECEDOR, MOTIVO_RESULTADO_INVALIDO)


class TransicaoRecusada(ValueError):
    """Uma transicao fora da tabela. O *trigger* recusa a mesma."""

    def __init__(self, de: str, para: str) -> None:
        super().__init__(f"transicao de image_jobs recusada: {de} -> {para}")
        self.de = de
        self.para = para


def pode(de: str, para: str) -> bool:
    """`True` se `de -> para` esta na tabela. Ficar no mesmo estado nao e transicao."""
    return de == para or para in TRANSICOES.get(de, frozenset())


def exigir_transicao(de: str, para: str) -> None:
    if de not in TRANSICOES or para not in TRANSICOES or not pode(de, para):
        raise TransicaoRecusada(de, para)


def motivo_valido(estado: str, motivo: str | None) -> bool:
    """O `image_jobs_motivo_ck`, do lado de ca."""
    if estado == BLOQUEADA_GATE:
        return motivo in MOTIVOS_DO_BLOQUEIO
    if estado == FALHADO:
        return motivo in MOTIVOS_DA_FALHA
    return motivo is None
