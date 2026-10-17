# ANÁLISE-23 — KAM-006: consumidores idempotentes, `events_consumed` e DLQ

| Campo | Valor |
|---|---|
| Ticket | KAM-006 — Consumidores idempotentes, `events_consumed` e DLQ |
| Âmbito | Revisão `0005`, `packages/core-ts/src/eventos/` (consumo, trabalho, DLQ, acções, reconciliador, trabalhador BullMQ), `services/worker-canal/src/consumidor.ts`, o espelho em `libs/py-core`, a *suite* `tests_eventos_consumo`, e as alterações ao KAM-005 (`filas_bullmq.ts`, `publicador.ts`) |
| Método | Revisão adversarial **independente**: um subagente recebeu os requisitos (bloco do ticket, `docs/tecnica/06` §6.3–§6.5, ADR-009, ADR-013) e o código, e **nunca as justificações de quem o escreveu**. Mandato: procurar razões para estar errado, com dez perguntas fixas, e dizer explicitamente onde procurou e não encontrou |
| Resultado | 11 achados — 3 críticos, 4 maiores, 4 menores. **10 corrigidos**, 1 registado com declaração |
| Veredicto do revisor | **REPROVADO**, pelo C1 |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. O que a revisão mudou, em três frases

O achado C1 é o que justifica o veredicto: o `once(key, fn)` — a função que
existe para **não repetir** um efeito externo — fazia `BEGIN`/`COMMIT` na mesma
ligação que a transacção do consumo, e o PostgreSQL não encadeia transacções.
O `COMMIT` dele fechava a transacção de fora, confirmando a marca de
`events_consumed` **antes de o efeito existir**; e a documentação deste próprio
ticket mandava chamá-lo exactamente assim.

Os outros dois críticos são da mesma família — um caminho que parecia coberto e
não estava: um erro na leitura do envelope nunca chegava à política, e a ligação
de cada fila ficava memoizada para sempre mesmo depois de morrer. Nenhum dos
três teria sido encontrado por releitura; os três foram encontrados a perguntar
«o que acontece a seguir a isto falhar?».

## 2. Os achados

### C1 — o `once()` confirmava a transacção do consumo — **corrigido**

`packages/core-ts/src/eventos/accoes.ts`. O `comContexto()` fazia `BEGIN`,
`set_config`, o passo, `COMMIT`. Dentro de uma transacção aberta, o `BEGIN` é
um aviso e mais nada, e o `COMMIT` fecha a de fora. A sequência que perde o
efeito para sempre:

1. `consumir()` abre a transacção e escreve a marca em `events_consumed`;
2. o efeito chama `once()`, como o `docs/consumo.md` §8 mandava;
3. o `COMMIT` do `once()` **confirma a marca**;
4. o efeito falha a seguir; o `ROLLBACK` do `consumir()` não tem transacção
   para desfazer;
5. todas as re-entregas lêem «duplicado» e saem. O efeito nunca acontece, não
   há entrada na DLQ, e o reconciliador salta o evento porque `events_consumed`
   tem linha. Num `payment.*`, é cliente que pagou e nunca é confirmado.

**Porque nenhum teste o apanhou:** os dez testes de `once()` corriam com uma
base falsa que regista instruções como cadeias — o teste «cada passo é uma
transacção curta» passaria de igual modo se o `BEGIN` fosse ilegal — e não
existia um único teste que chamasse `once()` de dentro de `consumir()`, que era
o uso primário documentado.

**Correcção.** O `once()` recusa-se, alto, a correr numa ligação com transacção
aberta (`TransaccaoAlheiaError`), detectando-o com
`now() <> statement_timestamp()`. O `docs/consumo.md` §8 foi reescrito: um
efeito externo corre **depois** do `COMMIT`, noutra ligação. Onde esse ponto
fica no laço do consumidor é decisão em aberto (§9, ressalva 7): o esqueleto
não tem efeitos externos. Prova: `eventos.dlq.test.ts`, «recusa-se a correr
dentro da transacção de quem o chama»; acoplamento em
`db/tests/test_consumo_contrato.py`, `TestOnceForaDaTransaccao`.

### C2 — uma falha antes da política nunca abria a DLQ — **corrigido**

`trabalhador_bullmq.ts`. `envelopeDoEvento()` corre antes de `processar()`, e
qualquer erro ali — tenant em falta, evento ausente do arquivo, base em baixo —
subia direito ao BullMQ. O *job* esgotava as seis tentativas e ficava em
`failed` no Redis, **sem linha na DLQ, sem métrica e sem alerta**; e como não
há `events_consumed` nem `events_dlq`, o reconciliador voltava a enfileirá-lo
de cinco em cinco minutos durante as 24 h da janela.

**Correcção.** Cada classe de erro tem resposta: um *job* sem `tenant_id` falha
à primeira (nenhuma retentativa lhe acrescenta um tenant, e sem tenant não há
linha de DLQ possível); um evento que o arquivo não tem é **adiado** — pode ser
cedo, porque o publicador enfileira antes do `COMMIT` que arquiva — e, esgotadas
as tentativas, abre uma entrada com `tipo = evt.ilegivel`, o `event_id`, o
tenant e o motivo. Prova: `db/tests_eventos_consumo/test_consumo.py`,
`TestEnvelopeIlegivel` (fila real), com o `test_o_que_esta_na_dlq_nao_volta` a fechar a outra metade, e
`packages/core-ts/tests/eventos.trabalhador.test.ts`.

### C3 — a ligação de cada fila nunca era invalidada — **corrigido**

`trabalhador_bullmq.ts`. O `pg.Client` não religa: depois de uma queda da base,
toda a consulta devolve «Client has encountered a connection error». Com a
promessa memoizada para sempre, a partição morria até ao reinício — dezasseis
sessões a poderem morrer uma a uma, com o `/healthz` a dizer que está tudo bem.

**Correcção.** `largarLigacao()` esquece a promessa e fecha o cliente em
qualquer erro que não seja de política, e a entrega seguinte abre outra.
**Não tem teste de execução** — simular uma queda de ligação a meio de um *job*
exige derrubar o PostgreSQL com a *suite* a correr, e isso não existe em
nenhuma *suite* do repositório. Está registado aqui e no `docs/consumo.md` §9.

### M1 — o caminho de escrita da DLQ sob RLS não era exercitado — **corrigido**

`db/tests_isolamento/sementes.py`. A receita de `events_dlq` tinha
`escrita_do_papel=False` — que significa «o papel não tem `INSERT`» — quando a
revisão 0005 dá `INSERT` a `kamba_app`. O comentário por cima afirmava que o
X-04 exercitava o `WITH CHECK`; não exercitava. Pior: o `por_tabela()` filtra
por `leitura_do_papel`, pelo que a tabela saía **também** dos testes de escrita
cruzada. A caixa de DoD «Isolamento de tenant — DLQ e consumo respeitam RLS»
estava marcada sobre um caminho sem teste nenhum.

**Correcção.** Ler e escrever passam a ser duas dimensões: `por_tabela_que_escreve()`
e `por_tabela_sem_escrita()` no `ComDoisTenants`, usadas pelos três testes de
escrita. Um `INSERT` não precisa de `SELECT` para ser recusado pela política,
pelo que não havia razão para as juntar.

### M2 — uma entrada resolvida que voltava a falhar desaparecia — **corrigido**

`SQL_PARA_DLQ` tinha `ON CONFLICT (consumer, event_id) DO NOTHING` sobre uma
unicidade do par inteiro. Um evento que falha, é reprocessado, e volta a falhar
colidia com a linha **fechada** e não escrevia nada: zero entradas abertas sobre
um efeito por aplicar, `evt_dlq_open` a zero, e a retenção de 30 dias a apagar a
única evidência. Num `payment.*`, um Sev1 que se apaga a si próprio.

**Correcção, e a que se rejeitou.** A unicidade passa a ser **parcial**
(`events_dlq_aberta_uq`, só sobre as abertas), e o `ON CONFLICT` nomeia o
predicado. Duas falhas na mesma execução continuam a dar uma entrada; um ciclo
novo abre a sua, com a anterior guardada. A alternativa óbvia — reabrir a linha
fechada com um `DO UPDATE` — foi **rejeitada**: obrigava a dar
`UPDATE (estado, …)` a `kamba_app`, e com isso quem consome passava a poder
fechar uma entrada sozinho, desfazendo do lado do código a regra dos dois
aprovadores. Prova: `db/tests/test_dlq_reabertura.py`, oito testes, com os
papéis reais.

O índice parcial trouxe uma consequência que só o gate 8 mostrou, e que custou
**duas** voltas de CI porque a primeira explicação estava errada: a cláusula de
inferência do `ON CONFLICT` — os dois elementos **e** o predicado — são
expressões sobre a tabela, e as três colunas contam como leitura. A primeira
hipótese foi «é só a coluna do predicado», e não chegava. A segunda mediu-se,
contra um PG 18.6 descartável e antes de gastar outra volta:

| Privilégios de `kamba_app` | O `INSERT … ON CONFLICT` |
|---|---|
| `INSERT` | `permission denied for table` |
| `INSERT`, `SELECT (estado)` | `permission denied for table` |
| `INSERT`, `SELECT (consumer, event_id, estado)` | `INSERT 0 1` |
| … e `SELECT id` com as três | `permission denied for table` |

Concederam-se as três, e o `id` continua fechado — que é a propriedade que
importa: a RLS já limita o papel às linhas do seu tenant, e o que uma sequência
revelaria é o volume do vizinho. Não há `UPDATE` nem `DELETE`.

### M3 — o `trabalhador_bullmq.ts` não tinha teste nenhum — **corrigido**

314 linhas, zero testes directos: `envelopeDoEvento()`, `tenantDoJob()`, as duas
classes de erro exportadas e nunca construídas em teste, o `fechar()`. A *suite*
com fila exercitava o ficheiro só pelo caminho feliz e com uma partição de cada
vez.

**Correcção.** `packages/core-ts/tests/eventos.trabalhador.test.ts`, com o que
se testa sem fila: de onde vem o `tenant_id` (quatro casos), a leitura do
envelope (contexto antes da leitura, as duas classes de erro), e a entrada sem
envelope. O que precisa de Redis continua na *suite* com fila, e o que não tem
teste nenhum está dito no C3.

### M4 — a carência só estava provada na direcção negativa — **corrigido**

Todos os testes que provavam reposição corriam com carência **0**; o único que
usava os dez minutos do §6.5 provava que um evento fresco **não** é reposto. Com
o sinal da comparação trocado, ou com o parâmetro ignorado, os dois continuavam
verdes.

**Correcção.** `test_com_a_carencia_do_documento_o_que_passou_dos_dez_minutos_volta`:
recua o `registado_em` do arquivo onze minutos e verifica que, com a carência de
produção, o evento **é** reposto. Fecha a assimetria sem esperar dez minutos.

### m1 — a asserção do contador de efeitos não podia falhar — **corrigido**

O efeito `conta` do `consumidor_runner.ts` usava `consumer:event_id:efeito` como
chave primária: um efeito repetido não escrevia duas linhas, rebentava na
unicidade. `assertEqual(self.efeitos(), 1, "o efeito repetiu-se")` nunca
observaria um 2 — a mensagem mentia sobre o que media. A chave passa a levar um
número de ordem, e duas aplicações deixam duas linhas.

### m2 — `REPETICAO.atraso` ficou morto com uma afirmação ao lado — **corrigido**

Depois de o *job* passar a `backoff: {type:'custom'}`, o valor deixou de ser
lido por código nenhum, e a sua docstring dizia ser «o primeiro degrau da
escada». Ou a afirmação é verdadeira e um teste prende-a, ou é decoração: agora
há o teste.

### m3 — guarda morta no `escadaDoAmbiente()` — **corrigido**

`split` sobre uma cadeia não vazia devolve sempre pelo menos um elemento.

### m4 — invariante nova e não documentada — **corrigido**

`backoff: {type:'custom'}` vale para **todos** os consumidores destas filas: um
*worker* sem `backoffStrategy` obtém atraso indefinido e queima as seis
tentativas num instante. Hoje só existe um `new Worker(` no repositório, pelo
que o risco é futuro — mas o KAM-038 e o KAM-041 herdam-no. Está em
`docs/consumo.md` §8, ponto 4.

## 3. O que a revisão confirmou

Vale registar, porque uma revisão que só lista achados não diz onde esteve:

- a transacção única do `consumir()` (contexto como primeira instrução, alvo
  nomeado no `ON CONFLICT`, `ROLLBACK` com `catch` vazio justificado, `COMMIT` e
  não `ROLLBACK` no caminho do duplicado, `Number.isSafeInteger` no `seq`, o
  `event_id <> $4` no `SQL_ULTIMO_SEQ`);
- **todas as contagens citadas na secção de verificação do bloco**, uma a uma,
  incluindo as 201 mutações aplicáveis e os 377 testes de `libs/py-core`;
- que duas das mutações nomeadas morderiam de facto, verificadas à mão;
- que o critério 5 está honestamente vazio, e que a justificação é verdadeira:
  não há ficheiro de regras nenhum no repositório;
- que os `tests_bd/*.ts` **estão** no `typecheck` (`tsconfig.tests.json`
  inclui-os), ao contrário do que a pergunta do mandato supunha;
- que os documentos (`docs/consumo.md`, `docs/eventos.md`, o bloco e
  `docs/tecnica/06`) estão coerentes entre si nos números e nos nomes.

## 4. O que ficou por rever

O revisor declarou o que não auditou, e fica aqui porque é informação:
`db/dlq.py` e `db/tests/test_dlq.py` (a CLI dos dois aprovadores, 497 + 569
linhas) só pela contagem e pelas consultas; o espelho em Python pela estrutura e
não linha a linha; a revisão `0005` só pelos `GRANT` e pelas funções de
retenção; e `metricas.ts` para além da lista fechada de desfechos. **Nenhuma
*suite* com base de dados ou fila foi corrida pelo revisor** — não há Node nem
`make` no anfitrião, e o Docker é intermitente; o que ele correu foi
`libs/py-core` (377 OK), o `test_consumo_contrato.py` (7 OK, na altura) e
`db/mutacoes.py --aplicaveis` (201/0).

## 5. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: 11 achados da revisão adversarial do KAM-006, 10 corrigidos e 1 (C3) registado sem teste de execução. | Equipa KAMBÁ |
