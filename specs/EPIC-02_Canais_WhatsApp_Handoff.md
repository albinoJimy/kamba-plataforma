# EPIC-02 — Canais WhatsApp e Handoff

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Canais WhatsApp e Handoff |
| Versão | 1.14 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/10_Onboarding_Governanca.md` (§6–§7), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` |
| Documentos relacionados | `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-01_Fundacoes_Dados.md`, `specs/EPIC-03_Agent_Runtime_Verticais.md`, `specs/EPIC-09_Onboarding_Governanca.md`, `specs/EPIC-10_Spikes_Validacao_Gates.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/tecnica/evidencia/E4_Stack_Licencas.md` |

---

## 1. Visão do Epic

Este epic constrói o **canal**: tudo o que está entre a Meta e o Agent Runtime, em ambos os sentidos. Entrada: o GWY como único endpoint de webhook (assinatura sobre o corpo bruto, deduplicação, 200 rápido, fila) e o CHR que transforma `phone_number_id` em tenant, canal e contacto. Saída: o *outbound* que respeita a janela de 24 h, os templates *utility*, o limite de débito e o custo por mensagem. Onboarding do número: Embedded Signup v4 como Tech Provider, coexistência com a app WhatsApp Business do dono (histórico, *echoes*, `PARTNER_REMOVED`, sincronização em 24 h) e o protocolo que decide **quem tem a palavra** em cada conversa (bot, dono, humano, pausada). Depois, o HND com Chatwoot (1 conta por PME, espelho por *inbox* de tipo API), a mídia, a vigilância da qualidade e do *free tier*, o consentimento no 1.º contacto e o simulador de webhooks que torna tudo isto testável sem a Meta.

O epic concretiza **ADR-001** (Cloud API oficial, Tech Provider, Embedded Signup v4, GWY único endpoint, Chatwoot como espelho), **ADR-010** (consentimento no 1.º contacto, BSUID, telefone nunca como chave), **ADR-011** (só o Fluxo A em produção: o CHR recusa `origem='plataforma'` e `vertical='assistente'`), **ADR-002** (Chatwoot MIT; Typebot e n8n fora das superfícies de tenants), **ADR-014** (mídia por `StorageProvider`) e **ADR-009** (eventos de canal pelo outbox). Aplica a política da Meta lida em E1 (Messaging Policy: caminho de escalonamento a humano em todas as conversas; opt-out; sem personificação) e trata como incógnitas medidas, não assumidas, a coexistência para números +244 (H3), o *echo* de mensagens enviadas por API e o comportamento do bot do Chatwoot.

Fase mista, por desenho: **Fase 0** para o que o esqueleto andante exige (KAM-013, 014, 015, 019, 024: uma mensagem entra, é resolvida, responde-se na janela, o handoff existe) e **Fase 1** para o que depende de Tech Provider, de números reais ou de decisões externas (KAM-016, 017, 018, 020–023). Os tickets de Fase 1 dependem de `ext:KAM-102` (Business Verification, App Review, Tech Provider) e `ext:KAM-100` (spike de coexistência), que arrancam na semana 1.

---

## 2. Critérios de Saída do Epic

Auditados em 2026-10-23, com todos os tickets do epic fundidos menos o KAM-115,
sobre `publico/main` (`3278307`, KAM-017). **O KAM-115 entregou-se depois desta
auditoria** e está verificado no bloco dele: sete critérios de oito, e o vazio é
o alvo de ≥ 95% dos *tenants* `ativo` com contacto verificado, que é medição
sobre *tenants* reais. As contagens desta secção são as do instante em que ela
foi escrita e não se reescrevem aqui — quem as quiser actualizadas lê o bloco. **Uma caixa marcada é uma afirmação,
e nenhuma se marcou sem o teste que a prova nomeado ao lado** — ficheiro e nome
do teste, para que se possa ir lá. Onde a caixa fica vazia, a razão e de quem
depende estão escritas: uma lista de caixas vazias sem razão é um mapa e não um
critério.

**Um critério com duas metades fica vazio quando uma não se cumpre**, e isso não
é o mesmo que não ter trabalho feito — é a regra que o KAM-023 já aplicou aos
seus próprios critérios. A metade que está medida fica dita na mesma, senão a
caixa vazia leria-se como «nada disto existe», que é falso.

**E as caixas dos blocos de ticket foram conferidas, todas.** À letra desta
mesma regra, e não só as do §2: cada caixa de critério e de *DoD* dos tickets
fundidos foi comparada com o veredito que a tabela de verificação do seu bloco
lhe dá. Quatro — KAM-016, KAM-017, KAM-021 e KAM-022 — tinham as caixas todas
vazias com as verificações a dar a maioria dos critérios como satisfeitos, e
ficaram alinhados (emenda 1.11); os restantes **já concordavam, caixa a
caixa**, e não se tocou em nenhum. Conferiu-se também o inverso, que é o que
faz de uma caixa uma afirmação prendida por máquina em vez de escrita: **todos**
os nomes declarados nas listas `GRUPOS` e `TESTES_OBRIGATORIOS` das suites de
`db/tests_*/` existem hoje nos ficheiros de teste — quatro deles com uma
constante interpolada no nome, e não como texto literal.

- [x] Reenviar o mesmo webhook 2× produz 1 *job*; a mesma mensagem em dois envelopes distintos produz 1 `inbound_events`; assinatura inválida devolve 401; o GWY responde 200 com p99 < 500 ms a 3× de tráfego de estados (alvo de `../docs/tecnica/01` §16).
  - **Evidência — as quatro partes, contra o GWY a correr.** `db/tests_entrada/test_entrada.py`: `TestFila::test_o_mesmo_corpo_duas_vezes_produz_um_job` (o `jobId` **é** o `sha256` do corpo, comparado com o resumo calculado em Python), `TestRegistoEQuarentena::test_a_mesma_mensagem_em_dois_corpos_distintos_da_uma_linha` (dois *jobs* e **uma** linha, pela `UNIQUE (kind, event_key)` — os dois níveis de deduplicação são distintos e o critério pede os dois) e `TestAssinatura::test_assinatura_invalida_responde_401`, com `test_o_corpo_reserializado_com_a_assinatura_do_original_da_401` ao lado, que é o que distingue a assinatura sobre os bytes recebidos da assinatura sobre o `JSON.stringify`.
  - **O p99 mede-se, e não se assume.** `db/tests_entrada_carga/test_carga.py::TestCarga::test_o_perfil_do_criterio_7` emite 50 corpos de mensagem e 150 de estado por segundo — o `3×` de estados do `E1` §5 — durante 60 s, com o ritmo imposto por instante-alvo e não à velocidade do anfitrião, e **falha** se o p99 não ficar abaixo dos 500 ms. Medido: p99 **199 ms**, mediana 39 ms, 12 000 respostas e todas 200, 3 000 de 3 000 mensagens registadas. A latência é a vista pelo cliente, do primeiro byte enviado ao último recebido.
  - A caixa do critério 7 do bloco KAM-013 fica vazia pela **regra do descarte sob saturação**, que é outra afirmação e que este critério de saída não pede.

- [x] 0 mensagens enviadas com janela fechada (`WINDOW_CLOSED`) e 0 respostas do bot depois de um *echo* do dono em 100 intercalações aleatórias de corrida (KAM-015, KAM-018).
  - **Reconfirmada.** A janela: `packages/core-ts/tests/outbound.decisao.test.ts`, grupo «janela fechada: WINDOW_CLOSED sem chamada (criterio 1)», e `packages/core-ts/tests/outbound.adapter.test.ts`, «a janela fechada da WINDOW_CLOSED sem chamada (criterio 1)» — que afirma **zero** chamadas HTTP à Meta e não apenas o motivo devolvido, porque um `WINDOW_CLOSED` depois da chamada já gastou o envio.
  - As intercalações: `packages/core-ts/tests_bd/modos.bd.test.ts`, «as 100 intercalacoes: 0 mensagens depois de o echo estar registado», com a corrida da letra ao lado («turno em t0, echo em t0+1s, resposta em t0+2s: 0 enviadas e 1 suprimida») e com «as 100 intercalacoes sao reproduziveis: a mesma semente da a mesma sequencia» — sem esta, uma semente degenerada dava 100 intercalações iguais e o teste passava sem provar nada. Os nomes estão prendidos pelos `TESTES_OBRIGATORIOS` de `db/tests_modos/test_modos.py`, que falha se um deles desaparecer da saída.

- [ ] Um onboarding Embedded Signup v4 completo numa conta de teste da Meta, com evidência em `docs/evidencia/KAM-016.md`; a coexistência está validada com ≥ 1 número +244 real **ou** o modo `cloud_only` está documentado como predefinido, conforme o relatório de KAM-100 (KAM-016, KAM-017).
  - **Vazia, e as duas saídas do «ou» estão fechadas por terceiros.** O onboarding real depende de `ext:KAM-102` (Business Verification, App Review, Tech Provider) e não existe `docs/evidencia/KAM-016.md`; a coexistência com um +244 depende de `ext:KAM-100` e não existe `docs/evidencia/KAM-100.md`. A alternativa — `cloud_only` **como predefinido** — também não se cumpre, porque é precisamente o que o KAM-017 deixou por decidir à espera do mesmo relatório (bloco KAM-017, critério 10 e DoD). O que **está** entregue é a lógica dos dois modos, inteira e testada; o que falta é um valor por omissão que ninguém aqui pode escolher. Depende de `ext:KAM-102` e de `ext:KAM-100`.

- [x] A sincronização de coexistência alerta aos 12 h e marca `falhado` às 24 h; `history` nunca gera resposta do bot (KAM-017).
  - **Evidência — as duas metades.** Os prazos: `packages/core-ts/tests/coexistencia.test.ts`, «alerta as 12 h, **uma vez**, e nao falha nada ainda» (a segunda varredura não alerta de novo, pelo `alertado_em IS NULL`) e «falha e pede offboard as 24 h, com o relogio acelerado»; contra a base, `packages/core-ts/tests_bd/coexistencia.bd.test.ts`, «[bd] o relogio acelerado fecha as 24 h, e a segunda varredura nao faz nada». O relógio entra por parâmetro e o prazo é coluna — é isso que torna «relógio acelerado» possível sem mexer no servidor.
  - O `history`: `packages/core-ts/tests/coexistencia.test.ts`, «um lote de historico alimenta contactos e contagens, e zero jobs» — o `jobsParaOAgr` é do tipo literal `0` e o módulo **não tem porta** para o AGR nem para a saída, pelo que o zero é da forma e não de um `if` —, com «nenhuma instrucao escreve corpo de mensagem: a tabela nao tem onde» ao lado. Grupos e nomes prendidos pelos `GRUPOS` e `TESTES_OBRIGATORIOS` de `db/tests_outbound/test_outbound.py`, e o esquema por `db/tests/test_coexistencia_schema.py`.
  - **O que esta caixa não afirma:** que a varredura corre sozinha. Não há agendador neste repositório (nasce com KAM-071/KAM-078); o que está provado é o predicado, chamado com o relógio por parâmetro.

- [ ] O Chatwoot não tem credenciais Meta; o agente da conta A não lê conversas da conta B; `openHandoff` repetido com o mesmo `handoffId` cria 1 conversa (KAM-019).
  - **Vazia: das três cláusulas, uma está medida e duas não.** As credenciais **estão**: o spike `infra/chatwoot/spike.py` (`make chatwoot-spike`) lê `WHATSAPP_APP_ID`, `WHATSAPP_CONFIGURATION_ID` e `WHATSAPP_APP_SECRET` **no `env` do contentor a correr** — a única forma de a asserção valer, porque uma variável pode entrar por `.env`, por herança ou embutida na imagem — e as três estão ausentes; o *inbox* criado vem `Channel::Api` do próprio Chatwoot. Resultado em `docs/evidencia/KAM-019-bot-open.md`.
  - «O agente da conta A não lê conversas da conta B» **não está medido**. O que existe é o X-03 sobre as **nossas** tabelas (`packages/core-ts/tests_bd/handoff.bd.test.ts`, «com o contexto de A, as passagens de B nao aparecem», e as duas `UNIQUE` que recusam a mesma conta e o mesmo utilizador do provedor em dois *tenants*), que é uma afirmação diferente: ninguém exercitou a API do Chatwoot com o *token* de uma conta contra as conversas de outra. O registo que hospedaria o X-10 não existe em código — é o `registerCase` do EPIC-07, KAM-066.
  - «`openHandoff` repetido cria 1 conversa» está provado **do nosso lado** e não no Chatwoot: «**cinco aberturas concorrentes: 1 linha e 1 chamada ao provedor**», em duas ligações, pela chave primária com o `handoff_id` derivado. Falta a busca da conversa por atributo `handoffId`, porque o `ClienteDoProvedor` não tem operação de leitura — e sem ela duas aberturas que a nossa base não correlacione criam duas conversas lá, pelo caminho do `degraded`. Depende do KAM-066 e de uma leitura no cliente do provedor que o KAM-019 deixou por fazer.

- [x] 0 invocações do AGR sem `consent_event` válido; «PARAR» pausa a conversa e regista a revogação (KAM-022).
  - **Evidência — as duas metades.** Os zeros: `packages/core-ts/tests/consentimento.test.ts`, «**0 invocacoes do AGR sem consentimento valido anterior**» — mil mensagens, cinquenta contactos, entradas sorteadas com semente fixa, zero violações, e com a asserção de que **houve** invocações, sem a qual um gate que recusasse tudo passava o teste. Contra a base: `packages/core-ts/tests_bd/consentimento.bd.test.ts`, «**sem consentimento: 1 aviso, 0 AGR, e a linha fica em outbound_messages**», que verifica também que **nenhuma prova** foi escrita — o aviso não é um consentimento. A decisão é um valor (`invocaAgr`) e o módulo nunca chama o AGR, que é o que torna a propriedade mensurável num sítio só.
  - O «PARAR»: `packages/core-ts/tests_bd/consentimento.bd.test.ts`, «**grava a revogacao de marketing e pausa, sem tocar na transacao**» (`accepted = false`, modo `pausada`, uma confirmação, `consent.withdrawn`), e `packages/core-ts/tests/consentimento.test.ts`, «**as oito variantes dos Testes Requeridos**» (caixa, acentos, espaços, pontuação e os três sinónimos). A revogação é **linha nova** e não correcção: «**o kamba_app nao tem UPDATE em consent_event**» e «**nem DELETE**» afirmam um `42501` — privilégio, não política.

- [x] Qualidade RED passa o canal a `restrito` sem suspender; o contador de *free tier* alerta aos 800 e aos 1.000 (KAM-021, KAM-023).
  - **Evidência — as duas metades.** O RED: `packages/core-ts/tests_bd/qualidade.bd.test.ts`, «**o RED restringe e escreve o motivo na mesma instrucao**» (as duas colunas na mesma instrução, senão há uma janela em que o canal está `restrito` e não diz porquê) e «**o GREEN repoe o canal, e emite**». O «sem suspender» é `packages/core-ts/tests/qualidade.test.ts`, «**nunca produz `suspenso`, com 50 eventos aleatorios** — a letra do criterio», com semente fixa.
  - Os avisos: `packages/core-ts/tests/metering.test.ts`, «um mes inteiro de 1.200 mensagens da **um** aviso e **um** esgotado» — é a **travessia** do número e não o valor, e um `usadas >= 800` dava duzentos avisos — com «**o esgotado sai na travessia dos 1.000, e so nela**» ao lado. Sob concorrência: `packages/core-ts/tests_bd/metering.bd.test.ts`, «**dois incrementos em paralelo na travessia: +2 e UM aviso**», em duas ligações. O 800 está escrito como fracção do tecto (`FRACCAO_DE_AVISO = 0.8`) e não como literal.
  - A caixa do critério 3 do bloco KAM-023 fica vazia pelo **fuso por canal**, que não existe no esquema e que este critério de saída não pede.

- [ ] O simulador cobre 100% dos tipos de entrada de `../docs/tecnica/01` §5.4 e dos campos de webhook de §4.4; o contrato *online* corre uma vez no número de teste de *staging* (KAM-024).
  - **Vazia: a cobertura cumpre-se e o contrato *online* não existe.** A cobertura **mede-se** e dá **100,0% (33/33)**, `exit 0` — `node tools/meta-sim/src/cli.ts cobertura`, com dezasseis itens de tipo, onze de campo e os seis motivos de `PARTNER_REMOVED` (quatro dos quais existiam só na declaração do `enum` antes da revisão adversarial). E o relatório não se acredita a si próprio: `tools/meta-sim/tests/cobertura.test.ts`, grupo «o relatorio de cobertura» — «da 100% e nenhuma falta», «tem 33 itens: 16 tipos, 11 campos e 6 motivos» e «falha quando um item perde o teste», que é o que o torna um *gate* e não um número.
  - O contrato *online* **não existe**, e não por falta de trabalho: precisa do número de teste da app Meta de *staging*, que depende de `ext:KAM-102`, pelo que `docs/evidencia/KAM-024.md` não pode trazer «1 execução verde». Escrever uma *suite* que se desligasse sozinha por falta de credenciais era construir o falso verde que o critério 9 do próprio KAM-024 proíbe por extenso. As duas regras já decididas estão em `../docs/meta-sim.md` §9, para quem a escrever quando o número existir. Depende de `ext:KAM-102`.

- [ ] Os itens NÃO VERIFICADOS L1, L2, L6, L7, L10 têm medição ou nota de evidência anexada ao ticket respectivo.
  - **Vazia por um dos cinco, e é o L10.** **L7 está medido**: o spike do KAM-019 respondeu à pergunta, com veredicto `O TOKEN DO BOT CHEGA` em `docs/evidencia/KAM-019-bot-open.md`, e a implementação usa a opção que funciona. **L2 tem medição e nota**: a carga do KAM-013 acima mede o p99 real, e a leitura do «estados não facturáveis» está devolvida por escrito a quem escreveu o critério, na secção de verificação daquele bloco. **L1 e L6 têm nota escrita** nos blocos respectivos — o KAM-017 diz por extenso que o relatório de `ext:KAM-100` não existe e que o modo predefinido fica por decidir, e o critério 8 do KAM-018 deixa a caixa vazia com a razão: a `echo_latency_ms` pede ≥ 30 *echoes* reais de *staging* com números +244, que é o mesmo `ext:KAM-100`.
  - **O L10 — verificação por SMS Unitel/Africell — não tem nota em ticket nenhum deste epic.** O risco R8 da secção «Riscos do Epic e itens NÃO VERIFICADOS» atribui-o ao KAM-093, que é de outro epic, e o único ticket deste que o tocaria, o KAM-115, está bloqueado pelo KAM-116 (agregador de SMS) e não arrancou. Depende do KAM-093 e do KAM-116.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-013 | GWY: webhook Meta (verificação, assinatura, deduplicação, 200 rápido, fila) | feature | L | P0 | KAM-001, KAM-005, KAM-010 |
| KAM-014 | CHR: ChannelResolver por `phone_number_id` com BSUID | feature | M | P0 | KAM-003, KAM-008, KAM-013, KAM-004, KAM-006 |
| KAM-015 | Outbound: envio, janela de 24 h, templates utility e custo de mensagens | feature | L | P0 | KAM-013, KAM-014, KAM-004, KAM-024 |
| KAM-016 | Embedded Signup v4 e Tech Provider (troca de code, subscrições de webhooks) | feature | L | P0 | KAM-013, KAM-003, ext:KAM-102, KAM-010, KAM-024 |
| KAM-017 | Coexistência: history, state sync, echoes, `PARTNER_REMOVED`, sincronização de 24 h | feature | L | P0 | KAM-016, ext:KAM-100, KAM-024 |
| KAM-018 | Protocolo bot ↔ dono ↔ humano: modos da conversa e silenciamento por echo | feature | M | P0 | KAM-014, KAM-017 |
| KAM-019 | HND: HandoffProvider e Chatwoot (Agent Bot API, espelho por inbox de tipo API) | feature | L | P0 | KAM-014 |
| KAM-020 | Mídia: download autenticado, armazenamento e URL interna assinada | feature | M | P0 | KAM-013, KAM-011, KAM-024 |
| KAM-021 | Quality rating, estado `restrito` e monitorização de limites | feature | M | P0 | KAM-013, KAM-009 |
| KAM-022 | Consentimento no 1.º contacto (aviso versionado, botões, `consent_event`) | feature | M | P0 | KAM-008, KAM-014, KAM-015, KAM-159 |
| KAM-023 | Monitorização do free tier de service messages e do método de pagamento da PME | feature | S | P0 | KAM-015 |
| KAM-024 | Simulador de webhooks Meta e testes de contrato com número de teste | chore | M | P0 | KAM-013 |
| KAM-115 | Aviso ao dono por canal alternativo (e-mail ou push) | feature | S | P1 | KAM-017, KAM-021, KAM-023, KAM-116 |

---

## KAM-013 — GWY: webhook Meta (verificação, assinatura, deduplicação, 200 rápido, fila)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-001, KAM-005, KAM-010 |
| Bloqueia | KAM-014, KAM-015, KAM-016, KAM-020, KAM-021, KAM-024, KAM-056, KAM-072, KAM-084 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§5), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.5), ADR-001, ADR-009, ADR-010 |

### Contexto

O GWY é o **único** endpoint de webhook da Meta (ADR-001); o Chatwoot recebe apenas um espelho. Factos CONFIRMADOS (E1 §5): HTTPS com certificado válido; verificação por `GET` com `hub.mode`, `hub.challenge`, `hub.verify_token`; `POST` com `X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo bruto com o App Secret>`; re-entrega até 7 dias com *backoff* exponencial, sem ordem garantida e concorrente; capacidade para 3× o tráfego de estados + 1× o de entrada. O *timeout* exacto do webhook é NÃO VERIFICADO (L2): o alvo interno é 200 em < 500 ms. As garantias do BullMQ também não foram verificadas, logo todos os consumidores são idempotentes.

### Objectivo

Implementar o serviço `gwy` (Hono 4.13.x, ≥ 2 réplicas sem estado) que valida, deduplica, enfileira e responde 200 sem I/O pesado, e o *worker* que explode o payload em eventos de canal e os regista sem duplicados.

### Critérios de Aceitação

- [x] `GET /wa/webhook` com `hub.verify_token` correcto responde 200 com o corpo igual a `hub.challenge`; com `verify_token` errado responde 403 (código em proposta).
- [x] `POST` com assinatura ausente ou inválida devolve 401 e incrementa `gwy_sig_fail`; a assinatura é calculada sobre os bytes recebidos antes de `JSON.parse` (um corpo re-serializado com espaços diferentes e a mesma assinatura é rejeitado).
- [x] Aceita assinatura feita com o App Secret actual **ou** o anterior (*ring* `[actual, anterior]`); com um terceiro segredo devolve 401. Comparação em tempo constante (`timingSafeEqual`).
- [x] Reenviar o mesmo corpo 2× produz 1 *job* (`jobId = sha256(corpo)`); a mesma mensagem (`wamid`) em dois corpos distintos produz 1 linha em `inbound_events` (`UNIQUE (kind, event_key)`); `event_key` de estados é `wamid:estado`.
- [x] O 200 só é devolvido depois de o *job* estar enfileirado; com Redis indisponível o GWY responde 503 (a Meta repete) e nunca 200.
- [ ] JSON inválido com assinatura válida: 200 e quarentena em `unrouted_events` (payload com retenção de 7 dias, proposta) + alerta; nunca 5xx (evita *retry storm*).
- [ ] Carga de 200 pedidos/s durante 60 s com 3 estados por mensagem (proposta de perfil): p99 < 500 ms, mediana ≤ 250 ms, < 1% acima de 1 s; sob saturação (fila > 10.000 *jobs*, proposta) são descartados estados não facturáveis, nunca `messages`.
- [x] Encaminhamento por `kind`: `message`/`echo` → CHR; `statuses` → *stage* de *outbound* (nunca ao AGR); `history`/`smb_app_state_sync` → só ingestão (KAM-017); `account_update`/qualidade/templates → *stage* de gestão de canal.
- [x] Logs JSON só com `ts, level, svc, msg_id, wa_type, latency_ms, outcome, error_code`; um linter e um teste sobre os logs de 1 000 pedidos encontram 0 telefones e 0 texto de mensagem.


### Verificação dos Critérios de Aceitação

**9 critérios; 7 marcados, 2 vazios. 8 caixas de DoD; 6 marcadas, 2 vazias.** Tudo
medido contra um PostgreSQL 18.6 e um Valkey a sério, com os **processos de
produção** a correr — `services/gwy/src/server.ts` e
`services/worker-canal/src/entrada.ts` —, e não contra uma fila em memória.

**A assinatura verifica-se com duas implementações.** A do repositório é
TypeScript; a da suite de integração é `hmac`/`hashlib` da biblioteca padrão de
Python. O que se mede é **interoperabilidade** e não auto-consistência — a
diferença entre «o nosso código concorda consigo» e «o nosso código concorda com
quem calcula HMAC-SHA256 por outro caminho».

### Os critérios, um a um

| # | Critério | Evidência |
|---|---|---|
| 1 | `GET` de verificação: 200 com o *challenge*, 403 com o token errado | Por HTTP real: o corpo volta **byte a byte** igual ao desafio. 403 para token errado, token truncado, token com um carácter a mais, token em maiúsculas, modo `unsubscribe`, sem `hub.mode` e sem `hub.challenge`. A resposta de recusa **não** devolve o desafio — a asserção procura-o no corpo |
| 2 | 401 com assinatura ausente ou inválida; `gwy_sig_fail`; assinatura sobre os bytes **antes** do `parse` | O teste que distingue a implementação certa da que assina o `JSON.stringify`: o **mesmo** JSON re-serializado com espaços, com a assinatura do original, dá **401**, e a fila fica com **um** *job* e não dois. Mais nove formas de cabeçalho malformado que recusam **sem lançar** — o `timingSafeEqual` rebenta com comprimentos diferentes, e o comprimento é escolhido por quem chama. `gwy_sig_fail` lido no `/metrics` do processo: delta de **2** em dois pedidos recusados |
| 3 | Anel `[actual, anterior]`; terceiro segredo → 401; `timingSafeEqual` | Os três casos por HTTP real contra o processo com o anel verdadeiro no cofre de ambiente. E o caso que o critério não pede: um anel vazio, nulo, ou de segredos vazios **recusa tudo** — em particular não valida um HMAC feito com chave vazia, que é um HMAC válido, e aceitá-lo era aceitar qualquer pedido de quem souber que o cofre está vazio |
| 4 | Dois níveis de deduplicação; `event_key` de estados é `wamid:estado` | **Nível 1, na fila a sério:** o mesmo corpo 2× deixa **um** *job*, e o `jobId` é exactamente `sha256(corpo)` (comparado com o resumo calculado em Python). **Nível 2, na base a sério:** dois corpos com o mesmo `wamid` e `sha256` **diferente** entram como **dois** *jobs* e deixam **uma** linha. **A letra:** três estados do mesmo `wamid` dão `wamid:sent`, `wamid:delivered` e `wamid:read` — três linhas e não uma, que é o que o perfil de carga precisa |
| 5 | 200 só depois de enfileirar; 503 com Redis em baixo, nunca 200 | **A ordem:** com um `addLote` que só resolve quando o teste manda, a resposta não chega antes — e o teste afirma que não chegou, com uma bandeira lida dentro do `then`. Por HTTP real, a leitura da fila é imediatamente depois da resposta, sem espera nenhuma. **A fila em baixo:** `docker stop --timeout 0` no contentor, cinco pedidos, e o conjunto de códigos é exactamente `{503}`. Nem `ECONNREFUSED`, nem o anfitrião, nem a senha saem na resposta ou no registo. E depois do `start`, o **mesmo** processo volta a aceitar sem ser reiniciado |
| 6 | JSON inválido: 200 e quarentena com retenção de 7 dias **+ alerta** | **Vazia, e é parcial.** As duas partes que o critério mede estão feitas e provadas: 200 (nunca 5xx, que começaria sete dias de re-entregas) e a linha em `unrouted_events` com `motivo = json_invalido`, `waba_id` nulo, o corpo em base64 e uma `event_key` determinística — a re-entrega do mesmo corpo mau **não** cria segunda linha. Faltam as outras duas, e nenhuma é código deste ticket: **a retenção de 7 dias não é imposta** (esta revisão não cria função de limpeza nem agendador — o agendador nasce com KAM-071, a mesma decisão que a `0004` tomou para as partições mensais), e **não há alerta**, porque não há sistema de alertas no repositório (KAM-079, KAM-080). Marcar a caixa era chamar «cumprido» a metade |
| 7 | Carga 200 req/s × 60 s; p99 < 500 ms; descarte de estados não facturáveis | **Vazia, e a razão não são os números.** Os números cumprem-se — estão na tabela da carga, abaixo. O que diverge é a **regra do descarte**: o critério diz «estados não facturáveis», e o campo que diz se um estado é facturável está `NÃO VERIFICADO` (o `E1` §5 não documenta a forma do `pricing` dentro de um `statuses[]`). Implementar «`pricing.billable === false`» era desenho sobre um campo que ninguém confirmou. A regra que corre é mais estreita: **um estado que traga `pricing`, de qualquer forma, não se descarta** — e isso é um subconjunto de «não facturáveis», não a letra. **A leitura fica escrita e a decisão volta a quem escreveu o critério.** Também é leitura minha o perfil: «3 estados por mensagem» lê-se como 50 corpos de mensagem + 150 de estado por segundo, pelo `3×` do `E1` §5 |
| 8 | Encaminhamento por `kind` | Os quatro grupos, com os onze campos de webhook registados com o `kind` certo contra a base real, e `unrouted_events` a **zero** nesse teste. E as duas propriedades **negativas** que importam, como asserções: um `statuses` nunca chega ao `chr` (é por lá que o AGR é alimentado), e `history`/`smb_app_state_sync` vão **só** a `ingestao`. O mapa é total (`Record<Kind, Destino>`): um `kind` novo sem destino é erro de compilação |
| 9 | Logs só com os oito campos; linter e teste de 1 000 pedidos | **O teste que o critério nomeia:** 1 000 pedidos com dez canários — telefone em quatro formatos, nome de perfil, texto de mensagem, morada, e-mail, cartão e *token* da Meta — um terço assinado, um terço sem assinatura e um terço com assinatura errada. **0 ocorrências** de qualquer canário e **nenhuma chave fora dos oito**. O *logger* corre em **modo estrito** nesse teste: um campo fora da *allowlist* lança em vez de ser retirado em silêncio. De ponta a ponta, o mesmo nos registos dos **dois processos**: o `wamid` nunca sai em claro — sai `idOpaco`, `m_` mais 32 hexadecimais. E `make log-lint`: 0 achados em 78 ficheiros TS/JS e 34 Python |

### A revisão adversarial encontrou oito, e os oito eram sobre o que não se vê

Nenhum foi apanhado pelos 796 testes de então, nem pelas 270 mutações, nem por
*gate* nenhum — e isso é o padrão: todos eles são sobre **comportamento sob
condições que nenhum teste criava** (um corpo grande, um Redis lento, um corpo
com mil itens, um processo que morreu a meio). Os oito estão corrigidos, e cada
um ficou com teste.

| | O defeito, com o cenário | Como ficou |
|---|---|---|
| **A1** | **O corpo era lido inteiro antes de a assinatura ser verificada, e sem tecto.** Qualquer pessoa, sem segredo nenhum, fazia `POST /wa/webhook` com 200 MB e o GWY alocava os 200 MB — mais uma cópia em base64 no caminho bom — antes de responder 401. No **único endpoint público** da plataforma, com duas réplicas e o *proxy* que o protegeria a ser de outro ticket (KAM-077) | `CORPO_MAXIMO` de 1 MiB (*proposta*), com **duas** guardas: o `content-length` declarado, e o tamanho do que chegou de facto — um pedido `chunked` não traz `content-length` e passava pela primeira. Responde **413** e não 401, para um corpo legítimo grande não aparecer como `gwy_sig_fail` e mandar procurar no sítio errado. Cinco testes, mais um na suite de integração contra o processo a correr |
| **A2** | **O `/metrics` estava na porta do webhook.** O webhook é alcançável de fora (ADR-001): qualquer pessoa que chegasse ao GWY lia `inbound_queue_depth` — o atraso da plataforma em tempo real —, `gwy_requests_total` e `gwy_sig_fail`. Com a profundidade visível, quem quisesse provocar o descarte do critério 7 sabia exactamente quando a fila passara os 10 000 | Dois servidores: a porta pública leva **só** o `/wa/webhook`, e o `/healthz` e o `/metrics` vivem na interna (3010, `GWY_METRICS_PORT`), como nos outros processos. O teste da sonda volta a afirmar que o `/metrics` **não** responde na porta pública, agora com a razão escrita, e a suite de integração mede-o nas duas portas do processo a correr |
| **A3** | **O amostrador da profundidade escrevia uma linha por segundo com o Redis em baixo** — 86 400 por dia. A avaria afogava o registo que devia sinalizá-la, e com ele as linhas de `assinatura_invalida` que importam. E com o Redis **lento** (2 s por comando) começava uma leitura nova a cada segundo sem a anterior ter acabado, cada uma com o seu temporizador de 5 s, a acumular pedidos pendentes no processo que tem de responder em menos de 500 ms | Trinco de reentrância (uma leitura de cada vez) e registo **só na transição**: uma linha quando deixa de se ler, uma quando volta |
| **A4** | **Cada evento de quarentena guardava uma cópia inteira do corpo, e não havia tecto de eventos por corpo.** Um corpo assinado com 1 000 `changes` de um campo desconhecido escrevia 1 000 linhas de até 256 KiB — 256 MB de um pedido, com a retenção que os limparia a ser de outro ticket. E um corpo com 100 000 `statuses` fazia 100 000 `INSERT` sequenciais num só *job*, com `concurrency: 1`, a bloquear a partição todo esse tempo | O corpo guarda-se **uma vez por corpo**, na primeira linha. E `EVENTOS_MAXIMOS_POR_CORPO` (1 000, *proposta*): acima do tecto o corpo vai **inteiro** a uma linha de quarentena, com chave determinística, em vez de ser meio processado — um corpo meio processado é pior, porque o `jobId` já não distingue os dois casos |
| **A5** | **Um *job* malformado gastava as seis tentativas da escada** — cerca de treze minutos de partição, com `concurrency: 1` — num *job* que se sabia irrecuperável à primeira leitura. O `eventos/trabalhador_bullmq.ts` já usava `UnrecoverableError` para esta classe exacta (`TenantEmFaltaError`), com a razão escrita | `UnrecoverableError`, como o precedente |
| **A6** | **Um evento recuperado era reportado como `duplicado`.** O caminho de recuperação — o evento estava registado e **sem** `processado_at` — devolvia `duplicado` e só depois encaminhava. O contador de duplicados subia sem ter havido duplicado, e a recuperação de um evento que esteve perdido não deixava rasto distinguível do caso banal | Desfecho próprio, `recuperado`, com contador e métrica próprios. Dois testes: o recuperado e o duplicado verdadeiro |
| **A7** | **O *worker* de entrada escutava em todas as interfaces.** `serve({ fetch, port })` sem `hostname`, pelo que o Node escuta em `::`/`0.0.0.0`: correr o processo à mão numa rede partilhada abria-lhe o `/metrics` e o `/healthz`. O `services/gwy/src/server.ts` defende-se disto e escreve a razão — `specs/01` §6 princípio 7 e o DoD do KAM-001, «nada além de localhost» | `hostname` explícito. **O `publicador.ts` e o `consumidor.ts` têm o mesmo defeito** e são anteriores a este ticket: ficam registados aqui e em `docs/dividas-documentais.md` |
| **A8** | **O *worker* expunha as cinco métricas do GWY, a zero.** Não incrementa nenhuma: saíam `gwy_sig_fail 0` e `inbound_queue_depth -1` permanentes — o segundo ao lado do valor real do GWY, onde um alerta sobre a profundidade o lê e **não dispara** — e do trabalho que ele faz de verdade não saía nada | Três métricas próprias (`inbound_events_total` por desfecho, `inbound_unrouted_total` por motivo, `inbound_job_failed_total`), com etiquetas de lista fechada. *Proposta*, como o `gwy_shed_total`: o DoD nomeia as do GWY |

**O que a revisão não mudou, e porquê.** Nenhum dos oito é um defeito de
desenho: os domínios, a deduplicação em dois níveis, o encaminhamento e a
política de registo passaram intactos. Os oito são sobre o comportamento nas
bordas — e sete deles só existem porque o GWY é o **único endpoint externo** da
plataforma, o que torna «o que um estranho consegue fazer com um pedido» a
pergunta certa a fazer a este ficheiro e não a outro.

### E um nono, que foi o *gate* 4 a apanhar

A separação de portas do **A2** criou uma segunda app no `services/gwy/src/app.ts`
— o `criarAppDeMetricas` — e eu deixei-a **sem `app.onError`**. Qualquer erro
nela saía pelo tratador por omissão do Hono, isto é, `console.error(err)` com a
mensagem e a pilha em claro no `stderr`: exactamente o que o `createApp` existe
para fechar (KAM-068). O mesmo no `criarApp` do processo de entrada do
`worker-canal`.

**E o teste que devia apanhá-lo passava**, porque contava uma app e via um
`onError`. O que ficou vermelho foi outra asserção do mesmo teste — a que exige
o texto literal `createApp(log).fetch` no `server.ts`, e que uma mudança
legítima (dar dependências ao `createApp`) quebrou por afirmar a **forma da
chamada** em vez da propriedade. Duas correcções, portanto:

- a asserção passa a exigir `createApp(log` — que a app é criada **com** o
  logger é o que importa;
- e acrescenta-se uma que **conta**: um `onError` por `new Hono(` em cada
  `src/app.ts`. Antes da correcção eram duas apps e um tratador, e a asserção
  nova fica vermelha — foi assim que se confirmou que ela morde.

É o caso mais limpo de «a máquina apanha o que os olhos não apanham» deste
ticket: a revisão adversarial leu o `app.ts` inteiro e não viu a app sem
tratador, porque estava a olhar para o que o código **faz** e não para o que lhe
**falta**.

### Três defeitos que só a suite de integração apanhou

Nenhum deles era visível nos testes unitários de então, e os três tinham o
mesmo sintoma: **silêncio**.

| | O defeito, medido | Como ficou |
|---|---|---|
| **1** | **O `backoffStrategy` que faltava.** O `addLote` do `filas_bullmq.ts` põe `backoff: { type: "custom" }` em **todos** os *jobs* — é a forma de o BullMQ passar a decisão do atraso ao *worker* —, e um *worker* que o não registe lança `Unknown backoff strategy custom` ao calcular o atraso da segunda tentativa. Pior do que «não recua»: o tratamento da falha rebentava, o *job* ficava em `failed` **sem passar pela quarentena**, e um corpo ilegível desaparecia com a Meta a re-entregar sete dias | `AJUSTES_DO_TRABALHADOR` com a escada do consumidor (`06` §6.4), numa constante exportada **para ter teste sem fila**: cinco asserções que prendem os degraus, o tecto e o `attemptsMade = 0` da primeira falha |
| **2** | **O `SELECT` que o `ON CONFLICT` exige.** `kamba_app` tinha só `INSERT` em `unrouted_events`, e o PostgreSQL trata os elementos da cláusula de inferência como **leitura**: a inserção falhava com `42501`. A quarentena ficava a zero e parecia que o corpo nunca chegara. **É a mesma lição que a revisão `0005` já escrevera** para o `ON CONFLICT (consumer, event_id)` do `events_dlq`, e eu não a tinha lido | `GRANT SELECT (kind, event_key)`, duas colunas. O `payload`, o `motivo` e os dois identificadores da Meta continuam fechados, e isso está medido coluna a coluna. **E o que as duas colunas dão de lambuja está declarado em vez de escondido:** com privilégio em qualquer coluna o `count(*)` passa — e é aceitável aqui e não era no `events_dlq`, porque esta tabela não tem `tenant_id` e a contagem é da plataforma inteira |
| **3** | **Um *job* falhado não deixava linha nenhuma.** O BullMQ não escreve nada quando ninguém ouve o acontecimento `failed`, e o *worker* não ouvia. Foi isto que fez o defeito 2 custar duas execuções da suite para ser diagnosticado: o registo mostrava `entrada_registado` para os corpos bons e **nada** para o que falhou | Ouvinte de `failed` **e** de `error` — o segundo para o que não tem *job* associado (a ligação caiu, o Lua do BullMQ recusou) — a sair por `log.excepcao`, com o código e a classe e **nunca** a mensagem: um erro de `pg` pode trazer a instrução com os parâmetros, e os parâmetros deste caminho são o corpo do webhook |

### Quatro coisas que o trabalho encontrou e que o bloco não previa

1. **O *gate* 3b obrigou a estreitar os domínios, e ficou melhor.** O bloco dá um
   `kind` com catorze valores; o *gate* pede o domínio **por coluna**, e isso
   revelou que `inbound_events` só vê doze (os campos de webhook) e
   `unrouted_events` só dois (os caminhos de quarentena). Com um `CHECK` de
   catorze nas duas, uma `message` podia ser escrita na quarentena e um
   `invalido` no registo de entrada. Nenhum caminho do código o fazia; agora
   nenhum o pode fazer, e os tipos em TypeScript dizem o mesmo.
2. **Um evento sem `wamid` não tinha chave.** Um `account_update` não traz
   identificador nenhum, e a Meta re-entrega sete dias: sem chave
   determinística, cada tentativa criava uma linha. Nenhum documento dizia qual
   era a chave desses eventos. Nasceu o **resumo canónico** `k_` + 32
   hexadecimais sobre `(waba_id, campo, valor)` com as chaves **ordenadas** — o
   `JSON.stringify` não serve, porque a ordem das chaves é a de inserção.
3. **O descarte sem verificar o campo descartava um `account_update`.** A
   primeira versão de `soEstadosSemPreco` inspeccionava o `value` e não o
   `field`: um `account_update` cujo `value` trouxesse um array chamado
   `statuses` era descartado **em silêncio**, e um `account_update` perdido é um
   canal que mudou de estado sem ninguém saber. Apanhado pelo teste «é falso para
   tudo o que não seja isso», que é a razão de ele enumerar casos em vez de
   confirmar o caso bom.
4. **O nome do array dentro de `smb_message_echoes` continua `NÃO VERIFICADO`.** O
   `E1` §5 não o diz e nenhuma página primária foi lida nesta execução. Em vez de
   o inventar, a explosão tem **duas regras**: um evento por item quando há itens
   com identificador, e um evento por `change` com o resumo canónico quando não
   há. Se a *proposta* (`message_echoes`) estiver errada, o *echo* cai na segunda
   regra — `kind` correcto, chave determinística, mais grosso e continua
   correcto. Fixá-lo é KAM-017, que é quem lê a documentação de coexistência.

### As duas caixas de DoD vazias

| Caixa | Porquê |
|---|---|
| «Todos os Critérios satisfeitos» | 7 de 9. Os dois vazios estão nomeados acima, e nenhum deles é código em falta: um pede um agendador e um sistema de alertas que são de outros tickets, o outro pede uma regra que depende de um campo `NÃO VERIFICADO` |
| «Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar» | **Testes verdes e cobertura acima do limiar** — os números estão abaixo. **Revisor humano: zero**, pela decisão em vigor (sem revisão humana até produção). Fica registado que este é o ticket do **único endpoint externo da plataforma**: tudo o que a Meta manda entra por aqui, e uma revisão adversarial é evidência, não é um revisor |

### O que correu, e com que números

| Verificação | Resultado |
|---|---|
| `pnpm -r run test` | **806 testes, 0 falhas** (eram 711: +95) — `core-ts` 725, `gwy` 44, `worker-canal` 15, `contracts` 12, `com` 5, `onboarding-web` 5 |
| Gate 8 (`tests`) | **387 testes, OK** — a revisão `0008` aplica, reverte e volta a aplicar |
| Gate 8 (`tests_entrada`) | **34 testes, OK**, 147 s, com os dois processos de produção, PostgreSQL e Valkey reais |
| Gate 8 (`tests_entrada_carga`) | **OK** — ver a tabela da carga, a seguir |
| Gate 4 (cobertura) | **crítico 95%** (mínimo 90%), **restante 88%** (mínimo 75%) |
| Gate 3b (nomes canónicos) | conforme — dicionário **v1.19**, 8 migrações, 22 tabelas, 68 valores de `CHECK` |
| Gate 3 (referências, *handoff*, contagens) | conforme — 15 578 referências em 970 ficheiros; 630 caminhos de *handoff*; 13 contagens vivas, 0 erradas |
| Gate 3c (coerência do backlog) | conforme — 159 linhas no §4 e 159 blocos a dizer o mesmo |
| Gate 2 (`log-lint`, `lint-arch`) | conforme — 0 achados em 78 ficheiros TS/JS e 34 Python |
| Gate 4, segunda passagem | **apanhou um defeito real** — a app das métricas sem `onError`. Ver a secção acima |
| Gate 9 (segredos) | **limpo** — 970 ficheiros |
| Gate 7 (contratos de evento) | conforme — 76 contratos |
| Gate 11 (SBOM, licenças, cadeia) | conforme — 143 componentes, 0 vulnerabilidades CRITICAL |
| Mutações | `--aplicaveis`: **270 conferidas, 0 não aplicáveis** — a edição de `filas_bullmq.ts` é aditiva e não quebrou nenhuma |

**Nenhuma dependência nova.** O `hono` 4.13.13 e o `@hono/node-server` 2.1.4 já
estavam no `gwy`; o `bullmq` 6.3.11 e o `ioredis` 5.11.1 chegam por
`@kamba/core-ts`, e o `pg` já era do `worker-canal`. O `pnpm-lock.yaml` **não
muda**.

### A carga do critério 7, medida

12 000 pedidos em **60,1 s**, isto é **200/s** exactos, com 50 corpos de
mensagem e 150 de estado por segundo. Contra o GWY real, com o *worker* a
consumir, PostgreSQL e Valkey em contentores, e o cliente a medir **do primeiro
byte enviado ao último recebido** — mais pessimista do que a latência do
servidor, e de propósito: é a que a Meta veria.

| Grandeza | Medido | Limiar do critério |
|---|---|---|
| Respostas | **12 000 × 200**, nenhuma outra | — (um 503 sob carga é um webhook que a Meta repete) |
| Mediana | **39 ms** | ≤ 250 ms |
| p99 | **199 ms** | < 500 ms |
| Acima de 1 s | **0,00%** | < 1% |
| Máximo | 580 ms | — |
| Mensagens registadas | **3 000 de 3 000** | nenhuma perdida |
| `gwy_shed_total` | **0** | nada descartado: todos os estados deste perfil trazem `pricing` |

**O que isto não é:** uma medição de capacidade de produção. Corre em
contentores descartáveis, na máquina de quem corre o *gate*, com o cliente no
mesmo anfitrião. O dimensionamento é KAM-084, que depende deste ticket. O que
esta prova mede é que o **desenho** aguenta o perfil — que o 200 não espera por
I/O que não devia estar no caminho.

### Três defeitos fora do âmbito, que este trabalho **não** corrigiu

Nenhum é causado por este ramo, e os dois são de outro ticket:

1. **O `lint_contagens` não corre de dentro de um `git worktree` sob
   `.claude/`** — e isto **já estava declarado**: é a linha **44** de
   `../docs/dividas-documentais.md`, encontrada pelo KAM-133 pela mesma via.
   Fica aqui porque voltou a morder e porque a medição é nova: com raiz
   relativa, **13 contagens vivas, 0 erradas**, acima do mínimo de 10. Em CI o
   *checkout* não está sob `.claude`, pelo que o *gate* passa de verdade e não
   por acidente. **Nada se acrescenta à lista de dívidas**: uma segunda entrada
   para o mesmo defeito era a classe de ruído que essa lista existe para evitar.
2. **O `coverage_gate.py` não corre em Python 3.14.** Um `%o` numa cadeia de
   ajuda que o `argparse` do 3.14 passou a validar («badly formed help string»).
   O CI usa 3.12 e não vê isto; apareceu ao medir a cobertura dentro de um
   contentor `node:24.21.0-alpine`, que traz 3.14. Linha **45** da lista de
   dívidas.
3. **O `publicador.ts` e o `consumidor.ts` escutam em todas as interfaces.** É
   o achado A7 aplicado a dois ficheiros anteriores a este ticket: `serve({
   fetch, port })` sem `hostname`, contra o que o `services/gwy/src/server.ts`
   fixa citando `specs/01` §6 princípio 7. O `entrada.ts` deste ticket foi
   corrigido; os outros dois ficam na linha **46**.
### Detalhes Técnicos

- **Componentes:** GWY (e *worker* de canal em `services/worker-canal`). O TLS público termina no proxy (KAM-077); o GWY escuta em HTTP atrás dele.
- **Pipeline (de `../docs/tecnica/01` §5.2):**
```ts
app.post('/wa/webhook', async (c) => {
  const raw = await c.req.arrayBuffer();
  if (!verifyAny(raw, c.req.header('x-hub-signature-256') ?? '', secrets.ring('META_APP_SECRET'))) return c.text('invalid signature', 401);
  await inboundQueue.add('wa', { raw: b64(raw), recvAt: Date.now() }, { jobId: sha256Hex(raw), removeOnComplete: 10000 });
  return c.text('ok', 200);
});
```
- **Tabelas:** `inbound_events(id, kind, event_key, waba_id, phone_number_id, recebido_at, processado_at, UNIQUE (kind, event_key))` sem `tenant_id` (o tenant só nasce no CHR); `unrouted_events` idem. O payload de conversa não é persistido aqui, só no *job* e, depois, nos *checkpoints* do AGR. Estados monotónicos (`sent < delivered < read`; `failed` terminal) aplicam-se em KAM-015.
- **Segredos:** App Secret e `verify_token` via `SecretProvider` (implementação de ambiente até KAM-010). Ordenação por conversa e janela de coalescência de 1,5 s (a calibrar) são do AGR/KAM-025; aqui só se preserva o `timestamp` da Meta.

### Testes Requeridos

- Unit: verificação de assinatura (válida, inválida, *ring*, corpo re-serializado); geração de `event_key`.
- Integração (Postgres e Redis reais): duplicado byte-a-byte, duplicado semântico, Redis parado, JSON inválido.
- Carga: perfil acima com medição de latência e de *shedding*. Contrato: fixtures do simulador (KAM-024).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/gwy.md`); Conventional Commits; sem TODOs órfãos.
- [x] **Idempotência** — dedup em dois níveis com teste de repetição.
- [x] **Privacidade** — logs sem conteúdo nem telefone; payload de conversa fora de `inbound_events`.
- [x] **Sem segredos** — App Secret só via `SecretProvider`; scan limpo.
- [x] **Custo e observabilidade** — `gwy_requests_total`, `gwy_sig_fail`, `gwy_enqueue_ms`, `inbound_queue_depth` desde o código.
- [x] **Migrações reversíveis** — `downgrade` das tabelas de entrada testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-013 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-013), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§5) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§5). Objectivo: GWY como único endpoint de webhook da Meta.
- Hono 4.13.x (não o 5.0.0-rc.0); GET de verificação; POST com HMAC-SHA256 sobre o corpo bruto, ring [actual,
  anterior], timingSafeEqual; 401 se falhar; jobId = sha256(corpo); 200 só após enfileirar; 503 se Redis cair.
- Worker: explode entry/changes/messages/statuses; inbound_events com UNIQUE (kind,event_key); quarentena
  para JSON inválido; roteamento por kind (history só ingestão; statuses nunca ao AGR).
- Logs JSON com allowlist de campos; zero telefones e zero conteúdo.
Não expandas escopo: resolução de tenant é KAM-014, envio é KAM-015, subscrição de campos é KAM-016.
Testes: assinatura, duplicados, Redis parado, carga, linter de logs. Abre PR com o template do §7.
```

---

## KAM-014 — CHR: ChannelResolver por `phone_number_id` com BSUID

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-003, KAM-008, KAM-013, KAM-004, KAM-006 |
| Bloqueia | KAM-015, KAM-018, KAM-019, KAM-022, KAM-025, KAM-054, KAM-118 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.3, §7, §10.2), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.1), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§5.5), ADR-010, ADR-011, ADR-012, ADR-015 |

### Contexto

O CHR é o único sítio onde o `tenant_id` nasce para o estado do grafo; a ToolLayer só aceita o que vier do estado (`../docs/tecnica/01` §7.2). Corre antes de qualquer acesso ao runtime, aplica o estado do tenant e do canal, resolve o contacto por BSUID ou telefone (KAM-008) e determina o **modo da conversa**. Aplica também as guardas do Fluxo B (ADR-011): em produção do Piloto recusa canais com `origem='plataforma'` ou `vertical='assistente'`. Antes de existir contexto, a resolução usa o papel estreito `kamba_resolver` (KAM-004); o backlog mestre não declara essa dependência nem a de KAM-006 para a invalidação por evento (ver riscos).

### Objectivo

Implementar o CHR: `resolve(phone_number_id) → ChannelContext`, a tabela de estados que decide o que fazer com cada entrada, a criação da conversa e a entrega ao AGR (ou ao dono/humano) de um *job* sem telefone nem conteúdo desnecessário.

### Critérios de Aceitação

- [x] `resolve` devolve `{tenant_id, channel_id, vertical, plano, estado_tenant, estado_canal, channel_mode, origem}` com cache de 60 s, invalidada por `channel.updated` em ≤ 1 s quando o consumidor existir; até lá vale o TTL.
- [x] `phone_number_id` desconhecido: 0 *jobs* para o AGR, 1 linha em `unrouted_events`, alerta; a resposta ao GWY já foi 200.
- [ ] Matriz de estados (de `../docs/tecnica/01` §7.2), testada por linha: `onboarding`/`pendente` regista e não responde; `ativo` normal; `restrito` só responde dentro da janela e sem *marketing*; `desligado` nada; `suspenso` regista e responde 1 vez por contacto/24 h com mensagem estática; `encerrado` regista e descarta.
- [ ] Mensagem com apenas `wa_id` e mensagem com apenas BSUID do mesmo cliente convergem no mesmo `contact_id`; a fusão emite `contact.merged` exactamente 1 vez em 10 repetições.
- [x] Com `KAMBA_FASE=piloto` um canal `origem='plataforma'` ou `vertical='assistente'` é recusado (0 *jobs*, alerta) e o arranque falha se existir tal linha em produção.
- [ ] O *job* entregue ao AGR cumpre `packages/contracts/agent_invocation.schema.json` (`tenant_id`, `contact_id`, `conversation_id`, `channel_id`, `wamid`, `type`, `modo`) e não contém telefone, BSUID nem `display_name`; `thread_id = tenant_id:contact_id`.
- [x] Mensagens com `conversations.mode` ≠ `bot` não vão ao AGR; vão ao dono/HND (KAM-018/019).
- [x] Isolamento: o `phone_number_id` de A nunca devolve contexto de B; o papel `kamba_resolver` não lê outras tabelas; `resolve` em cache p95 ≤ 5 ms e sem cache ≤ 50 ms (proposta).

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba-plataforma#30`, ramo
`feature/KAM-014-chr-channelresolver`.
**Onze caixas marcadas, cinco vazias** (16 = 11 + 5) — cada uma com uma linha
aqui. Os números são os do *run* do CI e reproduzem-se com `make ci-3b`,
`make ci-4`, `make ci-6` e `make ci-8`. A revisão adversarial
([`ANALISE-27`](../docs/analises/ANALISE-27-KAM-014-chr-channelresolver.md))
**não aprovou** a primeira versão: dez achados, **sete corrigidos**, e o que
justifica o veredicto era o critério 4 a não estar cumprido de verdade — o
evento `contact.merged` estava a ser **registado em log e nunca emitido**. O
segundo mais grave foi apanhado pela bateria que o próprio DoD exigia: o
`downgrade` da `0009` contava as conversas como dono de uma tabela com `FORCE` e
via zero linhas, pelo que apagava tudo em silêncio. O desenho está em
[`../docs/chr.md`](../docs/chr.md).

| CA | Estado | Evidência |
|---|---|---|
| 1 — `resolve` devolve os oito campos, com *cache* de 60 s e invalidação por `channel.updated` em ≤ 1 s «quando o consumidor existir; até lá vale o TTL» | **satisfeito** | Os oito campos saem de `canalDaLinha`, conferidos um a um contra o `ChannelContext` e com a afirmação explícita de que o `persona` do `../docs/tecnica/01` §7.2 **não** está lá (ver «O que fica por decidir»). O TTL é um limite e não uma margem: aos 60 s **exactos** a entrada expirou (teste próprio); uma falha da base não deixa a entrada velha a servir de resposta; e um `phone_number_id` desconhecido **não** entra na *cache*. A invalidação entra por `channel_id` — que é o que o evento traz —, e mediu-se **0,722 ms** do pedido à releitura com o estado novo (1,912 ms com a máquina carregada), contra o limiar de 1 s. A segunda metade da condição é a que vale: **não há consumidor de `channel.updated`** (quem o emite é KAM-016/KAM-021), e o critério admite-o por escrito |
| 2 — `phone_number_id` desconhecido: 0 *jobs*, 1 linha em `unrouted_events`, alerta; o 200 já foi dado | **satisfeito** | Contra a base: **uma** linha com `motivo = canal_desconhecido`, e a re-entrega do mesmo evento **não** deixa uma segunda (o `ON CONFLICT (kind, event_key)` da `0008`, que é o que a Meta obriga com sete dias de re-entrega). 0 *jobs* ao AGR e 0 ao dono; o alerta é `chr_unrouted_total{motivo}` mais a linha de registo. Um evento **sem** `phone_number_id` segue o mesmo caminho, e um erro da base **não** segue: lança, e o *job* volta à fila sem `processado_at`. O 200 é do GWY e é anterior a este ticket (provado em `tests_entrada`, KAM-013) |
| 3 — matriz de estados testada **por linha** | **parcial — caixa vazia** | **As seis linhas estão testadas, e as 30 combinações de `(5 estados de tenant × 6 de canal)` também**: cada uma tem resposta, nenhuma lança, e só `(ativo\|restrito) × (ativo\|restrito)` chega ao AGR. Contra a base: `desligado` não abre conversa e não resolve contacto; `ativo` abre e entrega; `suspenso` abre a conversa, manda 0 *jobs* e devolve `mensagem_estatica` como saída autorizada. **O que não se cumpre à letra:** «`suspenso` … responde **1 vez por contacto/24 h**». O CHR responde «pode», não «quantas vezes» — a contagem por contacto é de quem envia (`../docs/tecnica/01` §8, e a docstring do `ten/estados.ts` do KAM-009 já o escreve), o envio é KAM-015, e a coluna que contaria esse limite não existe no DDL deste ticket. A caixa fica vazia |
| 4 — `wa_id` e BSUID convergem no mesmo `contact_id`; a fusão emite `contact.merged` 1 vez em 10 repetições | **parcial — caixa vazia** | **A segunda metade cumpre-se e está provada contra a base**: dez mensagens com os dois identificadores dão **uma** fusão, uma linha em `events_outbox` e o mesmo `contact_id` nas dez. **A primeira não é satisfazível** pelo algoritmo de `../docs/tecnica/01` §6.3, que é o que o KAM-008 implementa: uma mensagem só com BSUID procura por BSUID, não acha, não tem telefone por onde procurar — e **cria**. Medido: só-telefone cria P, só-BSUID cria A, e nada os liga. A convergência existe a partir da primeira mensagem que traz os dois, é verdadeira nos dois sentidos daí em diante, e quem tenha o `contact_id` antigo chega ao novo pela lápide (`merged_into`). A caixa fica vazia e a decisão devolve-se a quem escreveu o critério (`../docs/dividas-documentais.md`, linha 49) |
| 5 — `KAMBA_FASE=piloto`: canal `plataforma` ou `assistente` recusado (0 *jobs*, alerta) **e** o arranque falha se existir tal linha | **satisfeito** | **As duas metades.** Em execução: as três formas de Fluxo B — `tenants.tipo = 'platform'`, `tenant_channels.origem = 'plataforma'`, e vertical fora de `{vendedor, servicos}` — dão 0 *jobs*, 0 entregas ao dono, nenhuma conversa aberta e `chr_resolve_total{desfecho="fluxo_b_recusado"}`; a recusa é **antes** da matriz, pelo que um canal `ativo` não a dispensa. A verificação da vertical é **mais larga** do que a letra: lista de permitidas, pelo que `assistente_v2` também não passa. No arranque: `verificarArranque` com uma linha de cada um dos três tipos recusa nos três, com a contagem na mensagem; com `kamba_app` **recusa-se a correr** (`GuardaCega`) em vez de contar zero sobre uma base que não vê; com `kamba_batch` corre (a primeira das três vias de visibilidade); e sem `KAMBA_FASE` levanta **antes** de tocar na base. É espelho do `fluxo_piloto.py` do KAM-004, com teste de paridade que lê o ficheiro Python e compara as constantes **e** o SQL de visibilidade |
| 6 — o *job* cumpre `packages/contracts/agent_invocation.schema.json`, sem telefone/BSUID/`display_name`, `thread_id = tenant_id:contact_id` | **parcial — caixa vazia** | **A substância cumpre-se, o caminho não.** O contrato está publicado, com `additionalProperties: false`, e é comparado com o código **nos dois sentidos**: os campos que o esquema exige são exactamente os que a função escreve. Os sete do critério estão lá pelo nome, mais o `thread_id` (padrão `{uuid}:{uuid}`, que recusa um telefone) e o `vertical` do contexto do KAM-025. Sem telefone, sem BSUID, sem `display_name` — e não por disciplina: os argumentos não têm por onde os passar. Confirmado contra a base com um BSUID e um telefone canário. **O caminho é `packages/contracts/schemas/agent_invocation.v1.json` e não o da letra**, por duas razões medidas: os esquemas deste pacote vivem em `schemas/` com a versão no nome (`specs/01` §5), e um ficheiro `*.schema.json` bate numa sentinela do *gate* 3b que o exige dentro de `contratos/eventos/` — e isto não é um contrato de evento. A caixa fica vazia (`../docs/dividas-documentais.md`, linha 48) |
| 7 — `conversations.mode` ≠ `bot` não vai ao AGR | **satisfeito** | Os três modos (`dono`, `humano`, `pausada`) dão 0 *jobs* e uma entrega ao dono; a verificação é **antes** da matriz, pelo que um modo `humano` num tenant `ativo` continua a não ir ao AGR. Um `echo` vai **sempre** ao dono e nunca ao AGR, sem abrir conversa nem resolver contacto. Um modo que o código não conhece **para** o caminho em vez de o tratar como o mais parecido. Contra a base: o modo posto a `humano` pelo `kamba_batch` muda o destino da mensagem seguinte, e `kamba_app` **não consegue** alterá-lo — o privilégio não existe (`permission denied`), porque as transições são KAM-018. **Esta última metade deixou de ser verdade com o KAM-018**, que pediu o privilégio que a `0009` lhe reservou: a revisão `0016` concede `UPDATE (mode, last_human_activity_at)` a `kamba_app`, e o teste de base deste critério passou a afirmar o que continua vedado — as quatro colunas da identidade da conversa. A primeira metade (0 *jobs* fora do modo `bot`) mantém-se, e o KAM-018 volta a medi-la com a máquina de modos a escrever o valor |
| 8 — isolamento: o `phone_number_id` de A nunca devolve B; `kamba_resolver` não lê outras tabelas; p95 ≤ 5 ms em *cache* e ≤ 50 ms sem | **satisfeito** | Contra a base, com os papéis verdadeiros: dois tenants, dois canais, e cada `phone_number_id` devolve o seu — a propriedade vem da `tenant_channels_phone_number_id_uq` e da política `resolver_leitura`, **não** do código. `kamba_app` sem contexto devolve **zero linhas** à mesma consulta (que o CHR leria como «canal desconhecido»): é o que torna o papel necessário e não conveniente. O resolvedor continua a não ler `token_ref`, `waba_id`, `nome`, `nif`, `contacto_negocio_enc`, `entitlements` nem — acrescentado aqui — `conversations`, coisa a coisa; as colunas legíveis são **exactamente** as concedidas (dez, com o `plano` que a `0009` acrescentou). E uma conversa de B não se vê com o contexto de A. Latência, p95 de 40 execuções: **0,805 ms** sem *cache* (limiar 50) e **0,0135 ms** com (limiar 5) numa máquina livre, e **3,329 ms** / **0,0697 ms** com a prova por mutação a correr ao lado — os dois lados do limiar em duas ordens de grandeza de folga. O que estes números valem está em [`../docs/chr.md`](../docs/chr.md) §8: detectam uma resolução que passou a ser de outra ordem de grandeza, e não orçamentam produção (KAM-085) |
| DoD — todos os CA satisfeitos e demonstráveis | **não satisfeito — caixa vazia** | Cinco de oito à letra; 3, 4 e 6 parciais, pelas razões acima. Os três desvios são do **critério** e não da implementação, e os três estão devolvidos a quem os escreveu |
| DoD — 2 revisores (isolamento de tenant, dados pessoais); testes verdes; cobertura ≥ limiar | **não satisfeito — caixa vazia** | **Zero revisores humanos**: uma revisão adversarial é evidência, não é um revisor. Testes verdes: 913 asserções Node (`contracts` 12, `core-ts` 832, `gwy` 44, `worker-canal` 15, `com` 5, `onboarding-web` 5) e as *suites* de base de dados abaixo. Cobertura de `src/chr/` medida **por ficheiro** em `db/tests_chr/`, contra o limiar do estrato `critico` lido de `ci/thresholds.yaml` (90%) — e esse limiar é novo para `*/chr/*`, o que faz desta uma alteração a um **ficheiro de limiares**, que pede dois revisores e por isso não marca esta caixa |
| DoD — documentação actualizada; Conventional Commits | **satisfeito** | [`../docs/chr.md`](../docs/chr.md) (novo), `../docs/ci.md` v1.39 (a *suite* nova e o estrato), dicionário §3.12 e §3.13 (emenda 1.20), `../docs/dividas-documentais.md` linhas 47 a 50. Conventional Commits imposto pelo `tools/githooks/commit-msg`, que recusou a primeira tentativa |
| DoD — isolamento de tenant: `tenant_id` só nasce aqui; RLS em `conversations`; teste cruzado do novo caminho | **satisfeito** | O `tenant_id` nasce no passo 1 e nenhum passo seguinte o recebe de fora: vem sempre do `ChannelContext`. `conversations` tem `ENABLE`, `FORCE` e `tenant_iso`, e a descoberta do X-05 passa de dezasseis tabelas a **dezassete** — com receita de sementes própria, a primeira tabela isolada **sem coluna de texto livre** (o canário vai na chave primária). Teste cruzado do caminho novo: o CHR abre a conversa de B e, com o contexto de A, a contagem é zero. E duas das três FK são **compostas com o `tenant_id`**, o que obrigou a acrescentar `UNIQUE (tenant_id, id)` a `tenant_channels`: sem ela, uma conversa de A podia apontar para um canal de B e nenhum dos dois *gates* o via |
| DoD — idempotência: repetição do mesmo `wamid` não cria 2 conversas nem 2 *jobs*; teste incluído | **satisfeito** | Contra a base: o mesmo evento duas vezes deixa **uma** linha em `conversations`, com o mesmo `conversation_id` nos dois *jobs* — é o `ON CONFLICT (tenant_id, contact_id, channel_id) DO UPDATE` sobre a `UNIQUE` de negócio. A segunda entrada empurra a janela e **não** cria linha nova nem muda o modo. Os dois *jobs* têm o mesmo `wamid`, logo o mesmo `jobId` — que é determinístico por `(tenant_id, wamid)` — e o BullMQ recusa o segundo; o limite dessa janela (`removeOnComplete`, e um *job* em `failed` a bloquear o mesmo `wamid`) está escrito no módulo, achado da revisão adversarial |
| DoD — privacidade: contacto por `contact_id`; sem telefone em *jobs*, logs ou eventos | **satisfeito** | Com um BSUID e um telefone canário: nenhum dos dois aparece no *job* nem na linha de `conversations`, procurados por valor. A `conversations` não tem coluna de texto livre nenhuma — oito colunas, declaradas no inventário fechado, todas `nao` na coluna «pessoal». Os *logs* levam só `outcome`, `error_code` da lista fechada do módulo e `wa_type`; a *allowlist* do KAM-068 recusa `tenant_id`, `conversation_id` e `wamid` por **erro de compilação**. O evento `contact.merged` leva dois `contact_id` e mais nada. **Uma ressalva, dita e não escondida:** o `wamid` vai no *job* porque o critério 6 o exige pelo nome, e o `wamid` leva o número do interlocutor codificado em base64 (INDÍCIO, `../docs/logs.md` §2.1). Por isso não sai para *log* nenhum, não é etiqueta de métrica, e **não** é a chave da fila — o `jobId` é um resumo |
| DoD — custo e observabilidade: `chr_resolve_ms`, `chr_unrouted_total`, `chr_cache_hit_ratio` | **satisfeito** | As três, mais uma quarta: `chr_resolve_total` com etiqueta de desfecho (cinco valores, lista fechada). É o único sítio onde duas recusas ficam visíveis — a do Fluxo B, que o critério 5 manda alertar **sem** quarentena, e a da matriz de estados —, e recusar sem contar é recusar em silêncio. Nenhuma métrica leva identificador (`../docs/seguranca/ameacas_stride.md`, OBS-I): as duas etiquetas são listas fechadas de cinco e dois valores. O `/metrics` do processo serve os dois conjuntos (`inbound_*` e `chr_*`), sem nome repetido |
| DoD — migrações reversíveis: `downgrade` de `conversations` testado | **satisfeito** | Bateria própria (`db/tests/test_conversas_schema.py`), três casos. Com a tabela vazia, desce e sobe — e a `UNIQUE` acrescentada a `tenant_channels` sai, o `FORCE` fica reposto e o `plano` volta a estar fora do alcance do resolvedor. **Com conversas e sem `KAMBA_DOWNGRADE_0009_COPIA`, recusa**, com a contagem na mensagem, e a base fica em `head` sem ter tocado em nada. Com a variável, escreve a cópia lógica das oito colunas de cada conversa — incluindo o modo `humano` e a janela aberta, que é o que torna reverter destrutivo — e desce. O ciclo `upgrade → downgrade → upgrade` completo corre em `test_migracao.py`. **Não há ferramenta de reposição**: a cópia é um `INSERT` por linha, como a `0003` já declarou |

**Como se correu, e o que saiu.** Nesta máquina não há `make`, `node` nem
`pnpm` no `PATH` (`.claude/skills/agentic-engineering/references/evidencia-e-verificacao.md`,
«Como correr a verificação aqui»):

| Verificação | Comando | Resultado |
|---|---|---|
| *gate* 3b (nomes canónicos) | `dict_export --check` e `canon_lint check`, com o Python do Windows | `conforme` — dicionário v1.20, 127 entradas, 9 migrações, 379 instruções, **74** valores de `CHECK` |
| *gate* 1, 2 e 4 (*build*, tipos, testes) | `pnpm run build`, `pnpm -r run typecheck`, `pnpm -r run test` em contentor `node:24.21.0-trixie-slim` | tudo verde; **913** asserções, 0 falhas |
| *gate* 6 (isolamento) | `db/gate_bd.py --suite tests_isolamento` | **78 testes, OK** — com a `conversations` descoberta pelo catálogo e semeada |
| *gate* 8 (migrações) | `db/gate_bd.py --suite tests` | **393 testes, OK** — seis deles novos: as FK da conversa coluna a coluna e os três casos do `downgrade` |
| *gate* 8 (entrada de canal, KAM-013) | `db/gate_bd.py --suite tests_entrada` | **34 testes, OK** — o *worker* de produção monta agora o CHR |
| *gate* 8 (CHR) | `db/gate_bd.py --suite tests_chr` | **6 asserções Python sobre 7 ficheiros de teste Node, OK**; p95 `0,805 ms` / `0,0135 ms` e invalidação `0,722 ms` numa máquina livre; `3,329 ms` / `0,0697 ms` e `1,912 ms` com carga ao lado |
| prova por mutação | `db/mutacoes.py --aplicaveis` e os filtros `chr:` e `revisao 0009` | **294 mutações, 0 não aplicáveis**; **24 novas, as 24 corridas e as 24 apanhadas** — filtro `chr:` 15, filtro `revisao 0009` 7, filtro `revisao 0008: o motivo` 2, com a linha de base verde confirmada em cada suite antes de cada volta. **Duas delas só são apanhadas pelo teste certo depois de uma correcção da revisão adversarial**: as que tiram o `tenant_id` das FK da conversa eram apanhadas por um teste da própria lista de mutações, e agora caem no `TestFkCompostas`. A lista inteira corre de noite (KAM-143) |

#### O que a revisão adversarial encontrou, e os sete defeitos que fechou

Vinte e nove achados. **Sete eram defeitos de código ou de teste e estão
corrigidos; o resto eram afirmações minhas mais confiantes do que a evidência
sustentava.** Por gravidade, e cada um com o que custava:

1. **A perdedora de uma corrida recebia `falhou`.** Duas chamadas concorrentes
   com a mesma origem: a perdedora do `ON CONFLICT` lia a linha em `pendente` —
   a vencedora ainda estava a descarregar — e o módulo devolvia-lhe `falhou` com
   `tentativas: 0`. Quem chama ramifica em `falhou`, que é o que o critério 6
   manda, e **pedia ao cliente que reenviasse enquanto a descarga do outro
   *worker* corria**. O comentário dessa linha dizia, por escrito, «devolver
   `falhou` era mentir», e a linha seguinte devolvia `falhou`: o tipo não tinha
   variante que dissesse «outro está a tratar», pelo que o código não podia
   dizer a verdade. **E o teste da concorrência não o via** — ele afirmava que
   as duas davam o mesmo `assetId` e que uma só armazenava, e as duas asserções
   passam com a outra a reportar uma falha que não houve. O `ResultadoDeMidia`
   ganhou a variante `pendente`, e o teste ganhou a asserção de que **nenhuma**
   das duas pode dizer `falhou`.
2. **Os dois caminhos de desfecho descartavam o resultado do `UPDATE`** — que é
   palavra por palavra o defeito que esta entrega diz ter corrigido no caminho
   do `armazenado`. O `SQL_MARCAR_DESFECHO` leva `AND estado = 'pendente'`: se a
   linha já não o estivesse, o `UPDATE` não casava e o módulo devolvia
   `rejeitado`/`falhou` sobre uma linha que a base diz outra coisa — e no caso
   da falha **avisava o AGR** a pedir reenvio com base num `UPDATE` que não fez
   nada. A assimetria não estava declarada, não tinha teste, e a mutação
   equivalente **não existia**. Agora os dois lêem o resultado, e há uma mutação
   por caminho.
3. **O objecto órfão não era contado.** Quando o `put` tem sucesso e a marcação
   não casa, o comentário prometia «deixar rasto para que o objecto a mais
   apareça antes de alguém o descobrir na factura» — e o `return` acontecia
   **antes** do `contar(media_bytes_total)`. Os bytes que ficaram no
   armazenamento nunca entravam na métrica cuja ajuda escrita diz que «é o que
   sustenta o custo de armazenamento por PME». A factura era, literalmente, o
   primeiro sítio onde ele aparecia.
4. **A `media_download_ms` media a resolução mais a descarga**, e a nota do
   `contrato.ts` justificava a porta ter duas operações dizendo o contrário («só
   a segunda move bytes: separá-las permite medir a latência da descarga **sem a
   resolução**»). No caminho em que o `resolver` estoura, o que ficava gravado
   sob o nome `download_ms` era a latência de uma resolução que nunca
   descarregou nada. **E o teste não o podia ver:** ele afirmava a *presença da
   chave* e não o valor, e o aparato que mediria o valor era morto — a duração
   só era posta a zero, e o avanço do relógio acontecia dentro do `descarregar`,
   que com a Meta em baixo nunca é chamado. Em toda a bateria o *gauge* só podia
   valer 0, e uma implementação que escrevesse zero constante passava. Três
   testes novos, um deles a exigir que os cinco segundos de uma resolução lenta
   **não** entrem na duração.
5. **O `GRANT UPDATE` concedia a `classe` sem chamador** — o critério exacto
   pelo qual a `0011` deixou a sua lista vazia, e que esta revisão cita três
   linhas acima. O módulo nunca escreve a `classe`: ela deriva do `wa_type` na
   reserva. O que o privilégio permitia não é académico: reclassificar um
   objecto muda a coluna de que **depende a política de retenção do KAM-071**, e
   um áudio reclassificado como imagem deixa de ter prazo e fica para sempre.
   São **seis** colunas e não sete.
6. **Duas mutações morriam por acidente, e uma era imortal quanto à propriedade
   que dizia medir.** A do `armazenado_ck` ancorava numa linha *dentro* do
   `CHECK`, e apagá-la deixava SQL que não analisa: o `alembic upgrade` falhava,
   a *suite* ficava vermelha, e ela contava como apanhada **sem nunca ter criado
   a tabela** — media o PostgreSQL e não o teste. A do `SQL_POR_ASSET` morria
   porque a base falsa despacha por `includes` de cadeias e o texto mutado
   deixava de casar o despacho; pela propriedade era inobservável, porque a RLS
   esconde a linha na base verdadeira e a base falsa impõe o *tenant* em
   JavaScript. A primeira ganhou âncora nova; a segunda **saiu**, com a razão
   escrita.
7. **A semente do X-03 declarava um valor que a base recusaria.** A coluna
   alterável era o `estado` com o valor `armazenado`, e um
   `SET estado='armazenado'` sozinho sobre a linha semeada dá `23514` — a
   `media_assets_armazenado_ck` exige a chave, o tamanho e o resumo na mesma
   instrução. Hoje não rebentava **por sorte de forma**: o teste cruzado não
   casa linha nenhuma (a RLS) e o próprio faz `SET estado = estado`. Qualquer
   teste futuro que o aplicasse recebia uma violação de `CHECK` onde esperava
   uma contagem.

**E a lista de grupos do *gate* 8 tinha três em falta**, dois deles do único
ficheiro que fala com o PostgreSQL — podiam desaparecer sem o *gate* notar, que
é exactamente o que o cabeçalho dele diz existir para impedir. A divisão
declarada («os cinco últimos são do ensaio de base») também estava errada: três
desses cinco são do ficheiro que corre sem base nenhuma.

**Dois testes saíram da lista de obrigatórios**, e é a mesma classe de defeito
que esta entrega já tinha reconhecido uma vez: fazem o `UPDATE` **à mão no
teste**, com o predicado escrito nele. Um deles dizia no comentário «aqui a
tentativa vem de uma instrução com a forma da que o módulo emite» — e a forma
não é nenhuma das que o módulo emite. Exigi-los pelo nome dava a impressão de
que a propriedade estava presa; quem a prende é o teste da janela.

#### As afirmações minhas que eram falsas

Ficam ditas em vez de corrigidas em silêncio, porque é o que esta *skill* pede:

- **«É a tabela com mais FK do esquema»** — falso, e afirmado em **cinco**
  sítios. A `outbound_messages` da `0010` tem quatro; esta tem três. Num deles a
  frase estava imediatamente acima do comentário que a contradizia.
- **«A análise de malware e de conteúdo activo não consta de
  `../docs/tecnica/`»** — falso: o `08` §4.2 tem, na linha do MED da matriz
  STRIDE, «Ficheiro malicioso → tipo/tamanho/**antivírus**, nunca executar» e
  «Parsers (imagem/PDF) → processo sem privilégios, sem rede». O que o KAM-065
  deve é o modelo de ameaças, não a primeira menção do controlo. A frase vem dos
  *Detalhes Técnicos* do ticket e eu propaguei-a como facto em três sítios
  novos.
- **«Dez destes nomes não existiam em sítio nenhum — nem em código»** — a
  enumeração tinha **doze** itens, e dois deles (`classe` e `sha256`) existem em
  código desde o KAM-011, o que a própria secção diz três parágrafos abaixo. Era
  verdade sobre o canon e falso sobre o código.
- **«Cobertura entre 89% e 100% em seis módulos»** — aritmeticamente impossível
  (ver a tabela de execução).
- **«Uma escrita na linha de B não acontece, nem como dono»** — o ensaio corre
  como `kamba_app`, que não é dono. O `FORCE` está provado, pela bateria do
  esquema.
- **«Registado nas dívidas»**, sobre o EXIF/GPS — não estava; estava só no
  dicionário. Agora é a dívida **64**, e os dois documentos deixaram de
  discordar sobre o número de donos.
- **E o `PRIMARY KEY` voltou a entrar em *backticks*** — na frase que narra a
  lição de o ter feito. O `dict_export` colhe os identificadores entre crases
  das notas, pelo que a menção repunha `PRIMARY` e `KEY` no conjunto de nomes
  conhecidos; e dois outros *spans* da mesma secção colhiam `a`, `z`, `z0`, `_`
  e `media_`. É a terceira vez que esta armadilha morde neste projecto.

#### O que o ticket pede e não está feito, e agora está declarado

Cinco divergências novas no §3.16 (7 a 11) e quatro linhas novas no §11 do
`../docs/media.md`: o `sticker` tratado como mídia contra o `01` §5.4, que manda
**ignorá-lo**; o limite de tamanho que só morde depois de materializar os bytes
quando a Meta não anuncia o tamanho; a repetição de um rejeitado a responder
sempre a frase do tipo errado; a **deduplicação por conteúdo**, que é opcional,
não está feita e não estava mencionada em sítio nenhum — e o
`test_media_schema.py` argumentava a partir dela como se existisse; e o «Teste
Requerido» de integração com a Graph falsa, que não se cumpre por decisão
escrita em quatro sítios mas que não estava na tabela de verificação.

#### Decisões tomadas neste ticket

- **O `tenant_id` nasce no passo 1 e nenhum passo seguinte o recebe de fora.**
  É o que torna a frase do `../docs/tecnica/01` §7.2 verificável e não uma
  intenção.
- **Três ligações, três papéis.** `kamba_resolver` para a resolução e para a
  guarda de arranque, `kamba_identity` para o contacto, `kamba_app` para a
  conversa. Uma ligação de `kamba_batch` resolvia os três passos e era o que o
  ADR-015 recusa.
- **A janela de 24 h vive em `conversations`**, e não em `contacts` como o
  `../docs/tecnica/01` §6.2 escreve: a janela da Meta é por par (número do
  negócio, número do cliente), e uma janela por contacto não distingue dois
  canais do mesmo tenant.
- **Dois valores novos entraram na revisão `0008` e não na `0009`.** O *gate* 3b
  lê o AST de cada revisão isoladamente: alargar um domínio numa revisão
  posterior deixa a que cria o `CHECK` vermelha. O custo é uma base já na `0008`
  não ganhar os valores sem voltar a aplicar as migrações.
- **A recusa do Fluxo B não deixa linha de quarentena**, porque o critério pede
  «0 *jobs*, alerta». O alerta é a métrica e o registo.
- **Um `echo` vai ao dono sem contacto nem conversa**: o campo que traz o
  destinatário é NÃO VERIFICADO (`../docs/tecnica/evidencia/E1` §5).
- **A verificação do modo é antes da matriz de estados.** Uma conversa em modo
  `humano` não vai ao AGR mesmo num tenant `ativo`.
- **O `jobId` da fila do AGR é um resumo e não o `wamid`**, que leva o número do
  interlocutor em base64.
- **O `contact.merged` é emitido por quem chama**, depois do `COMMIT` da fusão, e
  com o payload mapeado para o contrato publicado — que usa outros nomes e a
  leitura invertida.

#### O que fica por decidir

Quatro decisões que este ticket tomou para poder avançar e que **não são dele**.
Estão implementadas como *proposta*; inverter qualquer uma é uma revisão nova.
Estão todas em [`../docs/chr.md`](../docs/chr.md) §10, e as quatro divergências
documentais que as sustentam em `../docs/dividas-documentais.md`, linhas 47 a 50.

1. **O `persona` sai do `ChannelContext`**, porque `contacts.papel` — de onde
   viria — **não existe** em revisão nenhuma.
2. **O caminho do contrato `agent_invocation`**, que o *gate* 3b não deixa ser o
   da letra do critério 6.
3. **A convergência de identidade**, que o algoritmo do §6.3 só faz com uma
   mensagem que traga os dois identificadores (critério 4).
4. **O «uma vez por contacto/24 h» da mensagem estática**, que é de quem envia
   (KAM-015) e cuja coluna de contagem não existe neste DDL.

E uma consequência de arranque que não é decisão deste ticket mas passa a
afectá-lo: o `worker-canal` **deixa de arrancar em `KAMBA_ENV=prod`**, porque o
CHR monta o módulo de identidade e o KAM-008 recusa um `KeyProvider` de ambiente
em `prod` enquanto não houver um de cofre — que nenhum ticket constrói
(decisão 2 do KAM-008).

### Detalhes Técnicos

- **Componentes:** CHR (em `services/worker-canal`), com `identity` de KAM-008 e `tenantGate` de KAM-009.
- **Tabela criada aqui (o backlog não a atribui a nenhum ticket):**
```sql
CREATE TABLE platform.conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES platform.tenants(id),
  contact_id uuid NOT NULL REFERENCES platform.contacts(id), channel_id uuid NOT NULL REFERENCES platform.tenant_channels(id),
  mode text NOT NULL DEFAULT 'bot' CHECK (mode IN ('bot','dono','humano','pausada')),
  last_inbound_at timestamptz, window_expires_at timestamptz, last_human_activity_at timestamptz,
  UNIQUE (tenant_id, contact_id, channel_id));
```
  RLS via `enable_tenant_rls`. A janela vive aqui (não em `contacts`, divergindo de `../docs/tecnica/01` §6.2, pois `contacts` segue ADR-010/KAM-008). A migração regista o gancho `onContactMerge` para repontar conversas.
- **Resolução de contacto:** algoritmo de `../docs/tecnica/01` §6.3 (BSUID → telefone com `kid` actual e anterior → criar/fundir). O telefone em claro nunca sai do ponto de envio.
- **Fora de âmbito:** transições de modo (KAM-018), consentimento (KAM-022), envio (KAM-015).

### Testes Requeridos

- Unit: matriz de estados (6 × entradas); montagem do contrato do *job*.
- Integração: canal desconhecido, fusão, cache e invalidação, Fluxo B recusado.
- Isolamento: `phone_number_id` cruzado; `kamba_resolver` sem acesso a `orders`; teste X-03 sobre `conversations`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (isolamento de tenant, dados pessoais); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada; Conventional Commits.
- [x] **Isolamento de tenant** — `tenant_id` só nasce aqui; RLS em `conversations`; teste cruzado do novo caminho.
- [x] **Idempotência** — repetição do mesmo `wamid` não cria 2 conversas nem 2 *jobs*; teste incluído.
- [x] **Privacidade** — contacto por `contact_id`; sem telefone em *jobs*, logs ou eventos.
- [x] **Custo e observabilidade** — `chr_resolve_ms`, `chr_unrouted_total`, `chr_cache_hit_ratio`.
- [x] **Migrações reversíveis** — `downgrade` de `conversations` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-014 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-014) e docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§6.3, §7, §10.2).
Objectivo: CHR (phone_number_id → tenant, canal, contacto, modo da conversa).
- resolve() com cache de 60 s e invalidação por channel.updated; usa o papel kamba_resolver antes de haver contexto.
- Matriz de estados do tenant/canal (§7.2); recusa Fluxo B no Piloto (KAMBA_FASE=piloto).
- Resolve contacto com a identidade do KAM-008; cria conversations (DDL do ticket) com RLS.
- Entrega ao AGR um job conforme o contrato agent_invocation, sem telefone; mensagens em modo dono/humano
  não vão ao AGR. Desconhecidos vão para unrouted_events.
Não expandas escopo: transições de modo são KAM-018; consentimento KAM-022; envio KAM-015.
Testes: matriz de estados, fusão idempotente, Fluxo B, isolamento. Abre PR com o template do §7.
```

---

## KAM-015 — Outbound: envio, janela de 24 h, templates utility e custo de mensagens

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-013, KAM-014, KAM-004, KAM-024 |
| Bloqueia | KAM-022, KAM-023, KAM-031, KAM-048, KAM-054, KAM-058, KAM-084, KAM-118, KAM-122, KAM-123 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§8, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §5, §7), `../docs/tecnica/08_Seguranca_Conformidade.md` (§7.3), ADR-007, ADR-009, ADR-013 |

### Contexto

Factos CONFIRMADOS (E1): desde 2026-10-01 as *service messages* são pagas a partir da 1.001.ª por número e mês (Rest of Africa, 0,004 USD) e as *utility* dentro da janela também; mensagens livres só dentro da janela de 24 h, templates para iniciar conversa; cobrança por mensagem **entregue**; botões ≤ 3, listas ≤ 10 linhas; 130429 ao exceder o débito (80 mps por omissão; 20 mps fixos em coexistência). Logo: notificar com **mensagem livre** quando a janela está aberta, template *utility* só com janela fechada, nenhum *marketing* no Piloto e uma mensagem por turno quando possível (verbosidade é custo). Em coexistência, mensagens enviadas pela app não abrem janelas nem afectam preço da Cloud API.

### Objectivo

Implementar o `ChannelAdapter` de saída: decisão de envio por estado da janela, fila com ordem por conversa, registo e ciclo de vida de templates, ingestão monótona de estados e `pricing`, *rate limiting* e metering de custo por tenant.

### Critérios de Aceitação

- [x] `send` com janela aberta usa mensagem livre/interactiva (categoria *service*); com janela fechada e conteúdo livre devolve `WINDOW_CLOSED` **sem** chamada HTTP; com janela fechada e template `APPROVED` envia o template.
- [x] Idempotência: 2 chamadas com a mesma `idempotency_key` produzem 1 chamada à API (servidor falso conta) e 1 linha em `outbound_messages` (`UNIQUE`).
- [x] Estados monótonos: `delivered` seguido de `sent` mantém `delivered`; `failed` é terminal; duplicados do mesmo estado são *no-op*.
- [ ] `pricing` dos estados (`billable`, `pricing_model`, `type`, `category`) é guardado por mensagem; um estado com categoria *service* acima do *free tier* incrementa `meta_cost_usd_total{tenant}` em 0,004 (taxas em `config/meta_rates.yaml`, efectivas 2026-10-01, com data de revisão trimestral).
- [x] *Token bucket* por `phone_number_id` (15 mps em coexistência, proposta com folga sobre os 20 mps CONFIRMADOS) e por par tenant–contacto (1 msg/s e 30/min, proposta): 100 envios em fila nunca excedem 15/s em nenhuma janela de 1 s medida no servidor falso e drenam em ≥ 6,6 s.
- [ ] Resposta 130429 do servidor falso 3× seguida de 200: backoff exponencial com *jitter*, 3 tentativas, 1 mensagem entregue, 0 duplicados. Meta indisponível: fila com *backoff* e ordem por conversa; mensagens fora da janela expiram em 24 h com aviso ao dono.
- [x] Validação do construtor: 4 botões ou 11 linhas de lista falham antes de qualquer chamada; templates só nas categorias `utility` e `authentication`; `marketing` é recusado no Piloto.
- [ ] Gancho `PreSendGuard` chamado sob o *lock* da conversa antes de cada envio do bot (implementado em KAM-018); sem ele, o envio do bot falha em ambiente de CI.
- [x] Recategorização de um template para *marketing* (`template_category_update`) bloqueia o seu uso e alerta; o destinatário é endereçado por BSUID (`recipient`) quando existe, senão por telefone; o telefone nunca aparece em logs.

### Verificação dos Critérios de Aceitação

Entregue no PR `albinoJimy/kamba-plataforma#32`, ramo
`feature/KAM-015-outbound-envio`.
**Dez caixas marcadas, oito vazias** (18 = 10 + 8) — cada uma com uma linha
aqui. Os números reproduzem-se com `make ci-3b`, `make ci-4`, `make ci-6` e
`make ci-8`; o desenho está em [`../docs/outbound.md`](../docs/outbound.md).

**O padrão desta entrega, dito antes da tabela: cada defeito encontrado era
algo que eu tinha verificado à mão e que falhou quando uma máquina verificou.**
Foram nove, e nenhum foi previsto:

1. **O leitor de YAML recusou `0.004`** («só converte inteiros»), e estava certo:
   o §2 do dicionário proíbe vírgula flutuante em dinheiro. As tarifas passaram
   a micro-dólares inteiros. Somar `0.004` mil vezes em `float64` não dá `4.00`,
   e um acumulador de custo com deriva não se reconcilia contra uma factura.
2. **O *gate* 3b recusou `CHECK (quality IS NULL OR quality IN (...))`**: em SQL
   um `CHECK` que avalie a NULL **passa**, pelo que a forma simples já admite
   nulos e a longa é ruído que o *gate* lê como domínio mal escrito.
3. **O meu próprio teste do critério 5 recusou o balde cheio**: 16 mensagens
   numa janela de 1 s. A aritmética do próprio critério («≥ 6,6 s» = 100/15)
   prova qual das duas leituras é a pretendida.
4. **E recusou os dois baldes vazios**: 100 s para 100 contactos diferentes, num
   caso que devia dar 6,7 s. O do par nasce cheio, o do canal vazio.
5. **A *allowlist* do registo recusou quatro campos** (`contact_id`,
   `id_opaco`, `motivo`, `template`) e obrigou o `error_code` a ser **texto**.
   O motivo passou para o `outcome`, que é onde ele é.
6. **O `scan_secrets` recusou o *commit* duas vezes** — a segunda porque eu
   tinha citado o valor antigo no comentário que explicava a primeira correcção.
7. **O `set_config('app.tenant_id', $1, true)` solto não punha contexto nenhum.**
   O terceiro argumento a `true` é «local à transacção», e fora de um `BEGIN`
   explícito cada instrução é a sua própria transacção: a definição morria antes
   da seguinte, e com RLS `FORCE` o `kamba_app` via zero linhas. A *suite* caiu
   de **421 s** (tempo esgotado) para **33 s**.
8. **A `outbound_messages_entrega_ck` matava um `failed` depois de um
   `delivered`.** Admitia `delivered_at` só em `delivered` e `read`, e o
   `estados.ts` deixa sair de qualquer não-terminal para um terminal.
9. **O adapter dormia uma vez e enviava sem ficha.** Só apareceu ao montar o
   critério 5 onde ele manda — na porta da Meta e não na função pura: os dois
   primeiros envios de um canal saíam no mesmo instante e a janela de 1 s que os
   apanha via **dezasseis**. Provar a regra numa função pura não prova que quem
   a chama obedece.

**E a revisão adversarial não aprovou a primeira versão.** Nove achados, os nove
corrigidos, e o que justifica o veredicto é o primeiro: **o custo duplicava sob
concorrência.** O `ingerir` lia o estado actual **fora** da transacção do
`UPDATE` e calculava o custo a partir dessa leitura; com `delivered` e `read` a
chegarem juntos — que é o par que a Meta produz, porque não garante ordem nos
`statuses` —, os dois `UPDATE` casavam cada um com a sua lista de origens
permitidas e os dois somavam 4 000. Oito mil micro-dólares para uma mensagem
entregue uma vez, com o `SQL_CUSTO_DO_TENANT` a dizer quatro mil: a reconciliação
em que o DoD «Custo e observabilidade» se apoia deixava de fechar, e o painel
mentia **por cima**. **E o meu teste da propriedade não podia apanhá-lo:**
escolhia o par `delivered` + `sent`, e um `sent` depois de `sent` é *no-op* por
construção — custava zero quaisquer que fossem os defeitos. O `SQL_AVANCAR_ESTADO`
passa a devolver o `estado_antes` sob `FOR UPDATE`, e é dele que o custo sai.

Os outros oito, por ordem de gravidade: o `error_code: "-1"` do
`CODIGO_SEM_CODIGO` **não cabe na gramática** da *allowlist*, pelo que um
*timeout* da Meta fazia o `Logger` estrito levantar em vez de devolver uma
recusa com código; o `paraMostrar` perdia o transporte e apresentava 996 000
micro-dólares como `"0.100"` em vez de `"1.00"`; um `statuses` que chegasse antes
de o nosso `wamid` ter comprometido era descartado **em silêncio**, deixando a
linha em `sent` para sempre e o custo nunca contado; a asserção que dizia provar
«a RLS também protege a consulta» pedia o custo de B com o contexto de B, e esse
zero vinha do `WHERE tenant_id = $1` e não de política nenhuma; um teste
chamava-se «nenhum tecto o usa» sobre o `cheio` que o tecto do par usa; o mapa
por par crescia **sem tecto**, com um `esquecer` que nunca era chamado em
produção; o `RATE_LIMITED` era um valor **morto** na lista fechada de dez
motivos; e quatro comentários afirmavam coisas que o código já não fazia, entre
eles a contagem de colunas do §8.4 no dicionário (treze e não doze).

| CA | Estado | Evidência |
|---|---|---|
| 1 — janela aberta → mensagem livre *service*; fechada com conteúdo livre → `WINDOW_CLOSED` **sem** chamada HTTP; fechada com template `approved` → o template | **satisfeito** | Os três ramos, um a um, em `tests/outbound.decisao.test.ts`, e o do meio com o contador de chamadas a **zero** em `tests/outbound.adapter.test.ts`: com a janela fechada o adapter lê a janela e **para** — a sequência de consultas é exactamente `["janela"]`, não enfileira e não chama. Com a janela aberta sai `service` e **não** template, o que é a linha do §8.2 e é custo: a `utility` dentro da janela passou a ser paga em 2026-10-01 (`E1` §1). O limite da janela é **estrito** — expirar agora é estar fechada —, e `window_expires_at` nulo (conversa que nunca recebeu nada) conta como fechada. Cada um dos **quatro** estados de template que não são `approved` tem o seu caso, porque «não aprovado» é quatro coisas |
| 2 — idempotência: 2 chamadas com a mesma chave dão 1 chamada à API (servidor falso conta) e 1 linha | **satisfeito** | Contra a base **e** com o `GraphFalso` do KAM-024 a contar: duas chamadas com a mesma `idempotency_key` deixam **uma** linha e fazem **uma** chamada HTTP. A propriedade é da base e não do código — o `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id` devolve **vazio** na segunda, e é disso que o adapter conclui «não chamar»; uma verificação prévia em código perdia a corrida entre dois processos. A linha nasce **antes** da rede, e a ordem é afirmada pela sequência de consultas (`enfileirar` antes de `marcar_enviada`): ao contrário, uma falha entre o envio e a escrita deixava uma mensagem entregue sem linha, e a repetição mandava-a outra vez. E a segunda chamada devolve o `wamid` da primeira, não `null`: quem repete tem de poder correlacionar. **A unicidade é por *tenant***: a mesma chave em dois *tenants* dá **duas** linhas, que é a primeira divergência da emenda 1.21 face ao `../docs/tecnica/01` §8.4 — com unicidade global o segundo *tenant* era deduplicado em silêncio |
| 3 — estados monótonos: `delivered` depois de `sent` mantém `delivered`; `failed` é terminal; duplicados são *no-op* | **satisfeito** | As três frases, as três testadas, mais a propriedade que nenhuma delas diz: **a entrega conta-se ao *atravessar* o `delivered`, não ao chegar a ele**. A Meta entrega os `statuses` sem ordem garantida (`E1` §5), logo um `read` pode chegar antes do `delivered` — com um `=== "delivered"` essa mensagem **nunca** somava custo, e com uma comparação ingénua somava duas vezes. Os terminais **não** se comparam por índice: de um não-terminal vai-se para um terminal e isso avança, mas `failed` → `suppressed_by_human` não. Contra a base, com **duas ligações** em paralelo e com o par `delivered` + `read` — que é o que a Meta produz e o único que pode duplicar: o estado final é o maior dos dois, as duas ingestões avançam, e o custo conta **uma** vez. A monotonia está no predicado (`antes.state = ANY($4)`) e é a base que serializa; com uma ligação só, o teste provava que o JavaScript é sequencial. **O custo sai do `estado_antes` que o `UPDATE` devolve sob `FOR UPDATE`**, e não de uma leitura anterior — era exactamente aí que ele duplicava, e a primeira versão deste teste usava o par `delivered` + `sent`, que não podia apanhá-lo. E o `delivered_at` **sobrevive** ao `failed`: a entrega aconteceu, o custo já foi contado, e apagar o instante era destruir a linha de auditoria que reconcilia a factura |
| 4 — `pricing` guardado por mensagem; um *service* acima do *free tier* incrementa `meta_cost_usd_total{tenant}` em 0,004 (tarifas em `config/meta_rates.yaml`) | **parcial — caixa vazia** | **Tudo se cumpre excepto a etiqueta.** O `pricing` fica guardado por mensagem, em `jsonb`, e é dele que o `SQL_CUSTO_DO_TENANT` tira o custo por *tenant* — provado contra a base, com **o custo de A pedido com o contexto de B a dar zero** (a RLS também protege a consulta), e a mesma consulta com o contexto de A a dar mais de zero — sem este segundo lado, o zero podia ser uma consulta que não funciona, e a primeira versão deste teste pedia o custo de **B** com o contexto de B, cujo zero vinha do `WHERE tenant_id = $1` e não de política nenhuma. Um *service* acima do *free tier* soma **4 000 micro-dólares**, que são 0,004 USD, e dentro do contador soma zero; uma `utility` soma **mesmo dentro do contador**, porque o «grátis até 1.000» é das *service messages* (`E1` §1). O `config/meta_rates.yaml` declara as quatro tarifas, a zona, a data de efeito e o estado — `CONFIRMADO` para as tarifas, **proposta** para a cadência de revisão, porque o `../docs/tecnica/01` §8.4 diz de si mesmo «calendário a confirmar» e marcar as duas da mesma maneira era promover um INDÍCIO a facto. A paridade YAML↔TypeScript é um teste, e é o único sítio onde as duas fontes se confrontam. **O que não se cumpre:** a etiqueta `{tenant}`. As quatro bibliotecas de métricas deste repositório recusam **por gramática** uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID com hífenes — **a chamada levanta**. A razão é o `OBS-I` de `../docs/seguranca/ameacas_stride.md` e o X-11 do *gate* 6: uma etiqueta é tão legível como uma linha de registo. O por-*tenant* sai da consulta, que é o que o §16 do doc 01 já aponta. Registado na emenda 1.21 como a terceira divergência assumida |
| 5 — *token bucket* por `phone_number_id` (15 mps) e por par (1 mps, 30/min): 100 envios nunca excedem 15/s em nenhuma janela de 1 s **medida no servidor falso** e drenam em ≥ 6,6 s | **satisfeito** | Medido **na porta da Meta, com o `GraphFalso` a atender**, com relógio virtual que avança pelo que se dormiu: cem envios a cem contactos diferentes, cem chamadas atendidas (`graph.envios === 100`), cem linhas, **nenhuma janela de 1 s com mais de 15** — e todas as janelas, não só as alinhadas ao segundo — e drenagem de **6 700 ms** contra os ≥ 6 600 do critério. Montar isto onde o critério manda apanhou o defeito 9 da lista acima; com o adapter a dormir uma vez, a janela via **dezasseis** (confirmado por mutação). O balde do canal nasce **vazio** e o do par **cheio**, e a assimetria é o que cada um protege: 100/15 = 6,67 s só se obtém com o do canal vazio (cheio seriam 85/15 = 5,67 s, e o critério ficava por cumprir), e com o do par vazio **toda** a primeira mensagem a cada contacto esperava um segundo — 100 s para 100 contactos, medido. Os três tectos verificam-se **sem consumir**: consumir o do canal e descobrir depois que o par está cheio gastava 6,7% do débito por cada recusa de par. O mapa por par tem **tecto** (dez mil, com despejo do mais antigo, como a *cache* do CHR): sem ele, um processo de longa duração acumulava um balde e uma janela por cada par que vira, e o `esquecer` que a nota da classe citava nunca era chamado em produção. E uma espera acima de **5 s** é recusada com `RATE_LIMITED` em vez de dormida — o tecto por minuto do par pode pedir 60 s, e dormir um minuto dentro de uma chamada de envio prende o chamador, o *job* e a ligação à base por causa de um tecto nosso; era também o que fazia do `RATE_LIMITED` um valor morto na lista fechada de dez motivos. Os dois valores do par são **proposta e a calibrar**: o *pair rate limit* real da Meta é NÃO VERIFICADO (`E1` §5) |
| 6 — `130429` 3× seguida de 200: *backoff* exponencial com *jitter*, 3 tentativas, 1 mensagem entregue, 0 duplicados; Meta indisponível: fila com *backoff* e ordem por conversa; mensagens fora da janela expiram em 24 h com aviso ao dono | **parcial — caixa vazia** | **A primeira frase cumpre-se à letra**, e a letra obrigou a uma leitura: «3 tentativas» são três **repetições**, logo quatro chamadas — com três chamadas no total os três `130429` esgotam-nas e o `200` nunca chega, e a frase contradiz-se. A primeira versão tinha três chamadas, e isso deixava a caixa por marcar com o código a dizer que estava feita. A sequência exacta do critério é um teste: `429, 429, 429, 200` → **1 entregue, 0 duplicados** (uma linha, em `sent`), **quatro** chamadas, três esperas de 125, 250 e 500 ms. O `131049` **não** repete: **uma** chamada e nenhuma espera. O `Retry-After` **manda** sobre o exponencial. O *jitter* é observável — o mesmo guião com dois aleatórios diferentes dá esperas diferentes — e é `[base/2, base]` e não `[0, base]`, porque um atraso que possa ser zero não é atraso. Ramifica pelo `error.code` e **nunca** pelo estado HTTP: nenhuma fonte deste repositório dá o estado HTTP do `130429`, e um cliente que ramifique por `status === 429` passa os testes contra o servidor falso e nunca repete em produção. **O que não se cumpre:** não há **fila** (a ordem por conversa é do *worker*, e o `conversation_id` está na tabela para a suportar, mas nenhuma fila é entregue aqui), e a expiração em 24 h **com aviso ao dono** é o KAM-115, que os *Detalhes Técnicos* deste ticket não nomeiam mas o `../docs/outbound.md` §10 nomeia. A caixa fica vazia |
| 7 — 4 botões ou 11 linhas falham antes de qualquer chamada; templates só `utility` e `authentication`; `marketing` recusado no Piloto | **satisfeito** | A verificação de forma é o **primeiro** passo, e a prova de que está primeiro é que recusa **com a janela aberta**: se olhasse para a janela antes, um corpo com quatro botões e janela aberta passava, e o critério ficava por cumprir sem nenhum teste o dizer. No adapter, **zero** consultas — nem a janela se lê —, porque uma leitura é tão desperdiçada como um POST. Três botões passam, quatro falham; dez linhas passam, onze falham. O `marketing` é recusado **antes** da rede, e a lista de categorias do Piloto é que decide; o `authentication` passa na matriz (está no domínio e no Piloto), e o que o torna inviável na prática é exigir telefone — decisão de quem envia, não da matriz |
| 8 — `PreSendGuard` chamado sob o *lock* da conversa antes de cada envio do bot; sem ele, o envio do bot falha em CI | **parcial — caixa vazia** | **A segunda metade cumpre-se e é afirmada nos dois ambientes.** Sem guarda e com `KAMBA_ENV=ci`, o envio do bot **levanta** `SemGuardaError` e não chama a Meta; fora de CI recusa com `GUARD_REFUSED`, registra `outcome=sem_guarda` e também não chama — a diferença é deliberada, porque um processo de produção que levante a cada envio é pior do que um que recuse e registe, e **nenhum dos dois envia**, que é o que o critério protege. Um envio que não é do bot passa sem guarda; um guarda que diz não recusa sem chamada. **O que não se cumpre:** «sob o *lock* da conversa». **Não há *lock*** — o `conversations.mode` e as suas transições são o KAM-018, que o próprio critério nomeia como implementador do guarda, e `kamba_app` não tem sequer `UPDATE (mode)` (revisão `0009`). Chamar a guarda sem *lock* é o que este ticket pode entregar; a exclusão mútua pede a coluna e as transições que ainda não existem. A caixa fica vazia e a decisão devolve-se a quem escreveu o critério |
| 9 — recategorização para *marketing* bloqueia o uso e alerta; destinatário por BSUID quando existe, senão por telefone; o telefone nunca em *logs* | **satisfeito** | As três. O bloqueio escreve a categoria nova **e** o `bloqueado_em` na mesma instrução — separar deixava uma janela em que o template está em `marketing` e não está bloqueado, e é nessa janela que um envio passava — e é **idempotente**, porque a Meta reenvia o *webhook*: a segunda vez não volta a bloquear nem a alertar, e preserva o **primeiro** instante, que é o que se audita. Recategorizar para `utility` **não** bloqueia e nem chega à base. Um template bloqueado deixa de sair, e o `bloqueado_em` tem precedência sobre o `status`: a Meta pode manter `approved` e mudar a categoria, e é exactamente nesse caso que o bloqueio tem de morder. O destinatário é `recipient` (BSUID) quando existe e `to` (telefone) só na falta dele, e entra por **porta** — só `kamba_identity` lê `contact_endpoints` e o adapter corre como `kamba_app`. Sem nenhum dos dois, recusa `NO_RECIPIENT`, marca a linha `failed` e não chama. O telefone não vai a registo nenhum: a *allowlist* do KAM-068 recusa um campo que não seja dela, por erro de compilação |
| DoD — todos os CA satisfeitos e demonstráveis | **não satisfeito — caixa vazia** | Seis de nove à letra; 4, 6 e 8 parciais. Os três desvios são do **critério** e não da implementação — a etiqueta que as bibliotecas de métricas recusam, a fila e o aviso ao dono que têm outro dono, e o *lock* que precisa de uma coluna que este ticket não cria —, e os três estão devolvidos a quem os escreveu |
| DoD — 2 revisores (custo e dados pessoais); testes verdes; cobertura ≥ limiar | **não satisfeito — caixa vazia** | **Zero revisores humanos**: uma revisão adversarial é evidência, não é um revisor. Testes verdes: **134** testes nos quatro ficheiros da saída no *gate* 4, mais as *suites* de base de dados abaixo. Cobertura de `src/outbound/` medida **por ficheiro** em `db/tests_outbound/`, contra o limiar do estrato `restante` (75%) lido de `ci/thresholds.yaml`, e **não** do `critico`: o DoD diz «cobertura ≥ limiar» sem número, e alterar `ci/thresholds.yaml` pede dois revisores — não se alarga um ficheiro de limiares para marcar uma caixa que não pede o número |
| DoD — documentação actualizada (`docs/outbound.md`); tarifas revistas à data da evidência; Conventional Commits | **satisfeito** | [`../docs/outbound.md`](../docs/outbound.md) (novo, onze secções), `../docs/ci.md` v1.41 (a *suite* nova, com o que só ela prova), dicionário §3.14 (emenda 1.21, com as três divergências) e `../docs/dividas-documentais.md`. As tarifas são as de **2026-10-01** (`E1` §1), com a zona `rest_of_africa` declarada e o estado de cada afirmação separado: tarifas `CONFIRMADO`, cadência de revisão **proposta**. Conventional Commits imposto pelo `tools/githooks/commit-msg` |
| DoD — isolamento de tenant: `outbound_messages` e `message_templates` com RLS e teste cruzado | **satisfeito** | As duas têm `ENABLE`, `FORCE` e a política `tenant_iso`, e a descoberta do X-05 passa de dezassete tabelas a **dezanove**, com receita de sementes própria para cada uma. Teste cruzado, contra a base: com o contexto de A, as linhas de B **não aparecem** e uma escrita na linha de B **não acontece** — com `FORCE`, vale até para o dono. Os templates de A não se vêem com o contexto de B. E três das quatro FK de `outbound_messages` são **compostas com o `tenant_id`** (afirmado coluna a coluna, e a contagem também), o que obrigou a acrescentar `UNIQUE (tenant_id, id)` a `conversations`: sem ela, uma mensagem de A podia apontar para uma conversa de B, e nem a RLS de `outbound_messages` (a linha é de A) nem a de `conversations` (uma FK é verificada por dentro) o apanhavam |
| DoD — idempotência: chave por envio, teste de repetição | **satisfeito** | Ver o CA 2: a chave é `UNIQUE (tenant_id, idempotency_key)`, a repetição está testada contra a base com o servidor falso a contar as chamadas, e a linha nasce antes da rede |
| DoD — números só de *tools*: o adapter envia texto já validado; não gera preços nem totais | **satisfeito** | O adapter não formata nenhum número para o cliente: o `Corpo` chega pronto, e as quatro formas (texto, botões, lista, template) são transportadas sem interpretação — o `formaInvalida` conta botões e linhas e não lê conteúdo. O único número que o módulo calcula é o **custo**, que é interno, em micro-dólares inteiros, e nunca sai numa mensagem; o `paraMostrar` converte uma vez, no fim, para painel — e **arredonda antes de dividir**, porque a primeira versão perdia o transporte e dava `"0.100"` para 996 000 micro-dólares (249 entregas), o que é um número errado num painel de custo, que é pior do que nenhum porque ninguém o questiona. Uma categoria de `pricing` desconhecida custa **zero** e **faz barulho**, em vez de inventar um número: inventar para uma categoria nova da Meta era o defeito pior dos dois |
| DoD — privacidade: destinatário por BSUID quando existe; telefone nunca em *logs* | **satisfeito** | BSUID quando existe (CA 9). O que vai a registo é inspeccionado com o `Logger` **real** em modo estrito e um destino que captura: no envio, `outcome=enviada`, `tenant_id` e `msg_id` — e o `msg_id` é o `idOpaco` do §3.10 (`m_` + 32 hexadecimais do SHA-256), conferido contra o padrão. **O `wamid` não vai em claro**, procurado por valor em todas as linhas escritas, e o `contact_id` também não: o `wamid` leva o número do interlocutor em base64 (`../docs/logs.md` §2.1). O motivo de uma recusa vai no `outcome` e não num campo próprio, porque o motivo **é** o desfecho e dois campos para a mesma coisa divergiam; o `error_code` vai como **texto**, que é o que a *allowlist* aceita — é um código de domínio e não uma grandeza, e somar códigos de erro não quer dizer nada —, e um código negativo vira `sem_codigo`, porque a gramática do campo não aceita o sinal `-` e o `CODIGO_SEM_CODIGO` do cliente é `-1`: sem isso, um *timeout* da Meta fazia o `Logger` estrito **levantar** no caminho de envio em vez de devolver uma recusa. Um `statuses` para um `wamid` que não existe — o caso real é a nossa escrita ainda não ter comprometido — deixa um aviso `status_sem_mensagem` em vez de desaparecer. Nenhuma métrica leva identificador: as três etiquetas são listas fechadas de quatro, dez e dois valores |
| DoD — custo e observabilidade: `meta_cost_usd_total{tenant}`, `outbound_latency_ms`, `outbound_window_closed_total` desde o código | **não satisfeito — caixa vazia** | **Cinco métricas desde o código, e a etiqueta do DoD não é implementável.** As três nomeadas existem, mais `outbound_sent_total{kind}` — que é o que torna o custo auditável, porque uma soma não se verifica sozinha e `sent_total{kind}` × tarifa reconcilia-se com ela — e `outbound_rate_limited_total{origem}`, porque recusar sem contar é recusar em silêncio. A etiqueta `origem` tem dois valores e **a etiqueta é o ponto**: `bucket` quando foi o nosso balde a travar, `meta` quando foi um `130429` que o *backoff* repetiu. A primeira versão somava as duas sob uma ajuda escrita que dizia só a primeira, e isso é um contador que mente por omissão — as duas leituras levam a decisões opostas («o nosso tecto está apertado, pode subir» contra «o dela está à frente, baixa»). A `outbound_latency_ms` é medida num `finally`, logo é medida **mesmo quando o envio levanta**, que são precisamente as execuções que interessam. **Mas o `{tenant}` não entra** (ver o CA 4), e por isso a caixa fica vazia |
| DoD — migrações reversíveis: `downgrade` testado | **satisfeito** | Bateria própria (`db/tests/test_saida_schema.py`), três casos. Com as duas tabelas vazias, desce e sobe — e a `UNIQUE` acrescentada a `conversations` sai com o `FORCE` reposto, sem o que um `upgrade` seguinte falhava a criar a restrição que já existia. **Com linhas e sem `KAMBA_DOWNGRADE_0010_COPIA`, recusa**, com as duas contagens na mensagem, e deixa o `FORCE` das duas tabelas **intacto**: a recusa não pode trocar uma perda de dados por um furo de isolamento. Com a variável, escreve a cópia lógica das **catorze** colunas de cada envio e das **dez** de cada template, **com o `pricing` e o `delivered_at`** — uma cópia que levasse as linhas e perdesse o `pricing` era pior do que nenhuma, porque parecia completa. **As políticas saem antes de se contar**, e isso é a lição da `0009` aplicada a duas tabelas: com `FORCE`, o dono está sujeito à política e uma migração corre sem contexto de *tenant* — `count(*)` veria **zero** sobre duas tabelas cheias, não pediria cópia e apagaria em silêncio. O ciclo `upgrade → downgrade → upgrade` completo corre em `test_migracao.py`. **Não há ferramenta de reposição**: a cópia é um `INSERT` por linha, como a `0003` já declarou |

**Como se correu, e o que saiu.** Nesta máquina não há `make`, `node` nem
`pnpm` no `PATH`
(`.claude/skills/agentic-engineering/references/evidencia-e-verificacao.md`,
«Como correr a verificação aqui»):

| Verificação | Comando | Resultado |
|---|---|---|
| *gate* 3 (referências, *handoff*, backlog) | `lint_refs`, `lint_handoff` e `lint_backlog` com o Python do Windows | `conforme` — 16 502 referências em 1 070 ficheiros; 630 caminhos em 159 blocos; 159 linhas do §4 a dizer o mesmo que os 159 blocos |
| *gate* 3b (nomes canónicos) | `dict_export --check`, `canon_lint check` e `canon_lint canario` | `conforme` — dicionário v1.21, **143** entradas, 10 migrações, 416 instruções, 25 tabelas, 209 colunas, **102** valores de `CHECK`; o canário com 10 negativas vermelhas e 10 positivas verdes |
| *gate* 2 (tipos e arquitectura) | `pnpm -r run typecheck` em contentor `node:24.21.0-trixie-slim`, `lint_arch all`, `log_policy lint` e `canario` | os **sete** pacotes limpos; `lista de bloqueio: conforme`; `102` ficheiros TS/JS e 34 Python lidos, **0 achados**; 29 negativas e 6 positivas, 0 falhas. **Vermelho na primeira volta do CI, com dois defeitos empilhados:** o `pnpm` recusou o ciclo `@kamba/core-ts` ↔ `@kamba/meta-sim` com `ERR_PNPM_TASK_CYCLE` e abortou o passo **antes** de chegar ao `tsc` — e por isso escondia o segundo, um `bd.query` de ensaio que não era genérico e que o `tsc` recusa («T could be instantiated with an arbitrary type»). O ciclo passa a estar **declarado** em `pnpm-workspace.yaml` com a razão escrita: as duas arestas são de desenvolvimento, o fecho de produção dos dois pacotes é **zero** (medido pelo oráculo do `pnpm list --prod` no *gate* 11), e o que a declaração troca é a ordem das tarefas, que nenhuma das duas precisa. Correr `tsc` num pacote só não era correr o *gate* 2 |
| *gate* 4 (testes de unidade da saída) | `node --test` sobre os quatro ficheiros de `tests/outbound.*.test.ts` | **134 testes, 0 falhas** |
| *gate* 4 (cobertura) | `coverage_gate.py` sobre os sete relatórios LCOV | `critico` **96%** (mínimo 90), `restante` **85%** (mínimo 75) |
| *gate* 6 (isolamento) | `db/gate_bd.py --suite tests_isolamento` | **78 testes, OK** — com as duas tabelas novas descobertas pelo catálogo e semeadas |
| *gate* 8 (migrações) | `db/gate_bd.py --suite tests` | **407 testes, OK** — catorze deles novos: as FK da saída coluna a coluna, as três coerências pela semântica e os três casos do `downgrade` |
| *gate* 8 (saída de canal) | `db/gate_bd.py --suite tests_outbound` | **10 asserções Python sobre 5 ficheiros de teste Node, OK**, em **28 s**; cobertura de `src/outbound/` entre **92%** (`metricas.ts`) e **100%**, contra o limiar de 75% do estrato `restante` |
| *gate* 9 (segredos) | `scan_secrets tree` | `limpo` — 1 070 ficheiros seguidos pelo git |
| *gate* 11 (SBOM, licenças, vulnerabilidades) | `sbom check` | 9 SBOM CycloneDX 1.6; **144** componentes, 133 permitidas e 11 nossos; **0** CRITICAL |
| prova por mutação | `db/mutacoes.py --aplicaveis` e os filtros `saida:` e `revisao 0010` | **326 mutações, 0 não aplicáveis** — **32 novas** deste ticket, quatro delas da revisão adversarial. As **19** do filtro `saida:` correram e foram **as 19 apanhadas**; as 13 do `revisao 0010` correram e **uma sobreviveu**: «a aplicação passa a poder reescrever a chave de idempotência». **A causa não era falta de teste, era a suite errada** — a mutação estava declarada em `tests_outbound`, que não olha para `GRANT` nenhum, e quem a apanha é a matriz de privilégios do `test_privilegios.py`, que vive na suite das migrações. Corrigida a suite, a mutação passa a cair; e as duas tabelas da saída entraram em `TABELAS_COM_MATRIZ_DE_COLUNA`, porque a matriz de tabela não vê um privilégio de coluna a mais e o que lá havia confirmava as cinco colunas declaradas sem exigir que não houvesse uma sexta. As **quatro** mutações novas da revisão correram e foram as quatro apanhadas. **Uma mutação na suite errada é pior do que nenhuma: diz «não apanhada» e manda procurar um teste que já existe.** A lista inteira corre de noite (KAM-143) |

#### Decisões tomadas neste ticket

- **O dinheiro é inteiro, em micro-dólares.** Não é preferência: somar `0.004`
  mil vezes em `float64` não dá `4.00`, e o leitor de YAML da casa recusou a
  primeira versão por isso. O nome da métrica diz `usd` porque é o do DoD; a
  unidade está no `# HELP`, que é onde quem lê o painel a vê.
- **A entrega conta-se ao *atravessar* o `delivered`.** A Meta não garante ordem
  nos `statuses`, e é isto que faz um `read` que chegue primeiro somar custo
  **uma** vez e o `delivered` atrasado somar zero.
- **A linha nasce antes da rede.** É o que faz a idempotência ser da base. Ao
  contrário, uma falha entre o envio e a escrita deixava uma mensagem entregue
  sem linha.
- **O *token bucket* vem depois da linha.** Travar antes de enfileirar fazia a
  chave ser recusada e o chamador repetir com uma chave nova — perder a
  idempotência para poupar uma linha.
- **O balde do canal nasce vazio e o do par nasce cheio**, e as duas metades
  foram medidas (16 numa janela de 1 s; 100 s para 100 contactos).
- **«3 tentativas» são três repetições.** Entre duas leituras de um critério, a
  que o torna possível de cumprir é a pretendida.
- **A `outbound_rate_limited_total` leva etiqueta de origem.** Um contador que
  soma a nossa travagem com a da Meta perde a única decisão que informa.
- **O `cliente.ts` fica fora da medição de cobertura da *suite* de base**, como
  o `chr/fila.ts`: o que nele pode errar em silêncio tem bateria própria no
  *gate* 4 com o `fetch` por porta, e medi-lo aqui dava-lhe uma cobertura que
  diria só que o ensaio não abre *socket*.
- **O custo sai do `estado_antes` que a base devolve, e nunca de uma leitura
  anterior.** Não há recurso a essa leitura: em série as duas fontes concordam
  sempre, e um recurso fazia o código passar os testes sequenciais sem nunca
  usar a palavra da base — era assim que o defeito voltava a ficar invisível.
- **Uma espera longa é uma recusa e não um sono.** Acima de 5 s devolve-se
  `RATE_LIMITED`, que é o motivo que a lista fechada já declarava.
- **O sexto valor de `state`, `suppressed_by_human`, nasce nesta revisão** ainda
  que seja do KAM-018: o *gate* 3b lê o AST de cada revisão isoladamente, e
  alargar um domínio numa revisão posterior deixa vermelha a que cria o `CHECK`.

### Detalhes Técnicos

- **Componentes:** ChannelAdapter (Cloud API), parte do GWY/*worker* de canal. DDL de `outbound_messages` e `message_templates` exactamente como `../docs/tecnica/01` §8.3–§8.4 (`state` aceita também `suppressed_by_human`, necessário a KAM-018).
- **Tabela de decisão (§8.2):** resposta ou notificação com janela aberta → mensagem livre (*service*); janela fechada → template *utility* (0,004); *marketing* 0,0225 desligado; autenticação 0,004 exige telefone.
- **Templates:** `pt_PT` como base (a variante `pt_AO` não existe como código, NÃO VERIFICADO); conjunto padrão (confirmação de pedido, referência de pagamento, lembrete de expiração, lembrete de marcação, passagem a humano) submetido por *tenant* no onboarding (KAM-091); aprovação por Messaging account, não partilhada entre PMEs; estado em `message_template_status_update`, `template_category_update`, `message_template_quality_update`.
- **Janela:** `conversations.window_expires_at = último_inbound + 24 h`; a janela FEP (até 7 dias, anúncios CTWA) é de Clusters.
- **Fora de âmbito:** *free tier* e método de pagamento (KAM-023), decisão sobre quem tem a palavra (KAM-018), lembretes (KAM-048), régua de cobrança (KAM-058).

### Testes Requeridos

- Unit: decisão de envio (matriz janela × tipo × estado do canal); monotonia de estados; cálculo de custo.
- Integração com servidor Graph falso (KAM-024): 130429, 5xx, duplicados, ordem por conversa; carga de *rate limit*.
- Isolamento: `ctx` de A não envia por canal de B; X-03 sobre `outbound_messages`/`message_templates`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (custo e dados pessoais); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/outbound.md`); tarifas revistas à data da evidência; Conventional Commits.
- [x] **Isolamento de tenant** — `outbound_messages` e `message_templates` com RLS e teste cruzado.
- [x] **Idempotência** — chave por envio, teste de repetição.
- [x] **Números só de tools** — o *adapter* envia texto já validado; não gera preços nem totais.
- [x] **Privacidade** — destinatário por BSUID quando existe; telefone nunca em logs.
- [ ] **Custo e observabilidade** — `meta_cost_usd_total{tenant}`, `outbound_latency_ms`, `outbound_window_closed_total` desde o código.
- [x] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-015 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-015), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§8) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§1, §5, §7). Objectivo: ChannelAdapter de saída.
- send(): janela aberta → mensagem livre; fechada → template utility ou WINDOW_CLOSED sem chamada HTTP.
- outbound_messages e message_templates (DDL do doc 01 §8.3–8.4), idempotency_key única, estados monótonos,
  pricing por mensagem, custo em meta_rates.yaml (taxas CONFIRMADAS, revisão trimestral).
- Token bucket por número (15 mps em coexistência) e por par; 130429 com backoff+jitter; botões ≤ 3, listas ≤ 10.
- PreSendGuard sob o lock da conversa (implementação em KAM-018); sem marketing no Piloto; BSUID como recipient.
Não expandas escopo: free tier/pagamento Meta é KAM-023; lembretes e cobranças são de outros epics.
Testes: matriz de decisão, idempotência, estados, rate limit, 130429. Abre PR com o template do §7.
```

---

## KAM-016 — Embedded Signup v4 e Tech Provider (troca de code, subscrições de webhooks)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-013, KAM-003, ext:KAM-102, KAM-010, KAM-024 |
| Bloqueia | KAM-017, KAM-091, KAM-093 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§4.2–§4.4, §13), `../docs/tecnica/10_Onboarding_Governanca.md` (§6), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§2, §3), `../docs/tecnica/08_Seguranca_Conformidade.md` (§5), ADR-001, ADR-019 |

### Contexto

Factos CONFIRMADOS (E1 §3): Embedded Signup v2 e v3 deixam de funcionar a 2026-10-15, logo só v4; é preciso Tech Provider ou Solution Partner, Business Verification **da nossa empresa** antes do App Review, Advanced access a `whatsapp_business_messaging` e `whatsapp_business_management`; até 10 clientes novos/7 dias antes de verificação completa (200/7 dias depois; «Access Verification» NÃO VERIFICADO); o cliente é sempre dono dos activos; o ES devolve `waba_id`, `phone_number_id` e um *code* trocável por token. O prazo e a aceitação de documentos angolanos na Business Verification são NÃO VERIFICADOS (L3, D5). O backlog mestre não declara a dependência de KAM-010 (cofre do token e do PIN).

### Objectivo

Implementar o lado servidor do onboarding de canal: receber o resultado do ES v4, trocar o *code* por token de cliente, guardá-lo no cofre, subscrever a app ao WABA e aos campos de webhook, validar com um evento de teste e persistir a máquina de estados do canal com passos idempotentes e compensáveis.

### Critérios de Aceitação

- [x] `POST /internal/channels` aceita `{tenant_id, code, waba_id, phone_number_id, session_info}`; o ES é v4 (`extras.featureType = "whatsapp_business_app_onboarding"` e `sessionInfoVersion: "3"` para coexistência); o código não referencia v2/v3.
- [x] Idempotência: repetir o mesmo `code` ou o mesmo `(tenant_id, waba_id)` 2× produz 1 canal, 1 token e 0 subscrições duplicadas.
- [x] O token de cliente é guardado cifrado (AES-256-GCM, DEK por tenant, KEK no cofre, `kid` versionado) com `token_ref` em `tenant_channels`; um *dump grep* da BD e dos logs não encontra o token em claro; o PIN 2FA de 6 dígitos (modo `cloud_only`) vai para o cofre com acesso mínimo.
- [x] Anexar um `phone_number_id` já usado por outro tenant devolve 409, não altera nada e deixa registo de auditoria.
- [x] A subscrição cobre exactamente os campos: `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync`, `account_update`, `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update`; a leitura de confirmação devolve esse conjunto (igualdade de conjuntos) e um evento de teste chega ao GWY.
- [x] `channel_onboarding` regista a fase (`iniciado, es_concluido, subscrito, a_sincronizar, verificado, pronto, ativo, falhado, abandonado`); transições inválidas são rejeitadas; sem conclusão em 30 min o estado passa a `abandonado`.
- [x] Cada passo regista o recurso criado e tem compensação (revogar token, anular subscrição); uma falha injectada no passo 4 deixa 0 recursos órfãos.
- [x] Guarda `waba_id` e `waac_id` (nulo hoje) e `phone_number_id`; o contador `es_onboardings_7d` está exposto para o limite de 10 clientes/7 dias (a lista de espera é KAM-095).
- [ ] 1 onboarding ES v4 real numa conta de teste da Meta, depois de KAM-102, com evidência em `docs/evidencia/KAM-016.md` (capturas sem dados pessoais).

### Detalhes Técnicos

- **Componentes:** GWY (rotas internas), CHR (`tenant_channels`), serviço de onboarding. A página/pop-up do cliente é KAM-093; aqui um *harness* de teste mínimo.
- **Fluxo (de `../docs/tecnica/01` §4.3):** popup ES v4 → `code` + ids → trocar *code* por token → guardar no cofre → subscrever campos → sincronização (KAM-017) → Chatwoot (KAM-019/091) → mensagem de teste → gate de activação. Os pontos finais e parâmetros exactos da Graph API **não** constam de E1 (páginas de referência de API não lidas): ler a documentação vigente («Updated: Jul 24, 2026») e fixar a versão da Graph API em configuração.
- **Estado do canal:** `tenant_channels.estado` mantém `pendente → ativo`; as fases finas vivem em `channel_onboarding(channel_id, fase, recursos_criados jsonb, actualizado_at)`. O orquestrador (saga) é KAM-091; este ticket entrega passos idempotentes.
- **Fora de âmbito:** Business Verification/App Review (KAM-102), sincronização (KAM-017), método de pagamento no Billing Hub e gate de activação (KAM-093).

### Testes Requeridos

- Contrato com Graph falsa (KAM-024): troca de *code*, subscrição, falha injectada, repetição.
- Segurança: token em claro, 409 de `phone_number_id`, auditoria. Máquina de estados: tabela completa de transições.
- Real: 1 execução ponta a ponta na conta de teste (evidência).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (segredos, número de uma PME); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/onboarding-canal.md`); Conventional Commits.
- [x] **Isolamento de tenant** — um canal pertence a um só tenant; RLS em `channel_onboarding`; teste cruzado.
- [x] **Idempotência** — passos repetíveis com teste de repetição.
- [x] **Privacidade** — nenhum dado de cliente final tratado; token e PIN nunca em logs.
- [x] **Sem segredos** — token/PIN só no cofre; scan limpo.
- [x] **Migrações reversíveis** — `downgrade` testado.

### Verificação dos Critérios de Aceitação

> **As caixas desta lista foram marcadas a 2026-10-23**, na auditoria dos
> critérios de saída do epic (§2), e não no PR que entregou o ticket: elas
> ficaram todas vazias enquanto esta tabela já dizia o veredito de cada
> critério. A regra da marca é a desta tabela — **a caixa fica vazia quando
> qualquer parte do critério não se cumpre** — e nenhuma se marcou sem o teste
> que ela cita ter sido conferido no ficheiro de teste. Nada desta secção foi
> reescrito: ela mede o que era verdade no dia em que correu.
>
> **Oito caixas de critério marcadas e uma vazia** — a do critério 9, o
> onboarding real numa conta de teste da Meta, que depende de `ext:KAM-102`
> —, e **seis de DoD marcadas e duas vazias**: a dos revisores, e a do
> «todos os CA satisfeitos», que não pode estar marcada com o 9 vazio. É o
> que a emenda 1.9 do «Controlo de versões» deste epic já declarava — «oito
> caixas de critério marcadas e uma vazia» — e que as caixas nunca mostraram.

Medido em 2026-10-22, ramo `feature/KAM-016-embedded-signup-v4-tech-provider`,
sobre `publico/main` (`5f7dfeb`, KAM-022). Desenho em
[`../docs/onboarding-canal.md`](../docs/onboarding-canal.md).

**A revisão é a `0017` e não a `0016`, e isso mudou depois de as medições estarem
feitas.** Verifiquei o remoto antes de escolher o número — `git branch -r --list
'publico/feature/KAM-018*'` devolveu vazio — e o ramo do KAM-018 chegou depois,
com uma `0016` a descender da mesma `0015`. **Dois `down_revision` iguais são
recusados pelo Alembic**, e não é colisão mecânica: as revisões de base encaixam
uma na anterior e entram em série. Renumerou-se esta porque a dele **não cria
objecto nenhum** — dois `GRANT UPDATE` por coluna em `conversations` —, pelo que
nada lhe aponta, enquanto esta cria uma tabela com receita de sementes, entrada no
inventário, matriz de privilégios e lugar na descoberta do X-05.

**Consequência, e está dita porque é verificável:** o *gate* 8 deste ramo só passa
com a `0016` na base. Os números abaixo foram medidos com a revisão numerada
`0016` a descender da `0015`, que é a mesma árvore de objectos — o que a
renumeração muda é o `down_revision`, o nome do ficheiro e as citações. A ordem de
merge é a do remoto: primeiro o KAM-018, depois este.

Todas as medições de Node correram num contentor
`node:24.21.0-trixie-slim@sha256:173f1258…`, e as de Python num `venv` criado
**fora** do repositório: esta máquina de desenvolvimento não tem `node`, `pnpm`
nem `make` no `PATH`, e dentro do repositório o `supply_chain check` varre o
`site-packages` e falha. `make ci-8` numa máquina sem `make` responde
`command not found` — o que **não** é «o gate passa».

**Oito caixas de critério marcadas e uma vazia**, e a vazia é o nono: pede um
onboarding real numa conta de teste da Meta, depois de `ext:KAM-102`. Das oito do
DoD, **duas** ficam vazias e as duas são nomeadas abaixo com a razão.

| # | Critério | Estado | O que se mediu |
|---|---|---|---|
| 1 | `POST /internal/channels` com os cinco campos; ES v4 (`featureType`, `sessionInfoVersion: "3"`); o código não referencia v2/v3 | **satisfeito** | A rota existe e os cinco campos são validados antes de se abrir transacção nenhuma: **21** testes em `services/gwy/tests/canais.test.ts`, com os cinco campos em falta, um a um, a dar **400 sem abrir transacção**. A forma de v4 verifica-se **antes de falar com a Meta** — a asserção é que a única chamada à base foi a contagem da janela e que a Graph recebeu zero. O `sessionInfoVersion` aceita `"3"` e o número `3`, e recusa `"2"`, `"3 "`, `"03"`, `""`, `null` e a ausência; o `extras.featureType` é exigido **sem tolerância**, porque é ele que distingue a coexistência do `cloud_only` e adivinhá-lo pela ausência era decidir o modo do canal por omissão. **A terceira cláusula mede-se no texto dos ficheiros**, e é a única asserção desta bateria que o faz: varre `src/onboarding/*.ts` à procura de um `sessionInfoVersion` com valor diferente de `"3"` e de um ramo por versão do ES (`es_v2`, `esV3`). Não há variável de ambiente para a versão do ES — só para a da **Graph**, que é outra coisa e que os *Detalhes Técnicos* mandam fixar em configuração. **A rota vive na app interna do GWY**: a pública responde **404**, e há três asserções a prendê-lo |
| 2 | Idempotência: o mesmo `code` ou o mesmo `(tenant_id, waba_id)` 2× produz 1 canal, 1 *token*, 0 subscrições duplicadas | **satisfeito, e é da base** | Duas unicidades em `channel_onboarding` — `(tenant_id, code_hash)` e `(tenant_id, waba_id)` — e o `INSERT ... ON CONFLICT DO NOTHING RETURNING` **sem alvo**: com um alvo nomeado, a repetição do mesmo *code* noutro WABA levantava `23505` em vez de devolver a linha que lá estava. Medido contra a base: o mesmo *code* 2× dá **1** tentativa e **1** canal; o mesmo par com um *code* novo dá **1** canal (contado antes e depois); e **em paralelo, em duas ligações**, as duas chamadas ao `SQL_ABRIR` devolvem `[0, 1]` linhas e a tabela fica com **1**. «1 canal» não é propriedade do código: o canal cria-se na **mesma transacção** que escreve o `channel_id` nessa linha. E as duas chaves levam o `tenant_id` — o mesmo *code* em dois *tenants* abre **duas** tentativas, pela razão da emenda 1.21. A repetição **não fala com a Meta nem com o cofre**: trocar o *code* outra vez criava um segundo *token* antes de descobrir que havia um, e a asserção conta as chamadas das duas |
| 3 | *Token* cifrado (AES-256-GCM, DEK por *tenant*, KEK no cofre, `kid` versionado) com `token_ref`; *dump grep* da BD e dos logs não o encontra; PIN 2FA no cofre com acesso mínimo | **satisfeito** | **O *dump grep* é literal**: a bateria junta `tenant_channels` e `channel_onboarding` em texto (`c.*::text`) e procura o *token*, o *code* e o PIN — nenhum está lá. O que está é `meta_client_token/<32 hex>`, uma referência opaca. **E o que está no cofre é o criptograma**, não o *token*: a cifra é nossa, e a bateria decifra-o com a KEK para provar que é o mesmo valor. Doze asserções sobre a cifra: a DEK de dois *tenants* nunca coincide e é determinística no mesmo par; duas cifras do mesmo *token* dão criptogramas diferentes (IV novo); **um criptograma copiado para outro *tenant* não abre** — e isso não é zelo, porque o `token_ref` é uma coluna que o `GRANT UPDATE` da `0001` concede a `kamba_app`, pelo que mover a referência de A para a linha de B é uma escrita que a base aceita; o `kid` lê-se sem abrir e **a rotação da KEK não perde os *tokens* antigos**; um `kid` que saiu do anel diz **qual** falta; um octeto alterado não abre (GCM autentica); uma KEK de 16 octetos é recusada e não truncada; e nenhum erro repete o *token* que recusou. O PIN é de **seis** dígitos, vai para `meta_pin_2fa` («acesso minimo: so o provisionamento o le», `ops/secrets-inventory.yaml`) e a coluna guarda a referência com `CHECK` **de forma** de `SecretRef` — quatro cadeias mal formadas são recusadas pela base. **E a porta de escrita no cofre é nova**: fecha a lacuna que o `ADR-L002` §6 declarou para este dia |
| 4 | `phone_number_id` de outro *tenant* devolve 409, não altera nada, deixa registo de auditoria | **satisfeito** | As três metades resolvem-se com a **forma da transacção** e não com três mecanismos. O **409** é a `tenant_channels_phone_number_id_uq` da `0001` a levantar `23505`, e ramifica-se pelo **nome da restrição** e não pelo código sozinho — há um teste com um `23505` de outra restrição a provar que ele **não** se disfarça de 409. O **«não altera nada»** mede-se na base **depois do `ROLLBACK`**: o número de canais é o mesmo antes e depois, a linha do dono continua com o `tenant_id` de A, e a tentativa de B não existe. O **registo** escreve-se a seguir, numa transacção **própria** — e a asserção que o prende é a contagem de transacções da rota: **duas**. A resposta **não diz de quem é o número**: nomear o dono era um canal de leitura entre *tenants* por mensagem de erro, e há duas asserções sobre isso. **O registo não é o `audit_log`**, e a razão é mecânica e foi medida — ver a nota abaixo |
| 5 | Subscrição dos **onze** campos exactos; leitura de confirmação por igualdade de conjuntos; evento de teste chega ao GWY | **satisfeito contra o simulador** | As **três** cláusulas, e a terceira é a que obrigou a sair do módulo. As duas primeiras medem-se contra o `GraphFalso` do KAM-024 levantado em `node:http`: os onze campos subscrevem-se, o servidor guarda **quais**, e a leitura de confirmação devolve o mesmo conjunto. A comparação é de **conjuntos** — a ordem invertida passa, um campo a menos aparece em `falta` e só ele, um a mais aparece em `aMais` e não como falta, e duplicados na resposta não contam como campo a mais; subscrever duas vezes não duplica. **E o domínio compara-se com o do simulador**, que é a terceira cópia dele (a primeira é o critério, a segunda o `../docs/tecnica/01` §4.4): `CAMPOS_DE_WEBHOOK` e o `CAMPOS` do `@kamba/meta-sim` são o mesmo conjunto de onze, com teste — duas cópias de um domínio divergem no dia em que uma delas mudar. A **terceira** cláusula mede-se no GWY e campo a campo: uma *fixture* **assinada** de cada um dos onze entra pelo `POST /wa/webhook`, responde **200** e deixa **um** *job* na fila. É a prova de que subscrever estes onze nomes não é um gesto vazio — há um caminho de entrada para cada um. A assinatura vem do `assinar` do simulador, que tem `createHmac` próprio e não importa nada do `core-ts`: são duas implementações, e é isso que faz a ida e volta medir alguma coisa. **O que isto não é:** o evento de teste do passo 10 do `01` §13.2, que é uma mensagem real enviada e recebida no número do cliente. Esse é o nono critério |
| 6 | `channel_onboarding` com as nove fases; transições inválidas rejeitadas; `abandonado` aos 30 min | **satisfeito** | As nove, e **o `desligado` do diagrama do `01` §13.1 não é uma delas** — é valor de `tenant_channels.estado` desde a `0001`, e quem o escreve é o KAM-017; o `CHECK` da base recusa-o, junto com `pendente`, `INICIADO` e `""`. A matriz tem **dezesseis** arestas contra as onze do diagrama, e a diferença é uma regra: de qualquer fase não terminal vai-se a `falhado` — sem ela, o caminho que o critério 7 manda exercitar (uma falha no passo 4, que corre em `es_concluido`) não era representável. Os **81** pares ordenados medem-se um a um: exactamente dezesseis passam, uma fase para si mesma **não** é transição, o `ativo` é terminal, e o `abandonado` só sai de `iniciado` — como o diagrama o desenha. Contra a base, os dezesseis escrevem e a **segunda** passagem devolve **zero linhas**, que é o `WHERE fase = <esperada>` a serializar. Um par inválido **levanta antes de tocar na base**, e a asserção é que nenhuma consulta correu. Os **30 min**: um `iniciado` parado há 31 minutos passa a `abandonado`, um `falhado` ao lado **não é tocado**, e um `iniciado` dentro do prazo fica. E o domínio do contrato confronta-se com o `pg_get_constraintdef` da revisão, nos dois sentidos |
| 7 | Cada passo registra o recurso e tem compensação; falha injectada no passo 4 deixa 0 recursos órfãos | **satisfeito** | Os **quatro** recursos são os quatro passos com efeito fora da transacção (`token`, `pin`, `canal`, `subscricao`), e a lista é a coluna `recursos_criados`, pela ordem. A falha injectada no passo 4 — a subscrição, o que o critério nomeia — mede-se em **três** sítios e não na coluna: `0` linhas a mais em `tenant_channels` (contadas antes e depois), `0` segredos no cofre, e `0` subscrições **no WABA**, lido no `GraphFalso`. A coluna fica `[]`, o `channel_id` volta a `NULL` e a fase fica `falhado`. **A ordem é inversa e isso não é arbitrário**: anular a subscrição exige o *token* em claro, pelo que revogar o *token* primeiro deixava a subscrição sem forma de ser desfeita. Há três asserções que valem mais do que o caminho feliz: uma **compensação que falha não esvazia a lista nem desfaz o resto** (quem retomar tem de saber o que falta — e deixar o canal para trás porque a Meta não respondeu ao `DELETE` era trocar um órfão por dois); **compensar duas vezes resolve** (a `SecretWriter` exige `revogar` idempotente, e um `DELETE` de um canal que já não lá está devolve zero linhas); e a confirmação incompleta compensa **também** a subscrição. E o `jsonb ||` não perde um recurso que outro passo registou: duas escrituras concorrentes em duas ligações deixam **dois** na lista — numa base falsa isso era verdade por construção |
| 8 | Guarda `waba_id`, `waac_id` (nulo) e `phone_number_id`; `es_onboardings_7d` exposto para o limite de 10/7 dias | **satisfeito, e os três identificadores já existiam** | **Esta revisão não acrescenta coluna nenhuma a `tenant_channels`**: o `waba_id`, o `waac_id` e o `phone_number_id` existem desde a `0001`, com os `CHECK` de forma e o `GRANT UPDATE` por coluna a cobri-los, e o `token_ref` também. A bateria lê a linha criada e afirma os três, com o `waac_id` a `NULL` — nulo **de propósito**: a Fase 3 do novo modelo de contas (H1 2028, CONFIRMADO em `E1` §3) passa a exigir o ID do WAAC nos caminhos da API, e guardar os dois hoje é o que torna essa fase uma alteração de caminho e não de esquema. O contador **atravessa *tenants***, porque o tecto de dez em sete dias é da nossa app perante a Meta e não de uma loja: dois *tenants* diferentes dão `+2`, e com a política `tenant_iso` o `kamba_app` nunca o poderia contar — é por isso que corre como `kamba_batch`. A fronteira mede-se: oito dias atrás não conta, sete dias menos um minuto conta. Com nove na janela ainda passa e com dez recusa (**429**, não 403: é «ainda não», não «nunca»). **Conta tudo o que entrou na janela**, incluindo o `abandonado` e o `falhado` — o lado conservador, porque se um *popup* fechado consome um lugar na contagem **deles** é NÃO VERIFICADO, e contar de menos custa um cliente. A lista de espera é KAM-095, e o critério di-lo |
| 9 | 1 onboarding ES v4 real numa conta de teste da Meta, depois de KAM-102, com evidência em `../docs/evidencia/KAM-016.md` | **não satisfeito** | **Não há conta de teste da Meta, nem app aprovada, nem Tech Provider.** O critério depende de `ext:KAM-102` — Business Verification da nossa empresa, App Review com Advanced access a `whatsapp_business_messaging` e `whatsapp_business_management`, e o estatuto de Tech Provider —, e esse é trabalho do fundador, não deste ramo. **`../docs/evidencia/KAM-016.md` não existe e não se criou**: um ficheiro de evidência com capturas inventadas ou com a prosa de um onboarding que não aconteceu é pior do que a sua ausência, porque uma caixa marcada deixa de se poder distinguir de uma caixa verificada. O que está provado, e contra o quê, está na nota abaixo |

#### O que está provado contra o simulador, e o que só o primeiro contacto real pode dizer

A distinção não é académica: ela é a diferença entre este ticket estar feito e o
canal funcionar.

**Provado contra o `GraphFalso` do KAM-024, e vale como prova do nosso lado:**
que o cliente compõe o caminho com o segmento de versão e o registra lá; que o
*code* se troca e o *token* volta; que os onze campos se subscrevem e a leitura
de confirmação devolve o mesmo conjunto; que a anulação esvazia o WABA e repetir
resolve; que um `400` da Graph vem com o `error.code` e que a nossa mensagem não
repete o *code*. Tudo isto é sobre **o nosso cliente**, e um servidor falso é
suficiente para o afirmar.

**Não provado, e nenhum teste deste ramo o pode afirmar:**

1. **Que os três caminhos são os da Meta.** Os *Detalhes Técnicos* do bloco
   dizem-no por extenso — «Os pontos finais e parâmetros exactos da Graph API
   **não** constam de E1 (páginas de referência de API não lidas)» —, e não há
   rede nesta sessão. Os três vivem em constantes exportadas
   (`CAMINHO_DA_TROCA`, `caminhoDasSubscricoes`) para que o dia em que alguém
   leia a documentação vigente seja uma alteração de três linhas com um teste a
   afirmá-las.
2. **Que a Graph aceita a troca do *code* como a enviamos.** Ver «A primeira
   versão do cliente ficou vermelha», abaixo.
3. **Que a Meta aceita os onze campos de uma vez.** O simulador aceita tudo o
   que lhe mandem; a Graph real pode recusar um campo que a app não tenha
   permissão para subscrever, e é precisamente para isso que a leitura de
   confirmação existe — mas o que ela vai dizer no primeiro contacto é
   desconhecido.
4. **Que a versão `v21.0` existe.** É a omissão, e é ***proposta***: o próprio
   `GraphFalso` diz porquê — «inventar uma ("v23.0") era afirmar o que não se
   sabe». O que um teste afirma é que o cliente usa **a que a configuração diz**.
5. **Que o *popup* devolve um `session_info` com esta forma.** O `E1` §3 confirma
   os dois campos que o critério nomeia e nada mais; o resto do objecto entra
   **inteiro e opaco**, porque inventar-lhe campos era afirmar o que não se sabe.
6. **Que o PIN de seis dígitos é aceite no registo do número.** O passo 5′ do
   `01` §13.2 é KAM-093, e a entrega de SMS pela Unitel e pela Africell é NÃO
   VERIFICADA; este ticket guarda o PIN que esse passo vai usar.
7. **Que um *popup* abandonado não consome um lugar na contagem da Meta.** Por
   isso se conta pelo lado conservador.

#### A primeira versão do cliente ficou vermelha, e a correcção é uma exposição declarada

A troca do *code* ia em `POST` com `client_id`, `client_secret` e `code` no corpo
`application/x-www-form-urlencoded` — o que a RFC 6749 §4.1.3 exige do ponto
final de *token* de OAuth 2.0, e exige-o **precisamente** porque um segredo numa
URL aparece em registos de proxy, em registos de acesso e no `Referer`.

O `#trocarCode` do `GraphFalso` lê `pedido.consulta.code` e responde `400` a quem
não o ponha lá. **Três testes vermelhos na primeira execução.** Não é um defeito
do simulador: é ele a modelar a `GET /oauth/access_token` que a Meta documenta, e
o autor do KAM-024 sabia da outra forma — o comentário do `ouvir()` dele diz «o
Graph aceita `form-urlencoded` em algumas rotas».

Havia duas saídas:

* **alargar o simulador** para ler também o corpo, e passar a provar o cliente
  contra uma superfície que eu próprio tinha alargado para lhe servir. Se a Graph
  real só aceitar a consulta, o primeiro onboarding real falha **com os testes
  verdes** — que é exactamente o desfecho que o «não inventes caminhos de API» do
  bloco existe para evitar;
* **seguir o simulador**, que é a superfície de referência deste epic, e escrever
  a exposição.

Escolheu-se a segunda. O que está mitigado: o pedido sai em TLS, pelo que a
consulta não aparece em claro no fio; o *code* é de uso único e é esta chamada
que o gasta; este cliente **nunca escreve a URL num log**, e o `caminho` de um
`GraphRecusouError` leva a constante e não a consulta — há um teste a prendê-lo.
O que **não** está mitigado: um proxy de saída nosso que registre a linha de
pedido guarda o `code` e o `client_secret` num ficheiro. Isso é KAM-077, e está
declarado no `graph.ts`, no dicionário §3.20 e no
[`../docs/onboarding-canal.md`](../docs/onboarding-canal.md) §6.

#### O registo de auditoria do critério 4 não é o `audit_log`, e a razão foi medida

«Devolve 409, não altera nada e **deixa registo de auditoria**.» O registo é uma
linha de `channel_onboarding` em `falhado`, com o `motivo` escrito e
`recursos_criados = '[]'`.

O sítio onde se iria procurar é o `platform.audit_log` da revisão `0006`. Não é
lá, e a razão é mecânica: o domínio de `audit_log.action` tem **sete** valores e
o `CHECK` está nessa revisão, **fundida**. O *gate* 3b lê o `CHECK` de **cada
revisão isoladamente** e compara-o com o dicionário **nos dois sentidos** —
`tools/canon_lint/ddl.py` reporta `falta:` —, pelo que acrescentar um oitavo
valor ao dicionário deixava a `0006` vermelha. É a mesma mecânica que a emenda
1.20 pagou para o `unrouted_events.motivo` e a 1.26 para o `motivo_restricao`,
pelo outro lado: ali os valores entraram na revisão que cria o `CHECK`, e aqui
essa revisão não se reescreve.

E nenhum dos sete descreve isto — `price.update`, `stock.adjust`,
`payment.manual_confirm`, `access.conversation`, `batch.run`, `breakglass.open`,
`audit.read`. Enfiar a recusa em `access.conversation` era mentir num registo que
existe para não mentir.

**E o «não altera nada» continua literalmente verdadeiro**, porque o 409 vem de
uma transacção que **reverte**: o `INSERT` em `tenant_channels` levanta `23505`,
a transacção cai, e nem a linha do canal nem a actualização da tentativa
sobrevivem. A linha de `falhado` escreve-se **depois**, numa transacção própria —
e é por isso que a rota a escreve e o `ligar()` não: a ligação que ele tem é a
que acabou de abortar. Se a linha de auditoria contasse como «alterar», o
critério contradizia-se a si próprio na mesma frase.

#### O que a `(tenant_id, waba_id)` custa, e porque se aceitou

Um *tenant* não pode ter dois números no **mesmo** WABA por este caminho. Um WABA
aceita vários números, pelo que o caso é real.

O critério 2 fixa-o assim, e o que o justifica é que o recurso que o passo 4 cria
— a subscrição — é **do WABA** e não do número: «0 subscrições duplicadas» é,
literalmente, uma subscrição por `(tenant, waba)`. Quem acrescentar um segundo
número ao mesmo WABA tem de **reutilizar** a subscrição que já existe, e isso é
um caminho novo e não um relaxamento desta chave. Fica registado aqui e no
dicionário §3.20.

#### A revisão adversarial, e os três defeitos que ela encontrou

A revisão correu contra o estado do ramo **depois** de as oito caixas estarem
marcadas e de os quatro gates estarem verdes. Devolveu três defeitos, e o
primeiro é o que faz a diferença entre uma caixa marcada e uma caixa verificada:
**ele estava verde em todos os testes.**

| # | O que estava errado | Como se vê, e o que mudou |
|---|---|---|
| 1 | **O 409 deixava o *token* no cofre.** Um `23505` **aborta a transacção inteira** no PostgreSQL: todas as instruções seguintes respondem `25P02`, e entre elas estão as da compensação — que é quem revoga o *token* que o passo anterior cunhou. O `ROLLBACK` da rota apaga a linha do canal e a da tentativa, mas **o cofre não é transaccional**: o *token* ficava lá, sem nada a apontar para ele e sem ninguém a saber que existe. E o critério 4 diz «não altera nada» | Estava verde em **todos** os testes, e a razão é a que o `docstring` da bateria de unidade avisa por extenso: **a base falsa não modela o aborto da transacção.** A bateria de base verificava `tenant_channels` e a tabela nova — as duas limpas pelo `ROLLBACK` — e não o cofre. A correcção é um `SAVEPOINT` em volta do `INSERT` do canal: o conflito desfaz-se só até ali, a ligação continua utilizável, e a compensação corre. **O duplo da base passou a responder `25P02` depois de um `23505`**, que é o que torna isto medido e não corrigido às cegas — e há uma mutação própria que o tira |
| 2 | **A compensação rebentava no último passo.** O `SQL_LIMPAR_RECURSOS` põe o `channel_id` a `NULL`, e o `channel_onboarding_canal_ck` recusa-o nas seis fases do meio. A ordem era «limpa, depois transita», pelo que a limpeza corria com a fase ainda em `es_concluido` e levantava `23514` — **depois** de ter desfeito tudo o que havia a desfazer, que é o pior momento possível para rebentar | A ordem passou a «transita, depois limpa»: o `falhado` é uma das três fases que dispensam canal. É um `CHECK` que eu próprio escrevi a recusar uma instrução que eu próprio escrevi, e nenhum dos dois estava errado — o que estava errado era a ordem. Há um teste que afirma a ordem no registo de chamadas, e uma mutação que a troca |
| 3 | **Um comentário dizia o contrário do código.** «Uma compensação que falha **não para as outras**», escrevia o `catch` — e o código `return`a na primeira falha. O teste afirmava o `return` | Era o **comentário** que estava errado, e a razão é a ordem inversa: o `token` é o último a ser desfeito, pelo que revogá-lo depois de a anulação da subscrição falhar deixava um recurso órfão **impossível de desfazer** em vez de um que fica à espera da próxima passagem. O comentário passou a dizer isso. Um comentário que mente é pior do que nenhum: o próximo leitor acredita nele |

**O que os três têm em comum** é que nenhum é uma falha de lógica: são os três
sobre a **fronteira transaccional** — o que a base faz a seguir a um erro, o que
um `CHECK` vê a meio de uma sequência, e o que a ordem de uma lista obriga. E dois
dos três só se vêem contra um PostgreSQL de verdade, que é a razão de esta
*suite* existir.

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **vazia** | **Oito dos nove**, e o nono é o onboarding real: ele depende de `ext:KAM-102` e nenhuma medição deste ramo o pode substituir. O critério 5 fica **parcial** pela sua terceira cláusula, que é o mesmo número de teste. A caixa fica vazia e não meia porque a letra dela diz «todos» |
| Código revisto por **2 revisores** (segredos, número de uma PME); testes verdes; cobertura ≥ limiar | **vazia** | Testes verdes e cobertura **medidos**: **1 694** testes de unidade, **1 693** a passar, **0 a falhar** (o saltado é pré-existente, nos segredos), dos quais **66** novos em `tests/onboarding.test.ts`, **21** em `tests/onboarding.graph.test.ts`, **21** em `services/gwy/tests/canais.test.ts` e **29** em `tests_bd/onboarding.bd.test.ts`; as *suites* do *gate* 8 verdes (`tests` **512**, que inclui a revisão `0017` e o `downgrade`; `tests_outbound` **10**, com os tres ficheiros do modulo; `tests_isolamento` **78**); `src/onboarding/` entre **94,8% e 100%** por ficheiro. O `cifra.ts` entra no estrato `critico` de `ci/thresholds.yaml` — é o mesmo tipo de código que põe o `identity/cripto.ts` lá desde o KAM-008 — e mede **94,8%** contra os 90% desse estrato; o resto do módulo fica no `restante`, a 83% agregados contra 75%. **Zero revisores humanos** — é decisão escrita do fundador, e a caixa fica vazia como facto registado e não como passo cumprido. **Alterar `ci/thresholds.yaml` pede dois revisores**, e essa caixa fica vazia pela mesma razão |
| Documentação actualizada (`../docs/onboarding-canal.md`); Conventional Commits | **marcada** | [`../docs/onboarding-canal.md`](../docs/onboarding-canal.md), com as sete decisões de desenho e as **cinco** limitações declaradas. Emenda **1.29** ao dicionário (§3.20) e `canon/dicionario.yaml` regenerado — `dict_export --check`, `canon_lint check` e `canon_lint canario` conformes, v1.29, **230** entradas, 25 extensões. O `../docs/ci.md` §3 ganha as **sete** propriedades novas e a linha de versão **1.49**. Conventional Commits validados pelo gancho (`git -c core.hooksPath=tools/githooks commit`) |
| **Isolamento de tenant** — um canal pertence a um só tenant; RLS em `channel_onboarding`; teste cruzado | **marcada** | `rls.enable_tenant_rls("channel_onboarding")` na `0017`, com `FORCE` e a política `tenant_iso` (ADR-015); a descoberta do X-05 passa de vinte e quatro para **vinte e cinco** tabelas e a tabela ganhou receita de sementes no *gate* 6, com o canário no `waba_id`. Teste cruzado nos dois sentidos: com o contexto de A a tentativa de B não se vê, e **sem contexto são zero linhas**. A FK composta `(tenant_id, channel_id)` impede uma tentativa de A de apontar para um canal de B, e isso mede-se. **E a escrita não depende da política**: o `kamba_app` leva **`42501`** num `INSERT`, num `UPDATE` e num `DELETE` — o privilégio nem existe, que é mais forte do que a política recusar porque não depende de a política estar certa. «Um canal pertence a um só tenant» é a `tenant_channels_phone_number_id_uq` **global** da `0001`, e é a mesma unicidade que dá o 409 |
| **Idempotência** — passos repetíveis com teste de repetição | **marcada** | Critério 2, acima, em **três** níveis: o mesmo *code* duas vezes, o mesmo par com um *code* novo, e duas aberturas **em paralelo em duas ligações** (o `ON CONFLICT` a serializar). E os passos são repetíveis um a um: subscrever duas vezes não duplica (o conjunto é um conjunto), anular duas vezes resolve, revogar um segredo que já não existe resolve, e compensar duas vezes não revoga nada a segunda vez |
| **Privacidade** — nenhum dado de cliente final tratado; *token* e PIN nunca em logs | **marcada** | **Nenhuma coluna da tabela nova é dado pessoal de cliente final**, e isso não é sorte: o onboarding é entre a plataforma e o **dono** da PME. O que lá está são chaves opacas da Meta — e o `phone_number_id` **não é um telefone**, como o `COMMENT` da coluna homónima diz desde a `0001`. O módulo nunca vê um telefone. Os logs passam a lista branca de nove campos do `../docs/tecnica/08` §7.3 — nenhuma chamada leva um `fase` ou um `recurso` como campo, porque a lista não os tem: o que sai é `outcome` e `error_code`. **O `code` não entra na mensagem de um 400** (há teste), **o *token* não entra na mensagem de um erro da Graph** (há teste), e a resposta da rota **não leva o `token_ref` nem o `pin_ref`** (há teste). As quatro métricas não levam etiqueta de *tenant*, e há um teste que varre a exposição |
| **Sem segredos** — *token*/PIN só no cofre; *scan* limpo | **marcada** | O *dump grep* do critério 3, acima, nos **dois** sítios que o critério nomeia (a base e os logs) e num terceiro que ele não nomeia: o cofre guarda o **criptograma** e não o *token*. O `code` entra na base em `sha256` e nunca em claro — ele é trocável por um *token*, logo é um segredo com o valor do *token*, e guardá-lo em claro para fazer idempotência punha na base exactamente o que este critério manda não pôr lá. O `pin_ref` leva `CHECK` de forma de `SecretRef` na base. A `SecretWriter` vive num ficheiro só, e isso é deliberado: um `cunhar(familia, valor)` é a única assinatura deste repositório onde um valor de segredo é argumento, e tê-la num sítio mantém pequena a área que o *gate* 9 vigia |
| **Migrações reversíveis** — `downgrade` testado | **marcada** | `TestDowngradeDa0017`: desce **com linhas** e sobe outra vez; a tabela, os três índices e a política desaparecem, o canal e o *tenant* ficam, e o `upgrade` repõe tudo. **Sem guarda de dados e sem cópia para ficheiro**, ao contrário da `0010` e da `0012`: o que se perde é o registo de **tentativas** de onboarding — não é dinheiro nem prova jurídica, e as tentativas vivas refazem-se (o *code* queima-se e o dono repete o *popup*). Os canais **não** se perdem: a linha de `tenant_channels` é da `0001`. **E sem repor concessões**, pela lição que o KAM-023 mediu na `0013`: o PostgreSQL remove as concessões **com** o objecto, pelo que um `REVOKE` antes do `DROP TABLE` é uma instrução que nenhuma mutação consegue matar |

#### A prova por mutação

**528** mutações conferidas pelo `--aplicaveis`, **0 não aplicáveis** — e
esse comando corre-se depois de cada integração do `main`, pela lição que o
KAM-023 deixou: o `git merge` pode fazer uma constante deste ficheiro sombrear
outra **sem conflito nenhum**, e nenhum teste o vê. **Trinta e sete** são novas:
cinco da revisão `0017` (as duas unicidades, a FK composta, o `GRANT` e a RLS) e
trinta e duas do código, cada uma a tirar uma afirmação de um critério — o `ON
CONFLICT` com alvo nomeado, o *compare-and-set* sem a fase de partida, o
`recursos_criados` reescrito em vez de concatenado, a aresta que o critério 7
precisa, o `smb_message_echoes` fora dos onze, a DEK sem o *tenant*, o `kid` fora
do criptograma, o IV fixo, o sufixo previsível da referência.

**O prefixo é `ON_` e foi escolhido depois de procurar.** É a lição do
`MED_SQL`/`FT_SQL` que o KAM-022 repetiu: um prefixo que colida com o de outro
ticket sombreia entradas em silêncio.

---

### Handoff para Claude Code

```text
És o executor do ticket KAM-016 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-016), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§4, §13) e
docs/tecnica/10_Onboarding_Governanca.md (§6). Objectivo: lado servidor do Embedded Signup v4.
- Recebe code, waba_id, phone_number_id; troca o code por token; guarda no cofre (AES-256-GCM, DEK por tenant);
  subscreve os 11 campos de webhook e confirma por leitura; valida com evento de teste.
- channel_onboarding com fases, passos idempotentes por (tenant_id, waba_id) e compensação; 409 se o número é de outro tenant.
- Só v4. Lê a documentação vigente da Meta para endpoints e parâmetros; não inventes caminhos de API.
- Guarda waba_id e waac_id (nulo); expõe es_onboardings_7d (limite 10/7 dias).
Não expandas escopo: sem Business Verification (KAM-102), sem sync (KAM-017), sem UI (KAM-093).
Testes: Graph falsa, repetição, falha injectada, segurança do token, 1 execução real. Abre PR com o template do §7.
```

---

## KAM-017 — Coexistência: history, state sync, echoes, `PARTNER_REMOVED`, sincronização de 24 h

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-016, ext:KAM-100, KAM-024 |
| Bloqueia | KAM-018, KAM-083, KAM-093, KAM-115 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.1, §10.4, §10.5, §13), `../docs/tecnica/10_Onboarding_Governanca.md` (§6.3, §7.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§2), ADR-001, ADR-010 |

### Contexto

Factos CONFIRMADOS (E1 §2): a coexistência exige Tech Provider, app WhatsApp Business ≥ 2.24.17 e ES com *session logging*; sincroniza contactos e **6 meses** de histórico em **24 h** após o onboarding (cada passo só uma vez, senão offboard e refazer); débito fixo de 20 mps; `PARTNER_REMOVED` com `PRIMARY_INACTIVITY` (~14 dias sem abrir a app), `COMPANION_INACTIVITY`, `BUSINESS_DOWNGRADE`, `CHANGE_NUMBER`, `USER_RE_REGISTERED`, `ACCOUNT_DISCONNECTED`; a API de *deregister* não funciona. **Elegibilidade de Angola: NÃO VERIFICADA (L1)**; o spike KAM-100 decide. Se falhar para um número, o modo é `cloud_only` com número novo dedicado (a lógica de saída é a mesma). Se um *echo* é gerado por mensagens enviadas por API é NÃO VERIFICADO (L6); a comparação com `outbound_messages.wamid` torna o tratamento seguro nos dois casos.

### Objectivo

Tratar os webhooks de coexistência e a sincronização inicial com prazo duro de 24 h, o ciclo de desligamento e reconexão, e garantir que histórico e sincronização nunca produzem resposta do bot.

### Critérios de Aceitação

- [x] `history` e `smb_app_state_sync` alimentam `contacts` (KAM-008) e `coexistence_synced_at`; 0 *jobs* para o AGR e 0 mensagens enviadas por estes eventos (fixture com 6 meses de histórico).
- [x] O corpo das mensagens de histórico **não** é persistido nem indexado no Piloto (apenas contactos e contagens); a base legal para o usar (a confirmar por parecer, KAM-104) fica como critério de saída antes de o alargar.
- [x] O *job* de sincronização é idempotente (cada passo executado uma vez; 2.ª execução = *no-op*), alerta aos 12 h sem conclusão e marca o canal `falhado` + tarefa de *offboard* às 24 h (relógio acelerado nos testes).
- [x] O erro 2593109 (cliente não partilhou histórico) conduz a `sincronizado_sem_historico` e **não** a falha.
- [x] Cada um dos 6 motivos de `PARTNER_REMOVED` passa o canal a `desligado`, emite `channel.updated` e cria alerta; repetir o mesmo evento 2× produz 1 transição.
- [ ] Aviso preventivo `channel.inactivity_warning` aos 10 dias sem *echo* e sem actividade do dono (heurística de `../docs/tecnica/01` §10.5; a entrega ao dono por canal alternativo depende de mecanismo ainda sem ticket: ver riscos).
- [x] Os *echoes* (`smb_message_echoes`) são registados em `inbound_events` (`kind=echo`) e entregues ao tratador de KAM-018; um *echo* cujo `wamid` consta de `outbound_messages` é ignorado como actividade humana.
- [x] O `channel_mode` determina o que fica activo: em `cloud_only` não há *job* de sincronização nem *echoes*; o débito do *token bucket* de KAM-015 usa 15 mps em `coexistencia`.
- [x] A reconexão (`desligado → iniciado`) reutiliza o ES de KAM-016 sem criar canal duplicado.
- [ ] Evidência da elegibilidade: ≥ 1 sincronização completa num número +244 real e referência ao relatório de KAM-100; se KAM-100 concluir negativo, o predefinido do produto passa a `cloud_only` e o ticket regista-o.

### Detalhes Técnicos

- **Componentes:** CHR/canal (tratadores de `account_update`, `history`, `smb_app_state_sync`, `smb_message_echoes`), job de sincronização em BullMQ com *deadline*.
- **Campos CONFIRMADOS:** `extras.featureType = "whatsapp_business_app_onboarding"`; evento final `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`; **sem registo do número**; janela de conversa só abre com mensagem do utilizador **depois** do onboarding (conversas anteriores só por template).
- **Funcionalidades perdidas pela PME** (grupos, listas de difusão, catálogo e respostas rápidas da app, `E1` §2) devem constar do aviso do onboarding (texto em KAM-093).
- **Eventos:** `channel.updated` (KAM-007) com `motivo`; o registo de desligamento fica também em `channel_onboarding`.
- **Fora de âmbito:** decisão de silenciamento (KAM-018), UI de reconexão (KAM-093), histórico no RAG/LLM (proibido sem base legal; nunca para treino, Termos da Meta §4.7, L15).

### Testes Requeridos

- Contrato com fixtures do simulador (KAM-024): `history`, `smb_app_state_sync`, `smb_message_echoes`, 6 × `account_update`, erro 2593109, duplicados.
- Tempo: relógio acelerado para 12 h/24 h/10 dias. Isolamento: eventos de A não alteram canais de B.
- Real: sincronização num número +244 (evidência).

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (número de uma PME, dados pessoais); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/coexistencia.md`, com funcionalidades perdidas); Conventional Commits.
- [x] **Isolamento de tenant** — eventos resolvidos por `waba_id`/`phone_number_id` → tenant; teste cruzado.
- [x] **Idempotência** — sincronização e `account_update` repetidos com teste.
- [x] **Privacidade** — histórico não persistido nem enviado a LLM; contactos por `contact_id`.
- [x] **Custo e observabilidade** — `coex_sync_duration_s`, `coex_sync_failed_total`, `channel_disconnected_total`.
- [ ] O resultado de KAM-100 (L1) está referenciado e o modo predefinido decidido.

### Verificação dos Critérios de Aceitação

> **As caixas desta lista foram marcadas a 2026-10-23**, na auditoria dos
> critérios de saída do epic (§2), e não no PR que entregou o ticket: elas
> ficaram todas vazias enquanto esta tabela já dizia o veredito de cada
> critério. A regra da marca é a desta tabela — **a caixa fica vazia quando
> qualquer parte do critério não se cumpre** — e nenhuma se marcou sem o teste
> que ela cita ter sido conferido no ficheiro de teste. Nada desta secção foi
> reescrito: ela mede o que era verdade no dia em que correu.
>
> **Oito caixas de critério marcadas e duas vazias** — o critério 6, porque
> esta tabela o dá como **parcial** (metade da heurística do `01` §10.5 pede
> um sinal de acesso ao painel que não existe no esquema; dívida 84, KAM-093),
> e o critério 10, por `ext:KAM-100`. No DoD, **cinco marcadas e três
> vazias**: as duas que o parágrafo acima nomeia, mais a do «todos os CA
> satisfeitos», que não pode estar marcada com o 6 e o 10 vazios. As três
> grandezas do DoD de observabilidade foram conferidas em
> `packages/core-ts/src/coexistencia/metricas.ts` antes de a caixa ser
> marcada.

**Os nove critérios constroem-se, e oito ficam marcados.** O décimo — a
*Definition of Done* «o resultado de KAM-100 (L1) está referenciado e o modo
predefinido decidido» — e o critério 10 ficam **vazios**, e não por falta de
trabalho: o relatório do `ext:KAM-100` **não existe** (não há
`docs/evidencia/KAM-100.md`) e a elegibilidade de Angola continua **NÃO
VERIFICADA** (risco R1 da tabela deste epic). O que depende dele é **um valor
por omissão** e mais nada: a lógica dos dois modos está entregue inteira, e é a
mesma — o `../docs/tecnica/01` §10.1 di-lo por extenso («a lógica de saída é a
mesma, só muda o §10.2»). Escolher o predefinido aqui era decidir pelo relatório
que o havia de decidir, e a decisão devolve-se a quem tiver o relatório.

| Critério | Estado | Evidência |
|---|---|---|
| 1 — `history` e `smb_app_state_sync` alimentam `contacts` e `coexistence_synced_at`; **0** *jobs* para o AGR e **0** mensagens enviadas (*fixture* com 6 meses de histórico) | **satisfeito** | **Os zeros provam-se por construção e por asserção.** O módulo **não tem porta** para o AGR nem para a saída — não as pode chamar —, e o `ResultadoDaIngestao` leva um `jobsParaOAgr: 0` cujo tipo é o literal `0`: o teste afirma o número que o critério escreve em vez de afirmar a ausência de uma chamada que ninguém declarou. Os contactos passam pela porta do KAM-008 (`resolveContact`) e o que fica guardado é o `contact_id`; um contacto sem `bsuid` **e** sem telefone não vai à porta, porque ela levanta `PedidoSemIdentificadorError` e um lote de seis meses não se perde por uma linha mal formada. O `coexistence_synced_at` escreve-se **uma vez, no fim** — «sincronizou» é um facto e não um progresso, e um carimbo que se mexesse a cada lote respondia «há cinco minutos» a uma pergunta que é «quando é que este canal ficou pronto». **A *fixture* de 6 meses é a contagem e não os corpos**, e isso é o critério 2 a mandar: o lote entra como `{mensagens: N, contactos: [...], erros: []}`, e o `tests/coexistencia.test.ts` corre-a com 1 240 mensagens |
| 2 — o corpo das mensagens de histórico **não** é persistido nem indexado no Piloto | **satisfeito** | **A garantia é a forma e não uma regra escrita.** A `channel_coexistence` tem dezoito colunas e **nenhuma é texto livre**: as de texto são domínios fechados (`estado`, `motivo_desligamento`) ou um *array* com `CHECK` de conteúdo (`passos_feitos`). O que o histórico deixa são duas contagens. A `inbound_events` do KAM-013 também não tem coluna de corpo, pelo que o texto passa pelo processo e não fica em sítio nenhum. **Há um teste que o afirma pela forma** — percorre **todos** os parâmetros de **todas** as instruções que uma ingestão emite e exige que nenhum seja um texto que pudesse ser conteúdo. E nada vai a um LLM: é o «fora de âmbito» do bloco e o L15 (Termos da Meta §4.7). A base legal fica como critério de saída, em KAM-104 |
| 3 — o *job* é idempotente (2.ª execução = *no-op*), alerta aos 12 h e marca `falhado` + *offboard* às 24 h (relógio acelerado) | **satisfeito** | **O *no-op* é do PostgreSQL e não de um `if`.** O `SQL_MARCAR_PASSO` filtra por `NOT ($3 = ANY (passos_feitos))` **e** por `estado = 'a_sincronizar'`, e a segunda passagem devolve **zero linhas** — medido com **duas ligações** a disputar o mesmo passo em `tests_bd/`, onde exactamente uma escreve. A mesma instrução marca o passo **e** soma as contagens, de propósito: separá-las dava um caminho em que o lote repetido contava sem marcar. O segundo predicado não é enfeite — a Meta reenvia durante sete dias, e sem ele um `history` atrasado desfazia o *offboard* que o critério acabou de pedir (há teste). O alerta das 12 h é idempotente pelo `alertado_em IS NULL`; sem ele, um processo chamado de cinco em cinco minutos alertava doze vezes por hora durante doze horas. **O relógio entra por parâmetro e o prazo é coluna**, e as duas coisas juntas são o que torna «relógio acelerado» possível: um prazo derivado de `now()` na consulta não se acelera sem mexer no servidor. O *offboard* **é a mesma lista** do `falhados` e não uma segunda — um `falhado` é um *offboard* pedido, e devolver duas sugeria que pode haver um sem o outro. **Não há agendador**, e isso não é dívida deste ticket: não existe nenhum no repositório (nem `repeat:`, nem `delay:`, nem `cron`) e nasce com o KAM-071/KAM-078; o padrão é o do `abandonarVencidas` do KAM-016 e o do `pausarPorInactividade` do KAM-018 — uma função idempotente por predicado SQL, testável agora e chamável depois |
| 4 — o erro 2593109 conduz a `sincronizado_sem_historico` e **não** a falha | **satisfeito** | É um estado **terminal e bem-sucedido** e não um caso de erro: o cliente escolheu não partilhar histórico, que é uma escolha do titular. Tratá-lo como `falhado` disparava o *offboard* — isto é, mandava o dono repetir o Embedded Signup — por ele ter exercido uma escolha que o próprio *popup* da Meta lhe oferece. **E não marca o passo `historico`**, que não correu: fechar e marcar eram duas afirmações contraditórias sobre o mesmo facto. **O achado que mudou o desenho:** o código tem **sete** dígitos, e a política de *logs* recusa mais de **seis** em qualquer campo de texto (`DIGITOS_MAXIMOS`) nos **dois** campos onde ele caberia — no `outcome` e no `error_code`. Mediu-se contra o espelho Python: `validar("error_code", "2593109")` devolve `None` e o `131049` de seis dígitos do KAM-015 passa. **O número não se pode registar de todo**, pelo que vive numa coluna `integer` e o registo leva o `outcome` simbólico — e há um teste que prende as duas recusas, para que quem acrescente outro código da Meta o confronte primeiro |
| 5 — cada um dos 6 motivos passa o canal a `desligado`, emite `channel.updated` e cria alerta; repetir 2× produz 1 transição | **satisfeito** | **Os seis, um a um**, contra as *fixtures* assinadas do KAM-024 — que tem uma por motivo e uma marca de cobertura por motivo. A idempotência são **dois predicados na mesma transacção**: o `desligado_em IS NULL` da coexistência e o `estado <> 'desligado'` do canal; se só um mordesse, as duas tabelas discordavam sobre se o canal está desligado. Medido com duas chamadas concorrentes em `tests_bd/`: exactamente uma transita, um evento, uma contagem. **A ordem é escrever, emitir, contar**, e é a que o KAM-018 pagou — as duas escritas vivem na mesma transacção, e com o contador antes da emissão um `evt_emitir` que levante desfaz o `UPDATE` e **não** desfaz o contador; há um teste que injecta a excepção e exige que a métrica fique a zero. **Os seis valores vão em minúsculas, e a razão foi medida:** são também `outcome`, e a gramática do campo só aceita minúsculas — em modo estrito, que é o do CI, o `Logger` **levanta**, e um desfecho normal de um *webhook* virava excepção não tratada. Confrontaram-se os seis com o espelho Python, um a um, e o `CHECK` da `0018` recusa a forma `MAIUSCULA` — o que torna a tradução na fronteira obrigatória em vez de opcional. **O «cria alerta» é o evento e não uma entrega**: ver o critério 6 |
| 6 — aviso `channel.inactivity_warning` aos 10 dias sem *echo* e sem actividade do dono | **parcial — satisfeito no que se mede** | **Metade da heurística do `../docs/tecnica/01` §10.5 não é mensurável, e isso está declarado.** Ela diz «sem *echo* **e sem acesso ao painel**»: o *echo* mede-se (`channel_coexistence.ultimo_echo_em`, escrito a cada *echo* que não é nosso) e **o painel não existe** — é KAM-093, e não há sinal de acesso em sítio nenhum do esquema. Inventar um era inventar evidência; fica na dívida **84**. O que se entrega é a metade que existe, e entrega-se inteira: idempotente pelo `avisado_em IS NULL`, e a janela **reabre** quando chega actividade do dono (o `SQL_REGISTAR_ECHO` põe o carimbo a nulo) — sem isso, um canal avisado uma vez nunca mais era avisado. O `COALESCE(ultimo_echo_em, iniciado_em)` é o caso do canal que **nunca** teve *echo*: sem ele, um dono que nunca escreveu na app — exactamente quem o aviso existe para apanhar — nunca era avisado, porque `NULL <= $1` é `NULL`. Os dez dias são ***proposta***: o que é CONFIRMADO é o outro número, os ~14 dias de `PRIMARY_INACTIVITY`, e os dez são a folga de quatro. **A entrega ao dono é KAM-115**, e o próprio critério o diz — este ticket emite o evento e pára aí |
| 7 — os *echoes* em `inbound_events` (`kind=echo`), entregues ao tratador do KAM-018; o *echo* cujo `wamid` consta de `outbound_messages` é ignorado | **satisfeito** | O registo em `inbound_events` com `kind=echo` já era do KAM-013. O que este ticket entrega é o detector, e para o entregar **fixou o campo que o `explosao.ts` lhe atribuía por extenso** («fixar o campo é KAM-017»): o interlocutor de um *echo* é o **destinatário** (`CAMPO_DO_DESTINATARIO = "to"`), no nome que o simulador do KAM-024 já emite, para que os dois lados da ***proposta*, NÃO VERIFICADA** digam o mesmo. Sem ele, um *echo* não tem contacto, logo não tem conversa, logo a célula `bot→dono` do KAM-018 ficava sem detector para sempre. **O `bsuid` continua `null` e não se inventa**: o `from_user_id` identifica quem *envia*, e quem envia um *echo* é o dono — um BSUID do dono no lugar do interlocutor fazia o KAM-008 resolver o contacto errado. A regra do `wamid` é a do critério e é segura nos **dois** lados do L6: está em `outbound_messages` → fomos nós, ignora-se e **não se mexe no relógio** (um bot a responder não prova que o dono abriu a app); não está → é do dono, e dispara `echo_do_dono` pela porta do KAM-018. **Há um terceiro desfecho e ele é honestidade:** um *echo* do dono cujo destinatário não resolve conversa — o caso normal da coexistência — **conta-se** (`coex_echo_total{desfecho="sem_conversa"}`) em vez de se descartar em silêncio. A consulta leva `tenant_id` apesar de o `wamid` ser globalmente único, pela razão do `SQL_JANELA` do KAM-015. **O comando `/bot` não se detecta**, e não é esquecimento: o `EventoDeEntrada` não leva o corpo de uma mensagem, e fazê-lo levar punha texto de conversa no contrato de ingestão (contra o ADR-010) por uma transição que **nenhum dos nove critérios deste ticket pede**. A célula `dono + comando_bot` do KAM-018 fica sem detector, e está dito aqui e no `docs/coexistencia.md` §8 |
| 8 — o `channel_mode` determina o que fica activo; o *token bucket* usa 15 mps em `coexistencia` | **satisfeito** | Em `cloud_only` o `abrir` devolve `null` sem tocar na base, e um *echo* não vira actividade humana — nem se consulta o `outbound_messages`, porque não há *echoes* nesse modo. Os 15 mps já eram o `MPS_POR_CANAL` do KAM-015, **para todos os canais sem olhar ao modo**; o que este ticket acrescenta é o `MPS_POR_MODO` e o parâmetro `modo` do `pedir`, que tornam o 15 uma **escolha por modo** e não uma coincidência. **Os dois valores são hoje iguais, e isso é deliberado:** o `E1` §5 confirma 20 mps em coexistência e a Meta dá 80 em `cloud_only`, mas **nenhum documento deste repositório fixa o número do `cloud_only`** — e o próprio `limites.ts` já o dizia. Pô-lo por dedução era inventar o que o critério não diz e arriscar o `130429` que o balde existe para evitar. O modo só é lido quando o balde **nasce**: um balde que mudasse de capacidade a meio perdia a conta do que já tirou, e o `channel_mode` de um canal não muda sem um onboarding novo — que cria balde novo de qualquer forma, porque o `phone_number_id` do `cloud_only` é outro |
| 9 — a reconexão (`desligado → iniciado`) reutiliza o ES de KAM-016 sem criar canal duplicado | **satisfeito** | **Duas unicidades, e nenhuma é um `if`.** A `channel_onboarding_tenant_waba_uq` do KAM-016 faz um `ligar()` repetido devolver `novo: false` sem falar com a Meta nem com o cofre; a `channel_coexistence_canal_uq (tenant_id, channel_id)` deste ticket faz o `ON CONFLICT ... DO UPDATE` **repor** a linha que lá está. Medido com duas aberturas concorrentes em `tests_bd/`: fica **uma** linha. **Repor e não deixar**, e isso é o que vale a pena ler: uma reconexão é uma sincronização **nova**, e o `E1` §2 é explícito em que cada passo corre uma vez **por onboarding** — deixar os `passos_feitos` da ligação anterior fazia a sincronização nova nascer concluída sem ter corrido, que é precisamente o modo de falhar que o prazo de 24 h existe para apanhar. O `motivo_desligamento` e o `desligado_em` limpam-se **os dois juntos**, porque o `channel_coexistence_desligamento_ck` exige as duas metades ou nenhuma e limpar só uma era um `23514` na reconexão |
| 10 — evidência da elegibilidade: ≥ 1 sincronização completa num número +244 real e referência ao relatório de KAM-100 | **não satisfeito — caixa vazia** | **Não se entrega, e não é esquecimento.** O relatório do `ext:KAM-100` **não existe** — não há `docs/evidencia/KAM-100.md` —, a elegibilidade de Angola é **NÃO VERIFICADA** (risco R1: «Coexistência indisponível ou instável para números +244»), e uma sincronização real precisa de um número +244 em *staging* ligado a uma conta de teste da Meta, que também depende de `ext:KAM-102`. A tabela de riscos deste epic já atribui a mitigação a KAM-100 e escreve a regra que este ticket seguiu: «KAM-017 só fixa o modo predefinido depois do relatório de KAM-100; alternativa `cloud_only` com número novo dedicado». **A lógica dos dois modos está entregue e é a mesma**; o que falta é um valor por omissão, e a decisão é de quem tiver o relatório |

**Os dois DoD que também ficam por marcar, com a mesma razão.** «Código revisto
por 2 revisores (número de uma PME, dados pessoais)» fica **vazio** — nesta fase
não há revisores humanos, por decisão escrita do fundador, e a caixa fica vazia
como facto registado e não como caixa marcada. E «o resultado de KAM-100 (L1)
está referenciado e o modo predefinido decidido» é o critério 10.

**O que este PR tocou fora do seu módulo, e porquê.** Três sítios, e cada um
tem a razão escrita no código:

1. **`entrada/explosao.ts`** — o `interlocutor` de um `echo` deixou de ser
   `null`. É o que o comentário daquele módulo atribuía a este ticket, e sem
   ele o critério 7 não é cumprível.
2. **`chr/chr.ts`** — a porta `EntregaDoChr.dono` ganhou um `interlocutor`
   opcional. É o mínimo que faz o detector funcionar **sem** o CHR passar a
   resolver identidade num `echo`, que é a propriedade que a nota daquele ramo
   protege.
3. **`outbound/limites.ts`** — o `MPS_POR_MODO` e o parâmetro `modo` do
   `pedir`. Vive ali e não no `coexistencia/contrato.ts` porque é ali que estão
   os outros tectos, e pô-lo cá fazia o `outbound` importar do `coexistencia`,
   que já importa do `outbound`. Uma mutação do KAM-015 mudou de texto com esta
   alteração e **reescreveu-se em vez de se apagar**: o que ela mata — um balde
   a nascer cheio — continua a fazer falta.

**O módulo entrega-se construído e não montado**, e isso é o padrão da casa:
o `services/worker-canal/src/entrada.ts` tem quatro braços no `Encaminhador` e
três continuam a contar e mais nada. O KAM-021, o KAM-022 e o KAM-018 deixaram
todos o mesmo, e montar **um** braço enquanto os outros ficam por montar deixava
o processo a tratar coexistência e a ignorar qualidade e consentimento. A ordem
de montagem está em `../docs/coexistencia.md` §9.

**Sete defeitos da revisão adversarial, e dois deles tornavam critérios
inexecutáveis.** Todos corrigidos neste PR, com teste a prender cada um:

1. **As três varreduras não podiam correr.** As do critério 3 (alerta às 12 h,
   `falhado` às 24 h) e a do critério 6 são `UPDATE` **sem `tenant_id` no
   predicado**, logo só correm com `BYPASSRLS` — e o único papel que o tem é o
   `kamba_batch`, a quem a primeira versão da `0018` negava o `UPDATE`. Pior: a
   nota da revisão justificava a negação dizendo que «não há caminho de
   retaguarda que altere o estado de uma sincronização», quando o módulo tinha
   três. Respondiam `42501`, e **os critérios 3 e 6 não tinham caminho
   executável** — só decisão escrita. O precedente estava à vista e não se
   seguiu: o `abandonarVencidas` do KAM-016 corre como `kamba_batch` e a `0017`
   dá-lhe os quatro verbos. O teste de base ajudava a esconder, porque corria a
   varredura com o administrador e dizia que o que provava era «o predicado».
2. **Os emissores reais não encaixavam na porta `Emitir`.** A porta tem cinco
   parâmetros com o `channelId` em terceiro, e as funções tinham quatro e três
   sem ele. **Nem o compilador nem o contrato apanhavam** — o TypeScript admite
   atribuir uma função de menos parâmetros, e o `motivo` do esquema é `string`
   livre —, pelo que o `channel.updated` sairia com o **UUID do canal** no
   `phone_number_id` e o `phone_number_id` no `motivo`. Ficava latente porque
   todos os testes substituíam as portas por lambdas; o teste novo liga os
   emissores **reais** e lê o que chega ao `evt_emitir`.
3. **Um canal `suspenso` ficava com as duas tabelas em desacordo.** A ordem era
   registar e depois desligar, e o `SQL_DESLIGAR_CANAL` não toca em `suspenso`
   nem em `encerrado` (de propósito: uma suspensão é decisão nossa que um
   *webhook* da Meta não revoga) — mas o registo já tinha mordido, e a função
   devolvia normalmente. Era exactamente o modo de falhar que o tratador diz
   prevenir. Inverteu-se: o canal primeiro, o registo só se ele transitou.
4. **O aviso `desligamento_desalinhado` disparava no caminho normal de um canal
   `cloud_only`**, que nunca tem linha de coexistência porque o `abrir` não
   insere nesse modo — ruído no sinal que existe para apanhar desalinhamento a
   sério.
5. **O teste de privilégios por coluna era vácuo.** Ele avalia
   `de_tabela or coluna in por_coluna`, e um `GRANT UPDATE` de tabela
   curto-circuita o `or`: a lista nunca era confrontada, e o comentário que a
   acompanhava afirmava uma restrição que não existia — o `kamba_app` **podia**
   mover uma coexistência para o canal ou o *tenant* de outro. O `GRANT` passou
   a ser **por coluna**, o que torna o teste real e fecha o buraco; há também um
   teste que o afirma pelo efeito, e não só pela lista de nomes.
6. **O prazo das 24 h não era duro.** O `SQL_MARCAR_PASSO` e o `SQL_CONCLUIR`
   filtravam por `estado` e nunca pelo `prazo_em`: como não há agendador, um
   `history` reentregue às 30 h encontrava o estado ainda em `a_sincronizar` e
   fechava a sincronização **depois** do prazo. O teste que parecia cobri-lo
   chamava a varredura antes, pelo que provava o predicado do estado e não o
   prazo. Entrou o `prazo_em > $n` nas duas instruções, e o teste novo **não**
   chama a varredura.
7. **Um *echo* num canal sem linha de coexistência falhava fechado e mudo** — o
   relógio não avançava, o aviso dos 10 dias deixava de sair, e nada o
   registava. Passou a registar-se. E, a propósito, o `EVENTO_PARTNER_REMOVED`
   era uma constante exportada e nunca lida: o tratador decidia só pelo
   `reason`. Passou a ser guarda.

**E o que a revisão procurou e não encontrou**, que vale tanto como o que
encontrou: confrontou os **dezoito** valores de `outcome` com o espelho Python
(todos passam, e o `2593109` é recusado nos dois campos, como a §3.22 afirma);
rastreou o `interlocutor` de um *echo* por todo o `src/` e `services/` até
concluir que não chega a nenhuma escrita; e verificou que nenhuma etiqueta de
métrica aceita um identificador, que todas as consultas levam `tenant_id` além
da RLS — excepto as três varreduras, que o declaram —, e que o `downgrade` é
reversível com linhas.

**E um oitavo, que nenhum gate local apanhou porque o *gate* 7 não corre
offline:** as baterias deste ticket usavam telefones de forma **angolana real**
(`+244 9…`), 38 deles, e o `varrer` do KAM-024 recusa-os — o critério 7 daquele
ticket pede «0 telefones reais no repositório». Passaram ao `999`, o indicativo
que a UIT não atribui a país nenhum e que o `INDICATIVO_FICTICIO` reserva. Não
se declarou excepção no inventário: um número de ensaio não precisa de forma
angolana para provar nada, e a convenção já existia em três sítios.

**Uma alínea do critério 1 fica por demonstrar com *fixture* do simulador.** Ele
pede «*fixture* com 6 meses de histórico»; a do KAM-024 traz **uma** *thread*, e
o caminho de seis meses exercita-se com uma contagem sintética (1 240 mensagens)
em `tests/coexistencia.test.ts`. A propriedade que o critério mede — zero *jobs*,
zero envios, zero corpos — não depende do volume, e é por isso que a caixa fica
marcada; o que falta é a *fixture* saber produzir o volume, e isso é do KAM-024
(dívida **83**, que é onde a contradição daquela *fixture* já está declarada).

### Handoff para Claude Code

```text
És o executor do ticket KAM-017 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-017), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§10.1, §10.4, §10.5)
e docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§2). Objectivo: coexistência (histórico, sync, echoes, PARTNER_REMOVED).
- history e smb_app_state_sync só ingestão (contactos e contagens); nunca AGR, nunca resposta; não persistas corpos.
- Job de sincronização idempotente com deadline de 24 h e alerta aos 12 h; erro 2593109 é caso normal.
- account_update → desligado + channel.updated + alerta; aviso aos 10 dias sem echo; reconexão por ES sem duplicar canal.
- Echoes para o tratador de KAM-018; ignora echo cujo wamid está em outbound_messages. channel_mode manda.
- Lê o relatório de KAM-100; se negativo, o modo predefinido passa a cloud_only e regista-o.
Não expandas escopo: silenciamento é KAM-018; UI de reconexão é KAM-093.
Testes: fixtures do simulador, relógio acelerado, isolamento, 1 sync real. Abre PR com o template do §7.
```

---

## KAM-018 — Protocolo bot ↔ dono ↔ humano: modos da conversa e silenciamento por echo

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-014, KAM-017 |
| Bloqueia | KAM-034, KAM-109, KAM-114, KAM-117, KAM-118, KAM-123 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.2, §10.3, §19 proposta 01-C), `../docs/tecnica/00_Arquitectura_Solucao.md` (§12), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§12), ADR-001, ADR-010 |

### Contexto

Em coexistência o dono e o bot falam pelo mesmo número; sem protocolo respondem em simultâneo e contradizem-se (risco da §12 do doc 00). A decisão é tratar o **modo da conversa** (`bot`, `dono`, `humano`, `pausada`) como estado de primeira classe (proposta 01-C), por conversa e nunca por canal, com verificação pré-envio sob o *lock* da conversa. O gatilho é o *echo* (`smb_message_echoes`) cujo `wamid` não está em `outbound_messages`. A janela residual de corrida é a latência do *echo* (NÃO MEDIDA, L6). A Messaging Policy exige caminho de escalonamento a humano em todas as conversas (E1 §4, CONFIRMADO).

### Objectivo

Implementar a máquina de estados do modo da conversa, o tratador de *echoes*, o `PreSendGuard` que descarta respostas do bot quando houve actividade humana e a medição da latência do *echo*.

### Critérios de Aceitação

- [ ] Transições (tabela de `../docs/tecnica/01` §10.2): `bot→dono` por *echo* com `wamid` ausente de `outbound_messages`; `dono→bot` quando o cliente escreve depois de `silencio_dono_min` (predefinido 30, a calibrar) sem actividade do dono, ou por comando `/bot` do dono; `bot→humano` por pedido do grafo ou do cliente; `humano→bot` por `conversation_status_changed=resolved`; qualquer→`pausada` por opt-out ou 24 h sem humano após handoff; `pausada→bot` quando o cliente volta a escrever após aviso. Qualquer outra transição é rejeitada (teste exaustivo da tabela).
- [x] `PreSendGuard`, sob `pg_advisory_xact_lock(hash(tenant_id, contact_id))`, descarta o envio se `mode ≠ bot` ou `last_human_activity_at > início_do_turno`, regista `suppressed_by_human` e devolve ao AGR o sinal de cancelamento.
- [x] Teste de corrida: turno inicia em t0, *echo* chega em t0+1 s, resposta pronta em t0+2 s → 0 mensagens enviadas e 1 registo suprimido; em 100 intercalações aleatórias, 0 mensagens do bot são enviadas depois de o *echo* estar registado.
- [x] O silenciamento é por conversa: duas conversas no mesmo canal, A em `dono` e B em `bot`, respondem independentemente.
- [x] Mensagens do cliente em modo `dono`/`humano` são entregues ao dono/HND e **não** ao AGR (0 *jobs* AGR nesse modo).
- [ ] Cada mudança emite `conversation.mode_changed` (tipo acrescentado ao catálogo, KAM-007) e actualiza o estado visível em HND (KAM-019) em ≤ 5 s (proposta).
- [x] Um tratador `onOptOut(contact)` coloca `pausada` (a detecção de «PARAR» é de KAM-022); o *timeout* de 24 h corre como *job* idempotente.
- [ ] Métrica `echo_latency_ms` (diferença entre o carimbo da Meta e a recepção) com p50/p95 de ≥ 30 *echoes* reais em *staging* anexados como evidência (critério de saída de L6); sem limiar bloqueante.

### Detalhes Técnicos

- **Componentes:** CHR (modo da conversa), HND (espelho do estado), ChannelAdapter (`PreSendGuard`). Tabela `conversations` criada em KAM-014; migração aqui adiciona `outbound_messages.state='suppressed_by_human'` se ainda não existir.
- **Pseudocódigo do guard:**
```
guard(conv, turn): lock(conv)
  if conv.mode != 'bot' or conv.last_human_activity_at > turn.started_at:
      record(suppressed_by_human); return CANCEL
  return OK
```
- **UX:** o comando `/bot` do dono é uma mensagem real enviada ao cliente (visível); validar no Piloto se é aceitável e, se não, mover o comando para o painel/Chatwoot. O onboarding explica ao dono a regra «se responder na app, o bot cala-se nessa conversa» (`../docs/tecnica/01` §10.3).
- **Fora de âmbito:** retoma do grafo após handoff (KAM-034), criação de conversas no Chatwoot (KAM-019), detecção de opt-out (KAM-022).

### Testes Requeridos

- Unit: tabela de transições (todas as combinações estado × gatilho).
- Concorrência: 100 intercalações *echo*/resposta com ordem aleatória; dois eventos simultâneos serializados pelo *lock*.
- Integração: duas conversas independentes; modo `humano` sem invocações do AGR; evidência de latência de *echo* em *staging* com número +244.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (corrida, número de uma PME); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/modos-conversa.md`); Conventional Commits.
- [x] **Isolamento de tenant** — o *lock* e o modo usam `tenant_id` do contexto; teste cruzado do novo caminho.
- [x] **Idempotência** — o mesmo *echo* repetido 2× produz 1 transição; teste incluído.
- [x] **Privacidade** — sem conteúdo nem telefone em `conversation.mode_changed` nem em logs.
- [ ] **Custo e observabilidade** — `conv_mode_transitions_total`, `echo_latency_ms`, `reply_suppressed_total`.
- [x] **Migrações reversíveis** — `downgrade` testado.


### Verificação dos Critérios de Aceitação

**O que este PR entrega é a parte do ticket que não depende de coexistência**, e
as duas coisas que ficam de fora ficam de fora com a razão escrita: a transição
`bot→dono` por *echo* precisa de `smb_message_echoes` (KAM-017, atrás de
`ext:KAM-100`) e a métrica `echo_latency_ms` pede ≥ 30 *echoes* reais em
*staging* com números +244 (critério de saída do risco **L6/R6**, KAM-100). As
caixas dos critérios **1**, **6** e **8** ficam **vazias** por isso; as outras
cinco estão marcadas com a evidência abaixo.

| Critério | Estado | Evidência |
|---|---|---|
| 1 — a tabela de transições do `../docs/tecnica/01` §10.2, e qualquer outra transição rejeitada (teste exaustivo) | **parcial — caixa vazia** | **A tabela e a rejeição exaustiva cumprem-se; o detector do *echo* não.** As **32** células — quatro modos × oito gatilhos — são afirmadas **uma a uma** em `tests/modos.transicoes.test.ts`, contra uma tabela escrita à mão nesse ficheiro e **não** derivada da implementação; `db/tests_modos/` conta os 32 testes que passaram e falha com qualquer número menor, porque uma lista de nomes obrigatórios eram 32 linhas a repetir o que o ficheiro já enumera. O «qualquer outra é rejeitada» prova-se pelo complemento: nenhuma célula fica sem decisão escrita (os dois `Record` são completos sobre `Modo` e `Gatilho`, pelo que uma em falta é erro de compilação) e as doze que transitam são exactamente as esperadas, cada uma com a sua **fonte** — dez da tabela do §10.2, uma do diagrama e uma do `E1` §4. **O que não se cumpre:** a primeira cláusula do critério, «`bot→dono` por *echo* com `wamid` ausente de `outbound_messages`». A **célula** está na tabela e tem teste; a **detecção** precisa de `smb_message_echoes`, que é KAM-017. Nas baterias o gatilho `echo_do_dono` é **disparado** pelo ensaio, que é o que a máquina expõe. Idem para o `comando_bot`, que chega pela mesma via. A caixa fica vazia e a decisão sobre o critério devolve-se a quem o escreveu |
| 2 — `PreSendGuard` sob `pg_advisory_xact_lock(hash(tenant_id, contact_id))`, descarta se `mode ≠ bot` ou `last_human_activity_at > início_do_turno`, regista `suppressed_by_human`, devolve o cancelamento | **satisfeito** | **O *lock* serializa de verdade, e é a parte que só uma base real prova.** Em `tests_bd/modos.bd.test.ts`, com uma transição a reter o *lock* numa ligação, a guarda noutra **não resolve** depois de 150 ms — e quando o `COMMIT` sai, entra e vê `dono`. É a metade do critério 8 do KAM-015 que esse ticket teve de deixar por cumprir («**Não há *lock***»). As duas condições têm teste separado: `mode ≠ bot` nos três modos, e `last_human_activity_at` posterior ao turno **com o modo em `bot`**, que é a corrida da §10.3. O `suppressed_by_human` é escrito pelo **guarda** e não pelo adapter, porque na ordem dos sete passos do `ChannelAdapter` o guarda é o 3 e o `SQL_ENFILEIRAR` é o 4 — quando o guarda recusa não há linha para marcar —, e a escrita vai na mesma transacção do *lock*, idempotente por `idempotency_key`. O sinal de cancelamento é o `false` que o adapter converte em `GUARD_REFUSED`. **Duas coisas que o ensaio obrigou a corrigir:** uma conversa que a RLS não vê recusa **sem** escrever linha (a FK composta de `outbound_messages` mataria o `INSERT` com `23503`, e um `throw` no passo 3 deixava o turno sem resposta **e** sem registo), e um envio do bot sem `turnoIniciadoEm` é **recusado** com o motivo `sem_turno` — deixar passar desligava metade deste critério em silêncio |
| 3 — t0 / *echo* em t0+1 s / resposta em t0+2 s → 0 enviadas e 1 suprimido; 100 intercalações → 0 mensagens depois de o *echo* estar registado | **satisfeito** | **Os dois, contra PostgreSQL 18.6.** O primeiro com o relógio injectado: a transição corre com `agora = t0+1 s`, a guarda com `turnoIniciadoEm = t0`, e o que fica na base é **0** linhas em `queued` e **1** em `suppressed_by_human`. O segundo com **semente fixa** (`0x4b414d18`, escrita no ficheiro) e medido: `[KAM-018] 100 intercalacoes (semente 0x4b414d18): 54 passaram, 46 suprimidas; echo primeiro 46 (0 enviadas), guarda primeiro 54`. A propriedade afirmada é a do critério — nas **46** voltas em que o *echo* foi ordenado primeiro, **0** mensagens do bot saíram —, e nas outras 54 o envio é correcto: o *echo* ainda não estava registado quando a guarda leu, que é a janela residual que a §10.3 declara. **E há um segundo teste que corre as 100 duas vezes e compara as sequências**: é ele que impede um `Math.random()` de voltar, porque com um aleatório do sistema as duas divergiam. O número aparece no registo do *gate* por um `print` da *suite*, pela lição que a `tests_chr` escreveu — sem ele, o número existia e ninguém o via. **O *echo* é disparado e não detectado** (KAM-017); o que a corrida mede é o que o critério descreve |
| 4 — o silenciamento é por conversa: duas conversas no mesmo canal, A em `dono` e B em `bot`, respondem independentemente | **satisfeito** | Duas conversas com `channel_id` **igual** — afirmado por `count(DISTINCT channel_id) = 1` antes de medir, senão o teste passava sobre dois canais sem ninguém notar. A transição em A não move o modo de B, a guarda recusa em A e **passa** em B, e no fim A tem uma linha `suppressed_by_human` e B não tem nenhuma. E a outra direcção: o `onOptOut` de um contacto com conversa em **dois** canais pausa as duas e deixa a de outro contacto em `bot` |
| 5 — mensagens em `dono`/`humano` vão ao dono/HND e **não** ao AGR (0 *jobs*) | **satisfeito** | Com o `Chr` do KAM-014 e o `ResolvedorDeCanal` **verdadeiros** sobre a base, e **com controlo positivo**: em `bot` sai **1** *job* para o AGR; nos três modos que não são `bot` o desfecho é `entregue_ao_dono` e o contador de *jobs* não se move — 0 em `dono`, 0 em `humano`, 0 em `pausada`, e três entregas ao dono. Sem o controlo positivo, o zero dos outros não dizia nada. **E a costura entre os dois módulos tem teste próprio:** o `abrirConversa` do CHR devolve o modo que esta máquina escreveu, o que prova que uma entrada que chega **não desfaz** o silenciamento — o `SET` do `SQL_ABRIR_CONVERSA` não toca no `mode`, e agora que `kamba_app` tem o privilégio isso deixou de ser garantido pela ausência dele. O critério 7 do KAM-014 já afirmava a mesma propriedade; aqui ela é medida com a máquina a escrever o valor em vez do `kamba_batch` |
| 6 — cada mudança emite `conversation.mode_changed` (tipo acrescentado ao catálogo, KAM-007) e actualiza o estado visível em HND em ≤ 5 s | **parcial — caixa vazia** | **A emissão cumpre-se; o espelho no HND não, e o tipo não é deste ticket.** Cada transição deixa **uma** linha em `platform.events_outbox` com `tipo = conversation.mode_changed`, `versao = 2` e `classe_pii = P0`, na **mesma transacção** da escrita do modo — há teste que faz a porta de emissão levantar e verifica que a transição foi desfeita, que é a propriedade que o `chr/eventos.ts` **não** tem para o `contact.merged`. Uma corrida perdida **não** emite. **Três coisas que não se cumprem.** (a) O critério diz «tipo acrescentado ao catálogo, KAM-007» e o tipo **já lá estava**: `contratos/eventos/conversation.mode_changed/` tem `v1` e `v2`, nenhuma deste ticket — dívida **80**. (b) A carga publicada é `{thread_id, channel_mode}` com `channel_mode` de **três** valores e `additionalProperties: false`, e os modos são **quatro**: `dono` e `humano` saem os dois como «humano» e um consumidor do barramento não os distingue. Uma `v3` é quebra de contrato com compatibilidade a provar no *gate* 7 e o catálogo é do KAM-007 — inventá-la aqui era decidir por outro ticket. (c) O «≤ 5 s em HND» **não se mede**: o `setBotMuted` do `HandoffProvider` levanta `SemPrivilegioError` (KAM-019) e não há simulador de Chatwoot. O privilégio que o impedia existe agora, mas ligá-lo é alterar o provedor desse ticket. A caixa fica vazia |
| 7 — `onOptOut(contact)` coloca `pausada`; o *timeout* de 24 h corre como *job* idempotente | **satisfeito** | **O `onOptOut` é por contacto e não por conversa**, que é o que o critério escreve: uma transacção, **um** *lock* (a chave é `hash(tenant_id, contact_id)`, e é por isso que ela é por contacto), e todas as conversas do contacto pausadas de uma vez — com uma chave por conversa havia uma janela entre cada par. Repetir o «PARAR» devolve `mudou: false` em todas e **não escreve nada** nem emite evento: a idempotência é da célula `pausada + opt_out`, que é «sem efeito», e não de uma chave. O *job* das 24 h é idempotente **pelo predicado** — correr duas vezes seguidas pausa N e depois 0 — e por isso a revisão `0016` não cria coluna de controlo nenhuma. **E o relógio tem duas origens, o que o critério implica sem dizer:** uma conversa que passou a `humano` e onde **ninguém** respondeu tem `last_human_activity_at` vazio por definição, pelo que o `COALESCE` conta do `max(handoffs.opened_at)` (KAM-019) — testado com duas conversas, uma com um *handoff* de há 30 h (pausada) e outra com dois, o mais recente de há 2 h (não pausada). Com os dois vazios a conversa **não** é pausada e fica em `humano`: é o lado seguro, porque `humano` mantém o bot calado. É uma **função** e não um *job* agendado, pela decisão que a `0005` escreveu para a retenção — o agendador é KAM-071/KAM-078 |
| 8 — métrica `echo_latency_ms` com p50/p95 de ≥ 30 *echoes* reais em *staging* | **não satisfeito — caixa vazia** | **Não se entrega, e não é esquecimento.** A métrica mede a diferença entre o carimbo da Meta e a recepção de um *echo*, e um *echo* só existe em coexistência: a `smb_message_echoes` é KAM-017 e os ≥ 30 *echoes* reais são números +244 em *staging* — é o critério de saída do risco **L6/R6**, cuja mitigação a tabela de riscos deste epic já atribui a KAM-100 («evidência de ≥ 30 *echoes* reais (KAM-018)»). Declará-la e deixá-la a zero era pior: um painel que a mostre a zero diz «a latência do *echo* é nula» quando o que se passa é que ninguém a mede. Nasce com o ticket que a consiga medir, e a decisão fica registada na emenda 1.29 do dicionário |

### Verificação do Definition of Done

| Item | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **não satisfeito — caixa vazia** | Cinco dos oito. Os critérios **1**, **6** e **8** ficam parciais ou não satisfeitos, com a razão na tabela acima: os três dependem de coexistência (KAM-017/KAM-100) ou do catálogo de contratos (KAM-007) |
| Código revisto por 2 revisores; testes verdes; cobertura ≥ limiar | **parcial — caixa vazia** | **Os testes e a cobertura cumprem-se; os revisores não.** `db/gate_bd.py --suite tests_modos` sai com **0** — 7 asserções da *suite*, 108 testes em Node, 0 saltados —, e a cobertura de cada um dos **oito** ficheiros de `src/modos/` está acima do limiar do estrato `critico` lido de `ci/thresholds.yaml` (o número de cada ficheiro é impresso no registo do *gate*). **A caixa dos revisores fica vazia como facto registado**: nesta fase não há revisores humanos, é decisão escrita do fundador, e uma revisão adversarial é evidência e não um revisor. E este PR **altera `ci/thresholds.yaml`** — acrescenta `*/modos/*` ao estrato `critico` —, que é precisamente um ficheiro cuja alteração pede dois revisores: fica dito aqui, em `docs/ci.md` §3 e no próprio comentário do ficheiro |
| Documentação actualizada (`docs/modos-conversa.md`); Conventional Commits | **satisfeito** | `docs/modos-conversa.md` nasce com nove secções, e as §3 e §7 são as que respondem às perguntas que este ticket deixa abertas — as três divergências da §10.2 e o que fica de fora. `docs/ci.md` §3 ganha a secção da *suite* nova e a contagem passa de treze a **catorze**; o `hnd.md` §9, o `consentimento.md` §7 e o `outbound.md` ganham a nota do que mudou para eles. O `canon/dicionario.yaml` foi **regenerado** (`cd tools && python -m dict_export --root ..`): a emenda 1.29 acrescenta 12 entradas ao §3.20, e o `--check` do *gate* 3b compara o ficheiro byte a byte com o Markdown. **Os seis passos dos gates 3 e 3b correm a 0**: `dict_export --check`, `canon_lint check`, `canon_lint canario`, `lint_backlog check`, `lint_refs check` e `lint_handoff check` — e o `canario` entrou nesta lista por aviso de outra sessão, que o viu derrubar o CI do KAM-022. Confirmado que nenhum literal **nu** entrou com domínio, que é a armadilha que a emenda 1.22 pagou com o `tipo`: os únicos literais sem qualificação são o valor `modo` de `reply_suppressed_total.motivo` e o nome da porta `MudarModo`. Os *commits* passam pelo *hook* de `tools/githooks` |
| **Isolamento de tenant** — o *lock* e o modo usam o `tenant_id` do contexto; teste cruzado | **satisfeito** | Nada neste módulo abre ligação: o `ComTenant` não entrega cliente nenhum fora de uma transacção com `set_config('app.tenant_id', …, true)`, pelo que **não há como** escrever o modo nem tomar o *lock* sem contexto. Teste cruzado (X-03): com o contexto de A, a leitura do modo de B devolve **zero linhas** e a máquina levanta `ConversaDesconhecidaError` **sem escrever** — o modo de B fica como estava. E a guarda de A sobre uma conversa de B **recusa** o envio em vez de o deixar passar, sem escrever linha nenhuma |
| **Idempotência** — o mesmo *echo* repetido 2× produz 1 transição; teste incluído | **satisfeito** | Nas duas formas, e a segunda é mais forte do que o critério pede. Em série: a primeira transita, a segunda é «sem efeito» (a célula `dono + echo_do_dono`) e escreve só a actividade humana — **um** evento no outbox. Em paralelo, **duas ligações** a disputar a mesma conversa: exactamente **uma** ganha, e quem perde não emite. Quem decide é o predicado `AND antes.mode = ANY($4)` sob `FOR UPDATE`, não quem leu primeiro — e há uma mutação que lhe tira o `FOR UPDATE` |
| **Privacidade** — sem conteúdo nem telefone em `conversation.mode_changed` nem em logs | **satisfeito** | A carga do evento tem **dois** campos, afirmados por `Object.keys(...).sort()`: o `thread_id` (`{tenant_id}:{contact_id}`, dois UUID nossos — o `contact_id` é a referência opaca do KAM-008) e o `channel_mode`. O `conversation_id` vai no `agregado_id` do envelope, que é onde se audita. Um telefone sintético semeado na conversa **não** aparece na carga, procurado na tabela convertida a texto. Nos registos vai o `outcome` e o `tenant_id`, e mais nada: a *allowlist* do `logger/politica.ts` não tem `conversation_id`, `contact_id` nem `motivo`, e o motivo **é** o desfecho. Nas métricas, nenhuma etiqueta aceita identificador — um UUID com hífenes levanta `SufixoInvalidoError`, e há teste com um `tenant_id` a sério |
| **Custo e observabilidade** — `conv_mode_transitions_total`, `echo_latency_ms`, `reply_suppressed_total` | **parcial — caixa vazia** | **Duas das três, e a terceira não entra com o critério 8.** A `conv_mode_transitions_total` (etiqueta `gatilho`, oito valores) e a `reply_suppressed_total` (etiqueta `motivo`, três valores) existem e têm bateria própria. A `echo_latency_ms` **não**, pela razão do critério 8. E entra uma **quarta** que o DoD não nomeia, a `conv_mode_rejected_total`: é o único sítio onde «qualquer outra transição é rejeitada» fica visível em produção — sem ela, um gatilho mal ligado parece-se com «não houve gatilho nenhum», que é a razão do `chr_resolve_total` da emenda 1.20. A caixa fica vazia enquanto a `echo_latency_ms` não existir |
| **Migrações reversíveis** — `downgrade` testado | **satisfeito** | A revisão `0016` não cria tabela, coluna nem `CHECK` — são dois `GRANT UPDATE` por coluna —, pelo que o `downgrade` não perde dado nenhum e não exige cópia lógica (ao contrário da `0009`, que exige `KAMBA_DOWNGRADE_0009_COPIA`). O ciclo `upgrade`/`downgrade`/`upgrade` corre no *gate* 8 pela *suite* `tests`, e o `test_privilegios.py` passa a esperar **quatro** colunas em `(kamba_app, conversations, UPDATE)` em vez de duas: é ele que vê um `GRANT` desaparecer ou crescer. O `downgrade` revoga **só** as duas desta revisão, e há mutação que o troca pelas quatro — revogar as da `0009` deixava a base pior do que a encontrou, com o CHR sem conseguir empurrar a janela de 24 h |

### O que este ticket desbloqueia, e o que deixa como estava

**Desbloqueia e liga:** a porta `MudarModo` do `ConsentGate` (KAM-022), que a
revisão `0015` deixou por ligar com a razão escrita — «quem a ligar é quem tiver
o privilégio, e este módulo não o tem». Está ligada pelo `portaDoConsentGate`,
que traduz o modo que a porta pede no gatilho da tabela (`humano` por
`handoff_pedido`, `pausada` por `opt_out`), e tem teste nos dois sentidos.

**Fecha a metade que faltava** do critério 8 do KAM-015: a guarda passa a ser
chamada **sob o *lock* da conversa**, que é o que esse ticket deu por não
cumprido. A caixa dele **não** se marca aqui — é dele —, e fica registado que a
razão da sua recusa deixou de existir.

**Deixa como estava:** o `setBotMuted` do `HandoffProvider` (KAM-019) continua a
levantar `SemPrivilegioError`. O privilégio que o impedia existe agora, mas
ligá-lo é alterar o provedor desse ticket, e isso é alargar escopo em silêncio. A
caixa do critério dele fica como está, com a razão já escrita na emenda 1.22.

**Torna falsa uma afirmação do KAM-014**, e corrige-a nos dois sítios: a
verificação do critério 7 desse ticket diz que «`kamba_app` **não consegue**
alterar o `mode` — o privilégio não existe», e a revisão `0016` concede-o. A
frase ganha a nota do que mudou, e o teste de base que a afirmava passou a
afirmar o que continua vedado: as quatro colunas da identidade da conversa.

### O que a revisão adversarial e a prova por mutação mudaram

**A revisão adversarial deu quatro achados, e os quatro eram defeitos reais no
código deste PR.** Os quatro têm correcção, bateria e mutação própria — uma
correcção sem mutação é uma correcção que nada impede de ser desfeita.

1. **O `outcome` do registo levantava com um dos oito gatilhos.** A primeira
   versão escrevia `outcome: modo_rejeitado_<gatilho>`, e o `sem_humano_24h` não
   cabe na gramática do campo: um segmento é letras com até três dígitos **no
   fim**, ou um número, e o `24h` não é nenhum dos dois
   (`logger/politica.ts`). Em modo estrito — o do CI — o `Logger` **levanta**, e
   uma transição rejeitada, que é um resultado normal, passava a excepção não
   tratada no caminho de um *webhook*. É a mesma armadilha que o
   `codigoParaRegisto` do KAM-015 pagou com o `-1`. O gatilho saiu do `outcome`
   (está na etiqueta de `conv_mode_rejected_total`, que é onde a lista é
   fechada) e há bateria que corre **os oito** com um `Logger` estrito.
2. **A métrica contava transições que a transacção desfazia.** O
   `conv_mode_transitions_total` era incrementado **antes** da emissão do evento,
   e as duas escritas vivem na mesma transacção: com a emissão a levantar, o
   `UPDATE` é desfeito e um contador em memória não é desfeito com ele — o painel
   mentia por cima. Passou para depois da emissão, nos dois sítios (`#aplicar` e
   o *job* das 24 h), com bateria em cada um.
3. **A porta do `ConsentGate` prometia não lançar, e lançava.** O `disparar`
   lança `ConversaDesconhecidaError` quando a conversa não é deste *tenant* ou já
   não existe — a retenção do KAM-071 pode tê-la purgado —, e o gate chama a porta
   **depois** de escrever a prova *append-only* e de enviar o aviso: a excepção
   fazia o `tratar` falhar com os dois já escritos, e o *job* repetia-se sobre um
   estado que nunca vai melhorar. A porta apanha **essa** e só essa; qualquer
   outro erro sobe.
4. **Um *fail-open* de um caracter na guarda.** O `last_human_activity_at`
   era convertido com `new Date(valor)` e comparado directamente: um valor
   ilegível dá um `Date` cujo `getTime()` é `NaN`, e **qualquer** comparação
   com `NaN` é falsa — o envio **passava** por causa de um valor que ninguém
   percebeu, que é o contrário do que o guarda existe para fazer. A leitura
   passou a ter três respostas (`Date`, «não houve», «ilegível») e a terceira
   **suprime**.

**A prova por mutação deixou seis sobreviventes na primeira passagem, e as seis
valeram o custo.** Três eram lacunas de teste e viraram testes: o `FOR UPDATE` da
transição (que só se mata correndo o SQL **sem** o *advisory lock*, porque a
máquina toma-o sempre e esconde a diferença) e as duas escritas monótonas de
`last_human_activity_at` (que só se matam com um *echo* fora de ordem — o caso
real, porque a Meta não garante ordem nos *webhooks*). As outras três apagavam
código que nenhum caminho alcança: duas guardas do `transicoes.ts` que **nenhuma
célula da tabela podia accionar**, e a resposta foi **apagar as guardas** e
afirmar o invariante num teste («nenhuma celula aponta para o proprio modo»),
porque uma guarda inalcançável dá a ilusão de proteger e não protege nada; e o
`validarPayload` do evento, cuja precondição nenhum código viola hoje — a chamada
fica, porque é a regra do KAM-007, e o que a protege é um teste de paridade entre
as chaves que se montam e as que o catálogo exige. As três mutações saíram, com a
razão escrita em `db/mutacoes.py`.

No fim: **42 mutações corridas, 0 não apanhadas**
(`python db/mutacoes.py <python> modos`), e `python db/mutacoes.py --aplicaveis`
dá **529 conferidas, 0 não aplicáveis**.

### Quatro divergências registadas

As quatro estão em `../docs/dividas-documentais.md`, linhas **79** a **82**, e
três delas são do bloco deste ticket:

1. **a §10.2 do `../docs/tecnica/01` contradiz-se**, e em duas arestas: o
   diagrama tem `dono → humano` e a tabela não; a tabela tem
   `qualquer → pausada` e o diagrama só tem duas das três arestas. As leituras
   tomadas estão em `../docs/modos-conversa.md` §3 e têm teste;
2. **o critério 6 manda acrescentar ao catálogo um tipo que já lá está**, e não
   nomeia o que de facto falta (o domínio de três valores);
3. **os *Detalhes Técnicos* mandam adicionar o
   `outbound_messages.state='suppressed_by_human'`**, que existe desde a revisão
   `0010`;
4. **o critério 1 escreve «qualquer→`pausada`» para dois gatilhos** e o
   «qualquer» só vale para o opt-out — as 24 h contam-se sobre um *handoff*, e em
   `bot` e em `dono` não há nenhum.

E **uma célula vem de fora da §10.2**, declarada: `pausada + handoff_pedido →
humano`. Nem o diagrama nem a tabela a têm, e o critério 1 não a nomeia — mas o
**Contexto do próprio ticket** cita o `E1` §4 como CONFIRMADO («a Messaging
Policy exige caminho de escalonamento a humano em **todas** as conversas»), e uma
conversa `pausada` é de um cliente que disse «PARAR»: recusar-lhe uma pessoa
quando ele a pede era negar o caminho que a política exige.

### Handoff para Claude Code

```text
És o executor do ticket KAM-018 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-018), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§10.2, §10.3).
Objectivo: modos da conversa (bot, dono, humano, pausada) e silenciamento por echo.
- Máquina de estados com a tabela de transições; silencio_dono_min = 30 (a calibrar); comando /bot.
- Tratador de echoes: wamid ∉ outbound_messages ⇒ actividade humana; PreSendGuard sob pg_advisory_xact_lock.
- Suprime a resposta do bot se mode ≠ bot ou houve actividade humana depois do início do turno; regista
  suppressed_by_human. Mensagens do cliente em dono/humano não vão ao AGR. Emite conversation.mode_changed.
- Mede echo_latency_ms; reúne ≥ 30 echoes reais em staging como evidência de L6.
Não expandas escopo: retoma do grafo (KAM-034), opt-out (KAM-022), Chatwoot (KAM-019).
Testes: transições, 100 intercalações, conversas independentes, evidência de latência. Abre PR com o template do §7.
```

---

## KAM-019 — HND: HandoffProvider e Chatwoot (Agent Bot API, espelho por inbox de tipo API)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-014 |
| Bloqueia | KAM-031, KAM-034, KAM-091 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§11, §14, §15), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.6), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§12), `../docs/tecnica/evidencia/E4_Stack_Licencas.md` (§2.2), ADR-001, ADR-002 |

### Contexto

Adopta-se o **Desenho I** (proposta 01-A): o GWY é o único endpoint Meta; o HND grava no Chatwoot por *inbox* de tipo API; o *Agent Bot* (`outgoing_url` = HND) notifica-nos de mensagens e estados humanos; o envio ao cliente é sempre pelo nosso ChannelAdapter. Factos CONFIRMADOS no código (E4 §2.2): Chatwoot v4.18 é MIT fora de `enterprise/`; Platform API (`accounts`, `users`, `account_users`, `agent_bots`); `AgentBot` com `bot_type=webhook`, `outgoing_url`, `secret`, `access_token`; bot com `account_id` nulo é **global e acessível a todas as contas**; marca branca, SLA, audit logs, SAML, custom roles e Captain/Copilot são Enterprise. **NÃO VERIFICADO (L7):** que o token do *agent bot* consiga passar `pending → open`; plano B: utilizador-serviço «KAMBÁ Bot» com token da Application API. O Chatwoot contém dados pessoais (alojamento sob D1/ADR-008).

### Objectivo

Implementar a interface `HandoffProvider` e a sua implementação Chatwoot: provisionamento de conta/bot/*inbox* por PME, espelho idempotente de mensagens, `openHandoff` idempotente, recepção assinada de eventos humanos e entrega das respostas humanas ao Outbound.

### Critérios de Aceitação

- [x] `ensureAccount(tenantId)` cria (ou devolve) 1 conta Chatwoot por PME, 1 *agent bot* com `account_id` da conta e 1 *inbox* de tipo API; chamado 2× não duplica; um *agent bot* com `account_id` nulo é impossível por construção (teste).
- [x] O Chatwoot não tem credenciais Meta: `WHATSAPP_APP_ID`, `WHATSAPP_CONFIGURATION_ID` e `WHATSAPP_APP_SECRET` não estão configurados e nenhum *inbox* é do tipo WhatsApp (teste de configuração).
- [ ] `mirrorMessage` é idempotente por `wamid`: 3 chamadas produzem 1 mensagem no Chatwoot.
- [ ] `openHandoff` é idempotente por `handoffId = hash(thread_id, ordinal)`: procura a conversa por atributo `handoffId`, senão cria; 5 chamadas concorrentes produzem 1 conversa, passada a `open`, atribuída à equipa, com nota privada com o resumo.
- [x] Os *callbacks* do Chatwoot (`message_created` de agente, `conversation_status_changed`) só são aceites com o `secret` do bot; ausente ou errado devolve 401 e incrementa uma métrica.
- [ ] A resposta humana é enviada ao cliente pelo Outbound (janela, template se fechada, custo registado); com janela fechada o painel recebe aviso e proposta de template *utility*.
- [x] Tabela `handoffs(handoff_id PK, tenant_id, conversation_id, status ∈ waiting|resumed|timeout|cancelled|degraded, opened_at, resumed_at, resolver)` criada com RLS; o `resolved` duplicado não altera nada (a retoma por *compare-and-set* é KAM-034).
- [x] Spike de 1 dia concluído: o resultado de `pending → open` com o token do *agent bot* está em `docs/evidencia/KAM-019-bot-open.md` e a implementação usa a opção que funciona (bot ou utilizador-serviço).
- [ ] Chatwoot indisponível: `openHandoff` falha para uma fila com *retry*, o espelho acumula e reconcilia por `wamid`; healthcheck alerta.
- [ ] Teste X-10: o agente da conta A não lê conversas da conta B (API); tokens de bot cifrados por tenant; o token da Platform API só existe no módulo de provisioning.

### Detalhes Técnicos

- **Componentes:** HND (`services/worker-canal/hnd`). Interface de `../docs/tecnica/01` §11.1:
```ts
interface HandoffProvider {
  ensureAccount(tenantId: string): Promise<{ accountId: number; inboxId: number; botId: number }>;
  mirrorMessage(ctx: ChannelContext, m: MirrorMessage): Promise<void>;                 // idempotente por wamid
  openHandoff(req: { tenantId; contactId; conversationId; handoffId: string; motivo; resumo }): Promise<{ externalId: string }>;
  setBotMuted(conversationId: string, muted: boolean): Promise<void>;
  onHumanEvent(handler: (e: HumanEvent) => Promise<void>): void;
  close(handoffId: string, outcome: 'resolved'|'timeout'|'cancelled'): Promise<void>;
}
```
- **Notificação ao dono:** não pode usar o próprio número da loja; usa notificações do Chatwoot (push/e-mail). Um aviso por *template* a um segundo número do dono é NÃO VERIFICADO e fica fora deste ticket.
- **Licença:** versão fixada (4.18.x) por digest; funcionalidades `enterprise/` não usadas; o mecanismo de verificação (plano *community*) é definido aqui e ligado ao gate «licenças EE» (`../docs/tecnica/09` §7). Dimensionamento: ≥ 4 GB e 4 núcleos (KAM-076/084).
- **Fora de âmbito:** nós de grafo `handoff_prepare`/`handoff_wait` e retoma (KAM-034), provisioning orquestrado (KAM-091), Typebot/n8n (uso interno apenas).

### Testes Requeridos

- Contrato contra Chatwoot real em compose (v4.18.x) com dados sintéticos; idempotência concorrente; *secret* inválido.
- Isolamento: X-10 cross-account; teste de configuração sem credenciais Meta.
- Degradação: Chatwoot parado → fila e reconciliação por `wamid`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (isolamento entre contas, segredos); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/hnd.md`, resultado do spike); Conventional Commits.
- [x] **Isolamento de tenant** — 1 conta por PME, tokens por conta, RLS em `handoffs`; teste cruzado.
- [x] **Idempotência** — `openHandoff` e `mirrorMessage` com teste de repetição.
- [x] **Privacidade** — o Chatwoot só recebe dados da conversa necessários; dados sintéticos fora de `prod`; alojamento sujeito a D1.
- [ ] **Sem segredos** — tokens no cofre; **Dependências** — imagem por digest, sem `enterprise/`.
- [x] **Migrações reversíveis** — `downgrade` de `handoffs` testado.

### Verificação dos Critérios de Aceitação

Entregue no ramo `feature/KAM-019-hnd-chatwoot`.
**Doze caixas marcadas, seis vazias** (18 = 12 + 6) — cada uma com uma linha
aqui. Os números reproduzem-se com `make ci-3b`, `make ci-4`, `make ci-6`,
`make ci-8` e `make chatwoot-spike`; o desenho está em
[`../docs/hnd.md`](../docs/hnd.md).

**Esta secção teve três versões, e vale dizê-lo porque é o resultado do
ticket.** A primeira marcava dez caixas, escrita quando a máquina não conseguia
puxar a imagem do Chatwoot e o critério 8 era um spike que não tinha corrido. A
segunda marcava **sete**: o spike correu, respondeu à pergunta do L7 — **o
*token* do bot chega** — e no caminho até lá mediu quatro coisas que a
implementação fazia de outra maneira, pelo que três caixas tiveram de ser
desmarcadas. Esta terceira marca **dez**, porque o que o spike mediu foi implementado — e
as seis que ficam vazias ficam-no por razões que não são trabalho em falta
neste ticket: um consumidor de fila que é KAM-025, uma equipa que nenhuma fonte
define, um registo de testes que é KAM-066, um alerta que não tem painel onde
viver, o *gate* de licenças que não existe, e zero revisores humanos.

> **A lição, que é maior do que o ticket: um duplo prova que o nosso código chama
> o que pretendíamos chamar. Não prova que o terceiro aceita a chamada.**

As baterias do *gate* 4 estavam certas e estavam verdes, e uma delas **exigia
por asserção** o comportamento que um Chatwoot verdadeiro recusa com 401. O que
o spike mediu, tudo CONFIRMADO contra o v4.18.0 fixado por digest, com o registo
passo a passo em
[`../docs/evidencia/KAM-019-bot-open.md`](../docs/evidencia/KAM-019-bot-open.md):

1. **`pending → open` com o *token* do *agent bot* responde 200**, com
   `"current_status":"open"`. É a pergunta do critério 8, e dispensa o plano B.
2. **O *token* da Platform API responde 401 em `/api/v1/accounts/…`** («not
   authorized for bots»). Cria contas, utilizadores e bots, e mais nada.
3. **Os *endpoints* da conta querem um utilizador** criado por
   `/platform/api/v1/users` e ligado por `account_users`.
4. **O `set_agent_bot` é obrigatório.** Sem ele, `POST /conversations` dá 404 e
   o bot não recebe os *callbacks* do *inbox*.
5. **A conversa quer um contacto que exista**; um `source_id` que o provedor não
   emitiu dá 404.
6. **O *token* do bot responde 401 a criar contactos**, pelo que o do utilizador
   é preciso em execução — é o que põe `provider_user_id` e `user_token_ref` na
   `handoff_accounts` (emenda 1.23).
7. A resposta da criação de contacto tem a forma `payload.contact`.

**E uma revisão adversarial trouxe vinte achados, dos quais três eram afirmações
falsas desta secção.** Ficam ditas aqui em vez de corrigidas em silêncio:

- **«O X-10 não existe em sítio nenhum» era falso.** Existe:
  `../docs/tecnica/08` §3.7 tem a linha `X-10 Medusa/Chatwoot | Cross-seller e
  cross-account | COM, HND`, e o `EPIC-07` atribui a sua inscrição a **este
  ticket**. O `grep` que a sustentava olhou para `db`, `tools`, `ci` e o
  `Makefile`, e a conclusão foi generalizada para «o repositório» — que é
  exactamente a classe de erro que esta *skill* existe para apanhar.
- **«Um pedido sem segredo nunca faz uma consulta» era falso**, e passou a ser
  verdade: o `receber` ia ao cofre **e** fazia um `SELECT` antes de avaliar,
  pelo que o *endpoint* era utilizável como amplificador. Agora recusa antes de
  qualquer I/O, e há asserção a exigir que nada foi consultado.
- **«O predicado explícito protege se alguém desligar o `FORCE`» era falso**: é
  byte a byte o que a política `tenant_iso` gera, e o `FORCE` só vincula o dono
  da tabela.

| CA | Estado | Evidência |
|---|---|---|
| 1 — `ensureAccount` cria 1 conta, 1 *agent bot* com `account_id` e 1 *inbox* de tipo API; 2× não duplica; bot com `account_id` nulo impossível | **satisfeito** | **Seis pedidos, pela ordem que o spike mediu**, com asserção sobre a sequência exacta de URLs. O *inbox* é criado com o *token* do **utilizador** e há teste a exigir que **não** seja o da plataforma — foi a asserção invertida que a primeira versão tinha. O `set_agent_bot` existe e é afirmado, com a razão: sem ele o bot não vê o *inbox* nem recebe os *callbacks* dele. A idempotência é da **chave primária** `(tenant_id, provedor)`: provado contra a base — uma chamada ao provedor, uma linha — e com a linha gravada **zero** chamadas. O `account_id` do bot vai sempre preenchido, com teste a exigir o campo **presente** e não nulo, porque um bot com `account_id` nulo é global e acessível a todas as contas (`E4` §2.2). **E a base fecha dois lados que o critério não pede:** a `handoff_accounts_conta_uq` recusa a mesma conta do provedor em dois *tenants* (provado, `23505`), e a `handoff_accounts_utilizador_uq` faz o mesmo pelo utilizador — a conta fechada sem o utilizador fechado era meia fechadura |
| 2 — o Chatwoot não tem credenciais Meta: as três variáveis não estão configuradas e nenhum *inbox* é do tipo WhatsApp | **satisfeito** | **As duas metades estão medidas.** O spike confere as três variáveis **no `env` do contentor a correr** e as três estão ausentes — que é a única forma de a asserção valer, porque uma variável pode entrar por `.env`, por herança ou embutida na imagem, e nenhuma dessas aparece no YAML. Um ficheiro de compose que não as menciona é configuração, não é teste; isto é o teste. A segunda metade: o `TIPO_DE_INBOX` é `api`, o *inbox* criado veio `Channel::Api` do próprio Chatwoot, e há teste a afirmar que **não** é `whatsapp` — o GWY é o único ponto que fala com a Meta (ADR-001) e um *inbox* de WhatsApp aqui era um segundo caminho para o mesmo número |
| 3 — `mirrorMessage` é idempotente por `wamid`: 3 chamadas produzem 1 mensagem **no Chatwoot** | **parcial — caixa vazia** | **A de-duplicação está provada e a entrega não existe.** Três chamadas com o mesmo `wamid` deixam **uma** entrada na fila, e quem de-duplica é o `jobId`, que **é** o `wamid`; o limite fica dito e é o do `chr/fila.ts` — um *job* em `failed` bloqueia o mesmo `wamid` até sair. A carga **não leva `contact_id`**, com teste a procurá-lo. Não há tabela de fila, e é decisão escrita: o §14 pede uma fila que «reconcilia por `wamid`», e uma tabela ao lado de uma fila era um segundo sítio para a mesma verdade. **O defeito do `espelhar` está corrigido** — punha o `wamid` no URL onde vai o identificador da **conversa**, pelo que qualquer chamada real dava 404, e o teste de então afirmava o corpo e nunca o `url`; agora o `externalId` é argumento e há asserção sobre o URL **e** sobre o `wamid` não entrar nele. **Mas a caixa fica vazia**: o critério diz «no Chatwoot», e não há consumidor da fila neste ticket (é KAM-025), pelo que nenhuma mensagem chega lá |
| 4 — `openHandoff` idempotente por `handoffId = hash(thread_id, ordinal)`: procura por atributo, senão cria; 5 chamadas concorrentes produzem 1 conversa, passada a `open`, atribuída à equipa, com nota privada | **parcial — caixa vazia** | **Quatro das cinco partes cumprem-se.** Cinco chamadas concorrentes, contra a base e em **duas ligações**, deixam **uma** linha e fazem **uma** chamada ao provedor, e isso é da chave primária com o `handoff_id` **derivado** — o que faz cinco processos chegarem ao mesmo valor sem se falarem. «Passada a `open`»: `status: "open"` no corpo, e o spike **mediu** que o *token* do bot o consegue. A nota privada vai com o resumo e **depois** da conversa: se falhar, alguém atende sem o resumo, e o contrário não serve a ninguém; e um 200 com corpo vazio na nota já **não** derruba a passagem, que era o caminho pelo qual uma conversa criada ficava órfã. O contacto vem antes da conversa, com o *token* do utilizador, e o `source_id` é o que o provedor emitiu. **O que falta:** «procura a conversa por atributo `handoffId`, senão cria» — o atributo é **escrito** e nada o **procura**, porque o `ClienteDoProvedor` não tem operação de leitura; e «atribuída à equipa», porque **não existe equipa** em documento, dicionário ou código (dívida 60) |
| 5 — os *callbacks* só são aceites com o `secret` do bot; ausente ou errado devolve 401 e incrementa uma métrica | **satisfeito** | Os quatro motivos da lista fechada dão **401** e cada um conta na sua etiqueta: `sem_secret`, `secret_errado`, `tipo_desconhecido`, `conta_desconhecida`. Três decisões com teste próprio: **um segredo esperado vazio recusa tudo** — se o cofre não devolveu nada, nenhum *callback* passa, e sem essa linha uma configuração em falta tornava-se porta aberta, e passaria todos os outros testes do ficheiro; a comparação é de **tempo constante**, porque `===` sobre cadeias sai no primeiro carácter diferente; e **um pedido sem segredo é recusado antes de qualquer I/O**, com asserção a exigir que nem a base nem o cofre foram consultados. Essa última era a afirmação falsa da versão anterior, e tornou-se verdadeira: um pedido com segredo **errado** continua a custar uma consulta, e isso é inevitável — para saber que está errado é preciso saber qual era o certo. Os três tipos que não tratamos são **recusados** e não ignorados: com um 200 silencioso o provedor pára de reenviar |
| 6 — a resposta humana é enviada ao cliente pelo Outbound (janela, template se fechada, custo registado); com janela fechada o painel recebe aviso e proposta de template *utility* | **parcial — caixa vazia** | **A costura está feita e duas partes do critério não estão medidas.** Os testes montam um `Saida` **verdadeiro** com a base e a Meta por porta, e `doBot: false` — o guarda desta montagem recusa **sempre** e a resposta sai, porque recusar a resposta da pessoa que o modo humano existe para servir era o contrário do que ele protege. A chave de idempotência deriva do **identificador da mensagem no provedor**: dois *callbacks* do mesmo `message_created` dão **uma** mensagem, e duas mensagens iguais do agente («ok») com ids diferentes saem **as duas**. Sem esse identificador **não se envia**. Com a janela fechada não se envia, não se gasta chamada à Meta, e o painel recebe o aviso com o texto que não saiu e o template proposto. **O que não está:** «custo registado» não tem asserção — delega-se no Outbound por escrito, e a base falsa deste ficheiro não modela o `pricing`; e «template se fechada» **propõe-se e não se envia**, decisão defensável e escrita (é pago, e a decisão de gastar é da PME) mas metade do critério à letra |
| 7 — tabela `handoffs(...)` criada com RLS; o `resolved` duplicado não altera nada | **satisfeito** | A tabela tem `ENABLE`, `FORCE` e a política `tenant_iso`, e a descoberta do X-05 passa de dezanove a **vinte e uma** tabelas. **Nove colunas e não sete**: acrescentam-se o `motivo` (o `openHandoff` recebe-o, e sem ele a linha não diz porque é que alguém foi chamado) e o `external_id` (ele devolve-o e não tinha onde ficar). O `resolved` duplicado é *no-op* **pela base**: o `WHERE status = ANY($3)` faz o segundo `UPDATE` não casar, provado com **dois `close` em paralelo em duas ligações** — as métricas dos dois somadas contam **uma** passagem fechada. **E o *no-op* silencioso está fechado**, que era o defeito mais caro deste módulo: o `SQL_FECHAR` lê o *tenant* do contexto da sessão porque a assinatura do §11.1 não o traz, e com a forma `current_setting(..., true)` uma variável não definida devolvia `NULL` — zero linhas, nenhuma métrica, nenhum registo, e 200 ao provedor, que pára de reenviar. A forma estrita **levanta**, e há teste contra a base, com uma ligação sem contexto, a exigir a excepção. Um fecho que não casa por outra razão deixa rasto |
| 8 — spike de 1 dia concluído: o resultado de `pending → open` com o *token* do *agent bot* está em `docs/evidencia/KAM-019-bot-open.md` e a implementação usa a opção que funciona | **satisfeito** | **Concluído, com veredicto `O TOKEN DO BOT CHEGA`**, e a implementação usa essa opção: o `abrirConversa` chama com o *token* do bot. O plano B (um utilizador-serviço com *token* da Application API) **não é preciso para o estado** e fica arquivado — mas não apagado, e a razão é instrutiva: o spike mostrou que o *token* do bot **não** chega para contactos, pelo que a ideia de um utilizador-serviço não morreu, mudou de sítio. É agora o utilizador da conta do critério 1. O caminho até ao veredicto custou cinco corridas e cinco defeitos meus, todos no ficheiro de evidência: a montagem do PostgreSQL 18 (`/var/lib/postgresql`, não `/data` — o aviso está por escrito no `docker-compose.dev.yml` desde o KAM-001), o corpo truncado a 400 caracteres **antes** do `json.loads`, uma excepção a escapar depois do `finally`, a política de palavra-passe do Chatwoot, e `payload` onde era `payload.contact` |
| 9 — Chatwoot indisponível: `openHandoff` falha para uma fila com *retry*, o espelho acumula e reconcilia por `wamid`; *healthcheck* alerta | **parcial — caixa vazia** | **Tudo menos o alerta.** Com o provedor em baixo a passagem fica `degraded`, a abertura vai para a fila, **a linha fica** — e é isso que faz o painel ver o atraso em vez de a passagem desaparecer — e a métrica conta. E `degraded` **conta no SLA**, provado contra a base: uma passagem que nem chegou ao provedor está tão longe de ser atendida como uma à espera. A recuperação é do `SQL_MARCAR_ABERTA`, que aceita sair de `degraded` — **e o resultado dele já se lê**: descartá-lo dizia `waiting` a quem chamava quando a passagem estava `resumed`, contava uma passagem que já fechara, e deixava a conversa do provedor sem nada a apontá-la; agora devolve o estado da base e deixa rasto. **O que não existe:** o *healthcheck* que **alerta**. A grandeza está medida — `hnd_mirror_pendentes`, *gauge*, a única que distingue «ninguém falou» de «ninguém conseguiu espelhar» — e nada a lê: não há painel nem regra de alerta neste repositório (é KAM-084/085). Expor a métrica não é alertar |
| 10 — teste X-10: o agente da conta A não lê conversas da conta B (API); *tokens* de bot cifrados por *tenant*; o *token* da Platform API só existe no módulo de *provisioning* | **parcial — caixa vazia** | **Duas das três partes cumprem-se, e a terceira não tem onde viver.** O **isolamento está provado**, como X-03: com o contexto de A as passagens de B não aparecem, uma escrita na linha de B não acontece (com `FORCE`, nem como dono), e as duas `UNIQUE` recusam a mesma conta **e** o mesmo utilizador do provedor em dois *tenants*. **O *token* da Platform API passou a estar confinado**, que era a parte que falhava: o `ProvisionadorDoChatwoot` é o único objecto que o tem, o `ClienteDoChatwoot` não o conhece, e há teste a afirmar que nenhum pedido de execução leva aquele *token* nem toca em `/platform/api/` — é o `../docs/tecnica/08` §3.6 à letra, e antes era só um parâmetro distinto, que não é um processo distinto. **O que falta:** o **X-10 existe** (`08` §3.7, atribuído a este ticket pelo `EPIC-07`) e o registo que o hospedaria não — o `registerCase({id, camada, enumeravel, fn})` do `EPIC-07` não existe em código (`grep` dá zero; é KAM-066), pelo que a caixa fica vazia por **dependência**. E os *tokens* **não são «cifrados por tenant»**: são `SecretRef` opacas, que é o desenho do KAM-010, mais forte (não há chave nossa a proteger) e **diferente** do que o critério diz |
| DoD — todos os CA satisfeitos e demonstráveis | **não satisfeito — caixa vazia** | Seis de dez. Dos quatro que faltam: um pede um consumidor de fila que é KAM-025 (3), um pede uma equipa que nenhuma fonte define e uma busca por atributo que não existe (4), um pede um alerta que não tem onde viver (9), e um pede um registo de testes que é KAM-066 (10) |
| DoD — 2 revisores (isolamento entre contas, segredos); testes verdes; cobertura ≥ limiar | **não satisfeito — caixa vazia** | **Zero revisores humanos**: uma revisão adversarial é evidência, não é um revisor — ainda que esta tenha trazido vinte achados, corrigido três afirmações falsas e encontrado uma mutação **imortal**. Testes verdes e cobertura: ver a tabela de execução |
| DoD — documentação actualizada (`docs/hnd.md`, resultado do spike); Conventional Commits | **satisfeito** | [`../docs/hnd.md`](../docs/hnd.md) v1.1, com a §3 inteira dedicada ao que o spike mediu — a sequência de seis pedidos, os três segredos, e porque é que a chave do contacto é opaca. `docs/evidencia/KAM-019-bot-open.md` com o resultado **tal como ele saiu**, dicionário §3.15 (emendas 1.22 e 1.23), `../docs/ci.md` e `../docs/dividas-documentais.md`. Conventional Commits imposto pelo `tools/githooks/commit-msg` |
| DoD — isolamento de *tenant*: 1 conta por PME, *tokens* por conta, RLS em `handoffs`; teste cruzado | **satisfeito** | «Uma conta por PME» é a chave primária `(tenant_id, provedor)` e não uma verificação em código; os *tokens* são por conta — **dois** agora (`chatwoot_bot_token` e `chatwoot_user_token`, ambos `instancias: conta` em `ops/secrets-inventory.yaml`); as duas tabelas têm `FORCE` e `tenant_iso`; o teste cruzado está no X-03. A FK da conversa é **composta** com o `tenant_id`, pela razão da `0009`: sem ela, uma passagem de A podia apontar para uma conversa de B e nem o *gate* 6 nem o 3b o veriam |
| DoD — idempotência: `openHandoff` e `mirrorMessage` com teste de repetição | **satisfeito** | Cinco aberturas concorrentes contra a base dão uma linha e uma chamada; três espelhos com o mesmo `wamid` dão uma entrada na fila. **Fica dito o que estes testes não cobrem**, porque a versão anterior desta caixa não o dizia: as duas são sobre o **nosso** lado, e sem a busca por atributo `handoffId` (critério 4) duas aberturas que a nossa base não correlacione criariam duas conversas no Chatwoot. O caminho em que isso morde é o `degraded`, e está nomeado na caixa do critério 9 |
| DoD — privacidade: o Chatwoot só recebe dados da conversa necessários; dados sintéticos fora de `prod`; alojamento sujeito a D1 | **satisfeito** | **A fuga está fechada**, e era real: o `abrirConversa` mandava o nosso `contact_id` como `source_id`, contra o ADR-010, no mesmo módulo que diz na nota do `MirrorMessage` que isso não se faz — e os quatro testes de então inspeccionavam o atributo, o *inbox*, o estado e o *token*, e **nenhum** procurava o identificador no corpo. Agora entra uma `chaveDoContacto` opaca, derivada por quem chama, e há teste a varrer **tudo** o que foi escrito à procura de um identificador nosso, e a exigir que o contacto não leve telefone nem nome. O `MirrorMessage` tem cinco campos e o que não está neles é o ponto; do agente lê-se **só o `id`**, com o `name` e o `email` a chegarem no mesmo objecto. O compose usa dados sintéticos, escuta só em `127.0.0.1`, e as quatro listas de saídas estão **vazias** com `por_omissao: negar` — um Chatwoot sem rota de saída não leva conversa de clientes para fora por SMTP nem por telemetria. O alojamento com dados reais é **D1**, dito em três sítios |
| DoD — sem segredos (*tokens* no cofre); dependências (imagem por digest, sem `enterprise/`) | **parcial — caixa vazia** | **Duas das três medidas.** Os *tokens* estão no cofre, e agora há um caminho que os leva lá: o `ensureAccount` recebe os dois `access_token` — que o provedor mostra **uma única vez**, no corpo da criação — e guarda-os pela porta `guardarSegredo`, com teste a afirmar que **as referências** vão para a base e os *tokens* **não**. Antes nada os capturava: dois segredos gerados e perdidos. O `scan_secrets` está limpo. As imagens estão **fixadas por digest** — **três** distintas e três digests, não quatro: o `chatwoot` e o `chatwoot-worker` partilham a mesma. **O «sem `enterprise/`» não está medido**, e o que o mediria não existe: o ticket cita um «gate de licenças EE (`../docs/tecnica/09` §7)» que **não é um gate** — o §7 é «CI/CD» e tem uma linha de tabela, e em código o único mecanismo é o campo `ee` de `ci/supply-chain/licencas.yaml`, que é texto. Registado nas dívidas |
| DoD — migrações reversíveis: `downgrade` de `handoffs` testado | **satisfeito** | Bateria própria (`db/tests/test_handoff_schema.py`), **oito casos**. Com as duas tabelas vazias desce e sobe; **com linhas e sem `KAMBA_DOWNGRADE_0011_COPIA` recusa**, com as duas contagens na mensagem, e deixa o `FORCE` das duas **intacto** — a recusa não pode trocar uma perda de dados por um furo de isolamento. Com a variável, escreve a cópia das nove colunas de cada passagem e das **dez** de cada conta (eram oito: o `provider_user_id` e o `user_token_ref` entraram pela emenda 1.23), e é esse o motivo mais forte da recusa: os identificadores da conta, do bot, do *inbox* **e do utilizador** ficam a existir lá fora, e sem a linha que os aponta o `ensureAccount` seguinte cria uma segunda conta para a mesma PME — o que o critério 1 proíbe e que nenhuma migração nossa pode desfazer. **As políticas saem antes de se contar**, pela lição da `0009` e da `0010`. E a bateria afirma uma **ausência**: não há `CHECK` sobre o `resumed_at` nem sobre o `resolver` |

**Como se correu, e o que saiu.** Nesta máquina não há `make`, `node` nem
`pnpm` no `PATH`, e tudo o que se segue correu em Docker ou no `.venv`:

| Verificação | Comando | Resultado |
|---|---|---|
| *gate* 3 (referências, *handoff*, backlog) | `lint_refs`, `lint_handoff`, `lint_backlog` | `conforme`, **código 0** — 16831 referências em 1092 ficheiros; 636 caminhos em 160 blocos; as três superfícies do backlog a dizer o mesmo |
| *gate* 3b (nomes canónicos) | `dict_export --check`, `canon_lint check` e `canario` | `conforme`, **código 0** — dicionário v1.23, 26 extensões, 11 migrações, 27 tabelas, **228 colunas**, 108 valores de `CHECK`; o canário dá 10 negativas vermelhas com a mensagem esperada e 10 positivas verdes |
| *gate* 2 (tipos e arquitectura) | `tsc --noEmit` sobre `src` e `tests`, `lint_arch all`, `log_policy lint` | limpo; `conforme`; **0 achados** em 113 ficheiros TS/JS e 34 Python |
| *gate* 4 (baterias da passagem) | `node --test` sobre os cinco `tests/hnd.*.test.ts` | **108 testes, 108 passam** (eram 89 antes das correcções) |
| *gate* 6 (isolamento) | `db/gate_bd.py --suite tests_isolamento` | **78 testes, OK** — com as duas tabelas novas semeadas, e o X-05 de dezanove para **vinte e uma** |
| *gate* 8 (migrações) | `db/gate_bd.py --suite tests` | **415 testes, OK**, em 135 s |
| *gate* 8 (passagem a humano) | `db/gate_bd.py --suite tests_handoff` | **5 asserções Python sobre 6 ficheiros de teste Node, OK**, em 14 s; cobertura de `src/hnd/` entre **90%** (`metricas.ts`) e **100%** em dez módulos, contra o limiar de 75% do estrato `restante` |
| *gate* 11 (cadeia de abastecimento) | `supply_chain check` | `conforme`, **código 0** — pediu `read_only: true` nos quatro serviços do compose e as quatro listas de saídas, que ficaram escritas; 23 referências a 6 imagens, todas por digest |
| prova por mutação | `db/mutacoes.py --aplicaveis` e as 26 do módulo por filtro | **362 mutações, 0 não aplicáveis**; as 26 do módulo e as 9 da revisão correram, e **quatro sobreviveram à primeira**, as três por razões que valem mais do que o número; depois das correcções as corridas repetidas dão **26 + 9 corridas, 0 não apanhadas** — ver o parágrafo abaixo. **35 mutações são deste ticket**, das quais doze prendem o que o spike e a revisão fecharam |
| spike do L7 | `make chatwoot-spike` | **`O TOKEN DO BOT CHEGA`** — nove passos, veredicto conclusivo, à quinta corrida |

#### O que a prova por mutação encontrou, e que nenhum teste vermelho mostrava

As 26 mutações do módulo correram pela primeira vez neste ticket, e
**sobreviveram três**. Nenhuma das três era um teste em falta: eram três
afirmações a contar como prova sem o serem.

1. **Duas mutações eram imortáveis**, e uma delas ainda o é por natureza.
   «um segredo esperado vazio deixa de recusar tudo» apagava a linha
   `if (esperado.length === 0) return false;` — e **não muda comportamento
   nenhum**, porque a verificação de comprimento três linhas abaixo já recusa um
   esperado vazio. A linha fica, porque diz a intenção; a mutação passou a
   inverter o **sentido** (`return true`), e essa morre. A segunda —
   `timingSafeEqual(a, b)` trocado por `recebido === esperado` — **não tem
   substituta e foi retirada**: chegados ali os dois *buffers* têm o mesmo
   comprimento, pelo que as duas expressões dão o mesmo resultado para toda a
   entrada. A diferença é o **tempo**, e o tempo não é observável num teste
   unitário. **Fica dito, no código e aqui: a propriedade de tempo constante não
   tem teste.** Uma mutação que nenhum teste pode matar contaria como prova de
   uma garantia que não temos, que é pior do que não a ter.
2. **O `ON CONFLICT` da conta não era exercitado por teste nenhum.** Apagá-lo
   deixava a *suite* verde, e a razão é o caminho rápido: duas chamadas
   **sequenciais** a `ensureAccount` encontram a linha na leitura e nunca chegam
   ao `INSERT`. O único caminho que o provoca é o concorrente, e o teste de
   concorrência que havia era do `openHandoff`. Entrou um contra a base, com
   duas ligações, que faz as duas chamadas passarem a leitura e tentarem ambas
   inserir — sem o `ON CONFLICT`, a segunda levanta `23505`.
3. **A terceira imortal estava declarada e foi substituída** antes de correr:
   «o fecho deixa de ler o tenant da sessao» trocava o predicado por
   `WHERE true`, que sob RLS é semanticamente igual para o `kamba_app` e que a
   base falsa nunca lê. A que ficou troca a forma **estrita** do
   `current_setting` pela *lenient*, e essa morre contra a base.

4. **Uma unicidade passava por causa da outra.** A mutação que apaga a
   `handoff_accounts_conta_uq` sobrevivia em `tests_handoff`: apagada a
   restrição, a `handoff_accounts_utilizador_uq` apanhava o mesmo caso — porque
   a conta de ensaio colidia nos **dois** campos — e a asserção aceitava
   qualquer «duplicate key». **Um teste que passa por causa de outra fechadura
   não prova a que diz provar.** O teste foi apertado (asserção pelo **nome** da
   restrição, e o `provider_user_id` deliberadamente diferente), ganhou um irmão
   que faz o inverso para o utilizador, e a mutação passou para a *suite* onde a
   `test_handoff_schema` afirma as três restrições uma a uma. **Uma mutação na
   *suite* errada é pior do que nenhuma**, e é a terceira vez que este projecto
   o aprende.

**É o segundo achado mais valioso do ticket, depois do spike**, e pela mesma
razão: uma máquina perguntou «este teste falharia?» a asserções que pareciam
fortes, e quatro responderam que não.

#### Os quinze defeitos que o spike, a revisão e as mutações fecharam

Nenhum destes aparecia num teste vermelho, e é isso que os torna o resultado do
ticket. Por gravidade:

1. **O provisionamento não funcionava** — o *inbox* era criado com o *token* da
   plataforma (401), faltava o utilizador da conta, e faltava o `set_agent_bot`.
2. **O nosso `contact_id` ia para fora** no `source_id` da conversa, contra o
   ADR-010 — e dava 404 de qualquer maneira.
3. **O `espelhar` punha o `wamid` no URL** onde vai o identificador da conversa.
4. **O `close` sem contexto de sessão era um *no-op* silencioso**, e respondia
   200 ao provedor, que pára de reenviar.
5. **Uma mutação imortal contava como prova.**
6. **O resultado do `SQL_MARCAR_ABERTA` era descartado**, pelo que o estado
   devolvido podia ser falso.
7. **O `#pedir` lia JSON em todas as chamadas**, pelo que um 200 sem corpo
   degradava uma passagem cuja conversa já existia.
8. **Os dois `access_token` perdiam-se** — o provedor mostra-os uma vez e nada
   os capturava.
9. **O `resolver` nunca era escrito** (`$4` sempre nulo).
10. **O `SQL_REPOR_CONTA` não tinha chamador**, e a `0011` concedia
    `GRANT UPDATE` para ele — o que a `0009` recusou por escrito.
11. **O *token* da Platform API vivia no cliente de execução**, contra o
    `08` §3.6.
12. **O `ON CONFLICT` da conta não tinha teste** — nenhum caminho o exercitava.
13. **Uma mutação redundante contava como prova** da falha fechada do segredo.
14. **Uma mutação sobre tempo constante contava como prova** de uma propriedade
    que nenhum teste unitário pode verificar.
15. **Uma das duas unicidades passava por causa da outra**, e a mutação da
    primeira estava na *suite* errada.

#### Decisões tomadas neste ticket

- **A emenda ao dicionário veio antes do código, e a segunda veio da medição.**
  A 1.22 porque dois dos tipos da interface estavam **só nomeados** no §11.1; a
  1.23 porque o spike encontrou um terceiro ator que nenhuma leitura tinha
  visto.
- **`provider_user_id` e não `user_id`**: a KAMBÁ vai ter utilizadores seus
  (KAM-091), e um nome genérico cai na regra da emenda 1.14 — um domínio sobre
  um nome genérico vale para todas as colunas com esse nome.
- **A chave da passagem é texto e derivada**, contra o hábito do §2: é
  `hash(thread_id, ordinal)`, e é isso que faz cinco processos concorrentes
  chegarem ao mesmo valor sem se falarem.
- **Não há `GRANT UPDATE` em `handoff_accounts`**, e a entrada da matriz de
  privilégios fica com o conjunto **vazio** em vez de desaparecer: afirma a
  ausência, pelo que reconceder falha um teste.
- **Não há `CHECK` sobre o `resumed_at` nem o `resolver`**, e a ausência tem
  teste: uma restrição sobre colunas que nenhum código toca seria descoberta
  pelo KAM-034 contra linhas que já existem.
- **Os *callbacks* verificam-se no HND e não no GWY**: dois documentos do mesmo
  nível discordam e a ordem de fontes não desempata. O que desempata é o
  `secret` ser por bot, logo por *tenant*, e o GWY ser o único ponto sem
  contexto de *tenant*.
- **O plano B do L7 fica arquivado e não apagado.** O *token* do bot chega para
  o estado e **não** chega para contactos, pelo que a ideia de um
  utilizador-serviço mudou de sítio em vez de morrer.

### Handoff para Claude Code

```text
És o executor do ticket KAM-019 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-019), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§11) e
docs/tecnica/08_Seguranca_Conformidade.md (§3.6). Objectivo: HandoffProvider com Chatwoot (Desenho I).
- Uma conta Chatwoot por PME; agent bot com account_id; inbox de tipo API; zero credenciais Meta no Chatwoot.
- mirrorMessage idempotente por wamid; openHandoff idempotente por handoffId (atributo na conversa);
  callbacks só com o secret do bot; resposta humana pelo Outbound (KAM-015).
- Tabela handoffs com RLS. Spike de 1 dia: pending→open com token de bot (L7); plano B utilizador-serviço.
- Não uses nada de enterprise/ (marca branca, SLA, audit logs, SAML, custom roles, Captain/Copilot).
Não expandas escopo: nós do grafo e retoma por CAS são KAM-034; provisioning é KAM-091.
Testes: Chatwoot real em compose, concorrência, X-10, degradação. Abre PR com o template do §7.
```

---

## KAM-020 — Mídia: download autenticado, armazenamento e URL interna assinada

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-013, KAM-011, KAM-024 |
| Bloqueia | KAM-036, KAM-049, KAM-071 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§5.4), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.8, §7.5), `../docs/tecnica/00_Arquitectura_Solucao.md` (MED, STO), ADR-013, ADR-014 |

### Contexto

Áudio, imagens e documentos recebidos chegam por `media_id` e têm de ir para o `StorageProvider` (ADR-014); o URL da Meta expira e **nunca** é persistido. O MED serve STT (KAM-036), Catálogo AI (KAM-049), KYC (KAM-087) e o espelho para o Chatwoot. Uma imagem pode ser um comprovativo de pagamento, mas **nunca é prova** (ADR-013): o MED não tem caminho para alterar estado de pagamento. As páginas de referência da API de mídia não foram lidas em E1 (limitação declarada): o fluxo de duas etapas (resolver o `media_id`, descarregar com autenticação) deve ser confirmado na documentação vigente antes de implementar.

### Objectivo

Implementar o pipeline MED de recepção: descarga autenticada, validação, armazenamento por tenant, registo em `media_assets` e emissão de URL interna assinada de curta duração.

### Critérios de Aceitação

- [ ] Uma mensagem `image|audio|document` com `media_id` resulta em 1 objecto em `t/{tenant_id}/media/{classe}/{aaaa}/{mm}/{uuid}` e 1 linha em `media_assets` (`tenant_id, contact_id, conversation_id, wamid, classe, content_type, size, sha256, storage_ref, estado, retain_until`).
- [x] Idempotência: a mesma `(tenant_id, wamid, media_id)` processada 3× produz 1 objecto e 1 linha (`UNIQUE`).
- [x] Nenhum URL da Meta é persistido (BD, logs, eventos): teste que percorre as tabelas e logs de uma execução por padrões do domínio da Meta.
- [x] Validação por *allowlist* de `content_type` (proposta: JPEG, PNG, WebP, OGG/Opus, PDF) e tamanho máximo por classe configurável (valores a calibrar contra os limites da Meta, NÃO VERIFICADOS); tipo ou tamanho inválido → `estado='rejeitado'` e resposta determinística pedindo outro formato.
- [x] URL interna assinada com TTL ≤ 300 s para consumidores autorizados; com `ctx` de outro tenant é recusada (X-08); depois do TTL devolve 403.
- [x] Falha de descarga: 3 tentativas com *backoff*; depois `estado='falhou'` e sinal ao AGR para pedir ao cliente que reenvie.
- [x] Áudio: `retain_until = criação + 24 h` (alvo de `../docs/tecnica/08` §7.5; limite de erro 72 h) e gancho `onTranscribed(asset)` que agenda a eliminação do blob; a purga em si é KAM-071.
- [x] O MED não importa módulos de PAY nem de COM (teste de arquitectura): 0 caminhos de código que alterem estado de pagamento a partir de uma imagem.
- [x] Métricas `media_bytes_total{classe}`, `media_download_ms`, `media_rejected_total{motivo}` sem conteúdo nos logs.

### Detalhes Técnicos

- **Componentes:** MED, STO (via `StorageProvider` de KAM-011), GWY/*worker* de canal (origem do evento).
- **Fluxo:** `media_id` → resolver URL temporário com o token do canal (cofre) → descarregar → calcular `sha256` → `put` → registar → emitir referência interna `media://{asset_id}`; consumidores pedem `signUrl`. O *worker* corre sob contexto de tenant (CHR já resolvido).
- **Deduplicação por conteúdo:** `sha256` por tenant evita duplicar armazenamento (opcional; registar contagem); fotos de produto vivem enquanto o catálogo viver.
- **Segurança:** análise de malware/conteúdo activo em ficheiros carregados não consta de `../docs/tecnica/`; fica como item do modelo de ameaças (KAM-065) e limita-se aqui a *allowlist* de tipos.
- **Fora de âmbito:** STT (KAM-036), visão/Catálogo AI (KAM-049), KYC (KAM-087), purga (KAM-071), crypto-shredding por DEK de contacto (KAM-070/071).

### Testes Requeridos

- Unit: validação de tipos/tamanhos; geração de chaves; idempotência.
- Integração com Graph falsa (KAM-024) e `StorageProvider` *fake*/SeaweedFS: sucesso, URL expirado, falha de descarga.
- Isolamento X-08 e teste de arquitectura (sem PAY/COM); *grep* de URLs da Meta.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dados pessoais, isolamento); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/media.md`); Conventional Commits.
- [x] **Isolamento de tenant** — prefixo por tenant, RLS em `media_assets`, teste cruzado X-08.
- [x] **Idempotência** — `UNIQUE` e teste de repetição.
- [x] **Pagamento só por evento autenticado** — nenhuma imagem altera estado de pagamento (teste de arquitectura).
- [x] **Privacidade** — áudio com retenção curta; sem URLs da Meta nem conteúdo em logs.
- [x] **Custo e observabilidade** — métricas de bytes, latência e rejeição desde o código.
- [x] **Migrações reversíveis** — `downgrade` de `media_assets` testado.

### Verificação dos Critérios de Aceitação

Entregue no ramo `feature/KAM-020-med-midia`.
**Quinze caixas marcadas, três vazias** (18 = 15 + 3) — cada uma com uma linha
aqui. Os números reproduzem-se com `make ci-3b`, `make ci-4`, `make ci-6` e
`make ci-8`; o desenho está em [`../docs/media.md`](../docs/media.md).

**O bloqueio de origem deste ticket não é código: é que a API de mídia da Meta
não tem evidência nenhuma.** O `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`
não tem a página de referência e **nem a lista como omissão** — não há limite de
tamanho por tipo, nem tempo de expiração do URL, nem o fluxo de duas etapas
confirmado, nem os códigos de erro. O próprio bloco o diz («as páginas de
referência da API de mídia não foram lidas em E1 (limitação declarada)»), e a
consequência é que **tudo o que este módulo supõe sobre ela é *proposta***, com
o sítio onde calibra dito em cada constante: o primeiro contacto com a API real,
que é `ext:KAM-101` e `ext:KAM-102`. É por isso também que o `ClienteDeMidia`
entra por **porta** e que não há simulador: um simulador de uma API que não
conhecemos seria uma invenção a fingir medição.

**E a lição do KAM-019 moldou esta entrega desde o início.** Lá, as baterias
estavam todas verdes e metade do provisionamento recebia 401 de um Chatwoot
verdadeiro:

> **Um duplo prova que o nosso código chama o que pretendíamos chamar. Não prova
> que o terceiro aceita a chamada.**

Daí duas decisões: o `StorageProvider` entra nas baterias **de verdade** (é o
duplo do KAM-011, que é a porta a sério — com as validações de chave, o
`signUrl` e a expiração pelo relógio), e o módulo tem um **ensaio de base**
contra PostgreSQL, porque uma base falsa nunca lê o texto do SQL e por isso
qualquer mutação dele sobreviveria.

| CA | Estado | Evidência |
|---|---|---|
| 1 — uma mensagem `image\|audio\|document` com `media_id` resulta em 1 objecto em `t/{tenant_id}/media/{classe}/{aaaa}/{mm}/{uuid}` e 1 linha em `media_assets` (onze colunas) | **parcial — caixa vazia** | **A linha e o objecto cumprem-se; o caminho da chave não, e a divergência já estava registada antes deste ticket.** Um áudio dá **um** objecto e **uma** linha, com o `content_type` real, o `size`, o `sha256` que o `put` devolveu e o `storage_ref` — e as onze colunas que o critério lista existem todas, mais três (ver a emenda 1.24). **Mas a chave não é a do critério:** ele escreve `t/{tenant_id}/media/{classe}/…`, com um segmento `media/` a mais que a porta do KAM-011 **recusa** hoje — o `validarClasse` dela aceita `[a-z][a-z0-9_]{1,31}` num segmento só, e o §3.11 do dicionário já tinha registado esta divergência sem a resolver (dívida 8). Resolveu-se **pela classe e não pela porta**: os valores levam o prefixo `media_`, a chave fica `t/{tenant_id}/media_audio/{aaaa}/{mm}/{uuid}`, e o KAM-011 não se toca — ele está feito nas duas linguagens, testado, e tem o X-08 na sua bateria de contrato contra três alvos. **A caixa fica vazia porque à letra o caminho é outro**, e marcá-la era chamar «cumprido» a uma divergência resolvida de maneira diferente da escrita |
| 2 — idempotência: a mesma `(tenant_id, wamid, media_id)` processada 3× produz 1 objecto e 1 linha (`UNIQUE`) | **satisfeito** | Três chamadas deixam **um** objecto e **uma** linha, e a segunda e a terceira **não falam com a Meta** — uma resolução e uma descarga, com asserção sobre cada contador. Quem o garante é a `media_assets_origem_uq`, e **são três colunas e não uma**: o `wamid` sozinho não chega, porque uma mensagem pode trazer mais do que um objecto (há teste com dois `media_id` na mesma mensagem); o `media_id` sozinho também não, porque é do lado da Meta. **E a linha escreve-se ANTES da descarga**, que é a decisão central: os três valores vêm todos da mensagem, pelo que o segundo chamador perde o `ON CONFLICT` e não descarrega — com asserção a exigir que a reserva seja a **primeira** instrução. É o contrário do `ensureAccount` do KAM-019, que não podia escrever primeiro e por isso deixa recurso órfão numa corrida; aqui não há órfão possível. **Provado contra a base e em duas ligações:** duas chamadas concorrentes dão uma linha, o mesmo `assetId`, e **uma** só delas armazena |
| 3 — nenhum URL da Meta é persistido (BD, logs, eventos): teste que percorre as tabelas e logs de uma execução por padrões do domínio da Meta | **satisfeito** | **Não há coluna onde ele caiba**, e é isso que o faz passar por construção e não por disciplina: o que se guarda é o `media_id` (um identificador) e o `storage_ref` (a chave do nosso objecto). Dois testes, e cada um varre uma superfície diferente. O do *gate* 4 põe um canário com a forma de um URL de CDN da Meta e varre **tudo** o que o módulo escreveu — as linhas, o registo, os avisos ao AGR, as métricas e a exposição delas —, e repete-o no **caminho de falha**, que é onde um URL escapa mais facilmente (uma mensagem de erro que cite a URL completa). O do ensaio de base lê a tabela **inteira convertida a texto** (`media_assets::text`), linha a linha, e exige que não haja lá `http` nenhum — com a asserção de controlo de que **houve** linhas, porque um ciclo sobre zero linhas passa sempre |
| 4 — validação por *allowlist* de `content_type` e tamanho máximo por classe configurável; tipo ou tamanho inválido → `estado='rejeitado'` e resposta determinística | **satisfeito** | A *allowlist* é a do bloco (JPEG, PNG, WebP, OGG/Opus, PDF) e corre **no tipo da resposta e não no anunciado** — confiar no anúncio era aceitar que ele mente, e há teste para o caso em que o anúncio passa e a resposta não. O anúncio serve só para recusar cedo e poupar a descarga, com asserção a exigir **zero** descargas nesse caminho. Os limites são **injectáveis** e vão em configuração, pela razão que o KAM-015 escreveu para a versão da Graph; os valores são *proposta*, que é o que o próprio critério manda («valores a calibrar … NÃO VERIFICADOS»). **No limite passa e um byte acima não**, com teste para cada uma das três classes — é o erro de fronteira mais fácil de escrever. **Só PDF em documentos**, e a estreiteza é a defesa: a análise de malware «não consta de `../docs/tecnica/`» e fica para o KAM-065. A resposta é determinística e **não ecoa o que o cliente mandou**: há teste a procurar um `/` ou um dígito em cada frase, porque os textos ao cliente são decisão de produto a partir do KAM-025 |
| 5 — URL interna assinada com TTL ≤ 300 s; com `ctx` de outro tenant é recusada (X-08); depois do TTL devolve 403 | **satisfeito** | As três partes estão medidas. O TTL **não é escrito no MED**: lê-se do `TTL_MAXIMO_S` da porta, que é 300 — o mesmo número que o critério pede e que o `../docs/tecnica/08` §3.8 fixa, e lê-lo de lá faz mudar o limite ser um sítio e não dois. **O X-08 não é uma verificação nossa:** a chave leva o *tenant* no primeiro segmento e é a porta que levanta `ChaveForaDoTenantError`, e isso é mais forte do que um `if` nosso porque ela tem bateria de contrato própria — com dois casos chamados X-08 — que corre contra três alvos, incluindo um SeaweedFS real. São **duas fechaduras e as duas têm teste**: a RLS não deixa ler a linha de outro *tenant* (ensaio de base) e a porta não a assinaria (bateria do *gate* 4). E o **403 depois do TTL** mede-se com o relógio do armazenamento partilhado com o do MED: dentro do prazo serve 200 (o controlo, sem o qual um 403 podia vir de a URL estar mal formada), e um segundo depois do TTL dá 403. **O que fica por fazer e não é desta caixa:** a inscrição do caso no registo `registerCase` do `EPIC-07` — o `grep` dá zero em código e o dono é KAM-066, com o mesmo precedente que o KAM-011 e o KAM-019 escreveram |
| 6 — falha de descarga: 3 tentativas com *backoff*; depois `estado='falhou'` e sinal ao AGR | **satisfeito** | **Três tentativas e não quatro**, e lê-se à letra — não se repete a releitura que o critério 6 do KAM-015 obrigou, porque lá o texto contradizia-se na própria aritmética e aqui não há contradição que force outra leitura. **E há dois testes e não um**, porque a primeira versão tinha um defeito instrutivo: com a Meta em baixo é o `resolver` que estoura, pelo que se contavam três **resoluções** e zero descargas — o teste que contava descargas media zero. O par que ficou prende que o *retry* envolve **as duas** chamadas: um conta as resoluções com o `resolver` em baixo, o outro conta as descargas com o `resolver` a responder. Entre três tentativas há **duas** esperas e não três, e a segunda é maior que a primeira. O AGR é avisado com o *tenant*, a conversa, o `wamid` e a classe, e o aviso vem **depois** de a linha ficar `falhou`: se ele falhar, o estado está gravado e alguém o vê — ao contrário, o AGR pedia o reenvio de algo que a nossa base ainda dizia estar a caminho |
| 7 — áudio: `retain_until = criação + 24 h` e gancho `onTranscribed(asset)` que agenda a eliminação do blob | **satisfeito** | **Conta da criação, e é a única leitura auto-consistente.** O `../docs/tecnica/08` §7.5 diz «apagar o blob após sucesso (alvo ≤ 24 h; limite de erro 72 h)» e o critério diz «criação + 24 h»; contar da transcrição faz o prazo **nunca chegar** quando a transcrição nunca tem sucesso, que é precisamente o caso em que o áudio não devia ficar. Medido: o prazo gravado é exactamente `T0 + 24 h`. **E uma imagem não leva prazo curto**, com teste: «fotos de produto vivem enquanto o catálogo viver», diz o bloco, e inventar aqui um prazo era apagá-las sem ninguém decidir — a política por classe é do KAM-071. O gancho corre com a **chave do objecto**, porque sem ela quem purga não sabe o que apagar, e não corre para um `assetId` que não existe. **A purga em si é KAM-071**, que é o que o próprio critério diz |
| 8 — o MED não importa módulos de PAY nem de COM (teste de arquitectura): 0 caminhos de código que alterem estado de pagamento a partir de uma imagem | **satisfeito** | **O teste lê a fonte e não corre código**, porque o critério pede «0 caminhos» e um teste de comportamento prova só que os caminhos que ele exercita não fazem aquilo — o que prova zero é a **ausência da importação**. E está escrito **ao contrário**: enumera as importações que o MED tem e exige que cada uma esteja numa lista de permissão **com razão escrita**. Uma lista de bloqueio passaria hoje por o `pay/` ainda não existir em `packages/core-ts/src/`, e isso não é uma garantia — é um acaso com data de validade. Três cintos: a lista de permissão, a menção (que apanha um `import()` dinâmico que a expressão do primeiro não vê) e os nomes de tabela de pagamento. **Provado não-vacuoso:** com uma importação de `../pay/index.ts` acrescentada à mão, **dois dos cinco** testes caem. E há um controlo a exigir que **haja ficheiros para ler**, porque um `readdirSync` sobre a pasta errada devolve lista vazia e um ciclo sobre lista vazia passa sempre. **O `lint_arch` não cobre isto**, e fica dito no ficheiro: a ferramenta tem `blocklist.py` (dependências de npm), `structure.py`, `names.py` e `conventions.py`, e nenhum olha para importações **entre módulos** de `src/` |
| 9 — métricas `media_bytes_total{classe}`, `media_download_ms`, `media_rejected_total{motivo}` sem conteúdo nos logs | **satisfeito** | As três existem, com lista **fechada** em cada etiqueta — um valor livre é cardinalidade aberta, e é a mesma regra dos quatro motivos do HND. **Nenhuma leva identificadores**, e há teste a varrer a exposição à procura do *tenant*, do contacto, da conversa, do `wamid` e do `media_id`: a gramática de uma etiqueta é `^[a-z][a-z0-9_]{1,62}$`, mas a razão é a cardinalidade (`OBS-I`). A `media_bytes_total` leva a **classe** e não o `content_type`: três valores contra uma lista que cresce sempre que a *allowlist* cresce. **E a `media_download_ms` é um *gauge* e não um histograma**, pela mesma razão que o `gwy_enqueue_ms` escreveu (ADR-018, observabilidade leve no Piloto) — o sufixo `_ms` do nome que o ticket fixa convida a ler isto como uma distribuição, e fica dito no módulo que não é. **Mede-se mesmo quando a descarga falha**, de propósito: uma descarga que demora e falha é o sinal mais útil que esta métrica dá, e medir só os sucessos fazia um painel verde num dia em que nada chegou. As três aparecem sempre na exposição, os contadores a zero e o *gauge* a `-1`: um painel que mostre «sem dados» não distingue «nenhuma mídia» de «o processo não arrancou» |
| DoD — todos os CA satisfeitos e demonstráveis | **não satisfeito — caixa vazia** | Oito de nove. O que falta é o caminho da chave do critério 1, e o que o impede é uma divergência entre dois blocos que já estava registada (dívida 8): a forma que o KAM-020 escreve tem um segmento a mais do que a porta do KAM-011 aceita |
| DoD — 2 revisores (dados pessoais, isolamento); testes verdes; cobertura ≥ limiar | **não satisfeito — caixa vazia** | **Zero revisores humanos**: uma revisão adversarial é evidência, não é um revisor. Testes verdes e cobertura: ver a tabela de execução |
| DoD — documentação actualizada (`docs/media.md`); Conventional Commits | **satisfeito** | [`../docs/media.md`](../docs/media.md) (novo, doze secções), dicionário §3.16 (emenda 1.24), `../docs/ci.md` (treze *suites*) e `../docs/dividas-documentais.md`. Conventional Commits imposto pelo `tools/githooks/commit-msg` |
| DoD — isolamento de *tenant*: prefixo por tenant, RLS em `media_assets`, teste cruzado X-08 | **satisfeito** | As três partes, e duas herdam-se por usar a porta em vez de a reinventar. **O prefixo é da porta** (`novaChave` põe o *tenant* no primeiro segmento, e o `validarClasse` recusa o que não casa), e há asserção sobre a forma da chave gravada. **Três FK, e não as mais do esquema** — a `outbound_messages` da `0010` tem quatro, e cinco sítios desta entrega diziam que esta era a que tinha mais, num deles imediatamente acima do comentário que o contradizia. **A RLS é da revisão** e está provada em dois sítios: o X-03 do *gate* 6 com a receita de sementes nova (canário no `media_id`, porque a `origem_uq` leva o *tenant* e os dois podem semear o mesmo valor — ao contrário da `handoffs`, cuja chave é global), e o ensaio de base, com o controlo positivo e a escrita cruzada que não acontece. **O «nem como dono» sai desta frase**, e foi a revisão adversarial que o apanhou: o ensaio corre como `kamba_app`, que não é dono da tabela, pelo que um `ENABLE` sem `FORCE` dava o mesmo resultado ali. O `FORCE` **está** provado — mas noutro sítio, pela bateria do esquema, que lê o `relforcerowsecurity` do `pg_class`. **O X-08 existe e corre**, e isso foi medido e não suposto: o rótulo está no `../docs/tecnica/08` §3.7 e a bateria de contrato do KAM-011 tem **dois** casos com ele no título, sobre três alvos. O que o KAM-020 acrescenta é o lado novo — o URL interno do MED e a `media_assets` —, e está nos testes acima. O que **não** existe é o registo enumerável que o hospedaria (`registerCase`, KAM-066) |
| DoD — idempotência: `UNIQUE` e teste de repetição | **satisfeito** | Ver o CA 2. Três chamadas sequenciais dão uma linha e uma descarga; **duas concorrentes em duas ligações** dão uma linha e uma só armazena, que é a única forma de exercitar o `ON CONFLICT` — em série a segunda nem chega ao `INSERT`, e foi esse o buraco que a prova por mutação encontrou no `ensureAccount` do KAM-019 |
| DoD — pagamento só por evento autenticado: nenhuma imagem altera estado de pagamento (teste de arquitectura) | **satisfeito** | Ver o CA 8. E vale repetir o porquê, porque é o ADR-013 e não uma preferência: um cliente manda a fotografia de um depósito e o pagamento só muda de estado por um evento autenticado do banco ou do facilitador — **nunca** por alguém, ou algum modelo, ter olhado para a imagem |
| DoD — privacidade: áudio com retenção curta; sem URLs da Meta nem conteúdo em logs | **satisfeito** | O áudio leva 24 h contadas da criação (CA 7) e nenhum URL da Meta é persistido em sítio nenhum (CA 3). **E o registo não leva conteúdo**: a lista branca do *logger* tem nove campos e nenhum é texto de mensagem — o `log_policy` lê 119 ficheiros e dá **0 achados**. Os `outcome` que o MED escreve são todos de forma `media_*`, sem tipo, sem tamanho e sem identificador de objecto: o que o painel precisa de saber está na métrica |
| DoD — custo e observabilidade: métricas de bytes, latência e rejeição desde o código | **satisfeito** | Ver o CA 9. «Desde o código» é literal: as três estão no módulo e expostas pelo `exposicao()`, não são um painel por configurar — e a de bytes é a que sustenta o custo de armazenamento por PME, que é a razão de levar a classe (um catálogo de fotos e um mês de notas de voz têm políticas de retenção opostas) |
| DoD — migrações reversíveis: `downgrade` de `media_assets` testado | **satisfeito** | Bateria própria (`db/tests/test_media_schema.py`), **dezoito casos**. Com a tabela vazia desce e sobe sem perguntar; **com linhas e sem `KAMBA_DOWNGRADE_0012_COPIA` recusa**, com a contagem na mensagem, e deixa o `FORCE` **intacto** — a recusa não pode trocar uma perda de dados por um furo de isolamento. Com a variável, escreve a cópia das catorze colunas. **E o que se perde aqui é diferente das outras revisões, e pior:** as linhas vão e os **objectos ficam**. Um blob sem linha que o aponte é lixo que ninguém sabe que existe — nenhum consumidor o encontra, a purga do KAM-071 não o vê porque ela lê esta tabela, e continua a custar armazenamento e a guardar dados pessoais de um cliente final para sempre. A cópia é a única forma de alguém os reencontrar, e é o `storage_ref` de cada linha que o permite: há asserção a exigir que ele lá esteja. **A política sai antes de se contar**, pela lição medida na `0009` e confirmada na `0010` e na `0011` |

**Como se correu, e o que saiu.** Nesta máquina não há `make`, `node` nem
`pnpm` no `PATH`, e tudo o que se segue correu em Docker ou no `.venv`:

| Verificação | Comando | Resultado |
|---|---|---|
| *gate* 3 (referências, *handoff*, backlog) | `lint_refs`, `lint_handoff`, `lint_backlog` | `conforme`, **código 0** |
| *gate* 3b (nomes canónicos) | `dict_export --check`, `canon_lint check` e `canario` | `conforme`, **código 0** — dicionário v1.24, **12 migrações, 28 tabelas, 242 colunas, 116 valores de `CHECK`** |
| *gate* 2 (tipos e arquitectura) | `tsc --noEmit` sobre `src` e `tests`, `lint_arch all`, `log_policy lint` | limpo; `conforme`; **0 achados** em 119 ficheiros TS/JS |
| *gate* 4 (baterias da mídia) | `node --test` sobre os três `tests/med.*.test.ts` | **59 testes, 59 passam** |
| *gate* 6 (isolamento) | `db/gate_bd.py --suite tests_isolamento` | **78 testes, OK** — com a `media_assets` descoberta pelo catálogo e semeada, e o X-05 de vinte e uma para **vinte e duas** tabelas |
| *gate* 8 (migrações) | `db/gate_bd.py --suite tests` | **433 testes, OK** — eram 415; a bateria do esquema trouxe dezoito |
| *gate* 8 (mídia) | `db/gate_bd.py --suite tests_media` | **5 asserções Python sobre 4 ficheiros de teste Node, OK**; cobertura de `src/med/` em **seis** módulos: `pipeline.ts` a **89%** e os outros cinco entre 95% e 100%, contra o limiar de 75% do estrato `restante`. (A primeira versão desta linha dizia «entre 89% e 100% em seis módulos», que é aritmeticamente impossível — se um dos seis está a 89%, só cinco podem estar a 100%. O `../docs/ci.md` dizia a coisa certa, pelo que os dois documentos da mesma entrega discordavam.) |
| *gate* 11 (cadeia de abastecimento) | `supply_chain check` | `conforme`, **código 0** — 24 referências a 6 imagens, todas por digest |
| prova por mutação | `db/mutacoes.py --aplicaveis` e as 27 novas por filtro | **389 mutações, 0 não aplicáveis** — **27 novas** deste ticket. As do módulo e as da revisão correram **duas vezes**, e a segunda é a que conta: à primeira sobreviveram três, e depois das correcções da revisão adversarial sobreviveram **outras duas** — as duas que eu próprio acabara de acrescentar para os caminhos de desfecho, e que eu corrigira no código sem escrever o teste. A terceira volta dá **0 não apanhadas** em tudo. **É a segunda vez neste ticket que a prova por mutação me apanha a corrigir o código e a esquecer o teste**, e a primeira está narrada abaixo |

#### O que a prova por mutação encontrou, e era a armadilha que eu queria evitar

As dezassete mutações do módulo correram e sobreviveram três. **Duas eram o
mesmo defeito, e o defeito era meu:**

**O meu teste da monotonia fazia o `UPDATE` à mão.** Ele escrevia
`AND estado = 'pendente'` no próprio teste e verificava que não casava — o que
prova que o PostgreSQL sabe comparar duas cadeias, e **não prova nada sobre o
SQL do módulo**. As duas mutações que isso devia matar — tirar o predicado do
`SQL_MARCAR_ARMAZENADO`, e descartar o resultado dele — sobreviveram as duas. É
exactamente a classe de defeito que esta bateria existe para evitar, e escrevi-a
assim de qualquer maneira.

O que as mata é passar pelo **caminho do código**, e a única forma é mexer na
linha **durante** a descarga — a janela em que o módulo já reservou e ainda não
marcou. O gancho `antesDeDescarregar` do ensaio faz isso: outro processo rejeita
a linha, e depois exige-se que a marcação **não** tenha casado (a base continua
a dizer `rejeitado`, sem `storage_ref`) e que o módulo **não** tenha dito
`armazenado` a quem chamou. Um teste, duas mutações mortas.

A terceira foi uma **`PROVA INVALIDA`** — a *suite* a falhar por carga e não uma
mutação apanhada, que a *skill* manda contar como sobrevivente e tratar baixando
o paralelismo. Com `KAMBA_MUTACOES_PARALELO=2`: **17 corridas, 0 não apanhadas**.

#### Decisões tomadas neste ticket

- **A emenda ao dicionário veio antes do código**, e tinha de vir: a tabela e
  cinco das suas colunas não existiam em sítio nenhum, e a palavra «media» não
  ocorria uma única vez no `../canon/dicionario.yaml`.
- **Os dois domínios são qualificados** (`media_assets.classe` e
  `media_assets.estado`) pela regra da emenda 1.14, e aqui não é cautela: há
  **cinco** colunas `estado` com `CHECK` nas revisões `0001`, `0003` e `0005`, e
  um domínio nu tornaria as cinco vermelhas e mataria uma extensão declarada.
- **O prefixo `media_` nas classes resolve a dívida 8 sem mexer no KAM-011.**
- **O `pendente` não está no ticket**, e é a linha que torna a idempotência
  verdadeira: é ele que permite escrever a linha antes da descarga.
- **Não há `CHECK` sobre o `retain_until`**, e a ausência tem teste: uma
  restrição que o obrigasse a ser futuro impedia o KAM-071 de marcar um objecto
  para eliminação imediata — a lição que a `outbound_messages_entrega_ck` da
  `0010` pagou.
- **O `GRANT UPDATE` por coluna tem chamador**, ao contrário do que a `0011`
  tentou: a linha nasce em `pendente` e só depois da descarga se sabe o resto.
- **A `media_download_ms` é um *gauge*** e a limitação fica dita, em vez de o
  nome sugerir um histograma que esta biblioteca não implementa.
- **O `sticker` é imagem**: uma quarta classe multiplicava a política de
  retenção do KAM-071 sem mudar nada.

### Handoff para Claude Code

```text
És o executor do ticket KAM-020 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-020), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§5.4) e
docs/tecnica/08_Seguranca_Conformidade.md (§3.8, §7.5). Objectivo: pipeline MED de recepção de mídia.
- Descarga autenticada por media_id (confirma o fluxo na documentação vigente da Meta), validação por allowlist,
  put no StorageProvider em t/{tenant_id}/media/..., registo idempotente em media_assets (UNIQUE tenant,wamid,media_id).
- Nunca persistas URLs da Meta; URL interna assinada ≤ 300 s; áudio com retain_until = 24 h.
- O MED não importa PAY/COM: uma imagem nunca é prova de pagamento (ADR-013). Falhas: 3 tentativas e sinal ao AGR.
Não expandas escopo: STT (KAM-036), visão (KAM-049), KYC (KAM-087), purga (KAM-071).
Testes: idempotência, rejeição, URL expirada, X-08, teste de arquitectura. Abre PR com o template do §7.
```

---

## KAM-021 — Quality rating, estado `restrito` e monitorização de limites

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-013, KAM-009 |
| Bloqueia | KAM-083, KAM-097, KAM-115 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§9, §19 proposta 01-B), `../docs/tecnica/00_Arquitectura_Solucao.md` (§6.2), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), ADR-001 |

### Contexto

Factos CONFIRMADOS (E1 §5): desde 2025-10-07 a qualidade baixa já não faz descer o limite automaticamente e o estado «Flagged» foi eliminado; a qualidade (GREEN/YELLOW/RED) continua a existir; o limite de mensagens fora da janela é por **portfólio** e conta utilizadores únicos em 24 h móveis (250 → 2.000 → 10.000 → 100.000 → ilimitado); `messaging_limit_tier` está deprecado em favor de `whatsapp_business_manager_messaging_limit`; eventos `phone_number_quality_update`, `business_capability_update`, `account_alerts`. A Meta pode limitar ou remover acesso sem aviso com base em denúncias. Há divergência documental: o doc 00 §6.2 e o doc 01 §9.1 propõem RED → `restrito` (reversível, automático); `../docs/tecnica/10` §6.4 diz RED → `suspenso`. **Decisão:** `restrito`; `suspenso` fica para T&S, falta de pagamento ou violação (proposta 01-B).

### Objectivo

Persistir o estado de qualidade e de limites dos canais, aplicar a transição automática e reversível para `restrito` e vigiar a utilização do limite de contactos novos fora da janela.

### Critérios de Aceitação

- [x] `phone_number_quality_update` actualiza `tenant_channels.quality_rating` e acrescenta linha a `channel_quality_log` (valor anterior, novo, evento, hora); GREEN/YELLOW/RED aceites, outro valor registado como desconhecido sem falhar.
- [x] RED passa o canal a `restrito` em ≤ 5 s (proposta), emite `channel.updated` e: bloqueia templates *marketing* e iniciar conversas, mantém respostas dentro da janela; o regresso a GREEN/YELLOW repõe `ativo`; nunca há transição automática para `suspenso` (teste com 50 eventos aleatórios).
- [ ] No Piloto (1 canal por tenant) `tenants.estado` projecta `restrito` enquanto o canal único estiver restrito e volta a `ativo` com ele.
- [x] YELLOW gera 1 alerta a T&S por transição (sem repetição em eventos idênticos) e marca os templates para revisão.
- [x] `business_capability_update` persiste `messaging_limit` (ex.: `TIER_250 → TIER_2000`) e `max_phone_numbers_per_business`; `message_template_quality_update` pausa localmente o envio do template afectado.
- [x] Duplicados: o mesmo evento 2× gera 1 transição (a chave do evento é o *hash* de `phone_number_id` + tipo + valor + marca temporal da Meta).
- [x] Medidor `messaging_limit_usage_ratio` = utilizadores únicos contactados por template nas últimas 24 h ÷ limite do escalão; 200 contactos distintos com `TIER_250` dá 0,8 e dispara alerta; resposta dentro da janela não consome.
- [x] O `account_alerts` cria *ticket* para T&S com o texto da Meta (sem dados pessoais) e o canal não muda de estado.
- [x] O KAM-015 honra `restrito` (recusa *marketing*/iniciar conversa) e o CHR usa a matriz de KAM-009 (teste de integração entre os três).

### Detalhes Técnicos

- **Componentes:** CHR (estado do canal), GWY/*worker* de canal (consumo de webhooks), OBS (alertas). Colunas `quality_rating` e `messaging_limit` já existem (KAM-003).
- **Tabela nova:** `channel_quality_log(id, tenant_id, channel_id, evento, valor_anterior, valor_novo, ocorrido_em, event_key UNIQUE)` com RLS.
- **Regras do doc 01 §9.1:** YELLOW → alerta e revisão de templates; RED → `restrito`; escalão novo → persistir e recalcular capacidade; pico de bloqueios/denúncias (131xxx em `failed`) → congelar iniciativas do bot e rever. O padrão da Meta (limite e remoção sem aviso) mantém-se como risco residual.
- **Higiene preventiva (§9.2):** sem *marketing*, opt-out imediato, «falar com humano» em todas as conversas; fica fora deste ticket (KAM-022, KAM-015).
- **Fora de âmbito:** suspensão por T&S (KAM-089/097), gate de pagamento (KAM-023), runbook de rating (KAM-083).

### Testes Requeridos

- Contrato com fixtures do simulador (KAM-024): sequências GREEN→YELLOW→RED→GREEN, duplicados, valores desconhecidos.
- Integração: `restrito` bloqueia *marketing* em KAM-015 e não bloqueia resposta na janela.
- Isolamento: eventos de A não alteram canal de B; X-03 sobre `channel_quality_log`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada; divergência com `../docs/tecnica/10` §6.4 registada para correcção; Conventional Commits.
- [x] **Isolamento de tenant** — resolução por `phone_number_id`; RLS em `channel_quality_log`; teste cruzado.
- [x] **Idempotência** — chave por evento e teste de repetição.
- [x] **Privacidade** — alertas e *tickets* sem conteúdo nem telefone.
- [x] **Custo e observabilidade** — `channel_quality{rating}`, `messaging_limit_usage_ratio`, `channel_restricted_total`.
- [x] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-021 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-021), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§9) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§5). Objectivo: qualidade, estado restrito e limites do canal.
- phone_number_quality_update, business_capability_update, account_alerts, message_template_quality_update.
- RED → restrito (automático, reversível, sem marketing nem iniciar conversas); nunca suspenso automático.
- channel_quality_log com event_key único; messaging_limit_usage_ratio (utilizadores únicos fora da janela / escalão).
- Usa whatsapp_business_manager_messaging_limit (messaging_limit_tier está deprecado); emite channel.updated.
Não expandas escopo: suspensão é T&S (KAM-089/097); runbooks são KAM-083.
Testes: sequências de qualidade, duplicados, integração com KAM-015, isolamento. Abre PR com o template do §7.
```

### Verificação dos Critérios de Aceitação

> **As caixas desta lista foram marcadas a 2026-10-23**, na auditoria dos
> critérios de saída do epic (§2), e não no PR que entregou o ticket: elas
> ficaram todas vazias enquanto esta tabela já dizia o veredito de cada
> critério. A regra da marca é a desta tabela — **a caixa fica vazia quando
> qualquer parte do critério não se cumpre** — e nenhuma se marcou sem o teste
> que ela cita ter sido conferido no ficheiro de teste. Nada desta secção foi
> reescrito: ela mede o que era verdade no dia em que correu.
>
> **Oito caixas de critério marcadas e uma vazia** — a do critério 3, pela
> razão de segurança escrita acima —, e **seis de DoD marcadas e duas
> vazias**: a dos revisores, e a do «todos os CA satisfeitos», que não pode
> estar marcada enquanto o 3 estiver vazio. Os critérios 4 e 8 marcam-se com
> o veredito que esta tabela lhes dá, «satisfeito pelo que o repositório
> tem»: o que lhes falta é um mecanismo de *ticket* para T&S que não existe
> em sítio nenhum deste repositório, está em dívida (73) e é do KAM-115. As
> sub-linhas `2b` e `5b` são **divergências registadas** e não cláusulas em
> falta: numa, a matriz recusa **mais** do que a frase do critério; na
> outra, o nome do escalão difere entre o critério e o gerador.

**Entregue em `feature/KAM-021-qualidade-e-limites`:** a revisão `0014`
(descende da `0013`) e o módulo `packages/core-ts/src/qualidade/`, que preenche o
braço `gestao_de_canal` do `Encaminhador` que o KAM-013 declarou e deixou a
registar e mais nada. Desenho em [`../docs/qualidade.md`](../docs/qualidade.md).

**Uma caixa fica vazia por segurança, e é a do critério 3.** Ele quer que o
`tenants.estado` projecte `restrito`, e a revisão `0007` retirou o
`UPDATE (estado)` a `kamba_app` **de propósito**, com a razão escrita lá — «o
sujeito da condição não pode ser quem a retira» — e um teste a prendê-la.
Devolver o privilégio reabria exactamente a escalada que a revisão adversarial
do KAM-009 fechou. Decisão do fundador nesta sessão: **caixa vazia com a razão
escrita**.

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | `phone_number_quality_update` actualiza `quality_rating` e acrescenta linha a `channel_quality_log`; GREEN/YELLOW/RED aceites, outro valor registado como desconhecido sem falhar | **satisfeito** | **As duas colunas guardam coisas diferentes, e é isso que o critério pede.** `tests_bd/qualidade.bd.test.ts`, «**o bruto fica no registo e o canonico no canal**»: o `valor_novo` fica `GREEN` e o `quality_rating` fica `green`, pela regra do §2 do dicionário. O valor desconhecido: «**um valor que a Meta inventar fica registado e nao falha**» — um `PURPLE` entra no registo, o `quality_rating` **não se toca** (mudar o estado corrente para um valor que não se compreende era pior do que não o mudar), e a linha fica lá para se descobrir o que a Meta passou a mandar. Um domínio fechado na coluna do registo transformava a próxima mudança de vocabulário numa falha de inserção, e ela **já mudou uma vez** (o «Flagged» foi eliminado a 2025-10-07, CONFIRMADO `E1` §5). As quatro colunas que o critério nomeia — anterior, novo, evento, hora — estão todas, e o `valor_anterior` sai da coluna: «**o valor anterior do registo e o que estava na coluna**» |
| 2 | RED → `restrito` em ≤ 5 s, emite `channel.updated`, bloqueia templates *marketing* e iniciar conversas, mantém respostas na janela; GREEN/YELLOW repõe `ativo`; nunca `suspenso` automático (50 eventos aleatórios) | **satisfeito** | `tests_bd/qualidade.bd.test.ts`: «**o RED restringe e escreve o motivo na mesma instrucao**» (as duas colunas juntas, porque separá-las deixava uma janela em que o canal está `restrito` e não diz porquê), «**o GREEN repoe o canal, e emite**», e «**um RED repetido com chave nova nao e uma transicao nova**» — o critério pede «1 transição» e um `red` repetido não é uma. O ≤ 5 s é **síncrono**: a escrita está na mesma transacção do tratamento, e não há fila pelo meio. Os 50 eventos aleatórios: `tests/qualidade.test.ts`, «**nunca produz `suspenso`, com 50 eventos aleatorios**», com semente **fixa** — um `Math.random()` dava um teste que falha uma vez por mês e nunca se reproduz. O bloqueio de *marketing* é o critério 9, abaixo |
| 2b | …e a matriz recusa **mais** do que a frase | **divergência registada** | A linha `restrito` do §3.7 do dicionário tem `enviar_template_utilidade: **false**`, pelo que a `utility` também é recusada — e o critério só nomeia a `marketing`. **Usa-se a matriz, porque é o que o critério 9 do mesmo bloco pede por extenso** («o CHR usa a matriz de KAM-009»), e ela é **mais restritiva** do que a frase, que é o lado seguro. Mudá-la era mexer numa decisão do KAM-009 que tem espelho em Python e paridade imposta pelo X-11. Dois critérios do mesmo bloco não dizem o mesmo: dívida **71** |
| 3 | No Piloto, `tenants.estado` projecta `restrito` enquanto o canal único estiver restrito, e volta a `ativo` com ele | | **Não se faz, e a razão é de segurança.** A revisão `0007` (KAM-009) retirou o `UPDATE (estado)` em `platform.tenants` a `kamba_app`, com a razão escrita na própria revisão — «`UPDATE platform.tenants SET estado = 'ativo'` com o próprio contexto **passa** […] o sujeito da condição não pode ser quem a retira» — e o `db/tests/test_privilegios.py` prende-o (`("kamba_app", "tenants", "UPDATE (estado)"): set()`). Nenhum dos papéis que o *worker* de canal tem pode escrever ali; só o `kamba_batch`. Devolver o privilégio reabria a escalada que a revisão adversarial do KAM-009 fechou, e o que se ganhava era uma coluna derivada de outra que já está escrita. **A caixa fica vazia** e a decisão devolve-se a quem escreveu o critério: dívida **70**. O que está entregue é o estado do **canal**, que é onde a qualidade vive, e é esse que a matriz lê |
| 4 | YELLOW gera 1 alerta a T&S por transição (sem repetição em eventos idênticos) e marca os templates para revisão | **satisfeito pelo que o repositório tem** | A segunda metade é literal: `tests_bd/qualidade.bd.test.ts`, «**o YELLOW nao restringe, e marca os templates aprovados**» — a `quality` passa a `yellow` nos `approved` e **não** nos `pending`, porque um template que ainda está com a Meta não tem revisão que fazer. E o canal fica `ativo`: um aviso não corta a loja. O «sem repetição em eventos idênticos» é da unicidade `(tenant_id, event_key)` e do `avisaDeAmarelo`, que avisa quando a qualidade **passou a ser** `yellow`: «avisa na transicao para amarelo, e nao num amarelo que ja era». **O «alerta a T&S» entrega-se como contador e registo**, porque não existe mecanismo de *ticket* neste repositório — dívida **73**, e quem notifica é o KAM-115 |
| 5 | `business_capability_update` persiste `messaging_limit` e `max_phone_numbers_per_business`; `message_template_quality_update` pausa localmente o template afectado | **satisfeito** | «**o escalao e o tecto persistem, e um null nao apaga**»: a Meta manda **o que mudou**, e um corpo sem o tecto não apaga o tecto que já se sabia — sem os dois `COALESCE`, apagava. O tecto é `integer` com `CHECK (> 0)`, e a base morde: «**o tecto de numeros tem de ser positivo, e a base morde**» (`23514`). A pausa: «**o template pausa pelo idioma exacto, e nao por prefixo**» — `pt_PT` e `pt_BR` são templates diferentes com corpos diferentes, e um `LIKE 'pt%'` pausava um pelo outro. O `status` passa a `paused`, valor que o `message_templates_status_ck` da `0010` já aceita, e é o `decidir` do KAM-015 que lhe dá efeito. **Usa o `whatsapp_business_manager_messaging_limit`** e não o `messaging_limit_tier`, que está deprecado (CONFIRMADO, `E1` §5) |
| 5b | …o exemplo `TIER_250 → TIER_2000` | **divergência registada** | O gerador do KAM-024 (`tools/meta-sim/src/campos.ts`) produz `TIER_2K`, e usa-se o do gerador: é a única fonte deste repositório que **corre**. Não se inventa um sinónimo — um escalão fora do mapa é desconhecido e o rácio fica `null`, porque «não sei» não é «está folgado»: «**um escalao que nao se reconhece da racio nulo, e nao zero**». A escada de valores é a mesma nos dois (250 → 2.000 → 10.000 → 100.000 → ilimitado); o que divergem são os **nomes**. Dívida **72** |
| 6 | Duplicados: o mesmo evento 2× gera 1 transição; a chave é o *hash* de `phone_number_id` + tipo + valor + marca temporal da Meta | **satisfeito** | **É da base, e o `RETURNING` vazio é o sinal.** `ON CONFLICT (tenant_id, event_key) DO NOTHING RETURNING id`, sem `SELECT` antes do `INSERT` — entre os dois cabe outro processo, e o critério pede **uma** transição, não «quase sempre uma». Provas: «**o mesmo event_key duas vezes: uma linha e uma transicao**» (e **um** evento contado, porque um painel que conte dois mente sobre quantos *webhooks* a Meta mandou) e «**dois eventos iguais em paralelo: uma linha e um evento**», em **duas ligações**. A chave é **composta com o `tenant_id`**: «**a mesma chave em dois tenants da duas linhas**», pela razão da emenda 1.21 — com unicidade global, um evento de B que calhasse na mesma chave era deduplicado em silêncio contra uma linha de A. É o **segundo** nível; o primeiro é o `inbound_events (kind, event_key)` da `0008`, e existe porque esse dedupe o **corpo** e não o encaminhamento (`registo.ts` do KAM-013: «registar e encaminhar não são atómicos») |
| 7 | `messaging_limit_usage_ratio` = utilizadores únicos contactados por template nas últimas 24 h ÷ limite do escalão; 200 distintos com `TIER_250` dá 0,8 e dispara alerta; resposta dentro da janela não consome | **satisfeito** | A letra: «**200 unicos com TIER_250 dao 0,8 e avisam**», contra PostgreSQL, com duzentos contactos e duzentas linhas de saída. «Por template» lê-se como «iniciadas por template», que é o que o limite da Meta mede (CONFIRMADO, `E1` §5: o limite é sobre **iniciar** conversas fora da janela), e traduz-se em `kind <> 'service'`: «**uma service nao consome e uma utility consome**». As 24 h são **móveis**: «**as 24 h sao moveis e nao a meia-noite de Luanda**» — uma mensagem de há 25 h cai fora, hora a hora, e **é por isso que esta consulta não chama a `platform.ten_periodo`**, ao contrário do contador do KAM-023. E é `count(DISTINCT)` e não `count`: «**o mesmo contacto duas vezes conta uma**». A fracção de aviso é `0,8` escrita como **fracção** e não como número por escalão, para não poder divergir do tecto |
| 8 | `account_alerts` cria *ticket* para T&S com o texto da Meta (sem dados pessoais) e o canal não muda de estado | **satisfeito pelo que o repositório tem** | A segunda metade é literal e provada contra a coluna: «**um account_alerts registra o texto e nao muda o estado**» — nem `estado` nem `motivo_restricao` se tocam. A primeira entrega-se como o que existe: o alerta **conta** em `channel_quality_event_total{evento="account_alerts"}` e o texto da Meta vai para o `channel_quality_log.valor_novo`, que é `text`. **O texto vai para a base e não para o registo de linha**, e a diferença é a política: a lista branca de nove campos do `logger/politica.ts` não tem campo de texto livre, e o `outcome` é um identificador — um alerta da Meta pode trazer qualquer coisa escrita, a base aceita-o e uma linha de *log* não. Não existe mecanismo de *ticket* neste repositório, e criar um a partir de um critério de um ticket de canais era alargar o escopo em silêncio: dívida **73**, e quem notifica é o KAM-115 |
| 9 | O KAM-015 honra `restrito` (recusa *marketing*/iniciar conversa) e o CHR usa a matriz de KAM-009 (teste de integração entre os três) | **satisfeito** | **Pela matriz e não por um `if`.** O `decidir` do KAM-015 ganha um parâmetro opcional com o par (estado do *tenant*, estado do canal) e chama o `tenantGate`; um `STATE_REFUSED` novo entra nos `MOTIVOS_DE_RECUSA`, que passam de dez a **onze**. Um motivo e não um por estado: o que recusa é a matriz, que decide por um **regime** saído do par, e um motivo por estado dava seis etiquetas de métrica para uma causa só. O teste de integração entre os três está em `tests_bd/qualidade.bd.test.ts`, no grupo «o criterio 9 de ponta a ponta»: «**com o canal restrito por qualidade, um template recusa com STATE_REFUSED**» — e **a restrição vem deste ticket, pelo caminho do módulo**, não escrita à mão. Com o controlo: «**com o tenant e o canal ativos, o template sai**», sem o qual uma recusa não se distinguia de um envio que nunca podia sair. E «**e uma service dentro da janela continua a sair**», porque a linha `restrito` da matriz tem `responder_sessao: true` e um `if (estado === "restrito")` cortava-a. A porta é **opcional**, pelo que nenhum `adapter` ligado antes disto passa a recusar; o que **não** é permissivo é o canal que não se encontra — a porta devolve `null` e o `adapter` recusa, porque um canal que não se resolve não envia |
| 9b | …o CHR em si | **não alterado, e é correcto** | O CHR **já** carrega o par: o `ChannelContext` do `../docs/tecnica/01` §7.2 tem `estado_tenant` e `estado_canal`, e o KAM-014 entregou-os. A porta `ObterEstado` existe para que seja ele a responder — é ele a autoridade sobre o contexto do canal e tem a *cache* —, e é por isso que este ticket **invalida** essa *cache* em vez de a contornar. Acrescentar uma consulta própria no `outbound/` criava uma segunda fonte do mesmo facto |

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **vazia** | **Um dos nove não se satisfaz, e a razão é de segurança:** o 3 pede escrita numa coluna que a revisão `0007` retirou à aplicação de propósito, com um teste a prendê-la. Dos outros oito, dois entregam-se «pelo que o repositório tem» (o *ticket* de T&S dos critérios 4 e 8, que não existe como mecanismo) e dois trazem divergências registadas (a matriz mais restritiva do que a frase do critério 2, e o nome do escalão do critério 5). Nenhum é trabalho em falta neste ramo: os quatro estão nas dívidas **70** a **73** |
| Revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar | **vazia** | Testes verdes e cobertura **medidos**: **1 269** testes de unidade, **1 268** a passar, **0 a falhar** (o saltado é pré-existente, nos segredos), dos quais **59** novos em `tests/qualidade.test.ts`, **8** no bloco do critério 9 de `tests/outbound.decisao.test.ts`, **4** no grupo da porta de estado de `tests/outbound.adapter.test.ts` e **36** em `tests_bd/qualidade.bd.test.ts`; as três *suites* do *gate* 8 verdes (`tests` **461**, que inclui os **20** da revisão — dezassete do esquema e três de paridade — e o `downgrade`; `tests_outbound` 10; `tests_isolamento` **78**); `src/qualidade/` entre **98% e 100%** por ficheiro, contra os 75% do estrato `restante` de `ci/thresholds.yaml`. **Zero revisores humanos** — é decisão do fundador, e a caixa fica vazia como facto registado |
| Documentação actualizada; divergência com `../docs/tecnica/10` §6.4 registada; Conventional Commits | **marcada, e a divergência não existe** | Desenho em [`../docs/qualidade.md`](../docs/qualidade.md). Emenda **1.27** ao dicionário (§3.18) e `canon/dicionario.yaml` regenerado — `dict_export --check` e `canon_lint` conformes, v1.27. O `../docs/ci.md` §3 ganha as cinco propriedades novas da *suite* `tests_outbound` e a linha de versão **1.47**; `lint_refs` conforme (17 605 referências em 1 139 ficheiros), `lint_contagens` conforme, `lint_backlog` conforme, `lint_arch` conforme, `scan_secrets` limpo, `log_policy lint` com 0 achados. **A divergência que esta caixa manda registar já estava fechada, e mediu-se:** o Contexto do bloco diz que o `../docs/tecnica/10` §6.4 põe RED → `suspenso`, e aquele §6.4 diz «`phone_number_quality_update` vermelho → `restrito` (§15); T&S analisa»; o §15.1 do mesmo documento tem `ativo → restrito` com decisor **automático**; e o controlo de versões dele registra a emenda que o corrigiu — «1.1 […] **Emenda KAM-111** […] §6.4 e §15.1, D-08». Quem **ainda** diz `suspenso` é o `../docs/tecnica/00` §6.2, e essa divergência o `../docs/tecnica/01` §9 já registra com a razão. Registar uma divergência inexistente era escrever uma dívida falsa: o que se registra é **isto**, na dívida **74** |
| **Isolamento de tenant** — resolução por `phone_number_id`; RLS em `channel_quality_log`; teste cruzado | **marcada** | `rls.enable_tenant_rls("channel_quality_log")` na `0014`, com `FORCE` e a política `tenant_iso` (ADR-015), e a tabela entra no catálogo do X-05 — a descoberta passa de vinte e duas para **vinte e três** tabelas, e ganhou receita de sementes no *gate* 6. Teste cruzado nos dois sentidos, com a metade positiva primeiro pela regra do `../docs/isolamento.md`: «com o contexto de A, as transicoes de B nao aparecem» (e o administrador vê-as: o que falta a A é a política, não a linha) e «com o contexto de A, o canal de B nao se restringe». **E a integridade, que a RLS não dá:** «**um channel_id que nao e do tenant nao casa a FK composta**» (`23503`) — a FK leva o `tenant_id` nos dois lados, pela razão que a `0009` fixou |
| **Idempotência** — chave por evento e teste de repetição | **marcada** | Critério 6, acima. E em **dois** níveis de prova: a mesma chave duas vezes (o índice único) e **duas chaves diferentes em paralelo** (o `WHERE estado <> 'restrito'` do `UPDATE`). As duas são precisas e uma não substitui a outra — foi a prova por mutação que o disse, e está logo abaixo |
| **Privacidade** — alertas e *tickets* sem conteúdo nem telefone | **marcada** | Os seis `outcome` que este módulo escreve são identificadores (`canal_restrito_quality`, `qualidade_desconhecida`, `alerta_da_conta`, …) e passam a lista branca de nove campos do `logger/politica.ts`, que **não tem campo de texto livre**. O texto da Meta vai para a base e não para o *log*, e nenhuma das quatro métricas leva `tenant_id` nem `phone_number_id`: as etiquetas têm de casar `^[a-z][a-z0-9_]{1,62}$` e um UUID com hífenes **levanta** (`OBS-I` de `../docs/seguranca/ameacas_stride.md`) |
| **Custo e observabilidade** — `channel_quality{rating}`, `messaging_limit_usage_ratio`, `channel_restricted_total` | **marcada** | As três, e uma quarta: a `channel_quality_event_total{evento}`, que **não está no DoD** e entra pela razão da emenda 1.21 — *tratar sem contar é tratar em silêncio*, e sem a etiqueta um painel não distingue «a Meta não mandou nada» de «mandámos tudo para o braço errado». A `channel_quality` é *gauge* e **sem `_total`**, porque um canal que melhora sai de uma série e entra na outra: um `_total` que desce é um contador que mente. A `channel_restricted_total` leva o domínio **inteiro** do `motivo_restricao` e não só o `quality`: a métrica é do canal e não deste ticket. Declaradas no §3.18 do dicionário |
| **Migrações reversíveis** — `downgrade` testado | **marcada** | Revisão `0014`, e o `downgrade` é testado pelo **efeito** em `db/tests/test_qualidade_schema.py`, `TestDowngradeDa0014`: «desce com linhas e sobe outra vez» — a tabela e a coluna desaparecem, a linha do canal **fica**, e o `upgrade` repõe tudo. O que se perde é o histórico de anúncios da Meta e um tecto que o próximo `business_capability_update` repõe; nenhum é prova de nada perante terceiros |

#### O que a prova por mutação diz, e o teste que ela encontrou em falta

**Trinta e quatro** mutações novas — **sete** da revisão `0014` e **vinte e sete** do código —,
cada uma a reverter um defeito **real**: o domínio dos eventos a perder um valor,
a chave a ser única globalmente, a primeira linha de um canal a deixar de caber,
um valor vazio a passar a ser um valor, o tecto de números a aceitar zero, a
aplicação a ganhar `UPDATE` no registo que não se corrige, a tabela a nascer sem
política de *tenant*, o registo a reescrever a linha que já existia, o
`restringir` a sobrepor a marca de outro ticket, o `repor` a deixar de olhar para
o motivo que lá está, a medição a contar envios e não pessoas, a resposta dentro
da janela a consumir escalão, o que a fila ainda tem em mão a contar, a janela
móvel a passar a 48 h, a pausa do template a casar por prefixo de idioma, a marca
de revisão a mexer nos não aprovados, um corpo sem tecto a apagar o tecto que se
sabia, o aviso de amarelo a sair em cada *webhook*, o aviso do escalão a exigir
ultrapassar os 80%, um valor desconhecido a decidir o estado, o tecto do primeiro
escalão dez vezes maior, a tradução a aceitar qualquer cadeia, o rácio sem
observação a dizer «está folgado», um evento repetido a escrever e a restringir,
o `channel.updated` a sair sem transição, a *cache* a esquecer antes de o evento
sair, a matriz a deixar de ser consultada, a mensagem de sessão a pedir a acção
de template, e um canal que a porta não encontra a voltar a enviar.

**Duas foram escritas e descartadas, e vale dizer quais.** A primeira trocava a
FK composta do canal por uma simples: a `tenant_channels` não tem unicidade em
`id` sozinho, pelo que a migração **não corre** — e uma mutação que rebenta na
criação é apanhada por qualquer teste, o que não prova nada sobre a FK. A segunda
retirava o `ocorrido_em` do `ORDER BY` do registo: a ordem das linhas não é
afirmada por teste nenhum, e **não devia ser**, porque os *webhooks* chegam fora
de ordem — a mutação seria imortal.

**E duas sobreviveram, e as duas eram testes em falta — não código a mais.** É
a melhor lição deste ticket, porque nenhuma estava visível por leitura: o código
estava escrito, o comentário dele explicava-o, e o que faltava era a prova de que
morde.

A primeira: apagar o `WHERE estado <> 'restrito'` do `SQL_RESTRINGIR` **passou** a
prova inteira, porque no caminho sequencial o predicado é redundante — o
`accaoDaQualidade` já devolve `"nada"` quando o canal está `restrito`, pelo que o
`UPDATE` nunca corre sobre um canal restrito. Quem o torna necessário é a
**concorrência** com chaves **diferentes**: as duas passam pelo registo, as duas
leem `ativo`, e as duas decidem restringir; sem o predicado, as duas escrevem e
as duas emitem `channel.updated`. O teste da corrida que já existia usa a
**mesma** chave, pelo que prova o índice único e não o `UPDATE` — as duas provas
são precisas e uma não substitui a outra. Entrou «**dois RED com chaves
diferentes em paralelo: uma transicao e um evento**».

A segunda: apagar a recusa do canal que a porta 5 não encontra também passou,
porque **nenhum teste ligava a porta a responder `null`**. É a mais importante
das três recusas do critério 9 — um canal que não se consegue resolver não é «sem
opinião», é um canal que não existe neste contexto —, e estava escrita sem nada a
prendê-la. Entrou o grupo «a porta de estado do KAM-021 (criterio 9)» em
`tests/outbound.adapter.test.ts`, com quatro testes, e **a metade positiva entre
eles**: «**sem a porta ligada, envia como antes do KAM-021**», que é o que torna
a negativa legível e prova que a porta é de facto opcional.

Depois das correcções: **34 corridas, 0 não apanhadas**.

`python db/mutacoes.py --aplicaveis` → **451 conferidas, 0 não aplicáveis**.

#### A revisão adversarial, e os defeitos que ela e os *gates* apanharam

Nenhum dos cinco foi previsto por leitura. Os dois que a prova por mutação
encontrou estão na secção acima; estes são os dos *gates* e da leitura.

1. **O grupo do critério 9 passava pela razão errada.** O `tenants.estado` nasce
   `onboarding` (revisão `0001`) e a matriz do KAM-009 decide por um **regime**
   saído do par: `onboarding` é mais restritivo do que `restrito` e recusa tudo
   menos registar e a mensagem de teste. As três asserções de `STATE_REFUSED`
   teriam passado com o canal `ativo`, e o grupo não provava nada sobre o
   critério 9. Ganhou um `before` que põe o *tenant* `ativo` — escrito pelo
   **administrador**, porque o `kamba_app` não tem esse privilégio, que é a
   mesma retirada que deixa a caixa do critério 3 vazia — e um teste de
   **controlo**.
2. **O `COALESCE(motivo_restricao, 'quality')` parecia código morto e não é.**
   Um canal `restrito` nunca passa pelo `UPDATE`, que tem `estado <> 'restrito'`
   — mas a `marcarRestricao` do KAM-023 escreve o `motivo_restricao` **sem**
   mexer no `estado`, pelo que um canal `ativo` com a marca de falta de pagamento
   é um estado que existe. Sem o teste novo, a linha era código morto e uma
   mutação nela seria imortal.
3. **O `outbound_messages_template_ck` recusou a receita de sementes do medidor.**
   A `0010` exige `template_name` em tudo o que não é `service`; o ajudante do
   teste inseria `utility` sem ele e levantava `23514`. Apanhado pelo *gate* 8 à
   primeira execução.
4. **O nome `max_phone_numbers_per_business` contém «phone».** Dispara a lista
   fechada de colunas de telefone do `test_catalogo.py` — declarou-se, com a
   razão de que num `integer` não cabe um E.164, garantia **mais forte** do que a
   do `phone_number_id`, que é `text`. E descer de `head` para a `0011` passa
   agora pela `0014`, que compromete **antes** de a `0012` recusar, pelo que a
   asserção do `downgrade` da mídia mudou de `TABELAS` para `TABELAS_ATE_0013`.
5. **O `quality_rating` entre crases numa nota do dicionário** tornou a extensão
   do KAM-003 redundante e o *gate* 3b recusou: passou a «guillemets». E o nome
   do teste do X-05 dizia «vinte e uma tabelas» sobre uma asserção que já ia em
   vinte e três — o número saiu do nome, porque um nome que diz um número errado
   é pior do que um que não diz nenhum.

E a leitura adversarial encontrou **três** coisas que nenhuma máquina podia
dizer.

A primeira é a mais barata de deixar passar, porque é a prosa a prometer o que o
código não tem: o `qualidade/contrato.ts` afirmava que «há um teste que compara
as três listas» do domínio dos eventos, e o que existia comparava **duas** — as
duas de TypeScript. A terceira, que é o `CHECK` da revisão, não era confrontada
com nenhuma. Entrou o `TestParidadeDosDominios` em
`db/tests/test_qualidade_schema.py`, que lê as revisões `0010`, `0013` e `0014`
como **texto** — a forma do `TestTarifas`, e os domínios leem-se das revisões em
vez de se copiarem, para que a comparação não passe por construção — e confronta
os três domínios com as constantes do módulo. O que uma divergência custava não é
a métrica: um motivo novo no `CHECK` da `0013` sem entrada no `MOTIVOS` fazia o
`contar` **levantar**, e o que se perdia era a **restrição**.

A segunda é que os cinco passos **não são atómicos por si**. O passo que registra
consome a `event_key`; um processo que caia entre ele e a mudança de estado perde
a transição **para sempre**, porque a Meta reenvia e o `ON CONFLICT` deduplica
contra a linha que ficou. Está agora escrito que o `ClienteSql` é a ligação
**dentro** da transacção de quem chama — o que a `Emitir` já exigia por si, e o
argumento vale para o conjunto e não só para ela —, e é o que o `comConsumo` do
KAM-006 dá por desenho (ADR-013).

A terceira é que o `estadoDepois` era uma função que **só existia para ser
testada**: o mapa acção → estado estava lá e o SQL escrevia os literais, sem
ninguém confrontar os dois. É a classe de achado que o KAM-019 nomeou — uma
mutação imortal é sinal de que o código não faz nada. Entrou a asserção que os
liga («**o SQL escreve o estado que o `estadoDepois` diz**»), e com ela uma
mutação que a prende.

E a mesma revisão confirmou, pelo caminho, que a divergência que o DoD manda
registar **já estava fechada pelo KAM-111** (dívida 74): o documento que o bloco
cita diz hoje o contrário do que ele lhe atribui. Também corrigiu o que o
`valor_anterior` a `NULL` significa — a primeira versão do comentário da revisão
dizia só «a primeira linha de um canal», e em dois dos quatro eventos é
**sempre** `NULL`, porque um alerta não substitui valor nenhum e a qualidade de um
template vive noutra tabela.

---

## KAM-022 — Consentimento no 1.º contacto (aviso versionado, botões, `consent_event`)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-008, KAM-014, KAM-015, KAM-159 |
| Bloqueia | KAM-048, KAM-070, KAM-109 |
| Responsável sugerido | Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/10_Onboarding_Governanca.md` (§7), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§7.3), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§6.3), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§4), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, ADR-010 |

### Contexto

O ADR-010 exige consentimento no 1.º contacto. Cada PME é, em princípio, responsável pelo tratamento e a KAMBÁ subcontratada (NÃO VERIFICADO como a APD qualifica plataformas SaaS, D9); se a base legal é contrato, consentimento ou interesse legítimo é matéria de parecer (KAM-104). A Messaging Policy (E1 §4, CONFIRMADO) exige opt-in específico por categoria para mensagens iniciadas pelo negócio, opt-out claro e caminho para humano. O aviso inclui: quem é o responsável (a loja), que é um assistente automático (E3 req. 15), finalidades, destinatários (inclui fornecedor de LLM e país), direitos e como falar com um humano. **Há três desenhos de consentimento** nos documentos (`consent_log` em 01 §6.2, `consent_ledger` em 06 §7.3, `consent_event` em 10 §7.2); este ticket adopta `consent_event` (nome do backlog) e regista a reconciliação.

### Objectivo

Implementar a barreira de consentimento anterior ao AGR: aviso curto e versionado com botões, registo `append-only` com prova, opt-out «PARAR», e eventos `consent.recorded`/`consent.withdrawn`.

### Critérios de Aceitação

- [x] Primeira mensagem de um contacto sem `consent_event` válido para a versão de texto vigente: exactamente 1 mensagem de saída (o aviso, com 3 botões «Continuar», «Falar com a loja», «Saber mais») e 0 invocações do AGR.
- [x] «Continuar» grava 1 linha `consent_event` (`purpose='transacao'`, `accepted=true`, `text_version`, `canal`, `evidence_hash`) e só então o AGR é invocado; o mesmo botão repetido 2× produz 1 linha.
- [x] «Falar com a loja» passa a conversa a `humano` (KAM-018/019) sem tratar dados por IA; «Saber mais» envia o texto completo/ligação à política e repete o aviso; texto livre em vez de botão repete o aviso até 2 vezes e depois encaminha a `humano` (comportamento a confirmar por parecer).
- [x] Propriedade: em sequências aleatórias de 1.000 mensagens por 50 contactos, nenhum *job* do AGR é criado sem `consent_event` válido anterior (0 violações).
- [x] «PARAR» (insensível a maiúsculas e acentos) em qualquer ponto grava `purpose='marketing'`, `accepted=false`, passa a conversa a `pausada` (gancho de KAM-018) e responde 1 confirmação; *marketing* sem `accepted=true` específico é recusado pelo Outbound (KAM-015).
- [x] `consent_event` é *append-only* (`UPDATE/DELETE` recusados para `kamba_app`); revogação = nova linha; a vista `consent_actual` devolve o último estado por `(tenant, contact, purpose)`.
- [x] `consent_texts(version, purpose, texto, hash, vigente_desde)` versiona o aviso; subir a versão exige re-aviso apenas a contactos sem consentimento da nova versão (política em proposta, a confirmar por parecer); `evidence_hash = sha256(texto_versão ‖ contact_id ‖ wamid_do_botão ‖ hora)` é reprodutível.
- [x] Eventos `consent.recorded` e `consent.withdrawn` emitidos pelo outbox com `contact_id` (sem texto nem telefone).
- [x] Contactos vindos da sincronização de histórico (KAM-017) recebem o aviso na primeira mensagem **depois** do onboarding; o aviso é uma única mensagem em PT-AO (custo de *service message* a considerar).

### Detalhes Técnicos

- **Componentes:** CHR/canal (`ConsentGate` antes do AGR), Outbound (botões), GOV (texto e versões). DDL de `../docs/tecnica/10` §7.2 com `contact_id uuid` (o doc usa `bytea`, em conflito com ADR-010) e `purpose` com o dominio de dez do dicionario 3.1 (emenda 1.16); os propósitos analíticos de `consent_ledger` (06 §7.3) são Diferidos e entram por migração quando existirem.
- **Fluxo:** `inbound → ConsentGate → (sem consentimento) aviso | (com consentimento) AGR`. O gate corre no pipeline de canal, porque KAM-025 não depende deste ticket.
- **Botões:** `button_reply` entrega `reply.id` emitido por nós (o AGR confia no `id`, não no título). Marketing exige consentimento separado com «PARAR» em cada mensagem (E1 §4); no Piloto não há *marketing*.
- **Fora de âmbito:** consentimento da PME (ToS/DPA, KAM-090), direitos do titular (KAM-070), parecer sobre o texto (KAM-104); o texto final em PT-AO é revisto juridicamente.

### Testes Requeridos

- Unit: máquina de estados do aviso (6 entradas × 3 estados); `evidence_hash`; detecção de «PARAR» (8 variantes).
- Propriedade: 1.000 mensagens × 50 contactos, 0 AGR sem consentimento. Integração: repetição de botão, subir versão do texto.
- Segurança: *append-only* por papel; isolamento X-03 sobre `consent_event`.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por 2 revisores (dados pessoais); testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada; reconciliação dos três desenhos de consentimento registada; Conventional Commits.
- [x] **Isolamento de tenant** — RLS em `consent_event`/`consent_texts`; teste cruzado.
- [x] **Idempotência** — botão repetido não duplica registo; teste incluído.
- [x] **Privacidade** — `contact_id` (nunca telefone); texto e prova versionados; base legal marcada «a confirmar por parecer».
- [x] **Custo e observabilidade** — `consent_notice_sent_total`, `consent_accepted_ratio`, `consent_optout_total`.
- [x] **Migrações reversíveis** — `downgrade` testado (`consent_event` é aditivo).

### Handoff para Claude Code

```text
És o executor do ticket KAM-022 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-022), docs/tecnica/10_Onboarding_Governanca.md (§7) e
docs/tecnica/06_Dados_Eventos_Analytics.md (§7.3). Objectivo: consentimento no 1.º contacto (ADR-010).
- ConsentGate antes do AGR: sem consent_event válido, envia o aviso com 3 botões e não invoca o AGR.
- consent_event append-only com contact_id uuid, text_version, evidence_hash; consent_texts versionados; vista consent_actual.
- «PARAR» regista a revogação de marketing, pausa a conversa (KAM-018) e confirma; marketing só com opt-in separado.
- Emite consent.recorded e consent.withdrawn pelo outbox, sem texto nem telefone. O texto jurídico é «a confirmar por parecer».
Não expandas escopo: ToS/DPA da PME (KAM-090), direitos do titular (KAM-070).
Testes: máquina de estados, propriedade 0 AGR sem consentimento, PARAR, append-only. Abre PR com o template do §7.
```

### Verificação dos Critérios de Aceitação

> **As caixas desta lista foram marcadas a 2026-10-23**, na auditoria dos
> critérios de saída do epic (§2), e não no PR que entregou o ticket: elas
> ficaram todas vazias enquanto esta tabela já dizia o veredito de cada
> critério. A regra da marca é a desta tabela — **a caixa fica vazia quando
> qualquer parte do critério não se cumpre** — e nenhuma se marcou sem o teste
> que ela cita ter sido conferido no ficheiro de teste. Nada desta secção foi
> reescrito: ela mede o que era verdade no dia em que correu.
>
> **Nove caixas de critério marcadas e nenhuma vazia; sete de DoD marcadas e
> uma vazia** — a dos revisores. A do «todos os CA satisfeitos» marca-se
> porque esta tabela a dá como `marcada` e os nove critérios como
> satisfeitos. **A linha `9b` não a impede**: a pergunta dela — se o
> `ConsentGate` está construído no caminho de canal — não é cláusula de
> critério nenhum, e o que ela nomeia (um caminho de envio no *worker*, e
> uma versão do texto publicada, KAM-104) é montagem e não aceitação.

**Entregue em `feature/KAM-022-consentimento-no-primeiro-contacto`:** a revisão
`0015` (descende da `0014`) — duas tabelas e **a primeira vista do esquema** — e
o módulo `packages/core-ts/src/consentimento/`, que é a barreira anterior ao
AGR. Desenho em [`../docs/consentimento.md`](../docs/consentimento.md).

**A decisão é a única porta, e é por isso que ela é um valor.** O `tratar`
devolve um `invocaAgr: boolean` e nunca chama o AGR; quem monta o *job* é o
encaminhador do KAM-013/KAM-014. A propriedade do critério 4 só é demonstrável
assim — com a autorização a deduzir-se da acção em cada chamador, não havia um
sítio onde a medir.

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Primeira mensagem sem `consent_event` válido para a versão vigente: exactamente **1** mensagem de saída (o aviso, com 3 botões) e **0** invocações do AGR | **satisfeito** | `tests/consentimento.test.ts`, «**exactamente 1 mensagem de saida e 0 invocacoes do AGR**» — `mensagens: 1`, `invocaAgr: false`, e os **três** botões pelos `id` que nós emitimos. Contra a base: `tests_bd/consentimento.bd.test.ts`, «**sem consentimento: 1 aviso, 0 AGR, e a linha fica em outbound_messages**», que verifica também que **nenhuma prova** foi escrita — o aviso não é um consentimento. O texto sai **preenchido**, com o nome da loja no lugar do marcador: a `consent_texts` é de plataforma e não tem `tenant_id` |
| 2 | «Continuar» grava 1 linha (`purpose='transacao'`, `accepted=true`, `text_version`, `canal`, `evidence_hash`) e **só então** o AGR é invocado; o mesmo botão 2× produz 1 linha | **satisfeito** | A ordem é literal: o `SQL_REGISTAR` corre **antes** de a decisão autorizar, e «**grava a prova, autoriza o AGR, e a mensagem seguinte segue sem escrever**» prova o ciclo inteiro contra a base — a segunda mensagem lê `valido` **da vista** e segue sem escrever nada. A idempotência é **da base**: «**o mesmo botao duas vezes: uma linha**» e «**dois cliques em paralelo: uma linha e um evento**», em **duas ligações**. O que a torna suficiente é a composição do resumo — o `wamid` e a hora são **da Meta**, pelo que uma reentrega do mesmo *webhook* dá o mesmo valor; com a **nossa** hora, duas entregas davam duas linhas e o critério dizia o contrário |
| 3 | «Falar com a loja» passa a `humano` sem tratar dados por IA; «Saber mais» envia o texto e repete o aviso; texto livre repete o aviso até 2 vezes e depois encaminha a `humano` | **satisfeito** | As três, na matriz e contra a base. «**«Falar com a loja» passa a humano e nao invoca o AGR**» (e **vale também com consentimento válido**, porque a Messaging Policy exige um caminho para uma pessoa em qualquer ponto — `E1` §4). «**«Saber mais» envia o texto e repete o aviso**», sem autorizar: quem pede para saber mais não consentiu — e **com os três botões**, que é como as duas metades deste critério se cumprem numa mensagem só (ver a dívida 78 e o achado 2 da revisão adversarial). E o tecto: «**ao terceiro, passa a uma pessoa e nao envia aviso**», com a contagem a vir do **prefixo da chave de idempotência** — «**a contagem de avisos vem da base, pelo prefixo da chave**». O «comportamento a confirmar por parecer» que o próprio critério admite está numa **constante** (`AVISOS_ANTES_DO_HUMANO`) e não no meio de um `if`: quando o parecer chegar, muda-se um número |
| 4 | Propriedade: em 1.000 mensagens por 50 contactos, **nenhum** *job* do AGR sem `consent_event` válido anterior (0 violações) | **satisfeito** | `tests/consentimento.test.ts`, «**0 invocacoes do AGR sem consentimento valido anterior**»: mil mensagens, cinquenta contactos, seis entradas sorteadas, **0 violações** — e com a asserção de que **houve** invocações, sem a qual o teste não provava nada. O aleatório é **determinista**, com semente fixa: um `Math.random()` dava um teste que falha uma vez por mês e nunca se reproduz. E a leitura exaustiva que a sustenta: «**nenhuma celula autoriza o AGR sem consentimento valido**» percorre as dezoito células e verifica que só o estado `valido` ou o botão `continuar` autorizam |
| 5 | «PARAR» (insensível a maiúsculas e acentos) em qualquer ponto grava `purpose='marketing'`, `accepted=false`, passa a conversa a `pausada` e responde 1 confirmação | **satisfeito** | «**grava a revogacao de marketing, pausa e confirma**»: `accepted = false`, modo `pausada`, **uma** mensagem, e `consent.withdrawn`. As oito variantes dos Testes Requeridos: «**as oito variantes dos Testes Requeridos**» (caixa, acentos, espaços, pontuação e os três sinónimos). Contra a base, «**grava a revogacao de marketing e pausa, sem tocar na transacao**» mostra as **duas** finalidades na vista: um «PARAR» cala o *marketing* e **não** a loja. E «**nunca escreve `marketing` com `accepted = true`**»: o opt-in de *marketing* é separado e específico, e inventá-lo aqui era inventar um consentimento que ninguém deu |
| 5b | …«*marketing* sem `accepted=true` específico é recusado pelo Outbound (KAM-015)» | **já satisfeito, e por outro caminho** | O `decidir` do KAM-015 **já** recusa `marketing` no Piloto com `MARKETING_NOT_ALLOWED`, antes de qualquer consentimento: o `CATEGORIAS_DO_PILOTO` não o inclui. A verificação por `consent_actual` é para quando houver *marketing*, e **não tem caminho** porque o envio não tem. Acrescentá-la agora era escrever um ramo que nenhum teste pode exercitar |
| 6 | `consent_event` é *append-only* (`UPDATE/DELETE` recusados para `kamba_app`); revogação = nova linha; a vista `consent_actual` devolve o último estado por `(tenant, contact, purpose)` | **satisfeito** | **É um privilégio e não uma política**, e é a forma mais forte de prova que esta bateria tem: `tests_bd/consentimento.bd.test.ts` afirma o **`42501`** num `UPDATE` e num `DELETE` — e num `INSERT` em `consent_texts`, porque quem publica uma versão do texto é operação e não o caminho que serve clientes. Com a metade positiva: «**o SELECT e o INSERT na prova, esses, existem**», sem a qual as negativas passavam por uma concessão em falta por inteiro. A revogação é uma linha nova: `db/tests/test_consentimento_schema.py`, «a revogacao e uma linha nova e nao uma correccao». E a vista: «**a vista devolve a ultima linha do trio**», com `DISTINCT ON` e `ORDER BY ocorrido_em DESC, id DESC` |
| 6c | …e a ordem da vista | **satisfeito depois de o CI apanhar um defeito meu** | A ordem é `(ocorrido_em DESC, registado_em DESC, id DESC)`, e o do meio entrou por uma afirmação **falsa** que eu escrevi duas vezes — na revisão e no dicionário: que um empate no instante dentro do trio era impossível «pela unicidade da prova». A unicidade é sobre o `evidence_hash`, e **a hora que a Meta manda tem resolução de segundos**: dois cliques no mesmo segundo dão o mesmo instante com `wamid` diferentes, entram as duas linhas, e a vista desempatava pelo `uuid` aleatório. O ensaio «**duas provas do mesmo trio: o estado e o da ultima**» passava na minha máquina e **falhava no CI**, com os mesmos dados. O `registado_em` é a hora em que **nós** escrevemos, com `clock_timestamp()` — e não `now()`, que é o início da transacção e empatava também —, e é a única coluna do esquema que o usa; o par `ocorrido_em`/`registado_em` é o mesmo do envelope de evento do §3.5. A asserção verifica primeiro que as duas linhas **empatam** no instante, senão provaria o relógio e não o desempate; e há uma mutação que lhe tira o critério do meio |
| 6b | …a vista e a RLS | **satisfeito, e é o achado desta revisão** | **A `consent_actual` é a primeira vista do esquema**, e leva `security_invoker = true`. Sem a opção, uma vista corre com os privilégios do **dono** e o isolamento passa a depender do `FORCE` — numa relação onde ninguém iria procurar. O `verificar_vistas` de `db/tests_isolamento/catalogo.py` exige-o a **qualquer** vista, **sem lista de excepções**, e existe desde o KAM-004 sem nunca ter tido nada para ver: esta revisão foi a primeira a dar-lhe algo. Prova-se duas vezes — a opção está na relação, e «**a vista nao mostra o estado de B com o contexto de A**» mede-a pelo caminho do módulo |
| 7 | `consent_texts(version, purpose, texto, hash, vigente_desde)` versiona o aviso; subir a versão exige re-aviso apenas a quem não tem consentimento da nova; `evidence_hash = sha256(...)` é reprodutível | **satisfeito** | A tabela é a do critério, com `criado_em` a mais (quando a linha entrou, que não é quando ela passa a valer) e **sem `tenant_id`**, pela razão da dívida 77. «**uma versao com data futura nao vigora**» e «**subir a versao obriga a re-avisar quem ja tinha consentido**» — o estado passa a `desactualizado` e o aviso volta a sair. A reprodutibilidade mede-se **recalculando**: «**a prova guardada e a que se recalcula**» refaz o resumo a partir da linha e da versão do texto, como quem audita faria, e compara octeto a octeto. E «**o separador impede a colisao por deslocamento**»: sem separador, `sha256("ab" ‖ "c")` e `sha256("a" ‖ "bc")` são o mesmo valor |
| 8 | Eventos `consent.recorded` e `consent.withdrawn` emitidos pelo outbox com `contact_id` (sem texto nem telefone) | **satisfeito** | Os dois contratos **já existiam** (`contratos/eventos/consent.recorded/`, v1 e v2, do KAM-159/KAM-007) e a carga deles é `{contact_id, finalidade, origem}` — sem texto e sem telefone **por construção do esquema**, que tem `additionalProperties: false`. A emissão é **porta**, pela regra do KAM-005 e do ADR-009: o envelope constrói-se em SQL, na transacção de quem chama. Provas: `consent.recorded:transacao` no «Continuar», `consent.recorded:atendimento` no «Falar com a loja», `consent.withdrawn:marketing` no «PARAR», e **um** evento e não dois na corrida |
| 9 | Contactos vindos da sincronização de histórico (KAM-017) recebem o aviso na primeira mensagem **depois** do onboarding; o aviso é uma única mensagem em PT-AO | **satisfeito pelo que existe, e o resto não é deste ramo** | A segunda metade é literal: **uma** mensagem, e o texto é um só (`consent_texts.texto`). A primeira é o comportamento por omissão e não um caso especial — o gate não distingue de onde o contacto veio: um contacto sem `consent_event` válido recebe o aviso na primeira mensagem que mandar, e recebe-o **uma** vez pela chave de idempotência. **O KAM-017 não existe ainda**, pelo que não há sincronização de histórico que se possa exercitar de ponta a ponta; o que se pode afirmar está afirmado. O custo de *service message* que o critério manda considerar fica dito no desenho: é **uma** por contacto e por versão do texto |
| 9b | …e o gate está ligado ao caminho de canal? | **não, e são duas coisas que faltam, nomeadas** | O módulo está entregue e provado; **o `ConsentGate` não está construído em `services/worker-canal/src/entrada.ts`**, e isso fica dito em vez de implícito. Não é um passo esquecido: ligá-lo precisa de **duas** coisas que aquele processo não tem. A primeira é um caminho de **envio** — o `Saida` do KAM-015 não está construído ali (o *worker* tem três ligações à base e uma fila, e nenhum cliente da Meta), e sem ele o gate barrava o AGR **e não conseguia mandar o aviso**: uma loja muda sem sequer avisar porquê, que é o pior dos desfechos possíveis. A segunda é uma **versão do texto publicada** (KAM-104). A ordem de activação é: parecer → publicar a versão → construir o `Saida` no *worker* → ligar o gate. O que este ramo entrega é o que não depende de nenhuma das duas |

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **marcada** | Os nove, com a nota do 9: a metade que depende do KAM-017 não tem como ser exercitada e o comportamento que ela pede é o por omissão deste gate. Nenhum critério pede aqui o que o esquema não tem — ao contrário do KAM-021 — e as quatro divergências que se registaram (dívidas 75 a 78) são **do bloco contra documentos que outro ticket já corrigiu**, pedidos que não têm objecto, ou **dois critérios do mesmo bloco a pressupor dois textos quando um terceiro especifica a tabela com um** |
| Código revisto por **2 revisores** (dados pessoais); testes verdes; cobertura ≥ limiar | **vazia** | Testes verdes e cobertura **medidos**: **1 324** testes de unidade, **1 323** a passar, **0 a falhar** (o saltado é pré-existente, nos segredos), dos quais **55** novos em `tests/consentimento.test.ts` e **18** em `tests_bd/consentimento.bd.test.ts`; as três *suites* do *gate* 8 verdes (`tests` **486**, que inclui os **25** da revisão e o `downgrade`; `tests_outbound` 10; `tests_isolamento` **78**); `src/consentimento/` entre **98% e 100%** por ficheiro, contra os 75% do estrato `restante` de `ci/thresholds.yaml`. **Zero revisores humanos** — é decisão do fundador, e a caixa fica vazia como facto registado. **Esta é a única caixa deste epic que pede dois**, por serem dados pessoais, e é por isso que fica vazia e não meia |
| Documentação actualizada; reconciliação dos três desenhos registada; Conventional Commits | **marcada, e a reconciliação já estava feita** | Desenho em [`../docs/consentimento.md`](../docs/consentimento.md). Emenda **1.28** ao dicionário (§3.19) e `canon/dicionario.yaml` regenerado — `dict_export --check` e `canon_lint` conformes, v1.28, 207 entradas. O `../docs/ci.md` §3 ganha as cinco propriedades novas e a linha de versão **1.48**. **A reconciliação dos três desenhos é do KAM-140**, e mede-se: o `../docs/tecnica/06` §7.3 diz por extenso «o DDL de referência vive em `10` §7.2 (KAM-140)» e enumera os quatro campos que divergiam; os nomes `consent_log` e `consent_ledger` não aparecem hoje em documento técnico nenhum, só na coluna de variantes do dicionário §3.1 — que é onde pertencem. O que fica é o resíduo do `EPIC-07` §559, na dívida **75** |
| **Isolamento de tenant** — RLS em `consent_event`/`consent_texts`; teste cruzado | **marcada, com a razão da segunda escrita** | `rls.enable_tenant_rls("consent_event")` na `0015`, com `FORCE` e a política `tenant_iso` (ADR-015); a descoberta do X-05 passa de vinte e três para **vinte e quatro** tabelas e a tabela ganhou receita de sementes no *gate* 6. Teste cruzado nos dois sentidos, com a metade positiva primeiro, **e através da vista** — que é o caminho por onde um defeito passaria sem ninguém olhar. **A `consent_texts` não tem RLS porque não tem dados de *tenant* para isolar**, e o *gate* 6 não lhe pergunta: a descoberta do X-05 é pela coluna `tenant_id`. Não é uma excepção declarada — o `../ci/rls_exceptions.yaml` continua com **uma** entrada. Dívida **77** |
| **Idempotência** — botão repetido não duplica registo; teste incluído | **marcada** | Critério 2, acima, em **dois** níveis: o mesmo botão duas vezes (sequencial) e dois cliques em paralelo em **duas ligações** (o índice único a serializar). E a chave não é inventada: é o próprio `evidence_hash`, que leva o `wamid` e a hora da Meta |
| **Privacidade** — `contact_id` (nunca telefone); texto e prova versionados; base legal «a confirmar por parecer» | **marcada** | O módulo nunca vê um telefone: as portas falam em `contact_id`, `conversation_id` e `phone_number_id` (que é o número **da loja**, não do cliente). «**nenhum `outcome` leva o texto do cliente nem o wamid**» usa o `Logger` real em modo estrito e passa a lista branca de nove campos — e nenhuma das cinco métricas leva identificadores. O texto da Meta e o do cliente **não** entram no registo de linha. A base legal está escrita como por fixar no dicionário §3.19, no desenho e no módulo: das dez finalidades, só a `marketing` tem fonte directa e CONFIRMADA no `E3`, e **seis não têm nada** |
| **Custo e observabilidade** — `consent_notice_sent_total`, `consent_accepted_ratio`, `consent_optout_total` | **marcada** | As três, pelos nomes do DoD, e duas a mais: o `consent_accepted_total` (o numerador do rácio, exposto para que ele se possa **verificar**) e a `consent_blocked_total{accao}`, que não está no DoD e entra porque *barrar sem contar é barrar em silêncio* — sem ela, um painel não distingue «os clientes estão todos a consentir» de «não há texto vigente e o gate está a barrar tudo», e o segundo é uma loja muda. O rácio vale `-1` antes do primeiro aviso e **não se limita a 1**. Declaradas no §3.19 |
| **Migrações reversíveis** — `downgrade` testado (`consent_event` é aditivo) | **marcada** | `TestDowngradeDa0015`: desce **com linhas** e sobe outra vez; as duas tabelas **e a vista** desaparecem, o contacto fica, e o `upgrade` repõe tudo. **Não recusa com linhas**, e a razão está na revisão e não é que a prova valha pouco — é que uma cópia para ficheiro, que é o que a `0010` e a `0012` fazem, era guardar prova jurídica fora do esquema, sem RLS e sem retenção. **A vista cai primeiro**, e isso não é cerimónia: sem `CASCADE`, o `DROP TABLE` **falha** enquanto ela existir |

#### A primeira vista do esquema, e os quatro sítios que ela sacudiu

Nenhum estava previsto, e os quatro são da mesma família: código que dizia
«tabelas» e media **relações**.

1. **O `test_tenant_id_e_not_null_e_vem_primeiro_num_indice`** descobria pelo
   `information_schema.columns`, que inclui as colunas das **vistas** — e a
   `consent_actual` tem `tenant_id`. Uma vista não tem índice nem `NOT NULL`,
   pelo que as duas asserções não se lhe aplicam. Passou a filtrar
   `table_type = 'BASE TABLE'`, e a divisão de trabalho ficou dita: tabelas ali,
   vistas no `verificar_vistas`.
2. **O `_tabelas` do `test_media_schema.py`** era o único dos três ajudantes com
   o mesmo nome que **não** filtrava (os do `test_conversas_schema.py` e do
   `test_handoff_schema.py` leem o `pg_tables`, que já só tem as de base), e
   passou a devolver uma relação a mais do que a tupla `TABELAS`.
3. **O inventário** ganhou a vista como entrada, e **derivada** da tabela em vez
   de copiada: as três colunas que ela não mostra estão declaradas numa
   constante com a razão de cada uma, e a razão da derivação é a do
   `events_log_default` — uma cópia envelhece e ninguém nota.
4. **O domínio de `consent_texts.purpose`** precisou de ser declarado **outra
   vez** no dicionário. Os domínios dele são qualificados pela coluna (a decisão
   é da emenda 1.14), pelo que o *gate* 3b não reconhece em `consent_texts` os
   dez valores declarados em `consent_event`: **nove achados**
   `fora-do-dicionario` à primeira volta, um por cada valor que não é o
   `marketing`. O que **não** se fez foi declará-los em `../canon/extensoes.yaml`,
   que é o que a mensagem do gate sugere — uma extensão é para um nome que o
   dicionário não tem, e estes tem.

#### O que a prova por mutação diz

**Trinta e seis** mutações novas — **nove** da revisão `0015` e **vinte e
sete** do código. A mais importante não é de lógica: **tira o
`security_invoker = true` da vista**, e o que a mata é o `verificar_vistas` do
catálogo, que existia desde o KAM-004 e nunca tinha tido nada para matar.

As outras revertem defeitos reais: a unicidade da prova a desaparecer e a passar
a global, o resumo a aceitar qualquer tamanho, a aplicação a ganhar `UPDATE` na
prova e `INSERT` no texto jurídico, a tabela a nascer sem política, a versão
vigente a incluir as futuras e a ser a mais antiga, o estado a ler a tabela em
vez da vista, o registo a reescrever a prova, a contagem de avisos a contar a
conversa toda e a deixar de a filtrar, o «PARAR» a disparar dentro de uma frase,
a normalização a deixar de tirar acentos e caixa, o texto livre a autorizar o
agente, uma versão desactualizada a valer, uma recusa a contar como
consentimento, o `enviar_politica` a autorizar, o aviso a repetir-se para
sempre, o «PARAR» a deixar de ser lido primeiro, um botão desconhecido a passar
por «Continuar», o separador da prova a desaparecer, a prova a deixar de cobrir
a hora, o texto a sair com o marcador em claro, o rácio sem aviso a dizer que
ninguém aceitou, a prova a escrever-se **depois** de autorizar, e a falha
fechada a deixar de o ser.

**Duas foram escritas e descartadas, e vale dizer quais.** A primeira trocava o
`DISTINCT ON` da vista por um `GROUP BY`: não há forma de o escrever que devolva
as mesmas colunas, pelo que a migração **não corre** — e uma mutação que rebenta
na criação é apanhada por qualquer teste, o que não prova nada sobre a vista. A
segunda apagava o `DROP VIEW` do `downgrade`: sem `CASCADE` o `DROP TABLE`
**falha** enquanto a vista existir, pelo que o que o teste apanha é «o Alembic
falhou» e não uma propriedade da ordem.

**E uma sobreviveu, e era um teste em falta no caminho mais normal que
existe.** Trocar o `consent_actual` pela `consent_event` no `SQL_ESTADO` **passou**
a prova inteira, porque com **uma** linha por `(tenant, contacto, finalidade)` as
duas consultas dão o mesmo: o `DISTINCT ON` da vista só se distingue de um
`SELECT` sobre a tabela quando há **duas**. E duas há — o contacto aceita a `v1`,
o texto sobe para a `v2`, ele aceita outra vez —, e sem a ordem da vista a tabela
devolve as duas linhas **sem ordem garantida**: com a `v1` à frente, o estado
ficava `desactualizado` para sempre e o aviso repetia-se para sempre. Entrou
«**duas provas do mesmo trio: o estado e o da ultima**», que escreve as duas
linhas pelo caminho do módulo e verifica que a tabela tem duas, a vista tem uma, e
a vista é a `v2`.

**E uma mutação nova entrou depois da corrida**, porque ela é de um defeito que
eu próprio escrevi a corrigir outro: ver o achado 1 da revisão adversarial.

Depois das correcções: **35 corridas, 0 não apanhadas**.

`python db/mutacoes.py --aplicaveis` → **486 conferidas, 0 não aplicáveis**.

#### A revisão adversarial, e os dois achados que nenhuma máquina daria

1. **O nome da loja lia-se em todas as mensagens.** A primeira versão calculava
   o texto preenchido antes de saber o que ia fazer com ele — uma consulta ao
   `tenants.nome` por **cada** mensagem de cada conversa da plataforma, para um
   valor que o caminho comum (`seguir`) não usa. Passou a ler-se só quando alguma
   coisa o vai usar.

   **E a correcção teve o seu próprio defeito, que vale mais do que o achado.** A
   condição era `enviaMensagem(accao) || accao === "passar_a_humano"`, e o
   `registar_e_seguir` — que é o «Continuar», o caminho mais importante do
   ticket — **não envia mensagem**. Caiu fora, e a prova do consentimento passava
   a ser calculada sobre uma cadeia **vazia**. Quem a apanhava era «**a prova
   guardada e a que se recalcula**» do ensaio contra a base; o `enviaMensagem`
   sozinho não sabia dizer isto. As duas listas estão agora **nomeadas** —
   `enviaMensagem` e `registaProva` —, com um teste que afirma as duas e a
   intersecção delas, e uma mutação que prende a segunda.
2. **O «Saber mais» enviava o texto sem botões**, e deixava o cliente sem acção
   nenhuma — pior do que qualquer das duas leituras do critério 3. O critério
   pede «o texto completo **e** repete o aviso», que lido como duas mensagens
   contradiz o «exactamente 1 mensagem de saída» do critério 1; e a
   `consent_texts` que o critério 7 especifica tem **um** texto por versão.
   Cumprem-se as duas metades em **uma** mensagem: o texto vai com os três
   botões. **Não se acrescentou coluna** — o texto que vai ser revisto
   juridicamente é um, e dividi-lo é decisão de quem o escreve (KAM-104). Dívida
   **78**.

#### Os quatro defeitos que uma máquina apanhou, e o quarto é o mais sério

Nenhum estava no esquema nem no módulo, e os dois são da mesma classe: a bateria
a afirmar sobre o **ensaio** em vez de sobre o que o ensaio devia medir.

1. **O `excepcao.sqlstate` não existe.** A primeira versão da bateria de esquema
   inventou-o; o `pg8000` põe o código no campo `C` do dicionário da mensagem do
   servidor, e o `db/tests/base.py` **já tinha** o ajudante `sqlstate()` e os
   nomes dos SQLSTATE. **Dezasseis erros** à primeira volta do *gate* 8.
2. **A metade positiva do *append-only* contava linhas que a aplicação não podia
   ver.** A ligação que o `ComBase` dá nunca confirma, pelo que a sessão do
   `kamba_app` — que é outra — não vê o que o administrador acabou de escrever: o
   `SELECT` media `0` e o `INSERT` batia na FK composta com `23503` **antes** de
   o privilégio chegar a ser avaliado. Passou a afirmar o **privilégio**, que é o
   que o critério 6 pede, e quem exercita a escrita de verdade é o ensaio em Node
   contra dados confirmados.
3. **O CI apanhou uma afirmação que eu tinha escrito duas vezes, e esta é a
   mais séria das quatro.** O ensaio «duas provas do mesmo trio» passava
   localmente e falhava no *gate* 8 do CI **com os mesmos dados**, porque a ordem
   da vista não era total: ver o critério 6c. Não é um teste instável — é um
   defeito de desenho que só uma segunda máquina podia mostrar, porque o
   resultado dependia da ordem física das linhas.
4. **O CI apanhou também o que eu não corri, e é a lição do próprio ciclo.** Declarar
   `consent_event.canal ∈ {whatsapp}` no dicionário fez o *gate* 3b passar a
   **exigir** um `CHECK` fechado nessa coluna em qualquer revisão que a crie — e a
   *fixture* **positiva** `D-02_consent_event.py` do canário do `canon_lint`
   criava-a sem ele. Eu tinha corrido o `dict_export --check` e o
   `canon_lint check`, que são as duas primeiras linhas do alvo `ci-3b`; a
   terceira é o `canon_lint canario`, e foi ela que falhou — **e com ela o
   *gate* 4**, porque o `test_o_canario_esta_verde` corre o canário dentro dos
   testes de unidade. A *fixture* ganhou o `CHECK`, com a razão escrita no
   `docstring` dela: ela encarna o que o gate deve **aceitar**, e por isso tem de
   acompanhar o canon. O `docstring` já contava esta história uma vez — para o
   `purpose`, no KAM-159 — e agora conta-a duas.

---

## KAM-023 — Monitorização do free tier de service messages e do método de pagamento da PME

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | S |
| Dependências | KAM-015 |
| Bloqueia | KAM-081, KAM-083, KAM-094, KAM-115 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§7.1, §8.4, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1), `../docs/tecnica/00_Arquitectura_Solucao.md` (§9, §11), ADR-018 |

### Contexto

Factos CONFIRMADOS (E1 §1): desde 2026-10-01 só as primeiras 1.000 *service messages* **entregues** por número e mês são grátis (reinício às 00:00 no fuso da conta), depois 0,004 USD; sem método de pagamento na conta a Meta entrega as do *free tier* mas **deixa de entregar** depois; falha silenciosa a vigiar nos estados `failed`. Alvo do doc 00: alertas aos 80% (800). **NÃO VERIFICADO:** o fuso exacto da conta Meta, como o webhook marca as mensagens dentro do *free tier* (apenas `pricing.type` das *utility* na janela está descrito) e o código de erro da falta de método de pagamento. A pergunta sobre este código deve acrescentar-se ao pacote de KAM-101.

### Objectivo

Contar mensagens *service* entregues por canal e mês, alertar aos 800 e aos 1.000, estimar o custo acima do limite e detectar a provável falta de método de pagamento por falhas de entrega, alimentando o painel de custos.

### Critérios de Aceitação

- [x] `tenant_channels.free_tier_used` e `free_tier_month` contam mensagens de categoria *service* com estado `delivered` por `phone_number_id`; 1.200 estados sintéticos → contador 1.200.
- [x] Idempotência: estados duplicados do mesmo `wamid` não contam duas vezes (3 repetições, contador +1).
- [ ] Alertas: 1 aviso ao atingir 800 (80%) e 1 aos 1.000, sem repetição no mesmo mês; reinício do contador à meia-noite do fuso configurado do canal (`Africa/Luanda` por omissão; reconfirmar contra a primeira factura da Meta).
- [ ] Estimativa de custo `max(0, n − 1000) × 0,004 USD` lida de `config/meta_rates.yaml`: 1.200 mensagens → 0,80 USD; exposta como `meta_free_tier_used_ratio{tenant}` e `meta_cost_usd_estimate{tenant}`.
- [x] Detecção: depois de ≥ 1.000 entregues no mês, uma taxa de estados `failed` acima do limiar (proposta: 20% em 20 mensagens) gera alerta «possível método de pagamento ausente ou inválido» ao dono e a operações; cada código de erro visto é guardado em `meta_error_codes_seen` (para identificar o código concreto, NÃO VERIFICADO).
- [x] O alerta marca o canal com `motivo_restricao='payment_method'` e dispara `channel.updated`; remover o motivo exige estado `delivered` posterior ou limpeza manual registada.
- [ ] Reconciliação (critério de saída): ao fim de 1 mês real, o contador interno vs `pricing.billable` agregado diverge ≤ 2% (proposta) e o resultado é registado no ticket; discrepâncias sobem a KAM-101.
- [x] Os valores alimentam KAM-081 sem recalcular: métricas por tenant e canal, sem conteúdo.

### Detalhes Técnicos

- **Componentes:** ChannelAdapter/metering (consumo dos estados de KAM-015), OBS (alertas), CHR (marca de restrição).
- **Fonte de contagem:** estados com `pricing.category = service` e `status = delivered`; o campo `pricing.billable` é registado mas não se confia nele para decidir o *free tier* até a reconciliação; mensagens enviadas pela app do dono em coexistência não contam (não são Cloud API).
- **Tarifas:** `config/meta_rates.yaml` (Rest of Africa, efectivas 2026-10-01: *service* 0,004; *utility* 0,004; *marketing* 0,0225; *authentication* 0,004; CONFIRMADO, perecível, revisão trimestral — 1 Jan, 1 Abr, 1 Jul, 1 Out, a confirmar no calendário da Meta).
- **Gate de activação:** a verificação de que o método de pagamento existe no Billing Hub é KAM-093; aqui só a detecção em *runtime*.
- **Fora de âmbito:** dashboard de unit economics (KAM-081), cobrança à PME, runbook de cartão (KAM-083).

### Testes Requeridos

- Unit: contagem, reinício mensal com relógio fixo (fronteira de mês no fuso `Africa/Luanda`), custo.
- Integração com fixtures do simulador: 1.200 estados, duplicados, rajada de `failed`.
- Isolamento: contadores de A não afectam B; X-03 sobre `meta_error_codes_seen`.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada; tarifas com data de leitura da evidência; Conventional Commits.
- [x] **Isolamento de tenant** — contadores por canal/tenant com RLS e teste cruzado.
- [x] **Idempotência** — contagem por `wamid` com teste de repetição.
- [x] **Privacidade** — métricas e alertas sem telefone nem conteúdo.
- [x] **Custo e observabilidade** — as métricas acima nascem com o código (ADR-018).
- [x] **Migrações reversíveis** — `downgrade` testado.

### Verificação dos Critérios de Aceitação

Entregue no ramo `feature/KAM-023-free-tier-e-metodo-de-pagamento`, em **duas
metades**: a de código, sem DDL, e a revisão `0013`, que entrou quando a `0012`
do KAM-020 chegou a `main`.
**Onze caixas marcadas, cinco vazias** (16 = 11 + 5) — cada uma com uma linha
aqui. Os números reproduzem-se com os comandos do `Makefile` dos *gates* 2, 3,
3b, 4, 8, 9 e 11, e com `python db/mutacoes.py <python> "free tier:"` e
`"restricao"`.

**A tabela abaixo tem mais linhas do que há caixas, de propósito.** Três dos
critérios pedem duas coisas numa frase só, e uma delas cumpre-se e a outra não
— o 3 pede os alertas **e** o fuso «do canal», o 4 pede a conta **e** a etiqueta
de *tenant*, o 7 pede o instrumento **e** um mês real. Dividi-as para a
evidência ser atribuível, mas **a caixa é uma só e fica vazia quando qualquer
das metades falha**: cumprir à letra e não em espírito. Das oito caixas de
Critérios de Aceitação ficam marcadas **cinco** (1, 2, 5, 6 e 8); das oito do
DoD, **seis**.

> **Este ticket entregou-se em duas metades, e a razão da ordem é mecânica.**
> Os critérios 5 e 6 pedem `tenant_channels.motivo_restricao` e
> `meta_error_codes_seen`, e **nenhum dos dois existia** — nem em `db/`, nem no
> dicionário, nem nas extensões, nem em código. São DDL, e uma revisão de base
> encaixa na anterior pelo `down_revision`: a `0012` estava num ramo do KAM-020,
> e duas revisões a reclamar o mesmo pai não são uma colisão mecânica — o
> Alembic recusa.
>
> Por isso a metade de código entrou **primeiro e sem esperar** (contagem,
> alertas, custo, métricas, e a *decisão* do critério 5), e a revisão `0013`
> entrou quando o KAM-020 fundiu, no mesmo PR. O que ficou de fora não é
> trabalho em falta: são as quatro caixas abaixo, cada uma com a sua razão.
>
> **A premissa de que «este ticket não precisa de migração nenhuma» era
> verdadeira só para as duas colunas do contador**, que existem desde a `0001` e
> já estão no `GRANT UPDATE` de `kamba_app`. O `docstring` da `0010` entrega-lhes
> a manutenção a este ticket por extenso; as outras duas precisavam de DDL, e é
> a diferença entre as duas metades.

**O contador não decide sozinho quando conta, e isso é o desenho.** Quem sabe se
uma chegada de `statuses` foi **a** que entregou a mensagem é o
`SQL_AVANCAR_ESTADO` do KAM-015, que decide sob `FOR UPDATE`. O adapter passou a
devolver esse facto (`entregou`) — **um campo, já calculado lá dentro** — e é
dele que a contagem parte. Reler o estado aqui para o re-decidir reabria a
corrida que o KAM-015 fechou, desta vez no contador em vez de no custo.

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Contador de *service*/`delivered` por `phone_number_id`; 1.200 → 1.200 | **satisfeito** | `tests_bd/metering.bd.test.ts`, «**1.200 entregas dao contador 1.200**»: mil e duzentos incrementos contra PostgreSQL, lidos **da coluna** pelo administrador. O mesmo número com porta falsa em `tests/metering.test.ts`. A contagem é «por `phone_number_id`» como o critério manda, com junção por `tenant_channels` porque `outbound_messages` guarda `channel_id` e não o número (dívida 66) |
| 2 | Idempotência por `wamid`: 3 repetições, contador +1 | **satisfeito** | `tests_bd/metering.bd.test.ts`, «**tres `delivered` do mesmo wamid: contador +1**», com o adapter e o contador ligados de ponta a ponta. A propriedade é da base: três chegadas produzem **uma** transição. E `tests/outbound.adapter.test.ts`, «um delivered repetido nao volta a dizer `entregou`» |
| 3 | 1 aviso aos 800 e 1 aos 1.000, sem repetição no mês; reinício à meia-noite | **satisfeito** | Flanco e não valor: `tests/metering.test.ts`, «um mes inteiro de 1.200 mensagens da **um** aviso e **um** esgotado» → `{aviso: 1, esgotado: 1}`, e dois registos e não mil e duzentos. Sob concorrência: «**dois incrementos em paralelo na travessia: +2 e UM aviso**», em duas ligações. **A fronteira é a de `Africa/Luanda` e não a de UTC**: «**00:30 em Luanda ja e Novembro**» e «23:30 em Luanda ainda e Outubro» são dois instantes a **uma hora** de distância que caem em meses diferentes — em UTC seriam o mesmo. O fuso vem de `platform.ten_periodo` (`0007`) e não é reimplementado em TypeScript |
| 3b | …«do fuso configurado **do canal**» | **não satisfeito** | **Não há fuso por canal.** A única coluna de fuso do esquema é a de `tenants`, por *tenant*; um *tenant* com dois números não pode hoje ter dois fusos. Usa-se o do *tenant*, que é onde o fuso vive **num** sítio por decisão escrita do KAM-009. Criá-la por canal é DDL. Dívida 64, emenda 1.24 |
| 4 | Custo `max(0, n−1000) × 0,004 USD`; 1.200 → 0,80 USD | **satisfeito** | `tests/metering.test.ts`, «**1.200 mensagens dao 0,80 USD**» → 800 000 micro-dólares. Inteiros, pela razão do §2 do dicionário e do `tarifas.ts`. O limiar de aviso é **derivado** do tecto e não escrito: «**o aviso e 800, e e derivado do tecto**», para não poder divergir dele |
| 4b | …«exposta como `meta_free_tier_used_ratio{tenant}` e `meta_cost_usd_estimate{tenant}`» | **parcial** | As duas métricas existem; **a etiqueta de *tenant* não**. Não é implementável, e **a decisão não é nova**: é a que a emenda 1.21 já tomou para a `meta_cost_usd_total{tenant}` do KAM-015 — decidir ao contrário a dois módulos de distância punha o conjunto a contradizer-se. As bibliotecas da casa recusam por gramática uma etiqueta fora de `^[a-z][a-z0-9_]{1,62}$`, e um UUID com hífenes **levanta**: provado em «**um `tenant_id` como sufixo levanta**». Razão de fundo: `OBS-I` de `../docs/seguranca/ameacas_stride.md` e o X-11 do *gate* 6. Sem etiqueta, os *gauges* passam a agregados explícitos (máximo para o rácio, soma para a estimativa), porque «o último canal observado» não é o valor de nenhum. O por-canal sai de consulta |
| 5 | Heurística de falta de pagamento (20% em 20, depois de 1.000 entregues) | **satisfeito** | A decisão está entregue e provada: `tests_bd/metering.bd.test.ts`, «**a janela ignora o que ainda nao tem destino**» — 4 falhas em 20 resolvidas dão suspeita, e mais vinte em `queued` não a diluem —, com quatro casos de fronteira em `tests/metering.test.ts`. Os limiares são **proposta**, e a palavra é do próprio critério; a `meta_payment_suspect_total` existe para os calibrar. O código de erro concreto da Meta continua **NÃO VERIFICADO**: o `E1` nomeia três códigos e nenhum é de pagamento |
| 5b | …«cada código de erro visto é guardado em `meta_error_codes_seen`» | **satisfeito** | Revisão `0013`: `integer[]`, `NOT NULL DEFAULT '{}'`, com tecto de 32 por `CHECK`. É **coluna e não tabela** por três razões, e a primeira é o próprio X-03 que os *Testes Requeridos* pedem: passa a ser o de `tenant_channels`, que já corre — uma tabela nova com `tenant_id` que a *suite* não saiba semear **falha o *gate* 6**. Provas: «o mesmo codigo duas vezes entra **uma**» (é um conjunto), «**um statuses sem codigo nao mete `NULL` no conjunto**» (o `array_append(a, NULL)` não é um `no-op` e enchia o conjunto até o `CHECK` recusar), e «e os codigos de A nao se veem com o contexto de B (X-03)» |
| 6 | Marca `motivo_restricao='payment_method'` e dispara `channel.updated` | **satisfeito** | Revisão `0013`, com domínio fechado de três valores (o `quality` do KAM-021 e o `policy` do KAM-017 nascem lá pela mecânica do *gate* 3b). O evento vai pelo `platform.evt_emitir`, na transacção de quem chama, e o envelope constrói-se **em SQL** — a regra do KAM-005 e do ADR-009. Provas: «**marca, guarda o codigo, e o `channel.updated` cai no outbox**», «**uma segunda marca nao emite outro evento**» (um evento por mensagem falhada é o contrário de um alerta), «**um motivo diferente nao sobrepoe o primeiro**», «**duas marcas em paralelo: um evento e nao dois**» (o `FOR UPDATE`, em duas ligações), e «**com o contexto de A, o canal de B nao se marca** (X-03)». A segunda metade do critério — «remover o motivo exige estado `delivered` posterior» — é a `levantarRestricao`: «**levantar exige o motivo certo**, e emite» |
| 6b | …e o canal passa a `restrito`? | **decisão escrita, não tomada** | O critério **não o pede**, e este ticket **não o faz**: marca o motivo e emite o evento. Passar uma loja a `restrito` por uma heurística de limiares *propostos* (20% em 20) era cortar-lhe o atendimento por uma suspeita; quem restringe de facto é o KAM-021 (qualidade RED) e o KAM-094 (gate de activação). Está escrito no `docstring` da revisão e na emenda 1.26 |
| 7 | Reconciliação ao fim de **1 mês real**, divergência ≤ 2% | **não satisfeito** | **É critério de saída e não de PR**: pede um mês de Piloto, e um mês real não cabe num PR. O instrumento está entregue e provado contra `jsonb` real — «**a reconciliacao le o `pricing` jsonb e mede as duas divergencias**». Marcá-la com um ensaio sintético era marcar um critério de saída com dados que não são do mundo |
| 7b | …«o contador interno vs `pricing.billable` agregado» | **devolvido a quem escreveu o critério** | A frase compara **duas grandezas diferentes**: o contador conta todas as *service* entregues (1.200), o `billable` só marca as que estão acima do tecto (200) — dariam 83% de divergência num canal onde tudo está certo, e o limiar de 2% nunca fecharia. Medem-se **as duas** leituras que a frase admite (contagem contra contagem, facturável contra facturável) e a escolha devolve-se. Dívida 65 |
| 8 | Alimenta o KAM-081 sem recalcular; por tenant e canal, sem conteúdo | **satisfeito** | As funções puras (`microUsdEstimado`, `racioDoFreeTier`) e a `reconciliar` são exportadas em `src/metering/index.ts` para o consumidor não repetir a aritmética. Sem conteúdo nem telefone: «a exposicao tem as quatro, com tipo e ajuda, e sem etiqueta de tenant» afirma que nem o *tenant* nem o `phone_number_id` aparecem no ficheiro de exposição |

#### Definition of Done

| Caixa | Estado | Evidência |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **vazia** | Três dos oito não se satisfazem **à letra**: o 3 pede um fuso por canal que o esquema não tem, o 4 pede uma etiqueta de métrica que as bibliotecas recusam por gramática, e o 7 é um critério de **saída** que pede um mês real de Piloto. Nenhum é trabalho em falta neste ramo, e os três estão nas dívidas 65 a 68 ou devolvidos a quem escreveu o critério |
| Revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar | **vazia** | Testes verdes e cobertura **medidos**: **1 198** testes de unidade, 1 197 a passar, **0 a falhar** (o saltado é pré-existente, nos segredos), dos quais **59** novos em `tests/metering.test.ts` e **22** em `tests_bd/metering.bd.test.ts`; as duas suites do *gate* 8 verdes (`tests` 441, `tests_outbound` 10), e a do `tests` inclui o `downgrade` da `0013`; `src/metering/` entre **98% e 100%** por ficheiro, contra os 75% do estrato `restante` de `ci/thresholds.yaml`. **Zero revisores humanos** — é decisão do fundador, e a caixa fica vazia como facto registado |
| Documentação actualizada; tarifas com data de leitura; Conventional Commits | **marcada** | Desenho em [`../docs/metering.md`](../docs/metering.md), com a forma que o `outbound.md` e o `hnd.md` usam. Emenda **1.24** ao dicionário (§3.16) e `canon/dicionario.yaml` regenerado — `canon_lint` conforme, v1.24, 165 entradas, 26 extensões. O `../docs/ci.md` §3 ganha as cinco propriedades novas da *suite* `tests_outbound` e a linha de versão 1.43; `lint_contagens` conforme e `lint_refs` conforme (17 032 referências, 1 111 ficheiros). As tarifas mantêm a data de leitura do `E1` (2026-10-08) e a vigência `2026-10-01` em `config/meta_rates.yaml`, que este ticket **não altera**. Quatro dívidas novas (63 a 66) em `../docs/dividas-documentais.md` |
| **Isolamento de tenant** — contadores por canal/tenant com RLS e teste cruzado | **marcada** | `tests_bd/metering.bd.test.ts`: «**com o contexto de A, o contador de B nao se le**» (com a metade positiva primeiro, pela regra do `../docs/isolamento.md`), «**…nao se escreve**», e «e e simetrico». Uma política que só funcionasse num sentido passava acima |
| **Idempotência** — contagem por `wamid` com teste de repetição | **marcada** | Critério 2, acima |
| **Privacidade** — métricas e alertas sem telefone nem conteúdo | **marcada** | O aviso usa o `Logger` **real em modo estrito** e passa a lista branca de nove campos: «**o aviso passa a lista branca de nove campos** — e nao leva o canal». Não há campo para `phone_number_id`, e o alerta não o leva; quem avisa o dono com os detalhes é o KAM-115 |
| **Custo e observabilidade** — as métricas nascem com o código (ADR-018) | **marcada** | Quatro métricas, duas do critério 4 e duas acrescentadas pela razão da emenda 1.21 («avisar sem contar é avisar em silêncio»), com `# HELP`/`# TYPE` e lista fechada de etiquetas. Declaradas no §3.16 do dicionário |
| **Migrações reversíveis** — `downgrade` testado | **marcada** | Revisão `0013`, e o `downgrade` é testado pelo **efeito** em `db/tests/test_restricao_schema.py`: «desce com linhas marcadas e sobe outra vez» — as duas colunas desaparecem, **a linha do canal fica**, o privilégio volta a ser exactamente o da `0001`, e o `upgrade` repõe tudo. Ao contrário do da `0010`, este **não recusa com linhas**, e a razão está escrita na revisão: o que se perde é o motivo de uma restrição e um conjunto de códigos de diagnóstico, que se reconstroem do próximo `statuses`; nenhum é prova de nada perante terceiros |

#### O que a prova por mutação diz, e o que ela não pôde dizer

**Vinte e seis** mutações novas — quinze da metade de código e onze da revisão
`0013` —, cada uma a reverter um defeito **real**: o mês a sair como `date`, a
leitura a ignorar o mês guardado,
o `IS DISTINCT FROM` a voltar a `<>`, o reinício a começar em zero, o
`FOR UPDATE` a desaparecer, a janela de falhas a contar o que ainda não tem
destino, o aviso a voltar a ser o valor em vez da travessia, o rácio limitado a
1, a estimativa sem o `max(0, …)`, a suspeita sem o tecto, a divergência sem o
guarda do denominador zero, a etiqueta de *tenant* aceite, um canal
desconhecido a ganhar mil mensagens grátis, a reconciliação a voltar a comparar
meses em UTC, o domínio do motivo a perder um valor, o conjunto de códigos a
perder o tecto e a aceitar repetidos, a marca a sobrepor-se à primeira, o
`marcado` a voltar a sair do valor novo, a marca a perder o `FOR UPDATE` (e o
evento a sair duas vezes), o `levantar` a deixar de olhar para o motivo que lhe
dão, e o `event_id` ausente a ser calado.

**Uma décima segunda foi escrita e descartada, e o que ela ensinou está no
código.** Apagava o `REVOKE`/`GRANT` que o `downgrade` da `0013` fazia antes do
`DROP COLUMN`. **Nenhum teste a podia matar:** o PostgreSQL remove a concessão
**com** a coluna, pelo que os treze grants da `0001` sobrevivem ao `DROP` por si
sós e o resultado é idêntico. Uma mutação imortal não é um teste em falta — é um
sinal de que o código não faz nada, e aquelas duas instruções saíram da revisão.
A asserção do teste do `downgrade` continua a valer; o que mudou é que a
propriedade passou a ser garantida pela base em vez de por uma instrução nossa a
dizer o mesmo duas vezes.

`python db/mutacoes.py --aplicaveis` → **417 conferidas, 0 não aplicáveis**.

**E foi ele que apanhou um defeito que o `git merge` produziu sem conflito
nenhum.** O KAM-020 e este ticket escolheram ambos a constante `MED_SQL` em
`db/mutacoes.py` — ele para `src/med/consultas.ts`, este para
`src/metering/consultas.ts`. O `git` juntou as duas listas sem reclamar e a
minha, por vir depois, **sombreou** a dele: duas mutações da mídia passaram a
apontar para o ficheiro do *free tier*. Nenhum teste o via. O `--aplicaveis`
disse-o em segundos, que é exactamente para isso que corre em cada PR, e as
minhas passaram a `FT_*`. É a lição dos nomes em paralelo, aplicada a um
ficheiro de registo em vez de a um dicionário.

A prova destas: **26 corridas, 26 apanhadas** — mas as primeiras quinze só à
segunda, e o que ficou pelo caminho vale mais do que o resultado.

**À primeira, duas sobreviveram, e nenhuma delas era um teste em falta no
sentido habitual.**

A primeira — trocar `IS DISTINCT FROM` por `<>` no reinício — sobreviveu porque
o teste que a devia apanhar semeava o contador a **zero**, e com zero os dois
ramos do `CASE` dão o mesmo número: o `THEN 1` e o `ELSE 0 + 1`. A asserção
estava certa e a mutação era invisível para ela. Acrescentou-se o caso que a
torna visível — contador em 500 com o mês a `NULL` —, onde o ramo certo **repõe**
a 1 e o errado **soma** para 501. É a diferença entre «reinício» e «incremento»,
que é a palavra que o critério 3 usa.

A segunda — apagar a normalização do `antes` no reinício — sobreviveu porque
**não tinha efeito observável por caminho nenhum**: o `SQL_CONTAR` repõe sempre
a `1`, e com `para = 1` nenhum limiar é atravessado venha o `antes` de onde
vier. Era uma mutação imortal, da mesma família das duas que o KAM-019 mediu. O
que a tornou mortal não foi um caso artificial: foi reparar que a função é
**exportada** para o KAM-081 a reutilizar sem recalcular (critério 8), e que o
seu contrato promete a normalização a quem a chame com um lote. O caso novo
(`1500 → 900` com reinício) exercita esse contrato, que antes nenhum teste
tocava.

**Uma mutação que nenhum teste pode matar é pior do que nenhuma, porque conta
como prova** — e por isso há uma que **não** se declarou: tirar o predicado
`tenant_id` das consultas. Com a RLS ligada, a política `tenant_iso` filtra
igual e a mutação sobreviveria **por desenho**, não por falta de teste. O
predicado explícito é defesa em profundidade para quem corra a consulta sem
contexto, e fica dito aqui como o que é: **não provável por mutação enquanto a
RLS estiver de pé**.

Pela mesma razão, a bateria de unidade (`tests/metering.test.ts`) entrou na
lista de ficheiros da suite `tests_outbound`: as mutações em `custo.ts` e em
`metricas.ts` só por ela são apanhadas, e declará-las sem o seu oráculo era
declarar prova que não existe.

**A lista inteira (376) não se correu à mão.** O diff toca em
`src/outbound/adapter.ts`, que é alvo de quatro mutações, e num teste antigo —
o que, pela regra da *skill*, pedia a lista toda. A alteração ao adapter é
**aditiva** (um campo no tipo de retorno, já calculado lá dentro) e nenhuma das
quatro mutações do adapter ancora no que mudou; a alteração ao teste
**acrescenta** casos e aperta uma asserção, pelo que só pode tornar a detecção
mais forte. O `--aplicaveis` confirma-o em segundos, e a tarefa nocturna do
KAM-143 corre a lista completa.

#### O que a revisão adversarial apanhou

**Um defeito de correcção, na reconciliação, e tinha dois sintomas com a mesma
causa.** A primeira versão da `reconciliar` recebia o período por parâmetro, em
instantes:

1. **Comparava o contador de um mês com as entregas de outro.** O
   `free_tier_used` é **uma coluna e não uma série**: só sabe falar do mês
   corrente. Pedida sobre Outubro já em Novembro, a função lia um contador
   reposto a zero contra as mil e duzentas entregas de Outubro e devolvia 100%
   de divergência — num canal onde estava tudo certo. A API aceitava o pedido e
   respondia com um número sem significado, que é a pior forma de errar.
2. **As fronteiras do período vinham em UTC.** Um `delivered_at >= $3` com `$3`
   à meia-noite de UTC perde a última hora do mês de `Africa/Luanda` e ganha a
   primeira do seguinte. Era o **mesmo** defeito de fuso que o critério 3 existe
   para impedir, a entrar pela porta das traseiras — e numa reconciliação cujo
   limiar é 2%, uma hora de tráfego é exactamente o tamanho do erro que ela não
   distingue de ruído.

Os dois desaparecem com a mesma mudança: o período deixou de se exprimir em
instantes e passou a exprimir-se **pela função** — uma mensagem pertence ao
período quando `ten_periodo(delivered_at)` iguala `ten_periodo(agora)`, a mesma
função que decide o mês do contador, no mesmo fuso. Não há fronteira para errar,
e não há como pedir um mês de que o contador não sabe falar. A `reconciliar`
deixou de receber datas.

A asserção que o prova é a **décima quinta** mutação e o caso
«**uma entrega de outro mes nao entra, e a fronteira e a de Luanda**»: duas
entregas a **uma hora** de distância, que em Luanda caem em meses diferentes e
em UTC caem as duas em Outubro. Conta **uma**.

**E um segundo achado, mais pequeno e da mesma família: um número inventado
apresentado como medição.** O `estado` dobra «não sei» no tecto de propósito — a
porta do KAM-015 tem de devolver um número, e contar custo é a leitura
conservadora. Mas a `reconciliar` usava o mesmo caminho, e **uma agregação
devolve sempre uma linha**: o guarda de «zero linhas» nunca disparava lá, pelo
que um canal desconhecido saía do relatório como `contador: 1000` contra
`entregues: 0`. Separou-se o «não sei» do «mil» num método próprio: a porta
continua a dobrar, a reconciliação desiste. Caso novo:
«**a reconciliacao desiste, e nao reporta o tecto como medicao**».

#### Sobre os *gates*, e o que foi mesmo corrido

Esta máquina não tem `make`, `node` nem `pnpm`, e o `.venv` do repositório foi
criado dentro do Docker (`home = /usr/bin`), pelo que não corre em Windows. O
que se correu foi a **função** de cada *gate*, com o comando que o `Makefile`
usa, num ambiente montado para o efeito — e **não** `make ci-N`. Correram:
`lint_arch all`, `log_policy lint` e `canario` (2); `lint_refs check` (3);
`dict_export --check`, `canon_lint check` e `canario` (3b); a bateria de unidade
e a medição de cobertura (4); `gate_bd.py --suite tests_outbound` (8);
`scan_secrets tree` (9); `pip_lock --check-offline`, `sbom check` e
`supply_chain check` (11).

**Não** se correram, e o CI é que os corre: o *gate* 1 (build completo a partir
de um clone limpo), o *gate* 6 (isolamento e `x11`), e a metade Python do
*gate* 4. Correr a função de um *gate* não é correr os testes do *gate*, e a
distinção está aqui escrita porque já custou um CI vermelho neste projecto.

### Handoff para Claude Code

```text
És o executor do ticket KAM-023 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-023), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§8.4, §14) e
docs/tecnica/evidencia/E1_Meta_WhatsApp.md (§1). Objectivo: free tier de service messages e método de pagamento.
- Conta service/delivered por canal e mês (idempotente por wamid); alertas aos 800 e 1.000; reinício à meia-noite do fuso do canal.
- Custo estimado = max(0, n − 1000) × 0,004 USD a partir de config/meta_rates.yaml; métricas por tenant.
- Heurística de falta de método de pagamento: taxa de failed após 1.000 entregues; guarda os códigos vistos
  (o código concreto é NÃO VERIFICADO); marca motivo_restricao e emite channel.updated.
- Regista a reconciliação com a factura real num mês de Piloto (critério de saída).
Não expandas escopo: dashboard (KAM-081), gate de activação (KAM-093), runbooks (KAM-083).
Testes: contagem, fronteira de mês, duplicados, rajada de failed. Abre PR com o template do §7.
```

---

## KAM-024 — Simulador de webhooks Meta e testes de contrato com número de teste

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 0 |
| Tipo | chore |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-013 |
| Bloqueia | KAM-015, KAM-016, KAM-017, KAM-020, KAM-078, KAM-084 |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§4.4, §5.4, §16), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§6, §7), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§5), `specs/01_Engineering_Standards_e_Handoff.md` §4 (gates 7 e 15) |

### Contexto

O gate 7 exige contratos de webhooks Meta testados no CI e o gate 15 um *smoke* ponta a ponta com o número de teste. O ambiente `dev` usa *mocks* do webhook com corpo assinado com segredo de teste; `staging` usa o **número de teste** da app Meta (WABA de teste) e, nas semanas 1–3, 1–3 números +244 reais para o spike de coexistência. O número de teste **não prova** coexistência nem Embedded Signup em condições reais (`../docs/tecnica/09` §6). Entradas e campos a cobrir: os 11 tipos de §5.4 e os 11 campos de §4.4 de `../docs/tecnica/01`.

### Objectivo

Construir o simulador (biblioteca + CLI) que produz webhooks Meta assinados e um servidor Graph falso com cenários, mais a suite de contrato *offline* (obrigatória em cada PR) e *online* (nocturna contra o número de teste de *staging*).

### Critérios de Aceitação

- [x] `tools/meta-sim` gera, a partir de uma semente, payloads byte-idênticos (determinismo) para: `text`, `audio`, `image`, `document`, `location`, `interactive` (`button_reply`, `list_reply`), `order`, `reaction`, `sticker`, `unsupported`, `statuses` (`sent`, `delivered`, `read`, `failed`, com `pricing`) e `history`.
- [x] Cobre os 11 campos de webhook: `messages`, `smb_message_echoes`, `history`, `smb_app_state_sync`, `account_update` (6 motivos), `phone_number_quality_update`, `business_capability_update`, `account_alerts`, `message_template_status_update`, `template_category_update`, `message_template_quality_update`; um relatório de cobertura prova ≥ 1 *fixture* e ≥ 1 teste por tipo e campo (100%).
- [x] Casos adversos: assinatura inválida, JSON inválido assinado, corpo duplicado, mesma mensagem em dois corpos, ordem trocada, lote de várias `entry`, `wa_id` omitido (apenas BSUID/`username`), `phone_number_id` desconhecido.
- [x] A assinatura gerada é aceite pelo GWY de KAM-013 (ida e volta) e rejeitada quando o corpo muda 1 byte; o segredo de teste nunca coincide com um segredo de `staging`/`prod` (verificação de configuração).
- [ ] Servidor Graph falso com cenários programáveis: envio 200, 130429 (N vezes), 131049, 5xx, mídia, submissão de templates, troca de *code*, subscrições; usado por KAM-015, 016, 017 e 020.
- [x] Modo de re-entrega: reenvia o mesmo webhook com *backoff* exponencial comprimido (7 dias simulados em ≤ 1 min) para provar idempotência.
- [ ] Ferramenta de captura e saneamento: converte um webhook real em *fixture* substituindo identificadores por valores fictícios; recusa gravar se detectar um número que não pertença à lista de números fictícios; o repositório fica com 0 telefones reais (scan).
- [ ] Suite *offline* corre no gate 7 em ≤ 5 min (proposta); suite *online* corre 1× por noite no número de teste de *staging* e produz um relatório que compara a estrutura real com os schemas das *fixtures* (evidência de 1 execução verde em `docs/evidencia/KAM-024.md`).
- [ ] A suite *online* não é bloqueante de PR mas é de *release* (gate 15 em KAM-078); falha da Meta/credenciais gera alerta, não falso verde.

### Detalhes Técnicos

- **Componentes:** GWY (consumidor), todo o canal (fixtures), OBS. Pacote `tools/meta-sim` (TS) com schemas JSON dos payloads derivados da documentação e validados contra capturas reais.
- **Ambientes (`../docs/tecnica/09` §6):** `dev` com *mocks*; `staging` com número de teste da app Meta de *staging* e chaves distintas das de `prod`; coexistência e ES v4 só com número +244 real (fora desta suite).
- **Limites conhecidos:** o *timeout* exacto do webhook e o *pair rate limit* são NÃO VERIFICADOS (L2); o simulador não os inventa e expõe-nos como parâmetros configuráveis.
- **Segurança:** os telefones fictícios usam um intervalo reservado definido em `tools/meta-sim/fake_numbers.yaml`; nenhum token real no repositório (scan KAM-002).
- **Fora de âmbito:** *smoke* completo de CI/CD e deploy (KAM-078), mocks do facilitador de pagamento (EPIC-05).

### Testes Requeridos

- Unit: determinismo por semente, assinatura, saneamento de capturas.
- Contrato *offline*: todas as *fixtures* contra o GWY de KAM-013 e os tratadores de KAM-014/015/017/021.
- Contrato *online*: 1 execução real no número de teste (mensagem, estado, template) com relatório.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (evidência em `docs/evidencia/KAM-024.md`).
- [ ] Código revisto por ≥ 1 revisor; testes verdes.
- [x] Documentação actualizada (`docs/meta-sim.md`: como gerar *fixtures*, como correr o contrato *online*); Conventional Commits.
- [x] **Privacidade** — 0 telefones reais ou dados pessoais em *fixtures*; capturas saneadas.
- [x] **Sem segredos** — segredos de teste distintos dos de `staging`/`prod`; scan limpo.
- [x] **Dependências** — versões fixadas; licenças permitidas.
- [x] O gate 7 do CI executa a suite *offline* e falha o build.

### Handoff para Claude Code

```text
És o executor do ticket KAM-024 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-024), docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md (§4.4, §5.4, §16)
e docs/tecnica/09_Topologia_Operacao_Escala.md (§6, §7). Objectivo: simulador de webhooks Meta e testes de contrato.
- tools/meta-sim: payloads assinados e determinísticos para os 11 tipos de entrada e os 11 campos de webhook, com
  casos adversos (assinatura, JSON, duplicados, ordem, wa_id omitido, canal desconhecido) e modo de re-entrega.
- Servidor Graph falso com cenários (200, 130429, 131049, 5xx, mídia, templates, troca de code, subscrições).
- Captura e saneamento de payloads reais; números fictícios de fake_numbers.yaml; recusa números reais.
- Suite offline no gate 7; suite online nocturna no número de teste de staging, com relatório (não bloqueia PR).
Não expandas escopo: sem smoke de deploy (KAM-078), sem mocks de pagamento.
Testes: determinismo, ida e volta com o GWY, cobertura 100% de tipos e campos, 1 execução online. Abre PR com o template do §7.
```

---

### Verificação dos Critérios de Aceitação

Medido em 2026-10-20, ramo `feature/KAM-024-simulador-meta`. O detalhe, com a
saída de cada comando, está em `../docs/evidencia/KAM-024.md`.

Todas as medições de Node correram num contentor
`node:24.21.0-trixie-slim@sha256:173f1258…`: esta máquina de desenvolvimento não
tem `node`, `pnpm` nem `make` no `PATH`, e `make ci-7` numa máquina sem `make`
responde `command not found` — o que **não** é «o gate passa».

**Quatro caixas de critério e duas de DoD ficam vazias**, e cada uma é nomeada
abaixo com a razão. Três delas não são satisfazíveis por este ticket.

| # | Critério | Estado | O que se mediu |
|---|---|---|---|
| 1 | *Payloads* byte-idênticos para os 16 tipos | **satisfeito** | `node --test tools/meta-sim/tests/` — 6 asserções de determinismo verdes. Duas sementes iguais dão **32/32** *fixtures* byte-idênticas; duas sementes diferentes dão **0/32** iguais (zero, e não «poucas»: uma *fixture* igual significava que o gerador não entra naquele corpo). Terceira asserção: acrescentar uma *fixture* **não** muda os bytes das outras, porque a semente é `<semente>/<marca>` e não a posição na lista. O `timestamp` e o `entry.time` vêm do gerador, nunca do relógio |
| 2 | Os 11 campos, com relatório a 100% | **satisfeito** | `node src/cli.ts cobertura` → **100,0% (33/33)**, `exit 0`. Dezasseis itens de «tipo», onze de «campo» e **seis** de «motivo»; o `interactive` conta **duas** vezes, o `statuses` **quatro** e o `account_update` entra também pelos seis motivos de `PARTNER_REMOVED`, à letra dos critérios 1 e 2. A revisão adversarial mostrou porque é que os motivos têm de ser itens: quatro dos seis não tinham *fixture* nem teste, e existiam só na declaração do `enum`. **O relatório apanhou um defeito dos próprios testes**: as quatro marcas dos `statuses` estavam num `for` com o nome interpolado e o relatório deu **85,2% com quatro faltas** — correctamente, porque uma marca que só existe em execução não prova que alguém escreveu o teste. Corrigido para quatro `it` literais |
| 3 | Os oito casos adversos | **satisfeito** | Os oito, com o desfecho **declarado ao lado dos bytes** e lido de lá pelos testes. Medido contra o GWY: `assinatura_invalida` 401 e 0 *jobs*; `json_invalido_assinado` **200** e 1 *job*; `corpo_duplicado` 200+200 e **1** *job*; `mesma_mensagem_em_dois_corpos` 200+200 e **2** *jobs*; `ordem_trocada` 3 estados com 1 `wamid`; `lote_de_entries` 3 `entry` e 2 `waba_id`; `wa_id_omitido` sem `from` e sem `wa_id`, com BSUID nos dois sítios; `phone_number_id_desconhecido` com canal diferente do do cenário |
| 4 | Ida e volta no GWY; 401 a 1 byte; segredo distinto | **satisfeito** | `node --test services/gwy/tests/kam024.ida-e-volta.test.ts` → **19 testes, 0 falhas, 13,1 s**. As 32 *fixtures* dão 200 e 32 `jobId` distintos; 1 byte mudado dá 401 e **0** *jobs*; a mesma *fixture* **com espaços** — mesmo JSON, bytes diferentes — dá 401, que é o caso que apanha um GWY que normalize antes de verificar. O `assinar` do simulador tem `createHmac` próprio e não importa nada do `core-ts`: são duas implementações, senão a ida e volta ficava verde no dia em que o algoritmo estivesse errado dos dois lados. `exigirSegredoDeEnsaio` recusa um segredo sem o prefixo `ensaio-` **e** um igual ao valor de qualquer `KAMBA_SECRET_*` do ambiente |
| 5 | Servidor Graph falso, «usado por KAM-015, 016, 017 e 020» | **parcial** | A **primeira** metade está feita e medida: os oito cenários que o critério enumera existem, com **27 testes** verdes — envio 200; `130429` N vezes, com `[429,429,429,200,200]`, que é a letra do critério 1 do KAM-015; `131049`; 500 e 503; mídia, com URL expirada a dar 404 na descarga e 200 na metainformação; submissão e listagem de templates; troca de *code*; subscrições que guardam **quais** campos foram subscritos. Dois dos testes correm por cima de TCP real, com `fetch`. A **segunda** metade — «usado por KAM-015, 016, 017 e 020» — **não se pode medir**: nenhum desses quatro tickets existe. A caixa fica vazia e são eles que a fecham; a aresta de dependência já está declarada nas três superfícies do backlog (versão 1.2 deste epic) |
| 6 | Re-entrega: 7 dias em ≤ 1 min, a provar idempotência | **satisfeito** | Doze tentativas, `horizonteSimuladoS` = **604 800** (os sete dias exactos) em **13,1 s** de relógio, e **1** *job* na fila no fim. O teste afirma que o corpo **não muda** entre tentativas (`vistos.size === 1`): se mudasse, o `jobId` mudava com ele e o teste provava que duas coisas diferentes dão dois *jobs*, que é o contrário do que se quer. `razoesDeFalha` devolve as razões em vez de um booleano, para que a evidência possa dizer **qual** das duas condições falhou |
| 7 | Captura e saneamento; recusa; «0 telefones reais (scan)» | **parcial** | As **duas primeiras** cláusulas estão satisfeitas e medidas: 13 testes de saneamento verdes, incluindo os dois que fazem a ferramenta valer — o `wamid` novo **não** leva o número real dentro do base64 (o teste descodifica e verifica), e uma chave que o saneador não conheça dá `CapturaRecusadaError` a nomear a chave, porque a verificação é sobre a **saída** e não sobre a entrada. A **terceira** depende de uma leitura, e é por isso que a caixa fica vazia: ver «As duas leituras do critério 7», abaixo |
| 8 | *Suite* offline no gate 7 em ≤ 5 min; *suite* online nocturna com relatório | **parcial** | A **offline** está feita: `make ci-7-meta`, e as duas suites levam **24 s** contra os ≤ 5 min que o critério põe como *proposta* (o `pnpm -r run test` inteiro, 1095 testes, leva 70 s). A **online** não existe: depende de `ext:KAM-102` (Meta Business Verification e Tech Provider) e do número de teste da app Meta de *staging*, que não existem — `../docs/tecnica/09` §6 di-lo, e o próprio Contexto deste ticket diz que o número de teste «**não prova** coexistência nem Embedded Signup em condições reais». Não há como produzir «evidência de 1 execução verde» de uma *suite* que não pode correr |
| 9 | A *suite* online não bloqueia PR mas é de *release*; falha gera alerta | **não satisfeito** | **Não há *suite* online**, pela razão do critério 8. Escrever uma que se desligasse sozinha por falta de credenciais era construir exactamente o falso verde que este critério proíbe por extenso, e marcar a caixa com ela era pior do que a deixar vazia. As duas regras já decididas ficam escritas em `../docs/meta-sim.md` §9, para quem a escrever quando o número existir |

### A revisão adversarial, e as quatro caixas que ela reprovou

A revisão correu contra o estado do ramo **antes** desta secção, e devolveu
dezasseis achados — quatro graves. Reprovou quatro caixas que já estavam
marcadas, e vale escrever quais, porque é a diferença entre uma caixa marcada e
uma caixa verificada:

| Caixa | O que a reprovava | Depois da correcção |
|---|---|---|
| Critério 1 | Um `failed` com `comPricing: true` era engolido em silêncio, e o critério escreve «`statuses` (…, `failed`, com `pricing`)» | A omissão continua «sem `pricing`» — não se cobra o que não foi entregue — mas um `true` explícito é honrado, com teste |
| Critério 2 | Os 100% não provavam «≥ 1 teste»: 27 marcas escritas só em **comentários** davam 100%. E os «6 motivos» não eram itens | A marca tem de estar no nome de um `it(`, com dois testes a prová-lo nos dois sentidos. A tabela passa a **33** itens |
| DoD «Privacidade» | Um E.164 estrangeiro escrito sem `+` atravessava o `sanear`, o `exigirFicticios` e o *scan* — pela chave `history[].threads[].id`, que o próprio simulador produz. E as coordenadas eram números e passavam intactas | Uma terceira verificação, que é a lista **branca** que o critério pede; as oito chaves de texto livre que faltavam; e as coordenadas arredondadas à zona |
| DoD «gate 7 … falha o build» | **O `varrer` relativizava os caminhos contra o `cwd`**, e o `ci-7-meta` invoca-o com `cwd` = `tools/meta-sim`: `47 divergencias`, `exit 2` — em **todos** os PRs | A raiz vem do `pnpm-workspace.yaml`. Verificado nas três invocações (a do gate, a da raiz e a de outra pasta): `0 divergencias`, exit 0 |

O mais grave é o último, e o que ele diz sobre a verificação deste ticket é o
seguinte: **nenhum dos 133 testes o apanhava, porque nenhum deles corria o
comando que o `Makefile` corre.** Um teste que invoque a função e um gate que
invoque o CLI por `pnpm --filter exec` são duas coisas diferentes, e só a
segunda é o gate.

Os dezasseis achados, com a saída medida de cada um, estão em
`../docs/evidencia/KAM-024.md` §10 — incluindo os cinco que a revisão procurou e
**não** encontrou, que valem tanto como os outros.

### As duas leituras do critério 7, e porque é que a caixa fica vazia

Corri o *scan* sobre o repositório **antes** de escrever o inventário:
**89 ocorrências de forma real em 24 ficheiros**. Nenhuma é um descuido. Todas
são *fixtures* de redacção de PII — `tools/log_policy`, `tools/contract_diff`,
`packages/core-ts/src/eventos/pii.ts`, os dois *loggers*, as suites de
`platform.evt_emitir` — e existem para que o detector **dispare**.

As duas leituras do critério dão respostas opostas:

- «0 cadeias com a forma de um número angolano» é **insatisfazível**, e
  satisfazê-la destruía o que vale mais: um redactor testado só com números do
  `999` nunca prova que apanha um `+244 9…`, que é precisamente o que existe
  para apanhar. A caixa ficava marcada e a protecção ficava **pior**;
- «0 números que pertençam a uma pessoa real» é o que o DoD quer dizer («0
  telefones reais **ou dados pessoais**; capturas saneadas»), e é o que se pode
  defender — mas **não** por expressão regular, porque nenhuma distingue um
  número atribuído de um sequencial.

O que este ticket entrega para a segunda leitura é um **raquete**, e não uma
isenção: `tools/meta-sim/src/inventario.ts`, com uma entrada por ficheiro, a
contagem exacta e a razão que nomeia o que o número está a testar. Falha nos
quatro sentidos em que uma pasta permitida não falharia, e cada sentido tem o
seu teste: ficheiro com número e sem entrada; **um número a mais num ficheiro
já declarado**; um a menos, para a entrada não envelhecer; entrada sem medição,
porque o ficheiro mudou ou desapareceu. E uma razão com menos de trinta
caracteres é ela própria um defeito do inventário. O segundo sentido é o que
importa — é o único que uma pasta isenta deixava passar.

```
$ node tools/meta-sim/src/cli.ts varrer .
[KAM-024] varrer: 1053 ficheiros, 86 ocorrencias de forma real,
          86 declaradas no inventario, 0 divergencias   # exit 0
```

**Três** das 89 saíram neste PR: o `CORPO_DE_MENSAGEM` de
`services/gwy/tests/webhook.test.ts` tinha três números de forma angolana que
não testavam redacção nenhuma, e passaram para o intervalo fictício. O canário
da linha 648 desse ficheiro **fica**, e está declarado: o critério 9 do KAM-013
pede «1 000 pedidos com telefones nos logs e 0 achados», e um canário fictício
não provava nada.

Mesmo assim a caixa fica **vazia**, e é uma escolha e não um descuido: a letra
diz «0 telefones reais (scan)» e o *scan* devolve 86 ocorrências toleradas. A
regra desta casa é explícita — «um canário numa *fixture* falha o PR» não está
cumprido se a pasta do canário for uma área permitida, mesmo que a decisão seja
defensável. Quem decide se a leitura do inventário basta para marcar esta caixa
é quem escreveu o critério, não quem o executa.

### Verificação do DoD

| Linha | Estado | O que se mediu |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **não satisfeito** | Cinco de nove estão satisfeitos; os critérios 5, 7, 8 e 9 estão acima com a razão, e três deles não são satisfazíveis por este ticket. A evidência existe e está em `../docs/evidencia/KAM-024.md` |
| Código revisto por ≥ 1 revisor; testes verdes | **parcial** | **Testes verdes**: `pnpm -r run test` → **1095 testes, 0 falhas, 70 s** (meta-sim 162, gwy 63, core-ts 833, contracts 12, worker-canal 15, com 5, onboarding-web 5); `tsc -p` limpo nos quatro pacotes tocados. **Revisores**: a caixa fica vazia, como em todos os tickets desta fase — a decisão do fundador é fundir com o CI verde sem esperar revisão humana, e o *ruleset* de `main` exige 0 aprovações. É um facto registado, não um bloqueio. Houve **uma revisão adversarial** desta entrega |
| Documentação actualizada; Conventional Commits | **satisfeito** | `../docs/meta-sim.md`, com 11 secções: gerar, determinismo, assinatura e ida e volta, casos adversos, Graph falso, captura e *scan*, cobertura, re-entrega, *suite* online, códigos de erro. Mais `../docs/evidencia/KAM-024.md`. Os *commits* passam o `lint_arch` de mensagem, que corre no *hook* de *commit* |
| **Privacidade** — 0 telefones reais ou dados pessoais em *fixtures*; capturas saneadas | **satisfeito** | As 32 *fixtures* que este ticket gera passam todas por `exigirFicticios` num teste (`todos os telefones das fixtures sao do intervalo reservado`), e os oito casos adversos também — incluindo o `json_invalido_assinado`, que não dá `parse` e por isso se verifica sobre o texto. O saneamento tem 13 testes, e substitui o texto das mensagens **por inteiro** em vez de o limpar: uma limpeza parcial de texto livre é uma aposta, e é onde uma pessoa escreve o seu endereço. Nem o erro nem o *scan* imprimem o número que encontram, porque um relatório de CI fica no histórico das execuções |
| **Sem segredos** — segredos de teste distintos dos de `staging`/`prod`; scan limpo | **satisfeito** | `exigirSegredoDeEnsaio` recusa um segredo sem o prefixo `ensaio-` e um igual ao valor de qualquer `KAMBA_SECRET_*` do ambiente, com três testes. O `scan_secrets` do *hook* de *commit* correu limpo nos três *commits* deste ramo. O *token* que o Graph falso devolve diz-se de ensaio no próprio valor (`ensaio-token-…`), para que o scan do KAM-002 o separe de um real sem heurística |
| **Dependências** — versões fixadas; licenças permitidas | **satisfeito** | **Zero** dependências novas: o pacote usa `node:crypto` e `node:http` da biblioteca padrão e o vocabulário de `@kamba/core-ts`. É a razão de estar **na** *workspace* do pnpm, ao contrário do `tools/mermaid_lint` — e é o que faz os gates 2 e 4 cobri-lo sem alvo novo. `pnpm install --frozen-lockfile` → lockfile em dia, 115 entradas conformes à política de cadeia de fornecimento; `supply_chain check` → imagens, runtime, egress, licenças, renovate e ci todos conformes |
| O gate 7 do CI executa a *suite* offline e falha o build | **satisfeito** | `make ci-7` chama `ci-7-meta`, que corre `varrer`, `cobertura`, a *suite* do pacote e a ida e volta no GWY. **Falha o build** porque os códigos de saída são distintos: `0` conforme, `2` há achados, `1` a ferramenta não conseguiu correr. O terceiro existe de propósito — «0 ficheiros lidos» **não** é «0 achados», e devolver `0` aí transformava o gate num enfeite |

### Duas emendas à verificação, e as duas são consequências medidas

Não são arrumação: sem elas o gate 4 deixava de medir o que este ticket
acrescenta, e isso não se via de fora.

- **`tools/meta-sim` entra em `PACOTES_NODE`.** `tools/**` está nos `padroes` do
  estrato `restante` de `../ci/thresholds.yaml`, e o `coverage_gate` injecta a
  **0%** o que nenhum relatório mediu. Fora da lista, os dezasseis ficheiros do
  pacote entravam no denominador com zero.
- **`coverage_gate.base_do_nome` passa a conhecer a família `tools`.** Medido:
  sem isso, `node-tools-meta-sim.lcov` não casava família nenhuma, o resto vinha
  inteiro (`tools-meta-sim`) e os dezasseis ficheiros saíam como «medidos e não
  classificados por nenhum estrato» — que é o estado em que um ficheiro escapa
  ao limiar **em silêncio**. A comparação com `familia + "-"` mantém o
  `python-tools.lcov` a devolver `tools`.

Depois das duas: `critico` **96%** (mínimo 90%), `restante` **89%** (mínimo
75%), **0** ficheiros não classificados. Cobertura de linhas dos dezasseis
ficheiros do pacote: **98,8%** (3597/3641).

O `cli.ts` vai para `excluidos` pela mesma razão que os
`services/*/src/server.ts`: é um ponto de entrada que lê `process.argv` e chama
`process.exit`, e o gate 7 exercita-o três vezes.

---

## KAM-115 — Aviso ao dono por canal alternativo (e-mail ou push)

| Campo | Valor |
|---|---|
| Epic | EPIC-02 — Canais WhatsApp e Handoff |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-017, KAM-021, KAM-023, KAM-116 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/10_Onboarding_Governanca.md` (§6.4, §13), `../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` (§10.5, §11.4, §14), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §2), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§1, Art. 19.º), `../docs/tecnica/00_Arquitectura_Solucao.md` (§13.3, D10), ADR-001, ADR-008, ADR-010 |

### Contexto

Avisar o dono pelo canal que falhou é inútil. Factos CONFIRMADOS (E1 §2, §1): `PARTNER_REMOVED` (seis motivos, entre eles `PRIMARY_INACTIVITY`, ~14 dias sem abrir a app) desliga a coexistência; sem método de pagamento a Meta deixa de entregar *service messages* depois das 1.000 grátis. `../docs/tecnica/01` §10.5 e §14 e `../docs/tecnica/10` §6.4 mandam avisar o dono «por canal alternativo», mas nenhum ticket o construía (lacuna R16 deste epic). Os emissores existem: KAM-017 (`desligado` e `channel.updated`; aviso aos 10 dias), KAM-021 (`restrito` por qualidade RED) e KAM-023 (`motivo_restricao='payment_method'`). O canal alternativo não pode ser o número da loja (`../docs/tecnica/01` §11.4) nem um número operacional da KAMBÁ: D10 e KAM-101 condicionam esse número (o tenant `platform` está vedado até D2), pelo que este ticket **não o assume**. Canais: e-mail e notificação do painel/HND (push); o SMS fica atrás da interface `SmsProvider` de KAM-116 e só se activa quando esse contrato existir. O aviso é comunicação de serviço ao dono, não marketing; a base legal e a finalidade do contacto do dono são *(a confirmar por parecer, KAM-104)*.

### Objectivo

Consumir os eventos de falha ou risco do canal e enviar ao dono um aviso idempotente por e-mail e por notificação do painel, com limites de frequência, sem conteúdo de clientes e sem usar o WhatsApp.

### Critérios de Aceitação

- [x] Cinco gatilhos geram aviso: `channel.updated` com `desligado` (cada um dos 6 motivos de `PARTNER_REMOVED`), `channel.inactivity_warning` (10 dias), `restrito` por qualidade, `motivo_restricao='payment_method'` e HND indisponível > 5 min (*proposta*); cada um com texto próprio e o passo seguinte (reconectar, abrir a app, adicionar cartão). Um gatilho fora da lista não envia nada.
- [x] Idempotência por `hash(tenant_id, gatilho, episódio)`: o mesmo evento 3× (e re-entregue pela DLQ) produz 1 aviso; um novo episódio depois de resolvido produz outro.
- [x] Latência do evento ao aviso entregue ao fornecedor de e-mail ≤ 5 min p95 (*proposta*), medida com relógio acelerado e fornecedor falso.
- [x] Limites de frequência (*propostas*): ≤ 1 aviso por (tenant, gatilho) em 24 h e ≤ 3 por tenant/dia; lembretes às 24 h e 72 h se o estado persiste, depois pára e abre tarefa a T2; 500 eventos/hora de um só tenant enviam ≤ 3.
- [x] Conteúdo por allowlist de modelos (1 por gatilho): nome da loja, estado, hora, passos e ligação ao painel sem token nem identificador pessoal no URL; 0 telefones, `contact_id`, BSUID ou texto de clientes (varrimento X-11 sobre 200 avisos gerados).
- [ ] O dono tem ≥ 1 contacto alternativo verificado por ligação de confirmação (o e-mail é captado em KAM-086); tenant `ativo` sem contacto verificado gera alerta a T2 e a métrica `owner_alt_contact_missing`; alvo ≥ 95% dos tenants `ativo` com contacto verificado (*proposta*).
- [x] Falha de entrega (*bounce*, rejeição) marca o contacto como inválido, tenta o painel e abre tarefa a T2; nenhum aviso se perde em silêncio (falha injectada).
- [x] Nenhum adaptador de envio WhatsApp neste módulo (teste de configuração); o fornecedor de e-mail consta do inventário de subprocessadores (KAM-069) com `apd_ref`, ou fica `pendente` e bloqueia `prod` (ADR-008).

### Detalhes Técnicos

- **Componentes:** CHR (subscrição de eventos), HND (notificação do painel), OBS. Porta `OwnerNotifier.notify(tenant_id, gatilho, episodio, params)` com adaptadores `EmailNotifier`, `PanelNotifier` e `SmsNotifier` (desligado até KAM-116).
- **Registo de envio:** tabela `owner_notices` (`notice_id`, `tenant_id`, `gatilho`, `episodio`, `canal`, `estado`, `criado_at`, `entregue_at`) com RLS e sem corpo; a tabela `owner_notices` e o evento `channel.inactivity_warning` (de KAM-017) não constam do dicionário §3: a emenda é condição de merge (gate 3b de KAM-111).
- **Janela do aviso preventivo:** os 10 dias vêm da heurística de `../docs/tecnica/01` §10.5 (sem *echo* e sem acesso ao painel), a calibrar no Piloto.
- **Fora de âmbito:** adaptador SMS (KAM-116), número operacional da KAMBÁ (D10, KAM-101), runbooks (KAM-083), avisos de cobrança ao dono (KAM-058).

### Testes Requeridos

- Unit: idempotência, limites de frequência com relógio fixo, allowlist de modelos.
- Integração com fornecedor falso e o simulador de KAM-024 (6 × `account_update`, qualidade RED, falha de pagamento); *bounce*.
- Isolamento: eventos de A não avisam o dono de B (X-03 sobre `owner_notices`); privacidade: X-11 sobre os avisos.

### Definition of Done

- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Código revisto por ≥ 1 revisor; testes verdes; cobertura ≥ limiar.
- [x] Documentação actualizada (`docs/avisos-ao-dono.md`); Conventional Commits.
- [x] **Isolamento de tenant** — RLS em `owner_notices` e teste cruzado.
- [x] **Idempotência** — chave por episódio com teste de repetição.
- [x] **Privacidade** — avisos sem dados de clientes; endereço do dono só em cifra e nunca em logs.
- [x] **Custo e observabilidade** — `owner_notice_sent_total{gatilho,canal}`, `owner_notice_latency_s`, `owner_alt_contact_missing`.
- [x] **Migrações reversíveis** — `downgrade` testado.

### Handoff para Claude Code

```text
És o executor do ticket KAM-115 da KAMBÁ (plataforma WhatsApp-native de comércio conversacional para Angola).
Lê specs/EPIC-02_Canais_WhatsApp_Handoff.md (bloco KAM-115), docs/tecnica/10 (§6.4, §13) e docs/tecnica/01 (§10.5, §14).
Objectivo: avisar o dono por e-mail e painel quando o canal falha ou está em risco.
- Gatilhos: channel.updated (desligado), channel.inactivity_warning, restrito, motivo_restricao='payment_method', HND em baixo.
- Idempotente por (tenant, gatilho, episódio); ≤ 1 aviso/gatilho/24 h e ≤ 3/dia; lembretes às 24 h e 72 h.
- Nunca pelo WhatsApp, nem pelo número da loja, nem por um número operacional da KAMBÁ (D10): não o assumas.
- Sem dados de clientes no aviso. SMS só via SmsProvider de KAM-116, desligado até existir contrato.
Não expandas escopo: sem SMS, sem régua de cobrança (KAM-058), sem runbooks (KAM-083).
Testes: idempotência, limites, bounce, isolamento, X-11. Abre PR com o template do §7.
```

---

### Verificação dos Critérios de Aceitação

**Entregue em `feature/KAM-115-aviso-ao-dono`:** a revisão `0019` (descende da
`0018`) — **duas** tabelas — e o módulo `packages/core-ts/src/avisos/`, que é
quem entrega o aviso. Desenho em
[`../docs/avisos-ao-dono.md`](../docs/avisos-ao-dono.md).

**Este é o último ticket do epic, e fecha a lacuna R16.** Os emissores existiam
desde o KAM-017, o KAM-021 e o KAM-023; o que não existia era quem entrega.

**São duas tabelas e não uma, e quem o decide é o critério 7.** Ele manda que uma
falha de entrega «marque o **contacto** como inválido»: isso é um facto do
contacto e não do aviso, e com uma tabela só a pergunta «este dono tem contacto
válido?» passava a ser uma consulta sobre o histórico de envios em vez de um
facto.

| # | Critério | Estado | Evidência |
|---|---|---|---|
| 1 | Cinco gatilhos geram aviso, cada um com texto próprio e o passo seguinte; um gatilho fora da lista não envia nada | **satisfeito** | Os cinco estão no `GATILHOS` e no `owner_notices_gatilho_ck`, e **há um teste que compara os dois** contra o `pg_get_constraintdef` (`db/tests/test_avisos_schema.py`, «o dominio do gatilho e o do contrato em typescript») — a lição que a `0008` e a `0009` pagaram. «**os cinco gatilhos geram aviso, cada um com o seu texto e o seu passo**» verifica cinco assuntos **diferentes**, e «**todos os modelos dizem o passo seguinte**» que o corpo leva o passo dentro: um aviso que diz que algo está mal e não diz o que fazer é um aviso que o dono não pode usar. A recusa é literal nos dois lados: «**um gatilho fora da lista não envia nada**» mede 0 linhas e 0 entregas, e na base o `CHECK` recusa com `23514`. **Os seis motivos de `PARTNER_REMOVED` são um gatilho só**, e é decisão escrita: o critério pede que os seis *gerem* aviso, não que gerem seis textos — o passo é o mesmo nos seis, e seis modelos iguais eram seis sítios para a mesma frase divergir. O motivo vive no `episodio`, e «**os seis motivos de PARTNER_REMOVED são um gatilho só, e episódios diferentes**» prova que os seis dão **seis chaves**. O `painel_indisponivel` é ***proposta***, como o critério o marca |
| 1b | …e os cinco nomes passam a gramática do registo | **satisfeito, e mediu-se em vez de se prometer** | «**os cinco gatilhos passam a gramática do `outcome`**». Estes valores são também `outcome` de linha de registo, e o `IDENTIFICADOR` do `logger/politica.ts` só aceita minúsculas sem acentos — **em modo estrito, que é o do CI, o `Logger` levanta**, e um aviso perfeitamente normal passava a excepção não tratada no caminho de um *webhook*. É a mesma classe de defeito que o `sem_humano_24h` do KAM-018 pagou e que a `0018` repetiu para os motivos de desligamento; aqui o que isso proíbe é um `painel_indisponível` com acento |
| 2 | Idempotência por `hash(tenant_id, gatilho, episódio)`: o mesmo evento 3× (e re-entregue pela DLQ) produz 1 aviso; um novo episódio depois de resolvido produz outro | **satisfeito, e é da base** | «**o mesmo evento 3× produz 1 aviso por canal**»: três chamadas, **duas** linhas (uma por canal) e **uma** entrega em cada notificador. Quem decide é a `owner_notices_idempotencia_uq` com `ON CONFLICT DO NOTHING`, e isso só se prova com **duas** ligações: `tests_bd/avisos.bd.test.ts`, «**duas transacções concorrentes com a mesma chave deixam uma linha**» — `primeira + segunda === 1`. Com a decisão no código, duas transacções liam «ainda não avisei» as duas e o dono levava dois. A segunda metade é o `episodio`: «**um episódio novo depois de resolvido produz outro aviso**» e, na base, «o mesmo episodio em dois tenants da duas linhas» — a chave leva o `tenant_id` **dentro** do resumo (sem ele, dois *tenants* com a mesma `event_key` da Meta partilhavam-na e o segundo nunca era avisado) **e** ao lado, na restrição, porque a primeira protege de uma colisão e a segunda dá uma mensagem de erro em vez de um aviso perdido |
| 2b | …e a re-entrega pela DLQ não gasta o tecto | **satisfeito, e a ordem das recusas é que o dá** | «**a re-entrega pela DLQ não gasta o tecto diário**». O `ja_avisado` avalia-se **antes** dos limites, e não é detalhe: com os limites primeiro, três entregas do mesmo evento consumiam o tecto diário do dono e os outros gatilhos calavam-se — um dono com o canal desligado **e** o pagamento em falta sabia do primeiro três vezes e do segundo nunca |
| 3 | Latência do evento ao aviso entregue ao fornecedor ≤ 5 min p95 (*proposta*), medida com relógio acelerado e fornecedor falso | **satisfeito como o critério o escreve** | O critério manda medir «com relógio acelerado e fornecedor falso», e é o que se faz: **nenhuma função do módulo chama `Date.now()`** — o relógio é porta —, e os notificadores são portas com duas implementações de ensaio. «**mede-se com o relógio na mão, e entra no histograma**»: evento a `T0 − 90 s`, dois canais, `owner_notice_latency_s_count = 2` e `_sum = 180`. O corte de **300 s** está nos baldes por causa deste critério — «**o corte dos 300 s existe para o p95 se ler sem interpolar**» —, e uma latência negativa não entra, porque um `NaN` no formato de exposição faz o Prometheus descartar a recolha **toda**. **O p95 contra tráfego real é do Piloto**: o que a máquina pode afirmar é que o caminho é síncrono dentro da transacção de quem chama, pelo que a latência é a do fornecedor e não a de uma fila nossa |
| 4 | Limites (*propostas*): ≤ 1 aviso por (tenant, gatilho) em 24 h e ≤ 3 por tenant/dia; lembretes às 24 h e 72 h se o estado persiste, depois pára e abre tarefa a T2; 500 eventos/hora de um só tenant enviam ≤ 3 | **satisfeito** | As quatro metades. «**≤ 1 aviso por (tenant, gatilho) em 24 h**» nos dois lados da fronteira (`JANELA − 1` recusa, `JANELA` passa); «**≤ 3 avisos por tenant por dia**», com o dia **corrido e não civil** — «**o dia é corrido e não civil**», porque um dia civil fazia o tecto reiniciar à meia-noite e um dono avisado três vezes às 23 h levava outros três uma hora depois; «**os lembretes são às 24 h e às 72 h, e depois param**», e o «depois pára» está no `owner_notices_lembrete_ck` **na base** — «**o quarto lembrete é recusado pelo servidor, e não por um `if`**», com `23514` —, porque a regra de parar é a parte do limite que protege o dono de nós; e os 500: «**500 eventos numa hora de um só tenant enviam ≤ 3 avisos**», com a contagem de avisos **distintos** e com a asserção de que as supressões se contaram (mais de 400), sem a qual o teste provava que nada aconteceu |
| 4b | …e a ordem dos dois limites, que foi medida | **satisfeito, e é um achado da revisão adversarial** | «**a janela do gatilho vem antes do tecto diário, e a ordem é medida**». Com o tecto primeiro, um *tenant* com três episódios do mesmo gatilho gastava o dia todo num gatilho só e os outros quatro ficavam sem voz para as 24 h seguintes; com a janela primeiro, o segundo episódio do mesmo gatilho é recusado **sem gastar nada do tecto**. É a diferença entre um dono que sabe que tem três problemas e um dono que sabe três vezes o mesmo. E «**o tecto conta avisos e não linhas**»: um aviso sai pelos dois canais e é **um** aviso — contar duas linhas fazia o tecto de três valer um e meio |
| 4c | …e os lembretes, que a primeira versão nunca enviava | **satisfeito depois de a revisão adversarial o apanhar** | «**um lembrete não é recusado pela janela do gatilho**». Um lembrete é, por definição, um segundo aviso do mesmo gatilho dentro das 24 h — e a primeira versão filtrava os dois, pelo que **os lembretes nunca saíam**. O teste que afirmava o contrário media o lembrete das 24 h num **histórico vazio**, onde a janela não tem nada para recusar: passava pela razão errada. A correcção é o `lembrete === 0` no predicado da janela, e o teste afirma agora as duas coisas no mesmo instante — o lembrete passa e o aviso próprio é recusado por `ja_avisado`. Há uma mutação que troca o predicado por `true` |
| 5 | Conteúdo por *allowlist* de modelos (1 por gatilho): nome da loja, estado, hora, passos e ligação ao painel sem *token* nem identificador pessoal no URL; 0 telefones, `contact_id`, BSUID ou texto de clientes (varrimento X-11 sobre 200 avisos gerados) | **satisfeito** | A lista é fechada e aplica-se na **construção**: «**um parâmetro fora da lista levanta**» e «**a recusa é antes de preencher, e não dentro**» — com a recusa só dentro do `preencher`, um parâmetro a mais que nenhum modelo usasse passava sem ser visto, e o que entrava sem ser visto era o que o critério proíbe. O varrimento é o do critério: «**o varrimento de 200 avisos não encontra nada do que o critério proíbe**» gera 200 avisos variando gatilho, estado, hora e nome de loja — com telefones, NIF e IBAN escritos de todas as maneiras em que uma pessoa os escreve — e afirma **0** corridas de sete ou mais dígitos, **0** UUID, **0** BSUID e **0** marcadores por preencher. A ligação ao painel recusa a **forma** e não uma lista de parâmetros proibidos: «**a ligação ao painel não leva token nem identificador**» recusa `?`, `#`, `=` e `http`. E o `{estado}` vem de uma lista fechada, porque um parâmetro de texto livre era por onde a PII entrava |
| 5b | …e o nome da loja, que é o único texto livre | **satisfeito, e mascara-se em vez de recusar** | «**o nome da loja mascara telefones em vez de recusar o aviso**». O `loja` é o que o dono escreveu, e «Loja do Zé 923 456 789» é um nome plausível em Luanda. Recusar o aviso fazia o dono não saber que o canal caiu por causa de **como ele escreveu o nome da loja**, que é castigá-lo por um defeito nosso. A fronteira é o `DIGITOS_MAXIMOS` do `logger/politica.ts` — **seis** —, **reexportado e não redeclarado** («**a fronteira é o `DIGITOS_MAXIMOS` da casa e não um número novo**»), pela razão que o `MPS_POR_MODO` do KAM-017 escreveu. E a régua apanha as corridas **separadas por espaços, pontos, hífenes e barras**: procurar só a corrida contígua deixava passar exactamente o caso comum |
| 6 | O dono tem ≥ 1 contacto alternativo verificado por ligação de confirmação; *tenant* `ativo` sem contacto verificado gera alerta a T2 e a métrica `owner_alt_contact_missing`; alvo ≥ 95% dos *tenants* `ativo` com contacto verificado (*proposta*) | **parcial — caixa vazia** | **As duas primeiras metades estão satisfeitas.** A ligação de confirmação é emitida, guardada em resumo (`sha256`, nunca o *token*), tem prazo e confirma **uma vez**: «**a ligação de confirmação vale sete dias e confirma uma vez**», «um token errado não confirma», «uma ligação expirada não confirma», e contra a base «**duas confirmações simultâneas do mesmo *token* dão uma**» — a comparação e o prazo estão **na instrução**, pelo que com a leitura e a escrita separadas no código passavam as duas. Um contacto não verificado **não recebe avisos** (`contactoUtilizavel` exige verificado **e** não inválido). O alerta e a métrica estão: «**um *tenant* sem contacto verificado abre tarefa a T2 e conta**», e «**a varredura publica o numerador e o denominador**» — os dois, porque uma percentagem precisa de denominador e «doze *tenants* sem contacto» não se distingue de catástrofe nem de ruído sem ele. **O que não se cumpre é o alvo**: «≥ 95% dos *tenants* `ativo`» é uma medição sobre *tenants* reais, e não há nenhum — afirmar a percentagem contra dois *tenants* de ensaio era afirmar 100% de nada. O número sai no Piloto, e a caixa fica vazia. **E a captação do e-mail é do KAM-086**, como o próprio critério diz: este ticket emite, guarda, confirma e usa |
| 7 | Falha de entrega (*bounce*, rejeição) marca o contacto como inválido, tenta o painel e abre tarefa a T2; nenhum aviso se perde em silêncio (falha injectada) | **satisfeito** | As três metades, com falha injectada. «**um *bounce* marca o contacto como inválido e abre tarefa a T2**», e na base «**o *bounce* invalida o contacto pelo caminho do módulo**» confirma a coluna. «**e o painel entrega, que é o «tenta o painel» do critério**»: o aviso sai pelos **dois** canais sempre, pelo que quando o e-mail falha a notificação do painel já saiu — o «tenta o painel» não precisa de um segundo caminho. E «nenhum aviso se perde em silêncio: a falha fica registada na linha» (`estado = 'falhado'`, `falha_motivo`, `tentativas = 1`), com as duas séries de métrica que distinguem **nós recusámos** de **o fornecedor não entregou**: sem elas, um painel vê «o dono não foi avisado» e não distingue a regra a funcionar do canal alternativo estar quebrado |
| 7b | …e o que **não** condena o endereço | **satisfeito, e o domínio da base é que o impõe** | «**um fornecedor em baixo não condena o endereço**»: `indisponivel` não diz nada sobre o endereço, e marcar o contacto por uma avaria **nossa** era deixar o dono sem canal alternativo. O `sem_contacto` também não, porque não há nada a condenar — «**o `sem_contacto` não marca o contacto como inválido**», e um `sem_contacto` tratado como `bounce` marcava como inválido um endereço que não existe. Os dois lados: o `MOTIVOS_DE_INVALIDEZ` tem **dois** valores dos quatro, e o `owner_contacts_motivo_ck` recusa os outros dois com `23514`. E «**um contacto inválido faz o aviso seguinte falhar com `sem_contacto`**» e não com `bounce`: um `bounce` ali era dizer que o fornecedor recusou uma mensagem que nunca lhe foi entregue |
| 8 | Nenhum adaptador de envio WhatsApp neste módulo (teste de configuração); o fornecedor de e-mail consta do inventário de subprocessadores (KAM-069) com `apd_ref`, ou fica `pendente` e bloqueia `prod` (ADR-008) | **satisfeito** | A primeira metade é um **teste e não uma promessa**: «**nenhum `import` do módulo vem do `outbound` nem do `entrada`**» lê o texto dos ficheiros do directório — porque é o texto que o compilador lê — e recusa qualquer `import` de onde vive o cliente da Meta, e mede também a ausência da palavra `wamid`, que é o que um adaptador dela precisaria. Os `CANAIS` são dois e o `whatsapp` não é um deles, nem no `CHECK` da base («**o WhatsApp não é um canal de aviso**», `23514`); e o `sms` **não está pré-declarado**, porque é o KAM-116 e um nome sem superfície é o que o *gate* 3b recusa. A segunda metade é a alternativa que o próprio critério escreve: o inventário de subprocessadores **não existe** (nasce com o KAM-069), e o `fornecedor.ts` entrega o *gate* — «**em `prod`, sem `apd_ref`, o serviço não arranca**», com a forma do `storage/config.ts` do KAM-011 e os nomes de `tenant_destinations(provider, country, apd_ref)` do `../docs/tecnica/08` §8.3.1, para que o KAM-069 confronte um vocabulário só. **Qual é o fornecedor não se decide aqui**, e não é omissão: escolher um subprocessador num ficheiro de código é exactamente o que o ADR-008 existe para impedir — o valor por omissão é `pendente`, e `pendente` em `prod` é um arranque recusado |
| 8b | …e o caso de fronteira do *gate* | **satisfeito, e é o que uma mutação prende** | «**mas `pendente` em Angola bloqueia, porque `pendente` não é um sítio**». O `country` por omissão é `AO`, pelo que um predicado só sobre o país deixava passar um ambiente sem nada declarado — que não tem fornecedor nenhum. E o inverso também se afirma: «**um fornecedor escolhido em Angola não precisa de `apd_ref`**», porque o *gate* existe por causa da **transferência** e não por cerimónia |

#### O isolamento, a privacidade e as migrações

| DoD | Estado | Evidência |
|---|---|---|
| **Isolamento de tenant** — RLS em `owner_notices` e teste cruzado | **marcada** | RLS `FORCE` e política `tenant_iso` nas **duas** tabelas, pelo `rls.enable_tenant_rls`. O *gate* 6 descobre-as pela coluna `tenant_id` e corre o X-03/X-04 sobre elas — a receita de sementes é nova em `db/tests_isolamento/sementes.py`, e as **quatro** listas de `test_x05_catalogo.py` precisaram delas (a quarta falhou depois de as três primeiras passarem, exactamente como o KAM-017 avisou). Pelo caminho do módulo: «com o contexto de A, o aviso de B não se lê», «…não se muda» e «…o contacto de B não se lê nem se invalida» — zero linhas e `rowCount = 0`, que é a política como condição e não como excepção |
| **Idempotência** — chave por episódio com teste de repetição | **marcada** | Ver os critérios 2 e 2b. A chave é `sha256(domínio ␀ tenant ␀ gatilho ␀ episódio)` e o separador é o **octeto nulo** — «**o separador é o octeto nulo, e não um ponto**» —, pela razão que o `prova.ts` do KAM-022 escreveu: com um separador que possa aparecer nos campos, dois episódios diferentes davam a mesma cadeia. O `episodio` **não pode ser vazio**, e o `CHECK` está lá por isso: um `episodio` vazio punha todos os avisos do mesmo gatilho na mesma chave e o segundo episódio de um *tenant* nunca mais era avisado — o defeito mais silencioso possível neste módulo |
| **Privacidade** — avisos sem dados de clientes; endereço do dono só em cifra e nunca em logs | **marcada** | Três provas de três tipos. **Do esquema:** `db/tests/test_avisos_schema.py`, «**não há coluna em claro para o endereço**» — das colunas de `owner_contacts`, as de texto são **duas** e as duas têm domínio fechado; um teste do lado do código prova o que o código faz hoje, este prova que não há onde escrever um e-mail em claro. **Da base real:** `tests_bd/avisos.bd.test.ts`, «**o endereço nunca é escrito em claro em nenhuma coluna**» varre a tabela à procura do endereço que o módulo acabou de usar. **Do conteúdo:** o varrimento de 200 avisos do critério 5. E `owner_notices` **não tem coluna de corpo**, que é o que os *Detalhes Técnicos* pedem — o mesmo argumento que a `0018` escreveu: uma regra que depende de ninguém escrever num sítio onde dá para escrever não é uma regra |
| **Custo e observabilidade** — as três métricas do DoD | **marcada, e são cinco** | As três do DoD mais duas, e as duas entram pela razão da emenda 1.21: **recusar sem contar é recusar em silêncio**. Aqui isso é mais do que um princípio — há duas maneiras **opostas** de um aviso não chegar ao dono, e sem as duas séries um painel não distingue a regra a funcionar do canal quebrado. É a **primeira métrica desta casa com duas etiquetas**, e nenhuma é identificador: cinco gatilhos × dois canais são dez séries fixas, e o OBS-I recusa identificadores e não dimensões pequenas. «**um `tenant_id` numa etiqueta levanta**» mede-o, e «**uma etiqueta a menos levanta**» impede que `{gatilho}` conviva com `{gatilho,canal}` na mesma recolha — o Prometheus trata-as como séries diferentes e a soma deixa de ser o número de avisos |
| **Migrações reversíveis** — `downgrade` testado | **marcada** | `TestDowngradeDa0019`: desce com linhas, não recusa, e sobe outra vez — com as tabelas comparadas contra `TABELAS_ATE_0018` e `TABELAS`, e com a RLS e o `FORCE` conferidos **depois** de subir, porque um `downgrade` que deixasse a tabela sem política ao subir era pior do que não descer. O que se perde está dito na própria revisão: não é prova jurídica como o consentimento da `0015` — é a **idempotência**, porque descer e subir faz o episódio em curso poder ser avisado outra vez |
| **Todos os CA satisfeitos** | **por marcar** | Sete de oito. O critério 6 fica parcial pelo alvo de ≥ 95%, que é medição sobre *tenants* reais |
| **≥ 1 revisor** | **por marcar** | Não houve revisor humano. A revisão adversarial foi feita e está abaixo |

#### Os quatro defeitos que uma máquina apanhou, e o quarto é um gate que eu não corri

1. **O relógio, e foi o ensaio contra a base.** A varredura dos lembretes não
   encontrava episódio nenhum: as linhas tinham `criado_at` do servidor e a
   janela tinha a hora acelerada do ensaio. A correcção é o `criado_at` vir do
   relógio de quem chama, e é de **desenho** e não de teste — em produção os dois
   relógios coincidem, pelo que isto nunca apareceria antes do Piloto. É a mesma
   razão pela qual o `prazo_em` da `0018` é coluna e não cálculo.
2. **O `after` do ensaio, e pendurou o processo.** O `apagarTenant` do
   `tests_bd/apoio.ts` não conhecia as duas tabelas novas, pelo que o `DELETE` do
   *tenant* rebentava com `23503` **depois** de os testes passarem — e o `after`
   que fecha as ligações nunca chegava ao fim, pelo que o `node --test` não
   acabava. Trezentos segundos de silêncio, sem uma linha de saída. O lançador
   desta *suite* passou a devolver a saída parcial quando o tempo estoura, porque
   um ensaio pendurado sem saída não se investiga. A nota do KAM-016 já previa a
   oitava tabela; esta é a nona e a décima.
3. **Quatro testes meus a passar pela razão errada, e foi a prova por mutação.**
   Cada caso negativo precisa do seu `SAVEPOINT`: um erro aborta a transacção
   inteira no PostgreSQL, pelo que a segunda assercão negativa do mesmo teste
   respondia `25P02` («in_failed_sql_transaction») e não o `23514` que se
   esperava. O `ComBase.assertErroSql` já existia e faz exactamente isto — e a
   mesma corrida mostrou que um cursor do `pg8000` **não é gestor de contexto**,
   o que fazia o teste do `downgrade` levantar `TypeError` antes de afirmar o que
   fosse. **A bateria de esquema nunca tinha corrido**: o *gate* 8 correu antes
   de ela existir, e a prova por mutação foi a primeira coisa a executá-la. A
   lição não é sobre `SAVEPOINT` — é que uma bateria nova tem de correr no seu
   *gate* **depois** de ser escrita, e não antes.
4. **O CI apanhou o *gate* 7, que eu não corri.** O `varrer` do KAM-024 conta
   números de **forma** real em todo o repositório e exige que cada ficheiro que
   os tenha esteja no inventário de `../tools/meta-sim/src/inventario.ts`, com a
   contagem e a razão. Os nomes de loja do varrimento de 200 avisos do critério 5
   têm dois — «Loja do Zé 923456789» e «Mercearia 923 456 789» —, e **têm de os
   ter**: sem números de forma real, o teste provava que a máscara apanha números
   que não se parecem com telefones, que é o contrário do que ela existe para
   fazer. Declarou-se, e **não se mudou o valor**: é a mesma escolha que o
   `ci/secrets-allow.yaml` impõe pelo outro lado — a lista não se alarga, e aqui o
   inventário é desenhado para ser alargado **com a razão escrita**, que é o que o
   distingue de uma pasta isenta. O total do inventário sobe de 86 para 88 e as
   entradas de 22 para 23, e há um teste que afirma os dois números — o que obriga
   quem acrescentar um ficheiro a dizê-lo num sítio só. **A lição é a do KAM-022,
   repetida:** corri as duas primeiras verificações do *gate* 7 (o
   `contract_diff`) e não a terceira, o `ci-7-meta`. Correr a função de um gate
   não é correr o gate.

#### A revisão adversarial

**Dois achados, e os dois mudaram o código.**

1. **Os lembretes nunca saíam.** A janela de 24 h por gatilho filtrava **todos**
   os avisos desse gatilho, e um lembrete é por definição um segundo aviso do
   mesmo gatilho dentro da janela. O critério 4 manda enviá-lo, e a regra
   recusava-o. O teste que afirmava o contrário media o lembrete das 24 h num
   histórico **vazio**: passava, e não provava nada. Ver o critério 4c.
2. **O tecto diário contava linhas.** Um aviso sai pelos dois canais e escreve
   duas linhas; com a contagem por linha, o tecto de três valia um e meio e um
   dono com três problemas sabia de um. Passou a contar `(gatilho, episodio,
   lembrete)` distintos, e há teste com quatro linhas e dois avisos.

#### A prova por mutação: oito sobreviventes, e os oito eram lacunas minhas

Corrida sobre as 79 mutações deste ticket, com o código já congelado. **Oito
sobreviveram**, e nenhuma era um falso positivo: cada uma mostrou um teste que
passava pela razão errada. É a razão por que ela existe, e vale a pena o
inventário.

1. **A janela do gatilho a morder nos lembretes** — a mutação mais importante
   das oito, porque o predicado que ela apaga é a **correcção da revisão
   adversarial**. O teste que o afirmava media o lembrete das 24 h com o aviso
   próprio em `T0`, e aí a janela **já tinha expirado** — ela é `[T0, T0+24h)`.
   Passava com o predicado e sem ele. O cenário em que a janela morderia precisa
   de um **vizinho**: o episódio A avisado em `T0`, o lembrete 1 dele em
   `T0+24h`, um episódio **novo** do mesmo gatilho avisado em `T0+50h` e o
   lembrete 2 de A em `T0+72h` — a linha de `T0+50h` está a 22 h, dentro da
   janela. O teste novo tem esse cenário **e** o controlo que prova que a janela
   existe.
2. **A janela a passar de 24 h para 1 h** — os testes da fronteira usavam a
   própria constante nas duas pontas, pelo que eram verdadeiros para **qualquer**
   valor dela. Um número de produto afirma-se pelo número, como o
   `ATRASO_DO_LEMBRETE_MS` já fazia; os seis passaram a ser afirmados assim.
3. **O separador da chave a passar de octeto nulo para ponto** — a colisão que o
   teste construía (`(inactividade, "a")` contra `(inactivid, "adea")`) dá cadeias
   diferentes com **qualquer** separador. A colisão real é o deslocamento de uma
   fronteira: com um ponto, `(a, "b.c")` e `(a.b, "c")` dão a mesma cadeia. O
   teste novo tem essa, e a versão com dois-pontos — que é o separador que um
   `episodio` real traz.
4. **O marcador sem valor a deixar de levantar** — e aqui a resposta não foi um
   teste: a guarda era **inalcançável**. O `Parametros` é um `Record` total dos
   quatro nomes, pelo que o `valor === undefined` nunca podia ser verdade.
   Apagou-se, com a mutação, e é a resposta que o KAM-018 deu às duas guardas do
   `transicoes.ts` dele — «uma guarda inalcançável dá a ilusão de proteger». O
   invariante que ela pretendia proteger tem agora teste próprio, sobre os
   **cinco modelos** em vez de sobre a chamada que alguém exercitasse:
   `marcadoresDosModelos()` ⊆ `PARAMETROS`.
5. **A linha deduplicada a ser entregue outra vez** — e esta é a mais
   interessante das oito, porque o caminho que ela apaga era **inalcançável pelos
   testes mas não pelo código**. Em série, o `decidir` recusa primeiro, com
   `ja_avisado`, e o registo nem é chamado: o `registado === null` só acontece
   quando **duas transacções** lêem «ainda não avisei» as duas e a unicidade deixa
   passar uma. A base falsa ganhou um modo de conflito que reproduz exactamente
   isso — histórico vazio e `INSERT` sem linhas —, e o teste afirma que nada se
   entrega e que **não** se abre tarefa a T2: não houve falha, houve outra
   transacção a fazer o trabalho.
6. **A hora a voltar à forma curta** — e esta mostrou que a razão que eu tinha
   escrito era **falsa**. A nota dizia que a forma curta dá `09/11/2026`, oito
   dígitos que a régua apanharia; mediram-se as três formas e é a **média** que
   os traz (`short` dá `09/11/26`, seis). Agora são duas mutações, e cada uma
   morre por um teste diferente: a `medium` pelo varrimento do critério 5 e a
   `short` pela legibilidade — o mês por extenso e o ano inteiro, porque num
   aviso que o dono pode ler dias depois a data tem de ser inequívoca.
7. **A confirmação a deixar de conferir o prazo** — o teste da expiração vivia só
   na bateria do *gate* 4, contra a base falsa, e ela implementa o seu **próprio**
   predicado de prazo. Uma mutação ao `SQL_CONFIRMAR` passava. O ensaio contra a
   base ganhou-o, com o prazo avaliado pelo servidor e com a asserção de que um
   prazo que passou **não consome** a ligação — só a recusa.
8. **A varredura a contar os contactos não verificados** — o teste afirmava que
   os dois *tenants* do ensaio **não** aparecem na lista, e isso continuava
   verdade com o predicado mutado, porque eles têm contacto. O que prende os dois
   ramos é um *tenant* `ativo` cujo contacto existe e **não serve**: o ensaio novo
   percorre os três estados — não verificado (aparece), verificado (sai),
   verificado e inválido (volta a aparecer) —, e o terceiro é o critério 7 a
   deixar o dono sem canal, que é precisamente o que a métrica do critério 6 tem
   de ver.

**E três sobreviventes que não são deste ticket.** O filtro largo que corri
(`aviso`) apanhou também três mutações do KAM-017, porque o nome delas tem a
palavra: «o aviso deixa de ser idempotente», «o aviso passa a apanhar canais a
sincronizar» e «o aviso de desalinhamento volta a disparar em `cloud_only`». São
do aviso de inactividade **daquele** ticket, correm na `tests_outbound`, e **não
se tocou** — mexer no código de outro ticket a meio deste é o que a nota do
KAM-023 sobre o `MED_SQL` desaconselha. Ficam aqui nomeadas para que não se
perca: quem fechar o KAM-017 à letra tem três lacunas medidas por onde começar.

**Setenta e nove** mutações novas — **dez** da revisão `0019` e **sessenta e
nove** do código, cinco delas a prender os achados desta revisão —, e a cobertura
de `src/avisos/` mede-se na *suite* própria (`db/tests_avisos/`), ficheiro a
ficheiro, contra o limiar do estrato `critico` lido de `ci/thresholds.yaml`: está
entre **98%** e **100%** em cada um dos oito, contra os 90% exigidos.

**A prova por mutação completa corre de noite** (KAM-143), e o que o PR corre é o
`--aplicaveis` — que confere que cada mutação ainda **encontra o seu texto**, e
que é o que torna verdadeira a frase «no PR corre o que é novo». As 689 estão
aplicáveis. **As 79 deste ticket corremos-as**, e o que elas encontraram está na
secção acima: oito sobreviventes, oito lacunas, zero falsos positivos.

E vale a pena dizer o que a corrida **parcial** do desenvolvimento custou: três
horas de máquina para descobrir que uma bateria nova nunca tinha corrido, o que
um `--suite tests` de dois minutos teria dito.

---

## Riscos do Epic e itens NÃO VERIFICADOS

| # | Risco / item | Estado | Decisão ligada | Mitigação / critério de saída |
|---|---|---|---|---|
| R1 | Coexistência indisponível ou instável para números +244 (móveis e fixos) | NÃO VERIFICADO (L1; E1 §2) | D5; KAM-100; H3 | KAM-017 só fixa o modo predefinido depois do relatório de KAM-100; alternativa `cloud_only` com número novo |
| R2 | Timeout exacto do webhook, *retry* antes das 7 dias e *pair rate limit* | NÃO VERIFICADO (L2; E1 §5) | KAM-101 | Alvo interno 200 em < 500 ms; parâmetros configuráveis; pergunta 12 de E1 à Meta |
| R3 | Aceitação de documentos angolanos na Business Verification, prazo e «Access Verification» | NÃO VERIFICADO (L3) | D5; KAM-102 | KAM-016 depende de `ext:KAM-102`; plano B BSP com cotação a 2 BSPs |
| R4 | Método de pagamento local (Kz) no Billing Hub; PMEs sem cartão USD/EUR | NÃO VERIFICADO (L4) | D5, D9 | Gate de activação (KAM-093); alerta aos 800 (KAM-023); Multi-Partner Solution como alternativa |
| R5 | Classificação «AI Provider» e agregador permitido | NÃO VERIFICADO (L5) | D2; ADR-011 | Fluxo B diferido (guarda no CHR, KAM-014); persona limitada a comércio; pergunta 2 de E1 |
| R6 | *Echo* de mensagens enviadas por API e sua latência | NÃO VERIFICADO (L6) | KAM-100 | Comparação com `outbound_messages.wamid`; evidência de ≥ 30 *echoes* reais (KAM-018) |
| R7 | O token do *agent bot* do Chatwoot consegue passar `pending → open`; versão de ES do Chatwoot | NÃO VERIFICADO (L7) | ADR-001 (Desenho I) | Spike de 1 dia em KAM-019; plano B com utilizador-serviço; Desenho I não usa o ES do Chatwoot |
| R8 | Verificação por SMS (Unitel/Africell) e fixos por voz | NÃO VERIFICADO (L10) | KAM-093 | Fluxo de voz no pré-voo; medir na Fase 1 |
| R9 | Fuso do *free tier*, marcação dos primeiros 1.000 nos estados e código de erro da falta de pagamento | NÃO VERIFICADO | KAM-101 | Contador próprio + reconciliação mensal (KAM-023); acrescentar a pergunta ao pacote de KAM-101 |
| R10 | Base legal do consentimento (contrato vs consentimento), do aviso e do uso do histórico sincronizado; papel da KAMBÁ | A confirmar por parecer (E3) | D9; KAM-104 | Texto versionado e prova; histórico não persistido no Piloto (KAM-017) |
| R11 | Termos da Meta §4.7 sobre ML e dados da plataforma (leitura automática do texto PT) | CONFIRMADO com ressalva (L15) | ADR-018 | Nada de treino com conversas; confirmar texto EN antes de uso contratual |
| R12 | Alojamento de conversas, Chatwoot e mídia sem procedimento APD; CDN/WAF e TLS como subprocessadores | Decisão aberta | D1, D12; ADR-008 | Dados sintéticos fora de `prod`; gate de transferência em KAM-069; nenhum dado real antes de D1 |
| R13 | Limite de 10 clientes/7 dias até verificação completa | CONFIRMADO | D5 | Contador `es_onboardings_7d` (KAM-016); lista de espera (KAM-095) |
| R14 | Divergências documentais: RED → `suspenso` (`../docs/tecnica/10` §6.4) vs `restrito` (doc 00, doc 01); três tabelas de consentimento; `contact_id` como `bytea` em `consent_event` | Conflito documental | ADR-010 | Decisões em KAM-021 e KAM-022; propagar a `../docs/tecnica/10`, `01` e `06` |
| R15 | Dependências em falta no backlog mestre: KAM-016 sem KAM-010; KAM-014 sem KAM-004 nem KAM-006; KAM-018, KAM-021 e KAM-022 sem dependentes | Defeito do backlog | — | Sinalizado ao responsável de produto; entretanto usar `SecretProvider` de ambiente e TTL de cache |
| R16 | Sem ticket para avisar o dono por canal alternativo (e-mail/push) em `PARTNER_REMOVED`, inactividade ou falha de pagamento Meta | **FECHADA** pelo KAM-115 | — | Entregue: a revisão `0019` (duas tabelas) e o módulo `packages/core-ts/src/avisos/`, com cinco gatilhos, idempotência por episódio, limites de frequência, lembretes e o *gate* de `prod` do subprocessador. Sete de oito critérios satisfeitos; o oitavo — o alvo de ≥ 95% dos *tenants* com contacto verificado — é medição sobre *tenants* reais e sai no Piloto |

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
| 1.0 | Outubro 2026 | Emissão inicial: KAM-013 a KAM-024 (GWY, CHR, outbound, Embedded Signup v4, coexistência, handoff, mídia, qualidade, consentimento, simulador); KAM-115 (aviso ao dono por canal alternativo) acrescentado na consolidação. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-145: os **24** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | **KAM-014 entregue.** Secção de verificação no bloco, com onze caixas marcadas e **cinco vazias**: três critérios que não se cumprem à letra — o caminho do contrato `agent_invocation`, que uma sentinela do *gate* 3b não deixa existir; a convergência de identidade sem uma mensagem que traga os dois identificadores, que o algoritmo de `../docs/tecnica/01` §6.3 não faz; e o «uma vez por contacto/24 h» da mensagem estática, que é de quem envia — e as duas do DoD que delas dependem. As quatro divergências documentais que sustentam essas leituras estão em `../docs/dividas-documentais.md`, linhas 47 a 50. A revisão adversarial está em `../docs/analises/ANALISE-27-KAM-014-chr-channelresolver.md`. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | **A aresta KAM-024 → KAM-015, KAM-016, KAM-017 e KAM-020**, que o critério 5 do KAM-024 afirma e o grafo não declarava, nas três superfícies que o *gate* 3c compara. Sem ela, a ordem de execução do epic estava errada: o servidor Graph falso que os «Testes Requeridos» de quatro tickets nomeiam só nasce no KAM-024. | Equipa KAMBÁ |
| 1.4 | Outubro 2026 | **KAM-024 entregue.** Dez caixas marcadas com evidencia nomeada e seis vazias, na seccao «Verificação dos Critérios de Aceitação» do bloco. Tres das vazias nao sao satisfazeis por este ticket: o «usado por KAM-015, 016, 017 e 020» do critério 5 nao se pode medir antes de esses tickets existirem, e a *suite* online dos critérios 8 e 9 depende de `ext:KAM-102` e do número de teste da app Meta de *staging*. A quarta é o critério 7, que fica vazio por escolha: o *scan* mede 86 ocorrências de forma real no repositório, todas *fixtures* de redacção de PII, e a letra diz «0» — quem decide se o inventário basta é quem escreveu o critério. Acrescentada depois a secção «A revisão adversarial, e as quatro caixas que ela reprovou»: dezasseis achados, quatro graves, e o primeiro fazia o *gate* 7 falhar em **todos** os PRs sem nenhum dos 133 testes de então o apanhar — porque nenhum corria o comando que o `Makefile` corre. Depois das correcções as quatro caixas voltam a resistir, e a tabela de cobertura passa de 27 a **33** itens, com os seis motivos de `PARTNER_REMOVED` a contar como itens próprios. | Equipa KAMBÁ |
| 1.5 | Outubro 2026 | **KAM-015 entregue.** Secção de verificação no bloco, com **doze** caixas marcadas com evidência nomeada e **seis vazias**. Três das vazias são critérios que não se cumprem à letra, e as três estão em `../docs/dividas-documentais.md` (53 a 55): o critério 6 contradiz-se na própria aritmética («130429 3× seguida de 200» com «3 tentativas»), o critério 4 e o DoD de observabilidade pedem uma etiqueta `{tenant}` que as bibliotecas de métricas recusam por gramática, e o critério 8 pressupõe um *lock* de conversa que pertence ao KAM-018. As outras três são a fila e o aviso ao dono da segunda frase do critério 6 (KAM-115), o DoD «todos os CA satisfeitos» e os dois revisores. **Nove defeitos apanhados por máquina**, todos em coisas que eu tinha verificado à mão: o leitor de YAML, o *gate* 3b, o meu próprio teste do critério 5 (duas vezes), a *allowlist* do registo, o varredor de segredos, o `set_config` local à transacção, a `outbound_messages_entrega_ck` e o *token bucket* a enviar sem ficha. **E a revisão adversarial não aprovou a primeira versão**: nove achados, os nove corrigidos, com o custo a **duplicar sob concorrência** (o `delivered` e o `read` a chegarem juntos somavam 4 000 cada) e o teste que afirmava a propriedade a escolher o par que não podia apanhá-lo. | Equipa KAMBÁ |
| 1.6 | Outubro 2026 | **KAM-023 entregue, em duas metades.** Secção de verificação no bloco, com **onze** caixas marcadas e **cinco** vazias, cada uma com a razão escrita. A metade de código entrou sem DDL (contagem do *free tier*, alertas aos 800 e 1.000 por **flanco** e não por valor, custo estimado em micro-dólares inteiros, quatro métricas) e a revisão `0013` entrou quando a `0012` do KAM-020 fundiu — as revisões de base encaixam uma na anterior, e duas a reclamar o mesmo pai não são colisão mecânica. As cinco vazias: o fuso **por canal** que o esquema não tem (só há por *tenant*, e o fuso vive na `platform.ten_periodo` da `0007`), a etiqueta `{tenant}` que as bibliotecas de métricas recusam **por gramática** (mesmo precedente da emenda 1.21 do dicionário), o critério 7 que é de **saída** e pede um mês real de Piloto, a dos revisores (zero humanos, decisão do fundador) e a que depende das outras. Quatro dívidas novas (65 a 68), todas critérios que pedem o que o esquema não tem. **Esta linha fecha uma deriva:** o KAM-019 e o KAM-020 não acrescentaram a sua, pelo que a tabela saltou da 1.5 para aqui — fica registado em `../docs/dividas-documentais.md`. | Equipa KAMBÁ |
| 1.7 | Outubro 2026 | **KAM-021 entregue.** Secção de verificação no bloco, com **catorze** caixas marcadas e **três** vazias, cada uma com a razão escrita. Entrou a revisão `0014` (`channel_quality_log` com unicidade `(tenant_id, event_key)` e `tenant_channels.max_phone_numbers_per_business`) e o módulo `packages/core-ts/src/qualidade/`, que preenche o braço `gestao_de_canal` que o KAM-013 deixou a registar e mais nada. **A caixa do critério 3 fica vazia por segurança, e a decisão é do fundador:** ele quer que o `tenants.estado` projecte `restrito`, e a revisão `0007` retirou o `UPDATE (estado)` a `kamba_app` **de propósito** — «o sujeito da condição não pode ser quem a retira» —, com um teste a prendê-la; devolver o privilégio reabria a escalada que a revisão adversarial do KAM-009 fechou. As outras duas vazias são a dos revisores (zero humanos, decisão do fundador) e a que depende da primeira. Duas caixas entregam-se «pelo que o repositório tem» — o *ticket* de T&S dos critérios 4 e 8 não existe como mecanismo, e o que existe (contador e registo) é o que se usa, como o KAM-023 fez — e duas trazem divergências registadas: **dois critérios do mesmo bloco não dizem o mesmo** (o 2 nomeia só a `marketing` e a matriz do §3.7 recusa também a `utility`, e segue-se a matriz porque é o que o critério 9 pede), e o nome do escalão do critério 5 (`TIER_2000` contra o `TIER_2K` que o gerador do KAM-024 produz). Cinco dívidas novas (70 a 74). **A prova por mutação encontrou um teste em falta que nenhuma leitura viu:** apagar o `WHERE estado <> 'restrito'` do `SQL_RESTRINGIR` passava a prova inteira, porque no caminho sequencial o predicado é redundante — quem o torna necessário é a concorrência com chaves **diferentes**, e o teste da corrida que existia usava a mesma chave. **E o grupo do critério 9 passava pela razão errada:** o `tenants.estado` nasce `onboarding`, que é mais restritivo do que `restrito`, pelo que as três asserções de `STATE_REFUSED` teriam passado com o canal `ativo`. **A divergência que o DoD manda registar já estava fechada pelo KAM-111:** o `../docs/tecnica/10` §6.4 diz hoje «vermelho → `restrito`», e quem ainda diz `suspenso` é o `00` §6.2, que o `01` §9 já registra. | Equipa KAMBÁ |
| 1.8 | Outubro 2026 | **KAM-022 entregue.** Secção de verificação no bloco, com **quinze** caixas marcadas e **uma** vazia — a dos revisores, que neste ticket pede **dois** por serem dados pessoais e por isso fica vazia e não meia. Entrou a revisão `0015` (a `consent_event` *append-only*, a `consent_texts` **sem `tenant_id`** e **a primeira vista do esquema**, a `consent_actual`) e o módulo `packages/core-ts/src/consentimento/`, que é a barreira anterior ao AGR. **Três coisas que não são transcrição:** a decisão é **um valor** (`invocaAgr`) e o módulo nunca chama o AGR, porque a propriedade do critério 4 — «0 *jobs* sem consentimento válido anterior» — só é demonstrável se houver um sítio onde a medir; a idempotência do critério 2 sai do **próprio `evidence_hash`**, que leva o `wamid` e a hora **da Meta**, pelo que uma reentrega do mesmo *webhook* bate na unicidade (com a nossa hora, duas entregas davam duas linhas); e a contagem de avisos do critério 3 **não acrescentou DDL** — a chave `aviso:{conversation_id}:{n}` que impede o aviso de sair duas vezes é a que diz quantas vezes saiu. **A `consent_actual` é a primeira vista do esquema e leva `security_invoker = true`:** o `verificar_vistas` do catálogo do X-05 exige-o desde o KAM-004 e nunca tinha tido nada para ver — sem a opção, uma vista corre com os privilégios do dono e a RLS passa a depender do `FORCE`, numa relação onde ninguém iria procurar. Ela sacudiu **quatro** sítios que diziam «tabelas» e mediam relações, todos listados na secção. **A `consent_texts` nasce vazia e o gate falha fechada**, pelo que a loja fica muda até o texto existir: é o lado certo, porque a alternativa era tratar dados sem ter mostrado o aviso (ADR-010, `E3` req. 15). Quatro dívidas novas (75 a 78), e as duas primeiras são da classe da 74 — o bloco manda registar o que o **KAM-140** já fechou. **Dois defeitos que só uma máquina apanhou, os dois do ensaio:** um `excepcao.sqlstate` que o `pg8000` não tem (dezasseis erros), e a metade positiva do *append-only* a contar linhas que a sessão da aplicação não podia ver. | Equipa KAMBÁ |
| 1.9 | Outubro 2026 | **KAM-016 entregue, sem o nono critério.** Secção de verificação no bloco, com **oito** caixas de critério marcadas e **uma** vazia — o onboarding real numa conta de teste da Meta, que depende de `ext:KAM-102` e que **nenhuma medição deste ramo pode substituir**: não há `../docs/evidencia/KAM-016.md` e não se inventou nenhum. Entrou a revisão `0017` (a `channel_onboarding` com as nove fases e as duas unicidades), o módulo `packages/core-ts/src/onboarding/`, a rota `POST /internal/channels` na app **interna** do GWY, e a porta de escrita no cofre que o `ADR-L002` §6 declarou em falta para este dia. **Três leituras que mudaram o desenho:** o 409 do critério 4 é a `tenant_channels_phone_number_id_uq` **global** da `0001` a morder e não uma verificação em código; esta revisão **não acrescenta coluna nenhuma a `tenant_channels`**, porque os três identificadores do critério 8 existem desde a `0001`; e o registo de auditoria da recusa **não é o `audit_log`**, porque o domínio de `action` tem sete valores no `CHECK` da `0006`, fundida, e o *gate* 3b compara-o com o dicionário nos dois sentidos — um oitavo valor deixava essa revisão vermelha. **E quatro defeitos da revisão adversarial, os quatro sobre a fronteira transaccional, e o primeiro estava verde em todos os testes:** um `23505` aborta a transacção, pelo que a compensação que revoga o *token* respondia `25P02` — e o cofre **não é transaccional**, logo o `ROLLBACK` apagava a linha do canal e deixava o segredo lá (corrigido com um `SAVEPOINT`, e o duplo da base passou a modelar o `25P02`); a compensação apagava o canal **antes** de a linha o largar, e a FK sem `ON DELETE CASCADE` levantava `23503` — o que o comentário de `db/tests/test_inventario.py` já tinha previsto por escrito antes de o código existir; a limpeza corria antes da transição e o `channel_onboarding_canal_ck` levantava `23514`; e um comentário dizia o contrário do código, sendo o comentário o que estava errado. **A própria bateria esgotava o seu tecto**, e isso é o critério 8 a funcionar: o `es_onboardings_7d` atravessa *tenants*, pelo que as linhas de um teste contam na janela do seguinte. Emenda **1.29** ao dicionário (§3.20); a descoberta do X-05 passa de vinte e quatro para **vinte e cinco** tabelas; **528** mutações, 0 não aplicáveis. | Equipa KAMBÁ |
| 1.10 | Outubro 2026 | **Os critérios de saída do epic auditados, ticket a ticket.** O §2 passa a ter, debaixo de cada critério, ou a evidência que o prova — ficheiro e nome do teste — ou a razão de a caixa ficar vazia e de quem ela depende. **Cinco caixas marcadas e quatro vazias**, e as marcas não são a soma das caixas dos blocos: um critério de saída é mais estreito do que o critério de aceitação que lhe deu origem, e dois marcam-se por isso — a carga do KAM-013 mede o p99 em **199 ms** e a caixa do bloco só fica vazia pela regra do descarte, e o aviso do *free tier* aos 800 e aos 1.000 está medido com a caixa do bloco vazia pelo fuso por canal. Em sentido contrário, o do Chatwoot **desmarca-se** apesar de o ticket estar fundido: das três cláusulas, o cross-account pela API do provedor não está medido (o registo do X-10 é KAM-066) e o «1 conversa» só está provado do nosso lado. As quatro vazias são por terceiros ou por dependência: `ext:KAM-102` e `ext:KAM-100` (onboarding real e coexistência +244, e o contrato *online* do simulador), KAM-066 e a leitura no cliente do provedor (Chatwoot), e o **L10** — verificação por SMS —, que não tem nota em ticket nenhum deste epic porque o seu é o KAM-093, de outro. Nenhuma caixa se marcou sem o teste nomeado. O §3 e o código não mudaram; os blocos de ticket mudam na emenda seguinte e não nesta. | Equipa KAMBÁ |
| 1.11 | Outubro 2026 | **As caixas dos blocos KAM-016, KAM-017, KAM-021 e KAM-022, marcadas pelo que as suas tabelas de verificação já diziam.** A auditoria do §2 encontrou os quatro com **zero** caixas marcadas e as verificações a dar a maioria dos critérios como satisfeitos — o KAM-017 escreve «os nove critérios constroem-se, e oito ficam marcados» e tinha zero; o KAM-021 escreve «uma caixa fica vazia por segurança, e é a do critério 3», o que afirma que as outras estão marcadas, e tinha zero. Ficaram **cinquenta e sete** marcadas e **doze** vazias, critérios e DoD, e cada bloco leva agora uma nota a dizer que as caixas se marcaram a 2026-10-23 e por que regra: a caixa fica vazia quando **qualquer** parte do critério não se cumpre, e nenhuma se marcou sem o nome do teste citado ter sido conferido no ficheiro de teste. **As vazias:** `ext:KAM-102` (o onboarding real do KAM-016), `ext:KAM-100` (a elegibilidade do KAM-017), o `tenants.estado` que a revisão `0007` recusa por segurança (KAM-021), a metade da heurística do aviso preventivo que pede um sinal de painel que não existe (KAM-017, dívida 84), as quatro dos revisores humanos — vazias como facto registado, por decisão escrita do fundador — e as três do «todos os CA satisfeitos», que não fecham enquanto o bloco tiver um critério por fechar. **Nenhuma linha de tabela de verificação foi reescrita:** elas medem o que era verdade no dia em que correram. Dívida documental **87** paga no mesmo PR que a abriu. | Equipa KAMBÁ |
| 1.12 | Outubro 2026 | **As caixas dos sete blocos restantes conferidas, e nenhuma mudou.** A auditoria do §2 alargou-se aos blocos KAM-013, KAM-014, KAM-015, KAM-018, KAM-019, KAM-020 e KAM-024, caixa a caixa contra o veredito da tabela de verificação de cada um, nos **dois** sentidos — marcar o que a verificação sustenta e desmarcar o que ela não sustenta. **Os sete já concordavam**, e três deles declaram no próprio texto a contagem que têm («9 critérios; 7 marcados, 2 vazios» no KAM-013; «quinze caixas marcadas, três vazias» no KAM-020; e as emendas 1.2, 1.4 e 1.5 para o KAM-014, o KAM-024 e o KAM-015). O que esta emenda acrescenta é, por isso, a nota no §2 de que a conferência cobriu os blocos todos — e o resultado do inverso, que é a verificação mais forte que o repositório permite aqui: os **328** nomes declarados nas listas `GRUPOS` e `TESTES_OBRIGATORIOS` das suites de `db/tests_*/` existem todos nos ficheiros de teste, quatro deles com uma constante interpolada no nome. Uma caixa cuja evidência está nessas listas é prendida por máquina: o nome que desaparecer faz a suite falhar. Nenhum bloco de ticket, nenhuma tabela de verificação e nenhum código mudaram nesta emenda. | Equipa KAMBÁ |
| 1.13 | Outubro 2026 | **As caixas vazias dos tickets fundidos inventariadas por credor**, em [`../docs/epic-02-divida-de-criterios.md`](../docs/epic-02-divida-de-criterios.md). Das caixas vazias que a auditoria do §2 contou, as dos revisores humanos e as do «todos os CA satisfeitos» são derivadas e as do KAM-115 são trabalho por fazer; sobram **32** nos tickets fundidos, e o documento dá a cada uma a razão que a tabela de verificação do seu bloco já dava, mais o credor e a classe. **O achado é que cinco esperam um ticket que já fundiu** e ninguém voltou a medir: o critério 5 do KAM-024 («usado por KAM-015, 016, 017 e 020» — os quatro fundidos), o critério 1 do KAM-018 (a detecção do *echo*, que pedia o KAM-017), o critério 8 do KAM-015 (o *lock* da conversa, que pedia o KAM-018), o critério 6 do KAM-018 (a `v3` do contrato e o `setBotMuted`, que pediam o KAM-007 e o KAM-019) e o critério 3 do KAM-014. É a mesma classe de omissão que a emenda 1.10 encontrou no §2, um nível abaixo. O resumo por credor desfaz a leitura pessimista das caixas soltas: só sete esperam genuinamente um terceiro (`ext:KAM-100` e `ext:KAM-102`), dez são decisões e não trabalho — e **duas dessas não devem fechar**, a do KAM-021 porque devolver o privilégio reabre uma escalada e a do KAM-024 porque satisfazer a letra pioraria a protecção. Três caixas não têm credor nomeado, e é isso que as torna perigosas. Nenhuma caixa se marcou ou desmarcou, e nenhuma tabela de verificação foi reescrita. | Equipa KAMBÁ |
| 1.14 | Outubro 2026 | **KAM-115 entregue, e o epic fecha.** Secção de verificação no bloco, com **sete** caixas de critério marcadas e **uma** vazia, e com seis das oito do DoD. O que fica vazio é o alvo de «≥ 95% dos *tenants* `ativo` com contacto verificado» (critério 6): é medição sobre *tenants* reais e não há nenhum — a métrica que o mede está entregue, com numerador **e** denominador, e a varredura que a alimenta também. **O risco R16 passa a FECHADA**: era «sem ticket para avisar o dono por canal alternativo», e os emissores existiam desde o KAM-017, o KAM-021 e o KAM-023 — o que não existia era quem entrega. Entregues: a revisão `0019` com **duas** tabelas (e são duas porque o critério 7 manda marcar o **contacto** como inválido, que é facto do contacto e não do aviso), o módulo `packages/core-ts/src/avisos/`, a *suite* de *gate* 8 `tests_avisos` — a primeira que leva as duas baterias do módulo no mesmo corredor —, e o *gate* de `prod` do subprocessador, que é a alternativa que o próprio critério 8 escreve («ou fica `pendente` e bloqueia `prod`»), porque o inventário do KAM-069 não existe e escolher um subprocessador num ficheiro de código é o que o ADR-008 existe para impedir. **Três defeitos apanhados por máquina**, e o terceiro é o mais sério: o `criado_at` não podia vir do `now()` do servidor (o relógio acelerado dos ensaios media uma coisa e a base registava outra, e a varredura dos lembretes não via episódio nenhum); o `apagarTenant` do `apoio.ts` não conhecia as duas tabelas novas e o `after` pendurava o processo por trezentos segundos **sem uma linha de saída**; e a prova por mutação foi a **primeira coisa a executar** a bateria de esquema deste ticket — o *gate* 8 correu antes de ela existir —, encontrando quatro testes a responder `25P02` em vez de `23514` por falta de `SAVEPOINT`. **E a revisão adversarial não aprovou a primeira versão**: quatro achados, os quatro corrigidos — os lembretes **nunca saíam** (a janela do gatilho filtrava-os, e o teste que o afirmava media um histórico vazio), o tecto diário contava linhas e não avisos, a varredura tinha uma guarda **inalcançável** no lugar do «depois pára e abre tarefa a T2» (e o `lembretesEsgotados` existia, estava testado e não era chamado por ninguém), e a hora do aviso saía em UTC a um dono de Luanda. | Equipa KAMBÁ |
