"""O SQL da subscricao de eventos (KAM-038).

Em constantes e separado da logica pela razao do `consultas.py` do KAM-025: a
*suite* do *gate* 8 corre **estas** cadeias e nao copias delas. Os marcadores
sao `%s`, **posicionais**, e a ordem em que aparecem no texto e a ordem dos
argumentos — um parametro trocado aqui nao da erro, da a conversa de outra
pessoa.

## As duas escritas no `platform` que este ficheiro traz

O *lint* de arquitectura do *gate* 2 (`tools/lint_arch/tool_schema.py`) proibe
`INSERT`/`UPDATE`/`DELETE` contra o `platform` em modulos do AGR fora de `tls/`,
porque «a TLS e a unica via de leitura e escrita dos **agentes**» (§6.1,
ADR-015). A `events_dlq` entra na lista `ESCRITAS_DO_PLANO_DE_CONTROLO` daquele
modulo, e a entrada so e legitima porque as quatro condicoes dele valem:

1. **nenhum passo depende de saida de modelo nem de texto do cliente** — o que
   se escreve e o envelope que o `evt_emitir` construiu e um `erro` de lista
   fechada (`MOTIVOS_DA_DLQ`);
2. **e plano de controlo e nao dado de negocio** — uma entrada na DLQ diz que
   uma entrega parou, nao mexe em encomenda, preco nem contacto;
3. **o `tenant_id` esta na instrucao e ela corre dentro de `tenant_guard.tx`**,
   pelo que o isolamento continua a ser da base;
4. **o canon nomeia o AGR como dono da escrita**: o `consumo.py` do KAM-006
   escreve por extenso que «nao trata de retentativas nem de DLQ — isso e
   politica, e vive no trabalhador», e o trabalhador destas subscricoes e este
   servico.

A `events_consumed` **nao** precisa de entrada nenhuma: quem lhe escreve e o
`kamba_core.eventos.consumir` (KAM-006), que vive em `libs/` e nao em
`services/`, e o *lint* so varre `services/*/src/**`.
"""

from __future__ import annotations

#: Abre uma entrada na DLQ. Idempotente **entre as abertas**.
#:
#: O `ON CONFLICT ... WHERE estado = 'aberta' DO NOTHING` nao e optimizacao: e
#: o alvo do indice parcial `events_dlq_aberta_uq` da revisao `0005`, e a
#: razao esta escrita la por extenso — com a unicidade inteira, um ciclo novo
#: depois de uma resolucao nao escrevia nada e ficava uma DLQ a zero sobre um
#: efeito por aplicar. **O alvo esta nomeado**: um `DO NOTHING` sem alvo
#: engolia um conflito em qualquer outro indice que a tabela venha a ter.
#:
#: O `envelope` vai como texto com `::jsonb`: o `pg8000` nao tem adaptador para
#: `dict` e um `str` sem o molde chega como `text`, que a coluna recusa.
#:
#: Parametros: `consumer`, `event_id`, `tipo`, `versao`, `tenant_id`,
#: `envelope`, `erro`, `tentativas`.
SQL_ABRIR_DLQ = """
  INSERT INTO platform.events_dlq
    (consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas)
  VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
      ON CONFLICT (consumer, event_id) WHERE estado = 'aberta' DO NOTHING
"""

#: A conversa de um contacto, com o modo e se ha *handoff* a espera.
#:
#: Uma linha ou nenhuma, e **nenhuma nao e «esta em `bot`»** — e a mesma regra
#: do `SQL_PALAVRA_DA_CONVERSA` do KAM-025, e pela mesma razao: zero linhas quer
#: dizer que a conversa nao existe, foi apagada, ou que o contexto de RLS e de
#: outro *tenant*. Nas tres, o evento nao acorda nada; e e assim que um envelope
#: com `tenant_id` forjado fica sem efeito (criterio 4), porque o contexto vem
#: do envelope validado e so ve as conversas desse *tenant*.
#:
#: **O `tenant_id` esta no predicado alem da RLS**, pela razao do KAM-015 e do
#: KAM-018: repeti-lo torna a consulta correcta mesmo corrida sem contexto —
#: devolve zero linhas em vez da conversa de outro.
#:
#: **Porque e que ha um `ORDER BY`**: a `conversations` e
#: `UNIQUE (tenant_id, contact_id, channel_id)` (revisao `0009`), pelo que o
#: mesmo contacto em dois canais do mesmo *tenant* tem **duas** conversas, e um
#: evento traz `contact_id` e nao `channel_id` (o *payload* nunca traz canal:
#: §7.1). Escolhe-se a de entrada mais recente, que e a unica com janela
#: possivelmente aberta — a janela e `last_inbound_at + 24 h` (§3.14). O
#: desempate pelo `id` existe para que a escolha seja **deterministica**: sem
#: ele, duas conversas sem entrada nenhuma davam linhas diferentes em execucoes
#: diferentes, e a repeticao de uma entrega notificava outra conversa.
#:
#: **Sao dois parametros e nao quatro**, ao contrario do
#: `SQL_PALAVRA_DA_CONVERSA` do KAM-025: ali o `EXISTS` recebia o par outra vez
#: porque a conversa era conhecida pelo `id`; aqui ela e **procurada** pelo
#: contacto, pelo que o `EXISTS` se correlaciona com as colunas de `c` e nao ha
#: segundo par para passar. Repeti-lo era passar o `conversation_id` que ainda
#: nao se sabe.
#:
#: Parametros: o `tenant_id` e o `contact_id`.
SQL_CONVERSA_DO_CONTACTO = """
  SELECT c.id::text AS conversa,
         c.mode AS modo,
         EXISTS (
           SELECT 1
             FROM platform.handoffs h
            WHERE h.tenant_id = c.tenant_id
              AND h.conversation_id = c.id
              AND h.status = 'waiting'
         ) AS handoff_a_espera
    FROM platform.conversations c
   WHERE c.tenant_id = %s
     AND c.contact_id = %s
   ORDER BY c.last_inbound_at DESC NULLS LAST, c.id
   LIMIT 1
"""
