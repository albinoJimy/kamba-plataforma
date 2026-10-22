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
}

#: A particao `DEFAULT` tem as colunas do pai, uma a uma. Esta aqui — e nao
#: escrita a mao — porque uma particao que divergisse do pai era impossivel no
#: PostgreSQL, e repetir onze linhas convidava a que divergissem **no
#: inventario**: a copia envelhecia e ninguem notava.
INVENTARIO["events_log_default"] = dict(INVENTARIO["events_log"])


class TestInventario(ComBase):
    def no_catalogo(self) -> dict[str, dict[str, tuple]]:
        linhas = self.consultar(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'platform'"
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

    def test_toda_a_coluna_tem_a_pergunta_dos_dados_pessoais_respondida(self) -> None:
        for tabela, colunas in INVENTARIO.items():
            for coluna, (_, _, _, pessoal) in colunas.items():
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    self.assertTrue(pessoal.strip())

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
            # KAM-006: parcial e **unico**, e e o unico desta revisao. Impoe a
            # reentrada idempotente **entre as abertas**: o mesmo evento a
            # falhar outra vez nao abre uma segunda entrada aberta, mas um
            # ciclo novo depois de uma resolucao abre a sua. Perder o `UNIQUE`
            # daqui nao muda plano de consulta nenhum — nao se ve em lado
            # nenhum — e dava duas entradas abertas sobre o mesmo evento, com o
            # alerta a contar o dobro.
            "events_dlq_aberta_uq": True,
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
