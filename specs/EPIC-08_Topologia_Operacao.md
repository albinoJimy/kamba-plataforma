# EPIC-08 — Topologia e Operação

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Topologia e Operação |
| Versão | 1.0 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/09_Topologia_Operacao_Escala.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/EPIC-01_Fundacoes_Dados.md`, `specs/EPIC-07_Seguranca_Conformidade.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/00_KAMBA_Carta.md` |

---

## 1. Visão do Epic

Este epic põe a KAMBÁ a **correr de forma operável**: ambientes (`dev`, `staging`, `prod`) por infraestrutura como código, o **Compose de produção do conjunto reduzido** (≈ 18,6 GB de *working set*, ESTIMATIVA: GWY, AGR, Chatwoot, Medusa, `onboarding-web`, Postgres 18.6, Valkey/Redis, LiteLLM, STO, proxies, monitorização, pgBackRest), alojamento e borda, CI/CD com os gates 14–18 de `01_Engineering_Standards_e_Handoff.md` §4, backups com PITR e restauro testado, observabilidade sem conteúdo, SLOs, runbooks, custo por tenant, ensaio de carga e simulacro de recuperação. Existe porque o desenho exploratório tinha três defeitos que o doc 09 corrige: 13 serviços numa máquina de 8 vCPU/32 GB (≈ 42 GB com Langfuse v4), backup no mesmo *host* que a base de dados (RPO efectivo = total) e dependência de MinIO (arquivado desde 2026-04).

O epic concretiza **ADR-008** (alojamento, *backups*, CDN e observabilidade são «alojamento»; nenhum dado pessoal de produção sai de Angola sem registo da APD), **ADR-009** (Redis/Valkey reconstruível a partir do *outbox*), **ADR-014** (`StorageProvider`, sem MinIO), **ADR-018** (observabilidade leve: Langfuse **não** entra em produção no Piloto; tabela de chamadas LLM sem conteúdo), **ADR-002** (n8n e Typebot fora de produção), **ADR-005** (LiteLLM ≥ 1.83.0 por *digest* e cosign), **ADR-006** (Postgres 18.6), **ADR-001** (alertas `PARTNER_REMOVED`, 20 mps em coexistência) e **ADR-019** (`onboarding-web` no Compose, sem vitrine). As propostas locais ADR-P06 a ADR-P10 do doc 09 (host único, pgBackRest, sem Langfuse, Valkey, Node 24/Hono 4.x) são tratadas como **propostas**; a Valkey (ADR-P09) fica condicionada a teste em *staging* (D12).

**Estado das afirmações.** Só os requisitos de recursos de Chatwoot (≥ 4 GB e 4 núcleos), Langfuse v4 (4 núcleos, 16 GiB, 100 GiB) e Medusa (≥ 2 GB) vêm de documentação oficial (CONFIRMADO). A memória por serviço, os preços de VM, o volume por PME, as cotações de Luanda, a latência Luanda↔JNB e os limites do BullMQ são ESTIMATIVA ou NÃO VERIFICADO: os tickets KAM-084 (carga) e KAM-085 (DR) existem para os validar ou corrigir, e nenhum ticket trata um número do doc 09 como requisito sem esse critério de saída. **Fase:** 0 (KAM-075, 076, 077, 080: chão de infraestrutura e observabilidade mínima) e 1 (KAM-078, 079, 081–085). `prod` corre **só com dados sintéticos** até D1 e ao procedimento APD (KAM-105, KAM-069). Abreviaturas: «doc 09» designa `../docs/tecnica/09_Topologia_Operacao_Escala.md`, «doc 00» designa `../docs/tecnica/00_Arquitectura_Solucao.md`, «E1» a «E4» designam `../docs/tecnica/evidencia/E1_…` a `E4_…`.

---

## 2. Critérios de Saída do Epic

- [ ] O Compose de produção contém exactamente o conjunto reduzido; um teste de *denylist* falha se aparecer Langfuse, Nominatim, Typebot, n8n, vitrine ou MinIO; `onboarding-web` está presente.
- [ ] 100% das imagens de produção por *digest* (nunca por tag), com SBOM e assinatura cosign verificada; um `release.lock` por release; *rollback* = reimplantar o `release.lock` anterior.
- [ ] Os gates 14–18 (image scan, deploy *staging* + smoke, aprovação, deploy prod *rolling*, tag SemVer) estão activos e *fail-closed*; o smoke ponta a ponta envia uma mensagem ao número de teste e recebe resposta correcta em ≤ 15 s (p95 de 20 execuções) e fecha o ciclo pedido → referência no sandbox → callback → `paga`.
- [ ] *Rolling deploy* em *staging* sob tráfego sintético: 0 mensagens perdidas e 0 respostas duplicadas; release inválida é revertida automaticamente em ≤ 5 min (*proposta*).
- [ ] Restauro completo a partir do repositório de backup (`repo1`, noutro domínio de falha e dentro da jurisdição autorizada) noutro *host* em ≤ 2 h, com perda de dados ≤ 5 min, **medido** num simulacro (KAM-085); restauro mensal automático com 2 execuções consecutivas verdes.
- [ ] Em hora de ponta no perfil P0: memória ≤ 65% e CPU ≤ 60% sob o ensaio de carga; as estimativas do doc 09 §4.2 estão confirmadas (±20%) ou corrigidas por escrito (KAM-084).
- [ ] As 12 regras de alerta do doc 09 §9.2 estão activas, cada uma testada por injecção de falha e ligada a um runbook; 0 alertas sem runbook; a sonda sintética externa detecta a paragem do ingress em ≤ 11 min.
- [ ] Os 8 SLIs do doc 09 §10 são medidos, com orçamento de erro visível; o custo por tenant reconcilia com os *spend logs* do LiteLLM (desvio ≤ 2%, *proposta*).
- [ ] Nenhum dado pessoal real em `staging`/`dev`; `prod` não aceita `kamba_data_class=real` sem referência de D1 e `apd_ref` (gate de go-live).

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-075 | Ambientes dev/staging/prod e infraestrutura como código mínima | chore | M | P0 | KAM-001 |
| KAM-076 | Compose de produção do conjunto reduzido e redes isoladas | feature | L | P0 | KAM-075 |
| KAM-077 | Alojamento, TLS, edge e WAF (D1, D12) | chore | M | P0 | KAM-075, ext:KAM-105 |
| KAM-078 | CI/CD completo: deploy rolling e smoke ponta a ponta com número de teste | feature | L | P0 | KAM-002, KAM-076, KAM-024 |
| KAM-079 | Backups pgBackRest fora do host, PITR e restauro mensal automático | feature | L | P0 | KAM-076, ext:KAM-105 |
| KAM-080 | Métricas, logs JSON e alertas (Prometheus, Grafana, Loki) | feature | L | P0 | KAM-076 |
| KAM-081 | Custo por tenant e dashboard de unit economics | feature | M | P1 | KAM-030, KAM-080, KAM-023 |
| KAM-082 | SLOs, orçamento de erro e alertas | feature | S | P0 | KAM-080 |
| KAM-083 | Runbooks operacionais (Meta, facilitador, LLM, rating, free tier, tokens, segredos) | chore | M | P0 | KAM-080, KAM-021, KAM-023, KAM-017, KAM-079 |
| KAM-084 | Teste de carga e validação do dimensionamento | chore | M | P1 | KAM-076, KAM-013, KAM-015, KAM-025, KAM-031, KAM-024 |
| KAM-085 | Simulacro de recuperação (DR drill) com RTO medido | chore | M | P0 | KAM-079 |

---

## KAM-075 — Ambientes dev/staging/prod e infraestrutura como código mínima

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-001 |
| Bloqueia | KAM-076, KAM-077 |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§5.3, §6, §8.2), `../docs/tecnica/08_Seguranca_Conformidade.md` (§5), ADR-008, ADR-014, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (requisito 24) |

### Contexto
O Piloto tem três ambientes com regras de dados diferentes: `dev` e `staging` só com dados sintéticos (fora do âmbito dos Arts. 33.º–34.º da Lei 22/11), `prod` com dados reais apenas depois de D1 e do procedimento APD. D1 (Luanda ou JNB/CPT) está aberta e as cotações de Luanda são NÃO VERIFICADAS, logo a infraestrutura tem de ser **portátil**: mudar de região não pode exigir reescrita (E3 req. 24; doc 09 §5.3). O orçamento de RTO de 2 h assume «novo *host* por IaC em 30 min» (doc 09 §8.2): este ticket é onde isso passa a ser medido.

### Objectivo
Definir e provisionar `dev`, `staging` e `prod` por infraestrutura como código mínima e agnóstica de fornecedor, com a matriz de ambientes do doc 09 §6 e um *host* novo reproduzível em ≤ 30 min.

### Critérios de Aceitação
- [ ] A matriz de ambientes está versionada em `infra/ENVIRONMENTS.md` com as 7 linhas do doc 09 §6 (dados, compute, Meta, facilitador, LLM, segredos, acesso) e é verificada por um teste que compara a matriz com a configuração real.
- [ ] Numa conta vazia, `infra apply staging` produz um *host* com Docker, utilizador não-root, WireGuard e disco NVMe em ≤ 30 min (mediana de 3 execuções registada); um segundo `apply` não altera nada (idempotente).
- [ ] `staging` (4 vCPU/16 GB) cria-se e destrói-se com um comando; uma tentativa de restaurar um backup de `prod` em `staging` falha por controlo (teste negativo).
- [ ] `prod` arranca com `kamba_data_class=synthetic`; passar a `real` exige uma referência de decisão D1 e pelo menos um `apd_ref` preenchido, senão o *pipeline* recusa (a lógica do gate de transferência por destino é de KAM-069).
- [ ] Mapeamento ambiente → projecto de segredos (`dev`, `staging`, `prod`) definido; chaves Meta e do facilitador **distintas** por ambiente; *scan* de segredos limpo; um segredo de `prod` referenciado em `staging` faz o *pipeline* falhar.
- [ ] Checklist de portabilidade preenchida: 0 recursos geridos proprietários sem equivalente documentado.
- [ ] Etiquetas de custo por ambiente e custo mensal registado a partir de uma cotação real (não do doc 09).

### Detalhes Técnicos
- **Componentes:** infraestrutura transversal (suporta GWY, AGR, HND, COM, PAY, LLM, STO, OBS). Estrutura `infra/{modules,envs/{dev,staging,prod}}`; ferramenta a fixar em ADR local (*proposta*: OpenTofu + Ansible/cloud-init; critério: sem chave estática, sem módulo de fornecedor único).
- **`dev`:** Compose local; Meta por *mocks* com corpo assinado por segredo de teste; facilitador *mock*. **`staging`:** número de teste da app Meta de *staging* (WABA de teste); sandbox ProxyPay (`api.sandbox.proxypay.co.ao`; OPG `900000000` aceita, `900002004` *timeout*, `900003000` recusa, CONFIRMADO) e sandbox AppyPay (INDÍCIO); LiteLLM com chave própria e *budget* baixo. **`prod`:** break-glass auditado (`audit_log`).
- Os projectos de segredos são criados por KAM-010; este ticket só define o mapeamento e falha se o mapeamento for violado.
- DNS com TTL baixo (*proposta*: 300 s) pré-configurado, para o passo «DNS» do orçamento de RTO.

### Testes Requeridos
- Provisionamento a partir do zero num *host* descartável, 3×, com cronometragem; idempotência (`plan` vazio).
- Negativos: backup de `prod` → `staging`; segredo de `prod` em `staging`; `kamba_data_class=real` sem `apd_ref`.
- *Scan* de segredos e de licenças dos módulos de IaC.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Sem segredos em código, estado de IaC ou logs; estado de IaC cifrado.
- [ ] Dados: `dev`/`staging` sintéticos; `prod` sem dados reais (privacidade e ADR-008).
- [ ] Dependências de IaC fixadas por versão/hash; licenças permitidas.
- [ ] Custo por ambiente visível (ADR-018).
- [ ] Documentação actualizada: `infra/README.md` com o procedimento de «host novo em 30 min» (insumo de RB-K08).

### Handoff para Claude Code
```text
És o executor do ticket KAM-075 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-075), docs/tecnica/09_Topologia_Operacao_Escala.md (§5.3, §6, §8.2),
specs/01_Engineering_Standards_e_Handoff.md e docs/tecnica/00_Arquitectura_Solucao.md (ADR-008, D1).
Objectivo: IaC mínima e portátil para dev/staging/prod com a matriz do doc 09 §6.
- Cria infra/ com módulos e envs; fixa a ferramenta num ADR local curto (sem chaves estáticas, sem recurso de fornecedor único).
- Implementa kamba_data_class (synthetic|real) em prod: real só com decisão D1 e apd_ref; teste negativo incluído.
- Garante que prod->staging não restaura dados e que segredos de prod nunca são lidos em staging.
- Não escolhas o fornecedor de alojamento (D1/KAM-105): usa um módulo «provider» substituível.
Não expandas escopo: Compose é KAM-076, TLS/edge é KAM-077. Testes: provisionamento 3x cronometrado, idempotência, negativos. PR com o template da §7.
```

---

## KAM-076 — Compose de produção do conjunto reduzido e redes isoladas

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-075 |
| Bloqueia | KAM-078, KAM-079, KAM-080, KAM-084 |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§3, §4, §20), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.4, §4.8), ADR-002, ADR-005, ADR-006, ADR-009, ADR-014, ADR-018, ADR-019 |

### Contexto
O doc 09 §3 revê a topologia do doc 11: 13 serviços não cabem em 32 GB com Langfuse v4 (≈ 42 GB). O Piloto corre o **conjunto reduzido** (≈ 18,6 GB, ESTIMATIVA; 58% de 32 GB). Saem Langfuse (ADR-018), Nominatim e vitrine (Clusters), Typebot e n8n (ADR-002, licenças) e MinIO (ADR-014); entra `onboarding-web` (ADR-019). Versões do doc 09 (a reconfirmar na execução, 2026-10-08): Hono 4.13.x em Node 24 LTS, LangGraph 1.2.x como biblioteca, Chatwoot v4.18, Medusa v2.21.x, PostgreSQL 18.6 com pgvector 0.8.7 e pg_trgm, LiteLLM ≥ 1.83.0, SeaweedFS 4.48 (ou S3 gerido, D6).

### Objectivo
Entregar o Compose de produção (e o de *staging*, com as mesmas imagens) do conjunto reduzido, em quatro redes isoladas, com contentores endurecidos e limites de recursos, pronto para receber KAM-078/079/080.

### Critérios de Aceitação
- [ ] `docker compose config` lista exactamente os serviços do conjunto reduzido; um teste de CI falha se `langfuse`, `nominatim`, `typebot`, `n8n`, `storefront` ou `minio` surgirem no ficheiro de produção.
- [ ] 100% das imagens referenciadas por `@sha256:` (nenhuma por tag); teste de CI falha caso contrário. O perfil `staging-obs` (Langfuse v4, dados sintéticos) só existe em *staging* e não arranca com `kamba_data_class=real`.
- [ ] Redes `edge`, `app`, `data`, `ops`: de um contentor em `data` qualquer ligação externa falha; de `app` só têm êxito `graph.facebook.com`, o FQDN do facilitador e os FQDN de LLM/STT autorizados, e as restantes são bloqueadas e registadas (script de teste com 10 destinos).
- [ ] Todos os contentores com sistema de ficheiros só de leitura, utilizador não-root, `mem_limit` e `cpus`; a soma dos `mem_limit` ≤ 80% da RAM do *host* (≤ 25,6 GB em 32 GB).
- [ ] GWY e *workers* AGR com 2 réplicas e `/healthz`; no exterior só 443 e a porta UDP do WireGuard estão abertas (*scan* externo); Medusa admin e Grafana só por VPN.
- [ ] Teste de compatibilidade Valkey em *staging* (BullMQ do *outbox*, Sidekiq do Chatwoot, eventos/cache do Medusa) passa; se falhar, regressa-se a Redis e abre-se D12 sobre a licença. Resultado registado em ADR-P09.
- [ ] Se D6 = SeaweedFS: ensaio de *multipart*, URL assinada com TTL ≤ 5 min e *object lock*; falha → S3 gerido (resultado em `../docs/tecnica/evidencia/`).
- [ ] Flags de licença verificadas: `rbac`/`auth-oidc` do Medusa, `enterprise/` do Chatwoot e `ee/` do Langfuse inactivos.

### Detalhes Técnicos
- **Componentes:** GWY, AGR, HND, COM, LLM, STO, EVT, onboarding-web, Postgres, proxy TLS (Caddy ou Traefik), proxy de saída com allowlist de FQDN. Bases separadas `platform`, `medusa`, `chatwoot`; RLS é de KAM-004.
- **Limites propostos (ESTIMATIVA, ≈ 1,25× o doc 09 §4.2):** GWY 2×0,25 GB; AGR 2,5; Chatwoot 5 (mínimo oficial 4 GB, Sidekiq pode exceder 1 GB, INDÍCIO); Medusa 2,5 (mínimo oficial 2 GB); `onboarding-web` 0,75; Postgres 5; Valkey 0,75; LiteLLM 2; STO 1; monitorização 2; SO e proxies 1,5. Soma ≈ 23,5 GB. Ajustados em KAM-084.
- Chatwoot web exposto em 443 (operadores e PMEs); Medusa admin e Grafana só por VPN. O Chatwoot recebe espelho por inbox de tipo API; nunca fala com a Meta (GWY é o único endpoint).
- `release.lock` (lista de *digests*) é a única fonte do Compose; não há *pip/npm install* em arranque; Node 24 LTS (o intervalo de Node aceite pelo Medusa é NÃO VERIFICADO: confirmar em `engines`).

### Testes Requeridos
- Contrato do Compose (denylist, *digests*, limites, utilizador, FS só de leitura) e testes de rede (*default-deny*).
- *Smoke* de arranque a frio: todos os `healthz` verdes em ≤ 5 min; *scan* de portas externo.
- Compatibilidade Valkey e (condicional) SeaweedFS em *staging*.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Dependências por *digest*; licenças e lista de bloqueio respeitadas (sem MinIO, sem `langgraph-api`, LiteLLM ≥ 1.83.0).
- [ ] Egress *default-deny* provado; sem segredos em imagens, Compose ou logs.
- [ ] Consumo em repouso medido e registado (comparação com 18,6 GB fica em KAM-084).
- [ ] Dois revisores (infraestrutura que toca segredos e isolamento); documentação e ADR-P09 actualizados.

### Handoff para Claude Code
```text
És o executor do ticket KAM-076 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-076), docs/tecnica/09_Topologia_Operacao_Escala.md (§3, §4, §20),
docs/tecnica/08_Seguranca_Conformidade.md (§4.4, §4.8) e specs/01_Engineering_Standards_e_Handoff.md.
Objectivo: Compose de produção do conjunto reduzido com redes edge/app/data/ops e contentores endurecidos.
- Serviços: GWY x2, AGR workers x2, Chatwoot, Medusa, onboarding-web, Postgres 18.6, Valkey (a validar), LiteLLM, STO, proxy TLS, proxy de saída, monitorização.
- Proibido em prod: Langfuse, Nominatim, Typebot, n8n, vitrine, MinIO (teste de denylist).
- Imagens só por @sha256 via release.lock; FS só de leitura; não-root; limites propostos; egress default-deny.
- Escreve os testes de rede e o teste de compatibilidade Valkey; não decidas D1/D6, usa as flags.
Não expandas escopo: TLS/edge real é KAM-077, backups KAM-079, alertas KAM-080. PR com o template da §7.
```

---

## KAM-077 — Alojamento, TLS, edge e WAF (D1, D12)

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-075, ext:KAM-105 |
| Bloqueia | — |
| Responsável sugerido | Plataforma/SRE (com Responsável de Segurança) |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§3.2, §5), `../docs/tecnica/08_Seguranca_Conformidade.md` (§8.3, §13 N1/N2, §15), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§2, §7), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), ADR-008, D1, D12 |

### Contexto
A decisão D1 (KAM-105) escolhe entre Luanda (Raxio, Paratus, Angola Cables, Cloud Nacional) e JNB/CPT com procedimento APD; as cotações de Luanda e a latência Luanda↔JNB/Meta são NÃO VERIFICADAS (doc 09 §19). Alojar em Luanda **não** dispensa o procedimento APD (LLM, STT e Meta já são transferências). O proxy que termina TLS vê o corpo dos webhooks: um CDN/WAF é **subprocessador com acesso a conteúdo** (D12, ../docs/tecnica/08 §13 N1). A Meta exige HTTPS com certificado válido (autoassinado não suportado, CONFIRMADO) e validação de `X-Hub-Signature-256` sobre o corpo bruto.

### Objectivo
Pôr o *host* de produção no alojamento decidido em D1, com TLS válido, DNS, borda, regra de CDN/WAF decidida (D12), acesso administrativo por VPN e o `egress` com allowlist activo, mantendo `prod` sem dados reais até ao gate de go-live.

### Critérios de Aceitação
- [ ] O *host* de produção está no alojamento registado em KAM-105 (D1), com contrato, SLA, jurisdição do DC e 2.º local para backups arquivados em `provas/alojamento/` (entrada na pasta de provas, E3 req. 25).
- [ ] O GET de verificação do webhook devolve o *challenge* por HTTPS e `openssl s_client -verify_return_error` valida a cadeia; TLS ≥ 1.2; renovação automática testada (renovar em *staging* com validade encurtada).
- [ ] Decisão D12 (CDN/WAF) registada com dono e data: (a) CDN assumido como subprocessador e declarado na notificação, ou (b) caminho `/webhooks/*` directo à origem com *rate limit* na origem. Por omissão de construção, aplica-se (b) até parecer em contrário (*proposta*, ../docs/tecnica/08 §15).
- [ ] *Scan* externo: só 443 e a porta UDP do WireGuard; SSH por chave só via VPN; MFA no painel do fornecedor; acesso *break-glass* auditado.
- [ ] RTT medido de uma sonda em Luanda ao *host*, p50/p95 em 24 h, e do *host* a `graph.facebook.com`; tabela em `../docs/tecnica/evidencia/` (substitui os valores INDÍCIO do doc 09 §5.2).
- [ ] `prod` continua `kamba_data_class=synthetic`; o gate de go-live (D1 decidida, `apd_ref` por destino, parecer D9) está documentado com o seu estado (satisfeito ou não) e a data da última verificação.

### Detalhes Técnicos
- **Componentes:** proxy TLS (Caddy ou Traefik), proxy de saída, WireGuard, DNS; subprocessadores a registar em KAM-069 (alojamento, CDN, e-mail/SMS, sonda externa).
- A cotação e a escolha vêm de KAM-105; este ticket não escolhe fornecedor. Regra de trabalho do doc 09 §5.3: Luanda se cotação ≤ 2× JNB, VMs com SLA e 2.º local angolano; senão JNB/CPT com procedimento concluído.
- Backups também são alojamento (ADR-008): a localização de `repo1` é decidida aqui com KAM-079 e registada no inventário (N2: backups cifrados fora de Angola com chave em Angola, a confirmar por parecer).
- Ainda NÃO VERIFICADO: Postgres/objectos geridos em Luanda; entrega de SMS Unitel/Africell; timeout e *retry* exactos do webhook Meta.

### Testes Requeridos
- Verificação do webhook (GET e POST assinado/inválido) a partir do exterior; teste de renovação de certificado.
- *Scan* de portas e teste de egress (destino fora da allowlist bloqueado).
- Medição de RTT durante 24 h (script) e verificação de que o relatório contém números medidos, não estimados.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Nenhum dado pessoal real em `prod` antes do gate; destinos registados no inventário com estado do `apd_ref` (ADR-008).
- [ ] Sem segredos em código/logs; MFA e VPN activos; revisão por dois (Plataforma e Segurança).
- [ ] D12 e D1 reflectidas no registo de decisões (`00_KAMBA_Carta.md` §4.2) com data.
- [ ] Documentação actualizada (alojamento, RTT, 2.º local).

### Handoff para Claude Code
```text
És o executor do ticket KAM-077 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-077), docs/tecnica/09_Topologia_Operacao_Escala.md (§3.2, §5),
docs/tecnica/08_Seguranca_Conformidade.md (§8.3, §15) e a decisão D1 produzida por KAM-105.
Objectivo: configurar TLS, DNS, borda, VPN e egress no host decidido por D1, sem escolher o fornecedor.
- Se KAM-105 ainda não decidiu D1, pára e di-lo: prepara só o staging com o módulo provider substituível.
- Webhook Meta: HTTPS válido, GET de verificação, POST com X-Hub-Signature-256 sobre o corpo bruto; caminho /webhooks/* directo à origem por omissão (D12).
- Escreve o script de medição de RTT (24 h) e o relatório com números medidos; marca NÃO VERIFICADO o que não medires.
- Mantém prod em kamba_data_class=synthetic; nunca ligues dados reais.
Não expandas escopo: pgBackRest é KAM-079, métricas KAM-080. Testes: verificação de webhook externa, scan de portas, egress. PR com o template da §7.
```

---
## KAM-078 — CI/CD completo: deploy rolling e smoke ponta a ponta com número de teste

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-002, KAM-076, KAM-024 |
| Bloqueia | — |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `specs/01_Engineering_Standards_e_Handoff.md` (§4, gates 14–18), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§6, §7), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.8), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§1.2), ADR-005, ADR-009 |

### Contexto
KAM-002 entrega os gates 1–13 (CI base); este ticket entrega os gates **14–18** e a ligação a `staging`/`prod`: *image scan* (14), deploy em *staging* + *smoke* ponta a ponta (15), aprovação humana (16), deploy *rolling* em produção (17) e tag SemVer (18). Há uma divergência entre documentos: o doc 09 §7 põe «Tag e `release.lock`» **antes** do deploy de produção e os *Standards* põem a tag como encerramento do release. Resolução deste ticket: o `release.lock` (lista de *digests*) é gerado antes do deploy porque o deploy é por *digest*; a **tag SemVer** só é aplicada após a verificação pós-deploy (gate 18). O AGR re-executa nós após `interrupt()`, por isso o *rolling* só é seguro com acções idempotentes (`../docs/tecnica/02`).

### Objectivo
Automatizar o caminho `merge → imagem assinada → staging → smoke → aprovação → produção rolling → verificação → tag`, com reversão automática e sem nenhum gate contornável em silêncio.

### Critérios de Aceitação
- [ ] **Gate 14:** uma imagem sem *digest*, sem SBOM ou sem assinatura cosign verificada falha o *pipeline*; vulnerabilidade crítica sem excepção registada também falha (2 testes negativos).
- [ ] **Gate 15:** o *smoke* envia uma mensagem ao número de teste da app Meta de *staging* e recebe a resposta correcta em ≤ 15 s (p95 de 20 execuções); o caminho de pedido fecha em `paga` em ≤ 60 s via `ManualProvider` e, quando KAM-056 estiver Done, via referência no sandbox ProxyPay → callback assinado.
- [ ] **Gate 16:** um PR marcado dinheiro/segurança/isolamento não chega a `prod` com menos de 2 aprovações (teste negativo com 1).
- [ ] **Gate 17:** *rolling* de GWY e *workers* (2 réplicas: esvaziar, actualizar, verificar `/healthz` e métricas, passar à outra) sob tráfego sintético de 5 msg/s durante 5 min (1.500 mensagens): 0 perdidas, 0 duplicadas, ack < 500 ms em ≥ 99,9%.
- [ ] Uma release deliberadamente inválida (`/healthz` falha) é revertida para o `release.lock` anterior **sem intervenção humana** em ≤ 5 min (*proposta*).
- [ ] **Gate 18:** tag SemVer + `release.lock` + SBOM arquivados após verificação pós-deploy verde; `skip` ou `allow_failure` num gate exige referência a ADR/aprovação (*lint* do *pipeline*).
- [ ] Migrações classificadas `expand` ou `contract`, com `down` testado ou marcadas *expand-only*; a versão N-1 da aplicação passa o *smoke* contra o schema N.
- [ ] Chaves do número de teste e do sandbox são distintas das de produção; o *smoke* aborta se detectar o número de produção (teste negativo).

### Detalhes Técnicos
- **Componentes:** CI/CD sobre KAM-002; Compose de KAM-076; GWY, AGR, HND, PAY (sandbox). CI com OIDC (sem chaves estáticas); Renovate com quarentena ≥ 7 dias (excepção para correcções de segurança com revisão).
- Fluxo: PR → gates 1–13 → *build* por *digest* + cosign + SBOM (CycloneDX) → *scan* (14) → *staging* → *smoke* (15) → aprovação (16) → *prod rolling* (17) → verificação pós-deploy (`/healthz`, taxa de erro do ingress, idade da fila < 2 min, sonda externa) → tag (18).
- *Smoke* usa o simulador de KAM-024 para o tráfego sintético e o número de teste real da Meta para o fio ponta a ponta; mocks do callback assinam com HMAC-SHA256 do corpo bruto (`X-Signature`). Sandbox ProxyPay: `PUT /references/{id}` e *mock payment* (só sandbox).
- Paragem graciosa do *worker* (*proposta*: ≤ 60 s) para não cortar turnos a meio; dois *workers* nunca ficam em actualização em simultâneo.
- Falhas da Meta no *smoke* (indisponibilidade) classificam-se `inconclusivo`, não `verde`.

### Testes Requeridos
- Negativos dos gates 14, 16, 18 e do aborto por número de produção; teste de reversão automática.
- *Rolling* sob carga com reconciliação de ids (enviados × processados × respostas); morte de um *worker* a meio de um turno sem efeito duplicado.
- Migração: subir/descer e compatibilidade N-1.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Nenhum gate marcado *skip* sem registo; os 5 gates (14–18) visíveis no *pipeline* com dono.
- [ ] Imagens por *digest*, SBOM e cosign em 100% das imagens de produção; sem segredos em logs do CI.
- [ ] Idempotência no *rolling* provada (nenhum efeito de negócio duplicado) e migrações reversíveis.
- [ ] Dois revisores (deploy de produção); documentação do procedimento de *rollback* actualizada.

### Handoff para Claude Code
```text
És o executor do ticket KAM-078 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-078), specs/01_Engineering_Standards_e_Handoff.md (§4, gates 14-18),
docs/tecnica/09_Topologia_Operacao_Escala.md (§6, §7) e o pipeline base de KAM-002.
Objectivo: gates 14-18, deploy rolling por release.lock e smoke ponta a ponta com o número de teste da Meta.
- Estende o pipeline de KAM-002; não dupliques gates 1-13. OIDC no CI, sem chaves estáticas.
- Smoke: mensagem ao número de teste -> resposta correcta em <=15 s; pedido -> paga (ManualProvider; sandbox ProxyPay se KAM-056 existir).
- Rolling com 2 réplicas, verificação pós-deploy e reversão automática para o release.lock anterior.
- release.lock antes do deploy; tag SemVer só depois da verificação pós-deploy. Qualquer skip exige referência a ADR.
Não expandas escopo: backups (KAM-079), alertas (KAM-080). Testes: negativos, rolling sob carga, reversão. PR com o template da §7.
```

---

## KAM-079 — Backups pgBackRest fora do host, PITR e restauro mensal automático

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-076, ext:KAM-105 |
| Bloqueia | KAM-083, KAM-085 |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§8), `../docs/tecnica/08_Seguranca_Conformidade.md` (§6, §11, §13 N2, §15), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§2, req. 14), ADR-008, ADR-009, ADR-014 |

### Contexto
O doc 11 previa WAL e snapshots em MinIO **no mesmo VPS**: perder o *host* perdia tudo (RPO efectivo = total), o MinIO está arquivado e nunca se testava o restauro. O doc 09 §8 corrige: pgBackRest com repositório cifrado **noutro domínio de falha**, WAL contínuo, PITR de 7 dias e restauro mensal automático. O repositório de backup também é alojamento (ADR-008): `repo1` tem de ficar dentro da jurisdição autorizada (hipótese de trabalho: um 2.º local angolano) e, se sair de Angola, só com `apd_ref` (N2 de `../docs/tecnica/08` §13, a confirmar por parecer). Alvos do doc 00 §9: RPO ≤ 5 min, RTO ≤ 2 h. A dependência de KAM-105 (D1) não está declarada no backlog mestre e é tratada aqui como pré-condição para enviar dados **reais**.

### Objectivo
Entregar backups cifrados e verificáveis das bases `platform`, `medusa` e `chatwoot` e dos objectos do STO, com PITR de 7 dias, retenção de 35 dias e prova mensal e automática de que o restauro funciona.

### Critérios de Aceitação
- [ ] `pgbackrest check` e `pgbackrest info` verdes: completo semanal, diferencial diário, WAL contínuo com `archive_timeout = 60 s`; PITR 7 dias; retenção 35 dias; repositório cifrado AES-256.
- [ ] A métrica «idade do último WAL arquivado» dispara o alerta (> 300 s, P1, ligado a RB-K08) em ≤ 5 min quando o `archive_command` é interrompido em *staging* (teste de injecção de falha).
- [ ] PITR provado: com linhas-marcador inseridas a 1/s, o restauro para o instante T num *host* descartável contém os marcadores anteriores a T e nenhum posterior.
- [ ] Restauro completo a partir de `repo1` noutro *host*, com BD sintética ≥ 20 GB: tempo total medido e débito efectivo (Mbps) registados; compara-se com o orçamento do doc 09 §8.2 (≈ 30 min para 20 GB a 100 Mbps, ESTIMATIVA) e corrige-se o orçamento se divergir > 20%.
- [ ] Job mensal automático (restauro para *host* descartável + contagens por tabela + verificação da *hash-chain* do `audit_log` + *smoke*) corre 2× em *staging* com resultado arquivado; falha gera alerta P2.
- [ ] A chave de cifra tem cópia offline; um restauro numa máquina limpa usando só a cópia offline e o `repo1` tem êxito.
- [ ] `repo1` está noutro domínio de falha, fora do *host* primário e na jurisdição decidida em KAM-105; o destino consta do inventário de subprocessadores; enquanto não houver `apd_ref`, `prod` com dados reais não envia para ele (gate).
- [ ] Reaplicação do *erasure ledger* após restauro: com um sujeito apagado e um backup anterior ao apagamento, o *script* de reaplicação remove o sujeito (fixture).

### Detalhes Técnicos
- **Componentes:** OBS, STO, Postgres. Cobertura: bases `platform`/`medusa`/`chatwoot`; objectos do STO (replicação do bucket para o repositório); configuração em git; exportação cifrada semanal do cofre de segredos; âncora diária do último `row_hash` do `audit_log`.
- Valkey/Redis não é fonte de verdade: após restauro, o *outbox* republica eventos e os consumidores idempotentes (`events_consumed`) absorvem repetições; jobs BullMQ reconstroem-se.
- Defesa contra *ransomware*: restauro com credenciais distintas e **sem escrita a partir de produção**; viabilidade depende de *object lock*/versionamento no repositório (NÃO VERIFICADO para SeaweedFS e S3 gerido) — alternativa: *host* de backup que puxa (*pull*). Registar o que for possível.
- Contrato do *erasure ledger*: `erasure_ledger(subject_ref, erased_at)`, propriedade de KAM-070; aqui existe só o *hook* e a fixture.

### Testes Requeridos
- Injecção de falha do `archive_command`; PITR com marcadores; restauro completo cronometrado; restauro com a cópia offline da chave.
- Job mensal em *staging* (2 execuções) com falha forçada a gerar o alerta.
- Reaplicação do *erasure ledger* sobre um restauro.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Backups cifrados; chaves no cofre e cópia offline; sem segredos em logs ou configuração versionada.
- [ ] Destino registado no inventário de subprocessadores e coberto por `apd_ref` antes de dados reais (ADR-008).
- [ ] Métricas e alertas de backup nascem com o ticket e têm runbook (RB-K08).
- [ ] Dois revisores (dados de todos os tenants); documentação e orçamento de RTO actualizados.

### Handoff para Claude Code
```text
És o executor do ticket KAM-079 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-079), docs/tecnica/09_Topologia_Operacao_Escala.md (§8),
docs/tecnica/08_Seguranca_Conformidade.md (§6, §11, §13 N2) e o Compose de KAM-076.
Objectivo: pgBackRest com repo1 fora do host e dentro da jurisdição autorizada, PITR 7 dias, retenção 35 dias, restauro mensal automático.
- Configura stanza, cifra AES-256, archive_timeout=60s, semanal completo/diário diferencial; alerta se o último WAL > 5 min.
- Escreve o job de restauro mensal (host descartável, contagens, hash-chain do audit_log, smoke) e o script de medição de tempo e débito.
- Cobre as 3 bases e os objectos do STO; deixa o hook de erasure ledger com fixture.
- Não envies dados reais para nenhum destino sem apd_ref; em staging usa dados sintéticos.
Não expandas escopo: o simulacro cronometrado completo é KAM-085. Testes: injecção de falha, PITR com marcadores, restauro com chave offline. PR com o template da §7.
```

---

## KAM-080 — Métricas, logs JSON e alertas (Prometheus, Grafana, Loki)

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-076 |
| Bloqueia | KAM-081, KAM-082, KAM-083 |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§9, §13), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §5), ADR-010, ADR-018 |

### Contexto
O ADR-018 fixa observabilidade leve no Piloto: métricas próprias, logs sem conteúdo e custo por tenant; Langfuse fica fora de produção porque exige quatro serviços de estado e 16 GiB e os seus *traces* contêm conversas (transferência sob ADR-008). A sonda sintética externa é a única forma de detectar que o ingress parou sem alertas internos. A regra do doc 09 §9.2 é «alerta sem runbook é removido»; os runbooks completos são KAM-083 (depende deste), pelo que este ticket cria os *stubs* RB-K01 a RB-K10 (título, gatilho, severidade) e o *lint* que impede alertas sem `runbook_url`.

### Objectivo
Pôr em funcionamento métricas, logs JSON sem conteúdo, painéis, 12 alertas testados e uma sonda externa, desde a Fase 0, para que custo e fiabilidade existam desde o código.

### Critérios de Aceitação
- [ ] Logs JSON em todos os serviços, enviados por Alloy/Vector para Loki (instância única, retenção 30 dias); uma mensagem sintética com número de telefone e texto-canário não deixa nem o telefone nem o texto em Loki (teste de canário).
- [ ] Métricas Prometheus presentes: mensagens recebidas/enviadas por tenant; latência de ingress e de resposta (p50/p95/p99); fila (profundidade e idade do mais antigo); *handoff*; callbacks (ok/falhados/reconciliados); custo LLM por tenant; erros Meta 130429 e 131049; `quality_rating`; idade do WAL; memória/CPU por serviço.
- [ ] *Lint* de cardinalidade: `tenant_id` permitido como etiqueta; `contact_id`, telefone e BSUID proibidos (o CI falha).
- [ ] As 12 regras do doc 09 §9.2 existem com severidade P1/P2/P3 e `runbook_url` válido; cada uma dispara numa injecção de falha em *staging* e chega ao canal certo; CI falha para alerta sem runbook.
- [ ] Sonda externa (fora do *host* e do fornecedor) envia uma mensagem de teste a cada 5 min ao número de teste de produção e verifica `/healthz`; ao parar o GWY em *staging*, o alerta P1 «ingress parado» é recebido em ≤ 11 min.
- [ ] Painéis como código (JSON provisionado): caminho de venda, Meta, pagamentos, infraestrutura; Grafana só por VPN; consumo da pilha de monitorização medido (alvo ≤ 1,5 GB, ESTIMATIVA).
- [ ] Os webhooks de *status* persistem `pricing` (`billable`, `category`, `type`) por mensagem, expostos como métrica agregada por tenant e categoria.

### Detalhes Técnicos
- **Componentes:** OBS (Prometheus, Alertmanager, Grafana, Loki, Alloy/Vector, *exporters*), GWY, AGR, EVT, HND, LLM. Campos de log permitidos em `../docs/tecnica/08` §7.3; nunca conteúdo de mensagens (X-11 é de KAM-068; aqui é o teste de canário).
- Alertas (doc 09 §9.2): ingress parado (sonda 2× ou 0 mensagens > 10 min em horário comercial, P1); fila (idade > 2 min, P2); latência (p95 > 8 s por 10 min, P2); callbacks (falhas HMAC > 3/h ou pagamento por reconhecer, P1); WAL (> 5 min, P1); restauro mensal falhado (P2); *quality rating* (amarelo P3, vermelho P1); *free tier* (80% P3, 100% P2); `account_update` (P2); orçamento LLM (> 80% do diário, P3); segredo a expirar (< 14 dias, P3); memória (> 80% sustentada, P3).
- Horário comercial: 07:00–23:00 WAT. A sonda não transporta dados pessoais, mas o serviço escolhido regista-se no inventário de subprocessadores (KAM-069).
- A tabela de chamadas LLM sem conteúdo é de KAM-030 (`llm_call_log`); aqui só se exporta a métrica.

### Testes Requeridos
- Canário de PII em Loki; *lint* de etiquetas; validação das regras de alerta (`promtool`) e injecção de falha por alerta.
- Teste da sonda externa com GWY parado; verificação de retenção Loki de 30 dias na configuração.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Logs sem conteúdo nem identificadores directos; sem segredos em logs ou painéis (ADR-010).
- [ ] Métricas e custo nascem com a funcionalidade (ADR-018); painéis versionados.
- [ ] 0 alertas sem runbook (existe *stub* para cada `runbook_url`).
- [ ] Documentação actualizada (catálogo de métricas, canal de alertas e escalamento inicial).

### Handoff para Claude Code
```text
És o executor do ticket KAM-080 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-080), docs/tecnica/09_Topologia_Operacao_Escala.md (§9, §13),
docs/tecnica/08_Seguranca_Conformidade.md (§7.3) e o Compose de KAM-076.
Objectivo: métricas, logs JSON sem conteúdo, painéis, 12 alertas com runbook e sonda sintética externa.
- Prometheus/Alertmanager/Grafana/Loki/Alloy como código; Loki 30 dias; etiquetas proibidas: contact_id, telefone, BSUID.
- Cria os stubs RB-K01..RB-K10 e o lint que falha se um alerta não tiver runbook_url válido.
- Escreve o teste de canário de PII e os testes de injecção de falha por alerta; a sonda corre fora do host.
- Nunca registes conteúdo de mensagens; não instales Langfuse em produção.
Não expandas escopo: runbooks completos (KAM-083), SLOs (KAM-082), custo (KAM-081). PR com o template da §7.
```

---

## KAM-081 — Custo por tenant e dashboard de unit economics

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-030, KAM-080, KAM-023 |
| Bloqueia | KAM-117, KAM-124 |
| Responsável sugerido | Plataforma/SRE (com Responsável de Produto) |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§9.1, §9.3, §14, §17), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§3), `specs/EPIC-10_Spikes_Validacao_Gates.md` (KAM-109), ADR-005, ADR-018 |

### Contexto
O princípio 11 do doc 00 exige custo medido por tenant. O doc 09 §14 estima o custo de uma PME típica (300 conversas/mês × 8 turnos): LLM+STT ≈ $1,9 (cenário baixo), $6,4 (misto) ou $28 (tudo Sonnet), e Meta ≈ $7,5 (1.880 mensagens acima das 1.000 grátis a $0,004). São **ESTIMATIVAS**: o preço de LLM é reconferido antes de fixar tarifas e o volume por PME é medido no Piloto (H6). Este dashboard é o instrumento que alimenta H6 (custo ≤ 15% da mensalidade, KAM-109) e o ponto de equilíbrio (≈ 8 a 28 PMEs, hipótese).

### Objectivo
Calcular e mostrar, por tenant e por conversa, o custo de LLM, STT e mensagens Meta, o consumo do *free tier*, a margem face à mensalidade e o custo fixo por PME, com reconciliação contra as fontes.

### Critérios de Aceitação
- [ ] Vista `v_tenant_cost_daily` (tenant, dia, rubrica, USD, Kz): LLM (de `llm_call_log`), STT, Meta por categoria (de `pricing` dos *status*), com `fx_aoa_per_usd` parametrizável (omissão 913, INDÍCIO) e modo de sensibilidade +7,4% (981) e +35% (1.232).
- [ ] «Conversa» definida como mensagens do mesmo contacto sem pausa > 24 h; comando `h6-export` produz a amostra das últimas N conversas (omissão 500) com custo LLM, STT e Meta, percentis p50/p90/p99 e rácio custo/mensalidade; validado numa *fixture* com totais conhecidos (igualdade exacta).
- [ ] Reconciliação em *staging* com tráfego sintético de 7 dias: custo LLM de `llm_call_log` vs *spend logs* do LiteLLM com desvio ≤ 2% por tenant (*proposta*); custo Meta calculado vs tarifa (0,004 USD após 1.000/número/mês) com desvio ≤ 1% na *fixture*.
- [ ] Painel do *free tier*: mensagens/1.000 por número com *reset* à 00:00 do fuso da conta; alerta a 80% e 100% (reutiliza KAM-023); alerta de orçamento LLM diário > 80% por tenant.
- [ ] Painel de unit economics: custo fixo mensal (infra + ferramentas) ÷ n.º de PMEs, margem por mensalidade (parâmetro, 30–60 mil Kz), ponto de equilíbrio e comparação **estimado vs medido** com os valores do doc 09 §14.3–14.4; desvio > 30% numa rubrica gera um item de revisão do doc.
- [ ] Parâmetro `meta_payer = pme|kamba`; o painel mostra «custo para a KAMBÁ» e «custo total para o cliente (inclui Meta)».
- [ ] Sem conteúdo nem `contact_id` nos painéis ou vistas expostas; acesso por VPN e papel.

### Detalhes Técnicos
- **Componentes:** OBS, LLM, TEN, Postgres. `llm_call_log` (KAM-030) corresponde à tabela `llm_calls` descrita em `../docs/tecnica/09` §9.3 (tenant_id, turn_id, model, tokens_in, tokens_out, cached, cost_usd, latency_ms, outcome), sem conteúdo.
- Os preços Meta por mensagem consomem-se de KAM-015/KAM-023; se não existir tabela de `pricing` por mensagem, abre-se um `fix` (não se cria aqui).
- Fixos de referência (ESTIMATIVA, a substituir por cotações): infra Piloto $450–680/mês, ferramentas $20–50, LLM+STT $20–65.
- Reconciliação com a factura real da Meta é **manual e mensal** (Billing Hub da PME; para um Tech Provider a visibilidade da factura é NÃO VERIFICADA): documentar o procedimento.
- Preços de LLM e tokenizador (+30% nos modelos Anthropic ≥ 4.7): tabela de preços versionada com data de leitura; a subida do Gemini Flash 3.7/3.8 a 2027-01-01 é um evento da *watch list*.

### Testes Requeridos
- Unit da fórmula de custo (por rubrica, câmbio, *free tier*); *fixture* de conversas com totais conhecidos.
- Integração: reconciliação LiteLLM × `llm_call_log`; teste de ausência de PII nas vistas.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Custo por tenant e por conversa disponível (ADR-018); sem conteúdo nem PII nas vistas.
- [ ] Tabela de preços versionada com data; valores de mercado marcados como a reconferir.
- [ ] Documentação do procedimento de reconciliação mensal e de `h6-export`; ligação a KAM-109.
- [ ] Testes unitários e de integração verdes; cobertura não regride.

### Handoff para Claude Code
```text
És o executor do ticket KAM-081 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-081), docs/tecnica/09_Topologia_Operacao_Escala.md (§9, §14),
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§1) e o esquema de llm_call_log de KAM-030.
Objectivo: custo por tenant e por conversa (LLM, STT, Meta), free tier, margem e comparação estimado vs medido.
- Cria a vista v_tenant_cost_daily, o comando h6-export (amostra de N conversas, percentis, rácio à mensalidade) e os painéis.
- Preços e câmbio são parâmetros versionados com data; não fixes tarifas de terceiros como factos.
- Reconcilia LiteLLM x llm_call_log (<=2%) e Meta (tarifa 0,004 USD acima de 1.000 por número).
- Nenhum conteúdo, telefone ou contact_id em vistas ou painéis.
Não expandas escopo: os alertas de free tier são de KAM-023; a decisão H6 é de KAM-109. PR com o template da §7.
```

---
## KAM-082 — SLOs, orçamento de erro e alertas

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-080 |
| Bloqueia | KAM-110 |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§10, §16, §17), `../docs/tecnica/00_Arquitectura_Solucao.md` (§9), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), ADR-018 |

### Contexto
O doc 00 §9 fixa 99,5% de disponibilidade do caminho de venda no Piloto (99,9% na Escala), ack do webhook < 500 ms e RPO/RTO. O doc 09 §10 traduz isto em 8 SLIs com orçamento de erro a 30 dias: 99,5% = 216 min (3,6 h). Esse orçamento **não cobre** noites inteiras sem resposta, pelo que a sonda externa (KAM-080) e a rotação de *on-call* são parte do SLO e não acessórios. A política de orçamento (> 50% consumido em 14 dias congela mudanças não urgentes) só tem valor se estiver ligada ao *pipeline*.

### Objectivo
Medir os 8 SLIs, mostrar o orçamento restante, alertar por consumo (*burn rate*) e ligar a política de orçamento e a rotação de *on-call* a regras verificáveis.

### Critérios de Aceitação
- [ ] `ops/slo.md` define os 8 SLIs do doc 09 §10 (numerador, denominador, janela de 30 dias, fonte, SLO, orçamento): disponibilidade do caminho de venda 99,5% (216 min); ack < 500 ms em 99,9% dos pedidos; perda de mensagens = 0; p95 de resposta texto ≤ 8 s e voz ≤ 12 s; callback → cliente notificado p95 ≤ 30 s e p99 ≤ 2 min; reconciliação de pagamentos por reconhecer ≤ 15 min; frescura do backup (WAL ≤ 5 min, restauro mensal OK); 0 horas de número em vermelho > 24 h.
- [ ] *Recording rules* e painel mostram o orçamento restante; com 30 min de falha injectada do ingress em *staging* o orçamento desce 13,9% (30/216) e o alerta de *burn rate* dispara.
- [ ] «Perda de mensagens» operacionalizada como: ids aceites no ingress sem desfecho (processado, duplicado ou DLQ) após 15 min = 0 (*proposta*); testada com uma mensagem retida artificialmente.
- [ ] Alertas de *burn rate* rápido e lento activos (*proposta*: 2% do orçamento numa hora → P2; 5% em 6 h → P3), calibrados e documentados.
- [ ] Política: > 50% do orçamento consumido em 14 dias marca o estado `congelado`; o gate 16 recusa deploys não urgentes nesse estado (excepto aprovação do Arquitecto registada); 100% → só trabalho de fiabilidade; testes do gate.
- [ ] Janelas de manutenção anunciadas fora de 07:00–23:00 WAT contam como indisponibilidade **só** se afectarem mensagens (regra implementada e testada com duas janelas).
- [ ] *On-call*: rotação semanal com ≥ 3 pessoas, cobertura 07:00–23:00 WAT; fora disso um alerta P1 chama apenas o primário; um alerta não reconhecido escala ao secundário em 15 min e depois ao Arquitecto (teste de simulação).

### Detalhes Técnicos
- **Componentes:** OBS, Alertmanager, pipeline de KAM-078. SLO de 99,9% da Escala fica documentado mas inactivo.
- O SLI de disponibilidade combina a sonda sintética (5 min) com o tráfego real; o horário comercial é 07:00–23:00 WAT, o SLO é medido 24/7.
- Alvos auxiliares do doc 09 §17: tempo para fechar um alerta P1 ≤ 2 h; 0 alertas sem runbook; memória ≤ 65% em hora de ponta. *Post-mortem* sem culpa em ≤ 5 dias; compensação de *on-call* e dia de folga após P1 nocturno (decisão de gestão, fora do código).
- Os valores de *burn rate* e de atraso de 15 min são propostas; calibram-se nos primeiros 30 dias.

### Testes Requeridos
- Injecção de falha de 30 min e verificação aritmética do orçamento; teste do gate 16 em estado `congelado`.
- Simulação de escalamento de *on-call* com alerta não reconhecido; teste das duas janelas de manutenção.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Métricas dos SLIs sem conteúdo nem PII; painéis versionados.
- [ ] Cada alerta de SLO tem runbook; relatório mensal de SLO com modelo.
- [ ] Rotação de *on-call* publicada com nomes e substitutos (prova do critério de ≥ 3 pessoas).
- [ ] Documentação actualizada; alterações de SLO passam por registo.

### Handoff para Claude Code
```text
És o executor do ticket KAM-082 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-082), docs/tecnica/09_Topologia_Operacao_Escala.md (§10, §16, §17)
e as métricas de KAM-080.
Objectivo: SLIs, orçamento de erro, alertas de burn rate, política de congelamento ligada ao gate 16 e simulação de on-call.
- Escreve ops/slo.md e as recording rules dos 8 SLIs (216 min = 99,5% a 30 dias).
- Implementa o estado congelado e o teste do gate 16; marca como proposta os valores de burn rate.
- Não inventes ligações a pessoas reais: a rotação é um ficheiro com marcadores a preencher pelo Responsável de Produto.
Não expandas escopo: runbooks são KAM-083. Testes: injecção de 30 min, congelamento, escalamento. PR com o template da §7.
```

---

## KAM-083 — Runbooks operacionais (Meta, facilitador, LLM, rating, free tier, tokens, segredos)

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-080, KAM-021, KAM-023, KAM-017, KAM-079 |
| Bloqueia | KAM-110 |
| Responsável sugerido | Plataforma/SRE (com Responsável de Segurança) |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§9.2, §12, §13), `../docs/tecnica/08_Seguranca_Conformidade.md` (§5, §10), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.5, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` |

### Contexto
A regra do doc 09 é «alerta sem runbook é removido». O doc 09 §13 lista 10 runbooks (RB-K01 a RB-K10): Meta em baixo, facilitador em baixo, LLM em baixo ou sem *budget*, *quality rating* vermelho, *free tier* esgotado, token/ligação invalidado (`PARTNER_REMOVED`), rotação de segredos, BD/PITR, *flood* e *denial of wallet*, incidente de segurança. O título do backlog nomeia 7; os 10 estão aqui por serem os que os alertas de KAM-080 referenciam. Os factos Meta usados nos runbooks são CONFIRMADOS (E1): sem método de pagamento a Meta **deixa de entregar** service messages após as 1.000 grátis; qualidade baixa já não reduz o limite mas pode pausar templates; a re-sincronização de histórico em coexistência é um passo único e com prazo de 24 h; os webhooks falhados repetem até 7 dias.

### Objectivo
Transformar os stubs de KAM-080 em 10 runbooks executáveis por quem não esteve na conversa, ensaiados por outra pessoa que não o autor, e ligados 1:1 aos alertas.

### Critérios de Aceitação
- [ ] `ops/runbooks/RB-K01..RB-K10.md` seguem o modelo: cenário, alertas que o activam, severidade, diagnóstico (consultas e comandos exactos), mitigação passo a passo, critério de recuperação, escalamento, comunicação, dono, data da última revisão e do último ensaio.
- [ ] Cada runbook foi ensaiado por uma pessoa distinta do autor (mesa-redonda para K02, K04–K07, K09, K10; injecção de falha em *staging* para K01, K03; K08 por mesa-redonda aqui e simulacro completo em KAM-085); tempos e lacunas registados; 0 lacunas abertas à data de fecho.
- [ ] Verificação em CI de bijecção alerta ↔ runbook: todo o alerta de KAM-080 aponta para um runbook existente e todo o runbook tem pelo menos um alerta ou gatilho manual declarado.
- [ ] Os textos de comunicação à PME (PT-AO) para K01, K02, K04, K05 e K06 estão redigidos e aprovados pelo Responsável de Produto, com **canal alternativo** definido (e-mail/SMS) e registado no inventário de subprocessadores; o canal operacional da KAMBÁ segue a decisão D10 (entretanto, o canal do fundador).
- [ ] K07 (segredos) especifica a ordem e as janelas: GWY aceita `[actual, anterior]`; ProxyPay (chave API = chave HMAC) com reconciliador activo; LiteLLM e provedores primeiro em incidente; registo em `audit_log`; ensaiado em *staging*.
- [ ] Nenhum runbook contém segredos, dados pessoais ou conteúdo de conversa; os segredos citam-se pelo nome da entrada no cofre.
- [ ] Calendário do *game day* semestral (injecta K01, K03, K08) com a primeira data fixada.

### Detalhes Técnicos
- **Componentes:** OBS, GWY, LLM, PAY, HND, STO. Fontes: doc 09 §13 (tabela de sinais, diagnóstico, mitigação), degradação N0–N6 do §12, estados de canal de `../docs/tecnica/01` §10.5.
- K04: pausar marketing, rever templates, reduzir frequência, contactar *Direct Support*; tenant → `suspenso` se persistir. K05: modo conciso (1 mensagem por turno), exigir método de pagamento no Billing Hub, avisar a PME do custo (0,004 USD). K06: alertar o dono por canal alternativo, fluxo de reconexão, tenant → `suspenso` até repor. K09: bloqueio e *handoff*, *budget* por contacto, limite a nível de CDN.
- K10 alinha-se com `../docs/tecnica/08` §10: a notificação à APD em 72 h é boa prática e possível obrigação da Circular 02 (a confirmar por parecer; não se afirma como lei no runbook).
- Dependências não declaradas no backlog mestre que o autor deve verificar: K02 usa o reconciliador de KAM-056; K04/K05 usam KAM-021/KAM-023; K06 usa KAM-017; K07 usa KAM-010/KAM-072.

### Testes Requeridos
- Ensaios documentados (mesa-redonda e injecção de falha) com folha de tempos; verificação de CI da bijecção alerta ↔ runbook.
- *Scan* de segredos e de PII sobre `ops/runbooks/`.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Sem segredos nem PII; textos às PMEs em português de Angola.
- [ ] 0 alertas sem runbook (ADR-018); runbooks versionados com data de revisão.
- [ ] Factos de terceiros marcados com estado (CONFIRMADO/INDÍCIO/NÃO VERIFICADO) e fonte.
- [ ] Dois revisores (Plataforma e Segurança); documentação actualizada.

### Handoff para Claude Code
```text
És o executor do ticket KAM-083 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-083), docs/tecnica/09_Topologia_Operacao_Escala.md (§9.2, §12, §13),
docs/tecnica/08_Seguranca_Conformidade.md (§5, §10), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§10.5) e os stubs de KAM-080.
Objectivo: 10 runbooks executáveis (RB-K01..RB-K10), com modelo único, comandos exactos e textos às PMEs.
- Preenche cada stub a partir das tabelas do doc 09; não acrescentes factos de terceiros que não estejam nas fontes (marca NÃO VERIFICADO).
- Escreve o modelo, a folha de ensaio (tempos, lacunas) e o check de CI da bijecção alerta<->runbook.
- Prepara o roteiro de cada ensaio; os ensaios e a aprovação dos textos são feitos por humanos.
- Sem segredos nem PII nos ficheiros.
Não expandas escopo: o simulacro de DR é KAM-085. PR com o template da §7.
```

---

## KAM-084 — Teste de carga e validação do dimensionamento

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-076, KAM-013, KAM-015, KAM-025, KAM-031, KAM-024 |
| Bloqueia | — |
| Responsável sugerido | Plataforma/SRE |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§4, §11, §12, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.2, §2.10), ADR-009 |

### Contexto
O dimensionamento do doc 09 §4 é ESTIMATIVA, salvo os mínimos oficiais de Chatwoot (≥ 4 GB e 4 núcleos, até 10.000 conversas/dia) e Medusa (≥ 2 GB). O total de ≈ 18,6 GB (58% de 32 GB), os ≈ 50 conversas simultâneas por processo AGR, o limite de ~10k jobs/min do BullMQ (NÃO VERIFICADO) e o consumo de monitorização (1,5 GB) nunca foram medidos. O volume do Piloto (10 PMEs, ~25–30 mil mensagens/mês) é pequeno; o ensaio existe para achar a **primeira fronteira** (×10 para o perfil Clusters, rajada de reentrega da Meta, *flood*) e para corrigir o doc 09 com números.

### Objectivo
Medir consumo, latência, ack e comportamento sob carga, falha de LLM e rajada no perfil P0, e produzir um relatório que confirma (±20%) ou corrige cada estimativa do doc 09 §4.2 e define o limite de cada recurso.

### Critérios de Aceitação
- [ ] Relatório `../docs/tecnica/evidencia/Carga_Dimensionamento.md` com uma linha por serviço do §4.2: memória estimada, medida (p50/p95 em carga), veredicto («confirmado ±20%» ou «corrigido para X») e proposta de novo `mem_limit`.
- [ ] Cenário S1 (pico do Piloto, 10 PMEs) e S2 (×10): memória ≤ 65% (≤ 20,8 GB em 32 GB) e CPU ≤ 60%; ack do webhook < 500 ms em ≥ 99,9%; idade da fila < 2 min; 0 mensagens perdidas por reconciliação de ids. Se S2 falhar, regista-se o limite como fronteira do perfil P0.
- [ ] Cenário de rampa até saturação: identifica-se o primeiro recurso saturado (AGR, Postgres, Chatwoot, BullMQ ou LiteLLM) e a carga a que ocorre; o ponto «~50 conversas simultâneas por processo AGR» e «~10k jobs/min» ficam medidos ou continuam marcados NÃO VERIFICADO com o motivo.
- [ ] Cenário de rajada: reentrega de 1 h de backlog a 20× o ritmo normal (reentrega Meta até 7 dias); sem perda, sem duplicados, fila drenada num tempo registado.
- [ ] Cenário de degradação: LiteLLM com latência de 20 s e 5xx injectados activa N1/N2 (fluxo determinístico com menus ≤ 10 linhas e botões ≤ 3, estado do pedido e *handoff*) e o utilizador recebe resposta em ≤ 10 s; recuperação automática ao normalizar.
- [ ] Cenário de limites Meta: o *rate limiter* por número respeita 20 mps (coexistência) e 80 mps (Cloud API) com o simulador; erro 130429 simulado leva a *backoff* sem martelar.
- [ ] Cenário *flood*: um contacto a 100 mensagens/min é limitado e redireccionado a *handoff* sem afectar os outros tenants (RB-K09); custo LLM do contacto limitado pelo *budget*.
- [ ] Custo do ensaio e do *host* temporário registados; o relatório lista os itens do doc 09 que mudam (§4.2, §14.4).

### Detalhes Técnicos
- **Componentes:** GWY, EVT, AGR, LLM (com *stub* de latência configurável e uma amostra com LLM real), HND, Postgres, OBS. Ferramenta de carga a escolher (*proposta*: k6 ou Locust; licença registada no SBOM de ferramentas).
- Perfil de partida (ESTIMATIVA do doc 09 §14.1): 10 PMEs × 300 conversas × 8 turnos = 24.000 mensagens de cliente/mês e ≈ 28.800 do bot; 25% notas de voz de 30 s. O factor de hora de ponta é uma hipótese a medir, não a assumir.
- Corre no *host* de produção **antes do go-live** ou num clone 8 vCPU/32 GB criado por IaC; nunca com dados reais.
- Usa o simulador de webhooks de KAM-024. Dependências efectivas não declaradas no backlog mestre: o ensaio só é significativo com GWY, outbound, AGR e Vendedor operacionais (KAM-013, KAM-015, KAM-025, KAM-031).

### Testes Requeridos
- Os 7 cenários acima com *scripts* versionados e repetíveis; reconciliação de ids em todos.
- Verificação de que a medição de memória usa *working set* (não reservado) e a mesma definição do doc 09 §1.4.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Nenhum dado real usado; tráfego e dados sintéticos; sem segredos em *scripts*.
- [ ] Resultados e desvios registados; itens do doc 09 a corrigir abertos como tickets `fix`/docs.
- [ ] Métricas do ensaio disponíveis nos painéis de KAM-080; custo do ensaio registado.
- [ ] Scripts e relatório versionados; documentação actualizada.

### Handoff para Claude Code
```text
És o executor do ticket KAM-084 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-084), docs/tecnica/09_Topologia_Operacao_Escala.md (§4, §11, §12, §14),
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§5) e o simulador de KAM-024.
Objectivo: validar ou corrigir as estimativas de dimensionamento com 7 cenários de carga no perfil P0.
- Escreve os scripts de carga (S1, S2, rampa, rajada, degradação, limites Meta, flood) e a recolha de memória working set por serviço.
- Gera o relatório com a tabela estimado vs medido e veredicto por serviço; nunca marques como confirmado o que não mediste.
- Usa dados sintéticos e um host que não tenha dados reais; regista o custo do ensaio.
- Se um serviço necessário (GWY, AGR, Vendedor) não existir, pára e di-lo.
Não expandas escopo: ajustar limites no Compose é um PR de seguimento. PR com o template da §7.
```

---

## KAM-085 — Simulacro de recuperação (DR drill) com RTO medido

| Campo | Valor |
|---|---|
| Epic | EPIC-08 — Topologia e Operação |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-079 |
| Bloqueia | KAM-110 |
| Responsável sugerido | Plataforma/SRE (executa o *on-call* que não escreveu o runbook) |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§8.2, §8.3, §13 RB-K08), `../docs/tecnica/08_Seguranca_Conformidade.md` (§11), `specs/00_KAMBA_Carta.md` (§5), ADR-008, ADR-009 |

### Contexto
Os alvos RPO ≤ 5 min e RTO ≤ 2 h (doc 00 §9) só valem se forem medidos. O doc 09 §8.2 orça o RTO em ≈ 105 min: detecção 10 + decisão 10 + novo *host* por IaC 30 + restauro da base (BD ≤ 20 GB ≈ 30 min a 100 Mbps; 50 GB ≈ 70 min) + *replay* de WAL 10 + verificação (*hash-chain*, E2E) e DNS 15. É uma ESTIMATIVA. Com BD > 40 GB o RTO de 2 h deixa de ser seguro e o perfil P1 (réplica de espera) passa a necessário. A Carta (§5) exige «backups com restauro testado e RTO medido» para o Piloto estar *done*. Este ticket é o primeiro exercício trimestral cronometrado.

### Objectivo
Executar, num ambiente de ensaio com dados sintéticos, a perda do *host* de produção e a corrupção lógica, medir RTO e RPO reais passo a passo, e decidir com números se a Fase 1 mantém o perfil P0 ou exige réplica de espera.

### Critérios de Aceitação
- [ ] Cenário A (perda do *host*): novo *host* por IaC + restauro PITR a partir do `repo1` noutro *host*; **RTO medido ≤ 2 h** e **perda de dados ≤ 5 min** (linhas-marcador a 1/s até ao instante da falha); cada passo do orçamento (detecção, decisão, IaC, restauro, *replay*, verificação, DNS) cronometrado e comparado com os 105 min.
- [ ] Cenário B (corrupção lógica): PITR para antes do erro (migração defeituosa injectada) + *replay* de eventos do *outbox*; 0 efeitos de negócio duplicados (consumidores idempotentes, `events_consumed`).
- [ ] Verificações pós-restauro: contagens por tabela, *hash-chain* do `audit_log` íntegra, *erasure ledger* reaplicado, Valkey/BullMQ reconstruídos, *smoke* ponta a ponta verde.
- [ ] Cenário C (cofre indisponível): sem acesso ao Doppler, o procedimento usa a exportação cifrada semanal e o RTO adicional é registado.
- [ ] Executado por uma pessoa de *on-call* que não escreveu RB-K08, **só com o runbook**; todas as ambiguidades encontradas corrigidas no runbook (0 abertas).
- [ ] BD de ensaio ≥ 20 GB; extrapolação para 50 GB com o débito medido; se o RTO extrapolado > 2 h ou se BD prevista > 40 GB, abre-se o ticket de réplica de espera (P1).
- [ ] Cenário de credenciais comprometidas / *ransomware* ensaiado em mesa-redonda (a execução completa pode exceder 2 h, aceite e documentado).
- [ ] *Post-mortem* sem culpa em ≤ 5 dias com acções datadas; resultado arquivado; próxima data trimestral fixada; falha de objectivo = incidente P2.

### Detalhes Técnicos
- **Componentes:** pgBackRest (KAM-079), IaC (KAM-075), Compose (KAM-076), OBS, STO, EVT. O ensaio usa `staging`/clone com dados sintéticos; **nunca** restaura dados reais fora do destino autorizado (ADR-008).
- DNS: TTL pré-configurado (KAM-075); mede-se o tempo de propagação real.
- Instrumentação: relógio comum, folha de passos com carimbos, linhas-marcador e *script* que calcula RPO como diferença entre o último marcador restaurado e o último marcador confirmado antes da falha.
- Cenários não cobertos aqui: perda de região completa (usa o mesmo procedimento noutro local; ensaiado trimestralmente) e perda do número/token Meta (RB-K04/K06, a Meta re-entrega webhooks até 7 dias).

### Testes Requeridos
- Os cenários A, B e C com cronometragem e verificações pós-restauro; repetição do cenário A se o resultado ficar entre 100 e 120 min.
- Verificação de que o runbook, seguido à letra, basta (observador regista cada desvio).

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Nenhum dado real; sem segredos nos registos do exercício.
- [ ] RTO e RPO medidos registados em `../docs/tecnica/evidencia/` e no painel de SLO (frescura do backup).
- [ ] RB-K08 actualizado; *post-mortem* publicado; decisão sobre réplica de espera registada com dono e data.
- [ ] Documentação do orçamento de RTO corrigida com os valores medidos.

### Handoff para Claude Code
```text
És o executor do ticket KAM-085 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-08_Topologia_Operacao.md (bloco KAM-085), docs/tecnica/09_Topologia_Operacao_Escala.md (§8, §13 RB-K08),
docs/tecnica/08_Seguranca_Conformidade.md (§11) e os artefactos de KAM-079.
Objectivo: preparar e analisar um simulacro de DR com RTO e RPO medidos.
- Prepara a folha de passos com carimbos, o script de linhas-marcador (1/s) e o script que calcula RPO e RTO por passo.
- Prepara o gerador da base sintética (>=20 GB) e o script de verificações pós-restauro (contagens, hash-chain, smoke).
- Gera o relatório e o modelo de post-mortem; a execução do simulacro e as decisões são feitas por humanos (on-call), seguindo só o runbook.
- Não uses dados reais nem o repositório de produção.
Não expandas escopo: a réplica de espera, se necessária, é ticket novo. PR com o template da §7.
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| Risco / item | Estado | Decisão | Tratamento no epic |
|---|---|---|---|
| Cotações de Raxio, Paratus, Angola Cables e Cloud Nacional; serviços geridos em Luanda; custo ×1–2 de JNB como hipótese | NÃO VERIFICADO | D1 | KAM-105 obtém cotações; KAM-075 e KAM-077 são portáteis; custo de infra §14 é ESTIMATIVA até cotação |
| Latência real Luanda ↔ JNB / UE / Meta | INDÍCIO (biblioteca) / NÃO VERIFICADO | D1 | KAM-077 mede RTT em 24 h |
| Localização do `repo1` na jurisdição autorizada; backups cifrados fora de Angola com chave em Angola | Aguarda parecer (N2) | D1, D9 | KAM-079 só envia dados reais após `apd_ref`; destino no inventário (KAM-069) |
| CDN/WAF como subprocessador com acesso a conteúdo (N1) | Aguarda parecer | D12 | KAM-077: caminho de webhooks directo à origem por omissão |
| Valkey com BullMQ, Chatwoot e Medusa; licença actual do Redis | NÃO VERIFICADO | D12 | KAM-076: teste em *staging*; ADR-P09 só se passar |
| SeaweedFS: *multipart*, URLs assinadas, *object lock* | NÃO VERIFICADO | D6 | KAM-076 ensaia se D6 = SeaweedFS; senão S3 gerido |
| Requisitos de CPU e versões de Node do Medusa | NÃO VERIFICADO | D3 | KAM-076 confirma em `engines`; KAM-084 mede |
| Garantias de entrega do BullMQ e limite de ~10k jobs/min | NÃO VERIFICADO | ADR-009 | KAM-084 mede; handlers idempotentes em qualquer caso |
| Memória por serviço (18,6 GB), custo de infra ($450–680), custo por PME ($49–80 no Piloto) | ESTIMATIVA | — | KAM-084 e KAM-081 medem; KAM-085 valida o RTO |
| Timeout e *retry* exactos do webhook Meta; comportamento de desactivação após falhas | NÃO VERIFICADO | D5 | KAM-078 e KAM-084 testam o ack < 500 ms; pergunta em KAM-101 |
| Quem paga os custos em USD (Meta, cloud, LLM) | Não decidido | D9 | KAM-081 parametriza `meta_payer`; decisão em KAM-104/KAM-105 |
| Preços de LLM e tokenizador (+30%); Gemini Flash dobra a 2027-01-01 | INDÍCIO-forte | ADR-005 | KAM-081 usa tabela de preços versionada com data |
| Equipa pequena em *on-call* (3–4 pessoas); noites sem cobertura | Risco operacional | — | KAM-082: sonda externa, degradação automática, escalamento de 15 min |
| Segredos num SaaS (Doppler) em desastre | Risco | — | KAM-085 cenário C; cópia local cifrada semanal |
| Repositório de backup sem *object lock* (resistência a *ransomware*) | NÃO VERIFICADO | D6 | KAM-079: alternativa *pull*; registo do que for possível |
| Câmbio USD/AOA (913; spread ~7%; choque +35%) | INDÍCIO | — | KAM-081: modo de sensibilidade |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: KAM-075 a KAM-085 (topologia, alojamento, CI/CD, backups, observabilidade, SLOs, runbooks, carga e DR). | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-129: as 13 referências aos anexos E1–E4 passam a `../docs/tecnica/evidencia/…`; antes não resolviam de posição nenhuma. A referência ao relatório `Carga_Dimensionamento.md` (saída do KAM-084) **já estava correcta** e não foi tocada. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-145: os **21** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
