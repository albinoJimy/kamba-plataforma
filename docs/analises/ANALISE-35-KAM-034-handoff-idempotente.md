# ANÁLISE 35 — revisão adversarial do KAM-034 (*handoff* idempotente e retoma por *compare-and-set*)

| Campo | Valor |
|---|---|
| Ticket | KAM-034 — Handoff idempotente em dois nós, `/internal/resume` com *compare-and-set*, prazo de 24 h |
| Diff revisto | `16e7f48..e2fb8af` (seis commits: a emenda 1.41, o `handoff/`, o *lint*, a bateria, o `agr.md` e o instrumento do *drain*). O trabalho **foi commitado durante a revisão** — comecei a ler a árvore de trabalho e acabei contra `e2fb8af`; todas as sondas foram **re-executadas** contra o estado final e nenhuma mudou de resposta |
| Revisor | subagente independente, com encargo apertado (ficheiros e secções nomeados, oito áreas de procura por ordem de retorno, proibição de corrigir código) |
| O que o revisor **não** recebeu | as justificações do autor. O encargo mandava tratar cada comentário e cada *docstring* como **afirmação** a confrontar com uma medição |
| Instrumentos | leitura do canon linha a linha (`02` §11/§14, `01` §11.1/§11.4/§11.5/§10.2, dicionário §3.15/§3.32, revisão `0011`) e do **outro escritor** (`packages/core-ts/src/hnd/{provedor,consultas,estados}.ts`); **cinco sondas executadas**, duas delas contra um PostgreSQL 18 a sério (contentor próprio, a mesma imagem do *gate* 8); **duas mutações** aplicadas à mão sobre código real, com a bateria e os dez *gates* a correr por cada uma |
| Estado da bateria | verde antes e depois: **801** ensaios no `discover` do AGR; **198** na *suite* de PostgreSQL (`gate_bd.py --suite tests_agr`, exit 0); os dez *gates* sem Docker a zero achados; `mutacoes.py --aplicaveis` → «846 mutação(ões) conferida(s), 0 não aplicável(is)» |
| Veredicto | **REPROVADO** — 3 *must fix*, 6 *should fix*, 5 *nice to have* |

---

## A classe de defeito que esta revisão encontrou

Há uma, e é nova nesta série:

> **a propriedade está medida, e o duplo que a mede é mais forte do que a peça
> que ele substitui.**

Os três *must fix* são todos desta forma, e o caminho é sempre o mesmo. O
mecanismo existe e está certo visto de perto. O ensaio que o cobre monta um duplo
— uma tranca, uma base, uma política — que satisfaz a propriedade **por
construção**. A peça real não a satisfaz. A bateria fica verde a afirmar uma
barreira que não existe.

* o `TrancaFalsa` tem um `asyncio.Lock` **por chave** e afirma
  `sobrepostas == 0`; a `TrancaDeConversas` a sério, num processo, deixa **duas**
  corrotinas dentro da secção crítica da mesma conversa (achado 2, medido contra
  PostgreSQL);
* a `BaseFalsa` compara SQL por identidade e modela a transição `waiting →
  resumed` como se o AGR fosse o seu único escritor; o `hnd/provedor.ts`
  escreve-a primeiro, no mesmo *callback*, antes de pedir a retoma (achado 1,
  lido no código do outro lado);
* a `politica_ast` reprova as três formas em que o canário as escreve e cala-se
  sobre **seis** outras que produzem exactamente o mesmo defeito (achado 3,
  medido).

E há uma segunda, de dose menor e aplicada a todo o relatório:

> **o bloco marca sete das oito caixas e a prosa que as marca é mais longa do que
> a prova.** A caixa 7 está marcada com a mensagem de alternativas inteira sem um
> único ensaio (achado 8 — mutação sobrevivente); a caixa 8 está marcada a dizer
> que o `resolver` «é do HND, pelo seu próprio `close`», e o `ESTADOS_QUE_FECHAM`
> do HND não o deixa escrever depois de o CAS correr (achado 6).

O que **não** se encontrou está na secção «hipóteses que não se demonstraram», e
são cinco barreiras que aguentam — incluindo o isolamento entre *tenants* e entre
contactos, que é o achado de que o autor mais se orgulha e que está certo.

---

## Os três *must fix*

### 1. A `platform.handoffs` tem dois escritores para `waiting → resumed`, o do HND corre **primeiro**, e por isso o `Command(resume=…)` nunca corre

**(a) O que está errado.** O `consultas.py` deste ticket escreve a fronteira
entre os dois escritores, e a §3.32 repete-a:

> * **criar a passagem, marcá-la aberta, degradá-la e fechá-la pelo provedor** é
>   do HND (KAM-019) […];
> * **sair de `waiting` por `/internal/resume`** é do AGR (KAM-034) […]

As duas linhas **cobrem a mesma transição**. «Fechá-la pelo provedor» é o
`SQL_FECHAR` do `hnd/consultas.ts`, que é um `UPDATE platform.handoffs SET status
= $2` com `AND status = ANY($3)` — e o `$3` é o `ESTADOS_QUE_FECHAM` do
`hnd/estados.ts`, que é `["waiting", "degraded"]`. Isto é, o HND **sai de
`waiting`**. A fronteira que a emenda diz escrever «para que ninguém a
redescubra» não é uma partição.

E não é uma questão de qual dos dois é chamado: a ordem está fixada em código, no
`receber` do `hnd/provedor.ts`, e é a pior das duas:

```ts
if (acontecimento.acontecimento === "estado_mudou" && acontecimento.estado !== null) {
  const outcome = outcomeDoProvedor(acontecimento.estado);
  if (outcome !== null) {
    await this.#fechar(acontecimento.handoffId, outcome, acontecimento.resolver);
  }
}
if (this.#handler !== null) await this.#handler(acontecimento);
```

O `#fechar` corre **antes** do `onHumanEvent`, e o `onHumanEvent` é o único sítio
de onde `/internal/resume` pode ser chamado.

**(b) O caminho concreto.** Um cliente pede um humano. Um colega responde no
Chatwoot e marca a conversa como resolvida.

1. `conversation_status_changed` com `resolved` chega ao `receber` do HND.
2. `#fechar` corre: `platform.handoffs` fica `status = 'resumed'`,
   `resumed_at = now()`, `resolver = <agente>`.
3. o `onHumanEvent` dispara e alguém faz `POST /internal/resume {thread_id,
   handoff_id, outcome: "resolved"}`.
4. o `SQL_RETOMAR_HANDOFF` tem `AND h.status = 'waiting'` → **zero linhas**.
5. o `_classificar` lê `status = 'resumed'`, o `pode_retomar` dá `False`, e a
   rota responde **200 `repetido`** — o *no-op* do critério 3, aplicado ao
   pedido legítimo.
6. o `Command(resume=…)` **nunca é enviado**. O `interrupt()` do `handoff_wait`
   fica pendente no *checkpoint* para sempre.

O resto do sistema deixa de o conseguir ver, e cada camada por uma razão
diferente:

* a varredura dos prazos não o encontra: o `SQL_HANDOFFS_EXPIRADOS` filtra
  `h.status = 'waiting'`. O cliente não recebe nem a resposta nem a mensagem de
  alternativas;
* a invariante da não-reentrada abre-se: o `handoff_a_espera` do
  `SQL_PALAVRA_DA_CONVERSA` também só conta as `waiting`, pelo que a mensagem
  seguinte do cliente **entra no grafo** — sobre um *thread* com um `interrupt`
  pendente, que o `handoff_wait` volta a levantar. O turno nunca produz
  resposta, o *job* volta à fila e repete;
* o `ReversaoFalhadaError` não aparece: este caminho não passa pela compensação.
  Não há registo, não há métrica de erro, e o `agr_resume_total{repetido}` sobe —
  que é o contador que um painel lê como «tudo bem, era um duplicado».

O custo: **toda** a passagem resolvida por um humano deixa a conversa morta. Não
uma intercalação rara — o caminho feliz, todas as vezes.

**(c) A prova.** É leitura e não sonda, porque o fio HND → AGR ainda não está
ligado (o `onHumanEvent` não tem registo em produção: o único `hnd.onHumanEvent(…)`
do repositório está em `packages/core-ts/tests/hnd.provedor.test.ts:672`). O que
se mede é que a bateria **afirma** o comportamento quebrado como correcto:

`db/tests_agr/test_handoff_retoma.py::TestOCompareAndSet::test_nao_se_retoma_de_um_estado_que_nao_e_waiting`
percorre `("resumed", "timeout", "cancelled", "degraded")` e exige
`assertFalse(self.cas(...))` em todos — incluindo o `resumed` que o `#fechar`
acabou de escrever. E a mutação `handoff: o CAS deixa de exigir o estado de
partida` existe precisamente para matar quem tente abrir esse estado.

Uma verificação a mais: do lado Python, `SQL_FECHAR` é mencionado **uma** vez
(`consultas.py:355`, e só a propósito do `resumed_at`) e `ESTADOS_QUE_FECHAM`
**nenhuma**. O segundo escritor foi lido pela coluna de que divergia e não pelo
`status` que escreve.

```
$ grep -rn "ESTADOS_QUE_FECHAM" --include=*.py .
(nada)
```

**(d) O que isto obriga a decidir.** Não é um `if` que falta; é uma fronteira. As
duas saídas são:

* **o HND deixa de escrever o `status` no `resolved`** e passa a chamar
  `/internal/resume`, deixando o AGR vencer o CAS — e então o `resolver` precisa
  de um caminho (ver achado 6);
* **ou o AGR aceita retomar de `resumed`** quando o pedido traz o mesmo
  `handoff_id`, e nesse caso o «segundo é *no-op*» do §11.5 deixa de se poder
  decidir pelo `status` e precisa de outra marca (um `resumed_at` já escrito, uma
  coluna de controlo, o estado do *checkpoint*).

A primeira é a que o §11.4 desenha (`CW->>H: webhook …resolved` e depois
`H->>A: retoma com Command resume e resultado`) e a que a regra (3) do `02` §11
escolhe. Seja qual for, **tem de ficar escrita nos dois lados**, porque hoje cada
um dos dois ficheiros está certo sozinho.

---

### 2. A `TrancaDeConversas` não exclui duas corrotinas do mesmo processo — e a compensação do `retoma.py` apaga uma retoma legítima

**(a) O que está errado.** O desenho inteiro deste ticket assenta numa frase, e
ela aparece em cinco sítios (`retoma.py` módulo, `Retomador`, `api_interna.py`,
`SQL_REVERTER_RETOMA`, e a caixa 4 do bloco):

> A compensação é segura porque **tudo isto corre sob a tranca da conversa** […]
> Entre o CAS e a compensação ninguém mais toca na linha.

A tranca é o `SQL_TRANCAR_THREAD`: `pg_try_advisory_lock(hashtextextended(%s))`
sobre **uma** ligação dedicada por processo (`trancas.py`, um só `self._ligacao`).
Os *advisory locks* de sessão do PostgreSQL são **contados**: a segunda tomada da
mesma chave na mesma sessão devolve `true`. Logo, dentro de um processo, a tranca
não exclui **nada**.

Para o turno isso estava coberto por outra peça: o dreno do `turno.py`, que
serializa por `(thread_id, conversation_id)`. A rota de retoma e a varredura dos
prazos **não passam pelo dreno** — chamam `trancas.tomar(thread_id)`
directamente. Este ticket acrescentou os dois únicos chamadores para quem a
tranca é a única barreira, e é para esses que ela não funciona.

(Nota lateral: as duas *docstrings* da casa contradizem-se sobre isto. O
`trancas.py` diz «dentro do processo só uma corrotina por `thread_id` chega aqui
— quem serializa é o dreno»; o `turno.py` diz que o dreno é por conversa e que «a
tranca da base serializa entre processos **e entre as conversas do mesmo
contacto**». As duas não podem ser verdade, e a segunda é a que o KAM-034 usa.)

**(b) A prova.** Sonda contra PostgreSQL 18 (contentor próprio, imagem do *gate*
8), com a `TrancaDeConversas` **real** e nada falso no caminho:

```
[1] mesma sessao, mesma chave: 1.a tomada=True  2.a tomada=True
[1] unlock 1=True  unlock 2=True  (nenhum devolve false -> TrancaNaoLargadaError nunca levanta)
[2] corrotinas dentro da seccao critica ao mesmo tempo (max) = 2
[2] ordem = ['entra:A', 'entra:B', 'sai:A', 'sai:B']
[3] controlo positivo, duas ligacoes: max dentro = 1
```

A linha `[3]` é o controlo positivo que fecha a hipótese alternativa: entre
**processos** a tranca exclui, e o que falha é só dentro de um. E a linha `[1]`
diz porque é que isto nunca deu sinal: o `pg_advisory_unlock` devolve `true` nas
duas, pelo que o `TrancaNaoLargadaError` — a excepção que o `trancas.py` escreveu
para que «a exclusão mútua que deixou de existir apareça» — não levanta.

**(c) O caminho concreto, e o que custa.** Uma passagem em `waiting` há 25 h. No
mesmo processo, ao mesmo tempo:

* a varredura dos prazos retoma com `timeout`, vence o CAS (`status = 'timeout'`)
  e entra no `Command(resume=…)`, que leva um quarto de segundo e **falha** (o
  *checkpointer* a reiniciar);
* 50 ms depois chega o *webhook* do colega que acabou de resolver a conversa, com
  `outcome = "resolved"`.

Sonda com a tranca real e com a `BaseFalsa` **da própria bateria do ticket** (para
que o SQL não seja modelado por mim):

```
== com a tranca REAL (TrancaDeConversas, um processo, PostgreSQL) ==
  varredura -> levantou (e compensou)
  webhook   -> repetido
  status final da passagem = 'waiting'
  grafo retomado pelo webhook = 0 vez(es)

== com a TrancaFalsa da bateria (exclusao perfeita) ==
  varredura -> levantou (e compensou)
  webhook   -> retomado
  status final da passagem = 'resumed'
  grafo retomado pelo webhook = 1 vez(es)
```

Com exclusão a sério o sistema recupera: o *webhook* espera, a compensação
devolve a linha a `waiting`, o CAS do *webhook* vence e o grafo retoma. Sem ela,
o `resolved` do colega recebe **200 `repetido`** — o Chatwoot pára de reenviar —,
o grafo não retoma, e a passagem volta a `waiting` para o prazo a apanhar outra
vez. O cliente, cuja pergunta um humano **já respondeu**, recebe «Ainda não houve
resposta de um colega. Pode ligar para a loja…».

**(d) Porque é que a bateria não vê nada.** O `TrancaFalsa` do `apoio.py` tem um
`asyncio.Lock` por chave — exclusão perfeita — e o
`test_dois_pedidos_concorrentes_dao_uma_retoma` afirma `tranca.sobrepostas == 0`
sobre ele. A *docstring* do duplo diz, com razão, «isto não substitui a *suite*
do *gate* 8: que o `pg_try_advisory_lock` exclui entre **processos** só a base o
pode dizer, e é lá que está medido». Está — `test_duas_sessoes_nao_tem_a_mesma_tranca`.
Não há, em nenhuma das duas *suites*, o ensaio da **mesma** sessão duas vezes, que
é o caso que esta rota produz.

**(e) E a nota que o commit `e2fb8af` acrescentou piora o registo.** Ela corrige
a afirmação anterior (que o `unlock` de dentro largava a tranca cedo — falso, e
bem corrigido) e conclui:

> o bloco de fora continua a deter a tranca. O custo de aninhar era uma ida à
> base por retoma […]; **não era um defeito de exclusão**.

A última metade é verdadeira para o aninhamento e falsa para o caso que importa:
duas corrotinas **irmãs**. A nota passa a afirmar que não há defeito de exclusão
exactamente onde há um.

---

### 3. A política AST do critério 2 evade-se com uma linha, por seis formas — e três delas são o erro que alguém escreveria sem má-fé

**(a) O que está errado.** O critério 2 promete: «teste AST falha se existir
efeito antes dele, `interrupt()` dentro de `try/except` ou dentro de ciclo
`while`». A `politica_ast.verificar` implementa as três ao nível da **instrução**:

* `EFEITO_ANTES` pergunta se `instrucoes[0]` contém um `interrupt` em qualquer
  ponto da sua subárvore (`_chama_interrupt` faz `ast.walk`);
* `DENTRO_DE_TRY` procura `isinstance(linha, ast.Try)`;
* `DENTRO_DE_CICLO` procura `ast.While | ast.For | ast.AsyncFor`.

Nenhuma das três olha para **onde dentro da instrução** o efeito corre, nem
reconhece as outras construções que engolem ou repetem.

**(b) A prova.** Sonda com seis `handoff_wait` escritos à mão:

```
A: efeito na posicao de argumento do interrupt        -> EVADE (politica calada)
B: efeito num tuplo avaliado antes do interrupt       -> EVADE (politica calada)
C: o interrupt dentro de `with contextlib.suppress`   -> EVADE (politica calada)
D: o interrupt num ciclo escrito como compreensao     -> EVADE (politica calada)
E: o interrupt dentro de `try/except*` (TryStar)      -> EVADE (politica calada)
F: o interrupt dentro de um `async with` que engole   -> EVADE (politica calada)

Controlo positivo (o caso A com o efeito a correr de verdade):
    ordem de execucao real = ['efeito', 'interrupt']
```

O caso A é uma linha:

```python
desfecho = interrupt(deps.saida.enfileirar(estado, "ola", chave="k"))
```

O argumento avalia-se **antes** da chamada — o controlo positivo executa-o e
imprime `['efeito', 'interrupt']` — e a política dá lista vazia, porque a primeira
instrução «contém um `interrupt`». É o defeito 6 do §7.1 inteiro, e é a forma
mais natural de o escrever por acidente: quem queira passar contexto ao
`interrupt` escreve-o assim.

O caso C é duas:

```python
with contextlib.suppress(BaseException):
    desfecho = interrupt({})
```

O LangGraph interrompe **levantando**, pelo que o `suppress` engole a interrupção
exactamente como o `except` que a regra `DENTRO_DE_TRY` existe para apanhar — e
evade as duas regras ao mesmo tempo, porque o `With` é a primeira instrução e
contém um `interrupt`.

O caso D é uma: `[interrupt({"i": i}) for i in range(3)][-1]`. Uma compreensão
não é `ast.For`; os geradores dela são `ast.comprehension`. Três `interrupt()` num
ciclo, que é o problema de índice que a regra nomeia.

O caso E é a mesma forma do canário com `except*`: `ast.TryStar` não é `ast.Try`.

**(c) O que custa.** Nada hoje — o `handoff_wait` real está conforme, e isso está
medido. O custo é a seguir: a política é a única barreira do critério 2, não é um
*gate* (por decisão escrita), e um PR que escreva o caso A passa a bateria inteira
com a propriedade quebrada. O encargo desta revisão diz a frase melhor do que eu:
«uma política que se pode evadir com três linhas é uma política decorativa». Esta
evade-se com uma.

**(d) O que falta.** Três verificações, e nenhuma é grande:

1. a regra do efeito tem de olhar para a **forma** da primeira instrução, e não
   só para a presença do nome: o `interrupt` tem de ser o `value` de um `Assign`
   (ou um `Expr`) e os seus `args`/`keywords` não podem conter `ast.Call`
   nenhuma;
2. o `DENTRO_DE_TRY` tem de incluir o `ast.TryStar` e o `ast.With`/`ast.AsyncWith`
   — ou, se um `with` legítimo vier a ser preciso, recusar só os que não estejam
   numa lista declarada;
3. o `DENTRO_DE_CICLO` tem de incluir `ast.ListComp | ast.SetComp | ast.DictComp
   | ast.GeneratorExp`.

E os canários destas seis formas, que é o que torna a correcção mensurável.

---

## Os seis *should fix*

| # | Achado | Prova | Correcção proposta |
|---|---|---|---|
| 4 | **O `ESCRITA_NO_PLATFORM` ficou mais estreito do que era, e isso vale para todas as tabelas e todos os ficheiros.** O diff trocou `platform\.` por `platform\.(\w+)` para poder ler o nome da tabela. Um identificador entre aspas — SQL válido e que o repositório usa noutros sítios — deixou de casar o padrão, pelo que a escrita fica **invisível ao *lint*** e não só dispensada | Sonda sobre o próprio `ESCRITA_NO_PLATFORM` contra o padrão anterior: `UPDATE platform."orders" SET total = 0` → antiga **sim**, nova **NÃO**; `DELETE FROM platform."contacts"` → antiga **sim**, nova **NÃO** | o grupo tem de aceitar as duas formas: `platform\.(?:"(\w+)"\|(\w+))`, com o nome lido do grupo que casou. É um *gate* de bloqueio (2 e 11) a cobrir menos do que cobria, e não há canário a medi-lo |
| 5 | **A dispensa é por `(ficheiro, tabela)` e não por instrução, pelo que um `DELETE FROM platform.handoffs` no `consultas.py` passa em silêncio.** Os quatro critérios declarados são prosa: nenhum é verificado. O critério 2 («plano de controlo») e o 3 («`tenant_id` no predicado e dentro de `tenant_guard.tx`») não têm código a impô-los | Mesma sonda: `DELETE FROM platform.handoffs WHERE 1=1` → detectado e **dispensado**; `INSERT INTO platform.handoffs (handoff_id) VALUES (%s)` → detectado e **dispensado**. As duas são escritas que o canon atribui a outros: o `INSERT` é do HND (§3.32, «criar a passagem […] é do HND») e o `DELETE` é da purga em `kamba_batch` (KAM-071) | a chave passa a `(ficheiro, verbo, tabela)` — a entrada é `("…/consultas.py", "UPDATE", "handoffs")` —, e os canários ganham o terceiro eixo (o mesmo par com `DELETE` tem de morder). A `handoffs` é a tabela que sustenta o histórico do SLA, e a *docstring* do `downgrade` da `0011` já escreveu que ele não se reconstrói |
| 6 | **O `resolver` do critério 8 não tem caminho de escrita na ordem que o AGR assume, e a caixa está marcada a dizer que tem.** A caixa 8 e a linha «Corpo da retoma interna» da §3.32 dizem «quem sabe que agente respondeu é o HND, pelo seu próprio `close`». O `SQL_FECHAR` só casa quando `status = ANY(['waiting','degraded'])` | `hnd/estados.ts`: `ESTADOS_QUE_FECHAM = ["waiting", "degraded"]`. Se o CAS do AGR correr primeiro, a linha está em `resumed` e o `#fechar` devolve zero linhas — `handoff_fecho_sem_efeito` no registo e `resolver` a `NULL` para sempre. E `db/tests_agr/test_handoff_retoma.py::test_a_primeira_retoma_vence_e_escreve_o_instante` **afirma** `assertIsNone(resolver)` como propriedade desejada | é a outra metade do achado 1 e resolve-se com ele: se o HND fecha primeiro, o AGR precisa de poder retomar de `resumed`; se o AGR retoma primeiro, o `ESTADOS_QUE_FECHAM` tem de incluir os três estados terminais para o `#fechar` poder escrever o `resolver` — ou o `resolver` entra no corpo de `/internal/resume`, que é a emenda que a §3.32 recusou. Até lá a caixa 8 não devia estar marcada |
| 7 | **O `partes` não valida a forma do `contact_id`, pelo que um `thread_id` malformado atravessa a validação, rebenta na base e põe o *webhook* a repetir.** O `partes` exige exactamente um `:` e duas metades não vazias; o `conversations.contact_id` é `uuid` | Sonda com o **próprio** `SQL_RETOMAR_HANDOFF` contra PostgreSQL, num esquema com os tipos da `0011`: `partes("<tenant-uuid>:nao-sou-um-uuid")` **aceita**, e o CAS levanta `22P02 invalid input syntax for type uuid`. A excepção não é dos tipos que a rota apanha, pelo que sai **500** — e a tabela de respostas do `api_interna.py` diz que 500 «devolve o *job* à fila». Pior: o `_executar` larga e fecha a ligação de `handoff` a cada excepção, pelo que cada repetição custa uma tomada nova | o `partes` valida as duas metades com `uuid.UUID(…)` e levanta `ThreadInvalidoError` — que a rota já traduz em 400, e um 400 descarta em vez de repetir. É a mesma decisão que o `partes` já tomou para o `:` («recusa-se com 400 em vez de ir à base perguntar por uma conversa que não pode existir»), aplicada ao resto da cadeia |
| 8 | **A única mudança substantiva do critério 7 — a `MSG_ALTERNATIVAS` — não tem ensaio nenhum.** O critério pede «a mensagem de alternativas (telefone/e-mail/loja)» e o que este ticket entrega é a frase a nomear os três canais. Nada o mede: `grep -rn MSG_ALTERNATIVAS services/agr/tests db/` → nada, e o único ensaio do caminho (`test_vendedor.py::test_no_timeout_saem_as_alternativas_com_chave_propria`) afirma `assertIn("Ainda nao houve resposta", texto)`, que o texto **anterior** também satisfaz | **Mutação aplicada à mão** (reverter a `MSG_ALTERNATIVAS` para o texto pré-ticket, que não nomeia canal nenhum): `Ran 800 tests … OK`, e os *gates* `lint_refs`, `canon_lint`, `lint_arch`, `log_policy` e `lint_contagens` todos a `exit=0`. **Sobrevive a tudo** | um `assertIn` por canal no ensaio que já existe — «loja», «e-mail», e o terceiro —, e uma mutação `handoff: a mensagem de alternativas deixa de nomear os canais` no `mutacoes.py`. A dívida do **conteúdo** (os valores, dívida 124) está bem nomeada e não é isto: isto é a parte que o ticket **entregou** e não mediu |
| 9 | **O `handoff_seq` sobe no ramo que teve sucesso e não no ramo que também cria a linha.** O `_degradado` devolve um delta sem `handoff_seq`, pelo que a passagem seguinte da mesma conversa reutiliza o `handoff_id`. Do outro lado, o `abrir` do `hnd/provedor.ts` **insere a linha** e só depois a marca `degraded` (`SQL_MARCAR_DEGRADADA`) e enfileira a reabertura: a linha com aquele `handoff_id` passa a existir | Sonda pelo nó real: turno 1 com o provedor em baixo → `status='degraded'`, `'handoff_seq' in delta = False`, estado fica com `handoff_seq=0`; turno 2 com o provedor de pé → **o mesmo `hid`** (`f5632cb91b17…`). O comentário do próprio `handoff_prepare` descreve este defeito pelo outro lado: «se subisse no fim, dois *handoffs* seguidos partilhavam o identificador e o segundo era engolido pela idempotência do primeiro» | o `handoff_seq` sobe quando a passagem **se tenta**, não quando tem sucesso: o `_degradado` recebe o `seq` seguinte como o ramo de sucesso. O critério 1 mede as cinco repetições do mesmo turno (que é a propriedade certa, e o `seq` tem de ficar estável nessas) e o `test_o_handoff_seguinte_da_conversa_tem_outro_identificador` mede o caminho de sucesso; falta o caso misto, que é um `subTest` ao lado |

---

## Os cinco *nice to have*

1. **O tecto da varredura não tem ensaio nem mutação.** **Mutação aplicada:**
   `TECTO_POR_VARREDURA: Final = 500` → `1` → `Ran 801 tests … OK`,
   **sobrevive**. O `_LigacaoDeLote` da bateria ignora os parâmetros do
   `execute`, e a *suite* de PostgreSQL passa `tecto=1` explicitamente, pelo que
   o **valor** da constante nunca é afirmado. Não é defeito hoje (é *proposta*,
   calibra-se em KAM-084), e com o tecto a 1 uma varredura horária drena 24
   passagens por dia — exactamente o cenário do «provedor em baixo um fim de
   semana» que a constante existe para resolver. Uma asserção do número, como a
   que o `test_o_prazo_e_de_24_horas` já faz para as 24 h.
2. **O `'waiting'` do CAS e o `ESTADOS_RETOMAVEIS` do `maquina.py` são duas
   cópias da mesma decisão.** O módulo escreve, sobre os cinco estados, que os lê
   da migração «e não de uma cópia» porque «sem isso, as duas listas divergiam e o
   código escrevia um `status` que a base recusa». O `ESTADOS_RETOMAVEIS`
   (`("waiting",)`) e o `AND h.status = 'waiting'` do `SQL_RETOMAR_HANDOFF` são
   essa mesma situação, uma linha acima: se um crescer, o `_classificar` passa a
   chamar `recusado` a um duplicado, e o comentário dele já prevê o sintoma sem
   prevenir a causa. Há mutação de cada lado, e não há ensaio a confrontá-los.
3. **O `handoff_wait` escreve `status="resumed"` no estado nos três desfechos.**
   `return {"handoff": dict(anterior, status="resumed", outcome=resultado)}`:
   uma passagem que expirou fica, no estado do grafo, com `status='resumed'` e
   `outcome='timeout'`, enquanto a tabela diz `timeout`. Nada a jusante lê o
   `status` do estado (o `handoff_close` lê o `outcome`), pelo que é inofensivo —
   e é a máquina do critério 8 a dizer duas coisas diferentes em dois sítios,
   num ticket cuja decisão central é que os dois vocabulários têm **uma** cópia.
4. **A `BaseFalsa` não modela o `tenant_id` no predicado da reversão.** Os ramos
   do `SQL_RETOMAR_HANDOFF` e do `SQL_HANDOFF_PARA_RETOMA` confrontam
   `self.tenant != tenant`; o do `SQL_REVERTER_RETOMA` não. A instrução real
   tem-no, e a *suite* de PostgreSQL mede-a — pelo que não há furo. É uma
   assimetria num duplo que o próprio ficheiro declara como «o que ela prova é a
   orquestração», e que custa uma linha.
5. **A contagem das mutações no bloco está desactualizada.** A «Prova por
   mutação» afirma «**Vinte mutações** `handoff:` […] **treze** em Python […] e
   **sete** no SQL». Em `e2fb8af` a secção KAM-034 do `mutacoes.py` tem **25**
   (`awk '/---------------- KAM-034/{f=1} f&&/^    \(.handoff: /{n++}'` → 25), e
   o `lint_contagens` passa a zero porque não cobre esta. É a dívida de contagem
   que a casa já conhece, e o número está no bloco de um ticket que vai ser lido
   como registo.

---

## Hipóteses que **não** se demonstraram

O encargo pede que uma hipótese não demonstrada se diga por extenso. São cinco, e
duas delas são as áreas de procura de maior retorno — valem como barreiras
afirmadas.

**1. Isolamento entre *tenants* e entre contactos: não encontrei caminho, e são
três barreiras independentes.** Procurei-o por cinco vias — `handoff_id` de outro
*tenant*, `handoff_id` de outro contacto do mesmo *tenant* (o caso que o
`sha256` irreversível **não** impede sozinho), `thread_id` com prefixo de outro
*tenant* e segredo do primeiro, contexto de RLS de um e predicado do outro, e a
leitura de classificação a confirmar existência. As três barreiras aguentam: a
RLS esconde a linha, o `tenant_id` repetido no predicado torna a instrução
correcta mesmo corrida sem contexto, e o `EXISTS` sobre
`conversations.contact_id` fecha o terceiro caso. Está medido contra a base em
`TestOVinculoAoThread` e `TestOIsolamento`, com controlo positivo em cada. **Isto
é o melhor trabalho deste ticket** — é uma propriedade que nenhum documento pedia
e que o autor derivou de o `handoff_id` ser irreversível. E o 404 em vez de 403
não vaza existência: as três razões de recusa dão a mesma resposta.

**2. A compensação a desfazer o trabalho de outro pedido: refutada, e a razão é
de predicado.** Era a hipótese mais promissora da área 1, e procurei-a por três
vias. (i) Dois pedidos do AGR: o segundo não escreve nada (o CAS não casa), pelo
que não há trabalho dele para desfazer. (ii) A reversão a apanhar a escrita do
HND: o `SQL_REVERTER_RETOMA` só casa `status = <o que este pedido escreveu>`, e o
`SQL_FECHAR` do HND só casa `waiting|degraded` — os dois conjuntos não se cruzam,
pelo que a reversão não pode apagar um `close`. (iii) A reversão a devolver a
`waiting` uma passagem que outro já fechou: impossível pela mesma razão. O
predicado da reversão **não depende** da tranca para ser correcto, ao contrário do
que a sua própria *docstring* diz («é seguro porque corre sob a tranca […]; o
predicado confirma-o de qualquer maneira» — é o inverso: o predicado é que o
garante, e a tranca é que não existe). O que a falta de exclusão custa está no
achado 2, e é uma retoma **perdida**, não uma escrita desfeita.

**3. Dois `Command(resume=…)` para o mesmo `handoff_id`: refutada contra a
base.** Procurei duas réplicas e dois *webhooks* duplicados. O CAS é **uma**
instrução, e o PostgreSQL serializa: `test_duas_sessoes_concorrentes_dao_uma_retoma`
mede duas ligações a disputarem a mesma linha e exactamente uma a vencer. A minha
sonda com a tranca real confirma-o pelo outro lado — mesmo sem exclusão nenhuma,
o segundo recebe `repetido` e o grafo é retomado uma vez. O critério 3 está
cumprido, e é a parte do desenho que menos depende de tudo o resto.

**4. Tomar a tranca de uma conversa sem credencial válida: refutada.** Era a área
4, e o caminho existia antes de eu começar a ler — o commit `485350b`
acrescentou o `partes(corpo["thread_id"])` **antes** do `trancas.tomar`, e o
`verificar_bot` corre antes dos dois. Verifiquei as quatro ordens: o
`x-kamba-interno` decide sem ler o corpo; o `x-kamba-hnd-bot` decide depois do
corpo e **antes** da validação do vocabulário do `outcome` (pelo que a diferença
400/401 não revela os três desfechos); o `partes` decide antes da tranca; e a
omissão do `verificar_bot` **recusa** (`else "secret_errado"`). A única forma de
chegar à tranca com um `thread_id` arbitrário exige as duas credenciais, e nesse
caso o 500 do achado 7 é o que sobra.

**5. O `handoff_seq` a mudar entre duas execuções que deviam dar a mesma chave:
refutada para o caso que o critério 1 mede.** O ramo de sucesso devolve o `seq`
no delta e o LangGraph descarta o delta de um nó que levantou, pelo que cinco
repetições do mesmo turno vêem sempre o mesmo `seq` — medido pelo nó real no
`test_as_cinco_execucoes_pedem_sempre_a_mesma_chave`, que afirma
`len(set(saida.chaves)) == 1` e não depende da de-duplicação do duplo. O que
encontrei é o inverso (o `seq` a **não** subir quando devia) e está no achado 9.

---

## Contagem e o mais sério

| Classe | Quantos |
|---|---|
| *must fix* | **3** |
| *should fix* | **6** |
| *nice to have* | **5** |
| hipóteses declaradas e não demonstradas | 5 |
| mutações aplicadas à mão | 2, **as duas sobreviventes** |
| sondas executadas | 5 (duas contra PostgreSQL 18 a sério) |

**O mais sério é o achado 1**, e não por pouco. Os outros dois *must fix* são
barreiras que não excluem e políticas que não mordem — defeitos de segunda ordem,
que custam quando mais alguma coisa falhar. O achado 1 custa no **caminho
feliz**: cada passagem que um humano resolve deixa a conversa com um `interrupt`
pendente que ninguém volta a tocar, sem registo, sem métrica de erro, com um 200
a dizer ao Chatwoot que está tratado, e com o `agr_resume_total{repetido}` a subir
— que é o contador que um painel lê como normalidade. O cliente que pediu para
falar com uma pessoa, falou com ela, e depois nunca mais recebe nada do bot; e a
mensagem seguinte dele reentra num grafo que a volta a interromper.

E é o achado que o encargo previu pelo nome: «`packages/core-ts/src/hnd/…` — é
aqui que uma incoerência entre os dois lados aparece». A emenda 1.41 chega a
escrever que «a `platform.handoffs` passa a ter dois escritores em duas
linguagens» e a listar a fronteira; o que ela não fez foi abrir o `receber` do
`hnd/provedor.ts` para ver **em que ordem** eles correm. Do lado Python, o
`SQL_FECHAR` é citado uma vez — a propósito da coluna de que divergia — e o
`ESTADOS_QUE_FECHAM` nenhuma.

---

## O que esta revisão ensina a quem vier depois

**1. Um duplo mais forte do que a peça real transforma a bateria num espelho.**
Os três *must fix* são a mesma falha de calibração, e os três duplos estão
**bem** escritos e com as suas limitações declaradas — o `TrancaFalsa` chega a
dizer onde o resto está medido, e está. O que falta não é um duplo mais honesto:
é a pergunta «qual é a propriedade que este duplo garante por construção, e onde
está o ensaio que a mede na peça a sério?». Para a tranca, a resposta era um
`SELECT pg_try_advisory_lock(k)` duas vezes na mesma sessão — uma linha de SQL.

**2. Uma fronteira entre dois donos não é uma fronteira enquanto não disser a
ordem.** A §3.32 escreve as duas metades e as duas cobrem a mesma transição.
Quando duas peças escrevem a mesma linha, o que resolve não é dizer «esta cria e
aquela sai»: é dizer **quem corre primeiro** e o que o segundo faz quando chega e
já não encontra o estado de que precisava. As duas metades deste ticket estão
certas sozinhas, e é por isso que o *gate* inteiro passa.

**3. Uma política AST implementada ao nível da instrução protege contra a forma
em que o canário a escreve.** As três regras do critério 2 são sobre **execução**
— o que corre antes, o que engole, o que repete — e estão implementadas sobre
**posição sintáctica**. A distância entre as duas são seis construções da
linguagem, e três delas são o que alguém escreve sem má-fé. Quando uma regra é
«nada corre antes de X», a verificação não é «X está na primeira linha»: é «nada
no caminho de avaliação de X é uma chamada».

**4. Uma caixa marcada é uma afirmação, e vale o ensaio que a sustenta.** A caixa
7 está marcada com três parágrafos sobre a mensagem de alternativas e sem um
`assertIn`; a caixa 8 está marcada a atribuir o `resolver` a um `close` que, na
ordem que ela assume, não o pode escrever. As duas mutações que apliquei à mão
sobreviveram à bateria **e** aos dez *gates*, e as duas vivem precisamente onde a
prosa é mais longa. A regra que a ANALISE-34 escreveu continua a valer, com uma
palavra mudada: **uma afirmação de comportamento numa caixa marcada é uma dívida
de ensaio.**

---

## Veredicto

**REPROVADO.**

O desenho de cada peça é bom e, em dois sítios, melhor do que o canon pedia — o
vínculo ao `contact_id` no predicado do CAS e a quarta regra `sem_interrupt` são
as duas propriedades que ninguém mandou medir e que é certo medir. O que reprova
não é nenhuma peça: é o que acontece entre elas. A retoma não corre no caminho
feliz porque o outro escritor da tabela já consumiu o estado de que ela precisa
(achado 1); a tranca sobre a qual a compensação assenta não exclui dentro de um
processo (achado 2); e a política que é a única barreira do critério 2 evade-se
com uma linha (achado 3).

Os achados 1 e 6 são o mesmo problema visto pelos dois lados e têm de ser
resolvidos juntos, com a ordem escrita nos dois ficheiros. Enquanto o achado 1
estiver de pé, as caixas **3** e **8** do bloco não devem ficar marcadas, e a 7
não deve ficar marcada enquanto a mensagem não tiver ensaio.

---

## Controlo de versões

| Versão | Data | Autor | Alterações |
|---|---|---|---|
| 1.0 | 2026-10-27 | KAM-034 | Emissão contra `16e7f48..e2fb8af`: 3 *must fix*, 6 *should fix*, 5 *nice to have*, 5 hipóteses declaradas e não demonstradas; cinco sondas (duas contra PostgreSQL 18) e duas mutações à mão, as duas sobreviventes; bateria verde nos dois estados (801 ensaios no AGR, 198 na *suite* de BD, dez *gates* a zero) |
