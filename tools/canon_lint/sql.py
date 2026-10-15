"""Leitura de DDL PostgreSQL: so o suficiente para tirar nomes, e falha no resto.

**Nao e um parser de SQL.** Tokeniza, parte em instrucoes, e reconhece as formas
que introduzem os nomes que o gate 3b verifica — tabelas, colunas, valores de
`CHECK`, esquemas, tipos, papeis, unicidades. Uma instrucao cuja forma nao
conhece **nao e saltada**: e devolvida como `desconhecida`, e quem chama falha.

Porque nao uma biblioteca: o ticket admite uma («o parser de DDL usa biblioteca
de licenca permitida»), mas as ferramentas que impoem gates neste repositorio
correm so com a biblioteca padrao, para funcionarem num clone antes de qualquer
instalacao (`tools/kamba_yaml.py`, ADR-L001 §6). Um parser completo tambem nao
resolvia o problema real, que e o SQL **nao literal**: uma *f-string* nao se
analisa com parser nenhum.

O preco esta dito:

* um bloco `$$ … $$` so passa se nao tiver `CREATE` nem `ALTER` la dentro — o
  DDL dinamico (`DO $$ BEGIN CREATE ROLE … END $$`) falha em vez de ser saltado;
* `CREATE TABLE … AS`, `SELECT … INTO` e `CREATE SCHEMA … CREATE …` nao dao
  colunas e sao devolvidos como desconhecidos;
* as colunas de uma vista (`CREATE VIEW … AS SELECT … AS x`) e os nomes de
  indices, de restricoes e de politicas **nao** sao verificados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class SqlIlegivel(ValueError):
    """O texto nao se consegue tokenizar (cadeia ou comentario por fechar)."""


@dataclass(frozen=True)
class Token:
    tipo: str  # ident | str | num | punct | dollar
    valor: str
    linha: int  # 1-based, dentro do texto SQL


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_DOLLAR = re.compile(r"\$[A-Za-z_]*\$")


def tokenizar(texto: str) -> list[Token]:
    tokens: list[Token] = []
    i, n, linha = 0, len(texto), 1
    while i < n:
        c = texto[i]
        if c == "\n":
            linha += 1
            i += 1
        elif c.isspace():
            i += 1
        elif texto.startswith("--", i):
            fim = texto.find("\n", i)
            i = n if fim == -1 else fim
        elif texto.startswith("/*", i):
            fim = texto.find("*/", i + 2)
            if fim == -1:
                raise SqlIlegivel(f"comentario `/*` por fechar (linha {linha})")
            linha += texto.count("\n", i, fim)
            i = fim + 2
        elif c == "'":
            # `E'…'`: a barra invertida escapa. Sem isto, `E'a\'b'` fechava a
            # cadeia a meio e o DDL seguinte era lido como texto ate a proxima
            # plica — uma tabela inteira desaparecia dentro de um comentario.
            escapes = bool(tokens) and tokens[-1] == Token("ident", "e", linha) and texto[i - 1] in "eE"
            if escapes:
                tokens.pop()
            j, partes, inicio = i + 1, [], linha
            while True:
                if j >= n:
                    raise SqlIlegivel(f"cadeia por fechar (linha {inicio})")
                if escapes and texto[j] == "\\" and j + 1 < n:
                    partes.append(texto[j + 1])
                    j += 2
                    continue
                if texto[j] == "'":
                    if j + 1 < n and texto[j + 1] == "'":
                        partes.append("'")
                        j += 2
                        continue
                    break
                if texto[j] == "\n":
                    linha += 1
                partes.append(texto[j])
                j += 1
            tokens.append(Token("str", "".join(partes), inicio))
            i = j + 1
        elif c == '"':
            fim = texto.find('"', i + 1)
            if fim == -1:
                raise SqlIlegivel(f"identificador entre aspas por fechar (linha {linha})")
            tokens.append(Token("ident", texto[i + 1 : fim], linha))
            i = fim + 1
        elif c == "$" and _DOLLAR.match(texto, i):
            marca = _DOLLAR.match(texto, i).group(0)
            fim = texto.find(marca, i + len(marca))
            if fim == -1:
                raise SqlIlegivel(f"bloco `{marca}` por fechar (linha {linha})")
            tokens.append(Token("dollar", texto[i + len(marca) : fim], linha))
            linha += texto.count("\n", i, fim)
            i = fim + len(marca)
        elif _IDENT.match(texto, i):
            achado = _IDENT.match(texto, i)
            tokens.append(Token("ident", achado.group(0).lower(), linha))
            i = achado.end()
        elif _NUM.match(texto, i):
            achado = _NUM.match(texto, i)
            tokens.append(Token("num", achado.group(0), linha))
            i = achado.end()
        else:
            tokens.append(Token("punct", c, linha))
            i += 1
    return tokens


def instrucoes(tokens: list[Token]) -> list[list[Token]]:
    """Parte nos `;`. Uma instrucao vazia nao conta."""
    resultado: list[list[Token]] = []
    actual: list[Token] = []
    for token in tokens:
        if token.tipo == "punct" and token.valor == ";":
            if actual:
                resultado.append(actual)
            actual = []
        else:
            actual.append(token)
    if actual:
        resultado.append(actual)
    return resultado


# ------------------------------------------------------------------ modelo


@dataclass
class Check:
    tabela: str
    coluna: str
    valores: list[str]
    fechado: bool  # True: a restricao inteira e a lista de valores — e o dominio
    linha: int


@dataclass
class Objectos:
    """O que uma instrucao (ou um ficheiro) introduz."""

    esquemas: list[tuple[str, int]] = field(default_factory=list)
    tabelas: list[tuple[str, str, int]] = field(default_factory=list)  # (esquema, nome, linha)
    colunas: list[tuple[str, str, int]] = field(default_factory=list)  # (tabela, coluna, linha)
    #: (tabela, coluna, identificadores do tipo, linha) — para ligar um ENUM a coluna
    tipos_de_coluna: list[tuple[str, str, list[str], int]] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    #: (tabela, identificadores presentes na expressao, linha) de cada CHECK,
    #: tenha ou nao dado valores: e o que deixa falhar quando uma coluna com
    #: dominio aparece numa restricao que nao se conseguiu ler.
    checks_brutos: list[tuple[str, list[str], int]] = field(default_factory=list)
    unicidades: list[tuple[str, list[str], int]] = field(default_factory=list)
    papeis: list[tuple[str, int]] = field(default_factory=list)
    tipos: list[tuple[str, int]] = field(default_factory=list)  # CREATE TYPE / DOMAIN
    enums: dict[str, tuple[list[str], int]] = field(default_factory=dict)
    desconhecidas: list[tuple[str, int]] = field(default_factory=list)
    opacos: int = 0  # blocos `$$ … $$` aceites sem leitura de nivel 2
    instrucoes: int = 0

    def juntar(self, outro: "Objectos", desloca: int = 0) -> None:
        """Acrescenta `outro`, somando `desloca` a cada numero de linha."""

        def d(linha: int) -> int:
            return linha + desloca

        self.esquemas += [(n, d(l)) for n, l in outro.esquemas]
        self.tabelas += [(e, n, d(l)) for e, n, l in outro.tabelas]
        self.colunas += [(t, c, d(l)) for t, c, l in outro.colunas]
        self.tipos_de_coluna += [(t, c, i, d(l)) for t, c, i, l in outro.tipos_de_coluna]
        self.checks += [Check(c.tabela, c.coluna, c.valores, c.fechado, d(c.linha)) for c in outro.checks]
        self.checks_brutos += [(t, i, d(l)) for t, i, l in outro.checks_brutos]
        self.unicidades += [(t, c, d(l)) for t, c, l in outro.unicidades]
        self.papeis += [(n, d(l)) for n, l in outro.papeis]
        self.tipos += [(n, d(l)) for n, l in outro.tipos]
        for nome, (valores, linha) in outro.enums.items():
            self.enums[nome] = (valores, d(linha))
        self.desconhecidas += [(f, d(l)) for f, l in outro.desconhecidas]
        self.opacos += outro.opacos
        self.instrucoes += outro.instrucoes


#: Formas reconhecidas que **nao** introduzem tabela, coluna nem valor de CHECK.
#: A lista e fechada: o que nao esta aqui nem tem tratamento proprio e
#: `desconhecida`, e o gate falha.
_SEM_NOMES = {
    ("comment",), ("grant",), ("revoke",), ("drop",), ("set",), ("reset",),
    ("insert",), ("update",), ("delete",), ("select",), ("with",), ("do",),
    ("lock",), ("truncate",), ("analyze",), ("vacuum",), ("reindex",),
    ("refresh",), ("security",), ("begin",), ("commit",), ("notify",),
    ("create", "index"), ("create", "policy"), ("create", "function"),
    ("create", "procedure"), ("create", "trigger"), ("create", "extension"),
    ("create", "sequence"), ("create", "rule"), ("create", "aggregate"),
    ("create", "publication"), ("create", "collation"), ("create", "operator"),
    ("create", "statistics"), ("create", "event"), ("create", "cast"),
    ("alter", "policy"), ("alter", "default"), ("alter", "schema"),
    ("alter", "role"), ("alter", "function"), ("alter", "index"),
    ("alter", "sequence"), ("alter", "view"),
    ("alter", "database"), ("alter", "extension"), ("alter", "trigger"),
    ("alter", "procedure"), ("alter", "materialized"),
}

_MODIFICADORES = {
    "or", "replace", "unique", "temp", "temporary", "unlogged", "global",
    "local", "recursive", "concurrently", "constraint",
}

_INICIO_DE_RESTRICAO = {"constraint", "primary", "unique", "check", "foreign", "exclude", "like"}

#: Palavras que aparecem numa expressao de CHECK e nao sao colunas. Sem isto,
#: `coluna NOT IN ('a')` lia `not` como a coluna comparada.
_PALAVRAS = {
    "and", "or", "not", "is", "null", "in", "like", "ilike", "between", "case",
    "when", "then", "else", "end", "true", "false", "any", "all", "array",
    "exists", "similar", "to", "some", "distinct", "from",
}

#: Palavras que continuam um nome de tipo depois de `::` (`character varying`,
#: `double precision`, `timestamp with time zone`).
_CONTINUA_TIPO = {"varying", "precision", "with", "without", "time", "zone"}

#: DDL dentro de um bloco `$$`: o que faz o bloco falhar em vez de ficar opaco.
_DDL_EM_BLOCO = {"create", "alter"}
_DDL_EM_TEXTO = re.compile(r"\b(?:create|alter)\b", re.IGNORECASE)


def _e(token: Token | None, *valores: str) -> bool:
    return token is not None and token.tipo == "ident" and token.valor in valores


def _p(token: Token | None, valor: str) -> bool:
    return token is not None and token.tipo == "punct" and token.valor == valor


def _saltar(tokens: list[Token], i: int, *palavras: str) -> int:
    """Avanca sobre uma sequencia exacta de palavras, se la estiver."""
    j = i
    for palavra in palavras:
        if j < len(tokens) and _e(tokens[j], palavra):
            j += 1
        else:
            return i
    return j


def _nome_qualificado(tokens: list[Token], i: int) -> tuple[str, str, int]:
    """Le `[esquema.]nome` a partir de `i`. Devolve (esquema, nome, seguinte)."""
    if i >= len(tokens) or tokens[i].tipo != "ident":
        raise SqlIlegivel(f"esperava um nome (linha {tokens[i - 1].linha if i else 1})")
    esquema, nome, j = "", tokens[i].valor, i + 1
    if j + 1 < len(tokens) and _p(tokens[j], ".") and tokens[j + 1].tipo == "ident":
        esquema, nome, j = nome, tokens[j + 1].valor, j + 2
    return esquema, nome, j


def _grupo(tokens: list[Token], i: int) -> tuple[list[Token], int]:
    """Com `tokens[i] == "("`, devolve o interior e o indice a seguir ao `)`."""
    profundidade, j = 0, i
    while j < len(tokens):
        if _p(tokens[j], "("):
            profundidade += 1
        elif _p(tokens[j], ")"):
            profundidade -= 1
            if profundidade == 0:
                return tokens[i + 1 : j], j + 1
        j += 1
    raise SqlIlegivel(f"parentese por fechar (linha {tokens[i].linha})")


def _partir_por_virgulas(tokens: list[Token]) -> list[list[Token]]:
    partes: list[list[Token]] = []
    actual: list[Token] = []
    profundidade = 0
    for token in tokens:
        if _p(token, "(") or _p(token, "["):
            profundidade += 1
        elif _p(token, ")") or _p(token, "]"):
            profundidade -= 1
        if _p(token, ",") and profundidade == 0:
            partes.append(actual)
            actual = []
        else:
            actual.append(token)
    if actual:
        partes.append(actual)
    return partes


def _sem_casts(tokens: list[Token]) -> list[Token]:
    """Tira os `::tipo`, incluindo `::character varying(20)[]` e `::esquema.tipo`.

    O `pg_get_constraintdef` — e portanto o `pg_dump` — escreve
    `((estado)::text = ANY ((ARRAY['a'::character varying])::text[]))`. Sem tirar
    os casts, a coluna comparada era lida como `text` e o dominio nao se
    encontrava: o CHECK passava sem `restrito`.
    """
    saida: list[Token] = []
    i = 0
    while i < len(tokens):
        if _p(tokens[i], ":") and i + 1 < len(tokens) and _p(tokens[i + 1], ":"):
            i += 2
            if i < len(tokens) and tokens[i].tipo == "ident":
                i += 1
                if i + 1 < len(tokens) and _p(tokens[i], ".") and tokens[i + 1].tipo == "ident":
                    i += 2
                while i < len(tokens) and _e(tokens[i], *_CONTINUA_TIPO):
                    i += 1
                if i < len(tokens) and _p(tokens[i], "(") and i + 1 < len(tokens) and tokens[i + 1].tipo == "num":
                    _, i = _grupo(tokens, i)
                while i + 1 < len(tokens) and _p(tokens[i], "[") and _p(tokens[i + 1], "]"):
                    i += 2
            continue
        saida.append(tokens[i])
        i += 1
    return saida


def _sem_parenteses_de_um_nome(tokens: list[Token]) -> list[Token]:
    """`(estado)` → `estado`, quando nao e a lista de argumentos de uma funcao."""
    mudou = True
    while mudou:
        mudou = False
        for i in range(len(tokens) - 2):
            if (
                _p(tokens[i], "(")
                and tokens[i + 1].tipo == "ident"
                and tokens[i + 1].valor not in _PALAVRAS
                and _p(tokens[i + 2], ")")
            ):
                antes = tokens[i - 1] if i else None
                if antes is not None and antes.tipo == "ident" and antes.valor not in _PALAVRAS:
                    continue  # f(x): argumento de funcao
                tokens = tokens[:i] + [tokens[i + 1]] + tokens[i + 3 :]
                mudou = True
                break
    return tokens


def _so_cadeias(tokens: list[Token]) -> list[str] | None:
    """`'a', 'b', 'c'` → os valores; outra coisa qualquer → None."""
    valores = []
    for parte in _partir_por_virgulas(tokens):
        if len(parte) != 1 or parte[0].tipo != "str":
            return None
        valores.append(parte[0].valor)
    return valores or None


def _descascar(tokens: list[Token]) -> list[Token]:
    """Tira parenteses exteriores redundantes: `((a IN (...)))` → `a IN (...)`."""
    while tokens and _p(tokens[0], "("):
        interior, seguinte = _grupo(tokens, 0)
        if seguinte != len(tokens):
            break
        tokens = interior
    return tokens


def _partir_por_or(tokens: list[Token]) -> list[list[Token]]:
    partes: list[list[Token]] = []
    actual: list[Token] = []
    profundidade = 0
    for token in tokens:
        if _p(token, "("):
            profundidade += 1
        elif _p(token, ")"):
            profundidade -= 1
        if _e(token, "or") and profundidade == 0:
            partes.append(actual)
            actual = []
        else:
            actual.append(token)
    partes.append(actual)
    return partes


def analisar_check(interior: list[Token], tabela: str, linha: int) -> list[Check]:
    """Tira de uma expressao de `CHECK` os valores com que as colunas se comparam.

    Dois casos, e a diferenca importa:

    * a restricao **inteira** e `coluna IN ('a','b')`, `coluna = ANY (ARRAY[…])`
      ou `coluna = 'a' OR coluna = 'b'`: e o dominio fechado da coluna, e
      compara-se por igualdade com o dicionario — um estado a mais ou a menos
      falha;
    * a comparacao esta **dentro** de uma expressao maior
      (`tipo <> 'x' OR metodo IN ('a','b')`): a lista nao e o dominio, e so se
      exige que cada valor **pertenca** a ele.
    """
    corpo = _descascar(_sem_parenteses_de_um_nome(_sem_casts(interior)))
    resultado: list[Check] = []

    def lista_em(i: int) -> tuple[list[str] | None, int]:
        """Com `corpo[i]` logo a seguir a coluna: `IN (…)` ou `= ANY (ARRAY[…])`."""
        if _e(corpo[i] if i < len(corpo) else None, "in") and i + 1 < len(corpo) and _p(corpo[i + 1], "("):
            dentro, fim = _grupo(corpo, i + 1)
            return _so_cadeias(dentro), fim
        if (
            i + 2 < len(corpo)
            and _p(corpo[i], "=")
            and _e(corpo[i + 1], "any")
            and _p(corpo[i + 2], "(")
        ):
            dentro, fim = _grupo(corpo, i + 2)
            dentro = _descascar(dentro)
            if dentro and _e(dentro[0], "array") and len(dentro) > 2 and _p(dentro[1], "["):
                fecho = max(k for k, t in enumerate(dentro) if _p(t, "]"))
                if fecho == len(dentro) - 1:
                    return _so_cadeias(dentro[2:fecho]), fim
        return None, i

    def e_coluna(i: int) -> bool:
        token = corpo[i]
        anterior = corpo[i - 1] if i else None
        return (
            token.tipo == "ident"
            and token.valor not in _PALAVRAS
            and not _p(anterior, ".")
            and not (i + 1 < len(corpo) and _p(corpo[i + 1], "("))
        )

    # caso 1a: a restricao inteira e uma lista
    if corpo and e_coluna(0):
        valores, fim = lista_em(1)
        if valores is not None and fim == len(corpo):
            return [Check(tabela, corpo[0].valor, valores, True, linha)]

    # caso 1b: a restricao inteira e `c = 'a' OR c = 'b' OR …`, sempre a mesma coluna
    ramos = [_descascar(r) for r in _partir_por_or(corpo)]
    if len(ramos) > 1 and all(
        len(r) == 3 and r[0].tipo == "ident" and _p(r[1], "=") and r[2].tipo == "str" for r in ramos
    ):
        colunas = {r[0].valor for r in ramos}
        if len(colunas) == 1 and ramos[0][0].valor not in _PALAVRAS:
            return [Check(tabela, ramos[0][0].valor, [r[2].valor for r in ramos], True, linha)]

    # caso 2: comparacoes soltas dentro de uma expressao maior
    i = 0
    while i < len(corpo):
        token = corpo[i]
        if e_coluna(i):
            valores, fim = lista_em(i + 1)
            if valores is not None:
                resultado.append(Check(tabela, token.valor, valores, False, token.linha))
                i = fim
                continue
            # coluna = 'x' | coluna <> 'x' | coluna != 'x'
            j = i + 1
            if j < len(corpo) and _p(corpo[j], "="):
                j += 1
            elif j + 1 < len(corpo) and (
                (_p(corpo[j], "<") and _p(corpo[j + 1], ">"))
                or (_p(corpo[j], "!") and _p(corpo[j + 1], "="))
            ):
                j += 2
            else:
                j = -1
            if j > 0 and j < len(corpo) and corpo[j].tipo == "str" and corpo[j].valor.strip():
                resultado.append(Check(tabela, token.valor, [corpo[j].valor], False, token.linha))
                i = j + 1
                continue
        i += 1
    return resultado


def _checks_de(tokens: list[Token], tabela: str, objectos: Objectos) -> None:
    i = 0
    while i < len(tokens):
        if _e(tokens[i], "check") and i + 1 < len(tokens) and _p(tokens[i + 1], "("):
            interior, seguinte = _grupo(tokens, i + 1)
            objectos.checks += analisar_check(interior, tabela, tokens[i].linha)
            objectos.checks_brutos.append(
                (tabela, [t.valor for t in interior if t.tipo == "ident"], tokens[i].linha)
            )
            i = seguinte
        else:
            i += 1


def _unicidade_de(tokens: list[Token]) -> list[str] | None:
    """As colunas de um `UNIQUE (…)` ou `PRIMARY KEY (…)` de tabela."""
    i = 0
    if _e(tokens[0] if tokens else None, "constraint"):
        i = 2
    if i < len(tokens) and _e(tokens[i], "unique"):
        i += 1
    elif i + 1 < len(tokens) and _e(tokens[i], "primary") and _e(tokens[i + 1], "key"):
        i += 2
    else:
        return None
    i = _saltar(tokens, i, "nulls", "not", "distinct")
    if i < len(tokens) and _p(tokens[i], "("):
        interior, _ = _grupo(tokens, i)
        return [parte[0].valor for parte in _partir_por_virgulas(interior) if parte and parte[0].tipo == "ident"]
    return None


def _coluna(tabela: str, elemento: list[Token], objectos: Objectos) -> None:
    nome = elemento[0]
    objectos.colunas.append((tabela, nome.valor, nome.linha))
    # Os identificadores do tipo: o que vem entre o nome e a primeira restricao.
    tipo: list[str] = []
    for token in elemento[1:]:
        if token.tipo == "ident" and token.valor in (
            "constraint", "check", "not", "null", "default", "references", "primary",
            "unique", "generated", "collate",
        ):
            break
        if token.tipo == "ident":
            tipo.append(token.valor)
    objectos.tipos_de_coluna.append((tabela, nome.valor, tipo, nome.linha))
    if any(_e(t, "unique") for t in elemento[1:]):
        objectos.unicidades.append((tabela, [nome.valor], nome.linha))


def _corpo_de_tabela(interior: list[Token], tabela: str, objectos: Objectos) -> None:
    for elemento in _partir_por_virgulas(interior):
        if not elemento:
            continue
        primeiro = elemento[0]
        if primeiro.tipo != "ident":
            raise SqlIlegivel(f"elemento de tabela que nao comeca por um nome (linha {primeiro.linha})")
        if primeiro.valor in _INICIO_DE_RESTRICAO:
            unicas = _unicidade_de(elemento)
            if unicas:
                objectos.unicidades.append((tabela, unicas, primeiro.linha))
        else:
            _coluna(tabela, elemento, objectos)
        _checks_de(elemento, tabela, objectos)


def _alter_table(tokens: list[Token], objectos: Objectos) -> None:
    i = 2
    i = _saltar(tokens, i, "if", "exists")
    i = _saltar(tokens, i, "only")
    _, tabela, i = _nome_qualificado(tokens, i)
    for accao in _partir_por_virgulas(tokens[i:]):
        if not accao:
            continue
        if _e(accao[0], "add"):
            j = 1
            j = _saltar(accao, j, "column")
            j = _saltar(accao, j, "if", "not", "exists")
            if j < len(accao) and accao[j].tipo == "ident" and accao[j].valor in _INICIO_DE_RESTRICAO:
                unicas = _unicidade_de(accao[j:])
                if unicas:
                    objectos.unicidades.append((tabela, unicas, accao[j].linha))
            elif j < len(accao) and accao[j].tipo == "ident":
                _coluna(tabela, accao[j:], objectos)
            else:
                raise SqlIlegivel(f"ALTER TABLE ... ADD sem nome (linha {accao[0].linha})")
            _checks_de(accao, tabela, objectos)
        elif _e(accao[0], "rename"):
            j = 1
            if j < len(accao) and _e(accao[j], "to"):
                objectos.tabelas.append(("", accao[j + 1].valor, accao[j + 1].linha))
                continue
            if j < len(accao) and _e(accao[j], "constraint"):
                continue
            j = _saltar(accao, j, "column")
            # RENAME [COLUMN] velho TO novo
            if j + 2 < len(accao) and _e(accao[j + 1], "to"):
                objectos.colunas.append((tabela, accao[j + 2].valor, accao[j + 2].linha))
            else:
                raise SqlIlegivel(f"ALTER TABLE ... RENAME que nao sei ler (linha {accao[0].linha})")
        # As outras accoes (ENABLE/FORCE ROW LEVEL SECURITY, OWNER TO, ALTER
        # COLUMN, DROP, VALIDATE, ATTACH, SET, …) nao introduzem nomes.


def _ddl_dentro_de_bloco(tokens: list[Token]) -> Token | None:
    """O primeiro `CREATE`/`ALTER` dentro de um bloco `$$`, se houver."""
    for token in tokens:
        if token.tipo != "dollar":
            continue
        try:
            dentro = tokenizar(token.valor)
        except SqlIlegivel:
            return token
        for interior in dentro:
            if _e(interior, *_DDL_EM_BLOCO):
                return token
            # EXECUTE 'CREATE TABLE …': o DDL esta numa cadeia dentro do bloco
            if interior.tipo == "str" and _DDL_EM_TEXTO.search(interior.valor):
                return token
        aninhado = _ddl_dentro_de_bloco(dentro)
        if aninhado is not None:
            return token
    return None


def analisar_instrucao(tokens: list[Token]) -> Objectos:
    """O que uma instrucao introduz, ou `desconhecida` se a forma nao e conhecida."""
    objectos = Objectos(instrucoes=1)
    objectos.opacos = sum(1 for t in tokens if t.tipo == "dollar")
    if not tokens or tokens[0].tipo != "ident":
        linha = tokens[0].linha if tokens else 1
        objectos.desconhecidas.append(("instrucao que nao comeca por uma palavra", linha))
        return objectos

    primeira = tokens[0].valor
    linha = tokens[0].linha

    # DDL dinamico: `DO $$ BEGIN CREATE ROLE x; END $$`, ou uma funcao que cria
    # tabelas. O bloco e opaco para o nivel 2, pelo que nao pode criar nada.
    com_ddl = _ddl_dentro_de_bloco(tokens)
    if com_ddl is not None:
        objectos.desconhecidas.append(
            (f"{primeira.upper()} com CREATE/ALTER dentro de um bloco $$ (DDL dinamico)", com_ddl.linha)
        )
        return objectos

    if primeira == "create":
        i = 1
        while i < len(tokens) and tokens[i].tipo == "ident" and tokens[i].valor in _MODIFICADORES:
            i += 1
        alvo = tokens[i].valor if i < len(tokens) and tokens[i].tipo == "ident" else ""
        if alvo == "schema":
            i = _saltar(tokens, i + 1, "if", "not", "exists")
            if i < len(tokens) and _e(tokens[i], "authorization"):
                # CREATE SCHEMA AUTHORIZATION papel: o esquema chama-se como o papel
                if i + 1 < len(tokens) and tokens[i + 1].tipo == "ident":
                    objectos.esquemas.append((tokens[i + 1].valor, tokens[i + 1].linha))
                i += 2
            elif i < len(tokens) and tokens[i].tipo == "ident":
                objectos.esquemas.append((tokens[i].valor, tokens[i].linha))
                i += 1
                if i < len(tokens) and _e(tokens[i], "authorization"):
                    i += 2
            if i < len(tokens):
                # CREATE SCHEMA x CREATE TABLE …: elementos embutidos
                objectos.desconhecidas.append(
                    ("CREATE SCHEMA com elementos embutidos: escreva cada CREATE em separado", linha)
                )
            return objectos
        if alvo == "table":
            i = _saltar(tokens, i + 1, "if", "not", "exists")
            esquema, tabela, i = _nome_qualificado(tokens, i)
            objectos.tabelas.append((esquema, tabela, linha))
            if i < len(tokens) and _p(tokens[i], "("):
                interior, _ = _grupo(tokens, i)
                _corpo_de_tabela(interior, tabela, objectos)
            elif i < len(tokens) and _e(tokens[i], "partition"):
                pass  # PARTITION OF <mae>: as colunas sao as da mae
            else:
                objectos.desconhecidas.append(
                    (f"CREATE TABLE {tabela} sem lista de colunas (AS SELECT?): colunas ilegiveis", linha)
                )
            return objectos
        if alvo in ("view", "materialized"):
            i += 1
            if alvo == "materialized":
                i = _saltar(tokens, i, "view")
            i = _saltar(tokens, i, "if", "not", "exists")
            esquema, nome, _ = _nome_qualificado(tokens, i)
            objectos.tabelas.append((esquema, nome, linha))
            return objectos
        if alvo in ("role", "user", "group"):
            if i + 1 < len(tokens) and tokens[i + 1].tipo == "ident":
                objectos.papeis.append((tokens[i + 1].valor, linha))
            return objectos
        if alvo in ("type", "domain"):
            _, nome, j = _nome_qualificado(tokens, i + 1)
            objectos.tipos.append((nome, linha))
            if alvo == "type" and _e(tokens[j] if j < len(tokens) else None, "as"):
                seguinte = tokens[j + 1] if j + 1 < len(tokens) else None
                if _e(seguinte, "enum"):
                    interior, _ = _grupo(tokens, j + 2)
                    objectos.enums[nome] = (_so_cadeias(interior) or [], linha)
                elif _p(seguinte, "("):
                    # tipo composto: os atributos sao nomes, como colunas
                    interior, _ = _grupo(tokens, j + 1)
                    for elemento in _partir_por_virgulas(interior):
                        if elemento and elemento[0].tipo == "ident":
                            objectos.colunas.append((nome, elemento[0].valor, elemento[0].linha))
                else:
                    objectos.desconhecidas.append((f"CREATE TYPE {nome} de forma desconhecida", linha))
            else:
                _checks_de(tokens, nome, objectos)
            return objectos
        if alvo == "index":
            # Um indice unico **sem** `WHERE` e uma unicidade da tabela, igual a
            # um `UNIQUE (…)`; com `WHERE` e parcial e nao a impoe a todas as linhas.
            unico = any(_e(t, "unique") for t in tokens[1:i])
            em = next((k for k, t in enumerate(tokens) if _e(t, "on")), -1)
            if unico and em > 0 and not any(_e(t, "where") for t in tokens[em:]):
                k = _saltar(tokens, em + 1, "only")
                _, tabela, k = _nome_qualificado(tokens, k)
                if k < len(tokens) and _e(tokens[k], "using"):
                    k += 2
                if k < len(tokens) and _p(tokens[k], "("):
                    interior, _ = _grupo(tokens, k)
                    colunas = [
                        parte[0].valor
                        for parte in _partir_por_virgulas(interior)
                        if parte and parte[0].tipo == "ident"
                    ]
                    objectos.unicidades.append((tabela, colunas, linha))
            return objectos
        if ("create", alvo) in _SEM_NOMES:
            return objectos
        objectos.desconhecidas.append((f"CREATE {alvo.upper() or '?'}", linha))
        return objectos

    if primeira == "alter":
        segunda = tokens[1].valor if len(tokens) > 1 and tokens[1].tipo == "ident" else ""
        if segunda == "table":
            _alter_table(tokens, objectos)
            return objectos
        if segunda == "type":
            # ALTER TYPE t ADD VALUE 'x': um valor novo num dominio fechado
            _, nome, j = _nome_qualificado(tokens, 2)
            resto = tokens[j:]
            if _e(resto[0] if resto else None, "add") and _e(resto[1] if len(resto) > 1 else None, "value"):
                valores = [t.valor for t in resto if t.tipo == "str"][:1]
                objectos.checks.append(Check(nome, nome, valores, False, linha))
            elif _e(resto[0] if resto else None, "rename") and any(_e(t, "value") for t in resto):
                valores = [t.valor for t in resto if t.tipo == "str"][-1:]
                objectos.checks.append(Check(nome, nome, valores, False, linha))
            elif _e(resto[0] if resto else None, "owner", "set"):
                pass
            else:
                objectos.desconhecidas.append((f"ALTER TYPE {nome} de forma desconhecida", linha))
            return objectos
        if ("alter", segunda) in _SEM_NOMES:
            return objectos
        objectos.desconhecidas.append((f"ALTER {segunda.upper() or '?'}", linha))
        return objectos

    if primeira in ("select", "with") and any(_e(t, "into") for t in tokens):
        # SELECT … INTO tabela: cria uma tabela sem lista de colunas legivel.
        # (`INSERT INTO` comeca por `insert` e nao passa por aqui.)
        if primeira == "select" or not any(_e(t, "insert") for t in tokens):
            objectos.desconhecidas.append(("SELECT … INTO (cria uma tabela; colunas ilegiveis)", linha))
            return objectos

    if (primeira,) in _SEM_NOMES:
        return objectos

    objectos.desconhecidas.append((primeira.upper(), linha))
    return objectos


def analisar(texto: str) -> tuple[Objectos, list[Token]]:
    """Analisa um texto SQL. Devolve os objectos e **todos** os tokens (nivel 1)."""
    tokens = tokenizar(texto)
    objectos = Objectos()
    for instrucao in instrucoes(tokens):
        objectos.juntar(analisar_instrucao(instrucao))
    return objectos, tokens
