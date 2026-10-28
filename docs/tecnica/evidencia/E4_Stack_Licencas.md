# 04 - Stack, licenças e custos: verificação em fontes primárias

**Data da verificação:** 8 de Outubro de 2026.
**Método:** `gh api` (metadados de repositórios, releases, ficheiros LICENSE lidos na íntegra), PyPI/npm JSON, páginas oficiais de documentação e preços (WebFetch), pesquisa web apenas como indício.
**Contexto:** plataforma SaaS multi-tenant de comércio conversacional (WhatsApp) com agentes de IA, operada como serviço comercial para terceiros (PMEs em Angola). "SaaS multi-tenant OK?" significa: podemos executar a ferramenta como parte do nosso serviço pago a terceiros, sem pagar licença, sem expor a ferramenta (ou o seu editor) aos tenants como produto.

**Legenda de estado:** CONFIRMADO = lido no ficheiro/página primária nesta sessão. INDÍCIO = fonte secundária, resumo de fetch não corroborado, ou inferência directa de texto primário. NÃO VERIFICADO = não consegui confirmar; tratar como hipótese.

**Nota de método:** as páginas de preços da OpenAI e da Google foram lidas através do WebFetch (resumo por modelo pequeno), não em HTML bruto. Os valores são consistentes entre duas leituras (OpenAI) mas devem ser revalidados no dashboard antes de fixar preços ao cliente. A página da Anthropic veio em markdown bruto.

---

## 1. Tabela principal

| Ferramenta | Versão estável / data | Licença (SPDX e nota) | SaaS multi-tenant OK? | Maturidade (manutenção, estrelas) | Risco | Fonte (estado) |
|---|---|---|---|---|---|---|
| **Medusa v2** | v2.21.2, 2026-09-28 | MIT para o repo, **excepto Enterprise Edition (RBAC e SSO/OIDC)**, proprietário desde 2026-08-11. SPDX do GitHub: NOASSERTION. **Precisão do KAM-041 (2026-10-27):** o `package.json` publicado declara `"license": "SEE LICENSE IN LICENSE"` — já não `MIT` — desde a **2.19.0** (2026-08-13); a **2.18.0** (2026-07-23) é a última a declarar `MIT`. O acto de licenciamento é de 2026-08-11 (PR #16110) e **não é retroactivo**: as versões anteriores mantêm os termos originais. | SIM no core MIT. NÃO usar os caminhos EE (RBAC, `auth-oidc`) sem acordo comercial. **Correcção do KAM-041:** `@medusajs/policies` **não existe no npm** (`policies` é um directório do `@medusajs/framework`); e `@medusajs/rbac` e `@medusajs/auth-oidc` são `dependencies` **directas** do `@medusajs/medusa`, pelo que instalam-se sempre — o que a licença condiciona é **activar** a *feature flag* (`MEDUSA_FF_RBAC`, `MEDUSA_FF_RBAC_FILTER_FIELDS`, ambas `default_val: false`), não possuir o código. | 36,7k estrelas, releases quinzenais, push diário | MÉDIO: mudança de licença recente (open core a deslizar); RBAC/SSO do admin passam a ser pagos | github.com/medusajs/medusa/blob/develop/LICENSE e ENTERPRISE-LICENSE.md (CONFIRMADO); `registry.npmjs.org/@medusajs/medusa/{2.18.0,2.19.0,2.21.2}` e o `package-lock.json` do spike (CONFIRMADO, `../../spikes/KAM-041-medusa.md` §7.4 e §7.5) |
| **Mercur** (marketplace sobre Medusa) | v2.3.7, 2026-10-08 (v2.0.0 em 2026-03-18) | MIT (Copyright 2025 Rigby) | SIM (MIT). Requer `@medusajs/medusa >= 2.21.0`. | 1,8k estrelas, ~14 contribuidores no 1.º ano de v2, 10 issues abertas, cadência de várias releases/mês | MÉDIO-ALTO: jovem; fix de segurança "cross-seller authorization gaps in the vendor API" a 2026-10-08; só payout Stripe Connect | github.com/mercurjs/mercur (CONFIRMADO) |
| **Chatwoot** | v4.18.0, 2026-09-18 | MIT ("MIT Expat") fora de `enterprise/`; `enterprise/` sob licença proprietária (subscrição + nº de lugares) | SIM com core MIT. NÃO usar código `enterprise/` em produção sem subscrição. | 37,6k estrelas, release mensal, push diário | MÉDIO: o que é EE cresce (custom roles, SAML, SLA, captain, audit); marca branca é EE | github.com/chatwoot/chatwoot/blob/develop/LICENSE e enterprise/LICENSE (CONFIRMADO) |
| **Typebot** | v3.19.0, 2026-09-14 | **FSL-1.1-Apache-2.0** (Functional Source License). README ainda mostra badge AGPLv3 (desactualizado; o ficheiro LICENSE é FSL desde 2024-09-25). | **RESTRITO.** Uso interno OK; "Competing Use" proibido. Não oferecer o editor/runtime a tenants. | 10,5k estrelas, push 2026-10-07 | ALTO se usado como motor de fluxos para clientes; BAIXO para fluxos internos nossos | github.com/baptisteArno/typebot.io/blob/main/LICENSE (CONFIRMADO) |
| **n8n** | n8n@2.42.5, 2026-10-08 | **Sustainable Use License 1.0** (+ ficheiros `.ee.` sob licença Enterprise) | **NÃO** para tenants. Só uso interno / não comercial. | 206,7k estrelas | ALTO se tenants configurarem workflows; baixo para automações internas | github.com/n8n-io/n8n/blob/master/LICENSE.md (CONFIRMADO); FAQ docs.n8n.io (INDÍCIO via resumo) |
| **Dify** | 1.17.1, 2026-09-10 | Apache-2.0 **modificada**: proíbe operar ambiente multi-tenant (1 tenant = 1 workspace) sem autorização escrita; proíbe remover logo no frontend `web/` | **NÃO** (cláusula 1.a expressa). | 157,9k estrelas | Bloqueante para SaaS multi-tenant | github.com/langgenius/dify/blob/main/LICENSE (CONFIRMADO) |
| **LangGraph** (biblioteca) | langgraph **1.2.17** (no fecho do AGR desde o KAM-027; era 1.2.14 de 2026-10-06); `langgraph-checkpoint` 4.3.0; `langgraph-prebuilt` 1.1.1 e `langgraph-sdk` 0.4.9, que ele arrasta; langgraphjs 1.4.21 | MIT (PyPI e repo) nos **quatro** pacotes Python | SIM, sem restrições | 42,9k estrelas, releases semanais | BAIXO | github.com/langchain-ai/langgraph; pypi.org/pypi/langgraph/json e o `METADATA` instalado (CONFIRMADO, relido em 2026-10-25) |
| **LangGraph checkpointer Postgres** | `langgraph-checkpoint-postgres` 3.1.2 (2026-08-07) | MIT **o pacote**; o fecho **não** — exige `psycopg` e `psycopg-pool`, LGPL-3.0-only | **NÃO** | — | — | pypi.org/pypi/langgraph-checkpoint-postgres/3.1.2/json, campo `requires_dist` (CONFIRMADO, medido em 2026-10-25) |
| **LangGraph Server / "LangSmith Deployment"** (antigo LangGraph Platform) | `langgraph-api` 0.15.4 (2026-10-08) | **Elastic-2.0 (ELv2)** no pacote `langgraph-api` e `langgraph-runtime-inmem`; Standalone Server exige `LANGSMITH_API_KEY` + `LANGGRAPH_CLOUD_LICENSE_KEY` e egress para `beacon.langchain.com` | **NÃO usar** como base do serviço. Usar só a biblioteca MIT. | n/a | ALTO (licença + dependência + telemetria de licença) | pypi.org/pypi/langgraph-api/json (CONFIRMADO); docs.langchain.com/langsmith/deploy-standalone-server (CONFIRMADO, resumo) |
| **LiteLLM** (proxy) | v1.104.2, 2026-10-08 | MIT fora de `enterprise/`; `enterprise/` proprietário (subscrição) | SIM com a parte MIT (chaves virtuais, equipas, budgets, rate limits, spend tracking, fallbacks, Prometheus segundo a página de preços). SSO/SCIM/JWT-OIDC/audit logs/secret managers/key rotation/org-admins são Enterprise. | 60,4k estrelas, push horário | **ALTO operacional:** incidente de supply chain em 2026-03-24 (PyPI 1.82.7 e 1.82.8 maliciosas) | github.com/BerriAI/litellm/blob/main/LICENSE e enterprise/LICENSE.md; litellm.ai/pricing (CONFIRMADO); docs.litellm.ai/blog/security-update-march-2026 (CONFIRMADO, resumo) |
| **Langfuse** (self-host) | v4.55.0, 2026-10-08 (SDK Python 4.17.0). Docs de self-host já em **v4**. | MIT fora de `ee/`, `web/src/ee/`, `worker/src/ee/` (Enterprise License). Copyright 2023-2026 **ClickHouse, Inc.** | SIM no core MIT. EE (docs): Organization Creators, Instance Management API, UI Customization. | 35,5k estrelas; **adquirido pela ClickHouse (anúncio 2026-01-16)** | MÉDIO: 4 serviços de estado (Postgres, ClickHouse, Redis/Valkey, S3); risco de mais funções a migrarem para EE | github.com/langfuse/langfuse/blob/main/LICENSE; langfuse.com/self-hosting (CONFIRMADO); aquisição: langfuse.com/blog/announcing-acquisition (INDÍCIO via pesquisa; README do repo confirma "since January 2026 we're part of ClickHouse") |
| **PostgreSQL** | 18.6 (actual); 17.11; 16.15; 15.19; 14.24 (EOL 2026-11-12). PG 19 em Beta 4. | PostgreSQL License | SIM | Suporte 5 anos por major; 18 até 2030-11-14 | BAIXO | postgresql.org/support/versioning (CONFIRMADO) |
| **pgvector** | v0.8.7, 2026-10-01 | PostgreSQL License (texto lido) | SIM | 23,3k estrelas; v0.8.7 corrige buffer overflow na construção de índice IVFFlat | BAIXO; actualizar para 0.8.7 | github.com/pgvector/pgvector (CONFIRMADO) |
| **pg_trgm** | contrib do PostgreSQL (acompanha o major) | PostgreSQL License | SIM | n/a | BAIXO | inferido do projecto PostgreSQL (INDÍCIO; doc do contrib não lida nesta sessão) |
| **BullMQ** | 6.3.11, 2026-10-01 (npm) | MIT | SIM | 9,5k estrelas, releases semanais | BAIXO; exige Redis persistente (AOF) | github.com/taskforcesh/bullmq; registry.npmjs.org (CONFIRMADO). Garantias de entrega: NÃO VERIFICADO (docs não lidas; ver 3.8) |
| **Temporal** | v1.32.0, 2026-09-11 | MIT | SIM | 23,5k estrelas | BAIXO licença, MÉDIO operação (cluster) | github.com/temporalio/temporal (CONFIRMADO) |
| **DBOS** | dbos-transact-py 3.2.0 (2026-09-29); dbos-transact-ts v5.2 (2026-09-29) | MIT | SIM | 1,6k / 1,4k estrelas | BAIXO (só Postgres, biblioteca) | github.com/dbos-inc/* (CONFIRMADO) |
| **Restate** | v1.7.13, 2026-10-01 | **BUSL-1.1**; Change License Apache-2.0 após 4 anos. Additional Use Grant proíbe "Public Restate Platform Service" | SIM se os nossos serviços forem os únicos registados; NÃO se tenants registarem os seus endpoints | 4,5k estrelas | MÉDIO (BUSL) | github.com/restatedev/restate/blob/main/LICENSE (CONFIRMADO) |
| **MinIO** | Última release **RELEASE.2025-10-15** (2025-10-16). **Repo arquivado em 2026-04-24/25.** | AGPL-3.0 | Só por AGPL (rede = obrigação de código se modificado). **Projecto morto**: sem binários, sem manutenção. | 61,3k estrelas, arquivado | **ALTO: DESCONTINUADO** | github.com/minio/minio (CONFIRMADO: `archived: true`, README "THIS REPOSITORY IS NO LONGER MAINTAINED", source-only) |
| **SeaweedFS** | 4.48, 2026-09-28 | Apache-2.0 | SIM | 35,3k estrelas | BAIXO-MÉDIO | github.com/seaweedfs/seaweedfs (CONFIRMADO) |
| **Garage** | v2.4.1 (tag; branch `main-v2`) | AGPL-3.0 | Possível (AGPL: cuidado se modificar) | 4,7k estrelas | MÉDIO (AGPL; semântica S3 parcial: NÃO VERIFICADO nesta sessão) | github.com/deuxfleurs-org/garage (CONFIRMADO licença/tag) |
| **RustFS** | 1.0.1, 2026-10-03 (1.0.0 em 2026-09-16) | Apache-2.0 | SIM | 34,6k estrelas, mas 1.0 com 3 semanas | MÉDIO-ALTO (imaturo) | github.com/rustfs/rustfs (CONFIRMADO) |
| **Nominatim** | v5.3.2, 2026-04-19 | GPL-3.0 | SIM como serviço separado (GPL, não AGPL; não distribuímos). Não modificar e distribuir. | 4,5k estrelas, push 2026-09-30 | BAIXO | github.com/osm-search/Nominatim (CONFIRMADO) |
| **Valhalla** | 3.9.1, 2026-10-06 | MIT (COPYING lido) | SIM | 6,3k estrelas | BAIXO | github.com/valhalla/valhalla (CONFIRMADO) |
| **Hono** | 4.13.13 estável, 2026-10-04 (npm). **v5.0.0-rc.0 em 2026-10-08.** `@hono/node-server` 2.1.4 | MIT | SIM | 32,5k estrelas | BAIXO; não adoptar o RC v5 em produção | github.com/honojs/hono; npm (CONFIRMADO) |
| **Keycloak** | 26.8.0, 2026-10-01 | Apache-2.0 | SIM | 37,2k estrelas | BAIXO licença, MÉDIO operação (JVM) | github.com/keycloak/keycloak (CONFIRMADO) |
| **ClickHouse** | v26.9.13.15-stable, 2026-10-08 | Apache-2.0 | SIM | 50,3k estrelas | BAIXO | github.com/ClickHouse/ClickHouse (CONFIRMADO) |
| **Meilisearch** | v1.54.3, 2026-10-01 | `MIT AND BUSL-1.1`: MIT no geral; ficheiros "Enterprise Edition" em `enterprise_editions` sob BUSL (uso em produção exige licença comercial) | SIM no MIT. Não usar módulos EE. | 59,5k estrelas | BAIXO-MÉDIO | github.com/meilisearch/meilisearch/blob/main/LICENSE e LICENSE-EE (CONFIRMADO) |
| **HashiCorp Vault** | v2.1.2, 2026-10-07 | **BUSL-1.1** (licensor IBM). Additional Use Grant: produção OK desde que não ofereçamos o Vault a terceiros, em modo hospedado/embebido, de forma competitiva. Change License MPL-2.0 após 4 anos. | OK para uso interno (não vendemos um "Vault"); não é open source OSI | 36,4k estrelas | MÉDIO (licença não OSI) | github.com/hashicorp/vault/blob/main/LICENSE (CONFIRMADO) |
| **OpenBao** | v2.7.1, 2026-10-01 | MPL-2.0 | SIM | 8,4k estrelas | BAIXO-MÉDIO | github.com/openbao/openbao (CONFIRMADO) |
| **Doppler** (SaaS) | n/a | Proprietário (SaaS) | SIM (é serviço pago nosso, não redistribuído) | n/a | MÉDIO (dependência de terceiro para segredos) | doppler.com/pricing (CONFIRMADO, resumo) |

---

## 2. Detalhe por ferramenta (o que mudou, o que restringe)

### 2.1 Medusa v2 e Mercur

**Medusa (CONFIRMADO).** O ficheiro `LICENSE` diz: "Except for the Enterprise Edition materials identified in ENTERPRISE-LICENSE.md, the repository is licensed under the MIT License". O `ENTERPRISE-LICENSE.md` foi introduzido em **2026-08-11** (commit "chore: update license (#16110)"). Materiais EE: **RBAC** (módulo `rbac`, `policies`, rotas `admin/rbac`, `admin/users/[id]/roles`, dashboard `routes/roles` e `routes/policies`) e **SSO/OIDC** (`providers/auth-oidc`). O texto avisa que "Enabling any Enterprise feature flag constitutes a representation that you hold a valid commercial agreement" e que as versões anteriores continuam MIT. Ficam MIT: autenticação genérica, registo de auth providers, gestão genérica de utilizadores e convites.
Implicação: o admin do Medusa deve ser usado só pela nossa equipa/operador; permissões por tenant/vendedor têm de ser implementadas por nós (ou por Mercur). Não activar feature flags `rbac`.
Multi-tenancy nativo do Medusa (várias lojas isoladas por instância): NÃO VERIFICADO (a página de arquitectura que li não cobre o tema). Assumir 1 instância por "marketplace" e vendedores como entidade lógica via Mercur.

**Mercur (CONFIRMADO no repo).** MIT, v2.3.7. Linha temporal: v1.0.0 em 2025-06-23, v1.4.1 em 2025-10-29, **v2.0.0 em 2026-03-18**, v2.1.0 2026-04-28, v2.2.0 2026-07-09, v2.3.x de Agosto a Outubro. `docs/PRODUCT.md` do repo descreve, e o código tem módulos correspondentes (`seller`, `commission`, `offer`, `payout`, `review`, `product-attribute`, `product-edit`, `promotion-cost`, `custom-fields`):
- vendedores com estados (`pending_approval`, `open`, `suspended`, `terminated`), membros N:N, fecho agendado;
- comissões por produto/tipo/colecção/categoria/vendedor (fixas ou percentuais);
- **order splitting**: carrinho multi-vendedor dividido em encomendas por vendedor, com Order Group;
- produtos mestre + ofertas por vendedor (preço, stock, envio por oferta);
- pipeline de aprovação de alterações de produto;
- payouts: interface plugável, **só `payout-stripe-connect` incluído** (`packages/providers` contém apenas esse).

Avaliação: suficiente em funcionalidade para multi-vendor B2C/B2B. Reservas concretas: (1) o commit mais recente (2026-10-08) é "fix(vendor): close cross-seller authorization gaps in the vendor API", ou seja, havia falhas de isolamento entre vendedores até hoje, o que é a propriedade que mais nos interessa; exige revisão de segurança própria e testes de isolamento; (2) Stripe Connect como único payout; a disponibilidade do Stripe para Angola NÃO VERIFICADA, portanto assumir que é preciso um payout provider próprio; (3) o README refere "Mercur Enterprise" com módulos proprietários (EAN matching, Buy Box, KYC, multi-channel sync): INDÍCIO (resumo de fetch). O número de contribuidores é pequeno (~14 na primeira página da API). O doc 08 cita "~1,6k★": agora 1,8k.

### 2.2 Chatwoot

- **Licença (CONFIRMADO):** MIT fora de `enterprise/`. `enterprise/LICENSE` diz que o software "may only be used in production" com subscrição e "valid Chatwoot Enterprise License for the correct number of user seats"; permite modificar para desenvolvimento e teste.
- **O que é EE:** a documentação lista Whitelabeling, SLA Management, Audit Logs e Agent Capacity Management; preço "from $19 per agent per month" (CONFIRMADO, resumo de fetch). O código `enterprise/app/models` contém também `custom_role`, `account_saml_settings`, `sla_policy`, `captain`, `copilot_*`, `audit_log`, `inbox_capacity_limit` (CONFIRMADO por listagem). O doc 08 diz que o Captain é enterprise: consistente.
- **Agent Bot API (CONFIRMADO no código):** modelo `AgentBot` com `bot_type` apenas `webhook`, `outgoing_url`, `secret`, `access_token`; `account_id` nulo = bot global acessível a todas as contas (`accessible_to`); `agent_bot_inboxes` liga bot a caixas. O bot responde via API de mensagens com o seu token. Existe `assignee_agent_bot_id` em conversas.
- **Platform API (CONFIRMADO):** controllers `accounts`, `users`, `account_users`, `agent_bots`, `email_channel_migrations`. Documentação: Platform APIs "manage Chatwoot installations at the admin level"; operam só sobre recursos criados pela mesma chave de API ou com permissões explícitas. Multi-conta: SIM (1 conta por PME confirmável).
- **WhatsApp Cloud API e coexistência (CONFIRMADO no código):** `embedded_signup_service.rb`, `useWhatsappEmbeddedSignup.js` com `is_coexistence`, `webhook_setup_service.rb` com `is_coexistence`, tratamento de mensagens de coexistência em `whatsapp_events_job.rb`. Self-host precisa de app Meta tipo Business, permissões `whatsapp_business_management`, `whatsapp_business_messaging`, `business_management` e de 3 configurações de super-admin: `WHATSAPP_APP_ID`, `WHATSAPP_CONFIGURATION_ID`, `WHATSAPP_APP_SECRET` (CONFIRMADO, docs).
- **Multi-tenant com uma só app Meta:** o issue #13426 (que o doc 08 cita como "em aberto") foi **fechado como concluído em 2026-02-03**. Um comentário do autor do fecho refere que o PR #13279 permite sobrepor o webhook por WABA via `subscribed_apps`, ficando cada WABA encaminhado para a sua caixa (INDÍCIO: comentário no issue, não testado).
- **Limites do self-host:** não encontrei limite de contas/agentes na parte MIT; o limite é de capacidade (Rails + Sidekiq + Postgres + Redis). Marca branca, SLA, audit logs, SAML e custom roles exigem subscrição.
- Risco adicional: Embedded Signup **v2 será descontinuado em 2026-10-15** (doc Meta, CONFIRMADO). Verificar que a versão do Chatwoot usada fala Embedded Signup v4 (NÃO VERIFICADO).

### 2.3 Typebot

`LICENSE` = **FSL-1.1-Apache-2.0**, "Copyright 2023-2024 Typebot" (CONFIRMADO). Texto relevante:
- Permitted Purpose = "any purpose other than a Competing Use".
- Competing Use = "making the Software available to others in a commercial product or service that: 1. substitutes for the Software; 2. substitutes for any other product or service we offer using the Software ...; or 3. offers the same or substantially similar functionality as the Software."
- Permitido expressamente: "for your internal use and access" e "in connection with professional services that you provide to a licensee using the Software in accordance with these Terms".
- Cada versão converte-se em **Apache-2.0 ao 2.º aniversário** da sua disponibilização.

A documentação (resumo de fetch, CONFIRMADO em substância) diz: pode correr instâncias para uso interno e construir bots para clientes como freelancer; não pode comercializar acesso à instância self-hosted, oferecer hosting de Typebot, nem integrar o editor em produtos concorrentes.
Leitura prática: usar Typebot como **ferramenta interna nossa** (onboarding da PME que nós desenhamos, captura de morada/pin) é permitido. Oferecer aos tenants um construtor de fluxos, ou o runtime como parte do produto vendido, aproxima-se de "Competing Use" (terceira alínea é ampla). O doc 08 diz "seguro para uso interno/comercial": **a parte "comercial" é demasiado optimista**. Versões com mais de 2 anos (anteriores a ~Out/2024) já estão disponíveis sob Apache-2.0, mas são antigas. Qualquer dúvida: pedir confirmação escrita ao licenciante.

### 2.4 n8n

LICENSE.md (CONFIRMADO): Sustainable Use License 1.0: "You may use or modify the software only for your own internal business purposes or for non-commercial or personal use. You may distribute the software or provide it to others only if you do so free of charge for non-commercial purposes." Ficheiros `.ee.` exigem licença Enterprise.
FAQ oficial (INDÍCIO, resumo): proibido "host n8n as a service and allow your clients to build workflows" e white-label; permitido cobrar criação/manutenção de workflows e consultoria; um SaaS em que o n8n é backend invisível é aceitável **desde que os utilizadores finais não configurem workflows** pela UI ou API do nosso produto; para embeber, existe o acordo pago "n8n Embed".
Conclusão: n8n só para automações internas de back-office (relatórios, réguas nossas). Nunca exposto a tenants.

### 2.5 Dify

Cláusula 1.a (CONFIRMADO): "Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment", com tenant = workspace. Cláusula 1.b: não remover LOGO/copyright no frontend `web/`. Bloqueante, rejeição do doc 08 confirmada.

### 2.6 LangGraph, checkpointers, interrupt, Server

- Biblioteca `langgraph` e `langgraph-checkpoint`: MIT (PyPI). Monorepo `libs/` inclui `checkpoint-postgres`, `checkpoint-sqlite`, `sdk-py`, `sdk-js`, `cli`. Projecto muito activo (releases semanais; 42,9k estrelas). O repo `open-agent-platform` da mesma organização está **arquivado** (2026-02-25): não depender dele.
- **Correcção (KAM-026, 2026-10-25): o `langgraph-checkpoint-postgres` estava aqui como «MIT, SIM, sem restrições», e isso olhava o pacote e não o fecho.** O `requires_dist` dele exige `psycopg >= 3.2.0` e `psycopg-pool >= 3.2.0`, **ambos LGPL-3.0-only** — e o `ci/licenses.yaml` nega o prefixo `LGPL`, como o `db/requirements/migrations.in` já tinha medido e escrito no KAM-003. O pacote está agora em `tools/blocklist.yaml`, e o KAM-026 escreve o *checkpointer* sobre `pg8000`, usando só a interface `BaseCheckpointSaver` e o serializador do `langgraph-checkpoint` 4.3.0. **O fecho desse, esse sim, está limpo:** 35 pacotes, classificados pelo avaliador do *gate* 11 contra o `ci/licenses.yaml` — 35 permitidas, 0 fora. A lição para quem usar esta tabela: uma licença de pacote não é a licença do fecho.
- `interrupt()` (CONFIRMADO, docs): exige checkpointer durável e `thread_id`; retoma com `Command(resume=...)`; **o nó reinicia desde o início** na retoma, por isso efeitos secundários antes do `interrupt()` têm de ser idempotentes. Isto afecta directamente o desenho do handoff para Chatwoot (não criar mensagem/encomenda antes do `interrupt()` sem chave de idempotência).
- **LangGraph Platform foi renomeado "LangSmith Deployment"** (README do repo já usa o nome novo; data Out/2025 vem de pesquisa: INDÍCIO). Self-host com control plane exige plano Enterprise; o Standalone Server exige licença LangSmith (`LANGGRAPH_CLOUD_LICENSE_KEY`) e verificação em `beacon.langchain.com`. O pacote `langgraph-api` é **Elastic-2.0** (PyPI). Preços por nó executado e plano Self-Hosted Lite (1M nós): INDÍCIO (pesquisa), NÃO VERIFICADO em página oficial.
- Decisão: LangGraph como biblioteca MIT dentro do nosso serviço, checkpointer Postgres nosso. Não usar Agent Server.
- **Actualização do fecho em 2026-10-25 (KAM-027), CONFIRMADO.** A biblioteca entrou no fecho de *runtime* do AGR na versão **1.2.17** — este anexo tinha-a em 1.2.14, e é por essa versão que o `ci/supply-chain/licencas.yaml` a registava. O `license_expression` do PyPI e o `METADATA` do pacote instalado dizem **MIT** para os três que entram: `langgraph` 1.2.17, `langgraph-prebuilt` 1.1.1 e `langgraph-sdk` 0.4.9. Todas as transitivas deles já estavam fixadas com *hash* pelo KAM-026 (`langchain-core`, `langgraph-checkpoint`, `pydantic`, `xxhash`, `httpx`, `langchain-protocol`, `orjson`, `websockets`), pelo que o fecho passa de 43 para 46 pacotes e não de 43 para muitos.
- **O `langgraph-sdk` é o cliente do Server, e entra sem ser uma excepção ao ADR-002.** É dependência declarada do `langgraph`, e num fecho `--require-hashes --no-deps` instala-se o que está listado. O que o ADR-002 veda é o **Server** (`langgraph-api`, Elastic-2.0, na lista de bloqueio) e o egresso para `beacon.langchain.com` — que não está no `services/agr/egress.yaml`, com `por_omissao: negar` e `destinos: []`. Um cliente sem servidor e sem caminho de saída não fala com ninguém; e desde o KAM-027 o arranque do AGR falha também se uma distribuição da lista de bloqueio estiver **instalada**, e não só importável.
- **Correcção de uma lacuna deste anexo, encontrada no KAM-027.** O `psycopg2-binary` é LGPL como o `psycopg`, as duas listas de requisitos recusavam-no pelo nome em prosa, e o `tools/blocklist.yaml` **não o tinha** — as entradas `psycopg` são `match: exact` e não lhe batem. Passou a ter. Encontrado pelo teste de paridade entre a guarda de *runtime* do AGR e o `lint_arch`: os dois controlos estavam calados sobre ele.

### 2.7 LiteLLM

- Licença (CONFIRMADO): MIT fora de `enterprise/`; `enterprise/LICENSE.md` exige subscrição para produção.
- OSS segundo litellm.ai/pricing (CONFIRMADO, resumo): 100+ fornecedores, virtual keys/users/teams, spend tracking, budgets e rate limits, fallbacks, logging, Prometheus. Enterprise: SSO+SCIM, OIDC/JWT, audit logs, secret managers e key rotation, org & team admins, multi-region control plane. Uma fonte secundária diz que SSO é grátis até 5 utilizadores no OSS: INDÍCIO. Outra fonte secundária coloca Prometheus no Enterprise, contradizendo a página oficial: prevalece a oficial, validar no deploy.
- **Incidente (CONFIRMADO, post oficial):** em 2026-03-24 as versões PyPI **1.82.7 e 1.82.8** foram publicadas com malware que recolhia credenciais (SSH, cloud, K8s, env vars). Estiveram acessíveis cerca de 40 minutos. Remediação: v1.83.0+ via novo pipeline CI/CD, imagens Docker assinadas com cosign, auditoria v1.78.0-v1.82.6. O LiteLLM guarda as chaves dos fornecedores de LLM: é o componente de maior superfície de ataque do stack.
- Para o nosso caso (virtual key por tenant e ledger de custo) a parte MIT chega. Tratar o proxy como componente crítico: imagem Docker com digest fixo + verificação cosign, sem `pip install` na build, rede isolada, rotação de chaves.

### 2.8 Langfuse

- MIT fora de `ee/`. A EE License permite desenvolvimento e teste, produção só com acordo. Docs de self-host (v4): Postgres, **ClickHouse**, Redis/Valkey, S3/blob + containers Web e Worker (CONFIRMADO). Funções "(EE)" nas docs: Organization Creators, Instance Management API, UI Customization.
- Mudança: o doc 08 refere "Langfuse self-host (core MIT)": mantém-se, mas a versão em vigor é **v4.x** (não v3), e o copyright é agora ClickHouse, Inc. A ClickHouse anunciou "no planned changes to licensing" (INDÍCIO via pesquisa/README).
- Custo operacional: 4 serviços de estado só para observabilidade. Em fase piloto, considerar Langfuse Cloud ou adiar; os traces têm dados pessoais (conversas) e residência de dados é matéria de conformidade.

### 2.9 Postgres, pgvector, pg_trgm

- Fixar **PostgreSQL 18.6** (o doc 11 diz Postgres 16). 16.15 continua suportado até 2028-11-09; 14 chega ao fim a 2026-11-12.
- pgvector 0.8.7 (suporta Postgres 13+; CONFIRMADO no README). Limites do README: índices `vector` até 2.000 dimensões, `halfvec` até 4.000, `bit` até 64.000, `sparsevec` até 1.000 não-zeros. **Com índices aproximados, o filtro é aplicado depois do índice** (com `hnsw.ef_search` 40 e um filtro que apanha 10% das linhas, só ~4 resultados em média); desde 0.8.0 existem `iterative scans` (`hnsw.iterative_scan`). Isto interessa a multi-tenant: filtro por `tenant_id` com HNSW global dá resultados escassos; usar iterative scan, particionar por tenant ou índice parcial. Limites de escala (nº de vectores, RAM do índice HNSW): NÃO VERIFICADO com número; o README só recomenda `halfvec` e quantização binária para reduzir o working set.
- `pg_trgm` é módulo contrib; não tem versão própria nem licença separada (INDÍCIO).

### 2.10 BullMQ e alternativas de execução durável

- BullMQ 6.3.11 (MIT), sobre Redis. Existem agora implementações irmãs `rs` (Rust, 1.3.5) e `py` (3.3.1) no mesmo repo. Garantias: a literatura habitual é at-least-once com jobs stalled re-entregues, mas **não li a documentação nesta sessão**: NÃO VERIFICADO. Desenhar handlers idempotentes (de qualquer forma exigido pelo `interrupt()` do LangGraph).
- **Temporal** v1.32.0 (MIT): execução durável completa, mas exige cluster (Postgres/Cassandra + serviços). **DBOS** (MIT): biblioteca que usa só Postgres para workflows duráveis, a opção mais barata se já temos Postgres. **Restate** v1.7.13 (BUSL-1.1): o Additional Use Grant permite produção desde que não ofereçamos um "Public Restate Platform Service" onde terceiros registam os seus endpoints; cenário nosso (apenas serviços nossos) está expressamente permitido (CONFIRMADO no texto). Para o piloto, BullMQ + idempotência chega; DBOS é o próximo passo natural.

### 2.11 MinIO (descontinuado) e alternativas

CONFIRMADO: `gh api` devolve `archived: true`, `pushed_at 2026-04-24`; README: "THIS REPOSITORY IS NO LONGER MAINTAINED", edição community "distributed as source code only", sem binários pré-compilados, e redirecciona para AIStor (Free/Enterprise, comerciais). Últimos commits: 2025-12-03 "README maintenance mode", 2026-01-06 e 2026-02-12 só de README. Última release: RELEASE.2025-10-15T17-29-55Z.
Alternativas verificadas:
- **SeaweedFS 4.48** (Apache-2.0, 35,3k estrelas, release 2026-09-28): a opção mais madura com licença permissiva.
- **Garage v2.4.1** (AGPL-3.0): leve, bom para self-host pequeno; AGPL só obriga se modificarmos e expusermos.
- **RustFS 1.0.1** (Apache-2.0): 1.0 só desde 2026-09-16, evitar no piloto.
- **Versity GW v1.8.0** (Apache-2.0): gateway S3, não é armazenamento próprio.
- S3 gerido (Backblaze/Cloudflare R2/AWS): não verifiquei preços nem disponibilidade para Angola; NÃO VERIFICADO.
Recomendação: abstrair por interface S3 e começar com SeaweedFS ou um S3 gerido; **retirar MinIO do desenho** (docs 10 e 11 usam-no para WAL/PITR, fotos e Langfuse).

### 2.12 Nominatim e Valhalla (extracto de Angola)

- Extracto Geofabrik `angola-latest.osm.pbf`: **81 MB**, dados OSM até 2026-10-07T20:20:35Z, actualizado diariamente (CONFIRMADO via curl à página; `angola-261007.osm.pbf`). Dados OSM sob ODbL (atribuição obrigatória; nota de conhecimento geral, licença não lida na página).
- **Nominatim** v5.3.2, GPL-3.0. Requisitos oficiais (CONFIRMADO, docs): mínimo 2 GB RAM; planeta 128 GB RAM / 1 TB disco NVMe; PostgreSQL 12+ (13+ preferível), PostGIS 3.0+ (3.2+), Python 3.9+, osm2pgsql 1.8+. Para 81 MB o mínimo de 2 GB é um limite de instalação; dimensionar com folga (4-8 GB) até medir. Dimensionamento real do import de Angola: NÃO VERIFICADO.
- **Valhalla** 3.9.1, MIT. Constrói tiles a partir do mesmo PBF; requisitos de RAM/disco para Angola: NÃO VERIFICADO. A qualidade da geocodificação de moradas angolanas (bairros, ruas sem nome) é questão de dados OSM, não de software; o desenho "pin de localização" do doc 08 é prudente.
- GPL-3.0 do Nominatim: usado como serviço isolado, sem distribuição, não contamina o nosso código (não é AGPL). Não modificar e distribuir sem cumprir GPL.

### 2.13 Hono, Keycloak, ClickHouse, Meilisearch

- **Hono** 4.13.13 estável. O `v5.0.0-rc.0` saiu hoje (2026-10-08): fixar 4.x. `@hono/node-server` 2.1.4 já em major 2.
- **Keycloak** 26.8.0 (Apache-2.0), release 2026-10-01. Multi-tenancy por realms ou Organizations: não verifiquei a documentação nesta sessão (NÃO VERIFICADO); validar antes de decidir realms-por-tenant (custo de memória) vs organizations.
- **ClickHouse** v26.9 stable (Apache-2.0); nomenclatura passou a `YY.M`. Só entra se usado pelo Langfuse ou para analytics próprios.
- **Meilisearch** 1.54.3: o ficheiro `LICENSE` diz `SPDX-License-Identifier: MIT AND BUSL-1.1`. O LICENSE-EE tem um Additional Use Grant só para não-produção: "Production use of the Licensed Work requires a commercial license agreement". Basta não usar módulos "Enterprise Edition". Alerta: aparece "Copyright (c) 2019-2025 Meili SAS" e o repo agora inclui `crates/` e `enterprise_editions`; verificar na build que não activamos funções EE.

### 2.14 Segredos: Vault, OpenBao, Doppler

- **Vault v2.1.2 é BUSL-1.1** (IBM como licensor). Uso interno e produção são permitidos; proibido oferecer o Vault a terceiros "on a hosted or embedded basis in order to compete". Não somos concorrentes, mas a licença não é OSI e muda se o negócio evoluir.
- **OpenBao v2.7.1** (MPL-2.0): fork aberto do Vault; opção segura se queremos secrets engine self-hosted.
- **Doppler** (CONFIRMADO, resumo): Developer grátis para 3 utilizadores, depois $8/mês por utilizador (10 projectos, 50 service tokens, logs 3 dias); Team $21/mês por utilizador (SAML, RBAC, rotação automática, 250 projectos, 500 service tokens, logs 90 dias); custom roles/grupos/syncs são add-ons de $9/lugar. "AI agents and non-human identities ride free". Para equipa pequena inicial, Doppler Developer chega; atenção ao risco de depender de um SaaS externo para segredos críticos.

---

## 3. Custos de LLM e STT (consultados em 2026-10-08)

Preços em USD por 1M de tokens. "Cache" = cached input / cache hit.

### 3.1 Anthropic (CONFIRMADO, platform.claude.com/docs/en/about-claude/pricing, markdown bruto)

| Modelo | Input | Cache hit | Output | Notas |
|---|---|---|---|---|
| **Claude Haiku 5.5** (prompts <=100k) | 0,10 | 0,01 | 0,50 | >100k tokens: 0,50 / 0,05 / 2,50 |
| Claude Haiku 4.5 | 1,00 | 0,10 | 5,00 | |
| **Claude Sonnet 5.5** | 2,00 | 0,10 | 10,00 | cache hit a 0,05x |
| Claude Sonnet 5 | 2,00 | 0,20 | 10,00 | nota oficial: o preço de 2/10 "is now the standard price"; o aumento para 3/15 em 2026-09-01 **não** ocorrerá |
| Claude Sonnet 4.6 / 4.5 | 3,00 | 0,30 | 15,00 | |
| Claude Opus 5.5 | 4,00 | 0,20 | 20,00 | |
| Claude Opus 5 / 4.8 / 4.7 | 5,00 | 0,50 | 25,00 | |
| Claude Fable 5.1 / Mythos 5.1 | 10,00 | 0,25 | 50,00 | Mythos: acesso limitado |

Escrita de cache 5 min = 1,25x do input; 1 h = 2x. Batch API = -50%. **Atenção ao tokenizador:** "Claude 4.7 and later models ... produces approximately 30% more tokens for the same text" (aplica-se ao Haiku 5.5 e Sonnet 5.x), o que encarece o custo efectivo em português face à tabela. `inference_geo: "us"` = 1,1x.

### 3.2 OpenAI (CONFIRMADO em duas leituras do WebFetch de developers.openai.com/api/docs/pricing; tier Standard)

| Modelo | Input | Cached input | Output |
|---|---|---|---|
| gpt-6-luna | 0,10 | 0,01 | 0,50 |
| gpt-5.6-luna | 0,20 | 0,02 | 1,20 |
| gpt-5.6-terra | 2,00 | 0,20 | 12,00 |
| gpt-6.1-sol | 2,00 | 0,10 | 10,00 |
| gpt-6-sol | 2,00 | 0,20 | 10,00 |
| gpt-5.6-sol | 4,00 | 0,40 | 20,00 |
| gpt-5.5 | 5,00 | 0,50 | 30,00 |
| gpt-5.4-nano / -mini | 0,20 / 0,75 | 0,02 / 0,075 | 1,25 / 4,50 |
| gpt-5-nano / -mini | 0,05 / 0,25 | 0,005 / 0,025 | 0,40 / 2,00 |
| gpt-4.1-nano / -mini | 0,10 / 0,40 | 0,025 / 0,10 | 0,40 / 1,60 |
| gpt-4o-mini | 0,15 | 0,075 | 0,60 |

Os modelos do doc 08 (GPT-4.1-nano e GPT-4.1-mini) ainda estão listados, mas já não são a oferta barata de topo: gpt-6-luna custa o mesmo no input que o 4.1-nano e metade no input do 4.1-mini. Não vi na página indicação de datas de retirada dos 4.1 (NÃO VERIFICADO).
**STT/áudio OpenAI (mesma fonte):** gpt-transcribe $0,0045/min (novo); gpt-4o-transcribe ~$0,006/min; **gpt-4o-mini-transcribe ~$0,003/min**; Whisper $0,006/min; gpt-live-transcribe e gpt-realtime-whisper $0,017/min; gpt-realtime-2.1-mini texto 0,60/2,40 e áudio 10/20. TTS gpt-4o-mini-tts: $0,60 texto-in, $12 áudio-out por 1M.

### 3.3 Google Gemini (resumo de WebFetch de ai.google.dev/gemini-api/docs/pricing, tier pago; INDÍCIO-forte, revalidar)

| Modelo | Input | Cache | Output | Notas |
|---|---|---|---|---|
| Gemini 3.5 Flash-Lite | 0,30 | 0,03 | 2,50 | áudio incluído no mesmo preço |
| Gemini 3.1 Flash-Lite | 0,25 (áudio 0,50) | 0,025 | 1,50 | |
| Gemini 2.5 Flash-Lite | 0,10 (áudio 0,30) | 0,01 | 0,40 | modelo mais antigo, verificar data de retirada |
| Gemini 2.5 Flash | 0,30 (áudio 1,00) | 0,03 | 2,50 | |
| Gemini 3.7 Flash / 3.8 Flash | 0,75 | 0,075 | 3,75 | **preço promocional até 2026-12-31; a partir de 2027-01-01 passa a 1,50 / 0,15 / 7,50** |
| Gemini 3.1 Pro Preview | 2,00 (<=200k) | 0,20 | 12,00 | "Preview" |
| Gemini 2.5 Pro | 1,25 (<=200k) | 0,125 | 10,00 | |

Áudio como input dos Flash 3.7/3.8: $3,00 por 1M ou $0,005/min.

### 3.4 Groq Whisper (resumo de WebFetch de console.groq.com/docs/speech-to-text; a página groq.com/pricing não mostrou tabela)

- **whisper-large-v3-turbo: $0,04/hora**, 216x tempo real, WER 12%, só transcrição.
- whisper-large-v3: $0,111/hora, 189x, WER 10,3%, transcrição e tradução (tradução só para inglês).
- Faturação mínima 10 s; ficheiros até 25 MB (free) / 100 MB (dev); aconselha indicar o idioma ISO-639-1. O doc 08 está correcto no preço ($0,04/h). Estado: INDÍCIO-forte (resumo de fetch; uma pesquisa independente deu $0,04/h).
- Para comparação: gpt-4o-mini-transcribe a $0,003/min = $0,18/h, 4,5x o turbo do Groq.

### 3.5 Modelos recomendáveis para PT e latência

- **Qualidade em português de Angola:** NÃO VERIFICADO com fonte primária. Não existe benchmark oficial por variante. Recomendação operacional: montar um dataset de 100-300 conversas reais (já previsto no doc 08) e comparar 3 candidatos baratos e 1-2 intermédios. Candidatos pela relação preço/capacidade, **sem afirmar ranking**: baratos: Claude Haiku 5.5, gpt-6-luna, Gemini 3.1/3.5 Flash-Lite; intermédios: Claude Sonnet 5.5, gpt-6.1-sol, Gemini 3.7/3.8 Flash.
- **Latência típica:** NÃO VERIFICADO. O único dado que encontrei (Artificial Analysis, via pesquisa) mostra TTFT de 10,3 s (Gemini 3.5 Flash-Lite) e 127 s (GPT-5.6 Luna "max") com raciocínio no máximo, valores que não representam uso conversacional com raciocínio desligado/baixo. Não os usar. Medir p50/p95 de TTFT e total com o nosso prompt, em produção real, a partir de uma região próxima de Angola.
- Custo por mensagem de venda do doc 08 ($0,0003-0,0011) mantém a ordem de grandeza; com Haiku 5.5 ou gpt-6-luna a $0,10/$0,50 e cache, desce ou fica igual, mas o tokenizador novo da Anthropic acrescenta ~30% de tokens.

---

## 4. Decisões que mudam face aos documentos exploratórios

(Referências aos ficheiros em `C:\Jimy\Ideias`.)

1. **MinIO sai.** Repo arquivado em Abril/2026, sem binários, sem manutenção (docs 10 e 11 usam MinIO para WAL/PITR, ficheiros e objectos do Langfuse). Substituir por interface S3 com SeaweedFS (Apache-2.0) ou S3 gerido; Garage como alternativa AGPL.
2. **Typebot: corrigir a frase "seguro para uso interno/comercial" (doc 08, 2.6).** É seguro como ferramenta nossa interna (onboarding, captura de morada). Não é seguro como runtime ou construtor exposto a tenants (Competing Use). A "degradação graciosa: Typebot assume fluxos determinísticos" (doc 10) e a "Academia com Typebot" (doc 10) precisam de uma de duas coisas: aceitar o risco de interpretação, ou implementar fluxos determinísticos em LangGraph (sem custo de licença). Recomendo o segundo para tudo o que o tenant veja.
3. **LangGraph só como biblioteca MIT.** Não adoptar LangGraph Server/Platform/"LangSmith Deployment" (ELv2 + chave de licença + beacon). O checkpointer Postgres é MIT e está a ser mantido. Manter `interrupt()`, mas o nó reinicia na retoma: handoff e criação de encomendas têm de ser idempotentes (afecta doc 11, 4.2-4.3).
4. **Medusa: nova camada Enterprise desde 2026-08-11.** RBAC e SSO/OIDC já não são MIT. O doc 08 afirma "Medusa MIT"; passa a "MIT excepto RBAC/SSO". Não usar as feature flags `rbac`; permissões por tenant/vendedor fora do admin Medusa.
5. **Mercur: spike passa a obrigatório e inclui segurança.** Funcionalidade multi-vendor existe (split de encomendas, comissões, ofertas, aprovação de produtos). Mas a vulnerabilidade de isolamento entre vendedores corrigida hoje exige testes de autorização cross-seller próprios, e o payout incluído é só Stripe Connect (disponibilidade em Angola não verificada). O doc 14 já prevê "Mercur (se o spike falhar)".
6. **LiteLLM: tratar como componente de supply-chain crítico.** Imagem Docker fixada por digest/cosign, nunca `pip install litellm` solto, versão >= 1.83.0. Chaves virtuais/budgets/spend continuam na parte MIT; SSO e audit logs não.
7. **Langfuse v4 com ClickHouse (propriedade da ClickHouse desde Jan/2026).** O desenho "Langfuse self-host" implica 4 serviços de estado; para o piloto avaliar adiar ou usar a versão cloud. Licença MIT mantida, EE só em `ee/`.
8. **Postgres 16 -> 18.6** (doc 11). pgvector 0.8.7 (correcção de segurança de 2026-10-01). Desenhar a pesquisa vectorial multi-tenant com `hnsw.iterative_scan` ou particionamento, porque o filtro por tenant é aplicado depois do índice.
9. **Modelos do doc 08 estão desactualizados.** Os preços de referência (GPT-4.1-nano/mini, Gemini 2.5 Flash-Lite) foram ultrapassados: candidatos baratos actuais a $0,10/$0,50 (Haiku 5.5, gpt-6-luna). Gemini Flash 3.7/3.8 tem preço promocional que **dobra em 2027-01-01**. Sonnet 5 manteve $2/$10 (o aumento anunciado foi cancelado).
10. **Chatwoot: o issue #13426 já não está em aberto** (fechado 2026-02-03); o encaminhamento multi-tenant por WABA parece resolvido (INDÍCIO). Embedded Signup v2 morre a 2026-10-15: confirmar v4 na versão em uso. Coexistência está implementada no código; Meta: 20 mps fixos de throughput em números com Business App + Cloud API, app >= 2.24.17, sincronização de 180 dias em 24 h, exige Tech Provider/Solution Partner (CONFIRMADO, docs Meta). Angola suportada em coexistência: INDÍCIO (fontes secundárias dizem "todos os países" desde Abril/2026).
11. **n8n e Dify: rejeição confirmada.** n8n apenas back-office interno (doc 11 lista-o como serviço, aceitável se nenhum tenant o configura).
12. **Vault passou a BUSL-1.1 (IBM).** Se for preciso um cofre self-hosted, preferir OpenBao (MPL-2.0). Para equipa pequena, Doppler Developer cobre o arranque.

---

## 5. Riscos de dependência

| Risco | Componente | Probabilidade / impacto | Mitigação |
|---|---|---|---|
| Licença desliza para open-core mais restritivo | Medusa (EE 2026-08), Chatwoot (EE cresce), Langfuse (EE), Meilisearch (BUSL), Typebot (FSL desde 2024), n8n (SUL), LiteLLM (EE) | Alta ao longo de 12-24 meses | Fixar versão MIT conhecida (as versões antigas mantêm a licença original, como o próprio ENTERPRISE-LICENSE do Medusa declara); manter registo de licenças por versão; interfaces atrás de portas (HandoffProvider, LLMProvider) como já previsto no doc 14 |
| Projecto descontinuado | MinIO (arquivado 2026-04), open-agent-platform (arquivado 2026-02) | Já ocorreu | Retirar MinIO; abstracção S3 |
| Supply chain / credenciais | LiteLLM (incidente 2026-03) | Média / crítico (guarda as chaves de todos os LLM) | Digest + cosign, sem instalação dinâmica, rede egress limitada, rotação de chaves |
| Isolamento entre tenants/vendedores | Mercur (fix cross-seller em 2026-10-08); Chatwoot (multi-conta) | Média / crítico | Testes de autorização automáticos por tenant; revisão de segurança antes do piloto; RLS no Postgres para as nossas tabelas |
| Maturidade e pequena equipa | Mercur (14 contribuidores), RustFS 1.0, Garage | Média | Fallback já previsto (Medusa puro + link de vendedor); evitar RustFS no piloto |
| Dependência de licenciante único | Typebot (1 pessoa/empresa), LangSmith Deployment (LangChain) | Média | Evitar para caminho crítico do tenant |
| Mudanças da plataforma Meta | Embedded Signup v2 deprecado a 2026-10-15; coexistência 20 mps; preços de "AI Providers" (alteração 2026-05-13 para EU/EEA, Brasil mantém cobrança) | Alta (frequência de mudanças) | Acompanhar changelog Meta; Tech Provider; testes de embedded signup v4 |
| Aumento de preço de LLM | Gemini Flash 3.7/3.8 duplica em 2027-01-01; tokenizador Anthropic +30% | Média | LiteLLM com fallbacks e budgets por tenant; reavaliar trimestralmente |
| Custo operacional do stack | Langfuse (4 serviços de estado), Temporal (cluster), Keycloak (JVM) | Média | Adiar o que não é do MVP; DBOS/BullMQ em vez de Temporal; considerar Langfuse Cloud |
| Segredos | Vault BUSL; Doppler SaaS | Baixa-média | OpenBao ou Doppler com export; nunca segredos em imagens |
| Dados e residência | Traces Langfuse, conversas no LLM externo, Groq/OpenAI/Google em EUA | A decidir por conformidade | Fora do âmbito desta verificação; validar com a análise legal já existente (docs 02/04) |

---

## 6. O que não consegui verificar (lista para a próxima ronda)

> **Emenda de 2026-10-27 (spike KAM-041).** A documentação oficial do Medusa
> **está acessível**: `docs.medusajs.com` responde HTTP 200, qualquer página
> serve Markdown acrescentando `.md` ao URL, e há um corpus completo em
> `https://docs.medusajs.com/llms-full.txt`. A indisponibilidade registada nesta
> secção a 2026-10-08 era conjuntural, não permanente — e isso importa, porque
> três itens ficaram NÃO VERIFICADOS por causa dela quando eram verificáveis.
> O que o spike apurou está em
> [`../../spikes/KAM-041-medusa.md`](../../spikes/KAM-041-medusa.md):
>
> - **multi-tenancy nativa: não existe** — negação textual da documentação
>   («While Medusa doesn't natively support multi-tenancy…»), CONFIRMADO;
> - **reservas sem TTL:** o `ReservationItem` não tem campo de expiração e não
>   há *scheduler* nativo, CONFIRMADO;
> - **reserva atómica:** a camada do módulo é *read-then-write* sem lock nem
>   constraint; a protecção vive no passo de *workflow*, cujo provider de
>   locking por omissão é *in-memory* e, pela documentação, «only intended for
>   use in a single-instance environment», CONFIRMADO.
>
> E duas correcções ao §2.1 desta mesma evidência, também CONFIRMADAS:
> o `@medusajs/medusa` declara `SEE LICENSE IN LICENSE` desde a **2.19.0**
> (a 2.18.0 é a última `MIT`), e **`@medusajs/policies` não existe no npm** —
> `policies` é um directório do `@medusajs/framework`, e o interruptor real são
> as *feature flags* `MEDUSA_FF_RBAC` e `MEDUSA_FF_RBAC_FILTER_FIELDS`.

- ~~Multi-tenancy nativo do Medusa v2 (documentação não acessível no fetch).~~
  **Resolvido** pela emenda acima: não existe (CONFIRMADO, 2026-10-27).
- Disponibilidade do Stripe Connect em Angola e alternativas de payout (Mercur).
- Documentação do BullMQ sobre garantias de entrega e do Keycloak sobre Organizations/realms.
- Que versão do Embedded Signup usa a versão 4.18.0 do Chatwoot.
- Requisitos reais de RAM/disco do Nominatim e Valhalla para o extracto de Angola (81 MB de PBF), a medir em ensaio.
- Preços e pesos de S3 geridos acessíveis em Angola; semântica S3 do Garage/SeaweedFS para os nossos casos (multipart, versioning).
- Qualidade em português de Angola e latência p50/p95 dos modelos; datas de retirada dos modelos GPT-4.1 e Gemini 2.5.
- Preços oficiais do LangSmith Deployment (só pesquisa secundária).
- Confirmação formal com Typebot sobre o alcance de "Competing Use" para o nosso uso.
- Preços das páginas Google e OpenAI foram lidos através de um sumarizador: reconferir à mão antes de fixar preços ao cliente.

---

## 7. Fontes principais (URLs)

- Medusa: https://github.com/medusajs/medusa (LICENSE, ENTERPRISE-LICENSE.md, releases)
- Mercur: https://github.com/mercurjs/mercur (LICENSE, docs/PRODUCT.md, releases)
- Chatwoot: https://github.com/chatwoot/chatwoot (LICENSE, enterprise/LICENSE), https://developers.chatwoot.com/self-hosted/enterprise-edition, https://developers.chatwoot.com/self-hosted/configuration/features/integrations/whatsapp-embedded-signup, https://github.com/chatwoot/chatwoot/issues/13426
- Typebot: https://github.com/baptisteArno/typebot.io/blob/main/LICENSE, https://docs.typebot.com/self-hosting
- n8n: https://github.com/n8n-io/n8n/blob/master/LICENSE.md, https://docs.n8n.io/n8n-community-license/community-license/license-faq.md
- Dify: https://github.com/langgenius/dify/blob/main/LICENSE
- LangGraph: https://github.com/langchain-ai/langgraph, https://pypi.org/project/langgraph-api/, https://docs.langchain.com/langsmith/deploy-standalone-server, https://docs.langchain.com/oss/python/langgraph/interrupts
- LiteLLM: https://github.com/BerriAI/litellm (LICENSE, enterprise/LICENSE.md), https://www.litellm.ai/pricing, https://docs.litellm.ai/blog/security-update-march-2026
- Langfuse: https://github.com/langfuse/langfuse, https://langfuse.com/self-hosting, https://langfuse.com/blog/announcing-acquisition
- PostgreSQL: https://www.postgresql.org/support/versioning/; pgvector: https://github.com/pgvector/pgvector
- BullMQ: https://github.com/taskforcesh/bullmq; Temporal: https://github.com/temporalio/temporal; DBOS: https://github.com/dbos-inc/dbos-transact-py; Restate: https://github.com/restatedev/restate
- MinIO: https://github.com/minio/minio; SeaweedFS: https://github.com/seaweedfs/seaweedfs; Garage: https://github.com/deuxfleurs-org/garage; RustFS: https://github.com/rustfs/rustfs
- Nominatim: https://github.com/osm-search/Nominatim, https://nominatim.org/release-docs/latest/admin/Installation/; Valhalla: https://github.com/valhalla/valhalla; Geofabrik: https://download.geofabrik.de/africa/angola.html
- Hono: https://github.com/honojs/hono; Keycloak: https://github.com/keycloak/keycloak; ClickHouse: https://github.com/ClickHouse/ClickHouse; Meilisearch: https://github.com/meilisearch/meilisearch; Vault: https://github.com/hashicorp/vault; OpenBao: https://github.com/openbao/openbao; Doppler: https://www.doppler.com/pricing
- Meta WhatsApp: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview, .../onboarding-business-app-users, .../changelog/
- Preços: https://platform.claude.com/docs/en/about-claude/pricing, https://developers.openai.com/api/docs/pricing, https://ai.google.dev/gemini-api/docs/pricing, https://console.groq.com/docs/speech-to-text
