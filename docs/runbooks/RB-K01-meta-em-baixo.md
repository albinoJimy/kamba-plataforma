# Runbook RB-K01 — Meta em baixo, ou a ingestão parou

| Campo | Valor |
|---|---|
| ID | **RB-K01** |
| Versão | 1.0 |
| Cenário | A Cloud API da Meta não aceita envios, ou deixámos de receber *webhooks* |
| Severidade | **P1** |
| Alertas que o activam | `ingress_parado` (P1) e `alvo_em_baixo` (P1), em [`../../infra/compose/prometheus/regras/kamba.yml`](../../infra/compose/prometheus/regras/kamba.yml). **Por escrever:** a metade «sonda falha 2×» do §9.2, que exige a sonda externa (D1/KAM-105) |
| Gatilho manual | Uma PME diz que o bot não responde; erros de envio vistos nos logs; aviso da Meta |
| Nível de degradação | **N3** (envio falha) ou **N6** (ingress inoperante) — doc 09 §12 |
| Dono | Plataforma/SRE |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Injecção em *staging*, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.1; precisa de *staging* com *host* (KAM-077). Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K01; §12, N3 e N6 |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

Quatro factos medidos que mudam o que este runbook consegue fazer hoje:

1. **O GWY, tal como está escrito no compose, não arranca.** O
   `services/gwy/src/server.ts` exige `KAMBA_QUEUE_URL` e `KAMBA_AMBIENTE`
   (`exigir(...)`, linhas 75–76 e 99–107) e os segredos `meta_app_secret` e
   `meta_verify_token`; **nenhum** dos três compose define as duas variáveis, e o
   bloco `environment` do `gwy` de produção só tem `PORT`, o ambiente Node e o
   *proxy* de saída. Numa pilha levantada assim, o `ingress_parado` dispara e a
   causa é nossa. Está registado como achado fora de âmbito (ver
   [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §5).
2. **Nada envia para a Meta.** O cliente da Graph API (`ClienteDaGraph`,
   `packages/core-ts/src/outbound/`) existe e nenhum serviço o instancia; o
   `worker-canal` do compose só serve `/healthz` (KAM-187). O ramo «envio» deste
   runbook descreve o comportamento do módulo, não de um processo a correr.
3. **Não há métrica por código de erro da Meta** (`ops/metricas/catalogo.yaml`,
   série «erros 130429/131049», estado `inexistente`). A separação «Meta» contra
   «nós» faz-se pelos logs e pelo `up`, não por um gráfico.
4. **O Alertmanager não notifica ninguém** ([`README.md`](README.md) §6): o alerta
   vê-se se alguém for ver.

## 1. Cenário e gatilho

| Alerta | Condição exacta | O que quer dizer |
|---|---|---|
| `ingress_parado` | `increase(gwy_requests_total[10m]) == 0` **ou** `absent(gwy_requests_total)`, entre as 06:00 e as 22:00 UTC (07:00–23:00 WAT) | Nenhum *webhook* contado em 10 min em horário comercial. **Não distingue** «a Meta não envia» de «o GWY não recebe» — o §2 distingue |
| `alvo_em_baixo` | `up == 0` durante 2 min, para **qualquer** alvo | Um processo que o Prometheus raspa deixou de responder |

**O `alvo_em_baixo` não é só deste runbook.** Ler a etiqueta `job` e encaminhar:

| `job` | Vai para |
|---|---|
| `gwy` | **aqui** — §2 |
| `agr` | [RB-K03](RB-K03-llm-em-baixo-ou-sem-budget.md) §3, ramo «o AGR não responde» |
| `com` | **nenhum runbook cobre o COM em baixo.** Fazer o §3.1 deste (reinício e logs) trocando `gwy` por `com`, e abrir incidente. Lacuna registada em [`README.md`](README.md) §5.2 |

## 2. Diagnóstico

Por ordem. Os quatro primeiros dizem se a falha é nossa.

```bash
# 1. Que alvos estão em baixo?
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'up == 0'
```
`verificado` contra o Prometheus v3.7.3 do compose (imagem por *digest*), com as regras
do repositório, num contentor isolado, a 2026-11-09. Sem resultado = todos os alvos
respondem.

```bash
# 2. Chegam webhooks? (0 = nada em 10 min; sem resultado = a série não existe)
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'increase(gwy_requests_total[10m])'
# e quantos foram recusados por assinatura (uma rotação mal feita dá 401 a tudo: RB-K07)
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'increase(gwy_sig_fail[10m])'
```
`verificado` na mesma pilha isolada (a forma da consulta e do comando; sem GWY a correr,
a primeira devolve vazio). Os nomes das métricas são os de
`packages/core-ts/src/entrada/metricas.ts`, sem etiquetas.

```bash
# 3. O GWY está vivo, e o que diz?
docker compose -f infra/compose/docker-compose.prod.yml ps gwy
docker compose -f infra/compose/docker-compose.prod.yml logs --since 30m gwy
```
`não verificado` contra produção. Procurar `falta a variável de ambiente` (§0, ponto 1),
`cofre_inacessivel_no_arranque`, e respostas 503 «queue unavailable» (a fila falhou).

```bash
# 4. A fila de entrada aceita e está a ser consumida?
docker compose -f infra/compose/docker-compose.prod.yml exec queue valkey-cli ping
docker compose -f infra/compose/docker-compose.prod.yml exec queue valkey-cli LLEN bull:wa-inbound:wait
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'inbound_queue_depth'
```
`verificado` o `valkey-cli` na imagem `valkey/valkey:9.1.2` do compose, isolada, a
2026-11-09. A chave `bull:<fila>:wait` é a forma por omissão do BullMQ, a mesma que a
suite `db/tests_eventos` do *gate* 8 lê. `inbound_queue_depth` a **-1** quer dizer que
o GWY não consegue ler a fila. Uma fila a crescer **sem** consumidor é o estado de hoje
(KAM-187), e não um sintoma de Meta em baixo.

**5. É a Meta?** Só depois de 1–4 dizerem que o nosso lado está bem:

- a página de estado da Meta para a WhatsApp Business Platform — **o endereço não está
  neste repositório** e guarda-se na [lista de contactos](../seguranca/contactos_incidentes.md),
  linha «Meta» (NÃO VERIFICADO qual);
- o `proxy-saida` deixa sair? `docker compose -f infra/compose/docker-compose.prod.yml logs --since 30m proxy-saida`
  (`não verificado`): pedidos a `graph.facebook.com` recusados ou sem resposta são
  problema de saída nosso (egress ou DNS), não da Meta.

## 3. Mitigação

### 3.1 A falha é nossa (o GWY ou a fila)

1. **Não há pressa de dados:** com o GWY a responder 5xx ou em baixo, a Meta
   **re-entrega os *webhooks* até 7 dias** com *backoff* (CONFIRMADO, §7). A pressa é
   de clientes sem resposta, não de mensagens perdidas.
2. Se os logs mostram arranque recusado: corrigir a variável ou o segredo em falta
   (§0) e `docker compose -f infra/compose/docker-compose.prod.yml up -d gwy`.
3. Se o GWY está vivo e encravado: `docker compose -f infra/compose/docker-compose.prod.yml restart gwy`,
   **uma** vez. São duas réplicas; o `alvo_em_baixo` diz qual.
4. Se a fila está em baixo: o GWY responde 503 e a Meta repete — tratar a fila
   (`docker compose … restart queue`) e confirmar o §4. **Não** esvaziar a fila à mão.
5. Se a BD está em baixo: o caminho do *webhook* **não toca na BD**, pelo que não é
   isto que pára a ingestão; ver o [RB-K08](RB-K08-base-de-dados-e-restauro.md).

Todos os comandos deste ramo: `não verificado` contra produção.

### 3.2 A falha é da Meta (envio ou entrega)

1. **Não martelar.** O módulo de saída repete só os códigos `130429`, `1` e `2`, até
   **4 tentativas** com *backoff* de base 250 ms e o `Retry-After` a mandar
   (`packages/core-ts/src/outbound/limites.ts`); `131049` e `131047` **não** se
   repetem. Não se reenfileira nada à mão por cima disto.
2. Silenciar os alertas que vão repetir enquanto a causa é externa, **com prazo**:
   ```bash
   docker compose -f infra/compose/docker-compose.prod.yml exec alertmanager \
     amtool --alertmanager.url=http://127.0.0.1:9093 silence add alertname=ingress_parado \
     --duration=2h --author=<papel> --comment="RB-K01: Meta em baixo, incidente <id>"
   ```
   `verificado` contra o Alertmanager v0.28.1 do compose, isolado, a 2026-11-09.
   O `ingress_parado` já inibe os P2 e P3 do mesmo ambiente (`inhibit_rules` do
   `alertmanager.yml`).
3. **Avisar as PMEs pelo canal alternativo** (§6). Por WhatsApp não chega — é o canal
   que falhou.
4. Abrir caso no *Direct Support* da Meta, pelo Business Manager (canal na lista de
   contactos), se a página de estado não reconhecer o problema em 30 min.

### 3.3 Depois de recuperar

1. Confirmar o §4.
2. Ver a fila a escoar (`LLEN` do §2, ponto 4, a descer) — **hoje não escoa**, porque
   não há consumidor (KAM-187).
3. Conciliar o `status` das mensagens enviadas durante a falha — **não há ferramenta**;
   é trabalho do módulo de saída quando estiver ligado.
4. Expirar o silêncio: `docker compose … exec alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 silence expire <id>`
   (`verificado` como o `silence add`).

## 4. Critério de recuperação

- `up == 0` sem resultado (§2, ponto 1);
- `increase(gwy_requests_total[10m]) > 0` em horário comercial (§2, ponto 2);
- `inbound_queue_depth` ≥ 0 e a descer;
- `amtool --alertmanager.url=http://127.0.0.1:9093 alert query alertname=ingress_parado`
  sem linhas.

## 5. Escalamento

Primário → secundário (15 min) → Arquitecto (doc 09 §16). De fora: *Direct Support*
da Meta (Business Manager). Se os logs mostrarem `gwy_sig_fail` a subir depois de uma
rotação, é o [RB-K07](RB-K07-rotacao-de-segredos.md); se houver sinal de abuso, o
[RB-K10](RB-K10-incidente-de-seguranca.md).

## 6. Comunicação

**Interna:** linha temporal do incidente; o canal operacional é o da D10 — entretanto,
o canal do fundador.

**À PME — proposta, por aprovar pelo Responsável de Produto.** Vai por **e-mail**
(canal alternativo). O envio automático de avisos ao dono (`avisos`, KAM-115) existe
e não está ligado, e o fornecedor de e-mail está `pendente` no inventário de
subprocessadores (`gov/subprocessadores.yaml`, entrada `email_sms`): **até lá o envio
é manual**, a partir do canal operacional.

> **Assunto:** KAMBÁ — mensagens do WhatsApp com atraso
>
> Caro parceiro,
>
> Desde as {hora} (hora de Luanda) o WhatsApp está com falhas no envio e na
> recepção de mensagens. A causa {é do lado da Meta, que gere o WhatsApp | está do
> nosso lado e já estamos a tratar}.
>
> Os pedidos dos seus clientes não se perdem: ficam guardados e são respondidos
> assim que o serviço voltar. Enquanto isso, se tiver um cliente à espera de uma
> resposta urgente, pode atendê-lo directamente pelo seu telefone.
>
> Voltamos a escrever quando estiver resolvido.
>
> Equipa KAMBÁ

E, ao recuperar: «Desde as {hora} o WhatsApp voltou a funcionar normalmente. As
mensagens que ficaram pendentes estão a ser respondidas.»

A frase «não se perdem» só é verdade na janela de 7 dias da Meta e **com consumidor a
correr** — hoje não há (KAM-187). Quem aprovar o texto tem de o saber.

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| A Meta re-entrega *webhooks* falhados até 7 dias, com *backoff* exponencial | **CONFIRMADO** | `E1`, linha da re-entrega de *webhooks* |
| O comportamento de desactivação do *webhook* depois de falhas prolongadas | **NÃO VERIFICADO** | doc 09 §12, N6 |
| `130429` é débito excedido e repete-se; `131049` não se repete | do código (`outbound/limites.ts`) e do simulador (`docs/meta-sim.md`) | — |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): encaminhamento do `alvo_em_baixo` por `job`, diagnóstico «nós contra a Meta» com comandos marcados, mitigação por ramo, critério de recuperação, e o texto à PME por aprovar. O §0 regista que o GWY do compose não arranca tal como está escrito | KAM-083 |
