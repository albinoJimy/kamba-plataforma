"""Retencao e purga por classe de dados (KAM-071).

Tres coisas, e nenhuma apaga dados: quem apaga e o *job*
(`libs/py-core/src/kamba_core/retencao/jobs.py`), como `kamba_batch`.

* **A `platform.purge_log`**, uma linha por unidade de purga — classe, tabela,
  tenant, modo, resultado, motivo, contagens, janela e versao da politica —,
  **sem conteudo nem identificadores de titular** (criterio 5). Nao ha coluna
  onde caiba um `contact_id`, uma chave de objecto ou texto livre: o `motivo` e
  um dominio fechado. *Append-only* por privilegio, como o `erasure_ledger` da
  `0038`: o `kamba_batch` tem `SELECT, INSERT`, o `kamba_audit` le, ninguem tem
  `UPDATE` nem `DELETE`.

* **Duas accoes novas no dominio do `audit_log`**: `retention.hold_aplicado` e
  `retention.hold_levantado` (criterio 6, «o hold ... fica no `audit_log`»). O
  hold **vive** no registo, e nao numa tabela propria: uma tabela de holds e uma
  linha de auditoria por mudanca eram dois registos do mesmo facto. Passam de
  nove a **onze**, pela extensao por migracao que a linha do dominio no §3.2
  autoriza — o caminho que a `0038` abriu.

**Sem funcoes e sem `SECURITY DEFINER`.** As particoes mensais de
`platform.events_log` e `dat.llm_call_log` (criterio 7) criam-se e largam-se em
`db/particoes.py`, com a ligacao do dono: uma funcao que cria tabelas por DDL
dinamico e o que o *gate* 3b recusa por desenho (`tools/canon_lint/sql.py`), e
ensinar-lhe essa forma era afrouxar um *gate*.

## A `purge_log` nao tem FK para `tenants`, e e deliberado

Uma linha de purga tem de sobreviver ao tenant: o encerramento (criterio 9)
apaga o tenant, e a prova de que se apagou e precisamente esta linha. O
`tenant_id` e tambem **anulavel**: um `DROP` de particao e entre tenants.

## O que esta revisao NAO faz

Nao apaga nada, nao agenda nada (KAM-078), nao cria funcoes e nao da `DELETE`
a ninguem que nao o tivesse. Nao toca nas tabelas fiscais: sao imutaveis por *trigger* (KAM-053,
KAM-175), e um caminho de purga fiscal e decisao do fundador com o prazo do CGT.
"""

from __future__ import annotations

import json
import os

from alembic import op

import rls

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

PURGE_LOG = "platform.purge_log"

#: Os dominios fechados, e as mesmas tuplas do `kamba_core.retencao.purge_log`.
#: A bateria de base de dados compara as tres superficies.
MODOS = ("efectiva", "dry_run")
RESULTADOS = ("ok", "recusada", "retida", "falhou")
MOTIVOS = (
    "fiscal_sem_prazo",
    "fiscal_imutavel",
    "hold_tenant",
    "hold_contacto",
    "sem_caminho",
    "particao_por_criar",
    "erro",
)

#: Por extenso para o `CHECK`: o *gate* 3b le a revisao sem a correr e nao
#: resolve um `", ".join(...)` (a licao da `0006` e da `0038`).
LITERAIS_DE_MODO = "'efectiva', 'dry_run'"
LITERAIS_DE_RESULTADO = "'ok', 'recusada', 'retida', 'falhou'"
LITERAIS_DE_MOTIVO = (
    "'fiscal_sem_prazo', 'fiscal_imutavel', 'hold_tenant', 'hold_contacto', "
    "'sem_caminho', 'particao_por_criar', 'erro'"
)

#: O dominio de `audit_log.action` que esta revisao deixa: as nove da `0038` e
#: as duas do hold.
LITERAIS_DE_ACCAO_0042 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado', "
    "'retention.hold_aplicado', 'retention.hold_levantado'"
)

#: O que o `downgrade` repoe: as nove da `0038`, copiadas e nao importadas —
#: uma revisao nao importa outra, e se a `0038` mudar, esta descreve o que a base
#: tinha quando foi escrita.
LITERAIS_DE_ACCAO_0038 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado'"
)

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"

#: A variavel que o `downgrade` exige quando ha linhas de purga a perder.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0042_COPIA"

COLUNAS_DA_COPIA = (
    "purge_id",
    "execucao_id",
    "classe",
    "tabela",
    "tenant_id",
    "modo",
    "resultado",
    "motivo",
    "linhas",
    "objectos",
    "janela_ate",
    "politica_versao",
    "iniciado_at",
    "registado_at",
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {PURGE_LOG} (
          purge_id         uuid CONSTRAINT purge_log_pkey PRIMARY KEY
                           DEFAULT gen_random_uuid(),
          execucao_id      uuid NOT NULL,
          classe           text NOT NULL
                           CONSTRAINT purge_log_classe_ck
                           CHECK (classe ~ '^[a-z][a-z0-9_]{{1,62}}$'),
          tabela           text NOT NULL
                           CONSTRAINT purge_log_tabela_ck
                           CHECK (tabela ~ '^[a-z][a-z0-9_]*[.][a-z][a-z0-9_]*$'),
          tenant_id        uuid,
          modo             text NOT NULL
                           CONSTRAINT purge_log_modo_ck
                           CHECK (modo IN ({LITERAIS_DE_MODO})),
          resultado        text NOT NULL
                           CONSTRAINT purge_log_resultado_ck
                           CHECK (resultado IN ({LITERAIS_DE_RESULTADO})),
          motivo           text
                           CONSTRAINT purge_log_motivo_ck
                           CHECK (motivo IN ({LITERAIS_DE_MOTIVO})),
          linhas           bigint NOT NULL
                           CONSTRAINT purge_log_linhas_ck CHECK (linhas >= 0),
          objectos         bigint NOT NULL DEFAULT 0
                           CONSTRAINT purge_log_objectos_ck CHECK (objectos >= 0),
          janela_ate       timestamptz,
          politica_versao  text NOT NULL
                           CONSTRAINT purge_log_politica_versao_ck
                           CHECK (btrim(politica_versao) <> ''),
          iniciado_at      timestamptz NOT NULL,
          registado_at     timestamptz NOT NULL DEFAULT now(),
          -- Um `ok` nao tem motivo, e tudo o resto tem: uma recusa sem razao
          -- e uma recusa que ninguem consegue resolver.
          CONSTRAINT purge_log_motivo_par_ck
            CHECK ((resultado = 'ok') = (motivo IS NULL)),
          -- So um `ok` apagou alguma coisa. Uma linha `falhou` com contagem
          -- afirmava uma eliminacao que a transaccao reverteu.
          CONSTRAINT purge_log_so_ok_apaga_ck
            CHECK (resultado = 'ok' OR (linhas = 0 AND objectos = 0))
        )
        """
    )
    op.execute(
        f"""
        COMMENT ON TABLE {PURGE_LOG} IS
          'Uma linha por unidade de purga (KAM-071). Sem conteudo nem identificador de titular. Append-only por privilegio: ninguem tem UPDATE nem DELETE.'
        """
    )
    op.execute(
        f"""
        COMMENT ON COLUMN {PURGE_LOG}.tenant_id IS
          'Sem FK para tenants: a linha sobrevive ao encerramento do tenant, que e o que ela prova. Nulo num DROP de particao, que e entre tenants.'
        """
    )
    op.execute(
        f"CREATE INDEX purge_log_tenant_idx ON {PURGE_LOG} (tenant_id, registado_at)"
    )

    rls.enable_tenant_rls("purge_log")

    # Append-only por privilegio, como o `erasure_ledger` da `0038`.
    op.execute(f"GRANT SELECT, INSERT ON {PURGE_LOG} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT ON {PURGE_LOG} TO {PAPEL_DE_AUDITORIA}")

    _alargar_o_dominio_da_accao()


def _alargar_o_dominio_da_accao() -> None:
    """As duas accoes do hold no `CHECK` do `audit_log`.

    Com `NO FORCE` a volta, pela armadilha que a `0038` escreveu: a validacao
    das linhas existentes corre como o dono, e com `FORCE` o dono ve zero
    linhas.
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0042}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def _encolher_o_dominio_da_accao() -> None:
    """Repoe as nove da `0038`, ou recusa. Conta com o `FORCE` ja desligado."""
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log "
            "WHERE action IN ('retention.hold_aplicado', 'retention.hold_levantado')"
        )
        .scalar_one()
    )
    if linhas:
        raise RuntimeError(
            f"downgrade da 0042 recusado: ha {linhas} linha(s) de audit_log com "
            "accao retention.hold_* e o dominio da 0038 nao as aceita. O audit_log "
            "e append-only e nenhum papel tem DELETE: exporte a cadeia e decida o "
            "que fazer a essas linhas antes de descer."
        )
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0038}))
        """
    )


def downgrade() -> None:
    """Desce, e **recusa** perder linhas de purga sem copia.

    O `purge_log` e a prova de que se apagou. Com linhas, exige-se
    `KAMBA_DOWNGRADE_0042_COPIA` com o caminho de um ficheiro onde sao escritas
    antes de cairem — a forma da `0012`. A politica sai **antes** de contar,
    pela licao da `0009`: com `FORCE`, o dono via zero linhas e nao pedia copia.
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    _encolher_o_dominio_da_accao()
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")

    rls.disable_tenant_rls("purge_log")
    linhas = op.get_bind().exec_driver_sql(f"SELECT count(*) FROM {PURGE_LOG}").scalar_one()
    if linhas:
        destino = os.environ.get(VARIAVEL_DA_COPIA, "").strip()
        if not destino:
            raise RuntimeError(
                f"downgrade da 0042: ha {linhas} linha(s) no purge_log, que e a "
                "prova de que se apagou. Defina "
                f"{VARIAVEL_DA_COPIA} com o caminho de um ficheiro onde a copia e "
                "escrita antes de cair, ou nao reverta."
            )
        resultado = op.get_bind().exec_driver_sql(
            f"SELECT {', '.join(COLUNAS_DA_COPIA)} FROM {PURGE_LOG} ORDER BY registado_at"
        )
        with open(destino, "w", encoding="utf-8") as ficheiro:
            json.dump(
                {"purge_log": [
                    {c: (None if v is None else str(v)) for c, v in zip(COLUNAS_DA_COPIA, linha)}
                    for linha in resultado
                ]},
                ficheiro, ensure_ascii=False, indent=2,
            )
    op.execute("DROP INDEX platform.purge_log_tenant_idx")
    op.execute(f"DROP TABLE {PURGE_LOG}")
