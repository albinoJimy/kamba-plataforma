"""O hold legal: por tenant ou por contacto, e vive no `audit_log` (KAM-071, criterio 6).

## Porque e que nao ha tabela de holds

O criterio diz que o hold «impede a purga **e fica no `audit_log`**». Uma tabela
`retention_holds` mais uma linha de auditoria por cada mudanca eram **dois**
registos do mesmo facto, e a licao do KAM-069 e que duas leitoras da mesma
pergunta divergem sem nenhum portao o ver: um hold levantado na tabela e nao no
registo, ou o contrario. Aqui o registo **e** a fonte: aplicar e levantar sao
duas accoes do `audit_log`, e o *job* le o estado pela ultima accao de cada
alvo. O `audit_log` e *append-only* e encadeado (KAM-012), que e exactamente o
que um hold legal precisa de ser.

## O motivo nao fica em claro

O hold leva a referencia do processo que o justifica — e essa referencia pode
nomear pessoas. Vai **so** no `payload_hash` (`sha256`), que e a forma que o
`audit_log` ja tem para provar o que se disse sem o guardar.

## Quem le, e com que papel

O *job* corre como `kamba_batch`, que tem `BYPASSRLS` e `SELECT` no
`audit_log`: ve os holds de todos os tenants. Uma ligacao de aplicacao ve so os
do seu tenant, que e o certo para um painel.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

#: As duas accoes que a revisao acrescenta ao dominio do `audit_log`.
ACCAO_HOLD_APLICADO: Final = "retention.hold_aplicado"
ACCAO_HOLD_LEVANTADO: Final = "retention.hold_levantado"
ACCOES_DE_HOLD: Final = (ACCAO_HOLD_APLICADO, ACCAO_HOLD_LEVANTADO)

#: O alvo do hold, na coluna `entity`.
ENTIDADE_TENANT: Final = "retention_hold_tenant"
ENTIDADE_CONTACTO: Final = "retention_hold_contact"

#: Escreve uma accao de hold. A forma do `SQL_AUDITAR` do KAM-070.
#:
#: Parametros: tenant, actor_type, actor_id, action, entity, entity_id, motivo.
SQL_AUDITAR_HOLD: Final = """
  SELECT platform.audit_append(
           %s::uuid, %s, %s, %s, %s, %s, NULL, sha256(%s::bytea)
         )
"""

#: A ultima accao de hold de cada alvo, e so os que ficaram aplicados.
#:
#: `DISTINCT ON` com `id DESC` e a ordem da cadeia: o `id` e atribuido na
#: escrita e a cadeia e por tenant, pelo que dentro de um alvo a ordem do `id` e
#: a ordem dos factos.
SQL_HOLDS_ACTIVOS: Final = """
  SELECT tenant_id, entity, entity_id
    FROM (SELECT DISTINCT ON (tenant_id, entity, entity_id)
                 tenant_id, entity, entity_id, action
            FROM platform.audit_log
           WHERE action IN ('retention.hold_aplicado', 'retention.hold_levantado')
           ORDER BY tenant_id, entity, entity_id, id DESC) AS ultima
   WHERE action = 'retention.hold_aplicado'
"""


@dataclass(frozen=True)
class Holds:
    """Os holds activos: tenants inteiros, e contactos por tenant."""

    tenants: frozenset[str] = frozenset()
    contactos: dict[str, frozenset[str]] = field(default_factory=dict)

    def do_tenant(self, tenant_id: str | None) -> bool:
        return tenant_id is not None and str(tenant_id) in self.tenants

    def contactos_de(self, tenant_id: str | None) -> frozenset[str]:
        if tenant_id is None:
            return frozenset()
        return self.contactos.get(str(tenant_id), frozenset())

    def algum_em(self, tenants: Iterable[str]) -> bool:
        """Se algum destes tenants tem hold de tenant **ou** de contacto."""
        return any(self.do_tenant(t) or self.contactos_de(t) for t in tenants)


def ler(cursor: Any) -> Holds:
    """Os holds activos, lidos do `audit_log`."""
    cursor.execute(SQL_HOLDS_ACTIVOS)
    tenants: set[str] = set()
    contactos: dict[str, set[str]] = {}
    for tenant_id, entidade, alvo in cursor.fetchall():
        if entidade == ENTIDADE_TENANT:
            tenants.add(str(tenant_id))
        elif entidade == ENTIDADE_CONTACTO:
            contactos.setdefault(str(tenant_id), set()).add(str(alvo))
    return Holds(
        frozenset(tenants), {t: frozenset(c) for t, c in contactos.items()}
    )


def _escrever(
    cursor: Any,
    accao: str,
    *,
    tenant_id: str,
    contact_id: str | None,
    actor_type: str,
    actor_id: str,
    motivo_ref: str,
) -> None:
    if not motivo_ref.strip():
        raise ValueError("um hold sem referencia do processo nao se audita")
    entidade, alvo = (
        (ENTIDADE_TENANT, tenant_id) if contact_id is None else (ENTIDADE_CONTACTO, contact_id)
    )
    cursor.execute(
        SQL_AUDITAR_HOLD,
        (tenant_id, actor_type, actor_id, accao, entidade, alvo, motivo_ref.encode()),
    )


def aplicar(cursor: Any, **kwargs: Any) -> None:
    """Aplica um hold ao tenant (`contact_id=None`) ou a um contacto."""
    _escrever(cursor, ACCAO_HOLD_APLICADO, **kwargs)


def levantar(cursor: Any, **kwargs: Any) -> None:
    """Levanta o hold. O que fica e a historia dos dois factos, encadeada."""
    _escrever(cursor, ACCAO_HOLD_LEVANTADO, **kwargs)


__all__ = [
    "ACCAO_HOLD_APLICADO",
    "ACCAO_HOLD_LEVANTADO",
    "ACCOES_DE_HOLD",
    "ENTIDADE_CONTACTO",
    "ENTIDADE_TENANT",
    "SQL_AUDITAR_HOLD",
    "SQL_HOLDS_ACTIVOS",
    "Holds",
    "aplicar",
    "levantar",
    "ler",
]
