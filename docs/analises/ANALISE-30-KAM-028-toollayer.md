# ANÁLISE-30 — KAM-028: a camada que não se consegue importar

| Campo | Valor |
|---|---|
| Ticket | KAM-028 — ToolLayer: contrato, classes `read`/`write`/`money` e auditoria |
| Ramo | `feature/KAM-028-toollayer-contrato-classes-auditoria`, em `8f7163e`, cortado de `publico/main` (`e286e89`) |
| Âmbito | Os oito ficheiros de `services/agr/src/kamba_agr/tls/`, a revisão `0021`, o *lint* `tools/lint_arch/tool_schema.py`, as duas baterias novas (`services/agr/tests/test_tls.py`, `db/tests_agr/test_tool_audit.py`), o fecho da validação (1) no `registry/gates.yaml`, as alterações ao `__main__.py`, `ligacao.py`, `metricas.py`, as 20 mutações, a emenda 1.36 do dicionário, as quatro dívidas novas, o `docs/agr.md` §7-C e a secção «Verificação dos Critérios de Aceitação» do próprio bloco |
| Método | Revisão adversarial independente de `git diff e286e89..8f7163e` (37 ficheiros, ~7,0k linhas), por um agente que recebeu o código e os requisitos e **não** as justificações do autor. Dois instrumentos na mesma passagem (`code-review high` e `ponytail-review`), oito perguntas dirigidas, com obrigação de responder por extenso também onde não encontrasse nada. A secção «Verificação dos Critérios de Aceitação» foi tratada como **afirmação a verificar** e lida só no fim. Medições com `.venv/Scripts/python.exe` no próprio *worktree*: `services/agr/tests` (371 OK), `db/gate_bd.py --suite tests_agr` (105 OK), `lint_arch tool-schema` (conforme), e quatro guiões de medição próprios |
| Resultado | 23 achados — **9 must fix, 10 should fix, 4 nice to have** |
| Veredicto | **REPROVADO.** Três dos oito ficheiros da camada não se conseguem importar sozinhos — `python -c "import kamba_agr.tls.especificacoes"` dá `ImportError` —, e são exactamente os três que o KAM-031 e o KAM-035 têm de importar. O *lint* de CI do critério 3, que o critério manda «falhar o *build*», devolve `conforme` para um modelo que expõe `tenant_id`. E o X-02 do critério 8 mede onze recusas e não onze tools |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Engenheiro de Runtime/IA | | |

---

## 1. O achado que justifica o veredicto

**Três dos oito ficheiros da ToolLayer não são importáveis. Os três são os que
o KAM-031 e o KAM-035 precisam.**

```
$ PYTHONPATH="libs/py-core/src;services/agr/src" .venv/Scripts/python.exe -c "import kamba_agr.tls.especificacoes"
ImportError: cannot import name 'ErroDeBackend' from partially initialized module
'kamba_agr.tls.especificacoes' (most likely due to a circular import)
```

Medido módulo a módulo, com o interpretador do *worktree*:

| Módulo | `python -c "import <módulo>"` |
|---|---|
| `kamba_agr.tls` | OK |
| `kamba_agr.tls.erros` | OK |
| `kamba_agr.tls.contexto` | OK |
| `kamba_agr.tls.disjuntor` | OK |
| `kamba_agr.tls.auditoria` | OK |
| `kamba_agr.tls.camada` | OK |
| **`kamba_agr.tls.especificacoes`** | **`ImportError`** |
| **`kamba_agr.tls.get_store_info`** | **`ImportError`** |
| **`kamba_agr.tls.catalogo`** | **`ImportError`** |

O ciclo é este, e fecha-se dentro deste *diff*:

```
tls.catalogo → tls.get_store_info → tls.especificacoes
             → registo.validar → registo/__init__.py:110  (from ..metricas import …)
             → metricas.py:178  METRICA_TOOL_INVOCACOES: _nomes_de_tool()
             → metricas.py:152  from .tls.catalogo import ESPECIFICACOES_DO_PILOTO   ← parcial
```

O `_VALORES_DA_ETIQUETA` do `metricas.py` chama `_nomes_de_tool()` **ao carregar
o módulo** (linha 178), e essa função importa o catálogo. Quem entrar pelo lado
do catálogo encontra-o a meio.

Funciona hoje por acidente de ordem: o `camada.py` importa o `..metricas`
(linha 61) **antes** da `.especificacoes` (linha 82), e o `__main__.py` importa
`from .metricas import METRICAS` (linha 64) antes do `from .tls.catalogo import
catalogo_do_piloto` (linha 71). Inverter qualquer um dos dois pares derruba o
arranque. Medido nas duas ordens:

```
import kamba_agr.metricas; import kamba_agr.tls.catalogo   → ok
import kamba_agr.tls.catalogo                              → ImportError
```

**O que faz disto o achado do veredicto é o comentário que o nega.** O
`metricas.py`, nas linhas acima de `_nomes_de_tool`, escreve:

> «O `import` é local a este módulo e feito ao carregar, não dentro da função:
> o `tls.catalogo` importa o `tls.especificacoes`, que importa o
> `registo.validar`, e **nenhum dos três importa este ficheiro — não há
> ciclo**.»

A cadeia está certa até ao terceiro elo e pára um passo antes do que importa: o
`registo.validar` não importa o `metricas.py`, mas importar `registo.validar`
executa o `registo/__init__.py`, e **esse** importa-o, na linha 110. É a
primeira coisa que se vê a correr `import kamba_agr.registo` e o `sys.modules`:

```
import kamba_agr.metricas
→ 'kamba_agr.registo' in sys.modules:            True
→ 'kamba_agr.tls.especificacoes' in sys.modules: True
```

E é também o que faz o `test_quem_importa_a_tls_e_uma_lista_fechada_de_dois`
passar sem medir isto: ele pergunta **quem** importa a TLS por expressão
regular, não se o `import` funciona.

**Porque é que isto bloqueia o merge e não espera.** Os *Detalhes Técnicos* do
bloco põem as especificações das tools em `kamba/tls/specs/`, e os dois tickets
que este bloqueia — KAM-031 e KAM-035 — abrem com
`from .especificacoes import EspecificacaoDeTool`. É a primeira linha que cada
um deles escreve, e rebenta. A correcção é de uma linha: trocar o
`_nomes_de_tool()` da linha 178 por uma avaliação tardia (uma `property` no
`MetricasDoAgr`, ou um `functools.cache` lido na primeira contagem), que é o que
o próprio comentário do ficheiro já explica que não quis fazer.

---

## 2. Os outros oito *must fix*

### 2. O *lint* do critério 3 devolve `conforme` para um modelo que expõe `tenant_id`

O critério 3 é o único do bloco que nomeia um *gate*: «lint de CI, **falha o
build**». O `tool_schema.check` reconhece um esquema por
`_e_base_model`, que aceita **só** uma base chamada `BaseModel`:

```python
def _e_base_model(classe: ast.ClassDef) -> bool:
    for base in classe.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel": return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel": return True
    return False
```

Uma subclasse não é reconhecida, e com isso **nenhuma** das duas verificações
corre sobre ela — nem a dos quatro parâmetros proibidos nem a do
`extra="forbid"`. O caso concreto, medido numa árvore de ensaio com a forma de
um serviço:

```python
# services/agr/src/kamba_agr/tls/a_subclasse.py
class ArgumentosBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ArgumentosDeCriarPedido(ArgumentosBase):
    cart_id: str
    tenant_id: str
    seller: str
```

```
$ cd tools && ../.venv/Scripts/python.exe -m lint_arch --root <arvore> tool-schema
lint_arch: esquemas de tool: conforme
exit=0
```

Um modelo de argumentos com `tenant_id` **e** `seller` passa o *gate*. E um
modelo base com configuração partilhada é precisamente a forma que cinco tools
do Vendedor vão tomar.

A mesma árvore mostra o segundo buraco, que não precisa de subclasse nenhuma:
um esquema de tool **fora** de um directório `tls/` não é varrido de todo —
`services/agr/src/kamba_agr/vendedor/tools.py` com `tenant_id: str` dá
`conforme`. A convenção «um `BaseModel` dentro de `tls/`» está escrita na
*docstring* como deliberada, e é defensável; o que não é defensável é o critério
estar marcado `[x]` com a palavra «*build*» quando o *build* não morde nos dois
sítios onde o código vai nascer.

**Isto não é apanhado pelos seis canários do `test_tool_schema.py`**, porque os
seis declaram as classes a herdar de `BaseModel` directamente. O que a camada
ainda apanha é a metade de execução (`_validar_ligada` lê o `model_fields`, que
inclui os herdados, e recusa no arranque) — mas o critério fala do *lint*, e o
*lint* é a verificação que chega antes de alguém correr.

### 3. Um `asyncio.Lock` para todo o processo: dez *tenants* levam dez vezes o tempo de um

O `invoke` toma `self._exclusiva` e **só o larga no fim do pipeline inteiro** —
entitlement, chamada ao backend, auditoria —, sobre uma única
`self._ligacao`. A camada é uma instância por processo, por decisão escrita no
`__main__.py`. Medido com um executor que demora 200 ms, dez invocações de dez
*tenants* diferentes em `asyncio.gather`:

```
10 invocacoes de 10 tenants diferentes
backend: 200 ms cada
ideal (em paralelo): ~0.20 s
medido:              2.02 s
factor de serializacao: 10.1x
```

Serialização perfeita. Com `write`/`money` e o tecto de 8 s, uma cobrança lenta
de um *tenant* põe **todas** as conversas de **todos** os *tenants* do processo
à espera, uma a uma. O `admissao.py` tem um tecto de concorrência de 3 por
*tenant*, e o `turno.py` corre um dreno por conversa com
`asyncio.create_task` — ou seja, há concorrência real a chegar a este trinco.

A regra está escrita neste repositório, no `trancas.py` do KAM-025:

> «**E a espera não acontece dentro desse `asyncio.Lock`.** A primeira versão
> […] deixava a *thread* presa e, com ela, o `asyncio.Lock` da única ligação do
> processo. […] toma o `asyncio.Lock`, faz **uma** instrução e larga-o; entre
> tentativas espera-se fora.»

E tem teste com nome próprio — `test_duas_conversas_diferentes_nao_se_travam`,
que corre verde na `tests_agr`. A ToolLayer não tem o equivalente: nenhuma das
86 baterias de `test_tls.py` nem das 74 de `test_tool_audit.py` mede
concorrência. A pergunta não foi feita, e a resposta é a que o KAM-025 pagou.

A correcção mínima não é um *pool*: é largar o trinco em volta de cada ida à
base em vez de em volta do pipeline, e tirar a chamada ao backend de dentro dele
— para os backends `com`, `pay` e `idx` ela não toca na ligação, como o próprio
`Pedido` diz (`ligacao=… if backend == "plataforma" else None`).

### 4. Nenhum tecto de tempo é imposto pela camada — nem para `read`

O `timeout_de(klass)` calcula o número do §6.5 e põe-no no `Pedido.timeout_ms`.
Depois disso, o `chamar_backend` faz `especificacao.executor(pedido)` — uma
chamada síncrona, sem `asyncio.wait_for`, sem alarme, sem nada. O caso concreto,
com um executor `read` de 5 s contra um tecto de 2 s:

```
backend: 5000 ms
medido:  5.01 s
resultado: ok=True   (nenhum UPSTREAM_TIMEOUT)
```

A secção de verificação põe o critério 7 em `parcial` e nomeia a falta como
sendo dos executores `write`/`money` do KAM-031/KAM-035. A medição diz outra
coisa: **nenhuma** classe tem tecto imposto pela camada. O único tecto real é o
`SET LOCAL statement_timeout` que o `get_store_info` escreve, e esse é do
executor e não do pipeline — para o backend `plataforma` e mais nenhum.

E junto com o achado 3 isto deixa de ser um atraso e passa a ser indisponibilidade:
um executor HTTP sem tecto próprio que fique pendurado prende o `asyncio.Lock`
**para sempre**, e com ele toda a leitura e escrita de todos os agentes do
processo. Não há caminho de recuperação; só reiniciar o serviço.

A correcção mínima é uma linha no `invoke`: `asyncio.wait_for(…,
timeout=timeout_ms/1000)` em volta do `to_thread`, com o tecto da classe que a
camada já calcula. Isso transforma o número que o critério 7 pede de valor
passado em valor imposto, e fecha metade do crédito que a secção de verificação
atribui ao KAM-031.

### 5. Os **nomes** dos argumentos entram em claro na `tool_audit`

O critério 5 diz que a linha «não contém texto de mensagem nem telefone, só
`args_hash`, `args_redacted`, `fact_ids`». A `redigir` protege os **valores** e
copia as **chaves**:

```python
return {nome: type(valor).__name__ for nome, valor in sorted(args.items())}
```

As chaves do `args_crus` são produzidas pelo modelo de linguagem a partir da
mensagem do cliente, e a linha é escrita **com os argumentos crus**
(`args=inv.args_crus` no `registar_se_falta`), inclusive no caminho em que o
`extra="forbid"` as recusou. O caso concreto, com a função real:

```
$ .venv/Scripts/python.exe -c "...auditoria.redigir({'query':'sapatos','contacto 999123456789':'o Joao Mateus pediu'})"
args_redacted = {"contacto 999123456789": "str", "query": "str"}
```

Uma invocação de `search_catalog` cujo argumento inventado se chame
`999123456789` devolve `VALIDATION_ERROR` **e** escreve esse telefone na
`platform.tool_audit`, coluna `args_redacted`, numa tabela *append-only* de onde
nunca sai.

**O que fecha o caso é que o próprio ticket prova este caminho e chama-lhe
legítimo.** O controlo do varrimento de privacidade
(`test_o_varrimento_procura_nos_dados_e_nao_no_nome_das_colunas`) semeia o
canário assim:

```python
self.invocar("criar_pedido", {"cart_id": "c-1", self.CANARIO_TEXTO: ""})
...
self.assertEqual(self._ocorrencias(self.CANARIO_TEXTO), 1)
```

— e a *docstring* desse teste diz «pelo caminho legítimo, o `args_redacted`, que
guarda nomes de argumento». O teste que mede o critério
(`test_a_linha_nao_guarda_o_texto_nem_o_telefone_dos_argumentos`) põe os
canários nos **valores**. Os dois testes, lado a lado no mesmo ficheiro, provam
que o critério passa porque o canário está no sítio protegido e que o sítio
desprotegido existe. É a mesma figura do KAM-026 que a *docstring* do
`auditoria.py` cita — um varrimento a procurar no sítio certo com a semente no
sítio errado.

A correcção é pequena e não tem alternativa barata: redigir também a chave —
`{"<n>": tipo}` por posição, ou `sha256` do nome, ou recusar no passo 3 qualquer
chave que não case `^[a-z][a-z0-9_]{0,62}$` **antes** de montar a linha. A
última é a melhor, porque um nome de argumento fora dessa gramática não é um
nome de argumento de nenhuma tool do catálogo.

### 6. O passo 2 implementa um terço do que o §6.1 lhe manda fazer

O §6.1 passo 2 é «entitlement activo **e limites do TEN** (`msgs_ai_mes`,
`valor_max_pedido_minor`)», e o critério 2 do bloco repete-o. O
`verificar_entitlement` chama o `hook_de_tool` sem `chave` e sem `quantidade`:

```python
erro = hook_de_tool(_ClienteDeCursor(cursor), inv.ctx, modulo=inv.ctx.vertical,
                    idempotency_key=inv.idempotency_key,
                    tecto_chave=chave, tecto_valor=valor)
```

O `hook_de_tool` do KAM-009 — código que este *diff* não toca — faz três coisas
por esta ordem, e a terceira é guardada por uma saída antecipada:

```python
if chave is None:
    return None
...
consumo = consume_limit(...)
```

Com `chave=None` em **todas** as invocações, o `consume_limit` nunca corre. O
`msgs_ai_mes` nunca é decrementado por tool nenhuma, e o `invoke` não tem
parâmetro por onde o grafo possa passar uma chave de balde — o único que existe
é o `tecto`, que é o passo 2b (o tecto por pedido) e não o consumo.

E o `tecto` que existe não tem chamador nenhum:

```
$ grep -rn "tecto=" services/ db/ --include=*.py | grep -v tectos
services/agr/src/kamba_agr/tls/camada.py:525:            tecto=tecto,
```

Uma única ocorrência, que é a camada a passar o parâmetro a si mesma. Zero
testes, zero chamadores: o `valor_max_pedido_minor` que o §6.1 nomeia pelo nome
nunca foi exercido por este ticket. A combinação é o pior dos casos — metade do
passo 2 não existe, a outra metade existe e nunca correu, e nenhuma das duas
tem credor nomeado em sítio nenhum (nem nas dívidas 101–104, nem na secção de
verificação, nem na emenda 1.36). O critério 2 está marcado `[x]`.

### 7. O X-02 mede onze recusas, e não onze tools

O `test_x02_cada_tool_com_estado_de_a_e_referencia_a_b_da_zero_canarios` percorre
as onze tools passando sempre os mesmos argumentos:

```python
for nome in sorted(self.catalogo().nomes()):
    for referencia in referencias_de_b:
        resultado = self.invocar(nome, {"cart_id": referencia, "nota": referencia}, ...)
```

Medido tool a tool, com o catálogo real:

```
  book_slot            declarada  -> recusa no passo 1, backend nao corre
  cancel_booking       declarada  -> recusa no passo 1, backend nao corre
  criar_pedido         declarada  -> recusa no passo 1, backend nao corre
  get_availability     declarada  -> recusa no passo 1, backend nao corre
  get_order_status     declarada  -> recusa no passo 1, backend nao corre
  get_price_stock      declarada  -> recusa no passo 1, backend nao corre
  get_store_info       LIGADA     -> recusa no passo 3 (ValidationError), backend NAO corre
      campos do modelo: []
  list_services        declarada  -> recusa no passo 1, backend nao corre
  propose_cart         declarada  -> recusa no passo 1, backend nao corre
  reschedule_booking   declarada  -> recusa no passo 1, backend nao corre
  search_catalog       declarada  -> recusa no passo 1, backend nao corre
```

(Na bateria real, duas destas estão substituídas por especificações de ensaio;
a `criar_pedido` de ensaio corre, e é a **única** que chega ao backend.)

São **dez** das onze que nunca chegam ao passo 6, e não nove como a secção de
verificação escreve — porque a única tool ligada do catálogo real, a
`get_store_info`, tem modelo **sem campos nenhuns** e `extra="forbid"`: os
argumentos que o laço lhe passa são, para ela, dois argumentos a mais. Recusa no
passo 3.

O oráculo é `assertNotIn(canario, f"{resultado.data}{resultado.error}")`, e num
`ToolResult` de recusa o `data` é `{}` e o `detalhe` do erro só tem nomes de
tool e de campo. **A asserção não pode falhar.** O teste passava com a política
RLS apagada, com o `WHERE id = %s` do `get_store_info` apagado, e com o
`tenant_guard.tx` substituído por uma transacção sem contexto — porque para dez
das onze tools nada disso é alcançado.

A secção de verificação diz que «o X-02 é hoje mais barato do que vai ser», o
que é honesto quanto às declaradas, e não diz que a única tool real também não
entra. A correcção é dar a cada tool os **seus** argumentos (um `dict` por nome,
vazio para a `get_store_info`); a asserção sobre o canário fica igual e passa a
medir alguma coisa.

Vale registar, a favor do autor, que a propriedade de isolamento **está** medida
noutro teste — `test_a_get_store_info_com_o_contexto_de_a_nunca_devolve_a_loja_de_b`,
com o canário semeado na `tenants` de B, e esse corre o caminho todo. O defeito
é o X-02, que é o que o critério 8 nomeia.

### 8. A linha de arranque que diz o estado da camada é recusada pelo *logger* da casa

O `__main__.py` escreve, depois de construir a camada:

```python
log.info(outcome="toollayer_pronta",
         error_code=f"ligadas_{len(catalogo.ligadas())}_de_{len(catalogo.nomes())}"
                    f"_read_{tools.timeout_de('read')}ms")
```

O valor é `ligadas_1_de_11_read_2000ms`, e a *allowlist* de
`docs/tecnica/08` §7.3 exige, por segmento, `[a-z]+[0-9]{0,3}` ou `[0-9]{1,6}`.
O segmento `2000ms` — dígitos seguidos de letras — não casa nenhum dos dois.
Medido com o objecto real:

```
ESTRITO levantou: CampoRejeitado -> o logger recusou 1 elemento(s): valor_invalido (error_code)
{"ts":"...","level":"info","svc":"agr","outcome":"toollayer_pronta"}
contadores: {'log_field_rejected_total:valor_invalido': 1}
```

Em execução normal, a linha sai **sem** o campo: o único sítio onde um painel
podia ler quantas tools estão ligadas e com que tecto não existe, e cada
arranque incrementa `log_field_rejected_total`. Em modo estrito
(`KAMBA_LOG_ESTRITO=1`) o `Logger.registar` reemite `CampoRejeitado` — é a única
excepção que ele não engole — e a chamada no `main()` não está dentro de
`try`: o processo morre no arranque.

**O que esconde isto é a bateria.** Os três `_correr` de `test_arranque.py`
fazem `os.environ.pop("KAMBA_LOG_ESTRITO", None)` antes de chamar o `main()`, e
nenhum dos testes novos olha para a linha do caminho feliz — só o
`test_sem_auditoria_de_tools_o_agr_nao_arranca` lê um `error_code`, e esse é o
do `log.excepcao`, que o `codigo_com_classe` compõe bem. A caixa do DoD
«Privacidade e custo: métricas de latência e erro por tool» está marcada, e
metade da observabilidade que ela cita vai para o chão em silêncio.

### 9. O `Fact` entregue não serve o KAM-032, que é um dos tickets bloqueados

Os *Detalhes Técnicos* do KAM-032 escrevem, por extenso, qual é a sua única
dependência deste ticket:

> «dependência apenas da interface `Fact(kind, value_kz|datetime, sku,
> fact_id, retrieved_at)` de KAM-028»

E os critérios dele precisam de dois `kind` que o §6.2 não tem: «nomes
resolvidos a `sku` via *facts* `name`» e «percentagem sem *fact* `discount`
falha». O que foi entregue, medido:

```
KINDS = ('price', 'stock', 'total', 'datetime')
campos do Fact = ['fact_id', 'kind', 'value', 'retrieved_at']
name     -> ValueError 'name' nao e um `kind` do `docs/tecnica/02` §6.2
discount -> ValueError 'discount' nao e um `kind` do `docs/tecnica/02` §6.2
sku      -> TypeError Fact.__init__() got an unexpected keyword argument 'sku'
```

O `Fact` é `frozen=True, slots=True`, o `KINDS` é lista fechada que **levanta**,
e a emenda 1.36 acabou de escrever as duas coisas no dicionário canónico como
canon («Lista **fechada**, os quatro que o §6.2 nomeia»). O vínculo
`sku↔preço`, que é o mecanismo central do KAM-032 e a resposta ao ponto cego
«produto errado com preço certo», não tem onde viver.

O KAM-032 não fica impossível — fica obrigado a emendar o dicionário e a mudar
uma `dataclass` congelada que outro ticket canonizou. Isso é exactamente a
classe de divergência que as dívidas 102, 103 e 104 registam (uma coluna que o
§6.2 nomeia e não existe, um botão que cita um argumento que a tool não tem, uma
assinatura sem a lista que o passo 1 confronta), e esta — a única que quebra um
ticket bloqueado — não foi registada. A correcção barata é a dívida com credor
KAM-032; a honesta é acrescentar o `sku` opcional e os dois `kind` agora, porque
o custo de os acrescentar hoje é duas linhas e o de os acrescentar depois é uma
emenda ao canon.

---

## 3. *Should fix*

| # | Achado | Caso concreto |
|---|---|---|
| 10 | **O fecho da validação `tools` é honesto numa metade e vazio na outra.** A validação (1) exige duas coisas: que a tool exista no catálogo **e** que não exponha parâmetro proibido no esquema visível ao modelo. A primeira passou a morder de verdade, e há teste a prová-lo (`test_com_o_catalogo_ligado_a_validacao_das_tools_morde`, com um catálogo sem `search_catalog`). A segunda é **vazia para dez das onze**: `parametros_visiveis()` devolve `frozenset()` para uma entrada `declarada`, e `frozenset() & PARAMETROS_PROIBIDOS` é sempre vazio. O `registry/gates.yaml`, o `docs/agr.md` §7-B e a secção de verificação dizem só «a validação corre em `bloqueio`» e «a validação **morde**» | `Catalogo(ESPECIFICACOES_DO_PILOTO).parametros_visiveis("criar_pedido")` → `frozenset()`. Não há teste possível da metade dos parâmetros antes do KAM-031, e é isso que devia estar escrito onde o `credor` estava: um `aviso` fechado em metade não é um `aviso` fechado. A *docstring* da `especificacoes.py` diz-lhe a verdade («vazio porque nada está exposto»); os três sítios que um revisor lê primeiro não |
| 11 | **«Um `fact_id` é opaco» não é imposto por nada.** O autor encontrou uma fuga real no seu próprio executor de ensaio (`fact_id=f"f-{cart_id}"` punha o argumento do cliente na coluna `fact_ids`) e fechou-a com uma regra em prosa. Não há `CHECK` sobre os elementos de `fact_ids` — só o `array_position(fact_ids, NULL) IS NULL` —, o `Fact.__post_init__` só exige `fact_id` não vazio, e não há teste que recuse um `fact_id` derivado de argumento | `Fact(fact_id="f-999123456789", kind="total", value=1, retrieved_at="x")` constrói-se, e a linha escreve-se. Os dois tickets que vão cunhar `fact_id` a sério são o KAM-031 e o KAM-032, e o que os impede de repetir a fuga é um comentário num ficheiro de teste. Um `CHECK` com a gramática que a tabela já usa para `tool` fecha-o na base |
| 12 | **A janela do passo 7 numa tool `money` não tem rede, e perde a métrica do erro.** Se o `auditoria.escrever` levantar depois de o backend ter corrido, a excepção sobe, o turno falha, o *job* volta à fila, e a repetição corre o efeito outra vez — a idempotência que o fecharia é do KAM-029. Está assumido na *docstring*. O que não está assumido é que, nesse caminho, o `_contar` nunca corre (o `finally` levanta no `registar_se_falta`, que vem antes) | `test_uma_auditoria_que_falha_levanta_e_nao_devolve_ok` prova a subida com o executor já corrido. E no caminho em que o pipeline levanta **antes** do desfecho, o `registar_se_falta` escreve uma linha `status='erro'`/`UPSTREAM_DOWN` e o `_contar` sai em `if resultado is None`: o `agr_tool_erros_total` não conta uma invocação que a `tool_audit` registou como erro. Para uma classe `money` a sequência «efeito feito, registo falhado, alerta não contado» é a que menos se quer |
| 13 | **Um erro de negócio apaga o estado do disjuntor em vez de o deixar quieto.** O `chamar_backend` chama `registar_sucesso(backend)` num `ErroDeBackend`, e o `registar_sucesso` faz `self._por_backend.pop(backend, None)`. A razão escrita é boa — um `NOT_FOUND` é o backend a responder —, mas a consequência é mais forte do que «não conta» | Um backend a alternar `OUT_OF_STOCK` e `TimeoutError` nunca abre o disjuntor, com qualquer valor de `KAMBA_TLS_DISJUNTOR_FALHAS`: cada resposta de negócio põe o contador a zero. O `test_um_erro_de_negocio_nao_conta_para_o_disjuntor` mede que não **incrementa**; nenhum mede que não **apaga**. A correcção é não tocar no estado num `ErroDeBackend` |
| 14 | **A tentativa de meio-aberto não tem prazo.** O `permite` põe `a_experimentar = True` e deixa `aberto_ate` no passado. Se nem o `registar_sucesso` nem o `registar_falha` correrem, o `permite` devolve `False` para sempre | O `chamar_backend` apanha `Exception`; uma `BaseException` — `asyncio.CancelledError` no encerramento, `KeyboardInterrupt` — passa ao lado das duas chamadas, e aquele backend fica em disjuntor permanente até o processo reiniciar. Uma linha: guardar o instante da tentativa e deixá-la caducar com a pausa |
| 15 | **A metade «escrita fora da TLS» do *lint* é aplicada linha a linha, e o padrão atravessa espaço em branco.** O `ESCRITA_NO_PLATFORM` é `INSERT\s+INTO\s+platform\.`, e o `check` percorre `fonte.splitlines()` | Uma constante com `INSERT INTO` numa linha e `platform.conversations` na seguinte — a forma que o `consultas.py` deste repositório usa para SQL de várias linhas — é invisível. A segunda metade do `docs/tecnica/08` §3.2 passa a não verificar nada nesse caso. Correcção: procurar na fonte inteira e calcular o número de linha pelo *offset* |
| 16 | **O fecho do *gate* transformou uma divergência de prosa numa recusa de arranque, e não a registou.** O catálogo é lista fechada de onze nomes, a validação (1) está em `bloqueio`, e o nome canónico da tool de pesquisa é `search_catalog` (§6.2, `registry/vendedor.yaml`, dicionário §3.26). O `docs/tecnica/05` §6.3, o EPIC-04, o EPIC-06 e os blocos do KAM-061 e do KAM-032 escrevem `search_products` | O KAM-061 — que este ticket bloqueia — diz «o *registo* da tool na ToolLayer segue o contrato de KAM-028» e chama-lhe `search_products`. No dia em que o `registry/vendedor.yaml` tiver esse nome, o arranque sai com código 5 a dizer «a tool `search_products` não existe no catálogo». `grep -n "search_products" docs/dividas-documentais.md` dá zero. É a mesma classe das dívidas 102–104 e devia ter entrado com elas, com credor KAM-061 |
| 17 | **A quarta tomada não se fecha.** O `ligacao.py` passou de três ligações para quatro, e o `ao_encerrar=_fechar_as_tomadas(trancas, checkpointer)` do `__main__.py` continua a fechar duas. O `ToolLayer` não expõe `close()`, e o comentário acima do encerramento continua a dizer «as três tomadas» | Inócuo hoje (nada invoca a camada, o `/internal/turn` responde 503). A partir do KAM-031, cada `SIGTERM` deixa uma sessão `kamba-agr:tools` pendurada no PostgreSQL até o `tcp_keepalive` a cortar. A `TrancaDeConversas` já tem o `fechar()` que serve de modelo |
| 18 | **O `metricas.py` afirma que não há ciclo, e há.** É o comentário citado no §1. Também: o `Disjuntor.aberto()` diz na *docstring* «Para o log e para os testes», e `grep` por `.aberto(` dá três ocorrências, todas em `test_tls.py` — nada o escreve em log nenhum | Uma *docstring* que nomeia um consumidor que não existe é a forma mais barata de um achado se esconder: foi o que fez o ciclo do achado 1 passar por três revisões de ficheiro |
| 19 | **Duas contagens em prosa estão erradas, e o *gate* que as apanharia não corre aqui.** O comentário do `db/mutacoes.py` diz «Dezenove mutacoes» e são **vinte** (medido: `len([m for m in MUTACOES if m[0].startswith('tls:')]) == 20`). O cabeçalho «As duas que nao sao de logica, e morrem contra a base» cobre duas mutações, e só uma corre na `tests_agr` (medido: `Counter({'agr_unit': 17, 'lint_tool_schema': 2, 'tests_agr': 1})`) — a da ordenação do `sha256` está em `agr_unit`. E o `registo/validar.py`, linhas 7 e 15, continua a dizer «`tools` … **por ligar** (KAM-028)» e «As **três** da coluna da direita», enquanto o `gates.yaml`, o `docs/agr.md`, o `test_registo.py` e o `test_arranque.py` foram todos corrigidos para duas | O ficheiro que **implementa** a validação é o único que ficou a dizer que ela não corre, e é o primeiro que um executor do KAM-031 abre. A secção de verificação diz que «o `lint_contagens` não correu: não corre de dentro de um *worktree* (defeito dele, dono KAM-158)» e que se confia no CI — mas o `lint_contagens` lê prosa de documentos, não comentários de código, pelo que estes três não são apanhados por ele em CI nenhum |

---

## 4. *Nice to have* — **para não corrigir agora**

| # | Achado | Natureza |
|---|---|---|
| 20 | `Invocacao.passos_corridos` é escrito e nunca lido: o campo (linha 177) e o `append` (linha 531) são as duas únicas ocorrências em todo o repositório. Os testes por passo usam a lista `corridos` dos espiões, não esta. Três linhas a menos | eliminação |
| 21 | O `passo_7_auditoria` e o `inv.registada` existem para que a ordem do §6.1 se leia no `PASSOS`: o `finally` do `_correr` já escreve a linha em todos os casos, incluindo o caminho feliz. É um passo que não recusa nada, mais uma marca para o impedir de escrever duas vezes, para tornar afirmável uma ordem que a cobertura não precisa. Defensável — o critério 1 pede a ordem — e é o sítio onde a indirecção menos se paga | simplificação |
| 22 | O `ToolLayer.__init__` recebe `passos` e `relogio` só para os testes (`espioes_a_partir_de`, relógio falso). Consistente com a casa, e são dois parâmetros que nenhum chamador de produção passa | yagni |
| 23 | O `_latencia_de(inv)` é calculado duas vezes por invocação — uma no `registar_se_falta`, outra no `_contar` do `finally` —, pelo que a `tool_audit` e o `agr_tool_latency_ms` podem divergir em alguns microssegundos. Irrelevante na prática; o número da tabela é o certo | simplificação |

---

## 5. As oito perguntas, respondidas por extenso

**1. Que critério pode estar satisfeito pela razão errada?**

Quatro, e por quatro mecanismos diferentes.

O **critério 3** é o mais claro: o *lint* é um *gate* e não morde numa subclasse
nem fora de `tls/` (achado 2). Os seis canários do `test_tool_schema.py` provam
que o `check` não devolve sempre `[]` — o que era a armadilha óbvia — e nenhum
deles testa a única forma que o KAM-031 vai usar.

O **critério 5** passa porque o canário está nos valores e a fuga está nas
chaves (achado 5), e o controlo que o autor escreveu para não repetir o KAM-026
é ele próprio a demonstração da fuga. Vale dizer o que está bem: o varrimento é
`to_jsonb(tool_audit)::text LIKE %canario%` — a linha inteira, não uma lista de
colunas à mão — e tem controlo positivo. É o varrimento certo; o problema é a
semente.

O **critério 8** (X-02) passa com dez das onze tools a recusar antes de haver
alguma coisa para vazar (achado 7), com um oráculo que não pode falhar.

O **critério 2** passa na metade que o teste mede (`ENTITLEMENT_DENIED`,
`TOOL_NOT_ALLOWED`, `VALIDATION_ERROR`, e dois deles contra a base a sério, o
que é mais do que o critério pedia) e a metade «limites do TEN» do §6.1 não
existe (achado 6).

Pergunta ao contrário — *o que faria o teste passar com o código apagado?* — o
que **resiste** é a maior parte: o `test_uma_recusa_tambem_deixa_linha` morre se
o `registar_se_falta` sair do `finally`; o
`test_o_papel_da_aplicacao_nao_consegue_update_nem_delete` morre se o `REVOKE`
sair; o `test_nem_o_dono_das_tabelas_consegue` morre se o *trigger* sair; o
`test_o_trigger_resiste_ao_session_replication_role` morre se o `ENABLE ALWAYS`
sair. As três camadas da imutabilidade estão medidas uma a uma e cada medição
mata a sua. Isso é o melhor trabalho deste ticket.

**2. O fecho da validação `tools` é honesto?**

Meio. A `validar_tools` — código do KAM-027, que não mudou — faz duas
perguntas. A primeira («esta tool existe no catálogo?») passou a morder de
verdade: o `Catalogo.nomes()` inclui as declaradas de propósito, há uma mutação
que prova que isso é deliberado (`tls: o catalogo deixa de nomear as
declaradas`), e o `test_com_o_catalogo_ligado_a_validacao_das_tools_morde` liga
um catálogo sem `search_catalog` e o arranque recusa nomeando-a. O mecanismo
de `aviso` do KAM-027 também está correcto: `bloqueio` é a omissão, fechar é
apagar a linha, e um `aviso` que sobreviva ao credor é erro de arranque. Nada
disto é um silêncio.

A segunda pergunta («alguma expõe `tenant_id`?») é **vazia para dez das onze**,
porque `parametros_visiveis()` de uma entrada `declarada` é `frozenset()`
(achado 10). A diferença em relação ao estado anterior é que antes a validação
dizia, por `PorLigar`, «não se confirma que nenhuma expõe
`['tenant_id', …]`» — e agora não diz nada. Trocou-se um silêncio **declarado**
por um silêncio **calado**, em metade da validação. Não é grave em
consequência — o `_validar_ligada` recusa no arranque e o *lint* corre em CI —,
é grave em contabilidade: é a única das seis validações que está marcada como
fechada e cujo fecho ninguém pode medir até o KAM-031 chegar.

**3. A `tool_audit` é mesmo *append-only*, e as restrições recusam o que dizem?**

Sim, e esta é a parte melhor construída do ticket. Procurei os três buracos que
a pergunta nomeia e não encontrei nenhum:

* **`NULL` nos `CHECK`.** A divisão em duas restrições está **certa**, ao
  contrário do que a primeira leitura sugere. O `tool_audit_error_code CHECK
  (error_code IN (…))` sem `IS NULL OR` deixa passar o nulo — `NULL IN (…)` é
  `NULL` e um `CHECK` só recusa o falso —, mas o
  `tool_audit_erro_tem_codigo` fecha-o nos dois sentidos (`status='ok' AND
  error_code IS NULL` ou `status='erro' AND error_code IS NOT NULL`), e o
  `status` tem domínio fechado. Qualquer linha com `error_code` não nulo passa
  pelo domínio; qualquer linha com `status='erro'` tem `error_code` não nulo.
  Não há combinação que escape. As dez restrições têm teste negativo próprio e
  correm contra PostgreSQL 18.6 (105 testes OK, confirmado por mim).
* **Privilégios por coluna que não batem com o `INSERT`.** Batem, nos três
  sítios: `auditoria.COLUNAS` (18), `COLUNAS_ESCRITAS_PELO_CHAMADOR` da `0021`
  e `COLUNAS_POR_PAPEL` do `test_privilegios`. E há máquina a impedir a
  divergência: o `test_as_colunas_sao_as_que_a_migracao_concede` lê a fonte da
  migração com `re` e compara a tupla. O `confirmar` do arranque pergunta por
  `has_column_privilege` coluna a coluna, e não por `has_table_privilege` — que
  era a leitura errada, e está escrito porquê.
* **Caminhos de escrita a escapar à RLS.** `enable_tenant_rls` dá `ENABLE` +
  **`FORCE`** + política `tenant_iso` com `USING` e `WITH CHECK`; o `FORCE`
  prende o dono. O `kamba_app` tem `INSERT` por coluna e **não** tem `SELECT`.
  O único papel com `BYPASSRLS` que vê esta tabela é o `kamba_batch`, e tem
  `SELECT` e mais nada. O `kamba_agr` não tem `USAGE` no `platform`. Os dois
  *triggers* estão `ENABLE ALWAYS` e há teste a ler o `tgenabled` do
  `pg_trigger`. A tabela entra nas quatro listas do `test_x05_catalogo.py` e em
  `SEM_RECEITA_COM_RAZAO` com a razão certa (as receitas limpam com `DELETE`, e
  o *trigger* recusa-o).

O que falta aqui é só o achado 11: nenhuma restrição sobre o **conteúdo** dos
`fact_ids`, numa coluna que o próprio ticket descobriu ser caminho de fuga.

**4. Há fuga de dados do cliente para a `tool_audit` ou para o esquema que vai ao
modelo?**

Para a `tool_audit`, sim, pelos nomes dos argumentos (achado 5), e é a resposta
à pergunta «procura em todas as colunas, não só nas óbvias». Olhei para as vinte:

| Coluna | Fonte | Risco |
|---|---|---|
| `tenant_id`, `contact_id`, `conversation_id` | `ToolContext`, do estado | nenhum — identificadores, e é o desenho |
| `turn_id`, `run_id`, `vertical`, `graph_version` | contexto e registo | nenhum, com tecto de 200 caracteres a impedir conteúdo |
| `tool`, `tool_version`, `klass` | catálogo | nenhum — gramática no `CHECK` |
| `args_hash` | `sha256` da forma canónica | nenhum |
| **`args_redacted`** | **nomes** dos argumentos crus | **fuga** (achado 5) |
| `idempotency_key` | chamador | hoje sempre nulo; do KAM-029 é um `sha256`, e o critério dele diz «a coluna `key` nunca contém `+244`» |
| `status`, `error_code` | listas fechadas | nenhum |
| `result_hash` | `sha256` do `data` | nenhum |
| **`fact_ids`** | `fact_id` dos *facts* | fuga fechada **por convenção** e não por restrição (achado 11) |
| `latency_ms`, `ts`, `id` | relógio e identidade | nenhum |

Para o esquema que vai ao modelo, **não**, e aqui o trabalho é melhor do que o
critério pede: o `test_o_esquema_que_vai_ao_modelo_nao_tem_o_contexto` olha para
o `model_json_schema()` **inteiro** e foi o que apanhou que a *docstring* de uma
classe Pydantic entra no esquema como `description` — a descoberta mais valiosa
deste ticket, e a regra que fica («o que se escreve numa classe de argumentos de
tool é texto para o modelo») vale para os dois tickets seguintes. O que esse
teste não cobre é um `Field(description=…)`, que o comentário nomeia e nenhum
*lint* verifica; fica para o KAM-031 e não é achado deste.

Uma nota sobre o `detalhe` do `ErroDeTool`: ele não vai à `tool_audit` (está
escrito e é verdade — a `parametros()` só escreve o `codigo`), mas no passo 3
ele leva os **nomes dos campos** que falharam, que no caso do `extra="forbid"`
são os nomes inventados pelo modelo. Vai para o log, onde o `detalhe` não é
campo da *allowlist* — portanto não chega lá —, e vai no `ToolResult` para o
grafo. Onde isso acaba é decisão do KAM-031 (L4 do §4.3), e fica nomeado aqui
sem ser achado.

**5. O que acontece quando a auditoria falha depois do backend ter corrido?**

A resposta do autor é: levantar `AuditoriaIndisponivelError`, deixar o turno
falhar e o *job* voltar à fila, e nomear o KAM-029 como quem fecha a janela.
Avaliada para a classe `money`, é **a decisão certa com a rede errada**.

Certa porque a alternativa — engolir e devolver `ok` — é o que faz um efeito de
dinheiro existir sem registo, que é o oposto do ADR-015. E a guarda de arranque
(código de saída 6, `has_column_privilege` nas dezoito colunas) retira a causa
mais provável, que é configuração; o `test_sem_auditoria_de_tools_o_agr_nao_arranca`
mede que o processo **sai** e não abre porta, que é a coisa certa a medir.

A rede está errada em duas coisas. A primeira é que o *job* a voltar à fila com
o efeito já feito e **sem** idempotência é uma segunda cobrança: o passo 5
exige chave e não a usa para nada, e quem a usa é um ticket que não existe. A
sequência completa — `criar_pedido` cobra, `escrever` levanta, turno falha,
*job* repete, `criar_pedido` cobra outra vez — não tem nada no caminho hoje. A
segunda é que, nesse caminho, o `agr_tool_erros_total` não conta a invocação
(achado 12): o alerta que o §6.5 pede para uma violação existe, mas o alerta
desta janela em particular não.

O que atenua é que nenhuma tool `write` ou `money` tem executor neste ticket,
pelo que a janela não é alcançável em produção hoje — e isso está dito. O que
devia estar dito e não está é que o KAM-029 não é apenas «quem fecha por
inteiro»: é **o único** que fecha, e sem ele a classe `money` não deve ter
executor nenhum. Essa é uma frase para o bloco do KAM-031, e é a única coisa
que peço aqui além da métrica.

**6. Aguenta a carga esperada?**

Não. É o achado 3, e é o defeito mais caro deste ticket pela mesma razão que foi
o mais caro do KAM-025: um `asyncio.Lock` por processo em volta de trabalho que
bloqueia. Medido em 10,1x de serialização com dez *tenants*. Com o tecto de 8 s
das classes de escrita e sem tecto nenhum imposto pela camada (achado 4), o pior
caso não é lentidão — é um executor pendurado a prender toda a leitura e escrita
de todos os agentes do processo até alguém reiniciar o serviço.

A forma da casa que o `invoke` diz copiar é a do `conversa.py`, e a do
`conversa.py` é uma leitura curta dentro do trinco. A forma que o
`trancas.py` adoptou **depois de medir** — tomar o trinco, fazer uma instrução,
largá-lo, esperar fora — é a que se aplica aqui, e é a que não foi copiada. A
`tests_agr` tem um teste chamado `test_duas_conversas_diferentes_nao_se_travam`
para a tranca; a camada não tem o equivalente, e é por isso que ninguém viu.

A ligação única também é um limite, mas é o segundo: uma invocação abre três
transacções em série (entitlement, backend `plataforma`, auditoria) e isso é
uma escolha razoável para a `pg8000`. O que não é razoável é a chamada ao
backend `com`/`pay`/`idx` — que não toca na ligação — estar dentro do trinco
dela.

**7. Alguma linha é desnecessária, ou alguma abstracção não se paga?**

Pouco, e o ticket é notavelmente enxuto para 4 989 linhas: quase tudo o que está
lá tem um critério atrás. O que encontrei está nos achados 20 a 23, e o total é
de uma dezena de linhas. O caso mais claro é o `passos_corridos`, escrito e
nunca lido (achado 20). O mais discutível é o par
`passo_7_auditoria`/`inv.registada` (achado 21): o `finally` sozinho dá a
cobertura, e o passo 7 existe para que a ordem se leia nos `PASSOS` — uma
indirecção comprada para tornar afirmável uma frase de documento. A troca é
defensável porque o critério 1 pede a ordem por extenso; é, de todo o ticket, o
sítio onde ela menos se paga.

O que **não** é desnecessário e podia parecer: os dois estados de uma entrada de
catálogo (`ligada`/`declarada`) são o que permite fechar a validação (1) sem
inventar especificações de outros tickets, e têm mutação própria a prová-lo; o
`_ClienteDeCursor` traduz pelo `description` e não por posição, com a razão
escrita; o `Catalogo` validar ao construir-se em vez de na importação tem razão
de código de saída. Nenhum destes é bloat.

**8. Que consumidor deste desenho quebra?**

Li os sete blocos. Dois quebram, dois ficam mais caros, três passam.

| Ticket | Estado |
|---|---|
| **KAM-032** | **Quebra.** O `Fact` entregue não tem `sku` e o `KINDS` não tem `name` nem `discount`, e os três são a dependência que o bloco dele declara pelo nome (achado 9). Obrigado a emendar o canon que esta emenda 1.36 acabou de fixar |
| **KAM-061** | **Quebra.** Chama-lhe `search_products`; o catálogo é lista fechada e a validação está em `bloqueio` (achado 16). Código de saída 5 no primeiro arranque depois de o registar |
| KAM-029 | Passa, e é onde a janela do achado 12 se fecha. O que encontra pronto é a coluna, o parâmetro e a regra «`write`/`money` nunca correm sem chave», e isso serve-lhe. Mas o critério dele «50 invocações concorrentes de `criar_pedido` com o mesmo `cart_id`» vai medir-se através do trinco do achado 3: 50 invocações em série com o tecto de 8 s cada |
| KAM-031 / KAM-035 | Mais caros. A primeira linha de cada um — `from .especificacoes import EspecificacaoDeTool` — rebenta com `ImportError` (achado 1). Depois disso herdam: o tecto de 8 s para implementar no executor (achado 4), o retry do §6.5 para implementar no grafo, o `hold_id` do `book_slot` que não é argumento dela (dívida 103, bem registada), e a metade dos limites do TEN que o passo 2 não faz e para a qual o `invoke` não tem parâmetro (achado 6) |
| KAM-066 | Passa, com uma ressalva. O critério dele — «um item enumerado sem caso registado falha o CI» — vai enumerar onze tools, e dez delas não têm modelo de argumentos (`parametros_visiveis()` vazio), pelo que o *harness* não tem como sintetizar «argumentos que referem entidades de B». Vai herdar o X-02 vazio do achado 7 em vez de o corrigir |
| KAM-118 | Passa. A dívida 98 (a lista de permitidos da porta do AGR não tem a vertical `catalogo`) já estava registada pelo KAM-027 e este ticket não a agrava: o `ToolContext.de_estado` só exige que `vertical` seja um texto não vazio |

---

## 6. O que exijo corrigido antes do *merge*

| # | Achado | Porquê não espera |
|---|---|---|
| 1 | Três ficheiros da TLS não se importam sozinhos | É a primeira linha do KAM-031 e do KAM-035. Correcção: avaliar o `_nomes_de_tool()` tarde em vez de ao carregar o `metricas.py`, e corrigir o comentário que diz que não há ciclo |
| 2 | O *lint* do critério 3 não morde numa subclasse nem fora de `tls/` | O critério manda falhar o *build* e está marcado. Correcção: reconhecer qualquer base cujo nome acabe num modelo conhecido do ficheiro, ou resolver a hierarquia no `ast`; e um canário com subclasse |
| 3 | Um trinco global serializa todos os *tenants* | É o defeito do KAM-025, outra vez, no mesmo serviço. Correcção: largar o trinco por ida à base e tirar a chamada ao backend de dentro dele; mais um teste com o nome do da tranca |
| 4 | Nenhum tecto de tempo é imposto | Junto com o 3, uma chamada pendurada é indisponibilidade total e sem recuperação. Correcção: `asyncio.wait_for` com o tecto da classe, que a camada já calcula |
| 5 | Os nomes dos argumentos vão em claro para a `tool_audit` | Texto do cliente num registo *append-only*, no critério que existe para o impedir. Correcção: recusar no passo 3 uma chave fora da gramática de identificador, antes de montar a linha |
| 6 | O passo 2 não consome limites e o `tecto` não tem chamador | Metade de um passo do §6.1 não existe e não tem credor. Correcção mínima: declarar a falta com credor KAM-031, e dar ao `invoke` o parâmetro por onde a chave do balde entra |
| 7 | O X-02 mede onze recusas | É o critério que o bloco nomeia como seu. Correcção: um `dict` de argumentos por tool |
| 8 | A linha de arranque é recusada pelo *logger* | Em modo estrito mata o arranque; em normal apaga a única observabilidade da camada. Correcção: `read2000ms` → `read_2000_ms`, ou tirar o número do campo |
| 9 | O `Fact` não serve o KAM-032 | O único consumidor que declara a interface pelo nome não a consegue usar. Correcção: `sku` opcional e os dois `kind`, ou a dívida com credor KAM-032 |

Os achados 10, 16, 18 e 19 são de declaração e de prosa e cabem no mesmo PR sem
custo — e o 19 em particular, porque o ficheiro que implementa a validação é o
único que ficou a dizer que ela não corre. Os restantes são declaráveis.

**O que merece ser dito a favor.** As três camadas da imutabilidade medidas uma
a uma; o `CHECK` do `error_code` dividido em dois com a razão do `NULL` escrita
e medida; o varrimento de privacidade com controlo positivo; a descoberta de que
a *docstring* de um modelo Pydantic vai no prompt; a disciplina do `credor`
aplicada ao catálogo como o KAM-027 a aplicou ao `gates.yaml`; as vinte mutações
com uma propriedade por critério; e o `test_as_colunas_sao_as_que_a_migracao_concede`,
que é a forma certa de prender duas listas em ficheiros diferentes. Os nove
*must fix* são de uma camada que não foi exercida — nunca foi importada sozinha,
nunca foi chamada em concorrência, nunca recebeu um executor lento — e não de
uma camada mal desenhada.

---

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial. Revisão adversarial independente do KAM-028, com `code-review high` e `ponytail-review` na mesma passagem, e oito perguntas dirigidas. 23 achados — 9 *must fix*, 10 *should fix*, 4 *nice to have*; veredicto **REPROVADO**, com nove exigidos antes do *merge*. As medições correram no próprio *worktree* com `.venv/Scripts/python.exe`: `services/agr/tests` (371 OK), `db/gate_bd.py --suite tests_agr` (105 OK), `lint_arch tool-schema` (conforme), e quatro guiões próprios — o `import` módulo a módulo, a serialização do trinco com dez *tenants*, o tecto de tempo com um executor de 5 s, e o que o laço do X-02 de facto exercita tool a tool. | Revisor adversarial |

---

## 8. Resolução

Escrito por quem corrigiu, depois da revisão, e separado do corpo dela de
propósito: o relatório é o produto do revisor e não se reescreve.

**Os nove *must fix* estão corrigidos, cada um com teste.** Os nove foram
primeiro **reproduzidos** — nenhum se corrigiu por leitura do relatório:

| # | A correcção | O teste que a prende |
|---|---|---|
| 1 | a derivação das etiquetas no `metricas.py` passa a preguiçosa (`functools.lru_cache`) | `TestImportacaoIsolada`, que importa cada um dos oito ficheiros em **subprocesso** — dentro do processo os módulos já estão em `sys.modules` e o ciclo não se vê |
| 2 | o `_e_base_model` passa a resolver por **ponto fixo** sobre as bases do ficheiro, e uma base de fora é **achado** e não silêncio | `test_uma_subclasse_indirecta_tambem_falha`, `test_o_extra_forbid_herda_se`, `test_uma_base_de_fora_do_ficheiro_e_achado_e_nao_silencio` |
| 3 | as tomadas passam a uma `asyncio.Queue` (`KAMBA_TLS_LIGACOES`, 4), com a ligação a voltar pelo valor de retorno do trabalho e nunca pela *thread* | `test_dez_tenants_nao_correm_em_serie` (2,02 s → 0,61 s), `test_a_fila_e_o_tecto_de_tomadas` |
| 4 | a camada impõe o tecto com `asyncio.wait_for` sobre o tecto da classe mais `MARGEM_DO_TECTO_MS`; a *thread* continua, leva a sua vaga e escreve a linha com a latência real | `test_uma_tool_pendurada_custa_uma_vaga_e_nao_o_processo` |
| 5 | o `redigir` recebe os campos declarados; o resto conta-se em `<nao_declarados>`, e **sem** a lista nenhum nome passa | `TestRedaccaoDosNomes`, e `test_um_nome_de_argumento_inventado_nao_chega_a_tabela` contra a base |
| 6 | o tecto por pedido ganha teste contra o `platform.ten_tecto` | `test_o_tecto_por_pedido_do_passo_2_nega_e_nao_consome` |
| 7 | o X-02 dá a cada tool os argumentos que o esquema dela aceita, e **exige** que as ligadas cheguem ao passo 6 | o próprio X-02, com `chegaram_ao_backend == catalogo.ligadas()` |
| 8 | o `error_code` da linha de arranque passa a `ligadas_N_de_M` | `test_sem_auditoria_de_tools_o_agr_nao_arranca` lê o campo |
| 9 | o `sku` entra no `Fact`; os três `kind` que faltam ficam em dívida com credor | `TestFactParaOKam032` |

**Seis dos dez *should fix*** — os de comportamento ou de contagem — também
foram corrigidos: o `absolver` (um erro de negócio deixa de **apagar** a
contagem do disjuntor), a caducidade da tentativa de meio-aberto, o SQL de
várias linhas no *lint*, as métricas num `finally` próprio, a quarta tomada no
`ao_encerrar`, e as três contagens em prosa. Os outros quatro são registo e
ficaram em `../dividas-documentais.md` (linhas 105 a 107) ou nomeados na secção
de verificação do bloco. **Os quatro *nice to have* não se corrigiram**, como a
análise pede.

**Duas correcções que a análise não pediu** e que a medição delas tornou
óbvias: «um `fact_id` é opaco» passou de regra escrita a regra imposta
(`FactIdDerivadoError` — a montagem da linha recusa um `fact_id` que contenha um
valor de argumento), e cancelar o `invoke` punha uma vaga a mais na fila, porque
quem cancela não tem a tomada.

**Uma discordância, com a razão escrita.** O achado 6 nota que o
`consume_limit` nunca corre e o `msgs_ai_mes` nunca decrementa. É verdade e é
deliberado: o `msgs_ai_mes` conta **mensagens** e consome-se no envio (o nó
`send`), não por invocação de tool — consumi-lo a cada `search_catalog` queimava
o balde mensal de um *tenant* numa conversa. Corrigiu-se a outra metade do
achado, que era real: o parâmetro `tecto` não tinha chamador senão a própria
camada.

**E a prova por mutação apanhou o que os testes da correcção não apanhavam.**
Seis mutações novas repõem os seis defeitos acima, e na penúltima corrida
**uma sobreviveu**: a que repõe o `registar_sucesso` no caminho do erro de
negócio. O teste que havia chamava `disjuntor.absolver` **directamente** — prova
o que o `absolver` faz, não que a camada o chama. O teste que a mata corre pelo
`invoke` com um backend a alternar entre erro de negócio e falha. Corrida final:
**26 corridas, 0 não apanhadas**.

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.1 | Outubro 2026 | §8: a resolução. Os nove *must fix* corrigidos com teste, seis dos dez *should fix*, os quatro *nice to have* deixados por decisão, uma discordância fundamentada, e a mutação que sobreviveu à primeira correcção. | Equipa KAMBÁ |
