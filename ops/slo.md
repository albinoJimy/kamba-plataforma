# SLOs e orçamento de erro da KAMBÁ

| Campo | Valor |
|---|---|
| Ticket | KAM-082 |
| Âmbito | Os 8 SLI do doc 09 §10, o orçamento de erro a 30 dias, os alertas de *burn rate* e a política de orçamento |
| Fontes | [`../docs/tecnica/09_Topologia_Operacao_Escala.md`](../docs/tecnica/09_Topologia_Operacao_Escala.md) §10, §16 e §17; [`../docs/tecnica/00_Arquitectura_Solucao.md`](../docs/tecnica/00_Arquitectura_Solucao.md) §9; ADR-018 |
| Estado | **Um dos oito SLI está operacional, e os outros sete têm credor escrito.** Ver §2 |
| Depende de | KAM-080 (métricas, regras, painéis, `obs_lint`) |
| Não cobre | *Runbooks* executáveis (KAM-083), custo por *tenant* (KAM-081), a ligação da política de congelamento a um portão (**o fundador**, §6), a rotação de *on-call* (**o fundador**, §7) |

---

## 1. O número que governa tudo o que segue

```text
30 dias           = 43 200 min
99,5%             = o SLO de disponibilidade do caminho de venda no Piloto (doc 00 §9)
0,5% de 43 200    = 216 min = 3,6 h de orçamento de erro por janela de 30 dias
```

O 99,9% da Escala (43 min) fica **documentado e inactivo**, como os Detalhes
Técnicos do ticket mandam.

E a frase do doc 09 §16 que não se deve perder de vista: **os 216 min não cobrem
noites inteiras sem resposta.** Oito horas de silêncio nocturno são 480 min — mais
do dobro do orçamento mensal — e é por isso que a sonda externa e a rotação de
*on-call* são parte do SLO e não acessórios. Nenhuma das duas existe hoje (§2,
§7).

---

## 2. Os oito SLI, e o estado medido de cada um

O doc 09 §10 define oito. A coluna **Estado** não é uma opinião: mede se existe
uma série que *algum processo sirva* e que o `prometheus.yml` *raspe*. Os três
alvos raspados são `gwy:3010`, `com:3002` e `agr:8000`.

> **Porque é que isto se mede antes de operacionalizar.** Das **120** métricas
> declaradas em código (medido: `python tools/obs_lint/contar_metricas.py`; 122
> pela reconciliação `+2` do `services/com`), só **51** são alcançáveis numa
> pilha de `docker compose` — onze módulos do `packages/core-ts` não são
> importados por nenhum serviço. Um SLI assente numa série que ninguém produz
> **nunca dispara**, e um alerta que nunca dispara **parece cobertura**: é pior
> do que a sua ausência, porque ninguém volta a olhar. É a leitura com que o
> KAM-080 deixou oito das doze regras do §9.2 por escrever e o KAM-076 recusou
> um `scrape_config` para um `/metrics` inexistente.

### 2.1 SLI-1 — Disponibilidade do caminho de venda · **operacional**

| Campo | Valor |
|---|---|
| Predicado | Receber → processar → responder está servível |
| Numerador | Instantes de avaliação em que **todas** as réplicas do GWY e do AGR estavam raspáveis, menos os instantes isentos pela regra das janelas (§5) |
| Denominador | Instantes de avaliação da janela, menos os isentos |
| Janela | 30 dias corridos (deslizante) |
| Fonte | `up{job=~"gwy\|agr"}`, sintética do Prometheus, uma série por réplica |
| SLO | **99,5%** (Piloto); 99,9% documentado e inactivo (Escala) |
| Orçamento | **216 min** por 30 dias |
| Séries | `slo_caminho_de_venda_bom`, `slo_caminho_de_venda_mau`, `slo_caminho_de_venda_ratio_30d` |

**Três limites, e o terceiro é o que importa mais:**

1. **Não vê o que o cliente vê.** `up` diz que o Prometheus conseguiu raspar o
   processo de dentro da pilha. Internet, DNS, TLS e a Meta ficam fora. A sonda
   externa é o critério 5 do KAM-080, que ficou **vazio** por não haver produção
   nem *host* externo onde a pôr — credores **D1/KAM-105** (alojamento) e
   **KAM-069** (subprocessador).
2. **O `worker-canal` não está no numerador**, embora seja o «processar». O `CMD`
   do `services/worker-canal/Dockerfile` corre `src/server.ts`, que devolve
   **404** em `/metrics` por teste do KAM-001; as quatro entradas que servem
   métricas (`entrada.ts` 3013, `publicador.ts` 3011, `consumidor.ts` 3012 e
   `agr_shim.ts`) **não são o que o compose corre**, e o `prometheus.yml` não tem
   alvo para elas. Medido. Credor: o ticket que decidir qual processo do
   `worker-canal` o compose corre.
3. **Uma paragem do próprio Prometheus subconta o orçamento.** Sem avaliação não
   há amostra, e `avg_over_time` ignora o intervalo em falta — pelo que a pior
   avaria possível, o anfitrião todo em baixo, é a única que este SLI não vê. O
   simétrico também é verdade e é deliberado: sem nenhum alvo descoberto o
   caminho conta como **mau** (`or vector(0)`), logo um arranque a frio de mais
   de 4,32 min numa hora gasta mesmo essa fatia.

### 2.2 Os sete que não se operacionalizam hoje

Cada um fica com o predicado escrito — para que o ticket que trouxer a série não
tenha de o reinventar — e com o **credor**.

**A janela é a mesma dos oito: 30 dias corridos, deslizante.** A coluna **Fonte**
é a do §10 do doc 09, copiada de lá e não reinterpretada: é a origem do *alvo*, e
não a série que o mediria — essa é o que falta, e está na última coluna.

| # | SLI | Numerador / denominador | SLO | Orçamento | Fonte (§10) | O que falta, e o credor |
|---|---|---|---|---|---|---|
| 2 | Ack do webhook < 500 ms | pedidos com ack < 500 ms / pedidos aceites | 99,9% | 0,1% | `E1`, doc 00 | **Não há histograma de ingress.** O `gwy_enqueue_ms` é um *gauge* do **último** enfileiramento; um percentil exige `_bucket`, e uma fracção de amostras do último valor é uma amostragem enviesada e não o predicado. Credor: o ticket que der histogramas ao módulo `entrada` |
| 3 | Perda de mensagens | ids aceites sem desfecho após 15 min / ids aceites | **0** | 0 | — | **Duas faltas.** O `inbound_events_total{desfecho}` (`registado`, `duplicado`, `recuperado`) existe e é servido pelo `entrada.ts`, que **não é** o que o compose corre (ver §2.1, limite 2); e a correlação *por id* entre aceite e desfecho não é expressável em métricas agregadas — sai de consulta SQL sobre `platform.channel_events`, pela mesma razão por que o por-*tenant* sai de SQL (dicionário, emendas 1.21 e 1.25). Credor: o ticket que decidir o processo do `worker-canal`, e o KAM-110 para a consulta |
| 4 | Latência de resposta p95 | turnos ≤ alvo / turnos | texto ≤ **8 s**; voz ≤ **12 s** | 5% acima do alvo | doc 00 §9 | **O p95 não é computável e a modalidade não é distinguível.** O AGR não tem histogramas, por **ADR-018** («observabilidade leve»), escrito no próprio `metricas.py`; o `agr_turn_latency_ms` é o valor do último turno. E não há etiqueta de modalidade que separe texto de voz — criá-la é uma emenda ao dicionário. O KAM-080 nomeou o KAM-082 credor do quantil; **este ticket mede-o e devolve-o**, porque dar histogramas ao AGR é contrariar um ADR em vigor, e isso é do **fundador** |
| 5 | Callback → cliente notificado | notificações ≤ alvo / callbacks aceites | p95 ≤ **30 s**; p99 ≤ **2 min** | 1% | `04` | O módulo `hnd` não é importado por nenhum serviço, e «reconciliados» não tem métrica nenhuma. Credor: o ticket que ligar o módulo `hnd` |
| 6 | Reconciliação por reconhecer | idade do mais antigo por reconciliar | ≤ **15 min** | — | `E2` (*polling*) | Não há métrica de reconciliação de pagamentos. Credor: o ticket que ligar o módulo `hnd` |
| 7 | Frescura do backup | idade do último WAL arquivado; desfecho do restauro mensal | WAL ≤ **5 min**; restauro mensal OK | 0 falhas | doc 09 §8 | Não há pgBackRest nem *exporter*, e não há *job* de restauro cujo desfecho se possa contar. Credor: **KAM-079** |
| 8 | Número em estado vermelho | horas com `rating=red` acima de 24 h | **0 h** | — | `E1` | O `channel_quality{rating}` existe no módulo `qualidade`, com domínio fechado em três — e é o exemplo que o dicionário usa para explicar o `OBS-I` —, sem serviço que o importe. Credor: o ticket que ligar o módulo `qualidade` |

**Não se escreveram como regras inertes**, pela razão da citação do §2. As sete
linhas ficam aqui e não em YAML.

---

## 3. A aritmética do orçamento, e como está provada

```text
fracção_má        = avg_over_time(slo_caminho_de_venda_mau[30d])
consumido         = fracção_má / 0,005          → fracção do orçamento de 216 min
restante_minutos  = 216 × (1 − consumido)
```

O critério 2 do ticket dá o número que prova isto: **30 min de falha descem o
orçamento 13,9%** (30/216), deixando **186 min**. Está escrito como ensaio e não
como afirmação —
[`../infra/compose/prometheus/regras/testes/kamba_slo_test.yml`](../infra/compose/prometheus/regras/testes/kamba_slo_test.yml),
caso `orcamento: 30 min de falha injectada descem 13,9% (30/216)` → `0,1388888…`
e `186`.

Com três casos e não um: o controlo (30 dias sem falha → 216 min inteiros) e o
estouro (240 min de falha → **−24 min**, negativo de propósito, porque o excesso
é o número de que a política dos 100% precisa).

> **O que o ensaio não é.** `promtool test rules` corre o motor de regras com
> séries sintéticas: não há pilha, não há GWY a morrer, não há Alertmanager a
> receber. **E não há *staging*** — o Prometheus só existe no
> `docker-compose.prod.yml`, não há ambiente implantado, e o `make up` (dev) não
> levanta Prometheus nenhum. A «injecção de falha em *staging*» que os critérios
> 2 e 3 pedem **não tem onde correr**, e a caixa fica parcial por isso. O que o
> ensaio fecha é a pergunta anterior, que é a que se pode fechar hoje: *dada a
> série, a conta está certa?*

### 3.1 A janela de 30 dias exigiu 31 dias de retenção

O `--storage.tsdb.retention.time` do `docker-compose.prod.yml` era **15d**. Um
`avg_over_time(...[30d])` sobre 15 dias de dados **não dá erro**: devolve a média
das amostras que existem. O efeito é o pior desta família — um número errado com
ar de certo, e enviesado para o lado optimista, porque uma avaria de há 20 dias
cai fora da janela e o orçamento «sara» duas semanas antes do devido. Este ticket
põe a retenção em **31d**, um dia de folga sobre a janela.

---

## 4. Os alertas de *burn rate*

| Alerta | Condição | Em minutos | Severidade |
|---|---|---|---|
| `orcamento_de_erro_burn_rapido` | > **2%** do orçamento na última **1 h** | > **4,32 min** numa hora | **P2** |
| `orcamento_de_erro_burn_lento` | > **5%** do orçamento nas últimas **6 h** | > **10,8 min** em seis horas | **P3** |

Os dois limiares são **proposta** do próprio ticket, a calibrar nos primeiros 30
dias de operação real. *Runbook*:
[`../docs/runbooks/orcamento-de-erro.md`](../docs/runbooks/orcamento-de-erro.md).

**A unidade é a do critério** — fracção do orçamento total por janela — e não o
múltiplo adimensional (14,4× e 6,0×) que a mesma coisa dá na convenção mais
comum. Escolheu-se assim para que o limiar da regra seja o número que o critério
escreve, sem conversão pelo meio.

**O que prende a calibração são os casos em volta do limiar**, e não um caso que
dispare. Em
[`../infra/compose/prometheus/regras/testes/kamba_slo_burn_test.yml`](../infra/compose/prometheus/regras/testes/kamba_slo_burn_test.yml):
4 min de falha numa hora → calado; 5 min → dispara; 10 min em seis horas →
calado; 11 min → dispara. E o caso que mostra que o lento não é redundante: 11
min no **início** das seis horas disparam o lento com o rápido calado.

---

## 5. Janelas de manutenção (critério 6)

A regra do doc 09 §10, nas **três** condições que ela tem: uma janela
**anunciada**, **fora** de 07:00–23:00 WAT e que **não afectou mensagens** não
conta como indisponibilidade. Qualquer uma das três a faltar, conta.

A conversão de horário é a mesma do `ingress_parado`: **07:00–23:00 WAT =
06:00–22:00 UTC**, porque o `hour()` do Prometheus é UTC.

A isenção faz-se por `unless`, pelo que a amostra **desaparece** em vez de valer
0: o tempo isento sai do numerador **e** do denominador, que é o tratamento
convencional de uma janela acordada.

**O que está medido:** três casos em `kamba_slo_burn_test.yml` — isenta; conta
porque afectou mensagens; conta porque era horário comercial. E o mecanismo do
anúncio (a aritmética de instantes) em
[`../infra/compose/prometheus/regras/testes/kamba_manutencao_test.yml`](../infra/compose/prometheus/regras/testes/kamba_manutencao_test.yml),
com duas janelas, sobre a *fixture* `fixtures/janelas-de-exemplo.yml`.

**Dois limites:**

1. **«Afectou mensagens» mede um predicado mais fraco do que o pedido.** O sinal
   é `increase(gwy_shed_total[30m]) > 0`: vê os pedidos que **nós** descartámos
   estando em pé, não os que nunca chegaram porque o ingress estava em baixo — que
   é precisamente o caso de uma janela. O predicado completo é o que a sonda
   externa responderia (credores **D1/KAM-105** e **KAM-069**).
2. **A lista de janelas anunciadas está vazia**, em
   [`../infra/compose/prometheus/regras/kamba-manutencao.yml`](../infra/compose/prometheus/regras/kamba-manutencao.yml),
   porque nenhuma janela foi anunciada — não há produção nem *staging*. Anunciar
   uma é editar o ficheiro e recarregar o Prometheus, o que é operação pobre para
   uma equipa de 3–4 pessoas; um produtor melhor exige um *exporter* de
   contentores, que nenhum compose tem.

---

## 6. Política de orçamento — **escrita, medida, e não ligada** (critério 5)

### 6.1 A política, por extenso

| Estado | Condição | Efeito |
|---|---|---|
| `normal` | ≤ 50% do orçamento consumido numa janela de 14 dias | nenhum |
| `congelado` | **> 50%** do orçamento consumido em **14 dias** | o *gate* 16 recusa *deploys* **não urgentes**; excepção só com aprovação do Arquitecto **registada** |
| `só fiabilidade` | **100%** do orçamento consumido | só entra trabalho de fiabilidade até o orçamento recuperar |

Um *deploy* é **urgente** quando corrige o próprio incidente que está a consumir
o orçamento, ou quando é uma correcção de segurança. Qualquer outro é não
urgente. (*Proposta*: o doc 09 §10 e o bloco do ticket não definem «urgente».)

### 6.2 O que este ticket entrega da política

**A medição.** O painel
[`paineis/orcamento-de-erro.json`](paineis/orcamento-de-erro.json) mostra
`slo_caminho_de_venda_orcamento_consumido` com o limiar de 0,5 marcado a laranja
e o de 1,0 a vermelho, e o `slo_caminho_de_venda_orcamento_restante_minutos` ao
lado — que é o número que distingue «um *burn* a atender» de «uma decisão de
congelamento».

Com uma divergência dita à cabeça: a política fala de **14 dias** e as *recording
rules* medem a janela de **30 dias**, que é a que o critério 1 e o doc 09 §10
definem. Uma segunda janela de 14 dias é uma linha de PromQL
(`avg_over_time(slo_caminho_de_venda_mau[14d]) / 0.005`) e **não se escreveu**,
porque sem o estado `congelado` a existir ela não teria consumidor — e seria mais
uma série a parecer cobertura. Entra com a decisão, no mesmo PR que ligar o
portão.

### 6.3 O que este ticket **não** entrega, e porquê

**O estado `congelado` não existe e o *gate* 16 não o lê.** Não é falta de tempo:

- **O *gate* 16 não é um *job* de CI.** O `specs/01` §4 define-o como
  «**Aprovação** — gate humano (dois revisores para P0 de dinheiro/segurança)»,
  e o `.github/workflows/ci.yaml` tem *jobs* para os gates 1, 2, 3, 3b, 3c, 4, 6,
  7, 8, 9 e 11 — **e mais nenhum**. Não há *pipeline* de *deploy* onde o estado
  entre.
- **Ligá-lo é alterar uma regra de bloqueio, pelos dois caminhos.** Um *job* novo
  acrescenta um contexto exigido ao *ruleset* da `main` (e ao agregador «gates do
  KAM-002», que hoje tem onze `needs`); e mudar o critério de um portão que já
  bloqueia é a mesma fronteira por outra porta. É a fronteira que o KAM-080
  respeitou ao não ligar o `obs_lint` a nenhum portão.

**Credor: o fundador.** O que falta para decidir é uma coisa só — se o estado
`congelado` passa a ser um contexto exigido da `main`. A implementação, depois
dessa decisão, é a *recording rule* de 14 dias do §6.2 mais o *job* que a lê.

---

## 7. *On-call* — **devolvido** (critério 7)

O doc 09 §16 pede rotação semanal entre **≥ 3 pessoas**, cobertura 07:00–23:00
WAT, escalamento primário → secundário (15 min) → arquitecto.

**Isto é gente, não código, e não se simula.** Um «teste de simulação de
escalamento» sem pessoas na rotação e sem notificador no Alertmanager mediria um
ficheiro a ler-se a si próprio. E há duas faltas a montante:

1. **O Alertmanager não notifica ninguém.** Os três `receivers` não têm
   notificador, porque o canal de alertas **não está escolhido** — escolher um
   acrescenta um subprocessador (**KAM-069**). Sem canal não há escalamento a
   testar: o KAM-080 já deixou esta caixa vazia pela mesma razão.
2. **Não há nomes, e não os pode haver.** O repositório é **público**. A rotação
   fica em [`on-call.md`](on-call.md) com marcadores de **papel** e nenhum nome
   de pessoa, como o *handoff* do ticket manda («não inventes ligações a pessoas
   reais: a rotação é um ficheiro com marcadores a preencher pelo Responsável de
   Produto»).

**Credor: o fundador**, para a composição da rotação; **KAM-069** para o canal.

---

## 8. Relatório mensal

O modelo está em [`slo-relatorio-modelo.md`](slo-relatorio-modelo.md). É um
modelo e não um relatório: não há 30 dias de operação para relatar.

---

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Documento criado pelo **KAM-082**. Os 8 SLI do doc 09 §10 definidos com numerador, denominador, janela, fonte, SLO e orçamento; **um** operacional e sete com credor medido. *Recording rules* do orçamento de 216 min, painel do restante, alertas de *burn rate* rápido (P2) e lento (P3), regra das janelas de manutenção nas suas três condições, e retenção do TSDB de 15d para 31d. **Devolve com credor:** a ligação do estado `congelado` ao *gate* 16 (o fundador) e a rotação de *on-call* (o fundador, e KAM-069 para o canal). | Equipa KAMBÁ |
