# Dicionário de Dados Canónico — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Foundation — Dicionário de Dados Canónico |
| Versão | 1.17 — **PROPOSTA** (a do §6; o cabeçalho ficou em 1.0 durante treze emendas, e é a linha 7 do KAM-141) |
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
| Papéis de base de dados | `kamba_migrator` (DDL, dono das tabelas), `kamba_app` (`NOBYPASSRLS`, sem DDL), `kamba_batch` (`BYPASSRLS`, auditado) | `kamba_ops` (`../docs/tecnica/03` §5.5, `../docs/tecnica/04` §6) | *proposta* (emenda 1.2, KAM-003). Resolve-se a favor de `../docs/tecnica/08` §3.3, que é o documento de isolamento e a autoridade sobre papéis. O `REVOKE … FROM PUBLIC, kamba_app, kamba_ops` de `../docs/tecnica/04` revoga de um papel que não existirá — divergência a corrigir, **não** coberta pelas 12 do KAM-111 |
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
| Entitlements de módulo | No registo e na configuração: `modulo` ∈ {`catalogo`, `foto`, `social`, `orcamento`}, com limites `imagens_mes`, `posts_mes`, `orcamentos_mes`. A coluna `entitlements.modulo` tem `CHECK` de **forma** e não de domínio (§3.2, ADR-012): um módulo novo entra por configuração e não por migração | KAM-124, e a emenda 1.13 (KAM-141, linha 6) |
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
