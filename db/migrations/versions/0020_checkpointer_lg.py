"""KAM-026: o esquema `lg`, as duas tabelas do checkpointer e o papel que as usa.

## Porque e que o esquema e o papel nascem aqui, e nao no `platform`

O `docs/tecnica/02` §12 fixa-o: «Mesmo Postgres 18 (ADR-006), **esquema `lg`**,
separado do `platform` e do Medusa; *role* proprio». O dicionario §3.6 ja tem o
`lg` como nome canonico e o §3.24 ja diz que e este ticket que o cria.

A razao e de isolamento e nao de arrumacao. O estado de uma conversa contem
**texto de clientes** (`docs/tecnica/02` §12, «Backups»), e o papel que o le nao
precisa de ver mais nada: um `kamba_agr` sem `USAGE` no `platform` nao tem como
chegar aos `contacts` nem aos `orders`, aconteca o que acontecer ao codigo que o
usa. E a mesma ideia do `kamba_resolver` da `0006`, levada ao esquema.

## As tabelas sao duas, e o *saver* oficial tem tres

O `langgraph-checkpoint-postgres` separa os valores dos canais num
`checkpoint_blobs` proprio, para nao reescrever o estado inteiro a cada passo.
Aqui o estado e a **janela recortada** do §12 — ultimas K mensagens mais o
`summary` —, pelo que o estado inteiro e pequeno e serializa-se numa coluna. Uma
tabela a menos e menos codigo, menos um `JOIN` em cada leitura e menos uma
hipotese de os tres ficarem a discordar.

**O que esta escolha custa, e fica dito:** um grafo que use `DeltaChannel`
guarda so um sentinela no `channel_values` e reconstroi o valor andando a cadeia
de escritas para tras (`get_delta_channel_history` do `BaseCheckpointSaver`).
Nao se implementa aqui — nenhum grafo existe ainda, e e o KAM-031 que decide se
algum usa canais delta. O `BaseCheckpointSaver` levanta `NotImplementedError`
nesse caminho, que e o comportamento certo: melhor levantar do que reconstruir
um estado vazio em silencio.

## O `thread_id` e `text` e nao tem `CHECK` de forma

O criterio 2 pede `^<uuid>:<uuid>$`. A forma e imposta a **entrada**, no
`contexto.py` do KAM-025 (`thread_id_de` e o `thread_id_incoerente` do
`ler_invocacao`), e nao aqui, por duas razoes. O `thread_id` do LangGraph e
`text` livre no contrato da biblioteca, e um `CHECK` nesta tabela recusava um
dia uma invocacao legitima de um grafo que nao e nosso. E o varrimento do
criterio 2 — que corre sobre `lg.*` e conta as ocorrencias — prova a forma onde
ela importa: nos dados, nao no dominio.

## A RLS nao se aplica aqui, e isso e uma decisao a registar

O ADR-015 manda `FORCE ROW LEVEL SECURITY` «em todas as tabelas com
`tenant_id`». Estas nao tem: a chave e o `thread_id`, e o `tenant_id` vive **la
dentro**, como prefixo (`{tenant_id}:{contact_id}`, dicionario §3.1). Nao e
contradicao do ADR — e a ausencia da condicao que ele nomeia —, mas tambem nao
pode ficar por dizer, porque remove a barreira que todas as outras tabelas tem.

O isolamento desta tabela assenta em tres coisas, e nenhuma e a RLS:

1. o prefixo do `thread_id`, construido **so** do estado validado
   (`contexto.py` L203) e conferido contra a invocacao antes de qualquer turno;
2. o papel proprio, que nao tem `USAGE` no `platform` e por isso nao consegue
   juntar estas linhas a nada;
3. o ensaio cruzado, que mede 1 e 2 contra a base.

Por isso o `ci/rls_exceptions.yaml` nao leva linha nenhuma: aquele ficheiro e
para tabelas **com** `tenant_id` que dispensem a politica, e uma excepcao morta
falha o *gate* 6.

## O `downgrade` apaga o esquema, e isso e destrutivo

`DROP SCHEMA lg` leva o estado de todas as conversas em curso. E destrutivo por
natureza e nao ha forma de o nao ser: o inverso de criar o esquema e apaga-lo.
Sem `CASCADE`, como a `0001`: se alguem criou um objecto no `lg` fora desta
revisao, o `downgrade` **falha** em vez de o levar atras, e falhar e o que se
quer — um `CASCADE` aqui apagava o que ninguem mandou apagar.
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

#: O esquema do checkpointer. Dicionario §3.6.
ESQUEMA = "lg"

#: O papel que le e escreve o `lg`, e **so** o `lg`. Criado pelo
#: `db/bootstrap.py` como os outros seis — `CREATE ROLE` nao aparece em revisao
#: nenhuma, porque um papel sobrevive ao `downgrade base` e o Alembic nao o
#: devia poder remover.
PAPEL_DO_AGR = "kamba_agr"

#: O papel das varreduras. A retencao do `lg` corre com ele pela mesma razao que
#: a dos avisos: e `BYPASSRLS` e corre fora de qualquer pedido.
PAPEL_DO_LOTE = "kamba_batch"


def upgrade() -> None:
    # O esquema. Sem `IF NOT EXISTS`, como a `0001`: se ele ja existir, alguem
    # o criou fora da cadeia e isso e para saber, nao para tolerar.
    op.execute(f"CREATE SCHEMA {ESQUEMA}")

    # ----------------------------------------------------------- checkpoints
    #
    # As colunas sao o `CheckpointTuple` do `BaseCheckpointSaver`, com os nomes
    # da interface. O `channel` do `checkpoint_writes` fica em **ingles** de
    # proposito: `canal` ja e um nome canonico — o canal de WhatsApp do §3.6 —
    # e dois conceitos com o mesmo nome e o defeito que o dicionario existe
    # para fechar.
    op.execute(
        f"""
        CREATE TABLE {ESQUEMA}.checkpoints (
            thread_id            text        NOT NULL,
            -- O *namespace* de um subgrafo. Cadeia vazia no grafo de topo, que
            -- e o que o LangGraph passa quando nao ha subgrafo — e por isso o
            -- `DEFAULT ''` e nao um nulo: entra na chave primaria.
            checkpoint_ns        text        NOT NULL DEFAULT '',
            checkpoint_id        text        NOT NULL,
            -- Nulo no primeiro checkpoint de uma thread. E a cadeia que o
            -- `parent_config` do `CheckpointTuple` devolve.
            parent_checkpoint_id text,
            -- O discriminador do serializador (`JsonPlusSerializer`): ele
            -- devolve o par (tipo, octetos) e precisa dos dois para desfazer.
            type                 text        NOT NULL,
            -- O `Checkpoint` inteiro, `channel_values` incluidos. Ver a nota do
            -- modulo sobre as duas tabelas.
            checkpoint           bytea       NOT NULL,
            -- **Dois discriminadores e nao um.** Os metadados passam pelo mesmo
            -- serializador mas sao outro objecto, e o tipo que ele devolve para
            -- um deles nao e garantidamente o do outro. Guardar um so e contar
            -- com uma coincidencia que a interface nao promete.
            metadata_type        text        NOT NULL,
            metadata             bytea       NOT NULL,
            criado_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT checkpoints_pkey
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    # A varredura da retencao pergunta «que threads nao escrevem desde
    # quando?», que em SQL e `GROUP BY thread_id HAVING max(criado_at) < %s`.
    #
    # **O indice e `(thread_id, criado_at)` e nao `(criado_at)`.** A primeira
    # versao tinha so a segunda coluna e afirmava que sem ela «era um `seq
    # scan` por passagem» — falso: um indice so no `criado_at` nao serve um
    # agregado por `thread_id`, e o planeador lia a tabela toda na mesma. Com
    # as duas pela ordem certa, a agregacao sai do indice. Achado da revisao
    # adversarial.
    op.execute(
        f"CREATE INDEX checkpoints_thread_criado_idx "
        f"ON {ESQUEMA}.checkpoints (thread_id, criado_at)"
    )

    # ------------------------------------------------------ checkpoint_writes
    #
    # As escritas pendentes de uma tarefa que ficou a meio: e o que o
    # `pending_writes` do `CheckpointTuple` devolve, e o que faz um turno
    # repetido nao duplicar efeitos (criterio 5).
    op.execute(
        f"""
        CREATE TABLE {ESQUEMA}.checkpoint_writes (
            thread_id     text        NOT NULL,
            checkpoint_ns text        NOT NULL DEFAULT '',
            checkpoint_id text        NOT NULL,
            task_id       text        NOT NULL,
            -- **Guarda-se porque entra na ordem, nao porque se consulta.** O
            -- `writes_sort_key` do `BaseCheckpointSaver` e
            -- `(task_path, task_id, idx)`, e o `aget_tuple` tem de devolver as
            -- escritas nessa ordem: a propria interface avisa que «an
            -- order-sensitive reducer rebuilds a different value than the run
            -- produced» se nao forem. Cadeia vazia e o que o `aput_writes`
            -- passa por omissao.
            task_path     text        NOT NULL DEFAULT '',
            idx           integer     NOT NULL,
            channel       text        NOT NULL,
            type          text        NOT NULL,
            blob          bytea       NOT NULL,
            criado_at     timestamptz NOT NULL DEFAULT now(),
            -- A chave e (thread, ns, checkpoint, tarefa, ordem). E ela que
            -- torna o `put_writes` idempotente: a mesma tarefa a repetir a
            -- mesma escrita cai no mesmo sitio em vez de criar outra linha.
            CONSTRAINT checkpoint_writes_pkey
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx),
            CONSTRAINT checkpoint_writes_idx_ck CHECK (idx >= 0)
        )
        """
    )

    # ---------------------------------------------------------------- acessos
    #
    # **O `kamba_agr` nao leva `USAGE` no `platform`, e e esse o criterio 4.**
    # Nao ha nada a revogar aqui: ele nunca o teve, e um papel sem `USAGE` no
    # esquema nao chega as tabelas mesmo com privilegio nelas. O acesso ao
    # Medusa fica de fora pelo mesmo mecanismo um nivel acima: o Medusa e uma
    # **base** separada (`kamba_medusa`) e o `bootstrap.py` so da `CONNECT` na
    # base da plataforma.
    op.execute(f"GRANT USAGE ON SCHEMA {ESQUEMA} TO {PAPEL_DO_AGR}, {PAPEL_DO_LOTE}")
    # O `UPDATE` e para o `put_writes`: uma tarefa que repete uma escrita faz
    # `ON CONFLICT DO UPDATE` em vez de uma linha nova.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON {ESQUEMA}.checkpoints, {ESQUEMA}.checkpoint_writes TO {PAPEL_DO_AGR}"
    )
    # A varredura **apaga** e nao escreve: sem `INSERT`, pela razao da `0019` —
    # um papel de lote que pudesse inserir num sitio que so devia limpar e uma
    # porta aberta sem porta nenhuma a precisar dela.
    op.execute(
        f"GRANT SELECT, DELETE "
        f"ON {ESQUEMA}.checkpoints, {ESQUEMA}.checkpoint_writes TO {PAPEL_DO_LOTE}"
    )


def downgrade() -> None:
    # Destrutivo, e ver a nota do modulo: leva o estado de todas as conversas em
    # curso. Sem `CASCADE` de proposito — um objecto criado no `lg` fora desta
    # revisao faz isto **falhar**, que e melhor do que o apagar sem ninguem
    # mandar.
    op.execute(f"DROP TABLE {ESQUEMA}.checkpoint_writes")
    op.execute(f"DROP INDEX {ESQUEMA}.checkpoints_thread_criado_idx")
    op.execute(f"DROP TABLE {ESQUEMA}.checkpoints")
    op.execute(f"DROP SCHEMA {ESQUEMA}")
