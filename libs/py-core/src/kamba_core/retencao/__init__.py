"""Retencao e purga por classe de dados (KAM-071).

    politica.py   a `retention_policy`: classes, prazos (todos *proposta*),
                  mecanismos e a lista fechada de tabelas
    jobs.py       a purga: `apagar`, `ttl_sto`, `largar_particao` e `fiscal`,
                  com dry-run, hold legal e a reaplicacao apos restauro
    purge_log.py  a linha de cada unidade, sem conteudo
    hold.py       o hold legal, que vive no `audit_log`

**O bloco do ticket nomeia `services/retention/{policy,jobs,purge_log}`**, e o
modulo vive aqui pela razao que levou o KAM-069 para `kamba_core.destinos` e o
KAM-070 para `kamba_core.direitos`: e uma biblioteca de lote sem servidor, e um
servico novo pedia imagem, *egress* e cablagem para uma funcao que corre a
horas. O desvio fica registado no bloco.

Este subpacote **nao** e reexportado por `kamba_core`.
"""
