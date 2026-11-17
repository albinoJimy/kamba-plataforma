"""Activacao do lexico de dataset com o relatorio verde do gate (KAM-199).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

A metade do criterio 7 do KAM-062 que a `0049` deixou presa: uma entrada
`origem = 'dataset'` do `idx.termo_canonico` passa a poder ficar activa, **so**
com um relatorio verde do *gate* de avaliacao anexado que a mediu.

* `idx.eval_relatorio`, um relatorio por linha com os termos do lexico que a
  corrida mediu, que so aceita um verde (`eval_relatorio_verde_ck`: o nDCG@3
  lexical nao cai mais de 2 pontos e o zero-result nao sobe mais de 1) e nao se
  reescreve (`eval_relatorio_imutavel`);
* `termo_canonico.eval_relatorio_id`, com a FK `termo_canonico_eval_relatorio_fk`;
* o gatilho `termo_canonico_dataset_medido` no lugar da
  `termo_canonico_dataset_inactivo_ck`.

O `downgrade` repoe a `CHECK` antiga e **recusa** com uma entrada de *dataset*
activa: descer nao desactiva lexico em silencio.

## O SQL nao esta aqui

Esta em `db/indice.py` (`criar_activacao` e `remover_activacao`), pela razao da
`0045`: os ensaios importam-no dali e o *gate* 3b le-o pelo corpo.

## A cadeia

`down_revision = "0059"`, a `0059_lista_de_espera` do KAM-095. O numero
escreveu-se provisorio, com a base do ramo na `0055`, e a integracao sobre a
`publico/main` em `0c393555` confirmou-o. Os ensaios descobrem esta revisao pelo *glob*
`*_activacao_do_lexico_de_dataset.py`, e nao pelo numero.
"""

from __future__ import annotations

from alembic import op  # noqa: F401 — o `indice` executa por ele

import indice

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indice.criar_activacao()


def downgrade() -> None:
    indice.remover_activacao()
