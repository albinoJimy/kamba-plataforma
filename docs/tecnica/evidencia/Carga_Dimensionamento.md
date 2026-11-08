# Carga e dimensionamento — o segmento de entrada medido, e o resto por medir

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Evidência — ensaio de carga e validação do dimensionamento do perfil P0 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Estado | **Parcial.** O segmento de entrada está medido; o AGR, o LLM, o Chatwoot, o Medusa e o *host* P0 não estão |
| Fonte | [`../09_Topologia_Operacao_Escala.md`](../09_Topologia_Operacao_Escala.md) §1.4, §4, §11, §12, §14; [`E1_Meta_WhatsApp.md`](E1_Meta_WhatsApp.md) §5; o bloco KAM-084 em [`../../../specs/EPIC-08_Topologia_Operacao.md`](../../../specs/EPIC-08_Topologia_Operacao.md) |
| Dono | Plataforma/SRE |
| Ticket | KAM-084 (EPIC-08) |
| Classificação | Documento de Referência — Interno |
| Instrumento | [`db/tests_dimensionamento/`](../../../db/tests_dimensionamento/test_cenarios.py) — `python db/gate_bd.py --suite tests_dimensionamento` |

> **O que este documento é.** A medição do único segmento da pilha que hoje
> corre com processos de produção de ponta a ponta — do *webhook* da Meta ao
> *job* do AGR na fila `agr-inbound` — sob cinco cargas, com memória *working
> set* e CPU por contentor, ack, idade na fila e reconciliação de ids.
>
> **O que não é.** Não é a medição do perfil P0. O AGR **não corre turnos** em
> nenhum processo deste repositório (§1), e por isso o LLM, a degradação N1/N2,
> o *handoff* por *flood* e a memória do AGR em carga ficam **não medidos**, com
> credor. O Chatwoot, o Medusa e o LiteLLM sob carga também — e a máquina em que
> isto correu **não é** um *host* de 8 vCPU / 32 GB (§2). Tudo o que este
> documento diz para lá do medido está escrito como **extrapolação**.

---

## 0. Como se lê

Cada número tem o seu estado: **MEDIDO** (saiu de uma corrida deste ensaio, com
o comando em §3), **CITADO** (medido por outro ticket, com o anexo), **NÃO
MEDIDO** (com a razão e o credor) ou **EXTRAPOLAÇÃO** (uma conta sobre um número
medido, que ninguém mediu). Os veredictos do §5 só dizem «confirmado» ou
«corrigido» sobre números MEDIDOS; tudo o resto fica «não medido».

## 1. Porque o AGR não está medido — e não é por escolha

O bloco do ticket manda parar e dizê-lo se um serviço necessário (GWY, AGR,
Vendedor) não existir. **O Vendedor existe como código e não existe como
processo**:

- `services/agr/src/kamba_agr/__main__.py` passa `grafos=sem_grafos` ao
  `ExecutorDeTurnos`;
- `services/agr/src/kamba_agr/turno.py` define o `sem_grafos` como uma porta que
  levanta `grafo_nao_registado`, e o `/internal/turn` responde **503** a todos
  os turnos;
- o grafo do Vendedor (KAM-031) e o de Serviços (KAM-035) têm testes, mas nenhum
  processo os liga — o EPIC-03 regista-o com o credor «quem ligar a porta
  `grafos` do `turno.py`».

Medido em `refs/remotes/publico/main` `619e9826`, e confirmado pelo
orquestrador na mesma ponta. **A decisão foi não montar o grafo num arnês fora
do processo**: mediria uma composição que não é a de produção, e este ensaio
existe para medir a produção.

O que isto deixa **não medido**, todos com o mesmo credor — **o ticket que liga
a porta `grafos` do processo do AGR**:

| Fica por medir | Porque precisa de turnos |
|---|---|
| Memória e CPU do AGR em carga (doc 09 §4.2: 2 GB) | sem turno, o AGR só serve `/healthz` e 503 |
| «~50 conversas simultâneas por processo AGR» (doc 09 §11) | idem; continua **NÃO VERIFICADO** |
| O LLM com *stub* de latência, e a amostra com LLM real | ninguém chama o LLM. A amostra real, que tem custo, só se faria com turnos a correr: sem eles não há onde a pôr, e não se gastou nada |
| A degradação N1/N2 (LiteLLM a 20 s e 5xx) | o detector (`degradacao.py`, KAM-037) existe e não está ligado — o `__main__.py` não constrói `Dependencias` |
| O *flood* redireccionado a *handoff* (RB-K09) e o *budget* por contacto | idem; e **há uma divergência** que o credor herda: o tecto de ritmo por contacto do `admissao.py` (20 msgs/min) **descarta em silêncio**, e o critério pede **redirecção a *handoff*** |
| O LiteLLM, o Chatwoot e o Medusa sob carga | sem turnos não há tráfego para eles; e o Chatwoot e o Medusa não cabem na VM desta máquina (§2) |

## 2. A máquina, e o que se pode dizer a partir dela

| | Este ensaio | O perfil P0 (doc 09 §4.4) |
|---|---|---|
| CPU | **8** vCPU na VM do Docker Desktop (Windows 11, `docker info` → `NCPU 8`) | 8 vCPU |
| Memória | **7 784 MiB = 7,6 GiB** na VM (`MemTotal`) | 32 GB |
| Disco da base | `tmpfs` (o `db/gate_bd.py` levanta o PostgreSQL em memória) | NVMe ≥ 200 GB |
| Docker | 29.7.2, cgroup v2 | — |
| Rede do cliente | Windows → porta publicada do Docker Desktop, sem TLS | Internet → `proxy-tls` (Caddy, TLS) → GWY |

**Consequências, ditas antes dos números:**

1. A **memória** de cada contentor é comparável com o doc 09, porque o *working
   set* de um processo não depende da RAM total da máquina enquanto não houver
   pressão. A **soma** não é «≤ 65% de 32 GB»: é a soma de **cinco** dos catorze
   serviços. Tudo o que se disser sobre os 32 GB a partir daqui é extrapolação.
2. A **CPU** é de outra máquina. Uma VM do Docker Desktop em Windows não tem a
   mesma CPU nem o mesmo escalonador que um *host* Linux dedicado; os núcleos
   medidos são uma ordem de grandeza, não um dimensionamento.
3. O **PostgreSQL está em `tmpfs`**, e o `tmpfs` é contado no cgroup do
   contentor como `shmem` — que **é** *working set*. A memória do PostgreSQL
   deste ensaio inclui os próprios ficheiros da base, que num *host* real
   estariam em disco. Não se compara com os 4 GB do doc 09 (§5).
4. **A máquina é partilhada.** O KAM-085 (simulacro de DR) correu na mesma VM ao
   mesmo tempo. Cada cenário regista os contentores que **não** eram do ensaio
   (`outros_contentores`) e a CPU da VM inteira (`anfitriao`, lida do
   `/proc/stat`), para que a contenção fique medida e não suposta (§4.1).

## 3. O instrumento

```bash
python db/gate_bd.py --suite tests_dimensionamento
# KAMBA_CARGA_RELATORIO=<caminho.json> guarda o relatório; sem ele, vai para a pasta temporária
# KAMBA_CARGA_CENARIOS=s1,rajada corre só esses; os outros saltam, e o código de saída é 1
```

[`db/tests_dimensionamento/`](../../../db/tests_dimensionamento/test_cenarios.py)
levanta um PostgreSQL 18.6 e um Valkey reais (os do *gate* 8, por digest), aplica
as migrações até `head`, semeia **100 tenants `ativo`**, cada um com um canal
`ativo` em coexistência na vertical `vendedor`, e corre os **processos de
produção**: **duas** réplicas de `services/gwy/src/server.ts` (o compose de
produção tem `replicas: 2`) e **uma** de `services/worker-canal/src/entrada.ts`,
que monta o CHR. Os corpos são assinados em Python, numa segunda implementação do
HMAC.

**O que se mede, e como:**

| Grandeza | Como | Porque assim |
|---|---|---|
| Ack | do primeiro byte enviado ao último recebido, no cliente | é o que a Meta vê |
| Ritmo | cada pedido tem um instante-alvo; o atraso face ao alvo regista-se | um gerador atrasado não passa por um sistema que aguenta |
| Idade na fila | `recebido_at` do `inbound_events` (relógio da base) − instante de envio (relógio do Windows), corrigido pelo desvio entre relógios medido pelo menor RTT | sem a correcção, media-se o desvio |
| Reconciliação | o conjunto de `(kind, event_key)` enviado contra o que a base tem; repetidas contam como «a mais» | um `count(*)` não vê uma troca |
| A jusante | `LLEN bull:agr-inbound:wait` contra o número de mensagens **únicas**, por igualdade | os *jobs* do AGR acumulam-se sem consumidor (§1), e é por isso que se podem contar |
| Memória | `memory.current − inactive_file` do cgroup v2 de cada contentor, lido com `docker exec … cat` a cada 2 s | é o *working set* do `kubelet`; ver abaixo |
| CPU | `usage_usec` do `cpu.stat`, em núcleos | idem |
| CPU e memória da VM | `/proc/stat` e `/proc/meminfo` lidos de dentro do contentor do Valkey | não têm *namespace*: dão a máquina inteira, o ensaio **e** o resto |
| Débito do *worker* | eventos por segundo pelo `recebido_at`; o máximo de 10 s consecutivos | é o que a fila consegue drenar |

**O *working set* é a definição do doc 09 §1.4**, «memória residente típica em
carga, distinta da reservada». A reservada é o `mem_limit`; a residente é o que o
cgroup tem carregado **menos** a *page cache* que o kernel pode largar sem custo
(`inactive_file`). A conta está num sítio que um teste lê —
`db/tests_dimensionamento/test_medicao.py::TestWorkingSet`, que afirma que o
número não é o `memory.current` (que conta a cache) nem o `anon` (que esquece a
cache activa). Isto é o «Testes Requeridos» do bloco, à letra.

**O custo da medição está medido.** Em repouso, cada contentor gasta
~0,04–0,06 núcleo, e é sobretudo o próprio `docker exec` a cada 2 s, que corre
dentro do cgroup do contentor. Os números de CPU deste documento incluem-no, o que
é o lado pessimista.

**A ferramenta de carga é a biblioteca padrão do Python** (`http.client`,
`threading`), e não o k6 nem o Locust que o bloco propõe: não acrescenta
dependência nenhuma, e por isso não há licença a registar no SBOM de
ferramentas. O preço é um tecto no gerador, que o ensaio mede (§4.4).

### 3.1 O perfil, e a leitura que se fez dele

O doc 09 §14.1 dá 10 PMEs × 300 conversas × 8 turnos = **24 000** mensagens de
cliente por mês e ≈ 28 800 do bot. Cada mensagem do bot dá três estados (`sent`,
`delivered`, `read`): ~**110 000** *webhooks* por mês. Em 22 dias de 10 horas
úteis, isso é **0,14 *webhooks*/s** em média.

| Cenário | Ritmo | Canais | Duração | Leitura |
|---|---|---|---|---|
| **S1** — pico do Piloto | **5 /s** | 10 | 300 s | *proposta*: ~36× a média das horas úteis. O factor de hora de ponta é uma hipótese a medir com tráfego real (bloco do ticket), e escolheu-se pessimista |
| **S2** — ×10 | **50 /s** | 100 | 300 s | o S1 ×10, como o critério pede |
| **Rajada** | **100 /s**, mais 10% repetidos | 10 | ~210 s | 1 h de *backlog* do S1 (18 000 *webhooks*) reentregue a 20×; 1 800 corpos reenviados 30 s depois com os mesmos bytes |
| **Rampa** | 100 → 200 → 400 → 800 → 1 200 /s, 45 s cada | 100 | até falhar | degraus contíguos, sem drenar; pára no primeiro que falhe o critério 2 ou em que o gerador não imponha a taxa |

A mistura é **1 mensagem de cliente para 3 estados**, a do `E1` §5 e a do
KAM-013. O doc 09 dá 1:3,6 (28 800 respostas para 24 000 mensagens); a diferença
são 20% a menos de estados, e fica dita.

## 4. Resultados

### 4.1 As três corridas, e o que cada uma vale

| Corrida | Quando (UTC) | Vale para | Porque |
|---|---|---|---|
| **1** | 2026-11-08 19:13–19:34 | **nada a jusante do CHR**; o caminho GWY → fila vale como INDÍCIO | o CHR **falhou todas as mensagens**: primeiro com `SemChaveActualError` (não havia versão actual em `platform.hmac_key_versions`) e, corrigido isso numa corrida curta, com `chr_estado_recusou` / `estado_pendente` (os tenants nascem `onboarding`). As duas correcções estão na semente (§6.4). O *worker* fazia o caminho da falha e repetia *jobs*, pelo que o débito e a memória do *worker* não descrevem produção |
| **2** | 2026-11-08 20:15–20:34 | **correcção e *working set*** | com o CHR a encaminhar, mas com o KAM-085 a correr na mesma VM: o `kam085-primario` estava a **2,0–3,2 núcleos e 2,0 GiB** (`docker stats`, duas leituras depois da corrida, com ele ainda activo). O gerador chegou a **33 s** de atraso face ao alvo e os contentores do ensaio a picos de **6,6 núcleos**. Latência e débito desta corrida **não são medição** |
| **3** | **a medir na corrida 3, sem contenção** | latência, idade na fila, débito, rampa e CPU | aguarda a VM livre; o instrumento é o mesmo, com a CPU da VM inteira registada (§3) |

A memória vale da corrida 2 porque o *working set* de um processo é o que ele tem
carregado, e a contenção de CPU atrasa-o mas não o faz carregar outra coisa. Há
um limite, e diz-se: com a VM ocupada, o próprio amostrador atrasou-se — o
repouso da corrida 2 tem **8 amostras** em 60 s em vez de ~30, e uma falha. Os
números de repouso são por isso os mais fracos da tabela.

### 4.2 Correcção — corrida 2, válida

| Cenário | Pedidos | Eventos únicos | Na base | Em falta | A mais | *Jobs* do AGR / mensagens únicas | Drenagem depois do envio |
|---|---|---|---|---|---|---|---|
| S1 (5/s, 300 s) | 1 500 | 1 500 | 1 500 | **0** | **0** | **375 / 375** | 5,8 s |
| S2 (50/s, 300 s) | 15 000 | 15 000 | 15 000 | **0** | **0** | **3 750 / 3 750** | 2,5 s |
| Rajada (100/s + 10% repetidos) | 19 800 | 18 000 | 18 000 | **0** | **0** | **4 500 / 4 500** | 104,6 s |
| Rampa, 1.º degrau (100/s) | 4 500 | 4 500 | 4 500 | **0** | **0** | **1 125 / 1 125** | 14,3 s |

**A rajada é a que pesa.** Os 1 800 corpos repetidos — os mesmos bytes, 30 s
depois — não deram nem uma linha a mais no `inbound_events` nem um *job* a mais
na `agr-inbound`: cada mensagem única deu **exactamente um** *job* do AGR. É o
`UNIQUE (kind, event_key)` na base e o `jobId = sha256(tenant:wamid)` na fila,
medidos juntos e debaixo de contenção. A igualdade afirma-se no ensaio
(`_afirmar_sem_perdas`), e não um `<=`: com `<=`, a corrida 1 passava com **zero**
*jobs*, e passou.

**Um 503 na corrida 2**, no 1.º degrau da rampa: 4 499 respostas 200 e uma 503,
e o evento **está** na base. O GWY desistiu de esperar pela confirmação da fila,
a fila tinha-o aceite, e a Meta reentregaria — a deduplicação absorve-o. É o
comportamento desenhado no KAM-013 («o 200 só depois de o *job* estar
enfileirado»), visto sob contenção, e não é perda.

### 4.3 *Working set* — corrida 2, válida

MiB, p95 por contentor sobre as amostras do cenário (o máximo entre parênteses).

| Contentor | Repouso | S1 (5/s) | S2 (50/s) | Rajada (100/s) | Rampa (100/s) | `mem_limit` no compose de produção |
|---|---|---|---|---|---|---|
| `gwy` réplica A | 46,3 | 54,5 | 170,6 (172,4) | 175,3 (175,5) | 175,1 | 256 MiB |
| `gwy` réplica B | 50,6 | 59,1 | 172,6 (173,8) | 177,1 (177,7) | 187,7 (187,8) | 256 MiB |
| *worker* de entrada (`entrada.ts`) | 53,1 | 58,5 | 121,7 (125,9) | 169,7 (173,2) | 174,2 | **nenhum** — §6.1 |
| PostgreSQL | 118,1 | 123,1 | 132,7 | 136,0 | 133,2 | 5 120 MiB |
| Valkey | 10,5 | 19,4 | 89,0 (93,3) | 103,3 (105,7) | 90,2 (103,9) | 768 MiB |
| **Soma dos p95** | **278,6** | **314,6** | **686,6** | **761,4** | **760,4** | — |

Três leituras, e uma ressalva cada:

- **O GWY sobe para ~175 MiB por réplica e fica.** De ~46 MiB em repouso para
  ~171 MiB a 50/s, e daí não passa muito a 100/s — é o *heap* do V8 a crescer
  com a carga e a não devolver. O máximo medido é **187,8 MiB, 73% do
  `mem_limit` de 256 MiB por réplica**. A folga existe e não é larga; o que ela
  vale a 400/s ou 800/s é da corrida 3.
- **O *worker* de entrada chega aos 174 MiB.** Não tem linha no §4.2 nem
  processo no compose de produção (§6.1 e §6.2).
- **O PostgreSQL e o Valkey não são comparáveis com o doc 09.** O PostgreSQL
  corre em `tmpfs` com uma base quase vazia (§2, ponto 3), e o Valkey guarda os
  *jobs* do AGR que ninguém consome (§1). O que se lê deles é o **segmento**, e
  não o serviço em produção.

A soma dos p95 é um **majorante** (os picos de cada contentor não coincidem) e é
a soma de **cinco** contentores. Não é «memória ≤ 65% de 32 GB».

### 4.4 Latência, idade na fila, débito e rampa

**A medir na corrida 3, sem contenção.** O que as corridas 1 e 2 deixam, e com
que estado:

| Grandeza | O que se viu | Estado |
|---|---|---|
| Ack do GWY até 800 /s | corrida 1, rampa: 67 500 pedidos, **todos 200**, p99,9 de 95,6 / 101,7 / 99,7 / **179,2 ms** a 100 / 200 / 400 / 800 /s; o gerador parou a 800/s (265,6 ms de atraso no p99) e não o GWY | **INDÍCIO** — o caminho GWY → fila não passa pelo CHR, mas a corrida é a 1 |
| *Jobs* aceites pelo BullMQ | ≥ **48 000 por minuto** (800/s) sem 503 e com o Valkey a ≤ 1,05 núcleo | **INDÍCIO**, idem. O «~10k jobs/min» do doc 09 §11 **não é** o limite deste caminho |
| Débito do *worker* de entrada com o CHR a encaminhar | ~**100 eventos/s** no melhor intervalo de 10 s (103,1 e 108,0 /s na rajada e na rampa da corrida 2) | **INDÍCIO** sob contenção. Se se confirmar, é o **primeiro recurso saturado do segmento**: um *worker* com concorrência 1 e uma ligação à base, abaixo do ritmo de 200/s que o GWY aceita |
| Ack a 5/s (S1) | corrida 2: 98,8% abaixo de 500 ms, máximo 1,77 s | **não é medição** (contenção) — e o critério **falhou** nela; a corrida 3 decide |

### 4.5 Limites da Meta — válido

O balde por número e o *backoff* do `130429` são do KAM-015, e a medição
repetiu-se **nesta árvore**: `python db/gate_bd.py --suite tests_outbound` →
`Ran 10 tests … OK`, com o TAP inteiro verde contra o servidor Graph falso do
KAM-024. Os dois ensaios que respondem ao critério, pelo nome:

- `packages/core-ts/tests/outbound.limites.test.ts` — «**100 envios a contactos
  diferentes nunca passam de 15 em nenhuma janela de 1 s**» e «e drenam em
  >= 6,6 s»;
- `packages/core-ts/tests/outbound.adapter.test.ts` — «**tres 130429 e depois um
  200: 1 entregue, 0 duplicados**», com esperas exponenciais e *jitter* de
  meia-base, e o `Retry-After` a mandar.

O tecto é **15 mps por número nos dois modos** (`MPS_POR_MODO`), abaixo dos 20 mps
CONFIRMADOS em coexistência e dos 80 da Cloud API: o *rate limiter* respeita os
dois. **Para o dimensionamento, é um tecto de débito**: um número em
`cloud_only` envia a 15 mps quando a Meta deixaria 80 — o próprio `limites.ts` o
escreve, porque nenhum documento deste repositório fixa o número do
`cloud_only`.

## 5. O §4.2 do doc 09, linha a linha

«Medido» é o p50 / p95 da corrida 2 no cenário de carga mais alto que ela tem
(a rajada a 100/s), em MiB. Os veredictos só se dão sobre o que se mediu.

| Serviço (doc 09 §4.2) | Estimado (Piloto) | Medido p50 / p95 | Veredicto | Proposta de `mem_limit` |
|---|---|---|---|---|
| GWY (2 réplicas) | 0,4 GB | 343,6 / 352,4 (as duas) | **confirmado ±20%, provisório** — o p95 fica 8% abaixo de 0,4 GB (381 MiB); a corrida 3 vai a 800/s | manter **256 MiB por réplica**; o máximo medido é 73% dele |
| AGR (*workers* Python) | 2 GB | — | **não medido** — o AGR não corre turnos (§1) | — |
| Chatwoot (web + Sidekiq) | 4 GB | — | **não medido** — não corre nesta VM; credor: o *host* P0 | — |
| Medusa | 2 GB | — | **não medido** — `pendente` no compose | — |
| `onboarding-web` | 0,5 GB | — | **não medido** — fora do segmento | — |
| PostgreSQL 18 | 4 GB | 130,7 / 136,0 | **não comparável** — `tmpfs` e base quase vazia (§2) | — |
| Redis/Valkey | 0,5 GB | 88,9 / 103,3 | **não confirmado nem corrigido** — o segmento usa 20% da estimativa, mas falta o tráfego dos eventos (EVT) e um consumidor do AGR | — |
| LiteLLM | 1,5 GB | 469,6 em repouso (KAM-076 §9, CITADO) | **não medido em carga** — ninguém chama o LLM (§1) | — |
| Object storage | 0,7 GB | 64,3 em repouso (KAM-076 §9, CITADO) | **não medido em carga** | — |
| Monitorização | 1,5 GB | Prometheus 18,9 em repouso (KAM-076 §9, CITADO) | **não medido em carga** — o ensaio não levanta o Prometheus | — |
| SO, proxy, *exporters* | 1,5 GB | proxies 31,7 em repouso (KAM-076 §9, CITADO) | **não medido em carga** | — |
| *worker* de entrada (`worker-canal`) | **sem linha** | 151,8 / 169,7 | **linha em falta** (§6.2) | ≥ 256 MiB por processo, a calibrar na corrida 3 |
| **Total** | **≈ 18,6 GB** | — | **não medido** — mediu-se um segmento, e somar estimativas a medições não é medir | — |

**Extrapolação, e só isso:** se os cinco contentores medidos fossem tudo o que o
*host* P0 corresse, os 761 MiB da rajada seriam 2,3% de 32 GiB. Não são tudo: o
número diz apenas que **o segmento de entrada não é o que decide o tamanho do
*host***.

## 6. Achados

### 6.1 O compose de produção não corre nenhum consumidor da `wa-inbound`

**Evidência.** O `CMD` do `services/worker-canal/Dockerfile` é
`node services/worker-canal/src/server.ts`, e o serviço `worker-canal` do
`infra/compose/docker-compose.prod.yml` não tem `command:` que o troque. Nenhum
ficheiro de `infra/compose/` nomeia `entrada.ts`, `agr_shim.ts`, `publicador.ts`
ou `consumidor.ts` (procurado com `grep`; só o comentário de
`prometheus/regras/kamba-slo.yml` os cita). **Em produção, o GWY aceitaria
*webhooks* para uma fila que ninguém esvazia**, e o `/healthz` do `worker-canal`
diria que está tudo bem. O KAM-082 já o tinha medido do lado das métricas (bloco
KAM-082, critério 3); este ensaio é o mesmo achado visto do lado da carga: o
processo que ele mede **é** o que falta no compose.

### 6.2 O §4.2 do doc 09 não tem linha para o `worker-canal`

**Evidência.** As linhas do §4.2 são GWY, AGR, Chatwoot, Medusa,
`onboarding-web`, PostgreSQL, Redis/Valkey, n8n, Langfuse, LiteLLM, *object
storage*, Nominatim, Typebot, monitorização e SO. O *worker* de entrada, sozinho,
mediu **169,7 MiB no p95** da rajada (§4.3), e o `worker-canal` tem **quatro**
processos (`entrada`, `agr_shim`, `publicador`, `consumidor`). O compose dá ao
contentor 256 MiB — dimensionados para o `server.ts`, que é o único que corre.

### 6.3 O tecto de ritmo por contacto descarta, e o critério pede *handoff*

**Evidência.** O `services/agr/src/kamba_agr/admissao.py` impõe 20 mensagens por
minuto por contacto com «**descarte silencioso**» para o cliente (a sua
*docstring*, «Ritmo por contacto — 20 msgs/min, *descarte silencioso*
(criterio 5)», do KAM-025), e conta-o em
`agr_admitted_rejected_total{motivo="ritmo"}`. O critério de *flood* deste
ticket pede que um contacto a 100 msg/min seja «**limitado e redireccionado a
*handoff***» (RB-K09). As duas leituras não são a mesma coisa: hoje o atacante é
calado, e ninguém é chamado. Não se mediu nada aqui — o AGR não corre turnos —,
mas a divergência é de texto e lê-se sem carga.

### 6.4 Dois pré-requisitos de dados que nenhum documento lista

O ensaio só encaminhou mensagens para o AGR depois de duas correcções na
semente, e as duas são verdade em produção também:

- **sem uma linha `actual` em `platform.hmac_key_versions`, o CHR falha todas as
  mensagens** com `SemChaveActualError`, e o *job* repete-se. Quem a cria é o
  `iniciarRotacao` (KAM-008); um ambiente novo que arranque o `entrada.ts` sem a
  ter feito regista as mensagens em `inbound_events` e não entrega nenhuma;
- **um tenant em `onboarding` não chega ao AGR**: o CHR regista a conversa e
  recusa pela matriz de estados (`chr_estado_recusou`, `estado_pendente`). É o
  desenho, e diz-se aqui porque um ensaio que o esqueça mede o caminho da recusa
  e parece verde.

### 6.5 O gerador mede o Docker Desktop se o deixarem

Com 64 *threads* a 5 pedidos/s, **535 dos 600** pedidos reabriram a ligação (o
*keep-alive* do Node fecha ao fim de 5 s parado) e o p50 foi 15 ms; com 8,
**zero** e 5 ms. A corrida 1 do S1, com 64, deu p50 de 60 ms. O gerador passou a
`taxa / 8` *threads* e conta as reconexões por cenário (`reconexoes`).

## 7. Custo do ensaio, e os itens do doc 09 que mudam

| Rubrica | Custo |
|---|---|
| *Host* temporário | **0 USD** — não houve. O ensaio correu numa estação de trabalho já existente (§2); o clone de 8 vCPU / 32 GB do bloco não se criou |
| LLM real | **0 USD** — não houve chamada nenhuma (§1), e a amostra com LLM real fica **não medida** |
| Serviços pagos e contrapartes | **0 USD** — o servidor Graph falso do KAM-024 responde pela Meta |
| Tempo de máquina | duas corridas completas de ~20 min (a terceira está por fazer), uma do `tests_outbound` de 8 min e quatro curtas de desenvolvimento; electricidade não medida |

**O que este ensaio muda no doc 09, por medir ou por ler:**

| Doc 09 | O que muda | Estado |
|---|---|---|
| §4.2, linha do GWY | confirmada ±20% no p95, provisoriamente | MEDIDO (corrida 2) |
| §4.2 | falta a linha do `worker-canal` (§6.2) | MEDIDO |
| §4.2, total ≈ 18,6 GB | continua ESTIMATIVA: o segmento medido não o decide | — |
| §11, BullMQ «~10k jobs/min» | o caminho GWY → fila aceitou ≥ 48 000 *jobs*/min; o limite do segmento é o consumidor, não o BullMQ | INDÍCIO (corrida 1); a corrida 3 confirma |
| §11, AGR «~50 conversas/processo» | continua **NÃO VERIFICADO**: o AGR não corre turnos | — |
| §12, N1/N2 | não medido (§1) | — |
| §14.4 | **sem alteração**: nada do que se mediu muda a infra nem o LLM do Piloto | — |

## 8. O que fica por medir, e de quem é

| O que | Credor |
|---|---|
| AGR em carga, «~50 conversas/processo», LLM com *stub* e com amostra real, N1/N2, *flood* com *handoff* e *budget* por contacto | **o ticket que liga a porta `grafos` do processo do AGR** |
| S1 e S2 no *host* P0 (memória ≤ 65% e CPU ≤ 60% de 8 vCPU / 32 GB), Chatwoot, Medusa, LiteLLM e monitorização em carga, e as métricas do ensaio nos painéis do KAM-080 | **o ticket que repete o teste de carga no *host* P0** |
| Latência, idade na fila, débito e rampa sem contenção | **a corrida 3 deste ticket** |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Plataforma/SRE |  |  |  |
| Arquitecto de Plataforma |  |  |  |

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-084): o segmento de entrada medido com os processos de produção — correcção (0 perdidas, 0 a mais e um *job* do AGR por mensagem única em S1, S2, rajada e rampa) e *working set* por contentor, da corrida 2; o GWY confirmado ±20% no p95, provisoriamente; os limites da Meta, do `tests_outbound` repetido nesta árvore. Latência, idade na fila, débito e rampa ficam para a corrida 3, sem contenção. O AGR, o LLM, a degradação e o *flood* ficam **não medidos**, porque o AGR não corre turnos. Três achados com evidência (§6.1 a §6.3). | Equipa KAMBÁ |
