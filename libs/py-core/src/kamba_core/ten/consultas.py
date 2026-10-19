"""O SQL do TEN, num sitio so (KAM-009, revisao `0007`).

Espelho de `packages/core-ts/src/ten/consultas.ts`. A unica diferenca e o
marcador — `%s` em vez de `$n`, porque e o que a DB-API le; a posicao e o
significado de cada parametro nao mudam, e o `TestParidadeDoTypeScript` de
`libs/py-core/tests/test_ten.py` confirma-o reescrevendo os `$n` do TypeScript
e comparando o texto, caracter a caracter.

**A aritmetica nao esta aqui, e isso e o ponto.** Nenhuma destas consultas
soma, subtrai ou acumula um contador: a regra vive inteira em
`platform.ten_consumir` e o fuso do periodo em `platform.ten_periodo`, as duas
da revisao `0007`. O bloco do KAM-009 pede «o Python chama a mesma regra SQL»,
e isto e o que essa frase quer dizer na pratica — nao ha um `date_trunc`
reescrito em Python nem um `min()` sobre `limites` em lado nenhum deste
pacote. **Sem excepcoes, e ja esteve com uma:** a primeira versao do
`SQL_TECTO` escrevia aqui o `min(...)` sobre `limites`, e era a segunda copia
de uma regra que a `ten_consumir` ja tinha. Hoje o minimo e
`platform.ten_tecto`, chamada pelos dois.

**O `coalesce(..., now())` nao e enfeite.** As duas funcoes da `0007` tem um
argumento de instante com `DEFAULT now()`, e um argumento nomeado ausente nao
se exprime numa chamada posicional: ou se passa a lista toda, ou nenhum dos
seguintes. Como aqui se passa sempre a lista toda, passar `None` a secas punha
o periodo a `NULL` — no `ten_consumir`, o `CHECK` de `tenant_usage` a recusar
tudo; no `ten_periodo`, um `NULL` devolvido em silencio. E por isso que o
`coalesce` esta nos **dois**, e nao so no `SQL_CONSUMIR`: a revisao
adversarial mediu essa divergencia exacta — o `periodo()` sem instante
devolvia `None` deste lado e **levantava** do lado do TypeScript.

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
#:
#: `coalesce(%s, now())` pela razao da docstring do modulo, que e a mesma do
#: sexto argumento do `SQL_CONSUMIR`: sem ele, `periodo(bd)` sem instante
#: mandava `None` a funcao e recebia `None` de volta — e `None` nao e um
#: periodo, e um buraco que cada lado tapava a sua maneira.
SQL_PERIODO = """
  SELECT platform.ten_periodo(coalesce(%s, now())) AS periodo
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
#:
#: **So se chama com chaves consumiveis** (`x-kamba-consumivel: true` no
#: `registry/entitlement_keys.schema.json`). Um tecto por pedido que passe por
#: aqui cria linha em `tenant_usage` e gasta o balde — ver `SQL_TECTO`.
SQL_CONSUMIR = """
  SELECT aceite, valor, repetido, limite
    FROM platform.ten_consumir(%s, %s, %s, %s, %s, coalesce(%s, now()))
"""

#: O tecto de uma chave, **sem consumir nada**.
#:
#: A pergunta de um tecto por pedido e «este valor cabe?», e nao «quanto ja
#: gastei»: nao ha contador, nao ha periodo e nao se escreve linha nenhuma. E
#: por isso que ha uma funcao so para isto, e nao uma chamada a `ten_consumir`
#: com quantidade zero — a `0007` recusa quantidade nao positiva, e com
#: quantidade positiva escreveria.
#:
#: **A regra do minimo vive na revisao, como todas as outras.** A primeira
#: versao desta constante trazia o `min((limites ->> chave)::bigint)` para
#: aqui, e era a unica consulta deste ficheiro a infringir o argumento da
#: docstring: duas copias da mesma regra, e a segunda a divergir no dia em que
#: a primeira mudasse. A `0007` passou a ter `platform.ten_tecto(p_tenant,
#: p_chave)`, que a propria `ten_consumir` chama, e esta consulta e so a
#: chamada.
#:
#: O contrato da funcao, que e o que esta consulta herda:
#:
#: * devolve o **minimo** entre os modulos activos que declaram a chave — a
#:   regra que o dicionario §3.2 escreve para o par
#:   `valor_max_pedido_minor`/`manual_max_minor`, aplicada ao caso geral;
#: * devolve **`None`** quando nenhum modulo activo a declara, e isso **nega**
#:   (falha fechada do criterio 2: «sem tecto» nao quer dizer «sem limite»). A
#:   RLS poe o mesmo a acontecer quando o contexto da transaccao e de outro
#:   tenant — vazio, e nao erro;
#: * **levanta `22023`** quando um modulo activo declara a chave com um valor
#:   que nao e um inteiro nao negativo. Nao ignora a linha ilegivel, e a razao
#:   e aritmetica: ignora-la tirava um modulo do minimo, e o minimo de menos
#:   modulos e **maior** — um dado corrompido alargava o tecto. Quem le esta
#:   consulta traduz esse `22023`; ver `check_ceiling`.
#:
#: E `SECURITY INVOKER`, como as outras duas: a RLS de
#: `platform.entitlements` continua a aplicar-se a quem chama.
#:
#: Parametros: o tenant, depois a chave de limite.
SQL_TECTO = """
  SELECT platform.ten_tecto(%s, %s) AS tecto
"""
