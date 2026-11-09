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

O que isto deixa **não medido**, todos com o mesmo credor — **KAM-186**, o ticket que liga
a porta `grafos` do processo do AGR:

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
4. **A máquina é partilhada.** O KAM-085 (simulacro de DR) correu na mesma VM
   durante as corridas 1 e 2, e a corrida 3 esperou que ele acabasse (§4.1). Cada
   cenário regista os contentores que **não** eram do ensaio
   (`outros_contentores`) e a CPU da VM inteira (`anfitriao`, lida do
   `/proc/stat`), para que a contenção fique medida e não suposta.

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
| **1** | 2026-11-08 19:13–19:34 | **nada a jusante do CHR** | o CHR **falhou todas as mensagens**: primeiro com `SemChaveActualError` (não havia versão actual em `platform.hmac_key_versions`) e, corrigido isso numa corrida curta, com `chr_estado_recusou` / `estado_pendente` (os tenants nascem `onboarding`). As duas correcções estão na semente (§6.4). O *worker* fazia o caminho da falha e repetia *jobs* |
| **2** | 2026-11-08 20:15–20:34 | **só correcção** | o CHR já encaminhava, mas o KAM-085 corria na mesma VM: o `kam085-primario` a **2,0–3,2 núcleos e 2,0 GiB** (`docker stats`, duas leituras depois da corrida, com ele ainda activo), o gerador com até **33 s** de atraso face ao alvo e os contentores do ensaio com picos de **6,6 núcleos**. A correcção da corrida 2 coincide com a da 3, e fica como segunda corrida independente da mesma propriedade |
| **3** | **2026-11-09 08:05–08:26** | **tudo o que este documento cita como medido** | a VM acabada de reiniciar, `docker ps` sem contentor nenhum antes de começar, e **`outros_contentores` vazio nos cinco cenários**. A CPU da VM inteira (que inclui tudo o que lá corre) ficou em p95 de 9,2% em repouso e no máximo 62,6% no pico da rampa. `Ran 27 tests … OK`, à ponta `e20e4953` integrada |

Salvo indicação, **os números de baixo são da corrida 3**.

### 4.2 Correcção

| Cenário | Pedidos | Eventos únicos | Na base | Em falta | A mais | *Jobs* do AGR / mensagens únicas | Drenagem depois do último envio |
|---|---|---|---|---|---|---|---|
| S1 (5/s, 300 s) | 1 500 | 1 500 | 1 500 | **0** | **0** | **375 / 375** | 0,0 s |
| S2 (50/s, 300 s) | 15 000 | 15 000 | 15 000 | **0** | **0** | **3 750 / 3 750** | 0,0 s |
| Rajada (100/s + 10% repetidos) | 19 800 | 18 000 | 18 000 | **0** | **0** | **4 500 / 4 500** | **0,0 s** — a fila nunca passou de **18** *jobs* |
| Rampa (100 → 800/s) | 67 500 | 67 500 | 67 500 | **0** | **0** | **16 875 / 16 875** | **180,8 s** para um *backlog* de 43 945 |

**A rajada é a que pesa.** 18 000 *webhooks* — uma hora do S1 — a 20× o ritmo, e
**mais 1 800 corpos repetidos** com os mesmos bytes 30 s depois. Os repetidos não
deram nem uma linha a mais no `inbound_events` nem um *job* a mais na
`agr-inbound`: cada mensagem única deu **exactamente um** *job* do AGR. É o
`UNIQUE (kind, event_key)` na base e o `jobId = sha256(tenant:wamid)` na fila,
medidos juntos. **A fila drenou à medida que chegava**: o máximo foi 18 *jobs* e,
no fim do último envio, estava vazia — os 18 000 trataram-se nos ~210 s do próprio
envio. A igualdade a jusante afirma-se no ensaio (`_afirmar_sem_perdas`), e não
um `<=`: com `<=`, a corrida 1 passava com **zero** *jobs*, e passou.

**A corrida 2 deu o mesmo resultado**, sob contenção: 0 em falta e 0 a mais nos
quatro cenários, e 375, 3 750, 4 500 e 1 125 *jobs* para as mesmas mensagens
únicas. Teve **uma** resposta 503 (rampa, 1.º degrau) cujo evento **está** na
base: o GWY desistiu de esperar pela confirmação da fila, a fila tinha-o aceite,
e a deduplicação absorve a reentrega da Meta.

### 4.3 Ack, idade na fila e CPU — S1, S2 e rajada

| | S1 (5/s) | S2 (50/s) | Rajada (~94/s com as repetidas) |
|---|---|---|---|
| Respostas | 1 500 × 200 | 15 000 × 200 | 19 800 × 200 |
| Ack p50 / p95 / p99 | 4,1 / 18,7 / 35,2 ms | 3,7 / 15,3 / 32,1 ms | 3,2 / 17,5 / 34,4 ms |
| Ack p99,9 / máximo | 147,5 / 251,6 ms | 64,2 / 114,9 ms | 66,7 / 116,7 ms |
| **Ack < 500 ms** (critério: ≥ 99,9%) | **100%** | **100%** | **100%** |
| **Idade na fila** p99 / máximo (critério: < 2 min) | 0,03 / **0,14 s** | 0,04 / **0,14 s** | 0,12 / **0,22 s** |
| Erro da correcção de relógio | ≤ 0,5 ms | ≤ 0,3 ms | ≤ 0,3 ms |
| Atraso do gerador p99 | 1,3 ms | 1,0 ms | 1,2 ms |
| Reconexões do gerador | 0 | 61 | 26 |
| **CPU da VM inteira** p95 / máx | **12,0 / 15,2%** | **20,1 / 22,6%** | 28,3 / 34,4% |
| Memória usada da VM, p95 | 1 275 MiB (16%) | 1 601 MiB (21%) | 1 724 MiB (22%) |
| Soma dos núcleos dos cinco contentores, p95 | 0,40 | 0,86 | 1,31 |

**À escala desta máquina, o S1 e o S2 cumprem os cinco números do critério 2**:
ack, idade, perdas, CPU ≤ 60% (12% e 20%) e memória ≤ 65% (16% e 21% de
7,6 GiB). **Não é a letra do critério**, que fala do *host* de 32 GB com o
conjunto inteiro, e dos catorze serviços só cinco estão aqui (§2). A memória da
VM inclui o próprio Docker Desktop: em repouso, com os cinco contentores, já eram
1 269 MiB.

### 4.4 A rampa, o primeiro recurso saturado e o débito da fila

Degraus contíguos de 45 s, 100 tenants, sem drenar entre degraus:

| Degrau | Respostas | Ack p50 / p99,9 / máx | Atraso do gerador p99 | Fila de entrada no fim do degrau |
|---|---|---|---|---|
| 100/s | 4 500 × 200 | 3,5 / 71,1 / 113,3 ms | 1,2 ms | **0** |
| 200/s | 9 000 × 200 | 3,3 / 69,2 / 110,8 ms | 1,3 ms | **231** |
| 400/s | 18 000 × 200 | 7,5 / 129,9 / 173,7 ms | 2,5 ms | **11 762** |
| 800/s | 36 000 × 200 | 27,6 / 228,0 / 341,6 ms | **389,1 ms** — parou aqui | **43 945** |

**O primeiro recurso saturado do segmento é o *worker* de entrada**, entre 200 e
400 eventos/s. A 200/s a fila já cresce (231 no fim do degrau); a 400/s cresce
~256 por segundo, o que põe o consumo em **~144 eventos/s com o GWY a
ingerir**. Sem ingestão, na drenagem, o mesmo *worker* tratou os 43 945 em
180,8 s (~243/s, e **349/s** no melhor intervalo de 10 s). **Não é CPU**: o
*worker* ficou em 0,58 núcleo no p95 e 0,89 no máximo. É latência — concorrência 1
e uma ligação à base, com várias consultas do CHR por evento, uma de cada vez — e
piora quando o PostgreSQL e o Valkey estão ocupados com a ingestão. O
`entrada/trabalhador.ts` escreve-o por si: «um *job* de cada vez por *worker*.
Escala-se com réplicas».

**Consequência que se pode medir já:** a idade na fila passou os 2 min do
critério na rampa — **máximo de 180,7 s**, a 400 e 800/s. Com o perfil do S1 a 5/s está
~40× abaixo dos ~200/s a que o *worker* começa a acumular: o limite existe e está
longe do Piloto.

**O GWY e o BullMQ não saturaram.** A 800/s as duas réplicas responderam 200 a
tudo, com p99,9 de 228 ms; quem parou a rampa foi o **gerador** (389 ms de atraso
no p99), e não o sistema. Mas o GWY chegou perto: **0,95 e 1,20 núcleos no
máximo** por réplica, contra `cpus: 1.0` no compose de produção — um processo Node
é um fio, e 400/s por réplica é perto do tecto dele nesta máquina. O Valkey aceitou
os 800/s, isto é **48 000 *jobs* por minuto**, com 0,51 núcleo no p95 (1,30 no
máximo). Acima disto **não se mediu**: o gerador não chega.

| O doc 09 §11 diz | Medido |
|---|---|
| BullMQ/Redis «~10k jobs/min» | **≥ 48 000 *jobs*/min aceites**, e o consumo é o limite: **~8 600/min** com ingestão a 400/s (~144/s) e **até 20 952/min** a drenar, **com um *worker***. Os 10k/min não são o tecto do BullMQ neste caminho, e são da ordem do que **um** consumidor dá |
| AGR «~50 conversas simultâneas/processo» | **NÃO VERIFICADO**: o AGR não corre turnos (§1) |

### 4.5 *Working set*

MiB, p95 por contentor (o máximo entre parênteses).

| Contentor | Repouso | S1 (5/s) | S2 (50/s) | Rajada (~94/s) | Rampa (até 800/s) | `mem_limit` no compose de produção |
|---|---|---|---|---|---|---|
| `gwy` réplica A | 60,2 | 56,6 | 173,9 | 177,4 | 185,4 (186,0) | 256 MiB |
| `gwy` réplica B | 65,4 | 62,1 | 171,2 | 175,2 | 183,7 (183,9) | 256 MiB |
| *worker* de entrada (`entrada.ts`) | 65,4 | 68,4 | 182,2 | 177,9 | 196,6 (200,6) | **nenhum** — §6.1 |
| PostgreSQL | 150,6 | 154,1 | 162,1 | 182,5 | 219,1 (225,6) | 5 120 MiB |
| Valkey | 16,0 | 24,5 | 93,7 | 95,6 | 171,8 (201,6) | 768 MiB |
| **Soma dos p95** | **357,6** | **365,7** | **783,1** | **808,6** | **956,6** | — |

- **O GWY sobe para ~175 MiB por réplica e fica.** É o *heap* do V8 a crescer
  com a carga e a não devolver: de ~60 MiB para ~174 a 50/s, e só 186 a 800/s. O
  máximo medido é **186,0 MiB, 73% do `mem_limit` de 256 MiB** por réplica.
- **O *worker* de entrada chega aos 200,6 MiB.** Não tem linha no §4.2 nem
  processo no compose de produção (§6.1 e §6.2).
- **O PostgreSQL cresce com os dados**, porque corre em `tmpfs` (§2, ponto 3): de
  151 MiB em repouso para 220 MiB depois de ~100 000 eventos escritos (e
  apagados entre cenários, o que não devolve o espaço). Não é comparável
  com o doc 09.
- **O Valkey é o *backlog***: 201,6 MiB no máximo, com os 43 945 *jobs* de
  entrada da rampa e os 16 875 do AGR que ninguém consome (§1), o que dá uma
  ordem de grandeza de **~3 KiB por *job***. Em produção o `maxmemory` é 600 MB.

A soma dos p95 é um **majorante** (os picos não coincidem) e é a soma de **cinco**
contentores. A corrida 2 deu os mesmos patamares (GWY ~175 MiB por réplica,
*worker* ~174 MiB): a memória quase não se moveu com a contenção.

### 4.6 Limites da Meta

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

«Medido» é o p50 / p95 da corrida 3 na **rampa** (o cenário mais alto que o
gerador consegue), em MiB. Os veredictos só se dão sobre o que se mediu.

| Serviço (doc 09 §4.2) | Estimado (Piloto) | Medido p50 / p95 | Veredicto | Proposta de `mem_limit` |
|---|---|---|---|---|
| GWY (2 réplicas) | 0,4 GB | 360,4 / 369,1 (as duas) | **confirmado ±20%** — o p95 a 800/s fica 3% abaixo de 0,4 GB (381 MiB) | manter **256 MiB por réplica**: o máximo medido é 186 MiB, 73% dele |
| AGR (*workers* Python) | 2 GB | — | **não medido** — o AGR não corre turnos (§1) | — |
| Chatwoot (web + Sidekiq) | 4 GB | — | **não medido** — não corre nesta VM; credor: KAM-188 | — |
| Medusa | 2 GB | — | **não medido** — `pendente` no compose | — |
| `onboarding-web` | 0,5 GB | — | **não medido** — fora do segmento | — |
| PostgreSQL 18 | 4 GB | 185,3 / 219,1 | **não comparável** — `tmpfs` e base quase vazia (§2) | — |
| Redis/Valkey | 0,5 GB | 124,8 / 171,8 | **não confirmado nem corrigido** — é o *backlog* de um ensaio que satura o consumidor (§4.5), e falta o tráfego dos eventos (EVT) e um consumidor do AGR | — |
| LiteLLM | 1,5 GB | 469,6 em repouso (KAM-076 §9, CITADO) | **não medido em carga** — ninguém chama o LLM (§1) | — |
| Object storage | 0,7 GB | 64,3 em repouso (KAM-076 §9, CITADO) | **não medido em carga** | — |
| Monitorização | 1,5 GB | Prometheus 18,9 em repouso (KAM-076 §9, CITADO) | **não medido em carga** — o ensaio não levanta o Prometheus | — |
| SO, proxy, *exporters* | 1,5 GB | proxies 31,7 em repouso (KAM-076 §9, CITADO) | **não medido em carga** | — |
| *worker* de entrada (`worker-canal`) | **sem linha** | 181,1 / 196,6 | **linha em falta** (§6.2) | **256 MiB por processo** (o máximo medido é 200,6 MiB, 78%); e um processo, não o `server.ts` (§6.1) |
| **Total** | **≈ 18,6 GB** | — | **não medido** — mediu-se um segmento, e somar estimativas a medições não é medir | — |

**Extrapolação, e só isso:** se os cinco contentores medidos fossem tudo o que o
*host* P0 corresse, os 957 MiB do p95 da rampa seriam 2,9% de 32 GiB. Não são
tudo: o número diz apenas que **o segmento de entrada não é o que decide o
tamanho do *host***.

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
mediu **196,6 MiB no p95** da rampa e 200,6 no máximo (§4.5), e o `worker-canal` tem **quatro**
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
| Tempo de máquina | três corridas completas de ~21 min, uma do `tests_outbound` de 8 min e quatro curtas de desenvolvimento; electricidade não medida |

**O que este ensaio muda no doc 09, por medir ou por ler:**

| Doc 09 | O que muda | Estado |
|---|---|---|
| §4.2, linha do GWY | confirmada ±20% (p95 de 369 MiB a 800/s nas duas réplicas) | MEDIDO (corrida 3) |
| §4.2 | falta a linha do `worker-canal` (§6.2): 196,6 MiB no p95 da rampa | MEDIDO (corrida 3) |
| §4.2, total ≈ 18,6 GB | continua ESTIMATIVA: o segmento medido não o decide | — |
| §11, BullMQ «~10k jobs/min» | o caminho GWY → fila aceitou ≥ 48 000 *jobs*/min; o limite do segmento é **o consumidor**, ~144 eventos/s com ingestão e até 349/s a drenar, com um *worker* (§4.4) | MEDIDO (corrida 3) |
| §11, AGR «~50 conversas/processo» | continua **NÃO VERIFICADO**: o AGR não corre turnos | — |
| §12, N1/N2 | não medido (§1) | — |
| §14.4 | **sem alteração**: nada do que se mediu muda a infra nem o LLM do Piloto | — |

## 8. O que fica por medir, e de quem é

| O que | Credor |
|---|---|
| AGR em carga, «~50 conversas/processo», LLM com *stub* e com amostra real, N1/N2, *flood* com *handoff* e *budget* por contacto | **KAM-186 (o ticket que liga a porta `grafos` do processo do AGR)** |
| S1 e S2 no *host* P0 (memória ≤ 65% e CPU ≤ 60% de 8 vCPU / 32 GB), Chatwoot, Medusa, LiteLLM e monitorização em carga, e as métricas do ensaio nos painéis do KAM-080 | **KAM-188 (o teste de carga no *host* P0)** |
| O GWY e o BullMQ acima de 800/s — o gerador desta máquina não chega lá (§4.4) | **KAM-188 (o teste de carga no *host* P0)** |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Plataforma/SRE |  |  |  |
| Arquitecto de Plataforma |  |  |  |

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-084): o segmento de entrada medido com os processos de produção — correcção (0 perdidas, 0 a mais e um *job* do AGR por mensagem única em S1, S2, rajada e rampa) e *working set* por contentor; o GWY confirmado ±20% no p95 a 800/s; os limites da Meta, do `tests_outbound` repetido nesta árvore. A corrida 3, sem contenção, dá a latência, a idade na fila, o débito e a rampa: o S1 e o S2 cumprem o critério 2 à escala desta máquina, a rajada drena à medida que chega, e o primeiro recurso saturado do segmento é o *worker* de entrada, entre 200 e 400 eventos/s. O AGR, o LLM, a degradação e o *flood* ficam **não medidos**, porque o AGR não corre turnos. Três achados com evidência (§6.1 a §6.3). | Equipa KAMBÁ |
