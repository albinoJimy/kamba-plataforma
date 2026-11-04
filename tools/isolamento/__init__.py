"""`tools/isolamento` — o *harness* de isolamento cruzado (KAM-066, ADR-015).

Vive em `tools/` e nao em `security/`, que e o que os Detalhes Tecnicos do bloco
propunham: `tools/*/tests/test_*.py` e descoberto pelo `SUITES_DE_TOOLS` do
`Makefile`, `tools/**` ja esta classificado no `ci/thresholds.yaml` e `tools` ja
esta no `PYTHONPATH` — uma pasta de topo nova pedia tres alteracoes de
infra-estrutura, e uma delas e alteracao de critero de *gate*.

Quatro modulos, e sao os quatro que os Detalhes Tecnicos do bloco nomeiam, com
os nomes desta casa (que escreve em portugues) em vez dos do bloco:

    bloco           aqui            o que faz
    ------------    ------------    ----------------------------------------
    enumerate       enumeracao.py   descobre as superficies no codigo-fonte
    cases           casos.py        o registo `registar_caso`, e a cobertura
    oracle          oraculo.py      procura o canario em tudo o que sai
    seed            semente.py      os canarios de A e B, e de X e Y
                    lints.py        `SET LOCAL` de sessao, e o que o 3b nao ve

A ordem nao e indiferente, e e a razao de ser do ticket: **a enumeracao vem
primeiro**. Uma suite de isolamento escrita a mao cresce quando alguem se
lembra; esta recusa-se a passar quando uma superficie nova nao tem caso. O
criterio 2 do bloco di-lo em cinco palavras — «nao existe "sem teste"
silencioso» — e e o unico criterio que transforma a suite num portao.

## O que corre sem base de dados, e o que nao

A enumeracao, a cobertura e os *lints* leem **ficheiros** e correm em segundos,
sem PostgreSQL, sem `node` e sem rede: e o `python -m isolamento` que o *gate* 6
corre antes de levantar o contentor, pela mesma razao por que ele ja corria o
X-11 primeiro.

Os **casos** executam-se contra a base, e por isso vivem onde a base esta:
`db/tests_isolamento/`, que ja semeia dois tenants com canarios em todas as
tabelas com `tenant_id` (KAM-004 e os treze tickets que o alargaram). Os
modulos de `casos/` **declaram** os casos sem importar nada que precise de
base — e o que permite a cobertura ser verificada a seco — e a suite e que lhes
chama o `fn`.
"""

__all__ = ["casos", "enumeracao", "lints", "oraculo"]
