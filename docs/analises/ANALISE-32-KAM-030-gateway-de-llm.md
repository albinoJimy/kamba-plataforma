# ANÁLISE 32 — revisão adversarial do KAM-030 (*gateway* de LLM)

| Campo | Valor |
|---|---|
| Ticket | KAM-030 — LLM gateway: LiteLLM por digest, chaves virtuais, budgets e `llm_call_log` |
| Diff revisto | `3261eaf` contra `7d849e2` |
| Revisor | subagente independente, com encargo apertado (ficheiros nomeados, 12 perguntas numeradas, proibição de escrever ficheiros e de correr `gate_bd`/`mutacoes`) |
| O que o revisor **não** recebeu | as justificações do autor. O encargo mandava tratar as notas de módulo e a secção «Verificação dos Critérios de Aceitação» como **afirmações**, não como prova |
| Veredicto | **REPROVADO** — 7 *must fix*, 10 *should fix*, 5 *nice to have* |
| Estado | **os 7 *must fix* corrigidos com teste**; 8 dos 10 *should fix* corrigidos; 3 *nice to have* corrigidos; o resto nas dívidas 117–121 |

---

## A frase do revisor que vale mais do que a lista

> «O que mais me preocupa não é nenhum defeito isolado: é que os três mecanismos
> que este ticket entrega como garantias — o *bump* SemVer, a `dat.llm_call_log`
> com uma linha por chamada, e o `cosign verify` — **não podem falhar** nas
> condições em que foram declarados satisfeitos.»

Estava certa nos três, e os três eram defeitos diferentes do mesmo tipo: o
mecanismo existia, a bateria passava, e o que ela media não era o que o critério
pede.

---

## Os sete *must fix*

### 1. O `escrever` apagava a prova do *bump* — o critério 7 não era um *gate*

O `escrever` reescrevia `ci/llm-aliases.lock` com a `versao` **actual** e o
*hash* **novo**. O fluxo que a própria documentação manda seguir — «mude o alias,
corra `escrever`» — deixava o `check` **conforme sem *bump* nenhum**. Medido pelo
revisor: trocar `por_decidir` por `claude-sonnet-5-5`, correr `escrever`, e o
`check` sai 0 com a versão em 1.0.0.

O que o *lint* apanhava era «esqueceu-se de regenerar», que é *staleness* e não
SemVer.

**Corrigido:** o `escrever` **recusa-se** (`BumpEmFalta`, exit 1) quando existe um
*lock* cuja `versao` é igual à dos aliases e cujo *hash* difere. Não precisa do
ramo base: se aquela versão foi fixada com outro conteúdo, o conteúdo mudou
depois. Três baterias novas, com o canário a ser o fluxo exacto que o revisor
mediu.

### 2. A *suite* do `supply_chain` ficou vermelha e o canário do *gate* 11 desligado

A sétima imagem com `cosign: verificar` rompeu três asserções fixas e pôs a linha
de base do canário vermelha — «a cópia sem mutação já tem achados» —, o que
significa que **a prova por mutação de todas as verificações do `supply_chain`
deixou de valer**. O ficheiro de teste não tinha sido actualizado.

E a secção «Estado da prova» dizia `test_cosign.py` **15 ok** e `supply_chain
imagens` **1 achado, é o *gate* a falhar fechado**: as duas frases eram
verdadeiras e juntas escondiam que o módulo estava vermelho.

**Corrigido:** as contagens passam a 7 imagens, 1 a verificar, 13 serviços e 3
destinos; e o `cosign-sem-binario` sai do `executar_todas` por uma lista
**nomeada** (`ACHADOS_DA_MAQUINA`) com a razão escrita — é propriedade da
máquina, não da árvore, e o caminho do *gate* (`_relatar`) continua a vê-lo.

### 3. A saída para `raw.githubusercontent.com` não estava fechada

O `LITELLM_LOCAL_MODEL_COST_MAP` **não existia em ficheiro nenhum**, e o
comentário que afirmava fechá-la estava colado ao `turn_off_message_logging`, que
não tem nada a ver com o mapa de preços. O próprio autor mediu a saída no §5 da
evidência e não a fechou.

**Corrigido:** a variável entra no compose, com a razão e o apontador para a
medição.

### 4. Uma ligação por processo perdia a linha de registo sob carga

O `ClienteDeLlm` guardava **uma** ligação; o `tenant_guard.tx` é exclusivo por
ligação (`LigacaoEmUso`) e o AGR corre um `asyncio.Task` por conversa. Duas
conversas a chamar o modelo ao mesmo tempo: a segunda saía, consumia *tokens*,
transferia dados e **não gravava linha** — só incrementava
`agr_llm_registo_falhou_total`. O critério 5 e o registo de transferência do
ADR-008 falhavam **exactamente sob carga**, e o duplo sequencial da bateria não o
via.

A *docstring* do `ligar_para_llm` argumentava que a ToolLayer abre uma ligação por
invocação — era o desenho certo e não foi seguido.

**Corrigido:** uma ligação **por chamada**, aberta e fechada no `finally`. O
duplo da bateria passou a recusar a segunda transacção como o `tenant_guard`
real, e há um teste com duas *threads* e uma barreira que exige **duas** linhas.

### 5. Um preço expirado perdia a linha e deixava escapar um erro não tipado

O `custo()` **levanta** numa tarifa expirada, e era chamado no caminho de sucesso
**antes** de se gravar a linha — o único ponto desse caminho que levantava, e a
nota do `registo.py` existe precisamente para dizer que ele não pode levantar.
Com o `gemini-3.8-flash` escolhido, a partir de 2027-01-01 cada chamada:
transferia os dados, gravava **zero** linhas, e escapava um `ValueError` que não é
`ErroDeLlm` — turno falhado, *job* de volta à fila, **segunda** transferência e
segundo custo.

**Corrigido:** apanha-se no `_conseguiu` (custo nulo, métrica contada) **e** o
arranque recusa subir com uma tarifa expirada **que um alias use** — não a tabela
toda, que é um catálogo de candidatos e punha o arranque a falhar por um modelo
que ninguém escolheu.

### 6. Dois fornecedores iguais no mesmo alias davam vinte vezes o custo

O `prefixos` do `_quem_servio` é um dicionário indexado pelo prefixo: duas linhas
do mesmo fornecedor colapsavam e ficava a **última**. Com Haiku (`ordem: 1`) e
Sonnet (`ordem: 2`) atrás de `kamba-chat` — um *fallback* de qualidade dentro do
mesmo subprocessador, que nada recusava —, uma chamada servida pelo Haiku era
gravada como Sonnet com `custo_usd = 0.009000` em vez de `0.000450`: **vinte
vezes**, no número exacto em que o critério 5 se apoia.

**Corrigido:** o *lint* recusa `(alias, fornecedor)` repetido, com a razão escrita
e o caminho para quem precisar daquilo (desambiguar por `(prefixo, modelo)`).

### 7. A chave do cosign tinha sido extraída do *bundle* que ela verifica

Numa verificação por chave, a chave é a **raiz de confiança**. Tirada do *bundle*
do digest que se quer verificar, o `cosign verify --key` é tautológico: confirma
que a assinatura é consistente, não **quem** assinou. No dia em que alguém suba o
digest para uma imagem adulterada — o cenário do incidente de 2026-03-24 que
motivou o ADR-005 —, o procedimento escrito mandava repetir a extracção.

**Corrigido, e a correcção descobriu mais:** o projecto **publica** a chave em
`raw.githubusercontent.com/BerriAI/litellm/main/cosign.pub`, e ela é
**diferente** da que o *bundle* da `v1.104.2` traz. Fixou-se a publicada — que é
fora de banda e autoritativa — e a divergência ficou registada: qual delas
assinou esta versão só o `cosign verify` o diz. **A cláusula cosign do critério 1
passou de «pendente do CI» a «não satisfeita»**, que é o que ela é.

---

## Os *should fix* e o que ficou por fazer

| # | Achado | Estado |
|---|---|---|
| 8 | Seis formas de `pip install` que o leitor não apanha | **corrigidas cinco** (`sh -c`, `bash -lc`, forma exec, tab após `RUN`, opção antes de `install`), com baterias. `eval`, `xargs` e o *heredoc* do BuildKit ficam na **dívida 119**, com um teste que mede a lacuna |
| 9 | O `/key/list` não paginava: o 501.º *tenant* invisível | **corrigido** — pagina e **falha fechada** se a lista vier incompleta |
| 10 | `provisionar` é *check-then-act* | **corrigido** — apanha o 400 «already exists» e cai para `actualizar` |
| 11 | A chave virtual não autorizava o grupo de *fallback* | **corrigido** — o `kamba-chat-fallback2` entra no `models`, com teste de paridade contra o gerador. **Mas a medição ponta a ponta continua por fazer**, e é por isso que o critério 6 desceu a parcial |
| 12 | `cache > tokens_in` cortado em silêncio | **corrigido** — métrica `agr_llm_contagem_incoerente_total`, que é o sinal de que a premissa da dívida 116 caiu |
| 13 | Nada liga a versão dos aliases que o AGR lê à que o proxy serve | **dívida 120**, credor KAM-078 |
| 14 | O `llm/precos.yaml` não passava por lint nenhum | **corrigido** — entra no passo `aliases`, com quatro baterias |
| 15 | A imutabilidade não cobria partições futuras | **corrigido, e o revisor estava certo nos dois pontos**: medi contra PostgreSQL 18 e um *trigger* de linha no pai particionado **é aceite e herdado**, e o de `TRUNCATE` no pai **também é aceite** — as duas afirmações da revisão `0023` estavam erradas. Os dois *triggers* passaram para o pai; a bateria que **cimentava** a lacuna passou a medir o contrário. A RLS **não** se herda (medido), e essa metade é a **dívida 121** |
| 16 | O corpo do erro do fornecedor entrava na excepção | **corrigido** — fica o estado e o `error.type`, e só se ele casar a gramática de identificador. Três baterias, com o canário a ser um telefone no `message` |
| 17 | Um papel desconhecido é a única chamada que não grava linha | **declarado** na secção de verificação do bloco, como o revisor sugeriu |
| 18 | `_pedir_http` não apanhava `URLError` | **corrigido** — rede não é desfecho; o `cron` deixa de ler «houve alerta» onde houve rede |
| 19 | «seis» métricas para sete (hoje oito), e a tabela da `0023` ainda dizia «400 mapeado» | **corrigidos** os dois |
| 20 | Cinco nomes sem leitor | **corrigidos** — `FALHAS`, o `import Path`, o `VARIAVEL_DA_PASTA` duplicado e o `ler_aliases` saíram. O ramo `raiz=None` do `comando_para` fica: é o que as baterias usam |
| 21 | A `spec` saía vazia e a mensagem mentia | **corrigido** — a declaração leva o especificador |
| 22 | Arredondamento a seis casas dá zero para ≤ 4 *tokens* | **dívida 118**. É distinguível de «sem preço» (zero contra nulo) e o impacto é de ordem desprezável; fica declarado em vez de resolvido |

---

## O que esta revisão ensina a quem vier depois

**Três lições, e as três são sobre a forma de medir e não sobre o código.**

1. **Um mecanismo que não pode falhar não é um mecanismo.** Os três achados
   centrais (1, 4 e 7) tinham o mesmo formato: havia um *lock*, havia uma linha
   por chamada, havia um `cosign verify` — e nenhum dos três podia falhar nas
   condições em que foi declarado satisfeito. A pergunta que os apanha é «o que
   faria isto **falhar**?», e não «isto passa?».
2. **Um duplo sequencial não mede concorrência, e o AGR é concorrente.** O duplo
   de ligação da primeira versão aceitava duas transacções; o `tenant_guard` real
   não. Um duplo que é mais permissivo do que a coisa real transforma um defeito
   de produção num teste verde.
3. **Uma medição *ad-hoc* contra o componente real não é uma asserção.** As 20
   corridas que mediram o critério 6 foram feitas com `Router(...)` em Python, e
   a secção de verificação escreveu «contra o proxy real» — que é mais forte do
   que a evidência sustenta, e omitia que não havia chave virtual no caminho. O
   critério desceu a parcial por causa disso.

E uma quarta, de ferramenta: **o revisor reviu `3261eaf` enquanto o `HEAD` passou
a `755d1a3`** (um *merge* de `publico/main` feito em paralelo), e disse-o em voz
alta no relatório — o que evitou que eu lesse como achado deste ticket uma
alteração de 29 linhas em `db/tests/test_privilegios.py` que veio de `main`. Quem
lançar uma revisão sobre um ramo que ainda está a mexer dá-lhe o SHA, e não «o
diff».
