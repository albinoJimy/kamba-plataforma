# Seguimento do procedimento junto da APD, e registo de D9

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — folha de seguimento da submissão por destino, e registo de D9 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-105 (EPIC-10) |
| Documento-fonte | `../../08_Seguranca_Conformidade.md` §8.2, §8.3, §8.6; `../E3_Regulatorio_Dados.md` §1, §2; o registo de decisões da Carta, §4.2; ADR-008, D9 |
| Relacionados | [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), [`GoLive_Gate.md`](GoLive_Gate.md), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) |

> **A folha de seguimento nasce vazia.** Submeter à APD, pagar taxas e receber um
> número de protocolo são actos humanos, e nenhum deles se faz sem o parecer que
> o KAM-104 vai pedir. O que este documento entrega são as **colunas certas**,
> os **estados possíveis** e o registo **provisório** de D9 — e diz, em cada
> caso, o que falta para a linha deixar de estar em branco.

---

## 1. Folha de seguimento, por destino

Uma linha por destino do [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md) §3.
Estados: **`por submeter`** → `submetido` → `em apreciação` → `autorizado` ou
`negado`.

A coluna **«via»** diz o que o Art. 33.º ou o 34.º exige: **notificação** para
destino adequado, **autorização** para destino não adequado. **Qual se aplica a
cada país é NÃO VERIFICADO** — não há lista pública de países adequados, e é a
pergunta **E-01** do pacote. Por isso a coluna nasce em branco: preenchê-la
agora era decidir a adequação de um país por conta própria.

| # | Destino | País (hipótese) | Via (notificação / autorização) | Estado | Data de submissão | Taxa paga | N.º de protocolo | Dias decorridos | Resultado |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Meta (WhatsApp Cloud API) | EUA/UE (NÃO VERIFICADO) | | **por submeter** | | | | | |
| 2 | Fornecedor de modelo e transcrição | EUA | | **por submeter** | | | | | |
| 3 | Fornecedor de modelo | EUA | | **por submeter** | | | | | |
| 4 | Fornecedor de modelo e visão | EUA/UE | | **por submeter** | | | | | |
| 5 | Fornecedor de transcrição | EUA | | **por submeter** | | | | | |
| 6 | Alojamento de produção | **D1 não decidida** | | **por submeter** | | | | | |
| 7 | Repositório de cópias de segurança | **a decidir com D1** | | **por submeter** | | | | | |
| 8 | CDN e firewall aplicacional | Global | | **por submeter** | | | | | |
| 9 | Facilitador de pagamentos | Angola | **nenhuma?** — destino nacional | **por submeter** | | | | | |
| 10 | Software de facturação certificado | Angola (a confirmar) | **nenhuma?** — destino nacional | **por submeter** | | | | | |
| 11 | Cofre de segredos | EUA | **nenhuma?** — sem dados pessoais, por regra | **por submeter** | | | | | |
| 12 | Correio ou SMS transaccional | a decidir | | **por submeter** | | | | | |
| 13 | Sonda sintética externa | a decidir | **a confirmar** | **por submeter** | | | | | |
| 14 | Fornecedor de melhoramento de imagem | estrangeiro, a decidir | | **por submeter** | | | | | |

| Contagem | Valor |
|---|---|
| Destinos no mapa | **14** |
| Submetidos | **0** |
| Com número de protocolo | **0** |
| Autorizados | **0** |

> **Os três «nenhuma?» levam interrogação de propósito.** Para os destinos **9**,
> **10** e **11** a leitura da KAMBÁ é que não há transferência internacional a
> notificar: dois são nacionais e o terceiro não recebe dados pessoais por
> regra. **Mas essa leitura é nossa**, o tratamento em si continua sujeito à
> notificação prévia dos Arts. 35.º a 37.º — que é outra obrigação, e não esta —,
> e a pergunta **A-03** do pacote é exactamente sobre o que se submete e como.
> *(a confirmar por parecer)*.

### 1.1 O que é preciso antes de a primeira linha mudar de estado

Por ordem, e a primeira é a que bloqueia todas:

| # | Passo | Estado | Depende de |
|---|---|---|---|
| 1 | **Pacote de perguntas enviado ao advogado** | **não feito** | KAM-104, critério 4 — acto humano |
| 2 | Resposta a **A-01**: quem notifica — a plataforma, cada PME, ou ambas | **em falta** | Passo 1. **Sem isto não há submetente** |
| 3 | Resposta a **E-01**: que países a APD reconhece como adequados | **em falta** | Passo 1. Decide notificação contra autorização por destino |
| 4 | Resposta a **A-03**: formulários, taxas aplicáveis e prazo | **em falta** | Passo 1 |
| 5 | **D1 decidida** | **em falta** | [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) §4.1; decide o país dos destinos 6 e 7 |
| 6 | Mapa de tratamentos aprovado e assinado | **em falta** | Tabela de aprovação do mapa |
| 7 | Taxas pagas, com comprovativo | **em falta** | Passo 4 |

---

## 2. Prazos: o que se sabe e o que não

| Item | Valor | Estado |
|---|---|---|
| Prazo de resposta da APD à notificação | 30 dias | **INDÍCIO** — leitura única, `../E3_Regulatorio_Dados.md` §1 |
| Prazo de resposta à autorização | — | **NÃO VERIFICADO** |
| Silêncio positivo (pode tratar-se se a APD não responder?) | — | **NÃO VERIFICADO** (`../../08` §8.6) |
| Taxas | 4.315 a 350.450 Kz | **INDÍCIO** — Decreto Presidencial 60/21, por imprensa de 2021. Qual se aplica a este caso: pergunta **A-03** |
| Prazo comprometido pelo advogado para as P0 | — | Em branco: [`Seleccao_e_Registo_Juridico.md`](Seleccao_e_Registo_Juridico.md) §1.4 |

> **O prazo da APD é o número que mais pode mudar o plano, e é o que menos se
> sabe.** A Carta dá ao fundador até à semana 3 para decidir D1, e o parecer
> escrito das P0 é pedido para a semana 6. Se a APD levar 30 dias **a contar da
> submissão**, e a submissão depender do parecer, os dados reais não entram
> antes da semana 10 — **e isto é aritmética sobre um INDÍCIO, não uma
> previsão.** Vale registá-lo porque é a conta que o KAM-108 e o KAM-110 vão
> precisar de fazer, e porque a alternativa — descobri-lo na semana 6 — é pior.

---

## 3. D9 — registo provisório (critério 5)

O critério 5 do KAM-105 admite este caminho por escrito: «se o parecer ainda não
chegou, a decisão é **provisória**, marcada como tal». **Está marcada.**

| Elemento de D9 | Posição provisória | Fundamento | O que a torna definitiva |
|---|---|---|---|
| **Papel da KAMBÁ** | **Subcontratada** de cada PME, com contrato de subcontratação como pré-condição do onboarding | Defeito documentado do `../../08` §8.2, a partir dos Arts. 5.º e 23.º (**CONFIRMADO** quanto aos artigos; como a APD qualifica plataformas de software como serviço é **NÃO VERIFICADO**) | Resposta a **A-01** |
| **Co-responsabilidade** | Apenas nos tratamentos de finalidade própria da KAMBÁ — sinal de procura agregado e índice de reputação —, que ficam **desligados no Piloto** | `../../08` §8.2 | Resposta a **A-01**, e a decisão de ligar alguma dessas finalidades |
| **Quem notifica a APD** | **NÃO DECIDIDO** | Nenhuma fonte o diz. Três hipóteses na pergunta A-01: a plataforma, cada PME, ou ambas | Resposta a **A-01** |
| **Entidade que paga os custos em USD** | **NÃO DECIDIDO — decisão do fundador** | Pergunta **F-02**; a KAMBÁ entrega as duas opções e **não recomenda nenhuma**, por terem efeitos de estrutura societária e fiscal | Decisão do fundador, informada por F-02 e C-06 |

| Campo | Valor |
|---|---|
| Estado de D9 | **PROVISÓRIA** |
| Dono | Fundador + jurídico (Carta §4.2) |
| Data do registo provisório | Novembro de 2026 |
| Escalada da Carta | «Antes de dados reais» |
| Assinatura | — (um registo provisório não se assina como decisão) |

> **O que «provisório» significa aqui, para não ser lido como meia-decisão.** As
> duas primeiras linhas registam o que o desenho **já assume por defeito** — não
> são escolhas novas, são o estado documentado a ser posto por escrito num
> registo. As duas últimas estão **vazias**, e a última é expressamente do
> fundador. Um registo provisório de D9 **não desbloqueia nada**: o
> [`GoLive_Gate.md`](GoLive_Gate.md) continua a ter as linhas A2 e A3 em branco,
> e é essa a prova de que isto não foi tratado como decisão.

---

## 4. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança (privacidade) | | | |
| Responsável de Produto | | | |
| Fundador (D9) | | | |
| Advogado externo | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-105. Folha de seguimento com uma linha por cada um dos **14** destinos do mapa e os quatro estados do critério 7, a nascer **vazia** — nenhum submetido, nenhum com protocolo —, mais os sete passos que têm de acontecer antes de a primeira linha mudar de estado, dos quais o primeiro é o envio do pacote ao advogado. A coluna «via» fica em branco de propósito: decidir se um país é adequado era usurpar a pergunta E-01. Registados os prazos conhecidos com o seu estado, e a conta que deles sai — se a APD levar 30 dias a contar da submissão, e a submissão depender do parecer, os dados reais não entram antes da semana 10, **aritmética sobre um INDÍCIO**. D9 registada como **provisória** pelo caminho que o critério 5 prevê: as duas primeiras linhas põem por escrito o que o desenho já assume, e as duas últimas ficam vazias, uma delas expressamente do fundador. | Equipa KAMBÁ |
