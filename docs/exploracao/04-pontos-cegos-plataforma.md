# Pontos cegos da visão de plataforma (advogado do diabo)

Continuação de `03-modelo-plataforma-google-angola.md`. Stress-test honesto ao que foi desenhado,
ordenado do mais estrutural ao mais operacional.

---

## 1. O problema do índice — o maior de todos

**O Google indexou uma web que já existia. Nós temos de criar a web.**

Não existe camada de dados estruturados sobre o comércio angolano: sem sites, sem fichas de
negócio, sem preços online, sem horários, sem stock. Quando o consumidor perguntar "onde compro um
frigorífico mais barato no Kikolo?", o assistente só responde bem se alguém tiver **criado e
mantido** essa informação. A IA não inventa o índice — ela apenas o consulta.

Consequência prática: a parte mais cara da plataforma não é a tecnologia, é a **digitalização
física** — equipas de rua nos mercados (30, Kikolo, São Paulo, Asa Branca), loja a loja, como a
Jumia fez com redes de agentes e o Google fez com o Street View. Não orçamentámos isto em lado
nenhum.

**Pergunta de validação:** quanto custa criar e manter fresca 1 ficha de negócio em Luanda?

## 2. A frescura dos dados

Mesmo com o índice criado: preços em Angola mudam com o câmbio (às vezes semanalmente), o stock é
volátil, o vendedor informal não atualiza catálogo nenhum. **Uma resposta desatualizada destrói a
confiança mais depressa do que uma ausência de resposta.** É preciso um mecanismo de frescura:
a PME atualiza porque recebe leads (incentivo), o assistente pergunta ativamente ("ainda tem?"),
parcerias com distribuidores para preços de referência. Sem isto, o produto degrada-se sozinho.

## 3. A economia unitária do lado gratuito

O custo marginal de uma pesquisa no Google é ~zero. O nosso não:
- WhatsApp Business API **cobra por conversa** (mensagens de serviço iniciadas pelo negócio têm tarifa)
- Cada mensagem gasta **inferência de LLM** (e nota de voz gasta Whisper + LLM)

Ou seja: **o assistente gratuito tem custo real e crescente por utilizador.** Se escalar antes da
monetização, escala prejuízo — o pecado da Ayoba, mas na versão custo variável. É preciso modelar
o custo por utilizador ativo/mês em Kz e desenhar tetos (mensagens grátis/mês, categorias pagas).

## 4. A Meta é concorrente, não só parceira

Dois movimentos da dona da plataforma:
- **Meta AI dentro do WhatsApp**, grátis e por defeito — porque haveria o angolano de falar com o
  nosso assistente em vez do da Meta? Resposta: só se tivermos os **dados locais estruturados** que
  a Meta não tem (preços reais, stock, quem está aberto agora). O que reforça o ponto 1: o índice
  não é um detalhe, é a defesa existencial.
- **WhatsApp Business já traz grátis** catálogo, respostas rápidas e mensagens automáticas — e vai
  ganhar cada vez mais IA nativa para PMEs. O nosso wedge (Rececionista AI) pode ser comoditizado
  de graça pelo próprio WhatsApp.

Defesa real: aquilo que a Meta nunca fará para Angola — integração EMIS/referências, agenda com
confirmação, facturação AGT, preços de mercado locais, operação humana de back-office.

## 5. O comportamento real do consumidor angolano

A "busca" angolana é **social**: pergunta-se no grupo de WhatsApp do bairro, nos status, ao
vizinho, ao taxista. Confia-se na recomendação de uma pessoa conhecida. O nosso concorrente real
não é o Google nem a Meta — **é a tia do grupo**. Um bot desconhecido a recomendar onde gastar
30.000 Kz exige um salto de confiança que subestimámos. Hipóteses de ataque: entrar como utilidade
*dentro* de comunidades existentes (grupos, associações de bairro, igrejas, empresas) em vez de
assistente isolado; prova social antes de escala.

## 6. Fraude e a armadilha do patrocínio

- Angola tem histórico de burlas online → listagens falsas, perfis fantasma e esquemas vão tentar
  usar a plataforma. **Custo de moderação e verificação não está orçamentado** (KYC de negócios,
  verificação presencial das fichas — outra vez equipas de rua).
- O patrocínio só funciona como o Google se a camada orgânica for genuinamente útil. Com índice
  fraco (ponto 1), "destaque patrocinado" torna-se pay-to-play visível → destrói credibilidade.
  A transparência que defendemos é necessária mas não suficiente.

## 7. Assumimos rails de pagamento que não controlamos

Tratámos "integração Multicaixa Express / reconciliação automática" como detalhe técnico. Não é:
- A EMIS não tem API aberta self-service para startups; acesso é **negociação institucional**
- Cobrar comissão sobre transações pode exigir enquadramento junto do **BNA** (intermediação de
  pagamentos)
- KWiK/PayPay têm os seus próprios interesses e podem querer ser eles a plataforma

A linha de receita 3 (comissão sobre transações) depende de **parceria**, não de código. E
parcerias em Angola levam trimestres, não sprints.

## 8. O go-to-market angolano é de relações, não de produto

O Google cresceu com distribution deals (default search em browsers). O equivalente angolano:
- **Telecoms** (Unitel/Movicel): zero-rating do assistente, bundles, USSD fallback
- **Bancos** (BFA, BAI, BIC): programas PME, canais de app, co-marketing
- **Estado**: INAPEM, PRODEL, agenda de formalização da economia informal — pode ser canal e até
  financiador
- **Associações** de comerciantes e mercados organizados

Num mercado de relações, **um contrato de parceria vale mais do que dez features**. Isto devia
estar no centro da estratégia e está na periferia.

## 9. Endereços e logística: a camada que falta para fechar transações

"Atrás do mercado, perto da bomba" não é endereçável. Sem georreferenciação e sem logística
fiável, a conversa converte mas a entrega falha — e a falha é atribuída à plataforma. Opções:
parceria com Kubinga/Tupuca desde cedo, ou módulo próprio de localização (o "Google Maps do bairro"
é, ele próprio, um produto com valor).

## 10. Voz e línguas

O utilizador informal comunica por **notas de voz** e mistura português com Kimbundu/Umbundu.
Os LLMs atuais lidam bem com PT; com línguas nacionais, mal. Se a interface falhar na voz, perdemos
exatamente o segmento que mais precisa da plataforma. Isto é testável em uma semana e devia ser
testado **antes** de qualquer desenvolvimento.

## 11. Regulatório: o risco esquecido e a oportunidade esquecida

- Risco: Lei n.º 22/11 (proteção de dados), regras BNA se tocarmos pagamentos, publicidade
  conversacional sem enquadramento claro.
- **Oportunidade ignorada:** a AGT está a impor **facturação electrónica às PMEs**. Um módulo
  "Factura AI" (emite factura certificada a partir de uma mensagem de WhatsApp) pode ser um wedge
  **melhor que o Rececionista**: dor regulamentar, obrigatória, com prazo — as PMEs pagam para
  cumprir, não para experimentar. Nenhum dos três documentos aproveitou isto.

## 12. Capital e cadência

O modelo de 3 atos precisa de subsídio cruzado (o B2B financia o B2C) durante 18+ meses. Não
respondemos: com que capital se chega ao Ato 3? Bootstrapping puro torna o Ato 2 lento demais
(a frescura dos dados exige equipa de rua desde cedo). Investimento anjo em Angola existe mas é
escasso; a tese precisa de um **plano de financiamento explícito**, nem que seja "receita de
serviços cobre 2 pessoas de rua + stack".

## 13. Mortalidade da base de clientes

PMEs angolanas têm taxa de mortalidade alta. Se 30% dos clientes B2B fecham por ano, o churn não é
objeção de produto — é demografia. O modelo de receita tem de assumir substituição constante da
base, o que reforça a necessidade do diretório freemium como funil permanente de novos clientes.

---

## O que fazer com isto: as 6 validações antes de mais estratégia

1. **Teste de receita:** 20 PMEs pagam pelo Rececionista ou Factura AI? (4 semanas, porta a porta)
2. **Teste de custo:** custo real por conversa (API WhatsApp + LLM + voz) em Kz → teto do gratuito
3. **Teste do índice:** digitalizar 1 mercado (ex.: 100 lojas) e medir custo por ficha + custo de
   manutenção mensal
4. **Teste Meta AI:** o que o Meta AI já responde bem sobre Luanda hoje? Onde é que falha? (esse
   gap é o nosso território)
5. **Teste de voz:** notas de voz PT-AO + Kimbundu → taxa de acerto do pipeline
6. **Mapa de parcerias:** primeira reunião com EMIS/KWiK, um banco e INAPEM — medir tempo real de
   acesso

Se estas 6 validações correrem bem, os três documentos anteriores mantêm-se. Se correrem mal,
o ponto de entrada muda (provavelmente para Factura AI + parcerias), mas a tese de plataforma
sobrevive.
