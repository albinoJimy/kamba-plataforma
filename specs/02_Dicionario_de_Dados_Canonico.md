# Dicionário de Dados Canónico — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Foundation — Dicionário de Dados Canónico |
| Versão | 1.0 — **PROPOSTA** |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/` (docs 00–10), `specs/EPIC-*.md` |
| Documentos relacionados | `specs/00_KAMBA_Carta.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-01_Fundacoes_Dados.md` (KAM-111) |

---

## 1. Porquê este documento

Os documentos técnicos e os epics foram escritos em paralelo e **divergem em nomes, unidades e estados** (identificados na redacção dos epics). Em vez de reabrir dez documentos, este dicionário fixa **um nome por conceito**.

**Precedência.** Até ao KAM-111 (reconciliação de `../docs/tecnica/`) estar `Done`, **este dicionário prevalece** sobre `../docs/tecnica/03`, `04`, `06`, `08`, `10` e sobre qualquer ticket em divergência. Um nome fora deste dicionário num DDL, evento ou contrato é um defeito (gate de CI previsto em KAM-111).

**Estado.** Proposta. As escolhas assinaladas «*proposta*» são decisões minhas entre variantes existentes; não são factos. Os valores numéricos continuam a ser propostas a calibrar no Piloto.

## 2. Convenções gerais

| Tema | Regra canónica |
|---|---|
| Dinheiro | Inteiro em **unidade menor** (`*_minor`, cêntimos de AOA) + `currency` (`'AOA'`). Nunca vírgula flutuante. Apresentação ao cliente: «12.500 Kz» (a unidade menor só existe em armazenamento, eventos e contratos) |
| Identificadores | UUID aleatório (`gen_random_uuid()`); `contact_id` nunca derivado de telefone |
| Tempo | `timestamptz` em UTC; sufixo `_at` (`criado_at`, `pago_at`); apresentação em `Africa/Luanda` |
| Idioma dos nomes | Domínio angolano em português sem acentos (`encomenda`, `estado`, `referencia`); técnico em inglês (`tool`, `thread_id`, `idempotency_key`). Os nomes abaixo são os que existem |
| Estados | Minúsculas, `snake_case`, sem acentos |
| Multi-tenant | Toda a tabela de negócio tem `tenant_id uuid NOT NULL` + RLS `FORCE` (ADR-015); excepções (`tenants`, `contacts` globais, catálogos de referência) declaradas em KAM-004 |
| Soft delete | Estado, nunca `DELETE`, salvo purga prevista (KAM-071, KAM-098) |

## 3. Nomes canónicos por conceito

### 3.1 Identidade de contacto e consentimento (ADR-010)

| Conceito | Nome canónico | Substitui / variantes encontradas | Nota |
|---|---|---|---|
| Contacto | `contacts(contact_id, tenant_id, criado_at, …)` | 3 versões em `../docs/tecnica/01 §6.2`, `03 §5.3`, `06 §7.2` | Sem telefone nem BSUID em claro |
| Endpoints do contacto | `contact_endpoints(contact_id, tipo, bsuid_hmac, bsuid_enc, dek_id, phone_enc, …)` | idem | `bsuid_enc` e `phone_enc` cifrados com DEK por contacto (`dek_id`); o HMAC serve só para correspondência. O envio usa o `recipient` descifrado em memória |
| HMAC de pesquisa de um contacto | `contact_endpoints.bsuid_hmac` (BSUID) e `contacts.phone_hmac` (telefone), cada um com a versão da chave em `hmac_kid` | `lookup_hmac` | *proposta* (emenda 1.8, KAM-008). **Decide a linha 3 do KAM-141 a favor deste dicionário:** o bloco do KAM-008 pedia `lookup_hmac` e `UNIQUE (tenant_id, hmac_kid, lookup_hmac)` em `contacts`; o HMAC do BSUID vive em `contact_endpoints`, como a linha de cima já dizia e a emenda D-01 do KAM-111 levou a `../docs/tecnica/`, e a unicidade é `UNIQUE (tenant_id, hmac_kid, bsuid_hmac)` nessa tabela. A mensagem do HMAC leva o tipo e o `tenant_id` (o mesmo cliente em dois tenants não dá o mesmo HMAC). Pseudonimização, não anonimização (`../docs/tecnica/08` §7.2) |
| Estado de um contacto | `contacts.erased_at` (apagado a pedido do titular), `contacts.merged_into` e `contacts.merged_at` (absorvido numa fusão: a linha fica como lápide e aponta para quem a absorveu) | — | *proposta* (emenda 1.8, KAM-008). `erased_at` vem de `../docs/tecnica/03` §5.3; a lápide é deste ticket. Um contacto apagado ou absorvido não guarda `phone_hmac` |
| Chave de dados do contacto | `contact_deks(dek_id, tenant_id, contact_id, wrapped_dek, kek_id, criado_at, destroyed_at)` | «chave por tenant» (`../docs/tecnica/03` §5.3) | *proposta* (emenda 1.8, KAM-008). Uma DEK por contacto, embrulhada pela KEK do cofre; destruí-la (`wrapped_dek` nulo, `destroyed_at` datado) é o *crypto-shredding* do `../docs/tecnica/06` §7.6. A chave por tenant do doc 03 não deixa apagar um só titular |
| Versões da chave de pesquisa | `hmac_key_versions(kid, estado, criado_at)` | — | *proposta* (emenda 1.8, KAM-008). Metadados, **nunca o segredo**. No máximo uma versão actual e uma anterior: são as duas que a pesquisa tenta durante a rotação. Três estados: os dois que o anel de segredos já nomeia (§3.9, «actual» e «anterior») e «retirada», que está, qualificado pela coluna, em `../canon/extensoes.yaml` |
| Pseudónimo para analytics | `sujeito_ref = HMAC(chave_mensal, contact_id)` | `msisdn_hash` | Chave rodada; nunca de telefone |
| Prova de consentimento | `consent_event` (append-only) | `consent_log`, `consent_ledger`, `consents` | Campos: `tenant_id`, `contact_id`, `purpose`, `text_version`, `accepted`, `canal`, `evidence_hash`, `ocorrido_em`. Finalidades: `transaccao`, `marketing`, `partilha_estafeta`, `melhoria`, `notificacao_dono` |
| Chave de conversa | `thread_id = {tenant_id}:{contact_id}` | `msisdn_hash+tenant` | — |

### 3.2 Tenants e canais

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Estado do tenant | `onboarding`, `ativo`, `restrito`, `suspenso`, `encerrado` | `tenants.estado` sem `restrito` (`../docs/tecnica/03`) | `restrito` = limitação **imposta pela Meta** (quality rating); `suspenso` = decisão nossa. Ver `../docs/tecnica/00 §6.2` |
| Fase do onboarding | `onboarding_case.fase`: `kyc_pendente`, `aprovado`, `provisionando`, `aguarda_es`, `aguarda_catalogo`, `pronto` | — | Sub-estados do `onboarding`, não estados do tenant |
| Pré-alocação do tenant | `onboarding_case.tenant_id` criado no registo | — | O `events_outbox.tenant_id` é `NOT NULL` |
| Entitlement (chaves) | `msgs_ai_mes`, `marcacoes_mes`, `imagens_mes`, `posts_mes`, `orcamentos_mes`, `valor_max_pedido_minor` (limite do plano e do tecto K1/K2), `manual_max_minor` (limite do `ManualProvider`) | `valor_max_pedido_kz`, `manual_max_minor` | Limite efectivo de um pedido = **mínimo** de `valor_max_pedido_minor` e, se `ManualProvider`, `manual_max_minor` |
| Tenant (tabela e chave) | `platform.tenants(id uuid)` — a chave primária chama-se **`id`**, não `tenant_id` | — | *proposta* (emenda 1.2, KAM-003). A convenção `contacts(contact_id, …)` aplica-se à coluna que **referencia** um tenant nas tabelas de negócio, não à chave da própria tabela. `../docs/tecnica/03` §5.2 e as quinze tabelas de dinheiro de `../docs/tecnica/04` já escrevem `REFERENCES platform.tenants(id)`, e o KAM-004 assume `id = app.tenant_id`: escolher `tenant_id` custaria um `ALTER` em cascata por todo o doc 04 |
| Tipo de tenant | `tenants.tipo` ∈ {`pme`, `courier`, `reseller`, `agent`, `platform`} | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/03` §5.2. O valor `platform` é o que a guarda do ADR-011 recusa em produção do Piloto |
| Canal | `tenant_channels(tenant_id, phone_number_id, waba_id, vertical, estado, …)` | — | Estados do canal: ver a linha seguinte |
| Estado do canal | `pendente`, `ativo`, `restrito`, `desligado`, `suspenso`, `encerrado` | `tenant_channels.estado` com três estados (`../docs/tecnica/03` §5.2) | *proposta* (emenda 1.2). **Definidos em KAM-003 e não em KAM-014**, ao contrário do que esta linha dizia: o KAM-014 depende do KAM-003, pelo que mandar o DDL esperar por ele era uma inversão de dependência. Os seis vêm de `../docs/tecnica/01` §7.1; o KAM-014 herda-os |
| Origem do canal | `tenant_channels.origem` ∈ {`pme`, `plataforma`} | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/01` §7.1. `plataforma` é Fluxo B, recusado em produção do Piloto (ADR-011) |
| Modo do canal | `tenant_channels.channel_mode` ∈ {`coexistencia`, `cloud_only`} | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/01` §7.1 |
| Entitlement (tabela) | `entitlements(tenant_id, modulo, limites jsonb, ativo boolean)`, chave `(tenant_id, modulo)` | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/03` §5.2. As **chaves** de `limites` estão na linha «Entitlement (chaves)»; os valores de `modulo` em §3.7 |
| Papéis de base de dados | `kamba_migrator` (DDL, dono das tabelas), `kamba_app` (`NOBYPASSRLS`, sem DDL), `kamba_batch` (`BYPASSRLS`, auditado) | `kamba_ops` (`../docs/tecnica/03` §5.5, `../docs/tecnica/04` §6) | *proposta* (emenda 1.2, KAM-003). Resolve-se a favor de `../docs/tecnica/08` §3.3, que é o documento de isolamento e a autoridade sobre papéis. O `REVOKE … FROM PUBLIC, kamba_app, kamba_ops` de `../docs/tecnica/04` revoga de um papel que não existirá — divergência a corrigir, **não** coberta pelas 12 do KAM-111 |
| Privilégios de `kamba_app` | `SELECT` e `INSERT` por tabela; `UPDATE` **por coluna**; **sem `DELETE`** em tabela nenhuma de `platform` | `SELECT/INSERT/UPDATE/DELETE` igual a `kamba_batch` (primeira versão do KAM-003) | *proposta* (emenda 1.4, KAM-003). O §2 já diz «soft delete: estado, nunca DELETE»; quem apaga é o `kamba_batch`. Colunas que `kamba_app` não altera depois do *insert*: `tenants.tipo` e `tenant_channels.origem` (a costura do Fluxo B — com `UPDATE` livre, um tenant `platform` passava a `pme` e saía da vista da guarda do ADR-011), `tenant_channels.tenant_id` (mover um canal de tenant), e as chaves e `criado_at`. **Por decidir:** quem altera `tenants.plano`, `estado` e `verificado_at` — hoje `kamba_app` pode, e nenhum documento diz quem deve (KAM-004 ou KAM-009) |
| Forma das chaves de configuração em colunas | `tenant_channels.vertical` e `entitlements.modulo`: `^[a-z][a-z0-9_]*$` | texto livre | *proposta* (emenda 1.4, KAM-003). `CHECK` de **forma**, não de domínio: as verticais e os módulos são configuração (ADR-012), mas o §2 já fixa minúsculas e `snake_case`. Sem ele, `'Assistente'` e `' assistente'` entravam na coluna com uma forma que nenhuma comparação previa |
| Contexto de tenant na base | variável `app.tenant_id`, definida com `set_config('app.tenant_id', <uuid>, true)` — local à transacção | `SET` de sessão | *proposta* (emenda 1.5, KAM-004), de `../docs/tecnica/08` §3.3. Só pelos *helpers* de `tenant_guard` (`tx`/`comTenant`); nunca à mão |
| Política de isolamento | `tenant_iso` (USING e WITH CHECK), criada por `rls.enable_tenant_rls` | `tenant_isolamento` (`../docs/tecnica/03` §5.5) | *proposta* (emenda 1.5, KAM-004). O nome é o de `../docs/tecnica/08` §3.3 e do ticket. Em `tenants` a coluna da política é `id`; nas outras, `tenant_id` |
| Papel do resolvedor | `kamba_resolver` — `NOBYPASSRLS`; política própria `resolver_leitura` (`FOR SELECT … USING (true)`); `SELECT` só em `tenant_channels(id, tenant_id, phone_number_id, vertical, origem, estado, channel_mode)` e `tenants(id, tipo, estado)` | «papel estreito» sem nome (`../docs/tecnica/03` §5.5) | *proposta* (emenda 1.5, KAM-004). Resolve `phone_number_id → tenant` antes de haver contexto, e é **o papel com que corre a guarda de arranque do ADR-011**. As colunas são as mínimas para hoje e revêem-se no KAM-014 |
| Papel de identidade | `kamba_identity` — `NOBYPASSRLS`; o único papel de serviço com `SELECT` em `contact_endpoints` e `contact_deks`, e com `DELETE` (só em `contact_endpoints`) | — | *proposta* (emenda 1.8, KAM-008). É com ele que o módulo de identidade resolve, funde, roda e apaga contactos, um tenant de cada vez (não contorna a RLS). `kamba_app` lê de `contacts` só `contact_id`, `tenant_id`, `criado_at`, `erased_at`, `merged_into` e `merged_at`, e não escreve em nenhuma tabela de identidade; `kamba_batch` e `kamba_resolver` não lhes tocam. O bloco do KAM-008 nomeava-o e este parágrafo não o listava (linha 3 do KAM-141) |
| Vertical | No registo (`registry/*.yaml`): `id` ∈ {`vendedor`, `servicos`, `catalogo`, `social`, `orcamento`}. Em `tenant_channels.vertical`: só as de **atendimento** (`vendedor`, `servicos`). A **persona** `dono` é resolvida pelo CHR a partir de `contacts.papel` e agrega os módulos de entrada; os módulos activos de um tenant vivem em `entitlements.modulo` | «persona» usada como sinónimo de vertical | `../docs/tecnica/00 §11` (Terminologia) |

### 3.3 Comércio

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Preço | `preco_minor` + `preco_tipo` ∈ {`fixo`, `a_partir_de`, `sob_consulta`} | `preco_kz`, `'exato'` | O validador (KAM-032) usa o tipo para não citar «a partir de» como fixo |
| Stock | `stock_modo` ∈ {`garantido`, `indicativo`, `confirmar_dono`} | `p.stock>0` | Itens `confirmar_dono` exigem confirmação do dono (KAM-046) |
| Encomenda (estados) | `criada`, `aguarda_pagamento`, `pendente_confirmacao`, `paga`, `expirada`, `em_entrega`, `entrega_falhada`, `entregue`, `em_disputa`, `reembolso_pendente`, `reembolsada`, `cancelada` | Máquina incompleta em `../docs/tecnica/03 §6.1` | Fonte: `../docs/tecnica/00 §6.1` |
| Total da encomenda | `total_minor` | `total_kz` | — |
| Identificador de confirmação | `confirm:{cart_id}` (Vendedor), `confirm:{hold_id}` (Serviços), `confirm:{item_id}` (módulos de entrada: conteúdo, proposta, publicação de produto; *proposta*) | `confirm:{cart_id}` para ambos | Embutido no botão |
| Marcação | `bookings(booking_id, tenant_id, contact_id, service_id, resource_id, inicio_at, fim_at, estado, hold_id)` | — | Detalhe em KAM-047 |

### 3.4 Pagamentos

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Valor | `valor_minor` | `valor_kz` | — |
| Autenticação do evento | `payment_events.authn_ok boolean` + `authn_method` ∈ {`hmac`, `manual`, `consulta`} | `callback_hmac_ok`, `sig_ok` | O `ManualProvider` não tem HMAC: `authn_method='manual'` com actor humano registado |
| Eventos de pagamento | `payment.confirmed` (facilitador autenticado) e `payment.manual_confirmed` (`ManualProvider`) | `../docs/tecnica/04 §4.1` usa `payment.confirmed` para ambos | **Dois eventos distintos**; consumidores que não distinguem subscrevem ambos |
| Unicidade do ledger | Conforme `../docs/tecnica/04` (inclui `account_id`, tipo de evento e sequência); **não** `UNIQUE(provider, referencia)` | Dedup `db.seen(provider, ev.reference)` em `../docs/tecnica/08` §4.5 (localização a confirmar em KAM-111) | O ledger é append-only: o mesmo `referencia` tem várias linhas |
| Replay | Idempotência por `(provider, account_id, referencia)`; timestamp assinado só se o facilitador o fornecer | «replay ±5 min» | `../docs/tecnica/00` §4 (GWY) |
| Beneficiário | `beneficiary_kind` ∈ {`pme`, `plataforma_receita_propria`} | — | O billing da KAMBÁ não activa o tenant `platform` |

### 3.5 Eventos

| Conceito | Nome canónico | Nota |
|---|---|---|
| Envelope | `id`, `tipo`, `versao`, `tenant_id`, `agregado`, `seq`, `trace_id`, `ocorrido_em`, `payload` | `seq` por agregado (ordenação); versões desconhecidas **falham de forma visível** (nunca ignoradas em silêncio) |
| Tipos do Piloto | `channel.inactivity_warning`, `order.created`, `order.expired`, `order.delivered`, `payment.confirmed`, `payment.manual_confirmed`, `booking.created`, `booking.reminder_due`, `booking.cancelled`, `stock.low`, `review.created`, `query.unresolved`, `tenant.approved`, `tenant.provisioned`, `tenant.activated`, `channel.updated`, `contact.merged`, `conversation.mode_changed` | Os últimos sete são acrescentados ao catálogo de `../docs/tecnica/06 §5` (KAM-007) |
| Gatilho do provisioning | `tenant.approved` | Não `tenant.activated` (`../docs/tecnica/01`, `02`, `03`, `06` a actualizar) |
| Evento do gate da Fase 0 | Um pedido do Vendedor pago via `ManualProvider` emite `payment.manual_confirmed`; a vertical **Serviços** consome-o e confirma uma marcação com sinal (KAM-039, KAM-108) | `servicos.yaml` subscreve **ambos** os eventos de pagamento |
| Consumidores | Idempotentes por `(consumer, event_id)`; DLQ após 5 tentativas | — |
| Outbox transaccional | `events_outbox(id, event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, agregado_seq, particao, envelope, criado_at, publicado_at, tentativas, proxima_tentativa_at)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.1. O `events_outbox.tenant_id` é `NOT NULL` (§3.2). O `id` é `bigint` de identidade e não `uuid`: é a ordem de escrita que o publicador varre, e a chave de idempotência é o `event_id` (UUIDv7). Excepção consciente à convenção de chaves do §2 |
| Sequência por agregado | `evt_agregado_seq(tenant_id, agregado_tipo, agregado_id, seq)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.1 **com um desvio**: o documento não tem `tenant_id` e o contador fica global, o que deixava um tenant cortar a emissão de eventos de outro (ANALISE-20, achado 2). Com o `tenant_id` na chave, na política `tenant_iso` e na unicidade do triplo de `events_outbox`, o espaço de `seq` é por tenant |
| Subscrições de entrega | `evt_subscricoes(consumer, tipo, versao_max, finalidade, exige_ordem, activo)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.1. O publicador entrega a uma subscrição activa só se a sua `finalidade` estiver em `envelope.finalidades` (§7.3) |
| Arquivo de eventos | `events_log(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, agregado_seq, ocorrido_em, registado_em, classe_pii, envelope)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.5. Particionado por mês em `ocorrido_em`, imutável (nenhum papel de serviço tem `UPDATE` nem `DELETE`) |
| Partição DEFAULT do arquivo | `events_log_default` | *proposta* (emenda 1.9, KAM-005). As partições mensais têm nome com data e nascem de um *job*; a `DEFAULT` é a única que uma migração pode criar sem fixar o calendário, e é a rede quando o *job* não corre |
| Emissão de um evento | `evt_emitir` | *proposta* (emenda 1.9, KAM-005). A função que o produtor chama na sua própria transacção (`../docs/tecnica/06` §6.1). `SECURITY INVOKER`: a política `tenant_iso` do outbox continua a valer |
| Campos do envelope que o §6.1 acrescenta | `registado_em`, `produtor`, `correlacao_id`, `causa_id`, `classe_pii`, `finalidades` | *proposta* (emenda 1.9, KAM-005). O `jsonb_build_object` de `evt_emitir` constrói **14** chaves de topo e a linha «Envelope», acima, nomeia 9 nomes — dos quais `seq` não é de topo, pelo que são 8 de topo mais estes 6. Estes seis são os que faltavam, e entram porque são **colunas** do `events_log` e chaves do `envelope` que o DDL escreve. **O que fica por decidir:** se o contrato v1 publicado em `contratos/eventos/` (KAM-007) tem 9 ou 14 campos de topo, e se o `seq` vive no topo ou dentro de `agregado` — aqui a leitura é que a linha «Envelope» é uma lista de **nomes** e não de aninhamento, e que `agregado = {tipo, id, seq}` usa os dois. A decisão é de quem aprova emendas |

### 3.6 Runtime, LLM e dados derivados

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Registo de chamadas LLM | `llm_call_log` | `llm_calls` | Sem conteúdo de mensagens |
| Esquema do checkpointer | `lg` | — | Role próprio |
| Esquemas | `platform`, `lg`, `idx`, `servicos`, esquemas do Medusa | — | RLS também em `idx.*` (KAM-061) |
| Retenção de `assistant_queries` | 12 meses (*proposta*; a confirmar por parecer) | 12 (`../docs/tecnica/08`) vs 13 (`../docs/tecnica/06`) | Minimização |
| Coordenadas | Arredondadas à zona; exactas só no pedido de entrega (Clusters) | lat/lng exactos em `assistant_queries` | — |

### 3.7 Módulos de entrada (ADR-020, *proposta*)

| Conceito | Nome | Ticket |
|---|---|---|
| Papel do contacto | `contacts.papel` ∈ {`cliente`, `dono`} | KAM-118 |
| Persona do dono | `dono` (Assistente do Dono) | KAM-118 |
| Ferramenta de imagem | `foto` (tool `enhance_image`), interface `ImageProvider` | KAM-120 |
| Trabalhos de imagem | `image_jobs` | KAM-120 |
| Perfil de marca, calendário e itens de conteúdo | `brand_profile`, `content_calendar`, `content_items` | KAM-121, KAM-122 |
| Pedidos de orçamento | `quote_requests`; fact `quote_price` | KAM-123 |
| Entitlements de módulo | `modulo` ∈ {`catalogo`, `foto`, `social`, `orcamento`} com limites `imagens_mes`, `posts_mes`, `orcamentos_mes` | KAM-124 |
| Eventos | `quote.requested`, `quote.sent`, `content.approved` | KAM-123, KAM-122 |

### 3.8 Nomes introduzidos pelos tickets KAM-111 a KAM-117 (*proposta*, a ratificar por emenda)

| Conceito | Nome | Ticket |
|---|---|---|
| Avisos ao dono por canal alternativo | `owner_notices` | KAM-115 |
| Decisões do modo concierge (aprovado, editado, rejeitado) | `draft_decisions` e política `concierge` | KAM-114 |
| Edição livre de número no rascunho do concierge | `edicao_numero_livre` | KAM-114 |
| Vistas de churn e tenants dormentes | `v_churn_signals`, `v_tenant_dormente` | KAM-117 |
| Evento de aviso de inactividade do canal | `channel.inactivity_warning` | KAM-017 |

Sem esta emenda, o lint de KAM-111 rejeitá-los-ia; a ratificação faz-se numa linha do §6.

### 3.9 Nomes introduzidos pelo ticket KAM-010 — segredos (*proposta*, a ratificar por emenda)

Nenhum destes nomes é uma tabela ou uma coluna: são a referência com que o código
pede um segredo e os campos do inventário máquina-legível. Entram aqui porque
**seis tickets os herdam** — KAM-008, KAM-013, KAM-016, KAM-030, KAM-056 e
KAM-072 consomem esta porta — e um nome que seis tickets usam sem estar no
dicionário é a divergência que o §4 de `01_Engineering_Standards_e_Handoff.md`
existe para apanhar.

| Conceito | Nome | Ticket |
|---|---|---|
| Referência opaca a um segredo no cofre | `SecretRef`: `<id>` ou `<id>/<instância>` | KAM-010 |
| Porta de leitura de segredos | `SecretProvider` com `get`, `getRing`, `versions`, `health` | KAM-010 |
| Par de versões vivas de um segredo | *anel*; `getRing` devolve `[actual, anterior]`, com `anterior` nulo quando nunca houve rotação | KAM-010 |
| Inventário de segredos | `ops/secrets-inventory.yaml`, com `id`, `owner`, `rotacao_dias`, `rotacao_gatilho`, `ambientes`, `obrigatorio_em`, `consumidores`, `instancias`, `anel`, `kid` | KAM-010 |
| Papéis responsáveis (`owner`) | `seguranca`, `eng_canais`, `eng_runtime`, `eng_pagamentos`, `sre`, `privacidade` (de `../docs/tecnica/08` §1.3) | KAM-010 |
| Endereçamento de instâncias (`instancias`) | `nenhuma`, `tenant`, `provedor`, `conta`, `epoca` | KAM-010; `epoca` (a instância é o mês `YYYYMM`) é *proposta* da emenda 1.8, KAM-008 |
| Variável de ambiente de um segredo | `KAMBA_SECRET_<ID>` e `KAMBA_SECRET_<ID>_ANTERIOR` (ADR-L002) | KAM-010 |
| `id` dos segredos do `../docs/tecnica/08` §5 | `meta_app_secret`, `meta_verify_token`, `meta_client_token`, `kek_token_cliente`, `meta_pin_2fa`, `proxypay_api_key`, `appypay_client_secret`, `litellm_master_key`, `litellm_virtual_key`, `llm_provider_key`, `stt_provider_key`, `db_app_password`, `db_migrator_password`, `db_batch_password`, `pepper_contact_hmac`, `chatwoot_platform_token`, `chatwoot_bot_token`, `vpn_wireguard_admin`, `doppler_service_token` | KAM-010 |
| `id` dos segredos de identidade de contacto | `db_identity_password`, `kek_contact_dek`, `sujeito_epoch_key` | KAM-008 (*proposta*, emenda 1.8). O `../docs/tecnica/08` §5 não tem linha para a KEK das DEK de contacto nem para as chaves de época do `sujeito_ref` |

**A costura com o KAM-003.** O KAM-010 **não** define `tenant_channels.token_ref`:
define que o que lá se guarda é uma `SecretRef` — texto opaco, nunca o token — e
que quem a lê não a interpreta (não a parte, não deriva `tenant_id` dela). A
coluna é do KAM-003.

**Porque é que esta é a §3.9 e não a §3.8.** A §3.8 é, pelo título, dos tickets
KAM-111 a KAM-117. A linha 1.1 do §6 chama-lhe «§3.7», que é a numeração que ela
tinha antes de a §3.7 (módulos de entrada, ADR-020) ser inserida à frente: a
renumeração não chegou ao registo de versões. Essa divergência fica registada
aqui e não se corrige neste ticket, porque a §3.2 e o `INDICE.md` estão a ser
emendados por outras sessões em paralelo.

### 3.10 Nomes introduzidos pelo ticket KAM-068 — logs (*proposta*, a ratificar por emenda)

Nenhum destes nomes é uma tabela ou uma coluna: são os campos de uma linha de
*log* e as métricas do *logger*. Entram aqui porque **todos os serviços os
escrevem** e porque o KAM-013, o KAM-080 e o KAM-112 os consomem. Os doze campos
não são escolha deste ticket: são a *allowlist* de `../docs/tecnica/08` §7.3, que o
dicionário não tinha. A forma de cada valor, os motivos de rejeição e o processo
para acrescentar um campo estão em `../docs/logs.md`.

| Conceito | Nome | Ticket |
|---|---|---|
| Campos de uma linha de *log* (lista fechada; um campo novo é um PR revisto pelo Responsável de Segurança) | `ts`, `level`, `svc`, `tenant_id`, `contact_hmac_prefix`, `turn_id`, `msg_id`, `wa_type`, `latency_ms`, `tool`, `outcome`, `error_code` | KAM-068 |
| Campos recusados pelo *logger* (contador; o sufixo é o motivo) | `log_field_rejected_total` | KAM-068 |
| Linhas que o *logger* não conseguiu escrever (contador) | `log_write_failed_total` | KAM-068 |
| Variável de ambiente do modo estrito do *logger* (só em testes) | `KAMBA_LOG_ESTRITO` | KAM-068 |
| Identificador externo em forma registável (um `wamid`, um `event_id`): `m_` mais 32 hexadecimais do SHA-256 | `id_opaco` | KAM-068 |

**O que esta secção NÃO decide.** `contact_hmac_prefix` é o nome de `../docs/tecnica/08`
§7.3; se o desenho final de identidade (KAM-008) preferir outro identificador
pseudónimo, a troca é uma emenda a esta linha e um PR à *allowlist*, como o
próprio ticket prevê. O comprimento do prefixo (8 hexadecimais) é *proposta* do
KAM-068, em `../docs/logs.md` §2.

**Um efeito lateral a conhecer.** O *gate* 3b não sabe o tipo de um nome
(`../docs/ci.md` §7, lacuna 20): ao entrarem aqui, `ts`, `level`, `svc`, `tool` e
`outcome` passam a ser aceites também como nome de coluna numa migração. Não
torna nenhum DDL existente válido ou inválido; fica dito para quem fechar essa
lacuna (KAM-141).

### 3.11 Nomes introduzidos pelo ticket KAM-011 — armazenamento de objectos (*proposta*, a ratificar por emenda)

Nenhum destes nomes é uma tabela ou uma coluna: são a porta de armazenamento, a
forma da chave de um objecto e a configuração que diz para onde os bytes vão.
Entram aqui porque **cinco tickets os herdam** — KAM-020, KAM-071, KAM-087,
KAM-098 e KAM-120 são bloqueados pelo KAM-011 — e porque a chave de um objecto
é persistida por quem a recebe (`media_assets`, no KAM-020).

| Conceito | Nome | Ticket |
|---|---|---|
| Porta de armazenamento de objectos | `StorageProvider`, com `signUrl` e as operações de escrita, leitura, metadados, eliminação e listagem; toda a operação leva o tenant do contexto | KAM-011 |
| Chave de um objecto | `ObjectKey`, na forma `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}`: tenant em UUID canónico minúsculo, ano e mês em UTC, identificador aleatório | KAM-011 |
| Referência a um objecto guardado | `ObjectRef`: a chave, o tamanho em bytes e a soma SHA-256 do conteúdo; é o que um consumidor persiste, nunca uma URL | KAM-011 |
| Prazo a partir do qual um objecto pode ser purgado | `retain_until`, metadado obrigatório de todo o objecto; no servidor S3 vai como metadado do utilizador «retain-until» (com hífen: é um cabeçalho HTTP), em UTC | KAM-011 |
| Destino dos dados do armazenamento | `destino.country` (ISO 3166-1 alfa-2), `destino.provider` e `apd_ref`, com os nomes das colunas da tabela de destinos do KAM-069 | KAM-011 |
| Variáveis de configuração do armazenamento | `KAMBA_STORAGE_ENDPOINT`, `KAMBA_STORAGE_BUCKET`, `KAMBA_STORAGE_REGION`, `KAMBA_STORAGE_DESTINO_COUNTRY`, `KAMBA_STORAGE_DESTINO_PROVIDER`, `KAMBA_STORAGE_DESTINO_APD_REF` | KAM-011 |
| `id` dos segredos do armazenamento | `storage_access_key_id`, `storage_secret_access_key` | KAM-011 |

**O que fica de fora, de propósito.** A *lista* de classes de objecto não é do
KAM-011: o módulo fixa só a forma de uma classe (`snake_case`, 2 a 32
caracteres), e cada consumidor traz as suas — com a política de retenção por
classe no KAM-071. E o nome do fornecedor (`destino.provider`) é um
identificador livre: a decisão D6 continua aberta, e nenhum valor dele está
fixado aqui.

**Uma divergência que este ticket encontrou e não resolve.** O bloco do KAM-020
escreve a chave como `t/{tenant_id}/media/{classe}/{aaaa}/{mm}/{uuid}`, com um
segmento `media/` que a forma do KAM-011 não tem. A porta implementa a forma
desta tabela, que é a do critério de aceitação do KAM-011; **qual das duas
fica é uma decisão por ratificar**, como tudo nesta secção, e a porta recusa
hoje a forma do KAM-020. Está em `../docs/dividas-documentais.md`, linha 8.

## 4. Itens que continuam por decidir

| Item | Estado | Ticket |
|---|---|---|
| Estados exactos de `tenant_channels` | por definir | KAM-014 |
| Esquema do ledger (colunas finais, função de INSERT) | por ratificar com `../docs/tecnica/04` | KAM-053 |
| Contrato `v_oferta_viva` | por definir | KAM-051 |
| Prazo de retenção fiscal (CGT) | NÃO VERIFICADO | KAM-071 |
| Esquema de `servicos` (proposto por KAM-047) | a ratificar | KAM-047 |

## 5. Manutenção

Qualquer alteração a um nome canónico é uma emenda a este documento (linha em §6) e propaga-se aos tickets e a `../docs/tecnica/` por KAM-111. O lint de KAM-111 compara DDL, schemas de eventos e contratos de tools com as tabelas do §3.

## 6. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial como proposta: reconciliação das divergências encontradas na redacção dos epics. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | §3.7: nomes introduzidos pelos tickets KAM-111 a KAM-117; localização da divergência do ledger. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | **Emenda (Carta §6 ponto 4).** §3.2: oito nomes do schema `platform` que o KAM-003 precisa e o dicionário não tinha — chave de `tenants`, `tenants.tipo`, estados do canal, `origem`, `channel_mode`, tabela `entitlements` e papéis de base de dados. Resolve a inversão KAM-003↔KAM-014 (estados do canal) e a divergência `kamba_ops`/`kamba_batch`. Escrita porque a dependência `KAM-003←KAM-111` foi dispensada: sem estas entradas, o primeiro DDL nasceria com nomes fora do dicionário, que o §1 declara defeito. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | §3.9: nomes do KAM-010 (porta de segredos, inventário, `SecretRef`, variáveis `KAMBA_SECRET_*`). | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | §3.2: privilégios de `kamba_app` (sem `DELETE`, `UPDATE` por coluna) e forma das chaves de configuração em colunas, depois da revisão adversarial do KAM-003. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | §3.2: contexto de tenant na base (`app.tenant_id`), política `tenant_iso` e papel `kamba_resolver` (KAM-004). Regista a divergência de nome com `../docs/tecnica/03` §5.5 (`tenant_isolamento`). | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | §3.10: campos de uma linha de *log* (a *allowlist* de `../docs/tecnica/08` §7.3), métricas e variável do *logger*, e o identificador opaco de mensagem (KAM-068). | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | §3.11: nomes do KAM-011 (porta `StorageProvider`, forma da chave de objecto, `ObjectRef`, `retain_until`, destino do armazenamento, variáveis `KAMBA_STORAGE_*` e os dois segredos). Regista a divergência de forma de chave com o bloco do KAM-020. | Equipa KAMBÁ |
| 1.8 | Outubro 2026 | **Emenda (*proposta*), KAM-008.** §3.1: onde vive o HMAC de pesquisa (`contact_endpoints.bsuid_hmac`, `contacts.phone_hmac`, `hmac_kid`), com `lookup_hmac` registado como variante; `contact_deks` e `hmac_key_versions`. §3.2: papel `kamba_identity`. §3.9: instância `epoca` e os três `id` de segredos de identidade. **Decide a linha 3 do KAM-141** (dicionário contra o bloco do KAM-008) a favor do dicionário; a decisão é de quem aprova emendas e fica por ratificar. | Equipa KAMBÁ |
| 1.9 | Outubro 2026 | **Emenda (*proposta*), KAM-005.** §3.5: as quatro tabelas de eventos (`events_outbox`, `evt_agregado_seq`, `evt_subscricoes`, `events_log`), a partição `events_log_default`, a função `evt_emitir` e os seis campos que o `jsonb_build_object` do `../docs/tecnica/06` §6.1 acrescenta ao envelope (14 chaves de topo em total) (`registado_em`, `produtor`, `correlacao_id`, `causa_id`, `classe_pii`, `finalidades`). Entram porque são DDL que o KAM-005 escreve e o §1 declara defeito um nome fora deste dicionário. **Fica por decidir** se o contrato v1 publicado (KAM-007) tem 9 ou 14 campos de topo; a decisão é de quem aprova emendas. A contagem é 14 e não 13 — corrigida depois da revisão adversarial (ANALISE-20, achado 8), que apanhou o número errado nesta linha enquanto o DDL e os testes diziam 14. | Equipa KAMBÁ |
