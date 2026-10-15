# Pontos cegos — ronda 2 (sobre o modelo "Loja no WhatsApp")

Segunda stress-test, desta vez sobre `05-estrategia-loja-no-whatsapp.md` e `06-expansao-plataforma.md`.
Ordenado por gravidade. A ronda 1 está em `04-pontos-cegos-plataforma.md`.

---

## 1. A opacidade de preços é cultural, não um defeito de dados

Assumimos que a PME mantém preços públicos e frescos porque "dados errados = venda perdida".
Mas no comércio informal angolano **o preço é opaco por desígnio**: "quanto é?" → *"manda inbox"*.
O preço é arma de negociação — varia por cliente, por dia, por câmbio, por cara. Um preço baixo
publicado serve de isco e depois sobe na conversa.

Consequência: a promessa central do assistente ("compara preços") **choca com a cultura de
venda**. Ajustes possíveis: comparar **disponibilidade, zona e reputação** em vez de preço fechado;
preços como "a partir de"; ou focar o assistente em categorias de preço mais estável (serviços,
restauração, farmácia formal). Mas temos de escolher — a versão atual do produto ignora isto.

## 2. O paradoxo da "renda invisível"

O vídeo original chamava-se *renda invisível* — e o comércio informal angolano **valoriza
exatamente a invisibilidade**: sem registos, sem rasto fiscal, longe da AGT. A nossa plataforma
faz o contrário: referências com ID, histórico de vendas, Factura AI, score de crédito.

Para a PME formal(izável) isto é valor. Para o vendedor informal, **é uma ameaça** — e ele é
exatamente o segmento que imaginámos a digitalizar mercados. Há uma escolha de segmento por fazer:
- **Segmento A**: PMEs formais e em formalização (querem Factura AI, selo, crédito) → adotam
- **Segmento B**: informal que quer continuar invisível → nunca adotará ferramentas que deixam
  rasto; só aceita se o valor (vendas) for imediato e o rasto ficar opaco para terceiros

Misturar os dois no mesmo pitch é erro. E a agenda de formalização do Estado (parceria INAPEM)
pode assustar o segmento B se for comunicada cedo demais.

## 3. O problema técnico do "seu próprio número"

A promessa "a loja funciona no número da própria PME" esconde uma restrição real: o número de
WhatsApp Business da PME vive na **app do telemóvel do dono**; os agentes de IA correm na **API
cloud (WhatsApp Business Platform)**. Historicamente não coexistiam; a Meta tem vindo a abrir
mecanismos de coexistência/ligação, mas com limitações e requisitos (conta Business verificada,
BSP parceiro). Opções:
- Migrar o número para a API via BSP (Twilio, 360dialog, etc.) — muda a experiência do dono
- Número novo da plataforma com reencaminhamento — quebra a promessa do "número conhecido"
- Coexistência oficial da Meta — validar **antes** de prometer o fluxo

Se isto falhar, o conceito "Vendedor AI no número da PME" precisa de redesenho. É testável numa
semana e está no caminho crítico.

**Atualização (fluxo dual):** o risco foi mitigado por dois lados — a coexistência oficial já está
disponível e Angola é elegível (ver `08-arquitetura-tecnica-v2.md` §2.1); e o Fluxo B permite que uma
PME "light" venda sob o número da plataforma **sem migrar o seu número**, fazendo este ponto
deixar de ser bloqueante.

## 4. Aquisição de consumidores continua fraca: somos Shopify ou Google?

A loja no WhatsApp resolve o lado da oferta — mas quem traz **consumidores novos** ao assistente?
A PME promove a *sua* loja, não a plataforma. Risco real: construirmos excelente tooling B2B e o
assistente/índice nunca descolar — foi o que aconteceu ao Shopify (negócio gigante em SaaS; a Shop
app de consumo é marginal).

Duas leituras honestas:
- **Aceitar B2B-first**: a receita vem de assinaturas, transações e serviços à PME; o assistente
  é experiência barata nos clusters, não pilar
- **Ou desenhar aquisição B2C a sério**: vitrine web com SEO (já prevista), assistente em grupos
  de bairro, campanhas click-to-WhatsApp pagas com retorno via CPL

O que não podemos é assumir o flywheel B2C como garantido. O modelo "Google" depende dele; o
modelo "Shopify" não — e paga as contas mais cedo.

## 5. A fraude do comprovativo falso

Em Angola é endémico o envio de **comprovativos de transferência falsificados** (screenshot
editado). Qualquer fluxo que aceite "manda o comprovativo" como prova de pagamento será abusado
em escala. Regra arquitetural: **o pagamento só conta se for confirmado server-side** (referência
EMIS/KWiK reconciliada pela plataforma, nunca imagem). Isto reforça a dependência da parceria
EMIS — não é opcional, é o núcleo anti-fraude.

## 6. Unit economics por transação ainda não existe

Já flaggámos o custo do lado gratuito, mas falta o número que decide tudo:

```
Comissão média por pedido (ex.: 2% de 25.000 Kz) ........ 500 Kz
Custo IA por conversa (LLM + Whisper + retries) ......... 80–200 Kz
Custo API WhatsApp por conversa ......................... 30–80 Kz
Custo agente de ativação amortizado ..................... ?
Custo fraude/disputas amortizado ........................ ?
```

Com tickets baixos, a margem por transação pode ser fina ou negativa → o modelo precisa de
**categorias de ticket alto** (eletrónica, serviços, saúde privada) ou de receita de assinatura a
carregar o peso. Modelar antes de escalar.

## 7. O "quero comprar" pode morrer por silêncio

A procura invertida depende de as PMEs **responderem** aos pedidos. Marketplace que envia pedidos
e recebe silêncio treina o consumidor a desistir. É preciso: ranking por taxa/velocidade de
resposta, SLA visível ("3 lojas respondem em média em 12 min"), penalização de lojas mudas e —
no início — um humano da equipa a garantir resposta enquanto a densidade é baixa (concierge).

## 8. A rede de agentes é um negócio operacional em si

Agentes à comissão trazem: fraude (cadastrar PMEs-fantasma para ganhar comissão), qualidade
irregular de onboarding, churn de agentes, necessidade de supervisão, materiais, metas. M-Pesa e
Jumia gastaram fortunas a gerir redes de agentes. Subestimámos: **a camada de gestão de agentes é
produto + pessoas + auditoria**, não uma linha de comissão.

## 9. Logística federada = responsabilidade federada

Se o motoboy cadastrado rouba a mercadoria, danifica-a ou sofre acidente, o consumidor culpa a
**plataforma**, não o estafeta. E COD (pagamento na entrega) com estafetas é vetor clássico de
fraude. Antes de federar entregas: verificação + caução/seguro dos estafetas, limites de valor por
entrega, e fluxo de disputa definido. O mesmo para disputas consumidor↔PME: a plataforma será
arrastada para mediar — desenhar o fluxo desde o piloto.

## 10. Propriedade dos dados conversacionais

Indexar conversas comerciais levanta dois riscos:
- **ToS da Meta**: extrair/espelhar conteúdo de conversas do WhatsApp pode violar os termos
- **Lei n.º 22/11**: dados de consumidores exigem consentimento e finalidade clara

Arquitetura limpa: **os dados nascem na nossa base** (catálogo, preços, pedidos entram via
ferramentas da plataforma) e o WhatsApp é apenas o canal de exibição. Nunca o inverso. Isto tem
de estar no desenho desde o primeiro dia — refatorar depois é quase impossível.

## 11. Categorias sensíveis: farmácia e saúde

O exemplo que temos usado ("farmácia aberta agora") é das piores categorias para começar: IA a
responder sobre medicamentos = responsabilidade sobre saúde + regulação do setor farmacêutico.
Regra: começar por categorias onde uma resposta errada custa pouco (moda, eletrónica, serviços,
restauração) e deixar saúde/finanças para quando houver guardrails e parceiros formais.

## 12. Talento e operação local

Quem mantém agentes de IA, integrações EMIS e pipelines de dados **em Luanda**? O talento existe
mas é escasso e disputado por bancos/telecoms. Opções: equipa remota mista, formação interna
(Academia Kambá pode ter via técnica), ou stack deliberadamente simples (n8n + APIs geridas) para
reduzir dependência de engenharia sénior.

## 13. Risco cambial nos custos

Receita em Kz, custos críticos em USD (LLMs, BSP do WhatsApp, infra). Com desvalorização, a
margem comprime sozinha. Mitigações: preços revistos trimestralmente, modelos mais baratos para
intenções simples (nem tudo precisa de GPT-4o), e a linha diáspora como hedge natural.

## 14. O maior de todos: ainda não há nenhum cliente pagante

Temos 6 documentos de estratégia e zero validação de receita. O risco dominante já não é
estratégico — é **paralisia analítica**. Cada nova ronda de "o que está a escapar" tem retorno
decrescente; a informação que falta já não está em pesquisa, está **no mercado**. As 6 validações
do plano anterior continuam por executar e valem mais do que qualquer documento novo.

---

## Atualização à lista de validações (ronda 1 + ronda 2)

1. 20 PMEs **formais/em formalização** pagam pela Loja no WhatsApp ou Factura AI? (segmento A)
2. Viabilidade técnica: coexistência app do dono ↔ API cloud no mesmo número (ou alternativa)
3. Custo real por conversa (LLM + Whisper + API) vs. comissão por ticket médio → unit economics
4. Teste Meta AI + teste de voz PT-AO/Kimbundu
5. Digitalização de 1 cluster via agentes à comissão (medir custo real + fraude de agentes)
6. Reuniões EMIS/KWiK + 1 banco + INAPEM (tempo real de acesso + requisitos anti-fraude server-side)
7. **Novo:** teste de opacidade de preços — 30 PMEs aceitam publicar preço? Se não, o assistente
   compara o quê?
8. **Novo:** fluxo de disputa piloto (1 caso real mediado pela equipa) antes de federar logística
