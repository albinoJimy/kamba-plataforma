# ADR-L011 — AppyPay como segundo facilitador: **adiar**, com gatilhos escritos

| Campo | Valor |
|---|---|
| Estado | **Proposto** |
| Data | 2026-11-08 |
| Ticket | KAM-057 — Avaliação do segundo facilitador (AppyPay) e matriz de decisão |
| Âmbito | Local (ver [`README.md`](README.md)): **se** e **quando** se escreve um adaptador AppyPay atrás da interface `PaymentProvider`, e com que `ProviderCapabilities`. **Não** escolhe o primeiro facilitador — isso é D4, que continua aberta —, **não** fecha H5, e **não** emenda nenhum ADR canónico |
| Decisores | **O fundador**, por ratificar. A revisão por Arquitecto de Plataforma e por Responsável de Produto que o critério 6 do ticket pede **não foi feita** |
| ADRs canónicos aplicáveis | ADR-004 (liquidação directa à PME; a plataforma nunca detém fundos) e ADR-013 (pagamento só por evento autenticado), em [`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md) §8; e ADR-017 (comissão desligada no Piloto) |
| Documentos aplicáveis | [`../pagamentos/matriz_facilitadores.md`](../pagamentos/matriz_facilitadores.md) (a matriz, as fontes e o custo); [`../pagamentos/perguntas_appypay.md`](../pagamentos/perguntas_appypay.md) (as perguntas redigidas); [`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`](../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md) §3.1, §3.4, §3.5, §5, §10.4; [`../tecnica/evidencia/validacao/Pagamentos_Respostas.md`](../tecnica/evidencia/validacao/Pagamentos_Respostas.md) §5 (a regra de D4 do KAM-103) |
| Substitui | — |

**Porque é um `ADR-L` e não o canónico seguinte.** O critério 6 do ticket pede «numeração após
ADR-019», e os «Detalhes Técnicos» do bloco apontam a saída para um ficheiro em `docs/decisoes/`. As duas indicações
vêm de antes de o `ADR-020` existir e de o espaço `ADR-L` ser fixado. Seguiu-se a regra do
[`README.md`](README.md) deste directório, que é a leitura em vigor de «numerar após o último
canónico» para uma decisão de **execução**, e o precedente do KAM-010, cujo critério tinha a mesma
frase e fechou com o `ADR-L002`. Esta decisão não governa outro subsistema nem contradiz um ADR
canónico, que é o critério do README para subir a canónica. **A leitura vai ao fundador** com a
divergência escrita, como o KAM-116 fez com a mesma frase.

---

## 1. Contexto e problema

O Piloto confirma pagamentos com o `ManualProvider` até haver contrato com um facilitador
(`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §1.2). O ProxyPay é o preferido da arquitectura
porque tem *webhook* com HMAC e fila de reconciliação, ambos CONFIRMADOS — e não tem preço público
nem confirmação escrita da liquidação directa (`../tecnica/evidencia/validacao/Pagamentos_Respostas.md`
§5.2). A AppyPay cobre num só contrato Express, referência, débito directo **e Unitel Money**, tem
preço público, e declara não intervir no fluxo financeiro. (O débito directo vem marcado `[ALPHA]` na documentação dela, e o eTPA `[BETA]`.)

A pergunta que este ADR responde: **escreve-se um adaptador AppyPay, agora, como segundo
facilitador?**

O que a tornava impossível de responder até aqui era a documentação técnica, que nunca tinha sido
lida. A 2026-11-08 leu-se, e a [`matriz`](../pagamentos/matriz_facilitadores.md) dá o resultado
em dezanove critérios. Os quatro que decidem:

| Factor | Estado (matriz §3) |
|---|---|
| *Webhook* assinado | **NÃO VERIFICADO** — a documentação publicada não mostra assinatura nenhuma; silêncio, não negativa |
| Consulta de estado | **CONFIRMADO como documentação** — `GET /charges/{id}` e filtro por `merchantTransactionId`; **comportamento por medir** |
| Liquidação directa à PME | **CONFIRMADO** — termos, cl. 1.5 |
| Acesso ao ambiente de testes, prazo de *onboarding*, componente bancário do custo | **NÃO VERIFICADO** os três |

## 2. Factores de decisão

1. **ADR-013 é um portão, não um peso.** O critério 4 do ticket escreve-o: só se implementa o
   adaptador se o *webhook* for assinado **ou** existir consulta de estado confirmada por escrito.
2. **ADR-004 é outro portão.** Nenhuma opção pode exigir que a KAMBÁ detenha fundos ou execute
   *payouts*.
3. **D4 está aberta.** Um «segundo» facilitador pressupõe um primeiro, e o primeiro não está
   escolhido.
4. **Um adaptador sem suite de conformidade verde não é activável** (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`
   §3.5), e a suite precisa de credenciais de testes que não existem.
5. **Não se decide sobre NÃO VERIFICADO.** O que não ficou verificado vai para o relatório
   (matriz §6), e cada NV tem pergunta ou saída (matriz §3, última coluna).

## 3. Opções consideradas

| Opção | O que significa | Contra | A favor |
|---|---|---|---|
| **A. Adoptar agora** | Escrever o adaptador AppyPay já, atrás de *flag* | D4 aberta, sem contrato, sem credenciais, sem suite possível; o prazo e o custo bancário são NV; o portão do ADR-013 só passa por uma leitura que é do fundador (§5) | Unitel Money e preço público; a consulta de estado documentada daria um caminho autenticado |
| **B. Adiar, com gatilhos escritos** | Não escrever adaptador; fixar o que tem de chegar para reabrir, e o rascunho de `ProviderCapabilities` que o adaptador teria | Deixa o Unitel Money sem cobertura integrada no Piloto, **se** a ProxyPay de facto não o oferecer — o que é INDÍCIO de ausência, por confirmar na resposta à pergunta 7 | Não decide sobre nenhum NV; não contradiz ADR-004 nem ADR-013; nada do que se escreveu hoje se perde |
| **C. Rejeitar** | Retirar a AppyPay dos candidatos | Nenhum critério a desqualifica: os dois portões de canon passam ou estão por decidir, e nenhum falha | — |

## 4. Decisão (proposta)

**Opção B — adiar.** Numa frase: a documentação pública confirma a consulta de estado e a
liquidação directa, mas o *webhook* não mostra assinatura, o acesso ao *sandbox*, o prazo de
*onboarding* e o componente bancário do custo continuam NÃO VERIFICADOS e D4 está aberta — não há
o que adoptar, e também não há razão para rejeitar.

### 4.1 A regra de implementação (critério 4 do ticket)

> **Só se escreve o adaptador AppyPay se o *webhook* for assinado OU existir consulta de estado
> confirmada por escrito (ADR-013).** Com a consulta e sem a assinatura, o *webhook* é apenas uma
> **dica**: o PAY chama `status()` e só então avalia G2–G7, com `authn_method='consulta'`
> (`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5). Com nenhuma das duas, o adaptador **não
> pode** confirmar `paga` sozinho e não se escreve.

### 4.2 Os gatilhos que reabrem esta decisão

| # | Gatilho | Quem o produz | Leva a |
|---|---|---|---|
| 1 | D4 fechada com um primeiro facilitador escolhido, **ou** com a AppyPay como primeiro | o fundador | reabrir; sem ele, «segundo» não tem sentido |
| 2 | Resposta escrita à **pergunta 12** que confirme **o *webhook* assinado** ou **a consulta de estado como confirmação válida de uma referência paga depois**, **ou** ratificação da leitura 1 do §5. Uma resposta que negue as duas cai no §4.3 | o fundador | o portão do ADR-013 passa |
| 3 | Credenciais de testes (**pergunta 11**) e a suite §3.5 verde, incluindo «`status()` concorda com o *callback*» e uma referência paga depois de emitida | o fundador pede as credenciais; o executor do adaptador corre a suite | o adaptador é activável |
| 4 | Respostas às perguntas **11-a**, **1** e **2** (prazo e componente bancário) | o fundador | a pontuação da regra de D4 do KAM-103 pode passar o mínimo |

### 4.3 O que faz rejeitar

- **ADR-013:** a resposta escrita diz que o *webhook* não é assinado **e** a suite mostra que o
  `GET /charges/{id}` não reflecte o pagamento de uma referência feita depois. Sem nenhuma das duas
  vias, não há confirmação autenticada.
- **ADR-004:** a resposta à pergunta 15 descreve um modelo em que a entidade ou a liquidação são da
  plataforma e não da PME — o desenho B.
- A resposta à pergunta 14 mostra que o FTBAI é condição do contrato ou do modelo de parceiro.

## 5. Leituras devolvidas ao fundador

1. **A documentação pública conta como «confirmada por escrito»?** A regra de classificação do
   KAM-103 (`../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §2.1) dá «página oficial do
   fornecedor» como CONFIRMADO. Por essa regra, a consulta de estado da AppyPay está confirmada por
   escrito e o portão (a) da regra de D4 passa — o que inverte a linha da AppyPay no §5.2 daquele
   documento, onde estava «não satisfeito». **A leitura que este ADR propõe:** conta para a
   **existência** da consulta, e não dispensa o caso da suite que mede o **comportamento**. Quem
   escreveu o portão é que decide se é assim; até lá, o §5.2 do KAM-103 não se edita.
2. **O número e o sítio deste ADR** (ver o parágrafo antes do §1).

## 6. Rascunho de `ProviderCapabilities` da AppyPay

Os campos são os do tipo **já implementado** pelo KAM-052 em
`packages/core-ts/src/pagamentos/tipos.ts` — os onze que o
`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.1 enumera, mais `humanOnly` e `pspLicenciado`.
**É um rascunho**: não é código de produção, não se importa de lado nenhum, e cada valor leva o
estado da matriz. Os ids `S*` são as fontes da matriz §1.2.

```ts
// RASCUNHO (KAM-057) — o que o adaptador AppyPay declararia. Não é código de produção.
// `NAO_VERIFICADO` não existe de propósito: enquanto um campo o usar, o rascunho não compila.
const appypay: ProviderCapabilities = {
  // CONFIRMADO (S8): GPO e REF. UMM e SDD também existem (o SDD em ALPHA), mas o tipo `Metodo`
  // não os tem; acrescentá-los é emenda à interface, e não deste rascunho.
  metodos: ['referencia', 'express_push'],

  // NÃO VERIFICADO (S1 não documenta assinatura). Fica 'desconhecido', como o OPG no KAM-056,
  // até resposta à pergunta 12. Com statusQuery=true o callback é dica (doc 04 §5).
  callbackAuth: 'desconhecido',

  // CONFIRMADO como documentação (S3, S4). O comportamento mede-se na suite §3.5 antes de
  // activar, com o mapeamento dos cinco estados de S9 (Cancelled e Expired incluídos).
  statusQuery: true,

  // Nenhuma fila de não-reconhecidos documentada (S4 é uma listagem por datas, sem reconhecimento).
  reconciliationQueue: false,

  // O GPO suporta reembolso total ou parcial (S11), mas o reembolso automático está desligado
  // por canon: ADR-004, guardas G-2 e G-6.
  refund: false,

  // ADR-004, guarda G-2. O FTBAI existe (S10) e não se usa.
  payout: false,

  // Em segundos. A referência expira por omissão às 72 h (S8) — omissão, não mínimo nem máximo.
  // Mínimo e máximo: NÃO VERIFICADOS.
  chargeTtl: { min: NAO_VERIFICADO, max: NAO_VERIFICADO },

  // Em segundos. NÃO VERIFICADO: nenhum cabeçalho de idempotência documentado; o duplicado é
  // recusado (código 726 de S9), o que não é uma janela. Pergunta 12-a.
  idempotencyWindow: NAO_VERIFICADO,

  // `amount` é number<double> (S5, exemplo 100.2), com separador '.' (S1, exemplo 225.7): um número
  // JSON e não uma cadeia. «Duas casas» NÃO está documentado — 'decimal2' é o valor mais próximo
  // do tipo, não uma leitura. A conversão de `Minor` faz-se no adaptador e nunca por aritmética de
  // vírgula flutuante sobre o valor.
  amountFormat: 'decimal2',

  // CONFIRMADO (S1, S5): `merchantTransactionId` de 1 a 15, `^[a-zA-Z0-9]+$`.
  refMaxLen: 15,

  // CONFIRMADO (S13, E2). D+ por banco: NÃO VERIFICADO.
  settlement: 'directa à PME pela EMIS; Express no fecho do TPA virtual, referências às 20:00',

  // A confirmação é por consulta autenticada, não humana.
  humanOnly: false,

  // A AppyPay declara não intervir no fluxo financeiro (S12, cl. 1.5) e não figura como PSP (E2 §1.6).
  pspLicenciado: false,
};
```

**O `activar()` de `packages/core-ts/src/pagamentos/registo.ts` não verifica os campos que este
rascunho deixa por preencher** — verifica `humanOnly`, `callbackAuth`, `statusQuery` e a
conformidade. Por isso a guarda contra activar com valores inventados é o rascunho **não compilar**
enquanto houver um `NAO_VERIFICADO`, e não uma recusa do PAY.

## 7. Consequências

**Positivas.** O Piloto não ganha código que não pode testar. A decisão não depende de nenhum NV.
Os gatilhos são escritos, e cada um tem quem o produz. O rascunho de capacidades fica pronto para o
dia em que os gatilhos 1 a 3 chegarem.

**Negativas.** O Unitel Money fica sem via integrada no Piloto se a ProxyPay não o oferecer — o que
é INDÍCIO de ausência (matriz §3, linha 9), a confirmar na resposta à pergunta 7. Nesse caso, a PME
que só receba por carteira fica em `ManualProvider`.

**Uma consequência de desenho que fica para o adaptador, e não se resolve aqui.** O
`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.4 usa o `numero_publico` da encomenda como
`merchantTransactionId`. Uma encomenda pode ter **mais do que uma cobrança** — expira e volta a
cobrar-se —, e a documentação da AppyPay **recusa o identificador repetido** (código 726 de S9,
CONFIRMADO como documentação): a segunda cobrança da mesma encomenda seria recusada. O que fica
**NÃO VERIFICADO** é se a unicidade deixa de valer depois de a primeira cobrança expirar, e se o 726
é mesmo o do `merchantTransactionId` (o texto inglês diz «reference number», o português
«referência do comerciante»). **Proposta**, a confirmar pela pergunta 12-a ou na suite:
`numero_publico` seguido de um sufixo de tentativa no mesmo alfabeto, até aos 15 caracteres.

---

## 8. Verificação contra o canon

| ADR | O que exige | Esta decisão |
|---|---|---|
| **ADR-004** | Liquidação directa à PME; a plataforma nunca detém fundos; *payouts* só por PSP licenciado e fora do Piloto | Não adopta nada. O rascunho declara `payout: false` e `refund: false`, exclui o FTBAI, e o §4.3 faz rejeitar qualquer modelo de parceiro com entidade ou liquidação da plataforma. **Não contradiz** |
| **ADR-013** | `paga` só por evento autenticado | O §4.1 é a regra do ADR-013 por escrito; sem assinatura, o *callback* é dica e a confirmação vem de `status()`. **Não contradiz** |
| **ADR-017** | Comissão sobre transacção desligada no Piloto | O custo por transacção do §4 da matriz é da PME e não entra no preço da assinatura. **Não contradiz** |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-057), estado **proposto**: adiar, com quatro gatilhos escritos, três condições de rejeição, o rascunho de `ProviderCapabilities` e duas leituras devolvidas ao fundador. | Equipa KAMBÁ |
