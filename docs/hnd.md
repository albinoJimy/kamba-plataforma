# O HND — a passagem a humano

| Campo | Valor |
|---|---|
| Ticket | KAM-019 — HND: `HandoffProvider` e Chatwoot (Agent Bot API, espelho por *inbox* de tipo API) |
| Código | `packages/core-ts/src/hnd/` (onze ficheiros), revisão `0011` |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §11 e §14, [`tecnica/02_Agent_Runtime_Verticais.md`](tecnica/02_Agent_Runtime_Verticais.md) §11 e §14 |
| Nomes | [`../specs/02_Dicionario_de_Dados_Canonico.md`](../specs/02_Dicionario_de_Dados_Canonico.md) §3.15 (emendas 1.22 e 1.23) e §3.32 (emenda **1.42**, a fronteira da saída de `waiting`) |
| Testes | `packages/core-ts/tests/hnd.*.test.ts` (*gate* 4), `db/tests_handoff/` (*gate* 8) |

---

## 1. O que o HND é, em duas frases

É o que acontece quando o assistente deixa de responder e uma pessoa passa a
responder. Do lado de dentro são duas tabelas e uma porta; do lado de fora é uma
conversa que aparece no Chatwoot de uma PME, com o resumo do que já se disse.

**O que o HND não é:** não é o sítio onde se decide *se* a passagem acontece
(isso é o `conversations.mode`, e as transições são do KAM-018), nem o que
retoma o grafo depois (o *compare-and-set* da retoma é do KAM-034), nem quem
provisiona as contas em massa (KAM-091).

---

## 2. Doze nomes que não existiam

A emenda 1.22 do dicionário veio **antes** do código, e não por formalidade: o
*gate* 3b lê o AST de cada migração e recusa um nome que o §3 não cubra, pelo
que a revisão `0011` não podia nascer sem ela. Mas a razão mais forte é outra —
**dois dos tipos da interface não tinham campos definidos em documento nenhum.**

O `docs/tecnica/01` §11.1 escreve `mirrorMessage(ctx, m: MirrorMessage)` e
`onHumanEvent(handler: (e: HumanEvent) => Promise<void>)`, e nem ele, nem o §11
do `02`, nem o dicionário diziam o que um `MirrorMessage` ou um `HumanEvent`
levam dentro. O §3.15 é a primeira vez que se diz, e o que **não** está nos
campos é o ponto: sem telefone, sem BSUID, sem `contact_id`. O provedor
identifica a pessoa pela conta de contacto dele, e o ADR-010 proíbe mandar os
nossos identificadores para fora.

---

## 3. O que o spike mediu, e que nenhuma leitura dava

O critério 8 pedia um spike de um dia contra um Chatwoot real, e ele correu:
v4.18.0 fixado por digest, em compose local com dados sintéticos, sem
credenciais da Meta, a escutar só em `127.0.0.1`. O registo passo a passo está
em [`evidencia/KAM-019-bot-open.md`](evidencia/KAM-019-bot-open.md) e o veredicto
é **`O TOKEN DO BOT CHEGA`**.

**Mas o valor dele não foi a resposta: foi o caminho até lá.** A implementação
estava escrita e as baterias estavam verdes, e o spike mostrou que metade das
chamadas do provisionamento recebia 401. A lição vale mais do que o ticket:

> **Um duplo prova que o nosso código chama o que pretendíamos chamar. Não prova
> que o terceiro aceita a chamada.**

Os sete factos, todos **CONFIRMADO**:

| O que se perguntou | O que o Chatwoot respondeu |
|---|---|
| `pending → open` com o *token* do *agent bot* | **200**, com `"current_status":"open"`. É o **L7** do `tecnica/01` §18, que estava NÃO VERIFICADO. O plano B — um utilizador-serviço com *token* da Application API — **não é preciso para o estado** |
| As três variáveis da Meta no `env` do contentor | **ausentes**. É a prova que o critério 2 pedia, e não se consegue de um ficheiro de compose: uma variável pode entrar por `.env`, por herança ou embutida na imagem |
| *Token* da Platform API em `/api/v1/accounts/…` | **401**, «Access to this endpoint is not authorized for bots». Ele cria contas, utilizadores e bots, e mais nada |
| Quem pode criar o *inbox* | Um **utilizador** criado por `/platform/api/v1/users` e ligado à conta por `account_users`, com o `access_token` dele |
| Ligar o bot ao *inbox* | **Obrigatório** (`set_agent_bot`). Sem isso, `POST /conversations` dá **404** e o bot não recebe os *callbacks* do *inbox* |
| `source_id` inventado na conversa | **404**. Tem de ser o `contact_inboxes[0].source_id` que a criação do contacto devolveu |
| *Token* do bot a criar contactos | **401**. Logo o do utilizador é preciso **em tempo de execução**, e não só no provisionamento |

### A sequência do provisionamento, pela ordem medida

```text
1. POST /platform/api/v1/accounts                         [plataforma]  -> account_id
2. POST /platform/api/v1/users                            [plataforma]  -> user_id + access_token
3. POST /platform/api/v1/accounts/{conta}/account_users    [plataforma]  (role: administrator)
4. POST /api/v1/accounts/{conta}/inboxes                   [utilizador] -> inbox_id
5. POST /platform/api/v1/agent_bots                        [plataforma]  -> bot_id + access_token
6. POST /api/v1/accounts/{conta}/inboxes/{inbox}/set_agent_bot [utilizador]
```

Cada passo depende do anterior, e **é por isso que a ordem não é arbitrária**: o
utilizador precisa da conta para se lhe ligar, o *inbox* precisa do *token* do
utilizador, o `set_agent_bot` precisa dos dois identificadores. Se isto falhar a
meio fica o que já foi criado — não há transacção do lado do provedor e não a
podemos inventar. O que se escolheu é a ordem que deixa o destroço mais
inofensivo: um bot ligado a nada não recebe nada, e um *inbox* sem bot não
encaminha nada. O que **não** se pode deixar é a linha na nossa base sem os
identificadores, e é por isso que ela só se escreve depois disto devolver.

### Três segredos, e dois objectos

| Segredo | O que faz | Onde vive |
|---|---|---|
| `chatwoot_platform_token` | cria contas, utilizadores e bots | **só** no `ProvisionadorDoChatwoot` |
| `chatwoot_user_token` | cria *inboxes* e **contactos** | por conta, no cofre; a referência em `handoff_accounts.user_token_ref` |
| `chatwoot_bot_token` | abre, fecha e escreve em conversas | por conta, no cofre; a referência em `handoff_accounts.token_ref` |

**São dois objectos e não um**, e isso é o `tecnica/08` §3.6 à letra: «o *token*
da Platform API (poderoso) só existe no serviço de *provisioning*, nunca no
AGR». A primeira versão deste módulo tinha uma classe só, com o *token* da
plataforma como campo **obrigatório** do mesmo objecto que abre conversas:
qualquer processo que precisasse de abrir uma conversa tinha de o ter em
memória. Um parâmetro distinto não é um processo distinto, e era só isso que
estava garantido.

### A chave do contacto é opaca, e nunca o nosso `contact_id`

A conversa precisa de um contacto, e o contacto precisa de um `identifier`. A
primeira versão punha lá o nosso `contact_id` — o que era uma fuga de
identificador nosso para fora, contra o ADR-010, **no mesmo módulo** que diz, na
nota do `MirrorMessage`, que isso não se faz; e que de qualquer modo dava 404,
porque o provedor quer um `source_id` que ele próprio emitiu.

O que entra agora é uma `chaveDoContacto`: opaca, estável, derivada **por quem
chama**, que é quem tem o contexto para a derivar (o `contact_hmac_prefix` do
*logger* é a mesma família de ideia). O HND não recebe o identificador, e por
isso não o pode deixar escapar.

## 4. A idempotência é da base, e é de dois tipos

| O que | O mecanismo | Porque não em código |
|---|---|---|
| `openHandoff` | `INSERT ... ON CONFLICT (handoff_id) DO NOTHING RETURNING` | O `handoff_id` é **derivado** (`hash(thread_id, ordinal)`, §11.1): cinco chamadas concorrentes calculam o mesmo valor sem se falarem, e colidem na chave primária. Um `SELECT` antes do `INSERT` perdia a corrida |
| `ensureAccount` | chave primária `(tenant_id, provedor)` | «Uma conta por PME» (critério 1) passa a ser propriedade da **base**. Um `ensureAccount` concorrente bate na chave |
| `mirrorMessage` | `jobId` da fila **é** o `wamid` | A reconciliação que o §14 pede é a de-duplicação que a fila já faz, e o recuo dela é o *retry*. Uma tabela de fila ao lado de uma fila era um segundo sítio para a mesma verdade |
| `close` duplicado | `WHERE status = ANY($3)` | O segundo `UPDATE` não casa e devolve zero linhas. Dois *webhooks* duplicados chegam a **dois processos**, e só a base os serializa |

### A chave primária é texto, e isso é deliberado

O §2 do dicionário pede `uuid` para a coluna que referencia. Aqui a chave é
`text` porque é **derivada**, e é essa a propriedade que a torna a chave de
idempotência: nenhum `gen_random_uuid()` faz cinco processos chegarem ao mesmo
valor. Um `uuid` obrigava a uma segunda coluna com o resumo e a unicidade nela —
a mesma coisa com um nível de indirecção a mais.

### A `UNIQUE` que fecha o outro lado

A chave primária impede dois registos para o mesmo *tenant*. A
`handoff_accounts_conta_uq UNIQUE (provedor, account_id)` impede **a mesma conta
do provedor em dois *tenants***, que é o furo que o X-10 procura: um
`ensureAccount` que devolvesse por erro a conta de outra PME ficava gravado sem
ninguém ver. As duas são precisas, e nenhuma substitui a outra.

---

## 5. Os dois vocabulários de estado, e a ponte

A assinatura do `close` usa `outcome ∈ {resolved, timeout, cancelled}`; a tabela
usa `status ∈ {waiting, resumed, timeout, cancelled, degraded}`. **Duas das três
chamam-se igual e uma não**, e é isso que torna a tradução perigosa — um `as`
funcionava em dois casos e mentia no terceiro.

| `outcome` | `status` |
|---|---|
| `resolved` | **`resumed`** |
| `timeout` | `timeout` |
| `cancelled` | `cancelled` |

E os dois que nenhum desfecho escreve: `waiting`, onde uma passagem nasce, e
`degraded`, onde fica quando o provedor não respondeu. O teste afirma que a
**partição é total** — um estado novo que apareça falha ali, e é isso que obriga
quem o acrescentar a decidir de que lado fica, em vez de o deixar sem tradução e
descobri-lo quando um `close` não gravar nada.

### De onde é que o HND **pode** fechar: só de `degraded` (emenda 1.42)

O `ESTADOS_QUE_FECHAM` era `["waiting", "degraded"]` e passou a `["degraded"]`.
Não é arrumação: com `waiting` lá dentro, o `close` deste módulo era o **segundo**
escritor da saída de `waiting` da `platform.handoffs`, e corria **antes** do
*compare-and-set* do AGR — que é o gatilho do `Command(resume=…)`. Um colega
marcava a conversa como resolvida, o HND escrevia `resumed`, o CAS não casava
linha nenhuma, a rota respondia 200 `repetido`, e o `interrupt()` do
`handoff_wait` ficava pendente **para sempre**: o cliente não recebia nem a
resposta nem a mensagem de alternativas, e a varredura dos prazos não o encontrava
porque filtra `waiting`. Medido na
[`analises/ANALISE-35-KAM-034-handoff-idempotente.md`](analises/ANALISE-35-KAM-034-handoff-idempotente.md)
(achado 1); decidido na emenda 1.42 do dicionário (§3.32).

A partição que fica diz-se em duas frases, e as duas têm ensaio:

> **o HND nunca tira uma passagem de `waiting`; o AGR nunca tira uma de
> `degraded`.**

E são as **três** saídas de `waiting` e não só o `resolved`: a rota de retoma
retoma o grafo com `resolved` e com `cancelled`, e a varredura dos prazos com
`timeout`, pelo que sair de `waiting` por qualquer delas matava um `Command` da
mesma maneira.

**O que isto custa, e fica escrito:** das três, só duas têm hoje quem as peça — o
`resolved` vem do *callback* e o `timeout` da varredura dos prazos. O `cancelled`
tinha o `close(handoffId, 'cancelled')` do §11.1, que deixou de poder sair de
`waiting`, e **nenhum caminho deste repositório pede a retoma com `cancelled`**: a
desistência do cliente não está implementada em ticket nenhum — não estava antes
e continua a não estar. Quem a fizer pede a retoma, no mesmo sítio de onde o
`resolved` sai.

### O que corre no lugar do fecho: `POST /internal/resume`

O `receber`, no desfecho `resolved`, faz três coisas por esta ordem:

1. **confere a passagem** (`SQL_THREAD_DA_PASSAGEM`): traz o `contact_id` da
   conversa a que ela aponta — o `handoff_id` é irreversível
   (`sha256(thread_id:handoff_seq)`), pelo que o `thread_id` do corpo tem de vir
   da linha — e o `external_id` que nós gravámos. **Três saídas, e não duas:** a
   conversa bate e segue-se; a linha ainda não tem conversa gravada e
   **recupera-se** com o `SQL_MARCAR_ABERTA`, porque uma passagem `degraded`
   **pode** ter conversa no provedor (o `abrirConversa` cria-a antes de a nota
   privada poder falhar) e deixar cair esse *callback* era o defeito desta emenda
   por outra porta; ou o atributo é de **outra** conversa, e essa é a única que se
   recusa — o `handoff_id` chega de fora, e um valor trocado lá fazia-nos pedir a
   retoma do *thread* de outra pessoa;
2. **escreve o `resolver`** (`SQL_MARCAR_RESOLVER`), com `status = 'waiting'` no
   predicado — e o *no-op* que esse predicado compra vale no duplicado
   **sequencial**: duas chegadas concorrentes vêem ambas `waiting` e escrevem as
   duas, com a última a vencer. É escrita separada porque o ADR-010 mantém a identidade do agente
   fora do AGR — ela não entra no corpo da retoma —, e vem **antes** do pedido
   porque depois do CAS a passagem já não está em `waiting`. O predicado é também
   o que faz do *webhook* duplicado um *no-op* nesta coluna: o segundo não
   reescreve o `resolver` de quem respondeu;
3. **pede a retoma** (`retoma.ts`), com as **duas** credenciais — o
   `x-kamba-interno` prova «vem de dentro da rede» e o `x-kamba-hnd-bot` prova
   «vem do *agent bot* deste *tenant*» —, e o corpo são os três campos de forma
   fechada do §3.32: `thread_id`, `handoff_id`, `outcome`.

O `onHumanEvent` corre **depois**, e a ordem é escolhida: ele é uma notificação e
a retoma é a transição de estado. Uma falha da retoma faz este `receber` levantar,
o *endpoint* responder 5xx e o provedor reenviar — e na volta seguinte a passagem
ainda está em `waiting`, pelo que o `resolver` se reescreve e o CAS volta a ter
oportunidade. O que nunca acontece é uma retoma a mais: dois *callbacks* dão
**uma**, pelo CAS.

| Resposta do AGR | O que o HND faz |
|---|---|
| 200 `retomado` | tratado |
| 200 `repetido` | tratado: é o *webhook* duplicado, e o *no-op* a funcionar |
| 404 `recusado` | **levanta** — derivámos o `thread_id` da própria linha, pelo que isto é divergência nossa e não isolamento a morder |
| 400 | **levanta**: nenhuma repetição acrescenta um campo que falta |
| 401 | **levanta**. Engoli-lo fazia **todas** as passagens resolvidas deixarem de retomar o grafo, sem um único registo |
| 503 com `Retry-After` | espera o que ele pede — até um tecto — e tenta **uma** vez mais; nada foi escrito |
| 5xx, rede, corte | **levanta**: a passagem já voltou a `waiting` do lado dele, e a retentativa é a do provedor |

**O 503 repete-se aqui e o 5xx não**, e a razão é a janela: esta chamada corre
*dentro* do pedido do *webhook* do Chatwoot, e o tempo que ela leva é tempo que
ele espera. Por isso há um tecto para o sono (`TECTO_DA_ESPERA_MS`) — cumprir
`Retry-After: 120` à letra era manter uma ligação aberta dois minutos para um
provedor que desiste muito antes — **e um orçamento para o todo**
(`ORCAMENTO_DA_RETOMA_MS`, 20 s *proposta*): com o tecto do sono sozinho, o pior
caso eram 10 s de tentativa, 5 s de sono e 10 s de tentativa, e o AGR pede 5 s
**sempre**, pelo que o sono não era o caso patológico. O orçamento decide se há
segunda tentativa e encurta-lhe o tecto ao que resta.

**E o que levanta daqui é repetido pelo provedor.** A tabela é o que **este
cliente** faz com a resposta: no 401, no 404 e no 400 ele não repete a chamada ao
AGR. Mas levantar faz o `receber` levantar, o *endpoint* do *callback* responder
5xx e o Chatwoot reenviar — pelo que os três se repetem, com a escada dele. É
escolha: engolir um 401 permanente devolve 200, o provedor pára de reenviar, e a
conversa fica sem retoma **sem rasto accionável**, que é o defeito que esta
emenda existe para matar. O custo é uma tempestade de reentregas enquanto o
segredo estiver errado dos dois lados, visível em
`agr_resume_nao_autorizado_total`. **Quem decidir de outra maneira é quem
escrever o *endpoint*** — ele não existe neste repositório —, e é a razão de o
`Veredicto` ainda não prever excepções.

O provedor tem o seu próprio vocabulário (`open|resolved|pending|snoozed`), e só
o `resolved` dele é uma conclusão nossa. **Um `snoozed` não fecha nada:** tratar
uma soneca do agente como fecho era deixar o cliente sem resposta e marcar a
passagem como atendida.

---

## 6. A degradação: o provedor em baixo não falha, degrada

Com o `abrirConversa` a levantar `ProvedorIndisponivelError`:

1. a passagem fica **`degraded`** — aberta do nosso lado, não do dele;
2. a abertura vai para a fila, com recuo;
3. a **linha fica**, e é isso que faz o painel ver o atraso em vez de a passagem
   desaparecer;
4. e `degraded` **conta no SLA**: uma passagem que nem chegou ao provedor está
   tão longe de ser atendida como uma à espera, e esconder-lhe o atraso era
   mostrar um painel verde no pior caso.

A recuperação é do `SQL_MARCAR_ABERTA`, que aceita sair de `degraded`: quando a
fila drena e a conversa nasce lá, ela deixa de estar degradada. Sem `degraded`
nessa lista, uma passagem degradada ficava assim para sempre.

**Um 5xx degrada e um 4xx não.** Rede, *timeout* e 5xx são a mesma coisa para
quem chama — o provedor não respondeu. Um 4xx é um pedido **nosso** errado, e
uma fila que o repetisse nunca drenava: o defeito ficava escondido atrás dela.

---

## 7. Os *callbacks*: autenticação por `secret` de bot

O critério 5 pede «só são aceites com o `secret` do bot; ausente ou errado
devolve 401 e incrementa uma métrica». Quatro motivos, lista fechada porque é
etiqueta de métrica: `sem_secret`, `secret_errado`, `tipo_desconhecido`,
`conta_desconhecida`.

Três decisões que o código escreve e que valem mais do que a lista:

- **Um segredo esperado vazio recusa tudo.** Se o cofre não devolveu nada,
  nenhum *callback* passa — falha fechada, a mesma regra do `PreSendGuard` do
  KAM-015. Sem esta linha, uma configuração em falta tornava-se porta aberta.
- **A comparação é de tempo constante.** `===` sobre cadeias sai no primeiro
  carácter diferente, e com pedidos repetidos o tempo de resposta diz quantos
  caracteres do segredo estão certos. O comprimento é o único facto que vaza, e
  trata-se antes de comparar.
- **A ordem dos testes é a ordem do custo.** O segredo decide-se sem tocar na
  base; a conta precisa de uma leitura, e vem depois. Um pedido sem segredo
  nunca faz uma consulta — é o que impede o uso do *endpoint* como gerador de
  carga.

### Porque é que isto é no HND e não no GWY

O `docs/tecnica/08` §3.6 diz «verificados **pelo GWY**» e o `docs/tecnica/02`
§11, regra (3), diz «autenticação da origem pelo `secret` do *agent bot*
(**HND**)». São dois documentos do mesmo nível, a ordem de fontes não desempata,
e **o ADR-001 não resolve** — ele fixa o GWY como único endpoint dos *webhooks*
**da Meta**, e o *callback* do provedor está fora do seu âmbito.

O que decidiu foi uma razão que o §3.6 não considerou: **o `secret` é por bot,
logo por *tenant***, e o GWY é o único ponto que não tem contexto de *tenant*
antes de resolver o canal. Pôr a verificação lá obrigava-o a adivinhar de quem é
o segredo antes de saber de quem é a conversa. A divergência está em
[`dividas-documentais.md`](dividas-documentais.md) (57).

### O eco do nosso próprio espelho não é uma resposta humana

O `message_created` chega para **todas** as mensagens da conversa, incluindo as
que nós espelhámos. Tratá-las como resposta do agente era reenviar ao cliente o
que ele acabou de nos mandar — um ciclo. O campo que decide é o `message_type`:
só `outgoing` é do agente.

---

## 8. Privacidade: o `resolver` é o primeiro dado pessoal de quem atende

Todas as outras colunas pessoais do esquema são de **clientes finais**. O
`handoffs.resolver` é de **quem atende** — um trabalhador da PME —, e o que se
guarda é o mínimo que responde «quem retomou»: o identificador opaco do agente
no provedor. Nunca nome, nunca e-mail, nunca telefone, e não é um `contact_id`
da KAMBÁ: um agente não é um contacto, não passa pelo módulo de identidade e não
tem BSUID.

O provedor manda o `name` e o `email` no **mesmo objecto** do `id`. O código lê
só o `id`, e não lê os outros — não os ler é mais forte do que lê-los e
descartá-los, e há um teste que procura o nome e o e-mail em tudo o que foi
escrito.

Nas métricas: **nenhuma leva `tenant_id`**, pela razão do `OBS-I` que o §3.14 já
escreveu. O por-*tenant* sai do `SQL_FORA_DO_SLA`, por consulta.

---

## 9. O que não é executável, e porquê

O **`setBotMuted`** está na interface e **levanta** `SemPrivilegioError`.

Silenciar o bot é escrever `conversations.mode`, e `kamba_app` não tem
`UPDATE (mode)` — a revisão `0009` recusou-o por escrito («um privilégio
concedido para quando for preciso é um privilégio que ninguém volta a tirar») e
as transições de modo são do **KAM-018**, que o próprio critério 8 nomeia como
implementador do guarda. A revisão `0011` **não** concede o privilégio.

A porta fica, com o tipo certo, para que o KAM-018 a ligue sem alterar a
interface. Omiti-la era esconder hoje o que vai ter de aparecer — e a caixa do
critério fica **vazia**, com isto escrito.

> **Actualização (KAM-018).** O privilégio existe: a revisão `0016` concede
> `UPDATE (mode, last_human_activity_at)` a `kamba_app`, que é o que a `0009`
> reservou para este ticket. O `setBotMuted` **continua** a levantar, e a razão
> mudou: já não é «não há privilégio», é que ligá-lo é alterar o provedor deste
> ticket, e o KAM-018 não o faz para não alargar escopo em silêncio. A caixa
> fica vazia, agora por esta razão. Quem a quiser marcar liga a porta ao
> `MaquinaDeModos.disparar` com os gatilhos `handoff_pedido` e
> `handoff_resolvido` — o desenho está em
> [`modos-conversa.md`](modos-conversa.md).

Na mesma classe, e também com a caixa vazia: duas chamadas **concorrentes** a
`ensureAccount` podem deixar uma conta **órfã** no provedor. A linha precisa dos
identificadores que só a criação devolve, pelo que não se pode escrever
primeiro, e a assinatura não permite pedir um *lock*. Conta-se e registra-se
(`conta_de_handoff_orfa`) em vez de se esconder; o critério fala de «chamado
2×», que é o caso sequencial, e esse não duplica nada.

---

## 10. Como correr

```bash
# Os testes unitários e de porta (gate 4): estados, callbacks, Chatwoot, provedor, retoma
pnpm --filter @kamba/core-ts exec node --test tests/hnd.estados.test.ts tests/hnd.callbacks.test.ts tests/hnd.chatwoot.test.ts tests/hnd.provedor.test.ts tests/hnd.resposta.test.ts tests/hnd.retoma.test.ts

# A paridade com o outro lado da fronteira (a lista de estados, o cabeçalho, o corpo)
python -m unittest test_handoff.TestFronteiraComOHnd  # PYTHONPATH com services/agr/{src,tests}

# A suite contra PostgreSQL (gate 8)
python db/gate_bd.py --suite tests_handoff

# O spike do L7 contra um Chatwoot 4.18 real, com dados sintéticos
make chatwoot-spike
```

A divisão entre as duas primeiras é a do KAM-015: no *gate* 4 ficam as funções
puras e as portas — a tradução dos estados, a autenticação, a leitura do corpo,
a ordem dos passos, o cliente sobre `fetch`. Na *suite* de base de dados fica o
que **não se simula**: a idempotência contra a chave primária real, a
`UNIQUE` da conta, o `close` duplicado sob concorrência verdadeira e a RLS.

O **spike** é a terceira coisa, e não é um *gate*: é a medição que o critério 8
pede, e o que ela responde está em
[`evidencia/KAM-019-bot-open.md`](evidencia/KAM-019-bot-open.md).

---

## 11. O que não está aqui, e tem dono

| O que | Ticket |
|---|---|
| As transições de `conversations.mode`, o *lock* da conversa e o corpo do `PreSendGuard` | KAM-018 |
| O *compare-and-set* da retoma (`waiting → resumed`) e os nós `handoff_prepare`/`handoff_wait` | KAM-034 |
| O provisionamento orquestrado por *tenant* (a saga) | KAM-091 |
| O aviso ao dono por um segundo número | NÃO VERIFICADO; fora do bloco |
| O **X-10** cross-account como *gate* | não existe em sítio nenhum do repositório; ver a secção de verificação do ticket |
| O alojamento de uma instância com dados reais | **D1** (residência, ADR-008) |

---

## 12. Controlo de versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-10-20 | Criado pelo KAM-019. |
| 1.1 | 2026-10-21 | **O spike correu, e a §3 é o que ele mediu.** O veredicto é `O TOKEN DO BOT CHEGA` — o `pending → open` com o *token* do *agent bot* responde 200 e o plano B não é preciso para o estado. O que mudou o desenho foram as outras cinco medições: o *token* da Platform API dá 401 nos *endpoints* da conta, o *inbox* precisa de um utilizador ligado por `account_users`, o `set_agent_bot` é obrigatório, a conversa precisa de um contacto que exista, e o *token* do bot não cria contactos — pelo que o do utilizador é preciso em execução e a `handoff_accounts` passa a ter duas `SecretRef` e o `provider_user_id` (emenda 1.23). O cliente separou-se em dois objectos, pelo `tecnica/08` §3.6. E a chave do contacto passou a ser **opaca**: a primeira versão mandava o nosso `contact_id` para fora, contra o ADR-010. |
| 1.2 | 2026-10-22 | **KAM-018: a razão pela qual o `setBotMuted` não é executável mudou, e a §9 di-lo.** O privilégio existe — a revisão `0016` concede `UPDATE (mode, last_human_activity_at)` a `kamba_app` —, pelo que a frase «`kamba_app` não tem `UPDATE (mode)`» deixou de ser verdade. O `setBotMuted` continua a levantar porque ligá-lo é alterar este provedor, e o KAM-018 não o faz para não alargar escopo em silêncio. A caixa do critério fica vazia, agora por esta razão, e a §9 diz como se liga. |
| 1.3 | 2026-10-27 | **A fronteira da saída de `waiting` ficou decidida, e é a emenda 1.42 (§3.32).** O `ESTADOS_QUE_FECHAM` passa a `["degraded"]` e este módulo deixa de escrever o `status` no desfecho `resolved`: passa a chamar `POST /internal/resume` (`retoma.ts`, novo), porque era o `close` deste lado a correr primeiro que fazia o *compare-and-set* do AGR não casar — e com ele o `Command(resume=…)` nunca corria e o `interrupt()` ficava pendente para sempre (ANALISE-35, achado 1: o caminho feliz, todas as vezes). O `resolver` ganha instrução própria (`SQL_MARCAR_RESOLVER`), porque o ADR-010 mantém a identidade do agente fora do AGR, e o `thread_id` do corpo vem da linha da passagem com o `external_id` do *callback* no predicado (`SQL_THREAD_DA_PASSAGEM`). Novas §5.1, §5.2 e a tabela de respostas. |
