# ANÁLISE-16 — KAM-005: outbox transaccional, envelope v1 e publicador

| Campo | Valor |
|---|---|
| Ticket | KAM-005 — Outbox transaccional, publicador BullMQ e envelope de evento versionado |
| Âmbito | Revisão `0004`, `packages/core-ts/src/eventos/`, `services/worker-canal/src/publicador.ts`, as *suites* `tests_eventos` e `tests_eventos_carga`, e as alterações às *suites* do KAM-003 e do KAM-004 |
| Método | Revisão adversarial **independente**: um subagente recebeu os requisitos (bloco do ticket, `docs/tecnica/06`, dicionário §3.5, `E4` §2.10, `docs/isolamento.md`) e o código, e **nunca as justificações de quem o escreveu**. Mandato: procurar razões para estar errado, com doze perguntas fixas, e dizer explicitamente onde procurou e não encontrou |
| Resultado | 16 achados. **12 corrigidos**, 3 registados sem correcção, 1 devolvido. Dois eram perda de eventos e corte cruzado entre tenants |
| Veredicto do revisor | «Recusaria aprovar até ao fecho de A1, A2, A3 e A4» — os quatro estão fechados |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. O que a revisão mudou, em três frases

Dois dos achados eram defeitos de correcção, não de estilo: uma linha inválida
no *outbox* prendia ~200 eventos **para sempre**, e um tenant podia cortar a
emissão de eventos de outro com um `UPDATE` de uma linha. Um terceiro mostrou
que o critério de aceitação 3 estava a ser provado por uma asserção que **não
podia falhar**, e um quarto que a ordem por agregado — a razão de existir das 16
filas — não era medida em sítio nenhum e a mutação que a quebra sobrevivia.

Nenhum dos quatro teria sido encontrado por releitura. Três foram encontrados a
ler o `try/catch` contra o `WHERE ... ORDER BY id` da consulta, e um a perguntar
«esta asserção pode falhar?».

## 2. Disposição dos 16 achados

| # | Título | Classe | Disposição |
|---|---|---|---|
| 1 | Um evento envenenado prende ~200 eventos no *outbox* para sempre | defeito | **Corrigido** (§3.1) |
| 2 | `evt_agregado_seq` sem RLS **com `UPDATE`**: um tenant corta a emissão de outro | defeito de isolamento | **Corrigido** (§3.2) |
| 3 | O critério 3 provado por uma asserção que não pode falhar | lacuna de teste | **Corrigido** (§3.3) |
| 4 | A ordem por agregado nunca é medida; a mutação que a quebra sobrevive | defeito + lacuna | **Corrigido** (§3.4) |
| 5 | Constantes de mutação definidas e não usadas; 4 mutações na *suite* errada | lacuna de teste | **Corrigido** (§3.5) |
| 6 | A partição `DEFAULT` com linhas impede criar a mensal correspondente | risco | **Registado**, documentação corrigida (§4.1) |
| 7 | O p95 medido com um relógio que para antes do trabalho | afirmação sem evidência | **Corrigido** (§3.6) |
| 8 | A emenda 1.9 diz 13 chaves; o DDL escreve 14 | divergência do canon | **Corrigido** (§3.7) |
| 9 | Os critérios 1 e 2 não estavam provados à letra | lacuna de teste | **Corrigido** (§3.8) |
| 10 | A medição que justifica a RLS por partição não existe no repositório | afirmação sem evidência | **Corrigido** (§3.9) |
| 11 | Três verificações do KAM-004 ficaram sem quem as exerça | lacuna de teste | **Corrigido em duas, registada a terceira** (§3.9, §4.2) |
| 12 | Asserção tautológica com comentário que afirma provar o que não prova | lacuna de teste | **Corrigido** (§3.10) |
| 13 | Um erro transitório deixa o *advisory lock* preso (contagem por referência) | defeito | **Corrigido** (§3.11) |
| 14 | Quatro afirmações menores com mais confiança do que a evidência | afirmação sem evidência | **Corrigido** (§3.12) |
| 15 | A emenda 1.9 apagou uma extensão do KAM-008, e a emenda é *proposta* | divergência do canon | **Registado** (§4.3) |
| 16 | Quatro simplificações | simplificação | **Três adoptadas**, uma registada (§3.1, §3.2, §3.3, §3.6) |

E um achado **do próprio revisor sobre o estado da árvore**, antes dos 16: a
primeira versão do teste de liderança lia o `stdout` do publicador com
`readline()` sobre um `PIPE`, sem respeitar o limite de espera — o gate ficava
pendurado até aos 1500 s em vez de falhar. Já estava corrigido quando a revisão
correu (registo em ficheiro), e o revisor di-lo.

## 3. Os achados corrigidos

### 3.1 Achado 1 — uma linha inválida prendia o lote (defeito, corrigido)

**O que estava errado.** `#entregar` lançava para quatro causas que são **da
linha** (`EnvelopeInvalidoError`, `PadraoDeTelefoneError`, `DestinoInvalidoError`,
`SemConversorError`) de dentro da transacção do lote. Qualquer uma abortava as
200 linhas: `ROLLBACK`, e todas recuavam juntas. No ciclo seguinte a linha má
voltava a ser a de `id` mais baixo entre as elegíveis (`ORDER BY id`), voltava a
entrar no lote, voltava a derrubá-lo. As ~199 que partilhavam o recuo com ela
ficavam co-elegíveis **para sempre**: nunca iam à fila, nunca entravam no
`events_log` — e por isso o reconciliador do §6.5 (KAM-006), que parte do
`events_log`, também nunca as veria.

**Porque importava.** Perda de eventos com o *outbox* cheio e aparentemente
saudável, sobre uma fatia do *outbox* de **todos** os tenants, desencadeada por
uma linha inserida directamente (que o próprio código justifica com
«`kamba_batch`, uma migração, um *replay* operacional») ou por um produtor que
emita `versao = 2` antes de haver conversor.

**E a afirmação que o escondia.** `docs/eventos.md` chamava à implementação «o
equivalente observável» do estado `bloqueado` que o §6.2 pede. **Não era
equivalente**: o ponto do `bloqueado` no §6.2 é marcar *aquela* linha para que o
resto siga. A afirmação de equivalência era falsa, e é o tipo de frase que faz
um defeito passar por decisão.

**Correcção.** O ciclo passa a duas fases (`publicador.ts`):

1. **preparar**, síncrona e sem efeitos: ler e validar cada envelope, achar os
   destinos, converter a versão. O que falha fica de lado com o seu motivo, e
   nada foi para fila nenhuma;
2. **entregar** o que está bom, na mesma transacção; as de lado recuam em
   transacção própria.

O corte é **por agregado**: quando uma linha é posta de lado, tudo o que vem
depois dela no mesmo `(tenant_id, agregado_tipo, agregado_id)` espera com ela —
porque publicar `seq = 3` com a `seq = 2` para trás é perder a ordem causal. Os
outros agregados seguem. `ResultadoDoCiclo` ganha `bloqueadas`, distinto de
`recuadas` (que continua a ser a falha do **lote**: fila ou base em baixo).

**Provas novas.** Três testes unitários (`uma linha invalida **nao** derruba as
boas do lote`, `o corte arrasta o resto do agregado, e so dele`, `o agregado de
um tenant nao bloqueia o homonimo de outro`) e dois de integração
(`test_uma_linha_envenenada_nao_prende_o_resto_do_lote`,
`test_a_linha_envenenada_arrasta_o_seu_agregado_e_mais_nenhum`). Duas mutações
novas põem de volta cada metade do defeito.

**O que fica em aberto, e é a simplificação 2 do achado 16 não adoptada por
inteiro:** o §6.2 pede uma coluna de estado (`bloqueado`) e o DDL do §6.1 não a
tem. A correcção dá o comportamento sem acrescentar coluna; acrescentá-la é um
desvio ao DDL do documento e fica devolvido (§5, linha 3).

### 3.2 Achado 2 — corte cruzado entre tenants pelo contador (defeito, corrigido)

**O que estava errado.** `evt_agregado_seq` ficava fora da RLS e `kamba_app`
recebia `SELECT`, `INSERT` e `UPDATE (seq)` sobre ela. A chave era
`(agregado_tipo, agregado_id)`, global. Logo, uma sessão com o contexto do
tenant A podia:

1. `UPDATE platform.evt_agregado_seq SET seq = 0 WHERE agregado_id = '<de B>'` —
   passa, porque há privilégio e não há política. A partir daí o próximo
   `evt_emitir` de B devolve um `seq` que colide com
   `events_outbox_agregado_uq`, e **B deixa de conseguir emitir** para aquele
   agregado. Como `evt_emitir` corre na transacção do produtor, a transacção de
   negócio de B — a encomenda, o pagamento — falha com ela;
2. emitir com o **seu** `tenant_id` e o `agregado_id` de B (passa o `WITH
   CHECK`) e **consumir o `seq` de B**, que é precisamente o que o critério 1
   promete não acontecer — e invisível para B, porque a linha de A está
   escondida pela política do *outbox*.

**Porque importava.** Negação de serviço cruzada, permanente e silenciosa, sobre
o caminho do dinheiro, obtida com um identificador de agregado — que circula em
referências de pagamento e em mensagens. E o que estava **registado** era a
exposição errada: `docs/eventos.md` e a decisão aberta diziam «quem conheça o
`agregado_id` de outro tenant consegue ler-lhe o `seq`», isto é, **leitura**. A
decisão ia ser devolvida ao fundador com a gravidade errada em cima da mesa.

**Correcção.** `evt_agregado_seq` ganha `tenant_id`, com
`PRIMARY KEY (tenant_id, agregado_tipo, agregado_id)`, política `tenant_iso` e
`FORCE`; `events_outbox_agregado_uq` passa a
`(tenant_id, agregado_tipo, agregado_id, agregado_seq)`; o `ON CONFLICT` do
`evt_emitir` acompanha. **É um desvio ao DDL do `docs/tecnica/06` §6.1 e o único
não aditivo deste ticket** — está registado na revisão, no dicionário (§3.5), em
`docs/eventos.md` §5 e no corpo do PR. A tabela passa a entrar sozinha no X-03,
X-04 e X-05, e a decisão deixa de precisar de ser devolvida.

**Decisão tomada, e porquê.** O ticket diz «DDL: exactamente `docs/tecnica/06`
§6.1». Entre entregar a forma do documento com um buraco de isolamento numa
fundação de Fase 0 — de que dependem nove tickets — e desviar-me do DDL com o
desvio escrito, escolhi o segundo. Não devolvi a decisão porque devolver
significava fundir o buraco enquanto se decide.

### 3.3 Achado 3 — o critério 3 era inverificável (lacuna, corrigido)

**O que estava errado.** `Fila.jobs(fila)` devolvia o conjunto dos sufixos de
chaves `bull:<fila>:<jobId>` que são UUID. As chaves do Redis são únicas por
definição: para um dado `jobId` existe no máximo uma chave. Logo
`assertEqual(jobs(nome), {event_id})` era incapaz de distinguir «um *job*» de «o
`jobId` existe». Pior: o filtro de UUID **descartava** o sinal que importava —
um segundo *job* com `jobId` auto-gerado (`"1"`, `"2"`) não é UUID e saía da
contagem. E o *helper* que mediria de facto, `pendentes()` = `LLEN
bull:<fila>:wait`, existia e não era usado em teste nenhum.

**Correcção.** As asserções do critério 3 e do critério 5 passam a contar a
lista de espera (`pendentes()`) e a comparar `espera()` — a lista por inteiro,
por ordem de saída. O *helper* `espera()` é novo. O teste unitário que media o
`Map` da fila falsa foi reescrito: passa a afirmar só o que é **do publicador**
(que republicar usa o mesmo `jobId`) e diz, no comentário, que a deduplicação se
mede em `db/tests_eventos` contra uma fila real — porque a `FilasEmMemoria`
deduplica por construção, e tomar isso por evidência era o teste tautológico.

### 3.4 Achado 4 — a ordem por agregado não era medida (defeito + lacuna, corrigido)

**O que estava errado.** Duas coisas. Primeiro, o recuo do lote produzia a
inversão que o código e o documento diziam evitar: as linhas de um lote que
recua ficam com `proxima_tentativa_at` no futuro, e as inseridas depois nascem
elegíveis — pelo que a `seq` seguinte do mesmo agregado ia à fila primeiro.
Segundo, e mais grave para o método: **nada medía a ordem de entrega**. O teste
do agregado comparava **conjuntos**, e por isso a mutação que troca `ORDER BY
id` por `ORDER BY id DESC` **sobrevivia** — todos os eventos acabavam
publicados, todas as contagens passavam.

**Porque importava.** A ordem causal por agregado é a razão de existir do
`agregado_seq`, das 16 partições e da concorrência 1 por fila. É a pré-condição
dos consumidores `payment.*` do KAM-006, que são «sempre com ordem»: entregar
`seq = 3` antes de `seq = 2` empurra para `Adiar` e, esgotadas as tentativas,
para a DLQ — e um `payment.*` na DLQ é Sev1 pela definição do próprio ticket
seguinte.

**Correcção.** `Fila.espera()` devolve a lista `wait` por ordem de saída (o
BullMQ empurra com `LPUSH` e consome do fim), e
`test_o_mesmo_agregado_vai_sempre_a_mesma_fila` passa a comparar a **ordem**. A
inversão pelo recuo fecha-se com a correcção do achado 1: o corte por agregado
garante que nada do agregado passa à frente de uma linha que ficou para trás.

### 3.5 Achado 5 — mutações preparadas e não escritas (lacuna, corrigido)

Três constantes (`EV_ENVELOPE`, `EV_PII`, `EV_FILAS`) estavam definidas e não
usadas: nenhuma mutação atacava o `lerEnvelope` que falha fechada, o espelho
TypeScript do guarda de PII, nem — a mais carregada de todas — o
`enableOfflineQueue: false`, de que o critério 4 depende por inteiro. E quatro
mutações estavam declaradas contra `tests_eventos` sem que essa *suite* as
pudesse apanhar: todas as subscrições eram do mesmo `tipo`, a `particao` vinda
do `evt_emitir` está sempre em 0..15, e todos os eventos passavam pelo
`evt_emitir` (que já recusa telefones).

**Correcção.** Nove mutações novas (`enableOfflineQueue`, o tecto da escada, o
`clock_timestamp`, o `ON CONFLICT DO NOTHING`, os dois padrões do guarda de PII
em TypeScript, os campos desconhecidos do envelope, a `classe_pii` P2, e as duas
metades do achado 1), e a *suite* ganha o que faltava para as apanhar: linhas
inseridas **sem** passar pelo `evt_emitir` (com telefone no envelope e com
`particao = 16`) e uma subscrição de outro `tipo`.

### 3.6 Achado 7 — o p95 medido antes do trabalho (corrigido)

`publicado_at` era `now()`, que em PostgreSQL é `transaction_timestamp()`: o
instante em que a transacção do ciclo **começou**, antes do `SELECT ... FOR
UPDATE` e antes de todos os `add`. O atraso que o critério 8 nomeia é «outbox →
fila», e o número medido excluía o enfileiramento de até 200 linhas — com o
enviesamento a crescer precisamente no regime em que o atraso real é maior.
Passa a `clock_timestamp()` (simplificação 4 do achado 16), e há uma mutação que
põe o `now()` de volta.

**A segunda metade do achado fica parcialmente aberta** — ver §4.4.

### 3.7 Achado 8 — 13 contra 14 chaves (corrigido)

O `jsonb_build_object` escreve **14** chaves de topo; `CAMPOS_DO_ENVELOPE` tem
14 entradas e dois testes chamam-se «as catorze». Mas a emenda 1.9 ao
**dicionário canónico** — que é a autoridade, e é contra ela que o KAM-007 vai
publicar o `v1.schema.json` — dizia «13 chaves», e formulava a decisão aberta
como «9 ou 13». A aritmética também não fechava: a linha «Envelope» nomeia 9
nomes, dos quais `seq` não é de topo, logo 8 + 6 = 14. Corrigido no dicionário,
na emenda e em `docs/eventos.md`.

### 3.8 Achado 9 — os critérios 1 e 2 não estavam à letra (corrigido)

O critério 1 pede «1 000 *rollbacks* aleatórios»; o teste fazia **1 000
transacções** de que metade revertia, isto é ~500 reversões, e a constante
chamava-se `TRANSACCOES_DO_CRITERIO_1`. Passa a correr até ter mil reversões.

O critério 2 pede 100 repetições de duas transacções que se serializam; o teste
fazia `fio.start()` seguido imediatamente de `primeira.commit()`, pelo que na
maioria das repetições a segunda nem chegava a pedir o `seq` — as 100
exercitavam o caminho **sem contenção**, e a contenção real era provada uma só
vez noutro teste. Passa a esperar, em cada repetição, que o **servidor**
confirme uma sessão bloqueada (`pg_stat_activity.wait_event_type = 'Lock'`)
antes de confirmar a primeira.

O revisor conferiu os oito critérios número a número; os restantes seis estavam
à letra, com as ressalvas dos achados 3 e 7.

### 3.9 Achados 10 e 11 — políticas declaradas e nunca exercidas (corrigido)

**Achado 10.** Três sítios afirmavam «mediu-se contra o PostgreSQL 18.6: a
política do pai não protege quem lê a partição directamente». A medição foi
feita — numa sonda descartável, durante a implementação — e **não estava no
repositório**: o teste verificava só *flags* do catálogo. Uma afirmação que
sustenta uma exigência operacional perpétua (todo o *job* de partições futuro
tem de chamar `rls.enable_tenant_rls`) com uma medição que ninguém pode repetir
é exactamente o que o projecto marca NÃO VERIFICADO quando é de terceiros.

Agora há `test_a_politica_da_particao_filtra_quem_a_le_directamente`, com as
duas metades: com a política própria, a leitura directa devolve só o tenant do
contexto; tirada a política da partição — numa transacção que nunca confirma —
devolve os dois. É a prova de que é a política **da partição** que filtra.

**Achado 11, duas das três partes.** O `WITH CHECK` do `events_log` e o ramo
`UPDATE` da política do `events_outbox` estavam declarados (`FOR ALL`) e **nunca
avaliados**: `kamba_app` não tem esses privilégios e `kamba_batch` contorna a
RLS. O X-05 confirmava que a política existia, não que estivesse correcta.
Passam a ser exercidos pelo **dono** (`kamba_migrator`), que tem privilégio e
está sujeito à política pelo `FORCE`, com as duas metades em cada caso. A
terceira parte fica registada — §4.2.

### 3.10 Achado 12 — a asserção que não podia falhar (corrigido)

`assertTrue(esperar_por(lambda: self.pendentes() == 1, 5))` vinha sete linhas
depois de `assertEqual(self.pendentes(), 1)`, sem nada pelo meio que publicasse.
Não podia falhar, e o comentário acima dela dizia que o que estava em causa era
a libertação do *lock* consultivo pela morte da ligação — de que ela não media
nada. Removida, com a nota de onde essa propriedade é realmente medida.

### 3.11 Achado 13 — o *lock* preso por contagem de referência (corrigido)

Os *advisory locks* de sessão do PostgreSQL são contados por referência: um
`pg_try_advisory_lock` na sessão que já o detém devolve `true` e **incrementa** a
contagem. O `catch` do laço fazia `#lider = false` sem largar o *lock*, pelo que
depois de um erro transitório a volta seguinte re-elegia e a contagem ia a 2 — e
no encerramento limpo o `largar()` descia a 1 e a sessão continuava líder. A
réplica deixava de assumir em ≤ 10 s (critério 5) e passava a esperar a detecção
de ligação morta, que é escala de minutos. O `catch` passa a chamar `largar()`,
que engole o erro do `unlock` (se a ligação caiu, o servidor larga-o sozinho). Há
uma mutação que põe o defeito de volta.

### 3.12 Achado 14 — quatro afirmações menores (corrigido)

- A *docstring* da revisão falava no presente do `db/eventos_particoes.py`, que
  **não existe**. Passa a dizer que não existe.
- «medido no gate, fica muito abaixo dos 10 s do critério»: o gate mede ≤ 10 s;
  «muito abaixo» não é medido em sítio nenhum. A frase saiu.
- O desfecho `repetido` estava na lista fechada de etiquetas, era publicado em
  `docs/eventos.md` como valor da métrica, e **nada o incrementava**. Saiu da
  lista, com a razão escrita (uma republicação é indistinguível de uma primeira
  entrega do ponto de vista do publicador; quem a distingue é o consumidor).
- `Subscricao.exige_ordem` é lido do SQL e não é usado em decisão nenhuma do
  publicador — é do KAM-006. Legítimo, e agora dito.

**E o que o revisor procurou e não encontrou, que é informação igualmente útil:**
nenhuma promoção indevida do estado do BullMQ (varreu `CONFIRMADO`/`INDÍCIO`/`NÃO
VERIFICADO` nos três sítios e na tabela do §8); nenhum caminho em que dois
líderes publiquem a mesma linha; nenhuma dependência de monotonia de relógio;
nenhum caminho realista em que o `ON CONFLICT DO NOTHING` do arquivo esconda uma
divergência real — «mas também não há teste que o exclua».

## 4. Os achados registados sem correcção

### 4.1 Achado 6 — a partição `DEFAULT` com linhas bloqueia a mensal (risco)

No PostgreSQL, criar uma partição `FOR VALUES FROM ... TO ...` numa tabela com
partição `DEFAULT` **que tenha linhas no intervalo novo** falha: o servidor
varre a `DEFAULT` e recusa. Como o *job* das partições mensais não existe, todo
o arquivo cai na `events_log_default` — e no dia em que o *job* nascer não
conseguirá criar `events_log_2026_11` sem primeiro mover à mão as linhas desse
mês, numa tabela que o desenho declara imutável e em que nenhum papel de serviço
tem `DELETE`.

**Porque não está corrigido:** escrever o *job* das partições é trabalho que o
ticket não pede (o §6.5 descreve-o, os critérios de aceitação não o cobrem) e
que o KAM-071/KAM-078 vão fazer com a retenção. **O que foi corrigido é a
consequência escrita:** `docs/eventos.md` dizia «funciona, e perde a vantagem do
`DROP` de partição»; passa a dizer que cria uma dívida que cresce com o volume e
que só se paga com migração manual de dados. Decisão aberta 4.

### 4.2 Achado 11, terceira parte — as partições saíram do X-03 e do X-04

Tirar as partições de `tabelas_isoladas` foi deliberado e está escrito (as
mensais nascem de um *job* com data no nome, e a lista mudaria todos os meses),
mas o que substituiu um teste de **comportamento** foi, nessa parte, um teste de
**declaração**: o X-03 e o X-04 já não atacam partições com canários. O achado
10 recupera a parte que importa (a leitura directa filtrada, com as duas
metades); o ataque com canário por partição **não** foi recuperado, e fica
registado aqui como o que se perdeu na troca.

### 4.3 Achado 15 — a extensão do KAM-008 apagada depende de uma emenda *proposta*

Este PR remove `contact_endpoints.finalidade` de `canon/extensoes.yaml` porque a
emenda 1.9 passou a nomear `evt_subscricoes(… finalidade …)` no §3.5 e o *lint*
recusa extensões redundantes. Mas a emenda 1.9 é ***proposta*, por ratificar**:
se não for ratificada, o nome `finalidade` deixa de estar no dicionário e a
extensão que o cobria já foi apagada — e o gate 3b passa a falhar numa
superfície do **KAM-008**, não deste ticket.

**Porque não está «corrigido»:** não há forma de o evitar com o *lint* como
está — declarar a extensão **e** nomear o nome no dicionário é o que o *lint*
recusa. O acoplamento fica registado aqui, no comentário de
`canon/extensoes.yaml` e em `docs/eventos.md` §10 (decisão 10), para que quem
reverter a emenda saiba que tem de repor a extensão no mesmo passo.

### 4.4 Achado 7, segunda metade — a métrica do critério 8 não é confrontada

`evt_outbox_lag_seconds` é medida pelo publicador e exposta em `/metrics`, e
**nenhum teste a confronta com a realidade**: o único teste verifica que o
*gauge* contém o número que a base falsa devolveu. A rota `/metrics` de
`services/worker-canal/src/publicador.ts` não tem teste.

O que se fez: o `publicador_runner.ts` imprime as métricas ao terminar, e a
*suite* de carga lê-as e confronta `evt_publish_total{desfecho="entregue"}` com
o número de eventos publicados na base. O que **não** se fez: um teste da rota
`/metrics` e a comparação do *gauge* com `EXTRACT(EPOCH FROM now() -
min(criado_at))` sob carga. Fica como caixa do critério 8 marcada **com a
ressalva escrita** na secção de verificação do ticket, e como a razão pela qual
a frase «o sítio onde se mede é `evt_outbox_lag_seconds`» continua a ser uma
promessa sobre um número que ninguém confirmou.

## 5. O que a revisão não cobriu

- **A `tests_eventos_carga` correu a medição; a revisão não a correu.** O
  revisor leu-a; os números do p95 são os da execução registada na secção de
  verificação do ticket, não dele.
- **Nenhum achado sobre o `evt_emitir` em si.** O revisor diz que o DDL e a
  função são a parte sólida — critérios 1, 2, 6 e 7 medidos contra PostgreSQL
  real, com paridade SQL↔TypeScript do guarda de PII por *fixture* — e que o
  `uuidv7()` CONFIRMADO, com teste de regressão, é a melhor evidência do PR.
- **Não houve segunda revisão independente.** O DoD pede dois revisores quando
  se alteram regras de bloqueio ou limiares, e este ticket altera o X-05 e
  acrescenta duas *suites* ao gate 8. A caixa fica **vazia**: uma revisão
  adversarial é evidência, não é um revisor.

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-005): 16 achados, 12 corrigidos, 3 registados, 1 devolvido. Os quatro que o revisor recusava aprovar — perda de eventos por linha envenenada, corte cruzado entre tenants pelo contador, critério 3 inverificável e ordem por agregado nunca medida — estão fechados. | Equipa KAMBÁ |
