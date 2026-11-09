# Runbook RB-K03 — LLM em baixo, lento, ou sem *budget*; filas a crescer

| Campo | Valor |
|---|---|
| ID | **RB-K03** |
| Versão | 1.0 |
| Cenário | Os turnos do agente ficam lentos ou param, a fila de entrada ou a do agente cresce, ou o orçamento de LLM de um *tenant* esgota |
| Severidade | **P2** (filas e latência), **P3** (orçamento) |
| Alertas que o activam | `fila_de_entrada_a_crescer` (P2), `fila_do_agente_a_crescer` (P2), `latencia_de_resposta_alta` (P2) e `llm_sem_budget` (P3), em [`../../infra/compose/prometheus/regras/kamba.yml`](../../infra/compose/prometheus/regras/kamba.yml). A `degradacao_acima_do_limiar` e o `disjuntor_do_llm_aberto` vão para [`degradacao-do-agr.md`](degradacao-do-agr.md) |
| Gatilho manual | `alvo_em_baixo` com `job="agr"` (o RB-K01 encaminha para aqui); uma PME diz que o bot demora ou responde só com menus |
| Nível de degradação | **N1** (LLM lento: *fallback*) ou **N2** (LLM indisponível: fluxo determinístico) — doc 09 §12 |
| Dono | Engenharia de agentes, com Plataforma/SRE |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Injecção em *staging*, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.2; precisa de *staging* com *host* (KAM-077). Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K03; §12, N1 e N2 |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

Quatro factos medidos que, hoje, explicam estes alertas antes de o LLM os explicar:

1. **O AGR responde 503 a todos os turnos do Vendedor** — a porta `grafos` não está
   ligada (`GrafoNaoRegistadoError`, KAM-186). O turno não chega ao LLM, repete pela
   escada de tentativas e acaba em `failed`. Uma latência ou uma fila do agente alta é
   isto antes de ser o fornecedor.
2. **Nenhum consumidor lê a `wa-inbound`** (KAM-187). O `fila_de_entrada_a_crescer`
   dispara com **qualquer** tráfego, e a causa não é o LLM.
3. **O LiteLLM do compose não tem base de dados, e por isso não tem chaves virtuais nem
   orçamentos por *tenant*.** Medido contra a imagem fixada (`v1.104.2`, por *digest*) com
   a configuração do repositório, a 2026-11-09: `/key/generate`, `/key/list` e
   `/key/update` respondem **500 «DB not connected»**, e `/health/readiness` diz
   `"db": "Not connected"`. Logo o `python infra/llm/chaves.py provisionar|orcamentos` não
   funciona contra este compose, o «subir o limite do *tenant*» e o «`max_budget: 0`» não
   têm onde se aplicar, e o `llm_sem_budget` não tem orçamento que esgotar. Achado
   registado em [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §5.
4. **O Prometheus não raspa o LiteLLM**; erros por fornecedor leem-se nos logs dele e em
   `dat.llm_call_log` (hoje vazia, pelo ponto 1). **Não há modo degradado forçado à mão**
   nem mecanismo de «congelar *prompts*» (procurados; o mais próximo é o
   `ci/llm-aliases.lock`, que fixa os aliases no CI).

## 1. Cenário e gatilho

| Alerta | Condição | O mais provável hoje | Ramo |
|---|---|---|---|
| `fila_de_entrada_a_crescer` | `inbound_queue_depth > 0` durante 2 min | **falta de consumidor** (KAM-187), não o LLM | §3.1 |
| `fila_do_agente_a_crescer` | `agr_queue_depth > 0` durante 2 min | turnos à espera de vaga na admissão do AGR | §3.2 |
| `latencia_de_resposta_alta` | `agr_turn_latency_ms > 8000` durante 10 min, com turnos a acontecer | LLM lento (N1) ou o AGR saturado | §3.2 |
| `llm_sem_budget` | apareceu um `agr_llm_erros_total{resultado="budget_exhausted"}` | orçamento esgotado — **ou** consumo anómalo, que é o [RB-K09](RB-K09-flood-e-denial-of-wallet.md) | §3.3 |
| `alvo_em_baixo{job="agr"}` | o AGR não responde ao `/metrics` | processo em baixo | §3.4 |

Os dois limites que as regras confessam: as filas medem **profundidade** e não a idade
do mais antigo que o §9.2 pede; a latência é o **último valor** e não um p95 (o AGR não
tem histogramas, ADR-018).

## 2. Diagnóstico

Todas as consultas ao Prometheus: `verificado` o comando e a sintaxe de cada expressão
contra o Prometheus v3.7.3 do compose com as regras do repositório, num contentor
isolado, a 2026-11-09; os nomes e as etiquetas são os do `ops/metricas/catalogo.yaml`.

```bash
# 1. As filas e a latência
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'inbound_queue_depth'
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'agr_queue_depth'
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'agr_turn_latency_ms'
```

```bash
# 2. Como acabam os turnos, e como acabam as chamadas ao LLM
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'sum by (outcome) (increase(agr_turns_total[10m]))'
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'sum by (resultado) (increase(agr_llm_erros_total[15m]))'
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'sum by (motivo) (increase(agr_degraded_turns_total[15m]))'
```
**Separar «indisponível» de «sem *budget*»**, que é o que o §13 manda antes de agir:
`resultado` em `timeout` ou `erro_fornecedor` é o fornecedor; `budget_exhausted` é o
orçamento; `destino_negado` é o *gate* de transferência (ADR-008), que em produção nega
**todos** os destinos enquanto nenhum tiver `apd_ref` — e não é avaria.

```bash
# 3. O LiteLLM está vivo e pronto? (o mesmo teste do healthcheck do compose)
docker exec kamba-prod-litellm-1 python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4000/health/readiness', timeout=5).read().decode())"
docker logs --since 30m kamba-prod-litellm-1
```
`verificado` o `/health/readiness` contra a imagem `litellm:v1.104.2` do compose, com a
configuração do repositório, a 2026-11-09 (devolve `{"status":"healthy","db":"Not connected"}`).
Nos logs, procurar 429 e 5xx por fornecedor.

```bash
# 4. Chamadas ao LLM na última hora, por fornecedor e desfecho
docker exec kamba-prod-postgres-1 \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT fornecedor, resultado, count(*) AS n,
           round(avg(latencia_ms)) AS latencia_media_ms, sum(custo_usd) AS custo_usd
      FROM dat.llm_call_log
     WHERE ts > now() - interval '\''1 hour'\''
     GROUP BY 1, 2 ORDER BY n DESC"'
```
`verificado` contra uma base com as migrações até à 0039, a 2026-11-09
([`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2).

```bash
# 5. O AGR está vivo, e o que diz?
docker ps -a --filter label=com.docker.compose.project=kamba-prod --filter label=com.docker.compose.service=agr
docker logs --since 30m kamba-prod-agr-1
```
`não verificado` contra produção. **O `grafo_nao_registado` do §0, ponto 1, não aparece aqui:** é só o corpo JSON da resposta 503 (`api_interna.py`), e o servidor corre sem registo de acessos — nenhum log nem métrica do AGR o distingue. O que o mostra é o *job* a acabar em `failed` na `agr-inbound` depois das tentativas: `docker exec kamba-prod-queue-1 valkey-cli ZCARD bull:agr-inbound:failed` a subir (`verificado` o comando na imagem do Valkey; a fila é a `FILA_AGR` de `packages/core-ts/src/chr/contrato.ts`). Até ao KAM-186, a resposta certa a «é o grafo?» é **sim**.

## 3. Mitigação

### 3.1 Fila de entrada a crescer

1. Há consumidor da `wa-inbound`? Hoje **não** (KAM-187): o alerta é verdadeiro e não
   tem mitigação neste runbook. Registar e silenciar com prazo, dizendo porquê:
   ```bash
   docker exec kamba-prod-alertmanager-1 \
     amtool --alertmanager.url=http://127.0.0.1:9093 silence add alertname=fila_de_entrada_a_crescer \
     --duration=24h --author="<papel>" --comment="RB-K03: sem consumidor da wa-inbound (KAM-187)"
   ```
   `verificado` a forma contra o Alertmanager v0.28.1 do compose, isolado.
2. Quando houver consumidor: ver se ele está vivo e se a fila do agente (§3.2) é o
   gargalo a jusante.

### 3.2 Fila do agente ou latência alta

1. Se os *jobs* da `agr-inbound` acabam em `failed` (§2, ponto 5) e o `agr_llm_erros_total` não sobe, é o §0, ponto 1 — não é LLM.
2. Se o `resultado` dominante é `timeout` ou `erro_fornecedor`: o sistema já está em
   **N1** — o LiteLLM troca `kamba-chat` por `kamba-chat-fallback2` (`llm/litellm.config.yaml`,
   `allowed_fails: 3`, `cooldown_time: 30`), **só dentro dos destinos autorizados**. Se
   o *fallback* também falha, o AGR passa a **N2** sozinho (motivos `timeout`,
   `http_429`, `breaker`; ver `degradacao-do-agr.md`). Nada a forçar à mão (§0, ponto 4).
3. Se é saturação (fila funda com o LLM a responder): a admissão tem tecto por *tenant*
   (`AGR_TECTO_POR_TENANT`, 3) e limiar de contrapressão (`AGR_LIMIAR_DE_CONTRAPRESSAO`,
   100). Mudá-los é configuração do serviço e decisão de Engenharia de agentes,
   registada — não um passo de incidente.
4. Abrir caso com o fornecedor pelo canal da lista de contactos se a página de estado
   dele não reconhecer a falha.

### 3.3 Sem *budget*

1. Separar do **RB-K09**: o consumo subiu com o volume de conversas do *tenant*? Se não,
   é *denial of wallet* — vai para lá.
2. Subir o limite de um *tenant* é **decisão humana**, registada (doc 09 §13). O
   mecanismo desenhado é `python infra/llm/chaves.py provisionar "<tenant_id>" "<plano>"`
   com a mensalidade do plano nova — e **não funciona contra este compose** (§0, ponto 3).
   Credor: quem der base de dados ao LiteLLM (KAM-030/fundador).
3. Enquanto não houver orçamento por *tenant*, o turno sem orçamento degrada para **N2**
   (motivo `budget`) e o cliente recebe o menu determinístico e o caminho para humano.

### 3.4 O AGR não responde

1. `docker restart kamba-prod-agr-1`, **uma** vez
   (`não verificado` contra produção).
2. Se o Postgres ou o *checkpointer* estão em baixo, o AGR **não degrada**: responde 503
   com `Retry-After` e a mensagem fica na fila — é o [RB-K08](RB-K08-base-de-dados-e-restauro.md).

## 4. Critério de recuperação

- `agr_queue_depth` e `inbound_queue_depth` a 0, ou a descer, sem o alerta (§2, ponto 1);
- `agr_turn_latency_ms` abaixo de 8000 com turnos a acontecer;
- `sum by (resultado) (increase(agr_llm_erros_total[15m]))` sem resultado — o contador só conta **falhas** (`llm/cliente.py`), e o AGR não emite séries a zero, pelo que «sem resultado» é «nenhuma falha em 15 min»; e, na consulta do §2, ponto 4, o `resultado` dominado por `ok`;
- `amtool --alertmanager.url=http://127.0.0.1:9093 alert query` sem os quatro alertas
  deste runbook, e os silêncios expirados.

## 5. Escalamento

Engenharia de agentes → Plataforma/SRE → Arquitecto. De fora: o fornecedor de LLM pelo
canal da lista de contactos. Consumo anómalo → **RB-K09**; chave de fornecedor suspeita
→ **RB-K07** e **RB-K10**.

## 6. Comunicação

**Interna:** linha temporal. **PMEs:** só se o N2 durar mais de 1 h em horário
comercial — o texto do RB-K01 §6 com «o assistente está a responder em modo simplificado
(menus) e a passar a conversa a si quando não sabe responder». Proposta, por aprovar.

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| O orçamento esgotado chega do LiteLLM como HTTP 422 `budget_exceeded` | **CONFIRMADO** no ensaio do KAM-030 | `docs/evidencia/KAM-030-litellm.md` §4 |
| As chaves virtuais do LiteLLM exigem base de dados | **CONFIRMADO** contra a imagem fixada, a 2026-11-09 | §0, ponto 3 |
| Limites de TPM/RPM dos fornecedores | **NÃO VERIFICADO** | doc 09 §11 |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): um ramo por alerta, as consultas ao Prometheus e à base verificadas, a separação «indisponível» contra «sem *budget*», e o N1/N2 como o que já acontece sozinho. O §0 regista que o LiteLLM do compose não tem chaves virtuais nem orçamentos (medido) | KAM-083 |
