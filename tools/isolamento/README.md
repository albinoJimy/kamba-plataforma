# `tools/isolamento` — o *harness* de isolamento cruzado (KAM-066, ADR-015)

Nenhum tenant ve dados de outro, e nenhum contacto ve dados de outro dentro do
mesmo tenant. Esta pasta nao e uma suite de testes: e a **maquina que recusa a
ausencia de um teste**.

A diferenca esta no criterio 2 do bloco do KAM-066:

> A enumeracao automatica cobre 100% das rotas, *tools* do REG, *jobs* BullMQ e
> consumidores EVT; um item enumerado sem caso registado **falha o CI** (nao
> existe «sem teste» silencioso).

Uma suite escrita a mao cresce quando alguem se lembra. Esta recusa-se a passar
quando uma superficie nova nao tem caso — e por isso a enumeracao vem antes dos
casos, e nao depois.

---

## Como acrescentar um caso

A ordem e esta, e e a mesma seja a superficie uma rota, uma *tool*, uma fila ou
um consumidor.

### 1. Pergunte a enumeracao como e que o item se chama

```bash
python -c "import sys; sys.path.insert(0, 'tools'); \
           from isolamento.cli import main; sys.exit(main(['--listar']))"
```

Cada linha e `id`, tipo e sitio. O `id` e o contrato: e ele que vai no
`enumeravel` do caso, e e por ele que a cobertura liga as duas pontas. Um item
que apareca com `(indeciso)` tem o **sitio** no `id` em vez do nome, porque a
enumeracao nao o conseguiu resolver — e precisa de caso como qualquer outro.

### 2. Escolha a bateria e o modulo

| Bateria | O que ataca | Modulo |
|---|---|---|
| X-01 | rotas (IDOR autenticado) | `baterias/x01_rotas.py` |
| X-02 | *tools* do REG, pela ToolLayer | `baterias/x02_tools.py` |
| X-03 / X-04 / X-05 | a base: contexto, falha fechada, catalogo | `baterias/x03_x04_x05_base.py` |
| X-06 | vectores (IDX) | `baterias/x06_vectores.py` (KAM-061) |
| **X-07** | **reservada** | — ver «A lacuna X-07», abaixo |
| X-08 | *storage* | **por escrever** — credor KAM-011, KAM-020 |
| X-09 | injeccao cruzada, ≥ 30 *prompts* PT-AO | **por escrever** — credor KAM-073 |
| X-10 | *cross-seller* e *cross-account* | **por escrever** — credor KAM-042, KAM-019 |
| X-11 | *logs* | ja existe, no `make x11` (KAM-068) |
| C-01 | isolamento de contacto, no mesmo tenant | `baterias/c01_contacto.py` |
| P-01 | *pooling* em modo transaccao | `baterias/p01_pooling.py` |
| J-01 | filas BullMQ: o que o corpo do *job* transporta | `baterias/jobs_filas.py` |

Um modulo novo entra em `baterias/__init__.py`, na lista `MODULOS`. E uma lista
e nao uma varredura do directorio de proposito: um ficheiro deixado a meio nao
passa a correr sozinho.

### 3. Escreva o `fn`, e diga de que precisa

```python
from ..casos import registar_caso


def _o_meu_caso(ctx) -> list[str]:
    """Devolve os achados. Lista vazia quer dizer conforme."""
    achados = []
    resposta = ...  # o ataque: estado de A, identificadores de B
    achados += [
        f"o-meu-item: {fuga}"
        for fuga in ctx.oraculo.varrer_tudo(
            {"corpo": resposta.corpo, "cabecalhos": resposta.cabecalhos}
        )
    ]
    return achados


registar_caso(
    id="X-01/o-meu-servico/a-minha-rota",
    bateria="X-01",
    camada="rotas",
    enumeravel=("rota:svc:app:createApp:POST:/a/minha/rota",),
    fn=_o_meu_caso,
    precisa="postgres",
    origens=("corpo", "cabecalhos", "logs"),
)
```

O `precisa` **escolhe onde o caso corre**, e nao a bateria:

| `precisa` | O que tem de existir | Onde corre |
|---|---|---|
| `nada` | biblioteca padrao e a arvore | `make isolamento-a-seco`, e outra vez no *gate* 6 |
| `agr` | `starlette`, `pydantic`, `yaml` | `db/tests_isolamento/test_casos_cruzados.py` |
| `postgres` | a base descartavel do *gate* 6 | idem |
| `node` | o condutor de `tests/condutor/` | idem |

**Um modulo de `baterias/` tem de ser importavel sem nada disso.** E o que
permite medir a cobertura a seco, antes de o contentor subir: o `import` de um
modulo que precise do `starlette` fazia o passo a seco falhar na importacao em
vez de dizer que uma rota nao tem caso. Importe o que precisa **dentro** do
`fn` (ver `baterias/x01_rotas.py`, que poe o ataque ao AGR em `_agr.py` e so o
importa quando o caso corre).

### 4. Ponha a sonda positiva ao lado de cada «zero»

E a regra que nao tem excepcao de conveniencia, e a razao esta medida: quatro
afirmacoes de «zero canarios» passam todas contra uma tabela vazia, contra um
contacto sem linhas e contra uma consulta que nao devolve nada a ninguem.

```python
# A metade positiva, primeiro:
if canario_de_a not in o_que_a_leu:
    achados.append("a sonda positiva falhou: a leitura de A nao traz A")
# Só depois a negativa:
if canario_de_b in o_que_a_leu:
    achados.append("a leitura de A traz o canario de B")
```

O `Oraculo` tem a sua propria sonda (`confirmar_que_morde`), e o corredor
corre-a **uma vez antes do primeiro caso**, sobre **todos** os oraculos que o
contexto traz: se um deles nao encontrar um canario que esta mesmo la, nenhuma
bateria chega a correr.

**O que o corredor nao verifica, e vale saber:** ele nao inspecciona o que o teu
`fn` fez por dentro. O `origens` que declaras e verificado **so na forma** (que
nenhuma origem esta fora das cinco); se declarares `logs` e nao varreres nada, o
corredor nao o apanha. A sonda positiva ao lado de cada «zero» e, por isso, tua
— e e a unica coisa neste pacote que nao tem portao a cobri-la.

### 5. Corra, e veja a cobertura fechar

```bash
make isolamento-a-seco                          # enumeracao, cobertura, lint
cd tools && python -m unittest discover -s isolamento/tests -t .
make ci-6                                       # a suite inteira, com base
```

---

## E se o caso ainda nao pode existir?

Entao a superficie vai para `ci/isolamento-dispensas.yaml`, com o **credor** (o
ticket que escreve o caso) e a **razao**. O ficheiro nasceu vazio e deve
continuar vazio enquanto puder: cada entrada e uma superficie que ninguem
ataca.

Tres trincos, e o terceiro e o que impede a valvula de virar porta:

1. o credor tem de ser um `KAM-NNN` que **existe** no §4 do `specs/INDICE.md`;
2. a razao tem de ter 60 caracteres (o dobro do que o `rls_exceptions` pede);
3. uma dispensa morta — para um item que desapareceu, ou que entretanto ganhou
   caso — **falha o *gate***.

---

## A lacuna X-07

A lista de baterias de `docs/tecnica/08` §3.7 vai de X-01 a X-11 e **salta o
X-07**: a tabela desse paragrafo tem X-06 (vectores) seguido de X-08
(*storage*), sem nada no meio e sem nota a dizer porque. O bloco do KAM-066
manda reservar o identificador e registar a lacuna, e e o que esta feito:

* `casos.BATERIAS` inclui `"X-07"`, com o comentario a dizer que e a lacuna;
* `casos.RESERVADAS` inclui-o, e `registar_caso` **recusa** um caso com essa
  bateria;
* o relatorio do *harness* imprime `X-07: reservada (lacuna de 08 §3.7)`.

Reservar e nao reutilizar, e a razao e de leitura: um X-07 atribuido a outra
coisa fazia uma referencia antiga a `08` §3.7 passar a apontar para a bateria
errada, sem que nada avisasse. Quem quiser dar-lhe conteudo tem de emendar o
§3.7 primeiro — e aí a numeracao passa a ser a do documento e nao a deste
ficheiro.

---

## Onde esta o que

```text
enumeracao.py   descobre as quatro superficies na fonte; falha fechada
casos.py        `registar_caso`, as dispensas, e as quatro perguntas da cobertura
corredor.py     chama os `fn`; num gate, saltar e falhar
oraculo.py      procura o canario em corpo, cabecalhos, erros, logs e spans
semente.py      o eixo do contacto: X e Y, no mesmo tenant
lints.py        nenhum `SET app.tenant_id` sobrevive a transaccao
cli.py          o passo a seco do gate 6 (`make isolamento-a-seco`)
baterias/       os casos, um modulo por bateria
condutor/       a ponte para o condutor: arranca o `node` e le o relatorio
tests/          os canarios — cada verificacao tem de saber dizer «esta mal»
tests/condutor/ o condutor de TypeScript: ataca as apps Hono em processo
```

**O condutor de TypeScript esta em `tests/condutor/` e a ponte em `condutor/`,
e a separacao nao e arrumacao.** O `ci/thresholds.yaml` classifica por caminho:
`*/isolamento/*` e padrao do estrato `critico`, e um ficheiro `.ts` do universo
que nenhum teste carrega entra com todas as suas linhas no denominador e zero no
numerador. Medido **no *gate* 4 do commit `6212517`**, quando o condutor tinha
1310 linhas: levaram o estrato de 94,23% a 88,07%, contra 90 de minimo. O
ficheiro cresceu desde entao (o grupo `com-interna` do KAM-178), e por isso a
medicao fica datada em vez de arredondada — o que ela mostra e o sinal, nao o
numero de hoje. O `**/tests/**` dos `excluidos` ja existia e ja cobria o caso
gemeo — o `packages/core-ts/tests/x11_conduzir.ts`,
que o `make x11` conduz e que diz na propria *docstring* que vive em `tests/`
por nao ser um teste. Um andaime de ensaio em TypeScript vai para `tests/`;
**mexer no criterio do portao para o acomodar seria outra coisa, e nao e de
quem escreve o ticket.**

O eixo do **tenant** nao vive aqui: `db/tests_isolamento/sementes.py` semeia A e
B com canarios em todas as tabelas com `tenant_id` (45 receitas, do KAM-004 e
dos treze tickets que o alargaram), e `db/tests_isolamento/catalogo.py` tem as
verificacoes de `pg_class` × `pg_policy`. Este *harness* usa-os; nao os
duplica.

---

## O que este *harness* **nao** substitui

O repositorio base injecta `WHERE tenant_id` por construcao
(`docs/tecnica/08` §3.1), a RLS `FORCE` recusa sem contexto, e a ToolLayer nao
expoe `tenant_id` ao modelo. Uma suite de isolamento e a **ultima** camada: ela
impede a regressao, nao produz o isolamento. Uma suite verde com a RLS
desligada seria pior do que nenhuma, porque da confianca — e e por isso que o
criterio 8 do bloco exige a prova por mutacao (`db/mutacoes.py`), e nao so os
testes.
