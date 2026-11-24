# Pré-registo do experimento dos módulos de entrada — H10, H11 e H12

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — pré-registo das hipóteses H10–H12, das definições operacionais, dos critérios de abate e da regra de decisão dos módulos de entrada |
| Versão | 1.1 |
| Data | 2026-11-24 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-127 (EPIC-11) |
| Estado | NÃO VERIFICADO — nenhuma das três hipóteses foi medida; este documento é anterior à primeira medição |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H10, H11, H12 e os limiares); `../../../../specs/EPIC-11_Modulos_Entrada.md` (bloco do KAM-127: definições, critérios de abate e regra de decisão); `../E5_Modulos_Entrada.md` (disposição a pagar, inquérito, B1) |
| Dono | Fundador (a decisão de cada hipótese e de cada módulo é dele, `../../../../specs/00_KAMBA_Carta.md` §4.2); a medição é do Responsável de Produto com o Engenheiro de Plataforma (OBS) |
| Documento-fonte | `../../00_Arquitectura_Solucao.md` (ADR-020, D13); `../../02_Agent_Runtime_Verticais.md` §21.5; `../../09_Topologia_Operacao_Escala.md` §21 |
| Relacionados | [`Registo_Hipoteses.md`](Registo_Hipoteses.md) (H1–H9), [`../../../experimento-modulos.md`](../../../experimento-modulos.md) (operação), [`../../../modulos-entrada.md`](../../../modulos-entrada.md) (custo e preços de teste, KAM-124) |
| Instrumento de medição | `db/experimento_modulos.py` (`experimento-modulos`), sobre as vistas `platform.v_h10`, `platform.v_h11`, `platform.v_h12` e `platform.v_h12_pagantes` |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | Ratificado (decisões do fundador de 2026-11-24, no bloco do KAM-127) | 2026-11-24 |
| Responsável de Produto | *(por nomear)* | — |

> **Este documento nasce antes da medição, e é isso que o torna útil.** Um
> limiar escolhido depois de ver o resultado não é um limiar. O que aqui está
> fixa, **antes da primeira leitura**, as três hipóteses, o que conta como
> «usar», «entrar por um módulo», «activar» e «pagar», os critérios de abate e
> a regra que transforma uma leitura em manter, ajustar ou abater.
>
> **Os limiares foram ratificados pelo fundador a 2026-11-24** (versão 1.1),
> antes da primeira leitura — vinham do `14` §2 («Limiares são propostas
> minhas») e do bloco do KAM-127 nos critérios de abate. Uma alteração depois desta versão faz-se por linha nova de
> «Controlo de versões», com o motivo; uma alteração **depois de haver
> resultado** é uma mudança de critério, e não um ajuste.
>
> **Nada aqui é resultado.** As tabelas do §5 e do §6 nascem vazias. Quem as
> preenche é a leitura das semanas 8, 10 e 12 do Piloto, com PMEs reais.

---

## 1. As três hipóteses

| H | Enunciado | Métrica | Limiar | Leitura |
|---|---|---|---|---|
| H10 | Os módulos de entrada atraem PMEs | % das PMEs da coorte que usam ≥ 1 módulo nos primeiros 14 dias | ≥ 60% | semanas 8, 10 e 12 |
| H11 | Os módulos de entrada levam ao atendimento | % das PMEs que entram por um módulo e activam o atendimento aos 30 dias | ≥ 30% | semanas 8, 10 e 12 |
| H12 | O custo de geração fecha e há disposição a pagar | (i) custo por PME e módulo ÷ preço de teste do módulo; (ii) PMEs distintas que pagam por um módulo isolado | (i) ≤ 15%; (ii) ≥ 3 por módulo | semanas 8, 10 e 12 |

**Com ~10 PMEs, as percentagens são grosseiras.** 6 em 10 são 60%, e o
intervalo de Wilson a 95% vai de ~31% a ~83%. Por isso **toda a leitura sai com
n/N e com o intervalo**, e nunca só com a percentagem: um «cumpre» com um
intervalo que desce abaixo do limiar é uma leitura fraca, e o relatório di-lo.
Os limiares e as janelas estão em `config/experimento_modulos.yaml`, que é a
cópia máquina-legível desta tabela (`kamba_core.modulos.experimento` lê-a e
falha fechado).

---

## 2. Definições operacionais

### 2.1 «Usa um módulo» é um resultado de valor, e não uma abertura

| Módulo | O resultado | De onde se lê | O instante |
|---|---|---|---|
| `catalogo` | ≥ 1 produto publicado | `catalog_ingestions.estado = 'publicada'` | `confirmado_at` |
| `foto` | ≥ 1 versão escolhida | `image_jobs.escolhida`, sem as `sintetica` | `atualizado_at` |
| `social` | ≥ 1 item `aprovado` | `content.approved` no `events_log` | `ocorrido_em` |
| `orcamento` | ≥ 1 `quote.sent` | `quote.sent` no `events_log` | `ocorrido_em` |

Abrir o painel, pedir uma legenda ou fotografar sem publicar **não conta**.

### 2.2 A coorte da H10 e a censura

* **Entrada na coorte:** o **primeiro** `tenant.provisioned` do tenant no
  `events_log`.
* **Fora da coorte:** os tenants que não são PME (`tenants.tipo <> 'pme'`) e os
  marcados como **equipa** ou **teste** em `platform.module_experiment_exclusions`.
  A marca faz-se com `experimento-modulos excluir`, e é só de acrescentar: uma
  exclusão feita depois de uma leitura muda o N, e fica escrita com quem a fez.
* **Janela:** 14 dias desde a entrada, **semiaberta** — `[entrada, entrada + 14
  dias)`. Conta um resultado de valor com instante **antes** do fim da janela —
  incluindo um anterior ao provisionamento, feito pelo painel web enquanto o
  WhatsApp não estava ligado; um aos 14 dias exactos já não conta.
* **Censura:** uma PME com menos de 14 dias de observação fica **censurada** e
  não entra no N (aos 14 dias exactos deixa de o estar). Conta-se à parte.

### 2.3 A H11

* **«Entra por um módulo»:** o primeiro resultado de valor de um módulo (§2.1)
  acontece **antes** da primeira conversa de cliente — ou a PME ainda não teve
  nenhuma.
* **«Primeira conversa de cliente»:** a primeira resposta do bot (`agent.replied`
  no `events_log`) a um contacto que **não é o dono** — o `tenants.owner_contact_id`,
  que tem o mesmo escritor único do `contacts.papel` e se lê sem tocar no cofre de
  identidade —, pelo WhatsApp, numa conversa que existe e não é de teste
  (`conversations.is_test`).
* **«Activa o atendimento aos 30 dias»** (*proposta*, alinhada com o KAM-117):
  canal ligado (`tenant_channels.estado = 'ativo'`, vertical `vendedor` ou
  `servicos`), vertical de atendimento activa (`entitlements` de `vendedor` ou
  `servicos` com `ativo`) **e** ≥ 1 conversa de cliente atendida pelo bot nos 30
  dias depois do primeiro resultado de valor (semiaberto, como a H10).
* **Censura:** quem entrou por um módulo há menos de 30 dias fica censurado e não
  entra no N.

### 2.4 A H12

* **Custo:** o `v_h12` do KAM-124 (`docs/modulos-entrada.md`): imagem, texto e
  mensagens por tenant, mês e módulo, convertidos ao câmbio da sessão, contra o
  preço de teste do plano do tenant. Os preços de teste são **hipóteses**
  (`hipotese_nao_validada`), e é aqui que se registam como tal.
* **«Paga por um módulo isolado»:** um ciclo da assinatura **pago**
  (`billing_cycles.estado = 'paga'`) de um plano com **um só** módulo de entrada
  (os `entrada_<modulo>`; o `entrada_completo` não conta), de uma PME da coorte
  (`v_h12_pagantes`). O ciclo não tem instante de pagamento na vista: conta-se o
  que está pago no momento da leitura.
  **A intenção declarada não conta** — «dizer que paga» não é pagar (E5,
  disposição a pagar NÃO VERIFICADA).
* **≥ 3 PMEs distintas por módulo.**

> **Divergência com a letra do bloco, decidida pelo fundador a 2026-11-24 (decisão 4: o ciclo).** O bloco dizia
> «pagamento confirmado (`payment.confirmed` ou `payment.manual_confirmed`)». Desde
> a emenda 1.96 do dicionário (KAM-059), esses dois eventos agregam por
> **encomenda**, e o pagamento de um ciclo da assinatura é o `billing.cycle_paid`,
> com o ciclo em `paga` na mesma transacção. Ler o `payment.*` mediria pagamentos
> de clientes à PME, e não da PME à KAMBÁ. Este pré-registo usa o ciclo pago,
> e a letra do critério 4 ficou emendada nesse sentido.

---

## 3. Os critérios de abate, por módulo

| | Critério | Limiar |
|---|---|---|
| (a) | Uso baixo | < 20% das PMEs da coorte usam o módulo aos 14 dias |
| (b) | Custo | > 15% do preço de teste do módulo em 2 semanas seguidas, **ou** margem negativa no mês |
| (c) | Incidente de conteúdo | ≥ 1 de gravidade **alta** (categoria bloqueada publicada, preço errado enviado, saída sem aprovação) **ou** ≥ 3 de gravidade **média** em 30 dias |
| (d) | Catálogo AI | **nunca se abate** (ADR-020: pré-requisito do onboarding); só se ajusta |

**A semana do custo é uma leitura.** O preço de teste é mensal; o racio de uma
semana é o custo do módulo nessa semana sobre o preço semanal (o mensal × 12/52),
somados sobre as PMEs da coorte cujo plano tem preço de teste para o módulo. **Só
as semanas completas contam** (a semana da leitura fica de fora), e uma semana
sem custo conta como zero: duas semanas acima separadas por uma vazia não são
«seguidas».

**Os incidentes contam-se à mão**, a partir do golden e da auditoria do KAM-125:
não há tabela de incidentes de conteúdo, e a classificação alta/média é de uma
pessoa. Entram no `decidir` por um JSON com as duas contagens de cada módulo; um
módulo sem contagem **recusa** a decisão, porque «sem contagem» não é «zero».

## 4. A regra de decisão, pré-registada

Por módulo, pela ordem:

1. **abater** se (a) ou (c);
2. **ajustar** se (b), ou se algum critério estiver a ≤ 10% do seu limiar — com
   plano e data de revisão;
3. **manter** se tudo está dentro dos limiares.

Para o `catalogo`, onde a regra diria «abater», diz «ajustar», e o critério que o
accionou fica registado na mesma.

**«A ≤ 10% do limiar» lê-se como margem relativa ao próprio limiar:** o uso está
perto quando fica abaixo de 22% (20% × 1,10); o custo quando a última semana
completa passa 13,5% (15% × 0,90). **Não se aplica aos incidentes**: são contagens
inteiras com limiares de 1 e 3, e não há contagem entre o 2 (dentro) e o 3
(abate). A letra do bloco não dizia se os 10% são relativos ou absolutos; esta
leitura foi decidida pelo fundador a 2026-11-24 (decisão 2).

**Sem coorte não há decisão.** Com N = 0 o uso não se mede: o `decidir` devolve
`dados_insuficientes`, e o relatório regista essa justificação em vez de uma
decisão. Não se fixou um N mínimo — com N pequeno o intervalo de Wilson é
largo, e é o intervalo, que sai sempre, que o diz.

**A decisão é de uma pessoa.** A regra propõe para os quatro; quem decide regista
**um módulo de cada vez**, com a sua decisão — que pode não ser a proposta, e a
proposta fica ao lado nas métricas — em `platform.module_decisions` (só de acrescentar: módulo, data, métricas com n/N e
o intervalo de Wilson 95%, critério accionado, decisão, responsável,
justificação e data de revisão). A base recusa «abater» o `catalogo` e um
«ajustar» sem data de revisão.

**O efeito de um abate é configuração.** `activo: false` no
`registry/modulos_entrada.yaml` (o AGR recusa as tools desse módulo a todos os
tenants, e as portas fora da ToolLayer deixam de o oferecer: a oferta de «melhorar
foto» e, no `orcamento`, o botão «Pedir orçamento» do Vendedor, o envio da
proposta e a janela; o dono recebe a frase estática do módulo) e o módulo fora dos
planos `entrada_*` novos, num só PR, sem migração. Os outros módulos não mudam;
no atendimento ao cliente, só desaparece o que é do próprio módulo — o pedido de
orçamento, quando é o `orcamento` que se abate. O procedimento está em
[`../../../experimento-modulos.md`](../../../experimento-modulos.md).

---

## 5. Inquérito às PMEs do Piloto (*proposta*)

Cinco perguntas, **voluntárias e com consentimento**, a fazer a cada PME do
Piloto. Os resultados só se usam **agregados**; alimentam o gatilho da D13 (App
Review aprovado **e** ≥ 3 PMEs com Página ou conta profissional) e a H12.

| # | Pergunta | Respostas |
|---|---|---|
| 1 | A loja tem Página de Facebook? | sim / não / não sei |
| 2 | A loja tem conta profissional de Instagram? | sim / não / não sei |
| 3 | Com que frequência publica nas redes sociais hoje? | nunca / menos de 1 por semana / 1 a 3 por semana / mais de 3 por semana |
| 4 | Pagaria por este módulo isolado? (uma vez por módulo) | sim / talvez / não |
| 5 | Qual o preço máximo por mês que pagaria por este módulo? (uma vez por módulo) | valor em Kz, ou «não pagaria» |

As perguntas 4 e 5 são **intenção declarada**, e não contam para a H12 (§2.4):
servem para calibrar os preços de teste, que são hipóteses.

| Pergunta | Respostas (n) | Agregado | Data |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |

---

## 6. As leituras (semanas 8, 10 e 12 do Piloto)

**Por preencher.** Cada leitura corre `experimento-modulos ler` e
`experimento-modulos reproduzir` (diferença 0 numa amostra de 5), e regista aqui
n/N, o intervalo e a decisão proposta de cada módulo. O relatório final (semana
12) **anexa-se ao Gate do Piloto como informação**, e não é dependência do
KAM-110: este experimento não bloqueia o Gate.

| Semana | H10 (n/N, Wilson 95%) | H11 (n/N, Wilson 95%) | H12 custo (por módulo) | H12 pagantes (por módulo) | Censurados | Data |
|---|---|---|---|---|---|---|
| 8 | | | | | | |
| 10 | | | | | | |
| 12 | | | | | | |

| Semana | Módulo | Decisão proposta | Critério | Decisão registada | Responsável | Revisão em |
|---|---|---|---|---|---|---|
| 12 | `catalogo` | | | | | |
| 12 | `foto` | | | | | |
| 12 | `social` | | | | | |
| 12 | `orcamento` | | | | | |

## 7. Registo de calibração dos limiares

Revisto no fim do Piloto (critério de saída do EPIC-11): valor inicial, valor
medido e decisão.

| Limiar | Valor inicial (ratificado a 2026-11-24) | Valor medido | Decisão | Data |
|---|---|---|---|---|
| H10 | ≥ 60% | | | |
| H11 | ≥ 30% | | | |
| H12 custo | ≤ 15% | | | |
| H12 pagantes | ≥ 3 por módulo | | | |
| (a) uso | < 20% | | | |
| (b) custo | > 15% em 2 semanas | | | |
| (c) incidentes | ≥ 1 alto ou ≥ 3 médios em 30 dias | | | |
| margem de ajuste | 10% | | | |

---

## 8. O que este pré-registo não decide, e os limites conhecidos

* **Os limiares e a regra de escopo são do fundador**, que os ratificou a
  2026-11-24 (versão 1.1). O inquérito do §5 e a definição de «activa o
  atendimento» não estavam entre as decisões e continuam *proposta*.
* **O `foto` não tem caminho em produção, e mede zero por construção.** Nenhum
  processo chama hoje o serviço da foto (`kamba_core.foto`): a oferta de
  «melhorar foto» do catálogo só pergunta se o módulo está activo, e o trabalho é
  o `enhance_image` do KAM-120, por ligar ao canal. Enquanto assim for, `v_h10.foto`
  é sempre falso e a regra proporia «abater» o `foto` pelo critério (a) — **por
  falta de caminho, e não por falta de uso**. A leitura do `foto` regista-se como
  dados insuficientes até haver caminho.
* **O uso da foto pode apagar-se, e o instante é aproximado (INDÍCIO):** a
  `image_jobs` não guarda quando o dono escolheu, o `atualizado_at` é o da última
  mudança da linha, e voltar ao original (`escolhida = false`) apaga o uso.
* **O canal e a vertical da H11 são os de agora, e não os do dia 30 (INDÍCIO):**
  a `tenant_channels` e os `entitlements` não guardam a história. Uma PME que
  activou e depois desligou o canal conta como não activada.
* **O plano da H12 é o actual da subscrição**, como na `v_h12`: uma PME que mudou
  de plano conta pelo de agora.
* **O `publicada` é final hoje** (o gatilho da `0050`). Se o KAM-245 vier a tirar
  da `publicada` um produto que um *screen* posterior bloqueie, esse produto deixa
  de contar como resultado de valor.
* **O off-boarding muda as métricas para trás.** A purga do encerramento apaga a
  ingestão, os trabalhos de imagem, as conversas e os canais, e deixa o tenant e os
  eventos no `events_log`: uma PME que saiu perde o uso do catálogo e da foto, e a
  resposta do bot sem conversa deixa de contar. O relatório lê-se com as PMEs que
  saíram contadas à parte.
* **A reprodução reproduz a agregação, e não as definições.** O `reproduzir` faz em
  Python a janela, a censura, a entrada e a activação a partir das linhas cruas, mas
  a coorte, o dono e o canal e a vertical actuais são os mesmos predicados das
  funções: um erro de definição comum aos dois dá diferença 0.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | 2026-11-23 | Pré-registo inicial (KAM-127), antes da primeira medição. Limiares *proposta* do `14` §2 e do bloco do KAM-127. | Equipa KAMBÁ |
| 1.1 | 2026-11-24 | Ratificação, ainda antes da primeira medição: os limiares e as janelas, a margem relativa (uso e custo), o `events_log` para o `social` e o `orcamento`, o ciclo pago da assinatura e a regra de escopo — decisões do fundador de 2026-11-24, no bloco do KAM-127. Os valores não mudam. | Equipa KAMBÁ |
