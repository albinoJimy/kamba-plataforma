"""C-01 — o contacto X nao le encomendas, consentimentos nem cotacoes de Y.

Criterio 6 do KAM-066. **E outro eixo**, e e o que se esquece: X e Y estao no
**mesmo** tenant, a politica `tenant_iso` deixa passar os dois, e o que separa
um do outro e o `WHERE contact_id = …` das funcoes de repositorio. Tirar esse
predicado nao avermelha politica nenhuma — avermelha este caso, ou nao
avermelha nada.

Duas metades, e as duas sao necessarias:

```text
C-01/base       SQL contra a base: a leitura filtrada por X nao traz Y, e a
                leitura **sem** o filtro traz — a sonda positiva que prova que
                o isolamento de contacto nao e de graca
C-01/consultas  as tres funcoes de leitura reais, em TypeScript, exercitadas
                com o contacto X e com o contacto Y
```

A segunda e a que o criterio pede pela letra («3 tools de leitura testadas»);
a primeira e a que torna a segunda legivel. Sem a sonda positiva da primeira,
«X nao ve nada de Y» passa contra uma tabela vazia, contra um contacto sem
linhas, e contra uma consulta que nao devolve nada a ninguem.
"""

from __future__ import annotations

from ..casos import registar_caso
from ..semente import COLUNA_DO_CANARIO, TABELAS


def _base(ctx) -> list[str]:  # noqa: ANN001
    """A camada SQL: o filtro por contacto e, de facto, o que separa X de Y."""
    if ctx.x is None or ctx.y is None or ctx.cursor_de is None:
        return ["C-01/base: o contexto nao traz X e Y. Num gate, saltar e falhar."]

    achados: list[str] = []
    for schema, tabela in TABELAS:
        coluna = COLUNA_DO_CANARIO[(schema, tabela)]
        canario_de_y = ctx.y.canarios[(schema, tabela)]
        canario_de_x = ctx.x.canarios[(schema, tabela)]
        cursor = ctx.cursor_de("app", ctx.x.tenant_id)

        # A leitura como o repositorio a faz: tenant **e** contacto.
        cursor.execute(
            f"SELECT {coluna} FROM {schema}.{tabela} WHERE contact_id = %s",
            (ctx.x.id,),
        )
        vistos = [linha[0] for linha in cursor.fetchall()]

        if canario_de_x not in vistos:
            achados.append(
                f"C-01/base {schema}.{tabela}: a sonda positiva falhou — a "
                f"leitura de X nao traz o canario de X ({canario_de_x!r}). "
                "Tudo o que vem a seguir seria verde sobre uma leitura vazia."
            )
        if canario_de_y in vistos:
            achados.append(
                f"C-01/base {schema}.{tabela}: a leitura do contacto X traz o "
                f"canario de Y. Os dois estao no mesmo tenant: a RLS nao os "
                "separa, e o predicado do contacto deixou de os separar."
            )

        # **A outra sonda positiva, e e a que torna este caso um caso.** Sem o
        # filtro por contacto, a mesma ligacao e o mesmo contexto veem Y. Se
        # isto nao se verificar, a afirmacao de cima nao provou nada: nao havia
        # linha de Y para ver.
        cursor.execute(f"SELECT {coluna} FROM {schema}.{tabela}")
        sem_filtro = [linha[0] for linha in cursor.fetchall()]
        if canario_de_y not in sem_filtro:
            achados.append(
                f"C-01/base {schema}.{tabela}: sem o filtro por contacto, o "
                f"contexto de A tambem nao ve o canario de Y. A linha de Y nao "
                "existe, ou nao e visivel ao papel — e entao «X nao ve Y» e "
                "verde por ausencia e nao por isolamento."
            )
    return achados


#: As tres leituras do criterio, pelos nomes que o condutor usa.
LEITURAS = ("encomendas", "cotacoes", "consentimentos")

#: Leitura -> a tabela cujo canario ela devolve.
TABELA_DA_LEITURA = {
    "encomendas": ("platform", "orders_mirror"),
    "cotacoes": ("platform", "price_quotes"),
    "consentimentos": ("platform", "consent_event"),
}


def _consultas(ctx) -> list[str]:  # noqa: ANN001
    """As tres funcoes de leitura reais, pelo condutor de TypeScript."""
    if ctx.node is None:
        return [
            "C-01/consultas: nao ha condutor de node no contexto. Num gate, "
            "saltar e falhar."
        ]
    if ctx.x is None or ctx.y is None:
        return ["C-01/consultas: o contexto nao traz X e Y."]

    relatorio = ctx.node("contacto")
    entradas = (relatorio or {}).get("contacto")
    if not entradas:
        return [
            "C-01/consultas: o condutor devolveu um relatorio sem `contacto`: "
            f"{str(relatorio)[:200]}"
        ]

    por_chave: dict[tuple[str, str], dict] = {
        (str(entrada.get("leitura")), str(entrada.get("contacto"))): entrada
        for entrada in entradas
    }
    achados: list[str] = []
    from ..oraculo import achatar  # noqa: PLC0415

    for leitura in LEITURAS:
        chave = TABELA_DA_LEITURA[leitura]
        canario_de_y = ctx.y.canarios[chave]
        canario_de_x = ctx.x.canarios[chave]

        como_x = por_chave.get((leitura, "x"))
        como_y = por_chave.get((leitura, "y"))
        if como_x is None or como_y is None:
            achados.append(
                f"C-01/consultas {leitura}: o condutor nao executou as duas "
                "leituras (X e Y). A leitura de Y e a sonda positiva: sem ela, "
                "a de X e verde sem medir nada."
            )
            continue
        if not como_x.get("executado") or not como_y.get("executado"):
            achados.append(
                f"C-01/consultas {leitura}: o condutor marcou-a como nao "
                f"executada ({como_x.get('nota') or como_y.get('nota')})."
            )
            continue

        texto_de_x = achatar(como_x.get("corpo", ""))
        texto_de_y = achatar(como_y.get("corpo", ""))

        if canario_de_y in texto_de_x:
            achados.append(
                f"C-01/consultas {leitura}: a leitura do contacto X devolveu o "
                "canario de Y. A funcao de repositorio perdeu o predicado do "
                "contacto — e a RLS nao a apanha, porque os dois contactos sao "
                "do mesmo tenant."
            )
        if canario_de_x not in texto_de_x:
            achados.append(
                f"C-01/consultas {leitura}: a sonda positiva falhou — a leitura "
                "de X nao devolveu o canario de X."
            )
        if canario_de_y not in texto_de_y:
            achados.append(
                f"C-01/consultas {leitura}: a sonda positiva falhou — a leitura "
                "de Y nao devolveu o canario de Y. A funcao nao le a linha que "
                "se semeou, e «X nao ve Y» e verde por ausencia."
            )
    return achados


registar_caso(
    id="C-01/base",
    bateria="C-01",
    camada="rls",
    fn=_base,
    precisa="postgres",
    origens=("corpo",),
)

registar_caso(
    id="C-01/consultas",
    bateria="C-01",
    camada="rls",
    fn=_consultas,
    precisa="node",
    origens=("corpo",),
)
