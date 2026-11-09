# Runbooks operacionais — índice, modelo único e ligação aos alertas

| Campo | Valor |
|---|---|
| Ticket | **KAM-083** — Runbooks operacionais (`specs/EPIC-08_Topologia_Operacao.md`) |
| Versão | 1.0 |
| Fontes | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §9.2 (alertas), §12 (degradação N0–N6), §13 (os dez runbooks), §16 (*on-call*) |
| Ensaios | [`folha-de-ensaio.md`](folha-de-ensaio.md) — o roteiro de cada ensaio, a folha de tempos e o calendário do *game day* |
| Evidência | [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) |
| Estado | **Proposta.** Os dez procedimentos estão escritos; **nenhum foi ensaiado** e nenhum texto às PMEs está aprovado. Ambos são de pessoas, não deste repositório |

> **O que este índice garante e o que não garante.** Garante que cada runbook segue
> o mesmo modelo, que cada comando diz se foi corrido e contra o quê, e que a
> ligação alerta ↔ runbook está medida nos dois sentidos (§5). **Não garante que
> um runbook funciona** — isso só um ensaio por outra pessoa o diz, e o
> critério 2 do bloco exige-o antes de fechar.

---

## 1. Os runbooks

| ID | Ficheiro | Cenário | Severidade | Activado por | Nível (§12) |
|---|---|---|---|---|---|
| RB-K01 | [`RB-K01-meta-em-baixo.md`](RB-K01-meta-em-baixo.md) | A Meta não aceita envios, ou a ingestão parou | P1 | `ingress_parado`, `alvo_em_baixo`; manual | N3, N6 |
| RB-K02 | [`RB-K02-facilitador-em-baixo.md`](RB-K02-facilitador-em-baixo.md) | O facilitador de pagamentos falha ou cala-se | P1 | **manual** (as regras estão por escrever) | N4 |
| RB-K03 | [`RB-K03-llm-em-baixo-ou-sem-budget.md`](RB-K03-llm-em-baixo-ou-sem-budget.md) | LLM lento, em baixo ou sem *budget* | P2, P3 | `fila_de_entrada_a_crescer`, `fila_do_agente_a_crescer`, `latencia_de_resposta_alta`, `llm_sem_budget`; manual | N1, N2 |
| RB-K04 | [`RB-K04-quality-rating-vermelho.md`](RB-K04-quality-rating-vermelho.md) | A Meta baixou a qualidade do número ou de um *template* | P1, P3 | **manual** | — |
| RB-K05 | [`RB-K05-free-tier-esgotado.md`](RB-K05-free-tier-esgotado.md) | As 1.000 *service messages* grátis do mês aproximam-se do fim | P2, P3 | **manual** | — |
| RB-K06 | [`RB-K06-token-ou-ligacao-invalidados.md`](RB-K06-token-ou-ligacao-invalidados.md) | `account_update` de desligação, ou token inválido | P2 | **manual** | N3 |
| RB-K07 | [`RB-K07-rotacao-de-segredos.md`](RB-K07-rotacao-de-segredos.md) | Rotação de um segredo, planeada ou em incidente | P3 (P1 em incidente) | **manual** (calendário do inventário) | — |
| RB-K08 | [`RB-K08-base-de-dados-e-restauro.md`](RB-K08-base-de-dados-e-restauro.md) | BD indisponível ou corrompida; restauro PITR | P1, P2 | **manual** (as regras estão por escrever) | N5 |
| RB-K09 | [`RB-K09-flood-e-denial-of-wallet.md`](RB-K09-flood-e-denial-of-wallet.md) | Pico de um contacto ou IP; custo de LLM anómalo | P3 → P1 | `llm_sem_budget` (via RB-K03); manual | N2 |
| RB-K10 | [`RB-K10-incidente-de-seguranca.md`](RB-K10-incidente-de-seguranca.md) | Incidente de segurança | P1 | **manual**, por desenho | — |

Há três runbooks que não pertencem à lista fechada do §13 e que alertas reais
apontam: [`degradacao-do-agr.md`](degradacao-do-agr.md) (KAM-037),
[`orcamento-de-erro.md`](orcamento-de-erro.md) (KAM-082) e os dois procedimentos
sem alerta [`rotacao-de-chaves-de-llm.md`](rotacao-de-chaves-de-llm.md) e
[`simulacro-de-dr.md`](simulacro-de-dr.md), mais o
[`../../ops/runbooks/secrets-export.md`](../../ops/runbooks/secrets-export.md)
(KAM-010). **Não foram reescritos aqui:** o bloco do KAM-083 pede os dez do §13, e
estes têm dono próprio. Entram nas duas listas do §5 porque a regra do §9.2 vale
para eles também.

---

## 2. Onde vivem, e porque não é onde o bloco diz

O critério 1 do bloco escreve `ops/runbooks/RB-K01..RB-K10.md`. Os dez vivem em
**`docs/runbooks/`**, onde o KAM-080 os criou, e mudá-los de pasta não é uma
decisão de redacção:

- o `runbook_url` de cada regra de alerta aponta para
  `…/blob/main/docs/runbooks/<ficheiro>` — mudar a pasta é editar as regras de
  alerta, que são do fundador;
- o `tools/obs_lint` resolve esse URL contra `docs/runbooks/` (`RUNBOOKS` em
  `tools/obs_lint/lint.py`) e tem um ensaio que exige um ficheiro por número
  `RB-K01`…`RB-K10` nessa pasta; o `tools/backup_lint` procura o RB-K08 no mesmo
  sítio. Mudar a pasta é mudar o critério de dois *linters* de portão.

A leitura fica escrita, e a decisão devolvida a quem escreveu o critério: **ou o
critério passa a dizer `docs/runbooks/`, ou a mudança de pasta faz-se num ticket
que possa tocar nas regras e nos *linters*.** O `ops/runbooks/` continua a ter o
`secrets-export.md`, que é anterior aos dois.

---

## 3. O modelo único

Todos os dez seguem esta ordem de secções. O cabeçalho é uma tabela de campos, e
os campos são os que o critério 1 enumera.

| Campo do cabeçalho | O que leva |
|---|---|
| ID, Versão | O número do §13 e a versão do documento (igual à última linha do controlo de versões) |
| Cenário | Uma frase |
| Severidade | A do §9.2; se houver duas, a condição de cada uma |
| Alertas que o activam | O nome da regra em `infra/compose/prometheus/regras/`, ou **nenhum**, com a razão e o credor da regra que falta |
| Gatilho manual | Quem pode abrir este runbook sem alerta, e a partir de quê |
| Nível de degradação | O nível N0–N6 do §12 em que o sistema fica |
| Dono | Um **papel** do doc 09 §16, nunca uma pessoa |
| Última revisão | Data e ticket |
| Último ensaio | Data, tipo e quem — ou **nunca**, com o roteiro e o credor |

| Secção | O que leva |
|---|---|
| 0. Antes de começar | O que **hoje** não funciona e muda o procedimento. Lido primeiro, porque é o que faz um passo certo falhar |
| 1. Cenário e gatilho | A condição exacta e o que a distingue dos runbooks vizinhos |
| 2. Diagnóstico | Consultas e comandos exactos, por ordem, cada um com a marca do §4 |
| 3. Mitigação | Passos numerados. Cada passo diz quem o faz e o que se confirma antes do seguinte |
| 4. Critério de recuperação | Condições verificáveis, cada uma com o comando que a verifica |
| 5. Escalamento | Primário → secundário (15 min) → arquitecto (doc 09 §16), e quem de fora |
| 6. Comunicação | Interna; e, para K01, K02, K04, K05 e K06, o texto à PME em português de Angola, marcado **proposta por aprovar** |
| 7. Factos de terceiros | Cada facto sobre Meta, facilitador ou provedor com estado e fonte |
| Controlo de versões | Uma linha por alteração |

---

## 4. Convenções

**Cada comando leva uma marca, e só uma:**

- **`verificado`** — foi corrido, diz-se contra quê e quando (por exemplo, «contra
  o Prometheus v3.7.3 do compose, com as regras do repositório, a 2026-11-09»);
- **`não verificado`** — não foi corrido, e diz-se porquê. A razão mais comum é a
  de todo o repositório: **não há produção**, e um comando que só faz sentido
  contra o sistema real não se verifica numa máquina de desenvolvimento.

Um comando sem marca é defeito do runbook. Um comando `não verificado` não é um
comando errado — é um comando cujo erro ainda ninguém viu.

**Os comandos são para o *host* de produção, a partir da raiz do repositório**,
com o compose de produção (`name: kamba-prod`). Em *staging* troca-se o ficheiro
por `infra/compose/docker-compose.staging.yml`.

**Segredos, pessoas e contactos.** Um segredo cita-se pelo **nome da entrada** em
[`../../ops/secrets-inventory.yaml`](../../ops/secrets-inventory.yaml), nunca pelo
valor. Uma pessoa cita-se pelo **papel** (doc 09 §16, `docs/seguranca/resposta_incidentes.md`
§3), e um contacto externo pelo **canal** (por exemplo, «*Direct Support* da Meta,
pelo Business Manager»). **O repositório é público**: números, endereços e nomes
vivem fora dele, num sítio com controlo de acesso.

**Factos de terceiros** levam o estado da escala do conjunto (**CONFIRMADO**,
**INDÍCIO**, **NÃO VERIFICADO**) e a fonte, herdados da fonte e não promovidos.

---

## 5. Alertas ↔ runbooks: as duas listas

A regra do doc 09 §9.2 é «alerta sem runbook é removido». Medida nos dois
sentidos a 2026-11-09 sobre as regras de `infra/compose/prometheus/regras/`
(`kamba.yml`, `kamba-slo.yml`, `kamba-manutencao.yml`) e as entradas
`regras_por_escrever` de [`../../ops/metricas/catalogo.yaml`](../../ops/metricas/catalogo.yaml).
O comando e a saída estão em [`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §3.

**Nenhum alerta foi removido nem alterado aqui.** Mudar o que dispara, ou para
onde aponta, é do fundador; o que se entrega é a medição.

### 5.1 As dez regras que existem, e para onde apontam

| Regra | Sev. | Aponta para | O runbook fala dela? | Nota |
|---|---|---|---|---|
| `ingress_parado` | P1 | RB-K01 | sim | — |
| `alvo_em_baixo` | P1 | RB-K01 | sim, **e encaminha** | `up == 0` dispara por **qualquer** alvo — o AGR e o COM incluídos —, e só o do `gwy` é ingestão. O RB-K01 §1 encaminha os outros |
| `fila_de_entrada_a_crescer` | P2 | RB-K03 | sim, **e encaminha** | A fila de entrada a crescer é, hoje, quase sempre falta de consumidor (KAM-187) e não o LLM |
| `fila_do_agente_a_crescer` | P2 | RB-K03 | sim | — |
| `latencia_de_resposta_alta` | P2 | RB-K03 | sim | — |
| `llm_sem_budget` | P3 | RB-K03 | sim | O RB-K09 é o destino quando o consumo não se explica; está no **comentário** da regra, não na anotação |
| `degradacao_acima_do_limiar` | P2 | `degradacao-do-agr.md` | sim | — |
| `disjuntor_do_llm_aberto` | P2 | `degradacao-do-agr.md` | sim | — |
| `orcamento_de_erro_burn_rapido` | P2 | `orcamento-de-erro.md` | sim | — |
| `orcamento_de_erro_burn_lento` | P3 | `orcamento-de-erro.md` | sim | — |

### 5.2 Lista A — alertas sem runbook

**Entre as regras escritas: nenhuma.** As dez têm `runbook_url`, e o
`tools/obs_lint` exige que o ficheiro exista.

**Entre os alertas que o §9.2 pede e não estão escritos: um.** A linha
«Memória > 80% sustentada» (P3) do §9.2 tem «Escalar» na coluna do runbook, e
não um RB-K. Não tem regra (não há *exporter* de contentores) nem runbook; o
catálogo já a regista com o credor «quem governa o §9.2». **Credor: o fundador**
— a resposta é um runbook novo fora da lista fechada do §13, ou a remoção da
linha.

E **dois encaminhamentos que estão certos na forma e tortos no efeito**, na
tabela 5.1: o `alvo_em_baixo` e o `fila_de_entrada_a_crescer` apontam para
runbooks cujo cenário não é o seu caso mais provável. Os dois runbooks encaminham
por escrito; corrigir o `runbook_url` é editar a regra, e fica com o fundador.

### 5.3 Lista B — runbooks sem alerta

Sete dos dez RB-K não têm regra nenhuma a apontar para eles. Cada um declara o
**gatilho manual** no cabeçalho, que é o que o critério 3 aceita como
alternativa.

| Runbook | Porque não tem alerta | Regra que falta, e credor |
|---|---|---|
| RB-K02 | As séries existem e ninguém as serve ou as raspa | quatro: DLQ de `payment.*`, callbacks (HMAC > 3/h ou pagamento por reconhecer), anomalia de pagamento ≥ 3, órfão > 24 h — credores KAM-080 e o ticket que ligar o módulo `hnd` |
| RB-K04 | `channel_quality` sem serviço que a sirva | *quality rating* — o ticket que ligar o módulo `qualidade` |
| RB-K05 | `meta_free_tier_used_ratio` sem serviço | *free tier* — KAM-023 |
| RB-K06 | `channel_disconnected_total` sem serviço | `account_update` — o ticket que ligar o módulo `coexistencia` |
| RB-K07 | nada publica a idade dos segredos | segredo a expirar — KAM-072 |
| RB-K08 | o pgBackRest não corre em compose nenhum (D1) | WAL e restauro mensal — KAM-079, KAM-071/KAM-078, D1/KAM-105 |
| RB-K10 | **por desenho**: um incidente de segurança não se detecta por limiar | nenhuma |

O **RB-K09** fica entre as duas listas: nenhuma regra aponta para ele, e o
`llm_sem_budget` nomeia-o num comentário da regra. O runbook declara os dois
caminhos (a partir do RB-K03, e manual).

E fora da lista do §13, três procedimentos sem alerta e sem pretensão de o ter:
`rotacao-de-chaves-de-llm.md`, `simulacro-de-dr.md` e
`../../ops/runbooks/secrets-export.md` — são calendário, não incidente.

### 5.4 A verificação em CI que o critério 3 pede

O sentido **alerta → runbook existente** já é verificado em CI pelo
`tools/obs_lint` (regras `alerta_sem_runbook` e `runbook_inexistente`, no
*gate* 4). O sentido **runbook → alerta ou gatilho manual** não é verificado por
máquina nenhuma: as listas acima foram medidas, não impostas. **Não se acrescentou
a regra ao `obs_lint` aqui**, porque acrescentar o que um *linter* de portão
recusa é mudar o critério do portão. Credor: **o fundador**, com a medição feita.

---

## 6. O estado do sistema que todos os runbooks herdam

Lê-se uma vez aqui, e cada runbook repete na secção 0 só o que lhe muda o
procedimento.

| Facto | Consequência para quem opera | Fonte |
|---|---|---|
| **Não há produção.** O compose de produção corre em `KAMBA_DATA_CLASS=synthetic` e não há *host* (D1/KAM-105) | Nenhum comando contra produção foi corrido | `docs/observabilidade.md`, `infra/backup/cobertura.yaml` |
| **O Alertmanager não notifica ninguém.** Os três `receivers` não têm notificador; o canal de alertas não está escolhido | Um alerta vê-se no Alertmanager e não chega a um telemóvel. Hoje, quem está de serviço tem de **ir ver** | [`../../ops/on-call.md`](../../ops/on-call.md) §3, KAM-069 |
| **Nenhum consumidor lê a `wa-inbound` em produção** | O GWY aceita e enfileira; nada processa. Uma fila de entrada a crescer é isto antes de ser outra coisa | `specs/EPIC-08` bloco KAM-187 |
| **O AGR responde 503 a todos os turnos** (a porta `grafos` não está ligada) | Todo o turno do Vendedor falha e repete até `failed`. Não é o LLM | `specs/EPIC-03` bloco KAM-186 |
| **Não há escala de *on-call*** com pessoas | «Escalar ao secundário» não tem destinatário | `ops/on-call.md`, credor o fundador |
| **Não há sonda sintética externa** | A metade «sonda falha 2×» do `ingress_parado` não existe | `docs/observabilidade.md`, D1/KAM-105 |

---

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Criado pelo **KAM-083**: índice dos dez runbooks, o modelo único, as convenções de marca dos comandos, as duas listas alerta ↔ runbook medidas, e o estado do sistema que todos herdam | KAM-083 |
