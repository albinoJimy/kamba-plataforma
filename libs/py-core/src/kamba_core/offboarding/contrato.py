"""O que os tres modulos do off-boarding partilham: ler as fases e marca-las.

A tabela e a `platform.offboarding_run` (revisao `*_offboarding.py`). O
`kamba_batch` tem `SELECT`, `INSERT` e `UPDATE (estado, resultado)`; este lado
so **marca** — as linhas escreve-as o pedido, no TypeScript, com os prazos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Mapping

#: As fases pela ordem do bloco. O `CHECK` da revisao tem as mesmas.
FASES: Final = (
    "verificacao",
    "pendentes",
    "canal",
    "exportacao",
    "revogacao",
    "purga",
    "certificado",
)

SQL_FASES: Final = """
  SELECT fase, estado, prazo_at, resultado
    FROM platform.offboarding_run
   WHERE tenant_id = %s
   FOR UPDATE
"""

SQL_MARCAR: Final = """
  UPDATE platform.offboarding_run
     SET estado = %s, resultado = %s::jsonb
   WHERE tenant_id = %s AND fase = %s
"""

#: Um facto do off-boarding no `audit_log`, pela porta da `0006`: a forma do
#: `SQL_AUDITAR` do lado TypeScript (accao `batch.run`, entidade a fase,
#: `payload_hash` o SHA-256 de um texto sem nada do dono).
SQL_AUDITAR: Final = """
  SELECT platform.audit_append(
           %s::uuid, 'system', %s, 'batch.run', %s, %s, NULL, sha256(%s::bytea))
"""

#: O actor do lado dos dados. O do pedido e da revogacao e o
#: `kamba_batch:offboarding`; este distingue-se para o `audit_log` dizer quem fez.
ACTOR: Final = "kamba_batch:offboarding_dados"


class FaseForaDeOrdem(RuntimeError):
    """A fase nao pode correr agora: sem pedido, cancelado, antes do prazo, ou a anterior por concluir."""


class LigacaoRecusada(PermissionError):
    """A ligacao da exportacao expirou, e de outro tenant, ou nao confere. E o 403 do bloco."""


@dataclass(frozen=True)
class LinhaDaFase:
    fase: str
    estado: str
    prazo_at: datetime
    resultado: Mapping[str, Any]


def _objecto(valor: Any) -> dict[str, Any]:
    if isinstance(valor, str):
        return json.loads(valor)
    return dict(valor or {})


def ler_fases(cursor: Any, tenant_id: str) -> dict[str, LinhaDaFase]:
    """As fases do tenant, trancadas (`FOR UPDATE`) na transaccao de quem chama."""
    cursor.execute(SQL_FASES, (tenant_id,))
    return {
        str(f): LinhaDaFase(str(f), str(e), p, _objecto(r))
        for f, e, p, r in cursor.fetchall()
    }


def marcar(cursor: Any, tenant_id: str, fase: str, estado: str, resultado: Mapping[str, Any]) -> None:
    cursor.execute(SQL_MARCAR, (estado, json.dumps(resultado, sort_keys=True, default=str), tenant_id, fase))


def auditar(cursor: Any, tenant_id: str, fase: str, resumo: str) -> None:
    cursor.execute(SQL_AUDITAR, (tenant_id, ACTOR, f"offboarding_{fase}", tenant_id, resumo.encode()))
    cursor.fetchone()


def exigir_pedido_vivo(fases: Mapping[str, LinhaDaFase], fase: str) -> None:
    """O pedido existe, foi verificado e nao foi cancelado."""
    v = fases.get("verificacao")
    if v is None:
        raise FaseForaDeOrdem(f"a fase {fase} nao pode correr: nao ha pedido")
    if v.estado != "concluida":
        raise FaseForaDeOrdem(f"a fase {fase} nao pode correr: o pedido nao foi verificado")
    if "cancelado_at" in v.resultado:
        raise FaseForaDeOrdem(f"a fase {fase} nao pode correr: o pedido foi cancelado")


def exigir_concluida(fases: Mapping[str, LinhaDaFase], anterior: str, fase: str) -> None:
    linha = fases.get(anterior)
    if linha is None or linha.estado != "concluida":
        raise FaseForaDeOrdem(f"a fase {fase} nao pode correr: a fase {anterior} nao foi concluida")


def subestado(fases: Mapping[str, LinhaDaFase], estado_do_tenant: str) -> str | None:
    """O sub-estado de `encerrado` (PA-GOV-6, *proposta*), lido das fases.

    Nao e coluna, e e deliberado: uma coluna era uma segunda resposta a mesma
    pergunta, e as fases ja a respondem.

      em_exportacao   encerrado, e a purga ainda nao correu (o pacote vale)
      em_retencao     a purga correu (ou esta suspensa por disputa) e ficou
                      alguma coisa retida — as classes fiscais ficam sempre ate
                      haver prazo do CGT, pelo que hoje e este o estado final
      purgado         a purga correu e nada ficou retido

    `None` para um tenant que nao esta `encerrado`.
    """
    if estado_do_tenant != "encerrado":
        return None
    purga = fases.get("purga")
    if purga is None or purga.estado not in ("concluida", "suspensa_disputa"):
        return "em_exportacao"
    if purga.estado == "suspensa_disputa" or purga.resultado.get("retidas"):
        return "em_retencao"
    return "purgado"
