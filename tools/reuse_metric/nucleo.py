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

## O numero que esta linha afirmava estava errado, e vale dizer porque

Ate 2026-11-06 lia-se aqui «medido em `183e2b0` a 2026-11-05: `fluxo = 0`,
`conteudo = 48`, `prosa = 114`». **O `fluxo = 0` era falso.** O `183e2b0` e
anterior ao afiar que o proprio KAM-039 fez a este modulo — a passagem que
segue uma **constante de modulo** lida num teste (ver o `FORMAS_DE_DOMINIO`) —,
e com ela a corrida passou a dar `fluxo = 1`: o `AO_DONO` do
`eventos/handlers.py`. O numero ficou a afirmar o presente dentro do
instrumento que o mede, que e a classe de defeito que esta casa paga mais
vezes. Fica escrito em vez de apagado, porque uma linha corrigida em silencio
nao ensina nada a quem passar aqui a seguir.

Medido a 2026-11-06, depois de a notificacao ao dono sair do nucleo para
`subscriptions[].notifica` do `registry/`: `fluxo = 0`, `dominio = 1`,
`conteudo = 45`, `prosa = 118`, sobre 110 ficheiros de nucleo, saida **0**. A
lista do `conteudo` e as duas saidas medidas estao em
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

ClasseDeOcorrencia = Literal["prosa", "conteudo", "dominio", "fluxo"]


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
    def dominio(self) -> int:
        """Ramos que verificam que a vertical e **conhecida**. Nao sao excepcao."""
        return len(self.de_classe("dominio"))

    @property
    def conteudo(self) -> int:
        return len(self.de_classe("conteudo"))

    @property
    def prosa(self) -> int:
        return len(self.de_classe("prosa"))

    @property
    def passa(self) -> bool:
        """A condicao (d): nenhum ramo do nucleo **despacha** por vertical.

        `fluxo == 0`, e nao `fluxo + dominio == 0`: uma lista fechada de
        verticais permitidas nao distingue entre elas, e o criterio 5 do KAM-014
        exige-a por escrito. Ver `FORMAS_DE_DOMINIO`.
        """
        return self.fluxo == 0

    def como_mapa(self) -> dict:
        return {
            "criterio": (
                "docs/tecnica/02 §5.4 (d) — nenhuma excepcao de vertical no nucleo"
            ),
            "ficheiros_varridos": self.ficheiros,
            "fluxo": self.fluxo,
            "dominio": self.dominio,
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
            forma = decisao.get((no.lineno, no.col_offset))
            achados.append(
                Ocorrencia(
                    ficheiro=relativo,
                    linha=no.lineno,
                    classe=_classe_de(forma),
                    nome=achado.group(0).lower(),
                    forma=forma or "literal",
                    trecho=trecho(no.lineno),
                )
            )

    # 3. **Referencias a uma constante de modulo que leva nomes de vertical.**
    #    E a passagem que faltava, e sem ela o verificador nao via o idioma
    #    desta casa: o `contexto.py:191` — `if valores["vertical"] not in
    #    VERTICAIS: raise` — nao tem literal nenhum, e a constante da linha 71
    #    nao esta num contexto de decisao. O identificador `VERTICAIS` tambem
    #    nao casa com o padrao (nao contem «vendedor» nem «servicos»), pelo que
    #    a linha 191 nao produzia **ocorrencia nenhuma**. Achado da revisao
    #    adversarial, e o mais serio dela.
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Name):
            continue
        forma = decisao.get((no.lineno, no.col_offset))
        if forma is None:
            continue
        achados.append(
            Ocorrencia(
                ficheiro=relativo,
                linha=no.lineno,
                classe=_classe_de(forma),
                nome=no.id.lower(),
                forma=forma,
                trecho=trecho(no.lineno),
            )
        )

    # 4. Identificadores — sempre `conteudo`. Um nome de simbolo nao ramifica
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


#: As formas de `fluxo` que sao **validacao do dominio** e nao despacho: o
#: nucleo verifica que a vertical e **conhecida**, e trata todas por igual.
#:
#: E a correccao do achado mais serio da revisao adversarial, e vale escrever
#: porque o primeiro desenho errava nas duas direccoes. O verificador so marcava
#: literais escritos **dentro** da expressao de decisao, e o idioma desta casa e
#: a constante de modulo — pelo que o `contexto.py`, um ficheiro de nucleo,
#: tinha isto a passar como `conteudo`:
#:
#: ```python
#: VERTICAIS: Final = ("vendedor", "servicos")      # linha 71: `conteudo`
#: if valores["vertical"] not in VERTICAIS:         # linha 191: NADA
#:     raise InvocacaoInvalidaError(...)
#: ```
#:
#: Isso e, a letra, «o nucleo decide um ramo por nome de vertical», e os seis
#: canarios de mutacao mediam a forma inline que a arvore **nao** usa.
#:
#: Mas pô-lo a reprovar tornava o criterio (d) impossivel de satisfazer, e por
#: uma razao boa: uma lista **fechada** de verticais permitidas nao distingue
#: entre elas — e a validacao do dominio de um campo, e o criterio 5 do KAM-014
#: exige-a por escrito («`assistente` por igualdade nao via `assistente_v2`»).
#: Despacho e quando o nucleo faz coisa **diferente** segundo **qual** vertical.
#:
#: O discriminante e mecanico: uma pertenca (`in` / `not in`) a um conjunto com
#: **dois ou mais** nomes de vertical e dominio; uma igualdade, um subconjunto
#: proprio, ou um **mapa indexado** pela vertical — onde os valores diferem por
#: construcao — e despacho.
FORMAS_DE_DOMINIO: Final = frozenset({"dominio_fechado"})


def _classe_de(forma: str | None) -> ClasseDeOcorrencia:
    """A classe de uma ocorrencia, a partir da forma com que ela decide.

    Fora de um contexto de decisao e `conteudo` — configuracao, que se conta e
    se nomeia. Dentro, e `dominio` quando o nucleo so verifica que a vertical e
    **conhecida**, e `fluxo` quando ele faz coisa diferente segundo **qual** —
    que e a excepcao que o criterio (d) proibe.
    """
    if forma is None:
        return "conteudo"
    if forma in FORMAS_DE_DOMINIO:
        return "dominio"
    return "fluxo"


def _constantes_com_verticais(
    arvore: ast.Module, padrao: re.Pattern[str]
) -> dict[str, tuple[str, int]]:
    """`nome -> (forma, quantos nomes de vertical)` das constantes de topo.

    Resolve a indirecção que derrotava o verificador. A `forma` e `mapa` quando
    a constante e um `dict` — nesse caso os valores diferem por vertical por
    construcao, e nenhuma aritmetica de cardinalidade a salva — e `membros`
    quando e um conjunto, tuplo ou lista.
    """
    encontradas: dict[str, tuple[str, int]] = {}
    for instrucao in arvore.body:
        alvos: list[ast.expr] = []
        if isinstance(instrucao, ast.Assign):
            alvos = list(instrucao.targets)
        elif isinstance(instrucao, ast.AnnAssign):
            alvos = [instrucao.target]
        if not alvos or instrucao.value is None:  # type: ignore[union-attr]
            continue
        valor = instrucao.value  # type: ignore[union-attr]
        nomes = {
            no.value.lower()
            for no in ast.walk(valor)
            if isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and padrao.fullmatch(no.value)
        }
        if not nomes:
            continue
        forma = "mapa" if isinstance(valor, ast.Dict) else "membros"
        for alvo in alvos:
            if isinstance(alvo, ast.Name):
                encontradas[alvo.id] = (forma, len(nomes))
    return encontradas


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

    **E a referencia a uma constante de modulo que leve nomes de vertical**, que
    e o idioma desta casa e o que derrotava a primeira versao — ver o
    `FORMAS_DE_DOMINIO`.

    O nome compara-se por `fullmatch` e nao por subcadeia: um
    `if tipo == "servicos_de_terceiros"` nao decide por vertical nenhuma, e a
    primeira versao marcava-o (achado 4 da revisao adversarial). A subcadeia
    continua a valer para o `conteudo` e para a `prosa`, onde a pergunta e se o
    nucleo **nomeia** uma vertical, e nao se decide por ela.
    """
    marcadas: dict[tuple[int, int], str] = {}
    constantes = (
        _constantes_com_verticais(arvore, padrao)
        if isinstance(arvore, ast.Module)
        else {}
    )

    def nomes_em(subarvore: ast.AST | None) -> int:
        """Quantos nomes de vertical distintos este lado da comparacao traz."""
        if subarvore is None:
            return 0
        achados: set[str] = set()
        for no in ast.walk(subarvore):
            if (
                isinstance(no, ast.Constant)
                and isinstance(no.value, str)
                and padrao.fullmatch(no.value)
            ):
                achados.add(no.value.lower())
            elif isinstance(no, ast.Name) and no.id in constantes:
                tipo, quantos = constantes[no.id]
                if tipo == "membros":
                    # Conta a cardinalidade da constante, que e o que decide se
                    # o conjunto e o dominio inteiro ou um subconjunto proprio.
                    achados.update(str(i) for i in range(quantos))
        return len(achados)

    def marcar(subarvore: ast.AST | None, forma: str, *, dominio: bool) -> None:
        if subarvore is None:
            return
        for no in ast.walk(subarvore):
            if (
                isinstance(no, ast.Constant)
                and isinstance(no.value, str)
                and padrao.fullmatch(no.value)
            ):
                marcadas.setdefault(
                    (no.lineno, no.col_offset),
                    "dominio_fechado" if dominio else forma,
                )
            elif isinstance(no, ast.Name) and no.id in constantes:
                tipo, quantos = constantes[no.id]
                # **Um mapa indexado pela vertical e despacho seja qual for a
                # cardinalidade**: os valores diferem por construcao, e nenhuma
                # aritmetica de cardinalidade o salva. Um conjunto com dois ou
                # mais nomes, no lado do contentor de uma pertenca, e dominio.
                #
                # **Menos num `assert`**, onde nem um mapa despacha: uma
                # asserçao nao muda o que o codigo faz a nenhuma vertical, e
                # uma asserçao de completude sobre a tabela — «ela tem as tres»
                # — e o contrario de tratar uma delas de modo especial.
                e_dominio = dominio and (
                    forma == "assercao" or (tipo == "membros" and quantos >= 2)
                )
                marcadas.setdefault(
                    (no.lineno, no.col_offset),
                    "dominio_fechado" if e_dominio else f"{forma}_por_constante",
                )

    def marcar_comparacao(no: ast.Compare) -> None:
        """Os dois lados de uma comparacao **nao** sao a mesma coisa.

        Numa pertenca, o dominio esta no lado do **contentor**: um
        `if vertical in VERTICAIS` valida o dominio, e um
        `if "vendedor" in texto` procura uma subcadeia num texto — o nome esta
        do lado da **agulha**, e e despacho. A primeira versao marcava os dois
        lados com a mesma etiqueta e punha o segundo em `dominio`, o que o
        deixava passar: achado da revisao adversarial pelo lado dos falsos
        negativos, e do canario `test_subcadeia_num_teste` pelo outro.
        """
        pertenca = any(isinstance(op, (ast.In, ast.NotIn)) for op in no.ops)
        if not pertenca:
            marcar(no, "comparacao", dominio=False)
            return
        contentor_e_dominio = any(nomes_em(c) >= 2 for c in no.comparators)
        marcar(no.left, "comparacao", dominio=False)
        for comparador in no.comparators:
            marcar(comparador, "comparacao", dominio=contentor_e_dominio)

    # **As passagens correm da forma mais especifica para a menos**, e o
    # `setdefault` faz o resto. Com uma passagem so, o `ast.walk` visitava o
    # `If` antes do `Compare` que esta dentro dele e toda a excepcao ficava
    # etiquetada `teste` — o veredicto era o mesmo, mas o relatorio dizia menos
    # do que sabia, e e o relatorio que alguem vai ler para decidir.
    for no in ast.walk(arvore):
        # **Um `assert` nunca despacha**: e uma auto-verificacao, e uma asserçao
        # de completude sobre uma tabela de configuracao — «a tabela tem as tres
        # verticais» — e o contrario de tratar uma delas de modo especial.
        if isinstance(no, ast.Assert):
            marcar(no.test, "assercao", dominio=True)
    for no in ast.walk(arvore):
        if isinstance(no, ast.Compare):
            marcar_comparacao(no)
        elif isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute):
            if no.func.attr in ("startswith", "endswith"):
                for argumento in no.args:
                    marcar(argumento, "comparacao", dominio=False)
    for no in ast.walk(arvore):
        if isinstance(no, ast.match_case):
            marcar(no.pattern, "match", dominio=False)
            marcar(no.guard, "match", dominio=False)
    for no in ast.walk(arvore):
        if isinstance(no, (ast.If, ast.While, ast.IfExp)):
            marcar(no.test, "teste", dominio=False)
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
