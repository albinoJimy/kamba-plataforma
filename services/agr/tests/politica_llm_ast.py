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
#: O nome do selo privado do `minimizacao.py`.
SELO: Final = "_SELO"
#: O nome do tipo selado.
TIPO: Final = "MinimisedText"
#: O pacote que tem de aparecer nos `import` de quem minimiza.
PACOTE: Final = "privacidade"

MENSAGENS: Final = {
    ARGUMENTO_LITERAL: (
        "o argumento `mensagens` do `chamar()` e um literal: o gateway de LLM "
        "so aceita `MensagemMinimizada`, que se obtem de "
        "`privacidade.mensagem(papel, minimise(texto, ctx)[0])`. Um literal "
        "aqui e texto do cliente a sair para um fornecedor sem passar pelo "
        "detector de PII (KAM-112 criterio 1; ADR-008, ADR-010)"
    ),
    SELO_FORA_DO_MODULO: (
        f"o `{SELO}` do `privacidade/minimizacao.py` e referido fora dele: o "
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


def verificar(fonte: str, *, e_o_modulo_do_selo: bool = False) -> list[str]:
    """Os achados sobre uma fonte. Lista vazia e conforme.

    `e_o_modulo_do_selo` dispensa as regras do selo e da construcao: o
    `privacidade/minimizacao.py` **tem** de referir o `_SELO` e de construir o
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

    chamadas = [no for no in ast.walk(arvore) if _e_chamada_ao_gateway(no)]
    for chamada in chamadas:
        argumento = _mensagens_de(chamada)
        if argumento is None:
            continue
        if isinstance(_desembrulhar(argumento), _LITERAIS):
            apontar(ARGUMENTO_LITERAL, f"linha {chamada.lineno}")

    if not e_o_modulo_do_selo:
        for no in ast.walk(arvore):
            if isinstance(no, ast.Name) and no.id == SELO:
                apontar(SELO_FORA_DO_MODULO, f"linha {no.lineno}")
            # `from .minimizacao import _SELO` tambem conta, e nao e um `Name`.
            if isinstance(no, ast.ImportFrom):
                for alias in no.names:
                    if alias.name == SELO:
                        apontar(SELO_FORA_DO_MODULO, f"linha {no.lineno}")
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Name)
                and no.func.id == TIPO
            ):
                apontar(CONSTRUCAO, f"linha {no.lineno}")
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and no.func.attr == TIPO
            ):
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
        "from .minimizacao import _SELO, MinimisedText\n"
        "\n"
        "def fingir(texto):\n"
        "    return _SELO\n"
    ),
    CONSTRUCAO: (
        "from .minimizacao import MinimisedText\n"
        "\n"
        "def fingir(texto):\n"
        "    return MinimisedText(texto, None)\n"
    ),
}
