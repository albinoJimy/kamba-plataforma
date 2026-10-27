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
  repositorio esta conforme» e uma linha que um `check` vazio passa. A pergunta
  que o KAM-026 e o KAM-027 ensinaram a fazer: *o que faria este teste passar
  com o codigo da politica apagado?*

Nao se fez um *gate* novo: o bloco pede «Contrato/CI: teste AST sobre
`handoff_wait`», esta bateria corre no `make test-py`, e um *gate* novo e uma
regra de bloqueio nova — que pede dois revisores e que esta linha de trabalho
nao abre. A mesma decisao que o `tool_schema.py` escreveu quando entrou no
`lint_arch` em vez de num *gate* proprio.

## Le a fonte e nao importa nada

Pela razao do `tool_schema.py`: importar e inspeccionar o objecto da a resposta
do codigo **a correr** — e com uma fabrica de nos, o que o `inspect` devolve e a
closure, nao a arvore. O `ast` da a resposta do codigo **escrito**, que e o que
um PR traz.

## A quarta regra, que o criterio nao pede

`sem_interrupt`. Sem ela as outras tres passavam **vazias** sobre um
`handoff_wait` que nao interrompesse nada — e um no de espera que nao espera e
pior do que um efeito antes do `interrupt`: a conversa segue para o
`handoff_close` sem ninguem ter sido chamado. E a licao do KAM-032 outra vez:
o que nao se extrai nao se valida.
"""

from __future__ import annotations

import ast
from typing import Final

EFEITO_ANTES: Final = "efeito_antes_do_interrupt"
DENTRO_DE_TRY: Final = "interrupt_dentro_de_try"
DENTRO_DE_CICLO: Final = "interrupt_dentro_de_ciclo"
SEM_INTERRUPT: Final = "sem_interrupt"
SEM_NO: Final = "sem_no_interno"

MENSAGENS: Final = {
    EFEITO_ANTES: (
        "ha uma instrucao antes do `interrupt()`: na retoma o no reinicia do "
        "principio, pelo que tudo o que esteja antes corre duas vezes "
        "(`docs/tecnica/02` §11, defeito 6 do §7.1)"
    ),
    DENTRO_DE_TRY: (
        "o `interrupt()` esta dentro de `try`: o LangGraph interrompe "
        "levantando, e um `except` generico engole a interrupcao — a conversa "
        "segue sem nunca ter esperado por ninguem (`docs/tecnica/02` §11)"
    ),
    DENTRO_DE_CICLO: (
        "o `interrupt()` esta dentro de um ciclo: a ordem de multiplos "
        "`interrupt()` num no e por indice, e num ciclo o indice muda entre "
        "execucoes (`docs/tecnica/02` §11)"
    ),
    SEM_INTERRUPT: (
        "o no nao chama `interrupt()`: um no de espera que nao espera manda a "
        "conversa para o `handoff_close` sem ninguem ter sido chamado"
    ),
    SEM_NO: "nao se encontrou a funcao interna da fabrica do no",
}

#: As quatro regras que o canario tem de ver morder. Fixas aqui e nao derivadas
#: das *fixtures*, pela razao do `REGRAS_OBRIGATORIAS` do `log_policy`: um
#: manifesto que se esvazia dava «0 negativas, tudo verde».
REGRAS_OBRIGATORIAS: Final = (
    EFEITO_ANTES,
    DENTRO_DE_TRY,
    DENTRO_DE_CICLO,
    SEM_INTERRUPT,
)


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


def _chama_interrupt(no: ast.AST) -> bool:
    """`interrupt(...)`, pelo nome ou por atributo (`types.interrupt(...)`)."""
    for filho in ast.walk(no):
        if not isinstance(filho, ast.Call):
            continue
        alvo = filho.func
        if isinstance(alvo, ast.Name) and alvo.id == "interrupt":
            return True
        if isinstance(alvo, ast.Attribute) and alvo.attr == "interrupt":
            return True
    return False


def verificar(fonte: str, nome: str = "handoff_wait") -> list[str]:
    """Os achados sobre a fabrica `nome`. Lista vazia e conforme."""
    arvore = ast.parse(fonte)
    fabrica = _fabrica(arvore, nome)
    if fabrica is None:
        return [f"{nome}: {SEM_NO} — {MENSAGENS[SEM_NO]}"]
    corpo_do_no = _no_interno(fabrica)
    if corpo_do_no is None:
        return [f"{nome}: {SEM_NO} — {MENSAGENS[SEM_NO]}"]

    achados: list[str] = []
    instrucoes = [
        linha
        for linha in corpo_do_no.body
        # Uma *docstring* nao e uma instrucao: e a primeira expressao constante
        # do corpo, e o interpretador nao a executa como efeito. Qualquer
        # **outra** expressao solta conta, incluindo uma chamada cujo valor se
        # descarta — que e precisamente a forma de um efeito.
        if not (
            isinstance(linha, ast.Expr)
            and isinstance(linha.value, ast.Constant)
            and isinstance(linha.value.value, str)
        )
    ]

    if not _chama_interrupt(corpo_do_no):
        return [f"{nome}: {SEM_INTERRUPT} — {MENSAGENS[SEM_INTERRUPT]}"]

    if not instrucoes or not _chama_interrupt(instrucoes[0]):
        achados.append(f"{nome}: {EFEITO_ANTES} — {MENSAGENS[EFEITO_ANTES]}")

    for linha in ast.walk(corpo_do_no):
        if isinstance(linha, ast.Try) and _chama_interrupt(linha):
            achados.append(f"{nome}: {DENTRO_DE_TRY} — {MENSAGENS[DENTRO_DE_TRY]}")
            break
    for linha in ast.walk(corpo_do_no):
        if isinstance(linha, ast.While | ast.For | ast.AsyncFor) and _chama_interrupt(
            linha
        ):
            achados.append(f"{nome}: {DENTRO_DE_CICLO} — {MENSAGENS[DENTRO_DE_CICLO]}")
            break

    return achados
