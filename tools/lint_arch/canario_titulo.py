"""O canario da verificacao do titulo do PR — KAM-164, criterio 5.

Uma verificacao que passa nao diz se morde. Este repositorio ja pagou duas vezes
por confiar num `unittest` para o provar: o *gate* 9 esteve sete PR sem nada que
o provasse, e o primeiro canario do *gate* 3b dava verde com a lista de casos
vazia (`docs/ci.md` §3). Por isso o canario corre **no proprio passo de CI**,
como segundo comando, ao lado da verificacao que protege — o padrao do
`log-lint`, do `money-lint` e do *gate* 11.

A forma e por **fixtures em memoria** e nao por mutacao da arvore, ao contrario
do `supply_chain` e do `env_lint`: o que se verifica aqui e uma unica cadeia de
caracteres lida de um evento do GitHub, pelo que o caso mau e um literal e nao
uma arvore de ficheiros. Nao ha nada para copiar nem para limpar, e o canario nao
toca no disco.

Duas propriedades que o impedem de se esvaziar, ambas copiadas do
`tools/log_policy/lint.py`:

1. **A lista e codigo, nao configuracao.** Nao ha ficheiro que alguem possa
   esvaziar para o canario passar.
2. **`REGRAS_DO_TITULO` prende as regras que tem de continuar a ter pelo menos um
   caso negativo.** Uma regra que deixe de morder — ou que alguem apague do
   `check_pr_title` — deixa de ter quem a prove, e o canario diz o nome dela.

Codigos de saida, como no resto da casa: 0 = o canario morde, 1 = deixou de
morder.
"""

from __future__ import annotations

from . import conventions

#: Cada regra que `conventions.check_pr_title` sabe produzir, pelo fragmento que
#: a identifica no achado. Fixas aqui e **nao** derivadas dos casos abaixo: uma
#: lista derivada dos proprios casos encolhe com eles e da «0 regras, tudo
#: verde» (`docs/analises/ANALISE-05`, B1).
REGRAS_DO_TITULO = (
    "titulo fora de",
    "titulo de PR vazio",
    "titulo com",
    "ambito",
    "o minimo e",
    "o maximo e",
    "descricao nao termina em ponto",
    "descricao comeca em minuscula",
    "descricao inteira em maiusculas",
)

#: Os titulos que **tem** de ser recusados, cada um pela sua regra. O primeiro e
#: o caso real: o assunto que o PR #75 deixou no `main` no `29778f3`, sem o
#: ` (#75)` que o GitHub acrescenta na fusao — e o titulo tal como ele estava no
#: PR, que e o que esta verificacao teria visto.
NEGATIVOS = (
    ("KAM-038 — Subscricao de eventos: as verticais acordam por evento", "titulo fora de"),
    ("", "titulo de PR vazio"),
    ("   ", "titulo de PR vazio"),
    ("arranjei o titulo do PR", "titulo fora de"),
    ("build(KAM-164): verifica o titulo do PR contra a convencao", "titulo fora de"),
    ("feat(KAM-164) verifica o titulo do PR contra a convencao", "titulo fora de"),
    ("feat(monorepo): verifica o titulo do PR contra a convencao", "ambito"),
    ("feat(kam-164): verifica o titulo do PR contra a convencao", "ambito"),
    ("feat(KAM-164): curto", "o minimo e"),
    ("feat(KAM-164): " + "a" * 150, "o maximo e"),
    ("feat(KAM-164): verifica o titulo do PR contra a convencao.", "descricao nao termina em ponto"),
    ("feat(KAM-164): Verifica o titulo do PR contra a convencao", "descricao comeca em minuscula"),
    ("feat(KAM-164): VERIFICA O TITULO DO PR CONTRA A CONVENCAO", "descricao inteira em maiusculas"),
    # O cabecalho longo: 120 e o maximo, e a descricao sozinha cabe nos 100.
    ("feat(KAM-164): " + "ab " * 36 + "fim", "titulo com"),
    # As dispensas do `git` nao valem para um titulo de PR, e um `Merge ...`
    # dispensado acabaria no `main` como assunto.
    ("Merge branch 'main' into feature/KAM-164-titulo-do-pr-verificado", "titulo fora de"),
    ('Revert "chore(KAM-001): cria a arvore do monorepo"', "titulo fora de"),
)

#: Os titulos que **tem** de passar. Sao os cinco assuntos de *squash* que estao
#: no `main` e estao conformes, sem o ` (#NN)` do GitHub: um lint que recusasse
#: tudo tambem passava um canario que so tivesse negativos.
POSITIVOS = (
    "chore(KAM-162): retira a agentic-engineering e põe a software-factory no seu lugar",
    "fix(KAM-019): a fronteira da saida de waiting da platform.handoffs (fecha o criterio 3 do KAM-034)",
    "docs(KAM-161): o registo de entrega nas duas tabelas de versoes",
    "docs(KAM-034): o bloco deixa de afirmar o que a revisao mudou",
    "feat(KAM-034): handoff idempotente em dois nos e retoma por compare-and-set",
)


def canario(rules: conventions.Conventions) -> tuple[list[str], dict[str, int]]:
    """Devolve as falhas e as contagens. Lista vazia = a verificacao morde."""
    falhas: list[str] = []
    vistas: set[str] = set()

    for titulo, regra in NEGATIVOS:
        problemas = conventions.check_pr_title(titulo, rules)
        if not problemas:
            falhas.append(
                f"o titulo {titulo[:60]!r} passou e tinha de ser recusado por {regra!r}"
            )
            continue
        if not any(regra in problema for problema in problemas):
            falhas.append(
                f"o titulo {titulo[:60]!r} foi recusado, mas por {problemas} "
                f"e nao por {regra!r}: ser apanhado por outra regra e sorte, nao cobertura"
            )
            continue
        vistas.add(regra)

    for titulo in POSITIVOS:
        problemas = conventions.check_pr_title(titulo, rules)
        if problemas:
            falhas.append(
                f"o assunto real {titulo[:60]!r} esta conforme e foi recusado: {problemas}"
            )

    for regra in REGRAS_DO_TITULO:
        if regra not in vistas:
            falhas.append(
                f"sem caso negativo que prove {regra!r}: a regra pode ter deixado "
                "de morder sem ninguem dar por isso"
            )

    if len(POSITIVOS) < 2:
        falhas.append("menos de dois positivos: um lint que recusa tudo tambem passava")

    return falhas, {"negativos": len(NEGATIVOS), "positivos": len(POSITIVOS)}
