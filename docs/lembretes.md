# Lembretes de marcação e *template utility* (KAM-048)

| Campo | Valor |
|---|---|
| Ticket | KAM-048 |
| Módulo | `services/com/src/servicos/reminders/` |
| Revisão | **nenhuma** — este ticket não acrescenta esquema. Usa a `0010_saida_de_canal` (`outbound_messages`, `message_templates`), a `0015_consentimento` (`consent_event`, `consent_actual`, `consent_texts`), a `0009_conversas` (`conversations`) e a `0025_servicos` (`servicos.bookings`, `servicos.services`) |
| Depende de | KAM-047 (módulo `servicos`), KAM-015 (Outbound), KAM-022 (consentimento), KAM-007 (contrato de `booking.reminder_due`), KAM-038 (subscrição da vertical Serviços) |
| Bloqueia | — |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §8.2, §8.3, §8.4, [`tecnica/02_Agent_Runtime_Verticais.md`](tecnica/02_Agent_Runtime_Verticais.md) §8.2, [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §1, §4, ADR-007, ADR-009, ADR-010, ADR-018 |

## 1. O que o módulo faz

**Lembra uma marcação no dia anterior, pelo canal mais barato que esteja aberto, e
não lembra o que já não existe.** O evento `booking.created` agenda um despertar
para `inicio − 24 h`; quando ele chega, o módulo relê a marcação, verifica o
opt-in, e envia — mensagem livre se a janela de 24 h da Meta ainda está aberta,
*template utility* `lembrete_marcacao` se já fechou.

Três propriedades que são o ticket inteiro:

- **uma mensagem por lembrete**, por chave composta `booking_id:reminder:T-24h`;
- **nunca texto livre fora da janela**, e nunca um *template* que a Meta não
  aprovou ou recategorizou;
- **nenhum valor da mensagem é composto por um modelo** — a data, a hora e o
  nome do serviço vêm de *facts* da marcação lidos da base.

## 2. O que este ticket **não** escreveu, e já existia

Medido contra `refs/remotes/publico/main` antes da primeira edição, porque a
diferença entre «escrevi o contrato» e «o contrato existia e liguei-o» é a
diferença entre duas entregas:

| Peça | Onde já estava |
|---|---|
| Contrato de `booking.reminder_due`, `v1` e `v2`, com exemplo cada | `contratos/eventos/booking.reminder_due/`, publicado pelo KAM-007 |
| Espelho do *payload* em Python e TypeScript, e o catálogo | `libs/py-core/src/kamba_core/eventos/contratos.py`, `packages/contracts/src/eventos.gerado.ts` (gerados) |
| O tipo no dicionário canónico | `canon/dicionario.yaml`, três menções |
| A subscrição da vertical Serviços | `registry/servicos.yaml`, `booking.reminder_due` v1 |
| Decisão de janela, portão do *template*, tarifas e custo | `packages/core-ts/src/outbound/`, KAM-015 |
| Idempotência de saída | `UNIQUE (tenant_id, idempotency_key)` da revisão `0010` e o `ON CONFLICT` do `SQL_ENFILEIRAR` |
| *Gate* de consentimento | `packages/core-ts/src/consentimento/`, KAM-022 |
| `booking.cancelled` pelo caminho do cliente | `services/com/src/servicos/eventos.ts`, escrito pelo KAM-047 **para este ticket** |

A última linha merece ser lida: a nota do `emitirBookingCancelled` do KAM-047
diz por extenso que ela existe porque, sem o evento de cancelamento, «o KAM-048
continua a achar que a marcação existe — e envia um *template utility* **pago** a
lembrar uma marcação que o cliente cancelou». O portão do estado, na §4 abaixo, é
a outra metade dessa frase.

## 3. A versão do evento é a `v1`, e a escolha não é indiferente

Há duas publicadas. A diferença entre elas é **uma**: o `enum` de `finalidades`
do envelope ganha `partilha_estafeta` e `notificacao_dono` na `v2`. O `payload` é
byte a byte o mesmo — `(booking_id, inicio_at)`, os dois obrigatórios,
`additionalProperties: false`.

Consome-se a `v1` porque é a que a **subscrição** declara, e a verificação
`subscricoes` do *gate* 7 confronta a subscrição com o catálogo: consumir a `v2`
sem mexer na subscrição era declarar uma coisa e ler outra, e mexer na subscrição
para ganhar duas finalidades que um lembrete não usa era alargar escopo para
nada.

## 4. Os portões, pela ordem, e porque é essa a ordem

```text
1. a marcação, da base      estado `confirmada` e `inicio` actual
2. o opt-in                 consentimento válido para a finalidade `transacao`
3. o destino                conversa, canal e janela
4. o corpo                  livre com janela aberta, template com ela fechada
5. o Outbound               a chave, a decisão e a mensagem
6. a recusa de template     bloqueia, avisa o dono, registra
```

**(1) é a única leitura que pode dizer «não há nada a lembrar», e é de graça**:
corre na transacção que (2) e (3) iam abrir de qualquer maneira. Pô-la depois do
consentimento fazia o *gate* de opt-in correr para marcações canceladas — o que
não está errado, está a mais, e mede uma coisa sobre um cliente a propósito de um
acto que já não existe.

**(2) vem antes de tudo o que custa** porque é o único portão cuja violação é de
outra natureza: uma marcação cancelada é o sistema a funcionar, e um lembrete sem
opt-in é tratamento de dados sem base. O critério manda que «o motivo seja
auditado», e auditar implica que a decisão aconteça antes de qualquer efeito
observável de fora.

**(6) não lê a `message_templates`.** O `decidir` do Outbound já o faz e devolve
`TEMPLATE_NOT_APPROVED`, `TEMPLATE_BLOCKED` ou `MARKETING_NOT_ALLOWED` pela ordem
das causas. O que é deste módulo é o que se faz com a recusa: bloquear, avisar o
dono pela porta `AvisarDono`, e registar o motivo na métrica.

E a ordem do Outbound protege a chave: lá a decisão corre **antes** da linha em
`outbound_messages`, pelo que um *template* recusado **não gasta** a chave de
idempotência. Um lembrete que falhou por *template* por aprovar sai no dia em que
a Meta aprovar, com a mesma chave.

## 5. A idempotência é da base; a chave é nossa

«O mesmo evento entregue cinco vezes produz uma mensagem» não se cumpre com um
`SELECT` antes de enviar: entre o `SELECT` e o `INSERT` cabe a segunda entrega.
Cumpre-se com a unicidade da revisão `0010` e o `ON CONFLICT ... DO NOTHING
RETURNING` do `SQL_ENFILEIRAR`.

O que este módulo fornece é a chave, e a propriedade dela é o que se mede:

```text
chaveDoLembrete(booking_id)  ->  "<booking_id>:reminder:T-24h"
```

**Sem relógio e sem o identificador do evento.** Uma chave com o `event_id` lá
dentro dava cinco chaves para cinco entregas do mesmo evento — e o EVT entrega
«pelo menos uma vez», pelo que cinco entregas são o caso normal e não o
patológico.

A etiqueta `T-24h` é **texto da chave** e não o valor da antecedência. Se a
antecedência for calibrada, a etiqueta muda com ela e as chaves antigas
continuam a existir: uma mensagem já enviada não se reenvia por se ter mudado um
número.

### A chave é protegida das recusas anteriores à linha, e **só dessas**

A primeira versão desta secção dizia que «um *template* recusado não gasta a
chave» e parava aí. É verdade — e é meia verdade, que a revisão adversarial
mediu:

| Quando a recusa acontece | A linha em `outbound_messages` | A chave |
|---|---|---|
| **antes** da linha: `WINDOW_CLOSED`, `TEMPLATE_NOT_APPROVED`, `TEMPLATE_BLOCKED`, `MARKETING_NOT_ALLOWED`, `STATE_REFUSED`, forma inválida | não se escreve | livre — o lembrete sai no dia em que a causa desaparecer |
| **depois** da linha: `SEND_FAILED`, `NO_RECIPIENT`, `RATE_LIMITED`, e a supressão do guarda do KAM-018 | fica escrita, em `failed` ou `suppressed_by_human` | **gasta** |

E o que isso provocava: na entrega seguinte do mesmo evento, o `SQL_ENFILEIRAR`
devolve vazio, o adapter lê a linha pelo `SQL_POR_CHAVE` — que **não filtra
`state`** — e responde `{ok: true, repetido: true}`. Lido como «enviado», é uma
mensagem que nunca saiu contada como entregue.

A correcção: num `repetido`, o módulo lê o `state` da linha e decide contra os
`TERMINAIS` do KAM-015. Um estado de progresso é um lembrete que já saiu; um
estado terminal é `CHAVE_GASTA`, travado e contado. E uma repetição **não conta**
no `booking_reminder_sent_total`, que é a decisão que o `adapter.ts` do KAM-015
já tinha tomado para si: o contador mede mensagens, e cinco entregas do mesmo
evento são uma mensagem.

## 6. A finalidade de consentimento é `transacao`, e isso é uma leitura

O critério escreve «opt-in registado para a categoria *utility*», e as duas
palavras vivem em domínios diferentes:

- ***utility*** é uma **categoria de facturação da Meta** — `service`, `utility`,
  `marketing`, `authentication` (`outbound/contrato.ts`, §3.14 do dicionário);
- **`transacao`** é uma **finalidade de tratamento** — o domínio do §3.1 do
  dicionário, que o `consent_event.purpose` guarda.

Não há finalidade chamada `utility`, e inventá-la era pôr vocabulário da factura
da Meta dentro do registo de consentimento. A leitura que o módulo escreve, e que
fica como **leitura** e não como facto: o lembrete de uma marcação é o acto
comercial, logo `transacao` — a mesma escolha que o KAM-047 fez para o envelope
de `booking.created` e que o KAM-022 fez para o aviso do primeiro contacto. O que
**não** é é `marketing`, e isso é o que o critério protege: a frequência de
*marketing* é zero no Piloto.

**Hoje, em qualquer base recém-migrada, nenhum lembrete sai** — e o estado é o
correcto. A `consent_texts` nasce **vazia** (revisão `0015`), porque o texto é
jurídico e está «a confirmar por parecer» (KAM-104); sem versão vigente não há
aviso mostrado, logo não há consentimento registado, logo não há lembrete. O
motivo que sai é `SEM_TEXTO_VIGENTE`, auditado como os outros, e é a mesma falha
fechada que o `ConsentGate` aplica ao AGR.

## 7. Como se prova que nenhum valor vem de um modelo

Esta é a parte que um ensaio ingénuo não prova. Verificar **nomes de campo** fica
verde com um valor inventado lá dentro, porque o nome de um campo não diz de onde
veio o valor — e é esse o defeito que uma revisão adversarial apanhou noutro
ticket, num ensaio que olhava para nomes de etiqueta e não para a origem dos
valores.

O construtor dos parâmetros tem **uma** entrada, com dois campos, os dois lidos
da base: não há porta de modelo, não há argumento de texto, não há omissão que se
preencha com prosa. Sobre isso, quatro medições, e cada uma apanha uma coisa que
as outras não apanham:

| Via | O que mede | O que apanha |
|---|---|---|
| 1 | **que campos foram lidos** — os factos entram embrulhados num `Proxy` que registra cada acesso, e o conjunto lido tem de ser **exactamente** o declarado | um parâmetro constante, que não lê campo nenhum; e um valor de outra origem, que lê um campo a mais |
| 2 | **o que muda quando o facto muda** — varia-se só o campo declarado; o parâmetro tem de mudar, e os que vêm de outro campo de ficar iguais | um parâmetro que diz vir de um facto e é fixo |
| 3 | **o que não entra** — um campo a mais nos factos, com texto da forma que um modelo escreveria | a forma literal de «um valor composto pelo LLM» |
| 4 | **o que o módulo alcança** — a lista de importações de `template.ts` tem de ser só o seu próprio vocabulário | uma aresta nova para um gerador de texto, antes de ela aparecer numa saída |

Nenhuma das quatro olha para o nome de coisa nenhuma. E a propriedade vale nos
**dois** caminhos: a mensagem livre é o mesmo corpo aprovado com as posições
preenchidas pelos mesmos parâmetros, e não um segundo texto escrito ao lado — com
um texto à parte, o caminho mais frequente de um cliente activo ficava fora da
prova.

## 8. O fuso é o de Luanda, e a forma da data foi medida

`Africa/Luanda`, que é a omissão de `tenants.fuso_horario` (revisão `0007`) e o
fuso com que o `metering` fecha o mês. É UTC+1 sem horário de verão, pelo que um
`inicio_at` de `23:30Z` é `00:30` do **dia seguinte** em Luanda — e o ensaio de
fuso é exactamente esse: uma formatação em UTC daria o dia anterior, e o cliente
apareceria um dia antes.

O `dateStyle` é `long` e não `medium`, e a razão é medida e não estética: o
KAM-115 mediu as três formas, e `09/11/2026` são oito dígitos separados por
barras que a régua de forma de telefone do `meta-sim` apanha. O mês por extenso
não tem corrida de dígitos que chegue a sete, e há um ensaio a prendê-lo.

## 9. A remarcação fecha-se em duas metades, e nenhuma basta sozinha

```text
jobIdDoLembrete(booking_id, inicio_at)  ->  "lembrete:<uuid>:<iso>"
```

**No agendamento:** o `inicio_at` está no `jobId`. Sem ele, o `jobId` de uma
marcação era sempre o mesmo e a fila deduplicava o *job* novo contra o antigo —
remarcar de quinta para sábado deixava agendado o despertar de quarta.

**No disparo:** relê-se `estado` e `inicio` da base. O *job* antigo encontra
outro `inicio` e devolve `MARCACAO_REMARCADA` sem enviar.

Um `jobId` discriminante sozinho deixava o *job* velho a lembrar a marcação
antiga; uma reverificação sozinha nunca agendava o novo. O «um lembrete activo
por marcação» é a propriedade do par: dos dois *jobs* que podem estar na fila
depois de uma remarcação, só um pode produzir mensagem — e a chave de
idempotência garante que mesmo esse produz uma só.

## 10. As métricas, e porque é que o custo não é um contador daqui

```text
booking_reminder_sent_total{canal}        counter  service | utility
booking_reminder_blocked_total{motivo}    counter  os nossos portões + as recusas do Outbound
booking_reminder_scheduled_total{desfecho} counter  agendado | a razão de não agendar
```

**O custo não tem contador aqui.** O custo de um lembrete é o custo da mensagem
que o Outbound enviou, e quem o acumula é o `meta_cost_usd_total` dele; um segundo
acumulador sobre os mesmos envios somava o mesmo dinheiro duas vezes num painel
que não tinha como saber.

**O «por *tenant*» não vai numa etiqueta**, e isso não é escolha deste ticket —
é o que o KAM-015 já decidiu e escreveu: as bibliotecas de métricas desta casa
recusam por gramática uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$` e um
`tenant_id` é um UUID com hífenes, pelo que a chamada **levanta**; e o `OBS-I` de
`seguranca/ameacas_stride.md` chama-lhe re-identificação. O por-*tenant* sai do
`SQL_LEMBRETES_DO_TENANT`, por consulta.

São **duas** consultas, e isolam as linhas de lembrete pelo segmento `:reminder:`
da chave — o mesmo mecanismo que o `SQL_AVISOS_ENVIADOS` do KAM-022 usa para
contar avisos sem coluna nova, e pela mesma razão: a chave que impede o lembrete
de sair duas vezes é a que diz quais linhas são lembretes. Uma coluna `origem` em
`outbound_messages` era DDL para uma informação que a chave já carrega.

```text
SQL_LEMBRETES_DO_TENANT   tentativas e falhas por canal, no período de criação
SQL_CUSTO_DOS_LEMBRETES   linhas facturadas por categoria, no período de entrega
```

**Era uma, e ela inventava dinheiro.** A revisão adversarial confrontou-a com o
`SQL_CUSTO_DO_TENANT` do KAM-015 e com o `microUsdDe`, que escreve por extenso
que «uma categoria que não conhecemos não se converte num número inventado»:

- um `ELSE 4000` facturava a 0,004 USD qualquer categoria desconhecida — e a
  Meta acrescenta categorias;
- `WHEN NOT (pricing->>'billable')::boolean THEN 0` não excluía nada com o
  `billable` **ausente**: a condição é `NULL`, o `CASE` seguia para o `ELSE` e a
  linha era cobrada;
- somava sobre `created_at` quando a cobrança é na **entrega** (`E1` §1,
  CONFIRMADO), pelo que uma mensagem criada no dia 1 e entregue no dia 2 caía no
  período errado;
- e os literais das tarifas eram uma **terceira** cópia, não comparada com nada.
  As duas que existem — `outbound/tarifas.ts` e `config/meta_rates.yaml` — são
  confrontadas como texto pelo `TestTarifas` da suite de *gate* 8 do KAM-015.

Hoje nenhuma das duas converte: contam-se linhas, e quem chama multiplica pelo
`microUsdDe` — o único sítio desta casa onde uma categoria se torna um número, e
o que recusa uma que não conhece.

E as falhas cobrem os **dois** estados terminais, que entram por parâmetro a
partir dos `TERMINAIS` do KAM-015. Contavam só `failed`, e uma linha
`suppressed_by_human` entrava em «tentados», ficava fora de «falhados» e dava
custo zero — isto é, lia-se como um lembrete entregue e grátis.

**E ninguém executa estas cadeias.** A nota do módulo afirmava que a suite do
*gate* 8 as corria, e era falso. O que há é as colunas e os tipos lidos contra o
inventário de `db/tests/test_inventario.py` e um ficheiro de ensaio que prende
por **texto** os perigos concretos que as mutações da revisão exploraram — uma
asserção sobre o texto de uma consulta não apanha um erro de sintaxe, um tipo
errado nem um plano mau, pelo que o estado disto quanto a execução é **NÃO
VERIFICADO**. Credor na §11.

**Uma limitação dita:** ao contrário do caso do KAM-022, este `LIKE` **não** se
resolve pelo índice `outbound_messages_idempotency_uq`, porque o padrão começa
por `%` — a chave começa pelo `booking_id`. Com o `tenant_id` fixo pelo
predicado, é um varrimento das linhas desse *tenant* no período e não da tabela,
e a pergunta é de painel e não de caminho de envio. Fica *proposta* de calibração
se o volume a tornar lenta, e a alternativa é a coluna que hoje se recusa.

## 11. O que fica por ligar, com credor

| O que falta | Porquê | Credor |
|---|---|---|
| A implementação do porto de fila sobre BullMQ | O `FilasBullmq` do core serve o publicador de eventos e não tem `delay`; o `services/com` não tem processo de fila nem dependência directa de `bullmq`, e decidir o anfitrião é arquitectura. É a mesma lacuna, com a mesma razão, que o KAM-045 deixou escrita para a expiração de reservas | **KAM-071**, dono do varrimento agendado |
| A emissão de `booking.reminder_due` quando o *job* dispara | Depende do *worker* acima: é ele que, ao despertar, põe o evento no outbox | **KAM-071** |
| A antecedência **por tenant** | O valor de 24 h está numa constante, *proposta*. Ler um valor por *tenant* precisa de uma coluna que nenhuma revisão tem — a `0007` dá `tenants.fuso_horario` e os limites de `entitlements.limites`, nenhum deles uma antecedência de lembrete | **KAM-055** (cadeia Alembic) ou o ticket que calibrar o número com dados do Piloto |
| A subscrição de `booking.created` no COM | O consumidor genérico com recibo em `platform.events_consumed` é do KAM-006, e nenhum processo do COM subscreve hoje. O que está entregue é a função que esse consumidor chama | **KAM-071** |
| A ligação da porta `AvisarDono` ao painel | É a costura entre dois módulos que não se conhecem, e quem a liga é quem tem o painel — a mesma escolha que o `avisarPainel` do `hnd/resposta.ts` fez | **KAM-019** / **KAM-031** |

## 12. Um conflito entre dois consumidores do mesmo evento

**Dois caminhos falam com o cliente sobre o mesmo `booking.reminder_due`, com
chaves de idempotência diferentes — logo duas mensagens e não uma.** Não é um
defeito deste ticket e não se corrige aqui; fica registado com a medição.

E tem uma causa documental, que é o que torna isto previsível em vez de
acidental: **dois documentos dão o consumo ao AGR e o ticket dá os módulos ao
COM.** O [`tecnica/03_Core_Comercio_Medusa.md`](tecnica/03_Core_Comercio_Medusa.md)
§12 escreve, na linha de `booking.reminder_due`, «`AGR` (mensagem livre ou
*template utility*)», e o [`eventos.md`](eventos.md) dá-lhe consumidor `AGR`; os
Detalhes Técnicos do KAM-048 escrevem «Módulos
`services/com/servicos/reminders/{schedule,deliver,template}`». O ticket
prevalece — é o nível 8 da ordem de fontes e os dois documentos são o nível 9 —,
e foi por isso que a entrega se fez no COM. Mas o §12 já tinha levado o KAM-038 a
escrever texto para o par no AGR, e é daí que vêm os dois caminhos. A metade
textual está na dívida **194**; a metade que é decisão é a desta secção.

| Caminho | Chave | O que envia |
|---|---|---|
| AGR, vertical Serviços (KAM-038) | `{consumer}:{event_id}:{accao}` — a forma do §6.3, fixada no §3.5 do dicionário (`notificacao.py`, `chave_da_accao`) | Texto fixo **sem números**: «Lembramos a sua marcação. Se precisar de mudar, diga-nos.» (`handlers.py`, `TEXTOS`) |
| COM, este ticket (KAM-048) | `booking_id:reminder:T-24h` — a forma do critério 2 | O lembrete com serviço, data e hora, livre ou por *template* |

As duas chaves são canónicas e nenhuma pode ceder sem alterar canon. **Hoje não
há duplicado**, e a razão é que o caminho do AGR não está ligado: a porta
`OutboundPorLigar` devolve `sem_template` e o `Notificador` levanta
`NotificacaoNaoEntregue`, pelo que o evento vai à DLQ em vez de produzir
mensagem. O duplicado nasce no dia em que o Outbound do KAM-015 for ligado ao
AGR.

A nota do `handlers.py` do KAM-038 já resolveu a versão vizinha deste problema —
duas **verticais** a notificar sobre o mesmo pagamento — e a solução foi mudar a
chave do mapa de textos de `tipo` para `(vertical, tipo)`. Aqui o par não é
`(vertical, tipo)`: são dois **serviços**, e nenhum dos dois mapas o vê.

Decidir qual dos dois caminhos fala é escolha de produto e atravessa dois
tickets, pelo que **vai ao fundador** e não se decide aqui. As duas leituras que
se oferecem, para que a decisão não comece do zero: ou o AGR deixa de ter texto
para este par (e o `handlers.py` ganha uma entrada em `ACCOES_POR_LIGAR` com este
ticket por credor); ou este módulo deixa de enviar e passa a devolver a
`Notificacao` ao AGR — o que troca a chave do critério 2 pela do §6.3 e obriga a
emendar o critério.

## 13. O corpo do *template* e a política de antecedência

Esta secção existe porque faltava, e a falta foi medida: a caixa da DoD
«documentação do *template* e da política de antecedência actualizada» estava
marcada com uma linha de evidência que apontava para secções que não diziam
nenhuma das duas coisas. A revisão adversarial contou — zero ocorrências do corpo
do *template*, zero das posições `{{n}}`, zero do limiar de 2 h — e a caixa estava
marcada. É o defeito que esta casa fecha: marcar por memória do trabalho feito.

### O corpo

**É *proposta*, e a aprovação pela Meta não é garantida.** A submissão do conjunto
padrão por *tenant* é do EPIC-02 (KAM-091); o que este ticket define é o texto, e
o que ele consome é o estado — pela porta do Outbound, que lê a
`message_templates`.

```text
nome      lembrete_marcacao
idioma    pt_PT        (pt_AO não existe como código — NÃO VERIFICADO, E1)
categoria utility      (transaccional; a frequência de marketing é zero no Piloto)

corpo     Lembrete: tem marcação de {{1}} no dia {{2}} às {{3}}.
          Para remarcar ou cancelar, responda a esta mensagem.
```

As três posições, e de onde vem cada uma:

| Posição | Valor | Facto de origem |
|---|---|---|
| `{{1}}` | o nome do serviço | `servicos.services.nome`, por `SQL_SERVICO` |
| `{{2}}` | a data, no fuso de Luanda | `servicos.bookings.inicio_at`, por `SQL_MARCACAO` |
| `{{3}}` | a hora, no mesmo fuso | o mesmo `inicio_at` |

**Duas posições saem do mesmo facto**, e tinha de ser: um `timestamptz` não tem
duas colunas, e a Meta numera por posição no corpo aprovado. É a `PROVENIENCIA`
do `reminders/contrato.ts`, e é contra ela que a §7 mede.

O mesmo corpo serve a **mensagem livre**, com as posições preenchidas — ver a §7
para a razão de não haver um segundo texto.

### A política de antecedência

Os dois valores são ***proposta*** e estão em constantes com a unidade no nome,
não no DDL: um número no `CHECK` de uma coluna obrigava a uma revisão de base de
dados para o calibrar.

| Valor | Constante | O que decide | Onde se calibra |
|---|---|---|---|
| **24 h** | `ANTECEDENCIA_MS` | o instante do lembrete é `inicio − 24 h` | com dados do Piloto; o critério 1 di-lo «por tenant», e o por-*tenant* não existe — ver a §11 |
| **2 h** | `MINIMO_PARA_ENVIO_MS` | uma marcação criada com menos de 24 h de antecedência só leva lembrete **imediato** se o início estiver a **mais** de 2 h | com dados do Piloto |

O limiar de 2 h protege custo e utilidade ao mesmo tempo: um lembrete que chega
uma hora antes de uma marcação que o cliente acabou de fazer é um *template
utility* **pago** para lhe dizer o que ele escreveu há cinco minutos. O limite é
«mais de», logo exactamente 2 h **não** envia — a leitura conservadora.

Os dois têm **asserção-âncora** no `servicos.reminders.schedule.test.ts`, e a do
limiar de 2 h entrou por achado da revisão adversarial: sem ela, toda a fronteira
era medida contra a própria constante, e pôr-lhe 4 h deixava os ensaios verdes
com o critério 1 violado à letra.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Primeira versão, KAM-048. O agendamento em `inicio − 24 h` com o `inicio_at` no `jobId`, os portões do disparo, a chave composta `booking_id:reminder:T-24h`, a escolha de canal pela janela, o portão do *template* ligado ao KAM-015, o *gate* de consentimento ligado ao KAM-022, as quatro vias que provam a proveniência dos parâmetros, e os três contadores. Sem revisão de base de dados. Registra o que já existia e não se reescreveu (§2), o que fica por ligar com credor (§11) e o conflito de dois consumidores do mesmo evento (§12), que vai ao fundador. | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | **Revisão adversarial: catorze achados, e dois faziam o módulo não enviar nada.** O §13 nasce porque faltava — a caixa da DoD que o invocava estava marcada com uma linha de evidência que apontava para secções que não diziam nem o corpo do *template* nem a política de antecedência; contado, zero ocorrências das três posições e do limiar de 2 h. O §5 passa a dizer a verdade inteira sobre a chave: ela é protegida das recusas **anteriores** à linha e não das posteriores, e um `repetido` lido como «enviado» era uma mensagem que nunca saiu contada como entregue. O §10 deixa de prometer um custo que a consulta inventava, e passa a ter duas consultas que não convertem categorias em dinheiro, as falhas a cobrir os dois estados terminais, e a limitação dita de que ninguém as executa. As correcções de código, os ensaios que entraram e o que a revisão deu por limpo estão no bloco do ticket em `../specs/EPIC-04_Core_Comercio.md`. | Equipa KAMBÁ |
