"""O ciclo das tres fases de dados do off-boarding (KAM-210, criterio 1).

O processo de lote do onboarding (`services/onboarding-web/src/lote.ts`) corre
as fases do lado TypeScript — o canal, os pendentes e a revogacao — e conta as
sete nas metricas. **As tres deste lado** — a exportacao, a purga e o
certificado — correm aqui, numa volta que le a base e chama cada fase que ja
pode correr:

    exportacao   `pendente`, com os pendentes concluidos (a primeira geracao;
                 as seguintes sao a pedido do titular)
    purga        `pendente` ou `em_curso`, com a revogacao concluida e o D30
                 passado
    certificado  `pendente` ou `em_curso` (a entrega que falhou), com a purga
                 concluida

## O que nao corre sozinho, e porque

Uma purga `falhada` ou `suspensa_disputa` **nao** se repete a cada volta: cada
corrida escreve as suas linhas no `purge_log`, que e *append-only*, e uma falha
que persiste enchia-o de quinze em quinze minutos. Fica parada, o alerta
`offboarding_fase_parada` (ou a disputa) chama um humano, e o *runbook*
(`docs/offboarding.md`) diz como a correr outra vez com `correr_fase`.

## Uma fase que falha nao para as outras

Como no ciclo do lado TypeScript: cada chamada tem o seu `try`, e o resultado
diz quais falharam **pelo nome da fase**, nunca pelo tenant nem pela mensagem.
Uma porta sem adaptador (a entrega do certificado, hoje) levanta
`PortaSemAdaptador`, e a fase fica onde estava.

## As portas

Entram por argumento (`PortasDosDados`) e nenhuma tem valor por omissao que
finja: o armazenamento e o do KAM-011, a entrega do certificado e o cofre dos
contactos nao tem adaptador neste processo (credor KAM-218), e a chave do
certificado e o ciclo das copias vem da configuracao de quem arranca.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from .. import tenant_guard
from ..storage.port import StorageProvider
from .certificado import EntregarAoTitular, emitir_certificado
from .exportacao import FonteDoCatalogo, exportar
from .purga import ApagarContactos, purgar

AbrirLigacao = Callable[[], Any]

#: As fases deste lado, pela ordem do calendario.
FASES_DOS_DADOS: Final = ("exportacao", "purga", "certificado")

#: As fases deste lado que ja podem correr, pela ordem do D0 e do calendario. So
#: de um pedido vivo (`verificacao` concluida e sem `cancelado_at`): a fase volta a
#: pergunta-lo sob trinco. **Sem `LIMIT`**: uma fase que falha em todas as voltas
#: (a entrega sem adaptador) continua listada, e com um limite os pedidos mais
#: antigos tapavam os novos para sempre (achado 2 da revisao adversarial).
SQL_FASES_POR_CORRER: Final = """
  SELECT o.tenant_id::text, o.fase
    FROM platform.offboarding_run o
    JOIN platform.offboarding_run v
      ON v.tenant_id = o.tenant_id AND v.fase = 'verificacao'
   WHERE v.estado = 'concluida'
     AND NOT (v.resultado ? 'cancelado_at')
     AND (
       (o.fase = 'exportacao' AND o.estado = 'pendente'
        AND EXISTS (SELECT 1 FROM platform.offboarding_run p
                     WHERE p.tenant_id = o.tenant_id AND p.fase = 'pendentes' AND p.estado = 'concluida'))
       OR (o.fase = 'purga' AND o.estado IN ('pendente', 'em_curso') AND o.prazo_at <= %s
        AND EXISTS (SELECT 1 FROM platform.offboarding_run r
                     WHERE r.tenant_id = o.tenant_id AND r.fase = 'revogacao' AND r.estado = 'concluida'))
       OR (o.fase = 'certificado' AND o.estado IN ('pendente', 'em_curso')
        AND EXISTS (SELECT 1 FROM platform.offboarding_run g
                     WHERE g.tenant_id = o.tenant_id AND g.fase = 'purga' AND g.estado = 'concluida'))
     )
   ORDER BY v.prazo_at, o.tenant_id, array_position(ARRAY['exportacao', 'purga', 'certificado'], o.fase)
"""


class PortaSemAdaptador(RuntimeError):
    """Uma porta sem adaptador neste processo. A fase que precisa dela falha, e fica parada."""

    def __init__(self, porta: str) -> None:
        super().__init__(f"a porta {porta} do off-boarding nao tem adaptador neste processo")


def entrega_sem_adaptador(_tenant_id: str, _corpo: bytes) -> bool:
    """A entrega do certificado sem adaptador: levanta, e o certificado fica por entregar."""
    raise PortaSemAdaptador("entrega_do_certificado")


@dataclass(frozen=True)
class PortasDosDados:
    """O que as tres fases precisam de fora da base."""

    armazenamento: StorageProvider
    chave_do_certificado: bytes
    kid_do_certificado: str
    copias_expiram_em_dias: int
    entregar: EntregarAoTitular = entrega_sem_adaptador
    apagar_contactos: ApagarContactos | None = None
    fonte_do_catalogo: FonteDoCatalogo | None = None
    anos_fiscais: int | None = None


@dataclass
class ResultadoDaVolta:
    """Quantas chamadas correram, por fase, e as que falharam, pelo nome."""

    feitas: dict[str, int] = field(default_factory=dict)
    falhas: list[str] = field(default_factory=list)


def fases_por_correr(abrir_batch: AbrirLigacao, agora: datetime) -> list[tuple[str, str]]:
    """`(tenant, fase)` por correr, como `kamba_batch`."""
    ligacao = abrir_batch()
    try:
        with tenant_guard.tx_batch(ligacao, "offboarding_dados") as cursor:
            cursor.execute(SQL_FASES_POR_CORRER, (agora,))
            return [(str(t), str(f)) for t, f in cursor.fetchall()]
    finally:
        ligacao.close()


def correr_fase(
    abrir_batch: AbrirLigacao,
    abrir_app: AbrirLigacao,
    portas: PortasDosDados,
    tenant_id: str,
    fase: str,
    agora: datetime,
) -> dict[str, Any]:
    """Uma fase de um tenant. E tambem o que o *runbook* chama a mao, depois de corrigir."""
    if fase == "exportacao":
        return exportar(abrir_batch, abrir_app, tenant_id, portas.armazenamento, agora,
                        fonte_do_catalogo=portas.fonte_do_catalogo)
    if fase == "purga":
        return purgar(abrir_batch, tenant_id, agora, apagar_contactos=portas.apagar_contactos,
                      armazenamento=portas.armazenamento)
    if fase == "certificado":
        return emitir_certificado(
            abrir_batch, tenant_id, agora,
            chave=portas.chave_do_certificado, kid=portas.kid_do_certificado,
            copias_expiram_em_dias=portas.copias_expiram_em_dias,
            entregar=portas.entregar, anos_fiscais=portas.anos_fiscais,
        )
    raise ValueError("fase que nao e do lado dos dados")


def correr_volta(
    abrir_batch: AbrirLigacao,
    abrir_app: AbrirLigacao,
    portas: PortasDosDados,
    agora: datetime,
) -> ResultadoDaVolta:
    """Uma volta: as fases deste lado que ja podem correr, cada uma no seu `try`."""
    r = ResultadoDaVolta()
    try:
        por_correr = fases_por_correr(abrir_batch, agora)
    except Exception:  # noqa: BLE001 — a listagem que falha diz-se pelo nome
        r.falhas.append("listagem")
        return r
    for tenant, fase in por_correr:
        if fase not in FASES_DOS_DADOS:
            continue
        try:
            correr_fase(abrir_batch, abrir_app, portas, tenant, fase, agora)
            r.feitas[fase] = r.feitas.get(fase, 0) + 1
        except Exception:  # noqa: BLE001 — uma fase que falha nao para as outras
            if fase not in r.falhas:
                r.falhas.append(fase)
    return r


__all__ = [
    "FASES_DOS_DADOS",
    "PortaSemAdaptador",
    "PortasDosDados",
    "ResultadoDaVolta",
    "SQL_FASES_POR_CORRER",
    "correr_fase",
    "correr_volta",
    "entrega_sem_adaptador",
    "fases_por_correr",
]
