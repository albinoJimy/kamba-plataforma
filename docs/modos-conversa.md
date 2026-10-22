# Modos da conversa e silenciamento do bot (KAM-018)

| Campo | Valor |
|---|---|
| Ticket | KAM-018 |
| Módulo | `packages/core-ts/src/modos/` |
| Revisão | `0016_modos_de_conversa` (descende da `0015`) |
| Depende de | KAM-014 (CHR e `conversations`), KAM-015 (a porta `PreSendGuard`), KAM-019 (`handoffs`), KAM-007 (o contrato do evento) |
| Bloqueia | KAM-034, KAM-109, KAM-114, KAM-117, KAM-118, KAM-123 |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §10.2, §10.3, §12, [`tecnica/00_Arquitectura_Solucao.md`](tecnica/00_Arquitectura_Solucao.md) §12, [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §4, ADR-001, ADR-010, ADR-015 |
| Entregue | A parte que **não** depende de coexistência. Ver §7 |

## 1. O que o módulo faz

Decide **quem tem a palavra** numa conversa — `bot`, `dono`, `humano` ou
`pausada` — e impede o assistente de falar quando a palavra não é dele.

Duas coisas, e as duas sob o mesmo *lock*:

1. a **máquina de estados** (`transicoes.ts`, `modos.ts`): dada uma conversa e um
   gatilho, diz o que acontece, escreve a coluna e emite
   `conversation.mode_changed`;
2. a **verificação pré-envio** (`guarda.ts`): antes de cada envio do bot,
   descarta a mensagem se o modo não for `bot` ou se uma pessoa falou depois de o
   turno começar, registra `suppressed_by_human`, e devolve o cancelamento a quem
   pediu o envio.

## 2. Porque é que o privilégio é o centro deste ticket

A coluna `conversations.mode` nasceu na revisão `0009` (KAM-014) e o
`GRANT UPDATE` que essa revisão deu a `kamba_app` é **por coluna e não inclui o
`mode`**. A razão está escrita lá:

> Um `UPDATE (mode)` concedido aqui era a aplicação a poder silenciar ou
> dessilenciar uma conversa **sem o protocolo que o KAM-018 define**.

O efeito foi visível em dois tickets que vieram depois e que tiveram de deixar
caixas vazias por causa disso:

| Ticket | O que ficou por ligar | Onde está escrito |
|---|---|---|
| KAM-015 | O `PreSendGuard` é chamado **sem o *lock* da conversa** — a porta existe e falha fechada, mas a exclusão mútua pedia a coluna | critério 8, «**Não há *lock***» |
| KAM-019 | O `setBotMuted` do `HandoffProvider` levanta `SemPrivilegioError` | emenda 1.22 do dicionário |
| KAM-022 | A porta `MudarModo` do `ConsentGate` fica **por ligar** | `consentimento.md` §7 |

A revisão `0016` concede `UPDATE (mode, last_human_activity_at)` a `kamba_app` —
que é o que a frase da `0009` manda fazer — e este ticket liga a porta do
KAM-022 e fecha o *lock* do KAM-015. **O `setBotMuted` do KAM-019 continua a
levantar**: ligá-lo é alterar o provedor desse ticket, e isso é alargar escopo
em silêncio. Ver §7.

### O que o `GRANT` não garante, e fica dito

Um `GRANT UPDATE (mode)` a `kamba_app` dá a **toda** a aplicação a capacidade de
escrever a coluna, incluindo por fora da máquina. A contenção não é de
privilégio, e vale a pena dizer o que ela é:

1. o `UPDATE` da máquina leva o predicado da tabela de transições no próprio
   `WHERE` (`AND antes.mode = ANY($4)`), sob `FOR UPDATE` — o padrão que o
   `SQL_AVANCAR_ESTADO` da `0010` fixou;
2. o `CHECK` de quatro valores da `0009` é a última barreira;
3. o `pg_advisory_xact_lock(hash(tenant_id, contact_id))` serializa a transição e
   a verificação pré-envio da **mesma** conversa.

A alternativa — um papel `kamba_modo` com `SELECT` e `UPDATE` nessas duas colunas
e mais nada — **não** se tomou, por duas razões. Um papel não se cria numa
migração (o Alembic corre como `kamba_migrator`, e `db/bootstrap.py` é quem cria
os seis), pelo que um sétimo era alterar o arranque de toda a instância dentro
deste ticket; e um papel só move a fronteira, porque quem o detivesse continuava
a poder escrever qualquer modo — um `SECURITY DEFINER` está vedado pelo X-05 do
*gate* 6 (`ci/secdef_allowlist.yaml`), e uma função `SECURITY INVOKER` exigiria o
mesmo `UPDATE` ao chamador. A decisão sobre o papel devolve-se a quem desenhar a
topologia de ligações (KAM-078).

## 3. A tabela de transições, e os três sítios onde a fonte discorda de si mesma

A `TABELA` do `transicoes.ts` tem **32 células** — quatro modos × oito gatilhos —
e todas estão escritas: um caso por omissão deixava um gatilho novo passar em
silêncio. Doze transitam:

| De | Gatilho | Para | Fonte |
|---|---|---|---|
| `bot` | `echo_do_dono` | `dono` | §10.2 tabela |
| `bot` | `handoff_pedido` | `humano` | §10.2 tabela |
| `bot` | `opt_out` | `pausada` | §10.2 tabela |
| `dono` | `cliente_escreveu` | `bot` | §10.2 tabela (só depois de `silencio_dono_min`) |
| `dono` | `comando_bot` | `bot` | §10.2 tabela |
| `dono` | `handoff_pedido` | `humano` | §10.2 **diagrama** |
| `dono` | `opt_out` | `pausada` | §10.2 tabela |
| `humano` | `handoff_resolvido` | `bot` | §10.2 tabela |
| `humano` | `sem_humano_24h` | `pausada` | §10.2 tabela |
| `humano` | `opt_out` | `pausada` | §10.2 tabela |
| `pausada` | `cliente_reactivou` | `bot` | §10.2 tabela |
| `pausada` | `handoff_pedido` | `humano` | **`E1` §4** |

As outras vinte são `sem_efeito` (o gatilho é legítimo e não muda o modo) ou
`rejeitada` (não faz sentido neste modo). **A distinção não é cosmética:** sem o
`sem_efeito`, cada mensagem do cliente numa conversa em `bot` registava uma
transição rejeitada, e o contador de rejeições media tráfego em vez de defeitos.

### As três divergências, e como se resolveram

**1. `dono → humano`.** O **diagrama** da §10.2 tem-na («dono abre conversa no
Chatwoot»); a **tabela de quatro linhas** da mesma secção não, e o critério 1
também não a nomeia. Resolvida a favor do diagrama, e a razão é de consequência e
não de hierarquia: o dono abre a conversa no Chatwoot de facto, e uma máquina que
rejeitasse essa transição deixava a conversa em `dono` enquanto um agente
responde pelo Chatwoot — o modo passava a mentir sobre quem tem a palavra.

**2. `qualquer → pausada`.** A tabela tem-na; o diagrama só tem `bot → pausada` e
`humano → pausada`. Resolvida a favor da tabela e do critério, que são
explícitos. São três arestas: de `bot`, de `dono` e de `humano`.

**3. `pausada → humano`.** Nem o diagrama nem a tabela a têm. Entra porque o
**Contexto do próprio KAM-018** cita `E1` §4 como CONFIRMADO: «a Messaging Policy
exige caminho de escalonamento a humano em **todas** as conversas». Uma conversa
`pausada` é de um cliente que disse «PARAR» ou que ficou 24 h sem resposta
humana; recusar-lhe uma pessoa quando ele a pede era negar o caminho que a
política exige.

As três estão em [`dividas-documentais.md`](dividas-documentais.md) e a decisão
sobre a §10.2 devolve-se a quem a escreveu.

### A única célula condicional

`dono + cliente_escreveu → bot` só transita se o dono estiver calado há
`silencio_dono_min` — 30 minutos, *proposta*, a calibrar no Piloto (§10.2). A
condição **não** entra no predicado do `UPDATE`: compara-se com o
`last_human_activity_at` que a leitura trouxe, e repeti-la em SQL era uma segunda
implementação da mesma regra. A janela entre a leitura e a escrita é o que o
*lock* fecha — e é por isso que o *lock* não é decoração nesta célula.

Sem actividade humana registada, o silêncio conta como **expirado**: uma conversa
em `dono` sem instante de onde contar devolve a palavra ao assistente em vez de
ficar presa para sempre num modo que ninguém sabe quando começou.

## 4. O que conta como actividade humana

Três gatilhos escrevem `last_human_activity_at`, e todas as escritas passam por
`GREATEST` — a Meta não garante ordem nos *webhooks* (`E1` §5), pelo que um
*echo* antigo pode chegar depois de um recente, e sem o `GREATEST` esse *echo*
fazia o relógio andar para trás.

| Gatilho | Escreve | Porquê |
|---|---|---|
| `echo_do_dono` | sim | escreveu o dono, na app |
| `comando_bot` | sim | também escreveu ele; e o instante faz a guarda suprimir uma resposta de um turno que já corria |
| `handoff_resolvido` | sim | uma pessoa fechou o atendimento no Chatwoot |
| `handoff_pedido` | **não** | quem pede é o grafo ou o cliente: ninguém humano agiu |
| `cliente_escreveu` | **não** | escreveu o cliente, que não é o humano de que o invariante fala. Pô-lo aqui fazia cada mensagem adiar o silêncio do dono, e a conversa nunca voltava ao bot |

A consequência do `handoff_pedido` não escrever é que uma conversa que passa a
`humano` e onde ninguém responde fica com a coluna a `NULL`. O relógio das 24 h
conta então de `handoffs.opened_at` — ver §6.

## 5. A verificação pré-envio, e a janela que fica aberta

O `outbound/adapter.ts` do KAM-015 chama a porta `PreSendGuard` no **passo 3** de
sete, só quando `pedido.doBot`, e o `SQL_ENFILEIRAR` é o passo 4. Daí duas
consequências que explicam o desenho inteiro:

**A linha de supressão é escrita pelo guarda e não pelo adapter.** Quando o
guarda recusa, o adapter devolve `GUARD_REFUSED` e **nunca** enfileira — não há
linha para marcar como `suppressed_by_human`. Quem a escreve é quem sabe que
suprimiu, e escreve-a na mesma transacção do *lock*, por
`idempotency_key` com `ON CONFLICT DO NOTHING`: a repetição deixa **uma** linha.

**O sinal de cancelamento é o valor de retorno.** O guarda devolve `false`, o
adapter converte em `{ok: false, motivo: "GUARD_REFUSED"}` — um dos onze
`MOTIVOS_DE_RECUSA` do dicionário §3.14 —, e quem pediu o envio interrompe o
turno. **Não há aqui chamada ao AGR, nem fila, nem evento**: interromper o turno
é do KAM-025 e a retoma é do KAM-034.

E o `turnoIniciadoEm`: o `Pedido` do KAM-015 ganha um campo opcional com o
`turn.started_at` do pseudocódigo do critério 2. **Um envio do bot que não o
traga é recusado** (`reply_suppressed_total{motivo="sem_turno"}`), porque as duas
alternativas eram piores: deixar passar desligava metade do critério em silêncio,
e tratar qualquer actividade humana como posterior ao turno calava o bot para
sempre em qualquer conversa que já tivesse tido um *handoff* resolvido.

### A janela residual

O guarda larga o *lock* no `COMMIT` da sua transacção, e o adapter só depois
enfileira e chama a Meta. Um *echo* que chegue nesse intervalo **não** é
apanhado: é a «janela residual de corrida = latência do *echo*» que a §10.3
declara, e é **NÃO MEDIDA** (R6/L6; critério de saída em KAM-100). Fechá-la
exigia manter o *lock* da conversa aberto durante a chamada HTTP à Meta — uma
transacção de base de dados a durar o tempo de uma chamada de rede, por conversa.

O que o desenho garante é o que o critério 3 pede: **0 mensagens do bot depois de
o *echo* estar registado**.

## 6. O *job* das 24 h, e de onde conta o relógio

`pausarPorInactividade(tenantId)` é uma **função** e não um *job* agendado, pela
decisão que a `0005` já escreveu para a retenção do outbox: «uma função é
testável agora e chamável depois». O agendador nasce com KAM-071/KAM-078.

**Idempotente pelo predicado e não por uma marca escrita.** Depois da primeira
passagem as linhas já estão em `pausada` e o `mode = ANY($3)` deixa de casar;
correr duas vezes seguidas pausa N e depois 0, e não há coluna de controlo a
manter — é a razão pela qual a revisão `0016` não cria coluna nenhuma.

**O relógio tem duas origens, por esta ordem:**

```sql
COALESCE(
  c.last_human_activity_at,
  (SELECT max(h.opened_at) FROM platform.handoffs AS h
    WHERE h.tenant_id = c.tenant_id AND h.conversation_id = c.id)
) < $2
```

Uma conversa onde **nunca** houve resposta humana tem a primeira a `NULL`, e é
precisamente o caso que o critério descreve («24 h sem humano após handoff»): o
instante é o do *handoff*, que vive em `handoffs.opened_at` (KAM-019). O `max`
porque uma conversa pode ter tido mais do que um.

**E se os dois forem `NULL`, a conversa não é pausada** — fica em `humano`
indefinidamente. É deliberado e é o lado seguro: ficar em `humano` mantém o bot
calado, e o invariante da §10.2 é «o bot nunca interrompe uma conversa em modo
dono/humano». Uma conversa nesse estado só pode vir de uma escrita que não passou
por esta máquina; pausá-la por omissão era deixar o assistente retomar uma
conversa cuja história não conhecemos.

**Sem *lock*, e isso é escolha escrita.** Antes do *job* o modo é `humano` e
depois é `pausada`, e o guarda suprime o envio do bot nos dois: qualquer
intercalação com ele dá o mesmo desfecho — 0 mensagens. Um *lock* por linha num
`UPDATE` em lote obrigava a N transacções para não ganhar propriedade nenhuma.

## 7. O que fica de fora, e porquê

| O que | Onde está |
|---|---|
| **A transição `bot→dono` por *echo* real** | A detecção precisa de `smb_message_echoes` com o `wamid` ausente de `outbound_messages`, e essa tabela é **coexistência: KAM-017**, que por sua vez está atrás de `ext:KAM-100` (três cartões SIM +244 reais) e de `ext:KAM-102`. A **célula** está na tabela e tem teste; quem dispara o gatilho é quem conseguir detectar o *echo*. A caixa do critério 1 fica **vazia** |
| **A métrica `echo_latency_ms`** | Mede a diferença entre o carimbo da Meta e a recepção de um *echo*, e o critério 8 pede p50/p95 de **≥ 30 *echoes* reais em *staging*** com números +244. É o critério de saída do risco **L6/R6** e é trabalho de KAM-100. Uma métrica declarada e sempre a zero é pior do que ausente: um painel que a mostre a zero diz «a latência é nula» quando o que se passa é que ninguém a mede. A caixa do critério 8 fica **vazia** |
| **A detecção do `comando_bot`** | O `/bot` é uma mensagem que o dono escreve na app, e chega pela mesma via do *echo*: KAM-017. A célula `dono + comando_bot → bot` está entregue e testada |
| **O `setBotMuted` do `HandoffProvider`** | Continua a levantar `SemPrivilegioError` (KAM-019). O privilégio que o impedia existe agora, mas ligá-lo é alterar o provedor de outro ticket — e a caixa do critério dele fica como está, com a razão já escrita na emenda 1.22. É um candidato a emenda do KAM-019, não trabalho deste PR |
| **A `v3` de `conversation.mode_changed`** | O tipo **já existe** no catálogo (`contratos/eventos/conversation.mode_changed/`, v1 e v2, do KAM-007/KAM-159) e não é este ticket que o acrescenta — o critério 6 supunha que era. O que não cabe nele é o domínio: a carga é `{thread_id, channel_mode}` com `channel_mode ∈ {ai, humano, desligado}` e `additionalProperties: false`, pelo que **`dono` e `humano` saem indistinguíveis** no barramento. Uma `v3` de quatro valores é uma quebra de contrato com compatibilidade a provar no *gate* 7, e o catálogo é do KAM-007: inventá-la aqui era decidir por outro ticket |
| **A medição do «≤ 5 s em HND»** | O critério 6 pede que o estado visível no Chatwoot acompanhe a mudança em ≤ 5 s (*proposta*). Não há simulador de Chatwoot — o KAM-019 escreveu-o — e o `setBotMuted` não é executável, pelo que não há caminho a medir |
| **A detecção do «PARAR»** | KAM-022, que chama o `onOptOut` deste módulo. A porta `MudarModo` está **ligada** (`portaDoConsentGate`) |
| **A retoma do grafo depois do *handoff*** | KAM-034 |
| **O envio do aviso de conversa pausada** | KAM-022. O gatilho `cliente_reactivou` é distinto do `cliente_escreveu` de propósito: a reactivação exige o aviso, e quem decide que ele saiu é esse ticket |

## 8. Como se prova

| Propriedade | Onde |
|---|---|
| As 32 células da tabela, uma a uma; o silêncio do dono no limite inclusivo; o `origensDe` | `packages/core-ts/tests/modos.transicoes.test.ts` (*gate* 4) |
| A ordem das instruções (o *lock* antes da leitura que decide), a corrida perdida sem evento, a supressão antes do cancelamento, o `onOptOut` por contacto, o mapeamento do evento | `packages/core-ts/tests/modos.test.ts` (*gate* 4) |
| O *lock* a serializar de verdade; as 100 intercalações com semente fixa e reproduzíveis; duas conversas do mesmo canal independentes; 0 *jobs* do AGR com o `Chr` verdadeiro; o relógio das 24 h a contar do `handoffs.opened_at`; o privilégio por coluna; o X-03 | `packages/core-ts/tests_bd/modos.bd.test.ts`, pela *suite* `db/tests_modos/` (*gate* 8) |
| A cobertura de `src/modos/`, no estrato `critico` | `db/tests_modos/test_modos.py`, que lê o limiar de `ci/thresholds.yaml` |

**A semente das 100 intercalações está escrita no ficheiro** (`0x4b414d18`) e o
ensaio corre-as **duas vezes**, comparando as sequências de desfecho. É essa
segunda passagem que impede um `Math.random()` de voltar: com um aleatório do
sistema, as duas sequências divergiam e o teste falhava. Um teste de corrida que
não se reproduz é um teste que falha uma vez por mês e que ninguém consegue
investigar.

### O que a revisão adversarial mudou neste código

Quatro achados, e os quatro eram defeitos reais. Os quatro têm bateria **e**
mutação: uma correcção sem mutação é uma correcção que nada impede de ser
desfeita.

| O defeito | Porque importava | A correcção |
|---|---|---|
| O `outcome` do registo levava o gatilho, e um dos oito — `sem_humano_24h` — não cabe na gramática do campo: um segmento é letras com até três dígitos **no fim**, ou um número, e `24h` não é nenhum dos dois | Em modo estrito, que é o do CI, o `Logger` **levanta** — e uma transição rejeitada, que é um resultado normal, passava a excepção não tratada no caminho de um *webhook*. É a mesma armadilha que o `codigoParaRegisto` do KAM-015 pagou com o `-1` | `outcome: "modo_rejeitado"`, fixo. O gatilho está na etiqueta de `conv_mode_rejected_total`, que é onde a lista é fechada. Bateria com os **oito** gatilhos e um `Logger` estrito |
| A métrica contava a transição **antes** da emissão do evento | As duas escritas vivem na mesma transacção: com a emissão a levantar, o `UPDATE` é desfeito e um contador em memória não é desfeito com ele — o painel mentia por cima | A contagem passou para depois da emissão, nos dois sítios (`#aplicar` e o *job* das 24 h) |
| A porta do `ConsentGate` prometia não lançar, e o `disparar` lança `ConversaDesconhecidaError` | O gate chama a porta **depois** de escrever a prova *append-only* e de enviar o aviso: a excepção fazia o `tratar` falhar com os dois já escritos, e o *job* repetia-se sobre um estado que nunca vai melhorar — a conversa não volta a existir | A porta apanha **essa** e só essa. Qualquer outro erro sobe, incluindo um modo que o código não conheça |
| Um *fail-open* de um caracter: o `last_human_activity_at` era comparado directamente, e um `new Date("lixo").getTime()` é `NaN` | **Qualquer** comparação com `NaN` é falsa, pelo que um valor ilegível fazia o envio **passar** — o contrário do que o guarda existe para fazer | O `instanteDaLinha` tem três respostas (`Date`, «não houve», «ilegível») e a terceira **suprime** |

### O que a prova por mutação mudou neste código

A primeira passagem deixou **seis** sobreviventes, e as seis valeram a pena.
Três eram lacunas de teste e viraram testes; três eram código que nenhum teste
podia matar porque nenhum caminho o alcança.

**As três que viraram testes:**

| A mutação | Porque sobreviveu | O teste que a mata |
|---|---|---|
| Apagar o `FOR UPDATE` da subconsulta do `SQL_MUDAR_MODO` | Todos os testes passavam pela máquina, e a máquina toma o *advisory lock* — que serializa tudo e esconde a diferença | «o UPDATE ganha a corrida **sem** o lock»: corre a consulta crua em duas ligações, sem *lock* nenhum. Sem o `FOR UPDATE`, as duas escritas passam |
| Trocar o `GREATEST` por atribuição directa, no `SQL_MUDAR_MODO` | Nenhum teste enviava um instante **mais antigo** depois de um recente | «um echo fora de ordem não faz a actividade humana andar para trás», nas duas escritas da coluna. O caso é real: a Meta não garante ordem nos *webhooks* (`E1` §5) |
| Idem, no `SQL_REGISTAR_ACTIVIDADE_HUMANA` | A mesma razão | O mesmo teste, na sua segunda metade |

**As três que eram código morto**, e a resposta não foi inventar-lhes um teste:

Duas eram guardas do `transicoes.ts` — um `if (celula.para === estado.mode)` no
`transitar` e um `de !== para` no `origensDe` — e sobreviveram porque **nenhuma
célula da tabela aponta para o próprio modo**: o «não acontece nada» escreve-se
`para: null`. As **guardas saíram**, e o invariante passou a ser **afirmado** em
vez de defendido: `tests/modos.transicoes.test.ts` tem «nenhuma celula aponta
para o proprio modo», e é esse teste que impede uma célula assim de entrar. Uma
guarda inalcançável dá a ilusão de proteger e não protege nada.

A terceira apagava o `validarPayload` do `emitirModoMudado`, e sobreviveu porque
o `payloadDoModo` é tipado e não consegue produzir um payload inválido **hoje**.
A chamada **fica** — é a regra do KAM-007, «validar depois é descobrir o defeito
com o evento já publicado», e custa uma linha —, e o que de facto a protege é um
teste de paridade entre as chaves que se montam e as que o catálogo exige, nos
dois sentidos, como o `chr/invocacao.ts` já faz para o `agent_invocation`. A
mutação saiu, com a razão escrita em `db/mutacoes.py`: matá-la exigia inventar um
caminho que nenhum código percorre, e inventá-lo era pior do que declarar o
limite.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira versão, KAM-018 — a parte que não depende de coexistência. A revisão `0016` (dois `GRANT UPDATE` por coluna, zero DDL), a tabela de 32 células com as três divergências da §10.2 resolvidas e declaradas, o `PreSendGuard` sob `pg_advisory_xact_lock`, o `onOptOut` por contacto, o *job* das 24 h com o relógio em `handoffs.opened_at`, e a porta `MudarModo` do KAM-022 **ligada**. Ficam de fora, com a razão escrita: a transição `bot→dono` por *echo* (KAM-017) e a métrica `echo_latency_ms` (KAM-100, critério de saída do L6). | Equipa KAMBÁ |
