# ANÁLISE 38 — Revisão adversarial do KAM-114 (modo concierge)

| Campo | Valor |
|---|---|
| Ticket | KAM-114 — Modo concierge: a IA rascunha e o humano aprova |
| Data | 2026-10-28 |
| Base | `refs/remotes/publico/main` em `4165d9a` |
| Revisor | Subagente `general-purpose` independente, que recebeu **o diff e os critérios** e **não** o raciocínio do autor |
| Achados | **15** — 13 `CONFIRMADO`, 2 `PLAUSÍVEL` — mais **11** `MORTO` registados com a evidência que os matou |
| Estado | 13 `CONFIRMADO` corrigidos com teste; 1 `PLAUSÍVEL` corrigido por ser barato; 1 `PLAUSÍVEL` devolvido com o que falta para o decidir |

## Porque é que esta análise existe, e o que ela não é

A revisão **procura razões para o resultado estar errado**; não confirma que está
certo. Foi lançada **assim que o diff existiu** e não no fim — é *read-only* e não
depende da *self-validation*, pelo que as duas correram ao mesmo tempo. A árvore
mudou durante a revisão (o revisor di-lo no seu relatório, e nomeia o que lhe
faltava), pelo que **cada `CONFIRMADO` foi verificado outra vez contra a árvore
que vai fundir** — e dois deles mudaram de forma nessa segunda verificação. Ver o
§3.

Os `MORTO` ficam registados por uma razão prática: um achado morto que não se
registe volta na próxima auditoria e paga-se outra vez.

## 1. Os achados que mudaram desenho

### A1 — O `turn_seq` no `estado_inicial`: a conversa fica muda a partir do 2.º turno

**CONFIRMADO**, e é o mais grave. O `turno.py` chama `estado_inicial(primeira)` em
**cada** turno (linha 315) e passa o resultado ao `grafo.ainvoke`, pelo que toda a
chave que aquela função escreve **sobrescreve** a do *checkpoint*. Com o
`"turn_seq": 0` lá, ele valia 1 à entrada de todos os turnos, o
`draft_id = sha256(thread_id:turn_seq)` era o **mesmo** em toda a conversa, e o
rascunho do 2.º turno era engolido pelo `ON CONFLICT (draft_id) DO NOTHING`: o
operador nunca o via, nenhuma mensagem saía, e **não havia erro em sítio nenhum**.

> **O revisor viu o defeito e descreveu-o ao contrário, e isso importa.** O
> relatório dele diz que a `decisao` persistia e que por isso a mensagem **saía
> sem aprovação** do 2.º turno em diante. Medido na árvore que funde, o que
> acontece é o oposto: o `estado_inicial` **repõe** o `concierge` a `None`
> (porque é uma das chaves que ele escreve), pelo que a decisão **não** sobrevive
> — e o que sobra é a conversa **muda**. A direcção do sintoma era outra; o sítio
> e a gravidade eram os que ele disse.
>
> A primeira medição do autor também não o viu, e por outra razão: o `estado_de`
> dos ensaios gera um `contact_id` novo a cada chamada, logo um `thread_id` novo
> — dois «turnos» eram **duas conversas**. Foi preciso fixar o par
> `(tenant, contacto)` para o defeito aparecer.

**A correcção:** a chave sai do `estado_inicial`. Fica fora de **duas** tabelas e
não de uma — o `CAMPOS_DO_TURNO` (que o `reiniciar` devolve) e o `estado_inicial`
—, e o canal do LangGraph guarda o valor do *checkpoint*; o `total=False` do
`ConversaState` e o `estado.get("turn_seq") or 0` tratam a ausência no primeiro
turno. Medido depois: `turn_seq` 1, 2, 3 e três `draft_id` distintos.

**E o `concierge` fica no `estado_inicial`**, porque ali a reposição é a
propriedade que importa: sem ela, a `decisao` de um turno valia como aprovação no
seguinte — que é o defeito que o revisor descreveu, e que esta assimetria impede.

**A regressão tem barreira:** `TestConversaComVariosTurnos`, com três turnos da
**mesma** conversa, e um canário que mede que ela morde (3 dos 4 ensaios falham
com o defeito reposto). Mais duas mutações: `o turn_seq volta ao estado inicial` e
`a decisao passa a sobreviver ao turno`.

### A2 — O critério 5 não estava ligado

**CONFIRMADO.** A consulta que o critério 5 precisa (`SQL_PENDENTES_DO_THREAD`)
existia, estava documentada, estava no `__all__` — e **não tinha um único
consumidor**. O único caminho para `substituido` era a política desligada
(critério 8). Consequência: o dono responde no WhatsApp, o operador aprova o
rascunho dez minutos depois, e o bot fala **por cima do dono**.

**A correcção:** um `Substituidor`, com o gatilho onde ele vive — o
`Palavra.do_humano` do `ExecutorDeTurnos`, que é a leitura do KAM-018 que vê o
`conversations.mode` e o `handoffs` em `waiting` **na mesma instrução**. Corre
**antes** do reencaminhamento ao HND: entre as duas chamadas um operador pode
carregar em «aprovar», e alargar essa janela pelo tempo de uma chamada ao
provedor era alargar a corrida. Passa pelo **mesmo** CAS, pelo que das duas uma
vence. As 100 intercalações do critério estão medidas, com a ordem a alternar e
com a asserção de que **as duas saídas ocorreram** — senão o ensaio media uma
ordem fixa e não uma corrida.

### A3 — O `golden-candidates` devolvia zero linhas, sempre e em silêncio

**CONFIRMADO**, e o revisor mediu-o contra um PostgreSQL 18 descartável. O comando
corria como `kamba_audit`, que é `NOBYPASSRLS`, a consulta não tem predicado de
*tenant* e o módulo nunca fazia `SET app.tenant_id`: a política `tenant_iso`
reduzia a `tenant_id = NULL` e devolvia zero. **Pior, falhava em silêncio** — zero
candidatos é indistinguível de «ainda não houve edições nem rejeições», e é essa a
leitura que quem corre o comando faria.

**A correcção:** `kamba_batch` sob `tenant_guard.tx_batch` com *job* nomeado
(`agr_golden_candidates`), que é o único papel que a `0024` deixa atravessar
*tenants* — e a exportação é, por natureza, cross-*tenant*. **O argumento da
separação que a primeira versão invocava continua de pé, mas estava mal
dirigido:** quem produz as decisões é o `kamba_app`, e o `kamba_batch` não é o
produtor.

### A4 — O gate 3b vermelho: a emenda era condição de merge

**CONFIRMADO.** O bloco do ticket diz por escrito que a emenda ao dicionário é
**condição de merge**, e ela não estava feita: o `canon_lint` saía com 1 e **17
achados** `[fora-do-dicionario]` sobre a `0024`, e cinco comentários do código
novo já citavam um «dicionário §3.34» que não existia.

**A correcção:** a emenda **1.44** (§3.34), com os três nomes a saírem do §3.8 no
mesmo *commit* — o *lint* recusa a redundância. `canon_lint` passa a **exit 0**
(v1.44, 495 entradas). **E havia uma segunda metade que só a prova por mutação
apanhou:** o `test_a_emenda_139_esta_no_controlo_de_versoes` do KAM-032 confronta
o **cabeçalho** do dicionário com o §6, e o cabeçalho ficara em 1.43. A linha de
base da `agr_unit` ficou vermelha, o corredor de mutações recusou-se a correr — «a
cópia sem mutação NÃO corre verde; uma mutação apanhada sobre isto não significa
nada» — e foi assim que apareceu.

### A5 — Sem serviço ligado, a conversa morria em definitivo

**CONFIRMADO.** Com `deps.rascunho is None` e a política activa, o
`draft_prepare` não gravava linha e o `draft_wait` interrompia. O comentário dizia
«continua a não sair mensagem», o que era **meia verdade**. A metade que faltava:
sem linha, a varredura nunca encontra o rascunho (lista a tabela) e o CAS nunca o
casa (responde 404) — o `interrupt` ficava pendente **para sempre**, e a
invariante do §11 proíbe invocar o grafo com *input* novo nesse estado. A conversa
ficava muda **em definitivo**, não por 24 h.

**A correcção:** `ConciergeSemServicoError`. Levanta, o turno falha, a mensagem
fica na fila e o alerta diz que há uma configuração errada — o que o `versao_lida`
do KAM-026 já faz para o estado vindo do futuro. **Nos dois casos não sai
mensagem; o que muda é que um deixa a conversa recuperável.**

### A6 — O sinal do critério 4 não chegava ao operador

**CONFIRMADO.** O critério 4 manda que uma edição com número fora dos *facts* seja
«**sinalizada ao operador** e registada como `edicao_numero_livre`». O registo
fazia-se; a sinalização não — o `livre` entrava no `Command(resume=…)` e morria no
estado do grafo, e a rota devolvia só `{"outcome": …}`. Isto é, **a metade do
critério que este ticket tinha de entregar agora** era a que não estava lá
(«bloquear em vez de sinalizar fica para decisão do Responsável de Produto», logo
*sinalizar* é o âmbito).

**A correcção:** um `ResultadoDaDecisao` com `desfecho` e `numero_livre`, e a rota
devolve `{outcome, numero_livre}`. **E o sinal não se devolve num desfecho que não
decidiu:** no duplo clique, quem decidiu foi o primeiro pedido, e repetir o sinal
ao segundo dizia-lhe que a **sua** edição trazia um número livre.

### A7 — Dois comentários invocavam um ciclo de importação que não existe

**CONFIRMADO**, e o revisor provou-o movendo o *import* para o topo e importando o
grafo. O `_draft_id` do `nos.py` justificava um *import* tardio por um ciclo
`concierge.maquina → validador.veredicto → metricas` — e o **mesmo ficheiro** já
importava o `concierge.maquina` no topo, 1.700 linhas acima. O `MOTIVOS_DO_RASCUNHO`
duplicava literalmente os seis motivos «pela razão do ciclo escrita no
`_draft_id`».

**Porque é que isto importa:** o comentário falso **custava código** — uma lista de
seis *strings* duplicada, com um teste de paridade a sustentá-la, para evitar um
ciclo que não existe. A próxima pessoa a ler aquilo acreditaria e duplicaria a
terceira lista.

**A correcção:** os dois *imports* sobem ao topo, a lista duplicada sai, e o teste
de paridade passa a afirmar `assertIs(nos_mod.MOTIVOS, maquina.MOTIVOS)`. **O
*import* tardio que é legítimo fica:** o do `metricas.py::_valores_derivados`,
dentro do `lru_cache`, onde o ciclo **é** real porque o `veredicto.py` importa o
`metricas` no topo.

### A8 — O `graph_version` era texto livre e saía na exportação

**CONFIRMADO.** O `golden_candidates.py` afirmava «não há classe `texto`, e é a
prova de desenho: esta tabela não tem uma coluna de texto livre». **Tinha uma:** o
`graph_version` era `text` sem `CHECK` de forma — a própria migração o dizia, duas
vezes, porque era onde o canário do X-03 ia — e está em `CLASSES_QUE_SAEM`. A
prova do critério 7 assentava numa classificação à mão de uma coluna que a
migração descrevia como o sítio onde se mete texto arbitrário.

**A correcção:** a `0024` passou a impor SemVer (`^[0-9]+[.][0-9]+[.][0-9]+$`)
naquela coluna, e o canário do X-03 mudou-se para o `turn_id` — que é `text`, só
exige não-vazio, e **nunca sai** (é `identificador` na classificação). Medido
contra a base: `test_um_graph_version_sem_semver_e_recusado`.

## 2. Os restantes `CONFIRMADO`

| # | Achado | Correcção |
|---|---|---|
| A9 | `SQL_CANDIDATOS_AO_GOLDEN` era código morto, duplicado da consulta que de facto corre, já com um alias divergente | A cópia morta saiu do `concierge/consultas.py` |
| A10 | A `PoliticaDeConcierge` era construída e **nunca usada** — uma ponta solta que não dizia a ninguém o que falta ligar | Passou a um `portas_do_concierge` nomeado, com a razão escrita (quem liga o AgentRegistry passa `concierge=` e `rascunho=` ao `build_graph`) e um `log.info` no arranque. O `Substituidor` passou a ser usado **agora** |
| A11 | A cláusula do custo do critério 6 fica por entregar, e isso é **o critério a mudar** — regra de bloqueio | Não se decidiu. A medição está no bloco e no dicionário §3.34, com as três saídas e o credor; **sobe antes do merge** (ver o §4) |
| A12 | O teste dos 1.000 turnos corria em 1.000 *threads* de um turno, sem aprovar nenhum — nunca chegava ao 2.º turno, que é onde A1 vivia. E a suite custava 26 min | `TestConversaComVariosTurnos` (três turnos da mesma conversa) e `TestBarreira` em `unittest.TestCase` com `asyncio.run`: **1.068 testes em 37 s**, com os 1.000 turnos intactos |
| A14 | A receita do X-03 tinha `valor_alteravel="decisao"`, e um `SET decisao` sozinho viola o `decidido_ck` **para qualquer valor** — o ensaio mediria a restrição e não o isolamento. Era `PLAUSÍVEL` (nenhum ensaio bate hoje nesse caso) e **corrigiu-se por ser barato** | Passou a `("motivo", "tom")`, e a razão escrita na receita passou a nomear a restrição certa |
| A15 | A aresta 35 mudou de forma (passou a condicional) e continuava a declarar `fonte="02 §7.3"`, que a descreve como «sempre» — e o teste novo afirmava a `fonte` que divergiu | `FONTE_ALTERADA_PELO_CONCIERGE` («02 §7.3, alterada por KAM-114»), e o teste passou a medir isso. Continua a contar para o `LINHAS_DO_73`: a linha existe no documento, e o que mudou foi a forma e não a autoria |

**Dois pormenores menores**, da mesma família do A12: uma asserção duplicada no
teste dos nós (a nova e a antiga que ficou) e o cabeçalho do `test_vendedor.py` a
dizer «Dez funções puras» quando o `POR_NO` tem doze. Os dois corrigidos.

## 3. O `PLAUSÍVEL` que fica, e o que falta para o decidir

**A13 — a compensação pode desfazer a decisão depois de a mensagem já ter saído.**

Se o `grafo.ainvoke(Command(resume=…))` puder levantar **depois** de o `send` ter
chamado o `enfileirar` do Outbound, então: o CAS gravou `aprovado`, a mensagem
está no Outbound, e o `_reverter` põe `decisao = NULL` — uma linha que afirma
«nunca foi enviada» sobre uma mensagem que o cliente recebeu. A varredura
encontra-a (filtra `decisao IS NULL`) e 24 h depois grava `expirado`.

**O que falta:** saber se o `ainvoke` do LangGraph fixado no `.venv` pode falhar
depois de um nó ter corrido e antes de devolver, com o *checkpointer* real
(`AsyncPostgresSaver`, KAM-026) e não com o `InMemorySaver`. Um ensaio com um
*checkpointer* que levante no `aput` do super-passo do `send` decidia-o.

**Porque não se decide aqui:** a compensação do KAM-034 tem a **mesma** forma,
pelo que isto pode ser risco já aceite na casa — e a diferença é que aqui a
propriedade que ela pode quebrar **é o produto**. Fica como `PLAUSÍVEL` com o
ensaio que falta nomeado, em vez de se escrever um paliativo sobre uma premissa
não medida.

## 4. O que esta revisão **não** resolveu, e sobe

**A cláusula do custo do critério 6.** O revisor classificou-a `CONFIRMADO` e
escreveu que «é o critério de aceitação a mudar, e a regra de bloqueio da casa é
que alterar o critério de um gate é decisão do fundador: entrega-se a medição, não
a implementação».

É exactamente o que está feito: **a medição está entregue e a implementação não**.
As duas razões estão medidas (a `dat.llm_call_log` não tem `turn_id`; o
`kamba_app` não tem `SELECT` nela, por desenho do KAM-030), as três saídas estão
escritas no dicionário §3.34 e no bloco, e **nenhuma se tomou** — porque uma delas
retira uma barreira de privilégio. A caixa fica por marcar e a decisão sobe.

## 5. Os onze `MORTO`

Registados porque um achado morto que não se registe volta na próxima auditoria.
O revisor mediu-os, vários contra um PostgreSQL 18 real:

1. **`GRANT SELECT, INSERT (col, …)` seria erro de sintaxe** — não é; as cinco
   instruções passam, e o privilégio por coluna **morde** (`UPDATE … SET
   thread_id` dá `permission denied`).
2. **A `0024` não compilaria, ou o `downgrade` não reverteria tudo** — correm as
   duas, limpas: 15 instruções no `upgrade`, 5 no `downgrade`, e depois dele não
   sobra relação `draft%`/`v_draft%`, política nem ACL. A ordem está certa (vista
   antes da tabela, sem `CASCADE`), e o `security_invoker` funciona.
3. **O CAS com alias não passaria** — passa, e a `latencia_ms` dá o valor certo.
4. **Os percentis e o `make_interval(mins => %s)` rebentariam** — não.
5. **O `turn_seq` subiria duas vezes numa reentrega** — não: com um `interrupt`
   pendente o LangGraph não reexecuta o `ingest`, e o `ON CONFLICT` fecha o resto.
   Três entregas do mesmo turno: uma linha, uma publicação.
6. **O ciclo novo seria ilimitado** — é limitado por construção, e pelo
   `interrupt()` e não por um contador.
7. **Um *checkpoint* da 1.0.0 (sem `turn_seq`) daria `draft_id` colidente** — não;
   e o *bump* de *minor* está justificado.
8. **O critério 3 estaria por cumprir** — está cumprido **pela posição**, e o
   revisor escreveu «isto está bem feito».
9. **O CAS perderia a corrida, ou um `draft_id` de outro contacto passaria** — nem
   um nem outro; o predicado leva `tenant_id` **e** `thread_id`, e a tranca cobre
   CAS + `Command` + compensação.
10. **A direcção da falha da política estaria errada (*fail-open*)** — está certa:
    a excepção **sobe** e o turno falha sem enviar.
11. **Faltaria a receita de sementeira do gate 6** — não falta (a ressalva sobre o
    `valor_alteravel` é o A14).

## 6. Onde o revisor olhou e não achou nada

Dito porque um relatório que não diz onde não achou nada não deixa saber o que
ficou por cobrir: o **ponto** de intercepção da barreira (as cinco arestas que
entram no `send`, com as duas omissões nos dois sentidos), os domínios disjuntos
das duas vias de decisão, a idempotência do `draft_prepare`, a privacidade das
colunas/métricas/logs (com a única ponta a ser o A8), a RLS e os privilégios da
`0024`, os três índices, e as duas entradas novas no `ESCRITAS_DO_PLANO_DE_CONTROLO`
do `lint_arch`.

## 7. O que o autor mediu e a revisão não pediu

**O `handoff_seq` tem o mesmo defeito do A1.** Está no `estado_inicial` desde o
KAM-031, pelo que dois *handoffs* em dois turnos da mesma conversa derivam o
**mesmo** `handoff_id` e o segundo é engolido pelo `ON CONFLICT` do HND:
**ninguém é chamado**. Medido — duas passagens, `handoff_seq=1` nas duas, um
`handoff_id`, uma linha com contagem 2.

É código fundido e **fora de âmbito**. Fica em `../dividas-documentais.md` (linha
**134**) com o credor (**KAM-031**/**KAM-034**) e com o remédio que o `turn_seq`
usou, e uma nota em `../concierge.md` §7.

## 8. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial. A revisão adversarial do KAM-114: 15 achados (13 `CONFIRMADO`, 2 `PLAUSÍVEL`), 11 `MORTO`, e o que cada um mudou. | Equipa KAMBÁ |
