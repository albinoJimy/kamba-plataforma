"""A ToolLayer do AGR (`docs/tecnica/02` §6, KAM-028).

| Modulo | O que tem |
|---|---|
| `contexto.py` | o `ToolContext` e a `Confirmation` — a fronteira do que o modelo pode influenciar |
| `erros.py` | os dez erros do §6.5, o `Fact` e o `ToolResult` |
| `especificacoes.py` | a forma de uma especificacao e o `Catalogo` |
| `catalogo.py` | as **onze** tools do Piloto (§6.2): uma `ligada`, dez `declaradas` |
| `get_store_info.py` | a primeira tool real |
| `disjuntor.py` | o *circuit breaker* por backend |
| `auditoria.py` | a linha de `tool_audit` |
| `camada.py` | a `ToolLayer`: `for_context`, `invoke` e os **oito passos** |

## Vive no AGR e nao em `libs/py-core`, e a razao e a do `estado.py`

O bloco do ticket propoe `kamba/tls/{context,layer,pipeline,errors,breaker,audit}.py`.
Fica aqui pela regra que o KAM-025 escreveu por extenso no `estado.py`:
«`libs/py-core` e o que **todos** os servicos Python precisam de fazer da mesma
maneira», e o AGR e o unico processo que constroi e le a ToolLayer. Foi tambem o
que o KAM-026 fez com o *checkpointer* e o KAM-027 com o registo, e o dicionario
§3.26 repete a razao na linha do `AgentRegistry`.

**Os nomes dos ficheiros estao em portugues e sao sete e nao seis**, e as duas
diferencas face ao bloco tem razao:

* o portugues e a convencao do pacote (`estado.py`, `contexto.py`, `trancas.py`,
  `registo/`), e os nomes do **contrato** — `ToolLayer`, `for_context`,
  `ToolContext`, `ToolResult`, `Fact`, `Confirmation` — ficam em ingles porque
  sao canon citado do §6.1, como o `load_all` do §5.2 (dicionario §3.27);
* o bloco separa `layer` de `pipeline`, e aqui os dois sao o `camada.py`: o
  pipeline **e** o `invoke`, e separa-los punha os oito passos num ficheiro e a
  sua unica chamadora noutro. O que se ganharia era um nome; o que se perdia era
  ler a ordem ao lado de quem a percorre. Em troca, o `catalogo.py` e o
  `get_store_info.py` sao ficheiros proprios — e o `specs/` do bloco, com a tool
  real separada da lista.

## Este ficheiro nao importa nada, de proposito

O `metricas.py` do AGR deriva as suas etiquetas do `catalogo.py` (a licao das
listas literais, KAM-027), e o `camada.py` importa o `metricas.py`. Um
`__init__` que importasse o `camada` fechava esse triangulo num ciclo de
importacao que so rebenta pela ordem em que alguem importar primeiro. Quem quer
a camada importa `kamba_agr.tls.camada`.
"""
