"""A politica AST do caminho para o LLM (KAM-112, criterio 1 e Testes Requeridos).

«Arquitectura: nenhuma chamada ao cliente LLM fora de `minimise`.»

## A forma e a do `politica_ast.py`, e as tres pecas sao as mesmas

Aquele e a politica AST do `handoff_wait` (KAM-034) e tem as tres pecas de que
isto precisa: **regras com nome**, para que um achado diga qual propriedade
quebrou; **mensagens por regra**, porque quem le o vermelho nao tem o bloco
aberto; e **canarios** — fontes que **tem** de ser recusadas —, porque «o
repositorio esta conforme» e uma linha que um `check` vazio passa.

Nao se abre *gate* novo, pela decisao que o `politica_ast.py` ja escreveu: um
*gate* novo e um contexto exigido novo no *ruleset* de `main`, isto e, uma
alteracao de regra de bloqueio, que **nao e deste ticket** e pede o fundador.
Isto corre no `make test-py`, que o *gate* 4 ja executa e que **ja bloqueia**.

## Le a fonte e nao importa nada

Pela razao do `tool_schema.py` e do `politica_ast.py`: importar e inspeccionar
da a resposta do codigo **a correr**, e o que se quer saber e o que esta
**escrito**. Uma barreira que so morde em execucao nao apanha o caminho que
ninguem exercitou — e o caminho que ninguem exercitou e precisamente onde um
texto nao minimizado passaria a sair para um fornecedor estrangeiro.

**E e por isso que esta politica existe apesar de haver guarda em execucao.** O
`ClienteDeLlm.chamar` verifica `isinstance(item, MensagemMinimizada)` e levanta;
isso protege o que corre. O que nao protege e o diff: alguem que mude a guarda,
que a comente, ou que construa um `MensagemMinimizada` com um `MinimisedText`
obtido de outro sitio. As duas vias sao complementares e nenhuma substitui a
outra — como o `log_policy` tem o *lint* AST **e** o X-11 sobre os ficheiros.

## As quatro regras, e porque e que a terceira e a mais importante

1. `argumento_literal` — alguem passa uma **lista ou dicionario literal** como
   `mensagens` do `chamar`. E a forma exacta que a assinatura tinha antes deste
   ticket (`[{"role": "user", "content": texto}]`) e a que alguem reescreveria
   de memoria. Apanha-se na forma e nao no tipo, porque o `ast` nao sabe tipos.

2. `selo_fora_do_modulo` — o `_SELO` do `minimizacao.py` e referido noutro
   ficheiro. O selo e o que faz do `MinimisedText` um tipo e nao uma convencao;
   uma referencia a ele fora do modulo que o define e a unica forma de construir
   texto «minimizado» sem o detector correr.

3. `construcao_de_minimised_text` — alguem chama `MinimisedText(...)` fora do
   `minimizacao.py`.

   **E a mais importante das quatro, e e a que nao se ve ao ler o criterio.** A
   guarda em execucao do `__post_init__` recusa um selo errado, e por isso uma
   chamada destas **levanta** — hoje. Mas e tambem a chamada que alguem escreve
   um minuto antes de ir procurar porque e que ela falha, e a resposta que esta a
   um `grep` de distancia e «ha um `_SELO` no modulo». Recusar a construcao na
   **fonte** fecha o caminho antes de alguem ter razao para o abrir, e di-lo com
   a mensagem em vez de com um `TypeError`.

4. `chamar_sem_minimise` — um ficheiro que chama `.chamar(` e **nao** importa
   nada do pacote `privacidade`. E a regra mais fraca das quatro (um ficheiro
   pode receber as mensagens ja minimizadas de quem o chama) e por isso **nao e
   obrigatoria**: nao esta nas `REGRAS_OBRIGATORIAS` e serve de aviso ao
   varrimento, nao de recusa.

## O que esta politica NAO prova

Nao prova que o texto que chega ao `minimise` e o texto do cliente. Um no do
grafo que minimizasse uma cadeia vazia e mandasse o texto real por outro
caminho passava isto — e passaria tambem a guarda em execucao. O que fecha esse
caminho e nao haver outro caminho: o `ClienteDeLlm` e o unico egresso do AGR para
um modelo (`services/agr/egress.yaml` tem `destinos: []`), e o `egresso.py` tem
bateria propria. Diz-se aqui para que nao se leia esta politica como mais do que
ela e.
"""

from __future__ import annotations

import ast
from typing import Final

ARGUMENTO_LITERAL: Final = "argumento_literal"
SELO_FORA_DO_MODULO: Final = "selo_fora_do_modulo"
CONSTRUCAO: Final = "construcao_de_minimised_text"
CHAMAR_SEM_MINIMISE: Final = "chamar_sem_minimise"

#: O nome do metodo do gateway. Um so, e e o do `llm/cliente.py`.
METODO: Final = "chamar"
#: Os nomes privados do `minimizacao.py` que constroem um selo valido.
#:
#: **Eram um (`_SELO`) e sao tres**, porque o selo deixou de ser um objecto
#: passado e passou a ser um HMAC do texto (ver a nota do `_CHAVE_DO_SELO`): quem
#: tivesse a chave ou a funcao podia selar texto cru.
PRIVADOS: Final = ("_SELO", "_CHAVE_DO_SELO", "_impressao")
#: O nome do tipo selado.
TIPO: Final = "MinimisedText"
#: O pacote que tem de aparecer nos `import` de quem minimiza.
PACOTE: Final = "privacidade"

MENSAGENS: Final = {
    ARGUMENTO_LITERAL: (
        "o argumento `mensagens` do `chamar()` leva um dicionario literal: e a "
        "forma `[{\"role\": ..., \"content\": texto}]` que a assinatura "
        "aceitava antes do KAM-112, e e texto do cliente a sair para um "
        "fornecedor sem passar pelo detector de PII. A forma certa e "
        "`[privacidade.mensagem(papel, minimise(texto, ctx)[0])]` — uma **lista** "
        "de `MensagemMinimizada` e conforme (KAM-112 criterio 1; ADR-008, ADR-010)"
    ),
    SELO_FORA_DO_MODULO: (
        f"um nome privado do `privacidade/minimizacao.py` ({', '.join(PRIVADOS)}) "
        "e referido fora dele: o "
        "selo e o que faz do `MinimisedText` um tipo e nao uma convencao, e "
        "uma referencia a ele noutro ficheiro e a unica forma de construir "
        "texto «minimizado» sem o detector correr"
    ),
    CONSTRUCAO: (
        f"`{TIPO}(...)` e construido fora do `privacidade/minimizacao.py`: so o "
        "`minimise` o constroi, e uma construcao aqui levanta "
        "`TextoNaoMinimizado` em execucao — a recusa na fonte existe para que "
        "ninguem va procurar como a contornar"
    ),
    CHAMAR_SEM_MINIMISE: (
        f"este ficheiro chama `.{METODO}(` e nao importa nada de "
        f"`{PACOTE}`: confirma-se que as mensagens vem minimizadas de quem "
        "chama. Aviso, nao recusa"
    ),
}

#: As regras que o canario tem de ver morder, e que **recusam**. O
#: `CHAMAR_SEM_MINIMISE` fica fora: e aviso (ver a nota do modulo). Fixas aqui e
#: nao derivadas das *fixtures*, pela razao do `REGRAS_OBRIGATORIAS` do
#: `log_policy`: um manifesto que se esvazia dava «0 negativas, tudo verde».
REGRAS_OBRIGATORIAS: Final = (ARGUMENTO_LITERAL, SELO_FORA_DO_MODULO, CONSTRUCAO)

#: Os nos que sao um literal de coleccao. Um `mensagens=[...]` ou `{...}`.
_LITERAIS: Final = (ast.List, ast.Dict, ast.Tuple, ast.Set)


def _e_chamada_ao_gateway(no: ast.AST) -> bool:
    """Esta expressao e um `<algo>.chamar(...)`?

    Por atributo e nao por nome: o cliente chega sempre como atributo
    (`cliente.chamar`, `deps.llm.chamar`, `self._cliente.chamar`), e procurar
    um nome livre `chamar(` apanhava qualquer funcao local com esse nome.
    """
    return (
        isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == METODO
    )


def _mensagens_de(chamada: ast.Call) -> ast.expr | None:
    """O argumento `mensagens`, posicional (o segundo) ou por palavra."""
    for palavra in chamada.keywords:
        if palavra.arg == "mensagens":
            return palavra.value
    if len(chamada.args) >= 2:
        return chamada.args[1]
    return None


def _desembrulhar(valor: ast.expr) -> ast.expr:
    """Tira o `await` e os parentesis de uma expressao."""
    while isinstance(valor, ast.Await):
        valor = valor.value
    return valor


def _literais_atribuidos(arvore: ast.AST) -> dict[str, ast.expr]:
    """Variaveis ligadas a um literal de coleccao, por nome.

    **E a correccao da segunda evasao do achado 4 da revisao adversarial:**
    atribuir o literal a uma variavel desarmava a politica inteira, porque o
    `_mensagens_de` so olhava para o no passado na chamada.

        cru = [{"role": "user", "content": texto}]
        cliente.chamar("chat", cru, ctx)      # passava

    E a mesma classe das seis evasoes que o `politica_ast.py` do KAM-034
    documenta: a regra perguntava pela **forma do no** em vez de pelo **valor**.

    Resolve-se por modulo e nao por *scope*, que e grosseiro de proposito: um
    falso positivo aqui e um nome reutilizado, e o custo e uma mensagem a mais;
    um falso negativo e texto cru no modelo.
    """
    ligados: dict[str, ast.expr] = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.value, _LITERAIS):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    ligados[alvo.id] = no.value
        if (
            isinstance(no, ast.AnnAssign)
            and isinstance(no.target, ast.Name)
            and no.value is not None
            and isinstance(no.value, _LITERAIS)
        ):
            ligados[no.target.id] = no.value
    return ligados


def _tem_dicionario_de_mensagem(no: ast.expr) -> bool:
    """Esta expressao contem um `{"role": ..., "content": ...}`?

    **E a correccao da primeira metade do achado 4**, e era um falso positivo
    sobre o caminho certo. A regra recusava **qualquer** `ast.List` na posicao
    `mensagens` — incluindo `[mensagem("user", minimo)]`, que e a forma que a
    propria mensagem desta regra recomenda por escrito e que a bateria usa. Hoje
    nao mordia porque o varrimento le so `services/agr/src/kamba_agr`, onde nao
    ha chamador nenhum; no dia em que o grafo chamasse o gateway de forma
    idiomatica, o *gate* 4 ficava vermelho sobre codigo conforme — e um portao
    que avermelha o caminho certo e um portao que alguem desliga.
    """
    for filho in ast.walk(no):
        if not isinstance(filho, ast.Dict):
            continue
        chaves = {
            chave.value
            for chave in filho.keys
            if isinstance(chave, ast.Constant) and isinstance(chave.value, str)
        }
        # O esquema OpenAI-compativel, que e o que o `para_esquema` produz. Um
        # dicionario com estas chaves na posicao `mensagens` **e** a forma antiga.
        if "content" in chaves or "role" in chaves:
            return True
    return False


def _primeiro_e_self(chamada: ast.Call) -> bool:
    """O primeiro argumento desta chamada e o nome `self`?"""
    return bool(
        chamada.args
        and isinstance(chamada.args[0], ast.Name)
        and chamada.args[0].id == "self"
    )


def _de_dataclasses(arvore: ast.AST) -> bool:
    """O ficheiro faz `from dataclasses import replace`?"""
    return any(
        no.module == "dataclasses" and any(a.name == "replace" for a in no.names)
        for no in ast.walk(arvore)
        if isinstance(no, ast.ImportFrom)
    )


def verificar(fonte: str, *, e_o_modulo_do_selo: bool = False) -> list[str]:
    """Os achados sobre uma fonte. Lista vazia e conforme.

    `e_o_modulo_do_selo` dispensa as regras dos nomes privados e da construcao: o
    `privacidade/minimizacao.py` **tem** de os referir e de construir o
    `MinimisedText` — e o unico que pode.
    """
    try:
        arvore = ast.parse(fonte)
    except SyntaxError as erro:  # pragma: no cover — fonte do repositorio compila
        return [f"a fonte nao compila: {erro}"]

    achados: list[str] = []

    def apontar(regra: str, onde: str = "") -> None:
        sufixo = f" ({onde})" if onde else ""
        achados.append(f"{regra}{sufixo} — {MENSAGENS[regra]}")

    ligados = _literais_atribuidos(arvore)
    chamadas = [no for no in ast.walk(arvore) if _e_chamada_ao_gateway(no)]
    for chamada in chamadas:
        argumento = _mensagens_de(chamada)
        if argumento is None:
            continue
        alvo = _desembrulhar(argumento)
        # Pelo **valor** e nao pela forma: um literal directo, ou uma variavel
        # ligada a um literal mais atras.
        if isinstance(alvo, ast.Name) and alvo.id in ligados:
            alvo = ligados[alvo.id]
        if _tem_dicionario_de_mensagem(alvo):
            apontar(ARGUMENTO_LITERAL, f"linha {chamada.lineno}")

    if e_o_modulo_do_selo:
        return achados

    # Os nomes que este ficheiro deu ao `MinimisedText`, incluindo os alias de
    # `import`. **Sem isto, `from .minimizacao import MinimisedText as _T`
    # desarmava a regra da construcao** — a terceira evasao do achado 4.
    nomes_do_tipo = {TIPO}
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            for alias in no.names:
                if alias.name == TIPO and alias.asname:
                    nomes_do_tipo.add(alias.asname)
                if alias.name in PRIVADOS:
                    apontar(SELO_FORA_DO_MODULO, f"linha {no.lineno}")

    for no in ast.walk(arvore):
        if isinstance(no, ast.Name) and no.id in PRIVADOS:
            apontar(SELO_FORA_DO_MODULO, f"linha {no.lineno}")
        if isinstance(no, ast.Attribute) and no.attr in PRIVADOS:
            apontar(SELO_FORA_DO_MODULO, f"linha {no.lineno}")
        if not isinstance(no, ast.Call):
            continue
        # `MinimisedText(...)`, `mod.MinimisedText(...)`, `_T(...)` por alias, e
        # **`dataclasses.replace(...)`**, que era a primeira forja: reinvoca o
        # construtor com o selo do objecto de partida.
        alvo = no.func
        if isinstance(alvo, ast.Name) and alvo.id in nomes_do_tipo:
            apontar(CONSTRUCAO, f"linha {no.lineno}")
        elif isinstance(alvo, ast.Attribute) and alvo.attr == TIPO:
            apontar(CONSTRUCAO, f"linha {no.lineno}")
        # **`dataclasses.replace` e `object.__setattr__`, com o dono exigido.**
        #
        # A primeira versao perguntava so pelo nome do atributo (`attr in {TIPO,
        # "replace"}`) e dava **doze** achados na fonte do AGR: `texto.replace(...)`
        # e um metodo de cadeia e aparece em todo o lado. Um portao que avermelha
        # doze sitios conformes e um portao que alguem desliga — a mesma licao que
        # o `CONFORMES` desta politica paga pelo outro lado.
        #
        # Exige-se o dono: `dataclasses.replace` e `object.__setattr__`, que sao
        # as duas formas que a revisao adversarial mediu.
        elif (
            isinstance(alvo, ast.Attribute)
            and isinstance(alvo.value, ast.Name)
            and (
                (alvo.value.id == "dataclasses" and alvo.attr == "replace")
                or (
                    alvo.value.id == "object"
                    and alvo.attr == "__setattr__"
                    # **Excepto sobre o proprio `self`, e nao e cortesia.** Um
                    # `object.__setattr__(self, ...)` dentro do `__post_init__`
                    # de um dataclass `frozen` e **o** idioma para preencher um
                    # campo derivado, e o `verticais/vendedor/nos.py` usa-o para
                    # o relogio por omissao. A forja que a revisao mediu era
                    # sobre **outro** objecto: `object.__setattr__(minimo,
                    # "texto", cru)`. A regra distingue os dois pelo primeiro
                    # argumento, que e a diferenca real entre preencher-se e
                    # adulterar outra coisa.
                    and not _primeiro_e_self(no)
                )
            )
        ):
            apontar(CONSTRUCAO, f"linha {no.lineno}")
        # O `replace` importado directamente de `dataclasses`.
        elif isinstance(alvo, ast.Name) and alvo.id == "replace" and _de_dataclasses(arvore):
            apontar(CONSTRUCAO, f"linha {no.lineno}")

    return achados


def avisos(fonte: str) -> list[str]:
    """O `CHAMAR_SEM_MINIMISE`, que e aviso e nao recusa. Ver a nota do modulo."""
    try:
        arvore = ast.parse(fonte)
    except SyntaxError:  # pragma: no cover
        return []
    chama = any(_e_chamada_ao_gateway(no) for no in ast.walk(arvore))
    if not chama:
        return []
    importa = any(
        PACOTE in (no.module or "")
        for no in ast.walk(arvore)
        if isinstance(no, ast.ImportFrom)
    ) or any(
        PACOTE in alias.name
        for no in ast.walk(arvore)
        if isinstance(no, ast.Import)
        for alias in no.names
    )
    if importa:
        return []
    return [f"{CHAMAR_SEM_MINIMISE} — {MENSAGENS[CHAMAR_SEM_MINIMISE]}"]


#: Os canarios: fontes que **tem** de ser recusadas, uma por regra obrigatoria.
#:
#: Sem isto, «o repositorio esta conforme» e uma afirmacao que um `verificar`
#: que devolvesse sempre `[]` satisfazia. E a licao que o `log_policy` escreveu e
#: que o `politica_ast.py` repetiu.
CANARIOS: Final = {
    ARGUMENTO_LITERAL: (
        "def correr(cliente, ctx):\n"
        '    return cliente.chamar("chat", [{"role": "user", "content": "ola"}], ctx)\n'
    ),
    SELO_FORA_DO_MODULO: (
        "from .minimizacao import _impressao, MinimisedText\n"
        "\n"
        "def fingir(texto):\n"
        "    return _impressao(texto)\n"
    ),
    CONSTRUCAO: (
        "from .minimizacao import MinimisedText\n"
        "\n"
        "def fingir(texto):\n"
        "    return MinimisedText(texto, None)\n"
    ),
}

#: **As evasoes, e sao canarios como os outros.**
#:
#: O achado 4 da revisao adversarial mediu quatro formas de desarmar a primeira
#: versao desta politica, e a licao e a do `politica_ast.py` do KAM-034: as
#: evasoes nao se corrigem a olho — escrevem-se, e poe-se a politica a recusa-las.
#: Sem isto, os `CANARIOS` cobriam as tres regras **na forma mais ingenua de
#: cada uma** e nenhuma evasao, que e um canario que nao morde onde interessa.
#:
#: Cada entrada e `(regra, nome, fonte)`: a fonte tem de ser recusada **por
#: aquela** regra.
EVASOES: Final = (
    (
        ARGUMENTO_LITERAL,
        "o literal por variavel",
        "def correr(cliente, ctx, texto):\n"
        '    cru = [{"role": "user", "content": texto}]\n'
        '    return cliente.chamar("chat", cru, ctx)\n',
    ),
    (
        ARGUMENTO_LITERAL,
        "o literal por palavra-chave",
        "def correr(cliente, ctx, texto):\n"
        '    return cliente.chamar("chat", mensagens=[{"role": "user", "content": texto}])\n',
    ),
    (
        CONSTRUCAO,
        "o `dataclasses.replace`",
        "import dataclasses\n"
        "\n"
        "def fingir(minimo, cru):\n"
        "    return dataclasses.replace(minimo, texto=cru)\n",
    ),
    (
        CONSTRUCAO,
        "o `object.__setattr__`",
        "def fingir(minimo, cru):\n"
        '    object.__setattr__(minimo, "texto", cru)\n'
        "    return minimo\n",
    ),
    (
        CONSTRUCAO,
        "o `import ... as` do tipo",
        "from .minimizacao import MinimisedText as _T\n"
        "\n"
        "def fingir(cru, impressao):\n"
        "    return _T(cru, impressao)\n",
    ),
    (
        SELO_FORA_DO_MODULO,
        "a chave por atributo de modulo",
        "from . import minimizacao\n"
        "\n"
        "def fingir(texto):\n"
        "    return minimizacao._impressao(texto)\n",
    ),
)

#: As fontes que **tem** de passar: o caminho correcto e as suas variantes.
#:
#: **Existe porque a primeira versao desta politica recusava o caminho certo.**
#: Uma politica sem controlo positivo e satisfeita por uma que recuse tudo, e foi
#: exactamente o que aconteceu: o `argumento_literal` disparava sobre
#: `[mensagem("user", minimo)]`, que e a forma que a propria mensagem da regra
#: recomenda por escrito. Nao mordia hoje so porque o varrimento le
#: `services/agr/src/kamba_agr`, onde nao ha chamador nenhum — isto e, estava a
#: espera do dia em que o grafo chamasse o gateway de forma idiomatica para
#: avermelhar o *gate* 4 sobre codigo conforme.
CONFORMES: Final = (
    (
        "a lista de `mensagem(...)`, que e a forma recomendada",
        "from ..privacidade import mensagem, minimise\n"
        "\n"
        "def correr(cliente, ctx, texto, ctx_min):\n"
        "    minimo, _mapa = minimise(texto, ctx_min)\n"
        '    return cliente.chamar("chat", [mensagem("user", minimo)], ctx)\n',
    ),
    (
        "a lista construida numa variavel",
        "from ..privacidade import mensagem, minimise\n"
        "\n"
        "def correr(cliente, ctx, texto, ctx_min):\n"
        "    minimo, _mapa = minimise(texto, ctx_min)\n"
        '    msgs = [mensagem("system", minimo), mensagem("user", minimo)]\n'
        '    return cliente.chamar("chat", msgs, ctx)\n',
    ),
    (
        "um dicionario que nao e de mensagem",
        "def correr(cliente, ctx, msgs):\n"
        '    opcoes = {"temperatura": 0}\n'
        '    return cliente.chamar("chat", msgs, ctx)\n',
    ),
)
