# 02 - Pagamentos e regulação financeira em Angola (comércio conversacional no WhatsApp para PMEs)

Data da pesquisa: 8 de Outubro de 2026. Todas as páginas foram consultadas nessa data (as datas na coluna "Data" são as de publicação/vigência quando conhecidas; "s/d" = página sem data visível).

## 0. Como ler este relatório

Escala de estado:

- **CONFIRMADO**: lido directamente numa fonte primária (diploma do BNA/Assembleia/Presidente, documentação ou termos do próprio facilitador, sandbox/API do próprio facilitador, AGT) ou em duas ou mais fontes independentes consistentes.
- **INDÍCIO**: imprensa económica, escritórios de advogados/consultoras, blogs, SDKs/código de terceiros, resumos de motores de busca, ou declaração de marketing não corroborada. Marcado **[BLOG]** quando é blog ou código não oficial.
- **NÃO VERIFICADO**: não encontrei fonte acessível. Não é o mesmo que "não existe".

Limitações do método (relevantes para quem decide):

1. Alguns sites (PayPay, EMIS, lex.ao, Expansão) falharam intermitentemente por DNS/rede. Quando indico "(resumo)" o texto foi passado por um sumarizador e os números de artigo devem ser confirmados no diploma. Quando indico "(leitura directa)" li o HTML/PDF integral.
2. A documentação da AppyPay (Stoplight) é uma SPA que não consegui renderizar; os detalhes técnicos da AppyPay vêm de SDKs não oficiais e de snippets da própria Stoplight. Tratar como INDÍCIO até receber a documentação por escrito.
3. Não consegui aceder à lista oficial do BNA de prestadores autorizados nem à lista oficial da AGT de software certificado.
4. Nada aqui é aconselhamento jurídico. As conclusões da secção 3 sobre "precisa de licença?" são leitura do texto do Aviso 2/22 e precisam de parecer escrito de advogado angolano e, idealmente, de resposta escrita do BNA.

---

## 1. Facilitadores e APIs

### 1.1 Quadro-resumo

| Facilitador | API pública? | Auth | Callbacks | Sandbox | Preço público | Liquidação | Exige que o comerciante tenha banco/EMIS? |
|---|---|---|---|---|---|---|---|
| ProxyPay (TimeBoxed) | Sim (RPS v2, OPG v1, DDS v1) | Token / Bearer | Sim; RPS com HMAC-SHA256 | Sim | NÃO VERIFICADO | Directa via banco/EMIS (INDÍCIO) | Sim: contrato com banco angolano + TimeBoxed |
| AppyPay | Sim (Stoplight v2.0), acesso ao detalhe não verificado | OAuth2 client_credentials (INDÍCIO) | Sim (obrigatório em REF, INDÍCIO) | Sim (INDÍCIO) | 0,40% (mín. 50, máx. 1.500 Kz) | Directa pela EMIS ao banco do comerciante; Unitel Money para a carteira | Sim: "Banco de Apoio" + serviços EMIS (POSID, Entidade, IEC) |
| EMIS directo (GPO / Express) | Não documentação pública encontrada; só um SDK de terceiros | Token de comerciante (INDÍCIO) | Sim, sem assinatura (INDÍCIO) | NÃO VERIFICADO | Comissão do banco | Directa ao banco | Sim |
| PayPay África | NÃO VERIFICADO | NÃO VERIFICADO | NÃO VERIFICADO | NÃO VERIFICADO | NÃO VERIFICADO | É PSP licenciado (carteira) | NÃO VERIFICADO |
| BitPay.ao | NÃO VERIFICADO (nada encontrado) | - | - | - | - | - | - |
| MoMenu (agregador com factura fiscal) | Sim (INDÍCIO, via skill/SDK de terceiros) | `x-api-key` | Webhook sem assinatura nem reentrega (INDÍCIO) | `x-env-qa: true` (INDÍCIO) | NÃO VERIFICADO | NÃO VERIFICADO | NÃO VERIFICADO |
| Paybyrd (PSP internacional) | Sim, docs públicas | NÃO VERIFICADO | Sim | Números de teste | NÃO VERIFICADO | NÃO VERIFICADO | NÃO VERIFICADO |
| Já-Já, vPOS, Pay4All | Plugins/SDKs; Pay4All é PSP licenciado (INDÍCIO) | - | - | - | NÃO VERIFICADO | - | Já-Já exige contrato com banco angolano (plugin) |
| Unitel Money, Africell Money (Afrimoney) | Sem API de comerciante pública encontrada | - | - | - | - | Carteira | - |
| e-Kwanza | Só via agregadores (Pay4All, MoMenu) | - | - | - | - | - | - |

### 1.2 ProxyPay (TimeBoxed)

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| Existem três APIs: RPS (referências), OPG (pedido de pagamento por n.º de telemóvel, Multicaixa Express) e DDS (débito directo). | CONFIRMADO | https://developer.proxypay.co.ao/ (leitura) | s/d (docs vivas) | Para WhatsApp: OPG (push para o Express do cliente) e RPS (referência para ATM/home banking) cobrem os dois fluxos principais. |
| Bases: produção `https://api.proxypay.co.ao`, sandbox `https://api.sandbox.proxypay.co.ao`. HTTPS obrigatório. | CONFIRMADO | https://developer.proxypay.co.ao/rps/v2/ e /opg/v1/ (leitura directa) | s/d | Existe sandbox sem contrato (pelo menos documentado). |
| RPS v2 auth: `Authorization: Token <API_KEY>`. OPG v1 auth: `Authorization: Bearer <TOKEN>`. DDS: Bearer. | CONFIRMADO | docs RPS v2, OPG v1, DDS v1 | s/d | Dois esquemas de auth no mesmo fornecedor; abstrair no adaptador. |
| RPS: criar referência com `PUT /references/{id}` (`amount` 0,01 a 99.999.999,99; `end_datetime` ISO8601; `custom_fields` até 10 pares string, copiados para o pagamento). Resposta 204. Há `POST /reference_ids` para gerar IDs. | CONFIRMADO | https://developer.proxypay.co.ao/rps/v2/ | s/d | Guardar o `order_id` em `custom_fields`; o PUT é idempotente por `id` da referência. Esse limite 99.999.999,99 é do API, não é limite da rede Multicaixa. |
| RPS webhooks: POST para a URL configurada com cabeçalho `X-Signature` = HexEncode(HMAC-SHA-256(API_KEY, corpo bruto)). Responder 2xx; não-2xx (incl. 3xx) gera reentregas com intervalos crescentes; o mesmo pagamento pode chegar mais de uma vez. | CONFIRMADO | https://developer.proxypay.co.ao/rps/v2/ (leitura directa) | s/d | Validar HMAC sobre o corpo bruto (antes de parse), deduplicar por id do pagamento, responder 2xx rápido e processar em fila. A chave HMAC é a própria API key: rotação implica cuidado. |
| RPS fila de segurança: `GET /payments?n=100` lista pagamentos não reconhecidos; `DELETE /payments/{id}` confirma e remove. | CONFIRMADO | idem; reforçado por https://pkg.go.dev/github.com/spolly-ao/fllex/providers/proxypay [BLOG/código] | s/d | Reconciliação por polling é o mecanismo à prova de webhook perdido. Desenhar worker de reconciliação. |
| O evento de pagamento inclui `entity_id`, `fee` (comissão bancária), `terminal_type`, `terminal_transaction_id`, `terminal_location`, `terminal_id`. | CONFIRMADO | docs RPS v2 | s/d | Útil para conciliação e para custo real por transacção. |
| Há endpoint de pagamento simulado (Mock Payment) só no sandbox. | CONFIRMADO | docs RPS v2 | s/d | Testes automáticos sem dinheiro real. |
| Rate limit existe (HTTP 429) mas o valor não é publicado. | CONFIRMADO (existência) / NÃO VERIFICADO (valor) | docs RPS v2 | s/d | Backoff exponencial; perguntar o limite. |
| OPG: `POST /opg/v1/transactions` com `type=payment`, `pos_id`, `mobile` (n.º Express), `amount` (string, 2 casas), `callback_url` opcional. Estados `accepted` / `rejected`. Códigos de rejeição: 1000-1003 gateway, 2000-2012 processador (2001 saldo insuficiente, 2003 limite diário excedido, 2004 timeout), 3000 recusa do cliente. | CONFIRMADO | https://developer.proxypay.co.ao/opg/v1/ (resumo) | s/d | Mapear códigos para mensagens de WhatsApp compreensíveis ("saldo insuficiente", "tem 90 s para aceitar"). |
| OPG: o pedido expira ao fim de 30 minutos; cabeçalho opcional `Idempotency-Key` com cache de 5 minutos. | CONFIRMADO | idem | s/d | Idempotência só 5 min: a idempotência de longo prazo (duplo clique no WhatsApp, reentrega) tem de ser nossa (chave por `order_id` + tentativa). |
| OPG sandbox: `900000000` aceita (5-20 s); `900002004` rejeita por timeout (90 s); `900003000` recusa do cliente; `9XXXXXXXX` rejeita imediato (2010). | CONFIRMADO | idem | s/d | Dá para automatizar testes de ponta a ponta. |
| O callback do OPG é assinado (HMAC)? | NÃO VERIFICADO | docs OPG não mencionam assinatura | - | Assumir não assinado; confirmar com TimeBoxed. Sem assinatura, confirmar via `GET` da transacção antes de entregar mercadoria. |
| DDS: mandatos CAP (com assinatura) e SAP (activado no banco), IDs ISO 7064, requer inscrição no banco e IEC (identificador da entidade credora). Eventos por polling (stream com offset), sem webhook. | CONFIRMADO | https://developer.proxypay.co.ao/dds/v1/ (resumo) | s/d | Débito directo serve para subscrições recorrentes, mas exige IEC do comerciante (ou da plataforma, ver secção 3). |
| Para usar a ProxyPay é necessário contrato com um banco angolano e com a TimeBoxed. | INDÍCIO | readme do plugin WooCommerce (v4.2, actualizado 3 Ago 2026): https://wordpress.org/plugins/woo-multicaixa | 2026-08-03 | Onboarding do comerciante passa pelo banco dele (semanas, ver secção 1.7). |
| Preços ProxyPay. | NÃO VERIFICADO | `https://www.proxypay.co.ao` hoje só mostra ecrã de login do portal; pesquisa sem resultados | 2026-10-08 | Pedir proposta. |
| Entidade/NIF/alvará exigido ao comerciante. | NÃO VERIFICADO (só se sabe que precisa de banco angolano) | - | - | Os requisitos de KYC são do banco. |
| Referências geradas pelo plugin são válidas 24 h (por configuração do plugin, não limite do API). | INDÍCIO | readme do plugin | 2026-08-03 | A validade é configurável via `end_datetime`. |

### 1.3 AppyPay

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| Métodos: Multicaixa Express (GPO), Pagamento por Referência (REF), Débito Directo (SDD), UNITEL Money (UMM); também links de pagamento, QR, checkout, app, mPOS, gateway marca branca. Plugins WooCommerce e Shopify. | CONFIRMADO | https://appypay.co.ao/ e /faqs (leitura directa) | s/d (© 2025) | Cobertura mais ampla que a ProxyPay num só contrato (inclui Unitel Money). |
| Papel: "não intervém no fluxo financeiro"; limita-se a comunicar à EMIS/UNITEL Mobile Money os pedidos e a processar notificações. Montantes creditados directamente pela EMIS na conta bancária do cliente no "Banco de Apoio" ou na carteira Unitel Money. | CONFIRMADO | https://appypay.co.ao/termos-de-utilizacao cl. 1.5 (leitura directa) | s/d | Modelo de facilitador técnico puro. Liquidação directa ao comerciante, a plataforma nunca toca no dinheiro. |
| O cliente tem de contratar, no seu banco, os serviços EMIS (GPO/REF/SDD) e Unitel Money; o banco e a EMIS disponibilizam POSID e supervisor card (GPO), Entidade (REF) e IEC (SDD). A AppyPay configura o "TPA virtual" na gateway. | CONFIRMADO | termos cl. 4.1-4.2; FAQ | s/d | Cada PME tem de passar pelo seu banco antes de cobrar. Isto é o caminho crítico de onboarding. O "onboarding automático só com o NIF" anunciado em /precos-1-2 refere-se à conta AppyPay, não substitui o banco (contradição de marketing vs termos). |
| Contrato de Operação e Manutenção em suporte físico, assinado por ambas as partes antes do uso; "qualquer empresa pública ou privada que o Banco de apoio autorize". | CONFIRMADO | FAQ | s/d | Sem entidade colectiva com NIF/banco, não há credenciais. Pessoa singular/informal: NÃO VERIFICADO (a FAQ diz "empresa"). |
| Preço: 0,40% por cobrança, mínimo 50 Kz, máximo 1.500 Kz; sem adesão nem mensalidade; 75 Kz/mês por autorização de débito directo activa; SMS 20 Kz, email 5 Kz; IVA a acrescer. Comissão independente da do banco/EMIS. | CONFIRMADO (0,4% e mín. 50: página de preços; máx., DD, SMS: termos, resumo) | https://appypay.co.ao/precos-1-2 ; termos cl. 4.2 e 12 | s/d | Custo AppyPay + comissão bancária negociada pelo comerciante. Para o desenho de preços da plataforma, o custo total por transacção é de dois componentes. |
| Liquidação Express: TPAs virtuais abrem/fecham por defeito entre 08:00 e 08:30 GMT+1; todos os pagamentos do período caem na conta ao fecho. Referências: compensação às 20:00 GMT+1. Unitel Money: dinheiro fica na carteira Unitel Money. | CONFIRMADO | FAQ e páginas de produto (leitura directa) | s/d | Liquidação praticamente diária (D+0/D+1 conforme banco). Para Unitel Money o comerciante recebe em carteira, não em conta bancária. O prazo final depende também do banco: NÃO VERIFICADO por banco. |
| Express: 90 s para o cliente validar com PIN/impressão digital. Reembolso total ou parcial por API/portal, mas o montante tem de estar no TPA virtual no momento do pedido. Referências: não permitem devolução. | CONFIRMADO | páginas de produto e FAQ | s/d | Reembolsos Express só dentro da janela do TPA; para referências, política de devolução tem de ser por transferência fora do gateway. |
| Referências: validade por defeito 72 h; existe referência "carregamento" com pagamentos múltiplos de valor variável. | CONFIRMADO | FAQ | s/d | Boa para créditos/depósitos pré-pagos. |
| Se declara "serviço de facilitação certificado pela EMIS". | CONFIRMADO (como declaração do facilitador) / NÃO VERIFICADO (validação independente na EMIS) | FAQ | s/d | Pedir carta/certificado EMIS. |
| Estatuto regulatório: sociedade anónima, capital 14.000.000 Kz, matrícula 17981-23 na Conservatória do Registo Comercial de Luanda. **17981-23 é número de registo comercial, não licença do BNA.** Não aparece licença BNA nos termos. | CONFIRMADO | termos cl. 1.1 (leitura directa) | s/d | Correcção a uma leitura errada comum ("registo de PSP licenciado"). O desenho jurídico assenta no facto de não tocar nos fundos (secção 3). |
| Responsabilidade da AppyPay limitada ao valor pago pelo serviço no último mês (sem imposto); o cliente assume perdas, falsificações e erros de comunicação, salvo culpa comprovada. | CONFIRMADO | termos cl. 10 | s/d | Risco contratual para a plataforma e para PMEs; reflectir nos T&C da plataforma. |
| API v2.0: base `https://gwy-api.appypay.co.ao/v2.0`, endpoint `/charges`, `merchantTransactionId` 1-15 caracteres alfanuméricos; métodos GPO, UMM, REF (+ eTPA, SDD, FTBAI para transferências, em SDK de terceiros). Auth OAuth2 client_credentials com token em `https://auth.appypay.co.ao/connect/token` (SDK) ou Azure AD (SDK/versão anterior). Sandbox: `https://gwy-api-tst.appypay.co.ao/v2.0`. | INDÍCIO [BLOG/código] | snippets da documentação Stoplight (https://appypay.stoplight.io/docs/appypay-payment-gateway/branches/main/62b060530d899-post-a-charge); SDKs https://github.com/Gomes19/appypay-sdk e https://github.com/bit-ao/appy-pay-php | SDK 2025-12; docs s/d | Contrato de limite de 15 caracteres no `merchantTransactionId`: usar ID curto base-36 mapeado ao `order_id`. Confirmar auth e sandbox por escrito. |
| Webhook: obrigatório em REF; assinatura/HMAC; idempotência; retry. | INDÍCIO (obrigatório em REF) / NÃO VERIFICADO (assinatura, retry, idempotência) | SDK bit-ao (README) | 2025-08 | Pergunta obrigatória à AppyPay. |
| Funcionalidade FTBAI "Funds Transfers" (transferência de fundos) existe na API. | INDÍCIO [BLOG/código] | SDK bit-ao (README) | 2025-08 | Poderia servir para payouts, mas não está documentado publicamente: perguntar se é só para clientes do BAI e em nome de quem. |
| Documentação oficial AppyPay em Stoplight e backoffice. | CONFIRMADO (existência) | https://appypay.stoplight.io/docs/appypay-payment-gateway ; https://backoffice.appypay.co.ao/developers | s/d | Pedir acesso completo e exportar spec OpenAPI. |

### 1.4 EMIS directo (GPO / Multicaixa Express)

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| A EMIS opera o GPO (Gateway de Pagamentos Online) com três métodos: MCX Express, dados de cartão e referência. Integração directa com token de comerciante emitido pela EMIS; a EMIS certifica integradores (prestadores de serviços técnicos). | INDÍCIO | snippets de busca de multicaixa.ao (https://multicaixa.ao/pt/noticias/lancamento-da-gateway-de-pagamento-online/ não abriu) e cliente Go de terceiros | s/d | Possível via directa depois do banco; exige trabalho de integração e certificação. |
| Fluxo directo: `POST /online-payment-gateway/portal/frameToken` (referência, valor, token do comerciante) devolve `id`; cliente abre `/online-payment-gateway/portal/frame?token=<id>`; EMIS envia desfecho por callback. | INDÍCIO [BLOG/código] | https://pkg.go.dev/github.com/spolly-ao/fllex/providers/emis | s/d | Descrição de terceiros: confirmar com EMIS. |
| O callback da EMIS directo **não é assinado** e o GPO não tem consulta de estado (segundo esse código). | INDÍCIO [BLOG/código] | idem | s/d | Se verdade, a defesa é: validar POSID, moeda, tipo e **valor** contra o pedido e usar IP allowlist; não existe segunda fonte. Pesa a favor de usar facilitador com polling/assinatura. |
| Multicaixa Express representou ~62% das operações da rede Multicaixa em 2025 (2,1 mil milhões de operações). | INDÍCIO | https://www.verangola.net/va/pt/012026/BancaSeguros/47451/ (resumo de busca) | 2026-01 | Express é o rail dominante; a plataforma deve tê-lo como primário. |

### 1.5 PayPay África, KWiK, Unitel Money, Africell, e-Kwanza, BitPay.ao, outros

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| PayPay África pertence à Conectando, Sociedade Prestadora de Serviços de Pagamento, Lda., com licença BNA n.º 420; está na lista de PSP autorizados. | INDÍCIO | snippets de busca (Angop / Forbes África Lusófona); lista de 16 PSP em notícias (ver 1.6) | 2024-2026 | PayPay é PSP/carteira: pode legitimamente deter fundos de utilizadores. Utilizável como parceiro licenciado para payouts e contas, se aceitar. |
| PayPay foi o maior operador KWiK em Fev/2026: 1,6 milhões de transferências instantâneas, 52,2% de quota. | INDÍCIO | https://fr.allafrica.com/stories/202603050443.html (resumo de busca) | 2026-03 | KWiK é rail relevante para P2P/pagamentos de comerciante a comerciante. |
| API pública de comerciante da PayPay (QR KWiK, payouts por IBAN). | NÃO VERIFICADO | `https://www.paypayafrica.com` carrega só shell JS; `paypay.ao` não resolveu; não encontrei docs | 2026-10-08 | Tratar como "a negociar" com a PayPay (parceria), não como API de prateleira. |
| BitPay.ao. | NÃO VERIFICADO | nenhuma fonte encontrada | - | Não incluir no desenho até haver evidência. |
| KWiK: sistema de transferência e pagamento instantâneo desenvolvido pela EMIS com o BNA, lançado em Julho 2023; 22 instituições; em 2025 pelo menos 35 milhões de transacções e 590 mil milhões Kz; compatível com todos os bancos e PSP. | CONFIRMADO (múltiplas fontes de imprensa, consistentes) | https://allafrica.com/stories/202602030336.html (2026-01-29); https://forbesafricalusofona.com/?p=97841 (resumo de busca) | 2026-01 | KWiK é um rail de pessoa-a-pessoa; a existência de API de comerciante para pedido de pagamento KWiK: NÃO VERIFICADO. |
| Existem 16 PSP autorizados a emitir moeda electrónica, incluindo Unitel Money e Africell (Afrimoney). | CONFIRMADO (imprensa) | https://www.expansao.co.ao/empresas/detalhe/dezasseis-empresas-autorizadas-pelo-bna-a-emitir-moeda-electronica-62475.html (resumo) | 2024-08-29 | Carteiras são reguladas; a plataforma não pode ter a sua. |
| Unitel Money integrado por AppyPay (UMM, mínimo 50 AOA no SDK) e MoMenu (eKwanza). API directa Unitel/Africell para comerciantes. | INDÍCIO / NÃO VERIFICADO (API directa) | AppyPay; plugin Magento (Meetanshi) | s/d | Para Unitel Money, usar via AppyPay; liquidação fica em carteira. |
| e-Kwanza e Multicaixa Express no POS via Pay4All; vPOS (GPO). | INDÍCIO [BLOG] | https://apps.odoo.com/apps/modules/18.0/pos_pay4all ; https://github.com/v-pos | s/d | Existem alternativas ao duopólio ProxyPay/AppyPay. |
| MoMenu: agregador que cobra por Multicaixa Express (síncrono, ~180 s, sem webhook), eKwanza e referência (webhook não assinado nem reentregue; a confirmação fiável é a consulta de estado), em kwanzas inteiros, com emissão de factura fiscal SAF-T; `x-api-key`, base `https://api.momenu.online`. | INDÍCIO [BLOG/código] | https://pkg.go.dev/github.com/spolly-ao/fllex/providers/momenu ; https://skills.cat/skills/ithustle/momenu-skills/mom-factura-payments | s/d | Interessante porque combina pagamento + factura. Mas o código de terceiros diz que opera "por cima da licença de outra empresa": estrutura de fundos NÃO VERIFICADA. |
| Paybyrd (PSP português) oferece Multicaixa Express: pedido por telemóvel (90 s) ou QR/deeplink, assíncrono, estado "processing" até ao cliente concluir. | CONFIRMADO (docs do próprio) | https://docs.paybyrd.com/accept-payments/bank-transfers/multicaixa-express (leitura directa) | s/d | Possível via para entidade estrangeira da plataforma; elegibilidade, preço, liquidação e moeda: NÃO VERIFICADO. |

### 1.6 Quem está licenciado (indício)

Lista de 16 PSP (notícia sem data clara): Africell Mobile Money, Unitel Mobile Financial Services, Aky Pay, Conectando (PayPay), FaciAngola, Ginga Transfer, Kwattel, LinkedPay, Max Pay, NellPay, Now Now Digital Payments Systems Angola, PagAqi, Pay4all, Real Transfer, SunPay, Victória Transfer (https://www.verangola.net, resultado de busca; INDÍCIO). **ProxyPay/TimeBoxed e AppyPay não figuram** nessa lista, o que é coerente com o modelo "prestador técnico sem posse de fundos". A lista oficial do BNA não foi obtida: NÃO VERIFICADO.

### 1.7 Prazos de onboarding

| Afirmação | Estado | Fonte | Implicação |
|---|---|---|---|
| Prazo para um comerciante obter POSID/Entidade/IEC no banco. | NÃO VERIFICADO | nenhuma fonte pública | Medir com 2 bancos; planear semanas, não dias. Faz parte da lista de perguntas. |
| A AppyPay promete activação automática da conta com NIF. | INDÍCIO (marketing) | https://appypay.co.ao/precos-1-2 | Aplica-se à conta AppyPay, não às credenciais EMIS. |

---

## 2. Rails: referência, Multicaixa Express, KWiK

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| Referência Multicaixa = Entidade + Referência + Valor, paga em ATM, internet banking ou Multicaixa Express. Gera notificação em tempo real ao comerciante. Não admite devolução. | CONFIRMADO | AppyPay (página de referências, leitura directa); ProxyPay RPS | s/d | Rail mais inclusivo (clientes sem Express, pagamento em ATM). Sem chargeback: bom para o comerciante, mau para o cliente em caso de erro (política de disputa nossa). |
| Multicaixa Express (GPO): push no telemóvel, 90 s para validar com PIN/biometria; assíncrono; o comerciante recebe notificação de sucesso. Cliente só precisa do telemóvel. | CONFIRMADO | AppyPay; Paybyrd; ProxyPay OPG (timeout 2004 aos 90 s no sandbox) | s/d | Fluxo ideal para WhatsApp: pedir nº Express, enviar push, mensagem "tem 90 s para aprovar". |
| OPG expira cobrança aos 30 min (ProxyPay) enquanto cliente tem 90 s; MoMenu fala em ~180 s síncronos. | CONFIRMADO (ProxyPay) / INDÍCIO (MoMenu) | docs OPG; pkg.go.dev | s/d | Máquina de estados: `pending -> awaiting_customer -> paid/failed/expired`; timeouts por fornecedor. |
| Limites BNA (Instrutivo n.º 02/2025, 13 Ago 2025): pagamentos Multicaixa diários até 30.000.000 Kz; transferências por cartão 9.000.000 Kz/dia; levantamentos 180.000 Kz/dia (ATM 120.000); compras em TPA 12.000.000 Kz/dia (este último só em imprensa). | INDÍCIO (diploma da EMIS não abriu; números repetidos em Novo Jornal/Kamba Rico/Marcas em Acção, consistentes) | https://marcasemaccao.com/2025/09/22/emis-e-bna-modernizam-sistema-de-pagamentos-angolano-com-novas-funcionalidades-e-limites-actualizados/ ; PDF https://emis.ao/media/zhcpwuer/iinstrutivo-n%C2%BA-02_2025-sistema-de-pagamentos-limites-de-valor-em-opera%C3%A7%C3%B5es-realizadas.pdf (não acedido) | 2025-08-13 / 2025-09-22 | Para ticket de PME (milhares a poucas centenas de milhares de Kz) os limites de rede raramente mordem; o que morde são limites do cartão/banco do cliente (código 2003 "limite diário excedido" no OPG). |
| Limites do Express para **transferências**: 250.000 Kz por operação, 500.000 Kz/dia, 3.000.000 Kz/mês por cartão. | INDÍCIO | Expansão 2025-09-23 (resumo); Marcas em Acção | 2025-09 | Aplica-se a transferências P2P no Express, não a pagamentos de comerciante. |
| Limite por transacção em **pagamentos GPO/referência** a comerciante. | NÃO VERIFICADO | - | - | Pergunta ao banco/EMIS. |
| Comissões máximas sobre compras: >2.000 Kz até 1% (tecto 12.000 Kz); ≤2.000 Kz até 10 Kz; isenção até 2.000 Kz em inclusão financeira. | INDÍCIO (aplicação a online/referência não clara) | Marcas em Acção | 2025-09-22 | Modelar o custo bancário como 0-1% mais custo do facilitador. |
| Contas de moeda electrónica (Aviso 4/2025): 4 tipos; Tipo I e II só pessoas singulares para uso pessoal; III singulares para fins comerciais; IV pessoas colectivas. Prazo de regularização documental até 1 ano renovável. Limites do regime anterior (Instrutivo 05/2023): Tipo I saldo 50.000 Kz; II 600.000; III 6.000.000 (comerciais 19.200.000); IV sem limite. | INDÍCIO (imprensa; limites podem ter sido revistos pelo Aviso 4/2025) | https://pti.ao/bna-alivia-regras-para-contas-basicas-de-moeda-electronica/ (2025-09-08) ; https://pti.ao/bna-regulariza-utilizacao-de-contas-de-moeda-electronica/ (2023-06-01) | 2023-2025 | Pagamentos por carteira (Unitel Money/Afrimoney) têm tecto que pode bloquear tickets maiores. |
| Prazos de liquidação: Express diário (fecho do TPA virtual 08:00-08:30), referências às 20:00; depende do banco. | CONFIRMADO (AppyPay) / NÃO VERIFICADO (outros bancos e ProxyPay) | AppyPay FAQ | s/d | Não prometer ao comerciante "dinheiro na hora"; mostrar "liquidado pelo banco, normalmente no dia seguinte". |
| KWiK: instantâneo 24/7; para um pedido de pagamento KWiK (request-to-pay) iniciado por comerciante, não encontrei documentação. | CONFIRMADO (instantâneo) / NÃO VERIFICADO (API de comerciante) | allAfrica | 2026-01-29 | Não desenhar dependência de KWiK API; aceitar como "pagar por IBAN/QR com confirmação manual" apenas se houver forma de confirmação server-side. |

---

## 3. Regulação BNA

### 3.1 Diplomas reais (números verificados)

| Diploma | O que é | Estado | Fonte | Data |
|---|---|---|---|---|
| **Lei n.º 40/20, de 16 de Dezembro**, Lei do Sistema de Pagamentos de Angola | Lei-quadro. Revoga a Lei 5/05. Define serviços de pagamento (art. 4), exige autorização caso a caso do BNA para sociedades prestadoras de serviços de pagamento (arts. 11-13, prazo de decisão 3 meses), fundos dos utilizadores não são depósitos (art. 9), registo de agentes (art. 17), proíbe prestar serviços sem estar autorizado (art. 28). | CONFIRMADO (diploma; números de artigo de resumo, confirmar no texto) | https://lex.ao/docs/assembleia-nacional/2020/lei-n-o-40-20-de-16-de-dezembro/ | 2020-12-16 |
| **Aviso n.º 2/22, de 2 de Fevereiro** (publicado no DR I Série n.º 22, 2/2/2022, assinado em 21/1/2022) | Regulamenta a prestação de serviços de pagamento e o acesso à actividade de Sociedade Prestadora de Serviços de Pagamento. **Revoga o Aviso 5/14 e o Aviso 7/17** (art. 42). | CONFIRMADO (leitura directa do texto) | https://lex.ao/docs/banco-nacional-de-angola/2022/aviso-n-o-2-22-de-02-de-fevereiro/ | 2022-02-02 |
| Aviso n.º 7/2017 (12 Set) | Antigo regime de PSP / pagamentos móveis. **Revogado** pelo Aviso 2/22. Útil só como contexto (agentes de serviços de pagamento móveis, contas fiduciárias). | CONFIRMADO | idem; https://www.bfa.ao/media/1638/aviso-n%C2%BA-07_2017-12-de-setembro.pdf | 2017-09-12 |
| Aviso n.º 15/2020 (22 Jun 2020) | **Não é sobre pagamentos**: é o preçário de serviços e produtos financeiros e sua divulgação. Número sugerido na pergunta estava errado para este tema. | CONFIRMADO | https://www.fada.gov.ao/wp-content/uploads/2023/11/Aviso-15-2020-de-22-de-Junho-Sistema-Financeiro-Precario-de-Servicos-e-Produtos-Financeiros-e-Sua-Divulgacao.pdf (via busca) | 2020-06-22 |
| Aviso n.º 8/21 (5 Jul 2021) | Não é sobre pagamentos: requisitos prudenciais de fundos próprios de bancos. Descartar. | CONFIRMADO | https://lex.ao/docs/banco-nacional-de-angola/2021/aviso-n-o-8-21-de-05-de-julho/ | 2021-07-05 |
| Aviso n.º 15/2022 (6 Set 2022) | Permite que PSP autorizados disponibilizem TPA e ATM ao mercado. | INDÍCIO (imprensa) | https://pti.ao/bna-estabelece-novas-regras-para-prestadores-de-servicos-de-pagamento/ | 2022-09-06 |
| Aviso n.º 5/23 (29 Jun 2023) | Capital social mínimo das instituições financeiras não bancárias, incl. PSP. Valores anteriores (imprensa): principal 70 M Kz; standard classe 1 40 M; classe 2 25 M; iniciação de pagamento 25 M; informação sobre contas 20 M; remessa 70 M. Valores **actuais** após Aviso 5/23: NÃO VERIFICADO. | INDÍCIO | https://observador.pt/2023/07/05/banco-nacional-de-angola-adequa-capital-social-minimo-de-instituicoes-financeiras-nao-bancarias/ ; https://www.novojornal.co.ao/economia/detalhe/bna-estabelece-valor-minimo-do-capital-social-e-dos-fundos-proprios-das-instituicoes-financeiras-nao-bancarias--29452.html | 2023-07-05 / s/d | Ordem de grandeza do capital para PSP: dezenas de milhões de Kz (~10^4 a 10^5 USD a 913 Kz/USD), mais governação e AML. |
| Aviso n.º 2/24 (22 Mar 2024) | Branqueamento de capitais/financiamento do terrorismo para instituições financeiras sob supervisão do BNA: avaliação de risco, due diligence, reporte à UIF, compliance officer. | CONFIRMADO (resumo) | https://lex.ao/docs/banco-nacional-de-angola/2024/aviso-n-o-2-24-de-22-de-marco/ | 2024-03-22 |
| Aviso n.º 4/2025 | Abertura, movimentação e encerramento de contas de moeda electrónica. | INDÍCIO (imprensa) | https://pti.ao/bna-alivia-regras-para-contas-basicas-de-moeda-electronica/ | 2025-09-08 |
| Instrutivo n.º 02/2025 (13 Ago 2025) | Limites de valor em operações no sistema de pagamentos. | INDÍCIO | ver secção 2 | 2025-08-13 |
| Aviso n.º 03/2026 | Governação societária e controlo interno; inclui PSP com activos >= 4.000 M Kz durante 3 anos consecutivos, com 12 meses para adaptação. Não relevante para nós, relevante para parceiros PSP. | INDÍCIO | https://www.otelegrama.ao/opiniao/bna-reforca-governacao-e-controlo-interno-o-que-muda-com-o-novo-aviso-03-2026/ ; PLMJ | 2026-02 | - |
| Alerta do BNA (9 Out 2020): carteiras de moeda electrónica integradas em aplicações por empresas que não são sociedades prestadoras de serviços de pagamento carecem de licença. | CONFIRMADO (imprensa; base legal Lei 12/15 art. 7(g) e Lei 5/05) | https://www.expansao.co.ao/expansao-mercados/detalhe/bna-alerta-que-carteiras-de-moeda-electronica-carecem-de-licenca--55013.html | 2020-10-09 | Precedente de que o BNA vigia apps com carteiras. |
| Lei n.º 14/21 (19 Mai 2021), Regime Geral das Instituições Financeiras | Sociedades de pagamento são instituições financeiras não bancárias e não podem aceitar depósitos (Aviso 2/22 art. 6). | CONFIRMADO | citada no Aviso 2/22 | 2021-05-19 |

### 3.2 Leitura do Aviso 2/22 para a nossa arquitectura

(Leitura directa do texto; interpretação marcada como tal.)

| Afirmação | Estado | Fonte | Implicação para o desenho |
|---|---|---|---|
| Art. 4: serviços de pagamento incluem (a-b) depósito/levantamento em conta de pagamento, (c) execução de operações de pagamento (transferências, débitos directos, cartões), (e) emissão de instrumentos e/ou **aquisição** de operações, (f) moeda electrónica, (g) remessa, (h) **iniciação de pagamento**, (i) informação sobre contas, (j) **sub-adquirente**. | CONFIRMADO | Aviso 2/22 art. 4 | A actividade regulada é definida por função, não pelo rótulo "gateway". |
| "Sub-adquirente" = empresa que intermedeia pagamentos entre comerciante e adquirente, transmitindo dados da transacção e/ou **liquidando valores junto dos comerciantes**. | CONFIRMADO | art. 3(aa) | Se a plataforma receber o dinheiro das vendas e depois o repassar ao comerciante, aproxima-se de sub-adquirente: regulado. |
| Art. 5 (exclusividade): só podem prestar serviços de pagamento bancos, instituições financeiras não bancárias com objecto adequado (incl. Sociedades Prestadoras de Serviços de Pagamento), filiais/sucursais, serviço postal, Estado/autarquias. Art. 18: exercício carece de autorização prévia do BNA. Art. 6: PSP não podem aceitar depósitos. | CONFIRMADO | arts. 5, 6, 18 | Uma plataforma de software sem licença não pode prestar estes serviços, directamente ou "em nome de". |
| **Exclusão técnica** (art. 4, lista de excepções, alínea j): não são serviços de pagamento os "serviços prestados por prestadores de serviços técnicos, que apoiam a prestação de serviços de pagamento **sem nunca entrarem na posse dos fundos a transferir**", incluindo processamento e armazenamento de dados, autenticação, redes TIC, terminais; **com excepção dos serviços de iniciação de pagamentos e de informação sobre contas**. | CONFIRMADO | texto lex.ao | É a base legal do modelo "facilitador técnico" (AppyPay, ProxyPay): orquestrar, notificar e conciliar sem posse dos fundos. Atenção à ressalva de iniciação de pagamento. |
| Exclusão de "agente comercial autorizado por contrato a negociar ou concluir a venda exclusivamente em nome do ordenante ou do beneficiário" (alínea b). | CONFIRMADO | idem | Não é cobertura para uma plataforma multi-comerciante que cobra. NÃO usar como argumento sem parecer. |
| Art. 21: "é proibida a subcontratação de serviços operacionais para a prestação de serviços de pagamento." | CONFIRMADO | texto | Impede uma estrutura em que a plataforma opera pagamentos "ao abrigo" da licença de um PSP parceiro como subcontratada operacional. Parceria tem de ser técnica/comercial, com o fluxo de fundos nas mãos do parceiro licenciado. (Interpretação.) |
| Art. 28 (protecção de fundos: contas fiduciárias, segregação, reconciliação diária) aplica-se a **emitentes de moeda electrónica**. Art. 27: património separado. | CONFIRMADO | arts. 25-28 | Não há, no texto lido, figura geral de "escrow" para marketplace fora das regras de PSP/moeda electrónica. Escrow/retenção: NÃO VERIFICADO como regime específico. |
| Definição de iniciação de pagamento: serviço que inicia uma ordem de pagamento a pedido do utilizador relativamente a uma conta detida noutro PSP. Prestador de iniciação precisa de autorização (categoria própria, capital 25 M Kz na versão anterior à Aviso 5/23). | CONFIRMADO (definição, art. 3(x)/(t)); INDÍCIO (capital) | Aviso 2/22; Novo Jornal | Se o bot acciona a transferência/débito a partir da conta bancária do cliente (ex. via API de banco), pode ser "iniciação". Se apenas apresenta referência/QR e é o cliente quem paga no seu app, a leitura mais natural é que não. (Interpretação, pedir parecer.) |

### 3.3 O que exige licença: três desenhos

| Desenho | Fluxo de fundos | Leitura (interpretação sujeita a parecer) | Estado | Fonte |
|---|---|---|---|---|
| **A. Facilitador técnico**: plataforma gera referência/pedido Express com as credenciais do **comerciante** (via AppyPay/ProxyPay), recebe webhook, concilia. Liquidação directa na conta do comerciante. | Plataforma nunca toca no dinheiro. | Enquadra-se na exclusão técnica (art. 4, alínea j) e é o modelo contratual dos facilitadores existentes. Sem licença BNA própria. | CONFIRMADO (texto do Aviso e termos AppyPay); conclusão jurídica = INDÍCIO até parecer | Aviso 2/22; termos AppyPay cl. 1.5 |
| **B. Plataforma como "comerciante" único** (a plataforma tem as credenciais EMIS/entidade e recebe tudo), repassando ao PME. | Fundos de terceiros passam pela conta da plataforma. | Provável sub-adquirente / execução de pagamentos para terceiros: exige autorização BNA, segregação, KYC/AML. Alto risco regulatório. | INDÍCIO (leitura do art. 3(aa)) | Aviso 2/22 |
| **C. Payouts a terceiros** (estafetas, revendedores, comissões) pagos **pela plataforma**. | Plataforma executa transferências. | Execução de operações de pagamento / remessa: regulado. Alternativas: (i) o comerciante paga os seus estafetas a partir da sua conta (plataforma só gera ficheiro/lista); (ii) parceiro PSP/banco licenciado executa o payout com a conta do comerciante, via API do parceiro; (iii) plataforma obtém licença de iniciação de pagamento (se aplicável). | INDÍCIO | Aviso 2/22 arts. 4-5 |
| **D. Escrow / retenção até confirmação de entrega**. | Fundos retidos pela plataforma. | Equivale a deter fundos de utilizadores: PSP/instituição de moeda electrónica com conta fiduciária (Aviso 2/22 arts. 25-28). Não fazer sem licença ou sem banco/PSP parceiro a deter os fundos em nome do cliente. | INDÍCIO | Aviso 2/22; Lei 40/20 art. 9 |
| **E. Agentes** (Aviso 7/17 admitia agentes de PSP): agentes só actuam para o PSP que os registou; art. 17 da Lei 40/20 exige registo no BNA. | - | Uma startup não é "agente" apenas por ter contrato comercial com um PSP, sem registo. NÃO VERIFICADO o regime actual de agentes após o Aviso 2/22 (o Aviso 2/22 não define "agente" de forma explícita, segundo o resumo). | NÃO VERIFICADO | Lei 40/20 (resumo) |

### 3.4 Sanções e ambiguidade

| Afirmação | Estado | Fonte | Implicação |
|---|---|---|---|
| Prestar serviços de pagamento sem autorização é proibido e sancionável (Lei 40/20 art. 28 e capítulos de contravenções). Valor das coimas: NÃO VERIFICADO. | CONFIRMADO (proibição, resumo) / NÃO VERIFICADO (montantes) | Lei 40/20 | Risco real; o BNA já emitiu avisos públicos contra entidades não habilitadas (ex. "Kwanza Card", "Investimentoao"). |
| O BNA já alertou publicamente contra entidades não habilitadas (Kwanza Card, Investimentoao) e revogou licenças de PSP. | INDÍCIO | https://forbesafricalusofona.com/?p=37620 ; https://www.verangola.net/va/pt/042023/BancaSeguros/35201/ ; https://economiaemercado.com/artigo/bna-revoga-licenca-de-prestadores-de-servicos-de-pagamento | 2023 | Fiscalização activa. |
| Há ambiguidade doutrinal sobre quais entidades precisam de licença de "instituição de pagamento" e não existe sandbox regulatório de pagamentos. | INDÍCIO (artigo de escritório de advogados; cita Aviso "26/17", número que não confirmei, usar só a conclusão geral) | https://revista.cazosadvogados.com/en/cazos/do-levantamento-ao-clique-o-novo-rumo-dos-pagamentos-em-angola | 2025 | Pedir interpretação escrita ao BNA (Departamento de Sistema de Pagamentos). |

---

## 4. Fraude e confirmação server-side

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| Comprovativos de transferência falsos são fraude documentada contra comerciantes: faz-se uma transferência real de montante ínfimo (0,001 a 20 Kz) e edita-se o comprovativo; o burlão pede troco por "excesso". A Polícia (SIC) confirmou detenção de um engenheiro informático que manipulava comprovativos Multicaixa; perdas de 500.000 Kz a milhões. | CONFIRMADO (imprensa, múltiplos casos) | https://www.novojornal.co.ao/sociedade/detalhe/a-burla-da-manipulacao-do-comprovativo-de-transferencia-bancaria---como-os-comerciantes-estao-a-ser-roubados-31873.html ; https://www.angola24horas.com/sociedade/item/29088 | 2023-02-15 | **Nunca aceitar imagem/PDF de comprovativo como prova de pagamento** no WhatsApp. O estado "pago" só muda por evento do facilitador (webhook assinado ou consulta), com valor e referência a coincidir. |
| EMIS alerta repetidamente para phishing em Multicaixa Express (páginas falsas, apps falsas, SMS/WhatsApp, chamadas); linha de apoio 923 165 165; nenhuma entidade pede PIN/códigos por telefone, SMS ou redes. | CONFIRMADO | https://verifica.ao/burlas-envolvendo-multicaixa-express-estao-a-aumentar-desinformacao-e-engano-entre-os-motivos/ ; https://expansao.co.ao/empresas/detalhe/emis-lanca-alerta-sobre-casos-de-burlas-no-multicaixa-express-58586.html | 2025-05-31 | O bot nunca deve pedir PIN nem códigos; o pedido de pagamento Express chega pela app do banco, não por link no WhatsApp. Instruir o cliente a ignorar links alegadamente da "EMIS" enviados por terceiros. Incluir aviso fixo nas mensagens de cobrança. |
| Fraudes com cartão Multicaixa aumentaram (99,9% num ano; 251 fraudes/mês em 2022). | INDÍCIO | Forbes África Lusófona; Expansão | 2022-2023 | Dados antigos; apenas contexto. |
| ProxyPay: webhook com HMAC-SHA256 + fila de pagamentos por reconhecer (`GET/DELETE /payments`). | CONFIRMADO | docs RPS v2 | s/d | Melhor garantia disponível: validar assinatura + reconciliação periódica. |
| ProxyPay OPG: callback por POST; `Idempotency-Key`; consulta de transacção. | CONFIRMADO (callback, idempotência) / NÃO VERIFICADO (assinatura) | docs OPG | s/d | Tratar callback como "dica" e confirmar por consulta. |
| AppyPay: notificações em tempo real por email/portal/API; webhook obrigatório em REF. Assinatura: NÃO VERIFICADO. | INDÍCIO | AppyPay; SDK bit-ao | 2025 | Idem. |
| EMIS directo: callback sem assinatura e sem consulta de estado (segundo código de terceiros). | INDÍCIO [BLOG/código] | pkg.go.dev | s/d | Validar POSID/valor/moeda e fazer reconciliação com o extracto do banco. |
| Pagamento directo por IBAN/KWiK/transferência ao comerciante, sem facilitador: não há evento server-side padronizado. | INDÍCIO (lógica da arquitectura, não fonte directa) | - | - | Só aceitar como "confirmação manual pelo comerciante" com aviso de risco, ou não suportar. |
| Referências não admitem devolução (rail seguro para o comerciante); Express permite reembolso dentro da janela do TPA virtual. | CONFIRMADO | AppyPay | s/d | Sem risco de chargeback; risco passa a ser fraude de identidade/conta do comerciante e disputas de entrega. |

---

## 5. Moeda e câmbio (kwanza)

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| USD/AOA ~913,0 a 30 Set 2026, estável desde meados de Setembro (913,00 de 14 a 30 Set; 912,84-912,87 antes); variação de ano a data +0,08%. | INDÍCIO (agregador de dados) | https://countryeconomy.com/currencies/angola | 2026-09-30 | Taxa nominal praticamente fixa. |
| BNI, 8 Out 2026: compra 913 Kz/USD, venda 981,475 Kz/USD. | CONFIRMADO (cotação de banco, leitura directa) | https://www.bni.ao/pt/taxas | 2026-10-08 | Spread de retalho de ~7%: custos em USD pagos via banco custam mais do que a taxa de referência. |
| Taxa de referência BNA ~914,6 (snippet de busca); histórico: BNA manteve 912 durante 5 meses até Maio 2025, quando mexeu para 911,955 (variação de 0,005%). | INDÍCIO | https://angolax.com/fx/bna-rates/ (não aberto) ; https://www.expansao.co.ao/economia/detalhe/bna-decide-mexer-no-cambio-5-meses-depois-de-estar-parado-nos-912-kwanza-por-dolar-65289.html | 2025-05-08 | Regime de facto muito controlado. |
| Regime descrito como "managed float" com capacidade de intervenção; reservas 14,93 mil M USD (6,2 meses de importações); superávit comercial de 10,56 mil M USD até Junho 2026; sem aceleração de desvalorização. | INDÍCIO | https://negociosemexame.ao/financas/provavel-percurso-do-kwanza-em-2026-apos-medidas-do-bna/ | 2026-07-16 | Cenário base: estabilidade; mas manter cláusula de revisão. |
| Taxa directora do BNA baixada de 17% para 15,75%; inflação homóloga 10,11% (Jun 2026), previsão BNA de 8,6% para fim de 2026. | INDÍCIO | negociosemexame.ao; https://www.verangola.net/va/pt/072026/ (busca) ; tradingeconomics | 2026-07 | Inflação ainda de dois dígitos: preços em Kz perdem valor real face a custos em USD mesmo com câmbio fixo. |
| Histórico: desvalorização de cerca de 40% entre Maio e Junho de 2023 (mínimo de ~825 Kz/USD citado). | INDÍCIO [BLOG] | resultado de busca (angola2050.com) | 2023 | O risco de salto existe: não assumir paridade eterna. |
| Disponibilidade de USD para pagar serviços no estrangeiro (Meta/WhatsApp Business Platform, cloud, LLM) a partir de conta em Kz e via que cartão. | NÃO VERIFICADO | - | - | Se a entidade operadora for angolana, depende de operações cambiais via banco comercial (Aviso 3/2023 sobre pessoas singulares aparece em busca; regime para empresas não verificado). Alternativa: entidade/conta no estrangeiro a pagar os custos USD. |
| Impostos aplicáveis a pagamentos de serviços a prestadores não residentes (retenção, imposto de selo). | NÃO VERIFICADO | - | - | Pergunta a contabilista fiscal. |

Implicações para custos em USD: o custo variável da plataforma (mensagens WhatsApp, IA, cloud) é em USD e a receita das PMEs é em Kz. Com câmbio praticamente estável a 913, podem fixar-se tabelas em Kz hoje, mas incluir (i) cláusula de revisão semestral indexada à taxa de referência BNA, (ii) spread bancário ~7% no custo real, (iii) cenário de choque de +30-40% no stress-test do preço.

---

## 6. Factura electrónica AGT

### 6.1 Calendário e base legal

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| Base legal: **Decreto Presidencial n.º 71/25, de 20 de Março** (Regime Jurídico das Facturas). Art. 16: obrigados à facturação electrónica os contribuintes do regime geral e do regime simplificado do IVA; regime de exclusão: voluntário a pedido da AGT. Art. 17: software "validado ou disponibilizado" pela AGT. Art. 25: comunicação por transmissão electrónica de dados em formato SAF-T. Art. 37: fases. | CONFIRMADO (resumo do texto em angolex; confirmar numeração) | https://angolex.com/paginas/decreto-presidencial/regime-juridico-das-facturas-71a-25a.html ; https://lex.ao/docs/presidente-da-republica/2025/decreto-presidencial-n-o-71-25-de-20-de-marco/ | 2025-03-20 | Quem emite a factura é sempre o contribuinte, com software certificado. |
| **Decreto Executivo n.º 683/25, de 22 de Agosto**: estrutura de dados do software e modelo da facturação electrónica, especificações técnicas. | CONFIRMADO (múltiplas fontes) | https://www.ey.com/pt_ao/technical/tax-alerts/estrutura-de-dados-do-software-e-do-modelo-de-faturacao-electronica ; https://www.lexlink.eu/conteudo/geral/ia-serie/4106155/decreto-executivo-no-68325/14793/por-tema | 2025-08-22 | É a especificação a pedir à AGT/software house para qualquer integração. |
| Decreto Presidencial n.º 312/18 (21 Dez 2018): regime de submissão electrónica de elementos contabilísticos e requisitos dos sistemas de processamento. | INDÍCIO | https://lex.ao/docs/presidente-da-republica/2018/decreto-presidencial-n-o-312-18-de-21-de-dezembro/ (busca) | 2018-12-21 | Contexto histórico. |
| Calendário inicial: obrigatório a partir de 22 Set 2025 → adiado para 1 Out 2025 com fase transitória sem coimas até 31 Dez 2025. | CONFIRMADO (imprensa) | https://pti.ao/agt-apresenta-lista-de-softwares-certificados-para-emissao-de-factura-electronica/ ; cegid.com/ao | 2025-09/10 | - |
| **Fase 1: 1 de Janeiro de 2026**: grandes contribuintes (Repartições Fiscais de Grandes Contribuintes, 633 segundo a AGT em Abril 2026) e fornecedores do Estado. | CONFIRMADO (várias fontes, incluindo declarações da AGT) | https://lidermagazine.ao/agt-endurece-tom-sobre-facturacao-electronica-o-prazo-nao-sera-prorrogado/ (2026-04-15); https://www.giranoticias.com/economia/2026/01/27216-agt-aponta-medidas-para-o-sucesso-da-facturacao-eletronica.html (2026-01-04); https://diariodosnegocios.com/facturacao-electronica-angola-desafios-implementacao-2026/ (2026-02-25) | 2026 | Clientes PME que forneçam ao Estado ou a grandes contribuintes já têm de emitir. |
| **Fase 2: 1 de Janeiro de 2027**: restantes contribuintes dos regimes **geral e simplificado do IVA**. A AGT afirmou em Abril 2026 que "o prazo não será prorrogado". | INDÍCIO forte (imprensa de 2026 + declaração do presidente da AGT; sem diploma datado de 2026 lido) | Líder Magazine 2026-04-15; Giranotícias 2026-01-04; Cegid (actualizado 2026-08-19) https://www.cegid.com/ao/blog/obrigatoriedade-faturacao-eletronica-angola/ | 2026 | **A maioria das PMEs-alvo passa a ser obrigada em ~12 semanas.** O produto tem de ser "pronto para factura" no lançamento. |
| **Conflito de fontes**: algumas fontes (EY Abril 2025, Expansão) dão **21 de Setembro de 2026** como início da fase 2 (12 meses após a entrada em vigor original). Fontes posteriores ao adiamento dão 1 Jan 2027. Um blog de 15 Set 2026 ainda diz 21 Set 2026. | INDÍCIO (conflito) | EY https://www.ey.com/pt_ao/technical/tax-alerts/novo-regime-juridico-das-facturas ; beancount.io [BLOG] 2026-09-15 | 2025-04 / 2026-09 | A data de 21 Set 2026 já passou: se estivesse vigente, as PMEs de regime geral/simplificado já seriam obrigadas hoje. **Confirmar com a AGT por escrito qual é a data em vigor.** Plano prudente: tratar 1 Jan 2027 como a data oficial, e as PMEs como "já em risco". |
| Limiar de 25 milhões de Kz: o regime simplificado do IVA aplica-se com volume de negócios anterior >= 25 M e < 350 M Kz (7% sobre valor recebido); abaixo = regime de exclusão; acima = regime geral (14%). Também aparece uma notícia que fala em obrigação para facturas >= 25 M Kz. | INDÍCIO (consultoras; blog) | https://www.wisedat.pt/regimes-do-iva-em-angola/ (via busca); PwC (via busca); Primavera | 2023-2026 | Dividir a base de clientes: exclusão (< 25 M) provavelmente fora da obrigação, mas pode emitir pelo Portal do Contribuinte. |
| Contribuintes em regime de exclusão e pessoas singulares podem emitir pelo Portal do Contribuinte (máx. 300 documentos por ano). | INDÍCIO | resultado de busca (agt/minfin) | 2026 | Opção para micro-negócios, mas sem API. |
| Exigências do software: certificado/validado pela AGT, comunicação em tempo real com a AGT, assinatura digital, código de validação (ETD), geração de SAF-T, registo de cada estabelecimento junto da AGT. | CONFIRMADO (AGT/imprensa; sisgesc blog para ETD) | Giranotícias; Líder Magazine; sisgesc.net [BLOG] | 2026 | Plataforma que emita facturas por conta do PME, sem ser software certificado, não é válida. |
| Problemas de arranque: validação de factura chega a ~30 min; custos de software de 500 mil a 1,5 M Kz (pequenas) e ~10 M Kz (grandes); pedidos de prorrogação pelas associações. | INDÍCIO | Diário dos Negócios 2026-02-25 | 2026-02-25 | Latência e falhas de rede: o fluxo de WhatsApp não deve bloquear à espera da AGT; emitir de forma assíncrona. |
| Coimas: sem factura 7% (15% reincidência) por factura; SAF-T em falta 7%; emissão tardia > 5 dias úteis 0,2%. | INDÍCIO [BLOG] | beancount.io | 2026-09-15 | Confirmar nos artigos de coimas do DP 71/25. |

### 6.2 Softwares certificados com API

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| A AGT divulgou lista com 43 certificados em Dez 2025; a lista oficial actual não foi obtida. | CONFIRMADO (existência, imprensa) / NÃO VERIFICADO (lista actual) | https://pti.ao/agt-apresenta-lista-de-softwares-certificados-para-emissao-de-factura-electronica/ | 2025-12 | Obter e validar o n.º de certificado de cada parceiro (formato `FE/n/AGT/ano`). |
| **Vero** (vero.ao): declara certificado `FE/271/AGT/2026` (23 Jun 2026), envio à AGT em tempo real. API REST com `POST /v1/organisations/{ORG_ID}/invoices`, `customers/ensure`, `products`, proformas, notas de crédito/débito, guias; Bearer `vero_live_sk_...`/`vero_test_sk_...`; sandbox que **não submete à AGT**; webhooks `invoice.issued`, `invoice.cancelled` assinados com `X-Vero-Signature` HMAC-SHA256; idempotência (`idempotencyKey`); **modelo multi-tenant**: `organisations.create()` regista empresas e emite em nome delas; SDK Node/TypeScript; freemium. | INDÍCIO (declaração do fornecedor; certificado não validado na lista AGT) | https://vero.ao/ ; https://vero.ao/developers | 2026-10-08 | É o melhor encaixe actual para "plataforma emite por conta do PME" (multi-tenant + idempotência + webhooks). Validar certificado, preço, responsabilidade fiscal e continuidade antes de depender. |
| **CacimboERP / Electronic Invoice Cacimbo**: declara `FE/6/AGT/2025`; "API REST"; integração em ~2 h; preços por escalão de facturação anual (Independentes 50.000 Kz inicial + 50.000 Kz/ano; Micro 250.000/125.000; Pequena 500.000/250.000; Média 1.000.000/500.000; Grande 2.000.000/1.000.000). Documentação da API: não encontrada. | INDÍCIO | https://feinfo.cacimboweb.com/ | 2026-10-08 | Preço em licença anual por contribuinte: modelo diferente do multi-tenant da Vero. |
| **SIGESC / SISGESC**: plataforma de gestão com facturação certificada `FE/323/AGT/2026`, POS, stock. Existência de API pública: NÃO VERIFICADO. | INDÍCIO | https://sisgesc.net/blog/posts/facturacao-electronica-prazos-requisitos-rjfde [BLOG do fornecedor] | 2026-08-06 | - |
| **XDFE** `FE/150/AGT/2026`; **Cegid (Primavera, PHC, Vendus)** e **Odoo (localização angolana)**, **SAP**, **ISSXXI**, **EDICOM** (provedor certificado) aparecem referidos como certificados ou "preparados". API de integração para terceiros: NÃO VERIFICADO. | INDÍCIO | busca; cegid.com/ao; xdfe.info | 2026 | - |
| **Gestwin**, **Moloni Angola**: não encontrei fonte sobre certificação ou API. | NÃO VERIFICADO | - | - | Perguntar. |
| Possibilidade de emitir factura por API a partir de um terceiro (a plataforma) em nome do PME: tecnicamente demonstrada pela Vero (multi-tenant) e anunciada pela MoMenu (factura SAF-T com pagamento). O PME continua a ser o emissor; o software certificado é o da Vero/Cacimbo/etc. | INDÍCIO | vero.ao/developers ; skills.cat MoMenu | 2026 | Evita a plataforma ter de se certificar como software. Se a plataforma quiser emitir com o seu próprio motor, tem de ser certificada pela AGT (processo, custos, prazo: NÃO VERIFICADO). |

---

## 7. IVA e regimes relevantes para a assinatura SaaS

| Afirmação | Estado | Fonte(s) | Data | Implicação para o desenho |
|---|---|---|---|---|
| IVA: taxa geral 14%; regime simplificado 7% sobre o valor efectivamente recebido; regimes: geral, simplificado (25 M <= volume < 350 M Kz), exclusão (< 25 M Kz). | INDÍCIO (consultoras, via busca; Código do IVA e Lei 14/23 não lidos) | https://www.wisedat.pt/regimes-do-iva-em-angola/ ; https://www.pwc.com/ao/pt/servicos/tax/iva-regime-juridico-das-facturas.html ; https://lex.ao/docs/assembleia-nacional/2023/lei-n-o-14-23-de-28-de-dezembro/ | 2023-2026 | Preço da assinatura: decidir se é "IVA incluído" ou "mais IVA". Se a nossa entidade for do regime de exclusão (< 25 M Kz), pode não cobrar IVA, mas o PME-cliente em regime geral não deduz. |
| Serviços digitais/SaaS estão sujeitos a 14% de IVA; desde 1 Out 2019 prestadores não residentes em B2C têm de registar-se e cobrar IVA independentemente do valor. | INDÍCIO [BLOG de fornecedor de pagamentos] | https://payproglobal.com/pt/imposto-sobre-vendas-de-saas/angola/ | s/d | Se a entidade facturadora for estrangeira: tratamento B2B (autoliquidação) NÃO VERIFICADO. |
| OGE 2026 manteve em geral as opções fiscais; sem alteração material identificada para SaaS. | INDÍCIO | EY / Abreu: https://www.ey.com/content/dam/ey-unified-site/ey-com/pt-ao/services/tax/documents/tax-alert-especial-lei-orcamento-geral-do-estado-2026.pdf | 2026 | Rever com contabilista. |
| A nossa própria assinatura SaaS tem de ser facturada com software AGT-certificado (se a nossa entidade estiver no regime geral/simplificado), em prazo conforme a fase aplicável. Cobrança da assinatura por referência/Express/débito directo gera recibo; DP 71/25 art. 6 exige recibo em pagamentos parciais/totais (salvo factura-recibo). | INDÍCIO | resumo angolex | 2025 | Emitir factura-recibo automaticamente após cada pagamento confirmado. |
| Cobrança recorrente via Débito Directo (SDD) exige IEC da entidade credora, mandato (ADC) válido por defeito 1 ano, limites de valor/tempo definidos pelo devedor; reembolso do devedor em 60 dias e rectificação em 395 dias. | CONFIRMADO | FAQ AppyPay; docs DDS ProxyPay | s/d | Subscrições recorrentes são possíveis só com IEC e com banco do comerciante/plataforma. Alternativa: referência "carregamento" mensal. |

---

## 8. Bloqueios e caminho crítico

Ordem sugerida (as dependências externas são longas e fora do controlo da equipa):

1. **Decisão de desenho A (facilitador técnico, sem posse de fundos)** como arquitectura padrão. Desenhos B, C, D (receber para depois repassar, payouts, escrow) ficam fora do MVP até haver parecer jurídico e parceiro licenciado. Sem isto, tudo o resto (contratos, T&C, código) está a ser desenhado sobre premissa instável.
2. **Onboarding bancário do comerciante** é o bloqueio principal: cada PME precisa de banco de apoio + contrato EMIS (POSID/supervisor card, Entidade, IEC) e contrato assinado em papel com o facilitador. Prazo: NÃO VERIFICADO, provavelmente semanas e específico por banco. Mitigação: o produto deve funcionar desde o dia 1 em **modo sem gateway** (catálogo, encomenda, confirmação manual com avisos), e activar gateway por comerciante quando as credenciais chegarem.
3. **Prazo AGT**: se for 1 Jan 2027, restam ~12 semanas. O produto precisa de uma integração de facturação (Vero/Cacimbo/outro) em modelo "factura-recibo após pagamento confirmado", e de um fluxo assíncrono porque a validação da AGT pode demorar. Confirmar por escrito a data em vigor.
4. **Contratos de integração**: ProxyPay (preço NÃO VERIFICADO; docs públicas e sandbox disponíveis, pode começar-se a desenvolver já), AppyPay (acesso completo à Stoplight, assinatura do webhook, sandbox).
5. **Parceria PSP** (PayPay ou outro com licença) apenas se payouts/escrow forem requisito comercial: sujeito a parecer sobre art. 21 (proibição de subcontratar serviços operacionais).
6. **Custos USD**: definir quem paga Meta/cloud/IA (entidade com conta no estrangeiro vs. entidade angolana) antes de fixar preços em Kz.

Riscos já visíveis:

- Webhook EMIS directo não assinado: usar facilitador com polling/assinatura ou aceitar reconciliação de extracto.
- Facilitadores limitam a responsabilidade ao valor de um mês de serviço: a nossa plataforma não deve prometer garantias que não pode repassar.
- Referências não têm reembolso: disputa de entrega tratada fora do gateway.
- Falhas de rede e latência AGT: filas, retries, estado "factura pendente".
- Mudança regulatória: o BNA está a actualizar o quadro (Avisos 4/2025, 3/2026); revisão trimestral.

---

## 9. Perguntas que só o banco / facilitador / BNA / AGT pode responder por escrito

**Banco de apoio (BAI, BFA, BIC, Standard Bank, etc.)**
1. Quais os documentos, custos e prazo (dias úteis) para obter POSID/supervisor card (GPO), Entidade (referências) e IEC (débito directo)? Exigem alvará, certidão comercial, NIF, contabilidade? Aceitam empresário em nome individual?
2. Qual a comissão do banco por GPO Express, referência e débito directo? Aplica-se o tecto de 1% / 12.000 Kz do Instrutivo 02/2025?
3. A que horas e em que dia (D+0/D+1/D+2) liquidam GPO e referências? Há reservas ou retenções?
4. Qual o limite por transacção e diário por comerciante em GPO e referências?
5. Podem delegar a mesma Entidade/POSID a um facilitador técnico (ProxyPay/AppyPay) sem passar o dinheiro pela conta do facilitador?
6. Têm API própria de extracto/saldos/confirmação (conciliação), e API de transferência em lote para o comerciante pagar estafetas a partir da sua conta?

**ProxyPay / TimeBoxed**
7. Preçário completo (mensalidade, por transacção, mínimo), SLAs, prazos de onboarding, contratos-tipo.
8. O callback do OPG é assinado? Qual o esquema de retries e há fila de pagamentos também para OPG? Rate limits?
9. Uma plataforma multi-comerciante pode ter uma conta-mestre com sub-comerciantes (cada um com a sua Entidade/POSID) e uma só chave de API?
10. Rotação de chaves (a chave HMAC é a API key).

**AppyPay**
11. Documentação Stoplight completa e OpenAPI; esquema de autenticação actual (auth.appypay.co.ao vs Azure AD); sandbox oficial e dados de teste.
12. Assinatura dos webhooks, retries, idempotência além de `merchantTransactionId` (1-15 alfanum.).
13. Certificado EMIS (carta/data/âmbito) e confirmação de que não é necessária licença BNA para a AppyPay.
14. Uso de "FTBAI/transferência de fundos": para que serve e quem pode usar?
15. Existe modelo "partner/ISV" com onboarding de comerciantes via API?

**EMIS**
16. Condições para integração directa GPO (token de comerciante, certificação de integradores), documentação oficial, assinatura de callbacks e existência de consulta de estado.
17. Limite por operação de pagamento Express a comerciante e se há "request-to-pay" KWiK para comerciantes.

**PayPay / Pay4All / outros PSP**
18. Existe API de comerciante para QR KWiK e confirmação server-side? Existe API de payouts por IBAN? Em nome de quem (conta do comerciante ou da plataforma)? Aceitam parceria sem a plataforma deter fundos?

**BNA (Departamento de Sistema de Pagamentos)**, pedir resposta escrita
19. Uma plataforma de software que gera pedidos de pagamento com as credenciais de cada comerciante, e cuja liquidação é feita directamente pela EMIS para a conta do comerciante, está excluída por força da alínea j) do art. 4 do Aviso 2/22 (prestador técnico sem posse dos fundos)? E se também mostrar uma referência/QR sem iniciar a transferência?
20. Quando o bot acciona um pagamento a partir da conta do cliente (iniciação), qual a classificação e licença necessária?
21. Payouts a estafetas/revendedores executados por parceiro licenciado, mas instruídos pela plataforma: exige licença à plataforma?
22. Retenção de fundos até confirmação de entrega (escrow): só através de PSP/instituição de moeda electrónica com conta fiduciária?
23. Valores actuais de capital social e fundos próprios das categorias do art. 18 após o Aviso 5/23.
24. Regime actual de agentes de PSP (registo no BNA, art. 17 da Lei 40/20) após a revogação do Aviso 7/17.
25. Existência de sandbox regulatório ou procedimento de consulta prévia.

**AGT**
26. Data de entrada em vigor da obrigação para os regimes geral e simplificado (21 Set 2026 ou 1 Jan 2027) e texto do diploma que fixa a data.
27. Lista oficial actual de softwares certificados e se um software certificado pode ser chamado por API por terceiros em nome de várias empresas (multi-tenant).
28. Processo, custo e prazo para certificar software próprio; documento técnico do Decreto Executivo 683/25 (esquemas, endpoints de comunicação em tempo real).
29. Obrigação de registo de estabelecimentos; tratamento de recibos para pagamentos online; regime de exclusão: confirmar limite de 300 documentos/ano no Portal.

**Contabilista fiscal**
30. IVA sobre a assinatura SaaS (nosso regime, B2B/B2C), retenções ou impostos sobre pagamentos a fornecedores estrangeiros (Meta, cloud, IA), e câmbio para pagar em USD.

---

## 10. Lista de fontes principais

Primárias/oficiais:
- Aviso n.º 2/22 BNA: https://lex.ao/docs/banco-nacional-de-angola/2022/aviso-n-o-2-22-de-02-de-fevereiro/ (texto integral lido)
- Lei n.º 40/20: https://lex.ao/docs/assembleia-nacional/2020/lei-n-o-40-20-de-16-de-dezembro/ (resumo)
- Aviso n.º 7/17 (revogado): https://www.bfa.ao/media/1638/aviso-n%C2%BA-07_2017-12-de-setembro.pdf (texto integral lido)
- Aviso n.º 2/24: https://lex.ao/docs/banco-nacional-de-angola/2024/aviso-n-o-2-24-de-22-de-marco/
- ProxyPay docs: https://developer.proxypay.co.ao/rps/v2/ , /opg/v1/ , /dds/v1/
- AppyPay: https://appypay.co.ao/ , /faqs , /termos-de-utilizacao , /precos-1-2 ; Stoplight https://appypay.stoplight.io/docs/appypay-payment-gateway
- Paybyrd: https://docs.paybyrd.com/accept-payments/bank-transfers/multicaixa-express
- BNI cotações: https://www.bni.ao/pt/taxas
- Vero: https://vero.ao/ e https://vero.ao/developers (fornecedor)
- CacimboERP: https://feinfo.cacimboweb.com/ (fornecedor)

Imprensa e consultoras (INDÍCIO): Expansão, Novo Jornal, PTI, Ver Angola, Forbes África Lusófona, Líder Magazine, Diário dos Negócios, Giranotícias, Negócios em Exame, allAfrica, EY Angola, Cegid, Cazos Advogados, PLMJ.

Blogs/código de terceiros [BLOG]: github.com/Gomes19/appypay-sdk, github.com/bit-ao/appy-pay-php, pkg.go.dev/github.com/spolly-ao/fllex (emis, momenu, proxypay), sisgesc.net, beancount.io, payproglobal.com.
