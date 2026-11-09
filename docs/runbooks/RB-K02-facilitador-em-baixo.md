# Runbook RB-K02 — Facilitador de pagamentos em baixo

| Campo | Valor |
|---|---|
| ID | **RB-K02** |
| Versão | 1.0 |
| Cenário | A criação de referências falha, os *callbacks* do facilitador param ou chegam inválidos, ou há pagamentos que o cliente fez e nós não reconhecemos |
| Severidade | **P1** |
| Alertas que o activam | **Nenhum, hoje.** As quatro regras do catálogo estão por escrever (`ops/metricas/catalogo.yaml`, `regras_por_escrever`): DLQ de `payment.*`, *callbacks* (HMAC > 3/h ou pagamento por reconhecer), anomalia ≥ 3 e órfão > 24 h. **E a dos *callbacks* nomeia a métrica errada** — ver §0 |
| Gatilho manual | Uma PME diz que o cliente pagou e a encomenda não confirmou; referências a falhar nos logs; as consultas do §2 |
| Nível de degradação | **N4** (doc 09 §12): referência «segue em breve» ou `ManualProvider` com limite; reservas estendidas; **nunca** marcar paga sem evento |
| Dono | Plataforma/SRE, com o Responsável de Produto para as confirmações manuais |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Mesa-redonda, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3. Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K02; §12, N4 |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

Este é o runbook com menos sistema por baixo, e o operador tem de o saber antes do
primeiro passo:

- **Não há adaptador do ProxyPay** nem de nenhum facilitador real. Existe a interface
  (`PaymentProvider`, `packages/core-ts/src/pagamentos/tipos.ts`), o simulador
  (`fake.ts`) e o `ManualProvider`; nenhum serviço os importa para cobrar.
- **Não há reconciliador do facilitador** (KAM-056, por fazer). O desenho — *polling* de
  5 em 5 min por conta activa, `GET /payments`, `DELETE /payments/{id}` depois do
  *commit* — está só em [`../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`](../tecnica/04_Pagamentos_Liquidacao_AntiFraude.md).
  Os dois «reconciliadores» que existem no código **não são este**: o
  `eventos/reconciliador.ts` é do *outbox* e o `orders/reconcile.ts` é do espelho de
  encomendas.
- **A rota dos *callbacks* (`/hooks/pay/:provider/:webhook_token`) não está montada** em
  nenhum serviço (`atenderCallback`, `pagamentos/hooks.ts`).
- **O catálogo associa a este runbook a métrica errada.** O
  `hnd_callback_rejeitado_total` conta os *callbacks* do **Chatwoot** recusados
  (`packages/core-ts/src/hnd/assinatura.ts`), não os do facilitador. O sinal de HMAC de
  pagamento é o `fraud_signals_total{regra="hmac_invalido_em_massa"}`, servido pelo
  processo de pagamentos do COM na porta 3013 — que o Prometheus **não raspa** (raspa a
  3002) e que nenhum processo alimenta. Achado registado em
  [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §5.
- **O agendador da expiração das reservas não está ligado** (KAM-071): hoje as reservas
  não expiram sozinhas, e «alargar o TTL» não tem efeito a evitar. Também não há rota nem
  comando para o alargar (`extendReservation` existe só como função).

O que **existe** e vale a pena saber: as tabelas do *ledger* de pagamentos e a regra na
base de que uma cobrança **não passa a `paga` sem autenticação** (`hmac`, `consulta` ou
`manual`; restrição `confirmar_exige_autenticacao`, revisão 0029).

## 1. Cenário e gatilho

| Ramo | Sinal | Vai para |
|---|---|---|
| **A — referências não se criam** | erro 5xx ou 429 do facilitador ao emitir | §3.1 |
| **B — *callbacks* parados** | nenhum *callback* recebido em horário comercial com cobranças emitidas | §3.2 |
| **C — *callbacks* inválidos** | falhas de autenticação > 3 por hora | §3.3 |
| **D — pagamento por reconhecer** | a PME ou o cliente diz que pagou; a reconciliação encontra-o | §3.4 |

O ramo C distingue-se dos outros por ter, quase sempre, causa nossa: uma rotação de chave
mal feita ([RB-K07](RB-K07-rotacao-de-segredos.md)) — a chave da API do ProxyPay **é** a
chave do HMAC.

## 2. Diagnóstico

As quatro consultas são de leitura e correm com o utilizador do contentor (atravessa a
RLS). Todas `verificado` contra uma base com as migrações até à 0039, a 2026-11-09
([`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2); `não verificado` contra
produção, onde hoje devolvem vazio pelo §0.

```bash
# 1. Cobranças à espera, por tenant e facilitador, a mais antiga primeiro
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT tenant_id, provider, estado, count(*) AS n, min(criado_at) AS mais_antiga
      FROM platform.payment_charges
     WHERE estado IN ('\''emitida'\'','\''aguarda_cliente'\'','\''pendente_confirmacao'\'')
     GROUP BY 1, 2, 3 ORDER BY mais_antiga"'
```

```bash
# 2. Callbacks nas últimas 24 h, por hora: quantos chegaram e quantos falharam a autenticação
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT date_trunc('\''hour'\'', recebido_at) AS hora,
           count(*) FILTER (WHERE authn_ok IS FALSE) AS falhas_de_autenticacao,
           count(*) AS recebidos, max(recebido_at) AS ultimo
      FROM platform.payment_callbacks_inbox
     WHERE recebido_at > now() - interval '\''24 hours'\''
     GROUP BY 1 ORDER BY 1 DESC"'
```

```bash
# 3. Eventos de pagamento na DLQ (Sev1 pelo prefixo payment.)
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT consumer, tipo, count(*) AS abertas, min(criado_at) AS mais_antiga
      FROM platform.events_dlq
     WHERE estado = '\''aberta'\'' AND tipo LIKE '\''payment.%'\''
     GROUP BY 1, 2"'
```

```bash
# 4. Reservas de stock que expiram nas próximas 2 h
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT count(*) AS a_expirar_em_2h, min(expira_at) AS primeira
      FROM platform.stock_reservations
     WHERE estado = '\''ativa'\'' AND expira_at < now() + interval '\''2 hours'\''"'
```

**Do lado do facilitador:** o estado do serviço pelo canal técnico do facilitador (lista
de contactos, linha 3), e o estado do banco ou da EMIS se o facilitador apontar para lá.
A consulta directa (`GET /payments`) **não se faz à mão** a partir deste runbook: usa a
chave da API, que é segredo de plataforma, e não há ferramenta que a leia do cofre sem a
expor num terminal.

## 3. Mitigação

### 3.1 Ramo A — referências não se criam

1. Confirmar com o facilitador (canal técnico) que a falha é dele.
2. Entrar em **N4**: o cliente recebe «a referência segue em breve» e o pedido fica em
   fila — **quando houver** o fluxo; hoje não há adaptador (§0).
3. Se a falha dura mais de 1 h em horário comercial, o Responsável de Produto decide se
   activa o **`ManualProvider`** para os *tenants* afectados. Os limites são por
   *tenant* (`manual_max_minor`, `manual_dupla_acima_minor`, `manual_daily_max_minor`,
   `manual_max_por_contacto_24h`); **sem valor, recusa** — não há «sem limite».

### 3.2 Ramo B — *callbacks* parados

1. Consulta 2 do §2: o `ultimo` é antigo e a consulta 1 tem cobranças `emitida`?
2. Separar «o facilitador não envia» de «nós não recebemos»: o *proxy* de entrada
   (`proxy-tls`) e os logs do serviço que monta a rota — hoje nenhum (§0).
3. Reconciliar por *polling* — **sem ferramenta** até ao KAM-056. Enquanto não houver, a
   reconciliação é a PME a conferir os pagamentos no painel do facilitador.

### 3.3 Ramo C — *callbacks* inválidos

1. Houve rotação da chave do facilitador (`proxypay_api_key`) nas últimas horas? Se sim,
   é o [RB-K07](RB-K07-rotacao-de-segredos.md): a chave da API é a chave do HMAC, e o
   inventário diz que não há janela dupla — o reconciliador tem de estar activo durante
   a troca.
2. Se não houve rotação, é tentativa de forjar pagamentos: **[RB-K10](RB-K10-incidente-de-seguranca.md)**,
   classe P1 («pagamento forjado», `08` §10).

### 3.4 Ramo D — pagamento por reconhecer

1. **Nunca confirmar por imagem.** Um comprovativo enviado pelo cliente não é evento de
   pagamento; a base recusa confirmar sem `hmac`, `consulta` ou `manual`.
2. Confirmar no painel do facilitador que o pagamento existe, com a referência.
3. Confirmar pelo acto humano auditado — `platform.manual_confirmar(...)`, revisão 0032 —
   que é o único caminho manual, deixa linha no `audit_log` (`payment.manual_confirm`) e
   está sujeito à dupla confirmação acima do limite do *tenant*. É **decisão do
   Responsável de Produto**, uma a uma. `não verificado` neste runbook: a assinatura da
   função está no dicionário §3 e na revisão 0032.

## 4. Critério de recuperação

- a consulta 1 do §2 deixa de ter cobranças `emitida` mais antigas do que a validade da
  referência;
- a consulta 2 mostra *callbacks* a chegar, com `falhas_de_autenticacao` a 0;
- a consulta 3 não tem DLQ de `payment.*` aberta;
- cada pagamento reconhecido à mão tem a sua linha `payment.manual_confirm` no `audit_log`.

## 5. Escalamento

Primário → secundário (15 min) → Arquitecto. De fora: o canal técnico do facilitador
(lista de contactos). Callbacks forjados → **RB-K10**.

## 6. Comunicação

**À PME — proposta, por aprovar pelo Responsável de Produto.** Por e-mail (envio manual
até o fornecedor de e-mail estar aprovado — ver RB-K01 §6).

> **Assunto:** KAMBÁ — pagamentos por referência com atraso
>
> Caro parceiro,
>
> Desde as {hora} (hora de Luanda) o serviço de pagamentos por referência está com
> falhas do lado do {facilitador}. Os pagamentos já feitos pelos seus clientes não se
> perdem: confirmamos cada um assim que o serviço voltar.
>
> Até lá, pedimos que **não entregue encomendas com base em fotografias de
> comprovativos** — confirme sempre o pagamento connosco antes.
>
> Voltamos a escrever quando estiver resolvido.
>
> Equipa KAMBÁ

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| ProxyPay: a chave da API é a chave do HMAC do *callback* (`X-Signature`) | do desenho — **INDÍCIO**, sem adaptador que o exercite | `docs/tecnica/04`; `ops/secrets-inventory.yaml`, `proxypay_api_key` |
| O facilitador tem *rate limit* (429); o valor | **NÃO VERIFICADO** | doc 09 §11 |
| A OPG do *express* expira a 30 min e o cliente tem 90 s | doc 09 §11, herdado | `E2` |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): quatro ramos, quatro consultas à base verificadas, o N4 sem confirmação por imagem, o reconhecimento manual pelo único caminho auditado, e o texto à PME por aprovar. O §0 regista o que não existe (adaptador, reconciliador, rota) e que o catálogo aponta para este runbook uma métrica do Chatwoot | KAM-083 |
