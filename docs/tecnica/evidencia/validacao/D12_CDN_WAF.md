# D12 — CDN/WAF que termina TLS: registo da opção por omissão, como proposta

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — registo da metade CDN/WAF da D12, com a opção (b) por omissão de construção, **como proposta** |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-077 (EPIC-08), preparação sem o mundo real |
| Documento-fonte | `../../08_Seguranca_Conformidade.md` §8.3.2, §13 N1, §15; `../../00_Arquitectura_Solucao.md` §13.3; o registo de decisões da Carta, §4.2; ADR-008 |
| Relacionados | [`GoLive_Gate.md`](GoLive_Gate.md) (linha A5), [`Mapa_Tratamentos_v1.md`](Mapa_Tratamentos_v1.md) (destino 8), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) (pergunta E-04), [`../../../../provas/alojamento/README.md`](../../../../provas/alojamento/README.md) (prova 3.1) |

> **Isto não é a decisão D12.** O critério 3 do KAM-077 pede a D12 «registada
> **com dono e data**», e este documento deixa as duas células **em branco** de
> propósito: decidir é do dono que a Carta §4.2 nomeia (SRE + jurídico), e a
> preparação do lote 24 não é esse dono. O que fica registado é a opção que o
> próprio critério dá como omissão de construção — **(b)** — com o estado de
> **proposta**, o que já está construído nessa forma e o que ainda lhe falta.
> A D12 continua **ABERTA**.

---

## 1. O que esta metade da D12 decide, e o que não decide

A D12 junta duas perguntas que não têm nada em comum além do número
(`../../00_Arquitectura_Solucao.md` §13.3): o CDN/WAF que termina TLS como
subprocessador, e a licença do Redis (alternativa Valkey). **Este registo trata
só da primeira.** A segunda é do KAM-076 e está em
[`../../../adr/ADR-L009-ensaio-da-valkey.md`](../../../adr/ADR-L009-ensaio-da-valkey.md),
com o ensaio incompleto.

A pergunta: um proxy que termina TLS **vê o corpo** dos *webhooks* da Meta, que
são conversas. Se esse proxy for um CDN/WAF de terceiro, é **subprocessador com
acesso a conteúdo** e conta como transferência sob o ADR-008
(`../../08_Seguranca_Conformidade.md` §8.3.2) — se o é juridicamente é a
pergunta N1, enviada como **E-04** no pacote do parecer *(a confirmar por
parecer)*.

## 2. As duas opções

| Opção | O que é | Precisa de parecer? |
|---|---|---|
| **(a)** | O CDN fica à frente de tudo, e é **assumido como subprocessador**: entra no inventário, no mapa de tratamentos e na notificação à APD | Sim — a E-04 diz se basta a notificação |
| **(b)** | O caminho do *webhook* vai **directo à origem**, sem CDN; a assinatura `X-Hub-Signature-256` sobre o corpo bruto já autentica o pedido, e a origem protege-se com **limitação de débito** própria | Por hipótese, não — tira conteúdo do perímetro em vez de o justificar (`GoLive_Gate.md` §5). É **INDÍCIO** *(a confirmar por parecer)*: a E-04 pode dizer o contrário (ver §5) |

## 3. O registo

| Campo | Valor |
|---|---|
| Opção registada | **(b)** — caminho do *webhook* directo à origem, com limitação de débito na origem |
| Estado | **Proposta** (omissão de construção do critério 3 do KAM-077 e do `../../08` §15), **não decidida** |
| Dono | *em branco* — a Carta §4.2 dá o papel (SRE + jurídico), não a pessoa |
| Data da decisão | *em branco* |
| Registado por | Coordenação do lote 24, 2026-11-25, como preparação do KAM-077 |
| O que a fecha | O dono assina (b) ou escolhe (a); a E-04 respondida reabre-a se disser que (b) não basta |

## 4. O que a opção (b) exige, e o estado de cada parte

| # | Parte da (b) | Estado | Evidência |
|---|---|---|---|
| 1 | O *webhook* entra pelo proxy da própria origem, sem CDN | **Construído**, e corrigido nesta preparação | `../../../../infra/compose/caddy/Caddyfile`: `handle /wa/webhook` para o `gwy`. **A versão da `main` encaminhava `/webhooks/*`, que o GWY não serve** (o caminho dele é `/wa/webhook`, `services/gwy/src/webhook.ts`): medido num Caddy 2.10.2 com o Caddyfile da `main` à frente de um GWY simulado, o GET de verificação dava **404**; com a correcção, **200** e o *challenge* entregue. Nenhum serviço de CDN no compose |
| 2 | A assinatura autentica o pedido, sobre o corpo bruto | **Construído** (KAM-013) | `assinaturaValida` no GWY; o Caddyfile não reescreve o corpo |
| 3 | **Limitação de débito na origem** | **Não existe** | Medido: a imagem fixada do Caddy (`caddy:2.10.2-alpine`) tem **0** módulos de limitação de débito em `caddy list-modules`; o GWY não limita por origem. O descarte por profundidade da fila do GWY (critério 7 do KAM-013) protege o *worker*, não a origem, e não distingue quem envia. **Sem isto, (b) está incompleta** |
| 4 | Nenhum CDN à frente da origem | **Coerente com (b), não provado** | Nada no compose nem no Caddyfile põe um CDN à frente da origem. **Os documentos não o provam:** o `Mapa_Tratamentos_v1.md` mantém o CDN como **destino 8**, com a qualificação por confirmar (E-04), e o «não declarado» dele está na coluna das saídas declaradas — *egress* —, onde um proxy à frente da origem nunca apareceria. A `GoLive_Gate.md` linha E8 diz o mesmo. Que não há CDN só o prova o contrato da D1 (prova 1.1) |
| 5 | **Nenhum outro caminho com conteúdo atrás de um CDN** | **Por decidir com (b)** | A (b) escrita no `../../08` §15 só fala do *webhook*. Mas o `/app/*` do Chatwoot leva conversas, e o `/onboarding/*` leva dados da PME: um CDN à frente desses torna-se subprocessador pela mesma razão. Na prática, (b) só é (b) se **nenhum** caminho com conteúdo passar por um CDN — e então não há CDN nenhum |

**A parte 3 é a que falta, e a forma dela não se escolhe aqui.** Há pelo menos
dois sítios onde pode viver — um módulo de terceiro no Caddy (imagem nova,
*digest* novo, cadeia de fornecimento) ou um limite no próprio GWY —, e os
valores do limite seriam *proposta* sem medição de tráfego real da Meta. É
pergunta devolvida à coordenação, não trabalho desta preparação.

## 5. O que este registo não prova

- **Que a E-04 vai responder que (b) dispensa a notificação.** É o que o
  desenho assume; é **INDÍCIO** e está *(a confirmar por parecer)*.
- **Que nenhum proxy do fornecedor termina TLS à frente da origem.** Um
  *load balancer* gerido que termine TLS é o mesmo problema com outro nome; só
  se sabe com a D1 e o contrato (prova 1.1 de `provas/alojamento/`).
- **Que o 404 corrigido era o único defeito do caminho.** A prova foi com um
  GWY simulado e sem TLS; o GET e o POST reais, por HTTPS e de fora, são a
  prova 2.1 do KAM-077 depois da D1.

---

## 6. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| SRE (dono da D12, Carta §4.2) | | | |
| Responsável de Segurança | | | |
| Advogado externo (E-04) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, preparação do KAM-077 sem a D1. Regista a opção **(b)** da metade CDN/WAF da D12 como **proposta**, com dono e data **em branco** — a D12 continua ABERTA. Cinco partes da (b) com o estado de cada uma: duas construídas, uma coerente e não provada, uma por decidir e **uma em falta** (a limitação de débito na origem, medida como inexistente). E o defeito que a preparação apanhou e corrigiu: o Caddyfile encaminhava `/webhooks/*`, que o GWY não serve, e o GET de verificação dava 404 pela borda. | Coordenação do lote 24 |
