"""Simulacro de recuperacao (DR drill) com RTO e RPO medidos — KAM-085.

    folha.py       a folha de passos com carimbos (o relogio comum)
    calculo.py     RPO pelos marcadores, RTO por passo, extrapolacao e decisao
    marcadores.py  o escritor de linhas-marcador a 1/s (corre no condutor)
    eventos.py     o *outbox* e dois consumidores, para o cenario B (condutor)
    ensaio.py      o ensaio local em Docker: cenarios A, B e C
    cli.py         `python -m dr_simulacro calcular|ensaio`

O que este pacote **e**: os instrumentos que o *handoff* do bloco pede — folha
de passos, marcadores, o calculo de RPO e RTO por passo — e um ensaio local que
os exercita contra um PostgreSQL 18 real com o pgBackRest real e a
configuracao de `infra/backup/` montada tal como esta em git.

O que **nao** e: o simulacro do criterio 5 do bloco, que e executado por uma
pessoa de *on-call* que nao escreveu o RB-K08, so com o runbook. O ensaio
local mede os passos tecnicos (restauro, *replay* de WAL, verificacao) numa
maquina; a deteccao, a decisao, o *host* por IaC e o DNS sao humanos ou
dependem de infra-estrutura que nao existe (D1/KAM-105), e a folha di-lo
passo a passo em vez de os preencher com o orcamento.

So biblioteca padrao. O `marcadores.py` e o `eventos.py` importam o `pg8000`
**dentro** da funcao que liga, porque correm no contentor condutor do ensaio
(que o tem, pelo `db/requirements/migrations.txt`) e nao no *gate* 4.
"""
