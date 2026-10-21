# Dicionário de Dados Canónico — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Foundation — Dicionário de Dados Canónico |
| Versão | 1.22 — **PROPOSTA** (a do §6; o cabeçalho ficou em 1.0 durante treze emendas, e é a linha 7 do KAM-141) |
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
| Recusa de envio com a janela fechada | `WINDOW_CLOSED` | **Não é coluna nem estado**: é o valor que o `ChannelAdapter` devolve ao chamador, que decide template ou desistir (§8.2, regra 3). Entra aqui por ser a costura que o KAM-018, o KAM-048 e o KAM-058 consomem — como o `ChannelContext` do §3.13 |
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

*Emenda 1.22, **proposta**.* Entra porque a revisão `0011` cria DDL e o §1 declara
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

| Conceito | Nome canónico | Notas |
|---|---|---|
| Passagem de uma conversa a um humano | `platform.handoffs` — `handoff_id`, `tenant_id`, `conversation_id`, `status`, `motivo`, `external_id`, `opened_at`, `resumed_at`, `resolver` | **Nove colunas, e o bloco do KAM-019 escreve sete.** As duas que se acrescentam são o `motivo` (o `openHandoff` recebe-o e sem ele a linha não diz porque é que alguém foi chamado) e o `external_id` (o identificador da conversa no provedor, que o `openHandoff` **devolve** e que não tinha onde ficar — sem ele, a segunda chamada não encontra o que a primeira criou fora da nossa base). «PRIMARY KEY (handoff_id)» e FK composta «(tenant_id, conversation_id)» para `conversations` «(tenant_id, id)», pela razão da `0009`: sem a composta, um handoff do *tenant* A podia apontar para uma conversa de B |
| Identificador de uma passagem | `handoffs.handoff_id` = `hash(thread_id, ordinal_do_handoff)` | É a chave de idempotência, e o `../docs/tecnica/01` §11.1 fixa a fórmula. **Não é um UUID gerado por nós**: é derivado, para que duas chamadas concorrentes com a mesma conversa e o mesmo ordinal cheguem ao mesmo valor sem se falarem. O `../docs/tecnica/02` §11 diz porquê em uma frase: o `interrupt()` do LangGraph **re-executa o nó**, logo o `openHandoff` é chamado mais de uma vez por desenho |
| Estado de uma passagem | `handoffs.status` ∈ {`waiting`, `resumed`, `timeout`, `cancelled`, `degraded`} | Cinco, e são **exactamente** os do `../docs/tecnica/02` §11: «Estados de `handoffs`: `waiting → resumed \| timeout \| cancelled \| degraded`, com `opened_at`, `resumed_at`, `resolver` (humano), para o SLA < 15 min por *tenant*». A primeira versão desta linha dizia que o `degraded` «só existe no bloco do KAM-019» e isso era **falso** — o documento que o define não estava na lista que a *discovery* leu, e foi uma segunda leitura, de origem, que o encontrou. O gatilho está na tabela de degradação do mesmo documento, **§14** e não §11: «HND/Chatwoot indisponível → `degraded` → mensagem ao cliente, conversa `pausada`, notificação ao dono por canal alternativo». Sem este estado, uma passagem degradada era indistinguível de uma à espera de humano |
| Desfecho de um `close` | `resolved`, `timeout`, `cancelled` | **Três, contra os cinco do `status`, e a correspondência tem de estar escrita** porque a assinatura do §11.1 usa um vocabulário e a tabela usa outro: `resolved` → `status = resumed`, `timeout` → `timeout`, `cancelled` → `cancelled`. O `waiting` e o `degraded` não são desfechos (são estados de abertura) e o `resumed` não é desfecho de `close` (é o que o `resolved` escreve). Sem este mapeamento, o `close('resolved')` não sabia o que gravar |
| Quem retomou uma passagem | `handoffs.resolver` | Anulável. O `../docs/tecnica/02` §11 define-o em uma palavra — «`resolver` (humano)» —, e o que esta linha acrescenta é a **forma**: só o identificador opaco do agente no provedor, nunca nome, e-mail ou telefone. (A primeira versão desta linha dizia que nenhuma fonte o definia, e era falso.) Não é um `contact_id` da KAMBÁ: um agente de atendimento não é um contacto, não passa pelo módulo de identidade e não tem BSUID. É dado pessoal de um trabalhador da PME, pelo que a coluna é «pessoal: sim» no inventário e não vai a registo nenhum |
| Conta de atendimento de um tenant | `platform.handoff_accounts` — `tenant_id`, `provedor`, `account_id`, `inbox_id`, `bot_id`, `token_ref`, `criado_at`, `updated_at` | **Tabela nova que o bloco do KAM-019 não nomeia e de que o critério 1 depende**: «`ensureAccount` chamado 2× não duplica» exige onde guardar o que a primeira chamada criou, e não havia candidata — a `tenant_channels.token_ref` é do canal Meta. «PRIMARY KEY (tenant_id, provedor)», que é o que torna «uma conta por PME» uma propriedade da base e não do código |
| Provedor de atendimento | `handoff_accounts.provedor` ∈ {`chatwoot`} | **Um valor, e a coluna existe por causa do ADR-012**, que fixa a costura `HandoffProvider` e diz que o Chatwoot é substituível. Uma tabela chamada `tenant_chatwoot` tornava a substituição uma migração; uma coluna de domínio torna-a uma linha |
| Referência ao *token* do bot | `handoff_accounts.token_ref` | Uma `SecretRef` (§3.9), texto **opaco**, nunca o *token*. É o mesmo desenho da `tenant_channels.token_ref` da `0001` e a instância já está declarada: `chatwoot_bot_token` com `instancias: conta` em `ops/secrets-inventory.yaml`. O `chatwoot_platform_token` **não** entra em tabela nenhuma: tem `instancias: nenhuma` e vive só no módulo de provisionamento, como o `../docs/tecnica/08` §3.6 manda |
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
| 1.22 | Outubro 2026 | **Emenda (*proposta*), KAM-019.** §3.15: a tabela `handoffs` (**nove** colunas, contra as sete do bloco do ticket — acrescentam-se o `motivo`, que o `openHandoff` recebe, e o `external_id`, que ele devolve e que não tinha onde ficar), a tabela `handoff_accounts` (que o bloco não nomeia e de que o critério 1 depende, porque «`ensureAccount` 2× não duplica» exige onde guardar o que a primeira chamada criou), o domínio de `status` (**cinco** valores, com o `degraded` a ganhar significado escrito por só existir no bloco), a correspondência entre os três `outcome` do `close` e os cinco `status`, a definição de `resolver` (que nenhuma fonte dava), as portas `HandoffProvider`, `MirrorMessage` e `HumanEvent` — **os dois últimos nunca definidos em sítio nenhum, só nomeados na assinatura do §11.1** — e as três métricas do HND. **Doze nomes entram que não existiam nem aqui, nem em código, nem nos contratos de evento.** **Duas divergências assumidas:** o *compare-and-set* `waiting → resumed` fica fora do ticket, contra o `../docs/tecnica/01` §11.5 e o `02` §11 que o põem no HND (prevalece o bloco, `specs/01` §5), com a consequência escrita — a coluna `resumed_at` nasce e ninguém a escreve aqui; e os *callbacks* são verificados pelo **HND** e não pelo GWY, contra o `../docs/tecnica/08` §3.6, porque o `secret` é por bot e logo por *tenant*, e o GWY é o único ponto sem contexto de *tenant*. **Não há tabela de fila de espelho**, e é decisão: o §14 pede uma fila que reconcilie por `wamid`, e isso é uma fila BullMQ com `jobId` derivado dele. **O `setBotMuted` não é executável** — `kamba_app` não tem `UPDATE (mode)` (revisão `0009`) e as transições são do KAM-018 —, a revisão `0011` **não** concede o privilégio, e a caixa do critério fica vazia. **Duas correcções que o próprio *gate* 3b apanhou ao conferir esta emenda:** dar domínio ao nome **nu** `tipo` (no `HumanEvent`) fez o *gate* recusar o `CHECK` de `evt_subscricoes.tipo` da revisão `0005` e declarar mortas duas extensões de `contact_endpoints.tipo` — os dois domínios desta secção passam a ser **qualificados** (`MirrorMessage.direccao`, `HumanEvent.acontecimento`), que é a regra que a emenda 1.14 escreveu para nomes genéricos e que esta emenda quase repetiu; e o `PRIMARY KEY` entre acentos graves do §3.14 estava a colher «PRIMARY» e «KEY» para os nomes conhecidos do *gate* — a classe da «persona» do KAM-014 —, pelo que passa a guilhemés. O `tenant_channels.token_ref` **sai** de `canon/extensoes.yaml` (26 extensões, eram 27): o `token_ref` é agora nome do §3.15 e o lint recusa uma extensão que o dicionário já cobre. | Equipa KAMBÁ |
