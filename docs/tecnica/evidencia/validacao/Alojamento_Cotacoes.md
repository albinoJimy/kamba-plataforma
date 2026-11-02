# Alojamento: cotações, regra de decisão e D1

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — pedido de cotação, comparação e decisão D1 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-105 (EPIC-10) |
| Documento-fonte | `../../09_Topologia_Operacao_Escala.md` §5 (§5.1, §5.2, §5.3), §6, §8, §19; `../../08_Seguranca_Conformidade.md` §8.3; `../E3_Regulatorio_Dados.md` §7; ADR-008, D1, D6 |
| Relacionados | [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), [`GoLive_Gate.md`](GoLive_Gate.md), [`Seguimento_APD.md`](Seguimento_APD.md) |

> **As tabelas de cotação nascem vazias, e é assim que devem nascer.** Pedir uma
> cotação a um fornecedor é acto humano. O que este documento entrega é o
> **modelo do pedido**, a tabela com as colunas que a decisão precisa, e a regra
> de decisão já escrita — para que, quando as respostas chegarem, a decisão seja
> uma leitura e não uma discussão.
>
> **Nenhuma célula de preço, SLA ou latência foi estimada.** É o que os «Testes
> Requeridos» do KAM-105 exigem: cada célula tem documento de origem ou
> «sem resposta». Os números que o `../../09` §5.2 e §14 usam são **hipótese de
> planeamento** e **ESTIMATIVA** e **não entram** nas tabelas abaixo.

---

## 1. O que a decisão D1 realmente decide, e o que não decide

Do `../../09` §5.1, e vale repetir porque é o mal-entendido mais provável:

| Decide | Não decide |
|---|---|
| Onde correm a computação, a base de dados e as cópias de segurança | **Se há procedimento junto da APD** — há, nos dois casos |
| Quantos destinos de transferência é preciso autorizar | Se os modelos, a transcrição e a Meta são transferências — isso é a pergunta **A-02** do parecer |
| O custo mensal da infraestrutura e a moeda em que se paga | A entidade que paga os custos em USD, que é a outra metade de **D9** e decisão do fundador |

> **Alojar em Luanda não dispensa o procedimento**, porque os modelos, a
> transcrição e a própria Meta seriam transferências — **INDÍCIO**, pela
> inferência que o `../E3_Regulatorio_Dados.md` §2 marca assim, e é o que a
> pergunta A-02 pede *(a confirmar por parecer)*. Escolher Luanda **reduz o
> número de destinos a autorizar**; JNB/CPT **acrescenta um**. As cópias de
> segurança, o CDN e a observação contam como alojamento para o ADR-008.

---

## 2. Modelo de pedido de cotação

Enviar a **Raxio, Paratus, Angola Cables e Cloud Nacional** (Luanda) e a **um
hiperescalador em JNB/CPT**, como o `../../09` §5.3 ponto 5 manda. O mesmo texto
para todos, para que as respostas sejam comparáveis.

```text
Assunto: Pedido de cotação — alojamento de produção e pré-produção

Bom dia,

Somos uma plataforma de software angolana em fase de piloto, e procuramos
alojamento para produção e pré-produção. Pedimos cotação para o seguinte, e
agradecemos que indiquem "não aplicável" onde o serviço não existir, em vez de
o aproximarem — precisamos de comparar propostas e um valor aproximado
inviabiliza a comparação.

1. CAPACIDADE
   Produção:      8 vCPU, 32 GB de RAM, NVMe >= 200 GB
   Pre-producao:  4 vCPU, 16 GB de RAM
   Indiquem se e colocation (nos levamos o equipamento) ou IaaS (maquina
   virtual vossa), e o preco de cada modelo se oferecerem os dois.

2. PRECO
   Mensal, em Kwanzas e em USD, com e sem IVA, e o que esta incluido
   (energia, largura de banda, enderecos IP, transferencia de saida).
   Indiquem o custo de transferencia de saida por GB, se for medido.

3. SLA
   Disponibilidade contratada, a janela de manutencao, a compensacao por
   incumprimento, e o tempo de resposta a incidentes por severidade.

4. SEGUNDO LOCAL PARA COPIAS DE SEGURANCA
   Tem um segundo centro de dados, em dominio de falha distinto do primeiro?
   Em que localidade? Oferecem armazenamento de objectos la, e a que preco?

5. SERVICOS GERIDOS
   Oferecem PostgreSQL gerido? E armazenamento de objectos compativel com S3?
   Com que versao, que politica de copias e que SLA proprio?

6. LIGACAO
   Estao ligados a um ponto de troca de trafego (IXP)? Qual? Que operadores
   de transito usam? Oferecem IPv6?

7. CONTRATO E FACTURACAO
   Prazo minimo de contrato e periodo de aviso para cessar. Facturam em
   Kwanzas? Aceitam pagamento por transferencia local?

8. PROVISIONAMENTO
   Prazo entre a assinatura e a maquina disponivel, em dias uteis.

9. ENSAIO
   Disponibilizam uma maquina de ensaio ou periodo de avaliacao, mesmo curto?
   Precisamos de medir latencia de rede a partir de Luanda e para o
   estrangeiro antes de decidir.

10. PROTECCAO DE DADOS
    A plataforma trata dados pessoais de titulares em Angola. Pedimos:
    (a) a localidade exacta onde os dados ficariam;
    (b) se alguma operacao vossa (suporte, copias, monitorizacao) implica
        acesso aos dados ou a sua saida do pais, e para onde;
    (c) se aceitam clausulas de subcontratacao de tratamento de dados.

Agradecemos resposta por escrito, com validade da proposta.
```

**Porque o ponto 10 existe.** Um fornecedor em Luanda cujo suporte acede aos
dados de fora do país, ou cujas cópias saem para outro país, **não resolve o
problema que a escolha de Luanda procura resolver** — e isso não aparece numa
tabela de preços. Sem esta pergunta, a cotação mais barata podia ser a que
acrescenta um destino de transferência em silêncio.

---

## 3. Tabela comparativa — **nasce vazia**

Uma linha por fornecedor e por ambiente. **Cada célula preenchida leva o
documento de origem** (ficheiro, data, referência da proposta); onde o
fornecedor não responder, escreve-se **«sem resposta»** — nunca uma estimativa.

| # | Fornecedor | Local | Ambiente | Modelo | Preço/mês (Kz) | Preço/mês (USD) | SLA | 2.º local p/ cópias | IXP | Contrato mínimo | Factura em Kz | Postgres gerido | Objectos geridos | Prazo de provisionamento | Fonte |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | Luanda | produção | | | | | | | | | | | | |
| 2 | | Luanda | pré-produção | | | | | | | | | | | | |
| 3 | | Luanda | produção | | | | | | | | | | | | |
| 4 | | Luanda | pré-produção | | | | | | | | | | | | |
| 5 | | JNB/CPT | produção | | | | | | | | | | | | |
| 6 | | JNB/CPT | pré-produção | | | | | | | | | | | | |

**Mínimo que o critério 1 exige:** ≥ 3 cotações, das quais **≥ 2 de Luanda**
(entre Raxio, Paratus, Angola Cables e Cloud Nacional) e **≥ 1 de JNB/CPT**.

| Estado | Valor |
|---|---|
| Fornecedores contactados | **0** |
| Cotações recebidas | **0** |
| Data do primeiro pedido | — |

### 3.1 Resposta ao ponto 10, por fornecedor

Separada da tabela de preços de propósito: é a coluna que decide se a cotação
serve, e não quanto custa.

| Fornecedor | Localidade exacta dos dados | Suporte, cópias ou monitorização acedem aos dados? De onde? | Aceita cláusulas de subcontratação? | Fonte |
|---|---|---|---|---|
| | | | | |

---

## 4. Regra de decisão, e a decisão D1

A regra é a do `../../09` §5.3 ponto 4, transcrita em tabela para que a decisão
seja mecânica: **Luanda se as três forem `S`; caso contrário JNB/CPT com o
procedimento concluído.**

| # | Condição | Resultado | Fonte |
|---|---|---|---|
| R1 | A melhor cotação de Luanda é **≤ 2×** a de JNB/CPT, para a mesma capacidade | **em branco** | Requer as linhas 1 a 6 da §3 |
| R2 | Há **VMs com SLA** contratado em Luanda (não só colocation) | **em branco** | Requer a coluna SLA da §3 |
| R3 | Há **segundo local angolano** para as cópias de segurança | **em branco** | Requer a coluna «2.º local» da §3 |

> **Acrescento uma quarta condição, e declaro-a como acrescento.** O `../../09`
> §5.3 nomeia três. A §3.1 pergunta se o suporte, as cópias ou a monitorização
> do fornecedor acedem aos dados de fora do país — e se a resposta for sim, a
> escolha de Luanda **não reduz** os destinos de transferência, que é a única
> razão pela qual ela ganha a R1 e a R2. Proponho:
>
> | # | Condição | Resultado |
> |---|---|---|
> | R4 *(proposta)* | Nenhuma operação do fornecedor em Luanda implica acesso aos dados ou a sua saída do país | **em branco** |
>
> **Não a apliquei sem autorização:** a regra do §5.3 é de desenho e mudá-la é
> decisão de quem a escreveu. Fica como proposta, medida e visível, e a decisão
> de a incluir é do Arquitecto de Plataforma com o Responsável de Segurança.

### 4.1 D1 — a decisão

| Campo | Valor |
|---|---|
| Decisão | **em branco** — `Luanda` ou `JNB/CPT com procedimento concluído` |
| Resultado da regra | **em branco** (R1, R2, R3 não medidas) |
| Dono | Produto + Segurança; **decide o fundador** (Carta §4.2) |
| Prazo da Carta | O fundador decide **até à semana 3**; sem D1 não há dados reais |
| Data | — |
| Assinatura — Responsável de Produto | |
| Assinatura — Responsável de Segurança | |

> **Esta caixa fica vazia e não é por falta de trabalho.** A decisão exige três
> cotações que ninguém pediu, e pedir cotações a fornecedores não é acto de
> sessão. O que estava ao alcance — o pedido, as colunas, a regra e a quarta
> condição — está feito, e a decisão passa a ser uma leitura da tabela.

---

## 5. Latência (critério 3)

| Medição | Estado | Razão |
|---|---|---|
| RTT de Luanda para o alojamento candidato em Luanda | **NÃO MEDIDO** | Nenhum fornecedor contactado, pelo que não se sabe se algum oferece máquina de ensaio — é o ponto 9 do pedido da §2 |
| RTT de Luanda para JNB/CPT | **NÃO MEDIDO** | Idem. O `../../09` §5.2 traz «~52 ms» como **INDÍCIO da biblioteca exploratória**, e um indício não é uma medição: **não o uso** |
| RTT para a infraestrutura da Meta | **NÃO MEDIDO** | O `../../09` §5.2 diz que os webhooks são dominados pela infra da Meta (**INDÍCIO**) |

O critério 3 prevê este caminho por escrito: «sem oferta fica "NÃO MEDIDO" e o
**KAM-077** mede». **Fica NÃO MEDIDO, e o KAM-077 herda a medição** — com o
ponto 9 do pedido de cotação já a pedir a máquina de ensaio que a torna
possível.

---

## 6. D6 — recomendação dependente de D1 (critério 4)

D6 é o armazenamento de objectos, e a Carta §4.2 di-lo: **«decide com D1»**. A
decisão final é do **KAM-011**; aqui fica a recomendação.

| Cenário de D1 | Recomendação | Razão |
|---|---|---|
| **D1 = Luanda** | **SeaweedFS**, nó único | Os serviços geridos em Luanda são **NÃO VERIFICADO** (`../../09` §5.2 e §19): se não houver armazenamento de objectos gerido, a alternativa auto-alojada é a única. O MinIO está excluído (ADR-014) |
| **D1 = JNB/CPT** | **S3 gerido** | Existe, é maduro, e retira à equipa a operação do armazenamento — que, com uma equipa pequena, vale mais do que a diferença de preço |
| **D1 = Luanda com objectos geridos confirmados** | **Reavaliar**, a favor do gerido | A coluna «Objectos geridos» da §3 é que o diz; hoje está vazia |

**Testes pendentes antes de a decisão fechar** (KAM-076, e o `../../09` §19
lista-os como NÃO VERIFICADO):

| # | Teste | Estado |
|---|---|---|
| T1 | Carregamento em várias partes (*multipart*) | **NÃO VERIFICADO** |
| T2 | URLs assinadas com expiração | **NÃO VERIFICADO** |
| T3 | Bloqueio de objecto (*object lock*), para o que precise de ser imutável | **NÃO VERIFICADO** |
| T4 | Replicação do contentor para o repositório de cópias | **NÃO VERIFICADO** |

> **Uma consequência que convém não perder:** se D1 for Luanda e o
> armazenamento de objectos for auto-alojado em nó único, **o armazenamento
> deixa de ter redundância própria** e passa a depender inteiramente da
> replicação para o segundo local (R3). Isso torna a condição R3 mais do que um
> critério de preço: sem segundo local angolano, a opção Luanda com nó único
> fica com um ponto de perda total de objectos.

---

## 7. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Arquitecto de Plataforma | | | |
| Responsável de Segurança | | | |
| Responsável de Produto | | | |
| Fundador (decide D1) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-105. Modelo de pedido de cotação com dez pontos, tabela comparativa com dezasseis colunas e a regra de decisão do `../../09` §5.3 em tabela — todas a nascer **vazias**, porque pedir cotações é acto humano, e **sem uma única célula estimada**, que é o que os «Testes Requeridos» exigem. Acrescentado o ponto 10 ao pedido (se o suporte, as cópias ou a monitorização do fornecedor acedem aos dados de fora do país) e proposta uma quarta condição **R4** à regra de decisão, pela mesma razão: um fornecedor em Luanda cujas operações saem do país não reduz os destinos de transferência, que é a única razão pela qual Luanda ganha. A R4 fica **proposta e não aplicada**, por mudar uma regra de desenho. Latência **NÃO MEDIDO** pelo caminho que o próprio critério 3 prevê, com o KAM-077 a herdá-la. D6 com recomendação por cenário de D1, quatro testes pendentes e a consequência de um nó único sem segundo local. | Equipa KAMBÁ |
