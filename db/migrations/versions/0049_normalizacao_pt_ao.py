"""Normalizacao PT-AO: a versao do dicionario e as regras do lexico (KAM-062).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## O que esta revisao cria

O que a normalizacao do `docs/tecnica/05` §4.4 e §5 precisa e a `0045` nao
criou. **A funcao `idx.candidatos` nao muda.**

* `idx.norm_versao`, o registo so de acrescento das versoes do dicionario, sem
  `tenant_id`, o gatilho `termo_canonico_norm_versao` que o alimenta (marca e
  unidade activas marcam os documentos para reindexar, o resto so sobe a versao)
  e o `norm_versao_so_acrescenta`, que recusa reescrever ou apagar uma versao;
* duas `CHECK` no `idx.termo_canonico`: `aprovado_por` obrigatorio, e nenhuma
  entrada `origem = 'dataset'` activa antes do *gate* do KAM-064;
* `SELECT` da versao ao `kamba_app`.

## O SQL nao esta aqui

Esta em `db/indice.py` (`criar_normalizacao` e `remover_normalizacao`), pela
razao da `0045`: os ensaios importam-no dali e o *gate* 3b le-o pelo corpo.

## A cadeia

`down_revision = "0048"`: a cadeia do lote e `0046` (KAM-050), `0047` (KAM-192)
e `0048` (KAM-089), e esta fica no fim. **Num ramo sem a `0048` o `alembic` nao
encontra a revisao de baixo**: esta mede-se presa a `0045` e integra-se depois
das outras tres.
"""

from __future__ import annotations

from alembic import op  # noqa: F401 — o `indice` executa por ele

import indice

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indice.criar_normalizacao()


def downgrade() -> None:
    indice.remover_normalizacao()
