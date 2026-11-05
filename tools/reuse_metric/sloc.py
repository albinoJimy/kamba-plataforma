"""Linhas de codigo efectivas, por ficheiro e por simbolo (KAM-039).

## Porque e que nao e `wc -l`

A convencao deste repositorio e comentar por extenso: o
`verticais/servicos/nos.py` tem 1435 linhas e **649** com codigo, e o
`verticais/servicos/arestas.py` tem 699 e 268. Uma metrica de reaproveitamento
medida em linhas brutas nao mede reaproveitamento — mede densidade de prosa, e
move-se quando alguem explica melhor uma decisao. O `reuso` do §5.4 pergunta
quanto **codigo** a vertical nova teve de escrever, pelo que a unidade e a
linha com codigo.

E nao e uma escolha de estilo com duas respostas defensaveis: com `wc -l`, um
ticket que acrescentasse trinta linhas de comentario ao `nos.py` de Servicos
**baixava** o reuso sem acrescentar uma instrucao, e um ticket que apagasse
comentarios subia-o. Um numero que se move ao contrario do que afirma medir nao
se pode defender.

## A regra, a letra

Uma linha conta quando leva pelo menos um *token* que:

* nao e comentario (`COMMENT`);
* nao e estrutura do analisador (`NL`, `NEWLINE`, `INDENT`, `DEDENT`,
  `ENDMARKER`, `ENCODING`);
* nao e uma *docstring* — uma cadeia que e, ela so, uma instrucao de
  expressao.

**A *docstring* identifica-se por posicao e nao por forma.** A primeira versao
desta funcao excluia qualquer cadeia com tres aspas, e isso contava a menos:
uma cadeia de tres aspas usada como valor — um SQL, um texto de persona, um
molde — e codigo, e ha-as neste repositorio (`privacidade/catalogo.py`,
`verticais/*/nos.py`). Agora o AST diz **quais** cadeias sao instrucoes de
expressao, e o `tokenize` salta exactamente essas, pela linha e coluna. As duas
passagens vem do mesmo texto, pelo que nao podem divergir.

Isto conta como codigo o `import`, o `from __future__`, a declaracao de uma
constante e o cabecalho de uma funcao. Conta de proposito: sao as linhas que
alguem tem de escrever e manter.

## O que esta funcao **nao** sabe

Nao sabe se a linha corre. Uma linha de um ramo que nunca se toma conta como as
outras, porque a pergunta do §5.4 e sobre codigo escrito e nao sobre codigo
executado — para «corre ou nao corre» ha cobertura, que e o gate 4.
"""

from __future__ import annotations

import ast
import io
import token as _token
import tokenize
from pathlib import Path
from typing import Final

#: Os tipos de *token* que nao sao codigo em nenhuma leitura.
IGNORADOS: Final[frozenset[int]] = frozenset(
    {
        _token.COMMENT,
        _token.NL,
        _token.NEWLINE,
        _token.INDENT,
        _token.DEDENT,
        _token.ENDMARKER,
        _token.ENCODING,
    }
)


class FonteInvalidaError(ValueError):
    """O ficheiro nao e Python valido. Levanta em vez de contar zero.

    Contar zero era a forma de um erro de sintaxe **subir** o reuso: o ficheiro
    especifico passava a valer 0 no numerador e a metrica melhorava.
    """


def _posicoes_de_prosa(arvore: ast.AST) -> frozenset[tuple[int, int]]:
    """A linha e a coluna de cada cadeia que e, ela so, uma instrucao.

    Cobre a *docstring* de modulo, de classe e de funcao, e tambem a cadeia
    solta que este repositorio usa como comentario de bloco. Nao cobre uma
    cadeia que seja valor de alguma coisa, que e codigo.
    """
    posicoes: set[tuple[int, int]] = set()
    for no in ast.walk(arvore):
        corpo = getattr(no, "body", None)
        if not isinstance(corpo, list):
            continue
        for instrucao in corpo:
            if (
                isinstance(instrucao, ast.Expr)
                and isinstance(instrucao.value, ast.Constant)
                and isinstance(instrucao.value.value, str)
            ):
                posicoes.add((instrucao.value.lineno, instrucao.value.col_offset))
    return frozenset(posicoes)


def linhas_de_codigo(texto: str, *, onde: str = "<texto>") -> frozenset[int]:
    """Os numeros de linha (base 1) que levam codigo. Ver a regra no cabecalho."""
    try:
        arvore = ast.parse(texto)
    except SyntaxError as erro:
        raise FonteInvalidaError(f"{onde}: {erro}") from erro

    prosa = _posicoes_de_prosa(arvore)
    linhas: set[int] = set()
    try:
        for simbolo in tokenize.generate_tokens(io.StringIO(texto).readline):
            if simbolo.type in IGNORADOS:
                continue
            if simbolo.type == _token.STRING and simbolo.start in prosa:
                continue
            linhas.update(range(simbolo.start[0], simbolo.end[0] + 1))
    except tokenize.TokenError as erro:  # pragma: no cover — o `ast` ja falhou
        raise FonteInvalidaError(f"{onde}: {erro}") from erro
    return frozenset(linhas)


def sloc_de_ficheiro(caminho: Path) -> int:
    """As linhas com codigo de um ficheiro inteiro."""
    texto = caminho.read_text(encoding="utf-8")
    return len(linhas_de_codigo(texto, onde=str(caminho)))


class SimboloAusenteError(KeyError):
    """Pediu-se um simbolo que o modulo nao define ao nivel de topo.

    Levanta, e nao devolve zero: um simbolo que desapareceu de um ficheiro
    misto e uma alteracao ao caminho de execucao, e tapa-la com um zero fazia a
    metrica continuar a responder sobre um caminho que mudou.
    """


def sloc_de_simbolo(caminho: Path, nome: str) -> int:
    """As linhas com codigo da definicao de **um** simbolo de topo.

    Serve os ficheiros `misto` — aqueles de que a vertical nova importa alguns
    simbolos e nao o resto (ver `caminho.py`). Conta a definicao inteira, do
    primeiro decorador a ultima linha do corpo, intersectada com as linhas de
    codigo do ficheiro: um no com quarenta linhas de *docstring* nao vale
    quarenta linhas de reuso.

    Um simbolo definido **dentro** de outro nao se alcanca, e e deliberado: o
    que se importa de um modulo e o que ele expoe ao nivel de topo.
    """
    texto = caminho.read_text(encoding="utf-8")
    codigo = linhas_de_codigo(texto, onde=str(caminho))
    try:
        arvore = ast.parse(texto)
    except SyntaxError as erro:  # pragma: no cover — o `linhas_de_codigo` ja falhou
        raise FonteInvalidaError(f"{caminho}: {erro}") from erro

    for instrucao in arvore.body:
        inicio, fim = _extensao(instrucao, nome)
        if inicio is None:
            continue
        return len({linha for linha in codigo if inicio <= linha <= fim})
    raise SimboloAusenteError(f"{caminho}: o simbolo `{nome}` nao esta no nivel de topo")


def _extensao(instrucao: ast.stmt, nome: str) -> tuple[int | None, int]:
    """A primeira e a ultima linha da definicao de `nome`, ou `(None, 0)`."""
    if isinstance(
        instrucao, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    ) and instrucao.name == nome:
        # **O decorador conta.** Ele e parte da definicao e alguem o escreveu;
        # comecar no `def` perdia a linha de um `@dataclass`.
        inicio = min(
            [instrucao.lineno] + [d.lineno for d in instrucao.decorator_list]
        )
        return inicio, instrucao.end_lineno or instrucao.lineno

    alvos: list[ast.expr] = []
    if isinstance(instrucao, ast.Assign):
        alvos = list(instrucao.targets)
    elif isinstance(instrucao, ast.AnnAssign):
        alvos = [instrucao.target]
    for alvo in alvos:
        if isinstance(alvo, ast.Name) and alvo.id == nome:
            return instrucao.lineno, instrucao.end_lineno or instrucao.lineno
    return None, 0
