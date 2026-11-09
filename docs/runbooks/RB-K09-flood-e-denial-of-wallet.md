# Runbook RB-K09 — *Flood* e *denial of wallet*

| Campo | Valor |
|---|---|
| ID | **RB-K09** |
| Versão | 1.0 |
| Cenário | Um contacto ou um IP inunda o sistema de mensagens, ou o custo de LLM de um *tenant* sobe sem que o volume de conversas o explique |
| Severidade | **P3** à entrada; **P1** se o custo ameaçar o orçamento da plataforma ou se for ataque dirigido |
| Alertas que o activam | **Nenhuma regra aponta para aqui.** O `llm_sem_budget` (P3) aponta para o [RB-K03](RB-K03-llm-em-baixo-ou-sem-budget.md), e o **comentário** da regra (não a anotação) nomeia este runbook: o sinal é o mesmo e quem atende decide qual é |
| Gatilho manual | O RB-K03 §3.3 encaminha para aqui; a consulta de custo do §2 (proposta: diária); uma PME diz que um contacto está a enviar centenas de mensagens |
| Nível de degradação | **N2** para o *tenant* afectado, se o orçamento esgotar |
| Dono | Ops/Trust & Safety, com Plataforma/SRE |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Mesa-redonda, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3. Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K09 |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

O §13 pede quatro mitigações — bloqueio e *handoff*, *budget* por contacto, limite na
CDN, aviso a T&S. **Três das quatro não têm mecanismo hoje**, e o operador tem de o saber
antes de procurar o botão:

| Mitigação do §13 | Existe? |
|---|---|
| **Limite por contacto** | **Parcial.** Só no AGR: `AGR_RITMO_POR_CONTACTO` (20 turnos por 60 s por omissão), chaveado pelo `thread_id` e não pelo `contact_hmac`; o excedente é descartado em silêncio e contado em `agr_admitted_rejected_total{motivo="ritmo"}` (métrica fora do catálogo de observabilidade) |
| **Bloqueio de contacto** | **Não.** `platform.contacts` não tem estado de bloqueio; o `bloquear_contacto` de `fraud_signals.accao` só retém confirmações manuais de pagamento |
| ***Budget* por contacto** | **Não.** Só por *tenant* — e nem esse, no compose actual: o LiteLLM não tem base de dados (RB-K03 §0, ponto 3) |
| **Limite na CDN / por IP** | **Não.** O GWY não limita por IP nem por contacto (só corpo > 1 MiB e descarte de estados sem preço com a fila acima de 10 000); a borda (`proxy-tls`) não tem WAF nem *rate limit*; CDN é o **KAM-077** |
| ***Handoff* forçado por operador** | **Não** há rota nem comando |

E o `contact_hmac` é identificador de diagnóstico e **não** entra em etiqueta de métrica —
é pseudonimização, não anonimização (`docs/tecnica/08` §7.2), e o espaço de números
móveis angolanos é pequeno o bastante para ser enumerável.

## 1. Cenário e gatilho

| Ramo | Sinal | Vai para |
|---|---|---|
| **A — um contacto inunda** | `agr_admitted_rejected_total{motivo="ritmo"}` a subir; uma PME relata | §3.1 |
| **B — muitos contactos, um IP ou uma origem** | pico de *webhooks* sem aumento de conversas reais | §3.2 |
| **C — custo anómalo** | o custo de LLM do *tenant* sobe e as conversas activas não | §3.3 |

## 2. Diagnóstico

```bash
# 1. Turnos recusados por ritmo (por contacto) na última hora
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'increase(agr_admitted_rejected_total{motivo="ritmo"}[1h])'
docker compose -f infra/compose/docker-compose.prod.yml logs --since 1h agr | grep ritmo_excedido
```
A consulta: `verificado` o comando e a sintaxe contra o Prometheus v3.7.3 do compose,
isolado, a 2026-11-09. O `grep`: `não verificado` contra produção; `ritmo_excedido` é o
aviso que o AGR emite (`services/agr/src/kamba_agr/api_interna.py`).

```bash
# 2. Custo de LLM nas últimas 24 h, por tenant
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT tenant_id, count(*) AS chamadas, sum(custo_usd) AS custo_usd
      FROM dat.llm_call_log
     WHERE ts > now() - interval '\''24 hours'\''
     GROUP BY 1 ORDER BY custo_usd DESC NULLS LAST LIMIT 10"'
```

```bash
# 3. Conversas com mensagem na última hora, por tenant — o volume que devia explicar o custo
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT tenant_id, count(*) AS conversas_activas_1h
      FROM platform.conversations
     WHERE last_inbound_at > now() - interval '\''1 hour'\''
     GROUP BY 1 ORDER BY 2 DESC LIMIT 10"'
```
As duas: `verificado` contra uma base com as migrações até à 0039, a 2026-11-09
([`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2); `não verificado` contra
produção.

```bash
# 4. Pico de webhooks no GWY (ramo B)
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'increase(gwy_requests_total[10m])'
```
`verificado` como no RB-K01 §2. Não há etiqueta de origem: o IP lê-se nos logs do
`proxy-tls` (`docker compose … logs --since 1h proxy-tls`, `não verificado`).

**A leitura que decide:** custo a subir **com** conversas a subir é procura — RB-K03.
Custo a subir **sem** conversas, ou concentrado em poucas conversas, é este runbook.

## 3. Mitigação

### 3.1 Ramo A — um contacto

1. O limite do AGR já está a descartar o excedente (§0). Confirmar que as recusas sobem
   e o custo não.
2. Se o contacto continua a gerar custo: pôr **essa conversa** fora do bot, em `humano`
   ou `pausada`, é o único travão por contacto que existe — e **não há comando**; é acção
   no painel de atendimento (Chatwoot) por quem gere a PME. Proposta de engenharia, não
   ensaiada.
3. Avisar Ops/T&S, que decide com a PME.

### 3.2 Ramo B — muitos contactos ou um IP

1. Sem *rate limit* por IP na borda (§0), a única contenção é **cortar o caminho** — regra
   no fornecedor de borda, que não existe antes do KAM-077. Até lá: registar, medir, e
   escalar ao Arquitecto.
2. Se parecer ataque dirigido: **[RB-K10](RB-K10-incidente-de-seguranca.md)**.

### 3.3 Ramo C — custo anómalo

1. Comparar as consultas 2 e 3 do §2. Identificar o *tenant*.
2. Cortar o orçamento do *tenant* (`max_budget: 0` na chave virtual) é a contenção
   desenhada — e **não está disponível** no compose actual (RB-K03 §0, ponto 3). A
   alternativa que existe é parar o bot desse *tenant* por decisão do Responsável de
   Produto: *tenant* → `suspenso`, pelo comando do [RB-K04](RB-K04-quality-rating-vermelho.md)
   §3, passo 5.
3. Avisar T&S e a PME.

## 4. Critério de recuperação

- `increase(agr_admitted_rejected_total{motivo="ritmo"}[1h])` de volta ao nível habitual;
- o custo por *tenant* (§2, consulta 2) volta a acompanhar as conversas activas
  (consulta 3);
- se houve suspensão, o *tenant* volta a `ativo` por decisão registada.

## 5. Escalamento

Ops/T&S → Plataforma/SRE → Arquitecto. Ataque dirigido → **RB-K10**. Fornecedor de borda
(por decidir, KAM-077).

## 6. Comunicação

Interna, e a PME afectada por Ops/T&S, caso a caso. Sem texto-modelo: o critério 4 do
bloco não o pede para o K09, e cada caso depende de quem está do outro lado.

## 7. Factos de terceiros

Nenhum: este runbook não assenta em factos de terceiros.

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): o inventário do que existe e não existe para as quatro mitigações do §13, três ramos, as consultas de custo e de volume verificadas, e a leitura que separa procura de abuso | KAM-083 |
