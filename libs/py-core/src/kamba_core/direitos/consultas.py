"""O SQL dos direitos do titular, num sitio so (KAM-070, revisao `0037`).

`%s` e nao `$n`, que e o que a DB-API le, como em `kamba_core.ten.consultas` e
`kamba_core.destinos.consultas`.

## O predicado do contacto esta em **todas** as consultas da exportacao, e isso e verificavel

O criterio 2 pede «nenhum dado de outro contacto ou tenant aparece». O tenant e
da RLS — a politica `tenant_iso` acrescenta `tenant_id = app.tenant_id` a toda a
consulta, e nao se escreve a mao. **O contacto nao tem politica nenhuma**: e
responsabilidade de cada consulta, e uma consulta que a esqueca devolve a
conversa de todos os clientes daquele tenant ao primeiro que pedir a sua
exportacao.

Uma consulta esquecida assim **nao da erro**: devolve mais linhas. E por isso
que as consultas da exportacao estao num mapa nomeado — o `EXPORTACAO` — e nao
soltas: o ensaio
`test_toda_a_consulta_da_exportacao_filtra_pelo_contacto` itera o mapa e exige o
predicado no texto de cada uma. Uma consulta nova entra no mapa (senao a
exportacao nao a chama) e e medida sem ninguem se lembrar dela.

**E ha um segundo ensaio que nao e o mesmo**, e a diferenca e a licao que esta
casa pagou: um duplo de base que decidisse pelo **argumento** que lhe passam
ficava verde com o `AND contact_id = %s` apagado da instrucao, porque continuava
a receber o `contact_id` na tupla de parametros. O duplo
`BaseQueLeAInstrucao` **le o texto** da instrucao e recusa responder a uma que
nao filtre pelo contacto. Um mede que o texto esta la; o outro mede que o
caminho nao funciona sem ele.
"""

from __future__ import annotations

#: O predicado que toda a consulta da exportacao tem de conter, literalmente.
#:
#: E uma cadeia e nao uma expressao regular de proposito: o que o ensaio mede e
#: a presenca **desta** forma, e nao «alguma coisa que se pareca com um filtro
#: de contacto». Uma forma equivalente escrita de outra maneira (`contact_id=%s`
#: sem espacos, ou um `IN`) reprova — e deve, porque a disciplina barata e
#: escrever sempre igual, nao ensinar o ensaio a aceitar variantes.
PREDICADO_DO_CONTACTO = "contact_id = %s::uuid"

# ---------------------------------------------------------------------------
# O pedido
# ---------------------------------------------------------------------------

#: As colunas do pedido, pela ordem em que o `Pedido` as le. Uma cadeia so, para
#: que as consultas que devolvem um pedido devolvam **o mesmo** conjunto: duas
#: listas de colunas para o mesmo `dataclass` divergem na primeira coluna nova.
COLUNAS_DO_PEDIDO = (
    "dsar_id, tenant_id, contact_id, tipo, estado, papel_kamba, "
    "recebido_at, prazo_dias, prazo_interno_at, concluido_at"
)

#: Cria o pedido (criterio 1).
#:
#: O `prazo_interno_at` entra como parametro e **nao** se calcula aqui: a
#: aritmetica e do `contrato.prazo_interno`, pela razao que a revisao `0037`
#: escreve (`timestamptz + interval` le o `TimeZone` da sessao, pelo que um
#: calculo na base dava respostas diferentes a sessoes diferentes). O que a base
#: garante e a ordenacao.
#:
#: **Nao leva `ON CONFLICT`.** O indice unico parcial `dsar_requests_aberto_uq`
#: recusa um segundo pedido aberto do mesmo tipo, e a recusa e `23505` — que o
#: `pedidos.py` traduz para `PedidoEmCurso` **com o pedido que ja existe**. Um
#: `ON CONFLICT DO NOTHING` devolvia zero linhas e perdia a informacao de qual e
#: o pedido em curso, que e a unica coisa que quem pediu outra vez quer saber.
#:
#: Parametros: tenant, contacto, tipo, estado, papel, recebido_at, prazo_dias,
#: prazo_interno_at.
SQL_CRIAR_PEDIDO = f"""
  INSERT INTO platform.dsar_requests
         (tenant_id, contact_id, tipo, estado, papel_kamba,
          recebido_at, prazo_dias, prazo_interno_at)
  VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::smallint, %s)
  RETURNING {COLUNAS_DO_PEDIDO}
"""

#: O pedido aberto do mesmo tipo para o mesmo titular, se houver (criterio 8).
#:
#: Le-se **depois** da colisao e nao antes: ler-antes-e-inserir-depois e uma
#: corrida que duas chamadas simultaneas ganham as duas. O que impede o segundo
#: `job` e o indice; esta consulta serve para dizer **qual** e o pedido que ja
#: esta aberto.
SQL_PEDIDO_ABERTO = f"""
  SELECT {COLUNAS_DO_PEDIDO}
    FROM platform.dsar_requests
   WHERE {PREDICADO_DO_CONTACTO}
     AND tipo = %s
     AND estado <> 'concluido'
"""

#: Um pedido pelo seu identificador.
SQL_PEDIDO = f"""
  SELECT {COLUNAS_DO_PEDIDO}
    FROM platform.dsar_requests
   WHERE dsar_id = %s::uuid
"""

#: Marca o pedido como em curso. Idempotente: so morde no `recebido`.
SQL_EM_CURSO = f"""
  UPDATE platform.dsar_requests
     SET estado = 'em_curso'
   WHERE dsar_id = %s::uuid
     AND estado = 'recebido'
  RETURNING {COLUNAS_DO_PEDIDO}
"""

#: Fecha o pedido (criterio 3).
#:
#: **O `estado <> 'concluido'` no `WHERE` nao e defensiva: e a idempotencia.**
#: Sem ele, fechar duas vezes reescrevia o `concluido_at` — e a data de
#: conclusao de um pedido do titular e um facto com prazo legal atras dele, nao
#: um campo que se actualiza. Com ele, o segundo fecho devolve zero linhas e
#: quem chama sabe que nao foi o primeiro.
#:
#: Parametros: concluido_at, dsar_id.
SQL_CONCLUIR = f"""
  UPDATE platform.dsar_requests
     SET estado = 'concluido', concluido_at = %s
   WHERE dsar_id = %s::uuid
     AND estado <> 'concluido'
  RETURNING {COLUNAS_DO_PEDIDO}
"""

#: Os pedidos abertos de um tenant, do mais antigo para o mais novo.
#:
#: Serve o varrimento do criterio 8. Devolve **todos** os abertos e nao os que
#: ja passaram um limite, e e deliberado: quem decide se um pedido esta em
#: atraso ou se o alerta e devido e o `Pedido` do `contrato.py`, com o relogio
#: injectado — um `WHERE now() - recebido_at > interval '20 days'` punha a
#: aritmetica do prazo na base, onde nao se consegue ensaiar com datas fixas, e
#: dava **duas** leituras do mesmo predicado.
SQL_PEDIDOS_ABERTOS = f"""
  SELECT {COLUNAS_DO_PEDIDO}
    FROM platform.dsar_requests
   WHERE estado <> 'concluido'
   ORDER BY recebido_at, dsar_id
"""

# ---------------------------------------------------------------------------
# O ledger de apagamento
# ---------------------------------------------------------------------------

#: Registra que um escopo aplicou (criterio 3).
#:
#: `ON CONFLICT DO NOTHING` sobre `(tenant_id, dsar_id, escopo)`, e **aqui o
#: silencio e a resposta certa**, ao contrario do pedido: um consumidor que
#: aplique duas vezes o mesmo escopo nao e um erro a reportar — e a repeticao
#: que o criterio 8 manda ser idempotente. O `RETURNING` distingue os dois
#: casos sem os tratar de maneira diferente: vem linha na primeira vez, nao vem
#: na segunda.
#:
#: Parametros: tenant, dsar_id, contacto, escopo, aplicado_at.
SQL_REGISTAR_APLICACAO = """
  INSERT INTO platform.erasure_ledger
         (tenant_id, dsar_id, contact_id, escopo, aplicado_at)
  VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s)
  ON CONFLICT (tenant_id, dsar_id, escopo) DO NOTHING
  RETURNING erasure_id, tenant_id, dsar_id, contact_id, escopo, aplicado_at
"""

#: Os escopos que ja aplicaram, para um pedido.
#:
#: Devolve o conjunto e nao uma contagem, e e a diferenca que faz o criterio 3
#: significar algo: uma contagem de seis fechava o pedido com **seis linhas do
#: mesmo escopo** se a unicidade falhasse, e a mensagem de um pedido que nao
#: fecha tem de nomear quem falta ou ninguem o resolve.
SQL_ESCOPOS_APLICADOS = """
  SELECT escopo
    FROM platform.erasure_ledger
   WHERE dsar_id = %s::uuid
   ORDER BY escopo
"""

#: O par que o restauro precisa: quem foi apagado, e **quando pela primeira
#: vez** (criterio 6).
#:
#: O `min(aplicado_at)` e a escolha conservadora e e a unica que serve o
#: predicado do restauro: uma copia tirada **antes** do primeiro apagamento tem
#: o sujeito de certeza; uma tirada depois pode ja nao o ter. Tomar o
#: `max` deixava de fora as copias tiradas no meio de um apagamento — isto e,
#: exactamente as que ficam com metade do titular dentro.
#:
#: Uma linha por contacto, que e a forma que o *hook* de reaplicacao le.
SQL_SUJEITOS_APAGADOS = """
  SELECT contact_id, min(aplicado_at) AS erased_at
    FROM platform.erasure_ledger
   GROUP BY contact_id
   ORDER BY min(aplicado_at), contact_id
"""

# ---------------------------------------------------------------------------
# A exportacao (criterio 2)
# ---------------------------------------------------------------------------

#: O contacto, e **so as colunas que o `kamba_app` tem**.
#:
#: A `0003` concede `SELECT` por coluna em `platform.contacts`
#: (`COLUNAS_DA_APP`), e nenhuma delas e dado pessoal: o `phone_hmac` e o
#: `hmac_kid` ficam de fora do `GRANT`. Pedir `*` aqui levantava
#: `insufficient_privilege` — e e bom que levante: a exportacao corre com o
#: papel da aplicacao e nao com o do cofre, porque o que o titular acede sao os
#: seus dados e nao as chaves que os cifram.
#:
#: **O telefone e o BSUID nao entram na exportacao, e isso e uma lacuna
#: declarada e nao um esquecimento:** eles vivem cifrados no
#: `contact_endpoints`, que so o `kamba_identity` le, e decifra-los exige a DEK.
#: Fica no bloco com credor.
SQL_EXPORTAR_CONTACTO = f"""
  SELECT contact_id, criado_at, erased_at, merged_into, merged_at
    FROM platform.contacts
   WHERE {PREDICADO_DO_CONTACTO}
"""

SQL_EXPORTAR_CONVERSAS = f"""
  SELECT id, channel_id, mode, last_inbound_at, window_expires_at
    FROM platform.conversations
   WHERE {PREDICADO_DO_CONTACTO}
   ORDER BY last_inbound_at NULLS LAST, id
"""

#: As encomendas. **Mantem-se depois do apagamento** (criterio 5, retencao
#: fiscal), e por isso aparecem na exportacao de um titular que pode ja ter
#: pedido a eliminacao.
#:
#: O `deleted_at` entra na saida em vez de filtrar a linha: uma encomenda
#: anulada e um facto da relacao com o titular, e esconde-la de uma exportacao
#: dava-lhe uma copia dos seus dados que nao e a que a plataforma tem.
SQL_EXPORTAR_ENCOMENDAS = f"""
  SELECT id, numero_publico, estado, total_minor, currency, lines_snapshot,
         entrega_modo, paga_at, paga_via, entregue_at, deleted_at, criado_at
    FROM platform.orders_mirror
   WHERE {PREDICADO_DO_CONTACTO}
   ORDER BY criado_at, id
"""

#: Os consentimentos **em vigor**, da vista `consent_actual` (revisao `0015`).
#:
#: A vista e nao a tabela, e e o que o criterio quer dizer com «consentimentos
#: do titular»: o historico inteiro de `consent_event` e o rasto de cada
#: mudanca de ideias, e o que o titular pediu foi o que esta valido. O rasto
#: fica disponivel e nao entra aqui — dizer «consentiu e retirou nove vezes»
#: numa exportacao e responder a uma pergunta que ninguem fez.
SQL_EXPORTAR_CONSENTIMENTOS = f"""
  SELECT purpose, accepted, text_version, ocorrido_em
    FROM platform.consent_actual
   WHERE {PREDICADO_DO_CONTACTO}
   ORDER BY purpose
"""

#: As quatro coleccoes da exportacao, pelo nome que levam no JSON portatil.
#:
#: **E este mapa que o ensaio itera**, e e por isso que ele existe em vez de as
#: quatro consultas serem chamadas soltas: uma consulta nova entra aqui (senao a
#: exportacao nao a chama) e e medida pelo predicado do contacto sem ninguem se
#: lembrar dela. Uma lista escrita a mao no ensaio provava os itens de que
#: alguem se lembrou.
#:
#: Os quatro nomes sao os do criterio 2, por extenso: «contacto, conversas,
#: encomendas e consentimentos».
EXPORTACAO = {
    "contacto": SQL_EXPORTAR_CONTACTO,
    "conversas": SQL_EXPORTAR_CONVERSAS,
    "encomendas": SQL_EXPORTAR_ENCOMENDAS,
    "consentimentos": SQL_EXPORTAR_CONSENTIMENTOS,
}

# ---------------------------------------------------------------------------
# Rectificacao e oposicao (criterio 7)
# ---------------------------------------------------------------------------

#: A rectificacao de um telefone no cofre.
#:
#: Corre com o papel do **cofre** (`kamba_identity`), que e o unico com `UPDATE`
#: em `contact_endpoints` — o `kamba_app` nao tem `UPDATE` nenhum nessa tabela
#: (`0003`). Por isso esta consulta nao vive no mesmo caminho de ligacao das
#: outras, e o `dbapi.py` di-lo.
#:
#: Parametros: phone_enc, recolhido_at, contacto, finalidade.
SQL_RECTIFICAR_TELEFONE = f"""
  UPDATE platform.contact_endpoints
     SET phone_enc = %s, recolhido_at = %s
   WHERE {PREDICADO_DO_CONTACTO}
     AND tipo = 'telefone'
     AND finalidade = %s
  RETURNING id
"""

#: Escreve no `audit_log` (criterio 7, e criterio 1 para a recusa).
#:
#: `platform.audit_append` **nao devolve nada** de proposito (`0006`), e o
#: `payload_hash` e `sha256` calculado **na base** e nao no Python: e o que o
#: escritor do COM ja faz, e a razao e que um `sha256` feito do lado do cliente
#: era um segundo sitio onde a cadeia de *hashes* se pode calcular de outra
#: maneira.
#:
#: Parametros: tenant, actor_type, actor_id, action, entity, entity_id, turn_id,
#: texto a hashear.
SQL_AUDITAR = """
  SELECT platform.audit_append(
           %s::uuid, %s, %s, %s, %s, %s, %s, sha256(%s::bytea)
         )
"""

#: Registra a oposicao no `consent_event` (criterio 7).
#:
#: `accepted = false` por literal e nao por parametro: esta consulta **retira**
#: consentimento, e um `accepted` parametrizavel fazia dela uma consulta que
#: tambem o concede — e o caminho que concede consentimento e outro, do KAM-022,
#: com o texto mostrado e a prova da Meta. Uma consulta que faz as duas coisas
#: conforme o argumento e uma consulta onde um `True` por engano concede o que o
#: titular acabou de recusar.
SQL_REGISTAR_OPOSICAO = """
  INSERT INTO platform.consent_event
         (tenant_id, contact_id, purpose, text_version, accepted,
          canal, evidence_hash, ocorrido_em)
  VALUES (%s::uuid, %s::uuid, %s, %s, false, %s, %s, %s)
  ON CONFLICT (tenant_id, contact_id, purpose, evidence_hash) DO NOTHING
  RETURNING id
"""

# ---------------------------------------------------------------------------
# Eventos (criterio 3)
# ---------------------------------------------------------------------------

#: Poe um evento no *outbox* por `platform.evt_emitir` (revisao `0004`).
#:
#: **Nao ha publicador em Python**, e isso esta escrito no
#: `kamba_core.eventos.__init__`: o publicador e o reconciliador sao TypeScript
#: (KAM-005, KAM-006). O que ha e esta funcao SQL, que corre na transaccao do
#: produtor — e o *outbox* transaccional do ADR-009, pelo que o evento e a
#: linha do ledger ficam ou os dois ou nenhum.
#:
#: O `id`, o `seq`, a `particao` e o `registado_em` sao dela e nao deste modulo.
#: O `agregado.tipo` e `'contact'`, que e o que os dois contratos publicados
#: declaram com `const`.
#:
#: Parametros: tipo, versao, tenant, agregado_id, payload, classe_pii,
#: finalidades.
SQL_EMITIR = """
  SELECT platform.evt_emitir(
           %s, %s::smallint, %s::uuid, 'contact', %s, %s::jsonb, %s, %s::text[]
         )
"""
