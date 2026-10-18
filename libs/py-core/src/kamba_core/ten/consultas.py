"""O SQL do TEN, num sitio so (KAM-009, revisao `0007`).

Espelho de `packages/core-ts/src/ten/consultas.ts`. A unica diferenca e o
marcador — `%s` em vez de `$n`, porque e o que a DB-API le; a posicao e o
significado de cada parametro nao mudam, e o `TestParidadeDoTypeScript` de
`libs/py-core/tests/test_ten.py` confirma-o reescrevendo os `$n` do TypeScript
e comparando o texto, caracter a caracter.

**A aritmetica nao esta aqui, e isso e o ponto.** Nenhuma destas consultas
soma, subtrai ou compara um limite: a regra vive inteira em
`platform.ten_consumir` e o fuso do periodo em `platform.ten_periodo`, as duas
da revisao `0007`. O bloco do KAM-009 pede «o Python chama a mesma regra SQL»,
e isto e o que essa frase quer dizer na pratica — nao ha um `date_trunc`
reescrito em Python nem um `min()` sobre `limites` em lado nenhum deste
pacote.

**A ordem dos parametros segue o texto.** Os marcadores `%s` sao posicionais:
um `$2` que aparecesse no texto do TypeScript antes do `$1` sobrevivia a
comparacao e trocava os argumentos deste lado, em silencio. Por isso o
`SQL_ENTITLEMENT` filtra o tenant numa subconsulta — e o que mantem os numeros
ascendentes na ordem de leitura do lado de la.
"""

from __future__ import annotations

#: O periodo de um instante: o primeiro dia do mes em `Africa/Luanda`.
#:
#: Nao decide nada; a `ten_consumir` chama a mesma funcao la dentro. Existe
#: para quem precisa de **mostrar** o periodo e para os testes de fronteira de
#: mes poderem perguntar a base o que ela conta, com o relogio fixo do
#: criterio 5.
SQL_PERIODO = """
  SELECT platform.ten_periodo(%s) AS periodo
"""

#: O entitlement de um modulo, e se ele permite.
#:
#: **A decisao vem da base.** A coluna `permitido` e a conjuncao do criterio 2
#: escrita em SQL: ha linha, `ativo` e verdadeiro, e o estado do tenant nao e
#: `onboarding`, `suspenso` nem `encerrado`. Escrita uma vez, e o que faz com
#: que o Python e o TypeScript nao possam discordar.
#:
#: **Zero linhas tambem e uma decisao: nega.** Nao ha linha quando o tenant nao
#: existe, quando esta apagado por `deleted_at`, e — o caso que importa —
#: quando o contexto de RLS e de **outro** tenant: a politica `tenant_iso` de
#: `platform.tenants` e `id = app.tenant_id`, e um contexto trocado devolve
#: vazio em vez de erro.
#:
#: O `tem_linha` distingue «nao ha entitlement» de «ha, e esta inactivo»: sem
#: ele o `coalesce(e.ativo, false)` tornava os dois casos no mesmo `false`.
#:
#: Parametros: o tenant, depois o modulo.
SQL_ENTITLEMENT = """
  SELECT t.estado AS estado_tenant,
         (e.tenant_id IS NOT NULL) AS tem_linha,
         coalesce(e.ativo, false) AS ativo,
         (    t.estado <> ALL (ARRAY['onboarding', 'suspenso', 'encerrado'])
          AND coalesce(e.ativo, false)) AS permitido
    FROM (SELECT id, estado
            FROM platform.tenants
           WHERE id = %s AND deleted_at IS NULL) AS t
    LEFT JOIN platform.entitlements AS e
           ON e.tenant_id = t.id AND e.modulo = %s
"""

#: O consumo: a chamada a regra unica.
#:
#: Os seis argumentos sao os da assinatura da `0007`, pela ordem: tenant,
#: chave de limite, quantidade, chave de idempotencia, tecto de quem chama (ou
#: `None`) e o instante (ou `None` para `now()`).
#:
#: Os dois ultimos passam-se **sempre**, com `None` quando nao ha valor, em vez
#: de se montarem duas versoes do texto: duas versoes seriam duas consultas a
#: manter e a comparar com o TypeScript, e a que se usa menos e a que se parte.
#:
#: `coalesce(%s, now())` em vez de deixar o `DEFAULT` da funcao resolver: um
#: argumento nomeado ausente nao se exprime numa chamada posicional, e passar
#: `NULL` a secas poria o periodo a `NULL` e o `CHECK` de `tenant_usage` a
#: recusar tudo.
SQL_CONSUMIR = """
  SELECT aceite, valor, repetido, limite
    FROM platform.ten_consumir(%s, %s, %s, %s, %s, coalesce(%s, now()))
"""
