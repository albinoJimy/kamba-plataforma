# Estratégia de digitalização distribuída: cada PME vende no seu próprio WhatsApp

Resposta ao maior ponto cego (`04-pontos-cegos-plataforma.md`, nº 1 e 2): em vez de digitalizarmos
os mercados com equipas pagas, **a digitalização acontece como subproduto da PME usar a plataforma
para vender**. O incentivo é dela, o custo é dela, os dados são da plataforma.

---

## 1. A inversão de lógica

| Modelo anterior (digitalização centralizada) | Modelo distribuído (loja no WhatsApp) |
|---|---|
| Equipas de rua pagas recolhem dados loja a loja | A PME cadastra os seus produtos porque isso é a **sua montra** |
| Dados envelhecem; ninguém tem incentivo em atualizar | A PME mantém preço/stock fresco porque **dados errados = cliente dela perdido** |
| Custo cresce linearmente com a cobertura | Custo marginal ~zero por nova PME |
| Índice primeiro, receita depois | **Receita primeiro; o índice é o escape do processo de venda** |

É o modelo do **Shopify**: cada comerciante constrói a sua loja para si; a plataforma agrega
depois (a Shop app do Shopify é exatamente o índice federado de todas as lojas). É também o
**Google Business Profile**: o negócio mantém a ficha atualizada de graça porque dela vêm clientes.
E o **Meesho** na Índia provou que o comércio distribuído via WhatsApp escala em mercados emergentes.

## 2. O produto: "Loja no WhatsApp" por PME

Cada PME recebe, no **seu próprio número de WhatsApp Business**:

1. **Catálogo AI** (módulo 4): foto do telemóvel → IA cria título, descrição PT-AO, categoria,
   fundo limpo. 10 minutos para montar a loja.
2. **Vendedor AI** (módulo 6 evoluído): responde "tens?", "quanto é?", "onde fica?" com base no
   catálogo real, tira pedidos, emite **referência Multicaixa/QR da plataforma**.
3. **Painel mínimo** (ou só mensagens): "atualiza o preço do X", "o Y acabou" — a PME gere a loja
   por mensagem, sem app nova.
4. **Entrega**: coordenação com motoboy/Kubinga/Tupuca.

O consumidor final fala com o WhatsApp **do vendedor que já conhece** — não com um bot
desconhecido. Isto resolve em simultâneo o ponto cego 5 (confiança: o concorrente era "a tia do
grupo") e o risco de política da Meta (a conversa acontece no número da PME, opt-in natural).

## 3. Como as lojas viram o índice

Cada catálogo criado alimenta, em segundo plano, o **índice federado da plataforma**:

```
PME A (boutique, Maianga)  ─┐
PME B (eletrónica, Kikolo) ─┼── normalização por IA ──► ÍNDICE: produto · preço ·
PME C (farmácia, Talatona) ─┘   (mesma língua,         zona · stock · horário
                                 mesmas categorias)         │
                                                            ▼
                                        Número da PLATAFORMA: responde, faz
                                        handoff p/ a PME (B1) ou fecha
                                        a venda em nome dela (B2)
```

A normalização é o trabalho crítico da IA: cada PME escreve à sua maneira ("ténis", "sapatilha",
"niker 42 azul") e o índice precisa de categorias e atributos consistentes para ser pesquisável.

## 4. Dois pontos de entrada, um só motor: número da PLATAFORMA e/ou número da PME

O consumidor pode chegar por dois canais — e a plataforma serve os dois com a mesma espinha:

**Fluxo A — número da PME (loja no WhatsApp).** O cliente fala com o vendedor que já conhece; o
Vendedor AI da loja responde, tira o pedido e emite a referência. Confiança máxima, plataforma
invisível.

**Fluxo B — número da PLATAFORMA.** O cliente fala com um único número oficial da plataforma:
- Pergunta → o assistente consulta o índice federado e responde com 2–3 opções reais (preço, zona,
  distância)
- **B1 — handoff**: "quer falar com a loja? É este número" → a conversa continua no WhatsApp da
  PME (anatomia Google: pesquisa → clique → site do comerciante)
- **B2 — venda assistida**: o assistente **fecha o pedido em nome da PME** na própria conversa:
  pedido com ID único, referência de pagamento que liquida **diretamente na conta da PME**,
  entrega coordenada. A PME só recebe "pedido #1234 pago, entregar amanhã"

O Fluxo B2 é mais do que conveniência — resolve três problemas estruturais:
- **Cold-start**: o número da plataforma vende desde o dia 1, antes de qualquer PME ter migrado o
  próprio número para a API; o catálogo delas vende por procuração
- **PME "light"**: vendedores que não querem/não conseguem verificação Meta própria vendem à
  mesma — ficam sob o guarda-chuva do número da plataforma, sem número próprio na API
- **Atribuição total**: no B2 a plataforma controla pedido + pagamento → CPL, comissão e reviews
  ficam perfeitamente auditáveis; no B1 a atribuição vem do ID de pedido emitido no handoff

E mantém o **patrocínio nativo e transparente**: o "destaque" aparece nas 2–3 opções sugeridas,
marcado como patrocinado, dentro de uma conversa que o consumidor iniciou.

## 5. O que esta estratégia resolve dos pontos cegos

| Ponto cego | Como a loja no WhatsApp o ataca |
|---|---|
| 1. Custo de criar o índice | A PME cria o seu pedaço, por incentivo próprio |
| 2. Frescura dos dados | Dados errados custam vendas à própria PME; o assistente ainda confirma ("ainda tem?") |
| 5. Confiança no bot | Fluxo A: o consumidor fala com o vendedor conhecido; Fluxo B: reputação verificada e selo substituem a confiança pessoal |
| Meta AI concorrente | A Meta não tem as lojas federadas nem o checkout EMIS |
| Política do WhatsApp | Conversa comercial no número da PME **ou** no número oficial da plataforma; ambos opt-in puro |
| 12. Capital | Receita B2B desde o dia 1 financia o índice em vez de equipas de rua |

## 6. O que NÃO resolve (nova lista de atenção)

1. **Cold-start por zona/categoria**: o assistente só é útil no bairro X quando houver densidade de
   lojas lá → crescer por "clusters" (1 mercado/bairro de cada vez), não por cidade inteira
2. **Qualidade dos dados na origem**: a PME cadastra mal, esquece, abandona → a IA tem de
   estruturar input imperfeito e o sistema tem de "chatear" a PME para atualizar (gamificação:
   "lojas atualizadas esta semana aparecem primeiro")
3. **As equipas de rua não desaparecem — mudam de função**: de recolhedoras de dados passam a
   **rede de agentes de ativação** (onboard da PME, primeira foto, formação de 30 minutos), pagas
   **à comissão** por PME ativa e faturante, não por salário
4. **Comissão sobre transação continua dependente de EMIS/BNA** — a referência de pagamento da
   plataforma resolve a auditoria, mas não a parceria institucional
5. **Risco de bypass**: PME e consumidor conhecem-se e cortam a plataforma → mitigado se o valor
   contínuo for real (Vendedor AI, referências, relatórios, destaque no assistente)

## 7. O novo funil de crescimento (loop de dois lados)

```
Ativar PMEs num cluster (agentes à comissão)
      → lojas no WhatsApp vendem mais (prova)
        → vizinhos do mercado querem também (boca-a-boca no cluster)
          → índice do cluster fica denso
            → assistente de consumo lançado SÓ nesse cluster
              → consumidores trazem mais vendas às PMEs
                → case study para o cluster seguinte
```

Densidade antes de escala: **10 clusters completos valem mais que 1.000 lojas dispersas**,
porque o assistente só converte onde tem cobertura real.

## 8. Sequência de execução revista

1. **Semanas 1–4**: construir "Loja no WhatsApp" mínima (catálogo AI + Vendedor AI + referência
   de pagamento) e ativar 10 PMEs piloto num único mercado/bairro, à mão
2. **Mês 2–3**: provar que as PMEs vendem mais (antes/depois); recrutar 2–3 agentes à comissão;
   chegar a 50–100 lojas no cluster
3. **Mês 4**: ligar o assistente de consumo apenas nesse cluster e medir leads → vendas via IDs
   de pedido
4. **Mês 5+**: replicar o playbook cluster a cluster; introduzir CPL e destaque patrocinado quando
   o assistente tiver volume

O modelo Google mantém-se como destino — mas a porta de entrada deixa de ser "digitalizar o
mercado" e passa a ser **"pôr cada PME a vender melhor no seu próprio WhatsApp e ficar com o
mapa"**.
