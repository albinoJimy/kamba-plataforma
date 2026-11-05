"""Retirar comentarios de TypeScript **sem** ser cego as cadeias de caracteres.

Esta funcao existe por um defeito medido, e o defeito foi encontrado por uma
alteracao real a aterrar na base — nao por uma revisao.

A primeira versao vivia duas vezes, uma em `enumeracao.py` e outra em
`lints.py`, e era uma expressao regular:

```python
re.sub(r"/\\*.*?\\*/", ..., fonte, flags=re.DOTALL)   # blocos
re.sub(r"//[^\\n]*", "", sem_bloco)                   # linhas
```

Ela **nao sabe o que e uma cadeia**, e as duas metades sangram:

```text
api.use("/internal/*", ...)    o `/*` dentro do literal abre um comentario
                               falso, e o proximo `*/` do ficheiro fecha-o:
                               tudo entre os dois desaparece
fetch("https://x/y")           o `//` dentro do literal apaga o resto da linha
```

**Medido a 2026-11-05**, no `services/com/src/api/interna.ts` que o KAM-178
acrescentou: o `api.use("/internal/*", …)` da linha 320 engoliu o ciclo da
linha 332, e as **sete** rotas `POST /internal/...` que ele registra ficaram
invisiveis a enumeracao — nem como item, nem como `indeciso`. O criterio 2 deste
ticket promete 100% das rotas e o *gate* dava verde sobre 24 de 31. Uma
superficie que o enumerador nao ve e pior do que uma sem caso: a segunda para o
*gate*, a primeira passa por conforme.

Nao e ironia pequena: o varrimento de comentarios entrou no ticket **pela
revisao adversarial** (achado 7, uma rota comentada a ser contada), e a
correccao abriu um buraco maior do que o que fechou. Fica escrito porque e o
argumento da casa: a revisao produz achados, a execucao produz a verdade.

## O que esta funcao faz, e o que nao faz

Um varrimento por caracteres, com tres estados — fora, dentro de literal,
dentro de comentario. Os comentarios saem (o de bloco deixa as suas mudancas de
linha, porque o achado leva `ficheiro:linha` e um numero errado manda quem o le
para o sitio errado); as cadeias passam **intactas**, escapes incluidos.

**O que nao trata**, dito em vez de descoberto:

* uma crase dentro de `${…}` de um literal de modelo — `` `a${`b`}c` `` — conta
  como fecho do literal. E raro e o erro e para o lado seguro: o varrimento
  volta ao estado «fora», onde no maximo deixa passar um comentario, nunca
  esconde codigo.
* um literal de expressao regular (`/[/]/`) nao e estado proprio. Um `/` que nao
  seja seguido de `/` ou de `*` passa como caracter comum, que e o que basta
  para os casos deste repositorio.
"""

from __future__ import annotations

_FECHOS = "\"'`"


def sem_comentarios_ts(fonte: str) -> str:
    """`fonte` sem `//` nem `/* */`, com as linhas e as cadeias preservadas."""
    saida: list[str] = []
    i = 0
    n = len(fonte)
    while i < n:
        caracter = fonte[i]
        if caracter in _FECHOS:
            i = _copiar_literal(fonte, i, saida)
            continue
        if caracter == "/" and i + 1 < n:
            seguinte = fonte[i + 1]
            if seguinte == "/":
                while i < n and fonte[i] != "\n":
                    i += 1
                continue
            if seguinte == "*":
                fim = fonte.find("*/", i + 2)
                bloco = fonte[i:] if fim == -1 else fonte[i : fim + 2]
                saida.append("\n" * bloco.count("\n"))
                i += len(bloco)
                continue
        saida.append(caracter)
        i += 1
    return "".join(saida)


def _copiar_literal(fonte: str, i: int, saida: list[str]) -> int:
    """Copia o literal que comeca em `i` e devolve o indice depois dele."""
    fecho = fonte[i]
    saida.append(fecho)
    i += 1
    n = len(fonte)
    while i < n:
        caracter = fonte[i]
        saida.append(caracter)
        i += 1
        if caracter == "\\" and i < n:
            # O escape leva o caracter seguinte consigo: `"\\""` e uma cadeia
            # de um caracter e nao duas cadeias vazias.
            saida.append(fonte[i])
            i += 1
            continue
        if caracter == fecho:
            break
    return i
