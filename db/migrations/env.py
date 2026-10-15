"""Ambiente do Alembic (KAM-003).

Tres decisoes, cada uma com a sua razao:

**So modo online.** O modo offline (`--sql`) gera um script sem o aplicar. Aqui
o gate 8 prova as migracoes aplicando-as e revertendo-as contra um PostgreSQL
real; um caminho que nunca e exercitado e um caminho que nao se sabe se funciona.

**Corre como `kamba_migrator`, e so como ele.** O DDL e so desse papel
(`docs/tecnica/03` §11). A ligacao vem de `ligacao.url_sqlalchemy("migrator")`:
nao ha URL no `alembic.ini`.

**A tabela de versao vive em `public`, nao em `platform`.** O `downgrade base`
apaga o schema `platform` — o criterio de aceitacao pede 0 objectos la — e o
Alembic escreve a versao **depois** de correr o `downgrade`. Com a tabela dentro
do schema, o ultimo passo do `downgrade` falharia sempre.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import ligacao

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: Sem `target_metadata`: as revisoes escrevem-se a mao, em SQL, a partir do
#: DDL do desenho. O `--autogenerate` compararia a base com modelos que nao
#: existem e proporia apagar tudo.
target_metadata = None


def run_migrations_online() -> None:
    motor = create_engine(ligacao.url_sqlalchemy("migrator"), poolclass=pool.NullPool)
    with motor.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            version_table="alembic_version",
            version_table_schema="public",
            # Uma transaccao por revisao: o DDL do PostgreSQL e transaccional,
            # pelo que uma revisao que falhe a meio nao deixa meia tabela.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit(
        "o modo offline (--sql) nao e suportado: as migracoes provam-se "
        "aplicadas, no gate 8. Ver db/migrations/env.py."
    )

run_migrations_online()
