"""scan_secrets — gate 9: varrimento de segredos (KAM-002).

Corre em dois sitios e **tem de dar a mesma resposta nos dois**:

* como gate 9 do pipeline, sobre a arvore seguida pelo git;
* como *hook* de pre-commit, sobre o que esta em *stage*.

O ticket exige as duas: «o *hook* de pre-commit aplica o mesmo scanner». Nao e
conveniencia — um scanner no CI que o pre-commit nao aplica deixa o segredo
chegar ao servidor do git, e a partir dai a remocao e reescrever a historia e
rodar a chave, nao apagar uma linha.

Depende apenas da biblioteca padrao, pela razao do ADR-L001 §6: o primeiro
commit de um clone nao tem `.venv` nem `node_modules`, e um hook que so protege
depois do `make bootstrap` nao protege o primeiro commit de ninguem.

## O que procura

Padroes de **forma**, nao de conteudo: chaves com prefixo conhecido (`sk-`,
`ghp_`, `AKIA`), blocos de chave privada, URLs com credenciais embutidas, e
atribuicoes a nomes que significam segredo (`token`, `secret`, `password`) com
valor de entropia suficiente.

A deteccao por forma tem falsos positivos por desenho, e e para isso que existe
`ci/secrets-allow.yaml` — com **classes** por area, nao com um interruptor.
"""

__all__ = ["main"]

from .cli import main
