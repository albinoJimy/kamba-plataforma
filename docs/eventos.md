# Eventos — outbox transaccional, envelope v1 e publicador

| Campo | Valor |
|---|---|
| Documento | `docs/eventos.md` |
| Ticket | KAM-005 — Outbox transaccional, publicador BullMQ e envelope de evento versionado |
| Estado | Revisão `0004` aplicada; publicador e envelope v1 implementados; gate 8 com as *suites* `tests_eventos` e `tests_eventos_carga` activas. 13 das 16 caixas do ticket marcadas; as três vazias estão nomeadas na secção de verificação. Consumidores, `events_consumed` e DLQ são o KAM-006; o catálogo de *schemas* é o KAM-007 |
| Âmbito | O lado do **produtor**: escrever o evento na transacção do dado e entregá-lo às filas. Nada do lado do consumidor |
| Fontes | `docs/tecnica/06` §4, §6.1, §6.2, §6.5, §6.6, §7.3; `docs/tecnica/00` §7; ADR-009, ADR-010, ADR-018; `specs/02` §3.5 (emenda 1.9); `docs/tecnica/evidencia/E4` §2.10 |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. A tese, numa frase

O evento escreve-se na **mesma transacção** que o dado e publica-se depois
(ADR-009). Se a transacção do produtor reverte, não há evento: nem linha no
*outbox*, nem lacuna na sequência do agregado. Se a publicação falha, o evento
fica no *outbox* e volta a ser tentado. A entrega é *at-least-once*; o efeito
exactamente-uma-vez sai da idempotência do consumidor, que é o KAM-006.

**A verdade é o *outbox*, não a fila.** As garantias de entrega do BullMQ estão
`NÃO VERIFICADO` (§8), e o desenho assume o pior caso: duplicados e perda da
cauda do AOF. Nada de operacional depende da fila ser fiável.

```text
produtor                          publicador                     consumidor
--------                          ----------                     ----------
BEGIN                             pg_try_advisory_lock(7101)     (KAM-006)
  INSERT encomenda                loop (200 ms):
  SELECT evt_emitir(...)            BEGIN
COMMIT                              SELECT ... FOR UPDATE SKIP LOCKED
                                    add(jobId = event_id) ────────► evt.<c>.p<n>
                                    INSERT events_log
                                    UPDATE publicado_at
                                  COMMIT
```

## 2. O que existe na base

A revisão `0004` cria quatro relações e uma função, em `platform`, com a forma
de `docs/tecnica/06` §6.1 e §6.5. Os nomes estão no dicionário canónico §3.5
(emenda 1.9, *proposta*).

| Relação | Para que serve |
|---|---|
| `events_outbox` | O *outbox*. `event_id` é a chave de idempotência global (UUIDv7) e o `jobId` na fila. `particao` é a fila de destino. `tentativas` e `proxima_tentativa_at` são o recuo |
| `evt_agregado_seq` | O contador de `seq` por agregado **e por tenant**. É o `UPDATE` do `ON CONFLICT` que serializa o agregado. O `tenant_id` é um desvio ao §6.1 — ver §5 |
| `evt_subscricoes` | Quem recebe o quê, com que `versao_max` e para que `finalidade` |
| `events_log` | O arquivo imutável, particionado por mês em `ocorrido_em`. Base da reconciliação (`docs/tecnica/06` §11–§12) |
| `events_log_default` | A partição `DEFAULT` do arquivo. Rede de segurança — ver §7 |
| `evt_emitir(...)` | A função que o produtor chama. `SECURITY INVOKER`, com a guarda de PII |

### `uuidv7()` existe — CONFIRMADO

O `docs/tecnica/06` §4 marcava `uuidv7()` como **INDÍCIO** («nativo no PG 18 —
confirmar na versão fixada») e o ticket permitia o desvio de gerar o UUIDv7 na
aplicação. Mediu-se contra a imagem do inventário
(`pgvector/pgvector:0.8.7-pg18`, digest em `ci/supply-chain/imagens.yaml`):
`SELECT count(*) FROM pg_proc WHERE proname = 'uuidv7'` devolve **2** (duas
sobrecargas), a versão do servidor é `PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2)`,
e os UUID produzidos têm o dígito de versão `7` e saem ordenados. O desvio **não
foi necessário**; a função usa o `uuidv7()` nativo. A medição repete-se a cada
execução do gate 8 (`db/tests/test_eventos_schema.py::TestUuidv7`), para que a
afirmação não envelheça em silêncio.

### Como se emite

```sql
BEGIN;
  INSERT INTO ... ;                       -- o dado
  SELECT platform.evt_emitir(
    'order.created', 1::smallint, :tenant, 'order', :order_id,
    jsonb_build_object('order_id', :order_id, 'valor_minor', :total, 'currency', 'AOA'));
COMMIT;
```

Três coisas que a chamada esconde:

- **`SECURITY INVOKER`** (a omissão). A função corre com os privilégios e o
  contexto de quem a chama, pelo que o `WITH CHECK` da política `tenant_iso`
  continua a valer sobre o `INSERT` no *outbox*: `kamba_app` não emite um evento
  com o `tenant_id` de outro. Uma `SECURITY DEFINER` aqui era um buraco de
  isolamento, e o X-05 recusa-a.
- **O `seq` sai de uma linha trancada**, não de uma sequência. O
  `INSERT ... ON CONFLICT DO UPDATE ... RETURNING seq` bloqueia a linha do
  agregado até ao `COMMIT`: a segunda transacção espera, e por isso a ordem de
  `seq` coincide com a ordem de `COMMIT`. Uma sequência (`nextval`) não reverte,
  e deixava lacunas em cada `ROLLBACK`.
- **A guarda de PII corre primeiro.** Antes de qualquer escrita.

## 3. O envelope v1

Treze chaves de topo, as de `docs/tecnica/06` §6.1. O envelope **constrói-se em
SQL**, dentro de `evt_emitir`: não há construtor em TypeScript, de propósito —
duas fontes para a mesma forma divergem no primeiro campo novo, e foi esse o
defeito que o dicionário canónico existe para evitar. O que o TypeScript faz é
**ler e recusar** (`packages/core-ts/src/eventos/envelope.ts`): um envelope que
não se reconheça não se publica, e um campo de topo desconhecido é recusado em
vez de ignorado (um produtor que escreve um campo novo sem subir a `versao` é um
contrato quebrado em silêncio, que o §6.6 proíbe).

| Campo | Regra |
|---|---|
| `id` | UUIDv7. Chave de idempotência global e `jobId` na fila |
| `tipo`, `versao` | `família.verbo` em minúsculas; `versao` inteira ≥ 1 |
| `tenant_id` | UUID. Igual à coluna — verificado no gate 8 |
| `ocorrido_em` / `registado_em` | Quando o facto ocorreu / quando a transacção o gravou |
| `produtor` | `application_name` de quem emitiu. Pode ser nulo |
| `agregado` | `{tipo, id, seq}`. O `seq` é a ordem causal, sem lacunas |
| `correlacao_id` / `causa_id` / `trace_id` | Grafo causal e ligação aos *logs*. Podem ser nulos |
| `classe_pii` | `P0` ou `P1`. **`P2` é recusada** |
| `finalidades` | Lista não vazia. É o que faz o roteamento (§4) |
| `payload` | Objecto. Sem telefone, nome, morada nem texto — só referências |

### A divergência com o dicionário, e o que fica por decidir

O dicionário §3.5 («Envelope») nomeia **nove** nomes — `id`, `tipo`, `versao`,
`tenant_id`, `agregado`, `seq`, `trace_id`, `ocorrido_em`, `payload` — e o
`jsonb_build_object` do §6.1 escreve **treze** chaves, com o `seq` **dentro** de
`agregado`. A emenda 1.9 do dicionário acrescentou os seis que faltavam
(`registado_em`, `produtor`, `correlacao_id`, `causa_id`, `classe_pii`,
`finalidades`), porque são colunas do `events_log` e chaves que o DDL escreve.

A leitura que este ticket toma, e escreve: a linha «Envelope» do dicionário é
uma lista de **nomes**, não de aninhamento, e `agregado = {tipo, id, seq}` usa
os dois nomes. **O que fica por decidir**: se o contrato v1 publicado em
`contratos/eventos/` (KAM-007) tem nove ou treze campos de topo. A decisão é de
quem aprova emendas, e é o KAM-007 que a paga: enquanto não estiver tomada,
qualquer `v1.schema.json` que declare os treze campos **falha o gate 3b**
(`tools/canon_lint/eventos.py` exige extensão `envelope.<nome>` para campos de
topo fora da linha do dicionário, e uma extensão que nenhuma superfície usa
também falha — por isso não se podiam declarar aqui, à frente do KAM-007).

### A guarda de PII, e o que ela não apanha

`evt_emitir` recusa, com `check_violation`, um `payload` que contenha um padrão
de telefone:

```sql
IF p_payload::text ~ '\+?244 ?9[0-9]{8}' OR p_payload::text ~ '"\+[0-9]{9,15}"' THEN
  RAISE EXCEPTION 'evento % contem padrao de telefone (PII P2)', p_tipo
    USING ERRCODE = 'check_violation';
END IF;
```

O mesmo predicado existe em TypeScript (`packages/core-ts/src/eventos/pii.ts`) e
o publicador corre-o antes de pôr o envelope na fila — porque uma linha pode
entrar no *outbox* por um `INSERT` directo (`kamba_batch`, uma migração, um
*replay* operacional) e esse não passa por `evt_emitir`. Duas implementações do
mesmo predicado só se mantêm honestas com uma máquina a confrontá-las: a
*fixture* `packages/core-ts/tests/fixtures/eventos_pii.json` é corrida pelos dois
lados, e um veredicto diferente falha o gate 8.

**E apanha o que não devia.** O `+` do primeiro padrão é **opcional**, pelo que
qualquer corrida de doze dígitos começada por `2449` é apanhada — e um
identificador hexadecimal de 32 caracteres contém uma dessas de vez em quando. A
medição de carga deste ticket rebentou com isso ao evento ~8 000 de 15 000, sobre
um `agg-<hex>` sem telefone nenhum. **A consequência não é um aviso: é a
transacção de negócio a falhar**, porque `evt_emitir` corre nela. O
comportamento está fixado por teste
(`db/tests/test_eventos_schema.py::TestGuardaDePii`), e apertar o padrão muda o
§6.1 — decisão aberta 11.

**Não apanha**: um telefone com separadores (`+244-912-345-678`), um número
noutro formato, um nome, uma morada, o texto de uma mensagem. O próprio §6.1
di-lo: «o guarda de PII só apanha telefones explícitos; a defesa principal é o
*schema* fechado e o *lint* do §7.3». O *schema* fechado e o *lint* de nomes de
campo são o **KAM-007**, e até lá esta é a única barreira automática. Está
registado como lacuna, não como garantia.

## 4. O publicador

Processo de `services/worker-canal` (`node src/publicador.ts`), com a biblioteca
em `packages/core-ts/src/eventos/`.

### Um líder, e réplicas em espera

`pg_try_advisory_lock(7101)` — o valor é o de `docs/tecnica/06` §6.2 — de
**sessão**, não de transacção: tem de sobreviver às transacções do laço. Quem o
consegue publica; quem não o consegue tenta outra vez no ciclo seguinte. O
*lock* larga-se quando a ligação termina, incluindo quando o processo morre sem
avisar, e por isso a réplica assume sem ninguém intervir.

### A ordem, que é a garantia

```text
BEGIN
  linhas = SELECT ... WHERE publicado_at IS NULL AND proxima_tentativa_at <= now()
           ORDER BY id LIMIT 200 FOR UPDATE SKIP LOCKED
  para cada linha, para cada subscrição activa com finalidade ∈ finalidades:
      fila[consumer][particao].add(jobId = event_id, attempts = 6, backoff exp 1 s)
  INSERT events_log ... ON CONFLICT DO NOTHING
  UPDATE publicado_at
COMMIT
```

O `add` vem **antes** do `COMMIT`, e é isso que torna a perda impossível: uma
falha pelo meio deixa a linha sem `publicado_at` e o ciclo seguinte republica-a.
A ordem inversa (`COMMIT` e depois `add`) perdia eventos — um `kill -9` logo
depois do `COMMIT` deixava a linha publicada e o *job* por criar, que é
exactamente o modo de falha que o *outbox* existe para não ter.

**O lote inteiro é uma transacção.** Se uma linha não se puder publicar,
nenhuma do lote fica marcada, o `ROLLBACK` devolve tudo ao *outbox*, e depois —
em transacção própria — as linhas recuam. Marcar as boas e deixar as más era
mais eficiente e perdia a ordem do agregado: a linha `seq = 3` publicada
enquanto a `seq = 2` recua põe o consumidor a ver o futuro antes do passado.

### Roteamento por finalidade

O publicador entrega a uma subscrição activa **só se** a `finalidade` dela
estiver em `envelope.finalidades` (`docs/tecnica/06` §7.3). Um consumidor de
`marketing` não recebe um evento emitido só para `transacao`, mesmo que
subscreva o tipo. É limitação de finalidade escrita em código, e não um filtro
no consumidor — um filtro no consumidor já tinha o dado na mão.

### *Fan-out*: 16 filas por consumidor

`evt.<consumer>.p<0..15>`, com concorrência 1 por fila. A partição é
`hash(tenant_id ‖ agregado.id) & 15`, calculada **em SQL** por `evt_emitir` e
guardada em `events_outbox.particao`. O TypeScript lê a coluna; não recalcula o
*hash*. Reimplementá-lo era possível — é o `lookup3` do Bob Jenkins — e era um
defeito: duas implementações divergem na primeira versão do PostgreSQL que mude
o algoritmo, e o sintoma seria eventos do mesmo agregado em duas filas, isto é,
**perda de ordem**, silenciosa. Uma partição fora de 0..15 na coluna faz o
publicador falhar fechado em vez de dobrar por módulo.

### O recuo do *outbox*: 1 s, 2 s, 5 s, 15 s, 30 s

**Não é a escada do `docs/tecnica/06` §6.4**, e isso é deliberado. A escada do
§6.4 — 1 s, 5 s, 30 s, 2 min, 10 min, seis tentativas — é a **política da DLQ**:
o recuo do *job* no consumidor, e vai no `add` como `attempts: 6` com recuo
exponencial de base 1 s. O recuo do *outbox*, que o §6.2 só nomeia
(«`proxima_tentativa_at = now() + backoff(tentativas)`»), é outro problema.

O limite é o critério de aceitação 4: «Redis parado 60 s com 1 000 eventos
emitidos: após o regresso, 100% publicados em ≤ 60 s». Com a escada do §6.4, 60 s
de fila em baixo levam o publicador à quarta ou quinta tentativa, e a próxima
tentativa cai a 2 ou a 10 minutos de distância — o critério 4 **não se cumpre**
com a escada do §6.4. A contradição entre as duas linhas do documento é um
achado deste ticket. Com o tecto em 30 s, o pior caso depois de a fila voltar é
30 s, com folga. Os valores são **proposta**, calibrada contra o critério 4; o
sítio onde se mede é `evt_outbox_lag_seconds`.

### Conversão de versão: o gancho, vazio

`evt_subscricoes.versao_max` diz que versão cada consumidor aceita. O registo de
conversores (`packages/core-ts/src/eventos/conversor.ts`) está **vazio**, como o
ticket pede. Vazio não é inerte: um evento `versao = 2` para um consumidor de
`versao_max = 1` faz o publicador **não publicar e não descartar** — a linha
fica no *outbox*, `evt_publish_errors_total{motivo="sem_conversor"}` sobe, e o
registo leva o código. O §6.6 é explícito em que ignorar versões desconhecidas
perde dados em silêncio.

Um conversor registado tem de preservar `id` e `agregado.seq` (§6.6), e o
registo recusa-o se não os preservar — verificado sobre o resultado real, não por
confiança. Se o `id` mudar, a deduplicação por `jobId` deixa de funcionar; se o
`seq` mudar, a ordem causal quebra.

**Divergência registada:** o §6.2 manda, sem conversor, «marcar evento
`bloqueado`, alerta Sev2; NÃO descartar», mas o DDL do §6.1 **não tem coluna de
estado** e o ticket manda implementar o DDL «exactamente» como está. O
comportamento implementado é o equivalente observável — não publica, não
descarta, conta o erro e recua — sem acrescentar coluna. Acrescentar um estado
`bloqueado` é uma alteração ao DDL do §6.1 e fica devolvida.

## 5. Isolamento e privacidade

| Papel | `events_outbox` | `evt_agregado_seq` | `evt_subscricoes` | `events_log` |
|---|---|---|---|---|
| `kamba_app` (produtor) | `SELECT`, `INSERT` | `SELECT`, `INSERT`, `UPDATE (seq)` | — | `SELECT` |
| `kamba_batch` (publicador, retenção) | `SELECT`, `UPDATE`, `DELETE` | — | `SELECT` | `SELECT`, `INSERT` |
| `kamba_resolver`, `kamba_identity` | — | — | — | — |

RLS `FORCE` com política `tenant_iso` no `events_outbox`, no `events_log` e na
partição. O `kamba_app` lê **as suas** linhas, e é isso que faz da política uma
barreira real e não decoração: sem um papel sujeito a ela que as leia, a política
nunca seria exercida. O `kamba_batch` tem `BYPASSRLS` por atributo — é como lê o
*outbox* de todos os tenants — e a auditoria do que ele faz é o KAM-012.

**Ninguém tem `UPDATE` nem `DELETE` no `events_log`**: o arquivo é imutável por
privilégio. Não há *trigger* a impedi-lo — o dono (`kamba_migrator`) pode
alterá-lo numa migração, e é assim que se corrige um defeito de esquema.

### A política do pai não protege a partição

Mediu-se contra o PostgreSQL 18.6: com `ENABLE`/`FORCE` e política na tabela-mãe
particionada, um `SELECT` feito **na partição** devolveu as linhas de todos os
tenants — com o contexto de um tenant e sem contexto nenhum. O catálogo
confirma-o: a partição fica com `relrowsecurity = false` e zero políticas.

Consequências, as duas implementadas:

1. `rls.enable_tenant_rls` corre também na partição, e o
   `db/eventos_particoes.py` tem de fazer o mesmo em cada partição que criar;
2. nenhuma partição tem privilégio concedido a papel nenhum — quem acede, acede
   pelo pai. Uma partição nova nasce com `relacl` vazio (medido), pelo que isto
   é o estado por omissão, e a verificação está lá para que uma concessão
   directa não passe calada.

A verificação é o X-05 (`db/tests_isolamento/catalogo.py::verificar_particoes`),
e por causa dela as partições **saíram** de `tabelas_isoladas`: uma partição é
uma linha do catálogo com as colunas do pai, entrava sozinha na descoberta, e com
ela entravam receita de sementes e canário — sobre a mesma linha que o pai já
semeia. Pior: as partições mensais nascem de um *job* com data no nome, e a
lista mudava todos os meses.

### O desvio do `evt_agregado_seq`, e o buraco que ele fechou

A forma do §6.1 é `PRIMARY KEY (agregado_tipo, agregado_id)`, **sem tenant**, e o
contador fica global. Com `kamba_app` a precisar de `UPDATE (seq)` para o
`ON CONFLICT`, isso abre duas portas cruzadas, e a revisão adversarial
(ANALISE-20, achado 2) demonstrou as duas:

1. com o contexto do tenant A, `UPDATE evt_agregado_seq SET seq = 0 WHERE
   agregado_id = '<agregado de B>'` passa — há privilégio e não há política — e a
   partir daí **B deixa de poder emitir** para aquele agregado: o próximo `seq`
   colide com a unicidade do triplo, e como `evt_emitir` corre na transacção do
   produtor, a **transacção de negócio de B falha com ela**. Negação de serviço
   cruzada, permanente e silenciosa, sobre o caminho do dinheiro;
2. A pode emitir com o **seu** `tenant_id` e o `agregado_id` de B (passa o `WITH
   CHECK`) e **consumir o `seq` de B** — que é exactamente o que o critério 1
   promete não acontecer, e invisível para B.

Por isso a tabela ganhou `tenant_id` na chave, na política `tenant_iso` e na
unicidade do triplo de `events_outbox`. **É um desvio ao DDL do §6.1, e o único
não aditivo deste ticket** — registado aqui, na revisão, no dicionário (§3.5) e
no PR. A alternativa era devolver a decisão, e devolver significava fundir o
buraco enquanto se decide.

### Privacidade

O envelope não leva PII P2. A referência a uma pessoa é `contact_id` (ADR-010), e
é opaca. Os *logs* do publicador levam `outcome` e `error_code` da *allowlist* de
`docs/tecnica/08` §7.3, nunca o envelope. As métricas não levam identificadores
em etiquetas: os sufixos permitidos são listas fechadas, e `contar` recusa um
sufixo que não esteja nelas — `tenant_id`, `event_id`, `agregado_id` e `consumer`
não entram em etiqueta nenhuma (`OBS-I` de `docs/seguranca/ameacas_stride.md`; o
*lint* de cardinalidade é o KAM-080 e não existe).

## 6. Observabilidade

Três métricas, com os nomes do critério 8, expostas em `/metrics` pelo processo
do publicador (`PUBLICADOR_PORT`, omissão 3011), no formato do Prometheus:

| Métrica | Tipo | O que diz |
|---|---|---|
| `evt_outbox_lag_seconds` | *gauge* | Idade do evento pendente mais antigo. Medida a cada ciclo, mesmo sem linhas — 0 é a resposta certa, não «sem dados» |
| `evt_publish_total{desfecho}` | *counter* | `entregue`, `repetido`, `sem_destino` |
| `evt_publish_errors_total{motivo}` | *counter* | `fila_indisponivel`, `sem_conversor`, `envelope_invalido`, `padrao_de_telefone`, `destino_invalido`, `base_indisponivel` |
| `evt_publisher_leader` | *gauge* | 1 se este processo tem o *lock*, 0 se espera |

O `/metrics` fica no processo do publicador e **não** no `server.ts` do
`worker-canal`: os serviços têm um teste que exige 404 em `/metrics` (KAM-001), e
abrir lá a rota mudava um contrato de outro ticket por conveniência deste.

Não há quem recolha estas métricas: é a mesma lacuna que `docs/isolamento.md` §7
registou para `rls_context_missing_total`. Uma pilha de recolha não tem ticket.

### O atraso medido, e porque a caixa do critério 8 ficou vazia

A medição de carga deste ticket — 15 000 eventos a 50,0/s durante 304 s — correu
duas vezes: com a máquina livre, **p95 = 6,0 s e máximo = 20,8 s**; com outra
*suite* de base de dados ao lado, **p95 = 15,0 s e máximo = 29,5 s**. Contra o
1 s *proposto* no critério, e nas duas com tudo publicado, tudo arquivado, zero
perdidos e zero recuos.

**O atraso não vem de lentidão: vem do período do lote.** A 50 eventos/s, um
lote de 200 — o valor do `docs/tecnica/06` §6.2 — enche-se a cada 4 s, e quando o
publicador corre à capacidade o atraso de um evento é esse período. Duas
correcções entraram pelo caminho e ajudaram sem resolver: o `addBulk` em vez de
um `add` por *job*, que levou o p95 de 9,0 s a 6,0 s, e deixar de dormir os
200 ms entre ciclos quando há trabalho.

O que resolve é **baixar o lote** — o que aumenta o número de transacções — e
isso é calibração. O ambiente da medição (Windows, Docker Desktop, PostgreSQL e
Valkey em contentores e o publicador num terceiro) não é onde um alvo de latência
se calibra — e a diferença entre as duas medições mostra-o: 2,5× de variação só
por haver outra *suite* na máquina. Por isso os números ficam escritos, a caixa
fica vazia, e o que o gate impõe é um **tecto de regressão** de 60 s — generoso
de propósito, porque um tecto que falha por carga do *runner* é um gate que
mente. Quem apanha o publicador parado é a espera de `pendentes() == 0`, antes
do tecto. Decisão aberta 8.

### Porque é um processo do `worker-canal` e não um serviço próprio

O ticket deixa a escolha aberta. A decisão, e a razão: o publicador **escala
para cima com réplicas em espera**, não com concorrência — só o processo que
ganha o *lock* publica. No mesmo processo que o consumidor da fila de entrada
(`server.ts`), que escala horizontalmente, N réplicas do consumidor davam N−1
publicadores a dormir dentro de processos com trabalho a fazer; por isso é um
**segundo processo**, com o seu `node src/publicador.ts`. Um serviço próprio
(`services/evt-publisher`) pagava manifesto, imagem, egressos, entrada em
`PACOTES_NODE`, em `ci/thresholds.yaml` e no `make smoke`, para correr o mesmo
laço com a mesma configuração de base de dados e de fila que o `worker-canal` já
tem.

**O que não foi feito, e é deliberado:** o publicador **não entra no
`infra/compose/docker-compose.dev.yml`**. O `make up` espera por `--wait` e o
`make smoke` percorre `HEALTHZ_TARGETS`; um processo cuja saúde normal é «estou à
espera de ser líder» não cabe nessa forma sem a mudar. O compose de
desenvolvimento ainda não aplica migrações (é o KAM-075), pelo que o publicador
lá não teria tabelas. Fica para o KAM-075/KAM-078, e está dito.

## 7. Partições do arquivo

As partições mensais do `events_log` **não nascem na migração**. Têm nome com
data (`events_log_2026_11`), e uma revisão não as pode criar com nome calculado:
o gate 3b lê a revisão pela árvore sintáctica e um nome que ele não consiga ler é
achado `ilegivel`. Escrevê-las à mão fixava o calendário numa migração — a mesma
classe de defeito que o KAM-008 pagou nos testes.

Por isso a revisão cria **só a partição `DEFAULT`**, que nunca caduca, e as
mensais são obra de um *job* (M+2 no dia 1, `docs/tecnica/06` §6.5; falha =
alerta Sev2). A `DEFAULT` é também a rede: um `INSERT` cuja data não caiba em
nenhuma partição mensal entra nela em vez de rebentar — e a sua contagem é o
sinal de que o *job* não correu.

**O que fica por fazer, e é uma lacuna deste ticket:** o `db/eventos_particoes.py`
que cria as partições mensais e lhes liga a RLS **não existe**. A revisão e o
X-05 estão prontos para ele (a verificação de partições corre sobre todas as que
existirem), mas o *job* em si não foi escrito. Enquanto não existir, todo o
arquivo cai na partição `DEFAULT`: funciona, e perde a vantagem do `DROP` de
partição para a retenção de 24 meses (§7.4). Ver §9, linha 4.

## 8. BullMQ: o que está NÃO VERIFICADO, e o que se leu

O `docs/tecnica/evidencia/E4` §2.10 diz, e **continua a dizer**: «Garantias: a
literatura habitual é at-least-once com jobs stalled re-entregues, mas **não li a
documentação nesta sessão**: NÃO VERIFICADO.» O ticket manda ler a documentação
sobre *jobs* parados e AOF antes de fechar e anexar nota ao PR.

**O estado não muda, e a razão é de método.** Ler o que o BullMQ afirma sobre si
mesmo dá, no melhor caso, **INDÍCIO** — é fonte secundária sobre o próprio
produto — e não CONFIRMADO, porque não medimos nem a re-entrega de *jobs*
parados nem a perda da cauda do AOF. Nesta execução não se leu a documentação do
BullMQ (sem acesso de rede a ela a partir do ambiente de trabalho), pelo que o
que está escrito aqui é o que o desenho **assume**, não o que alguém verificou:

| Afirmação | Estado |
|---|---|
| Um `jobId` repetido não cria um segundo *job* enquanto o primeiro existir na fila | NÃO VERIFICADO. É o que o desenho assume e o que o critério 3 mede **no nosso caso** (um evento republicado deixa um *job*) — a medição é do nosso uso, não da garantia geral |
| Um *job* já consumido e removido deixa de deduplicar | NÃO VERIFICADO, e é por isso que a deduplicação que conta é a do consumidor, por `(consumer, event_id)` (KAM-006) |
| *Jobs* parados são re-entregues | NÃO VERIFICADO. Nada neste ticket depende disso |
| Com AOF `everysec`, a fila perde ≤ 1 s | NÃO VERIFICADO (E4 §2.10 e `docs/tecnica/06` §6.2). A fila do gate corre com `--appendonly yes --appendfsync everysec`, que é a configuração que o desenho assume, mas a perda não foi medida |

O que se faz com isso é o que o §6 manda: **assumir o pior caso**. Em concreto,
três decisões de código:

1. **`jobId` sempre**, e é o `event_id`;
2. **`removeOnComplete: { count: 10 000 }`** em vez de remover ao concluir, para
   alargar a janela em que o `jobId` ainda deduplica. O número é *proposta*, a
   calibrar com os consumidores do KAM-006;
3. **a verdade é o *outbox***. Se a fila perder a cauda do AOF, o `publicado_at`
   já está escrito e o evento **não volta** por este caminho — volta pelo
   reconciliador do §6.5, que é o KAM-006. É uma **lacuna conhecida entre os dois
   tickets**, e está aqui escrita em vez de ficar implícita.

A porta das filas (`packages/core-ts/src/eventos/filas.ts`) existe por causa
disto: um só ficheiro importa `bullmq`, e a decisão é reversível. O próprio E4
nomeia o DBOS como o próximo passo natural, e a D12 (Redis ou Valkey) continua
aberta.

## 9. Para quem produz um evento novo

1. **O `tipo` tem de estar no dicionário** §3.5 («Tipos do Piloto»). Um tipo
   fora dele é um defeito, e o gate 3b apanha-o quando o *schema* existir
   (KAM-007).
2. **Chamar `evt_emitir` na transacção do dado.** Nunca depois do `COMMIT`.
3. **`payload` só com referências.** Sem telefone, nome, morada nem texto; a
   pessoa é `contact_id`.
4. **Declarar as `finalidades`.** Por omissão `{transacao}`. É o que decide quem
   recebe.
5. **Registar a subscrição** em `evt_subscricoes` — `(consumer, tipo,
   versao_max, finalidade)` — na revisão ou no *job* do ticket do consumidor.
6. **Subir a `versao`** em qualquer mudança de significado, remoção ou tipo, e
   registar o conversor (§4).

## 10. O que fica por decidir

| # | Decisão | Estado |
|---|---|---|
| 1 | **O contrato v1 publicado tem nove ou treze campos de topo**, e o `seq` fica no topo ou dentro de `agregado` (§3) | Devolvida — de quem aprova emendas; paga-a o KAM-007 |
| 2 | **`evt_agregado_seq` sem `tenant_id`** (§5): quem conheça o `agregado_id` de outro tenant lê-lhe o contador. Fechar obriga a mudar a chave primária, que é desvio ao §6.1 | Devolvida ao fundador |
| 3 | **Um estado `bloqueado` no `events_outbox`** para o evento sem conversor, que o §6.2 pede e o DDL do §6.1 não tem (§4) | Devolvida — é uma alteração ao DDL do documento |
| 4 | **O *job* das partições mensais** (`db/eventos_particoes.py`) não existe (§7). Sem ele todo o arquivo cai na `DEFAULT` e a retenção por `DROP` de partição não funciona | Sem ticket; nasce com a retenção (KAM-071) ou com o procedimento de *deploy* (KAM-078) |
| 5 | **O *job* de retenção do *outbox* publicado** (7 dias, §7.4): o privilégio existe (`DELETE` ao `kamba_batch`), o *job* não | Sem ticket; idem |
| 6 | **`order.paid` não está no dicionário.** O Contexto do KAM-005 e o catálogo de `docs/tecnica/06` §5 usam-no; o §3.5 do dicionário («Tipos do Piloto») não o tem | Devolvida — paga-a o KAM-007, com o catálogo |
| 7 | **`LISTEN evt_novo` sem quem faça `NOTIFY`.** O publicador escuta o canal (§6.2) e o `evt_emitir` não o avisa: o laço acorda pelo intervalo de 200 ms, que é o limite superior do atraso | Sem ticket; o `NOTIFY` entra quando o atraso medido o justificar |
| 8 | **O limiar de p95 ≤ 1 s** a 50 eventos/s é *proposta* do próprio ticket. **Medido: 6,0 s com a máquina livre, 15,0 s com outra *suite* ao lado**, com tudo publicado e nada perdido — o atraso é o período do lote de 200 (§6.2), não lentidão. Calibrar o lote, e medir em ambiente representativo, é o que falta | Aberta, com o número escrito (§6). A caixa do critério 8 ficou **vazia** |
| 10 | **A emenda 1.9 do dicionário é *proposta*, e este PR apagou a extensão `contact_endpoints.finalidade`** que o KAM-008 tinha em `canon/extensoes.yaml` (ficou redundante com o nome no §3.5). Se a emenda não for ratificada, a extensão tem de ser reposta **no mesmo passo**, ou o gate 3b falha numa superfície do KAM-008 | Registada (ANALISE-20 §4.3) |
| 11 | **A guarda de PII tem falsos positivos em identificadores opacos.** O `+` de `\+?244 ?9[0-9]{8}` é opcional, pelo que qualquer corrida de doze dígitos começada por `2449` é apanhada — e um identificador hexadecimal de 32 caracteres contém uma dessas de vez em quando (aconteceu na medição de carga, ao evento ~8 000 de 15 000). **A consequência é a transacção de negócio a falhar**, porque `evt_emitir` corre nela. Apertar o padrão — exigir o `+`, ou uma fronteira de palavra — muda o §6.1 | Devolvida. O comportamento está fixado por teste, não corrigido |
| 9 | **Quem recolhe as métricas.** Existem em memória e em `/metrics`; não há Prometheus (§6) | Sem ticket, como em `docs/isolamento.md` §7 |

## 11. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-005): revisão `0004`, envelope v1, publicador de instância única, roteamento por finalidade, as três métricas, e o que fica por decidir. Registo de que `uuidv7()` é CONFIRMADO no PG 18.6 fixado, de que a política de uma tabela particionada não cobre a partição, e de que a escada do §6.4 é da DLQ e não do *outbox*. | Equipa KAMBÁ |
