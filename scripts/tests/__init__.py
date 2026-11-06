"""Ensaios de `scripts/` (KAM-100).

Existe para o `unittest discover -t scripts` conseguir importar a pasta — sem
ele, o arranque falha com «Start directory is not importable».

**Nenhum portao corre estes ensaios.** Medido: `scripts/` nao esta nos padroes
de `ci/thresholds.yaml`, nao esta no `SUITES_DE_TOOLS` do `Makefile` — que
descobre suites por `tools/*/tests/test_*.py` — e nao e nomeado no
`.github/workflows/ci.yaml`. Fica devolvido no §6, item 7, do
`docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md`: ligar isto a um
portao muda o que o gate 4 exige, e e decisao do fundador.

    python -m unittest discover -s scripts/tests -t scripts
"""
