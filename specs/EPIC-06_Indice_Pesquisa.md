# EPIC-06 — Índice e Pesquisa

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Índice e Pesquisa |
| Versão | 1.2 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/03_Core_Comercio_Medusa.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-04_Core_Comercio.md` |

---

## 1. Visão do Epic

O **IDX** responde à pergunta «o que é que *esta loja* vende que corresponda ao que o cliente escreveu ou disse». No Piloto é um índice **por tenant**, em Postgres 18 com `pgvector` ≥ 0.8.7, `pg_trgm` e FTS em português, sem serviço de pesquisa externo (ADR-006). A pesquisa é recuperação de candidatos: **nunca é fonte de preço nem de stock**. Essas grandezas só existem no Registo (COM) e entram na resposta por *join* com a oferta viva no momento de responder, sob o validador de citação com verificação por `sku` (ADR-007). O epic substitui a query do doc 11 §7, que não corre como escrita (aliases inexistentes, `UNION` que multiplica linhas, sem filtro de tenant, `LIMIT` sem `ORDER BY`, `plainto_tsquery`, soma de *scores* de escalas incompatíveis) e viola o ADR-007 (`p.stock` no índice).

Três decisões moldam o epic. Primeiro, **fusão por RRF ponderado** em vez de soma linear (PROP-IDX-2): `ts_rank`, cosseno e trigrama não partilham escala e o RRF resiste a trocas de modelo. Segundo, **Piloto sem índice ANN**: com HNSW/IVFFlat o filtro por `tenant_id` é aplicado depois do índice (CONFIRMADO, README do pgvector) e o tenant raro recebe lista vazia sem erro — o modo de falha mais perigoso, porque parece «a loja não tem esse produto»; catálogos de 50–2 000 produtos usam busca exacta com `btree(tenant_id)` (PROP-IDX-1). Terceiro, **modo lexical obrigatório** (PROP-IDX-3): o texto da consulta do cliente enviado a um fornecedor de embeddings no estrangeiro é, por defeito, uma transferência internacional (INDÍCIO, `../docs/tecnica/evidencia/E3` §2; precedente de USD 505 mil, ADR-008); sem destino autorizado (`apd_ref`) o IDX corre só com trigramas e FTS — *fail closed* para o dado, aberto para o serviço.

Concretiza os ADRs **ADR-006**, **ADR-007**, **ADR-008**, **ADR-003** (o IDX recebe `catalog.product_changed` e referencia produtos por `product_ref` opaco, imune ao resultado do spike D3) e **ADR-010** (consultas e pesos sem identificadores). Tudo o que pressupõe o número da plataforma — índice federado, assistente de consumo, «quero comprar», AdsEngine, vitrine SEO — é **Diferido/Clusters** (ADR-011, D2) e **não** faz parte deste epic. É **Fase 1**: os quatro tickets (KAM-061 a KAM-064) entram depois do esqueleto andante, e a qualidade só se mede com o dataset PT-AO do ticket KAM-064; o modelo de embeddings (PROP-IDX-4) e o léxico PT-AO são NÃO VERIFICADOS e têm critério de saída por medição.

---

## 2. Critérios de Saída do Epic

- [ ] `idx.candidatos` corre em CI com os testes T1–T4 de `../docs/tecnica/05` §6.4 e com os de isolamento: tenant A a pesquisar devolve 0 linhas de B; tenant `suspenso` ou em `onboarding` devolve 0 linhas.
- [ ] Nenhuma coluna do schema `idx` se chama ou contém `preco`, `price`, `stock` ou `qtd`; o *lint* de texto de embedding rejeita preço e stock; 0 índices `hnsw`/`ivfflat` em `idx.search_doc` no Piloto.
- [ ] Sem tabela `idx.*` sem política RLS `FORCE` quando tem `tenant_id`; sem contexto de tenant a pesquisa devolve 0 linhas.
- [ ] Latências medidas em tenant de 5 000 documentos: ramo lexical p95 ≤ 80 ms; híbrido (excluindo a chamada de embedding) p95 ≤ 120 ms; recuperação total com *join* vivo p95 ≤ 300 ms.
- [ ] Frescura: produto alterado fica pesquisável p95 ≤ 30 s (máx. 5 min); reindexação de um tenant de 2 000 produtos ≤ 10 min.
- [ ] Embeddings desligados quando o destino não tem `apd_ref`: 0 chamadas ao fornecedor e 100% das consultas respondidas em modo lexical; *timeout* de 1,5 s degrada para lexical.
- [ ] Dataset `golden_search` com ≥ 300 consultas em ≥ 5 catálogos e o *gate* de CI activo; métricas do Piloto (propostas) medidas: success@3 ≥ 0,85, recall@10 ≥ 0,90, nDCG@3 ≥ 0,75, success@3 em *typo*/regionalismo ≥ 0,80, zero-result ≤ 8%, falso-positivo em «não resolvível» ≤ 10%.
- [ ] «Produto citado inexistente» e «preço/stock divergente» = 0 no conjunto adversarial.
- [ ] Decisão escrita sobre o modelo de embeddings (PROP-IDX-4) com a comparação híbrido vs lexical no dataset.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-061 | `idx.candidatos`: pesquisa híbrida por tenant com RRF (exacta, sem ANN) | feature | L | P0 | KAM-042, KAM-043, KAM-051, KAM-028, KAM-006, KAM-007 |
| KAM-062 | Normalização PT-AO: sinónimos, marcas e tolerância a erros | feature | M | P1 | KAM-061 |
| KAM-063 | Embeddings do catálogo e modo lexical quando o destino não está autorizado | feature | M | P1 | KAM-061, KAM-030, ext:KAM-069 |
| KAM-064 | Avaliação de qualidade da pesquisa e dataset | feature | M | P1 | KAM-061, KAM-040, KAM-062, KAM-063 |

---

## KAM-061 — `idx.candidatos`: pesquisa híbrida por tenant com RRF (exacta, sem ANN)

| Campo | Valor |
|---|---|
| Epic | EPIC-06 — Índice e Pesquisa |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-042, KAM-043, KAM-051, KAM-028, KAM-006, KAM-007 |
| Bloqueia | KAM-062, KAM-063, KAM-064 |
| Responsável sugerido | Engenheiro de Dados/Pesquisa |
| Documentos de referência | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§4, §6, §7, §15), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.5, §7), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§5), ADR-003, ADR-006, ADR-007, ADR-015 |

### Contexto
O Piloto precisa de uma pesquisa que o AGR possa chamar numa tool (`search_products`) e que seja correcta, determinística e isolada por tenant. O doc 11 §7 falha em 9 pontos (D1–D9 em `../docs/tecnica/05` §6.1). A versão corrigida é `idx.candidatos` (§6.2): três ramos (`sem`, `tri`, `fts`) com `ORDER BY` antes do `LIMIT`, fusão por RRF com pesos 0,5/0,3/0,2 e `p_rrf_k = 60` (convencional, INDÍCIO, a afinar no dataset), porta de tenant activo por junção a `tenants.estado = 'ativo'` (dupla defesa com `visivel`). Os limiares do `pg_trgm` por omissão e a normalização 32 do `ts_rank` são INDÍCIO (manual não relido): os testes §6.4 fecham a dúvida.

### Objectivo
Criar o schema `idx` (extensões, configuração FTS `idx.kamba_pt`, `idx.search_doc` sem ANN), a função `idx.candidatos`, o consumidor de `catalog.product_changed` e dos eventos de estado do tenant, e a camada de resposta `search_products` com *join* à oferta viva `com.v_oferta_viva`.

### Critérios de Aceitação
- [ ] Os testes T1–T4 de `../docs/tecnica/05` §6.4 correm em CI (a asserção de cada um nunca é removida para passar; só o limiar `pg_trgm.word_similarity_threshold`, proposta 0,45, é afinado pelo dataset).
- [ ] Tenant A a pesquisar «nike» com produtos homónimos em B e S devolve 0 linhas com `tenant_id ≠ A`; tenant `suspenso` ou `onboarding` devolve 0 linhas mesmo com `visivel = true` (porta `tn`).
- [ ] `idx.search_doc` e `idx.termo_canonico` têm RLS `FORCE` por `tenant_id` (entradas globais com `tenant_id` nulo legíveis); sem `SET LOCAL app.tenant_id` a função devolve 0 linhas.
- [ ] *Lint* de schema: 0 colunas em `idx` com `preco|price|stock|qtd` no nome; o *lint* de texto de embedding rejeita dígitos seguidos de `kz|akz|$` e as palavras «stock», «disponível», «preço» (3 casos negativos no teste).
- [ ] `SELECT count(*) FROM pg_indexes WHERE schemaname='idx' AND indexdef ~* '(hnsw|ivfflat)'` devolve 0 no Piloto.
- [ ] Com `p_qvec = NULL` a função mantém a assinatura, devolve `o_rk_sem` nulo e o mesmo ranking lexical; 20 execuções da mesma consulta devolvem a mesma lista ordenada (desempate por `doc_id`).
- [ ] Uma consulta com 3 termos em que 1 não existe devolve ainda os candidatos dos outros 2 (`websearch_to_tsquery` com `or`, defeito D7).
- [ ] A camada de resposta só devolve linhas `publicado` e `stock_disp > 0`, filtra por `max_preco_kz` na oferta viva (nunca no índice) e devolve `[{sku, product_ref, nome, preco_kz, preco_tipo, disponivel, fonte:'registo', lido_em}]`; com < 3 resultados devolve os indisponíveis marcados `disponivel=false`.
- [ ] Um `catalog.product_changed` torna o produto pesquisável em p95 ≤ 30 s; `tenant.suspended` põe `visivel=false` em ≤ 30 s e, se o consumidor atrasar, a porta `tn` já impede a fuga.
- [ ] Em tenant de 5 000 documentos sintéticos: ramo lexical p95 ≤ 80 ms e híbrido (excl. embedding) p95 ≤ 120 ms em 500 execuções; o resultado e o ambiente ficam registados.

### Detalhes Técnicos
- **Componentes:** IDX, TLS, COM, EVT. DDL de `../docs/tecnica/05` §4.1–§4.2 e função de §6.2 sem alterações de semântica; `halfvec(1024)` é provisório até KAM-063 (PROP-IDX-4).
- **Ficheiros:** `migrations/NNNN_idx_schema.sql`, `services/idx/src/{consumer,search_products}.ts`, `services/idx/test/{candidatos,isolamento,lint}.sql`. Chamador: `BEGIN; SET LOCAL pg_trgm.word_similarity_threshold = 0.45; SELECT … ; COMMIT;`.
- **Contrato de saída:** o §6.3 usa `preco_kz` e `preco_tipo ('exato'|'a_partir_de'|'sob_consulta')`; `../docs/tecnica/03` usa `preco_minor` e `preco_modo ('fixo'|…)`. O adaptador converte (`fixo→exato`, `preco_minor/100`) e a divergência fica em Riscos. A vista `com.v_oferta_viva` é contrato de leitura de KAM-051; até lá usa-se uma vista de teste com o mesmo contrato.
- O SQL do doc 05 usa `tenants` sem o prefixo `platform.` e refere `orders_mirror.pagamento_estado`/`reviews`; adaptar ao schema `platform` de `../docs/tecnica/03` §5 (a reputação `rep.v_reputacao` não faz parte do Piloto).
- Métricas desde o código: `idx_query_ms{ramo,modo}`, `idx_results_total`, `idx_mode{hibrido|lexical}`; o *registo* da tool na ToolLayer segue o contrato de KAM-028.
- Sem nenhum índice ANN: a salvaguarda anti-vazio (§7.3) só se escreve quando se introduzir HNSW (limiar: > 200 000 vectores ou p95 do ramo `sem` > 100 ms).

### Testes Requeridos
- SQL (CI, transacção com `ROLLBACK`): T1–T4, isolamento entre 3 tenants, estado do tenant, determinismo, `p_qvec` nulo.
- Lint: colunas proibidas, texto de embedding, ausência de ANN, RLS por catálogo (`pg_class` × `pg_policy`).
- Integração: consumidor de eventos (idempotência, ordem), *join* com a vista viva, filtro de preço.
- Desempenho: 500 execuções em 5 000 documentos; relatório anexado ao PR.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Isolamento de tenant: RLS `FORCE` e casos X-06 na suite cruzada (KAM-066); tenant pequeno obtém resultados mesmo com um tenant grande.
- [ ] Números só de tools: preço e stock só no *join* vivo; nenhum número vem do índice; o contrato inclui `sku` para o validador.
- [ ] Idempotência: o consumidor de eventos é idempotente (`events_consumed`) e testado com duplicados ×10.
- [ ] Privacidade: nenhum identificador de cliente no índice; logs sem texto de consulta.
- [ ] Custo e observabilidade: métricas de latência por ramo e de modo.
- [ ] Migração reversível; dependências fixadas (`pgvector` ≥ 0.8.7); cobertura ≥ 75% (≥ 90% no isolamento).

### Handoff para Claude Code

```text
És o executor do ticket KAM-061 da KAMBÁ. Lê specs/EPIC-06_Indice_Pesquisa.md (bloco KAM-061) e
docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md (§4, §6, §7, §15) e ADR-006/007/008.
Objectivo: schema idx (vector>=0.8.7, pg_trgm, unaccent, config idx.kamba_pt), idx.search_doc SEM índice ANN,
função idx.candidatos (RRF, três ramos com ORDER BY antes do LIMIT, porta de tenant activo), consumidor de
catalog.product_changed e eventos de estado do tenant, e search_products com join à oferta viva.
- tenant_id vem do estado; RLS FORCE; sem SET LOCAL => 0 linhas.
- Preço/stock nunca no índice nem em embeddings; só no join vivo (lint obrigatório).
- Não removas asserções de T1-T4; afina só o limiar pg_trgm com o dataset (KAM-064).
Não expandas escopo: normalização (KAM-062), embeddings (KAM-063), avaliação (KAM-064), índice federado (Clusters).
Testes: SQL de CI, lint, integração, desempenho. PR com o template (§7).
```

---

## KAM-062 — Normalização PT-AO: sinónimos, marcas e tolerância a erros

| Campo | Valor |
|---|---|
| Epic | EPIC-06 — Índice e Pesquisa |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-061 |
| Bloqueia | KAM-064 |
| Responsável sugerido | Engenheiro de Dados/Pesquisa |
| Documentos de referência | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§4.4, §5, §14.4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.3), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§8), ADR-007, ADR-010 |

### Contexto
O cliente angolano diz «geleira» e a loja vende «frigorífico»; escreve «niker» e quer «Nike»; diz «250 mil» e quer um limite. A normalização é determinística (sem LLM), corre no índice e na consulta e extrai as restrições numéricas, que **não** vão ao índice. O léxico do §5.1 é **ilustrativo** e não foi verificado com falantes (NÃO VERIFICADO): só entra em produção depois de validado contra o dataset e revisto por falantes de PT-AO. Marcas, unidades e números são canonizados nos dois lados; sinónimos só na consulta, para que alterar um sinónimo não obrigue a reindexar.

### Objectivo
Implementar `normalizar(texto, tenant_id, origem)` com os 9 passos do §5.1, a tabela `idx.termo_canonico`, o versionamento `norm_versao` com reindexação em segundo plano, a correcção de erros por vocabulário do tenant e o relatório semanal de *tokens* não resolvidos.

### Critérios de Aceitação
- [ ] A função implementa os 9 passos, devolve `{q_norm, q_or, restricoes, tokens_nao_resolvidos, norm_versao}` e é pura: mesma entrada, mesma saída em 100 execuções; sem chamadas de rede nem LLM.
- [ ] Restrições (tabela §5.2 como testes): «até 250 mil», «no máximo 250k», «menos de 250.000 kz» → `max_preco_kz=250000`; «entre 100 e 150 mil» → `min=100000, max=150000`; «250 mil» sem verbo de limite → `alvo_preco_kz=250000` (ordena, não filtra); moeda diferente de AOA → pergunta.
- [ ] Origem `voz`: «duzentos e cinquenta mil» → 250000; os números por extenso só se convertem com `origem='voz'`.
- [ ] Unidades e marcas canónicas aplicam-se ao índice e à consulta; sinónimos só à consulta (`q_or`): alterar um sinónimo incrementa `norm_versao` mas não marca documentos para reindexar; alterar marca/unidade marca-os e o *worker* reindexa-os (tenant de 2 000 produtos em ≤ 10 min).
- [ ] Erro comum e *typo*: auto-correcção só com `similarity ≥ 0,6` **e** ≥ 1 candidato após correcção; caso contrário o *token* vai para `tokens_nao_resolvidos` e o AGR faz uma só pergunta (teste «niker» → «nike» e «xyzq» → não resolvido).
- [ ] O termo do tenant prevalece sobre o global; um termo de B nunca é aplicado a A (RLS na tabela, teste cruzado).
- [ ] Todo o termo novo exige `aprovado_por`; entradas `origem='dataset'` só ficam `activo` depois de passarem o *gate* de KAM-064 (nDCG@3 não cai > 2 pontos).
- [ ] O relatório semanal agrega *tokens* não resolvidos com ≥ 5 sujeitos distintos, sem texto bruto, sem `contact_id` e sem `sujeito_ref`.
- [ ] «Telefone» ambíguo (telemóvel vs telefone fixo) gera pergunta de desambiguação, não correcção silenciosa.
- [ ] Latência da normalização p95 ≤ 20 ms por consulta (proposta, medir).

### Detalhes Técnicos
- **Componentes:** IDX, AGR. Módulos `services/idx/src/normalize/{pipeline,numbers,units,typos}.ts`; DDL de `idx.termo_canonico` em §4.4 (índice único `termo_canonico_uq` com `COALESCE(tenant_id, 0-uuid)`).
- **Vocabulário do tenant:** `ts_stat('SELECT fts FROM idx.search_doc WHERE tenant_id = …')`, em *cache* com TTL e invalidado por `norm_versao`.
- **Léxico inicial:** o do §5.1 é exemplo; o conteúdo real é curado por ops e validado por pelo menos 2 falantes de PT-AO antes de `activo = true` (critério de saída do NÃO VERIFICADO); registar a data e os revisores.
- A normalização é a mesma função para texto e voz transcrita; o STT é de KAM-036. As restrições numéricas aplicam-se na oferta viva, nunca no índice.
- Dados sensíveis (saúde, etc.) na consulta: não persistir o texto; o classificador é do guardrail (KAM-033).

### Testes Requeridos
- Unit: tabela de casos de números/moeda/unidades; pureza da função; precedência tenant > global.
- Integração: versionamento e *worker* de reindexação; vocabulário por tenant.
- Dataset: execução sobre `golden_search` (KAM-064) antes de activar entradas `dataset`.
- Segurança: RLS cruzada em `termo_canonico`; relatório sem PII.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Isolamento de tenant: RLS `FORCE` em `idx.termo_canonico` e caso novo na suite cruzada.
- [ ] Números só de tools: as restrições de preço do cliente filtram a oferta viva; nunca viram texto de índice.
- [ ] Privacidade: relatórios agregados sem texto bruto; logs sem conteúdo de consulta.
- [ ] Eval-gate verde: alterar o dicionário corre o *gate* de KAM-064; SemVer do dicionário atribuída.
- [ ] Migração reversível; léxico validado por falantes e registado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-062 da KAMBÁ. Lê specs/EPIC-06_Indice_Pesquisa.md (bloco KAM-062) e
docs/tecnica/05 (§4.4, §5, §14.4).
Objectivo: normalizar(texto, tenant_id, origem) em 9 passos (NFKC/unaccent, voz->números, restrições de preço,
unidades, marcas, erros comuns, stopwords, sinónimos só na consulta), tabela idx.termo_canonico, norm_versao com
reindexação em segundo plano, auto-correcção só com similarity >= 0.6 e >= 1 candidato.
- Determinístico, sem LLM. Preços ditos pelo cliente são RESTRIÇÕES aplicadas à oferta viva, nunca texto do índice.
- O léxico do doc 05 é ILUSTRATIVO (NÃO VERIFICADO): não o actives sem validação por falantes e pelo gate de KAM-064.
Não expandas escopo: embeddings (KAM-063), avaliação (KAM-064), STT (KAM-036).
Testes: unit (tabelas de casos), integração (versionamento), dataset, RLS. PR com o template (§7).
```

---

## KAM-063 — Embeddings do catálogo e modo lexical quando o destino não está autorizado

| Campo | Valor |
|---|---|
| Epic | EPIC-06 — Índice e Pesquisa |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-061, KAM-030, ext:KAM-069 |
| Bloqueia | KAM-064 |
| Responsável sugerido | Engenheiro de Dados/Pesquisa |
| Documentos de referência | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§6.5, §7.4, §14.3, §17, PROP-IDX-3, PROP-IDX-4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.4, §8.3), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§2), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§3.5), ADR-005, ADR-008 |

### Contexto
O embedding da **consulta** envia texto do cliente (pode conter nome, bairro ou um tema de saúde) a um fornecedor no estrangeiro: transferência por defeito (INDÍCIO; com a pseudonimização a ser confirmada por parecer, N3). O embedding do **catálogo** envia dados comerciais da PME, de menor risco, e o seu texto nunca leva preço, stock nem dados de contacto. A qualidade de embeddings em PT-AO e a escolha do modelo são NÃO VERIFICADAS (`../docs/tecnica/evidencia/E4` §3.5; PROP-IDX-4), tal como o ganho do híbrido sobre o lexical; ambos se decidem por medição, não por suposição.

### Objectivo
Gerar os embeddings do catálogo e da consulta pelo gateway LLM (chave virtual por tenant), aplicar o *gate* de destino por tenant antes de cada chamada, cair em modo lexical (`p_qvec = NULL`) quando o destino não está autorizado, falha ou excede o *timeout*, e produzir a decisão escrita do modelo com a comparação híbrido vs lexical.

### Critérios de Aceitação
- [ ] Com o tenant sem linha `autorizado` no `tenant_destinations` para o fornecedor de embeddings (ou sem `apd_ref`), o fornecedor recebe 0 chamadas (contador do *mock* = 0), a consulta é respondida em modo lexical e `idx_mode{lexical}` incrementa; com destino autorizado há 1 chamada.
- [ ] Revogar o destino passa as consultas seguintes a lexical em ≤ 60 s (TTL máximo da *cache* do *gate*, proposta).
- [ ] O embedding da consulta tem *timeout* de 1,5 s; ao exceder, degrada para lexical sem erro ao cliente; p95 da chamada ≤ 600 ms medido em staging.
- [ ] Texto de consulta que o detector classifica como sensível (saúde, etc.) ou com identificador directo não vai ao fornecedor: a consulta corre em lexical e o texto não é persistido.
- [ ] O texto que gera o embedding do catálogo passa o *lint* (sem preço, stock, telefone, contacto da PME); mudar o preço de um produto **não** dispara reembedding; mudar nome, marca, categoria ou descrição dispara.
- [ ] `embedding_modelo` é gravado por linha; trocar de modelo escreve numa coluna nova e comuta atomicamente; nunca coexistem 2 modelos na mesma coluna (teste de migração).
- [ ] Reindexar os embeddings de um tenant de 2 000 produtos ≤ 10 min, com *retry* e DLQ para falhas; o custo por tenant aparece no `llm_call_log`.
- [ ] Documento de decisão do modelo (PROP-IDX-4): ≥ 2 candidatos (fornecedor externo e, se viável, *self-host* em Luanda) medidos em nDCG@3 e success@3 na divisão `dev`, com híbrido vs lexical; regra proposta: o embedding só se justifica se melhorar o nDCG@3 em ≥ 2 pontos (calibrar), caso contrário o Piloto fica em lexical.
- [ ] Dados reais não são embebidos enquanto não houver `apd_ref` e KAM-105 fechado (dados sintéticos até lá).

### Detalhes Técnicos
- **Componentes:** IDX, LLM, AGR. Módulos `services/idx/src/embed/{catalog,query,gate,fallback}.ts`; o *gate* lê `tenant_destinations` (KAM-069); chamadas só via LiteLLM com chave virtual do tenant (KAM-030).
- **Dimensão:** a coluna é `halfvec(1024)` por defeito; a dimensão real é a do modelo escolhido; `halfvec` indexa até 4 000 e `vector` até 2 000, sem índice ANN no Piloto (KAM-061).
- **Falha fechada:** qualquer erro do *gate* (linha ausente, base indisponível) equivale a destino negado.
- O ramo `sem` já é opcional na função (`p_qvec = NULL`); não se altera a função. Modo registado em `assistant_queries.modo` (`hibrido`/`lexical`).
- A minimização antes do LLM (`../docs/tecnica/08` §7.4) é do AGR; aqui chama-se o detector através de uma interface e documenta-se a dependência (ver problemas do backlog).
- Reduzir a fronteira: modelo *self-host* em Luanda (D1) ou aceitar lexical; a decisão é uma saída do ticket, não um pressuposto.

### Testes Requeridos
- Unit: *gate* (autorizado, negado, revogado, erro), *timeout*, TTL da *cache*.
- Integração: embedding do catálogo com `FakeEmbeddingProvider`; troca de modelo e comutação atómica.
- Contrato: nenhum pedido ao fornecedor sem passar pelo *gate* (teste de arquitectura que falha se o cliente de embeddings for importado fora do módulo).
- Avaliação: execução do dataset (KAM-064) em híbrido e lexical, relatório anexado.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Privacidade (ADR-008): nenhum dado pessoal sai de Angola sem destino registado com `apd_ref`; 0 chamadas sem *gate*.
- [ ] Números só de tools: nenhum preço, stock ou data em embeddings (lint + teste).
- [ ] Custo e observabilidade: custo por tenant em `llm_call_log`; métricas `idx_mode`, `embedding_latency_ms`, `embedding_fallback_total`.
- [ ] Sem segredos: chaves virtuais; nenhuma chave de fornecedor no módulo.
- [ ] Eval-gate verde na troca de modelo; SemVer da coluna e do modelo; migração reversível.

### Handoff para Claude Code

```text
És o executor do ticket KAM-063 da KAMBÁ. Lê specs/EPIC-06_Indice_Pesquisa.md (bloco KAM-063),
docs/tecnica/05 (§6.5, §7.4, §14.3, PROP-IDX-3/4) e docs/tecnica/08 (§7.4, §8.3).
Objectivo: embeddings do catálogo e da consulta via gateway LiteLLM (chave virtual por tenant), gate de destino por
tenant antes de CADA chamada, modo lexical (p_qvec NULL) quando o destino não tem apd_ref, falha ou excede 1,5 s,
e decisão escrita do modelo com comparação híbrido vs lexical no dataset.
- Sem destino autorizado: 0 chamadas ao fornecedor. Erro do gate = negado (fail closed).
- Preço/stock nunca no texto de embedding. Dados reais só com apd_ref e KAM-105 fechado.
- O ganho do híbrido e a qualidade em PT-AO são NÃO VERIFICADOS: mede-os, não os assumas.
Não expandas escopo: função idx.candidatos (KAM-061), gate em si (KAM-069), HNSW (Clusters).
Testes: unit do gate, integração, arquitectura (cliente só via gate), avaliação. PR com o template (§7).
```

---

## KAM-064 — Avaliação de qualidade da pesquisa e dataset

| Campo | Valor |
|---|---|
| Epic | EPIC-06 — Índice e Pesquisa |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-061, KAM-040, KAM-062, KAM-063 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Dados/Pesquisa |
| Documentos de referência | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§14, §15), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4, termos de ML), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-018, §9), `../docs/tecnica/08_Seguranca_Conformidade.md` (§8.7) |

### Contexto
Sem dataset não há como saber se o dicionário, os pesos do RRF, o limiar do `pg_trgm` ou o modelo de embeddings melhoraram ou pioraram a pesquisa. O dataset `golden_search` serve **só para avaliação e curadoria de dicionário**: os Termos da Meta proíbem treinar ou melhorar ML com dados do WhatsApp (ADR-018; leitura automática, texto EN a verificar). Por isso as conversas reais do concierge/H7 entram **pseudonimizadas e reescritas sinteticamente**, com consentimento específico para avaliação. Todos os alvos são propostas a calibrar no Piloto.

### Objectivo
Construir o dataset `golden_search` (≥ 300 consultas, ≥ 5 catálogos), o executor de avaliação com as métricas de §14.2, o *gate* de CI de §14.3 que compara híbrido e lexical, e a linha de base versionada.

### Critérios de Aceitação
- [ ] O dataset tem ≥ 300 consultas em ≥ 5 catálogos sintéticos, ≥ 20% com *typo*/regionalismo, ≥ 10% «não resolvível» (devem devolver vazio) e ≥ 15% em origem `voz` com erros de STT simulados; o formato JSONL segue §14.1 e há um ficheiro por *snapshot* de catálogo.
- [ ] Anotação por 2 pessoas com graus 0–3; Cohen's κ ≥ 0,7 (cálculo anexado); discordâncias resolvidas por ops e registadas.
- [ ] Divisão `dev` 70% / `teste` 30% fixa por *hash* do `qid`; o executor de afinação falha se ler a divisão `teste` (teste automatizado).
- [ ] Nenhuma consulta de origem real entra no repositório sem passar por reescrita sintética e remoção de identificadores; um *scanner* procura telefone, NIF e nomes (0 ocorrências) e o ficheiro lista o consentimento específico usado.
- [ ] O executor calcula success@3, recall@10, nDCG@3, success@3 em *typo*/regionalismo, zero-result rate e falso-positivo em «não resolvível», por catálogo e global, em modos híbrido e lexical, e produz um relatório JSON e Markdown.
- [ ] O *gate* de CI falha se nDCG@3 cai > 2 pontos, se zero-result sobe > 1 ponto ou se algum teste de isolamento/§6.4/§7.3 falha; corre em alterações de dicionário, pesos, modelo, limiar `pg_trgm` e versão de `idx.candidatos`.
- [ ] A linha de base inicial (`baseline.json`, SemVer) é registada no primeiro *run* verde; as métricas medidas comparam-se aos alvos do Piloto de §14.2 e os desvios ficam explicados em vez de se alterarem os alvos em silêncio.
- [ ] «Produto citado inexistente» e «preço/stock divergente» são verificados no conjunto adversarial com 0 ocorrências (asserção determinística).
- [ ] O relatório completo de uma execução em CI demora ≤ 5 min (proposta).

### Detalhes Técnicos
- **Componentes:** IDX, OBS, AGR. Módulos `eval/search/{dataset,runner,metrics,gate}.py`; dados em `eval/search/data/golden_search/*.jsonl`; relatório em `eval/search/reports/`.
- **Formato:** `{qid, tenant, origem, texto, tags, restricoes, relevantes:[{product_ref, grau}], nao_resolvivel}`.
- **Métricas** (definições em §14.2): success@3 (≥ 1 relevante de grau ≥ 2 nos 3 primeiros), recall@10, nDCG@3 com graus 0–3, zero-result e falso-positivo.
- **Origem dos dados:** (1) conversas do concierge/H7, só depois da reescrita sintética e com consentimento (a confirmar por parecer, E3); (2) sintéticas por ops para a cauda; enquanto o concierge não gerar volume (KAM-109), o dataset arranca 100% sintético e regista-se.
- Reaproveita a infra de *eval harness* de KAM-040 (golden PT-AO de conversas): são datasets diferentes com o mesmo executor de CI.
- O dicionário e os pesos do RRF só se alteram por PR com o relatório do *gate* anexado.

### Testes Requeridos
- Unit: cada métrica com casos de valor conhecido (incluindo empates e consultas sem relevantes).
- Integração: execução ponta a ponta híbrido e lexical sobre a base de teste; falha provocada do *gate* (regressão artificial de nDCG).
- Conformidade: *scanner* de PII sobre o dataset; teste de não-consulta da divisão `teste`.
- Qualidade: relatório de κ.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Eval-gate: o *gate* está activo no CI e bloqueia a promoção de artefactos de pesquisa; SemVer da linha de base atribuída.
- [ ] Privacidade: o dataset não contém dados pessoais; nenhum uso para treinar ou afinar modelos (ADR-018).
- [ ] Números só de tools: asserções de `sku`, preço e stock vêm da oferta viva.
- [ ] Custo e observabilidade: tempo e custo da execução registados; métricas publicadas no painel de OBS.
- [ ] Alvos do Piloto registados como propostas, com plano de recalibração após o Piloto.

### Handoff para Claude Code

```text
És o executor do ticket KAM-064 da KAMBÁ. Lê specs/EPIC-06_Indice_Pesquisa.md (bloco KAM-064),
docs/tecnica/05 (§14, §15) e ADR-018 (golden por reescrita sintética; não treinar com dados da Meta).
Objectivo: dataset golden_search (>= 300 consultas, >= 5 catálogos, >= 20% typo/regionalismo, >= 10% não resolvível),
executor com success@3, recall@10, nDCG@3, zero-result e falso-positivo em híbrido e lexical, gate de CI
(nDCG@3 -2 pts, zero-result +1 pt, ou teste de isolamento falhado => build vermelho) e baseline versionada.
- Divisão dev/teste fixa; a afinação nunca lê 'teste'. Sem PII, sem conversas reais cruas.
- Os alvos (0,85/0,90/0,75/...) são PROPOSTAS; regista desvios, não os escondas.
Não expandas escopo: normalização (KAM-062), embeddings (KAM-063), dataset de conversas do AGR (KAM-040).
Testes: unit das métricas, integração do executor e do gate, scanner de PII. PR com o template (§7).
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| Risco / item | Estado | Impacto | Mitigação ou critério de saída | Decisão |
|---|---|---|---|---|
| Resultado vazio silencioso por filtro pós-índice (ANN) | CONFIRMADO (README do pgvector) | O assistente diz «não temos» quando temos | Piloto sem ANN; teste `count ≥ n_esperado` quando HNSW existir; limiar > 200 000 vectores ou p95 > 100 ms | ADR-006 |
| Consulta enviada a embeddings no estrangeiro sem procedimento APD | INDÍCIO (transferência por defeito); precedente de USD 505 mil | Multa e paragem | Modo lexical *fail closed* por tenant; modelo *self-host* em Luanda como opção; dados sintéticos até KAM-105 | D1, D9 |
| Qualidade de embeddings PT-AO e escolha do modelo; limites de escala do pgvector | NÃO VERIFICADO (`../docs/tecnica/evidencia/E4` §3.5, §2.9) | Custo/transferência sem ganho | Decisão por dataset (KAM-063/064); limiares de HNSW a medir | PROP-IDX-4 |
| `pg_trgm` (limiar por omissão, `<%`), normalização 32 do `ts_rank`, `websearch_to_tsquery` | INDÍCIO (manual não relido) | Testes T1/T4 instáveis | Testes executáveis em CI; afinar o limiar no dataset, nunca remover asserções | — |
| Léxico PT-AO (sinónimos, marcas, erros) não verificado com falantes | NÃO VERIFICADO | Correcções erradas | Validação por ≥ 2 falantes e pelo *gate* antes de `activo = true` | — |
| Termos da Meta sobre ML: aplicação ao dicionário e à avaliação | CONFIRMADO com ressalva de leitura automática (`../docs/tecnica/evidencia/E1`) | Violação de termos | Dataset só de avaliação, reescrita sintética; ler o texto EN integral | ADR-018 |
| Contratos divergentes entre docs: `preco_kz`/`preco_tipo` (05) vs `preco_minor`/`preco_modo` (03); `tenants`/`reviews`/`pagamento_estado` sem schema em 05 | Inconsistência documental | Integração com o COM falha | Adaptador no KAM-061; corrigir `../docs/tecnica/05` e `../docs/tecnica/03` | D3 |
| `com.v_oferta_viva` depende do spike do Medusa e de KAM-051 | Depende do spike | *Join* vivo sem contrato estável | Vista de teste com o mesmo contrato até KAM-051; `product_ref` opaco | D3 |
| Metas de qualidade (0,85/0,90/0,75/...) e de latência | Propostas | Calibração errada | Recalibrar após o Piloto com tráfego real | — |
| Índice federado, assistente de consumo, «quero comprar», patrocínio e vitrine SEO | Diferido (ADR-011) | Fora do âmbito | Não implementar; só costuras (`visivel_federado = false`) | D2 |

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
| 1.0 | Outubro 2026 | Emissão inicial: 4 tickets (KAM-061 a KAM-064) — pesquisa híbrida por tenant com RRF, normalização PT-AO, embeddings com modo lexical e avaliação de qualidade. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-129: as 4 referências aos anexos E1, E3 e E4 passam a `../docs/tecnica/evidencia/…`; antes não resolviam de posição nenhuma. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-145: os **5** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
