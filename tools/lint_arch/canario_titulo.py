"""O canario da verificacao do titulo do PR — KAM-164, criterio 5.

Uma verificacao que passa nao diz se morde. Este repositorio ja pagou duas vezes
por confiar num `unittest` para o provar: o *gate* 9 esteve sete PR sem nada que
o provasse, e o primeiro canario do *gate* 3b dava verde com a lista de casos
vazia (`docs/ci.md` §3). Por isso o canario corre **no proprio passo de CI**, e
tambem dentro do `make lint-arch` — isto e, dentro do *gate* 2 —, para que
`make ci` o corra sem passar pelo GitHub.

A forma e por **fixtures em memoria** e nao por mutacao da arvore, ao contrario
do `supply_chain` e do `env_lint`: o que se verifica aqui e uma unica cadeia de
caracteres lida de um evento do GitHub, pelo que o caso mau e um literal e nao
uma arvore de ficheiros. Nao ha nada para copiar nem para limpar, e o canario nao
toca no disco.

Tres propriedades o impedem de se esvaziar. As duas primeiras vem do
`tools/log_policy/lint.py`; a terceira e uma licao paga **neste** ticket:

1. **A lista e codigo, nao configuracao.** Nao ha ficheiro que alguem possa
   esvaziar para o canario passar.
2. **`REGRAS_DO_TITULO` prende as regras que tem de continuar a ter caso
   negativo.** Uma regra que deixe de morder — ou que alguem apague do
   `check_pr_title` — deixa de ter quem a prove, e o canario diz o nome dela.
3. **Cada regra reconhece-se por um padrao ancorado, e nao por um pedaco de
   texto.** A primeira versao usava fragmentos (`"o maximo e"`), e dois achados
   diferentes partilhavam-no: o do cabecalho longo («titulo com 165 caracteres;
   o maximo e 120») e o da descricao longa («descricao com 150 caracteres; o
   maximo e 100»). O unico negativo da descricao longa estourava tambem o
   cabecalho, pelo que a regra ficava marcada como provada **pela regra errada**
   — e com `subjectMaxLength` desligada o canario ficava **verde**, medido. Era
   exactamente o modo de falha que este modulo declara impedir: «ser apanhado por
   outra regra e sorte, nao cobertura». Com padroes ancorados a confusao nao e
   possivel, seja qual for a mensagem que se acrescente a seguir. Achado da
   revisao adversarial do KAM-164.

Codigos de saida, como no resto da casa: 0 = o canario morde, 1 = deixou de
morder.
"""

from __future__ import annotations

import re

from . import conventions

#: Cada regra que `conventions.check_pr_title` sabe produzir, pelo padrao
#: **ancorado** que so a mensagem dela satisfaz. Fixas aqui e **nao** derivadas
#: dos casos abaixo: uma lista derivada dos proprios casos encolhe com eles e da
#: «0 regras, tudo verde» (`docs/analises/ANALISE-05`, B1).
REGRAS_DO_TITULO: tuple[tuple[str, str], ...] = (
    ("forma", r"^titulo fora de "),
    ("titulo vazio", r"^titulo de PR vazio$"),
    ("titulo longo", r"^titulo com \d+ caracteres; o maximo e \d+$"),
    ("sufixo do squash", r"^o assunto do squash ficaria com \d+ caracteres"),
    ("ambito", r"^ambito "),
    ("descricao curta", r"^descricao com \d+ caracteres; o minimo e \d+$"),
    ("descricao longa", r"^descricao com \d+ caracteres; o maximo e \d+$"),
    ("ponto final", r"^descricao nao termina em ponto$"),
    ("minuscula", r"^descricao comeca em minuscula"),
    ("maiusculas", r"^descricao inteira em maiusculas$"),
)

_PADROES = {nome: re.compile(padrao) for nome, padrao in REGRAS_DO_TITULO}

#: Os titulos que **tem** de ser recusados, cada um pela sua regra. O primeiro e
#: o caso real: o assunto que o PR #75 deixou no `main` no `29778f3`, sem o
#: ` (#75)` que o GitHub acrescenta na fusao — e o titulo tal como ele estava no
#: PR, que e o que esta verificacao teria visto.
NEGATIVOS: tuple[tuple[str, str], ...] = (
    ("KAM-038 — Subscricao de eventos: as verticais acordam por evento", "forma"),
    ("", "titulo vazio"),
    ("   ", "titulo vazio"),
    ("arranjei o titulo do PR", "forma"),
    ("build(KAM-164): verifica o titulo do PR contra a convencao", "forma"),
    ("feat(KAM-164) verifica o titulo do PR contra a convencao", "forma"),
    ("feat(monorepo): verifica o titulo do PR contra a convencao", "ambito"),
    ("feat(kam-164): verifica o titulo do PR contra a convencao", "ambito"),
    ("feat(KAM-164): curto", "descricao curta"),
    # Descricao de 101 caracteres, cabecalho de 116: passa dos 100 da descricao
    # sem chegar aos 120 do cabecalho. Ja nao precisava de isolar a regra — os
    # padroes sao ancorados —, mas um negativo que estoure uma regra so continua
    # a ser o que se le melhor quando o canario fica vermelho.
    ("feat(KAM-164): " + "ab " * 34, "descricao longa"),
    ("feat(KAM-164): verifica o titulo do PR contra a convencao.", "ponto final"),
    ("feat(KAM-164): Verifica o titulo do PR contra a convencao", "minuscula"),
    ("feat(KAM-164): VERIFICA O TITULO DO PR CONTRA A CONVENCAO", "maiusculas"),
    # Cabecalho de 126: passa dos 120.
    ("feat(KAM-164): " + "ab " * 36 + "fim", "titulo longo"),
    # 119 caracteres — **abaixo** dos 120, pelo que nenhuma regra de cabecalho
    # morde; o que o recusa e o assunto projectado, que com o ` (#NNNN)` fica em
    # 127. E o caso que a revisao adversarial trouxe, e sem ele a gama de 113 a
    # 120 passava.
    ("refactor(KAM-164): " + "ab " * 33 + "a", "sufixo do squash"),
    # As dispensas do `git` nao valem para um titulo de PR, e um `Merge ...`
    # dispensado acabaria no `main` como assunto.
    ("Merge branch 'main' into feature/KAM-164-titulo-do-pr-verificado", "forma"),
    ('Revert "chore(KAM-001): cria a arvore do monorepo"', "forma"),
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
        padrao = _PADROES[regra]
        problemas = conventions.check_pr_title(titulo, rules)
        if not problemas:
            falhas.append(
                f"o titulo {titulo[:60]!r} passou e tinha de ser recusado por {regra!r}"
            )
            continue
        if not any(padrao.match(problema) for problema in problemas):
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

    for regra, _ in REGRAS_DO_TITULO:
        if regra not in vistas:
            falhas.append(
                f"sem caso negativo que prove {regra!r}: a regra pode ter deixado "
                "de morder sem ninguem dar por isso"
            )

    if len(POSITIVOS) < 2:
        falhas.append("menos de dois positivos: um lint que recusa tudo tambem passava")

    return falhas, {"negativos": len(NEGATIVOS), "positivos": len(POSITIVOS)}
