# Contratos de pagamento: bancos e facilitadores — perguntas, matriz e D4

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — contratos de pagamento, matriz banco × facilitador e insumo para D4 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-103 (EPIC-10) |
| Documento-fonte | `../E2_Pagamentos_Angola.md` §1 (§1.1, §1.2, §1.3, §1.4, §1.7), §3 (§3.3), §8, §9 (perguntas 1–18); `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H5), §6; `../../04_Pagamentos_Liquidacao_AntiFraude.md` §3, §8, §10; `../../00_Arquitectura_Solucao.md` (ADR-004, ADR-013, §13.3 D4, D8) |
| Relacionados | [`Meta_Perguntas.md`](Meta_Perguntas.md), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md), [`KAM-126_Factura_AI.md`](KAM-126_Factura_AI.md), [`GoLive_Gate.md`](GoLive_Gate.md) |
| Instrumento de medição | `spikes/proxypay-d4/` (descartável; não é código de produção e não é um portão) |

> **Nenhuma contraparte foi contactada, e nenhuma resposta existe.** Contactar
> bancos e facilitadores, pedir chaves de *sandbox*, negociar e assinar são
> **actos do fundador**. O que este documento entrega é o questionário já
> escrito e endereçado, as tabelas com as colunas que a decisão precisa, o
> *script* que mede o *sandbox* quando as chaves existirem, e as regras de H5 e
> de D4 **pré-registadas** — isto é, escritas antes de haver dados que as
> possam torcer.
>
> **Os estados herdam-se de `../E2_Pagamentos_Angola.md` e não sobem aqui.** Uma
> só célula deste documento é **CONFIRMADO** sobre comissão: a da AppyPay (0,40%
> por cobrança, mínimo 50 Kz, máximo 1.500 Kz, IVA a acrescer), porque tem
> página de preços do próprio fornecedor. Todas as outras são **NÃO
> VERIFICADO**, e continuar NÃO VERIFICADO é entrega. Promover uma a facto por
> parecer plausível é o defeito que este ticket existe para não cometer.
>
> **H5 não está satisfeito, e não pode estar.** O limiar pede prazo de
> *onboarding* por PME ≤ 6 semanas **declarado por escrito** pela contraparte ou
> **medido num caso real**. Não há declaração escrita nenhuma, e nenhum caso
> real foi medido: o prazo bancário é NÃO VERIFICADO em `../E2_Pagamentos_Angola.md`
> §1.7, sem fonte pública. O §4 escreve a regra e o §4.3 registra H5 como
> **`inconclusiva`**, com amostra zero.
>
> **A linha que não se negocia.** Nenhum contrato aqui previsto pode prever que
> a KAMBÁ receba ou retenha fundos de terceiros (ADR-004). O §7 escreve a
> cláusula a exigir, e levanta **o único sinal que vai no sentido contrário** e
> que não é uma opção da matriz: a pergunta da conta-mestre, que tem duas
> leituras e cuja leitura errada é o desenho B de `../E2_Pagamentos_Angola.md`
> §3.3 — actividade regulada. É um achado para o fundador.

---

## 1. O que este ticket decide, e o que não decide

| Decide | Não decide |
|---|---|
| **Que perguntas** vão a cada contraparte, com o texto já escrito e o destinatário fixado (§2) | **As respostas.** Nenhuma existe; a folha de seguimento nasce toda em `por enviar` (§2.8) |
| **Que colunas** a matriz de decisão precisa, e que cada célula leva o seu estado (§3) | **Que facilitador se escolhe.** É D4, e D4 é do fundador (§5.4) |
| **A regra de H5**, pré-registada, com as três saídas e o que cada uma dispara (§4) | **Se H5 se confirma.** Sem declaração escrita e sem caso medido, fica `inconclusiva` (§4.3) |
| **A regra ponderada de D4**, com os critérios do ticket, os pesos como *proposta*, e os dois que são **eliminatórios** e não ponderados (§5) | **O resultado de D4.** A regra aplica-se ao que hoje se sabe e nenhum caminho passa o mínimo (§5.2) |
| **O impacto escrito em KAM-056, KAM-057 e KAM-059** se o limiar H5 falhar (§6) | **Replanear esses tickets.** Mudar linha do backlog mestre é trabalho de outro PR |
| **A cláusula de fronteira do ADR-004** que cada minuta tem de ter, e o sinal contrário que apareceu (§7) | **A minuta.** Redigir e revê-la é o advogado do KAM-104; aceitar termos é do fundador |
| **A verificação empírica do contrato da ProxyPay contra um *mock***, com canário (§8) | **A corrida contra o *sandbox* do fornecedor.** Precisa de chaves, e pedir chaves é contacto com contraparte (§8.3) |

**O que fica explicitamente fora.** O adaptador ProxyPay é o **KAM-056**; a
avaliação da AppyPay com `ProviderCapabilities` e registo MADR é o **KAM-057**;
o parecer jurídico é o **KAM-104**. Nada aqui implementa código de pagamentos, e
o *spike* do §8 vive em `spikes/`, descartável, fora de portão nenhum.

---

## 2. Fichas por contraparte

### 2.1 Como se lê uma ficha, e a regra de classificação

Cada ficha tem duas tabelas. A primeira é **as perguntas**: o texto, o
destinatário, a célula da matriz que a resposta alimenta, e a prioridade. A
segunda é o **registo de resposta**, com os campos que o critério 1 do ticket
exige — e **nasce vazia**, porque não há respostas.

Os campos do registo, um a um:

| Campo | O que leva |
|---|---|
| `#` | O número da pergunta em `../E2_Pagamentos_Angola.md` §9, que é a numeração que o resto do conjunto cita |
| `estado` | `por enviar` → `enviada` → `respondida` ou `sem resposta`. O `por enviar` é o estado **anterior** aos outros, não um resultado |
| `data` | A data da **resposta**, não a do envio; a do envio vive na folha de seguimento do §2.8 |
| `remetente` | **O papel ou a equipa, nunca o nome de uma pessoa.** O repositório é público |
| `classificação` | `CONFIRMADO` ou `INDÍCIO`, pela regra abaixo |
| `resposta` | O texto, resumido, com a citação literal onde o número importa |

**A regra de classificação é pela origem, e fixa-se aqui antes de haver
respostas** — fixá-la depois é escolher o estado que convém:

| Origem da resposta | Classificação |
|---|---|
| Documento escrito da própria contraparte: proposta comercial, preçário assinado, minuta de contrato, mensagem de correio electrónico de um endereço da contraparte, página oficial do fornecedor | **CONFIRMADO** |
| Resposta **verbal** — reunião, chamada, balcão — **mesmo vinda da contraparte** | **INDÍCIO** |
| Intermediário, consultor, parceiro, plugin, SDK de terceiros, imprensa, fórum | **INDÍCIO** |
| Nada recebido | fica **NÃO VERIFICADO**; a célula da matriz não se preenche |

O verbal fica INDÍCIO deliberadamente, e é a regra que mais vai doer: uma
reunião num banco produz números ditos em voz alta, e é precisamente desses que
o ticket diz «**declarado por escrito**». A mesma regra está em
[`Meta_Perguntas.md`](Meta_Perguntas.md) §2, e herda-se dela em vez de se
inventar uma segunda.

### 2.2 Banco de apoio A — o banco onde a empresa do fundador já tem conta

| Campo | Valor |
|---|---|
| Contraparte | **NÃO VERIFICADO** — só o fundador sabe qual é |
| Porque é esta | É o único caminho em que H5 se pode fechar por **caso real medido** e não por declaração: o ticket nomeia «a empresa do fundador como primeiro caso» (critério 3) |
| Canal | Gestor de conta empresarial. Pedido **por escrito**, para que a resposta sirva de evidência |
| Estado do contacto | `por contactar` |
| O que se pede | As respostas 1 a 6, e a **minuta** do contrato de serviços EMIS |

As perguntas são as de `../E2_Pagamentos_Angola.md` §9, grupo «Banco de apoio»:

| # | Pergunta | Célula da matriz que alimenta | Prioridade |
|---|---|---|---|
| 1 | Quais os documentos, custos e prazo (dias úteis) para obter POSID/*supervisor card* (GPO), Entidade (referências) e IEC (débito directo)? Exigem alvará, certidão comercial, NIF, contabilidade? Aceitam empresário em nome individual? | `documentos exigidos`, `custo único`, `prazo em dias úteis` | **P0 — é a pergunta de H5** |
| 2 | Qual a comissão do banco por GPO Express, referência e débito directo? Aplica-se o tecto de 1% / 12.000 Kz do Instrutivo 02/2025? | `comissão por transacção` | **P0** |
| 3 | A que horas e em que dia (D+0/D+1/D+2) liquidam GPO e referências? Há reservas ou retenções? | `liquidação` | P1 |
| 4 | Qual o limite por transacção e diário por comerciante em GPO e referências? | `limite por transacção` | P1 |
| 5 | Podem delegar a mesma Entidade/POSID a um facilitador técnico sem passar o dinheiro pela conta do facilitador? | `modelo`, e **a fronteira do §7** | **P0** |
| 6 | Têm API própria de extracto/saldos/confirmação (conciliação), e API de transferência em lote para o comerciante pagar estafetas a partir da sua conta? | `modelo` (conciliação); e o desenho C do §7 | P2 |

Registo de resposta — **nasce vazio**:

| # | estado | data | remetente (papel) | classificação | resposta |
|---|---|---|---|---|---|
| 1 | `por enviar` | — | — | — | — |
| 2 | `por enviar` | — | — | — | — |
| 3 | `por enviar` | — | — | — | — |
| 4 | `por enviar` | — | — | — | — |
| 5 | `por enviar` | — | — | — | — |
| 6 | `por enviar` | — | — | — | — |

> **O prazo deste banco é o único que pode fechar H5 por medição.** Nos outros
> caminhos, H5 só fecha por declaração escrita — e uma declaração escrita de
> prazo é coisa que nenhuma fonte pública desta casa tem
> (`../E2_Pagamentos_Angola.md` §1.7: «nenhuma fonte pública»).

### 2.3 Banco de apoio B — o segundo, para comparação

| Campo | Valor |
|---|---|
| Contraparte | **proposta: um dos quatro nomeados em `../E2_Pagamentos_Angola.md` §9**; qual, decide o fundador |
| Porque é esta | Um só banco não dá comparação, e o prazo é **específico por banco** (`../E2_Pagamentos_Angola.md` §1.7). Dois caminhos é o mínimo para a matriz do §3 ter duas linhas |
| Critério de escolha, escrito | (a) estar na lista de `../E2_Pagamentos_Angola.md` §9; (b) **não** ser o Banco A; (c) ter balcão empresarial acessível ao fundador. Nada nesta casa sustenta um critério mais fino, e inventar um era o defeito |
| Canal | Balcão ou gestor de empresas, pedido **por escrito** |
| Estado do contacto | `por contactar` |

As perguntas são **as mesmas 1 a 6**, sem alteração: a comparação só vale se as
duas colunas responderem à mesma pergunta. O registo nasce igualmente vazio:

| # | estado | data | remetente (papel) | classificação | resposta |
|---|---|---|---|---|---|
| 1 | `por enviar` | — | — | — | — |
| 2 | `por enviar` | — | — | — | — |
| 3 | `por enviar` | — | — | — | — |
| 4 | `por enviar` | — | — | — | — |
| 5 | `por enviar` | — | — | — | — |
| 6 | `por enviar` | — | — | — | — |

### 2.4 ProxyPay / TimeBoxed

| Campo | Valor |
|---|---|
| Contraparte | TimeBoxed, operadora da ProxyPay |
| O que já se sabe | **O contrato técnico está documentado e é CONFIRMADO** (`../E2_Pagamentos_Angola.md` §1.2): RPS v2 com HMAC-SHA256 em `X-Signature`, fila de reconciliação `GET /payments` e `DELETE /payments/{id}`, pagamento simulado no *sandbox*, OPG com os números de ensaio. O §8 mede essa forma contra um *mock* |
| O que **não** se sabe | **Preços: NÃO VERIFICADO** — o sítio só mostra ecrã de *login* (`../E2_Pagamentos_Angola.md` §1.2, medido a 2026-10-08). **Assinatura do *callback* do OPG: NÃO VERIFICADO.** **Valor do *rate limit*: NÃO VERIFICADO** (a existência do 429 é CONFIRMADA). **Prazo de *onboarding*: NÃO VERIFICADO** |
| Exigência de banco | **INDÍCIO**: é necessário contrato com um banco angolano **e** com a TimeBoxed (fonte: *readme* de *plugin* WooCommerce, 2026-08-03). Herda-se o INDÍCIO; é a pergunta 7 que o fecha |
| Canal | Formulário comercial ou contacto directo. Pedido **por escrito** |
| Estado do contacto | `por contactar` |

| # | Pergunta | Célula da matriz que alimenta | Prioridade |
|---|---|---|---|
| 7 | Preçário completo (mensalidade, por transacção, mínimo), SLAs, prazos de *onboarding*, contratos-tipo | `custo único`, `custo recorrente`, `comissão por transacção`, `prazo em dias úteis` | **P0 — é a única via para o preço** |
| 8 | O *callback* do OPG é assinado? Qual o esquema de *retries* e há fila de pagamentos também para OPG? *Rate limits*? | `callbacks assinados`, e o **eliminatório (a)** do §5.1 | **P0** |
| 9 | Uma plataforma multi-comerciante pode ter uma conta-mestre com sub-comerciantes (cada um com a sua Entidade/POSID) e uma só chave de API? | `modelo`, e **a fronteira do §7.2** | **P0** |
| 10 | Rotação de chaves — a chave HMAC **é** a API key | `callbacks assinados` (operação), e o DoD de segredos | P1 |

Registo de resposta — **nasce vazio**:

| # | estado | data | remetente (papel) | classificação | resposta |
|---|---|---|---|---|---|
| 7 | `por enviar` | — | — | — | — |
| 8 | `por enviar` | — | — | — | — |
| 9 | `por enviar` | — | — | — | — |
| 10 | `por enviar` | — | — | — | — |

Junto com as perguntas pede-se, em separado, **as chaves do *sandbox*** — e é
isso que destrava a segunda metade do §8. Pedir chaves é contacto com
contraparte; está no §11 com credor.

### 2.5 AppyPay

| Campo | Valor |
|---|---|
| Contraparte | AppyPay |
| O que já se sabe | **Comissão CONFIRMADA**: 0,40% por cobrança, mínimo 50 Kz, máximo 1.500 Kz, sem adesão nem mensalidade, 75 Kz/mês por autorização de débito directo activa, SMS 20 Kz, correio electrónico 5 Kz, **IVA a acrescer**, e **independente da comissão do banco** (`../E2_Pagamentos_Angola.md` §1.3). **Papel CONFIRMADO**: «não intervém no fluxo financeiro»; a EMIS credita directamente na conta do comerciante no banco de apoio (termos cl. 1.5) |
| O que **não** se sabe | **Assinatura do *webhook*, *retries* e idempotência: NÃO VERIFICADO.** **Autenticação e *sandbox*: INDÍCIO** (de SDK de terceiros). **Certificado EMIS: declaração do próprio, validação independente NÃO VERIFICADA.** **Prazo de *onboarding*: NÃO VERIFICADO** — o «*onboarding* automático só com o NIF» é marketing e aplica-se à conta AppyPay, não às credenciais EMIS (`../E2_Pagamentos_Angola.md` §1.7) |
| Canal | *Backoffice* de desenvolvedores ou contacto comercial. Pedido **por escrito** |
| Estado do contacto | `por contactar` |

| # | Pergunta | Célula da matriz que alimenta | Prioridade |
|---|---|---|---|
| 11 | Documentação Stoplight completa e OpenAPI; esquema de autenticação actual; *sandbox* oficial e dados de teste | `sandbox`, e a passagem de INDÍCIO a CONFIRMADO do contrato técnico | **P0** |
| 12 | Assinatura dos *webhooks*, *retries*, idempotência além do `merchantTransactionId` (1 a 15 alfanuméricos) | `callbacks assinados`, e o **eliminatório (a)** do §5.1 | **P0** |
| 13 | Certificado EMIS (carta, data, âmbito) e confirmação de que não é necessária licença BNA à AppyPay | `modelo`, e o §7 | P1 |
| 14 | Uso de «FTBAI / transferência de fundos»: para que serve e quem pode usar? | **o §7.2** — é o segundo sinal na direcção do desenho C | **P0 pela fronteira**, P2 pelo produto |
| 15 | Existe modelo *partner/ISV* com *onboarding* de comerciantes via API? | `modelo`, e **a fronteira do §7.2** | **P0** |

Registo de resposta — **nasce vazio**:

| # | estado | data | remetente (papel) | classificação | resposta |
|---|---|---|---|---|---|
| 11 | `por enviar` | — | — | — | — |
| 12 | `por enviar` | — | — | — | — |
| 13 | `por enviar` | — | — | — | — |
| 14 | `por enviar` | — | — | — | — |
| 15 | `por enviar` | — | — | — | — |

### 2.6 EMIS — opcional (perguntas 16 e 17)

| Campo | Valor |
|---|---|
| Contraparte | EMIS |
| Porque é opcional | O ticket marca-a como opcional, e com razão: a via directa tem o *callback* **não assinado** e **sem consulta de estado** (INDÍCIO, de código de terceiros, `../E2_Pagamentos_Angola.md` §1.4). Isso choca de frente com o **eliminatório (a)** do §5.1 — pelo que a EMIS directa entra na matriz **excluída à partida**, e não por falta de resposta |
| Porque se pergunta mesmo assim | Porque o INDÍCIO vem de **uma só fonte**, e código de terceiros não é o fornecedor. Uma resposta que diga o contrário muda a exclusão |
| Estado do contacto | `por contactar` |

| # | Pergunta | Célula da matriz que alimenta | Prioridade |
|---|---|---|---|
| 16 | Condições para integração directa GPO (token de comerciante, certificação de integradores), documentação oficial, assinatura de *callbacks* e existência de consulta de estado | `callbacks assinados`, `sandbox` | P2 |
| 17 | Limite por operação de pagamento Express a comerciante, e se há *request-to-pay* KWiK para comerciantes | `limite por transacção`, `cobertura` | P2 |

| # | estado | data | remetente (papel) | classificação | resposta |
|---|---|---|---|---|---|
| 16 | `por enviar` | — | — | — | — |
| 17 | `por enviar` | — | — | — | — |

### 2.7 PayPay / Pay4All — opcional (pergunta 18)

| Campo | Valor |
|---|---|
| Contraparte | PayPay África (Conectando), ou outro PSP licenciado |
| Porque é opcional | A PayPay **é PSP licenciado** (INDÍCIO, licença BNA n.º 420) e por isso **pode** legitimamente deter fundos. Isso torna-a a via para *payouts* — e *payouts* estão **fora do Piloto** (ADR-004). A pergunta serve a Clusters, não a D4 |
| Fronteira | A resposta a esta pergunta **não** pode entrar na matriz como opção de cobrança do Piloto. Se entrar, estamos a desenhar o desenho C de `../E2_Pagamentos_Angola.md` §3.3 |
| Estado do contacto | `por contactar` |

| # | Pergunta | Célula da matriz que alimenta | Prioridade |
|---|---|---|---|
| 18 | Existe API de comerciante para QR KWiK e confirmação *server-side*? Existe API de *payouts* por IBAN? Em nome de quem — conta do comerciante ou da plataforma? Aceitam parceria sem a plataforma deter fundos? | **nenhuma** célula da matriz do §3; alimenta o §7.2 e Clusters | P3 |

| # | estado | data | remetente (papel) | classificação | resposta |
|---|---|---|---|---|---|
| 18 | `por enviar` | — | — | — | — |

### 2.8 Folha de seguimento

Nasce com todas as linhas em `por enviar`, zero enviadas, zero respondidas.

| Contraparte | Perguntas | Enviadas | Respondidas | Estado | Dono do envio |
|---|---|---|---|---|---|
| Banco de apoio A | 1–6 | 0 | 0 | `por enviar` | **fundador** |
| Banco de apoio B | 1–6 | 0 | 0 | `por enviar` | **fundador** |
| ProxyPay / TimeBoxed | 7–10 (+ chaves de *sandbox*) | 0 | 0 | `por enviar` | **fundador** |
| AppyPay | 11–15 | 0 | 0 | `por enviar` | **fundador** |
| EMIS (opcional) | 16–17 | 0 | 0 | `por enviar` | **fundador** |
| PayPay (opcional) | 18 | 0 | 0 | `por enviar` | **fundador** |

**Regra de seguimento, e um gatilho que não é uma data.** Lembrete ao **dia 10**
depois de cada envio; a quem não responder ao **dia 20**, segundo pedido com a
pergunta reduzida ao essencial (no caso dos bancos: só a 1 e a 2). O
**escalamento** não tem data: tem gatilho — a **semana 6**, que é quando a Carta
§4.2 manda o Piloto para `ManualProvider` se não houver contrato (§5.3). As
**datas absolutas não se escrevem aqui**, porque contam-se do dia 0, que é o dia
do envio e **ainda não existe**.

---

## 3. Matriz banco × facilitador

### 3.1 As colunas, e porque cada uma existe

| Coluna | O que decide | Quem a responde |
|---|---|---|
| `documentos exigidos` | Se a PME média do Piloto consegue reunir o dossiê. Um alvará exigido elimina o informal | pergunta 1 |
| `custo único` | O que a PME paga para **começar**, que é a barreira de adopção | perguntas 1 e 7 |
| `custo recorrente` | O que a PME paga por mês sem vender nada | perguntas 1, 7 e a comissão fixa da AppyPay |
| `comissão por transacção` | O custo real por venda, em **dois componentes** — facilitador **e** banco/EMIS, que são independentes (`../E2_Pagamentos_Angola.md` §1.3) | perguntas 2 e 7 |
| `liquidação` | D+0/D+1/D+2 e a hora. Decide o que a interface pode prometer — e **nunca promete «dinheiro na hora»** | pergunta 3 |
| `limite por transacção` | Se a encomenda típica passa | perguntas 4 e 17 |
| `prazo em dias úteis` | **É H5.** ≤ 30 dias úteis passa; mais, falha | perguntas 1 e 7 |
| `modelo` | Quem é o dono do contrato e por onde passa o dinheiro. É aqui que o ADR-004 se verifica ou se quebra | perguntas 5, 9, 13 e 15 |
| `callbacks assinados` | Se a confirmação é autenticável. **Eliminatório** (§5.1) | perguntas 8, 12 e 16 |
| `sandbox` | Se se pode desenvolver e testar sem dinheiro real | perguntas 11 e 16, e o §8 |
| `cobertura` | Que *rails* ficam cobertos num só contrato — Express, referência, débito directo, Unitel Money | `../E2_Pagamentos_Angola.md` §1.1 e §1.3 |
| `dono do contrato` | Quem assina. **Nunca a KAMBÁ pela PME** | perguntas 5 e 15 |

**A regra da célula é dura: sem fonte escrita, a célula fica NÃO VERIFICADO.**
Não fica «provavelmente», não fica «semanas», não fica com um intervalo
estimado. O bloco do ticket diz-o por extenso no *handoff*, e é a diferença
entre uma matriz e uma opinião formatada.

### 3.2 A matriz

Cada célula leva o seu estado. `NV` é **NÃO VERIFICADO**; `IND` é **INDÍCIO**;
`CONF` é **CONFIRMADO**.

| Coluna | Banco A × ProxyPay | Banco A × AppyPay | Banco B × ProxyPay | Banco B × AppyPay | EMIS directo |
|---|---|---|---|---|---|
| `documentos exigidos` | POSID/*supervisor card*, Entidade, IEC no banco **(CONF, `../E2_Pagamentos_Angola.md` §1.3)**; a lista exacta e os anexos: **NV** | idem; **NV** na lista exacta | **NV** | **NV** | **NV** |
| `custo único` | **NV** | **NV** (AppyPay «sem adesão», **CONF**; a parte bancária **NV**) | **NV** | **NV** | **NV** |
| `custo recorrente` | **NV** | 75 Kz/mês por débito directo activo **(CONF)**; parte bancária **NV** | **NV** | idem | **NV** |
| `comissão por transacção` | **NV** nos dois componentes | **0,40%, mín. 50 Kz, máx. 1.500 Kz, IVA a acrescer (CONF)** + comissão bancária **NV** | **NV** | **CONF** + **NV**, idem | comissão do banco, **NV** |
| `liquidação` | directa via banco/EMIS **(IND)**; dia e hora **NV** | Express ao fecho do TPA virtual (08:00–08:30 GMT+1) e referências às 20:00 GMT+1 **(CONF)**; D+ por banco **NV** | **IND** / **NV** | **CONF** / **NV** | directa ao banco **(IND)** |
| `limite por transacção` | `amount` do API entre 0,01 e 99.999.999,99 **(CONF, e é limite do API, não da rede)**; limite da rede e do banco **NV** | **NV** | idem | **NV** | **NV** |
| `prazo em dias úteis` | **NV** | **NV** | **NV** | **NV** | **NV** |
| `modelo` | facilitador técnico, liquidação directa **(IND)**; conta-mestre **NV** e com duas leituras (§7.2) | facilitador técnico puro, «não intervém no fluxo financeiro» **(CONF, termos cl. 1.5)**; modelo ISV **NV** | idem | idem | integração directa, **IND** |
| `callbacks assinados` | RPS: `X-Signature` HMAC-SHA256 sobre o corpo bruto, com a API key **(CONF)**. **OPG: NV** | **NV** (INDÍCIO de que o *webhook* é obrigatório em REF; assinatura, *retry* e idempotência **NV**) | idem | **NV** | **não assinado e sem consulta de estado (IND, uma só fonte)** → **excluído** pelo §5.1 |
| `sandbox` | `api.sandbox.proxypay.co.ao` documentado, com pagamento simulado **(CONF)**; acesso depende de chaves **NV** | `gwy-api-tst` **(IND, SDK de terceiros)** | idem | **IND** | **NV** |
| `cobertura` | Express (OPG), referência (RPS), débito directo (DDS) **(CONF)**; Unitel Money **não** | Express, referência, débito directo **e Unitel Money** num só contrato **(CONF)** | idem | **CONF** | Express, cartão, referência **(IND)** |
| `dono do contrato` | **a PME**, com o seu banco e com a TimeBoxed **(IND)** | **a PME**, com o banco de apoio e a AppyPay **(CONF, FAQ: contrato em suporte físico assinado por ambas as partes)** | **IND** | **CONF** | a PME **(IND)** |

### 3.3 A única célula CONFIRMADA sobre custo, e o que ela não cobre

A comissão da AppyPay é **CONFIRMADO** e é a única. Três coisas que ela **não**
diz, e que a matriz tem de manter separadas para a conta não sair errada:

1. **Não inclui a comissão bancária.** Os termos dizem-no: a comissão é
   «independente da do banco/EMIS». O custo por venda tem **dois** componentes e
   o segundo é **NÃO VERIFICADO** nas quatro colunas.
2. **Não inclui o IVA**, que acresce. Uma conta que use 0,40% como custo total
   subestima-o.
3. **Não é o custo da ProxyPay.** Transpor 0,40% para a coluna da ProxyPay era
   inventar o preço de um fornecedor a partir do preço de outro — exactamente o
   que o *handoff* do ticket proíbe («nunca inventes preços da ProxyPay»).

**E o `fee` do evento de pagamento é o instrumento que fecha o segundo
componente sem esperar pelo banco.** O evento do RPS traz um campo `fee`, que é
a comissão bancária da transacção (`../E2_Pagamentos_Angola.md` §1.2,
CONFIRMADO). O ensaio 4 do §8 verifica que ele vem; contra o *sandbox* do
fornecedor, com uma transacção real, ele **mede** o que a pergunta 2 pede por
escrito — e é por isso que a corrida contra o fornecedor vale mais do que uma
corrida a mais contra o *mock*.

---

## 4. Limiar H5, pré-registado

### 4.1 A regra

H5, em `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2: «Existe
via de cobrança com confirmação *server-side* para uma PME», com critério de
sucesso «prazo e custo por PME conhecidos e ≤ 6 semanas», semanas 1 a 6.

O critério 3 do ticket aperta-o e é essa a forma que vale aqui:

> Existe **≥ 1 caminho** com prazo de *onboarding* por PME **≤ 6 semanas
> (30 dias úteis)**, **declarado por escrito** pela contraparte **ou medido num
> caso real** (a empresa do fundador como primeiro caso). Caso contrário, H5 é
> `refutada`.

Três leituras ficam fixadas **antes** de haver dados, porque fixá-las depois é
escolher o resultado:

| O que se fixa | Como se lê |
|---|---|
| **O que conta o prazo** | Da entrega do dossiê completo no banco até a PME ter POSID/Entidade/IEC **e** credenciais do facilitador activas — isto é, até **poder cobrar**. Não até ao «pedido aceite» |
| **O que conta como «por escrito»** | A regra do §2.1: documento da contraparte. **Uma resposta verbal não fecha H5**, por boa que seja |
| **O que conta como caso real** | Um *onboarding* **completado**, com as datas das duas pontas registadas. Um em curso não conta, e um estimado conta menos ainda |

### 4.2 As três saídas

| Saída | Condição | O que dispara |
|---|---|---|
| **`confirmada`** | ≥ 1 caminho com prazo ≤ 30 dias úteis, por escrito ou medido, **e** custo por PME conhecido (os dois componentes) | D4 decide-se pela regra do §5; KAM-056 e KAM-057 seguem como planeados |
| **`inconclusiva`** | Há respostas, mas nenhuma dá prazo **e** custo; ou o prazo vem só verbal; ou o caso real está a meio | O Piloto arranca em `ManualProvider` **sem** declarar H5 refutada; o seguimento do §2.8 continua. **É o estado de hoje** |
| **`refutada`** | Todas as contrapartes responderam e **nenhum** caminho fica ≤ 30 dias úteis; ou a semana 6 passou sem contrato | O §6 entra em vigor: camadas 1–2 e venda de atendimento e agenda **sem cobrança integrada** (`../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §6) |

**`inconclusiva` não é `refutada`, e a diferença é material.** `refutada` muda a
tese e manda replanear três tickets; `inconclusiva` só diz que ainda não se
mediu. Confundir as duas por impaciência custava um replaneamento inteiro sobre
um dado que não existe.

### 4.3 Registo de H5

| Campo | Valor |
|---|---|
| Hipótese | H5 — existe via de cobrança com confirmação *server-side* para uma PME |
| Limiar | ≥ 1 caminho com *onboarding* por PME ≤ 6 semanas (30 dias úteis), por escrito ou medido, e custo por PME conhecido |
| Amostra | **n = 0** caminhos com prazo declarado; **n = 0** casos reais medidos |
| Resultado | — |
| Estado | **`inconclusiva`** |
| Razão | Nenhuma contraparte foi contactada; o prazo bancário é **NÃO VERIFICADO** sem fonte pública (`../E2_Pagamentos_Angola.md` §1.7), e o prazo da ProxyPay e da AppyPay também |
| Dono | Responsável de Produto |
| Data | 2026-11-06 |
| Gatilho de reavaliação | A primeira resposta **escrita** com prazo, vinda de qualquer uma das quatro contrapartes do §2.8 |

> **H5 não se declara satisfeito sem declaração escrita, e este documento não o
> declara.** É a instrução do ticket à letra. O custo de marcar a caixa aqui
> seria uma decisão D4 tomada sobre um prazo que ninguém disse.

---

## 5. D4: a regra ponderada (*proposta*)

### 5.1 Os critérios, e os dois que não são pesos

O critério 5 do ticket nomeia sete critérios ponderados: *callbacks* assinados
ou *polling* de reconciliação, *sandbox*, liquidação directa, prazo, custo,
modelo multi-comerciante, cobertura (Unitel Money).

**Dois deles não podem ser pesos, e isto é uma leitura declarada, não uma
decisão tomada.** Um peso deixa-se compensar: um candidato fraco num critério
compensa noutro e ainda passa. Há dois onde compensar é proibido por canon em
vigor:

| Eliminatório | Porquê | Fonte |
|---|---|---|
| **(a) Confirmação autenticável** — *callback* assinado **ou** consulta de estado confirmada **por escrito** | O estado `paga` só é alcançável por evento autenticado. Um facilitador sem nenhum dos dois não tem como confirmar um pagamento, e nenhum peso noutra coluna compra isso | **ADR-013**; e o critério 4 do **KAM-057** escreve a mesma regra com as mesmas palavras |
| **(b) Liquidação directa à PME** | A plataforma nunca detém fundos. Um candidato que liquide para uma conta nossa não é um candidato pior: é um desenho diferente, e regulado | **ADR-004**; `../E2_Pagamentos_Angola.md` §3.3, desenhos B e D |

Os restantes cinco ponderam-se. Os pesos são ***proposta*** — são a primeira
calibração, escrita para poder ser recusada, e quem a recusa é quem escreveu o
critério:

| Critério ponderado | Peso (*proposta*) | Porque este peso |
|---|---|---|
| **Prazo de *onboarding* por PME** | **30** | É H5, e H5 é o critério de pivô da tese (`../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2). O caminho crítico dos pagamentos é este, e não o código |
| **Custo por PME** (os dois componentes, com IVA) | **25** | Decide o preço da assinatura e a margem; um custo por venda alto come a mensalidade |
| ***Sandbox*** acessível, com pagamento simulado | **20** | Sem ele não há suite de conformidade (`../../04_Pagamentos_Liquidacao_AntiFraude.md` §3.5), e sem suite não há adaptador que se possa afirmar correcto |
| **Modelo multi-comerciante** compatível com o §7 | **15** | Decide se o *onboarding* de cada PME é trabalho nosso ou dela. Pesa, mas **não** compensa: a leitura incompatível é eliminada por (b), não descontada |
| **Cobertura de *rails*** num só contrato (Express, referência, débito directo, Unitel Money) | **10** | Unitel Money alarga o alcance, mas liquida **em carteira** e não em conta — é alcance, não é fundação |
| | **100** | |

**Mínimo para adoptar: 60 de 100, e os dois eliminatórios satisfeitos.** O 60 é
*proposta* e a sua justificação é esta: 60 não se alcança sem o prazo **ou** sem
o custo — os dois maiores pesos somam 55 —, pelo que a regra não deixa adoptar
um facilitador de quem não se saiba nem prazo nem preço. Que é exactamente a
situação de hoje.

### 5.2 A regra aplicada ao que hoje se sabe

| Candidato | (a) confirmação autenticável | (b) liquidação directa | Pontos ponderados | Resultado |
|---|---|---|---|---|
| **ProxyPay (RPS)** | **satisfeito** — `X-Signature` HMAC-SHA256 **e** fila de reconciliação por *polling*, as duas CONFIRMADAS | **IND** — directa via banco/EMIS | **20 de 100**: *sandbox* **20**; prazo **0**, custo **0**, modelo **0**, cobertura **0** (sem Unitel Money e com as três próprias já contadas no *sandbox*) | **não adopta** — falta prazo e custo |
| **ProxyPay (OPG, Express)** | **não decidido** — a assinatura do *callback* é **NV**; o KAM-056 trata o *callback* do OPG como **dica** até resposta escrita | **IND** | não pontua à parte: é um *rail* dentro do candidato acima | **não adopta** |
| **AppyPay** | **não satisfeito hoje** — assinatura, *retry* e idempotência do *webhook* são **NV**; nenhuma consulta de estado confirmada por escrito | **satisfeito** — CONFIRMADO nos termos cl. 1.5 | **35 de 100**: custo **25** (a única célula CONFIRMADA), cobertura **10**; *sandbox* **0** (IND, não CONF), prazo **0**, modelo **0** | **não adopta** — **falha o eliminatório (a)** |
| **EMIS directo** | **não satisfeito** — *callback* não assinado e sem consulta de estado (IND, uma só fonte) | **IND** | não se pontua | **excluído** pelo eliminatório (a) |

**Nenhum caminho adopta hoje, e os dois melhores falham por razões opostas** — a
ProxyPay tem o contrato técnico e não tem preço; a AppyPay tem o preço e não tem
o contrato técnico. É um resultado útil: diz que as perguntas 7 (preço ProxyPay)
e 12 (assinatura AppyPay) são, cada uma, a única pergunta que destrava o seu
candidato. São as duas P0 que o §2.8 manda enviar primeiro.

### 5.3 A saída de falha: `ManualProvider` à semana 6

Sem contrato à **semana 6**, o Piloto fica em `ManualProvider` (Carta §4.2) e **a
decisão é escrita**. O que isso significa, operacionalmente, já está desenhado e
não se reinventa aqui: confirmação humana auditada, com valor máximo por pedido
por *tenant* e registo de quem confirmou
(`../../04_Pagamentos_Liquidacao_AntiFraude.md` §4). No *billing* da própria
plataforma, a confirmação é de operações com **duas pessoas distintas**
(KAM-059, critério 5).

**O que `ManualProvider` não é:** não é «a plataforma recebe e depois repassa».
Continua a ser a PME a receber, pelos canais dela; o que é manual é a
**confirmação**, não a **liquidação**. Confundir as duas era entrar no desenho B
do §7.

### 5.4 Insumo para D4

| Campo | Valor |
|---|---|
| Decisão | **D4** — facilitador (ProxyPay ou AppyPay) e modelo de *onboarding* por PME |
| Estado | **aberta** |
| Dono | **fundador** (`../../00_Arquitectura_Solucao.md` §13.3) |
| Data deste insumo | 2026-11-06 |
| Regra pré-registada | §5.1: dois eliminatórios, cinco ponderados, mínimo 60 de 100 — pesos e mínimo como ***proposta*** |
| Aplicação ao que hoje se sabe | §5.2: **nenhum candidato adopta**; o melhor tem 35 e falha um eliminatório |
| Gatilho de decisão | A resposta escrita à pergunta **7** (preço ProxyPay) ou à **12** (assinatura do *webhook* AppyPay) — cada uma destrava o seu candidato |
| Gatilho de falha | A **semana 6** sem contrato → `ManualProvider`, decisão escrita (§5.3) |
| Decisão tomada aqui | **nenhuma.** Registar não é fechar; as linhas de assinatura do §12 ficam vazias |

> **Duas leituras ficam devolvidas ao Responsável de Produto, e não foram
> decididas aqui** (§11, itens 9 e 10): **(a)** o critério 5 chama «ponderados»
> aos sete critérios, e o §5.1 lê dois deles como **eliminatórios** por força do
> ADR-004 e do ADR-013 — é uma leitura de canon, não uma preferência, mas é
> leitura; **(b)** os pesos e o mínimo de 60 são a primeira calibração, e uma
> calibração que ninguém reviu é uma *proposta*, não uma regra.

---

## 6. Se H5 falhar: o impacto em KAM-056, KAM-057 e KAM-059

Esta secção só entra em vigor com H5 **`refutada`** pela regra do §4.2 — não com
`inconclusiva`, que é o estado de hoje. O que `14` §6 manda é: manter as camadas
1–2 e vender atendimento e agenda **sem cobrança integrada**.

| Ticket | O que é hoje | O que muda se H5 for `refutada` | O que **não** muda |
|---|---|---|---|
| **KAM-056** — Adapter ProxyPay (RPS, *callbacks* HMAC, reconciliação, expiração) | `feature`, Fase 1, P1, estimativa L, com `ext:KAM-103` nas dependências | **Não se implementa no Piloto.** O próprio ticket já tem a saída escrita no seu critério 8: sem contrato à data de fim da Fase 1, o adaptador fica com **`proxypay_enabled=false`** e registra-se a decisão, **com o gatilho nomeado como H5**. Com H5 `refutada`, o gatilho disparou: a saída deixa de ser contingência e passa a ser o plano | A interface `PaymentProvider` e o `ManualProvider` são o **KAM-052** e o **KAM-053**, e não dependem deste ticket. O Piloto continua a ter como confirmar um pagamento — com uma pessoa, auditada |
| **KAM-057** — Avaliação da AppyPay e matriz de decisão | `spike`, Fase 1, P2, estimativa S, com `ext:KAM-103` | **Reduz-se, não cai.** O KAM-057 é um *spike* de decisão escrita, e uma decisão escrita «não adoptar, por estas razões» é produto válido dele. O que cai é o rascunho de `ProviderCapabilities` com valores que nenhuma resposta sustenta — e o critério 3 do próprio ticket já o proíbe («nenhum critério NÃO VERIFICADO é tratado como facto na decisão») | O registo MADR continua a fazer-se. Um «não» documentado tem o mesmo valor de canon que um «sim» |
| **KAM-059** — *Billing* da plataforma via `PaymentProvider` | `feature`, Fase 1, P1, estimativa L. **Não depende de KAM-103** nas dependências declaradas | **Muda o caminho, não o escopo.** O ticket já prevê o caso: «a conta EMIS própria da KAMBÁ é NÃO VERIFICADA (D4); saída: `ManualProvider` + factura manual», e o critério 5 exige confirmação de operações com **duas pessoas distintas**. Com H5 `refutada`, essa saída passa a ser o caminho único: a KAMBÁ cobra as PMEs por transferência, confirmada à mão, com dupla aprovação | `commission_enabled=false` continua por omissão (D8, ADR-017) — e isso **não** é efeito de H5: a comissão está desligada por outra razão, que é a atribuição inauditável. Nenhum documento fiscal é emitido por este ticket (D7) |

**O que esta secção não faz, de propósito:** não altera a linha de nenhum destes
três tickets no backlog mestre, nem lhes mexe nas dependências. Replanear é
trabalho de outro PR, e fazê-lo aqui sobre H5 `inconclusiva` era replanear sobre
um dado que não existe. O credor está no §11.

**E uma consequência que não é de nenhum dos três tickets, e por isso fica dita
aqui:** se H5 for `refutada`, o produto do Piloto deixa de ter cobrança
integrada, e o que a interface promete à PME muda. Quem decide o que se promete
é o Responsável de Produto, não este documento.

---

## 7. A fronteira do ADR-004, e o sinal que vai no sentido contrário

### 7.1 A cláusula que cada minuta tem de ter

O ADR-004 é canon em vigor: pagamentos via facilitador, liquidação **sempre**
directa à PME, e a plataforma **nunca** detém fundos. Receber-e-repassar,
*escrow* e *payouts* só através de PSP licenciado e **fora do Piloto**.

Traduzido para o que uma minuta tem de dizer, e que o advogado do **KAM-104**
revê antes de qualquer assinatura:

| # | O que a cláusula tem de estabelecer | Porquê |
|---|---|---|
| 1 | A liquidação é feita **directamente** na conta bancária da PME (ou na carteira da PME), pela EMIS ou pelo banco, **sem passar por conta da KAMBÁ** | É o desenho A de `../E2_Pagamentos_Angola.md` §3.3, o único CONFIRMADO como fora da necessidade de licença |
| 2 | A KAMBÁ actua como **prestador técnico** e **não** toma posse, em momento algum, de fundos de terceiros | Art. 4, alínea j) do Aviso 2/22, na leitura de `../E2_Pagamentos_Angola.md` §3.2 — **leitura a confirmar por parecer** |
| 3 | O contrato de serviços EMIS e o contrato com o facilitador são **da PME**, e a KAMBÁ **não** é parte nem mandatária para efeitos de recebimento | Senão a KAMBÁ passa a ser o comerciante de registo, que é o desenho B |
| 4 | **Nenhuma** cláusula de retenção, caução, *escrow*, compensação ou dedução de comissão sobre fundos liquidados | Dedução sobre liquidação é posse momentânea. É também a razão por que a comissão está desligada (D8, ADR-017) |
| 5 | **Nenhum** mandato de *payout* a terceiros em nome da PME | Desenho C de `../E2_Pagamentos_Angola.md` §3.3: execução de operações de pagamento, regulado |
| 6 | Se a minuta prever conta-mestre ou modelo ISV, tem de dizer **por escrito** que a Entidade/POSID é **da PME** e a liquidação é para a conta **dela** | É a ambiguidade do §7.2, e é onde o desenho A e o desenho B se parecem no papel |

**Todas as seis levam a ressalva `(a confirmar por parecer)`** onde tocam a
leitura do Aviso 2/22: nenhuma leitura nossa de diploma angolano é definitiva, e
o `../E2_Pagamentos_Angola.md` §0 declara-o nas suas limitações.

### 7.2 O sinal contrário: a conta-mestre tem duas leituras, e uma delas é actividade regulada

**Este é um achado para o fundador, e não uma opção da matriz.**

A pergunta 9 (ProxyPay) pergunta se «uma plataforma multi-comerciante pode ter
uma conta-mestre com sub-comerciantes (cada um com a sua Entidade/POSID) e uma
só chave de API». A pergunta 15 (AppyPay) pergunta pelo modelo *partner/ISV* com
*onboarding* via API. As duas são P0 e as duas são **necessárias**: sem elas, o
*onboarding* de cada PME é trabalho manual nosso.

Mas a pergunta 9, **como está escrita em `../E2_Pagamentos_Angola.md` §9, não
distingue duas coisas que o ADR-004 separa**:

| Leitura | O que significa | Desenho | Compatível com ADR-004? |
|---|---|---|---|
| **(a) uma só credencial, muitas entidades** | A KAMBÁ tem **uma** chave de API; cada PME mantém a **sua** Entidade/POSID; a liquidação vai para a conta de **cada PME** | **A** — facilitador técnico | **sim** |
| **(b) uma só entidade, muitos vendedores** | A KAMBÁ tem a Entidade/POSID **dela** e recebe por todas as PMEs, repassando depois | **B** — plataforma como comerciante único | **não.** `../E2_Pagamentos_Angola.md` §3.3: «provável sub-adquirente / execução de pagamentos para terceiros: exige autorização BNA, segregação, KYC/AML. Alto risco regulatório» |

As duas leituras cabem na mesma frase «conta-mestre com uma só chave de API», e
é por isso que uma resposta «sim» a essa pergunta **não pode preencher a célula
`modelo` da matriz**. Três consequências, e nenhuma delas é uma decisão minha:

1. **A pergunta 9 tem de ser enviada partida em duas**, e o §2.4 já a envia com
   o parêntesis que a desambigua («cada um com a sua Entidade/POSID»). Mas a
   resposta tem de confirmar **as duas metades**: a chave única **e** a entidade
   por PME. Uma resposta que confirme só a primeira é a leitura (b) disfarçada.
2. **Um «sim» não desambiguado é uma célula NÃO VERIFICADO**, não um «sim». Está
   escrito na linha `modelo` do §3.2.
3. **Se alguma proposta que chegue descrever a leitura (b)** — e descrevê-la-á,
   porque é o modelo que dá menos trabalho ao facilitador —, **isso é um achado
   para o fundador**, não uma opção a pontuar. O eliminatório (b) do §5.1 existe
   para isso.

**E há um segundo sinal, mais pequeno, na AppyPay.** O
`../E2_Pagamentos_Angola.md` §1.3 registra a funcionalidade **FTBAI «Funds
Transfers»** como existente na API (INDÍCIO, de SDK de terceiros), com a nota de
que «poderia servir para *payouts*». *Payouts* executados pela plataforma são o
desenho **C** de §3.3, regulado. A pergunta 14 pergunta para que serve e quem
pode usar — e a resposta **não** entra na matriz de D4, seja ela qual for:
*payouts* estão fora do Piloto por ADR-004, e a via legítima é um PSP licenciado
(pergunta 18), em Clusters.

> **Nada neste documento prevê que a KAMBÁ receba ou retenha fundos de
> terceiros.** As quatro colunas da matriz do §3.2 são todas do desenho A, a
> EMIS directa está excluída por outra razão, e a coluna de um PSP licenciado
> **não existe** — a pergunta 18 alimenta o §7.2 e Clusters, e está dito no
> §2.7. A verificação final é do advogado (KAM-104), e é uma caixa de DoD que
> fica **vazia**.

---

## 8. Verificação empírica do *sandbox* da ProxyPay

### 8.1 O instrumento

`spikes/proxypay-d4/`, com `README.md` próprio. Python da biblioteca padrão, sem
dependências, sem Docker e sem rede para fora. Duas peças:

| Ficheiro | O que é |
|---|---|
| `provedor_mock.py` | O **alvo**: um servidor que fala a forma do contrato que `../E2_Pagamentos_Angola.md` §1.2 dá como CONFIRMADA. Guarda de facto o id da referência, remove de facto da fila o que foi reconhecido, e assina de facto sobre os bytes que viajam |
| `sandbox.py` | O **cliente de ensaio**: dez predicados, e um canário que estraga o *mock* de catorze maneiras e exige que o ensaio certo avermelhe |

**Corre-se contra o *mock*, e é isso que o ticket manda:** preparar o *script*,
correr contra o *mock*, e deixar a corrida contra o fornecedor como caixa
devolvida. É o mesmo padrão do **KAM-126**, que o fez com a Vero.

### 8.2 Resultado contra o *mock*

Medido a **2026-11-06**, com `python spikes/proxypay-d4/sandbox.py`:
**10 de 10 predicados verdes**, código de saída 0.

| # | Predicado | Resultado | Facto que está a medir |
|---|---|---|---|
| 1 | `PUT /references/{id}` → 204, e o mesmo id **não** deixa uma segunda referência pagável | verde | `E2` §1.2, CONF |
| 2 | Limites do `amount`: 0,01 e 99.999.999,99 aceitam; 0,00 e 100.000.000,00 recusam | verde | `E2` §1.2, CONF |
| 3 | O pagamento simulado cria o pagamento **e copia** os `custom_fields` | verde | `E2` §1.2, CONF |
| 4 | O evento traz os seis campos de conciliação, **`fee` incluído** | verde | `E2` §1.2, CONF — e é a coluna de custo do §3.3 |
| 5 | `GET /payments` lista; `DELETE` remove o **nosso**; um `DELETE` de id desconhecido **não** esvazia a fila | verde | `E2` §1.2 + `../../04_Pagamentos_Liquidacao_AntiFraude.md` §8, regra b |
| 6 | `X-Signature` = HMAC-SHA256 **do corpo bruto**, com a **própria API key** | verde | `E2` §1.2, CONF |
| 7 | `Token` no RPS e `Bearer` no OPG, e a credencial de um **não** serve no outro | verde | `E2` §1.2, CONF |
| 8 | OPG: `900000000` aceita; `900002004` rejeita com 2004; `900003000` rejeita com 3000; um móvel fora da lista rejeita com 2010 | verde | `E2` §1.2, CONF |
| 9 | OPG: a mesma `Idempotency-Key` devolve **uma** transacção | verde | `E2` §1.2, CONF |
| 10 | **INSTRUMENTO:** o *callback* do OPG chegou, e os cabeçalhos ficaram registados | verde | — |

**O canário: catorze defeitos, catorze vermelhos.** Cada defeito apaga um
predicado e o ensaio correspondente tem de avermelhar. O detalhe está no
`README.md` do *spike*; aqui ficam os dois que valem registo:

- **O `put-nao-idempotente` ficou verde na primeira corrida do canário**, e foi
  o canário a apanhar o **ensaio**, não o contrário: a asserção comparava o
  **conjunto** de `reference_id` da fila, e uma referência a mais com id novo não
  é observável por rota documentada nenhuma. Os dois lados mudaram — o defeito
  passou a deixar duas referências pagáveis **sob o mesmo id**, e o ensaio
  passou a **contar** os pagamentos que um só pagamento simulado produz, que é a
  forma em que um `PUT` não idempotente **cobra o cliente final duas vezes**.
- **A assinatura leva três defeitos**, e o terceiro é o que importa: assinar o
  corpo **reserializado**. É o erro real desta classe de integração — um cliente
  que faça `parse` e volte a serializar antes de verificar fica verde contra um
  fornecedor correcto e **vermelho** contra um que mude um espaço.

**Isto é INDÍCIO-forte sobre o instrumento, e não é evidência sobre a
ProxyPay.** Um *mock* passa nos ensaios de quem o escreveu; a saída do *script*
di-lo na última linha. Não substitui a resposta escrita, e o critério 7 do
ticket já o dizia.

**O ensaio 10 não é um predicado sobre a ProxyPay, e o ensaio di-lo na saída.**
Se o *callback* do OPG é assinado continua **NÃO VERIFICADO**: o
`../E2_Pagamentos_Angola.md` §1.2 diz que a documentação do OPG não menciona
assinatura e manda **assumir que não é assinado**. O *mock* envia-o sem
assinatura por **escolha nossa**, a espelhar essa instrução — pelo que uma
asserção «não vem assinado» mediria a nossa escolha, e uma asserção «vem
assinado» mediria uma coisa que ninguém verificou. O que o ensaio 10 mede é o
**instrumento**: que o receptor recebeu e guardou **todos** os cabeçalhos que
vierem, não só os que alguém escolheu procurar. É a mesma distinção que o
KAM-126 fez no seu predicado 7. Quem fecha a pergunta é a resposta à **8**.

### 8.3 O que falta, e o que custa

| O que falta | Porquê | Custo |
|---|---|---|
| **As chaves do *sandbox*** (`PROXYPAY_API_KEY`, `PROXYPAY_OPG_TOKEN`) | Pedir chaves é contacto com contraparte, e é acto do **fundador**. Sem elas, a forma `--base` **recusa-se a arrancar** em vez de correr metade | um pedido escrito à TimeBoxed, junto com as perguntas 7 a 10 |
| **Adaptar o cliente ao contrato real** | O cliente fala o contrato do *mock*, e **duas peças dele são inventadas**: a rota de configuração do *callback* do RPS (na ProxyPay isso faz-se no **portal**, não por API) e o corpo do pagamento simulado, que não foi lido numa fonte primária | trabalho de **Engenheiro de Pagamentos**; não é «correr e ler» |
| **Correr contra `api.sandbox.proxypay.co.ao`** e anexar a saída a esta secção | Depende das duas linhas acima | — |

**O que a corrida contra o fornecedor acrescenta, e que o *mock* nunca dará:**
o valor real do `fee` numa transacção (o segundo componente de custo do §3.3), o
valor do *rate limit* (hoje NÃO VERIFICADO), e **os cabeçalhos reais do
*callback* do OPG** — que é a única evidência empírica que a pergunta 8 pode ter
antes da resposta escrita, e ainda assim só como INDÍCIO: um *callback* de teste
sem assinatura não prova que o de produção também não tem.

### 8.4 Os números do OPG, e porque não entram no inventário do *gate* 7

Os três números — `900000000`, `900002004`, `900003000` — são **de ensaio,
publicados pelo próprio fornecedor** (`../E2_Pagamentos_Angola.md` §1.2), são
sequenciais, e não pertencem a ninguém. Escrevem-se na forma nacional de nove
algarismos, que é a forma em que a documentação do OPG os publica.

**Medido: nenhum dos três é apanhado pelo varrimento de telefones do *gate* 7, e
por isso nenhum ficheiro deste ticket leva entrada no `INVENTARIO`** de
`tools/meta-sim/src/inventario.ts`.

| O que se mediu | Resultado |
|---|---|
| Método | Os dois padrões de `tools/meta-sim/src/numeros.ts` — `telefone_ao` (`\+?244 ?9[0-9]{8}`) e `e164_entre_aspas` (`"\+[0-9]{9,15}"`) — reimplementados em Python com a mesma lista de pastas e extensões ignoradas de `tools/meta-sim/src/cli.ts` e o mesmo critério de binário (um `NUL` nos primeiros 8 KiB) |
| Sobre a árvore de `refs/remotes/publico/main` em `db0582d` | **33 ficheiros, 115 ocorrências** |
| Confronto com o `INVENTARIO` | **33 entradas, 115 declaradas, e idênticas ficheiro a ficheiro** — zero divergências |
| Os três números do OPG | Nenhum casa nenhum dos dois padrões: o primeiro exige o indicativo `244`, o segundo exige `+` e aspas. **Nove algarismos nus não casam** |
| Controlo independente | O `../E2_Pagamentos_Angola.md` traz os três desde a emissão, **não tem entrada no inventário**, e o *gate* 7 está verde na `main` |

**A fidelidade da reimplementação é CONFIRMADA por coincidência exacta** com o
inventário — que é a saída da ferramenta real —, e não por leitura do código.
Mas o que ela mede é a árvore de hoje: a medição vale para **estes** padrões e
**esta** lista de exclusões, e muda no dia em que um deles mudar.

**Uma entrada a mais seria um defeito, e não precaução.** O `inventario.ts`
recusa entradas mortas: uma entrada que declarasse ocorrências num ficheiro onde
o varrimento não encontra nenhuma **avermelha** o portão. A regra está escrita no
topo do próprio ficheiro, como terceira propriedade do inventário.

**O que não foi medido, e porquê.** O `ci-7-meta` corre
`pnpm --filter @kamba/meta-sim exec node src/cli.ts varrer`, e **nesta máquina
não há `node` nem `pnpm`**: o comando do portão não correu. O que correu foi a
reimplementação acima. Fica **INDÍCIO-forte** — pela coincidência exacta com o
inventário — e a medição que conta é a do *runner*.

---

## 9. Estado por afirmação

A coluna «estado em `../E2_Pagamentos_Angola.md`» é a de origem; a coluna
«estado aqui» é o que este documento afirma. **Não há nenhuma linha em que a
segunda seja mais forte do que a primeira**, e é essa a propriedade que importa.

| # | Afirmação | Estado em `E2` | Estado aqui | Nota |
|---|---|---|---|---|
| 1 | Comissão AppyPay: 0,40%, mín. 50 Kz, máx. 1.500 Kz, IVA a acrescer, independente da do banco | CONFIRMADO | **CONFIRMADO** | A única célula de custo CONFIRMADA da matriz (§3.3) |
| 2 | AppyPay não intervém no fluxo financeiro; liquidação directa pela EMIS | CONFIRMADO | **CONFIRMADO** | É o que satisfaz o eliminatório (b) |
| 3 | Preços ProxyPay | NÃO VERIFICADO | **NÃO VERIFICADO** | Pergunta 7. **Não se transpôs o preço da AppyPay** |
| 4 | O *callback* do OPG é assinado | NÃO VERIFICADO | **NÃO VERIFICADO** | Pergunta 8. O §8 mede o instrumento, não isto |
| 5 | Assinatura, *retry* e idempotência do *webhook* AppyPay | NÃO VERIFICADO | **NÃO VERIFICADO** | Pergunta 12. É o que faz a AppyPay falhar o eliminatório (a) |
| 6 | Prazo de *onboarding* bancário (POSID/Entidade/IEC) | NÃO VERIFICADO | **NÃO VERIFICADO** | Perguntas 1 e 7. É H5, e por isso H5 fica `inconclusiva` |
| 7 | Prazo de *onboarding* da ProxyPay e da AppyPay | NÃO VERIFICADO | **NÃO VERIFICADO** | Perguntas 7 e 11 |
| 8 | Valor do *rate limit* do RPS (existência do 429 é CONFIRMADA) | CONF (existência) / NV (valor) | **igual** | Pergunta 8. Um valor inventado no *mock* punha o ensaio a validar a nossa escolha (§8 e `README` do *spike*) |
| 9 | Contrato técnico do RPS v2: `PUT`, 204, `custom_fields` copiados, HMAC sobre o corpo bruto com a API key, fila de segurança, pagamento simulado | CONFIRMADO | **CONFIRMADO** sobre a documentação; **INDÍCIO-forte** sobre o comportamento, e só contra um *mock* | §8.2. Contra o fornecedor: não medido |
| 10 | Números de ensaio do OPG e os quatro desfechos | CONFIRMADO | **CONFIRMADO** sobre a documentação; comportamento **não medido** contra o fornecedor | §8.2 |
| 11 | Para usar a ProxyPay é necessário contrato com banco angolano e com a TimeBoxed | INDÍCIO (*readme* de *plugin*) | **INDÍCIO** | Pergunta 7. **Não subiu** por aparecer em mais do que um sítio desta casa |
| 12 | Liquidação da ProxyPay é directa via banco/EMIS | INDÍCIO | **INDÍCIO** | É por isso que o eliminatório (b) da ProxyPay está `IND` e não `satisfeito` |
| 13 | Certificado EMIS da AppyPay | CONF (como declaração) / NV (validação) | **igual** | Pergunta 13 |
| 14 | *Sandbox* AppyPay (`gwy-api-tst`) e autenticação OAuth2 | INDÍCIO [BLOG/código] | **INDÍCIO** | Pergunta 11. Por isso a célula `sandbox` da AppyPay pontua **0** no §5.2 |
| 15 | EMIS directo: *callback* não assinado e sem consulta de estado | INDÍCIO (uma só fonte) | **INDÍCIO** | Suficiente para **excluir** (a exclusão é conservadora), insuficiente para **afirmar**. Pergunta 16 |
| 16 | FTBAI «Funds Transfers» existe na API da AppyPay | INDÍCIO [BLOG/código] | **INDÍCIO** | Pergunta 14. Não entra na matriz: é o desenho C (§7.2) |
| 17 | PayPay é PSP licenciado (licença BNA n.º 420) | INDÍCIO | **INDÍCIO** | Pergunta 18. Fora do Piloto |
| 18 | A exclusão do art. 4, alínea j) do Aviso 2/22 cobre o desenho A | CONF do texto / leitura a confirmar por parecer | **igual, com `(a confirmar por parecer)`** | §7.1. Nenhuma leitura nossa de diploma é definitiva |
| 19 | O desenho B (plataforma recebe e repassa) exige autorização BNA | INDÍCIO | **INDÍCIO**, e **suficiente para o eliminatório (b)** | §7.2. Um INDÍCIO de risco regulatório é razão bastante para **não** fazer; não seria razão bastante para fazer |
| 20 | Unitel Money liquida **em carteira**, não em conta bancária | CONFIRMADO | **CONFIRMADO** | É por isso que `cobertura` pesa 10 e não mais (§5.1) |

---

## 10. Dados pessoais, segredos e o que não entra no repositório

| O que | Estado |
|---|---|
| Nomes de pessoas | **nenhum.** O registo de resposta do §2.1 manda identificar o remetente **pelo papel ou pela equipa** |
| Números de telefone reais | **nenhum.** Os três números do OPG são de ensaio, publicados pelo fornecedor, sequenciais, e medidos como fora do varrimento do *gate* 7 (§8.4) |
| NIF, números de conta, IBAN | **nenhum.** Os NIFs do *spike*, se vierem a existir, seguem a forma declaradamente sintética do KAM-126 |
| Chaves de API e segredos | **nenhum.** As do *mock* geram-se em cada arranque e nunca vão a ficheiro; as de um fornecedor vêm do ambiente, e a sua ausência faz o *script* recusar arrancar |
| Documentos bancários | **nenhum**, e é uma caixa de DoD: o arquivo das minutas e das propostas é controlado e **fora** do repositório |
| Identidade dos bancos | o Banco A é **NÃO VERIFICADO** (só o fundador sabe) e o Banco B é uma **proposta** entre os quatro que o `../E2_Pagamentos_Angola.md` §9 já nomeia |

---

## 11. Caixas devolvidas, com credor

| # | O que ficou por fazer | Porquê | Credor |
|---|---|---|---|
| 1 | Enviar as perguntas 1–6 aos dois bancos e registar as respostas (§2.2, §2.3) | Contactar contrapartes é acto do fundador | **fundador** |
| 2 | Escolher **qual** é o Banco A e **qual** é o Banco B (§2.2, §2.3) | O Banco A é onde a empresa do fundador tem conta — facto que só ele tem | **fundador** |
| 3 | Enviar as perguntas 7–10 à TimeBoxed e as 11–15 à AppyPay (§2.4, §2.5) | idem | **fundador** |
| 4 | Enviar as opcionais 16–17 (EMIS) e 18 (PayPay) (§2.6, §2.7) | idem; e a 18 serve Clusters, não D4 | **fundador** |
| 5 | **Pedir as chaves do *sandbox* da ProxyPay** (§8.3) | Pedir chaves é contacto com contraparte | **fundador** |
| 6 | **Adaptar o cliente do *spike* ao contrato real** — rota de configuração do *callback*, corpo do pagamento simulado (§8.3) | O cliente fala o contrato do *mock*, e duas peças dele são inventadas. **Não é «correr e ler»** | **Engenheiro de Pagamentos** |
| 7 | Correr `sandbox.py` contra `api.sandbox.proxypay.co.ao` e anexar a saída ao §8.2 | Depende das linhas 5 e 6 | **Engenheiro de Pagamentos** |
| 8 | **Revisão da minuta de cada contraparte pelo advogado**, antes de assinar (§7.1) | É o KAM-104, e é acto humano. Nenhuma minuta existe ainda | **KAM-104**, e **fundador** para o envio |
| 9 | Decidir se os dois critérios do §5.1 são **eliminatórios** ou ponderados | O critério 5 chama-lhes «ponderados»; o §5.1 lê dois como eliminatórios por força do ADR-004 e do ADR-013. É leitura de canon, e a decisão é de quem escreveu o critério | **Responsável de Produto** |
| 10 | Calibrar os **pesos** e o **mínimo de 60** do §5.1 | São a primeira calibração, escrita para poder ser recusada. Quem escreve as contas não as revê | **Responsável de Produto** |
| 11 | **Decidir D4** | É decisão do fundador, e o gatilho é a resposta à pergunta 7 ou à 12 (§5.4) | **fundador** |
| 12 | Levar ao fundador o achado do §7.2 — a conta-mestre com duas leituras, e o FTBAI | É um achado sobre a fronteira do ADR-004, não uma opção da matriz | **fundador** |
| 13 | Replanear as linhas de KAM-056, KAM-057 e KAM-059 no backlog mestre, **se** H5 for `refutada` (§6) | Hoje H5 é `inconclusiva`; replanear sobre um dado que não existe era o defeito | **Responsável de Produto** |
| 14 | Decidir o que a interface promete à PME se não houver cobrança integrada (§6) | É decisão de produto | **Responsável de Produto** |
| 15 | Correr o `validar_evidencia.py` sobre estas fichas, como os «Testes Requeridos» do bloco pedem | **O ficheiro não existe na árvore.** É artefacto do KAM-100, e dá-lo por corrido era inventar evidência | **KAM-100** |
| 16 | Correr o `ci-7-meta` com `node`/`pnpm` e confirmar o varrimento do §8.4 no *runner* | Nesta máquina não há `node` nem `pnpm`; a medição local é INDÍCIO-forte | **o CI** (*runner* do portão) |

> **Todos os credores são pessoas, papéis, tickets vivos ou o CI — nenhum é uma
> sessão.** Fundir este PR arquiva a sessão que o escreveu; um combinado cujo
> credor fosse «a sessão» ou «quando X aterrar» morria no acto da fusão.

---

## 12. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto (dono de H5; decide os itens 9, 10, 13 e 14 do §11) | | | |
| Engenheiro de Pagamentos (revê a matriz do §3 e é credor dos itens 6 e 7) | | | |
| Responsável de Segurança (revê o §7 e o §10) | | | |
| Fundador (decide D4; é o credor da maioria do §11) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-103. Fichas para seis contrapartes — dois bancos de apoio, ProxyPay/TimeBoxed, AppyPay, e as opcionais EMIS e PayPay — com as perguntas 1 a 18 de `../E2_Pagamentos_Angola.md` §9 endereçadas, a célula da matriz que cada resposta alimenta, e o registo de resposta com os campos do critério 1. O registo e a folha de seguimento **nascem vazios**: zero enviadas, zero respondidas, porque contactar contrapartes é acto do fundador. Regra de classificação pela origem, herdada de [`Meta_Perguntas.md`](Meta_Perguntas.md), com o **verbal a ficar INDÍCIO mesmo vindo da contraparte**. Matriz banco × facilitador com doze linhas e cinco colunas, cada célula com o seu estado: **uma só é CONFIRMADA sobre custo** — a comissão da AppyPay — e o §3.3 diz as três coisas que ela não cobre, entre elas que transpor 0,40% para a coluna da ProxyPay era inventar o preço de um fornecedor a partir do de outro. H5 pré-registado com as três saídas e fica **`inconclusiva`**, amostra zero, porque o prazo bancário é NÃO VERIFICADO sem fonte pública e nenhuma contraparte respondeu — `inconclusiva` não é `refutada`, e a diferença decide se três tickets se replaneiam. Regra de D4 com os sete critérios do bloco: **dois lidos como eliminatórios e não ponderados**, por força do ADR-004 e do ADR-013, e cinco ponderados com pesos e mínimo de 60 como *proposta*; aplicada ao que hoje se sabe, **nenhum candidato adopta, e os dois melhores falham por razões opostas** — a ProxyPay tem o contrato técnico e não tem preço, a AppyPay tem o preço e não tem o contrato técnico, o que identifica as duas perguntas P0 que destravam D4. Impacto escrito em KAM-056, KAM-057 e KAM-059 se H5 for `refutada`, com a nota de que cada um dos três **já tem a sua saída escrita no próprio bloco** e o que H5 muda é o gatilho, não o desenho. O **achado do §7.2 é o mais valioso**: a pergunta da conta-mestre tem duas leituras que a frase de `../E2_Pagamentos_Angola.md` §9 não distingue, e a segunda é o **desenho B** do §3.3 — plataforma como comerciante único, actividade regulada —, pelo que um «sim» não desambiguado é uma célula NÃO VERIFICADO e não um «sim»; o FTBAI da AppyPay é o segundo sinal, na direcção do desenho C. Instrumento de medição em `spikes/proxypay-d4/` (descartável, fora de portão nenhum): **10 de 10 predicados verdes** contra o *mock* e **catorze defeitos, catorze vermelhos** no canário, sendo que o `put-nao-idempotente` **ficou verde na primeira corrida** e foi o canário a apanhar o ensaio — a asserção comparava o conjunto de referências em vez de contar os pagamentos que uma cobrança produz. O **ensaio 10 é instrumento e não predicado**, e di-lo na saída: se o *callback* do OPG é assinado continua NÃO VERIFICADO, e um *mock* que o assinasse punha o *script* a provar a nossa própria escolha. Medido e escrito no §8.4: **nenhum dos três números do OPG é apanhado pelo varrimento do *gate* 7** — 33 ficheiros e 115 ocorrências na árvore, idênticas ficheiro a ficheiro ao `INVENTARIO` —, pelo que **nenhum ficheiro deste ticket leva entrada no inventário**, e uma entrada a mais seria um defeito e não precaução. | Equipa KAMBÁ |
