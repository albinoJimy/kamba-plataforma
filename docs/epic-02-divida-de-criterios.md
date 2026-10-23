# EPIC-02 — as caixas vazias dos tickets fundidos, por credor

| Campo | Valor |
|---|---|
| Âmbito | As caixas de critério e de *DoD* que ficam vazias nos tickets **fundidos** do `../specs/EPIC-02_Canais_WhatsApp_Handoff.md` |
| Medido em | 2026-10-23, sobre `publico/main` mais a auditoria dos critérios de saída (emendas 1.10 a 1.12 do epic) |
| Fonte de cada linha | A tabela de «Verificação dos Critérios de Aceitação» do **próprio bloco**. Este documento lê-a; não a reavalia |
| O que não é | Uma reavaliação dos vereditos. Não marca nem desmarca caixa nenhuma. Ver §5 |
| Estado | Vivo — quem fechar uma caixa risca a linha no mesmo PR |

## 1. Porque é que isto existe

A auditoria dos critérios de saída do epic contou **71** caixas vazias nos treze
blocos. Lidas assim, não dizem nada: uma caixa vazia por falta de um número de
telefone angolano da Meta é um problema completamente diferente de uma caixa
vazia porque o critério pede uma coisa que não se deve fazer.

Separadas, são quatro populações, e três delas não precisam de inventário:

| População | Caixas | Porque não entra aqui |
|---|---|---|
| Revisores humanos | 13 | Vazias por decisão escrita do fundador: nesta fase não há revisores, e a caixa fica vazia **como facto registado**. Uma por bloco |
| «Todos os CA satisfeitos» | 12 | Derivada: fecha sozinha no dia em que o seu bloco fechar |
| KAM-115 | 14 | O ticket não arrancou, e espera o KAM-116 (agregador de SMS, EPIC-09). Não é dívida de execução, é trabalho por fazer |
| **Os tickets fundidos** | **32** | **É isto que este documento inventaria** |

Destas 32, **nenhuma é trabalho esquecido.** Cada uma tem a razão escrita na
secção de verificação do seu bloco — o que falta à letra, e porquê. O que
faltava era a leitura transversal: **quem é o credor de cada uma**, e quantas
caixas cada credor desbloqueia.

## 2. O achado: cinco caixas esperam um ticket que já fundiu

É a razão pela qual este documento não é uma lista de espera. Cinco das 32
ficaram vazias porque o ticket de que dependiam **não existia no dia em que o
seu PR fundiu** — e entretanto fundiu também. Ninguém voltou atrás a medir.

| Caixa | O que a tabela do bloco diz | Credor | Hoje |
|---|---|---|---|
| KAM-024, critério 5 | «a segunda metade — *usado por KAM-015, 016, 017 e 020* — **não se pode medir**: nenhum desses quatro tickets existe» | KAM-015, KAM-016, KAM-017, KAM-020 | **os quatro fundidos** |
| KAM-018, critério 1 | «a **detecção** precisa de `smb_message_echoes`, que é KAM-017» | KAM-017 | **fundido** |
| KAM-015, critério 8 | «*sob o lock da conversa*. **Não há *lock*** — o `conversations.mode` e as suas transições são o KAM-018» | KAM-018 | **fundido** |
| KAM-018, critério 6 | o tipo do catálogo é do KAM-007; a carga precisa de uma `v3`; o «≤ 5 s em HND» precisa do `setBotMuted` do KAM-019 | KAM-007, KAM-019 | **fundidos** |
| KAM-014, critério 3 | «a contagem por contacto é de quem envia […], o envio é KAM-015, e a coluna que contaria esse limite não existe» | KAM-015 | **fundido**, e a coluna continua a não existir |

**Isto é a mesma classe de omissão que a auditoria do §2 encontrou**, um nível
abaixo: ninguém volta atrás a reavaliar uma caixa quando a condição que a
bloqueava deixa de valer. A diferença entre esta e as outras vinte e sete é que
estas **fecham-se com trabalho aqui** — nada externo as bloqueia.

**O que fechá-las custa, honestamente,** porque «o credor chegou» não é «a caixa
fecha»: duas são medições (o KAM-024 critério 5 e o KAM-018 critério 1), uma é
ligar o guarda ao *lock* que agora existe (KAM-015 critério 8), uma pede uma
`v3` de contrato com compatibilidade a provar no *gate* 7 (KAM-018 critério 6), e
uma pede uma coluna que ninguém criou (KAM-014 critério 3). São cinco tarefas de
tamanhos muito diferentes.

## 3. As 32 caixas, uma a uma

As classes, e a tabela usa-as na última coluna:

| Classe | Significado |
|---|---|
| **terceiro** | A Meta, `ext:KAM-100`, `ext:KAM-102`, ou tempo de calendário. Nada daqui a destranca |
| **ticket** | Espera um ticket que **não** está fundido. O ticket vem nomeado |
| **credor chegou** | O ticket que ela esperava está fundido. Fecha-se com trabalho aqui — ver §2 |
| **divergência** | O critério pede X à letra e entregou-se Y, melhor ou mais estreito, com a dívida documental nomeada. Fechá-la é reescrever o critério, não mudar código |
| **devolvida** | O critério pede algo que não se deve fazer, ou cuja leitura foi devolvida a quem o escreveu |
| **sem credor** | A tabela do bloco não nomeia ninguém. É informação: é uma caixa que ninguém sabe quem fecha |

### KAM-013 — GWY

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 6 | JSON inválido: 200 e quarentena com retenção de 7 dias **+ alerta** | O 200 e a linha em `unrouted_events` estão provados. A retenção de 7 dias **não é imposta** (não há agendador) e **não há alerta** (não há sistema de alertas no repositório) | KAM-071 (agendador), KAM-079 e KAM-080 (alertas) | ticket |
| 7 | Carga 200 req/s × 60 s; p99 < 500 ms; descarte de estados **não facturáveis** | Os números cumprem-se (p99 **199 ms**). Diverge a **regra do descarte**: o campo que diz se um estado é facturável está NÃO VERIFICADO no `E1` §5, e a regra que corre — um estado que traga `pricing` não se descarta — é um subconjunto da letra | quem escreveu o critério; a leitura do `pricing` em `statuses[]` depende da Meta | devolvida |

### KAM-014 — CHR

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 3 | Matriz de estados testada por linha | As seis linhas e as trinta combinações estão testadas. Falta «`suspenso` … responde **1 vez por contacto/24 h**»: o CHR responde «pode», não «quantas vezes», e a coluna que contaria o limite não existe | KAM-015 (**fundido**) mais uma coluna que ninguém criou | credor chegou |
| 4 | `wa_id` e BSUID convergem no mesmo `contact_id` | A fusão emite uma vez em dez repetições, provado. A convergência de uma mensagem **só** com BSUID com uma **só** com telefone **não é satisfazível** pelo algoritmo do `tecnica/01` §6.3, que é o que o KAM-008 implementa: cada uma cria o seu contacto, e nada as liga antes da primeira que traga os dois | quem escreveu o critério | devolvida |
| 6 | O *job* cumpre `packages/contracts/agent_invocation.schema.json` | A substância cumpre-se nos dois sentidos, sem telefone, BSUID nem `display_name`. **O caminho é outro**: os esquemas do pacote vivem em `schemas/` com a versão no nome | — (reescrever o caminho no critério) | divergência |

### KAM-015 — Outbound

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 4 | `pricing` por mensagem; um *service* acima do *free tier* incrementa `meta_cost_usd_total{tenant}` | Tudo se cumpre excepto **a etiqueta `{tenant}`**: as bibliotecas de métricas da casa recusam por gramática uma etiqueta fora de `^[a-z][a-z0-9_]{1,62}$`, e um identificador de *tenant* é um UUID com hífenes — a chamada levanta. O por-*tenant* sai da consulta | — (a divergência está assumida na emenda 1.21 do epic) | divergência |
| 6 | `130429` 3× e depois 200; Meta indisponível: fila com *backoff* e ordem por conversa; expiração em 24 h com aviso ao dono | A primeira frase cumpre-se à letra. **Não há fila** entregue aqui, e a expiração em 24 h **com aviso ao dono** é o KAM-115 | KAM-115, mais uma fila | ticket |
| 8 | `PreSendGuard` **sob o *lock* da conversa** antes de cada envio do bot | A segunda metade cumpre-se nos dois ambientes: sem guarda, o envio do bot levanta em CI e recusa fora dela, e **nenhum dos dois envia**. Falta o «sob o *lock*» | KAM-018 (**fundido**) | credor chegou |
| DoD | Custo e observabilidade: `meta_cost_usd_total{tenant}`, `outbound_latency_ms`, `outbound_window_closed_total` | As cinco métricas existem desde o código. A etiqueta `{tenant}` não entra, pela razão do critério 4 | — (mesma divergência) | divergência |

### KAM-016 — Embedded Signup v4

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 9 | 1 onboarding ES v4 real numa conta de teste da Meta, com evidência | Tudo: não há conta de teste nem `docs/evidencia/KAM-016.md`, e não se inventou nenhum | `ext:KAM-102` (Business Verification, App Review, Tech Provider) | terceiro |

### KAM-017 — Coexistência

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 6 | Aviso preventivo aos 10 dias sem *echo* **e sem acesso ao painel** | A metade do *echo* mede-se e entrega-se inteira, idempotente e com a janela a reabrir com actividade do dono. **O painel não existe** e não há sinal de acesso em sítio nenhum do esquema | KAM-093 (o painel); dívida documental 84 | ticket |
| 10 | Evidência da elegibilidade: ≥ 1 sincronização num +244 real | Tudo. A lógica dos dois modos está entregue; falta o relatório | `ext:KAM-100` | terceiro |
| DoD | O resultado de KAM-100 está referenciado e o modo predefinido decidido | O valor por omissão. Escolhê-lo aqui era decidir pelo relatório que não existe | `ext:KAM-100` | terceiro |

### KAM-018 — Modos da conversa

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 1 | A tabela de transições, e qualquer outra rejeitada | As **32** células são afirmadas uma a uma, contra uma tabela escrita à mão e não derivada da implementação, e o complemento prova a rejeição. Falta a **detecção** do `bot→dono` por *echo*: nas baterias o gatilho é disparado pelo ensaio | KAM-017 (**fundido**) | credor chegou |
| 6 | Cada mudança emite `conversation.mode_changed` e actualiza o HND em ≤ 5 s | A emissão cumpre-se, na mesma transacção da escrita do modo, e uma corrida perdida não emite. Faltam três: o tipo **já estava** no catálogo (dívida 80); a carga tem `channel_mode` de três valores e os modos são **quatro**, pelo que `dono` e `humano` saem indistinguíveis e uma `v3` é quebra de contrato; e o «≤ 5 s em HND» precisa de ligar o `setBotMuted` | KAM-007 (a `v3`) e KAM-019 (o provedor), **ambos fundidos** | credor chegou |
| 8 | Métrica `echo_latency_ms` com p50/p95 de ≥ 30 *echoes* reais em *staging* | Tudo. Declará-la a zero era pior: um painel a mostrar zero diz «a latência é nula» quando ninguém a mede | `ext:KAM-100` | terceiro |
| DoD | Custo e observabilidade: três métricas | Duas das três existem com bateria própria, mais uma quarta que o DoD não nomeia. Falta a `echo_latency_ms`, pela razão do critério 8 | `ext:KAM-100` | terceiro |

### KAM-019 — HND e Chatwoot

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 3 | `mirrorMessage` idempotente por `wamid`: 3 chamadas dão 1 mensagem **no Chatwoot** | A de-duplicação está provada — três chamadas deixam uma entrada na fila, e quem de-duplica é o `jobId`, que **é** o `wamid`. Não há consumidor da fila, pelo que nenhuma mensagem chega lá | KAM-025 | ticket |
| 4 | `openHandoff` idempotente; 5 chamadas concorrentes dão 1 conversa, passada a `open`, atribuída à equipa, com nota privada | Quatro das cinco partes cumprem-se, contra a base e em duas ligações. Faltam: «procura a conversa por atributo `handoffId`» — o atributo é **escrito** e nada o procura, porque o cliente do provedor não tem operação de leitura — e «atribuída à equipa», porque **não existe equipa** em documento, dicionário ou código (dívida 60) | **ninguém**: a leitura fecha-se neste módulo; a equipa é uma decisão devolvida | sem credor |
| 6 | A resposta humana sai pelo Outbound, com custo registado; janela fechada avisa e propõe template | A costura está feita com um `Saida` verdadeiro, e sem identificador de mensagem não se envia. «Custo registado» não tem asserção (delega-se por escrito no Outbound), e «template se fechada» **propõe-se e não se envia** — decisão escrita: é pago, e a decisão de gastar é da PME | quem escreveu o critério | devolvida |
| 9 | Chatwoot indisponível: fila com *retry*, espelho reconcilia, *healthcheck* **alerta** | Tudo menos o alerta: a passagem fica `degraded`, a linha fica, a métrica conta, e `degraded` conta no SLA. A grandeza está medida e **nada a lê**: não há painel nem regra de alerta. Expor uma métrica não é alertar | KAM-084 e KAM-085 | ticket |
| 10 | Teste X-10: o agente da conta A não lê conversas da conta B (API) | O isolamento está provado **como X-03**, sobre as nossas tabelas, e as duas `UNIQUE` recusam a mesma conta e o mesmo utilizador do provedor em dois *tenants* — mas isso é outra afirmação, e ninguém exercitou a API do provedor com o *token* de uma conta contra as conversas de outra. O registo que hospedaria o X-10 não existe em código. E os *tokens* **não são «cifrados por tenant»**: são referências opacas, que é o desenho do KAM-010, mais forte e **diferente** do que o critério diz | KAM-066 (o registo do X-10); a segunda metade é divergência | ticket |
| DoD | Sem segredos; dependências por digest, **sem `enterprise/`** | Duas das três medidas: os *tokens* vão para o cofre por porta com teste, e as imagens estão fixadas por digest. O «sem `enterprise/`» **não está medido**, e o que o mediria não existe: o ticket cita um «gate de licenças EE» que **não é um gate** | **ninguém**: o gate citado não existe | sem credor |

### KAM-020 — Mídia

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 1 | 1 objecto em `t/{tenant_id}/media/{classe}/…` e 1 linha em `media_assets` | A linha e o objecto cumprem-se, com as onze colunas e mais três. **A chave não é a do critério**: ele escreve um segmento `media/` a mais, que a porta do KAM-011 recusa — ela aceita um segmento só. Resolveu-se **pela classe e não pela porta** (`media_audio`), e o KAM-011 não se tocou, porque está feito nas duas linguagens e tem o X-08 na sua bateria de contrato | — (dívida documental 8, registada antes deste ticket) | divergência |

### KAM-021 — Qualidade e limites

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 3 | No Piloto, `tenants.estado` projecta `restrito` e volta a `ativo` com o canal | **Não se faz, e a razão é de segurança.** A revisão `0007` retirou o `UPDATE (estado)` em `platform.tenants` a `kamba_app` **de propósito** — «o sujeito da condição não pode ser quem a retira» — e há teste a prendê-lo. Devolver o privilégio reabria a escalada que a revisão adversarial do KAM-009 fechou, e o que se ganhava era uma coluna derivada de outra que já está escrita | quem escreveu o critério; dívida 70 | devolvida |

### KAM-023 — *Free tier*

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 3 | Aviso aos 800 e aos 1.000; reinício à meia-noite **do fuso configurado do canal** | Os avisos estão medidos pela travessia, e a fronteira é a de `Africa/Luanda`. **Não há fuso por canal**: a única coluna de fuso do esquema é por *tenant*, e um *tenant* com dois números não pode hoje ter dois fusos. Criá-la é DDL | **ninguém**: dívida 64, sem ticket que a tome | sem credor |
| 4 | Custo estimado, exposto como `meta_free_tier_used_ratio{tenant}` e `meta_cost_usd_estimate{tenant}` | A aritmética cumpre-se e o limiar de aviso é **derivado** do tecto. As duas métricas existem; **a etiqueta de *tenant* não**, pela mesma razão do KAM-015 critério 4 — e decidir ao contrário a dois módulos de distância punha o conjunto a contradizer-se | — (mesma divergência) | divergência |
| 7 | Reconciliação ao fim de **1 mês real**: divergência ≤ 2% | O instrumento está entregue e provado contra `jsonb` real. Falta o mês: **é critério de saída e não de PR**, e marcá-lo com um ensaio sintético era marcar um critério de saída com dados que não são do mundo | um mês de Piloto a facturar | terceiro |

### KAM-024 — Simulador

| # | Critério | O que falta à letra | Credor | Classe |
|---|---|---|---|---|
| 5 | Servidor Graph falso, «usado por KAM-015, 016, 017 e 020» | A primeira metade está feita e medida: os oito cenários, com 27 testes verdes, dois deles sobre TCP real. A segunda não se podia medir porque nenhum dos quatro tickets existia | KAM-015, KAM-016, KAM-017 e KAM-020, **os quatro fundidos** | credor chegou |
| 7 | Captura e saneamento; recusa; «0 telefones reais (*scan*)» | As duas primeiras cláusulas estão medidas, incluindo que o `wamid` novo não leva o número real dentro do base64. A terceira tem **duas leituras opostas**: «0 cadeias com a forma de um número angolano» é insatisfazível, e satisfazê-la **pioraria** a protecção (um redactor testado só com números fictícios nunca prova que apanha um real); «0 números que pertençam a uma pessoa real» é o que o DoD quer dizer e não se prova por expressão regular. Entregou-se um **raquete** — um inventário com uma entrada, a contagem exacta e a razão por ficheiro, que falha nos quatro sentidos em que uma pasta isenta não falharia | quem escreveu o critério | devolvida |
| 8 | *Suite* offline no *gate* 7 em ≤ 5 min; *suite* online nocturna com relatório | A offline está feita e leva 24 s contra os ≤ 5 min. A **online não existe**: precisa do número de teste da app Meta de *staging* | `ext:KAM-102` | terceiro |
| 9 | A *suite* online não bloqueia PR mas é de *release*; a falha gera alerta | Tudo, pela razão do critério 8. Escrever uma que se desligasse sozinha por falta de credenciais era construir o falso verde que o próprio critério proíbe por extenso. As duas regras já decididas ficam escritas em `meta-sim.md` §9 | `ext:KAM-102` | terceiro |

## 4. Resumo por credor

Responde à pergunta útil: **se este credor chegar amanhã, quantas caixas fecham?**

| Credor | Caixas | Quais |
|---|---|---|
| **Trabalho aqui — o credor já chegou** | **5** | KAM-014 crit. 3, KAM-015 crit. 8, KAM-018 crit. 1 e 6, KAM-024 crit. 5 |
| `ext:KAM-100` — *spike* de coexistência | 4 | KAM-017 crit. 10 e DoD, KAM-018 crit. 8 e DoD |
| `ext:KAM-102` — Business Verification e Tech Provider | 3 | KAM-016 crit. 9, KAM-024 crit. 8 e 9 |
| Reescrever o critério (divergência assumida) | 5 | KAM-014 crit. 6, KAM-015 crit. 4 e DoD, KAM-020 crit. 1, KAM-023 crit. 4 |
| Decisão devolvida a quem escreveu o critério | 5 | KAM-013 crit. 7, KAM-014 crit. 4, KAM-019 crit. 6, KAM-021 crit. 3, KAM-024 crit. 7 |
| **Sem credor nomeado** | **3** | KAM-019 crit. 4 e DoD, KAM-023 crit. 3 |
| KAM-084 e KAM-085 — painéis e alertas | 1 | KAM-019 crit. 9 |
| KAM-071, KAM-079 e KAM-080 — agendador e alertas | 1 | KAM-013 crit. 6 |
| KAM-025 — consumidor da fila do espelho | 1 | KAM-019 crit. 3 |
| KAM-066 — o registo que hospeda o X-10 | 1 | KAM-019 crit. 10 |
| KAM-093 — o painel da PME | 1 | KAM-017 crit. 6 |
| KAM-115 — aviso ao dono por canal alternativo | 1 | KAM-015 crit. 6 |
| Um mês de Piloto a facturar | 1 | KAM-023 crit. 7 |

O que esta tabela mostra, e que as 32 linhas soltas não mostravam:

1. **Só sete caixas esperam genuinamente um terceiro** — as quatro do
   `ext:KAM-100` e as três do `ext:KAM-102` —, mais uma que espera tempo de
   calendário. A Meta não é o gargalo que a contagem de caixas vazias sugeria.
2. **Dez são decisões, não trabalho**: cinco divergências assumidas e cinco
   leituras devolvidas. Fechá-las é reescrever um critério ou ratificar uma
   decisão, e **duas delas não devem fechar** — a do KAM-021 porque devolver o
   privilégio reabre uma escalada, e a do KAM-024 porque satisfazer a letra
   pioraria a protecção que ela existe para dar.
3. **Cinco fecham-se já**, e são a dívida real deste epic (§2).
4. **Três não têm credor** e é isso que as torna perigosas: ninguém as reclama,
   e por isso ninguém as fecha. Duas são do KAM-019 e uma do KAM-023.

## 5. O que este documento não é

- **Não é uma reavaliação dos vereditos.** Cada linha lê a tabela de verificação
  do bloco e resume o que ela diz. Onde a tabela não nomeia um credor, escreve-se
  «sem credor nomeado» em vez de se inventar um.
- **Não marca nem desmarca caixa nenhuma.** As caixas dos treze blocos ficam como
  a auditoria dos critérios de saída as deixou.
- **Não corrige nada nas secções de verificação.** Elas medem o que era verdade
  no dia em que correram, e corrigi-las falsearia o registo — é a mesma razão
  pela qual o `lint_contagens` não as lê.
- **Não é um plano.** Diz quem deve a quem; não diz por que ordem se paga, nem
  se se paga.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: as 32 caixas vazias dos tickets fundidos do EPIC-02, com a razão de cada uma e o seu credor, e o resumo por credor. O achado do §2 — cinco caixas esperam um ticket que já fundiu — saiu de confrontar o credor que cada tabela de verificação nomeia com o que está hoje em `publico/main`. | Equipa KAMBÁ |
