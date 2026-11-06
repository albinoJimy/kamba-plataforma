# Registo de Hipóteses — H1 a H9

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — registo das hipóteses críticas, com limiar, método, resultado e decisão |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-100 (EPIC-10), e usado por todos os tickets do epic |
| Estado | NÃO VERIFICADO — nenhuma das nove hipóteses foi medida |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (limiares) e §6 (pivôs) |
| Dono | Fundador (a decisão de cada hipótese é dele, `../../../../specs/00_KAMBA_Carta.md` §4.2) |
| Documento-fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2, §3A, §6; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` §2 |
| Relacionados | [`H3_Coexistencia_244.md`](H3_Coexistencia_244.md), [`Meta_Perguntas.md`](Meta_Perguntas.md), [`Seguimento_APD.md`](Seguimento_APD.md) |

> **A folha nasce por preencher, e isso é o produto.** O KAM-100 entrega as nove
> linhas com o **limiar**, o **método** e o **pivô** já escritos — que é o que
> tem de estar fixado **antes** de medir, porque um limiar escolhido depois do
> resultado não é um limiar. As sete colunas de medição ficam vazias: nenhuma das
> nove hipóteses foi medida, e nenhuma se decide sem o fundador.
>
> Validar com o `scripts/validar_evidencia.py`. O modo `check` verifica a forma;
> o modo `--completo` é o do fim e falha sobre cada célula vazia.

---

## 1. As nove hipóteses

Esquema fixado nos «Detalhes Técnicos» do KAM-100: `H | enunciado | limiar |
método | amostra n | resultado | estado | fonte | decisão | pivô aplicável
(14 §6) | dono | data`. A **ordem** das doze colunas é a do esquema, e o
validador recusa-a trocada.

Os estados de uma hipótese são três: `confirmada`, `refutada`, `inconclusiva`.
**Não são** os três da escala de verificação do conjunto — CONFIRMADO, INDÍCIO,
NÃO VERIFICADO —, que classificam uma afirmação sobre o mundo e não o destino de
uma hipótese. Confundi-los faz uma hipótese parecer decidida por haver uma fonte.

| H | enunciado | limiar | método | amostra n | resultado | estado | fonte | decisão | pivô aplicável (`14` §6) | dono | data |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | PMEs formais pagam por atendimento e loja no WhatsApp | ≥ 5 pagam após 30 dias de piloto | 30 entrevistas e 10 pilotos concierge a preço real (KAM-106, KAM-109) | | | | | | Voltar às entrevistas: mudar de segmento ou de produto (candidato: Factura AI isolada) | | |
| H2 | O preço pode ser publicado ou respondido pelo bot | ≥ 50% aceitam para ≥ 70% do catálogo | Entre as 30 PMEs, quantas aceitam preço fixo ou «a partir de» (KAM-106) | | | | | | Reposicionar: atendimento e disponibilidade, não comparação de preço | | |
| H3 | A coexistência funciona no número da PME angolana | 3/3 ligados sem perda de histórico, operacionalizado em [`H3_Coexistencia_244.md`](H3_Coexistencia_244.md) §3 | Spike técnico com 3 números +244 reais, Embedded Signup v4 e sincronização (KAM-100) | | | | | | Mudar de canal: BSP parceiro, número novo, ou produto sem automação no WhatsApp da PME | | |
| H4 | A Meta aceita o caso de uso (assistente de PME, templates, opt-in) | Resposta escrita da Meta ou aprovação de Tech Provider | Leitura da política em fonte primária e pedido de Tech Provider ou BSP (KAM-101, KAM-102) | | | | | | Mudar de canal: BSP parceiro, número novo, ou produto sem automação no WhatsApp da PME | | |
| H5 | Existe via de cobrança com confirmação *server-side* para uma PME | Prazo e custo por PME conhecidos e ≤ 6 semanas | Reunião com 2 bancos e 2 facilitadores (KAM-103) | | | | | | Manter as camadas 1 e 2: vender atendimento e agenda sem cobrança integrada | | |
| H6 | O custo por conversa fecha com a assinatura | Custo ≤ 15% da mensalidade | Medir 500 conversas reais: LLM, voz e Meta (KAM-109) | | | | | | Subir o preço, reduzir modelo ou voz, ou limitar volume por plano | | |
| H7 | O bot não fica sozinho em apuros (voz, regateio, kimbundu) | ≥ 85% resolvidas sem *handoff* errado | *Dataset* de 100 conversas reais, com avaliação humana | | | | | | — (ver §4, item 2) | | |
| H8 | A PME mantém o catálogo actualizado | ≥ 60% de catálogos correctos em auditoria | Observar 4 semanas: % de actualizações face a mudanças reais (KAM-109) | | | | | | — (ver §4, item 2) | | |
| H9 | Retenção: usam depois do primeiro mês | ≥ 70% activos ao dia 60, das PMEs activadas até à semana 4 | *Cohorts* do piloto (KAM-109) | | | | | | — (ver §4, item 2) | | |

**Os limiares são propostas do fundador** (`14` §2, à letra: «Limiares são
propostas minhas»). Fixam-se antes de medir e só mudam por emenda registada
(EPIC-10 §1). Uma alteração de limiar depois de haver resultado é uma alteração
do critério, e não um ajuste.

### 1.1 Contagem, para não se ler a forma como resultado

| | |
|---|---|
| Linhas | 9 de 9 |
| Linhas com limiar, método e pivô escritos | 9, 9 e 6 |
| Linhas com resultado medido | **0** |
| Linhas com estado decidido | **0** |
| Células por preencher | **63 de 108** |

---

## 2. Como se preenche uma linha

1. **A amostra fecha-se antes do resultado.** `amostra n` é quantas unidades
   entraram na medição — entrevistas, números, conversas —, e escreve-se mesmo
   quando é menor do que o método pedia. Uma mediana de três envios apresentada
   como se fossem dez é o defeito que o `spikes/h3/tabela.py` recusa cometer, e
   aqui não é diferente.
2. **`resultado` é um número, não uma frase.** «Correu bem» não é um resultado.
   Se a medição não produziu número, o resultado é `NÃO MEDIDO` e o estado é
   `inconclusiva`.
3. **`fonte` nomeia o artefacto**, com caminho: o ficheiro de validação, o anexo
   de evidência, a resposta escrita. «Reunião de 12 de Novembro» não é fonte
   enquanto não houver registo dela.
4. **`estado` é um dos três**, e `inconclusiva` é uma resposta legítima. O que
   não é legítimo é deixar a célula vazia depois de o prazo passar.
5. **`decisão` diz o que muda no produto**, e só o fundador a escreve. Uma
   hipótese `refutada` sem decisão registada deixa o pivô à espera de ninguém.
6. **`pivô aplicável`** já está escrito onde `14` §6 o dá. Não se inventa: ver o
   §4, item 2.

---

## 3. Prazos de `14` §2, e o ponto de decisão

| H | Semanas | Fase |
|---|---|---|
| H3, H4 | 1–3 e 1–6 | 0 — **correm primeiro, porque bloqueiam tudo** (`14` §2, regra de decisão) |
| H1, H2, H5 | 1–8, 1–4, 1–6 | 0 |
| H6, H7, H8 | 4–10, 4–10, 4–12 | 1 |
| H9 | 8–12 | 1 |

O ponto de decisão é a **semana 6** (`14` §3A, Regra 5), e é nele que H3 se
revê. Paragem total, pela letra de `14` §6: se ao fim de 12 semanas não houver
≥ 3 pagantes recorrentes e nenhum canal comercial repetível.

---

## 4. O que fica devolvido, e a quem

Nenhum dos dois se decide aqui, e nenhum deles é trabalho de máquina.

| # | O que | Porque não se fecha aqui | Credor |
|---|---|---|---|
| 1 | **O `14` §2 tem doze hipóteses; esta folha tem nove.** Medido: H10, H11 e H12 — os módulos de entrada do EPIC-11 — estão em `14` §2 com limiar *proposto* e prazo, e **não** estão nesta folha | Porque a folha segue o **critério de saída do EPIC-10** §2, que diz «H1–H9 (…) 9 de 9 linhas completas», e o *handoff* do KAM-100 diz «as 9 linhas». Alargar a folha a doze mudava o critério de saída de um epic, e o validador passaria a exigir doze onde o critério exige nove — uma sessão não muda um critério de saída. As três hipóteses **não ficam sem sítio**: ou entram aqui por emenda ao critério, ou o EPIC-11 abre a sua folha | **Fundador** |
| 2 | **O `14` §6 não dá pivô a H7, H8 nem H9.** Medido: §6 tem seis linhas — H1, H3 e H4 (juntas), H5, H2, H6, e «nenhum canal de acesso funciona». H7, H8 e H9 não aparecem em nenhuma | Porque escrever um pivô que a fonte não dá é inventar a decisão de contingência de três hipóteses. A célula fica `—` com esta nota, e não com um pivô plausível — que é exactamente o que pareceria medido sem o ser | **Fundador** |
| 3 | **As sete colunas de medição das nove linhas** | Porque medir H1, H2, H5, H6, H7, H8 e H9 é trabalho de outros tickets (KAM-103, KAM-106, KAM-109), e medir H3 exige três donos de número com consentimento escrito — acto do fundador. H4 depende de resposta da Meta (KAM-101, KAM-102) | **KAM-103**, **KAM-106**, **KAM-109**, **KAM-101**, **KAM-102** e o **fundador** para H3 |

---

## 5. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Fundador (decisão de cada hipótese) | | | |
| Responsável de Produto | | | |
| Engenheiro de Plataforma (H3, H6) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-100. As **nove** linhas H1–H9 no esquema de doze colunas que os «Detalhes Técnicos» do KAM-100 fixam, pela ordem dele. Nascem com **limiar, método e pivô escritos** — 9, 9 e 6 de 9 — e com as **sete** colunas de medição vazias: **63 células de 108 por preencher**, 0 resultados medidos e 0 estados decididos. Os limiares são os de `14` §2 e são *propostas do fundador*, à letra do documento; fixam-se antes de medir. Os pivôs são os de `14` §6, transcritos e não interpretados. **Duas divergências medidas e devolvidas ao fundador, não resolvidas aqui:** (1) o `14` §2 tem **doze** hipóteses e o critério de saída do EPIC-10 §2 pede **nove** — as três dos módulos de entrada do EPIC-11 ficam fora da folha porque alargá-la mudava um critério de saída de epic; (2) o `14` §6 **não dá pivô** a H7, H8 nem H9, e as três células ficam `—` em vez de levarem um pivô inventado. O §2 fixa como se preenche uma linha, com a regra de que `amostra n` se escreve mesmo quando é menor do que o método pedia. Validável com `scripts/validar_evidencia.py --registo` (forma) e `--completo` (fim do spike). | Equipa KAMBÁ |
