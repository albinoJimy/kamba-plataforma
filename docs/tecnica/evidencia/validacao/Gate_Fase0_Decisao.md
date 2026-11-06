# Decisão do gate da Fase 0 — **por preencher**

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — decisão do gate da Fase 0 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Estado | NÃO VERIFICADO |
| Fonte | `../../00_Arquitectura_Solucao.md` §13.1 e §13.2; `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §3A Regra 5; `../../../../specs/00_KAMBA_Carta.md` §4.2 |
| Dono | Fundador, com o Arquitecto de Plataforma, o Responsável de Segurança e o de Produto |
| Ticket | KAM-108 (EPIC-10) |
| Classificação | Documento de Referência — Interno; **decisão de fase** |
| Relacionados | [`Gate_Fase0.md`](Gate_Fase0.md), [`Gate_Fase0_Demonstracao.md`](Gate_Fase0_Demonstracao.md), [`Registo_Hipoteses.md`](Registo_Hipoteses.md) |

> **Este ficheiro nasce vazio, e isso é o produto.** O bloco KAM-108 diz nos
> «Detalhes Técnicos»: «a demonstração e o veredicto são humanos». O que está
> preparado é a **forma** da decisão — o que se decide, quem decide, que
> evidência a sustenta e o que fica aberto com dono e data. **Escrever um
> veredicto aqui era tomar a decisão com outro nome.**
>
> **Não se assina este documento sem a [`Gate_Fase0.md`](Gate_Fase0.md) ao lado.**
> A regra é a mesma: nenhuma linha passa a satisfeita sem evidência nomeada, e
> nenhum veredicto se escreve sem as linhas G0-n que o sustentam.

---

## 0. Como se preenche

Pela ordem, e nenhum passo se salta:

1. **Correr a demonstração** pelo cenário de [`Gate_Fase0_Demonstracao.md`](Gate_Fase0_Demonstracao.md) §2, três vezes consecutivas, por quem **não escreveu o código**, com a Meta real.
2. **Preencher as linhas G0-n** da [`Gate_Fase0.md`](Gate_Fase0.md) que a demonstração resolve, cada uma com a evidência que a demonstração produziu (o traço, a gravação do ecrã, a ligação da corrida de CI).
3. **Ler a tabela inteira** e escolher o veredicto do §1 **pela regra do §1.1**, não por impressão.
4. **Listar os itens abertos** no §2, cada um com dono e data — e um AMARELO exige que a data esteja a ≤ 2 semanas.
5. **Decidir o K1** no §3.
6. **Decidir o destino do KAM-109** no §4.
7. **Assinar** no §5, os três papéis.

---

## 1. Veredicto

| Campo | Valor |
|---|---|
| **Veredicto** | |
| Data da decisão | |
| Ponta medida (`sha`) | |
| Execução de CI que a sustenta | |
| Quem conduziu a demonstração | |
| Quem **não** pode conduzir | quem escreveu o código (critério G0-1) |

### 1.1 A regra, transcrita do critério G0-8

Transcreve-se em vez de se resumir, porque um resumo de uma regra de veredicto é
uma regra diferente:

| Veredicto | Condição | Consequência |
|---|---|---|
| **VERDE** | G0-1 a G0-7 passam | A Fase 1 arranca |
| **AMARELO** | G0-1 e G0-2 passam; os restantes com **item datado ≤ 2 semanas** e **sem trabalho da Fase 1 que dependa deles** | A Fase 1 arranca **só** no que não depende dos itens abertos |
| **VERMELHO** | **G0-1 ou G0-2 falham** | **Não arranca trabalho de funcionalidade da Fase 1**, e **corrige-se a abstracção antes de haver terceira vertical** |

**Três coisas que esta tabela não deixa negociar**, e vale dizê-las antes de
haver pressão para as negociar:

- **AMARELO não é «verde com ressalvas».** Exige as duas condições: item **datado**
  a ≤ 2 semanas, **e** nenhum trabalho da Fase 1 a depender dele. Um item sem
  data não dá AMARELO; dá VERMELHO ou nada.
- **VERMELHO não é só «parar».** A segunda metade — «corrige-se a abstracção
  antes de haver terceira vertical» — é a que custa, e é a que o `14` §3A Regra
  de dois existe para impor.
- **O G0-1 tem hoje uma linha `não` medida** (linha 1.6 da
  [`Gate_Fase0.md`](Gate_Fase0.md), e o §9.2 do mesmo ficheiro): a acção do
  consumo na vertical Serviços **não está escrita**. Lido à letra, o G0-1 não
  passa. **Essa leitura é do fundador e não está tomada neste ficheiro.**

---

## 2. Itens abertos

Uma linha por item, com dono e data. **Um item sem data não é um item aberto: é
uma pendência**, e uma pendência não sustenta um AMARELO.

| # | Item | Linha G0-n | Dono (papel) | Data-limite | Bloqueia trabalho da Fase 1? | Critério de saída |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |

### 2.1 Os itens NÃO VERIFICADOS que condicionam a Fase 1

A Definition of Done do bloco KAM-108 nomeia três por extenso — **D1, D4 e D5** —
e manda listá-los «com critério de saída». Os três estão medidos na
[`Gate_Fase0.md`](Gate_Fase0.md) §7 e repetem-se aqui com o critério de saída,
que é o que esta secção acrescenta.

| Decisão | Estado medido | Critério de saída | Dono (papel) | Data-limite |
|---|---|---|---|---|
| **D1** — alojamento | `inconclusiva`; **zero** cotações pedidas contra um mínimo de três | R1, R2 e R3 do `../../09_Topologia_Operacao_Escala.md` §5.3 avaliadas sobre ≥ 3 cotações escritas, e a decisão assinada | Produto + Segurança | |
| **D4** — facilitador | `inconclusiva`; nenhum candidato adopta (o melhor com 32 de 100), os dois melhores bloqueados por portões diferentes | Duas respostas escritas por candidato, e a regra ponderada a dar ≥ 60 com os dois portões de canon satisfeitos | Produto | |
| **D5** — Tech Provider ou BSP | `inconclusiva`; **ABERTA** e não «provisória»; zero cotações de BSP | Estatuto aprovado no painel, **ou** ≥ 2 cotações formais com suporte a BSUID; e o *input* de D9 sobre quem paga em USD | Produto | |

---

## 3. K1 — declarado ou negado

O `../../00_Arquitectura_Solucao.md` §13.1 define o nível: «**K1** Esqueleto
andante: conversa real, pedido, evento, duas verticais». E a linha seguinte do
mesmo §13.1 é a que dá peso a esta caixa: «**não se salta K1→K3**: sem isolamento
testado e pagamento autenticado, escalar é amplificar o risco».

| Campo | Valor |
|---|---|
| **K1** | *declarado* / *negado* |
| Razão, numa frase | |
| Data | |

---

## 4. KAM-109 — desbloqueado ou replaneado

O KAM-108 **bloqueia** o KAM-109 (piloto concierge e medição de H1, H6, H8 e
H9), e o bloco exige que esta decisão diga qual dos dois.

| Campo | Valor |
|---|---|
| **KAM-109** | *desbloqueado* / *replaneado* |
| Se replaneado: o quê, e para quando | |
| Se desbloqueado: que partes arrancam, e quais esperam | |

**E há uma condição anterior a esta**, escrita no próprio critério G0-7: se H3 ou
H4 tiverem sido **`refutada`**, a decisão de mudar de canal tem de estar
**assinada antes** de o KAM-109 arrancar. Hoje as duas estão `inconclusiva` com
amostra zero, pelo que a condição **não se activa** — e `inconclusiva` não é
`refutada`.

---

## 5. Assinaturas

**Três papéis, e nenhum assina pelo outro.** O bloco nomeia-os: Arquitecto de
Plataforma, Responsável de Segurança, Responsável de Produto. Uma assinatura sem
data não é uma assinatura.

| Papel | Nome (papel, não pessoa) | Data | Observação |
|---|---|---|---|
| Arquitecto de Plataforma | | | |
| Responsável de Segurança | | | |
| Responsável de Produto | | | |

**E a verificação cruzada, que os «Testes Requeridos» do bloco exigem à parte:**

| Campo | Valor |
|---|---|
| Quem verificou que cada linha G0-n tem evidência **ligada** e não declarada | |
| Data | |
| Resultado | |

Quem verifica **não pode ser quem escreveu** este ficheiro nem a
[`Gate_Fase0.md`](Gate_Fase0.md) — é a letra dos «Testes Requeridos»:
«verificação cruzada, **por pessoa distinta do autor**».

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-108): o modelo da decisão, **por preencher**. Entrega a forma — a regra de veredicto transcrita do critério G0-8, a tabela de itens abertos com dono e data, os três NÃO VERIFICADOS que a Definition of Done nomeia (D1, D4, D5) com critério de saída, o K1, o destino do KAM-109 e os três blocos de assinatura. Nenhum campo preenchido: o veredicto é humano. | Equipa KAMBÁ |
