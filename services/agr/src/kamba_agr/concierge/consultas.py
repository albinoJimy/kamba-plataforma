"""As instrucoes SQL do modo concierge (KAM-114).

Vivem aqui e nao no `consultas.py` da raiz pela razao que o KAM-034 escreveu
para o `handoff/`: o que e de um subsistema fica no subsistema, e o *lint* de
arquitectura dispensa escritas no `platform` por `(ficheiro, tabela, verbo)` —
uma dispensa que nomeasse o `consultas.py` da raiz abria-a para as nove tabelas
que ele toca.

**O `thread_id` entra no predicado de todas as escritas, e nao e redundante com
a RLS nem com o `tenant_id`.** E a licao do KAM-034: o `draft_id` e
`sha256(thread_id:turn_seq)` e portanto **irreversivel**, pelo que do
identificador nao se le o *thread* de volta. Com so o `tenant_id`, um
`draft_id` do **mesmo** *tenant* e de **outro contacto** passava o predicado — e
a decisao de um operador sobre o rascunho de uma conversa aprovava a mensagem de
outra pessoa. O `thread_id` e `tenant_id:contact_id`, pelo que po-lo no
predicado compra a propriedade sem coluna nova.

E o `tenant_id` repete-se **alem** da RLS pela razao do `SQL_PALAVRA_DA_CONVERSA`
do KAM-025: repeti-lo torna a instrucao correcta mesmo corrida sem contexto —
zero linhas em vez do rascunho de outro.
"""

from __future__ import annotations

from typing import Final

#: Abre o rascunho em `pendente` (`decisao IS NULL`). Idempotente por
#: `draft_id`, que e a chave primaria.
#:
#: **O `ON CONFLICT DO NOTHING` e o criterio 2** («re-executar o no de rascunho
#: 5x cria 1 rascunho»): a idempotencia e da base e nao de um contador deste
#: processo, que o reinicio perdia e a segunda replica nao via.
#:
#: Parametros: `draft_id`, `tenant_id`, `thread_id`, `turn_seq`, `turn_id`,
#: `graph_version`.
SQL_ABRIR_RASCUNHO: Final = """
  INSERT INTO platform.draft_decisions
         (draft_id, tenant_id, thread_id, turn_seq, turn_id, graph_version)
  VALUES (%s, %s, %s, %s, %s, %s)
  ON CONFLICT (draft_id) DO NOTHING
  RETURNING 1
"""

#: O *compare-and-set* `pendente -> decidido` do criterio 2. **Uma** instrucao:
#: ler o estado e escrever depois perdia a corrida entre dois cliques
#: concorrentes, que e exactamente o que o criterio mede.
#:
#: A `latencia_ms` calcula-se **na base** e nao na aplicacao: com dois relogios
#: (o do processo que abriu o rascunho e o do que o decide) a diferenca media o
#: desvio entre eles e nao o tempo do operador.
#:
#: Parametros: `decisao`, `motivo`, `razao_edicao`, `edicao_numero_livre`,
#: `tenant_id`, `draft_id`, `thread_id`.
SQL_DECIDIR_RASCUNHO: Final = """
  UPDATE platform.draft_decisions AS d
     SET decisao = %s,
         motivo = %s,
         razao_edicao = %s,
         edicao_numero_livre = %s,
         decidido_at = now(),
         latencia_ms = (
             EXTRACT(EPOCH FROM (now() - d.criado_at)) * 1000
         )::integer
   WHERE d.tenant_id = %s
     AND d.draft_id = %s
     AND d.thread_id = %s
     AND d.decisao IS NULL
  RETURNING 1
"""

#: O estado de um rascunho **deste** *thread*. Corre so quando o CAS deu zero
#: linhas, para separar o duplicado da recusa — e a forma do
#: `SQL_ESTADO_DO_HANDOFF` do KAM-034.
#:
#: Zero linhas aqui quer dizer tres coisas e as tres sao a mesma recusa: o
#: rascunho nao existe, e de outro *tenant* (a RLS nao o mostra), ou e de outro
#: contacto do mesmo *tenant* (o `thread_id` nao casa). Uma linha quer dizer que
#: o rascunho e desta conversa e que **ja foi decidido** — o duplo clique, que
#: responde 200 sem efeito.
#:
#: Parametros: `tenant_id`, `draft_id`, `thread_id`.
SQL_ESTADO_DO_RASCUNHO: Final = """
  SELECT d.decisao
    FROM platform.draft_decisions d
   WHERE d.tenant_id = %s
     AND d.draft_id = %s
     AND d.thread_id = %s
"""

#: Os rascunhos `pendente` de um *thread* — o criterio 5 (*echo* do dono ou
#: handoff).
#:
#: **Nao leva `draft_id`**: quem substitui chega com a conversa e nao com o
#: rascunho, e um *thread* pode ter mais do que um pendente se um turno anterior
#: ficou por varrer.
#:
#: Parametros: `tenant_id`, `thread_id`.
SQL_PENDENTES_DO_THREAD: Final = """
  SELECT d.draft_id
    FROM platform.draft_decisions d
   WHERE d.tenant_id = %s
     AND d.thread_id = %s
     AND d.decisao IS NULL
   ORDER BY d.criado_at
"""

#: Os rascunhos `pendente` de todos os *tenants*, dos mais antigos para os mais
#: novos. E a listagem da varredura — a dos prazos (criterio 1) e a da politica
#: desligada (criterio 8), que sao a **mesma** passagem.
#:
#: **Atravessa *tenants***, pela razao do `agr_handoff_prazos` do KAM-034 — com
#: contexto de um *tenant* a RLS devolvia so os rascunhos desse —, pelo que
#: corre com o papel `kamba_batch`.
#:
#: **So lista; nao escreve.** A escrita e um *compare-and-set* por rascunho,
#: feito com o papel da aplicacao e com contexto de *tenant*, exactamente como a
#: varredura do *handoff* faz: uma segunda via de escrita que nao passasse pelo
#: CAS era uma segunda implementacao do criterio 2, e perdia a corrida contra um
#: operador a decidir no mesmo instante.
#:
#: Parametros: `tecto`.
SQL_PENDENTES: Final = """
  SELECT d.draft_id, d.tenant_id, d.thread_id, d.criado_at
    FROM platform.draft_decisions d
   WHERE d.decisao IS NULL
   ORDER BY d.criado_at
   LIMIT %s
"""

#: Quantos rascunhos estao `pendente` ha mais de N minutos — o alerta
#: (*proposta*) do criterio 6. Atravessa *tenants*, como a varredura.
#:
#: Parametros: `minutos`.
SQL_PENDENTES_HA_MAIS_DE: Final = """
  SELECT count(*)
    FROM platform.draft_decisions d
   WHERE d.decisao IS NULL
     AND d.criado_at < now() - make_interval(mins => %s)
"""

#: O que a compensacao escreve para devolver o rascunho a `pendente`. **Uma
#: instrucao propria e nao o `SQL_DECIDIR_RASCUNHO` ao contrario**: ela tem de
#: limpar as seis colunas do CAS de uma vez, e o `CHECK` do par
#: `decisao`/`decidido_at` recusa qualquer reversao parcial — o que e a base a
#: impedir uma compensacao a meio.
SQL_REVERTER_DECISAO: Final = """
  UPDATE platform.draft_decisions AS d
     SET decisao = NULL,
         motivo = NULL,
         razao_edicao = NULL,
         edicao_numero_livre = false,
         decidido_at = NULL,
         latencia_ms = NULL
   WHERE d.tenant_id = %s
     AND d.draft_id = %s
     AND d.thread_id = %s
     AND d.decisao = %s
  RETURNING 1
"""

__all__ = [
    "SQL_ABRIR_RASCUNHO",
    "SQL_DECIDIR_RASCUNHO",
    "SQL_ESTADO_DO_RASCUNHO",
    "SQL_PENDENTES",
    "SQL_PENDENTES_DO_THREAD",
    "SQL_PENDENTES_HA_MAIS_DE",
    "SQL_REVERTER_DECISAO",
]
