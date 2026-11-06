# EPIC-08 — Topologia e Operação

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Topologia e Operação |
| Versão | 1.7 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/09_Topologia_Operacao_Escala.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/EPIC-01_Fundacoes_Dados.md`, `specs/EPIC-07_Seguranca_Conformidade.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/00_KAMBA_Carta.md` |

---

## 1. Visão do Epic

Este epic põe a KAMBÁ a **correr de forma operável**: ambientes (`dev`, `staging`, `prod`) por infraestrutura como código, o **Compose de produção do conjunto reduzido** (≈ 18,6 GB de *working set*, ESTIMATIVA: GWY, AGR, Chatwoot, Medusa, `onboarding-web`, Postgres 18.6, Valkey/Redis, LiteLLM, STO, proxies, monitorização, pgBackRest), alojamento e borda, CI/CD com os gates 14–18 de `01_Engineering_Standards_e_Handoff.md` §4, backups com PITR e restauro testado, observabilidade sem conteúdo, SLOs, runbooks, custo por tenant, ensaio de carga e simulacro de recuperação. Existe porque o desenho exploratório tinha três defeitos que o doc 09 corrige: 13 serviços numa máquina de 8 vCPU/32 GB (≈ 42 GB com Langfuse v4), backup no mesmo *host* que a base de dados (RPO efectivo = total) e dependência de MinIO (arquivado desde 2026-04).

O epic concretiza **ADR-008** (alojamento, *backups*, CDN e observabilidade são «alojamento»; nenhum dado pessoal de produção sai de Angola sem registo da APD), **ADR-009** (Redis/Valkey reconstruível a partir do *outbox*), **ADR-014** (`StorageProvider`, sem MinIO), **ADR-018** (observabilidade leve: Langfuse **não** entra em produção no Piloto; tabela de chamadas LLM sem conteúdo), **ADR-002** (n8n e Typebot fora de produção), **ADR-005** (LiteLLM ≥ 1.83.0 por *digest* e cosign), **ADR-006** (Postgres 18.6), **ADR-001** (alertas `PARTNER_REMOVED`, 20 mps em coexistência) e **ADR-019** (`onboarding-web` no Compose, sem vitrine). As propostas locais ADR-P06 a ADR-P10 do doc 09 (host único, pgBackRest, sem Langfuse, Valkey, Node 24/Hono 4.x) são tratadas como **propostas**; a Valkey (ADR-P09) fica condicionada a teste em *staging* (D12).

**Estado das afirmações.** Só os requisitos de recursos de Chatwoot (≥ 4 GB e 4 núcleos), Langfuse v4 (4 núcleos, 16 GiB, 100 GiB) e Medusa (≥ 2 GB) vêm de documentação oficial (CONFIRMADO). A memória por serviço, os preços de VM, o volume por PME, as cotações de Luanda, a latência Luanda↔JNB e os limites do BullMQ são ESTIMATIVA ou NÃO VERIFICADO: os tickets KAM-084 (carga) e KAM-085 (DR) existem para os validar ou corrigir, e nenhum ticket trata um número do doc 09 como requisito sem esse critério de saída. **Fase:** 0 (KAM-075, 076, 077, 080: chão de infraestrutura e observabilidade mínima) e 1 (KAM-078, 079, 081–085). `prod` corre **só com dados sintéticos** até D1 e ao procedimento APD (KAM-105, KAM-069). Abreviaturas: «doc 09» designa `../docs/tecnica/09_Topologia_Operacao_Escala.md`, «doc 00» designa `../docs/tecnica/00_Arquitectura_Solucao.md`, «E1» a «E5» designam `../docs/tecnica/evidencia/E1_…` a `E5_…`.

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

### Verificação dos Critérios de Aceitação

Treze caixas — 7 critérios e 6 linhas de DoD —, **7 marcadas e 6 vazias**. As
seis vazias têm a razão escrita, e **quatro delas dependem da D1**, que é acto
do fundador. Os comandos e os números estão em
[`../docs/evidencia/KAM-075.md`](../docs/evidencia/KAM-075.md).

> **O que a D1 bloqueia, dito de uma vez.** O alojamento (Luanda ou JNB/CPT)
> está `em branco` na linha A1 de
> `../docs/tecnica/evidencia/validacao/GoLive_Gate.md`, e depende de ≥ 3
> cotações das quais **nenhuma foi pedida** (KAM-105). Sem conta e sem
> fornecedor não há `apply`, não há cronómetro e não há cotação — e é isso, e
> não falta de trabalho, que deixa os critérios **2**, **3** (metade) e **7**
> por cumprir.

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Matriz em `infra/ENVIRONMENTS.md` com as 7 linhas do doc 09 §6, verificada por um teste que a compara com a configuração real | **satisfeito** | `infra/ENVIRONMENTS.md` §2 tem as **sete** linhas que o critério nomeia (dados, compute, Meta, facilitador, LLM, segredos, acesso), cada uma com uma **chave** que aponta para um campo de `infra/envs/<ambiente>/env.yaml`. Quem compara é `tools/env_lint` no gate 2: `cd tools && python -m env_lint --root .. lint` → **0**, «3 ambientes, 12 linhas de matriz, 31 segredos do inventário, 37 ficheiros de infra/, 11 regras, 0 achados». Que morde: `env_lint canario` → **0**, «25 de 25 casos a morder, a exercitar 11 de 11 regras», com `matriz-divergente` e `matriz-linha-em-falta` entre eles. Testes: `TestMatriz` em `tools/env_lint/tests/test_lint.py` e `tools/env_lint/tests/test_matriz.py` (17 casos de leitura e recusa). **Uma divergência de contagem registada e não corrigida:** o doc 09 §6 tem **oito** linhas e o critério nomeia sete — seguiu-se a letra do critério, e a oitava (Factura AGT, ligada à D7) está em `ENVIRONMENTS.md` §3 fora do conjunto verificado, com a razão (§2.1) |
| 2 | Numa conta vazia, `infra apply staging` produz um *host* com Docker, utilizador não-root, WireGuard e disco NVMe em ≤ 30 min (mediana de 3 execuções); segundo `apply` não altera nada | **não satisfeito** | **Zero execuções, e portanto nenhum número.** Não há conta nem fornecedor (D1), e um `apply` pára na barreira — medido: `tofu plan` em `infra/envs/prod` → **1**, com quatro precondições falhadas e **zero recursos planeados** (`../docs/evidencia/KAM-075.md` §1.5). Os 30 min continuam ***proposta*** do `../docs/tecnica/09` §8.2, onde entram no orçamento de RTO. O que existe: o documento cloud-init que instala as quatro coisas nomeadas (`infra/modules/host-base/cloud-init.yaml.tftpl`), com a formatação do disco condicional a `blkid -L` para que um segundo arranque não apague a base de dados — **desenho, não medição** —, e o procedimento cronometrado em `infra/README.md` §5, que diz o que conta para os 30 min e o que não conta. **Nenhuma das quatro coisas foi observada num *host*** |
| 3 | `staging` cria-se e destrói-se com um comando; restaurar um *backup* de `prod` em `staging` falha por controlo (teste negativo) | **parcial** | **A metade negativa está feita e medida.** `dados.restauro_de` em `infra/envs/*/env.yaml` está vazia nos três, e qualquer ambiente que não seja `prod` com `prod` nessa lista faz o gate 2 falhar com `restauro-de-prod` — canário: um dos 25 casos, e teste `test_staging_a_aceitar_restauro_de_prod`. É o primeiro mecanismo que impede o que a linha **D10t** do `GoLive_Gate.md` dá hoje como «satisfeito por desenho e **não por medição**». **A metade positiva não:** «um comando» que cria e destrói depende da D1 pela razão acima. Os comandos estão escritos (`infra/README.md` §5) e **nunca correram**. A caixa fica vazia porque o critério tem duas metades e só uma se cumpre |
| 4 | `prod` arranca com `kamba_data_class=synthetic`; passar a `real` exige referência de decisão D1 e ≥ 1 `apd_ref`, senão o *pipeline* recusa | **satisfeito** | `infra/envs/prod/env.yaml` tem `dados.classe: synthetic`, `decisao_d1: null` e `apd_refs: []`. O *pipeline* que recusa é o **gate 2**: `tools/env_lint` dá `real-sem-d1` e `real-sem-apd-ref`, e as duas metades testam-se **separadas** de propósito (dois casos do canário, um por metade; `test_real_sem_d1_e_sem_apd_ref_da_os_dois_achados`). A metade positiva também tem teste — `test_real_com_as_duas_referencias_passa` —, que é o que prova que isto é uma barreira e não um bloqueio permanente. Verifica-se também a forma das duas referências e que a etiqueta de custo não minta sobre a classe. **A forma da referência de D1 é *proposta* deste ticket** (`D1/<AAAA-MM-DD>/<slug>`, em `../specs/02_Dicionario_de_Dados_Canonico.md` §3.41): nenhuma existia, e os dois critérios que a exigem escrevem-na sem formato. **E recusa o ambiente, não o destino** — o gate por destino é do KAM-069 e a `tenant_destinations` não existe (linha D1t do `GoLive_Gate.md`). **A força da barreira está escrita, e é menor do que parece:** verifica a **forma** das duas referências, não a existência da decisão nem do protocolo — um `decisao_d1` inventado passa, medido em revisão adversarial. Vale contra a distracção, que é o modo de falha real; o que impede a entrada de dados reais de verdade é o `GoLive_Gate.md`, que é um acto humano com assinatura (`infra/ENVIRONMENTS.md` §5) |
| 5 | Mapeamento ambiente → projecto de segredos definido; chaves Meta e do facilitador distintas por ambiente; *scan* de segredos limpo; um segredo de `prod` referenciado em `staging` faz o *pipeline* falhar | **satisfeito** | **O mapeamento:** `dev` → `local` (que é a ausência de projecto, doc 09 §6: «Local, não reutilizáveis»), `staging` → `staging`, `prod` → `prod`, em `infra/envs/*/env.yaml` e na tabela de `infra/README.md` §4. **Chaves distintas:** derivam-se (`<projecto>/<ID_EM_MAIÚSCULAS>`, com o `ID` vindo de `../ops/secrets-inventory.yaml`), e o lint **não confia na derivação** — calcula as três referências de `meta_app_secret` e de `proxypay_api_key` e exige que difiram duas a duas (`chave-partilhada-entre-ambientes`; teste `test_dois_ambientes_no_mesmo_projecto`). ***Scan* limpo:** `python -m scan_secrets --root .. tree` → **0**, «limpo — 1606 ficheiros seguidos pelo git». **O negativo:** `prod/META_APP_SECRET` escrito dentro de `infra/envs/staging/` dá `segredo-de-outro-ambiente` — **em duas formas**, o `.tf` e o `terraform.tfvars`, que o OpenTofu auto-carrega (dois casos do canário). **Os projectos não são criados aqui:** são do KAM-010, e este ticket só declara o mapeamento e falha quando é violado, como o bloco manda |
| 6 | Checklist de portabilidade preenchida: 0 recursos geridos proprietários sem equivalente documentado | **satisfeito** | `infra/PORTABILIDADE.md`: **oito** classes de recurso, cada uma com forma portátil e equivalente documentado; contagem de recursos geridos proprietários = **0**. A §1 desse documento escreve a distinção que torna o zero honesto: um zero de conjunto vazio (não há fornecedor) e um zero mantido por **regra verificada por máquina** — nenhum ficheiro de configuração nativa fora de `infra/modules/provider-*/` declara `resource`, `data` ou `provider` — e **nas duas formas que o OpenTofu carrega**, o `.tf` e o `.tf.json` —, achado `recurso-fora-da-costura` (dois casos do canário; nove testes entre `TestPortabilidade` e `TestFormasNativasDoOpenTofu`, incluindo o falso positivo de prosa). **E a §3 nomeia as duas linhas que não fecham**, as duas depois da revisão adversarial: a classe 5 (identidade federada não tem equivalente portátil, devolvida como **critério de aceitação da D1**) e a classe 3 (a forma portátil é `nftables` e **não está implementada** — é do KAM-077) |
| 7 | Etiquetas de custo por ambiente e custo mensal registado a partir de uma cotação real (não do doc 09) | **parcial** | **As etiquetas estão feitas:** `kamba_env` e `kamba_data_class` nos três ambientes, a atravessar a costura (`infra/modules/provider-pendente/variables.tf`), com o gate 2 a exigir que a etiqueta de classe não minta sobre `dados.classe` (`etiqueta-de-classe-divergente`, um caso do canário). **O custo não, e não é possível hoje:** o critério exige «cotação real (não do doc 09)» e `../docs/tecnica/evidencia/validacao/Alojamento_Cotacoes.md` registra **«Nenhuma pedida»**. `custo.mensal_usd` é `null` nos três, declarado NÃO VERIFICADO. Pedir cotações é o KAM-105 |

#### Definition of Done

| # | Linha | Estado | Evidência |
|---|---|---|---|
| 1 | Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não satisfeito** | Dos sete: **4 satisfeitos** (1, 4, 5, 6) e **3 parciais ou não satisfeitos** (2, 3, 7). Os três dependem da **D1**, e nenhum se resolve neste ramo |
| 2 | Sem segredos em código, estado de IaC ou logs; estado de IaC cifrado | **parcial** | **A primeira metade está medida:** `scan_secrets tree` → **0** sobre 1606 ficheiros; a chave privada do WireGuard **não** está no `wg0.conf` versionado — entra no arranque do cofre, pela referência (`infra/modules/host-base/cloud-init.yaml.tftpl`), e o que o repositório tem é um `wg0.conf.modelo` sem `PrivateKey`. **A segunda não se demonstra: não há estado.** Nenhum ambiente foi aplicado, pelo que não existe ficheiro de estado para cifrar. A configuração da cifra está escrita e **comentada** em `infra/envs/*/estado.tf`, com a razão: *onde* fica o estado é alojamento, logo ADR-008, logo D1. Estado: **NÃO VERIFICADO**. O `.gitignore` já exclui `infra/envs/*/.terraform/`, o estado e os planos |
| 3 | Dados: `dev`/`staging` sintéticos; `prod` sem dados reais (privacidade e ADR-008) | **satisfeito** | Os três ambientes têm `dados.classe: synthetic`, verificado pelo gate 2 contra a matriz (critério 1). E não é só o valor de hoje: o mecanismo do critério 4 recusa a passagem a `real` sem a decisão D1 e sem `apd_ref`, pelo que `prod` com dados reais deixou de ser uma edição de uma linha. **Uma tensão do documento-fonte, nomeada e não resolvida:** a linha «Meta» do doc 09 §6 prevê, para `staging`, «na semana 1–3, 1–3 números **+244 reais**» para o *spike* de coexistência (H3) — e um +244 real é dado pessoal, o que contraria a linha «Dados» da mesma tabela. A `ENVIRONMENTS.md` §5.1 reproduz a cláusula (a primeira versão deixava-a cair) e devolve a pergunta ao *spike* H3 e ao parecer: declarar a excepção aqui era decidir que `staging` pode ter dados pessoais, o que atravessa o ADR-008, a Lei 22/11 e a **D5** |
| 4 | Dependências de IaC fixadas por versão/hash; licenças permitidas | **satisfeito** | **Versão exacta e não gama:** `required_version = "1.10.6"` em `infra/envs/*/versoes.tf` — uma gama deixava a versão do CI divergir da de quem desenvolve. Medido: `tofu version` na imagem `ghcr.io/opentofu/opentofu:1.10.6` → `OpenTofu v1.10.6`. **Licença CONFIRMADA da fonte primária:** o `LICENSE` na raiz de `opentofu/opentofu` (ramo `main`, lido a 2026-11-02) diz «Mozilla Public License, version 2.0», e `MPL-2.0` está em `../ci/licenses.yaml` `permitidas`. **Não há *provider* fixado porque não há *provider*** — `required_providers` está vazio (ADR-L007 §5), e é essa ausência que faz `tofu init -backend=false` e `tofu validate` correrem **offline**. A metade do *hash* (`.terraform.lock.hcl`) aplica-se ao primeiro `provider-<nome>` real |
| 5 | Custo por ambiente visível (ADR-018) | **não satisfeito** | As **etiquetas** estão definidas e verificadas (critério 7), mas «visível» exige um número e não há nenhum: zero cotações pedidas. `custo.mensal_usd` é `null` nos três ambientes, com a razão escrita no próprio ficheiro e em `infra/ENVIRONMENTS.md` §6 |
| 6 | Documentação actualizada: `infra/README.md` com o procedimento de «host novo em 30 min» (insumo de RB-K08) | **satisfeito** | `infra/README.md` §5: os seis passos (do `init` ao `destroy`), a tabela do que conta para os 30 min e do que não conta (o Compose é KAM-076, o restauro é outro item do orçamento de RTO), e onde registar a mediana. Abre com o aviso de que **o número não foi medido** e fecha com o que falta ao procedimento — o módulo de fornecedor que não existe e os subcomandos do Doppler marcados NÃO VERIFICADO em `../ops/runbooks/secrets-export.md` §7 |

#### As perguntas que ficam com o fundador

| # | Pergunta | Porque não é de quem executa |
|---|---|---|
| 1 | **D1** — fornecedor e região de alojamento | Acto do fundador. Bloqueia os critérios 2, 3 (metade) e 7, e as linhas 1, 2 e 5 do DoD |
| 2 | Um fornecedor **sem identidade federada (OIDC)** é aceitável? | `infra/PORTABILIDADE.md` §3: a única classe de recurso sem equivalente portátil. Aceitá-lo exigiria emendar o ADR-L007 §4a, que proíbe chave estática |
| 3 | A forma de uma referência de decisão D1 | ***Proposta*** deste ticket porque nenhuma existia; quem decidir a D1 pode querer outra |
| 4 | O critério 1 diz «7 linhas» e o doc 09 §6 tem **8** | Seguiu-se a letra do critério e a oitava ficou registada fora do conjunto verificado. **Alterar um critério de aceitação não é acto de quem o executa** |

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

### Verificação dos Critérios de Aceitação

Treze caixas — 8 critérios e 5 linhas de DoD —, **3 marcadas (critérios 1, 4 e
8) e 10 vazias ou parciais**. Nenhuma fica sem razão escrita, e **cada uma das
dez nomeia o seu credor** na última coluna — porque uma caixa vazia sem credor
é trabalho que ninguém reclama. Quatro dos credores não são de quem executa: a
**D6** (critério 7), a **D12** (critério 6), a **D1** (metade do critério 5,
pelo *scan* externo) e a inversão **KAM-078 → KAM-076** do `release.lock`
(critério 2). Os comandos e os números
estão em [`../docs/evidencia/KAM-076.md`](../docs/evidencia/KAM-076.md).

> **O que o `release.lock` bloqueia, dito de uma vez.** Os «Detalhes Técnicos»
> deste bloco dizem «`release.lock` (lista de *digests*) é a única fonte do
> Compose». O `release.lock` é produzido pelo **KAM-078**, que **depende deste
> ticket**: hoje não há *digest* publicado de nenhuma imagem nossa, e escrever
> um era inventar um número. É isso, e não falta de trabalho, que deixa o
> critério 2 por cumprir para os **cinco serviços nossos** — as nove referências
> a imagens de terceiros vêm todas por `@sha256:`.

| # | Critério | Estado | Evidência | Credor |
|---|---|---|---|---|
| 1 | `docker compose config` lista exactamente o conjunto reduzido; um teste de CI falha se `langfuse`, `nominatim`, `typebot`, `n8n`, `storefront` ou `minio` surgirem no ficheiro de produção | **satisfeito** | `docker compose config --services` → **13** serviços; **14** com `--profile sto-proprio` (o `seaweedfs`, atrás de perfil porque a **D6** está aberta). «Exactamente» exige **dois sentidos**, e um teste que só leia o compose sabe o que *está* lá e não o que *devia* estar: o outro lado é `infra/compose/conjunto-reduzido.yaml`, com cada serviço `presente`, `pendente` (com ticket e razão) ou `proibido` (com ADR). `cd tools && python -m compose_prod --root .. lint` → **0 achados**, «14 serviços, 14 presentes e **5 PENDENTES**, 6 nomes proibidos, 4 destinos na allowlist, 13 regras» — os pendentes são impressos em voz alta porque um verde sobre um conjunto a que faltam cinco serviços não é o mesmo verde. **A *denylist* lê o texto todo** e não só os nomes dos serviços: um `minio` num volume ou um `n8n` numa variável de ambiente conta (dois casos de canário fazem exactamente isso); comentários saltam-se, pela razão do `lint_arch/medusa.py` — um *lint* que falhasse por se documentar a regra proibia documentá-la. **Nos dois sentidos:** `compose_prod canario` → **45 de 45** casos a morder, a exercitar **13 de 13** regras, e três deles são a *denylist* (`minio` num volume, um serviço `langfuse`, um `N8N_WEBHOOK_URL`) | — fecha neste ramo |
| 2 | 100% das imagens por `@sha256:` (nenhuma por tag); o perfil `staging-obs` só existe em *staging* e não arranca com `kamba_data_class=real` | **parcial** | **A segunda metade está satisfeita e medida.** O `langfuse` só existe em `docker-compose.staging.yml`, atrás do perfil `staging-obs`, e a regra `denylist` falha se o nome aparecer no ficheiro de produção; `staging-obs-com-dados-reais` falha se `kamba_data_class` valer `real` em *staging*, e `langfuse-sem-perfil` falha se o serviço estiver solto. As três têm caso de canário. As imagens de *staging* são **as mesmas** de produção, verificado por `staging-com-outras-imagens` (compara *digest* a *digest*). **A primeira metade não:** as **nove referências** a imagens de terceiros vêm por `@sha256:` (nove `image:`, oito imagens distintas — o Chatwoot conta duas vezes), com o *digest* lido da fonte e registado em `ci/supply-chain/imagens.yaml`; os **cinco serviços nossos** vêm por `build:`, pela inversão do `release.lock` dita acima. O que está verificado para esses cinco: a imagem de base de cada `Dockerfile` vem por *digest* e consta do inventário, e nenhum instala em arranque (`supply_chain imagens` e `runtime`, conformes). A regra `imagem-nao-resolvida` **já está escrita e com canário**, pelo que uma variável sem omissão com *digest* falha o *gate* no dia em que alguém tentar o atalho. `../docs/evidencia/KAM-076.md` §5 | **KAM-078** (produz o `release.lock`, e depende deste ticket) |
| 3 | Redes `edge`, `app`, `data`, `ops`: de `data` qualquer ligação externa falha; de `app` só têm êxito `graph.facebook.com`, o FQDN do facilitador e os FQDN de LLM/STT autorizados, e as restantes são bloqueadas **e registadas** (script com 10 destinos) | **parcial** | **O mecanismo está inteiro e medido; faltam dois destinos que não têm dono.** `cd tools && python -m compose_prod --root .. egress-dez` → **«10 destinos, 4 permitidos e 6 recusados, todos com o veredicto esperado e cada recusa registada»**, contra o `proxy-saida` do **próprio** compose de produção e as quatro redes de verdade. **De `data`:** dez destinos, dez vezes `gaierror` — não é *timeout*, **o nome não resolve**; numa rede `internal: true` para o DNS também, e isso mediu-se (`../docs/evidencia/KAM-076.md` §2). **De `app`:** os quatro da allowlist devolveram `200 Connection established` e os seis restantes **403**. **E o guião mudou por causa da revisão:** exigia «não-403» nos permitidos, e um **503** não é 403 — pelo que um destino que o proxy **não alcança** contava como permitido (a revisão viu exactamente isso no `graph.facebook.com`, por cache de DNS fria). Hoje exige **200**, distingue «inalcançável» de «recusado», e declara-se **INCONCLUSIVO** se nenhum permitido for alcançado; e a causa fechou-se com `preresolve_hostnames` na configuração do Envoy. **A `edge` passou a ser sondada também:** tem saída livre e não registada — **10 de 10 destinos abertos**, por desenho, porque é dela que o proxy sai — e deixou de ficar a parecer fechada por não ser medida; quem garante que não se espalha é a regra `servico-em-edge`. **E registadas** — a metade que se esquece: 10 linhas de `access_log` em JSON, com autoridade, método e veredicto, e nunca corpo. **Os dois que faltam, e porquê:** o **FQDN do facilitador** é CONFIRMADO (`E2` §1.2) mas **nenhum serviço do repositório o declara** — não há `services/pay/`, o adaptador é o **KAM-056** —, e um destino na allowlist sem dono é o contrário de negar por omissão, além de ser transferência sem `apd_ref` (KAM-069); o **FQDN de STT** não existe porque **nenhum provedor de STT está escolhido**. O guião testa os dois **como bloqueados**, com a razão no relatório, em vez de os dar por cumpridos | **KAM-056** (FQDN do facilitador, com dono) e a escolha de provedor de **STT** |
| 4 | Todos os contentores com FS só de leitura, utilizador não-root, `mem_limit` e `cpus`; a soma dos `mem_limit` ≤ 80% da RAM (≤ 25,6 GB em 32 GB) | **satisfeito** | **FS só de leitura:** os 14 serviços, verificado pelo `supply_chain runtime` que já o exige em todos os compose do repositório — «42 serviço(s) de compose só de leitura», conforme. Não se duplicou a regra aqui de propósito (duas mensagens para o mesmo defeito divergem com o tempo). **Não-root:** regras `utilizador-por-omissao` e `utilizador-root`, com caso de canário cada. **Limites:** `sem-limite-de-memoria` e `sem-limite-de-cpu`, idem. **E as capacidades:** toda a pilha corre com `cap_drop: ALL`, e a regra `capacidade-acrescentada` falha se um serviço acrescentar uma capacidade que não esteja nomeada no *lint* com a razão — nasceu nesta execução, porque há **uma** excepção e ela foi medida: o `/usr/bin/caddy` traz `cap_net_bind_service=ep` como capacidade de **ficheiro** e com `cap_drop: ALL` o kernel recusa **executar** o binário (`exec: operation not permitted`, com e sem `no-new-privileges`). Concede-se `NET_BIND_SERVICE` — a única da pilha — **e** o Caddy escuta em 8443, acima de 1024, para que ela nunca seja exercida; a porta externa continua 443. **A soma, e a correcção que a revisão adversarial forçou:** o `mem_limit` do compose é **por contentor** e o `deploy.replicas` é honrado fora de swarm (medido: `docker compose config` resolve o `gwy` com `replicas: 2` e um `mem_limit` próprio). A primeira versão punha o total do bloco em **cada** réplica e somava-o **uma** vez: o GWY reservava 2×512 MiB onde o bloco propõe «2×0,25 GB», e o conjunto passava o tecto em **922 MiB** com o *lint* a zero achados. Corrigido: o manifesto declara `replicas` e `memoria_mib` é o **total do serviço**; o `gwy` passa a `256m` e o `agr` a `1280m`. **A reserva real é 20 736 MiB (20,25 GiB) para os 14 presentes**, lida do compose resolvido com `mem_limit × replicas`, e **24 064 MiB = 23,50 GiB** com os cinco `pendente` — que se contam, porque um conjunto que só cabe por lhe faltar metade dos serviços não cabe. Tecto: **26 214 MiB** (80% de 32 GiB). A soma reconcilia **exactamente** com os «≈ 23,5 GB» do bloco, repartida pelos serviços que o compose tem de facto (Chatwoot em dois contentores, o COM a sair do orçamento do Medusa, o `worker-canal` da linha «SO e proxies»), e há um teste que prende os dois números (`test_a_soma_dos_limites_reconcilia_com_os_23_5_gb_do_bloco`). **`memoria-divergente`** falha se `mem_limit × replicas` discordar do total do manifesto, e **`replicas-divergentes`** se as réplicas discordarem — para que a soma não meça outra pilha. **E o tecto deixou de ser editável numa linha:** a revisão mediu que subir `fraccao_maxima_pct` de 80 para 95 punha o *lint* verde, porque os dois lados da comparação vinham do mesmo ficheiro que a regra lê; hoje os números do critério estão **em código** e o manifesto tem de concordar com eles (`tecto-alterado`). **Os limites continuam ESTIMATIVA**, como o bloco os marca; medi-los sob carga é o **KAM-084** | — fecha neste ramo |
| 5 | GWY e *workers* AGR com 2 réplicas e `/healthz`; no exterior só 443 e a porta UDP do WireGuard; Medusa admin e Grafana só por VPN | **parcial** | **As réplicas e o `/healthz`:** `deploy.replicas: 2` no `gwy` e no `agr`, com a sonda a chamar `/healthz`; regras `sem-duas-replicas` e `healthcheck-sem-healthz`, com caso de canário cada, e `sem-healthcheck` para todos os serviços. **E as sondas foram verificadas contra a imagem, uma a uma** — uma sonda que não corre deixa o contentor `unhealthy` para sempre e, com `depends_on: service_healthy`, bloqueia a pilha: a imagem do Envoy **não tem `curl` nem `wget`** e duas das minhas sondas estavam erradas (`../docs/evidencia/KAM-076.md` §8.4). **As portas, por leitura:** só o `proxy-tls` tem `ports:`, e só `443:8443` — porta **externa** 443, que é a que o critério nomeia; a interna é 8443 pela capacidade de ficheiro do binário do Caddy, explicada abaixo; a regra `porta-publicada` tem **dois** casos de canário (outro serviço a publicar, e o proxy a publicar uma porta que não é 443). **O que falta:** o ***scan* externo não foi corrido** — é o KAM-077 por fronteira deste bloco, e exige um *host* a sério, que depende da **D1**. **E o «só por VPN» é hoje uma sentinela:** nem o `medusa` nem o `grafana` estão no compose (o primeiro não tem imagem publicada, KAM-042; o Grafana é **AGPL-3.0**, que o `../ci/licenses.yaml` nega, KAM-080). A regra `admin-sem-vpn` **vê zero serviços** e dispara no dia em que um deles nascer com `ports:` — e o canário prova que dispara, fazendo nascer um Grafana com porta publicada. É a forma do `_rotas_internas_do_com` do `lint_arch/medusa.py`, e está nomeada como sentinela em vez de dada por cumprida | **KAM-077** (*scan* externo, que depende da **D1**/KAM-105); o «só por VPN» é sentinela até o KAM-042 e o KAM-080 trazerem o Medusa e o Grafana |
| 6 | Teste de compatibilidade Valkey em *staging* (BullMQ do *outbox*, Sidekiq do Chatwoot, eventos/cache do Medusa) passa; se falhar, regressa-se a Redis e abre-se D12. Resultado registado em ADR-P09 | **parcial** | Registado em [`../docs/adr/ADR-L009-ensaio-da-valkey.md`](../docs/adr/ADR-L009-ensaio-da-valkey.md). **O ensaio está incompleto, e por isso nada muda:** a **D12 continua aberta** e a ADR-P09 continua **proposta**. Dos três consumidores: **BullMQ CONFIRMADO** — a suite `tests_eventos` do *gate* 8 corre o publicador contra uma **Valkey 9.1.2 real** fixada por *digest*, e não contra uma fila em memória (20 testes, 19 verdes); **Sidekiq apenas INDÍCIO** — o `docker-compose.chatwoot.yml` já aponta o Chatwoot e o Sidekiq para uma Valkey e o spike do KAM-019 correu essa pilha, o que mostra que o **Rails** fala com ela, e **ninguém mediu o Sidekiq a processar um trabalho**; **Medusa NÃO APLICÁVEL** — o Medusa do Piloto usa módulos de event bus e cache **em memória** (`spikes/medusa-d3/contentor.py`), e o bus canónico é o EVT (ADR-009), pelo que não há nada a ensaiar. **Não se executou a segunda metade do critério** («se falhar, regressa-se a Redis»): o ensaio não *falhou* — ficou incompleto, e regressar trocaria BSD-3 por RSAL/SSPL sem medição que o justificasse. O que o ticket entrega é a **forma** da decisão: serviço `queue` (nem `redis` nem `valkey`), imagem e cliente por variável — fechar a D12 é mudar duas variáveis, não editar código. **E um achado:** o 20.º teste daquela suite está **vermelho**. Se é pré-existente fica **NÃO VERIFICADO**: a tentativa de controlo numa árvore pristina de `publico/main` falhou **sete ou mais** testes por lhe faltar o ambiente, logo não distingue nada — e isso está escrito em `../docs/evidencia/KAM-076.md` §4.2 em vez de a conclusão ficar de pé. O que **está** confirmado é que nenhum dos 29 ficheiros deste diff está em `db/` ou `services/com/`, pelo que o diff não pode ter quebrado a suite (`db/` é fronteira com o KAM-044). **E um achado sobre a letra do critério, que é o que torna esta caixa devolvível e não falhada:** ele tem ramo para «passa» e ramo para «falha» («se falhar, regressa-se a Redis e abre-se D12») e **nenhum para «incompleto»**, que foi exactamente o que aconteceu. Executar o ramo da falha trocaria BSD-3 por RSAL/SSPL sem medição que o justificasse; executar o da passagem promoveria dois indícios a facto. O que o ticket entrega em vez disso é a **forma** da decisão, e é ela que a torna uma *flag* e não uma reescrita: o serviço chama-se `queue` e não `redis` nem `valkey`, a imagem é `${KAMBA_QUEUE_IMAGE}` e o cliente `${KAMBA_QUEUE_CLI}` — fechar a D12 em qualquer dos sentidos é mudar duas variáveis de ambiente, e nenhum módulo do repositório sabe qual das duas corre. **E a caixa fecha com a decisão tomada, não com a pergunta em aberto:** a sessão que orquestra relatou que **o fundador deferiu — fica a *flag*, a omissão em Valkey mantém-se e a D12 não fecha agora** (decisão relatada por essa sessão, não lida por mim no registo da Carta §4.2, que não se toca aqui). A razão da deferição fica escrita porque é ela que justifica uma decisão de licença não ter bloqueado um PR: o `${KAMBA_QUEUE_IMAGE}`, o `${KAMBA_QUEUE_CLI}` e o nome neutro `queue` tornam a troca para Redis **um valor de ambiente e não uma reescrita**, e não há produção para afectar enquanto a **D1** não decidir o alojamento. **Não é uma dispensa:** a caixa fica devolvida, com o decisor nomeado e o custo de a reverter medido em **uma variável**. A D12 continua aberta nos dois ficheiros de licença (`../ci/licenses.yaml` e `../ci/supply-chain/licencas.yaml`), onde o Redis e a Valkey seguem os dois `pendentes_de_decisao` — verificado, e de propósito não alterado | **o fundador** (D12, **deferida**). O que falta medir está em ADR-L009 §5, e o «em *staging*» depende da **D1** |
| 7 | Se D6 = SeaweedFS: ensaio de *multipart*, URL assinada com TTL ≤ 5 min e *object lock*; falha → S3 gerido | **parcial** | **Fecha por citação e não por ensaio novo — e não fecha por inteiro, porque o relatório citado traz uma marca que não se promove aqui.** O **KAM-011** mediu as três capacidades contra SeaweedFS 4.48 e registou-as em [`../docs/evidencia/KAM-011-seaweedfs.md`](../docs/evidencia/KAM-011-seaweedfs.md): ***multipart*** §3.1, «1 abertura, 2 partes, 1 fecho; sha256 idêntico» (**CONFIRMADO**); **URL assinada** §3.2, TTL de 60 s — dentro do ≤ 5 min que o critério pede — com **200 antes e 403 depois de 65 s** esperados a sério, mais 403 com a chave trocada e 403 com a chave errada (**CONFIRMADO**); ***object lock*** §3.3, *bucket* com `object-lock-enabled` 200, `PUT` COMPLIANCE 200 com `x-amz-version-id`, `GET ?retention` 200 em COMPLIANCE, **`DELETE` da versão retida 403** e `GET` depois 200. **Este terceiro é INDÍCIO e não CONFIRMADO**, e o próprio §3.3 escreve o que a sonda não prova: que a retenção sobreviva a um reinício (os dados estavam em `tmpfs`), que não se contorne **fora da API S3** (o *filer* e os volumes não foram atacados), o modo `GOVERNANCE`, o *legal hold*, a expiração, e o comportamento com mais de um nó. WORM a sério é Clusters (`../docs/tecnica/08` §6). **E a premissa continua aberta:** «Se D6 = SeaweedFS» — a **D6** não está decidida, e o *Handoff* deste bloco manda «não decidas D1/D6, usa as *flags*». A *flag* é a do Compose: o `seaweedfs` está atrás do perfil **`sto-proprio`**, pelo que uma pilha levantada sem ele não o traz. Não se levantou nada de novo, porque repetir o ensaio do KAM-011 não decidiria a D6. **Uma afirmação minha corrigida pela revisão adversarial:** eu tinha escrito «uma pilha com `KAMBA_STO_MODO=s3-gerido` não o levanta», e era verdadeiro por vacuidade — `grep -rn KAMBA_STO_MODO` devolvia só comentários, **nada lia a variável** | **o fundador** (D6). A profundidade WORM é Clusters (`../docs/tecnica/08` §6) |
| 8 | Flags de licença verificadas: `rbac`/`auth-oidc` do Medusa, `enterprise/` do Chatwoot e `ee/` do Langfuse inactivos | **satisfeito** | **Medusa:** já tinha *lint* próprio do KAM-042 — `tools/lint_arch/medusa.py` cobre **cinco** *flags* (as três do critério mais `MEDUSA_FF_RBAC` e `MEDUSA_FF_RBAC_FILTER_FIELDS`), com treze canários. Não se duplicou. **Chatwoot:** `DISABLE_ENTERPRISE: "true"` nos dois contentores (web e Sidekiq), verificado pela regra `flag-de-licenca`, com caso de canário. **Langfuse:** `LANGFUSE_EE_LICENSE_KEY` vazia, de propósito e não por omissão, e o serviço só existe em *staging*. **E a licença foi relida na versão que corre, não herdada:** o `LICENSE` da v4.74.0 lista **quatro** pastas `ee/` e o `E4` §2.8 (v4.55.0) lista **três** — junta-se `packages/shared/src/server/ee/`. A diferença está registada em `../ci/supply-chain/licencas.yaml`. **Um extra que o bloco pede noutro sítio e aqui se verifica também:** o Chatwoot **não** tem `WHATSAPP_APP_ID`, `WHATSAPP_CONFIGURATION_ID` nem `WHATSAPP_APP_SECRET` (ADR-001: o GWY é o único endpoint), com regra `chatwoot-fala-com-a-meta` e canário | — fecha neste ramo |

#### Definition of Done

| # | Linha | Estado | Evidência | Credor |
|---|---|---|---|---|
| 1 | Todos os Critérios de Aceitação satisfeitos e demonstráveis | **não satisfeito** | Dos oito: **3 satisfeitos** (1, 4, 8), **4 parciais** (2, 3, 5, 6) e **1 não satisfeito** (7). Nenhum dos cinco se resolve neste ramo: dependem da **D6**, da **D12**, da **D1** e da inversão **KAM-078 → KAM-076** | os cinco credores dos critérios 2, 3, 5, 6 e 7 |
| 2 | Dependências por *digest*; licenças e lista de bloqueio respeitadas (sem MinIO, sem `langgraph-api`, LiteLLM ≥ 1.83.0) | **parcial** | **A metade das licenças e da lista de bloqueio está satisfeita e medida:** `supply_chain licencas` → conforme, «27 componentes (18 permitido, 2 pendente_de_decisao, 6 bloqueado, 1 nao_adoptado)»; sem MinIO (também proibido pela *denylist* do critério 1), sem `langgraph-api`, e o LiteLLM é **v1.104.2**, acima do piso 1.83.0 e fora de {1.82.7, 1.82.8}. As quatro licenças novas foram **lidas** e não herdadas — e uma armadilha ficou registada: a primeira leitura da licença do Envoy «dentro da imagem» apanhou o `copyright` do pacote Debian `adduser`, que é **GPL**, e dá-la como licença do Envoy marcava um componente Apache-2.0 como GPL (`../docs/evidencia/KAM-076.md` §7). **A metade dos *digests* não**, pela razão do critério 2 | **KAM-078** (a metade dos *digests* dos nossos serviços) |
| 3 | Egress *default-deny* provado; sem segredos em imagens, Compose ou logs | **parcial** | **O egress está provado e medido** (critério 3), com a ressalva dos dois destinos sem dono. **Sem segredos:** `scan_secrets tree` limpo, e nenhum valor de segredo está nos dois ficheiros — todos entram por `${...:?}`, que faz o compose **recusar-se a arrancar** sem eles em vez de arrancar com uma chave vazia. O proxy de saída registra autoridade, método e veredicto e **nunca corpo**; o Caddy registra em JSON sem corpo nem cabeçalhos. **O que não se demonstrou:** «sem segredos em **imagens**» exige SBOM e varrimento de camadas por imagem, que é o **KAM-078** — e está NÃO VERIFICADO, como o próprio `ci/supply-chain/imagens.yaml` já diz nas razões de `cosign: por_apurar` | **KAM-078** (SBOM por imagem e varrimento de camadas) |
| 4 | Consumo em repouso medido e registado (comparação com 18,6 GB fica em KAM-084) | **parcial** | **Medido: 637 MiB (0,62 GiB) em repouso**, com **sete** contentores `healthy` — `litellm` 469,6, `seaweedfs` 64,3, `postgres` 45,4, `proxy-saida` 20,6, `prometheus` 18,9, `proxy-tls` 11,1, `queue` 7,2 —, contra 11 008 MiB de limites declarados para esses sete (**5,8%**). Tabela e comandos em `../docs/evidencia/KAM-076.md` §9. **Não é o conjunto todo:** faltam os cinco nossos (exigem `node`/`pnpm`, que não existem no `PATH` desta máquina, ADR-L001), o Chatwoot e o Sidekiq (migrações do Rails, e são o maior consumidor declarado) e os cinco `pendente`. **E levantar a pilha apanhou dois defeitos que o `docker compose config` dava por válidos** (§9.1): o Caddy não executava com `cap_drop: ALL` — capacidade de **ficheiro** no binário, não a porta — e o LiteLLM recusava arrancar porque eu tinha copiado os nomes das variáveis do compose do KAM-030 e o `llm/litellm.config.yaml` gerado lê outros quatro. Os dois corrigidos e remedidos. A comparação com os ≈ 18,6 GB **é do KAM-084** por escrito no bloco | **KAM-084** (a comparação com os 18,6 GB, por escrito no bloco) e a construção dos nossos cinco serviços |
| 5 | Dois revisores (infraestrutura que toca segredos e isolamento); documentação e ADR-P09 actualizados | **parcial** | **Documentação:** `infra/README.md`, `tools/compose_prod/README.md`, esta secção e `../docs/evidencia/KAM-076.md`. **ADR-P09:** o resultado está em `../docs/adr/ADR-L009-ensaio-da-valkey.md`, com o estado honesto (ensaio incompleto, D12 aberta) — a ADR-P09 em si é uma **proposta** num documento de referência, e ratificá-la é acto do fundador. **Dois revisores:** uma revisão adversarial correu sobre este ramo e os achados estão no corpo do PR; a **segunda revisão humana** é do fundador e não de quem executa | **o fundador** (a segunda revisão humana e a ratificação da ADR-P09) |

#### As perguntas que ficam com o fundador

| # | Pergunta | Porque não é de quem executa |
|---|---|---|
| 1 | **D6** — SeaweedFS ou S3 gerido | Decisão aberta, e é só a **decisão** que falta: o **conteúdo** do ensaio que o critério 7 pede já está medido pelo KAM-011 — *multipart* e URL assinada CONFIRMADO, *object lock* **INDÍCIO** —, pelo que aquele critério passou a **parcial** por citação em vez de vazio. O compose já tem a *flag* (`sto-proprio`) para qualquer dos sentidos |
| 2 | **D12** — licença do Redis/Valkey | Decisão aberta, e o ensaio que a informava ficou **incompleto** (critério 6). O que falta medir está em ADR-L009 §5: o Sidekiq a processar um trabalho, e em *staging* — que depende da **D1** |
| 3 | **Um contexto exigido novo no *ruleset* para o compose de produção?** | Acrescentar um contexto exigido a `main` é alteração de regra de bloqueio. A medição e a recomendação estão em `../docs/evidencia/KAM-076.md` §10: **não criar** — as duas verificações já são *fail-closed* nos gates 2 e 6, e o ganho de um *job* próprio seria um nome no painel. **Não se mexeu em `.github/rulesets/` nem no `ci.yaml`** |
| 4 | ~~**Um teste vermelho no *gate* 8**~~ — **resolvido, e não há pergunta** | `test_mil_eventos_com_a_fila_parada_recuperam_sem_perder_nenhum` falhava **nesta máquina**. O **`gate 8` passou em CI** sobre este ramo, e é ele que corre aquela suite: logo não é pré-existente em `main`, não foi causado por este diff, e o que resta é a sensibilidade do teste a contenção — que fica nomeada em `../docs/evidencia/KAM-076.md` §4.2.1. **Não entra nenhum teste vermelho com este PR.** Fica como lição e não como achado: o controlo que eu montei era inválido, eu disse que era, e por isso a conclusão falsa não chegou a esta tabela |
| 5 | **A allowlist do proxy não é por serviço** — e é o defeito real mais importante que fica | A revisão adversarial mediu-o: o Envoy decide pelo `:authority` e **nunca pela origem**, pelo que qualquer contentor em `app` alcança os quatro FQDN. Os contratos por serviço (`infra/egress/*.yaml`, `services/*/egress.yaml`) dizem cada um «a aplicação na rede é do KAM-076», e este ticket aplicou a **união** deles, não a política por serviço. Fechá-lo exige RBAC do Envoy por IP de origem ou um *listener* por serviço — muda o desenho do proxy e pede revisão própria, pelo que vai como **recomendação com a medição** e não como implementação |
| 6 | **O facilitador e o STT sem dono** | O critério 3 nomeia-os como permitidos e **nenhum serviço os declara**. Abri-los na allowlist sem dono contraria a regra de negar por omissão do próprio repositório; o facilitador entra com o **KAM-056** e o STT quando houver provedor escolhido |

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
- [x] Logs sem conteúdo nem identificadores directos; sem segredos em logs ou painéis (ADR-010).
- [ ] Métricas e custo nascem com a funcionalidade (ADR-018); painéis versionados.
- [x] 0 alertas sem runbook (existe *stub* para cada `runbook_url`).
- [x] Documentação actualizada (catálogo de métricas, canal de alertas e escalamento inicial).

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

### Verificação dos Critérios de Aceitação

Doze caixas — 7 critérios e 5 linhas de DoD —, **3 marcadas (DoD 2, 4 e 5) e 9
vazias ou parciais**. Nenhuma fica sem razão escrita, e **cada uma das nove
nomeia o seu credor** — porque uma caixa vazia sem credor é trabalho que ninguém
reclama. Os comandos e os números estão em
[`../docs/evidencia/KAM-080.md`](../docs/evidencia/KAM-080.md); a leitura
operacional está em [`../docs/observabilidade.md`](../docs/observabilidade.md).

**Quatro dos nove credores não são de quem executa**, e vale dizê-lo à cabeça: a
**licença AGPL-3.0** do Grafana e do Loki (critérios 1 e 6), o **portão** do
*lint* de cardinalidade (critério 3), o **canal de alertas** e o inventário de
subprocessadores (critério 4), e a **ausência de *staging* e de produção**
(critérios 4 e 5).

> **A medição que explica quase tudo o que fica vazio.** Das **115** métricas
> declaradas em código, **23** estavam servidas por algum processo e só **7**
> eram alcançáveis numa pilha de `docker compose` (`gwy` 5, `com` 2). Este
> ticket expôs o AGR (**44**) e passa a **51** alcançáveis. As restantes não
> estão por esquecimento: os **dez** módulos `outbound`, `metering`, `hnd`,
> `qualidade`, `coexistencia`, `avisos`, `consentimento`, `modos`, `onboarding`
> e `provisioning` do `packages/core-ts` **não são importados por nenhum
> serviço** (medido: `grep -rn "core-ts/outbound" services` dá zero). São
> biblioteca à espera de quem as ligue, e expô-las publicava **zeros
> permanentes** — que é o defeito que o KAM-076 recusou ao não acrescentar um
> `scrape_config` para um `/metrics` inexistente.
>
> **E o número de declaradas sobe sem que os outros dois subam**, o que é a
> própria tese deste ticket com um exemplo que não é meu: entre a primeira
> medição e a integração final, o **KAM-091** fundiu com um
> `provisioning/metricas.ts` de **6** métricas que nenhum serviço importa — as
> declaradas passaram de 109 a 115 e as servidas ficaram nas mesmas. O problema
> não é faltarem métricas; é faltarem serviços que as importem.
>
> **E uma segunda vez, já depois deste ticket fundir:** o **KAM-116** trouxe um
> `sms/metricas.ts` de **sete** nomes que nenhum serviço importa — quem liga a
> porta `SmsProvider` é o KAM-086 —, e as declaradas passaram de 115 a **122**
> com as servidas e as alcançáveis nas mesmas. Os números acima são os da
> medição **deste** ticket e ficam como estavam; o de hoje lê-se do
> `tools/obs_lint/contar_metricas.py`, e a prosa que o cita está em
> `../docs/observabilidade.md` §2.1.
>
> É por isso que **8 das 12 linhas do §9.2 não se escreveram**. Um alerta sobre
> uma série que ninguém produz nunca dispara, e um alerta que nunca dispara
> **parece cobertura** — é pior do que a sua ausência, porque ninguém volta a
> olhar. As oito estão nomeadas, uma a uma, com o que falta e o credor, em
> `regras_por_escrever` de [`../ops/metricas/catalogo.yaml`](../ops/metricas/catalogo.yaml).
>
> **A aritmética, corrigida pela revisão adversarial.** O ficheiro tem **8
> regras**, que cobrem **4 das 12 linhas** do §9.2 — a fila dá duas regras, uma
> por serviço — mais **3** que não são do §9.2 (o `alvo_em_baixo`, e os dois que
> o KAM-037 deixou escritos). A versão anterior desta secção dizia «6 das 12» em
> cinco ficheiros, e **sobredeclarava a cobertura**: contava como linhas do §9.2
> os dois do KAM-037. 4 + 8 = 12.

| # | Critério | Estado | Evidência / credor |
|---|---|---|---|
| 1 | Logs JSON em todos os serviços → Alloy/Vector → Loki (30 d); canário de telefone e texto não deixa nada em Loki | **parcial** | **Os logs existem e são verificados**: os cinco serviços instalam o *logger* tipado (12 campos de *allowlist*, `docs/tecnica/08` §7.3), o gate 2 recusa quem escreva fora dele (`make log-lint`, com canário) e o gate 6 corre o **X-11** sobre 1 030 *fixtures* pelos dois *loggers*, exigindo saída igual byte a byte e zero achados — é o canário de PII, e já existia (KAM-068). **O que não existe é o destino:** não há Loki, nem Alloy, nem Vector, e nada envia nada. **Credor: decisão de licença** — o Loki é **AGPL-3.0**, que o `../ci/licenses.yaml` nega por prefixo, e a evidência do KAM-076 já escreveu que «entrar exige fechar a licença com um ADR». **A caixa fica vazia e não se marca com o X-11:** medir o emissor não é medir o Loki, e uma caixa marcada com prova que não é a pedida é pior do que uma caixa vazia |
| 2 | Métricas Prometheus presentes (12 séries nomeadas) | **parcial** | A tabela `series_do_criterio_2` do catálogo dá o estado das **doze**, uma a uma: **5 expostas** (mensagens recebidas, latência de ingress, fila, *handoff*, e o AGR por inteiro), **4 declaradas e não expostas** (mensagens enviadas, latência de resposta, callbacks, custo LLM), **3 inexistentes** (erros Meta `130429`/`131049`, idade do WAL, memória/CPU). Credores: o ticket que ligar o estágio de saída, **KAM-079** (WAL) e um *exporter* de contentores (nenhum compose tem um). **E o «por tenant» não se cumpre por desenho e não por falta:** as emendas **1.21** e **1.25** do dicionário já recusaram `tenant_id` em etiqueta, duas vezes, com a saída escrita — «o por-*tenant* sai de consulta». O dicionário é fonte de nível 4 e o bloco de nível 8 |
| 3 | *Lint* de cardinalidade: `tenant_id` permitido; `contact_id`, telefone e BSUID proibidos (**o CI falha**) | **parcial** | **O *lint* existe e morde, e está medido nas duas direcções.** `tools/obs_lint`, **10** regras, 3 superfícies (catálogo, regras de alerta e painéis); sobre a árvore real **0 achados**; canário com **16 negativas e 2 positivas**, cada negativa a morder exactamente a sua regra, as obrigatórias vindas do código e não das *fixtures*. **94 testes**, **91%** de cobertura. O par que prova o critério à letra: `positivas/tenant_id_passa_pelo_nome` (o **nome** passa) e `negativas/valor_fora_da_gramatica__uuid_no_dominio` (um **UUID** não passa, mesmo com o nome permitido). **A revisão adversarial mediu cinco furos neste *lint*, e os cinco estão fechados com negativa própria** — nenhum era visível pelo canário, porque não eram regras a falhar mas verificações que não existiam: (a) `tenant_id` com **só** `cardinalidade_maxima` passava sem que nenhum valor fosse olhado, e 64 UUIDs cabem num tecto de 64; (b) um `label_replace`/`label_join` **criava** um `contact_id` limpo, nas duas superfícies — e criar é pior do que filtrar; (c) um `{__name__="…"}` contornava o catálogo por inteiro; (d) o `templating` e as `annotations` de um painel, que vivem **fora** de `panels`, não eram lidos, nem as subpastas que o Grafana lê recursivamente; (e) o `exposta_por: []` era uma promessa escrita no catálogo que o *lint* não cumpria. Mais dois de menor gravidade: um `cardinalidade_maxima: true` passava (`isinstance(True, int)`) e um `sum by (contact_id)` mordia pela regra errada. **O que não se fez foi ligá-lo a um portão, e é a metade que falta da caixa.** Credor: **o fundador.** Ligar uma verificação que trava fusões é alteração de regra de bloqueio, pelos dois caminhos: um *job* novo acrescenta contexto exigido ao *ruleset* da `main` (e ao `esperados=11`), e uma linha no `ci-2` muda o **critério** de um portão que já bloqueia. Para ligar é **uma linha** no `Makefile`, documentada em `../docs/observabilidade.md` §7 |
| 4 | As 12 regras existem com severidade P1/P2/P3 e `runbook_url` válido; **cada uma dispara numa injecção de falha em *staging*** e chega ao canal certo; CI falha para alerta sem runbook | **parcial** | **8 regras, que cobrem 4 das 12 linhas** do §9.2, em `../infra/compose/prometheus/regras/kamba.yml` → `promtool check rules`: `SUCCESS: 8 rules found`. Todas com `severity` em P1/P2/P3 e `runbook_url` que **resolve para ficheiro no disco**. **Três das que vêm do §9.2 medem um predicado mais fraco**, dito na anotação `limite` de cada uma: a fila mede profundidade e não a idade do mais antigo; a latência mede o último valor com guarda de trânsito e não o p95 (**o AGR não tem histogramas**, ADR-018); o orçamento do LLM dispara no esgotamento e não aos 80%. **As outras 8 linhas não se escreveram** (ver a nota acima). **A revisão adversarial encontrou quatro regras que não funcionavam, e as quatro estão corrigidas com caso de teste:** três alertas do AGR **nunca disparavam na primeira ocorrência** — o `exposicao()` do AGR não emite séries a zero, pelo que o contador nasce já a 1 e o `increase()` não vê subida, e exigiam **duas** ocorrências do que existem para apanhar a primeira; e a `latencia_de_resposta_alta` **nunca resolvia**, porque um *gauge* que fica alto satisfaz a condição para sempre. Mais duas correcções minhas: o `ingress_parado` ficava **calado quando o ingress parava** (`increase()` sobre série ausente devolve nada, não zero) e levava **20 min** em vez dos ≤ 11 do critério 5, porque o `for: 10m` somava-se à janela de `[10m]`. **Nenhuma destas era visível pelo `check rules` nem pelo `obs_lint`**, e daí o `testes/kamba_test.yml`: **17 casos de `promtool test rules`**, que confrontam o que cada regra faz com o que devia fazer. **Não é a injecção em *staging*** que o critério pede — é o motor de regras com séries sintéticas, sem pilha e sem Alertmanager a receber —, e **não há *staging* a correr**. **E «chega ao canal certo» não se cumpre:** os três `receivers` **não têm notificador**, porque o canal não está escolhido (§16 não nomeia transporte; escolher um acrescenta um subprocessador, **KAM-069**). O «CI falha» é o mesmo credor do critério 3 |
| 5 | Sonda externa (fora do *host* e do fornecedor) a cada 5 min ao **número de teste de produção**; P1 «ingress parado» em ≤ 11 min ao parar o GWY em *staging* | **vazia** | **Não há produção, não há número de teste de produção e não há *host* externo onde pôr a sonda.** Nada disto se simula: uma sonda apontada a `localhost` não é uma sonda externa — é um teste a chamar-se sonda, e seria a caixa marcada com a prova errada. **O que se entregou da metade que não depende da sonda:** a regra `ingress_parado` existe, é P1, aponta para o RB-K01 e mede «0 mensagens > 10 min em horário comercial» sobre o `gwy_requests_total`, com a conversão **07:00–23:00 WAT = 06:00–22:00 UTC** escrita (o `hour()` do Prometheus é UTC; sem ela o alerta disparava todas as noites). A metade da sonda fica com credor **D1/KAM-105** (alojamento) e KAM-069 (subprocessador) |
| 6 | Painéis como código (JSON provisionado): venda, Meta, pagamentos, infra; Grafana só por VPN; consumo da pilha ≤ 1,5 GB medido | **parcial** | **Os quatro painéis existem como código**, versionados em [`../ops/paineis/`](../ops/paineis/), com `provisionamento.yaml`, e **verificados**: o `obs_lint` lê-os como terceira superfície e recusa uma consulta que filtre por identificador, **que o crie** com um `label_replace`, ou que cite métrica fora do catálogo (13 consultas, 0 achados). **Três *fixtures* negativas** provam que morde nos painéis, e duas delas vêm de furos medidos pela revisão: o `templating` e as `annotations` vivem **fora** de `panels` e não eram lidos — e uma variável de painel é o melhor sítio para esconder uma consulta —, e o `glob` não era recursivo quando o *file provider* do Grafana **lê as subpastas**. **Dos quatro painéis, o de pagamentos não tem série nenhuma**: é um painel de texto, porque nenhuma métrica de pagamentos está exposta (o módulo `hnd` não é importado por nenhum serviço). Não se desenhou um gráfico a zero — ali ele pareceria dizer que não há falhas de HMAC, quando o que diz é que ninguém está a contar. As 13 consultas repartem-se 9 + 2 + 0 + 2. **O Grafana não corre**, logo «só por VPN» não se verifica: é **AGPL-3.0**, credor **decisão de licença**. **O consumo mediu-se e não é a medição pedida:** tectos declarados, Prometheus 1 024 + Alertmanager 256 = **1 280 MiB** dentro do alvo; com Grafana (512) e Loki (256) a pilha completa dá **2 048 MiB**, acima de 1,5 GB. São tectos e não execução, e a pilha completa não corre |
| 7 | Os webhooks de *status* persistem `pricing` (`billable`, `category`, `type`) por mensagem, expostos como métrica agregada por tenant e categoria | **parcial** | **A persistência já existe e nenhuma migração é necessária** — foi medido antes de se escrever qualquer DDL: `platform.outbound_messages.pricing jsonb` carrega `billable`, `pricing_model`, `type` e `category` desde a revisão **`0010`** (KAM-015), com `COMMENT` nas quatro chaves, e nenhuma revisão `0011`–`0031` a altera. **O que falta é a ligação e a métrica:** o `statuses[]` do webhook chega ao `worker-canal`, mas o `explodirMensagens` extrai só `id`, `status` e as chaves de evento — o `EventoDeEntrada` **não tem campo** para o `pricing` —, e o braço `outbound` do encaminhador só regista o evento. Nenhum serviço importa o módulo `outbound`. **E a métrica agregada não existe**: o `SQL_CUSTO_DO_TENANT` soma por tenant e período e **não** agrupa por categoria. Credor: o ticket que ligar o estágio de saída (KAM-015). O agregado por **categoria** é admissível pelo `OBS-I` (domínio fechado em quatro); o por **tenant** sai de SQL e não de etiqueta, pelas emendas 1.21 e 1.25 |

| # | DoD | Estado | Evidência / credor |
|---|---|---|---|
| 1 | Todos os Critérios de Aceitação satisfeitos e demonstráveis | **vazia** | Não estão: nenhum dos sete fecha por inteiro. A razão de cada um está na tabela acima, e quatro dos credores não são de quem executa |
| 2 | Logs sem conteúdo nem identificadores directos; sem segredos em logs ou painéis (ADR-010) | **marcada** | Quatro provas, e nenhuma é por leitura. **Logs:** o *logger* tipado impõe a *allowlist* de 12 campos em compilação (tipos) e em execução (rejeição contada em `log_field_rejected_total`), e o **X-11** do gate 6 varre 1 030 *fixtures* pelos dois *loggers* por telefone `+244`/`9\d{8}`, e-mail, IBAN, token e canário — zero achados, saídas iguais byte a byte. **Etiquetas:** o `obs_lint` recusa 16 nomes de identificador em três superfícies, num selector, numa cláusula `by`/`on` **ou criada** por `label_replace`; e a regra do **valor** recusa um UUID mesmo com nome permitido. **Saída real:** `test_depois_de_contar_o_corpo_traz_o_formato_sem_identificadores` lê o corpo servido pelo `/metrics` do AGR. **A revisão adversarial mostrou que a primeira versão deste teste era tautológica** — olhava só para **nomes** de etiqueta, e os nomes de eixo do AGR vêm de dois literais, pelo que um `contact_id=` era impossível por construção e o teste não podia falhar. Passou a olhar também para a **forma dos valores** (UUID, `+244…`, `9########`, 32 hex, `wamid.…`), que é onde um identificador podia de facto viajar, porque o valor vem de quem chama o `contar`. **Painéis:** 13 consultas, 0 achados, com três negativas a provar que morde. **Segredos:** gate 9 sobre a árvore e sobre a história do PR |
| 3 | Métricas e custo nascem com a funcionalidade (ADR-018); painéis versionados | **parcial** | **Painéis versionados: sim** — quatro em `../ops/paineis/`, como código, com provisionamento e verificados pelo *lint*. **«Custo nasce com a funcionalidade»: não** — o `meta_cost_usd_total` e o `meta_cost_usd_estimate` existem em código e nenhum serviço importa o módulo `metering`, pelo que o custo não é observável em execução. Credor: o ticket que ligar o estágio de saída, e **KAM-081** para o custo por tenant |
| 4 | 0 alertas sem runbook (existe *stub* para cada `runbook_url`) | **marcada** | **Dez *stubs* RB-K01–RB-K10** criados, cada um com título, gatilho e severidade, e a linha canónica do §13. **Zero alertas sem runbook**, verificado por máquina: as regras `alerta_sem_runbook` e `runbook_inexistente` do `obs_lint` dão **0 achados** sobre as 8 regras, e o `runbook_url` tem de **resolver para um ficheiro no disco** (não basta parecer um URL). Dois testes prendem-no: `test_cada_runbook_citado_por_uma_regra_existe` e `test_os_dez_stubs_rb_k_existem`. **Mas a caixa escondia um defeito, que a revisão adversarial mediu e está corrigido.** A verificação é da **forma** — o ficheiro existe — e não do **efeito**: cinco dos seis alertas apontavam para o mesmo *stub* (RB-K03), dois deles para uma página que **não os menciona**, e o RB-K03 nomeava `fila_idade`, `latencia_p95` e `orcamento_llm`, três nomes que **não existiam em regra nenhuma** — quem atendesse abriria uma página a falar de outros alertas. Corrigido: os dois do AGR apontam para `runbooks/degradacao-do-agr.md`, que os reivindica por escrito, e **as dez linhas «Alertas que apontam para aqui» passaram a distinguir o que existe do que está por escrever**. **Uma ressalva que fica:** o 12.º alerta do §9.2 (memória) **não tem runbook no canon** — aquela linha diz «Escalar» —, o que contradiz a regra «alerta sem runbook é removido» do mesmo §9.2. Como esse alerta não se escreveu (não há *exporter*), não há hoje alerta sem runbook; o conflito fica medido em `../docs/observabilidade.md` §3.2 para quem governa o §9.2 |
| 5 | Documentação actualizada (catálogo de métricas, canal de alertas e escalamento inicial) | **marcada** | [`../docs/observabilidade.md`](../docs/observabilidade.md): **§2** o catálogo (com o legível por máquina em `../ops/metricas/catalogo.yaml`), **§4.1** o canal — documentado como **não escolhido**, com o efeito dito sem rodeios e os dois sítios que ele terá de tocar —, **§4.2** o escalamento inicial do §16 (primário → secundário aos 15 min → arquitecto, rotação semanal ≥ 3, 07:00–23:00 WAT) e **porque é que o Alertmanager não o implementa**. Mais `../docs/evidencia/KAM-080.md` com os comandos e as saídas. **Propagação feita:** o `docs/runbooks/degradacao-do-agr.md` dizia «não há sistema de alertas» e «o AGR não expõe `/metrics`» — as duas deixaram de ser verdade e o bloco foi reescrito; o `infra/README.md` e o comentário de cabeçalho do `prometheus.yml` idem. **A revisão adversarial encontrou duas que eu tinha deixado atrás, e estão corrigidas:** a *docstring* do `services/agr/src/kamba_agr/app.py` continuava a dizer que `create_app()` dá «só a `/healthz`» — no próprio ficheiro onde a rota nova está —, e o comentário do `prometheus` no compose dizia ser «o único membro de `ops`» três parágrafos acima do parágrafo que anuncia o Alertmanager ao lado. Mais a aritmética «6 das 12», que estava errada em cinco ficheiros |

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
- [x] `ops/slo.md` define os 8 SLIs do doc 09 §10 (numerador, denominador, janela de 30 dias, fonte, SLO, orçamento): disponibilidade do caminho de venda 99,5% (216 min); ack < 500 ms em 99,9% dos pedidos; perda de mensagens = 0; p95 de resposta texto ≤ 8 s e voz ≤ 12 s; callback → cliente notificado p95 ≤ 30 s e p99 ≤ 2 min; reconciliação de pagamentos por reconhecer ≤ 15 min; frescura do backup (WAL ≤ 5 min, restauro mensal OK); 0 horas de número em vermelho > 24 h.
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
- [x] Métricas dos SLIs sem conteúdo nem PII; painéis versionados.
- [x] Cada alerta de SLO tem runbook; relatório mensal de SLO com modelo.
- [ ] Rotação de *on-call* publicada com nomes e substitutos (prova do critério de ≥ 3 pessoas).
- [x] Documentação actualizada; alterações de SLO passam por registo.

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

### Verificação dos Critérios de Aceitação

Doze caixas — 7 critérios e 5 linhas de DoD —, **4 marcadas (critério 1 e DoD 2,
3 e 5), 4 parciais e 4 vazias**. Nenhuma fica sem razão escrita, e **cada uma das
oito nomeia o seu credor**. Os comandos e as saídas estão em
[`../docs/evidencia/KAM-082.md`](../docs/evidencia/KAM-082.md); a definição dos
SLI está em [`../ops/slo.md`](../ops/slo.md).

**Duas caixas devolvem-se por serem de outra autoridade, e dizem-se à cabeça:**

- **O critério 5 (estado `congelado` ligado ao *gate* 16).** O *gate* 16 **não é
  um *job* de CI**: o `specs/01` §4 define-o como «**Aprovação** — gate humano»,
  e o `ci.yaml` tem *jobs* para os gates 1, 2, 3, 3b, 3c, 4, 6, 7, 8, 9 e 11 e
  mais nenhum. Ligar um portão a recusar *deploys* é **alteração de regra de
  bloqueio pelos dois caminhos** — um *job* novo acrescenta contexto exigido ao
  *ruleset* da `main` e ao agregador «gates do KAM-002», e mudar o critério de um
  portão que já bloqueia é a mesma fronteira por outra porta. Entrega-se a
  **política escrita** (`ops/slo.md` §6.1) e a **medição de que ela morde** (o
  painel, com o limiar de 0,5 marcado). **Credor: o fundador.**
- **O critério 7 (*on-call*).** Rotação semanal com ≥ 3 pessoas é gente, não
  código, e **o repositório é público**: uma escala com nomes é um inventário de
  quem está acordado a que horas. Entrega-se `ops/on-call.md` com marcadores de
  **papel** e nenhum nome, como o próprio *handoff* manda. **Credor: o fundador**,
  e **KAM-069** para o canal.

> **A medição que decide a forma deste ticket, e fez-se antes de escrever
> regras.** O §10 tem **oito** SLI; deles, **um** tem série que algum processo
> sirva e que o `prometheus.yml` raspe. Das **120** métricas declaradas em código
> (medido: `tools/obs_lint/contar_metricas.py`; **122** pela reconciliação `+2`
> do `services/com`), só **51** são alcançáveis numa pilha de `docker compose`,
> porque onze módulos do `packages/core-ts` não são importados por nenhum
> serviço. Um SLI assente numa série que ninguém produz **nunca dispara**, e um
> alerta que nunca dispara **parece cobertura** — pior do que a sua ausência,
> porque ninguém volta a olhar. **Os sete não se escreveram como regras inertes**;
> ficam definidos em prosa, com numerador, denominador, janela, fonte, SLO,
> orçamento e **credor**, em `ops/slo.md` §2.2. É a mesma leitura com que o
> KAM-080 deixou oito das doze regras do §9.2 por escrever.
>
> **E um dos sete tinha este ticket como credor.** O catálogo do KAM-080 escreveu
> «o p95 não é computável… credor: KAM-082 (SLOs), que é quem precisa do
> quantil». A resposta medida é que **dar histogramas ao AGR é contrariar o
> ADR-018** («observabilidade leve»), escrito no próprio `metricas.py`, e que a
> modalidade (texto contra voz) não existe como etiqueta — criá-la é emenda ao
> dicionário. As duas são decisões de canon, não de execução: o credor passa a ser
> **o fundador**, com a medição feita e não a suposição herdada.
>
> **Um defeito encontrado a medir, e corrigido:** o
> `--storage.tsdb.retention.time` do `docker-compose.prod.yml` era **15d**, e um
> `avg_over_time(...[30d])` sobre 15 dias de dados **não dá erro** — devolve a
> média das amostras que existem. Era um número errado com ar de certo e
> enviesado para o optimismo, porque uma avaria de há 20 dias cai fora da janela e
> o orçamento «sara» duas semanas antes do devido. Está em **31d**.

| # | Critério | Estado | Evidência / credor |
|---|---|---|---|
| 1 | `ops/slo.md` define os 8 SLI do doc 09 §10 (numerador, denominador, janela de 30 dias, fonte, SLO, orçamento) | **marcada** | [`../ops/slo.md`](../ops/slo.md): os **oito**, cada um com os seis campos. O §2.1 dá o operacional por extenso (disponibilidade, 99,5%, **216 min**, por `up{job=~"gwy\|agr"}`); o §2.2 dá os outros sete em tabela, cada um com numerador, denominador, SLO, orçamento, **fonte** (a coluna do §10, copiada e não reinterpretada) e **o que falta com o credor**, sobre a janela de 30 dias que é a mesma dos oito e está dita acima da tabela. Os valores são os do §10 à letra, reconferidos linha a linha contra a tabela do documento-fonte — **e a coluna «Fonte» entrou numa segunda passagem**, porque a primeira versão desta tabela tinha cinco dos seis campos e o critério pede seis: a caixa estava marcada com um campo a menos, e foi a revisão adversarial que o ia levantar. O critério pede que o ficheiro **defina**, e define — o que cada um deles ainda não mede está nas caixas 2 a 4 e no §2.2, não escondido aqui |
| 2 | *Recording rules* e painel mostram o orçamento restante; com 30 min de falha injectada do ingress em *staging* o orçamento desce 13,9% (30/216) e o alerta de *burn rate* dispara | **parcial** | **A aritmética está provada, e por ensaio e não por afirmação.** Oito *recording rules* em [`../infra/compose/prometheus/regras/kamba-slo.yml`](../infra/compose/prometheus/regras/kamba-slo.yml) → `promtool check rules`: `SUCCESS: 10 rules found`. O caso `orcamento: 30 min de falha injectada descem 13,9% (30/216)` dá **0,1388888…** e **186 min**, com o controlo (30 dias limpos → 216 inteiros) e o estouro (240 min → **−24 min**, negativo de propósito). A segunda metade do critério tem caso próprio: `criterio 2: 30 min de falha do ingress disparam o burn rapido`. O painel é [`../ops/paineis/orcamento-de-erro.json`](../ops/paineis/orcamento-de-erro.json), com o restante em minutos e o consumido em fracção lado a lado. **O que falta é a injecção em *staging*:** o Prometheus só existe no `docker-compose.prod.yml`, **não há ambiente implantado** e o `make up` (dev) não levanta Prometheus nenhum. `promtool test rules` é o motor de regras com séries sintéticas — sem pilha, sem GWY a morrer, sem Alertmanager a receber — e **não é** a injecção que o critério pede. Credores: **D1/KAM-105** (alojamento) e **KAM-069** (subprocessador), os mesmos do critério 5 do KAM-080 |
| 3 | «Perda de mensagens» operacionalizada como ids aceites no ingress sem desfecho após 15 min = 0 (*proposta*); testada com uma mensagem retida artificialmente | **parcial** | **A operacionalização está escrita** (`ops/slo.md` §2.2, linha 3), com as duas faltas medidas e não supostas. (a) O `inbound_events_total{desfecho}` com o domínio fechado `registado`/`duplicado`/`recuperado` **existe** em `packages/core-ts/src/entrada/metricas.ts` e é servido pelo `entrada.ts` na porta 3013 — que **não é o que o compose corre**: o `CMD` do `services/worker-canal/Dockerfile` é `src/server.ts`, que devolve **404** em `/metrics` por teste do KAM-001, e o `prometheus.yml` não tem alvo para as quatro entradas que servem métricas. Medido. (b) A correlação **por id** entre aceite e desfecho não é expressável em métricas agregadas: sai de consulta SQL sobre `platform.channel_events`, pela mesma razão por que o por-*tenant* sai de SQL (emendas **1.21** e **1.25** do dicionário). **A caixa não se marca com o ensaio de uma mensagem retida**, porque não há processo que sirva a série nem pilha onde a retenção aconteça — marcá-la com a prova errada é pior do que a deixar vazia. Credores: o ticket que decidir qual processo do `worker-canal` o compose corre, e **KAM-110** para a consulta |
| 4 | Alertas de *burn rate* rápido e lento activos (*proposta*: 2% do orçamento numa hora → P2; 5% em 6 h → P3), calibrados e documentados | **parcial** | **Os dois existem, com os limiares que o critério propõe e a severidade que ele dá** (`orcamento_de_erro_burn_rapido` P2, `orcamento_de_erro_burn_lento` P3), ambos com `runbook_url` que resolve para ficheiro no disco, e **documentados** em `ops/slo.md` §4 e no *runbook* [`../docs/runbooks/orcamento-de-erro.md`](../docs/runbooks/orcamento-de-erro.md), que os reivindica por nome. **O que prende a calibração são os casos em volta do limiar e não um caso que dispare:** 4 min de falha numa hora → calado, 5 min → dispara; 10 min em seis horas → calado, 11 min → dispara; e o caso que mostra que o lento não é redundante (11 min no **início** das seis horas disparam o lento com o rápido calado). **A palavra «calibrados» não se cumpre**, e a razão está nos Detalhes Técnicos do próprio ticket: «os valores de *burn rate* … são propostas; calibram-se nos primeiros 30 dias». Calibrar exige tráfego real, que não existe. Credor: **Plataforma/SRE**, no primeiro relatório mensal com tráfego (modelo em [`../ops/slo-relatorio-modelo.md`](../ops/slo-relatorio-modelo.md), §7) |
| 5 | Política: > 50% do orçamento em 14 dias marca `congelado`; o *gate* 16 recusa *deploys* não urgentes nesse estado (excepto aprovação do Arquitecto registada); 100% → só fiabilidade; testes do *gate* | **vazia** | **Devolvida, e é a primeira das duas que se diz à cabeça.** A política está escrita por extenso nos três estados em `ops/slo.md` §6.1, com «urgente» definido como *proposta* (o §10 e o bloco não o definem), e a **medição** está no painel. O que não se fez é o estado e a ligação ao portão, por duas razões medidas: o *gate* 16 **não existe como *job*** (é o gate humano de aprovação do `specs/01` §4; o `ci.yaml` tem onze *jobs* de gate e nenhum é o 16), e ligá-lo é **alteração de regra de bloqueio pelos dois caminhos**. Registada também a divergência de janela: a política fala de **14 dias** e as regras medem **30**, que é a janela que o critério 1 e o §10 definem — a segunda janela é uma linha de PromQL e **não se escreveu**, porque sem o estado a existir ela não tinha consumidor e seria mais uma série a parecer cobertura. **Credor: o fundador** |
| 6 | Janelas de manutenção anunciadas fora de 07:00–23:00 WAT contam como indisponibilidade **só** se afectarem mensagens (regra implementada e testada com duas janelas) | **parcial** | **A regra está implementada nas três condições que o critério tem** — anunciada, fora de 06:00–22:00 UTC (= 07:00–23:00 WAT, porque o `hour()` do Prometheus é UTC) e sem mensagens afectadas — e a isenção faz-se por `unless`, pelo que o tempo isento sai do numerador **e** do denominador. **Testada com duas janelas, e com uma terceira que prende a condição que elas não prendiam:** isenta; conta porque afectou mensagens; conta porque era horário comercial. O mecanismo do **anúncio** tem ensaio próprio em [`../infra/compose/prometheus/regras/testes/kamba_manutencao_test.yml`](../infra/compose/prometheus/regras/testes/kamba_manutencao_test.yml), com duas janelas sobre uma *fixture*, para que quem anunciar a primeira a sério não estreie a expressão. **E o ficheiro de regras de produção das janelas passou a estar sob ensaio**, o que não estava: a revisão adversarial mediu que pôr o `vector(0)` do `kamba-manutencao.yml` a `vector(1)` isentava **toda** a indisponibilidade nocturna sem *shed* e deixava os quatro ficheiros de ensaio verdes — um orçamento de erro que para de contar sem um único teste vermelho, e com o procedimento documentado para anunciar uma janela a ser *editar aquela expressão*. Fechado pelo `testes/kamba_slo_producao_test.yml`, que carrega os **dois** ficheiros de produção juntos e exige que a bandeira valha 0 e que o tempo conte. **O limite que fica, com a consequência tirada e não só o limite dito:** «afectou mensagens» é `increase(gwy_shed_total[30m]) > 0`, e com o GWY em baixo **não existe série** `gwy_shed_total` — o `increase` sobre série ausente devolve nada, o `or vector(0)` dá 0, e a janela é julgada «não afectou mensagens». Para uma janela que derrube o ingress, que é o caso normal, esta condição responde **sempre «não»**: o «**só** se afectarem mensagens» do critério é, na prática, **incondicional**. A primeira versão deste ticket dizia o limite em três sítios e **não tirava dele esta conclusão**. Fica assim por escolha e não por engano — a isenção é uma afirmação de quem anunciou a janela, e esta pilha só a pode **refutar**, nunca confirmar; inverter o omisso tornava a regra letra morta pelo outro lado. O que a torna auditável é o anúncio ser um **commit** e o relatório mensal ter uma coluna para ela. O predicado completo é o que a sonda externa responderia: credores **D1/KAM-105** e **KAM-069**. E a lista de janelas anunciadas está **vazia**, porque nenhuma foi anunciada |
| 7 | *On-call*: rotação semanal com ≥ 3 pessoas, cobertura 07:00–23:00 WAT; fora disso um P1 chama apenas o primário; não reconhecido escala ao secundário em 15 min e depois ao Arquitecto (teste de simulação) | **vazia** | **Devolvida, e é a segunda que se diz à cabeça.** Entregue: [`../ops/on-call.md`](../ops/on-call.md) com os requisitos do §16 fixados, a escala em **marcadores de papel** e **nenhum nome de pessoa** — o repositório é público, e o *handoff* do ticket manda-o por escrito. **O «teste de simulação» não se faz, e não é por falta de tempo:** o Alertmanager **não notifica ninguém** (os três `receivers` não têm notificador, porque o canal não está escolhido — **KAM-069**), e o escalamento temporizado **não é dele**: ele reenvia e inibe, mas não sabe se alguém *reconheceu* um alerta nem muda de destinatário por isso, o que exige um gestor de plantão, que é outro subprocessador. Simular escalamento sem canal e sem pessoas seria um ficheiro a ler-se a si próprio. **Credor: o fundador** para a rotação; **KAM-069** para o canal |

| # | DoD | Estado | Evidência / credor |
|---|---|---|---|
| 1 | Todos os Critérios de Aceitação satisfeitos e demonstráveis | **vazia** | Não estão: **1 dos 7** fecha por inteiro. A razão de cada um está na tabela acima, e **dois dos credores são o fundador** |
| 2 | Métricas dos SLI sem conteúdo nem PII; painéis versionados | **marcada** | **Três provas, e nenhuma é por leitura.** (a) As **nove** séries novas têm `etiquetas: []` no catálogo — **não levam etiqueta nenhuma**, pelo que não há onde um identificador viaje; são derivadas por *recording rule* e o seu valor é uma fracção. (b) O `obs_lint` lê as três superfícies com o catálogo e o painel novos dentro: **0 achados** sobre **27 métricas, 20 regras em 3 ficheiros, 10 alertas e 22 consultas em 5 painéis**. (c) O canário continua a morder: **16 negativas e 2 positivas**, todas a morder a sua regra. Painéis versionados: o quinto é `ops/paineis/orcamento-de-erro.json`, e o `provisionamento.yaml` não precisou de mudar porque o provedor lê a pasta inteira |
| 3 | Cada alerta de SLO tem *runbook*; relatório mensal de SLO com modelo | **marcada** | **Zero alertas sem *runbook*, verificado por máquina:** as regras `alerta_sem_runbook` e `runbook_inexistente` do `obs_lint` dão 0 achados sobre os **10** alertas, e o `runbook_url` tem de **resolver para um ficheiro no disco**. O *runbook* é [`../docs/runbooks/orcamento-de-erro.md`](../docs/runbooks/orcamento-de-erro.md), e **reivindica os dois alertas por nome** — que é a correcção que o KAM-080 teve de fazer quando cinco dos seis alertas apontavam para uma página que não falava deles. **Não leva número RB-K** de propósito: a série RB-K01–RB-K10 é a lista fechada do §13 e inventar um RB-K11 era acrescentar uma linha a um canon que este ticket não governa. Modelo mensal: [`../ops/slo-relatorio-modelo.md`](../ops/slo-relatorio-modelo.md), oito secções, **cada número com a consulta que o produz** |
| 4 | Rotação de *on-call* publicada com nomes e substitutos (prova do critério de ≥ 3 pessoas) | **vazia** | **Não se cumpre por desenho, e a razão é o repositório ser público.** «Publicada com nomes» num repositório público é publicar quem está acordado a que horas. O `ops/on-call.md` tem três linhas de rotação (três, porque com menos de três uma pessoa está de serviço em semanas seguidas) com marcadores de **papel**; a atribuição de pessoas fica fora do repositório, num sítio com controlo de acesso. **Credor: o fundador** |
| 5 | Documentação actualizada; alterações de SLO passam por registo | **marcada** | **O registo existe:** `ops/slo.md` §9, `ops/on-call.md` §4 e `ops/slo-relatorio-modelo.md` §8 têm «Controlo de versões». **E não é verificado por máquina, ao contrário do que esta célula dizia** — a revisão adversarial mediu-o: o corpus do `tools/lint_backlog/versoes.py` é `('specs/**/*.md', 'docs/**/*.md', 'README.md')`, com `docs/analises/` e `docs/evidencia/` excluídos por `PASTAS_DE_REGISTO`, pelo que **`ops/` não entra** e os 78 documentos contados não incluem nenhum destes três (medido: 78 antes e 78 depois do ticket). Um buraco na sequência de versões destes ficheiros passa. **Não se alargou o corpus aqui:** `versoes.py` é o instrumento do *gate* 3c, e alargá-lo muda o critério de um portão que já bloqueia — a mesma fronteira que o critério 5 devolve. Credor: **o fundador**, com a emenda de uma linha nomeada. O que fica verificado por máquina é o resto da propagação, abaixo. **Propagação feita, e medida contra o que deixou de ser verdade:** o `docs/observabilidade.md` dizia no «Não cobre» que os SLOs não existiam e contava **quatro** painéis — hoje diz onde eles estão e conta cinco, com linha nova para as regras de SLO e emenda **1.2** no seu controlo de versões; o comentário do `ops/paineis/provisionamento.yaml` dizia «os quatro painéis». **O que não se tocou:** as contagens do §3 e do §5 do `observabilidade.md`, que dizem «as 8 regras do `kamba.yml`» e continuam exactas — reescrever a medição de outro ticket era reescrever a medição de outro ticket |

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
| 1.3 | Novembro 2026 | **KAM-075 entregue**, com a secção «Verificação dos Critérios de Aceitação» no bloco: **13 caixas, 7 marcadas e 6 vazias**, e as seis com a razão escrita. Quatro das seis dependem da **D1**, que está `em branco` e é acto do fundador — sem conta e sem fornecedor não há `apply`, não há cronómetro e não há cotação, pelo que **os 30 minutos de um *host* novo não foram medidos** (zero execuções) e o custo mensal a partir de cotação real não existe (nenhuma pedida). O que fica entregue e medido: a estrutura `infra/{modules,envs/*}`, a matriz do doc 09 §6 em forma comparada por máquina no gate 2 (`tools/env_lint`, 0 achados, canário com 25 de 25 mutações a morder, a exercitar as 11 regras), o mapeamento ambiente → projecto de segredos com o negativo que o faz falhar, a recusa de `kamba_data_class=real` sem referência de D1 e sem `apd_ref`, a recusa de restauro de `prod` noutro ambiente, e a costura `infra/modules/provider-pendente/` que **falha fechado** — um `tofu plan` pára nela com zero recursos planeados. A ferramenta fica no ADR-L007 (OpenTofu mais cloud-init; Terraform e Ansible excluídos pela política de licenças do próprio repositório). Quatro perguntas devolvidas ao fundador no fim da secção, entre elas a divergência entre as «7 linhas» do critério 1 e as **oito** do doc 09 §6, registada em vez de corrigida. **A revisão adversarial reprovou o ramo** e as suas duas razões estão corrigidas: um gate 4 vermelho deste diff (o cabeçalho do `../specs/02` em 1.52 com a emenda 1.53) e a caixa do critério 5, que era evitável escrevendo a referência num `terraform.tfvars` em vez de num `.tf`. Os quatro furos que ela mediu eram todos da camada de **recolha** e não das regras — o filtro de extensões, o filtro `.tf`, as 12 chaves comparadas e a lista fixa de três ambientes —, e as quatro mutações são hoje casos de canário. Mais dois defeitos do cloud-init que nenhuma máquina podia apanhar: o `mkfs` podia formatar o disco de arranque, e o `sudo` do `admin` era inutilizável com a palavra-passe bloqueada (reproduzido). Nenhum *host* esteve em risco, porque nunca houve *host*. | Equipa KAMBÁ |
| 1.4 | Novembro 2026 | **KAM-076 entregue**, com a secção «Verificação dos Critérios de Aceitação» no bloco: **13 caixas, 4 marcadas e 9 vazias ou parciais**, cada uma com a razão. Entregue e medido: o Compose de produção e o de *staging* do conjunto reduzido, **com as mesmas imagens**, em quatro redes isoladas; o conjunto declarado em `infra/compose/conjunto-reduzido.yaml` com os três estados (`presente`, `pendente` com ticket, `proibido` com ADR), que é o outro sentido do «exactamente» do critério 1; o novo `tools/compose_prod` no gate 2 (**0 achados**, canário com **45 de 45** mutações a morder e **13 de 13** regras, 36 testes próprios) e o guião dos dez destinos no gate 6 — **10 destinos, 4 permitidos e 6 recusados, todos com o veredicto esperado e cada recusa registada** no `access_log`, que é a metade do critério 3 que se esquece. As quatro redes mediram-se: numa rede `internal: true` **não para só o tráfego, para o DNS**, e uma rede declarada e sem membros **não é criada** — foi por isso que o `ops` nasceu com o Prometheus dentro. A soma dos limites fecha **exacta** nos ≈ 23,5 GB do bloco (24 064 MiB, 92% do tecto de 80% de 32 GiB), com teste que prende os dois números. Consumo em repouso **medido**: 637 MiB com sete contentores `healthy`. O intervalo de Node do Medusa sai de **NÃO VERIFICADO** para **CONFIRMADO** por leitura do `engines` (Medusa 2.21.2 aceita `^20.19.0 || >=22.12.0`, logo **Node 24 serve**). As quatro imagens novas foram reconfirmadas, três **por execução**, e as licenças lidas e não herdadas — o Envoy entrou no lugar do Squid **por licença** (GPL-2.0 é negada) e o Grafana e o Loki ficam de fora pela mesma razão (AGPL-3.0), o que devolve ao KAM-080 uma decisão de licença que ninguém tinha visto. **O que não se cumpre, e porquê:** o critério 2 para os cinco serviços nossos, porque o `release.lock` é do **KAM-078**, que depende deste ticket; o critério 3 para o FQDN do facilitador e o de STT, porque **nenhum serviço os declara** e um destino aprovado sem dono é o contrário de negar por omissão; o critério 7 por inteiro, porque a **D6** está aberta; e o critério 6 porque o ensaio da Valkey ficou **incompleto** (BullMQ CONFIRMADO, Sidekiq INDÍCIO, Medusa **não aplicável** — usa módulos em memória), pelo que a **D12 continua aberta** e a ADR-P09 continua proposta (ADR-L009). **Dois defeitos que só apareceram a correr a pilha** e que nenhum `docker compose config` apanha: o Caddy não **executava** com `cap_drop: ALL` (capacidade de ficheiro no binário, não a porta) e o LiteLLM recusava arrancar com os nomes de variável que eu copiei do compose do KAM-030, que o config gerado já não procura — os dois corrigidos, remedidos, e o segundo deixou um achado no `docker-compose.llm.yml`, que tem o mesmo defeito. **E um erro meu, corrigido em vez de apagado:** escrevi que a falha de `tests_eventos` era pré-existente «medido» a partir de um controlo que falhava os **vinte** testes por lhe faltar o ambiente; a conclusão caiu e o estado é **NÃO VERIFICADO**. Não se mexeu em `.github/rulesets/` nem no `ci.yaml`: a recomendação de não criar contexto exigido novo vai com a medição, e a decisão é do fundador. | Equipa KAMBÁ |
| 1.5 | Novembro 2026 | **KAM-080 entregue**, com a secção «Verificação dos Critérios de Aceitação» no bloco: **12 caixas, 3 marcadas (DoD 2, 4 e 5) e 9 vazias ou parciais**, cada uma com a razão e **com o credor nomeado** — e quatro dos credores não são de quem executa. Entregue e medido: o `tools/obs_lint` (**10** regras, **3 superfícies** — catálogo, regras de alerta e painéis —, 0 achados na árvore, canário com **16 negativas e 2 positivas**, 94 testes e **91%** de cobertura), **8** regras de alerta que cobrem **4 das 12 linhas** do §9.2 com **17 casos de `promtool test rules`**, os **dez** *stubs* RB-K01–RB-K10, o Alertmanager 0.28.1 (Apache-2.0 **lido do projecto na etiqueta, porque a imagem não traz `/LICENSE`** — a armadilha que o Envoy já tinha pregado) no orçamento de 256 MiB que o conjunto reduzido lhe reservava, os quatro painéis como código, e o **`/metrics` do AGR**, que servia **zero** das suas 44 métricas e cuja falta o próprio `docs/runbooks/degradacao-do-agr.md` nomeava. **A medição que explica o resto, agora com instrumento no repositório** (`tools/obs_lint/contar_metricas.py`, com o predicado escrito antes da contagem): das **115** métricas declaradas, só **7** eram alcançáveis numa pilha de `compose` (agora 51), porque **dez** módulos do `packages/core-ts` **não são importados por nenhum serviço** — e o número de declaradas subiu de 109 para 115 durante a integração, com o `provisioning` do KAM-091, sem que as servidas mudassem — logo 8 das 12 linhas do §9.2 não se escreveram, e **não como YAML inerte**: um alerta que nunca dispara parece cobertura. **A revisão adversarial deu 19 achados e mudou código**, e os mais graves eram desta classe: **quatro das regras não funcionavam** — três alertas do AGR nunca disparavam na primeira ocorrência (o `exposicao()` não emite séries a zero, logo o contador nasce a 1 e o `increase` não vê subida) e a latência nunca resolvia (um *gauge* que fica alto) — e o *lint* tinha **cinco furos**, nenhum visível pelo canário porque não eram regras a falhar mas verificações que não existiam: `tenant_id` com só um tecto, um `label_replace` a **criar** um `contact_id`, um `{__name__="…"}` a contornar o catálogo, o `templating` e as subpastas dos painéis sem leitura, e o `exposta_por: []` como promessa não cumprida. Todos corrigidos, cada um com caso de teste ou *fixture* negativa. Mais dois defeitos meus, encontrados antes: o `ingress_parado` ficava **calado quando o ingress parava** (`increase()` sobre série ausente devolve nada, não zero) e levava 20 min em vez dos ≤ 11 do critério 5. **O que se devolve medido em vez de se fingir:** o canário em Loki e os painéis servidos, porque o **Grafana e o Loki são AGPL-3.0** e a decisão de licença que o KAM-076 devolveu a este ticket **também não é deste**; a injecção de falha em *staging* e a sonda ao número de produção, porque **não há *staging* nem produção** (uma sonda apontada a `localhost` não é uma sonda externa); o «chega ao canal certo», porque os três `receivers` **não têm notificador** — o §16 não nomeia transporte e escolher um acrescenta um subprocessador (KAM-069); e o consumo da pilha, porque 1 280 MiB é o tecto do que corre e 2 048 MiB o da pilha completa, acima do alvo. **O *lint* entrega-se sem portão**, e pelos dois caminhos: um *job* novo acrescenta contexto exigido ao *ruleset*, e uma linha no `ci-2` muda o critério de um portão que já bloqueia — é a mesma fronteira, e a decisão é do fundador. **Nenhuma migração foi escrita, e mediu-se porquê:** o `pricing` com `billable`, `pricing_model`, `type` e `category` existe em `platform.outbound_messages` desde a revisão `0010`, e o que falta é a ligação do `statuses[]` e um `GROUP BY`. Quatro divergências do canon ficam nomeadas e não resolvidas: o 12.º alerta do §9.2 não tem runbook («Escalar»), o que contradiz a regra do próprio §9.2; o critério 3 pede `tenant_id` em etiqueta, que as emendas **1.21** e **1.25** do dicionário já recusaram duas vezes; o `exposicao()` do AGR não emite séries a zero, preso por três testes de outro ticket; e em *staging* todo o alerta sai com `ambiente: prod`, porque os dois composes montam o mesmo `prometheus.yml`. | Equipa KAMBÁ |
| 1.6 | Novembro 2026 | **KAM-116**, e é uma emenda de **propagação** e não de conteúdo deste epic: o inventário fechado de módulos de métricas do `tools/obs_lint` ficou vermelho com o `packages/core-ts/src/sms/metricas.ts`, e a mensagem do próprio *gate* manda levar os números novos à secção de verificação do KAM-080. Medido: `contar_metricas` passa de **19 módulos, 113 nomes** para **20 módulos, 120 nomes**, e a reconciliação `+2` do `services/com` dá **122** declaradas, eram 115. **Os números da medição do KAM-080 ficam como estavam** — são a medição daquele ticket, e reescrevê-los era reescrever a medição de outro; o que entra é uma nota a dizer onde o número está hoje. E a nota vale por si: o KAM-080 argumenta que «o número de declaradas sobe sem que os outros dois subam», com o KAM-091 como exemplo — o KAM-116 é o **segundo**, à letra, com sete nomes que nenhum serviço importa, porque quem liga a porta `SmsProvider` é o KAM-086. Nenhuma caixa deste epic muda. | Equipa KAMBÁ |
| 1.7 | Novembro 2026 | **KAM-082 entregue**, com a secção «Verificação dos Critérios de Aceitação» no bloco: **12 caixas, 4 marcadas (critério 1 e DoD 2, 3 e 5), 4 parciais e 4 vazias**, cada uma com a razão e **com o credor nomeado**. Entregue e medido: os **oito** SLI do §10 definidos em [`../ops/slo.md`](../ops/slo.md) com numerador, denominador, janela de 30 dias, fonte, SLO e orçamento; **oito *recording rules*** do orçamento de **216 min** e **dois alertas de *burn rate*** (rápido P2 a 2% numa hora, lento P3 a 5% em seis) em `kamba-slo.yml`, com a bandeira das janelas de manutenção em `kamba-manutencao.yml`; o painel `ops/paineis/orcamento-de-erro.json`; e **21 casos de `promtool test rules`** (na unidade do KAM-080: blocos `- interval:`), com **43** afirmações em quatro ficheiros novos — quatro porque o `evaluation_interval` é por ficheiro e a janela de 30 dias e a fronteira dos alertas pedem cadências incompatíveis, e porque o quarto é o único que carrega os **dois** ficheiros de regras de produção juntos. **A aritmética do critério 2 está provada e não afirmada:** 30 min de falha dão **0,1388888…** e **186 min** restantes, com controlo (30 dias limpos → 216 inteiros) e estouro (240 min → **−24 min**, negativo de propósito). **E a força dos ensaios foi medida três vezes, porque as duas primeiras medições discordaram.** A minha, de seis mutações escolhidas por mim: 6 mortas, 0 sobreviventes — verdadeira sobre as seis e **falsa sobre o que parecia dizer**, porque um canário só prova os defeitos que quem o escreve escolheu, e quem escolhe é quem escreveu os ensaios. A da revisão adversarial, com 23 pontos escolhidos por quem não os escreveu: **10 sobreviventes**, e quase todos as **decisões semânticas centrais** — o `or vector(0)`, o AGR no numerador, as janelas dos dois alertas, as fronteiras do horário, o divisor da escala, e o `kamba-manutencao.yml`, que **não estava carregado por ensaio nenhum**. A terceira, depois de fechar as dez: **29 mortas, 0 sobreviventes, de 29**. Uma das dez tinha causa na *fixture* e não no ensaio — as janelas começavam em instantes que não são múltiplos do intervalo de avaliação, logo a fronteira **não era consultável**, e a lição é geral: uma fronteira que não cai num instante de avaliação não é testável, e o ensaio que a rodeia parece prendê-la. **A medição que decide a forma do ticket:** o §10 tem oito SLI e só **um** tem série que algum processo sirva e que o `prometheus.yml` raspe — das **120** métricas declaradas (122 com a reconciliação `+2` do `services/com`) só **51** são alcançáveis em `compose`, porque onze módulos do `core-ts` não são importados por nenhum serviço. Os sete restantes **não se escreveram como regras inertes**, porque um alerta que nunca dispara parece cobertura: ficam definidos em prosa com credor. **Um deles tinha este ticket como credor** (o p95, que o catálogo do KAM-080 deixou ao KAM-082) e devolve-se medido: dar histogramas ao AGR contraria o **ADR-018**, e a modalidade texto/voz não existe como etiqueta — as duas são canon, logo **o fundador**. **Um defeito encontrado a medir e corrigido:** a retenção do TSDB era **15d** e a janela do SLO é de **30d** — um `avg_over_time(...[30d])` sobre 15 dias **não dá erro**, devolve a média do que existe, e o orçamento «sarava» duas semanas antes do devido. Está em **31d**, sem mexer em `mem_limit` nenhum. **Devolve-se com credor, e à cabeça:** a ligação do estado `congelado` ao *gate* 16 — que **não é um *job* de CI**, é o gate humano de aprovação do `specs/01` §4, e ligá-lo é alteração de regra de bloqueio pelos dois caminhos (**o fundador**) — e a rotação de *on-call*, que é gente e não código, entregue em `ops/on-call.md` com marcadores de papel e **sem nomes de pessoas**, porque o repositório é público (**o fundador**, e **KAM-069** para o canal). **E a injecção de falha em *staging* dos critérios 2 e 3 não tem onde correr:** o Prometheus só existe no compose de produção, não há ambiente implantado, e `promtool test rules` **não é** a injecção pedida — diz-se, em vez de se marcar a caixa com a prova errada. **A revisão adversarial deu 15 achados e verificaram-se os 15 contra a árvore: 15 CONFIRMADOS, nenhum morto** — e três eram afirmações minhas falsas, que é a classe que mais custa. (a) A célula do DoD 5 oferecia o `lint_backlog` como prova de máquina das tabelas de versão dos três documentos novos, e o corpus dele é `('specs/**/*.md', 'docs/**/*.md', 'README.md')`: **`ops/` não entra**, e os 78 documentos contados são 78 antes e 78 depois. Corrigida, e **o corpus não se alargou** — o `versoes.py` é o instrumento do *gate* 3c, e alargá-lo muda o critério de um portão que já bloqueia, a mesma fronteira que o critério 5 devolve. (b) Os números do `lint_refs` no anexo não reproduziam, porque foram medidos antes de os ficheiros novos estarem versionados — e **os lints só vêem o que está versionado**. (c) O `b6c4ddb` deixou uma frase partida no próprio spec. Mais duas propagações em falta: o `catalogo.yaml` continuava a nomear o KAM-082 credor do p95 que este ticket devolveu ao fundador (dois documentos com credores diferentes para a mesma falta), e o comentário do contentor do Prometheus dizia «oito regras de alerta» quando o `rule_files` monta a pasta inteira e ele carrega **20 regras em 3 ficheiros, 10 delas alertas**. E o achado mais afiado não era código, era uma conclusão não tirada: com o ingress em baixo **não existe série** `gwy_shed_total`, logo o predicado «afectou mensagens» responde sempre «não» e o «**só** se afectarem mensagens» do critério 6 é, no caso comum, **incondicional** — o limite estava escrito em três sítios e a consequência em nenhum. **E o próprio defeito da retenção tinha o chão aberto:** um Prometheus que arrancou há três dias publica um «orçamento de 30 dias» calculado sobre 10% da janela, sem erro e sem aviso; entrou a série `slo_caminho_de_venda_amostras_30d` e um painel ao lado do número. **E um gate 4 vermelho meu, que a revisão deu por verde e a medição não:** o `test_os_quatro_paineis_do_criterio_6_existem` do `obs_lint` é um `assertEqual` com quatro nomes e o quinto painel parte-o — partido em dois, o critério 6 continua exigido pelo nome e um painel sem ticket que o reivindique continua a falhar. O `log_policy` vermelho é do **ambiente** e não do ramo: `ModuleNotFoundError: kamba_core` com `Ran 69`, e com o `PYTHONPATH` completo dá **Ran 114, OK**. | Equipa KAMBÁ |
