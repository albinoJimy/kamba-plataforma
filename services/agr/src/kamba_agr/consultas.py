"""O SQL do AGR, num ficheiro so (KAM-025).

Em constantes e separado da logica pela razao que o `chr/consultas.ts`, o
`outbound/consultas.ts`, o `modos/consultas.ts` e o `ten/consultas.py` ja
escreveram: a *suite* do *gate* 8 corre **estas** cadeias e nao copias delas, e
foi assim que o KAM-009 descobriu um `coalesce` em falta que uma copia no teste
escondia. Uma base falsa compara SQL por texto e nunca o interpreta — um erro de
sintaxe passava o *gate* 4 inteiro.

Os marcadores sao `%s`, que e o que a DB-API le (`pg8000`), como em
`ten/consultas.py`. **Sao posicionais**: a ordem em que aparecem no texto e a
ordem dos argumentos, e um parametro trocado aqui nao da erro — da a resposta
de outra conversa.

## Tres coisas que este SQL faz, e vale ve-las antes de as ler

**A exclusao mutua e da base, e e de sessao.** O `SQL_TRANCAR_THREAD` e um
`pg_advisory_lock` — nao `pg_advisory_xact_lock` — e a decisao, com as tres
opcoes que se pesaram, esta em `docs/adr/ADR-L004-fila-e-tranca-do-agr.md`
(Decisao 2). Em duas linhas: a tranca larga quando a **ligacao** morre, e e isso
que faz o criterio 4 (SIGKILL a meio do turno) funcionar sem temporizador
nenhum a calibrar.

**Quem tem a palavra decide-se numa consulta so.** O `SQL_PALAVRA_DA_CONVERSA`
le o `conversations.mode` e a existencia de um `handoffs` em `waiting` **na
mesma leitura**, e nao em duas. Em duas havia uma janela entre elas em que o
modo dizia `bot` e o *handoff* abria: o turno entrava no grafo sobre uma conversa
que ja estava com um humano. A invariante do `docs/tecnica/02` §11 regra 4 nao
admite essa janela, e uma consulta so e a forma mais barata de a nao ter.

**O `tenant_id` esta no predicado alem da RLS**, pela razao do `SQL_JANELA` do
KAM-015 e do `SQL_CONTACTO_DA_CONVERSA` do KAM-018: repeti-lo e o que torna a
consulta correcta mesmo que alguem a corra sem contexto — devolve zero linhas em
vez da conversa de outro. E zero linhas **nao** e «esta em `bot`»: ver
`turno.py`, que trata a ausencia como recusa.
"""

from __future__ import annotations

#: Tenta tomar a tranca da conversa. **Fora** de transaccao, numa ligacao
#: dedicada. Devolve `true` se a conseguiu e `false` se outra sessao a tem.
#:
#: **`pg_try_advisory_lock` e nao `pg_advisory_lock`, e a diferenca e a razao de
#: ser desta linha.** O `pg_advisory_lock` **bloqueia** no servidor ate a tranca
#: ser sua, e o `pg8000` e sincrono: a chamada prende a `thread` do *executor* e,
#: com ela, o `asyncio.Lock` que serializa o uso da unica ligacao de tranca do
#: processo. O resultado — medido pela revisao adversarial — e que uma conversa
#: a espera de uma chave **para o processo inteiro**: nenhuma outra conversa
#: consegue trancar, e as que acabaram nao conseguem **destrancar**, porque o
#: `pg_advisory_unlock` precisa da mesma ligacao. E bloqueio de cabeca de fila
#: que atravessa *tenants*, que e exactamente o que o criterio 5 proibe.
#:
#: A chave colide de proposito com a do `pg_advisory_xact_lock` dos modos
#: (KAM-018), que o `PreSendGuard` toma **em cada envio do bot**: nao e preciso
#: um segundo AGR para a espera acontecer.
#:
#: Com a tentativa que nao bloqueia, quem espera larga o `asyncio.Lock` entre
#: tentativas (`trancas.py`), e a espera deixa de ser exclusiva. **A ordem de
#: chegada continua preservada** porque dentro do processo so uma corrotina por
#: `thread_id` chega aqui — o dreno de `turno.py` e que serializa —, pelo que
#: nao ha duas tentativas da mesma chave a competir neste processo.
#:
#: `hashtextextended(texto, 0)` e nao `hashtext`: o primeiro devolve `bigint`,
#: que e a largura que `pg_advisory_lock(bigint)` aceita; o segundo devolve
#: `int4` e obrigava a forma de dois argumentos. A semente `0` e fixa — uma
#: semente que variasse dava chaves diferentes para a mesma conversa em
#: processos diferentes, que e o mesmo que nao ter tranca.
#:
#: **A chave e o `thread_id` inteiro**, que ja e `{tenant_id}:{contact_id}` e
#: ja traz o separador que impede a colisao entre pares cuja concatenacao
#: coincida. O `SQL_TRANCAR_CONVERSA` do KAM-018 hasheia
#: `tenant_id || ':' || contact_id`, que e **o mesmo texto**: as duas chaves
#: colidem de proposito, e e isso que faz uma transicao de modo em curso travar
#: a entrada de um turno (ADR-L004, Decisao 2).
#:
#: Parametros: o `thread_id`.
SQL_TRANCAR_THREAD = """
  SELECT pg_try_advisory_lock(hashtextextended(%s::text, 0)) AS consegui
"""

#: Larga a tranca da conversa. Devolve `true` se esta sessao a tinha.
#:
#: O booleano nao se ignora: um `false` significa que esta sessao largou uma
#: tranca que nao era sua — ou, mais provavelmente, que o `trancar` e o
#: `destrancar` correram em **ligacoes diferentes**, que e o modo de falha de um
#: *pooler* em modo transacção (ADR-L004). Sem ler o resultado, esse defeito nao
#: da erro nenhum: da exclusao mutua que nao exclui.
#:
#: Parametros: o `thread_id`.
SQL_DESTRANCAR_THREAD = """
  SELECT pg_advisory_unlock(hashtextextended(%s::text, 0)) AS largou
"""

#: Quem tem a palavra nesta conversa: o modo, e se ha um *handoff* a espera.
#:
#: Uma linha ou nenhuma. **Nenhuma** quer dizer uma de tres coisas — a conversa
#: nao existe, foi apagada, ou o contexto de RLS e de outro *tenant* — e as tres
#: dao a mesma resposta em `turno.py`: nao entra no grafo. Uma conversa que o
#: AGR nao consegue ler nao e uma conversa em `bot`.
#:
#: O `EXISTS` sobre `handoffs` filtra por `(tenant_id, conversation_id)`, que e
#: a FK composta da revisao `0011`, e por `status = 'waiting'`, que e o unico dos
#: cinco estados que fecha a porta (§3.15: `waiting -> resumed | timeout |
#: cancelled | degraded`). Os outros quatro sao passagens **acabadas** e o turno
#: entra normalmente — e por isso que o predicado nomeia `waiting` em vez de
#: negar os outros: um estado novo no dominio nao pode fechar a porta por
#: omissao.
#:
#: Parametros: o `tenant_id`, o `conversation_id`, e outra vez os dois para o
#: `EXISTS` — porque os marcadores sao posicionais e o `%s` nao se reutiliza.
SQL_PALAVRA_DA_CONVERSA = """
  SELECT c.mode AS modo,
         EXISTS (
           SELECT 1
             FROM platform.handoffs h
            WHERE h.tenant_id = %s
              AND h.conversation_id = %s
              AND h.status = 'waiting'
         ) AS handoff_a_espera
    FROM platform.conversations c
   WHERE c.tenant_id = %s
     AND c.id = %s
"""

# O contexto de *tenant* **nao** esta aqui, e e deliberado: quem o da e o
# `kamba_core.tenant_guard.tx`, que ja escreve o `set_config('app.tenant_id',
# %s, true)` e ja recusa as quatro coisas que o tornam inutil (sem tenant, um
# tenant que nao e UUID, uma ligacao em `autocommit`, e um `tx` dentro de
# outro). Uma segunda copia da mesma regra aqui era a classe de defeito que o
# `ten/consultas.py` nomeia por escrito: a primeira versao dele escrevia o
# `min(...)` que a `ten_consumir` ja tinha.


# ---------------------------------------------------------------------------
# O checkpointer (KAM-026)
#
# Oito cadeias, e as colunas sao as do `CheckpointTuple` do
# `BaseCheckpointSaver`. Tres notas que valem antes de as ler:
#
# **O `checkpoint_id` ordena.** O `Checkpoint` do LangGraph di-lo por escrito —
# «both unique and monotonically increasing, so can be used for sorting
# checkpoints from first to last» —, e e por isso que o «mais recente» e um
# `ORDER BY checkpoint_id DESC LIMIT 1` e nao um `ORDER BY criado_at`: o
# `criado_at` e o relogio do servidor e dois checkpoints do mesmo passo podem
# cair no mesmo microssegundo.
#
# **As escritas pendentes voltam por `(task_path, task_id, idx)`**, que e o
# `writes_sort_key` da interface. Nao e enfeite: ela avisa que um redutor
# sensivel a ordem reconstroi um valor diferente do que a execucao produziu se
# a ordem for outra.
#
# **O `ON CONFLICT DO UPDATE` e o que torna o turno repetivel.** Um turno que
# repete depois de uma falha reescreve o mesmo `checkpoint_id` e a mesma
# `(tarefa, idx)` em vez de duplicar — e o criterio 5 visto da tabela.

#: O checkpoint mais recente de uma *thread* num *namespace*.
#:
#: Parametros: `thread_id`, `checkpoint_ns`.
SQL_CHECKPOINT_RECENTE = """
  SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint,
         metadata_type, metadata
    FROM lg.checkpoints
   WHERE thread_id = %s
     AND checkpoint_ns = %s
   ORDER BY checkpoint_id DESC
   LIMIT 1
"""

#: Um checkpoint nomeado. E o caminho da retoma de um `interrupt` e da viagem
#: no tempo: o `config` traz o `checkpoint_id` e pede-se exactamente aquele.
#:
#: Parametros: `thread_id`, `checkpoint_ns`, `checkpoint_id`.
SQL_CHECKPOINT_POR_ID = """
  SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint,
         metadata_type, metadata
    FROM lg.checkpoints
   WHERE thread_id = %s
     AND checkpoint_ns = %s
     AND checkpoint_id = %s
"""

#: As escritas pendentes de um checkpoint, na ordem do `writes_sort_key`.
#:
#: Parametros: `thread_id`, `checkpoint_ns`, `checkpoint_id`.
SQL_ESCRITAS_PENDENTES = """
  SELECT task_id, channel, type, blob
    FROM lg.checkpoint_writes
   WHERE thread_id = %s
     AND checkpoint_ns = %s
     AND checkpoint_id = %s
   ORDER BY task_path, task_id, idx
"""

#: O historico de uma *thread*, do mais recente para o mais antigo.
#:
#: O `before` do `alist` e um `<` sobre o `checkpoint_id` pela mesma razao que o
#: `SQL_CHECKPOINT_RECENTE` ordena por ele. O nulo no terceiro parametro quer
#: dizer «sem limite superior», e o `%s IS NULL OR` e o que o permite sem uma
#: segunda cadeia.
#:
#: **Os dois `::text` nao sao enfeite.** Sem eles o servidor responde
#: `42P18 — could not determine data type of parameter $3`: um parametro cujo
#: unico uso e `IS NULL` nao da ao analisador contexto nenhum para inferir o
#: tipo, e a instrucao nem chega a correr. Medido contra a base, nao lido.
#:
#: Parametros: `thread_id`, `checkpoint_ns`, `before` (ou nulo), `limite`.
SQL_LISTAR_CHECKPOINTS = """
  SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint,
         metadata_type, metadata
    FROM lg.checkpoints
   WHERE thread_id = %s
     AND checkpoint_ns = %s
     AND (%s::text IS NULL OR checkpoint_id < %s::text)
   ORDER BY checkpoint_id DESC
   LIMIT %s
"""

#: Grava um checkpoint. Repetir o mesmo `checkpoint_id` reescreve-o.
#:
#: Parametros: `thread_id`, `checkpoint_ns`, `checkpoint_id`,
#: `parent_checkpoint_id`, `type`, `checkpoint`, `metadata_type`, `metadata`.
SQL_GRAVAR_CHECKPOINT = """
  INSERT INTO lg.checkpoints
         (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
          type, checkpoint, metadata_type, metadata)
  VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
      ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id)
      DO UPDATE SET parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
                    type                 = EXCLUDED.type,
                    checkpoint           = EXCLUDED.checkpoint,
                    metadata_type        = EXCLUDED.metadata_type,
                    metadata             = EXCLUDED.metadata
"""

#: Grava uma escrita pendente. A chave e (thread, ns, checkpoint, tarefa, idx),
#: pelo que a mesma tarefa a repetir a mesma escrita cai no mesmo sitio.
#:
#: Parametros: `thread_id`, `checkpoint_ns`, `checkpoint_id`, `task_id`,
#: `task_path`, `idx`, `channel`, `type`, `blob`.
SQL_GRAVAR_ESCRITA = """
  INSERT INTO lg.checkpoint_writes
         (thread_id, checkpoint_ns, checkpoint_id, task_id, task_path,
          idx, channel, type, blob)
  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
      ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
      DO UPDATE SET task_path = EXCLUDED.task_path,
                    channel   = EXCLUDED.channel,
                    type      = EXCLUDED.type,
                    blob      = EXCLUDED.blob
"""

#: Apaga uma *thread* inteira: as escritas primeiro, pela ordem que nao deixa
#: escritas orfas se a segunda instrucao falhar.
#:
#: Sao duas cadeias e nao uma com `CASCADE`: nao ha chave estrangeira entre as
#: duas tabelas de proposito — uma `FOREIGN KEY` obrigava cada escrita a esperar
#: pelo checkpoint que a origina, e o LangGraph grava escritas de uma tarefa
#: **antes** do checkpoint do passo seguinte existir.
#:
#: Parametros: o `thread_id`.
SQL_APAGAR_ESCRITAS_DA_THREAD = """
  DELETE FROM lg.checkpoint_writes WHERE thread_id = %s
"""

#: Parametros: o `thread_id`.
SQL_APAGAR_CHECKPOINTS_DA_THREAD = """
  DELETE FROM lg.checkpoints WHERE thread_id = %s
"""

#: As *threads* sem escrita nenhuma desde um instante. E a varredura da
#: retencao (criterio 8), e corre como `kamba_batch`.
#:
#: O predicado e sobre o **maximo** `criado_at` da *thread* e nao sobre cada
#: linha: uma *thread* com um checkpoint de ontem e outro de ha um ano esta
#: activa, e apagar-lhe o antigo era poda e nao retencao — e a poda nao se faz
#: aqui, pela razao escrita no `checkpointer.py`.
#:
#: Parametros: o instante limite.
SQL_THREADS_INACTIVAS = """
  SELECT thread_id
    FROM lg.checkpoints
   GROUP BY thread_id
  HAVING max(criado_at) < %s
"""
