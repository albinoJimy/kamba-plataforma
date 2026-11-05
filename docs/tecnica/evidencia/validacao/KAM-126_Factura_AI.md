# Factura AI: parceiro certificado AGT, API, custo e recomendação

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — *spike* de parceiro de facturação electrónica certificado pela AGT |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-126 (EPIC-11) |
| Documento-fonte | `../E2_Pagamentos_Angola.md` §6 (§6.1, §6.2), §7, §8, §9 (perguntas 26–29); `../E3_Regulatorio_Dados.md` §2, §6, §7; `../E5_Modulos_Entrada.md` («Bloqueios e riscos», B10); `../../00_Arquitectura_Solucao.md` (ADR-004, ADR-008, D7) |
| Relacionados | [`Seguimento_APD.md`](Seguimento_APD.md), [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md), [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) |
| Instrumento de medição | `spikes/factura-ai/` (descartável; não é código de produção e não é um portão) |

> **Este relatório não valida nenhum certificado, e não pode.** A lista oficial
> actual de softwares certificados pela AGT **não foi obtida** — a de Dezembro de
> 2025, com 43 certificados, é a última de que há notícia (`../E2_Pagamentos_Angola.md` §6.2).
> Sem essa lista, todo o número de certificado que aparece abaixo é **declaração
> do fornecedor**, e nenhuma célula deste documento diz o contrário. O critério 2
> do ticket escreve a regra à letra: **CONFIRMADO só se constar da lista oficial**.
>
> **Nenhum fornecedor foi contactado, e nenhum contrato foi lido.** Contactar a
> AGT e os fornecedores, pedir chaves de teste, negociar e assinar são **actos do
> fundador**. O que este documento entrega é o questionário já escrito, as tabelas
> com as colunas que a decisão precisa, o *script* que mede o *sandbox* quando as
> chaves existirem, e a regra de decisão aplicada ao que **hoje** se sabe.
>
> **Nenhum preço foi estimado.** O preço hipotético de Factura AI é
> **NÃO VERIFICADO** e o ticket proíbe inventá-lo; o que o §6 faz em vez disso é
> inverter a conta e dizer **qual teria de ser** esse preço para a condição (c) da
> regra se verificar. Essa é uma afirmação sobre aritmética, não sobre o mercado.

---

## 1. O que este *spike* decide, e o que não decide

| Decide | Não decide |
|---|---|
| Que forma tem o pedido à AGT, e quais são as três perguntas que o desbloqueiam | **Qual é a data da Fase 2** — há conflito de fontes e só a AGT a fecha por escrito |
| Quais são os candidatos conhecidos com API, e o que falta saber de cada um | **Qual é o parceiro.** Isso é a decisão aberta **D7**, e é do fundador |
| Que predicados o *sandbox* tem de satisfazer, e como se medem | **Se a Vero/Cacimbo os satisfazem** — sem chaves de teste, nada disso foi medido contra fornecedor |
| Qual é a fórmula do custo, e qual o preço de equilíbrio da condição (c) | **Quanto custa a Vero** — modelo *freemium* sem preçário publicado |
| Que perguntas de dados pessoais e de transferência internacional têm de ter resposta antes da primeira chamada em produção | **Se há transferência** — depende de onde o parceiro aloja, e isso é NÃO VERIFICADO |

> **A KAMBÁ nunca é a emissora.** O Decreto Presidencial n.º 71/25 art. 16 põe a
> obrigação no contribuinte, e o art. 17 exige software «validado ou
> disponibilizado» pela AGT (CONFIRMADO, `../E2_Pagamentos_Angola.md` §6.1). Um
> parceiro certificado chamado por API deixa a PME como emissora e o software do
> parceiro como o software certificado. Se a KAMBÁ quisesse emitir com motor
> próprio, teria de se certificar — e o processo, o custo e o prazo disso são
> **NÃO VERIFICADOS** (§8.3).

---

## 2. Questionário à AGT

**Destinatário:** AGT — Administração Geral Tributária. **Canal:** o do KAM-104
(pedido escrito com registo de entrada) ou canal próprio do fundador. **Quem
envia:** o fundador. **O que se faz com a resposta:** registo datado no §2.2,
e as linhas do §9 que dela dependem mudam de estado.

> **Nenhuma data é prometida ao mercado sem resposta escrita.** É o critério 1 do
> ticket, e vale também para dentro de casa: o roteiro de produto não fixa marco
> nenhum na Fase 2 enquanto o §2.2 estiver vazio.

### 2.1 As três perguntas

**P1 — Lista oficial actual de softwares certificados.**

> Qual é a lista oficial e actual dos softwares de facturação certificados ou
> validados pela AGT ao abrigo do art. 17 do Decreto Presidencial n.º 71/25, com
> o número de certificado de cada um? Onde é publicada e com que periodicidade é
> actualizada? Como se verifica, caso a caso, se um número de certificado no
> formato `FE/<n>/AGT/<ano>` é válido e está em vigor?

*Porque se pergunta:* é a única forma de pôr um `CONFIRMADO` na coluna de
validação do §3. Hoje todas as células dessa coluna são `NÃO VERIFICADO`.

**P2 — Software certificado chamado por API por terceiros, em nome de várias empresas.**

> Um software de facturação certificado pela AGT pode ser invocado por via de API
> por uma entidade terceira — uma plataforma de software que não é o contribuinte
> — para emitir documentos fiscais em nome de várias empresas distintas, cada uma
> com o seu NIF, mantendo-se cada contribuinte como emissor? Em caso afirmativo:
> (a) é exigido algum registo, comunicação ou autorização prévia relativa a essa
> plataforma terceira; (b) quem responde perante a AGT pelo conteúdo do documento
> emitido; (c) o registo de estabelecimentos do art. 17 é feito pelo contribuinte
> ou pode ser feito pela plataforma em nome dele?

*Porque se pergunta:* é a **pergunta 27** de `../E2_Pagamentos_Angola.md` §9, e é
a pergunta de que todo o desenho depende. A viabilidade *técnica* está
demonstrada pela Vero (modelo multi-tenant, `organisations.create()`, **INDÍCIO**
pela documentação do fornecedor); a admissibilidade *fiscal* não está demonstrada
por fonte nenhuma. Se a resposta for negativa, não há Factura AI com parceiro —
só arquivo da factura que a PME emitiu no seu próprio software.

**P3 — Data de entrada em vigor da Fase 2.**

> Qual é a data em vigor da obrigação de facturação electrónica para os restantes
> contribuintes dos regimes geral e simplificado do IVA — 21 de Setembro de 2026
> ou 1 de Janeiro de 2027 — e qual é o diploma, com número e data, que a fixa?
> Mantém-se alguma fase transitória sem coimas?

*Porque se pergunta:* o conflito de fontes está registado em
`../E2_Pagamentos_Angola.md` §6.1 e é material. **A data de 21 de Setembro de
2026 já passou**: se estivesse em vigor, as PMEs-alvo já seriam obrigadas hoje, e
o produto estaria a ser desenhado com um atraso que ninguém mediu. Fontes
posteriores ao adiamento dão 1 de Janeiro de 2027 (**INDÍCIO forte**), e a AGT
declarou em Abril de 2026 que «o prazo não será prorrogado».

### 2.2 Registo da resposta

| Pergunta | Data de envio | Canal | Data de resposta | Resposta (resumo) | Estado |
|---|---|---|---|---|---|
| P1 — lista oficial | | | | | **não enviada** |
| P2 — API por terceiros (multi-tenant) | | | | | **não enviada** |
| P3 — data da Fase 2 | | | | | **não enviada** |

> **A tabela nasce vazia e é assim que deve nascer.** Enviar é acto humano. Se o
> prazo de resposta passar sem resposta, a célula escreve-se **«sem resposta» com
> a data** — que é informação, e diferente de uma célula em branco.

### 2.3 Questionário aos fornecedores

Mesmo texto para todos, para que as respostas sejam comparáveis. **Quem envia: o
fundador.** As onze perguntas correspondem, uma a uma, às colunas da matriz do §4
que hoje estão a `NÃO VERIFICADO`.

1. Número de certificado AGT, data de emissão, âmbito e cópia do documento de certificação.
2. Propriedade da empresa (sócios, país de registo), ano de início de actividade, número de clientes activos e existência de auditoria ou certificação de segurança.
3. O modelo multi-tenant é suportado contratualmente — uma plataforma terceira cria organizações e emite em nome delas? Que cláusula do contrato o diz?
4. Documentação da API: OpenAPI ou equivalente, lista de *endpoints*, tipos de documento suportados (factura, factura-recibo, proforma, nota de crédito, nota de débito, guia).
5. Idempotência: qual é o cabeçalho ou campo, qual a janela de retenção da chave, e o que devolve a segunda chamada com a mesma chave?
6. *Webhooks*: que eventos, que esquema de assinatura, como se obtém e roda o segredo, qual a política de *retries* e se há consulta de estado como alternativa ao *webhook*.
7. *Sandbox*: existe, as chaves de teste são distintas das de produção, e **garante-se por escrito que o ambiente de teste não submete nada à AGT**?
8. Estados assíncronos: que estados tem um documento entre a criação e a validação pela AGT, qual a latência observada, e o que acontece quando a AGT está indisponível.
9. Exportação SAF-T: formato, periodicidade, quem a submete, e se a plataforma terceira a pode obter por API.
10. Limites de taxa, SLA de disponibilidade com compensação, e canal e prazo de suporte.
11. Responsabilidade fiscal: que cláusula diz que o contribuinte é o emissor, e qual o limite de responsabilidade do fornecedor por documento emitido com erro ou não submetido.

Perguntas de preço, que o §6 precisa e que não se inventam:

12. Preçário completo e datado: por contribuinte, por documento, por volume, e o que o nível gratuito inclui e exclui.
13. O valor «inicial» inclui o primeiro ano de serviço, ou o primeiro ano é «inicial + anual»? (É a ambiguidade do §6.2, e muda o custo do ano 1 em 50%.)
14. Existe preço de parceiro ou desconto por volume para uma plataforma que traga N contribuintes? A partir de que N?

---

## 3. Ficha dos candidatos

Quatro candidatos, acima do mínimo de três do critério 2. **Todas as linhas da
coluna «Validação na lista da AGT» dizem `NÃO VERIFICADO`, e dizem-no pela mesma
razão: a lista não foi obtida.** Nenhuma delas pode dizer `CONFIRMADO` por acto
desta sessão.

| Candidato | N.º de certificado **declarado** | Validação na lista da AGT | API para terceiros | Fonte | Data da fonte |
|---|---|---|---|---|---|
| **Vero** (vero.ao) | `FE/271/AGT/2026`, declarado de 23 Jun 2026 | **NÃO VERIFICADO** — lista não obtida | **INDÍCIO** — API REST multi-tenant documentada pelo fornecedor | `https://vero.ao/` ; `https://vero.ao/developers` | 2026-10-08 |
| **CacimboERP** / Electronic Invoice Cacimbo | `FE/6/AGT/2025` | **NÃO VERIFICADO** — lista não obtida | **INDÍCIO** — «API REST» anunciada; **documentação não encontrada** | `https://feinfo.cacimboweb.com/` | 2026-10-08 |
| **SIGESC / SISGESC** | `FE/323/AGT/2026` | **NÃO VERIFICADO** — lista não obtida | **NÃO VERIFICADO** — existência de API pública não estabelecida | blogue do fornecedor (`sisgesc.net`) | 2026-08-06 |
| **XDFE** | `FE/150/AGT/2026` | **NÃO VERIFICADO** — lista não obtida | **NÃO VERIFICADO** | busca; `xdfe.info` | 2026 |

Todas as linhas vêm de `../E2_Pagamentos_Angola.md` §6.2, que já as marca como
**INDÍCIO** por serem declaração do fornecedor.

### 3.1 Propriedade e continuidade do fornecedor

As duas colunas que o critério 2 pede e que **nenhuma fonte consultada tem**.
Ficam escritas com a pergunta que as preenche, e vazias até haver resposta.

| Candidato | Propriedade (sócios, país de registo) | Ano de início | Clientes activos | Risco de descontinuidade |
|---|---|---|---|---|
| Vero | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** |
| CacimboERP | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** |
| SIGESC / SISGESC | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** |
| XDFE | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** | **NÃO VERIFICADO** |

> **Dezasseis células vazias não são desleixo: são a medida de quanto falta.**
> Preenchem-se com a pergunta 2 do §2.3 e com uma consulta ao registo comercial —
> e um fornecedor cuja propriedade não se consegue estabelecer é, por si, um
> achado para a condição (a) da regra do §8.

### 3.2 Candidatos descartados e porquê

| Nome | Porque não entra na ficha |
|---|---|
| Cegid (Primavera, PHC, Vendus), Odoo (localização angolana), SAP, ISSXXI, EDICOM | Referidos como certificados ou «preparados», mas **API de integração para terceiros NÃO VERIFICADA**; nenhuma fonte os liga ao modelo multi-tenant |
| Gestwin, Moloni Angola | Sem fonte sobre certificação nem sobre API — **NÃO VERIFICADO** em ambos os eixos |
| Portal do Contribuinte da AGT | Sem API; e o limite de 300 documentos/ano (**INDÍCIO**) exclui-o como caminho de plataforma |
| MoMenu | Anuncia factura com SAF-T, mas é produto vertical e não fornecedor de API — **INDÍCIO** de que o modelo existe, não um candidato |

---

## 4. Matriz de adequação

Treze predicados, um por coluna do critério 3. A legenda é a da casa:
**SIM/NÃO** quando há fonte, **INDÍCIO** quando a fonte é o fornecedor a
declarar-se, **NV** para NÃO VERIFICADO. Nenhuma célula foi inferida de outra.

| # | Predicado | Vero | CacimboERP | SIGESC | XDFE |
|---|---|---|---|---|---|
| 1 | **Multi-tenant** — uma organização por PME, emissão em nome dela | INDÍCIO — `organisations.create()`, `POST /v1/organisations/{ORG_ID}/invoices` | NV | NV | NV |
| 2 | **Idempotência** — chave de pedido, repetição não duplica | INDÍCIO — `idempotencyKey` documentada; janela de retenção **NV** | NV | NV | NV |
| 3 | ***Webhooks* assinados** | INDÍCIO — `invoice.issued`, `invoice.cancelled`, `X-Vero-Signature` HMAC-SHA256 | NV | NV | NV |
| 4 | ***Sandbox* que não submete à AGT** | INDÍCIO — declarado; chaves `vero_test_sk_…` distintas das de produção. **Garantia por escrito: NV** | NV | NV | NV |
| 5 | **Proformas** | INDÍCIO — documentado | NV | NV | NV |
| 6 | **Factura-recibo após pagamento confirmado** | NV — proformas e notas documentadas; o tipo factura-recibo **não** aparece nomeado | NV | NV | NV |
| 7 | **Notas de crédito** | INDÍCIO — notas de crédito/débito documentadas | NV | NV | NV |
| 8 | **Estados assíncronos** — «pendente» até validação da AGT | NV no fornecedor. Latência de validação **≈ 30 min** é **INDÍCIO** de imprensa, não do fornecedor | NV | NV | NV |
| 9 | **Exportação SAF-T** | NV | NV | NV | NV |
| 10 | **Limites de taxa** | NV | NV | NV | NV |
| 11 | **SLA** com compensação | NV | NV | NV | NV |
| 12 | **SDK** | INDÍCIO — Node/TypeScript | NV | NV | NV |
| 13 | **Termos de responsabilidade fiscal** — a PME é a emissora | NV — é consequência do art. 16, não cláusula lida. **Não ler contratos é fronteira desta sessão** | NV | NV | NV |

**Leitura da matriz, e é incómoda.** De 52 células, **7 têm INDÍCIO e 45 estão a
NÃO VERIFICADO**; nenhuma está a SIM. Os 7 INDÍCIOS são todos da Vero e todos da
mesma fonte — a página de desenvolvedores do próprio fornecedor, lida uma vez, a
2026-10-08. Três colunas inteiras estão vazias. **A Vero não aparece melhor por
ser melhor: aparece melhor por ser a única que publicou documentação.** Essa
assimetria é de informação, não de produto, e confundi-las seria exactamente o
defeito que este relatório existe para evitar.

Os predicados 6, 8, 9, 10, 11 e 13 estão a NV **até na Vero** — e são os seis que
decidem se o fluxo de WhatsApp pode emitir sem bloquear, se a PME cumpre o SAF-T
do art. 25, e quem paga quando um documento sai errado.

---

## 5. Teste de *sandbox*

O critério 4 pede sete predicados medidos: criar organização, emitir factura,
emitir proforma, emitir nota de crédito, repetir com a mesma `idempotencyKey` 2×
e obter **um** documento, e verificar a assinatura do *webhook*.
**Mediram-se todos — contra um *mock*.** Nenhum foi medido contra fornecedor,
porque não há chaves de teste e pedi-las é contacto.

### 5.1 O instrumento

`spikes/factura-ai/`, descartável, biblioteca padrão do Python, sem dependências.
Dois ficheiros fazem o trabalho: `provedor_mock.py` é um servidor HTTP que
implementa o contrato, e `sandbox.py` é o cliente que mede os sete predicados
contra qualquer base URL. O *mock* é o alvo por omissão; apontar o `sandbox.py` a
um fornecedor é mudar uma variável de ambiente, e é o que se faz quando as chaves
existirem.

> **O *mock* foi escrito para poder reprovar.** Um falso que decide pelo nome do
> ensaio não mede predicado nenhum: fica verde com a implementação apagada. Por
> isso o *mock* guarda de facto a `idempotencyKey` e devolve o documento anterior,
> e assina de facto com HMAC-SHA256 sobre o corpo. E por isso o *script* tem um
> **canário** (`sandbox.py --canario`) que estraga o *mock* de seis maneiras — a
> idempotência que ignora a chave, a assinatura calculada sobre outro corpo, o
> segredo errado, a proforma numerada como factura, a nota de crédito sem
> documento de origem, e o *sandbox* a submeter à AGT — e **exige que o ensaio
> correspondente fique vermelho em cada uma**. Um ensaio que não reprova quando
> devia não é evidência.

### 5.2 Resultado contra o *mock*

Execução de 2026-11-05, `python spikes/factura-ai/sandbox.py` e
`python spikes/factura-ai/sandbox.py --canario`.

| # | Predicado do critério 4 | Resultado contra o *mock* | Canário correspondente |
|---|---|---|---|
| 1 | Criar organização (uma por PME) | **verde** | — |
| 2 | Emitir factura | **verde** | — |
| 3 | Emitir proforma, sem numeração fiscal | **verde** | `proforma-numerada` → vermelho, como se exige |
| 4 | Emitir nota de crédito sobre a factura | **verde** | `nota-sem-origem` → vermelho, como se exige |
| 5 | Mesma `idempotencyKey` 2× → **um** documento | **verde** | `idempotencia-ignorada` → vermelho, como se exige |
| 6 | Assinatura do *webhook* verificada | **verde** | `assinatura-de-outro-corpo`, `segredo-errado` → vermelho, como se exige |
| 7 | *Sandbox* não submete à AGT | **verde** | `sandbox-submete` → vermelho, como se exige |

**Seis canários, seis vermelhos.** O que isto demonstra é que os sete ensaios
medem o que dizem medir. **O que não demonstra é absolutamente nada sobre a
Vero, a Cacimbo, a SIGESC ou a XDFE** — um *mock* que eu escrevi passa nos
ensaios que eu escrevi, e seria estranho se não passasse.

### 5.3 O que falta, e o que custa

| Passo | Quem | Pré-requisito |
|---|---|---|
| Obter chaves de teste do *sandbox* | fundador | contacto com o fornecedor |
| Garantia **por escrito** de que o *sandbox* não submete à AGT | fundador | contacto com o fornecedor |
| Correr `sandbox.py` contra o *sandbox* do fornecedor e anexar a saída ao §5.2 | sessão seguinte | as duas linhas acima |

O teste cabe nos «≤ 2 dias» do critério 4 — o instrumento está escrito e o
trabalho que resta é correr e ler. **Dados sintéticos, sem NIF reais:** os NIFs
que o *script* usa têm a forma `SINTETICO-<n>` e não a de um NIF angolano, de
propósito, para que nenhum deles possa coincidir com um contribuinte real; o
`spikes/factura-ai/README.md` escreve essa regra e a de apagar as chaves no fim.

---

## 6. Modelo de custo

### 6.1 Fórmula e unidades

A unidade é **Kz por PME por mês**, porque é a única em que o custo do parceiro
se compara com o preço de um módulo. `N` é o número de PMEs; `I` o valor inicial
por contribuinte (Kz); `R` a renovação anual por contribuinte (Kz/ano).

```text
Custo_ano1(N)    = N × I                      [Kz]      leitura A
Custo_ano1(N)    = N × (I + R)                [Kz]      leitura B
Custo_regime(N)  = N × R                      [Kz/ano]  a partir do 2.º ano
Custo_PME_mes    = R / 12                     [Kz/PME/mês]   em regime
```

> **As leituras A e B não são um detalhe de apresentação.** «50.000 Kz inicial +
> 50.000 Kz/ano» pode querer dizer que o inicial inclui o primeiro ano (A) ou que
> o primeiro ano é a soma dos dois (B). A diferença no ano 1 é de **50%**, e a
> fonte é uma página de preços, não um contrato. A ambiguidade é **NÃO
> VERIFICADA** e está na pergunta 13 do §2.3. Abaixo mostram-se as duas.

### 6.2 CacimboERP — a única coluna com preços datados

Escalões e valores de `https://feinfo.cacimboweb.com/`, lidos a **2026-10-08**,
registados em `../E2_Pagamentos_Angola.md` §6.2 como **INDÍCIO**.

| Escalão | `I` (Kz) | `R` (Kz/ano) | `Custo_PME_mes` em regime (Kz) |
|---|---|---|---|
| Independentes | 50 000 | 50 000 | 4 167 |
| Micro | 250 000 | 125 000 | 10 417 |
| Pequena | 500 000 | 250 000 | 20 833 |
| Média | 1 000 000 | 500 000 | 41 667 |
| Grande | 2 000 000 | 1 000 000 | 83 333 |

Para 10, 50 e 200 PMEs, no escalão **Micro** (o mais provável para a base-alvo, e
a escolha do escalão é **hipótese de planeamento**, não facto):

| N | Ano 1, leitura A (Kz) | Ano 1, leitura B (Kz) | Em regime (Kz/ano) | Em regime (Kz/mês) |
|---|---|---|---|---|
| 10 | 2 500 000 | 3 750 000 | 1 250 000 | 104 167 |
| 50 | 12 500 000 | 18 750 000 | 6 250 000 | 520 833 |
| 200 | 50 000 000 | 75 000 000 | 25 000 000 | 2 083 333 |

> **O custo é linear em `N`, e isso é o achado.** O preçário da Cacimbo é **por
> contribuinte**: 200 PMEs custam 200 vezes uma. Não há desconto de volume
> documentado — **NÃO VERIFICADO**, pergunta 14 do §2.3 — e sem ele a facturação
> não tem economia de escala nenhuma, ao contrário de todo o resto da plataforma.
> **Um preçário por contribuinte é um custo variável puro**: entra directamente na
> margem de cada PME e não dilui com o crescimento.

### 6.3 Vero — a coluna que não se preenche

| N | Ano 1 | Em regime |
|---|---|---|
| 10 | **NÃO VERIFICADO** | **NÃO VERIFICADO** |
| 50 | **NÃO VERIFICADO** | **NÃO VERIFICADO** |
| 200 | **NÃO VERIFICADO** | **NÃO VERIFICADO** |

A Vero declara modelo ***freemium*** (**INDÍCIO**, `vero.ao`), e não foi
encontrado preçário publicado. **Um nível gratuito sem limites publicados não é
um preço**: não se sabe quantos documentos, quantas organizações nem quanto tempo
inclui, e a diferença entre «grátis» e «grátis até 50 documentos» é toda a
diferença do modelo. A célula fica vazia até à pergunta 12 do §2.3.

### 6.4 Comparação com o preço de Factura AI, sem o inventar

O critério 5 pede a comparação e proíbe inventar o preço; a condição (c) da regra
do §8 pede `Custo_PME_mes ≤ 10% × P`, onde `P` é o preço do módulo por PME por
mês. **Inverte-se a desigualdade e a conta faz-se sem `P`:**

```text
(c) verifica-se  ⟺  P ≥ Custo_PME_mes / 0,10  =  10 × Custo_PME_mes
```

| Parceiro / escalão | `Custo_PME_mes` (Kz) | **`P` mínimo** para (c) se verificar (Kz/PME/mês) |
|---|---|---|
| Cacimbo — Independentes | 4 167 | **41 667** |
| Cacimbo — Micro | 10 417 | **104 167** |
| Cacimbo — Pequena | 20 833 | **208 333** |
| Vero | NÃO VERIFICADO | **indeterminado** |

> **Isto é a conta mais útil do relatório, e também a mais desconfortável.** Com a
> Cacimbo no escalão Micro, a condição (c) só se verifica se Factura AI for
> vendido a **≥ 104 167 Kz por PME por mês**. Não digo que esse preço é alto nem
> baixo — **o preço de Factura AI é NÃO VERIFICADO e não o invento**. Digo que a
> condição (c) deixou de ser uma incógnita e passou a ser uma **pergunta de preço
> ao fundador**, com um número exacto do lado de lá: *o módulo vai custar ao menos
> isto?* Se a resposta for não, (c) falha com o preçário de hoje, e o caminho é
> negociar preço de parceiro (pergunta 14) ou mudar de parceiro.

### 6.5 A assinatura da própria KAMBÁ

`../E2_Pagamentos_Angola.md` §7 regista que **a própria assinatura SaaS da KAMBÁ
tem de ser facturada com software certificado** pela AGT, se a entidade estiver no
regime geral ou simplificado (**INDÍCIO**), e que o art. 6 do DP 71/25 exige
recibo nos pagamentos, salvo factura-recibo.

**É o mesmo problema e pode ser o mesmo parceiro — e esse é um argumento de
custo que o critério 5 manda registar.** A KAMBÁ é **um** contribuinte: no
preçário da Cacimbo, um escalão único, independente de `N`. A mesma integração
serve os dois casos de uso, e o caso de uso da própria casa tem a vantagem de não
depender da resposta P2 da AGT — aqui a KAMBÁ **é** o contribuinte e não emite em
nome de ninguém.

| Caso de uso | Contribuintes | Depende da resposta P2? | Custo |
|---|---|---|---|
| Factura AI (emitir pela PME) | `N` | **sim** — é a pergunta que o viabiliza | linear em `N` (§6.2) |
| Assinatura da KAMBÁ | 1 | **não** | um escalão, `I` + `R` (§6.2) |

> **Consequência de desenho:** se P2 vier negativa, a integração com parceiro
> certificado **não morre** — perde o caso de uso Factura AI e fica com o da
> assinatura própria, que é obrigatório de qualquer maneira. O caminho de
> facturar a assinatura é, por isso, o menos arriscado dos dois, e não precisa de
> esperar por D7.

### 6.6 Revisão da fórmula por segunda pessoa

Os «Testes Requeridos» do ticket pedem revisão do modelo de custo — fórmula e
unidades — por uma segunda pessoa. **Não está feita, e não pode ser feita por
quem escreveu as contas.**

| Item a rever | Estado |
|---|---|
| Unidades de `Custo_PME_mes` (Kz/PME/mês) e a divisão por 12 | **pendente de revisor** |
| As duas leituras `I`/`R` e a diferença de 50% no ano 1 | **pendente de revisor** |
| A inversão da condição (c) e os valores de `P` mínimo do §6.4 | **pendente de revisor** |
| A escolha do escalão Micro como hipótese de planeamento | **pendente de revisor** |

Credor: **Responsável de Produto** (papel, não sessão).

---

## 7. Dados pessoais, subprocessamento e transferência internacional

### 7.1 Que dados fiscais existem, e quais são pessoais

| Dado do documento fiscal | É dado pessoal? | Porquê |
|---|---|---|
| NIF e nome do contribuinte emissor (a PME) | **depende** | Empresário em nome individual: **sim**. Sociedade: não, mas o representante pode aparecer |
| NIF e nome do cliente | **depende** | Cliente particular: **sim** (**INDÍCIO** — inferência do art. 4 da Lei 22/11) |
| Morada do cliente | **sim**, quando é particular | |
| Linhas do documento (artigos, quantidades, valores) | não, isoladamente | Mas revelam hábitos de consumo ligados a um nome |
| Código de validação (ETD) e assinatura digital | não | **INDÍCIO** — `../E2_Pagamentos_Angola.md` §6.1 |

> **Uma factura a um particular leva o nome e o NIF de uma pessoa.** O caminho de
> Factura AI trata dados pessoais por natureza, e não por acidente de desenho. A
> minimização possível é de conteúdo, não de existência: **a plataforma envia ao
> parceiro só os campos que o documento fiscal exige**, e nunca o `contact_id`,
> o número de WhatsApp nem o histórico da conversa.

### 7.2 As três perguntas do critério 6

| Pergunta | Resposta hoje | Como se fecha |
|---|---|---|
| **Onde residem os dados fiscais?** | **NÃO VERIFICADO** para os quatro candidatos. Nenhuma fonte diz onde a Vero, a Cacimbo, a SIGESC ou a XDFE alojam | Pergunta ao fornecedor (§2.3 p. 2), com o país e a região por escrito |
| **O parceiro é subprocessador?** | **NÃO VERIFICADO**, e a pergunta anterior a esta é *quem é o responsável do tratamento*. Se a PME é a emissora (art. 16), a PME é a responsável, a KAMBÁ é subcontratante e o parceiro é **subsubcontratante** — leitura por inferência, **não** confirmada por parecer | Pergunta ao parecer jurídico (`Pacote_Parecer_Juridico.md`), e cláusula no contrato do parceiro |
| **Há transferência internacional?** | **NÃO VERIFICADO**, por depender da primeira. Se o alojamento for fora de Angola, **há** — os arts. 33/34 da Lei 22/11 pedem notificação para destino adequado e autorização para destino não adequado (CONFIRMADO, `../E3_Regulatorio_Dados.md` §2) | Resposta do fornecedor, depois procedimento APD e `apd_ref` |

### 7.3 `apd_ref` e o que ele trava

ADR-008: **nenhum dado pessoal de produção sai de Angola sem a notificação ou
autorização da APD aplicável.** O inventário de subprocessadores pede, por
fornecedor, um `apd_ref` na forma `APD-<AAAA>-<NNNNN>`.

| Fornecedor | País de alojamento | Destino adequado? | Procedimento | `apd_ref` |
|---|---|---|---|---|
| Vero | **NÃO VERIFICADO** | — | — | **vazio** |
| CacimboERP | **NÃO VERIFICADO** | — | — | **vazio** |
| SIGESC / SISGESC | **NÃO VERIFICADO** | — | — | **vazio** |
| XDFE | **NÃO VERIFICADO** | — | — | **vazio** |

> **Regra de bloqueio, e esta é dura:** nenhuma chamada a um destes fornecedores
> com dados de produção antes de a linha respectiva ter país **e** `apd_ref`, ou
> a confirmação escrita de que o alojamento é em Angola. Um fornecedor angolano a
> alojar fora de Angola é transferência internacional igual — é a quarta condição
> **R4** que o `Alojamento_Cotacoes.md` propõe, e aplica-se aqui pela mesma razão.
> O seguimento vive em `Seguimento_APD.md`.
>
> **Isto não trava o *sandbox*.** Dados sintéticos não são dados pessoais, e o
> `spikes/factura-ai/` usa NIFs da forma `SINTETICO-<n>`. O que trava é a
> primeira factura real.

### 7.4 Orçamento não é factura — pergunta ao parecer

`../E5_Modulos_Entrada.md` («Bloqueios e riscos», B10) registou o risco: um orçamento ou proforma do
módulo de Orçamento expresso **pode ser confundido com documento fiscal**, e a
plataforma não é software validado pela AGT. Mitigação já desenhada: rótulo
«Orçamento — não é factura» e ausência de numeração fiscal (**INDÍCIO**).

Entra na lista de perguntas ao parecer jurídico (`Pacote_Parecer_Juridico.md`),
nesta forma:

> Um documento emitido por uma plataforma de software não certificada, intitulado
> «Orçamento», sem numeração fiscal e com os valores e o prazo de validade,
> enviado por WhatsApp a um cliente, pode ser qualificado como documento
> equivalente a factura para efeitos do Decreto Presidencial n.º 71/25? Que
> elementos o desqualificam, e que elementos o qualificariam? O rótulo «não é
> factura» é bastante, ou é preciso mais?

*Porque importa:* se a resposta for que o orçamento pode ser qualificado, o
módulo de Orçamento expresso **já hoje** precisa de parceiro certificado — e
Factura AI deixa de ser Fase 2 para passar a ser pré-requisito de um módulo do
Piloto. É a pergunta deste relatório com maior capacidade de mudar o roteiro, e a
resposta não é minha.

---

## 8. Recomendação

### 8.1 A regra, como o critério 7 a pré-registou

Marcada ***proposta***, como o ticket a marca. **Avançar para o epic de Clusters
só se as quatro condições se verificarem:**

| | Condição | Como se mede |
|---|---|---|
| **(a)** | Certificado **validado na lista da AGT** ou confirmado por escrito | Resposta P1, ou documento de certificação do fornecedor |
| **(b)** | API **multi-tenant** com idempotência e *webhooks* | `sandbox.py` verde contra o *sandbox* do fornecedor (§5.3) |
| **(c)** | Custo por PME **≤ 10%** do preço de Factura AI | `Custo_PME_mes` do §6.2 contra o `P` do §6.4 |
| **(d)** | Caminho **APD** definido | País de alojamento e `apd_ref`, ou alojamento em Angola por escrito (§7.3) |

Caso contrário: **adiar** ou **parceiro alternativo**.

### 8.2 A regra aplicada ao que hoje se sabe

| Condição | Estado | Porquê |
|---|---|---|
| (a) certificado validado | **FALHA** | Lista oficial não obtida; os quatro certificados são auto-declarados (§3) |
| (b) API multi-tenant | **NÃO MEDIDO** | Vero com 3 INDÍCIOS de documentação própria; zero medições contra fornecedor (§5) |
| (c) custo ≤ 10% do preço | **NÃO MENSURÁVEL** | `P` é NÃO VERIFICADO; o §6.4 dá o `P` mínimo, não a verificação |
| (d) caminho APD | **FALHA** | País de alojamento NÃO VERIFICADO nos quatro; `apd_ref` vazio nos quatro (§7.3) |

> ## Recomendação: **adiar**.
>
> E adiar **pela própria regra**, não por juízo meu: (a) e (d) falham, (b) não foi
> medido e (c) não é mensurável. Nenhuma das quatro se verifica, e a regra diz o
> que fazer quando isso acontece. **Não há aqui um empate a desfazer nem uma
> decisão de produto a tomar** — há quatro condições pré-registadas e nenhuma
> satisfeita.
>
> **Adiar não é parar.** O que desbloqueia é curto e está todo em actos humanos:
> as três perguntas à AGT (§2.1), as catorze aos fornecedores (§2.3), e as chaves
> de teste (§5.3). Com P1, P2 e as chaves, (a), (b) e (d) tornam-se mensuráveis em
> dias, e (c) torna-se uma pergunta de preço com um número exacto (§6.4).

### 8.3 Certificação própria, como opção

| Item | Estado |
|---|---|
| Processo de certificação de software próprio junto da AGT | **NÃO VERIFICADO** — pergunta 28 de `../E2_Pagamentos_Angola.md` §9 |
| Custo | **NÃO VERIFICADO** |
| Prazo | **NÃO VERIFICADO** |
| Documento técnico do Decreto Executivo n.º 683/25 (esquemas, *endpoints* de comunicação em tempo real) | existe e é **CONFIRMADO**; **não foi obtido** |

> **Fica registada como opção e nada mais.** Três NÃO VERIFICADOS não fazem uma
> alternativa, fazem uma pergunta. E a comparação com o caminho de parceiro só
> existe depois da resposta 28; antes dela, qualquer frase sobre «fazer nós» é
> especulação com cara de plano.

### 8.4 Insumo para D7

**D7** — «Parceiro de factura AGT (Vero, CacimboERP, outros)», gatilho
«Confirmação escrita AGT sobre 2027 e certificação», horizonte «Clusters»
(`../../00_Arquitectura_Solucao.md` §13.3).

| O que este relatório entrega a D7 | O que D7 continua a precisar |
|---|---|
| Quatro candidatos com certificado declarado e estado de validação por candidato (§3) | A lista oficial da AGT (P1) |
| A matriz de 13 predicados, com 45 de 52 células a NÃO VERIFICADO (§4) | As respostas do §2.3, que são exactamente essas células |
| O modelo de custo com preços datados da Cacimbo e o `P` mínimo da condição (c) (§6) | O preçário da Vero (p. 12) e o preço do módulo |
| A regra aplicada, a dar **adiar** (§8.2) | P1, P2, P3 e as chaves de teste |
| Que a assinatura da própria KAMBÁ é o mesmo problema sem depender de P2 (§6.5) | Decisão do fundador sobre a facturar com parceiro |
| Que o orçamento do módulo pode mudar o horizonte de D7 (§7.4) | O parecer jurídico sobre B10 |

> **D7 não fecha aqui, e o gatilho dela diz porquê:** pede confirmação escrita da
> AGT, e escrever à AGT é acto do fundador. Este relatório é o **insumo** que o
> ticket pede, não a decisão.

---

## 9. Estado por afirmação

Todas as afirmações materiais deste relatório, com o estado final de cada uma. É
a tabela que a caixa de DoD «nenhum NÃO VERIFICADO tratado como facto» exige.

| # | Afirmação | Estado | Fonte | Data |
|---|---|---|---|---|
| 1 | Facturação electrónica obrigatória; DP 71/25 art. 16 põe a obrigação no contribuinte | **CONFIRMADO** | `../E2_Pagamentos_Angola.md` §6.1 | 2025-03-20 |
| 2 | Art. 17: software «validado ou disponibilizado» pela AGT | **CONFIRMADO** | `../E2_Pagamentos_Angola.md` §6.1 | 2025-03-20 |
| 3 | Plataforma que emita por conta da PME sem ser software certificado **não é válida** | **CONFIRMADO** | `../E2_Pagamentos_Angola.md` §6.1; `../E3_Regulatorio_Dados.md` §6 | 2026 |
| 4 | DE 683/25 fixa a estrutura de dados e as especificações técnicas | **CONFIRMADO** | `../E2_Pagamentos_Angola.md` §6.1 | 2025-08-22 |
| 5 | Fase 1 (grandes contribuintes e fornecedores do Estado): 1 Jan 2026 | **CONFIRMADO** | `../E2_Pagamentos_Angola.md` §6.1 | 2026 |
| 6 | Fase 2 (regimes geral e simplificado): 1 Jan 2027 | **INDÍCIO forte** — sem diploma de 2026 lido | `../E2_Pagamentos_Angola.md` §6.1 | 2026 |
| 7 | Fontes alternativas dão 21 Set 2026 para a Fase 2 | **INDÍCIO (conflito)** | `../E2_Pagamentos_Angola.md` §6.1 | 2025-04 / 2026-09 |
| 8 | **Qual das duas datas está em vigor** | **NÃO VERIFICADO** — P3 | — | — |
| 9 | A AGT divulgou lista com 43 certificados em Dez 2025 | **CONFIRMADO** (existência) | `../E2_Pagamentos_Angola.md` §6.2 | 2025-12 |
| 10 | **Lista oficial actual de softwares certificados** | **NÃO VERIFICADO** — P1 | — | — |
| 11 | Vero declara `FE/271/AGT/2026` | **INDÍCIO** — declaração do fornecedor | `vero.ao` | 2026-10-08 |
| 12 | CacimboERP declara `FE/6/AGT/2025` | **INDÍCIO** | `feinfo.cacimboweb.com` | 2026-10-08 |
| 13 | SIGESC declara `FE/323/AGT/2026` | **INDÍCIO** | blogue do fornecedor | 2026-08-06 |
| 14 | XDFE declara `FE/150/AGT/2026` | **INDÍCIO** | busca; `xdfe.info` | 2026 |
| 15 | **Qualquer um destes certificados está validado na lista da AGT** | **NÃO VERIFICADO** nos quatro | — | — |
| 16 | Vero: API multi-tenant com `organisations.create()`, idempotência, *webhooks* HMAC-SHA256, *sandbox* que não submete | **INDÍCIO** — documentação do fornecedor, leitura única | `vero.ao/developers` | 2026-10-08 |
| 17 | CacimboERP tem «API REST» | **INDÍCIO**; documentação **não encontrada** | `feinfo.cacimboweb.com` | 2026-10-08 |
| 18 | SIGESC e XDFE têm API pública para terceiros | **NÃO VERIFICADO** | — | — |
| 19 | Um software certificado **pode** ser chamado por API por terceiros em nome de várias empresas | **NÃO VERIFICADO** — P2. Viabilidade técnica é **INDÍCIO** (Vero); admissibilidade fiscal não tem fonte | — | — |
| 20 | Latência de validação da AGT ≈ 30 min | **INDÍCIO** — imprensa | `../E2_Pagamentos_Angola.md` §6.1 | 2026-02-25 |
| 21 | Preços por escalão da CacimboERP (§6.2) | **INDÍCIO** — página de preços do fornecedor | `feinfo.cacimboweb.com` | 2026-10-08 |
| 22 | O «inicial» da Cacimbo inclui o primeiro ano de serviço | **NÃO VERIFICADO** — p. 13; muda o ano 1 em 50% | — | — |
| 23 | Vero é *freemium* | **INDÍCIO** | `vero.ao` | 2026-10-08 |
| 24 | **Preço da Vero** | **NÃO VERIFICADO** — sem preçário publicado | — | — |
| 25 | Existe desconto por volume ou preço de parceiro em qualquer candidato | **NÃO VERIFICADO** — p. 14 | — | — |
| 26 | **Preço hipotético de Factura AI** | **NÃO VERIFICADO** — e não se inventa | — | — |
| 27 | Com Cacimbo Micro, (c) exige `P ≥ 104 167` Kz/PME/mês | **CONFIRMADO** como aritmética sobre a afirmação 21, que é INDÍCIO | §6.4 | 2026-11-05 |
| 28 | A assinatura SaaS da própria KAMBÁ tem de ser facturada com software certificado | **INDÍCIO** | `../E2_Pagamentos_Angola.md` §7 | 2025 |
| 29 | Os sete predicados do critério 4 passam **contra o *mock*** | **CONFIRMADO** — medido a 2026-11-05 | §5.2; `spikes/factura-ai/` | 2026-11-05 |
| 30 | Os seis canários ficam vermelhos quando o *mock* é estragado | **CONFIRMADO** — medido a 2026-11-05 | §5.2 | 2026-11-05 |
| 31 | **Qualquer fornecedor satisfaz os sete predicados** | **NÃO VERIFICADO** — nenhuma medição contra fornecedor | — | — |
| 32 | **Onde residem os dados fiscais** de cada candidato | **NÃO VERIFICADO** nos quatro | — | — |
| 33 | **Há transferência internacional** | **NÃO VERIFICADO** — depende da afirmação 32 | — | — |
| 34 | Transferência para fora de Angola exige notificação (destino adequado) ou autorização (não adequado) | **CONFIRMADO** — arts. 33/34 da Lei 22/11 | `../E3_Regulatorio_Dados.md` §2 | 2011 |
| 35 | Não há lista pública de países adequados da APD | **CONFIRMADO** quanto à ausência nas fontes consultadas | `../E3_Regulatorio_Dados.md` §2 | 2026 |
| 36 | Uma factura a cliente particular contém dados pessoais | **INDÍCIO** — inferência do art. 4 da Lei 22/11 | §7.1 | — |
| 37 | O parceiro é subsubcontratante, sendo a PME a responsável do tratamento | **INDÍCIO** — inferência; sem parecer | §7.2 | — |
| 38 | Um orçamento rotulado «não é factura» e sem numeração fiscal não é documento equivalente a factura | **NÃO VERIFICADO** — pergunta ao parecer (§7.4) | `../E5_Modulos_Entrada.md` («Bloqueios e riscos», B10) | 2026 |
| 39 | Prazo de conservação de facturas (n.º de anos) | **NÃO VERIFICADO** | `../E3_Regulatorio_Dados.md` §6 | — |
| 40 | Processo, custo e prazo de certificação de software próprio | **NÃO VERIFICADO** — p. 28 | — | — |
| 41 | A regra do §8.1, aplicada ao que hoje se sabe, dá **adiar** | **CONFIRMADO** — as quatro condições e os seus estados estão no §8.2 | §8.2 | 2026-11-05 |

**Contagem: 41 afirmações — 12 CONFIRMADO, 14 INDÍCIO (1 deles «forte», 1
«conflito»), 15 NÃO VERIFICADO.** Nenhum NÃO VERIFICADO é usado como premissa de
nenhuma conclusão deste relatório; os quatro que mais pesam — a data da Fase 2, a
lista da AGT, a resposta P2 e o preço de Factura AI — são precisamente as razões
pelas quais a recomendação é **adiar** e não «avançar».

---

## 10. Caixas devolvidas, com credor

| O que ficou por fazer | Porquê | Credor |
|---|---|---|
| Enviar as três perguntas à AGT e registar a resposta (§2.2) | Contactar a AGT é acto do fundador | **fundador** |
| Enviar as catorze perguntas aos fornecedores (§2.3) | Contactar fornecedores é acto do fundador | **fundador** |
| Preencher propriedade e continuidade dos quatro candidatos (§3.1) | Precisa das respostas acima e de consulta ao registo comercial | **fundador** |
| Obter chaves de teste e a garantia escrita de que o *sandbox* não submete à AGT (§5.3) | Pedir chaves é contacto com fornecedor | **fundador** |
| Correr `sandbox.py` contra o *sandbox* do fornecedor | Depende da linha acima | **fundador** (desbloqueia), depois sessão de execução |
| Ler os contratos e as cláusulas de responsabilidade fiscal (§4, predicado 13) | Ler e aceitar contratos é fronteira desta sessão | **fundador** |
| Revisão da fórmula de custo por segunda pessoa (§6.6) | Quem escreveu as contas não as revê | **Responsável de Produto** |
| Levar a pergunta B10 ao parecer jurídico (§7.4) | O pacote do parecer é enviado por acto humano | **fundador** |
| Decidir D7 | É decisão do fundador, e o gatilho dela é a resposta da AGT | **fundador** |
| Entregar a recomendação ao Responsável de Produto | Acto de entrega, fora do alcance de uma sessão | **fundador** |

> **Todos os credores são pessoas ou papéis, nenhum é uma sessão.** Fundir este PR
> arquiva a sessão que o escreveu; um combinado cujo credor fosse «a sessão» morria
> no acto da fusão.

---

## 11. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto (recebe a recomendação) | | | |
| Engenheiro de Plataforma (revê a matriz do §4) | | | |
| Responsável de Segurança (revê o §7) | | | |
| Fundador (decide D7, e é o credor do §10) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-126. Questionário à AGT com as três perguntas que desbloqueiam o ticket (lista oficial, API por terceiros em nome de várias empresas — a pergunta 27 de `../E2_Pagamentos_Angola.md` §9 —, e a data da Fase 2), questionário de catorze perguntas aos fornecedores, ficha de **quatro** candidatos acima do mínimo de três, e matriz de treze predicados onde **45 das 52 células estão a NÃO VERIFICADO** e nenhuma está a SIM. Nenhum certificado afirmado como validado: a lista oficial da AGT não foi obtida, e a coluna de validação diz NÃO VERIFICADO nas quatro linhas. *Script* de *sandbox* em `spikes/factura-ai/` com os sete predicados do critério 4 medidos contra um *mock* e **seis canários a provar que os ensaios reprovam quando devem** — e com a ressalva de que nada disso mede fornecedor nenhum. Modelo de custo com a única coluna de preços datados que existe (CacimboERP), as duas leituras do valor «inicial» que diferem **50%** no ano 1, e a inversão da condição (c) a dar o `P` mínimo de **104 167 Kz/PME/mês** no escalão Micro — sem inventar o preço de Factura AI, que fica NÃO VERIFICADO. Registado que o preçário por contribuinte é **custo variável puro, linear em `N`, sem economia de escala**, e que a facturação da assinatura da própria KAMBÁ é o mesmo problema **sem depender da resposta P2**. Análise de dados com as três perguntas do critério 6 todas a NÃO VERIFICADO por dependerem de onde o parceiro aloja, `apd_ref` vazio nos quatro candidatos e a regra de bloqueio que isso impõe à primeira factura real. Recomendação **adiar**, pela regra pré-registada e não por juízo: (a) e (d) falham, (b) não foi medido, (c) não é mensurável. Tabela de **41 afirmações com estado** (12 CONFIRMADO, 14 INDÍCIO, 15 NÃO VERIFICADO) e **dez caixas devolvidas, todas com credor que sobrevive à fusão**. | Equipa KAMBÁ |
