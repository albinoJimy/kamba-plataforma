"""A regra de dois (ADR-012), medida: reaproveitamento e nucleo sem excepcoes.

Entregue pelo **KAM-039**. Duas perguntas, um ficheiro declarado
(`ci/regra-de-dois.yaml`) e uma linha de comandos:

```text
python -m reuse_metric medir  --root .    reuso = 1 - LoC_especifico / LoC_total
python -m reuse_metric nucleo --root .    criterio (d) do §5.4, classificado
```

As regras de contagem estao em `docs/reuse-metric.md`. O que cada modulo faz:

```text
sloc.py      linhas com codigo, por ficheiro e por simbolo (nao e `wc -l`)
fecho.py     o caminho de execucao, derivado por fecho de importacao
caminho.py   a classificacao e a conta
nucleo.py    o criterio (d), em tres classes: prosa, conteudo, fluxo
cli.py       os dois comandos e os codigos de saida
```
"""

from __future__ import annotations

__all__ = ["caminho", "cli", "fecho", "nucleo", "sloc"]
