# Observabilidade da KAMBÁ

| Campo | Valor |
|---|---|
| Ticket | KAM-080 |
| Âmbito | Métricas, logs JSON, alertas, painéis e a sua verificação por máquina |
| Fontes | [`tecnica/09_Topologia_Operacao_Escala.md`](tecnica/09_Topologia_Operacao_Escala.md) §9 e §13, [`tecnica/08_Seguranca_Conformidade.md`](tecnica/08_Seguranca_Conformidade.md) §7.3, ADR-010, ADR-018 |
| Estado | **Parcial, e medido.** O que falta tem credor escrito em [`../ops/metricas/catalogo.yaml`](../ops/metricas/catalogo.yaml) |
| Não cobre | SLOs e orçamento de erro (KAM-082), custo por tenant (KAM-081), runbooks executáveis (KAM-083) |

---

## 1. O que existe, numa tabela

| Camada | Onde | Estado |
|---|---|---|
| Logs JSON sem conteúdo | `packages/core-ts/src/logger/`, `libs/py-core/src/kamba_core/logger/` | **Activo desde o KAM-068.** Os cinco serviços instalam o *logger*; o gate 2 recusa quem escreva fora dele e o gate 6 corre o X-11 |
| Métricas | 19 módulos, 115 nomes distintos | **Declaradas 115; alcançáveis em `compose` 51** — ver §2 |
| Exposição | `/metrics` no GWY (3010), no COM (3002) e no AGR (8000) | O AGR nasceu com este ticket |
| Recolha | [`../infra/compose/prometheus/prometheus.yml`](../infra/compose/prometheus/prometheus.yml) | Três alvos, por `dns_sd_configs` |
| Regras de alerta | [`../infra/compose/prometheus/regras/kamba.yml`](../infra/compose/prometheus/regras/kamba.yml) | **8 regras, que cobrem 4 das 12 linhas** do §9.2 — ver §3 |
| Comportamento das regras | [`../infra/compose/prometheus/regras/testes/kamba_test.yml`](../infra/compose/prometheus/regras/testes/kamba_test.yml) | 17 casos, `promtool test rules` |
| Encaminhamento | [`../infra/compose/alertmanager/alertmanager.yml`](../infra/compose/alertmanager/alertmanager.yml) | Por severidade. **Não notifica** — ver §4 |
| Runbooks | `runbooks/RB-K01…RB-K10` | *Stubs*: título, gatilho, severidade. Os executáveis são o KAM-083 |
| Painéis | [`../ops/paineis/`](../ops/paineis/) | Quatro, como código. **O Grafana não corre** — ver §6 |
| Verificação | `tools/obs_lint`, `make obs-lint`, `make obs-promtool` | **Não ligada a nenhum portão** — ver §7 |
| Envio para Loki | — | **Não existe.** Loki é AGPL-3.0 — ver §6 |
| Sonda externa | — | **Não existe.** Não há produção — ver §5 |

---

## 2. Catálogo de métricas

O catálogo legível por máquina é [`../ops/metricas/catalogo.yaml`](../ops/metricas/catalogo.yaml), e é a superfície que o `obs_lint` verifica. Cobre as métricas que as regras e os painéis citam, mais as doze séries que o critério 2 do KAM-080 nomeia — **não** é o inventário das 109.

### 2.1 As contagens, com o instrumento que as produz

As contagens têm comando, e o comando está no repositório — `tools/obs_lint/contar_metricas.py`:

```text
$ python tools/obs_lint/contar_metricas.py --detalhe
...
contar_metricas: 19 modulos de metricas, 113 nomes distintos (piso: ver o predicado 2 na docstring)
```

**O predicado está escrito antes da contagem**, na *docstring* do próprio ficheiro, porque uma contagem feita antes de se definir o que conta produz números errados com a mesma firmeza com que produziria os certos. Um predicado mais largo dá outro número — e está certo para esse predicado.

A reconciliação de 113 para **115**: o módulo `services/com/src/metricas.ts` conta **0** pelo predicado, porque os seus dois nomes são declarados em `services/com/src/repo-base/index.ts:80,83` e **importados** pelo módulo que os expõe. 113 + 2 = 115.

**O número de declaradas sobe com os tickets, e os outros dois não.** Entre a primeira medição deste ticket e esta, o KAM-091 fundiu com um `provisioning/metricas.ts` de **6** métricas que **nenhum serviço importa** — logo as declaradas passaram de 109 a 115 e as servidas ficaram nas mesmas. É a leitura central deste ticket, agora com um exemplo que não é meu: o problema não é faltarem métricas, é faltarem serviços que as importem.

### 2.2 Declaradas, servidas, alcançáveis — três números e não um

| | Antes | Depois |
|---|---|---|
| Declaradas em código | 115 | 115 |
| Servidas por **algum** processo que o repositório define | 23 | 67 |
| Alcançáveis numa pilha de `docker compose` | **7** | **51** |

A diferença entre as duas últimas linhas são os processos `publicador`, `consumidor`, `entrada` e `agr_shim` do `worker-canal`: servem 16 métricas entre si, existem como *scripts* no `package.json` e **não aparecem em nenhum `Dockerfile` nem compose**. Em compose, antes deste ticket, só `gwy:3010` (5) e `com:3002` (2) eram raspáveis.

Este ticket acrescentou o AGR, com **44**.

As restantes 48 não estão por esquecimento. Os **dez** módulos `outbound`, `metering`, `hnd`, `qualidade`, `coexistencia`, `avisos`, `consentimento`, `modos`, `onboarding` e `provisioning` do `packages/core-ts` **não são importados por nenhum serviço** — medido com `grep -rn "core-ts/outbound" services`, que dá zero. São biblioteca à espera de quem as ligue, e expô-las publicava zeros permanentes.

### 2.3 A regra das etiquetas, e porque é que o `tenant_id` não serve

O `OBS-I` de `seguranca/ameacas_stride.md` — que vive no repositório privado — **recusa identificadores, não dimensões pequenas**. A frase é do dicionário §3.16, na linha da `channel_quality{rating}`: uma etiqueta de três valores fechados passa onde uma de *tenant* não passava.

O critério 3 do KAM-080 escreve «`tenant_id` permitido como etiqueta». O dicionário, nas emendas **1.21** (para a `meta_cost_usd_total{tenant}` do KAM-015) e **1.25** (para as métricas do KAM-023), já decidiu o contrário, **duas vezes**, e com a saída escrita: *«o por-*tenant* e o por-canal saem de consulta»*.

Onde as duas discordam prevalece o dicionário, que é fonte de nível 4 contra o nível 8 de um bloco de ticket. O `obs_lint` encaixa as duas leituras sem contradizer nenhuma:

1. o **nome** `tenant_id` passa — é o que o critério 3 escreve à letra;
2. um nome permitido por nome tem de declarar **lista fechada de valores**, nunca só um tecto;
3. todo o valor de domínio casa `^[a-z][a-z0-9_]{1,62}$` — e **um UUID não casa**, porque tem hífenes e começa muitas vezes por dígito.

A regra 2 nasceu de um furo medido: sem ela, `tenant_id` com `cardinalidade_maxima: 64` passava **sem que nenhum valor fosse olhado**, e 64 UUIDs cabem num tecto de 64. É a 2 que faz a 3 correr, e é a 3 que torna a 1 honesta.

**O por-tenant, então, de onde sai?** De SQL. O `SQL_CUSTO_DO_TENANT` do `packages/core-ts/src/outbound/consultas.ts` soma micro-dólares por tenant e período. Hoje **não** agrupa por categoria, o que o critério 7 pede: fica em §8.

---

## 3. Alertas

As **8** regras estão em [`../infra/compose/prometheus/regras/kamba.yml`](../infra/compose/prometheus/regras/kamba.yml), validadas por `make obs-promtool`.

A aritmética, porque é fácil de errar e eu errei-a: as 8 regras cobrem **4 das 12 linhas** do §9.2 (a fila dá duas regras, uma por serviço); **8 linhas** do §9.2 ficam por escrever; e **3** das regras não são do §9.2.

| Alerta | Sev. | §9.2 | Runbook | Nota |
|---|---|---|---|---|
| `ingress_parado` | P1 | linha 1 | RB-K01 | Só a metade de «0 mensagens > 10 min»; **não há sonda** |
| `alvo_em_baixo` | P1 | **não** | RB-K01 | `up == 0`. Acrescentada: é o que apanha **uma** réplica morta de duas |
| `fila_de_entrada_a_crescer` | P2 | linha 2 | RB-K03 | Mede **profundidade**, não a idade do mais antigo |
| `fila_do_agente_a_crescer` | P2 | linha 2 | RB-K03 | Idem, do lado do AGR |
| `latencia_de_resposta_alta` | P2 | linha 3 | RB-K03 | **Último** valor com guarda de trânsito, não um p95 |
| `llm_sem_budget` | P3 | linha 10 | RB-K03 | Dispara no **esgotamento**, não aos 80% |
| `degradacao_acima_do_limiar` | P2 | **não** (KAM-037) | `degradacao-do-agr.md` | Fiel |
| `disjuntor_do_llm_aberto` | P2 | **não** (KAM-037) | `degradacao-do-agr.md` | Fiel |

**Três das que vêm do §9.2 medem um predicado mais fraco** do que ele escreve, e está dito na anotação `limite` de cada uma. Não se marca uma caixa com prova que não é a pedida, e uma regra que diga «p95» sobre um *gauge* do último valor seria exactamente isso — o AGR não tem histogramas, por decisão do ADR-018 escrita no próprio `metricas.py`.

As **oito que faltam** estão em `regras_por_escrever` do catálogo, cada uma com o que falta e o credor: callbacks, WAL, restauro mensal, *quality rating*, *free tier*, `account_update`, segredo a expirar e memória. Não se escreveram como YAML inerte de propósito: **um alerta que nunca dispara parece cobertura**, e é pior do que a sua ausência porque ninguém volta a olhar.

### 3.1 As duas classes de defeito que estas regras aprenderam a evitar

Nenhuma das duas é visível pelo `promtool check rules`, e nenhuma é visível pelo `obs_lint`. **Só se vêem a correr as regras** — e é por isso que existe o `testes/kamba_test.yml`, com 17 casos.

| Classe | O que mordeu | Remédio |
|---|---|---|
| **Série ausente não é série a zero** | O `ingress_parado` com `increase(...) == 0`: um `increase()` sobre uma série que desapareceu devolve **nada**, e uma expressão sem resultado não dispara. A regra ficava calada precisamente quando o ingress parava | `absent()` |
| **Série que nasce a 1 não é série que subiu** | Os três `increase(...) > 0` do AGR: o `exposicao()` não emite séries a zero, pelo que o contador **nasce já a 1** e o Prometheus não atribui subida à primeira amostra. Os alertas exigiam **duas** ocorrências para avisar da primeira | `or (c > 0 unless c offset <janela>)` |

E uma terceira, que não é de PromQL mas de leitura: o `for: 10m` por cima de um `increase[10m]` **soma-se** à janela, e o `ingress_parado` levava 20 min a disparar contra os ≤ 11 min que o critério 5 pede. A janela já é a duração.

### 3.2 O décimo-segundo alerta não tem runbook, e isso é um conflito do canon

O §9.2 escreve «Escalar» na linha da memória, e não um `RB-K`. Mas o mesmo §9.2 diz **«alerta sem runbook é removido»**, e o critério 4 deste ticket exige `runbook_url` em todas. As três afirmações não cabem juntas.

Não se resolveu aqui: criar um `RB-K11` excede os dez *stubs* que o ticket manda criar, e apontar um alerta de capacidade para um dos dez seria mandar quem atende para uma página que não fala de capacidade. **Fica medido**, no catálogo e nesta linha, para quem governa o §9.2 decidir.

### 3.3 Cada alerta aponta para um runbook que fala dele

Parece óbvio e não era: a primeira versão tinha **cinco dos seis** alertas a apontar para o RB-K03, e dois deles — os do AGR — para uma página que não os menciona. Pior, o RB-K03 nomeava `fila_idade`, `latencia_p95` e `orcamento_llm`, **três nomes que não existiam em regra nenhuma**.

Um `runbook_url` que resolve para um ficheiro existente cumpre a regra do §9.2 **na forma**; que o ficheiro fale do alerta é o que a cumpre **no efeito**. O `obs_lint` só pode verificar a primeira — a segunda verifica-se lendo, e foi assim que se corrigiu. Os dois do AGR apontam agora para `runbooks/degradacao-do-agr.md`, que os reivindica por escrito.

---

## 4. Canal de alertas e escalamento

### 4.1 O canal não está escolhido, e o efeito é concreto

Os três `receivers` do Alertmanager — `primario-p1`, `primario-p2`, `registo-p3` — **não têm notificador**. O `docs/tecnica/09` §16 fixa a rotação e o escalamento e **não nomeia transporte**: não diz e-mail, nem SMS, nem Slack, nem fornecedor de *paging*. Escolher um acrescenta um **subprocessador**, que entra no inventário do **KAM-069**.

O [`../infra/egress/alertmanager.yaml`](../infra/egress/alertmanager.yaml) é `destinos: []` com `por_omissao: negar`, pela mesma razão: um FQDN escrito por antecipação passava o gate e entregava alertas a um sítio que ninguém decidiu.

> **Dito sem rodeios:** as regras avaliam, os alertas agrupam-se e ficam visíveis no Alertmanager, e **nenhum ser humano é notificado**.

Quando o canal for escolhido, entram **dois** sítios e não um: um destino em `infra/egress/alertmanager.yaml` **e** a mesma linha em `infra/egress/proxy-saida.yaml` (as regras `allowlist-em-falta` e `allowlist-sem-dono` exigem os dois), e o serviço passa a precisar da rede `app` e do `HTTPS_PROXY`.

### 4.2 O escalamento inicial

Do `docs/tecnica/09` §16, e **é procedimento humano**:

```text
primário  →  secundário (15 min)  →  arquitecto
```

- rotação semanal entre **≥ 3** pessoas; cobertura **07:00–23:00 WAT** (horário de comércio);
- fora dele, **só P1** chama o primário, e a degradação graciosa (§12) protege os dados;
- passagem de turno escrita; *post-mortem* sem culpa em ≤ 5 dias; revisão trimestral de acessos.

**O Alertmanager não implementa isto, e vale dizer porquê:** ele reenvia ao mesmo `receiver` em `repeat_interval` e **não sabe** que o primeiro humano não respondeu. Quem saberia é um sistema de *paging* com confirmação de recepção, que não existe aqui. O que a configuração dá é `repeat_interval: 15m` nos P1, para que o alerta volte enquanto ninguém o silencia.

O horário comercial entra em **UTC** na regra `ingress_parado`: 07:00–23:00 WAT = **06:00–22:00 UTC**, e o `hour()` do Prometheus é em UTC. Sem a conversão, o alerta disparava todas as noites — e um alerta que dispara todas as noites ensina a equipa a ignorá-lo. Há um caso de teste só para isto.

---

## 5. O que não se pode medir aqui, e não se finge

| Critério | O que pede | Porque não fecha |
|---|---|---|
| 1 (canário) | o telefone e o texto-canário **não ficam em Loki** | **Não há Loki.** O canário de PII existe e corre — é o X-11 do gate 6, sobre a saída dos dois *loggers*, com 1 030 *fixtures* — mas mede o **emissor**, não o destino. Medir o emissor não é medir o Loki |
| 4 (injecção) | cada regra **dispara numa injecção de falha em *staging*** | **Não há *staging* a correr.** O que se mediu, e é mais do que antes: as 8 regras passam `promtool check rules`, cada uma cita uma métrica que um processo serve (`obs_lint`), e **17 casos de `promtool test rules`** confrontam o que cada regra faz com o que devia fazer — incluindo os quatro casos em que ela não disparava. **Não é injecção em *staging***: é o motor de regras com séries sintéticas, sem pilha, sem GWY a morrer de verdade e sem Alertmanager a receber |
| 5 (sonda) | mensagem de teste a cada 5 min **ao número de teste de produção**; P1 em ≤ 11 min ao parar o GWY | **Não há produção nem número de teste de produção**, e a sonda tem de correr **fora do *host***. Não se escreveu uma sonda contra `localhost`: isso não é uma sonda externa, é um teste a chamar-se sonda. **O que se mediu da metade que não depende dela:** o `ingress_parado` dispara em **8 min** quando o GWY morre e em **11 min** quando fica vivo sem trânsito, os dois com caso de teste. A versão anterior levava 15 e 20 |
| 6 (consumo) | consumo da pilha de monitorização **medido** (alvo ≤ 1,5 GB) | Mediu-se o que existe: Prometheus **1 024 MiB** e Alertmanager **256 MiB** de tecto declarado = **1 280 MiB**, dentro do alvo. **Não é a medição que o critério pede** — aquela é consumo em execução da pilha completa, e a pilha completa inclui Grafana (512 MiB) e Loki (256 MiB), que não correm. Com eles o tecto declarado dá **2 048 MiB**, acima do alvo |

---

## 6. O Grafana e o Loki são AGPL-3.0

Esta é a decisão que o KAM-076 devolveu a este ticket, e que este ticket devolve a quem pode tomá-la.

O [`../ci/licenses.yaml`](../ci/licenses.yaml) nega o prefixo `AGPL`, e a lista `negadas` não é «não permitida»: é **proibida**, e só passa com *waiver* que cite um ADR. A evidência do KAM-076 (`evidencia/KAM-076.md`) escreveu-o na própria linha do manifesto: *«**AGPL-3.0**, que `ci/licenses.yaml` nega por prefixo: entrar exige fechar a licença com um ADR, e isso não é deste ticket»*.

**Também não é deste.** Alterar `ci/licenses.yaml` ou escrever um *waiver* é mexer no critério de um portão que bloqueia, o que é regra de bloqueio e decisão do fundador.

O que se entregou em vez disso é a parte que **é nossa** e não depende de correr o programa:

- os quatro painéis em JSON do esquema do Grafana, versionados em [`../ops/paineis/`](../ops/paineis/);
- o [`../ops/paineis/provisionamento.yaml`](../ops/paineis/provisionamento.yaml), que os monta quando houver Grafana;
- a verificação: o `obs_lint` lê os painéis como terceira superfície — **incluindo o `templating` e as `annotations`, que vivem fora de `panels`, e as subpastas, que o *file provider* do Grafana lê recursivamente**.

**Substitutos permissivos existem e não se escolheram.** Para registo, e não como recomendação: o Vector é MPL-2.0 (que a *allowlist* já permite) e o Alloy é Apache-2.0, ambos no lugar do agente de recolha; a Perses é Apache-2.0 no lugar dos painéis. Trocar um componente que o **título do ticket nomeia** é decisão de desenho e de canon, não de quem o executa — fica medido, não tomado.

---

## 7. A verificação por máquina, e porque é que não está num portão

`tools/obs_lint` tem dois comandos e **três superfícies**:

```bash
make obs-lint       # cardinalidade + runbooks + canário
make obs-promtool   # promtool check rules E test rules, da imagem fixada
```

| Regra | O que recusa |
|---|---|
| `etiqueta_proibida` | `contact_id`, telefone, BSUID, `wamid`, `contact_hmac`, … (16 nomes, com razão escrita cada) — num selector, numa cláusula `by`/`on`, **ou criada** por `label_replace`/`label_join` |
| `etiqueta_sem_dominio` | uma etiqueta sem lista fechada nem tecto; e um nome permitido por nome (`tenant_id`) que traga **só** tecto |
| `dominio_grande` | mais de 64 valores |
| `etiqueta_fora_da_gramatica` | um nome que não casa `^[a-z][a-z0-9_]{1,62}$`, declarado **ou criado** |
| `valor_fora_da_gramatica` | um **valor** que não casa — é aqui que o UUID cai |
| `alerta_sem_runbook` | um alerta sem `runbook_url` |
| `runbook_inexistente` | um `runbook_url` que não resolve para ficheiro no disco |
| `severidade_invalida` | `severity` fora de P1/P2/P3 |
| `metrica_fora_do_catalogo` | uma regra **ou painel** que cita métrica fora do catálogo, **incluindo escondida num `{__name__="…"}`** |
| `metrica_sem_produtor` | uma regra ou painel que cita métrica com `exposta_por: []` — a promessa que o catálogo fazia e o *lint* não cumpria |

O canário tem **16 negativas e 2 positivas**; cada negativa tem de morder **exactamente** a sua regra, as dez obrigatórias vêm do código (e não das *fixtures*, para que uma pasta vazia não dê «tudo verde») e exigem-se ≥ 2 positivas, para que um *lint* que recuse tudo não passe. **94 testes**, 91% de cobertura.

Cinco das dezasseis negativas existem porque a revisão adversarial mediu o furo correspondente: um escape que um portão podia ter apanhado vira portão, e nesta casa a forma de um portão se provar é a *fixture* negativa.

> **Não está ligado a nenhum `ci-*`, e isso é deliberado.**
>
> O critério 3 escreve «o CI falha». Este ticket entrega o *lint* e a medição de que ele morde, e **pára aí**: ligar uma verificação que trava fusões é alteração de **regra de bloqueio**, e isso é decisão do fundador.
>
> Vale pelos dois caminhos, e o segundo é o que parece inofensivo: um *job* novo no `ci.yaml` acrescenta um **contexto exigido** ao *ruleset* da `main` (e teria de entrar no `esperados=11` escrito à mão); e uma linha dentro do `ci-2` — o caminho que o `log-lint` e o `money-lint` usaram — não cria contexto novo mas muda o **critério** de um portão que já bloqueia. É a mesma fronteira, por outra porta.
>
> Para ligar, quando essa decisão existir, é **uma linha** no alvo `ci-2` do `Makefile`, ao lado do `@$(MAKE) log-lint`:
>
> ```make
> 	@$(MAKE) obs-lint
> ```

### 7.1 O que o `obs_lint` não cobre

Prova que o **catálogo, as regras e os painéis** respeitam a política. **Não** prova:

- **que o código não declara uma etiqueta que o catálogo não conhece** — para isso teria de ler TypeScript, e um varredor de TypeScript cego às cadeias é um defeito medido nesta casa (KAM-066). Quem fecha esse lado são as bibliotecas de métricas, que já recusam por gramática **em execução**;
- **semântica temporal** — se uma regra dispara quando deve. Isso é o `promtool test rules`, e a razão de ele existir é que três alertas passaram este *lint* e o `check rules` sem nunca poderem disparar;
- **que o runbook fala do alerta** — só que o ficheiro existe. Ver §3.3.

Há uma verificação que lê o **texto servido** em vez do código: `services/agr/tests/test_healthz.py::TestMetricas::test_depois_de_contar_o_corpo_traz_o_formato_sem_identificadores`. Ela olha para os **nomes** de etiqueta e para a **forma dos valores** (UUID, `+244…`, `9########`, 32 hex, `wamid.…`); a primeira metade, sozinha, era prova tautológica — os nomes de eixo do AGR vêm de dois literais e não podem variar.

---

## 8. Divergências e dívidas que este ticket deixa nomeadas

1. **O `exposicao()` do AGR não emite séries a zero.** Faz `if not series: continue`, pelo que um processo acabado de arrancar serve um corpo **vazio** e **um contador nasce já a 1**. Contraria a regra que os módulos TypeScript escrevem, e teve consequência real: três alertas não disparavam na primeira ocorrência (§3.1). **Não se corrigiu** — o comportamento está preso por três testes de outro ticket (`test_metricas.py::test_a_exposicao_vazia_e_vazia` exige exactamente `""`), é decisão do módulo (KAM-025/KAM-037) e invertê-la é mexer no critério de outro ticket. O remédio ficou do lado das regras, com o `unless`. **Se alguém fizer o AGR emitir zeros, o `unless` passa a ser redundante e pode sair** — e há um caso de teste de controlo que mostra isso.
2. **O `SQL_CUSTO_DO_TENANT` não agrupa por categoria.** O critério 7 pede o `pricing` «exposto como métrica agregada por tenant e categoria». A persistência **já existe** — `platform.outbound_messages.pricing jsonb`, com `billable`, `pricing_model`, `type` e `category`, desde a revisão `0010` — e **nenhuma migração é necessária**. O que falta é (a) o `statuses[]` do webhook levar o `pricing` até ao `Saida.ingerir`, que hoje não acontece porque o `EventoDeEntrada` não tem campo para ele e o braço `outbound` do encaminhador é um esqueleto, e (b) um `GROUP BY` por categoria. O primeiro é do ticket que ligar o estágio de saída.
3. **Não há métrica por código de erro da Meta.** O critério 2 nomeia `130429` e `131049`. O que existe é `outbound_rate_limited_total{origem="meta"}`, que conta um `130429` repetido pelo *backoff* e não cobre o `131049`. Uma métrica `{codigo}` com domínio fechado nos três códigos do `E1` seria admissível pelo `OBS-I`.
4. **Em *staging*, todo o alerta sai com `ambiente: prod`.** O `external_labels` está no `prometheus.yml`, que **os dois composes montam sem *override***. A linha é anterior a este ticket, mas é este ticket que faz *staging* **produzir** alertas — antes o Prometheus só se raspava a si próprio e não tinha `rule_files`. Duas consequências: o `inhibit_rules` do Alertmanager fecha com `equal: [ambiente]` e tudo em *staging* casa com tudo de «prod»; e a prova que o critério 5 pede é literalmente «ao parar o GWY em *staging*», cujo alerta diria `ambiente="prod"`. **Não se corrigiu aqui** porque as duas saídas são do mesmo nível: ou um segundo ficheiro de configuração quase idêntico (duplicação de ~100 linhas por uma etiqueta), ou templating no compose — e nenhuma é obviamente certa. Credor: o ticket que puser *staging* a correr.
5. **A amostragem semanal de logs em `prod` continua sem agendamento.** O `tools/log_policy/amostra.py` existe e está testado, e o `docs/logs.md` diz que a origem seria o Loki — que não existe.

---

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Documento criado pelo **KAM-080**. Catálogo de métricas com o instrumento que o conta, **8** regras de alerta (4 das 12 linhas do §9.2) com **17 casos de `promtool test rules`**, dez *stubs* RB-K01–RB-K10, Alertmanager por severidade sem notificador, quatro painéis como código, e o `obs_lint` com dez regras em três superfícies e 16 negativas de canário. Mede e devolve: o canário em Loki, a injecção em *staging*, a sonda de produção, o consumo da pilha completa e a licença AGPL-3.0 do Grafana e do Loki. **A revisão adversarial encontrou 19 achados; os quatro mais graves eram alertas que não podiam disparar e cinco furos do *lint*, e estão corrigidos com caso de teste cada.** | Equipa KAMBÁ |
