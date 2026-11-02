"""As consultas do modulo `produtos`, lidas do proprio TypeScript.

**Nao sao uma copia.** Uma copia prova que a copia funciona: a revisao
adversarial do KAM-009 descobriu que o SQL das bibliotecas nunca corria contra
uma base, e o `SQL_PERIODO` tinha um defeito real que ninguem media.

O instrumento e o `ConsultaDoTypeScript` de `db/tests/base.py`, que ja existe e
ja resolve a parte dificil: guarda a **ordem** dos marcadores `$n` e reordena os
argumentos, porque o `pg8000` nao tem `$n` — tem `%s`, e liga-os pela ordem em
que aparecem no texto.

## Porque e que a reordenacao importa aqui mais do que no `tests_servicos`

O `db/tests_servicos/consultas.py` escreveu um conversor proprio que **recusa**
uma consulta cujos `$n` nao aparecam por ordem crescente, e tinha razao para o
fazer: o `SQL_OCUPADO` escrevia `inicio_at < $2 AND fim_at > $1`, a conversao
trocou-os, e o teste do isolamento dizia que o proprio tenant nao via a sua
marcacao — a apontar para a RLS quando o defeito era na conversao.

Aqui a ordem crescente **nao e alcancavel**, e nao por desleixo: as consultas
deste modulo entram na base pelo repo-base do KAM-042, que exige
`tenant_id = $1` **depois do primeiro `WHERE`**. Num `UPDATE` a clausula `SET`
vem antes do `WHERE`, pelo que os marcadores do `SET` aparecem antes do `$1` —
sempre. Exigir ordem crescente obrigava a reescrever os `UPDATE` como CTE para
satisfazer um conversor, que e deixar a ferramenta decidir a forma do SQL.

Por isso usa-se o `ConsultaDoTypeScript`, que reordena, e **quem chama escreve
os argumentos pela numeracao do documento** (`$1` primeiro, qualquer que seja o
sitio onde apareca). O `$n` repetido continua recusado, pelo `args()`: nao ha
equivalente posicional para o mesmo argumento usado duas vezes.
"""

from __future__ import annotations

from pathlib import Path

from tests.base import ConsultaDoTypeScript

#: O ficheiro do modulo. Tres niveis acima de `db/tests_produtos/`.
MODULO = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "com"
    / "src"
    / "produtos"
    / "consultas.ts"
)


def exigir(nome: str) -> ConsultaDoTypeScript:
    """A constante do modulo, pronta para o `pg8000`. Falha se nao existir."""
    return ConsultaDoTypeScript(nome, ficheiro=MODULO)


SQL_TERMOS = exigir("SQL_TERMOS")
SQL_TERMOS_PARA_ESCRITA = exigir("SQL_TERMOS_PARA_ESCRITA")
SQL_ACTUALIZAR_TERMOS = exigir("SQL_ACTUALIZAR_TERMOS")
SQL_PUBLICAR = exigir("SQL_PUBLICAR")
SQL_AJUSTAR_STOCK = exigir("SQL_AJUSTAR_STOCK")
SQL_PESQUISAR = exigir("SQL_PESQUISAR")
SQL_COTACAO_VALIDA = exigir("SQL_COTACAO_VALIDA")
SQL_ACEITAR_COTACAO = exigir("SQL_ACEITAR_COTACAO")
SQL_AUDITAR = exigir("SQL_AUDITAR")
SQL_EMITIR = exigir("SQL_EMITIR")

#: As que a suite exercita contra a base, para o teste de cobertura do contrato.
#:
#: **Nos dois sentidos**, como o `test_contrato` do KAM-047 faz: uma consulta do
#: modulo que ninguem exercite entra sem ser provada, e um nome nesta lista que o
#: modulo nao tenha e uma declaracao morta. Foi assim que o `SQL_GRELHA` daquele
#: ticket chegou com um defeito que nenhuma bateria tocava.
EXERCITADAS = (
    "SQL_TERMOS",
    "SQL_TERMOS_PARA_ESCRITA",
    "SQL_ACTUALIZAR_TERMOS",
    "SQL_PUBLICAR",
    "SQL_AJUSTAR_STOCK",
    "SQL_PESQUISAR",
    "SQL_COTACAO_VALIDA",
    "SQL_ACEITAR_COTACAO",
    "SQL_AUDITAR",
    "SQL_EMITIR",
)
