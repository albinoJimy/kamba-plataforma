# EPIC-05 — Pagamentos e Billing

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Pagamentos e Billing |
| Versão | 1.5 |
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
| Bloqueia | KAM-054, KAM-056, KAM-060 |
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
- [ ] Um `createCharge(manual)` acima de `manual_max_minor` (proposta 50 000 Kz) devolve `REJECTED` e a encomenda não avança; no limite exacto é aceite; o valor é lido do tenant, não de constante.
- [ ] Confirmação enviada por um BSUID que não está em `payment_confirmers` activo (incluindo mensagem «sou o dono») não tem efeito e grava `confirmacao_manual_rejeitada`; o cliente nunca confirma (teste com o BSUID do cliente).
- [ ] A declaração «paguei» (texto ou imagem) só cria `manual_confirmations.fase='declaracao_cliente'` e a cobrança `pendente_confirmacao`; a imagem é arquivada com `evidencia_ref` rotulado `nao_prova` e nenhum módulo do `ManualProvider` lê o conteúdo da imagem (*lint* de importações de OCR/visão = 0).
- [ ] Desafio do valor: o dono escreve o valor visto na sua app; `amount_minor − 1` cêntimo rejeita (`valor_bate=false`, cobrança volta a `emitida`); valor igual avança, sem tolerância.
- [ ] Até `manual_dupla_acima_minor` (proposta 20 000 Kz) uma confirmação gera `pagamento_confirmado` com `authn_method='humano_auditado'` e `actor_id` não nulo; acima, a cobrança fica `pendente_confirmacao`, a segunda aprovação pelo mesmo contacto é rejeitada e só a de outro confirmador com `pode_segunda_aprovacao=true` conclui.
- [ ] `manual_daily_max_minor` e `manual_max_por_contacto_24h` excedidos retêm a confirmação para ops com `fraud_signals.accao='reter_confirmacao'`.
- [ ] Sem resposta do dono em 24 h (omissão, F-18) a cobrança volta a `pendente_confirmacao → emitida` com `confirmacao_manual_rejeitada` e a reserva mantém-se até `expires_at`.
- [ ] Reversão: `confirmacao_manual_revertida` + `refund_cases` aberto + cobrança `paga → reembolso_pendente`; nenhuma linha é apagada (a contagem do ledger só cresce).
- [ ] A mesma mensagem (`canal_msg_id`) processada 2 vezes produz 1 confirmação; `metodo='cod'` com *opt-in* desligado devolve `REJECTED`.

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
- [ ] Todos os Critérios de Aceitação satisfeitos e demonstráveis.
- [ ] Pagamento só por evento autenticado: o caminho `humano_auditado` exige actor, desafio de valor e limites; nenhum código marca `paga` por imagem ou texto do cliente.
- [ ] Idempotência: repetir a mesma confirmação não duplica efeitos; teste de repetição presente.
- [ ] Isolamento de tenant e de contacto: RLS em `payment_confirmers` e `manual_confirmations`; caso novo na suite cruzada.
- [ ] Privacidade: sem telefone nem texto de mensagem nos logs; contacto por `contact_id`.
- [ ] Observabilidade: `manual_confirmations_total{fase}` e alerta de desvio semanal (`../docs/tecnica/08` §4.6).
- [ ] Dois revisores; cobertura ≥ 90%; limites registados como propostas a calibrar.

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
