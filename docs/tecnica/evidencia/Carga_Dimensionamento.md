# Carga e dimensionamento — o segmento de entrada medido, e o resto por medir

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Evidência — ensaio de carga e validação do dimensionamento do perfil P0 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Estado | **Parcial.** O segmento de entrada está medido, com os limites do compose de produção; o AGR, o LLM, o Chatwoot, o Medusa e o *host* P0 não estão |
| Fonte | [`../09_Topologia_Operacao_Escala.md`](../09_Topologia_Operacao_Escala.md) §1.4, §4, §11, §12, §14; [`E1_Meta_WhatsApp.md`](E1_Meta_WhatsApp.md) §5; o bloco KAM-084 em [`../../../specs/EPIC-08_Topologia_Operacao.md`](../../../specs/EPIC-08_Topologia_Operacao.md) |
| Dono | Plataforma/SRE |
| Ticket | KAM-084 (EPIC-08) |
| Classificação | Documento de Referência — Interno |
| Instrumento | [`db/tests_dimensionamento/`](../../../db/tests_dimensionamento/test_cenarios.py) — `python db/carga.py` |

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
   durante as corridas 1 e 2, e o KAM-083 durante a 6 (§4.1). Cada
   cenário regista os contentores que **não** eram do ensaio
   (`outros_contentores`) e a CPU da VM inteira (`anfitriao`, lida do
   `/proc/stat`), para que a contenção fique medida e não suposta.

## 3. O instrumento

```bash
python db/carga.py
# KAMBA_CARGA_RELATORIO=<caminho.json> guarda o relatório; sem ele, vai para a pasta temporária
# KAMBA_CARGA_CENARIOS=s1,rajada corre só esses; os outros saltam, e o código de saída é 1
```

**É um ponto de entrada próprio, e não uma suite do `db/gate_bd.py`.** O `SUITES`
de lá é a lista do que o CI corre, e um ensaio (`db/tests/test_mutacoes.py`) exige
que cada nome dela esteja num alvo do `Makefile`; o ensaio de carga é meia hora de
relógio e uma medição, e pô-lo num *gate* é decisão do fundador. O `db/carga.py`
reutiliza do `gate_bd.py` o arranque e a limpeza do PostgreSQL e do Valkey e corre
a *suite* com as regras de um *gate* — um teste saltado é uma falha. As corridas 1
a 8 deste documento correram pelo `gate_bd.py`, com a *suite* declarada no
`SUITES`; o que mudou foi só a porta de entrada.

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
| A jusante | o conjunto de `jobId` na `agr-inbound` (`LRANGE … wait`) contra o que o plano dá, `sha256(tenant:wamid)` — **por identidade**, e a contagem só como terceira asserção | os *jobs* do AGR acumulam-se sem consumidor (§1), e é por isso que se podem conferir um a um |
| Memória | `memory.current − inactive_file` do cgroup v2 de cada contentor, lido com `docker exec … cat` a cada 2 s | é o *working set* do `kubelet`; ver abaixo |
| CPU | `usage_usec` do `cpu.stat`, em núcleos, dividido pelo tempo do **`/proc/uptime` da VM lido no mesmo `cat`** | o `docker exec` leva de 100 ms a segundos, e com o relógio de quem o chama o divisor ficava errado pela diferença entre dois `exec` — foram os «6,6 núcleos» comuns a quatro contentores na corrida 2 (achado da revisão adversarial) |
| CPU e memória da VM | `/proc/stat` e `/proc/meminfo` lidos de dentro do contentor do Valkey | não têm *namespace*: dão a máquina inteira, o ensaio **e** o resto |
| Débito do *worker* | eventos por segundo pelo `recebido_at`; o máximo de 10 s consecutivos | é o que a fila consegue drenar |
| Duplicados da rajada | os `msg_id` dos `entrada_duplicado` do registo do *worker* (`m_` + SHA-256 da `event_key`, o `idOpaco`) contra os das repetidas do plano | por identidade: uma repetida em falta e outra a mais não se anulam |

**O *working set* é a definição do doc 09 §1.4**, «memória residente típica em
carga, distinta da reservada». A reservada é o `mem_limit`; a residente é o que o
cgroup tem carregado **menos** a *page cache* que o kernel pode largar sem custo
(`inactive_file`). A conta está num sítio que um teste lê —
`db/tests_dimensionamento/test_medicao.py::TestWorkingSet`, que afirma que o
número não é o `memory.current` (que conta a cache) nem o `anon` (que esquece a
cache activa). Isto é o «Testes Requeridos» do bloco, à letra.

**O custo da medição não está separado.** Em repouso, cada contentor mostra
~0,03–0,06 núcleo, e isso inclui o trabalho ocioso do serviço **e** o `cat` que o
`docker exec` corre dentro do cgroup a cada 2 s; não se mediu um sem o outro (um
intervalo de 2 s contra um de 10 s separava-os). Os números de CPU deste documento
incluem os dois, o que é o lado pessimista.

**Os contentores correm com os limites do compose de produção**: o `mem_limit` e
o `cpus` de `gwy` (nas duas réplicas), `worker-canal` (no *worker* de entrada),
`postgres` e `queue`, lidos do `infra/compose/docker-compose.prod.yml`. A corrida
3 correu **sem** eles — o *worker* chegou a 0,89 núcleo, e o compose dá-lhe 0,5 —,
e foi a revisão adversarial que o apontou; os números de CPU, de débito e da rampa
deste documento são da corrida 5, que os tem.

**Mas na corrida 5 a memória entrou tarde, e isso mudou um resultado.** Os limites
foram postos com `docker update` **depois** do arranque, e o V8 dimensiona o *heap*
pela memória que vê ao arrancar. **Medido** com a imagem do ensaio:
`v8.getHeapStatistics().heap_size_limit` dá **2 240 MiB** num contentor que arranca
sem limite e **259 MiB** num que arranca com `--memory 256m`. Em produção o compose
põe o `mem_limit` antes do arranque. Desde a ponta `a58f4155` os três processos
Node arrancam com os limites no `docker run` (`node.lancar(limites=…)`), e o
`docker update` ficou só para o PostgreSQL e o Valkey, que não dimensionam memória
pelo cgroup. A consequência para a corrida 5 está no §6.6.

**A ferramenta de carga é a biblioteca padrão do Python** (`http.client`,
`threading`), e não o k6 nem o Locust que o bloco propõe: não acrescenta
dependência nenhuma, e por isso não há licença a registar no SBOM de
ferramentas. O preço é um tecto no gerador, que o ensaio mede (§4.4). **A
assinatura dos corpos é a terceira cópia** da mesma função de HMAC em Python (as
outras duas são do `tests_entrada` e do `tests_entrada_carga`); fica, pela
convenção do KAM-013 de cada *suite* assinar sem importar o módulo testado, e a
revisão adversarial registou-a como código a mais aceite.

### 3.1 O perfil, e a leitura que se fez dele

O doc 09 §14.1 dá 10 PMEs × 300 conversas × 8 turnos = **24 000** mensagens de
cliente por mês e ≈ 28 800 do bot. Cada mensagem do bot dá três estados (`sent`,
`delivered`, `read`): ~**110 000** *webhooks* por mês. Em 22 dias de 10 horas
úteis, isso é **0,14 *webhooks*/s** em média.

| Cenário | Ritmo | Canais | Duração | Leitura |
|---|---|---|---|---|
| **S1** — pico do Piloto | **5 /s** | 10 | 300 s | *proposta*: ~36× a média das horas úteis. O factor de hora de ponta é uma hipótese a medir com tráfego real (bloco do ticket), e escolheu-se pessimista |
| **S2** — ×10 | **50 /s** | 100 | 300 s | o S1 ×10, como o critério pede |
| **Rajada** | **100 /s**, mais 10% repetidos | 10 | ~210 s | 1 h de *backlog* do S1 (18 000 *webhooks*) reentregue a 20×; 1 800 corpos reenviados 30 s depois — **900 com os mesmos bytes** (que o GWY reconhece pelo `jobId = sha256(corpo)`) e **900 com o mesmo JSON e outros bytes** (que passam o GWY e só a `UNIQUE (kind, event_key)` da base apanha) |
| **Rampa** | 100 → 200 → 400 → 800 → 1 200 /s, 45 s cada | 100 | até falhar | degraus contíguos, sem drenar; pára no primeiro que falhe o critério 2 ou em que o gerador não imponha a taxa |

A mistura é **1 mensagem de cliente para 3 estados**, a do `E1` §5 e a do
KAM-013. O doc 09 dá 1:3,6 (28 800 respostas para 24 000 mensagens): este perfil
tem 16,7% menos estados do que o doc 09, e fica dito.

## 4. Resultados

### 4.1 As oito corridas, e o que cada uma vale

| Corrida | Quando (UTC) | Vale para | Porque |
|---|---|---|---|
| **1** | 2026-11-08 19:13–19:34 | **nada a jusante do CHR** | o CHR **falhou todas as mensagens**: primeiro com `SemChaveActualError` (não havia versão actual em `platform.hmac_key_versions`) e, corrigido isso numa corrida curta, com `chr_estado_recusou` / `estado_pendente` (os tenants nascem `onboarding`). As duas correcções estão na semente (§6.4) |
| **2** | 2026-11-08 20:15–20:34 | **só correcção** | o KAM-085 corria na mesma VM (o `kam085-primario` a 2,0–3,2 núcleos e 2,0 GiB), o gerador chegou a 33 s de atraso, e os «6,6 núcleos» que os contentores mostraram eram em parte o defeito de relógio do amostrador que a revisão adversarial apontou (§3, linha «CPU») |
| **3** | 2026-11-09 08:05–08:26 | correcção, ack, idade na fila e *working set* | VM livre, mas **sem os limites do compose** e com o defeito de relógio na CPU por contentor. A CPU por contentor e a rampa desta corrida **não se citam**: a 5 substitui-as |
| **4** | 2026-11-09 08:53–11:15 | S1, S2 e rampa, como **segunda corrida** da 5 | com os limites. **A rajada está contaminada**: o Windows entrou em espera moderna às 09:05:01 e saiu às 11:07:40 (registo `Microsoft-Windows-Kernel-Power`, eventos 506 e 507), e um pedido ficou 7 359 s parado. A rampa correu já depois do regresso |
| **5** | **2026-11-09 11:16–11:50** | **tudo o que este documento cita como medido** | VM livre, **`outros_contentores` vazio nos cinco cenários**, limites do compose aplicados, o relógio da CPU corrigido, e a máquina mantida acordada. À ponta `1c1b1c04`, com a `publico/main` `6583930f` integrada. `Ran 41 tests`: o S1, o S2 e a rajada passaram; **a rampa falhou**, e a razão é um achado (§4.4 e §6.6) |
| **6** | 2026-11-09 12:02–12:10 | **nada** | só a rampa, para confirmar a morte do *worker* da corrida 5; o KAM-083 tinha quatro contentores na mesma VM (`kam083-am`, `-pg`, `-prom`, `-q`) e a CPU da VM estava a 47% no p95 já a 100/s. **Não reproduziu a morte**, e uma corrida contaminada não a desmente |
| **7** | 2026-11-09 13:22–13:27 | **nada** | só a rajada, já com os processos Node a arrancar com os limites: o GWY não respondeu nos 180 s de arranque, com o KAM-187 e o KAM-083 no mesmo Docker. Não chegou a enviar um pedido; a espera de arranque desta *suite* passou a 600 s |
| **8** | 2026-11-09 13:52–13:56 | **a correcção da rajada** | só a rajada, depois da revisão adversarial: repetidas escolhidas por tipo (N1), duplicados conferidos por identidade (N2) e processos Node com os limites no arranque (N3). **Com contenção** — o KAM-083 e outros contentores na VM, a CPU dela a 55% no p95 —, pelo que **os tempos desta corrida não se citam**; a correcção vale com contenção. `OK (skipped=4)` |

Salvo indicação, **os números de baixo são da corrida 5**; a correcção da rajada é da **8**.

### 4.2 Correcção

| Cenário | Pedidos | Eventos únicos | Na base | Em falta | A mais | *Jobs* do AGR / mensagens únicas, por identidade | Drenagem depois do último envio |
|---|---|---|---|---|---|---|---|
| S1 (5/s, 300 s) | 1 500 | 1 500 | 1 500 | **0** | **0** | **375 / 375**, 0 em falta, 0 a mais | 0,0 s |
| S2 (50/s, 300 s) | 15 000 | 15 000 | 15 000 | **0** | **0** | **3 750 / 3 750**, 0 em falta, 0 a mais | 0,0 s |
| Rajada (100/s + 10% repetidos), corrida 8 | 19 800 | 18 000 | 18 000 | **0** | **0** | **4 500 / 4 500**, 0 em falta, 0 a mais | não se cita (contenção); na corrida 5, **0,0 s**, com a fila a nunca passar de **6** *jobs* |
| Rampa (100 → 1 200/s) | 121 500 | 121 500 | 96 283 | **25 217** | 0 | 24 071 / 30 375 | **não drenou** em 900 s — §4.4 |

**Os *jobs* do AGR comparam-se por identidade**: o conjunto de `jobId` na
`agr-inbound` contra o que o plano dá (`sha256(tenant:wamid)`, a conta do
`chr/invocacao.ts`). Com a contagem, uma troca — o *job* de uma mensagem em falta
e o de outra em dobro — passava; a revisão adversarial apontou-o.

**A rajada mede os dois níveis de deduplicação, e por identidade.** 18 000
*webhooks* — uma hora do S1 — a 20×, e **1 800 corpos repetidos 30 s depois**,
cada grupo com **metade mensagens e metade estados** (corrida 8):

| Repetidos | Quem os apanha | Medido, pelo `msg_id` de cada um no registo do *worker* |
|---|---|---|
| **900 com os mesmos bytes** (450 mensagens, 450 estados) | o GWY, pelo `jobId = sha256(corpo)` do `webhook.ts`, enquanto o *job* estiver na retenção da fila | **nenhum** chegou ao *worker* como `entrada_duplicado` |
| **900 com o mesmo JSON e outros bytes** (450 mensagens, 450 estados) | passam o GWY; o *worker* regista-os e a `UNIQUE (kind, event_key)` de `inbound_events` reconhece-os | **os 900** como `entrada_duplicado`, **as 450 mensagens** entre eles, e **nenhum** *job* do AGR a mais — o CHR não encaminha o que a base já tinha |

**A primeira versão disto media uma coisa que não dizia.** Repetia um em cada dez
pedidos e repartia-os por posição, e como o plano vem em blocos de mensagem,
estado, estado, estado, os 900 «com outros bytes» saíram **todos estados
`delivered`** e os 900 «com os mesmos bytes» **todos mensagens**: nenhuma mensagem
passou pelo segundo nível, que é o único que decide se o AGR recebe um *job* a
mais. A revisão adversarial reproduziu-o (N1). Hoje escolhe-se por tipo, com uma
amostra de semente fixa — um passo regular caía sempre no mesmo estado, e um
ensaio (`test_as_repetidas_escolhem_se_por_tipo`) apanhou-o —, e a corrida 8 diz
**450 mensagens pelo segundo nível, 450 encontradas, 0 *jobs* do AGR a mais**.

**Os duplicados conferem-se por identidade, e o excesso está preso à causa
medida** (`medicao.duplicados_explicados`): cada repetida com outros bytes tem de
aparecer como `entrada_duplicado` com o seu `msg_id` (o `idOpaco` do *logger*,
`m_` + SHA-256 da `event_key`, com o valor fixado pelo Node num ensaio), nenhuma das
com os mesmos bytes pode aparecer, e o que sobrar é excesso, com o tecto de
`entrada_falhou` × 1 evento por corpo. Na corrida 8: **900 vistos, 900 esperados,
0 em falta, 0 que passaram o GWY, 0 falhas, excesso 0**. **Os limites do tecto,
ditos** (N4): o `entrada_falhou` conta também erros do *worker* sem *job*, o que só
o alarga; um *job* que perca a tranca e se repita sem `entrada_falhou` dá excesso sem
falha e fica vermelho — um falso vermelho possível, não visto; e o tecto nasceu da
corrida 4 (901 para 900 com dois `entrada_falhou`), cuja rajada está contaminada
pela espera do Windows, pelo que o mecanismo é **INDÍCIO**. **Mutações de controlo**
(`test_medicao.TestDuplicados`): o dobro dos repetidos, uma igual que passou o GWY,
900 `msg_id` errados com a contagem certa, e o ensaio a ligar as repetidas erradas
(as iguais como esperadas) — **todas vermelhas**; e sem o tecto
(`0 <= excesso <= tecto` trocado por `0 <= excesso`) o dobro dos repetidos passava.

### 4.3 Ack, idade na fila e CPU — S1, S2 e rajada

| | S1 (5/s) | S2 (50/s) | Rajada (~94/s com as repetidas) |
|---|---|---|---|
| Respostas | 1 500 × 200 | 15 000 × 200 | 19 800 × 200 |
| Ack no cliente p50 / p99 / p99,9 / máx | 4,7 / 10,0 / 27,5 / 43,6 ms | 2,8 / 12,5 / 42,6 / 114,5 ms | 2,2 / 15,4 / 31,9 / 73,7 ms |
| **Ack no GWY** (`latency_ms`) p99 / máx | 4 / 16 ms | 4 / 31 ms | 5 / 35 ms |
| **Ack < 500 ms** (critério: ≥ 99,9%) | **100%** | **100%** | **100%** |
| **Idade na fila** p99 / máximo (critério: < 2 min) | 0,011 / **0,039 s** | 0,012 / **0,064 s** | 0,045 / **0,122 s** |
| Reconexões do gerador (latência contada desde a 1.ª tentativa) | 0 | 9 (`RemoteDisconnected`) | 25 (`RemoteDisconnected`) |
| **CPU da VM inteira** p95 / máx | **6,1 / 8,5%** | **12,9 / 18,8%** | 19,3 / 23,1% |
| Memória usada da VM, p95 | 1 145 MiB (14,7%) | 1 567 MiB (20,1%) | 1 610 MiB (20,7%) |

**À escala desta máquina, o S1 e o S2 cumprem os cinco números do critério 2**:
ack, idade, perdas, CPU ≤ 60% (6,1% e 12,9%) e memória ≤ 65% (14,7% e 20,1% de
7,6 GiB). **Não é a letra do critério**, que fala do *host* de 32 GB com o
conjunto inteiro; dos catorze serviços, só cinco estão aqui (§2). A memória da VM
inclui o Docker Desktop: em repouso, com os cinco contentores, já eram 1 153 MiB.

**A diferença entre o ack do cliente e o do GWY** é o encaminhamento de portas do
Docker Desktop e o gerador: no S2, 12,5 ms contra 4 ms no p99. A corrida 4, com os
mesmos limites, deu o S1 e o S2 com o mesmo resultado (100% abaixo de 500 ms,
idade máxima de 0,09 e 0,13 s).

### 4.4 A rampa, o primeiro recurso saturado e o *worker* que deixou de responder

Degraus contíguos de 45 s, 100 tenants, sem drenar entre degraus, **com os
limites do compose**:

| Degrau | Respostas | Ack no GWY p99 / máx | Ack no cliente p99,9 | Atraso do gerador p99 | Fila no fim | CPU do *worker* p95 (tecto 0,5) | CPU da VM p95 |
|---|---|---|---|---|---|---|---|
| 100/s | 4 500 × 200 | 5 / 48 ms | 31,6 ms | 0,7 ms | **0** | 0,24 | 19,5% |
| 200/s | 9 000 × 200 | 9 / 57 ms | 53,2 ms | 0,7 ms | **0** | 0,39 | 29,8% |
| 400/s | 18 000 × 200 | 17 / 55 ms | 59,5 ms | 0,9 ms | **5 531** | **0,45** | 42,1% |
| 800/s | 36 000 × 200 | 48 / 120 ms | 149,0 ms | 6,3 ms | **33 031** | **0,43** | 55,2% |
| 1 200/s | 54 000 × 200 | 51 / 152 ms | 176,3 ms | 69,2 ms | **80 783** | **0,40** | 61,4% |

**O primeiro recurso saturado do segmento é o *worker* de entrada, por CPU, no
tecto que o compose lhe dá.** A partir de 400/s o *worker* fica colado aos
0,45 núcleo e a fila cresce — o resto dos 0,5 será o *throttling* do cgroup, mas
o `throttled_usec` do `cpu.stat` não se guardou, e é inferência (achado da revisão
adversarial). O
consumo com ingestão desce à medida que a ingestão sobe: **~277 eventos/s** a
400/s, ~185/s a 800/s e ~129/s a 1 200/s (o crescimento da fila descontado da
taxa), porque o PostgreSQL e o Valkey que ele usa estão a servir o GWY ao mesmo
tempo. **Onde a fronteira fica depende da corrida**: a 200/s a fila drenou na
corrida 5 e acumulou 3 261 na corrida 4 (que correu logo a seguir ao regresso da
espera), pelo que o que se pode afirmar é **entre 100 e 400/s, conforme a corrida, com 100/s
folgado nas três corridas com limites**. O S1, a 5/s, está ~40× abaixo.

A primeira versão deste documento dizia «não é CPU, é latência»: mediu-se sem os
limites do compose, com o *worker* a 0,58 núcleo no p95 e sem tecto. Com o tecto
de 0,5, é CPU. A revisão adversarial apontou que a afirmação não tinha medição por
degrau que a sustentasse; agora tem.

**O GWY e o BullMQ chegaram aos 1 200/s sem recusar nada.** Todos os pedidos
deram 200, com o p99 no GWY de 51 ms. O GWY ficou em **0,78 núcleo** por réplica
(tecto 1,0) e o Valkey a **0,99 núcleo no máximo** (tecto 1,0) — **os dois perto
do tecto deles a 1 200/s**, o que é a fronteira seguinte e fica por medir acima
disto. O BullMQ aceitou **~71 400 *jobs*/min durante 45 s** (1 190/s): os «~10k
jobs/min» do doc 09 §11 não são o tecto do BullMQ neste caminho.

**E a fila não drenou.** Com 80 783 *jobs* em espera, o *worker* de entrada
**deixou de responder ~144 s depois do fim do envio**: o registo dele acaba às
11:37:42 a meio de uma sequência de `entrada_registado`, sem erro nenhum, as 379
amostras seguintes do `docker exec` falharam, e o *working set* tinha chegado a
**251,7 MiB, contra o `mem_limit` de 256 MiB**. Ficaram **25 217 eventos por
registar** e 6 304 *jobs* do AGR por criar. **Não é medição do que acontece em
produção**: o `mem_limit` do *worker* entrou por `docker update` depois do
arranque, e com isso o V8 tinha o *heap* dimensionado para 2 240 MiB e não para os
256 do cgroup (§3). Morrer sem linha de erro a 251,7 MiB de 256 é exactamente o que
isso dá. **É um artefacto do ensaio, medido**, e a proposta que a primeira versão
deste documento tirava daqui — dar ao *worker* mais de 256 MiB — **cai**. Se o
*worker* aguenta o mesmo *backlog* com o limite no arranque **não se mediu**: a
rampa não se repetiu, e é do KAM-188.

### 4.5 *Working set*

MiB, p95 por contentor (o máximo entre parênteses). Corrida 5, com os limites do
compose.

| Contentor | Repouso | S1 (5/s) | S2 (50/s) | Rajada (~94/s) | Rampa (até 1 200/s) | `mem_limit` no compose |
|---|---|---|---|---|---|---|
| `gwy` réplica A | 64,2 | 64,9 | 172,3 | 175,5 | 192,2 (192,5) | 256 MiB |
| `gwy` réplica B | 66,2 | 66,4 | 170,9 | 175,2 | 195,5 (195,9) | 256 MiB |
| *worker* de entrada | 65,7 | 71,8 | 170,7 | 177,5 | 236,3 (**251,7**) | 256 MiB (o do `worker-canal`, §6.2) |
| PostgreSQL | 118,6 | 122,3 | 131,6 | 150,5 | 233,2 (240,2) | 5 120 MiB |
| Valkey | 14,9 | 23,5 | 92,2 | 91,3 | 246,5 (301,0) | 768 MiB |
| **Soma dos p95** | **329,6** | **348,9** | **737,7** | **770,0** | **1 103,7** | — |

- **O GWY sobe para ~175 MiB por réplica a partir de 50/s, e chega a 196 a
  1 200/s.** É o *heap* do V8 a crescer com a carga e a não devolver. Na corrida
  6, contaminada, **uma réplica chegou a 254,0 MiB** — partindo do arranque e indo
  directa à rampa, sem os cenários anteriores. É INDÍCIO e não medição, mas diz
  que os 256 MiB por réplica não têm a folga que o p95 da corrida 5 sugere.
- **O *worker* de entrada chega ao tecto, mas com o *heap* do V8 dimensionado para a VM**: o `mem_limit` entrou depois do arranque, e o número não diz o que ele faz com o limite no arranque (§3 e §6.6). Não tem linha no §4.2 (§6.2).
- **O PostgreSQL cresce com os dados** porque corre em `tmpfs` (§2, ponto 3): de
  119 MiB em repouso para 240 MiB depois de ~130 000 eventos escritos (e apagados
  entre cenários, o que não devolve o espaço). Não é comparável com o doc 09.
- **O Valkey é o *backlog***: 301,0 MiB no máximo, com ~80 000 *jobs* de entrada
  e os do AGR que ninguém consome (§1). O `maxmemory` de produção é 600 MB.

A soma dos p95 é um **majorante** (os picos não coincidem) e é a soma de cinco
contentores.

### 4.6 Limites da Meta

O balde por número e o *backoff* do `130429` são do KAM-015, e a suite repetiu-se
**nesta árvore**: `python db/gate_bd.py --suite tests_outbound` → `Ran 10 tests …
OK`. Os dois ensaios que respondem à regra:

- `packages/core-ts/tests/outbound.limites.test.ts` — «**100 envios a contactos
  diferentes nunca passam de 15 em nenhuma janela de 1 s**» e «e drenam em
  >= 6,6 s»;
- `packages/core-ts/tests/outbound.adapter.test.ts` — «**tres 130429 e depois um
  200: 1 entregue, 0 duplicados**», com esperas exponenciais e *jitter* de
  meia-base, e o `Retry-After` a mandar.

**Mas não são o critério 6 à letra**, que pede a medição «com o simulador», e a
revisão adversarial confirmou-o: o primeiro é uma função pura com o relógio por
parâmetro (a docstring dele diz que a parte «medida no servidor falso» vive
noutro sítio), e o segundo usa uma `MetaFalsa` dentro do processo. O único ensaio
que usa o `GraphFalso` (`tests_bd/outbound.bd.test.ts`) não tem cenário de ritmo
nem de `130429`. E «sem martelar» só está provado por mensagem: nada mostra que um
`130429` trava os outros envios do mesmo número. O critério 6 fica **vazio**,
com o KAM-188, que tem o processo de saída a correr.

O tecto é **15 mps por número nos dois modos** (`MPS_POR_MODO`), abaixo dos 20 mps
CONFIRMADOS em coexistência e dos 80 da Cloud API. **Para o dimensionamento é um
tecto de débito**: um número em `cloud_only` envia a 15 mps quando a Meta deixaria
80, e o próprio `limites.ts` o escreve, porque nenhum documento deste repositório
fixa o número do `cloud_only`.

## 5. O §4.2 do doc 09, linha a linha

«Medido» é o p50 / p95 da corrida 5 em MiB, no cenário que a coluna indica. A
coluna do doc 09 é a do **Piloto**, pelo que o veredicto se dá contra o S1 (o
pico do Piloto) e se diz também o que acontece acima. Os veredictos só se dão
sobre o que se mediu.

| Serviço (doc 09 §4.2) | Estimado (Piloto) | Medido p50 / p95 | Veredicto | Proposta de `mem_limit` |
|---|---|---|---|---|
| GWY (2 réplicas) | 0,4 GB | S1: 99,7 / 131,3 · S2: 224,7 / 343,2 · rampa: 386,5 / 387,7 (as duas) | **corrigido para ~0,13 GB no pico do Piloto** (−66% no S1); a partir de 50/s o p95 fica entre −10% e +2% de 0,4 GB, que **confirma a estimativa como tecto** | **não baixar**: o máximo medido é 195,9 MiB por réplica (77% de 256), e a corrida 6, contaminada, chegou a 254,0. Calibra-se no KAM-188 |
| AGR (*workers* Python) | 2 GB | — | **não medido** — o AGR não corre turnos (§1) | — |
| Chatwoot (web + Sidekiq) | 4 GB | — | **não medido** — não corre nesta VM | — |
| Medusa | 2 GB | — | **não medido** — `pendente` no compose | — |
| `onboarding-web` | 0,5 GB | — | **não medido** — fora do segmento | — |
| PostgreSQL 18 | 4 GB | rampa: 232,1 / 233,2 | **não comparável** — `tmpfs` e base quase vazia (§2) | — |
| Redis/Valkey | 0,5 GB | rampa: 212,6 / 246,5 | **não confirmado nem corrigido** — é o *backlog* de um ensaio que satura o consumidor (§4.4), e falta o tráfego dos eventos (EVT) e um consumidor do AGR | — |
| LiteLLM | 1,5 GB | 469,6 em repouso (KAM-076 §9, CITADO) | **não medido em carga** — ninguém chama o LLM (§1) | — |
| Object storage | 0,7 GB | 64,3 em repouso (KAM-076 §9, CITADO) | **não medido em carga** | — |
| Monitorização | 1,5 GB | Prometheus 18,9 em repouso (KAM-076 §9, CITADO) | **não medido em carga** — o ensaio não levanta o Prometheus | — |
| SO, proxy, *exporters* | 1,5 GB | proxies 31,7 em repouso (KAM-076 §9, CITADO) | **não medido em carga** | — |
| *worker* de entrada (`worker-canal`) | **sem linha** | S1: 59,0 / 71,8 · rampa: 197,6 / 236,3 | **linha em falta** (§6.2) | **256 MiB, sem prova de que não chegam**: a morte a 251,7 MiB da corrida 5 é um artefacto do ensaio (§6.6). O valor é do KAM-187, que o põe no compose |
| **Total** | **≈ 18,6 GB** | — | **não medido** — mediu-se um segmento, e somar estimativas a medições não é medir | — |

**Extrapolação, e só isso:** se os cinco contentores medidos fossem tudo o que o
*host* P0 corresse, os 1 104 MiB do p95 da rampa seriam 3,4% de 32 GiB. Não são
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
processo que ele mede **é** o que falta no compose. **Paga-o o KAM-187**, que
põe os consumidores do `worker-canal` no compose de produção.

### 6.2 O §4.2 do doc 09 não tem linha para o `worker-canal`

**Evidência.** As linhas do §4.2 são GWY, AGR, Chatwoot, Medusa,
`onboarding-web`, PostgreSQL, Redis/Valkey, n8n, Langfuse, LiteLLM, *object
storage*, Nominatim, Typebot, monitorização e SO. O *worker* de entrada, sozinho,
mediu **236,3 MiB no p95** da rampa e 251,7 no máximo (§4.5), e o `worker-canal` tem **quatro**
processos (`entrada`, `agr_shim`, `publicador`, `consumidor`). O compose dá ao
contentor 256 MiB — dimensionados para o `server.ts`, que é o único que corre.
**Paga-o o KAM-187**, no seu critério 4: cada consumidor novo entra no orçamento
de memória com a linha que o paga.

### 6.3 O tecto de ritmo por contacto descarta, e o critério pede *handoff*

**Evidência.** O `services/agr/src/kamba_agr/admissao.py` impõe 20 mensagens por
minuto por contacto com «**descarte silencioso**» para o cliente (a sua
*docstring*, «Ritmo por contacto — 20 msgs/min, *descarte silencioso*
(criterio 5)», do KAM-025), e conta-o em
`agr_admitted_rejected_total{motivo="ritmo"}`. O critério de *flood* deste
ticket pede que um contacto a 100 msg/min seja «**limitado e redireccionado a
*handoff***» (RB-K09). As duas leituras não são a mesma coisa: hoje o atacante é
calado, e ninguém é chamado. Não se mediu nada aqui — o AGR não corre turnos —,
mas a divergência é de texto e lê-se sem carga. **Paga-a o KAM-186**, no seu
critério 11 («o ritmo excedido tem um só comportamento»).

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
*keep-alive* do Node fecha ao fim de 5 s parado), numa corrida de 120 s com p50 de
15 ms. Com 8 *threads* houve duas corridas curtas: **zero** reconexões nas duas, e
p50 de 5 ms numa e de **24,8 ms** na outra. As três correram com o KAM-085 na
mesma VM. **O que fica provado é a contagem, e não a causa do p50**: as
reconexões não o explicam sozinhas. O gerador passou a `taxa / 8` *threads*,
conta as reconexões por cenário com a classe da excepção (`reconexoes_por_erro`),
e a latência de um pedido que reconectou conta desde a **primeira** tentativa —
a primeira versão deitava fora o tempo da tentativa falhada, e isso é latência
que o pedido pagou.

### 6.6 O *worker* que deixou de responder na corrida 5 é um artefacto do ensaio

**Evidência.** Na drenagem de 80 783 *jobs*, o *working set* do *worker* chegou a
**251,7 MiB** com o `mem_limit` de 256 MiB, o registo dele acabou às 11:37:42 a
meio de uma sequência de `entrada_registado` sem linha de erro, e as 379 amostras
seguintes falharam por o contentor já não existir. **E a causa é do ensaio**: o
limite entrou por `docker update` depois do arranque, quando o V8 já tinha
dimensionado o *heap* para a VM — 2 240 MiB, contra 259 MiB num contentor que
arranca com `--memory 256m` (medido, §3; achado N3 da revisão adversarial). O ensaio
passou a arrancar os processos Node com os limites. **Se o *worker* aguenta um
*backlog* de 80 000 com o limite no arranque não se mediu**, e é do KAM-188. O que
o provaria é o código de saída do `docker run` (137) e o `oom` do `docker events`,
que o ensaio passou a guardar; o `oom_kill` do `memory.events`, que chegou a
entrar, saiu, porque não se lê de um contentor que o kernel já levou (achado N7).

**O que fica do achado** é o §6.1 visto de outro lado: os consumidores do
`worker-canal` não têm processo nem orçamento no compose, e o KAM-187 é que os
põe lá com o limite que medir.

### 6.7 A retenção do `jobId` do AGR, que o código manda calibrar aqui

O `packages/core-ts/src/chr/fila.ts` fixa `JOBS_GUARDADOS = 10_000` e escreve
«Calibra-se em KAM-084, com o perfil de carga real». **É a retenção da
`agr-inbound`**, que conta mensagens (um quarto dos *webhooks* do perfil): 10 000
mensagens cobrem **~2,2 h** ao ritmo do S1 (1,25 mensagens/s) e **~7 min** ao da
rajada (25/s). A da `wa-inbound` (`MANTER_CONCLUIDOS`, também 10 000) conta
*webhooks* e cobre ~33 min e ~100 s. As duas ficam muito abaixo dos **7 dias** de
reentrega da Meta.

**O que se mediu sobre ela, e o que não.** Nesta montagem a `agr-inbound` não tem
consumidor (§1), pelo que o `removeOnComplete` nunca actua e **a retenção do AGR não
foi exercida**. O que se mediu foi o nível que a substitui quando expira: as
mensagens repetidas com outros bytes da rajada passaram o GWY, chegaram ao
*worker*, a `UNIQUE (kind, event_key)` reconheceu-as, e **nenhuma deu *job* do AGR a
mais** (§4.2). **Proposta: manter os 10 000**, que custam da ordem dos 30 MB de
Valkey; o perfil real e um AGR a consumir, no KAM-188, decidem se vale mais.

## 7. Custo do ensaio, e os itens do doc 09 que mudam

| Rubrica | Custo |
|---|---|
| *Host* temporário | **0 USD** — não houve. O ensaio correu numa estação de trabalho já existente (§2); o clone de 8 vCPU / 32 GB do bloco não se criou |
| LLM real | **0 USD** — não houve chamada nenhuma (§1), e a amostra com LLM real fica **não medida** |
| Serviços pagos e contrapartes | **0 USD** — o servidor Graph falso do KAM-024 responde pela Meta |
| Tempo de máquina | cinco corridas completas de 21 a 35 min (mais as ~2 h da espera do Windows na corrida 4), uma só da rampa, uma do `tests_outbound` de 8 min e quatro curtas de desenvolvimento; electricidade não medida |

**O que este ensaio muda no doc 09, por medir ou por ler:**

| Doc 09 | O que muda | Estado |
|---|---|---|
| §4.2, linha do GWY | **corrigida para ~0,13 GB no pico do Piloto**; os 0,4 GB confirmam-se como tecto a partir de 50/s | MEDIDO (corrida 5) |
| §4.2 | falta a linha do `worker-canal` (§6.2): 236,3 MiB no p95 da rampa; se 256 MiB chegam com o limite no arranque está por medir (§6.6) | MEDIDO (corrida 5) |
| §4.2, total ≈ 18,6 GB | continua ESTIMATIVA: o segmento medido não o decide | — |
| §11, BullMQ «~10k jobs/min» | o BullMQ aceitou ~71 400 *jobs*/min durante 45 s; o limite do segmento é **o consumidor**, por CPU no tecto de 0,5 núcleo do compose, entre 100 e 400 eventos/s conforme a corrida (§4.4) | MEDIDO (corrida 5) |
| §11, AGR «~50 conversas/processo» | continua **NÃO VERIFICADO**: o AGR não corre turnos | — |
| §12, N1/N2 | não medido (§1) | — |
| §14.4 | **sem alteração**: nada do que se mediu muda a infra nem o LLM do Piloto | — |

## 8. O que fica por medir, e de quem é

| O que | Credor |
|---|---|
| AGR em carga, «~50 conversas/processo», LLM com *stub* e com amostra real, N1/N2, *flood* com *handoff* e *budget* por contacto | **KAM-186**, que liga a porta `grafos` do processo do AGR, e **KAM-188**, que os mede no *host* P0 |
| S1 e S2 no *host* P0 (memória ≤ 65% e CPU ≤ 60% de 8 vCPU / 32 GB), Chatwoot, Medusa, LiteLLM e monitorização em carga, e as métricas do ensaio nos painéis do KAM-080 | **KAM-188 (o teste de carga no *host* P0)** |
| O GWY e o Valkey acima de 1 200/s, onde os dois chegam perto do tecto de CPU do compose (§4.4) | **KAM-188 (o teste de carga no *host* P0)** |
| Se o *worker* de entrada aguenta um *backlog* de ~80 000 com o `mem_limit` posto no arranque (§6.6) | **KAM-188**, com o código de saída e o `oom` do Docker que o ensaio já regista, e **KAM-187**, que lhe dá processo e orçamento |
| Os limites da Meta com o simulador, e «sem martelar» entre envios do mesmo número (§4.6) | **KAM-188** |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Plataforma/SRE |  |  |  |
| Arquitecto de Plataforma |  |  |  |

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-084): o segmento de entrada medido com os processos de produção e os limites do compose de produção, em oito corridas, das quais a 5 é a de referência e a 8 a da correcção da rajada. Correcção: 0 perdidas e os *jobs* do AGR iguais às mensagens únicas por identidade no S1, no S2 e na rajada; na rajada, mensagens e estados repetidos pelos dois níveis de deduplicação, conferidos pelo `msg_id`, sem *job* do AGR a mais. O S1 e o S2 cumprem o critério 2 à escala desta máquina; o primeiro recurso saturado é o *worker* de entrada, por CPU no tecto do compose, entre 100 e 400 eventos/s conforme a corrida. O GWY corrigido para ~0,13 GB no pico do Piloto. A morte do *worker* na rampa da corrida 5 é um artefacto do ensaio (o `mem_limit` entrava depois do arranque do V8, medido). O AGR, o LLM, a degradação, o *flood* e os limites da Meta com o simulador ficam **não medidos**, com os credores KAM-186 e KAM-188. Sete achados (§6), três pagos pelo KAM-186 e pelo KAM-187. Revisão adversarial: quinze achados e, na verificação das correcções, mais sete; os confirmados corrigidos. | Equipa KAMBÁ |
