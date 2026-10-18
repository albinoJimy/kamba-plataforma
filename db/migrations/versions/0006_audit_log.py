"""Registo de auditoria append-only com cadeia de hash por tenant (KAM-012).

Revisao: 0006
Anterior: 0005

O `docs/tecnica/08` §6 pede uma tabela *append-only* para dinheiro, stock,
preco, acessos privilegiados e configuracao de tenant, com cadeia de hash por
tenant, verificacao da cadeia e ancora diaria. O conteudo das conversas **nao**
entra aqui: so hashes e identificadores (§7.1, e o §7.6 do `docs/tecnica/06`
explica porque e que um registo imutavel so sobrevive ao direito de apagamento
se nao contiver dado pessoal).

Duas tabelas e quatro funcoes:

    audit_log        a linha de auditoria. Forma de §6, com as diferencas
                     declaradas abaixo. `REVOKE` **e** triggers.
    audit_heads      a cabeca da cadeia por tenant, uma linha cada. **Nenhum
                     papel lhe escreve**: so o trigger.
    audit_row_hash   a formula de um elo.
    audit_encadear   o trigger `BEFORE INSERT` que **e** a cadeia.
    audit_append     a porta documentada, que e um `INSERT` e mais nada.

**Tudo o que segue foi medido contra o PostgreSQL 18.6 fixado por digest**
(`pgvector/pgvector:0.8.7-pg18`, `ci/supply-chain/imagens.yaml`), numa base
descartavel, antes de ser escrito. As medicoes estao em `docs/auditoria.md` §5.

## 1. A cadeia vive num trigger, e a primeira versao desta revisao estava errada

A primeira versao pos a cadeia dentro de `audit_append`, com
`SECURITY INVOKER`, e justificou-o assim: o `INSERT ... ON CONFLICT DO UPDATE
... RETURNING old., new.` do PostgreSQL 18 serializa o tenant sem privilegio
elevado, logo nao e preciso `SECURITY DEFINER` e a lista de
`ci/secdef_allowlist.yaml` continua vazia.

**O raciocinio provava a coisa errada.** Serializar e uma propriedade; ser o
**escritor exclusivo** e outra. Com `SECURITY INVOKER`, para a funcao
funcionar o chamador tem de ter `INSERT` em `audit_log` e `SELECT`/`UPDATE` em
`audit_heads` — e quem os tem pode dispensar a funcao. A revisao adversarial
demonstrou-o: o `kamba_app` lia a cabeca, escrevia directamente uma linha
**correctamente encadeada**, com `criado_at` a escolha, avancava a cabeca, e o
verificador respondia «cadeia intacta».

Esta versao poe a cadeia onde o chamador nao lhe chega: num trigger
`BEFORE INSERT` que **recalcula** `criado_at`, `prev_hash` e `row_hash` e
**ignora** o que o chamador enviar nessas tres colunas. Com isso:

* o `kamba_app` tem `INSERT` **por coluna**, sem `criado_at` e sem os hashes;
* nenhum papel de aplicacao escreve em `audit_heads`;
* escrever directamente na tabela deixa de ser um ataque e passa a ser outra
  forma de chamar a mesma coisa — e e por isso que o `audit_append` pode
  continuar `SECURITY INVOKER`: ja nao e ele que guarda a propriedade.

A funcao do trigger e que e `SECURITY DEFINER`, com `search_path` fixo, e tem
entrada em `ci/secdef_allowlist.yaml`. A excepcao e estreita e defensavel: ela
nao escreve a linha — escreve **a cabeca da cadeia**, que e precisamente o que
quem escreve a linha nao pode poder fazer.

## 2. `audit_heads` nao tem RLS, e isso e uma excepcao declarada

O trigger corre como o dono da tabela. Com `FORCE ROW LEVEL SECURITY` o dono
**tambem** esta sujeito a politica, e a cadeia de plataforma — a de
`tenant_id` nulo — ficava invisivel ao predicado `tenant_iso`: as accoes de
plataforma eram impossiveis de registar.

A tabela nao guarda facto nenhum de negocio: uma linha por cadeia, com um hash
opaco. A excepcao esta em `ci/rls_exceptions.yaml`, com o ADR que a funda.
O `audit_log`, esse, tem RLS `FORCE` como todas as outras.

## 3. O `criado_at` entra no hash

Na primeira versao nao entrava, com o argumento de que a cadeia nao devia
depender de valores que a base atribui. A revisao adversarial mostrou o preco:
apagar a ultima linha e reinseri-la com o mesmo conteudo e outra data deixava
a cadeia «intacta». Para um registo cujo valor probatorio e «quem fez o que
**e quando**», a cronologia tem de estar no hash.

O `id` continua de fora, e esse argumento mantem-se: um `id` reatribuido numa
restauracao partia a cadeia inteira sem nada estar errado.

## 4. Imutabilidade: tres camadas, e o que cada uma deixa passar

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
`ALTER TABLE ... DISABLE TRIGGER`, que exige ser dono. **Desvio declarado ao
criterio 5**, com a medicao que o justifica.

## 5. O que esta revisao nao traz

A verificacao nocturna da cadeia e a ancora diaria **nao** sao SQL: sao o
`db/auditoria.py`. O WORM e o repositorio de backup fora do host sao o
KAM-079; a instrumentacao das tools e o KAM-028; a do `ManualProvider` e o
KAM-054.
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
#: Sao **sete** e nao as seis do bloco do ticket: o criterio 9 desse mesmo
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
#: O `criado_at` **entra**, desde a revisao adversarial: sem ele, apagar a
#: ultima linha e reinseri-la com o mesmo conteudo e outra data deixava a
#: cadeia intacta. O `id` continua de fora — um `id` reatribuido numa
#: restauracao partia a cadeia inteira sem nada estar errado.
CAMPOS_DO_ROW_HASH = (
    "prev_hash",
    "criado_at",
    "tenant_id",
    "actor_type",
    "actor_id",
    "action",
    "entity",
    "entity_id",
    "turn_id",
    "payload_hash",
)

#: A expressao SQL que concatena os campos do `row_hash`, pela mesma razao.
#:
#: Os dois anulaveis chegam ja normalizados; os `*_hash` entram em
#: hexadecimal, para que a concatenacao seja sempre texto; o `criado_at` entra
#: em **ISO 8601 UTC com microssegundos**, que e a unica forma de um
#: `timestamptz` dar sempre o mesmo texto independentemente do fuso da sessao;
#: e o separador e `chr(31)`, sem o qual ('ab','c') e ('a','bc') dariam o mesmo
#: hash.
CONCATENACAO_DO_ROW_HASH = (
    "encode(p_prev_hash, 'hex') || chr(31) || "
    "to_char(p_criado_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') "
    "|| chr(31) || p_tenant_id || chr(31) || "
    "p_actor_type || chr(31) || p_actor_id || chr(31) || p_action || chr(31) || "
    "p_entity || chr(31) || p_entity_id || chr(31) || p_turn_id || chr(31) || "
    "encode(p_payload_hash, 'hex')"
)

#: A assinatura de `audit_append`, para o `GRANT` e o `COMMENT`.
ARGUMENTOS_DE_AUDIT_APPEND = "uuid, text, text, text, text, text, text, bytea"

#: A assinatura de `audit_row_hash`, idem.
ARGUMENTOS_DE_ROW_HASH = (
    "bytea, timestamptz, text, text, text, text, text, text, text, bytea"
)

#: As colunas que um papel de aplicacao pode escrever.
#:
#: **O `criado_at`, o `prev_hash` e o `row_hash` nao estao aqui**, e e essa a
#: diferenca entre esta revisao e a primeira versao dela: o trigger escreve-os,
#: e quem insere nao os escolhe. Sem isto, quem tem `INSERT` forja uma linha
#: correctamente encadeada com a data que quiser.
COLUNAS_ESCRITAS_PELO_CHAMADOR = (
    "tenant_id, actor_type, actor_id, action, entity, entity_id, turn_id, payload_hash"
)

#: Variavel com o caminho do ficheiro de copia logica que o `downgrade` escreve.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0006_COPIA"

#: O que a copia logica do `downgrade` leva.
TABELAS_COPIADAS = ("audit_log", "audit_heads")

#: O tecto de comprimento das colunas de texto de `audit_log`.
#:
#: O criterio 7 pede que o payload aceite «apenas hashes e identificadores». O
#: `payload_hash` e `bytea(32)` por `CHECK` e nao cabe la texto — mas o
#: `entity_id` era `text` sem limite, e nada impedia que uma mensagem inteira
#: fosse escrita nele. Um tecto nao prova que o conteudo nao e texto; prova que
#: **nao cabe** uma conversa, que e o risco que o §7.1 nomeia. Apanhado pela
#: revisao adversarial.
TECTO_DE_TEXTO = 256


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
        "uma de `tenant_id` nulo para as accoes de plataforma. **Nenhum papel de "
        "aplicacao lhe escreve**: so o trigger `audit_encadear` (KAM-012).'"
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
          prev_hash     bytea NOT NULL DEFAULT '{GENESE}'::bytea,
          row_hash      bytea NOT NULL DEFAULT '{GENESE}'::bytea,
          CONSTRAINT audit_log_pkey PRIMARY KEY (id),
          CONSTRAINT audit_log_row_hash_uq UNIQUE (tenant_id, row_hash),
          CONSTRAINT audit_log_actor_type CHECK (actor_type IN ({LITERAIS_DE_ATOR})),
          CONSTRAINT audit_log_action CHECK (action IN ({LITERAIS_DE_ACCAO})),
          CONSTRAINT audit_log_hashes_sha256 CHECK (
            octet_length(payload_hash) = 32
            AND octet_length(prev_hash) = 32
            AND octet_length(row_hash) = 32
          ),
          CONSTRAINT audit_log_actor_id_nao_vazio CHECK (actor_id <> ''),
          CONSTRAINT audit_log_entity_id_nao_vazio CHECK (entity_id <> ''),
          CONSTRAINT audit_log_texto_curto CHECK (
            length(actor_id) <= {TECTO_DE_TEXTO}
            AND length(entity) <= {TECTO_DE_TEXTO}
            AND length(entity_id) <= {TECTO_DE_TEXTO}
            AND length(coalesce(turn_id, '')) <= {TECTO_DE_TEXTO}
          )
        )
        """
    )
    # O `UNIQUE (tenant_id, row_hash)` e **por tenant** e nao global, e a razao
    # e um canal de leitura: um indice unico global nao respeita RLS, pelo que
    # quem tem `INSERT` e nao tem `SELECT` confirmava palpites sobre linhas que
    # nao pode ler — incluindo as da cadeia de plataforma, cuja genese e uma
    # constante conhecida. Com o `tenant_id` na chave, o oraculo fica dentro da
    # cadeia que o chamador ja pode escrever. Apanhado pela revisao adversarial.
    op.execute(
        "CREATE INDEX audit_log_tenant_id_idx ON platform.audit_log (tenant_id, id)"
    )
    op.execute(
        "COMMENT ON TABLE platform.audit_log IS "
        "'Registo append-only de dinheiro, stock, preco, acessos privilegiados e "
        "configuracao de tenant (docs/tecnica/08 §6). Nunca conteudo de conversa: "
        "so hashes e identificadores. O `criado_at`, o `prev_hash` e o `row_hash` "
        "sao escritos pelo trigger `audit_encadear`, nunca por quem insere (KAM-012).'"
    )

    _cadeia()
    _imutabilidade()
    _porta()
    _rls()
    _privilegios()


def _cadeia() -> None:
    """A formula do elo, e o trigger que **e** a cadeia.

    `audit_row_hash` e `IMMUTABLE STRICT`: a mesma entrada da sempre o mesmo
    hash, e um argumento em falta devolve `NULL` em vez de um hash de uma
    cadeia mais curta.

    `audit_encadear` e `SECURITY DEFINER` com `search_path` fixo, e e a unica
    excepcao a regra do `docs/tecnica/08` §3.3 neste ticket. A razao e
    estreita: ela nao escreve a linha de auditoria — escreve **a cabeca da
    cadeia**, que e exactamente o que quem escreve a linha nao pode poder
    fazer. Com `SECURITY INVOKER`, o chamador precisaria de `UPDATE` em
    `audit_heads`, e com esse privilegio forja uma linha encadeada sem passar
    por aqui (foi o que a revisao adversarial demonstrou na primeira versao).
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.audit_row_hash(
          p_prev_hash bytea, p_criado_at timestamptz, p_tenant_id text,
          p_actor_type text, p_actor_id text, p_action text, p_entity text,
          p_entity_id text, p_turn_id text, p_payload_hash bytea)
        RETURNS bytea LANGUAGE sql IMMUTABLE STRICT AS $$
          SELECT sha256(convert_to({CONCATENACAO_DO_ROW_HASH}, 'UTF8'))
        $$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.audit_row_hash({ARGUMENTOS_DE_ROW_HASH}) IS "
        "'A formula de um elo da cadeia: SHA-256 sobre os dez campos, por ordem "
        "fixa, separados por chr(31). O `criado_at` entra em ISO 8601 UTC, que e a "
        "unica forma de um timestamptz dar o mesmo texto em qualquer fuso (KAM-012).'"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.audit_encadear() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, platform AS $$
        DECLARE
          v_tenant text;
          v_turn   text;
          v_prev   bytea;
          v_row    bytea;
        BEGIN
          NEW.criado_at := now();
          v_tenant := coalesce(NEW.tenant_id::text, '');
          v_turn   := coalesce(NEW.turn_id, '');

          INSERT INTO platform.audit_heads AS h (tenant_id, last_hash)
          VALUES (
            NEW.tenant_id,
            platform.audit_row_hash('{GENESE}'::bytea, NEW.criado_at, v_tenant,
              NEW.actor_type, NEW.actor_id, NEW.action, NEW.entity, NEW.entity_id,
              v_turn, NEW.payload_hash)
          )
          ON CONFLICT (chave) DO UPDATE SET last_hash =
            platform.audit_row_hash(h.last_hash, NEW.criado_at, v_tenant,
              NEW.actor_type, NEW.actor_id, NEW.action, NEW.entity, NEW.entity_id,
              v_turn, NEW.payload_hash)
          -- `RETURNING WITH (OLD AS …, NEW AS …)`: dentro de um trigger, o
          -- `OLD` e o `NEW` da funcao **ensombram** os do RETURNING, e o
          -- `old.last_hash` resolvia para o registo do trigger — que num
          -- BEFORE INSERT nao tem campos («record "old" has no field
          -- last_hash»). Medido; a sintaxe de renomeacao e do PostgreSQL 18.
          RETURNING WITH (OLD AS anterior, NEW AS actual)
            coalesce(anterior.last_hash, '{GENESE}'::bytea), actual.last_hash
          INTO v_prev, v_row;

          NEW.prev_hash := v_prev;
          NEW.row_hash  := v_row;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.audit_encadear() IS "
        "'Escreve o `criado_at`, o `prev_hash` e o `row_hash` de uma linha de "
        "auditoria e avanca a cabeca da cadeia, **ignorando** o que o chamador "
        "enviou nessas colunas. SECURITY DEFINER porque so ela pode escrever em "
        "`audit_heads`: com INVOKER, quem insere forjava uma linha encadeada sem "
        "passar por aqui. A serializacao por tenant vem do bloqueio que o "
        "ON CONFLICT poe na cabeca (KAM-012).'"
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_encadear
          BEFORE INSERT ON platform.audit_log
          FOR EACH ROW EXECUTE FUNCTION platform.audit_encadear()
        """
    )
    # `ALWAYS` tambem aqui: um `session_replication_role = replica` que saltasse
    # este trigger escrevia uma linha com a genese e sem avancar a cabeca.
    op.execute(
        "ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_encadear"
    )


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


def _porta() -> None:
    """`audit_append`: a porta documentada, que hoje e um `INSERT` e mais nada.

    Fica `SECURITY INVOKER` — e isso ja nao e uma decisao de seguranca, porque
    ela nao guarda propriedade nenhuma. Guarda-a o trigger. A funcao existe
    para que o chamador nao tenha de saber a forma da tabela.

    **E nao devolve o `row_hash`.** Devolvia, e isso exigia `SELECT` nessa
    coluna a quem chama — um `RETURNING` le. Com o `kamba_app` a precisar de
    `SELECT (row_hash)`, o criterio 9 («leitura de `audit_log` por `kamba_app`
    recusada») passava a ter uma excepcao, e o oraculo do indice unico ganhava
    um segundo caminho. O recibo de uma escrita de auditoria e a propria
    linha; quem precisar do hash le-o com o papel que le o registo.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.audit_append(
          p_tenant uuid, p_actor_type text, p_actor_id text, p_action text,
          p_entity text, p_entity_id text, p_turn_id text, p_payload_hash bytea)
        RETURNS void LANGUAGE sql AS $$
          INSERT INTO platform.audit_log ({COLUNAS_ESCRITAS_PELO_CHAMADOR})
          VALUES (p_tenant, p_actor_type, p_actor_id, p_action, p_entity,
                  p_entity_id, p_turn_id, p_payload_hash)
        $$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND}) IS
        'Escreve uma linha de auditoria. Nao devolve o row_hash: um RETURNING le,
         e dar SELECT nessa coluna a quem escreve abria uma excepcao ao criterio
         9. A cadeia e do trigger `audit_encadear`, nao desta funcao: escrever
         directamente na tabela da o mesmo resultado. **Exige READ COMMITTED**,
         que e a omissao: sob REPEATABLE READ duas escritas concorrentes na
         mesma cadeia dao 40001 e a segunda perde-se (KAM-012).'
        """
    )


def _rls() -> None:
    """RLS em `audit_log`; `audit_heads` fica de fora, com excepcao declarada.

    O trigger corre como o dono. Com `FORCE`, o dono tambem esta sujeito a
    politica, e a cadeia de plataforma — `tenant_id` nulo — ficava invisivel ao
    predicado `tenant_iso`: `batch.run` e `breakglass.open` eram impossiveis de
    registar.

    A tabela nao guarda facto nenhum de negocio: uma linha por cadeia, com um
    hash opaco. E **nenhum papel de aplicacao lhe escreve** — o `GRANT` e so de
    leitura, e so para quem verifica. A excepcao esta em
    `ci/rls_exceptions.yaml`.

    No `audit_log` a RLS vale como em todas as outras, e tem uma consequencia
    que se quer: as linhas de `tenant_id` nulo sao invisiveis a `tenant_iso`
    para toda a gente, pelo que so o `kamba_batch`, que tem `BYPASSRLS`, as
    escreve e le. O papel da aplicacao nao consegue escrever uma accao de
    plataforma nem ve que ela existe.
    """
    rls.enable_tenant_rls("audit_log")


def _privilegios() -> None:
    """Quem escreve nao le, quem insere nao escolhe a data, e ninguem apaga.

    O `INSERT` e **por coluna**: sem `criado_at`, sem `prev_hash`, sem
    `row_hash`. Mesmo que o trigger os reescrevesse na mesma, o privilegio nao
    se da — uma coluna que nenhum chamador pode escrever e uma coluna que
    nenhum chamador tenta escrever.
    """
    op.execute(
        f"GRANT INSERT ({COLUNAS_ESCRITAS_PELO_CHAMADOR}) "
        "ON platform.audit_log TO kamba_app"
    )
    op.execute(
        f"GRANT INSERT ({COLUNAS_ESCRITAS_PELO_CHAMADOR}) "
        "ON platform.audit_log TO kamba_batch"
    )
    # O `kamba_batch` le a cadeia inteira para a verificar de noite, e e o
    # unico que escreve a cadeia de plataforma — por ter `BYPASSRLS`, porque
    # essas linhas tem `tenant_id` nulo.
    op.execute("GRANT SELECT ON platform.audit_log TO kamba_batch")
    # O papel de auditoria: le o registo e a cabeca. A cabeca porque **verificar
    # a cadeia exige-a** — sem ela, apagar as ultimas N linhas deixava-a
    # consistente consigo propria. A primeira versao negava-lha e com isso
    # tornava o verificador impossivel de correr com o papel estreito.
    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_audit")
    op.execute("GRANT SELECT ON platform.audit_log TO kamba_audit")
    op.execute("GRANT SELECT ON platform.audit_heads TO kamba_audit")
    op.execute("GRANT SELECT ON platform.audit_heads TO kamba_batch")

    # **As funcoes nascem com `EXECUTE` para `PUBLIC`**, que e a omissao do
    # PostgreSQL, e com isso o `kamba_resolver` e o `kamba_identity` podiam
    # chama-las. Revoga-se e concede-se nominalmente; sem isto, os `GRANT`
    # abaixo eram decorativos. Apanhado pela revisao adversarial.
    op.execute(
        f"REVOKE ALL ON FUNCTION platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION platform.audit_row_hash({ARGUMENTOS_DE_ROW_HASH}) "
        "FROM PUBLIC"
    )
    op.execute("REVOKE ALL ON FUNCTION platform.audit_encadear() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION platform.audit_log_imutavel() FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND}) "
        "TO kamba_app, kamba_batch"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.audit_row_hash({ARGUMENTOS_DE_ROW_HASH}) "
        "TO kamba_audit, kamba_batch"
    )


def downgrade() -> None:
    """Apaga o registo de auditoria, e por isso exige copia logica.

    O mesmo guarda da revisao 0005: `audit_log` e prova, e um `DROP TABLE` sem
    rede e perda de prova.
    """
    _copia_logica()
    op.execute(f"DROP FUNCTION IF EXISTS platform.audit_append({ARGUMENTOS_DE_AUDIT_APPEND})")
    op.execute("DROP TABLE IF EXISTS platform.audit_log")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_encadear()")
    op.execute("DROP FUNCTION IF EXISTS platform.audit_log_imutavel()")
    op.execute(f"DROP FUNCTION IF EXISTS platform.audit_row_hash({ARGUMENTOS_DE_ROW_HASH})")
    op.execute("DROP TABLE IF EXISTS platform.audit_heads")
    op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_audit")


def _copia_logica() -> None:
    """Escreve as duas tabelas num ficheiro JSON **novo**, antes de as apagar.

    **Com as tabelas vazias nao exige nada**, e isso nao e conveniencia: a
    suite do gate 8 faz `downgrade base` a cada execucao, e um `downgrade` que
    exige uma variavel para apagar zero linhas torna o gate impossivel de
    correr sem a definir — e uma variavel definida sempre e uma variavel que
    ninguem le. Com linhas, recusa. E a forma da 0005.
    """
    op.execute("ALTER TABLE platform.audit_log DISABLE ROW LEVEL SECURITY")
    contagens = _contar()
    if not any(contagens.values()):
        return

    destino = os.environ.get(VARIAVEL_DA_COPIA)
    resumo = ", ".join(f"{tabela}: {n}" for tabela, n in contagens.items())
    if not destino:
        raise RuntimeError(
            f"downgrade da 0006 recusado: ha registo de auditoria ({resumo}) e o passo "
            f"apaga-o. Defina {VARIAVEL_DA_COPIA} com o caminho de um ficheiro que "
            f"**nao** exista, para onde a copia logica e escrita."
        )
    caminho = Path(destino)
    if caminho.exists():
        raise RuntimeError(f"{VARIAVEL_DA_COPIA} aponta para um ficheiro que ja existe: {caminho}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(_linhas(), indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def _contar() -> dict:
    """Quantas linhas ha em cada tabela a copiar.

    A forma e a da 0005: o ciclo sobre a constante de modulo, e a *f-string*
    sobre a variavel do ciclo — e o unico padrao de SQL dinamico que o gate 3b
    sabe resolver sem correr a revisao.
    """
    contagens = {}
    for tabela_a_contar in TABELAS_COPIADAS:
        contagens[tabela_a_contar] = (
            op.get_bind()
            .exec_driver_sql(f"SELECT count(*) FROM platform.{tabela_a_contar}")
            .scalar_one()
        )
    return contagens


def _linhas() -> dict:
    """As linhas das duas tabelas, como dicionario de listas.

    **Sem argumentos**, e a razao e o gate 3b: ele le esta revisao sem a correr
    e so segue uma chamada cujos argumentos consiga resolver. Um `_linhas(tabela)`
    dentro de um ciclo deixa-o cego ao SQL que a funcao executa — e o SQL de uma
    migracao que o gate nao le e SQL que ninguem verifica. (A 0005 tomou a mesma
    decisao, com a mesma nota.)
    """
    copia: dict = {}
    for tabela_a_copiar in TABELAS_COPIADAS:
        resultado = op.get_bind().exec_driver_sql(
            f"SELECT to_jsonb(t) FROM platform.{tabela_a_copiar} t ORDER BY 1"
        )
        copia[tabela_a_copiar] = [linha[0] for linha in resultado.fetchall()]
    return copia
