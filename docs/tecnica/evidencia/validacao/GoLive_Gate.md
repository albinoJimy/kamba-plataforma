# Gate de go-live — entrada de dados reais

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — checklist de entrada de dados reais em produção |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno; **regra de bloqueio operacional** |
| Ticket | KAM-105 (EPIC-10) |
| Documento-fonte | `../../08_Seguranca_Conformidade.md` §8.5, §8.6, §8.3; `../../09_Topologia_Operacao_Escala.md` §6; o registo de decisões da Carta, §4.2 |
| Relacionados | [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), [`Seguimento_APD.md`](Seguimento_APD.md), [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) |

> **Este documento não decide nada: mede.** Cada linha é uma condição objectiva
> com estado e data. **Enquanto uma única linha obrigatória estiver em branco ou
> `não`, não entram dados reais em produção** — é o que a Carta §4.2 quer dizer
> com «sem D1 não há dados reais», e o que o `../../08` §8.6 chama gate de
> go-live.
>
> **Hoje nenhuma linha obrigatória está satisfeita**, e isso não é um atraso: é
> o estado correcto de um produto que ainda não tem parecer jurídico nem
> procedimento submetido. O valor deste documento é tornar o «ainda não» legível
> e datável, em vez de uma impressão.

---

## 0. Como se lê

| Estado | Significado |
|---|---|
| `satisfeito` | A condição está cumprida, com a evidência nomeada na coluna |
| `não` | Medida e não cumprida |
| `em branco` | Não medida ainda |
| `não aplicável` | Com a razão escrita |

**Uma linha só passa a `satisfeito` com evidência nomeada** — um número de
protocolo, uma assinatura com data, um comando com o seu resultado. «Está
tratado» não é evidência.

---

## 1. Bloco A — Decisões (sem estas, nada abaixo importa)

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| A1 | **D1 decidida**: alojamento em Luanda ou em JNB/CPT, com dono e assinatura | Carta §4.2; KAM-105 critério 2 | Sim | **em branco** | Depende de ≥ 3 cotações: [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md). Nenhuma pedida | |
| A2 | **D9 decidida**: papel da KAMBÁ e quem notifica a APD | Carta §4.2; `../../08` §8.2 | Sim | **em branco** — há registo **provisório** | [`Seguimento_APD.md`](Seguimento_APD.md) §3. Depende da pergunta A-01 do parecer | |
| A3 | **D9, segunda metade**: entidade que paga os custos em USD | Carta §4.2; `../../09` §19 | Sim | **em branco** | **Decisão do fundador.** Pergunta F-02 do parecer; a KAMBÁ não recomenda nenhuma das opções | |
| A4 | **D6 decidida**: armazenamento de objectos | Carta §4.2 | Não — recomendação basta para o gate | **recomendação registada** | [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) §5; decisão final em KAM-011 | |
| A5 | **D12 decidida**: o CDN que termina TLS é subprocessador? | Carta §4.2; `../../08` §8.3.2 | Sim, **se** o caminho de webhooks ficar atrás do proxy | **em branco** | Pergunta E-04 do parecer. **Há um caminho que dispensa a decisão:** não pôr o caminho de webhooks atrás do proxy — ver nota em §5 | |

---

## 2. Bloco B — Procedimento junto da APD

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| B1 | **Mapa de tratamentos aprovado** e assinado | `../../08` §8.6 (1) | Sim | **em branco** — mapa emitido, não aprovado | [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md), v1.0, tabela de aprovação em branco | |
| B2 | **Cada destino de produção com `apd_ref` válido**, ou decisão escrita do advogado de que não é exigido | `../../08` §8.3.1, §8.6 (3) | Sim | **não** — **0 de 14** destinos com `apd_ref` | [`Seguimento_APD.md`](Seguimento_APD.md) §1 | |
| B3 | **Taxas pagas**, com comprovativo | `../../08` §8.6 (4) | Sim | **em branco** | Decreto Presidencial 60/21, 4.315 a 350.450 Kz (**INDÍCIO**); valor aplicável a este caso é a pergunta A-03 | |
| B4 | **Número de protocolo** de recepção por submissão | KAM-105 critério 7 | Sim | **em branco** | Nenhuma submissão feita | |
| B5 | **Prazo de resposta da APD conhecido**, e silêncio positivo esclarecido | `../../08` §8.6 | Não — informa o prazo, não bloqueia | **em branco** | **NÃO VERIFICADO.** Pergunta A-03 do parecer | |

---

## 3. Bloco C — Contratos e textos publicados

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| C1 | **Contrato de subcontratação (DPA)** redigido e aceite por cada PME, como condição de activação | `../../08` §8.5 req. 4, §8.6 (5) | Sim | **não** — **não está redigido** | KAM-090. Existe a lista de cláusulas dos termos de utilização, não um DPA | |
| C2 | **Aviso de privacidade publicado e versionado** | `../../08` §8.4, §8.6 (5) | Sim | **não** — **o texto não existe** | KAM-090 e KAM-022. A tabela de textos nasce vazia e o controlo falha fechada: sem aviso publicado o assistente não corre | |
| C3 | **Lista pública de subprocessadores** | `../../08` §8.5 req. 4 | Sim | **em branco** | Deriva do [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md) §3; os nomes dos fornecedores são matéria contratual em aberto | |
| C4 | **Contrato com cada fornecedor**, com retenção zero e não-treino, arquivado | `../../08` §8.3.1, §8.5 req. 8 | Sim, por destino usado | **em branco** | Checklist por fornecedor; nenhum assinado | |

---

## 4. Bloco D — Controlos técnicos

Estes não dependem do advogado nem do fundador: dependem de código, e por isso
são os únicos que a equipa fecha sozinha.

| # | Condição | Fonte | Obrigatória | Estado | Evidência | Data |
|---|---|---|---|---|---|---|
| D1t | **`tenant_destinations` existe e o *gate* falha fechado** sem linha `autorizado` | `../../08` §8.3.1; KAM-069 | Sim | **não** — **a tabela não existe** | KAM-069. Entretanto, o *gate* de destino do cliente de modelos recusa os três fornecedores em `KAMBA_ENV=prod` — é a barreira que existe hoje | |
| D2t | **Listas de saída declaradas e aplicadas na rede** | `infra/egress/`, `services/*/egress.yaml`; KAM-076 | Sim | **parcial** | Os contratos existem (`por_omissao: negar`; três FQDN em `infra/egress/litellm.yaml`, `destinos: []` nos cinco serviços). **A aplicação na rede é o KAM-076** e não está feita | |
| D3t | **Checklist de segurança do `../../08` §8.5 #11**: TLS, cifra em repouso, segregação entre PMEs, MFA, auditoria de acessos — com **pentest antes do go-live** | `../../08` §8.5 #11 | Sim | **em branco** | Dono: Responsável de Segurança. O pentest não está agendado | |
| D4t | **Isolamento entre PMEs verificado** — zero leituras cruzadas | `../../08` §3, §14 | Sim | **a suite existe e corre em cada alteração** | Suite de testes cruzados que faz falhar a construção; alvo medido **zero** | |
| D5t | **Minimização antes do modelo a correr** | `../../08` §7.4; KAM-112 | Sim | **satisfeito** | KAM-112, fundido. O valor **jurídico** depende da pergunta A-02 — o controlo existe, a sua suficiência é que está por confirmar | |
| D6t | **Registos sem conteúdo**, verificados por varredura | `../../08` §7.3 | Sim | **satisfeito** | Registador tipado com lista fechada e varredura por padrões de telefone e NIF | |
| D7t | **Retenção e purga por classe**, com registo de eliminação | `../../08` §11, §8.5 req. 14 | Sim | **não** | O agendador nasce com KAM-071; o prazo fiscal é **NÃO VERIFICADO** e até confirmação não se eliminam registos fiscais | |
| D8t | **Direitos do titular**: acesso, correcção, eliminação, exportação | `../../08` §8.5 req. 13 | Sim | **não** | KAM-070 | |
| D9t | **Cópias de segurança noutro domínio de falha, com restauro testado** | `../../09` §8 | Sim | **em branco** | Depende de D1 (o repositório também é alojamento para o ADR-008) | |
| D10t | **Ambientes separados; `staging` nunca com cópia de produção** | `../../09` §6 | Sim | **satisfeito por desenho** | `dev` e `staging` com dados **sintéticos**; a tabela do `../../09` §6 di-lo | |

---

## 5. Notas que mudam o que o gate exige

**Alojar em Luanda não dispensa o bloco B.** O `../../09` §5.1 e o `../../08`
§8.3.1 dizem-no: os modelos, a transcrição e a própria Meta seriam
transferências — **INDÍCIO**, e é o que a pergunta A-02 pede *(a confirmar por
parecer)*. Escolher Luanda reduz o número de destinos a autorizar; não remove o
procedimento.

**A linha A5 tem um caminho que a dispensa, e é executável hoje.** O
`../../08` §8.3.2 escreve duas opções para o CDN que termina TLS e **nenhuma
está decidida**: (a) assumi-lo como subprocessador e incluí-lo na notificação;
(b) **não** pôr o caminho de webhooks atrás do proxy — a assinatura da Meta já
autentica o pedido — e proteger a origem com limitação de débito. A opção (b)
**não precisa de parecer** e retira conteúdo do perímetro em vez de o
justificar. É decisão pendente de SRE, não um item assumido.

**Os dados sintéticos não passam por este gate.** O `../../09` §5.3 ponto 2 e o
§6: `dev` e `staging` com dados sintéticos ficam fora do âmbito dos Arts. 33.º e
34.º e podem correr em qualquer região. Este gate governa **dados reais em
produção**, e só esses.

**Há uma excepção pedida, e está por responder.** Dois spikes de Fase 0 — o de
coexistência e o de voz — precisam de **dados reais de teste com
consentimento** na semana 1, antes de qualquer procedimento estar concluído. É a
pergunta F-01 do parecer, e a alternativa é risco aceite por escrito pelo
fundador. **Não é uma passagem por este gate: é uma excepção a ele**, e como tal
tem de ficar registada com quem a autorizou.

---

## 6. Contagem, ao dia de hoje

| Bloco | Obrigatórias | `satisfeito` | `não` | `em branco` |
|---|---|---|---|---|
| A — Decisões | 4 | 0 | 0 | 4 |
| B — Procedimento APD | 4 | 0 | 1 | 3 |
| C — Contratos e textos | 4 | 0 | 2 | 2 |
| D — Controlos técnicos | 10 | 4 | 4 | 2 |
| **Total** | **22** | **4** | **7** | **11** |

**4 de 22 condições obrigatórias satisfeitas**, e as quatro são do bloco técnico
— as que não dependem de ninguém de fora. Nenhuma condição dos blocos A, B e C
está satisfeita, e é coerente: o pacote de perguntas ao advogado **não foi
enviado**, e enquanto não for, nem o parecer nem as decisões que dele dependem
podem existir.

---

## 7. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança (privacidade) | | | |
| Arquitecto de Plataforma | | | |
| Responsável de Produto | | | |
| Fundador (autoriza a entrada de dados reais) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-105. **22** condições obrigatórias em quatro blocos — decisões, procedimento junto da APD, contratos e textos, controlos técnicos —, cada uma com fonte, estado, evidência e data. Ao dia de hoje **4 de 22** satisfeitas, todas do bloco técnico; nenhuma dos blocos A, B e C, porque o pacote de perguntas ao advogado ainda não saiu. Registadas três notas que mudam o que o gate exige: Luanda não dispensa o procedimento, a linha do CDN tem um caminho executável que dispensa a decisão, e os dados reais de teste dos spikes são uma **excepção** ao gate e não uma passagem por ele. | Equipa KAMBÁ |
