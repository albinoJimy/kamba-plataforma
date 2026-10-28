"""As consultas do modulo `servicos`, lidas do proprio TypeScript.

**Nao sao uma copia.** O `db/tests_ten/base.py` importa as constantes de
`kamba_core.ten.consultas` para que «o que o *gate* 8 exercita contra PostgreSQL
passe a ser o texto que a biblioteca envia» — e a razao esta escrita la: a
revisao adversarial do KAM-009 descobriu que o SQL das bibliotecas **nunca
corria contra uma base**, e o `SQL_PERIODO` tinha um defeito real que ninguem
media.

Aqui o modulo e TypeScript e nao Python, pelo que nao ha `import`. O que ha e
este ficheiro, que **le o ficheiro do modulo** e extrai as constantes. A
diferenca face a uma copia e a que importa: se alguem alterar o
`SQL_CRIAR_HOLD` em `services/com/src/servicos/consultas.ts`, o que esta suite
corre muda com ele — e se o alterar para algo que a base recusa, a suite fica
vermelha. Numa copia, ficava verde sobre texto que ja ninguem enviava.

## A unica traducao e o estilo do parametro

O PostgreSQL aceita `$1`; o `pg8000` nao — usa `%s` posicional. A conversao e
mecanica e esta aqui por extenso:

    $1, $2, ... -> %s, na ordem em que aparecem

**E e isso que obriga a chamar com os argumentos na ordem dos `$n`.** Um `$1`
que apareca duas vezes na mesma consulta passaria a exigir o argumento duas
vezes, o que nao e equivalente: por isso ha uma asercao que recusa uma consulta
em que algum `$n` se repita, em vez de a converter em silencio.

## O que este ficheiro nao faz

Nao interpreta TypeScript. Procura `export const NOME = ` seguido de uma
*template string* (acentos graves) ou de uma cadeia com aspas, e para ai. Uma
constante construida por concatenacao ou por interpolacao **nao e encontrada**, e
o `exigir()` falha com o nome em falta em vez de devolver uma cadeia vazia — que
e a falha certa: uma consulta que a suite nao encontrou e uma consulta que a
suite nao esta a provar.
"""

from __future__ import annotations

import re
from pathlib import Path

#: O ficheiro do modulo. Tres niveis acima de `db/tests_servicos/`.
MODULO = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "com"
    / "src"
    / "servicos"
    / "consultas.ts"
)

_TEMPLATE = re.compile(
    r"^export const (?P<nome>[A-Z][A-Z0-9_]*) = `(?P<corpo>[^`]*)`;",
    re.MULTILINE,
)
_CADEIA = re.compile(
    r"^export const (?P<nome>[A-Z][A-Z0-9_]*) = \"(?P<corpo>[^\"]*)\";",
    re.MULTILINE,
)

_PARAMETRO = re.compile(r"\$(\d+)")


def _converter(nome: str, sql: str) -> str:
    """`$n` -> `%s`, recusando uma consulta que repita um `$n`.

    Um `$n` repetido tem significado no PostgreSQL (o mesmo argumento usado duas
    vezes) e nao tem equivalente posicional: converte-lo em silencio mudava a
    aritmetica dos argumentos e a suite passava a chamar outra coisa. Nenhuma
    consulta do modulo o faz hoje, e e isto que garante que continua assim.
    """
    numeros = _PARAMETRO.findall(sql)
    if len(numeros) != len(set(numeros)):
        raise AssertionError(
            f"{nome}: um parametro `$n` repete-se, e nao ha equivalente "
            "posicional em pg8000. Converter em silencio mudava os argumentos."
        )
    esperados = [str(n) for n in range(1, len(numeros) + 1)]
    if sorted(numeros, key=int) != esperados:
        raise AssertionError(
            f"{nome}: os parametros nao sao `$1..${len(numeros)}` sem saltos "
            f"(encontrados: {numeros})"
        )
    # **E tem de aparecer por ordem crescente no texto.** O `%s` do pg8000 e
    # posicional pela ordem em que **aparece**, e o `$n` do PostgreSQL nao: uma
    # consulta com `... < $2 ... > $1 ...` converte-se numa em que o primeiro
    # `%s` recebe o argumento de `$2`, com os dois trocados em silencio.
    #
    # Isto custou uma falha a perceber. O `SQL_OCUPADO` escrevia
    # `inicio_at < $2 AND fim_at > $1`, a conversao trocou-os, e o teste do
    # isolamento dizia que o **proprio** tenant nao via a sua marcacao —
    # apontando para a RLS quando o defeito era aqui. Quem escreve a consulta
    # passa a ter de a escrever com os parametros por ordem, e esta asercao
    # di-lo com o nome da constante.
    if numeros != esperados:
        raise AssertionError(
            f"{nome}: os parametros `$n` tem de aparecer no texto por ordem "
            f"crescente — o `%s` do pg8000 e posicional pela ordem de aparicao "
            f"(encontrados: {numeros}). Reordena as condicoes na consulta."
        )
    return _PARAMETRO.sub("%s", sql)


def _ler() -> dict[str, str]:
    texto = MODULO.read_text(encoding="utf-8")
    encontradas: dict[str, str] = {}
    for padrao in (_TEMPLATE, _CADEIA):
        for achado in padrao.finditer(texto):
            encontradas[achado.group("nome")] = achado.group("corpo")
    return encontradas


#: Tudo o que se encontrou, com o nome do modulo. As cadeias de SQL ja com `%s`.
CONSTANTES = _ler()


def exigir(nome: str) -> str:
    """A constante do modulo, convertida. Falha se nao existir."""
    if nome not in CONSTANTES:
        raise AssertionError(
            f"{nome} nao esta em {MODULO.name}: a suite nao pode provar uma "
            f"consulta que nao encontrou. Encontradas: {sorted(CONSTANTES)}"
        )
    return _converter(nome, CONSTANTES[nome])


SQL_LISTAR_SERVICOS = exigir("SQL_LISTAR_SERVICOS")
SQL_SERVICO = exigir("SQL_SERVICO")
SQL_GRELHA = exigir("SQL_GRELHA")
SQL_OCUPADO = exigir("SQL_OCUPADO")
SQL_SLOT_OFERECIVEL = exigir("SQL_SLOT_OFERECIVEL")
SQL_TRANCAR_RECURSO = exigir("SQL_TRANCAR_RECURSO")
SQL_CRIAR_HOLD = exigir("SQL_CRIAR_HOLD")
SQL_REMARCAR = exigir("SQL_REMARCAR")
SQL_MARCACAO_DO_SLOT = exigir("SQL_MARCACAO_DO_SLOT")
SQL_CONFIRMAR_HOLD = exigir("SQL_CONFIRMAR_HOLD")
SQL_MARCACAO_POR_HOLD = exigir("SQL_MARCACAO_POR_HOLD")
SQL_MARCACAO = exigir("SQL_MARCACAO")
SQL_CANCELAR = exigir("SQL_CANCELAR")
SQL_EXPIRAR_HOLDS = exigir("SQL_EXPIRAR_HOLDS")
SQL_EMITIR_BOOKING_CREATED = exigir("SQL_EMITIR_BOOKING_CREATED")

#: Os `SQLSTATE` que o modulo traduz em codigos de recusa. Tambem lidos de la,
#: porque um `23P01` escrito a mao nos dois sitios podia divergir num.
SQLSTATE_SOBREPOSICAO = CONSTANTES["SQLSTATE_SOBREPOSICAO"]
SQLSTATE_UNICIDADE = CONSTANTES["SQLSTATE_UNICIDADE"]

#: As que a suite exercita, para o teste de cobertura do contrato.
EXERCITADAS = (
    "SQL_LISTAR_SERVICOS",
    "SQL_SERVICO",
    "SQL_GRELHA",
    "SQL_OCUPADO",
    "SQL_SLOT_OFERECIVEL",
    "SQL_TRANCAR_RECURSO",
    "SQL_CRIAR_HOLD",
    "SQL_REMARCAR",
    "SQL_MARCACAO_DO_SLOT",
    "SQL_CONFIRMAR_HOLD",
    "SQL_MARCACAO_POR_HOLD",
    "SQL_MARCACAO",
    "SQL_CANCELAR",
    "SQL_EXPIRAR_HOLDS",
    "SQL_EMITIR_BOOKING_CREATED",
)
