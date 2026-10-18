"""ruleset_check — fecha a volta entre o ruleset do GitHub e o espelho (KAM-137).

O ruleset `main: gates fail-closed do KAM-002` e a peca de que toda a
propriedade fail-closed depende: sem ele os gates correm, reportam, e nada
impede o merge. Vive na API do GitHub, altera-se sem PR e sem revisor, e o
espelho versionado em `.github/rulesets/main.json` nao e aplicado por nada.

Este pacote **le** o ruleset efectivo, normaliza-o e compara-o com o espelho.
Nao aplica, nao repoe, nao escreve: a decisao esta em
`docs/adr/ADR-L003-verificacao-do-ruleset.md`, e o modulo nao tem caminho de
escrita nenhum — ha um teste que o exige.

Modulos:

* `config`      le `ci/ruleset.yaml` (repositorio, id do ruleset, espelho);
* `api`         obtem o ruleset efectivo, por `gh api` ou por HTTPS com token;
* `comparador`  normaliza os dois lados e produz as divergencias;
* `cli`         `python -m ruleset_check check`, que e o que o `make ruleset` corre.

**Fail-closed inclui nao conseguir verificar.** Se a API nao responder ou a
credencial nao autorizar, a verificacao sai **2** — nao da o ruleset por
conforme. E a mesma regra que o gate 11 aplica a OSV: um gate de seguranca que
passa quando nao consegue verificar e um gate que mente.

So biblioteca padrao.
"""

__all__ = ["main"]

from .cli import main
