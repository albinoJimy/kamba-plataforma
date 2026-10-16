# Consumo de eventos — idempotência, DLQ e reconciliador

| Campo | Valor |
|---|---|
| Documento | `docs/consumo.md` |
| Ticket | KAM-006 — Consumidores idempotentes, `events_consumed` e DLQ |
| Estado | Revisão `0005` aplicada; *wrapper* de consumo (TypeScript e Python), DLQ, `once()` e reconciliador implementados; gate 8 com a *suite* `tests_eventos_consumo` activa. As caixas marcadas e as vazias estão nomeadas na secção de verificação do bloco do ticket |
| Âmbito | O lado do **consumidor**: tornar uma entrega *at-least-once* num efeito exactamente-uma-vez, decidir o que fazer com o que falha, e repor o que a fila perdeu. Nada do lado do produtor — isso é `docs/eventos.md` |
| Fontes | `docs/tecnica/06` §6.3, §6.4, §6.5; `docs/tecnica/00` §6.1; ADR-009, ADR-013; `specs/02` §3 (emenda 1.10) |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. A tese, numa frase

A fila entrega **pelo menos uma vez**; o efeito acontece **exactamente uma
vez** porque a marca de consumo e o efeito partilham a transacção.

```
BEGIN
  SET LOCAL app.tenant_id = envelope.tenant_id
  n = INSERT INTO events_consumed (consumer, event_id, …) ON CONFLICT (consumer, event_id) DO NOTHING
  se n == 0: COMMIT; duplicado — e não se faz mais nada
  se exige_ordem: ler o último seq do agregado
  se o tipo causa transição: ler o estado do agregado
                  → Adiar          (a pré-condição ainda não chegou)
                  → ForaDeOrdem    (vem atrasado E a transição é inválida)
  efeito(bd, envelope)        ← na MESMA transacção
COMMIT
```

Em duas transacções haveria dois modos de falha, e os dois acontecem: efeito sem
marca (repete-se à próxima entrega) ou marca sem efeito (perde-se para sempre).
O segundo é o pior, e é por isso que a marca não se escreve antes.

O código está em `packages/core-ts/src/eventos/consumo.ts` e, espelhado, em
`libs/py-core/src/kamba_core/eventos/consumo.py`. Os dois lados existem porque
há consumidores nos dois idiomas, e um teste de paridade
(`TestParidadeDoTypeScript`) lê o TypeScript **como texto** e confronta os
números, o SQL e as assinaturas — duas implementações do mesmo contrato só se
mantêm honestas se houver uma máquina a confrontá-las.

## 2. O que existe na base

A revisão `0005` cria quatro tabelas e duas funções de retenção. O dicionário
tem-nas na **emenda 1.10**.

| Tabela | Chave | Para quê |
|---|---|---|
| `events_consumed` | `(consumer, event_id)` | A janela de deduplicação. 90 dias |
| `events_dlq` | `id` (`bigint IDENTITY`), único em `(consumer, event_id)` | O efeito que ninguém aplicou |
| `evt_dlq_aprovacoes` | `(dlq_id, aprovador)` | Os dois aprovadores do descarte |
| `evt_acoes` | `idempotency_key` | O `once(key, fn)` dos efeitos externos |

Duas **restrições** que não estão no documento e que esta revisão acrescenta,
declaradas como desvios aditivos:

- `events_consumed.tenant_id`, `agregado_tipo`, `agregado_id` e `agregado_seq`
  são `NOT NULL`. O §6.3 deixa-os nulos; sem eles a tabela não entra na RLS por
  tenant nem serve a leitura do último `seq`;
- `evt_subscricoes_payment_exige_ordem`: `tipo LIKE 'payment.%'` **obriga**
  `exige_ordem`. É a primeira metade do critério 7 — a configuração errada é
  recusada pela base, e não detectada no arranque.

A segunda metade é a verificação de arranque (`exigirOrdemNosPagamentos`, em
`services/worker-canal/src/consumidor.ts`), que continua a valer se alguém
largar a restrição. **As duas existem porque uma guarda que depende da outra não
é uma guarda.**

### As duas retenções

`evt_limpar_consumidos(p_dias int DEFAULT 90)` **recusa** menos de sete dias: a
janela tem de exceder a re-entrega da Meta, ou um evento re-entregue volta a
produzir efeito. `evt_limpar_dlq(p_dias int DEFAULT 30)` apaga 30 dias **após a
resolução** e nunca apaga uma entrada aberta, por mais velha que seja.

**Os *jobs* que as chamam não existem.** O privilégio existe (`EXECUTE` ao
`kamba_batch`); o agendador é o KAM-071 ou o KAM-080. Ver §7.

## 3. Dois papéis, e a razão de serem dois

Esta é a parte que a primeira versão errou, e vale registá-la.

| Trabalho | Papel | Porquê |
|---|---|---|
| Consumir | `kamba_app` | É quem tem `INSERT` em `events_consumed`, `INSERT` na DLQ e `SELECT/INSERT/UPDATE` em `evt_acoes` |
| Reconciliar, e publicar `evt_dlq_open` | `kamba_batch` | Procura o que se perdeu em **todos** os tenants e lê `evt_subscricoes`; tem `BYPASSRLS` e é auditado |

`kamba_app` é `NOBYPASSRLS` e as três tabelas têm `ENABLE`, `FORCE` e a política
`tenant_iso`. Daí a primeira instrução da transacção ser o `SET LOCAL
app.tenant_id`, **tirado do envelope** — que é o arquivo a dizer de quem o
evento é, e não a fila, que trouxe um ponteiro. Sem ele o `INSERT` não falha por
privilégio: falha o `WITH CHECK`, e a mensagem fala de *row-level security* e
não de uma variável esquecida.

O mesmo vale fora da transacção do consumo, e por isso duas funções abrem a sua:

- `paraDlq()` — a transacção do consumo já fez `ROLLBACK` quando se chega aqui,
  e com ela foi-se o contexto. Sem um `SET LOCAL` próprio, o evento que falhou
  seis vezes desaparecia sem deixar linha;
- `once()` — é chamado de dentro **e** de fora da transacção do consumo, e
  depender de um `SET LOCAL` alheio fazia a mesma função funcionar num sítio e
  falhar no outro. Duas transacções curtas, com o efeito externo **entre** as
  duas.

Para a leitura do envelope — que acontece antes de haver transacção — o `tenant_id`
vem do *job*: o publicador põe-no nos dados e o reconciliador também. É um
ponteiro, não uma autoridade: se não for o do evento, a leitura sob RLS não vê
nada e falha fechada.

### Uma ligação por fila

`concurrency: 1` limita a **fila**, não o processo: dezasseis filas são
dezasseis trabalhos ao mesmo tempo. Com uma ligação partilhada, os `BEGIN` e
`COMMIT` de dezasseis transacções intercalavam-se na mesma sessão — um `COMMIT`
de uma fila fechava a transacção de outra, e a marca de consumo de um evento
ficava confirmada com o efeito de outro. Por isso a opção do
`criarTrabalhadores` é `ligar()`, uma fábrica, e cada fila abre a sua à primeira
entrega (e não ao arranque: uma réplica que sirva quatro filas não abre
dezasseis sessões).

Nenhuma suite de execução vê isto com um evento de cada vez, e é por isso que o
acoplamento está fixado por texto em `db/tests/test_consumo_contrato.py`.

## 4. Três saídas, e a diferença entre elas

A decisão não está no `consumir()` — está no `processar()` de
`packages/core-ts/src/eventos/trabalho.ts`, que se testa **sem fila e sem
BullMQ**, com um cliente SQL falso.

| Saída | Quando | O que acontece |
|---|---|---|
| `Adiar(5 s)` | A pré-condição ainda não se verifica (`payment.confirmed` antes de `aguarda_pagamento`) | Tenta-se outra vez. Esgotadas as tentativas: DLQ com `adiado_sem_resolver:` — **nunca** a transição aplicada à força |
| `ForaDeOrdem` | O evento vem atrasado **e** a transição não é válida | DLQ à primeira, com `erro = 'fora_de_ordem'`. Não há tentativa que resolva um atraso |
| qualquer outro erro | Falha técnica | Recua pela escada; na sexta, DLQ com a mensagem do erro |

A pré-condição de estado é verificada **fora** do `exige_ordem`, e isto foi uma
correcção: com ela dentro, uma subscrição com `exige_ordem = false` sobre um tipo
que causa transição aplicava-a sem verificação nenhuma — e a restrição do DDL só
obriga `exige_ordem` em `payment.%`, pelo que o buraco era alcançável por
configuração. A **ordem** continua dependente de `exige_ordem`: sem o último
`seq` não se sabe se o evento vem atrasado, e sem isso a saída é sempre `Adiar`.

### A escada, e o acoplamento que a tornava decorativa

1 s, 5 s, 30 s, 2 min, 10 min, sobre 1 + 5 tentativas — a escada do §6.4, em
`ESCADA_DO_CONSUMIDOR`. O publicador tem uma escada **diferente** de propósito
(`ESCADA_DE_RECUO`, tecto de 30 s): ali o que recua é a republicação de um
evento que ninguém consumiu; aqui o que recua é um efeito de negócio cuja
pré-condição pode levar minutos a chegar.

**O BullMQ só consulta a escada se o *job* a pedir.** A estratégia de recuo do
*worker* (`backoffStrategy`) só é chamada quando as opções do *job* dizem
`backoff: { type: 'custom' }` — e quem cria o *job* é o **publicador**. Com o
`exponential` que lá estava, o recuo real era 1 s, 2 s, 4 s, 8 s, 16 s: a
contagem de tentativas do critério 2 ficava certa e os **intervalos** errados,
que é a pior combinação porque passa despercebida. Está corrigido em
`filas_bullmq.ts`, e os dois ficheiros estão presos por
`test_o_job_pede_a_escada_do_consumidor`.

O atraso de um `Adiar` **não** é o degrau da escada: são duas razões diferentes
para esperar, e um `Adiar` a herdar o degrau esperava dez minutos por uma
encomenda que ia ser paga a seguir. O `backoffStrategy` recebe o erro e
distingue-as.

E **não** se chama `moveToDelayed`: o BullMQ só aceita esse movimento se o que se
lançar a seguir for um `DelayedError` dele. Com outro erro, o *job* já não está
activo e o tratamento da falha rebenta a dizer que falta o *lock* — um evento
adiado ficava preso em vez de ser retentado.

## 5. A DLQ, e quem a fecha

Uma entrada na DLQ não é um erro técnico: é **um efeito de negócio que ninguém
aplicou**. Um `payment.*` ou um `order.paid` ali é cliente que pagou sem
confirmação — Sev1, e é por isso que a severidade se decide pelo **tipo** e não
pela contagem. As restantes alertam depois de uma hora aberta.

A métrica é `evt_dlq_open{tipo}`, a primeira de etiqueta aberta do repositório:
admite nomes com a gramática `familia.verbo` e tem tecto (`MAXIMO_DE_TIPOS = 64`)
— uma métrica que cresce sem fim deixa de ser observabilidade. É um *gauge* da
realidade e não um contador de chamadas, pelo que quem o publica é o processo,
pela ligação de operação, com `publicarAbertas()` — e não quem acabou de falhar
um evento. Quem consome tem só `INSERT` na DLQ, e isso é deliberado: o `id` é
sequencial, e um papel sujeito a RLS que o lesse media o volume de falhas do
vizinho.

**A regra de alerta não existe.** A severidade está classificada e a métrica
exposta; o Prometheus e as regras são o KAM-080. Ver §7.

Fechar uma entrada é acto de operação, com ferramenta própria:

```bash
python db/dlq.py listar
python db/dlq.py reprocessar <id> --operador <nome>
python db/dlq.py descartar <id> --aprovador <nome>
```

Três regras da ferramenta, e não do costume de quem opera: reprocessar e
descartar recusam-se **pelo lado ruidoso** sobre uma entrada já fechada;
descartar um `payment.*` exige **dois aprovadores distintos** (a primeira
chamada registra e recusa); e isto **não re-enfileira nada** — quem volta a pôr
o evento na fila é o reconciliador, e a mensagem di-lo por extenso.

## 6. O reconciliador: o buraco que o outbox não fecha

O publicador marca `publicado_at` **depois** do `add` à fila. Se o Redis perder
o *job*, a linha do outbox já está publicada e o publicador não lhe volta a
tocar: para ele, o trabalho está feito. O evento ficou arquivado em
`events_log` e nunca chegou a consumidor nenhum.

A verdade usada para o detectar não é a fila — que já perdeu a informação — é a
diferença entre **o que o arquivo diz que foi publicado** e **o que o consumo e
a DLQ dizem que chegou** (a consulta do §6.5). Corre a cada cinco minutos, com o
**seu** *lock* consultivo (7102, o seguinte ao do publicador): com o do
publicador, uma réplica em espera para publicar ficava em espera para repor.

O `jobId` é o `event_id`, como na publicação: se o *job* original ainda existir,
o BullMQ recusa o duplicado; e se chegar duas vezes, o consumo idempotente
absorve. São as duas redes, e as duas são precisas.

A janela (24 h) e a carência (10 min) do §6.5 são **parâmetros** e não literais
no SQL, por uma razão de prova: com os literais dentro da consulta, verificar a
reposição levava dez minutos de espera real por execução. Os valores por omissão
são os do documento, e há um teste que mostra que a carência de produção protege
o que acabou de ser publicado.

## 7. O que se prova, e onde

| Propriedade | Onde | Como |
|---|---|---|
| A decisão (classificação de erros, escada, `once`) | `packages/core-ts/tests/eventos.consumo.test.ts`, `eventos.dlq.test.ts` | Base falsa, sem fila |
| O espelho em Python e a paridade com o TypeScript | `libs/py-core/tests/test_eventos_consumo.py` | 59 testes (80 com a máquina de estados); o TypeScript lido como texto |
| O esquema, os privilégios e os inventários fechados | `db/tests/` | PostgreSQL real, `downgrade base` incluído |
| Os acoplamentos entre ficheiros | `db/tests/test_consumo_contrato.py` | Texto: o que nenhuma execução distingue de coincidência |
| A DLQ operada (dois aprovadores, códigos de saída) | `db/tests/test_dlq.py` | PostgreSQL real |
| O isolamento das três tabelas | `db/tests_isolamento/` | Dois tenants, leitura cruzada, gate 6 |
| **A transacção, a contagem de tentativas e a reposição** | `db/tests_eventos_consumo/` | PostgreSQL **e fila** reais |
| A recusa de arranque | `services/worker-canal/tests/consumidor.test.ts` | A função, sem levantar o processo |

### O relógio acelerado, e porque é honesto

A *suite* com fila corre com a escada em cinco degraus de 300 ms e a carência da
reposição a zero. É o que os «Testes Requeridos» do ticket pedem, e a razão é
aritmética: com a escada do §6.4, cada um dos testes que esgota as seis
tentativas esperava 756 s, e são dois; com a carência do §6.5, cada verificação
da reposição esperava dez minutos.

O que o relógio acelerado **não** faz é esconder os valores: a escada real está
provada em `TestEscada`, nos dois idiomas, e o acoplamento que a torna efectiva
em `test_o_job_pede_a_escada_do_consumidor`. O que a *suite* com fila mede é a
**contagem** de tentativas e o caminho — que é o que nenhum teste sem fila diz.

## 8. Para quem escreve um consumidor

1. **A subscrição entra em `evt_subscricoes`** — `(consumer, tipo, versao_max,
   finalidade)`. Um `payment.*` sem `exige_ordem` é recusado pela base.
2. **O efeito recebe `(bd, envelope)`** e corre **dentro** da transacção. Usa
   essa ligação e nenhuma outra: outra ligação não está na transacção, e o que
   ela escrever sobrevive a um `ROLLBACK`.
3. **Efeito externo passa por `once()`**, com a chave
   `consumer:event_id:acção` — a mesma que vai no `Idempotency-Key` do pedido ao
   terceiro, para que quem o recebe possa também deduplicar.
4. **Nada de contadores próprios de tentativas.** O número vem da fila: com duas
   réplicas, um contador próprio contava metade cada uma e o evento ia para a
   DLQ ao dobro das tentativas — ou nunca ia.
5. **Um tipo que causa transição exige máquina de estados.** Sem ela o consumo
   recusa-se a correr, porque o ADR-013 manda que `paga` só se alcance por
   evento autenticado.

## 9. O que fica por decidir

| # | Decisão | Estado |
|---|---|---|
| 1 | **A regra de alerta Sev1 não existe.** A severidade está classificada (`severidade()`, `eSev1()`) e a métrica exposta; não há Prometheus nem Alertmanager no repositório | Sem ticket próprio: é o KAM-080 (métricas, logs e alertas). A caixa do critério 5 está **vazia** por causa disto |
| 2 | **Os *jobs* de retenção não existem.** As duas funções e o `EXECUTE` ao `kamba_batch` existem; quem as chama todos os dias não | Sem ticket; nasce com a retenção (KAM-071) ou com o procedimento de *deploy* (KAM-078) |
| 3 | **O efeito do processo do `worker-canal` é um esqueleto.** Regista e mais nada: as verticais que consomem eventos são o KAM-038 e o *core* de comércio é o KAM-041 | Por desenho. Quem acrescentar uma vertical troca o efeito e mais nada |
| 4 | **`evt_acoes` é nome em proposta**, como o próprio ticket diz. Está no dicionário na emenda 1.10, marcado como tal | Devolvida — de quem aprova emendas |
| 5 | **O consumidor precisa de duas ligações com papéis diferentes** (`KAMBA_CONSUMIDOR_DB_URL` e `KAMBA_CONSUMIDOR_OPS_DB_URL`), e o cofre do KAM-010 ainda não distribui a segunda | Registada. Hoje é configuração de ambiente; o inventário de segredos é o KAM-010 |
| 6 | **Quem recolhe as métricas.** Existem em memória e em `/metrics`; não há Prometheus | Sem ticket, como em `docs/eventos.md` §10 |

## 10. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-006): revisão `0005`, *wrapper* de consumo nos dois idiomas, DLQ com Sev1 por tipo e descarte a dois aprovadores, `once()`, reconciliador com *lock* próprio, e a *suite* `tests_eventos_consumo` no gate 8. Registo de três defeitos que só a base e a fila reais mostraram: o consumo precisa do contexto de tenant na transacção, cada fila precisa da sua ligação, e o *job* tinha de pedir a escada do consumidor para ela ser consultada. | Equipa KAMBÁ |
