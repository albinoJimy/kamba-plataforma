"""O SQL do *gate* de transferencia, num sitio so (KAM-069, revisao `0036`).

**Uma consulta por decisao, e e so esta.** O resto do modulo nao vai a base:
a *cache* responde pelo que ja sabe e nada mais se le.

A aritmetica nao esta aqui nem podia estar: a decisao e uma conjuncao sobre as
linhas devolvidas (ver `porta.py`), e ela **nao** se escreve em SQL de
proposito. A razao e a precedencia — uma linha do tenant tapa as globais — e
exprimi-la num `WHERE` dava duas leituras do mesmo predicado: uma na base e
outra no Python, para quando a base esta em baixo. Com a conjuncao em Python ha
**uma**, e o caminho de falha fechada usa a mesma.

## O `%s` e nao o `$n`

E o que a DB-API le, como em `kamba_core.ten.consultas`. Nao ha espelho em
TypeScript deste ficheiro: o unico chamador de hoje e o AGR, que e Python, e o
*gate* de go-live do criterio 8 corre no mesmo processo que o escrever.
"""

from __future__ import annotations

#: Os destinos que se aplicam a um pedido: os do tenant **e** os globais.
#:
#: Devolve as linhas todas e nao uma decisao, e isso e deliberado — ver a nota
#: do modulo. A coluna `especifica` e o que permite a precedencia: `true` para
#: uma linha do tenant, `false` para uma global.
#:
#: **O `apd_ref` nao sai da base.** Sai `tem_apd_ref`, um booleano: a referencia
#: do procedimento e um dado de conformidade que nenhuma decisao de transferencia
#: precisa de ter em memoria, e trazer o valor punha-o ao alcance de um *log* de
#: excepcao. A mensagem de recusa nomeia a falta, nunca o valor.
#:
#: **Zero linhas tambem e uma decisao: nega.** Nao ha linha quando o destino
#: nunca foi registado, e — o caso que importa — quando o contexto de RLS e de
#: **outro** tenant: a politica `tenant_iso` da `0036` e
#: `tenant_id = app.tenant_id` e um contexto trocado devolve vazio em vez de
#: erro. As linhas globais continuam a aparecer, pela segunda politica
#: (`destinos_globais`), e e por isso que a precedencia se avalia em Python: um
#: contexto trocado nao pode deixar as globais a decidir por um tenant que tem
#: linha propria.
#:
#: Parametros: o tenant, o fornecedor, a finalidade.
SQL_DESTINOS = """
  SELECT d.tenant_id IS NOT NULL AS especifica,
         d.status                AS status,
         d.apd_ref IS NOT NULL   AS tem_apd_ref,
         d.country               AS country
    FROM platform.tenant_destinations d
   WHERE (d.tenant_id = %s::uuid OR d.tenant_id IS NULL)
     AND d.provider = %s
     AND d.purpose = %s
"""

#: Os destinos activos de um tenant, para o *gate* de go-live (criterio 8).
#:
#: «Destino activo» e o que o criterio quer dizer com «algum destino activo do
#: tenant»: um par (fornecedor, finalidade) que o tenant tem registado. A
#: pergunta do *gate* e se **todos** eles estao autorizados — e nao se **algum**
#: esta —, e por isso a consulta devolve a lista e nao uma contagem: uma
#: contagem dizia quantos faltam e nao quais, e a mensagem de recusa de um
#: go-live tem de nomear o que falta ou ninguem o resolve.
#:
#: Parametros: o tenant.
SQL_DESTINOS_DO_TENANT = """
  SELECT d.provider              AS provider,
         d.purpose               AS purpose,
         d.status                AS status,
         d.apd_ref IS NOT NULL   AS tem_apd_ref
    FROM platform.tenant_destinations d
   WHERE d.tenant_id = %s::uuid
   ORDER BY d.provider, d.purpose
"""
