"""O recolector do registo do PostgreSQL (KAM-225).

Ve a recusa `42501` sobre `platform.trust_level` que o servidor escreve no
registo — a de uma ligacao directa com a credencial do `kamba_app`, de um
processo Python, de uma consulta solta num *pool* —, que o `tenant_guard` do
KAM-219 so via quando passava pelo `comTenant`/`comBatch`. A base nao a conta (a
recusa por privilegio acontece antes de qualquer *trigger*); quem a escreve e o
registo do servidor, e este processo le-o. **Nao ve** a recusa que um bloco
PL/pgSQL apanha com `EXCEPTION`: o servidor nao a escreve.

    leitor.py     seguir os `*.json` e reconhecer a recusa (tres campos)
    metricas.py   o contador da recusa e a idade do registo, sem etiquetas
    processo.py   a volta, a rota `/metrics` e o `/healthz`
"""

from .leitor import PAPEL_DO_LOTE, SQLSTATE_PRIVILEGIO, Seguidor, campos, e_recusa_no_tecto
from .metricas import METRICA_IDADE_DO_REGISTO, METRICA_TECTO_RECUSADO, METRICAS, MetricasDoRegistoPg

__all__ = [
    "METRICAS",
    "METRICA_IDADE_DO_REGISTO",
    "METRICA_TECTO_RECUSADO",
    "PAPEL_DO_LOTE",
    "SQLSTATE_PRIVILEGIO",
    "MetricasDoRegistoPg",
    "Seguidor",
    "campos",
    "e_recusa_no_tecto",
]
