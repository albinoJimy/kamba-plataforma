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
