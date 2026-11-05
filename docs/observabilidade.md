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
| Métricas | 18 módulos, 109 nomes distintos | **Declaradas 109; alcançáveis em `compose` 51** — ver §2 |
| Exposição | `/metrics` no GWY (3010), no COM (3002) e no AGR (8000) | O AGR nasceu com este ticket |
| Recolha | [`../infra/compose/prometheus/prometheus.yml`](../infra/compose/prometheus/prometheus.yml) | Três alvos, por `dns_sd_configs` |
| Regras de alerta | [`../infra/compose/prometheus/regras/kamba.yml`](../infra/compose/prometheus/regras/kamba.yml) | **Seis** das doze do §9.2 — ver §3 |
| Encaminhamento | [`../infra/compose/alertmanager/alertmanager.yml`](../infra/compose/alertmanager/alertmanager.yml) | Por severidade. **Não notifica** — ver §4 |
| Runbooks | `runbooks/RB-K01…RB-K10` | *Stubs*: título, gatilho, severidade. Os executáveis são o KAM-083 |
| Painéis | [`../ops/paineis/`](../ops/paineis/) | Quatro, como código. **O Grafana não corre** — ver §6 |
| Verificação | `tools/obs_lint`, `make obs-lint`, `make obs-promtool` | **Não ligado a nenhum portão** — ver §7 |
| Envio para Loki | — | **Não existe.** Loki é AGPL-3.0 — ver §6 |
| Sonda externa | — | **Não existe.** Não há produção — ver §5 |

---

## 2. Catálogo de métricas

O catálogo legível por máquina é [`../ops/metricas/catalogo.yaml`](../ops/metricas/catalogo.yaml), e é a superfície que o `obs_lint` verifica. Cobre as métricas que as regras e os painéis citam, mais as doze séries que o critério 2 do KAM-080 nomeia — **não** é o inventário das 109.

**A medição que importa, de 2026-11-05.** Há dois números e eles não são o mesmo, o que é precisamente o ponto:

| | Antes | Depois |
|---|---|---|
| Métricas servidas por **algum** processo que o repositório define | 23 | 67 |
| Métricas alcançáveis numa pilha de `docker compose` | **7** | **51** |

A diferença entre as duas colunas da esquerda são os processos `publicador`, `consumidor`, `entrada` e `agr_shim` do `worker-canal`: servem 16 métricas entre si, existem como *scripts* no `package.json` e **não aparecem em nenhum `Dockerfile` nem compose** (medido). Em compose, antes deste ticket, só `gwy:3010` (5) e `com:3002` (2) eram raspáveis.

Este ticket acrescentou o AGR, com **44**.

As restantes 42 não estão por esquecimento. Os módulos `outbound`, `metering`, `hnd`, `qualidade`, `coexistencia`, `avisos`, `consentimento`, `modos` e `onboarding` do `packages/core-ts` **não são importados por nenhum serviço** — medido com `grep -rn "core-ts/outbound" services`, que dá zero. São biblioteca à espera de quem as ligue, e expô-las publicava zeros permanentes.

### 2.1 A regra das etiquetas, e porque é que o `tenant_id` não serve

O `OBS-I` de `seguranca/ameacas_stride.md` — que vive no repositório privado — **recusa identificadores, não dimensões pequenas**. A frase é do dicionário §3.16, na linha da `channel_quality{rating}`: uma etiqueta de três valores fechados passa onde uma de *tenant* não passava.

O critério 3 do KAM-080 escreve «`tenant_id` permitido como etiqueta». O dicionário, nas emendas **1.21** (para a `meta_cost_usd_total{tenant}` do KAM-015) e **1.25** (para as métricas do KAM-023), já decidiu o contrário, **duas vezes**, e com a saída escrita: *«o por-*tenant* e o por-canal saem de consulta»*.

Onde as duas discordam prevalece o dicionário, que é fonte de nível 4 contra o nível 8 de um bloco de ticket. O `obs_lint` encaixa as duas leituras sem contradizer nenhuma:

1. o **nome** `tenant_id` passa — é o que o critério 3 escreve à letra;
2. toda a etiqueta declara **domínio fechado ou tecto**;
3. todo o valor de domínio casa `^[a-z][a-z0-9_]{1,62}$` — e **um UUID não casa**, porque tem hífenes e começa muitas vezes por dígito.

É a regra 3 que torna a 1 honesta. Sem ela, bastava declarar 64 UUIDs e o identificador entrava com o nome permitido. As duas *fixtures* que provam o par são `positivas/tenant_id_passa_pelo_nome` e `negativas/valor_fora_da_gramatica__uuid_no_dominio`.

**O por-tenant, então, de onde sai?** De SQL. O `SQL_CUSTO_DO_TENANT` do `packages/core-ts/src/outbound/consultas.ts` soma micro-dólares por tenant e período. Hoje **não** agrupa por categoria, o que o critério 7 pede: fica nomeado em §8.

---

## 3. Alertas

As seis regras que existem estão em [`../infra/compose/prometheus/regras/kamba.yml`](../infra/compose/prometheus/regras/kamba.yml), validadas por `make obs-promtool`.

| Alerta | Sev. | Runbook | Nota |
|---|---|---|---|
| `ingress_parado` | P1 | RB-K01 | Só a metade de «0 mensagens > 10 min»; **não há sonda** |
| `fila_a_crescer` | P2 | RB-K03 | Mede **profundidade**, não a idade do mais antigo |
| `latencia_de_resposta_alta` | P2 | RB-K03 | Mede o **último** turno, não o p95 |
| `llm_sem_budget` | P3 | RB-K03 | Dispara no **esgotamento**, não aos 80% |
| `degradacao_acima_do_limiar` | P2 | RB-K03 | Fiel. Era o «alerta» que o KAM-037 deixou escrito à espera deste ticket |
| `disjuntor_do_llm_aberto` | P2 | RB-K03 | Fiel |

**Três das quatro primeiras medem um predicado mais fraco do que o §9.2 escreve**, e está dito na anotação `limite` de cada uma. Não se marca uma caixa com prova que não é a pedida, e uma regra que diz «p95» sobre um *gauge* do último valor seria exactamente isso — o AGR não tem histogramas, por decisão do ADR-018 escrita no próprio `metricas.py`.

As **seis que faltam** estão em `regras_por_escrever` do catálogo, cada uma com o que falta e o credor: callbacks, WAL, restauro mensal, *quality rating*, *free tier*, `account_update`, segredo a expirar e memória. Não se escreveram como YAML inerte de propósito: **um alerta que nunca dispara parece cobertura**, e é pior do que a sua ausência porque ninguém volta a olhar.

### 3.1 O décimo-segundo alerta não tem runbook, e isso é um conflito do canon

O §9.2 escreve «Escalar» na linha da memória, e não um `RB-K`. Mas o mesmo §9.2 diz **«alerta sem runbook é removido»**, e o critério 4 deste ticket exige `runbook_url` em todas. As três afirmações não cabem juntas.

Não se resolveu aqui: criar um `RB-K11` excede os dez *stubs* que o ticket manda criar, e apontar um alerta de capacidade para um dos dez seria mandar quem atende para uma página que não fala de capacidade. **Fica medido**, no catálogo e nesta linha, para quem governa o §9.2 decidir.

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

O horário comercial entra em **UTC** na regra `ingress_parado`: 07:00–23:00 WAT = **06:00–22:00 UTC**, e o `hour()` do Prometheus é em UTC. Sem a conversão, o alerta disparava todas as noites — e um alerta que dispara todas as noites ensina a equipa a ignorá-lo.

---

## 5. O que não se pode medir aqui, e não se finge

| Critério | O que pede | Porque não fecha |
|---|---|---|
| 1 (canário) | o telefone e o texto-canário **não ficam em Loki** | **Não há Loki.** O canário de PII existe e corre — é o X-11 do gate 6, sobre a saída dos dois *loggers*, com 1 030 *fixtures* — mas mede o **emissor**, não o destino. Medir o emissor não é medir o Loki, e marcar a caixa com isso era marcá-la com prova que não é a pedida |
| 4 (injecção) | cada regra **dispara numa injecção de falha em *staging*** | **Não há *staging* a correr.** O que se mediu é que as seis regras são sintacticamente válidas (`promtool`, 6 rules found) e que cada uma cita uma métrica que um processo serve (`obs_lint`). Nenhuma foi vista a disparar |
| 5 (sonda) | mensagem de teste a cada 5 min **ao número de teste de produção**; P1 em ≤ 11 min ao parar o GWY | **Não há produção nem número de teste de produção**, e a sonda tem de correr **fora do *host*** — que também não existe. Não se escreveu uma sonda que apontasse para `localhost`: isso não é uma sonda externa, é um teste a chamar-se sonda |
| 6 (consumo) | consumo da pilha de monitorização **medido** (alvo ≤ 1,5 GB) | Mediu-se o que existe: Prometheus **1 024 MiB** e Alertmanager **256 MiB** de tecto declarado = **1 280 MiB**, dentro do alvo. **Não é a medição que o critério pede** — aquela é consumo em execução da pilha completa, e a pilha completa inclui Grafana (512 MiB) e Loki (256 MiB), que não correm. Com eles o tecto declarado dá **2 048 MiB**, acima do alvo de 1,5 GB |

---

## 6. O Grafana e o Loki são AGPL-3.0

Esta é a decisão que o KAM-076 devolveu a este ticket, e que este ticket devolve a quem pode tomá-la.

O [`../ci/licenses.yaml`](../ci/licenses.yaml) nega o prefixo `AGPL`, e a lista `negadas` não é «não permitida»: é **proibida**, e só passa com *waiver* que cite um ADR. A evidência do KAM-076 (`evidencia/KAM-076.md`) escreveu-o na própria linha do manifesto: *«**AGPL-3.0**, que `ci/licenses.yaml` nega por prefixo: entrar exige fechar a licença com um ADR, e isso não é deste ticket»*.

**Também não é deste.** Alterar `ci/licenses.yaml` ou escrever um *waiver* é mexer no critério de um portão que bloqueia, o que é regra de bloqueio e decisão do fundador.

O que se entregou em vez disso é a parte que **é nossa** e não depende de correr o programa:

- os quatro painéis em JSON do esquema do Grafana, versionados em [`../ops/paineis/`](../ops/paineis/);
- o [`../ops/paineis/provisionamento.yaml`](../ops/paineis/provisionamento.yaml), que os monta quando houver Grafana;
- a verificação: o `obs_lint` lê os painéis como terceira superfície, e recusa uma consulta que filtre por identificador ou cite métrica fora do catálogo.

**Substitutos permissivos existem e não se escolheram.** Para registo, e não como recomendação: o Vector é MPL-2.0 (que a *allowlist* já permite) e o Alloy é Apache-2.0, ambos no lugar do agente de recolha; a Perses é Apache-2.0 no lugar dos painéis. Trocar um componente que o **título do ticket nomeia** é decisão de desenho e de canon, não de quem o executa — fica medido, não tomado.

---

## 7. A verificação por máquina, e porque é que não está num portão

`tools/obs_lint` tem dois comandos e três superfícies:

```bash
make obs-lint       # cardinalidade + runbooks + canário
make obs-promtool   # promtool check rules, de dentro da imagem fixada
```

| Regra | O que recusa |
|---|---|
| `etiqueta_proibida` | `contact_id`, telefone, BSUID, `wamid`, `contact_hmac`, … (16 nomes, com razão escrita cada) |
| `etiqueta_sem_dominio` | uma etiqueta sem lista fechada nem tecto |
| `dominio_grande` | mais de 64 valores |
| `etiqueta_fora_da_gramatica` | um nome que não casa `^[a-z][a-z0-9_]{1,62}$` |
| `valor_fora_da_gramatica` | um **valor** que não casa — é aqui que o UUID cai |
| `alerta_sem_runbook` | um alerta sem `runbook_url` |
| `runbook_inexistente` | um `runbook_url` que não resolve para ficheiro no disco |
| `severidade_invalida` | `severity` fora de P1/P2/P3 |
| `metrica_fora_do_catalogo` | uma regra **ou painel** que cita métrica que ninguém expõe |

O canário tem **11 negativas e 2 positivas**; cada negativa tem de morder **exactamente** a sua regra, as obrigatórias vêm do código (e não das *fixtures*, para que uma pasta vazia não dê «tudo verde») e exigem-se ≥ 2 positivas, para que um *lint* que recuse tudo não passe.

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

Prova que o **catálogo, as regras e os painéis** respeitam a política. **Não** prova que o código não declara uma etiqueta que o catálogo não conhece — para isso teria de ler TypeScript, e um varredor de TypeScript cego às cadeias é um defeito medido nesta casa (KAM-066: o `//` de um `"https://…"` apaga o resto da linha).

Quem fecha esse lado são as próprias bibliotecas de métricas, que já recusam por gramática, **em execução**, uma etiqueta fora de `^[a-z][a-z0-9_]{1,62}$`. E há uma verificação que lê o **texto servido** em vez do código: `services/agr/tests/test_healthz.py::TestMetricas::test_depois_de_contar_o_corpo_traz_o_formato_sem_identificadores`.

---

## 8. Divergências e dívidas que este ticket deixa nomeadas

1. **O `exposicao()` do AGR não emite séries a zero.** Faz `if not series: continue`, pelo que um processo acabado de arrancar serve um corpo **vazio**. Contraria a regra que os módulos TypeScript escrevem («as séries aparecem sempre, mesmo a zero»), e **não se corrigiu**: o comportamento está preso por três testes de outro ticket (`test_metricas.py::test_a_exposicao_vazia_e_vazia` exige exactamente `""`). É decisão do módulo (KAM-025/KAM-037), não descuido. O que não se perde é o `up`, que fica a 1 — logo «não arrancou» continua distinguível, pelo `up` e não pela série.
2. **O `SQL_CUSTO_DO_TENANT` não agrupa por categoria.** O critério 7 pede o `pricing` «exposto como métrica agregada por tenant e categoria». A persistência **já existe** — `platform.outbound_messages.pricing jsonb`, com `billable`, `pricing_model`, `type` e `category`, desde a revisão `0010` — e **nenhuma migração é necessária**. O que falta é (a) o `statuses[]` do webhook levar o `pricing` até ao `Saida.ingerir`, que hoje não acontece porque o `EventoDeEntrada` não tem campo para ele e o braço `outbound` do encaminhador é um esqueleto, e (b) um `GROUP BY` por categoria. O primeiro é do ticket que ligar o estágio de saída.
3. **Não há métrica por código de erro da Meta.** O critério 2 nomeia `130429` e `131049`. O que existe é `outbound_rate_limited_total{origem="meta"}`, que conta um `130429` repetido pelo *backoff* e não cobre o `131049`. Uma métrica `{codigo}` com domínio fechado nos três códigos do `E1` seria admissível pelo `OBS-I`.
4. **A amostragem semanal de logs em `prod` continua sem agendamento.** O `tools/log_policy/amostra.py` existe e está testado, e o `docs/logs.md` diz que a origem seria o Loki — que não existe. Não se agendou nada.

---

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Documento criado pelo **KAM-080**. Catálogo de métricas, seis das doze regras de alerta com severidade e `runbook_url`, dez *stubs* RB-K01–RB-K10, Alertmanager por severidade sem notificador, quatro painéis como código, e o `obs_lint` com 11 negativas de canário. Mede e devolve: o canário em Loki, a injecção em *staging*, a sonda de produção, o consumo da pilha completa e a licença AGPL-3.0 do Grafana e do Loki. | Equipa KAMBÁ |
