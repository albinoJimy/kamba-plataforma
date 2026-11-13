# EPIC-06 — Índice e Pesquisa

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Índice e Pesquisa |
| Versão | 1.6 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/03_Core_Comercio_Medusa.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md`, `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-04_Core_Comercio.md` |

---

## 1. Visão do Epic

O **IDX** responde à pergunta «o que é que *esta loja* vende que corresponda ao que o cliente escreveu ou disse». No Piloto é um índice **por tenant**, em Postgres 18 com `pgvector` ≥ 0.8.7, `pg_trgm` e FTS em português, sem serviço de pesquisa externo (ADR-006). A pesquisa é recuperação de candidatos: **nunca é fonte de preço nem de stock**. Essas grandezas só existem no Registo (COM) e entram na resposta por *join* com a oferta viva no momento de responder, sob o validador de citação com verificação por `sku` (ADR-007). O epic substitui a query do doc 11 §7, que não corre como escrita (aliases inexistentes, `UNION` que multiplica linhas, sem filtro de tenant, `LIMIT` sem `ORDER BY`, `plainto_tsquery`, soma de *scores* de escalas incompatíveis) e viola o ADR-007 (`p.stock` no índice).

Três decisões moldam o epic. Primeiro, **fusão por RRF ponderado** em vez de soma linear (PROP-IDX-2): `ts_rank`, cosseno e trigrama não partilham escala e o RRF resiste a trocas de modelo. Segundo, **Piloto sem índice ANN**: com HNSW/IVFFlat o filtro por `tenant_id` é aplicado depois do índice (CONFIRMADO, README do pgvector) e o tenant raro recebe lista vazia sem erro — o modo de falha mais perigoso, porque parece «a loja não tem esse produto»; catálogos de 50–2 000 produtos usam busca exacta com `btree(tenant_id)` (PROP-IDX-1). Terceiro, **modo lexical obrigatório** (PROP-IDX-3): o texto da consulta do cliente enviado a um fornecedor de embeddings no estrangeiro é, por defeito, uma transferência internacional (INDÍCIO, `../docs/tecnica/evidencia/E3` §2; precedente de USD 505 mil, ADR-008); sem destino autorizado (`apd_ref`) o IDX corre só com trigramas e FTS — *fail closed* para o dado, aberto para o serviço.

Concretiza os ADRs **ADR-006**, **ADR-007**, **ADR-008**, **ADR-003** (o IDX recebe `catalog.product_changed` e referencia produtos por `product_ref` opaco, imune ao resultado do spike D3) e **ADR-010** (consultas e pesos sem identificadores). Tudo o que pressupõe o número da plataforma — índice federado, assistente de consumo, «quero comprar», AdsEngine, vitrine SEO — é **Diferido/Clusters** (ADR-011, D2) e **não** faz parte deste epic. É **Fase 1**: os cinco tickets (KAM-061 a KAM-064, e o KAM-193 que o KAM-061 abriu) entram depois do esqueleto andante, e a qualidade só se mede com o dataset PT-AO do ticket KAM-064; o modelo de embeddings (PROP-IDX-4) e o léxico PT-AO são NÃO VERIFICADOS e têm critério de saída por medição.

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
| KAM-193 | IDX: processo do consumidor, métricas servidas e latência no ambiente de referência | feature | M | P1 | KAM-061 |

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
| Bloqueia | KAM-062, KAM-063, KAM-064, KAM-193, KAM-194 |
| Responsável sugerido | Engenheiro de Dados/Pesquisa |
| Documentos de referência | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§4, §6, §7, §15), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.5, §7), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§5), ADR-003, ADR-006, ADR-007, ADR-015 |

### Contexto
O Piloto precisa de uma pesquisa que o AGR possa chamar numa tool (`search_products`) e que seja correcta, determinística e isolada por tenant. O doc 11 §7 falha em 9 pontos (D1–D9 em `../docs/tecnica/05` §6.1). A versão corrigida é `idx.candidatos` (§6.2): três ramos (`sem`, `tri`, `fts`) com `ORDER BY` antes do `LIMIT`, fusão por RRF com pesos 0,5/0,3/0,2 e `p_rrf_k = 60` (convencional, INDÍCIO, a afinar no dataset), porta de tenant activo por junção a `tenants.estado = 'ativo'` (dupla defesa com `visivel`). Os limiares do `pg_trgm` por omissão e a normalização 32 do `ts_rank` são INDÍCIO (manual não relido): os testes §6.4 fecham a dúvida.

### Objectivo
Criar o schema `idx` (extensões, configuração FTS `idx.kamba_pt`, `idx.search_doc` sem ANN), a função `idx.candidatos`, o consumidor de `catalog.product_changed` e dos eventos de estado do tenant, e a camada de resposta `search_products` com *join* à oferta viva `com.v_oferta_viva`.

### Critérios de Aceitação
- [x] Os testes T1–T4 de `../docs/tecnica/05` §6.4 correm em CI (a asserção de cada um nunca é removida para passar; só o limiar `pg_trgm.word_similarity_threshold`, proposta 0,45, é afinado pelo dataset).
- [x] Tenant A a pesquisar «nike» com produtos homónimos em B e S devolve 0 linhas com `tenant_id ≠ A`; tenant `suspenso` ou `onboarding` devolve 0 linhas mesmo com `visivel = true` (porta `tn`).
- [x] `idx.search_doc` e `idx.termo_canonico` têm RLS `FORCE` por `tenant_id` (entradas globais com `tenant_id` nulo legíveis); sem `SET LOCAL app.tenant_id` a função devolve 0 linhas.
- [x] *Lint* de schema: 0 colunas em `idx` com `preco|price|stock|qtd` no nome; o *lint* de texto de embedding rejeita dígitos seguidos de `kz|akz|$` e as palavras «stock», «disponível», «preço» (3 casos negativos no teste).
- [x] `SELECT count(*) FROM pg_indexes WHERE schemaname='idx' AND indexdef ~* '(hnsw|ivfflat)'` devolve 0 no Piloto.
- [x] Com `p_qvec = NULL` a função mantém a assinatura, devolve `o_rk_sem` nulo e o mesmo ranking lexical; 20 execuções da mesma consulta devolvem a mesma lista ordenada (desempate por `doc_id`).
- [x] Uma consulta com 3 termos em que 1 não existe devolve ainda os candidatos dos outros 2 (`websearch_to_tsquery` com `or`, defeito D7).
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
- [x] Isolamento de tenant: RLS `FORCE` e casos X-06 na suite cruzada (KAM-066); tenant pequeno obtém resultados mesmo com um tenant grande.
- [x] Números só de tools: preço e stock só no *join* vivo; nenhum número vem do índice; o contrato inclui `sku` para o validador.
- [x] Idempotência: o consumidor de eventos é idempotente (`events_consumed`) e testado com duplicados ×10.
- [x] Privacidade: nenhum identificador de cliente no índice; logs sem texto de consulta.
- [ ] Custo e observabilidade: métricas de latência por ramo e de modo.
- [ ] Migração reversível; dependências fixadas (`pgvector` ≥ 0.8.7); cobertura ≥ 75% (≥ 90% no isolamento).

### Verificação dos Critérios de Aceitação

Medição de **2026-11-10** sobre `baef17ea`, integrada e medida outra vez a **2026-11-12** sobre `9b68d6b5`. A revisão é a **`0045`** (`db/migrations/versions/0045_indice_de_pesquisa.py`). O DDL e a função vivem em `../db/indice.py`, declarado como módulo auxiliar de migração, e os ensaios importam-no dali. O lado Python é `../libs/py-core/src/kamba_core/idx/` (`texto`, `pesquisa`, `consumidor`). Reproduz-se, nesta máquina, com o `.venv` e o Docker, e não com `make` (que aqui não existe):

```bash
python db/gate_bd.py --suite tests_produtos      # T1-T4, isolamento, consumidor, resposta
python db/gate_bd.py --suite tests_isolamento    # gate 6: X-03, X-04, X-05 e o X-06 novo
python db/desempenho_indice.py relatorio.json    # criterio 10, fora do CI
python -c "import sys; sys.path[:0]=['libs/py-core/src','libs/py-core/tests']; import unittest; unittest.main(module=None, argv=['x','test_idx'])"
```

**O DDL do §4.1, §4.2 e §4.4 e a função do §6.2 entram sem alterações de semântica**, com quatro adaptações de forma, cada uma escrita na nota do `db/indice.py`: `tenants` passa a `platform.tenants`; as restrições têm nome; cada ramo desempata pelo `doc_id` **antes** do `LIMIT` (o §6.2 só desempatava depois, e um empate no último lugar era sorteio — é isso que o critério 6 pede); e três formas de instrução (`CREATE FUNCTION` e `CREATE SCHEMA` sem `OR REPLACE` nem `IF NOT EXISTS`, e o `unaccent` criado `WITH SCHEMA public`, que é onde o `idx.f_unaccent` do §4.1 o chama). **O que o §4 não tem e o bloco pede é acréscimo, não adaptação:** a RLS das duas tabelas — a `tenant_iso` intacta e, no léxico, a `termos_globais` só de leitura, pela forma da `destinos_globais` do KAM-069 —, os `GRANT` e os comentários.

**Portões, medidos na árvore integrada com a `publico/main` em `9b68d6b5`** (KAM-087 e KAM-088 fundidos, a `0045` sobre a `0044`). `tests_produtos` → **140** ensaios, OK. *Gate* 6 → 83 ensaios, uma falha só, `test_os_casos_que_precisam_de_node`, que é a falta de `node_modules` nesta máquina (a do KAM-051); passam o X-02 com o `search_catalog` ligado e o X-06. *Gate* 8, suite `tests` → **869** ensaios, com o inventário fechado do `idx`, o dono das tabelas, o ciclo `upgrade → downgrade → upgrade` através da `0045` e a lista de retenção do KAM-071, que pediu as duas tabelas do `idx` no `SEM_DADOS_PESSOAIS` (`test_o_catalogo_esta_todo_mapeado`, vermelho até lá, medido). AGR → 204 ensaios nos módulos tocados, OK; `py-core`, OK. Gate 3b, `lint_backlog`, `lint_refs`, `lint_contagens`, `lint_handoff` e `lint_bloco` (110 medidos, piso 55) conformes. **Mutações:** as 15 de `tests_produtos` correram e as **15** foram apanhadas — e uma delas (o desempate do `fts`) sobreviveu primeiro e matou-se com uma pergunta que só esse ramo responde. As duas de RLS morrem no *gate* 6, cuja linha de base não fica verde nesta máquina pelo Node, e ficam para a corrida nocturna. A receita de cópia passou a levar o `docs/tecnica/05`: sem ele a linha de base da `tests_produtos` era vermelha, já desde o KAM-051.

**Uma medição que mudou quem cria uma extensão.** A `vector` 0.8.7 **não é *trusted*** (`pg_available_extension_versions`, na imagem do *gate*: `trusted = f`), pelo que o `kamba_migrator` não a cria. Quem a cria é quem corre como administrador: o *initdb* do compose (já o fazia) e o `db/bootstrap.py` do *gate* 8 (passa a fazê-lo, com a mesma guarda). A revisão repete o `CREATE EXTENSION IF NOT EXISTS`, e não larga extensões no `downgrade`.

| # | Critério | Estado | O que se mediu, e com que comando |
|---|---|---|---|
| 1 | T1–T4 do §6.4 em CI | satisfeito | Um ensaio por teste, com a asserção do documento e mais uma, **que** produto veio e não só quantos: `test_t1_typo_encontra_o_produto_de_a_e_so_de_a`, `test_t2_nenhum_resultado_de_b_ou_s_ao_pesquisar_em_a` (com o *join* do §6.4, lido pelo administrador), `test_t3_tenant_suspenso_zero_resultados`, `test_t4_sinonimo_so_na_descricao_bate_pela_expansao` (e é o ramo `fts` que bate, não o trigrama). Em `db/tests_produtos/test_indice.py`, que o `make ci-8` corre (`--suite tests_produtos`). O limiar 0,45 é **proposta** (`indice.LIMIAR_DE_PALAVRA`); nenhuma asserção foi removida. `word_similarity('niker','nike air force 1 branco')` mediu **0,667**, e não os ≈ 0,57 calculados à mão no §6.2 |
| 2 | Isolamento entre três tenants; `suspenso` e `onboarding` dão zero | satisfeito | `test_homonimos_em_tres_tenants_nao_atravessam`, `test_t3_…`, `test_tenant_em_onboarding_zero_resultados_com_visivel` — e `test_os_estados_que_nao_sao_ativo_fecham_todos`, porque o domínio tem cinco valores e a prosa nomeia dois (`restrito` e `encerrado` também fecham). As mutações «a porta tn aceita o tenant em qualquer estado» e «a porta tn só fecha o suspenso» estão no `db/mutacoes.py` |
| 3 | RLS `FORCE` nas duas tabelas, globais legíveis, sem contexto zero linhas | satisfeito | `test_as_duas_tabelas_tem_rls_force`; `test_as_entradas_globais_do_lexico_leem_se_e_nao_se_escrevem` (com contexto **e** sem ele); `test_sem_contexto_zero_linhas`. **A ligação, e não só o corpo:** `test_o_parametro_de_outro_tenant_nao_contorna_o_contexto` põe o contexto em A e o `p_tenant` em B, e exige zero linhas, com o controlo em B. O *gate* 6 cobre as duas tabelas pela descoberta (X-03, X-04, X-05) e pelo X-06 novo (`tools/isolamento/baterias/x06_vectores.py`) |
| 4 | *Lint* de esquema e de texto de embedding | satisfeito | Esquema: `test_nenhuma_coluna_do_idx_fala_de_preco_nem_de_stock`, com o controlo de que a mesma expressão encontra o `preco_minor` da oferta. Texto: `kamba_core.idx.texto.exigir_texto_de_embedding`, `test_os_tres_negativos_do_criterio` (dinheiro, «stock», «disponível» e «preço»), mais `test_todas_as_formas_de_dinheiro` e os positivos de `test_o_que_nao_e_dinheiro_passa`. **Sem chamador de produção ainda**: quem gera embeddings é o KAM-063. *Actualizado pelo KAM-063:* tem chamador — o `embeber_catalogo` e a `ConsultaVectorial` de `../libs/py-core/src/kamba_core/idx/embeddings.py` —, e o *lint* passou a recusar também telefone, contacto, moeda por extenso e estrangeira e o stock dito de outra forma |
| 5 | Zero índices `hnsw`/`ivfflat` no `idx` | satisfeito | `test_zero_indices_ann_no_esquema`, a consulta do critério à letra, com o controlo de que os três índices do §4.2 existem. Mutação «um HNSW no embedding» |
| 6 | `p_qvec` nulo, mesmo ranking lexical, 20 execuções iguais com desempate por `doc_id` | satisfeito | `test_qvec_nulo_e_modo_lexical_com_o_mesmo_ranking` (postos `tri` e `fts` iguais com e sem vector); `test_vinte_execucoes_devolvem_a_mesma_lista`; e `test_o_empate_no_limite_decide_se_pelo_doc_id`, sete empatados com `p_k = 3`, que é o caso que o texto do §6.2 deixava ao acaso. Mutações dos dois desempates |
| 7 | Três termos, um inexistente, devolve os outros (D7) | satisfeito | `test_um_termo_inexistente_nao_anula_os_outros`, e é o ramo `fts` que o devolve. Mutação «o ramo fts volta ao `plainto_tsquery`» |
| 8 | Camada de resposta: só `publicado`, `stock_disp > 0`, preço filtrado na oferta viva, contrato de saída, indisponíveis com menos de 3 | parcial | **A metade entregue:** `kamba_core.idx.pesquisa.pesquisar`, a consulta do §6.3 sobre a `platform.v_oferta_viva` do KAM-051, **sem parâmetro de tenant** (lê o `app.tenant_id` da transacção): `test_so_sai_o_publicado` (despublicado depois de indexado e sem evento: é a oferta viva que o tira), `test_o_filtro_de_preco_e_na_oferta_viva_e_nunca_no_indice` (o preço muda sem evento e o filtro vê o de agora), `test_o_contrato_e_o_da_secao_6_3_lido_do_documento` (os oito campos lidos do documento, não copiados), `test_o_tenant_vem_do_contexto_e_nao_de_um_parametro` (o mesmo `sku` e nome em B, com outro preço). **E a tool está ligada**: o `search_catalog` do AGR chama-a (`../services/agr/src/kamba_agr/tls/idx.py`), com o `score` normalizado pelo máximo teórico do RRF e o limiar *proposta* 0,3 que o `__main__` passa ao grafo — `TestLigacaoDoAgr`, que corre o `retrieve` real: a frase típica passa (0,4, só pelo `fts`), e com o limiar do duplo a mesma frase caía (o defeito da escala, fixado); `test_um_numero_da_pergunta_nao_encontra_o_produto_errado` («quero 2 bicicletas» contra «Arroz 2 kg»: os algarismos saem da expansão `or`, pelo passo 3 do §5.1). A ligação da camada ao *backend* `idx` tem ensaio pela `ToolLayer` real (`test_tls.TestOBackendDoIndiceRecebeALigacao`), que fica vermelho com o `idx` fora de `BACKENDS_DA_BASE` — medido. **Um limite dito, e não escondido:** no modo lexical o limiar 0,3 deixa passar todo o candidato do topo, pelo que «não resolvível» é a resposta **vazia** e não uma decisão do limiar; uma pergunta que partilhe um só termo com um produto devolve-o, e o `cart_build` propõe-no (o cliente confirma por botão antes de haver encomenda). Afinar isto é o par do KAM-064. **A metade bloqueada:** o filtro `stock_disp > 0` e o `disponivel=false` dos indisponíveis dependem do nível de stock, que a vista não tem — credores **KAM-045** e **D3**, como no critério 7 do KAM-051. O campo sai `None` («não sei»). E os nomes do critério (`preco_kz`, `preco_tipo 'exato'`) são os que o dicionário substitui: o contrato é o canónico do §6.3, `preco_minor` e `fixo` (emenda 1.68) |
| 9 | Frescura: produto pesquisável em p95 ≤ 30 s; `tenant.suspended` ≤ 30 s; a porta `tn` impede a fuga | parcial | **O efeito e a segunda defesa estão medidos; o processo não existe.** `kamba_core.idx.consumidor` dentro do `consumir` do KAM-006, que lê o estado presente e não o *payload* (a ordem não importa): `test_o_produto_publicado_entra_normalizado_e_visivel`, `test_suspender_e_reactivar_o_tenant`, `test_o_efeito_le_o_estado_presente_e_nao_o_payload`, `test_cada_forma_de_nao_ser_publicavel_fica_invisivel`; e `test_tenant_suspenso_responde_vazio_mesmo_com_o_indice_por_actualizar`, que é a frase «se o consumidor atrasar, a porta `tn` já impede a fuga». **O que falta é quem subscreve a fila e chama o consumidor** (a entrada em `../registry/` e o trabalhador): sem ele, os dois p95 não têm o que medir. Credor **KAM-193**, aberto neste PR — **e o KAM-193 devolveu-a outra vez, ao KAM-194**: o que falta não é do IDX, é a ponte fila → consumidor Python (a casca BullMQ → HTTP, as linhas de `platform.evt_subscricoes` numa revisão de dados e uma forma do `../registry/` para um consumidor que não é vertical), e serve também o AGR. Ver a verificação do KAM-193 |
| 10 | Latência em 5 000 documentos: lexical p95 ≤ 80 ms, híbrido p95 ≤ 120 ms, 500 execuções, resultado e ambiente registados | parcial | **Medido, e a medição não fecha nem reprova o alvo**: correu numa máquina partilhada, com outros *gates* a competir. Credor **KAM-193**, aberto neste PR, que a repete no ambiente de referência e optimiza se ela o pedir. O que se mediu: `python db/desempenho_indice.py` (o instrumento, fora do CI): 3 tenants × 5 000 documentos, 500 execuções por modo como `kamba_app`. No servidor (`EXPLAIN ANALYZE`): lexical p50 **92 ms**, p95 **175 ms**; híbrido p50 **123 ms**, p95 **265 ms**. No cliente: lexical p95 **329 ms**, híbrido p95 **430 ms**. O resultado e o ambiente estão em `../docs/evidencia/KAM-061.md`. **Onde está o tempo:** no ramo `tri`, que o planeador serve pelo índice por tenant e recalcula o `word_similarity` sobre os 5 000 documentos (≈ 100 de 116 ms no plano registado). Um GIN composto `(tenant_id, nome_norm gin_trgm_ops)` com `btree_gin` baixou o p50 de 128 para 83 ms numa experiência, e **não entrou**: é DDL fora do §4.2, e medido numa máquina com três *gates* de outras sessões a correr ao mesmo tempo e um catálogo sintético muito mais denso do que um real (≈ 550 correspondências por pergunta). Fica como hipótese, com o instrumento pronto para a medir. **Repetida pelo KAM-193 a 2026-11-12, na mesma máquina e com mais contenção:** servidor lexical p95 **343 ms**, híbrido **511 ms** — o dobro, com o código igual —, o que mostra que esta máquina não decide o alvo (`../docs/evidencia/KAM-193.md`). A caixa continua parcial, agora com credor **KAM-077**, que traz o ambiente de referência |

| DoD | Estado | Evidência |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | vazia | Os critérios 8, 9 e 10 são parciais, pelas razões acima; o 9 e o 10 têm credor no KAM-193 |
| Isolamento: RLS `FORCE`, casos X-06 na suite cruzada, tenant pequeno ao lado de um grande | satisfeito | RLS `FORCE` nas duas (critério 3); a bateria **X-06** passa a existir (`../tools/isolamento/baterias/x06_vectores.py`): com o contexto de A e um vector a distância zero do de B, o ramo semântico só devolve A, com sonda positiva; o parâmetro de B com o contexto de A dá zero; sem contexto, zero. **Com B `ativo`**: o corredor só activava A, e com B em `onboarding` a porta `tn` fechava as sondas sem a RLS chegar a ser medida (achado 1 da revisão adversarial). E o **X-02** ataca o `search_catalog` pela camada real, com o executor real e argumentos de B, e com sonda positiva (A encontra o seu produto). `test_o_tenant_pequeno_obtem_resultados_ao_lado_de_um_grande`: 300 documentos com o vector exacto da pergunta num tenant, um só no outro, e o pequeno vê o seu no posto 1 |
| Números só de tools; o contrato inclui `sku` | satisfeito | Nenhuma coluna de preço ou stock no `idx` (critério 4); o preço sai da oferta viva no instante da pergunta (critério 8); o `sku` é o primeiro campo do contrato, e o executor do AGR devolve-o sem *facts* novos — o preço do turno continua a vir do `get_price_stock` |
| Idempotência: `events_consumed`, duplicados ×10 | satisfeito | `test_dez_duplicados_escrevem_uma_vez`: dez entregas do mesmo evento, um `aplicado` e nove `duplicado`, uma linha e um só `atualizado_at` |
| Privacidade: nenhum identificador de cliente no índice; logs sem texto de consulta | satisfeito | O inventário fechado do `idx` responde «não» coluna a coluna (`test_o_catalogo_do_idx_e_exactamente_o_inventario`); o `descr_norm` vem do catálogo. Nem o `kamba_core.idx` nem o `tls/idx.py` escrevem registo nenhum, e a mensagem do *lint* de embedding diz a categoria e nunca o excerto (`test_a_mensagem_nao_repete_o_texto`) |
| Custo e observabilidade: métricas de latência por ramo e de modo | vazia | **Não há métricas.** `idx_query_ms{ramo,modo}` por ramo não sai de uma função SQL que corre os três numa consulta, e as outras duas (`idx_results_total`, `idx_mode`) custam o inventário fechado do `obs_lint` e as contagens da `../docs/observabilidade.md`. Credor **KAM-193**, aberto neste PR. **O KAM-193 serviu as três** (`../libs/py-core/src/kamba_core/idx/metricas.py`, na `/metrics` do AGR, no inventário do `obs_lint` e nas contagens), **com o eixo `ramo` num valor só**, `todos`: medir por ramo pede mudar o `idx.candidatos`, que não era dele. A caixa continua vazia por isso, e a decisão está na verificação do KAM-193 |
| Migração reversível; `pgvector` fixado; cobertura | parcial | `downgrade` sem `CASCADE`, que larga tudo menos as extensões, coberto pelo ciclo do *gate* 8 (`test_migracao`); o `pgvector` 0.8.7 é o da imagem fixada por *digest*. A cobertura do `kamba_core.idx` mede-se no estrato `restante` (≥ 75%); **pôr o `pesquisa.py` no estrato `critico` (≥ 90%) é alteração do `../ci/thresholds.yaml`**, que é regra de bloqueio e decisão do fundador — a pergunta está com ele, pelo orquestrador do lote |

**A revisão adversarial**, independente e sem acesso ao raciocínio de quem escreveu, levantou nove achados. Cada um foi verificado contra o código antes de gerar trabalho:

| # | Achado | Estado | O que o fechou |
|---|---|---|---|
| 1 | O X-06 era verde sem medir RLS: o B do corredor nunca estava `ativo`, e a porta `tn` fechava as sondas | CONFIRMADO, corrigido | O corredor activa também o B (`test_casos_cruzados.py`) |
| 2 | A ligação da camada ao *backend* `idx` não tinha ensaio que a matasse; o X-02 tratava o `search_catalog` como declarado | CONFIRMADO, corrigido | `TestOBackendDoIndiceRecebeALigacao` pela `ToolLayer` real (vermelho com a mutação, medido); o X-02 ataca-o como ligado, com sonda positiva, e a semente do documento leva a oferta viva |
| 3 | O limiar 0,3 deixa passar qualquer termo único do `fts`, e um algarismo («quero 2 bicicletas» contra «Arroz 2 kg») encontrava o produto errado | CONFIRMADO no PostgreSQL; algarismos corrigidos, o resto dito | Os algarismos saem da expansão `or` (§5.1, passo 3), com ensaio; o termo único fica como limite escrito e é o par do KAM-064 |
| 4 | As adaptações declaradas divergiam entre o código e esta secção, e faltavam três | CONFIRMADO, corrigido | As quatro, iguais nas duas superfícies, e o acréscimo da RLS separado delas |
| 5 | Duas referências a `db/tests_idx/`, que não existe | CONFIRMADO, corrigido | Apontam para `db/tests_produtos/test_indice.py` |
| 6 | O consumidor não subscreve `tenant.approved` nem `tenant.provisioned` | MORTO | O `tenant.approved` é o gatilho do *provisioning* (dicionário §3.5) e o tenant continua em `onboarding`; a passagem a `ativo` é o `tenant.activated`, que se subscreve |
| 7 | O ensaio do `p_qvec` nulo compara postos que o ramo `sem` não pode mudar | CONFIRMADO, aceite | É a igualdade que o critério pede, e é por construção: está dito no ensaio |
| 8 | O ensaio do desempate matava a mutação só em probabilidade | CONFIRMADO, corrigido | Os `doc_id` entram por ordem decrescente, num tenant só deles |
| 9 | `max_preco_minor` com «²» ou acima do `bigint` rebentava em vez de `VALIDATION_ERROR` | CONFIRMADO, corrigido | Até 18 algarismos ASCII, com os dois casos no ensaio |

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
| Bloqueia | KAM-064, KAM-194 |
| Responsável sugerido | Engenheiro de Dados/Pesquisa |
| Documentos de referência | `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§4.4, §5, §14.4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.3), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§8), ADR-007, ADR-010 |

### Contexto
O cliente angolano diz «geleira» e a loja vende «frigorífico»; escreve «niker» e quer «Nike»; diz «250 mil» e quer um limite. A normalização é determinística (sem LLM), corre no índice e na consulta e extrai as restrições numéricas, que **não** vão ao índice. O léxico do §5.1 é **ilustrativo** e não foi verificado com falantes (NÃO VERIFICADO): só entra em produção depois de validado contra o dataset e revisto por falantes de PT-AO. Marcas, unidades e números são canonizados nos dois lados; sinónimos só na consulta, para que alterar um sinónimo não obrigue a reindexar.

### Objectivo
Implementar `normalizar(texto, tenant_id, origem)` com os 9 passos do §5.1, a tabela `idx.termo_canonico`, o versionamento `norm_versao` com reindexação em segundo plano, a correcção de erros por vocabulário do tenant e o relatório semanal de *tokens* não resolvidos.

### Critérios de Aceitação
- [x] A função implementa os 9 passos, devolve `{q_norm, q_or, restricoes, tokens_nao_resolvidos, norm_versao}` e é pura: mesma entrada, mesma saída em 100 execuções; sem chamadas de rede nem LLM.
- [x] Restrições (tabela §5.2 como testes): «até 250 mil», «no máximo 250k», «menos de 250.000 kz» → `max_preco_kz=250000`; «entre 100 e 150 mil» → `min=100000, max=150000`; «250 mil» sem verbo de limite → `alvo_preco_kz=250000` (ordena, não filtra); moeda diferente de AOA → pergunta.
- [x] Origem `voz`: «duzentos e cinquenta mil» → 250000; os números por extenso só se convertem com `origem='voz'`.
- [ ] Unidades e marcas canónicas aplicam-se ao índice e à consulta; sinónimos só à consulta (`q_or`): alterar um sinónimo incrementa `norm_versao` mas não marca documentos para reindexar; alterar marca/unidade marca-os e o *worker* reindexa-os (tenant de 2 000 produtos em ≤ 10 min).
- [x] Erro comum e *typo*: auto-correcção só com `similarity ≥ 0,6` **e** ≥ 1 candidato após correcção; caso contrário o *token* vai para `tokens_nao_resolvidos` e o AGR faz uma só pergunta (teste «niker» → «nike» e «xyzq» → não resolvido).
- [x] O termo do tenant prevalece sobre o global; um termo de B nunca é aplicado a A (RLS na tabela, teste cruzado).
- [ ] Todo o termo novo exige `aprovado_por`; entradas `origem='dataset'` só ficam `activo` depois de passarem o *gate* de KAM-064 (nDCG@3 não cai > 2 pontos).
- [ ] O relatório semanal agrega *tokens* não resolvidos com ≥ 5 sujeitos distintos, sem texto bruto, sem `contact_id` e sem `sujeito_ref`.
- [x] «Telefone» ambíguo (telemóvel vs telefone fixo) gera pergunta de desambiguação, não correcção silenciosa.
- [x] Latência da normalização p95 ≤ 20 ms por consulta (proposta, medir).

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
- [x] Números só de tools: as restrições de preço do cliente filtram a oferta viva; nunca viram texto de índice.
- [ ] Privacidade: relatórios agregados sem texto bruto; logs sem conteúdo de consulta.
- [ ] Eval-gate verde: alterar o dicionário corre o *gate* de KAM-064; SemVer do dicionário atribuída.
- [ ] Migração reversível; léxico validado por falantes e registado.

### Verificação dos Critérios de Aceitação

Medição de **2026-11-12** sobre `f7e32c84` (a `publico/main` com o KAM-061), com a revisão presa à `0045`, e **medida outra vez a 2026-11-13 na árvore integrada** com a `publico/main` em `32092f45` (o #187 do KAM-089 já fundido). A revisão é a **`0049`** (`db/migrations/versions/0049_normalizacao_pt_ao.py`), sobre a `0048` do KAM-089 (a cadeia do lote: `0046` KAM-050, `0047` KAM-192, `0048` KAM-089). **Na árvore integrada, com a `0049` por cima de tudo:**

- *gate* 8: `tests_produtos` com **164** ensaios OK e `tests_agr` com **252** OK;
- os ensaios de descida `TestDowngradeDa0038` (19), `TestDowngradeDa0042` (no `test_retencao_bd`, 26), `TestDowngradeDa0046` (4), `TestDowngradeDa0047` (na `tests_agr`) e o `TestDowngrade` da `0048` (no `test_revisao_schema`, 29): todos OK. O `downgrade` da `0049` não tem guarda nem recusa, pelo que nenhuma descida que o atravesse pára nele;
- as listas fechadas `test_inventario` (12), `test_auditoria` (28), `test_catalogo` (28) e `test_migracao` (18): OK;
- *gate* 6: 83 ensaios, com uma só falha, a do `TestCasosDeNode`, que precisa de Node e não o tem nesta máquina (a mesma da medição de base);
- AGR com **1670** ensaios e `py-core` com **858**: OK. O DDL vive em `../db/indice.py` (`criar_normalizacao`), pela razão do KAM-061. **Uma adaptação dos Detalhes Técnicos, dita:** os módulos não são `services/idx/src/normalize/*.ts` mas `../libs/py-core/src/kamba_core/idx/` (`normalizacao`, `numeros`, `lexico`), ao lado do índice, da camada de resposta e do consumidor que o KAM-061 já escreveu em Python — uma normalização em TypeScript não tinha quem a chamasse. Reproduz-se nesta máquina com o `.venv` e o Docker:

```bash
python db/gate_bd.py --suite tests_produtos      # gate 8: a versao, a reindexacao, o typo, a RLS, as CHECK
python -c "import sys; sys.path[:0]=['libs/py-core/src','libs/py-core/tests']; import unittest; unittest.main(module=None, argv=['x','test_idx_normalizacao','test_idx'])"
```

**O léxico do §5.1 continua ilustrativo e NÃO VERIFICADO**, e este ticket não o promove: nenhuma linha do `idx.termo_canonico` nasce com ele. O exemplo do §5.1 só existe como *fixture* dos ensaios. Em produção, enquanto não houver léxico curado, a normalização faz os passos que não dependem dele (1, 2, 3 e o *typo* por vocabulário), e os passos 4 a 8 ficam à espera das linhas.

| # | Critério | Estado | O que se mediu, e com que comando |
|---|---|---|---|
| 1 | Os 9 passos, os cinco campos, pura em 100 execuções, sem rede nem LLM | satisfeito | `kamba_core.idx.normalizacao.normalizar(texto, tenant_id, origem, lexico=…, vocabulario=…)`: o léxico e o vocabulário entram por parâmetro, e é isso que a torna pura (`kamba_core.idx.lexico` lê-os da base). `test_devolve_os_cinco_campos`, `test_os_nove_passos_numa_frase`, `test_mesma_entrada_mesma_saida_em_100_execucoes` e `test_o_modulo_nao_importa_rede_nem_llm`, que lê os `import` dos dois módulos e só aceita a biblioteca de base. Devolve ainda as `desambiguacoes` (critério 9) |
| 2 | A tabela do §5.2 como ensaios; moeda estrangeira pergunta | satisfeito | `TestRestricoes`: os três máximos, o «entre», o alvo que não filtra, as cinco formas de AOA e as três de moeda estrangeira. **Os nomes são os do dicionário e do §5.2, e não os do critério:** `max_preco_minor = 25 000 000` (unidade menor, 1 Kz = 100), e não `max_preco_kz = 250000` — a mesma substituição da emenda 1.68 que o KAM-061 já fez. Mais as formas angolanas que a revisão adversarial partiu: «250.000,00», «250 000», «1,5 milhões», «250mil», «até mil kz», «1 milhão de dólares» e o valor acima do `bigint` (`test_as_formas_angolanas_de_escrever_um_valor`). E no PostgreSQL, a filtrar a oferta viva: `TestRestricoesNaOfertaViva` (máximo, mínimo, «entre», e o alvo que não filtra) |
| 3 | «duzentos e cinquenta mil» → 250000, só com `origem='voz'` | satisfeito | `test_duzentos_e_cinquenta_mil` (`valor_por_extenso` = 250 000 e a restrição em unidade menor), `test_so_converte_com_origem_voz`, `test_a_tabela_de_numeros` e `test_os_casos_da_voz_que_a_revisao_partiu`: o «e» só junta uma palavra menor a uma maior («entre cem e duzentos mil» são dois números), e o multiplicador dito fica dito («dois mil e quinhentos» é `2.5 mil`) |
| 4 | Marca e unidade nos dois lados, sinónimo só na consulta; sinónimo sobe a versão sem marcar, marca/unidade marca e o *worker* reindexa 2 000 em ≤ 10 min | parcial | **A metade entregue:** os dois lados (`test_marca_e_unidade_nos_dois_lados`, `test_sinonimo_so_na_consulta`); a versão é a `idx.norm_versao` (`0049`), por gatilho no `termo_canonico` (`TestVersao`: o sinónimo sobe a versão e não a do índice; a marca sobe as duas; desactivar e apagar uma unidade activa também marcam, e uma entrada inactiva não; e a versão só se acrescenta — `test_a_versao_so_se_acrescenta`, nem o dono a reescreve nem a apaga); o *worker* é o `kamba_core.idx.consumidor.reindexar` (`test_sinonimo_nao_reindexa_e_marca_reindexa`, `test_um_invisivel_desactualizado_nao_e_marcado_e_a_volta_acaba`), e os 2 000 documentos medem-se em `test_2000_produtos_em_menos_de_10_minutos`. Medido contra a base: **2 000 documentos em 8,3 s**, por lotes de 200 numa escrita só (a primeira versão, uma instrução por documento, levou 472 s numa máquina carregada). **A metade que falta:** o processo de fundo que chama o `reindexar` em ciclo numa pilha levantada — o mesmo processo Python que liga a fila ao consumidor. Credor **KAM-194** (ponte fila → consumidor Python), cujo bloco nomeia o ciclo do `reindexar` |
| 5 | Auto-correcção só com similaridade ≥ 0,6 **e** ≥ 1 candidato; senão `tokens_nao_resolvidos` e uma só pergunta («niker» → «nike», «xyzq» → não resolvido) | satisfeito | `test_niker_e_nike`, `test_xyzq_nao_se_resolve`, `test_o_limiar_e_0_6_dos_dois_lados` (o limiar escrito no ensaio, com um par em 0,6 e outro em 4/7); a semelhança é a do `pg_trgm`, cruzada com o PostgreSQL (`test_a_semelhanca_e_a_do_pg_trgm`); o «≥ 1 candidato» mede-se na base com a palavra (`test_cada_palavra_do_vocabulario_encontra_um_candidato`) e com a frase corrigida inteira (`test_a_frase_corrigida_inteira_encontra_o_produto`). **Duas leituras, ditas:** o «niker» corrige pela tabela de erros comuns e sem limiar (a semelhança dele com «nike» é 4/7 e o critério pede-o corrigido); e a pergunta da palavra desconhecida só se faz quando nenhum candidato passa o limiar do grafo — com o léxico vazio, «quero comprar arroz» tem duas palavras que nenhuma loja vende, e perguntar por elas trocava todo o pedido típico por uma pergunta (`test_a_palavra_desconhecida_com_candidato_acima_do_limiar_nao_pergunta`). A pergunta é uma só (`test_a_pergunta_da_normalizacao_e_a_unica_mensagem`) |
| 6 | O termo do tenant prevalece; um termo de B nunca se aplica a A (RLS, teste cruzado) | satisfeito | Puro: `TestPrecedencia` (e o `Lexico.de_linhas` descarta outra vez o termo de outro tenant). Na base, como `kamba_app`: `test_o_termo_do_tenant_prevalece_sobre_o_global` e `test_um_termo_de_b_nunca_chega_ao_lexico_de_a`, com o controlo de que o mesmo termo se lê com o contexto de B; e `test_a_marca_de_b_nao_reescreve_o_documento_de_a` |
| 7 | `aprovado_por` obrigatório; `dataset` só `activo` depois do *gate* do KAM-064 | parcial | **A metade entregue:** as duas `CHECK` da `0049` — `termo_canonico_aprovado_ck` (nulo, vazio e só espaços recusados) e `termo_canonico_dataset_inactivo_ck` (`test_sem_aprovado_por_recusa`, `test_dataset_so_entra_inactivo`). **A metade que falta:** o *gate* do KAM-064 não existe, e por isso uma entrada de *dataset* não fica activa nunca — falha fechada. Credor **KAM-064**, que solta a `CHECK` com a medição do nDCG@3 |
| 8 | Relatório semanal de *tokens* não resolvidos, ≥ 5 sujeitos distintos, sem texto bruto, sem `contact_id` nem `sujeito_ref` | parcial | **A metade entregue:** a normalização devolve os `tokens_nao_resolvidos` de cada consulta (critério 5), que é a matéria-prima do relatório, e não os guarda em lado nenhum. **A metade devolvida:** o relatório e o seu armazenamento. Contar «cinco sujeitos distintos» obriga a guardar texto da consulta ligado a um sujeito, e isso pede a mesma decisão de privacidade e de retenção que o dataset do KAM-064 já tem de tomar — e o DoD do KAM-061 diz «logs sem texto de consulta». Credor **KAM-064**, que é a curadoria do dicionário a partir do dataset, e cujo bloco nomeia esta caixa como recebida |
| 9 | «Telefone» ambíguo pergunta, não corrige em silêncio | satisfeito | O canónico leva as alternativas separadas por barra vertical (o índice único do §4.4 deixa um só canónico por termo): `test_telefone_sozinho_pergunta` (nem «telefone» nem «telemóvel» entram no `q_or`), `test_telefone_fixo_ja_respondeu` e `test_celular_nao_e_ambiguo`; no grafo, o `TERMO_AMBIGUO` pergunta mesmo com candidatos acima do limiar |
| 10 | p95 da normalização ≤ 20 ms (proposta, medir) | satisfeito | `TestLatencia.test_p95_abaixo_de_20_ms`: 500 consultas com um léxico de 2 000 termos e um vocabulário de 5 000 palavras. A primeira versão mediu 26,7 ms numa máquina carregada; os termos por tipo passaram a calcular-se uma vez por léxico e não por consulta. É o piso de uma máquina de desenvolvimento; o ambiente de referência é o do KAM-193 |

| DoD | Estado | Evidência |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | vazia | Os critérios 4, 7 e 8 são parciais, pelas razões acima |
| Isolamento: RLS `FORCE` em `idx.termo_canonico` e caso novo na suite cruzada | parcial | A RLS `FORCE` é da `0045` e o X-03 continua a cobri-la (a semente passou a levar o `aprovado_por`). O caso novo de «termo de B aplicado a A» está no *gate* 8 (`test_um_termo_de_b_nunca_chega_ao_lexico_de_a`, como `kamba_app`) e **não** na suite cruzada do *gate* 6, cuja linha de base não fica verde nesta máquina pelo Node |
| Números só de tools: as restrições filtram a oferta viva e nunca viram texto de índice | satisfeito | Critério 2 e `TestRestricoesNaOfertaViva`; nenhum número chega ao `q_or` (`test_as_formas_angolanas_de_escrever_um_valor` verifica-o caso a caso) |
| Privacidade: relatórios agregados sem texto bruto; logs sem conteúdo de consulta | parcial | Nenhum módulo novo escreve registo nem guarda a consulta; o grafo recebe o **código** da pergunta e nunca a palavra (`test_o_codigo_e_do_dominio_do_grafo_e_nunca_a_palavra`). O relatório agregado é do KAM-064 (critério 8) |
| Eval-gate verde e SemVer do dicionário | vazia | Credor **KAM-064**. A versão do léxico é um inteiro monótono (`idx.norm_versao`), e não uma SemVer |
| Migração reversível; léxico validado por falantes e registado | parcial | A `0049` desce sem `CASCADE`, pelo ciclo do *gate* 8 (`TestDowngradeDa0028` passa por ela). O léxico **não** foi validado por falantes: é o estado NÃO VERIFICADO que o bloco manda herdar |

**A revisão adversarial**, independente e sem acesso ao raciocínio de quem escreveu, levantou dezasseis achados. Cada um foi verificado contra o código antes de gerar trabalho:

| # | Achado | Estado | O que o fechou |
|---|---|---|---|
| 1 | «até 1 milhão **de** dólares» virava um tecto em kwanzas | CONFIRMADO, corrigido | A moeda lê-se também depois de «de» (`numeros._moeda_em`) |
| 2 | «250.000,00 kz» e «250 000 kz» davam preço 0 e mandavam o número ao índice | CONFIRMADO, corrigido | O passo 1 guarda o decimal; os grupos de milhares juntam-se antes de multiplicador ou moeda |
| 3 | Na voz, o «e» juntava dois números («entre cem e duzentos mil» = 300 mil) | CONFIRMADO, corrigido | Uma palavra só se junta a uma maior do que ela |
| 4 | «até dois mil e quinhentos» (voz) perdia o tecto | CONFIRMADO, corrigido | O multiplicador dito fica dito, em decimal (`2.5 mil`) |
| 5 | Os decimais davam uma restrição errada, e o comentário dizia o contrário | CONFIRMADO, corrigido | Decimais suportados; o comentário saiu |
| 6 | Com o léxico vazio, `TERMO_DESCONHECIDO` substituía o «não encontrei» em quase tudo, e o executor decidia antes do limiar | CONFIRMADO, corrigido | A decisão passou ao `retrieve`, depois do limiar; o texto não culpa o cliente e mantém o colega |
| 7 | A identidade dá a versão pela ordem de início, e a visibilidade é pela de *commit*: um documento podia ficar desactualizado sem marca | PLAUSÍVEL, corrigido | O gatilho toma `SHARE ROW EXCLUSIVE` na `norm_versao`: quem escreve o léxico serializa |
| 8 | Ensaios que não mordiam: o limiar importado do alvo, o `AND visivel`, o mínimo e o alvo do `SQL_RESPOSTA` | CONFIRMADO, corrigido | `test_o_limiar_e_0_6_dos_dois_lados`, `test_um_invisivel_desactualizado_nao_e_marcado_e_a_volta_acaba` (e a mutação no `db/mutacoes.py`), `TestRestricoesNaOfertaViva` |
| 9 | O «≥ 1 candidato» só estava provado para palavras soltas | PLAUSÍVEL, corrigido | O `or` do `q_or` dá-o para a frase; mede-se com `test_a_frase_corrigida_inteira_encontra_o_produto`, e a fronteira está escrita no módulo |
| 10 | O alvo de preço quase nunca ordena: o `o_score` raramente empata | CONFIRMADO, aceite | Leitura dita: o alvo desempata depois da relevância, e nunca filtra. Pô-lo à frente da relevância punha um produto mal relacionado e com o preço certo antes do pedido; a calibração é do KAM-064 |
| 11 | Um número enorme partia a tool no `bigint` | CONFIRMADO, corrigido | Fica no tecto do `bigint`, que é «sem filtro» |
| 12 | Restrições contraditórias davam resposta vazia | CONFIRMADO, corrigido | Um mínimo acima do máximo cai; fica o tecto |
| 13 | «250mil», «até mil kz» e «até $300» não se reconheciam | CONFIRMADO, corrigido | As três, com ensaio |
| 14 | Qualquer marca reindexava todos os tenants, mesmo inactiva | CONFIRMADO, corrigido em parte | Uma entrada inactiva já não marca (`test_uma_entrada_inactiva_nao_marca_o_indice`). A versão continua global, como o §4.4 a escreve: uma marca de um tenant reescreve os documentos de todos, com o mesmo conteúdo nos outros. É custo e não correcção |
| 15 | O `kamba_app` vê a cadência das alterações do léxico de outros tenants | CONFIRMADO, aceite | Uma linha diz só «algo mudou» e quando, nunca o quê nem de quem |
| 16 | O *cache* crescia sem limite | CONFIRMADO, corrigido | Tecto de 256 tenants (*proposta*) |

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
- [x] Com o tenant sem linha `autorizado` no `tenant_destinations` para o fornecedor de embeddings (ou sem `apd_ref`), o fornecedor recebe 0 chamadas (contador do *mock* = 0), a consulta é respondida em modo lexical e `idx_mode{lexical}` incrementa; com destino autorizado há 1 chamada.
- [x] Revogar o destino passa as consultas seguintes a lexical em ≤ 60 s (TTL máximo da *cache* do *gate*, proposta).
- [ ] O embedding da consulta tem *timeout* de 1,5 s; ao exceder, degrada para lexical sem erro ao cliente; p95 da chamada ≤ 600 ms medido em staging.
- [x] Texto de consulta que o detector classifica como sensível (saúde, etc.) ou com identificador directo não vai ao fornecedor: a consulta corre em lexical e o texto não é persistido.
- [ ] O texto que gera o embedding do catálogo passa o *lint* (sem preço, stock, telefone, contacto da PME); mudar o preço de um produto **não** dispara reembedding; mudar nome, marca, categoria ou descrição dispara.
- [ ] `embedding_modelo` é gravado por linha; trocar de modelo escreve numa coluna nova e comuta atomicamente; nunca coexistem 2 modelos na mesma coluna (teste de migração).
- [ ] Reindexar os embeddings de um tenant de 2 000 produtos ≤ 10 min, com *retry* e DLQ para falhas; o custo por tenant aparece no `llm_call_log`.
- [ ] Documento de decisão do modelo (PROP-IDX-4): ≥ 2 candidatos (fornecedor externo e, se viável, *self-host* em Luanda) medidos em nDCG@3 e success@3 na divisão `dev`, com híbrido vs lexical; regra proposta: o embedding só se justifica se melhorar o nDCG@3 em ≥ 2 pontos (calibrar), caso contrário o Piloto fica em lexical.
- [x] Dados reais não são embebidos enquanto não houver `apd_ref` e KAM-105 fechado (dados sintéticos até lá).

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
- [x] Privacidade (ADR-008): nenhum dado pessoal sai de Angola sem destino registado com `apd_ref`; 0 chamadas sem *gate*.
- [x] Números só de tools: nenhum preço, stock ou data em embeddings (lint + teste).
- [x] Custo e observabilidade: custo por tenant em `llm_call_log`; métricas `idx_mode`, `embedding_latency_ms`, `embedding_fallback_total`.
- [x] Sem segredos: chaves virtuais; nenhuma chave de fornecedor no módulo.
- [ ] Eval-gate verde na troca de modelo; SemVer da coluna e do modelo; migração reversível.

### Verificação dos Critérios de Aceitação

**Quatro caixas de nove nos critérios e quatro de seis no DoD; as outras ficam vazias, cada uma com a razão e o credor.** Ramo `feature/KAM-063-embeddings-catalogo`, base `a6bb0ae0`. **Sem migração e sem DDL**: o vector e o `embedding_modelo` já existiam (KAM-061). O que este ticket entrega: o núcleo `../libs/py-core/src/kamba_core/idx/embeddings.py` — o `ClienteDeEmbeddings`, único sítio que chama um fornecedor, e só depois da porta de destinos do KAM-069 autorizar **todos** os fornecedores do alias; a `ConsultaVectorial`, que dá o vector da pergunta ou cai em lexical; e o `embeber_catalogo`, uma volta do *worker* —, o modo híbrido no `procurar` e no executor do `search_catalog`, o `/embeddings` do gateway (`ClienteDeLlm.embeber`, com a chave virtual do tenant e a linha em `dat.llm_call_log`) e o adaptador do AGR (`../services/agr/src/kamba_agr/tls/embeddings.py`). **O que não entrega, e é decisão e não falta:** o vector **não está ligado em produção** — o `kamba-embed` está `por_decidir` (`../llm/aliases.yaml`) e o arranque do AGR só liga a `ConsultaVectorial` com modelo escolhido; até lá, toda a pesquisa é lexical, como era. Os módulos do bloco eram `services/idx/src/embed/*.ts`; o IDX vive em Python desde o KAM-061 (`kamba_core.idx`), e é lá que isto está.

| # | Critério | Estado | O que se mediu, e com que comando |
|---|---|---|---|
| 1 | Sem destino autorizado: 0 chamadas, lexical e `idx_mode{lexical}`; com destino, 1 chamada | satisfeito | Com a porta **real** do KAM-069 e o fornecedor falso com contador: `TestCriterio1Gate` (`../libs/py-core/tests/test_idx_embeddings.py`) — sem linha, `pendente`, `revogado`, `negado` e `autorizado` sem `apd_ref` dão **0** chamadas e `destino_negado`; autorizado dá **1**; um alias com dois fornecedores e só um autorizado dá **0** (o *fallback* do proxy); erro da base e tenant ilegível negam. **De ponta a ponta contra um PostgreSQL**: `test_o_executor_do_agr_sem_destino_responde_lexical_e_conta` (`../db/tests_produtos/test_indice.py`) — a *tool* do AGR, a porta sobre `platform.tenant_destinations` sem linha, um índice com vectores: **0** chamadas, o produto certo na resposta e `idx_mode{lexical}` = 1. O caso autorizado na pesquisa: `test_a_pesquisa_hibrida_e_o_chao_lexical` (1 chamada, modo `hibrido`) |
| 2 | Revogar passa a lexical em ≤ 60 s | satisfeito | `test_revogar_vale_no_maximo_ao_fim_do_ttl`, com o relógio da porta fixo: a 59 999 ms a decisão guardada ainda vale, a 60 000 ms a consulta cai em lexical sem chamada. O tecto é o TTL da *cache* da porta (KAM-069, *proposta*), que a porta recusa acima de 60 s |
| 3 | *Timeout* de 1,5 s com degradação sem erro; p95 ≤ 600 ms em *staging* | parcial | **O tecto e a degradação, sim:** `TECTO_DA_CONSULTA_S = 1.5`; `test_passar_o_tecto_corta_a_espera_e_cai_em_lexical` (um fornecedor de 2 s e um tecto de 0,2 s: a espera acaba em < 1 s, `tempo_esgotado`, sem excepção); e o tecto cabe no da *tool* — as `read` têm 2 s, e o `procurar` dá ao vector o prazo do tecto menos uma reserva de 500 ms (*proposta*), contado **depois** da porta e da primeira transacção, e desconta o que ele gastou ao `statement_timeout` da pesquisa: `TestPrazo` e `test_o_tempo_do_vector_desconta_se_do_tecto_da_pesquisa`. **O p95 não:** não há modelo escolhido, nem *staging*, nem destino autorizado — zero chamadas reais. Credor **KAM-064**, com o modelo |
| 4 | Texto sensível ou com identificador não vai ao fornecedor; lexical; texto não persistido | satisfeito | O detector entra por interface (`sensivel`), corre **antes** da porta e um detector que levanta conta como sensível: `TestCriterio4Sensivel`. O do AGR junta o `e_sensivel` do KAM-033, os dados de cartão e o detector de PII do KAM-112: `TestSensivel`. E o adaptador recusa um texto cujo mapa de minimização não venha vazio — nem mascarado sai: `test_identificador_directo_nao_sai`. **Não persistido:** nenhum dos módulos escreve registo, e as métricas não têm por onde receber texto (`test_os_embeddings_nao_tem_por_onde_receber_texto`, `test_a_metrica_nao_leva_o_texto`) |
| 5 | *Lint* do texto (preço, stock, telefone, contacto); o preço não reembebe, nome, marca, categoria e descrição sim | parcial | **O *lint*:** o `motivos_de_recusa` do KAM-061 ganhou `telefone` (nove ou mais algarismos num lance, com indicativo e até dois separadores), `contacto` (e-mail, endereço web com ou sem `www.`, `@utilizador`), a moeda por extenso e estrangeira, e o stock dito de outra forma («esgotado», «últimas unidades»), lidos no texto **com** a pontuação: `TestTextoDoCatalogo`. O *lint* lê o nome **cru** da oferta viva e o que sai é a forma normalizada do documento, a mesma do `q_norm` da pergunta: `test_o_lint_le_o_nome_cru_e_nao_o_normalizado`, `test_o_worker_grava_o_vector_e_o_modelo_e_recusa_o_contacto`. Um texto que o fornecedor recusa sozinho conta como recusado e não derruba o lote: `test_um_texto_que_o_fornecedor_recusa_nao_derruba_o_lote`. **O disparo:** o consumidor anula o vector e o modelo quando o texto escrito muda, e só então: `test_o_preco_nao_reembebe_e_o_nome_sim` (PostgreSQL); a escrita confere o texto, e um nome que muda durante a chamada não fica com o vector antigo: `test_a_escrita_nao_grava_o_vector_de_um_nome_que_mudou`. **Porque é parcial:** a categoria e a descrição **não têm escritor** — o `platform.offer_terms` só tem `nome` — e não se pode mudá-las para medir. O que fica é estrutural: `test_cada_coluna_do_texto_escrita_e_comparada` recusa uma instrução que escreva uma coluna do texto sem a comparar. Credor **KAM-049** (o catálogo que traz categoria e descrição) |
| 6 | `embedding_modelo` por linha; trocar de modelo escreve numa coluna nova e comuta atomicamente; nunca 2 modelos na mesma coluna (teste de migração) | parcial | **Por linha e nunca dois, sim, sem DDL:** o *worker* não chama o fornecedor nem escreve num tenant com vectores de outro modelo, e a instrução de escrita recusa-o sozinha: `test_nunca_dois_modelos_na_coluna_do_tenant`; a pesquisa só é híbrida com **um** modelo no tenant e o mesmo na pergunta, relido na transacção da pesquisa: `test_dois_modelos_no_indice_sao_lexical_sem_chamada`, `test_outro_modelo_na_resposta_e_modelo_divergente`. **A coluna nova e a comutação atómica, não:** são DDL, a dimensão real é a do modelo, e este ticket não tinha migração. Hoje trocar de modelo é limpar e reembeber, em lexical entretanto. Credor **KAM-064**, com a escolha do modelo |
| 7 | 2 000 produtos em ≤ 10 min, com *retry* e DLQ; custo por tenant no `llm_call_log` | parcial | **O custo, sim:** o `ClienteDeLlm.embeber` grava a linha com os *tokens* e o custo: `test_o_pedido_e_o_do_esquema_e_vai_com_a_chave_do_tenant` (120 mil *tokens*, **0,0024** USD). **A volta, sim:** `embeber_catalogo` lê um lote pelo cursor do `doc_id`, chama uma vez e grava; uma volta que não grava devolve o motivo e repete-se na seguinte, que é o *retry*. **O tempo e a DLQ, não:** quem corre o ciclo é o processo do **KAM-194**, e o alvo mede-se nele; e um lote que falha sempre falha inteiro — isolar o documento envenenado numa DLQ é do processo. Credor **KAM-194** |
| 8 | Documento de decisão do modelo, ≥ 2 candidatos em nDCG@3 e success@3 na `dev`, híbrido contra lexical | vazio | Não há dataset (o `golden_search` é o KAM-064, que depende deste), nem modelo nenhum que se possa chamar sem LLM pago. Nada foi medido. Credor **KAM-064**, onde o critério está escrito nos Detalhes Técnicos |
| 9 | Dados reais não são embebidos sem `apd_ref` e KAM-105 fechado | satisfeito | A porta exige `autorizado` **com** `apd_ref` para cada fornecedor, e nega o resto: o caso `autorizado` sem `apd_ref` do critério 1, e `test_sem_destino_na_base_zero_chamadas` contra o `platform.tenant_destinations` real — o *worker* não chama, não grava, e o documento fica lexical |

| DoD | Estado | Evidência |
|---|---|---|
| Critérios satisfeitos e demonstráveis | vazia | Cinco critérios são parciais ou vazios, com os credores acima |
| Privacidade: nada sai sem destino com `apd_ref`; 0 chamadas sem *gate* | satisfeito | O critério 1 e o ensaio de arquitectura do bloco, `../services/agr/tests/test_embeddings_arquitectura.py`: quatro regras sobre a fonte — o gateway de embeddings só no adaptador, o adaptador só como argumento do `ClienteDeEmbeddings`, o fornecedor nunca antes do `self.autorizar`, e o `/embeddings` só no cliente HTTP —, cada uma com canário |
| Números só de *tools*: nenhum preço, stock ou data em embeddings | satisfeito | O *lint* do critério 5 e `test_o_preco_nao_esta_na_instrucao`; o documento não tem coluna de preço (KAM-061, `test_nenhuma_coluna_do_idx_fala_de_preco_nem_de_stock`) |
| Custo e observabilidade | satisfeito | O custo do critério 7. As métricas: `idx_mode` (KAM-193) e as duas novas, `embedding_latency_ms{uso}` e `embedding_fallback_total{motivo}`, no `kamba_core.idx.metricas`, servidas pela `/metrics` do AGR e declaradas em `../ops/metricas/catalogo.yaml` (`test_o_catalogo_declara_os_mesmos_dominios`); `obs_lint` com **0 achados**, `contar_metricas` → 26 módulos, 142 nomes |
| Sem segredos | satisfeito | A chave é a virtual do tenant, lida do cofre a cada chamada (`chave_virtual` do `__main__`); nenhum módulo deste ticket tem chave nem nome de variável de chave; `scan_secrets` limpo nos dois *commits* |
| *Eval-gate* verde na troca de modelo; SemVer; migração reversível | vazia | Não há *eval-gate* de pesquisa nem troca de modelo, e não houve migração. Credor **KAM-064** |

**Portões, medidos nesta árvore** (base `a6bb0ae0`), com o Python do `.venv` do *worktree* e o `PYTHONPATH` em caminhos Windows, **depois** das correcções da revisão: `libs/py-core` → **907** ensaios, OK (93 nos três módulos do IDX); AGR → **1697**, OK — na primeira corrida, de 1696, houve **um** vermelho meu (a política AST do KAM-112 recusa `dataclasses.replace` em todo o AGR), corrigido; `obs_lint` → **96**, OK, e o *lint* com 0 achados; `llm_config` conforme; *gate* 8, o `tests_produtos.test_indice` contra o PostgreSQL da receita do `gate_bd` → **52 de 52**, com os **11** do `TestEmbeddings` (a primeira corrida teve um vermelho do próprio ensaio: o `lido_em` é o instante da leitura). *Gate* 3b (os três comandos) conforme; `lint_backlog` (197), `lint_refs`, `lint_handoff`, `lint_contagens`, `lint_bloco` (117 emparelhados, piso 58), `log_policy` (0 achados) e `lint_arch all` conformes, depois da última edição. **O que não correu aqui:** as vinte suites de `tools/` do *gate* 4, o *gate* 6 e o resto do *gate* 8; ficam com o CI deste PR.

**A revisão adversarial**, independente e sem acesso ao raciocínio de quem escreveu, levantou doze achados e correu **52 mutações** sobre as ligações decisivas: **45 mortas e 7 sobreviventes**. Cada achado verificou-se contra a árvore antes de gerar trabalho; as sobreviventes que escondiam risco ganharam ensaio.

| # | Achado | Estado | O que o fechou |
|---|---|---|---|
| 1 | Um só texto que o detector de PII recusa (um nome de produto lido como morada, «Pão de Luanda») deixava o lote inteiro em `falha`, e para sempre: o *retry* recusava-o outra vez | CONFIRMADO, corrigido | O *worker* pergunta ao fornecedor **texto a texto** (`ClienteDeEmbeddings.aceita`, `FornecedorDoGateway.aceita`) e o recusado conta em `recusados`: `test_um_texto_que_o_fornecedor_recusa_nao_derruba_o_lote`. **O custo, dito:** esses nomes ficam só lexicais — mascarar troca a palavra por `MORADA_1`, e mandar o cru passava ao lado do KAM-112 |
| 2 | O *lint* deixava passar a moeda por extenso e estrangeira, o stock dito de outra forma, telefones com dois espaços ou barras, e domínios sem `www.` e `@utilizador` | CONFIRMADO, corrigido | Os quatro padrões alargados e os casos em `TestTextoDoCatalogo`; os nomes de produto do ensaio de positivos continuam a passar. Fica dito no módulo o que ainda escapa: um domínio fora da lista |
| 3 | A pergunta e o documento iam embebidos em formas diferentes, e o comentário dizia o contrário | CONFIRMADO, corrigido | Os dois lados enviam a forma normalizada do KAM-062: o `q_norm` da pergunta e o `nome_norm`, `marca_canon`, `categoria_canon`, `descr_norm` do documento; o *lint* continua a ler o nome cru. `test_o_lint_le_o_nome_cru_e_nao_o_normalizado`, `test_um_modelo_e_hibrido_com_o_q_norm` |
| 4 | O vector pedia-se antes da normalização: uma pergunta que normalizada fica vazia («até 5000 kz») saía para fora sem uso | CONFIRMADO, corrigido | O `procurar` normaliza na transacção curta do modelo e só pede o vector com `q_norm`: `test_pergunta_que_normalizada_fica_vazia_nao_sai` |
| 5 | O tempo da porta e da primeira transacção não contava para o tecto do vector, e podia deixar a pesquisa com 1 ms de `statement_timeout` | PLAUSÍVEL, corrigido | O `procurar` passa um **prazo** (tecto da pesquisa menos a reserva), e o cliente calcula o tecto do vector **depois** da porta: `TestPrazo`, `test_o_tempo_do_vector_desconta_se_do_tecto_da_pesquisa`. A latência da porta em falha de *cache* no ambiente de referência continua por medir |
| 6 | O `_validar` aceitava um vector nulo (`NaN` no `<=>`) e componentes acima de 65 504 (não cabem em `halfvec`) | PLAUSÍVEL, corrigido | Recusados os dois, em `test_cada_resposta_invalida_e_recusada` |
| 7 | A guarda de «um modelo por coluna» tem corrida entre dois *workers* em `READ COMMITTED` | PLAUSÍVEL, escrito | A nota do SQL de escrita deixou de dizer «na mesma instrução» e diz o limite: dois *workers* com modelos diferentes ao mesmo tempo gravam os dois, e a pesquisa apanha a mistura e cai em lexical — falha fechada. Um *worker* por tenant é do KAM-194 |
| 8 | Caixas devolvidas sem credor, e o canon desactualizado | CONFIRMADO, corrigido | A revisão leu o `23508466`; a secção de verificação, o «Recebido do KAM-063» no KAM-064, a emenda 1.88 do dicionário e o credor do `kamba-embed` entraram no `52b70f1f` e no `ee93f0d1`. A célula 4 da verificação do KAM-061 diz agora que há chamador. O KAM-194 **não** fala de embeddings: o credor do critério 7 fica escrito aqui e na nota de integração do lote |
| 9 | O `dataclasses.replace` avermelhava a política do KAM-112 | CONFIRMADO, já corrigido | `com_tecto`, no `52b70f1f`; e o corte do tecto passou depois para o `procurar` (achado 5) |
| 10 | O caminho híbrido do `procurar` não tinha ensaio unitário; o `visivel` do *worker* e a troca de vectores entre documentos sobreviviam | CONFIRMADO, corrigido | `TestProcurarHibrido` (a segunda leitura do modelo e o desconto do tecto, mutações M22 e M23), `test_cada_vector_vai_para_o_seu_documento` (M52), `test_o_invisivel_nao_vai_ao_fornecedor` contra o PostgreSQL (M42) |
| 11 | O ensaio de arquitectura só via a ordem das linhas: a porta dentro de um `try` que a engole passava | CONFIRMADO, corrigido | Regra nova sobre o `try`, com canário (`test_porta_engolida_por_um_try`). Os ensaios de comportamento já matavam a mutação |
| 12 | O vector anula-se pelo `nome_norm`, pelo que uma mudança do léxico que o mexa paga o reembedding do tenant | PLAUSÍVEL, escrito | É o lado seguro: o texto que sai **é** o normalizado, e mudou. Fica dito aqui; o custo mede-se com o modelo (KAM-064) |

As sobreviventes que ficam: M17 e M35 (o tenant no SQL de escrita e no dos modelos) são mascaradas pela RLS, que é a barreira; M51 (o `visivel` na leitura dos modelos) é inofensiva.

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
- **O limiar do `retrieve` do AGR também se afina aqui** (KAM-061): o `LIMIAR_DO_RRF` de `../services/agr/src/kamba_agr/tls/idx.py`, contra o RRF normalizado pelo seu máximo teórico (`score_normalizado`), entrou como *proposta* (0,3) quando o KAM-061 ligou o `search_catalog`, e muda junto com o pontuador, com o mesmo relatório.
- **Recebido do KAM-062**, que o devolveu na sua verificação: o critério 8 daquele bloco (o relatório semanal de *tokens* não resolvidos, ≥ 5 sujeitos distintos, sem texto bruto, sem `contact_id` nem `sujeito_ref`) e a metade do critério 7 que solta a `termo_canonico_dataset_inactivo_ck` quando o *gate* deste ticket passar. O relatório guarda texto da consulta ligado a um sujeito, e pede a mesma decisão de privacidade e de retenção que este ticket já toma para o dataset; o KAM-062 deixa a normalização a devolver os `tokens_nao_resolvidos` e não os guarda.
- **Recebido do KAM-063**, que entregou o caminho dos embeddings e devolveu, na sua verificação, o que só se decide com o modelo escolhido: o critério 8 daquele bloco (o documento de decisão do modelo, PROP-IDX-4, com ≥ 2 candidatos medidos em nDCG@3 e success@3 na divisão `dev`, híbrido contra lexical, e a regra proposta dos 2 pontos); a metade do critério 6 que é DDL — a coluna nova e a comutação atómica numa troca de modelo, com o seu teste de migração, porque a dimensão real é a do modelo; o p95 ≤ 600 ms do critério 3, que se mede com o modelo escolhido num ambiente com destino autorizado; e a caixa «*eval-gate* verde na troca de modelo». Até lá o `kamba-embed` fica `por_decidir` com credor neste ticket (`../llm/aliases.yaml`) e o AGR não liga o vector: a pesquisa é lexical. O executor deste ticket corre o modo híbrido pelo `kamba_core.idx.pesquisa.procurar` com uma `ConsultaVectorial` (`../libs/py-core/src/kamba_core/idx/embeddings.py`).

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

## KAM-193 — IDX: processo do consumidor, métricas servidas e latência no ambiente de referência

| Campo | Valor |
|---|---|
| Epic | EPIC-06 — Índice e Pesquisa |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-061 |
| Bloqueia | KAM-194 |
| Responsável sugerido | Engenheiro de Dados/Pesquisa, com o dono da observabilidade |
| Documentos de referência | `EPIC-06_Indice_Pesquisa.md` (bloco KAM-061 e a sua verificação), `../docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md` (§4.3, §6.2, §15), `../docs/evidencia/KAM-061.md`, `../docs/observabilidade.md` |

### Contexto

O KAM-061 entregou o índice, a função, o consumidor e a camada de resposta, e devolveu três caixas
que nenhum ticket do backlog recebia. Este ticket é o credor delas, e nasce **no mesmo PR** que as
devolve: uma caixa devolvida «sem ticket» morre na fusão, porque ninguém fica a dever. Os motivos e
as medições de cada uma estão na verificação do bloco KAM-061 e no anexo `../docs/evidencia/KAM-061.md`,
e não se repetem aqui.

### Objectivo

Pôr o consumidor do índice a correr como processo, servir as métricas do IDX, e medir a latência do
critério 10 do KAM-061 no ambiente de referência — optimizando só se a medição o pedir.

### Critérios de Aceitação

- [ ] Critério 9 do KAM-061: um processo subscreve `catalog.product_changed` e os quatro eventos de estado do tenant na fila e chama o `kamba_core.idx.consumidor.consumir_evento`, com a subscrição declarada em `../registry/`; um produto alterado fica pesquisável em p95 ≤ 30 s e um `tenant.suspended` põe `visivel=false` em ≤ 30 s, medidos numa pilha levantada.
- [ ] DoD «métricas» do KAM-061: `idx_query_ms{ramo,modo}`, `idx_results_total` e `idx_mode{hibrido|lexical}` servidas, no inventário do `obs_lint` e nas contagens da `../docs/observabilidade.md`; sem identificadores nem texto de consulta nas etiquetas.
- [ ] Critério 10 do KAM-061: o p95 do ramo lexical (alvo ≤ 80 ms) e do híbrido sem o embedding da pergunta (alvo ≤ 120 ms), em 500 execuções sobre um tenant de 5 000 documentos, medidos com o `../db/desempenho_indice.py` **no ambiente de referência** e não numa máquina partilhada; se ficarem acima, a optimização entra por revisão nova com a medição antes e depois (a hipótese do GIN composto está no anexo do KAM-061).

### Detalhes Técnicos

- **Componentes:** IDX (consumidor e função), EVT (subscrição), OBS (métricas).
- **O consumidor já existe e lê o estado presente**, pelo que o processo não precisa de ordem (`exige_ordem = False`); o que falta é quem o chama.
- **Por ramo, `idx_query_ms` não sai de uma função SQL** que corre os três ramos numa consulta: medir por ramo pede instrumentação própria, e a escolha fica escrita.
- O ambiente de referência é o do fundador; a medição regista-se como a do KAM-061, com o ambiente ao lado.

### Testes Requeridos

- Integração: o processo consome um `catalog.product_changed` e um `tenant.suspended` numa pilha levantada, com o p95 medido.
- Observabilidade: o `obs_lint` vê as três métricas, e o X-11 nenhum texto de consulta.
- Desempenho: o relatório do `db/desempenho_indice.py` no ambiente de referência, anexado.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos, e a verificação do KAM-061 actualizada a apontar para este ticket nas caixas que fecha.
- [x] Métricas novas no inventário do `obs_lint`; nenhum texto de consulta em logs.
- [x] Documentação actualizada; migração (se houver) reversível.

### Verificação dos Critérios de Aceitação

**Nenhuma das três caixas dos critérios fecha, e cada uma tem a razão e o credor escritos.** Ramo `feature/KAM-193-idx-consumidor-metricas`, base `f7e32c84`. O que este ticket entrega: o módulo `../libs/py-core/src/kamba_core/idx/metricas.py`, ligado ao executor do `search_catalog` (`../services/agr/src/kamba_agr/tls/idx.py`) e servido na `/metrics` do AGR; a repetição da medição do critério 10 do KAM-061 nesta máquina (`../docs/evidencia/KAM-193.md`); e **o KAM-194**, aberto neste PR (`tickets/KAM-194.md`), para que a caixa (a) não fique devolvida sem ninguém a dever.

| # | Critério | Estado | O que se mediu, e com que comando |
|---|---|---|---|
| 1 | Processo que subscreve a fila e chama o `consumir_evento`, com a subscrição em `../registry/`; p95 ≤ 30 s numa pilha levantada | parcial | **O efeito existe e está medido desde o KAM-061; a ponte entre a fila e ele não existe, e não é do IDX.** Medido na `publico/main` em `f7e32c84`: (1) não há casca BullMQ → HTTP para eventos — o único consumidor das partições `evt.<consumer>.p<0..15>` é o `../services/worker-canal/src/consumidor.ts`, que marca o `events_consumed` **em TypeScript**, pelo que um consumidor Python atrás dele via sempre `duplicado`; a casca do `/internal/event` do AGR tinha como credores o KAM-005 e o KAM-006, que estão fechados; (2) em `platform.evt_subscricoes` só escreve o dono (a `0004` dá `SELECT` ao `kamba_batch` e nada ao `kamba_app`), pelo que as linhas do `idx` são uma **migração de dados**; (3) o `../registry/` tem três formas fechadas no *gate* 3b (`../tools/canon_lint/registo.py`), e nenhuma serve a um consumidor que não é vertical. Fazer as três aqui passava o ticket a L e prendia-o à cadeia do alembic, e a escolha foi do orquestrador do lote. Credor **KAM-194**, que recebe também as duas dívidas do AGR sem dono (a casca e as linhas de subscrição dele); a verificação do KAM-038 no EPIC-03 e o `../docs/agr.md` §7-H passam a apontar para ele. **O dicionário §3.33 ainda os dá ao KAM-005 e ao KAM-006**, e não se emendou aqui: é uma superfície partilhada do lote, e o KAM-194 já a vai emendar pela forma nova do registo — está escrito nos Detalhes Técnicos dele |
| 2 | `idx_query_ms{ramo,modo}`, `idx_results_total` e `idx_mode{hibrido\|lexical}` servidas, no inventário do `obs_lint` e nas contagens da `../docs/observabilidade.md`; sem identificadores nem texto de consulta nas etiquetas | parcial | **As três servidas, e o eixo `ramo` com um valor só.** O registo é o `kamba_core.idx.metricas` (dois domínios fechados: `modo` em {`hibrido`, `lexical`}, `ramo` em {`todos`}); o executor do `search_catalog` escreve-o depois de uma pesquisa que respondeu, e a `/metrics` do AGR serve-o ao lado do registo dele: `test_a_rota_serve_tambem_as_metricas_do_idx`. A ligação, e não só a função: `TestMetricasDoExecutor` (as três séries saem de uma chamada real do executor; uma pesquisa que falhou ou um filtro recusado não escrevem; a pergunta e o tenant não aparecem no texto servido). O registo **não tem por onde receber texto** — a assinatura só aceita modo, ramo, duração e número, e um ensaio prende-a. Inventário: `tools/obs_lint/tests/test_contar_metricas.py`, com o módulo na lista; `contar_metricas` → **25 módulos, 136 nomes**, levados ao §1 e ao §2.1 da `observabilidade.md` (138 declaradas) e à nota do KAM-080 no `EPIC-08`; catálogo com os dois domínios por extenso, confrontado com o código (`test_o_catalogo_declara_os_mesmos_dominios`), e o `obs_lint` com **0 achados**. **Porque é parcial:** o critério pede latência **por ramo**, e o `idx.candidatos` corre os três ramos numa instrução SQL — do cliente só se vê a duração dela. Separar os ramos é mudar a função, que a fronteira com o KAM-062 deixa fora deste ticket; a escolha está escrita no módulo e a decisão (mudar a função, ou aceitar `todos` e ler o tempo por ramo do `EXPLAIN` do instrumento) fica com o orquestrador do lote. Um *gauge* com o último valor, como os do AGR: **não dá o p95** (ADR-018) |
| 3 | p95 lexical ≤ 80 ms e híbrido ≤ 120 ms em 500 execuções sobre 5 000 documentos, medidos com o `../db/desempenho_indice.py` **no ambiente de referência** | parcial | **Medido, e a medição não conta, como o bloco avisa.** O ambiente de referência é o alojamento, que é o **KAM-077**, aberto. Correu o instrumento sem alteração nesta máquina, a 2026-11-12: servidor lexical p95 **343 ms** e híbrido **511 ms**, cliente lexical **1 338 ms** e híbrido **2 114 ms**, com dois máximos do cliente acima de **460 s** (o processo parado à espera de CPU), 62 minutos de corrida e pelo menos quatro *gates* 8 de outras sessões ao lado. O KAM-061 tinha medido 175 e 265 ms no servidor com o mesmo código: **o dobro entre dois dias, com a função igual**, que é a prova de que esta máquina não decide o alvo. Resultado e ambiente em `../docs/evidencia/KAM-193.md`. Não se optimizou: a hipótese do GIN composto mede-se no ambiente de referência, onde a diferença que ela faz não fica dentro do ruído. Credor **KAM-077** |

| DoD | Estado | Evidência |
|---|---|---|
| Critérios satisfeitos, e a verificação do KAM-061 actualizada | vazia | Os três critérios são parciais. A verificação do KAM-061 está actualizada: as linhas 9 e 10 e a caixa das métricas apontam para os credores de agora (KAM-194, KAM-077 e a decisão do eixo `ramo`) |
| Métricas novas no inventário do `obs_lint`; nenhum texto de consulta em logs | satisfeito | O inventário: o ensaio do conjunto `MODULOS`, verde com o módulo novo. Logs: nem o `kamba_core.idx` nem o `tls/idx.py` escrevem registo nenhum (procurado: zero chamadas ao *logger* nos dois), e este ticket não acrescenta nenhuma. O X-11 do *gate* 6 não corre nesta máquina, pela falta de `node_modules` (a do KAM-051); corre no CI deste PR |
| Documentação actualizada; migração (se houver) reversível | satisfeito | Sem migração. Documentação: `../docs/observabilidade.md` (§1, §2.1 e versão 1.10), `../ops/metricas/catalogo.yaml`, a nota do KAM-080 no `EPIC-08`, as docstrings do `kamba_core.idx`, e o anexo de evidência |

**Portões, medidos nesta árvore** (base `f7e32c84`), com o Python de um *worktree* irmão e o `PYTHONPATH` em caminhos Windows: AGR → **1660** ensaios, OK; `libs/py-core` → **809**, OK; `obs_lint` → **96**, OK, e o *lint* com **0 achados** sobre 36 métricas no catálogo; `contar_metricas` → 25 módulos, 136 nomes. *Gate* 3b (os três comandos: `dict_export --check`, `canon_lint check` e o canário) conforme. `lint_backlog` (194 nas três superfícies), `lint_refs` (KAM-001 a KAM-194), `lint_handoff`, `lint_contagens` e `lint_bloco` (111 emparelhados, piso 55, 0 achados) conformes, depois da última edição. **O que não correu aqui:** as vinte suites de `tools/` do *gate* 4 não acabaram nesta máquina (a do `canon_lint` levou 3,7 h com outras sessões a competir; correram `backup_lint`, `canon_lint` e `obs_lint`, verdes), nem o *gate* 6 com o X-11, pela falta de `node_modules`. Os dois ficam com o CI deste PR. Sem migração.

**A revisão adversarial**, independente e sem acesso ao raciocínio de quem escreveu, levantou dez achados. Cada um verificou-se contra a árvore antes de gerar trabalho:

| # | Achado | Estado | O que o fechou |
|---|---|---|---|
| 1 | `test_a_rota_serve_tambem_as_metricas_do_idx` dependia da ordem: os ensaios que chamam o `search_catalog` sujavam o registo global, e o `ordem-dos-ensaios` do *gate* 4 corre a pasta ao contrário | CONFIRMADO, corrigido | Reproduzido (`test_idx.TestExecutor` antes dele dava `idx_results_total 4`). Repõe o registo **antes**, compara linhas inteiras e não substrings, e o `TestExecutor` limpa o que escreve |
| 2 | A duração não estava presa: `>= 0` deixava passar um executor que escrevesse 0 ou segundos | CONFIRMADO, corrigido | O relógio é fixo no ensaio e a série tem de dar **250,0** ms |
| 3 | `modo="hibrido"` nunca é escrito pelo executor de hoje | CONFIRMADO, mantido e escrito | É o valor que o critério nomeia e o KAM-063 produz; a diferença para o `ramo` está na nota do módulo |
| 4 | O comentário dizia que a falta conta no `agr_tool_erros_total`, que soma as tools todas, e um tecto da camada pode ser contado como resposta | CONFIRMADO, corrigido | O comentário diz agora os dois limites, e o `idx_mode` não promete denominador de falha |
| 5 | `idx_mode` é *counter* sem `_total` | CONFIRMADO, escrito | O nome é o do bloco; a escolha está na nota do módulo |
| 6 | Faltava a aresta KAM-193 → KAM-194 | CONFIRMADO, corrigido | O KAM-194 depende também do KAM-193 (serve o registo dele), nas três superfícies, e o `Bloqueia` do KAM-193 ganha-o |
| 7 | A linha 1.60 do `INDICE` punha no §1 a linha dos ficheiros do EPIC-01, que está no §2 | CONFIRMADO, corrigido | — |
| 8 | A caixa «nenhum texto de consulta em logs» assenta numa procura e não no X-11 | PLAUSÍVEL | A caixa diz o que a sustenta: zero chamadas ao *logger* nos dois módulos, e o X-11 do *gate* 6 que corre no CI deste PR |
| 9 | O anexo afirmava mais do que os números: sem o relatório, uma inferência dada como facto, e «sobre a máquina e não sobre o índice» | CONFIRMADO, corrigido | O relatório está anexado (`../docs/evidencia/KAM-193.json`); a paragem por CPU passa a INDÍCIO; e o anexo diz que as duas corridas ficam acima do alvo |
| 10 | As linhas de versão do `docs/agr.md` e do EPIC-03 atribuíam a emenda ao KAM-194, que não é entregue aqui | CONFIRMADO, corrigido | Atribuídas ao KAM-193 |

### Handoff para Claude Code

```text
És o executor do ticket KAM-193 da KAMBÁ (caixas devolvidas pelo KAM-061).
Lê specs/EPIC-06_Indice_Pesquisa.md (blocos KAM-193 e KAM-061, com a verificação deste) e
docs/evidencia/KAM-061.md.
Objectivo: o processo que chama o consumidor do idx, as três métricas do IDX servidas, e a medição do
critério 10 do KAM-061 no ambiente de referência.
Regras: o tenant vem do envelope (consumidor) e do contexto (pesquisa); nada de texto de consulta em
etiquetas nem em logs; uma optimização só entra com medição antes e depois.
Testes: integração na pilha levantada, obs_lint e o relatório de desempenho.
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
| 1.3 | Novembro 2026 | KAM-061: secção de verificação do bloco, com **sete** caixas de dez nos critérios e **quatro** de sete na DoD; as vazias têm a razão e o credor. E uma linha nos Detalhes Técnicos do KAM-064: o limiar do `retrieve` do AGR afina-se com o *dataset* dele, junto com o pontuador. **Entra o KAM-193**, credor das três caixas que o KAM-061 devolveu sem ticket (o processo do consumidor, as métricas servidas e a latência no ambiente de referência): o critério 10 passa de «não satisfeito» a parcial, porque uma medição numa máquina partilhada não fecha nem reprova o alvo. | Equipa KAMBÁ |
| 1.4 | Novembro 2026 | KAM-193: secção de verificação do bloco, com **nenhuma** das três caixas dos critérios fechada e **duas** de três na DoD. Entrega o módulo `kamba_core.idx.metricas` com as três métricas servidas pela `/metrics` do AGR (o eixo `ramo` só com `todos`, e a razão escrita), e a repetição da medição do critério 10 do KAM-061 nesta máquina, que deu o dobro com o código igual (`../docs/evidencia/KAM-193.md`). **Abre o KAM-194** no EPIC-01, credor do processo do consumidor, e o `Bloqueia` do KAM-061, do KAM-062 e do KAM-193 ganham-no. A verificação do KAM-061 passa a apontar para os novos credores nas linhas 9 e 10 e na caixa das métricas. | Equipa KAMBÁ |
| 1.5 | Novembro 2026 | KAM-062: secção de verificação do bloco, com **sete** caixas de dez nos critérios e **uma** de seis na DoD; as parciais e a vazia têm a razão e o credor (KAM-064 recebe o relatório semanal e a soltura das entradas de *dataset*, e fica-lhe uma linha nos Detalhes Técnicos; KAM-194 recebe o ciclo do *worker*). O léxico do §5.1 continua NÃO VERIFICADO. | Equipa KAMBÁ |
| 1.6 | Novembro 2026 | KAM-063: secção de verificação do bloco, com **quatro** caixas de nove nos critérios (1, 2, 4 e 9) e **quatro** de seis no DoD, sem migração. Ficam parciais o 3 (o p95 em *staging*, KAM-064), o 5 (categoria e descrição sem escritor, KAM-049), o 6 (a coluna nova e a comutação atómica, que são DDL, KAM-064) e o 7 (o tempo e a DLQ do ciclo, KAM-194), e vazio o 8 (a decisão do modelo, KAM-064). O bloco do KAM-064 ganha nos Detalhes Técnicos o que recebe deste. | Equipa KAMBÁ |
