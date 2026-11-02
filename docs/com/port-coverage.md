# Cobertura da porta `CommerceRegistry` — quem implementa o quê

| Campo | Valor |
|---|---|
| Ticket | KAM-042 — Porta `CommerceRegistry` e adaptador (critério 6) |
| Fonte normativa | [`specs/EPIC-04_Core_Comercio.md`](../../specs/EPIC-04_Core_Comercio.md), bloco KAM-042 |
| Contrato | [`docs/tecnica/03_Core_Comercio_Medusa.md`](../tecnica/03_Core_Comercio_Medusa.md) §3.2 |
| Código | [`services/com/src/port/contrato.ts`](../../services/com/src/port/contrato.ts), [`services/com/src/adapters/medusa/`](../../services/com/src/adapters/medusa/) |
| Registo activo | **opção B** (Medusa puro + módulo `merchant`) — *recomendação* do KAM-041, **não ratificada** (D3) |

> **Nada está ratificado.** A opção B é a recomendação do spike KAM-041
> (2026-10-27). A decisão D3 em
> [`docs/tecnica/00`](../tecnica/00_Arquitectura_Solucao.md) §13.3 diz, por
> escrito, que «falta a assinatura do Arquitecto de Plataforma e do Responsável
> de Segurança, e a ratificação do fundador». O ADR-003 continua a nomear a
> opção C como *fallback*, e este documento não o contradiz.

---

## 1. Para que serve este documento

O critério 6 do KAM-042: «Métodos cuja implementação pertence a tickets
posteriores devolvem `NOT_IMPLEMENTED` e estão listados em
`docs/com/port-coverage.md` com o ticket dono; cada um tem teste de isolamento
marcado *xfail strict* que falha quando a implementação chegar sem teste.»

**Hoje os doze devolvem `NOT_IMPLEMENTED`**, e isso é o resultado honesto do
KAM-042 e não uma entrega a meio: o ticket entrega a **porta**, a barreira de
isolamento e a *pipeline*; cada método é de um ticket a jusante, e nenhum deles
está `Done`. O que o KAM-042 entrega e que **não** é adiado está no §3.

## 2. Os doze métodos e o ticket dono

| # | Método | Ticket dono | O que falta para deixar de ser `NOT_IMPLEMENTED` |
|---|---|---|---|
| 1 | `upsertProductDraft` | **KAM-043** | Produtos e variantes no Registo; `offer_terms` em rascunho |
| 2 | `publishProduct` | **KAM-043** | A confirmação do dono e o `screening` de categoria restrita (§8.2) |
| 3 | `getOfferView` | **KAM-043** | Os três `preco_tipo` e os três `stock_modo` (§7.1, §7.3) |
| 4 | `createOrder` | **KAM-044** | `orders_mirror` + `order_intents`; a *saga* e a chave por intenção (§6.3). O KAM-046 acrescenta-lhe o `propose_cart` |
| 5 | `requestOwnerConfirmation` | **KAM-044** | `orders_mirror.confirmacao_dono` e o aviso ao dono (KAM-115) |
| 6 | `reserveStock` | **KAM-045** | `stock_reservations` e o `UPDATE … WHERE quantidade - reservada >= :q` (§6.4) |
| 7 | `extendReservation` | **KAM-045** | O tecto de 72 h e a validade da cobrança correspondente |
| 8 | `commitReservation` | **KAM-045** | O consumidor de `payment.confirmed` e de `payment.manual_confirmed` |
| 9 | `releaseReservation` | **KAM-045** | A consulta final a PAY antes de libertar (§6.5) |
| 10 | `transition` | **KAM-044** | `order_state_graph`, o CAS por `version` e o `order_state_log` (§6.2) |
| 11 | `getOrder` | **KAM-044** | `orders_mirror` com RLS `FORCE` |
| 12 | `listOrders` | **KAM-044** | O cursor opaco e os filtros do ISO-10 |

**São doze, e não onze.** O objectivo do bloco KAM-042 e a linha do dicionário
§3.38 escrevem «onze métodos»; o §3.2 do `docs/tecnica/03`, que é a fonte do
contrato, lista doze, e o critério 1 do mesmo bloco nomeia os doze um a um. A
contagem está corrigida nos dois sítios pelo PR do KAM-042, e fica registada
aqui porque uma contagem que anda em três documentos é o modo de falha que este
conjunto já pagou quatro vezes. A contagem está presa em
`services/com/tests/port.contrato.test.ts`.

## 3. O que não é `NOT_IMPLEMENTED`

Estas quatro propriedades são do KAM-042 e valem **hoje**, nos doze métodos.
Nenhuma muda entre a opção B e a opção C — é por isso que a porta e o repo-base
não vivem dentro do adaptador.

| Propriedade | Onde | Como se verifica |
|---|---|---|
| `ctx` obrigatório, falha fechada | `port/contrato.ts` → `exigirCtx` | `tests/port.iso.test.ts`: as doze operações com `ctx` sem `tenantId` lançam, **e sem pedir ligação** (o cliente de ensaio explode se lhe falarem) |
| `merchant_id` do `platform.tenants` e nunca de um argumento | `repo-base/index.ts` → `idsDoRegisto` | `tests/repo-base.test.ts`: um tenant com a coluna a `NULL` falha fechado |
| Nenhuma consulta ao Registo sem o filtro | `repo-base/index.ts` → `repoBase` | `tests/repo-base.test.ts`: a consulta recusada **não chega** à base |
| Canal e localização por tenant, idempotentes | `adapters/medusa/provisionamento.ts` | `tests/provisionamento.test.ts`: a ordem, a idempotência e o `UPDATE` que só preenche o vazio |

## 4. O `xfail strict`, e porque não é um `todo`

O critério pede «*xfail strict*», que é vocabulário do pytest. O `node:test` não
o tem: um `{ todo: true }` que **passa** é reportado como *todo* e **não** falha
a suite, que é o contrário de «strict».

A forma com a semântica certa está em `tests/port.iso.test.ts` e é mais simples
do que uma marca: **afirmar o `NOT_IMPLEMENTED`**. Enquanto o método não estiver
implementado, a asserção passa. No dia em que alguém o implementar e não
substituir o caso pelo teste de isolamento a sério, a asserção **falha** — com a
mensagem a dizer o ticket dono e o que a substitui:

```text
<metodo> deixou de devolver NOT_IMPLEMENTED.
O ticket dono e o KAM-0NN: substitui este caso pelo teste de isolamento a
serio — ctx do tenant A sobre um id do tenant B tem de dar TENANT_MISMATCH ou
NOT_FOUND, nunca a linha de B. E actualiza docs/com/port-coverage.md.
```

## 5. A suite ISO: o que está medido e o que não está

| Casos | Estado | Onde |
|---|---|---|
| ISO-09 (sem `tenantId`) | **verde**, nos doze métodos | `tests/port.iso.test.ts` |
| ISO-01..08 (`ctx` de A sobre ids de B) | **não medidos** — precisam de uma operação que leia algo | `xfail strict` neste ficheiro |
| ISO-10 (filtro vazio, cursor forjado, `OR`) | **não medido** — um caso, a partir por três quando o `listOrders` existir | idem |
| ISO-11..32 (Store API, Admin API, *query graph*) | **medidos só no KAM-041**, e o **ISO-15 está vermelho lá**: a Store API serviu a encomenda de um tenant a uma chave publicável de outro. Exigem um Medusa a correr, e não há nenhum em `infra/compose/` | `spikes/medusa-d3/resultados/iso.json` |
| ISO-33..56 | **não medidos aqui**; são de reservas, SKU e concorrência (KAM-043, KAM-045) | — |
| ISO-57..60 (`tenant_id` no texto) | **ignorados**, pelo critério 2 do bloco, por escrito | — |

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | **KAM-042, critério 6.** Primeira versão: os doze métodos com o ticket dono, as quatro propriedades que não são adiadas, a forma do `xfail strict` no `node:test` e o estado medido de cada gama da suite ISO. A contagem «onze métodos» do objectivo do bloco e do dicionário §3.38 fica registada como corrigida para **doze**, que é o que o `docs/tecnica/03` §3.2 lista e o critério 1 nomeia. | Equipa KAMBÁ |
