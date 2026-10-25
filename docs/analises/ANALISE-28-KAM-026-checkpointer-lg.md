# ANÁLISE-28 — KAM-026: o *checkpointer* que a licença obrigou a escrever

| Campo | Valor |
|---|---|
| Ticket | KAM-026 — Checkpointer Postgres (esquema `lg`), `thread_id` e retenção |
| Âmbito | A revisão `0020`, o papel `kamba_agr`, o módulo `kamba_agr/checkpointer.py`, o SQL de `kamba_agr/consultas.py`, a varredura de `retencao.py`, o recorte de `estado.py`, as duas baterias, o fecho de dependências do AGR, a emenda 1.34 do dicionário e o §7-A do `docs/agr.md` |
| Método | Revisão adversarial independente do *diff* `publico/main...HEAD`, por um agente que recebeu o código e os requisitos e **não** as justificações do autor. Oito perguntas dirigidas, com obrigação de responder por extenso também onde não encontrasse nada. A verificação por máquina correu contra um PostgreSQL 18 descartável |
| Resultado | 22 achados — **4 críticos, 7 sérios, 11 menores**. Todos tratados: 20 corrigidos, 2 declarados |
| Veredicto | **REPROVADO à primeira**: dois dos críticos eram reproduzíveis sem base de dados, e um deles já punha uma bateria existente a vermelho |

| Aprovação | Nome | Data |
|---|---|---|
| Engenheiro de Runtime/IA | | |
| Arquitecto de Plataforma | | |

---

## 1. O achado que justifica o veredicto

**A inserção de duas entradas no `ops/secrets-inventory.yaml` partiu a entrada
vizinha.** As duas novas (`db_audit_password`, `db_agr_password`) entraram
**entre** o `obrigatorio_em: []` do `db_identity_password` e a cauda dele. O
resultado, em YAML válido e portanto silencioso à vista:

- o `db_identity_password` ficou sem `consumidores`, `instancias`, `anel`,
  `kid` e `nota` — cinco campos, quatro deles obrigatórios pelo esquema;
- a cauda colou-se ao `db_agr_password`, que passou a ter **duas** chaves
  `consumidores` (a segunda, `[CHR]`, vence por semântica de YAML) e a `nota`
  do papel de identidade, a dizer «quinto papel … criado pelo KAM-008 … o
  módulo de identidade».

O `tools/secrets_inventory` recusa o ficheiro inteiro —
`linha 313: chave repetida no mesmo item (consumidores)` — e a seguir reporta
**0 segredos, cobertura 0/11 (0%)**. A bateria
`tools/secrets_inventory/tests/test_inventario.py` estava **vermelha** no ramo,
e o autor não a tinha corrido: nenhuma das *suites* que ele correu (`tests_agr`,
unidade do AGR, os quatro *lints* documentais) a toca.

Isto não é um defeito de desenho — é um defeito de edição que nenhuma leitura
apanha e que uma máquina apanha em dois segundos. Está aqui como o achado do
veredicto porque é a terceira vez neste epic que uma alteração a um ficheiro de
registo passa sem se correr a bateria desse registo.

## 2. Os outros três críticos

**O encerramento rebentava, e a ligação da tranca não largava.** O `create_app`
declara `ao_encerrar: Callable[[], Awaitable[None]]` e faz `await
ao_encerrar()`; o `TrancaDeConversas.fechar` é `async def`. O
`_fechar_as_tomadas` devolvia uma função **síncrona** que chamava o `fechar()`
sem `await`. Num `SIGTERM`: `lifespan.shutdown.failed`, um `TypeError`, e a
tomada `kamba-agr:tranca` aberta — com as `pg_advisory_lock` de sessão tomadas
até o PostgreSQL notar. É exactamente o modo de falha que o KAM-025 escreveu
em três sítios e que esta função existia para evitar. Nenhum ensaio o via,
porque todos os de arranque substituem o `uvicorn.run` e o `lifespan` nunca
corre.

**Uma excepção envenenava a única ligação, para sempre.** O `_correr_sincrono`
confirmava no fim e não desfazia no erro; a ligação é `autocommit=False` e o
`pg8000` abre transacção antes de cada instrução sem a desfazer. Um
`statement_timeout` ou um reinício do servidor deixava-a em `25P02 current
transaction is aborted`, e a partir daí **todas** as instruções falhavam e
nenhuma chegava ao `commit`. Com uma ligação para o processo inteiro, o
*checkpointer* ficava morto para todas as conversas de todos os *tenants* —
e o processo continuava a aceitar turnos.

**Um cancelamento largava a tranca com a *thread* ainda a usar a ligação.** O
`asyncio.to_thread` não cancela a *thread*: um `CancelledError` no `await`
desenrolava o `async with`, libertava o `asyncio.Lock`, e a corrotina seguinte
usava a mesma tomada em paralelo. É a corrupção de protocolo que o docstring do
módulo diz que a tranca evita — e **foi o único caminho que a revisão encontrou
para o estado de um *tenant* chegar a outro**. O cancelamento é caminho vivo: o
`turno.py` trata-o em dois sítios.

## 3. A afirmação que o código desmentia

O módulo da retenção e o `docs/agr.md` §7-A diziam que a varredura «corre com o
`kamba_batch`». **Corria metade:** a `ligacao` do lote fazia o `SELECT`, e o
apagamento ia pelo `adelete_thread` do *checkpointer*, que corre com o
`kamba_agr`. Duas consequências, e a segunda é a que interessa: o
`GRANT SELECT, DELETE ... TO kamba_batch` da revisão `0020` era privilégio
**morto e nunca exercido**, e o ensaio que parecia prová-lo abria uma ligação
`batch` que não era a que apagava.

## 4. Quatro ensaios que passavam pela razão errada

O ticket tinha-se auto-criticado bem num ponto — a armadilha do `msgpack`, em
que uma busca por texto devolve zero com um telefone lá dentro — e o controlo
positivo que ele acrescentou era bom. **Mas o ensaio negativo continuava
vazio por três razões independentes:** a amostra era fabricada pelo próprio
ensaio (não há «turno normal» nenhum, não há grafo); o varrimento filtrava pelo
`thread_id` que o ensaio acabara de semear, quando o critério diz «nas tabelas
`lg.*`»; e a expressão só apanhava `\+?244\d{9}` — **não a forma local
`9xxxxxxxx`, que é a que um cliente angolano escreve no WhatsApp**.

Os outros três: o do `OBS-I` provava que uma função de dois parâmetros recusa
três argumentos; o da latência afirmava `>= 0` sobre uma diferença de
`monotonic`, que é sempre verdade; e dois do arranque comparavam literais entre
si sem correr nada.

## 5. O que se corrigiu, e como

| Achado | Correcção |
|---|---|
| A1 inventário partido | Entrada reposta, as duas novas completas. 30 entradas válidas, 11/11, 77 ensaios OK |
| A2 encerramento | `_fechar_as_tomadas` devolve uma corrotina; ensaio novo que a liga ao `create_app` real |
| A3 ligação envenenada | `rollback` no erro, com a razão escrita |
| A4 cancelamento | `shield` mais espera pela *thread* antes de largar a tranca |
| B1 escritas perdidas | As escritas de uma tarefa numa transacção só |
| B2 corrida da varredura | O `DELETE` ganhou predicado de tempo: não apaga o que acordou |
| B3 papel errado | A varredura apaga na ligação do lote; o `GRANT` deixa de ser morto |
| B4 ordem do apagamento | Numa transacção, e os checkpoints primeiro |
| B5 contrato do `alist` | `limit=None` é `LIMIT NULL`; `before` lido com tolerância; `config=None` levanta `NotImplementedError` |
| B7 forma do `thread_id` | Validada no `_coordenadas`, não só à entrada |
| D1–D4 | Os quatro ensaios refeitos; o varrimento cobre as tabelas inteiras e as três formas do número |
| C1–C9 | O índice passa a `(thread_id, criado_at)`; 35 e não 36; o papel no §3.2; quatro listas de papéis — e o `kamba_audit` faltava numa delas desde o KAM-012; o `TABELAS_ATE_0019` morto removido; as contagens em prosa; o `pyproject.toml` |

**Dois ficam declarados e não corrigidos.** O `postgres` alcançável por todos os
papéis (`CONNECT` ao `PUBLIC` por omissão) é anterior a este ticket e está na
dívida **95**. E o `SQL_PALAVRA_DA_CONVERSA` do KAM-025 tem a ordem dos
parâmetros invertida no docstring, sem efeito prático — fica para quem lhe
tocar.

## 6. O que a revisão procurou e **não** encontrou

Vale tanto como o resto, e por isso fica escrito. As oito cadeias de SQL foram
conferidas uma a uma — contagem de marcadores contra o tuplo, ordem posicional
contra a ordem das colunas, e as chaves dos dois `ON CONFLICT` contra as duas
`PRIMARY KEY` da revisão: **casam exactamente**. O `upgrade` e o `downgrade`
são inversos, um `upgrade` repetido falha limpo em `42P06` dentro da transacção,
e o `downgrade` com dados apaga tudo, o que está documentado e é inevitável. A
afirmação de que as tabelas do `lg` não precisam de linha no
`ci/rls_exceptions.yaml` foi verificada **no código** do `verificar_rls` e está
correcta. E o `asyncio.Lock` construído fora do *loop* é seguro em 3.12.

## 7. O que isto diz sobre o processo

Duas coisas, e nenhuma é sobre este ticket em particular.

**Correr as baterias dos ficheiros que se toca não é opcional.** O A1 custou
dois segundos de máquina para encontrar e teria custado um PR vermelho no
*gate* 11. O autor correu cinco baterias e nenhuma era a do ficheiro que
partiu.

**Um revisor que recebe as justificações do autor não é independente.** As
oito perguntas deste guião foram dirigidas ao código e não ao raciocínio, e as
três que deram mais achados — «o que acontece a meio», «os testes provam o que
dizem», «afirmações com mais confiança do que a evidência» — são as que não
admitem resposta por leitura.

---

## 8. Controlo de versões

| Versão | Data | Autor | Alterações |
|---|---|---|---|
| 1.0 | 2026-10-25 | KAM-026 | Revisão adversarial independente do *diff*: 22 achados, 4 críticos, 7 sérios, 11 menores. 20 corrigidos, 2 declarados |
