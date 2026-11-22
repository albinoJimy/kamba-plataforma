"""O recolector do registo do PostgreSQL (KAM-225).

Ve a recusa `42501` sobre `platform.trust_level` venha por onde vier — uma
ligacao directa com a credencial do `kamba_app`, um processo Python, uma
consulta solta num *pool* —, que o `tenant_guard` do KAM-219 so via quando
passava pelo `comTenant`/`comBatch`. A base nao a conta (a recusa por privilegio
acontece antes de qualquer *trigger*); quem a escreve e o registo do servidor, e
este processo le-o.

    leitor.py     seguir os `*.json` e reconhecer a recusa (tres campos)
    metricas.py   `registo_pg_tecto_recusado_total`, sem etiquetas
    processo.py   a volta, a rota `/metrics` e o `/healthz`
"""

from .leitor import PAPEL_DO_LOTE, SQLSTATE_PRIVILEGIO, Seguidor, campos, e_recusa_no_tecto
from .metricas import METRICA_TECTO_RECUSADO, METRICAS, MetricasDoRegistoPg

__all__ = [
    "METRICAS",
    "METRICA_TECTO_RECUSADO",
    "PAPEL_DO_LOTE",
    "SQLSTATE_PRIVILEGIO",
    "MetricasDoRegistoPg",
    "Seguidor",
    "campos",
    "e_recusa_no_tecto",
]
