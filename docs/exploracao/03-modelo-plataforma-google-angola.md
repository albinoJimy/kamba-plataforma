# Modelo de Plataforma estilo Google para Angola: atenção gratuita, intenção paga

Continuação de `01-modelo-negocios-angola-ai-first.md` e `02-enquadramento-plataforma-angola.md`.
Objetivo: adaptar o modelo Google (utilizadores grátis + anunciantes pagos + ecossistema fechado)
à plataforma angolana AI-First, com base em pesquisa de referências globais e africanas.

---

## 1. O modelo Google, traduzido

| Pilar Google | Adaptação angolana |
|---|---|
| Utilizadores grátis (Search, Gmail, Maps, YouTube) → atenção | **Assistente de consumo gratuito no WhatsApp**: o angolano pergunta "onde compro X mais barato no Kilamba?", "marca consulta no dentista", "quanto custa Y em Luanda" — e a plataforma responde de graça, 24/7 |
| Anunciantes pagos (Google Ads) → monetizam a intenção | **PMEs, importadores, marcas e distribuidores pagam** para serem a resposta: destaque nas recomendações, leads qualificados, transações e módulos premium |
| Ecossistema fechado (Android, login Google) → dados + retenção | **WhatsApp + pagamentos (Multicaixa Express/KWiK) + base de catálogos e preços** — quanto mais se usa, mais a plataforma sabe o que se compra, a que preço e onde |

A diferença fundamental: **o "motor de busca" de Angola não é uma caixa de pesquisa — é uma
conversa de WhatsApp.** A economia informal angolana já funciona por mensagem ("tens?", "quanto
é?", "manda a referência"). A plataforma não cria um comportamento novo; organiza o que já existe.

---

## 2. Os três lados da plataforma

### Lado 1 — Consumidores (GRATUITO, a base de atenção)

Produto: **assistente pessoal de consumo no WhatsApp** (nomes de trabalho: *Kambá*, *Soba*, *Waza*).
- "Onde tem farmácia aberta agora perto do Viana?" → resposta com opções, preços e contacto
- "Compara o preço de um frigorífico no Kikolo vs. lojas online" → tabela comparada
- "Marca-me corte de cabelo sábado no Talatona" → agendamento direto na agenda da barbearia
- "Quanto está o câmbio / a conta de luz / o bilhete" → utilidades diárias

Porque é grátis: cada pergunta é um **dado de intenção de compra real** — o equivalente angolano
à query do Google. Ninguém no país tem este mapa: o que se procura, onde, a que preço, e o que
fecha em venda.

O assistente vive num **único número oficial da plataforma** e tem dois modos: **handoff**
(envia o cliente para o WhatsApp da loja, que fecha a venda) ou **venda assistida** (fecha o
pedido em nome da PME na própria conversa, com o pagamento a liquidar diretamente na conta dela).
O consumidor escolhe o canal — número da plataforma **e/ou** número da PME; a plataforma
transaciona nos dois.

### Lado 2 — PMEs (FREEMIUM, a base de oferta)

- **Grátis**: ficha no diretório, catálogo básico (até N produtos), rececionista AI com limite de
  conversas/mês, aparecer nas respostas orgânicas do assistente **e vender sob o número da
  plataforma** (modo "light", sem número próprio na API — rampa de entrada para o modo completo)
- **Pago (módulos do documento anterior)**: rececionista ilimitado, catálogo pro, orçamentos AI,
  redes sociais, cobranças, relatórios
- **Pago (visibilidade)**: destaque patrocinado nas recomendações, prioridade na categoria/bairro

O freemium resolve o problema da literacia digital: entrar custa zero e a equipa ativa tudo;
a PME só fala no WhatsApp.

### Lado 3 — Anunciantes e marcas (PAGO, o motor de receita de escala)

- **Importadores e distribuidores** (os "fornecedores" do negócio Nº 1): pagam para que os seus
  produtos sejam recomendados quando o consumidor compara preços
- **Marcas de consumo** (cervejarias, telecoms, bancos, seguradoras): campanhas conversacionais
  segmentadas por intenção real — não por perfil demográfico como no Facebook
- **Bancos e fintechs**: ofertas contextuais (conta, crédito, seguro) no momento da compra

Formato nativo: a recomendação patrocinada **dentro da conversa**, sempre marcada como tal
(transparência) e sempre com opt-in do utilizador (exigência das políticas do WhatsApp).

---

## 3. O que a pesquisa mostrou (referências e avisos)

### ⚠️ Aviso 1 — Atenção sem monetização morre: o caso Ayoba
A super-app da MTN chegou a **35 milhões de utilizadores ativos/mês** e foi
[encerrada em março de 2026](https://techcabal.com/2026/03/24/mtn-begins-shutdown-of-ayoba-as-it-shifts-to-unified-digital-platform/).
A MTN redirecionou o foco para fintech — que processou **$500 mil milhões em transações** com
crescimento de 24,9%, enquanto os serviços digitais cresceram só 15%
([Tech Insider](https://techinsider.africa/mtn-to-shut-down-ayoba-as-it-reassesses-its-super-app-ambitions/)).

**Lição:** em África, audiência grande não paga contas — o mercado publicitário digital africano
vale ~$3,8 mil milhões (2025) e Angola é uma fatia pequena
([Yahoo/Research&Markets](https://finance.yahoo.com/news/africa-digital-ad-spend-business-090100920.html)).
**A monetização tem de nascer ancorada em transações e leads, não em display ads.** A publicidade
pura é a fase final, não a inicial.

### ⚠️ Aviso 2 — Não construir uma app nova: o caso M-Pesa
O M-Pesa [cedeu o domínio das mensagens ao WhatsApp](https://blog.mondato.com/from-mobile-money-powerhouse-to-super-app-the-case-of-m-pesa/),
que é usado por 97% dos internautas no Quénia (e domina igualmente em Angola).

**Lição:** o ecossistema constrói-se **sobre** o WhatsApp, não contra ele. Zero downloads.

### ✅ Prova 1 — Retail media funciona em África: o caso Jumia
A Jumia lançou anúncios (Mirakl Ads) em 9 países africanos em 2 meses:
[**+28% de receita publicitária, +12% de GMV dos vendedores, ROAS médio 9:1**](https://www.mirakl.com/content/customer-stories/jumia/).
Vendedores pagam por visibilidade **quando ela converte em venda mensurável**.

**Lição:** o nosso "destaque patrocinado" deve ser vendido com prova de conversão (leads e vendas
registadas pela própria plataforma) — é retail media conversacional.

### ✅ Prova 2 — WeChat monetiza em camadas
O WeChat cobra [anúncios aos comerciantes + comissão sobre transações via WeChat Pay + tempo de
permanência no ecossistema](https://www.ad-hoc-news.de/boerse/news/ueberblick/the-wechat-app-mini-programs-tencent-bets-on-deeper-daily-integration/69803052).

**Lição:** a sequência correta é pagamentos/transações primeiro, publicidade depois — e os dois
juntos compõem o fosso.

### ✅ Prova 3 — A Meta já validou o funil conversacional
Anúncios click-to-WhatsApp geram
[$1,5–10 mil milhões/ano à Meta, a crescer ~80% ao ano](https://www.sendwo.com/blog/rise-of-conversational-commerce-on-whatsapp/);
200M+ de negócios usam WhatsApp Business mensalmente.

**Lição:** a Meta monetiza o **topo** do funil (o clique); a nossa plataforma é a **camada de
conversão** (a conversa, o orçamento, a marcação, a cobrança). Somos complementares à Meta, não
concorrentes — e podemos até comprar click-to-WhatsApp ads para crescer.

---

## 4. As cinco linhas de receita (na ordem certa)

| # | Linha | Quando | Preço indicativo |
|---|---|---|---|
| 1 | **Assinaturas premium das PMEs** (módulos) | Desde o dia 1 — financia tudo | 25.000–350.000 Kz/mês |
| 2 | **Leads qualificados (CPL)** — consumidor pediu, PME recebe o contacto quente | Com ~1.000 consumidores ativos | 500–5.000 Kz/lead por categoria |
| 3 | **Comissão sobre transações** — marcações, pedidos e cobranças processadas (MCX/referência) | Com módulo Cobranças ativo | 1–3% por transação |
| 4 | **Destaque patrocinado** — prioridade nas recomendações da categoria/bairro | Com ~10.000 consumidores ativos | leilão mensal por categoria/bairro, ex. 20.000–200.000 Kz |
| 5 | **Campanhas de marcas** — distribuidores, bancos, telecoms | Escala (50.000+ utilizadores) | pacotes de campanha conversacional |

Repare-se: as linhas 1–3 são o **modelo da agência-como-software** (já desenhado); as linhas 4–5
são o **modelo Google** propriamente dito. A primeira financia a construção da segunda. Este é o
erro que a Ayoba cometeu ao contrário: tentou escala antes de receita.

---

## 5. O flywheel (a "máquina Google" adaptada)

```
Assistente grátis atrai consumidores
        ↓
Perguntas geram dados de intenção (o que, onde, a que preço)
        ↓
PMEs querem estar no diretório para serem recomendadas (grátis → freemium)
        ↓
Mais oferta = respostas melhores = mais consumidores
        ↓
PMEs pagam por módulos (1) e leads (2); transações geram comissão (3)
        ↓
Dados de conversão provam ROI → leilão de destaque (4) e marcas (5)
        ↓
Receita financia melhor IA + mais categorias + mais cidades
```

O fosso composto: **dados de intenção + preços reais + contexto das PMEs + integração EMIS** —
cada volta do ciclo torna a plataforma mais difícil de copiar.

---

## 6. O que muda face ao enquadramento anterior

| Antes (plataforma B2B) | Agora (modelo Google) |
|---|---|
| Cliente = PME | Cliente pagante = PME/marca; utilizador = consumidor |
| Receita só de assinatura | 5 linhas de receita em fases |
| Crescimento por vendas diretas | Crescimento por utilidade gratuita (produto) |
| Dados são subproduto | Dados de intenção são o ativo central |
| Concorrente: agências e ERPs | Concorrente real: o "perguntar ao conhecido no WhatsApp" |

A cunha mantém-se: o **Rececionista AI** para clínicas/salões continua a ser o ponto de entrada
B2B — mas agora cada marcação feita por ele é também um **consumidor dentro do ecossistema**,
sem custo de aquisição. O B2B paga a construção do B2C.

---

## 7. Métricas norte do modelo

1. **Perguntas de consumidores/semana** (atenção) — a "query volume" da plataforma
2. **Taxa de resposta útil** (qualidade da IA) — % de perguntas resolvidas sem humano
3. **Leads entregues → vendas fechadas** (prova de ROI para cobrar)
4. **Módulos por PME** (expansão B2B)
5. **% de conversas que terminam em transação** (caminho para a linha 3)

---

## 8. Riscos específicos do modelo de atenção

| Risco | Mitigação |
|---|---|
| Política do WhatsApp proíbe spam/ads não solicitados | Assistente é opt-in; patrocínio só dentro de conversas iniciadas pelo utilizador e marcado como "patrocinado" |
| Confiança: "a recomendação é paga?" | Transparência radical: rótulo claro + sempre mostrar alternativa orgânica; credibilidade é o ativo |
| Lei de Proteção de Dados de Angola (Lei n.º 22/11) | Consentimento explícito, dados anonimizados para segmentação, DPO desde cedo |
| Mercado de ads angolano pequeno | Linhas 4–5 só depois de escala; receita inicial vem de assinaturas/leads/transações |
| Custo de aquisição de consumidores | Crescer dentro das PMEs (cada cliente do Rececionista vira utilizador) + conteúdo viral de utilidade ("pergunta ao Kambá") |

---

## 9. Roadmap revisto (modelo Google em 3 atos)

**Ato 1 (0–6 meses) — Receita primeiro**: Rececionista AI + Catálogo AI para 20–50 PMEs pagantes
em Luanda. Em paralelo, ligar o assistente de consumo gratuito **só para os catálogos destas PMEs**
(perguntas de preço/disponibilidade/marcação). Primeiros dados de intenção.

**Ato 2 (6–18 meses) — Atenção organizada**: abrir o assistente ao público por categoria e bairro;
lançar CPL (linha 2) e comissão de transações (linha 3); diretório freemium atrai centenas de PMEs
sem custo de vendas.

**Ato 3 (18+ meses) — Monetização de atenção**: leilão de destaque patrocinado por categoria/bairro
(linha 4); primeiras campanhas de marcas/distribuidores (linha 5); expansão para Benguela/Huíla;
marketplace de operadores (fase C do enquadramento anterior).

---

## Fontes

- Encerramento da Ayoba: [TechCabal](https://techcabal.com/2026/03/24/mtn-begins-shutdown-of-ayoba-as-it-shifts-to-unified-digital-platform/), [Tech Insider](https://techinsider.africa/mtn-to-shut-down-ayoba-as-it-reassesses-its-super-app-ambitions/), 35M MAU: [Technology Times](https://technologytimes.ng/ayoba-mtn-super-app-reaches-35-million-users/)
- M-Pesa vs WhatsApp: [Mondato](https://blog.mondato.com/from-mobile-money-powerhouse-to-super-app-the-case-of-m-pesa/)
- Ad spend digital em África: [Yahoo Finance/Research and Markets](https://finance.yahoo.com/news/africa-digital-ad-spend-business-090100920.html)
- Jumia + Mirakl Ads: [Mirakl](https://www.mirakl.com/content/customer-stories/jumia/)
- Modelo WeChat: [ad-hoc-news](https://www.ad-hoc-news.de/boerse/news/ueberblick/the-wechat-app-mini-programs-tencent-bets-on-deeper-daily-integration/69803052), [FourWeekMBA](https://fourweekmba.com/how-does-wechat-make-money/)
- Click-to-WhatsApp e comércio conversacional: [Sendwo](https://www.sendwo.com/blog/rise-of-conversational-commerce-on-whatsapp/), [egrow](https://www.egrow.com/en/blog/whatsapp-commerce-statistics-2026-the-numbers-every-e-commerce-owner-should-know)
- Dados Angola: ver `01-modelo-negocios-angola-ai-first.md` (EMIS, UNCTAD, trade.gov)
