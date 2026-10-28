"""KAM-114: a `platform.draft_decisions` e a vista das metricas do concierge.

## O concierge nao e um quinto modo, e por isso esta tabela nao mexe em modos

O KAM-018 recusa transicoes fora da tabela de `docs/tecnica/01` §10.2, e os
quatro modos (`bot`, `dono`, `humano`, `pausada`) ficam como estao. O concierge
e uma **politica por tenant** aplicada a conversa em modo `bot`: o no de envio e
substituido por um pedido de aprovacao. Esta revisao nao toca na
`platform.conversations` nem no `SQL_MUDAR_MODO`.

**E a politica tambem nao nasce aqui.** Ela e uma linha de
`platform.entitlements` com `modulo = 'concierge'` — a coluna tem `CHECK` de
**forma** (`^[a-z][a-z0-9_]*$`) e nao de dominio desde a `0001`, e o dicionario
§3.7 escreve por extenso que «um modulo novo entra por configuracao e nao por
migracao» (ADR-012). O leitor e o `check_entitlement` do KAM-009, que **falha
fechado**, e a *cache* tem TTL de 60 s: e o que faz o criterio 8 («desactivar a
politica repoe o envio automatico **sem reiniciar o AGR**») ser uma propriedade
medivel e nao uma promessa.

## `pendente` nao e um valor de `decisao`: e a ausencia de decisao

O criterio 2 pede um *compare-and-set* `pendente -> decidido` e o criterio 6
fixa `decisao` em **cinco** valores — `aprovado`, `editado`, `rejeitado`,
`expirado`, `substituido` — e `pendente` **nao esta entre eles**. As duas coisas
conciliam-se com uma coluna e nao com duas:

* `decisao IS NULL` **e** o estado `pendente`;
* o CAS e `SET decisao = $x ... WHERE draft_id = $1 AND decisao IS NULL`, pelo
  que so o primeiro de dois cliques concorrentes casa linha.

**A alternativa era uma coluna `estado` com seis valores**, e recusa-se pela
razao que o dicionario §3.32 escreveu para o `handoffs.status`: chamar `decisao`
a um rascunho que ainda nao foi decidido dizia que um rascunho que acabou de
nascer ja tem uma. Duas colunas a codificar o mesmo facto sao duas verdades a
espera de divergir, e aqui nao ha nada que a segunda diga que `decisao IS NULL`
nao diga.

## Sem texto, e isso e o produto e nao arrumacao

Nenhuma das treze colunas pode conter o texto do rascunho, a mensagem do cliente
ou a edicao do operador. O texto vive **so** no checkpointer (`lg`, KAM-026, com
a retencao de conversa de `docs/tecnica/08` §7.1) e no HND. O que fica aqui sao
identificadores, um dominio fechado, um booleano e tres numeros.

**Mas «nao ha coluna de texto» nao e prova de «nao ha texto»**, e e a licao que
a `0023` escreveu: o `thread_id` e o `turn_id` sao `text`, e um dia alguem
escreve ali o que nao devia. A prova e por varrimento dos dados com canarios, em
`db/tests_agr/test_draft_decisions.py`.

**O `graph_version` tem `CHECK` de forma e os outros dois nao**, e a assimetria
tem razao: ele e o unico dos tres que **sai** na exportacao do criterio 7, pelo
que um campo livre ali era texto livre a atravessar para fora. Os outros dois
nunca saem (sao `identificador` na classificacao do `golden_candidates.py`) e
ficam sem forma porque um `thread_id` e um `wamid` nao tem uma que se possa
fixar sem partir o que o KAM-008 e a Meta decidem.

**O `motivo` e dominio fechado e nao texto livre**, e e essa a diferenca que
conta: a `handoffs.motivo` e texto livre (a `handoffs_motivo_ck` so exige
nao-vazio) porque quem a escreve e o grafo; aqui quem escreve e um operador
humano a carregar num botao, e um campo livre numa mao humana e por onde o nome
de um cliente entra numa tabela que jura nao ter nenhum.

## O custo **nao** e coluna desta tabela, e as duas razoes mediram-se

O criterio 6 manda gravar «custo da chamada (de `llm_call_log` por `turn_id`)».
Nao se faz, e nao por escolha:

1. **a `dat.llm_call_log` nao tem `turn_id`.** As dezesseis colunas da `0023`
   trazem `trace_id` — o `trace_id` do W3C de `docs/tecnica/06` §4 —, e o
   `turn_id` deste repositorio e o `wamid` (dicionario §3.24,
   `ContextoDoTurno.turn_id`). Sao dois conceitos e nao dois nomes do mesmo;
2. **o `kamba_app` nao tem `SELECT` nessa tabela**, e isso e uma barreira
   deliberada do KAM-030: «quem produz o registo nao e quem o audita, e um
   `SELECT` concedido ao processo que escreve e um caminho para o custo de outro
   tenant voltar a um turno». Quem le e o `kamba_audit` e o `kamba_batch`.

Logo o AGR **nao pode** ler o custo no instante da decisao, e preencher a coluna
exigia retirar aquele privilegio — e *minimo* nunca e retirar uma barreira. O
**A vista nao junta a `dat.llm_call_log`, e isso e escolha e nao esquecimento.**
Um `LEFT JOIN ... ON l.trace_id = d.turn_id` compilava e devolvia sempre zero
linhas: sao dois identificadores diferentes, e uma juncao que nunca casa e pior
do que juncao nenhuma — da `NULL` com cara de «ainda nao houve custo» em vez de
«esta coluna nao tem chave». Por isso a vista nao tem coluna de custo.

O criterio 6 fica **parcial** por esta clausula, com a decisao devolvida a quem o
escreveu. As tres saidas, e nenhuma se toma aqui: dar `SELECT` da
`dat.llm_call_log` ao `kamba_app` (retira a barreira do KAM-030), acrescentar
`turn_id` aquela tabela — particionada e *append-only* — e preenche-lo em cada
chamada (DDL de outro ticket), ou correlacionar `trace_id` e `turn_id` num sitio
onde os dois existam.

(E hoje qualquer das tres devolvia `NULL` de qualquer maneira: o `custo_usd` da
`0023` e nulo enquanto o modelo for `por_decidir`, que e o que a propria nota de
entrega do KAM-030 registou.)

## As metricas sao uma vista, porque a etiqueta nao as aceita

O criterio 6 pede «metricas por tenant e `graph_version`». **Nenhum dos dois
pode ser etiqueta de metrica**, e mediu-se: a gramatica do
`kamba_core.ten.metricas` e `^[a-z][a-z0-9_]{1,62}$`, um UUID tem hifenes e
`1.1.0` comeca por digito e tem pontos — as duas chamadas levantam
`EtiquetaInvalida`. E uma serie por tenant explode a cardinalidade e
re-identifica (`OBS-I`).

E a mesma tensao que as emendas 1.38, 1.39 e 1.41 resolveram tres vezes da
mesma maneira: **a desagregacao faz-se nas colunas e le-se por consulta**. Por
isso as quatro medidas do criterio 6 vivem na `platform.v_draft_metrics`, por
`(tenant_id, graph_version)`, que e o que «alimentam H6 e H7 de KAM-109 **sem
recalculo**» pede — uma consulta e nao uma reconstrucao a partir de conversas.
A serie Prometheus que fica (`agr_draft_decisao_total{decisao}`) leva so o
dominio fechado, que casa a gramatica.

`security_invoker = true` **nao e opcional**: o `verificar_vistas` do *gate* 6
recusa qualquer vista sem ele, e sem ele a vista corria com os privilegios do
dono e via as linhas de todos os tenants.

## A receita de isolamento poe o canario no `turn_id`

O X-03 semeia o **mesmo** canario nos dois tenants e exige que cada um veja so o
seu, pelo que o canario tem de ir numa coluna que os dois possam ter igual. As
candidatas caem uma a uma: o `draft_id` e chave primaria **global** (como o
`handoff_id`, e a receita do `_handoff` paga essa licao por escrito), o `motivo`
e dominio fechado e o `CHECK` recusa um canario, o `thread_id` leva o
`tenant_id` dentro, e o `graph_version` passou a ter `CHECK` de forma SemVer —
ver acima. Fica o `turn_id`, que e `text`, so exige nao-vazio, e e
legitimamente igual nos dois tenants num ensaio.

**A coluna alteravel e o `motivo` e nao a `decisao`**, e a primeira versao desta
revisao escolheu mal. O `draft_decisions_decidido_ck` exige que `decisao` e
`decidido_at` sejam as duas nulas ou as duas nao-nulas, pelo que um
`SET decisao = <valor>` **sozinho** — que e o que o X-04 faz — viola a restricao
**para qualquer valor**, e nao so para o `editado` que a receita acautelava. Um
`UPDATE` que rebenta com `23514` nao mede isolamento nenhum: mede a restricao.
O `motivo` escreve-se sozinho numa linha pendente sem violar nada, e e dominio
fechado, que e o que um teste de escrita cruzada precisa. Apanhado pela revisao
adversarial, que o mediu contra um PostgreSQL 18.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

TABELA = "platform.draft_decisions"

VISTA = "platform.v_draft_metrics"

#: O dominio **fechado** de `decisao`, os cinco do criterio 6. O `pendente`
#: **nao** esta aqui, e e a nota do modulo: ele e `decisao IS NULL`.
DECISOES = (
    "aprovado",
    "editado",
    "rejeitado",
    "expirado",
    "substituido",
)

#: O mesmo dominio, pronto a entrar no `CHECK`. **Literal e nao derivado de
#: `DECISOES`**, pela razao da `0023`: o *gate* 3b nao resolve uma chamada de
#: funcao dentro de um `op.execute`, e com `{_lista(DECISOES)}` o `CREATE TABLE`
#: inteiro saia como `[ilegivel]` — o lint nao lia nome nenhum daquela
#: instrucao. Ha teste que confronta as duas listas
#: (`test_o_check_cita_as_cinco_decisoes`).
DECISOES_SQL = "'aprovado', 'editado', 'rejeitado', 'expirado', 'substituido'"

#: Os motivos de lista fechada do criterio 4. **Proposta**: o bloco diz «a
#: definir com o operador do Piloto», e calibra-se no KAM-109.
#:
#: Dominio fechado e nao texto livre — ver a nota do modulo. Cresce com uma
#: revisao de base de dados, que e a licao que a `0022` pagou ao fazer crescer o
#: `tool_audit.error_code` de dez para onze.
MOTIVOS = (
    "tom",
    "preco_errado",
    "stock_errado",
    "fora_de_ambito",
    "deveria_ir_a_humano",
    "outro",
)

MOTIVOS_SQL = (
    "'tom', 'preco_errado', 'stock_errado', 'fora_de_ambito', "
    "'deveria_ir_a_humano', 'outro'"
)

#: As colunas que o papel da aplicacao insere. **Nao incluem `criado_at`** (o
#: instante de um registo nao e do chamador, pela razao da `0021` e da `0023`)
#: nem nenhuma das colunas de decisao, que nascem nulas e entram pelo CAS.
COLUNAS_DA_INSERCAO = (
    "draft_id",
    "tenant_id",
    "thread_id",
    "turn_seq",
    "turn_id",
    "graph_version",
)

#: As colunas que o CAS escreve. `GRANT UPDATE` por coluna, como a `0011` fez ao
#: `handoffs (status, resumed_at)`: sem isto o papel da aplicacao podia
#: reescrever o `tenant_id` de uma linha ja gravada.
COLUNAS_DO_CAS = (
    "decisao",
    "motivo",
    "razao_edicao",
    "edicao_numero_livre",
    "latencia_ms",
    "decidido_at",
)

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_AUDITORIA = "kamba_audit"
PAPEL_DE_LOTE = "kamba_batch"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {TABELA} (
            -- `sha256(thread_id:turn_seq)` — estavel entre re-execucoes do no,
            -- que e o criterio 2 («re-executar 5x cria 1 rascunho»). Chave
            -- primaria e nao indice unico: a idempotencia e da base e nao de um
            -- contador deste processo, que o reinicio perdia e a segunda
            -- replica nao via.
            draft_id            text        NOT NULL,
            tenant_id           uuid        NOT NULL,
            -- `tenant_id:contact_id` (dicionario §3.1). Nao e telefone: o
            -- `contact_id` e o substituto (ADR-010).
            thread_id           text        NOT NULL,
            -- O ordinal do turno na conversa, que e a segunda metade do
            -- `draft_id`. Guarda-se porque sem ele o `draft_id` e irreversivel
            -- e nao se sabe de que turno a linha fala.
            turn_seq            integer     NOT NULL,
            -- O `turn_id` do turno, que neste repositorio **e o `wamid`**
            -- (dicionario §3.24, `ContextoDoTurno.turn_id`). Guarda-se para
            -- que a linha diga de que turno fala sem depender do `draft_id`,
            -- que e irreversivel. **Nao e a chave do custo**, e nao ha: ver a
            -- nota do modulo.
            turn_id             text        NOT NULL,
            -- **Com `CHECK` de forma**, ao contrario da `0023`, e a razao e o
            -- criterio 7. Esta coluna **sai na exportacao** do
            -- `golden-candidates`, e sem forma ela era um campo de texto livre
            -- a sair — o que torna falsa a afirmacao «esta tabela nao tem
            -- coluna de texto livre» em que a prova de esquema assenta.
            -- Apanhado pela revisao adversarial.
            --
            -- SemVer, que e o que o `VERSAO_DO_GRAFO` escreve. O canario do
            -- X-03 mudou-se por isso para o `turn_id` — ver a receita em
            -- `db/tests_isolamento/sementes.py`.
            graph_version       text
                                CONSTRAINT draft_decisions_graph_version_ck
                                CHECK (graph_version IS NULL
                                       OR graph_version ~ '^[0-9]+[.][0-9]+[.][0-9]+$'),
            -- **Nula e o estado `pendente`.** Ver a nota do modulo.
            decisao             text,
            motivo              text,
            -- Distancia normalizada 0-1 entre o rascunho e a edicao (criterio
            -- 6). `numeric` e nao virgula flutuante, pela convencao da casa.
            razao_edicao        numeric(4, 3),
            -- O sinal do criterio 4: a edicao trouxe um numero que nao e *fact*
            -- do turno. Booleano e nao motivo: o `motivo` e a razao que o
            -- operador deu e este e uma condicao que o sistema detectou, e
            -- somar as duas num campo perdia a que nao foi escolhida.
            edicao_numero_livre boolean     NOT NULL DEFAULT false,
            latencia_ms         integer,
            criado_at           timestamptz NOT NULL DEFAULT now(),
            decidido_at         timestamptz,
            CONSTRAINT draft_decisions_pkey PRIMARY KEY (draft_id),
            CONSTRAINT draft_decisions_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT draft_decisions_decisao_ck
                CHECK (decisao IS NULL OR decisao IN ({DECISOES_SQL})),
            CONSTRAINT draft_decisions_motivo_ck
                CHECK (motivo IS NULL OR motivo IN ({MOTIVOS_SQL})),
            -- **O par `decisao`/`decidido_at` nao pode divergir.** Uma linha
            -- decidida sem instante nao responde a «quanto tempo esperou o
            -- operador», e uma linha com instante e sem decisao afirma que
            -- alguem decidiu e nao diz o que.
            CONSTRAINT draft_decisions_decidido_ck CHECK (
                (decisao IS NULL AND decidido_at IS NULL)
                OR (decisao IS NOT NULL AND decidido_at IS NOT NULL)
            ),
            -- A distancia e **a razao de ser** do `editado` e nao faz sentido
            -- em mais nenhum valor: sem isto, um `rejeitado` com
            -- `razao_edicao = 0,4` dizia que houve uma edicao que nao houve, e
            -- o `draft_edit_ratio_p50` da vista contava-a.
            CONSTRAINT draft_decisions_razao_edicao_ck CHECK (
                (decisao = 'editado' AND razao_edicao IS NOT NULL)
                OR (decisao IS DISTINCT FROM 'editado' AND razao_edicao IS NULL)
            ),
            CONSTRAINT draft_decisions_razao_dominio_ck CHECK (
                razao_edicao IS NULL OR (razao_edicao >= 0 AND razao_edicao <= 1)
            ),
            -- **So uma edicao pode ter trazido um numero livre.** Um
            -- `rejeitado` com o sinal a `true` punha o criterio 4 a contar
            -- edicoes que nao existem.
            CONSTRAINT draft_decisions_numero_livre_ck CHECK (
                NOT edicao_numero_livre OR decisao = 'editado'
            ),
            CONSTRAINT draft_decisions_latencia_ck
                CHECK (latencia_ms IS NULL OR latencia_ms >= 0),
            -- Um `turn_seq` negativo nao e um turno.
            CONSTRAINT draft_decisions_turn_seq_ck CHECK (turn_seq >= 0),
            -- As tres formas. O `draft_id` e sha256 em hexadecimal, como o
            -- `handoff_id`; os outros dois nao podem ser vazios, que e a forma
            -- do `token_ref` da `0001`.
            CONSTRAINT draft_decisions_draft_id_ck
                CHECK (draft_id ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT draft_decisions_thread_id_ck CHECK (btrim(thread_id) <> ''),
            CONSTRAINT draft_decisions_turn_id_ck CHECK (btrim(turn_id) <> '')
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {TABELA} IS "
        "'Decisoes do modo concierge (KAM-114). SEM TEXTO: o rascunho vive no "
        "checkpointer (lg) e no HND. decisao IS NULL e o estado pendente. "
        "Dicionario 3.34.'"
    )

    # As duas consultas que isto serve. A primeira e a varredura dos prazos e a
    # da substituicao, que procuram **pendentes** por idade: indice **parcial**
    # em `decisao IS NULL`, porque as decididas nao se varrem outra vez e um
    # indice total crescia com elas para sempre.
    op.execute(
        f"CREATE INDEX draft_decisions_pendentes_idx ON {TABELA} (criado_at) "
        "WHERE decisao IS NULL"
    )
    # A segunda e a vista das metricas, que agrupa por tenant e versao do grafo.
    op.execute(
        f"CREATE INDEX draft_decisions_tenant_versao_idx ON {TABELA} "
        "(tenant_id, graph_version)"
    )
    # E a terceira serve a substituicao por *echo* do dono ou por handoff, que
    # chega com o `thread_id` e nao com o `draft_id` (criterio 5).
    op.execute(
        f"CREATE INDEX draft_decisions_thread_idx ON {TABELA} (thread_id) "
        "WHERE decisao IS NULL"
    )

    _metricas()
    _rls()
    _privilegios()


def _metricas() -> None:
    """As quatro medidas do criterio 6, por `(tenant_id, graph_version)`.

    Os nomes sao os do bloco: `draft_approved_ratio`, `draft_edit_ratio_p50`,
    `draft_decision_latency_s` (p50 e p90) e o custo por rascunho aprovado.

    **A latencia em segundos e nao em milissegundos**, porque e o nome que o
    criterio escreve (`draft_decision_latency_s`); a coluna guarda `ms` por ser
    inteira e a vista divide. Guardar segundos fraccionarios na coluna perdia
    precisao sem ganhar nada.

    **Nao ha coluna de custo** — ver a nota do modulo: nao existe chave entre
    esta tabela e a `dat.llm_call_log`, e o `kamba_app` nao tem leitura nela.
    Uma coluna sempre `NULL` aqui dizia «ainda nao houve custo» sobre o que nao
    tem como ser lido, que e a linha que o KAM-025 recusou escrever para o
    `degraded_turns`.
    """
    op.execute(
        f"""
        CREATE VIEW {VISTA} WITH (security_invoker = true) AS
        SELECT
            d.tenant_id,
            d.graph_version,
            count(*)                                         AS draft_total,
            count(*) FILTER (WHERE d.decisao IS NULL)         AS draft_pendentes,
            -- As razoes sao sobre as **decididas**: incluir pendentes no
            -- denominador fazia a taxa de aprovacao descer so por haver
            -- rascunhos a espera, que nao e informacao sobre a qualidade do
            -- rascunho. `NULLIF` porque um tenant sem decisoes nao tem taxa —
            -- e nao tem taxa **zero**.
            (count(*) FILTER (WHERE d.decisao IN ('aprovado', 'editado')))::numeric
                / NULLIF(count(*) FILTER (WHERE d.decisao IS NOT NULL), 0)
                                                             AS draft_approved_ratio,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY d.razao_edicao)
                                                             AS draft_edit_ratio_p50,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY d.latencia_ms / 1000.0)
                                                      AS draft_decision_latency_s_p50,
            percentile_cont(0.9) WITHIN GROUP (ORDER BY d.latencia_ms / 1000.0)
                                                      AS draft_decision_latency_s_p90
        FROM platform.draft_decisions d
        GROUP BY d.tenant_id, d.graph_version
        """
    )
    op.execute(
        f"COMMENT ON VIEW {VISTA} IS "
        "'Metricas do concierge por tenant e graph_version (KAM-114, criterio "
        "6). Nem tenant_id nem graph_version podem ser etiqueta de metrica "
        "(gramatica de kamba_core.ten.metricas), e esta biblioteca nao tem "
        "histogramas: a desagregacao e os percentis leem-se aqui. SEM custo: "
        "ver a nota da revisao 0024.'"
    )


def _rls() -> None:
    """Politica `tenant_iso` (ADR-015).

    O `WITH CHECK` e o que impede o papel da aplicacao de gravar a decisao de um
    rascunho no nome de outro tenant.

    **E nao chega sozinho**, e a licao e do KAM-034: o `draft_id` e
    `sha256(thread_id:turn_seq)` e portanto irreversivel, pelo que um `draft_id`
    do **mesmo** tenant e de outro contacto passava o predicado do `tenant_id` e
    decidia o rascunho de outra pessoa. O CAS leva por isso o `thread_id` no
    predicado, do lado do codigo (`db/tests_agr/test_draft_decisions.py`).
    """
    rls.enable_tenant_rls("draft_decisions")


def _privilegios() -> None:
    """`INSERT` e `UPDATE` por coluna para a aplicacao; leitura para quem audita.

    **O `kamba_app` le**, ao contrario da `0023`: o CAS tem de saber se a linha
    existe e a varredura dos prazos tem de a encontrar. O que o isolamento
    garante e que ele le **as do seu contexto**, pela politica.

    **Nao tem `DELETE`.** A retencao desta tabela e do `kamba_batch` (KAM-071) e
    uma decisao gravada nao se apaga a pedido de quem a produziu — a mesma razao
    pela qual a `0005` nao deu `DELETE` ao consumidor da DLQ.

    **O `kamba_agr` nao ganha nada**, como na `0023` e na `0020`: o papel que
    guarda o estado das conversas nao tem por onde chegar as decisoes de
    ninguem.
    """
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(COLUNAS_DA_INSERCAO)}) "
        f"ON {TABELA} TO {PAPEL_DA_APP}"
    )
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DO_CAS)}) ON {TABELA} TO {PAPEL_DA_APP}"
    )
    op.execute(f"GRANT SELECT ON {TABELA} TO {PAPEL_DE_AUDITORIA}")
    # O lote le **e apaga**: e ele que leva a retencao (KAM-071) e e ele que
    # atravessa tenants na varredura dos prazos, pela razao do
    # `agr_handoff_prazos` do KAM-034 — com contexto de um tenant a RLS devolvia
    # so os rascunhos desse.
    op.execute(f"GRANT SELECT, UPDATE, DELETE ON {TABELA} TO {PAPEL_DE_LOTE}")
    # A vista herda a RLS da tabela pelo `security_invoker`; o privilegio e
    # preciso de qualquer maneira. Quem le metricas e quem audita e quem faz
    # lote, nao o processo que escreve.
    op.execute(f"GRANT SELECT ON {VISTA} TO {PAPEL_DE_AUDITORIA}, {PAPEL_DE_LOTE}")


def downgrade() -> None:
    # A vista primeiro: ela depende da tabela, e um `DROP TABLE` sem ela saia
    # com `dependent objects still exist` ou, com `CASCADE`, levava-a em
    # silencio. Sem `CASCADE`, como a `0023` e a `0020`.
    op.execute(f"DROP VIEW {VISTA}")
    rls.disable_tenant_rls("draft_decisions")
    op.execute(f"DROP TABLE {TABELA}")
