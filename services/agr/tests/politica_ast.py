"""A politica AST do `handoff_wait` (KAM-034, criterio 2).

«`handoff_wait` tem o `interrupt()` como 1.ª instrucao; teste AST falha se
existir efeito antes dele, `interrupt()` dentro de `try/except` ou dentro de
ciclo `while`.»

## A forma e a do `tools/log_policy/lint.py`, e nao e imitacao

Aquele e a politica AST que o *gate* 2 ja corre, e as tres pecas que ele tem sao
as tres de que isto precisa:

* **regras com nome**, para que um achado diga qual e a propriedade quebrada e
  nao «o ficheiro esta mal»;
* **mensagens por regra**, com o porque, porque quem le o vermelho nao tem o
  §11 aberto;
* **canarios** — ficheiros que **tem** de ser recusados —, porque «o
  repositorio esta conforme» e uma linha que um `check` vazio passa.

Nao se fez um *gate* novo: o bloco pede «Contrato/CI: teste AST sobre
`handoff_wait`», esta bateria corre no `make test-py`, e um *gate* novo e uma
regra de bloqueio nova — que pede dois revisores e que esta linha de trabalho
nao abre. A mesma decisao que o `tool_schema.py` escreveu quando entrou no
`lint_arch` em vez de num *gate* proprio.

## Le a fonte e nao importa nada

Pela razao do `tool_schema.py`: importar e inspeccionar o objecto da a resposta
do codigo **a correr** — e com uma fabrica de nos, o que o `inspect` devolve e a
closure, nao a arvore. O `ast` da a resposta do codigo **escrito**.

## A primeira versao evadia-se com UMA linha, por seis formas

A revisao adversarial do KAM-034 mediu-as (achado 3), e vale escreve-las porque
a correccao e desenhada contra elas e nao contra o enunciado:

| Evasao | Porque passava |
|---|---|
| `desfecho = interrupt(deps.saida.enfileirar(...))` | o argumento avalia-se **antes** da chamada, e a politica so perguntava se a primeira instrucao «contem um `interrupt`» |
| `_, desfecho = deps.x(), interrupt({})` | idem: a instrucao contem um `interrupt` |
| `with contextlib.suppress(BaseException): desfecho = interrupt({})` | um `With` nao e um `ast.Try`, e o LangGraph interrompe **levantando** |
| `[interrupt({"i": i}) for i in range(3)][-1]` | uma compreensao nao e `ast.For`; os geradores dela sao `ast.comprehension` |
| `try: ... except* Exception: ...` | `ast.TryStar` nao e `ast.Try` |
| `async with engole(): desfecho = interrupt({})` | idem o `With` |

As tres primeiras sao o erro que alguem escreveria **sem ma-fe**: quem queira
passar contexto ao `interrupt` escreve o primeiro caso.

## As cinco regras, e porque e que a terceira tinha de existir

1. `sem_interrupt` — o no nao chama `interrupt`. Nao esta no criterio, e sem ela
   as outras passam **vazias**: um no de espera que nao espera satisfaz «nao ha
   efeito antes de nada, nao ha `try`, nao ha ciclo» e manda a conversa para o
   `handoff_close` sem ninguem ter sido chamado.
2. `efeito_antes_do_interrupt` — a chamada ao `interrupt` nao e **o valor
   inteiro** da primeira instrucao. E a forma que apanha as quatro evasoes
   estruturais de uma vez: um tuplo, uma compreensao, um `with` e qualquer
   instrucao a frente dao todos «o valor da primeira instrucao nao e a chamada».
3. `efeito_no_argumento` — os argumentos do `interrupt` tocam o `deps`.

   **E a unica regra que nao e estrutural, e a razao esta na pergunta que o
   `ast` nao pode responder:** «esta chamada e um efeito?». O no real passa
   `estado.get("handoff")` nos argumentos, que e uma chamada e nao e um efeito;
   proibir chamadas nos argumentos recusava codigo correcto, e e assim que se
   ensina alguem a desligar uma politica.

   O que se pode decidir e **de onde** um efeito pode vir, e vem de um sitio so:
   o `deps` e a unica porta deste grafo para o mundo — o `saida` (o Outbound), o
   `tools` (a ToolLayer), o `hnd` (o provedor), o `metricas`. O `estado` e um
   `dict` que o LangGraph deu ao no. Logo: nenhuma referencia ao `deps` antes do
   `interrupt`, e nos argumentos dele e «antes».
4. `interrupt_dentro_de_try` — ha um `Try`, um `TryStar`, um `With` ou um
   `AsyncWith` a envolver o `interrupt`. **O `with` conta**, e e metade do
   achado: o `contextlib.suppress` engole a interrupcao exactamente como o
   `except` que a regra existe para apanhar.
5. `interrupt_dentro_de_ciclo` — ha um `While`, um `For`, um `AsyncFor` **ou uma
   compreensao** a envolver o `interrupt`. A compreensao conta porque e um ciclo
   escrito de outra maneira, e a ordem de multiplos `interrupt()` num no e por
   indice.
"""

from __future__ import annotations

import ast
from typing import Final

EFEITO_ANTES: Final = "efeito_antes_do_interrupt"
EFEITO_NO_ARGUMENTO: Final = "efeito_no_argumento_do_interrupt"
DENTRO_DE_TRY: Final = "interrupt_dentro_de_try"
DENTRO_DE_CICLO: Final = "interrupt_dentro_de_ciclo"
SEM_INTERRUPT: Final = "sem_interrupt"
SEM_NO: Final = "sem_no_interno"

#: O nome do parametro da fabrica que e a porta para o mundo. Tudo o que o no
#: pode fazer **acontecer** passa por aqui (`deps.saida`, `deps.tools`,
#: `deps.hnd`, `deps.metricas`); o `estado` e um `dict` que o LangGraph deu.
PORTA: Final = "deps"

MENSAGENS: Final = {
    EFEITO_ANTES: (
        "a chamada a `interrupt()` nao e o valor inteiro da primeira instrucao "
        "do no: na retoma o no reinicia do principio, pelo que tudo o que corra "
        "antes corre duas vezes (`docs/tecnica/02` §11, defeito 6 do §7.1)"
    ),
    EFEITO_NO_ARGUMENTO: (
        f"os argumentos do `interrupt()` tocam o `{PORTA}`: os argumentos "
        "avaliam-se **antes** da chamada, e o `deps` e a unica porta do no para "
        "o mundo — um efeito ali corre duas vezes na retoma"
    ),
    DENTRO_DE_TRY: (
        "o `interrupt()` esta dentro de `try`, `except*` ou `with`: o LangGraph "
        "interrompe **levantando**, e um `except` generico (ou um "
        "`contextlib.suppress`) engole a interrupcao — a conversa segue sem "
        "nunca ter esperado por ninguem (`docs/tecnica/02` §11)"
    ),
    DENTRO_DE_CICLO: (
        "o `interrupt()` esta dentro de um ciclo (ou de uma compreensao, que e "
        "um ciclo escrito de outra maneira): a ordem de multiplos `interrupt()` "
        "num no e por indice, e num ciclo o indice muda entre execucoes "
        "(`docs/tecnica/02` §11)"
    ),
    SEM_INTERRUPT: (
        "o no nao chama `interrupt()`: um no de espera que nao espera manda a "
        "conversa para o `handoff_close` sem ninguem ter sido chamado"
    ),
    SEM_NO: "nao se encontrou a funcao interna da fabrica do no",
}

#: As regras que o canario tem de ver morder. Fixas aqui e nao derivadas das
#: *fixtures*, pela razao do `REGRAS_OBRIGATORIAS` do `log_policy`: um manifesto
#: que se esvazia dava «0 negativas, tudo verde».
REGRAS_OBRIGATORIAS: Final = (
    EFEITO_ANTES,
    EFEITO_NO_ARGUMENTO,
    DENTRO_DE_TRY,
    DENTRO_DE_CICLO,
    SEM_INTERRUPT,
)

#: Os nos que **engolem** uma excepcao, e por isso engolem a interrupcao. O
#: `With` e o `AsyncWith` entram porque o `contextlib.suppress` e um deles.
_ENGOLEM: Final = (ast.Try, ast.TryStar, ast.With, ast.AsyncWith)

#: Os nos que **repetem**. As tres compreensoes entram porque sao ciclos.
_REPETEM: Final = (
    ast.While,
    ast.For,
    ast.AsyncFor,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)

#: As formas de instrucao em que uma chamada pode ser **o valor inteiro**.
_VALOR_INTEIRO: Final = (ast.Assign, ast.AnnAssign, ast.Expr, ast.Return, ast.Await)


def _fabrica(arvore: ast.AST, nome: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef) and no.name == nome:
            return no
    return None


def _no_interno(
    fabrica: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """A funcao que a fabrica devolve.

    Procura-se o `return <nome>` e resolve-se o nome, em vez de se assumir que a
    funcao interna se chama `no`: uma politica que dependesse do nome calava-se
    no dia em que alguem renomeasse a funcao interna — e calar-se e o unico modo
    de falha que uma politica nao pode ter.
    """
    devolvido: str | None = None
    for corpo in fabrica.body:
        if isinstance(corpo, ast.Return) and isinstance(corpo.value, ast.Name):
            devolvido = corpo.value.id
    if devolvido is None:
        return None
    for corpo in fabrica.body:
        if (
            isinstance(corpo, ast.FunctionDef | ast.AsyncFunctionDef)
            and corpo.name == devolvido
        ):
            return corpo
    return None


def _e_interrupt(no: ast.AST) -> bool:
    """Esta expressao **e** a chamada a `interrupt(...)`?

    Pelo nome ou por atributo (`types.interrupt(...)`): e o mesmo `interrupt`
    por outro caminho, e dar `sem_interrupt` sobre um no correcto era ensinar
    quem levasse o vermelho a desligar a politica.
    """
    if not isinstance(no, ast.Call):
        return False
    alvo = no.func
    if isinstance(alvo, ast.Name):
        return alvo.id == "interrupt"
    return isinstance(alvo, ast.Attribute) and alvo.attr == "interrupt"


def _chamadas_de_interrupt(no: ast.AST) -> list[ast.Call]:
    """Todas as chamadas a `interrupt` na subarvore."""
    return [filho for filho in ast.walk(no) if _e_interrupt(filho)]


def _valor_da_instrucao(instrucao: ast.stmt) -> ast.expr | None:
    """O valor de uma instrucao, se ela tiver **um** valor inteiro."""
    if not isinstance(instrucao, _VALOR_INTEIRO):
        return None
    return getattr(instrucao, "value", None)


def _desembrulhar(valor: ast.expr | None) -> ast.expr | None:
    """Tira o `await` de `desfecho = await interrupt(...)`.

    O `interrupt` do LangGraph e sincrono, mas recusar a forma `await` dava um
    vermelho sobre codigo que alguem podia escrever de boa-fe num no `async`, e
    o que importa e que **nada corre antes** — um `await` sobre a propria chamada
    nao corre nada antes dela.
    """
    while isinstance(valor, ast.Await):
        valor = valor.value
    return valor


def _toca_a_porta(no: ast.AST) -> bool:
    """A subarvore refere o `deps`?"""
    return any(
        isinstance(filho, ast.Name) and filho.id == PORTA for filho in ast.walk(no)
    )


def verificar(fonte: str, nome: str = "handoff_wait") -> list[str]:
    """Os achados sobre a fabrica `nome`. Lista vazia e conforme."""
    arvore = ast.parse(fonte)
    fabrica = _fabrica(arvore, nome)
    if fabrica is None:
        return [f"{nome}: {SEM_NO} — {MENSAGENS[SEM_NO]}"]
    corpo_do_no = _no_interno(fabrica)
    if corpo_do_no is None:
        return [f"{nome}: {SEM_NO} — {MENSAGENS[SEM_NO]}"]

    chamadas = _chamadas_de_interrupt(corpo_do_no)
    if not chamadas:
        return [f"{nome}: {SEM_INTERRUPT} — {MENSAGENS[SEM_INTERRUPT]}"]

    achados: list[str] = []

    def apontar(regra: str) -> None:
        achados.append(f"{nome}: {regra} — {MENSAGENS[regra]}")

    instrucoes = [
        linha
        for linha in corpo_do_no.body
        # Uma *docstring* nao e uma instrucao: e a primeira expressao constante
        # do corpo, e o interpretador nao a executa como efeito.
        if not (
            isinstance(linha, ast.Expr)
            and isinstance(linha.value, ast.Constant)
            and isinstance(linha.value.value, str)
        )
    ]

    # **Regra 2: a chamada tem de ser o valor INTEIRO da primeira instrucao.**
    # Nao «a primeira instrucao contem um `interrupt`», que foi o que a primeira
    # versao perguntou e o que quatro das seis evasoes exploravam.
    primeira = _desembrulhar(_valor_da_instrucao(instrucoes[0])) if instrucoes else None
    if not (primeira is not None and _e_interrupt(primeira)):
        apontar(EFEITO_ANTES)
    else:
        # **Regra 3: os argumentos avaliam-se antes da chamada.** So se pergunta
        # pelos argumentos da chamada que **e** a primeira instrucao; nas outras
        # formas a regra 2 ja mordeu.
        if any(_toca_a_porta(argumento) for argumento in primeira.args) or any(
            _toca_a_porta(palavra.value) for palavra in primeira.keywords
        ):
            apontar(EFEITO_NO_ARGUMENTO)

    # **Regras 4 e 5: o que envolve o `interrupt`.** Percorre-se a arvore e
    # pergunta-se, por cada no que engole ou repete, se ha um `interrupt` dentro
    # dele — e nao o contrario, porque o `ast` nao da pais.
    if any(
        isinstance(linha, _ENGOLEM) and _chamadas_de_interrupt(linha)
        for linha in ast.walk(corpo_do_no)
    ):
        apontar(DENTRO_DE_TRY)
    if any(
        isinstance(linha, _REPETEM) and _chamadas_de_interrupt(linha)
        for linha in ast.walk(corpo_do_no)
    ):
        apontar(DENTRO_DE_CICLO)

    return achados
