"""KAM-030: o esquema `dat`, a `dat.llm_call_log` e a particao por omissao.

## Porque e que o esquema `dat` nasce aqui

O `docs/tecnica/06` §14 fixa a tabela como `dat.llm_call_log`, e o `dat` **nao
existia**: o repositorio tinha dois esquemas, o `platform` da `0001` e o `lg` da
`0020`. O dicionario §3.6 tambem nao o tinha — a linha «Esquemas» canonizava
`platform, lg, idx, servicos` e os do Medusa —, e por isso a emenda 1.38
acrescenta-o antes desta revisao poder existir: uma tabela num esquema que o
canon nao conhece e um achado do *gate* 3b, nao uma tabela nova.

E um esquema de **analitica**, nao de aplicacao: o que vive aqui e medida, nao
estado de negocio. Essa e a razao de nao ir para o `platform` — e a mesma
arrumacao que o `06` faz, e a razao pela qual a retencao desta tabela e um
`DROP` de particao (13 meses, `06` §9.3) e nao um `DELETE`.

## Duas colunas a mais do que o §14, e as duas sao de um criterio

O DDL do `06` §14 tem **catorze** colunas. Esta tabela tem **dezesseis**: entram
o `papel` e o `graph_version`.

Nao e enfeite, e **o DoD deste ticket nao fecha sem elas**: «custo por tenant,
por vertical e por **papel** desde o primeiro dia (ADR-018)». Sem a coluna
`papel` o custo por papel nao e calculavel de lado nenhum — o `modelo` nao
serve, porque dois aliases podem apontar ao mesmo modelo e porque o modelo e
`por_decidir` ate o KAM-040 escolher. E o `docs/tecnica/02` §13.4 lista as
quatro etiquetas de *metering* por extenso: `tenant_id`, `vertical`, `papel`,
`graph_version`. Faltavam duas das quatro.

E um desvio **aditivo** a uma fonte mais alta, com a razao escrita — a mesma
classe de desvio que a emenda 1.10 fez ao `events_consumed`, que ganhou um
`tenant_id` que o `06` nao tinha.

## O custo e `numeric` e nao unidade menor inteira, e isso tem de ser dito

A convencao do repositorio e «dinheiro em unidade menor inteira (`*_minor`) com
moeda explicita; nunca virgula flutuante». Esta coluna e `numeric(12, 6)`, que e
o que o `06` §14 escreve, e as duas coisas conciliam-se:

* a unidade menor do USD e o centimo, e o custo de um turno do §13.3 e
  **0,00045 USD** — quatro centesimos e meio de **centimo**. Em unidade menor
  inteira isso arredonda a zero, e uma tabela de custo que arredonda cada linha
  a zero nao mede nada;
* o que a convencao proibe e a **virgula flutuante**, e `numeric` nao e: e
  decimal exacto. A moeda continua explicita, no nome da coluna.

A unidade menor inteira vale para o dinheiro que o negocio movimenta — precos,
encomendas, pagamentos —, e nao para uma fraccao de centimo que nenhum centimo
representa.

## O dominio de `resultado` e **fechado**, e por isso e canon

Seis valores, e e uma lista que so cresce com uma revisao de base de dados — a
licao que a `0022` pagou ao fazer crescer o `tool_audit.error_code` de dez para
onze. Escreve-se **qualificado pela tabela** no dicionario
(`dat.llm_call_log.resultado`), porque `resultado` nu colidia com o `resultado`
de `evt_acoes`, que tem outro dominio: foi o defeito que a emenda 1.37 pagou com
quatro achados de nivel 1.

| Valor | Quando |
|---|---|
| `ok` | a chamada correu no fornecedor de `ordem: 1` |
| `ok_fallback` | correu no segundo fornecedor aprovado (criterio 6) |
| `budget_exhausted` | o LiteLLM recusou por orcamento. O criterio 4 diz «mapeado do 400» e a versao fixada responde **422** com `type: budget_exceeded`; o reconhecimento e pelo tipo (`llm/erros.py`) |
| `timeout` | passou o tecto do alias (8 s no `router`, 20 s no `chat`) |
| `erro_fornecedor` | o fornecedor falhou por outra razao |
| `destino_negado` | o *gate* de destino recusou **antes** de sair (ADR-008) |

**O `destino_negado` escreve linha, e e deliberado.** Uma chamada recusada e uma
chamada: o criterio 5 diz «cada chamada grava 1 linha», o teste de orcamento do
criterio 4 tem de **contar** recusas — senao passa com o orcamento apagado —, e
a `v_transfer_audit` do KAM-069 precisa de ver as tentativas, nao so as que
sairam. Nessas linhas o `modelo` e o `fornecedor` sao os **pretendidos**, e os
*tokens* e o custo ficam nulos: nao houve chamada a contar.

## Sem conteudo, e isso nao se prova a ler este ficheiro

Nao ha coluna de *prompt*, de resposta, de telefone nem de texto de cliente, e
nenhuma das dezesseis o pode conter. Mas «nao ha coluna» nao e prova de «nao ha
conteudo»: o `trace_id`, o `no_grafo` e o `modelo` sao texto, e um dia alguem
escreve ali o que nao devia. A prova e por **varrimento dos dados com
canarios**, em `db/tests_agr/test_llm_call_log.py`, e e a licao do KAM-026 — o
varrimento dele dava zero por procurar texto num campo `msgpack`.

## Particionada, com a particao por omissao e nada mais

`PARTITION BY RANGE (ts)`, como o §14 manda, e cria-se **so** a `DEFAULT`. E a
decisao que a emenda 1.9 tomou para o `events_log`: as particoes mensais tem
data no nome e nascem de um *job*, e uma migracao que as criasse fixava o
calendario. A `DEFAULT` e a rede para quando o *job* nao corre — e o *job* nao
existe, porque o agendador e o KAM-071, como no KAM-026.

**A RLS poe-se no pai e tambem na particao.** No pai porque e por la que a
aplicacao consulta; na particao porque o teste de catalogo X-05 do *gate* 6 olha
para **cada** tabela com `tenant_id`, e uma particao e uma tabela: sem isto, o
*gate* 6 encontrava uma tabela com `tenant_id` sem `FORCE` e falhava — com razao,
porque um `SELECT` dirigido a particao escapava a politica do pai.

## Sem receita de sementeira, pela razao da `tool_audit`

As receitas de `db/tests_isolamento/sementes.py` semeiam **e apagam**, e o
*trigger* `ENABLE ALWAYS` recusa o `DELETE`. Entra em `SEM_RECEITA_COM_RAZAO`,
ao lado da `audit_log` e da `tool_audit`, e o isolamento prova-se em
`db/tests_agr/test_llm_call_log.py` com as perguntas do X-04.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

#: O esquema de analitica. Dicionario §3.6, emenda 1.38.
#:
#: **As tres sao literais e nao derivadas umas das outras**, e isso nao e
#: desarrumacao: o *gate* 3b resolve `f-strings` sobre constantes de modulo, mas
#: nao resolve uma constante que seja **ela propria** uma f-string. Com
#: `TABELA = f"{ESQUEMA}.llm_call_log"`, nove `op.execute` desta revisao sairam
#: como `[ilegivel]` — o lint nao conseguia ler o SQL e por isso nao verificava
#: nome nenhum contra o dicionario.
ESQUEMA = "dat"

TABELA = "dat.llm_call_log"

#: A particao por omissao. Nome sem data, de proposito: as mensais nascem do
#: *job* da retencao (KAM-071) e tem data no nome.
PARTICAO = "dat.llm_call_log_default"

#: O dominio **fechado** de `resultado`. Ver a tabela na nota do modulo.
RESULTADOS = (
    "ok",
    "ok_fallback",
    "budget_exhausted",
    "timeout",
    "erro_fornecedor",
    "destino_negado",
)

#: Os papeis que o cliente expoe (dicionario §3.29). Lista **fechada** e nao
#: gramatica: ao contrario das *tools* da `0021`, os papeis nao crescem — o
#: `docs/tecnica/02` §13.2 fixa quatro. A mesma lista vive em `PAPEIS`, no
#: servico e no `tools/llm_config`, com teste de paridade.
PAPEIS_SQL = "'router', 'chat', 'vision', 'embed'"

#: O mesmo dominio, pronto a entrar no `CHECK`. **Literal e nao derivado de
#: `RESULTADOS`**, e isso tem razao: o *gate* 3b nao resolve uma chamada de
#: funcao dentro de um `op.execute`, e com `{_lista(RESULTADOS)}` o `CREATE
#: TABLE` inteiro saia como `[ilegivel]` — o lint nao lia nome nenhum daquela
#: instrucao, pelo que nao verificava nada dela contra o dicionario.
#:
#: Duas listas no mesmo ficheiro sao duas verdades a espera de divergir, e por
#: isso ha um teste que as confronta (`test_o_check_cita_os_seis_resultados`).
RESULTADOS_SQL = (
    "'ok', 'ok_fallback', 'budget_exhausted', 'timeout', "
    "'erro_fornecedor', 'destino_negado'"
)

#: As colunas que quem chama escreve. **Nao incluem `id` nem `ts`**, pela razao
#: da `0021`: o instante de um registo nao e do chamador e o `id` e de
#: identidade. E a mesma lista do `GRANT` e do `COLUNAS` do
#: `kamba_agr/llm/registo.py`; se divergirem, o `INSERT` rebenta por privilegio
#: e nao em silencio.
COLUNAS_DO_CHAMADOR = (
    "tenant_id",
    "trace_id",
    "vertical",
    "no_grafo",
    "papel",
    "graph_version",
    "modelo",
    "fornecedor",
    "tokens_in",
    "tokens_out",
    "tokens_cache",
    "custo_usd",
    "latencia_ms",
    "resultado",
)

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_AUDITORIA = "kamba_audit"
PAPEL_DE_LOTE = "kamba_batch"


def upgrade() -> None:
    # Sem `IF NOT EXISTS`, como a `0001` e a `0020`: se o esquema ja existir,
    # alguem o criou fora da cadeia e isso e para saber, nao para tolerar.
    op.execute(f"CREATE SCHEMA {ESQUEMA}")
    op.execute(
        f"COMMENT ON SCHEMA {ESQUEMA} IS "
        "'Analitica (KAM-030). Medida, nao estado de negocio; retencao por "
        "DROP de particao. Dicionario 3.6.'"
    )

    op.execute(
        f"""
        CREATE TABLE {TABELA} (
            id             bigint      GENERATED ALWAYS AS IDENTITY,
            ts             timestamptz NOT NULL DEFAULT now(),
            tenant_id      uuid        NOT NULL,
            -- `trace_id` do W3C: e o que liga esta linha aos logs e aos
            -- eventos (`docs/tecnica/06` §4). Gramatica e nao lista: o valor
            -- vem de quem chama e cresce com o trafego.
            trace_id       text        NOT NULL,
            -- Nulos nos dois: uma chamada pode nascer fora de um grafo (um
            -- *script* de provisionamento, uma avaliacao offline), e nesse caso
            -- nao ha vertical nem no.
            vertical       text,
            no_grafo       text,
            -- As duas colunas que o §14 nao tem. Ver a nota do modulo.
            papel          text        NOT NULL,
            graph_version  text,
            -- `por_decidir` ate o KAM-040 escolher: a coluna guarda o que o
            -- alias resolveu, seja o que for, e nao se valida contra uma lista
            -- — uma lista de modelos no DDL obrigava a uma revisao de base de
            -- dados por cada modelo novo, que e o argumento que a `0021`
            -- escreveu para o `tool`.
            modelo         text        NOT NULL,
            fornecedor     text        NOT NULL,
            -- Nulos quando nao houve chamada (`destino_negado`) ou quando o
            -- fornecedor nao devolveu contagem.
            tokens_in      integer,
            tokens_out     integer,
            tokens_cache   integer,
            -- Decimal exacto, nao unidade menor inteira. Ver a nota do modulo.
            custo_usd      numeric(12, 6),
            latencia_ms    integer,
            resultado      text        NOT NULL,
            CONSTRAINT llm_call_log_pkey PRIMARY KEY (id, ts),
            CONSTRAINT llm_call_log_resultado_ck
                CHECK (resultado IN ({RESULTADOS_SQL})),
            -- Lista **fechada**, e nao a gramatica de identificador que o
            -- `tool` e o `vertical` da `0021` levam. O argumento de la — «uma
            -- lista de permitidos obrigava a uma revisao de base de dados por
            -- cada tool nova» — nao se aplica: as *tools* crescem com o KAM-031
            -- e o KAM-035, e os papeis **nao crescem** (o `docs/tecnica/02`
            -- §13.2 fixa quatro). Com gramatica, o dicionario dizia quatro
            -- valores e esta coluna aceitava qualquer identificador: duas
            -- verdades sobre a mesma coluna, e o *gate* 3b apanhou-as.
            CONSTRAINT llm_call_log_papel_ck
                CHECK (papel IN ({PAPEIS_SQL})),
            -- Contagens e tempos nao sao negativos. Um `-1` como «nao sei»
            -- obrigava quem soma a conhecer a convencao; o nulo ja diz isso.
            CONSTRAINT llm_call_log_tokens_ck CHECK (
                (tokens_in IS NULL OR tokens_in >= 0)
                AND (tokens_out IS NULL OR tokens_out >= 0)
                AND (tokens_cache IS NULL OR tokens_cache >= 0)
            ),
            CONSTRAINT llm_call_log_custo_ck
                CHECK (custo_usd IS NULL OR custo_usd >= 0),
            CONSTRAINT llm_call_log_latencia_ck
                CHECK (latencia_ms IS NULL OR latencia_ms >= 0),
            -- **Uma recusa de destino nao tem custo nem tokens.** Sem isto,
            -- uma linha `destino_negado` com `custo_usd` preenchido afirmava
            -- que se pagou por uma chamada que nunca saiu de Angola — e o
            -- somatorio de custo por tenant passava a contar o que nao houve.
            CONSTRAINT llm_call_log_negado_sem_consumo CHECK (
                resultado <> 'destino_negado'
                OR (tokens_in IS NULL AND tokens_out IS NULL
                    AND tokens_cache IS NULL AND custo_usd IS NULL)
            )
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute(f"CREATE TABLE {PARTICAO} PARTITION OF {TABELA} DEFAULT")
    # As duas consultas que isto serve sao «o custo deste tenant neste mes»
    # (ADR-018, `v_tenant_cost_daily` do KAM-081) e a juncao da
    # `v_transfer_audit` do KAM-069. As duas filtram por tenant e por instante,
    # por essa ordem.
    op.execute(f"CREATE INDEX llm_call_log_tenant_ts_idx ON {TABELA} (tenant_id, ts)")

    _imutabilidade()
    _rls()
    _privilegios()


def _imutabilidade() -> None:
    """*Append-only*, nas tres camadas da `0006` e da `0021`.

    Uma linha de custo que se pudesse alterar nao era um registo de custo: era
    uma estimativa. E o `UPDATE` e precisamente o que faria desaparecer uma
    transferencia que ja aconteceu, que e o que o ADR-008 manda poder auditar.

    Os *triggers* vao no **pai** — ver a nota de baixo, que e o que uma medicao
    corrigiu.
    """
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {TABELA} FROM PUBLIC")
    op.execute(
        f"""
        CREATE FUNCTION {ESQUEMA}.llm_call_log_imutavel() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        BEGIN
          RAISE EXCEPTION
            'dat.llm_call_log e append-only: % recusado (KAM-030, ADR-008, ADR-018)',
            TG_OP
            USING ERRCODE = 'integrity_constraint_violation';
        END $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {ESQUEMA}.llm_call_log_imutavel() IS "
        "'Levanta excepcao em UPDATE e DELETE de dat.llm_call_log. "
        "SECURITY INVOKER: nao precisa de privilegio nenhum para recusar.'"
    )
    # **Os dois *triggers* vao no PAI, e isso e o que faz uma particao nova
    # nascer imutavel.** A primeira versao desta revisao pos o de `UPDATE`/
    # `DELETE` na particao e afirmou que «uma tabela particionada nao aceita
    # *trigger* de `TRUNCATE`». As duas coisas estavam erradas, e mediram-se
    # contra um PostgreSQL 18 real (`docs/evidencia/KAM-030-litellm.md` §6):
    #
    #   * `BEFORE UPDATE OR DELETE ... FOR EACH ROW` no pai **e aceite**, e
    #     morde tanto pelo pai como pela particao;
    #   * uma particao **nova herda-o** — e era precisamente essa a via que o
    #     *job* da retencao (KAM-071) ia abrir: `dat.llm_call_log_2027_01`
    #     nascia sem *trigger* e um `UPDATE` do dono reescrevia registo de custo
    #     e fazia desaparecer transferencias que o ADR-008 manda poder auditar;
    #   * `BEFORE TRUNCATE ... FOR EACH STATEMENT` no pai **tambem e aceite**.
    #
    # O que **nao** se herda e a RLS (medido: `false/false` numa particao nova),
    # e por isso ela continua no pai **e** na particao — e o KAM-071 tem de a
    # por nas mensais. Essa metade fica na divida **121**.
    #
    # Encontrado pela revisao adversarial (`docs/analises/ANALISE-32`, achado 15).
    op.execute(
        f"""
        CREATE TRIGGER llm_call_log_sem_update_nem_delete
          BEFORE UPDATE OR DELETE ON {TABELA}
          FOR EACH ROW EXECUTE FUNCTION {ESQUEMA}.llm_call_log_imutavel()
        """
    )
    op.execute(
        f"ALTER TABLE {TABELA} "
        "ENABLE ALWAYS TRIGGER llm_call_log_sem_update_nem_delete"
    )
    op.execute(
        f"""
        CREATE TRIGGER llm_call_log_sem_truncate
          BEFORE TRUNCATE ON {TABELA}
          FOR EACH STATEMENT EXECUTE FUNCTION {ESQUEMA}.llm_call_log_imutavel()
        """
    )
    op.execute(f"ALTER TABLE {TABELA} ENABLE ALWAYS TRIGGER llm_call_log_sem_truncate")
    op.execute(f"REVOKE ALL ON FUNCTION {ESQUEMA}.llm_call_log_imutavel() FROM PUBLIC")


def _rls() -> None:
    """Politica `tenant_iso` no pai **e** na particao (ADR-015).

    Aqui o `WITH CHECK` nao e redundante com o *append-only*: e o que impede o
    papel da aplicacao de escrever uma linha de custo no nome de outro tenant —
    o unico tipo de escrita que esta tabela aceita. E a razao da particao esta
    na nota do modulo: para o *gate* 6, uma particao e uma tabela.
    """
    rls.enable_tenant_rls("llm_call_log", schema=ESQUEMA)
    rls.enable_tenant_rls("llm_call_log_default", schema=ESQUEMA)


def _privilegios() -> None:
    """`INSERT` por coluna para o papel da aplicacao; leitura para quem audita.

    **O `kamba_app` escreve e nao le**, pela razao da `0021` e da `audit_log`:
    quem produz o registo nao e quem o audita, e um `SELECT` concedido ao
    processo que escreve e um caminho para o custo de outro tenant voltar a um
    turno. Quem le e o `kamba_audit` e o `kamba_batch`.

    **O `kamba_agr` nao ganha nada.** O KAM-026 deixou-o sem `USAGE` no
    `platform` de proposito, e o mesmo vale aqui: o papel que guarda o estado
    das conversas nao tem por onde chegar ao custo de ninguem.
    """
    op.execute(
        f"GRANT USAGE ON SCHEMA {ESQUEMA} TO "
        f"{PAPEL_DA_APP}, {PAPEL_DE_AUDITORIA}, {PAPEL_DE_LOTE}"
    )
    op.execute(
        f"GRANT INSERT ({', '.join(COLUNAS_DO_CHAMADOR)}) ON {TABELA} TO {PAPEL_DA_APP}"
    )
    op.execute(f"GRANT SELECT ON {TABELA} TO {PAPEL_DE_AUDITORIA}")
    # O lote **le** e nao apaga: a retencao desta tabela e um `DROP` de
    # particao (`06` §9.3), que exige ser dono e nao um `DELETE` — e o dono e o
    # `kamba_migrator`. Sem `DELETE`, pela razao da `0019` e da `0020`: um papel
    # de lote que pudesse apagar linhas de um registo *append-only* desfazia a
    # imutabilidade por privilegio.
    op.execute(f"GRANT SELECT ON {TABELA} TO {PAPEL_DE_LOTE}")


def downgrade() -> None:
    # Destrutivo por natureza: leva o registo de custo e de transferencia todo.
    # Sem `CASCADE`, como a `0020`: um objecto criado no `dat` fora desta
    # revisao faz isto **falhar**, que e melhor do que o levar atras.
    rls.disable_tenant_rls("llm_call_log_default", schema=ESQUEMA)
    rls.disable_tenant_rls("llm_call_log", schema=ESQUEMA)
    op.execute(f"DROP TABLE {PARTICAO}")
    op.execute(f"DROP TABLE {TABELA}")
    op.execute(f"DROP FUNCTION IF EXISTS {ESQUEMA}.llm_call_log_imutavel()")
    op.execute(f"DROP SCHEMA {ESQUEMA}")
