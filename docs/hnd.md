# O HND — a passagem a humano

| Campo | Valor |
|---|---|
| Ticket | KAM-019 — HND: `HandoffProvider` e Chatwoot (Agent Bot API, espelho por *inbox* de tipo API) |
| Código | `packages/core-ts/src/hnd/` (oito ficheiros), revisão `0011` |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §11 e §14, [`tecnica/02_Agent_Runtime_Verticais.md`](tecnica/02_Agent_Runtime_Verticais.md) §11 e §14 |
| Nomes | [`../specs/02_Dicionario_de_Dados_Canonico.md`](../specs/02_Dicionario_de_Dados_Canonico.md) §3.15 (emenda 1.22) |
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

## 3. A idempotência é da base, e é de dois tipos

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

## 4. Os dois vocabulários de estado, e a ponte

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

O provedor tem o seu próprio vocabulário (`open|resolved|pending|snoozed`), e só
o `resolved` dele é uma conclusão nossa. **Um `snoozed` não fecha nada:** tratar
uma soneca do agente como fecho era deixar o cliente sem resposta e marcar a
passagem como atendida.

---

## 5. A degradação: o provedor em baixo não falha, degrada

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

## 6. Os *callbacks*: autenticação por `secret` de bot

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

## 7. Privacidade: o `resolver` é o primeiro dado pessoal de quem atende

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

## 8. O que não é executável, e porquê

O **`setBotMuted`** está na interface e **levanta** `SemPrivilegioError`.

Silenciar o bot é escrever `conversations.mode`, e `kamba_app` não tem
`UPDATE (mode)` — a revisão `0009` recusou-o por escrito («um privilégio
concedido para quando for preciso é um privilégio que ninguém volta a tirar») e
as transições de modo são do **KAM-018**, que o próprio critério 8 nomeia como
implementador do guarda. A revisão `0011` **não** concede o privilégio.

A porta fica, com o tipo certo, para que o KAM-018 a ligue sem alterar a
interface. Omiti-la era esconder hoje o que vai ter de aparecer — e a caixa do
critério fica **vazia**, com isto escrito.

Na mesma classe, e também com a caixa vazia: duas chamadas **concorrentes** a
`ensureAccount` podem deixar uma conta **órfã** no provedor. A linha precisa dos
identificadores que só a criação devolve, pelo que não se pode escrever
primeiro, e a assinatura não permite pedir um *lock*. Conta-se e registra-se
(`conta_de_handoff_orfa`) em vez de se esconder; o critério fala de «chamado
2×», que é o caso sequencial, e esse não duplica nada.

---

## 9. Como correr

```bash
# Os testes unitários e de porta (gate 4): estados, callbacks, Chatwoot, provedor
pnpm --filter @kamba/core-ts exec node --test tests/hnd.estados.test.ts tests/hnd.callbacks.test.ts tests/hnd.chatwoot.test.ts tests/hnd.provedor.test.ts

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

## 10. O que não está aqui, e tem dono

| O que | Ticket |
|---|---|
| As transições de `conversations.mode`, o *lock* da conversa e o corpo do `PreSendGuard` | KAM-018 |
| O *compare-and-set* da retoma (`waiting → resumed`) e os nós `handoff_prepare`/`handoff_wait` | KAM-034 |
| O provisionamento orquestrado por *tenant* (a saga) | KAM-091 |
| O aviso ao dono por um segundo número | NÃO VERIFICADO; fora do bloco |
| O **X-10** cross-account como *gate* | não existe em sítio nenhum do repositório; ver a secção de verificação do ticket |
| O alojamento de uma instância com dados reais | **D1** (residência, ADR-008) |

---

## 11. Controlo de versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-10-20 | Criado pelo KAM-019. |
