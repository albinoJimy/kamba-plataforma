"""Gate 8: o inventario fechado de colunas de `platform`.

Cada coluna do schema esta aqui com o tipo, a nulidade e a omissao. Uma coluna
nova, ou uma coluna que mude, faz este teste falhar ate alguem a declarar — e e
esse o proposito, por duas razoes que a revisao adversarial mostrou:

**Telefone em claro.** O criterio de aceitacao 5 procurava `msisdn`, `telefone`
e `phone` no **nome** da coluna. Uma `contacto_dono text` ou uma
`whatsapp_cliente text` passavam. Uma lista de fragmentos proibidos nunca fecha;
uma lista de colunas permitidas fecha: quem acrescentar uma coluna de texto tem
de a escrever aqui, e ao escreve-la responde a pergunta «isto guarda dados
pessoais?» na coluna `pessoal`.

**NOT NULL e omissoes.** Retirar o `NOT NULL` a treze colunas, ou trocar a
omissao de `origem` para `plataforma`, deixava a suite verde.

O que isto **nao** garante, e nenhum schema garante: que ninguem grave um
telefone em `nome` ou em `zona`. Isso e do validador de entrada e do KAM-068.
"""

from __future__ import annotations

from tests.base import ComBase

SIM, NAO = "YES", "NO"

#: tabela -> coluna -> (tipo, anulavel, omissao, guarda dados pessoais?)
#:
#: `pessoal`: `nao`, ou a razao pela qual e aceitavel. Nenhuma coluna aqui guarda
#: telefone, BSUID ou nome de pessoa singular em claro.
INVENTARIO = {
    "tenants": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tipo": ("text", NAO, None, "nao"),
        "nome": ("text", NAO, None, "nome do negocio, nao de pessoa singular"),
        "nif": ("text", SIM, None, "identificador fiscal do negocio"),
        "contacto_negocio_enc": ("bytea", SIM, None, "cifrado em aplicacao (ADR-010)"),
        "owner_contact_id": ("uuid", SIM, None, "referencia opaca a contacts (KAM-008)"),
        "zona": ("text", SIM, None, "zona do negocio"),
        "plus_code": ("text", SIM, None, "localizacao do negocio"),
        "plano": ("text", NAO, "'free'::text", "nao"),
        "estado": ("text", NAO, "'onboarding'::text", "nao"),
        "medusa_sales_channel_id": ("text", SIM, None, "nao"),
        "medusa_merchant_id": ("text", SIM, None, "nao"),
        "chatwoot_account_id": ("integer", SIM, None, "nao"),
        "litellm_key_id": ("text", SIM, None, "identificador da chave, nao a chave"),
        "fuso_horario": ("text", NAO, "'Africa/Luanda'::text", "nao"),
        "verificado_at": ("timestamp with time zone", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "deleted_at": ("timestamp with time zone", SIM, None, "nao"),
        # KAM-090 (0040): a primeira entrada em `ativo`, que so o *trigger* do
        # gate escreve. E o que distingue uma activacao nova de uma reactivacao.
        "primeira_activacao_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "tenant_channels": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "waba_id": ("text", NAO, None, "identificador da conta na Meta"),
        "waac_id": ("text", SIM, None, "identificador da conta na Meta"),
        "phone_number_id": ("text", NAO, None, "identificador opaco da Meta; nao e um telefone"),
        "channel_mode": ("text", NAO, None, "nao"),
        "vertical": ("text", NAO, None, "nao"),
        "origem": ("text", NAO, "'pme'::text", "nao"),
        "estado": ("text", NAO, "'pendente'::text", "nao"),
        "token_ref": ("text", NAO, None, "referencia opaca ao segredo; nunca o token"),
        "quality_rating": ("text", SIM, None, "nao"),
        "messaging_limit": ("text", SIM, None, "nao"),
        "free_tier_used": ("integer", NAO, "0", "nao"),
        "free_tier_month": ("date", SIM, None, "nao"),
        "coexistence_synced_at": ("timestamp with time zone", SIM, None, "nao"),
        "last_account_update_at": ("timestamp with time zone", SIM, None, "nao"),
        # KAM-023, revisao 0013. O `motivo_restricao` e anulavel e o `NULL` e o
        # estado normal: «este canal nao esta restrito».
        "motivo_restricao": ("text", SIM, None, "nao"),
        "meta_error_codes_seen": (
            "ARRAY",
            NAO,
            "'{}'::integer[]",
            "codigos de erro da Meta; nao e um identificador de pessoa",
        ),
        # KAM-021, revisao 0014. Atributo do **portfolio** e nao do canal:
        # guarda-se por canal porque nao ha tabela de WABA neste esquema.
        "max_phone_numbers_per_business": ("integer", SIM, None, "nao"),
    },
    "entitlements": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "modulo": ("text", NAO, None, "nao"),
        "limites": ("jsonb", NAO, "'{}'::jsonb", "nao"),
        "ativo": ("boolean", NAO, "true", "nao"),
    },
    # ------------------------------------------------------------ KAM-008
    # Identidade de contacto. Aqui a pergunta «guarda dados pessoais?» tem
    # resposta afirmativa em varias linhas, e cada uma diz **em que forma**:
    # nenhuma guarda BSUID nem telefone em claro.
    "contacts": {
        "contact_id": ("uuid", NAO, "gen_random_uuid()", "identificador aleatorio; nunca derivado do telefone (ADR-010)"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "phone_hmac": ("bytea", SIM, None, "pseudonimo do telefone: HMAC-SHA256 com segredo do cofre; continua dado pessoal"),
        "hmac_kid": ("text", SIM, None, "versao do segredo do HMAC; nao e o segredo"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "erased_at": ("timestamp with time zone", SIM, None, "nao"),
        "merged_into": ("uuid", SIM, None, "referencia opaca ao contacto que absorveu este"),
        "merged_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "contact_deks": {
        "dek_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": ("uuid", NAO, None, "referencia opaca ao contacto"),
        "wrapped_dek": ("bytea", SIM, None, "chave de dados embrulhada pela KEK do cofre; nao e dado pessoal, e e o que o apagamento destroi"),
        "kek_id": ("text", NAO, None, "versao da KEK; nao e a chave"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "destroyed_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "contact_endpoints": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": ("uuid", NAO, None, "referencia opaca ao contacto"),
        "tipo": ("text", NAO, None, "nao"),
        "bsuid_hmac": ("bytea", SIM, None, "pseudonimo do BSUID: HMAC-SHA256 com segredo do cofre; so para correspondencia"),
        "hmac_kid": ("text", SIM, None, "versao do segredo do HMAC; nao e o segredo"),
        "bsuid_enc": ("bytea", SIM, None, "BSUID cifrado (AES-256-GCM, DEK por contacto)"),
        "phone_enc": ("bytea", SIM, None, "telefone cifrado (AES-256-GCM, DEK por contacto)"),
        "dek_id": ("uuid", NAO, None, "nao"),
        "finalidade": ("text", SIM, None, "finalidade do tratamento do telefone; nao identifica ninguem"),
        "recolhido_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "expira_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "hmac_key_versions": {
        "kid": ("text", NAO, None, "identificador da versao do segredo; nao e o segredo"),
        "estado": ("text", NAO, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # ------------------------------------------------------------ KAM-005
    # Eventos. A resposta a «guarda dados pessoais?» e a mesma em todas as
    # colunas `envelope`: o envelope v1 **nao leva PII P2** (ADR-010,
    # `docs/tecnica/06` §7.1) — a referencia a uma pessoa e `contact_id`, dentro
    # do `payload`, e e opaca. Quem o garante nao e este inventario: e a guarda
    # de PII do `evt_emitir` (criterio 6), o espelho dela no publicador, e o
    # schema fechado de cada evento (KAM-007).
    "events_outbox": {
        "id": ("bigint", NAO, None, "nao"),
        "event_id": ("uuid", NAO, None, "identificador do evento (UUIDv7); nao identifica pessoas"),
        "tipo": ("text", NAO, None, "nao"),
        "versao": ("smallint", NAO, None, "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "agregado_tipo": ("text", NAO, None, "nao"),
        "agregado_id": ("text", NAO, None, "identificador do agregado (pedido, marcacao); opaco"),
        "agregado_seq": ("bigint", NAO, None, "nao"),
        "particao": ("smallint", NAO, None, "nao"),
        "envelope": ("jsonb", NAO, None, "envelope v1 sem PII P2; a referencia a pessoa e contact_id, opaco (ADR-010)"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "publicado_at": ("timestamp with time zone", SIM, None, "nao"),
        "tentativas": ("integer", NAO, "0", "nao"),
        "proxima_tentativa_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "evt_agregado_seq": {
        # O `tenant_id` e um desvio ao DDL do `docs/tecnica/06` §6.1, e esta
        # explicado na revisao: sem ele o contador e global e um tenant corta a
        # emissao de eventos de outro (ANALISE-20, achado 2).
        "tenant_id": ("uuid", NAO, None, "nao"),
        "agregado_tipo": ("text", NAO, None, "nao"),
        "agregado_id": ("text", NAO, None, "identificador do agregado; opaco"),
        "seq": ("bigint", NAO, None, "nao"),
    },
    "evt_subscricoes": {
        "consumer": ("text", NAO, None, "nao"),
        "tipo": ("text", NAO, None, "nao"),
        "versao_max": ("smallint", NAO, "1", "nao"),
        "finalidade": ("text", NAO, None, "finalidade de uso do consumidor; nao identifica ninguem"),
        "exige_ordem": ("boolean", NAO, "false", "nao"),
        "activo": ("boolean", NAO, "true", "nao"),
    },
    "events_log": {
        "event_id": ("uuid", NAO, None, "identificador do evento (UUIDv7); nao identifica pessoas"),
        "tipo": ("text", NAO, None, "nao"),
        "versao": ("smallint", NAO, None, "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "agregado_tipo": ("text", NAO, None, "nao"),
        "agregado_id": ("text", NAO, None, "identificador do agregado; opaco"),
        "agregado_seq": ("bigint", NAO, None, "nao"),
        "ocorrido_em": ("timestamp with time zone", NAO, None, "nao"),
        "registado_em": ("timestamp with time zone", NAO, None, "nao"),
        "classe_pii": ("text", NAO, None, "classe do dado do envelope; nao e dado"),
        "envelope": ("jsonb", NAO, None, "envelope v1 sem PII P2; a referencia a pessoa e contact_id, opaco (ADR-010)"),
    },
    # ---------------------------------------------------------- KAM-006 (0005)
    "events_consumed": {
        "consumer": ("text", NAO, None, "nao"),
        "event_id": ("uuid", NAO, None, "identificador do evento (UUIDv7); nao identifica pessoas"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "agregado_tipo": ("text", NAO, None, "nao"),
        "agregado_id": ("text", NAO, None, "identificador do agregado; opaco"),
        "agregado_seq": ("bigint", NAO, None, "nao"),
        "processado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "events_dlq": {
        "id": ("bigint", NAO, None, "nao"),
        "consumer": ("text", NAO, None, "nao"),
        "event_id": ("uuid", NAO, None, "identificador do evento (UUIDv7); nao identifica pessoas"),
        "tipo": ("text", NAO, None, "nao"),
        "versao": ("smallint", NAO, None, "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "envelope": ("jsonb", NAO, None, "envelope v1 sem PII P2; a referencia a pessoa e contact_id, opaco (ADR-010)"),
        "erro": ("text", NAO, None, "mensagem de erro do consumidor; nao leva payload"),
        "tentativas": ("integer", NAO, None, "nao"),
        "estado": ("text", NAO, "'aberta'::text", "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "resolvido_at": ("timestamp with time zone", SIM, None, "nao"),
        "resolvido_por": ("text", SIM, None, "nome de quem resolveu: pessoa da plataforma, nao titular de dados"),
    },
    "evt_dlq_aprovacoes": {
        "dlq_id": ("bigint", NAO, None, "nao"),
        "aprovador": ("text", NAO, None, "nome de quem aprovou: pessoa da plataforma, nao titular de dados"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "evt_acoes": {
        "idempotency_key": ("text", NAO, None, "consumer:event_id:accao; nao identifica pessoas"),
        "consumer": ("text", NAO, None, "nao"),
        "event_id": ("uuid", NAO, None, "identificador do evento (UUIDv7); nao identifica pessoas"),
        "accao": ("text", NAO, None, "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "estado": ("text", NAO, "'em_curso'::text", "nao"),
        "resultado": ("jsonb", SIM, None, "desfecho da accao externa; nao leva conteudo de mensagem"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "concluido_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # ------------------------------------------------------- KAM-012 (0006)
    #
    # **A resposta a «guarda dados pessoais?» e a razao de ser desta tabela.**
    # Nenhuma coluna guarda conteudo: o que seria conteudo entra em
    # `payload_hash`, que e SHA-256 de 32 bytes. O `actor_id` identifica quem
    # agiu — e esse e o ponto de uma auditoria —, mas e uma referencia e nao um
    # dado: `contact_id`, utilizador de staff ou nome de job, nunca telefone
    # nem nome. O `docs/tecnica/06` §7.6 explica porque e que um registo
    # imutavel so sobrevive ao direito de apagamento se for assim.
    "audit_log": {
        "id": ("bigint", NAO, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "tenant_id": ("uuid", SIM, None, "nao; nulo nas accoes de plataforma"),
        "actor_type": ("text", NAO, None, "nao"),
        "actor_id": (
            "text", NAO, None,
            "referencia a quem agiu (contact_id, utilizador de staff, nome de job); "
            "nunca telefone nem nome",
        ),
        "action": ("text", NAO, None, "nao"),
        "entity": ("text", NAO, None, "nao"),
        "entity_id": ("text", NAO, None, "identificador da entidade auditada; nao de pessoa"),
        "turn_id": ("text", SIM, None, "identificador do turno de conversa; nao leva conteudo"),
        "payload_hash": (
            "bytea", NAO, None,
            "**hash** do antes/depois, nunca o conteudo; 32 bytes, por CHECK",
        ),
        # A omissao existe para que o `INSERT` do chamador nao tenha de as
        # mencionar: quem insere **nao as pode escrever** (o `GRANT` e por
        # coluna e nao as inclui), e e o trigger `audit_encadear` que lhes poe
        # o valor verdadeiro antes de a linha existir.
        "prev_hash": (
            "bytea", NAO,
            "'\\x0000000000000000000000000000000000000000000000000000000000000000'::bytea",
            "nao; hash opaco",
        ),
        "row_hash": (
            "bytea", NAO,
            "'\\x0000000000000000000000000000000000000000000000000000000000000000'::bytea",
            "nao; hash opaco",
        ),
    },
    "audit_heads": {
        "tenant_id": ("uuid", SIM, None, "nao; nulo na cadeia de plataforma"),
        "chave": (
            "uuid", NAO, None,
            "nao; coluna gerada, `coalesce(tenant_id, zero)`, para a chave primaria "
            "aceitar a cadeia sem tenant",
        ),
        "last_hash": ("bytea", NAO, None, "nao; hash opaco"),
    },
    # ----------------------------------------------- KAM-009 (0007)
    #
    # Nenhuma destas colunas guarda dados pessoais, e nenhuma e de texto
    # livre: a `chave_limite` e um nome de chave do dicionario §3.2 e a
    # `idempotency_key` e escolhida por quem chama. **A `idempotency_key` e a
    # unica que merece a pergunta**, porque e a unica que um chamador escreve
    # a vontade: se alguem a derivar de um telefone, entra aqui um telefone.
    # Nao se resolve no schema — resolve-se em quem a gera, e esta dito na
    # biblioteca.
    "tenant_usage": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "chave_limite": ("text", NAO, None, "nao; nome de chave do dicionario §3.2"),
        "periodo": ("date", NAO, None, "nao"),
        "valor": ("bigint", NAO, "0", "nao"),
        "actualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "usage_ledger": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "idempotency_key": (
            "text", NAO, None,
            "nao, e e responsabilidade de quem a gera: e o unico texto livre "
            "destas duas tabelas",
        ),
        "chave_limite": ("text", NAO, None, "nao; nome de chave do dicionario §3.2"),
        "periodo": ("date", NAO, None, "nao"),
        "quantidade": ("bigint", NAO, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # ------------------------------------------------------------ KAM-013
    # Entrada de canal. **Nenhuma das duas tem `tenant_id`**: o GWY e o
    # endpoint unico da Meta e o tenant so nasce no CHR (KAM-014).
    #
    # A pergunta «guarda dados pessoais?» tem aqui a resposta mais
    # desconfortavel do inventario, e esta escrita por extenso na linha do
    # `payload`: **sim, pode guardar**. E a unica coluna do schema que guarda
    # corpo de conversa, e existe porque o criterio 6 do KAM-013 a pede para
    # se diagnosticar o que nao encaixou.
    "inbound_events": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "kind": ("text", NAO, None, "nao"),
        "event_key": (
            "text",
            NAO,
            None,
            "wamid ou wamid:estado; identificador de mensagem da Meta, que leva o "
            "numero do interlocutor codificado em base64 (INDICIO, docs/logs.md "
            "§2.1). Nunca sai para um log em claro: la vai `id_opaco`",
        ),
        "waba_id": ("text", NAO, None, "identificador da conta na Meta"),
        "phone_number_id": (
            "text",
            SIM,
            None,
            "identificador opaco da Meta; nao e um telefone",
        ),
        "recebido_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "processado_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # KAM-014. Oito colunas, e **nenhuma guarda dado pessoal**: o contacto
    # entra por `contact_id`, que e um UUID aleatorio (ADR-010), e nao ha aqui
    # texto livre nenhum — nem conteudo de mensagem, nem `display_name`. E a
    # primeira tabela deste caminho com `tenant_id`, e por isso a primeira com
    # RLS: as duas de cima nao o tem por desenho.
    "conversations": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "referencia opaca a contacts (ADR-010); nao e telefone nem BSUID",
        ),
        "channel_id": ("uuid", NAO, None, "nao"),
        "mode": ("text", NAO, "'bot'::text", "nao"),
        "last_inbound_at": ("timestamp with time zone", SIM, None, "nao"),
        "window_expires_at": ("timestamp with time zone", SIM, None, "nao"),
        "last_human_activity_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # KAM-015. As duas tabelas da saida de canal.
    #
    # **Tres colunas pedem uma frase cada**, e sao as unicas desta revisao que
    # tocam em dados pessoais ou em identificadores externos: o `wamid`, pela
    # mesma razao do `inbound_events.event_key`; o `template_name`, que e nome
    # de artefacto e nao de pessoa, mas que viaja para a Meta; e o `pricing`,
    # que nao e dado pessoal mas e **dado financeiro** e o unico registo do que
    # a Meta cobrou. O destinatario entra por `contact_id`, que e um UUID
    # aleatorio (ADR-010): nao ha telefone nem BSUID nesta tabela.
    "outbound_messages": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "channel_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "referencia opaca a contacts (ADR-010); nao e telefone nem BSUID",
        ),
        "conversation_id": ("uuid", NAO, None, "nao"),
        "idempotency_key": (
            "text",
            NAO,
            None,
            "chave nossa, gerada por quem envia; unica por (tenant_id, "
            "idempotency_key) e nao global, para que um tenant nao suprima "
            "mensagens de outro adivinhando-a (emenda 1.21, divergencia 2)",
        ),
        "wamid": (
            "text",
            SIM,
            None,
            "identificador de mensagem da Meta, que leva o numero do "
            "interlocutor codificado em base64 (INDICIO, docs/logs.md §2.1). "
            "Nunca sai para um log em claro: la vai `id_opaco`",
        ),
        "kind": ("text", NAO, None, "nao"),
        "template_name": (
            "text",
            SIM,
            None,
            "nome de artefacto e nao de pessoa, mas viaja para a Meta e "
            "identifica o tenant junto dela; NULL para `service`, obrigatorio "
            "nas outras tres (outbound_messages_template_ck)",
        ),
        "state": ("text", NAO, "'queued'::text", "nao"),
        "pricing": (
            "jsonb",
            SIM,
            None,
            "nao e dado pessoal, e **e** dado financeiro: o pricing que chegou "
            "nos statuses e o unico registo do que a Meta cobrou, e e dele que "
            "sai o custo por tenant (docs/tecnica/01 §16)",
        ),
        "error_code": ("integer", SIM, None, "nao"),
        "created_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "delivered_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # KAM-015. **Nenhuma coluna guarda dado pessoal**: um template e um
    # artefacto do tenant, nao de um contacto. O `body_hash` e o que permite
    # dizer «o corpo aprovado nao e o corpo que estamos a enviar», e e resumo e
    # nao corpo — de propósito, para que o texto aprovado nao viva aqui.
    "message_templates": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "name": ("text", NAO, None, "nome do template junto da Meta"),
        "lang": ("text", NAO, None, "nao"),
        "category": ("text", NAO, None, "nao"),
        "status": ("text", NAO, "'pending'::text", "nao"),
        "quality": ("text", SIM, None, "nao"),
        "meta_template_id": (
            "text",
            SIM,
            None,
            "identificador opaco da Meta; so existe depois de ela aceitar",
        ),
        "body_hash": (
            "text",
            NAO,
            None,
            "resumo do corpo aprovado, e nao o corpo: o texto aprovado nao vive "
            "nesta tabela",
        ),
        "bloqueado_em": ("timestamp with time zone", SIM, None, "nao"),
        "updated_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "unrouted_events": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "kind": ("text", NAO, None, "nao"),
        "event_key": ("text", NAO, None, "ver `inbound_events.event_key`"),
        "waba_id": ("text", SIM, None, "identificador da conta na Meta"),
        "phone_number_id": (
            "text",
            SIM,
            None,
            "identificador opaco da Meta; nao e um telefone",
        ),
        "motivo": ("text", NAO, None, "nao"),
        "payload": (
            "text",
            SIM,
            None,
            "SIM — o corpo bruto do webhook em base64. Pode conter telefone e "
            "texto de mensagem. E a unica coluna do schema que guarda corpo de "
            "conversa, e esta aqui porque sem ela nao se diagnostica uma "
            "quarentena. Retencao de 7 dias (*proposta*, KAM-013), a impor em "
            "KAM-071. `kamba_app` escreve e **nao le** (sem GRANT SELECT)",
        ),
        "recebido_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "processado_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # KAM-019. As duas tabelas da passagem a humano.
    #
    # **Duas colunas pedem uma frase cada, e sao de classes diferentes de dado
    # pessoal.** O `resolver` e o **primeiro dado pessoal de um trabalhador da
    # PME** a entrar no schema: todas as outras colunas pessoais deste
    # inventario sao de clientes finais, e esta e de quem atende. E o `motivo`
    # e texto livre que uma pessoa pode ter escrito — nao e o corpo da
    # conversa, mas tambem nao e um valor de lista fechada, e por isso nao se
    # declara `nao`.
    #
    # O `external_id` e o `account_id`/`inbox_id`/`bot_id` sao identificadores
    # opacos de um terceiro, pela mesma logica do `meta_template_id`: nao
    # identificam uma pessoa, identificam um recurso que o provedor criou.
    "handoffs": {
        "handoff_id": (
            "text",
            NAO,
            None,
            "resumo de `(thread_id, ordinal)`; nao e identificador de pessoa",
        ),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "conversation_id": ("uuid", NAO, None, "nao"),
        "status": ("text", NAO, "'waiting'::text", "nao"),
        "motivo": (
            "text",
            NAO,
            None,
            "texto livre com a razao da passagem; pode ter sido escrito por "
            "uma pessoa, e por isso nao se declara `nao`. Nao e o corpo da "
            "conversa, que vive no provedor e nao aqui",
        ),
        "external_id": (
            "text",
            SIM,
            None,
            "identificador opaco da conversa no provedor; so existe depois de "
            "ela ser criada la",
        ),
        "opened_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "resumed_at": ("timestamp with time zone", SIM, None, "nao"),
        "resolver": (
            "text",
            SIM,
            None,
            "SIM — identificador opaco do agente humano no provedor "
            "(`docs/tecnica/02` §11, «resolver (humano)»). E o **primeiro dado "
            "pessoal de um trabalhador da PME** neste schema; todas as outras "
            "colunas pessoais aqui sao de clientes finais. Nunca nome, e-mail "
            "nem telefone, e nao e um `contact_id` da KAMBA",
        ),
    },
    "handoff_accounts": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "provedor": ("text", NAO, None, "nao"),
        "account_id": ("bigint", NAO, None, "identificador opaco da conta no provedor"),
        "inbox_id": ("bigint", NAO, None, "identificador opaco da caixa no provedor"),
        "bot_id": ("bigint", NAO, None, "identificador opaco do bot no provedor"),
        # As duas da emenda 1.23, que vieram do spike. O `provider_user_id` e o
        # identificador do **utilizador** da conta no provedor, e a pergunta
        # «guarda dados pessoais?» tem aqui a resposta menos obvia da tabela:
        # **nao**, e e por desenho. O utilizador nao e uma pessoa da PME — e um
        # utilizador de servico que a plataforma cria para provisionar e criar
        # contactos, com um `email` de dominio `.invalid`. As pessoas da PME
        # entram pelo painel com contas proprias, que sao do KAM-091, e essas
        # sim guardam dados pessoais. O unico dado pessoal de um trabalhador
        # neste esquema continua a ser o `handoffs.resolver`.
        "provider_user_id": (
            "bigint",
            NAO,
            None,
            "identificador opaco do utilizador de servico no provedor",
        ),
        "user_token_ref": (
            "text",
            NAO,
            None,
            "referencia opaca ao segredo do utilizador da conta; nunca o token",
        ),
        "token_ref": (
            "text",
            NAO,
            None,
            "referencia opaca ao segredo; nunca o token (ver "
            "`tenant_channels.token_ref`)",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "updated_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # KAM-020. **A pergunta «guarda dados pessoais?» e aqui a mais delicada do
    # esquema**, e a resposta e: a tabela nao, o que ela aponta sim.
    #
    # Nenhuma coluna desta tabela contem dados de uma pessoa. O `contact_id` e
    # uma referencia (como em toda a parte), o `wamid` e o `media_id` sao
    # identificadores de terceiro, e o `storage_ref` e uma chave de objecto. Mas
    # o **objecto** que o `storage_ref` aponta e a voz, a cara ou o documento de
    # um cliente final, e e por isso que esta tabela tem `retain_until` e que o
    # `docs/tecnica/08` §7.5 lhe poe um prazo. A politica de privacidade desta
    # tabela nao se le nas colunas: le-se no que elas localizam.
    # KAM-021, revisao 0014. O registo das transicoes de qualidade do canal.
    "channel_quality_log": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "channel_id": ("uuid", NAO, None, "nao"),
        "evento": ("text", NAO, None, "nao"),
        # Anulavel, e o `NULL` tem significado: e a **primeira** linha de um
        # canal, onde nao havia valor anterior.
        "valor_anterior": ("text", SIM, None, "nao"),
        # Guarda o que a Meta anunciou **tal e qual**, mesmo quando nao e um dos
        # tres que conhecemos: o criterio 1 manda registar um valor desconhecido
        # sem falhar.
        "valor_novo": ("text", NAO, None, "nao"),
        "ocorrido_em": ("timestamp with time zone", NAO, "now()", "nao"),
        "event_key": (
            "text",
            NAO,
            None,
            "resumo de phone_number_id, tipo, valor e hora da Meta; nao e PII",
        ),
    },
    "media_assets": {
        "asset_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": ("uuid", NAO, None, "nao"),
        "conversation_id": ("uuid", NAO, None, "nao"),
        "wamid": ("text", NAO, None, "identificador da mensagem no WhatsApp"),
        # **Nao e um URL.** O URL temporario que ele resolve nunca e
        # persistido, aqui nem em sitio nenhum (criterio 3 do KAM-020).
        "media_id": ("text", NAO, None, "identificador opaco do objecto na Meta"),
        "classe": ("text", NAO, None, "nao"),
        # Anulaveis ate a descarga: a linha nasce em `pendente` e o
        # `content_type` **real** so se sabe da resposta — confiar no que o
        # webhook anuncia era aceitar que ele mente.
        "content_type": ("text", SIM, None, "nao"),
        "size": ("bigint", SIM, None, "nao"),
        "sha256": (
            "text",
            SIM,
            None,
            "resumo do conteudo; **nao** e identificador de pessoa, mas dois "
            "iguais dizem que o conteudo e o mesmo",
        ),
        "storage_ref": (
            "text",
            SIM,
            None,
            "chave do objecto nosso; o objecto que ela aponta pode ser a voz "
            "ou a cara de um cliente final",
        ),
        "estado": ("text", NAO, None, "nao"),
        "retain_until": ("timestamp with time zone", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # ------------------------------------------------- KAM-022 (0015)
    #
    # O texto do aviso, versionado. **Sem `tenant_id`**, e nao e esquecimento: e
    # um texto juridico revisto uma vez e mostrado por todas as lojas, pelo que
    # nao e dado de tenant. Consequencia directa — nao entra no X-05 nem no
    # `ci/rls_exceptions.yaml`, porque o gate 6 pergunta por RLS as tabelas que
    # **tem** a coluna.
    "consent_texts": {
        "version": ("text", NAO, None, "nao"),
        "purpose": ("text", NAO, None, "nao"),
        "texto": (
            "text",
            NAO,
            None,
            "nao — e o aviso que se mostra ao cliente, texto juridico de "
            "plataforma, com um marcador no lugar do nome da loja",
        ),
        "hash": ("bytea", NAO, None, "nao"),
        "vigente_desde": ("timestamp with time zone", NAO, None, "nao"),
        "criado_em": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # A prova, append-only.
    "consent_event": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "referencia opaca a contacts (ADR-010): e o uuid e nunca o "
            "telefone, e e isso que o DoD de privacidade deste ticket pede",
        ),
        "purpose": ("text", NAO, None, "nao"),
        "text_version": ("text", NAO, None, "nao"),
        "accepted": ("boolean", NAO, None, "nao"),
        "canal": ("text", NAO, None, "nao — e o transporte, nao o interlocutor"),
        "evidence_hash": (
            "bytea",
            NAO,
            None,
            "resumo de 32 bytes do texto mostrado, do contact_id, do wamid do "
            "botao e da hora. **Nao e reversivel e nao e identificador de "
            "pessoa**, mas dois iguais dizem que a mesma pessoa viu o mesmo "
            "texto e carregou no mesmo botao — e e isso que o torna prova",
        ),
        "ocorrido_em": ("timestamp with time zone", NAO, "now()", "nao"),
        # A hora em que **nos** escrevemos, e e o desempate da vista. A unica
        # coluna deste esquema com `clock_timestamp()` por omissao, e a razao
        # esta na revisao: o `now()` e o inicio da transaccao e empatava.
        "registado_em": (
            "timestamp with time zone",
            NAO,
            "clock_timestamp()",
            "nao",
        ),
    },
    # ------------------------------------------------- KAM-016 (0017)
    #
    # A tentativa de ligar um numero pelo Embedded Signup v4. Treze colunas, e o
    # bloco do ticket nomeia quatro: as nove restantes tem cada uma o criterio
    # que a obriga (dicionario §3.20).
    #
    # **Nenhuma coluna desta tabela e dado pessoal de cliente final**, e isso nao
    # e sorte: o onboarding e entre a plataforma e o **dono** da PME, e o DoD do
    # ticket di-lo — «Privacidade — nenhum dado de cliente final tratado». Os
    # identificadores que ca estao sao chaves opacas da Meta (o `waba_id`, o
    # `waac_id`, o `phone_number_id`) e referencias nossas.
    "channel_onboarding": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "channel_id": (
            "uuid",
            SIM,
            None,
            "nao — e nulo ate a troca do code criar a linha de tenant_channels, "
            "e nulo outra vez depois de a compensacao a apagar",
        ),
        "waba_id": (
            "text",
            NAO,
            None,
            "nao — e a chave opaca que a Meta da a conta de negocio, nao um "
            "identificador de pessoa",
        ),
        "waac_id": (
            "text",
            SIM,
            None,
            "nao — **nulo hoje** e de proposito: a Fase 3 do novo modelo de "
            "contas (H1 2028, CONFIRMADO em E1 §3) passa a exigi-lo nos "
            "caminhos da API, e guardar os dois identificadores hoje e o "
            "criterio 8",
        ),
        "phone_number_id": (
            "text",
            NAO,
            None,
            "nao — **nao e um telefone**: e uma chave opaca da Cloud API, como "
            "o COMMENT da coluna homonima de tenant_channels diz desde a 0001",
        ),
        "code_hash": (
            "bytea",
            NAO,
            None,
            "nao — e o sha256 do code do Embedded Signup, **nunca o code**. O "
            "code e trocavel por um token de cliente, logo e um segredo com o "
            "valor do token; o resumo serve para a igualdade que a idempotencia "
            "precisa e nao serve para trocar",
        ),
        "fase": ("text", NAO, "'iniciado'::text", "nao"),
        "recursos_criados": (
            "jsonb",
            NAO,
            "'[]'::jsonb",
            "nao — a lista dos recursos que cada passo criou, e o `ref` de cada "
            "um e uma referencia opaca (SecretRef, channel_id, waba_id) e nunca "
            "um valor de segredo",
        ),
        "pin_ref": (
            "text",
            SIM,
            None,
            "nao — e a referencia opaca ao PIN 2FA no cofre (meta_pin_2fa), "
            "nunca o PIN",
        ),
        "motivo": (
            "text",
            SIM,
            None,
            "nao — e texto nosso a dizer porque e que o onboarding nao acabou, "
            "lido por uma pessoa",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "actualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # ------------------------------------------------- KAM-017 (0018)
    #
    # O estado de coexistencia de um canal. Dezoito colunas, e o bloco do ticket
    # **nao nomeia nenhuma** — o que ele nomeia e o `coexistence_synced_at`, que
    # e de `tenant_channels` e existe desde a `0001` (dicionario §3.22).
    #
    # **Nenhuma coluna desta tabela guarda conteudo de mensagem, e isso nao e
    # sorte:** o criterio 2 proibe persistir ou indexar o corpo das mensagens de
    # historico no Piloto, e a forma de garantir a regra e **nao haver onde**.
    # Das dezoito, nao ha uma unica coluna de texto livre: as quatro de texto sao
    # dominios fechados (`estado`, `motivo_desligamento`) ou um *array* com
    # `CHECK` de conteudo (`passos_feitos`). O que o historico deixa aqui sao
    # **contagens**.
    #
    # Nenhuma e dado pessoal de cliente final pela mesma razao da tabela acima:
    # os contactos que o historico traz sao resolvidos pela porta do KAM-008 e
    # vivem em `contacts`, por `contact_id` — o telefone nunca e chave (ADR-010).
    "channel_coexistence": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "channel_id": ("uuid", NAO, None, "nao"),
        "estado": ("text", NAO, "'a_sincronizar'::text", "nao"),
        "passos_feitos": (
            "ARRAY",
            NAO,
            "'{}'::text[]",
            "nao — os dois passos que o E1 §2 nomeia, com CHECK de conteudo. "
            "E o conjunto que faz o «2.a execucao = no-op» do criterio 3 ser "
            "do PostgreSQL e nao de um if",
        ),
        "iniciado_em": ("timestamp with time zone", NAO, "now()", "nao"),
        "prazo_em": (
            "timestamp with time zone",
            NAO,
            None,
            "nao — **coluna e nao calculo**, e e isso que torna o relogio "
            "acelerado do criterio 3 possivel sem mexer no servidor",
        ),
        "alertado_em": ("timestamp with time zone", SIM, None, "nao"),
        "concluido_em": ("timestamp with time zone", SIM, None, "nao"),
        "contactos_vistos": ("integer", NAO, "0", "nao"),
        "mensagens_vistas": (
            "integer",
            NAO,
            "0",
            "nao — **uma contagem, nunca um corpo**: o criterio 2 proibe "
            "persistir o conteudo das mensagens de historico no Piloto, e a "
            "base legal para o usar e parecer por dar (KAM-104)",
        ),
        "meta_error_code": (
            "integer",
            SIM,
            None,
            "nao — hoje so o 2593109. E integer e nao text porque **nao pode "
            "ser registado**: tem sete digitos, e a politica de logs recusa "
            "mais de seis em qualquer campo de texto (DIGITOS_MAXIMOS), nos "
            "dois campos onde caberia (outcome e error_code)",
        ),
        "ultimo_echo_em": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — quando chegou o ultimo echo que nao foi nosso. E um "
            "instante, nao o conteudo nem o autor",
        ),
        "avisado_em": ("timestamp with time zone", SIM, None, "nao"),
        "motivo_desligamento": (
            "text",
            SIM,
            None,
            "nao — um dos seis motivos de PARTNER_REMOVED (E1 §2), em "
            "minusculas porque sao tambem outcome de registo e a gramatica "
            "desse campo so aceita minusculas",
        ),
        "desligado_em": ("timestamp with time zone", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "actualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # KAM-115: o contacto alternativo do dono.
    #
    # **E a unica tabela do esquema cujo conteudo e, por definicao, um dado
    # pessoal** — um endereco de e-mail de uma pessoa singular —, e e por isso
    # que nao ha coluna em claro: o `endereco_enc` e `bytea` e o DoD do ticket
    # di-lo por extenso, «endereco do dono so em cifra e nunca em logs». A
    # diferenca face ao `contacto_negocio_enc` da `0001` e so o sujeito: la e o
    # contacto da empresa, aqui e o do dono como pessoa.
    #
    # Nao ha HMAC de pesquisa, ao contrario do `contact_endpoints` do KAM-008:
    # la ha pesquisa por valor (chega um telefone num webhook e e preciso achar
    # o contacto), aqui entra-se sempre pelo `tenant_id`. Um HMAC sem quem o
    # consulte era uma chave a mais para guardar e rodar.
    "owner_contacts": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "canal": (
            "text",
            NAO,
            "'email'::text",
            "nao — e o transporte e nao o interlocutor, como o consent_event.canal. "
            "Dominio de **um** valor: o painel nao tem endereco e o sms e o KAM-116",
        ),
        "endereco_enc": (
            "bytea",
            NAO,
            None,
            "**sim, e e o unico sitio do esquema onde isto esta certo**: e o "
            "e-mail do dono, cifrado com AES-256-GCM e DEK por tenant derivada "
            "da KEK kek_contacto_dono. Nao existe coluna em claro, e e assim "
            "que a regra se garante — uma regra que depende de ninguem "
            "escrever onde da para escrever nao e uma regra",
        ),
        "verificado_at": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — nulo e o estado normal de um endereco acabado de captar, e "
            "um endereco nao verificado **nao recebe avisos**: quem o impoe e o "
            "predicado da consulta e nao um if (criterio 6)",
        ),
        "confirmacao_hash": (
            "bytea",
            SIM,
            None,
            "nao — sha256 do token da ligacao de confirmacao, nunca o token. "
            "Sem chave, ao contrario dos *_hmac do KAM-008: o que obriga a HMAC "
            "la e o espaco dos numeros angolanos ter poucos milhoes de "
            "elementos, e 32 octetos do gerador do sistema nao se enumeram",
        ),
        "confirmacao_expira_em": ("timestamp with time zone", SIM, None, "nao"),
        "invalido_at": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — quando uma entrega falhou de forma que condena o endereco "
            "(criterio 7). E facto do **contacto** e nao do aviso, e e por isso "
            "que sao duas tabelas",
        ),
        "motivo_invalido": ("text", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "actualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # KAM-115: o registo de cada aviso ao dono, **sem corpo**.
    #
    # Os Detalhes Tecnicos do ticket pedem «RLS e sem corpo», e nao haver coluna
    # de texto para o conteudo e a forma de o garantir — o mesmo argumento que a
    # `0018` escreveu para as contagens do historico. O que se registra e qual o
    # gatilho, qual o episodio, por que canal, em que lembrete e com que
    # desfecho; nunca o texto que saiu.
    #
    # O `episodio` **e** texto livre, e e a unica coluna desta tabela que o e.
    # Nao guarda dados pessoais porque o que lhe entra sao identificadores
    # nossos e da Meta — um `channel_id` com um motivo, uma `event_key` —, e
    # nunca telefone, `contact_id` nem corpo de mensagem.
    "owner_notices": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "gatilho": ("text", NAO, None, "nao"),
        "episodio": (
            "text",
            NAO,
            None,
            "nao — e o que distingue «o canal caiu outra vez» de «o canal "
            "caiu», cunhado por quem conhece o episodio: o channel_id com o "
            "motivo, a event_key da Meta. Identificadores nossos e dela, nunca "
            "de um titular",
        ),
        "chave": (
            "bytea",
            NAO,
            None,
            "nao — sha256(dominio ␀ tenant ␀ gatilho ␀ episodio), 32 octetos. "
            "Redundante com as tres colunas de proposito: e sobre ela que a "
            "unicidade se faz, e um resumo de comprimento fixo nao se parte com "
            "um episodio de 300 caracteres",
        ),
        "lembrete": (
            "smallint",
            NAO,
            "0",
            "nao — 0 o aviso, 1 as 24 h, 2 as 72 h. E com esta coluna que a "
            "idempotencia do criterio 2 e os lembretes do criterio 4 cabem na "
            "mesma unicidade",
        ),
        "canal": ("text", NAO, None, "nao — e o transporte e nao o interlocutor"),
        "estado": ("text", NAO, "'pendente'::text", "nao"),
        "tentativas": (
            "smallint",
            NAO,
            "0",
            "nao — quantas vezes se tentou entregar **este** aviso. Nao e o "
            "limite de frequencia (esse conta avisos, nao tentativas): e o que "
            "torna visivel um fornecedor a devolver erro transitorio em serie",
        ),
        "falha_motivo": ("text", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "entregue_at": ("timestamp with time zone", SIM, None, "nao"),
        "actualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # KAM-028, revisao 0021. O registo de **todas** as invocacoes da ToolLayer.
    #
    # **Vinte colunas e nenhuma guarda texto do cliente**, que e o critero 5 do
    # bloco e o `docs/tecnica/08` §6. As tres que poderiam e nao guardam:
    #
    #   args_hash      a impressao da chamada, 32 octetos. Nao e reversivel, e
    #                  e por isso que serve: diz «foi a mesma chamada» sem
    #                  guardar a chamada
    #   args_redacted  a **forma** dos argumentos — nome e tipo de cada um —, e
    #                  nunca o valor. O `query` de `search_catalog` e texto que
    #                  um cliente escreveu, e a pergunta «isto guarda dados
    #                  pessoais?» responde-se com o que a coluna guarda e nao
    #                  com o que a chamada tinha
    #   fact_ids       os identificadores dos *facts*, nao os valores deles
    #
    # Isto nao se prova por leitura: prova-se por varrimento com canarios, em
    # `db/tests_agr/test_tool_audit.py`.
    # KAM-052: a conta de pagamento (revisao `0027`). **Catorze colunas, e
    # nenhuma de dinheiro** — a G-3 do `docs/tecnica/04` secao 10.4 («nao
    # existe balance/wallet») e o `test_nao_ha_colunas_de_dinheiro_nem_saldos`
    # do `test_catalogo.py`, que recusa `%saldo%`, `%balance%`, `%_minor` e
    # `%_kz` em `platform`. Os factos de dinheiro vivem no ledger (KAM-053).
    "payment_accounts": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "beneficiary_kind": ("text", NAO, None, "nao"),
        # **Anulavel, e e a terceira excepcao do esquema.** Ver a nota de
        # `TABELAS_0027` em `base.py` e o `ANULAVEIS` de `test_catalogo.py`.
        "tenant_id": ("uuid", SIM, None, "nao"),
        "provider": ("text", NAO, None, "nao"),
        # Identificadores EMIS da **empresa**, emitidos pelo banco e pela
        # EMIS (secao 10.2): uma Entidade Multicaixa, um POSID de TPA e um
        # IEC de entidade credora. Nao sao dados de pessoa singular, e nao
        # ha aqui nome, telefone nem morada de ninguem.
        "entidade": ("text", SIM, None, "nao — Entidade Multicaixa da PME, identificador de empresa"),
        "pos_id": ("text", SIM, None, "nao — POSID do TPA virtual da PME, identificador de empresa"),
        "iec": ("text", SIM, None, "nao — IEC da PME como entidade credora de debito directo"),
        # **Caminho no cofre, nunca o segredo** (criterio 7). A forma e a do
        # `SecretRef` do KAM-010 e esta imposta por `CHECK`; o varrimento de
        # `test_pagamentos_schema.py` confere que nenhuma coluna guarda um
        # valor com forma de segredo, com os padroes do gate 9.
        "credenciais_ref": (
            "text",
            SIM,
            None,
            "nao — referencia opaca ao cofre (KAM-010), nunca a credencial. O CHECK impoe a forma e recusa maiusculas, espacos e enchimento base64",
        ),
        # Identificador **publico** da conta no URL do callback: 32 octetos
        # de CSPRNG em base64url. Opaco de proposito — nao leva o
        # `tenant_id`, o `id` nem o `provider` —, porque um URL de webhook
        # aparece em paineis de terceiros e em registos de proxy.
        "webhook_token": ("text", NAO, None, "nao — token opaco, sem conteudo derivado"),
        "liquidacao_destino": ("text", SIM, None, "nao"),
        # Dados de pagamento que a PME da ao cliente no ManualProvider
        # (secao 4): o nome do banco, o IBAN da **empresa** ou o numero de
        # carteira. Texto que o dono escreve e que o cliente ve.
        "manual_instrucoes": (
            "text",
            SIM,
            None,
            "dados de pagamento da empresa (IBAN ou carteira), escritos pelo dono para o cliente ver; nao e dado de pessoa singular",
        ),
        "estado": ("text", NAO, "'nao_iniciado'::text", "nao"),
        # O caminho critico da secao 10.2, por conta. As chaves sao do
        # KAM-091 (onboarding de retaguarda) e por isso nasce vazio — divida
        # documental 155.
        "checklist": ("jsonb", NAO, "'{}'::jsonb", "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "tool_audit": {
        "id": ("bigint", NAO, None, "nao"),
        "ts": ("timestamp with time zone", NAO, "now()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            SIM,
            None,
            "referencia opaca a contacts (KAM-008); nunca o telefone",
        ),
        "conversation_id": ("uuid", SIM, None, "referencia opaca a conversations"),
        "turn_id": ("text", SIM, None, "nao — identificador do turno, opaco"),
        "run_id": ("text", SIM, None, "nao — identificador da execucao do grafo"),
        "vertical": ("text", SIM, None, "nao"),
        "graph_version": ("text", SIM, None, "nao"),
        "tool": ("text", NAO, None, "nao"),
        "tool_version": ("text", SIM, None, "nao"),
        "klass": ("text", NAO, None, "nao"),
        "args_hash": (
            "bytea",
            NAO,
            None,
            "nao — sha256 da forma canonica dos argumentos, 32 octetos. "
            "Irreversivel por construcao, e e isso que a torna aceitavel num "
            "registo que cobre tambem as leituras",
        ),
        "args_redacted": (
            "jsonb",
            SIM,
            None,
            "nao — a **forma** dos argumentos (nome e tipo), nunca o valor. Um "
            "valor aqui era texto do cliente num registo de auditoria",
        ),
        # KAM-029 corrigiu a razao desta linha, e nao a coluna. Ela dizia «a
        # chave do §6.3», e **nao e**: aqui fica a chave do **chamador**, que e
        # a do turno (vai tambem ao `usage_ledger`, no passo 2), enquanto a do
        # §6.3 e a do **carrinho** e vive na `tool_idempotency.key`. Nao sao a
        # mesma e nao podiam ser — um segundo toque com `wamid` novo e um turno
        # novo, com chave de turno nova, e se o carrinho se desduplicasse por
        # ela esse toque cobrava outra vez (criterio 8 do KAM-029). As duas
        # linhas ligam-se pelo par `(tool, args_hash)`, que e o mesmo nas duas
        # tabelas. A nota longa esta no `kamba_agr/tls/idempotency.py`.
        "idempotency_key": (
            "text",
            SIM,
            None,
            "nao — a chave de idempotencia **do chamador** (do turno; o KAM-025 "
            "usa `turn_id:seq`). Opaca, sem telefone (ADR-010); a chave do "
            "carrinho do §6.3 vive na `tool_idempotency`",
        ),
        "status": ("text", NAO, None, "nao"),
        "error_code": ("text", SIM, None, "nao — um dos dez codigos do §6.5"),
        "result_hash": ("bytea", SIM, None, "nao — sha256 do resultado, 32 octetos"),
        "fact_ids": (
            "ARRAY",
            SIM,
            None,
            "nao — os `fact_id` devolvidos, nao os valores. E o que liga uma "
            "citacao do KAM-032 a linha que a produziu",
        ),
        "latency_ms": ("integer", SIM, None, "nao"),
    },
    # KAM-029: a barreira de idempotencia. A pergunta «isto guarda dados
    # pessoais?» tem aqui uma resposta que a base **impoe** e nao so declara: a
    # `key` tem `CHECK (key ~ '^[0-9a-f]{64}$')`, pelo que nenhum telefone,
    # BSUID ou nome cabe la, qualquer que seja o chamador (criterio 6, ADR-010).
    #
    # A coluna a olhar com cuidado e o `result`, e nao a `key`: e o `data` que o
    # backend devolveu, guardado para o *replay*. Um `criar_pedido` devolve
    # identificadores de encomenda, que sao opacos; o dia em que um executor
    # devolver nome ou morada do cliente no `data`, e esta linha que passa a
    # dizer «sim» — e o varrimento com canarios de
    # `db/tests_agr/test_idempotencia.py` que o apanha.
    "tool_idempotency": {
        "key": (
            "text",
            NAO,
            None,
            "nao — sha256 de `(tenant_id, contact_id, tool, cart_id)` em "
            "hexadecimal, com `CHECK` de forma. Irreversivel por construcao",
        ),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "tool": ("text", NAO, None, "nao"),
        "args_hash": (
            "bytea",
            NAO,
            None,
            "nao — sha256 da forma canonica dos argumentos, 32 octetos. O mesmo "
            "valor da `tool_audit.args_hash`, pela mesma funcao",
        ),
        "estado": ("text", NAO, "'em_curso'::text", "nao"),
        "result": (
            "jsonb",
            SIM,
            None,
            "nao — o `data` que o backend devolveu, que num `criar_pedido` sao "
            "identificadores de encomenda, opacos. Varrido por canarios em "
            "`db/tests_agr/test_idempotencia.py`",
        ),
        "created_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # ------------------------------------------------- KAM-114 (0024)
    #
    # **Treze colunas e nenhuma de texto livre**, e isso e o produto e nao
    # arrumacao: o texto do rascunho e da edicao vive no checkpointer (`lg`) e
    # no HND. Das seis `text`, quatro tem forma e duas tem dominio fechado.
    "draft_decisions": {
        "draft_id": (
            "text",
            NAO,
            None,
            "nao — sha256 de `(thread_id, turn_seq)` em hexadecimal, com "
            "`CHECK` de forma. Irreversivel por construcao",
        ),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "thread_id": (
            "text",
            NAO,
            None,
            "nao — `tenant_id:contact_id` (§3.1). O `contact_id` e o "
            "substituto, nunca o telefone (ADR-010)",
        ),
        "turn_seq": ("integer", NAO, None, "nao"),
        "turn_id": (
            "text",
            NAO,
            None,
            "nao — o `wamid` da mensagem, que e um identificador da Meta e nao "
            "do titular. **Nunca sai na exportacao** do criterio 7: e "
            "`identificador` na classificacao do `db/golden_candidates.py`",
        ),
        "graph_version": (
            "text",
            SIM,
            None,
            "nao — SemVer, com `CHECK` de forma. **A forma importa e foi "
            "acrescentada pela revisao adversarial**: e a unica coluna desta "
            "tabela que sai na exportacao, e sem ela era um campo de texto "
            "livre a atravessar para fora",
        ),
        "decisao": ("text", SIM, None, "nao — dominio fechado de cinco valores"),
        "motivo": (
            "text",
            SIM,
            None,
            "nao — dominio fechado de seis valores, e **nao** texto livre: quem "
            "o escreve e um operador humano num botao, e um campo livre numa "
            "mao humana e por onde o nome de um cliente entra numa tabela que "
            "jura nao ter nenhum",
        ),
        "razao_edicao": (
            "numeric",
            SIM,
            None,
            "nao — distancia normalizada 0-1 entre o rascunho e a edicao. Os "
            "dois textos entram no `concierge/servico.py` e **nao saem**: para "
            "aqui atravessa este numero",
        ),
        "edicao_numero_livre": ("boolean", NAO, "false", "nao"),
        "latencia_ms": ("integer", SIM, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "decidido_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # ---------------------------------------------------------------- KAM-043
    #
    # Os termos comerciais de um SKU: o preco opaco e o stock nao-garantido
    # (revisao `0028`). **Nenhuma coluna guarda dado pessoal**, e a unica de
    # texto livre e o `nome`, que e o nome comercial do produto — a mesma
    # resposta do `servicos.resources.nome` e do `tenants.nome`.
    "offer_terms": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "sku": (
            "text",
            NAO,
            None,
            "nao — a referencia do produto na loja. **Escrita pelo dono**, e e "
            "por isso que leva `CHECK` de nao-vazio e nao de forma: um padrao "
            "inventado recusava SKUs reais de PMEs angolanas, que nao seguem "
            "nenhum",
        ),
        "nome": (
            "text",
            NAO,
            None,
            "nao — nome comercial do produto, nunca de pessoa singular. E o "
            "campo que o `searchOffers` pesquisa por trigramas; o que impede um "
            "telefone aqui nao e o schema (nenhum o faz) mas o validador de "
            "entrada e o KAM-068, como diz o cabecalho deste ficheiro",
        ),
        "medusa_variant_id": (
            "text",
            SIM,
            None,
            "nao — id opaco no Registo. Nulo em toda a Fase 0: nao ha Medusa em "
            "`infra/compose/`",
        ),
        "preco_tipo": (
            "text",
            NAO,
            None,
            "nao — dominio fechado de tres valores. **`preco_tipo` e nao "
            "`preco_modo`**, que o dicionario §3.3 substitui desde a emenda 1.12",
        ),
        "preco_minor": (
            "bigint",
            SIM,
            None,
            "nao — unidade menor inteira. **Anulavel so em `sob_consulta`**, e a "
            "equivalencia esta no `offer_terms_preco_ck` nos dois sentidos",
        ),
        "currency": (
            "text",
            NAO,
            "'AOA'::text",
            "nao — dominio de um valor. `text` com `CHECK` e nao `char(3)`: um "
            "`char(3)` sem `CHECK` aceita `'USD'` em silencio e nenhum gate o le",
        ),
        "preco_atualizado_at": ("timestamp with time zone", SIM, None, "nao"),
        "preco_valido_ate": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — passado o prazo o preco **le-se** como `a_partir_de`; a "
            "coluna `preco_tipo` nao muda",
        ),
        "stock_modo": ("text", NAO, "'indicativo'::text", "nao"),
        "stock_verificado_at": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — acima de 24 h o `indicativo` sai com aviso (§7.3)",
        ),
        "estado": ("text", NAO, "'rascunho'::text", "nao"),
        "categoria_restrita": (
            "text",
            SIM,
            None,
            "nao — categoria de produto, preenchida pelo *screening* (KAM-049). "
            "Nao nula bloqueia a publicacao",
        ),
        # KAM-045: as duas colunas de quantidade, que e a autoridade de stock
        # que faltava para o `OUT_OF_STOCK` do `createOrder` (dicionario 3.43).
        "stock_quantidade": (
            "bigint",
            SIM,
            None,
            "nao — a quantidade declarada pelo dono. **Nulo e «nao declarada», "
            "nao zero**: zero e a afirmacao de que nao ha, e nulo e a ausencia "
            "de afirmacao. Nenhum caminho de escrita a escreve ainda, e isso e "
            "divida com credor no KAM-043/KAM-049",
        ),
        "stock_reservada": (
            "bigint",
            NAO,
            "0",
            "nao — quanto da quantidade esta prometido a reservas `ativa`. "
            "`NOT NULL` por medicao e nao por gosto: `NULL + 1` e `NULL`, e "
            "uma coluna anulavel fazia o predicado aritmetico do criterio 1 "
            "devolver `NULL` — que num `WHERE` nao e verdadeiro, pelo que "
            "**toda** a reserva era recusada, em silencio",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "atualizado_at": (
            "timestamp with time zone",
            NAO,
            "now()",
            "nao — escrito pelo modulo em cada `UPDATE`, nao por *trigger*",
        ),
        "deleted_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # A cotacao do dono: e por aqui que um `sob_consulta` ganha numero. O
    # `contact_id` e a referencia pseudonimizada do ADR-010 — nunca o telefone —,
    # e a FK que a liga e **composta**, pela correccao de 2026-10-27 do
    # `docs/tecnica/03` §5.4.
    "price_quotes": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "nao — referencia opaca a `contacts` (KAM-008, ADR-010). E o "
            "substituto, nunca o telefone",
        ),
        "sku": ("text", NAO, None, "nao — a referencia do produto cotado"),
        "qty": ("integer", NAO, None, "nao"),
        "preco_total_minor": (
            "bigint",
            NAO,
            None,
            "nao — o total da linha para `(sku, qty)`, e nao o unitario: "
            "dividir por `qty` perdia o desconto de quantidade, que e a razao de "
            "existir a cotacao",
        ),
        "currency": ("text", NAO, "'AOA'::text", "nao — dominio de um valor"),
        "valida_ate": (
            "timestamp with time zone",
            NAO,
            None,
            "nao — a expiracao e por este instante e **nao** pelo `estado`: um "
            "estado so muda quando alguem o muda",
        ),
        "estado": ("text", NAO, "'emitida'::text", "nao"),
        "emitida_por": (
            "uuid",
            NAO,
            None,
            "nao — o id do actor dono que a emitiu, que pode ser o "
            "`owner_contact_id` do tenant ou um operador. **Sem FK**: um actor "
            "nao e uma linha de `contacts`, e inventar-lhe uma tabela era escopo "
            "de outro ticket",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # ------------------------------------------------------- KAM-044 (0030)
    #
    # As encomendas. **A resposta que esta tabela existe para dar e a do
    # ADR-010**: `orders_mirror` nao tem `msisdn`, nao tem nome, nao tem morada
    # e nao tem texto livre nenhum — o cliente entra por `contact_id`, que e uma
    # referencia opaca a `contacts`, e o `docs/tecnica/03` secao 5.1 n.o 3
    # registou que o `cliente_msisdn text NOT NULL` do documento 11 violava o
    # ADR-010 e a minimizacao da Lei 22/11. O `lines_snapshot` tem o `nome` do
    # **produto**, que e a mesma resposta do `offer_terms.nome`.
    # A reserva de stock (KAM-045), do mesmo bloco SQL do `docs/tecnica/03`
    # secao 5.4 que a `0030` deixou com o credor escrito. O prazo chama-se
    # `expira_at` e nao a forma inglesa do DDL daquele documento: a emenda 1.11
    # do dicionario resolveu a divergencia e a 1.12 registou a variante depois
    # de medir que uma migracao com a forma antiga falhava o *gate* 3b,
    # nomeando **esta** tabela.
    "stock_reservations": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "order_id": (
            "uuid",
            NAO,
            None,
            "nao — a encomenda, por FK **composta** `(tenant_id, order_id)`, "
            "que e a licao ISO-58 do spike KAM-041: uma FK simples deixava a "
            "reserva de A apontar para a encomenda de B",
        ),
        "line_no": (
            "integer",
            NAO,
            None,
            "nao — o indice da linha no `lines_snapshot`, que e um `jsonb` sem "
            "chaves proprias. E o que da identidade a linha reservada",
        ),
        "sku": (
            "text",
            NAO,
            None,
            "nao — **copiado e nao referenciado por FK**: a reserva e do "
            "instante da encomenda, como o `lines_snapshot`, e um SKU em "
            "*soft delete* nao pode invalidar uma reserva activa",
        ),
        "qty": ("integer", NAO, None, "nao"),
        "estado": (
            "text",
            NAO,
            "'ativa'::text",
            "nao — `ativa`, `consumida` ou `libertada`. Os dois ultimos sao "
            "**terminais** pelo *trigger*, e e isso que faz de «execucao dupla "
            "= 1 libertacao» (criterio 4) uma restricao e nao uma convencao",
        ),
        "motivo": (
            "text",
            SIM,
            None,
            "nao — `expirada`, `cancelada` ou `recusada_dono` (criterio 6), e "
            "**so** quando `libertada`: a exigencia e uma equivalencia e nao "
            "uma implicacao, porque um motivo escrito noutro estado afirmava "
            "uma razao para uma coisa que nao aconteceu",
        ),
        "expira_at": (
            "timestamp with time zone",
            NAO,
            None,
            "nao — o prazo. `NOT NULL` porque o varrimento tinha de tratar o "
            "nulo como «nunca expira», e uma reserva provisoria cujo "
            "`charge.issued` nunca chegasse ficava a prender stock para sempre",
        ),
        "confirmada_at": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — quando o `charge.issued` fixou o prazo (criterio 3). Nulo e "
            "uma reserva **provisoria**; nao e um quarto estado porque as duas "
            "sao `ativa` para todos os efeitos de stock — o que difere e o prazo",
        ),
        "consumida_at": ("timestamp with time zone", SIM, None, "nao"),
        "libertada_at": ("timestamp with time zone", SIM, None, "nao"),
        "version": (
            "integer",
            NAO,
            "1",
            "nao — concorrencia optimista. O *trigger* exige que suba de um em "
            "cada **mudanca de estado**, como no `orders_mirror`: exigi-la em "
            "todo o `UPDATE` proibia um toque sem efeito",
        ),
        "criado_at": (
            "timestamp with time zone",
            NAO,
            "now()",
            "nao — e e contra **este** instante que o tecto de 72 h do "
            "criterio 7 se mede, e nao contra `now()`: dois prolongamentos de "
            "36 h passavam a validacao um a um e somavam 72 h sobre uma "
            "reserva que ja tinha 48",
        ),
        "atualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # KAM-091 (0034): o estado da saga de provisioning de oito passos. **Dez
    # colunas e nenhum `id` gerado**: a chave e natural e composta,
    # `(onboarding_id, step)`, que e a `UNIQUE(onboarding_id, step)` que o
    # contrato de `packages/core-ts/src/provisioning/contrato.ts` declara. Um
    # `uuid` ao lado era um identificador que nenhuma porta cita — nenhuma das
    # **oito** recebe um `id` de linha.
    "provisioning_step": {
        "onboarding_id": (
            "uuid",
            NAO,
            None,
            "nao — a chave do caso de onboarding, **sem FK**: a tabela "
            "`onboarding_case` nasceu depois, com a `0043` (KAM-087), e a FK "
            "ficou por acrescentar. E uma referencia opaca e nao um dado da "
            "pessoa",
        ),
        "tenant_id": (
            "uuid",
            NAO,
            None,
            "nao — **pre-alocado e sem FK para `platform.tenants`**: o passo 1 "
            "da saga (`tenant_e_caso`) e que escreve a linha de `tenants`, "
            "pelo que uma FK tornava o proprio passo 1 impossivel. E por esta "
            "coluna que a RLS e o X-05 do *gate* 6 agarram a tabela",
        ),
        "step": (
            "text",
            NAO,
            None,
            "nao — um dos **oito** passos do dicionario secao 3.47, **pela "
            "ordem**, que e a que a compensacao inverte. Os nomes sao os do "
            "passo e nao os do fornecedor (`conta_atendimento` e nao "
            "`chatwoot`), porque o fornecedor e decisao aberta",
        ),
        "status": (
            "text",
            NAO,
            None,
            "nao — um dos **cinco** do dicionario secao 3.47, **qualificado "
            "pela tabela**: o `status` nu e o dominio {`ok`, `erro`} do secao "
            "3.27, e a migracao sem o nome qualificado deu dois achados "
            "`[regra]` do *gate* 3b. O `compensado` distingue «foi desfeito» "
            "de «nunca correu», que e o que a reconciliacao nocturna le",
        ),
        "attempt": (
            "integer",
            NAO,
            None,
            "nao, **e sem omissao de proposito** — o `abrir` incrementa e "
            "devolve a linha **depois** do "
            "incremento, e e esse valor que o tecto de tres tentativas do "
            "criterio 5 le. Com `DEFAULT 0`, um `ON CONFLICT ... DO UPDATE` "
            "que deixasse o `attempt` fora do `INSERT` devolvia zero a "
            "primeira volta e deslocava as tres metades do criterio 5 em "
            "silencio; sem omissao, leva `23502`. E o `CHECK` e `>= 0` e nao "
            "`>= 1` porque o `marcarEspera` repoe a zero: uma espera nao e "
            "falha, e sem isso tres passagens com o dono por agir escalavam o "
            "caso",
        ),
        "external_id": (
            "text",
            SIM,
            None,
            "nao — a referencia do recurso criado la fora (uma conta de "
            "atendimento, uma chave do LiteLLM). **Anulavel**, e o nulo nao e "
            "lapso: dois dos oito passos nao produzem recurso externo nenhum, "
            "e o `marcarConcluido` aceita-o na assinatura",
        ),
        "error_code": (
            "text",
            SIM,
            None,
            "nao, **e tem `CHECK` de forma para o garantir**: leva a classe do "
            "erro ou um identificador curto em `snake_case` "
            "(`^[A-Za-z][A-Za-z0-9_]{2,63}$`), nunca a mensagem. A revisao "
            "adversarial do KAM-091 mediu que o `erro.name` e escrevivel por "
            "quem lanca e punha a chave inteira do LiteLLM nesta coluna; o "
            "codigo passou a devolver `erro_opaco` para o que nao casa, e "
            "agora a coluna tambem o recusa",
        ),
        "status_de_espera": (
            "text",
            SIM,
            None,
            "nao — uma das **tres** esperas dos passos 6-8 (dicionario secao "
            "3.47). Anulavel, e o nulo e o estado normal: um passo que nao "
            "espera por ninguem. **Nao e o `onboarding_case.fase`** do secao "
            "3.2, que tem seis valores e nao tem o `aguarda_teste`",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "atualizado_at": (
            "timestamp with time zone",
            NAO,
            "now()",
            "nao — escrito pelo modulo em cada `UPDATE`, nao por *trigger*, "
            "como na `0028`, na `0030` e na `0033`",
        ),
    },
    "orders_mirror": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "nao — referencia opaca a `contacts` (KAM-008, ADR-010). E o "
            "substituto do telefone, nunca o telefone, e a FK e **composta** "
            "com o `tenant_id` (correccao de 2026-10-27 do secao 5.4, ISO-58)",
        ),
        "origem": ("text", NAO, "'pme'::text", "nao"),
        "numero_publico": (
            "text",
            NAO,
            "platform.order_numero_publico()",
            "nao — base32 de Crockford de oito caracteres, gerado pela base. "
            "Serve de referencia curta no PAY, e e por isso que a entropia e de "
            "`gen_random_uuid()` e nao de `random()`: um numero previsivel "
            "deixava adivinhar a referencia de outra encomenda",
        ),
        "intent_key": (
            "text",
            NAO,
            None,
            "nao — a chave de idempotencia da criacao (secao 6.3), escolhida "
            "pelo COM e nao pelo cliente",
        ),
        "medusa_order_id": (
            "text",
            SIM,
            None,
            "nao — referencia **logica** ao Registo (secao 5.1 n.o 7), nunca FK "
            "de base. Nula em toda a Fase 0",
        ),
        "estado": ("text", NAO, "'criada'::text", "nao"),
        "confirmacao_dono": ("text", NAO, "'nao_aplicavel'::text", "nao"),
        "total_minor": (
            "bigint",
            NAO,
            None,
            "nao — unidade menor inteira (secao 5.1 n.o 2). **Nao e um saldo**: "
            "congela com o `lines_snapshot` depois de `criada`, pelo que e "
            "historia e nao posicao. Declarado em `EM_UNIDADE_MENOR` de "
            "`test_catalogo.py` com a razao por extenso (ADR-L008)",
        ),
        "currency": ("text", NAO, "'AOA'::text", "nao — dominio de um valor"),
        "lines_snapshot": (
            "jsonb",
            NAO,
            None,
            "nao — as linhas da encomenda: `sku`, `qty`, preco e o **nome do "
            "produto**, que e a mesma resposta do `offer_terms.nome` (nome "
            "comercial, nunca de pessoa singular). Imutavel depois de `criada`, "
            "pelo *trigger* `order_transicao_valida`",
        ),
        "entrega_modo": ("text", NAO, "'levantamento'::text", "nao"),
        "expira_at": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — fim da reserva activa. Nulo enquanto nao houver cobranca "
            "emitida, e e o payload obrigatorio do `order.expired`",
        ),
        "paga_at": ("timestamp with time zone", SIM, None, "nao"),
        "paga_via": (
            "text",
            SIM,
            None,
            "nao — como o pagamento foi dado por bom. O dominio da coluna tem "
            "tres valores (secao 5.4) e o `CHECK` do estado aceita **dois** "
            "para `paga`: o `cod_manual` fica alcancavel para quem implementar "
            "a cobranca a entrega, com a razao escrita",
        ),
        "excepcao": ("text", SIM, None, "nao — quem a escreve e o KAM-050"),
        "entregue_at": ("timestamp with time zone", SIM, None, "nao"),
        "entrega_confirmada_por": (
            "text",
            SIM,
            None,
            "nao — **o papel e nao a pessoa**: `cliente`, `dono` ou `estafeta`. "
            "Quem confirmou pelo `id` esta no `order_state_log.actor_id`",
        ),
        "version": (
            "integer",
            NAO,
            "1",
            "nao — concorrencia optimista. O *trigger* exige que suba de um em "
            "cada mudanca de estado, e e a ela que o `order_state_log.version` "
            "se refere",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "atualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "deleted_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    "order_intents": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "intent_key": ("text", NAO, None, "nao — ver `orders_mirror.intent_key`"),
        "draft_hash": (
            "bytea",
            NAO,
            None,
            "nao — `sha256` do conteudo do rascunho confirmado, 32 octetos pelo "
            "`CHECK`. E um resumo e nao o conteudo: do *hash* nao se le o que o "
            "cliente escreveu",
        ),
        "estado": ("text", NAO, "'em_curso'::text", "nao"),
        "order_id": (
            "uuid",
            SIM,
            None,
            "nao — nulo enquanto a encomenda nao existe. A FK composta com uma "
            "metade nula **nao e imposta** (`MATCH SIMPLE`), e o "
            "`order_intents_concluida_exige_encomenda_ck` e que liga o estado "
            "ao `order_id` nos dois sentidos",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "order_state_log": {
        "id": (
            "uuid",
            NAO,
            "gen_random_uuid()",
            "nao — `uuid` e **nao** `bigint` de identidade como o secao 5.4 "
            "escreve: o `kamba_app` tem de ler esta tabela (e o *trigger* "
            "diferido que a le, como invocador), pelo que uma chave sequencial "
            "media as transicoes de toda a plataforma a quem atende um cliente",
        ),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "order_id": ("uuid", NAO, None, "nao"),
        "de": ("text", NAO, None, "nao"),
        "para": ("text", NAO, None, "nao"),
        "version": (
            "integer",
            NAO,
            None,
            "nao — a `version` **de depois** da transicao. Coluna que o secao "
            "5.4 nao tem, e e ela que liga esta linha a transicao exacta: sem "
            "ela o ciclo `expirada -> aguarda_pagamento -> expirada` deixava "
            "uma linha de uma volta anterior satisfazer a verificacao de uma "
            "volta nova",
        ),
        "causa": (
            "text",
            NAO,
            None,
            "nao — o nome do evento ou do gesto que causou a transicao "
            "(`payment.confirmed`, `ttl`, `dono_confirma`, `reconciliacao`). "
            "**Nao e texto do cliente**: e um identificador de caminho, e o "
            "dominio nao esta fechado porque o secao 5.4 da exemplos e nao uma "
            "lista",
        ),
        "evento_id": (
            "text",
            SIM,
            None,
            "nao — o `id` do evento que a causou. **Obrigatorio para `paga`**, "
            "pelo *trigger* diferido: e a prova do criterio 3 e do ADR-013",
        ),
        "actor_kind": (
            "text",
            NAO,
            None,
            "nao — um dos quatro do dicionario §3.2 (`agente`, `dono`, "
            "`sistema`, `ops`). E um papel e nao uma pessoa",
        ),
        "actor_id": (
            "text",
            SIM,
            None,
            "nao — o identificador do actor dentro do papel. Opaco: nunca um "
            "telefone nem um nome, como no `audit_log.actor_id`",
        ),
        "em": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "order_state_graph": {
        "de": ("text", NAO, None, "nao"),
        "para": ("text", NAO, None, "nao"),
        "flag": (
            "text",
            SIM,
            None,
            "nao — o nome da bandeira que a transicao exige, ou nulo quando "
            "esta sempre activa. Dominio fechado por `CHECK` num valor "
            "(`COM_DELIVERY_ENABLED`): um nome vindo da linha deixava quem "
            "escreve no grafo escolher que GUC a base consulta",
        ),
    },
    "order_reconciliation_issues": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "order_id": (
            "uuid",
            SIM,
            None,
            "nao — anulavel porque duas das cinco regras do secao 10.3 falam de "
            "uma encomenda que o espelho ainda **nao** tem",
        ),
        "tipo": ("text", NAO, None, "nao — uma das cinco regras do secao 10.3"),
        "detalhe": (
            "jsonb",
            NAO,
            "'{}'::jsonb",
            "nao — o que divergia, para quem reconcilia ler sem reabrir o "
            "Registo: `intent_key`, `sku`, totais e estados. **Sem dado "
            "pessoal**, e e o `reconcile.ts` que o constroi campo a campo, nao "
            "um despejo de linha",
        ),
        "estado": ("text", NAO, "'aberta'::text", "nao"),
        "aberta_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "resolvida_at": ("timestamp with time zone", SIM, None, "nao"),
    },
    # ------------------------------------------------------- KAM-053 (0029)
    #
    # A cobranca: o estado **derivado** do ledger, e a unica tabela mutavel de
    # PAY — mutavel so pela `append_payment_event`, porque nenhum papel tem
    # `UPDATE`. **Tem a primeira coluna de dinheiro de `platform` que nao e de
    # catalogo**, o `amount_minor`, e nao e um saldo: e o que se pediu a este
    # cliente nesta cobranca, nao o que a plataforma detem (G-3 do
    # `docs/tecnica/04` secao 10.4). Ver o `EM_UNIDADE_MENOR` de
    # `test_catalogo.py`, onde a razao se escreve coluna a coluna.
    "payment_charges": {
        "id": (
            "uuid",
            NAO,
            "gen_random_uuid()",
            "nao — `= chargeId = Idempotency-Key` (secao 6.2): quem cria a "
            "cobranca escolhe o `id`, e e isso que torna a criacao retentavel "
            "com a mesma chave (F-09)",
        ),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "order_id": (
            "uuid",
            SIM,
            None,
            "nao — FK composta `(tenant_id, order_id)` para a `orders_mirror` "
            "desde a `0035` (KAM-055); a tabela e do KAM-044. Continua "
            "anulavel porque exactamente um dos dois sujeitos existe, e o "
            "`payment_charges_um_sujeito` impoe-no — o `MATCH SIMPLE` da FK e "
            "o que deixa o nulo passar",
        ),
        "billing_cycle_id": (
            "uuid",
            SIM,
            None,
            "nao — idem, e a FK e do KAM-059. A facturacao da propria KAMBA usa "
            "o mesmo PAY (secao 11.2), e e por isso que o `order_id` nao podia "
            "ser obrigatorio",
        ),
        "tentativa": ("smallint", NAO, "1", "nao"),
        "account_id": ("uuid", NAO, None, "nao"),
        "provider": ("text", NAO, None, "nao"),
        "metodo": ("text", NAO, None, "nao — dominio fechado de quatro valores"),
        "referencia": (
            "text",
            SIM,
            None,
            "nao — Entidade + Referencia Multicaixa, identificador de "
            "pagamento e nao de pessoa. Anulavel: um `express_push` nao tem "
            "referencia",
        ),
        "provider_charge_id": ("text", SIM, None, "nao — id opaco do facilitador"),
        "amount_minor": (
            "bigint",
            NAO,
            None,
            "nao — unidade menor inteira, e **nao e um saldo**: e o valor desta "
            "cobranca. Ver `EM_UNIDADE_MENOR` em `test_catalogo.py`",
        ),
        "currency": (
            "character",
            NAO,
            "'AOA'::bpchar",
            "nao — dominio de um valor. `char(3)` **com** `CHECK`, ao contrario "
            "do `text` da `0028`: aqui o DDL do secao 6.2 escreve `char(3)` e o "
            "`payment_charges_currency_ck` e que fecha o dominio",
        ),
        "estado": (
            "text",
            NAO,
            "'iniciada'::text",
            "nao — projeccao de `next_state` sobre o ledger; o "
            "`rebuild_charge_state` reconstroi-o a partir dos eventos",
        ),
        "motivo_falha": ("text", SIM, None, "nao — dominio fechado de nove valores"),
        "requer_humano": ("boolean", NAO, "false", "nao"),
        "valid_until": ("timestamp with time zone", NAO, None, "nao"),
        "payer_hmac": (
            "bytea",
            SIM,
            None,
            "**e um HMAC e nao o numero**: o msisdn Express do pagador e PII P2 "
            "(ADR-010), e o que se guarda e o resumo com segredo do cofre, pelo "
            "anti-auto-compra do secao 9. `bytea`, como o `phone_hmac` da "
            "`contacts`",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "atualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    # Toda a entrega HTTP de callback, incluindo as rejeitadas. **Sem
    # `tenant_id`**, e nao e lapso: quando o corpo chega nao se sabe de quem e
    # (secao 5.1), e uma coluna de isolamento preenchida depois era uma chave
    # que o atacante controla. O que a isola e o papel estreito
    # `kamba_pay_hooks` — ver `TABELAS_0029` em `base.py`.
    #
    # **E a tabela de `platform` com mais superficie de dado de fora**, e por
    # isso a que mais precisa desta pergunta respondida linha a linha: guarda o
    # corpo cru e os cabecalhos de um pedido que qualquer um pode enviar.
    "payment_callbacks_inbox": {
        "id": ("bigint", NAO, None, "nao"),
        "account_id": (
            "uuid",
            SIM,
            None,
            "nao — nulo quando o `webhook_token` nao resolve (recibo "
            "`token_desconhecido`): guardar a entrega e o que torna o 404 "
            "uniforme auditavel",
        ),
        "recebido_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "source_ip": (
            "inet",
            SIM,
            None,
            "o IP de origem do callback e de um **servidor do facilitador** e "
            "nao de uma pessoa: o cliente paga no Multicaixa ou no Express, e "
            "quem entrega o callback e a EMIS ou o banco. Nao e dado de "
            "navegacao de ninguem",
        ),
        "headers": (
            "jsonb",
            NAO,
            "'{}'::jsonb",
            "nao — **sem segredos** (secao 6.2): quem escreve aqui redige o "
            "`Authorization` e a assinatura antes de gravar",
        ),
        "body": (
            "bytea",
            NAO,
            None,
            "o corpo **cru** de um callback de pagamento, em octetos, porque o "
            "HMAC e sobre ele e guardar texto descodificado perdia a "
            "capacidade de o reverificar. Um payload da EMIS leva referencia, "
            "valor e instante — identificadores de pagamento, nao de pessoa —, "
            "e o telefone do pagador, quando o provedor o envia, e PII P2 que "
            "nao se promove a coluna: fica no corpo que o `verifyCallback` le "
            "e o `append_payment_event` **nao** copia para o ledger (a guarda "
            "de PII da `0004` recusa um payload com padrao de telefone). A "
            "retencao desta tabela e do KAM-071",
        ),
        "body_hash": (
            "bytea",
            NAO,
            None,
            "nao — sha256 do corpo, com `CHECK` de 32 octetos",
        ),
        "authn_ok": (
            "boolean",
            SIM,
            None,
            "nao — anulavel: `NULL` enquanto o `verifyCallback` nao correu, "
            "porque o secao 5.1 grava a linha **antes** de haver veredicto",
        ),
        "estado": (
            "text",
            NAO,
            "'recebido'::text",
            "nao — dominio fechado de sete recibos",
        ),
        "processado_at": ("timestamp with time zone", SIM, None, "nao"),
        "erro": (
            "text",
            SIM,
            None,
            "nao — mensagem de diagnostico escrita pelo *worker*, nao pelo que "
            "chegou pela rede",
        ),
    },
    # O ledger. `INSERT` so por `append_payment_event`; `UPDATE`, `DELETE` e
    # `TRUNCATE` recusados pelo `deny_mutation` **a todos**, incluindo ao dono e
    # ao superutilizador. O `payload` e redigido (secao 6.2, ADR-010) e a guarda
    # da `0004` recusa um padrao de telefone.
    "payment_events": {
        "id": ("bigint", NAO, None, "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "charge_id": ("uuid", NAO, None, "nao"),
        "order_id": (
            "uuid",
            SIM,
            None,
            "nao — copiado da cobranca pela funcao, nunca enviado pelo "
            "chamador: um evento nao aponta para um sujeito diferente do da "
            "cobranca a que pertence. FK composta desde a `0035` (KAM-055), "
            "pela razao da `payment_charges` — e e esta que torna uma "
            "encomenda com ledger impossivel de apagar",
        ),
        "billing_cycle_id": ("uuid", SIM, None, "nao — idem"),
        "provider": ("text", NAO, None, "nao"),
        "account_id": ("uuid", NAO, None, "nao"),
        "referencia": (
            "text",
            NAO,
            None,
            "nao — `NOT NULL` aqui e anulavel na cobranca: um provedor sem "
            "referencia usa `numero_publico#tentativa`, o que mantem a "
            "unicidade por conta",
        ),
        "tipo_evento": (
            "text",
            NAO,
            None,
            "nao — dominio fechado de dezassete tipos. Factos e decisoes na "
            "mesma coluna: o que os distingue e a `decisao`",
        ),
        "sequencia": (
            "integer",
            NAO,
            None,
            "nao — n-esima ocorrencia deste tipo para esta referencia, "
            "calculada sob `FOR UPDATE` na cobranca",
        ),
        "provider_event_id": (
            "text",
            SIM,
            None,
            "nao — id de entrega do facilitador. Anulavel: um facto que a "
            "plataforma gera nao tem identificador de entrega",
        ),
        "valor_minor": (
            "bigint",
            NAO,
            None,
            "nao — unidade menor inteira, e **nao e um saldo**: e o valor do "
            "facto registado. Ver `EM_UNIDADE_MENOR` em `test_catalogo.py`",
        ),
        "currency": (
            "character",
            NAO,
            "'AOA'::bpchar",
            "nao — dominio de um valor, pela razao da `payment_charges`",
        ),
        "authn_method": (
            "text",
            NAO,
            None,
            "nao — **quatro** valores, e o quarto (`sistema`) ganhou dominio "
            "escrito neste ticket: os factos de ciclo de vida que ninguem "
            "autentica. Nunca autentica um `pagamento_confirmado`, porque a "
            "`confirmar_exige_autenticacao` nao o inclui",
        ),
        "authn_ok": ("boolean", NAO, None, "nao"),
        "decisao": ("text", NAO, None, "nao — dominio fechado de tres valores"),
        "motivo": ("text", SIM, None, "nao — diagnostico escrito pela plataforma"),
        "actor_kind": ("text", NAO, None, "nao — dominio fechado de quatro valores"),
        "actor_id": (
            "uuid",
            SIM,
            None,
            "nao — o id do operador de ops que registou o acto, e nao o nome "
            "dele. Exigido quando `authn_method = 'manual'` pelo "
            "`humano_exige_actor`: uma confirmacao humana sem actor nao e "
            "auditavel",
        ),
        "payload_hash": ("bytea", NAO, None, "nao — sha256, com `CHECK` de 32 octetos"),
        "payload": (
            "jsonb",
            NAO,
            "'{}'::jsonb",
            "nao — **redigido** (secao 6.2, ADR-010), e nao e so convencao: o "
            "`evt_emitir` da `0004` tem uma guarda que recusa um payload com "
            "padrao de telefone, e e ela que o criterio 8 do bloco usa para "
            "forcar a falha no *outbox*. O corpo cru do callback fica no "
            "`payment_callbacks_inbox` e nao e copiado para ca",
        ),
        "ocorrido_at": (
            "timestamp with time zone",
            SIM,
            None,
            "nao — o instante que o facilitador declara; anulavel porque nem "
            "todos o enviam",
        ),
        "recebido_at": (
            "timestamp with time zone",
            NAO,
            "now()",
            "nao — o instante da plataforma. **Nao entra no `row_hash`**: a "
            "verificacao da cadeia le-o da linha e nao o reconstroi",
        ),
        "prev_hash": (
            "bytea",
            NAO,
            "'\\x0000000000000000000000000000000000000000000000000000000000000000'::bytea",
            "nao — o elo anterior da cadeia por cobranca. A omissao sao trinta "
            "e dois zeros e **nao** `NULL`, pela razao da `0006`: com `NULL` o "
            "`sha256(NULL || ...)` e `NULL` e o `row_hash NOT NULL` recusava a "
            "primeira linha de cada cobranca",
        ),
        "row_hash": (
            "bytea",
            NAO,
            None,
            "nao — `sha256(prev_hash || campos canonicos)`, pela formula de "
            "`payment_event_row_hash`. Sem o `id` nem o `recebido_at`: um elo "
            "tem de se poder recalcular, e o `id` so existe depois do `INSERT`",
        ),
    },
    # `(tipo_evento, authn_method) -> tipo EVT`. Fica **vazia**: o conteudo
    # definitivo e do KAM-055, e um tipo sem mapeamento nao produz evento de
    # dominio. Configuracao **global** e nao dado de tenant, como a
    # `evt_subscricoes` da `0004` — e e por isso que nao tem `tenant_id` nem RLS.
    "payment_outbox_map": {
        "tipo_evento": ("text", NAO, None, "nao"),
        "authn_method": ("text", NAO, None, "nao"),
        "evt_tipo": ("text", NAO, None, "nao — nome de tipo de evento de dominio"),
        "evt_versao": ("smallint", NAO, "1", "nao"),
    },
    # ------------------------------------------------- KAM-054, revisao 0032
    #
    # As quatro da confirmacao humana auditada. **Nenhuma guarda telefone nem
    # texto de mensagem**, e nas duas primeiras isso e a regra M-1 e nao
    # higiene: quem confirma identifica-se pelo BSUID do canal resolvido a
    # `contact_id`, e nao ha coluna por onde uma mensagem a dizer «sou o dono»
    # entre. O `canal_msg_id` e um identificador opaco da Meta e nao o conteudo.
    "payment_confirmers": {
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "nao — referencia opaca a contacts (KAM-008). E o BSUID do canal "
            "resolvido, e e a unica forma de dizer quem confirma (M-1)",
        ),
        "papel": ("text", NAO, None, "nao — dominio fechado de dois valores"),
        "pode_segunda_aprovacao": ("boolean", NAO, "false", "nao"),
        "ativo": (
            "boolean",
            NAO,
            "true",
            "nao — retirar um funcionario e pôr isto a false, nao apagar a "
            "linha: a linha fica para a auditoria",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "manual_confirmations": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "charge_id": ("uuid", NAO, None, "nao"),
        "fase": ("text", NAO, None, "nao — dominio fechado de cinco valores"),
        "actor_contact_id": (
            "uuid",
            NAO,
            None,
            "nao — referencia opaca a contacts. Na fase declaracao_cliente e o "
            "contacto do cliente, e e dela que a guarda do M-1 le quem o cliente e",
        ),
        "canal_msg_id": (
            "text",
            NAO,
            None,
            "nao — identificador opaco da mensagem no canal, nao o conteudo "
            "dela. E a chave de idempotencia do criterio 9",
        ),
        "valor_declarado_minor": (
            "bigint",
            SIM,
            None,
            "nao — unidade menor inteira, e **nao e um saldo**: e o valor que o "
            "dono escreveu ao ver a app do banco dele (M-4). Ver "
            "`EM_UNIDADE_MENOR` em `test_catalogo.py`",
        ),
        "valor_bate": (
            "boolean",
            SIM,
            None,
            "nao — o veredicto do desafio do valor, sem tolerancia. Anulavel "
            "porque a declaracao do cliente nao tem valor declarado",
        ),
        "evidencia_ref": (
            "text",
            SIM,
            None,
            "nao — referencia ao anexo no STO, **nunca o conteudo**, e com o "
            "rotulo nao_prova imposto por CHECK (M-7). Nenhum modulo do "
            "ManualProvider le a imagem",
        ),
        "motivo": ("text", SIM, None, "nao — codigo de recusa, nao texto livre"),
        "decisao": (
            "text",
            SIM,
            None,
            "nao — o que a manual_confirmar decidiu nesta fase, de um dominio "
            "fechado de quatro. **E o predicado que o G8, a dupla do M-5 e a "
            "manual_janela leem**, e nao a fase: a fase e escrita por tres "
            "decisoes diferentes e por isso registava uma tentativa onde eles "
            "liam uma aprovacao. Anulavel nas fases que nao decidem nada, com a "
            "equivalencia imposta pelo manual_confirmations_decisao_da_fase",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "refund_cases": {
        "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "order_id": (
            "uuid",
            SIM,
            None,
            "nao — FK composta para a orders_mirror desde a `0035` (KAM-055), "
            "ao lado da da payment_charges: pô-la so num dos dois lados "
            "deixava o par incoerente",
        ),
        "charge_id": ("uuid", SIM, None, "nao"),
        "motivo": ("text", NAO, None, "nao — razao escrita, obrigatoria (M-8)"),
        "valor_minor": (
            "bigint",
            NAO,
            None,
            "nao — unidade menor inteira, e **nao e um saldo**: e o montante da "
            "cobranca que se reverteu, e a plataforma nao detem nada por causa "
            "dele (ADR-004, G-6). Ver `EM_UNIDADE_MENOR`",
        ),
        "estado": ("text", NAO, "'aberto'::text", "nao — dominio de quatro"),
        "prova_ref": (
            "text",
            SIM,
            None,
            "nao — referencia a prova que a PME junta ao executar, no STO",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
        "fechado_at": ("timestamp with time zone", SIM, None, "nao"),
        "pedido_evento_id": (
            "uuid",
            SIM,
            None,
            "nao — o id do envelope order.refund_requested que abriu o caso "
            "(KAM-197); nulo nos casos da manual_reverter",
        ),
    },
    "fraud_signals": {
        "id": ("bigint", NAO, None, "nao — identidade, pela razao do events_outbox"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            SIM,
            None,
            "nao — referencia opaca a contacts. Anulavel: um sinal pode ser do "
            "tenant e nao de um contacto",
        ),
        "charge_id": ("uuid", SIM, None, "nao"),
        "regra": ("text", NAO, None, "nao — nome da regra determinista"),
        "severidade": ("smallint", NAO, None, "nao — 1 a 5 por CHECK"),
        "accao": ("text", NAO, None, "nao — dominio fechado de cinco valores"),
        "detalhe": (
            "jsonb",
            NAO,
            "'{}'::jsonb",
            "nao — os agregados da janela e a identificacao da confirmacao. "
            "**Sem telefone e sem texto de mensagem**: o contacto vai na coluna "
            "contact_id",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
}

#: **A terceira vista do esquema** (KAM-053, revisao `0029`), e esta aqui pela
#: razao da `consent_actual` e da `v_draft_metrics`: a descoberta do
#: `information_schema.columns` apanha-a de qualquer forma, e numa vista o
#: PostgreSQL nao prova `NOT NULL` nem guarda omissao — logo `SIM` e `None` em
#: todas.
#:
#: Escreve-se **derivada** da tabela, como a `consent_actual` e pela mesma
#: razao: uma copia de dezoito colunas envelhece e ninguem nota. O que ela
#: acrescenta e **uma** coluna que a tabela nao tem — o `authn_hmac_ok` —, e o
#: que deixa de fora sao sete, cada uma por uma razao:
#:
#:   order_id, billing_cycle_id  o sujeito da cobranca, nao do evento. Quem
#:                               audita o ledger segue o `charge_id`
#:   provider_event_id           o id de entrega do facilitador: serve a
#:                               deduplicacao (G7) e nao a leitura de auditoria
#:   payload_hash, payload       o conteudo da entrega. A vista responde «o que
#:                               aconteceu», nao «o que veio no corpo»
#:   prev_hash, row_hash         a cadeia. Quem a verifica chama o
#:                               `verify_ledger_chain`, e a cabeca le-se na
#:                               `v_payment_ledger_heads`
#:
#: **A coluna chama-se `authn_hmac_ok` e nao o que o criterio 9 do bloco pede**:
#: o nome daquele criterio e variante de nivel 1 do *gate* 3b e falha em
#: qualquer superficie, incluindo dentro de uma cadeia. O predicado e o mesmo.
#: Ver o comentario de `_vistas` na revisao `0029`.
EXCLUIDAS_DA_VISTA_DO_LEDGER = (
    "order_id",
    "billing_cycle_id",
    "provider_event_id",
    "payload_hash",
    "payload",
    "prev_hash",
    "row_hash",
)

#: Os destinos de transferencia (KAM-069, revisao `0036`). **Catorze colunas**,
#: e a resposta a «guarda dados pessoais?» e `nao` em todas — incluindo a
#: `dados_pessoais` do inventario, que **nao e coluna desta tabela**: o
#: inventario de subprocessadores e um ficheiro (`gov/subprocessadores.yaml`) e
#: declara **classes** de dados, nunca valores.
#:
#: O que esta tabela guarda e configuracao de conformidade: quem, para que, para
#: onde, com que numero de procedimento. Um `apd_ref` e uma referencia emitida
#: por um orgao publico sobre a **KAMBÁ**, nao sobre um titular; um
#: `contrato_ref` aponta para um contrato arquivado fora daqui.
#:
#: **O `tenant_id` e a primeira coluna `tenant_id` ANULAVEL deste esquema**, e o
#: nulo e o destino global de infra-estrutura (criterio 1). Ver a nota do
#: `TABELAS_0036` em `base.py`.
INVENTARIO["tenant_destinations"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", SIM, None, "nao — e o nulo e o destino global"),
    "provider": ("text", NAO, None, "nao — nome de empresa, nao de pessoa"),
    "country": ("text", NAO, None, "nao"),
    "purpose": ("text", NAO, None, "nao"),
    "apd_ref": (
        "text",
        SIM,
        None,
        "nao — e a referencia de um procedimento da APD sobre a KAMBÁ, nao "
        "sobre um titular",
    ),
    "status": ("text", NAO, None, "nao"),
    "contrato_ref": (
        "text",
        SIM,
        None,
        "nao — aponta para um contrato arquivado fora desta base",
    ),
    "retencao_zero": ("boolean", NAO, None, "nao"),
    "sem_treino": ("boolean", NAO, None, "nao"),
    "autorizado_em": ("timestamp with time zone", SIM, None, "nao"),
    "revogado_em": ("timestamp with time zone", SIM, None, "nao"),
    "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    "atualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: Os pedidos do titular (KAM-070, revisao `0038`). **Dez colunas**, e a unica
#: que toca no titular e o `contact_id` — uma referencia opaca a `contacts`, por
#: FK composta com o `tenant_id`.
#:
#: **Nenhuma coluna de texto livre**, e e desenho: o `tipo`, o `estado` e o
#: `papel_kamba` sao dominios fechados por `CHECK`. Um pedido do titular nao
#: guarda o que ele escreveu — guarda o que a plataforma tem de fazer com ele.
#:
#: **O `papel_kamba` e `NOT NULL` sem omissao**, ao contrario de tudo o que ao
#: lado tem `DEFAULT`: a D9 — quem executa o pedido, a PME responsavel ou a
#: KAMBA subcontratada — esta aberta, e um `DEFAULT` na DDL fazia-a parecer
#: decidida a quem le o esquema. Ver a nota da revisao.
#:
#: **O `prazo_dias` e coluna e nao constante enterrada na aritmetica**: os 30
#: dias sao o interno do requisito 13 de E3 e os 60 dias uteis da Lei 22/11 sao
#: INDICIO. O que nao esta na base e a soma `recebido_at + prazo_dias` — um
#: `CHECK` sobre ela le o `TimeZone` da sessao (`timestamptz + interval` e
#: `STABLE` e nao `IMMUTABLE`), e uma restricao que depende de um GUC nao
#: restringe. O que fica e a ordenacao, no `dsar_requests_prazo_ordenado_ck`.
INVENTARIO["dsar_requests"] = {
    "dsar_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "contact_id": ("uuid", NAO, None, "referencia opaca ao contacto"),
    "tipo": ("text", NAO, None, "nao"),
    "estado": ("text", NAO, None, "nao"),
    "papel_kamba": ("text", NAO, None, "nao"),
    "recebido_at": ("timestamp with time zone", NAO, "now()", "nao"),
    "prazo_dias": ("smallint", NAO, None, "nao"),
    "prazo_interno_at": ("timestamp with time zone", NAO, None, "nao"),
    "concluido_at": ("timestamp with time zone", SIM, None, "nao"),
}

#: O ledger de apagamentos (KAM-070, revisao `0038`). **Seis colunas**, uma
#: linha por escopo que aplicou — e nao o registo do pedido outra vez.
#:
#: Quem conta os seis consumidores do `privacy.erasure_requested` e esta tabela,
#: pela unicidade `(tenant_id, dsar_id, escopo)`, e nao o barramento: o contrato
#: publicado do `privacy.erasure_applied` tem **um** campo de `payload`, o
#: `contact_id`, e **nao diz quem aplicou** — fechar o pedido a contar eventos
#: fechava-o ao sexto, viesse ele de seis componentes ou seis vezes do mesmo.
#:
#: **A chave e o `contact_id` e nao o `sujeito_ref` do dicionario §3**: esse e um
#: HMAC de chave **mensal**, pelo que o mesmo contacto tem refs diferentes em
#: meses diferentes e um ledger que lhe sobrevive meses nao se reaplica por ele.
#: E a razao esta no `COMMENT` da coluna, na propria base.
INVENTARIO["erasure_ledger"] = {
    "erasure_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "dsar_id": ("uuid", NAO, None, "nao"),
    "contact_id": ("uuid", NAO, None, "referencia opaca ao contacto"),
    "escopo": ("text", NAO, None, "nao"),
    "aplicado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: O registo da purga (KAM-071, revisao `0042`). **Nenhuma coluna guarda dado
#: pessoal, e e o criterio 5**: classe, tabela, tenant, contagens e janela, sem
#: conteudo nem identificador de titular. Nao ha onde caber um `contact_id`, uma
#: chave de objecto ou texto livre — o `motivo` e um dominio fechado.
INVENTARIO["purge_log"] = {
    "purge_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "execucao_id": ("uuid", NAO, None, "nao"),
    "classe": ("text", NAO, None, "nome da classe de retencao"),
    "tabela": ("text", NAO, None, "nome qualificado de uma tabela"),
    "tenant_id": ("uuid", SIM, None, "nao"),
    "modo": ("text", NAO, None, "nao"),
    "resultado": ("text", NAO, None, "nao"),
    "motivo": ("text", SIM, None, "dominio fechado, sem texto livre"),
    "linhas": ("bigint", NAO, None, "nao"),
    "objectos": ("bigint", NAO, "0", "nao"),
    "janela_ate": ("timestamp with time zone", SIM, None, "nao"),
    "politica_versao": ("text", NAO, None, "nao"),
    "iniciado_at": ("timestamp with time zone", NAO, None, "nao"),
    "registado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: O caso de onboarding (KAM-087, revisao `0043`; DDL do KAM-086). **O NIF e o
#: telefone vao cifrados em aplicacao e com HMAC ao lado**, como em `contacts`:
#: o HMAC e para a correspondencia e o indice unico, e nao se inverte. O
#: `nome_negocio` e o nome do negocio e nao da pessoa, mas numa PME em nome
#: individual pode ser o nome do dono — fica respondido como dado pessoal.
INVENTARIO["onboarding_case"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": (
        "uuid",
        NAO,
        "gen_random_uuid()",
        "nao — pre-alocado no registo, sem FK: a linha de `tenants` nasce no "
        "passo 1 da saga (KAM-091)",
    ),
    "fase": ("text", NAO, "'registo'::text", "nao"),
    "fase_at": ("timestamp with time zone", NAO, "now()", "nao"),
    "origem": ("text", NAO, None, "nao"),
    "nome_negocio": (
        "text",
        NAO,
        None,
        "pode ser — numa PME em nome individual e o nome do dono",
    ),
    "categoria_declarada": ("text", NAO, None, "nao"),
    "nif_enc": ("bytea", NAO, None, "cifrado em aplicacao (ADR-010)"),
    "nif_hmac": ("bytea", NAO, None, "HMAC do NIF; pseudonimo, nao se inverte"),
    "phone_enc": ("bytea", NAO, None, "cifrado em aplicacao (ADR-010)"),
    "phone_hmac": ("bytea", NAO, None, "HMAC do telefone; pseudonimo, nao se inverte"),
    "email_enc": ("bytea", SIM, None, "cifrado em aplicacao (ADR-010)"),
    "device_hash": ("bytea", SIM, None, "HMAC grosseiro do dispositivo; pseudonimo"),
    "ip_prefix_hash": ("bytea", SIM, None, "HMAC do prefixo de IP, nunca o endereco"),
    "flags": ("ARRAY", NAO, "'{}'::text[]", "nao"),
    "owner_active_seconds": ("integer", NAO, "0", "nao"),
    "preflight": (
        "jsonb",
        SIM,
        None,
        "nao — itens e detalhes de listas fechadas (KAM-093), sem texto livre",
    ),
    "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    "activo_at": ("timestamp with time zone", SIM, None, "nao"),
}

#: A verificacao K1 de um documento (KAM-087, revisao `0043`). **O documento
#: nao esta aqui**: esta no STO, e a linha guarda a chave. Os campos lidos (NIF,
#: nome, BI, IBAN) vao cifrados em aplicacao no `extraido_enc`, e esquecem-se a
#: D+30 de um caso rejeitado ou abandonado.
INVENTARIO["kyc_check"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "onboarding_id": ("uuid", NAO, None, "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "doc_tipo": ("text", NAO, None, "nao"),
    "doc_ref": (
        "text",
        NAO,
        None,
        "nao — a chave do objecto no STO, que guarda o documento; o acesso e "
        "por URL assinada de 300 s e auditado",
    ),
    "sha256": ("bytea", NAO, None, "nao — resumo do ficheiro"),
    "phash": ("bytea", SIM, None, "nao — dHash de 64 bits da imagem"),
    "extraido_enc": (
        "bytea",
        SIM,
        None,
        "cifrado em aplicacao (AES-256-GCM): NIF, nome do titular, BI e IBAN",
    ),
    "flags": ("ARRAY", NAO, "'{}'::text[]", "nao"),
    "score": ("smallint", SIM, None, "nao"),
    "resultado": ("text", NAO, None, "nao"),
    "versao_regras": ("text", NAO, None, "nao"),
    "custo_micro_usd": ("integer", NAO, "0", "nao"),
    "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: A decisao de screening (KAM-088, revisao `0044`). **O texto do produto nao
#: esta aqui**: a linha guarda o `sha256` do conteudo decidido, e a
#: `sujeito_ref` e o `sku` ou o texto da categoria declarada pelo dono.
INVENTARIO["screening_decision"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "onboarding_id": ("uuid", SIM, None, "nao"),
    "sujeito_tipo": ("text", NAO, None, "nao"),
    "sujeito_ref": (
        "text",
        NAO,
        None,
        "nao — o `sku` do produto, ou a categoria declarada do negocio",
    ),
    "decisao": ("text", NAO, None, "nao"),
    "regras": ("ARRAY", NAO, None, "nao — ids de regras da politica"),
    "versao_politica": ("text", NAO, None, "nao"),
    "origem": ("text", NAO, None, "nao"),
    "conteudo_sha256": ("bytea", NAO, None, "nao — resumo do conteudo decidido"),
    "criado_at": ("timestamp with time zone", NAO, "clock_timestamp()", "nao"),
}

#: O caso de revisao (KAM-089, revisao `0048`). **Nenhum dado pessoal**: as
#: evidencias sao referencias (`kyc_check`, `screening_decision`,
#: `onboarding_case`), o motivo interno e composto de codigos pelo modulo
#: (`marcas=...;score=...`) e o publico e de lista fechada.
INVENTARIO["review_case"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tipo": ("text", NAO, None, "nao"),
    "onboarding_id": ("uuid", SIM, None, "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "motivo_codigo": ("text", NAO, None, "nao"),
    "motivo_interno": (
        "text",
        NAO,
        None,
        "nao — codigos de marcas e regras, composto pelo modulo; so para T&S",
    ),
    "motivo_publico": ("text", NAO, None, "nao"),
    "evidencias": ("jsonb", NAO, "'[]'::jsonb", "nao — referencias, nunca copias"),
    "recomendacao": ("text", SIM, None, "nao"),
    "estado": ("text", NAO, "'aberto'::text", "nao"),
    "prioridade": ("smallint", NAO, "5", "nao"),
    "fila_at": ("timestamp with time zone", NAO, "now()", "nao"),
    "sla_alerta_at": ("timestamp with time zone", NAO, None, "nao"),
    "sla_due_at": ("timestamp with time zone", NAO, None, "nao"),
    "sla_alertado_at": ("timestamp with time zone", SIM, None, "nao"),
    "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: A decisao do revisor (KAM-089, revisao `0048`). A `nota_enc` e texto livre
#: do revisor e **pode** levar dados pessoais: vai cifrada em aplicacao, com o
#: `review_case:<id>` como contexto, e nunca sai para o dono.
INVENTARIO["review_decision_log"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "case_id": ("uuid", NAO, None, "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "revisor_id": ("uuid", NAO, None, "nao — identificador de staff, nao do titular"),
    "decisao": ("text", NAO, None, "nao"),
    "instancia": ("text", NAO, "'primeira'::text", "nao"),
    "regra": ("text", SIM, None, "nao"),
    "nota_enc": ("bytea", SIM, None, "sim — cifrada em aplicacao"),
    "em": ("timestamp with time zone", NAO, "clock_timestamp()", "nao"),
}

#: A ingestao do Catalogo AI (KAM-049, revisao do Catalogo AI). **A foto nao
#: esta aqui**: a `media_ref` e a chave do objecto no STO do proprio tenant
#: (presa a ele por `CHECK`), e o EXIF e o GPS saem antes do STO. O `extraido`
#: guarda o que a visao leu do produto, campo a campo, e e catalogo e nao
#: pessoa. Dezoito colunas.
INVENTARIO["catalog_ingestions"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "media_ref": (
        "text",
        NAO,
        None,
        "nao — a chave do objecto no STO do tenant, nunca a URL da Meta",
    ),
    "media_id_meta": ("text", SIM, None, "nao — identificador da midia na Meta"),
    "phash": ("bytea", SIM, None, "nao — hash perceptual (DCT) de 64 bits da imagem"),
    "estado": ("text", NAO, "'recebida'::text", "nao"),
    "extraido": (
        "jsonb",
        NAO,
        "'{}'::jsonb",
        "nao — campos do produto (valor, confianca, fonte), lidos da foto",
    ),
    "campos_em_falta": ("ARRAY", NAO, "'{}'::text[]", "nao"),
    "perguntas_feitas": ("smallint", NAO, "0", "nao"),
    "categoria_restrita": ("text", SIM, None, "nao — id de regra da politica"),
    "sku": ("text", SIM, None, "nao"),
    "custo_llm_usd": ("numeric", NAO, "0", "nao"),
    "confirmado_at": ("timestamp with time zone", SIM, None, "nao"),
    "confirmado_por": (
        "text",
        SIM,
        None,
        "nao — identificador do actor que confirmou, nunca o nome nem o telefone",
    ),
    "ultima_mensagem_id": (
        "text",
        SIM,
        None,
        "nao — identificador da ultima mensagem do dono processada, nunca o texto",
    ),
    "versao": ("integer", NAO, "0", "nao"),
    "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    "atualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: Os sinais de Trust & Safety (KAM-097). **Sem dados pessoais**: o `detalhe` so
#: admite chaves de referencia (`order_id`, `sku`, contagens), fechadas por
#: `CHECK`, e o `ref_evento` e um evento ou um agregado. Oito colunas.
INVENTARIO["ts_signal"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "tipo": ("text", NAO, None, "nao"),
    "severidade": ("text", NAO, None, "nao"),
    "ref_evento": ("uuid", NAO, None, "nao — o evento, ou o agregado do sinal"),
    "detalhe": ("jsonb", NAO, "'{}'::jsonb", "nao — so chaves de referencia, por CHECK"),
    "ocorrido_em": ("timestamp with time zone", NAO, None, "nao"),
    "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: A escada de sancoes de Trust & Safety (KAM-097). O `motivo_interno` e texto de
#: T&S sobre o comportamento de uma loja, nao sobre uma pessoa; o `autor` e um
#: identificador de staff ou `sistema:<versao>`. Quinze colunas.
INVENTARIO["ts_sanction"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "chave": ("text", NAO, None, "nao"),
    "passo": ("text", NAO, None, "nao"),
    "origem": ("text", NAO, None, "nao"),
    "motivo_interno": ("text", NAO, None, "nao — so para T&S; o kamba_app nao o le"),
    "motivo_publico": ("text", NAO, None, "nao — codigo de lista fechada"),
    "autor": ("text", NAO, None, "nao — identificador de staff ou do sistema"),
    "regra": ("text", SIM, None, "nao"),
    "sinais": ("jsonb", NAO, "'[]'::jsonb", "nao — identificadores de ts_signal"),
    "case_id": ("uuid", SIM, None, "nao"),
    "justificacao_salto": ("text", SIM, None, "nao — texto de T&S sobre a loja"),
    "recurso_de": ("uuid", SIM, None, "nao"),
    "recurso_estado": ("text", SIM, None, "nao"),
    "em": ("timestamp with time zone", NAO, "clock_timestamp()", "nao"),
}

#: As versoes publicadas dos quatro documentos (KAM-090, revisao `0040`).
#: **Sem `tenant_id`**: texto de plataforma, como a `consent_texts`. O
#: `conteudo` e o texto juridico (com marcadores ate ao parecer do KAM-104), e
#: **nao** e dado pessoal — e o mesmo para todos os tenants.
INVENTARIO["contract_document"] = {
    "document_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "tipo": ("text", NAO, None, "nao"),
    "versao": ("text", NAO, None, "nao"),
    "sha256": ("bytea", NAO, None, "nao"),
    "conteudo": ("text", NAO, None, "nao: texto juridico de plataforma"),
    "vigente_desde": ("timestamp with time zone", NAO, None, "nao"),
    "publicado_em": ("timestamp with time zone", NAO, "now()", "nao"),
}

#: A prova de um aceite (KAM-090, revisao `0040`). **Onze colunas**, as do
#: criterio 3 e do DDL do bloco. Sem dado pessoal, que e a caixa 4 da DoD: o
#: signatario e uma **referencia** ao titular do caso, e o IP so entra como
#: `sha256` do prefixo (ADR-010). O `aceite_em` e o `evidence_hash` escreve-os o
#: *trigger* `contract_acceptance_preparar`, por cima do que o chamador mandou.
INVENTARIO["contract_acceptance"] = {
    "id": ("uuid", NAO, "gen_random_uuid()", "nao"),
    "onboarding_id": ("uuid", NAO, None, "nao"),
    "tenant_id": ("uuid", NAO, None, "nao"),
    "document_id": ("uuid", NAO, None, "nao"),
    "versao": ("text", NAO, None, "nao"),
    "doc_sha256": ("bytea", NAO, None, "nao"),
    "signatario_ref": ("uuid", NAO, None, "referencia opaca ao titular do caso"),
    "otp_challenge_id": ("uuid", NAO, None, "nao"),
    "ip_prefix_hash": ("bytea", SIM, None, "hash do prefixo; nunca o endereco"),
    "aceite_em": ("timestamp with time zone", NAO, "now()", "nao"),
    "evidence_hash": ("bytea", NAO, None, "nao"),
}

#: **A quinta vista do esquema** (KAM-069, revisao `0036`), e a primeira que
#: atravessa esquemas: le `dat.llm_call_log` e `platform.tenant_destinations`.
#:
#: Escreve-se **a mao** e nao derivada, e a razao nao e a da
#: `v_payment_ledger_heads` (que tem um `AS`): aqui a tabela de que as colunas
#: vem — a `dat.llm_call_log` — **nao esta neste inventario**, que filtra
#: `table_schema = 'platform'`. Derivar exigia um segundo inventario para o
#: `dat`, e um inventario de um esquema que nenhum teste confronta nao e um
#: inventario.
#:
#: As sete colunas sao as da chamada, e o que **nao** esta aqui e o que uma
#: pergunta de conformidade nao precisa: os quatro contadores de *tokens*, o
#: custo, a latencia, o `trace_id`, a `vertical`, o `no_grafo` e o
#: `graph_version`. Quem audita transferencias pergunta «quem, quando, para que
#: fornecedor, com que desfecho» — e nao «quanto custou».
#:
#: Como nas outras cinco, `SIM` e `None` em todas: numa vista o PostgreSQL nao
#: prova `NOT NULL` nem guarda omissao. (Eram quatro ate a `v_oferta_viva` do
#: KAM-051 entrar; uma contagem em prosa que a sexta vista tornou falsa, e que
#: nenhum linter le — os `.md` tem o `lint_contagens` e os comentarios `.py` nao
#: tem nada.)
INVENTARIO["v_transfer_audit"] = {
    "id": ("bigint", SIM, None, "nao"),
    "ts": ("timestamp with time zone", SIM, None, "nao"),
    "tenant_id": ("uuid", SIM, None, "nao"),
    "fornecedor": ("text", SIM, None, "nao — nome de empresa, nao de pessoa"),
    "modelo": ("text", SIM, None, "nao"),
    "papel": ("text", SIM, None, "nao"),
    "resultado": ("text", SIM, None, "nao"),
}

#: **A setima vista do esquema** (KAM-081): o custo por tenant, dia e rubrica.
#: O SQL vive em `db/custo.py`, e o `custo.COLUNAS` e a mesma lista que esta, por
#: ordem — o `db/tests/test_custo_schema.py` compara a base com aquela tuple e
#: esta tabela com a base, pelo que as tres nao divergem sem um vermelho.
#:
#: **O que nao esta aqui e o criterio 7** («sem conteudo nem `contact_id` nas
#: vistas expostas»): a `outbound_messages` e lida e o `contact_id`, o
#: `conversation_id`, o `wamid` e o `pricing` dela nao saem; da `llm_call_log`
#: saem so somas e contagens. Nenhuma coluna aponta para uma pessoa.
#:
#: Como nas outras seis, `SIM` e `None` em todas: numa vista o PostgreSQL nao
#: prova `NOT NULL` nem guarda omissao.
#: A vista do SLA da fila de revisao (KAM-089, revisao `0048`). Escreve-se a
#: mao pela razao das outras: duas das dez colunas nao sao colunas do caso (a
#: primeira decisao, do registo, e o `dentro_do_sla`, calculado). As colunas de
#: uma vista sao todas anulaveis no catalogo.
INVENTARIO["v_review_sla"] = {
    "case_id": ("uuid", SIM, None, "nao"),
    "tenant_id": ("uuid", SIM, None, "nao"),
    "tipo": ("text", SIM, None, "nao"),
    "estado": ("text", SIM, None, "nao"),
    "prioridade": ("smallint", SIM, None, "nao"),
    "fila_at": ("timestamp with time zone", SIM, None, "nao"),
    "sla_alerta_at": ("timestamp with time zone", SIM, None, "nao"),
    "sla_due_at": ("timestamp with time zone", SIM, None, "nao"),
    "primeira_decisao_at": ("timestamp with time zone", SIM, None, "nao"),
    "dentro_do_sla": ("boolean", SIM, None, "nao"),
}

INVENTARIO["v_tenant_cost_daily"] = {
    "tenant_id": ("uuid", SIM, None, "nao"),
    "dia": ("date", SIM, None, "nao — o dia no fuso do tenant, sem hora"),
    "rubrica": ("text", SIM, None, "nao"),
    "unidades": ("bigint", SIM, None, "nao — uma contagem"),
    "sem_preco": ("bigint", SIM, None, "nao — uma contagem"),
    "custo_usd": ("numeric", SIM, None, "nao"),
    "custo_aoa_minor": ("bigint", SIM, None, "nao"),
    "fx_aoa_per_usd": ("numeric", SIM, None, "nao — o cambio da sessao"),
}

#: **A sexta vista do esquema** (KAM-051, revisao `0037`): o contrato de leitura
#: da oferta viva, que a tool `search_products` junta aos candidatos do indice
#: (`docs/tecnica/05` secao 6.3).
#:
#: Escreve-se **a mao** e nao derivada da `offer_terms`, pela razao da
#: `v_payment_ledger_heads`: tres das nove colunas nao sao colunas daquela
#: tabela — o `product_ref` e um `AS` sobre o `sku`, o `publicado` e um predicado
#: e o `lido_em` e o `now()` da leitura —, e derivar dava os nomes errados.
#:
#: **O que nao esta aqui e metade da resposta ao criterio 6** («a vista nao
#: contem PII nem texto de descricao»). A aritmetica das dezesseis colunas da
#: `offer_terms`, que a primeira versao deste comentario dava errada em tres
#: sitios (dizia «quatro»), medida coluna a coluna:
#:
#:   * **seis** saem projectadas — `tenant_id`, `sku`, `nome`, `preco_minor`,
#:     `preco_tipo`, `stock_modo` (o `sku` sai duas vezes, tambem como
#:     `product_ref`);
#:   * **quatro** sao lidas **so dentro de expressao** e nao aparecem: o
#:     `preco_valido_ate` no `CASE` do `preco_tipo`, e o `estado`, o
#:     `deleted_at` e a `categoria_restrita` no predicado do `publicado`;
#:   * **seis** nunca sao lidas: `medusa_variant_id`, `currency`,
#:     `preco_atualizado_at`, `stock_verificado_at`, `criado_at`,
#:     `atualizado_at`.
#:
#: **E nao ha coluna de nivel de stock nenhuma:** o criterio 7 esta bloqueado
#: pelo D3 e pelo KAM-045.
#:
#: Como nas outras cinco, `SIM` e `None` em todas: numa vista o PostgreSQL nao
#: prova `NOT NULL` nem guarda omissao.
INVENTARIO["v_oferta_viva"] = {
    "tenant_id": ("uuid", SIM, None, "nao"),
    "product_ref": (
        "text",
        SIM,
        None,
        "nao — a referencia opaca por que o indice trata o produto, e **e** o "
        "`sku`: o criterio 6 exige que o *join* por `(tenant_id, product_ref)` "
        "caia no `offer_terms_pkey`, que e `(tenant_id, sku)`. Nao e o "
        "`medusa_variant_id`, que e nulo em toda a Fase 0 e seria o modelo "
        "interno do Registo, que o bloco manda nao expor",
    ),
    "sku": ("text", SIM, None, "nao — a mesma resposta do `offer_terms.sku`"),
    "nome": (
        "text",
        SIM,
        None,
        "nao — nome comercial do produto, nunca de pessoa singular. A mesma "
        "resposta do `offer_terms.nome`, e aqui com uma razao a mais: esta "
        "vista nao projecta texto de descricao nenhum (criterio 6)",
    ),
    "preco_minor": (
        "bigint",
        SIM,
        None,
        "nao — preco de catalogo em unidade menor. Declarado no "
        "`EM_UNIDADE_MENOR` de `db/tests/test_catalogo.py`, que e o que pagar a "
        "vista no `platform` compra",
    ),
    "preco_tipo": (
        "text",
        SIM,
        None,
        "nao — e **nao** e sempre o valor guardado: passado o "
        "`preco_valido_ate`, um `fixo` sai como `a_partir_de` (regra 2 do "
        "`docs/tecnica/03` secao 7.1). So o `fixo` degrada",
    ),
    "stock_modo": (
        "text",
        SIM,
        None,
        "nao — o modo canonico em tres valores, e **nao** uma coluna "
        "`disponibilidade`: esse nome e, desde o KAM-043, o texto de "
        "apresentacao derivado deste",
    ),
    "publicado": (
        "boolean",
        SIM,
        None,
        "nao — predicado do criterio 2 (`estado='publicado'`, `deleted_at` nulo "
        "e `categoria_restrita` nula), exposto e nao aplicado: quem filtra e o "
        "`WHERE v.publicado` da secao 6.3",
    ),
    "lido_em": ("timestamp with time zone", SIM, None, "nao"),
}

INVENTARIO["v_payment_events_audit"] = {
    coluna: (tipo, SIM, None, pessoal)
    for coluna, (tipo, _, _, pessoal) in INVENTARIO["payment_events"].items()
    if coluna not in EXCLUIDAS_DA_VISTA_DO_LEDGER
}
#: O predicado de HMAC do `docs/tecnica/08` secao 14, derivado e nao guardado.
INVENTARIO["v_payment_events_audit"]["authn_hmac_ok"] = ("boolean", SIM, None, "nao")

#: **A quarta vista** (KAM-053): a cabeca da cadeia de *hashes* por cobranca,
#: que o *job* diario exporta para STO como ancora externa (secao 8) — uma
#: cadeia cuja cabeca esta fora do *host* nao se reescreve sem se notar.
#:
#: Escreve-se **a mao** e nao derivada, ao contrario da vista acima: o
#: `event_id` e um `AS` sobre o `id` da tabela, e derivar daria o nome errado.
INVENTARIO["v_payment_ledger_heads"] = {
    "charge_id": ("uuid", SIM, None, "nao"),
    "tenant_id": ("uuid", SIM, None, "nao"),
    "event_id": ("bigint", SIM, None, "nao"),
    "sequencia": ("integer", SIM, None, "nao"),
    "row_hash": ("bytea", SIM, None, "nao"),
    "recebido_at": ("timestamp with time zone", SIM, None, "nao"),
}

#: **A segunda vista do esquema** (KAM-114), e esta no inventario pela razao da
#: `consent_actual`: a descoberta do `information_schema.columns` apanha-a de
#: qualquer forma. Como la, declara-se `SIM` e `None` em todas — numa vista o
#: PostgreSQL nao prova `NOT NULL` nem guarda omissao.
#:
#: Escreve-se **a mao** e nao derivada da tabela, ao contrario da
#: `consent_actual`: nenhuma destas colunas e uma coluna da `draft_decisions`.
#: Sao contagens, uma razao e tres percentis — derivar daria os nomes errados.
#:
#: **Nenhuma responde `sim`, e e o desenho:** o que a vista mostra sao medidas
#: agregadas por `(tenant_id, graph_version)`, que e onde o criterio 6 manda a
#: desagregacao que a gramatica de etiqueta do `kamba_core.ten.metricas` recusa
#: como serie — o `tenant_id` tem hifenes e o `1.1.0` comeca por digito.
INVENTARIO["v_draft_metrics"] = {
    "tenant_id": ("uuid", SIM, None, "nao"),
    "graph_version": ("text", SIM, None, "nao"),
    "draft_total": ("bigint", SIM, None, "nao"),
    "draft_pendentes": ("bigint", SIM, None, "nao"),
    "draft_approved_ratio": ("numeric", SIM, None, "nao"),
    # Os tres percentis sao `double precision` e **nao** `numeric`: o
    # `percentile_cont` nao tem variante `numeric`, pelo que a entrada e
    # convertida para `float8` e o resultado sai assim. Nao contradiz a
    # convencao do §2 — o que ela proibe e virgula flutuante a guardar
    # **dinheiro**, e isto e dispersao sobre numeros ja gravados.
    "draft_edit_ratio_p50": ("double precision", SIM, None, "nao"),
    "draft_decision_latency_s_p50": ("double precision", SIM, None, "nao"),
    "draft_decision_latency_s_p90": ("double precision", SIM, None, "nao"),
}

#: **A primeira vista do esquema** (KAM-022), e esta no inventario e nao fora
#: dele: uma vista sobre dados pessoais tem a mesma pergunta a responder que uma
#: tabela, e a descoberta do `information_schema.columns` apanha-a de qualquer
#: forma. O que muda sao as duas colunas de forma — numa vista o PostgreSQL nao
#: prova `NOT NULL` nem guarda omissao —, e por isso declara-se `SIM` e `None`
#: em todas.
#:
#: Escreve-se **derivada** da tabela, e nao a mao, pela razao do
#: `events_log_default` logo abaixo: uma copia das colunas envelhece e ninguem
#: nota. O que a vista mostra e um subconjunto proprio de `consent_event`, e as
#: tres que ficam de fora ficam de fora por uma razao cada:
#:
#:   id             e a chave da linha, e a vista responde por trio e nao por
#:                  linha. Expo-la convidava a guarda-la como referencia a uma
#:                  linha que a vista pode deixar de escolher amanha.
#:   evidence_hash  e a **prova**, e quem pergunta «este contacto aceitou?» nao
#:                  precisa dela — precisa da resposta. Quem a precisa le a
#:                  tabela, e nao e o mesmo caminho.
#:   canal          e o transporte por onde o consentimento foi dado, e nao faz
#:                  parte da resposta: o consentimento vale para o titular, nao
#:                  para o transporte em que ele o deu.
#:   registado_em   e a chave de ordem da propria vista, e nao uma resposta:
#:                  quem pergunta «aceitou?» quer saber **quando aconteceu** (o
#:                  `ocorrido_em`), nao quando nos escrevemos a linha.
EXCLUIDAS_DA_VISTA = ("id", "evidence_hash", "canal", "registado_em")

INVENTARIO["consent_actual"] = {
    coluna: (tipo, SIM, None, pessoal)
    for coluna, (tipo, _, _, pessoal) in INVENTARIO["consent_event"].items()
    if coluna not in EXCLUIDAS_DA_VISTA
}

#: A particao `DEFAULT` tem as colunas do pai, uma a uma. Esta aqui — e nao
#: escrita a mao — porque uma particao que divergisse do pai era impossivel no
#: PostgreSQL, e repetir onze linhas convidava a que divergissem **no
#: inventario**: a copia envelhecia e ninguem notava.
INVENTARIO["events_log_default"] = dict(INVENTARIO["events_log"])

#: O inventario fechado do esquema `servicos` (KAM-047, revisao `0025`).
#:
#: **Num dicionario proprio, e nao dentro do `INVENTARIO`.** Aquele e indexado
#: por nome de tabela sem esquema e a sua consulta filtra `table_schema =
#: 'platform'`: um nome solto la dentro fazia a asercao procurar
#: `platform.bookings`, que nao existe, e o teste falhava por uma tabela a menos
#: em vez de medir alguma coisa. E a mesma separacao que o `TABELAS_LG` e o
#: `TABELAS_DAT` fazem em `tests/base.py`.
#:
#: **E e o primeiro inventario de colunas fora do `platform`.** O `lg` (KAM-026)
#: e o `dat` (KAM-030) nunca ganharam um, e isso continua a ser uma lacuna — mas
#: nao desta revisao: fecha-la para eles e mexer em tabelas de outros tickets.
#: Fica em `docs/dividas-documentais.md`.
#:
#: tabela -> coluna -> (tipo, anulavel, omissao, guarda dados pessoais?)
INVENTARIO_SERVICOS = {
    "services": {
        "service_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "nome": ("text", NAO, None, "nome do servico, nao de pessoa singular"),
        "duracao_min": ("integer", NAO, None, "nao"),
        "preco_tipo": ("text", NAO, None, "nao"),
        "preco_minor": ("bigint", SIM, None, "nao"),
        "currency": ("text", NAO, "'AOA'::text", "nao"),
        "ativo": ("boolean", NAO, "true", "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "resources": {
        "resource_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        # **A unica coluna deste esquema que pode nomear uma pessoa**, e por isso
        # a unica que a resposta nao despacha com «nao». E o nome de trabalho de
        # um profissional da PME — o que o cliente ve na lista de opcoes —, nao
        # um dado de identificacao: nao ha telefone, BI, morada nem e-mail nesta
        # tabela, e o que a protege e a RLS `FORCE` mais a falta de qualquer
        # privilegio para os papeis que nao sao o da aplicacao e o de lote.
        "nome": (
            "text",
            NAO,
            None,
            "nome de trabalho do profissional, escrito pela PME; sem telefone, "
            "BI nem morada",
        ),
        "ativo": ("boolean", NAO, "true", "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "availability_rules": {
        "rule_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "resource_id": ("uuid", NAO, None, "nao"),
        "dia_semana": ("smallint", NAO, None, "nao"),
        "inicio": ("time without time zone", NAO, None, "nao"),
        "fim": ("time without time zone", NAO, None, "nao"),
        "fuso": ("text", NAO, "'Africa/Luanda'::text", "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "bookings": {
        "booking_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "contact_id": (
            "uuid",
            NAO,
            None,
            "referencia opaca a platform.contacts (KAM-008); nunca um telefone",
        ),
        "service_id": ("uuid", NAO, None, "nao"),
        "resource_id": ("uuid", NAO, None, "nao"),
        # Token assinado do *slot* (`servicos/slots.ts`). Leva o servico, o
        # recurso e o intervalo — nada de pessoa — e a assinatura e derivada por
        # tenant, pelo que o token de um tenant nao verifica noutro.
        "slot_id": (
            "text",
            NAO,
            None,
            "token assinado com servico, recurso e intervalo; sem dados de pessoa",
        ),
        "hold_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "inicio_at": ("timestamp with time zone", NAO, None, "nao"),
        "fim_at": ("timestamp with time zone", NAO, None, "nao"),
        "estado": ("text", NAO, None, "nao"),
        "hold_expires_at": ("timestamp with time zone", SIM, None, "nao"),
        "version": ("integer", NAO, "1", "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
}

#: O inventario fechado do esquema `idx` (KAM-061, revisao `0045`), num
#: dicionario proprio pela razao do `INVENTARIO_SERVICOS`.
#:
#: **Nenhuma coluna guarda dados de pessoa**, e e essa a regra do esquema: o
#: indice e o catalogo da PME normalizado, e o §4.2 do `docs/tecnica/05` diz que
#: o `descr_norm` vem do catalogo e nunca de mensagens de clientes. O
#: `information_schema` da o `halfvec` como `USER-DEFINED` e a coluna gerada sem
#: omissao (a expressao vive no `generation_expression`, nao no
#: `column_default`).
INVENTARIO_IDX = {
    # KAM-062 (revisao `0049`): a versao do lexico. Sem `tenant_id` e sem pessoa.
    "norm_versao": {
        "versao": ("bigint", NAO, None, "nao"),
        "afecta_indice": ("boolean", NAO, None, "nao"),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "search_doc": {
        "doc_id": ("uuid", NAO, "gen_random_uuid()", "nao"),
        "tenant_id": ("uuid", NAO, None, "nao"),
        "product_ref": ("text", NAO, None, "nao; o sku da oferta (ADR-003)"),
        "norm_versao": ("integer", NAO, None, "nao"),
        "nome_norm": ("text", NAO, None, "nao; nome do produto normalizado"),
        "marca_canon": ("text", SIM, None, "nao"),
        "categoria_canon": ("text", SIM, None, "nao"),
        "descr_norm": (
            "text",
            NAO,
            "''::text",
            "nao; vem do catalogo da PME, nunca de mensagens de clientes (§4.2)",
        ),
        "zona": ("text", SIM, None, "nao; zona da loja, nao de pessoa"),
        "visivel": ("boolean", NAO, "true", "nao"),
        "visivel_federado": ("boolean", NAO, "false", "nao"),
        "embedding": (
            "USER-DEFINED",
            SIM,
            None,
            "nao; vector do texto do catalogo, nunca de uma pergunta",
        ),
        "embedding_modelo": ("text", SIM, None, "nao"),
        "fts": ("tsvector", SIM, None, "nao; gerada do texto do catalogo"),
        "atualizado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
    "termo_canonico": {
        "id": ("bigint", NAO, None, "nao"),
        "tenant_id": ("uuid", SIM, None, "nao; nulo e entrada global"),
        "tipo": ("text", NAO, None, "nao"),
        "termo": ("text", NAO, None, "nao; termo de lexico"),
        "canonico": ("text", NAO, None, "nao; termo de lexico"),
        "peso": ("real", NAO, "1.0", "nao"),
        "origem": ("text", NAO, None, "nao"),
        "activo": ("boolean", NAO, "true", "nao"),
        "aprovado_por": (
            "text",
            SIM,
            None,
            "nao; texto livre de ops, nunca contacto de cliente",
        ),
        "criado_at": ("timestamp with time zone", NAO, "now()", "nao"),
    },
}


class TestInventario(ComBase):
    def no_catalogo(self, esquema: str = "platform") -> dict[str, dict[str, tuple]]:
        linhas = self.consultar(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = %s",
            (esquema,),
        )
        resultado: dict[str, dict[str, tuple]] = {}
        for tabela, coluna, tipo, anulavel, omissao in linhas:
            resultado.setdefault(tabela, {})[coluna] = (tipo, anulavel, omissao)
        return resultado

    def test_o_catalogo_e_exactamente_o_inventario(self) -> None:
        catalogo = self.no_catalogo()
        self.assertEqual(set(catalogo), set(INVENTARIO), "tabelas a mais ou a menos")
        for tabela, colunas in INVENTARIO.items():
            self.assertEqual(
                set(catalogo[tabela]),
                set(colunas),
                f"colunas de {tabela} diferem do inventario: uma coluna nova tem de "
                "ser declarada em db/tests/test_inventario.py, com a resposta a "
                "«guarda dados pessoais?»",
            )
            for coluna, (tipo, anulavel, omissao, _) in colunas.items():
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    self.assertEqual(catalogo[tabela][coluna], (tipo, anulavel, omissao))

    def test_o_catalogo_do_servicos_e_exactamente_o_inventario(self) -> None:
        """O mesmo trinco da `platform`, para o esquema `servicos` (KAM-047).

        Sem isto, uma coluna nova em `servicos.bookings` entrava sem ninguem
        responder «isto guarda dados pessoais?» — a pergunta que este ficheiro
        existe para fazer. O `test_o_catalogo_e_exactamente_o_inventario`
        **nao** a fazia: filtra `table_schema = 'platform'`, e um esquema novo
        era invisivel para ele.
        """
        catalogo = self.no_catalogo("servicos")
        self.assertEqual(
            set(catalogo),
            set(INVENTARIO_SERVICOS),
            "tabelas a mais ou a menos no esquema servicos",
        )
        for tabela, colunas in INVENTARIO_SERVICOS.items():
            self.assertEqual(
                set(catalogo[tabela]),
                set(colunas),
                f"colunas de servicos.{tabela} diferem do inventario: uma coluna "
                "nova tem de ser declarada em db/tests/test_inventario.py, com a "
                "resposta a «guarda dados pessoais?»",
            )
            for coluna, (tipo, anulavel, omissao, _) in colunas.items():
                with self.subTest(coluna=f"servicos.{tabela}.{coluna}"):
                    self.assertEqual(catalogo[tabela][coluna], (tipo, anulavel, omissao))

    def test_o_catalogo_do_idx_e_exactamente_o_inventario(self) -> None:
        """O mesmo trinco, para o esquema `idx` (KAM-061).

        Pela razao do `servicos`: o `test_o_catalogo_e_exactamente_o_inventario`
        filtra `table_schema = 'platform'`, e um esquema novo era invisivel.
        """
        catalogo = self.no_catalogo("idx")
        self.assertEqual(
            set(catalogo), set(INVENTARIO_IDX), "tabelas a mais ou a menos no esquema idx"
        )
        for tabela, colunas in INVENTARIO_IDX.items():
            self.assertEqual(
                set(catalogo[tabela]),
                set(colunas),
                f"colunas de idx.{tabela} diferem do inventario: uma coluna nova "
                "tem de ser declarada em db/tests/test_inventario.py, com a "
                "resposta a «guarda dados pessoais?»",
            )
            for coluna, (tipo, anulavel, omissao, _) in colunas.items():
                with self.subTest(coluna=f"idx.{tabela}.{coluna}"):
                    self.assertEqual(catalogo[tabela][coluna], (tipo, anulavel, omissao))

    def test_toda_a_coluna_tem_a_pergunta_dos_dados_pessoais_respondida(self) -> None:
        for inventario in (INVENTARIO, INVENTARIO_SERVICOS, INVENTARIO_IDX):
            for tabela, colunas in inventario.items():
                for coluna, (_, _, _, pessoal) in colunas.items():
                    with self.subTest(coluna=f"{tabela}.{coluna}"):
                        self.assertTrue(pessoal.strip())

    def test_as_fk_do_servicos_nao_saem_do_esquema_nem_apagam_em_cascata(self) -> None:
        """As tres FK do `servicos` ficam dentro dele, e nenhuma e `CASCADE`.

        **Dentro do esquema**, e isso e uma regra e nao uma coincidencia: o
        `servicos` e acedido so pela TLS, e o `contact_id` entra como referencia
        opaca a `platform.contacts` — do mesmo modo que o `agregado_id` das
        tabelas de eventos. Uma FK para `platform` fazia do `servicos` uma
        extensao daquele esquema e dava ao papel que le a agenda uma razao para
        ter `REFERENCES` nas tabelas de identidade.

        **Nenhuma apaga em cascata** (`a` e `NO ACTION`): apagar um recurso nao
        pode apagar em silencio as marcacoes que alguem tem com ele.

        As duas para `resources` e a uma para `services` sao **compostas com o
        `tenant_id`** — a forma que a `0009` fixou —, e assentam nos indices
        unicos `resources_tenant_uq` e `services_tenant_uq` que a revisao `0025`
        criou precisamente para isto.
        """
        linhas = self.consultar(
            "SELECT conname, confdeltype, confupdtype, "
            "       confrelid::regclass::text AS alvo "
            "  FROM pg_constraint "
            " WHERE contype = 'f' AND connamespace = 'servicos'::regnamespace "
            " ORDER BY conname"
        )
        self.assertEqual(
            linhas,
            [
                ("availability_rules_recurso_fk", "a", "a", "servicos.resources"),
                ("bookings_recurso_fk", "a", "a", "servicos.resources"),
                ("bookings_servico_fk", "a", "a", "servicos.services"),
            ],
        )

    def test_a_restricao_de_exclusao_e_a_do_criterio_1(self) -> None:
        """A barreira do critério 1, lida do catalogo e nao do DDL.

        «1.000 tentativas concorrentes ... produzem **1** marcacao ... garantido
        por restricao de exclusao na BD, nao por codigo aplicacional.» O que esta
        aqui e a definicao que o PostgreSQL guardou, confrontada por extenso: uma
        revisao futura que lhe tirasse o `tenant_id`, que alargasse o predicado,
        ou que a trocasse por um indice unico, falha este teste.

        As tres partes, e o que cada uma impede:

        - `tenant_id WITH =` — sem ele, o recurso de um tenant bloqueava o
          intervalo de outro, e a mensagem de conflito do PostgreSQL (que cita a
          chave) tornava-se um canal de leitura entre vizinhos.
        - `tstzrange(inicio_at, fim_at) WITH &&` — `[)`, pelo que adjacente nao
          sobrepoe e a grelha de horas e possivel.
        - o predicado dos dois estados activos — e o que deixa cancelar sem
          apagar: a linha sai do indice e o intervalo volta a estar livre.
        """
        linhas = self.consultar(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE contype = 'x' AND connamespace = 'servicos'::regnamespace"
        )
        self.assertEqual(
            linhas,
            [
                (
                    "bookings_sem_sobreposicao",
                    "EXCLUDE USING gist (tenant_id WITH =, resource_id WITH =, "
                    "tstzrange(inicio_at, fim_at) WITH &&) WHERE ((estado = ANY "
                    "(ARRAY['hold'::text, 'confirmada'::text])))",
                )
            ],
        )

    def test_os_indices_parciais_do_servicos_sao_os_esperados(self) -> None:
        """O irmao do `test_os_indices_unicos_parciais_sao_os_esperados`, para o `servicos`.

        Aquele filtra `schemaname = 'platform'`, pelo que os indices parciais de
        um esquema novo **nao entram nele** — e o *gate* 8 fica verde sem eles.
        Nao se alarga o dele: as tabelas de `platform` sao de outros tickets e a
        lista e deles.

        **A lista diz tambem se cada um e unico**, e aqui isso vale o que vale no
        outro: um indice parcial unico impoe uma regra de negocio e um parcial
        nao unico e so velocidade. Perder o `UNIQUE` do
        `bookings_contacto_slot_uq` nao muda o plano de nenhuma consulta — nao se
        ve em lado nenhum — e abre a porta a **duas** marcacoes activas do mesmo
        contacto para o mesmo *slot*, que e metade do critério 4.

        A restricao de exclusao **tambem** aparece no `pg_indexes` com um
        `WHERE`, porque e imposta por um indice GiST. Entra na lista; o que
        confronta a definicao dela por extenso e o
        `test_a_restricao_de_exclusao_e_a_do_criterio_1`.
        """
        parciais = {
            # Criterio 4: a idempotencia de `(contact_id, slot_id)`, **unico** e
            # parcial pelos dois estados activos — parcial para que um hold
            # expirado deixe o mesmo contacto voltar a pedir o mesmo *slot*.
            "bookings_contacto_slot_uq": True,
            # A restricao de exclusao do criterio 1, vista como indice.
            "bookings_sem_sobreposicao": False,
            # Velocidade: o calculo da disponibilidade e o varrimento.
            "bookings_recurso_janela_idx": False,
            "bookings_hold_vencido_idx": False,
        }
        linhas = self.consultar(
            "SELECT indexname::text, indexdef FROM pg_indexes "
            "WHERE schemaname = 'servicos' AND indexdef LIKE '%%WHERE%%' ORDER BY 1"
        )
        self.assertEqual(sorted(nome for nome, _ in linhas), sorted(parciais))
        for nome, definicao in linhas:
            with self.subTest(indice=nome):
                self.assertEqual(
                    "UNIQUE INDEX" in definicao,
                    parciais[nome],
                    f"{nome}: a unicidade deixou de ser a declarada",
                )

    def test_a_extensao_btree_gist_vive_no_esquema_servicos(self) -> None:
        """A extensao que a restricao de exclusao precisa, e onde ela esta.

        O ticket manda **validar** que `btree_gist` existe na versao fixada do
        PostgreSQL 18 em vez de assumir. Esta e a validacao, e corre a cada
        *gate* 8: a versao e o esquema lidos do catalogo.

        No `servicos` e nao no `public`, por duas razoes que a revisao escreve:
        o `kamba_migrator` nao tem `CREATE` no `public`, e no `servicos` o
        `DROP EXTENSION` do `downgrade` cai com o resto do esquema em vez de
        deixar uma extensao orfa numa base que desceu.
        """
        linhas = self.consultar(
            "SELECT e.extname, n.nspname, e.extversion "
            "  FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
            " WHERE e.extname = 'btree_gist'"
        )
        self.assertEqual(linhas, [("btree_gist", "servicos", "1.8")])

    def test_as_fk_nao_apagam_em_cascata(self) -> None:
        """Um `ON DELETE CASCADE` transformava apagar um tenant em apagar os canais.

        `a` e `NO ACTION`: apagar um tenant com canais falha, que e o que o
        soft delete do dicionario §2 quer.
        """
        linhas = self.consultar(
            "SELECT conname, confdeltype, confupdtype FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'platform'::regnamespace "
            "ORDER BY conname"
        )
        self.assertEqual(
            sorted(linhas),
            [
                (nome, "a", "a")
                for nome in sorted(
                    [
                        # KAM-070 (0038): **cinco**, duas do pedido e tres do
                        # ledger, e nenhuma apaga em cascata — pela razao geral
                        # e por uma que e deste ticket: apagar um tenant ou um
                        # contacto nao pode apagar a prova de que o apagamento
                        # dele foi pedido e aplicado. E a razao do direito ao
                        # apagamento ao contrario: o que o criterio 6 precisa,
                        # depois de um restauro, e saber **quem** foi apagado.
                        #
                        # As duas que levam o `tenant_id` a frente sao
                        # **compostas**, pela razao das da saida e da midia: um
                        # pedido nao aponta para o contacto de outro tenant, e
                        # uma linha do ledger nao aponta para o pedido de outro.
                        # A `erasure_ledger_dsar_fk` e a que sustenta a
                        # contagem do criterio 3 — sem ela, um escopo aplicava-se
                        # a um `dsar_id` que nao existe e o pedido fechava com
                        # linhas de ninguem.
                        #
                        # **A `tenant_destinations` da `0036` nao deixou nenhuma
                        # nesta lista**, e e a razao por que esta lista nao
                        # aparece na propagacao escrita para aquele ticket: um
                        # destino registra-se antes de o tenant activar e por
                        # isso nao tem FK para `tenants`. Um pedido do titular
                        # tem — nasce no canal de um tenant ja activo —, pelo
                        # que quem seguir a `0036` como modelo nao encontra esta
                        # lista e deixa-a a faltar.
                        # KAM-090 (0040): **uma**, e sem cascata pela razao
                        # inversa da do tenant: uma versao ja aceite nao se
                        # apaga, e e esta FK que o garante tambem ao dono da
                        # tabela, que tem `DELETE` implicito.
                        "contract_acceptance_documento_fk",
                        "dsar_requests_tenant_fk",
                        "dsar_requests_contact_fk",
                        "erasure_ledger_tenant_fk",
                        "erasure_ledger_dsar_fk",
                        "erasure_ledger_contact_fk",
                        # KAM-054 (0032): **dez**, e todas com nome da casa em
                        # vez do `_fkey` que o PostgreSQL geraria. Nenhuma apaga
                        # em cascata, pela razao geral: apagar um tenant nao
                        # apaga o rasto de quem confirmou um pagamento dele, e o
                        # `deleted_at` do dicionario §2 e que faz o *soft
                        # delete*.
                        #
                        # A FK de `refund_cases.order_id` **nao** esta aqui: veio
                        # com a `0035` (KAM-055), ao lado da da
                        # `payment_charges` e pela razao dela.
                        "payment_confirmers_tenant_fk",
                        "payment_confirmers_contact_fk",
                        "manual_confirmations_tenant_fk",
                        "manual_confirmations_charge_fk",
                        "manual_confirmations_actor_fk",
                        # KAM-087 (0043): a verificacao K1 aponta o caso pelo
                        # par `(onboarding_id, tenant_id)`, sem cascata: um
                        # caso nao se apaga com as verificacoes dentro.
                        "kyc_check_caso_fk",
                        # KAM-088 (0044): a decisao de screening aponta o caso
                        # pelo mesmo par, sem cascata: um caso nao se apaga com
                        # as decisoes dentro, que sao *append-only*.
                        "screening_decision_caso_fk",
                        # KAM-089 (0048): o caso de revisao aponta o caso de
                        # onboarding pelo par, e a decisao aponta o caso de
                        # revisao pelo par. Sem cascata: o registo e
                        # *append-only* e nao se apaga com o caso.
                        "review_case_caso_fk",
                        "review_decision_log_case_fk",
                        # KAM-049 (revisao do Catalogo AI): a ingestao aponta o
                        # tenant, sem cascata pela razao geral — apagar um
                        # tenant nao apaga as fotos dele por baixo da retencao,
                        # que e quem as purga (KAM-071).
                        "catalog_ingestions_tenant_fk",
                        # KAM-097 (revisao de T&S): os sinais e as sancoes
                        # apontam o tenant, a sancao humana aponta o caso de
                        # revisao pelo par, e o desfecho de um recurso aponta a
                        # sancao recorrida pelo par. Sem cascata: e tudo
                        # *append-only*.
                        "ts_signal_tenant_fk",
                        "ts_sanction_tenant_fk",
                        "ts_sanction_caso_fk",
                        "ts_sanction_recurso_fk",
                        "refund_cases_tenant_fk",
                        "refund_cases_charge_fk",
                        "fraud_signals_tenant_fk",
                        "fraud_signals_contact_fk",
                        "fraud_signals_charge_fk",
                        # KAM-019: as tres do handoff. A da conversa e
                        # **composta** com o `tenant_id`, pela mesma razao das
                        # da saida; a `handoff_accounts` nao referencia a
                        # `handoffs`, porque uma conta de atendimento existe
                        # antes de haver passagem nenhuma.
                        # KAM-022: as duas da prova de consentimento. A do
                        # contacto e **composta** com o `tenant_id`, pela mesma
                        # razao das da saida e da midia. Nenhuma apaga em
                        # cascata, e aqui isso vale duas vezes: apagar um
                        # contacto nao pode apagar a prova de que ele foi
                        # informado — o direito ao apagamento e o KAM-070 e
                        # tem de decidir isto com um parecer, nao com um
                        # `ON DELETE CASCADE` escrito de passagem.
                        "consent_event_tenant_fk",
                        "consent_event_contact_fk",
                        # KAM-043: as **tres** da revisao `0028`. A do
                        # contacto da cotacao e **composta** com o
                        # `tenant_id`, pela correccao de 2026-10-27 do
                        # `docs/tecnica/03` secao 5.4 — que nomeia esta
                        # tabela por escrito — e pelo ISO-58 do spike
                        # KAM-041, que mediu o que a FK simples permite:
                        # uma cotacao de A a apontar para um contacto de B.
                        # Nenhuma apaga em cascata, e na `offer_terms` isso
                        # vale duas vezes: apagar um tenant nao pode apagar
                        # o catalogo dele em silencio, porque a retencao e
                        # explicita (KAM-071) e o soft delete da tabela e o
                        # `deleted_at` do secao 5.6.
                        "offer_terms_tenant_fk",
                        "price_quotes_tenant_fk",
                        "price_quotes_contacto_do_mesmo_tenant_fk",
                        # KAM-044: as **sete** das encomendas, e quatro delas
                        # compostas com o `tenant_id` — a correccao de
                        # 2026-10-27 do secao 5.4, que nomeia este ticket. As
                        # tres para `orders_mirror` assentam na
                        # `orders_mirror_tenant_id_uq`, que a revisao `0030`
                        # acrescenta so para isso.
                        #
                        # **Nenhuma apaga em cascata, e aqui isso vale mais do
                        # que em qualquer outra tabela**: um `ON DELETE CASCADE`
                        # no `order_state_log` fazia apagar uma encomenda apagar
                        # a prova de que ela foi paga por evento autenticado — o
                        # `deny_mutation` recusa o `DELETE` directo, e uma
                        # cascata nao e um `DELETE` que ele veja. Apagar uma
                        # encomenda e escrever `deleted_at` (secao 5.6), e a
                        # purga fisica e da retencao (KAM-071).
                        "order_intents_encomenda_do_mesmo_tenant_fk",
                        "order_intents_tenant_fk",
                        "order_reconciliation_issues_encomenda_do_mesmo_tenant_fk",
                        "order_reconciliation_issues_tenant_fk",
                        "order_state_log_encomenda_do_mesmo_tenant_fk",
                        "orders_mirror_contacto_do_mesmo_tenant_fk",
                        "orders_mirror_tenant_fk",
                        # KAM-045 (0033): as duas da reserva de stock. A da
                        # encomenda e **composta** `(tenant_id, order_id)`,
                        # pela licao ISO-58 do spike KAM-041 — uma FK simples
                        # deixava a reserva de A apontar para a encomenda de B.
                        # Nenhuma apaga em cascata, como todas as outras.
                        "stock_reservations_encomenda_do_mesmo_tenant_fk",
                        "stock_reservations_tenant_fk",
                        # KAM-016: as duas da tentativa de onboarding. A do
                        # canal e **composta** com o `tenant_id`, pela razao que
                        # a `0009` fixou e as cinco revisoes seguintes
                        # repetiram, e assenta na `tenant_channels_tenant_id_uq`
                        # que aquela revisao acrescentou precisamente para isto.
                        # Sem `ON DELETE CASCADE`, como todas: apagar um canal
                        # nao pode apagar o registo das tentativas que o
                        # criaram — e a compensacao do criterio 7 **apaga** o
                        # canal, o que faz a FK recusar e obriga a por o
                        # `channel_id` a `NULL` primeiro, que e o que o
                        # `SQL_LIMPAR_RECURSOS` faz.
                        "channel_onboarding_tenant_fk",
                        "channel_onboarding_channel_fk",
                        # KAM-017: as **duas** da coexistencia, e a do canal e
                        # composta com o `tenant_id` pela mesma razao da linha
                        # acima. Sem `ON DELETE CASCADE`, como todas: apagar um
                        # canal nao pode apagar em silencio o estado da
                        # sincronizacao dele — que e o unico sitio onde se le
                        # porque e que ele se desligou.
                        "channel_coexistence_tenant_fk",
                        "channel_coexistence_channel_fk",
                        # KAM-115: **uma** de cada tabela do aviso ao dono, as
                        # duas para `tenants` e nenhuma para `tenant_channels`.
                        # Uma e nao duas, e a razao e o que o ticket e: o aviso e
                        # do **dono** e nao do canal, e o canal, quando faz parte
                        # da historia, vai dentro do `episodio`. E nenhuma
                        # referencia a outra: o contacto existe sem aviso e o
                        # aviso sai sem contacto (pelo painel), e uma FK entre
                        # elas tornava impossivel o caso que o criterio 6 manda
                        # tratar. Sem `ON DELETE CASCADE`, como todas: apagar um
                        # tenant nao pode apagar em silencio a prova de que ele
                        # foi avisado.
                        "owner_contacts_tenant_fk",
                        "owner_notices_tenant_fk",
                        # KAM-114: a unica FK da `draft_decisions`, e **nao**
                        # composta — ela nao referencia conversa nenhuma. O
                        # vinculo ao contacto e o `thread_id`, que e texto
                        # derivado (§3.1) e nao uma FK, pela mesma razao que o
                        # `handoff_id` do §3.15 e irreversivel. `NO ACTION`,
                        # como todas: apagar um tenant com decisoes falha, que
                        # e o que o soft delete do §2 quer.
                        "draft_decisions_tenant_fk",
                        # KAM-052: a **unica** FK da `payment_accounts`, e e por
                        # desenho — o `docs/tecnica/04` secao 6 escreve que ela
                        # «so referencia `tenants`», e que as FK para
                        # `orders_mirror` sao do KAM-055 e a de `billing_cycles`
                        # do KAM-059. **Simples e nao composta**, porque o
                        # `tenant_id` e anulavel aqui e uma FK composta nao tem
                        # segunda coluna para levar. `NO ACTION`, como todas:
                        # apagar um tenant com contas de pagamento falha, e e o
                        # que se quer — a conta diz para onde foi o dinheiro de
                        # uma venda, e isso e prova.
                        "payment_accounts_tenant_fk",
                        # KAM-053: as **seis** da revisao `0029`, e sao seis e
                        # nao oito porque duas nao nascem com ela — a de
                        # `order_id` para `orders_mirror` chegou com a `0035`
                        # (KAM-055) e esta no bloco de baixo; a de
                        # `billing_cycle_id` para `billing_cycles` e do
                        # **KAM-059** e a tabela ainda nao existe (o `CHECK` de
                        # exclusividade entre os dois sujeitos fica na `0029`,
                        # porque nao depende de tabela nenhuma).
                        #
                        # **Nenhuma e composta com o `tenant_id`**, e nas
                        # tres que apontam para a `payment_accounts` isso nao e
                        # uma falta mas uma impossibilidade: o `tenant_id` dela
                        # e **anulavel** (a conta propria da KAMBA), pelo que
                        # nao existe a unicidade `(id, tenant_id)` sobre que uma
                        # FK composta assentasse. O que prende o beneficiario ao
                        # tenant da cobranca e o *trigger* `assert_beneficiary`
                        # (a guarda G-1 do secao 10.4), que compara os dois e
                        # recusa com `check_violation` — e e ligado **nesta**
                        # revisao, nao no KAM-055: a `payment_charges` nasce
                        # aqui, e deixar uma tabela de dinheiro dois tickets
                        # sem a G-1 era tirar uma barreira que ja existe.
                        #
                        # A `payment_events_charge_fk` liga duas tabelas que
                        # **a mesma revisao** cria — como a
                        # `contact_endpoints_dek_fk` da `0003` —, e e a
                        # primeira a fazer isso entre uma tabela mutavel e uma
                        # *append-only*.
                        # `NO ACTION`, como todas, e aqui isso vale mais do que
                        # em qualquer outra linha desta lista: um
                        # `ON DELETE CASCADE` da cobranca para o ledger fazia de
                        # um `DELETE` numa tabela mutavel o apagamento de prova
                        # *append-only* — o `deny_mutation` recusa o `DELETE`
                        # directo, e uma cascata entrava por uma porta que ele
                        # nao guarda.
                        "payment_charges_tenant_fk",
                        "payment_charges_account_fk",
                        "payment_callbacks_inbox_account_fk",
                        "payment_events_tenant_fk",
                        "payment_events_charge_fk",
                        "payment_events_account_fk",
                        # KAM-055: as **tres** da revisao `0035`, e sao as que o
                        # bloco acima e o da `0032` deixaram escritas com este
                        # ticket por credor. Todas `(tenant_id, order_id) ->
                        # orders_mirror (tenant_id, id)`, contra a
                        # `orders_mirror_tenant_id_uq` — isto e, **compostas**,
                        # ao contrario das seis de cima, e aqui isso e possivel
                        # porque o `tenant_id` da `orders_mirror` e `NOT NULL`.
                        #
                        # `MATCH SIMPLE` (a omissao) e o que deixa a coluna
                        # anulavel continuar a servir: uma cobranca de ciclo de
                        # billing tem `order_id` nulo — o
                        # `payment_charges_um_sujeito` exige exactamente um dos
                        # dois sujeitos — e com um nulo no par a restricao esta
                        # satisfeita. Com `MATCH FULL` a facturacao da propria
                        # KAMBA do secao 11.2 ficava sem caminho de escrita.
                        #
                        # A da `payment_events` e a que custa: o ledger e
                        # *append-only*, pelo que ela torna uma encomenda com
                        # eventos impossivel de apagar. E o que se quer em
                        # producao (uma encomenda marca-se, nao se apaga) e e o
                        # que a limpeza de `db/tests_pagamentos/base.py` passa a
                        # respeitar, pela forma que o KAM-044 ja usava para o
                        # `order_state_log`.
                        "payment_charges_encomenda_do_mesmo_tenant_fk",
                        "payment_events_encomenda_do_mesmo_tenant_fk",
                        "refund_cases_encomenda_do_mesmo_tenant_fk",
                        "handoffs_tenant_fk",
                        "handoffs_conversation_fk",
                        "handoff_accounts_tenant_fk",
                        # KAM-020: as **tres** da midia. Duas sao compostas com o `tenant_id`
                        # (contacto e conversa), pela razao de sempre; e as tres
                        # existem porque uma linha desta tabela so faz sentido
                        # dentro de uma conversa de um contacto de uma PME.
                        # Sem `ON DELETE CASCADE`, como todas — e aqui a razao
                        # e mais forte: apagar uma conversa em cascata levaria
                        # o registo do objecto e **deixaria o blob** no
                        # armazenamento, lixo que a purga do KAM-071 nao ve
                        # porque ela le esta tabela.
                        # KAM-021: as duas da qualidade. A do canal e
                        # **composta com o `tenant_id`**, pela razao que a
                        # `0009` fixou: sem ele, uma transicao de A podia
                        # apontar para um canal de B.
                        "channel_quality_log_tenant_fk",
                        "channel_quality_log_channel_fk",
                        "media_assets_tenant_fk",
                        "media_assets_contact_fk",
                        "media_assets_conversation_fk",
                                    # KAM-015: as quatro da saida. Tres sao compostas
                        # com o `tenant_id` — contacto, canal e conversa —
                        # porque sem elas uma mensagem do tenant A podia
                        # apontar para um objecto de B, e nem o gate 6 nem o 3b
                        # o veriam. Sem `ON DELETE CASCADE`, como todas: o §2
                        # manda soft delete, e quem purga e o `kamba_batch`.
                        "message_templates_tenant_fk",
                        "outbound_messages_channel_fk",
                        "outbound_messages_contact_fk",
                        "outbound_messages_conversation_fk",
                        "outbound_messages_tenant_fk",
                        "contact_deks_contact_fk",
                        "contact_deks_tenant_fk",
                        "contact_endpoints_contact_fk",
                        "contact_endpoints_dek_fk",
                        "contact_endpoints_hmac_kid_fk",
                        "contact_endpoints_tenant_fk",
                        "contacts_hmac_kid_fk",
                        "contacts_merged_fk",
                        "contacts_tenant_fk",
                        "entitlements_tenant_fk",
                        # KAM-006: as aprovacoes apontam para a entrada da DLQ.
                        # Sem `ON DELETE CASCADE`, como todas as outras: quem
                        # apaga a entrada apaga as aprovacoes primeiro, por
                        # extenso (`evt_limpar_dlq`).
                        "evt_dlq_aprovacoes_dlq_fk",
                        "tenant_channels_tenant_fk",
                        # KAM-009: as duas tabelas de uso. Sem `ON DELETE
                        # CASCADE`, como todas as outras — apagar um tenant
                        # nao apaga o registo do que ele consumiu.
                        "tenant_usage_tenant_fk",
                        "tenants_owner_fk",
                        "usage_ledger_tenant_fk",
                        # KAM-014: as tres da conversa. Duas sao **compostas
                        # com o `tenant_id`** — uma conversa nao aponta para um
                        # contacto nem para um canal de outro tenant, e e a
                        # base que o diz. A do canal e a razao por que a `0009`
                        # acrescenta `tenant_channels_tenant_id_uq`: sem ela
                        # nao havia chave sobre que assentar.
                        "conversations_channel_fk",
                        "conversations_contact_fk",
                        "conversations_tenant_fk",
                    ]
                )
            ],
        )

    def test_a_fk_do_dono_e_a_unica_diferida(self) -> None:
        """`tenants_owner_fk` e `DEFERRABLE INITIALLY DEFERRED`; as outras nao.

        O tenant e o seu primeiro contacto nascem na mesma transaccao e
        referem-se um ao outro. Uma FK diferida a mais adiava para o `COMMIT`
        um erro que tem de aparecer na instrucao que o causa.
        """
        linhas = self.consultar(
            "SELECT conname::text FROM pg_constraint "
            "WHERE contype = 'f' AND connamespace = 'platform'::regnamespace "
            "AND (condeferrable OR condeferred)"
        )
        self.assertEqual(linhas, [("tenants_owner_fk",)])
        self.assertEqual(
            self.consultar(
                "SELECT condeferrable, condeferred FROM pg_constraint "
                "WHERE conname = 'tenants_owner_fk'"
            ),
            [(True, True)],
        )

    def test_os_indices_unicos_parciais_sao_os_esperados(self) -> None:
        """Nao sao restricoes no catalogo; sem lista, um que desaparecesse passava.

        A lista diz tambem se cada um e **unico**, e isso nao e detalhe: um
        indice parcial unico impoe uma regra de negocio (um telefone por
        contacto e finalidade, uma versao actual de chave), e um parcial nao
        unico e so velocidade. Perder o `UNIQUE` de um dos primeiros nao muda o
        plano de nenhuma consulta — nao se ve em lado nenhum — e abre a porta a
        duas linhas onde devia haver uma.
        """
        parciais = {
            "contact_endpoints_telefone_uq": True,
            "contacts_phone_hmac_uq": True,
            "hmac_key_versions_actual_uq": True,
            "hmac_key_versions_anterior_uq": True,
            "tenants_nif_uq": True,
            # KAM-005: parcial e **nao** unico. E o indice que o publicador
            # varre (`docs/tecnica/06` §6.1), e so cobre o que falta publicar:
            # depois de publicada, a linha sai do indice e o varrimento nao
            # cresce com o arquivo.
            "events_outbox_pendentes": False,
            # KAM-006: parcial e **nao** unico, pela mesma ideia. E o indice do
            # alerta e da metrica `evt_dlq_open`: so cobre o que esta aberto, e
            # uma DLQ saudavel tem zero linhas aqui.
            "events_dlq_abertas": False,
            # KAM-114: os dois da `draft_decisions`, parciais e **nao** unicos.
            # Cobrem so o que esta `pendente` (`decisao IS NULL`), que e a mesma
            # ideia dos dois acima: depois de decidido, o rascunho sai do indice
            # e nenhuma das duas varreduras cresce com o historico. Um indice
            # total crescia com as decididas para sempre.
            "draft_decisions_pendentes_idx": False,
            # KAM-052: parcial e **unico**, e e o criterio 4 do ticket. Impede
            # duas contas a ocupar o par `(tenant_id, provider)`, e o predicado
            # sao **dois** estados e nao um: uma conta em `teste_sandbox_ok` ja
            # reserva o facilitador, para que ninguem comece uma segunda
            # integracao enquanto a primeira esta a ser testada. Depois de
            # `revogado` o par fica livre — e tem de ficar, senao uma PME que
            # trocou de facilitador e quer voltar nao podia.
            #
            # **Nao limita a KAMBA a uma conta propria por `provider`**: o
            # `tenant_id` dela e nulo, e um indice unico do PostgreSQL nao
            # considera dois NULL iguais. E o comportamento certo, e fica dito
            # para nao parecer descuido.
            "payment_accounts_um_ativo": True,
            # KAM-043: os dois da revisao `0028`, parciais e **nao** unicos.
            # O `offer_terms_tenant_estado_idx` cobre so o que nao esta
            # apagado (`deleted_at IS NULL`), que e a leitura do catalogo; o
            # `price_quotes_vivas_idx` cobre so o que esta `emitida`, que e a
            # pergunta do `getValidQuote` — depois de aceite, expirada ou
            # revogada a cotacao sai do indice e ele nao cresce com o
            # historico. **Nao unicos, e nenhum devia ser:** um tenant tem
            # muitos SKU publicados, e um dono pode cotar o mesmo `(sku, qty)`
            # duas vezes — vale a ultima, e e o `ORDER BY criado_at DESC` da
            # consulta que o decide, nao um indice unico que recusava a
            # segunda cotacao.
            "offer_terms_tenant_estado_idx": False,
            "price_quotes_vivas_idx": False,
            # KAM-053: os **quatro** parciais da revisao `0029`, e tres deles
            # sao unicos — o que faz desta a revisao que acrescenta mais regras
            # de negocio por indice parcial.
            #
            # `payment_charges_ref_uq`: o criterio 4 do secao 6.2. O par
            # `(account_id, referencia)` e unico **com a conta**, e nao sem ela:
            # uma referencia Multicaixa e Entidade + Referencia, e duas PMEs
            # podem ter o mesmo numero (`evidencia/E2` secao 2). Parcial em
            # `referencia IS NOT NULL` porque um `express_push` nao tem
            # referencia, e um indice total recusava a segunda cobranca sem ela.
            #
            # `payment_charges_activa_uq`: uma cobranca activa por sujeito. O
            # predicado sao **quatro** estados, e depois de um terminal o par
            # liberta-se — e **tem** de libertar-se, senao o `tentativa + 1` do
            # F-06 nao podia existir. Perder o `UNIQUE` aqui dava duas cobrancas
            # a correr para a mesma encomenda, que e o cliente a pagar duas
            # vezes: e o caso em que a perda do `UNIQUE` num parcial custa
            # dinheiro, e e por isso que esta lista diz se cada um e unico.
            #
            # `payment_events_entrega_uq`: a deduplicacao de entregas (G7), e
            # **com o tipo de evento no predicado**, que e o secao 6.2 a letra.
            # Nao e global por uma razao medida: o mesmo `provider_event_id`
            # aparece num `pagamento_confirmado` que decorre do
            # `pagamento_recebido` que o trouxe, e um indice sobre todos os
            # tipos recusava a decisao por causa do facto.
            #
            # `payment_callbacks_inbox_pendentes`: parcial e **nao** unico, pela
            # ideia do `events_outbox_pendentes` — cobre so o que falta
            # processar, e o varrimento do *worker* nao cresce com o arquivo das
            # entregas ja tratadas.
            "payment_charges_ref_uq": True,
            "payment_charges_activa_uq": True,
            "payment_events_entrega_uq": True,
            "payment_callbacks_inbox_pendentes": False,
            "draft_decisions_thread_idx": False,
            # KAM-006: parcial e **unico**, e e o unico desta revisao. Impoe a
            # reentrada idempotente **entre as abertas**: o mesmo evento a
            # falhar outra vez nao abre uma segunda entrada aberta, mas um
            # ciclo novo depois de uma resolucao abre a sua. Perder o `UNIQUE`
            # daqui nao muda plano de consulta nenhum — nao se ve em lado
            # nenhum — e dava duas entradas abertas sobre o mesmo evento, com o
            # alerta a contar o dobro.
            "events_dlq_aberta_uq": True,
            # KAM-045: parcial e **nao** unico. E o indice do varrimento da
            # expiracao, e so cobre `estado = 'ativa'`: uma reserva `consumida`
            # ou `libertada` nunca volta a ser varrida, e deixa-las no indice
            # fazia-o crescer para sempre sobre linhas que ninguem consulta. Nao
            # impoe regra nenhuma — e so velocidade —, pelo que o `False` aqui e
            # a afirmacao certa e nao uma omissao.
            "stock_reservations_expira_idx": False,
            # KAM-050 (0046): parcial e **unico**. Substitui a
            # `stock_reservations_linha_uq` da `0033`, que era total: com ela, a
            # linha de uma encomenda `expirada` nao se re-reservava (regra 1 do
            # `docs/tecnica/03` §6.6). Uma reserva **viva** por linha continua a
            # ser regra; uma libertada deixa de contar.
            "stock_reservations_linha_viva_uq": True,
            # KAM-089: o dos casos de um onboarding, parcial e **nao** unico.
            # Cobre so os casos com onboarding, que sao os que a quota e o
            # desbloqueio perguntam; um caso de saga ou de *trust* nao entra.
            "review_case_onboarding_idx": False,
            # KAM-049 (revisao do Catalogo AI): os dois da ingestao, parciais e
            # **nao** unicos. O do `phash` cobre so as fotos ja medidas, que sao
            # as que a pergunta «e o mesmo produto?» compara; o da fila cobre so
            # as duas paragens humanas (`bloqueada_gate`, `bloqueada_categoria`),
            # e uma plataforma saudavel tem poucas linhas nele. A unicidade da
            # reentrega e a restricao `catalog_ingestions_media_uq`, nao um
            # indice parcial.
            "catalog_ingestions_fila_idx": False,
            "catalog_ingestions_phash_idx": False,
            # KAM-115: os dois do aviso ao dono, e os dois parciais e **nao**
            # unicos. O do contacto cobre so os enderecos utilizaveis
            # (verificados e nao invalidos), que e o conjunto que a entrega le;
            # o dos avisos cobre so o que ainda nao foi entregue, que e o
            # conjunto que as varreduras dos lembretes e dos pendentes leem. Nos
            # dois, o indice cheio seria quase todo entradas que a consulta nao
            # quer — e uma plataforma saudavel tem poucas linhas no segundo.
            #
            # **Nao unicos, e isso e desenho e nao esquecimento**: a unicidade
            # destas tabelas e de restricao e nao de indice parcial — a
            # `owner_contacts_canal_uq` e a `owner_notices_idempotencia_uq` —, e
            # um parcial unico aqui diria uma regra diferente: «um contacto
            # verificado por canal» ja e dito pela restricao, e «um aviso
            # pendente por episodio» era falso, porque um episodio tem um aviso
            # por canal.
            "owner_contacts_verificado_idx": False,
            "owner_notices_pendentes_idx": False,
            # KAM-044: **um** parcial na revisao `0030`, e nao e unico. O
            # `orders_mirror_expira_idx` cobre so os dois estados que expiram
            # (`aguarda_pagamento`, `pendente_confirmacao`), que e a mesma ideia
            # do `events_outbox_pendentes`: depois de paga, expirada ou
            # cancelada a encomenda sai do indice e o varrimento da expiracao
            # (KAM-045) nao cresce com o historico.
            #
            # **Nao comeca pelo `tenant_id`, e nao deve**: esse varrimento corre
            # como `kamba_batch` sobre a base toda e procura por instante. O
            # indice que serve o tenant e o `orders_mirror_estado_idx`, que nao
            # e parcial e por isso nao esta nesta lista.
            #
            # Nao unico, e seria errado se o fosse: duas encomendas do mesmo
            # tenant expiram no mesmo instante sempre que a mesma cobranca
            # define a validade das duas.
            "orders_mirror_expira_idx": False,
            # KAM-069 (0036): as linhas **globais** dos destinos de
            # transferencia, que sao as da infra-estrutura — o `tenant_id` nulo.
            #
            # **Parcial de proposito, e e o segundo acesso da tabela.** A
            # unicidade `(tenant_id, provider, country, purpose)` serve o
            # primeiro (as linhas de um tenant) porque principia pelo
            # `tenant_id`; as globais nao, porque um `IS NULL` sobre a primeira
            # coluna de um indice de quatro varre-o todo. A porta le as globais
            # em **todas** as consultas, pela precedencia do `porta.py`.
            #
            # **Nao comeca pelo `tenant_id`, e nao pode**: o predicado e
            # `tenant_id IS NULL`, pelo que a coluna nao discrimina nada dentro
            # do indice. O que o X-05 exige — `tenant_id` a cabeca de **algum**
            # indice — e satisfeito pela unicidade.
            #
            # Nao unico, e seria errado se o fosse: a unicidade das globais e a
            # restricao `UNIQUE NULLS NOT DISTINCT`, que leva o `country`; este
            # indice nao o leva, e unico recusaria dois paises para o mesmo
            # fornecedor e finalidade — que e exactamente a configuracao que o
            # passo 4 da porta existe para tratar.
            "tenant_destinations_globais_idx": False,
            # KAM-070 (0038): os **dois** da `dsar_requests`, e um e unico e o
            # outro nao. O `erasure_ledger_contacto_idx` nao esta nesta lista
            # porque nao e parcial: o ledger nao tem estado a excluir — uma
            # linha dele e um apagamento que aconteceu, e nenhuma sai do
            # conjunto que se le.
            #
            # `dsar_requests_aberto_uq`: a idempotencia do criterio 8, e **o
            # predicado e a regra**. Dois pedidos do mesmo tipo pelo mesmo
            # titular sao legitimos ao longo do tempo — um apagamento em Marco
            # e outro em Setembro, depois de o BSUID voltar a escrever; o que
            # nao e legitimo e **dois ao mesmo tempo**, que e o que duplica
            # *jobs*. Perder o `UNIQUE` daqui nao muda plano de consulta nenhum
            # e deixava dois pedidos abertos a correr para o mesmo titular, com
            # dois apagamentos a aplicar os mesmos seis escopos; perder o
            # **predicado** fazia o contrario — recusava o pedido legitimo de
            # Setembro porque o de Marco existiu. E por isso que esta lista diz
            # as duas coisas de cada indice.
            #
            # `dsar_requests_prazo_idx`: o varrimento do prazo (criterio 8, o
            # alerta aos 20 dias) le os abertos ordenados pelo prazo. Parcial
            # pela ideia do `events_outbox_pendentes` — um pedido concluido nao
            # tem prazo a vencer — e **nao** unico, e seria errado se o fosse:
            # dois pedidos do mesmo tenant vencem no mesmo instante sempre que
            # chegaram no mesmo.
            "dsar_requests_aberto_uq": True,
            "dsar_requests_prazo_idx": False,
            # KAM-087: o NIF de um caso **vivo** e unico (o indice do bloco do
            # KAM-086). Unico e parcial: um caso rejeitado deixa o NIF voltar.
            "onboarding_nif_vivo": True,
            # KAM-197: o pedido que abriu um caso de reembolso abre-o **uma**
            # vez. Unico, e e a idempotencia do criterio 1 imposta pela base;
            # parcial porque os casos da `manual_reverter` nao vem de pedido
            # nenhum. Perder o `UNIQUE` dava dois casos para o mesmo pedido.
            "refund_cases_pedido_uq": True,
        }
        linhas = self.consultar(
            "SELECT indexname::text, indexdef FROM pg_indexes "
            "WHERE schemaname = 'platform' AND indexdef LIKE '%%WHERE%%' ORDER BY 1"
        )
        self.assertEqual(sorted(nome for nome, _ in linhas), sorted(parciais))
        for nome, definicao in linhas:
            with self.subTest(indice=nome):
                self.assertEqual(
                    definicao.startswith("CREATE UNIQUE INDEX"), parciais[nome]
                )

    def test_as_restricoes_sao_as_esperadas(self) -> None:
        """Lista fechada de CHECK, UNIQUE e PK: uma que desapareca nao passa calada."""
        linhas = self.consultar(
            "SELECT conname FROM pg_constraint "
            "WHERE connamespace = 'platform'::regnamespace AND contype IN ('c', 'u', 'p') "
            "ORDER BY conname"
        )
        self.assertEqual(
            sorted(nome for (nome,) in linhas),
            sorted(
                [
                    # --------------------------------------- KAM-090 (0040)
                    #
                    # **Treze: nove da versao publicada e quatro da prova.** Na
                    # versao, o `sha256_ck` e o `canonico_ck` sao os que fazem o
                    # criterio 1 ser da base («`sha256` do conteudo canonico»),
                    # o `sem_retroactivo_ck` impede uma versao de ter vigorado
                    # antes de existir, e o `citavel_uq` existe para a FK
                    # composta da prova. Na prova, o `evidencia_ck` prende a
                    # formula do criterio 3 a quem escreva sem o *trigger*. O
                    # `EXCLUDE` do OTP nao entra: e `contype = 'x'`.
                    # --------------------------------------- KAM-071 (0042)
                    #
                    # **Onze.** Os tres dominios fechados (`modo`, `resultado`,
                    # `motivo`), as duas formas de nome (`classe`, `tabela`), as
                    # tres contagens e a versao, e os dois que ligam colunas: um
                    # `ok` nao tem motivo e tudo o resto tem, e so um `ok`
                    # apagou alguma coisa.
                    # --------------------------------------- KAM-087 (0043)
                    #
                    # O caso: os dominios da `fase`, da `origem` e das
                    # `flags`, as formas dos dois HMAC e do `preflight`, o
                    # contador, e as duas unicidades (o tenant pre-alocado e
                    # o par que a FK do `kyc_check` aponta).
                    "onboarding_case_fase_ck",
                    "onboarding_case_flags_ck",
                    "onboarding_case_id_tenant_uq",
                    "onboarding_case_nif_hmac_ck",
                    "onboarding_case_origem_ck",
                    "onboarding_case_owner_active_seconds_ck",
                    "onboarding_case_phone_hmac_ck",
                    "onboarding_case_pkey",
                    "onboarding_case_preflight_ck",
                    "onboarding_case_tenant_uq",
                    # A verificacao: os tres dominios, as formas, o
                    # prefixo do STO e a idempotencia por `sha256`.
                    "kyc_check_custo_micro_usd_ck",
                    "kyc_check_doc_ref_ck",
                    "kyc_check_doc_tipo_ck",
                    "kyc_check_documento_uq",
                    "kyc_check_flags_ck",
                    "kyc_check_phash_ck",
                    "kyc_check_pkey",
                    "kyc_check_resultado_ck",
                    "kyc_check_score_ck",
                    "kyc_check_sha256_ck",
                    "kyc_check_versao_regras_ck",
                    # --------------------------------------- KAM-088 (0044)
                    #
                    # **Sete.** Os tres dominios fechados (`decisao`,
                    # `origem`, `sujeito_tipo`), a referencia nao vazia, a
                    # versao SemVer com o metadado do motor (`+m.N`), o
                    # resumo de 32 octetos e a chave primaria.
                    "screening_decision_conteudo_sha256_ck",
                    "screening_decision_decisao_ck",
                    "screening_decision_origem_ck",
                    "screening_decision_pkey",
                    "screening_decision_sujeito_ref_ck",
                    "screening_decision_sujeito_tipo_ck",
                    "screening_decision_versao_politica_ck",
                    # --------------------------------------- KAM-089 (0048)
                    #
                    # **Dezassete.** No caso: os cinco dominios fechados
                    # (`tipo`, `estado`, `motivo_publico`, `recomendacao`,
                    # `prioridade`), a forma do `motivo_codigo`, o tamanho do
                    # interno, as evidencias em lista, a ordem do prazo, a
                    # chave de abertura, a unicidade composta da FK da decisao
                    # e a chave primaria. Na decisao: os dois dominios, a
                    # regra, o recurso so de aprovar ou rejeitar e a chave.
                    "review_case_abertura_uq",
                    "review_case_estado_ck",
                    "review_case_evidencias_ck",
                    "review_case_id_tenant_uq",
                    "review_case_motivo_codigo_ck",
                    "review_case_motivo_interno_ck",
                    "review_case_motivo_publico_ck",
                    "review_case_pkey",
                    "review_case_prioridade_ck",
                    "review_case_recomendacao_ck",
                    "review_case_sla_ck",
                    "review_case_tipo_ck",
                    "review_decision_log_decisao_ck",
                    "review_decision_log_instancia_ck",
                    "review_decision_log_pkey",
                    "review_decision_log_recurso_ck",
                    "review_decision_log_regra_ck",
                    # ------------------------- KAM-097 (revisao de T&S)
                    #
                    # **Vinte e quatro.** No sinal: o tipo, o dominio e o par
                    # tipo/severidade (a severidade fixa), o `detalhe` fechado a
                    # chaves de referencia, a chave do bloco, a unicidade
                    # composta das FK e a chave primaria. Na sancao: os
                    # dominios (passo, origem, motivo publico, desfecho), as
                    # formas (chave, autor, motivo interno, regra, sinais,
                    # justificacao), as quatro coerencias (a chave e o autor presos a
                    # origem, grave so humana, humana
                    # com caso, recurso humano e com desfecho), a chave, a
                    # unicidade composta e a chave primaria.
                    "ts_signal_chave_uq",
                    "ts_signal_detalhe_ck",
                    "ts_signal_id_tenant_uq",
                    "ts_signal_pkey",
                    "ts_signal_severidade_ck",
                    "ts_signal_severidade_dominio_ck",
                    "ts_signal_tipo_ck",
                    "ts_sanction_autor_ck",
                    "ts_sanction_chave_ck",
                    "ts_sanction_chave_forma_ck",
                    "ts_sanction_chave_uq",
                    "ts_sanction_grave_humana_ck",
                    "ts_sanction_humana_com_caso_ck",
                    "ts_sanction_id_tenant_uq",
                    "ts_sanction_justificacao_ck",
                    "ts_sanction_motivo_interno_ck",
                    "ts_sanction_motivo_publico_ck",
                    "ts_sanction_origem_ck",
                    "ts_sanction_passo_ck",
                    "ts_sanction_pkey",
                    "ts_sanction_recurso_ck",
                    "ts_sanction_recurso_estado_ck",
                    "ts_sanction_regra_ck",
                    "ts_sanction_sinais_ck",
                    # ------------------- KAM-049 (revisao do Catalogo AI)
                    #
                    # **Catorze.** Os nove de coluna (o dominio do `estado`, a
                    # forma do `media_id_meta`, do `phash`, do `extraido`, da
                    # `categoria_restrita`, do `sku` e do `confirmado_por`, as
                    # perguntas entre zero e doze e o custo nao negativo), os
                    # tres de linha — a `media_ref` presa ao tenant da linha, a
                    # `bloqueada_categoria` com categoria e a `publicada` com
                    # SKU, sem categoria e com quem confirmou e quando —, a
                    # unicidade da reentrega e a chave primaria.
                    "catalog_ingestions_bloqueada_ck",
                    "catalog_ingestions_categoria_ck",
                    "catalog_ingestions_confirmado_por_ck",
                    "catalog_ingestions_custo_ck",
                    "catalog_ingestions_estado_ck",
                    "catalog_ingestions_extraido_ck",
                    "catalog_ingestions_media_id_ck",
                    "catalog_ingestions_media_ref_ck",
                    "catalog_ingestions_media_uq",
                    "catalog_ingestions_perguntas_ck",
                    "catalog_ingestions_phash_ck",
                    "catalog_ingestions_pkey",
                    "catalog_ingestions_publicada_ck",
                    "catalog_ingestions_sku_ck",
                    "catalog_ingestions_ultima_mensagem_ck",
                    "purge_log_classe_ck",
                    "purge_log_linhas_ck",
                    "purge_log_modo_ck",
                    "purge_log_motivo_ck",
                    "purge_log_motivo_par_ck",
                    "purge_log_objectos_ck",
                    "purge_log_pkey",
                    "purge_log_politica_versao_ck",
                    "purge_log_resultado_ck",
                    "purge_log_so_ok_apaga_ck",
                    "purge_log_tabela_ck",
                    "contract_acceptance_aceite_uq",
                    "contract_acceptance_evidencia_ck",
                    "contract_acceptance_ip_prefix_hash_ck",
                    "contract_acceptance_pkey",
                    "contract_document_canonico_ck",
                    "contract_document_citavel_uq",
                    "contract_document_pkey",
                    "contract_document_sem_retroactivo_ck",
                    "contract_document_sha256_ck",
                    "contract_document_tipo_ck",
                    "contract_document_versao_ck",
                    "contract_document_versao_uq",
                    "contract_document_vigencia_uq",
                    # --------------------------------------- KAM-070 (0038)
                    #
                    # **Doze: nove do pedido e tres do ledger.** No pedido sao a
                    # chave primaria, a unicidade composta e sete `CHECK` — tres
                    # de dominio fechado (`tipo`, `estado`, `papel_kamba`), um de
                    # intervalo (`prazo_dias`) e tres que **ligam colunas**, que
                    # sao os que fazem a tabela nao poder contradizer-se:
                    #
                    #   dsar_requests_prazo_ordenado_ck  o prazo interno e
                    #     **depois** da recepcao. E o que fica na base do
                    #     `prazo_interno_at = recebido_at + 30 d` do criterio 1:
                    #     a soma nao e verificavel aqui (`timestamptz +
                    #     interval` e `STABLE`, le o `TimeZone` da sessao), a
                    #     ordenacao e. Sem ele, um prazo **anterior** a recepcao
                    #     passa, e o varrimento do criterio 8 alerta sobre um
                    #     pedido que acabou de chegar
                    #   dsar_requests_concluido_par_ck  a equivalencia nos
                    #     **dois** sentidos entre `estado = 'concluido'` e o
                    #     `concluido_at` escrito, como o `refund_cases_fechado`
                    #     abaixo. Um `AND` onde esta o `=` aceitava um pedido
                    #     `concluido` sem data — e o criterio 3 conta pedidos
                    #     fechados pela data
                    #   dsar_requests_concluido_ordenado_ck  nao se conclui
                    #     antes de receber
                    #
                    # No ledger sao a chave primaria, o dominio dos seis escopos
                    # e a unicidade `(tenant_id, dsar_id, escopo)` — e esta
                    # ultima **e o criterio 3**: e ela que faz «o pedido so
                    # fecha quando todos aplicaram» contavel, porque o contrato
                    # do `privacy.erasure_applied` nao diz quem aplicou. Sem
                    # ela, seis eventos do mesmo componente fechavam o pedido.
                    #
                    # O `dsar_requests_aberto_uq` **nao** esta aqui, e nao e
                    # esquecimento: e um indice unico **parcial** e nao uma
                    # restricao, pelo que nao aparece no `pg_constraint`. Quem o
                    # confere e o `test_os_indices_unicos_parciais_sao_os_esperados`
                    # acima, que diz tambem que ele e unico.
                    "dsar_requests_pkey",
                    "dsar_requests_tenant_dsar_uq",
                    "dsar_requests_tipo_ck",
                    "dsar_requests_estado_ck",
                    "dsar_requests_papel_kamba_ck",
                    "dsar_requests_prazo_dias_ck",
                    "dsar_requests_prazo_ordenado_ck",
                    "dsar_requests_concluido_par_ck",
                    "dsar_requests_concluido_ordenado_ck",
                    "erasure_ledger_pkey",
                    "erasure_ledger_escopo_ck",
                    "erasure_ledger_escopo_uq",
                    # --------------------------------------- KAM-069 (0036)
                    #
                    # **Catorze**: a chave primaria, a unicidade e os doze
                    # `CHECK`. Os quatro primeiros sao de forma (dominio
                    # fechado, dominio fechado, ISO 3166-1, identificador), o
                    # quinto e o sexto recusam o vazio, e os seis ultimos ligam
                    # colunas — e sao eles que fazem a tabela nao poder
                    # contradizer-se.
                    "tenant_destinations_pkey",
                    "tenant_destinations_destino_uk",
                    "tenant_destinations_status_ck",
                    "tenant_destinations_purpose_ck",
                    "tenant_destinations_country_ck",
                    "tenant_destinations_provider_ck",
                    "tenant_destinations_apd_ref_ck",
                    "tenant_destinations_contrato_ref_ck",
                    "tenant_destinations_autorizado_com_apd_ref_ck",
                    "tenant_destinations_autorizado_com_checklist_ck",
                    "tenant_destinations_autorizado_com_janela_ck",
                    "tenant_destinations_revogado_com_janela_ck",
                    "tenant_destinations_janela_ordenada_ck",
                    "tenant_destinations_sem_janela_ck",
                    # ------------------------------------- KAM-054 (0032)
                    #
                    # **Quinze**: quatro do `payment_confirmers` (a chave
                    # composta, o dominio do papel e as duas chaves primarias
                    # contadas como uma), cinco da `manual_confirmations`, cinco
                    # da `refund_cases` e tres do `fraud_signals` — mais os
                    # `_pkey` das tres com `id`.
                    #
                    # Tres fazem trabalho que vale a pena nomear:
                    #
                    #   manual_confirmations_evidencia_ck  o M-7 imposto pela
                    #     base: `evidencia_ref LIKE 'nao_prova:%'`. Nao ha como
                    #     gravar um anexo do cliente sem dizer, no proprio
                    #     registo, que ele nao prova pagamento nenhum. O rotulo
                    #     tem de estar no **principio**, e ha ensaio para isso
                    #   manual_confirmations_msg_uq  a idempotencia do criterio
                    #     9, por `(charge_id, canal_msg_id)` e nao pelo
                    #     `canal_msg_id` so: os identificadores de mensagem vem
                    #     da Meta, e uma colisao global fazia a segunda cobranca
                    #     recusar uma confirmacao legitima
                    #   refund_cases_fechado  a equivalencia nos dois sentidos
                    #     entre o estado terminal e o instante de fecho. Um
                    #     `AND` onde devia estar o `=` aceitava um caso
                    #     `concluido` sem data e uma data sem conclusao
                    "payment_confirmers_pk",
                    "payment_confirmers_papel_ck",
                    "manual_confirmations_pkey",
                    "manual_confirmations_msg_uq",
                    "manual_confirmations_fase_ck",
                    "manual_confirmations_valor_ck",
                    "manual_confirmations_evidencia_ck",
                    #   manual_confirmations_decisao_ck  o dominio de quatro
                    #   manual_confirmations_decisao_da_fase  a equivalencia nos
                    #     **dois** sentidos entre «a fase decide» e «ha decisao
                    #     escrita». As duas sao a emenda que as tres revisoes
                    #     adversariais obrigaram: sem a coluna, o G8 aceitava a
                    #     fase de uma confirmacao **retida** como prova de que
                    #     os limites foram cumpridos
                    "manual_confirmations_decisao_ck",
                    "manual_confirmations_decisao_da_fase",
                    "refund_cases_pkey",
                    "refund_cases_valor_ck",
                    "refund_cases_estado_ck",
                    "refund_cases_um_sujeito",
                    "refund_cases_fechado",
                    "fraud_signals_pkey",
                    "fraud_signals_severidade_ck",
                    "fraud_signals_accao_ck",
                    # ------------------------------------- KAM-053 (0029)
                    #
                    # **Trinta e duas**: onze da `payment_charges`, tres do
                    # `payment_callbacks_inbox`, treze da `payment_events` e
                    # cinco da `payment_outbox_map`. **Era** a revisao que
                    # acrescentava mais restricoes a esta lista — a `0030`
                    # (KAM-044) traz quarenta e duas —, e a razao de serem tantas
                    # esta no que ela cria: seis dominios fechados, uma cadeia de
                    # *hashes* e as duas regras que o secao 14 cita como
                    # mecanismo.
                    #
                    # As duas que fazem o trabalho sao as que **nao** levam o
                    # nome da tabela, e e deliberado — o DDL do secao 6.2
                    # nomeia-as assim e elas descrevem uma regra e nao uma
                    # coluna:
                    #
                    #   confirmar_exige_autenticacao  o alvo «100% das `paga`
                    #     com evento autenticado» (secao 14). Um
                    #     `pagamento_confirmado` exige `authn_ok`, `decisao =
                    #     'aceite'` e um `authn_method` **dos tres** que
                    #     autenticam — o `sistema` nao esta na lista, e e esse o
                    #     dominio do quarto valor que este ticket decidiu.
                    #   humano_exige_actor  um `manual` sem `actor_id` nao e
                    #     auditavel: «quem confirmou?» nao tem resposta.
                    #
                    # O `payment_events_hashes_sha256` e **aditivo ao DDL do
                    # documento** (desvio registado no PR), pela razao da
                    # `0006`: sem ele um `prev_hash` de outro comprimento
                    # passava, e a verificacao da cadeia deixava de poder
                    # afirmar que compara sha256 com sha256. O
                    # `payment_callbacks_inbox_body_hash_sha256` e o mesmo para
                    # o corpo que entrou pela rede.
                    #
                    # Os dois `currency_ck` existem porque a coluna e `char(3)`:
                    # um `char(3)` **sem** `CHECK` aceita `'USD'` em silencio, e
                    # o `canon_lint` do *gate* 3b le os valores de um `CHECK`
                    # contra o dominio fechado do dicionario — e e por isso que
                    # o dominio de um valor se escreve e nao se presume.
                    #
                    # Os dois `um_sujeito` sao a exclusividade do secao 6.1 —
                    # uma cobranca e de encomenda **ou** de ciclo de billing,
                    # exactamente um — e ficam aqui, e nao no KAM-055, porque
                    # nao dependem de tabela nenhuma: e o `CHECK` que as FK em
                    # falta nao podem substituir.
                    "payment_charges_pkey",
                    "payment_charges_order_tentativa_uq",
                    "payment_charges_billing_tentativa_uq",
                    "payment_charges_um_sujeito",
                    "payment_charges_estado_ck",
                    "payment_charges_metodo_ck",
                    "payment_charges_motivo_falha_ck",
                    "payment_charges_amount_ck",
                    "payment_charges_currency_ck",
                    "payment_charges_tentativa_ck",
                    "payment_charges_provider_ck",
                    "payment_callbacks_inbox_pkey",
                    "payment_callbacks_inbox_estado_ck",
                    "payment_callbacks_inbox_body_hash_sha256",
                    "payment_events_pkey",
                    "payment_events_uq",
                    "payment_events_um_sujeito",
                    "payment_events_tipo_evento_ck",
                    "payment_events_sequencia_ck",
                    "payment_events_valor_ck",
                    "payment_events_currency_ck",
                    "payment_events_authn_method_ck",
                    "payment_events_decisao_ck",
                    "payment_events_actor_kind_ck",
                    "confirmar_exige_autenticacao",
                    "humano_exige_actor",
                    "payment_events_hashes_sha256",
                    "payment_outbox_map_pkey",
                    "payment_outbox_map_tipo_evento_ck",
                    "payment_outbox_map_authn_method_ck",
                    "payment_outbox_map_evt_tipo_ck",
                    "payment_outbox_map_evt_versao_ck",
                    # ------------------------------------- KAM-043 (0028)
                    # Onze da `offer_terms` e oito da `price_quotes`. As
                    # duas chaves, os cinco dominios fechados, os dois
                    # `CHECK` de forma do texto e os de dinheiro.
                    #
                    # O `offer_terms_preco_ck` e o criterio 1 a letra, e a
                    # equivalencia esta **nos dois sentidos**: um
                    # `sob_consulta` com preco afirmava um numero que
                    # ninguem cotou, e um `fixo` sem preco deixava o agente
                    # sem *fact* para citar — e e o segundo que faz falta
                    # mais vezes, e o que uma leitura distraida do `CHECK`
                    # deixa passar.
                    #
                    # O `offer_terms_categoria_restrita_ck` recusa texto em
                    # branco, e nao e cosmetica: vazio nao e «sem categoria
                    # restrita», e o `publishProduct` lia-o como presente e
                    # bloqueava a publicacao sem dizer qual.
                    #
                    # Os dois `currency_ck` existem porque a coluna e `text`
                    # e nao `char(3)` como o secao 5.4 escreve: um `char(3)`
                    # sem `CHECK` aceita `'USD'` em silencio e gate nenhum o
                    # le, e o `canon_lint` do *gate* 3b le os valores de um
                    # `CHECK` contra o dominio fechado do dicionario §3.4.
                    "offer_terms_pkey",
                    "offer_terms_sku_ck",
                    "offer_terms_nome_ck",
                    "offer_terms_preco_tipo_ck",
                    "offer_terms_stock_modo_ck",
                    "offer_terms_estado_ck",
                    "offer_terms_currency_ck",
                    "offer_terms_preco_ck",
                    "offer_terms_preco_nao_negativo_ck",
                    "offer_terms_categoria_restrita_ck",
                    # KAM-045 (0033): as **tres** que a reserva de stock
                    # acrescenta a tabela do KAM-043. Eram quatro: o
                    # `offer_terms_stock_garantido_exige_quantidade_ck` saiu
                    # depois da revisao adversarial, porque era uma barreira
                    # retroactiva sobre a tabela de outro ticket sem o caminho
                    # de escrita que a satisfaz — media-se em 34 erros na suite
                    # `tests_produtos`. O invariante passou para o predicado do
                    # `SQL_RESERVAR`.
                    "offer_terms_stock_quantidade_ck",
                    "offer_terms_stock_reservada_ck",
                    "offer_terms_stock_nao_sobrevende_ck",
                    "price_quotes_pkey",
                    "price_quotes_sku_ck",
                    "price_quotes_qty_ck",
                    "price_quotes_preco_ck",
                    "price_quotes_estado_ck",
                    "price_quotes_currency_ck",
                    # ------------------------------------- KAM-044 (0030)
                    #
                    # **Quarenta e duas**, e e agora esta a revisao que
                    # acrescenta mais restricoes a esta lista — a nota da
                    # `0029` dizia «trinta e duas» e era verdade quando foi
                    # escrita. Dezanove da `orders_mirror`, cinco do
                    # `order_intents`, oito do `order_state_log`, cinco do
                    # `order_state_graph` e cinco do
                    # `order_reconciliation_issues`.
                    #
                    # Nove dominios fechados, cinco chaves, tres unicidades e
                    # seis regras. **As regras sao o que distingue esta
                    # revisao**, e cada uma delas e um criterio de aceitacao
                    # feito restricao em vez de convencao:
                    #
                    #   orders_mirror_paga_exige_via_ck
                    #       o criterio 3 na coluna: `paga` exige instante e uma
                    #       das **duas** vias autenticadas. O que a coluna nao
                    #       alcanca — o actor e o `evento_id` — e o *trigger*
                    #       diferido que o exige, porque esses vivem na linha do
                    #       `order_state_log` e um `CHECK` nao ve outra tabela.
                    #       O `cod_manual` fica no dominio da coluna
                    #       (`orders_mirror_paga_via_ck`, tres valores) e fora
                    #       deste: nenhuma transicao do nucleo o escreve.
                    #
                    #   orders_mirror_entregue_exige_quem_ck
                    #       entregue sem quem confirmou era uma entrega que
                    #       ninguem assume — e o payload do `order.delivered`
                    #       exige o campo, pelo que a alternativa era descobri-lo
                    #       no `validarPayload` depois de a linha estar escrita.
                    #
                    #   orders_mirror_numero_ck
                    #       a forma do base32 de Crockford, sem `I`, `L`, `O`
                    #       nem `U`, ate oito caracteres. A unicidade e por
                    #       tenant (`orders_mirror_numero_uq`), e a geracao e a
                    #       omissao da coluna.
                    #
                    #   order_intents_concluida_exige_encomenda_ck
                    #       nos dois sentidos, como o `offer_terms_preco_ck`: um
                    #       recibo `concluida` sem encomenda nao e recibo de
                    #       nada, e uma encomenda num recibo `em_curso` dizia
                    #       que a saga nao acabou com a prova de que acabou.
                    #
                    #   order_state_log_version_ck  (`>= 2`)
                    #       uma encomenda nasce na versao 1 e a primeira
                    #       transicao leva-a a 2: um registo na versao 1
                    #       descrevia uma transicao que nao houve.
                    #
                    #   order_reconciliation_issues_resolvida_ck
                    #       tambem nos dois sentidos: sem instante nao se mede a
                    #       divergencia contra os 5 min da metrica, e um
                    #       instante numa divergencia aberta dizia que ela
                    #       fechou.
                    #
                    # A unicidade `order_state_log_version_uq` nao esta la para
                    # indexar: e **a idempotencia do DoD** — a mesma transicao
                    # gravada duas vezes e um `23505` e nao uma duplicacao
                    # silenciosa. E a `orders_mirror_tenant_id_uq` nao serve
                    # consulta nenhuma: existe para que as tres FK compostas
                    # para a `orders_mirror` possam existir.
                    "orders_mirror_pkey",
                    "orders_mirror_tenant_id_uq",
                    "orders_mirror_origem_ck",
                    "orders_mirror_estado_ck",
                    "orders_mirror_confirmacao_ck",
                    "orders_mirror_total_ck",
                    "orders_mirror_currency_ck",
                    "orders_mirror_snapshot_ck",
                    "orders_mirror_entrega_modo_ck",
                    "orders_mirror_paga_via_ck",
                    "orders_mirror_paga_exige_via_ck",
                    "orders_mirror_excepcao_ck",
                    "orders_mirror_entrega_confirmada_ck",
                    "orders_mirror_entregue_exige_quem_ck",
                    "orders_mirror_version_ck",
                    "orders_mirror_numero_ck",
                    "orders_mirror_intent_key_ck",
                    "orders_mirror_intent_uq",
                    "orders_mirror_numero_uq",
                    # KAM-045 (0033): as **doze** da reserva de stock (onze desde a `0046`) — oito
                    # `CHECK`, a chave primaria e a unicidade na tabela nova,
                    # mais as duas FK que o teste das cascatas ja conta a
                    # parte. As quatro da `offer_terms` estao mais abaixo, com
                    # as da `0028`, porque e dela que a tabela e.
                    "stock_reservations_pkey",
                    # A `stock_reservations_linha_uq` saiu com a `0046`
                    # (KAM-050): a unicidade passou a indice parcial
                    # (`stock_reservations_linha_viva_uq`), que nao e
                    # restricao e nao entra neste inventario.
                    "stock_reservations_estado_ck",
                    "stock_reservations_motivo_ck",
                    "stock_reservations_sku_ck",
                    "stock_reservations_qty_ck",
                    "stock_reservations_version_ck",
                    "stock_reservations_line_no_ck",
                    "stock_reservations_libertada_exige_motivo_ck",
                    "stock_reservations_consumida_exige_instante_ck",
                    # KAM-091 (0034): as **nove** do estado da saga — oito
                    # `CHECK` e a chave primaria, que **e** a unicidade
                    # `(onboarding_id, step)` do contrato e por isso nao ha
                    # `_uq` ao lado dela. **Nenhuma FK**: o passo 1 e que
                    # escreve a linha de `tenants`, pelo que esta tabela nao
                    # aparece no teste das cascatas.
                    "provisioning_step_pkey",
                    "provisioning_step_step_ck",
                    "provisioning_step_status_ck",
                    "provisioning_step_espera_ck",
                    "provisioning_step_attempt_ck",
                    "provisioning_step_error_code_ck",
                    "provisioning_step_external_id_ck",
                    "provisioning_step_falha_exige_codigo_ck",
                    "provisioning_step_concluido_limpo_ck",
                    "order_intents_pkey",
                    "order_intents_intent_key_ck",
                    "order_intents_draft_hash_ck",
                    "order_intents_estado_ck",
                    "order_intents_concluida_exige_encomenda_ck",
                    "order_state_log_pkey",
                    "order_state_log_de_ck",
                    "order_state_log_para_ck",
                    "order_state_log_sem_laco_ck",
                    "order_state_log_version_ck",
                    "order_state_log_causa_ck",
                    "order_state_log_actor_kind_ck",
                    "order_state_log_version_uq",
                    "order_state_graph_pkey",
                    "order_state_graph_de_ck",
                    "order_state_graph_para_ck",
                    "order_state_graph_sem_laco_ck",
                    "order_state_graph_flag_ck",
                    "order_reconciliation_issues_pkey",
                    "order_reconciliation_issues_tipo_ck",
                    "order_reconciliation_issues_detalhe_ck",
                    "order_reconciliation_issues_estado_ck",
                    "order_reconciliation_issues_resolvida_ck",
                    # ------------------------------------- KAM-022 (0015)
                    # A prova: a chave, a unicidade que da a idempotencia do
                    # criterio 2, os dois dominios e os dois `CHECK` de forma.
                    # O `evidence_ck` exige **32 bytes**, nem mais nem menos:
                    # um resumo de outro tamanho nao e um sha256, e uma prova
                    # que nao se sabe reproduzir nao e prova.
                    # KAM-052: as **oito** da conta de pagamento. A
                    # `payment_accounts_beneficiario_ck` e a que faz o trabalho:
                    # a equivalencia `(beneficiary_kind = 'pme') = (tenant_id IS
                    # NOT NULL)` nos dois sentidos, que e o que torna o
                    # `tenant_id` anulavel seguro em vez de frouxo. A
                    # `payment_accounts_credenciais_ref_ck` e o criterio 7 na
                    # base: a forma do `SecretRef` do KAM-010, nunca o segredo.
                    "payment_accounts_pkey",
                    "payment_accounts_webhook_token_uq",
                    "payment_accounts_beneficiary_kind_ck",
                    "payment_accounts_estado_ck",
                    "payment_accounts_liquidacao_destino_ck",
                    "payment_accounts_beneficiario_ck",
                    "payment_accounts_credenciais_ref_ck",
                    "payment_accounts_webhook_token_ck",
                    "payment_accounts_provider_ck",
                    "consent_event_pkey",
                    "consent_event_prova_uq",
                    "consent_event_purpose_ck",
                    "consent_event_canal_ck",
                    "consent_event_text_version_ck",
                    "consent_event_evidence_ck",
                    # O texto: chave natural `(version, purpose)`, o dominio
                    # das dez finalidades, e tres `CHECK` de forma. Um aviso
                    # vazio e pior do que nenhum: ele e a prova de que se
                    # informou.
                    "consent_texts_pkey",
                    "consent_texts_purpose_ck",
                    "consent_texts_texto_ck",
                    "consent_texts_version_ck",
                    "consent_texts_hash_ck",
                    # ------------------------------------- KAM-016 (0017)
                    # A chave, as **duas** unicidades que dao a idempotencia do
                    # criterio 2 (e as duas levam o `tenant_id`, pela razao da
                    # emenda 1.21), o dominio das nove fases, e seis `CHECK` de
                    # forma. O `canal_ck` e uma **implicacao e nao uma
                    # igualdade**: nas seis fases do meio ha canal, e nas tres
                    # de fora pode nao haver — o `falhado` **pode** ter canal
                    # enquanto a compensacao nao correu, e um `CHECK` sobre as
                    # seis recusava esse estado legitimo.
                    "channel_onboarding_pkey",
                    "channel_onboarding_code_uq",
                    "channel_onboarding_tenant_waba_uq",
                    "channel_onboarding_fase_ck",
                    "channel_onboarding_canal_ck",
                    "channel_onboarding_waba_id_ck",
                    "channel_onboarding_waac_id_ck",
                    "channel_onboarding_phone_number_id_ck",
                    "channel_onboarding_code_hash_ck",
                    "channel_onboarding_recursos_ck",
                    "channel_onboarding_pin_ref_ck",
                    "channel_onboarding_motivo_ck",
                    # ------------------------------------- KAM-017 (0018)
                    # A chave, a unicidade por canal (que e o criterio 9 pela
                    # base: a reconexao repoe em vez de duplicar), os **dois**
                    # dominios fechados — o `estado` com quatro valores e o
                    # `motivo_desligamento` com os seis do `E1` §2 —, o `CHECK`
                    # de **conteudo** dos passos (`<@ ARRAY[...]`, e nao de
                    # cardinalidade), o prazo depois do arranque, as contagens
                    # nao negativas, e o `desligamento_ck`, que e uma
                    # **igualdade e nao uma implicacao**: um desligamento tem as
                    # duas metades ou nenhuma.
                    # KAM-115: as duas tabelas do aviso ao dono. No contacto,
                    # o dominio de **um** valor do `canal` (o painel nao tem
                    # endereco, o sms e o KAM-116), os dois `CHECK` de
                    # comprimento — `bytea` aceita qualquer um, e e aqui que se
                    # diz que um `sha256` tem 32 octetos e um criptograma pelo
                    # menos 30 —, e os dois pares em **igualdade e nao
                    # implicacao**: uma invalidacao tem as duas metades ou
                    # nenhuma, e um resumo de confirmacao sem prazo era uma
                    # ligacao eterna. No aviso, os quatro dominios fechados, a
                    # unicidade de quatro colunas que e a idempotencia do
                    # criterio 2 **e** os lembretes do criterio 4 ao mesmo tempo,
                    # o `lembrete BETWEEN 0 AND 2` que e o «depois para» do
                    # criterio 4 na base, e o `episodio` nao vazio — um episodio
                    # vazio punha todos os avisos do mesmo gatilho na mesma chave
                    # e o segundo episodio de um tenant nunca mais era avisado.
                    "owner_contacts_pkey",
                    "owner_contacts_canal_uq",
                    "owner_contacts_canal_ck",
                    "owner_contacts_motivo_ck",
                    "owner_contacts_invalidez_ck",
                    "owner_contacts_confirmacao_ck",
                    "owner_contacts_hash_ck",
                    "owner_contacts_enc_ck",
                    "owner_notices_pkey",
                    "owner_notices_idempotencia_uq",
                    "owner_notices_gatilho_ck",
                    "owner_notices_canal_ck",
                    "owner_notices_estado_ck",
                    "owner_notices_falha_ck",
                    "owner_notices_lembrete_ck",
                    "owner_notices_tentativas_ck",
                    "owner_notices_entrega_ck",
                    "owner_notices_motivo_ck",
                    "owner_notices_episodio_ck",
                    "owner_notices_chave_ck",
                    "channel_coexistence_pkey",
                    "channel_coexistence_canal_uq",
                    "channel_coexistence_estado_ck",
                    "channel_coexistence_passos_ck",
                    "channel_coexistence_motivo_ck",
                    "channel_coexistence_prazo_ck",
                    "channel_coexistence_contagens_ck",
                    "channel_coexistence_desligamento_ck",
                    # ------------------------------------- KAM-028 (0021)
                    # A chave, os tres dominios fechados de canon (`klass`,
                    # `status` e os dez codigos do §6.5) e as cinco coerencias.
                    #
                    # **O dominio do `error_code` e restricao propria**, separada
                    # da coerencia com o `status`: o *gate* 3b exige «CHECK
                    # fechado» na coluna para reconhecer os dez valores como
                    # canon, e dentro de uma condicao composta nao os ve.
                    #
                    # **Dois `CHECK` sao de forma e nao de dominio**, e isso e
                    # deliberado: o `tool` e o `vertical` levam uma gramatica de
                    # identificador em vez da lista das onze tools. Uma lista de
                    # permitidos obrigava a uma revisao de base de dados por
                    # cada tool que o KAM-031, o KAM-035 ou a Fase C
                    # acrescentassem, e quem recusa uma tool fora do catalogo e
                    # o passo 1 do `invoke` — com `TOOL_NOT_ALLOWED` e contra o
                    # registo, que e onde a lista vive.
                    #
                    # O `erro_tem_codigo` olha para os **dois** sentidos: um
                    # `ok` com codigo e um `erro` sem codigo sao a mesma classe
                    # de linha ilegivel.
                    "tool_audit_pkey",
                    "tool_audit_klass",
                    "tool_audit_status",
                    "tool_audit_tool_nome",
                    "tool_audit_vertical_nome",
                    "tool_audit_error_code",
                    "tool_audit_erro_tem_codigo",
                    "tool_audit_resultado_so_em_ok",
                    "tool_audit_hashes_sha256",
                    "tool_audit_latencia_nao_negativa",
                    "tool_audit_fact_ids_sem_nulos",
                    "tool_audit_texto_curto",
                    # ------------------------------------- KAM-029 (0022)
                    # Seis, e a primeira e a que mais vale: o `key_sha256` e o
                    # criterio 6 do bloco imposto **pela base** e nao por um
                    # teste nosso — «a coluna `key` nunca contem `+244`» passa a
                    # ser verdade porque nenhum telefone casa `^[0-9a-f]{64}$`.
                    #
                    # O `resultado_so_em_concluida` olha para os **dois**
                    # sentidos, pela licao que a `0021` pagou: uma `concluida`
                    # sem `result` devolvia um *replay* vazio, e um `result`
                    # numa `falhada` era um resultado devolvido como *replay* de
                    # uma invocacao que ninguem confirmou.
                    #
                    # O `tool_nome` e de forma e nao de dominio, pela razao
                    # exacta do `tool_audit_tool_nome` acima.
                    "tool_idempotency_pkey",
                    "tool_idempotency_key_sha256",
                    "tool_idempotency_estado",
                    "tool_idempotency_tool_nome",
                    "tool_idempotency_args_hash_sha256",
                    "tool_idempotency_resultado_so_em_concluida",
                    # ------------------------------------- KAM-114 (0024)
                    # Catorze na `draft_decisions`, e as quatro coerencias sao
                    # a parte que importa: o par `decisao`/`decidido_at` nao
                    # pode divergir (uma linha decidida sem instante nao
                    # responde a «quanto esperou o operador»), a `razao_edicao`
                    # existe **so** no `editado` (senao um `rejeitado` dizia que
                    # houve uma edicao que nao houve, e o `draft_edit_ratio_p50`
                    # contava-a), o `edicao_numero_livre` so no `editado` pela
                    # mesma razao, e o `graph_version` leva forma SemVer porque
                    # e a unica coluna que sai na exportacao do criterio 7.
                    "draft_decisions_pkey",
                    # (A `draft_decisions_tenant_fk` **nao** entra aqui: esta
                    # consulta filtra `contype IN ('c', 'u', 'p')` e uma FK e
                    # `'f'`. Ela esta na lista do `test_as_fk_nao_apagam_em_cascata`,
                    # que e a consulta das FK.)
                    "draft_decisions_decisao_ck",
                    "draft_decisions_motivo_ck",
                    "draft_decisions_decidido_ck",
                    "draft_decisions_razao_edicao_ck",
                    "draft_decisions_razao_dominio_ck",
                    "draft_decisions_numero_livre_ck",
                    "draft_decisions_latencia_ck",
                    "draft_decisions_turn_seq_ck",
                    "draft_decisions_draft_id_ck",
                    "draft_decisions_thread_id_ck",
                    "draft_decisions_turn_id_ck",
                    "draft_decisions_graph_version_ck",
                    # ------------------------------------- KAM-015 (0010)
                    # Os dois dominios da `outbound_messages`, as duas
                    # unicidades (a da chave de idempotencia e **por tenant**;
                    # a do `wamid` e global, e a assimetria esta no §3.14), e as
                    # tres coerencias: template obrigatorio fora de `service`,
                    # instante de entrega so onde houve entrega — `delivered`,
                    # `read` e os **dois terminais**, porque uma mensagem
                    # entregue pode passar a `failed` depois e o instante nao
                    # se apaga —, codigo de erro so em `failed`.
                    #
                    # Nos templates: as tres listas fechadas — e a de `quality`
                    # permite nulos sem o dizer, porque em SQL um `CHECK` que
                    # avalie a NULL passa.
                    #
                    # E a `UNIQUE (tenant_id, id)` que esta revisao acrescenta a
                    # `conversations` para a FK composta poder assentar nela,
                    # como a `0009` fez a `tenant_channels`.
                    # ------------------------------------- KAM-019 (0011)
                    # A chave derivada da passagem, o dominio do seu estado, a
                    # coerencia do motivo nao vazio, e as quatro da conta de
                    # atendimento: a chave natural `(tenant_id, provedor)`, a
                    # **unicidade da conta no provedor** — que e o que impede a
                    # mesma conta em dois tenants, o furo que o X-10 procura e
                    # que a chave primaria sozinha nao fecha —, o dominio do
                    # provedor e a referencia a segredo nao vazia.
                    #
                    # **O que nao esta aqui e deliberado**: nao ha `CHECK`
                    # sobre o `resumed_at` nem sobre o `resolver`. Era o que
                    # apetecia, e e o defeito que a `outbound_messages_entrega_ck`
                    # da `0010` pagou — uma restricao que recusa um estado que a
                    # propria maquina produz. Aqui e pior, porque ninguem
                    # escreve essas duas colunas neste ticket: o
                    # compare-and-set e do KAM-034.
                    "handoff_accounts_conta_uq",
                    "handoff_accounts_pkey",
                    "handoff_accounts_provedor_ck",
                    "handoff_accounts_token_ck",
                    # As duas da emenda 1.23, que vem do spike: o utilizador da
                    # conta fecha o mesmo furo que o `conta_uq` fecha para a
                    # conta, e a referencia dele nao pode ser vazia pela mesma
                    # razao que a do bot — uma referencia vazia e um segredo
                    # que ninguem vai buscar.
                    "handoff_accounts_user_token_ck",
                    "handoff_accounts_utilizador_uq",
                    "handoffs_motivo_ck",
                    "handoffs_pkey",
                    "handoffs_status_ck",
                    # KAM-020: nove na `media_assets`. **As tres FK nao
                    # entram aqui** — esta lista e de `p`, `u` e `c`, e as FK
                    # tem o seu proprio teste (o da cascata). A primeira versao
                    # pos as tres aqui e a lista ficou com tres elementos a
                    # mais. A `armazenado_ck` e a
                    # unica do esquema que liga **duas** colunas por estado: um
                    # `armazenado` sem `storage_ref` e uma linha que diz que o
                    # objecto esta la e nao diz onde. **E nao ha `CHECK` sobre
                    # o `retain_until`**, de proposito: uma restricao que o
                    # obrigasse a ser futuro impedia o KAM-071 de marcar um
                    # objecto para eliminacao imediata — a licao que a
                    # `outbound_messages_entrega_ck` da `0010` pagou.
                    # KAM-021: seis na `channel_quality_log`. **As duas FK
                    # nao entram aqui** — esta lista e de `p`, `u` e `c`, e
                    # as FK tem o seu proprio teste (o da cascata). A
                    # `event_key_uq` e composta com o `tenant_id`: com
                    # unicidade global, um evento de B que calhasse na
                    # mesma chave era deduplicado em silencio contra uma
                    # linha de A, que e a divergencia que a emenda 1.21 do
                    # dicionario registou para a `idempotency_key`.
                    "channel_quality_log_event_key_ck",
                    "channel_quality_log_event_key_uq",
                    "channel_quality_log_evento_ck",
                    "channel_quality_log_pkey",
                    "channel_quality_log_valor_anterior_ck",
                    "channel_quality_log_valor_novo_ck",
                    "media_assets_armazenado_ck",
                    "media_assets_classe_ck",
                    "media_assets_estado_ck",
                    "media_assets_media_id_ck",
                    "media_assets_origem_uq",
                    "media_assets_pkey",
                    "media_assets_sha256_ck",
                    "media_assets_size_ck",
                    "media_assets_wamid_ck",
                    "conversations_tenant_id_uq",
                    "message_templates_category_ck",
                    "message_templates_pkey",
                    "message_templates_quality_ck",
                    "message_templates_status_ck",
                    "outbound_messages_entrega_ck",
                    "outbound_messages_erro_ck",
                    "outbound_messages_idempotency_uq",
                    "outbound_messages_kind_ck",
                    "outbound_messages_pkey",
                    "outbound_messages_state_ck",
                    "outbound_messages_template_ck",
                    "outbound_messages_wamid_uq",
                    # ------------------------------------- KAM-014 (0009)
                    # O dominio de `mode`, a coerencia da janela (os dois
                    # tempos andam juntos e o fim e depois do inicio), a chave
                    # primaria e a unicidade que torna o `ON CONFLICT` do CHR
                    # idempotente. E a `UNIQUE (tenant_id, id)` que a `0009`
                    # acrescenta a `tenant_channels` para a FK composta poder
                    # assentar nela.
                    "conversations_janela_ck",
                    "conversations_mode_ck",
                    "conversations_pkey",
                    "conversations_tenant_contact_channel_uq",
                    "tenant_channels_tenant_id_uq",
                    # ------------------------------------- KAM-013 (0008)
                    # Os dois dominios fechados, os tectos de comprimento dos
                    # tres valores que vem do corpo do webhook, e as duas
                    # chaves de deduplicacao. O `CHECK` do `payload` e o tecto
                    # de armazenamento: uma coluna sem limite escrita a partir
                    # de um corpo externo e armazenamento ilimitado a custa de
                    # outrem.
                    "inbound_events_event_key_ck",
                    "inbound_events_kind_ck",
                    "inbound_events_kind_event_key_uq",
                    "inbound_events_phone_number_id_ck",
                    "inbound_events_pkey",
                    "inbound_events_waba_id_ck",
                    "unrouted_events_event_key_ck",
                    "unrouted_events_kind_ck",
                    "unrouted_events_kind_event_key_uq",
                    "unrouted_events_motivo_ck",
                    "unrouted_events_payload_ck",
                    "unrouted_events_phone_number_id_ck",
                    "unrouted_events_pkey",
                    "unrouted_events_waba_id_ck",
                    # ------------------------------------- KAM-009 (0007)
                    "tenant_usage_chave_limite_ck",
                    "tenant_usage_periodo_ck",
                    "tenant_usage_pkey",
                    "tenant_usage_valor_ck",
                    "usage_ledger_chave_limite_ck",
                    "usage_ledger_idempotency_key_ck",
                    "usage_ledger_pkey",
                    "usage_ledger_quantidade_ck",
                    # A forma de `tenants.plano`, acrescentada pela `0007` a
                    # uma tabela da `0001`. E de forma e nao de dominio, e a
                    # razao esta no dicionario §3.2 e na propria revisao.
                    "tenants_plano_ck",
                    # ------------------------------------- KAM-012 (0006)
                    "audit_heads_hash_sha256",
                    "audit_heads_pkey",
                    "audit_log_action",
                    "audit_log_actor_id_nao_vazio",
                    "audit_log_actor_type",
                    "audit_log_entity_id_nao_vazio",
                    "audit_log_hashes_sha256",
                    "audit_log_pkey",
                    # Uma bifurcacao da cadeia deixa de ser detectada pelo
                    # verificador e passa a ser impossivel de escrever.
                    "audit_log_row_hash_uq",
                    "audit_log_texto_curto",
                    # ------------------------------------- KAM-006 (0005)
                    "events_consumed_pkey",
                    "events_dlq_estado_ck",
                    "events_dlq_pkey",
                    "events_dlq_resolucao_ck",
                    "evt_acoes_conclusao_ck",
                    "evt_acoes_estado_ck",
                    "evt_acoes_pkey",
                    "evt_dlq_aprovacoes_aprovador_ck",
                    "evt_dlq_aprovacoes_pkey",
                    "evt_subscricoes_payment_exige_ordem",
                    "contact_deks_destruida_ck",
                    "contact_deks_kek_id_ck",
                    "contact_deks_pkey",
                    "contact_deks_tenant_dek_uq",
                    "contact_endpoints_bsuid_hmac_ck",
                    "contact_endpoints_bsuid_uq",
                    "contact_endpoints_finalidade_ck",
                    "contact_endpoints_forma_ck",
                    "contact_endpoints_pkey",
                    "contact_endpoints_tipo_ck",
                    "contacts_inactivo_sem_phone_ck",
                    "contacts_merged_outro_ck",
                    "contacts_merged_par_ck",
                    "contacts_phone_hmac_ck",
                    "contacts_phone_par_ck",
                    "contacts_pkey",
                    "contacts_tenant_contact_uq",
                    "hmac_key_versions_estado_ck",
                    "hmac_key_versions_kid_ck",
                    "hmac_key_versions_pkey",
                    # KAM-005. A forma do `docs/tecnica/06` §6.1 e §6.5: o
                    # `events_outbox` tem a chave de identidade, a unicidade do
                    # `event_id` (que e o que deduplica na fila) e a do triplo do
                    # agregado (que e o que impede duas linhas com o mesmo
                    # `seq`); `events_log` tem a chave composta com a coluna de
                    # particao, e a particao `DEFAULT` tem a sua.
                    "events_log_default_pkey",
                    "events_log_pkey",
                    "events_outbox_agregado_uq",
                    "events_outbox_event_id_uq",
                    "events_outbox_pkey",
                    "evt_agregado_seq_pkey",
                    "evt_subscricoes_pkey",
                    "entitlements_limites_ck",
                    "entitlements_modulo_ck",
                    "entitlements_pk",
                    "tenant_channels_channel_mode_ck",
                    "tenant_channels_estado_ck",
                    "tenant_channels_free_tier_used_ck",
                    # KAM-023, revisao 0013.
                    # KAM-021, revisao 0014.
                    "tenant_channels_max_phone_numbers_ck",
                    "tenant_channels_meta_error_codes_seen_ck",
                    "tenant_channels_motivo_restricao_ck",
                    "tenant_channels_origem_ck",
                    "tenant_channels_phone_number_id_ck",
                    "tenant_channels_phone_number_id_uq",
                    "tenant_channels_pkey",
                    "tenant_channels_token_ref_ck",
                    "tenant_channels_vertical_ck",
                    "tenant_channels_waba_id_ck",
                    "tenants_estado_ck",
                    "tenants_nif_ck",
                    "tenants_nome_ck",
                    "tenants_pkey",
                    "tenants_tipo_ck",
                ]
            ),
        )
