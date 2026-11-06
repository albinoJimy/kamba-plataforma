# Gate da Fase 0 — demonstração do esqueleto andante

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — checklist do gate da Fase 0 (G0-1 a G0-8) |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Estado | NÃO VERIFICADO |
| Fonte | `../../00_Arquitectura_Solucao.md` §13.1 (K1) e §13.2 (Fase 0); `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §3A (Regras 1B e 5); `../../../../specs/00_KAMBA_Carta.md` §4.2 e §5; `../../../../specs/01_Engineering_Standards_e_Handoff.md` §4 |
| Dono | Arquitecto de Plataforma, com o Responsável de Segurança e o de Produto |
| Ticket | KAM-108 (EPIC-10) |
| Classificação | Documento de Referência — Interno; **gate de fase** |
| Relacionados | [`Gate_Fase0_Decisao.md`](Gate_Fase0_Decisao.md), [`Gate_Fase0_Demonstracao.md`](Gate_Fase0_Demonstracao.md), [`Registo_Hipoteses.md`](Registo_Hipoteses.md), [`GoLive_Gate.md`](GoLive_Gate.md) |
| Instrumentos | [`tools/gate_fase0/`](../../../../tools/gate_fase0/README.md) |

> **Este documento não decide nada: mede.** A linha de cada condição tem estado,
> evidência nomeada ou credor, e data. **A demonstração e o veredicto são
> humanos** — está escrito nos «Detalhes Técnicos» do bloco KAM-108, e é a
> fronteira deste ficheiro: o que foi preparado está preparado; o que exige uma
> conversa real, três execuções por quem não escreveu o código e três
> assinaturas, está **em branco com o credor nomeado**.
>
> **Nenhuma linha G0-n está satisfeita hoje**, e isso não é um atraso: é o estado
> correcto de um gate cujo primeiro critério é uma demonstração que ainda não se
> fez. O valor deste documento é tornar o «ainda não» legível, datável e
> **separável** — distinguir o que falta medir do que já se mediu e falhou, e do
> que não pode ficar verde sem trabalho que este ticket não faz.
>
> **Duas divergências medidas** (§9). Nenhuma é defeito deste ticket nem dos
> tickets que ele verifica: são o critério a pedir coisas que a Fase 0 não tem, e
> alterar o critério de um gate não é acto de quem o executa. A do **G0-5** está
> **decidida** — o fundador decidiu a 2026-11-06 que o critério não muda e que
> ela fica **registada** (§9.1); a do **G0-1** fica **devolvida**, porque pede
> três decisões que ainda não foram tomadas (§9.2).

---

## 0. Como se lê

| Estado | Significado |
|---|---|
| `satisfeito` | Cumprido, com a evidência nomeada na coluna |
| `não` | Medido e não cumprido |
| `em branco` | Não medido ainda — e com o **credor** na coluna, porque uma linha aberta sem credor é trabalho que ninguém reclama |
| `não aplicável` | Com a razão escrita |

**Uma linha só passa a `satisfeito` com evidência nomeada** — um comando com o
seu resultado, uma execução de CI, um ficheiro, uma assinatura com data. «Está
tratado» não é evidência, e «o ticket fundiu» não é «a condição está cumprida».

**A ponta de medição é `fe40048`** (`publico/main` a 2026-11-06), e cada linha
que leve um número diz onde foi medido. Um número sem ponta não é reproduzível, e
nesta árvore muda duas ou três vezes ao dia.

---

## 1. G0-1 — Esqueleto andante

> «Num ambiente com a Meta real (telemóvel → número de teste ou de coexistência,
> **nunca simulador**), o cenário *scriptado* cria um pedido (Vendedor), emite
> referência, recebe `payment.manual_confirmed` (ou `payment.confirmed` no
> *sandbox*), passa a `paga` e a vertical Serviços cria o lembrete/agenda; 3
> execuções consecutivas verdes por uma pessoa que não escreveu o código; traço
> por identificadores (mensagem → pedido → evento de pagamento → consumo) sem
> conteúdo nem telefone.»

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 1.1 | **Cenário *scriptado* escrito**, com o observável de cada passo por identificador | **satisfeito** | Oito passos em [`Gate_Fase0_Demonstracao.md`](Gate_Fase0_Demonstracao.md) §2, **gerados** de `tools/gate_fase0/cenario.py` — e com ensaio a exigir que cada elo que o traço procura tenha um passo que o produz (`test_cenario.py`) | 2026-11-06 |
| 1.2 | **Ambiente com a Meta real**, nunca simulador | **em branco** | É o passo P0 do cenário, e é a única parte que não se pode automatizar sem deixar de a provar. Credor: **fundador** (número de teste ou de coexistência) | |
| 1.3 | A conversa real cria um pedido (Vendedor) | **em branco** | Credor: **a demonstração**. A cadeia mede-se com `python -m gate_fase0 traco`; a consulta do elo está em `tools/gate_fase0/consulta.py` | |
| 1.4 | Emite referência (`payment.reference_issued`) | **em branco** | Credor: **a demonstração** (passo P3) | |
| 1.5 | Recebe `payment.manual_confirmed` ou `payment.confirmed` e passa a `paga` | **em branco** | Credor: **KAM-055**, que entrega os dois eventos e a transição da encomenda e está **aberto** — sem secção de «Verificação dos Critérios de Aceitação» no `EPIC-05`, medido em `fe40048`. Só depois dele é que este passo tem o que medir | |
| 1.6 | **A vertical Serviços cria o lembrete/agenda** a partir do evento | **não** | **Medido, e é o achado deste ticket** — ver §9.2. O par `(servicos, payment.confirmed)` e o `(servicos, payment.manual_confirmed)` estão em `ACCOES_POR_LIGAR` (`services/agr/src/kamba_agr/eventos/handlers.py:221`), o que quer dizer «esta vertical subscreve e a acção dela **não está escrita**»; o desfecho do consumo é `sem_accao`. E o contrato publicado dos dois eventos **não admite `booking_id`** no *payload* (`additionalProperties: false`, quatro propriedades, medido nos dois esquemas de `contratos/eventos/payment.manual_confirmed/`), pelo que o efeito não é implementável como está escrito. Credor: **fundador** (§9.2) | 2026-11-06 |
| 1.7 | **3 execuções consecutivas verdes** por quem não escreveu o código | **em branco** | Folha de registo das três em [`Gate_Fase0_Demonstracao.md`](Gate_Fase0_Demonstracao.md) §4, a nascer vazia. Credor: **fundador** (quem conduz não pode ser quem escreveu) | |
| 1.8 | **Traço por identificadores, sem conteúdo nem telefone** — o instrumento | **satisfeito** | `tools/gate_fase0/traco.py`, com três barreiras (lista fechada, forma do valor, guarda da saída) e o **controlo negativo** a provar o predicado: alimentado com um *log* que leva conteúdo e um telefone de forma real, a saída não leva nenhum dos dois, e o canário corre os detectores **primeiro sobre a entrada**. **104 ensaios verdes**, cobertura de `traco.py` a 100% | 2026-11-06 |
| 1.9 | O traço da demonstração, corrido e arquivado | **em branco** | Credor: **a demonstração**. O instrumento sai com código **1** se a cadeia tiver elos em falta, para que um guião não leia verde sobre uma cadeia que parou | |

**O que a linha 1.6 significa para o veredicto.** O G0-8 diz que VERMELHO é «G0-1
ou G0-2 falham». A linha 1.6 está `não` por medição e não por falta de
demonstração, e é a única linha do G0-1 que **não se resolve correndo a
demonstração**. Decidir o que isso faz ao veredicto é do fundador, e não deste
documento: ver §9.2.

---

## 2. G0-2 — Regra de dois

> «A métrica de KAM-039 mostra reaproveitamento ≥ 70% e 0 excepções no core
> (teste de contrato verde; nenhum ramo `if vertical` no core, verificado por
> pesquisa estática).»

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 2.1 | Reaproveitamento **≥ 70%** | **satisfeito, e re-mede-se depois do KAM-055** | `python -m reuse_metric medir` em `fe40048` → **88,30%** (específico 1705, partilhado 12 869, total 14 574 linhas com código), código de saída **0**; limiar lido de `ci/regra-de-dois.yaml` (`caminho.limiar: 70`) e não escrito à mão. `python -m gate_fase0 reuso <artefacto>` recusa um artefacto de árvore suja ou de outra ponta | 2026-11-06 |
| 2.2 | **0 excepções no core** (nenhum ramo decidido por nome de vertical) | **satisfeito, e re-mede-se depois do KAM-055** | `python -m reuse_metric nucleo` em `fe40048` → «110 ficheiros varridos; **fluxo 0**, dominio 1, conteudo 45, prosa 119», código de saída **0**. O limite está escrito: `fluxo == 0` quer dizer «em nenhuma das formas que este verificador segue» (`docs/reuse-metric.md` §4) | 2026-11-06 |
| 2.3 | **Teste de contrato verde** | **satisfeito** | *Gate* 7 (contratos de evento) **verde** na execução [42222973021](https://github.com/albinoJimy/kamba-plataforma/actions/runs/42222973021) sobre `fe40048` | 2026-11-06 |
| 2.4 | O número da demonstração, medido na árvore que a demonstração correu | **em branco** | O KAM-055 **não está nesta ponta**, e é ele que traz os dois eventos de pagamento e a transição. Logo 2.1 e 2.2 **re-medem-se** depois de ele fundir, com o mesmo comando e a ponta nova. Credor: **KAM-055** (PR aberto) | |

**Porque é que 2.1 e 2.2 estão `satisfeito` e 2.4 está `em branco`.** São duas
perguntas e não uma: «a métrica passa o limiar nesta ponta» está medida e passa;
«a métrica passa o limiar na ponta em que o esqueleto andou» só se responde
depois. Marcar 2.1 sem 2.4 era dizer que o número de hoje é o número da
demonstração; não marcar nenhuma era esconder uma medição que existe.

---

## 3. G0-3 — Invariantes de domínio

> «Duplo toque e callback duplicado → 0 pedidos e 0 efeitos duplicados; suite de
> isolamento → 0 fugas entre tenants e contactos; 0 caminhos que marquem `paga`
> sem evento autenticado ou `ManualProvider` auditado e limitado; 0 números
> divergentes das tools no conjunto adversarial mínimo (validador de citação,
> KAM-032).»

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 3.1 | **Duplo toque → 0 pedidos duplicados** | **em branco**, com instrumento nomeado | `services/agr/tests/test_vendedor.py::test_o_duplo_toque_no_mesmo_botao_da_um_pedido_e_pede_reconfirmacao` e `test_servicos.py::test_o_duplo_toque_produz_exactamente_uma_marcacao`. Correm no *gate* 4, **verde** na execução [42222973021](https://github.com/albinoJimy/kamba-plataforma/actions/runs/42222973021). O que falta é o **duplo toque da demonstração**, no telemóvel: o critério é sobre a execução e não sobre a suite. Credor: **a demonstração** | |
| 3.2 | **Callback duplicado → 0 efeitos duplicados** | **em branco**, com instrumento nomeado | `services/agr/tests/test_regra_de_dois.py::test_cinco_entregas_dao_UM_efeito` (cinco entregas → uma mensagem ao cliente e um aviso ao dono) e `db/tests_agr/test_idempotencia.py::test_a_repeticao_nao_duplica_o_efeito_e_fecha_o_registo`, contra uma base real no *gate* 8. Credor: **a demonstração** (repetir o callback) | |
| 3.3 | **Suite de isolamento → 0 fugas entre tenants e contactos** | **satisfeito** | *Gate* 6 (isolamento de tenant) **verde** na execução [42222973021](https://github.com/albinoJimy/kamba-plataforma/actions/runs/42222973021), que corre o X-11, o passo a seco do KAM-066, a camada SQL (X-03, X-04, X-05) e os casos cruzados de `db/tests_isolamento/test_casos_cruzados.py` | 2026-11-06 |
| 3.4 | **0 caminhos que marquem `paga` sem evento autenticado** | **satisfeito, com o limite escrito** | `services/agr/tests/test_regra_de_dois.py::test_nenhum_codigo_do_AGR_marca_a_encomenda_paga`, com a mutação `aplica_transicao=True` apanhada. **O limite é do próprio KAM-039 e herda-se aqui**: a metade «pelo efeito» assere `desfecho == "aplicado"`, que é verdade com ou sem transição aplicada, pelo que medir «nenhuma transição foi aplicada» exige a base — e isso é o *gate* 8 | 2026-11-06 |
| 3.5 | `ManualProvider` **auditado e limitado** | **em branco** | `db/tests_pagamentos/test_confirmacao_manual.py` mede o tecto de valor e a reversão idempotente contra a base. O que falta é o **limite em vigor na demonstração** — qual é o valor, e quem o assinou. Credor: **fundador** (assinar um limite é L6) | |
| 3.6 | **0 números divergentes** no conjunto adversarial mínimo (KAM-032) | **em branco**, com instrumento nomeado | O validador de citação existe e está medido: **267 casos** no conjunto adversarial e 96% de cobertura do módulo `validador/` (secção de verificação do KAM-032). O que falta é correr o conjunto **sobre as respostas da demonstração**. Credor: **a demonstração** | |

---

## 4. G0-4 — Gates de CI

> «Gates 1–13 de `01_Engineering_Standards_e_Handoff.md` §4 verdes no ramo
> principal (os que existem na Fase 0); nenhum gate em *skip* sem ADR; *scan* de
> segredos limpo; nenhum dado real em nenhum ambiente.»

A tabela abaixo é a saída de `python -m gate_fase0 ci`, sobre a execução
[42222973021](https://github.com/albinoJimy/kamba-plataforma/actions/runs/42222973021)
(`fe40048`, conclusão `success`). Reproduz-se com
`gh run view 42222973021 --repo albinoJimy/kamba-plataforma --json jobs,headSha,url,conclusion`.

| Gate | O que valida | Job | Estado | Bloqueia |
|---|---|---|---|---|
| 1 | build | gate 1 — build | **verde** | sim |
| 2 | lint, format e tipos | gate 2 — lint e tipos | **verde** | sim |
| 3 | lint de referências cruzadas | gate 3 — referencias cruzadas | **verde** | sim |
| 3b | lint de nomes canónicos | gate 3b — nomes canonicos | **verde** | sim |
| 3c | lint de coerência do backlog | gate 3c — coerencia do backlog | **verde** | sim |
| 4 | unit e cobertura | gate 4 — unit e cobertura | **verde** | sim |
| 5 | integração | gate 5 — reservado (nao bloqueia) (5, KAM-003) | **vermelho (failure)** | não |
| 6 | isolamento de tenant e contacto | gate 6 — isolamento de tenant | **verde** | sim |
| 7 | contratos | gate 7 — contratos de evento | **verde** | sim |
| 8 | migrações | gate 8 — migracoes | **verde** | sim |
| 9 | segredos | gate 9 — segredos | **verde** | sim |
| 10 | SAST | — | **sem job** | não |
| 11 | SCA e licenças | gate 11 — SCA, licencas e SBOM | **verde** | sim |
| 12 | política de categorias | — | **sem job** | não |
| 13 | eval golden PT-AO | — | **sem job** | não |

**11 verdes, 1 vermelho e 3 sem *job***, nos gates do §4 que a Fase 0 alcança.

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 4.1 | Os gates do §4 **que existem** estão verdes no ramo principal | **satisfeito** | Os onze acima. O parêntesis do critério — «os que existem na Fase 0» — é o que obriga a distinguir três coisas e não duas: um gate do §4 **sem *job*** não é verde nem vermelho, e contá-lo como qualquer dos dois dá a leitura errada — a primeira dá cobertura que não existe, a segunda trava um PR por um gate que ninguém escreveu | 2026-11-06 |
| 4.2 | O **gate 5** está vermelho, e isso não é um gate avariado | **não aplicável** | Falha **por desenho** até o **KAM-003** o ligar: `tools/ci_gate_reservado.py` escreve a razão — «um job que passa porque ainda não há nada para testar faz o *pipeline* parecer que cobre o que não cobre». Corre com `continue-on-error` e não está nos `needs` do agregador, pelo que não bloqueia. **Não é um *skip***: é uma reserva declarada com o ticket no nome | 2026-11-06 |
| 4.3 | Os gates **10, 12 e 13** não têm *job* | **em branco** | Nenhum existe no `.github/workflows/ci.yaml` desta ponta. O 13 (eval golden PT-AO) é, pelo próprio §4, de «promoção de artefactos comportamentais» e não de *merge*. Credores: os tickets que os criam; **não são deste ticket** | 2026-11-06 |
| 4.4 | **Nenhum gate em *skip* sem ADR** | **satisfeito** | `ci/waivers.yaml` tem `waivers: []` — **nenhuma excepção activa**, e o ficheiro diz que existe vazio de propósito. É o único mecanismo de excepção do *pipeline* (regra transversal do §4) | 2026-11-06 |
| 4.5 | ***Scan* de segredos limpo** | **satisfeito** | *Gate* 9 **verde** na execução acima, que desde o KAM-131 corre **duas** passagens — árvore e história do PR (`docs/ci.md` §2). Declarar «gate 9 verde» a partir de metade dele é o erro que o KAM-102 registou | 2026-11-06 |
| 4.6 | **Nenhum dado real em nenhum ambiente** | **satisfeito, e é um zero de conjunto vazio** | Os três ambientes têm `dados.classe: synthetic` em `infra/envs/*/env.yaml`, e o *gate* 2 (`tools/env_lint`) recusa a passagem a `real` sem referência de decisão D1 e sem `apd_ref` (secção de verificação do KAM-075, critério 4). **E a força da barreira está escrita e é menor do que parece**: verifica a **forma** das referências, não a existência da decisão — um `decisao_d1` inventado passa, medido em revisão adversarial. O que impede dados reais de verdade é o [`GoLive_Gate.md`](GoLive_Gate.md), que é um acto humano com assinatura | 2026-11-06 |

---

## 5. G0-5 — Infraestrutura

> «KAM-075, KAM-076 e KAM-080 concluídos; Compose reduzido a correr em
> *staging*; sonda externa activa; `prod` em `kamba_data_class=synthetic`.»

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 5.1 | **KAM-075 concluído** | **não** | Fundido e **não** concluído: a sua própria secção de verificação dá **4 de 7 critérios** satisfeitos e 2 de 6 linhas de DoD, e as abertas dependem da **D1** — zero cotações pedidas, logo sem conta e sem fornecedor não há `apply`, não há cronómetro e não há cotação. Credor: **fundador** (D1) | 2026-11-06 |
| 5.2 | **KAM-076 concluído** | **não** | Fundido e **não** concluído: **3 de 8 critérios** e nenhuma linha de DoD inteira. Os cinco abertos dependem da **D6**, da **D12**, da **D1** e da inversão **KAM-078 → KAM-076**. Credores: **fundador** (D6 e D12) e **KAM-078** | 2026-11-06 |
| 5.3 | **KAM-080 concluído** | **não** | Fundido e **não** concluído: **3 marcadas** e nove vazias ou parciais, com quatro dos nove credores fora de quem executa — a licença **AGPL-3.0** do Grafana e do Loki, o portão do *lint* de cardinalidade, o canal de alertas, e a **ausência de *staging* e de produção**. Credor: **fundador** (a licença é decisão de canon) | 2026-11-06 |
| 5.4 | **Compose reduzido a correr em *staging*** | **não** | **Duas metades, e só uma existe.** O conjunto reduzido está **definido e verificado**, e re-medido aqui em `fe40048` em vez de citado: `python -m compose_prod --root .. lint` → «15 serviços no compose de produção, 15 presentes e 4 PENDENTES no manifesto», **0 achados**; e `canario` → «**45 de 45** casos a morder, a exercitar 13 de 13 regras», com a *denylist* a ler o texto todo e não só os nomes de serviço. **Os PENDENTES imprimem-se em voz alta de propósito**: um verde sobre um conjunto a que faltam serviços não é o mesmo verde. **A correr em *staging*, não**: não há *host* de *staging* porque não há fornecedor, e isso é a **D1**. O que se mediu foi uma pilha local — 637 MiB em repouso com sete contentores `healthy` —, e uma pilha local não é *staging*. Credor: **fundador** (D1) | 2026-11-06 |
| 5.5 | **Sonda externa activa** | **não — e é divergência registada** | O `../../../observabilidade.md` §1 (v1.3) diz, na tabela do que existe: «Sonda externa \| — \| **Não existe.** Não há produção — ver §5». Não é defeito do KAM-080: é o critério a pedir uma coisa que a Fase 0 deliberadamente não tem. **O fundador decidiu a 2026-11-06 que o critério não muda e a divergência fica registada** — ver §9.1 | 2026-11-06 |
| 5.6 | **`prod` em `kamba_data_class=synthetic`** | **satisfeito** | `infra/envs/prod/env.yaml` tem `dados.classe: synthetic`, `decisao_d1: null` e `apd_refs: []`, com o *gate* 2 a recusar `real` sem as duas referências e com as **duas metades testadas em separado** (KAM-075, critério 4). A etiqueta `kamba_data_class` atravessa a costura e o *lint* exige que não minta sobre a classe | 2026-11-06 |

---

## 6. G0-6 — Tempo

> «Duração real da Fase 0 registada (início → demonstração) contra o tecto de 6
> semanas; se excedido, causa e corte de **profundidade** (nunca de costuras)
> registados.»

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 6.1 | **Data de início da Fase 0** | **em branco** | **Medido: nenhuma fonte do conjunto a fixa.** Procurou-se na Carta, no `specs/INDICE.md` e no `../../00_Arquitectura_Solucao.md`; o §13.2 do `00` dá o tecto («≤ 6 semanas») e não dá o dia. As duas datas mais próximas não são o início da Fase 0 e não se usam como se fossem: a decisão do fundador do ADR-020 é de **2026-10-09**, e o primeiro *commit* da `publico/main` é de **2026-10-15** — que é a criação do espelho público. Credor: **fundador** (fixar a data de início é decisão de programa) | 2026-11-06 |
| 6.2 | **Data da demonstração** | **em branco** | Credor: **a demonstração** | |
| 6.3 | **Duração contra o tecto de 6 semanas** | **em branco** | Não se calcula sem 6.1 e 6.2. Escrever uma duração a partir de uma data inventada era o defeito que esta casa chama «feito dito sem *output* colado» | |
| 6.4 | Se excedido: causa e **corte de profundidade** registados | **em branco** | A regra está escrita e é a do `14` §3A — corta-se a **profundidade** de cada serviço, nunca as costuras —, e o ADR-020 regra 5 nomeia o que se corta primeiro: os módulos de entrada, **excepto** o Catálogo AI. Credor: **fundador** | |

---

## 7. G0-7 — Decisões externas à semana 6

> «Estado de H3 (KAM-100), H4 (KAM-101, KAM-102), D3 (KAM-041), D4 (KAM-103),
> D5, D1 e parecer P0 (KAM-104/105), cada um `confirmada`, `inconclusiva` com
> plano, ou `refutada` com pivô decidido; se H3 ou H4 falharam, a decisão de
> mudar de canal está assinada antes de arrancar o KAM-109.»

A tabela abaixo é a saída de `python -m gate_fase0 decisoes --prefixo ../../../../`,
lida do manifesto `tools/gate_fase0/decisoes.yaml`. O instrumento verifica três
invariantes que uma tabela escrita à mão não garante: que cada ponteiro existe na
árvore, que **nenhuma linha diz `confirmada` com a evidência vazia**, e que
nenhuma linha fica sem credor.

**As sete linhas estão `inconclusiva`, e as sete estão medidas.** Os tickets que
as alimentam estão todos fundidos — e é por isso que esta tabela existe: **«o
ticket fundiu» não é «a decisão está tomada»**. Cada linha transcreve o estado
que a sua própria secção de verificação declara, não uma leitura dele.

| # | Assunto | Tickets | Estado | Plano ou pivô | Evidência | Credor |
|---|---|---|---|---|---|---|
| H3 | Coexistência funciona em +244 (3/3 números sem perda de histórico) | KAM-100 | **inconclusiva** | O limiar está operacionalizado e escrito **antes** de medir (≥ 95% em 20 conversas de controlo por número, janela de 6 meses, prazo de 24 h), e a amostra é **0 de 3** números ligados. A regra de decisão das três saídas está registada no §4 do ficheiro; o pivô de `refutada` é o do `14` §6 | 1 de 7 critérios e 1 de 5 de DoD; o critério 3 declara «não satisfeito» com «0 de 3 números ligados» — [`H3_Coexistencia_244.md`](H3_Coexistencia_244.md) §3 e §6 | **fundador** (três donos de número com consentimento escrito); e a Q3/Q9 de [`Meta_Perguntas.md`](Meta_Perguntas.md), as duas em `por enviar` |
| H4 | A Meta aceita o caso de uso (resposta escrita ou aprovação) | KAM-101, KAM-102 | **inconclusiva** | As três saídas estão escritas como listas de verificação, com a ressalva de que `confirmada` pela via da aprovação de Tech Provider **não** fecha D2 nem levanta o diferimento do ADR-011. Amostra n = 0: quinze perguntas, quinze em `por enviar`, zero respondidas; e zero submissões nos seis passos do dossiê | 4 de 7 critérios no KAM-101 e 0 de 9 no KAM-102, os dois a declarar que enviar, submeter, gravar e aprovar são actos humanos — [`Meta_Perguntas.md`](Meta_Perguntas.md) §4.4 e §1.1 | **fundador** (envio em nome da empresa e submissões) e **Responsável de Produto** (registo) |
| D3 | Registo de comércio: Medusa puro / Mercur / registo próprio | KAM-041 | **inconclusiva** | O *spike* está **feito** (2026-10-27) com recomendação fundamentada — opção B, com a autoridade da reserva no `platform`. Falta a assinatura do Arquitecto de Plataforma e do Responsável de Segurança, e a ratificação do fundador. E dois bloqueantes **não se mediram** (AC-5, AC-6) e um passe indevido real ficou medido (AC-1, ISO-15 na API *Store* do Medusa), pelo que a D3 não fecha sobre eles | O *harness* sai `1`; AC-1 e AC-8 vermelhos, AC-5, AC-6, AC-9 e AC-10 não verificados, e as duas caixas de Critérios de Aceitação vazias por não haver assinaturas — [`KAM-041-medusa.md`](../../../spikes/KAM-041-medusa.md) §8 | **Arquitecto de Plataforma** e **Responsável de Segurança** (assinaturas); **fundador** (ratificação) |
| D4 | Facilitador (ProxyPay ou AppyPay) e onboarding bancário por PME | KAM-103 | **inconclusiva** | D4 registada e **não** decidida, com dono Responsável de Produto e o fundador como quem fecha. Aplicada a regra ponderada, **nenhum candidato adopta**: o melhor tem 32 de 100, e os dois melhores estão bloqueados por portões **diferentes**. Saída escrita sem contrato à semana 6: o Piloto fica em `ManualProvider`. H5 fica `inconclusiva` com amostra zero | 3 de 8 critérios e 2 de 5 de DoD; zero contrapartes contactadas, zero respostas arquivadas — [`Pagamentos_Respostas.md`](Pagamentos_Respostas.md) §5.4 e §5.2 | **fundador** (contactar bancos e facilitadores, pedir chaves) e **Responsável de Produto** (registo e fecho) |
| D5 | Tech Provider directo ou BSP | KAM-102 | **inconclusiva** | D5 fica **ABERTA** e explicitamente **não** «provisória» — o KAM-102 escreve que o seu critério 5 não autoriza esse caminho, ao contrário do que o critério 5 do KAM-105 autorizou para D9. Faltam-lhe duas cotações formais (zero pedidas, zero recebidas) e o *input* de D9 sobre quem paga em USD. O pivô do `14` §6 (BSP parceiro) tem o pré-requisito a **zero**: um pivô para uma opção sem cotação formal é um pivô para o desconhecido | Critério 5 «não satisfeito», com a matriz das três opções feita e a tabela das cotações a nascer vazia — [`Tech_Provider_Dossie.md`](Tech_Provider_Dossie.md) §6.5 | **fundador** (cotações e submissões), **Responsável de Produto** (registo e fecho), **Arquitecto de Plataforma** (redacção do ADR-001, se mudar) |
| D1 | Alojamento: Luanda desde o início ou JNB/CPT com procedimento APD | KAM-105 | **inconclusiva** | A regra do `../../09_Topologia_Operacao_Escala.md` §5.3 está em tabela e fiel à fonte (R1, R2, R3), com o bloco de decisão a nascer vazio. O que falta é o **resultado**, e lê-se das cotações: **zero pedidas**, contra um mínimo de três (≥ 2 de Luanda, ≥ 1 de JNB/CPT). A latência RTT fica `NÃO MEDIDO` pelo caminho que o próprio critério 3 prevê. A decisão é do fundador (Carta §4.2) | 5 de 8 critérios e 0 de 5 de DoD; a linha A1 do [`GoLive_Gate.md`](GoLive_Gate.md) está `em branco`, e o critério 1 declara «Vazia, estado `não satisfeito`» — [`Alojamento_Cotacoes.md`](Alojamento_Cotacoes.md) §5 e §6 | **fundador** (pedir cotações e decidir D1) |
| P0 | Parecer jurídico P0 e procedimento APD | KAM-104, KAM-105 | **inconclusiva** | O pacote está completo e verificável — quarenta perguntas com os oito campos, onze delas P0, e o anexo de factos medido em seis páginas por renderizador nomeado. O registo de respostas nasce **vazio** e a selecção também: zero propostas de honorários, nenhuma carta de compromisso assinada, pacote **não enviado**. Pelo lado do KAM-105, zero submissões à APD em catorze destinos e zero números de protocolo | 4 de 7 critérios no KAM-104, com os critérios 4, 5 e 6 declarados «não satisfeito» por serem actos humanos; e o critério 7 do KAM-105 «Vazia, estado `não satisfeito`» — [`Seleccao_e_Registo_Juridico.md`](Seleccao_e_Registo_Juridico.md) §2 e §3 | **fundador** (enviar o pacote, pedir honorários, assinar e submeter); **advogado** (parecer) |

### 7.1 A segunda metade do critério, e porque ela não se activa hoje

> «Se H3 ou H4 **falharam**, a decisão de mudar de canal está assinada antes de
> arrancar o KAM-109.»

**Não se activa**, e a razão é precisa: `inconclusiva` **não é** `refutada`. As
duas linhas estão `inconclusiva` com **amostra zero** — zero números ligados e
zero perguntas enviadas —, e tratar ausência de dados como falha dispararia uma
decisão de mudar de canal sobre um dado que ninguém mediu. É a mesma distinção
que o KAM-103 fixou por escrito para H5 e que o critério A do **KAM-110** fixa
como os três estados de uma hipótese.

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 7.1 | H3 ou H4 `refutada` → decisão de canal assinada | **não aplicável** | Nenhuma das duas está `refutada`: estão `inconclusiva` com amostra zero. A linha reactiva-se no dia em que uma delas for medida e falhar | 2026-11-06 |

### 7.2 Uma célula que fica NÃO VERIFICADO por decisão escrita

O achado do KAM-103 (§7.2 do [`Pagamentos_Respostas.md`](Pagamentos_Respostas.md))
vale aqui e não se dilui: a pergunta da **conta-mestre** da ProxyPay/AppyPay tem
**duas** leituras que a frase de `E2` §9 não distingue — uma chave de API com a
Entidade/POSID **de cada PME** e liquidação para a conta dela (o desenho A), ou a
Entidade/POSID **da KAMBÁ** a receber por todas (o desenho B, «provável
sub-adquirente, exige autorização BNA», INDÍCIO). As duas cabem na mesma frase,
pelo que **um «sim» não desambiguado é uma célula NÃO VERIFICADO e não um «sim»**.
Fica registado aqui para que o G0-7 não leia uma resposta futura como fecho de D4.

---

## 8. G0-8 — Resultado e registo

> «VERDE (G0-1 a G0-7 passam), AMARELO (G0-1 e G0-2 passam; restantes com item
> datado ≤ 2 semanas e sem trabalho da Fase 1 que dependa deles) ou VERMELHO
> (G0-1 ou G0-2 falham: não arranca trabalho de funcionalidade da Fase 1 e
> corrige-se a abstracção antes de haver terceira vertical); K1 declarado ou
> negado; Registo de Hipóteses e registo de decisões actualizados; assinatura dos
> três papéis.»

| # | Condição | Estado | Evidência ou credor | Data |
|---|---|---|---|---|
| 8.1 | **Veredicto** VERDE / AMARELO / VERMELHO | **em branco** | [`Gate_Fase0_Decisao.md`](Gate_Fase0_Decisao.md) §1, **por preencher**. Credor: **fundador**, com os três papéis | |
| 8.2 | **K1 declarado ou negado** | **em branco** | O §13.1 do `../../00_Arquitectura_Solucao.md` define K1 como «esqueleto andante: conversa real, pedido, evento, duas verticais». Credor: **fundador** | |
| 8.3 | **Registo de Hipóteses actualizado** | **em branco** | [`Registo_Hipoteses.md`](Registo_Hipoteses.md) existe com as nove linhas e o limiar, método e pivô escritos; as colunas de medição estão vazias. Credor: **a demonstração** (H3 e H4) e o **fundador** | |
| 8.4 | **Registo de decisões actualizado** (Carta §4.2) | **em branco** | Credor: **fundador** (a Carta §4.2 é o registo dos donos das decisões D, e nenhuma muda sem ele) | |
| 8.5 | **Assinatura dos três papéis** | **em branco** | Três blocos de assinatura em [`Gate_Fase0_Decisao.md`](Gate_Fase0_Decisao.md) §5, a nascer vazios. Credores: **Arquitecto de Plataforma**, **Responsável de Segurança**, **Responsável de Produto** | |

**O que a tabela do G0-8 não faz, e é deliberado: não propõe um veredicto.**
Tinha-se o material para o fazer — G0-1 com uma linha `não` medida, G0-2 com as
duas metades acima do limiar — e escrevê-lo aqui era tomar a decisão com outro
nome. O bloco diz «o veredicto é humano», e o `Gate_Fase0_Decisao.md` nasce
vazio.

---

## 9. As duas divergências medidas

Nenhuma é defeito deste ticket. As duas são do mesmo género: **o critério de um
gate a pedir uma coisa que a árvore de hoje não pode dar**, e alterar o critério
de um gate não é acto de quem o executa. **O que as separa é o estado**: a
primeira está **decidida e registada**, a segunda fica **devolvida** com três
perguntas que ninguém tomou.

### 9.1 O G0-5 pede uma sonda externa que a Fase 0 não tem — **divergência registada**

**Estado: decidida.** O fundador decidiu a **2026-11-06** que **o critério não
muda** e que esta divergência **fica registada**, com as duas citações lado a lado
e a data da medição. A linha 5.5 fica, por isso, com o estado que a evidência
sustenta — `não` — e **não** `não aplicável`: a causa está nomeada, e é isso que
o G0-8 precisa para decidir entre AMARELO e VERMELHO em vez de olhar para uma
linha aberta sem razão.

As duas citações, lido na árvore a 2026-11-06, ponta `fe40048`:

| Fonte | O que diz, à letra |
|---|---|
| `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md`, critério **G0-5** | «KAM-075, KAM-076 e KAM-080 concluídos; Compose reduzido a correr em *staging*; **sonda externa activa**; `prod` em `kamba_data_class=synthetic`» |
| `../../../observabilidade.md` §1 (v1.3), tabela «O que existe» | «Sonda externa \| — \| **Não existe.** Não há produção — ver §5» |

A segunda linha é do **KAM-080**, o ticket que o próprio G0-5 manda dar por
concluído. E o mesmo vale para a metade «Compose reduzido a correr em *staging*»
(linha 5.4): não há *host* de *staging* porque não há fornecedor, e isso é a
**D1**, que é do fundador.

**Sem produção e sem *staging*, a condição não é «ainda não fizemos»: é
insatisfazível na Fase 0 por desenho** — uma sonda que corresse dentro da rede
que observa não seria externa. Isto fica escrito como o que é, e **não se propôs
nem se propõe emenda ao critério**: medir o que lá está e escrever o que se mediu
é o que cabe a quem executa.

**A metade do critério que a divergência não contamina.** O G0-5 nomeia quatro
coisas, e só duas falham por esta razão: a **sonda externa** e o **Compose em
*staging***. A linha `prod` em `kamba_data_class=synthetic` está **satisfeita e
medida** (linha 5.6), e a conclusão dos três tickets falha por outras causas
nomeadas (linhas 5.1 a 5.3). Juntá-las todas numa só divergência apagava quatro
medições diferentes.

### 9.2 O G0-1 pede um consumo cuja acção não está escrita, e os credores nomeados já fundiram

Isto é mais do que uma divergência de leitura: é uma linha G0-n que **não pode
ficar verde correndo a demonstração**.

**O que se mediu, em `fe40048`:**

| O que | Onde | O que diz |
|---|---|---|
| A subscrição existe | `registry/servicos.yaml` | a vertical Serviços subscreve `payment.confirmed` e `payment.manual_confirmed` |
| A acção **não está escrita** | `services/agr/src/kamba_agr/eventos/handlers.py:221` | os dois pares estão em `ACCOES_POR_LIGAR`, que o comentário define como «esta vertical subscreve e a acção dela **não está escrita**»; o desfecho do consumo é `sem_accao` — contado, registado, e com credor |
| O credor nomeado no código | idem | **KAM-047** para os dois pares |
| O contrato **não admite o efeito** | `contratos/eventos/payment.manual_confirmed/v1.schema.json` e `v2.schema.json` | o `payload` tem `additionalProperties: false` e quatro propriedades (`order_id`, `valor_minor`, `currency`, `autenticacao`); **`booking_id` não é uma delas**, pelo que um evento que o leve vai para a DLQ |

**E os dois credores nomeados já fundiram.** O **KAM-047** (módulo `servicos`) tem
secção de «Verificação dos Critérios de Aceitação» no `EPIC-04` — 6 de 8
critérios —, o **KAM-035** (grafo de Serviços) também, e o **KAM-007** (catálogo
de eventos) também. O KAM-039 já tinha medido a segunda metade disto na sua linha
(b) e nomeado os dois credores; o que esta medição acrescenta é que **ambos
fecharam e a acção continua por escrever**, pelo que a linha não tem credor vivo.

**Porque é que não se corrige aqui.** O bloco KAM-108 diz por extenso: «não
expandas escopo: corrigir falhas encontradas é ticket novo». Escrever a acção da
vertical Serviços é implementação noutro componente; e admitir `booking_id` no
*payload* é **alterar um contrato de evento publicado**, que é canon de nível 4 e
8 e muda a compatibilidade que o `contract_diff` verifica **dentro do *gate* 7**.
O número do portão é mesmo o 7, e vale dizê-lo por extenso porque ele tem duas
metades e confundi-las é fácil: o `specs/01_Engineering_Standards_e_Handoff.md`
§4 dá ao 7 «webhooks Meta (simulador, KAM-024), callbacks do facilitador,
schemas de eventos (**compatibilidade**, KAM-007)», e o alvo `ci-7` do
`Makefile` corre as **duas** — `contract_diff check` **e** o `ci-7-meta`, que é
o varrimento de números deste mesmo gate.

**O que fica devolvido, em três perguntas separadas:**

1. **Abrir o ticket** que escreve a acção do consumo na vertical Serviços (o
   lembrete ou a marcação a partir do evento de pagamento), e actualizar o credor
   do `ACCOES_POR_LIGAR`, que hoje aponta para um ticket fechado.
2. **Decidir por onde vem o `booking_id`**: emendar o contrato (versão nova, com
   o custo de compatibilidade), ou o consumidor resolver a marcação por consulta
   em vez de o evento a transportar. É desenho, e toca o ADR-009 e o KAM-007.
3. **Decidir o que a linha 1.6 faz ao veredicto** do G0-8. Lida à letra, o G0-1
   não passa, e «G0-1 falha» é VERMELHO — que significa «não arranca trabalho de
   funcionalidade da Fase 1 e corrige-se a abstracção antes de haver terceira
   vertical». Isto **não se decide aqui**.

---

## 10. O que este documento não é

- **Não é o veredicto.** O veredicto é o [`Gate_Fase0_Decisao.md`](Gate_Fase0_Decisao.md), e nasce por preencher.
- **Não é uma medição da demonstração.** Nenhuma linha diz que a conversa real correu, porque não correu.
- **Não está ligado a portão nenhum.** Nada neste ficheiro trava uma fusão; ligá-lo a um *job* acrescentaria um contexto exigido ao *ruleset* da `main`, e isso é alteração de regra de bloqueio — decisão do fundador. O precedente está escrito no KAM-039 e no KAM-180.
- **Não substitui o [`GoLive_Gate.md`](GoLive_Gate.md).** Esse mede a entrada de **dados reais em produção**; este mede se a Fase 0 está verde. As duas condições são independentes, e nenhuma implica a outra.

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-108): a checklist G0-1 a G0-8 com estado, evidência nomeada ou credor por linha, medida em `fe40048`. **Nenhuma linha G0-n satisfeita**, e as satisfeitas são sub-condições: o instrumento do traço, o cenário, a métrica de reaproveitamento (88,30% e `fluxo 0`), os onze gates verdes do §4, a ausência de excepções em `ci/waivers.yaml`, o isolamento, e os três ambientes em `synthetic`. Duas divergências medidas devolvidas ao fundador: o G0-5 pede uma sonda externa que o `observabilidade.md` §1 declara não existir, e o G0-1 pede um consumo cuja acção **não está escrita** no `ACCOES_POR_LIGAR` e cujo efeito o contrato publicado não admite — com os dois credores nomeados no código já fundidos. | Equipa KAMBÁ |
