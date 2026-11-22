"""A serie do recolector do registo do PostgreSQL (KAM-225).

```text
registo_pg_tecto_recusado_total  counter  42501 sobre platform.trust_level, do registo
```

**Sem etiquetas**, logo sem tenant (`OBS-I`): o registo do servidor nao diz o
tenant, e o recolector nao o procura. **Nasce a zero**: a serie sai desde o
arranque, e uma regra com `increase(...)` ve a primeira recusa (a licao do
cabecalho de `infra/compose/prometheus/regras/kamba.yml`).

E o par do `tenant_guard_tecto_recusado_total` do KAM-219, e nao o substitui: o
do `tenant_guard` diz **que processo** recebeu o erro, e so ve o que passa pelo
`comTenant`/`comBatch`; este ve **toda** a recusa que a base escreve no registo
— uma ligacao directa, um processo Python, uma consulta solta — e nao diz quem.
"""

from __future__ import annotations

import threading
from typing import Final

METRICA_TECTO_RECUSADO: Final = "registo_pg_tecto_recusado_total"

_AJUDA: Final = {
    METRICA_TECTO_RECUSADO: (
        "counter",
        "Recusas (42501) sobre platform.trust_level a um papel que nao e o kamba_batch, lidas do registo do PostgreSQL.",
    ),
}


class MetricasDoRegistoPg:
    """Um contador em memoria, seguro entre *threads*. So um numero."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._recusas = 0

    def contar(self) -> None:
        with self._trinco:
            self._recusas += 1

    def recusas(self) -> int:
        with self._trinco:
            return self._recusas

    def exposicao(self) -> str:
        """O formato de exposicao do Prometheus, com `# HELP` e `# TYPE`."""
        linhas: list[str] = []
        valor = self.recusas()
        for nome, (tipo, ajuda) in _AJUDA.items():
            linhas.extend((f"# HELP {nome} {ajuda}", f"# TYPE {nome} {tipo}", f"{nome} {valor}"))
        return "\n".join(linhas) + "\n"


#: As metricas do processo.
METRICAS: Final = MetricasDoRegistoPg()
