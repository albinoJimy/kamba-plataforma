# Dicionário de Dados Canónico — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Foundation — Dicionário de Dados Canónico |
| Versão | 1.44 — **PROPOSTA** (a do §6; o cabeçalho ficou em 1.0 durante treze emendas, e é a linha 7 do KAM-141) |
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
| Tempo | `timestamptz` em UTC; sufixo `_at` (`criadoEm` (o código escreve-o assim, e o dicionário fixa esta forma: `criado_at` não é a transformação *camelCase* de nada), `pago_at`); apresentação em `Africa/Luanda` |
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
| Prova de consentimento | `consent_event` (append-only) | `consent_log`, `consent_ledger`, `consents` | Campos: `tenant_id`, `contact_id`, `purpose`, `text_version`, `accepted`, `canal`, `evidence_hash`, `ocorrido_em`. O domínio de `purpose` está na linha abaixo |
| Finalidade do consentimento | `consent_event.purpose` ∈ {`transacao`, `atendimento`, `marketing`, `analytics_agregado`, `melhoria_servico`, `sugestoes_patrocinadas`, `partilha_loja`, `partilha_parceiros`, `partilha_estafeta`, `notificacao_dono`} | — (ver a nota) | *proposta* (emenda 1.16, KAM-159). É a **união** das duas listas que existiam: as cinco deste dicionário e as oito dos 38 contratos publicados, que se cruzavam **numa só**. Decisão do fundador, 2026-10-18. **A base legal de cada uma não está fixada**: das dez, só `marketing` tem fonte directa e CONFIRMADA no `E3` — é KAM-104, e está no §4. **`transaccao` e `melhoria` não entram na coluna «Substitui», e isso é deliberado**: são palavras portuguesas correntes — a transacção de uma base de dados, a melhoria de um serviço — e registando-as o *gate* 3b passava a assinalar **prosa**. Medido: 15 achados, nenhum deles um identificador. As ocorrências que eram mesmo identificadores foram corrigidas |
| Chave de conversa | `thread_id = {tenant_id}:{contact_id}` | `msisdn_hash+tenant` | — |

### 3.2 Tenants e canais

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Estado do tenant | `onboarding`, `ativo`, `restrito`, `suspenso`, `encerrado` | `tenants.estado` sem `restrito` (`../docs/tecnica/03`) | `restrito` = limitação **imposta pela Meta** (quality rating); `suspenso` = decisão nossa. Ver `../docs/tecnica/00 §6.2` |
| Fase do onboarding | `onboarding_case.fase`: `kyc_pendente`, `aprovado`, `provisionando`, `aguarda_es`, `aguarda_catalogo`, `pronto` | — | Sub-estados do `onboarding`, não estados do tenant |
| Pré-alocação do tenant | `onboarding_case.tenant_id` criado no registo | — | O `events_outbox.tenant_id` é `NOT NULL` |
| Entitlement (chaves) | `msgs_ai_mes`, `marcacoes_mes`, `imagens_mes`, `posts_mes`, `orcamentos_mes`, `valor_max_pedido_minor` (limite do plano e do tecto K1/K2), `manual_max_minor` (limite do `ManualProvider`), `manual_daily_max_minor`, `manual_max_por_contacto_24h`, `manual_dupla_acima_minor` | `valor_max_pedido_kz` | Limite efectivo de um pedido = **mínimo** de `valor_max_pedido_minor` e, se `ManualProvider`, `manual_max_minor`. **A coluna «Substitui» tinha `manual_max_minor`, que é o nome canónico desta mesma linha** (emenda 1.13, KAM-007 linha 1): o gate tratava-o como canónico e avisava em cada execução. Era lapso de transcrição, não escolha — por simetria com `valor_max_pedido_kz` a forma antiga seria `manual_max_kz`, que **documento nenhum escreve**, pelo que não se regista uma variante sem sujeito. **As três últimas entram na emenda 1.17 (KAM-009)**: estavam em `../docs/tecnica/04` §4.2 (M-3 e M-5) desde sempre, e o mesmo §4.2 diz em M-10 que os valores ficam «registados em `entitlements`» — logo são chaves de `limites` e não parâmetros de outro sítio. Não entraram aqui por lapso de transcrição, e a falta era a mesma classe do KAM-159 ao contrário: um documento técnico a nomear o que o canon não declara. O registo de chaves do KAM-009 **rejeita na escrita** o que não esteja nesta linha, pelo que deixá-las de fora tornava M-3 e M-5 impossíveis de implementar |
| Tenant (tabela e chave) | `platform.tenants(id uuid)` — a chave primária chama-se **`id`**, não `tenant_id` | — | *proposta* (emenda 1.2, KAM-003). A convenção `contacts(contact_id, …)` aplica-se à coluna que **referencia** um tenant nas tabelas de negócio, não à chave da própria tabela. `../docs/tecnica/03` §5.2 e as quinze tabelas de dinheiro de `../docs/tecnica/04` já escrevem `REFERENCES platform.tenants(id)`, e o KAM-004 assume `id = app.tenant_id`: escolher `tenant_id` custaria um `ALTER` em cascata por todo o doc 04 |
| Tipo de tenant | `tenants.tipo` ∈ {`pme`, `courier`, `reseller`, `agent`, `platform`} | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/03` §5.2. O valor `platform` é o que a guarda do ADR-011 recusa em produção do Piloto |
| Canal | `tenant_channels(tenant_id, phone_number_id, waba_id, vertical, estado, …)` | — | Estados do canal: ver a linha seguinte |
| Estado do canal | `pendente`, `ativo`, `restrito`, `desligado`, `suspenso`, `encerrado` | `tenant_channels.estado` com três estados (`../docs/tecnica/03` §5.2) | *proposta* (emenda 1.2). **Definidos em KAM-003 e não em KAM-014**, ao contrário do que esta linha dizia: o KAM-014 depende do KAM-003, pelo que mandar o DDL esperar por ele era uma inversão de dependência. Os seis vêm de `../docs/tecnica/01` §7.1; o KAM-014 herda-os |
| Origem do canal | `tenant_channels.origem` ∈ {`pme`, `plataforma`} | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/01` §7.1. `plataforma` é Fluxo B, recusado em produção do Piloto (ADR-011) |
| Modo do canal | `tenant_channels.channel_mode` ∈ {`coexistencia`, `cloud_only`} | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/01` §7.1 |
| Entitlement (tabela) | `entitlements(tenant_id, modulo, limites jsonb, ativo boolean)`, chave `(tenant_id, modulo)` | — | *proposta* (emenda 1.2, KAM-003), de `../docs/tecnica/03` §5.2. As **chaves** de `limites` estão na linha «Entitlement (chaves)»; os valores de `modulo` em §3.7 |
| Papéis de base de dados | `kamba_migrator` (DDL, dono das tabelas), `kamba_app` (`NOBYPASSRLS`, sem DDL), `kamba_batch` (`BYPASSRLS`, auditado), `kamba_agr` (`NOBYPASSRLS`, so o esquema `lg`; KAM-026, §3.25) | `kamba_ops` (`../docs/tecnica/03` §5.5, `../docs/tecnica/04` §6) | *proposta* (emenda 1.2, KAM-003). Resolve-se a favor de `../docs/tecnica/08` §3.3, que é o documento de isolamento e a autoridade sobre papéis. O `REVOKE … FROM PUBLIC, kamba_app, kamba_ops` de `../docs/tecnica/04` revoga de um papel que não existirá — divergência a corrigir, **não** coberta pelas 12 do KAM-111 |
| Privilégios de `kamba_app` | `SELECT` e `INSERT` por tabela; `UPDATE` **por coluna**; **sem `DELETE`** em tabela nenhuma de `platform` | `SELECT/INSERT/UPDATE/DELETE` igual a `kamba_batch` (primeira versão do KAM-003) | *proposta* (emenda 1.4, KAM-003). O §2 já diz «soft delete: estado, nunca DELETE»; quem apaga é o `kamba_batch`. Colunas que `kamba_app` não altera depois do *insert*: `tenants.tipo` e `tenant_channels.origem` (a costura do Fluxo B — com `UPDATE` livre, um tenant `platform` passava a `pme` e saía da vista da guarda do ADR-011), `tenant_channels.tenant_id` (mover um canal de tenant), e as chaves e `criado_at`. **Decidido na emenda 1.17 (KAM-009), e não a favor do que estava.** `kamba_app` perde o `UPDATE` sobre `tenants.plano` e sobre `entitlements(limites, ativo)`. A razão é a política de `tenants`, que é por `id = app.tenant_id` (KAM-004): com esses privilégios **um contexto de tenant subia o próprio plano e os próprios limites**, e os limites são a única coisa entre um tenant e o tecto de dinheiro por pedido (ADR-013, ADR-015). Quem os altera é o `kamba_batch` — provisionamento (KAM-091) e cobrança (KAM-059) são de retaguarda e já lá correm. **A emenda 1.18 acrescenta-lhe o `INSERT` em `entitlements` e o `UPDATE` sobre `tenants.estado`**, pela revisão adversarial: revogar o `UPDATE` e deixar o `INSERT` fechava um verbo e não a escalada — com `WITH CHECK (tenant_id = app.tenant_id)` um tenant **cria** a própria linha de entitlement com o tecto que quiser —, e o `estado` é a condição do critério 2 nas mãos do sujeito dela. **`verificado_at` fica como está**, e volta ao §4 com dono: acompanha o onboarding e não é entrada de decisão nenhuma |
| Uso de entitlement (tabelas) | `tenant_usage(tenant_id, chave_limite, periodo, valor, actualizado_at)`, chave `(tenant_id, chave_limite, periodo)`; `usage_ledger(tenant_id, idempotency_key, chave_limite, periodo, quantidade, criado_at)`, chave `(tenant_id, chave_limite, idempotency_key)` | — | *proposta* (emenda 1.17, KAM-009). **Nenhum documento técnico tinha onde fica o consumo**: o `../docs/tecnica/03` §5.2 dá `entitlements`, que guarda o **tecto**, e mais nada. A `tenant_usage` é o contador por período; a `usage_ledger` é o que torna o consumo idempotente — a chave única é o que recusa a segunda chamada, e não uma leitura prévia. O bloco do KAM-009 esboça `(tenant_id, key, …)` e `n`: `key` ao lado de `idempotency_key` **não diz de que chave se trata**, e `n` não é um nome; o esboço do §Detalhes é fonte 6 e este documento é fonte 3 |
| Período de uso | `tenant_usage.periodo date` — o **primeiro dia do mês** em `Africa/Luanda` | — | *proposta* (emenda 1.17, KAM-009). O fuso é a constante e **não** a coluna de fuso horário que a `0001` deu a cada tenant (escrita aqui sem crase de propósito: pô-la em crase fá-la-ia nome canónico desta secção, e ela já é extensão declarada em `../canon/extensoes.yaml`). O critério do ticket fixa `Africa/Luanda` e nenhum documento diz que o período de facturação segue o fuso do tenant. Fica dito para que a diferença seja uma decisão e não uma surpresa no dia em que houver um tenant noutro fuso |
| Forma das chaves de configuração em colunas | `tenant_channels.vertical`, `entitlements.modulo` e `tenants.plano`: `^[a-z][a-z0-9_]*$` | texto livre | *proposta* (emenda 1.4, KAM-003). `CHECK` de **forma**, não de domínio: as verticais e os módulos são configuração (ADR-012), mas o §2 já fixa minúsculas e `snake_case`. Sem ele, `'Assistente'` e `' assistente'` entravam na coluna com uma forma que nenhuma comparação previa. **`tenants.plano` junta-se na emenda 1.17 (KAM-009)**, e junta-se aqui e não a um domínio fechado por uma razão de mecânica: o *gate* 3b exige o `CHECK` de um domínio **na revisão que cria a coluna**, e essa é a `0001`, fundida — fixar o domínio aqui punha vermelha uma revisão que ninguém vai reescrever. Os planos vivem em `registry/plans.yaml`, que é configuração como as verticais, e é lá que a lista fechada se impõe; a coluna ganha o `CHECK` de forma na `0007` |
| Contexto de tenant na base | variável `app.tenant_id`, definida com `set_config('app.tenant_id', <uuid>, true)` — local à transacção | `SET` de sessão | *proposta* (emenda 1.5, KAM-004), de `../docs/tecnica/08` §3.3. Só pelos *helpers* de `tenant_guard` (`tx`/`comTenant`); nunca à mão |
| Política de isolamento | `tenant_iso` (USING e WITH CHECK), criada por `rls.enable_tenant_rls` | `tenant_isolamento` (`../docs/tecnica/03` §5.5) | *proposta* (emenda 1.5, KAM-004). O nome é o de `../docs/tecnica/08` §3.3 e do ticket. Em `tenants` a coluna da política é `id`; nas outras, `tenant_id` |
| Papel do resolvedor | `kamba_resolver` — `NOBYPASSRLS`; política própria `resolver_leitura` (`FOR SELECT … USING (true)`); `SELECT` só em `tenant_channels(id, tenant_id, phone_number_id, vertical, origem, estado, channel_mode)` e `tenants(id, tipo, estado)` | «papel estreito» sem nome (`../docs/tecnica/03` §5.5) | *proposta* (emenda 1.5, KAM-004). Resolve `phone_number_id → tenant` antes de haver contexto, e é **o papel com que corre a guarda de arranque do ADR-011**. As colunas são as mínimas para hoje e revêem-se no KAM-014 |
| Papel de identidade | `kamba_identity` — `NOBYPASSRLS`; o único papel de serviço com `SELECT` em `contact_endpoints` e `contact_deks`, e com `DELETE` (só em `contact_endpoints`) | — | *proposta* (emenda 1.8, KAM-008). É com ele que o módulo de identidade resolve, funde, roda e apaga contactos, um tenant de cada vez (não contorna a RLS). `kamba_app` lê de `contacts` só `contact_id`, `tenant_id`, `criado_at`, `erased_at`, `merged_into` e `merged_at`, e não escreve em nenhuma tabela de identidade; `kamba_batch` e `kamba_resolver` não lhes tocam. O bloco do KAM-008 nomeava-o e este parágrafo não o listava (linha 3 do KAM-141) |
| Vertical | No registo (`registry/*.yaml`): `id` ∈ {`vendedor`, `servicos`, `catalogo`, `social`, `orcamento`}. Em `tenant_channels.vertical`: só as de **atendimento** (`vendedor`, `servicos`). A **persona** `dono` é resolvida pelo CHR a partir de `contacts.papel` e agrega os módulos de entrada; os módulos activos de um tenant vivem em `entitlements.modulo` | «persona» usada como sinónimo de vertical | `../docs/tecnica/00 §11` (Terminologia) |
| Registo de auditoria | `audit_log(id, criado_at, tenant_id, actor_type, actor_id, action, entity, entity_id, turn_id, payload_hash, prev_hash, row_hash)` | — | *proposta* (emenda 1.14, KAM-012). Forma do `../docs/tecnica/08` §6, com **duas** diferenças: a coluna de tempo é `criado_at` e não ts, pelo §2 («sufixo `_at`»); **ts não entra na coluna «Substitui»** porque é nome canónico de campo de *log* no §3.10, e registá-lo aqui criava uma contradição do tipo que a emenda 1.13 acabou de fechar — a divergência é só nesta tabela e diz-se aqui, e o `tenant_id` é **nulável** — as acções de plataforma têm cadeia própria, e é a excepção à regra multi-tenant do §2, declarada em `../ci/rls_exceptions.yaml`. *Append-only*: `REVOKE UPDATE, DELETE, TRUNCATE` **e** um *trigger*, porque o `REVOKE` não prende o dono da tabela (medido) |
| Ator de uma linha de auditoria | `actor_type` ∈ {`contact`, `owner`, `staff`, `agent`, `system`} | — | *proposta* (emenda 1.14, KAM-012). Do `../docs/tecnica/08` §6 |
| Acções auditadas | `action` ∈ {`price.update`, `stock.adjust`, `payment.manual_confirm`, `access.conversation`, `batch.run`, `breakglass.open`, `audit.read`} | — | *proposta* (emenda 1.14, KAM-012). O §6 do `../docs/tecnica/08` dá quatro e reticências; o bloco do KAM-012 fecha em seis e nomeia um sétimo — `audit.read` — no seu último critério, sem o pôr na lista. São **sete**: ler o registo de auditoria é acção auditada, e um domínio que não a contém torna o critério impossível de cumprir. Estende-se por migração |
| Cabeça da cadeia de auditoria | `audit_heads(tenant_id, chave, last_hash)` | — | *proposta* (emenda 1.14, KAM-012). Uma linha por tenant, com `last_hash` igual ao `row_hash` da última linha desse tenant. O `chave` é coluna **gerada** — `coalesce(tenant_id, zero)` — e é o alvo do `ON CONFLICT`, porque uma chave primária recusa `NULL` e a cadeia de plataforma precisa dele (medido contra o PostgreSQL 18.6) |
| Papel de auditoria | `kamba_audit` — `NOBYPASSRLS`, sem DDL; único com `SELECT` em `audit_log` | — | *proposta* (emenda 1.14, KAM-012). O §3.3 do `../docs/tecnica/08` lista três papéis e a auditoria não tinha nenhum; `kamba_app` escreve e **não lê** |

### 3.3 Comércio

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Preço | `preco_minor` + `preco_tipo` ∈ {`fixo`, `a_partir_de`, `sob_consulta`} | `preco_kz`, `'exato'`, `preco_modo` | O validador (KAM-032) usa o tipo para não citar «a partir de» como fixo. O `preco_modo` entra na coluna «Substitui» pela emenda 1.12 (KAM-007): o `../docs/tecnica/03` escreve-o no DDL de `catalog_items`, a emenda 1.11 resolveu a divergência a favor desta linha, e **não a registou** — pelo que a migração que criasse essa coluna falhava o *gate* 3b por um nome que o documento técnico manda usar, sem variante que o explicasse |
| Stock | `stock_modo` ∈ {`garantido`, `indicativo`, `confirmar_dono`} | `p.stock>0` | Itens `confirmar_dono` exigem confirmação do dono (KAM-046) |
| Encomenda (estados) | `criada`, `aguarda_pagamento`, `pendente_confirmacao`, `paga`, `expirada`, `em_entrega`, `entrega_falhada`, `entregue`, `em_disputa`, `reembolso_pendente`, `reembolsada`, `cancelada` | Máquina incompleta em `../docs/tecnica/03 §6.1` | Fonte: `../docs/tecnica/00 §6.1` |
| Total da encomenda | `total_minor` | `total_kz` | — |
| Prazo de uma reserva ou de uma referência | `expira_at` | `expires_at` | *proposta* (emenda 1.12, KAM-007). O mesmo nome na coluna, no payload do evento e no `orders_mirror`. O `../docs/tecnica/03` escreve `expires_at` no DDL de `platform.stock_reservations`: a emenda 1.11 resolveu a divergência a favor de `expira_at` e **não registou a variante**, pelo que a migração que criasse essa tabela falhava o *gate* 3b sem explicação. Entra aqui no §3.3 e não no §3.5 porque é nome de **coluna** antes de ser nome de campo de evento |
| Identificador de confirmação | `confirm:{cart_id}` (Vendedor), `confirm:{hold_id}` (Serviços), `confirm:{item_id}` (módulos de entrada: conteúdo, proposta, publicação de produto; *proposta*) | `confirm:{cart_id}` para ambos | Embutido no botão |
| Marcação | `bookings(booking_id, tenant_id, contact_id, service_id, resource_id, inicio_at, fim_at, estado, hold_id)` | — | Detalhe em KAM-047 |

### 3.4 Pagamentos

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Valor | `valor_minor` + `currency` ∈ {`AOA`} | `valor_kz` | O `currency` estava só no §2 e o D-03 do KAM-111 dá-o como forma canónica «(§3.4)» — isto é, o dicionário nomeava-o numa secção de princípios e não na de nomes. Entra aqui pela emenda 1.13 (KAM-141, linha 2). O domínio é `AOA` enquanto a plataforma for de Angola; alargá-lo é emenda |
| Autenticação do evento | `payment_events.authn_ok boolean` + `authn_method` ∈ {`hmac`, `manual`, `consulta`} | `callback_hmac_ok`, `sig_ok`, `hmac_sha256`, `status_pull`, `humano_auditado` | O `ManualProvider` não tem HMAC: `authn_method='manual'` com actor humano registado. **As três formas do `../docs/tecnica/04` §6.2 entram na coluna «Substitui» pela emenda 1.13 (KAM-141, linha 4):** `hmac_sha256` → `hmac`, `status_pull` → `consulta`, `humano_auditado` → `manual`. Sem isto, o DDL do KAM-053, copiado do documento como o ticket manda, era recusado pelo gate sem explicação. **O quarto valor do `CHECK` desse documento, sistema, fica por decidir** e não entra aqui: não tem contrapartida no domínio de três, e registá-lo como variante faria o gate gritar sobre uma palavra comum em todo o conjunto documental. É pergunta para o KAM-053 — um pagamento confirmado pela própria plataforma (reconciliação) é `consulta` ou é um valor novo? |
| Eventos de pagamento | `payment.confirmed` (facilitador autenticado) e `payment.manual_confirmed` (`ManualProvider`) | `../docs/tecnica/04 §4.1` usa `payment.confirmed` para ambos | **Dois eventos distintos**; consumidores que não distinguem subscrevem ambos |
| Unicidade do ledger | Conforme `../docs/tecnica/04` (inclui `account_id`, tipo de evento e sequência); **não** `UNIQUE(provider, referencia)` | Dedup `db.seen(provider, ev.reference)` em `../docs/tecnica/08` §4.5 (localização a confirmar em KAM-111) | O ledger é append-only: o mesmo `referencia` tem várias linhas |
| Replay | Idempotência por `(provider, account_id, referencia)`; timestamp assinado só se o facilitador o fornecer | «replay ±5 min» | `../docs/tecnica/00` §4 (GWY) |
| Beneficiário | `beneficiary_kind` ∈ {`pme`, `plataforma_receita_propria`} | — | O billing da KAMBÁ não activa o tenant `platform` |

### 3.5 Eventos

| Conceito | Nome canónico | Nota |
|---|---|---|
| Envelope | `id`, `tipo`, `versao`, `tenant_id`, `ocorrido_em`, `registado_em`, `produtor`, `agregado`, `correlacao_id`, `causa_id`, `trace_id`, `classe_pii`, `finalidades`, `payload` — **catorze** campos de topo; o `agregado` é um objecto com `tipo`, `id` e `seq` | **Corrigido na emenda 1.11 (KAM-007): eram nove, e o `seq` estava no topo.** Não é uma escolha de desenho — é o que o `platform.evt_emitir` constrói e o que o `lerEnvelope` exige (`CAMPOS_DO_ENVELOPE`, lista fechada). Um `v1.schema.json` com `additionalProperties: false` que declarasse nove recusava **todos** os envelopes reais. Fecha a decisão aberta da emenda 1.9 («9 ou 14 campos de topo, e o `seq` no topo ou dentro do `agregado`») pelo lado do código, que é a única fonte que já corre. Versões desconhecidas **falham de forma visível** (nunca ignoradas em silêncio) |
| Tipos do Piloto | `order.created`, `order.paid`, `order.expired`, `order.cancelled`, `order.delivered`, `payment.reference_issued`, `payment.confirmed`, `payment.manual_confirmed`, `payment.failed`, `payment.expired`, `review.requested`, `review.created`, `query.resolved`, `query.unresolved`, `query.handoff`, `tenant.approved`, `tenant.provisioned`, `tenant.activated`, `tenant.suspended`, `tenant.reactivated`, `tenant.closed`, `catalog.product_changed`, `catalog.price_changed`, `stock.reserved`, `stock.released`, `stock.adjusted`, `stock.low`, `consent.recorded`, `consent.withdrawn`, `privacy.erasure_requested`, `privacy.erasure_applied`, `channel.updated`, `channel.inactivity_warning`, `contact.merged`, `conversation.mode_changed`, `booking.created`, `booking.reminder_due`, `booking.cancelled` | **Corrigido e completado na emenda 1.11 (KAM-007): eram dezoito, e a nota dizia «os últimos sete são acrescentados ao catálogo de `../docs/tecnica/06 §5`» — a contagem estava errada (dois deles já lá estavam) e faltavam vinte tipos de Fase P que o §5 tem e esta linha não tinha, a começar por `order.paid`. São agora **trinta e oito**: os trinta de Fase P do `../docs/tecnica/06 §5`, mais os oito que o §5 não lista e que outros documentos exigem — `channel.updated` e `contact.merged` (`../docs/tecnica/01` §6.3 e §7.2), `conversation.mode_changed` (KAM-018), `tenant.provisioned` (KAM-092), `channel.inactivity_warning` e os três de marcação, que esta linha já tinha. Fase C e D ficam de fora: o critério 1 do KAM-007 pede Fase P, e um contrato para um evento que ninguém emite é especulação. Cada um tem `contratos/eventos/<tipo>/v1.schema.json` |
| Campos de payload dos eventos | `order_id`, `review_id`, `numero_publico`, `sku`, `qty`, `linhas`, `currency`, `nota`, `motivo`, `entrega_modo`, `entrega_confirmada_por`, `paga_via`, `expira_at`, `autenticacao`, `authn_ok`, `provider_event_id`, `plano` | *proposta* (emenda 1.11, KAM-007). O `../docs/tecnica/06` §5 dá produtor, consumidores, agregado, classe de PII e fase de cada tipo, e **não dá os campos de nenhum payload** — há um único exemplo, no §4. Estes são os nomes que os trinta e oito contratos v1 usam além dos que o dicionário já tinha; vêm do DDL de `../docs/tecnica/03` e de `../docs/tecnica/02` sempre que lá existem. Nenhum é de PII P2: os sete nomes que o *lint* do §7.3 proíbe — telefone, nome, morada, texto, email, msisdn e bsuid — não aparecem em contrato nenhum (§7.1). **Duas divergências com o DDL de `../docs/tecnica/03`, resolvidas a favor desta tabela:** esse documento escreve preco_modo e o §3.3 desta tabela fixa `preco_tipo`, que é o que os contratos usam; e a coluna expires_at das reservas de stock é, em evento, `expira_at` — o nome que o `orders_mirror` já usa para a mesma ideia. O `motivo` é o nome de evento para a razão de uma transição: a coluna do registo de estados chama-lhe causa, e em evento esse nome colidia com `causa_id`, que é outra coisa |
| Gatilho do provisioning | `tenant.approved` | Não `tenant.activated` (`../docs/tecnica/01`, `02`, `03`, `06` a actualizar) |
| Evento do gate da Fase 0 | Um pedido do Vendedor pago via `ManualProvider` emite `payment.manual_confirmed`; a vertical **Serviços** consome-o e confirma uma marcação com sinal (KAM-039, KAM-108) | `servicos.yaml` subscreve **ambos** os eventos de pagamento |
| Consumidores | Idempotentes por `(consumer, event_id)`; DLQ após **6** tentativas (1 + 5) | **Corrigido na emenda 1.10 (KAM-006): dizia «5 tentativas».** O `../docs/tecnica/06` §6.4 fixa 1 + 5 e explica a diferença: o documento exploratório 11 dizia «5 retries», que são as **re**tentativas. A escada tem cinco degraus (1 s, 5 s, 30 s, 2 min, 10 min) e a primeira tentativa não espera — por isso são seis. O critério 2 do KAM-006 exige «exactamente 6 tentativas» |
| Outbox transaccional | `events_outbox(id, event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, agregado_seq, particao, envelope, criado_at, publicado_at, tentativas, proxima_tentativa_at)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.1. O `events_outbox.tenant_id` é `NOT NULL` (§3.2). O `id` é `bigint` de identidade e não `uuid`: é a ordem de escrita que o publicador varre, e a chave de idempotência é o `event_id` (UUIDv7). Excepção consciente à convenção de chaves do §2 |
| Sequência por agregado | `evt_agregado_seq(tenant_id, agregado_tipo, agregado_id, seq)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.1 **com um desvio**: o documento não tem `tenant_id` e o contador fica global, o que deixava um tenant cortar a emissão de eventos de outro (ANALISE-20, achado 2). Com o `tenant_id` na chave, na política `tenant_iso` e na unicidade do triplo de `events_outbox`, o espaço de `seq` é por tenant |
| Subscrições de entrega | `evt_subscricoes(consumer, tipo, versao_max, finalidade, exige_ordem, activo)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.1. O publicador entrega a uma subscrição activa só se a sua `finalidade` estiver em `envelope.finalidades` (§7.3) |
| Arquivo de eventos | `events_log(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, agregado_seq, ocorrido_em, registado_em, classe_pii, envelope)` | *proposta* (emenda 1.9, KAM-005). Forma de `../docs/tecnica/06` §6.5. Particionado por mês em `ocorrido_em`, imutável (nenhum papel de serviço tem `UPDATE` nem `DELETE`) |
| Partição DEFAULT do arquivo | `events_log_default` | *proposta* (emenda 1.9, KAM-005). As partições mensais têm nome com data e nascem de um *job*; a `DEFAULT` é a única que uma migração pode criar sem fixar o calendário, e é a rede quando o *job* não corre |
| Emissão de um evento | `evt_emitir` | *proposta* (emenda 1.9, KAM-005). A função que o produtor chama na sua própria transacção (`../docs/tecnica/06` §6.1). `SECURITY INVOKER`: a política `tenant_iso` do outbox continua a valer |
| Janela de deduplicação | `events_consumed(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq, processado_at)` | *proposta* (emenda 1.10, KAM-006). Forma de `../docs/tecnica/06` §6.3 **com um desvio aditivo**: o documento não tem `tenant_id`, e sem ele a tabela fica fora da RLS e expõe que eventos existem noutro tenant — a mesma correcção que a emenda 1.9 fez ao `evt_agregado_seq`. A chave é `(consumer, event_id)`: é o par que torna a entrega *at-least-once* num efeito exactamente-uma-vez. Retenção de 90 dias, que excede a re-entrega da Meta (7 dias) |
| Fila de mortos | `events_dlq(id, consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas, estado, criado_at, resolvido_at, resolvido_por)` | *proposta* (emenda 1.10, KAM-006). Forma de `../docs/tecnica/06` §6.4. `estado ∈ {aberta, reprocessada, descartada}`; a unicidade de `consumer` e `event_id` faz a reentrada idempotente. Uma entrada de um evento de pagamento, ou do evento que diz que a encomenda ficou paga, é **Sev1**: é cliente que pagou sem confirmação. Retenção de 30 dias **após** resolução; uma entrada aberta nunca se apaga |
| Aprovações de descarte | `evt_dlq_aprovacoes(dlq_id, aprovador, criado_at)` | *proposta* (emenda 1.10, KAM-006). **Não está no `../docs/tecnica/06`**, que tem só `resolvido_por text`: «descartar um evento de pagamento exige duas pessoas» (§6.4) não se escreve numa coluna de texto. Com a chave `(dlq_id, aprovador)`, a mesma pessoa a aprovar duas vezes é **impossível** em vez de detectada |
| Acções com efeito externo | `evt_acoes(idempotency_key, consumer, event_id, accao, tenant_id, estado, resultado, criado_at, concluido_at)` | *proposta* (emenda 1.10, KAM-006). O ticket dá o nome como proposta. A chave é `consumer:event_id:acção`, que é o mesmo valor do `Idempotency-Key` enviado ao terceiro (§6.3). `estado ∈ {em_curso, feita, falhada}`: o `em_curso` existe para o processo que morreu entre o registo e a conclusão — o efeito **talvez** tenha acontecido, e nesse caso adia-se em vez de repetir ou de dar por feito |
| Retenção das tabelas de eventos | `evt_limpar_consumidos`, `evt_limpar_dlq` | *proposta* (emenda 1.10, KAM-006). As duas retenções do §6.3 e §6.4 como funções, não como *jobs*: o agendador nasce com a retenção (KAM-071) ou com o procedimento de *deploy* (KAM-078), a mesma decisão que a emenda 1.9 tomou para as partições mensais. A primeira recusa menos de 7 dias — a janela tem de exceder a re-entrega da Meta |
| Campos do envelope que o §6.1 acrescenta | `registado_em`, `produtor`, `correlacao_id`, `causa_id`, `classe_pii`, `finalidades` | *proposta* (emenda 1.9, KAM-005). O `jsonb_build_object` de `evt_emitir` constrói **14** chaves de topo e a linha «Envelope», acima, nomeia 9 nomes — dos quais `seq` não é de topo, pelo que são 8 de topo mais estes 6. Estes seis são os que faltavam, e entram porque são **colunas** do `events_log` e chaves do `envelope` que o DDL escreve. **O que fica por decidir:** se o contrato v1 publicado em `contratos/eventos/` (KAM-007) tem 9 ou 14 campos de topo, e se o `seq` vive no topo ou dentro de `agregado` — aqui a leitura é que a linha «Envelope» é uma lista de **nomes** e não de aninhamento, e que `agregado = {tipo, id, seq}` usa os dois. A decisão é de quem aprova emendas |

### 3.6 Runtime, LLM e dados derivados

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Esquema do checkpointer | `lg` | — | Role próprio |
| Esquema de analítica | `dat` | — | *proposta* (emenda 1.38, KAM-030). Criado pela revisão `0023`. O que vive aqui é **medida**, não estado de negócio, e a retenção é `DROP` de partição e não `DELETE` |
| Esquemas | `platform`, `lg`, `dat`, `idx`, `servicos`, esquemas do Medusa | — | RLS também em `idx.*` (KAM-061) e em `dat.*` (KAM-030) |
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
| Entitlements de módulo | No registo e na configuração: `modulo` ∈ {`catalogo`, `foto`, `social`, `orcamento`}, com limites `imagens_mes`, `posts_mes`, `orcamentos_mes`. A coluna `entitlements.modulo` tem `CHECK` de **forma** e não de domínio (§3.2, ADR-012): um módulo novo entra por configuração e não por migração | KAM-124, e a emenda 1.13 (KAM-141, linha 6) |
| Eventos | `quote.requested`, `quote.sent`, `content.approved` | KAM-123, KAM-122 |

### 3.8 Nomes introduzidos pelos tickets KAM-111 a KAM-117 (*proposta*, a ratificar por emenda)

| Conceito | Nome | Ticket |
|---|---|---|
| Vistas de churn e tenants dormentes | `v_churn_signals`, `v_tenant_dormente` | KAM-117 |
| Evento de aviso de inactividade do canal | `channel.inactivity_warning` | KAM-017 |

Sem esta emenda, o lint de KAM-111 rejeitá-los-ia; a ratificação faz-se numa linha do §6.

O **`owner_notices`** esteve nesta tabela, do KAM-115. Saiu com a emenda 1.32, que
é a do próprio ticket: o nome deixou de ser uma pré-declaração sem conceito e
passou a ter a tabela, as colunas e os domínios no §3.23. É o mesmo percurso que
o `token_ref` fez na 1.22, o `waac_id` na 1.30 e as duas colunas de
`tenant_channels` na 1.31 — e o lint recusa a redundância, pelo que a linha tinha
de sair daqui no mesmo *commit* em que entrou lá.

As **duas linhas do KAM-114** fizeram o mesmo percurso com a emenda 1.44: a
`draft_decisions`, a política `concierge` e o `edicao_numero_livre` passaram a ter
tabela, colunas e domínios no §3.34, e saíram daqui no mesmo *commit*.

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

### 3.12 Nomes introduzidos pelo ticket KAM-013 — entrada de canal (*proposta*, a ratificar por emenda)

As duas tabelas de entrada e o vocabulário que as atravessa. Entram aqui porque
são **DDL que o KAM-013 escreve** e o §1 declara defeito um nome de DDL fora
deste dicionário — a mesma razão das emendas 1.2, 1.9, 1.14 e 1.17 — e porque
**nove tickets as herdam**: KAM-014, KAM-015, KAM-016, KAM-017, KAM-018,
KAM-020, KAM-021, KAM-024 e KAM-084 são bloqueados pelo KAM-013.

Nenhuma das duas tem `tenant_id`, e isso é desenho e não esquecimento: o GWY é
o endpoint **único** da Meta (ADR-001) e o tenant só nasce no CHR, que corre
depois (KAM-014). Pela mesma razão não têm RLS — o *gate* 6 descobre as tabelas
a isolar **pela coluna `tenant_id`**, e sem ela nenhuma política é exigida nem
dispensada; não há entrada em `../ci/rls_exceptions.yaml`.

| Conceito | Nome canónico | Nota |
|---|---|---|
| Registo de um evento de canal recebido | `inbound_events(id, kind, event_key, waba_id, phone_number_id, recebido_at, processado_at)`, com `UNIQUE (kind, event_key)` | Forma do bloco do KAM-013 e de `../docs/tecnica/01` §5.2. **Não guarda o corpo**: o *payload* de conversa vive no *job* e, depois, nos *checkpoints* do AGR (DoD do ticket, «Privacidade») |
| Quarentena de um evento que não se conseguiu encaminhar | `unrouted_events(id, kind, event_key, waba_id, phone_number_id, motivo, payload, recebido_at, processado_at)`, com `UNIQUE (kind, event_key)` | Forma de `../docs/tecnica/01` §5.5. **Esta guarda o corpo**, e é a única excepção: sem ele não se diagnostica o que não encaixou. Retenção de **7 dias** (*proposta*), a impor em KAM-071 |
| Classe de um evento de canal registado | `inbound_events.kind` ∈ {`message`, `echo`, `statuses`, `history`, `smb_app_state_sync`, `account_update`, `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update`} | **Doze**, e são os **onze campos de webhook** que o critério do KAM-016 fixa, com o campo `messages` a dar dois (`message` e `statuses`, que chegam no mesmo `value` e têm destinos opostos) |
| Classe de um evento em quarentena | `unrouted_events.kind` ∈ {`desconhecido`, `invalido`} | **Dois, e não os doze da outra tabela.** Não são campos da Meta: são os dois caminhos de quarentena, e existem como `kind` para que a chave `(kind, event_key)` deduplique também o que não se conseguiu encaminhar. A divisão em dois domínios foi obrigada pelo *gate* 3b, que pede o domínio **por coluna**, e é mais estreita do que a primeira versão desta emenda: com catorze valores nas duas tabelas, uma `message` podia ser escrita na quarentena e um `invalido` no registo de entrada |
| Chave de deduplicação semântica de um evento de canal | `event_key` | `wamid` para `message` e `echo`; `wamid:estado` para `statuses` (letra do critério 4 do KAM-013); para o resto, o resumo canónico de `(waba_id, campo, valor)` — ver a linha seguinte |
| Resumo canónico de um evento sem `wamid` | `k_` mais 32 hexadecimais do SHA-256 do JSON com chaves ordenadas | *proposta*. Um `account_update` não traz identificador nenhum, e sem chave determinística a re-entrega da Meta (7 dias, E1 §5) criava uma linha por tentativa. Distingue-se do `id_opaco` do §3.10 pelo prefixo: aquele mascara para *log*, este deduplica em base |
| Razão por que um evento foi para quarentena | `unrouted_events.motivo` ∈ {`json_invalido`, `campo_desconhecido`, `corpo_sem_entry`, `change_sem_itens`, `canal_desconhecido`, `mensagem_sem_identidade`} | *proposta*. `json_invalido` é o critério 6 do KAM-013 (200 e quarentena, nunca 5xx); `change_sem_itens` é um campo **conhecido** cujo `value` não traz item tratável — a Meta põe `errors` dentro do campo `messages`, e isso não é campo desconhecido nem corpo malformado. Os dois últimos são do **KAM-014** (emenda 1.20): `canal_desconhecido` é o critério 2 desse ticket — um `phone_number_id` que não está em `tenant_channels` — e `mensagem_sem_identidade` é uma `message` sem `from` e sem `from_user_id`, que o `E1` §3 diz que não devia existir e que, sem motivo próprio, fazia o *job* repetir sete dias sobre um corpo que nunca melhora. Os quatro primeiros são do **corpo**; estes dois são do **encaminhamento**, e é por isso que têm motivo próprio em vez de caberem em `campo_desconhecido`. **O domínio desta coluna vive todo nesta linha**, e os valores novos entram aqui e na revisão `0008`, que é quem cria o `CHECK`: o *gate* 3b lê cada revisão isoladamente, pelo que um `CHECK` com menos valores do que o dicionário é achado mesmo que uma revisão posterior o alargue |
| Destino de encaminhamento de um `kind` | `destino` ∈ {`chr`, `outbound`, `ingestao`, `gestao_de_canal`, `quarentena`} | *proposta*. É a tabela do critério 8 do KAM-013 em forma de domínio fechado: `message`/`echo` → `chr`; `statuses` → `outbound` (nunca ao AGR); `history`/`smb_app_state_sync` → `ingestao` (KAM-017); os sete de gestão → `gestao_de_canal`. **Não é coluna**, e por isso entra sem qualificação de tabela — ao contrário de `inbound_events.kind` e de `unrouted_events.motivo`, que são colunas com `CHECK` na revisão `0008`. Vive no código, e é o `kind` que o decide |
| Fila de entrada do webhook | `wa-inbound`, com `jobId` igual ao SHA-256 do corpo bruto | *proposta*. O `jobId` é o primeiro dos dois níveis de deduplicação (re-entrega byte-a-byte); o segundo é `UNIQUE (kind, event_key)` |
| Métricas do GWY | `gwy_requests_total`, `gwy_sig_fail`, `gwy_shed_total`, `gwy_enqueue_ms`, `inbound_queue_depth` | **Cinco, e o DoD do KAM-013 nomeia quatro.** O quinto é `gwy_shed_total`: o critério 7 manda descartar tráfego sob saturação, e descartar sem contar é descartar em silêncio — um painel sem ele não distingue «a Meta mandou menos estados» de «nós deitámos fora os dela». Nenhum leva etiqueta com identificador (`../docs/seguranca/ameacas_stride.md`, OBS-I). `gwy_enqueue_ms` é um *gauge* do **último** enfileiramento: a agregação por percentil é KAM-080, e o p99 do critério 7 mede-se na prova de carga |
| `id` dos segredos do webhook | `meta_app_secret` (com anel `[actual, anterior]`), `meta_verify_token` | Já estavam em `../ops/secrets-inventory.yaml` e no §3.9; ficam nomeados aqui porque são a entrada do critério 3 |

**O que esta secção NÃO decide.** O nome do array que o campo
`smb_message_echoes` traz dentro do `value` é **NÃO VERIFICADO**: o `E1` §5 não
o diz e nenhuma página primária foi lida nesta execução. O código trata-o pela
regra geral (um evento por `change`, com o resumo canónico) e reconhece
`message_echoes` como *proposta*; fixá-lo é KAM-017, que é quem lê a
documentação de coexistência. **Nem decide o `wa_type`**: a lista de tipos de
mensagem é a de `../docs/tecnica/01` §5.4, vive no código do GWY como lista
fechada e **não entra aqui nem em `../canon/extensoes.yaml`** — por duas razões.
Um `text` ou um `order` como nome canónico solto passavam a ser aceites como
nome de coluna em qualquer migração (o efeito lateral que o §3.10 já avisa); e
nenhuma superfície do *gate* 3b lê TypeScript, pelo que uma extensão declarada
para eles seria uma entrada que nenhuma superfície usa — e essas **falham** o
próprio *gate*.

### 3.13 Nomes introduzidos pelo ticket KAM-014 — CHR e conversas (*proposta*, a ratificar por emenda)

A tabela das conversas, o modo que diz quem tem a palavra, e o vocabulário da
resolução de canal. Entram aqui porque a `conversations` é **DDL que o KAM-014
escreve** e o §1 declara defeito um nome de DDL fora deste dicionário — a mesma
razão das emendas 1.2, 1.9, 1.14, 1.17 e 1.19 — e porque **sete tickets a
herdam**: KAM-015, KAM-018, KAM-019, KAM-022, KAM-025, KAM-054 e KAM-118 são
bloqueados pelo KAM-014.

O `tenant_id` da plataforma **nasce aqui**. As duas tabelas de entrada do
KAM-013 não o têm por desenho (§3.12); a `conversations` é a primeira tabela do
caminho do webhook que o tem, e por isso é a primeira que o *gate* 6 descobre
pela coluna `tenant_id` e que leva RLS `FORCE` com a política `tenant_iso`
(ADR-015). Não há entrada em `../ci/rls_exceptions.yaml`.

| Conceito | Nome canónico | Nota |
|---|---|---|
| Conversa entre um contacto e um canal | `conversations(id, tenant_id, contact_id, channel_id, mode, last_inbound_at, window_expires_at, last_human_activity_at)`, com `UNIQUE (tenant_id, contact_id, channel_id)` | DDL do bloco do KAM-014. **A janela de 24 h vive aqui e não em `contacts`**, divergindo de `../docs/tecnica/01` §6.2: a `contacts` segue o ADR-010 e o KAM-008, e uma janela por contacto não distingue dois canais do mesmo tenant |
| Modo de uma conversa (quem tem a palavra) | `conversations.mode` ∈ {`bot`, `dono`, `humano`, `pausada`} | De `../docs/tecnica/01` §10.2. O KAM-014 só escreve o valor de omissão (`bot`) e **lê** os outros para decidir se a mensagem vai ao AGR; as **transições** são KAM-018 |
| Prazo da janela de serviço de uma conversa | `conversations.window_expires_at` = `last_inbound_at` + 24 h | *proposta*. As 24 h são CONFIRMADO (`../docs/tecnica/evidencia/E1` §4); o que é proposta é a janela viver nesta tabela. O FEP de 7 dias (`../docs/tecnica/01` §8) é de **Clusters** — corrigido pela emenda 1.21: esta linha atribuía-o ao KAM-015 e os *Detalhes Técnicos* do próprio KAM-015 atribuem-no a Clusters, e sobre o âmbito de um ticket o campo do próprio ticket prevalece |
| Contexto que a resolução de canal devolve | `ChannelContext` — `tenant_id`, `channel_id`, `vertical`, `plano`, `estado_tenant`, `estado_canal`, `channel_mode`, `origem` | Os oito campos do critério 1 do KAM-014. **Não é tabela nem coluna**: é o que o CHR devolve, e entra aqui por ser a costura que sete tickets consomem — como o `StorageProvider` e o `ObjectRef` do §3.11. A «persona» que `../docs/tecnica/01` §7.2 põe neste contexto **não** está nos oito: ver «O que esta secção NÃO decide». Escrita em guilhemetes e não entre crases de propósito: entre crases o `dict_export` colhe-a como nome conhecido, e um nome conhecido que nenhuma secção define é uma coluna futura a passar o *gate* 3b sem ninguém decidir nada (medido: o teste `test_o_ddl_de_tenant_channels_do_doc_03_seria_recusado` do `canon_lint` ficou com um achado em vez de dois) |
| Contrato do *job* que o CHR entrega ao AGR | `agent_invocation` — `tenant_id`, `contact_id`, `conversation_id`, `channel_id`, `wamid`, `type`, `modo`, `thread_id`, `vertical` | Os sete campos do critério 6 do KAM-014, mais o `thread_id` que o mesmo critério fixa (`{tenant_id}:{contact_id}`, §3.1) e o `vertical` que o contexto do KAM-025 nomeia. **Sem telefone, sem BSUID e sem `display_name`** — é o critério e é o ADR-010 |
| Fila de invocação do AGR | `agr-inbound`, com `jobId` igual ao SHA-256 de `{tenant_id}:{wamid}` | *proposta*. O KAM-025 chama-lhe «fila inbound» e nenhum documento lhe dá nome. O `jobId` é um resumo e **não** o `wamid`: o `wamid` leva o número do interlocutor em base64 (`../docs/logs.md` §2.1) e uma chave de fila é lida por quem opera a fila |
| Razão por que a resolução não encaminhou | **Dois** valores novos na linha «Razão por que um evento foi para quarentena» do §3.12, que passa de quatro a **seis**: `canal_desconhecido` e `mensagem_sem_identidade` | O domínio fica **todo** no §3.12, e não repartido: é uma coluna só, e o *gate* 3b compara o `CHECK` da revisão com **uma** entrada por coluna — duas entradas para `unrouted_events.motivo` fazem a segunda tapar a primeira, e a revisão `0008` ficava vermelha por lhe «faltarem» os quatro valores que tem (medido). **A recusa do Fluxo B não entra aqui**: o critério 5 pede «0 *jobs*, alerta» e não uma linha de quarentena, e um valor de domínio que nenhum caminho escreve é peso morto — o alerta é a métrica de resoluções e a linha de registo |
| Métricas do CHR | `chr_resolve_ms`, `chr_unrouted_total`, `chr_cache_hit_ratio`, `chr_resolve_total` | **Quatro, e o DoD do KAM-014 nomeia três.** A quarta é `chr_resolve_total`, com uma etiqueta de desfecho de cinco valores (encaminhado, entregue ao dono, em quarentena, Fluxo B recusado, recusado pela matriz de estados — lista fechada no código, como o `wa_type` do §3.12 e pela mesma razão; a razão da quarentena vive na etiqueta `motivo` da métrica da quarentena, e não aqui): é ela que torna visível a recusa do Fluxo B (critério 5, que pede alerta e não quarentena) e a recusa pela matriz de estados — sem ela um painel não distingue «ninguém escreveu» de «foi tudo recusado», e as outras três não o dizem, porque a de quarentena só conta o que não se encaminhou. Nenhuma leva etiqueta com identificador (`../docs/seguranca/ameacas_stride.md`, OBS-I): os cinco desfechos são lista fechada e não crescem com o tráfego |
| Variáveis de ligação do CHR | `KAMBA_CHR_RESOLVER_DB_URL`, `KAMBA_CHR_IDENTITY_DB_URL` | Uma por papel, no padrão do `services/worker-canal/src/consumidor.ts` (que já abre duas ligações com dois papéis). A terceira ligação do CHR — `kamba_app`, para `conversations` — é a que o processo de entrada já tem (`KAMBA_ENTRADA_DB_URL`) |
| Fase do produto, lida pela guarda do ADR-011 | `KAMBA_FASE` ∈ {`piloto`} | Já existia em `libs/py-core/src/kamba_core/fluxo_piloto.py` (KAM-004) e **não estava neste dicionário**. Fica nomeada porque o KAM-014 é o primeiro código TypeScript que a lê, e porque um valor ausente ou desconhecido **não** desliga a guarda: levanta |

**O que esta secção NÃO decide.** A «persona» do `ChannelContext` de
`../docs/tecnica/01` §7.2 fica de fora, e não por esquecimento: o §3.2 deste
dicionário diz que «a **persona** `dono` é resolvida pelo CHR a partir de
`contacts.papel`», e `contacts.papel` **não existe** — a revisão `0003`
(KAM-008) não a criou e nenhum ticket a atribui. Os oito campos do critério 1
do KAM-014 também não a incluem. Enquanto a coluna não existir, o CHR não pode
resolver persona nenhuma; quem decide onde o papel de um contacto vive é o
ticket que criar a coluna, e está em `../docs/dividas-documentais.md`. **Nem
decide o `turn_id`**: o contexto do KAM-025 nomeia um `turn_id` igual ao
`wamid`, e o contrato `agent_invocation` leva o `wamid` com esse nome; se o AGR
preferir `turn_id`, é o KAM-025 que o acrescenta — duplicar o mesmo valor com
dois nomes num contrato com `additionalProperties: false` era pedir que
divergissem.

### 3.14 Saída de canal: envio, templates e custo (KAM-015)

*Emenda 1.21, **proposta**.* Entra porque a revisão `0010` cria DDL e o §1 declara
defeito um nome de DDL fora deste dicionário. A fonte do desenho é
`../docs/tecnica/01` §8.2–§8.5; onde esta secção divergir dele, a divergência
está escrita na linha e no `docstring` da revisão.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Mensagem que a plataforma envia | `platform.outbound_messages` — `id`, `tenant_id`, `channel_id`, `contact_id`, `conversation_id`, `idempotency_key`, `wamid`, `kind`, `template_name`, `state`, `pricing`, `error_code`, `created_at`, `delivered_at` | Catorze colunas. O DDL de `../docs/tecnica/01` §8.4 tem **treze**: acrescenta-se `conversation_id` (sem ela não há ordem por conversa, que o critério 6 pede) e nada mais. Vive em `platform.` e leva **FK compostas**, contra a forma do §8.4 — ver «As três divergências», abaixo |
| Estado de uma mensagem de saída | `outbound_messages.state` ∈ {`queued`, `sent`, `delivered`, `read`, `failed`, `suppressed_by_human`} | **Seis**, e o §8.4 escreve cinco. O sexto é do KAM-018 e **nasce aqui**: o *gate* 3b lê o AST de cada revisão isoladamente e compara o `CHECK` com uma entrada por coluna, pelo que alargar o domínio numa revisão posterior deixava a `0010` vermelha por lhe faltar um valor — foi medido no `unrouted_events.motivo` (emenda 1.20). O bloco do KAM-015 manda-o por extenso; o do KAM-018 diz que a migração dele o «adiciona se ainda não existir», e passa a não ter trabalho |
| Categoria de uma mensagem de saída | `outbound_messages.kind` ∈ {`service`, `utility`, `marketing`, `authentication`} | É a categoria que a Meta factura, e o nome é o do §8.4. **Atenção:** `kind` já é coluna de `inbound_events` (§3.12, doze valores). Duas colunas com o mesmo nome e domínios diferentes — o *gate* 3b compara **uma entrada por coluna**, logo as duas entradas convivem porque estão qualificadas pela tabela, e é a mesma armadilha que o §3.13 registou |
| Preço que a Meta cobrou por uma mensagem | `outbound_messages.pricing` (`jsonb`) — chaves `billable`, `pricing_model`, `type`, `category` | As quatro chaves são as do critério 4 e as do `pricing` dos `statuses`. Guarda-se o que **chegou**, sem recalcular: a cobrança é por mensagem entregue (CONFIRMADO, `E1` §1) e quem factura é a Meta |
| Template registado de um tenant | `platform.message_templates` — `tenant_id`, `name`, `lang`, `category`, `status`, `quality`, `meta_template_id`, `body_hash`, `bloqueado_em`, `updated_at` | «PRIMARY KEY (tenant_id, name, lang)», como o §8.3. A `bloqueado_em` é nova e serve o critério 9: a recategorização para `marketing` bloqueia o uso, e um bloqueio sem instante não se audita nem se levanta |
| Estado de aprovação de um template | `message_templates.status` ∈ {`pending`, `approved`, `rejected`, `paused`, `disabled`} | **Em minúsculas**, e o §8.3 escreve-os em maiúsculas porque é o vocabulário da Meta. O §2 deste dicionário manda «Estados: minúsculas, `snake_case`, sem acentos», e prevalece: a base é nossa. A tradução do vocabulário da Meta faz-se **na fronteira**, numa função com teste, pela mesma razão por que o `wa_type` do §3.12 ficou como lista fechada no código |
| Categoria de um template | `message_templates.category` ∈ {`utility`, `marketing`, `authentication`} | O `marketing` entra no domínio porque a Meta **recategoriza** e a tabela tem de poder registar o que ela diz; o que o Piloto recusa é **enviar** nessa categoria (critério 7), e recusar no envio é diferente de não saber ler o que chega |
| Nota de qualidade de um template | `message_templates.quality` ∈ {`green`, `yellow`, `red`} | Anulável: um template recém-submetido não tem nota. Minúsculas pela mesma regra do `status` |
| Recusa de envio com a janela fechada | `WINDOW_CLOSED` | Um dos **onze** `MOTIVOS_DE_RECUSA` — eram dez, e o `STATE_REFUSED` do §3.18 (KAM-021) é o décimo primeiro. **Não é coluna nem estado**: é o valor que o `ChannelAdapter` devolve ao chamador, que decide template ou desistir (§8.2, regra 3). Entra aqui por ser a costura que o KAM-018, o KAM-048 e o KAM-058 consomem — como o `ChannelContext` do §3.13 |
| Gancho chamado antes de cada envio do bot | `PreSendGuard` | **Porta, não implementação.** O corpo é do KAM-018 (§KAM-018, «Componentes: ChannelAdapter (`PreSendGuard`)»); o que o KAM-015 entrega é a porta e a **falha fechada**: sem guarda instalada, o envio do bot levanta em `KAMBA_ENV=ci`. Um gancho que falte e deixe passar é um gancho que não existe |
| Chave de idempotência de um envio | `outbound_messages.idempotency_key`, única por `(tenant_id, idempotency_key)` | **Não global**, e o §8.4 escreve `UNIQUE` sozinho. A razão é a da emenda 1.18, que levou a chave do `usage_ledger` de global a composta: com unicidade global, duas chaves iguais de *tenants* diferentes colidem, o segundo envio é deduplicado em silêncio, e o `INSERT` falha sobre uma linha que o segundo *tenant* **não pode ver** — um *tenant* suprime mensagens de outro se adivinhar a chave. O `wamid` fica com unicidade **global**, e a assimetria é deliberada: a chave é nossa e uma colisão entre *tenants* é acidente de nomes, o `wamid` é da Meta e globalmente único por construção, pelo que uma colisão ali é um defeito que vale a pena fazer barulho |
| Tarifas da Meta por categoria | `config/meta_rates.yaml` | Pasta nova. As tarifas são CONFIRMADO (`E1` §1, *Rest of Africa*, efectivas 2026-10-01): `service` 4 000, `utility` 4 000, `authentication` 4 000, `marketing` 22 500 **micro-dólares** (1e-6 USD) — isto é, 0,004 e 0,0225 USD. A unidade é inteira porque o §2 manda «dinheiro em unidade menor inteira, nunca vírgula flutuante», e o centavo não serve: 0,004 USD são 0,4 centavos. Somar 0,004 mil vezes em `float64` não dá 4,00, e num acumulador de custo isso é deriva que ninguém reconcilia contra uma factura; o `tools/kamba_yaml.py` recusou a primeira versão do ficheiro por escrever `0.004`, e apanhou o defeito no sítio certo. A **cadência** de revisão é *proposta* e não CONFIRMADO: o «1 Jan, 1 Abr, 1 Jul, 1 Out» de `../docs/tecnica/01` §8.4 diz de si «calendário a confirmar», e o `E1` §1 diz que a cadência «vem de resumo de pesquisa». O ficheiro declara as duas coisas com estados diferentes |
| Métricas da saída | `outbound_sent_total`, `outbound_latency_ms`, `outbound_window_closed_total`, `outbound_rate_limited_total`, `meta_cost_usd_total` | **Cinco, e o DoD do KAM-015 nomeia três.** A `outbound_rate_limited_total` é o único sítio onde um envio travado por débito fica visível, e sem ela um painel não distingue «ninguém enviou» de «foi tudo travado»; leva a etiqueta «origem», de dois valores — «bucket» (o nosso *token bucket*) e «meta» (um `130429` que o *backoff* repetiu) —, e separá-las é o que distingue «o nosso tecto está apertado» de «o dela está à frente do nosso». A `outbound_sent_total` leva a etiqueta `kind` (lista fechada de quatro) e é ela que torna o custo auditável contra a tabela. A `meta_cost_usd_total` **não leva etiqueta de tenant** — ver «As três divergências» |
| Débito de saída por canal | *token bucket* por `phone_number_id`, capacidade 15 mps em coexistência | *proposta*, com folga sobre os 20 mps CONFIRMADOS (`E1` §5). Para `cloud_only` nenhum documento dá número: fica o mesmo 15, configurável, e dito como *proposta* |
| Débito de saída por par | *token bucket* por `(tenant_id, contact_id)`, 1 mensagem/s e 30/min | *proposta* e **a calibrar**: o *pair rate limit* real da Meta é NÃO VERIFICADO (`E1` §5), e o §8.5 di-lo. Não se inventa um valor para ele |
| Variável de ligação do destinatário | — | **Não existe, e é deliberado.** O `ChannelAdapter` não abre ligação a `contact_endpoints`: recebe uma **porta** que devolve o destinatário, e quem a liga ao módulo de identidade é o serviço. Só `kamba_identity` lê `contact_endpoints` (§3.2) e o adapter corre como `kamba_app`; dar-lhe uma quarta ligação era alargar o privilégio de quem envia ao de quem decifra |

**As três divergências que esta emenda assume**, cada uma contra um documento que
diz outra coisa:

1. **`platform.` e FK compostas**, contra a forma dos DDL de `../docs/tecnica/01`
   §8.3–§8.4, que não têm prefixo nem chaves estrangeiras — e contra o bloco do
   KAM-015, que diz «exactamente como o doc 01 §8.3–§8.4». As nove revisões
   anteriores criam tudo em `platform.` e, desde a `0003`, com FK em
   `(tenant_id, …)`; a `0009` escreveu a razão: sem a composta, «uma conversa do
   *tenant* A podia apontar para um canal do *tenant* B», e nem o *gate* 6 nem o
   3b o veriam. Uma tabela de saída sem FK composta tinha o mesmo furo.
2. **`status` e `quality` em minúsculas**, contra o §8.3. O §2 deste dicionário
   manda minúsculas e prevalece sobre `../docs/tecnica/`; o vocabulário da Meta
   traduz-se na fronteira.
3. **`meta_cost_usd_total` sem etiqueta de *tenant***, contra o DoD do KAM-015,
   que escreve `meta_cost_usd_total{tenant}`. As quatro bibliotecas de métricas
   deste repositório recusam por gramática uma etiqueta que não case
   `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID com hífenes: **a chamada
   levanta**. A razão é o `OBS-I` de `../docs/seguranca/ameacas_stride.md`
   («identificadores em etiquetas explodem a cardinalidade e re-identificam») e
   o X-11 do *gate* 6, que varre registos por identificadores — uma etiqueta é
   tão legível como uma linha de registo. O custo por *tenant* sai de
   `outbound_messages.pricing` por consulta, que é o que o §16 do doc 01 já
   aponta («mecanismo: `pricing` dos *status*»). A caixa do DoD fica **vazia**,
   com esta razão.

**O que esta secção NÃO decide.** A **janela FEP** fica fora, e não por
esquecimento: o §3.13 desta tabela escreveu «O FEP de 7 dias é KAM-015» e o
bloco do KAM-015 escreve, nos seus próprios *Detalhes Técnicos*, «a janela FEP
(até 7 dias, anúncios CTWA) é de **Clusters**». Sobre o âmbito de um ticket, o
campo do próprio ticket é a afirmação mais específica — a linha do §3.13 foi
escrita pelo KAM-014 a atribuir trabalho a um vizinho —, e por isso **a linha do
§3.13 é corrigida nesta emenda** em vez de ficarem dois documentos a discordar.
Nenhum dos nove critérios do KAM-015 menciona FEP.

Também não decide: o **contador do *free tier*** (`tenant_channels.free_tier_used`
e `free_tier_month` existem desde a `0001` e `kamba_app` já pode alterá-las, mas
quem as mantém é o **KAM-023**, que o «Fora de âmbito» do KAM-015 exclui — o
adapter recebe o estado do *free tier* por porta, e é com ela injectada que o
critério 4 se demonstra); o **consumidor** de
`message_template_status_update`/`template_category_update`, cujo destino
`gestao_de_canal` tem tratador no **KAM-016**/**KAM-021** (o KAM-015 cria a
tabela, define quem tem `UPDATE` nas três colunas de estado, e escreve a regra de
bloqueio); o **aviso ao dono** quando uma mensagem expira, que precisa de canal
alternativo e é **KAM-115**; e o **evento de barramento** de entrega ou falha,
que nenhum critério pede e que o primeiro ticket a jusante a precisar dele
acrescenta como contrato novo.

### 3.15 Passagem a humano: handoff e provedor de atendimento (KAM-019)

*Emendas 1.22 e 1.23, **propostas**.* Entra porque a revisão `0011` cria DDL e o §1 declara
defeito um nome de DDL fora deste dicionário. A fonte do desenho é
`../docs/tecnica/01` §11 (Desenho I, promovido a ADR-001) e `../docs/tecnica/02`
§11 (o `interrupt()` idempotente), com o gatilho do `degraded` no §14 do mesmo
documento; onde esta secção divergir, a divergência está escrita na linha.

**Todas as referências de secção aqui foram conferidas contra os cabeçalhos
`## ` do ficheiro, e não pelo número de linha.** A primeira versão desta secção
citava o «`02` §12» em sete sítios, e o §12 daquele documento é o *Checkpointer
Postgres*: o que define os estados de `handoffs` e o `resolver` é o §11, que
acaba quatro linhas antes. Uma referência que existe e manda o leitor para o
sítio errado passa qualquer *gate*, e numa emenda ao dicionário custa mais do
que noutro sítio — é o que os tickets seguintes vão citar.

**Doze destes nomes não existiam em sítio nenhum** — nem aqui, nem em código, nem
nos contratos de evento. Dois deles, `MirrorMessage` e `HumanEvent`, só estavam
**nomeados** na assinatura do §11.1, sem campos definidos em nenhum documento:
esta secção é a primeira vez que se diz o que são.

**A emenda 1.23 vem de medição e não de leitura.** O spike do critério 8
correu contra um Chatwoot v4.18.0 fixado por digest, e o que ele mediu obrigou a
acrescentar duas colunas à `handoff_accounts` e a reescrever o caminho do
provisionamento. Os sete factos, todos **CONFIRMADO**, com o registo passo a
passo em [`../docs/evidencia/KAM-019-bot-open.md`](../docs/evidencia/KAM-019-bot-open.md):

1. `pending → open` com o *token* do *agent bot* responde **200**, com
   `"current_status":"open"`. É a pergunta do L7 e dispensa o plano B.
2. O *token* da **Platform API** responde **401** em `/api/v1/accounts/...`:
   «Access to this endpoint is not authorized for bots». Ele cria contas e bots,
   e mais nada.
3. Os *endpoints* da conta querem o `access_token` de um **utilizador** criado
   por `/platform/api/v1/users` e ligado à conta por `account_users`.
4. O *agent bot* tem de ser **ligado ao *inbox*** (`set_agent_bot`). Sem isso, o
   `POST /conversations` responde 404 e o bot não recebe os *callbacks* dele.
5. A conversa quer o `source_id` de um **`contact_inbox` que exista**. Um valor
   inventado responde 404 — e o nosso `contact_id` é, do lado deles, um valor
   inventado.
6. O *token* do bot responde **401** ao criar contactos. Logo o *token* do
   utilizador da conta é preciso **em tempo de execução**, e não só no
   provisionamento: é isso que põe a coluna na tabela.
7. A resposta da criação de contacto tem a forma `payload.contact`, com o
   `source_id` em `contact_inboxes[0]`.

**A lição, porque é maior do que o ticket: um duplo prova que o nosso código
chama o que pretendíamos chamar, não que o terceiro aceita a chamada.** As
baterias que validaram a primeira versão desta emenda estavam certas e estavam
verdes; o que elas nunca podiam dizer é que o Chatwoot responde 401 a metade
delas.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Passagem de uma conversa a um humano | `platform.handoffs` — `handoff_id`, `tenant_id`, `conversation_id`, `status`, `motivo`, `external_id`, `opened_at`, `resumed_at`, `resolver` | **Nove colunas, e o bloco do KAM-019 escreve sete.** As duas que se acrescentam são o `motivo` (o `openHandoff` recebe-o e sem ele a linha não diz porque é que alguém foi chamado) e o `external_id` (o identificador da conversa no provedor, que o `openHandoff` **devolve** e que não tinha onde ficar — sem ele, a segunda chamada não encontra o que a primeira criou fora da nossa base). «PRIMARY KEY (handoff_id)» e FK composta «(tenant_id, conversation_id)» para `conversations` «(tenant_id, id)», pela razão da `0009`: sem a composta, um handoff do *tenant* A podia apontar para uma conversa de B |
| Identificador de uma passagem | `handoffs.handoff_id` = `hash(thread_id, ordinal_do_handoff)` | É a chave de idempotência, e o `../docs/tecnica/01` §11.1 fixa a fórmula. **Não é um UUID gerado por nós**: é derivado, para que duas chamadas concorrentes com a mesma conversa e o mesmo ordinal cheguem ao mesmo valor sem se falarem. O `../docs/tecnica/02` §11 diz porquê em uma frase: o `interrupt()` do LangGraph **re-executa o nó**, logo o `openHandoff` é chamado mais de uma vez por desenho |
| Estado de uma passagem | `handoffs.status` ∈ {`waiting`, `resumed`, `timeout`, `cancelled`, `degraded`} | Cinco, e são **exactamente** os do `../docs/tecnica/02` §11: «Estados de `handoffs`: `waiting → resumed \| timeout \| cancelled \| degraded`, com `opened_at`, `resumed_at`, `resolver` (humano), para o SLA < 15 min por *tenant*». A primeira versão desta linha dizia que o `degraded` «só existe no bloco do KAM-019» e isso era **falso** — o documento que o define não estava na lista que a *discovery* leu, e foi uma segunda leitura, de origem, que o encontrou. O gatilho está na tabela de degradação do mesmo documento, **§14** e não §11: «HND/Chatwoot indisponível → `degraded` → mensagem ao cliente, conversa `pausada`, notificação ao dono por canal alternativo». Sem este estado, uma passagem degradada era indistinguível de uma à espera de humano |
| Desfecho de um `close` | `resolved`, `timeout`, `cancelled` | **Três, contra os cinco do `status`, e a correspondência tem de estar escrita** porque a assinatura do §11.1 usa um vocabulário e a tabela usa outro: `resolved` → `status = resumed`, `timeout` → `timeout`, `cancelled` → `cancelled`. O `waiting` e o `degraded` não são desfechos (são estados de abertura) e o `resumed` não é desfecho de `close` (é o que o `resolved` escreve). Sem este mapeamento, o `close('resolved')` não sabia o que gravar |
| Quem retomou uma passagem | `handoffs.resolver` | Anulável. O `../docs/tecnica/02` §11 define-o em uma palavra — «`resolver` (humano)» —, e o que esta linha acrescenta é a **forma**: só o identificador opaco do agente no provedor, nunca nome, e-mail ou telefone. (A primeira versão desta linha dizia que nenhuma fonte o definia, e era falso.) Não é um `contact_id` da KAMBÁ: um agente de atendimento não é um contacto, não passa pelo módulo de identidade e não tem BSUID. É dado pessoal de um trabalhador da PME, pelo que a coluna é «pessoal: sim» no inventário e não vai a registo nenhum |
| Conta de atendimento de um tenant | `platform.handoff_accounts` — `tenant_id`, `provedor`, `account_id`, `inbox_id`, `bot_id`, `provider_user_id`, `token_ref`, `user_token_ref`, `criado_at`, `updated_at` | **Tabela nova que o bloco do KAM-019 não nomeia e de que o critério 1 depende**: «`ensureAccount` chamado 2× não duplica» exige onde guardar o que a primeira chamada criou, e não havia candidata — a `tenant_channels.token_ref` é do canal Meta. «PRIMARY KEY (tenant_id, provedor)», que é o que torna «uma conta por PME» uma propriedade da base e não do código. **Dez colunas e não oito** (emenda 1.23): o `provider_user_id` e o `user_token_ref` entram porque o spike mediu que os *endpoints* da conta recusam o *token* da plataforma e que o do bot não cria contactos — há um terceiro ator, o utilizador da conta, e o que ele devolve existe **lá fora**, pelo que não guardar os seus identificadores fazia a segunda chamada criar um segundo utilizador |
| Provedor de atendimento | `handoff_accounts.provedor` ∈ {`chatwoot`} | **Um valor, e a coluna existe por causa do ADR-012**, que fixa a costura `HandoffProvider` e diz que o Chatwoot é substituível. Uma tabela chamada `tenant_chatwoot` tornava a substituição uma migração; uma coluna de domínio torna-a uma linha |
| Referência ao *token* do bot | `handoff_accounts.token_ref` | Uma `SecretRef` (§3.9), texto **opaco**, nunca o *token*. É o mesmo desenho da `tenant_channels.token_ref` da `0001` e a instância já está declarada: `chatwoot_bot_token` com `instancias: conta` em `ops/secrets-inventory.yaml`. O `chatwoot_platform_token` **não** entra em tabela nenhuma: tem `instancias: nenhuma` e vive só no módulo de provisionamento, como o `../docs/tecnica/08` §3.6 manda |
| Identificador do utilizador da conta no provedor | `handoff_accounts.provider_user_id` | **`provider_user_id` e não `user_id`**, e a diferença é deliberada: o `account_id`, o `inbox_id` e o `bot_id` são vocabulário do Chatwoot e não colidem com nada nosso, mas a KAMBÁ vai ter utilizadores seus (o painel, KAM-091) e um `user_id` à solta cai na regra da emenda 1.14 — um domínio sobre um nome genérico vale para **todas** as colunas com esse nome. É o utilizador que a Platform API cria e que o `account_users` liga à conta; guarda-se pela mesma razão que o `bot_id`: existe lá fora, e sem a linha que o aponta a chamada seguinte cria outro |
| Referência ao *token* do utilizador da conta | `handoff_accounts.user_token_ref` | Uma `SecretRef` (§3.9), como a do bot. **Duas referências e não uma, e a razão é medida:** o *token* do bot abre e fecha conversas e manda mensagens, mas responde **401** a criar contactos, e a conversa precisa de um contacto que exista. Os dois *tokens* têm alcances diferentes e por isso vivem em instâncias diferentes do cofre (`chatwoot_user_token`, `instancias: conta`). **O que isto não muda:** o `chatwoot_platform_token` continua a não entrar em tabela nenhuma |
| Porta do provedor de atendimento | `HandoffProvider` | **Porta, não implementação**, com as seis operações do `../docs/tecnica/01` §11.1 — `ensureAccount`, `mirrorMessage`, `openHandoff`, `setBotMuted`, `onHumanEvent`, `close`. O KAM-019 entrega a porta e **uma** implementação (Chatwoot); o ADR-012 é o que exige que a porta exista antes de haver duas |
| Mensagem espelhada no provedor | `MirrorMessage` — `wamid`, `MirrorMessage.direccao`, `wa_type`, `texto`, `criado_at` | **Não estava definido em sítio nenhum**: o §11.1 nomeia o tipo e nenhum documento diz os campos. Cinco, e o que **não** está neles é o ponto: sem telefone, sem BSUID, sem `contact_id` — o provedor identifica a pessoa pela sua própria conta de contacto, criada no `ensureAccount`, e o ADR-010 proíbe mandar os nossos identificadores para fora. O `texto` é o corpo que o cliente já leu ou vai ler; não se acrescenta nada que ele não tenha visto |
| Acontecimento humano recebido do provedor | `HumanEvent` — `HumanEvent.acontecimento`, `external_id`, `handoff_id`, `texto`, `mensagemId`, `estado`, `resolver` | Idem: nomeado no §11.1 e nunca definido. **Sete campos e nao seis**: o `mensagemId` — o identificador da mensagem no provedor — entrou porque a resposta humana que sai pelo Outbound (critério 6) precisa de uma chave de idempotência, e derivá-la do **texto** fazia duas mensagens iguais do agente («ok») serem uma só. Sem ele não se envia: uma chave inventada tirava ao `ChannelAdapter` a única coisa que o torna idempotente |
| Sentido de uma mensagem espelhada | `MirrorMessage.direccao` ∈ {`entrada`, `saida`} | **Qualificado, e não o nome nu**, pela regra que a emenda 1.14 escreveu para os nomes genéricos: um domínio sobre um nome como `tipo` ou `estado` passa a valer para **qualquer** coluna com esse nome em qualquer tabela. Medido nesta emenda — a primeira versão desta secção dava domínio a `tipo`, e o *gate* 3b passou a recusar o `CHECK` de `evt_subscricoes.tipo` da revisão `0005` e a declarar mortas duas extensões de `contact_endpoints.tipo`. O nome do campo passou a ser qualificado, e o do `HumanEvent` passou de `tipo` a `acontecimento` |
| Tipo de acontecimento humano | `HumanEvent.acontecimento` ∈ {`mensagem_de_agente`, `estado_mudou`} | Os dois são exactamente os dois *callbacks* que o critério 5 aceita (`message_created` de agente e `conversation_status_changed`); um terceiro que o provedor mande é **recusado**, não ignorado, porque aceitar um acontecimento que não se sabe tratar é deixá-lo passar sem efeito. Chama-se `acontecimento` e não `tipo` pela razão da linha acima |
| Métricas do handoff | `hnd_handoff_total`, `hnd_callback_rejeitado_total`, `hnd_mirror_pendentes` | Três. A `hnd_callback_rejeitado_total` é a que o critério 5 pede pelo nome («devolve 401 e incrementa uma métrica»), com etiqueta `motivo` de lista fechada (`sem_secret`, `secret_errado`, `tipo_desconhecido`, `conta_desconhecida`); a `hnd_handoff_total` leva `desfecho` (os cinco do `status`); a `hnd_mirror_pendentes` é *gauge* e é o que o «healthcheck alerta» do critério 9 lê — uma fila de espelho que cresce é o sintoma de o provedor estar em baixo. **Nenhuma leva `tenant_id`**, pela razão do `OBS-I` já escrita no §3.14 |
| Fila de espelho e de abertura | *nenhum nome novo* | **Não há tabela, e é decisão.** O §14 pede «fila de espelho» que «reconcilia por `wamid`», e isso é exactamente uma fila BullMQ com `jobId` derivado do `wamid`: a reconciliação é a de-duplicação que ela já faz, e o recuo com *jitter* já existe (KAM-005). Uma tabela de fila ao lado de uma fila era um segundo sítio para a mesma verdade. O limite fica dito, e é o mesmo que o `chr/fila.ts` escreveu: um *job* em `failed` **bloqueia** o mesmo `wamid` até sair, pelo que a janela de `removeOnComplete` é o que decide quanto tempo a reconciliação dura |

**As duas divergências que esta emenda assume**, cada uma contra um documento que
diz outra coisa, e as duas devolvidas a quem escreveu o documento
(`../docs/dividas-documentais.md`):

1. **O *compare-and-set* `waiting → resumed` fica fora deste ticket, e há três
   posições na casa — não duas.** A tabela de erros do `../docs/tecnica/01` §11.5
   põe-o no HND («Webhook duplicado `resolved` | Compare-and-set em
   `handoffs.status` (`waiting → resumed`); segundo é *no-op*»); a regra (3) do
   `../docs/tecnica/02` §11 põe o **ponto de entrada** no AGR e a autenticação no
   HND («retoma por `POST /internal/resume {thread_id, handoff_id, outcome}`:
   *compare-and-set* em `handoffs(status: waiting → resumed)` … autenticação da
   origem pelo `secret` do *agent bot* (HND); a invocação `Command(resume=…)`
   corre sob o *lock* da conversa»); e o critério 7 do KAM-019 manda que «o
   `resolved` duplicado não altera nada (a retoma por *compare-and-set* é
   KAM-034)». Segue-se o bloco do ticket, que é a afirmação mais específica sobre
   o âmbito de um ticket (`specs/01` §5). A consequência fica escrita: **a coluna
   `resumed_at` nasce e ninguém a escreve neste ticket**, e isso é melhor do que
   uma coluna que o KAM-034 teria de acrescentar depois a uma tabela com linhas.
   A terceira posição é a que mais interessa a quem fizer o KAM-034: o `02` §11
   diz **onde** o endpoint vive e sob que *lock* corre, e nenhum dos outros dois
   diz isso.
2. **Os *callbacks* do provedor são verificados pelo HND**, e isto é uma
   contradicção entre **dois documentos do mesmo nível**, que é o que a torna
   decisão e não arrumação: o `../docs/tecnica/02` §11, regra (3), diz
   «autenticação da origem pelo `secret` do *agent bot* (HND)» e está do lado do
   critério 5; o `../docs/tecnica/08` §3.6 diz «webhooks de saída do Chatwoot
   assinados e verificados **pelo GWY**». Os dois são `../docs/tecnica/01`–`10`,
   pelo que a ordem de fontes **não desempata**. O que desempata é uma razão de
   desenho que o §3.6 não considerou: o `secret` é **por bot**, logo por
   *tenant*, e o GWY é o único ponto que não tem contexto de *tenant* antes de
   resolver o canal — era o CHR ao contrário. **E o ADR-001 não resolve isto**:
   diz «GWY como único endpoint de webhook **da Meta**», com o Chatwoot nomeado
   como espelho, pelo que o *callback* do Chatwoot está fora do seu âmbito.

**O que esta secção NÃO decide.** O `setBotMuted` **não é executável** e a secção
di-lo em vez de o esconder: `kamba_app` não tem `UPDATE (mode)` em
`conversations` (revisão `0009`, que escreveu a razão — «um privilégio concedido
para quando for preciso é um privilégio que ninguém volta a tirar») e as
transições de modo são do KAM-018. A revisão `0011` **não** concede esse
privilégio; a porta fica na interface e levanta, com teste a prová-lo, e a caixa
do critério fica vazia. Também não decide: onde o provedor é alojado (**D1**, e
o provedor trata dados pessoais), o nó de grafo `handoff_prepare`/`handoff_wait`
e a retoma (KAM-034), o provisionamento orquestrado (KAM-091), o aviso ao dono
por um segundo número (NÃO VERIFICADO, fora do bloco). **O `pending_reply`
deixou de ser um problema desta secção enquanto ela se escrevia:** a *discovery*
deste ticket encontrou-o numa única linha do repositório inteiro — o fecho do
`../docs/tecnica/01` §14, a mandar registá-lo, sem dicionário, coluna nem
código — e o **KAM-160** resolveu-o pelo outro lado, fazendo o §14 deixar de o
mandar. Fica aqui a nota porque era defeito e não resíduo (obrigava a escolher
entre criar a coluna ou emendar o documento), e porque é o género de lacuna que
só aparece a quem for implementar: dois tickets antes, ninguém a tinha visto.

---

### 3.16 Mídia recebida: descarga, armazenamento e URL interna (KAM-020)

*Emenda 1.24, **proposta**.* Entra porque a revisão `0012` cria DDL e o §1 declara
defeito um nome de DDL fora deste dicionário. A fonte do desenho é
`../docs/tecnica/01` §5.4 (a tabela de tipos de entrada), `../docs/tecnica/08`
§3.8 (isolamento do armazenamento) e §7.5 (áudio e dados sensíveis), com os
ADR-013 e ADR-014; onde esta secção divergir, a divergência está escrita na
linha.

**Todas as referências de secção aqui foram conferidas contra os cabeçalhos
`## ` do ficheiro**, pela lição que a §3.15 pagou.

**Doze destes nomes não estavam no canon**, e a conta importa porque a
primeira versão desta linha dizia «dez» e enumerava doze: a tabela, cinco das
suas colunas (`classe`, `content_type`, `size`, `sha256`, `storage_ref`), o
`asset_id`, a forma `media://`, o gancho `onTranscribed` e as três métricas.
A palavra «media» não ocorria uma única vez em `canon/dicionario.yaml`.

**E «nem em código» era falso para dois deles**, o que a própria secção diz
três parágrafos abaixo: a `classe` e o `sha256` existem desde o KAM-011, no
`validarClasse` e no `ObjectRef.sha256` da porta. O que não existia era a
entrada no dicionário, e é isso que esta emenda corrige.

**E o que já existe não se reinventa.** O `StorageProvider` do KAM-011 está
feito nas duas linguagens, com duplo e bateria de contrato, e o MED é o seu
**primeiro consumidor**. Esta secção nomeia as colunas da tabela; os nomes da
porta são os do §3.11 e não se duplicam aqui. Em particular: o `size` desta
tabela é o `ObjectRef.tamanho` da porta, e o `sha256` é o `ObjectRef.sha256` —
**dois vocabulários para o mesmo valor**, pela mesma razão que o §3.12 aceitou
`wa_type`: a coluna segue o critério de aceitação do ticket, e a porta segue o
seu próprio.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Objecto de mídia recebido | `platform.media_assets` — `asset_id`, `tenant_id`, `contact_id`, `conversation_id`, `wamid`, `media_id`, `classe`, `content_type`, `size`, `sha256`, `storage_ref`, `estado`, `retain_until`, `criado_at` | **Catorze colunas e não onze**, e as três a mais vêm do próprio ticket. O `media_id` porque o critério **2** pede a unicidade de `(tenant_id, wamid, media_id)` e o critério 1 não o lista — a contagem do critério 1 não fecha com a do 2, e é a primeira coisa que esta linha corrige. O `asset_id` porque o critério 5 emite `media://{asset_id}` e não havia chave de onde o tirar. O `criado_at` pela convenção de todas as tabelas do §3 |
| Identificador de um objecto de mídia | `media_assets.asset_id` | `uuid` gerado, e aqui **não** é derivado — ao contrário do `handoffs.handoff_id` (§3.15). A razão é a diferença de quem o produz: a passagem a humano precisa de uma chave a que cinco processos cheguem sem se falarem, e aqui a idempotência é a `UNIQUE (tenant_id, wamid, media_id)`, que já existe e já é derivada do que a mensagem traz. Uma segunda chave derivada seria o mesmo facto duas vezes |
| Referência interna a mídia | `media://{asset_id}` | A forma que os consumidores guardam e passam entre si. **Nunca o URL da Meta e nunca a chave do objecto:** a chave é do armazenamento e muda se a classe ou o molde mudarem; o `asset_id` é nosso e não muda. Quem precisa de ler pede `signUrl` à porta (§3.11), com TTL ≤ 300 s — que é o `TTL_MAXIMO_S` que a porta já impõe, pelo que o critério 5 do KAM-020 **não precisa de número novo** |
| Classe de um objecto de mídia | `media_assets.classe` ∈ {`media_audio`, `media_imagem`, `media_documento`} | **Qualificado, e não o nome nu**, pela regra da emenda 1.14: um domínio sobre um nome como `classe` ou `estado` passa a valer para **qualquer** coluna com esse nome em qualquer tabela, e a dívida 41 já registou esse risco. **E os valores levam o prefixo «media_» de propósito, porque é o que resolve a divergência da linha 8 das dívidas:** o bloco do KAM-020 escreve a chave como `t/{tenant_id}/media/{classe}/{aaaa}/{mm}/{uuid}`, com um segmento a mais que a porta **recusa** hoje (`validarClasse`, `[a-z][a-z0-9_]{1,31}`). Em vez de mudar a porta — que está feita, testada e tem o X-08 na sua bateria de contrato — a classe passa a dizer que é mídia, e a chave fica `t/{tenant_id}/media_audio/{aaaa}/{mm}/{uuid}`: **um segmento, três classes, e nenhuma alteração ao KAM-011**. A lista de classes é do primeiro consumidor, e o §3.11 di-lo por escrito |
| Estado de um objecto de mídia | `media_assets.estado` ∈ {`pendente`, `armazenado`, `rejeitado`, `falhou`} | Qualificado, pela mesma regra — e aqui não é cautela: há **cinco** colunas `estado` com `CHECK` nas revisões `0001`, `0003` e `0005`, e um domínio nu tornaria as cinco vermelhas e mataria a extensão «hmac_key_versions.estado=retirada» do `../canon/extensoes.yaml` — e escreve-se em guillemets e **não** em *backticks* de propósito, porque um nome em *backticks* numa coluna de nota entra no conjunto de nomes conhecidos, e a mera menção fazia a extensão deixar de ser consultada e o *gate* declará-la morta. É a lição que o «PRIMARY KEY» da §3.14 pagou, noutra roupagem — e escreve-se aqui em guillemets pela mesma razão que lá, porque a revisão adversarial apanhou-o **em backticks nesta própria frase**, a narrar a lição. É a medição que a emenda 1.22 descreve para o `tipo`. **O `pendente` não está no ticket e é a linha que torna a idempotência verdadeira:** o `wamid` e o `media_id` são conhecidos **antes** da descarga, pelo que a linha se escreve primeiro e o segundo chamador perde o `ON CONFLICT` e **não descarrega** — ao contrário do `ensureAccount` do §3.15, que não podia escrever primeiro porque precisava de identificadores que só a criação devolve |
| Desfecho de uma descarga que não deu | `rejeitado` (tipo ou tamanho fora da *allowlist*) e `falhou` (três tentativas sem sucesso) | **Dois estados e não um**, e a diferença é operacional: um `rejeitado` pede ao cliente outro formato e nunca melhora sozinho; um `falhou` é do nosso lado ou do da Meta e pode ser retomado. Juntá-los fazia o painel mandar a PME pedir outro ficheiro quando o problema era nosso. **E `falhou` é a quarta grafia da mesma ideia no conjunto** — `falhado` em `image_jobs`, `falhada` em `evt_acoes`, e `falhou` aqui, que é a única forma **verbal** entre estados que são particípios ou adjectivos. Segue-se o bloco do ticket, que é a afirmação mais específica sobre os seus nomes, e a escolha de uma só grafia fica para quem ratifica: está em `../docs/dividas-documentais.md` |
| Tipo de conteúdo aceite | `media_assets.content_type`, com *allowlist* | Os valores são **proposta** e calibram-se contra os limites da Meta, que **não têm evidência nenhuma**: o `E1` não tem a página da API de mídia e **nem a lista como omissão**. A *allowlist* do ticket (JPEG, PNG, WebP, OGG/Opus, PDF) entra como proposta, em configuração e não em literal, pela razão que o KAM-015 escreveu para a versão da Graph: quem a muda é quem opera |
| Retenção de um objecto | `media_assets.retain_until` | Já existe no §3.11, como «metadado obrigatório de todo o objecto». O que esta linha acrescenta é **de quando conta**, porque as fontes discordam: o `../docs/tecnica/08` §7.5 diz «apagar o blob após sucesso (alvo ≤ 24 h; limite de erro 72 h)» e o critério 7 do ticket diz «`retain_until` = criação + 24 h». **Fica a do ticket, e é a única leitura auto-consistente:** contar da transcrição faz o prazo nunca chegar quando a transcrição nunca tem sucesso, que é precisamente o caso em que o áudio não devia ficar. É a mesma classe de releitura que o critério 6 do KAM-015 obrigou |
| Gancho de transcrição | `onTranscribed(asset)` | Porta, não implementação: o KAM-020 **agenda** a eliminação e a purga é KAM-071. Fica nomeado aqui porque dois tickets o citam e nenhum o define |
| Bytes armazenados | `media_bytes_total`, etiqueta `classe` | *Counter*. A etiqueta é a classe e **não** o `content_type`: três valores contra uma lista aberta, e uma etiqueta de cardinalidade aberta é o que o `OBS-I` do `../docs/seguranca/ameacas_stride.md` proíbe |
| Latência da descarga | `media_download_ms` | *Histogram*, sem etiqueta de *tenant* — pela mesma regra, e é decisão escrita: um `tenant_id` como etiqueta **levanta** |
| Rejeições | `media_rejected_total`, etiqueta `motivo` | *Counter*, com lista **fechada** de motivos pela mesma razão que os quatro do §3.15: um motivo livre numa etiqueta é cardinalidade aberta |

#### Divergências que esta secção registra e não resolve

1. **A contagem do critério 1 não fecha com a do critério 2** — onze colunas
   listadas, e a unicidade do 2 exige uma décima segunda (`media_id`) que a
   lista não tem. Corrigido aqui por acrescento, e devolvido a quem escreveu os
   critérios.
2. **A API de mídia da Meta não tem evidência nenhuma** — nem tamanho máximo,
   nem expiração do URL, nem o fluxo de duas etapas, nem os códigos de erro. O
   `E1` não a tem e não a lista como omissão. **Três critérios (4, 6 e a
   *allowlist*) ficam com números *proposta***, e o sítio onde calibram está
   dito em cada um.
3. **A chave do critério 1 não é construível com a porta do KAM-011** (dívida
   8). Resolve-se pela classe, como a linha acima explica, sem alterar o
   KAM-011 — mas a divergência textual entre os dois blocos **fica**.
4. **Quatro grafias para «falhou»** no conjunto, e nenhum árbitro: o §2 fixa
   minúsculas, `snake_case` e sem acentos, e não desempata género nem tempo
   verbal.
5. **O EXIF/GPS tem dois donos e nenhum critério.** O `../docs/tecnica/03` §8.2
   atribui a remoção ao MED, o bloco do KAM-020 não a menciona, e o KAM-049
   repete-a. Não se faz aqui, e a razão é a regra de escopo: um critério que não
   existe não se inventa.
6. **O caminho `token_ref` → cofre → cabeçalho de autenticação não existe em
   código e nenhum ticket o declara seu.** O KAM-020 precisa dele para
   descarregar, e os seus *Detalhes Técnicos* dizem «com o token do canal
   (cofre)» sem o nomear como entrega.
7. **O `sticker` é tratado como mídia e o `../docs/tecnica/01` §5.4 manda
   ignorá-lo.** A linha dele diz «`reaction`, `sticker`, `unsupported` |
   **Ignorar com contagem**», e manda ao MED apenas `audio`, `image` e
   `document`. O `CLASSE_POR_WA_TYPE` mapeia-o para `media_imagem`, e a razão é
   a retenção: do ponto de vista do armazenamento um *sticker* é uma imagem, e
   uma quarta classe multiplicava a política do KAM-071 sem mudar nada. **O
   custo é real e fica dito:** cada *sticker* recebido passa a gastar duas
   chamadas à Meta, um objecto no armazenamento e uma linha na tabela, contra o
   que o canon diz. Esta divergência faltava nesta lista, e foi a revisão
   adversarial que a encontrou — numa secção cujo preâmbulo promete que «onde
   esta secção divergir, a divergência está escrita na linha».
8. **O limite de tamanho só morde depois de os bytes estarem em memória**,
   quando a Meta não anuncia o tamanho. O `MidiaResolvida.tamanho` é lido e
   recusa antes de descarregar **se vier**; se não vier, a *allowlist* corre em
   `bytes.byteLength`, isto é, depois de materializar o objecto inteiro. O
   `../docs/tecnica/08` §4.2 nomeia «Upload gigante → limites» como controlo de
   negação de serviço do MED, e isto cumpre-o só quando o anúncio existe — e se
   ele existe é matéria do `E1`, que não a tem.
9. **A repetição de um objecto já rejeitado responde sempre «outro formato»**,
   mesmo quando o problema foi o tamanho: a base não guarda o motivo (o `estado`
   tem quatro valores e nenhum deles é um motivo), e a métrica que o guarda é
   agregada. Quem mandou um áudio de 20 MiB e reenvia a mesma mensagem recebe a
   frase do tipo errado — determinística, como o critério 4 pede, e errada. Uma
   coluna de motivo resolve-o, e não se acrescenta aqui porque o critério não a
   pede.
10. **A «deduplicação por conteúdo» dos *Detalhes Técnicos* não está feita**, o
    que é legítimo — ela é explicitamente «opcional» — mas não estava declarado
    em sítio nenhum. Não há índice por `sha256` nem consulta que o procure, nem
    a «contagem» que o ticket lhe pede. O `test_media_schema.py` argumenta a
    partir dela («duas grafias do mesmo resumo faziam a deduplicação por
    conteúdo falhar») como se existisse; o argumento vale para o futuro.
11. **O «Teste Requerido» de integração com a Graph falsa (KAM-024) não se
    cumpre**, e é decisão: o simulador não serve os *endpoints* de mídia (o `id`
    que ele põe no webhook não é resolúvel), pelo que o `ClienteDeMidia` entra
    por porta. A dependência do bloco continua a nomear o KAM-024, e lido de
    fora parecia coberto.

---

### 3.17 Monitorização do free tier de service messages (KAM-023)

*Emenda 1.25, **proposta**.* Entra **sem DDL**, e isso é o que a distingue das três
secções anteriores: as duas colunas que o ticket mantém existem desde a revisão
`0001` e já estão em «canon/extensoes.yaml» (emenda do KAM-003). O que entra aqui
são **nomes de métrica** e um domínio de nível de alerta, pelo precedente que o
§3.10 abriu para as métricas do *logger* — «entram aqui porque todos os serviços
os escrevem», e estas entram porque o painel de custos (KAM-081) as consome.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Fracção do *free tier* consumida, no canal mais perto do tecto (*gauge*) | `meta_free_tier_used_ratio` | O critério 4 escreve-a com etiqueta de *tenant*. **Não leva nenhuma** — ver «As duas divergências», abaixo. Sem etiqueta, um *gauge* teria de ser o valor do último canal observado, que não é o de nenhum; é por isso o **máximo** sobre os canais, que é a pergunta que um alerta de 80% faz. A média respondia-a mal: um canal a 100% entre dez a zero dá 10%. Vale `-1` antes da primeira observação, como os *gauges* do §3.14 |
| Custo estimado acima do *free tier*, em micro-dólares inteiros, somado sobre os canais (*gauge*) | `meta_cost_usd_estimate` | `max(0, n − 1000) × 4 000` micro-dólares. **Não é a `meta_cost_usd_total` do §3.14 com outro nome, e a diferença é o ticket inteiro:** aquela é o que a Meta disse ter cobrado, somado do *pricing* de cada *status*; esta é o que nós estimamos a partir do nosso contador. São duas grandezas e a **diferença entre elas é o que o critério 7 manda reconciliar** — com uma só, não havia contra o que reconciliar. O nome diz `usd` e a unidade é o micro-dólar, pela razão do §2 e do §3.14 |
| Avisos de *free tier* emitidos (contador) | `meta_free_tier_alert_total` | Leva a etiqueta «nivel», de dois valores. Não está no critério 4 e está aqui pela razão da `outbound_rate_limited_total` (emenda 1.21) e do `gwy_shed_total` (1.19): **avisar sem contar é avisar em silêncio**. O critério 3 afirma «1 aviso aos 800 e 1 aos 1.000, sem repetição no mesmo mês», e sem este contador não há como verificar, depois do facto, que saiu um e não zero nem duzentos |
| Nível de um aviso de *free tier* | `aviso`, `esgotado` | Lista fechada. `aviso` é a travessia de 80% do tecto (800 com o tecto de 1.000 do `E1` §1); `esgotado` é a travessia do tecto. Minúsculas e sem acentos porque entram como etiqueta e o §2 manda-o — e porque um sufixo que não case `^[a-z][a-z0-9_]{1,62}$` é recusado por gramática. **O 800 é derivado do tecto e não escrito:** se a Meta mudar o tecto, o aviso acompanha-o |
| Porque é que um canal está restrito | `tenant_channels.motivo_restricao` ∈ {`payment_method`, `quality`, `policy`} | Revisão `0013`. **Anulável, e o `NULL` é o estado normal** — «este canal não está restrito»; um `NOT NULL DEFAULT 'nenhum'` acrescentava um quarto valor ao domínio só para dizer a ausência. Só o `payment_method` é deste ticket; o `quality` é do KAM-021 e o `policy` do KAM-017, e **nascem na mesma revisão** pela mecânica que a emenda 1.20 pagou e a `0010` repetiu para o `suppressed_by_human` — o *gate* 3b lê o `CHECK` de cada revisão isoladamente, pelo que alargar o domínio depois deixava a `0013` vermelha. O `CHECK` é **qualificado pela tabela** (`tenant_channels_motivo_restricao_ck`), pela regra da emenda 1.14: um domínio sobre um nome genérico valeria para as cinco colunas `estado` das revisões `0001`, `0003` e `0005`. **Não muda o `estado` do canal** — passar uma loja a `restrito` por uma heurística de limiares *propostos* era cortar-lhe o atendimento; quem restringe de facto é o KAM-021 e o KAM-094 |
| Códigos de erro que a Meta já devolveu num canal | `tenant_channels.meta_error_codes_seen` (`integer[]`) | Revisão `0013`, `NOT NULL DEFAULT '{}'`, com tecto de **32** códigos distintos por `CHECK` (*proposta*: o `E1` nomeia três códigos e não há base para saber quantos existem). **Coluna e não tabela**, por três razões: o X-03 passa a ser o de `tenant_channels`, que já corre (uma tabela nova com `tenant_id` que a *suite* não saiba semear **falha o *gate* 6**); o conjunto não tem história — o critério quer saber **quais** códigos apareceram, não quando nem quantas vezes; e os códigos da Meta são inteiros, que um `jsonb` punha num saco onde a base não sabe que são números. O tecto não é defensividade gratuita: a coluna é escrita pelo caminho de um *webhook* e é lida em cada envio |
| Suspeitas de método de pagamento ausente ou inválido (contador) | `meta_payment_suspect_total` | Mesma razão do anterior, e vale mais: a detecção do critério 5 é uma heurística de limiares **propostos** (20% de falhas em 20 mensagens, depois do tecto esgotado), e sem a contar não há como os calibrar. O código de erro concreto com que a Meta recusa por falta de pagamento é **NÃO VERIFICADO** — o `E1` nomeia três códigos e nenhum é de pagamento —, e é por isso que a detecção é sobre a taxa e não sobre um código |

**As duas colunas entraram na emenda 1.26, e não nesta.** Quando a 1.25 se
escreveu, a revisão que as cria ainda não podia existir: ela descende da `0012`
do KAM-020, e as revisões de base encaixam uma na anterior. Não se
pré-declararam — «canon/extensoes.yaml» diz que «uma extensão que nenhuma
superfície usa falha o gate», e o mesmo argumento vale para um nome do
dicionário sem DDL que o use. A metade de código do ticket entrou primeiro, sem
esperar; estas duas linhas entraram com a `0013`.

**As duas divergências assumidas**, cada uma contra um documento que diz outra
coisa:

1. **As métricas ficam sem etiqueta de *tenant*, contra o critério 4** — que
   escreve `meta_free_tier_used_ratio{tenant}` e `meta_cost_usd_estimate{tenant}`.
   A decisão **não é nova**: é a que a emenda 1.21 já tomou para a
   `meta_cost_usd_total{tenant}` do KAM-015, e decidir ao contrário a dois
   módulos de distância era pôr o conjunto a contradizer-se. As bibliotecas de
   métricas deste repositório recusam por gramática uma etiqueta que não case
   `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID com hífenes que muitas
   vezes começa por dígito — **a chamada levanta**. A razão de fundo é o `OBS-I`
   de `../docs/seguranca/ameacas_stride.md` e o X-11 do *gate* 6. O por-*tenant*
   e o por-canal saem de consulta, que é o caminho que o `../docs/tecnica/01`
   §16 já aponta. **As caixas do critério 4 ficam, por isso, parcialmente
   satisfeitas**, com esta razão escrita na secção de verificação do ticket.
2. **O mês reinicia no fuso do *tenant*, e o critério 3 diz «do canal».** O
   critério escreve «reinício à meia-noite do fuso configurado do canal
   (`Africa/Luanda` por omissão)». Não há coluna de fuso em «tenant_channels» —
   a única do esquema é «tenants.fuso_horario», que é por *tenant*, pelo que um
   *tenant* com dois números não pode hoje ter dois fusos. O que se usa é a
   função «platform.ten_periodo» da revisão `0007`, que é onde o fuso vive **num
   sítio** por decisão escrita do KAM-009; reimplementar a fronteira em
   TypeScript era a quarta cópia a divergir. Configurá-lo por canal é DDL e fica
   com a mesma revisão dos critérios 5 e 6.

**E uma divergência de atribuição, que não muda nenhum número.** O bloco do
ticket escreve «Alvo do doc 00: alertas aos 80% (800)». O `../docs/tecnica/00`
§9 não dá limiar nenhum — diz só «*service messages* > 1.000/mês a 0,004 USD». O
80% vem do `../docs/tecnica/08` §3.7 e do `../docs/tecnica/09` §9 (RB-K05). O
valor é unânime em dez afirmações do conjunto; só a atribuição está errada, e
está registada em `../docs/dividas-documentais.md`.

---

### 3.18 Qualidade do canal, estado `restrito` e limites (KAM-021)

*Emenda 1.27, **proposta**.* Entra porque a revisão `0014` cria DDL e o §1 declara
defeito um nome de DDL fora deste dicionário. A fonte do desenho é
`../docs/tecnica/01` §9 e o `../docs/tecnica/evidencia/E1` §5; onde esta secção
divergir, a divergência está escrita na linha.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Transição de qualidade de um canal | `platform.channel_quality_log` — `id`, `tenant_id`, `channel_id`, `evento`, `valor_anterior`, `valor_novo`, `ocorrido_em`, `event_key` | Oito colunas, e o bloco do ticket pede sete — acrescenta-se o `id`, porque a chave de negócio é a `event_key` e o §2 pede `uuid` para a coluna que identifica. **Vive em `platform.`** e leva FK **compostas** com o `tenant_id`, pela razão que a `0009` fixou. A aplicação tem `SELECT` e `INSERT` e **não tem `UPDATE`**: uma linha é o facto de a Meta ter dito uma coisa a uma hora, e um facto não se corrige — é a mesma forma do `usage_ledger` do §3.9 |
| Chave de idempotência de uma transição | `channel_quality_log.event_key`, com `UNIQUE (tenant_id, event_key)` | O critério 6 pede o resumo de `phone_number_id` + tipo + valor + marca temporal da Meta. **Composta com o `tenant_id`** e não global, pela razão da emenda 1.21: com unicidade global, um evento do *tenant* B que calhasse na mesma chave era deduplicado em silêncio contra uma linha de A. É o **segundo** nível — o primeiro é o `inbound_events (kind, event_key)` do §3.12 — e existe porque registar e encaminhar não são atómicos (KAM-013) |
| *Webhook* de gestão de canal | `channel_quality_log.evento` ∈ {`phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_quality_update`} | **Quatro, e são exactamente os quatro `kind` que o §3.12 manda para o destino `gestao_de_canal`.** Três cópias do mesmo domínio — o `KIND_POR_CAMPO` do KAM-013, este `CHECK` e a lista do módulo — e um teste que as confronta, porque três cópias divergem no dia em que uma mudar |
| Valor que a Meta anunciou, tal e qual | `channel_quality_log.valor_novo` | **Guarda o bruto e não o canónico**, e é o centro do critério 1: «outro valor registado como desconhecido sem falhar». Um domínio fechado nesta coluna transformava uma mudança da Meta numa falha de inserção — e ela já mudou este vocabulário uma vez (o «Flagged» foi eliminado a 2025-10-07, CONFIRMADO `E1` §5). O canónico vai para o «tenant_channels.quality_rating», e a tradução é uma função com teste, como o `wa_type` do §3.12 |
| Tecto de números do portfólio | `tenant_channels.max_phone_numbers_per_business` (`integer`, anulável) | Do `business_capability_update`. É atributo da **WABA** e não do canal: guarda-se por canal porque não há tabela de WABA neste esquema, e dois canais da mesma conta guardam o mesmo número — desnormalização assumida. **O nome tem «phone» e a coluna não guarda telefones**, e é por isso que está declarada na `COLUNAS_DE_TELEFONE_ACEITES` do `test_catalogo.py`: num `integer` não cabe um E.164, o que é garantia mais forte do que a do `phone_number_id`, que é `text` |
| Motivo de restrição por qualidade | `tenant_channels.motivo_restricao = 'quality'` | O valor já está no domínio que a revisão `0013` criou (§3.17, KAM-023). **Cada ticket levanta apenas o motivo que põe:** o `SQL_REPOR` deste leva `motivo_restricao = 'quality'` no predicado, porque um canal restrito por falta de método de pagamento continua a ter qualidade e repô-lo era desfazer a decisão de outro ticket |
| Recusa de envio pelo estado | `STATE_REFUSED` | **Acrescenta-se aos dez `MOTIVOS_DE_RECUSA` do §3.14**, que passam a **onze**. Um motivo e não um por estado: o que recusa é a matriz do §3.7, que decide por um **regime** saído do par (estado do *tenant*, estado do canal) — um motivo por estado dava seis etiquetas de métrica para uma causa só. O nome segue o `estado_recusou` dos `DESFECHOS` do §3.13, que é a mesma decisão do outro lado do caminho |
| Canais em cada qualidade (*gauge*) | `channel_quality` | Etiqueta `rating`, de **três** valores fechados — e é por isso que ela passa onde a de *tenant* das emendas 1.21 e 1.24 não passava: o `OBS-I` recusa identificadores, não dimensões pequenas. *Gauge* e não contador, e **sem `_total`**, porque um canal que melhora sai de uma série e entra na outra: um `_total` que desce é um contador que mente |
| Fracção do escalão consumida (*gauge*) | `messaging_limit_usage_ratio` | Utilizadores únicos contactados por template em **24 h móveis** ÷ tecto do escalão. Móveis e não «hoje» (CONFIRMADO, `E1` §5), e é por isso que **não** usa a `platform.ten_periodo` do §3.9: o mês do *free tier* reinicia à meia-noite de um fuso, este não reinicia. Vale `-1` antes da primeira observação **e também** quando o escalão não se reconhece — «não sei» não é «está folgado» |
| Transições para `restrito` (contador) | `channel_restricted_total` | Etiqueta `motivo`, com o domínio **inteiro** do `motivo_restricao` e não só o `quality`: a métrica é do canal e não deste ticket, e quando o KAM-023 ou o KAM-017 restringirem contam na mesma série. Leva `_total` porque é monótono |
| *Webhooks* de canal tratados (contador) | `channel_quality_event_total` | Etiqueta `evento`, de quatro valores. Não está no DoD e entra pela razão da `outbound_rate_limited_total` da emenda 1.21: **tratar sem contar é tratar em silêncio**, e sem a etiqueta um painel não distingue «a Meta não mandou nada» de «mandámos tudo para o braço errado» |

**Três divergências assumidas**, cada uma contra um documento que diz outra
coisa:

1. **O `tenants.estado` não projecta `restrito`, contra o critério 3.** A
   revisão `0007` (KAM-009) retirou o `UPDATE (estado)` a `kamba_app` de
   propósito, com a razão escrita lá — «`UPDATE platform.tenants SET estado =
   'ativo'` com o próprio contexto **passa** […] o sujeito da condição não pode
   ser quem a retira» — e o `db/tests/test_privilegios.py` prende-o. Nenhum dos
   papéis que o *worker* de canal tem pode escrever ali; só o `kamba_batch`.
   Devolver o privilégio reabria exactamente a escalada que a revisão
   adversarial do KAM-009 fechou. **A caixa fica vazia** e a decisão devolve-se
   a quem escreveu o critério.
2. **A matriz recusa também a `utility` sob `restrito`, e o critério 2 só nomeia
   a `marketing`.** A linha `restrito` do §3.7 tem
   `enviar_template_utilidade: false`, e usa-se a matriz porque é o que o
   critério 9 pede por extenso — «o CHR usa a matriz de KAM-009». Ela é **mais
   restritiva** do que a frase, que é o lado seguro; mudá-la era mexer numa
   decisão do KAM-009 que tem espelho em Python e paridade imposta pelo X-11.
3. **Os nomes dos escalões são os do gerador do KAM-024 e não os do bloco.** O
   critério 5 dá o exemplo `TIER_250 → TIER_2000` e o
   `tools/meta-sim/src/campos.ts` gera `TIER_2K`. Usa-se o do gerador, que é a
   única fonte deste repositório que corre, e **não se inventa um sinónimo**: um
   escalão fora do mapa é desconhecido e o rácio fica `null`. Fica em
   `../docs/dividas-documentais.md`.

**O que esta secção não declara, e é escopo e não esquecimento.** Não há nome
para «*ticket* de T&S» (critérios 4 e 8): não existe mecanismo de *ticket* neste
repositório, e o que existe — contadores e registo — é o que se usa, como o
KAM-023 fez para o aviso do *free tier*. Quem notifica é o KAM-115. E não há
coluna de fuso por canal, que o KAM-023 já registou na dívida 66: o medidor
deste ticket não precisa dela, porque as 24 h são móveis e não fecham em
meia-noite nenhuma.

---

### 3.19 Consentimento no 1.º contacto: o texto, a prova e a barreira (KAM-022)

*Emenda 1.28, **proposta**.* A `consent_event` e o domínio de dez finalidades
**já estavam** no §3.1 (emendas 1.8 e 1.16); o que entra aqui é o que a revisão
`0015` cria de novo e o vocabulário do gate. A fonte do desenho é
`../docs/tecnica/10` §7.2 (o DDL de referência, reconciliado pelo KAM-140),
`../docs/tecnica/06` §7.3 (o índice e a vista) e o `../docs/tecnica/evidencia/E3`;
onde esta secção divergir, a divergência está escrita na linha.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Texto do aviso, versionado | `platform.consent_texts` — `version`, `purpose`, `texto`, `hash`, `vigente_desde`, `criado_em` | **Não tem `tenant_id`, e é decisão.** O aviso é um texto jurídico revisto uma vez e mostrado por todas as lojas; dar-lhe uma coluna de *tenant* dizia que cada loja pode ter o seu, contra «o texto final em PT-AO é revisto juridicamente» do bloco. Consequência directa: **não entra no X-05 nem no `../ci/rls_exceptions.yaml`** — o *gate* 6 pergunta por RLS às tabelas que **têm** a coluna. A chave é natural, «version» + «purpose»: duas finalidades podem ter avisos diferentes na mesma versão. Nasce **vazia** (ver a nota do `vigente_desde`) |
| Finalidade que um aviso descreve | `consent_texts.purpose` ∈ {`transacao`, `atendimento`, `marketing`, `analytics_agregado`, `melhoria_servico`, `sugestoes_patrocinadas`, `partilha_loja`, `partilha_parceiros`, `partilha_estafeta`, `notificacao_dono`} | **O mesmo domínio do «consent_event.purpose» do §3.1, declarado outra vez — e a repetição é obrigatória e não redundante.** Os domínios deste dicionário são **qualificados pela coluna** (a decisão é da emenda 1.14), pelo que o *gate* 3b não reconhece em `consent_texts.purpose` os dez valores que só estão declarados em «consent_event.purpose»: mediram-se **nove achados** `fora-do-dicionario` na primeira versão desta secção, um por cada valor que não é o `marketing` — esse passa porque está declarado por si em outro sítio. O que **não** se fez foi declará-los em `../canon/extensoes.yaml`, que é o que a mensagem do gate sugere: uma extensão é para um nome que o dicionário não tem, e estes tem — o que faltava era a linha que os liga a esta coluna | 
| Versão vigente de um aviso | a linha de `consent_texts` com `vigente_desde` mais alto que já passou | Uma versão publicada com data **futura** não vigora, e é assim que um texto novo se publica antes de valer. A tabela nasce vazia porque o texto está «a confirmar por parecer» (KAM-104), e o gate trata a ausência como **falha fechada**: sem aviso para mostrar não há consentimento a registar e o AGR não corre. O efeito é uma loja muda até o texto existir, e é o lado certo — a alternativa era tratar dados sem ter mostrado o aviso, que é o que o ADR-010 proíbe |
| Marcador do nome da loja no texto | `{loja}` | O texto é de plataforma e o aviso tem de nomear o responsável (`E3` req. 15). O que se mostra é o texto **preenchido**, e é esse que a prova cobre — ver a linha do `evidence_hash`. Um texto sem marcador passa sem mudar e **não levanta**: um aviso que não nomeie a loja é um defeito de quem o escreveu, e quem o apanha é o parecer, não um erro que deixa o cliente sem resposta |
| Hora em que a plataforma escreveu a prova | `consent_event.registado_em` (`clock_timestamp()`) | **É o desempate da vista, e entrou porque a primeira versão desta secção afirmou uma coisa falsa:** que um empate no «ocorrido_em» dentro do trio era impossível «pela unicidade da prova». A unicidade é sobre o `evidence_hash`, e **a hora que a Meta manda tem resolução de segundos** — dois cliques no mesmo segundo dão o mesmo instante com `wamid` diferentes, entram as duas linhas, e a vista desempatava pelo `uuid` aleatório: o ensaio contra a base escolheu a `v2` numa máquina e a `v1` no CI, com os mesmos dados. O par «ocorrido_em»/`registado_em` é o mesmo que o envelope de evento do §3.5 já usa. **`clock_timestamp()` e não «now()», e é a única coluna do esquema que o usa:** o `now()` é o início da transacção e empatava também | 
| Estado corrente do consentimento | `platform.consent_actual` (vista) — «tenant_id», «contact_id», «purpose», `accepted`, «text_version», «ocorrido_em» | **A primeira vista do esquema**, e do `../docs/tecnica/06` §7.3. `DISTINCT ON (tenant_id, contact_id, purpose)` com `ORDER BY ... ocorrido_em DESC, registado_em DESC, id DESC` — **três critérios, e o segundo é o que torna a ordem total** (ver a linha acima). Leva **`security_invoker = true`**, e isso não é decorativo: uma vista corre com os privilégios do **dono**, e o dono está sujeito a RLS só por causa do `FORCE` — a opção põe a vista a correr como quem a consulta, que é o que a política pressupõe. O `verificar_vistas` do *gate* 6 exige-o a qualquer vista, **sem lista de excepções**, e existe desde o KAM-004 sem nunca ter tido nada para ver. **Não mostra o `evidence_hash` nem o «canal»**: quem pergunta «aceitou?» precisa da resposta, não da prova |
| Chave da prova, e a sua idempotência | `consent_event` com `UNIQUE (tenant_id, contact_id, purpose, evidence_hash)` | É o critério 2 — «o mesmo botão repetido 2× produz 1 linha» — e é **da base**. O que a torna suficiente é a composição do resumo: o `wamid` e a hora são **da Meta**, pelo que uma reentrega do mesmo *webhook* dá o mesmo valor. Com a **nossa** hora, duas entregas davam dois resumos e duas linhas. **Composta com o `tenant_id`**, pela razão da emenda 1.21: com unicidade global, uma prova do *tenant* B que calhasse no mesmo resumo era deduplicada em silêncio contra uma linha de A — e aqui o que se perdia era prova jurídica |
| Prova de que um aviso foi mostrado e aceite | `consent_event.evidence_hash` = `sha256(texto_mostrado ‖ contact_id ‖ wamid ‖ hora)`, 32 octetos | Os quatro pela ordem do critério 7, com `\u0000` como separador — um UUID, um `wamid` em base64, um instante em ISO e prosa não o contêm, e **sem separador** `sha256("ab" ‖ "c")` e `sha256("a" ‖ "bc")` são o mesmo resumo. O texto que entra é o **preenchido**, com o nome da loja no lugar do marcador: senão a prova dizia «mostrámos-lhe um texto com um marcador», que não é verdade. O `CHECK` exige **32 octetos exactos** — um resumo de outro tamanho não é um `sha256`, e uma prova que não se sabe reproduzir não é prova |
| Transporte por onde o consentimento foi dado | `consent_event.canal` ∈ {`whatsapp`} | **Um valor, e o domínio fechado é a afirmação**: o segundo transporte entra por migração e não por inserção em silêncio. **Não é FK para «tenant_channels»**, e a razão é que isto é prova jurídica: ela não pode deixar de se poder ler porque a linha de um canal mudou. Qual o número que a recebeu deduz-se da conversa, que tem «channel_id» |
| Barreira anterior ao agente | `ConsentGate` | O nome é o do bloco. Corre no caminho de canal — **não** no KAM-025, que não depende deste ticket — e devolve uma decisão em vez de invocar o AGR: quem monta o *job* é o encaminhador do KAM-013/KAM-014. A propriedade do critério 4 («0 *jobs* sem consentimento válido anterior») só é demonstrável se a decisão for **a única porta**, e é por isso que o resultado tem um campo `invocaAgr` em vez de se deduzir da acção |
| Botões do aviso | `continuar`, `falar_com_a_loja`, `saber_mais` | **Os `id` que nós emitimos**, em `snake_case` pela regra do §2, e **não** os títulos: «o `button_reply` entrega `reply.id` emitido por nós (o AGR confia no `id`, não no título)». A razão é que o título é texto em PT-AO que um revisor jurídico vai mudar, e um `switch` sobre «Continuar» partia-se na primeira revisão. **Três e não mais**, e o limite é da Meta (`E1`): um `interactive` de botões aceita no máximo três, e o §3.14 já o impõe |
| Acções do aviso | `enviar_aviso`, `registar_e_seguir`, `seguir`, `passar_a_humano`, `enviar_politica`, `registar_revogacao` | Seis, e são a saída de uma tabela de **seis entradas × três estados** do consentimento (`ausente`, `desactualizado`, `valido`) — dezoito células escritas uma a uma, pela razão do §3.7: uma célula em falta deixa de compilar. **Duas autorizam o AGR e só duas**, e nenhuma o faz a partir de um estado que não seja `valido` ou de um botão que não seja o `continuar` |
| Palavras que valem como *opt-out* | `parar`, `stop`, `sair`, `cancelar` (insensível a maiúsculas e acentos) | O critério 5 nomeia a primeira; as outras três são as que uma pessoa escreve de facto. **A palavra tem de ser a mensagem inteira**, e a decisão está escrita: disparar dentro de uma frase dava revogações que o cliente não pediu — ele estava a conversar —, e uma revogação é um facto que fica. Falhar em reconhecer um *opt-out* não é um defeito de conveniência: é continuar a escrever a quem pediu para parar (`E1` §4, CONFIRMADO; Art. 19.º da Lei 22/11, CONFIRMADO para o artigo) |
| Avisos enviados numa conversa | `outbound_messages.idempotency_key` com o prefixo `aviso:` | «Repete o aviso até 2 vezes e depois encaminha a `humano`» precisa de uma contagem, e **não há coluna para ela em sítio nenhum do esquema**. Em vez de criar uma — em «conversations», que o KAM-018 teria de aprender a não mexer —, a chave é `aviso:{conversation_id}:{n}` e a contagem é um `count(*)` com prefixo: **a mesma chave que impede o aviso de sair duas vezes é a que diz quantas vezes saiu**. Resolve-se pelo índice `(tenant_id, idempotency_key)` do §3.14 |
| Avisos enviados (contador) | `consent_notice_sent_total` | Do DoD. Conta os que **saíram**: um aviso que não saiu é uma loja que não respondeu, e o critério 1 promete «exactamente 1 mensagem de saída» |
| Revogações de *marketing* (contador) | `consent_optout_total` | Do DoD |
| Fracção de aceitação (*gauge*) | `consent_accepted_ratio` | Do DoD. É **derivado** de dois contadores na leitura, e não uma terceira série guardada que pudesse divergir deles; o numerador, `consent_accepted_total`, está exposto para que o rácio se possa verificar. Vale `-1` antes do primeiro aviso, pela razão da emenda 1.27: «não sei» não é «ninguém aceitou», e um `0` acendia um alarme no primeiro minuto de cada processo. **Não se limita a 1**, e isso é informação: o mesmo contacto pode aceitar num aviso antigo que ainda está no telefone dele |
| Mensagens barradas antes do agente (contador) | `consent_blocked_total` | Etiqueta `accao`, de seis valores fechados. **Não está no DoD** e entra pela razão da emenda 1.21: *barrar sem contar é barrar em silêncio.* Sem ela, um painel não distingue «os clientes estão todos a consentir» de «não há texto vigente e o gate está a barrar tudo» — e o segundo é uma loja muda, que é o pior desfecho e o mais fácil de não notar |

**O que esta secção não declara, e é escopo e não esquecimento.** Não há nome
para a coluna de **modo** da conversa que o gate quer mudar: ela existe desde a
`0009` («conversations.mode») e o `UPDATE` que a aplicação tem **não a inclui**,
por decisão do KAM-014 — quem a muda é o KAM-018, e aqui entra por porta. Não há
nome para o **ToS/DPA da PME** (KAM-090) nem para os **direitos do titular**
(KAM-070). E as outras **sete** finalidades do §3.1 não têm caminho neste
módulo: `analytics_agregado`, `sugestoes_patrocinadas` e as três `partilha_*`
exigem consentimento específico no momento do uso (`../docs/tecnica/06` §7.3), e
quem o pede é quem usa.

**A base legal continua por fixar, e isto não a fixa.** Das dez finalidades, só
a `marketing` tem fonte directa e CONFIRMADA no `E3`, e **seis não têm nada**. O
que este ticket entrega é a prova de que **o aviso foi apresentado** e o registo
do que o titular respondeu; se a base é contrato, consentimento ou interesse
legítimo é matéria de parecer (KAM-104, e o §4 deste dicionário).

---

### 3.20 Modos da conversa: a máquina, os gatilhos e o silenciamento (KAM-018)

*Emenda 1.29, **proposta**.* A tabela `conversations` e o domínio de
`conversations.mode` (quatro valores) **já estavam** no §3.13 (emenda 1.20), e o
`PreSendGuard` no §3.14 (emenda 1.21); o que entra aqui é o vocabulário da
máquina de estados e o que a revisão `0016` muda. **A `0016` não cria tabela,
coluna nem `CHECK`** — são dois `GRANT UPDATE` por coluna —, e por isso nenhuma
linha desta secção repete um domínio que o §3.13 já tenha: duas entradas para
`conversations.mode` fariam a segunda tapar a primeira e a revisão `0009` ficava
vermelha por lhe «faltarem» os quatro valores que tem (a lição medida na emenda
1.20).

A fonte do desenho é `../docs/tecnica/01` §10.2 e §10.3 e o
`../docs/tecnica/evidencia/E1` §4; onde esta secção divergir, a divergência está
escrita na linha.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Gatilho de uma transição de modo | `conv_mode_transitions_total.gatilho` ∈ {`echo_do_dono`, `cliente_escreveu`, `comando_bot`, `handoff_pedido`, `handoff_resolvido`, `opt_out`, `sem_humano_24h`, `cliente_reactivou`} | **Oito, e é lista fechada no código** (`modos/contrato.ts`), como os `DESFECHOS` do §3.13 e pela mesma razão: é etiqueta de métrica, e um identificador não entra em etiqueta nenhuma (`../docs/seguranca/ameacas_stride.md`, OBS-I). O nome está **qualificado pela métrica** e não escrito nu: um «gatilho» solto seria um nome genérico a ganhar domínio, que é o defeito que a emenda 1.22 pagou com o `tipo`. A **detecção** de dois deles é coexistência (KAM-017): o `echo_do_dono` precisa de `smb_message_echoes` com o `wamid` ausente de `outbound_messages`, e o `comando_bot` chega pela mesma via |
| O que a tabela de transições responde | «transita», «sem efeito», «rejeitada» | **Três e não duas**, e a terceira é a que faz o resto funcionar: um gatilho legítimo que não muda o modo — uma mensagem do cliente numa conversa em `bot` — não é uma transição rejeitada. Sem a distinção, o contador de rejeições media tráfego em vez de defeitos. As **32** células (quatro modos × oito gatilhos) estão todas escritas, e o critério 1 obriga-o: «qualquer outra transição é rejeitada» só se prova enumerando |
| Silêncio do dono que devolve a palavra ao bot | `silencio_dono_min` = **30** minutos | *proposta*, e o número é o de `../docs/tecnica/01` §10.2, que o marca «a calibrar no Piloto». É a condição da única célula condicional da tabela (`dono` com `cliente_escreveu`). Sem actividade humana registada conta como **expirado**: uma conversa em `dono` sem instante de onde contar devolve a palavra ao assistente em vez de ficar presa |
| Tempo em atendimento humano sem humano que pausa a conversa | **24 h** | O número é o do critério 7 e da §10.2. **Não é a janela de serviço da Meta**, que também é de 24 h (§3.13): as duas coincidirem é acidente, e calibrar uma não move a outra — a da Meta não é nossa para calibrar (`../docs/tecnica/evidencia/E1` §4, CONFIRMADO) |
| Instante a partir do qual as 24 h contam | `conversations.last_human_activity_at`, e `handoffs.opened_at` quando ela é nula | **Duas origens, por esta ordem**, e a segunda é o caso que o critério descreve: «24 h sem humano após *handoff*» é uma conversa onde **ninguém** respondeu, e aí a primeira coluna está vazia por definição. Com as duas vazias a conversa **não** é pausada e fica em `humano` — é o lado seguro, porque `humano` mantém o bot calado (§10.2: «o bot nunca interrompe uma conversa em modo dono/humano») |
| Chave do *lock* da conversa | `pg_advisory_xact_lock(hashtextextended(tenant_id ‖ ':' ‖ contact_id, 0))` | É a do critério 2, «hash(tenant_id, contact_id)». **Por contacto e não por conversa**, e isso é mais largo do que o guarda precisa de propósito: é o que permite ao `onOptOut` travar de uma vez todas as conversas de um contacto, que podem estar em canais diferentes do mesmo *tenant* |
| Instante em que o turno do AGR começou | `Pedido.turnoIniciadoEm` | **Acrescenta-se ao `Pedido` do §3.14**, que passa de oito campos a **nove**, e é opcional. É o «turn.started_at» do pseudocódigo do critério 2, e é com ele que o guarda compara o `last_human_activity_at`. Opcional porque um envio com `doBot` falso não tem turno nenhum nem passa pelo guarda; e **um envio do bot que o não traga é recusado**, com o motivo `sem_turno` — deixar passar desligava metade do critério em silêncio |
| Métricas dos modos da conversa | `conv_mode_transitions_total`, `reply_suppressed_total`, `conv_mode_rejected_total` | **Três, e o DoD do KAM-018 nomeia três — mas não estas três.** As duas primeiras são do DoD; a terceira é acrescento deste ticket e é o único sítio onde «qualquer outra transição é rejeitada» fica visível em produção: sem ela, um gatilho mal ligado parece-se exactamente com «não houve gatilho nenhum». É a razão do `chr_resolve_total` da emenda 1.20 e do `gwy_shed_total` da 1.19 — recusar sem contar é recusar em silêncio. **Nenhuma leva etiqueta de modo**, nem de origem nem de destino: o par (modo, gatilho) determina o destino, logo a origem e o destino são informação que o gatilho já tem, repartida por dezesseis séries em vez de oito |
| A métrica que o DoD nomeia e que **não** entra | `echo_latency_ms` | **Fica de fora com o critério 8, e é decisão escrita.** Mede a diferença entre o carimbo da Meta e a recepção de um *echo*, e o critério pede p50/p95 de **≥ 30 *echoes* reais em *staging*** com números +244 — o critério de saída do risco L6, que é trabalho de KAM-100. Uma métrica declarada e sempre a zero é pior do que ausente: um painel que a mostre a zero diz «a latência do *echo* é nula» quando o que se passa é que ninguém a mede. Nasce com o ticket que a consiga medir |
| Porque é que um envio do bot foi descartado | `reply_suppressed_total.motivo` ∈ {`modo`, `actividade_humana`, `sem_turno`} | **Três, e a separação paga-se a si mesma.** O `modo` é o caso normal (uma conversa em atendimento humano, onde o bot não devia ter sido invocado); o `actividade_humana` é a corrida da §10.3, que é o que o risco L6 fica à espera de medir; o `sem_turno` é um defeito de ligação e **deve** ficar a zero. Um painel que os some não sabe se a janela de corrida está a ser atingida |
| Estado de um envio descartado pelo guarda | `outbound_messages.state` = `suppressed_by_human` | **Já existe**: é o sexto valor do domínio do §3.14 e nasceu na revisão `0010` por antecipação deste ticket, pela mecânica do *gate* 3b que a emenda 1.21 explica. A `0016` não o acrescenta, contra os *Detalhes Técnicos* do KAM-018 («adiciona se ainda não existir»). **A linha é escrita pelo guarda e não pelo `ChannelAdapter`**, porque na ordem dos sete passos dele o guarda é o 3 e o `SQL_ENFILEIRAR` é o 4: quando o guarda recusa, não há linha para marcar |
| Porta que muda o modo de uma conversa | `MudarModo` | Declarada no `ConsentGate` do KAM-022 e deixada **por ligar** pela revisão `0015` («quem a ligar é quem tiver o privilégio, e este módulo não o tem»). Ligada neste ticket, com a tradução do modo que a porta pede no gatilho da tabela: `humano` por `handoff_pedido`, `pausada` por `opt_out` |

**O que esta secção NÃO decide.** A `smb_message_echoes` fica de fora — é
coexistência, KAM-017 —, e com ela a detecção do *echo* e do comando `/bot`. E
**não decide a carga do evento**: o tipo `conversation.mode_changed` já está no
catálogo (`../contratos/eventos/conversation.mode_changed/`, v1 e v2, do
KAM-007 e do KAM-159), ao contrário do que o critério 6 supõe ao escrever «tipo
acrescentado ao catálogo, KAM-007», e a carga publicada tem o `thread_id` e o
`channel_mode` com **três** valores. Os nossos modos são quatro: `dono` e
`humano` saem os dois como «humano», e um consumidor do barramento não os
distingue. Uma `v3` de quatro valores é uma quebra de contrato com
compatibilidade a provar no *gate* 7, e o catálogo é do KAM-007 — inventá-la aqui
era decidir por outro ticket. A perda está declarada em
`../docs/dividas-documentais.md`.
### 3.21 Onboarding de canal: Embedded Signup v4, fases e saga (KAM-016)

*Emenda 1.30, **proposta**.* O que entra aqui é o que a revisão `0017` cria e o
vocabulário do Embedded Signup v4. **É a `0017` e não a `0016`**: o KAM-018
reclamou aquele número e a revisão dele chegou primeiro ao remoto; a dele não cria
objecto nenhum (dois `GRANT UPDATE` por coluna) e esta cria uma tabela, pelo que
renumerar esta custou menos. Dois `down_revision` iguais são recusados pelo
Alembic. A fonte do desenho é `../docs/tecnica/01`
§4.2–§4.4 e §13 (a máquina de estados e a tabela de passos, prazos e
compensação), o `../docs/tecnica/evidencia/E1` §3 (CONFIRMADO para o ES v4, os
limites de onboarding e o novo modelo de contas) e o
`ops/secrets-inventory.yaml`, que já declara as três famílias de segredo deste
ticket; onde esta secção divergir, a divergência está escrita na linha.

**Três identificadores que o critério 8 manda guardar não entram aqui, e isso é
leitura e não omissão:** `tenant_channels.waba_id`, `waac_id` e
`phone_number_id` existem desde a revisão `0001` e já estão no §3.2 e nas
extensões do KAM-003; o `token_ref` é nome do §3.15 desde a emenda 1.22. Esta
revisão **não acrescenta coluna nenhuma a «tenant_channels»**.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Tentativa de ligar um número | `platform.channel_onboarding` — `id`, «tenant_id», `channel_id`, «waba_id», «waac_id», «phone_number_id», `code_hash`, `fase`, `recursos_criados`, `pin_ref`, `motivo`, «criado_at», `actualizado_at` | **Treze colunas, e o bloco do ticket nomeia quatro** (`channel_id`, `fase`, `recursos_criados jsonb`, `actualizado_at`). As nove restantes vêm de critérios do mesmo bloco: o `id` porque o §2 pede `uuid` para a coluna que identifica e aqui a chave de negócio é o par «(tenant, waba)»; o `tenant_id` porque sem ele não há RLS e o DoD pede-a; o `code_hash` e o par «waba_id»/«phone_number_id» porque são as **duas unicidades** do critério 2 e a recusa do critério 4; o `waac_id` pelo critério 8; o `pin_ref` pelo critério 3; o `motivo` porque o registo de auditoria do critério 4 sem razão escrita não é registo; e o `criado_at` porque é dele que sai a janela de sete dias do critério 8 — e pela convenção do §3. **Vive em `platform.`** e leva FK **compostas** com o `tenant_id`, pela razão que a `0009` fixou |
| Fase de um onboarding | `channel_onboarding.fase` ∈ {`iniciado`, `es_concluido`, `subscrito`, `a_sincronizar`, `verificado`, `pronto`, `ativo`, `falhado`, `abandonado`} | **Nove, e o diagrama do `../docs/tecnica/01` §13.1 desenha dez.** O décimo é o «desligado», e ele **não é fase de onboarding**: é valor de «tenant_channels.estado» desde a `0001` (§3.2), e quem o escreve é o tratador de «account_update» — KAM-017. O diagrama mistura as duas máquinas num desenho e o critério 6 desfaz a mistura. O `ativo` é **terminal**: a saga acaba ali, e a reconexão volta por `iniciado`. Domínio **qualificado pela tabela**, pela regra da emenda 1.14: «fase» é um nome genérico, e um domínio nu valeria para qualquer coluna futura com esse nome |
| Transições legais de uma fase | `TRANSICOES` — **dezesseis** arestas | O diagrama desenha **onze**, e a diferença é uma regra só: **de qualquer fase não terminal vai-se a `falhado`**. O diagrama só desenha «a_sincronizar --> falhado» (o prazo de 24 h), mas o critério 7 pede uma falha injectada no **passo 4** — a subscrição, que corre em `es_concluido`. Uma saga cuja compensação não tem onde se registar é uma saga que não compensa: sem esta regra, o caminho que o critério 7 manda exercitar não é representável na tabela que o critério 6 define. O `abandonado` fica **só de `iniciado`**, como o diagrama o desenha: o critério diz «sem conclusão em 30 min» e o diagrama diz de que conclusão fala. **A matriz vive no código e não num *trigger***, e aplica-se por *compare-and-set* (`WHERE fase = <esperada>`) — a mesma escolha que a `0010` fez para a monotonia de «outbound_messages.state»; a base impõe o domínio, e o *gate* 8 percorre os **81** pares ordenados |
| Idempotência de um onboarding | `channel_onboarding` com `UNIQUE (tenant_id, code_hash)` e `UNIQUE (tenant_id, waba_id)` | É o critério 2 — «repetir o mesmo code ou o mesmo (tenant_id, waba_id) 2× produz 1 canal, 1 token e 0 subscrições duplicadas» — e é **da base**, em duas chaves. **«1 canal» sai de «1 linha aqui»**, porque o canal cria-se na mesma transacção que escreve o `channel_id` nesta linha: duas chamadas concorrentes com o mesmo par não podem ter as duas uma linha, logo não podem ter as duas um canal. **As duas levam o `tenant_id`**, pela razão da emenda 1.21: com unicidade global, uma tentativa de B que calhasse no mesmo resumo era deduplicada em silêncio contra a de A. **O que a segunda custa está escrito:** um *tenant* não pode ter dois números no **mesmo** WABA por este caminho. O critério fixa-o assim, e o que o justifica é que o recurso do passo 4 — a subscrição — é **do WABA** e não do número: «0 subscrições duplicadas» é, literalmente, uma subscrição por «(tenant, waba)». Um segundo número no mesmo WABA é um caminho novo, não um relaxamento desta chave |
| Resumo do *code* do Embedded Signup | `channel_onboarding.code_hash` = «sha256(code)», 32 octetos | **O *code* nunca entra na base em claro**, e isto não é zelo: ele é trocável por um *token* de cliente, logo é um segredo com o valor do *token* — e o *dump grep* do critério 3 encontrava-o. Um resumo serve para o que a idempotência precisa (igualdade) e não serve para o que um atacante precisa (trocar). **Sem sal e sem HMAC**, ao contrário do «contacts.phone_hmac» do §3.1: o *code* tem entropia de segredo, pelo que o resumo dele não é enumerável — é o telefone que obriga o `pepper_contact_hmac` a existir, não o resumo em si |
| Recursos que um passo criou | `channel_onboarding.recursos_criados` (`jsonb` **array** de «{recurso, ref}») | Do `../docs/tecnica/01` §13.2: «cada passo registra o recurso criado; a falha dispara a compensação inversa». É um **array** e não um objecto porque a **ordem** é metade do que faz a compensação inversa ser inversa, e o `CHECK` exige «jsonb_typeof(...) = 'array'». **O «ref» nunca é um valor de segredo**: é uma `SecretRef` (§3.9) para o *token* e o PIN, o «channel_id» para o canal, o «waba_id» para a subscrição. Depois de compensar vale «[]», e é aí que se leem os «0 recursos órfãos» do critério 7 — ao lado de «0 linhas em tenant_channels» e «0 subscrições no WABA», porque uma lista vazia só prova que a lista está vazia |
| Tipo de recurso de uma saga | `RecursoCriado.recurso` ∈ {`token`, `pin`, `canal`, `subscricao`} | Quatro, um por passo com efeito **fora** da transacção, e é isso que decide a lista: um passo sem recurso não tem o que compensar. **Qualificado pelo tipo e não pela coluna**, e isso é uma correcção que o próprio *gate* 3b fez: a primeira versão desta linha escrevia «channel_onboarding.recursos_criados[].recurso», o `dict_export` colheu-a como domínio da **coluna** «recursos_criados», e o gate deu dois achados a exigir um `CHECK (recursos_criados IN (…))` numa coluna `jsonb` — que não o pode ter. É a mesma classe de correcção que a emenda 1.22 fez com «MirrorMessage.direccao» e «HumanEvent.acontecimento»: um domínio que não é de uma coluna de base qualifica-se pelo tipo que o declara. O que a base impõe sobre a coluna é só a forma (`jsonb_typeof(...) = 'array'`); o domínio dos quatro valores vive no `RECURSOS` do «onboarding/contrato.ts», e é lá que uma célula em falta deixa de compilar. A ordem em que se criam é esta, e a compensação percorre a coluna ao contrário — **e isso não é arbitrário**: anular a subscrição exige o *token* em claro, pelo que revogar o *token* primeiro deixava a subscrição sem forma de ser desfeita |
| Referência ao PIN 2FA do número | `channel_onboarding.pin_ref` | Uma `SecretRef` (§3.9) para `meta_pin_2fa`, que o `ops/secrets-inventory.yaml` já declara com «instancias: tenant» e «acesso minimo: so o provisionamento o le». **Fica aqui e não em «tenant_channels»**, e é decisão: o PIN é artefacto de **onboarding** — é o passo 5′ do `01` §13.2, usado uma vez para registar o número em `cloud_only` —, e uma coluna no canal dizia que ele precisa dele para viver. Pior: o `GRANT UPDATE` por coluna da `0001` teria de a admitir, o que põe a referência de um segredo ao alcance de `kamba_app`, que nunca a lê. Leva `CHECK` **de forma** de `SecretRef`, e não só de não-vazio: uma referência mal formada é um segredo que ninguém vai conseguir ir buscar, e isso descobre-se no dia em que faz falta |
| Razão por que um onboarding falhou | `channel_onboarding.motivo` | Texto **nosso** e não da Meta, e anulável — o `NULL` é o estado normal. Um código de erro da Meta vive em «tenant_channels.meta_error_codes_seen» (§3.17), que é a coluna que o KAM-023 criou para isso. **Não tem domínio fechado**, ao contrário do «motivo_restricao» do §3.17, e a diferença é o consumidor: aquele é lido por código que decide se pode repor a restrição, este é lido por uma pessoa a perceber porque é que um onboarding não acabou |
| Registo de auditoria de um onboarding recusado | uma linha de `channel_onboarding` em «fase = 'falhado'», com `motivo` e «recursos_criados = '[]'» | **E não o «audit_log» do §3.2**, que é onde se iria procurar. A razão é mecânica e foi medida: o domínio de «audit_log.action» tem **sete** valores e o `CHECK` está na revisão `0006`, fundida; o *gate* 3b lê o `CHECK` de **cada revisão isoladamente** e compara-o com o dicionário **nos dois sentidos** (`tools/canon_lint/ddl.py` reporta «falta:»), pelo que acrescentar um oitavo valor deixava a `0006` vermelha. É a mecânica que a emenda 1.20 pagou para o «unrouted_events.motivo» e a 1.26 para o «motivo_restricao», pelo outro lado: ali os valores entraram na revisão que cria o `CHECK`, e aqui essa revisão não se reescreve. E nenhum dos sete descreve isto — enfiar a recusa em «access.conversation» era mentir num registo que existe para não mentir. **O «não altera nada» do critério 4 continua literal**, porque o 409 vem de uma transacção que **reverte**; esta linha escreve-se depois, numa transacção própria |
| Configuração do *popup* de coexistência | «extras.featureType» = `whatsapp_business_app_onboarding`, «sessionInfoVersion» = `"3"` | CONFIRMADO (`E1` §3, `01` §4.3). O «sessionInfoVersion» é **cadeia** e não número, e é assim que o `E1` o escreve; aceita-se também o número «3», e isso é tolerância de fronteira com a razão escrita — um *popup* que o mande como número é um «JSON.parse» a fazer o seu trabalho, e recusar o onboarding de um cliente real por um par de aspas era o lado errado de falhar. O «featureType» é exigido **sem tolerância**: é ele que distingue a coexistência do `cloud_only`, e adivinhá-lo pela ausência era decidir o modo do canal por omissão |
| Evento com que o *popup* fecha em coexistência | `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` | CONFIRMADO (`E1` §3). **Não há registo do número** em coexistência: ele já está registado. Quem consome o evento é a página (KAM-093); este ticket recebe o resultado |
| Campos de webhook que um canal subscreve | `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync`, `account_update`, `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update` | **Onze**, os do critério 5 e do `01` §4.4, todos CONFIRMADOS no `E1` §2–§3. O `smb_message_echoes` **não existia no canon** — é o único dos onze que não ocorria uma vez no `../canon/dicionario.yaml`. Subscrevem-se os onze e tratam-se quatro: os de template são do KAM-015 e os de qualidade do KAM-021, e subscrever menos do que onze era deixar um webhook que outro ticket espera a nunca chegar — o que não se descobre num teste do ticket que o trata. **A confirmação é por igualdade de conjuntos** e não de listas, e o critério di-lo: a Meta devolve «subscribed_fields» sem ordem garantida |
| Versão da Graph API | `KAMBA_META_GRAPH_VERSION`, na forma «v<maior>.<menor>» | Em **configuração**, e os *Detalhes Técnicos* do bloco mandam-no por extenso: «Os pontos finais e parâmetros exactos da Graph API **não** constam de E1 (páginas de referência de API não lidas)». A omissão é ***proposta***; o `GraphFalso` do KAM-024 aceita qualquer versão e registra a que o cliente usou, e diz porquê no seu próprio ficheiro — «inventar uma ("v23.0") era afirmar o que não se sabe». Falha **fechada** numa forma inválida e não cai para a omissão: um segmento que a Meta não reconhece dá 404 em produção. **Não há variável para a versão do Embedded Signup**, e é decisão: só v4, e uma variável convidava alguém a voltar atrás |
| Porta de escrita no cofre | `SecretWriter` — «cunhar(familia, valor)», «revogar(ref)» | A lacuna que o `ADR-L002` §6 declarou para este dia: «Não há caminho de escrita … é o que o **KAM-016** vai precisar na troca do code … O KAM-016 acrescenta-a». Entra **separada** da `SecretProvider` do §3.9 e não acrescentada a ela: o `EnvSecretProvider` não escreve — um processo não escreve no seu próprio ambiente de forma que outro veja —, e uma porta cujos implementadores lançam em metade dos métodos não é um contrato. O «revogar» é **idempotente por contrato**: a compensação de uma saga pode correr duas vezes, e uma compensação que falha na segunda passagem deixa a saga sem forma de acabar |
| Sufixo de uma referência cunhada | 16 octetos aleatórios em hexadecimal | **Não é o `tenant_id`**, e seria cómodo que fosse — a referência dizia de quem era o segredo e a compensação não precisaria de a ler da base. É por isso que não se faz: o «token_ref» vive numa coluna que o `kamba_app` **lê** (o `GRANT UPDATE` da `0001` nomeia-a), e um sufixo que fosse o `tenant_id` tornava cada referência um identificador de *tenant* em claro num sítio onde o resto do esquema tem cuidado de não o ter. Quem precisa de saber de quem é lê a linha que a guarda |
| Cifra do *token* de cliente | AES-256-GCM, DEK **derivada** por *tenant*, KEK `kek_token_cliente` no cofre, «kid» versionado dentro do criptograma | O critério 3 pede as duas metades ao mesmo tempo — cifrado **e** com «token_ref» —, e o inventário confirma-o do outro lado: declara `kek_token_cliente` como entrada **separada** do `meta_client_token`, com «anel: true», «kid: true» e a descrição «chave que encripta as DEK por tenant dos tokens de cliente». O que fica no cofre, sob a referência, é o **criptograma**: uma cópia do cofre não dá o *token* sem também a KEK, que tem dono diferente («owner: seguranca» contra «owner: eng_canais»). **A DEK é derivada e não guardada**, por «HKDF-SHA256(KEK, info = domínio ‖ tenant_id)», e isso divergir do KAM-008 é decisão: a tabela «contact_deks» existe para a DEK de um contacto sobreviver à rotação da KEK sem re-cifrar os dados, e aqui o segredo é **re-cunhável** (o inventário diz «rotacao_gatilho: offboard_ou_expiracao»); além disso uma tabela nova com `tenant_id` que a *suite* não saiba semear **falha o *gate* 6**, que é a razão que o KAM-023 escreveu para pôr «meta_error_codes_seen» numa coluna. **O «kid» vai dentro do criptograma** — sem ele, o dia em que a KEK rodasse tornava indecifráveis todos os *tokens* já guardados, e um *token* de cliente não se regenera sem o dono repetir o *popup*. O contexto autenticado leva «domínio ‖ tenant_id ‖ kid», pela razão do «contextoDaCifra» do §3.1: um criptograma copiado para a linha de outro *tenant* **não abre** — e mover um «token_ref» de A para a linha de B é uma escrita que a base aceita |
| Tecto de clientes novos | `es_onboardings_7d` < **10** em **7** dias | CONFIRMADO (`E1` §3): até 10 clientes novos / 7 dias sem verificação completa, 200 / 7 dias com Business Verification + App Review + «Access Verification» (este último NÃO VERIFICADO). O contador **atravessa *tenants***, porque o limite é da nossa app perante a Meta e não de uma loja — e é por isso que ele só corre com `BYPASSRLS`: com a política `tenant_iso`, o `kamba_app` contaria sempre as suas e contaria mal, o que é pior do que não contar porque parece certo. **Conta tudo o que entrou na janela**, incluindo o `abandonado` e o `falhado`: se um *popup* fechado consome um lugar na contagem **deles** é NÃO VERIFICADO, e contar de menos fazia-nos passar o tecto e receber a recusa no onboarding de um cliente real. Contar de mais custa esperar; contar de menos custa um cliente. **A lista de espera é KAM-095**, e o critério 8 di-lo |
| Tentativas por fase (*gauge*) | `es_onboarding_fase` | Etiqueta «fase», de nove valores fechados. **Não está no DoD** e entra pela razão da emenda 1.21: um painel que só veja canais activos não distingue «não há onboardings» de «estão todos parados em es_concluido». Reescreve as nove séries de cada vez, incluindo as que ficam a zero — uma série que desaparece fica no último valor em qualquer painel que a tenha visto |
| Compensações corridas (contador) | `es_onboarding_compensado_total` | Etiqueta «recurso», de quatro valores fechados. Não está no DoD, e a razão é a mesma: **compensar sem contar é compensar em silêncio.** Uma saga que reverte tudo correctamente e uma saga que nunca chega ao passo 4 produzem o mesmo número de canais activos — zero |
| Onboardings recusados (contador) | `es_onboarding_recusado_total` | Etiqueta «motivo» ∈ {`es_nao_e_v4`, `numero_de_outro_tenant`, `limite_7d`}. Três, e são as três recusas que acontecem **antes** de haver recursos; uma falha depois disso não é uma recusa, é uma compensação, e conta na outra série |
| Rota interna de criação de canal | `POST /internal/channels` | Os cinco campos do critério 1: «tenant_id», «code», «waba_id», «phone_number_id», «session_info». **Vai na app interna do GWY e não na pública**, e isso é decisão: esta rota **cria canais** e o `tenant_id` vem no corpo, pelo que na porta pública — alcançável da Internet por desenho (ADR-001) — quem lhe chegasse podia ligar um número ao *tenant* que quisesse. É a mesma razão que tirou o «/metrics» de lá na revisão adversarial do KAM-013, com mais em jogo: ali lia-se a profundidade da fila, aqui escrevia-se no esquema. **E o `tenant_id` no corpo não contradiz o ADR-010**: este corpo não é texto de utilizador, é o resultado de um *popup* que a nossa página abriu (KAM-093) com o `tenant_id` que ela já tinha em contexto. Códigos: **201** criou, **200** repetiu (é a forma de o critério 2 se verificar de fora), **400** não é v4, **409** número de outro *tenant*, **429** tecto gasto (e não 403: é «ainda não», não «nunca»), **502** a Meta recusou |

**O que esta secção não declara, e é escopo e não esquecimento.** Não há nome
para a **sincronização** de contactos e histórico: o `a_sincronizar` existe no
domínio e **nenhuma transição deste módulo o produz** — a porta é
«subscrito → a_sincronizar», e quem entra por ela é o KAM-017. Não há nome para
o **orquestrador** da saga, que é KAM-091 e de que este ticket entrega os passos.
Não há nome para a **lista de espera** do tecto de dez (KAM-095), para o ***gate*
de activação** (KAM-093), nem para o **registo do número** em `cloud_only` — o
passo 5′ do `01` §13.2, cuja verificação por SMS ou voz em Angola é NÃO
VERIFICADA e cujo PIN este ticket apenas guarda.

**E uma exposição declarada, que não é um nome mas pertence aqui.** A troca do
*code* vai em «GET» com o *code* e o «client_secret» na **consulta**, porque é a
forma que a Meta documenta e que o `GraphFalso` do KAM-024 modela — a primeira
versão do cliente mandava-os no corpo, pela RFC 6749 §4.1.3, e **ficou vermelha**
contra o simulador. A alternativa era alargar o simulador e passar a provar o
cliente contra uma superfície alargada para lhe servir, o que faria o primeiro
onboarding real falhar com os testes verdes. O pedido sai em TLS e o *code* é de
uso único; o que **não** está mitigado é um proxy de saída nosso que registre a
linha de pedido, e isso é KAM-077.

---

### 3.22 Coexistência: sincronização de 24 h, *echoes* e desligamento (KAM-017)

*Emenda 1.31, **proposta**.* O que entra aqui é o que a revisão `0018` cria e o
vocabulário da coexistência. A fonte do desenho é `../docs/tecnica/01` §10.1,
§10.4 e §10.5, e a evidência é o `../docs/tecnica/evidencia/E1` §2 — **CONFIRMADO
pela fonte primária** para os prazos, os seis motivos, os 6 meses, o 2593109 e o
tecto de 20 mps **da Meta**, e **NÃO VERIFICADO** para a elegibilidade de Angola
(risco R1). Os 20 mps são o tecto dela; o `MPS_POR_MODO` abaixo é o **nosso**
débito, e são 15 nos dois modos pela razão que o `limites.ts` escreve desde o
KAM-015 — os dois números não se contradizem, medem lados diferentes.

**A revisão não acrescenta coluna nenhuma a `tenant_channels`**, e isto repete o
achado da `0017` pela mesma razão: o `coexistence_synced_at` e o
`last_account_update_at` existem desde a `0001`, estão no `GRANT UPDATE` por
coluna que a `0014` reescreveu por inteiro, e **nunca tiveram escritor**. Este
ticket é o primeiro a escrever-lhes, e isso custa código e não DDL. O
`channel_mode` e o valor `desligado` de `tenant_channels.estado` também já lá
estão, com os `CHECK` da `0001`.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Quando a coexistência de um canal sincronizou | `tenant_channels.coexistence_synced_at` | **Existe desde a `0001`, e este ticket é o primeiro a escrever-lhe.** O critério 1 nomeia-a, e é ela que o painel lê para dizer «este canal está sincronizado». Sai hoje de `../canon/extensoes.yaml` e entra no dicionário, pela razão que a emenda 1.22 escreveu para o `token_ref` e a 1.30 para o `waac_id`: uma coluna que um ticket passa a usar por extenso deixa de ser nome sem conceito. Escreve-se **uma vez**, quando os dois passos acabam — e não a cada lote de `history`, porque «sincronizou» é um facto e não um progresso |
| Quando chegou o último `account_update` | `tenant_channels.last_account_update_at` | Pelo mesmo motivo, e com o mesmo percurso. É o carimbo do último `account_update` **tratado**, e não do último recebido: um evento deduplicado pela `inbound_events_kind_event_key_uq` não o move, porque mover era dizer que a Meta falou quando quem falou foi uma re-entrega nossa |
| Estado de coexistência de um canal | `platform.channel_coexistence` — `id`, `tenant_id`, `channel_id`, `estado`, `passos_feitos`, `iniciado_em`, `prazo_em`, `alertado_em`, `concluido_em`, `contactos_vistos`, `mensagens_vistas`, `meta_error_code`, `ultimo_echo_em`, `avisado_em`, `motivo_desligamento`, `desligado_em`, `criado_at`, `actualizado_at` | **Dezoito colunas, e o bloco do ticket não nomeia nenhuma** — o que ele nomeia é `coexistence_synced_at`, que é de `tenant_channels` e existe desde a `0001`. **Uma tabela e não duas**, e **por canal e não por tentativa de sincronização**: é a unicidade `(tenant_id, channel_id)` que faz «sem criar canal duplicado» (critério 9) ser propriedade da base — a reconexão **repõe** a linha que lá está. Com uma linha por tentativa, a pergunta «este canal já sincronizou?» passava a ter duas respostas. **Vive em `platform.`** e leva FK **compostas** com o `tenant_id`, pela razão que a `0009` fixou |
| Estado de uma sincronização | `channel_coexistence.estado` ∈ {`a_sincronizar`, `sincronizado`, `sincronizado_sem_historico`, `falhado`} | **Quatro, e o terceiro é terminal e bem-sucedido**: é o critério 4 inteiro. O 2593109 diz que o cliente escolheu não partilhar histórico, e tratá-lo como `falhado` disparava o *offboard* do critério 3 — isto é, mandava o dono repetir o Embedded Signup — por o titular ter exercido uma escolha que o próprio *popup* lhe oferece. Domínio **qualificado pela tabela**, pela regra da emenda 1.14: a `tenant_channels.estado` já tem o seu, e são dois domínios diferentes da mesma palavra |
| Passos da sincronização | `channel_coexistence.passos_feitos` (`text[]`) ⊆ {`contactos`, `historico`} | **Dois, os que o `E1` §2 nomeia**, e cada um «só pode ser executado uma vez» (CONFIRMADO). Quem impõe o «2.ª execução = *no-op*» do critério 3 é a instrução e não um `if`: `UPDATE … SET passos_feitos = passos_feitos ‖ $n WHERE NOT ($n = ANY (passos_feitos))` devolve **zero linhas** na segunda passagem. O `CHECK` é de **conteúdo** (`<@ ARRAY[…]`) e não de cardinalidade: um conjunto vazio é o estado normal, e `array_length(…) <= 2` afirmava a mesma coisa duas vezes |
| Motivo de desligamento de um canal | `channel_coexistence.motivo_desligamento` ∈ {`primary_inactivity`, `companion_inactivity`, `business_downgrade`, `change_number`, `user_re_registered`, `account_disconnected`} | Os **seis** de `PARTNER_REMOVED` (`E1` §2, CONFIRMADO), **em minúsculas e não na forma da Meta**, e a razão foi medida: estes valores são também `outcome` de registo, e o `IDENTIFICADOR` do `logger/politica.ts` só aceita minúsculas — **em modo estrito, que é o do CI, o `Logger` levanta**, e um desfecho normal de um *webhook* virava excepção não tratada. É a mesma classe de defeito que o `sem_humano_24h` do KAM-018 pagou. A forma `MAIUSCULA` da Meta converte-se na fronteira, pelo `MOTIVO_POR_EVENTO_META` |
| O código que diz «sem histórico» | `channel_coexistence.meta_error_code` = `2593109` | `integer` e **não** `text`, e isto não é arrumação: o código tem **sete** dígitos e o `DIGITOS_MAXIMOS` do `logger/politica.ts` é **seis**, pelo que ele é recusado nos **dois** campos onde caberia — no `outcome` e no `error_code`. Mediu-se contra o espelho Python: `validar("error_code", "2593109")` devolve `None` e `validar("error_code", "131049")` passa. **O número não se regista**; o que vai ao registo é o `outcome` simbólico `sincronizado_sem_historico`. Diferente da `tenant_channels.meta_error_codes_seen` da `0013`, que é a **lista** de códigos vistos no canal: esta coluna é o código que decidiu **esta** sincronização |
| Contagens do histórico | `channel_coexistence.contactos_vistos`, `channel_coexistence.mensagens_vistas` | **Contagens, nunca corpos.** O critério 2 proíbe persistir ou indexar o corpo das mensagens de histórico no Piloto, e a base legal para o usar é parecer por dar (KAM-104). **Não há coluna de texto para conteúdo nesta tabela**, e é essa a forma de garantir a regra: uma regra que depende de ninguém escrever num sítio onde dá para escrever não é uma regra |
| Relógio do último *echo* | `channel_coexistence.ultimo_echo_em` | Quando chegou o último *echo* que **não** foi nosso — isto é, cujo `wamid` não consta de `outbound_messages`. É o relógio do aviso preventivo dos 10 dias do critério 6. A outra metade da heurística do `../docs/tecnica/01` §10.5 — «sem acesso ao painel» — **não se mede**: não há painel (é KAM-093), e inventar um sinal era inventar evidência. Fica declarado em `../docs/dividas-documentais.md` |
| Aviso de inactividade já enviado | `channel_coexistence.avisado_em` | Nulo é o estado normal, e é o que torna o aviso idempotente — a instrução filtra por `avisado_em IS NULL`. **Repõe-se a nulo quando chega actividade do dono**, que é o que faz o aviso poder voltar a sair na janela seguinte; sem isso, um canal avisado uma vez nunca mais era avisado |
| Prazos da coexistência | `PRAZO_DE_SINCRONIZACAO_MS` = 24 h, `ALERTA_DE_SINCRONIZACAO_MS` = 12 h, `INACTIVIDADE_DO_DONO_MS` = 10 dias | As 24 h são **CONFIRMADAS** (`E1` §2: «cada passo só pode ser executado uma vez; senão o cliente tem de ser *offboarded*»); as 12 h e os 10 dias são do bloco do ticket e do `01` §10.5, e são ***proposta*, a calibrar no Piloto**. O `prazo_em` é **coluna e não cálculo**, e isso é o critério 3 a mandar: «relógio acelerado nos testes» — um prazo derivado de `now()` na consulta não se acelera sem mexer no servidor |
| Débito do *token bucket* por modo | `MPS_POR_MODO` — `coexistencia` → 15, `cloud_only` → 15 | O critério 8 pede «15 mps em `coexistencia`», e é o que o `MPS_POR_CANAL` do KAM-015 já valia para todos os canais. O que entra aqui é a **função** do modo, e os dois valores são hoje iguais de propósito: o `E1` §5 confirma 20 mps em coexistência e a Meta dá 80 em `cloud_only`, mas **nenhum documento deste repositório fixa o número do `cloud_only`** — e pôr 80 por dedução era inventar o que o critério não diz. O que o par resolve é tornar o 15 do critério uma **escolha por modo** e não uma coincidência |
| Motivo de um `channel.updated` | `PayloadChannelUpdated.motivo` ∈ os seis de `motivo_desligamento` | **Qualificado pelo tipo e não pela coluna**, pela razão que a emenda 1.30 pagou com o `RecursoCriado.recurso`: o `motivo` do evento não é coluna nenhuma e um domínio qualificado por coluna fazia o *gate* 3b exigir-lhe um `CHECK` que não existe. O `v2.schema.json` tem-no como `string` livre, e não se aperta: o esquema é do KAM-007 e apertá-lo aqui era decidir por outro ticket |
| Destinatário de um *echo* | `message_echoes[].to` | ***Proposta*, NÃO VERIFICADO.** O `E1` §5 não descreve a forma de `smb_message_echoes`, e o `ARRAY_DOS_ECHOES` já estava no canon como proposta pela mesma razão. Este ticket **fixa o campo** — que é o que o comentário do `explosao.ts` lhe atribuía — e fixa-o no nome que o simulador do KAM-024 já emite, para que os dois lados da proposta digam o mesmo. Sem ele, um *echo* não tem interlocutor e não há conversa para transitar: a célula `bot→dono` do KAM-018 ficava sem detector |
| Métricas da coexistência | `coex_sync_duration_s`, `coex_sync_failed_total{motivo}`, `channel_disconnected_total{motivo}`, `coex_echo_total{desfecho}` | As **três** primeiras são as do DoD. A quarta não está no DoD e entra pela razão da emenda 1.21: o critério 7 distingue o *echo* do dono do *echo* que é nosso, e **separar sem contar é separar em silêncio** — sem ela, o dia em que a Meta passar (ou deixar) de gerar *echo* para envios por API, que é o **NÃO VERIFICADO L6**, não se vê em produção. Nenhuma leva etiqueta de *tenant* nem de canal, pela regra do OBS-I: um UUID com hífenes **levanta** |
| Desfecho de um *echo* | `coex_echo_total.desfecho` ∈ {`do_dono`, `nosso`, `sem_conversa`} | Três e não dois, e o terceiro é honestidade: um *echo* cujo `to` não resolve contacto **não se descarta em silêncio** — conta-se. É o que torna o L6 mensurável pelo lado que falta |

**O que esta emenda não decide, e fica por marcar.** O **modo predefinido do
produto** (`coexistencia` ou `cloud_only`) depende do relatório do `ext:KAM-100`,
que **não existe** — não há `docs/evidencia/KAM-100.md` — e a elegibilidade de
Angola continua **NÃO VERIFICADA** (risco R1). A lógica dos dois modos entrega-se
inteira, e é a mesma: o `01` §10.1 di-lo («a lógica de saída é a mesma, só muda o
§10.2»). O que fica por decidir é **um valor por omissão**, e inventá-lo era
escolher pelo relatório que o havia de decidir. Também não decide: o aviso ao
dono por canal alternativo (**KAM-115** — este ticket emite o evento e pára aí),
a base legal do uso do histórico (**KAM-104**), a UI de reconexão (**KAM-093**),
a detecção do comando `/bot` (ver a dívida: o corpo de um *echo* não entra no
`EventoDeEntrada`, e fazê-lo entrar punha texto de mensagem no contrato de
ingestão), e a métrica `echo_latency_ms` (**KAM-100**, que é quem pode medir ≥ 30
*echoes* reais).

### 3.23 Aviso ao dono por canal alternativo: o contacto, o registo e os limites (KAM-115)

*Emenda 1.32, **proposta**.* O que entra aqui é o que a revisão `0019` cria e o
vocabulário do aviso. A fonte do desenho é `../docs/tecnica/01` §10.5, §11.4 e
§14 e `../docs/tecnica/10` §6.4, e a evidência é o
`../docs/tecnica/evidencia/E1` §1 e §2 — **CONFIRMADO pela fonte primária** para
os seis motivos de `PARTNER_REMOVED`, para os ~14 dias de `PRIMARY_INACTIVITY` e
para o corte das *service messages* depois das 1.000 grátis sem método de
pagamento. Tudo o que é número de frequência neste ticket é ***proposta***, e
está marcado.

**Este é o último ticket do EPIC-02, e fecha a lacuna R16** — «sem ticket para
avisar o dono por canal alternativo em `PARTNER_REMOVED`, inactividade ou falha
de pagamento Meta». Os emissores existiam desde o KAM-017, o KAM-021 e o
KAM-023; o que não existia era quem entrega.

**São duas tabelas e não uma**, e a razão é o critério 7: ele manda que uma falha
de entrega «marque o **contacto** como inválido». Isso é um facto do contacto e
não do aviso — com uma tabela só, a invalidação vivia na última linha de aviso e
a pergunta «este dono tem contacto válido?» passava a ser uma consulta sobre o
histórico de envios em vez de um facto.

**E a revisão não toca em `tenants` nem em `tenant_channels`.** Tentou-se pôr o
contacto alternativo em `tenants`, e o que o desaconselha é o `GRANT UPDATE` por
coluna dessa tabela: o `estado` saiu de `kamba_app` na emenda 1.18 porque «o
sujeito de uma condição não pode ser quem a retira», e acrescentar-lhe duas
colunas obrigava a reabrir essa lista. Uma tabela própria tem a sua RLS, a sua
unicidade e os seus privilégios, e não mexe no que a `0007` fechou.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Contacto alternativo do dono | `platform.owner_contacts` — `id`, `tenant_id`, `canal`, `endereco_enc`, `verificado_at`, `confirmacao_hash`, `confirmacao_expira_em`, `invalido_at`, `motivo_invalido`, `criado_at`, `actualizado_at` | **Onze colunas, e o bloco do ticket não nomeia nenhuma** — ele nomeia só a `owner_notices`. É a tabela que o critério 6 pressupõe quando pede «≥ 1 contacto alternativo verificado por ligação de confirmação», e sem ela esse critério não tinha onde viver. **Uma linha por (tenant, canal)**: o «≥ 1» é um mínimo e não um número, e com vários por canal a pergunta «para onde vai o aviso?» passava a ter de escolher entre dois e-mails do mesmo dono — escolha que um aviso de avaria não deve tomar. Leva FK **só** para `tenants`: o aviso é do **dono** e não do canal |
| O endereço, cifrado | `owner_contacts.endereco_enc` (`bytea`) | **Não existe coluna em claro, e é assim que a regra se garante.** É o DoD «Privacidade» do ticket por extenso: «endereço do dono só em cifra e nunca em logs». A cifra é a do `onboarding/cifra.ts` (AES-256-GCM, DEK por *tenant* derivada por HKDF de uma KEK do cofre, `kid` dentro do criptograma) e **não se reescreveu nada**: o que muda é a KEK, que é a entrada nova `kek_contacto_dono` do `../ops/secrets-inventory.yaml`. Duas KEK diferentes dão duas DEK diferentes para o mesmo *tenant*, pelo que a separação de domínio sai da **chave** em vez de sair de uma constante que alguém pode esquecer de mudar. **Não há HMAC de pesquisa**, ao contrário do `contact_endpoints` do KAM-008: lá há pesquisa por valor (chega um telefone num *webhook* e é preciso achar o contacto), aqui entra-se sempre pelo `tenant_id` — e um HMAC sem quem o consulte era uma chave a mais para guardar e rodar |
| Canal de um contacto | `owner_contacts.canal` ∈ {`email`} | **Um valor, e é a honestidade do estado de hoje.** O painel é um canal por onde o aviso sai e **não tem endereço** — quem o lê é o dono quando entra, e a notificação identifica-se pelo `tenant_id` que a RLS já impõe. O `sms` **não está pré-declarado**, porque o adaptador é o KAM-116 e o ticket diz que «só se activa quando esse contrato existir»: um nome sem superfície é o que o *gate* 3b recusa, e o `ARRAY_DOS_ECHOES` do KAM-017 mostrou o que custa. O precedente de um domínio de um valor é o `consent_event.canal IN ('whatsapp')` da `0015`. Domínio **qualificado pela coluna** e diferente do `owner_notices.canal`, pela regra da emenda 1.14 |
| Prova da verificação | `owner_contacts.verificado_at`, `owner_contacts.confirmacao_hash`, `owner_contacts.confirmacao_expira_em` | O critério 6 pede «verificado por ligação de confirmação», e o que se guarda é o **`sha256` do *token*** e nunca o *token*: quem leia a base não consegue confirmar um endereço por ele. **Sem chave**, e isto é diferente dos `*_hmac` do KAM-008 — o que obriga a HMAC lá é o espaço dos números angolanos ter poucos milhões de elementos, não o resumo ser fraco; 32 octetos do gerador do sistema não se enumeram. Um endereço não verificado **não recebe avisos**, e quem o impõe é o predicado da consulta. Emitir uma confirmação nova **repõe o `verificado_at` a nulo**: sem isso, um endereço trocado herdava a verificação do anterior. **Quem entrega a ligação é o KAM-086**, que é quem capta o e-mail (o critério di-lo); este ticket emite, guarda, põe prazo e confirma |
| Invalidez de um contacto | `owner_contacts.invalido_at`, `owner_contacts.motivo_invalido` ∈ {`bounce`, `rejeitado`} | O critério 7: «falha de entrega (*bounce*, rejeição) marca o contacto como inválido». **Dois valores e não quatro**, e a diferença é medida: um fornecedor em baixo (`indisponivel`) não diz nada sobre o endereço, e marcar o contacto por isso era deixar o dono sem canal por uma avaria **nossa**; e o `sem_contacto` não condena nada porque não há nada a condenar — tratá-lo como `bounce` marcava como inválido um endereço que não existe. O par é uma **igualdade e não uma implicação**: só com o motivo não se sabe quando, só com o instante não se sabe porquê. E um endereço **verificado** pode ficar inválido: os dois estados convivem, porque o critério 6 pergunta pela prova de que o dono um dia confirmou |
| Registo dos avisos | `platform.owner_notices` — `id`, `tenant_id`, `gatilho`, `episodio`, `chave`, `lembrete`, `canal`, `estado`, `tentativas`, `falha_motivo`, `criado_at`, `entregue_at`, `actualizado_at` | **Treze colunas, contra as oito que os *Detalhes Técnicos* nomeiam** (`notice_id`, `tenant_id`, `gatilho`, `episodio`, `canal`, `estado`, `criado_at`, `entregue_at`). O `notice_id` do bloco é o `id`, pela regra do §2 — «identificadores: UUID aleatório». As cinco a mais são a `chave` (o resumo que a unicidade usa), o `lembrete` (a ordem do lembrete), as `tentativas`, o `falha_motivo` e o `actualizado_at`. **Não há coluna de corpo**, e os *Detalhes* pedem-no por extenso — «com RLS e sem corpo»: o mesmo argumento que a `0018` escreveu para as contagens do histórico, uma regra que depende de ninguém escrever num sítio onde dá para escrever não é uma regra |
| A chave de idempotência | `owner_notices.chave` = `sha256(domínio ␀ tenant ␀ gatilho ␀ episódio)`, 32 octetos | O critério 2 escreve `hash(tenant_id, gatilho, episódio)`. O `tenant_id` lá dentro não é arrumação: sem ele, dois *tenants* com o mesmo `episodio` — e um `episodio` é muitas vezes um `channel_id` ou uma `event_key` da Meta — partilhavam a chave, e o segundo nunca era avisado. É `sha256` e **não** HMAC, porque não há segredo a proteger: quem lê a base vê o `episodio` na coluna ao lado, e o que a chave faz é dar comprimento fixo a um texto de comprimento arbitrário, que é o que um índice de unicidade quer. O separador é o **octeto nulo** pela razão que o `prova.ts` do KAM-022 escreveu |
| O episódio | `owner_notices.episodio` (`text`, não vazio) | **O que distingue «o canal caiu outra vez» de «o canal caiu»**, e é a segunda metade do critério 2 («um novo episódio depois de resolvido produz outro»). Texto **opaco** para esta tabela, cunhado por quem conhece o episódio: o `channel_id` com o motivo num desligamento, a `event_key` da Meta numa restrição de qualidade. **Não pode ser vazio**, e o `CHECK` está lá por isso: um `episodio` vazio punha todos os avisos do mesmo gatilho na mesma chave e o segundo episódio de um *tenant* nunca mais era avisado — o defeito mais silencioso possível neste módulo |
| Gatilho de um aviso | `owner_notices.gatilho` ∈ {`canal_desligado`, `inactividade`, `qualidade_restrita`, `sem_pagamento`, `painel_indisponivel`} | Os **cinco** do critério 1, e um gatilho fora da lista não envia nada — a lista é fechada nos dois lados, no `CHECK` e no `avisos/contrato.ts`, com um teste a comparar os dois contra o `pg_get_constraintdef`. **O gatilho é a *situação* e não o tipo do evento**: duas das cinco chegam pelo mesmo `channel.updated`, e se o gatilho fosse o tipo os dois casos tinham o mesmo texto — o «cada um com texto próprio e o passo seguinte» ficava sem sujeito. **Os seis motivos de `PARTNER_REMOVED` são um gatilho só**, e isto é decisão: o critério pede que os seis **gerem** aviso, não que gerem seis textos; o passo é o mesmo nos seis e o motivo vive no `episodio`. **Em minúsculas e sem acentos**, pela razão que a `0018` mediu — são também `outcome` de registo, e em modo estrito o `Logger` **levanta** o que a gramática recuse |
| Canal de um aviso | `owner_notices.canal` ∈ {`email`, `painel`} | **Dois, e o WhatsApp não é um deles** — nem podia: o ticket chama-se «por canal alternativo» porque avisar o dono pelo canal que falhou é inútil, e o critério 8 pede um teste de configuração a prová-lo. O aviso sai pelos **dois**, sempre, e é isso que faz o «tenta o painel» do critério 7 não precisar de um segundo caminho. As duas linhas contam como **um** aviso para o tecto diário: contar duas fazia o tecto de três valer um e meio |
| Estado de um aviso | `owner_notices.estado` ∈ {`pendente`, `entregue`, `falhado`} | Três, e **não há `suprimido`**: um aviso recusado por um limite de frequência **não escreve linha**. Escrever uma era inventar um aviso que não houve, e a pergunta «quantos avisos levou este dono hoje?» — que é o próprio limite — passava a ter de distinguir os que contam dos que não contam. O que se recusou **conta-se**, em `owner_notice_suppressed_total`. O `estado` nasce `pendente` mesmo quando a entrega é síncrona: registar-depois-entregar é a ordem do `outbound` do KAM-015, porque um aviso entregue que não se registou volta a sair e o dono recebe dois |
| Motivo de falha de um aviso | `owner_notices.falha_motivo` ∈ {`bounce`, `rejeitado`, `sem_contacto`, `indisponivel`} | **Quatro, e são mais do que os dois da invalidez do contacto.** Os dois primeiros são os do critério 7; o `sem_contacto` é o critério 6 a encontrar um *tenant* `ativo` sem endereço verificado; o `indisponivel` é o fornecedor em baixo. Os dois últimos **não** condenam o endereço — ver a invalidez, acima. Domínio **qualificado pela coluna** e diferente do `owner_contacts.motivo_invalido`, pela regra da emenda 1.14: são dois domínios da mesma ideia, e o do contacto é o mais pequeno |
| Ordem do lembrete | `owner_notices.lembrete` ∈ 0..2 | `0` o aviso próprio, `1` o lembrete das 24 h, `2` o das 72 h (critério 4). É esta coluna que faz a **idempotência do critério 2 e os lembretes do critério 4 caberem na mesma unicidade** `(tenant_id, chave, lembrete, canal)`: três entregas do mesmo evento tentam escrever a mesma linha e fica uma, e o lembrete das 24 h não colide com o aviso de que é lembrete. Com a unicidade sem ele, o critério 2 passava e o critério 4 era impossível. O `CHECK` de 0 a 2 é o «depois pára» do critério, **na base**: a regra de parar é a parte do limite que protege o dono de nós, e deixá-la só no código era deixá-la ao alcance do primeiro `if` mal escrito |
| Tentativas de entrega | `owner_notices.tentativas` (`smallint`, ≥ 0) | Quantas vezes se tentou entregar **este** aviso. **Não é o limite de frequência** — esse conta avisos, não tentativas —: é o que torna visível um fornecedor a devolver erro transitório em série. É também a coluna alterável que a receita de sementes do *gate* 6 usa, porque o `estado` está preso ao `entregue_at` por um `CHECK` e um `UPDATE` de uma coluna só levantava `23514` antes de a política ser avaliada |
| Quando o aviso foi criado | `owner_notices.criado_at` | **Escrito pelo relógio de quem chama e não pelo `now()` do servidor**, e o `DEFAULT now()` fica para quem insira à mão e para a semente do *gate* 6. A razão saiu do primeiro ensaio contra a base: os dois limites do critério 4 e os lembretes medem-se deste carimbo, e com ele escrito pelo servidor um relógio acelerado nos testes media uma coisa e a base registava outra — a varredura dos lembretes não via episódio nenhum. É a mesma razão pela qual o `prazo_em` da `0018` é coluna e não cálculo |
| Limites de frequência | `JANELA_DO_GATILHO_MS` = 24 h, `TECTO_DIARIO` = 3, `JANELA_DIARIA_MS` = 24 h | ***Propostas***, as três, e são a letra do critério 4: «≤ 1 aviso por (tenant, gatilho) em 24 h e ≤ 3 por tenant/dia». **A janela do gatilho avalia-se antes do tecto diário**, e a ordem é medida: com o tecto primeiro, um *tenant* com três episódios do mesmo gatilho gastava o dia todo num gatilho só e os outros quatro ficavam sem voz para as 24 h seguintes — a diferença entre um dono que sabe que tem três problemas e um dono que sabe três vezes o mesmo. O dia é **corrido** e não civil: um dia civil fazia o tecto reiniciar à meia-noite e um dono avisado três vezes às 23 h levava outros três uma hora depois |
| Atraso dos lembretes | `ATRASO_DO_LEMBRETE_MS` = [24 h, 72 h] | ***Propostas***, e são **dois valores de produto e não uma progressão**: escreve-se `[24, 72]` e não `[24, 24 × 3]` para que, se o Piloto mudar o segundo, ele não arraste o primeiro. A função devolve o lembrete **mais alto já devido** e não o seguinte ao enviado: um processo que esteve em baixo entre as 24 h e as 72 h não deve mandar os dois de seguida ao voltar. «Já acabou» e «ainda não é hora» são respostas **diferentes** e têm funções diferentes, porque levam a coisas opostas — esperar e abrir tarefa a T2 |
| Alvo de latência | `LATENCIA_ALVO_MS` = 5 min | ***Proposta***, e é o p95 do critério 3. Não é um prazo que o módulo imponha — é o alvo que a métrica existe para medir, e o corte de **300 s** está nos baldes do histograma para que o p95 se leia sem interpolar entre dois cortes |
| Limiar do painel em baixo | `LIMIAR_DO_PAINEL_MS` = 5 min | ***Proposta***, do critério 1 («HND indisponível > 5 min»). Quem mede a indisponibilidade é a sonda do KAM-002 e não este módulo; o que está aqui é o limiar que o gatilho pressupõe, para que o número viva num sítio só |
| Prazo da confirmação | `PRAZO_DA_CONFIRMACAO_MS` = 7 dias | ***Proposta***: o critério 6 pede a ligação e não lhe dá prazo. Escolhe-se **longa** de propósito — a ligação é a única coisa que separa um dono de poder ser avisado, e um prazo curto faz o dono que abriu o e-mail na segunda-feira seguinte ficar sem canal alternativo. A calibrar no Piloto |
| Parâmetros de um modelo | `PARAMETROS` = {`loja`, `estado`, `hora`, `painel`} | A lista branca do critério 5, **fechada e aplicada na construção**. Não há parâmetro de telefone, de contacto, de cliente nem de mensagem — e os quatro ficam aqui sem acento grave de propósito, porque um nome entre acentos graves no §3 é um nome **canónico** e estes são o contrário, são os que não existem: o critério pede «0 telefones, `contact_id`, BSUID ou texto de clientes», e a forma de o garantir é não haver parâmetro por onde isso entre — um varrimento *a posteriori* diz que um aviso leva um telefone, uma lista fechada faz o telefone não ter por onde entrar. **Fazem-se as duas**: a lista, e o varrimento sobre 200 avisos que o critério manda |
| O estado no texto | `ESTADOS_NO_TEXTO` ∈ {`restrito`, `desligado`, `suspenso`} | O `{estado}` é um parâmetro de modelo, e um parâmetro de texto livre era por onde a PII entrava. São os valores do `CHECK` da `0001` em `tenant_channels.estado` que fazem sentido num aviso — um dono não precisa de saber que o canal está `a_verificar` |
| A máscara do nome da loja | `MASCARA`, `DIGITOS_MAXIMOS` (reexportado), `MAXIMO_DA_LOJA` = 120 | O `loja` é o nome que o dono deu à loja — a coluna do nome do *tenant*, que vive em `../canon/extensoes.yaml` desde o KAM-003 e não neste documento —, e um dono pode ter escrito lá um telefone — «Loja do Zé 923 456 789» é um nome plausível em Luanda. **Mascara-se, não se recusa**: recusar fazia o dono não saber que o canal caiu por causa de como ele escreveu o nome da loja, que é castigá-lo por um defeito nosso. A fronteira é o `DIGITOS_MAXIMOS` do `logger/politica.ts` — **seis** —, **reexportado e não redeclarado**, pela razão que o `MPS_POR_MODO` do KAM-017 escreveu. A régua apanha corridas de sete ou mais dígitos **separadas por espaços, pontos, hífenes e barras**, que é como uma pessoa escreve um telefone à mão; e apanha o NIF e o IBAN pela mesma via, sem procurar o formato de cada um |
| A ligação ao painel | a raiz do painel, sem `?`, `#` nem `=` | O critério 5 pede «ligação ao painel sem *token* nem identificador pessoal no URL», e a razão é o canal: um URL vai para a caixa de correio do dono e para o histórico do navegador — um *token* num URL é um *token* publicado. Recusa-se a **forma** e não uma lista de parâmetros proibidos, que era uma lista que alguém havia de esquecer de actualizar. Diferente da ligação de **confirmação** do critério 6, que leva o *token* por natureza e não sai deste módulo |
| Métricas do aviso | `owner_notice_sent_total{gatilho,canal}`, `owner_notice_latency_s`, `owner_alt_contact_missing`, `owner_notice_suppressed_total{gatilho,motivo}`, `owner_notice_failed_total{canal,motivo}` | As **três** primeiras são as do DoD. As outras duas entram pela razão da emenda 1.21 e da 1.27: **recusar sem contar é recusar em silêncio** — e aqui isso é mais do que um princípio, porque há duas maneiras opostas de um aviso não chegar ao dono (nós recusámos, ou o fornecedor não entregou) e sem as duas séries um painel não distingue a regra a funcionar do canal alternativo quebrado. O critério 7 escreve-o: «nenhum aviso se perde em silêncio». **A primeira métrica desta casa com duas etiquetas**, e nenhuma é identificador: cinco gatilhos × dois canais são dez séries fixas, e o OBS-I recusa identificadores e não dimensões pequenas. O `owner_alt_contact_missing` é um **número** e não uma série por *tenant* — um `tenant_id` é um UUID com hífenes e **levanta** —, e publica-se com o seu total, porque a percentagem do critério 6 precisa de denominador |
| A porta de notificação | `OwnerNotifier` → `AvisoAoDono`, com `Notificador` por canal | O `OwnerNotifier.notify(tenant_id, gatilho, episodio, params)` dos *Detalhes Técnicos*. O `canal` está **dentro** da interface e não ao lado: com ele fora, nada impedia registar o notificador de e-mail no lugar do painel, e o aviso saía pelo canal errado sem que nada o dissesse. O `SmsNotifier` do bloco **não existe** — é o KAM-116 —, e o que existe é o lugar dele |
| A fila humana | `AbrirTarefa`, porta | O critério 6 e o 7 mandam «abrir tarefa a T2», e **não existe mecanismo de *ticket* neste repositório** — dívida **73**, escrita pelo KAM-021. Inventar um a partir de um critério deste ticket era alargar o escopo em silêncio. O que o módulo garante é que **chama**, e há teste da chamada |

**O que esta emenda não decide, e fica por marcar.** O **alvo de «≥ 95% dos
*tenants* `ativo` com contacto verificado»** (critério 6) é uma medição sobre
*tenants* reais, e não há nenhum: a métrica que o mede está entregue, com
numerador e denominador, e a varredura que a alimenta também; o número sai no
Piloto. Afirmar a percentagem contra dois *tenants* de ensaio era afirmar 100% de
nada. E o **fornecedor de e-mail no inventário de subprocessadores** (critério 8)
é uma escolha com contrato e procedimento APD (KAM-069, ADR-008): o próprio
critério escreve a alternativa — «ou fica `pendente` e bloqueia `prod`» — e é o
que está. Também não decide: o adaptador SMS (**KAM-116**), o número operacional
da KAMBÁ (**D10**, **KAM-101**), a captação do e-mail e a entrega da ligação de
confirmação (**KAM-086**), a base legal e a finalidade do contacto do dono
(**KAM-104**), os *runbooks* (**KAM-083**) e os avisos de cobrança (**KAM-058**).

---

### 3.24 Runtime de agentes: a API interna, a tranca e os tectos (KAM-025)

*Emenda 1.33, **proposta**.* Entra **sem DDL**, e é a quarta assim (como as
1.25, 1.29 e as métricas da 1.21): o KAM-025 não cria tabela nenhuma — a tranca
é um `pg_advisory_lock`, que não tem tabela, e as duas que ele lê
(`conversations` e `handoffs`) existem desde as revisões `0009` e `0011`. A
cadeia de migrações **fica na `0019`**. O que entra aqui são os nomes que o
código passa a usar e que nenhum documento nomeia: a credencial da API interna,
os quatro tectos, e as métricas.

A fonte do desenho é `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§4.2
regra 4, §5.3, §11 regra 3, §12, §15.2) e
[`../docs/adr/ADR-L004-fila-e-tranca-do-agr.md`](../docs/adr/ADR-L004-fila-e-tranca-do-agr.md),
que é onde as duas decisões que o bloco do ticket manda registar estão escritas,
com as opções que se pesaram.

**O `turn_id` resolve-se aqui, e era uma lacuna declarada.** O §3.13 fecha
dizendo que não decide o `turn_id` — «o contexto do KAM-025 nomeia um `turn_id`
igual ao `wamid`, e o contrato `agent_invocation` leva o `wamid` com esse nome;
se o AGR preferir `turn_id`, é o KAM-025 que o acrescenta». A decisão é: **o
`turn_id` é uma propriedade derivada e não um campo do contrato**. O contrato
fica com nove campos, e `InvocacaoDoAgente.turn_id` devolve o `wamid`. O nome
existe porque é o que a *allowlist* de `../docs/tecnica/08` §7.3 conhece e o que
a `idempotency_key = turn_id:seq` do critério 4 nomeia; o valor é um só, que é
exactamente o que o §3.13 pedia.

| Conceito | Nome canónico | Nota |
|---|---|---|
| Identificador do turno | `turn_id` = o `wamid` da mensagem que o iniciou | **Derivado, não campo.** Resolve a lacuna que o §3.13 deixou por escrito. Já estava na *allowlist* de *logs* (`../docs/tecnica/08` §7.3) sem nenhum documento dizer o que era |
| Chave de idempotência de um envio do turno | `idempotency_key` = `{turn_id}:{seq}`, com `seq` a contar **dentro** do turno e a reiniciar em cada volta | É o critério 4 por extenso. O `seq` reiniciar é o que faz «0 duplicados» ser consequência da repetição e não coincidência: um contador que sobrevivesse à repetição dava chaves novas e o Outbound mandava a mensagem duas vezes. **Não é o `handoff_seq`** do §5.3, que conta *handoffs* e é do KAM-034 |
| Rotas internas do AGR | `POST /internal/turn`, `POST /internal/resume`, e a `GET /healthz` que já existia | «API interna mínima» é o adjectivo do §4.2 regra 4, e cumpre-se à letra: duas rotas, nenhuma de leitura, nenhuma de administração. A `/healthz` **não** leva credencial — uma sonda que precisa de segredo é uma sonda que falha no dia em que o segredo roda |
| Cabeçalho da credencial interna | `x-kamba-interno` | Em minúsculas, e não é estética: os cabeçalhos ASGI chegam em minúsculas, e um `X-Kamba-Interno` escrito no código nunca casava |
| Credencial da API interna | `agr_internal_token` (§3.9 dá a forma) | **Dois consumidores e não um:** o AGR verifica e quem chama apresenta — o *shim* da fila e o HND, que faz o `POST /internal/resume` da retoma (§11 regra 3). Sem anel: a comparação é em tempo constante contra **um** valor, e um anel obrigava a comparar contra dois — o que duplica a superfície de um segredo que roda sem corte, porque o *shim* repete o *job*. Entrada em `../ops/secrets-inventory.yaml` |
| Chave da tranca por conversa | `pg_advisory_lock(hashtextextended(thread_id, 0))`, **de sessão**, numa ligação dedicada | A decisão, com as três opções, está em `ADR-L004` (Decisão 2). **A chave colide de propósito com a do `pg_advisory_xact_lock(hash(tenant_id, contact_id))` do §3.20** (KAM-018): os dois textos são o mesmo, e é isso que faz uma transição de modo em curso travar a entrada de um turno. Medido em `../db/tests_agr/test_tranca.py` — é uma afirmação sobre o `hashtextextended` e só a base a confirma |
| Quem consome a fila `agr-inbound` | *shim* em TypeScript (`@kamba/core-ts/agr`), hospedado em `services/worker-canal/src/agr_shim.ts` | `ADR-L004`, Decisão 1. **Não** há consumidor Python do BullMQ: a compatibilidade de protocolo entre o `bullmq` Python 3.3.1 e o TypeScript 6.3.11 que o CHR usa é **NÃO VERIFICADA** (`../docs/tecnica/evidencia/E4` §2.10 nomeia as duas e não a afirma). O que faria rever a decisão está escrito no ADR |
| Tectos do AGR, por variável de ambiente | `AGR_RITMO_POR_CONTACTO` (20), `AGR_TECTO_POR_TENANT` (3), `AGR_COALESCENCIA_MS` (1500), `AGR_LIMIAR_DE_CONTRAPRESSAO` (100) | Os quatro são ***proposta*** e calibram-se em KAM-084; os três primeiros vêm do critério 3 e do critério 5, e o quarto é o «limiar» da regra 4 do §15.2, que nenhum documento numera. **Zero é sem limite** no ritmo e no tecto, e isso é parte do contrato e não um descuido: é o modo em que o critério 2 se mede. Um valor que não seja inteiro **levanta** em vez de cair na omissão |
| URL do AGR na rede interna | `KAMBA_AGR_URL`; a porta da sonda do *shim* é `AGR_SHIM_PORT` (3025) | Só o *shim* as lê. O AGR **não** ganha variável de ligação própria: lê as de `../db/ligacao.py` (`KAMBA_DB_HOST`, `KAMBA_DB_PORT`, `KAMBA_DB_NAME`, `KAMBA_SECRET_DB_APP_PASSWORD`) com o papel `kamba_app` do §3.2, e um segundo conjunto de nomes para a mesma base era o defeito que o §3.13 pagou ao inventar `KAMBA_CHR_*_DB_URL` |
| Métricas do AGR | `agr_turns_total{outcome}`, `agr_turn_latency_ms`, `agr_queue_depth`, `agr_admitted_rejected_total{motivo}`, `agr_coalesced_total`, `agr_backpressure_total` | **Seis, e o DoD do ticket nomeia três** («fila, latência de turno e `degraded_turns`»). Duas das três estão; a terceira não — ver abaixo. As outras quatro são o que torna visível o que o ticket recusa: sem a de recusa, um descarte por ritmo e um tecto cheio são indistinguíveis de «ninguém escreveu»; sem a de coalescência, o critério 3 não tem onde aparecer; sem a de contrapressão, a regra 4 do §15.2 não tem onde aparecer. É a mesma razão do `chr_resolve_total` da emenda 1.20 e do `conv_mode_rejected_total` da 1.29: recusar sem contar é recusar em silêncio |
| Desfecho de um turno (etiqueta `outcome`) | `executado`, `entregue_ao_hnd`, `sem_conversa`, `falhou` | Lista **fechada** no código, como o `wa_type` do §3.12 e o desfecho do §3.13. `sem_conversa` junta três casos — a conversa não existe, foi apagada, ou o contexto de RLS é de outro *tenant* —, e a junção é deliberada: as três dão a mesma decisão (não entra no grafo) e a razão exacta não está ao alcance de quem lê zero linhas |
| Razão de uma recusa na admissão (etiqueta `motivo`) | `ritmo`, `tecto_do_tenant`, `invocacao_invalida` | Lista **fechada**. `tecto_do_tenant` contém a palavra «tenant» e **não** é um identificador: é por isso que a regra do `OBS-I` se impõe pela gramática da etiqueta e não por uma lista de palavras proibidas |
| Métricas do *shim* da fila | `agr_shim_total{outcome}` — com `outcome` de **nove** valores, os oito que o AGR responde (`executado`, `entregue_ao_hnd`, `sem_conversa`, `descartado`, `tecto_do_tenant`, `grafo_nao_registado`, `invocacao_invalida`, `nao_autorizado`) mais `desconhecido` para uma resposta que não é nenhuma delas — e `agr_shim_failed_total` | **Do lado TypeScript**, e nenhuma repete um nome do AGR. O que só o *shim* vê é o que aconteceu ao ***job***, e a diferença é a que importa: um `agr_shim_total{outcome="executado"}` muito abaixo de `agr_turns_total{outcome="executado"}` significa que o AGR corre turnos que o *shim* não sabe que correram — isto é, que o `lockDuration` está curto e há *jobs* duplicados. **O `desconhecido` existe e é o nono valor**, porque uma resposta que o *shim* não reconhece tem de ter onde aparecer; a lista era fechada no código e estava sem domínio aqui, o que a revisão adversarial apanhou |
| Turnos em modo determinístico | `agr_degraded_turns_total` — **pertence ao AGR e nasce com o KAM-037** | Não entra em código neste ticket, e **a caixa do DoD fica por marcar**. A razão é a que a emenda 1.29 escreveu para o `echo_latency_ms`: uma métrica declarada e sempre a zero é pior do que uma métrica ausente — um painel que a mostre a zero diz «não houve turnos degradados» quando o que se passa é que ninguém os mede. O `degraded_turns` do §14 conta turnos que correram em **modo determinístico** por o LLM estar indisponível, lento ou sem orçamento, e o modo determinístico é o KAM-037: não há, neste ticket, caminho nenhum por onde um turno possa ficar degradado. O que existe e conta de verdade é o `agr_backpressure_total`, que é o sinal que o KAM-037 vai consumir |

**O que esta secção NÃO decide.** O checkpointer e o esquema `lg` (**KAM-026**,
que também cria o papel `kamba_agr`), o AgentRegistry (**KAM-027**), a ToolLayer
(**KAM-028**), os grafos (**KAM-031** e **KAM-035**), o modo determinístico e a
métrica dele (**KAM-037**), o *compare-and-set* da retoma do *handoff*
(**KAM-034** — o KAM-025 entrega a rota, a autenticação, a validação do corpo e
o *lock*, e a porta levanta `NotImplementedError` em vez de devolver 200 a
fingir), a aplicação da *allowlist* de saída na rede (**KAM-076**) e a
calibração dos quatro tectos (**KAM-084**).

**E não decide os campos do `ConversaState`.** As dezenove chaves do §5.3 de
`../docs/tecnica/02` são canon citado e o AGR constrói-as com esses nomes; o
`schema_version` nasce a `1`. As sub-estruturas (`cart`, `slots`, `stt`,
`guard`, `facts`, `draft`, `handoff`) ficam por tipar, e tipá-las era decidir
pelos tickets que as definem.

---

### 3.25 Checkpointer: o esquema `lg`, as duas tabelas e o papel (KAM-026)

*Emenda 1.34, **proposta**.* O `lg` já era canónico desde o §3.6 e o §3.24 já
dizia que é este ticket que o cria. O que entra aqui são os nomes que a revisão
`0020` escreve: o papel, as duas tabelas e as colunas delas.

A fonte é `../docs/tecnica/02_Agent_Runtime_Verticais.md` §12 e a interface
`BaseCheckpointSaver` do `langgraph-checkpoint` 4.3.0, que é quem dá forma às
colunas — elas são o `CheckpointTuple` dela, não um desenho nosso.

**O `checkpointer` é nosso e o pacote que o canon nomeava não entra.** O
`docs/tecnica/02` §12 nomeia o `langgraph-checkpoint-postgres` 3.1.2 e o `E4`
§2.6 dá-o como «MIT, sem restrições». O pacote é MIT; o fecho dele exige
`psycopg` e `psycopg-pool`, **LGPL-3.0-only**, que o `ci/licenses.yaml` nega por
prefixo e que este repositório já recusou pelo nome duas vezes por escrito. O
que entra é o `langgraph-checkpoint` — a interface e o serializador —, e o SQL é
nosso, sobre o `pg8000`.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Papel do checkpointer | `kamba_agr` | — | `NOBYPASSRLS`, **sem `USAGE` no `platform`**. É o segundo papel do AGR: o `kamba_app` lê o `platform`, este escreve o `lg` e não vê mais nada |
| Palavra-passe do papel | `db_agr_password` | — | `KAMBA_SECRET_DB_AGR_PASSWORD`, obrigatória nos três ambientes: sem ela o AGR não arranca |
| Tabela dos checkpoints | `lg.checkpoints` | — | Oito colunas. O `Checkpoint` inteiro numa coluna, `channel_values` incluídos |
| Tabela das escritas pendentes | `lg.checkpoint_writes` | — | Nove colunas. É o `pending_writes` do `CheckpointTuple` |
| Chave da *thread* | `thread_id` | — | Já canónico (§3.1); o domínio é `^<uuid>:<uuid>$` e impõe-se **à entrada**, no `contexto.py`, não por `CHECK`: o `thread_id` do LangGraph é texto livre no contrato da biblioteca |
| *Namespace* do subgrafo | `checkpoint_ns` | — | Cadeia vazia no grafo de topo, e é por isso que tem `DEFAULT ''`: entra na chave primária |
| Identificador do checkpoint | `checkpoint_id` | — | Único e **monotonicamente crescente**: é ele que ordena, não o `criado_at` |
| Pai na cadeia | `parent_checkpoint_id` | — | Nulo no primeiro checkpoint da *thread* |
| Estado serializado | `checkpoint` | — | A coluna `bytea` com o `Checkpoint` inteiro, `channel_values` incluídos. É o mesmo nome do conceito, e é deliberado: a tabela chama-se `checkpoints` e a coluna é o checkpoint |
| Metadados do passo | `metadata` | — | A coluna `bytea` com o `CheckpointMetadata`: o número do passo, a origem, o que o LangGraph lá puser |
| Valor da escrita pendente | `blob` | — | A coluna `bytea` de `checkpoint_writes`. É o nome da interface, e **não** se traduz: o par `(type, blob)` é o que o serializador devolve e volta a receber |
| Discriminador do serializador | `type`, `metadata_type` | — | **Dois e não um**: os dois objectos passam pelo mesmo serializador mas o tipo de um não é garantidamente o do outro |
| Caminho da tarefa | `task_path` | — | Entra na ordem (`writes_sort_key` é `(task_path, task_id, idx)`), não na chave |
| Canal da escrita | `channel` | — | **Em inglês de propósito:** `canal` já é o canal de WhatsApp (§3.6), e dois conceitos com o mesmo nome é o defeito que este documento existe para fechar |
| Janela de mensagens | `JANELA_MAXIMA` | — | O `K` do §12, a **20** como ***proposta***. Calibra-se no *golden* (KAM-040) e no `llm_call_log` (KAM-030) |
| Inactividade até apagar | `DIAS_DE_INACTIVIDADE` | — | **30** dias, ***proposta***. Ver «os dois prazos», abaixo |

**A RLS não se aplica, e isso é a decisão que o bloco manda registar.** O
ADR-015 manda `FORCE ROW LEVEL SECURITY` «em todas as tabelas com `tenant_id`»;
estas não têm — a chave é o `thread_id` e o `tenant_id` vive lá dentro, como
prefixo. Não é contradição do ADR, é a ausência da condição que ele nomeia. O
isolamento assenta em três coisas e nenhuma é a RLS: o prefixo do `thread_id`,
construído **só** do estado validado e conferido antes de cada turno; o papel
sem `USAGE` no `platform`; e o ensaio cruzado que mede as duas contra a base. O
`ci/rls_exceptions.yaml` não leva linha nenhuma — aquele ficheiro é para tabelas
**com** `tenant_id` que dispensem a política, e uma excepção morta falha o
*gate* 6.

**Os dois prazos de retenção, e nenhum é decisão deste ticket.** O
`../docs/tecnica/02` §12 diz *threads* inactivos **> 30 dias**; o
`../docs/tecnica/08` §7.1 e §11 dizem conteúdo de conversa **90 dias após o
fecho**, que é também o que o KAM-071 toma. E não são o mesmo relógio: um conta
inactividade, o outro conta do **fecho da conversa** — que **não está definido
em documento nenhum**. Fica o valor do §12 como *proposta*, porque é o que o
bloco cita, e o prazo espera parecer, como o próprio §11 já diz.

**O que esta emenda não decide.** A cifra do conteúdo do `lg`: o
`../docs/tecnica/06` §7.6.2 diz que mensagens e *checkpoints* do AGR são
cifrados com a DEK do contacto, «incluindo nos *backups*», e nem o §12 nem o
bloco falam de cifra. O `SerializerProtocol` do LangGraph tem um
`CipherProtocol`, pelo que o sítio existe. Fica nomeado, com dono por atribuir.

---

### 3.26 AgentRegistry: o registo das verticais, as seis validações e o modo de um gate (KAM-027)

*Emenda 1.35, **proposta**.* O `registry/` já era canónico — o §3.2 fixa
`id ∈ {vendedor, servicos, catalogo, social, orcamento}` «no registo
(`registry/*.yaml`)» e a emenda 1.17 pôs lá a lista fechada de planos. O que
entra aqui são os nomes que os ficheiros das **verticais** escrevem, os **seis
nós** que um grafo tem de ter, as **onze** tools do catálogo do Piloto e a
terceira forma desta superfície.

A fonte é `../docs/tecnica/02_Agent_Runtime_Verticais.md` §5.1 (o esquema), §5.2
(as seis validações) e §6.2 (o catálogo de tools), com o ADR-012 (verticais como
configuração) e o ADR-011 (`phase: D` fora de produção no Piloto).

**`valor_max_pedido_kz` não entra, e isto é uma correcção ao desenho.** O
exemplo de `../docs/tecnica/02` §5.1 e os *Detalhes Técnicos* do bloco do
KAM-027 escrevem `limites: [msgs_ai_mes, valor_max_pedido_kz]`. A emenda 1.13
registou `valor_max_pedido_kz` como **variante** que este dicionário substitui
por `valor_max_pedido_minor`, pelo que o *gate* 3b o trata como achado de nível
1 — falha sempre, e um `registry/vendedor.yaml` escrito à letra do §5.1 **não
passava**. O próprio bloco previa a resolução («a divergência nominal resolve-se
com o KAM-009, e unidades em *minor*»), e o KAM-009 está feito: a chave canónica
é `valor_max_pedido_minor`. Fonte 3 sobre fontes 6 e 7.

**`registry/gates.yaml` é a terceira forma desta superfície, e as duas fontes
discordavam.** O §5.1 põe o gate dentro da vertical
(`golden: { dataset, gate: "gates/vendedor.yaml" }`); o critério 8 do bloco
manda registá-lo em `registry/gates.yaml`. Resolve-se a favor do bloco (fonte 6
sobre fonte 7): a vertical mantém o `golden` que o §5.1 lhe dá, com o
**dataset**, e o `registry/gates.yaml` leva o **modo** de cada validação. A
duplicação do caminho do dataset nos dois ficheiros não fica à solta — o
`load_all` exige que coincidam e recusa o registo se não coincidirem.

**O `servicos.yaml` subscreve os dois eventos de pagamento, e isso já era
canónico.** O bloco dá o `payment.manual_confirmed` como *proposta* a confirmar
no KAM-038; a linha «Evento do gate da Fase 0» do §3.5 já o decidiu por
extenso, e o *gate* 3b já impõe a regra («quem não distingue os dois caminhos
subscreve os dois»). Não é decisão deste ticket: é cumprimento.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Registo de verticais | `AgentRegistry` | — | Já nomeado em `../docs/tecnica/00` §4 (REG) e no ADR-012 como costura definitiva. Vive no AGR e não em `libs/py-core`: é o único serviço que o constrói e o lê, a mesma razão escrita no `estado.py` do KAM-025 |
| Carregamento e validação no arranque | `load_all` | — | Corre as **seis** validações do §5.2 e falha o arranque. Em inglês porque é o nome do contrato do §5.2, como `resolve` e `build_graph` |
| Resolução por contexto | `resolve` | — | Por `ctx.vertical` **e** entitlement activo do tenant. Uma só vertical principal por número no Piloto: não agrega, não encaminha |
| Contrato de uma vertical | `Vertical`, com `build_graph(deps)` | «persona» como sinónimo de vertical (§3.2) | `Protocol`. O `deps` injecta ToolLayer, LLM, HND e Outbound — nenhum existe neste ticket, e por isso o grafo constrói-se fora dele |
| Nós obrigatórios de um grafo | `ingest`, `guard_in`, `validate`, `guard_out`, `send`, `handoff_wait` | — | Validação (3) do §5.2. São **nós partilhados** (§5.4, «Regra de dois»), não da vertical; o `handoff_wait` é o `handoff_*` do §5.4 que suspende no `interrupt()` |
| Terceira forma do registo | `registry/gates.yaml`, chave de topo `gates` | `gates/vendedor.yaml` (`../docs/tecnica/02` §5.1) | As outras duas são a vertical (chave `id`) e os planos (chave `plans`). O *gate* 3b distingue-as pela chave de topo e nunca pelo nome do ficheiro |
| Modo de uma validação | `modo` ∈ {`aviso`, `bloqueio`}, com `credor` | — | O §5.1 e o exemplo do bloco escrevem `warn` e `block`, e **não** se registam como variantes: são duas palavras inglesas correntes, e pô-las na coluna «Substitui» fazia de qualquer `warn` em prosa um achado de nível 1 em todo o conjunto — a lição do ADR-L001 §10 («um gate que bloqueia o que ninguém escolheu é um gate que alguém acaba por desligar»). Quem as recusa é a lista fechada do `registry/gates.yaml`, onde elas importam. `bloqueio` é a omissão: uma validação que o ficheiro não nomeie **falha fechada**. Um `modo: aviso` sem `credor` é recusado — um atalho sem o ticket que o fecha não é atalho |
| As seis validações, por nome | `tools`, `entitlements`, `grafo`, `subscriptions`, `fase`, `golden` | — | A ordem é a do §5.2. Lista fechada no código: um nome a mais em `registry/gates.yaml` é recusado, senão um `tool` escrito por `tools` desligava a validação em silêncio |
| Tool de pesquisa no catálogo | `search_catalog` (tool search_catalog) | — | `../docs/tecnica/02` §6.2, classe `read`. Vendedor. As especificações são do KAM-028 e do KAM-031; o que entra aqui é o **nome** |
| Tool de preço e stock | `get_price_stock` (tool get_price_stock) | — | §6.2, `read`. Vendedor. Devolve *facts* `price` e `stock` |
| Tool de proposta de carrinho | `propose_cart` (tool propose_cart) | — | §6.2, `read`. Vendedor. Devolve `cart_id` e o *fact* do total; sem efeitos |
| Tool de criação de pedido | `criar_pedido` (tool criar_pedido) | — | §6.2, classe `money`, botão `confirm:{cart_id}`. Vendedor. O único nome do catálogo em português, como o §6.2 o escreve |
| Tool de estado de pedido | `get_order_status` (tool get_order_status) | — | §6.2, `read`. Vendedor. Só encomendas do **próprio** contacto |
| Tool de informação da loja | `get_store_info` (tool get_store_info) | — | §6.2, `read`. **Nas duas verticais** — é a primeira tool real do KAM-028 |
| Tool de lista de serviços | `list_services` (tool list_services) | — | §6.2, `read`. Serviços |
| Tool de disponibilidade | `get_availability` (tool get_availability) | — | §6.2, `read`. Serviços. Devolve *slots* como *facts* `datetime` |
| Tool de marcação | `book_slot` (tool book_slot) | — | §6.2, classe `write`, botão `confirm:{hold_id}`. Serviços |
| Tool de cancelamento de marcação | `cancel_booking` (tool cancel_booking) | — | §6.2, `write`, botão. Serviços |
| Tool de reagendamento | `reschedule_booking` (tool reschedule_booking) | — | §6.2, `write`, botão. Serviços. Atómica (cancela e marca) |
| Parâmetros proibidos no esquema visível ao modelo | `tenant_id`, `merchant_id`, `seller`, `account` | — | Lista **fechada** e de **proibidos**, ao contrário do resto deste documento: são os quatro que o critério 2 do KAM-027 e o critério 3 do KAM-028 nomeiam. O `tenant_id` é nome canónico (§3.1) e é precisamente por isso que não pode chegar ao modelo (ADR-002, ADR-015) |
| O que `resolve` devolve | `Resolucao`, com `vertical`, `resposta` e `motivo` | — | Exactamente **um** dos dois lados vem preenchido. O §5.2 escreve `resolve(ctx) -> Vertical`, e um `Vertical` não tem onde levar a resposta estática que o critério 6 pede; levantar uma excepção punha o caminho normal de um tenant sem plano a passar por um `except`, e é assim que uma recusa prevista deixa de se distinguir de um defeito |
| Classe de problema que um `aviso` pode calar | `PorLigar` | — | «A fonte que esta validação confronta não existe neste repositório.» É a **única** classe que o `modo: aviso` cala; qualquer outro problema bloqueia o arranque seja qual for o modo. Sem a distinção, no dia em que o credor chegasse a linha do `gates.yaml` sobrevivia e um defeito real passava a aviso — e um `aviso` que sobrevive ao credor é, ele próprio, erro de arranque |
| Validação adiada, no registo de arranque | `Adiada`, com `validacao`, `vertical` e `credor` | — | O `error_code` é `<validacao>_<credor em minúsculas, com `_`>`: `tools_kam_028`. **Não leva o texto do problema:** o `error_code` da *allowlist* de `../docs/tecnica/08` §7.3 é um identificador de 96 caracteres, e uma frase ali **cai em silêncio** — o arranque dizia ter registado os avisos e não registava nenhum |
| Fases em que uma vertical `phase: D` pode correr | `FASES_POSTERIORES`, **lista vazia** | — | O canon define **um** valor para `KAMBA_FASE`: `piloto`. Uma vertical diferida não arranca em ambiente nenhum até a Fase C entrar aqui por emenda. Ler «≠ `piloto`» como «já se pode» era inventar canon, e punha o `assistente` em produção com um `KAMBA_FASE` escrito por engano (ADR-011) |
| Resposta sem entitlement activo | `servico_indisponivel` | — | O identificador da resposta estática do critério 6, não o texto. O texto ao cliente é português de Angola e vive no `compose` (KAM-033); um identificador é o que cabe num `error_code` da *allowlist* de `../docs/tecnica/08` §7.3 |
| Métrica das resoluções negadas | `agr_registry_denied_total` | — | Etiqueta `motivo` ∈ {`sem_entitlement`, `vertical_desconhecida`}, lista fechada. **Nunca `tenant_id`** (`../docs/seguranca/ameacas_stride.md`, `OBS-I`): a gramática de etiqueta de `metricas.py` recusa-o pela forma |
| Código de saída de registo inválido | `5` | — | Próprio, pela razão escrita no §3.25 e no `__main__.py`: o `2` é configuração inválida, o `3` a guarda do ADR-002, o `4` a falta de checkpointer. Num painel, «o AGR não arranca» sem dizer porquê não se diagnostica |
| Directório do registo | `KAMBA_REGISTRY_DIR` | — | Omissão `registry`, relativa ao directório de trabalho do processo. A forma `KAMBA_*` é a do §3.9 e do §3.11. É o primeiro ficheiro do repositório que um serviço lê em execução, e por isso entra no `Dockerfile` do AGR por `COPY` |

**A validação (6) nasce em `aviso`, e está escrito em três sítios.** O critério 8
do bloco di-lo: o *gate* do *golden* corre em modo aviso até o KAM-040 existir, e
passa a bloqueante quando ele ficar `Done`. Não é a única: a (1) precisa do
catálogo da ToolLayer, que é o KAM-028, e a (3) precisa de um grafo compilado,
que é o KAM-031 e o KAM-035. As três ficam em `aviso` com o seu `credor` nomeado
em `registry/gates.yaml`; as outras três — `entitlements` contra o
`CHAVES_DE_LIMITE` do TEN, `subscriptions` contra o `CATALOGO` de
`kamba_core.eventos.contratos`, e `fase` contra o `KAMBA_FASE` de
`fluxo_piloto` — correm em `bloqueio` desde já, porque as fontes **existem**.

**O que esta emenda não decide.** O nome do módulo que constrói cada grafo. O
§5.1 escreve `graph: kamba.verticals.vendedor:build_graph`, e esse caminho não
existe nem pode existir: o pacote chama-se `kamba_agr` e o KAM-025 já decidiu,
por extenso, que o que é só do AGR vive nele. Os ficheiros das verticais levam
`kamba_agr.verticais.<id>:build_graph` como ***proposta***, e quem o ratifica é
o ticket que escreve o módulo (KAM-031 para o Vendedor, KAM-035 para Serviços).
Enquanto não existir, a validação (3) está em `aviso` e o alvo não resolve — que
é a razão pela qual `resolve` não devolve grafo nenhum e o `/internal/turn`
continua a responder 503.

---

### 3.27 ToolLayer: o contrato, as classes, a auditoria e os erros (KAM-028)

*Emenda 1.36, **proposta**.* A emenda 1.35 pôs aqui os **nomes** das onze tools
do catálogo do Piloto e disse, por extenso, que «as especificações são do
KAM-028 e do KAM-031». Esta emenda traz o resto: o contrato da camada, as três
classes, a tabela `tool_audit`, os dez erros tipados e os dois nomes do
`ToolContext` que **nenhuma** chave do estado tinha — `run_id` e `graph_version`.

A fonte é `../docs/tecnica/02_Agent_Runtime_Verticais.md` §6.1 (o contrato e os
oito passos), §6.2 (o catálogo), §6.4 (o DDL) e §6.5 (os erros), com o
`../docs/tecnica/08_Seguranca_Conformidade.md` §3.2 (o *lint*), §4.3 (L3) e §6
(auditoria), e os ADR-007, ADR-013 e ADR-015.

**Os nomes do contrato ficam em inglês, e a razão é a da emenda 1.35.** O §6.1
escreve `ToolLayer`, `for_context`, `invoke`, `ToolContext`, `ToolResult`,
`Fact` e `Confirmation`, como o §5.2 escreve `load_all`, `resolve` e
`build_graph`. São nomes de contrato citados de documento técnico; traduzi-los
criava um segundo nome para a mesma coisa, que é o defeito que este documento
existe para fechar. O que é **nosso** — módulos, classes internas, variáveis de
ambiente, métricas — segue o português do resto do código do AGR.

**`run_id` e `graph_version` não são chaves do estado, e não podem ser.** O
§5.3 fixa dezenove chaves e o `estado.py` do KAM-025 escreve que «não se
acrescenta nenhuma». As duas vêm de outro lado: o `graph_version` é o `version`
que a vertical declara em `registry/*.yaml`, e o `run_id` identifica **uma
execução** do grafo — nasce no executor de turnos, não no estado que o
*checkpointer* persiste. Pô-los no estado era gravar, a cada *checkpoint*, um
número que só vale enquanto o processo corre.

**O `klass` escreve-se com dois `s`, e é de propósito.** É o nome da coluna no
DDL do §6.4 e o do campo da especificação, porque `class` é palavra reservada
em Python. Não é variante de `classe`: é o nome canónico desta coluna e deste
campo, e `classe` em prosa refere-se à mesma coisa.

**O que o §6.2 chama «morada» não existe no esquema, e não se inventa.** A linha
do `get_store_info` do §6.2 diz «Horário, morada, Plus Code». A
`platform.tenants` da `0001` tem `fuso_horario`, `zona` e `plus_code`, e **não**
tem coluna de morada — e `morada` é um dos sete nomes que o *lint* de PII do
`../docs/tecnica/08` §7.3 proíbe. A tool devolve as três colunas que existem;
acrescentar uma morada é decisão de quem a acrescentar à `tenants`, e não deste
ticket. Fonte 3 sobre fonte 7.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Camada de tools | `ToolLayer`, com `for_context(ctx, allowed)` e `invoke(ctx, name, args, confirmation)` | — | `../docs/tecnica/02` §6.1. **A única via** de leitura e escrita dos agentes (ADR-015). Vive no AGR e não em `libs/py-core`, pela razão escrita no `estado.py` do KAM-025: é o único serviço que a constrói e a lê |
| Contexto de um turno, para tools | `ToolContext`, com `tenant_id`, `channel_id`, `contact_id`, `conversation_id`, `turn_id`, `vertical`, `run_id`, `graph_version` | — | `frozen`, construído **do estado** e nunca de texto (§6.1). Oito campos, e os seis primeiros são chaves do §5.3 |
| Identificador de uma execução do grafo | `run_id` | — | Texto opaco, por invocação. **Não** é chave do estado (§5.3 tem dezenove e fecha): nasce no executor de turnos. Coluna de `tool_audit` |
| Versão do grafo que corre o turno | `graph_version` | — | O `version` que a vertical declara em `registry/*.yaml`. **Não** é chave do estado, pela mesma razão. Coluna de `tool_audit` |
| Tool ligada a um contexto | `BoundTool`, com o nome da tool, o `klass`, a versão e o esquema visível ao modelo | — | O que `for_context` devolve: uma tool **já fechada** sobre o `ToolContext`. O modelo recebe o esquema e nunca o contexto |
| Classe de uma tool | `klass` ∈ {`read`, `write`, `money`} | — | Lista **fechada**. É o mecanismo de L3 contra injecção (`../docs/tecnica/08` §4.3): `read` livre, `write` com confirmação, `money` com confirmação, tecto e auditoria (ADR-015). Escreve-se `klass` por ser o nome da coluna do §6.4 e porque `class` é reservada em Python |
| Resultado de uma invocação | `ToolResult`, com `ok`, `data`, `facts`, `error`, `idempotent_replay` | — | §6.1. O `idempotent_replay` nasce sempre `False`: quem o põe a `True` é o KAM-029 |
| Número vindo de uma tool | `Fact`, com `fact_id`, `kind`, `value`, `retrieved_at` e `sku` | — | ADR-007: «o número é prova, o texto não». O validador de citação do KAM-032 cita-os por `fact_id`. O `facts` do estado (§5.3) é a lista destes, **só do turno**. O `sku` é **anulável** e entra porque o consumidor o declarou: o KAM-032 pede `Fact(kind, …, sku, fact_id, retrieved_at)` e o vínculo `sku`↔preço é metade do que ele faz; um `total` de carrinho e um `datetime` de *slot* não têm `sku`. O campo do valor chama-se `value` e **não** `value_kz`: o §2 manda dinheiro em unidade menor inteira, e `valor_kz` é variante que este documento substitui — e um `value_kz` num *fact* de `stock` era o nome errado. As duas divergências com o bloco do KAM-032 estão em `../docs/dividas-documentais.md` |
| Natureza de um *fact* | `kind` ∈ {`price`, `stock`, `total`, `datetime`} | — | Lista **fechada**, os quatro que o §6.2 nomeia. Um `kind` novo entra aqui por emenda, com a tool que o produz |
| Prova de confirmação por botão | `Confirmation`, com `botao`, `contact_id` e `turn_id` | — | §6.1 passo 4. O `botao` é o `confirm:{cart_id}` (Vendedor) ou `confirm:{hold_id}` (Serviços) do §6.3, **emitido pelo runtime** e respondido pelo mesmo `contact_id` no turno actual. Uma confirmação de outro contacto ou de outro turno não é uma confirmação |
| Especificação de uma tool | `EspecificacaoDeTool`, com o nome da tool, o `klass`, a versão, o `backend`, o modelo de argumentos e o `credor` | — | O `kamba/tls/specs/` dos *Detalhes Técnicos* do bloco. O `modelo` é o Pydantic com `extra="forbid"`; o `credor` é o ticket que **liga** a tool e só existe enquanto ela não está ligada |
| Entrada de catálogo sem executor | `declarada`, com `credor` obrigatório | — | O estado de dez das onze tools depois deste ticket: têm nome, `klass` e o ticket que as liga (KAM-031 ou KAM-035), e **não** têm modelo nem executor. Uma entrada sem executor e sem `credor` é recusada — a mesma disciplina do `modo: aviso` do `registry/gates.yaml` (§3.26): um atalho sem o ticket que o fecha não é atalho. Uma entrada `declarada` **não é visível ao modelo**: o `for_context` não a liga e o `invoke` recusa-a com `TOOL_NOT_ALLOWED` |
| Entrada de catálogo com executor | `ligada` | — | Tem modelo e executor. Depois deste ticket é **uma**: o `get_store_info` |
| Backend de uma tool | `backend` ∈ {`com`, `pay`, `idx`, `plataforma`} | — | Lista **fechada**. Os três primeiros são os componentes do `../docs/tecnica/00` §4; o `plataforma` é a nossa própria base, e é o do `get_store_info`. É a unidade do *circuit breaker*: o §6.5 diz «*circuit breaker* por backend» |
| Registo de todas as invocações | `platform.tool_audit` | — | DDL do §6.4. *Append-only* pelo padrão da `audit_log` (§3.2, KAM-012): `REVOKE UPDATE, DELETE, TRUNCATE` **mais** *trigger* `ENABLE ALWAYS`. **Distinta** da `audit_log`: esta cobre **todas** as invocações, aquela cobre dinheiro, stock e preço — e `money` escreve nas duas |
| Colunas de `tool_audit` | `id`, `ts`, `tenant_id`, `contact_id`, `conversation_id`, `turn_id`, `run_id`, `vertical`, `graph_version`, `tool`, `tool_version`, `klass`, `args_hash`, `args_redacted`, `idempotency_key`, `status`, `error_code`, `result_hash`, `fact_ids`, `latency_ms` | — | **Vinte**, as do §6.4 e mais nenhuma. Nenhuma guarda texto de mensagem nem telefone — é o critério 5 do bloco e o `../docs/tecnica/08` §6 |
| Impressão dos argumentos | `args_hash` | — | `sha256` da forma canónica dos `args`, 32 octetos, `NOT NULL`. É o que permite dizer «foi a mesma chamada» sem guardar a chamada |
| Argumentos redigidos | `args_redacted` | — | `jsonb`. **Só a forma**: por cada argumento, o nome e o tipo, nunca o valor. Um `query` de pesquisa é texto do cliente, e texto do cliente não entra num registo de auditoria |
| Impressão do resultado | `result_hash` | — | `sha256` da forma canónica do `data`, ou `NULL` quando a invocação falhou |
| Identificadores dos *facts* devolvidos | `fact_ids` | — | `text[]`. Os `fact_id` do `ToolResult.facts`, não os valores: é o que liga uma citação do KAM-032 à linha que a produziu |
| Estado de uma invocação, no registo | `status` ∈ {`ok`, `erro`} | — | Lista **fechada**. Quando é `erro`, o `error_code` leva um dos **onze** (os dez do §6.5 e o do §6.3); quando é `ok`, o `error_code` é `NULL`, e há um `CHECK` que o impõe nos dois sentidos |
| Erros tipados da camada | `tool_audit.error_code` ∈ {`NOT_FOUND`, `OUT_OF_STOCK`, `PRICE_CHANGED`, `LIMIT_EXCEEDED`, `ENTITLEMENT_DENIED`, `TOOL_NOT_ALLOWED`, `TENANT_MISMATCH`, `UPSTREAM_TIMEOUT`, `UPSTREAM_DOWN`, `VALIDATION_ERROR`, `INTENT_REUSED_WITH_DIFFERENT_CONTENT`} | — | Lista **fechada**, os dez do §6.5 **mais o do §6.3** (`INTENT_REUSED_WITH_DIFFERENT_CONTENT`, emenda 1.37), com o tratamento no grafo que eles definem. **Escritos como valores de `tool_audit.error_code`, qualificados pela tabela:** o *gate* 3b qualifica um valor pela coluna a que pertence (`tool_audit.error_code=NOT_FOUND`), e uma lista sem a coluna deixava os dez `CHECK` da revisao `0021` fora do dicionario — medido, dez achados de nivel 1. **Sem a tabela tambem nao serve**: o `error_code` ja e coluna de `outbound_messages` (§3.14), e um dominio sobre o nome nu aplicava-se a ela e declarava-a ilegivel — tambem medido. A forma qualificada e a do `channel_coexistence.meta_error_code` do §3.22. `ENTITLEMENT_DENIED` e `LIMIT_EXCEEDED` são os que o `hook_de_tool` do KAM-009 já devolve (`libs/py-core/src/kamba_core/ten/hook.py`), e não se redeclaram: importam-se de lá |
| *Timeout* por classe | `KAMBA_TLS_TIMEOUT_READ_MS` (2000), `KAMBA_TLS_TIMEOUT_ESCRITA_MS` (8000) | — | Os dois números do §6.5 («read 2 s, write/money 8 s»). A forma `KAMBA_*` é a do §3.9. Um *timeout* dá `UPSTREAM_TIMEOUT` |
| Tomadas da camada | `KAMBA_TLS_LIGACOES` (4) | — | Quantas ligações a camada abre. **Não é uma**: com uma só, dez invocações de dez *tenants* corriam em série (medido: 2,02 s com um backend de 200 ms) — bloqueio de cabeça de fila a atravessar *tenants*, que é o defeito mais caro do KAM-025. A fila é o *pool* e é o tecto; quem não tem vaga espera por uma vaga, e não pelo turno de outro *tenant* |
| Folga do tecto que a camada impõe | `MARGEM_DO_TECTO_MS` (500) | — | O tecto do §6.5 é do **backend**, e onde há um tecto preciso do lado do servidor (o `statement_timeout` do `get_store_info`) é esse que tem de morder. A espera da camada é a rede por baixo, para um executor que ignore o tecto que recebeu — sem ela, um executor de 5 s contra um tecto de 2 s devolvia `ok=True` em 5 s |
| Argumentos que o esquema não declara, no registo | `<nao_declarados>`, com a contagem | — | As chaves de `args` vêm do modelo, e um **nome** é texto tanto como um valor: `{"contacto 999123456789": …}` punha um telefone na `tool_audit` pela coluna que o critério 5 fecha para os valores. Só passam os nomes que o esquema declara; o resto conta-se. A contagem é informação útil e não é um canal |
| *Circuit breaker* | `KAMBA_TLS_DISJUNTOR_FALHAS` (5), `KAMBA_TLS_DISJUNTOR_PAUSA_MS` (30000) | — | Falhas **consecutivas** por backend até abrir, e quanto fica aberto. Aberto devolve `UPSTREAM_DOWN` **sem chamar o backend** (critério 7). `disjuntor` é o nome português da peça; `backend` é a sua unidade |
| Invocações de tool | `agr_tool_invocacoes_total` | — | Etiqueta `tool`, lista fechada (as onze do §3.26). **Nunca `tenant_id`** (`../docs/seguranca/ameacas_stride.md`, `OBS-I`): a gramática de etiqueta do `metricas.py` recusa-o pela forma |
| Erros de tool | `agr_tool_erros_total` | — | Etiqueta `codigo`, os **onze** erros em minúsculas (`tool_not_allowed`, …) — a gramática de etiqueta exige minúsculas, e o código canónico é maiúsculo. Os valores são **derivados** de `CODIGOS` e não escritos à mão, pela lição que o KAM-027 pagou no `test_gate11` |
| Latência da última invocação | `agr_tool_latency_ms` | — | Medida, em milissegundos. É o «métricas de latência e erro por tool» do DoD |
| Aberturas do disjuntor | `agr_tls_disjuntor_aberto_total` | — | Etiqueta `backend`, lista fechada |
| Alerta de isolamento | `agr_tool_tenant_mismatch_total` | — | **Sem etiqueta.** É o «gera alerta de segurança» do critério 8. Um `TENANT_MISMATCH` nunca se repete (§6.5: «**nunca** tentar de novo») |
| Código de saída sem auditoria | `6` | — | Próprio, pela razão escrita no §3.25 e no §3.26: o `2` é configuração inválida, o `3` a guarda do ADR-002, o `4` a falta de *checkpointer*, o `5` registo inválido. Um AGR que arrancasse sem poder escrever `tool_audit` corria tools `money` sem registo, que é o oposto do ADR-015 |
| *Lint* dos esquemas expostos ao modelo | `tool_schema`, no `lint_arch` | — | O «falha o build» do critério 3 e do `../docs/tecnica/08` §3.2. Corre no *gate* 2 (e no 11, que já corre o `lint_arch`) e **não** abre *gate* novo. Verifica os quatro `PARAMETROS_PROIBIDOS` do §3.26 por análise da fonte, sem importar nada — o `lint_arch` só depende da biblioteca padrão, por desenho |

**O ponto de extensão da idempotência era deste ticket e está preenchido pelo
KAM-029.** O passo 5 do §6.1 é a chave de idempotência, e o §6.3 dá a fórmula e
a tabela `tool_idempotency`. O que o KAM-028 entregou é a coluna
`idempotency_key` em `tool_audit`, o parâmetro no caminho, e a regra que o DoD
pede por extenso — uma tool `write` ou `money` **nunca corre sem chave**. O
resto está no **§3.28** (emenda 1.37).

**E uma coisa que este ticket afirmou saiu errada, com a razão escrita no
§3.28:** a `idempotency_key` da `tool_audit` **não** é a chave do §6.3. É a do
chamador — a do turno —, e a do §6.3 é a do carrinho, que vive em
`tool_idempotency.key`. As duas não podiam ser a mesma, e o §3.28 diz porquê.

**Quatro nomes desta secção entraram pela revisão adversarial**, e os quatro
saíram de uma medição e não de uma leitura: o `KAMBA_TLS_LIGACOES` (a camada
tinha **uma** tomada e serializava todos os *tenants*), o `MARGEM_DO_TECTO_MS`
(o tecto do §6.5 não era imposto por ninguém — um executor de 5 s contra 2 s
devolvia `ok`), o `<nao_declarados>` (os **nomes** dos argumentos iam em claro
para a `tool_audit`) e o `sku` do `Fact` (o KAM-032 declara-o e sem ele teria de
o inventar). A análise está em `../docs/analises/ANALISE-30-KAM-028-toollayer.md`.

---

---

### 3.28 Idempotência de tools por `cart_id` (KAM-029)

*Emenda 1.37, **proposta**.* A emenda 1.36 registou a ToolLayer e deixou escrito
que «`tool_idempotency` não entra no dicionário neste ticket», porque a tabela
era do KAM-029. É este. Entram a tabela e as suas colunas, o erro tipado novo, e
os dois nomes da espera.

A fonte é `../docs/tecnica/02_Agent_Runtime_Verticais.md` §6.3 (a chave e a
tabela) e `../docs/tecnica/03_Core_Comercio_Medusa.md` §6.3 (o protocolo, o
tecto de espera de 3 s e o nome do erro), com os ADR-009, ADR-010 e ADR-013.

**Há duas chaves de idempotência no caminho de uma invocação, e não são a mesma.**
É a decisão que dá forma a esta secção, e a emenda 1.36 afirmou o contrário sem o
ter medido — o inventário dizia que a `tool_audit.idempotency_key` guardava «a
chave do §6.3».

A `idempotency_key` — o parâmetro do `invoke` e a coluna de `tool_audit` — é **do
chamador**, o grafo, e responde a «este *turno* já foi contado?»: vai ao
`hook_de_tool` do passo 2, que escreve o `usage_ledger`, e o KAM-025 usa
`turn_id:seq`. A `tool_idempotency.key` é **derivada na TLS** e responde a «este
*carrinho* já foi comprado?».

A chave do chamador **não pode** servir para o carrinho, e a razão é o critério 8
deste ticket: um segundo toque com `wamid` novo é um **turno novo**, com `turn_id`
novo e portanto chave de turno nova. Se o carrinho se desduplicasse pela chave do
turno, esse toque não encontrava nada guardado e cobrava outra vez — a encomenda a
dobrar que o ticket existe para fechar. A chave do carrinho não tem turno dentro,
de propósito, e é isso que o teste de propriedade do critério 6 mede. As duas
linhas ligam-se pelo `tool` e pelo turno em que correram.

**E o `args_hash` das duas tabelas não é o mesmo valor**, o que a primeira versão
desta emenda afirmou e a revisão adversarial desmentiu (`../docs/analises/ANALISE-31-KAM-029-idempotencia.md`,
achado 4). O da `tool_idempotency` é do **modelo validado**
(`inv.args.model_dump()`) e o da `tool_audit` é dos argumentos **crus**, como o
modelo de linguagem os emitiu. A razão é que respondem a perguntas diferentes: a
auditoria registra o que **chegou**, que é o que um registo deve guardar, e esta
compara o que **vale** — e tem de o fazer sobre o modelo validado, senão um
segundo toque que reemitisse um campo de omissão (`{"cart_id": "c-1"}` contra
`{"cart_id": "c-1", "nota": ""}`) dava `args_hash` diferente e o *replay* virava
`INTENT_REUSED_WITH_DIFFERENT_CONTENT`.

**O `|` da fórmula do §6.3 não é um caractere separador.** O `cart_id` é opaco —
é gerado pelo `propose_cart` (KAM-046) — pelo que nenhum caractere é seguro como
separador: com um separador literal, `(a, b|c)` e `(a|b, c)` dão a mesma chave, e
numa tool `money` isso é a encomenda de um cliente a responder pela de outro.
Escreve-se com o **comprimento a prefixar** cada parte, que é inequívoco sem supor
nada sobre o conteúdo.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Barreira de idempotência das tools de escrita | `platform.tool_idempotency` | — | DDL na revisão `0022`. **Não** é *append-only*, ao contrário da `tool_audit`: o protocolo tem de alterar a linha. O que a protege é o `UPDATE` concedido **por coluna** |
| Colunas de `tool_idempotency` | `key`, `tenant_id`, `tool`, `args_hash`, `estado`, `result`, `created_at` | — | Sete. Sem `contact_id`: ele entra na **derivação** da `key` e guardá-lo ao lado era guardar uma referência a um contacto numa tabela que não precisa de a ler |
| Chave de idempotência de um carrinho | `key` = `sha256(tenant_id` ⟂ `contact_id` ⟂ `tool` ⟂ `cart_id)`, em hexadecimal | `hash(msisdn + sku + janela_5min)` | As quatro partes do §6.3, com o comprimento a prefixar (⟂ denota essa concatenação, não um caractere). `CHECK (key ~ '^[0-9a-f]{64}$')`: um telefone **não cabe** nesta coluna, por recusa da base e não por confiança no chamador (ADR-010, critério 6) |
| Identificador opaco do carrinho | `cart_id` | — | Produzido por `propose_cart` (KAM-046) e **opaco**: não se interpreta nem se deriva de nada. Em Serviços o lugar dele é o `hold_id` (§6.2). O botão é `confirm:{cart_id}`; que ele caiba nos 256 caracteres do `id` de um *reply button* é **NÃO VERIFICADO** — ver o §4 |
| Estado de uma reserva | `tool_idempotency.estado` ∈ {`em_curso`, `concluida`, `falhada`} | — | Lista **fechada**. `em_curso` → quem chega espera; `concluida` → devolve-se o `result` guardado; `falhada` → **retoma-se** e executa-se outra vez, que é o critério 4. A lista fechada do código (`ESTADOS`) e a do `CHECK` são confrontadas por um teste. **Qualificado pela tabela**, e não `estado` nu: o `estado` é já coluna de `hmac_key_versions`, `events_dlq` e `evt_acoes`, com domínios diferentes, e um domínio sobre o nome nu declarava as três ilegíveis — medido, quatro achados de nível 1 mais uma extensão do `canon/` a ficar sem uso. É a lição que a emenda 1.36 escreveu para o `error_code`, repetida |
| Resultado guardado de uma invocação | `result` | — | `jsonb`, o `data` do `ToolResult`. Há `CHECK` **nos dois sentidos**: uma `concluida` sem `result` devolvia um *replay* vazio, e um `result` numa `falhada` era um resultado devolvido como *replay* de uma invocação que ninguém confirmou |
| Marca de repetição, na resposta | `idempotent_replay` | — | Campo do `ToolResult` (§3.27). Nasce `False`; é este ticket que o põe a `True`, quando a chave encontra um resultado guardado |
| Reutilização de uma intenção com outro conteúdo | `INTENT_REUSED_WITH_DIFFERENT_CONTENT` | — | O **décimo primeiro** erro tipado, e o mesmo nome que o COM usa no §6.3 do `../docs/tecnica/03` — são as duas barreiras independentes da mesma intenção. É defeito do chamador e **não se repete**; não é violação e não levanta alerta de segurança |
| Retoma de uma reserva abandonada | `MINUTOS_PARA_RETOMAR` (2) | — | Uma reserva `em_curso` mais velha do que isto considera-se **abandonada** e retoma-se, por `UPDATE` condicional (atómico). É o ponto 4 do `../docs/tecnica/03` §6.3, que escreve o mesmo para o COM. **Dois minutos e não os 8,5 s do tecto da classe:** o tecto diz quanto o dono *pode* demorar, e retomar por cima de um dono vivo é o que duplica o efeito. Sem isto, uma reserva cujo `fechar` não passasse envenenava aquele `cart_id` para sempre, com a encomenda já feita |
| Tecto de espera por uma reserva de outro | `TECTO_DE_ESPERA_MS` (3000) | — | O «poll ≤ 3 s» do `../docs/tecnica/03` §6.3. Esgotado, devolve `UPSTREAM_TIMEOUT` **sem executar**. Não é variável de ambiente, ao contrário dos tectos por classe do §3.27: vem do desenho e não da afinação de um ambiente |
| Retenção de uma reserva | `DIAS_DE_RETENCAO` (30) | — | ***Proposta***. O critério pede «≥ validade da reserva (72 h) + prazo de disputa», e o prazo de disputa **não está fixado em documento nenhum** — o `../docs/tecnica/04` tem `refund_cases` e a transição `paga → reembolso_pendente` e não dá prazo. Apaga só reservas **fechadas**; recalibra-se quando o `04` o fixar |

**Dois nomes do §3.27 ficaram errados e corrigem-se aqui, e os dois saíram de
escrever código contra eles.** O primeiro é a `idempotency_key` da `tool_audit`,
acima. O segundo é a contagem: «os dez erros tipados» passa a onze, e isso toca a
revisão `0022` (que altera o `CHECK` fechado da `0021`), a etiqueta da métrica
`agr_tool_erros_total` — **derivada** de `CODIGOS`, pela lição que o KAM-027 pagou
— e os testes que afirmavam «são dez». Um `CHECK` fechado é canon: um código novo
não é uma constante, são quatro sítios e uma revisão de base de dados.

**Esta tabela não tem chave estrangeira para `tenants`, e é deliberado.** É a
mesma escolha da `tool_audit`: uma FK punha o `DELETE` de um *tenant* a depender
de marcas de desduplicação, e o que liga a linha ao *tenant* é a RLS, que não
precisa de FK para valer.

### 3.29 Gateway de LLM (KAM-030)

*Emenda 1.38, **proposta**.* O `llm_call_log` estava pré-declarado no §3.6 desde
a redacção inicial, sem esquema e sem colunas. Sai de lá e entra aqui
**qualificado** — `dat.llm_call_log` —, com o esquema novo, as dezesseis colunas,
o domínio fechado do `resultado` e o contrato do cliente. É o mesmo percurso do
`owner_notices` na emenda 1.32 e do `token_ref` na 1.22, e pela mesma razão: o
*lint* recusa a redundância.

A fonte é `../docs/tecnica/02_Agent_Runtime_Verticais.md` §13 e §14 (o *gateway* e
a degradação), `../docs/tecnica/06_Dados_Eventos_Analytics.md` §14 (a tabela) e
`../docs/tecnica/evidencia/E4_Stack_Licencas.md` §2.7 e §3 (o incidente e as
tarifas), com os ADR-005, ADR-008, ADR-010 e ADR-018.

**Três afirmações de fonte mais alta não sobreviveram a serem medidas contra a
versão fixada da imagem**, e as três mudaram código. Estão em
`../docs/evidencia/KAM-030-litellm.md`, e são a espinha desta secção:

1. **O orçamento esgotado não devolve 400.** O critério 4 do bloco diz
   «`BUDGET_EXHAUSTED` (mapeado do 400)». A versão 1.104.2 responde **422** com
   `{"error": {"type": "budget_exceeded"}}`, e usa o 400 para outra coisa — um
   `/key/generate` com `key_alias` repetido. Um mapeamento pelo 400 **nunca
   disparava** no orçamento e disparava num erro de provisionamento: o critério
   ficava satisfeito por nada. O reconhecimento passa a ser pelo `error.type`.
2. **A configuração do `../docs/tecnica/02` §13.1, à letra, não cumpre o critério
   6.** Ela escreve duas entradas de `model_list` com o **mesmo** `model_name` e
   conta com o `num_retries: 1` para comutar. Medido, 20 corridas com o primeiro
   fornecedor sempre em falha: a estratégia por omissão é `simple-shuffle`
   (aleatória), **3 das 20 falharam por completo**, e num grupo aleatório não
   existe «fornecedor primário» nenhum — a `ordem` não teria efeito. Com dois
   grupos e um `fallbacks` nomeado, 20 de 20 passam e a sequência é sempre a
   mesma.
3. **O nome do subprocessador não é o prefixo do fornecedor no proxy.**
   `google/` é recusado (`BadRequestError`); o prefixo do Gemini é `gemini/`.
   Dos 162 prefixos que a versão reconhece, nenhum se chama `google`. Os dois
   espaços de nomes ficam **separados**, e não se harmonizam: o `fornecedor` é o
   nome do subprocessador do `../docs/tecnica/08` §8.3.2, que é o que o ADR-008 e
   o `tenant_destinations` (KAM-069) usam para autorizar uma transferência, e
   renomeá-lo para acompanhar uma biblioteca punha o registo da APD a falar a
   língua de um pacote.

**O que esta emenda não decide, e é o mais importante: nenhum modelo.** O §13.2 e
o `E4` §3.5 dizem-no por extenso — qualidade em português de Angola e latência
são **NÃO VERIFICADAS**, não há *benchmark* por variante, e a escolha faz-se com
o *golden* do KAM-040. Todas as linhas de `llm/aliases.yaml` têm
`modelo: por_decidir`, com o credor escrito ao lado, e há um teste que **falha**
no dia em que isso mudar — porque esse dia é um *release*.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Registo de chamadas a modelos | `dat.llm_call_log` | `llm_calls` | DDL na revisão `0023`. *Append-only* nas três camadas da `0006`, particionada por `RANGE (ts)` com **só** a `DEFAULT` criada (a decisão da emenda 1.9 para o `events_log`: as mensais têm data no nome e nascem de um *job*, que é o KAM-071). Retenção 13 meses por `DROP` de partição (`../docs/tecnica/06` §9.3) |
| Partição DEFAULT do registo de chamadas | `dat.llm_call_log_default` | — | A única que a revisão `0023` cria, pela decisão que a emenda 1.9 tomou para o `events_log_default`: as mensais têm data no nome e nascem de um *job* (KAM-071), e uma migração que as criasse fixava o calendário. Leva RLS e *trigger* **próprios** — para o *gate* 6 uma partição é uma tabela, e um `SELECT` dirigido a ela escapava à política do pai |
| Colunas de `dat.llm_call_log` | `id`, `ts`, `tenant_id`, `trace_id`, `vertical`, `no_grafo`, `papel`, `graph_version`, `modelo`, `fornecedor`, `tokens_in`, `tokens_out`, `tokens_cache`, `custo_usd`, `latencia_ms`, `resultado` | — | **Dezesseis**, contra as catorze do `../docs/tecnica/06` §14: entram o `papel` e o `graph_version`. É desvio **aditivo** com razão escrita, como o `tenant_id` que a emenda 1.10 deu ao `events_consumed` — sem `papel`, o «custo por tenant, por vertical e por **papel**» do DoD não é calculável de lado nenhum, e o §13.4 lista as quatro etiquetas de *metering* por extenso |
| Colunas que o chamador escreve | `COLUNAS` (catorze) | — | As dezesseis menos o `id` e o `ts`: o instante de um registo não é do chamador e o `id` é de identidade. É a mesma decisão da `tool_audit` (§3.27), e o `GRANT INSERT` da `0023` é **por coluna** — um `has_table_privilege` não a verificava |
| Desfecho de uma chamada | `llm_call_log.resultado` ∈ {`ok`, `ok_fallback`, `budget_exhausted`, `timeout`, `erro_fornecedor`, `destino_negado`} | — | Lista **fechada**, com `CHECK`: um valor novo é uma revisão de base de dados e não uma constante, pela lição que a `0022` pagou. **Qualificado pela tabela** e não `resultado` nu: o `resultado` é já coluna de `evt_acoes` com outro domínio, e um domínio sobre o nome nu declarava-a ilegível — quatro achados de nível 1, que é o que a emenda 1.37 pagou com o `estado` |
| Custo de uma chamada | `custo_usd` | — | `numeric(12, 6)`, do §14. **Não** é unidade menor inteira, e a razão está na revisão: o turno do §13.3 custa 0,00045 USD — quatro centésimos e meio de **cêntimo** —, que em unidade menor arredonda a zero, e uma tabela de custo que arredonda cada linha a zero não mede nada. O que a convenção proíbe é vírgula flutuante, e `numeric` é decimal exacto; a moeda fica explícita no nome |
| Custo desconhecido | `custo_usd` nulo | `custo_usd` = 0 | Um modelo sem linha em `llm/precos.yaml` dá **nulo**, nunca zero: zero afirmava que a chamada foi gratuita e punha o somatório por *tenant* a mentir por omissão. Hoje é o caso de **todas** as chamadas, porque o modelo é `por_decidir`, e a métrica `agr_llm_sem_preco_total` torna isso visível |
| Artefacto comportamental dos aliases | `llm/aliases.yaml` | — | Tem `versao` em SemVer e o conteúdo fixado por *hash* em `ci/llm-aliases.lock`. O *hash* **exclui os comentários**, e é isso que faz «mudou o conteúdo e não a versão» ser detectável — o cabeçalho gerado nomeia a `versao`, pelo que hashear o texto inteiro desfazia a propriedade. Passo `aliases` do `lint_arch`, *gate* 2 |
| Configuração do proxy | `llm/litellm.config.yaml` | — | **Gerada** de `llm/aliases.yaml` por `python -m llm_config`, e versionada — o mesmo desenho do `canon/dicionario.yaml`, que é gerado de `specs/02` e também entra no repositório. Duas fontes à mão punham o produto a servir um modelo que o artefacto versionado não nomeia, que é a falha que o critério 7 fecha |
| Tarifário de tokens | `llm/precos.yaml` | — | *proposta* nos valores do Google (INDÍCIO, `E4` §3.3) e CONFIRMADO nos da Anthropic e do OpenAI. **É nosso e não o do LiteLLM**: o dele descarrega-se de `raw.githubusercontent.com` no arranque — medido —, e um custo registado que dependesse de um ficheiro de terceiros a mudar sem aviso não é um registo. A linha do `gemini-3.8-flash` leva `valido_ate: 2026-12-31` e o cálculo **levanta** depois disso, porque o preço duplica |
| Papel de um alias | `llm_call_log.papel` ∈ {`router`, `chat`, `vision`, `embed`} | — | Lista fechada, no `CHECK` da revisão `0023` e em `PAPEIS` (serviço e `tools/llm_config`, com teste de paridade). **Fechada e não gramática**, ao contrário do `tool` da `0021`: o argumento de lá — «uma lista de permitidos obrigava a uma revisão por cada *tool* nova» — não se aplica, porque as *tools* crescem com o KAM-031 e o KAM-035 e os papéis **não crescem** (o §13.2 fixa quatro). Com gramática, o dicionário dizia quatro e o DDL aceitava qualquer identificador: duas verdades sobre a mesma coluna. O grafo pede o **papel**; qual modelo está atrás disso é o `llm/aliases.yaml`. `vision` e `embed` ficam `declarada`, com credor KAM-033 e KAM-063: correm no COM e no IDX (§13.2) e nenhum nó do AGR os chama |
| Nome de um alias | `kamba-router`, `kamba-chat`, `kamba-vision`, `kamba-embed` | — | Os quatro do §13.1. `timeout` de **8 s** no `router` e **20 s** nos outros três |
| Estado de um alias | `aliases[].estado` ∈ {`ligada`, `declarada`} | — | O vocabulário do §3.26 (KAM-027), reutilizado. `declarada` exige `credor` com a forma `KAM-NNN`: um atalho sem o ticket que o fecha não é atalho. Hoje os quatro são `declarada`, credor KAM-040 |
| Ordem de tentativa de um fornecedor | `fornecedores[].ordem` | — | **Não é um ranking de qualidade**: é a ordem de tentativa. A `ordem: 1` fica com o nome do alias e as seguintes com `<alias>-fallback<ordem>` — grupos **distintos** no proxy, ligados por um `fallbacks` nomeado, porque um grupo único é aleatório (ver o ponto 2, acima) |
| Fornecedor aprovado | `fornecedor` ∈ {`anthropic`, `openai`, `google`} | — | Três dos onze subprocessadores do `../docs/tecnica/08` §8.3.2; os outros oito não servem modelos de linguagem, e o Groq é STT (KAM-036). Um nome fora desta lista é recusado pelo *lint* **e** pelo arranque do AGR: é um destino de transferência que ninguém registou |
| Prefixo do fornecedor no proxy | `PREFIXO_LITELLM` (`google` → `gemini`) | — | Espaço de nomes **separado** do nome do subprocessador. Ver o ponto 3, acima. Um fornecedor aprovado sem entrada aqui faz o gerador **levantar**, em vez de escrever uma configuração que o proxy recusa no arranque |
| Contrato do cliente | `ClienteDeLlm` com `chamar(papel, mensagens, ctx)`, `ContextoDeChamada` (cinco campos), `Resposta` | — | `kamba_agr/llm/cliente.py`. Expõe **papéis**, nunca modelos, e fala HTTP com o proxy no esquema OpenAI-compatível: **nenhum SDK de fornecedor entra no AGR**, e o pacote `litellm` também não — o `httpx` já estava no fecho desde o KAM-026, pelo que o *gateway* não acrescenta dependência nenhuma |
| Contexto de uma chamada | `ContextoDeChamada(tenant_id, trace_id, vertical, no_grafo, graph_version)` | — | **Não é o `ToolContext`**, que tem oito campos: aqui não entram `contact_id` nem `conversation_id`, porque nenhum entra na tabela. Um contexto mais largo do que a tabela era um convite a guardar o que não se deve |
| Erros tipados do *gateway* | `OrcamentoEsgotado`, `TempoEsgotado`, `FornecedorFalhou`, `DestinoNegado` | — | Quatro, e **não** são os onze do §6.5 (§3.27, §3.28): aqueles são o contrato entre o grafo e uma *tool*, estes entre o grafo e o **modelo**. Juntá-los punha um `BUDGET_EXHAUSTED` no `CHECK` fechado da `tool_audit.error_code` para descrever o que nenhuma *tool* faz |
| *Gate* de transferência | `PortaDeDestinos.autorizar(tenant_id, fornecedor, finalidade)` | — | **O `assertDestinationAllowed` do bloco do KAM-069 não é uma variante e não entra na coluna «Substitui»**: é o mesmo conceito escrito em inglês no texto de outro ticket, e declará-lo como variante tornava ilegal o vocabulário do bloco que o vai implementar — além de acrescentar uma variante ao canon que o `dict_export` conta. Esta é a porta que o **KAM-069** vai implementar sobre `tenant_destinations`, com os nomes em português. Até lá a implementação é `NegaTudoAteKam069`, que nega **tudo** em `prod` — mais restritivo do que o KAM-069 será. Um ambiente desconhecido é tratado como `prod` |
| Momento do *gate* | antes da chamada, para **todos** os fornecedores do alias | — | O *fallback* é do router e o cliente não escolhe quem serve. Autorizar só o de `ordem: 1` deixava o segundo receber os dados **sem** o *gate* ter sido consultado por ele. Falha fechada sobre a **união**, não sobre a escolha |
| Métricas do *gateway* | `agr_llm_chamadas_total{papel}`, `agr_llm_erros_total{resultado}`, `agr_llm_latency_ms`, `agr_llm_destino_negado_total`, `agr_llm_sem_preco_total`, `agr_llm_registo_falhou_total`, `agr_llm_servidor_desconhecido_total` | — | **Sete**, e o `tenant_id` não é etiqueta de nenhuma. Resolve a tensão do bloco: o §13.4 manda *metering* por `tenant_id`, `vertical`, `papel`, `graph_version`, e a convenção proíbe `tenant_id` em etiqueta (`OBS-I`). São dois sítios — as quatro etiquetas vão para as **colunas** de `dat.llm_call_log`, de onde o custo por *tenant* se lê; a métrica leva só o `papel`. O custo por *tenant* é uma consulta, não uma série temporal, e tinha de ser |
| Chave virtual de um *tenant* | `key_alias` = `tenant-<uuid>`, segredo `litellm_virtual_key/<tenant_id>` | — | Criada por `infra/llm/chaves.py`, **idempotente por código nosso**: medido, um segundo `/key/generate` com o mesmo alias devolve 400 «already exists». A idempotência é procurar em `/key/list` e depois `/key/update` ou `/key/generate`. O `/key/update` **não reemite** a chave, pelo que o valor no cofre continua válido |
| Orçamento de uma chave | 15% × mensalidade em USD, `budget_duration: 30d` | — | ***Proposta***, e a mensalidade por plano **não está fixada** em documento nenhum (`../docs/tecnica/10`): vem de `KAMBA_LLM_MENSALIDADE_USD_<PLANO>` e sem ela o *script* **recusa-se a correr**, em vez de inventar um tecto de custo. Calibra-se em H6 |
| Limiar do alerta de orçamento | `LIMIAR_DE_ALERTA` (0,80) | — | O «alertas a 80%» do §13.3. Lê-se o `spend` e o `max_budget` de `/key/list`, que é quem **impõe** o orçamento; somar a nossa `dat.llm_call_log` dava outro número, e hoje daria zero (custo nulo). Uma chave com `max_budget` 0 não entra: sem tecto não há fracção |
| Imagem do proxy | `ghcr.io/berriai/litellm:v1.104.2@sha256:3d88bd…a500` | — | Etiqueta **e** digest ao mesmo tempo: o digest fixa o conteúdo e a etiqueta prova a versão, que é o que o `forbidden_below: 1.83.0` de `tools/blocklist.yaml` avalia. Nunca abaixo de 1.83.0 e fora de {1.82.7, 1.82.8}, as duas com malware (`E4` §2.7) |
| Material de verificação de uma assinatura | `cosign_chave_publica` | — | Campo novo do `ci/supply-chain/imagens.yaml`, **alternativa** a `cosign_identidade`/`cosign_emissor` e não um extra. O LiteLLM assina **com uma chave** (ECDSA P-256) e a assinatura não tem certificado: não existe identidade OIDC para escrever. Uma entrada com as duas formas é recusada — não se saberia qual foi verificada |
| Código de saída sem *gateway* | **7** | — | O sétimo: `2` configuração, `3` guarda do ADR-002, `4` sem checkpointer, `5` registo inválido, `6` sem auditoria de tools, `7` sem *gateway* de LLM. Cobre os dois ficheiros de `llm/` e o `INSERT` nas catorze colunas. Uma chamada que corresse sem poder escrever a linha descobria-o **depois** de os dados saírem de Angola |
| Quinta ligação do AGR | `kamba-agr:llm` | — | Papel `kamba_app`, transaccional. A quinta e não a das tools, pela razão que o `ligacao.py` já dá para a das tools não ser a da leitura: o `tenant_guard` recusa uma segunda transacção na mesma ligação, e uma chamada ao modelo acontece **dentro** de um nó que pode ter uma invocação de tool a meio |
| Pasta dos ficheiros de LLM | `KAMBA_LLM_DIR` | — | Como o `KAMBA_REGISTRY_DIR` do §3.26: o serviço não sabe onde a árvore está |
| Endereço do proxy | `KAMBA_LLM_PROXY_URL` | — | Na rede interna. **Nunca um FQDN de fornecedor**: o `services/agr/egress.yaml` tem `destinos: []` e os FQDN pertencem a `infra/egress/litellm.yaml`, que é a única lista de saídas da pilha com fornecedores de LLM |

**O que esta emenda deixa por decidir, e a quem.** O modelo de cada alias e o
*ranking* (KAM-040, e com ele o Gate 13, que **não existe**); a tabela
`tenant_destinations` e o `apd_ref` que autoriza uma transferência (KAM-069, e
sem eles `prod` fica fechado); o modo determinístico a que o
`OrcamentoEsgotado` devia degradar (KAM-037, e por isso hoje o turno falha e o
*job* volta à fila); **o domínio das finalidades de transferência** — as três
(`conversa`, `embeddings`, `visao`) vivem em `FINALIDADES`, em
`kamba_agr/llm/destinos.py`, e **não** entram no §3: a coluna é o
`tenant_destinations.purpose` do KAM-069 e quem declara o domínio de uma coluna é
a revisão que a cria. Escritas aqui como domínio, o *gate* 3b ligava-as ao
`finalidade` de `platform.contact_endpoints` — três achados de nível 1 na
primeira forma e três extensões do `canon/` a ficar **sem uso** na segunda, que é
o efeito colateral que a emenda 1.37 descreve. Medido: o `canon_lint` está
conforme no `HEAD` e os três achados eram desta emenda; a minimização de PII
antes do modelo (KAM-112, que este ticket desbloqueia); a mensalidade por plano (`../docs/tecnica/10`, H6); o
agendador do alerta de orçamento e das partições mensais (KAM-071); e **se os
fornecedores reportam o cache dentro ou ao lado da entrada**, que está NÃO
VERIFICADO e cuja subtracção é defensiva até alguém medir com uma chave real.

### 3.30 Validador de citação e *renderer* por referência (KAM-032)

*Emenda 1.39, **proposta**.* O `../docs/tecnica/02_Agent_Runtime_Verticais.md` §9
desenha o validador em duas camadas e nomeia sete veredictos, quatro métricas e
os blocos do *renderer*; nenhum deles estava neste documento. Entram aqui porque
são contrato entre o `compose`, o `validate` e o `render` do grafo (KAM-031,
KAM-035) e o consumo do KAM-123 — e porque o §1 declara defeito um nome em código
que não esteja aqui.

A fonte é o §9 (o desenho e as limitações do §9.2), o §8.2 (a extensão a datas,
horas e durações), o `../docs/tecnica/03_Core_Comercio_Medusa.md` §7.1 (o preço
opaco e o `OfferView.precoDisplay`), o
`../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` §6.3 (o contrato de saída da
tool), o ADR-007 e a **proposta 02-A** do §20 do `02`.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Veredicto do validador | `Verdict.errors` ∈ {`money_unbacked`, `sku_price_mismatch`, `name_sku_mismatch`, `qty_unbacked`, `datetime_unbacked`, `discount_unbacked`, `number_unbacked`} | — | ../docs/tecnica/02 §9.1. Lista fechada de sete |
| Bloco do *renderer* | `blocks[].type` ∈ {`text`, `item`, `total`, `buttons`, `datetime`} | — | ../docs/tecnica/02 §9.1; o quinto vem do §8.2, que estende o validador a datas, horas e duracoes |
| Literais permitidos fora de *facts* | `Policy.allowed_literals` | — | ../docs/tecnica/02 §9.1, «lista curta permitida» |
| Campos de um bloco de item | `item.sku` + `item.show` ⊆ {`name`, `price`, `stock`} | — | ../docs/tecnica/02 §9.1, do exemplo de blocos |
| Valor monetário normalizado | `value_minor` | `value_kz` | §2 (unidade menor inteira) e ../docs/tecnica/02 §9.1, corrigido pelo KAM-139: inteiro, em cêntimos de AOA |

**Lista fechada de sete, e o número é canon.** É a mesma escolha dos onze erros
tipados da `tool_audit` (§3.28): o grafo decide **pelo veredicto** — `retry` até
ao tecto, depois `handoff` (§8.4, linha «Citação de números e `sku`») —, e um
veredicto que ele não conheça cai no caminho de omissão, que num validador
*fail-closed* é o caminho errado. Os sete são valores de `Verdict.errors` e
**qualificados pela estrutura**, pela razão que a emenda 1.37 pagou com o
`error_code` e a 1.38 com o `resultado`: `total` é já um `type` de bloco neste
mesmo §3.30 e `price` é já um `kind` de `Fact` no §3.28, e um domínio sobre o
nome nu colidia com os dois.

#### O `value_minor` é em cêntimos, e `value_kz` não entra

O critério 1 do bloco do KAM-032 escreve «devolve `value_kz` inteiro», e **não é
o nome nem a unidade**. São duas fontes mais altas a dizer o contrário, e as duas
já estavam escritas antes deste ticket:

* o §2 deste documento manda dinheiro em **unidade menor inteira** (`*_minor`) e
  a emenda 1.13 registou `valor_kz` como variante que ele substitui;
* o §9.1 do `02` foi **corrigido pelo KAM-139** depois de a revisão adversarial
  medir o achado C1: o *fact* vem do `search_catalog` do `05` §6.3, cujo contrato
  de saída é `preco_minor` **em cêntimos**, e comparar a fala do cliente em Kz com
  um *fact* em cêntimos falha **sempre**, por um factor de cem. «12.500 Kz» dá
  `value_minor = 1250000`.

A dívida **106** de `../docs/dividas-documentais.md` já tinha nomeado esta
divergência, com o credor. Fica decidida a favor da fonte mais alta (fonte 3
sobre fonte 6): o campo do `Fact` é o `value` que o KAM-028 entregou — serve os
quatro `kind`, e um `stock` não é Kz — e a normalização para cêntimos é deste
ticket.

#### Três `kind` que o validador precisa e que **não** nascem aqui

O bloco declara «dependência apenas da interface `Fact(kind, value_kz|datetime,
sku, fact_id, retrieved_at)`», e três dos sete veredictos pedem `kind` que o
catálogo do §6.2 não tem: `name` (para o `name_sku_mismatch`), `qty`
(`qty_unbacked`) e `discount` (`discount_unbacked`). O §9.1 nomeia ainda um
quarto, `expiry`, no `require_fact` das datas. O `KINDS` do KAM-028 está **fechado
nos quatro** do §6.2 (`price`, `stock`, `total`, `datetime`, emenda 1.36), e um
`Fact(kind="discount", …)` **levanta**.

É a dívida **105**, e o credor que ela nomeia mantém-se: «quem acrescenta o `kind`
é o ticket que produz o *fact*» — os três saem de tools que o **KAM-031** liga
(`search_catalog`, `get_price_stock`). Este ticket **não** os acrescenta, e o que
faz em vez disso está escrito e medido:

* a quantidade cai em `stock`, que existe — é o `kinds={"qty","stock"}` do §9.1
  menos o que não existe;
* a data cai em `datetime`, pela mesma conta sobre `expiry`;
* o desconto **não tem onde cair**, pelo que *qualquer* percentagem dá
  `discount_unbacked`. É *fail-closed* e é o que o ADR-007 manda («cada número
  citado existe no *output* real de uma tool»), mas tem um limite que se escreve:
  o lado positivo do critério — uma percentagem **com** *fact* a ser aceite — é
  **inverificável** hoje, e passa a verificável no dia em que o `discount` for um
  `kind`;
* o nome resolve-se a `sku` pelo `nome` do contrato de saída do `05` §6.3, que
  vive no `ToolResult.data` e **não** num `Fact` — e é por isso que o validador
  recebe a oferta ao lado dos *facts*, em vez de inventar um `kind`.

#### As métricas: o `vertical` entra, o `tenant_id` não

O critério 8 pede as quatro métricas «exportadas com `tenant_id` e `vertical`».
**O `tenant_id` não pode ser etiqueta de métrica**, e não é convenção: o `OBS-I`
de `../docs/seguranca/ameacas_stride.md` impõe-no, e a biblioteca da casa
impõe-no **pela gramática** — uma etiqueta tem de casar `^[a-z][a-z0-9_]{1,62}$`,
e um UUID canónico tem hífenes, não casa, e a chamada **levanta**
`EtiquetaInvalida`. Uma métrica escrita como o critério 8 pede não exporta valor
nenhum: rebenta no primeiro turno.

Não é a primeira vez, e os precedentes dizem todos o mesmo. A emenda **1.21**
(`meta_cost_usd_total`), a **1.25** (as quatro do *free tier*) e a **1.38** (o
§13.4 do `02`: «as quatro etiquetas vão para as colunas da tabela, e a métrica
leva só o `papel`») resolveram-no da mesma maneira. E a dívida **54** de
`../docs/dividas-documentais.md` é o caso idêntico a este, com o desfecho
escrito: o critério 4 e o DoD do KAM-015 pedem `meta_cost_usd_total{tenant}`, a
etiqueta **não é implementável**, e «as duas caixas ficam vazias».

Resolve-se igual: **a desagregação por *tenant* faz-se onde tem significado e não
na etiqueta.** Lá foram as colunas de `dat.llm_call_log` e o `pricing` por
consulta; aqui é o `turn_id` do registo do turno, de onde a amostragem do §9.2 lê.
A leitura fica escrita, a gramática **não se alarga**, e a caixa do critério 8
fica vazia: a decisão é de quem escreveu o critério.

A segunda metade do critério também não sobrevive à biblioteca como está: as
quatro são **taxas**, e a biblioteca da casa tem contadores e medidas e **não tem
histogramas** (ADR-018, observabilidade leve). Uma taxa guardada como medida perde
o denominador — e o `agr_llm_*` do KAM-030 já escolheu o outro caminho. Exportam-se
**cinco contadores**, cada um com o `vertical` por eixo, e as quatro taxas do §9.2
são razões entre eles:

* `validate_fail_rate` = `agr_validate_falhas_total` / `agr_validate_total` — **não** se soma o
  `handoff`, que é um subconjunto das falhas e não uma classe ao lado delas;
* `validate_retry_rate` = `agr_validate_repeticoes_total` / `agr_validate_total`;
* `handoff_by_citation` = `agr_validate_handoff_total` — é uma contagem, e o §9.2 não lhe chama taxa;
* `render_only_ratio` = `agr_render_only_total` / `agr_turns_total{outcome="executado"}` — o
  denominador é o **turno** e não a validação, que é o que o critério 6 pede por extenso
  («medido por turno»): um turno com duas repetições conta três validações.

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Validações de citação | `agr_validate_total{vertical}` | — | ../docs/tecnica/02 §9.2. É o denominador das taxas |
| Validações recusadas | `agr_validate_falhas_total{vertical}` | — | ../docs/tecnica/02 §9.2 |
| Recusas que geraram repetição | `agr_validate_repeticoes_total{vertical}` | — | ../docs/tecnica/02 §9.2 |
| Recusas que esgotaram o tecto | `agr_validate_handoff_total{vertical}` | — | ../docs/tecnica/02 §9.2 e §8.4, «retry -> handoff» |
| Respostas sem prosa numérica livre | `agr_render_only_total{vertical}` | — | ../docs/tecnica/02 §9.2. Medido por turno |
| Amostragem em produção | `citation_fail_rate` | — | ../docs/tecnica/02 §9.2. Não é métrica Prometheus: é a medição por amostragem, com dono KAM-040 e KAM-081 |

O `citation_fail_rate` **não** é métrica Prometheus e está aqui para não ser
confundido com uma: o §9.2 nomeia-o como a medição **por amostragem de produção**
que complementa o *gate* duro, e o seu dono é o KAM-040 (o *golden*) com o
KAM-081 (as vistas). A razão de ele existir está no próprio §9.2 e repete-se
porque é o limite deste ticket: «0 preços/totais divergentes das tools em
produção» é **objectivo de desenho com risco residual**, e a regra dos três diz
quanto vale um conjunto fechado — 0 falhas em N = 200 limita o risco a ≈ 1,5%
(95%), e não a zero.

Os valores do eixo `vertical` **derivam-se** de `VERTICAIS` (`kamba_agr/contexto.py`,
espelho de `VERTICAIS_DO_PILOTO` do `02` §5.1) e não se escrevem à mão, pela lição
que o KAM-027 pagou no `test_gate11`: uma lista literal transforma uma invariante
num número. O dia em que o KAM-123 trouxer o `orcamento` ao `ToolContext`, a
etiqueta segue sozinha.

#### O que esta emenda **não** decide

Nenhum `kind` novo (dívida 105, credor KAM-031); o nome da tool, que é
`search_catalog` e não o `search_products` que o `05` §6.3 e o bloco escrevem
(dívida 107, decidida na emenda 1.35); o `OfferView` e o `precoDisplay`, que são
nomes da vista do COM (`03` §7.1) e entram com o KAM-051 que define a
`v_oferta_viva` — este ticket consome os canónicos `preco_minor` e `preco_tipo`
(§3.3); o `price_quote` do dono (KAM-123); as frases vetadas sem número («mais
barato», «chega amanhã»), que são `guard_out` e pertencem ao **KAM-033**; e o
tecto de repetições antes do *handoff*, que é do grafo (KAM-031) e lê o
`citation_retries` que o §5.3 já tem.

### 3.31 Grafo do Vendedor: nós, intenções, veredictos de guarda e avisos (KAM-031)

*Emenda 1.40, **proposta**.* O `../docs/tecnica/02_Agent_Runtime_Verticais.md` §7
desenha o grafo do Vendedor com vinte e um nós e uma tabela de arestas, e o §5.3
desenha o estado partilhado; o §8.4 nomeia as camadas de guardrail. Nenhum dos
nomes abaixo estava neste documento — só os **seis** nós obrigatórios do §3.26,
que são o esqueleto partilhado e não o grafo. Entram aqui porque são contrato
entre o grafo, a ToolLayer e o validador, e porque o §1 declara defeito um nome
em código que não esteja aqui.

A fonte é o §7 (os vinte e um nós, as trinta e nove linhas da tabela de arestas,
o fluxo de dois turnos), o §5.3 (o estado), o §6.5 (os erros tipados que chegam
ao `compose`), o §8.4 (as camadas de guarda), o §10 (os níveis de confiança do
STT), o §11 (o par `handoff_prepare`/`handoff_wait`) e o §14 (a degradação).

| Conceito | Nome canónico | Substitui | Nota |
|---|---|---|---|
| Nós do grafo do Vendedor | `ingest`, `stt`, `guard_in`, `classify`, `retrieve`, `tools_read`, `cart_build`, `confirm_gate`, `create_order`, `order_status`, `tools_info`, `compose`, `validate`, `guard_out`, `unknown_reply`, `ask_repeat`, `safe_reply`, `send`, `handoff_prepare`, `handoff_wait`, `handoff_close` | — | ../docs/tecnica/02 §7.3 e §7.4. Lista fechada de **vinte e um**; os seis do §3.26 são subconjunto |
| Intenção do Vendedor | `state.intent` ∈ {`produto`, `preco_stock`, `comprar`, `confirmar`, `pagamento_estado`, `encomenda`, `info_loja`, `humano`, `outro`} | — | ../docs/tecnica/02 §7.3, linhas 11 a 17. **Nove**, e é a lista do Vendedor: a de Serviços está no §8.2 e é outra |
| Veredicto da guarda de entrada | `state.guard.veredicto` ∈ {`ok`, `injection`, `abuse`, `out_of_domain`, `card_data`, `sensitive`} | — | ../docs/tecnica/02 §7.3 linhas 8 a 10, e §8.4 (as cinco camadas de entrada) |
| Oferta de produto no estado do turno | `state.ofertas` | — | Os campos são os do contrato de saída da tool (`../docs/tecnica/05` §6.3) e **não se repetem aqui**: um deles designa o produto por palavras, e torná-lo canónico esvaziava a extensão qualificada da designação da loja no `canon/extensoes.yaml` — medido pelo *gate* 3b. Só deste turno, reiniciado em `ingest` |
| Aviso de negócio para o `compose` | `state.avisos` ⊆ {`NOT_FOUND`, `OUT_OF_STOCK`, `PRICE_CHANGED`, `LIMIT_EXCEEDED`, `VALIDATION_ERROR`, `UPSTREAM_TIMEOUT`, `UPSTREAM_DOWN`, `STALE_CONFIRMATION`} | — | Os sete primeiros são erros tipados do §6.5 (§3.28); o oitavo nasce no §7.3 linha 24 e **não** é erro de tool |
| Confirmação antiga ou inválida | `STALE_CONFIRMATION` | — | ../docs/tecnica/02 §7.3 linha 24. Valor de `state.avisos`, não de `tool_audit.error_code` |
| Desfecho da admissao do turno | `state.admissao` ∈ {`turno_repetido`, `contacto_bloqueado`, `ritmo`} | — | ../docs/tecnica/02 §7.3 linha 4. `None` quando o turno corre; o `ritmo` e o mesmo valor que o `agr_admitted_rejected_total` ja usa (§3.24) |
| Motivo do *handoff* | `state.handoff_motivo` | — | ../docs/tecnica/02 §11, que o lê no `handoff_prepare` e no `interrupt` |
| Versão do grafo | `graph_version`, SemVer | — | ../docs/tecnica/02 §6.4 já tem a coluna; o valor é atribuído pelo grafo que a escreve |
| Tecto de repetições de citação | `citation_retries` ≤ **1** | — | ../docs/tecnica/02 §7.3 linhas 30 e 31, e §14 («validador falha 2×») |
| Validade do carrinho | `cart.expira_at`, **30 min *proposta*** | — | ../docs/tecnica/02 §7.3 linha 23 («`cart` não expirado»), que não dá prazo |

#### Os nós são vinte e um e as arestas são **quarenta e duas**, não trinta e nove

A tabela do §7.3 tem **trinta e nove linhas** e o critério 1 do bloco do KAM-031
escreve «as 39 arestas da tabela de §7.3». São coisas diferentes, e a diferença
mede-se: **duas** linhas carregam mais do que uma aresta — a **27** (`order_status`,
`tools_info` → `compose`) carrega duas e a **34** (`unknown_reply`, `ask_repeat`,
`safe_reply` → `send`) carrega três. Trinta e nove linhas, quarenta e duas
arestas dirigidas.

Fica escrito porque o critério pede um teste de contrato que falhe «se faltar ou
sobrar uma aresta», e um teste que afirmasse trinta e nove passava com três
arestas a menos — e três arestas a menos são três nós sem caminho para o envio.
A tabela de arestas em código leva o número da linha de cada uma, de modo a que
as duas contagens se provem **ambas**.

#### O `avisos` é um campo novo do estado, e o `ofertas` também

O §5.3 escreve vinte e três campos e nenhum deles serve para isto. As duas
ausências aparecem ao escrever o grafo contra o §7.3, e não ao ler:

* **`avisos`.** Os critérios 3 e 6 do bloco dizem que `STALE_CONFIRMATION`,
  `PRICE_CHANGED`, `OUT_OF_STOCK` e `LIMIT_EXCEEDED` «chegam a `compose` como
  *facts*». Não podem: um `Fact` do §3.28 é **um número com proveniência** e o
  seu `kind` está fechado nos quatro do §6.2, pelo que um
  `Fact(kind="STALE_CONFIRMATION")` **levanta**. O que os critérios querem é que
  o `compose` seja informado, e é esse o campo — com um domínio fechado, para que
  o `compose` decida por valor conhecido e não por cadeia livre.
* **`ofertas`.** O `validate` precisa de resolver a designação de um produto a um `sku`
  (`name_sku_mismatch`), e o quarto parâmetro do `validar` do KAM-032 é
  exactamente a lista de ofertas — cujo tipo o KAM-032 já entregou — o nome vive no `ToolResult.data` do §6.3 do
  `05` e **não** num `Fact`, pela dívida **105**. Entre o `tools_read`, que o
  recebe da tool, e o `validate`, que o consome, o estado é o único canal.

Os dois são **do turno** e reiniciam-se no `ingest`, pela mesma razão que o §5.3
escreve para os `facts`: uma oferta de um turno anterior é um nome sem prova
neste, e um aviso de um turno anterior é uma explicação que já se deu.

#### Porque e que o `admissao` e um campo e nao uma segunda pergunta

Dos dez encaminhadores do §7.4, nove decidem por campos que o §5.3 já tem — o
`r_stt` lê o `stt`, o `r_guard` lê o `guard`, o `r_intent` lê o `intent`, o
`r_hits` lê as `ofertas`, o `r_upstream` e o `r_confirm` lêem os `avisos`, o
`r_cite` lê o `draft` e o `citation_retries`, o `r_handoff` lê o `handoff`. O
`r_ingest` não tinha nenhum, e a alternativa era ele **voltar a perguntar** às
fontes que o `ingest` já consultou.

Não pode: a fonte do ritmo é o `aceita_o_ritmo` do KAM-025, e esse **registra a
chegada** numa janela deslizante. Chamá-lo duas vezes por turno gastava duas
vagas das vinte por minuto e cortava o tecto a metade, sem nada no resultado o
denunciar. O campo é o que faz a decisão ser tomada uma vez e lida a seguir —
pela mesma razão que o `stt` e o `guard` são campos e não funções.

#### O que esta emenda NÃO decide

O `seq` do `idempotency_key` **não** entra no estado, e o §3.24 já o tem: com uma
só mensagem por turno (§15.1, «uma só mensagem por turno»), o `seq` do único
envio é zero, e um segundo envio no mesmo turno precisa de um campo de estado e
de outra emenda. O limiar do IDX abaixo do qual o `retrieve` vai a
`unknown_reply` fica **parâmetro sem valor canónico**: o §7.3 chama-lhe «limiar de
IDX, parâmetro» e quem o calibra é o KAM-061 com índice real. Os níveis de
confiança do STT ficam ao KAM-036, que o §10 nomeia e que declara os limiares
«a calibrar com áudio PT-AO». As frases vetadas do `guard_out` ficam ao KAM-033,
como a emenda 1.39 já escrevera.

### 3.32 Retoma do handoff: o *compare-and-set*, o `secret` do bot e o prazo (KAM-034)

*Emendas 1.41 e 1.42, **propostas**.* Entra **sem DDL**, e é a quinta assim (como as
1.25, 1.29, 1.33 e as métricas da 1.21): a `platform.handoffs` existe desde a
revisão `0011` e este ticket **não lhe acrescenta coluna nenhuma**. A cadeia de
migrações fica na `0023`. A fonte do desenho é
`../docs/tecnica/02_Agent_Runtime_Verticais.md` (§11 e §14) e
`../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§11.1, §11.4, §11.5), com o
ADR-002, o ADR-009, o ADR-010 e o ADR-015.

**A emenda 1.22 deixou uma divergência por resolver e é esta secção que a
fecha.** Ela escreveu três posições na casa sobre onde vive o *compare-and-set*
`waiting → resumed`: o `../docs/tecnica/01` §11.5 põe-no no HND, a regra (3) do
`../docs/tecnica/02` §11 põe o **ponto de entrada** no AGR, e o critério 7 do
KAM-019 manda que «a retoma por *compare-and-set* é KAM-034». Segue-se a regra
(3), porque é a única das três que diz **onde** o *endpoint* vive e sob que
*lock* corre. A consequência é que a `handoffs` tem **dois escritores em duas
linguagens**:

* **criar a passagem, marcá-la aberta, degradá-la e recuperá-la de `degraded`** é
  do HND (KAM-019), em TypeScript — as instruções do `hnd/consultas.ts`;
* **sair de `waiting`** é do AGR (KAM-034), em Python, por `/internal/resume`, e é
  a única escrita que ele faz nesta tabela.

**As duas linhas não eram uma partição, e a emenda 1.42 fez delas uma.** A
primeira versão desta secção dizia que eram, e que a fronteira ficava «escrita
aqui para que ninguém a redescubra» — e isso era **falso**, medido pela revisão
adversarial do KAM-034 (`../docs/analises/ANALISE-35`, achado 1). «Fechá-la pelo
provedor» era o `SQL_FECHAR` do `hnd/consultas.ts`, cujo `WHERE status = ANY($3)`
recebe o `ESTADOS_QUE_FECHAM` do `hnd/estados.ts` — que era
`["waiting", "degraded"]`. Isto é: **o HND também saía de `waiting`**, e escrevia
o mesmo `status = 'resumed'` que o CAS do AGR.

E a ordem estava fixada em código, no `receber` do `hnd/provedor.ts`, e era a
pior das duas: o `#fechar` corria **antes** do `onHumanEvent`, que é o único
sítio de onde `/internal/resume` pode ser chamado. No caminho feliz — um colega
responde e marca a conversa como resolvida — a linha já estava em `resumed`
quando o pedido chegava ao AGR, o CAS dava zero linhas, a rota respondia 200 (o
*no-op* do §11.5 aplicado a um pedido legítimo) e o `Command(resume=…)` **nunca
corria**: o `interrupt()` ficava pendente no *checkpoint*, a varredura dos prazos
não o encontrava (filtra `waiting`) e a invariante da não-reentrada abria-se (o
`handoff_a_espera` do `SQL_PALAVRA_DA_CONVERSA` também só conta `waiting`).

**Porque é que o AGR não podia resolver isto sozinho**, e é a razão de a decisão
ter sido de canon: do lado dele as duas situações são **indistinguíveis** — uma
passagem em `resumed` a receber um `outcome=resolved` pode ser o *webhook*
duplicado (e o *no-op* está certo) ou o primeiro pedido legítimo depois de o HND
ter escrito (e o *no-op* mata a conversa) —, e a única marca que as separa é o
estado do *checkpoint* do LangGraph, que esta rota não lê. Havia duas saídas, a
1.41 recomendou a primeira, e é ela que a **1.42** escolhe:

1. **o HND deixa de escrever o `status`** e passa a chamar `/internal/resume`,
   deixando o AGR vencer o CAS. É a que o `../docs/tecnica/01` §11.4 desenha
   (`CW->>H: webhook … resolved`, e **depois** `H->>A: retoma com Command resume
   e resultado`), a que a regra (3) do `../docs/tecnica/02` §11 escolhe, e a que
   a **emenda 1.22 já tinha escrito**: «a coluna `resumed_at` nasce e ninguém a
   escreve neste ticket [o KAM-019]» — o código do HND contradizia a entrada de
   canon do seu próprio ticket;
2. ou o AGR aceitava retomar de `resumed`, e então o «segundo é *no-op*» do §11.5
   deixava de se poder decidir pelo `status` e precisava de outra marca.
   **Recusada:** desfaz a propriedade que o KAM-034 provou com ensaios contra
   PostgreSQL e troca um predicado de uma linha por uma segunda marca que nenhum
   documento define.

**O que a 1.42 fixa, e é mais estreito do que a opção 1 pedia.** O
`ESTADOS_QUE_FECHAM` passa a `["degraded"]` — e não só «deixa de incluir
`waiting` no `resolved`»: as **três** saídas de `waiting` são do CAS do AGR
(`resumed`, `timeout` e `cancelled`, porque a rota e a varredura dos prazos
retomam o grafo nas três), pelo que um HND que saísse de `waiting` por qualquer
delas matava um `Command` da mesma maneira. A partição que fica é esta, e diz-se
em duas frases que se podem confrontar com o código: **o HND nunca tira uma
passagem de `waiting`; o AGR nunca tira uma de `degraded`.** Uma passagem
`degraded` nem chegou ao provedor, pelo que não tem resposta humana para retomar,
e o CAS recusa-a pelo predicado.

**E o `resolver` ganha caminho de escrita próprio**, porque viajava no mesmo
`#fechar` que deixou de escrever. Não entra no corpo da retoma — o ADR-010 mantém
a identidade do agente fora do AGR, e a linha do «Corpo da retoma interna» abaixo
diz porquê —, pelo que é o HND que o escreve, numa instrução **separada** do
`status` e com `status = 'waiting'` no predicado. O predicado é o que faz do
*webhook* duplicado um *no-op* também aqui: o segundo não reescreve o `resolver`
do primeiro, que é quem de facto respondeu. E a escrita vem **antes** do pedido
de retoma, pela ordem: depois do CAS a passagem já não está em `waiting` e a
instrução não casava linha nenhuma.

**E uma passagem `degraded` pode ter conversa no provedor, o que obriga a uma
terceira saída.** O `abrirConversa` **cria** a conversa — com o atributo
`handoffId` — e só depois publica a nota privada: se a nota falhar, a passagem
fica `degraded` com `external_id` nulo e a conversa está aberta lá. Um
*callback* legítimo dela existe, portanto, e o HND tem de o tratar: confere a
conversa da linha contra a do *callback*, e quando a linha ainda não tem conversa
gravada **recupera-a** (o `SQL_MARCAR_ABERTA`, que a emenda 1.22 já descreve como
«a que recupera uma passagem que ficou `degraded`») antes de pedir a retoma. A
primeira versão desta emenda punha o `external_id` no predicado da consulta do
*thread* e deixava cair esse *callback* em silêncio — isto é, reintroduzia o
defeito que ela existe para matar, por outra porta. Medido pela revisão
adversarial do KAM-019.

**O que continua a não ter dono:** uma passagem em `resumed` cujo *checkpoint*
não foi retomado — o resíduo do `ReversaoFalhadaError` — continua sem ticket, e a
1.42 não o atribui. O que ela fecha é a janela que **produzia** essas passagens
no caminho feliz; o que resta é a falha dupla (o `Command` e a compensação a
falharem no mesmo pedido), que é rara e que nenhuma varredura deste repositório
vê.

**E o `cancelled` de uma passagem em `waiting` fica sem produtor, e isso é uma
perda que se escreve em vez de se descobrir.** Das três saídas de `waiting`, duas
têm quem as peça — o `resolved`, pelo *callback* do provedor, e o `timeout`, pela
varredura dos prazos (`DESFECHO_DO_PRAZO`). O `cancelled` tinha o
`close(handoffId, 'cancelled')` do `../docs/tecnica/01` §11.1, e essa porta
deixou de poder sair de `waiting`: hoje devolve zero linhas com registo. Nenhum
caminho deste repositório pede `/internal/resume` com `cancelled`, e o
`outcomeDoProvedor` só traduz o `resolved`. **A desistência do cliente não está
implementada em ticket nenhum** — não estava antes e continua a não estar, e o
que muda é que agora está dito: quem a implementar pede a retoma com `cancelled`,
e o sítio é o mesmo de onde o `resolved` sai.

(Uma lista e não uma tabela: as tabelas do §3 são lidas pelo `dict_export`, que
exige as colunas «Conceito», «Nome canónico» e «Notas» — uma tabela auxiliar
aqui fazia a exportação levantar, e foi o que ela fez à primeira versão desta
secção.)

**O `handoff_id` é irreversível, e isso obriga a uma verificação que nenhum
documento pede.** Ele é `sha256(thread_id:handoff_seq)` (§3.15), pelo que do
identificador **não** se lê o *thread* de volta: um `handoff_id` do mesmo
*tenant* mas de **outro contacto** passaria o `tenant_id` do predicado e
retomaria o *thread* errado — a conversa de outra pessoa a ser retomada com o
desfecho desta. O CAS leva por isso o vínculo ao `contact_id` da conversa no
predicado. A alternativa era uma coluna `thread_id` na `handoffs`, e com ela uma
migração sobre uma tabela cujo DDL é do KAM-019.

**E o `resumed_at` passa a escrever-se nos três desfechos**, contra o
`SQL_FECHAR` do HND, que o escreve só em `resumed`: as três saídas de `waiting`
por esta rota **retomam o grafo**, pelo que a coluna responde a «quando é que
esta passagem deixou de estar à espera». O SLA de 15 min continua a contar só as
`resumed`, pelo predicado da consulta, e por isso a divergência não altera número
nenhum do painel.

(**Eram «quatro» nesta secção e na linha da emenda 1.41, e são três**: o
`DESFECHOS` do `handoff/maquina.py` é `("resolved", "timeout", "cancelled")` e o
`ESTADO_DO_DESFECHO` tem três chaves. Corrigido pela emenda 1.42, que foi ler o
código antes de repetir o número. A divergência com o `SQL_FECHAR` sobrevive, e
agora só no caminho `degraded`, que é o único de que ele fecha.)

| Conceito | Nome canónico | Notas |
|---|---|---|
| Serviço de passagem do lado do agente | `HandoffService` | **Porta, não implementação**, e é **outra** porta que o `HandoffProvider` do §3.15: aquela é a costura para o provedor (seis operações, do lado do HND) e esta é o que o grafo chama — **uma** operação, a abertura. O `../docs/tecnica/02` §11 nomeia-a sem lhe dar campos; o que esta linha acrescenta é que ela recebe seis argumentos e **não** o estado da conversa, porque a janela de mensagens levava o texto do cliente para fora num campo que o §6.4 não cobre |
| Corpo da retoma interna | `thread_id`, `handoff_id`, `outcome` | **Três campos de forma fechada**, os da regra (3) do `../docs/tecnica/02` §11, e um quarto é um corpo que não conhecemos. **Nenhum é o `tenant_id`**: ele sai do prefixo do `thread_id` (§3.1) e não de um campo, porque um `tenant_id` escrito por quem chama é um `tenant_id` que alguém pode trocar. E nenhum é o `resolver`: quem sabe que agente respondeu é o HND, e o AGR nunca aprende essa identidade — que é o lado certo do ADR-010 |
| Valores do `outcome` da retoma | `resolved`, `timeout`, `cancelled` | São os três **desfechos de um `close`** que o §3.15 já fixou, e não os estados da tabela: o `outcome` atravessa o `interrupt()` sem tradução, porque é ele que o nó `handoff_close` compara para decidir se manda a mensagem de alternativas. Traduzir antes de entrar fazia o `resolved` chegar ao grafo como `resumed`, que não bate com nada |
| Desfecho de uma chamada de retoma | `retomado`, `repetido`, `recusado` | Lista fechada; é o eixo de `agr_resume_total`. `retomado` venceu o *compare-and-set*; `repetido` é o *webhook* duplicado do Chatwoot, que responde 200 sem efeito; `recusado` é a passagem que **não é deste *thread*** e responde 404 — e é 404 e não 403 porque «existe mas não é tua» confirma a existência de uma passagem de outro *tenant* (ADR-015). Um painel que somasse os três não distinguia «uma retoma» de «duas» |
| Cabeçalho do `secret` do *agent bot* | `x-kamba-hnd-bot` | **A segunda credencial de `/internal/resume`**, ao lado do `x-kamba-interno` do §3.24, e provam coisas diferentes: aquele prova «vem de dentro da rede» e este prova «vem do *agent bot* **deste tenant**». Com só o primeiro, qualquer componente interno retomava a passagem de qualquer *tenant*; com só o segundo, o segredo de um bot passava a valer de fora da rede. Cabeçalho próprio e não o `Authorization`: dois valores no mesmo obrigavam a um esquema de prefixos para os separar |
| Motivo de uma retoma não autorizada | `sem_secret`, `secret_errado` | Lista fechada; é o eixo de `agr_resume_nao_autorizado_total`. São os **dois primeiros** dos quatro que o §3.15 dá ao `hnd_callback_rejeitado_total`; os outros dois não entram porque nenhum caminho desta rota os produz — o tipo é do *callback* do Chatwoot e a conta é resolvida pelo HND antes de ele chamar o AGR —, e declará-los era etiqueta sempre a zero |
| Segredo do *agent bot* | `chatwoot_bot_secret` | Uma instância por conta, como o `chatwoot_bot_token` (§3.15), e **não é ele**: o *token* autentica as nossas chamadas **para** o Chatwoot e o `secret` autentica os pedidos que chegam **de** lá (`../docs/tecnica/01` §11.3). Dois alcances opostos no mesmo bot, logo duas instâncias no cofre. **Dois consumidores:** o HND verifica o *callback* e o AGR verifica o `/internal/resume` que o HND lhe faz. Não tem coluna em tabela nenhuma: a instância é o próprio *tenant*, e a `0011` não lhe deu uma porque não é uma referência que a aplicação resolva por linha |
| Métricas da passagem no AGR | `agr_handoff_total`, `agr_resume_total`, `agr_resume_nao_autorizado_total`, `agr_handoff_degradado_total` | Quatro. O eixo da primeira são os cinco valores de `handoffs.status` e o nome do eixo é **estado** e não `outcome`, porque `waiting` é um estado de abertura e chamar-lhe desfecho dizia que uma passagem que acabou de abrir já tem um; a segunda e a terceira estão nas linhas acima; a quarta é **sem etiqueta**, pela razão do `agr_tool_tenant_mismatch_total` (§3.27). **Nenhuma leva `tenant_id`**, e o critério 8 pede a métrica de retoma «por *tenant*»: a tensão resolve-se como nas emendas 1.38 e 1.39 — a desagregação faz-se nas **colunas** (`tenant_id`, `opened_at`, `resumed_at`) e lê-se por consulta, porque uma série por *tenant* explode a cardinalidade e re-identifica (`OBS-I`) e a chamada levanta `EtiquetaInvalida` pela gramática de qualquer maneira |
| Degradação da passagem contra degradação do turno | `agr_handoff_degradado_total` ≠ `agr_degraded_turns_total` | **Duas degradações diferentes com nomes parecidos**, e a distinção escreve-se porque somá-las num painel é misturar coisas sem relação: esta conta passagens que o provedor não aceitou abrir (`../docs/tecnica/02` §14, linha do HND) e a outra conta turnos que correram em **modo determinístico** por o LLM estar indisponível (§14, linha do LLM) — e essa continua a nascer com o KAM-037, como a emenda 1.33 escreveu |
| Prazo sem resposta humana | 24 h | O `../docs/tecnica/01` §11.4 regra 4 e o critério 7. **Não é parâmetro de calibração**, ao contrário dos tectos do §3.24: é a exigência da Messaging Policy que o §11.4 cita. Ao fim dele o *scheduler* retoma com o desfecho `timeout` e o cliente recebe a mensagem de alternativas **uma só vez**, por uma chave de idempotência derivada da passagem |
| Trabalho de lote da varredura dos prazos | `agr_handoff_prazos` | O nome do *job* que o `tx_batch` exige, e exige-o para que não haja «uso sem nome nem sem contagem» do papel `kamba_batch`. A varredura atravessa *tenants* — com contexto de um, a RLS devolvia só as passagens desse —, pelo que corre com esse papel e não com o `kamba_app` da retoma. **Não há agendador**, e isso é a mesma linha que a emenda 1.34 escreveu para a retenção do `lg`: entrega-se o corpo da varredura, prova-se com relógio simulado, e quem a chama a horas é o *scheduler* do EVT |
| Sexta ligação do AGR | `kamba-agr:handoff` | O `application_name` da tomada da retoma, a sexta do serviço (§3.25 dá as quatro primeiras e a 1.38 a quinta). Tomada própria e não a da leitura pela razão da 1.38: o `kamba_core.tenant_guard` recusa uma segunda transacção na mesma ligação, e uma retoma corre **ao mesmo tempo** que turnos de outras conversas — a tranca serializa por `thread_id`, não o processo. Papel `kamba_app`, que é quem tem o `UPDATE (status, resumed_at)` da `0011` |

**O que esta secção NÃO decide**, e cada um tem credor:

* **a transição `conversation.mode = pausada` da degradação.** O critério 6 pede
  as três metades do §14 e duas são do AGR (o estado `degraded` e a mensagem);
  a terceira é a máquina de modos do **KAM-018**, que faz a transição pelo
  `SQL_MUDAR_MODO` e emite `conversation.mode_changed` **na mesma transacção**.
  O privilégio existe — a revisão `0016` deu `UPDATE (mode)` a `kamba_app` —,
  pelo que isto não é limitação da base: reescrever aquele par em Python dava um
  segundo dono para uma transição e a possibilidade de um modo mudar **sem
  evento**, que nenhum consumidor a jusante (o painel, KAM-091) saberia ler. O
  AGR tem a porta e chama-a; quem a liga é o KAM-018, do lado do CHR;
* **o cliente HTTP do `openHandoff`** é o KAM-019. Até ele existir, a porta por
  omissão levanta `HandoffUnavailable` — que não é uma falha a fingir: é
  exactamente a linha que o `../docs/tecnica/01` §11.5 escreve para «Chatwoot
  indisponível»;
* **a notificação ao dono** por canal alternativo, que o §14 pede na mesma
  linha da degradação, é o **KAM-115**; o §11.4 regra 2 proíbe usar o número da
  própria loja;
* **o *eval-gate* de handoff** (golden ≥ 85%, H7) é o **KAM-040**;
* **a varredura de passagens em `resumed` sem *checkpoint* retomado.** É o
  resíduo do único caso em que a compensação da retoma também falha, e limpá-la
  exige ler o estado do LangGraph, que esta varredura não faz. **Não está
  atribuída a ticket nenhum**, e fica dito em vez de ficar por dizer. É também o
  estado em que a sobreposição descrita acima deixa toda a passagem resolvida por
  um humano, pelo que decidir a fronteira é o que torna esta varredura
  dispensável em vez de necessária;
* **o caminho de escrita do `resolver`, se a fronteira for decidida pela opção
  1.** Hoje ele é escrito pelo mesmo `#fechar` cuja ordem é o defeito: pô-lo
  depois do `onHumanEvent` fá-lo encontrar a linha já em `resumed`, que não está
  no `ESTADOS_QUE_FECHAM`, e a coluna fica por escrever. Quem decidir a fronteira
  decide os dois no mesmo *diff*.

---

### 3.33 Subscrição de eventos no AGR: o consumidor, o turno por evento e a DLQ (KAM-038)

*Emenda 1.43, **proposta**.* Entra **sem DDL**, e é a sétima assim (como as 1.25,
1.29, 1.33, 1.41 e as métricas da 1.21): as quatro tabelas que este consumidor
toca — `events_consumed`, `events_dlq`, `conversations` e `handoffs` — existem
desde as revisões `0005`, `0009` e `0011`, e o `kamba_app` já tem nelas os
privilégios de que ele precisa (`GRANT SELECT, INSERT ON
platform.events_consumed`, `GRANT INSERT ON platform.events_dlq`). A cadeia de
migrações fica na `0023`. As fontes do desenho são
`../docs/tecnica/02_Agent_Runtime_Verticais.md` (§3, §5.1, §8.2, §15.2),
`../docs/tecnica/06_Dados_Eventos_Analytics.md` (§4, §6.3, §6.4, §6.6) e
`../docs/tecnica/03_Core_Comercio_Medusa.md` (§12), com o ADR-009, o ADR-012, o
ADR-013 e o ADR-015.

**O `payment.manual_confirmed` já estava subscrito, e esta secção regista-o em
vez de o propor.** Os Detalhes Técnicos do bloco do KAM-038 pedem-no como
*proposta* (SemVer MINOR) para as duas verticais; a emenda 1.35 (KAM-027) já o
tinha decidido pela linha «Evento do *gate* da Fase 0» do §3.5, e os dois
`registry/*.yaml` entregues já o declaram. O que este ticket acrescenta não é a
subscrição: é o **consumidor** que a lê.

**A contradição que o critério 3 nomeia já não existe no texto, e isso
escreve-se para que ninguém a reabra.** O bloco manda registar qual das duas
regras prevalece — o `../docs/tecnica/03` §12 «ignoram versões desconhecidas»
contra a regra §5 dos *Standards*, que manda falhar visível. A frase do `03` §12
**já foi corrigida** (lê-se hoje «versões desconhecidas **falham de forma
visível** (bloqueio com alerta, `06` §6.6), nunca são ignoradas em silêncio»), e
o `06` §6.6 escreve a razão por extenso: ignorar «perde dados em silêncio quando
o produtor é actualizado primeiro». Prevalece a regra §5, as três fontes
concordam, e o consumidor abre DLQ com alerta.

**Um consumidor por vertical, e não um por `(vertical, tipo)`.** O `consumer` é
a primeira metade da chave de `events_consumed` e de `events_dlq`, e a escolha
decide o que «uma linha por evento» quer dizer. Com um consumidor por par, o
mesmo `payment.confirmed` entregue às duas verticais dava quatro linhas e quatro
efeitos; com um por vertical, dá duas — uma por vertical, que é o que a regra de
dois do ADR-012 exige («as verticais não se chamam entre si: subscrevem»). A
contagem do critério 2 («1 linha em `events_consumed`») é por consumidor, e é a
única leitura em que ela é verdadeira num sistema com duas verticais a subscrever
o mesmo tipo.

**O turno por evento não invoca o grafo, e isso é decisão e não omissão.** O
critério 5 pede três propriedades — `turn_id = event_id`, sob a tranca da
conversa, e não correr com um humano com a palavra — e nenhuma delas é «invoca o
grafo». O `ingest` do grafo do Vendedor (§3.31) pressupõe **uma mensagem do
cliente** na janela `messages`, e dar-lhe um envelope era mudar o nó de entrada
de um grafo cujo dono é o KAM-031 (e o KAM-035, para Serviços). O que corre sob
a tranca é um *handler* determinístico: sem modelo no caminho, logo sem prosa a
validar pelo ADR-007, e com o texto ao cliente a ser escolhido pelo Outbound
entre mensagem livre e *template* aprovado. Quem ligar o grafo a um evento é
quem for dono do grafo.

**E o `aplica_transicao` nasce de o primeiro consumidor Python não ser quem
decide.** O `ESTADO_PRETENDIDO` do KAM-006 põe os dois eventos de pagamento a
exigir pré-condição de estado, e a sua própria nota diz porquê: «estão aqui os
eventos cujo consumo **aplica** a transição». O AGR não aplica transição nenhuma
— quem transita a encomenda é o COM (`../docs/tecnica/03` §6), e o AGR **está a
ser informado** —, e sem esta distinção o consumo de `payment.confirmed` no AGR
levantava `MaquinaEmFalta` ou, com uma máquina sobre uma tabela de encomendas
que ainda não existe (o COM é o KAM-041), adiava seis vezes e mandava para a DLQ
**todos** os pagamentos. A opção é do lado Python e a omissão é `true`, pelo que
nenhum consumidor existente muda de comportamento.

| Conceito | Nome canónico | Notas |
|---|---|---|
| Consumidor de eventos de uma vertical | `agr_vendedor`, `agr_servicos` | O `consumer` de `events_consumed` e de `events_dlq`, **um por vertical** e derivado do `id` do registo com o prefixo `agr_` — não uma lista escrita à mão, que é a lição que o `metricas.py` do KAM-027 já pagou («uma lista literal transforma uma invariante num número»). A forma casa a gramática de etiqueta de métrica `^[a-z][a-z0-9_]{1,62}$`, e tinha de casar: é o eixo do *lag* por consumidor que o DoD pede |
| Rota interna de entrega de um evento | `/internal/event` | A terceira rota de `/internal/*` (§3.24 dá `/internal/turn` e a 1.41 dá `/internal/resume`), com o mesmo `x-kamba-interno`. A casca do BullMQ fica em TypeScript, como o `agr/shim.ts` do ADR-L004 Decisão 1: a decisão toda — envelope, roteamento, idempotência, tranca, DLQ — vive no AGR, e prova-se sem fila nenhuma. **As garantias de entrega do BullMQ continuam NÃO VERIFICADAS** (L6), e é por isso que a idempotência não assenta nelas |
| Corpo da entrega de um evento | `event_id`, `tenant_id`, `envelope`, `tentativas` | **Quatro** campos de forma fechada, e um quinto é um corpo que não conhecemos. O `tentativas` é o `attemptsMade` do *job* e **não** um contador do AGR: com duas réplicas do consumidor, um contador próprio contava metade cada uma e o evento ia para a DLQ ao dobro das tentativas — a mesma razão que o `trabalhador_bullmq.ts` do KAM-006 já escreveu. Os dois primeiros são **ponteiros da fila e não autoridade**: existem porque as colunas `event_id` e `tenant_id` de `events_dlq` são `NOT NULL` e sem eles um envelope que **não se lê** desaparecia em silêncio (a mesma lacuna que o `paraDlqSemEnvelope` do `dlq.ts` fecha). Quando o envelope se lê, confrontam-se com ele e uma divergência recusa a entrega |
| Desfecho do consumo de um evento | `aplicado`, `duplicado`, `adiado`, `para_dlq`, `entregue_ao_hnd`, `sem_entitlement`, `sem_accao` | Lista fechada; é o eixo de `agr_evt_consumidos_total`. Os dois primeiros são os `DESFECHOS_DO_CONSUMO` do KAM-006 e não se renomeiam; `adiado` é a pré-condição por verificar, que **não** é desfecho do consumo mas é desfecho da entrega e é o que um painel precisa de separar de uma falha; `para_dlq` é a entrega que não volta a ser tentada; `entregue_ao_hnd` é o evento consumido numa conversa com um humano com a palavra — consumido, porque repeti-lo seis vezes para dizer sempre o mesmo não é tentar outra vez; `sem_entitlement` é o evento de um *tenant* que **não tem activa** nenhuma das verticais que o subscrevem, e **não vai à DLQ** porque não é defeito do evento: a `evt_subscricoes` é configuração de entrega global (por `consumer`, não por *tenant*) e só o AGR sabe que módulos este *tenant* tem. O nome é o `motivo` que o §3.26 já deu ao `agr_registry_denied_total`, e não se inventa um segundo. O `sem_accao` é a vertical que **subscreve** o tipo e cuja acção não está escrita — consome-se (uma linha, para o reconciliador parar) e diz-se, com credor; é o que impede a alternativa, um *handler* agnóstico à vertical a mandar a **mesma** mensagem duas vezes ao mesmo cliente |
| Motivo de uma entrada aberta na DLQ pelo AGR | `envelope_invalido`, `tipo_desconhecido`, `versao_desconhecida`, `sem_template`, `tentativas_esgotadas` | **Cinco**; lista fechada; é o eixo de `agr_evt_dlq_total` e é o que vai para `events_dlq.erro`. Os **quatro** primeiros não esperam pelas seis tentativas: um envelope que não se lê, um tipo sem contrato, uma versão que não existe e um *template* que não está aprovado não mudam entre tentativas, e gastar a escada do §6.4 com eles era adiar o alerta por treze minutos. **O `fora_de_ordem` do KAM-006 não está aqui**, e isso não é esquecimento: ele nasce dentro da pré-condição de estado, que este consumidor não corre (ver `aplica_transicao`, abaixo), pelo que declará-lo era uma etiqueta **sempre a zero** — a lição que o `echo_latency_ms` do KAM-018 escreveu. No dia em que um consumidor do AGR aplique uma transição, o valor entra aqui por emenda |
| Acção com efeito externo de um evento | `notificar_cliente`, `notificar_dono` | Os dois valores de `accao` na chave `consumer:event_id:accao` do §6.3, que o §3.5 já fixou como forma. São **duas** e não uma porque percorrem canais diferentes e têm destinatários diferentes: a primeira vai ao Outbound (WhatsApp, janela ou *template*) e a segunda vai ao HND (painel ou e-mail do Chatwoot). Dar-lhes a mesma chave fazia a segunda ser engolida como repetição da primeira |
| Desfecho de uma notificação ao cliente | `livre`, `template`, `sem_template` | Lista fechada; é o eixo de `agr_evt_notificacoes_total`, com `dono` como quarto valor para o outro canal. A decisão entre os três é do **Outbound** (KAM-015, `../docs/tecnica/01` §8.2): janela aberta dá mensagem livre (`service`), janela fechada dá *template utility* aprovado, e sem *template* aprovado **não se envia** e alerta-se. O que é do AGR é não ter caminho nenhum que mande texto livre com a janela fechada — e **o `sem_template` levantar**: ele abre entrada na DLQ em vez de dar `aplicado`, porque contar e seguir deixava uma linha em `events_consumed` sem mensagem nenhuma e, no dia em que o KAM-024 aprovasse os *templates*, a re-entrega dava `duplicado` e o cliente nunca era avisado |
| *Handler* de um evento | `(vertical, tipo)` | A chave é o **par** e não o tipo, e isso decide quantas mensagens o cliente recebe. Com a chave no tipo, um *tenant* com as **duas** verticais activas — que é precisamente o do *gate* da Fase 0 (ADR-012, KAM-108: o Vendedor produz e os Serviços consomem) — recebia a mesma mensagem **duas vezes** sobre o mesmo pagamento: dois consumidores, duas chaves de idempotência, e a `UNIQUE (tenant_id, idempotency_key)` de `outbound_messages` sem nada para deduplicar. A justificação do ADR-012 («as duas fazem coisas **diferentes** com o mesmo evento») só vale se elas fizerem mesmo coisas diferentes, e é o par que o garante |
| Acção de uma vertical por ligar | `ACCOES_POR_LIGAR`, com o credor na linha | Os pares em que a vertical subscreve o tipo e a acção dela **não está escrita** — hoje, os dois eventos de pagamento nos Serviços, cuja acção o `../docs/tecnica/03` §12 descreve («confirma uma marcação com sinal») e que é o **KAM-047** e o **KAM-035**. Declará-los, em vez de os deixar de fora, é o que distingue «ninguém escreveu isto» de «isto não existe»: o arranque continua a exigir consumidor para **cada** subscrição (código de saída 8) e o desfecho é `sem_accao`, contado e registado |
| Notificação ao dono | nunca pelo número da própria loja | O `../docs/tecnica/01` §11.4 regra 2, e aqui é uma propriedade **do código** e não uma intenção: o aviso ao dono sai por uma porta diferente da do cliente, e há um teste que lhe põe um espião e exige **zero** chamadas à porta do Outbound. O canal alternativo é o do KAM-115; o painel e o e-mail são do HND (KAM-019) |
| `turn_id` de um turno por evento | o `event_id` do envelope | O §3.24 fixou `turn_id` como o `wamid`, e isto **estende-o** em vez de o contradizer: `turn_id` é o identificador do turno, e um turno por evento não tem `wamid` nenhum. A consequência é a que o critério 5 quer — a chave de envio `turn_id:seq` do §3.24 fica estável entre re-entregas do mesmo evento, pelo que repetir a entrega não repete a mensagem |
| Métricas da subscrição no AGR | `agr_evt_consumidos_total`, `agr_evt_dlq_total`, `agr_evt_notificacoes_total`, `agr_evt_lag_ms` | Quatro. As três primeiras são contadores com os eixos das linhas acima; a quarta é uma **medida com etiqueta**, e é a primeira do repositório — o DoD pede «*lag* de consumo **por consumidor**», e um valor sem eixo não responde a isso. O eixo é o `consumer`, cujos valores são derivados das verticais. **Nenhuma leva `tenant_id`, `contact_id`, `conversation_id` nem `wamid`**, pela gramática de etiqueta e pelo `OBS-I`: a desagregação por *tenant* faz-se nas colunas de `events_consumed` e de `events_dlq`, que as têm |
| *Lag* de consumo | `ocorrido_em` até ao instante do consumo | O numerador do alvo do `../docs/tecnica/06` — p99 ≤ 10 s para a família **payment** em carga leve. Mede-se do **`ocorrido_em`** e não do `registado_em`: o primeiro é quando o facto aconteceu e é o que o cliente espera, e o segundo esconde o atraso entre o facto e a transacção que o gravou. É a mesma escolha que o §4 escreve ao separar os dois campos |
| Reserva de concorrência dos eventos de pagamento | `AGR_RESERVA_DE_PAGAMENTO` | *Proposta*, omissão **1**. É a regra 2 do `../docs/tecnica/02` §15.2 («prioridade de eventos de pagamento sobre conversa») em número: um evento da família **payment** é admitido acima do `AGR_TECTO_POR_TENANT` do §3.24, e não dentro dele. Acima e não dentro porque descontá-lo do tecto baixava a concorrência de conversa de 3 para 2 e mudava o critério 5 do KAM-025, que foi medido com 3; o anti-vizinho-ruidoso sobrevive porque o lugar extra só serve eventos dessa família, cujo ritmo é do facilitador e não do cliente. Calibra-se em KAM-084, com os outros quatro |
| Consumo que não aplica transição | `aplica_transicao` | Opção do consumo do KAM-006, omissão **verdadeira**, e só o lado Python a tem. A falsa salta a pré-condição de estado do §6.3 — e **só** essa: a marca, a ordem e a DLQ não mudam. Existe porque o `ESTADO_PRETENDIDO` é uma propriedade de **quem aplica** a transição e estava a ser lida como propriedade do tipo de evento; o AGR é informado de um pagamento, não é quem o decide (ADR-013: quem decide é o PAY, e quem transita é o COM) |
| Sétima ligação do AGR | `kamba-agr:eventos` | O `application_name` da tomada do consumidor, a sétima do serviço (§3.25 dá as quatro primeiras, a 1.38 a quinta e a 1.41 a sexta). Tomada própria pela razão das duas anteriores: o `kamba_core.tenant_guard` recusa uma segunda transacção na mesma ligação, e um evento é consumido **ao mesmo tempo** que turnos de outras conversas. Papel `kamba_app`, que é quem tem `INSERT` nas duas tabelas de eventos pela `0005` |
| Código de saída com subscrições por registar | 8 | O oitavo, pela razão escrita nas emendas 1.35, 1.36 e 1.38: `2` configuração, `3` guarda do ADR-002, `4` sem checkpointer, `5` registo inválido, `6` sem auditoria de tools, `7` sem gateway de LLM, `8` sem consumidores. Cada um manda olhar para um sítio diferente, e este manda olhar para as `subscriptions` de `registry/*.yaml`. **A validação é a mesma do KAM-027** (a (4) do §5.2, `validar_subscriptions`), e não uma segunda: duas a dizer o mesmo divergiam no dia em que o catálogo mudasse |

**O que esta secção NÃO decide**, e cada um tem credor:

* **as linhas de `evt_subscricoes`** que mandam o publicador entregar estes
  eventos ao AGR. A tabela é da revisão `0004` e a configuração de entrega é do
  **KAM-005**; sem linhas lá, o consumidor está registado no AGR e não recebe
  nada. A fonte única para as escrever é o `consumidores()` deste ticket, que as
  deriva do registo;
* **a casca BullMQ** que traduz `evt.<consumer>.p<0..15>` em `POST
  /internal/event` é o **KAM-005/KAM-006** do lado do EVT, pelo molde do
  `agr/shim.ts`;
* **a decisão entre mensagem livre e *template*** é do **KAM-015**, e o
  *template utility* aprovado de cada notificação é do **KAM-024** (catálogo de
  *templates*). Até ele existir, a porta por omissão devolve `sem_template`, que
  **não é uma falha a fingir**: é exactamente o estado do sistema hoje — não há
  *template* aprovado nenhum, e o critério 6 manda não enviar e alertar;
* **a entrega do aviso ao dono** por canal alternativo é o **KAM-115** e o
  painel é o **KAM-019**; o que é deste ticket é a porta e a propriedade de ela
  não ser a do cliente;
* **a `evt_acoes`** da revisão `0005` continua **sem escritor**. Ela é a rede do
  §6.3 para o processo que morre entre o `COMMIT` da marca e o efeito externo, e
  aqui o efeito externo corre **dentro** da transacção do consumo — o que fecha
  essa janela para a notificação, mas deixa-a aberta para quem vier a precisar
  de um efeito que não caiba numa transacção. Credor: **KAM-006**;
* **a produção dos eventos** é do **EPIC-04** e do **EPIC-05**, e o catálogo de
  esquemas versionados é o **KAM-007**, que já entregou `contratos/eventos/`.

---

### 3.34 Modo concierge: a política, o rascunho e a decisão (KAM-114)

*Emenda 1.44, **proposta**.* A fonte do desenho é o bloco do KAM-114 em
`EPIC-03_Agent_Runtime_Verticais.md`, o `../docs/exploracao/14` §3A (o Piloto
concierge), o `../docs/tecnica/01` §10.2, §10.3 e §11.4 (os modos e o prazo), o
`../docs/tecnica/02` §11 (o padrão dos dois nós) e §16 (o *golden*), e o
`../docs/tecnica/10` §11.2 e §11.3 (a reescrita sintética), com o ADR-002, o
ADR-007, o ADR-010, o ADR-015 e o ADR-018.

**Os três nomes saem do §3.8**, onde estavam pré-declarados sem conceito: a
`draft_decisions`, a política `concierge` e o `edicao_numero_livre`. É o percurso
do `owner_notices` na 1.32, do `token_ref` na 1.22 e do `llm_call_log` na 1.38, e
o *lint* recusa a redundância — pelo que as duas linhas tinham de sair de lá no
mesmo *commit* em que entraram aqui.

**O concierge não é um quinto modo de conversa, e essa é a decisão do ticket.**
O KAM-018 recusa transições fora da tabela de `../docs/tecnica/01` §10.2, e os
quatro modos (`bot`, `dono`, `humano`, `pausada`) ficam como estão. O concierge é
uma **política por *tenant*** aplicada à conversa em modo `bot`: o nó de envio é
substituído por um pedido de aprovação. Nada nesta secção toca na
`platform.conversations` nem no `SQL_MUDAR_MODO`.

**A política é uma linha de `platform.entitlements` e não superfície nova**, e as
outras três foram medidas antes de se escolher esta. O `registry/*.yaml` lê-se
uma vez no arranque e não se recarrega (não há *watcher*, não há TTL), pelo que
uma política em YAML falhava o critério 8 — «desactivar repõe o envio automático
sem reiniciar o AGR» — **por construção**. O `entitlements.limites` tem
`additionalProperties: false` no `registry/entitlement_keys.schema.json` e as
suas dez chaves são todas `bigint_nao_negativo`, pelo que um `concierge: true`
ali é **recusado na escrita**. E uma tabela ou coluna de políticas não existe e
era uma superfície a mais para o que uma linha já diz. Fica a linha, que herda a
falha fechada do `check_entitlement` (KAM-009), a RLS, o X-03 e — por se ler da
base em cada turno — o efeito imediato que o critério 8 pede.

**`pendente` não é um valor de `decisao`: é a ausência de decisão.** O critério 2
pede um *compare-and-set* `pendente → decidido` e o critério 6 fixa `decisao` em
**cinco** valores, entre os quais o `pendente` não está. As duas coisas só valem
ao mesmo tempo com uma leitura, e é esta: `decisao IS NULL` **é** o estado
pendente, e o CAS é `SET decisao = $x ... WHERE decisao IS NULL`. Uma coluna
`estado` com seis valores ao lado recusa-se pela razão que o §3.32 escreveu para
o `handoffs.status` — chamar `decisao` a um rascunho que ainda não foi decidido
dizia que um rascunho que acabou de nascer já tem uma —, e duas colunas a
codificar o mesmo facto são duas verdades à espera de divergir.

**O `turn_seq` não vive no `estado_inicial`, e a assimetria é o remédio de um
defeito medido.** O `turno.py` chama `estado_inicial` em **cada** turno e passa o
resultado ao `ainvoke`, pelo que toda a chave que aquela função escreve
sobrescreve a do *checkpoint*. Com o `turn_seq` lá, ele valia 1 em todos os
turnos e o `draft_id = sha256(thread_id:turn_seq)` era o **mesmo** em toda a
conversa: o rascunho do 2.º turno era engolido pelo `ON CONFLICT (draft_id) DO
NOTHING`, o operador nunca o via, e a conversa ficava **muda** a partir do
segundo turno. Ele vive por isso fora de **duas** tabelas — o `CAMPOS_DO_TURNO`
e o `estado_inicial` —, e o canal do LangGraph guarda o valor do *checkpoint*. O
`concierge` fica no `estado_inicial`, e aí a reposição por turno é a propriedade
que importa: sem ela, a `decisao` de um turno valia como aprovação no turno
seguinte e a mensagem saía **sem ninguém a ter aprovado**.

**O mesmo defeito atinge o `handoff_seq`, e não se corrige aqui.** Ele está no
`estado_inicial` desde o KAM-031, pelo que dois *handoffs* em dois turnos da
mesma conversa derivam o **mesmo** `handoff_id` e o segundo é engolido pelo `ON
CONFLICT` do HND: ninguém é chamado. Medido ao implementar este ticket (duas
passagens, um `handoff_id`, uma linha com contagem 2). É código fundido e fora de
âmbito; o credor é o **KAM-031**/**KAM-034** e o remédio é o mesmo que o
`turn_seq` usou.

**O custo do critério 6 não é coluna desta tabela, e as duas razões mediram-se.**
Ele manda gravar «custo da chamada (de `llm_call_log` por `turn_id`)», e: (1) a
`dat.llm_call_log` **não tem** `turn_id` — as dezesseis colunas da `0023` trazem
`trace_id`, o do W3C de `../docs/tecnica/06` §4, e o `turn_id` deste repositório
é o `wamid` (§3.24) —, pelo que a chave que o critério nomeia não existe; e (2) o
`kamba_app` **não tem `SELECT`** naquela tabela, por decisão deliberada do
KAM-030 («quem produz o registo não é quem o audita»). O AGR não pode portanto
ler o custo no instante da decisão, e preenchê-lo exigia retirar aquele
privilégio — e *mínimo* nunca é retirar uma barreira. O critério 6 fica
**parcial** por esta cláusula, e a decisão **é de quem escreveu o critério**:
conceder leitura ao AGR, acrescentar `turn_id` a uma tabela particionada e
*append-only*, ou correlacionar `trace_id` e `turn_id` onde os dois existam. (E
hoje qualquer das três devolvia `NULL`: o `custo_usd` da `0023` é nulo enquanto o
modelo for `por_decidir`.)

**As quatro métricas do critério 6 são uma vista, e por duas razões
independentes.** A primeira é a gramática de etiqueta (`OBS-I`): nem o
`tenant_id` (tem hifenes) nem o `graph_version` (`1.1.0` começa por dígito e tem
pontos) casam `^[a-z][a-z0-9_]{1,62}$`, pelo que as duas chamadas levantariam
`EtiquetaInvalida` — a mesma tensão que as emendas 1.38, 1.39 e 1.41 resolveram
três vezes, e resolve-se igual: a desagregação faz-se nas **colunas**. A segunda
é mais dura e não tem contorno: esta biblioteca **não implementa histogramas**
(está escrito no `medir`), pelo que um p50 e um p90 não são exprimíveis nela. A
`platform.v_draft_metrics` é por isso o sítio onde as quatro medidas vivem, e é o
que «alimentam H6 e H7 de KAM-109 **sem recálculo**» pede — uma consulta, não uma
reconstrução a partir de conversas.

**Privacidade: a tabela não tem coluna de texto, e isso é o produto.** O texto do
rascunho vive só no checkpointer (`lg`, com a retenção de conversa de
`../docs/tecnica/08` §7.1) e no HND. A medida da edição calcula-se onde o texto
entra — o `concierge/servico.py`, que lê o original do *checkpoint* com
`aget_state` — e para a tabela atravessa um `numeric(4, 3)`. Mas «não há coluna
de texto» não é prova de «não há texto», que é a lição da `0023`: o `thread_id` e
o `turn_id` são `text`, e a prova é por varrimento dos dados com canários. O
`graph_version` **tem** `CHECK` de forma SemVer, e a assimetria tem razão: ele é
o único dos três que **sai** na exportação do critério 7, e sem forma era um
campo livre a atravessar para fora.

**O que o HND em baixo faz, e porque não se melhora.** O `handoff_prepare` do
KAM-034, com o provedor em baixo, degrada e manda uma **mensagem estática** ao
cliente. Aqui não se pode: o critério 1 conta «0 mensagens ao cliente sem decisão
`aprovado` ou `editado`», e uma mensagem de degradação é uma mensagem. O que fica
é a linha `pendente` gravada (há registo da tentativa), a contagem em
`agr_draft_indisponivel_total`, o `interrupt()` de qualquer maneira, e o prazo
das 24 h a fechá-lo como `expirado`. **O cliente não recebe nada**, e isso é uma
perda real que se escreve em vez de se descobrir; fechá-la por outro lado — um
texto pré-aprovado por *tenant*, que seria uma decisão já tomada e não uma
mensagem sem aprovação — é decisão do **Responsável de Produto**, o mesmo credor
a quem o critério 4 devolve o «bloquear em vez de sinalizar».

| Conceito | Nome canónico | Notas |
|---|---|---|
| Política por *tenant* do modo concierge | `concierge` | O `modulo` de uma linha de `platform.entitlements`. A coluna tem `CHECK` de **forma** (`^[a-z][a-z0-9_]*$`) e não de domínio desde a `0001`, e o §3.7 escreve que «um módulo novo entra por configuração e não por migração» (ADR-012) — pelo que **não há migração para a política**, só para a tabela de decisões. Não é um módulo de entrada do ADR-020: os quatro do §3.7 são capacidades que se vendem, e este é um modo de operação que se liga a um *tenant* do Piloto. Lê-se em **cada turno**, sem *cache*, e é isso que faz desactivá-la ter efeito no turno seguinte (critério 8) em vez de «até 60 s depois» |
| Decisões sobre rascunhos | `platform.draft_decisions(draft_id, tenant_id, thread_id, turn_seq, turn_id, graph_version, decisao, motivo, razao_edicao, edicao_numero_livre, latencia_ms, criado_at, decidido_at)` | *proposta* (emenda 1.44, KAM-114). **Treze** colunas e **nenhuma de texto livre** — ver a nota acima. Criada pela revisão `0024`. Chave primária `draft_id`, e é ela que faz «re-executar o nó 5× cria 1 rascunho» ser uma propriedade da base e não de um contador deste processo. Sem `DELETE` para o `kamba_app`: a retenção é do `kamba_batch` (KAM-071) e uma decisão gravada não se apaga a pedido de quem a produziu |
| Identificador de um rascunho | `draft_id` = `sha256(thread_id:turn_seq)` | A forma do `handoff_id` do §3.15, e com a mesma consequência: é **irreversível**, pelo que o `tenant_id` no predicado não chega — um `draft_id` do mesmo *tenant* e de **outro contacto** decidia o rascunho de outra pessoa. O CAS leva por isso o `thread_id` no predicado, que é `tenant_id:contact_id` (§3.1) e compra a propriedade sem coluna nova. É a lição que a revisão adversarial do KAM-034 mediu |
| Estado pendente de um rascunho | `decisao IS NULL` | **Não é um sexto valor de `decisao`**, e a razão está na nota acima. É o que o CAS do critério 2 compara (`pendente → decidido`), o que a varredura dos prazos filtra, e o que o índice parcial `draft_decisions_pendentes_idx` indexa — total, crescia com as decididas para sempre |
| Valores de `draft_decisions.decisao` | `aprovado`, `editado`, `rejeitado`, `expirado`, `substituido` | **Cinco**, lista fechada e qualificada pela tabela, pela razão que a emenda 1.38 escreveu para o `dat.llm_call_log.resultado`: `decisao` nu colidiria com outro domínio. Cresce só com uma revisão de base de dados, que é a lição que a `0022` pagou. **As duas primeiras são as únicas que deixam sair mensagem** (`DECISOES_QUE_ENVIAM`), e é aí que a barreira do critério 1 vive em código |
| As duas vias de decisão, e os seus domínios disjuntos | `aprovado`, `editado`, `rejeitado` (o operador) contra `expirado`, `substituido` (o sistema) | A partição é a barreira do critério 1 **por dentro**: a varredura dos prazos não pode escrever `aprovado` e a rota não pode escrever `expirado`. Sem ela, uma varredura com um defeito fazia sair uma mensagem que nenhum humano aprovou, e um operador escrevia um desfecho que o sistema se reserva. Os dois conjuntos são disjuntos e a sua união são os cinco |
| Motivo de uma decisão | `tom`, `preco_errado`, `stock_errado`, `fora_de_ambito`, `deveria_ir_a_humano`, `outro` | **Seis**, lista fechada, e ***proposta***: o critério 4 diz «a definir com o operador do Piloto», e calibra-se no KAM-109. Obrigatório no `rejeitado` **e** no `editado`, proibido no `aprovado` — é o motivo que alimenta o `golden-candidates`, e uma edição sem motivo exporta um caso sem rótulo. **Domínio fechado e não texto livre**, ao contrário da `handoffs.motivo`: ali quem escreve é o grafo, e aqui é um operador humano num botão — um campo livre numa mão humana é por onde o nome de um cliente entra numa tabela que jura não ter nenhum |
| Sinal de edição com número fora dos *facts* | `edicao_numero_livre` | *proposta* (emenda 1.44, KAM-114). Coluna **booleana** e não um sétimo motivo: o `motivo` é a razão que o operador deu e este é uma condição que o sistema detectou, e juntá-los num campo perdia a que não foi escolhida. O sinal é o veredicto do validador de citação do KAM-032 sobre o texto editado — e **é o mesmo `validar`**, não uma regra própria: uma segunda implementação divergia da primeira no dia em que uma delas aprendesse um formato novo, e já há dois que só ele conhece (o extenso e o `a partir de`). O critério 4 manda **sinalizar e contar**, não bloquear, pelo que ele **volta no corpo da resposta** de `/internal/draft-decision` — gravá-lo sem o devolver deixava o sinal só num painel que quem editou não está a ver. Bloquear é decisão do Responsável de Produto |
| Razão de edição | `razao_edicao` | A «distância normalizada 0–1» do critério 6, em `numeric(4, 3)` — decimal exacto, nunca vírgula flutuante (§2). `0` é «o operador não mexeu» e `1` é «reescreveu tudo». O **intervalo** é o que o critério fixa; a **medida** é o complemento do `difflib.SequenceMatcher.ratio()` e é ***proposta***, a calibrar no KAM-109 contra as edições reais do Piloto. Obrigatória no `editado` e proibida nos outros quatro, por `CHECK`: sem isso, um `rejeitado` com `razao_edicao` dizia que houve uma edição que não houve e o `draft_edit_ratio_p50` contava-a. É por este `CHECK` que a distância se calcula **antes** do CAS — a decisão e a sua medida entram numa escrita só |
| Desfecho de uma chamada de decisão | `decidido`, `repetido`, `recusado` | Lista fechada; é o eixo de `agr_draft_decisao_total`. São os três do `/internal/resume` (§3.32) e pela mesma razão: `decidido` venceu o CAS; `repetido` é o duplo clique, que responde 200 sem efeito; `recusado` é o rascunho que **não é deste *thread*** e responde **404** — e é 404 e não 403 porque «existe mas não é teu» confirmava a existência do rascunho de outro *tenant* (ADR-015). Um painel que somasse os três não distinguia «uma decisão» de «duas» |
| Rota da decisão | `POST /internal/draft-decision` | Três campos obrigatórios (`thread_id`, `draft_id`, `decisao`) e **dois opcionais** (`motivo`, `texto`). Por isso a verificação do corpo é de **inclusão** e não de igualdade, ao contrário da retoma, onde os três são de forma fechada: exigir igualdade obrigava o HND a mandar `"texto": null` num `aprovado`. Responde `{outcome, numero_livre}`. Duas credenciais, como a retoma: o `x-kamba-interno` (§3.24) prova «vem de dentro da rede» e o `x-kamba-hnd-bot` (§3.32) prova «vem do *agent bot* deste *tenant*». O `texto` tem tecto próprio de 4096 caracteres (*proposta*, a janela de texto do WhatsApp), porque é o único campo desta rota que atravessa para o *checkpoint* |
| Nós do concierge | `draft_prepare`, `draft_wait` | Dois, o padrão do §11: o primeiro é idempotente e tem os efeitos, o segundo **só** faz `interrupt()`. Não estão nos vinte e um do §7.4 — o grafo do Vendedor passa a **vinte e três** —, e a mesma política AST do `handoff_wait` corre sobre o `draft_wait`, sem regra nova: o `verificar` do `politica_ast.py` recebe o nome do nó |
| Arestas do concierge | 40 (`send → draft_prepare`), 41 (`draft_prepare → draft_wait`), 42 (`draft_wait → send`), 43 (`draft_wait → END`) | **Quatro, e não estão no §7.3**, que continua a ter trinta e nove linhas e quarenta e duas arestas — por isso cada aresta passou a declarar a sua `fonte`, em vez de se inflacionar um `LINHAS_DO_73` que nomeia um documento que este ticket não abre. A linha 35 (`send → END`) passou a **condicional** e declara-o na sua `fonte` («alterada por KAM-114»), que é a única do §7.3 que este ticket toca. O desvio é no `send` e não à entrada de cada caminho porque são **cinco** as arestas que chegam lá, e uma resposta estática é uma mensagem ao cliente tanto como uma composta — interceptar num sítio cobre as cinco, e a primeira esquecida era uma mensagem a sair sem aprovação |
| O ciclo `send → draft_prepare → draft_wait → send` | limitado pelo `interrupt()`, não por contador | É o **segundo** ciclo do grafo (o primeiro é o `compose`/`validate`, com o `citation_retries`), e o limite é de outra natureza: o `draft_wait` **para** o grafo e só uma decisão humana ou a varredura o retomam, pelo que ele não pode girar sozinho — o que é mais forte do que um tecto, porque não depende de alguém manter o tecto certo. A segunda passagem pelo `send` traz a decisão no estado e sai pela aresta `enviado` |
| Campo novo do estado | `concierge` | O que o concierge sabe sobre o rascunho **deste** turno: `draft_id`, `estado`, `publicado`, `decisao` e `numero_livre`. **Reinicia-se em cada turno** (o `estado_inicial` põe-no a `None`), e é essa reposição que impede a decisão de um turno de valer como aprovação no seguinte. Dentro do turno sobrevive ao `interrupt()`, porque a retoma entra por `Command(resume=…)` e essa não traz estado inicial nenhum. As chaves do §5.3 passam a **vinte e sete** |
| Ordinal do turno na conversa | `turn_seq` | A segunda metade do `draft_id`. **Fora do `CAMPOS_DO_TURNO` e fora do `estado_inicial`** — ver a nota acima, e é a razão pela qual as chaves do §5.3 contam vinte e sete e não vinte e oito. Sobe no `ingest`, uma vez por turno, e **antes** da recusa de admissão: um turno recusado é um turno que aconteceu, e dar o mesmo ordinal ao seguinte fazia dois turnos partilharem o `draft_id` |
| Chave de idempotência do envio aprovado | `{draft_id}:send` | A do critério 2, e é **outra** que a `turn_id:seq` do KAM-031 — são duas chaves pela razão do KAM-029: no concierge o envio é consequência da **decisão** e não do turno, e dois cliques concorrentes são o mesmo `draft_id` e têm de dar **um** envio |
| Vista das métricas do concierge | `platform.v_draft_metrics` | *proposta* (emenda 1.44, KAM-114). Por `(tenant_id, graph_version)`, com `draft_approved_ratio`, `draft_edit_ratio_p50`, `draft_decision_latency_s_p50` e `_p90`. `security_invoker = true` **não é opcional**: o `verificar_vistas` do *gate* 6 recusa qualquer vista sem ele, e sem ele a vista corria com os privilégios do dono e via as linhas de todos os *tenants*. **Sem coluna de custo** — ver a nota acima. As razões são sobre as **decididas**: incluir pendentes no denominador fazia a taxa de aprovação descer só por haver rascunhos à espera |
| Métricas do concierge no AGR | `agr_draft_decisao_total`, `agr_draft_estado_total`, `agr_draft_indisponivel_total`, `agr_draft_pendentes` | Quatro. **Nenhuma leva `tenant_id` nem `graph_version`** — ver a nota acima. O eixo da segunda é **estado** e não `outcome`, pela razão do `agr_handoff_total`: o `substituido` e o `expirado` não são desfechos de chamada nenhuma, porque ninguém os pediu. A terceira é sem etiqueta, e conta precisamente o caso em que o cliente **não recebe nada**: sem ela, o único sinal de uma conversa que morreu em silêncio era a linha `expirado` 24 h depois. A quarta é uma **medida** e não um contador, porque «quantos estão à espera agora» não se lê de um contador monótono |
| Prazo sem decisão humana | 24 h | O critério 1. **Não é parâmetro de calibração**, como o do *handoff* (§3.32): é o mesmo prazo, e vem da Messaging Policy que o `../docs/tecnica/01` §11.4 cita — passadas 24 h a janela de serviço fechou e a mensagem não pode sair de qualquer maneira. Ao fim dele a varredura marca `expirado` **e retoma o grafo**, que é a metade que não se pode esquecer: um rascunho marcado sem retoma deixava o *thread* com um `interrupt` pendente para sempre, e a invariante do §11 proíbe invocar o grafo com *input* novo nesse estado — a conversa ficava **muda** em vez de automática |
| Alerta de rascunho à espera | 10 minutos | ***Proposta*** (critério 6), a calibrar no KAM-109 com o operador do Piloto. É o valor que a varredura mede para o `agr_draft_pendentes` |
| Trabalho de lote da varredura dos rascunhos | `agr_draft_prazos` | O nome do *job* que o `tx_batch` exige, e exige-o para que não haja «uso sem nome nem sem contagem» do papel `kamba_batch`. A varredura atravessa *tenants* — com contexto de um, a RLS devolvia só os rascunhos desse —, pelo que **lista** com esse papel; a **escrita** de cada rascunho vai pelo mesmo CAS e pela mesma tranca que um clique usa, porque uma segunda via de escrita era uma segunda implementação do critério 2 e perdia a corrida contra o operador que decide no mesmo instante. **Não há agendador**, e é a mesma linha da `0020` e do KAM-034: entrega-se o corpo, prova-se com relógio simulado, e quem a chama a horas é o *scheduler* do EVT (KAM-071) |
| Substituição de um rascunho pendente | `substituido`, pelo `Substituidor` | O critério 5. O gatilho é o `Palavra.do_humano` do `ExecutorDeTurnos` — o *echo* do dono põe a conversa em `dono`, ou há um `handoffs` em `waiting` —, e corre **antes** do reencaminhamento ao HND: entre as duas chamadas um operador pode carregar em «aprovar», e alargar essa janela pelo tempo de uma chamada ao provedor era alargar a corrida. Passa pelo mesmo CAS, pelo que das duas **uma** vence. Uma falha aqui **não** impede o reencaminhamento: o cliente já está a falar com um humano, e trocar a entrega da mensagem dele por um rascunho que o prazo fecha de qualquer maneira era a troca errada |
| Trabalho de lote da exportação | `agr_golden_candidates` | O *job* do `tx_batch` do `golden-candidates`. O comando corre como **`kamba_batch`** e não como `kamba_audit`: a exportação é por natureza cross-*tenant* e o `kamba_audit` é `NOBYPASSRLS`, pelo que sem contexto a política reduzia a `tenant_id = NULL` e a consulta devolvia **zero linhas, em silêncio** — indistinguível de «ainda não houve edições». Medido contra um PostgreSQL 18. A separação do KAM-030 mantém-se: quem produz as decisões é o `kamba_app`, e o `kamba_batch` não é o produtor |
| Porta de publicação do rascunho | `PortaDeRascunho` com `publicar` | O `postDraft` que o bloco nomeia, do lado do AGR. **Uma operação e não duas**: o «evento de decisão» que o bloco põe ao lado não é operação desta porta — é um *callback* que entra pelo HND e sai em `POST /internal/draft-decision`, isto é, atravessa a fronteira no sentido contrário. Idempotente por `draft_id`, pela propriedade que o `abrir` do *handoff* compra com `ON CONFLICT`. Recebe o texto do rascunho e **não** o estado, pela lição que a revisão adversarial do KAM-031 mediu no `_resumo`: a janela de mensagens atravessava para o HND num campo que o §6.4 não cobre |
| Política activa sem serviço ligado | `ConciergeSemServicoError` | **Levanta, e não interrompe**, e a distinção é o que separa uma conversa recuperável de uma morta. Sem serviço não se grava linha, e sem linha a varredura nunca encontra o rascunho (filtra a tabela) e o CAS nunca o casa (responde 404): o `interrupt` ficava pendente **para sempre** e a invariante do §11 fechava a conversa a mensagens novas. Levantar faz o turno falhar e a mensagem fica na fila. Nos dois casos não sai mensagem; o que muda é a recuperação |
| Exportação de candidatos ao *golden* | `golden-candidates` (`db/golden_candidates.py`), com `origem=sintetico` | **Cinco** campos de `editado` e `rejeitado` — a decisão, o motivo, o sinal do número livre, a versão do grafo e a razão de edição **arredondada a uma casa** —, e nenhum identificador, nenhum instante e nenhum texto. O arredondamento é minimização e não estética: três casas sobre um universo pequeno é quase um identificador. Os Termos da Meta §4.7 proíbem treinar ou melhorar ML com dados do WhatsApp (ADR-018), pelo que daqui sai o **rótulo** e quem escreve o caso reescreve-o sinteticamente (`../docs/tecnica/10` §11.2); o caso entra em **KAM-040** |
| Oitava ligação do AGR | `kamba-agr:concierge` | O `application_name` da tomada do concierge, a oitava do serviço (o §3.25 dá as quatro primeiras, a 1.38 a quinta, a 1.41 a sexta e a 1.43 a sétima). Tomada própria e **não** a do *handoff*, que é do mesmo papel e serviria em privilégio: o `kamba_core.tenant_guard` recusa uma segunda transacção na mesma ligação, e um `/internal/draft-decision` e um `/internal/resume` concorrentes rebentavam um ao outro. Papel `kamba_app`, que é quem a `0024` autoriza |

**O que esta secção NÃO decide**, e cada um tem credor:

* **o custo por rascunho aprovado**, que é a cláusula parcial do critério 6. As
  três saídas estão escritas acima e nenhuma se toma aqui, porque uma delas
  retira uma barreira de privilégio do KAM-030: decide **quem escreveu o
  critério**;
* **o *eval-gate* do critério «Gate 13 verde com a política desligada e
  ligada»**. O **gate 13 não existe**: não há alvo `ci-13` no `Makefile` nem
  *job* no `.github/workflows/ci.yaml`, e mediu-se antes de se escrever código.
  Quem o constrói é o **KAM-040**, que está aberto e bloqueado pelo KAM-035 e
  pelo KAM-033. A caixa do DoD fica **vazia**;
* **bloquear uma edição com número livre**, em vez de a sinalizar. O critério 4
  devolve-o por escrito ao **Responsável de Produto**;
* **o texto pré-aprovado para quando o HND está em baixo**, se alguém decidir que
  o cliente não pode ficar sem resposta. Mesmo credor;
* **o `handoff_seq` que reinicia em cada turno** (ver acima): **KAM-031** e
  **KAM-034**;
* **a mensagem nova do cliente com um rascunho pendente**, que abre um segundo
  rascunho em vez de substituir o primeiro. Não sai mensagem nenhuma e o prazo
  fecha o órfão, mas fechá-lo na hora pedia que a invariante do §11 soubesse de
  rascunhos pendentes — e ela lê `conversations.mode` e `handoffs.status`, que
  são do **KAM-025** e do **KAM-018**;
* **a interface do operador**, que é o Chatwoot, e o `postDraft` do lado do HND:
  **KAM-019** entrega o cliente HTTP do provedor, e até lá a porta por omissão
  levanta `RascunhoIndisponivel` — que não é uma falha a fingir, é a linha que o
  `../docs/tecnica/01` §11.5 escreve para «Chatwoot indisponível»;
* **o agendador da varredura**, que é o **KAM-071**;
* **a calibração dos valores *proposta***: os seis motivos, a medida da distância
  e o alerta dos 10 minutos medem-se no **KAM-109**;
* **a aprovação automática por limiar de risco**, que o próprio bloco põe fora de
  âmbito (Fase 2), e **qualquer treino ou *fine-tuning* com as decisões**, que o
  ADR-018 proíbe.

---

## 4. Itens que continuam por decidir

| Item | Estado | Ticket |
|---|---|---|
| Base legal de cada finalidade de `consent_event` | o domínio está fixado (§3.1, dez valores, emenda 1.16). **A base legal não**: das dez, só `marketing` tem fonte directa e CONFIRMADA no `E3`; **seis** não têm nada | KAM-104 |
| Esquema do ledger (colunas finais, função de INSERT) | por ratificar com `../docs/tecnica/04` | KAM-053 |
| Contrato `v_oferta_viva` | por definir | KAM-051 |
| Prazo de retenção fiscal (CGT) | NÃO VERIFICADO | KAM-071 |
| Esquema de `servicos` (proposto por KAM-047) | a ratificar | KAM-047 |
| Quem altera `tenants.verificado_at` | o `plano` saiu de `kamba_app` na emenda 1.17 e o `estado` na **1.18** — este porque é a condição do critério 2 do KAM-009 e o sujeito de uma condição não pode ser quem a retira. O `verificado_at` ficou: acompanha o onboarding e não é entrada de decisão nenhuma | KAM-091 |
| Lista de planos e os seus limites | `registry/plans.yaml` nasce com valores **de exemplo**, marcados `estado: hipotese_nao_validada`. Nenhum documento tem a tabela de planos; o `../docs/tecnica/10` pressupõe-a em quatro sítios e não a escreve, e a mensalidade por plano também não está definida | KAM-109 |

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
| 1.10 | Outubro 2026 | **Emenda (*proposta*), KAM-006.** §3.5: as quatro tabelas do consumo (`events_consumed`, `events_dlq`, `evt_dlq_aprovacoes`, `evt_acoes`) e as duas funções de retenção. Duas delas desviam-se do `../docs/tecnica/06`, e os dois desvios estão escritos na sua linha: o `tenant_id` do `events_consumed` (sem ele não há RLS) e a tabela de aprovações, que o §6.4 não tem (duas pessoas não se escrevem numa coluna de texto). **E corrige uma contradicção que já cá estava:** a linha «Consumidores» dizia «DLQ após 5 tentativas» e são **6** (1 + 5), como o §6.4 fixa e o critério 2 do KAM-006 exige. | Equipa KAMBÁ |
| 1.11 | Outubro 2026 | **Emenda (*proposta*), KAM-007.** §3.5, três alterações. (1) O envelope passa a listar os **catorze** campos de topo que o `evt_emitir` constrói, com o `seq` dentro do `agregado`: eram nove, e a emenda 1.9 deixava em aberto «9 ou 14, e o `seq` no topo ou dentro do `agregado`» — fecha-se pelo lado do código, porque um contrato v1 com `additionalProperties: false` e nove campos recusava todos os envelopes reais. (2) Os «Tipos do Piloto» passam de dezoito a **trinta e oito**, com a nota corrigida: faltavam vinte tipos de Fase P que o `../docs/tecnica/06 §5` tem e esta tabela não tinha, a começar por `order.paid` (decisão aberta 6 de `../docs/eventos.md`, agora fechada). (3) Nova linha com os **campos de payload**, que nenhum documento especificava: o §5 dá produtor, consumidores, agregado, PII e fase, e não dá campos. | Equipa KAMBÁ |
| 1.12 | Outubro 2026 | **Emenda (*proposta*), KAM-007.** §3.3, duas variantes que a emenda 1.11 devia ter registado e não registou: `preco_modo` entra na coluna «Substitui» de «Preço», e «Prazo de uma reserva ou de uma referência» nasce com `expira_at` canónico e `expires_at` substituído. A 1.11 resolvera as duas divergências com o DDL de `../docs/tecnica/03` **a favor deste dicionário** e deixara as formas antigas por registar — com duas consequências que a revisão adversarial mediu (achado M3): a migração que criasse `catalog_items.preco_modo` ou `platform.stock_reservations.expires_at` falhava o *gate* 3b por um nome que o documento técnico manda usar, e o *gate* não contava as dezanove ocorrências nos documentos, porque só conta variantes registadas. | Equipa KAMBÁ |
| 1.13 | Outubro 2026 | **Emenda (*proposta*), KAM-141.** As contradições que o *gate* 3b encontrou no próprio dicionário, decididas uma a uma. §3.2: `manual_max_minor` sai da coluna «Substitui», onde estava por lapso — era o nome canónico da mesma linha, e o *gate* avisava-o em cada execução (linha 1). §3.4: `currency` ∈ {`AOA`} entra na linha «Valor», porque estava só no §2 e o D-03 do KAM-111 dá-o como forma canónica «(§3.4)» (linha 2); e as três formas do `../docs/tecnica/04` §6.2 — `hmac_sha256`, `status_pull`, `humano_auditado` — entram na coluna «Substitui» de `authn_method`, sem as quais o DDL do KAM-053, copiado do documento como o ticket manda, era recusado sem explicação (linha 4). §3.7: a linha dos módulos passa a dizer «No registo e na configuração», que é o que o §3.2 já dizia de outra maneira, e com isso a excepção `dominios_so_no_registo` de `../ci/canon-lint.yaml` fica **vazia** — era configuração a desfazer o que o dicionário dizia em prosa (linhas 6 e 9). O cabeçalho deste documento passa a 1.13: ficou em 1.0 durante treze emendas (linha 7). **As linhas 3 e 5 já estavam decididas** pelas emendas 1.8 e 1.11, e a 8 é de quem escreveu o critério do KAM-111 — ver a secção de verificação do bloco. | Equipa KAMBÁ |
| 1.14 | Outubro 2026 | **Emenda (*proposta*), KAM-012.** §3.2: entram `audit_log` e as suas doze colunas, o domínio de `actor_type`, o de `action`, a tabela `audit_heads` e o papel `kamba_audit`. Nenhum destes nomes existia no dicionário, e o §1 declara defeito um nome fora dele num DDL — sem esta emenda a revisão `0006` nascia a falhar o *gate* 3b, como a emenda 1.2 já registou para o KAM-003. **Três decisões que não são transcrição:** a coluna de tempo é `criado_at` e não o ts do `../docs/tecnica/08` §6, pelo §2 — e ts **não** entra na coluna «Substitui», porque é nome canónico de campo de *log* no §3.10 e registá-lo criava uma contradição nova, da classe que a emenda 1.13 acabou de fechar; o domínio de `action` tem **sete** valores e não os seis do bloco do ticket, porque o último critério desse mesmo bloco exige registar a leitura do registo e chama-lhe `audit.read`; e o `audit_heads` tem uma coluna gerada `chave`, porque uma chave primária recusa `NULL` e a cadeia das acções de plataforma precisa de uma linha com `tenant_id` nulo. | Equipa KAMBÁ |
| 1.15 | Outubro 2026 | **Emenda (*proposta*), KAM-140.** §4: a linha «Estados exactos de `tenant_channels` — por definir — KAM-014» sai. Contradizia o §3.2 do **mesmo documento**, que os fixa em seis e diz, por escrito, «Definidos em KAM-003 e não em KAM-014». Era uma contradição viva da classe que o KAM-141 fechou, e que o KAM-141 não apanhou — a palavra `tenant_channels` não aparece no seu bloco. No lugar dela entra a que o KAM-140 encontrou e **não** decidiu: a taxonomia de finalidades de `consent_event`, onde este dicionário e os 38 contratos de evento já publicados nomeiam conjuntos que se cruzam numa só finalidade — KAM-159. | Equipa KAMBÁ |
| 1.16 | Outubro 2026 | **Emenda (*proposta*), KAM-159.** §3.1: a taxonomia de finalidades de `consent_event` fica fixada, e e a **união** das duas que existiam — dez valores. Decisão do fundador, 2026-10-18. As cinco deste dicionário e as oito dos 38 contratos publicados cruzavam-se **numa só** (`marketing`), e duas das daqui — `partilha_estafeta` e `notificacao_dono` — eram **impossíveis de emitir**, por o `enum` dos contratos ser fechado. **Três decisões que não são transcrição:** a grafia passa a `transacao`, com um `c`, porque é a que corre — está em 38 contratos, na revisão `0004` e em onze baterias, e a convenção do §2 diz «sem acentos» e **não desempata** consoantes dobradas; o `melhoria` daqui e o `melhoria_servico` de lá são o mesmo conceito e fica o segundo, pela mesma razão; e o domínio passa de prosa a `∈ {…}`, que é a forma que o exportador lê — em prosa não havia nada que um gate pudesse comparar. `transaccao` e `melhoria` ficam registados como variantes. **O que esta emenda NÃO decide:** a base legal de cada finalidade. Das dez, só `marketing` tem fonte directa e CONFIRMADA no `E3`; **seis** não têm nada — é KAM-104, e está no §4. (A emenda dizia «cinco»: a contagem foi corrigida pelo mesmo ticket, depois da revisão adversarial.) | Equipa KAMBÁ |
| 1.17 | Outubro 2026 | **Emenda (*proposta*), KAM-009.** §3.2, cinco alterações, porque o TEN é o primeiro código a escrever uso e nenhum documento dizia onde o uso vive. (1) Entram `tenant_usage` e `usage_ledger`: o `../docs/tecnica/03` §5.2 dá `entitlements`, que guarda o **tecto**, e não há em documento nenhum a tabela do **consumo**. (2) Entra o período de uso, com o fuso dito por extenso em vez de assumido. (3) As chaves de `limites` passam de sete a **dez**: `manual_daily_max_minor`, `manual_max_por_contacto_24h` e `manual_dupla_acima_minor` estavam no `../docs/tecnica/04` §4.2 e não aqui, e o mesmo §4.2 diz em M-10 que ficam «registados em `entitlements`» — sem elas o registo de chaves deste ticket tornava o M-3 e o M-5 impossíveis de implementar, que é a classe do KAM-159 ao contrário: um documento técnico a nomear o que o canon não declara. (4) `tenants.plano` junta-se à linha da **forma** e não a um domínio: fixar-lhe o domínio aqui punha vermelha a `0001`, que é quem cria a coluna e está fundida; a lista fechada de planos impõe-se em `registry/plans.yaml`, que é configuração como as verticais. (5) **E decide-se o que estava «por decidir» desde a emenda 1.4:** `kamba_app` perde o `UPDATE` sobre `tenants.plano` e sobre `entitlements(limites, ativo)` — com a política `id = app.tenant_id` do KAM-004, um contexto de tenant subia o **próprio** plano e os **próprios** limites, e os limites são a única coisa entre um tenant e o tecto de dinheiro por pedido (ADR-013, ADR-015). Quem os altera passa a ser o `kamba_batch`. O `estado` e o `verificado_at` da mesma linha **não** se decidem aqui, e voltam ao §4 com dono (KAM-091) em vez de ficarem sem ele. | Equipa KAMBÁ |
| 1.18 | Outubro 2026 | **Emenda (*proposta*), KAM-009 — revisão adversarial.** O ticket reprovou com três críticos, e os três são §3.2. (1) A chave de `usage_ledger` passa a `(tenant_id, chave_limite, idempotency_key)`: sem a `chave_limite`, uma chave de idempotência valia para **todas** as chaves de limite do tenant, e foi medido — consumir `msgs_ai_mes` com a chave `IDK` e depois pedir `valor_max_pedido_minor` de 99 999 999 com a mesma `IDK` era aceite contra um tecto de 50 000 Kz, sem contar. (2) `kamba_app` perde o **`INSERT`** em `entitlements`: a emenda 1.17 revogou-lhe o `UPDATE` e deixou o `INSERT` da `0001`, e com a política `tenant_iso` o tenant **criava** a própria linha com o tecto que quisesse — a mesma escalada por outro verbo. (3) `kamba_app` perde o `UPDATE` sobre `tenants.estado`, que a 1.17 tinha deixado em aberto: o critério 2 do bloco manda negar `onboarding`, `suspenso` e `encerrado`, e medido, um tenant suspenso reactivava-se a si próprio e o consumo seguinte passava. A 1.17 escreveu a razão para o deixar e não escreveu esta consequência. `verificado_at` continua alterável e continua no §4 com dono (KAM-091). Nenhum nome de DDL novo nesta emenda: a coluna já estava na assinatura, o que muda é a chave. | Equipa KAMBÁ |
| 1.19 | Outubro 2026 | **Emenda (*proposta*), KAM-013.** §3.12: as duas tabelas de entrada (`inbound_events`, `unrouted_events`), os dois domínios de `kind` — doze valores em `inbound_events` e dois em `unrouted_events` —, a `event_key`, o resumo canónico `k_`, os domínios de `motivo` (quatro valores) e de `destino`, a fila `wa-inbound` e as cinco métricas do GWY. Entram porque são DDL que o KAM-013 escreve e o §1 declara defeito um nome de DDL fora deste dicionário — a mesma razão das emendas 1.2, 1.9, 1.14 e 1.17. **Três decisões que não são transcrição:** os valores de `kind` são **catorze** e não os quatro grupos do critério 8 do bloco, e repartem-se por duas colunas com `CHECK` diferentes, porque o campo `messages` da Meta traz `messages` e `statuses` no mesmo `value` (dois `kind` de um campo) e porque a quarentena precisa de dois valores próprios (`desconhecido`, `invalido`) que não são campos de webhook; o `event_key` de um evento sem `wamid` passa a ser um resumo canónico com prefixo `k_`, porque sem chave determinística a re-entrega de sete dias da Meta (E1 §5) criava uma linha de `account_update` por tentativa, e nenhum documento dizia qual era a chave desses eventos; e `unrouted_events` guarda o `payload` — a única tabela do conjunto que guarda corpo de conversa — porque o critério 6 do bloco o pede com retenção de sete dias, e isso está declarado como dado pessoal no inventário fechado de `db/tests/test_inventario.py`. **O que esta emenda NÃO decide:** o nome do array dentro do campo `smb_message_echoes`, que continua **NÃO VERIFICADO** — é KAM-017. | Equipa KAMBÁ |
| 1.20 | Outubro 2026 | **Emenda (*proposta*), KAM-014.** §3.13: a tabela `conversations` e as suas oito colunas, o domínio de `conversations.mode` (quatro valores), o prazo da janela, o `ChannelContext` de oito campos, o contrato `agent_invocation`, a fila `agr-inbound` com a forma do seu `jobId`, as quatro métricas do CHR, as duas variáveis de ligação e a variável `KAMBA_FASE`. §3.12: o domínio de `unrouted_events.motivo` passa de quatro valores a **seis** — `canal_desconhecido` (critério 2) e `mensagem_sem_identidade` são razões de **encaminhamento** e não do corpo, e sem elas o `CHECK` da revisão `0008` recusava as linhas de quarentena que o CHR tem de escrever. Os valores entram **na revisão `0008`**, que é quem cria o `CHECK`, e não numa revisão nova: o *gate* 3b lê o AST de cada revisão isoladamente, pelo que alargar o domínio numa `0009` deixava a `0008` vermelha por lhe faltarem valores (medido). A consequência está dita no DoD do KAM-014: uma base que já esteja na `0008` não ganha os valores sem voltar a aplicar as migrações. Entra porque a `conversations` é DDL que o KAM-014 escreve e o §1 declara defeito um nome de DDL fora deste dicionário. **Três decisões que não são transcrição:** o `jobId` da fila do AGR é um **resumo** de `{tenant_id}:{wamid}` e não o `wamid`, porque o `wamid` leva o número do interlocutor em base64 (`../docs/logs.md` §2.1) e uma chave de fila é lida por quem opera a fila; as métricas são **quatro** e o DoD nomeia três, pela mesma razão do `gwy_shed_total` da emenda 1.19 — e a quarta é o único sítio onde a recusa do Fluxo B e a recusa pela matriz de estados ficam visíveis, porque nenhuma das duas escreve na quarentena; e a janela de 24 h fica em `conversations` e não em `contacts`, divergindo de `../docs/tecnica/01` §6.2. **O que esta emenda NÃO decide:** a «persona» do `ChannelContext`, porque depende de `contacts.papel`, que o §3.2 nomeia e **nenhuma revisão criou** — está em `../docs/dividas-documentais.md`; nem o `turn_id` do KAM-025. A «persona» escreve-se em guilhemetes e não entre crases em toda esta secção, e isso é uma correcção desta emenda e não estilo: entre crases o `dict_export` colhia-a para `nomes_nota` e ela passava a **nome conhecido** do *gate* 3b sem nenhuma secção a definir, o que fazia o DDL de `tenant_channels` do `../docs/tecnica/03` — que tem uma coluna `persona` — dar um achado em vez de dois. Medido pelo `test_o_ddl_de_tenant_channels_do_doc_03_seria_recusado` do `canon_lint`, que ficou vermelho no CI deste PR. É a lição do comentário do `dicionario.py` sobre os valores de domínio, pelo outro lado: um nome num texto de nota não é uma decisão. | Equipa KAMBÁ |
| 1.21 | Outubro 2026 | **Emenda (*proposta*), KAM-015.** §3.14: as tabelas `outbound_messages` (catorze colunas) e `message_templates` (dez), os domínios de `state` (**seis** valores), `kind`, `category`, `status` e `quality`, o `pricing`, o `WINDOW_CLOSED`, a porta `PreSendGuard`, a chave de idempotência, as tarifas em `config/meta_rates.yaml` e as **cinco** métricas da saída (a `outbound_rate_limited_total` com a etiqueta «origem», de dois valores). **Três divergências assumidas, cada uma contra um documento que diz outra coisa:** as tabelas vivem em `platform.` e levam FK compostas, contra a forma dos DDL de `../docs/tecnica/01` §8.3–§8.4 e contra o «exactamente como o doc 01» do bloco do ticket — sem a FK composta, uma mensagem do *tenant* A podia apontar para um canal de B, que é o furo que a `0009` já nomeou; o `status` e o `quality` dos templates ficam em **minúsculas**, contra o §8.3, porque o §2 manda minúsculas e a base é nossa (o vocabulário da Meta traduz-se na fronteira, como o `wa_type` do §3.12); e a `meta_cost_usd_total` fica **sem etiqueta de tenant**, contra o DoD do ticket, porque as quatro bibliotecas de métricas recusam por gramática uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$` e um `tenant_id` é um UUID com hífenes — **a chamada levanta**; o custo por *tenant* sai de `outbound_messages.pricing` por consulta, que é o que o §16 do doc 01 já aponta, e a caixa do DoD fica vazia com esta razão. O sexto valor de `state`, `suppressed_by_human`, **nasce nesta revisão** embora seja do KAM-018, pela mecânica do *gate* 3b que a emenda 1.20 já pagou. **Corrige o §3.13**, que atribuía o FEP de 7 dias ao KAM-015 quando os *Detalhes Técnicos* do próprio KAM-015 o atribuem a Clusters. **O que não decide:** o contador do *free tier* (KAM-023), o consumidor dos webhooks de template (KAM-016/021), o aviso ao dono (KAM-115) e o evento de barramento, que nenhum critério pede. | Equipa KAMBÁ |
| 1.22 | Outubro 2026 | **Emenda (*proposta*), KAM-019.** §3.15: a tabela `handoffs` (**nove** colunas, contra as sete do bloco do ticket — acrescentam-se o `motivo`, que o `openHandoff` recebe, e o `external_id`, que ele devolve e que não tinha onde ficar), a tabela `handoff_accounts` (que o bloco não nomeia e de que o critério 1 depende, porque «`ensureAccount` 2× não duplica» exige onde guardar o que a primeira chamada criou), o domínio de `status` (**cinco** valores, com o `degraded` **não** nasce no bloco — o `docs/tecnica/02` §11 define-o, e a primeira versão desta entrada dizia o contrário), a correspondência entre os três `outcome` do `close` e os cinco `status`, a definição de `resolver` (que nenhuma fonte dava), as portas `HandoffProvider`, `MirrorMessage` e `HumanEvent` — **os dois últimos nunca definidos em sítio nenhum, só nomeados na assinatura do §11.1** — e as três métricas do HND. **Doze nomes entram que não existiam nem aqui, nem em código, nem nos contratos de evento.** **Duas divergências assumidas:** o *compare-and-set* `waiting → resumed` fica fora do ticket, contra o `../docs/tecnica/01` §11.5 e o `02` §11 que o põem no HND (prevalece o bloco, `specs/01` §5), com a consequência escrita — a coluna `resumed_at` nasce e ninguém a escreve aqui; e os *callbacks* são verificados pelo **HND** e não pelo GWY, contra o `../docs/tecnica/08` §3.6, porque o `secret` é por bot e logo por *tenant*, e o GWY é o único ponto sem contexto de *tenant*. **Não há tabela de fila de espelho**, e é decisão: o §14 pede uma fila que reconcilie por `wamid`, e isso é uma fila BullMQ com `jobId` derivado dele. **O `setBotMuted` não é executável** — `kamba_app` não tem `UPDATE (mode)` (revisão `0009`) e as transições são do KAM-018 —, a revisão `0011` **não** concede o privilégio, e a caixa do critério fica vazia. **Duas correcções que o próprio *gate* 3b apanhou ao conferir esta emenda:** dar domínio ao nome **nu** `tipo` (no `HumanEvent`) fez o *gate* recusar o `CHECK` de `evt_subscricoes.tipo` da revisão `0005` e declarar mortas duas extensões de `contact_endpoints.tipo` — os dois domínios desta secção passam a ser **qualificados** (`MirrorMessage.direccao`, `HumanEvent.acontecimento`), que é a regra que a emenda 1.14 escreveu para nomes genéricos e que esta emenda quase repetiu; e o `PRIMARY KEY` entre acentos graves do §3.14 estava a colher «PRIMARY» e «KEY» para os nomes conhecidos do *gate* — a classe da «persona» do KAM-014 —, pelo que passa a guilhemés. O `tenant_channels.token_ref` **sai** de `canon/extensoes.yaml` (26 extensões, eram 27): o `token_ref` é agora nome do §3.15 e o lint recusa uma extensão que o dicionário já cobre. | Equipa KAMBÁ |
| 1.23 | Outubro 2026 | **Emenda (*proposta*), KAM-019, e esta vem de medição.** §3.15: a `handoff_accounts` passa de oito para **dez** colunas, com o `provider_user_id` e o `user_token_ref`, e o preâmbulo ganha os sete factos que o spike do critério 8 mediu contra um Chatwoot v4.18.0. O que os obriga é o terceiro ator que nenhuma leitura tinha visto: o *token* da Platform API responde 401 nos *endpoints* da conta e o do bot responde 401 a criar contactos, pelo que existe um **utilizador da conta** cujo `access_token` é preciso em tempo de execução. `provider_user_id` e não `user_id` pela regra da 1.14: a KAMBÁ vai ter utilizadores seus e um nome genérico arrastaria o domínio para eles. A entrada 1.22 dizia que o `degraded` «só existe no bloco» e isso ficou corrigido na própria 1.22. | Equipa KAMBÁ |
| 1.24 | Outubro 2026 | **Emenda (*proposta*), KAM-020.** §3.16: a `platform.media_assets` com **catorze** colunas, os dois domínios **qualificados** (`media_assets.classe` e `media_assets.estado`), a forma `media://{asset_id}`, o gancho `onTranscribed` e as três métricas — **doze** nomes que não estavam no canon (a primeira versão desta entrada dizia «dez», e a secção enumerava doze), e a palavra «media» não ocorria uma única vez no `../canon/dicionario.yaml`. Qualificados pela regra da 1.14, e aqui não é cautela: há **cinco** colunas `estado` com `CHECK` nas revisões `0001`, `0003` e `0005`, e um domínio nu tornaria as cinco vermelhas e mataria a extensão `hmac_key_versions.estado=retirada`. Três colunas a mais do que o critério 1 lista, e as três vêm do próprio ticket: o `media_id`, porque o critério 2 pede a unicidade de `(tenant_id, wamid, media_id)` e o 1 não o lista; o `asset_id`, porque o critério 5 emite `media://{asset_id}`; e o `criado_at`, pela convenção do §3. **E os valores da classe levam o prefixo `media_`**, que é o que resolve a dívida 8 sem mexer no KAM-011: a chave do bloco do KAM-020 tem um segmento que a porta recusa, e em vez de mudar a porta — feita, testada, com o X-08 na sua bateria de contrato — é a classe que diz que é mídia. Seis divergências registadas, e a maior é que **a API de mídia da Meta não tem evidência nenhuma**: o `E1` não a tem e não a lista como omissão, pelo que três critérios ficam com números *proposta*. | Equipa KAMBÁ |
| 1.25 | Outubro 2026 | **Emenda (*proposta*), KAM-023, e entra sem DDL.** §3.16: as quatro métricas do *free tier* (`meta_free_tier_used_ratio` e `meta_cost_usd_estimate`, que o critério 4 nomeia, e `meta_free_tier_alert_total` com a etiqueta «nivel» e `meta_payment_suspect_total`, que ele não nomeia e que estão lá pela razão da `outbound_rate_limited_total` da emenda 1.21 — avisar sem contar é avisar em silêncio) e o domínio de dois valores do nível de aviso. **As duas colunas que o ticket mantém não entram:** existem desde a `0001` e já estão nas extensões do KAM-003, e o `docstring` da `0010` entrega-lhes a manutenção a este ticket por extenso. **Duas divergências assumidas:** as métricas ficam **sem etiqueta de tenant**, contra o critério 4, pela mesma razão e com o mesmo precedente da `meta_cost_usd_total` da emenda 1.21 — as bibliotecas da casa recusam por gramática uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$` e um UUID com hífenes **levanta** —, pelo que um *gauge* sem etiqueta passa a ser um agregado explícito (máximo para o rácio, soma para a estimativa) e as caixas do critério 4 ficam parcialmente satisfeitas; e o mês reinicia no fuso do *tenant* e não «do canal», porque não há coluna de fuso por canal e o fuso vive num sítio só, a função de período da `0007`. **O que não decide:** o motivo de restrição do canal e os códigos de erro vistos (critérios 5 e 6), que são DDL e esperam a revisão que descende da `0012` do KAM-020 — não se pré-declaram, pela regra das extensões de que um nome sem superfície falha o *gate*. | Equipa KAMBÁ |
| 1.26 | Outubro 2026 | **Emenda (*proposta*), KAM-023, a segunda metade.** §3.17: as duas colunas que a revisão `0013` acrescenta a `tenant_channels` — `motivo_restricao`, anulável e com domínio fechado de **três** valores (`payment_method` deste ticket, `quality` do KAM-021 e `policy` do KAM-017, que **nascem aqui** pela mecânica do *gate* 3b que a emenda 1.20 já pagou), e `meta_error_codes_seen`, um `integer[]` com tecto de 32 por `CHECK`. **Entra agora e não na 1.25 porque a `0013` descende da `0012` do KAM-020**, que fundiu entretanto: as revisões de base vão em série, e a metade de código do ticket foi entregue sem DDL para não ficar à espera. O `CHECK` do motivo é **qualificado pela tabela**, pela regra da 1.14. **O que não decide:** o `estado` do canal não muda (uma heurística de limiares *propostos* não corta o atendimento de uma loja; quem restringe de facto é o KAM-021 e o KAM-094), e o fuso por canal do critério 3 continua a não existir — fica na dívida 66. | Equipa KAMBÁ |
| 1.27 | Outubro 2026 | **Emenda (*proposta*), KAM-021.** §3.18: a tabela `channel_quality_log` (**oito** colunas, contra as sete do bloco — acrescenta-se o `id`, porque a chave de negócio é a `event_key`), o domínio de `evento` (**quatro**, os mesmos que o §3.12 manda para `gestao_de_canal`), a unicidade `(tenant_id, event_key)`, o `valor_novo` a guardar o **bruto** da Meta, a coluna `max_phone_numbers_per_business`, o `STATE_REFUSED` que faz os `MOTIVOS_DE_RECUSA` do §3.14 passarem de dez a **onze**, e as **quatro** métricas da qualidade (`channel_quality` com a etiqueta `rating`, que passa onde a de *tenant* não passava porque tem três valores fechados e não é um identificador; e a `channel_quality_event_total`, que não está no DoD e entra pela razão da 1.21 — tratar sem contar é tratar em silêncio). **Três divergências assumidas:** o `tenants.estado` **não** projecta `restrito`, contra o critério 3, porque a `0007` retirou o privilégio a `kamba_app` de propósito e um teste prende-o — devolvê-lo reabria a escalada que a revisão adversarial do KAM-009 fechou, e a caixa fica vazia; a matriz do §3.7 recusa também a `utility` sob `restrito` e o critério 2 só nomeia a `marketing`, e usa-se a matriz porque é o que o critério 9 pede; e os nomes dos escalões são os do gerador do KAM-024 (`TIER_2K`) e não os do bloco (`TIER_2000`), sem sinónimo inventado. **O que não decide:** o *ticket* de T&S (não existe mecanismo, e quem notifica é o KAM-115) e o fuso por canal (dívida 66, e este medidor não precisa dele — as 24 h são móveis). | Equipa KAMBÁ |
| 1.28 | Outubro 2026 | **Emenda (*proposta*), KAM-022.** §3.19: a `consent_texts` (**sem `tenant_id`**, porque um aviso de privacidade e um texto juridico de plataforma e nao dado de *tenant* — e por isso **nao** entra no X-05 nem no `../ci/rls_exceptions.yaml`, que continua com uma entrada so), a vista `consent_actual` — **a primeira do esquema** — com `security_invoker = true` (sem ele uma vista corre como o dono e a RLS passa a depender do `FORCE`, numa relacao onde ninguem iria procurar; o `verificar_vistas` do *gate* 6 exige-o desde o KAM-004 e nunca tinha tido nada para ver), a unicidade `(tenant_id, contact_id, purpose, evidence_hash)` que da a idempotencia do criterio 2 **pela base**, a composicao do `evidence_hash` com separador `\u0000` e sobre o texto **preenchido**, o dominio de um valor do `canal`, o `ConsentGate` e as suas **seis accoes** saidas de uma tabela de seis entradas x tres estados, os tres `id` de botao (e nao os titulos, porque o titulo e texto que um parecer vai mudar), as quatro palavras de *opt-out*, a contagem de avisos pelo **prefixo da chave de idempotencia** (que nao acrescenta DDL: a mesma chave que impede o aviso de sair duas vezes diz quantas vezes saiu), e as **cinco** metricas — as tres do DoD, o numerador do racio, e a `consent_blocked_total{accao}`, que nao esta no DoD e entra pela razao da 1.21: barrar sem contar e barrar em silencio. **A `consent_event` e o dominio de dez finalidades nao entram aqui** porque ja estavam no §3.1 (emendas 1.8 e 1.16). **Uma divergencia assumida:** o `id` da `consent_event` e `uuid` e nao o `bigint GENERATED ALWAYS AS IDENTITY` do `../docs/tecnica/10` §7.2 — o `kamba_app` **le** esta tabela e uma chave sequencial media quantos consentimentos tem a plataforma, que e a razao da regra do §2; a ordem que a vista precisava passou para o `ocorrido_em`, e o empate dentro do trio e impossivel pela unicidade da prova. | Equipa KAMBÁ |
| 1.29 | Outubro 2026 | **Emenda (*proposta*), KAM-018, e entra sem DDL.** §3.20: os **oito** gatilhos de transição de modo (qualificados pela métrica, e não escritos nus — a lição que a emenda 1.22 pagou com o `tipo`), as três respostas da tabela de transições, o `silencio_dono_min` de 30 minutos, as duas origens do relógio das 24 h, a chave do *lock* da conversa, as **três** métricas e os três motivos de supressão. A revisão `0016` **não cria tabela, coluna nem `CHECK`**: são dois `GRANT UPDATE` por coluna, e por isso nenhuma linha desta secção repete um domínio do §3.13 — duas entradas para `conversations.mode` fariam a segunda tapar a primeira e a `0009` ficava vermelha por lhe faltarem os quatro valores que tem. **Acrescenta um campo ao `Pedido` do §3.14**, que passa de oito a **nove**: o `turnoIniciadoEm`, opcional, que é o «turn.started_at» do pseudocódigo do critério 2 — e um envio do bot que o não traga é **recusado**, porque deixar passar desligava metade do critério em silêncio. **Três decisões que não são transcrição:** as métricas são três e o DoD nomeia três **outras** — a `conv_mode_rejected_total` entra porque é o único sítio onde «qualquer outra transição é rejeitada» fica visível em produção, e a `echo_latency_ms` **não entra**, porque pede ≥ 30 *echoes* reais de *staging* (L6, KAM-100) e uma métrica sempre a zero diz que a latência é nula quando o que se passa é que ninguém a mede; o relógio das 24 h tem **duas** origens e a segunda é o `handoffs.opened_at`, porque a conversa que o critério descreve — «24 h sem humano após handoff» — tem o `last_human_activity_at` vazio por definição; e nenhuma métrica leva etiqueta de modo, porque o par (modo, gatilho) determina o destino e uma etiqueta de origem e destino repartia oito séries em dezesseis sem dizer mais. **O que não decide:** a `smb_message_echoes` e a detecção do *echo* e do `/bot` (KAM-017), e a carga do `conversation.mode_changed` — o tipo **já existe** no catálogo, ao contrário do que o critério 6 supõe, e os seus três valores de `channel_mode` não distinguem `dono` de `humano`; a `v3` é do KAM-007. | Equipa KAMBÁ |
| 1.30 | Outubro 2026 | **Emenda (*proposta*), KAM-016.** A revisao e a **`0017`** e nao a `0016`: o KAM-018 reclamou aquele numero e chegou primeiro ao remoto, e dois `down_revision` iguais sao recusados pelo Alembic. §3.21: a `platform.channel_onboarding` (**treze** colunas, contra as quatro do bloco — cada uma das nove com o criterio que a obriga), o dominio **qualificado** de `channel_onboarding.fase` (**nove** valores, e o «desligado» do diagrama do `../docs/tecnica/01` §13.1 **fica de fora** porque e estado de «tenant_channels» e nao fase de onboarding), as **dezesseis** transicoes contra as onze do diagrama, as **duas** unicidades que dao a idempotencia do criterio 2 pela base, o `code_hash` que impede o *code* de entrar em claro, o `recursos_criados` como *array* e o dominio de quatro valores do `RecursoCriado.recurso` — **qualificado pelo tipo e nao pela coluna**, porque o *gate* 3b colheu a primeira forma («recursos_criados[].recurso») como dominio da coluna `jsonb` e exigiu-lhe um `CHECK` que ela nao pode ter, que e a classe de correccao que a 1.22 ja fez duas vezes —, o `pin_ref` (que fica aqui e nao em «tenant_channels»), o `motivo`, os **onze** campos de webhook — o `smb_message_echoes` **nao ocorria uma vez no canon** —, a forma do *popup* v4, a variavel da versao da Graph, a porta `SecretWriter` que fecha a lacuna do `ADR-L002` §6, a cifra do *token* com DEK **derivada** por *tenant* e «kid» dentro do criptograma, o tecto de dez em sete dias, as **quatro** metricas e a rota `POST /internal/channels`. **Os tres identificadores que o criterio 8 manda guardar nao entram**: «waba_id», «waac_id» e «phone_number_id» existem desde a `0001`, e esta revisao **nao acrescenta coluna nenhuma a «tenant_channels»**. **Quatro divergencias assumidas, e tres sairam de medicao.** (1) O registo de auditoria do criterio 4 e uma linha de `channel_onboarding` em «falhado» e **nao o «audit_log»**: o dominio de «audit_log.action» tem sete valores no `CHECK` da `0006`, fundida, e o *gate* 3b compara-o com o dicionario **nos dois sentidos** — um oitavo valor deixava a `0006` vermelha, que e a mecanica que a 1.20 e a 1.26 pagaram pelo outro lado. (2) A DEK por *tenant* e **derivada** e nao guardada numa tabela como a «contact_deks» do KAM-008, porque este segredo e re-cunhavel e porque uma tabela nova com `tenant_id` que a *suite* nao saiba semear falha o *gate* 6. (3) A matriz de transicoes vive no **codigo** com *compare-and-set* e nao num *trigger*, como a monotonia de «outbound_messages.state» da `0010`. (4) A troca do *code* vai na **consulta** e nao no corpo, contra a RFC 6749 §4.1.3: a primeira versao ficou vermelha contra o `GraphFalso`, e alargar o simulador era provar o cliente contra uma superficie alargada para lhe servir. **O que esta emenda nao decide:** a sincronizacao (KAM-017, que entra por «subscrito → a_sincronizar»), o orquestrador da saga (KAM-091), a lista de espera do tecto (KAM-095), o *gate* de activacao e o registo do numero em «cloud_only» (KAM-093), e o nono criterio — o onboarding real numa conta de teste da Meta —, que depende de `ext:KAM-102` e **fica por marcar**, sem evidencia inventada. | Equipa KAMBÁ |
| 1.31 | Outubro 2026 | **Emenda (*proposta*), KAM-017.** §3.22: a `platform.channel_coexistence` (**uma** tabela e não duas, e **por canal** e não por tentativa — é a unicidade `(tenant_id, channel_id)` que faz o «sem criar canal duplicado» do critério 9 ser propriedade da base), o domínio **qualificado** de `channel_coexistence.estado` (**quatro** valores, e o `sincronizado_sem_historico` é **terminal e bem-sucedido** — tratá-lo como `falhado` disparava o *offboard* por o titular ter exercido uma escolha que o *popup* da Meta lhe oferece), os **dois** passos do `E1` §2 como `text[]` com `CHECK` de **conteúdo** (o «2.ª execução = *no-op*» é da instrução, não de um `if`), os **seis** motivos de `PARTNER_REMOVED` **em minúsculas**, o `meta_error_code` como `integer`, as duas contagens, os dois relógios (`ultimo_echo_em` e `avisado_em`), os três prazos, o `MPS_POR_MODO`, o `PayloadChannelUpdated.motivo` qualificado pelo **tipo**, o `message_echoes[].to` e as **quatro** métricas. **A revisão `0018` não acrescenta coluna nenhuma a `tenant_channels`**: o `coexistence_synced_at` e o `last_account_update_at` existem desde a `0001` e nunca tiveram escritor — este ticket é o primeiro, e isso custa código e não DDL (o mesmo achado da 1.30). **Três decisões que saíram de medição.** (1) Os seis motivos vão em minúsculas porque são também `outcome` de registo e o `IDENTIFICADOR` do `logger/politica.ts` só aceita minúsculas — em modo estrito o `Logger` **levanta**, que é a classe de defeito que o `sem_humano_24h` do KAM-018 pagou. (2) **O 2593109 não se pode registar de todo**: tem sete dígitos e o `DIGITOS_MAXIMOS` é seis, pelo que é recusado no `outcome` **e** no `error_code` — mediu-se contra o espelho Python, onde o `131049` de seis dígitos passa e este não. O número fica em coluna `integer` e o registo leva o `outcome` simbólico. (3) A quarta métrica (`coex_echo_total`) não está no DoD e entra pela razão da 1.21: o critério 7 distingue o *echo* do dono do que é nosso, e separar sem contar é separar em silêncio — é o único sítio onde o **NÃO VERIFICADO L6** (se um envio por API gera *echo*) fica visível em produção. **O que esta emenda não decide:** o **modo predefinido** do produto, que depende do relatório do `ext:KAM-100` — que **não existe** — e da elegibilidade de Angola, **NÃO VERIFICADA** (risco R1); a lógica dos dois modos entrega-se inteira e é a mesma (`01` §10.1), e o que fica por marcar é um valor por omissão. E ainda: o aviso ao dono por canal alternativo (KAM-115), a base legal do histórico (KAM-104), a UI de reconexão (KAM-093), o comando `/bot` (o corpo de um *echo* não entra no `EventoDeEntrada`, e fazê-lo entrar punha texto de mensagem no contrato de ingestão) e a `echo_latency_ms` (KAM-100). | Equipa KAMBÁ |
| 1.32 | Outubro 2026 | **Emenda (*proposta*), KAM-115.** §3.23: as **duas** tabelas da revisão `0019` — a `platform.owner_contacts` (**onze** colunas, e o bloco do ticket não nomeia nenhuma) e a `platform.owner_notices` (**treze**, contra as oito do bloco) —, e são duas e não uma porque o critério 7 manda marcar o **contacto** como inválido: com uma tabela só, a invalidação vivia na última linha de aviso e «este dono tem contacto válido?» passava a ser uma consulta sobre o histórico de envios em vez de um facto. Entram também o domínio **qualificado** de `owner_notices.gatilho` (**cinco** valores — o gatilho é a *situação* e não o tipo do evento, e os **seis** motivos de `PARTNER_REMOVED` são um gatilho só, com o motivo no `episodio`), o de `owner_notices.canal` (**dois**, e o WhatsApp não é um deles — é o ticket inteiro), o de `owner_contacts.canal` (**um**, e o `sms` **não** se pré-declara: é o KAM-116), os dois domínios de motivo — **quatro** na falha do aviso e **dois** na invalidez do contacto, porque um fornecedor em baixo não diz nada sobre o endereço —, a `chave` de idempotência com o *tenant* dentro do resumo, o `lembrete` de 0 a 2 **no `CHECK`**, os três limites de frequência, os dois atrasos de lembrete, a lista branca de quatro parâmetros, a máscara do nome da loja e as **cinco** métricas. **O `owner_notices` sai do §3.8**, onde estava pré-declarado desde a redacção do epic: é o mesmo percurso do `token_ref` na 1.22 e do `waac_id` na 1.30, e o lint recusa a redundância. **Quatro decisões que saíram de medição.** (1) O `criado_at` é escrito pelo **relógio de quem chama** e não pelo `now()` do servidor: os dois limites e os lembretes medem-se dele, e com o servidor a escrevê-lo o relógio acelerado dos ensaios media uma coisa e a base registava outra — a varredura dos lembretes não via episódio nenhum. É a razão do `prazo_em` da `0018`. (2) A **janela do gatilho avalia-se antes do tecto diário**: com o tecto primeiro, três episódios do mesmo gatilho gastavam o dia todo e os outros quatro calavam-se. (3) A unicidade leva o `lembrete` **e** o `canal`: sem o primeiro, o critério 4 era impossível (um lembrete é um segundo aviso do mesmo episódio); sem o segundo, o aviso não podia sair pelos dois canais, que é o objectivo do ticket. (4) **Não há estado `suprimido`**: um aviso recusado por um limite não escreve linha, porque escrevê-la era inventar um aviso que não houve e fazer o próprio limite ter de distinguir os que contam. **O que esta emenda não decide:** o alvo de ≥ 95% dos *tenants* `ativo` com contacto verificado, que é medição sobre *tenants* reais e **fica por marcar** (a métrica e a varredura estão entregues); o fornecedor de e-mail no inventário de subprocessadores, que fica `pendente` e bloqueia `prod` por desenho (KAM-069, ADR-008); o adaptador SMS (KAM-116); a captação do e-mail e a entrega da ligação de confirmação (KAM-086); e a base legal do contacto do dono (KAM-104). | Equipa KAMBÁ |
| 1.33 | Outubro 2026 | **Emenda (*proposta*), KAM-025, e entra sem DDL.** §3.24: a API interna do AGR (`/internal/turn`, `/internal/resume`, o cabeçalho `x-kamba-interno` e o segredo `agr_internal_token`), a chave da tranca por conversa — um `pg_advisory_lock` de **sessão**, cuja chave **colide de propósito** com a do `pg_advisory_xact_lock` dos modos (§3.20), medido contra a base —, os quatro tectos por variável de ambiente (**proposta**, zero = sem limite), e as **seis** métricas do AGR mais as **duas** do *shim*. **Resolve a lacuna que o §3.13 deixou por escrito:** o `turn_id` é o `wamid` e fica **derivado**, não campo — o contrato `agent_invocation` mantém nove campos. **A cadeia de migrações fica na `0019`:** este ticket não cria tabela nenhuma, e a tranca não tem tabela. **Uma caixa do DoD fica por marcar e está dito onde:** o `agr_degraded_turns_total` pertence ao AGR e nasce com o KAM-037, pela razão que a emenda 1.29 escreveu para o `echo_latency_ms` — uma métrica sempre a zero afirma o que ninguém mediu. As duas decisões que o bloco do ticket manda registar estão em `../docs/adr/ADR-L004-fila-e-tranca-do-agr.md`, com as opções que se pesaram e o que faria rever cada uma. | Equipa KAMBÁ |
| 1.34 | Outubro 2026 | **Emenda (*proposta*), KAM-026.** §3.25: o papel `kamba_agr` — o **segundo** papel do AGR, `NOBYPASSRLS` e **sem `USAGE` no `platform`** —, a palavra-passe `db_agr_password` (obrigatória nos três ambientes: sem ela o AGR não arranca), e as duas tabelas da revisão `0020`, a `lg.checkpoints` (**oito** colunas) e a `lg.checkpoint_writes` (**nove**). As colunas são o `CheckpointTuple` do `BaseCheckpointSaver`, não um desenho nosso. **Duas tabelas e não três:** o *saver* oficial separa os valores dos canais num `checkpoint_blobs`, e com a janela recortada o estado é pequeno — o custo é não suportar canais `DeltaChannel`, e está escrito na revisão. **O `channel` fica em inglês** porque `canal` já é o canal de WhatsApp (§3.6). **Dois discriminadores de serializador** (`type` e `metadata_type`) porque o tipo do *checkpoint* não é garantidamente o dos metadados. **O pacote que o canon nomeava não entra:** o `langgraph-checkpoint-postgres` é MIT mas exige `psycopg` e `psycopg-pool`, LGPL-3.0-only, que o `ci/licenses.yaml` nega — entra só o `langgraph-checkpoint` (interface e serializador) e o SQL é nosso sobre `pg8000`; o `E4` §2.6 fica corrigido. **A RLS não se aplica** a estas tabelas, que não têm `tenant_id`: o isolamento é o prefixo do `thread_id`, o papel sem `USAGE` e o ensaio cruzado, e isso é a decisão que o bloco manda registar. **O que não decide:** os dois prazos de retenção do canon (30 dias de inactividade no §12 contra 90 após o fecho no `08` §7.1, e «fecho de conversa» não está definido em sítio nenhum), e a cifra do conteúdo do `lg` que o `06` §7.6.2 pressupõe e o §12 não nomeia. | Equipa KAMBÁ |
| 1.35 | Outubro 2026 | **Emenda (*proposta*), KAM-027.** §3.26: os nomes do `AgentRegistry` — o contrato (`load_all`, `resolve`, `Vertical`, `build_graph`), os **seis** nos obrigatorios de um grafo, as **onze** tools do catalogo do Piloto (`../docs/tecnica/02` §6.2, que nenhuma linha deste documento nomeava: so o `enhance_image` do §3.7 era tool canonica), os quatro parametros proibidos no esquema visivel ao modelo, a `registry/gates.yaml` como **terceira forma** da superficie do registo, o `modo` de uma validacao com o seu `credor`, a resposta `servico_indisponivel`, a metrica `agr_registry_denied_total`, o codigo de saida `5` e o `KAMBA_REGISTRY_DIR`. **A revisao adversarial acrescentou quatro nomes**, e os quatro saem de defeitos que ela encontrou: a `Resolucao` (que o §5.2 nao tem, e sem a qual a resposta estatica do critero 6 nao cabe no retorno), o `PorLigar` (a unica classe de problema que um `aviso` pode calar — sem ela, no dia em que o credor chegasse a linha do `gates.yaml` engolia um defeito real), a `Adiada` (cujo `error_code` tem de ser um identificador, porque a *allowlist* de logs deixava a prosa cair em silencio) e as `FASES_POSTERIORES` **vazias** (ler «≠ piloto» como «ja se pode» punha o `assistente` em producao com um `KAMBA_FASE` escrito por engano). **Decide tres divergencias**, todas a favor de fontes mais altas: `valor_max_pedido_minor` contra o `valor_max_pedido_kz` que o §5.1 e o bloco escrevem (a variante da emenda 1.13 falharia o *gate* 3b no nivel 1); `registry/gates.yaml` contra o `gates/vendedor.yaml` dentro da vertical; e o `payment.manual_confirmed` no `servicos.yaml`, que o bloco da como *proposta* e a linha «Evento do gate da Fase 0» do §3.5 ja tinha decidido. | Equipa KAMBÁ |
| 1.36 | Outubro 2026 | **Emenda (*proposta*), KAM-028.** §3.27: o contrato da ToolLayer (`ToolLayer` com `for_context`/`invoke`, `ToolContext` de oito campos, `ToolResult`, `Fact`, `BoundTool`, `Confirmation`), as **tres** classes de tool (`klass` ∈ {`read`, `write`, `money`}), as **vinte** colunas da `platform.tool_audit` (`../docs/tecnica/02` §6.4), os **dez** erros tipados do §6.5, os dois `timeout` por classe e os dois numeros do disjuntor, as cinco metricas de tool e o codigo de saida **6**. Dois nomes entram porque **nenhuma** chave do estado os tinha e nenhuma os pode ter (o §5.3 fecha em dezenove): o `run_id`, que identifica uma execucao do grafo, e o `graph_version`, que e o `version` da vertical. Registam-se tambem os dois estados de uma entrada de catalogo — `ligada` e `declarada`, esta com `credor` obrigatorio —, que e o mecanismo pelo qual a validacao (1) do §5.2 passa de `aviso` a `bloqueio` neste ticket sem que as especificacoes das tools do Vendedor e de Servicos (KAM-031 e KAM-035) tenham de existir. Duas correccoes ao desenho: `klass` com dois `s` **nao** e variante de `classe` (e o nome da coluna do §6.4, e `class` e reservada em Python), e a «morada» que o §6.2 da ao `get_store_info` **nao existe** na `platform.tenants` e e um dos sete nomes que o *lint* de PII do `../docs/tecnica/08` §7.3 proibe — a tool devolve `fuso_horario`, `zona` e `plus_code`, que sao as colunas que ha. **Quatro nomes entraram pela revisão adversarial**, e os quatro de uma medição: `KAMBA_TLS_LIGACOES` (uma tomada só serializava todos os *tenants* — 2,02 s para dez invocações de dez *tenants*), `MARGEM_DO_TECTO_MS` (o tecto do §6.5 não era imposto: um executor de 5 s contra 2 s devolvia `ok=True`), `<nao_declarados>` (os **nomes** dos argumentos, que vêm do modelo, iam em claro para a `tool_audit`) e o `sku` do `Fact`, que o KAM-032 declara. | Equipa KAMBÁ |
| 1.37 | Outubro 2026 | **Emenda (*proposta*), KAM-029.** §3.28: a `platform.tool_idempotency` e as suas sete colunas, a chave do §6.3 com o `CHECK` de forma hexadecimal, os três estados de uma reserva, o `INTENT_REUSED_WITH_DIFFERENT_CONTENT` como **décimo primeiro** erro tipado, o `TECTO_DE_ESPERA_MS` e o `DIAS_DE_RETENCAO`. **Corrige duas afirmações da emenda 1.36**, e as duas saíram de escrever código contra elas e não de uma leitura: a `tool_audit.idempotency_key` **não** guarda a chave do §6.3 — guarda a do chamador, a do turno —, e são duas chaves porque um segundo toque com `wamid` novo é um turno novo, pelo que uma desduplicação por chave de turno cobrava outra vez (critério 8); e «os dez erros tipados» passa a onze, o que arrasta o `CHECK` fechado da revisão `0021`, a etiqueta da métrica e os testes de contagem. **Uma decisão de forma com consequência:** o `\|` da fórmula do §6.3 não é um caractere separador — o `cart_id` é opaco e nenhum caractere seria seguro —, e a derivação prefixa cada parte com o comprimento; com um separador literal, duas partições diferentes das mesmas partes davam a mesma chave, que numa tool `money` é a encomenda de um cliente a responder pela de outro. Fica **NÃO VERIFICADO** e declarado no §4 que o `confirm:{cart_id}` cabe nos 256 caracteres do `id` de um *reply button*. | Equipa KAMBÁ |
| 1.38 | Outubro 2026 | **Emenda (*proposta*), KAM-030.** §3.29: o esquema **`dat`** (o terceiro do repositório, depois do `platform` da `0001` e do `lg` da `0020`, e que o canon não tinha), a `dat.llm_call_log` com as suas **dezesseis** colunas — **catorze** no `../docs/tecnica/06` §14, mais o `papel` e o `graph_version`, sem os quais o «custo por papel» do DoD não é calculável de lado nenhum —, o domínio **fechado e qualificado** de `dat.llm_call_log.resultado` (seis valores), o `llm/aliases.yaml` como artefacto comportamental com SemVer e *lock*, o `llm/precos.yaml`, os quatro papéis, os quatro erros tipados, a `PortaDeDestinos`, as **sete** métricas, a chave virtual por *tenant*, o código de saída **7** e a quinta ligação. **O `llm_call_log` sai do §3.6**, onde estava pré-declarado sem esquema e sem colunas: é o percurso do `owner_notices` na 1.32 e do `token_ref` na 1.22, e o *lint* recusa a redundância. **Três afirmações de fonte mais alta não sobreviveram a serem medidas contra a imagem fixada, e as três mudaram código** (`../docs/evidencia/KAM-030-litellm.md`): (1) o orçamento esgotado responde **422** com `type: budget_exceeded` e não o **400** que o critério 4 escreve — e o proxy usa o 400 para «alias repetido», pelo que o mapeamento do bloco nunca disparava no orçamento e disparava num erro de provisionamento; (2) a configuração do `../docs/tecnica/02` §13.1, à letra — duas entradas com o mesmo `model_name` —, **não cumpre o critério 6**: a estratégia por omissão é `simple-shuffle`, aleatória, e em 20 corridas com o primeiro fornecedor sempre em falha **3 falharam por completo**; com dois grupos e um `fallbacks` nomeado são 20 de 20; (3) `google/` é recusado pelo proxy e o prefixo do Gemini é `gemini/` — o nome do subprocessador e o prefixo da biblioteca ficam em espaços de nomes **separados**, porque é o primeiro que o `tenant_destinations` do KAM-069 usa para autorizar uma transferência. **Duas decisões de conformidade que se escrevem em vez de se tomarem em silêncio:** o `custo_usd` é `numeric` e não unidade menor inteira (0,00045 USD não cabe num cêntimo, e `numeric` não é vírgula flutuante), e o `tenant_id` **não** é etiqueta de métrica nenhuma apesar de o §13.4 mandar *metering* por ele — as quatro etiquetas vão para as colunas da tabela, e a métrica leva só o `papel` (`OBS-I`). **O que não decide:** nenhum modelo (KAM-040, e todas as linhas são `por_decidir` com credor escrito), a `tenant_destinations` e o `apd_ref` (KAM-069, e sem eles `prod` nega tudo), o modo determinístico da degradação (KAM-037), a minimização de PII (KAM-112), a mensalidade por plano (H6), o agendador (KAM-071), e se os fornecedores reportam o cache dentro ou ao lado da entrada, que fica **NÃO VERIFICADO**. | Equipa KAMBÁ |
| 1.39 | Outubro 2026 | **Emenda (*proposta*), KAM-032.** §3.30: os **sete** veredictos de `Verdict.errors` como lista fechada e qualificada, os **cinco** blocos de `blocks[].type` (o `datetime` vindo do §8.2, que o exemplo do §9.1 não tem), o `Policy.allowed_literals`, o `item.show`, o `value_minor` em **cêntimos de AOA**, as **cinco** métricas com o `vertical` por eixo e o `citation_fail_rate` como medição de amostragem que **não** é métrica Prometheus. **Decide uma divergência a favor de fonte mais alta:** o critério 1 do bloco escreve `value_kz`, e tanto o §2 (unidade menor inteira, emenda 1.13) como o §9.1 do `02` corrigido pelo KAM-139 dizem cêntimos — comparar Kz com `preco_minor` falha **sempre**, por um factor de cem (dívida 106). **Devolve duas ao credor em vez de as resolver:** os `kind` `name`, `qty` e `discount` (mais o `expiry` do `require_fact`) continuam fora do `KINDS` fechado do KAM-028, e quem os acrescenta é o ticket que produz o *fact* (dívida 105, KAM-031) — pelo que a quantidade cai em `stock`, a data em `datetime`, e o desconto **não tem onde cair**, o que torna *qualquer* percentagem `discount_unbacked`: é *fail-closed* e é o que o ADR-007 manda, mas o lado positivo do critério fica **inverificável** até o `discount` existir. **E o critério 8 não se marca:** pede as métricas «com `tenant_id` e `vertical`», e o `tenant_id` em etiqueta **levanta** `EtiquetaInvalida` pela gramática `^[a-z][a-z0-9_]{1,62}$` (`OBS-I`) — é a tensão que a emenda 1.38 já resolveu para o §13.4, e resolve-se igual: a desagregação por *tenant* faz-se onde tem significado (o `turn_id` do registo), a gramática não se alarga, e a decisão volta a quem escreveu o critério. As quatro «taxas» do §9.2 passam a razões entre cinco contadores, porque a biblioteca da casa não tem histogramas e uma taxa guardada como medida perde o denominador. | Equipa KAMBÁ |
| 1.40 | Outubro 2026 | **Emenda (*proposta*), KAM-031.** §3.31: os **vinte e um** nós do grafo do Vendedor como lista fechada (os seis do §3.26 são subconjunto), as **nove** intenções do Vendedor (a de Serviços é outra, e está no §8.2), os **seis** veredictos da guarda de entrada, o `state.ofertas`, o `state.avisos` e o `state.admissao` como campos novos do estado, o `STALE_CONFIRMATION` como oitavo valor de `avisos` que **não** é erro de tool, o `handoff_motivo` que o §11 lê e não declara, o tecto `citation_retries` ≤ 1 e a validade do carrinho (**30 min *proposta***). **Duas decisões que não são transcrição.** A primeira saiu de **medir** e não de ler: a tabela do §7.3 tem trinta e nove **linhas** e o grafo tem **quarenta e duas** arestas dirigidas — duas linhas carregam mais do que uma —, e um teste de contrato que afirmasse trinta e nove passava com três nós sem caminho para o envio. A segunda é o `avisos`: os critérios 3 e 6 do bloco mandam `STALE_CONFIRMATION` e `OUT_OF_STOCK` chegarem ao `compose` «como *facts*», e um `Fact` do §3.28 é um número com proveniência cujo `kind` está fechado nos quatro do §6.2 — o que os critérios querem é um campo de avisos, com domínio fechado, e não um `Fact` que levanta. **O que não decide:** o `seq` não entra no estado (com uma mensagem por turno, §15.1, o seq do único envio é zero), o limiar do IDX fica parâmetro sem valor canónico (KAM-061) e os níveis de confiança do STT ficam ao KAM-036, que o §10 declara «a calibrar». | Equipa KAMBÁ |
| 1.41 | Outubro 2026 | **Emenda (*proposta*), KAM-034, e entra sem DDL.** §3.32: o `HandoffService` como porta **distinta** do `HandoffProvider` do §3.15 (aquela e a costura para o provedor, com seis operacoes do lado do HND; esta e o que o grafo chama, com **uma**), os tres campos de forma fechada do corpo de `/internal/resume`, os **tres** desfechos de uma chamada de retoma (`retomado`, `repetido`, `recusado`), o cabecalho `x-kamba-hnd-bot` e o segredo `chatwoot_bot_secret` com **dois** consumidores, os dois motivos de recusa, as **quatro** metricas da passagem, o prazo de 24 h, o *job* de lote `agr_handoff_prazos` e a sexta ligacao `kamba-agr:handoff`. **Fecha a divergencia que a emenda 1.22 deixou por resolver**, e eram **tres** posicoes e nao duas: segue-se a regra (3) do `../docs/tecnica/02` §11, que e a unica das tres que diz **onde** o *endpoint* vive e sob que *lock* corre, pelo que a `platform.handoffs` passa a ter dois escritores em duas linguagens — e a fronteira entre eles fica escrita. **Duas decisoes que sairam de escrever codigo contra o canon e nao de o ler.** A primeira: o `handoff_id` e `sha256(thread_id:handoff_seq)` e portanto **irreversivel**, pelo que o `tenant_id` no predicado nao chega — um `handoff_id` do mesmo *tenant* e de **outro contacto** retomava o *thread* errado, isto e, a conversa de outra pessoa com o desfecho desta; o CAS leva o vinculo ao `contact_id` da conversa, que compra a propriedade sem a coluna `thread_id` que obrigaria a uma migracao sobre DDL do KAM-019. A segunda: o `resumed_at` escreve-se nos **quatro** desfechos e nao so no `resumed`, contra o `SQL_FECHAR` do HND, porque as quatro saidas de `waiting` por esta rota retomam o grafo — e o SLA de 15 min continua a contar so as `resumed`, pelo predicado, pelo que a divergencia nao altera numero nenhum. **Uma regra de arquitectura estreitou-se, e nao em silencio:** o *lint* do `tool_schema` proibia **toda** a escrita no `platform` fora da ToolLayer e a regra que ele implementa (§6.1, ADR-015) diz «a unica via dos **agentes**» — as duas davam o mesmo resultado so enquanto nao houvesse uma escrita de plano de controlo; passa a haver uma lista de triplos `(ficheiro, tabela, verbo)` com quatro criterios por entrada, e seis canarios medem os tres eixos: a mesma tabela noutro ficheiro, outra tabela no mesmo ficheiro, e outro verbo na mesma tabela. **O verbo entrou pela revisao adversarial do ticket**, porque a `0011` concede `GRANT SELECT, INSERT` ao `kamba_app` e um `INSERT` escrito no `consultas.py` passava o *lint* **e** corria na base. **O que nao decide, com credor em cada:** a transicao `-> pausada` da degradacao e do KAM-018 (reescrever o `SQL_MUDAR_MODO` em Python dava um segundo dono para uma transicao e um modo a mudar **sem evento**), o cliente HTTP do `openHandoff` e do KAM-019, o aviso ao dono e do KAM-115, o *golden* de handoff e do KAM-040, e a varredura de passagens em `resumed` sem *checkpoint* retomado **nao esta atribuida a ticket nenhum**. | Equipa KAMBÁ |
| 1.42 | Outubro 2026 | **Emenda (*proposta*), KAM-019, e entra sem DDL.** §3.32: **decide a fronteira que a emenda 1.41 deixou por decidir** — a sobreposição dos dois escritores da transição `waiting → resumed` da `platform.handoffs` —, pela **opção 1**, que é a que o `../docs/tecnica/01` §11.4 desenha, a que a regra (3) do `../docs/tecnica/02` §11 escolhe e a que a emenda **1.22** já tinha escrito contra o código do seu próprio ticket («a coluna `resumed_at` nasce e ninguém a escreve neste ticket»). O HND deixa de escrever o `status`, passa a chamar `POST /internal/resume`, e o AGR fica o escritor único de toda a saída de `waiting`. **E o que fica escrito é mais estreito do que a opção 1 pedia:** o `ESTADOS_QUE_FECHAM` do `hnd/estados.ts` passa a `["degraded"]` e não só «deixa de incluir `waiting` no `resolved`» — as **três** saídas de `waiting` retomam o grafo (a rota retoma com `resolved` e `cancelled`, a varredura dos prazos com `timeout`), pelo que um HND que saísse de `waiting` por qualquer delas matava um `Command(resume=…)` da mesma maneira. A partição passa a ser enunciável em duas frases: **o HND nunca tira uma passagem de `waiting`; o AGR nunca tira uma de `degraded`**. **Dois nomes de canon não mudam e um caminho de escrita nasce:** o `resolver` continua fora do corpo da retoma (ADR-010 — o AGR nunca aprende a identidade do agente), pelo que o HND passa a escrevê-lo numa instrução **separada** do `status`, com `status = 'waiting'` no predicado (é o que faz do *webhook* duplicado um *no-op* também aqui: o segundo não reescreve o `resolver` de quem respondeu) e **antes** do pedido de retoma, porque depois do CAS a passagem já não está em `waiting`. **Corrige um número da emenda 1.41:** o `resumed_at` escreve-se nos **três** desfechos e não nos quatro — o `DESFECHOS` do `handoff/maquina.py` tem três valores —, e o erro saiu de repetir uma contagem em vez de a ir ler. **O que não decide:** a varredura de passagens em `resumed` sem *checkpoint* retomado continua **sem ticket** (o que esta emenda fecha é a janela que as produzia no caminho feliz, não o resíduo da falha dupla), o *golden* de handoff é do **KAM-040**, o protocolo bot↔dono é do **KAM-018** e o aviso ao dono do **KAM-115**. **Duas coisas que saíram da revisão adversarial desta emenda, e as duas eram afirmações dela.** A primeira é um defeito que ela reintroduzia por outra porta: o `external_id` do *callback* no predicado da consulta do *thread*, justificado por «uma passagem `degraded` não existe no provedor, logo nenhum *callback* legítimo dele pode ser dela» — e o `abrirConversa` **cria** a conversa antes de a nota privada poder falhar, pelo que pode. Esse *callback* caía em silêncio, com o `interrupt()` pendente para sempre e sem varredura que o veja (a dos prazos filtra `waiting` e a passagem está `degraded`). A coluna sai do predicado, passa a sair no `SELECT`, e o chamador tem três saídas: a conversa bate, a linha ainda não tem conversa gravada (recupera-se pelo `SQL_MARCAR_ABERTA`), ou o atributo é de outra conversa — e só essa se recusa. A segunda é mais pequena e é de rigor: o *no-op* do `resolver` pelo `status = 'waiting'` só vale no duplicado **sequencial**; duas chegadas concorrentes escrevem as duas, e a nota dizia o contrário. **E o `cancelled` de `waiting` fica sem produtor**, dito acima. | Equipa KAMBÁ |
| 1.43 | Outubro 2026 | **Emenda (*proposta*), KAM-038, e entra sem DDL.** §3.33: o `consumer` por vertical (`agr_vendedor`, `agr_servicos`, derivado do `id` do registo e não escrito à mão), a rota `/internal/event` e os quatro campos do seu corpo, os **seis** desfechos do consumo de um evento, os **quatro** motivos de uma entrada na DLQ, as **duas** acções com efeito externo (`notificar_cliente`, `notificar_dono`) e a chave `consumer:event_id:accao` que o §3.5 já tinha fixado em forma, os **três** desfechos de uma notificação ao cliente, o `turn_id` de um turno por evento, as **quatro** métricas da subscrição, o *lag* medido do `ocorrido_em`, a reserva `AGR_RESERVA_DE_PAGAMENTO`, a sétima ligação `kamba-agr:eventos` e o código de saída **8**. **Regista uma subscrição em vez de a propor:** o bloco pede `payment.manual_confirmed` nas duas verticais como *proposta* MINOR, e a emenda 1.35 já o tinha decidido pela linha «Evento do *gate* da Fase 0» do §3.5 — os dois `registry/*.yaml` entregues já o declaram, pelo que o que este ticket acrescenta é o **consumidor**, não a subscrição. **E fecha a contradição que o critério 3 manda registar sem precisar de a arbitrar:** a frase do `../docs/tecnica/03` §12 («ignoram versões desconhecidas») **já foi corrigida** e lê-se hoje «falham de forma visível», pelo que as três fontes — ela, o `06` §6.6 e a regra §5 dos *Standards* — concordam, e o consumidor abre DLQ com alerta. **Três decisões que saíram de escrever código e não de o ler.** A primeira: o `consumer` é **por vertical** e não por `(vertical, tipo)`, senão o mesmo `payment.confirmed` entregue às duas verticais dava quatro linhas em `events_consumed` e quatro efeitos, e a contagem «1 linha» do critério 2 era falsa por construção. A segunda: o `aplica_transicao` do KAM-006 — o `ESTADO_PRETENDIDO` é uma propriedade de **quem aplica** a transição e estava a ser lido como propriedade do tipo, e sem a distinção o primeiro consumidor Python levantava `MaquinaEmFalta` em **todos** os pagamentos ou, com uma máquina sobre a tabela de encomendas que o KAM-041 ainda não escreveu, adiava seis vezes e mandava para a DLQ todos os pagamentos confirmados. A terceira: o `agr_evt_lag_ms` é a **primeira medida com etiqueta** do repositório, porque «*lag* por consumidor» não cabe num valor sem eixo. **O que não decide, com credor em cada:** as linhas de `evt_subscricoes` que mandam o publicador entregar ao AGR (KAM-005), a casca BullMQ da rota (KAM-005/KAM-006), a decisão janela/*template* (KAM-015) e o catálogo de *templates* aprovados (KAM-024, e até lá a porta devolve `sem_template`, que é o estado honesto), a entrega do aviso ao dono (KAM-115 e KAM-019), a `evt_acoes` que continua sem escritor (KAM-006), e o grafo invocado a partir de um evento — o `ingest` pressupõe uma mensagem do cliente, e mudá-lo é do dono do grafo (KAM-031, KAM-035). | Equipa KAMBÁ |
| 1.44 | Outubro 2026 | **Emenda (*proposta*), KAM-114.** §3.34: a política `concierge` como `modulo` de uma linha de `platform.entitlements` (**sem migração**, porque a coluna tem `CHECK` de forma e o §3.7 já escreve que «um módulo novo entra por configuração»), a `platform.draft_decisions` com as suas **treze** colunas e **nenhuma de texto livre**, o `draft_id = sha256(thread_id:turn_seq)`, os **cinco** valores de `decisao` e os **seis** de `motivo` (*proposta*, a calibrar no KAM-109), o `edicao_numero_livre`, a `razao_edicao`, os **três** desfechos de uma chamada de decisão, a rota `POST /internal/draft-decision` com três campos obrigatórios e dois opcionais, os **dois** nós (`draft_prepare`, `draft_wait`) e as **quatro** arestas, a `platform.v_draft_metrics`, as **quatro** métricas, o prazo de 24 h, os *jobs* `agr_draft_prazos` e `agr_golden_candidates`, e a oitava ligação `kamba-agr:concierge`. **Os três nomes saem do §3.8**, onde estavam pré-declarados sem conceito — o percurso do `owner_notices` na 1.32 e do `llm_call_log` na 1.38, e o *lint* recusa a redundância. **`pendente` não é um sexto valor de `decisao`:** o critério 2 pede um CAS `pendente → decidido` e o critério 6 fixa cinco valores sem ele, e a única leitura que faz os dois valerem é `decisao IS NULL`. **Três decisões saíram de medir e não de ler.** A primeira é um defeito que esta emenda corrige no seu próprio ticket: o `turno.py` passa o `estado_inicial` ao `ainvoke` em **cada** turno, pelo que toda a chave que nasça lá sobrescreve a do *checkpoint* — com o `turn_seq` lá, ele valia 1 em todos os turnos, o `draft_id` era o **mesmo** em toda a conversa, o rascunho do 2.º turno era engolido pelo `ON CONFLICT` e a conversa ficava **muda**; ele sai do `estado_inicial` e as chaves do §5.3 passam a **vinte e sete** e não vinte e oito. O mesmo defeito atinge o **`handoff_seq`** (medido: duas passagens, um `handoff_id`, contagem 2) e **não se corrige aqui** — credor KAM-031/KAM-034. A segunda: o custo do critério 6 **não é implementável como escrito**, e por duas razões medidas — a `dat.llm_call_log` não tem `turn_id` (tem `trace_id`, que é outro conceito) e o `kamba_app` não tem `SELECT` nela, por decisão deliberada do KAM-030 —, pelo que o critério fica **parcial** e a decisão sobe a quem o escreveu, porque uma das três saídas retira uma barreira de privilégio. A terceira: as quatro métricas são uma **vista** e não séries, e agora por duas razões independentes — a gramática de etiqueta recusa `tenant_id` **e** `graph_version` (`1.1.0` começa por dígito), e esta biblioteca **não tem histogramas**, pelo que um p50 não é exprimível nela. **O `graph_version` ganhou `CHECK` de forma SemVer**, e isso veio da revisão adversarial: ele é a única coluna que **sai** na exportação do critério 7, e sem forma era um campo de texto livre a atravessar para fora — o canário do X-03 mudou-se para o `turn_id`. **O que não decide, com credor em cada:** o *eval-gate* do «Gate 13», que **não existe** (medido: sem `ci-13` no `Makefile` e sem *job* no CI) e é do **KAM-040**; bloquear a edição com número livre em vez de a sinalizar, e o texto pré-aprovado para o HND em baixo, que são do **Responsável de Produto**; a mensagem nova do cliente com um rascunho pendente, que abre um segundo em vez de substituir o primeiro (**KAM-025**/**KAM-018**, que são donos da invariante do §11); o `postDraft` do lado do HND (**KAM-019**); o agendador da varredura (**KAM-071**); e a calibração dos valores *proposta* (**KAM-109**). | Equipa KAMBÁ |
