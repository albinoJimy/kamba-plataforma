# Billing da plataforma — a assinatura das PMEs, a dupla de ops e a factura-recibo

| Campo | Valor |
|---|---|
| Documento | `docs/billing.md` |
| Ticket | KAM-059 — Billing da plataforma: assinatura via PaymentProvider (beneficiário próprio) |
| Estado | **Proposta.** O ciclo, a cobrança e as barreiras estão na revisão do billing e medidos em `db/tests_pagamentos/test_subscricao_e_billing.py`; o processo da factura-recibo é manual e está **a confirmar por parecer** (D7) |
| Âmbito | Como a KAMBÁ cobra a assinatura às PMEs: o ciclo mensal, quem confirma um pagamento por transferência, e como se emite a factura-recibo. Não a régua de cobrança (KAM-058) nem a comissão, que no Piloto é só sombra |
| Fontes | `docs/tecnica/04` §9, §10.4, §11, §12 e §13; `specs/02` §3.66; ADR-004, ADR-013, ADR-017; D2, D4, D7, D8 |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

## 1. O ciclo

A KAMBÁ cobra a assinatura com a **mesma** interface de pagamento com que as PMEs cobram as
suas vendas, numa conta de `plataforma_receita_propria` — é isso que evita activar o tenant
`platform`, vedado por D2. Por cada subscrição `ativa` ou `em_atraso`, no início do período:

1. o *job* de abertura (`abrirCiclos`, em `../packages/core-ts/src/pagamentos/billing.ts`, como
   `kamba_pay`) lê o preço em vigor no **início** do período e abre o ciclo — ou nada, se já
   existe: a base tem um ciclo por subscrição e por período;
2. na mesma transacção, cria a cobrança (tentativa 1, válida **72 h**) na conta de receita
   própria, regista-a no *ledger* e põe o ciclo em `cobranca_emitida`;
3. quando o pagamento entra no *ledger* — autenticado pelo facilitador, ou confirmado por ops
   com dupla aprovação (§2) —, a base põe o ciclo em `paga` e emite o evento de ciclo pago, na
   mesma transacção do pagamento.

Num ciclo `paga` ou `anulado` não se cria cobrança nova (o gatilho `payment_charges_ciclo_vivo`).
Uma cobrança que já existia quando o ciclo foi anulado, se for paga, fica paga no *ledger* — o
dinheiro chegou — e o ciclo continua `anulado`, sem evento: cancelar a cobrança ao anular o ciclo,
e tratar o que chegar depois, é da régua.

**O agendamento do *job* não está ligado** a processo nenhum, nem a guarda de arranque da comissão
(§4): é do KAM-058, que é também quem põe uma subscrição em `em_atraso` e `suspensa`. Uma PME `em_atraso` **mantém os limites** até a
régua a suspender.

**Sem conta EMIS própria (D4, NÃO VERIFICADO)**, a cobrança do Piloto é por transferência: o
emissor é o `emissorManual` (método `manual`, sem referência), e as instruções de pagamento são
as `manual_instrucoes` da conta da KAMBÁ. O callback de um facilitador sobre a conta da KAMBÁ
**não tem caminho** ainda: o `resolve_webhook_token` devolve o `tenant_id` da conta, que é nulo,
e a cobrança do ciclo é do tenant que paga.

## 2. Confirmar um pagamento por transferência: a dupla de ops

A PME é quem paga, pelo que **não** confirma o próprio pagamento: o caminho do dono
(`manual_declarar`, `manual_confirmar`) recusa uma cobrança de ciclo. Quem confirma é ops, e o
`docs/tecnica/04` §9 manda que seja «com motivo e dupla aprovação»:

1. uma pessoa de ops lê o extracto bancário da KAMBÁ e aprova pela consola (`aprovarPorOps`):
   cobrança, valor lido e **motivo** — o motivo é obrigatório e diz de onde vem a prova
   («extracto bancário de 13/11, linha 42»), nunca dados do pagador;
2. **a primeira aprovação não conclui**. Fica registada (`billing_ops_approvals`) e a cobrança
   continua `emitida`;
3. uma **segunda pessoa**, diferente, faz o mesmo. A segunda aprovação escreve o pagamento no
   *ledger* (`authn_method = 'manual'`, `actor_kind = 'ops'`, com o motivo), e o ciclo fica
   `paga`.

A mesma pessoa a aprovar duas vezes não conta. Um valor diferente do da cobrança é recusado.

**O que a base garante, e o que não garante — dito sem eufemismo.** A base garante que o
pagamento de ops só entra com **dois `actor_id` diferentes**, cada um com motivo e com o valor da
cobrança, e que o evento é de um deles e de `ops`. **Não autentica pessoas**: o `actor_id` é a
identidade da equipa que a consola autenticou no IdP, com MFA (KAM-196), e um chamador com a
credencial do papel de billing que inventasse dois identificadores passava. A barreira contra isso
é a da consola e a da credencial, e não a da base. O que a base fecha por inteiro é o outro lado:
**o ledger de um ciclo só se escreve numa ligação do `kamba_pay`** (o gatilho
`payment_events_billing_papel`), pelo que nem os turnos do agente nem nenhum processo de uma PME —
que corre como `kamba_app`, no contexto da PME que deve — consegue pagar o próprio ciclo, nem com
um pagamento «autenticado» escrito à mão na porta do ledger. E o `kamba_pay` só escreve no ledger
dos ciclos, nunca no das encomendas.

## 3. A factura-recibo da assinatura

**Nenhum documento fiscal sai do código da KAMBÁ** (DP 71/25, CONFIRMADO: emitir sem software
validado pela AGT não é válido; `docs/tecnica/04` §13). A porta `InvoiceProvider` está declarada
em `billing.ts` com os seis métodos do §13 e **não tem implementação**: é Clusters, com o
parceiro certificado por decidir (D7). Um ensaio do `pagamentos.billing.test.ts` afirma que
nenhuma classe a implementa e que nenhuma função ou rota emite factura.

**No Piloto, o processo é manual e registado** — *(a confirmar por parecer)*:

1. o evento de ciclo pago é o gatilho: ops tem a lista dos ciclos `paga` do dia;
2. ops emite a factura-recibo da assinatura **no software de facturação certificado pela AGT que
   a KAMBÁ contratar** (D7), com os dados do ciclo — os dados fiscais da PME (os que o registo do
   tenant tiver; quais são exigidos é parte do parecer), o período, o plano e o valor;
3. o número fiscal da factura-recibo fica registado no software certificado, que é o registo
   fiscal; a referência dele guarda-se junto do ciclo quando houver a tabela de pedidos de
   factura do §13 (`invoice_requests`, Clusters);
4. o envio do documento à PME é pelo canal de avisos ao dono.

O que fica **NÃO VERIFICADO** e não se decide aqui: o software (D7) e se o regime da KAMBÁ a
obriga já à e-factura (fase 2 a 01-01-2027, INDÍCIO forte, `docs/tecnica/04` §13); se o
`valor_minor` do precário inclui IVA, e a taxa (`iva_pct` 14,00 por omissão, a confirmar com
contabilista); e o prazo de conservação fiscal (CGT).

## 4. A comissão é sombra

`commission_enabled` está desligada por omissão, global e por tenant, e ligá-la sem
`parecer_ref` (D8) **recusa o arranque** (`verificarComissao`). Mesmo com parecer, a base só
aceita `modo = 'sombra'` (`commission_accruals_so_sombra`): passar a facturar comissão é uma
revisão nova que cite o parecer, e nunca uma *flag*. A sombra mede *unit economics* sobre os
pagamentos autenticados pelo facilitador — nunca se factura e nunca se retém (ADR-004, ADR-017).
A taxa da sombra não tem omissão: é «por contrato» e não está decidida.

## 5. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | KAM-059: emissão inicial — o ciclo, a dupla de ops, o processo manual da factura-recibo e a comissão em sombra. | Equipa KAMBÁ |
