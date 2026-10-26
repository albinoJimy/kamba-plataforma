# ANALISE-31 — KAM-029: idempotência de tools por `cart_id`

| Campo | Valor |
|---|---|
| Ticket | KAM-029 — Idempotência de tools por `cart_id` (EPIC-03, M, P0, Fase 0) |
| Ramo | `feature/KAM-029-idempotencia-de-tools-por-cart-id` |
| Base | `publico/main` em `a713cf8` (KAM-028) |
| Revisor | Agente independente, com o diff e os requisitos e **sem** as justificações do autor |
| Data | 2026-10-26 |
| Veredicto da revisão | **REPROVADO** — 4 *must fix*, 4 *should fix*, 2 *nice to have* |
| Estado depois das correcções | os 4 *must fix* tratados (3 corrigidos com teste, 1 devolvido como tensão entre critérios); 3 dos 4 *should fix* corrigidos, 1 recusado com razão |

## O que o revisor leu, e o que correu

O bloco KAM-029 inteiro (critérios, DoD, a secção de Verificação do autor — que
atacou como afirmação e não como evidência), `tls/idempotency.py`,
`0022_tool_idempotency.py`, os cinco pontos pedidos de `camada.py`,
`tenant_guard/__init__.py`, `db/tests_agr/test_idempotencia.py`, as três classes
novas de `services/agr/tests/test_tls.py`, `docs/tecnica/02` §6.3 e `03` §6.3, o
dicionário §3.28 e a emenda 1.37, e as dívidas 108–111. Correu
`canon_lint --root .. check` (saída 0, dicionário 1.37, 386 entradas).

**Duas coisas resistiram ao ataque, e são as que mais importam:** a derivação da
chave e a migração.

---

## Must fix

### 1. O tecto de espera (3 s) é menor do que o tecto do backend que ele espera (8 s)

**Caso concreto.** `criar_pedido(cart_id=c-1)`, backend do COM a responder em 4 s
— dentro do tecto de 8 s da classe. O cliente toca duas vezes. Em t=0 A reserva
e chama o backend; em t≈0,05 B lê `em_curso` e espera; em t=3,0 B devolve
`UPSTREAM_TIMEOUT`; em t=4,0 A fecha `concluida`. O critério 1 escreve «devolvem
**todas** o mesmo resultado» e aqui uma devolve recusa. E para o grafo
`UPSTREAM_TIMEOUT` é falha de infra-estrutura: o cliente pede carrinho novo, o
`propose_cart` dá `cart_id` novo, logo chave nova — e a segunda barreira do COM
também não o apanha, porque um carrinho novo é `draft_id` novo. **Duas
encomendas.** A bateria não o apanha porque usa um backend de 50 ms, 60× abaixo
do tecto.

**Disposição: devolvido como tensão entre critérios, e o critério 1 passa a
parcial.** O achado é real e está medido. Mas a correcção que o revisor propõe —
servir o esperador depois do tecto, ou subir o tecto — **contradiz o critério
5**, que escreve «aguarda até 3 s … e, se continuar `em_curso`, devolve
`UPSTREAM_TIMEOUT` sem executar», e cita o `03` §6.3 para o valor. Os critérios 1
e 5 só podem valer ao mesmo tempo enquanto o backend responder dentro de 3 s, e
escolher entre eles é decisão de quem os escreveu — não se resolve em silêncio
dentro do ticket. É a mesma classe das três tensões que o KAM-025 registou (linha
93 das dívidas). Fica: o critério 1 **parcial** com a condição escrita, o tecto
como parâmetro do construtor (já era), e a dívida **112** com o credor.

### 2. Uma linha `em_curso` cujo `fechar` não passou era imortal, com a encomenda já feita

**Caso concreto.** Não é o `SIGKILL` exótico: é o caminho que o `except` do
`_correr` existe para tratar. O backend corre e cria a encomenda; a ligação cai
(a razão pela qual o `except` faz `ligacao.close()`); o `fechar` levanta e é
engolido ali de propósito. A linha fica `em_curso`; `reservar` só retomava
`falhada`; a varredura recusa apagar `em_curso` por idade. Toda a repetição
daquele `cart_id` respondia `UPSTREAM_TIMEOUT`, o cliente saía por carrinho novo
⇒ chave nova ⇒ **segunda encomenda**. E a caixa do DoD «Idempotência … sem
duplicar efeitos» estava marcada.

**Disposição: corrigido.** `MINUTOS_PARA_RETOMAR = 2` e `SQL_RETOMAR_ABANDONADA`:
uma linha `em_curso` mais velha do que isso considera-se abandonada e retoma-se,
por `UPDATE` condicional (atómico — de dois leitores, um só passa). É o que o
`03` §6.3 **ponto 4** já desenhava para o COM e que o revisor citou contra mim:
«intenções `em_curso` > 2 min são retomadas ou marcadas `falhada`». Dois minutos
e não 8,5 s porque o tecto diz quanto o dono **pode** demorar, e retomar por cima
de um dono vivo é o que duplica o efeito. Quatro baterias contra a base
(`TestRetomaPorIdade`) mais uma de unidade.

### 3. O critério 5 estava satisfeito pela razão errada: o «há mais de 2 s» não era lido

**Caso concreto do revisor.** Em
`test_em_curso_espera_ate_tres_segundos_e_nao_executa`, apague-se o
`now() - interval '10 minutes'` da semente: **o teste passa igual**. O
`created_at` não entrava em decisão nenhuma, e a *docstring* dizia que os dez
minutos eram «o "há mais de 2 s" do critério». Era decoração, não oráculo — a
mesma forma do varrimento do KAM-026 que dava sempre zero e do X-02 do KAM-028.

**Disposição: corrigido pela mesma alteração do achado 2**, que torna a idade
carga útil. A bateria de unidade e a de base passaram a ter **par**: a única
diferença entre as duas é a idade da linha, e o desfecho é o oposto. A semente do
critério 5 passou de dez minutos para dez **segundos** — mais do que os 2 s que o
critério nomeia, menos do que os 2 min da retoma.

### 4. O `args_hash` era dos argumentos crus, não do modelo validado

**Caso concreto.** Com `ArgumentosDoEnsaio(cart_id: str, nota: str = "")`: o
primeiro toque emite `{"cart_id": "c-1"}`, o segundo (turno novo, geração nova)
emite `{"cart_id": "c-1", "nota": ""}`. Validam para o **mesmo** modelo e dão
hashes diferentes ⇒ `INTENT_REUSED_WITH_DIFFERENT_CONTENT` em vez do *replay*.
Idem com coerção (`2` contra `"2"`). Isto desmente a metade entregue do critério
8: ela só valia se o modelo de linguagem reproduzisse o dicionário byte a byte.

**E o revisor apanhou a agravante:** o autor **sabia** da assimetria — está
escrita num comentário da semente do critério 5 — e usou-a para fazer a bateria
bater, em vez de a tratar como defeito.

**Disposição: corrigido.** O hash passa a ser de `inv.args.model_dump()`. As
omissões estão preenchidas e os tipos coagidos, pelo que se compara a **intenção**
e não a forma como ela foi escrita; o critério 3 não se perde. Consequência
registada: a `tool_audit.args_hash` continua a ser do `args_crus` e **as duas
colunas deixam de ser o mesmo valor** — a auditoria registra o que chegou, esta
compara o que vale. A afirmação contrária saiu do dicionário §3.28.

---

## Should fix

### 5. A alteração ao *gate* 3b era larga demais, e o âmbito dela é discutível

O revisor demonstrou **três** buracos na primeira versão (uma regra inferida: «não
se cobra `falta` a quem uma revisão de nome posterior redeclare»):

- **(a) nenhuma prova de `DROP CONSTRAINT`.** Caso concreto, e é deste ticket: se
  a `0022` tivesse escrito `ADD CONSTRAINT tool_audit_error_code_v2` **sem**
  largar o da `0021`, as duas restrições ficavam vivas, a base continuava a
  recusar `INTENT_REUSED_WITH_DIFFERENT_CONTENT` com `23514` — o defeito que a
  `0022` existe para evitar — e o *gate* dizia **conforme**. Antes da alteração
  ficava vermelho.
- **(b) o leitor de revisões lê o `downgrade`.** Uma revisão cujo `upgrade`
  largue o domínio e cujo `downgrade` o redeclare não levava achado **e**
  amnistiava as anteriores: a declaração que concede a amnistia é a que a base
  não tem.
- **(c) a ordem era o `sorted()` do caminho**, e a superfície `migracoes` aceita
  `*.sql` em qualquer sítio da árvore.

E o argumento de âmbito: a dívida **94** diz por escrito que mexer num *gate* de
bloqueio pede dois revisores, e foi por isso que o KAM-025 não mexeu.

**Disposição: a regra inferida foi retirada e substituída por uma declaração
nomeada.** `ci/canon-lint.yaml` ganha `dominios_historicos`: uma entrada por
declaração histórica, com revisão, tabela, coluna, ticket, razão e data. Não se
infere nada — os três buracos fecham-se por construção, porque não há inferência
onde possam existir. A entrada é por **revisão e coluna**, não por tabela nem por
ordem. A `revisao` nomeada tem de existir na árvore, ou o *gate* recusa a
política. Três baterias novas, a primeira com quatro asserções: sem entrada a
falta cobra-se, com a entrada certa passa, com uma entrada que nomeie **outra**
revisão não passa, e o excesso cobra-se sempre.

**O que fica em pé do argumento de âmbito**, e está dito no PR: isto continua a
ser uma alteração ao motor de um *gate* de bloqueio, feita dentro de um ticket de
dinheiro. A razão por que não se evita: sem ela nenhum domínio fechado deste
repositório pode crescer, e a alternativa era editar uma revisão já fundida —
que nunca se fez aqui (as 22 revisões têm **um** *commit* cada, medido com
`git log` por ficheiro). A caixa dos dois revisores continua vazia, como em toda
esta linha.

### 6. A espera de 3 s prende uma tomada do *pool*, e a espera por uma tomada não tem tecto

**Caso concreto.** `vaga = await self._tomadas.get()` corre **fora** do
`asyncio.wait_for`. Com `LIGACOES_POR_OMISSAO = 4` e o backend de 4 s do achado
1, quatro toques duplicados ocupam as quatro tomadas 3 s inteiros a sondar; um
`get_price_stock` de **outro tenant** espera ≥ 3 s antes de o seu próprio
temporizador começar — excede o tecto da sua classe sem que nada o registe. É o
defeito que o `KAMBA_TLS_LIGACOES` do KAM-028 diz ter fechado, com 3 s em vez de
200 ms. A bateria do critério 1 usa `LIGACOES = 12` e 50 ms, pelo que a omissão
de produção nunca é exercitada em concorrência.

**Disposição: declarado, não corrigido, e ligado ao achado 1.** A causa é a
mesma: a espera só é longa porque o tecto dela desencontra o tecto do backend.
Corrigir aqui (pôr o `get` dentro do `wait_for`, ou a espera fora da tomada)
mexe no `invoke` do KAM-028 e na forma do *pool*, que é desenho dele e não deste
ticket. Fica na dívida **112** com o achado 1, e o credor é o KAM-084, que é quem
calibra tectos e carga.

### 7. A premissa do critério 4 estava afirmada contra o documento que cita

A *docstring* de `Pedido.chave` dizia que «o COM recebe-a e **deriva dela** a sua
`intent_key`». O `03` §6.3 define `intent_key` por HMAC de
`(tenant, contacto, draft_id, draft_version)` — não tem esta chave dentro — e o
Contexto do próprio bloco diz «**nenhuma das duas depende da outra**». A frase era
falsa e estava no sítio que sustenta o critério 4. E o que resta a sustentá-lo é
um duplo construído para a ter: não há *lint* nem contrato que obrigue um
executor a ler `Pedido.chave`.

**Disposição: a frase falsa corrigida**, e o limite escrito onde se afirma o
critério: o que o campo garante é que o backend **recebe** a chave; usá-la é
contrato do KAM-046 e do KAM-035, e enquanto nenhum executor real existir a
propriedade está provada só contra o duplo. Está na secção de verificação do
bloco e na *docstring*.

### 8. `key` é chave primária global e a visibilidade é por RLS

Se existisse uma linha com a mesma `key` e outro `tenant_id`, o
`ON CONFLICT DO NOTHING` não inseria **e** o `SELECT` não a via: sondava 3 s e
devolvia `UPSTREAM_TIMEOUT` sem nada no registo. O revisor marca a
alcançabilidade como **suspeita** e a consequência como concreta.

**Disposição: recusado, com razão.** Chegar lá exige uma colisão de `sha256`: a
derivação inclui o `tenant_id`, pelo que duas chaves iguais de *tenants*
diferentes são uma colisão e não um defeito de uso. `UNIQUE (tenant_id, key)`
seria endurecimento de um caminho inalcançável ao preço de tocar outra vez em
cinco pontos de registo. Fica a razão escrita no ramo em causa.

---

## Nice to have

### 9. `varrer` escreve no `platform` fora do `tenant_guard.tx_batch`

Sem nome de *job*, sem contador, sem `rollback`. **Recusado com razão:** é o
mesmo padrão do `retencao.varrer` do KAM-026, e mudá-lo aqui divergia os dois.
Vale a observação de que este escreve no `platform` e aquele no `lg`.

### 10. Afirmações por fechar na documentação

- `02` §6.3 (iii) continuava a dizer que «o *lock* por conversa serializa-os», e
  esse trinco foi substituído por uma `asyncio.Queue` na revisão do KAM-028: o
  único serializador é o `ON CONFLICT`. **Corrigido.**
- A *docstring* de `test_mil_chaves_…` dizia que o telefone entra «em todas as
  partes de onde ela se deriva» e ele entra só no `cart_id`. **Corrigido.**
- O teste de propriedade do critério 6 é, nas mil combinações, mil vezes a mesma
  invariante estrutural, e não mede **injectividade** nas mil. **Aceite e
  escrito** na secção de verificação: o que as mil medem é estabilidade, a
  injectividade está medida em quatro pares (`test_as_quatro_partes_entram_todas`)
  e a ausência de colisão é o argumento de construção do próprio revisor.

---

## As perguntas adversariais, e o que elas deram

| Pergunta | Resultado |
|---|---|
| Interleaving que duplica, perde ou pendura | **Dois achados** (1 e 2), os dois com encomenda a dobrar no fim |
| A derivação da chave | **Resistiu.** O `f"{len(bytes)}:" + bytes` por parte é *prefix-free* e injectivo por construção — lê-se o decimal até ao `:` e consomem-se exactamente esses octetos, pelo que nenhuma partição alternativa descodifica. Sem relógio, telefone nem BSUID no caminho. Uma reserva (**suspeita**): `str(getattr(...))` sobre um `campo_de_confirmacao` que não fosse `str` punha a chave a depender do `repr` do tipo; hoje é `cart_id: str` |
| Critério satisfeito pela razão errada | **Um achado** (3), no critério 5. Os critérios 2 e 3 resistiram |
| A migração | **Resistiu.** `CHECK` certos nos dois sentidos (o `estado` é `NOT NULL`, logo sem o buraco do `NULL IN (…)`); `GRANT` por coluna a bater com os comentários; o `ALTER` da `tool_audit` não quebra uma base com linhas, porque o domínio novo é superconjunto estrito. Duas notas menores: `DROP CONSTRAINT` sem `IF EXISTS`, e o `ADD CONSTRAINT` validante toma `ACCESS EXCLUSIVE` e varre a tabela — `NOT VALID` + `VALIDATE` evitava-o na que vai ser a maior do `platform` |
| A alteração ao *gate* | **Um achado com três buracos demonstrados** (5). A regra foi substituída |
| Afirmações mais fortes do que a evidência | **Três** (7 e 10), todas corrigidas |

E uma coisa que o revisor confirmou e vale registar: a correcção do
`fix(KAM-029)` — limpar a marca de posse à entrada — **está certa** e fecha a
máscara da excepção nesse caminho. O `registar_se_falta` do `finally` sobre uma
ligação já fechada pode mascarar a excepção original quando `inv.registada` é
`False`, mas isso é anterior a este ticket (o `ligacao.close()` é do KAM-028).

## Veredicto

**REPROVADO** na revisão. Os quatro *must fix* estão tratados: três corrigidos
com teste que falha sem a correcção, e o primeiro devolvido como tensão entre dois
critérios do próprio bloco — com o critério 1 a passar a **parcial**, a condição
escrita, e a dívida **112** com credor. Três dos quatro *should fix* corrigidos; o
oitavo recusado com a razão escrita.

**A lição de método deste ticket**, e é a mesma que o KAM-028 pagou: os 405 testes
passavam todos antes desta revisão. Nenhum deles chamava a camada com um backend
mais lento do que o tecto de espera, nenhum semeava uma linha `em_curso` de duas
idades diferentes, e nenhum perguntava se o `args_hash` sobrevivia a o modelo
reemitir um campo de omissão. As três perguntas não tinham sido feitas.
