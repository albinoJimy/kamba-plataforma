"""KAM-028: a `tool_audit`, o registo *append-only* de todas as invocacoes da TLS.

O `docs/tecnica/02` §6.4 da o DDL e o `docs/tecnica/08` §6 da a forma da
imutabilidade. Esta revisao cria **uma** tabela e nao cria papel nenhum: o
`kamba_app`, que e o papel com que o AGR le o `platform` (`ligacao.py` do
KAM-025), e quem lhe escreve.

## Porque e que isto nao e a `audit_log`

Sao duas tabelas e as duas sao *append-only*, e a diferenca esta no **ambito**:

| | `audit_log` (KAM-012) | `tool_audit` (este ticket) |
|---|---|---|
| O que cobre | dinheiro, stock, preco, acessos privilegiados e configuracao de tenant (`docs/tecnica/08` §6) | **todas** as invocacoes de tool, incluindo as de leitura |
| Quem escreve | a porta `audit_append`, com cadeia de hash por tenant | a TLS, uma linha por invocacao |
| Cadeia de hash | sim — `prev_hash`/`row_hash` por tenant, com ancora diaria | **nao** |

Uma invocacao de classe `money` escreve nas **duas**: o §6.4 di-lo por extenso
(«Dinheiro, stock e preco tem, alem disto, o seu registo no dominio»), e o bloco
do KAM-028 repete-o nos *Detalhes Tecnicos*.

**A cadeia de hash nao se copia, e isto e uma decisao.** O §6.4 nao a pede, e a
razao e o volume: a `audit_log` escreve por acto de negocio e a `tool_audit`
escreve por invocacao, incluindo todas as leituras de um turno. A cadeia da
`audit_log` serializa as escritas de um tenant num `UPDATE` da `audit_heads` —
o que custa, e e o que a *suite* `tests_auditoria_carga` mede. Posta aqui,
punha o caminho de leitura de um turno a esperar pelo mesmo trinco. O que se
copia e a **imutabilidade** em tres camadas, que e o que faz da tabela um
registo e nao um cache.

## As tres camadas da imutabilidade, e porque sao tres

Sao as da `0006`, medidas la uma a uma:

1. `REVOKE UPDATE, DELETE, TRUNCATE ... FROM PUBLIC` — tira o privilegio a quem
   o tem por omissao. **Nao** prende o dono da tabela.
2. o *trigger* que levanta — prende o dono, e e por isso que o
   `test_privilegios` ve o `kamba_migrator` com tudo e a tabela continua
   *append-only*.
3. `ENABLE ALWAYS` — prende quem pode `SET session_replication_role = replica`,
   que um *trigger* normal nao prende.

## O que a tabela **nao** guarda, e e o critero 5 do bloco

Nem texto de mensagem, nem telefone, nem valores de argumento. O `args_hash` e
a impressao da chamada e o `args_redacted` e a **forma** dela — nome e tipo de
cada argumento, nunca o valor. Um `query` de `search_catalog` e texto do
cliente, e texto do cliente nao entra num registo de auditoria
(`docs/tecnica/08` §6, dicionario §3.27).

Isto nao se prova por leitura do DDL: prova-se por varrimento dos dados, e o
`db/tests/test_tool_audit.py` fa-lo com canarios — foi assim que o KAM-026
descobriu que o seu varrimento de privacidade dava zero por procurar texto num
campo `msgpack`.

## `tool` e `vertical` levam **gramatica** e nao lista de literais

O `klass`, o `status` e o `error_code` levam `CHECK` com a lista: as tres sao
listas fechadas de canon (dicionario §3.27) e nao crescem com o trafego nem com
o registo. O `tool` e o `vertical` levam uma gramatica de identificador.

A razao e a que o `metricas.py` do KAM-025 escreveu para as etiquetas: «uma
lista de proibidos protegia contra os nomes de que alguem se lembrou; a
gramatica protege contra a forma». Aqui o argumento e o simetrico — uma lista
de **permitidos** com as onze tools do Piloto obrigava a uma revisao de base de
dados por cada tool que o KAM-031, o KAM-035 ou a Fase C acrescentassem, e quem
tem de escrever uma migracao para acrescentar uma tool acaba por nao a
acrescentar. Quem recusa uma tool fora do catalogo e o passo 1 do `invoke`, com
`TOOL_NOT_ALLOWED`, onde a lista e o registo e nao o DDL.

## Sem receita de sementeira, pela razao da `audit_log`

As receitas de `db/tests_isolamento/sementes.py` semeiam **e apagam**, e um
*trigger* `ENABLE ALWAYS` recusa o `DELETE`. A `audit_log` esta em
`SEM_RECEITA_COM_RAZAO` por isso mesmo, e a `tool_audit` junta-se-lhe: o
isolamento dela prova-se em `db/tests/test_tool_audit.py`, que faz as perguntas
do X-04 (ler e escrever no tenant de outro, e sem contexto nenhum) sem precisar
de apagar nada.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

#: As colunas que **quem invoca** escreve: todas menos a identidade e a data.
#:
#: O `INSERT` e por coluna, como na `0006`: mesmo que o `DEFAULT now()`
#: reescrevesse o `ts` na mesma, o privilegio nao se da. Uma coluna que nenhum
#: chamador pode escrever e uma coluna que nenhum chamador tenta escrever — e o
#: `ts` de uma linha de auditoria nao e do chamador.
COLUNAS_ESCRITAS_PELO_CHAMADOR = (
    "tenant_id, contact_id, conversation_id, turn_id, run_id, vertical, "
    "graph_version, tool, tool_version, klass, args_hash, args_redacted, "
    "idempotency_key, status, error_code, result_hash, fact_ids, latency_ms"
)

#: As tres classes de tool (`docs/tecnica/02` §6.1, dicionario §3.27).
LITERAIS_DE_KLASS = "'read', 'write', 'money'"

#: Os dois desfechos de uma invocacao, no registo.
LITERAIS_DE_STATUS = "'ok', 'erro'"

#: Os **dez** erros tipados do `docs/tecnica/02` §6.5.
LITERAIS_DE_ERRO = (
    "'NOT_FOUND', 'OUT_OF_STOCK', 'PRICE_CHANGED', 'LIMIT_EXCEEDED', "
    "'ENTITLEMENT_DENIED', 'TOOL_NOT_ALLOWED', 'TENANT_MISMATCH', "
    "'UPSTREAM_TIMEOUT', 'UPSTREAM_DOWN', 'VALIDATION_ERROR'"
)

#: A gramatica de um nome de tool e de vertical. A mesma do `metricas.py`.
GRAMATICA_DE_NOME = "^[a-z][a-z0-9_]{1,62}$"

#: O tecto de comprimento das colunas de texto, como na `0006`.
#:
#: Nao e defesa contra um nome comprido: e defesa contra alguem pôr **conteudo**
#: numa coluna de identificador. Um `turn_id` de 4 KB nao e um `turn_id`.
TECTO_DE_TEXTO = 200


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform.tool_audit (
          id               bigint GENERATED ALWAYS AS IDENTITY,
          ts               timestamptz NOT NULL DEFAULT now(),
          tenant_id        uuid NOT NULL,
          contact_id       uuid,
          conversation_id  uuid,
          turn_id          text,
          run_id           text,
          vertical         text,
          graph_version    text,
          tool             text NOT NULL,
          tool_version     text,
          klass            text NOT NULL,
          args_hash        bytea NOT NULL,
          args_redacted    jsonb,
          idempotency_key  text,
          status           text NOT NULL,
          error_code       text,
          result_hash      bytea,
          fact_ids         text[],
          latency_ms       int,
          CONSTRAINT tool_audit_pkey PRIMARY KEY (id),
          CONSTRAINT tool_audit_klass CHECK (klass IN ({LITERAIS_DE_KLASS})),
          CONSTRAINT tool_audit_status CHECK (status IN ({LITERAIS_DE_STATUS})),
          CONSTRAINT tool_audit_tool_nome CHECK (tool ~ '{GRAMATICA_DE_NOME}'),
          CONSTRAINT tool_audit_vertical_nome CHECK (
            vertical IS NULL OR vertical ~ '{GRAMATICA_DE_NOME}'
          ),
          -- **Duas restricoes e nao uma, e a divisao tem duas razoes.**
          --
          -- A primeira e o **dominio**: os dez codigos do §6.5. Fica num `CHECK`
          -- proprio sobre a coluna porque e assim que o *gate* 3b o reconhece —
          -- ele qualifica um valor pela coluna (`tool_audit.error_code=…`) e
          -- exige «CHECK fechado» na declaracao dela. Escondido dentro da
          -- condicao composta abaixo, os dez valores ficavam **fora do
          -- dicionario** para o lint; medido, dez achados de nivel 1.
          --
          -- **Sem `IS NULL OR`, e nao e esquecimento.** Um `CHECK` recusa
          -- apenas o que e **falso**, e `NULL IN (…)` e `NULL`: a coluna
          -- anulavel passa de graca. O `IS NULL OR` era redundante e tinha um
          -- preco — o *gate* 3b deixava de ler a restricao como dominio
          -- fechado, e os dez valores voltavam a ficar fora do dicionario.
          CONSTRAINT tool_audit_error_code CHECK (
            error_code IN ({LITERAIS_DE_ERRO})
          ),
          -- A segunda e a **coerencia com o `status`**, nos dois sentidos: um
          -- `ok` com codigo de erro e um `erro` sem codigo sao a mesma classe de
          -- linha ilegivel, e um `CHECK` num sentido so deixava passar metade.
          --
          -- A primeira versao punha o `IN` aqui dentro e deixava passar um
          -- `status = 'erro'` com `error_code` nulo: um `CHECK` so recusa o que
          -- e **falso**, e `NULL IN (…)` e `NULL`. Com o dominio na restricao de
          -- cima, aqui basta o `IS NOT NULL`, que nunca e nulo. Apanhado pelo
          -- `test_um_erro_sem_codigo_e_recusado`.
          CONSTRAINT tool_audit_erro_tem_codigo CHECK (
            (status = 'ok' AND error_code IS NULL)
            OR (status = 'erro' AND error_code IS NOT NULL)
          ),
          -- Um resultado so existe quando houve resultado.
          CONSTRAINT tool_audit_resultado_so_em_ok CHECK (
            status = 'ok' OR result_hash IS NULL
          ),
          CONSTRAINT tool_audit_hashes_sha256 CHECK (
            octet_length(args_hash) = 32
            AND (result_hash IS NULL OR octet_length(result_hash) = 32)
          ),
          CONSTRAINT tool_audit_latencia_nao_negativa CHECK (
            latency_ms IS NULL OR latency_ms >= 0
          ),
          -- Um `NULL` dentro do `fact_ids` nao e um `fact_id`: e uma citacao
          -- que o validador do KAM-032 nao consegue resolver, guardada como se
          -- fosse uma.
          CONSTRAINT tool_audit_fact_ids_sem_nulos CHECK (
            fact_ids IS NULL OR array_position(fact_ids, NULL) IS NULL
          ),
          CONSTRAINT tool_audit_texto_curto CHECK (
            length(tool) <= {TECTO_DE_TEXTO}
            AND length(coalesce(turn_id, '')) <= {TECTO_DE_TEXTO}
            AND length(coalesce(run_id, '')) <= {TECTO_DE_TEXTO}
            AND length(coalesce(graph_version, '')) <= {TECTO_DE_TEXTO}
            AND length(coalesce(tool_version, '')) <= {TECTO_DE_TEXTO}
            AND length(coalesce(idempotency_key, '')) <= {TECTO_DE_TEXTO}
          )
        )
        """
    )
    # O indice e `(tenant_id, id)` e nao `(id)`: toda a leitura desta tabela e
    # de um tenant — a verificacao de cobertura do critero 5, o painel por
    # tool — e a RLS acrescenta sempre o `tenant_id` ao predicado. E a mesma
    # forma do `audit_log_tenant_id_idx` da `0006`.
    op.execute(
        "CREATE INDEX tool_audit_tenant_id_idx ON platform.tool_audit (tenant_id, id)"
    )
    op.execute(
        "COMMENT ON TABLE platform.tool_audit IS "
        "'Registo append-only de **todas** as invocacoes da ToolLayer "
        "(docs/tecnica/02 §6.4, KAM-028). Distinta de audit_log, que cobre "
        "dinheiro, stock e preco: uma invocacao money escreve nas duas. Nunca "
        "conteudo de mensagem nem telefone: so args_hash, args_redacted "
        "(a forma dos argumentos, sem valores) e fact_ids.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.tool_audit.args_redacted IS "
        "'A **forma** dos argumentos: nome e tipo de cada um, nunca o valor. "
        "Um valor aqui e texto do cliente num registo de auditoria.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.tool_audit.idempotency_key IS "
        "'O ponto de extensao do passo 5 do docs/tecnica/02 §6.1. Nulo neste "
        "ticket: quem o preenche e o KAM-029. Uma tool write ou money sem "
        "chave nao corre — a recusa e no codigo, antes do backend.'"
    )

    _imutabilidade()
    _rls()
    _privilegios()


def _imutabilidade() -> None:
    """O que faz de `tool_audit` *append-only*, nas tres camadas da `0006`."""
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON platform.tool_audit FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION platform.tool_audit_imutavel() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION
            'platform.tool_audit e append-only: % recusado (KAM-028, docs/tecnica/02 §6.4)',
            TG_OP
            USING ERRCODE = 'integrity_constraint_violation';
        END $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.tool_audit_imutavel() IS "
        "'Levanta excepcao em UPDATE, DELETE e TRUNCATE de platform.tool_audit. "
        "SECURITY INVOKER: nao precisa de privilegio nenhum para recusar.'"
    )
    op.execute(
        """
        CREATE TRIGGER tool_audit_sem_update_nem_delete
          BEFORE UPDATE OR DELETE ON platform.tool_audit
          FOR EACH ROW EXECUTE FUNCTION platform.tool_audit_imutavel()
        """
    )
    op.execute(
        """
        CREATE TRIGGER tool_audit_sem_truncate
          BEFORE TRUNCATE ON platform.tool_audit
          FOR EACH STATEMENT EXECUTE FUNCTION platform.tool_audit_imutavel()
        """
    )
    op.execute(
        "ALTER TABLE platform.tool_audit "
        "ENABLE ALWAYS TRIGGER tool_audit_sem_update_nem_delete"
    )
    op.execute(
        "ALTER TABLE platform.tool_audit ENABLE ALWAYS TRIGGER tool_audit_sem_truncate"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform.tool_audit_imutavel() FROM PUBLIC"
    )


def _rls() -> None:
    """Politica `tenant_iso`, como em toda a tabela com `tenant_id` (ADR-015).

    Aqui a RLS nao e redundante com o *append-only*: o `WITH CHECK` e o que
    impede o papel da aplicacao de escrever uma linha de auditoria **no nome de
    outro tenant**, que e o unico tipo de escrita que esta tabela aceita. E a
    defesa em profundidade do passo 6 do §6.1: o `tenant_id` vem do
    `ToolContext` e o `SET LOCAL app.tenant_id` tem de bater com ele.
    """
    rls.enable_tenant_rls("tool_audit")


def _privilegios() -> None:
    """`INSERT` por coluna para o papel do AGR; leitura so para quem verifica.

    **O `kamba_app` nao le esta tabela.** Escreve-a e nao a le, pela mesma razao
    da `audit_log`: quem produz o registo nao e quem o audita, e um `SELECT`
    concedido ao processo que escreve e um caminho para o conteudo do registo
    voltar a um turno. Quem le e o `kamba_audit` (o papel de auditoria) e o
    `kamba_batch` (a verificacao nocturna).

    **O `kamba_agr` nao ganha nada**, aqui como em todo o `platform`: o KAM-026
    deu-lhe o esquema `lg` e deixou-o sem `USAGE` no `platform`, e e isso que o
    `PAPEIS_SEM_NADA_EM_PLATFORM` do `test_privilegios` mede.
    """
    op.execute(
        f"GRANT INSERT ({COLUNAS_ESCRITAS_PELO_CHAMADOR}) "
        "ON platform.tool_audit TO kamba_app"
    )
    op.execute("GRANT SELECT ON platform.tool_audit TO kamba_audit")
    op.execute("GRANT SELECT ON platform.tool_audit TO kamba_batch")


def downgrade() -> None:
    # Pela ordem inversa: a politica antes da tabela, e os *triggers* caem com
    # ela. A funcao e do schema e nao da tabela, e por isso larga-se a mao.
    rls.disable_tenant_rls("tool_audit")
    op.execute("DROP TABLE platform.tool_audit")
    op.execute("DROP FUNCTION IF EXISTS platform.tool_audit_imutavel()")
