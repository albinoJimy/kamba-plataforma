# EPIC-05 — Pagamentos e Billing

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Pagamentos e Billing |
| Versão | 1.10 |
| Data | Outubro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` |
| Documentos relacionados | `../docs/tecnica/00_Arquitectura_Solucao.md`, `../docs/tecnica/03_Core_Comercio_Medusa.md`, `../docs/tecnica/06_Dados_Eventos_Analytics.md`, `../docs/tecnica/08_Seguranca_Conformidade.md`, `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md`, `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/EPIC-04_Core_Comercio.md` |

---

## 1. Visão do Epic

O **PAY** é o componente que torna a terceira fundação da KAMBÁ — *dinheiro confirmado só por evento autenticado, com liquidação directa à PME e a plataforma nunca na posse dos fundos* — arquitecturalmente verificável. Entrega a interface `PaymentProvider` (com `verifyCallback` e `reconcile`, sem as quais a regra do ADR-013 não é implementável), o *ledger* `payment_events` *append-only* com escrita só por função, o `ManualProvider` (o único meio de pagamento com que o Piloto pode arrancar, porque o contrato bancário e do facilitador é caminho crítico de papel e não de engenharia), o adaptador do facilitador (ProxyPay, se o contrato existir), a régua e o billing da assinatura da própria KAMBÁ e a detecção de anomalias. Os esquemas SQL são os de `../docs/tecnica/04` §6 e §11; este epic não os reinventa.

O epic existe porque a falha de pagamento em Angola tem um vector documentado e barato: o comprovativo editado (perdas de 500 000 Kz ou mais, com detenção confirmada pela Polícia, `../docs/tecnica/evidencia/E2` §4). Por isso a imagem nunca é prova; o estado `paga` só é alcançável por HMAC verificado, consulta autenticada ao facilitador ou confirmação humana auditada, limitada e com dupla verificação. Os limites do `ManualProvider` (50 000 Kz por pedido, dupla aprovação acima de 20 000 Kz), a régua D+3/D+7/D+10 e a banda cambial de ±5% são **propostas a calibrar no Piloto**; preços do ProxyPay, rate limits, assinatura do callback OPG e prazo de onboarding bancário são **NÃO VERIFICADOS** e cada ticket afectado traz critério de saída. Payouts, escrow, sub-adquirência e comissão sobre transacção ficam fora do Piloto.

Concretiza os ADRs **ADR-004** (plataforma sem fundos; guardas G-1..G-6), **ADR-013** (pagamento só por evento autenticado), **ADR-017** (assinatura primeiro, comissão desligada), **ADR-009** (outbox na mesma transacção), **ADR-010** (pagador por `contact_id`), **ADR-007** (valores e referências vêm da cobrança, nunca do LLM) e **ADR-015** (RLS `FORCE` e classe de tool `money`), com **ADR-011** a manter `origem='plataforma'` no DDL sem correr em produção. **Fase 0:** KAM-052 a KAM-055 (o `payment.manual_confirmed` é parte do gate **KAM-108**). **Fase 1:** KAM-056 a KAM-060, condicionados a **D4** (facilitador), **D8** (enquadramento BNA) e **D10** (canal operacional da KAMBÁ).

---

## 2. Critérios de Saída do Epic

- [ ] Nenhuma cobrança nem encomenda está `paga` sem evento com `authn_ok=true` e `authn_method IN ('hmac_sha256','status_pull','humano_auditado')`: a consulta de consistência diária devolve 0 linhas e o `CHECK confirmar_exige_autenticacao` está activo em produção.
- [ ] `UPDATE`, `DELETE` e `TRUNCATE` sobre `payment_events` falham para `kamba_app` e `kamba_ops`; o `INSERT` só é possível por `append_payment_event`; a cadeia de *hashes* é verificada diariamente e a cabeça exportada.
- [ ] A suite de conformidade de adaptador (`../docs/tecnica/04` §3.5) está verde para o `ManualProvider` e, se o contrato existir, para o ProxyPay RPS; sem ela verde o adaptador não é activável.
- [ ] Callback duplicado ×10 produz 1 efeito; valor ± 1 cêntimo produz `pagamento_divergente`; HMAC inválido não altera estado, devolve 401 e fica registado.
- [ ] `ManualProvider`: pedido acima de `manual_max_minor` é recusado; confirmação com valor ≠ `amount_minor` é rejeitada; acima do limiar de dupla verificação não há `paga` sem segunda aprovação de outro confirmador.
- [ ] Guardas G-1..G-6 testadas: beneficiário = PME (*trigger*), `payout`/`refund` devolvem `NOT_SUPPORTED`, não existe `balance`/`wallet`, `commission_enabled=false`.
- [ ] Fase 0: a demonstração do gate KAM-108 mostra `payment.manual_confirmed` a levar a encomenda a `paga` e o evento consumido pela vertical Serviços sem excepção no core.
- [ ] Alvos de `../docs/tecnica/04` §14 medidos: p95 pagamento → `paga` ≤ 5 s; ack de callback p99 < 500 ms; 0 órfãos abertos > 24 h.
- [ ] Billing: dois ciclos de execução do mesmo período produzem 1 `billing_cycle` e 1 cobrança; a régua suspende no D+10 uma única vez e reactiva na regularização.
- [ ] Cada item NÃO VERIFICADO (D4, D8, D10) tem decisão escrita ou *feature flag* desligada com critério de saída registado no ticket.

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-052 | Interface PaymentProvider (com `verifyCallback` e `reconcile`) e beneficiário por conta | feature | M | P0 | KAM-003, KAM-008 |
| KAM-053 | Ledger `payment_events` append-only (INSERT por função) e unicidade | feature | L | P0 | KAM-052, KAM-004, KAM-008 |
| KAM-054 | ManualProvider: confirmação humana auditada, limites e dupla verificação | feature | L | P0 | KAM-052, KAM-053, KAM-015, KAM-014, KAM-012 |
| KAM-055 | Eventos `payment.confirmed` e `payment.manual_confirmed` e transição da encomenda | feature | M | P0 | KAM-054, KAM-044, KAM-005, KAM-006 |
| KAM-056 | Adapter ProxyPay: referências, callbacks HMAC, reconciliação e expiração | feature | L | P1 | KAM-052, KAM-053, ext:KAM-103, KAM-013, KAM-010 |
| KAM-057 | Avaliação do segundo facilitador (AppyPay) e matriz de decisão | spike | S | P2 | KAM-052, ext:KAM-103 |
| KAM-058 | Régua de cobrança D+3/D+7/D+10 | feature | M | P1 | KAM-055, KAM-015, KAM-059, ext:KAM-101 |
| KAM-059 | Billing da plataforma: assinatura via PaymentProvider (beneficiário próprio) | feature | L | P1 | KAM-052, KAM-054, KAM-009 |
| KAM-060 | Detecção de anomalias de pagamento (valor divergente, duplicados, padrões) | feature | M | P1 | KAM-053, KAM-054 |
| KAM-175 | Um `DELETE` sem linhas no *ledger* `payment_events` não é recusado: o *trigger* por instrução só cobre o `TRUNCATE` | fix | S | P1 | KAM-053 |

---

## KAM-052 — Interface PaymentProvider (com `verifyCallback` e `reconcile`) e beneficiário por conta

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-003, KAM-008 |
| Bloqueia | KAM-045, KAM-046, KAM-053, KAM-054, KAM-056, KAM-057, KAM-059 |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§3, §6.2, §10.2, §10.4), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-004, ADR-011, ADR-013), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` |

### Contexto
O contrato de quatro métodos do doc 00 §4 (`createCharge`, `status`, `refund`, `payout`) não permite verificar a autenticidade de um callback nem reconciliar um pagamento perdido; a PA-04-1 acrescenta `verifyCallback`, `listUnacknowledged`, `acknowledge`, `cancelCharge` e `capabilities`. A interface é uma costura definitiva (princípio 8): fixa-se agora, os adaptadores engrossam por fase. A conta de pagamento passa a ter beneficiário explícito (PA-04-4), o que torna o ADR-004 verificável e permite à KAMBÁ cobrar a própria assinatura sem activar o tenant `platform` (vedado por D2).

### Objectivo
Entregar o pacote `pay-core` com a interface completa, `ProviderCapabilities`, registo de adaptadores com regras de activação, a tabela `payment_accounts` (DDL de `../docs/tecnica/04` §6.2) com o *trigger* de beneficiário (G-1), as *flags* G-2 e o *harness* reutilizável da suite de conformidade.

### Critérios de Aceitação
- [x] A interface TypeScript contém os 8 métodos de `../docs/tecnica/04` §3.1 e os tipos `Minor = bigint`, `Metodo`, `ChargeResult`, `ProviderErr`; um *lint* falha o *build* se um montante for `number` ou vírgula flutuante em qualquer ficheiro de `pay-core`.
- [x] O registo recusa activar um adaptador com `callbackAuth='none'` e `statusQuery=false` (erro `ADAPTER_CANNOT_CONFIRM`), excepto adaptadores só de confirmação humana (`ManualProvider`), e recusa chamar uma capacidade não declarada.
- [x] `refund` e `payout` de qualquer adaptador devolvem `NOT_SUPPORTED`; com `payouts_enabled=true` sem adaptador marcado `psp_licenciado` o serviço não arranca (teste de arranque).
- [x] A migração cria `payment_accounts` conforme §6.2, é reversível (inversa testada) e o índice `payment_accounts_um_ativo` impede 2 contas activas do mesmo `provider` para um tenant.
- [x] O *trigger* `assert_beneficiary` rejeita: cobrança de encomenda cuja conta tem `tenant_id` ≠ `tenant_id` da cobrança; conta `plataforma_receita_propria` usada numa encomenda; conta partilhada entre dois tenants (3 testes).
- [x] A verificação de arranque G-4 falha se alguma conta de `tenant` apontar para uma entidade EMIS da KAMBÁ (lista de entidades da KAMBÁ em configuração).
- [x] A coluna `credenciais_ref` só aceita caminho do cofre; um teste de varrimento de colunas e fixtures por padrões de segredo devolve 0 ocorrências.
- [x] A transição de `payment_accounts.estado` (`nao_iniciado` … `ativo`/`revogado`, §10.2) é uma função pura; `nao_iniciado → ativo` é rejeitada e `teste_sandbox_ok → ativo` exige o sinal «primeira cobrança real conciliada».
- [x] O *harness* expõe os 10 casos obrigatórios de `../docs/tecnica/04` §3.5 como testes parametrizáveis por adaptador e um `FakeProvider` passa todos.

### Detalhes Técnicos
- **Componentes:** PAY, TEN. Módulos `services/pay/src/provider/{types,registry,capabilities}.ts`, `services/pay/src/accounts/`, `migrations/NNNN_payment_accounts.sql`, `services/pay/test/conformance/` (*harness*).
- **Regra de activação (pseudocódigo):** `activate(adapter) { if (!adapter.humanOnly && adapter.capabilities.callbackAuth !== 'hmac' && !adapter.capabilities.statusQuery) throw AdapterCannotConfirm; if (!conformance.green(adapter.id)) throw ConformanceRequired; }`. O campo `humanOnly` é uma extensão mínima a `ProviderCapabilities`; regista-se na revisão.
- **Ordem de migração** (`../docs/tecnica/04` §6): `…orders_mirror → payment_accounts → payment_charges → payment_events`. `payment_accounts` só referencia `tenants`; as FK para `orders_mirror` são acrescentadas por KAM-055 e a de `billing_cycles` por KAM-059.
- RLS `FORCE` em `payment_accounts` por `tenant_id` (nulo para a conta da KAMBÁ, acessível só ao papel de billing). `webhook_token` gerado na aplicação, opaco, 32 bytes aleatórios.
- Notas: `iec`, `pos_id` e `entidade` são identificadores EMIS da PME; o prazo e os requisitos bancários para os obter são NÃO VERIFICADOS (D4/KAM-103) e não bloqueiam este ticket.

### Testes Requeridos
- Unit: registo e regras de activação; função de transição de `estado`; conversão `Minor` ↔ `decimal2`/`inteiro_kz`.
- Integração (Postgres real): *trigger* G-1 (3 casos), RLS cruzada (tenant A não lê contas de B), migração aplicar/reverter.
- Contrato: `FakeProvider` contra o *harness* da suite §3.5.
- Segurança: varrimento de segredos em colunas e fixtures; arranque com `payouts_enabled=true`.

### Definition of Done
- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] Plataforma sem fundos (ADR-004): G-1, G-2 e G-4 verificados por teste; sem `balance`, `wallet` nem `escrow` no código ou na UI.
- [x] Isolamento de tenant: RLS `FORCE` em `payment_accounts` e caso novo na suite cruzada (KAM-066).
- [x] Sem segredos em código, logs ou colunas; `credenciais_ref` só aponta ao cofre.
- [x] Migração reversível com inversa testada; dependências fixadas; cobertura do módulo de dinheiro ≥ 90%.
- [ ] Dois revisores (P0 de dinheiro); decisão sobre `humanOnly` registada no PR.

### Verificação dos Critérios de Aceitação

Uma linha por critério, com a prova nomeada. Os comandos e os resultados estão no
corpo do PR; o que esta tabela dá é **onde** a propriedade se mede.

| # | Critério | Estado | Prova |
|---|---|---|---|
| 1 | Os 8 métodos de §3.1, os tipos `Minor`/`Metodo`/`ChargeResult`/`ProviderErr`, e um *lint* que falha o *build* com `number` ou vírgula flutuante | **satisfeito** | Os oito estão na `interface PaymentProvider` de `packages/core-ts/src/pagamentos/tipos.ts`, e `Minor = bigint`. O *lint* é o `tools/money_lint`, no **gate 2** (`make money-lint`, dentro de `ci-2`, que o CI corre) — e não num *job* novo, porque isso acrescentaria um contexto exigido ao *ruleset* de `main`, que é alteração de regra de bloqueio. **Seis regras, com canário de treze negativas e sete positivas**, e o canário corre no gate e não só num `unittest`. **Cinco formas passavam o lint e foi uma revisão adversarial a medi-las**: a conversão dentro de um literal de *template*, o separador de milhares num decimal (`50_000.00` — o estilo da casa era o que cegava o lint), o expoente, o `+` unário — que estava na *docstring* e não estava implementado — e o `number` por asserção e por tipo de retorno. **Nota de letra:** o critério diz «falha o *build*» e isto é o gate 2 (tipos), não o gate 1 (*build*). Bloqueia de facto |
| 2 | O registo recusa activar quem não pode confirmar (`ADAPTER_CANNOT_CONFIRM`), excepto `ManualProvider`, e recusa chamar capacidade não declarada | **satisfeito** | `registo.ts`, com `activar` e `chamar`. **Implementa-se a regra dos *Detalhes Técnicos* (`callbackAuth !== 'hmac'` e sem `statusQuery`) e não a do critério**, e a diferença é o `desconhecido`: o AppyPay está em NÃO VERIFICADO na matriz do §3.2 e activava-se pela letra. O §3.4 já manda tratar o desconhecido como `none` por escrito, e o princípio 1 do §2 é *fail closed*; o conjunto recusado **contém** o do critério. Dívida **151**. **Duas correcções da revisão adversarial:** o `capabilities.metodos` **não era lido por linha nenhuma de produção** — medido, `createCharge` aceitava `cod` num adaptador que só declara `referencia`, e um pedido de pagamento à entrega recebia uma referência Multicaixa —, e a dispensa do `humanOnly` era **auto-atribuída**, isto é, a guarda do ADR-013 desligava-se com uma linha nas capacidades do adaptador que ela devia medir. Entram `suporta()`/`cobrar()` e a `PoliticaDeActivacao` com listas fechadas |
| 3 | `refund` e `payout` devolvem `NOT_SUPPORTED`; com `payouts_enabled=true` sem `psp_licenciado` o serviço não arranca | **satisfeito** | `chamar` **devolve** a recusa (não lança) e o adaptador nunca é chamado — a G-2 a morder no registo. A primeira versão lançava, e a revisão adversarial apanhou a divergência: o critério escreve «devolvem» e o §3.1 tipa o retorno, pelo que o `RefundResult` ficava inalcançável pelo caminho recomendado. A G-2 passa a morder também na **declaração**: `refund: true` ou `payout: true` recusam a activação (o §10.4 tem dois mecanismos e só o segundo estava imposto). O teste de arranque é `pagamentos.arranque.test.ts`, «com payouts_enabled=true e sem psp_licenciado, o serviço não arranca» → `PAYOUTS_SEM_PSP_LICENCIADO`. **A lista de PSP reconhecidos está vazia e só D8 a abre**, pelo que a *flag* ligada recusa sempre; o caminho positivo mede-se com uma política explícita |
| 4 | A migração cria `payment_accounts` conforme §6.2, é reversível, e `payment_accounts_um_ativo` impede 2 contas activas do mesmo `provider` | **satisfeito** | Revisão `0027`, com `down_revision = "0026"`. **Uma divergência face ao §6.2, e é a única:** `beneficiary_kind` é `pme` e não `tenant`, porque o dicionário §3.4 fecha o domínio e o gate 3b recusa o valor do documento — medido, dezanove achados sobre uma migração copiada à letra. Dívida **149**. A inversa é o `TestDowngradeDa0027`, que desce a `0026`, exige que a tabela, a função, o índice e a política **desapareçam**, e sobe outra vez. O índice é o `TestIndiceUnicoParcial`, com cinco ensaios: dois activos recusados, o predicado a ser **dois** estados e não um, o par livre depois de `revogado`, dois tenants com o mesmo `provider`, e — o que fica dito para não parecer descuido — que o índice **não** limita a KAMBÁ a uma conta própria, porque um índice único do PostgreSQL não considera dois `NULL` iguais |
| 5 | O *trigger* `assert_beneficiary` rejeita os três casos (3 testes) | **satisfeito** | `TestGuardaDoBeneficiario`, contra PostgreSQL real, com os três nomeados: `test_caso_1_encomenda_com_conta_de_outro_tenant_e_recusada`, `test_caso_2_conta_da_plataforma_numa_encomenda_e_recusada` e `test_caso_3_a_conta_nao_e_um_recurso_partilhado_entre_tenants` — este **com dois tenants e não um**, porque provar que a conta de A recusa a cobrança de B uma vez não prova que ela não é um recurso partilhado; provar que recusa B **e** C prova. Mais o caminho feliz (sem ele os três podiam estar a recusar tudo) e o billing numa conta de PME. **O *trigger* liga-se a uma tabela de ensaio com a forma da `payment_charges`**, que é do KAM-055: o que corre é a função que vai para produção, com contas reais e recusas reais do servidor; o que falta é a tabela a que ela se vai ligar. É o recurso que o `test_x05_catalogo.py` já usa, e é mais honesto do que não medir |
| 6 | A verificação de arranque G-4 falha se alguma conta de `tenant` apontar para uma entidade EMIS da KAMBÁ | **satisfeito** | `verificarG4` em `arranque.ts`, com a lista em `config/kamba_emis.yaml` e espelhada em TypeScript (confrontadas **como texto** por ensaio, o desenho do `config/meta_rates.yaml`). **As três listas estão vazias e o estado é NÃO VERIFICADO** (D4, KAM-103): com elas vazias a guarda passa sempre, e é um zero que não diz nada. Por isso a lista é um **parâmetro sem omissão** — a revisão adversarial mostrou que a omissão fazia a guarda ler a constante compilada, pelo que editar o YAML não mudava nada no serviço a correr — e há **controlo positivo**: `recusa uma conta de pme que aponte para a entidade da KAMBÁ`, e os três identificadores medidos um a um. Mais o lado que não se pode recusar: a conta de receita própria **com** a entidade da KAMBÁ passa, senão o KAM-059 era impossível |
| 7 | `credenciais_ref` só aceita caminho do cofre; o varrimento de colunas e fixtures devolve 0 | **satisfeito** | A forma está no `CHECK` da revisão **e** é a mesma expressão do `SecretRef` do KAM-010, confrontadas como texto (`test_a_forma_do_credenciais_ref_e_a_do_secretref`). Os valores recusados são as formas em que um segredo chega de facto — PEM, `base64` com enchimento, maiúsculas, espaços, 300 caracteres — e montam-se por **concatenação**, porque o *gate* 9 recusou o *commit* da primeira versão deste ensaio, com razão: um literal com prefixo de fornecedor é indistinguível de uma chave viva para quem varre, e o remédio errado era declarar o ficheiro em `ci/secrets-allow.yaml`. O varrimento é o `TestSemSegredosNasColunas`, e corre com os **padrões do gate 9** e não com uma segunda lista escrita à mão: as onze colunas de texto de uma conta completa, mais as *fixtures* (o próprio ficheiro), mais o **controlo positivo** que exige que o varrimento veja uma chave de API. `scan_secrets tree` limpo em 1501 ficheiros |
| 8 | A transição de `estado` é função pura; `nao_iniciado → ativo` rejeitada; `teste_sandbox_ok → ativo` exige o sinal | **satisfeito** | `estados.ts`, função pura (`test_e_pura`). A tabela é a do `stateDiagram-v2` do §10.2 e **nenhuma a mais**: o ensaio percorre os 81 pares `(estado, gatilho)` e exige que os **72** que o diagrama não tem sejam recusados. `nao_iniciado → ativo` é recusada por **ausência de aresta** e não por caso especial. O sinal é exigido **só** naquela aresta, e isso mede-se nos dois sentidos — sem o sinal recusa, com `false` recusa, e a regularização `suspenso → ativo` **não** o pede, senão uma PME regularizada ficava travada. **Uma correcção da revisão adversarial:** o `podeCobrar` devolvia só `ativo`, duas linhas abaixo de uma constante que dizia o contrário, e com isso **nenhuma conta chegava a `ativo`** — a transição exige uma cobrança real, que ele recusava em `teste_sandbox_ok`. Um impasse que só aparecia com a primeira PME. `suspenso → revogado` não existe no diagrama e fica na dívida **152** |
| 9 | O *harness* expõe os 10 casos de §3.5 parametrizáveis por adaptador, e o `FakeProvider` passa todos | **satisfeito** | `conformidade.ts`, com `CASOS` de **dez** entradas, contadas por ensaio e confrontadas com a transcrição do §3.5 pela ordem do documento. O `FakeProvider` passa os dez. **E o caso que mede autenticidade foi reescrito, porque a primeira versão não media nada:** uma revisão adversarial construiu dois adaptadores obviamente defeituosos — um que não verifica assinatura nenhuma e um que verifica HMAC e **ignora a conta** — e mediu que os dois passavam os dez casos e eram activados; reproduzido, o primeiro aceita um callback forjado sem chave. A causa era estrutural: o caso recebia a mutação **de quem estava a ser medido**. Passa a exigir a recusa de um callback **genuinamente assinado para outra conta**, que é agnóstica ao formato e mata os dois, e os dois ficam como ensaio permanente. **Os dez casos têm canário** (eram cinco), com ensaio a exigir que nenhum fique sem — e foi um canário a descobrir que o caso 2 estava vazio. O caso 2 passa a medir a divergência de ±1 **contra a cobrança**, que é o que o §3.5 nomeia; o caso 7 conta as cobranças criadas no facilitador; e o `status()` deixou de ser um memorando do callback, que tornava o caso 10 tautológico |

#### Verificação do Definition of Done

| Caixa | Estado | Nota |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | **satisfeito** | Os nove acima, cada um com prova nomeada. Duas divergências face à letra ficam declaradas e não escondidas: a regra de activação segue os *Detalhes Técnicos* e não o critério 2 (dívida 151), e o `beneficiary_kind` segue o dicionário e não o §6.2 (dívida 149) |
| Plataforma sem fundos (ADR-004): G-1, G-2 e G-4 verificados por teste; sem `balance`, `wallet` nem `escrow` | **satisfeito** | G-1 no `TestGuardaDoBeneficiario` (contra PostgreSQL) e em `pagamentos.contas.test.ts`; G-2 e G-4 em `pagamentos.arranque.test.ts`, as duas a **recusar o arranque** e as duas com controlo positivo. Os três nomes não existem: o `money_lint` recusa-os neste directório (regra `sem_fundos`, com canário) e o `test_nao_ha_colunas_de_dinheiro_nem_saldos` recusa `%saldo%`, `%balance%`, `%_minor` e `%_kz` em `platform` — a `payment_accounts` **não tem coluna de dinheiro nenhuma**, e isso é a G-3 e não uma omissão. Verificado por `grep` independente na revisão adversarial: três ocorrências na árvore, todas legítimas |
| Isolamento de tenant: RLS `FORCE` em `payment_accounts` e caso novo na suite cruzada (KAM-066) | **satisfeito** | `rls.enable_tenant_rls("payment_accounts")`, que emite `ENABLE`, `FORCE` e a política `tenant_iso`. A tabela entra no X-03, X-04 e X-05 do **gate 6** sem ninguém a declarar (a descoberta é pelo catálogo), e o que se declarou foram as três listas fechadas: a da descoberta, a de políticas — **uma** e não duas, porque «políticas permissivas somam-se por OU» — e a dos nomes com `tenant_iso`. A receita de sementes é `_payment_account`, com `escrita_do_papel=False`, porque o `kamba_app` **lê e não escreve**: nesta tabela o X-03/X-04 troca «a política recusa a escrita» por «o privilégio nem existe», que é mais forte. A suite cruzada ponta a ponta é o **KAM-066** e continua a ser dele |
| Sem segredos em código, logs ou colunas; `credenciais_ref` só aponta ao cofre | **satisfeito** | O critério 7 acima, mais `scan_secrets tree` limpo em 1501 ficheiros — e o *gate* 9 **recusou** o primeiro *commit* deste ticket, duas vezes, o que é a prova de que ele morde sobre esta árvore. Nada se declarou em `ci/secrets-allow.yaml`: as formas de ensaio montam-se por concatenação e um local chamou-se `emitido` em vez do nome óbvio, porque o padrão `atribuicao` não distingue um literal de uma chamada de função. Nenhum valor de segredo em coluna nenhuma, medido com os padrões do gate 9 |
| Migração reversível com inversa testada; dependências fixadas; cobertura do módulo de dinheiro ≥ 90% | **satisfeito** | A inversa é o `TestDowngradeDa0027` (critério 4). **Nenhuma dependência nova**, em Node ou em Python: o módulo usa o `node:crypto` da biblioteca padrão e o `money_lint` só a biblioteca padrão do Python — pelo que não há *lockfile* a mexer nem SBOM a crescer. A cobertura é a do estrato `critico` do `ci/thresholds.yaml`, que já tinha o padrão `pagamentos` a 90% escrito «para os tickets que os vão criar (KAM-052 em diante)»: **não se acrescentou padrão nenhum**, e este directório é o dia em que ele começa a morder. **Medido à parte, por ficheiro, e a razão fica dita:** o `coverage_gate.py` agrega **por estrato**, pelo que passar o gate 4 não prova que este módulo esteja acima de 90% — a medição independente da revisão adversarial deu **96,00% de linhas** no módulo |
| Dois revisores (P0 de dinheiro); decisão sobre `humanOnly` registada no PR | *(caixa vazia)* — **não satisfeito** | **Metade cumpre-se e a outra não, e a caixa fica vazia por causa da que não cumpre.** A decisão sobre o `humanOnly` **está registada no PR**, como os *Detalhes Técnicos* mandam, e com o acrescento que a revisão levantou (A22): a recusa `HUMAN_ONLY_INCOERENTE` é uma recusa **nova** que o bloco não tem, e a dispensa passou a ser uma lista fechada em vez de um booleano que o adaptador se atribui. **Os dois revisores não existem:** nesta fase funde-se com CI verde sem esperar revisão humana (decisão do fundador), e uma revisão adversarial é **evidência, não é um revisor** — ela mede, não assina. Há uma, independente, com 23 achados CONFIRMADO, registada em `../docs/analises/ANALISE-41-interface-paymentprovider.md`. **E diz-se por extenso, porque é informação que o fundador pode querer usar:** este é um ticket **P0 de dinheiro** e o critério pede dois revisores **explicitamente** — é um dos poucos do conjunto que o faz. Esconder isso atrás de «não há revisores nesta fase» seria pior do que a caixa vazia. O mesmo vale para a nota do `ci/thresholds.yaml`, que escreve «alterar este ficheiro pede dois revisores»: este ticket **não** o alterou, pelo que a questão não se põe aqui |

### Handoff para Claude Code

```text
És o executor do ticket KAM-052 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-052),
docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md (§3.1, §3.5, §6.2, §10.2, §10.4) e ADR-004/011/013.
Objectivo: pacote pay-core com a interface PaymentProvider completa (8 métodos), ProviderCapabilities,
registo com regras de activação, tabela payment_accounts com trigger assert_beneficiary (G-1),
flags G-2 e o harness da suite de conformidade (§3.5).
- Minor é bigint; sem floats em montantes; refund/payout => NOT_SUPPORTED.
- Adaptador sem HMAC e sem statusQuery não confirma (excepto humano-only).
- credenciais_ref guarda caminho do cofre, nunca o segredo. RLS FORCE. Migração reversível.
Não expandas escopo: ledger (KAM-053), ManualProvider (KAM-054) e ProxyPay (KAM-056) são tickets próprios.
Testes: unit, integração (trigger, RLS, migração), contrato (FakeProvider). PR com o template (§7).
```

---

## KAM-053 — Ledger `payment_events` append-only (INSERT por função) e unicidade

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-052, KAM-004, KAM-008 |
| Bloqueia | KAM-054, KAM-056, KAM-060, KAM-175 |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§5, §6, §7, §8), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§6.1), `../docs/tecnica/08_Seguranca_Conformidade.md` (§3.3, §4.5), ADR-009, ADR-013, ADR-015 |

### Contexto
O DDL do doc 11 tinha `UNIQUE (provider, referencia)` (mistura *dedupe* com estado), `estado` + `boolean` na mesma linha, `valor_kz int` e nenhum mecanismo contra `UPDATE`/`DELETE`; `../docs/tecnica/04` §6.1 corrige-o. O ledger regista factos (`pagamento_recebido`) e decisões (`pagamento_confirmado`, `pagamento_divergente`) separadamente; o estado é derivado e vive em `payment_charges`, a única tabela mutável de PAY. Os docs 00 e 08 falam em `callback_hmac_ok`; o campo canónico é `authn_ok` com `authn_method`.

### Objectivo
Implementar `payment_charges`, `payment_callbacks_inbox` e `payment_events` com imutabilidade por privilégios e *triggers*, a função `append_payment_event` (único caminho de escrita, projecta o estado e escreve no *outbox*), `next_state`, `rebuild_charge_state`, a cadeia de *hashes* com verificação diária e o *handler* genérico `POST /hooks/pay/{provider}/{webhook_token}` que grava no *inbox* antes de qualquer 2xx.

### Critérios de Aceitação
- [x] `UPDATE`, `DELETE` e `TRUNCATE` em `payment_events` falham como `kamba_app` e como `kamba_ops` (3 testes); `INSERT` directo como `kamba_app` falha por permissão e `SELECT * FROM append_payment_event(...)` funciona.
- [x] Inserir `pagamento_confirmado` com `authn_ok=false`, ou com `decisao='rejeitada'`, é rejeitado pelo `CHECK`; a função recusa também se `valor_minor ≠ amount_minor` ou `account_id` difere da cobrança, mesmo que o `CHECK` passe.
- [x] Dois eventos do mesmo `(provider, account_id, referencia, tipo_evento)` recebem `sequencia` 1 e 2; 20 chamadas concorrentes sobre a mesma cobrança produzem sequências 1..20 sem lacunas (`FOR UPDATE`).
- [x] O mesmo `provider_event_id` num `pagamento_recebido` duas vezes produz 1 linha no ledger e o recibo `duplicado` (G7); a mesma referência em duas contas (entidades) distintas é aceite.
- [x] `next_state` cobre todas as transições de `../docs/tecnica/04` §7.1 e rejeita as restantes; um teste de propriedade com 1 000 sequências aleatórias válidas mostra `rebuild_charge_state(c)` igual a `payment_charges.estado`.
- [x] `row_hash = sha256(prev_hash ‖ campos canónicos)`; alterar um byte com superutilizador num teste faz o *job* `verify_ledger_chain` falhar e alertar; a cabeça da cadeia é exportada diariamente via `StorageProvider` (*fake* em teste).
- [x] Token desconhecido devolve 404 uniforme com recibo `token_desconhecido`; HMAC inválido devolve 401, deixa `payment_callbacks_inbox.estado='hmac_invalido'` e `sig_ok=false` e escreve 0 linhas em `payment_events`; o corpo é durável antes do 2xx; ack p99 < 500 ms a 50 pedidos/s.
- [x] A escrita no `events_outbox` ocorre na mesma transacção: uma falha forçada no *outbox* reverte também a linha do ledger.
- [ ] A vista `v_payment_events_audit` expõe `callback_hmac_ok = (authn_method='hmac_sha256' AND authn_ok)` para os alvos de `../docs/tecnica/08` §14.

### Detalhes Técnicos
- **Componentes:** PAY, EVT. DDL exactamente o de `../docs/tecnica/04` §6.2 (`payment_charges`, `payment_callbacks_inbox`, `payment_events`, `deny_mutation`, índices `payment_events_entrega_uq`, `payment_charges_ref_uq`, `payment_charges_activa_uq`).
- **As três colunas de dinheiro deste ticket estão ratificadas, e a ratificação chegou depois delas.** A allowlist `EM_UNIDADE_MENOR` de `db/tests/test_catalogo.py` (*gate* 8) — onde este ticket inscreveu `payment_charges.amount_minor`, `payment_events.valor_minor` e o `valor_minor` da vista `v_payment_events_audit` — foi **ratificada pelo fundador a 2026-11-03**: KAM-172, [`../docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md`](../docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md). Este ticket fundiu **no mesmo dia** da decisão (`94bd634`, `2026-11-03 09:25:39 +0100`) e escreveu as três entradas com a pergunta **escrita como aberta** no próprio `EM_UNIDADE_MENOR`; o ADR-L008 cobre-as, e nenhuma se mexe. **A ordem dentro do dia é INDICIO e não se afirma:** o *commit* tem hora, a decisão tem data e não hora, e nada no registo as ordena — o que vale sem a ordem é o que importa, e basta. O que fica a valer para quem vier depois: coluna nova em `platform` com `*_minor` paga a sua linha com a razão pela qual **não é um saldo**, em `bigint` e nos **dois sentidos**; `saldo`, `balance` e `_kz` continuam proibidos **sem excepção**, com canário que o prova.
- `order_id` e `billing_cycle_id` ficam sem FK nesta migração (`CHECK` de exclusividade mantém-se); KAM-055 acrescenta a FK para `orders_mirror` e KAM-059 a de `billing_cycles`.
- **Fluxo do worker** (`../docs/tecnica/04` §5.1): `inbox.insert → verifyCallback → 2xx`; o worker avalia G2–G7 e escreve `pagamento_recebido` + `pagamento_confirmado`/`pagamento_divergente`. Sem assinatura (OPG, EMIS) o callback é só dica e segue `status_pull`.
- O tipo de evento de *outbox* sai de uma tabela de mapeamento `(tipo_evento, authn_method) → tipo EVT` que KAM-055 preenche; aqui testa-se com um mapeamento de teste.
- O *handler* corre no serviço `pay` atrás do GWY; o papel `kamba_pay_hooks` (estreito) resolve `webhook_token → account` antes de existir contexto de tenant.
- RLS `FORCE` em `payment_charges` e `payment_events` (`tenant_id`); o *inbox* não tem `tenant_id` e só é acessível pelo papel estreito.

### Testes Requeridos
- Unit: `next_state`, cálculo de `row_hash`, canonicalização de campos.
- Integração (Postgres real): privilégios, *triggers*, concorrência (20 sessões), RLS cruzada, migração reversível.
- Propriedade: reconstrução do estado a partir do ledger.
- Contrato: o *handler* contra os casos de `../docs/tecnica/04` §3.5 com um `FakeProvider` (HMAC adulterado, duplicado ×10, fora de ordem).
- Carga: ack p99 do *handler*.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] Pagamento só por evento autenticado: não existe caminho de código que escreva `paga` fora de `append_payment_event`.
- [x] Idempotência: duplicados ×10 produzem 1 efeito; chaves `provider_event_id` e `sequencia` testadas.
- [x] Isolamento: RLS `FORCE` e caso novo na suite cruzada; `SECURITY DEFINER` apenas em `append_payment_event`, na lista aprovada.
- [ ] Privacidade: `payload` redigido sem PII; referências mascaradas em logs; sem telefone.
- [ ] Observabilidade: métricas `callback_ack_ms`, `payment_events_total{tipo}`, alerta de HMAC inválido por conta.
- [ ] Migração reversível; cobertura ≥ 90%; dois revisores.

### Verificação dos Critérios de Aceitação

Uma linha por critério, com a prova nomeada. Os comandos e os resultados estão no
corpo do PR; o que esta tabela dá é **onde** a propriedade se mede.

| # | Critério | Estado | Prova |
|---|---|---|---|
| 1 | `UPDATE`, `DELETE` e `TRUNCATE` em `payment_events` falham como `kamba_app` e como `kamba_ops` (3 testes); `INSERT` directo como `kamba_app` falha por permissão e `SELECT * FROM append_payment_event(...)` funciona | **satisfeito, com uma substituição declarada** | `TestPrivilegiosDoLedger` e `TestNemOSuperutilizador` em `db/tests_pagamentos/test_porta.py`, contra PostgreSQL real. **O `kamba_ops` não existe nesta base** — os papéis são oito (`db/bootstrap.py`) e o dicionário §3.2 registra `kamba_ops` como **variante proibida**, pelo que criá-lo contradizia o canon. As três mutações correm contra `kamba_app`, `kamba_batch` (que tem `BYPASSRLS`, e é portanto o mais forte dos três) e `kamba_audit` (o papel de ops que existe), e **mais uma via que o critério não pede**: o superutilizador, que é o único que os `REVOKE` não prendem e que o `deny_mutation` recusa na mesma. O `INSERT` directo dá `42501` **antes** de qualquer `CHECK`, e a linha do ensaio é deliberadamente válida em tudo o mais para que a razão da recusa seja o privilégio e não o conteúdo. A chamada legítima é `SELECT * FROM`, como o critério escreve, em `test_a_porta_funciona_como_app` |
| 2 | Inserir `pagamento_confirmado` com `authn_ok=false`, ou com `decisao='rejeitada'`, é rejeitado pelo `CHECK`; a função recusa também se `valor_minor ≠ amount_minor` ou `account_id` difere da cobrança, mesmo que o `CHECK` passe | **satisfeito** | **As duas metades têm ensaio separado, e é o que o «mesmo que o `CHECK` passe» exige.** A função: `TestNaoHaSegundaPorta`, com `test_a_porta_recusa_confirmar_sem_autenticacao`, `test_a_porta_recusa_valor_diferente_do_da_cobranca` e `test_a_porta_recusa_conta_diferente_da_da_cobranca` — esta última é a mais importante das três, porque **nenhum `CHECK` a pode fazer**: nenhuma restrição de `payment_events` consegue ler o `amount_minor` da `payment_charges`. O `CHECK` sozinho: `TestOsCheckMordemSozinhos`, com `INSERT` directo pelo superutilizador, que é a única via que resta — sem `INSERT` concedido, nenhum caminho da aplicação chega lá, e um `CHECK` nunca exercitado é um `CHECK` que ninguém sabe se está a valer. Inclui o `humano_exige_actor` e o `payment_events_um_sujeito`, com a sonda positiva de cada um. **E uma terceira recusa que a revisão adversarial mediu como contornável:** `p_account_id => NULL` saltava o G2 **em silêncio** — `NULL <> x` avalia a `NULL`, o `IF` não disparava, e o `INSERT` gravava o `account_id` da própria cobrança, pelo que não havia `NOT NULL` que o apanhasse depois. O predicado é agora `IS NULL OR IS DISTINCT FROM`, e o nulo tem ensaio (`TestOG2ComContaNula`) — e não era hipotético: o recibo `token_desconhecido` do `hooks.ts` grava `accountId: null` |
| 3 | Dois eventos do mesmo `(provider, account_id, referencia, tipo_evento)` recebem `sequencia` 1 e 2; 20 chamadas concorrentes sobre a mesma cobrança produzem sequências 1..20 sem lacunas (`FOR UPDATE`) | **satisfeito** | `TestSequenciaSobConcorrencia` em `test_concorrencia.py`: vinte ligações próprias (na mesma ligação a segunda tomada da tranca é concedida de imediato e não haveria disputa), `sequencias == list(range(1, 21))` e **zero** falhas — com a tranca na cobrança elas esperam-se umas pelas outras em vez de colidirem. **Mais um passo de canário**, que é o que torna o resto honesto: copia a função para uma com outro nome **sem** o `FOR UPDATE`, repete as vinte, e exige que colidam com `23505`. Sem ele, em série o `1 + count(*)` dá sempre o número certo e o critério ficava por provar. E `test_duas_sequencias_de_tipos_diferentes_contam_a_parte`, porque um `count(*)` sobre a cobrança inteira — o erro fácil de escrever — passava o primeiro ensaio |
| 4 | O mesmo `provider_event_id` num `pagamento_recebido` duas vezes produz 1 linha no ledger e o recibo `duplicado` (G7); a mesma referência em duas contas (entidades) distintas é aceite | **satisfeito** | `TestIdempotenciaDaEntrega`: a segunda chamada dá `23505` e o ledger fica com **uma** linha; `test_dez_duplicados_dao_um_efeito` é a caixa do DoD («duplicados ×10 produzem 1 efeito») medida com dez tentativas. A mesma referência em duas contas: `test_a_mesma_referencia_em_duas_contas_e_aceite`, que é o defeito que o §6.1 corrige no documento 11 (uma referência Multicaixa é Entidade + Referência, `evidencia/E2` §2). O recibo `duplicado` é decidido por `reciboDoVeredicto` em `packages/core-ts/src/pagamentos/gates.ts` e medido em `pagamentos.gates.test.ts`; **a escrita dele no `payment_callbacks_inbox` é do adaptador do *worker*, que não existe** — ver a nota de escopo abaixo |
| 5 | `next_state` cobre todas as transições de `../docs/tecnica/04` §7.1 e rejeita as restantes; um teste de propriedade com 1 000 sequências aleatórias válidas mostra `rebuild_charge_state(c)` igual a `payment_charges.estado` | **satisfeito** | `TestNextState` transcreve as arestas do diagrama do §7.1 e afirma as três coisas: que todas estão, que os seis factos sem transição devolvem o mesmo estado, e que **todo o resto do produto `(estado × tipo × decisão)`** dá `NULL` — é esta terceira que o «rejeita as restantes» pede, e uma máquina que devolvesse o estado de entrada por omissão passava as duas primeiras. Mais `test_para_paga_ha_um_caminho_so`, varrido sobre o produto inteiro. A propriedade: `TestReconstrucao`, **mil** sequências com semente fixa, cada uma uma cobrança com os seus eventos, e a reconstrução comparada com a projecção **e** com o que o §7.1 diz — mais a asserção de que as mil chegam a pelo menos cinco estados distintos e uma delas a `paga`, porque mil cobranças que nunca saíssem de `iniciada` concordavam sempre e o ensaio não media transição nenhuma |
| 6 | `row_hash = sha256(prev_hash ‖ campos canónicos)`; alterar um byte com superutilizador num teste faz o *job* `verify_ledger_chain` falhar e alertar; a cabeça da cadeia é exportada diariamente via `StorageProvider` (*fake* em teste) | **satisfeito** | A fórmula: `TestFormulaDoElo` varre cada posição de argumento, e **isso não bastava** — a revisão adversarial mostrou que o ensaio era tautológico quanto à pergunta que a frase faz: varrer os argumentos da função só cobre os campos que já estão no elo, e **nove** das vinte e três colunas estavam de fora (o `actor_id`, o `actor_kind`, o `motivo`, o `ocorrido_at`, o `tenant_id`, o `order_id` e o `billing_cycle_id` entre elas). Medido: adulterar qualquer uma delas devolvia **zero** elos partidos. O elo cobre agora **vinte e duas** colunas, as quatro que ficam fora têm razão escrita no `FORA_DO_ROW_HASH`, e o ensaio que conta é o `test_toda_a_coluna_esta_no_elo_ou_declarada_fora`, que compara a lista com o **catálogo** nos dois sentidos — uma coluna nova que ninguém ponha no elo nem declare fora dele falha. Mais o `TestAFormulaRecalculaEmPython`, que recalcula o `sha256` **fora** do PostgreSQL como o ledger de auditoria da `0006` faz: sem ele a fórmula só era comparada consigo própria, porque o verificador chama a mesma função que a escreveu. A detecção: `test_um_byte_alterado_com_superutilizador_e_apanhado`, pela única via de adulteração que existe (o `deny_mutation` recusa a todos, pelo que o ensaio tem de desligar o *trigger* como dono), e `test_uma_linha_removida_no_meio_e_apanhada_pelo_encadeamento`, que a fórmula sozinha não veria. O `ENABLE ALWAYS` dos **três** *triggers* lê-se do catálogo em **dois** sítios, e os dois fazem falta: o `TestTriggersSaoAlways` mede o estado **vivo** no fim da suite (apanha quem desligue um *trigger* e se esqueça de o repor) e o `TestDowngradeDa0029` mede-o depois de **reaplicar a revisão ele próprio** (apanha quem lhe tire o `ALTER`). Só o segundo existia por boa razão — ver «Nove mutações, e a que sobreviveu» abaixo. A âncora: `pagamentos.ledger.test.ts` com armazenamento *fake*, e **`test_sem_ancora_nao_e_conforme_mesmo_com_a_cadeia_intacta`** é o ensaio mais importante desse ficheiro — uma cadeia de *hashes* detecta adulteração de quem não a recalcula, e o que a torna uma prova contra quem tem a base é a cabeça estar fora do *host* |
| 7 | Token desconhecido devolve 404 uniforme com recibo `token_desconhecido`; HMAC inválido devolve 401, deixa `payment_callbacks_inbox.estado='hmac_invalido'` e `sig_ok=false` e escreve 0 linhas em `payment_events`; o corpo é durável antes do 2xx; ack p99 < 500 ms a 50 pedidos/s | **satisfeito, com um limite nomeado** | `pagamentos.hooks.test.ts`. O 404: medido com **quatro** *tokens* diferentes, mesmo corpo e mesmo recibo — um corpo que distinguisse «mal formado» de «não existe» era um oráculo —, e a entrega grava-se com `account_id` nulo **antes** do 404, que é o que torna um varrimento de *tokens* auditável. **Uniforme na forma, e não no tempo:** a primeira versão do módulo afirmava «o mesmo corpo e o mesmo tempo», e a revisão adversarial apanhou que nada no caminho iguala os tempos — o do *token* desconhecido não passa pelo `verifyCallback` e é mais curto. A afirmação foi corrigida em vez de a medição ser inventada. O 401: `estado='hmac_invalido'` e `authn_ok=false` (**`sig_ok` é o nome substituído**: o dicionário §3.4 põe-no na coluna «Substitui» e o canónico é `authn_ok`), e **zero** escritas no ledger como propriedade do caminho — nada é encaminhado, pelo que o *worker* nunca é chamado. O «antes do 2xx» mede-se pela **ordem** das chamadas às portas, comparada com a do §5.1: `test_o_corpo_e_gravado_antes_de_verificar_e_antes_do_2xx`. **O limite:** o p99 é medido no caminho deste módulo, a 50 pedidos/s em lotes de um segundo, com as portas a custarem 1 ms cada — **não** num *endpoint* HTTP, porque `services/pay/` não existe nesta árvore (dívida 148). O alvo do §14 mede-se no GWY com a métrica `callback_ack_ms`, que este módulo emite em todos os códigos de resposta. **E há um prazo**, que a revisão adversarial pediu: um `verifyCallback` que nunca resolvesse pendurava o pedido indefinidamente, e o módulo não tinha `timeout`, `AbortSignal` nem `Promise.race` em sítio nenhum. São 300 ms (*proposta*, calibra-se com um adaptador real no KAM-056), e esgotado o prazo a entrega fica em `erro` e a resposta é **200** — o corpo já é durável e um 5xx geraria reentregas do que já ficou. **E um quarto código, que o §5.1 não tem e que fica declarado:** `413` para um corpo acima de 64 KiB, e é o único caso em que a entrega **não** fica gravada |
| 8 | A escrita no `events_outbox` ocorre na mesma transacção: uma falha forçada no *outbox* reverte também a linha do ledger | **satisfeito** | `TestOutboxNaMesmaTransaccao`, com a sonda positiva primeiro (o caminho que funciona, antes de o partir) e a falha forçada por um *trigger* `BEFORE INSERT` sobre o `events_outbox` criado e apagado pelo próprio ensaio, com asserção de que caiu. **A primeira versão forçava-a com um `payload` que tinha padrão de telefone, contando com a guarda de PII do `evt_emitir`, e não funcionou** — o `payload` que vai para o *outbox* não é o do evento, é uma projecção que a função constrói. Desse achado saiu a guarda de PII da própria porta (`TestPrivacidadeDoPayload`). E `test_sem_mapeamento_nao_ha_evento_de_dominio_e_o_ledger_grava`, que é o que deixa esta revisão fundir antes do KAM-055 |
| 9 | A vista `v_payment_events_audit` expõe `callback_hmac_ok = (authn_method='hmac_sha256' AND authn_ok)` para os alvos de `../docs/tecnica/08` §14 | *(caixa vazia)* — **não satisfeito, e a medição está entregue** | A vista existe, com `security_invoker = true`, e expõe o predicado — **com a coluna chamada `authn_hmac_ok`**. Os dois nomes que o critério escreve estão os dois na coluna «Substitui» do dicionário §3.4, e são dois casos diferentes: `hmac_sha256 → hmac` é uma tradução que a emenda 1.13 (KAM-141, linha 4) escreveu **com este ticket nomeado**, e está feita; `callback_hmac_ok` é **variante de nível 1** do *gate* 3b e não se traduz, porque é o nome da coluna que o critério pede. **Medido:** a primeira versão da revisão escrevia-o e o `canon_lint` devolveu dois achados `[variante]` (na vista e no `COMMENT ON`), porque o nível 1 varre todos os tokens, incluindo o interior das cadeias. Nenhuma entrada de `canon/extensoes.yaml` o salva — o leitor recusa-a com erro de configuração —, e o `ci/canon-allow.yaml` cobre só a superfície `documentos`, que é porque o nome **pode** aparecer no §6.1 do doc 04 e não numa migração. Mudar o que o *gate* 3b aceita é alteração de regra de bloqueio: a decisão é do fundador, e o que este ticket entrega é a medição e não a implementação |

#### Verificação do Definition of Done

| Caixa | Estado | Nota |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | *(caixa vazia)* — **não satisfeito** | Oito dos nove. O critério 9 não se cumpre porque o nome que ele pede é proibido por uma fonte acima dele, e a medição está na linha 9 acima. Dois critérios ficam **satisfeitos com limite declarado** e não escondido: o `kamba_ops` do critério 1 não existe e está registado como variante proibida, e o p99 do critério 7 é do caminho do *handler* e não de um *endpoint* |
| Pagamento só por evento autenticado: não existe caminho de código que escreva `paga` fora de `append_payment_event` | **satisfeito** | **Provado por privilégio e não por `grep`** — e **a revisão adversarial mostrou que a prova estava incompleta, e que esta caixa estava marcada em falso.** Fica escrito porque é o achado mais grave do ticket.

A primeira versão tentava **quatro** vias: `UPDATE` directo na cobrança, `INSERT` no ledger, a porta com `authn_ok=false`, a porta com `decisao='rejeitada'`. **Faltava a quinta, que é a óbvia:** o `kamba_app` tem `INSERT` na `payment_charges`, e o `estado` tinha domínio mas não tinha valor inicial imposto — pelo que um `INSERT … VALUES (…, 'paga', …)` passava, com o contexto do próprio tenant, e deixava uma cobrança **paga com zero eventos no ledger**. Qualquer um dos dez estados entrava, incluindo o `reembolso_pendente` que este bloco declara inalcançável. **E o único detector excluía-a por construção:** o *job* do §8 compara a projecção com a reconstrução só para cobranças **com** eventos, e uma cobrança forjada não tem nenhum.

Conflui-se «ninguém tem `UPDATE`» com «não há caminho para escrever `paga`», e as duas coisas não são a mesma. Fecha-a o *trigger* `payment_charges_nasce_iniciada` (`BEFORE INSERT`, `ENABLE ALWAYS`), e não um `CHECK` — um `CHECK (estado = 'iniciada')` é avaliado em toda a versão da linha e impedia a própria projecção de mover o estado. O ensaio é o `TestAQuintaVia`, com os nove estados não-iniciais, as duas colunas de resultado (`motivo_falha` e `requer_humano`, que também nasciam preenchíveis), a sonda positiva e o caso que mostra que a porta **continua** a mover o estado.

`TestNaoHaSegundaPorta` cobre as outras quatro e exige o `SQLSTATE` de cada recusa, com a via que **passa** ao lado. **Ninguém tem `UPDATE` em `payment_charges`**, o `kamba_batch` incluído. Do outro lado, `test_nenhuma_escrita_e_um_update_de_estado` em `pagamentos.gates.test.ts` afirma que nenhum veredicto do *worker* produz um estado — só tipos de evento |
| Idempotência: duplicados ×10 produzem 1 efeito; chaves `provider_event_id` e `sequencia` testadas | **satisfeito** | Critérios 3 e 4 acima. O `payment_events_entrega_uq` é **parcial com o tipo no predicado**, que é o §6.2 à letra, e `test_o_mesmo_provider_event_id_noutra_conta_e_aceite` mostra porque é que a conta faz parte da chave: dois facilitadores podem numerar as entregas a partir de 1 |
| Isolamento: RLS `FORCE` e caso novo na suite cruzada; `SECURITY DEFINER` apenas em `append_payment_event`, na lista aprovada | **satisfeito** | `rls.enable_tenant_rls` nas duas tabelas com `tenant_id`, com as bandeiras lidas do catálogo em `TestRlsDasDuasTabelas` e a sonda positiva antes das leituras cruzadas. **O ensaio que este ticket acrescenta ao que o X-03/X-04 já fazem** é `TestADefinerSobRls`: a porta corre `SECURITY DEFINER` e **não** contorna o `FORCE` — uma chamada com o contexto de B sobre uma cobrança de A recusa, e o ledger de A fica vazio. É a única forma de medir a afirmação central do `db/rls.py`, que nomeia este ticket como credor. `SECURITY DEFINER` **uma só**, e chegar lá custou **três** tentativas na resolução do `webhook_token` — as duas primeiras falharam por razões opostas, e fica escrito porque a terceira só se entende contra elas. **(1)** `SECURITY DEFINER` sozinho **não funciona**: corre como o dono, que é `NOBYPASSRLS`, e o `FORCE` prende-o — zero linhas sem contexto de tenant. É a lição que o `db/rls.py` escreve e que nomeia este ticket como credor, e re-aprendi-a aqui. **(2)** `SECURITY INVOKER` mais política `USING (true)` mais `GRANT` por coluna **funciona e abre um buraco**, que a revisão adversarial mediu: com `SELECT` na coluna do *token* — que o `INVOKER` obriga a ter, porque a função a compara — o papel fazia `SELECT webhook_token FROM payment_accounts` e **enumerava** o segredo de callback de todas as PMEs (36 linhas, 36 *tokens*, sem contexto). **(3)** A política carrega o predicado: `USING (webhook_token = NULLIF(current_setting('app.webhook_token', true), ''))`. A expressão de uma política é do **dono** da tabela e os privilégios de coluna conferem-se contra as colunas da **consulta**, pelo que o papel compara a coluna do segredo **sem ter `SELECT` nela** — sem *token*, zero linhas; com um, uma. Sem enumeração e sem segunda `DEFINER`. Medido: `TestOPapelEstreito` |
| Privacidade: `payload` redigido sem PII; referências mascaradas em logs; sem telefone | *(caixa vazia)* — **parcial** | **A primeira metade está feita e é uma barreira**, não uma convenção: a porta recusa um `payload` ou um `motivo` com padrão de telefone, com os **mesmos** dois padrões do `evt_emitir` da `0004` e um ensaio de paridade que lê os dois corpos do catálogo (`TestPrivacidadeDoPayload`). Num ledger *append-only* isto conta mais do que noutra tabela: um telefone que entre não sai, nem com `UPDATE`. A `payment_callbacks_inbox` guarda o corpo cru — tem de guardar, porque o HMAC é sobre ele — e os cabeçalhos passam por uma lista de **inclusão**. **A segunda metade não está feita:** «referências mascaradas em logs» exigiria um redactor de `referencia` no logger, e este ticket não escreve registo nenhum — o `log_policy` do gate 2 passa a 0 achados porque nenhum ficheiro novo escreve fora do logger, o que é diferente de mascarar. Fica para quem escrever o serviço `pay` |
| Observabilidade: métricas `callback_ack_ms`, `payment_events_total{tipo}`, alerta de HMAC inválido por conta | *(caixa vazia)* — **parcial** | O `callback_ack_ms` é **emitido** pelo *handler* em todos os códigos de resposta, com ensaio (`test_a_metrica_do_ack_e_emitida_em_todos_os_codigos`), e o alerta de HMAC inválido por conta também (`ALERTA_HMAC`, com o `account_id` e o `provider`). O `payment_events_total{tipo}` está **declarado e não emitido**: quem o emitiria é o *worker*, por tipo de evento escrito, e o *worker* não existe. **E há um quarto alerta**, que a revisão adversarial tornou necessário: o `pay_ledger_leitura_falhou`, para uma **leitura** do *job* que não correu. É diferente dos outros — eles dizem «a cadeia está partida» e este diz «não se conseguiu verificar» —, e confundi-los era o pior dos dois mundos: um *job* que não corre a parecer um *job* que passou. E nenhum dos quatro chega a um colector: as portas `medir` e `alertar` são opcionais e nesta árvore não há quem as ligue, porque não há `services/pay/` |
| Migração reversível; cobertura ≥ 90%; dois revisores | *(caixa vazia)* — **não satisfeito** | **Duas de três.** A reversibilidade é o `TestDowngradeDa0029`, que afirma as três partes que o ciclo do *gate* 8 é cego para ver: que o papel **não** se apaga, que a política `pay_hooks_token` sobre a tabela da `0027` **cai** (deixá-la pendurada estraga o `downgrade` da revisão **anterior**), e que a função `assert_beneficiary` fica. A cobertura: `hooks.ts` 98,5%, `ledger.ts` 100% e `gates.ts` medido no mesmo LCOV, contra o mínimo de 90% do estrato `critico`, que o `ci/thresholds.yaml` já aplicava a `*/pagamentos/*` desde o KAM-052 — nenhum padrão novo. **Os dois revisores não se cumprem:** nesta fase funde-se com CI verde sem esperar revisão humana (instrução do fundador), e uma revisão adversarial é evidência e não um revisor. Fica dito, como no KAM-052, que este é um ticket **P0 de dinheiro** e que o critério pede dois revisores **explicitamente** — é informação que o fundador pode querer usar para abrir excepção |

#### O que fica para os tickets que este bloqueia

Nomeado porque uma lacuna nomeada é informação e uma lacuna silenciosa é um
defeito à espera:

* **o processo do *worker*.** A parte **avaliar** do §5.1 está feita e medida —
  `avaliarGates` em `gates.ts`, G2 a G7 pela ordem do §5, com dezanove ensaios —
  e a parte **orquestrar** não: ler o *inbox*, abrir a transacção, chamar a
  porta por cada escrita do veredicto, marcar o recibo. É I/O e vive no serviço
  `pay`, que **não existe nesta árvore** (dívida documental 148, aberta pelo
  KAM-052). O que não fica frouxo é a barreira: mesmo um *worker* mal escrito
  não consegue escrever `paga` sem passar pela porta;
* **as duas FK** — `payment_charges.order_id` → `orders_mirror` (KAM-055) e
  `billing_cycle_id` → `billing_cycles` (KAM-059). O `CHECK` de exclusividade
  fica nesta revisão, porque não depende de tabela nenhuma;
* **o conteúdo da `payment_outbox_map`** (KAM-055). A tabela fica **vazia**, e um
  `tipo_evento` sem linha nela não produz evento de domínio e o ledger grava-se
  na mesma — é isso que deixa esta revisão fundir primeiro;
* **o `EXECUTE` da porta para o `kamba_batch`.** A reconciliação do §8 vai
  precisar dele (KAM-056); nesta revisão não há quem a chame como lote, e um
  privilégio sem chamador é uma porta aberta sem ninguém a usar;
* **o G8** (limites da confirmação humana, M-2..M-5) é do **KAM-054**: só se
  aplica ao `ManualProvider` e os tectos que ele mede são *propostas* a calibrar
  no Piloto. Avaliá-lo aqui era inventar os valores.

#### Três divergências com o `../docs/tecnica/04`, e o que se fez com cada uma

1. **O quarto valor de `authn_method` era uma pergunta escrita para este
   ticket**, e fica respondida. O §6.2 fixa quatro valores no `CHECK` e anota que
   o `sistema` «não tem contrapartida no dicionário» e que «a decisão pertence a
   quem escrever o KAM-053». A resposta é que a pergunta do documento — «um
   pagamento confirmado pela própria plataforma é `consulta` ou exige um valor
   novo?» — tem a premissa errada: um `pagamento_confirmado` **nunca** é
   `sistema`, porque a restrição `confirmar_exige_autenticacao` não o inclui e a
   base recusa (medido em `test_o_check_recusa_confirmado_autenticado_por_sistema`).
   O `sistema` serve os factos de ciclo de vida que não vêm de fora, e entra no
   dicionário §3.4 pela emenda 1.54.
2. **Três arestas do §7.1 não têm evento que as accione, e ficam recusadas.** A
   `paga --> reembolso_pendente: disputa` não tem tipo de evento nos dezassete do
   §6.2 — abrir um caso é `refund_cases` (§6.3, KAM-054) —, e a divergência a
   partir de `aguarda_cliente` e de `pendente_confirmacao` não está desenhada,
   embora o G4 possa bater nos dois estados. O critério 5 manda seguir o §7.1 à
   letra, e é o que o `next_state` faz; a lacuna é do §7.1 e está em
   `../docs/dividas-documentais.md`.
3. **«Confirmação humana auditada» é um `authn_method`, não um tipo de evento.**
   O §7.1 desenha `pendente_confirmacao --> paga: confirmacao humana auditada`, e
   ler a frase como um tipo de evento (o `confirmacao_manual_registada`) criava um
   segundo caminho para `paga` que **não passa** pela restrição
   `confirmar_exige_autenticacao` — a segunda porta que este ticket existe para
   não ter. Para `paga` há um caminho só, varrido sobre o produto inteiro em
   `test_para_paga_ha_um_caminho_so`.

#### Uma divergência com o §6.2 que é aditiva, e um *trigger* que se antecipa

* **`CONSTRAINT payment_events_hashes_sha256`** não está no §6.2: exige que os
  três *hashes* tenham 32 octetos. É um desvio **aditivo**, pela razão da `0006`
  — sem ele um `prev_hash` de outro comprimento passava, e a verificação da
  cadeia deixava de poder afirmar que compara `sha256` com `sha256`.
* **O `CREATE TRIGGER payment_charges_beneficiario` liga-se nesta revisão**, e o
  comentário da `0027` escreve que seria do KAM-055. É a única coisa que contraria
  o que ficou escrito, e a razão é que a `payment_charges` nasce **aqui**: deixar
  uma tabela de dinheiro dois tickets sem a guarda G-1 do §10.4 não é «não
  alargar o escopo», é tirar uma barreira que já existe, construída e testada,
  por causa de uma frase escrita quando se supunha que a tabela nasceria mais
  tarde. O que fica para o KAM-055 é o que ele tem de ser: a FK para
  `orders_mirror`.

#### A revisão adversarial reprovou o ramo, e o que ela mudou

Uma revisão independente, por um agente que não viu o raciocínio de quem
escreveu o ramo. Procurou **doze** classes de defeito, devolveu **doze achados**
— onze confirmados por medição — e **reprovou a fusão** com três `must fix`. Os
números e as sondas estão no corpo do PR; o que esta secção dá é o que mudou no
ticket por causa deles.

Os três `must fix` tinham a mesma assinatura, e é a que esta casa nomeia como o
seu modo de falha: **a caixa estava marcada e o ensaio que a apoiava media outra
coisa.**

| # | O achado | O que estava marcado | O que se fez |
|---|---|---|---|
| 1 | O `kamba_app` cria uma cobrança **já em `paga`**, com zero eventos no ledger: o `estado` tinha domínio mas não tinha valor inicial imposto | «não existe caminho de código que escreva `paga` fora de `append_payment_event`», provado com **quatro** vias | o *trigger* `payment_charges_nasce_iniciada` e o `TestAQuintaVia`. Ver a caixa do DoD acima |
| 2 | As **duas vistas** não tinham `GRANT`: `42501 permission denied for view`. A âncora externa do §8 falhava na primeira execução real, e o `kamba_audit` não abria a vista que existe para ele. E o *job* **lançava** contra a sua própria docstring quando o `rebuild_charge_state` levantava, deixando a âncora por escrever | «a cabeça da cadeia é exportada diariamente via `StorageProvider`» | `GRANT SELECT` nas duas, com o `TestPrivilegiosDasVistas` a lê-las **como papel** — que é a única forma de o medir, e que nenhum ensaio fazia (os de catálogo inspeccionam como administrador e o `test_privilegios.py` não tem matriz para vistas). E cada leitura do *job* dentro do seu `try`, com o alerta `pay_ledger_leitura_falhou` e `conforme` falso |
| 3 | **Nove** das vinte e três colunas do ledger fora do elo, o `actor_id` e o `tenant_id` incluídos: reescreviam-se sem a cadeia dar por nada | «`row_hash = sha256(prev_hash ‖ campos canónicos)`», com um ensaio que varria «cada posição» | o elo cobre **vinte e duas** colunas; o `test_toda_a_coluna_esta_no_elo_ou_declarada_fora` compara a lista com o **catálogo** nos dois sentidos; e o `TestAFormulaRecalculaEmPython` recalcula o `sha256` fora do PostgreSQL, como a `0006` faz |

Os `should fix`, todos corrigidos no mesmo PR: o `p_account_id => NULL` a saltar
o G2 (critério 2 acima); o `pagamento_orfao` que a sua própria tabela torna
impossível de escrever (dívida 169); a enumeração do `webhook_token` (caixa do
isolamento acima); a célula do §3.42 a dizer `SECURITY DEFINER` onde o código
diz `INVOKER`, e a do §3.4 a afirmar no mesmo parágrafo que o quarto valor está
decidido e que fica por decidir (emenda 1.55 do dicionário); e a afirmação de
que o 404 é uniforme **no tempo**, que nada no módulo garantia (critério 7).

Dos `nice to have`: o `confirmacao_manual_revertida`, recusado em todo o produto
`(estado × tipo × decisão)`, entra na dívida 166, e o código `413` fica
declarado. O que **não** se mexeu: a revisão leu o *trigger* `assert_beneficiary`
ligado nesta revisão como «defensável» e não como achado, e confirmou que não há
colisão de ficheiros com o PR #102.

#### Nove mutações, e a que sobreviveu

As barreiras desta revisão têm agora **catorze** mutações em `db/mutacoes.py`,
uma por barreira, e correm na suite `tests_pagamentos`. Na primeira execução
**oito foram apanhadas e uma sobreviveu**: «os *triggers* do ledger deixam de ser
`ALWAYS`» — isto é, a revisão passava a criá-los sem o `ALTER`, e a suite inteira
continuava verde.

A causa não era a mutação: era um ensaio a escrever o estado que outro ensaio
afirma. O `TestCadeiaEscritaPelaPorta` tem de **desligar** o
`payment_events_imutavel` para adulterar um byte, e repunha-o com `ENABLE
ALWAYS` **fixo**; o `TestTriggersSaoAlways`, que corre depois no mesmo ficheiro,
lia um `A` escrito por esse vizinho. Medido numa cópia da árvore: a suite deu
código de saída **0**, e um diagnóstico impresso no próprio ensaio mostrou
`[('payment_events_imutavel', 'A'), …]` numa base onde o `ALTER` nunca correu.

Corrigiu-se nas duas pontas: o restauro repõe **o que estava** (`_desligar_trigger`
devolve o `tgenabled` anterior), e a asserção passou a existir também no
`TestDowngradeDa0029`, **que reaplica a revisão ele próprio** — e aí o que o
catálogo diz foi escrito pela migração e por mais nada.

**É a razão de as mutações existirem**, e vale escrevê-la: os ensaios estavam
verdes, o `ENABLE ALWAYS` estava no diff, e a leitura do código não distinguia
este caso do caso bom. O que o distinguiu foi tirar a barreira e exigir que
alguém desse por isso. Hoje as catorze são apanhadas.

#### Um achado sobre uma barreira que não se consegue exercitar

O `WITH CHECK` da política `tenant_iso` sobre a `payment_charges` **é
inalcançável** pelo `kamba_app`, e as duas formas de o tentar estão medidas em
`test_o_with_check_da_cobranca_e_inalcancavel_e_isso_fica_medido`: com o contexto
de A e o `tenant_id` de B, o *trigger* `assert_beneficiary` compara os dois e
recusa; com o contexto de C e o `tenant_id` de A, ele não vê a conta e recusa. Nos
dois casos o *trigger* corre `BEFORE INSERT` e ganha.

Não é um defeito — são duas barreiras independentes e a primeira dá a mensagem
mais útil —, mas **é preciso que alguém o saiba**: quem ler «a tabela tem
`tenant_iso` com `WITH CHECK`» supõe que há um ensaio a prová-lo, e não há nesta
tabela. Onde o `WITH CHECK` **é** medido é no `payment_events`, pela porta
(`TestADefinerSobRls`).

### Handoff para Claude Code

```text
És o executor do ticket KAM-053 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-053) e
docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md (§5, §6.1, §6.2, §7, §8) e docs/tecnica/06 §6.1.
Objectivo: tabelas payment_charges, payment_callbacks_inbox e payment_events (DDL de §6.2, sem copiar o doc 11),
imutabilidade por REVOKE + triggers, função SECURITY DEFINER append_payment_event (FOR UPDATE, sequencia,
cadeia de hashes, projecção de estado, outbox na mesma transacção), next_state, rebuild_charge_state,
job verify_ledger_chain e o handler POST /hooks/pay/{provider}/{token} que grava no inbox antes do 2xx.
- Nunca UPDATE/DELETE no ledger; correcções por eventos compensatórios.
- Callback duplicado => 1 efeito. HMAC inválido => 401, inbox hmac_invalido, 0 linhas no ledger.
Não expandas escopo: ManualProvider (KAM-054), eventos de domínio (KAM-055) e ProxyPay (KAM-056) à parte.
Testes: privilégios, concorrência, propriedade (rebuild), RLS, migração. PR com o template (§7).
```

---

## KAM-054 — ManualProvider: confirmação humana auditada, limites e dupla verificação

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | L |
| Dependências | KAM-052, KAM-053, KAM-015, KAM-014, KAM-012 |
| Bloqueia | KAM-055, KAM-059, KAM-060, KAM-096 |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§4, §6.3, §7.2 F-18, §9), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.6), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§4), ADR-013, ADR-015 |

### Contexto
O Piloto arranca sem facilitador: contratos com banco, EMIS e facilitador dependem de papel e de prazos NÃO VERIFICADOS (D4/KAM-103). Até lá cada PME opera no nível T1: o cliente paga fora (transferência, depósito) e o dono confirma. A fraude de comprovativos editados está documentada, pelo que a confirmação é um evento humano auditado e limitado (M-1..M-10), nunca a leitura de uma imagem.

### Objectivo
Implementar o `ManualProvider` (`manual`, e `cod` desligado por omissão), as tabelas `payment_confirmers`, `manual_confirmations` e `refund_cases`, a máquina de confirmação (declaração do cliente → desafio do valor → confirmação → segunda aprovação) e a reversão auditada, com todos os limites lidos de `entitlements.limites`.

### Critérios de Aceitação
- [x] Um `createCharge(manual)` acima de `manual_max_minor` (proposta 50 000 Kz) devolve `REJECTED` e a encomenda não avança; no limite exacto é aceite; o valor é lido do tenant, não de constante.
- [x] Confirmação enviada por um BSUID que não está em `payment_confirmers` activo (incluindo mensagem «sou o dono») não tem efeito e grava `confirmacao_manual_rejeitada`; o cliente nunca confirma (teste com o BSUID do cliente).
- [x] A declaração «paguei» (texto ou imagem) só cria `manual_confirmations.fase='declaracao_cliente'` e a cobrança `pendente_confirmacao`; a imagem é arquivada com `evidencia_ref` rotulado `nao_prova` e nenhum módulo do `ManualProvider` lê o conteúdo da imagem (*lint* de importações de OCR/visão = 0).
- [x] Desafio do valor: o dono escreve o valor visto na sua app; `amount_minor − 1` cêntimo rejeita (`valor_bate=false`, cobrança volta a `emitida`); valor igual avança, sem tolerância.
- [x] Até `manual_dupla_acima_minor` (proposta 20 000 Kz) uma confirmação gera `pagamento_confirmado` com `authn_method='humano_auditado'` e `actor_id` não nulo; acima, a cobrança fica `pendente_confirmacao`, a segunda aprovação pelo mesmo contacto é rejeitada e só a de outro confirmador com `pode_segunda_aprovacao=true` conclui.
- [x] `manual_daily_max_minor` e `manual_max_por_contacto_24h` excedidos retêm a confirmação para ops com `fraud_signals.accao='reter_confirmacao'`.
- [x] Sem resposta do dono em 24 h (omissão, F-18) a cobrança volta a `pendente_confirmacao → emitida` com `confirmacao_manual_rejeitada` e a reserva mantém-se até `expires_at`.
- [x] Reversão: `confirmacao_manual_revertida` + `refund_cases` aberto + cobrança `paga → reembolso_pendente`; nenhuma linha é apagada (a contagem do ledger só cresce).
- [x] A mesma mensagem (`canal_msg_id`) processada 2 vezes produz 1 confirmação; `metodo='cod'` com *opt-in* desligado devolve `REJECTED`.

### Detalhes Técnicos
- **Componentes:** PAY, TLS (classe `money`), HND. DDL de `payment_confirmers`, `manual_confirmations`, `refund_cases` em `../docs/tecnica/04` §6.2–6.3; acrescenta-se `UNIQUE (charge_id, canal_msg_id)` em `manual_confirmations` como índice de idempotência (proposta, regista-se no PR).
- **Máquina:** `emitida → pendente_confirmacao` (declaração) `→ [desafio] → [dupla?] → paga | emitida` (§4.1). Cada fase escreve uma linha em `manual_confirmations` e um evento no ledger por `append_payment_event`.
- Parâmetros em `entitlements.limites`: `manual_max_minor`, `manual_daily_max_minor`, `manual_max_por_contacto_24h`, `manual_dupla_acima_minor`; valores iniciais são **propostas a calibrar no Piloto** (M-10).
- As mensagens ao dono e ao cliente são *templates* parametrizados com o aviso fixo (M-9); o envio é feito por uma porta `OwnerNotifier` (implementada com o outbound, ver riscos). O `sender` é identificado pelo BSUID do canal do tenant (CHR), nunca pelo texto.
- Os eventos `payment.*` para o EVT e a transição da encomenda ficam em KAM-055.

### Testes Requeridos
- Unit: regras M-1..M-5 e M-8 como tabela de casos (valor, papel, limiar).
- Integração: fluxo completo com `FakeOwnerNotifier`; TTL de 24 h com relógio simulado; concorrência de duas confirmações simultâneas.
- Abuso: BSUID forjado, confirmação do cliente, imagem com valor diferente do declarado.
- Idempotência: repetição de `canal_msg_id`; RLS cruzada em `payment_confirmers`.

### Definition of Done
- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] Pagamento só por evento autenticado: o caminho `humano_auditado` exige actor, desafio de valor e limites; nenhum código marca `paga` por imagem ou texto do cliente.
- [x] Idempotência: repetir a mesma confirmação não duplica efeitos; teste de repetição presente.
- [x] Isolamento de tenant e de contacto: RLS em `payment_confirmers` e `manual_confirmations`; caso novo na suite cruzada.
- [x] Privacidade: sem telefone nem texto de mensagem nos logs; contacto por `contact_id`.
- [ ] Observabilidade: `manual_confirmations_total{fase}` e alerta de desvio semanal (`../docs/tecnica/08` §4.6).
- [ ] Dois revisores; cobertura ≥ 90%; limites registados como propostas a calibrar.

### Verificação dos Critérios de Aceitação

Medição de **2026-11-04**, sobre a revisão `0032`, o `packages/core-ts/src/pagamentos/manual.ts`
e as suites `db/tests_pagamentos/test_confirmacao_manual.py` e
`packages/core-ts/tests/pagamentos.manual.test.ts`. Uma linha por critério, com a prova
**nomeada**: o nome do ensaio e a saída da execução, e não a conclusão de quem o escreveu.

Os comandos, e o que cada um devolveu:

| Comando | Resultado |
|---|---|
| `python -m dict_export --root .. --check` | `0` — «`canon/dicionario.yaml` corresponde a `specs/02_…`» |
| `python -m canon_lint --root .. check` | `0` — «conforme»; dicionário v1.59, 688 entradas; **32** ficheiros de migração, 1138 instruções, 66 tabelas, 621 colunas, 504 valores de `CHECK` |
| `python -m canon_lint --root .. canario` | `0` — «10 negativas vermelhas com a mensagem esperada, 10 positivas verdes» |
| `python -m lint_refs / lint_backlog / lint_handoff / lint_contagens --root .. check` | `0` nos quatro |
| `python -m lint_arch --root .. all` | `0` nos cinco passos |
| `pnpm run build` (contentor `node:24.21.0-alpine`) | `0` |
| `pnpm -r run typecheck` | `0` |
| `pnpm --filter @kamba/core-ts run test` | `0` — **1951** ensaios, 1950 verdes, **0** vermelhos |
| `python db/gate_bd.py --suite tests_pagamentos` | `0` — **181** ensaios, `OK` em 199 s (103 do KAM-053 e **78** deste ticket, em `test_confirmacao_manual.py`) |
| `python db/gate_bd.py --suite tests_isolamento` | `0` — 79 ensaios, `OK` (*gate* 6, com o X-05 a descobrir as quatro tabelas novas) |
| `python db/gate_bd.py --suite tests` (subconjunto: inventário, catálogo, privilégios, migração) | `0` — 110 ensaios, `OK` |
| `python tools/coverage_gate.py --root .` | estrato `critico` a **97%** (mínimo 90%); `manual.ts` a **99%** (865/871 linhas), módulo `pagamentos` a 98% |

**O que esta medição não cobre, e diz-se junto com o resultado:** a suite `tests` correu em
**subconjunto** (os quatro módulos que uma migração nova pode partir) e não inteira — a inteira
esgota os 900 s do `gate_bd.py` num ensaio de mutação de `tools/` que nada tem a ver com este
ramo, e isso é o `shortcut:` do alvo `ordem-dos-ensaios` e não um achado deste ticket. O CI
corre-a inteira, com o seu próprio tempo.

| # | Critério | Estado | Prova |
|---|---|---|---|
| 1 | `createCharge(manual)` acima de `manual_max_minor` devolve `REJECTED` e a encomenda não avança; no limite exacto é aceite; o valor é lido do tenant, não de constante | **satisfeito** | `pagamentos.manual.test.ts`, bloco «createCharge — o tecto por pedido». A fronteira mede-se **dos dois lados e no ponto**: `tecto` passa, `tecto − 1` passa, `tecto + 1` dá `ProviderError('REJECTED')`. **O «não de constante» é o caso que vale**: «o tecto vem do tenant e não de constante» corre o **mesmo** montante (600 000 cêntimos) contra dois tenants — um com `manual_max_minor = 500 000` e outro com `50 000 000` — e exige recusa num e aceitação no outro, sem o código mudar. O módulo não tem nenhum dos quatro números: o `PROPOSTAS_DE_OMISSAO` é tabela de documentação, e «nenhuma decisão muda se a tabela de propostas for outra» prova-o. **E `null` recusa** («sem tecto declarado recusa»), que é a leitura fechada do critério 2 do KAM-009 — «sem tecto» não quer dizer «sem limite». Do lado da base há **segunda** barreira, e não é deste ticket: o `KA007` da revisão `0030` (KAM-044) recusa pôr uma encomenda em `pendente_confirmacao` com `total_minor` acima do tecto manual, lido pela **mesma** `platform.ten_tecto` que o `checkCeiling` chama |
| 2 | Confirmação de um BSUID que não está em `payment_confirmers` activo (incluindo «sou o dono») não tem efeito e grava `confirmacao_manual_rejeitada`; o cliente nunca confirma | **satisfeito** | `TestQuemConfirma`, nove ensaios. Recusa: `test_um_bsuid_fora_da_tabela_nao_tem_efeito` (decisão `rejeita`, motivo `sem_confirmador`, cobrança de volta a `emitida`, `confirmacao_manual_rejeitada` no ledger), `test_e_o_pagamento_nao_fica_pago` (**zero** `pagamento_confirmado`), `test_um_confirmador_inactivo_e_como_um_que_nao_existe`. **O cliente**: `test_o_cliente_nunca_confirma_o_seu_proprio_pagamento` — é o ensaio que o critério nomeia («teste com o BSUID do cliente») — e `test_nem_quando_o_cliente_esta_na_tabela_de_confirmadores`, que é a ordem das portas a ser medida: com a tabela consultada **antes** do cliente, um erro de provisionamento deixava-o confirmar o próprio pagamento. **A sonda positiva**: `test_o_dono_confirma_e_a_cobranca_fica_paga`. **O «sou o dono» mede-se por estrutura e não por comportamento**: a `EntradaDaConfirmacao` do `manual.ts` não tem campo nenhum que leve uma afirmação de quem envia, e «sou o dono não é um campo» prende as oito chaves dela — não há por onde o texto entrar, e **não existir** é o que fecha a porta. E `test_o_authn_ok_distingue_quem_falhou_de_o_que_falhou`: um BSUID forjado grava `authn_ok = false`, um confirmador legítimo com o valor errado grava `true` |
| 3 | A declaração «paguei» só cria `fase='declaracao_cliente'` e a cobrança `pendente_confirmacao`; a imagem é arquivada com `evidencia_ref` rotulado `nao_prova` e nenhum módulo do `ManualProvider` lê a imagem (*lint* = 0) | **satisfeito** | `TestDeclaracaoDoCliente`, seis ensaios. O «só»: `test_a_declaracao_nao_confirma_nada` exige que os eventos do ensaio sejam **exactamente** `['confirmacao_manual_pedida']` — não basta o estado estar certo. `test_o_evento_da_declaracao_nao_e_uma_origem_autenticada`: `authn_ok = false`, `decisao = 'informativo'`, motivo `declaracao_do_cliente_nao_e_prova`. O rótulo é **imposto pela base**, não por convenção: `manual_confirmations_evidencia_ck` (`LIKE 'nao_prova:%'`), com `test_a_evidencia_sem_o_rotulo_nao_entra` (23514), a sonda positiva `test_a_evidencia_com_o_rotulo_entra`, e `test_o_rotulo_tem_de_estar_no_principio` — um `LIKE` mal escrito aceitava o rótulo no meio da cadeia. **O *lint* de importações**: «nenhum modulo do adaptador importa OCR ou visao, e ha canario» varre os três módulos do adaptador contra `IMPORTACOES_PROIBIDAS` (13 fragmentos) e dá **zero**; e tem **um canário por fragmento**, nas três formas (estática, dinâmica, maiúsculas), mais a sonda negativa (`node:crypto` e a cadeia `"ocr"` não são achados). Um canário só provava que a varredura apanha **um** nome |
| 4 | Desafio do valor: `amount_minor − 1` cêntimo rejeita (`valor_bate=false`, cobrança volta a `emitida`); valor igual avança, sem tolerância | **satisfeito** | `TestDesafioDoValor`, quatro ensaios, e o cêntimo é medido nos **dois** sentidos: `test_um_centimo_a_menos_rejeita_e_a_cobranca_volta_a_emitida` e `test_um_centimo_a_mais_tambem`, com `valor_bate = false` e estado `emitida`. A sonda positiva é `test_o_valor_igual_avanca`. `test_o_valor_declarado_e_o_veredicto_ficam_no_registo` prende as duas fases por extenso — a declaração e a rejeição, com o valor errado guardado —, que é o M-6. Do lado puro, `pagamentos.manual.test.ts` acrescenta a ausência de tolerância **relativa**: um por mil de 4 000 000 de cêntimos também rejeita |
| 5 | Até `manual_dupla_acima_minor` uma confirmação gera `pagamento_confirmado` com `actor_id` não nulo; acima, a cobrança fica `pendente_confirmacao`, a segunda aprovação pelo mesmo contacto é rejeitada e só a de outro confirmador com `pode_segunda_aprovacao=true` conclui | **satisfeito, com um nome corrigido** | `TestDuplaAprovacao`, sete ensaios. `test_no_tecto_exacto_uma_confirmacao_basta` (a fronteira), `test_acima_do_tecto_a_primeira_nao_paga` (fica `pendente_confirmacao`), `test_a_segunda_pelo_mesmo_contacto_e_rejeitada` (`mesmo_confirmador`), `test_outro_confirmador_sem_a_marca_tambem_nao_conclui` (`sem_segunda_aprovacao`) e a sonda positiva `test_so_outro_confirmador_com_a_marca_conclui`, que prende as três fases pela ordem. `test_o_evento_humano_tem_actor_e_authn_method_manual` prende `authn_ok`, `decisao='aceite'`, `actor_kind='dono'` e o `actor_id` **do segundo** confirmador. **O nome corrigido**: o critério escreve `authn_method='humano_auditado'`, valor que não existe no domínio de quatro do §6.2 e que o `payment_events_authn_method_ck` da `0029` **recusa** — e o lado errado é o critério, porque o §4.2 M-6 escreve `manual`. Dívida documental **183**, emenda 1.60 do dicionário (§3.45) |
| 6 | `manual_daily_max_minor` e `manual_max_por_contacto_24h` excedidos retêm a confirmação para ops com `fraud_signals.accao='reter_confirmacao'` | **satisfeito** | `TestLimitesDaJanela`, oito ensaios. Os dois limites retêm com a **sua** regra (`manual_limite_diario` e `manual_limite_por_contacto_24h`, severidade `3`, acção `reter_confirmacao`), `test_retida_nao_fica_paga` exige **zero** `pagamento_confirmado`, e as duas sondas positivas estão lá (`test_no_tecto_diario_exacto_passa`, `test_uma_abaixo_do_tecto_do_contacto_passa`). `test_sem_tecto_de_janela_declarado_retem` é a leitura fechada. **E dois ensaios que medem o desenho e não a regra**: `test_a_janela_conta_o_contacto_que_declarou_e_nao_quem_confirma` — a dimensão do §9 é o comprador, e um tecto por confirmador era um tecto de vendas — e `test_a_janela_nao_ve_o_tenant_vizinho`, sem o qual uma PME com muitas vendas esgotava o tecto da PME ao lado. A ordem das portas é medida no módulo puro: «retem vence a dupla» (uma segunda assinatura não resolve um tecto diário) e «o valor errado vence os limites» (quem recebesse «retido» em vez de «o valor não bate» aprendia que acertou no valor) |
| 7 | Sem resposta do dono em 24 h a cobrança volta a `pendente_confirmacao → emitida` com `confirmacao_manual_rejeitada` e a reserva mantém-se até `expira_at` | **satisfeito** | `TestSilencioDoDono`, seis ensaios. `test_dentro_da_janela_nao_expira` (zero linhas, estado intacto) e `test_passada_a_janela_volta_a_emitida`, com relógio simulado **pela janela** (`p_janela_horas => 0`) e não pelo `now()` do servidor — mexer no relógio falseava também a janela de 24 h da `manual_janela` e a cadeia de *hashes*. `test_e_escreve_a_rejeicao_e_o_evento` prende o motivo `silencio_do_dono`, `authn_ok = false` e `actor_kind = 'sistema'`. **A metade fácil de perder** é `test_a_reserva_mantem_se_ate_expira_at`: o `valid_until` fica igual e **não** há `cobranca_expirada` — uma implementação que limpasse tudo de uma vez punia o cliente por um silêncio que não é dele. E a sonda positiva do critério inteiro, `test_depois_de_voltar_a_emitida_o_cliente_pode_declarar_outra_vez`, mostra que o caminho continua a funcionar. **O nome é `expira_at` e o critério escreve `expires_at`**: o *gate* 3b recusa a variante (medido), dívida documental **184** |
| 8 | Reversão: `confirmacao_manual_revertida` + `refund_cases` aberto + cobrança `paga → reembolso_pendente`; nenhuma linha é apagada | **satisfeito** | `TestReversao`, seis ensaios, e correm sobre uma cobrança que chegou a `paga` **pelo caminho humano inteiro** (`cobranca_paga`) — pelo que não podem ficar verdes sobre um caminho de confirmação que não funcione. `test_a_reversao_abre_o_caso_e_move_a_cobranca` prende o estado e o caso (`aberto`, o valor da cobrança, o motivo). **A propriedade que não se negoceia** está em dois ensaios: `test_nenhuma_linha_e_apagada_e_a_contagem_so_cresce` exige a contagem a crescer **e** que o `pagamento_confirmado` que a reversão desfaz **fique** no ledger, e `test_e_a_barreira_nao_e_a_funcao_mas_a_tabela` corre `DELETE` e `UPDATE` **com superutilizador**, incluindo os que **não casam linha nenhuma** — que é a metade que o KAM-175 fechou. `test_reverter_sem_motivo_e_recusado` (três formas de vazio) e `test_o_caso_leva_o_valor_da_cobranca_e_nao_um_argumento` fecham a «abuso de reembolso» do §9. A aresta nova é medida sozinha em `test_a_quinta_aresta_existe_e_so_de_paga`: `paga` dá `reembolso_pendente` e `emitida` continua a dar `NULL` |
| 9 | A mesma mensagem (`canal_msg_id`) processada 2 vezes produz 1 confirmação; `metodo='cod'` com *opt-in* desligado devolve `REJECTED` | **satisfeito** | `TestIdempotencia`, cinco ensaios: a declaração e a confirmação repetidas devolvem a **mesma** linha com `repetida = true`, **sem** evento novo e com uma fase só; `test_a_repeticao_nao_levanta` (três vezes); e `test_a_unicidade_e_por_cobranca_e_nao_global` — o mesmo `canal_msg_id` noutra cobrança é outro facto, porque os identificadores de mensagem vêm da Meta e uma colisão global fazia o dono ver «já confirmou» sobre um pedido que nunca tocou. **A concorrência** é `test_duas_confirmacoes_simultaneas_em_ligacoes_proprias`, em `ThreadPoolExecutor` e não em série: uma confirma, a outra é recusada pela guarda de estado, e há **um** `pagamento_confirmado` no ledger. O `cod` é o bloco «createCharge — o opt-in do cod» do `pagamentos.manual.test.ts`: desligado dá `REJECTED`, ligado passa (sonda positiva), a omissão **é** desligada, recusa-se mesmo dentro do tecto (a ordem importa: a mensagem certa é «sem opt-in» e não «acima do tecto»), e um método que o adaptador não cobre dá `NOT_SUPPORTED` e não `REJECTED` |

**Três barreiras que os critérios não pedem e que o ticket entrega**, porque sem elas os
critérios eram afirmações sobre um caminho de código e não propriedades da base:

| Barreira | O que fecha | Prova |
|---|---|---|
| `payment_events_g8_humano` (*trigger* `BEFORE INSERT`, `ENABLE ALWAYS`) | **O G8 do §5, que não existia em sítio nenhum.** Até aqui um `pagamento_confirmado` com `authn_method='manual'` e um `actor_id` qualquer passava — sem confirmador, sem desafio de valor e sem limites —, e o caminho humano era o único dos três do G1 sem guarda. Passa a exigir, na mesma transacção, uma fase de `manual_confirmations` desta cobrança que **conclua**, com `valor_bate` e com o **mesmo** actor | `TestG8DoCaminhoHumano`, sete ensaios, todos pelo **superutilizador** (o único com `INSERT` na tabela): sem fase recusa, com a fase passa (sonda positiva), a fase de **outro** actor não serve, uma fase com o valor errado não serve, e uma `declaracao_cliente` não é uma fase que conclua — que é o caminho mais directo do ataque, o cliente a declarar e isso a bastar. `test_o_confirmado_por_hmac_nao_e_afectado` separa «o G8 funciona» de «o G8 parte o outro caminho», e `test_o_trigger_e_always_e_o_replica_nao_o_salta` fecha a fenda do `session_replication_role` |
| A guarda de estado da `manual_confirmar` | **Uma confirmação sobre uma cobrança que já não espera confirmação escrevia a fase antes de o ledger recusar** — e a fase, com `valor_bate` verdadeiro, é exactamente o que o G8 exige. A transacção revertia, mas o desenho passava a depender de ela reverter. Saiu do ensaio de concorrência, que encontrou um `23514` com uma mensagem sobre transições onde a resposta certa era «esta cobrança já não espera confirmação» | `TestGuardaDeEstado`, quatro ensaios: `emitida` recusa, `paga` recusa, **nenhuma das duas deixa fase escrita**, e `pendente_confirmacao` passa (sonda positiva) |
| «A aplicação lê as quatro e não escreve nenhuma» | Com `INSERT` concedido, duas das quatro tabelas desfaziam uma guarda e não só uma convenção: no `payment_confirmers` um tenant acrescentava-se a si próprio à lista de quem pode confirmar (e o `WITH CHECK` da `tenant_iso` **não** o impedia — a linha era do próprio tenant), e na `manual_confirmations` escrevia-se uma `declaracao_cliente` com o `actor_contact_id` à escolha, o que faz escolher **quem o cliente é** | `TestPrivilegiosDasQuatroTabelas`: a sonda positiva (a aplicação **lê** as quatro), `42501` no `INSERT` das quatro, `42501` no `UPDATE` e no `DELETE` das duas de registo, e a sonda positiva do conjunto — ler-e-não-escrever **não** bloqueia o caminho, porque as cinco funções correm |

**E duas medições que não são de um critério e que o ticket trouxe:**

- **A tabela pura do `manual.ts` e a função da base concordam caso a caso.**
  `TestAcordoComATabelaPura` corre **onze** casos — legítimo, cliente, estranho, inactivo, valor
  a menos, valor a mais, diário, por contacto, sem diário, acima da dupla, sem dupla — e exige a
  mesma `decisao` e o mesmo `motivo` dos dois lados, contra um PostgreSQL real. As duas a
  divergir é o defeito perfeito: a suite de unidade verde, a base a recusar outra coisa, e o
  agente a dizer ao dono uma razão que não é a razão.
- **As cadeias SQL que o módulo envia correm.** `TestCadeiasDoModulo` lê as seis constantes
  `SQL_MANUAL_*` **do próprio ficheiro TypeScript** e corre cada uma contra a base, com a
  cobrança no estado que ela pede. Sem isto, uma mudança de nome de parâmetro na revisão deixava
  o módulo a falar com uma função que não existe, e **nenhum gate dava por nada**: o *gate* 4
  compila TypeScript e não fala com a base.

### Verificação da Definition of Done

| Caixa | Estado | Prova |
|---|---|---|
| Todos os Critérios de Aceitação satisfeitos e demonstráveis | **satisfeito** | Os nove acima. **São nove e não oito**, e vale dizê-lo: a contagem é a do bloco |
| Pagamento só por evento autenticado: o caminho `humano_auditado` exige actor, desafio de valor e limites; nenhum código marca `paga` por imagem ou texto do cliente | **satisfeito** | Três barreiras em série, e nenhuma depende das outras. (1) O `next_state` dá `paga` por **um** caminho só — `pagamento_confirmado` com `decisao='aceite'` —, que é o único que passa pela `confirmar_exige_autenticacao` (KAM-053). (2) O `humano_exige_actor` impõe o `actor_id`. (3) O **G8** exige a fase auditada com o mesmo actor e com `valor_bate`. Da imagem: a `manual_declarar` não escreve `pagamento_confirmado` nenhum (`test_a_declaracao_nao_confirma_nada`), e nenhum módulo do adaptador lê o conteúdo dela (*lint* com canário por fragmento) |
| Idempotência: repetir a mesma confirmação não duplica efeitos; teste de repetição presente | **satisfeito** | Critério 9. A chave é a restrição `manual_confirmations_msg_uq` e não um `ON CONFLICT`: a segunda chamada **lê** a linha e devolve-a com `repetida = true`, sem escrever evento nenhum — e não levanta, porque quem reentrega uma mensagem teria de distinguir «já estava» de «falhou» apanhando um `23505` pelo nome da restrição. Cobre os três caminhos que escrevem: declaração, confirmação e reversão |
| Isolamento de tenant e de contacto: RLS em `payment_confirmers` e `manual_confirmations`; caso novo na suite cruzada | **satisfeito, com a fronteira escrita** | RLS `FORCE` e política `tenant_iso` nas **quatro** tabelas (`rls.enable_tenant_rls`), e o X-05 do *gate* 6 descobre-as pelo catálogo — entram na verificação sem ninguém as declarar, e o `ci/rls_exceptions.yaml` continua **vazio**. Casos novos na suite cruzada: a `refund_cases` e o `fraud_signals` ganharam **receita de sementes**, pelo que o X-03/X-04/X-05 corre sobre elas. As outras duas estão em `SEM_RECEITA_COM_RAZAO`, cada uma com a sua razão escrita — a `manual_confirmations` porque nenhum papel tem `INSERT` e o `charge_id` obriga a semear uma cobrança (que já está dispensada pelo `assert_beneficiary`), e o `payment_confirmers` por uma razão que essa lista ainda não tinha: **nenhuma das seis colunas dela pode levar um canário** (dois domínios fechados, dois booleanos, um instante e duas FK), e libertar o `contact_id` parte a bateria de identidade — medido, sete ensaios vermelhos. O isolamento das duas prova-se no `TestIsolamentoDaConfirmacao`, com sete ensaios que incluem o que essa bateria não sabe fazer: as funções `DEFINER` **recusam** com o contexto de B sobre uma cobrança de A (o `FORCE` prende também o dono), e um contacto que **está** em `payment_confirmers` do tenant B não confirma uma cobrança de A — que é a RLS cruzada que esta caixa nomeia |
| Privacidade: sem telefone nem texto de mensagem nos logs; contacto por `contact_id` | **satisfeito** | Por inventário e por barreira, e não por convenção. O `test_inventario.py` declara as quatro tabelas coluna a coluna com a resposta a «isto guarda dados pessoais?», e **nenhuma** guarda telefone, BSUID ou nome: o confirmador é um `contact_id`, o `canal_msg_id` é um identificador opaco da Meta e não o conteúdo da mensagem, e a `evidencia_ref` é uma referência ao anexo e nunca o anexo. A barreira do `payload` é a da `append_payment_event` (guarda de PII da `0004`, que recusa padrões de telefone no `payload` **e** no `motivo`), e os `payload` que este ticket escreve levam identificadores e agregados. Os *templates* do M-9 passam por «nenhum aviso tem telefone nem texto do cliente» |
| Observabilidade: `manual_confirmations_total{fase}` e alerta de desvio semanal | *(caixa vazia)* — **parcial** | **Declarado e não emitido**, pela mesma razão que o `payment_events_total{tipo}` do KAM-053: a emissão é I/O e quem a faria é o serviço `pay`, que **não existe** nesta árvore (dívida 148). O que está feito: o nome da métrica (`METRICA_CONFIRMACOES`), as etiquetas (uma série por fase, com ensaio que prende as cinco contra `FASES`) e o nome do alerta (`ALERTA_DESVIO_SEMANAL`). O **limiar** do desvio fica de fora de propósito — é *proposta* e calibra-se no **KAM-096**; escrevê-lo num módulo que não lê *entitlements* era o endurecimento silencioso que o `PROPOSTAS_DE_OMISSAO` existe para evitar. Credor: o serviço `pay`, o mesmo do *worker* do §5.1 |
| Dois revisores; cobertura ≥ 90%; limites registados como propostas a calibrar | *(caixa vazia)* — **duas de três** | **Cobertura: satisfeita.** `tools/coverage_gate.py` dá o estrato `critico` a **97%** (mínimo 90%), com o `manual.ts` a **99%** (865/871 linhas) e o módulo `pagamentos` a 98%. **Limites: satisfeito.** Os quatro vivem em `entitlements.limites` e nenhum está em constante — `PROPOSTAS_DE_OMISSAO` é documentação, com ensaio a provar que não entra em decisão nenhuma, e as **duas chaves de janela não têm proposta nenhuma** porque o §4.2 M-3 não dá valor a nenhuma (dívida **185**, credor KAM-096). A emenda 1.60 do dicionário registra os quatro como propostas. **Dois revisores: devolvida, e não bloqueia.** A revisão adversarial deste ramo é **uma** das duas assinaturas — um agente que não viu o raciocínio de quem escreveu —, e a segunda é um revisor de dinheiro que só o fundador pode nomear. **E o fundador decidiu que na fase inicial as fusões seguem com o CI verde sem esperar revisão humana, e isso vale até produção** — pelo que a caixa fica vazia com o credor escrito e **não** é uma condição de fusão. A diferença importa: uma caixa vazia por decisão registada é informação, e uma caixa marcada «em espírito» era uma assinatura inventada. Credor: **o fundador** |

**O que não se cumpre, nomeado:**

- **A observabilidade fica a meio, e a metade que falta não é deste ticket.** As métricas e o
  alerta estão nomeados e testados; emiti-los exige um processo que chame as portas, e esse
  processo é o serviço `pay`. É a mesma fronteira que o KAM-053 escreveu para o
  `payment_events_total{tipo}` e para os quatro alertas do ledger.
- **O segundo revisor de dinheiro não está nomeado, e isso não bloqueia a fusão.** A
  revisão adversarial cobre uma das duas assinaturas que a DoD pede; a outra é uma
  decisão de quem pode nomear revisores de dinheiro. O fundador decidiu que na fase
  inicial as fusões seguem com o CI verde sem esperar revisão humana, e isso vale até
  produção: a caixa fica vazia com o credor escrito, e não marcada «em espírito».
- **Três divergências entre o bloco e fontes acima dele ficam registadas e não emendadas**
  (dívidas **183**, **184** e **185**): o `authn_method='humano_auditado'` do critério 5, que a
  base recusa e que o próprio §4.2 M-6 contradiz; o `expires_at` do critério 7, que o *gate* 3b
  recusa; e os dois limites do M-3 que o documento nomeia e **não quantifica** — este último com
  consequência medida, porque um tenant sem eles tem **todas** as confirmações retidas para ops.
  A letra de um critério é de quem o escreveu; o que este ticket entrega é a medição.
- **A suite `tests` do *gate* 8 correu em subconjunto** (quatro módulos) e não inteira, pela
  razão escrita acima da tabela de comandos. O CI corre-a inteira.
- **Uma ressalva de forma, e fica escrita em vez de corrigida.** O *commit* de *merge* que
  integrou a `main` (o `8047a46`, do KAM-178) leva ao colo duas coisas que deviam ter tido
  *commit* próprio: o `db/tests_pagamentos/test_downgrade_0032.py` e a passagem da
  `downgrade` da revisão a chamar `rls.disable_tenant_rls`. **Não se reescreve**, e a
  razão é a mesma que a dívida 170 dá para um caso próximo: reescrever a história custa
  um *force-push* e um ciclo inteiro de CI para mudar a **forma** de uma coisa cujo
  **conteúdo** está certo, e o *gate* 2 dispensa `^Merge ` por construção — pelo que
  trocava um defeito de forma por um de história. Diz-se aqui porque um *commit* de
  *merge* que traz código de produto é exactamente o que um revisor deve poder ver sem
  ter de o descobrir.

### Handoff para Claude Code

```text
És o executor do ticket KAM-054 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-054) e
docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md (§4 inteiro, §6.3, §7.2 F-18, §9) e ADR-013.
Objectivo: ManualProvider com payment_confirmers, manual_confirmations e refund_cases; fluxo
declaração do cliente -> desafio do valor -> confirmação -> segunda aprovação acima do limiar.
- Só confirma quem está em payment_confirmers (BSUID do canal), nunca por texto; o cliente nunca confirma.
- Imagem de comprovativo = evidencia_ref 'nao_prova'; nunca a leias para decidir.
- Limites (50.000 Kz, 20.000 Kz) vêm de entitlements e são PROPOSTAS a calibrar; sem tolerância no valor.
- Reverter = evento compensatório + refund_cases; nunca apagar. Tudo via append_payment_event.
Não expandas escopo: eventos EVT e transição da encomenda (KAM-055); anomalias (KAM-060).
Testes: unit (tabela M-1..M-5), integração, abuso, idempotência, RLS. PR com o template (§7).
```

---

## KAM-055 — Eventos `payment.confirmed` e `payment.manual_confirmed` e transição da encomenda

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 0 |
| Tipo | feature |
| Prioridade | P0 |
| Estimativa | M |
| Dependências | KAM-054, KAM-044, KAM-005, KAM-006 |
| Bloqueia | KAM-058, KAM-096, KAM-097, KAM-108, KAM-117 |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§5, §7.1), `../docs/tecnica/06_Dados_Eventos_Analytics.md` (§4, §5, §6.3), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§6.2, §6.5, §6.6), `../docs/tecnica/00_Arquitectura_Solucao.md` (§6.1, §13.2), ADR-009, ADR-013 |

### Contexto
O gate da Fase 0 (KAM-108) exige que uma conversa real crie um pedido, receba `payment.confirmed` ou `payment.manual_confirmed` e que o evento seja consumido pela vertical Serviços. `payment.manual_confirmed` existe porque misturar os dois sob `payment.confirmed` esconderia a diferença de autenticação (`../docs/tecnica/06` §5). O COM só transita a encomenda por estes eventos; o `falhada` da cobrança nunca é estado de encomenda.

### Objectivo
Registar os contratos v1 dos eventos de pagamento, preencher o mapeamento ledger → evento, e implementar no COM o consumidor idempotente e ordenado que leva `aguarda_pagamento`/`pendente_confirmacao` a `paga`, consome as reservas e emite `order.paid`.

### Critérios de Aceitação
- [ ] Existem `contratos/eventos/payment.confirmed/v1.schema.json`, `payment.manual_confirmed`, `payment.reference_issued`, `payment.failed` e `payment.expired` com `additionalProperties:false`, sem telefone nem texto, e o teste de compatibilidade (KAM-007) passa.
- [ ] `pagamento_confirmado` com `authn_method` em `hmac_sha256`/`status_pull` emite `payment.confirmed`; com `humano_auditado` emite `payment.manual_confirmed`; nunca existe um emitido sem o `authn_ok=true` correspondente no ledger.
- [ ] O mesmo evento entregue 10 vezes produz 1 transição, 1 `order.paid` e 1 linha em `events_consumed`.
- [ ] O consumidor está registado com `exige_ordem=true`; um `payment.*` que chega antes de `aguarda_pagamento` é adiado 5 s e, esgotadas as tentativas, vai para a DLQ sem aplicar transição inválida.
- [ ] `paga_via` fica `provider_autenticado` ou `manual_auditado` conforme o evento; as reservas passam a `consumida` e `paga_at` é preenchido na mesma transacção que `order_state_log`.
- [ ] Um evento cujo `valor_minor` difere de `orders_mirror.total_minor` não transita a encomenda e gera `payment.failed`.
- [ ] Um `payment.confirmed` para encomenda `expirada` ou `cancelada` não aplica a transição (o caso completo é KAM-050), vai para a DLQ com `erro='estado_incompativel'` e alerta Sev1.
- [ ] Migração `NNNN_payment_order_fks` acrescenta as FK `payment_charges.order_id` e `payment_events.order_id` para `orders_mirror`, reversível.
- [ ] p95 de `payment.confirmed` no ledger até `order.paid` ≤ 5 s em 100 eventos simulados.

### Detalhes Técnicos
- **Componentes:** PAY, COM, EVT. Produtor: `append_payment_event` via `evt_emitir`; consumidor no COM com `transition` por CAS (`UPDATE … WHERE id AND version AND estado`), conforme `../docs/tecnica/03` §6.2.
- **Payload:** `order_id`, `charge_id`, `provider`, `referencia`, `valor_minor`, `moeda='AOA'`, `autenticacao{metodo, provider_event_id}`. O doc 06 §4 exemplifica `valor_kz`; `../docs/tecnica/03` §5.1 e `../docs/tecnica/04` usam unidades menores. Este ticket fixa `valor_minor` e regista a divergência em Riscos.
- **O nome `*_minor` de que este ticket depende está ratificado, e `valor_kz` continua proibido.** A comparação que o critério 2 pede — o `valor_minor` do evento contra `orders_mirror.total_minor` — assenta em colunas `*_minor` dentro de `platform`, e a allowlist `EM_UNIDADE_MENOR` de `db/tests/test_catalogo.py` (*gate* 8) que as autoriza foi **ratificada pelo fundador a 2026-11-03**: KAM-172, [`../docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md`](../docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md). Duas consequências práticas: a `payment_charges` e a `payment_events` deste caminho chegaram já com o **KAM-053** (revisão `0029`) e as suas entradas estão escritas, pelo que este ticket não acrescenta coluna de dinheiro nenhuma a `platform` — só as FK; e a divergência do doc 06 §4, que exemplifica `valor_kz`, continua a resolver-se contra este ticket e não a favor dele — o sufixo `_kz` é proibido **sem excepção** no *gate* 8, com canário que o prova.
- A reconciliação final antes de expirar (`../docs/tecnica/03` §6.5) e o pagamento tardio (§6.6) são de KAM-045/KAM-050; aqui só se garante que não há transição inválida.
- Tabela de mapeamento versionada em `payment_event_map` (SemVer); alterá-la é MINOR.
- `payment.failed` e `payment.expired` alimentam o HND (humano) e o COM; DLQ de `payment.*` é Sev1 (`../docs/tecnica/06` §6.4).
- Falta KAM-006 nas dependências do mestre; o consumidor usa o padrão de `../docs/tecnica/06` §6.3 e requer `events_consumed` (ver problemas do backlog).

### Testes Requeridos
- Unit: mapeamento ledger → evento; comparação de valor.
- Integração: ledger → outbox → consumidor → `orders_mirror` com Postgres e Redis reais; ordem inversa; duplicados ×10; concorrência de duas transições (CAS).
- Contrato: schemas v1 e *lint* de PII (`../docs/tecnica/06` §7.3).
- Fim-a-fim: caminho Manual até `order.paid` consumido pela vertical Serviços (insumo do KAM-108).

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Pagamento só por evento autenticado: `paga` só por estes dois eventos; sem atalho por input de utilizador.
- [ ] Idempotência: duplicados ×10 e reentrega após *crash* a meio testados.
- [ ] Isolamento: o consumidor aplica `tenant_id` do envelope e RLS; caso na suite cruzada.
- [ ] Privacidade: eventos sem telefone, nome ou texto; só `contact_id` e referências.
- [ ] Observabilidade: métricas de lag `payment→order.paid` e DLQ de `payment.*`; versão SemVer dos schemas atribuída.
- [ ] Migração reversível; dois revisores.

### Handoff para Claude Code

```text
És o executor do ticket KAM-055 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-055),
docs/tecnica/04 (§5, §7.1), docs/tecnica/06 (§4, §5, §6.3) e docs/tecnica/03 (§6.2, §6.5, §6.6).
Objectivo: schemas v1 dos eventos payment.*, mapeamento ledger -> evento (hmac/status_pull => payment.confirmed;
humano_auditado => payment.manual_confirmed) e consumidor idempotente e ordenado no COM que leva a encomenda a
paga, consome reservas, preenche paga_via/paga_at e emite order.paid; FK de orders_mirror nas tabelas de PAY.
- Valor do evento tem de bater com total_minor; senão payment.failed, sem transição.
- Estado incompatível (expirada/cancelada) => DLQ Sev1, nunca transição inválida (KAM-050 trata o tardio).
- CAS por version; evento duplicado => 1 efeito.
Não expandas escopo: ManualProvider (KAM-054), pagamento tardio e disputas (KAM-050), régua (KAM-058).
Testes: unit, integração (Postgres+Redis), contrato de schemas, fim-a-fim Manual. PR com o template (§7).
```

---

## KAM-056 — Adapter ProxyPay: referências, callbacks HMAC, reconciliação e expiração

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-052, KAM-053, ext:KAM-103, KAM-013, KAM-010 |
| Bloqueia | KAM-072 |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§3.2, §3.3, §3.5, §5, §7.2, §8), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§1.2), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.5), D4 |

### Contexto
O ProxyPay RPS v2 é o facilitador preferido pela arquitectura: HMAC-SHA256 em `X-Signature` (CONFIRMADO), fila de reconciliação `GET /payments` e `DELETE /payments/{id}` (CONFIRMADO). Estão **NÃO VERIFICADOS**: preços, rate limit (existe HTTP 429), assinatura do callback OPG, janela de duas chaves e o prazo de onboarding bancário. A chave HMAC é a própria API key. Este ticket só se executa com contrato (KAM-103, D4); sem ele fica atrás de *flag* e o Piloto segue em `ManualProvider`.

### Objectivo
Implementar o adaptador ProxyPay RPS (referência) com `createCharge`, `verifyCallback`, `listUnacknowledged`/`acknowledge`, `cancelCharge`, o *job* de reconciliação e a expiração, e, por detrás de uma segunda *flag*, o OPG (Express) tratado como dica com `status_pull`.

### Critérios de Aceitação
- [ ] `createCharge(referencia)` faz `POST /reference_ids` e `PUT /references/{id}` com `amount` em `decimal2` convertido de `Minor`, `end_datetime = valid_until` e `custom_fields = {charge: chargeId}` sem PII; repetir o `PUT` com o mesmo `id` não cria 2.ª referência.
- [ ] `verifyCallback` valida `X-Signature = hex(HMAC-SHA256(API_KEY, corpo cru))` em tempo constante com chave corrente ou anterior (janela de duas chaves); 1 byte alterado devolve 401 e `hmac_invalido`.
- [ ] A suite de conformidade (§3.5) passa 10/10 no *sandbox*, incluindo callback ×10 → 1 efeito, valor ± 1 cêntimo, referência desconhecida → `pagamento_orfao`, pagamento após `valid_until`, *timeout* com resposta perdida e HTTP 429.
- [ ] O *job* de reconciliação corre de 5 em 5 min por conta activa e antes de expirar uma reserva; só chama `DELETE /payments/{id}` **depois** do *commit* e só para cobranças nossas; um pagamento desconhecido gera alerta e não é reconhecido.
- [ ] O lag de reconciliação p99 ≤ 10 min (`reconciliation_lag`) num teste com 100 pagamentos perdidos; se o `DELETE` falhar, o pagamento reaparece e G7 absorve-o.
- [ ] Sem *timestamp* assinado, a janela «±5 min» não é aplicada; a defesa de *replay* é G7 e um teste prova que reentregar um corpo válido não repete o efeito.
- [ ] Um `fee` do evento é guardado em `payload.fee` em 100% dos pagamentos do *sandbox*.
- [ ] OPG (se activado): `Idempotency-Key = chargeId`; resposta perdida repete o POST só até 5 min e depois consulta `status()`; sem `statusQuery` confirmado por escrito, o callback é dica e nunca confirma sozinho; códigos 2001/2003/2004/3000 mapeiam as mensagens de `../docs/tecnica/04` §3.3.
- [ ] Saída para NÃO VERIFICADO: sem contrato à data de fim da Fase 1 o adaptador permanece com `proxypay_enabled=false` e regista-se a decisão (gatilho H5); preços e rate limit só entram em configuração depois de recebidos por escrito.

### Detalhes Técnicos
- **Componentes:** PAY, GWY. Módulos `services/pay/src/adapters/proxypay/{rps,opg,verify,reconcile}.ts`; credenciais por conta em `credenciais_ref` (corrente e anterior); **uma chave de API dedicada por PME** para a KAMBÁ.
- **Mapeamento:** `Authorization: Token <API_KEY>` (RPS) e `Bearer` (OPG); *sandbox* `https://api.sandbox.proxypay.co.ao`; *Mock Payment* para testes; números OPG de teste `900000000` (aceita), `900002004` (*timeout*), `900003000` (recusa), `9XXXXXXXX` (rejeita).
- **Capabilities:** RPS `callbackAuth='hmac'`, `statusQuery=true`, `reconciliationQueue=true`, `amountFormat='decimal2'`; OPG `callbackAuth='desconhecido'` até resposta.
- *Backoff* exponencial com *jitter* para 429; o valor do limite é NÃO VERIFICADO e fica em configuração.
- Reconhecer pagamentos de outra integração da PME roubaria-lhe pagamentos: nunca `DELETE` sem cobrança nossa correspondente (`../docs/tecnica/04` §8 regra b).

### Testes Requeridos
- Contrato com *sandbox* e *Mock Payment* no CI (suite §3.5 completa).
- Unit: conversão `Minor` ↔ `decimal2`, janela de duas chaves, mapeamento de códigos.
- Integração: reconciliação com `listUnacknowledged` simulado, *commit* antes de `DELETE`, perda de callback.
- Segurança: corpo adulterado, chave errada, token desconhecido.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis (ou *flag* desligada com decisão registada).
- [ ] Pagamento só por evento autenticado: confirmação só por HMAC ou `status_pull`; o OPG sem assinatura não confirma sozinho.
- [ ] Plataforma sem fundos: credenciais da PME, liquidação directa; `payout`/`refund` `NOT_SUPPORTED`.
- [ ] Idempotência: `PUT` por `id`, G7 e `Idempotency-Key` testados.
- [ ] Sem segredos: chaves no cofre; rotação coordenada com KAM-072.
- [ ] Suite de conformidade verde antes da activação em produção; dois revisores.

### Handoff para Claude Code

```text
És o executor do ticket KAM-056 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-056),
docs/tecnica/04 (§3.2, §3.3, §3.5, §5, §7.2, §8) e docs/tecnica/evidencia/E2 §1.2. Só avanças com o contrato KAM-103
(D4); senão deixa o adaptador atrás da flag proxypay_enabled=false.
Objectivo: adaptador ProxyPay RPS (POST /reference_ids, PUT /references/{id}, X-Signature HMAC sobre o corpo cru,
GET/DELETE /payments) + job de reconciliação; OPG (Express) atrás de segunda flag, tratado como dica + status_pull.
- Janela de duas chaves; nunca DELETE antes do commit; nunca reconhecer pagamentos que não são cobranças nossas.
- Sem timestamp assinado: sem janela ±5 min; a defesa é a idempotência G7.
- Preços e rate limit são NÃO VERIFICADOS: não os inventes; fica em configuração.
Não expandas escopo: AppyPay (KAM-057), rotação de chaves (KAM-072).
Testes: suite de conformidade §3.5 no sandbox, unit, integração, segurança. PR com o template (§7).
```

---

## KAM-057 — Avaliação do segundo facilitador (AppyPay) e matriz de decisão

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 1 |
| Tipo | spike |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | KAM-052, ext:KAM-103 |
| Bloqueia | — |
| Responsável sugerido | Arquitecto de Plataforma |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§3.2, §3.4, §10.2), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§1.3, §9 perguntas 11–15), D4 |

### Contexto
A AppyPay cobre num só contrato Express, referência, débito directo e Unitel Money, e declara não intervir no fluxo financeiro (termos cl. 1.5, CONFIRMADO). O preço público é 0,40% por cobrança (mínimo 50 Kz, máximo 1 500 Kz, IVA a acrescer; CONFIRMADO). A documentação técnica (Stoplight) **não foi lida**: assinatura do *webhook*, *retries*, idempotência, ambiente de testes, modelo *partner/ISV* e esquema de autenticação são NÃO VERIFICADOS (INDÍCIO por SDKs de terceiros). A responsabilidade da AppyPay limita-se ao valor pago no último mês.

### Objectivo
Produzir uma decisão escrita (adoptar, adiar ou rejeitar) sobre a AppyPay como segundo facilitador, com matriz comparada ao ProxyPay, perguntas enviadas por escrito e a declaração de `ProviderCapabilities` que o adaptador teria. Sem código de produção.

### Critérios de Aceitação
- [ ] As perguntas 11–15 de `../docs/tecnica/evidencia/E2` §9 foram enviadas por escrito à AppyPay e o registo de envio (data, canal) está anexado; as respostas ou a sua ausência estão datadas.
- [ ] A matriz tem pelo menos 12 critérios (assinatura de *webhook*, consulta de estado, *retries*, idempotência, ambiente de testes, autenticação, `merchantTransactionId` ≤ 15, reembolso, Unitel Money, preço, prazo de onboarding, estrutura de fundos), cada um com estado CONFIRMADO/INDÍCIO/NÃO VERIFICADO e fonte.
- [ ] Nenhum critério NÃO VERIFICADO é tratado como facto na decisão; cada um tem uma pergunta aberta ou um critério de saída.
- [ ] A decisão inclui o rascunho de `ProviderCapabilities` da AppyPay e a regra: só se implementa o adaptador se o *webhook* for assinado **ou** existir consulta de estado confirmada por escrito (ADR-013).
- [ ] O custo total por transacção está modelado em dois componentes (facilitador + comissão bancária/EMIS) com os intervalos marcados e o impacto no preço da PME; o prazo de onboarding e a pessoa singular sem NIF ficam registados como NÃO VERIFICADOS.
- [ ] O registo da decisão segue o formato MADR com numeração após ADR-019, estado «proposto», e é revisto por Arquitecto e Responsável de Produto.
- [ ] Tempo-limite: 2 dias úteis de trabalho; o que não ficou verificado vai para o relatório, não para a decisão.

### Detalhes Técnicos
- **Componentes:** PAY. Saída: `docs/decisoes/MADR-pay-segundo-facilitador.md` e `docs/pagamentos/matriz_facilitadores.md`.
- **Dados de partida (não os confundir com verificados):** `POST /charges`, base `gwy-api.appypay.co.ao/v2.0`, OAuth2 *client credentials*, *sandbox* `gwy-api-tst` — INDÍCIO [BLOG/código]. O `numero_publico` (≤ 8 caracteres) serviria de `merchantTransactionId`.
- Contrapartes a comparar: ProxyPay RPS/OPG (KAM-056), EMIS directo (não recomendado: callback não assinado e sem consulta, INDÍCIO), MoMenu e Paybyrd como candidatos (estrutura de fundos NÃO VERIFICADA).
- Liquidação: Express no fecho do TPA virtual e referências às 20:00 (CONFIRMADO); D+0/D+1 por banco NÃO VERIFICADO; a interface nunca promete «dinheiro na hora».
- Lacuna conhecida: o FTBAI (transferência de fundos) existe no SDK de terceiros; não é para usar (payouts fora do Piloto).

### Testes Requeridos
- Revisão por pares do relatório contra a lista de verificação: cada afirmação tem estado e fonte.
- Verificação de que a decisão não contradiz ADR-004 nem ADR-013.
- Se houver *sandbox* acessível, uma chamada de teste documentada (opcional, sem dados reais).

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Decisão escrita e registada; perguntas por escrito anexadas com datas.
- [ ] Nenhum NÃO VERIFICADO transformado em requisito sem critério de saída.
- [ ] Plataforma sem fundos: nenhuma opção avaliada exige detenção de fundos ou payouts da KAMBÁ.
- [ ] Sem segredos nem dados reais de PME em anexos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-057 da KAMBÁ (spike, S, sem código de produção).
Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-057), docs/tecnica/04 (§3.2, §3.4, §10.2) e
docs/tecnica/evidencia/E2 (§1.3, §9 perguntas 11-15).
Objectivo: matriz de decisão AppyPay vs ProxyPay (>= 12 critérios, cada um com CONFIRMADO/INDÍCIO/NÃO VERIFICADO e
fonte), rascunho de ProviderCapabilities, perguntas por escrito e decisão adoptar/adiar/rejeitar em formato MADR.
- A documentação Stoplight não foi lida: tudo o que vier de SDKs de terceiros é INDÍCIO.
- Só se implementa se o webhook for assinado OU houver consulta de estado confirmada por escrito.
Não escrevas adaptador; não inventes preços, prazos nem limites. Entrega: relatório + decisão + registo de perguntas.
```

---

## KAM-058 — Régua de cobrança D+3/D+7/D+10

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-055, KAM-015, KAM-059, ext:KAM-101 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§11.2), `../docs/tecnica/00_Arquitectura_Solucao.md` (§6.2, D10), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§12), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§4, Art. 16.º Lei 15/03), ADR-017 |

### Contexto
A régua é a sequência de cobrança da **assinatura da KAMBÁ às PMEs** (`../docs/tecnica/04` §11.2): D+0 referência, D+3 lembrete, D+7 aviso de suspensão, D+10 `ativo → suspenso` («falta de pagamento», doc 00 §6.2), e regularização → `ativo`. Os dias são **parâmetros propostos** a calibrar no Piloto. Há dois pontos abertos: o canal por onde a KAMBÁ fala com o dono é a decisão **D10** (o Fluxo A usa o número da PME e o tenant `platform` está vedado); e a classificação Meta de uma mensagem de cobrança (utility vs marketing) é NÃO VERIFICADA. A régua não cobra comissão (ADR-017) nem tem poder para suspender por outro motivo.

### Objectivo
Implementar o motor da régua sobre `billing_cycles`, idempotente por passo, com relógio injectável, canal de notificação por porta (`OwnerNotifier`), suspensão e reactivação do tenant, e métricas.

### Critérios de Aceitação
- [ ] Para um ciclo `cobranca_emitida` não paga, o motor produz exactamente os passos D+3, D+7 e D+10; reexecutar o motor 5 vezes no mesmo dia não duplica nenhum passo (unicidade `(billing_cycle_id, passo)`).
- [ ] No D+10 o tenant passa `ativo → suspenso` uma única vez, com `audit_log` e evento `tenant.suspended`; o CHR passa a rejeitar o tenant antes do AGR (teste fim-a-fim).
- [ ] Pagamento autenticado no D+9 cancela os passos pendentes e o tenant não é suspenso; pagamento no D+11 repõe `suspenso → ativo` em p95 ≤ 60 s após `payment.confirmed`.
- [ ] Os dias (3, 7, 10) e o texto vêm de configuração versionada; mudar um valor aplica-se apenas a ciclos abertos depois (aviso prévio, Art. 16.º da Lei 15/03 em INDÍCIO, a confirmar por parecer).
- [ ] Cada lembrete é *template* parametrizado (valor, referência, prazo vêm da cobrança no `ledger`, nunca do LLM) com aviso anti-*phishing* fixo; um teste falha se o texto contiver um número que não seja campo da cobrança.
- [ ] O motor entrega por `OwnerNotifier`; até D10 fechar, o adaptador por omissão cria tarefas de ops numa lista diária (*fallback* manual) e nenhuma mensagem sai pelo número de um tenant para outro assunto que não seja o dele.
- [ ] A suspensão nunca apaga dados, nunca bloqueia o titular de exportar os seus dados e respeita o estado `restrito` da Meta (não o sobrepõe).
- [ ] O relógio é injectável: o teste de 11 dias corre em < 5 s.

### Detalhes Técnicos
- **Componentes:** PAY, TEN, GOV. Módulos `services/pay/src/dunning/{engine,steps,config}.ts`; tabela `billing_dunning_steps(billing_cycle_id, passo, executado_at, resultado)` com `UNIQUE (billing_cycle_id, passo)` (proposta).
- **Dependência de dados:** consome `subscriptions` e `billing_cycles` de KAM-059 (DDL em `../docs/tecnica/04` §11.2); o mestre não declara a dependência (ver problemas). Até KAM-059 estar `Done`, o motor testa-se com fixtures desse DDL.
- **Eventos:** `billing.reminder_due` (interno) e `tenant.suspended`/`tenant.reactivated` (catálogo `../docs/tecnica/06` §5); sem PII no payload.
- **Canal:** `OwnerNotifier` com adaptadores *WhatsApp via outbound* (KAM-015, dentro da janela ou *template utility*) e *ops manual*. A categoria Meta do *template* é NÃO VERIFICADA (pergunta D2/KAM-101); saída: se a Meta o classificar como marketing, o adaptador WhatsApp fica desligado e a régua usa o canal de ops.
- Suspensão não é instantânea no cliente final: o CHR responde com mensagem determinística de loja indisponível (princípio 12).

### Testes Requeridos
- Unit: calendário de passos com relógio simulado; configuração versionada.
- Integração: ciclo completo D+0 → D+10 → regularização com Postgres real e `FakeOwnerNotifier`.
- Idempotência: reexecução do motor e *crash* a meio de um passo.
- Contrato: nenhum número em mensagens fora dos campos da cobrança.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Idempotência: cada passo tem chave e teste de repetição.
- [ ] Números só de tools: valores e referências dos lembretes vêm da cobrança.
- [ ] Privacidade: nenhum telefone nem texto de mensagem em logs ou eventos; contacto do dono por `contact_id`.
- [ ] Observabilidade: `dunning_step_total{passo}`, `tenants_suspended_by_dunning_total`; alerta se > N suspensões/dia (N proposta).
- [ ] Sem comissão: a régua só trata assinatura (ADR-017); canal D10 documentado como decisão aberta.

### Handoff para Claude Code

```text
És o executor do ticket KAM-058 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-058),
docs/tecnica/04 §11.2, docs/tecnica/00 §6.2 e a decisão aberta D10.
Objectivo: motor da régua de cobrança da assinatura (D+3 lembrete, D+7 aviso, D+10 ativo->suspenso, regularização
-> ativo) sobre billing_cycles, idempotente por (billing_cycle_id, passo), relógio injectável, canal por porta
OwnerNotifier (fallback: lista de ops até D10 fechar).
- Dias e textos são PROPOSTAS em configuração versionada; valores/referências vêm da cobrança, nunca do LLM.
- Suspender não apaga dados; pagamento D+9 cancela passos pendentes; D+11 reactiva em <= 60 s (p95).
Não expandas escopo: criação de ciclos e cobranças é KAM-059; comissão não existe no Piloto.
Testes: unit (calendário), integração (ciclo completo), idempotência. PR com o template (§7).
```

---

## KAM-059 — Billing da plataforma: assinatura via PaymentProvider (beneficiário próprio)

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-052, KAM-054, KAM-009 |
| Bloqueia | KAM-058 |
| Responsável sugerido | Responsável de Produto |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§10.4, §11, §12, §13), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-017, §6.2), `../docs/tecnica/08_Seguranca_Conformidade.md` (§8.8, §8.10), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§5, §6, §7) |

### Contexto
No Piloto a receita é **assinatura**; a comissão sobre transacção fica desligada até parecer (D8, ADR-017) porque a atribuição é inauditável (a PME e o cliente falam no próprio número) e a plataforma não pode deduzi-la da liquidação (ADR-004). A KAMBÁ cobra as PMEs com a mesma interface `PaymentProvider` (*dogfooding*), numa `payment_account` com `beneficiary_kind='plataforma_receita_propria'` para não activar o tenant `platform` (D2). Sem conta EMIS própria o *fallback* é transferência com `ManualProvider` e factura manual. A KAMBÁ não emite facturas fiscais próprias (DP 71/25, CONFIRMADO; D7).

### Objectivo
Implementar `price_book`, `subscriptions`, `billing_cycles` e `commission_accruals` (modo sombra), a abertura idempotente de ciclos e cobranças, o pagamento do ciclo por evento autenticado ou confirmação de ops com dupla aprovação, e a ligação do plano aos `entitlements`.

### Critérios de Aceitação
- [ ] A migração cria as 4 tabelas de `../docs/tecnica/04` §11.2 e a FK `charges_billing_fk`; `UNIQUE (subscription_id, periodo)` garante 1 ciclo por período e a migração é reversível.
- [ ] O *job* de abertura de ciclos corre 2 vezes para o mesmo período e produz 1 `billing_cycle` e 1 `payment_charge` (`UNIQUE (billing_cycle_id, tentativa)`); a cobrança tem validade de 72 h.
- [ ] A cobrança usa só contas `plataforma_receita_propria`; criá-la numa conta de PME falha pelo *trigger* G-1 e uma cobrança de encomenda nesta conta também.
- [ ] `payment.confirmed` autenticado leva o ciclo a `paga`; o mesmo evento 10× produz 1 transição e 1 evento `billing.cycle_paid`.
- [ ] Com `ManualProvider` no billing, a confirmação é de ops (`actor_kind='ops'`) com motivo obrigatório e duas pessoas distintas; uma só aprovação não conclui.
- [ ] Alterar uma linha de `price_book` (nova `valido_de`) não altera ciclos já em `cobranca_emitida`; só se aplica ao ciclo seguinte, e a alteração fica no `audit_log`.
- [ ] `commission_enabled=false` por omissão (global e por tenant): `commission_accruals` só aceita `modo='sombra'`, `UNIQUE (payment_event_id)` evita duplicados, e arrancar com `commission_enabled=true` sem `parecer_ref` (D8) falha no arranque.
- [ ] Mudar `subscriptions.plano` actualiza os `entitlements` do tenant (KAM-009) na mesma transacção; um tenant `em_atraso` mantém os limites até à suspensão da régua.
- [ ] Nenhum documento fiscal é emitido por este ticket: um teste confirma que não existe rota nem função de emissão (C-04).
- [ ] Está definido (processo documentado; interface `InvoiceProvider` como gancho, implementação Diferida) como a KAMBÁ emite a **factura-recibo** da sua própria assinatura às PMEs em conformidade com a AGT, via software certificado (D7); no Piloto é um processo manual registado, sem emitir facturas a partir de código próprio (a confirmar por parecer; E2).

### Detalhes Técnicos
- **Componentes:** TEN, PAY. Módulos `services/pay/src/billing/{cycles,price_book,accruals}.ts`; DDL em `../docs/tecnica/04` §11.2. `iva_pct` tem 14,00 por omissão no DDL; confirmar com contabilista (NÃO está em `../docs/tecnica/evidencia/`).
- **Ciclo:** abre no início do período → cria cobrança (`referencia`, 72 h) → paga → `billing.cycle_paid`; o pedido de factura-recibo (porta `InvoiceProvider`) é Clusters (D7). Débito directo recorrente exige IEC da KAMBÁ: Clusters.
- **Sombra de comissão:** deriva de `payment.confirmed` com `paga_via='provider_autenticado'`; nunca factura e nunca retém (ADR-004, ADR-017).
- Valores em `*_minor`; preços do plano são decisão de produto (não inventar aqui); câmbio e margem: alerta de 15% da mensalidade em KAM-081, `fx_reference` e revisão semestral (banda ±5% proposta) ficam registados como seguimento.
- A conta EMIS própria da KAMBÁ é NÃO VERIFICADA (D4); saída: `ManualProvider` + factura manual.

### Testes Requeridos
- Unit: cálculo de período e valor com `price_book` versionado; guarda de `commission_enabled`.
- Integração: ciclo completo com `FakeProvider` e `ManualProvider`; dupla aprovação de ops; alteração de preço a meio.
- Idempotência: *job* ×2, `payment.confirmed` ×10.
- Segurança: G-1 nos dois sentidos; RLS cruzada em `subscriptions` e `billing_cycles`.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Plataforma sem fundos: a receita é da KAMBÁ como comerciante; sem retenção nem repasse de vendas; comissão desligada.
- [ ] Pagamento só por evento autenticado ou confirmação humana de ops com dupla aprovação.
- [ ] Idempotência: ciclos e cobranças com chave e teste de repetição.
- [ ] Isolamento: RLS `FORCE` com a conta da KAMBÁ acessível só ao papel de billing; caso na suite cruzada.
- [ ] Migração reversível; dois revisores; parecer D8 referenciado para qualquer activação futura de comissão.

### Handoff para Claude Code

```text
És o executor do ticket KAM-059 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-059),
docs/tecnica/04 (§10.4, §11, §12, §13) e ADR-004, ADR-013, ADR-017.
Objectivo: price_book versionado, subscriptions, billing_cycles e commission_accruals (só 'sombra'); abertura
idempotente de ciclo+cobrança (72 h) numa payment_account 'plataforma_receita_propria'; ciclo paga por
payment.confirmed autenticado ou por confirmação de ops com dupla aprovação; plano -> entitlements.
- commission_enabled=false; sem parecer_ref (D8) o arranque falha se ligarem; nunca deduzir da liquidação.
- Não emitas facturas fiscais (DP 71/25; InvoiceProvider é Clusters). Preços do plano e IVA: não inventes.
Não expandas escopo: régua (KAM-058), margem cambial (KAM-081), débito directo (Clusters).
Testes: unit, integração (FakeProvider/Manual), idempotência, G-1 nos dois sentidos, RLS. PR com o template (§7).
```

---

## KAM-060 — Detecção de anomalias de pagamento (valor divergente, duplicados, padrões)

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-053, KAM-054 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` (§7.2, §8, §9, §14), `../docs/tecnica/08_Seguranca_Conformidade.md` (§4.6), `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§4), ADR-013 |

### Contexto
O motor de sinais do Piloto é determinístico: regras que gravam `fraud_signals` e accionam `reter_confirmacao`, `exigir_dupla`, `bloquear_contacto` ou `suspender_manual`; modelos estatísticos só em Clusters com dados do próprio *ledger*. Todos os limiares são **propostas a calibrar no Piloto**. Este ticket cobre os sinais de pagamento; a escada de sanções e o Trust & Safety de tenants são de KAM-097 (EPIC-09).

### Objectivo
Implementar o motor de regras sobre `payment_events`, `payment_charges` e `manual_confirmations`, a tabela `fraud_signals`, as acções automáticas sobre o `ManualProvider`, os alertas, e a reconciliação diária por extracto bancário carregado pelo dono (`ajuste_reconciliacao`).

### Critérios de Aceitação
- [ ] Existem as regras R-01 a R-08 (abaixo) como dados versionados com limiar configurável; cada uma tem um caso sintético que a dispara e um que não dispara.
- [ ] 3 `pagamento_divergente` na mesma conta em 1 h (limiar proposto) criam `fraud_signals` de severidade ≥ 3 e alertam ops; HMAC inválido acima de N/hora por conta (N proposto) alerta (F-05).
- [ ] `pagamento_orfao` cria sinal imediato e alerta; a métrica «órfãos abertos > 24 h» é 0 no teste de 7 dias simulados e dispara alerta se > 0.
- [ ] Um `pagamento_duplicado` cria `refund_cases` e sinal; o 2.º pagamento nunca confirma a encomenda (G6).
- [ ] Auto-compra: pagador cujo `payer_hmac` ou `contacts.phone_hmac` coincide com o do dono ou de funcionários cria sinal com acção `reter_confirmacao`; o `ManualProvider` respeita a acção (a confirmação fica retida até ops).
- [ ] Confirmações manuais por semana acima de k vezes a mediana do tenant (k proposto) criam sinal `exigir_dupla` para as seguintes (`../docs/tecnica/08` §4.6).
- [ ] O CSV de extracto carregado pelo dono é comparado com as cobranças `paga`; cada diferença gera `ajuste_reconciliacao` compensatório (nunca `UPDATE`) e um caso para ops; um CSV repetido não duplica ajustes.
- [ ] Os sinais não contêm telefone nem texto: só `contact_id`, `charge_id`, regra e severidade; o `detalhe` passa o *lint* de PII.
- [ ] Reproduzir 10 000 eventos sintéticos corre o motor em < 60 s e produz sinais idênticos em duas execuções (determinismo).

### Detalhes Técnicos
- **Componentes:** PAY, GOV, OBS. Módulos `services/pay/src/fraud/{rules,engine,actions}.ts`; DDL de `fraud_signals` em `../docs/tecnica/04` §6.3; correr por `payment_events` (gatilho) e por *job* periódico.
- **Regras (propostas):** R-01 divergência repetida; R-02 HMAC inválido em massa; R-03 órfão; R-04 duplicado; R-05 auto-compra (`payer_hmac`/`phone_hmac`); R-06 desvio de confirmações manuais; R-07 *no-show* de COD → exigir sinal por referência; R-08 diferença extracto × `paga`.
- **Acções:** `registar`, `reter_confirmacao`, `exigir_dupla`, `bloquear_contacto`, `suspender_manual` (tenant); enforcement no `ManualProvider` por *flags* em `entitlements`, nunca por escrita no ledger.
- **Fronteira com KAM-097:** este ticket produz sinais de pagamento; o consumo para sanções e reviews retidos é de KAM-097/REP.
- Extracto bancário: ingestão por CSV no Piloto; API do banco é Clusters e NÃO VERIFICADA.

### Testes Requeridos
- Unit: cada regra com casos positivo e negativo; determinismo.
- Integração: sinal → acção → `ManualProvider` (retenção efectiva).
- Cenários sintéticos: comprovativo falso repetido, callback forjado, auto-compra, duplicado.
- Carga: 10 000 eventos.

### Definition of Done
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Pagamento só por evento autenticado: o motor nunca escreve `paga`; só sinais e eventos compensatórios.
- [ ] Privacidade: sinais por `contact_id`; sem telefone nem texto em `detalhe`, logs ou eventos.
- [ ] Observabilidade: `fraud_signals_total{regra}`, painel de órfãos e de retenções.
- [ ] Isolamento: RLS em `fraud_signals`; caso na suite cruzada.
- [ ] Limiares registados como propostas a calibrar, com plano de revisão no Piloto.

### Handoff para Claude Code

```text
És o executor do ticket KAM-060 da KAMBÁ. Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-060),
docs/tecnica/04 (§7.2, §8, §9) e docs/tecnica/08 §4.6.
Objectivo: motor determinístico de regras R-01..R-08 sobre o ledger e as confirmações manuais, tabela fraud_signals,
acções reter_confirmacao/exigir_dupla/bloquear_contacto/suspender_manual aplicadas por flags no ManualProvider,
alertas e reconciliação diária por extracto CSV (ajuste_reconciliacao compensatório).
- Limiares são PROPOSTAS a calibrar; regras como dados versionados.
- O motor nunca altera estado de pagamento nem escreve 'paga'; sem PII nos sinais.
Não expandas escopo: sanções e T&S (KAM-097), modelos estatísticos (Clusters).
Testes: unit por regra, integração com ManualProvider, cenários sintéticos, determinismo. PR com o template (§7).
```

---

## KAM-175 — Um `DELETE` sem linhas no *ledger* `payment_events` não é recusado: o *trigger* por instrução só cobre o `TRUNCATE`

| Campo | Valor |
|---|---|
| Epic | EPIC-05 — Pagamentos e Billing |
| Fase | 0 |
| Tipo | fix |
| Prioridade | P1 |
| Estimativa | S |
| Dependências | KAM-053 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Pagamentos |
| Documentos de referência | `../db/migrations/versions/0029_ledger_de_pagamentos.py`, `../db/migrations/versions/0030_encomendas_e_estados.py` (a nota dos *triggers*), `../db/tests_pagamentos/test_porta.py`, `../db/tests_pagamentos/test_cadeia.py`, `../db/tests_pagamentos/test_downgrade.py`, `../db/tests_encomendas/test_isolamento.py`, `../docs/dividas-documentais.md` (dívidas 175 e 176), `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §6.2, `../docs/tecnica/08_Seguranca_Conformidade.md` §6, ADR-013, ADR-015 |

### Contexto

**A barreira que torna o *ledger* `append-only` tem um caso que passa, e o caso
é o que não apaga nada.** A revisão `../db/migrations/versions/0029_ledger_de_pagamentos.py`
protege a `platform.payment_events` com dois *triggers* sobre a mesma função
`platform.deny_mutation()`, os dois `ENABLE ALWAYS`:

* `payment_events_imutavel` — `BEFORE UPDATE OR DELETE … FOR EACH ROW`;
* `payment_events_sem_truncate` — `BEFORE TRUNCATE … FOR EACH STATEMENT`.

Um *trigger* por linha **não dispara quando não há linha nenhuma**. Logo um
`DELETE FROM platform.payment_events WHERE <predicado que não casa>` não é
recusado por nenhum dos dois: devolve `DELETE 0` a quem o escreveu e passa.

**Medido, e não deduzido.** A 2026-11-03, contra um PostgreSQL **18.6** real
(`pgvector/pgvector:0.8.7-pg18`, a mesma imagem do `../infra/compose/docker-compose.dev.yml`),
com a forma da `0029` reproduzida numa tabela de ensaio:

| Instrução | Forma da `0029` | Forma da `0030` (KAM-044) | Forma que este ticket impõe |
|---|---|---|---|
| `DELETE` **com** linhas | recusado (`42501`) | recusado | recusado |
| `DELETE` **sem** linhas | **`DELETE 0`** | recusado | recusado |
| `UPDATE` **sem** linhas | **`UPDATE 0`** | **`UPDATE 0`** | recusado |
| `TRUNCATE` | recusado | recusado | recusado |

**São duas metades e a dívida 175 só nomeia uma.** A dívida descreve o `DELETE`;
a mesma medição mostra que o `UPDATE` sem linhas **também** passa, pela mesma
razão e sem nada de novo — um `UPDATE … WHERE <predicado que não casa>` devolve
`UPDATE 0`. E mostra mais: a forma que o KAM-044 escreveu para o
`platform.order_state_log` (`BEFORE TRUNCATE OR DELETE … FOR EACH STATEMENT`)
fechava o `DELETE` e **deixava o `UPDATE` aberto** — medido a **2026-11-03**,
antes da revisão `0031`, que o **KAM-176** entregou a 2026-11-04 e que fechou
essa metade. A frase fica no passado porque é um registo de medição, e ficava a
descrever a forma antiga em presente (achado 15 da revisão adversarial do
KAM-176). Fechar aqui só o `DELETE` seria
repetir um nível abaixo a omissão que este ticket existe para fechar, pelo que
as duas metades entram nos critérios.

**A consequência, que é o que torna isto um defeito e não arrumação.** Nenhuma
linha se perde: o que falha é a **propriedade**, não os dados. Quem audita a
tabela — e é o que o `../docs/tecnica/08_Seguranca_Conformidade.md` §6 e o
critério de saída deste epic mandam fazer — corre a instrução proibida e lê
`DELETE 0` sem erro, que é indistinguível de «a tabela aceita `DELETE` e não
havia nada para apagar». A afirmação «`UPDATE`, `DELETE` e `TRUNCATE` sobre
`payment_events` falham» passa a ter de ser lida com uma ressalva que não está
escrita em sítio nenhum, e um *ledger* de dinheiro é o pior sítio para uma
ressalva tácita.

**O que fecha, e a prova de que é o `FOR EACH STATEMENT` que fecha.** Um
`BEFORE … FOR EACH STATEMENT` corre **uma vez por instrução**, antes de haver
linhas, pelo que a recusa é a mesma para o caso que apaga e para o que não
apaga. Medido nas duas direcções: com os dois *triggers* ligados, o `DELETE`
sem linhas é recusado; desligado **só** o por instrução, o mesmo `DELETE`
devolve `DELETE 0`. É esse par que torna o critério 4 um canário e não uma
afirmação.

**Como apareceu.** Na revisão adversarial do KAM-044 (PR #112), que ao escrever
a barreira do `order_state_log` reparou que a tabela anterior tem a mesma
lacuna. A nota da revisão dizia que a lacuna «fica registada no PR deste», e a
revisão respondeu o que era preciso responder: **o corpo de um PR não é
versionado**, pelo que registar ali é não registar. Está na **dívida 175** de
`../docs/dividas-documentais.md` (linha de versões 1.90), e este ticket é o
credor dela.

**Três tabelas irmãs têm a mesma lacuna e não são deste ticket.** Medido no
mesmo varrimento das revisões: a `platform.audit_log` (`0006`, KAM-012), a
`platform.tool_audit` (`0021`, KAM-028) e a `dat.llm_call_log` (`0023`,
KAM-030) escrevem todas o par «por linha para `UPDATE`/`DELETE`, por instrução
só para `TRUNCATE`» — a forma da `0029`, com as duas metades abertas. Não se
tocam aqui, e a razão é a fronteira que a própria dívida 175 desenhou: a
barreira de uma tabela decide-se em quem a tem. Ficam registadas na **dívida
176**, com credor por tabela. A `dat.llm_call_log` tem ainda uma pergunta
própria, porque é **particionada**: a `0023` mediu que o `BEFORE UPDATE OR
DELETE … FOR EACH ROW` e o `BEFORE TRUNCATE … FOR EACH STATEMENT` no pai são
aceites e que uma partição nova os herda, e **nada ali diz** se um
`BEFORE DELETE … FOR EACH STATEMENT` no pai se comporta do mesmo modo. Isso
mede-se no ticket dela, não neste.

### Objectivo

Fazer com que a `platform.payment_events` recuse `UPDATE`, `DELETE` e
`TRUNCATE` **independentemente de quantas linhas a instrução toca**, pela mesma
função `deny_mutation` e sem *trigger* novo: o que muda é a lista de eventos do
*trigger* por instrução que já existe. E deixar escrito, no ficheiro, qual dos
dois *triggers* passa a dar a propriedade — porque depois desta alteração o por
linha já não é o que a dá.

### Critérios de Aceitação

- [x] 1. O `payment_events_sem_truncate` da `0029` passa a
  `BEFORE TRUNCATE OR DELETE OR UPDATE … FOR EACH STATEMENT`, continua
  `ENABLE ALWAYS` e continua a chamar a `platform.deny_mutation()`. **Não há
  *trigger* novo e não há função nova**: os dois nomes de *trigger* ficam como
  estão, que é o que mantém verdes o `TestTriggersSaoAlways` do
  `../db/tests_pagamentos/test_cadeia.py` e os dois confrontos do
  `../db/tests_pagamentos/test_downgrade.py`, que prendem o par
  `[('payment_events_imutavel', 'A'), ('payment_events_sem_truncate', 'A')]`.
  Medido: um `DELETE` sem linhas e um `UPDATE` sem linhas passam a ser recusados
  com `42501` (`insufficient_privilege`), que é o `SQLSTATE` que a função já
  levanta e que a suite já afirma.
- [x] 2. **As duas metades, e não só a do `DELETE`.** O ensaio cobre os quatro
  casos, cada um com a sua asserção: `DELETE` sem linhas, `UPDATE` sem linhas,
  `DELETE` com linhas e `TRUNCATE`. Fechar só o `DELETE` satisfazia a dívida 175
  à letra e deixava aberta a metade que a medição deste ticket encontrou — e que
  é a metade que o KAM-044 deixou aberta no `order_state_log`.
- [x] 3. **O que a barreira não impede continua a não impedir**, e há ensaio que
  o prova em vez de o supor: o `INSERT` pela `platform.append_payment_event`
  passa, o `SELECT` passa, e o `DROP TABLE` do `downgrade` da `0029` passa — um
  `DROP TABLE` não é um `DELETE`, o que a `0029` já escreve e que aqui se mede
  (confirmado contra o PostgreSQL 18.6). Sem este critério, a prova de que a
  barreira morde é indistinguível de uma tabela que ninguém consegue abrir.
- [x] 4. **Canário obrigatório, e nos dois sentidos.** Desligado **só** o
  `payment_events_sem_truncate` — com o `payment_events_imutavel` ligado —, o
  `DELETE` sem linhas tem de **passar** (`DELETE 0`) e o `UPDATE` sem linhas
  também. É isso, e só isso, que prova que quem recusa o caso sem linhas é o
  *trigger* por instrução: com os dois ligados, os dois casos são recusados e
  nenhum dos dois ensaios distingue qual deles mordeu. O `ALTER TABLE` do
  canário corre na ligação **transaccional** e é revertido, pela razão escrita
  no `TestCanarioDoTrigger` do `../db/tests_encomendas/test_grafo.py`: um
  `ALTER TABLE` confirmado deixava a base do *gate* 8 sem barreira para os
  ensaios seguintes, e a suite passava a medir uma tabela sem *trigger*.
- [x] 5. **O `payment_events_imutavel` fica ou sai, com a razão escrita.**
  Medido: depois do critério 1 ele é **estritamente redundante** — com o por
  linha desligado e o por instrução ligado, um `DELETE` com linhas continua a
  ser recusado. A recomendação é **ficar**, e a razão não é defesa em
  profundidade: é que o `_desligar_trigger` do `../db/tests_pagamentos/test_cadeia.py`
  o desliga **pelo nome** para forjar um elo partido, e o
  `../db/tests_pagamentos/test_downgrade.py` prende os dois nomes. Qualquer das
  duas decisões serve; o que não serve é ficar sem a frase, porque quem ler a
  `0029` depois desta alteração vai ler o *trigger* por linha como a origem da
  propriedade, e já não é.
- [x] 6. **O `_desligar_trigger` do `../db/tests_pagamentos/test_cadeia.py`
  passa a desligar os dois**, e isto não é arrumação: é o único ensaio existente
  que esta alteração **quebra**. Ele desliga só o `payment_events_imutavel` e
  depois corre `DELETE FROM platform.payment_events WHERE id = %s` para partir
  um elo da cadeia de *hashes*; medido que, com o critério 1 aplicado, o
  *trigger* por instrução passa a recusar esse `DELETE`. O `_repor_trigger`
  continua a repor **o que estava** e não o que devia estar, pela razão que já
  está escrita nele.
- [x] 7. **A alteração entra na `0029` ou numa revisão nova, e a escolha está
  medida.** O que a decide é uma pergunta de facto: existe algum ambiente onde a
  `0029` já foi aplicada e que não se reconstrói de zero? O `alembic` guarda uma
  linha em `alembic_version` e mais nada, pelo que uma edição à `0029` é
  **invisível** para uma base que já a correu — se houver uma, a forma certa é
  uma revisão nova com `DROP TRIGGER` e `CREATE TRIGGER`, com `down_revision` a
  apontar para a última. Se não houver (e o *gate* 8 reconstrói sempre de zero),
  a edição no sítio é a forma certa, porque uma revisão nova para corrigir uma
  linha deixa duas verdades na cadeia. A resposta escreve-se no ticket; o que não
  se aceita é escolher sem a pergunta.
- [x] 8. A nota da `0029` passa a dizer o que os dois *triggers* fazem **depois**
  desta alteração, e porque é que são dois: o bloco do `_eventos()` que hoje diz
  «um *trigger* `BEFORE UPDATE OR DELETE` e outro `BEFORE TRUNCATE`» descreve a
  forma antiga, e uma nota que descreve a forma antiga é pior do que nenhuma. A
  nota do `../db/migrations/versions/0030_encomendas_e_estados.py` que aponta
  esta lacuna para a dívida 175 passa a dizer que ela tem credor.
- [x] 9. **O critério de saída do epic não se emenda aqui.** O segundo da lista
  diz «`UPDATE`, `DELETE` e `TRUNCATE` sobre `payment_events` falham para
  `kamba_app` e **`kamba_ops`**», e o `kamba_ops` não existe — é a **dívida
  167**, com credor KAM-053, e emendar a letra de um critério é de quem o
  escreveu. Fica dito, e fica como está: este ticket toca no *trigger*, não na
  redacção do critério.

### Detalhes Técnicos

- **Onde.** `../db/migrations/versions/0029_ledger_de_pagamentos.py`, a função
  `_eventos()` (o `CREATE TRIGGER payment_events_sem_truncate` e a nota do
  *docstring*), ou a revisão nova que o critério 7 decidir. Mais os ensaios de
  `../db/tests_pagamentos/` — `test_porta.py` (as recusas) e `test_cadeia.py`
  (o `_desligar_trigger`). O `../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`
  **não muda**: o §6.2 prescreve a tabela e a imutabilidade, não a lista de
  eventos do *trigger*.
- **A medição completa, para quem a quiser repetir.** Numa tabela de ensaio com
  a função `deny_mutation` e o par de *triggers* da `0029`, contra o PostgreSQL
  18.6: `DELETE` sem linhas → `DELETE 0`; `UPDATE` sem linhas → `UPDATE 0`;
  `DELETE` com linhas → `42501`. Com o por instrução em
  `BEFORE TRUNCATE OR DELETE OR UPDATE`: os quatro casos recusados, `INSERT` e
  `SELECT` intactos, `DROP TABLE` intacto. Com `SET session_replication_role =
  replica` e os dois `ENABLE ALWAYS`: recusado — o `ALWAYS` continua a valer
  para o por instrução, pela mesma razão da `0006` que a `0029` cita.
- **Porque é que o `UPDATE` cabe no mesmo *trigger*.** O PostgreSQL aceita
  `BEFORE UPDATE … FOR EACH STATEMENT`; o que um *trigger* por instrução não tem
  é `OLD` e `NEW`, e a `deny_mutation` não os usa — ela levanta excepção com o
  `TG_OP` e o `TG_TABLE_NAME`, que estão disponíveis nos dois níveis. É por isso
  que a alteração é à lista de eventos e não à função.
- **O `FOR EACH ROW` para `TRUNCATE` não existe**, o que é a razão original de
  serem dois *triggers* e não um: o `TRUNCATE` só admite por instrução. O que
  esta alteração faz é notar que o por instrução, existindo, cobre também os
  outros dois — e que o custo é nulo, porque uma instrução que fosse passar já
  era recusada.
- **O que a alteração não pode quebrar, e onde se verifica.** O
  `../db/tests_pagamentos/base.py` **não** apaga do `payment_events` na limpeza,
  de propósito e com a razão escrita; a FK `payment_events_charge_fk` é
  restritiva e não há `ON DELETE CASCADE` a entrar na tabela, pelo que nenhum
  `DELETE` legítimo noutra tabela cai aqui. Confirmar os dois antes de aplicar:
  um `DELETE` em cascata sobre uma tabela *append-only* passava a ser recusado,
  e a recusa aparecia no sítio errado.
- **O caminho pelo qual isto não se apanha hoje.** O
  `../db/tests_pagamentos/test_porta.py` corre `DELETE FROM platform.payment_events`
  **sem** `WHERE` sobre uma tabela com linhas, pelo que o *trigger* por linha
  morde e o ensaio fica verde. É a armadilha que o KAM-171 nomeia: o instrumento
  está certo e o predicado é que não cobre a população — e o caso que falta é
  precisamente o que não toca linha nenhuma.

### Testes Requeridos

- Integração (`db/tests_pagamentos/`): `DELETE FROM platform.payment_events
  WHERE <predicado que não casa>` é recusado com `42501`, como semente e como
  administrador.
- Integração: o mesmo para `UPDATE … WHERE <predicado que não casa>`.
- Integração: os casos que já existiam continuam verdes — `UPDATE`, `DELETE` e
  `TRUNCATE` com linhas, para os papéis de aplicação (por privilégio) e para o
  superutilizador (pelo *trigger*).
- Sonda positiva: `INSERT` pela `append_payment_event` e `SELECT` passam depois
  da alteração.
- Canário: desligado **só** o `payment_events_sem_truncate`, o `DELETE` sem
  linhas passa e o `UPDATE` sem linhas passa; o `ALTER TABLE` é revertido na
  mesma transacção.
- Catálogo: os dois *triggers* continuam a reportar `A` em
  `pg_trigger.tgenabled` depois da migração e depois do `downgrade` e novo
  `upgrade` — os dois confrontos do `test_downgrade.py` ficam como estão.
- *Gate* 8: a revisão (ou a edição) sobe, desce e volta a subir numa base limpa,
  sem objectos residuais.
- Não-regressão do `test_cadeia.py`: o ensaio do elo removido no meio continua a
  partir a cadeia, agora com os dois *triggers* desligados.

### Definition of Done

- [x] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [x] **As duas metades fechadas** — `DELETE` e `UPDATE` sem linhas —, cada uma
  com ensaio próprio.
- [x] **Canário verde quando a barreira morde e vermelho quando deixa de
  morder**, com o `ALTER TABLE` revertido.
- [x] A escolha entre editar a `0029` e abrir revisão nova **respondida pela
  pergunta do critério 7**, e não por preferência.
- [x] A nota da `0029` descreve a forma nova, e diz qual dos dois *triggers* dá
  a propriedade.
- [x] O `_desligar_trigger` do `test_cadeia.py` desliga os dois, e o ensaio do
  elo removido continua a provar o que provava.
- [x] *Gate* 8 verde: `upgrade`, `downgrade`, `upgrade` sem resíduos.
- [x] **A dívida 175 riscada** em `../docs/dividas-documentais.md`, neste PR.
- [x] **A dívida 176 não é riscada** — as três tabelas irmãs ficam aos seus
  credores — e a `0029` não ganha nenhuma alteração que lhes diga respeito.
- [x] Linha de «Controlo de versões» em cada documento formal tocado, e o campo
  `Versão` do cabeçalho a condizer.
- [x] Revisão adversarial independente, com os achados fechados por teste.

### Verificação dos Critérios de Aceitação

Medição de **2026-11-04**, contra o PostgreSQL **18.6** descartável que o
[`../db/gate_bd.py`](../db/gate_bd.py) levanta (`pgvector/pgvector:0.8.7-pg18`,
fixado por *digest*). Reproduz-se com:

```text
python db/gate_bd.py --suite tests_pagamentos    -> Ran 103 tests in 84.446s / OK
python db/mutacoes.py --aplicaveis               -> 953 mutacoes conferidas, 0 nao aplicaveis
python db/mutacoes.py tests_pagamentos           -> 14 corridas, 0 nao apanhadas
```

A terceira é a que prova que os ensaios **mordem**: corre o *gate* inteiro uma
vez por mutação, com uma barreira da `0029` desfeita de cada vez, e exige que
falhe. A mutação nova deste ticket — «o *trigger* por instrução volta a cobrir só
o `TRUNCATE`» — é apanhada por **quatro** ensaios, o primeiro deles o
`test_o_delete_sem_linhas_e_recusado`.

Eram **93** ensaios antes deste ticket e são **103** depois: entram dez, sete em
`TestBarreiraNaoDependeDeQuantasLinhas` e três em
`TestCanarioDoTriggerPorInstrucao`, os dois em
[`../db/tests_pagamentos/test_porta.py`](../db/tests_pagamentos/test_porta.py).
**Três dos dez entraram pela revisão adversarial** e estão nomeados nas células
1, 5 e na secção dos achados, abaixo.

**E a alteração quebrou exactamente os dois ensaios que o critério 6 previu, e
só esses.** Com o *trigger* já alterado e o `_desligar_trigger` ainda a desligar
um só, a suite saiu `Ran 93 tests / FAILED (errors=2)`, com
`42501 'tabela append-only: UPDATE proibido em payment_events'` no
`test_um_byte_alterado_com_superutilizador_e_apanhado` e
`42501 '… DELETE proibido …'` no
`test_uma_linha_removida_no_meio_e_apanhada_pelo_encadeamento`. É a medição que
torna o critério 6 um facto em vez de uma precaução.

| # | Critério | Estado | O que se mediu, e onde |
|---|---|---|---|
| 1 | O `payment_events_sem_truncate` passa a `BEFORE TRUNCATE OR DELETE OR UPDATE … FOR EACH STATEMENT`, `ENABLE ALWAYS`, mesma função, sem *trigger* nem função nova | **marcada** | A linha está na `_eventos()` da [`../db/migrations/versions/0029_ledger_de_pagamentos.py`](../db/migrations/versions/0029_ledger_de_pagamentos.py); os `ALTER TABLE … ENABLE ALWAYS` e os dois nomes ficaram como estavam. **A lista de eventos está presa no catálogo**, e passou a estar por causa da revisão adversarial (achado 10): os três confrontos que já existiam — `test_cadeia.TestTriggersSaoAlways.test_os_dois_triggers_do_ledger_sao_always`, `test_downgrade.TestDowngradeDa0029.test_em_head_os_triggers_do_ledger_sao_always` e `test_depois_de_voltar_a_subir_tudo_volta` — comparam **nomes e `tgenabled`** (`[('payment_events_imutavel', 'A'), ('payment_events_sem_truncate', 'A')]`) e não dizem nada sobre que eventos cada *trigger* cobre; valem para o `ENABLE ALWAYS` e para a reaplicação, não para a forma. Entrou o `test_a_lista_de_eventos_do_trigger_esta_no_catalogo`, que lê o `pg_get_triggerdef` dos dois e exige os três verbos no por instrução, os dois no por linha, o nível de cada um, e que o por linha **não** tenha `TRUNCATE` (o `FOR EACH ROW` não o admite, que é a razão de serem dois). Não se compara a frase inteira porque o `pg_get_triggerdef` reordena os eventos pela ordem canónica do catálogo, que não é a ordem em que a revisão os escreveu — o que é propriedade é o conjunto e o nível, não a ordem do texto. O `42501` é o da função, medido nos ensaios do critério 2 |
| 2 | As **duas metades**, cada caso com a sua asserção: `DELETE` sem linhas, `UPDATE` sem linhas, `DELETE` com linhas e `TRUNCATE` | **marcada** | Quatro asserções em `TestBarreiraNaoDependeDeQuantasLinhas`, com o predicado `WHERE id = -1` (o `id` é `GENERATED ALWAYS AS IDENTITY` e começa em 1, pelo que não casa com linha nenhuma **e não é constante**): `test_o_delete_sem_linhas_e_recusado` e `test_o_update_sem_linhas_e_recusado`, separados de propósito — uma asserção que cobrisse os dois não distinguia qual regrediu —, e `test_o_que_ja_era_recusado_continua_recusado` com os dois `subTest` do `DELETE` com linhas e do `TRUNCATE`. Os quatro saem `42501`. Mais um quinto: `test_os_dois_casos_sem_linhas_tambem_na_ligacao_de_semente` mede os dois casos sem linhas **fora** do `SAVEPOINT` do `assertErroSql`, na ligação de semente em `autocommit`, que é o que separa «a barreira recusa» de «o embrulho do ensaio recusa» |
| 3 | O que a barreira não impede continua a não impedir: `INSERT` pela porta, `SELECT` e o `DROP TABLE` do `downgrade` | **marcada** | `test_a_sonda_positiva_insert_pela_porta_e_select_passam`: o `append_payment_event` devolve `event_id` e os dois eventos do ensaio ficam legíveis depois da alteração. O `DROP TABLE` mede-se onde ele corre — `test_downgrade.TestDowngradeDa0029.test_o_downgrade_leva_tabelas_vistas_funcoes_indices_e_politicas` e `test_depois_de_voltar_a_subir_tudo_volta` correm o `downgrade` pelo `alembic` e falhariam se a barreira o apanhasse; um `DROP TABLE` não é um `DELETE` e o *trigger* não dispara (confirmado contra o 18.6). Sem este critério, as quatro recusas do critério 2 eram indistinguíveis de uma tabela inutilizada |
| 4 | Canário nos dois sentidos, com o `ALTER TABLE` revertido | **marcada** | `TestCanarioDoTriggerPorInstrucao.test_sem_o_trigger_por_instrucao_o_caso_sem_linhas_passa`: desligado **só** o `payment_events_sem_truncate` — e o ensaio lê o `tgenabled` do `payment_events_imutavel` e exige `'A'`, para que isto seja canário do por instrução e não de «a tabela não tem *triggers*» —, o `DELETE` sem linhas e o `UPDATE` sem linhas **passam**, com `rowcount == 0` nos dois. O lado «ligado, recusa» é o critério 2. O `ALTER TABLE` corre na ligação transaccional e o `finally` faz `rollback`, pela razão do `TestCanarioDoTrigger` de [`../db/tests_encomendas/test_grafo.py`](../db/tests_encomendas/test_grafo.py). Mais `test_com_o_por_instrucao_desligado_o_caso_com_linhas_continua_recusado`, que é a outra metade: com o por instrução desligado, um `DELETE` **com** linhas continua `42501` — pelo por linha |
| 5 | O `payment_events_imutavel` fica ou sai, **com a razão escrita** | **marcada** | **Fica**, e a razão está escrita no comentário imediatamente acima do `CREATE TRIGGER payment_events_sem_truncate` da `0029`: não é defesa em profundidade, é que o `_desligar_trigger` o desliga **pelo nome** e os dois confrontos do `test_downgrade.py` prendem o par de nomes — removê-lo era mexer em três ensaios para não ganhar barreira nenhuma. **A redundância está medida, e a primeira versão desta célula citava o ensaio errado** — achado 3 da revisão adversarial, `CONFIRMADO`. A afirmação é «com o **por linha** desligado e o por instrução ligado, um `DELETE` e um `UPDATE` com linhas continuam recusados», e o ensaio que estava citado (`test_com_o_por_instrucao_desligado_o_caso_com_linhas_continua_recusado`) desliga o *trigger* ao contrário: prova a proposição **inversa**, que o por linha ainda morde. Entrou o ensaio simétrico — `test_sem_o_por_linha_o_caso_com_linhas_continua_recusado` —, que desliga só o `payment_events_imutavel`, confirma que o por instrução ficou em `'A'`, semeia linhas (sem elas o por instrução recusaria de qualquer forma e a asserção deixava de medir «com linhas») e exige `42501` nos dois verbos. Os dois canários juntos dão a tabela inteira: cada *trigger* sozinho fecha o caso com linhas, e só o por instrução fecha o caso sem linhas. A *docstring* da `_eventos()` passa a dizer, por extenso, que quem dá a propriedade é o por instrução |
| 6 | O `_desligar_trigger` do `test_cadeia.py` desliga os dois, e o ensaio do elo removido continua a provar o que provava | **marcada** | O auxiliar passou a devolver um `dict` nome → `tgenabled` sobre a constante `TRIGGERS_DO_LEDGER`, a desligar os dois e a repor **o que estava** em cada um (o `_repor_trigger` mantém a disciplina que o seu próprio *docstring* explica: repor `ENABLE ALWAYS` fixo contaminava o `TestTriggersSaoAlways`). Os dois ensaios que a alteração quebrou — `test_um_byte_alterado_com_superutilizador_e_apanhado` e `test_uma_linha_removida_no_meio_e_apanhada_pelo_encadeamento` — voltam a verde provando o mesmo: o elo adulterado é o único apontado, e o buraco no meio é denunciado pelo `prev_hash` do elo seguinte. E o `TestTriggersSaoAlways`, que corre depois deles no mesmo ficheiro, continua a ler `'A'` nos dois |
| 7 | A alteração entra na `0029` ou numa revisão nova, **e a escolha está medida** | **marcada** | **Edição no sítio**, e a pergunta do critério respondeu-se por medição: não existe base onde a `0029` tenha sido aplicada e que não se reconstrua de zero. Três medições, escritas também no comentário da `0029`: (a) o *gate* 8 corre contra a base descartável que o `db/gate_bd.py` cria e destrói — o `exigir_base_descartavel` de [`../db/tests/base.py`](../db/tests/base.py) recusa qualquer nome que não seja o dela, por **igualdade** e não por sufixo, e a suite faz `downgrade base`; (b) não há alvo de `Makefile` nem *script* de `initdb` que corra `alembic` contra a base do `../infra/compose/docker-compose.dev.yml` — `grep -rn alembic` sobre o `Makefile`, o `infra/compose/`, o `.github/workflows/` e os `*.sh`/`*.tf` dá **zero** fora de `db/` e de prosa em `docs/`, e o único ficheiro de `initdb` é o `01-bases-e-extensoes.sql`; (c) os `../infra/envs/staging/` e `../infra/envs/prod/` apontam para o módulo `provider-pendente`, com `chaves_ssh_de_administracao = []` e a nota «não há host», e não há ficheiro `*.tfstate` no repositório. E **(d), que entrou pela revisão adversarial** (achado 1, `MORTO`): o revisor notou que o `../db/migrations/README.md` §«Como se usa» manda correr `python -m alembic … upgrade head` à mão e que o PostgreSQL do compose guarda os dados num volume **nomeado** (`postgres-data`), que sobrevive a `make down` — logo uma máquina de desenvolvimento seria uma base nessas condições. **Não é**, e o próprio README o diz no seu último parágrafo: «não há ainda forma de aplicar as migrações ao PostgreSQL do compose de desenvolvimento: a rede de dados é interna e não publica portas». Medido no `../infra/compose/docker-compose.dev.yml`: o serviço `db` não tem `ports:` («sem `ports:`, de propósito», verificado por execução a 2026-10-10) e está só na rede `data`, que é `internal: true` — o `alembic` do anfitrião não lhe chega. A medição (b) respondia a uma pergunta mais estreita do que o critério faz, e o achado tinha razão nisso; a resposta ao critério não muda, e agora tem a medição que lhe faltava. Uma revisão nova para corrigir uma linha deixava duas verdades na cadeia.<br><br>**E a frase «a resposta oposta à do KAM-176, pela mesma pergunta e com a mesma regra» era falsa** — achado 2, `CONFIRMADO`. A `0029` também fundiu em `main` (`94bd634`, #104), antes da `0030` (`84f3169`, #112), pelo que o critério 5 do KAM-176 — que decide por «a `0030` fundiu, logo qualquer clone que tenha corrido `alembic upgrade head` a tem» — aplicado à `0029` daria **revisão nova**, e não edição no sítio. As duas regras são diferentes: a do KAM-175 pergunta se existe **base viva** que a correu e não se reconstrói; a do KAM-176 toma o ter fundido como suficiente. Pela medição deste ticket, a regra do KAM-176 não se sustenta nem para a `0030` — não há base nessas condições para revisão nenhuma. **Não se emenda aqui:** o critério 5 do KAM-176 dá a resposta por escrito e com razão, e emendar a letra de um critério é de quem o escreveu. O KAM-176 segue a letra dele (revisão nova) e a divergência fica registada no bloco dele, devolvida a quem o escreveu |
| 8 | A nota da `0029` descreve a forma nova; a nota da `0030` diz que a dívida 175 tem credor | **marcada** | A *docstring* da `_eventos()` da `0029` deixou de dizer «um *trigger* `BEFORE UPDATE OR DELETE` e outro `BEFORE TRUNCATE`» e passa a dizer o que cada um cobre, qual dá a propriedade, que o por linha é estritamente redundante, e porque é que são dois (o `FOR EACH ROW` não admite `TRUNCATE`). A nota dos *triggers* da [`../db/migrations/versions/0030_encomendas_e_estados.py`](../db/migrations/versions/0030_encomendas_e_estados.py) passa a dizer que a dívida 175 **tem credor e está paga** (KAM-175) e que a metade do `UPDATE` continua aberta ali, com credor KAM-176 — nenhuma linha de DDL da `0030` é tocada |
| 9 | O critério de saída do epic **não se emenda aqui** | **marcada** | Fica como está. O `kamba_ops` do segundo critério de saída não existe nesta base — os papéis são oito e nenhum se chama assim, medido no `ATRIBUTOS` de [`../db/bootstrap.py`](../db/bootstrap.py) (`migrator`, `app`, `batch`, `resolver`, `identity`, `audit`, `agr`, `pay_hooks`) e preso no `../db/tests/test_privilegios.py`; a primeira versão desta célula citava o `PAPEIS_DE_APLICACAO` do `test_porta.py`, que tem **três** entradas e não registava nada sobre oito — achado 8 da revisão adversarial —, é a **dívida 167** com credor KAM-053, e emendar a letra de um critério é de quem o escreveu. O diff deste PR não toca na §2 nem na lista de critérios de saída do epic |

**Fora dos critérios, uma alteração que a correcção obriga e que vale ser dita:
a mutação do `payment_events_imutavel` deixou de poder ser morta.** O
[`../db/mutacoes.py`](../db/mutacoes.py) tinha «revisão 0029: o *trigger* de
imutabilidade deixa de cobrir o `DELETE`» (`BEFORE UPDATE OR DELETE` →
`BEFORE UPDATE`, no por linha). Depois do critério 1 essa mutação
**sobreviveria** — o `DELETE` continua recusado pelo outro *trigger* —, e uma
mutação que não se consegue matar não mede cobertura. Foi substituída por
«revisão 0029: o *trigger* por instrução volta a cobrir só o `TRUNCATE`»
(`BEFORE TRUNCATE OR DELETE OR UPDATE` → `BEFORE TRUNCATE`), que repõe
exactamente o defeito que este ticket fecha, e **está apanhada**:
`python db/mutacoes.py tests_pagamentos` → `14 mutacao(oes) corrida(s), 0 nao
apanhada(s)`, com a nova a morrer em quatro ensaios, o primeiro deles o
`test_o_delete_sem_linhas_e_recusado`. É esse o sentido «vermelho quando deixa de
morder» do canário: com a lista de eventos reposta na forma antiga, a revisão
deixa de fechar o caso sem linhas e os ensaios novos ficam vermelhos.

**E a contagem das mutações da `0029` é catorze, não quinze.** O comentário do
`../db/mutacoes.py` escrito pelo KAM-044 diz «quinze», e eram catorze no dia em
que a frase foi escrita: medido com `grep -c "', REV29,"` sobre o ficheiro em
`c75d523` (**14**) e depois da troca (**14**, porque uma mutação substitui uma).
Corrigido no mesmo PR, por ser um número em prosa dentro de um ficheiro que este
ticket já altera e porque esta secção o citava — não entra como linha de dívida.

#### Definition of Done

| Caixa | Estado | Prova |
|---|---|---|
| Todos os CA satisfeitos e demonstráveis | **marcada** | Os nove acima, cada um com ensaio nomeado |
| As duas metades fechadas, cada uma com ensaio próprio | **marcada** | `test_o_delete_sem_linhas_e_recusado` e `test_o_update_sem_linhas_e_recusado` |
| Canário verde quando morde e vermelho quando deixa de morder, com o `ALTER TABLE` revertido | **marcada** | O «verde quando morde» é o critério 2; o «passa quando se desliga» é `test_sem_o_trigger_por_instrucao_o_caso_sem_linhas_passa`, com `rollback` no `finally`; e o «vermelho quando a barreira sai da revisão» é a mutação nova, abaixo |
| A escolha respondida pela pergunta do critério 7 | **marcada** | As três medições do critério 7, escritas no ficheiro e não só aqui |
| A nota da `0029` descreve a forma nova e diz qual *trigger* dá a propriedade | **marcada** | Critério 8 |
| O `_desligar_trigger` desliga os dois, e o ensaio do elo removido continua a provar o que provava | **marcada** | Critério 6, com a saída `FAILED (errors=2)` de antes da emenda como controlo |
| *Gate* 8 verde: `upgrade`, `downgrade`, `upgrade` sem resíduos | **marcada** | Localmente, `db/gate_bd.py --suite tests_pagamentos` → 100 ensaios, `OK`, e inclui o `TestDowngradeDa0029` inteiro (`downgrade` até à `0028` e novo `upgrade`, com tabelas, vistas, funções, índices e políticas confrontados em cada ponta); mais `db/mutacoes.py tests_pagamentos`, que corre o gate inteiro uma vez por mutação. No CI, o *job* «gate 8 — migrações» do PR, verde na corrida registada no corpo |
| A dívida 175 riscada neste PR | **marcada** | Linha 175 de [`../docs/dividas-documentais.md`](../docs/dividas-documentais.md) riscada, com os nomes dos ensaios na própria linha |
| A dívida 176 não é riscada, e a `0029` não ganha nada que lhes diga respeito | **marcada** | A linha 176 fica inteira, com os quatro credores (KAM-012, KAM-028, KAM-030, KAM-176). O diff não toca na `0006`, na `0021`, na `0023`, nem na parte de DDL da `0030` |
| Linha de «Controlo de versões» em cada documento formal tocado, e o campo `Versão` a condizer | **marcada** | Este epic em **1.8** (cabeçalho e última linha a condizer) e `docs/dividas-documentais.md` em **1.94** |
| Revisão adversarial independente, com os achados fechados por teste | **marcada** | Uma passagem sobre o ramo empurrado, por um agente que não viu este raciocínio: **treze achados, dez `CONFIRMADO`**, verificados um a um contra a árvore que funde. Cinco fecharam por **ensaio novo ou emenda de ensaio**, cinco por emenda de texto, um por dívida (a **178**) e dois ficaram `MORTO` com a evidência que os matou. A tabela está na secção seguinte |

#### Achados da revisão adversarial

Treze levantados, **dez `CONFIRMADO`** e três `PLAUSÍVEL`. Nenhum mostrou o SQL
errado: o que mostraram foi **cinco afirmações a valer menos do que diziam
valer**, que é o modo de falha desta casa. Os dois `must fix` eram os dois sobre
a decisão do critério 7, e os dois resolveram-se por medição — um ficou `MORTO`,
o outro era uma frase falsa que saiu.

Cada achado foi reverificado contra `6684b32` e não contra o `a4f3701` que a
revisão leu: o ramo ganhou entretanto o *commit* de integração do `main`, e dois
achados (o 6 e o 7) já estavam fechados por ele quando a revisão respondeu.

| # | Achado | Estado | O que o fechou |
|---|---|---|---|
| 1 | A medição (b) do critério 7 responde a uma pergunta mais estreita: o `db/migrations/README.md` manda correr `alembic upgrade head` à mão, e a base do compose tem volume **persistente** | **MORTO** | O último parágrafo do próprio README: «não há ainda forma de aplicar as migrações ao PostgreSQL do compose de desenvolvimento: a rede de dados é interna e não publica portas». Medido no compose: o serviço `db` não tem `ports:` e está só na rede `data`, `internal: true`. O `alembic` do anfitrião não lhe chega — **mas o achado tinha razão sobre a pergunta**, e a medição (d) entrou na célula 7 por causa dele |
| 2 | «A resposta oposta à do KAM-176, pela mesma pergunta e com a mesma regra» é falso: a `0029` também fundiu em `main` | **CONFIRMADO** | A frase saiu. A `0029` fundiu em `94bd634` (#104) e a `0030` em `84f3169` (#112); as duas regras são de facto diferentes, e a do KAM-176 aplicada à `0029` daria revisão nova. A divergência está escrita na célula 7 e **devolvida a quem escreveu o critério 5 do KAM-176** — que se segue à letra |
| 3 | A redundância do por linha é dada como «medido» e o ensaio citado prova a proposição **inversa** | **CONFIRMADO** | Ensaio novo: `test_sem_o_por_linha_o_caso_com_linhas_continua_recusado`, que desliga só o `payment_events_imutavel` e exige `42501` nos dois verbos com linhas semeadas |
| 4 | «Vinte caixas marcadas» e as onze caixas da DoD continuavam `- [ ]` no bloco | **CONFIRMADO** | As onze passaram a `- [x]`. Eram nove marcadas de vinte e são vinte |
| 5 | O `docs/tecnica/04` §6.2 **prescreve** a lista de eventos (linhas 357 e 359), ao contrário do que os *Detalhes Técnicos* dizem, e passou a descrever a forma antiga | **CONFIRMADO** | **Dívida 178**, com credor **KAM-053**. Não se emenda aqui: o ticket manda por escrito não tocar naquele documento, e emendar a letra de uns *Detalhes Técnicos* é de quem os escreveu. O *gate* 3b não o apanha — a superfície de `docs/tecnica/**` do `canon_lint` corre só o nível 1, variantes de nome |
| 6 | «A `0029` continua com quinze mutações»: são **catorze** | **CONFIRMADO** | Já fechado em `6684b32`, antes de a revisão responder: `grep -c "', REV29,"` dá 14 em `c75d523` e 14 depois da troca. O comentário de `db/mutacoes.py` que era a fonte do erro foi corrigido no mesmo *commit* |
| 7 | Colisão do `1.94` em `docs/dividas-documentais.md` com o que o #118 já inscreveu | **CONFIRMADO** | Já fechado em `6684b32`: a nossa linha passou a `1.95`. O achado lia o `a4f3701`, onde a colisão estava |
| 8 | «como o `PAPEIS_DE_APLICACAO` do `test_porta.py` já registava» — tem três entradas, não registava nada sobre oito papéis | **CONFIRMADO** | A citação passou para o `ATRIBUTOS` do `db/bootstrap.py`, que é onde os oito estão |
| 9 | A *docstring* do `test_o_que_ja_era_recusado_continua_recusado` diz que ele mede «com linhas», e depois da correcção a população deixou de ser carga da asserção | **CONFIRMADO** | A *docstring* foi reescrita: diz que **media** o caso com linhas e deixou de o medir por causa deste ticket, e remete para o canário, que é quem o mede agora |
| 10 | Nada no catálogo prendia a **lista de eventos**: os três confrontos comparam nomes e `tgenabled` | **CONFIRMADO** | Ensaio novo: `test_a_lista_de_eventos_do_trigger_esta_no_catalogo`, pelo `pg_get_triggerdef`. A célula 1 deixou de dizer que «o catálogo confirma» o que o catálogo não confirmava |
| 11 | O predicado constante-falso (`WHERE false`) não estava medido, e a propriedade é afirmada sem ressalva | **MORTO** | Medido: o `WHERE false` **é** recusado. Entrou como `subTest` ao lado do `WHERE id = -1` nos dois ensaios das metades, em `PREDICADOS_SEM_LINHAS`. O `One-Time Filter: false` não impede o *trigger* por instrução de disparar |
| 12 | A metade «`DROP TABLE` do `downgrade`» do critério 3 apoia-se numa corrida que o revisor não pôde repetir | **PLAUSÍVEL → fechado** | O *job* «gate 8 — migrações» do PR, que corre `TestDowngradeDa0029` inteiro, com a corrida citada no corpo do PR. O revisor não levantou base, e di-lo |
| 13 | Um `INSERT … ON CONFLICT DO UPDATE` passa a ser recusado **mesmo sem conflito**, pelo que «o custo é nulo» não é estritamente verdade | **CONFIRMADO** | Medido e **declarado** em vez de ficar surpresa: `test_o_insert_com_on_conflict_do_update_tambem_e_recusado`. Não quebra caminho nenhum hoje — a `append_payment_event` não usa `ON CONFLICT`, e a idempotência dela vem do `FOR UPDATE` na cobrança e da `payment_events_uq` —, mas quem escrever a próxima porta precisa de o saber antes |

**O que a revisão procurou e não encontrou**, que é a parte que distingue «não
encontrei» de «não procurei»: caminhos legítimos que a barreira passe a morder
(varrimento ficheiro a ficheiro de toda a `db/`, mais os `.ts` de
`packages/core-ts/src/pagamentos/` — zero, sem `ON DELETE CASCADE`, sem FK a
referenciar a tabela, sem `MERGE`); canário não revertido ou estado de *trigger*
contaminado (o `finally` e o `tearDown` revertem os dois); `rowcount` a devolver
`-1` (e, mesmo que devolvesse, a asserção **falhava** em vez de passar
falsamente); `assertErroSql` satisfeito por privilégio em vez de pelo *trigger*
(o canário mata-o: o **mesmo** papel corre a instrução com sucesso quando o
*trigger* está desligado); e escopo (`git diff --stat` toca sete ficheiros,
com `.github/`, `ci/`, `specs/01` e `docs/tecnica/` intactos).

### Handoff para Claude Code

```text
És o executor do ticket KAM-175 da KAMBÁ.
Lê specs/EPIC-05_Pagamentos_Billing.md (bloco KAM-175 e bloco KAM-053),
db/migrations/versions/0029_ledger_de_pagamentos.py (a funcao _eventos),
db/migrations/versions/0030_encomendas_e_estados.py (a nota dos triggers),
db/tests_pagamentos/test_porta.py, db/tests_pagamentos/test_cadeia.py,
db/tests_pagamentos/test_downgrade.py, db/tests_pagamentos/base.py,
db/tests_encomendas/test_isolamento.py e db/tests_encomendas/test_grafo.py.
Objectivo: a platform.payment_events recusa UPDATE, DELETE e TRUNCATE
independentemente de quantas linhas a instrucao toca.
- O payment_events_sem_truncate passa a BEFORE TRUNCATE OR DELETE OR UPDATE ...
  FOR EACH STATEMENT, ENABLE ALWAYS, com a mesma funcao deny_mutation. Sem
  trigger novo e sem funcao nova: os dois nomes ficam como estao, senao partes o
  TestTriggersSaoAlways e os dois confrontos do test_downgrade.py.
- SAO DUAS METADES. A divida 175 fala do DELETE; o UPDATE sem linhas tambem
  passa hoje, pela mesma razao. Fecha as duas. Medido contra o PostgreSQL 18.6:
  com a forma da 0029, DELETE sem linhas da DELETE 0 e UPDATE sem linhas da
  UPDATE 0; com a forma do KAM-044 (TRUNCATE OR DELETE), o UPDATE continua a
  passar -- nao copies essa forma, que e meia.
- Canario obrigatorio: desligado SO o payment_events_sem_truncate, o DELETE sem
  linhas tem de passar. Com os dois ligados nenhum ensaio distingue quem mordeu.
  O ALTER TABLE corre na ligacao transaccional e e revertido -- ver o
  TestCanarioDoTrigger de db/tests_encomendas/test_grafo.py.
- O _desligar_trigger de db/tests_pagamentos/test_cadeia.py passa a desligar os
  dois. E o unico ensaio que esta alteracao quebra: ele apaga uma linha para
  partir a cadeia de hashes, e o trigger por instrucao passa a recusar isso.
- Antes de escolher onde a alteracao entra, responde: existe ambiente onde a 0029
  ja foi aplicada e que nao se reconstroi de zero? Se existir, revisao nova com
  DROP TRIGGER e CREATE TRIGGER. Se nao, edicao no sitio. Escreve a resposta.
- Sonda positiva: INSERT pela append_payment_event e SELECT continuam a passar, e
  o DROP TABLE do downgrade tambem (um DROP TABLE nao e um DELETE).
- Risca a divida 175 de docs/dividas-documentais.md neste PR.
Nao expandas escopo: as tres tabelas irmas da divida 176 (platform.audit_log do
KAM-012, platform.tool_audit do KAM-028, dat.llm_call_log do KAM-030) NAO se
tocam -- a barreira de uma tabela decide-se em quem a tem, e a llm_call_log e
particionada e tem uma pergunta propria. O kamba_ops do segundo criterio de saida
do epic e a divida 167, com credor KAM-053: nao o emendes.
Testes: as quatro recusas, as duas sondas positivas, o canario nos dois sentidos,
o catalogo depois do downgrade, gate 8, e a nao-regressao do test_cadeia.py.
PR com o template da seccao 7 de specs/01_Engineering_Standards_e_Handoff.md, e com
o titulo na forma tipo(KAM-175): descricao no imperativo.
Commits: fix(KAM-175): …
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| Risco / item | Estado | Impacto | Mitigação ou critério de saída | Decisão |
|---|---|---|---|---|
| Sem contrato de facilitador a tempo (banco, EMIS, ProxyPay/AppyPay) | NÃO VERIFICADO (prazos de onboarding, semanas por banco) | Sem camada de pagamento autenticado | `ManualProvider` com limites; KAM-056 atrás de *flag*; H5 como gatilho de pivô | D4 |
| Preços do ProxyPay; rate limit; janela de duas chaves; assinatura do callback OPG | NÃO VERIFICADO | Custo e segurança do adaptador | Perguntas por escrito (KAM-103); OPG como dica + `status_pull`; nada em configuração antes de resposta escrita | D4 |
| Assinatura, *retries* e idempotência da AppyPay | NÃO VERIFICADO (INDÍCIO por SDKs) | Segundo facilitador inviável | KAM-057: só implementar com HMAC ou consulta confirmada | D4 |
| Enquadramento BNA do desenho A (facilitador técnico), do *push* OPG e da comissão | INDÍCIO até parecer (a confirmar por parecer) | Infracção regulatória | Guardas G-1..G-6; comissão desligada; `parecer_ref` obrigatório para activar | D8 |
| Canal operacional da KAMBÁ para falar com o dono (régua) e categoria Meta do *template* de cobrança | NÃO VERIFICADO | Régua sem canal legítimo | `OwnerNotifier` com *fallback* de ops; pergunta escrita à Meta | D10, D2 |
| Comprovativo falso no `ManualProvider`; conta WhatsApp do dono sequestrada | CONFIRMADO (fraude documentada) | Perda por fraude | Desafio de valor, dupla verificação, limites diários, notificação por segundo canal | — |
| Limites do `ManualProvider` (50 000 / 20 000 Kz), régua D+3/7/10, banda cambial ±5%, limiares de anomalia | Propostas | Calibração errada | Calibrar no Piloto com dados reais; valores em `entitlements` e configuração versionada | — |
| Divergência de contrato `valor_minor` (03/04) vs `valor_kz` (06 §4) e `callback_hmac_ok` vs `authn_ok` | Inconsistência documental | Contratos de evento incompatíveis | KAM-055 fixa `valor_minor` e `authn_ok`; actualizar `../docs/tecnica/06` | — |
| PME informal sem NIF fora do pagamento integrado | NÃO VERIFICADO (pessoa singular) | Segmento sem T2 | T1 com limite mais baixo ou T0; decisão de produto/GOV | D4 |
| Quem paga os custos em USD e o regime cambial/fiscal da receita | NÃO VERIFICADO | Margem e conformidade | Registar com contabilista antes de preços finais; alerta de margem em KAM-081 | D9 |
| Localização dos dados de pagamento (Luanda vs JNB) | Em aberto | Transferência sem registo APD | Seguir KAM-069/KAM-105; dados sintéticos até lá | D1 |

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
| 1.0 | Outubro 2026 | Emissão inicial: 9 tickets (KAM-052 a KAM-060) — interface PaymentProvider, ledger, ManualProvider, eventos de pagamento, ProxyPay, avaliação AppyPay, régua, billing da plataforma e anomalias. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-129: as 3 referências ao anexo E2 e ao directório de evidência passam a `../docs/tecnica/evidencia/…`; antes não resolviam de posição nenhuma. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-145: os **16** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | **KAM-052 entregue.** Secção «Verificação dos Critérios de Aceitação» no bloco, com os **nove** critérios e as **seis** caixas do DoD, cada um com prova nomeada. **Catorze caixas marcadas e uma vazia**, e a vazia é a dos **dois revisores**: metade cumpre-se (a decisão sobre o `humanOnly` está no PR) e a outra não — nesta fase funde-se com CI verde sem esperar revisão humana, e uma revisão adversarial é evidência e não um revisor. Fica dito no PR que este é um ticket **P0 de dinheiro** e que o critério pede dois revisores **explicitamente**, porque é informação que o fundador pode querer usar para abrir excepção. **Duas divergências face à letra, declaradas:** a regra de activação segue os *Detalhes Técnicos* e não o critério 2 (o `desconhecido` do AppyPay activava-se pela letra, dívida 151), e o `beneficiary_kind` segue o dicionário §3.4 e não o §6.2 (o gate 3b devolve dezanove achados sobre uma migração copiada à letra, dívida 149). **O `tenant_id` anulável foi decidido pelo fundador** (2026-10-29) contra uma lista fechada que dizia que as duas da auditoria eram as únicas. **E uma revisão adversarial independente reprovou o ramo** com 23 achados CONFIRMADO, 5 deles *must fix* — três eram barreiras que não podiam falhar nas condições em que tinham sido declaradas satisfeitas: o *harness* dava verde a um adaptador que não verifica assinatura nenhuma, o *lint* de dinheiro não via o idioma da casa, e o `capabilities.metodos` não era lido por linha nenhuma. Todos corrigidos; registo em `../docs/analises/ANALISE-41-interface-paymentprovider.md`. | Equipa KAMBÁ |
| 1.4 | Novembro 2026 | **KAM-053 entregue.** Secção «Verificação dos Critérios de Aceitação» no bloco, com os **nove** critérios e as **sete** caixas do DoD, cada um com prova nomeada. **Onze caixas marcadas e cinco vazias**, e as cinco têm razão escrita: o critério 9 pede uma coluna com um nome que é **variante de nível 1** do *gate* 3b (`callback_hmac_ok`) e nenhuma excepção o salva — a vista existe com `authn_hmac_ok` e o que este ticket entrega é a medição, porque mudar o que o *gate* aceita é regra de bloqueio; a privacidade cumpre-se numa metade (a porta recusa um `payload` ou um `motivo` com padrão de telefone, com os mesmos padrões do `evt_emitir`) e não na outra (mascarar referências em logs, que exige o serviço `pay`); a observabilidade emite duas das três métricas e nenhuma chega a um colector; e os **dois revisores** não se cumprem, como no KAM-052 — fica dito que é um **P0 de dinheiro** e que o critério os pede explicitamente. **Decide a pergunta que o `../docs/tecnica/04` §6.2 deixou escrita para este ticket:** o `authn_method` fica com quatro valores, e a premissa da pergunta era falsa — um `pagamento_confirmado` **nunca** é `sistema`, porque a restrição `confirmar_exige_autenticacao` não o inclui e a base recusa (medido). **Quatro defeitos que a suite apanhou na própria revisão**, todos corrigidos: o `STRICT` do `payment_event_row_hash` com o `coalesce` no corpo em vez de nos chamadores (62 ensaios no mesmo `23502`); o papel novo sem `USAGE` no esquema; a guarda de PII do `evt_emitir` que **não vê** o `payload` do ledger, de onde saiu a guarda da própria porta; e a chave do `ci/secdef_allowlist.yaml` sem os nomes dos parâmetros, que o `pg_get_function_identity_arguments` inclui — a `audit_encadear()` escondeu-o desde o KAM-004 por não ter argumentos, e a primeira entrada com argumentos deu seis falhas no X-05. **Um achado sobre uma barreira que não se consegue exercitar:** o `WITH CHECK` da `tenant_iso` sobre a `payment_charges` é inalcançável pelo `kamba_app`, porque o `assert_beneficiary` corre `BEFORE INSERT` e recusa primeiro nas duas formas de o tentar — fica medido em vez de suposto. | Equipa KAMBÁ |
| 1.5 | Novembro 2026 | **KAM-053, revisão adversarial: o ramo foi reprovado e corrigido.** Doze classes procuradas, doze achados, onze confirmados por medição, três `must fix` — e os três tinham a mesma assinatura, que é o modo de falha que esta casa nomeia: **a caixa estava marcada e o ensaio que a apoiava media outra coisa.** O mais grave: o `kamba_app` criava uma cobrança **já em `paga`** com zero eventos no ledger, porque o `estado` tinha domínio e não tinha valor inicial imposto — a caixa do DoD dizia «não existe caminho de código que escreva `paga` fora de `append_payment_event`» e tentava quatro vias, e a quinta era a óbvia; e o único detector, o *job* do §8, excluía-a por construção, porque só compara cobranças **com** eventos. Os outros dois: as duas vistas sem `GRANT` (a âncora externa falhava na primeira execução real, e nenhum ensaio o via porque os de catálogo inspeccionam como administrador), e **nove** das vinte e três colunas do ledger fora da cadeia de *hashes* — o `actor_id` e o `tenant_id` incluídos —, com o ensaio nomeado a varrer as posições de argumento da função, isto é, só os campos que já estavam dentro. Todos corrigidos com ensaio próprio, mais seis `should fix` (o `p_account_id => NULL` a saltar o G2, a enumeração do `webhook_token` pelo papel dos *webhooks*, o `pagamento_orfao` que a sua própria tabela torna impossível de escrever, duas células do dicionário erradas e a afirmação de que o 404 é uniforme no tempo). **E catorze mutações, com uma que sobreviveu** e que era um ensaio a escrever o estado que outro ensaio afirma — hoje as catorze são apanhadas. As caixas marcadas continuam onze e as vazias cinco; o que mudou foi o que as apoia. | Equipa KAMBÁ |
| 1.6 | Novembro 2026 | **KAM-172:** a allowlist `EM_UNIDADE_MENOR` do *gate* 8 está **ratificada** (2026-11-03, [`../docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md`](../docs/adr/ADR-L008-allowlist-de-colunas-em-unidade-menor.md)). O **KAM-053** fundiu **no mesmo dia** da decisão e inscreveu as suas três entradas com a pergunta escrita como aberta (a ordem dentro do dia é INDICIO: o *commit* tem hora, a decisão tem data) — o ADR-L008 cobre-as, e nenhuma se mexe. O bloco leva a nota; o **KAM-055** leva a sua, que é outra: ele não acrescenta coluna de dinheiro nenhuma a `platform` (a `payment_charges` e a `payment_events` já vieram com o KAM-053) e a divergência do doc 06 §4, que exemplifica `valor_kz`, continua a resolver-se contra o sufixo `_kz`, agora com canário que o prova. | Equipa KAMBÁ |
| 1.7 | Novembro 2026 | **KAM-175** acrescentado, e **não entregue no mesmo PR**: o que se entrega é o ticket, não a correcção. Fecha a dívida 175 de [`../docs/dividas-documentais.md`](../docs/dividas-documentais.md), que a revisão adversarial do KAM-044 mediu de passagem: a barreira *append-only* da `platform.payment_events` tem um caso que passa, e é o que não apaga nada. O `payment_events_imutavel` da `0029` é `FOR EACH ROW` e **não dispara quando não há linhas**; o `payment_events_sem_truncate` é `FOR EACH STATEMENT` mas só em `BEFORE TRUNCATE`. Logo um `DELETE` com um predicado que não casa devolve `DELETE 0` e passa. **Medido a 2026-11-03 contra um PostgreSQL 18.6 real** (`pgvector/pgvector:0.8.7-pg18`, a imagem do `../infra/compose/docker-compose.dev.yml`), com a forma da `0029` reproduzida numa tabela de ensaio — e a medição acrescentou à dívida **duas coisas que ela não dizia**. Primeira: o `UPDATE` sem linhas **também** passa (`UPDATE 0`), pela mesma razão, pelo que são duas metades e não uma. Segunda: a forma que o KAM-044 escreveu para o `order_state_log` — `BEFORE TRUNCATE OR DELETE … FOR EACH STATEMENT` — fecha o `DELETE` e **deixa o `UPDATE` aberto**, pelo que copiá-la era repetir um nível abaixo a omissão que este ticket fecha. O ticket impõe `BEFORE TRUNCATE OR DELETE OR UPDATE … FOR EACH STATEMENT`, sem *trigger* novo e sem função nova: os dois nomes ficam como estão, que é o que mantém verdes o `TestTriggersSaoAlways` e os dois confrontos do `test_downgrade.py`. Três coisas ficam escritas por medição e não por suposição: o canário tem de desligar **só** o *trigger* por instrução (com os dois ligados, nenhum ensaio distingue qual deles mordeu); o `payment_events_imutavel` passa a ser **estritamente redundante** e a recomendação é ficar, porque o `_desligar_trigger` do `test_cadeia.py` o desliga pelo nome; e esse mesmo `_desligar_trigger` é **o único ensaio que a alteração quebra**, pelo que passa a desligar os dois. A escolha entre editar a `0029` e abrir revisão nova fica decidida por uma pergunta de facto — existe ambiente onde a `0029` já foi aplicada e que não se reconstrói de zero? — e não por preferência. P1, `fix`, S, depende do KAM-053, que ganha o recíproco no `Bloqueia`. **E três tabelas irmãs ficam de fora de propósito**: a `platform.audit_log` (KAM-012), a `platform.tool_audit` (KAM-028) e a `dat.llm_call_log` (KAM-030) escrevem a mesma forma da `0029` com as duas metades abertas, e a barreira de uma tabela decide-se em quem a tem — ficam na **dívida 176**, com credor por tabela. O segundo critério de saída deste epic **não se emenda aqui**: o `kamba_ops` que ele nomeia é a dívida 167, com credor KAM-053. | Equipa KAMBÁ |
| 1.8 | Novembro 2026 | **KAM-175 entregue.** Secção «Verificação dos Critérios de Aceitação» no bloco, com os **nove** critérios e as **onze** caixas do DoD, cada um com ensaio nomeado e saída de execução. **Vinte caixas marcadas e nenhuma devolvida** — e isso é excepção neste epic, pelo que vale dizer porquê: os nove critérios deste ticket pedem todos medições contra a base, e nenhum deles pede uma decisão de quem o escreveu. O `payment_events_sem_truncate` da `0029` passa a `BEFORE TRUNCATE OR DELETE OR UPDATE … FOR EACH STATEMENT`, **por edição no sítio e não por revisão nova** — a pergunta do critério 7 respondeu-se por três medições e não por preferência: não há base onde a `0029` tenha sido aplicada e que não se reconstrua de zero (o *gate* 8 cria e destrói a sua; nenhum alvo do `Makefile` nem *script* de `initdb` corre `alembic` contra a base do `../infra/compose/`; e os `../infra/envs/{staging,prod}` apontam para `provider-pendente` com «não há host» e sem `tfstate`). É a resposta **oposta** à que o KAM-176 tem para a `0030`, pela mesma pergunta e com a mesma regra — a `0030` já fundiu em `main`. **As duas metades fechadas, com ensaio separado por metade**, e o par de nomes de *trigger* intacto: a suite passou de **93** para **103** ensaios, `OK` em 84,4 s — eram 100 à entrega e a revisão adversarial acrescentou três (ver a versão 1.9). O canário corre nos dois sentidos (`TestCanarioDoTriggerPorInstrucao`), com o `ALTER TABLE` revertido no `finally` e com o por linha a ficar em `A` durante o ensaio, para ser canário do por instrução e não de «a tabela não tem *triggers*». **E a alteração quebrou exactamente os dois ensaios que o critério 6 previu, e só esses** — `Ran 93 tests / FAILED (errors=2)`, os dois do `test_cadeia.py` que desligavam um *trigger* para forjar um elo partido —, o que torna esse critério um facto medido em vez de uma precaução. **Uma alteração fora dos critérios, e declarada:** a mutação «o *trigger* de imutabilidade deixa de cobrir o `DELETE`» passou a ser **imatável** depois desta correcção (o `DELETE` fica recusado pelo outro *trigger*), e foi substituída pela que repõe o defeito que o ticket fecha — «o *trigger* por instrução volta a cobrir só o `TRUNCATE`»; corrida e **apanhada** (`python db/mutacoes.py tests_pagamentos` → 14 corridas, 0 não apanhadas). E a contagem de mutações da `0029` é **catorze** e não quinze: o comentário do `../db/mutacoes.py` dizia quinze e já estava errado em `main` (medido com `grep -c` antes e depois da troca), e corrige-se no mesmo PR por ser prosa num ficheiro que este ticket já altera. O `payment_events_imutavel` **fica**, com a razão escrita na `0029`: não é defesa em profundidade, é que três ensaios o prendem pelo nome. A dívida 175 fica **riscada**; a 176 fica inteira, com os seus quatro credores. | Equipa KAMBÁ |
| 1.9 | Novembro 2026 | **KAM-175, revisão adversarial: treze achados, dez `CONFIRMADO`, e nenhum sobre o SQL.** O núcleo passou intacto — o `BEFORE TRUNCATE OR DELETE OR UPDATE … FOR EACH STATEMENT` faz o que o PR afirma, e o eixo «caminhos legítimos que a barreira passa a morder» ficou **MORTO** por varrimento ficheiro a ficheiro de toda a `../db/`. O que a revisão encontrou foram **cinco afirmações a valer menos do que diziam valer**, que é o modo de falha desta casa, e dois `must fix` sobre a decisão do critério 7. **Os dois fecharam por medição.** O primeiro dizia que a base do compose de desenvolvimento é um ambiente que não se reconstrói de zero (o `../db/migrations/README.md` manda correr `alembic upgrade head` à mão e o volume `postgres-data` é persistente): ficou **MORTO** pelo último parágrafo do próprio README — «não há ainda forma de aplicar as migrações ao PostgreSQL do compose de desenvolvimento: a rede de dados é interna e não publica portas» — e pelo compose, onde o serviço `db` não tem `ports:` e está só numa rede `internal: true`. **Mas o achado tinha razão sobre a pergunta**, e a medição (d) entrou na célula do critério 7 por causa dele: a medição (b) respondia a «há alvo que corra `alembic`?» e não a «há base nessas condições?». O segundo era uma frase falsa e saiu: «a resposta oposta à do KAM-176, pela mesma pergunta e com a mesma regra» — a `0029` também fundiu em `main` (`94bd634`, #104), pelo que a regra do critério 5 do KAM-176 aplicada a ela daria **revisão nova**. As duas regras são diferentes, e pela medição deste ticket a do KAM-176 não se sustenta nem para a `0030`; **não se emenda aqui** — o critério 5 dá a resposta por escrito, e emendar a letra de um critério é de quem o escreveu, pelo que o KAM-176 segue a letra dele e a divergência fica devolvida no bloco dele. **Três ensaios novos**, cada um a fechar um achado: o canário **simétrico** (o critério 5 dizia «medido» e o ensaio citado provava a proposição inversa), o `pg_get_triggerdef` (nada no catálogo prendia a lista de eventos — os três confrontos comparam nomes e `tgenabled`) e o `INSERT … ON CONFLICT DO UPDATE`, que um *trigger* `BEFORE UPDATE … FOR EACH STATEMENT` recusa **mesmo sem conflito** — fica declarado em vez de ser surpresa para quem escrever a próxima porta. E duas hipóteses passaram a medição: o `WHERE false` **é** recusado (entrou como `subTest` ao lado do `WHERE id = -1`), e o `rowcount` do `pg8000` é fiável aqui. **As onze caixas da DoD estavam por marcar** — a secção dava-as como marcadas e a lista dizia o contrário; são agora vinte de vinte. E **uma dívida nova, a 178**: o `../docs/tecnica/04` §6.2 **prescreve** o `CREATE TRIGGER` nas linhas 357 e 359, ao contrário do que os *Detalhes Técnicos* deste ticket afirmam, pelo que o documento-fonte do epic ficou a descrever a forma antiga — o modo de falha que o critério 8 do próprio ticket nomeia. Credor **KAM-053**; não se emendou aqui porque o ticket manda não tocar naquele documento. | Equipa KAMBÁ |
| 1.10 | Novembro 2026 | **KAM-054 entregue.** Secção «Verificação dos Critérios de Aceitação» nova no bloco, com os **nove** critérios (são nove e não oito) e as sete caixas da DoD, cada uma com evidência nomeada — nome do ensaio e saída da execução. **Quatorze caixas marcadas e duas vazias, com o credor escrito:** a observabilidade, que fica declarada e não emitida pela mesma fronteira que o `payment_events_total{tipo}` do KAM-053 (não há `services/pay/`), e os **dois revisores**, que é uma de três — a cobertura e os limites estão satisfeitos, e o segundo revisor de dinheiro é nomeação do fundador. A revisão `0032` cria as quatro tabelas do §6.2–6.3 que faltavam, as cinco funções de fase e **duas barreiras que os critérios não pedem**: a quinta aresta do §7.1 (`paga` + `confirmacao_manual_revertida` → `reembolso_pendente`), que a `0029` deixou escrita como dívida com este ticket nomeado, e o **G8 do §5**, que **não existia em sítio nenhum** — até aqui um `pagamento_confirmado` com `authn_method='manual'` e um `actor_id` qualquer passava, sem confirmador, sem desafio de valor e sem limites, e o caminho humano era o único dos três do G1 sem guarda. **Três dívidas documentais novas** (183 a 185), as três de critérios deste bloco contra fontes acima dele, e nenhuma emendada aqui. Dicionário em **1.60** (§3.45 nova) e `docs/dividas-documentais.md` em **1.100**. | Equipa KAMBÁ |
