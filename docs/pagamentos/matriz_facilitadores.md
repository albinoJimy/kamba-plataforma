# Matriz de facilitadores — AppyPay contra ProxyPay

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Matriz de decisão do segundo facilitador: AppyPay contra ProxyPay, custo por transacção e relatório do que ficou por verificar |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-057 (EPIC-05), *spike* |
| Estado | **Misto, por célula.** Nenhuma contraparte foi contactada e nenhuma resposta existe; o que sobe de estado sobe por leitura de **documentação pública do próprio fornecedor**, datada de 2026-11-08 |
| Documento-fonte | [`../tecnica/evidencia/E2_Pagamentos_Angola.md`](../tecnica/evidencia/E2_Pagamentos_Angola.md) §1.2, §1.3, §2, §9 (perguntas 11–15); [`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`](../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md) §3.1, §3.2, §3.4, §5, §10.2; [`../tecnica/evidencia/validacao/Pagamentos_Respostas.md`](../tecnica/evidencia/validacao/Pagamentos_Respostas.md) §2.5, §3, §5 |
| Decisão | [`../adr/ADR-L011-segundo-facilitador-appypay.md`](../adr/ADR-L011-segundo-facilitador-appypay.md) — estado **proposto** |
| Perguntas | [`perguntas_appypay.md`](perguntas_appypay.md) — **redigidas, por enviar**; o envio é do fundador |
| Dono | Responsável de Produto (dono de D4 pela Carta §4.2); o **fundador** é o único a contactar contrapartes e a ratificar |

> **O que mudou desde o `../tecnica/evidencia/E2_Pagamentos_Angola.md`, e é a razão de esta matriz
> não ser uma cópia dele.** O E2 (pesquisa de 2026-10-08) registou que a documentação da AppyPay em
> Stoplight «é uma SPA que não consegui renderizar», e por isso tudo o que dizia do contrato técnico
> da AppyPay era INDÍCIO de SDK de terceiros. **A 2026-11-08 a documentação renderizou** num navegador,
> sem *login*, sem aceitar termos e sem *cookie banner*, e foi lida directamente. Três coisas mudam
> de estado por isso, e uma delas pesa na decisão:
>
> 1. **A consulta de estado existe e está documentada pelo fornecedor** — `GET /charges/{id}` e
>    `GET /charges?merchantTransactionId=…` (§3, critério 2). É **CONFIRMADO** como *documentação*;
>    o comportamento contra um pagamento real **não foi medido**, e o próprio fornecedor dá dois
>    conjuntos de estados diferentes em duas páginas.
> 2. **A documentação publicada do *webhook* não mostra assinatura nenhuma.** As quatro amostras
>    (GPO, REF, SDD, eTPA) trazem `POST {URL}` com um único cabeçalho, `Content-Type: application/json`,
>    e nenhuma página descreve segredo, HMAC, cabeçalho de assinatura ou verificação (§3, critério 1).
>    **Isto não é uma negativa escrita** — o silêncio de uma página não prova que o *webhook* não é
>    assinado —, pelo que a célula fica **NÃO VERIFICADO**, com a ausência registada como INDÍCIO.
> 3. A autenticação, as bases e o limite do `merchantTransactionId` passam de INDÍCIO a
>    **CONFIRMADO** (documentação), com uma correcção: o *token* vem de um *tenant* Azure AD de
>    **desenvolvimento**, e o de produção continua **NÃO VERIFICADO**.
>
> **Nada aqui foi pedido, enviado, aceite ou assinado.** Não se criou conta, não se pediram
> credenciais e não se chamou o *sandbox*. As perguntas estão redigidas em
> [`perguntas_appypay.md`](perguntas_appypay.md) com a data de redacção, e enviá-las é acto do
> fundador.

---

## 1. Método, fontes e o que não foi acessível

### 1.1 Como se leu

| Via | O que produz | Estado máximo que sustenta |
|---|---|---|
| **Navegador, página renderizada** — o texto da página extraído do DOM depois de o JavaScript correr | O texto da página tal como o fornecedor o publica | **CONFIRMADO** quando a página é do próprio fornecedor (escala do `../tecnica/evidencia/E2_Pagamentos_Angola.md` §0 e regra de classificação de `../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §2.1: «página oficial do fornecedor») |
| **Leitura por sumarizador** (*WebFetch*) — o HTML passa por um modelo que responde a uma pergunta | Um resumo, com citações que o modelo diz literais | **CONFIRMADO (resumo)**, na convenção do E2 §0 ponto 1: os números e as frases citadas devem ser confirmados na fonte antes de entrarem em contrato |
| Herdado do E2 sem nova leitura | O estado e a fonte do E2, com a data dele (2026-10-08) | O que o E2 diz, sem promoção |

**A regra que esta matriz não viola:** a ausência de uma afirmação numa página **não** é uma
afirmação de ausência. Onde a documentação se cala, a célula fica **NÃO VERIFICADO**, e o silêncio
regista-se como INDÍCIO de ausência quando a página é a que devia falar disso.

### 1.2 Fontes, todas consultadas a 2026-11-08

| Id | Fonte | URL | Via |
|---|---|---|---|
| S1 | AppyPay — *Charges Webhook (Transactional Webhook)*, quatro separadores | https://appypay.stoplight.io/docs/appypay-payment-gateway/c48b10e5d96e5-charges-webhook-transactional-webhook | navegador |
| S2 | AppyPay — *Charges* (pedidos síncronos e assíncronos, reembolsos) | https://appypay.stoplight.io/docs/appypay-payment-gateway/45990cb0c9d19-charges | navegador |
| S3 | AppyPay — *Get a charge* (`GET /charges/{id}`) | https://appypay.stoplight.io/docs/appypay-payment-gateway/b72da81707c4b-get-a-charge | navegador |
| S4 | AppyPay — *Get all charges* (`GET /charges`, filtros) | https://appypay.stoplight.io/docs/appypay-payment-gateway/a295158c1a7db-get-all-charges | navegador |
| S5 | AppyPay — *Post a Charge* (`POST /charges`) | https://appypay.stoplight.io/docs/appypay-payment-gateway/62b060530d899-post-a-charge | navegador |
| S6 | AppyPay — *Authentication and Authorization* e *Get a token* | https://appypay.stoplight.io/docs/appypay-payment-gateway/131cb8e51d9f2-authentication-and-authorization ; https://appypay.stoplight.io/docs/appypay-payment-gateway/73a20f59c9d9d-get-a-token | navegador |
| S7 | AppyPay — *AppyPay-API* (bases TEST e PROD, servidor *mock*) | https://appypay.stoplight.io/docs/appypay-payment-gateway/b984ae862a208-appy-pay-api | navegador |
| S8 | AppyPay — *Supported Payment Methods* (operações por método, limites, *webhook* por método) | https://appypay.stoplight.io/docs/appypay-payment-gateway/6a14vlzwhui8u-supported-payment-methods | navegador |
| S9 | AppyPay — *Errors* (códigos HTTP e códigos internos) | https://appypay.stoplight.io/docs/appypay-payment-gateway/0xz2op2epwc6t-errors | navegador |
| S10 | AppyPay — *Funds-Transfers* (FTBAI) | https://appypay.stoplight.io/docs/appypay-payment-gateway/809pcqp2gtyrx-funds-transfers | navegador |
| S11 | AppyPay — *Post a charge refund* | https://appypay.stoplight.io/docs/appypay-payment-gateway/7225e362e0416-post-a-charge-refund | navegador |
| S12 | AppyPay — Termos de utilização, cláusulas 1.5, 4.1, 4.2, 10.5 e anexo «Preçário geral» | https://www.appypay.co.ao/termos-de-utilizacao | navegador (texto do acordeão lido do DOM) |
| S13 | AppyPay — FAQ | https://appypay.co.ao/faqs | sumarizador |
| S14 | AppyPay — página de API (`/api-info`) | https://appypay.co.ao/api-info | sumarizador |
| S15 | ProxyPay — RPS v2 | https://developer.proxypay.co.ao/rps/v2/ | sumarizador |
| S16 | ProxyPay — OPG v1 | https://developer.proxypay.co.ao/opg/v1/ | sumarizador |
| E2 | Herdado de `../tecnica/evidencia/E2_Pagamentos_Angola.md` §1.2 e §1.3 | as URL que o E2 cita | pesquisa de 2026-10-08 |

### 1.3 Fontes não acessíveis, e porque não se avançou

| Fonte | O que aconteceu | O que se fez |
|---|---|---|
| https://backoffice.appypay.co.ao/developers | Devolve só o título «Portal Backoffice», sem conteúdo legível. É a porta do portal do comerciante | **Não se avançou.** Registada como fonte não acessível; entrar exigiria conta, e criar conta está fora do que este *spike* pode fazer |
| Ligação «Sign in» da Stoplight | Presente em todas as páginas | Não usada. Tudo o que se cita aqui leu-se sem sessão |
| https://appypay.co.ao/precos-1-2 | **Já não mostra a percentagem**: diz só «sem custos de adesão ou subscrição» e «uma baixa comissão por cada pagamento recebido» | O preço passa a assentar no anexo «Preçário geral» dos termos (S12), lido directamente. O E2 citava esta página para os 0,40% e o mínimo de 50 Kz, e essa fonte deixou de os conter |
| Página *Migration Guide v1.2 to v2.0* | Ficou em «Loading…» | Não lida; nada nesta matriz depende dela |
| Busca da Stoplight por «signature», «HMAC», «idempot», «retries», «duplicate» | Resultados inconsistentes entre tentativas (dois «No search results», o resto sem resposta legível) | **Não se usa como evidência.** A ausência de assinatura assenta na leitura de S1, não na busca |

---

## 2. Como se lê a matriz

Cada célula leva o **estado** e a **fonte** (os ids do §1.2). `CONF` é CONFIRMADO, `IND` é INDÍCIO,
`NV` é NÃO VERIFICADO. A última coluna diz, para cada linha com alguma metade por verificar, **a
pergunta escrita que a fecha** (numeração de `../tecnica/evidencia/E2_Pagamentos_Angola.md` §9, e os
acréscimos declarados em [`perguntas_appypay.md`](perguntas_appypay.md)) **ou o critério de saída**
que a fecha sem pergunta. É o que o critério 3 do ticket pede: nenhum NV fica sem caminho.

Os doze primeiros critérios são os que o critério 2 do ticket enumera, pela ordem dele. Os sete
seguintes são acréscimos, porque a decisão precisa deles e o ticket não os proíbe.

---

## 3. A matriz

| # | Critério | AppyPay | ProxyPay (RPS referência / OPG Express) | Pergunta ou saída |
|---|---|---|---|---|
| 1 | **Assinatura do *webhook*** | **NV.** As amostras dos quatro separadores de S1 mostram `POST {URL}` com `Content-Type: application/json` e nada mais; nenhuma página lida descreve segredo, HMAC, cabeçalho de assinatura ou verificação (S1, S2, S5). **IND de ausência**: é a página que devia falar disso, e cala-se | **RPS: CONF** — `X-Signature` = HMAC-SHA-256 com a API key sobre o corpo cru, hexadecimal minúsculo (S15; E2). **OPG: NV** — a página descreve o *callback* como POST do objecto da transacção e não descreve assinatura (S16) | AppyPay: **pergunta 12**. ProxyPay OPG: **pergunta 8** (do KAM-103, não deste ticket) |
| 2 | **Consulta de estado** | **CONF (documentação)** — `GET /charges/{id}` e o filtro `merchantTransactionId`, autenticados por *Bearer*, com o histórico em `transactionEvents` (S3); `GET /charges` com filtros, descrito como «useful to check a pending payment status» (S4). **Os estados divergem entre páginas do fornecedor:** S3 e S4 dão `Requested`, `Pending`, `Success`, `Failed`; a lista «Internal Responses» de S9 dá `Success`, `Pending`, `Cancelled`, `Failed` e `Expired` («not available for all payments methods»), e quase todas as recusas do GPO saem `[Cancelled]`. **NV (comportamento)**: que o estado de uma referência paga num ATM horas depois apareça como `Success`, e que concorde com o *webhook*, não foi medido | **RPS: CONF** como fila — `GET /payments` lista o que não foi reconhecido (S15); consulta por referência: NV. **OPG: CONF** — `GET /opg/v1/transactions/{id}` com `status`, `status_datetime`, `status_reason` (S16) | AppyPay: **saída** — o caso «`status()` concorda com o *callback*» da suite de conformidade (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.5) corre verde no *sandbox* antes de qualquer activação, com o mapeamento dos **cinco** estados de S9; e **pergunta 12** para a semântica. ProxyPay RPS: **saída** — a consulta por referência não é precisa, porque a fila de reconciliação a substitui (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §8) |
| 3 | ***Retries* do *webhook*** | **NV.** Nenhuma página descreve reentregas. O *payload* tem `sourceDetails.attempt` (S1), cujo significado não está documentado — não se lê como política de reentrega | **RPS: CONF** — resposta não-2xx (incluindo 3xx) gera reentregas «at increasing intervals»; duplicados possíveis; número e calendário **NV** (S15). **OPG: NV** | AppyPay: **pergunta 12**. ProxyPay OPG: **pergunta 8** (KAM-103). ProxyPay RPS, número e calendário: **saída** — a fila de reconciliação apanha o que as reentregas não entregarem, e o G7 absorve os duplicados |
| 4 | **Idempotência** | **CONF (documentação) que o duplicado é recusado; NV o resto.** O código interno **726** de S9 diz «A referência do comerciante [XXXX] solicitado já existe» (*Duplicated resource*, `[Failed]`, em Charges para GPO, REF e UMM); o **763** é outro, para o número de referência REF. Logo repetir o pedido com o mesmo identificador **não** devolve a cobrança original: é recusado. **Fica NV:** que o 726 seja o do `merchantTransactionId` — o texto inglês diz «reference number» e o português «referência do comerciante» —, o código HTTP com que sai (o `POST /charges` lista um **409** que não descreve, S5), e o âmbito da unicidade. Não há cabeçalho de idempotência documentado | **RPS: IND** — `PUT /references/{id}` cria ou actualiza pelo `id` (S15), que é idempotente pela semântica do PUT; a página não o diz por extenso. **OPG: CONF** — `Idempotency-Key` com *cache* de 5 minutos; mesma chave e corpo diferente dá 400 (S16) | AppyPay: **pergunta 12-a** (acréscimo declarado). ProxyPay RPS: **saída** — a idempotência é nossa (`chargeId` antes da chamada, `../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.1), e a suite §3.5 mede o PUT repetido |
| 5 | **Ambiente de testes** | **CONF (existência)** — base TEST `https://gwy-api-tst.appypay.co.ao/{version}` e um servidor *mock* da Stoplight (S7); a página de API declara «um ambiente de testes» (S14, resumo). **NV (acesso)** — as credenciais geram-se no portal ou pedem-se ao gestor comercial (S6) | **CONF (existência)** — `https://api.sandbox.proxypay.co.ao` e pagamento simulado `POST /payments` só no *sandbox* (S15); números de ensaio do OPG (E2). **NV (acesso)** — as chaves não existem (`../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §8.3) | AppyPay: **pergunta 11**. ProxyPay: o **pedido de chaves** que segue com as perguntas 7–10 (KAM-103 §2.8). A chamada de teste que o ticket dá como opcional **não se fez** (§6) |
| 6 | **Autenticação** | **CONF (documentação, ambiente de testes)** — OAuth2 *client credentials* sobre Azure AD B2C, *token* de uma hora, `Authorization: Bearer` (S6). O *endpoint* do *token* documentado é o de um *tenant* de **desenvolvimento** do fornecedor; **o de produção: NV**. O E2 dava `auth.appypay.co.ao` por SDK de terceiros — a documentação não o confirma | **CONF** — RPS `Authorization: Token <API_KEY>`; OPG `Authorization: Bearer` (S15, S16). A chave HMAC do RPS **é** a API key: rodá-la exige janela de duas chaves (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.3) | AppyPay: **pergunta 11-c** (acréscimo declarado) |
| 7 | **`merchantTransactionId` ≤ 15** | **CONF** — 1 a 15 caracteres, padrão `^[a-zA-Z0-9]+$`, no pedido e no *webhook* (S1, S5). O `numero_publico` (oito caracteres de Crockford) cabe. **Mas uma encomenda pode ter mais do que uma cobrança** (expirar e voltar a cobrar), e a documentação recusa o identificador repetido (código 726, linha 4): a segunda cobrança da mesma encomenda com o mesmo `numero_publico` é **recusada**, salvo se a unicidade deixar de valer depois de a primeira expirar — **NV** (ver o ADR-L011, consequências) | **NV** quanto a limite: nenhum comprimento documentado para o `id` da referência. **CONF** a correlação por `custom_fields`, até 10 pares (S15; E2) | AppyPay: **pergunta 12-a** — âmbito da unicidade e repetição depois de expirar. ProxyPay: **saída** — a correlação é por `custom_fields = {charge: chargeId}`, que não tem o limite |
| 8 | **Reembolso** | **CONF, com divergência interna** — total ou parcial por API (S11). A página *Charges* diz «only supported by GPO and UMM» (S2); a tabela de S8 dá UMM, GPO, eTPA e SDD. **As duas fontes são do fornecedor e discordam** em eTPA e SDD; concordam em GPO e UMM, e em **REF sem reembolso** (S8; E2) | **RPS: CONF sem reembolso** (referência). **OPG: CONF** — «Only full refunds are currently supported» (S16, resumo). O E2 tinha o reembolso do OPG como NV | **Saída**, e não pergunta: o reembolso automático está **desligado por canon** (ADR-004, guarda G-2; reembolso é processo manual da PME, G-6). A divergência fica registada e não muda a decisão |
| 9 | **Unitel Money** | **CONF** — método UMM, mínimo 50 AOA, aprovação em 30 s (S8); liquidação em **carteira**, não em conta bancária (S13, resumo; E2). **O preço do UMM: NV** — o anexo de preços dos termos cobre «GPO, REF e SDD» e não o UMM (S12). E dois métodos vêm marcados como imaturos em S8: **SDD `[ALPHA]`** e **eTPA `[BETA]`** | **IND de ausência** — o E2 lista três APIs na ProxyPay (RPS, OPG, DDS), nenhuma de carteira; é silêncio, não negativa escrita | AppyPay: **pergunta 11-b** (acréscimo declarado). ProxyPay: a resposta à **pergunta 7** (KAM-103), cujos contratos-tipo enumeram os serviços |
| 10 | **Preço (componente do facilitador)** | **CONF** — 0,40% por transacção com sucesso em GPO, REF e SDD, mínimo 50 AOA, máximo 1 500 AOA; 75 AOA por mês por ADC (débito directo) activa; SMS 20 AOA e e-mail 5 AOA se activos; «sujeitos ao IVA à taxa em vigor»; independente da comissão do banco de apoio, cl. 4.2 (S12, leitura directa) | **NV** — sem preçário público (E2 §1.2; a S15 não fala de preço) | ProxyPay: **pergunta 7** (KAM-103). O componente bancário, nos dois: **perguntas 1 e 2** ao banco (KAM-103) e §4 |
| 11 | **Prazo de *onboarding*** | **NV.** A FAQ exige contrato de operação e manutenção assinado pelas duas partes antes do uso (S13, resumo) e não dá prazo; o «*onboarding* automático só com o NIF» é marketing e refere-se à conta AppyPay, não às credenciais EMIS (E2 §1.7) | **NV** (E2 §1.2; KAM-103 §2.4) | AppyPay: **pergunta 11-a** (acréscimo do KAM-103). ProxyPay: **pergunta 7** (KAM-103). Bancos: **pergunta 1**. É H5 |
| 12 | **Estrutura de fundos** | **CONF** — «não intervém no fluxo financeiro»; a EMIS credita «directamente (…) na conta bancária do Cliente domiciliada no Banco de Apoio ou na carteira da UNITEL Money» (S12, cl. 1.5, leitura directa). **E o sinal contrário, que não é opção:** a API tem **transferências de fundos** (FTBAI), interbancárias e intrabancárias, só com o BAI como banco devedor e credor, marcadas *BETA* (S8, S10). Usá-las seria o desenho C — *payouts* — e fica **fora** por ADR-004 | **IND** — «directa via banco/EMIS» é do quadro-resumo do E2 §1.1, não de confirmação escrita; é o portão (b) que o KAM-103 deixou bloqueado (`../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §5.2) | AppyPay FTBAI: **pergunta 14**. ProxyPay: **perguntas 5 ou 9** (KAM-103) |
| 13 | **Fila de reconciliação** | **Sem fila de não-reconhecidos documentada.** A reconciliação possível é **por listagem**: `GET /charges` com `dateFrom`, `dateTo`, `limit` e `skip` (S4) — CONF como listagem, e não há operação de reconhecimento | **RPS: CONF** — `GET /payments?n=…` e `DELETE /payments/{id}` (S15) | **Saída**: o adaptador declara `reconciliationQueue=false` e reconcilia por listagem; a suite §3.5 mede-o |
| 14 | **Liquidação** | **CONF** — Express no fecho do TPA virtual (por omissão entre 08:00 e 08:30 GMT+1), referências às 20:00 GMT+1, UMM na carteira (S13, resumo; E2). D+ por banco: **NV** | **IND** — directa via banco/EMIS (E2 §1.1); dia e hora **NV** | Bancos: **pergunta 3** (KAM-103). A interface nunca promete «dinheiro na hora» |
| 15 | ***Rate limit*** | **NV** — S9 lista os códigos HTTP sem 429 e nenhuma página dá limite | **CONF (existência)** — HTTP 429 «Too Many Requests»; **valor NV** (S15, S16) | AppyPay: **pergunta 12-b** (acréscimo declarado). ProxyPay: **pergunta 8** |
| 16 | **Responsabilidade contratual** | **CONF** — limitada «ao valor pago pelo serviço APPYPAY, no último mês de utilização, exclusive o imposto» (S12, cl. 10.5) | **NV** — sem contrato-tipo público | ProxyPay: **pergunta 7**. **Saída**: os termos da plataforma não prometem garantia que não se possa repassar (E2 §8) |
| 17 | **Quem pode contratar** (pessoa singular sem NIF) | **CONF para empresa** — «qualquer empresa pública ou privada que o Banco de apoio autorize» (S13, resumo; E2). **Pessoa singular ou empresário sem NIF: NV** | **NV** — os requisitos são do banco (E2 §1.2) | Bancos: **pergunta 1** (KAM-103). A segmentação do Piloto é PME formal com NIF (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §10.2) |
| 18 | ***Replay* e *timestamp* assinado** | **NV** — sem assinatura documentada, também não há *timestamp* assinado | **NV** — a assinatura do RPS cobre o corpo cru (S15) e a página não descreve *timestamp* nenhum na assinatura; o campo `datetime` do evento vai **dentro** do corpo, o que não é janela de *replay*. É o que o `../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5 já regista como NÃO VERIFICADO | **Saída**: a defesa é a idempotência G7 por `provider_event_id` (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5), nos dois |
| 19 | **Expiração e janela de aprovação** | **CONF, com duas divergências internas** — referência expira por omissão às 72 h, com data configurável (S8). **Aprovação do GPO:** 60 s na tabela de S8, contra 90 s na FAQ (S13) e nas mensagens dos códigos 210/211 de S9. **Latência do pedido síncrono** (outra coisa): «up to 60 seconds» em S2, contra «up to 90 seconds» em S5 | **CONF** — OPG expira aos 30 min; o cliente tem 90 s (S16; E2); a referência RPS leva `end_datetime` (S15) | **Saída**: o prazo vive em configuração por fornecedor, e a máquina de estados trata `aguarda_cliente` com o maior dos valores até haver resposta |

**Contagem, para que a afirmação do critério 2 se possa conferir:** dezanove critérios, os doze do
ticket mais sete. Em cada linha as duas metades levam estado e fonte. Das trinta e oito células, as
que dizem **NV** em alguma parte têm todas uma pergunta ou uma saída na última coluna.

### 3.1 Os outros candidatos que o ticket nomeia

Os «Detalhes Técnicos» do bloco mandam comparar também a EMIS directa, a MoMenu e a Paybyrd. **Não
se releram a 2026-11-08**: o estado é o de `../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.2,
que o herda do E2 §1.4 e §1.5, e não sobe aqui. Basta para os pôr fora desta decisão, e diz-se
porquê:

| Candidato | Portão do ADR-013 (confirmação autenticada) | Portão do ADR-004 (liquidação directa) | Porque fica fora desta decisão |
|---|---|---|---|
| **EMIS directo** | *Callback* **não assinado** e **sem consulta de estado** — IND, uma só fonte, código de terceiros | directa ao banco, IND | **Excluído** pelo portão do ADR-013 enquanto o IND não for desmentido (pergunta 16, KAM-103) |
| **MoMenu** | *Webhook* sem assinatura nem reentrega; a consulta de estado é a confirmação fiável — IND, código de terceiros | **NV** — o mesmo código diz que opera «por cima da licença de outra empresa» | O portão do ADR-004 não se pode avaliar; sem fonte do próprio fornecedor, não é comparável |
| **Paybyrd** | NV | NV — entidade estrangeira; elegibilidade e moeda NV | Candidato de fase D (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.2), fora do Piloto |

---

## 4. Custo por transacção em dois componentes

O ticket pede o custo modelado em **dois componentes** — facilitador e comissão bancária/EMIS —,
com os intervalos marcados e o impacto no preço da PME. Os valores de encomenda abaixo são
**ilustrativos** (escolhidos para atravessar o mínimo e o máximo), e não dados do Piloto.

### 4.1 A AppyPay, componente do facilitador — CONFIRMADO

`custo = min(max(0,40% × valor; 50 AOA); 1 500 AOA)`, **mais IVA** à taxa em vigor (S12). O mínimo
morde abaixo de 12 500 AOA e o máximo acima de 375 000 AOA.

| Valor da encomenda | 0,40% | Componente AppyPay (sem IVA) | Em % do valor |
|---|---|---|---|
| 2 000 AOA | 8 | **50** (mínimo) | 2,50% |
| 5 000 AOA | 20 | **50** (mínimo) | 1,00% |
| 20 000 AOA | 80 | **80** | 0,40% |
| 100 000 AOA | 400 | **400** | 0,40% |
| 500 000 AOA | 2 000 | **1 500** (máximo) | 0,30% |

**O IVA acresce e a taxa não se fixa aqui.** O E2 §7 dá a taxa geral de 14% como **INDÍCIO**
(consultoras; o Código do IVA não foi lido), e o anexo dos termos diz só «à taxa em vigor no momento
de facturação». Com 14% o componente sobe de 50 para 57 AOA e de 1 500 para 1 710 AOA — **cálculo
sobre um INDÍCIO**, e não preço.

### 4.2 A ProxyPay, componente do facilitador — NÃO VERIFICADO

Sem preçário público (E2 §1.2). **Não se transpõem os 0,40% da AppyPay**: era inventar o preço de
um fornecedor a partir do de outro, que é o que o *handoff* do ticket proíbe e o que o
`../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §3.3 já recusou.

### 4.3 O componente bancário/EMIS — intervalo marcado como INDÍCIO

É **independente** do facilitador (S12, cl. 4.2) e negociado entre a PME e o banco de apoio. O único
intervalo que o conjunto tem é o de comissões máximas sobre compras do Instrutivo n.º 02/2025 —
**INDÍCIO**, e a aplicação a pagamentos *online* e por referência **não está clara** (E2 §2):

| Valor da encomenda | Tecto bancário (INDÍCIO) | Intervalo do componente bancário |
|---|---|---|
| ≤ 2 000 AOA | até 10 AOA | 0 a 10 AOA |
| 5 000 AOA | até 1% | 0 a 50 AOA |
| 20 000 AOA | até 1% | 0 a 200 AOA |
| 100 000 AOA | até 1% | 0 a 1 000 AOA |
| 500 000 AOA | até 1% (tecto 12 000 AOA) | 0 a 5 000 AOA |

O instrumento que fecha este componente sem esperar pelo banco é o campo `fee` do evento do RPS da
ProxyPay (CONFIRMADO, S15 e E2): mede a comissão bancária de cada transacção. **A AppyPay não tem
campo equivalente documentado** — o `applicationFeeAmount` de S3 não está descrito, e ler nele a
comissão bancária seria inferência.

### 4.4 Custo total e impacto no preço da PME

| Valor da encomenda | AppyPay + banco, sem IVA (intervalo) | Em % do valor | ProxyPay + banco |
|---|---|---|---|
| 2 000 AOA | 50 a 60 AOA | 2,5% a 3,0% | **NV** |
| 5 000 AOA | 50 a 100 AOA | 1,0% a 2,0% | **NV** |
| 20 000 AOA | 80 a 280 AOA | 0,4% a 1,4% | **NV** |
| 100 000 AOA | 400 a 1 400 AOA | 0,4% a 1,4% | **NV** |
| 500 000 AOA | 1 500 a 6 500 AOA | 0,3% a 1,3% | **NV** |

**O que isto diz ao preço, e o que não diz.**

- **O custo é da PME, não da KAMBÁ.** A plataforma não detém fundos e não deduz nada da liquidação
  (ADR-004); a receita do Piloto é a assinatura e a comissão sobre transacção está desligada
  (ADR-017). O custo por transacção não entra no preço da assinatura: entra na margem da PME.
- **O mínimo de 50 AOA é o que morde as encomendas pequenas.** Abaixo de 5 000 AOA o componente
  do facilitador passa de 1% do valor; a 2 000 AOA são 2,5% antes do banco e do IVA. Se a PME do
  Piloto vende sobretudo bilhetes pequenos, a AppyPay pesa-lhe mais do que a percentagem sugere.
- **O componente bancário pode ser maior do que o do facilitador**: a 100 000 AOA, até 1 000 AOA
  contra 400. Escolher facilitador pelo preço dele sem saber o do banco é escolher pela parcela
  menor.
- **O que não se pode dizer:** qual dos dois facilitadores é mais barato. A ProxyPay não tem preço
  público, e o componente bancário é NV nos dois.

---

## 5. O que esta matriz muda no conjunto, e o que não muda

| Documento | O que diz | O que esta leitura acrescenta | Tratamento |
|---|---|---|---|
| `../tecnica/evidencia/E2_Pagamentos_Angola.md` §0 ponto 2 e §1.3 | Stoplight não renderizada; auth, *sandbox*, `/charges` e o limite de 15 são INDÍCIO de SDK | Renderizou e leu-se; quatro linhas sobem a CONFIRMADO (documentação) e uma (*token* de produção) corrige-se | **Não se edita aqui.** É pesquisa datada (2026-10-08); a leitura nova fica nesta matriz com a data dela. Dívida registada em `../dividas-documentais.md` |
| `../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.2, §3.4, §16 | AppyPay: «consulta de estado: endpoint de cobranças (INDÍCIO)»; documentação «não foi lida» | Consulta de estado CONFIRMADA como documentação; *webhook* sem assinatura documentada | Idem: dívida, e o dono do §3 é quem a paga |
| `../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §3.2 e §5.2 | AppyPay bloqueada pelo portão (a): «nenhuma consulta de estado confirmada por escrito» | A documentação pública é escrita e é do fornecedor. **Se** ela contar como «confirmada por escrito», o portão (a) passa para a AppyPay por via da consulta. **E a pontuação muda mesmo sem essa leitura:** pela regra do §5.1 daquele documento, o *sandbox* pontua metade pelo ambiente **documentado** (foi assim que a ProxyPay teve 9 de 18), e o ambiente da AppyPay passou de INDÍCIO a CONFIRMADO (linha 5) — a AppyPay sobe de **24 para 33**. Com o portão (a) satisfeito pela consulta, o critério (a) pontua ainda até 15, e fica **até 48**. Abaixo do mínimo de 60 de qualquer forma; e o §2.5 daquele documento («autenticação e *sandbox*: INDÍCIO») fica desactualizado pela mesma leitura | **Leitura devolvida ao fundador** no ADR-L011: quem escreveu o portão decide se documentação publicada o satisfaz, ou se exige resposta à pergunta 12. A pontuação não se reescreve aqui: é produto do KAM-103, e fica na dívida 204 |

**O que não muda, e é o que mais importa:** D4 continua **aberta**, H5 continua **inconclusiva**,
nenhum facilitador tem contrato, e o Piloto continua em `ManualProvider` até lá.

---

## 6. Relatório: o que não ficou verificado

O critério 7 do ticket manda que o que não ficou verificado vá para o relatório e não para a
decisão. É esta secção.

| O que ficou por verificar | Porquê | Quem o fecha |
|---|---|---|
| A assinatura do *webhook* da AppyPay | A documentação cala-se; o silêncio não é negativa | Pergunta 12, enviada pelo fundador |
| Que `GET /charges/{id}` reflecte um pagamento de referência feito depois, e concorda com o *webhook* | Exige um pagamento no ambiente de testes | Suite §3.5 no *sandbox*, depois das credenciais |
| A chamada de teste ao *sandbox* que o ticket dá como **opcional** | **Não feita, por desenho:** exige credenciais, as credenciais exigem conta, e criar conta ou pedir credenciais é contacto com contraparte — acto do fundador | Quem tiver as credenciais, já com a suite do KAM-056 como molde |
| Retries, idempotência e o significado do 409 | Não documentados | Perguntas 12 e 12-a |
| O *endpoint* de *token* de produção | Só o de desenvolvimento está documentado | Pergunta 11-c |
| O prazo de *onboarding* | Sem fonte pública | Pergunta 11-a e, pelo banco, pergunta 1 |
| A pessoa singular sem NIF | A FAQ diz «empresa» e não fala do resto | Pergunta 1 ao banco |
| O componente bancário do custo | Negociado PME a PME | Perguntas 1 e 2 ao banco; o `fee` do RPS mede-o com uma transacção real |
| O preço do Unitel Money | O anexo de preços não o cobre | Pergunta 11-b |
| O preço da ProxyPay | Sem preçário público | Pergunta 7 (KAM-103) |
| A certificação EMIS da AppyPay | Declaração do próprio, sem validação independente | Pergunta 13 |
| As divergências internas da documentação da AppyPay — reembolso em eTPA e SDD; aprovação do GPO em 60 s contra 90 s, e latência síncrona em 60 s contra 90 s; e quatro estados de cobrança contra cinco | Páginas do fornecedor dizem coisas diferentes | Não mudam a decisão; registadas no §3, linhas 2, 8 e 19, e o mapeamento dos cinco estados entra na suite |

---

## 7. Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Produto |  |  |  |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-057): matriz AppyPay contra ProxyPay em dezanove critérios com estado e fonte por célula, custo por transacção em dois componentes, e o relatório do que ficou por verificar. A documentação Stoplight da AppyPay foi lida pela primeira vez a 2026-11-08. | Equipa KAMBÁ |
