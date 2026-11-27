# Decisão do gate do Piloto — **por preencher**

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — memorando de decisão do gate do Piloto: continuar, pivô ou parar |
| Versão | 1.1 |
| Data | Novembro de 2026 |
| Estado | NÃO VERIFICADO |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2, §5 e §6; `../../../../specs/00_KAMBA_Carta.md` §5 e §6; `../../00_Arquitectura_Solucao.md` §13.2 e §13.3; `../../../../specs/INDICE.md` §1 e §6 |
| Dono | Fundador, com o Arquitecto de Plataforma, o Responsável de Segurança e o de Produto |
| Ticket | KAM-110 (EPIC-10) |
| Classificação | Documento de Referência — Interno; **decisão de fase** |
| Relacionados | [`Gate_Piloto.md`](Gate_Piloto.md), [`Registo_Hipoteses.md`](Registo_Hipoteses.md), [`Gate_Fase0_Decisao.md`](Gate_Fase0_Decisao.md) |

> **Este ficheiro nasce em branco, e isso é o produto.** O bloco KAM-110 diz nos
> «Detalhes Técnicos» que o Claude Code prepara «o modelo do memorando de decisão
> com o campo de decisão **em branco**» e que «não escolhe nem recomenda a
> decisão». O que está aqui é a **forma**: o que se decide, quem decide, que
> evidência a sustenta, e o que cada uma das três decisões obriga a escrever.
>
> **Os números de pista são do fundador.** Meses de pista, capital e o ponto em
> que se pára ou se muda (`14` §5) escrevem-se à mão, aqui, por ele. Não há
> número nenhum neste ficheiro que não esteja numa fonte citada.
>
> **Não se assina este memorando sem o [`Gate_Piloto.md`](Gate_Piloto.md) ao
> lado**, gerado no dia do gate sobre o manifesto congelado do KAM-109 — e não
> sobre a pré-visualização versionada hoje.

---

## 0. Como se preenche

Uma ordem proposta:

1. **Gerar o pacote** sobre o Registo actualizado e o resumo do piloto, com o manifesto congelado do KAM-109 (`piloto_congelado.json`) copiado para a árvore e o seu SHA-256 (o comando está no `tools/gate_piloto/README.md`). Sem o manifesto na árvore, H1, H6, H8 e H9 saem `inconclusiva`.
2. **Ler o pacote inteiro**: o estado **efectivo** de H1–H9 (§1 do pacote), a Carta §5 item a item (§2), as linhas de `14` §6 accionadas e a paragem total (§3), a economia (§4).
3. **Preencher o §3 deste memorando**, a economia e a pista (a pergunta de `14` §5).
4. **Escrever o plano datado** de cada hipótese inconclusiva no §2.
5. **Escolher a decisão no §1**, registar a acção de cada H7, H8 ou H9 `refutada` (§1.2), e preencher a secção que a decisão obriga (§4, §5 ou §6).
6. **Listar os NÃO VERIFICADOS** que ficam, no §7.
7. **Assinar** no §8, e fazer a verificação cruzada do §9 por pessoa distinta do autor.
8. **Registar a decisão**, com dono e data, no `Registo_Hipoteses.md` e no registo de decisões da Carta (Definition of Done do bloco KAM-110).

---

## 1. Decisão

| Campo | Valor |
|---|---|
| **Decisão** (`CONTINUAR`, `PIVÔ` ou `PARAR`) | |
| Se `PIVÔ`: qual linha de `14` §6 | |
| Dono da decisão | |
| Data da decisão | |
| Pacote que a sustenta (caminho e ponta `sha`) | |
| SHA-256 do manifesto congelado do KAM-109 (`piloto_congelado.json`) | |

### 1.1 As regras, transcritas

Transcrevem-se em vez de se resumirem, porque um resumo de uma regra de decisão é
uma regra diferente.

| Fonte | Regra |
|---|---|
| `14` §2, regra de decisão | «se H1 ou H5 falharem, a tese muda antes de se escrever mais código» |
| `14` §6, paragem total | «Paragem total: se ao fim de 12 semanas não houver ≥ 3 pagantes recorrentes e nenhum canal comercial repetível» |
| Bloco KAM-110, «Detalhes Técnicos» | «uma hipótese inconclusiva não permite `CONTINUAR` sem um plano datado para a fechar» |
| Bloco KAM-110, «Detalhes Técnicos» | «Os limiares são propostas do fundador; o gate não os altera. Mudá-los depois dos dados é re-litígio (Carta §6)» |
| Bloco KAM-110, critério A | «uma hipótese sem dados é `inconclusiva`, nunca `confirmada`» |
| `../../00_Arquitectura_Solucao.md` §13.2, gate da Fase 1 | «≥ 5 PMEs pagantes a 30 dias (H1); ≥ 70% activas ao dia 60 (H9)» |
| `../../../../specs/INDICE.md` §1 | os epics da Fase 2 e da Fase 3 «só se escrevem quando o **Gate do Piloto (KAM-110)** for verde» |

**O que a matriz do pacote é, e o que não é.** O §3 do pacote devolve a linha de
`14` §6 que cada falha **acciona** — é o que o critério C manda aplicar. Não é uma
recomendação: duas falhas podem accionar duas linhas, e escolher entre elas, ou
decidir que a paragem total se aplica, é desta secção.

### 1.2 A acção para H7, H8 e H9, quando falham

`14` §6 não tem linha para estas três, e o critério C diz que nelas «o gate decide
e regista a acção». Regista-se aqui, **seja qual for a decisão do §1** — uma
`CONTINUAR` com H8 `refutada` também tem de dizer o que muda. O bloco KAM-109
acrescenta duas regras, transcritas: para H8, «o gate propõe uma acção de produto
(…) e regista-a»; para H9, «aplica-se a regra de paragem total e o gate decide o
pivô sobre retenção».

| H | Estado efectivo (do pacote) | Acção decidida | Dono (papel) | Data |
|---|---|---|---|---|
| H7 | | | | |
| H8 | | | | |
| H9 | | | | |

---

## 2. Inconclusivas, e o plano datado de cada uma

Uma linha por hipótese que o pacote dá `inconclusiva`. Sem plano datado, a
decisão `CONTINUAR` não está disponível (§1.1).

| H | Porque está inconclusiva (do pacote) | Plano para a fechar | Data-limite | Dono (papel) |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |

---

## 3. Economia real e pista (critério D)

**A linha da pista preenche-a o fundador, e só ele.** O gerador do pacote recusa
qualquer chave de pista no resumo, e este memorando não tem valor por omissão.

| Campo | Valor | Quem preenche | Fonte |
|---|---|---|---|
| Custo por PME, medido | | Produto, do §4 do pacote | KAM-081 |
| Custo por PME, estimado | 49 – 80 USD por PME e por mês no Piloto — ESTIMATIVA | (transcrito) | `../../09_Topologia_Operacao_Escala.md` §14.4 |
| Ponto de equilíbrio, hipótese | ≈ 8 a 28 PMEs | (transcrito) | `../../09_Topologia_Operacao_Escala.md` §14.5 |
| Ponto de equilíbrio, actualizado com o custo medido | | Produto | |
| **Capital disponível** | | **Fundador** | `14` §5 |
| **Meses de pista restantes** | | **Fundador** | `14` §5 |
| **Ponto em que se pára ou se muda** | | **Fundador** | `14` §5 |

---

## 4. Se `CONTINUAR`

### 4.1 Os epics da Fase 2 a escrever

O `../../../../specs/INDICE.md` §6 diz o que fica fora e quando entra. Transcrevem-se
as linhas cujo gatilho é o gate do Piloto, ou que o nomeiam; a coluna da direita
preenche-se no dia, porque **escrever um epic não é o mesmo que ter o gatilho
dele cumprido**.

| Item (`INDICE.md` §6) | Fase | Gatilho, à letra | Gatilho cumprido à data? |
|---|---|---|---|
| Geo, logística e estafetas; disputas de entrega | 2 (Clusters) | Gate do Piloto verde; decisões D1, D8 | |
| Vitrine SEO, revendedores, Academia, rede de agentes | 2 | Idem | |
| Pesquisa híbrida (o modelo do `kamba-embed`, o limiar calibrado, a comutação atómica e o resto da linha) | 2 | Gate do Piloto verde (KAM-110); um destino autorizado com `apd_ref` (ADR-008) ou um modelo servido em Luanda; ≥ 2 candidatos medidos na `dev` | |

### 4.2 Os gatilhos que a decisão faz verificar: D2, D7, D8 e D11

O critério F manda listar os gatilhos de `INDICE.md` §6 para D2, D7, D8 e D11. **A
decisão `CONTINUAR` não os abre**: pela Carta §6, ponto 2, uma decisão CONDICIONAL
«só "abre" quando o seu gatilho nomeado ocorre», e uma ABERTA tem dono e escalada.
O que esta tabela regista é o estado de cada uma no dia do gate.

| D | Assunto (`../../00_Arquitectura_Solucao.md` §13.3) | Estado (Carta §4.2) | Depende de (§13.3) | O que desbloqueia (`INDICE.md` §6) | Estado à data do gate |
|---|---|---|---|---|---|
| D2 | Fluxo B / número agregador | CONDICIONAL | Resposta escrita da Meta (política, limites) | Índice federado, assistente de consumo, Fluxo B, PME light | |
| D7 | Parceiro de factura AGT | CONDICIONAL | Confirmação escrita AGT sobre 2027 e certificação | Cobranças avançadas, Factura AI (parceiro AGT), `InvoiceProvider`; Factura AI com parceiro AGT | |
| D8 | Enquadramento BNA do modelo facilitador | ABERTA | Parecer jurídico | Geo, logística e estafetas; e vitrine SEO, revendedores, Academia, rede de agentes («Idem») — as duas com o gate verde e D1 | |
| D11 | Kambá Score como informação de crédito | CONDICIONAL | Parecer; D8 | Analytics (ClickHouse), Kambá Score, índice de preços, AdsEngine, API pública — Fase 3, e com volume de dados | |

---

## 5. Se `PIVÔ`

| Campo | Valor |
|---|---|
| Linha de `14` §6 escolhida (transcrita do §3 do pacote) | |
| Métrica de sucesso do pivô, com limiar fixado **antes** de medir | |
| Data do próximo ponto de decisão | |

**Plano das duas semanas seguintes:**

| Semana | Acção | Dono (papel) | Saída verificável |
|---|---|---|---|
| 1 | | | |
| 2 | | | |

**Tickets a congelar e a criar** (critério F):

| Ticket | Congelar ou criar | Porquê | Dono (papel) |
|---|---|---|---|
| | | | |
| | | | |

---

## 6. Se `PARAR`

| Campo | Valor |
|---|---|
| Data de fim do serviço às PMEs do piloto | |
| Aviso às PMEs: canal e antecedência | |
| *Off-boarding* das PMEs do piloto: o que cada uma leva (catálogo, histórico de pedidos) e em que formato | |
| Purga de dados: o quê, por que procedimento, e a prova de que se fez | |
| Contratos e subprocessadores a encerrar | |
| Dono do encerramento (papel) | |

---

## 7. NÃO VERIFICADOS que ficam por fechar

A Definition of Done do bloco manda listá-los «com dono e critério de saída».
Partem do registo de riscos do EPIC-10 e do §2 do pacote.

| Item | Estado | Dono (papel) | Critério de saída | Data-limite |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |

---

## 8. Assinaturas

**Quatro assinaturas.** A decisão é do fundador; o critério E nomeia as
assinaturas do Arquitecto, de Segurança e de Produto.

| Papel | Nome (papel, não pessoa) | Data | Observação |
|---|---|---|---|
| Fundador (decisão) | | | |
| Arquitecto de Plataforma | | | |
| Responsável de Segurança | | | |
| Responsável de Produto | | | |

---

## 9. Verificação cruzada

Os «Testes Requeridos» do bloco pedem uma «revisão cruzada, por pessoa distinta do
autor, de que cada item da Carta §5 tem evidência ligada».

| Campo | Valor |
|---|---|
| Quem verificou | |
| Data | |
| Itens da Carta §5 com evidência ligada e aberta (de 18, a contagem do §2 do pacote) |
| Hipóteses `confirmada` cujo resultado cumpre o limiar de `14` §2 (o gerador não o confere) | | |
| Resultado | |

Quem verifica é «pessoa distinta do autor» (Testes Requeridos do bloco).

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-110, preparação): o memorando, **em branco**. Entrega a forma — a ordem de preenchimento, as regras de decisão transcritas de `14` §2 e §6 e do bloco, o plano datado das inconclusivas, a economia com a pista por preencher pelo fundador, a acção para H7, H8 e H9 quando falham, as três secções que cada decisão obriga (epics da Fase 2 e os gatilhos D2, D7, D8 e D11; pivô com plano de duas semanas e tickets; encerramento), os NÃO VERIFICADOS com dono, as quatro assinaturas e a verificação cruzada. Nenhum campo de decisão nem de pista preenchido. | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | KAM-110, interface com o KAM-109 fundido (#283): o pacote sustenta-se no manifesto congelado `piloto_congelado.json` e no SHA-256 dele, e não na exportação — é o manifesto que o protocolo do Piloto (§10) manda citar na coluna `fonte` do Registo. Três menções mudam (o aviso de cima, o passo 1 do §0, que passa a dizer que o manifesto se copia para a árvore, e a linha do §1); a decisão e as assinaturas continuam em branco. | Equipa KAMBÁ |
