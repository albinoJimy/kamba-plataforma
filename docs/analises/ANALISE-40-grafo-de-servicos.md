# ANÁLISE 40 — KAM-035, grafo de Serviços: revisão adversarial e hipóteses

| Campo | Valor |
|---|---|
| Ticket | KAM-035 — Grafo de Serviços: slots, disponibilidade e `book_slot` |
| Base medida | `refs/remotes/publico/main` em `eafa2ca` |
| Instrumento | subagente `general-purpose`, read-only, sem acesso ao raciocínio do autor |
| Achados levantados | 22 |
| `CONFIRMADO` | 22 |
| `PLAUSÍVEL` | 0 |
| `MORTO` | 0 |
| Corridos depois da correcção | 1 271 ensaios do AGR, 0 falhas |

## O que esta análise é, e o que não é

É o registo da **uma** revisão adversarial deste ticket — a decisão do fundador
de Outubro de 2026 fixa uma por ticket, sem segundas leituras. O revisor recebeu
o diff e os requisitos e **não** recebeu as justificações do autor; o guião
mandava-o procurar razões para o resultado estar errado, não confirmar que
estava certo.

**A árvore mexeu-se a meio da revisão, e isso está registado porque muda o que
os achados valem.** O revisor notou-o, exportou o índice (`git archive $(git
write-tree)`) para fora do repositório e correu tudo contra esse instantâneo —
em vez de medir uma árvore e reportar outra. Pela regra da casa, cada
`CONFIRMADO` foi **verificado outra vez** contra a árvore que vai fundir; dois
dos vinte e dois já estavam corrigidos quando a revisão respondeu, e estão
assinalados.

## Calibração

Vinte e dois achados levantados e vinte e dois confirmados é uma calibração de
**1,00**, e o número é `INDÍCIO` e não `CONFIRMADO`: lê-se à mão desta análise
contra o PR, e este repositório não tem instrumento que o derive — é a lacuna
que a própria `software-factory` nomeia no §3. O que a sustenta é cada achado
trazer um cenário de falha reproduzido, e não uma opinião.

## Os achados, por severidade

### Críticos — seis, e cinco eram a mesma classe

| # | Achado | Estado | Onde se fechou |
|---|---|---|---|
| 1 | As `ofertas` são reiniciadas em cada turno, pelo que o slot `servico` nunca se preenchia | **corrigido antes da resposta** | `_servicos_vistos`: o catálogo vem da tool `list_services` e guarda-se nos `slots`, que atravessam turnos |
| 2 | O `classify` não honra a pergunta pendente: «amanhã» caía em `outro` → `safe_reply` | corrigido | `classify` herda `slots.intencao` quando nenhuma regra decide e há pergunta no ecrã |
| 3 | O `stage` ficou no `estado_inicial`: `awaiting_confirm` não atravessava o turno e **toda** a confirmação saía `stale` | corrigido | `stage` sai do `estado_inicial` e nasce no `ingest`; vale para as **duas** verticais |
| 4 | O *hold* nunca se tomava: o nó pedia o dia inteiro e o backend só o emite para um intervalo | **corrigido antes da resposta** | `_intervalo_de` estreita à hora quando ela é conhecida; os dois caminhos do critério 4 ficam ambos vivos |
| 5 | `cancel_booking` devolvia sempre `VALIDATION_ERROR`: nenhum caminho emitia o botão que o passo 4 exige | corrigido | aresta 43 (`confirm_gate --> cancel_booking`, `fonte` §6.2) e fluxo de dois turnos no nó |
| 6 | O botão citava `hold_id` e o `reschedule_booking` cita `booking_id` — remarcação sempre recusada | corrigido | `referencia_a_confirmar`, com **um** dono para as três escritas |

**A classe comum dos achados 1, 3 e 4 é a mais importante desta análise.** O
diff tinha tirado o `slots` do `estado_inicial` com a razão escrita e medida, e
deixado lá as `ofertas` e o `stage` — isto é, o autor corrigiu **uma** instância
de um defeito que tinha três, e a razão que escreveu aplicava-se às três. É o
padrão que o KAM-114 já tinha pago para o `turn_seq`:

> Toda a chave que nasça no `estado_inicial` sobrescreve a do *checkpoint*,
> porque o `turno.py` chama aquela função em cada turno e passa o resultado ao
> `ainvoke`.

O portão que fecha isto é o ensaio
`test_tres_chaves_do_estado_nao_nascem_no_estado_inicial`, que afirma o conjunto
exacto das três e falha se uma quarta entrar ou sair sem decisão.

### Altos — cinco

| # | Achado | Estado | Onde se fechou |
|---|---|---|---|
| 7 | `slots.hora_candidatas` era escrito e nunca lido: «de tarde» não resolvia a desambiguação e entrava em ciclo | corrigido | `resolver_candidatas`, e não é palpite — é aplicar a resposta às duas leituras já guardadas |
| 8 | `remarcar` sem referência caía no ramo da marcação nova: o cliente ficava com **duas** | corrigido | `classify` já não escreve `True`; o `r_slots` e o `slots_collect` barram, com `REFERENCIA_EM_FALTA` |
| 9 | A *docstring* do `confirm_gate` afirmava três barreiras e a segunda não se aplica: dois toques são dois `turn_id`, logo duas chaves | corrigido | a nota passou a nomear as barreiras que existem; a que serializa é a restrição de exclusão da `0025` |
| 10 | O `safe_reply` do Vendedor dizia ao cliente de um salão que a loja só trata de «produtos, preços e pedidos» | corrigido | `safe_reply` e `ask_repeat` próprios; o reuso passa de catorze nós a **doze** |
| 11 | `LIMIT_EXCEEDED` saía com uma frase e **sem** botão: «um colega pode ajudar» não é uma oferta de handoff | corrigido | `AVISOS_QUE_OFERECEM_HUMANO` emite o botão; um `SLOT_TAKEN` não o emite, de propósito |

**O achado 10 custou dois nós na contagem de reuso, e é a correcção mais
desconfortável desta análise:** o número que prova a regra de dois (ADR-012)
estava a contar como mérito dois nós cuja reutilização era um defeito. Um
indicador que premeia o que está errado é pior do que não ter indicador.

### Médios — onze

| # | Achado | Estado |
|---|---|---|
| 12 | Um cancelamento bem-sucedido dizia «a sua marcação ficou registada» (decidia-se pela presença do `booking_id`) | corrigido: decide-se pelo `estado` |
| 13 | A confirmação não citava instante nenhum, e o `fact_id` guardado «para o `compose` citar» nunca era citado | corrigido: a tool devolve o *fact* `datetime` e o `compose` cita todo o que este turno trouxe |
| 14 | `SEM_DISPONIBILIDADE` com zero opções apontava para uma lista vazia | corrigido: `SEM_VAGA_NENHUMA`, com frase própria |
| 15 | O ponto como separador de horas lia ordinais, milhares e datas como horas — e «dia 20. às 10h» dava **20h00** | corrigido: o ponto sai do padrão; seis casos no ensaio |
| 16 | «às 5 e meia da tarde» dava 17h00 — a meia hora desaparecia em silêncio | corrigido: `_FRACCOES` |
| 17 | O `estado.py` citava esta análise, que não existia | corrigido: é este ficheiro |
| 18 | Seis declarações de «fica em `docs/dividas-documentais.md`» e o diff não tocava no ficheiro | corrigido: dívidas **140** a **147** |
| 19 | Nenhum comentário `shortcut:` nos ficheiros novos, com três atalhos declarados em prosa | corrigido: três, com tecto e gatilho |
| 20 | O cabeçalho do `estado.py` dizia que todas as chaves do §5.3 estavam na tabela | corrigido |
| 21 | A bateria do autor não passava: 16 de 86 vermelhos | corrigido: 104 ensaios verdes, 1 266 na suite |
| 22 | A bateria não estava em *staging* — o PR não trazia teste nenhum | corrigido |

**Dois dos vermelhos do achado 21 eram defeito de ensaio e não de código**, e o
revisor viu-o: o `invocacao_crua` do `apoio.py` gera um `contact_id` novo em cada
chamada, pelo que uma *fixture* montada com um `estado_de()` e exercitada com
outro punha a marcação num contacto e o pedido noutro — a tool respondia
`NOT_FOUND` com razão, e o critério parecia falhar por código. O portão é a
classe `Conversa`, que fixa o contacto e varia só o `wamid`.

### Um achado que a revisão não encontrou, e o ensaio dela encontrou

O cabeçalho do `datas.py` escrevia que «uma hora com marca nunca é ambígua — quem
escreve `17h` não escreveu `5`», e o código **não cumpria a própria frase**:
mandava `10h` pela regra do 1 a 12 e devolvia as duas candidatas. O efeito era o
pior possível para o critério 3 — a desambiguação a disparar no caso em que não
há nada para desambiguar.

Não foi a revisão que o apanhou: foi o ensaio **do achado 15**, que precisava de
ler «às 10h» no meio de uma frase com um ordinal. Os casos da tabela de horas
usavam todos `14h` ou mais, pelo que a regra errada nunca se via. Fica escrito
porque é a lição de sempre — **uma tabela de casos só mede o que lhe põem** —, e
porque é a melhor prova de que corrigir um achado com um ensaio paga mais do que
corrigi-lo sem.

## Dois achados que esta revisão NÃO viu, e de onde vieram

Chegaram **depois de o PR abrir**, por nota da sessão do KAM-047, e são os dois
da mesma classe — a que o criterio 3 do KAM-027 já tinha escrito por extenso:
«esse teste contra um objecto inventado prova que o nosso `nos_do_grafo` lê o
nosso próprio duplo».

| Achado | Medido |
|---|---|
| O `check_availability` lia `opcao["minutos_em_luanda"]`, e o `Opcao` do contrato **não tem** esse campo (`slotId`, `serviceId`, `resourceId`, `inicioAt`, `fimAt`) | O nó compilava contra o *fake*, que o inventava. O minuto passa a derivar-se do `inicio_at` |
| O `Marcacao.holdExpiresAt` é `string \| null` e o duplo devolvia um `float` | O `float()` do nó **levanta** `ValueError` sobre `"2026-11-16T13:40:00Z"`. Passava na bateria porque o duplo facilitava |

**Porque é que a revisão não os viu, e isso é a parte útil:** ela recebeu o diff
e mediu o que o diff faz — e o diff é coerente **consigo mesmo**. O que faltava
era confrontá-lo com um ficheiro que o diff não toca, noutro serviço e noutra
linguagem. Nem o guião da revisão nem a bateria o pediam.

O portão é a família `TestContratoDoModuloServicos`, e a forma importa: lê o
`contrato.ts` e converte `camelCase` para `snake_case` na fronteira da tool, em
vez de repetir os nomes numa lista — uma lista à mão divergiria do contrato no
dia em que ele mudasse, que é o defeito que ela existiria para apanhar.

**E uma terceira nota da mesma sessão não gerou trabalho, de propósito:** não
existe ligação entre serviço e recurso, pelo que o `getAvailability` devolve
horas de **todos** os recursos activos do tenant — e numa PME com duas salas o
grafo oferece a errada, com o `slot_id` assinado a certificá-la. É a dívida
**137**, declarada pelo KAM-047, e resolvê-la é esquema novo: decisão do
fundador. O `_unica_na_hora` já cai para o lado seguro quando duas opções batem
a mesma hora, e isso ficou escrito onde ele vive.

## Hipóteses devolvidas ao fundador

As duas são decisões que a skill manda devolver em vez de decidir em silêncio:
uma interacção entre tickets que nenhum dos dois prevê, e um nome canónico cujo
credor está fechado.

### H1 — O *hold* que nenhuma tool catalogada pode criar

```text
HIPÓTESE
- Hipótese: o `get_availability` (classe `read`) devolve `hold_id` e
  `expira_at` quando o pedido estreita a um único intervalo, tomando o *hold*
  curto do §8.2 sem tool nova.
- Evidência que a sustenta: o §8.2 fixa o botão `confirm:{hold_id}` e diz que
  «o `book_slot` mantém *hold* curto»; o §6.1 passo 4 exige que uma tool de
  classe `write` traga o botão de confirmação; no instante de criar o *hold*
  ainda não existe `hold_id` para o botão citar. O módulo `servicos` (KAM-047)
  tem `holdSlot` como operação e o catálogo do §6.2 não lhe dá tool. Medido: com
  o `book_slot` a tentar criar e confirmar, o passo 4 recusa.
- Estado: NÃO VERIFICADO — é uma leitura nossa de duas linhas que não se
  encontram, e faz uma tool de leitura ter efeito de escrita.
- Como validar: decisão escrita do fundador entre (a) o que está implementado,
  com a nota de que uma tool `read` passa a ter efeito; e (b) uma sétima tool
  `hold_slot` de classe `write` sem confirmação por botão, que acrescenta um
  **nome** ao §6.2 e ao dicionário §3.26 — canon desde a emenda 1.35 — e abre a
  pergunta de como se confirma uma escrita reversível e limitada por TTL.
```

### H2 — Duas superfícies canónicas cujo credor está fechado

```text
HIPÓTESE
- Hipótese: a duração de um serviço não se pode citar, e o ticket que a devia
  tornar citável está fechado.
- Evidência que a sustenta: o §8.2 manda estender o validador a «datas, horas e
  durações» e o critério 6 pede *facts* `datetime`/`duration`; o `KINDS` do
  `tls/erros.py` tem quatro valores e não tem `duration`; a lista fechada de
  blocos do §9.1 (dicionário §3.30) tem cinco e nenhum é de duração. O credor
  natural — KAM-032, que escreveu o *renderer* — fundiu. O mesmo padrão
  aparece no credor das cinco tools de Serviços: o ticket que ligaria o AGR ao
  módulo `servicos` não existe no §4 do `INDICE`, e o KAM-047, que seria o
  candidato, também fechou.
- Estado: CONFIRMADO quanto ao facto (as listas são as que são, e os tickets
  estão fechados); NÃO VERIFICADO quanto a quem paga.
- Como validar: o fundador nomear o ticket — ou autorizar abri-lo, que é linha
  L1 e altera o backlog mestre. Entretanto esta vertical **não** cita durações,
  e as cinco tools ficam `declaradas` com o credor a apontar para este ticket,
  o que está registado como declaração de lacuna e não como conformidade
  (dívidas **145** e **147**).
```

## Uma decisão que NÃO se reabre, e cita-se

O `docs/adr/ADR-L005-degradacao-e-concierge.md`, de 2026-10-29, decide que com a
política `concierge` activa a resposta do modo determinístico **também** vai a
aprovação humana — os dois mecanismos somam-se. O `send` é o nó partilhado onde
o KAM-114 intercepta, pelo que a decisão aplica-se a este grafo pela mesma
construção, **sem código novo**: quatro arestas e dois nós reutilizados.

Não é opcional, e isso mediu-se: sem elas o `send` deste grafo põe
`concierge.estado` a `a_aprovar` e não enfileira — o turno acabava com o cliente
sem resposta e sem ninguém a quem aprovar. **Um nó partilhado traz as arestas de
que depende.**

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: revisão adversarial do KAM-035, 22 achados confirmados, as duas hipóteses devolvidas ao fundador e o achado que o ensaio de um achado encontrou. | Equipa KAMBÁ |
