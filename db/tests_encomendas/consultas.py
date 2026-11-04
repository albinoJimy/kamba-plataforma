"""As consultas do modulo `orders`, lidas do proprio TypeScript.

**Nao sao uma copia.** Uma copia prova que a copia funciona: a revisao
adversarial do KAM-009 descobriu que o SQL das bibliotecas nunca corria contra
uma base, e o `SQL_PERIODO` tinha um defeito real que ninguem media. O
`db/tests_servicos/`, o `db/tests_produtos/` e esta suite exercitam o texto que
o modulo envia.

O instrumento e o `ConsultaDoTypeScript` de `db/tests/base.py`, que guarda a
**ordem** dos marcadores `$n` e reordena os argumentos — o `pg8000` nao tem `$n`,
tem `%s`, e liga-os pela ordem em que aparecem no texto. Quem chama escreve os
argumentos **pela numeracao do documento** (`$1` primeiro, qualquer que seja o
sitio onde apareca).

A ordem crescente nao e alcancavel aqui, pela razao que o
`db/tests_produtos/consultas.py` escreve: num `UPDATE` a clausula `SET` vem antes
do `WHERE`, e o repo-base do KAM-042 exige `tenant_id = $1` depois do primeiro
`WHERE` — pelo que os marcadores do `SET` aparecem antes do `$1`, sempre.

## Os tres `INSERT` do modulo nao estao aqui

A linha de `order_state_log`, o espelho novo e a divergencia aberta entram por
`repo.inserirNoTenant`, que **constroi** o `INSERT` com a coluna do filtro. Nao
ha constante para ler, e por isso esta suite escreve os tres `INSERT` ela
propria. O que isso custa esta dito: o texto do `INSERT` do modulo nao e
exercitado aqui — e exercitado pela suite do proprio repo-base, que e quem o
constroi.
"""

from __future__ import annotations

from pathlib import Path

from tests.base import ConsultaDoTypeScript

#: O ficheiro do modulo. Tres niveis acima de `db/tests_encomendas/`.
MODULO = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "com"
    / "src"
    / "orders"
    / "consultas.ts"
)


def exigir(nome: str) -> ConsultaDoTypeScript:
    """A constante do modulo, pronta para o `pg8000`. Falha se nao existir."""
    return ConsultaDoTypeScript(nome, ficheiro=MODULO)


SQL_LER = exigir("SQL_LER")
SQL_TRANSITAR = exigir("SQL_TRANSITAR")
SQL_GRAFO = exigir("SQL_GRAFO")
SQL_FECHAR_DIVERGENCIA = exigir("SQL_FECHAR_DIVERGENCIA")
SQL_DIVERGENCIAS_ABERTAS = exigir("SQL_DIVERGENCIAS_ABERTAS")
SQL_EMITIR = exigir("SQL_EMITIR")

# As oito do KAM-046: a saga do recibo de intencao e o fluxo do dono. Corridas
# em `test_idempotencia.py`, contra o mesmo motor e com o mesmo texto.
SQL_LER_INTENCAO = exigir("SQL_LER_INTENCAO")
SQL_CONCLUIR_INTENCAO = exigir("SQL_CONCLUIR_INTENCAO")
SQL_FALHAR_INTENCAO = exigir("SQL_FALHAR_INTENCAO")
SQL_RETOMAR_INTENCAO = exigir("SQL_RETOMAR_INTENCAO")
SQL_PEDIDO_POR_PAGAR = exigir("SQL_PEDIDO_POR_PAGAR")
SQL_CONFIRMACAO_DO_DONO = exigir("SQL_CONFIRMACAO_DO_DONO")
SQL_LER_CONFIRMACAO = exigir("SQL_LER_CONFIRMACAO")
SQL_ENCOMENDA_DA_CHAVE = exigir("SQL_ENCOMENDA_DA_CHAVE")

#: As que a suite exercita contra a base, para o teste de cobertura do contrato.
#:
#: **Nos dois sentidos**, como o `test_contrato` do KAM-047 e do KAM-043: uma
#: consulta do modulo que ninguem exercite entra sem ser provada, e um nome
#: nesta lista que o modulo nao tenha e uma declaracao morta. Foi assim que o
#: `SQL_GRELHA` do KAM-047 chegou com um defeito que nenhuma bateria tocava.
EXERCITADAS = (
    "SQL_LER",
    "SQL_TRANSITAR",
    "SQL_GRAFO",
    "SQL_FECHAR_DIVERGENCIA",
    "SQL_DIVERGENCIAS_ABERTAS",
    "SQL_EMITIR",
    "SQL_LER_INTENCAO",
    "SQL_CONCLUIR_INTENCAO",
    "SQL_FALHAR_INTENCAO",
    "SQL_RETOMAR_INTENCAO",
    "SQL_PEDIDO_POR_PAGAR",
    "SQL_CONFIRMACAO_DO_DONO",
    "SQL_LER_CONFIRMACAO",
    "SQL_ENCOMENDA_DA_CHAVE",
)
