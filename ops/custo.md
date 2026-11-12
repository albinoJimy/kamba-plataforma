# Custo por tenant, `h6-export` e reconciliação

| Campo | Valor |
|---|---|
| Ticket | KAM-081 |
| Âmbito | O custo por tenant e por conversa (LLM e Meta), a exportação da amostra da H6, a reconciliação contra as fontes e a leitura de unit economics |
| Fontes | [`../docs/tecnica/09_Topologia_Operacao_Escala.md`](../docs/tecnica/09_Topologia_Operacao_Escala.md) §14; [`../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`](../docs/tecnica/evidencia/E1_Meta_WhatsApp.md) §1; [`../docs/tecnica/evidencia/E4_Stack_Licencas.md`](../docs/tecnica/evidencia/E4_Stack_Licencas.md) §3; ADR-005, ADR-018 |
| Estado | **O instrumento existe; nada foi medido em operação.** Não há tráfego, *staging* nem Grafana a correr |
| Alimenta | KAM-109 (a decisão da H6: custo ≤ 15% da mensalidade) |
| Não cobre | A decisão da H6 (KAM-109), o custo de STT (KAM-036), quem paga a Meta (D9), a fonte de dados do Grafana e o acesso por VPN (deploy, KAM-080) |

---

## 1. O que existe

| Peça | Onde | O que faz |
|---|---|---|
| Vista | `platform.v_tenant_cost_daily`, SQL em [`../db/custo.py`](../db/custo.py) | Custo por tenant, dia (fuso do tenant) e rubrica: `llm` e `meta_<categoria>`, em USD e em cêntimos de Kz, com o câmbio ao lado. `SELECT` só do `kamba_batch` |
| Comando | [`../db/h6_export.py`](../db/h6_export.py) (`h6-export`) | `exportar`, `reconciliar` e `economia` |
| Painéis | [`paineis/custo-por-tenant.json`](paineis/custo-por-tenant.json), [`paineis/unit-economics.json`](paineis/unit-economics.json) | Custo diário por rubrica, por tenant, *free tier* por número, LLM do dia; custo por PME, margem, equilíbrio e estimado contra medido |

**Sem STT em parte nenhuma.** Não há registo de chamadas de transcrição: o
`papel` da `dat.llm_call_log` é lista fechada — os quatro da `0023` e o
`screening` da `0047` —, e o STT entra com o KAM-036. A vista não tem a rubrica, o `h6-export` escreve `null`, e os painéis
dizem-no. Escrever zero era afirmar que a voz não custou nada.

**Sem pessoas em parte nenhuma.** A vista não tem `contact_id`, conversa,
telefone, `wamid` nem texto; o `h6-export` troca o contacto por um ordinal **na
base**; e o `db/tests/test_custo.py` recusa um `rawSql` de painel que nomeie um
identificador ou que escreva uma relação qualificada fora da vista, da
`tenant_channels` e da `tenants` — em maiúsculas ou minúsculas, depois de um
`FROM`, de um `JOIN` ou de uma vírgula. **É um ensaio sobre o texto, e tem o
limite disso:** a defesa que não depende do texto é a fonte do Grafana ler com
um papel que só tenha `SELECT` na vista, que é do deploy.

## 2. `h6-export`: a amostra de conversas

```bash
python db/h6_export.py exportar --n 500 --mensalidade-kz 30000 --saida h6.json
python db/h6_export.py exportar --modo choque     # câmbio a 1.232
```

Corre como `kamba_batch` (as variáveis do `db/ligacao.py`), sob o *job*
`ops_h6_export`. Sai JSON com:

* **as últimas N conversas** (omissão 500), cada uma com o tenant, o dia de
  início e de fim, o número de mensagens e o custo LLM, STT e Meta;
* **os percentis p50, p90 e p99** do custo total por conversa, por posição mais
  próxima (um valor que existe na amostra, sem interpolar);
* **o rácio custo/mensalidade por tenant e mês**, em Kz ao câmbio pedido. O
  custo é o **do mês inteiro**, lido da vista, e não a soma da amostra (que
  dependia do N e do corte); o mês corrente sai com `mes_completo: false`;
* **`llm_nao_atribuido`**: o LLM dos dias em que o tenant não enviou mensagem
  nenhuma, por tenant. Não tem a quem ser rateado, e sem esta linha perdia-se;
* **`excluidas`**: as conversas que ficaram de fora por ainda estarem abertas
  (a última mensagem tem menos de 24 h) ou por poderem ter começado antes da
  janela (a primeira está nas primeiras 24 h dela). A amostra só leva
  conversas inteiras.

Três limites, que a própria saída escreve no campo `metodo`:

1. **Conversa** é «mensagens do mesmo contacto sem pausa maior do que 24 h»,
   **medida nas mensagens de saída**. As mensagens de texto da entrada não se
   guardam com contacto (`platform.inbound_events` não tem `tenant_id` nem
   `contact_id`; a mídia guarda-se, em `platform.media_assets`, e é só a mídia),
   pelo que uma conversa sem resposta do bot não aparece.
   **INDÍCIO**: o bot responde a cada turno.
2. **O LLM por conversa é rateado** pelas mensagens de saída do tenant nesse
   dia, e não medido: a `dat.llm_call_log` não tem chave para uma conversa — tem
   `trace_id`, que não é o `turn_id` nem o contacto (nota do custo na revisão
   `0024`). A soma do rateado dá o LLM dos dias **com** mensagens, tenant a
   tenant; o dos dias sem nenhuma vai para `llm_nao_atribuido`.
3. **A Meta é medida**: a tarifa da categoria que o `pricing` dos *statuses* diz,
   nas mensagens entregues e cobráveis.

## 3. Reconciliação do LLM com o LiteLLM

```bash
python db/h6_export.py reconciliar --litellm spend.json --desde 2026-11-01 --ate 2026-11-30
```

O `spend.json` é uma lista `[{"tenant_id": …, "spend_usd": …}]`. Tira-se do
*spend* por chave virtual do LiteLLM e traduz-se para o tenant pelo
`tenants.litellm_key_id`. **O caminho exacto da API de *spend* do LiteLLM é NÃO
VERIFICADO** nesta versão: o KAM-030 mediu o `/key/list` (gasto e tecto por
chave) e mais nada. O comando sai com **1** e lista os tenants cujo desvio passa
de **2%** (*proposta*, do critério 3) ou que só aparecem de um lado.

**Quando correr:** sete dias de tráfego sintético em *staging*, como o critério
3 pede, e depois uma vez por mês. Nada disto correu: não há *staging*.

## 4. Reconciliação da Meta

**Pela tarifa, por comando:**

```bash
python db/h6_export.py reconciliar-meta --mes 2026-11
```

Por número (o ordinal do canal dentro do tenant; o `channel_id` não sai da
base) e mês, compara o custo **medido** — as mensagens que o `pricing` diz
cobráveis, à tarifa da categoria — com o custo **pela tarifa** — a contagem das
entregues, com 1.000 *service* grátis e 0,004 USD depois. Desvio acima de **1%**
é achado, e o comando sai com 1. Uma categoria que não conhecemos é achado, e
não zero.

**Contra a factura, manual e mensal**, porque a factura é da PME:

1. No Billing Hub da conta da PME, tirar o total do mês por categoria e por
   número. **Para um Tech Provider, a visibilidade dessa factura é NÃO
   VERIFICADA** (`E1`): pode ser preciso pedi-la à PME.
2. Ler o mesmo mês na vista: `SELECT rubrica, sum(custo_usd) FROM
   platform.v_tenant_cost_daily WHERE tenant_id = … AND dia >= … GROUP BY
   rubrica`, com a leitura do `sem_preco` ao lado.
3. Divergência acima de **1%** numa categoria é um achado. As causas por ordem
   de probabilidade: tarifa velha em `config/meta_rates.yaml` (a revisão é
   trimestral e a cadência é *proposta*); mensagens entregues cujo *status* não
   chegou; categoria desconhecida (`meta_outra`).

A conta pela tarifa — 1.000 *service* grátis por número e por mês, 0,004 USD
depois — está em `meta_pela_tarifa()`, e o ensaio da PME típica do §14.3 dá os
7,52 USD de 1.880 mensagens.

## 5. Preços e câmbio: as tabelas e o estado de cada uma

| Tabela | Data | Estado | Onde |
|---|---|---|---|
| Tarifas da Meta | efectivas 2026-10-01 | CONFIRMADO (`E1` §1); cadência de revisão *proposta* | `config/meta_rates.yaml`, copiado no `CASE` da vista com ensaio de paridade |
| Preços de LLM | lidos em 2026-10-08 (`E4` §3) | por linha: Anthropic e OpenAI CONFIRMADO, Google INDÍCIO; o Gemini 3.8 Flash dobra a 2027-01-01 | `llm/precos.yaml`; o `custo_usd` calcula-se na chamada |
| Preços de STT | lidos em 2026-10-08 | gpt-4o-mini-transcribe CONFIRMADO; Groq INDÍCIO-forte | só no `docs/tecnica/09` §14.2: não há tabela, porque não há registo |
| Câmbio | 2026-09-30 | **INDÍCIO** (913); venda BNI 981 a 2026-10-08 CONFIRMADO | parâmetro `app.fx_aoa_per_usd` |

**Valores de mercado a reconferir antes de fixar tarifas.** O doc 09 §14.1 já o
diz para o LLM, e vale para todos.

## 6. Unit economics

```bash
python db/h6_export.py economia --mes 2026-11 --fixo-usd 600 --mensalidade-kz 45000 --meta-payer pme
```

O custo fixo é **parâmetro**: o §14.4 dá 470–730 USD por mês (infra +
ferramentas) como ESTIMATIVA, a substituir por cotações. O comando dá o custo
fixo e variável por PME, o custo para a KAMBÁ e o custo total para o cliente
(que inclui sempre a Meta), a margem por mensalidade, o ponto de equilíbrio e os
itens de revisão do doc 09 — uma rubrica com desvio acima de **30%** contra o
cenário pedido do §14.3 gera um item na saída. O painel mostra o mesmo, com o
custo para a KAMBÁ e o custo para o cliente nas **duas** leituras do
`meta_payer`, porque a D9 está por decidir, e abre no **mês anterior**: a
comparação com o §14.3 só diz alguma coisa sobre um mês inteiro.

**O custo total para o cliente é o que ele paga, e não o que custa servi-lo:** a
mensalidade e, quando é a PME quem paga a Meta, a Meta por cima. O LLM e o fixo
são da KAMBÁ. **É uma leitura** do «custo total para o cliente (inclui Meta)»
do critério 6, e escreve-se como tal.

**O que fica de fora:** a comparação com o §14.4 por estágio (o painel usa dele
só a omissão do custo fixo), e um item de revisão escrito num sítio que dure —
hoje é uma linha na saída do comando e uma coluna no painel.

## 7. O que fica com credor

| O quê | Credor |
|---|---|
| Custo de STT | KAM-036 |
| Custo LLM medido por conversa (e não rateado) | devolvido: as três saídas da nota do custo da `0024` |
| Fonte PostgreSQL do Grafana, papel de leitura próprio e VPN | deploy do KAM-080 (o Grafana está pendente pela licença) |
| Alertas de *free tier* a 80% e 100% | KAM-023 (`meta_free_tier_used_ratio` sem serviço que a sirva) |
| Alerta de orçamento LLM diário a 80% por tenant | KAM-030 (`infra/llm/chaves.py` tem o limiar; falta agendador e regra) |
| Reconciliação em *staging* com 7 dias de tráfego | quando houver *staging* (KAM-075) |
| A decisão da H6 | KAM-109 |

---

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Documento criado pelo **KAM-081**: a vista, o `h6-export`, os dois painéis, os procedimentos de reconciliação do LLM e da Meta, as tabelas de preços com data e estado, e o que fica com credor. | Equipa KAMBÁ |
