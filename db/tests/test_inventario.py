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

    def test_toda_a_coluna_tem_a_pergunta_dos_dados_pessoais_respondida(self) -> None:
        for inventario in (INVENTARIO, INVENTARIO_SERVICOS):
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
            "draft_decisions_thread_idx": False,
            # KAM-006: parcial e **unico**, e e o unico desta revisao. Impoe a
            # reentrada idempotente **entre as abertas**: o mesmo evento a
            # falhar outra vez nao abre uma segunda entrada aberta, mas um
            # ciclo novo depois de uma resolucao abre a sua. Perder o `UNIQUE`
            # daqui nao muda plano de consulta nenhum — nao se ve em lado
            # nenhum — e dava duas entradas abertas sobre o mesmo evento, com o
            # alerta a contar o dobro.
            "events_dlq_aberta_uq": True,
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
