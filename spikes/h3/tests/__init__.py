"""Ensaios do harness do spike H3 (KAM-100).

**Nenhum portao os corre, e isso esta medido.** O `SUITES_DE_TOOLS` do
`Makefile` (linha 61) descobre suites por `tools/*/tests/test_*.py`; os padroes
de `ci/thresholds.yaml` sao `services/*/src/**`, `packages/*/src/**`,
`libs/*/src/**` e `tools/**`; e nem o `Makefile` nem o
`.github/workflows/ci.yaml` nomeiam `spikes/`. Logo estes ensaios sao evidencia
de um instante — o que o PR registar —, e nao uma guarda continua.

A alternativa era poe-los em `tools/<nome>/tests/`, onde o gate 4 os corria. Nao
se fez, por duas razoes e nenhuma delas e conveniencia:

1. o bloco do ticket diz «o *harness* e **descartavel** em `spikes/h3/`», e um
   artefacto descartavel cuja remocao avermelha o gate 4 de todos os PRs deixa
   de ser descartavel;
2. liga-lo a um portao muda o que o gate 4 passa a exigir, e **alterar o
   criterio de um portao e decisao do fundador** — esta skill poe isso nas
   regras de bloqueio. O que se entrega e a medicao; a ligacao, se a quiser,
   e dele.

Correr-se assim, com a raiz do repositorio no PYTHONPATH por causa do
`kamba_core`:

    PYTHONPATH='spikes/h3;libs/py-core/src' python -m unittest discover \\
        -s spikes/h3/tests -t spikes/h3
"""
