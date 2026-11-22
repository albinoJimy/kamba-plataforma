"""As duas series do recolector do registo do PostgreSQL (KAM-225).

```text
registo_pg_tecto_recusado_total        counter  42501 sobre platform.trust_level, do registo
registo_pg_idade_do_registo_segundos   gauge    ha quanto tempo o jsonlog mais novo nao muda
```

**Sem etiquetas**, logo sem tenant (`OBS-I`): o registo do servidor nao diz o
tenant, e o recolector nao o procura. **O contador nasce a zero**: a serie sai
desde o arranque, e uma regra com `increase(...)` ve a primeira recusa (a licao
do cabecalho de `infra/compose/prometheus/regras/kamba.yml`).

O contador e o par do `tenant_guard_tecto_recusado_total` do KAM-219, e nao o
substitui: o do `tenant_guard` diz **que processo** recebeu o erro, e so ve o que
passa pelo `comTenant`/`comBatch`; este ve a recusa que a base escreve no registo
— uma ligacao directa, um processo Python, uma consulta solta — e nao diz quem.

**O gauge e o que impede o recolector de ficar cego em silencio.** Um volume com
ficheiros velhos e o `jsonlog` desligado (o `postgres` recriado sem o
`command:`) deixava-o a servir zero para sempre, com o `/healthz` a 200. Com o
servidor de pe, a rotacao por tempo cria ou trunca o ficheiro de cada hora mesmo
sem nada para escrever (medido: `docs/evidencia/KAM-225.md` §2), pelo que a idade
do mais novo fica abaixo de uma hora. Acima disso, o registo parou. Sem nenhum
`*.json` na pasta, a idade e `+Inf`.
"""

from __future__ import annotations

import math
import threading
from typing import Final

METRICA_TECTO_RECUSADO: Final = "registo_pg_tecto_recusado_total"
METRICA_IDADE_DO_REGISTO: Final = "registo_pg_idade_do_registo_segundos"

_AJUDA: Final = {
    METRICA_TECTO_RECUSADO: (
        "counter",
        "Recusas (42501) sobre platform.trust_level a um papel que nao e o kamba_batch, lidas do registo do PostgreSQL.",
    ),
    METRICA_IDADE_DO_REGISTO: (
        "gauge",
        "Segundos desde a ultima modificacao do ficheiro jsonlog mais recente do PostgreSQL.",
    ),
}


class MetricasDoRegistoPg:
    """Um contador e um gauge em memoria, seguros entre *threads*. So numeros."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._recusas = 0
        self._idade: float | None = None

    def contar(self) -> None:
        with self._trinco:
            self._recusas += 1

    def recusas(self) -> int:
        with self._trinco:
            return self._recusas

    def definir_idade(self, segundos: float) -> None:
        """A idade do `jsonlog` mais novo. `math.inf` quando nao ha nenhum."""
        valor = float(segundos)
        if math.isnan(valor) or valor < 0:
            # Um relogio a andar para tras (o *host* acertado) da idade negativa:
            # e registo fresco, e nao registo parado.
            valor = 0.0
        with self._trinco:
            self._idade = valor

    def idade(self) -> float | None:
        with self._trinco:
            return self._idade

    def exposicao(self) -> str:
        """O formato de exposicao do Prometheus, com `# HELP` e `# TYPE`.

        O gauge so sai depois da primeira medicao: um zero inventado leria-se como
        «registo fresco».
        """
        recusas, idade = self.recusas(), self.idade()
        linhas: list[str] = []
        for nome, (tipo, ajuda) in _AJUDA.items():
            linhas.extend((f"# HELP {nome} {ajuda}", f"# TYPE {nome} {tipo}"))
            if nome == METRICA_TECTO_RECUSADO:
                linhas.append(f"{nome} {recusas}")
            elif idade is not None:
                linhas.append(f"{nome} {'+Inf' if math.isinf(idade) else round(idade, 3)}")
        return "\n".join(linhas) + "\n"


#: As metricas do processo.
METRICAS: Final = MetricasDoRegistoPg()
