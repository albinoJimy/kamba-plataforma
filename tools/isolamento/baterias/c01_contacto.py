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
        # **A marca de cada tabela e a da sua coluna**, e nao sempre o canario
        # de texto. Na `price_quotes` o `sku` passou a ser partilhado por X e Y
        # (para o cenario do criterio 6 ser alcancavel), pelo que o que
        # distingue as duas linhas e o `id` — e comparar o canario de texto ali
        # fazia a sonda positiva falhar sobre uma leitura que estava certa.
        # Medido na execucao do *gate* 6 que seguiu os achados.
        if coluna == "id":
            canario_de_y = ctx.y.ids[(schema, tabela)]
            canario_de_x = ctx.x.ids[(schema, tabela)]
        else:
            canario_de_y = ctx.y.canarios[(schema, tabela)]
            canario_de_x = ctx.x.canarios[(schema, tabela)]
        cursor = ctx.cursor_de("app", ctx.x.tenant_id)

        # A leitura como o repositorio a faz: tenant **e** contacto.
        #
        # `::text` e nao a coluna crua: o `id` e `uuid`, e o `pg8000` devolve-o
        # como objecto `UUID` — a comparacao com a marca, que e uma cadeia,
        # falhava sempre e a sonda positiva acusava uma leitura que estava
        # certa. Medido na execucao do *gate* 6.
        cursor.execute(
            f"SELECT {coluna}::text FROM {schema}.{tabela} WHERE contact_id = %s",
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
        cursor.execute(f"SELECT {coluna}::text FROM {schema}.{tabela}")
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

#: Leitura -> o que o caso compara na resposta: `canario` ou `id`.
#:
#: **Nao e uniforme, e a razao e da projeccao de cada consulta.** A
#: `SQL_ESTADO` do consentimento projecta o `text_version`, que e a coluna do
#: canario; a `SQL_PEDIDO_POR_PAGAR` das encomendas projecta
#: `(id, numero_publico, estado, total_minor, currency, criado_at)` e **nao** o
#: `intent_key` — pelo que ali o que se compara e o identificador da linha, que
#: faz a mesma afirmacao: a linha de Y nao sai na leitura de X.
MARCA_DA_LEITURA = {
    "encomendas": "id",
    # Partilha o `(sku, qty)` com o outro contacto, de proposito (ver
    # `semente.SKU_PARTILHADO`): o canario nao pode viver numa coluna que os
    # dois partilham, e o que distingue as linhas e o `id`, que a
    # `SQL_COTACAO_VALIDA` projecta.
    "cotacoes": "id",
    "consentimentos": "canario",
}

#: A leitura que **nao** tem predicado de contacto no repositorio, e o ticket a
#: quem isso pertence.
#:
#: Ver `_fixacao_das_cotacoes` para o que se mediu e porque e que esta bateria
#: fixa o estado em vez de afirmar a propriedade.
SEM_PREDICADO_DE_CONTACTO = {"cotacoes": "KAM-043"}

#: A constante de SQL de cada leitura, e o ficheiro onde vive. O caso le-a para
#: afirmar sobre o **predicado escrito**, e nao sobre o que uma execucao
#: devolveu: uma leitura que por acaso nao traga a linha de Y nao prova que o
#: predicado existe.
SQL_DA_LEITURA = {
    "encomendas": (
        "services/com/src/orders/consultas.ts",
        "SQL_PEDIDO_POR_PAGAR",
    ),
    "cotacoes": (
        "services/com/src/produtos/consultas.ts",
        "SQL_COTACAO_VALIDA",
    ),
    "consentimentos": (
        "packages/core-ts/src/consentimento/consultas.ts",
        "SQL_ESTADO",
    ),
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
        if MARCA_DA_LEITURA[leitura] == "id":
            marca_de_x = ctx.x.ids.get(chave, "")
            marca_de_y = ctx.y.ids.get(chave, "")
        else:
            marca_de_x = ctx.x.canarios[chave]
            marca_de_y = ctx.y.canarios[chave]
        if not marca_de_x or not marca_de_y:
            achados.append(
                f"C-01/consultas {leitura}: a semente nao deu a marca "
                f"({MARCA_DA_LEITURA[leitura]}) das linhas de X e de Y em "
                f"{chave[0]}.{chave[1]}. Sem ela o caso nao compara nada."
            )
            continue

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

        if leitura in SEM_PREDICADO_DE_CONTACTO:
            achados.extend(
                _fixacao_das_cotacoes(
                    ctx,
                    leitura,
                    texto_de_x,
                    marca_de_x,
                    marca_de_y,
                    str(como_x.get("nota") or ""),
                )
            )
            continue

        if marca_de_y in texto_de_x:
            achados.append(
                f"C-01/consultas {leitura}: a leitura do contacto X devolveu a "
                "linha de Y. A funcao de repositorio perdeu o predicado do "
                "contacto — e a RLS nao a apanha, porque os dois contactos sao "
                "do mesmo tenant."
            )
        if marca_de_x not in texto_de_x:
            achados.append(
                f"C-01/consultas {leitura}: a sonda positiva falhou — a leitura "
                "de X nao devolveu a linha de X."
            )
        if marca_de_y not in texto_de_y:
            achados.append(
                f"C-01/consultas {leitura}: a sonda positiva falhou — a leitura "
                "de Y nao devolveu a linha de Y. A funcao nao le a linha que "
                "se semeou, e «X nao ve Y» e verde por ausencia."
            )
    return achados


def _fixacao_das_cotacoes(
    ctx,  # noqa: ANN001
    leitura: str,
    texto_de_x: str,
    marca_de_x: str,
    marca_de_y: str,
    nota: str = "",
) -> list[str]:
    """Fixa o **comportamento medido** da leitura de cotacoes, nao o texto do SQL.

    ## O que se mede, e porque e que esta bateria nao afirma a propriedade

    O criterio 6 do KAM-066 diz que «o contacto X, com o estado de X, nao le
    encomendas, consentimentos nem `price_quotes` de Y». Das tres leituras, a
    das cotacoes **nao tem predicado de contacto**: a `SQL_COTACAO_VALIDA`
    (`services/com/src/produtos/consultas.ts`) filtra `tenant_id`, `sku`, `qty`,
    `estado` e `valida_ate`, e mais nada — e a `platform.price_quotes` tem
    `contact_id uuid NOT NULL` com FK composta desde a revisao `0028`. Dentro do
    mesmo tenant, X e Y com cotacao para o mesmo `(sku, qty)` leem **a mesma
    linha**: a mais recente.

    **E um achado deste ticket e nao um defeito deste ticket.** O
    `docs/tecnica/03` §7.2 descreve a cotacao como um preco «para `(sku, qty)`»
    e nao diz que e por cliente; o esquema diz que e. As duas leituras divergem,
    e acrescentar o predicado muda que cotacao um cliente recebe —
    comportamento do COM, nao do *harness*. Fica atribuido ao **KAM-043**, e a
    caixa do criterio 6 fica **vazia** no bloco, com esta medicao escrita.

    ## Porque e sobre o comportamento e nao sobre o texto

    A primeira versao desta fixacao fazia `if "contact_id" in sql` sobre o
    *template literal* inteiro — projeccao e comentarios incluidos — e saltava
    **antes** das duas sondas positivas. A revisao adversarial mostrou a cadeia
    inteira: bastava o KAM-043 acrescentar `contact_id` a **lista do `SELECT`**,
    sem predicado, para a fixacao anunciar «o credor pagou a divida»; quem
    seguisse a instrucao da mensagem tirava a leitura de
    `SEM_PREDICADO_DE_CONTACTO` e passava a correr uma asserção que ficava verde
    por outra razao — a semente dava a X e a Y `sku` **distintos**, pelo que X
    pedia o seu proprio `sku` e recebia a sua propria linha. A fixacao,
    desenhada para avisar, era o que fazia a caixa fechar errado.

    Agora: a semente da aos dois o **mesmo** `(sku, qty)`
    (`semente.SKU_PARTILHADO`), o que torna o cenario do criterio alcancavel, e
    o que se afirma e o que a leitura **devolveu**. Duas direccoes:

    * hoje, a leitura de X devolve a linha de **Y** — a mais recente das duas —
      e e isso que se fixa;
    * no dia em que ela devolver a linha de **X**, o predicado apareceu: o caso
      fica vermelho e diz o que fazer.

    Um `in` sobre texto nao distinguia estas duas coisas; uma comparacao de
    identificadores distingue.
    """
    credor = SEM_PREDICADO_DE_CONTACTO[leitura]
    relativo, constante = SQL_DA_LEITURA[leitura]

    if marca_de_x in texto_de_x and marca_de_y not in texto_de_x:
        return [
            f"C-01/consultas {leitura}: a leitura do contacto X devolveu a linha "
            f"de X e **nao** a de Y, com o `(sku, qty)` partilhado. O predicado "
            f"do contacto apareceu na `{constante}` ({relativo}) e o credor "
            f"{credor} pagou a divida — **esta e a boa noticia**, e esta bateria "
            "esta a dar o aviso que existe para dar: tire "
            f"{leitura!r} de `SEM_PREDICADO_DE_CONTACTO` em "
            "`baterias/c01_contacto.py`, e o caso passa a afirmar a propriedade "
            "do criterio 6 em vez de fixar a ausencia dela. Marque entao a caixa."
        ]
    if marca_de_y in texto_de_x:
        # O estado medido: a leitura cruza. Nao e achado **aqui** — e o achado
        # do bloco, com credor — mas fica dito na saida do *gate*, para que
        # ninguem leia este verde como «o isolamento de contacto esta provado».
        return []
    # **A mensagem leva o que a leitura devolveu, e isso nao e enfeite.** A
    # primeira versao dizia so «nao devolveu nem uma nem outra» e listava duas
    # causas possiveis; quando ela disparou no CI — verde nesta maquina,
    # vermelha no *runner* — nao havia como escolher entre as duas sem mais uma
    # volta de 17 minutos. Um diagnostico que obriga a adivinhar nao e um
    # diagnostico. Vai o texto cru, truncado, e as duas marcas esperadas.
    return [
        f"C-01/consultas {leitura}: a leitura do contacto X nao devolveu **nem** "
        f"a linha de X nem a de Y. O caso nao mediu nada: ou a semente nao "
        f"escreveu as duas cotacoes com o `(sku, qty)` partilhado, ou a "
        f"`{constante}` deixou de devolver linha a quem pede. Sem uma das duas "
        "marcas na resposta, nada do que esta bateria afirma sobre as cotacoes "
        "tem suporte."
        f" || esperava `{marca_de_x}` (X) ou `{marca_de_y}` (Y);"
        f" a leitura devolveu: {texto_de_x[:600]!r}"
        f" || a `nota` do condutor: {nota[:400]!r}"
    ]


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
