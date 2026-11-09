# Runbook RB-K04 — *Quality rating* amarelo ou vermelho

| Campo | Valor |
|---|---|
| ID | **RB-K04** |
| Versão | 1.0 |
| Cenário | A Meta baixou a classificação de qualidade de um número ou de um *template* |
| Severidade | **P1** (vermelho), **P3** (amarelo) |
| Alertas que o activam | **Nenhum, hoje.** A regra do §9.2 está por escrever: `channel_quality{rating}` existe (`packages/core-ts/src/qualidade/metricas.ts`) e nenhum serviço importa o módulo `qualidade`. Credor: o ticket que ligar o módulo (`ops/metricas/catalogo.yaml`, `regras_por_escrever`) |
| Gatilho manual | Aviso no Business Manager ou por e-mail da Meta; uma PME diz que os *templates* deixaram de sair; um `phone_number_quality_update` ou `message_template_quality_update` visto no registo de entrada |
| Nível de degradação | — (o envio de *templates* pausados falha; as respostas dentro da janela continuam) |
| Dono | Ops/Trust & Safety, com Plataforma/SRE |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Mesa-redonda, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3. Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K04 |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

- **Nada trata os eventos de qualidade em produção.** O módulo `qualidade`
  (`GestaoDeCanal`) existe e não está importado por nenhum serviço; o `account_update`
  e os eventos de qualidade ficam só registados em `platform.inbound_events`, e hoje
  **nem isso**, porque nenhum consumidor lê a `wa-inbound` (KAM-187). O que o módulo
  faria, quando ligado, está no §1 — e o operador faz à mão o que ele não faz.
- **Não há transição automática do *tenant* para `suspenso`.** O `kamba_app` não pode
  escrever `platform.tenants.estado` (revisão 0007); só o papel `kamba_batch`. A
  suspensão é um acto humano (§3, passo 5).
- **Não há «pausar marketing» a fazer:** o envio de marketing já é **recusado sempre**
  no Piloto (`MARKETING_NOT_ALLOWED`, `packages/core-ts/src/outbound/decisao.ts`). O
  passo do §13 «pausar marketing» aplica-se a difusões feitas **pela PME fora da
  KAMBÁ**, no mesmo número.

## 1. Cenário e gatilho

| Evento da Meta | Qualidade | Severidade | O que o módulo `qualidade` faria (quando ligado) |
|---|---|---|---|
| `phone_number_quality_update` | **RED** | **P1** | canal → `restrito`, `motivo_restricao = 'quality'`; conta `channel_restricted_total` |
| `phone_number_quality_update` | YELLOW | P3 | marca a qualidade dos *templates* aprovados; **não** pausa |
| `phone_number_quality_update` | GREEN ou YELLOW depois de RED | — | repõe `ativo`, **só** se o motivo da restrição era `quality` |
| `message_template_quality_update` | qualquer | P3 (P1 se o *template* é o de pagamento ou de recibo) | *template* → `status = 'paused'` — **com qualquer valor recebido**, não só RED (ver §7) |

A assimetria de severidade é deliberada: amarelo é uma tendência a corrigir com calma;
vermelho é o estado em que a Meta pode pausar *templates*.

## 2. Diagnóstico

As consultas leem a base com o utilizador do contentor (`$POSTGRES_USER`), que
**atravessa a RLS**: só leitura, e com o `tenant_id` sabido.

```bash
# Estado e qualidade do canal do tenant
docker exec kamba-prod-postgres-1 \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT phone_number_id, estado, quality_rating, motivo_restricao, messaging_limit
      FROM platform.tenant_channels WHERE tenant_id = '\''<tenant_id>'\''"'
```

```bash
# Que templates estão pausados ou com nota, e a história de qualidade do canal
docker exec kamba-prod-postgres-1 \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT name, lang, category, status, quality
      FROM platform.message_templates
     WHERE tenant_id = '\''<tenant_id>'\'' AND (status = '\''paused'\'' OR quality IS NOT NULL);
    SELECT evento, valor_anterior, valor_novo, ocorrido_em
      FROM platform.channel_quality_log
     WHERE tenant_id = '\''<tenant_id>'\'' ORDER BY ocorrido_em DESC LIMIT 20"'
```

`verificado` contra uma base com as migrações do repositório aplicadas (ver
[`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2); `não verificado` contra
produção. Hoje as tabelas ficam por preencher, pela razão do §0.

**Depois, a causa** — no Business Manager da PME, com ela:

- a taxa de bloqueios e de denúncias nos últimos 7 dias;
- que *templates* foram enviados, a quem e com que frequência;
- se houve difusão de marketing no número **fora** da KAMBÁ (coexistência: a PME usa
  a aplicação no mesmo número).

## 3. Mitigação

1. **Amarelo (P3):** rever com a PME o texto e a frequência dos *templates*; garantir
   que cada um tem saída clara (*opt-out*). Sem pressa; registar e acompanhar 7 dias.
2. **Vermelho (P1):** pedir à PME que **suspenda as difusões de marketing** que faz no
   mesmo número, fora da KAMBÁ. Dentro da KAMBÁ, o marketing já está recusado (§0).
3. Rever e reescrever os *templates* pausados; submeter de novo **só** depois de
   corrigida a causa.
4. Se a qualidade não melhora em 48 h, ou a Meta pausa *templates* de pagamento:
   abrir caso no *Direct Support* da Meta (canal na lista de contactos). O *Tech
   Provider*, que é o tipo de parceiro do ADR-001, tem *Direct Support* (CONFIRMADO,
   `E1`).
5. **Se persistir** (proposta: vermelho mais de 7 dias, ou reincidência no mês):
   *tenant* → `suspenso`. É **decisão do Responsável de Produto**, registada, e
   executa-se com o papel `kamba_batch` — não há ferramenta (§0):
   ```bash
   docker exec kamba-prod-postgres-1 \
     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "
       BEGIN; SET ROLE kamba_batch;
       UPDATE platform.tenants SET estado = '\''suspenso'\''
        WHERE id = '\''<tenant_id>'\'' AND estado = '\''ativo'\'';
       COMMIT;"'
   ```
   `verificado` contra uma base com as migrações até à 0039 (com `ROLLBACK` no lugar do
   `COMMIT`; [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2): o papel
   `kamba_batch` tem o `UPDATE`. Confirmar que devolve `UPDATE 1`. Nenhum caminho de
   código faz esta transição, e por isso não há evento `tenant.*` emitido nem registo no
   `audit_log` — **regista-se na linha temporal**. Repor: o mesmo comando com
   `'ativo'` e `estado = 'suspenso'`.

## 4. Critério de recuperação

- `quality_rating` volta a `GREEN` ou `YELLOW` na consulta do §2 (o valor vem da Meta);
- canal em `ativo` e `motivo_restricao` vazio;
- os *templates* necessários com `status = 'approved'`;
- se houve suspensão, o *tenant* volta a `ativo` por decisão registada.

## 5. Escalamento

Ops/T&S → Plataforma/SRE → Responsável de Produto (suspensão). De fora: *Direct
Support* da Meta.

## 6. Comunicação

**À PME — proposta, por aprovar pelo Responsável de Produto.** Por e-mail (canal
alternativo; envio manual até o fornecedor de e-mail estar aprovado — ver RB-K01 §6).

> **Assunto:** KAMBÁ — a Meta baixou a qualidade do seu número de WhatsApp
>
> Caro parceiro,
>
> A Meta, que gere o WhatsApp, classificou a qualidade do seu número como
> {amarela | vermelha}. Isto acontece quando muitos clientes bloqueiam ou denunciam
> mensagens do número.
>
> {Vermelha: Enquanto a qualidade não melhorar, algumas mensagens automáticas
> (por exemplo, avisos de encomenda) podem ficar suspensas pela Meta.}
>
> Para recuperar, pedimos que:
> 1. suspenda por agora as mensagens promocionais que envia deste número;
> 2. envie mensagens só a clientes que falaram consigo recentemente;
> 3. fale connosco antes de enviar novas campanhas.
>
> Vamos acompanhar a situação consigo nos próximos dias.
>
> Equipa KAMBÁ

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| Qualidade baixa **já não reduz** o limite de mensagens (desde 7 Out 2025) | **CONFIRMADO** | `E1`, linha do estado «Flagged» |
| A Meta pode rever, pausar e rejeitar *templates* a qualquer momento | **CONFIRMADO** | `E1`, linha dos *templates* |
| O *Tech Provider* (o tipo de parceiro do ADR-001) tem *Direct Support* | **CONFIRMADO** | `E1`, linha dos três tipos de parceiro |
| O módulo pausa um *template* com **qualquer** `message_template_quality_update`, sem olhar ao valor | do código (`qualidade/qualidade.ts`) — achado, ver [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §5 | — |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): o que o módulo `qualidade` faria e o que fica à mão, consultas à base, mitigação por cor, suspensão como acto humano registado, e o texto à PME por aprovar | KAM-083 |
