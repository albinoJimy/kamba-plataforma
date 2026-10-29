# ANÁLISE 39 — KAM-037, modo determinístico sem LLM e degradação

| Campo | Valor |
|---|---|
| Alvo | `feature/KAM-037-modo-deterministico`, commit `94ee77a` sobre `refs/remotes/publico/main` |
| Worktree | `C:\Jimy\Ideias\.claude\worktrees\suspicious-mahavira-4b20e2` |
| Diff | 19 ficheiros, 2475 inserções — **todos** em `services/agr` |
| Papel | revisão adversarial: procurar razões para o resultado estar errado |
| Canon lido | bloco KAM-037 de `specs/EPIC-03_Agent_Runtime_Verticais.md`, `docs/tecnica/02` §7.3, §13.3, §14, §15.2, `docs/tecnica/00` princípio 12, `docs/dividas-documentais.md` 124 e 135 |
| Suite em `94ee77a` + árvore de trabalho | **código de saída 1** (ver C10) |
| Suite em `34bcf82` | **código de saída 0** — `Ran 1147 tests … OK` |

**29 achados: 12 `CONFIRMADO` (10 em aberto, 2 pagos durante a revisão), 4
`PLAUSÍVEL`, 13 `MORTO`.** Ordenados por severidade dentro de cada classe.

> **O worktree mexeu-se a meio desta revisão.** O alvo declarado é `94ee77a`.
> Enquanto media, outra sessão commitou `d60aae2` («a secção de verificação, o
> dicionário §3.35 e o runbook»), `683b1b5` e `34bcf82`, deixando o worktree
> limpo e a suite verde. **C10 e C11 ficam escritos porque eram defeitos reais do
> commit em revisão, e marcam-se como pagos.** Reverifiquei **todos** os outros
> achados contra `34bcf82`: C1 a C9 e P1 a P4 **mantêm-se**, com as mesmas
> reproduções. A nova secção de verificação não nomeia nenhum deles — e em dois
> casos (C5 e C8) afirma o contrário do que eu medi, o que os reforça em vez de
> os matar.

Todas as reproduções correram no contentor `kamba-agr-tests`, com
`PYTHONPATH=/w/services/agr/src:/w/libs/py-core/src:/w/tools` e
`cwd=/w/services/agr/tests`, e lendo o **código de saída** e não a última linha.

---

## CONFIRMADO

### C1 — Crítico. Os botões que o modo degradado emite deixam de funcionar no instante em que o LLM recupera

**Onde.** `verticais/vendedor/nos.py:975-981` (o `if estado.get("degradado")` do
`classify`) e `verticais/vendedor/degradado/intencoes.py:67-72` e `:115-121`.

**O que está errado.** O mapa `INTENCAO_DA_OPCAO` — a única coisa que traduz
`menu:encomenda`, `menu:pagamento`, `menu:loja` e `menu:humano` em intenção — só
é consultado dentro do `intencao_sem_llm`, e o `intencao_sem_llm` só corre quando
`estado["degradado"]` é verdade. O `degradado` é um campo **do turno**
(`CAMPOS_DO_TURNO`, e é isso que entrega o critério 7). O botão, porém, **fica no
ecrã do WhatsApp** indefinidamente. Logo: o turno em que o menu sai reconhece os
identificadores; o turno seguinte, com o modelo recuperado, não os reconhece.

**Caso concreto** (`probe5`, grafo compilado, classificador ligado e a devolver
`outro`):

```
menu:encomenda -> intent='outro'            | o modelo viu=['menu:encomenda']
                  enviado='…So posso ajudar com os produtos, os precos e os pedidos desta loja. Prefere falar com um colega?'
menu:loja      -> intent='outro'            | o modelo viu=['menu:loja']       | mesmo texto
menu:humano    -> intent='outro'            | o modelo viu=['menu:humano']     | mesmo texto
menu:pagamento -> intent='pagamento_estado' | o modelo viu=[]
                  enviado='…Nao encontrei esse artigo no catalogo da loja.'
```

Sem classificador ligado (a omissão de hoje) o desfecho é o mesmo: `outro` →
`safe_reply`.

Três consequências, por ordem de gravidade:

1. **`menu:humano` não abre handoff.** Um cliente que pede um colega recebe
   «só posso ajudar com os produtos desta loja». É um pedido de pessoa não
   honrado, e o §8.4 e o `registry/vendedor.yaml` tratam-no como gatilho.
2. **O identificador de botão cru vai ao modelo como se fosse texto do
   cliente.** O cabeçalho do `nos.py:22-26` escreve a regra pelo nome — «um botão
   `confirm:*` **nunca** passa por modelo: a intenção está no identificador» — e
   o §15.1 repete-a. Os `menu:*` passam.
3. É **exactamente** a classe de defeito que o achado 3 da revisão do KAM-031
   pagou e que o `_CANCELAMENTO` (`nos.py:714-726`) existe para corrigir: «o
   botão `confirm:{cart_id}` da mensagem anterior continua no ecrã do WhatsApp».
   A lição está escrita no ficheiro e não foi aplicada aos botões novos.

**Severidade.** Crítica. O remédio é o mesmo do `_CANCELAMENTO`: tirar o
`INTENCAO_DA_OPCAO` de dentro do caminho degradado e consultá-lo no `classify`
antes do `intencao_por_regras`, degradado ou não — um `menu:*` é um
identificador nosso e a intenção dele não depende da saúde do modelo.

---

### C2 — Alto. Duas das quatro opções que o modo anuncia respondem «Não encontrei esse artigo no catálogo da loja»

**Onde.** `verticais/vendedor/nos.py:1235-1238` (`order_status`), com
`degradado/intencoes.py:68-69` e `encaminhadores.py:49-50`.

**O que está errado.** `menu:encomenda` → `encomenda` e `menu:pagamento` →
`pagamento_estado`; os dois dão a chave `status` e vão ao `order_status`, que
exige uma referência **no texto do cliente**
(`_REFERENCIA.search(_texto_do_cliente(estado))`). No turno de um toque, o texto
do turno *é* o identificador do botão, que não tem referência nenhuma. Resultado:
`NOT_FOUND` → `FRASE_DO_AVISO[NOT_FOUND]` → «Não encontrei esse **artigo** no
**catálogo** da loja» a quem pediu o estado de um pedido ou a referência de
pagamento.

**Caso concreto** (`probe2`, disjuntor aberto, entrada interactiva):

```
menu:pagamento -> intent='pagamento_estado' avisos=('NOT_FOUND',)
                  enviado='…Nao encontrei esse artigo no catalogo da loja.'
menu:encomenda -> intent='encomenda'        avisos=('NOT_FOUND',)
                  enviado='…Nao encontrei esse artigo no catalogo da loja.'
menu:loja      -> intent='info_loja'        avisos=()
                  enviado='…Casa Bela\nLuanda'            (este funciona)
```

**E não há saída.** Nada no estado registou que o cliente pediu o estado de um
pedido, pelo que não há pergunta de seguimento; e a referência escrita sozinha no
turno seguinte não é reconhecida (`probe4`):

```
'ABC-123'          -> outro      | servida=False   (volta ao menu)
'ABC-123?'         -> outro      | servida=False
'o pedido ABC-123' -> encomenda  | servida=True
```

Ou seja: pelo menu, a capacidade «estado do pedido por `numero_publico`» do
critério 2 é **inalcançável**. E o `MENU_PRINCIPAL` tem três opções, uma das
quais é esta.

**Severidade.** Alta. O critério 2 enumera cinco capacidades; duas delas
respondem com a frase errada e uma delas está no menu principal. O
`degradado/__init__.py:45` marca a referência de pagamento como «parcial, dívida
124» — a dívida 124 é sobre **não poder mostrar os dígitos**, e não sobre
responder com uma mensagem de catálogo a quem tocou no botão de pagamentos.

---

### C3 — Alto. O disjuntor é global por processo e o orçamento é por tenant: um tenant sem orçamento degrada todos os outros

**Onde.** `degradacao.py:130` (`BACKEND_DO_LLM: Final = "llm"`), `:290-303`
(`registar_falha`, que conta o `budget` de propósito), `:255`
(`motivo_antes_do_turno` recebe `tenant_id` e pergunta
`self._disjuntor.aberto(BACKEND_DO_LLM)` — o `tenant_id` é ignorado neste ramo).

**O que está errado.** O orçamento esgotado é da **chave virtual do tenant** —
`llm/cliente.py:209` manda `Authorization: Bearer {self._chave_virtual(ctx.tenant_id)}`
e o §13.3 fixa «orçamento mensal da **chave** = 15% × mensalidade». O disjuntor é
um só, com uma chave. Logo três turnos seguidos de um tenant sem orçamento abrem
a porta para **toda** a réplica.

**Caso concreto** (`probe1 §A`):

```
det = DetectorDeDegradacao(metricas=MetricasDoAgr())
det.registar_falha(OrcamentoEsgotado(...)) x3      # tenant A
det.motivo_antes_do_turno("tenant-B")  ->  'breaker'
```

Todos os outros tenants entram em modo determinístico durante a pausa de 30 s, e
o ciclo repete-se cada vez que o tenant A volta a tentar. O `docstring` do módulo
justifica «um e não um por alias» (`:126-129`) e **nunca aborda** a dimensão
tenant — que é a que o anti-vizinho-ruidoso do §15.2 regra 2 existe para
proteger.

**Severidade.** Alta: é amplificação de falha entre tenants, e o `budget` foi
contado no disjuntor por escolha explícita (`:293-298`), o que a torna activa e
não acidental. A mesma leitura vale, em menor grau, para o `http_429` quando o
ritmo é por chave virtual.

---

### C4 — Alto. Um `DestinoNegado` (recusa ADR-008) conta como avaria do modelo e abre o disjuntor global

**Onde.** `degradacao.py:154-180` (`motivo_do_erro`) e `llm/erros.py:123-134`.

**O que está errado.** `DestinoNegado` **é** um `ErroDeLlm` — a recusa do *gate*
de destino por transferência de dados pessoais para fora de Angola sem
autorização (ADR-008, `llm/cliente.py:196-202`). O `motivo_do_erro` não tem ramo
para ele: `resultado == "destino_negado"` não é `timeout` nem `budget`, e
`estado_http` é `None`, pelo que cai no `return MOTIVO_BREAKER` final — o ramo que
o comentário descreve como «avaria, e a avaria é o que o disjuntor existe para
medir».

**Caso concreto** (`probe1 §B`):

```
motivo_do_erro(DestinoNegado("destino nao autorizado", "router")) -> 'breaker'
registar_falha(DestinoNegado(...)) x3  ->  motivo_antes_do_turno("outro-tenant") == 'breaker'
```

Três recusas de conformidade — que são **permanentes** até alguém autorizar o
destino, e não uma avaria transitória — abrem o disjuntor para todos os tenants e
contam em `agr_degraded_turns_total{motivo="breaker"}`. O painel diz «o modelo
ficou inalcançável» e o que aconteceu foi uma barreira de soberania a funcionar.

**Severidade.** Alta, e cruza com a C3: o *gate* de destino é **por tenant**
(`autorizar(ctx.tenant_id, fornecedor, finalidade)`), logo um tenant sem destino
autorizado degrada a plataforma.

---

### C5 — Alto. O alerta do critério 6 é calculado e descartado: não há alerta nenhum

**Onde.** `degradacao.py:316-367` (`registar_turno`, «Devolve se deve alertar») e
os seus **dois únicos** chamadores: `verticais/vendedor/nos.py:913`
(`_degradacao_antes_do_turno`) e `nos.py:1054-1056` (`_degradar`).

```
nos.py:913   deps.degradacao.registar_turno(tenant_id, str(estado.get("turn_id") or ""), motivo)
nos.py:1054  deps.degradacao.registar_turno(
                 estado["tenant_id"], str(estado.get("turn_id") or ""), motivo
             )
```

Nenhum dos dois atribui o resultado. `grep -rn "registar_turno" services/agr/src`
devolve exactamente estas duas chamadas e as definições. O booleano morre ali: não
há métrica, não há log, não há efeito.

**O que não substitui o alerta.** `METRICA_DEGRADACAO_ALERTA`
(`agr_degraded_breaker_aberto_total`) conta **aberturas do disjuntor**, que é
outra coisa — o próprio runbook as separa em «três números, e nenhum substitui os
outros». A proporcão de 5% em 15 min por tenant não aparece em sítio nenhum.

**O ensaio mede a função e não o sistema.** `TestJanelaEAlerta` (test_degradacao.py
:468-495) afirma `assertTrue(det.registar_turno(...))` — isto é, mede o valor de
retorno de um método, não que alguma coisa aconteça por causa dele. Passaria
inalterado se os dois chamadores não existissem.

**E a secção de verificação afirma o contrário.** A linha do critério 6 (acrescentada
em `d60aae2`) escreve «a métrica existe com o **motivo** por etiqueta e **o alerta
mede-se** (`TestJanelaEAlerta`, oito ensaios)». O que esses oito ensaios medem é o
**valor de retorno de um método**; não há alerta, porque não há consumidor. As duas
divergências que a linha confessa são outras (o `429`→`http_429` e o `tenant` em
etiqueta) — esta não está confessada.

**Severidade.** Alta: é metade do critério 6 («alerta quando > 5% dos turnos de um
tenant em 15 min») sem nenhum caminho de execução. O runbook assume-o escrito
(«§1. Como se vê que há degradação»). O limiar ser *proposta* não dispensa o
alerta de existir.

---

### C6 — Alto. A «lista de opções» sai como bloco `buttons` com 4 ids, e o contrato do Outbound recusa mais de 3

**Onde.** `degradado/textos.py:86-91` (`LISTA_DE_OPCOES`, quatro opções),
`degradado/nos.py:92` (`{"type": "buttons", "ids": list(opcoes)}`),
`validador/render.py:61` (`MAX_BOTOES: Final = 10`),
`packages/core-ts/src/outbound/contrato.ts:125-126`
(`MAXIMO_DE_BOTOES = 3`, `MAXIMO_DE_LINHAS = 10`),
`packages/core-ts/src/outbound/decisao.ts:81-83`.

**O que está errado.** O bloco `buttons` do §9.1 não distingue *reply buttons* de
*lista* — o próprio `textos.py:42-51` nomeia a indistinção. O que o ticket faz é
decidir «pela contagem» (3 → menu, 4 → lista) e entregar a decisão a um consumidor
que não tem regra para a ler: o `send` passa `botoes=('menu:encomenda',
'menu:pagamento', 'menu:loja', 'menu:humano')` e mais nada. Do lado do Outbound:

```ts
export const MAXIMO_DE_BOTOES = 3;
export function formaInvalida(corpo: Corpo): MotivoDeRecusa | null {
  if (corpo.tipo === "botoes" && corpo.botoes.length > MAXIMO_DE_BOTOES) return "TOO_MANY_BUTTONS";
```

Se a ponte AGR→Outbound mapear um `buttons` de 4 ids para `{tipo: "botoes"}`, o
`formaInvalida` recusa e **nada é enviado** — e o turno degradado mais comum é
precisamente esse (texto livre não reconhecido → `MSG_LISTA` + 4 opções, e também
`MSG_SEM_CATALOGO` + 4 opções). Isso é o oposto do critério 1 («sem mensagem em
falta»).

**Caso concreto** (`probe2 §5`, grafo compilado):

```
'quanto custa a camisa azul' (degradado)
 -> botoes=('menu:encomenda', 'menu:pagamento', 'menu:loja', 'menu:humano')   # quatro
```

**O ensaio afirma as quatro.** `test_um_pedido_de_catalogo_recebe_a_explicacao_e_a_lista`
(test_degradacao.py:751-756) faz `assertEqual(botoes, txt.LISTA_DE_OPCOES)` sem
confrontar com nenhum tecto; o `assertLessEqual(len(botoes), MAX_BOTOES_DO_MENU)`
só existe no ensaio do menu. O `MAX_BOTOES_DO_MENU = 3` é uma constante que nada
no código de execução lê — `grep -rn MAX_BOTOES_DO_MENU` só a encontra na
definição e no ensaio.

**Segunda metade, e é do critério.** O `Corpo` do Outbound exige
`{id, titulo}` por botão (`contrato.ts:150`). O modo determinístico produz
**ids sem rótulo**: não há rótulo em pt de Angola para `menu:encomenda` em
sítio nenhum da árvore. O critério pede «textos estáticos em `pt` de Angola
versionados» e o `VERSAO_DOS_TEXTOS` versiona três frases e zero rótulos; o que
o cliente vê no botão fica por decidir, e se for o id cru é `menu:encomenda`.

**Severidade.** Alta. Até a ponte existir, isto é um contrato que já se sabe
inválido contra uma constante que está neste repositório.

---

### C7 — Médio-alto. Um erro que não é do LLM acaba contado como turno degradado, pela tentativa de meio-aberto

**Onde.** `degradacao.py:274-282` (`pode_chamar_o_llm`),
`tls/disjuntor.py:131-143` (`a_experimentar` / `experimenta_ate`),
`verticais/vendedor/nos.py:985-1003`.

**O que está errado.** A barreira 1 do ticket diz que um erro que não seja do LLM
não degrada, não responde e não é contado como turno degradado. O turno que o
sofre cumpre as três — a excepção sobe. Mas o **estado que ele deixa no disjuntor**
não: o `classify` chama `pode_chamar_o_llm()` (que **consome** a tentativa de
meio-aberto e marca `a_experimentar = True`) e só depois chama o classificador.
Se este levantar algo que não é `ErroDeLlm`, ninguém chama `registar_falha` nem
`absolver`, e o `permite()` devolve `False` durante os 30 s do `experimenta_ate`.
Nesse intervalo o `aberto()` já é falso, pelo que os turnos nascem normais e
degradam no `classify` com `motivo="breaker"`.

**Caso concreto** (`probe3 §4`):

```
3x registar_falha(TempoEsgotado)  ->  disjuntor aberto
relogio.avancar(31)
pode_chamar_o_llm()      -> True    # meia-tentativa consumida
<classificador levanta RuntimeError("a base caiu")>   # nem registar_falha nem absolver
motivo_antes_do_turno()  -> None
pode_chamar_o_llm()      -> False
turno seguinte           -> degradado={'motivo': 'breaker'} | 1 mensagem enviada
metrica                  -> agr_degraded_turns_total{motivo="breaker"} 1
```

Isto é, um `RuntimeError` que não é do modelo produz, indirectamente, turnos
degradados contados como `breaker` — e para **todos** os tenants, pela C3. O
`caducar` do `tls/disjuntor.py` limita o dano a uma pausa; não o elimina.

**Severidade.** Média-alta. O remédio é um `try/finally` que chame `absolver`
quando a tentativa de meio-aberto termina sem veredicto sobre a saúde do modelo —
o `absolver` existe no disjuntor exactamente para isto e o detector não o expõe.

---

### C8 — Médio. O critério 3 não cita nada: a confirmação degradada responde sem referência e sem *fact*, e o ensaio que diz medi-lo não o mede

**Onde.** `verticais/vendedor/nos.py:1364-1390` (`compose`),
`:1408-1431` (`_blocos_dos_dados`), e
`test_degradacao.py:789-808`.

**O que está errado.** O critério 3 pede «cria **1** pedido **e responde com a
referência por *template* estático e *facts***». A primeira metade cumpre-se. A
segunda não cita nada: o `tem_o_total` é falso porque o *fact* do carrinho é do
turno anterior (e isso está certo, §5.3), e nenhum bloco leva a referência.

**Caso concreto** (`probe3 §1`, conversa com checkpointer, carrinho no turno 1 e
disjuntor aberto no turno 2):

```
turno 1 (normal)    : 'SKU-100 - Camisa Azul\nTotal: 12 500 Kz'  botoes=('confirm:c1','cancelar','falar_com_humano')
turno 2 (degradado) : 'O seu pedido ficou registado. A loja confirma o pagamento e avisa-o aqui.\npendente'
                      botoes=()  |  draft.dados={'order_id': 'o3', 'estado': 'pendente'}
                      encomendas={'o3': (...)}      # um pedido, correcto
```

O cliente acaba de pagar e recebe zero números, zero referência e a palavra
`pendente` numa linha solta — o campo `estado` do backend emitido como bloco
`text` isolado pelo `_blocos_dos_dados`, sem frase que o enquadre.

**O ensaio passa pela razão errada.** Chama-se
`test_a_confirmacao_degradada_cria_um_pedido_e_cita_por_fact` e as suas
afirmações são: `degradado` verdade, `+1` encomenda, `stage == awaiting_payment`,
`draft["ok"]`. Nenhuma olha para um *fact* citado. Passaria inalterado com zero
facts no texto — que é o que acontece.

**E a secção de verificação marca este critério como «satisfeito».** A linha
(acrescentada em `d60aae2`) prova três coisas — um pedido, `awaiting_payment`,
`draft["ok"]` — e acrescenta «nenhum texto livre: o `create_order` e o `compose`
são os do grafo normal e só produzem blocos». Isso responde à **terceira** cláusula
do critério e não à segunda. A segunda («responde com a referência por *template*
estático e *facts*») não tem prova e não está cumprida; o critério 2 está marcado
`parcial` pela mesma dívida 124 e o 3 está marcado `satisfeito`, o que é
incoerente entre si.

**Severidade.** Média. A dívida 124 cobre **não poder mostrar os dígitos da
referência**; não cobre a ausência de qualquer *fact*, nem o nome do ensaio
afirmar o contrário do que ele mede, nem a caixa ficar `satisfeito`.

---

### C9 — Médio. O ensaio do critério 2 passa com o comportamento errado

**Onde.** `test_degradacao.py:778-785`.

```python
def test_o_estado_do_pedido_e_servido_pelo_order_status(self) -> None:
    grafo, _, backend, saida, _ = self._grafo_degradado()
    final = correr(grafo, estado_de("o meu pedido ABC-123 ja saiu?", tenant_id=TENANT))
    self.assertEqual(final["intent"], "encomenda")
    self.assertEqual(len(saida.enviadas), 1)
```

Duas afirmações, e nenhuma olha para o texto. **O estado do pedido não é
servido** (`probe3 §2`):

```
intent='encomenda'  avisos=('NOT_FOUND',)
enviado='…Nao encontrei esse artigo no catalogo da loja.'
```

`ABC-123` não existe no backend de ensaio, o aviso é `NOT_FOUND`, e o texto que
sai é a frase de catálogo. O ensaio afirma o nome de um comportamento e mede
apenas que *alguma* mensagem saiu. O `backend` é desempacotado e nunca usado.

**Severidade.** Média (de confiança, não de produto): é o ensaio que devia ter
apanhado o C2 e não apanha. Nenhum ensaio da bateria toca `menu:encomenda`,
`menu:pagamento` ou `menu:loja` através do grafo — só `OPCAO_HUMANO`
(`test_falar_com_humano_vai_a_handoff_com_motivo`). Três das quatro portas novas
do modo não têm ensaio de ponta a ponta.

---

### C10 — Médio. **PAGO em `d60aae2`..`34bcf82`.** A suite não passava no worktree, e o `§3.35` que o código cita cinco vezes não estava no commit

**A suite.** Comando do briefing, código de saída lido:

```
EXIT=1
FAIL: test_a_emenda_139_esta_no_controlo_de_versoes (test_validador.TestCanon)
AssertionError: '| Versão | 1.45 — **PROPOSTA**' not found in '…| Versão | 1.44 — **PROPOSTA** …'
```

A modificação **não-commitada** de `specs/02_Dicionario_de_Dados_Canonico.md`
acrescenta a linha `| 1.45 | Outubro 2026 |` à tabela de versões e deixa o
cabeçalho em `1.44`. O `test_a_emenda_139_esta_no_controlo_de_versoes`
(test_validador.py:1242-1258) calcula a última emenda da tabela e exige que o
cabeçalho a acompanhe. No estado **commitado** (sem a 1.45) o ensaio passa.

**O que não está no commit.** `git diff --name-only refs/remotes/publico/main..HEAD`
dá 19 ficheiros, todos sob `services/agr`. `git status --porcelain`:

```
 M specs/02_Dicionario_de_Dados_Canonico.md
?? docs/runbooks/degradacao-do-agr.md
```

- `git show HEAD:specs/02_Dicionario_de_Dados_Canonico.md | grep -c "3.35"` → **0**.
  O código commitado cita «§3.35» **cinco** vezes (`degradacao.py:103`,
  `metricas.py:46`, `arestas.py:145`, e duas na bateria) como o sítio onde o
  domínio dos cinco motivos e o nó `degraded_menu` são declarados. A secção
  existe só na árvore de trabalho.
- `docs/runbooks/degradacao-do-agr.md` está **untracked** e é citado pelo
  `degradacao.py:83`. A caixa de DoD «documentação do runbook de degradação
  actualizada» não é satisfeita pelo commit.
- `docs/dividas-documentais.md` (dívida 135, emenda 1.74) **já está** em
  `publico/main` — logo a metade documental deste ticket foi fundida antes do
  código, e a referência que ela faz a `specs/02 §3.35` já estava pendurada.

**Severidade.** Média, mas era a mais mecânica de todas: fundir `94ee77a` como
estava perdia a emenda 1.45 e o runbook, e deixava cinco citações a apontar para
nada; e a 1.45 commitada como estava deixava o gate de canon vermelho.

**Pago.** `d60aae2` commitou o runbook e o §3.35, `34bcf82` corrigiu o cabeçalho
do dicionário, e a suite em `34bcf82` sai com **0** (`Ran 1147 tests … OK`).
Reverificado: `git show HEAD:specs/02_Dicionario_de_Dados_Canonico.md | grep -c
"### 3.35"` → 1, `git log -1 -- docs/runbooks/degradacao-do-agr.md` → `d60aae2`,
`git status --porcelain` → vazio. Fica escrito porque a lição é de processo e não
de código: a metade documental do KAM-037 (dívida 135, emenda 1.74) já estava em
`publico/main` **antes** do código, com uma referência a um `§3.35` que ainda não
existia — a ordem de fusão deixou uma citação pendurada em `main` durante dois
commits.

---

### C11 — Médio. **PAGO em `d60aae2`.** A «secção de verificação do bloco», citada cinco vezes pelo código novo, não existia

**Onde.** `arestas.py:71`, `degradado/intencoes.py:35`, `degradado/nos.py:22`,
`degradado/__init__.py:52`, `__main__.py:726`; mais quatro citações na bateria
(test_degradacao.py:20, 214, 877, 928).

**O que está errado.** O bloco do KAM-037 em
`specs/EPIC-03_Agent_Runtime_Verticais.md` vai de «### Handoff para Claude Code»
directo ao `## KAM-038` — não tem «### Verificação dos Critérios de Aceitação»
(ao contrário do KAM-038, que tem). E as **8** caixas de Critérios de Aceitação e
as **7** de Definition of Done estão todas `[ ]`.

Três decisões que o código diz ter devolvido ao fundador não têm, por isso, onde
estar escritas:

1. a pesquisa de catálogo ficar **fora** do modo, pela letra do critério 2
   (`degradado/intencoes.py:25-44`);
2. o `429` do critério 6 ter virado `http_429` por causa da gramática `OBS-I`
   (`degradacao.py:24-34`);
3. **degradado × concierge** — a leitura «a resposta determinística também vai a
   aprovação» (`test_degradacao.py:915-930`), que é o que torna o critério 1 falso
   para tenants em concierge.

**Severidade.** Média. Um ticket que fecha com decisões devolvidas e sem o sítio
onde as devolver é um ticket que as perde.

**Pago.** `d60aae2` acrescentou a secção (linha 2694), com a tabela dos oito
critérios, a do DoD e a hipótese `degradado × concierge` em forma de HIPÓTESE. As
três decisões têm agora onde estar. **O que a secção não nomeia** são os achados
C1 a C9 desta análise: o critério 2 fica `parcial` só pela referência de pagamento
e pela pesquisa de catálogo, o 3 fica `satisfeito`, e o 6 diz que o alerta se
mede. Ver C5 e C8.

---

### C12 — Baixo. Contagens de cabeçalho que passaram a mentir

| Onde | Diz | É (medido) |
|---|---|---|
| `verticais/vendedor/nos.py:1` | «Os vinte e um nós do grafo do Vendedor» | `len(NOS_DO_GRAFO) == 23` (e o comentário da linha 1905 diz «vinte e três») |
| `verticais/vendedor/arestas.py:108` | «Os vinte e um nós, pela ordem do §7.4» | `len(tabela.NOS) == 24` |
| `verticais/vendedor/encaminhadores.py:1` | «Os dez encaminhadores do §7.4 — e os dez são funções puras» | `len(POR_NO) == 13`, 12 funções distintas |

As duas primeiras são de ficheiros que **este** ticket abre (a segunda acrescenta
o `degraded_menu` à lista imediatamente abaixo da frase errada). As contagens que
os ensaios afirmam estão **certas** e o filtro está correcto: `LINHAS_DO_73 == 39`,
`len(do_73()) == 42` com 39 linhas distintas, `len(do_concierge()) == 4`,
`len(do_degradado()) == 2`, e a soma iguala `len(ARESTAS)` — e o `do_73()` filtra
pela lista `FONTES_FORA_DO_73` e não por negação de um valor, o que é a correcção
certa (sem ela a contagem teria passado de 42 para 44 em silêncio).

---

## PLAUSÍVEL

### P1 — `turn_id` vazio colapsa turnos concorrentes numa única entrada da janela

`verticais/vendedor/nos.py:913` e `:1055` passam
`str(estado.get("turn_id") or "")`. O `registar_turno` identifica a entrada por
`e[1] == turn_id` (`degradacao.py:353`), pelo que todos os turnos com `turn_id`
vazio do mesmo tenant são **o mesmo turno**:

```
# probe1 §C
d3.registar_turno("t", "", None) x3
len(d3._turnos["t"]) == 1          # tres turnos, uma entrada
```

Com `tecto_por_tenant = 3` há até três turnos em voo, e o denominador do critério
6 encolhe silenciosamente. O ensaio `test_a_degradacao_de_um_turno_nao_marca_o_turno_do_lado`
cobre o caso com três `turn_id` distintos e não este.

**O que falta para decidir.** Um caminho real em que o grafo seja invocado sem
`turn_id`. Hoje o `chave_do_turno` do `send` faz `estado["turn_id"]` e levantaria
`KeyError`, pelo que o turno falharia — mas falharia **já mal contado**, porque o
`ingest` conta antes de qualquer nó precisar do campo. Decide-se quando a porta
`grafos` do `turno.py` for ligada; até lá, o `or ""` é um valor de omissão a
transportar uma colisão em vez de levantar.

### P2 — O `agora` do `registar_turno` lê-se fora do trinco, e o `_podar` assume a deque ordenada

`degradacao.py:349-360`: `agora = self._relogio()` corre **antes** do
`with self._trinco`. Com turnos concorrentes do mesmo tenant, a thread com o
instante menor pode anexar depois da que tem o instante maior, e o `_podar` faz
`while fila and fila[0][0] <= limite` — pára na primeira entrada não expirada e
deixa entradas mais velhas presas atrás dela.

**O que falta.** Medir se a inversão é observável com `time.monotonic` e a GIL.
O efeito é memória limitada pelo número de threads por tenant (até 3), não
correcção do alerta — mas contradiz a *docstring* do `_podar`, que vende um
«tecto de memória igual aos turnos de quinze minutos».

### P3 — Degradado × concierge sem `ServicoDeRascunho` dá um turno que falha indefinidamente

`probe3 §3`, com a política activa e `rascunho=None`:

```
LEVANTOU: ConciergeSemServicoError
enviadas: []
```

O turno falha, o *job* volta à fila e, com o LLM em baixo, repete sempre o mesmo
caminho. É comportamento do KAM-114 (`nos.py:1823-1831`) e não deste ticket, mas o
modo degradado passa a ser o caminho que mais vezes o atinge, porque com o LLM em
baixo **todos** os turnos chegam ao `draft_prepare`.

**O que falta.** Saber se algum tenant do Piloto concierge pode arrancar com a
política ligada e o serviço de rascunho por ligar — isto é, se a guarda de
arranque do `__main__.py` cobre esse par.

### P4 — O critério 1 é falso para tenants em concierge, e a decisão não tem onde estar escrita

`TestDegradadoComConcierge.test_o_menu_degradado_vai_a_aprovacao_e_nao_sai_ao_cliente`
mede `saida.enviadas == []`. **A barreira do KAM-114 é respeitada e isso está
certo** — o `send` intercepta as cinco arestas que lhe chegam (32, as três da 34,
e a 37), e o menu degradado sai por uma delas, pelo que não há furo. O problema é
o outro lado: o critério 1 («0 turnos sem resposta») fica falso para esses
tenants, e a leitura escolhida entre as três possíveis está devolvida a uma
secção de verificação que não existe (C11).

**O que falta.** A decisão do fundador. As três leituras não são equivalentes: a
implementada preserva a barreira do KAM-114 ao custo do critério 1 do KAM-037, e
a inversa retirava uma barreira.

---

## MORTO

Procurei nestas áreas e o que parecia defeito não é. Fica escrito para não voltar.

### M1 — Os limiares do disjuntor não divergem da configuração real do proxy

`llm/litellm.config.yaml:55-56` e `llm/aliases.yaml:44-45` dão `allowed_fails: 3`
e `cooldown_time: 30`; `docs/evidencia/KAM-030-litellm.md:150-151` confirma-os
contra a imagem fixada (`r.allowed_fails == 3 ; r.cooldown_time == 30`);
`FALHAS_PARA_ABRIR = 3` e `PAUSA_MS = 30_000`. O bloco dizia «a validar na versão
fixada» e **não divergem**. E o `TestLimiaresDoDisjuntor` **lê os dois YAML** em
vez de copiar os números, pelo que mede o acoplamento e não a paciência de quem o
escreveu.

### M2 — Nenhum texto estático levanta no `renderizar` nem dispara a guarda de saída

Medido a correr (`probe4`), não lido: os 3 `MSG_*` do `degradado/textos.py`, os 9
`MSG_*` do `nos.py` e as 8 entradas de `FRASE_DO_AVISO` renderizam num bloco
`text` com zero *facts* sem levantar, e `violacao_de_saida` devolve `None` em
todos os 20. Não há dígito nem corrida de duas palavras de número.

### M3 — O `r_intent` não deixa intenção sem destino nem tem ramo de omissão que siga em frente

`CHAVE_DA_INTENCAO` (`encaminhadores.py:44-54`) cobre as nove de `INTENCOES`;
uma intenção fora das nove dá `other` → `safe_reply`, **inclusive degradado** —
a assimetria é deliberada e está escrita. A chave `menu` só se escolhe com
`estado.get("degradado")` **e** `not intencoes.serve(intencao)`. O `mapa_de("classify")`
é derivado da tabela (não escrito à mão) e tem as oito chaves; o
`_conferir_coerencia` do `grafo.py` e o
`test_as_arestas_do_compilado_sao_exactamente_as_da_tabela` confrontam-no com o
grafo compilado nos dois sentidos.

### M4 — O `estado_http` novo no `ErroDeLlm` não parte chamador nenhum, e o domínio fechado não foi violado

Terceiro parâmetro posicional com omissão `None`; os dois `raise` do
`llm/cliente.py:180` e `:225` continuam com dois argumentos e compilam. O
`RESULTADOS` do `llm/erros.py:48-55` continua a ser os **seis** valores — nenhum
valor novo, nenhuma revisão de base de dados, `CHECK` da `0023` intocado. O 429
distingue-se pelo atributo e não pelo `resultado`, e o `motivo_do_erro` verifica
`timeout` e `budget` **antes** do `estado_http`, pelo que um 422 de orçamento dá
`budget` e não `http_429`.

### M5 — Nenhum identificador entra em etiqueta de métrica, e nenhum texto de cliente sai por onde não devia

`METRICA_DEGRADADOS` leva só o `motivo`, lista fechada **derivada** de
`degradacao.MOTIVOS` (`metricas.py:443-449`) e não escrita duas vezes; os cinco
casam `^[a-z][a-z0-9_]{1,62}$`, e o `test_todos_casam_a_gramatica_de_etiqueta`
mede as duas metades — que os cinco passam e que `"429"` cru levanta
`EtiquetaInvalida`. `METRICA_DEGRADACAO_ALERTA` é sem etiqueta.
`test_a_metrica_leva_o_motivo_e_nao_o_tenant` afirma a ausência do UUID na
exposição, e confirmei-a na exposição real (`probe2 §8`). O `degraded_menu` não
loga nada; o `_resumo` do handoff continua sem o texto do cliente.

### M6 — A memória das estruturas novas tem tecto

O `_podar` apaga a chave do tenant quando a fila esvazia
(`degradacao.py:404-410`), e `test_a_janela_nao_cresce_com_um_tenant_por_chave`
mede 50 tenants → 1 depois da janela passar. O `Disjuntor` do LLM tem **uma**
chave (`"llm"`). O `ErroDeLlm.estado_http` é um inteiro por excepção. (Ressalva: a
P2, que é entradas presas e não crescimento ilimitado.)

### M7 — Sem fuga de escopo

`grep -rni "typebot|n8n|dify" services/agr` dá só a lista de **proibidos** do
`egresso.py:134-138` e os ensaios dela, anteriores a este ticket. Nenhum perfil de
Serviços, marcação ou *booking* em `verticais/vendedor/degradado/` nem no
`degradacao.py`. O sub-grafo é nós e arestas do **mesmo** `StateGraph` (ADR-002,
LangGraph), com a razão escrita (dois `build_graph` punham dois esquemas de canais
sobre o mesmo `thread_id`).

### M8 — Postgres ou checkpointer em baixo não degrada, não responde e não conta

`motivo_do_erro` levanta `TypeError` para o que não é `ErroDeLlm`
(`degradacao.py:167-171`), e o `SemDegradacao` recusa pela mesma função — não há
duas cópias. O `classify` apanha `ErroDeLlm` e mais nada (`nos.py:993`); não há
`except Exception` no `degradacao.py`. O `versao_lida` no topo do `ingest` sobe. O
`test_um_erro_da_base_no_turno_nao_degrada_e_nao_envia` mede zero mensagens e
ausência da contagem, com um `BaseEmBaixo` que não é `ErroDeLlm`. **A ressalva é a
C7**, que é indirecta e não desmente esta.

### M9 — O critério 1 é medido a cem, à letra

`test_zero_turnos_sem_resposta_em_cem_execucoes`: `execucoes = 100`, os três erros
por rotação (nenhum fica sem execução), e desliga o disjuntor com a razão escrita
— sem isso, 97 das 100 nunca chegavam ao `except` e o ensaio media o disjuntor em
vez do «sem excepção». A soma final é `assertEqual(enviadas, 100)`.

### M10 — Nenhum caminho de saída do modo degradado passa ao lado do `validate`

O `degraded_menu` devolve `draft.blocos` e **não** `texto` — a aresta 45 leva-o ao
`validate`, e `test_o_no_do_menu_nao_devolve_texto_pronto` afirma a ausência da
chave `texto` (que é o que o `_resposta_estatica` usa para saltar a camada). As
outras saídas do modo vão por `compose → validate`: `confirm_gate`/`create_order`
(C8 confirma o texto rendido), `order_status`, `tools_info`. O ramo `degraded` do
`handoff_prepare` sai pela aresta 37 com `MSG_DEGRADADO`, que não tem dígitos
(M2). Medido no grafo compilado: `citation_retries == 0` e `draft["ok"] is True`
no turno do menu, o que só acontece se o `validate` correu.

### M11 — A janela de 24 h não é contornada por este ticket

O AGR não tem código de janela: `grep -rn "WINDOW_CLOSED" services/agr/src` não
devolve nada, e quem a impõe é o Outbound (KAM-015). O modo degradado **não
acrescenta nenhum chamador novo** de `enfileirar`: a única saída nova é o
`degraded_menu`, que sai pelo `send` com a mesma `idempotency_key = turn_id:seq`.
E não há resposta antiga para reenviar, porque o `draft` é do turno
(`CAMPOS_DO_TURNO`) — `test_o_rascunho_do_turno_degradado_nao_e_reenviado_no_seguinte`
mede duas chaves de idempotência distintas em dois turnos.

### M12 — A recuperação do critério 7 não precisa de código, e é verdade

O `degradado` entra no `CAMPOS_DO_TURNO` e no `estado_inicial` com `None`
(`estado.py:126,242`), pelo que voltar ao modo normal é a **ausência** de estado e
não um caminho de saída que possa falhar. `test_o_turno_seguinte_volta_ao_modo_normal`
mede-o em dois turnos com checkpointer, e o disjuntor fecha ao primeiro sucesso
(contagem de falhas **consecutivas**, `tls/disjuntor.py:145-148`).

### M13 — A contrapressão exige as duas condições

`_contrapressao` (`degradacao.py:261-272`) exige `em_curso >= tecto_por_tenant`
**e** `a_espera >= limiar_de_contrapressao`, e trata o zero como «sem tecto» nas
duas — a mesma leitura do `vaga_de` do `admissao.py`. A propriedade `tectos` nova
devolve o `dataclass` `frozen` **desta** `Admissao` e não relê o ambiente, o que é
a razão certa para ela existir. Os ensaios medem as quatro combinações.

---

## Resumo por critério

| Critério | Estado medido |
|---|---|
A coluna «declarado» é o que a secção de verificação de `d60aae2` escreve; a
coluna «medido» é o que eu medi a correr.

| Critério | Declarado | Medido |
|---|---|---|
| 1 — resposta em ≤ 1 turno, 0 sem resposta em 100 | satisfeito | cumprido com a política concierge desligada (M9); falso com ela ligada, e isso está declarado (P4); em risco pelo C6 |
| 2 — o modo serve menu, lista, estado do pedido, loja, referência, humano | parcial (só a referência e a pesquisa) | **2 das 5 capacidades respondem com a frase errada quando se toca no botão** (C2); a lista de 4 excede o contrato do Outbound (C6) |
| 3 — confirmação degradada cria 1 pedido e cita por *template* e *facts* | **satisfeito** | 1 pedido: cumprido. **Cita zero** *facts* e nenhuma referência (C8) |
| 4 — intenção sem LLM; texto livre devolve o menu | satisfeito | cumprido **dentro** do turno degradado; os identificadores morrem no turno seguinte (C1) |
| 5 — o validador aplica-se também aqui | satisfeito | cumprido (M10) |
| 6 — `degraded_turns` por motivo e tenant; alerta > 5% | parcial, «o alerta mede-se» | métrica por motivo: cumprida. Por tenant: `OBS-I`, parcial e bem declarada. **Alerta: sem consumidor** (C5) |
| 7 — recuperar volta ao modo normal; nada antigo reenviado | parcial (a janela é do KAM-015) | cumprido na parte do AGR (M12, M11) |
| 8 — contrapressão move o tenant para o modo | satisfeito | cumprido (M13) |

**O que eu mudaria antes de fundir**, por ordem: C1 (tirar o `INTENCAO_DA_OPCAO`
do caminho degradado), C2 (o toque no botão de encomenda/pagamento tem de pedir a
referência em vez de responder com a frase do catálogo), C3+C4 (disjuntor por
tenant, ou pelo menos não contar `budget` e `destino_negado` num disjuntor
global), C6 (decidir como é que a lista de quatro atravessa o Outbound), C5 (dar
consumidor ao alerta, ou declarar a caixa vazia em vez de dizer que se mede).
