"""Registo de auditoria append-only com cadeia de hash por tenant (KAM-012).

Revisao: 0006
Anterior: 0005

O `docs/tecnica/08` §6 pede uma tabela *append-only* para dinheiro, stock,
preco, acessos privilegiados e configuracao de tenant, com cadeia de hash por
tenant, verificacao da cadeia e ancora diaria. O conteudo das conversas **nao**
entra aqui: so hashes e identificadores (§7.1, e o §7.6 do `docs/tecnica/06`
explica porque e que um registo imutavel so sobrevive ao direito de apagamento
se nao contiver dado pessoal).

Duas tabelas e uma funcao:

    audit_log     a linha de auditoria. Forma de §6, com as diferencas
                  declaradas abaixo. `REVOKE` **e** trigger.
    audit_heads   a cabeca da cadeia por tenant, uma linha cada.
    audit_append  escreve a linha e avanca a cadeia, numa transaccao.

**Tudo o que segue foi medido contra o PostgreSQL 18.6 fixado por digest**
(`pgvector/pgvector:0.8.7-pg18`, `ci/supply-chain/imagens.yaml`), numa base
descartavel, antes de ser escrito. As medicoes estao em `docs/auditoria.md` §5.

## 1. `audit_append` e `SECURITY INVOKER`, e isso nao era obvio

O bloco do ticket manda-a ser `SECURITY DEFINER` e entrar em
`ci/secdef_allowlist.yaml`, com a razao «actualiza a cabeca da cadeia». A
allowlist esta vazia desde que existe, o `docs/tecnica/08` §3.3 proibe
`SECURITY DEFINER` «excepto lista aprovada», e as duas revisoes anteriores que
criaram funcoes **recusaram-na por escrito** — a 0004 diz, sobre o
`evt_emitir`, que «uma `SECURITY DEFINER` aqui seria um buraco de isolamento».

A necessidade que a justificaria era ler a cabeca anterior e escrever a nova
sem deixar duas transaccoes bifurcarem a cadeia. O `evt_emitir` resolveu o
mesmo problema com `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, que
bloqueia a linha ate ao COMMIT e serializa o agregado. **Faltava saber como
obter o valor anterior**, porque o `RETURNING` de um `DO UPDATE` devolve a
linha nova.

Medido: o PostgreSQL 18 aceita `old.` e `new.` no `RETURNING`, e numa
insercao o `old` e `NULL`. Uma instrucao da as duas pontas da cadeia:

    INSERT INTO platform.audit_heads AS h (tenant_id, last_hash)
    VALUES (p_tenant, v_novo)
    ON CONFLICT (chave) DO UPDATE SET last_hash = <f(h.last_hash)>
    RETURNING coalesce(old.last_hash, GENESE), new.last_hash

Logo: `SECURITY INVOKER` (a omissao), allowlist continua vazia, e o `WITH
CHECK` da politica `tenant_iso` continua a valer sobre o INSERT.

## 2. O `tenant_id` e nulavel, e a chave primaria e gerada

As accoes de plataforma (`batch.run`, `breakglass.open`) nao tem tenant, e o
§2 do dicionario exige `tenant_id uuid NOT NULL` em toda a tabela de negocio.
E excepcao declarada em `ci/rls_exceptions.yaml`, pela mesma razao que
`tenants` e `contacts` ja la estao.

Medido: `tenant_id uuid PRIMARY KEY` **recusa** a linha de `tenant_id` nulo,
pelo que a cadeia de plataforma nao caberia na tabela de cabecas. A chave
passa a ser uma coluna **gerada**, `coalesce(tenant_id, PLATAFORMA)`, e e ela
o alvo do `ON CONFLICT`. O `tenant_id` continua a dizer a verdade, incluindo
que nao ha nenhum.

## 3. O trigger e `ALWAYS`, e isso muda o teste de adulteracao

Medido, por esta ordem:

* `REVOKE UPDATE, DELETE, TRUNCATE ... FROM PUBLIC` **nao** prende o dono da
  tabela. Um `UPDATE` por `kamba_migrator` passa. Dai o trigger.
* um trigger normal prende o dono — mas **nao** prende quem pode fazer
  `SET session_replication_role = replica`, que e como o bloco do ticket
  propoe adulterar uma linha no ambiente de teste. O `UPDATE` passou e a linha
  ficou adulterada.
* `ENABLE ALWAYS TRIGGER` **resiste** ao `session_replication_role`: o mesmo
  `UPDATE` falhou e a linha ficou intacta.

Escolheu-se `ALWAYS`, que e a proteccao mais forte, e com isso o caminho de
adulteracao que o ticket nomeia deixa de existir. O teste adultera por
`ALTER TABLE ... DISABLE TRIGGER`, que exige ser dono e e um acto que nao se
faz por engano. **Desvio declarado ao criterio 5**, com a medicao que o
justifica — e o que se ganha e que a adulteracao por
`session_replication_role` passa de possivel a impossivel.

## 4. O que esta revisao nao traz

A verificacao nocturna da cadeia e a ancora diaria **nao** sao SQL: sao o
`db/auditoria.py`, que esta revisao nao cria. O WORM e o repositorio de backup
fora do host sao o KAM-079; a instrumentacao das tools e o KAM-028; a do
`ManualProvider` e o KAM-054.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from alembic import op

import rls

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

#: O ator de uma linha de auditoria (dicionario §3.2, emenda 1.14).
TIPOS_DE_ATOR = ("contact", "owner", "staff", "agent", "system")

#: As accoes auditadas. Lista fechada; estende-se por migracao.
#:
#: Sao **sete** e nao as seis do bloco do ticket: o ultimo criterio desse mesmo
#: bloco exige que a leitura do registo seja ela propria registada e chama-lhe
#: `audit.read`, que a lista nao tinha. Um dominio sem ela tornava o criterio
#: impossivel de cumprir (emenda 1.14).
ACCOES = (
    "price.update",
    "stock.adjust",
    "payment.manual_confirm",
    "access.conversation",
    "batch.run",
    "breakglass.open",
    "audit.read",
)

#: A chave da cadeia de plataforma, para as accoes sem tenant.
#:
#: Nao e um tenant: e o valor que a coluna gerada `chave` toma quando
#: `tenant_id` e nulo, para que a cabeca da cadeia caiba numa chave primaria.
#: O UUID de zeros nao colide com `gen_random_uuid()`.
CHAVE_DA_PLATAFORMA = "00000000-0000-0000-0000-000000000000"

#: O `prev_hash` da primeira linha de uma cadeia.
#:
#: Trinta e dois zeros, e nao `NULL`: com `NULL`, o `prev_hash NOT NULL` do §6
#: tornava a primeira linha impossivel, e a verificacao tinha de tratar o
#: primeiro elo como caso especial. Com a genese explicita, a cadeia e uniforme
#: do primeiro elo ao ultimo.
GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000000"

#: As colunas que entram no `row_hash`, por esta ordem.
#:
#: **A ordem e parte da definicao**, e e por isso que esta aqui e nao so no
#: corpo da funcao: a suite do gate 8 recalcula o hash em Python e compara. Um
#: campo que entre no hash sem entrar nesta tupla faz os dois divergirem, que e
#: exactamente o que se quer que aconteca.
#:
#: O `id` e o `criado_at` **nao** entram, e a razao e a verificacao: relê-los
#: obrigaria a cadeia a depender de valores que a base atribui, e um `id`
#: reatribuido numa restauracao partia a cadeia inteira. O que os distingue e o
#: `prev_hash`, que e unico por construcao.
CAMPOS_DO_ROW_HASH = (
    "prev_hash",
    "tenant_id",
    "actor_type",
    "actor_id",
    "action",
    "entity",
    "entity_id",
    "turn_id",
    "payload_hash",
)

#: Os mesmos dois dominios, escritos por extenso para o `CHECK`.
#:
#: **Nao e duplicacao por descuido.** O gate 3b le esta revisao sem a correr e
#: so resolve cadeias, constantes de modulo e *f-strings* sobre elas: um
#: `", ".join(...)` sobre a tupla deixa o SQL ilegivel para ele, e um `CHECK`
#: que o gate nao consegue ler e um dominio que ele nao verifica. Escrevem-se
#: as duas formas, e a *suite* do gate 8 confronta-as — um dominio escrito em
#: dois sitios que ninguem compara e um dominio que vai divergir.
LITERAIS_DE_ATOR = "'contact', 'owner', 'staff', 'agent', 'system'"
LITERAIS_DE_ACCAO = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read'"
)

#: A expressao SQL que concatena os campos do `row_hash`, pela mesma razao.
#:
#: Os dois anulaveis chegam ja normalizados (`coalesce(..., '')` no
#: `audit_append`); os `*_hash` entram em hexadecimal, para que a concatenacao
#: seja sempre texto; e o separador e `chr(31)`, sem o qual ('ab','c') e
#: ('a','bc') dariam o mesmo hash.
CONCATENACAO_DO_ROW_HASH = (
    "encode(p_prev_hash, 'hex') || chr(31) || p_tenant_id || chr(31) || "
    "p_actor_type || chr(31) || p_actor_id || chr(31) || p_action || chr(31) || "
    "p_entity || chr(31) || p_entity_id || chr(31) || p_turn_id || chr(31) || "
    "encode(p_payload_hash, 'hex')"
)

#: A assinatura de `audit_append`, para o `GRANT` e o `COMMENT`.
ARGUMENTOS_DE_AUDIT_APPEND = "uuid, text, text, text, text, text, text, bytea"

#: A assinatura de `audit_row_hash`, idem.
ARGUMENTOS_DE_ROW_HASH = "bytea, text, text, text, text, text, text, text, bytea"

#: Variavel com o caminho do ficheiro de copia logica que o `downgrade` escreve.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0006_COPIA"

#: O que a copia logica do `downgrade` leva.
TABELAS_COPIADAS = ("audit_log", "audit_heads")


def upgrade() -> None:
    # --------------------------------------------------------------- audit_heads
    #
    # A `chave` e gerada e e ela a chave primaria: uma PK recusa NULL, e a
    # cadeia das accoes de plataforma precisa de uma linha com `tenant_id`
    # nulo (medido).
    op.execute(
        f"""
        CREATE TABLE platform.audit_heads (
          tenant_id  uuid,
          chave      uuid GENERATED ALWAYS AS
                     (coalesce(tenant_id, '{CHAVE_DA_PLATAFORMA}'::uuid)) STORED,
          last_hash  bytea NOT NULL,
          CONSTRAINT audit_heads_pkey PRIMARY KEY (chave),
          CONSTRAINT audit_heads_hash_sha256 CHECK (octet_length(last_hash) = 32)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.audit_heads IS "
        "'Cabeca da cadeia de `audit_log` por tenant. Uma linha por tenant, mais "
        "uma de `tenant_id` nulo para as accoes de plataforma (KAM-012).'"
    )

    # ----------------------------------------------------------------- audit_log
    op.execute(
        f"""
        CREATE TABLE platform.audit_log (
          id            bigint GENERATED ALWAYS AS IDENTITY,
          criado_at     timestamptz NOT NULL DEFAULT now(),
          tenant_id     uuid,
          actor_type    text NOT NULL,
          actor_id      text NOT NULL,
          action        text NOT NULL,
          entity        text NOT NULL,
          entity_id     text NOT NULL,
          turn_id       text,
          payload_hash  bytea NOT NULL,
          prev_hash     bytea NOT NULL,
          row_hash      bytea NOT NULL,
          CONSTRAINT audit_log_pkey PRIMARY KEY (id),
          CONSTRAINT audit_log_row_hash_uq UNIQUE (row_hash),
          CONSTRAINT audit_log_actor_type CHECK (actor_type IN ({LITERAIS_DE_ATOR})),
          CONSTRAINT audit_log_action CHECK (action IN ({LITERAIS_DE_ACCAO})),
          CONSTRAINT audit_log_hashes_sha256 CHECK (
            octet_length(payload_hash) = 32
            AND octet_length(prev_hash) = 32
            AND octet_length(row_hash) = 32
          ),
          CONSTRAINT audit_log_actor_id_nao_vazio CHECK (actor_id <> ''),
          CONSTRAINT audit_log_entity_id_nao_vazio CHECK (entity_id <> '')
        )
        """
    )
    # O `UNIQUE (row_hash)` nao e decoracao: duas linhas com o mesmo `row_hash`
    # sao uma bifurcacao da cadeia, e o criterio 3 do ticket pede que mil
    # insercoes concorrentes dem uma cadeia **linear**. Com a restricao, a
    # bifurcacao deixa de ser detectada pelo verificador e passa a ser
    # impossivel de escrever.
    op.execute(
        "CREATE INDEX audit_log_tenant_id_idx ON platform.audit_log (tenant_id, id)"
    )
    op.execute(
        "COMMENT ON TABLE platform.audit_log IS "
        "'Registo append-only de dinheiro, stock, preco, acessos privilegiados e "
        "configuracao de tenant (docs/tecnica/08 §6). Nunca conteudo de conversa: "
        "so hashes e identificadores (KAM-012).'"
    )

    _imutabilidade()
    _funcao_de_escrita()
    _rls()
    _privilegios()


def _imutabilidade() -> None:
    """O que faz de `audit_log` append-only, em tres camadas.

    1. `REVOKE` — tira o privilegio a quem o tem por omissao.
    2. o *trigger* — prende quem tem o privilegio por ser dono; medido que o
       `REVOKE` sozinho nao o faz.
    3. `ENABLE ALWAYS` — prende quem pode `SET session_replication_role =
       replica`; medido que um *trigger* normal nao o faz.
    """
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON platform.audit_log FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION platform.audit_log_imutavel() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION
            'platform.audit_log e append-only: % recusado (KAM-012, docs/tecnica/08 §6)',
            TG_OP
            USING ERRCODE = 'integrity_constraint_violation';
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.audit_log_imutavel() IS "
        "'Levanta excepcao em UPDATE, DELETE e TRUNCATE de platform.audit_log. "
        "SECURITY INVOKER: nao precisa de privilegio nenhum para recusar.'"
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_sem_update_nem_delete
          BEFORE UPDATE OR DELETE ON platform.audit_log
          FOR EACH ROW EXECUTE FUNCTION platform.audit_log_imutavel()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_sem_truncate
          BEFORE TRUNCATE ON platform.audit_log
          FOR EACH STATEMENT EXECUTE FUNCTION platform.audit_log_imutavel()
        """
    )
    op.execute(
        "ALTER TABLE platform.audit_log "
        "ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete"
    )
    op.execute(
        "ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_sem_truncate"
    )
    # A cabeca da cadeia **muda**, pelo que nao leva trigger de imutabilidade.
    # O que a protege e nao haver `UPDATE` directo: so o `audit_append` lhe
    # toca, e o `kamba_app` nao tem `UPDATE` nela (ver `_privilegios`).


def _funcao_de_escrita() -> None:
    """Duas funcoes: a formula do elo, e a escrita que a usa.

    `audit_row_hash` existe por uma razao de correccao e nao de arrumacao. A
    cadeia avanca numa **unica** instrucao — `INSERT ... ON CONFLICT DO UPDATE
    ... RETURNING old., new.` —, e essa instrucao tem **dois** ramos: o da
    primeira linha de uma cadeia, que parte da genese, e o das seguintes, que
    partem de `h.last_hash`. Os dois precisam da mesma formula. Escrita duas
    vezes, divergia; numa funcao `IMMUTABLE`, nao pode divergir.

    E a instrucao ser uma so e o que dispensa o `SECURITY DEFINER`: o
    `ON CONFLICT DO UPDATE` bloqueia a linha da cabeca ate ao COMMIT, o que
    serializa o tenant sem privilegio elevado, e o `RETURNING old./new.` do
    PostgreSQL 18 da as duas pontas sem um segundo `SELECT` que podia ver
    outra coisa. Um `SELECT ... FOR UPDATE` antes nao servia: numa cadeia que
    ainda nao existe nao ha linha para bloquear, e duas primeiras insercoes
    concorrentes partiam da genese as duas.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.audit_row_hash(
          p_prev_hash bytea, p_tenant_id text, p_actor_type text, p_actor_id text,
          p_action text, p_entity text, p_entity_id text, p_turn_id text,
          p_payload_hash bytea)
        RETURNS bytea LANGUAGE sql IMMUTABLE STRICT AS $$
          SELECT sha256(convert_to({CONCATENACAO_DO_ROW_HASH}, 'UTF8'))
        $$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.audit_row_hash({ARGUMENTOS_DE_ROW_HASH}) IS "
        "'A formula de um elo da cadeia: SHA-256 sobre os nove campos, por ordem "
        "fixa, separados por chr(31). STRICT de proposito — um argumento que falte "
        "devolve NULL e o NOT NULL da coluna recusa a linha, em vez de a escrever "
        "com um hash de uma cadeia mais curta (KAM-012).'"
    )
    # **O `tenant_id` entra como `text` e nao como `uuid`, e isso foi medido.**
    # Com `uuid` e `STRICT`, a cadeia de plataforma — a que tem `tenant_id`
    # nulo — fazia a funcao devolver NULL, e o `last_hash NOT NULL` da cabeca
    # recusava a linha: `batch.run` e `breakglass.open` eram impossiveis de
    # registar. O `audit_append` normaliza os dois anulaveis com
    # `coalesce(..., '')` antes de chamar, e o STRICT continua a valer para o
    # que falte de verdade.
    op.execute(
        f"""
        CREATE FUNCTION platform.audit_append(
          p_tenant uuid, p_actor_type text, p_actor_id text, p_action text,
          p_entity text, p_entity_id text, p_turn_id text, p_payload_hash bytea)
        RETURNS bytea LANGUAGE plpgsql AS $$
        DECLARE
          v_tenant text := coalesce(p_tenant::text, '');
          v_turn  text  := coalesce(p_turn_id, '');
          v_prev  bytea;
          v_row   bytea;
        BEGIN
          INSERT INTO platform.audit_heads AS h (tenant_id, last_hash)
          VALUES (
            p_tenant,
            platform.audit_row_hash('{GENESE}'::bytea, v_tenant, p_actor_type,
              p_actor_id, p_action, p_entity, p_entity_id, v_turn, p_payload_hash)
          )
          ON CONFLICT (chave) DO UPDATE SET last_hash =
            platform.audit_row_hash(h.last_hash, v_tenant, p_actor_type,
              p_actor_id, p_action, p_entity, p_entity_id, v_turn, p_payload_hash)
          RETURNING coalesce(old.last_hash, '{GENESE}'::bytea), new.last_hash
          INTO v_prev, v_row;

          INSERT INTO platform.audit_log
            (tenant_id, actor_type, actor_id, action, entity, entity_id,
             turn_id, payload_hash, prev_hash, row_hash)
          VALUES (p_tenant, p_actor_type, p_actor_id, p_action, p_entity,
                  p_entity_id, p_turn_id, p_payload_hash, v_prev, v_row);
          RETURN v_row;
        EXCEPTION WHEN unique_violation THEN
          -- O `UNIQUE (row_hash)` disparou: a mesma linha, no mesmo elo, duas
          -- vezes. Nao se esconde — uma escrita de auditoria que se perde em
          -- silencio e pior do que nao existir.
          RAISE EXCEPTION
            'audit_append: row_hash repetido para o tenant %; a cadeia bifurcaria',
            coalesce(p_tenant::text, '(plataforma)')
            USING ERRCODE = 'unique_violation';
        END $$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND}) IS
        'Escreve uma linha de auditoria e avanca a cadeia do tenant. SECURITY
         INVOKER: a serializacao vem do bloqueio que o ON CONFLICT poe na cabeca,
         e nao de privilegio elevado (KAM-012). O p_payload_hash e o hash do
         antes/depois, nunca o conteudo.'
        """
    )


def _rls() -> None:
    """RLS nas duas, e a de `audit_heads` quase nao entrou.

    O receio era o `ON CONFLICT`: uma linha invisivel por RLS da erro de chave
    duplicada em vez de actualizar, e a cadeia partia-se de forma dificil de
    diagnosticar. Medido, o receio nao se concretiza, e a razao e que a
    `chave` sai do **mesmo** `p_tenant` que o chamador passa: uma sessao so
    pode colidir com a sua propria linha. Um chamador que passe outro tenant e
    recusado pelo `WITH CHECK` do `audit_log`, antes de chegar aqui.

    E as duas excepcoes a regra ficam declaradas aqui e nao em
    `ci/rls_exceptions.yaml`, porque **nao sao excepcoes**: as linhas de
    `tenant_id` nulo — a cadeia das accoes de plataforma — sao invisiveis a
    politica `tenant_iso` para toda a gente, e quem as escreve e le e o
    `kamba_batch`, que tem `BYPASSRLS`. Nao e um furo: e a propriedade que se
    quer. O papel da aplicacao nao consegue escrever uma accao de plataforma
    nem ve que ela existe.
    """
    rls.enable_tenant_rls("audit_log")
    rls.enable_tenant_rls("audit_heads")


def _privilegios() -> None:
    """Quem escreve nao le, e quem le fica registado.

    `kamba_app` tem `INSERT` em `audit_log` e **nao tem `SELECT`**: o criterio 8
    do ticket pede que a leitura seja recusada ao papel da aplicacao. O
    `audit_append` precisa de ler a cabeca e de a escrever, e por isso o
    `kamba_app` tem `SELECT` e `UPDATE` em `audit_heads` — que nao e o registo,
    e so guarda hashes opacos.
    """
    op.execute("GRANT INSERT ON platform.audit_log TO kamba_app")
    op.execute("GRANT SELECT, INSERT, UPDATE (last_hash) ON platform.audit_heads TO kamba_app")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND}) "
        "TO kamba_app"
    )
    # O papel de auditoria: le o registo e mais nada. Nao escreve, nao apaga, e
    # nao tem acesso a `audit_heads` — a cabeca e detalhe de implementacao da
    # cadeia, e quem audita verifica-a recalculando a partir do `audit_log`.
    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_audit")
    op.execute("GRANT SELECT ON platform.audit_log TO kamba_audit")
    # O `kamba_batch` escreve as suas proprias accoes (`batch.run`,
    # `breakglass.open`) e le a cadeia inteira para a verificar de noite — e e
    # o unico que consegue escrever a cadeia de plataforma, porque tem
    # `BYPASSRLS` e essas linhas tem `tenant_id` nulo, invisivel a politica
    # `tenant_iso`. Medido: sem `INSERT` em `audit_heads` o `audit_append`
    # falhava-lhe com «permission denied for table audit_heads», e as duas
    # accoes de plataforma do dominio eram impossiveis de registar.
    #
    # **Le o registo e nao o apaga**: a retencao do `audit_log` e
    # «>= prazo fiscal» (doc 08 §11) e o prazo fiscal esta **NAO VERIFICADO**
    # (dicionario §4, KAM-071) — uma funcao de limpeza escrita contra um prazo
    # que ninguem confirmou apaga prova que a lei pode exigir.
    op.execute("GRANT SELECT, INSERT ON platform.audit_log TO kamba_batch")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE (last_hash) ON platform.audit_heads TO kamba_batch"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND}) "
        "TO kamba_batch"
    )


def downgrade() -> None:
    """Apaga o registo de auditoria, e por isso exige copia logica.

    O mesmo guarda da revisao 0005: `audit_log` e prova, e um `DROP TABLE` sem
    rede e perda de prova. A copia corre **antes** de a RLS ser desligada nao
    porque a ordem importe para o dono — importa: com `FORCE`, o dono le zero
    linhas — mas porque e assim que a 0005 o faz e a razao e a mesma.
    """
    _copia_logica()
    op.execute(f"DROP FUNCTION IF EXISTS platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND})")
    op.execute(f"DROP FUNCTION IF EXISTS platform.audit_row_hash({ARGUMENTOS_DE_ROW_HASH})")
    op.execute("DROP TABLE IF EXISTS platform.audit_log")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_log_imutavel()")
    op.execute("DROP TABLE IF EXISTS platform.audit_heads")
    op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_audit")


def _copia_logica() -> None:
    """Escreve as duas tabelas num ficheiro JSON **novo**, antes de as apagar."""
    destino = os.environ.get(VARIAVEL_DA_COPIA)
    if not destino:
        raise RuntimeError(
            f"o downgrade da revisao 0006 apaga o registo de auditoria. Defina "
            f"{VARIAVEL_DA_COPIA} com o caminho de um ficheiro que **nao** exista, "
            f"para onde a copia logica e escrita."
        )
    caminho = Path(destino)
    if caminho.exists():
        raise RuntimeError(f"{VARIAVEL_DA_COPIA} aponta para um ficheiro que ja existe: {caminho}")
    op.execute("ALTER TABLE platform.audit_log DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.audit_heads DISABLE ROW LEVEL SECURITY")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(_linhas(), indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def _linhas() -> dict:
    """As linhas das duas tabelas, como dicionario de listas.

    **Sem argumentos**, e a razao e o gate 3b: ele le esta revisao sem a correr
    e so segue uma chamada cujos argumentos consiga resolver. Um `_linhas(tabela)`
    dentro de um ciclo deixa-o cego ao SQL que a funcao executa — e o SQL de uma
    migracao que o gate nao le e SQL que ninguem verifica. (A 0005 tomou a mesma
    decisao, com a mesma nota.)
    """
    ligacao = op.get_bind()
    copia: dict = {}
    for tabela in TABELAS_COPIADAS:
        if tabela == "audit_log":
            resultado = ligacao.exec_driver_sql(
                "SELECT to_jsonb(t) FROM platform.audit_log t ORDER BY t.id"
            )
        else:
            resultado = ligacao.exec_driver_sql(
                "SELECT to_jsonb(t) FROM platform.audit_heads t ORDER BY t.chave"
            )
        copia[tabela] = [linha[0] for linha in resultado.fetchall()]
    return copia
