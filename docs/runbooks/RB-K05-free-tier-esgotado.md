# Runbook RB-K05 — *Free tier* de *service messages* esgotado

| Campo | Valor |
|---|---|
| ID | **RB-K05** |
| Versão | 1.0 |
| Cenário | Um número aproxima-se das 1.000 *service messages* gratuitas do mês, ou esgota-as |
| Severidade | **P3** (80% — 800), **P2** (100% — 1.000) |
| Alertas que o activam | **Nenhum, hoje.** A regra do §9.2 está por escrever: `meta_free_tier_used_ratio` existe (`packages/core-ts/src/metering/metricas.ts`) e nenhum serviço importa o módulo `metering`. Credor: **KAM-023** (`ops/metricas/catalogo.yaml`, `regras_por_escrever`) |
| Gatilho manual | Revisão semanal da consulta do §2 (proposta: às segundas-feiras, e diária a partir do dia 15); aviso da Meta no Billing Hub; uma PME diz que as respostas deixaram de chegar ao fim do mês |
| Nível de degradação | — (acima das 1.000, sem método de pagamento, a Meta deixa de entregar) |
| Dono | Ops/Trust & Safety |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Mesa-redonda, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3. Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K05; §11 (*service messages*) |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

- **O contador não conta nada em produção.** O `free_tier_used` de
  `platform.tenant_channels` é incrementado pelo módulo `metering`, que nenhum serviço
  importa — e nada envia para a Meta (RB-K01 §0). A consulta do §2 está certa e devolve
  zeros. Até o KAM-023 ligar o módulo, **a fonte é o Billing Hub da Meta**, e não a nossa
  base.
- **O «modo conciso» do §13 não existe no código** (procurado: nenhuma ocorrência fora
  dos documentos). O passo correspondente do §3 é por isso uma decisão de *prompt* e de
  produto, não um interruptor.
- A suspeita de falta de método de pagamento existe no módulo — 4 falhas em 20 envios
  levam o canal a `restrito` com `motivo_restricao = 'payment_method'` — e também não
  corre (§0, ponto 1).

## 1. Cenário e gatilho

| Limiar | Severidade | Porque |
|---|---|---|
| **800** entregues no mês (80%) | P3 | Existe para haver tempo de agir antes do de 100% |
| **1.000** (100%) | **P2** | Sem método de pagamento no Billing Hub, a Meta **deixa de entregar** *service messages* — não é um aviso de custo, é uma paragem de entrega anunciada |

São dois limiares na mesma série, e não dois alertas. O mês é o período de
`platform.ten_periodo(now())` (o primeiro dia do mês); a Meta reinicia à 00:00 no fuso
da conta (§7).

## 2. Diagnóstico

```bash
# Os canais acima dos 80% este mês
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT tenant_id, phone_number_id, free_tier_used, estado, motivo_restricao
      FROM platform.tenant_channels
     WHERE free_tier_month = platform.ten_periodo(now()) AND free_tier_used >= 800
     ORDER BY free_tier_used DESC"'
```
`verificado` contra uma base com as migrações até à 0039, a 2026-11-09
([`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2); `não verificado` contra
produção. O utilizador do contentor atravessa a RLS: só leitura.

**Depois, com a PME, no Business Manager / Billing Hub:**

- há **método de pagamento** na conta de mensagens? É a pergunta que decide a
  severidade;
- quantas mensagens por turno o bot está a mandar? Conversas longas, com várias
  mensagens por resposta, multiplicam o consumo (`E1`, recomendação 3).

## 3. Mitigação

1. **80% (P3):** avisar a PME (§6, texto A) e confirmar o método de pagamento.
2. **Reduzir mensagens por turno** para esse *tenant*: uma resposta, uma mensagem;
   evitar *templates* que a janela de atendimento já dispensa. Sem modo conciso no código
   (§0), é ajuste de *prompt* — decisão de Engenharia de agentes, registada.
3. **100% sem método de pagamento (P2):** avisar a PME de que as respostas vão deixar de
   chegar (§6, texto B) e pedir o método de pagamento no Billing Hub. **Não há nada do
   nosso lado que faça a Meta entregar** acima do *free tier* sem ele.
4. **100% com método de pagamento:** as mensagens continuam a ser entregues e passam a
   custar 0,004 USD cada (§7). Avisar a PME do custo (texto A) e seguir o custo por
   *tenant* (KAM-081).

## 4. Critério de recuperação

- a PME tem método de pagamento confirmado no Billing Hub, **ou**
- o mês virou (`free_tier_month` passa a `platform.ten_periodo(now())` e o contador
  recomeça na primeira entrega);
- e as respostas voltaram a ser entregues (confirmado com a PME ou pelos estados das
  mensagens, quando o módulo de saída estiver ligado).

## 5. Escalamento

Ops/T&S → Responsável de Produto (custo e plano da PME). De fora: suporte de faturação
da Meta, pelo Business Manager.

## 6. Comunicação

**À PME — propostas, por aprovar pelo Responsável de Produto.** Por e-mail (canal
alternativo; envio manual até o fornecedor de e-mail estar aprovado — ver RB-K01 §6).

**Texto A — aproximação ao limite (80%) ou custo depois dele:**

> **Assunto:** KAMBÁ — mensagens gratuitas do WhatsApp deste mês quase esgotadas
>
> Caro parceiro,
>
> Este mês o seu número já enviou {n} das 1.000 respostas gratuitas que a Meta
> oferece por mês. A partir da 1.001.ª, cada resposta custa 0,004 USD, cobrados pela
> Meta ao método de pagamento da sua conta.
>
> Para continuar a responder aos seus clientes sem interrupção, confirme que tem um
> método de pagamento activo na sua conta de WhatsApp Business. Se precisar de ajuda,
> fale connosco.
>
> Equipa KAMBÁ

**Texto B — limite atingido sem método de pagamento:**

> **Assunto:** KAMBÁ — URGENTE: as respostas aos seus clientes vão parar
>
> Caro parceiro,
>
> O seu número usou as 1.000 respostas gratuitas deste mês e a sua conta de WhatsApp
> Business não tem método de pagamento. A partir de agora a Meta **deixa de entregar**
> as respostas aos seus clientes até {fim do mês | adicionar um método de pagamento}.
>
> Para resolver, adicione um método de pagamento na sua conta (podemos ajudar). Enquanto
> isso, atenda os clientes urgentes directamente pelo seu telefone.
>
> Equipa KAMBÁ

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| As primeiras 1.000 *service messages* por número e por mês são grátis, desde 1 Out 2026; não acumulam; reiniciam à 00:00 no fuso da conta | **CONFIRMADO** | `E1`, linha da mudança de 1 Out 2026 |
| Sem método de pagamento, a Meta deixa de entregar *service messages* depois do *free tier* | **CONFIRMADO** | `E1`, linha seguinte |
| *Service* custa 0,004 USD por mensagem entregue em «Rest of Africa» | **CONFIRMADO** | `E1`, tarifas |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): a consulta à base verificada, o Billing Hub como fonte até o `metering` estar ligado, a mitigação por limiar e os dois textos à PME por aprovar | KAM-083 |
