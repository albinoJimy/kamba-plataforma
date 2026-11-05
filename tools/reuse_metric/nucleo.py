"""O criterio (d) da regra de dois: nomes de vertical no nucleo (KAM-039).

O §5.4 escreve a condicao (d) como «nenhuma excepcao no core (`grep` de nomes de
vertical em `core/` = 0)», e o bloco do KAM-039 repete-a com a exclusao de
`registry/` e dos testes.

## Um `grep` responde a pergunta errada, e mede-se que responde

Corrido a letra sobre o nucleo deste repositorio, o `grep -iE
'vendedor|servicos|assistente'` devolve **162** ocorrencias em 30 dos 110
ficheiros de nucleo. Mas a convencao da casa e explicar por extenso: **114**
dessas 162 sao prosa de comentario ou de *docstring* a dizer **porque** e que o
nucleo nao depende de uma vertical — por exemplo, o `ligacao.py` a explicar que
a tranca e por conversa e nao por vertical. Um portao que contasse essas linhas
obrigava a apagar a explicacao para ficar verde, o que e o contrario do que o
criterio quer.

E ao mesmo tempo um `grep` nao distingue as duas coisas que importam:

```text
TEXTOS = {("vendedor", "payment.confirmed"): "..."}   uma tabela por vertical
if estado["vertical"] == "vendedor": ...              uma EXCEPCAO no nucleo
```

A primeira e «verticais como configuracao», que e a tese do ADR-012. A segunda e
precisamente o que ele proibe. Um `grep` da duas ocorrencias e nao sabe a
diferenca.

## As tres classes, e qual delas e a condicao (d)

```text
prosa      comentario ou docstring                        nunca e excepcao
conteudo   um literal numa tabela, ou um identificador     configuracao; conta-se
fluxo      o nome decide um ramo: comparacao, `match`,     E A EXCEPCAO
           ou o teste de um `if`/`while`/`assert`
```

**A condicao (d) e `fluxo == 0`.** O `conteudo` conta-se, nomeia-se e vai no
relatorio, porque a fronteira entre «tabela indexada pela vertical» e «excepcao
no nucleo» e uma decisao de quem assina o ADR-012 — nao deste modulo, e nao de
quem o escreveu. O que este modulo garante e que a decisao se toma sobre uma
lista e nao sobre uma impressao.

Medido em `183e2b0` a 2026-11-05: `fluxo = 0`, `conteudo = 48`, `prosa = 114`,
sobre 110 ficheiros de nucleo. A lista das 48 esta em
`docs/evidencia/KAM-039.md`.

## E morde nas duas direccoes

Nao basta dar zero. A bateria injecta um `if ... == "servicos"` num ficheiro de
nucleo temporario e exige que o veredicto passe a vermelho, e injecta a mesma
tabela como `dict` e exige que **nao** passe. Um verificador que da zero sobre
uma arvore sa e que nao se provou a morder nao mediu nada: foi a armadilha que
este repositorio ja pagou seis vezes num ticket so.
"""

from __future__ import annotations

import ast
import fnmatch
import io
import re
import token as _token
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ClasseDeOcorrencia = Literal["prosa", "conteudo", "fluxo"]


class DeclaracaoDoNucleoInvalidaError(ValueError):
    """O `nucleo:` de `ci/regra-de-dois.yaml` esta malformado."""


@dataclass(frozen=True, slots=True)
class DeclaracaoDoNucleo:
    """O `nucleo:` de `ci/regra-de-dois.yaml`, validado."""

    padroes: tuple[str, ...]
    excluidos: tuple[str, ...]
    nomes: tuple[str, ...]

    @classmethod
    def de_mapa(cls, bruto: dict, *, onde: str) -> DeclaracaoDoNucleo:
        nucleo = bruto.get("nucleo")
        if not isinstance(nucleo, dict):
            raise DeclaracaoDoNucleoInvalidaError(f"{onde}: falta o mapa `nucleo`")
        for chave in ("padroes", "nomes"):
            valor = nucleo.get(chave)
            if not isinstance(valor, list) or not valor:
                raise DeclaracaoDoNucleoInvalidaError(
                    f"{onde}: `nucleo.{chave}` tem de ser uma lista nao vazia"
                )
        return cls(
            padroes=tuple(str(p) for p in nucleo["padroes"]),
            excluidos=tuple(str(p) for p in nucleo.get("excluidos", ()) or ()),
            nomes=tuple(str(n) for n in nucleo["nomes"]),
        )

    def padrao(self) -> re.Pattern[str]:
        """A busca do criterio: subcadeia, sem distinguir maiusculas."""
        return re.compile("|".join(re.escape(n) for n in self.nomes), re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Ocorrencia:
    """Um nome de vertical encontrado no nucleo, com a sua classe."""

    ficheiro: str
    linha: int
    classe: ClasseDeOcorrencia
    nome: str
    #: O que a ocorrencia e: `comentario`, `docstring`, `literal`, `identificador`,
    #: `comparacao`, `match`, `teste`. Vai no relatorio.
    forma: str
    trecho: str

    def como_mapa(self) -> dict:
        return {
            "ficheiro": self.ficheiro,
            "linha": self.linha,
            "classe": self.classe,
            "nome": self.nome,
            "forma": self.forma,
            "trecho": self.trecho,
        }


@dataclass(frozen=True, slots=True)
class Veredicto:
    """O resultado: as ocorrencias por classe, e se a condicao (d) passa."""

    ocorrencias: tuple[Ocorrencia, ...]
    ficheiros: int

    def de_classe(self, classe: ClasseDeOcorrencia) -> tuple[Ocorrencia, ...]:
        return tuple(o for o in self.ocorrencias if o.classe == classe)

    @property
    def fluxo(self) -> int:
        return len(self.de_classe("fluxo"))

    @property
    def conteudo(self) -> int:
        return len(self.de_classe("conteudo"))

    @property
    def prosa(self) -> int:
        return len(self.de_classe("prosa"))

    @property
    def passa(self) -> bool:
        """A condicao (d): nenhum ramo do nucleo decide por nome de vertical."""
        return self.fluxo == 0

    def como_mapa(self) -> dict:
        return {
            "criterio": (
                "docs/tecnica/02 §5.4 (d) — nenhuma excepcao de vertical no nucleo"
            ),
            "ficheiros_varridos": self.ficheiros,
            "fluxo": self.fluxo,
            "conteudo": self.conteudo,
            "prosa": self.prosa,
            "passa": self.passa,
            "ocorrencias": [
                o.como_mapa()
                for o in sorted(
                    self.ocorrencias, key=lambda o: (o.classe, o.ficheiro, o.linha)
                )
            ],
        }


def ficheiros_do_nucleo(raiz: Path, declaracao: DeclaracaoDoNucleo) -> tuple[Path, ...]:
    """Os `.py` que a declaracao poe no nucleo, ja sem os excluidos."""
    encontrados: list[Path] = []
    for ficheiro in sorted(raiz.rglob("*.py")):
        relativo = ficheiro.relative_to(raiz).as_posix()
        if not any(fnmatch.fnmatch(relativo, p) for p in declaracao.padroes):
            continue
        if any(fnmatch.fnmatch(relativo, p) for p in declaracao.excluidos):
            continue
        encontrados.append(ficheiro)
    return tuple(encontrados)


def verificar(
    raiz: Path, bruto: dict, *, onde: str = "ci/regra-de-dois.yaml"
) -> Veredicto:
    """Varre o nucleo e classifica cada ocorrencia de um nome de vertical.

    A raiz resolve-se, pela razao escrita no `medir` do `caminho.py`: em
    Windows o caminho curto e o longo sao a mesma pasta e nao sao o mesmo
    prefixo.
    """
    raiz = raiz.resolve()
    declaracao = DeclaracaoDoNucleo.de_mapa(bruto, onde=onde)
    padrao = declaracao.padrao()
    ficheiros = ficheiros_do_nucleo(raiz, declaracao)
    ocorrencias: list[Ocorrencia] = []
    for ficheiro in ficheiros:
        relativo = ficheiro.relative_to(raiz).as_posix()
        try:
            ocorrencias.extend(
                _ocorrencias_de(ficheiro.read_text(encoding="utf-8"), relativo, padrao)
            )
        except SyntaxError as erro:
            # **Nao se salta em silencio, e nao se deixa subir cru.** Saltar era
            # a forma de um ficheiro que nao compila dar `fluxo = 0` por
            # ausencia; deixar subir dava um *traceback* em vez de uma mensagem
            # (medido ao escrever o canario de mutacao). O codigo de saida 2
            # distingue «malformado» de «achado», que e o que nao se pode
            # confundir.
            raise DeclaracaoDoNucleoInvalidaError(
                f"{relativo}:{erro.lineno}: o ficheiro de nucleo nao e Python "
                f"valido e nao se pode varrer ({erro.msg})"
            ) from erro
    return Veredicto(ocorrencias=tuple(ocorrencias), ficheiros=len(ficheiros))


def _ocorrencias_de(
    texto: str, relativo: str, padrao: re.Pattern[str]
) -> tuple[Ocorrencia, ...]:
    arvore = ast.parse(texto)
    linhas = texto.splitlines()
    prosa = _posicoes_de_prosa(arvore)
    decisao = _posicoes_de_decisao(arvore, padrao)

    def trecho(linha: int) -> str:
        bruto = linhas[linha - 1].strip() if 0 < linha <= len(linhas) else ""
        return bruto[:90]

    achados: list[Ocorrencia] = []

    # 1. Comentarios e docstrings — prosa, pela via do `tokenize`, que e quem ve
    #    os comentarios (o AST deita-os fora).
    for simbolo in tokenize.generate_tokens(io.StringIO(texto).readline):
        if simbolo.type == _token.COMMENT:
            forma = "comentario"
        elif simbolo.type == _token.STRING and simbolo.start in prosa:
            forma = "docstring"
        else:
            continue
        for achado in padrao.finditer(simbolo.string):
            achados.append(
                Ocorrencia(
                    ficheiro=relativo,
                    linha=simbolo.start[0],
                    classe="prosa",
                    nome=achado.group(0).lower(),
                    forma=forma,
                    trecho=trecho(simbolo.start[0]),
                )
            )

    # 2. Literais de cadeia no codigo — `fluxo` se decidem um ramo, senao
    #    `conteudo`.
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Constant) or not isinstance(no.value, str):
            continue
        if (no.lineno, no.col_offset) in prosa:
            continue
        for achado in padrao.finditer(no.value):
            em_decisao = (no.lineno, no.col_offset) in decisao
            achados.append(
                Ocorrencia(
                    ficheiro=relativo,
                    linha=no.lineno,
                    classe="fluxo" if em_decisao else "conteudo",
                    nome=achado.group(0).lower(),
                    forma=decisao.get((no.lineno, no.col_offset), "literal"),
                    trecho=trecho(no.lineno),
                )
            )

    # 3. Identificadores — sempre `conteudo`. Um nome de simbolo nao ramifica
    #    nada por si: o que ele diz e que o nucleo **nomeia** a vertical, que e
    #    a leitura larga do criterio e nao a estrita.
    for no in ast.walk(arvore):
        for nome in _identificadores(no):
            for achado in padrao.finditer(nome):
                achados.append(
                    Ocorrencia(
                        ficheiro=relativo,
                        linha=getattr(no, "lineno", 0),
                        classe="conteudo",
                        nome=achado.group(0).lower(),
                        forma="identificador",
                        trecho=trecho(getattr(no, "lineno", 0)),
                    )
                )
    return tuple(achados)


def _identificadores(no: ast.AST) -> tuple[str, ...]:
    """Os nomes que um no declara ou usa. Nao inclui literais."""
    if isinstance(no, ast.Name):
        return (no.id,)
    if isinstance(no, ast.Attribute):
        return (no.attr,)
    if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (no.name,)
    if isinstance(no, ast.arg):
        return (no.arg,)
    if isinstance(no, ast.keyword) and no.arg:
        return (no.arg,)
    if isinstance(no, ast.alias):
        return (no.name, *((no.asname,) if no.asname else ()))
    if isinstance(no, ast.ImportFrom) and no.module:
        return (no.module,)
    return ()


def _posicoes_de_prosa(arvore: ast.AST) -> frozenset[tuple[int, int]]:
    """Igual a do `sloc.py`, e **nao se importa de la** de proposito.

    O `sloc.py` conta linhas e este classifica ocorrencias: se um dia a
    definicao de prosa divergir entre as duas perguntas, a duplicacao e o que
    permite que divirja sem partir a outra. Sao sete linhas, e a bateria mede
    que as duas concordam hoje.
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


def _posicoes_de_decisao(
    arvore: ast.AST, padrao: re.Pattern[str]
) -> dict[tuple[int, int], str]:
    """Onde e que um literal de nome de vertical **decide** um ramo.

    Os quatro contextos, e cada um tem a sua razao para estar aqui:

    * `Compare` — `x == "vendedor"`, `x in ("vendedor", ...)`. E a forma
      canonica da excepcao;
    * o `pattern` de um `match` — a mesma coisa pela gramatica nova;
    * o `test` de um `if`, `while`, `assert` ou expressao condicional — cobre
      `if "vendedor" in texto:`, que nao e um `Compare`;
    * o argumento de um `startswith`/`endswith` — e uma comparacao escrita como
      chamada, e deixa-la de fora era deixar a excepcao escrever-se assim.
    """
    marcadas: dict[tuple[int, int], str] = {}

    def marcar(subarvore: ast.AST | None, forma: str) -> None:
        if subarvore is None:
            return
        for no in ast.walk(subarvore):
            if (
                isinstance(no, ast.Constant)
                and isinstance(no.value, str)
                and padrao.search(no.value)
            ):
                marcadas.setdefault((no.lineno, no.col_offset), forma)

    # **As passagens correm da forma mais especifica para a menos**, e o
    # `setdefault` faz o resto. Com uma passagem so, o `ast.walk` visitava o
    # `If` antes do `Compare` que esta dentro dele e toda a excepcao ficava
    # etiquetada `teste` — o veredicto era o mesmo, mas o relatorio dizia menos
    # do que sabia, e e o relatorio que alguem vai ler para decidir.
    for no in ast.walk(arvore):
        if isinstance(no, ast.Compare):
            marcar(no, "comparacao")
        elif isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute):
            if no.func.attr in ("startswith", "endswith"):
                for argumento in no.args:
                    marcar(argumento, "comparacao")
    for no in ast.walk(arvore):
        if isinstance(no, ast.match_case):
            marcar(no.pattern, "match")
            marcar(no.guard, "match")
    for no in ast.walk(arvore):
        if isinstance(no, (ast.If, ast.While, ast.IfExp, ast.Assert)):
            marcar(no.test, "teste")
    return marcadas


__all__ = [
    "ClasseDeOcorrencia",
    "DeclaracaoDoNucleo",
    "DeclaracaoDoNucleoInvalidaError",
    "Ocorrencia",
    "Veredicto",
    "ficheiros_do_nucleo",
    "verificar",
]
