"""O canario da verificacao das mensagens dos *commits* — KAM-174, criterio 6.

Uma verificacao que passa nao diz se morde. Este repositorio ja pagou tres vezes
por confiar num `unittest` para o provar: o *gate* 9 esteve sete PR sem nada que
o provasse, o primeiro canario do *gate* 3b dava verde com a lista de casos vazia
(`docs/ci.md` §3), e o do titulo do PR dava verde com a regra do comprimento
desligada (ver `canario_titulo.py`). Por isso este corre **no proprio portao**,
dentro do `make lint-arch` — isto e, dentro do *gate* 2 —, pelo mesmo caminho do
canario do titulo e **sem abrir um segundo**.

Tem duas metades, porque ha duas coisas diferentes que podem deixar de morder:

1. **A funcao.** `conventions.check_commit_message` tem de continuar a recusar o
   que recusa, e **cada regra pela sua propria mensagem**. Por *fixtures* em
   memoria, como o canario do titulo: o que se verifica e uma cadeia de
   caracteres, pelo que o caso mau e um literal.
2. **A leitura do intervalo.** `commits.verificar_intervalo` tem de encontrar um
   assunto fora da forma **dentro** do intervalo, e tem de deixar fora o que esta
   fora dele. Esta metade precisa de uma arvore `git` de verdade — um intervalo
   nao e uma cadeia de caracteres — e por isso constroi um repositorio
   descartavel, com a forma exacta de um *merge ref* do GitHub: pai 1 a base,
   pai 2 a cabeca do ramo.

Tres propriedades impedem a primeira metade de se esvaziar. As duas primeiras vem
do `log_policy/lint.py`; a terceira e a licao que o canario do titulo pagou:

1. **A lista e codigo, nao configuracao.** Nao ha ficheiro que alguem possa
   esvaziar para o canario passar.
2. **`REGRAS_DA_MENSAGEM` prende as regras que tem de continuar a ter caso
   negativo.** Uma regra que deixe de morder — ou que alguem apague do
   `check_commit_message` — deixa de ter quem a prove, e o canario diz o nome
   dela.
3. **Cada regra reconhece-se por um padrao ancorado, e nao por um pedaco de
   texto.** Com fragmentos, dois achados diferentes partilham-no — «o maximo e»
   serve ao cabecalho longo e a descricao longa — e a regra fica marcada como
   provada **pela regra errada**. Foi medido no KAM-164: com `subjectMaxLength`
   desligada o canario ficava verde.

Codigos de saida, como no resto da casa: 0 = o canario morde, 1 = deixou de
morder.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import tempfile
from pathlib import Path

from . import commits as commits_module
from . import conventions

#: Cada regra que `conventions.check_commit_message` sabe produzir, pelo padrao
#: **ancorado** que so a mensagem dela satisfaz. Fixas aqui e **nao** derivadas
#: dos casos abaixo: uma lista derivada dos proprios casos encolhe com eles e da
#: «0 regras, tudo verde» (`docs/analises/ANALISE-05`, B1).
REGRAS_DA_MENSAGEM: tuple[tuple[str, str], ...] = (
    ("mensagem vazia", r"^mensagem de commit vazia$"),
    ("forma", r"^cabecalho fora de "),
    ("cabecalho longo", r"^cabecalho com \d+ caracteres; o maximo e \d+$"),
    ("ambito", r"^ambito "),
    ("descricao curta", r"^descricao com \d+ caracteres; o minimo e \d+$"),
    ("descricao longa", r"^descricao com \d+ caracteres; o maximo e \d+$"),
    ("ponto final", r"^descricao nao termina em ponto$"),
    ("minuscula", r"^descricao comeca em minuscula"),
    ("maiusculas", r"^descricao inteira em maiusculas$"),
    ("corpo sem linha em branco", r"^falta uma linha em branco entre o cabecalho"),
    ("rodape sem linha em branco", r"^falta uma linha em branco antes do rodape "),
)

_PADROES = {nome: re.compile(padrao) for nome, padrao in REGRAS_DA_MENSAGEM}

#: A mensagem do achado A1 da revisao adversarial do KAM-174, e o unico caso em
#: que os dois modos de `tirar_comentarios` divergem — por isso vive numa
#: constante: serve de caso negativo **e** de prova de que o parametro faz algo.
#:
#: Com `-m` o *cleanup* do `git` e `whitespace`, que nao tira comentarios: esta
#: mensagem fica guardada como esta, e o `git` usa a **primeira** linha como
#: `%s`. A funcao julgava a segunda — a conforme — pelo que num PR de um so
#: *commit* o `#123 …` ia para o `main` fora da forma.
A1_CARDINAL = "#123 arrumacoes no modulo\n\nfix(KAM-174): le as mensagens dos commits"

#: As mensagens que **tem** de ser recusadas, cada uma pela sua regra.
#:
#: A primeira e o caso real: o assunto que o PR #75 deixou no `main` no
#: `29778f3`, sem o ` (#75)` que o GitHub acrescenta na fusao. Ele **nao** serve
#: de caso do varrimento — vive em `main`, e o criterio 3 existe para o manter
#: fora do intervalo —, mas serve de caso da funcao, que e onde o KAM-164 ja o
#: usa.
NEGATIVOS: tuple[tuple[str, str], ...] = (
    ("KAM-038 — Subscricao de eventos: as verticais acordam por evento", "forma"),
    ("", "mensagem vazia"),
    ("   \n  \n", "mensagem vazia"),
    ("arrumacoes", "forma"),
    # **Achado A1 da revisao adversarial.** Com `-m` o *cleanup* do `git` e
    # `whitespace`, que nao tira comentarios: esta mensagem fica guardada como
    # esta, e o `git` usa a **primeira** linha como `%s`. A funcao julgava a
    # segunda — a conforme — e dava a mensagem por conforme, pelo que num PR de
    # um so *commit* o `#123 …` ia para o `main`. O canario corre a funcao no
    # modo do portao (`tirar_comentarios=False`), que e onde isto se recusa.
    (A1_CARDINAL, "forma"),
    ("# arrumacoes sem cardinal a seguir", "forma"),
    # O caso que uma sessao desta casa escreveu a mao a trazer a `main` para
    # dentro do ramo, e que o *hook* recusou: minuscula e com dois pontos, pelo
    # que nao casa a isencao `^Merge ` **nem** casa tipo nenhum. Nao confundir
    # com o `Merge branch ...` que o `git` escreve por omissao, que e isento e
    # esta nos positivos.
    ("merge: traz a main", "forma"),
    ("build(KAM-174): le as mensagens dos commits do intervalo", "forma"),
    ("fix(KAM-174) le as mensagens dos commits do intervalo", "forma"),
    ("fix(monorepo): le as mensagens dos commits do intervalo", "ambito"),
    ("fix(kam-174): le as mensagens dos commits do intervalo", "ambito"),
    ("fix(KAM-174): curto", "descricao curta"),
    # Descricao de 101 caracteres, cabecalho de 116: passa dos 100 da descricao
    # sem chegar aos 120 do cabecalho. Ja nao precisava de isolar a regra — os
    # padroes sao ancorados —, mas um negativo que estoure uma regra so continua
    # a ser o que se le melhor quando o canario fica vermelho.
    ("fix(KAM-174): " + "ab " * 34, "descricao longa"),
    ("fix(KAM-174): le as mensagens dos commits do intervalo.", "ponto final"),
    ("fix(KAM-174): Le as mensagens dos commits do intervalo", "minuscula"),
    ("fix(KAM-174): LE AS MENSAGENS DOS COMMITS DO INTERVALO", "maiusculas"),
    # Cabecalho de 126: passa dos 120.
    ("fix(KAM-174): " + "ab " * 37 + "fim", "cabecalho longo"),
    # As duas regras do corpo, que o *hook* impoe e que um varrimento que lesse
    # so o assunto nao veria. E a razao por que `mensagens_do_intervalo` da a
    # mensagem inteira: dar so o assunto fazia o *gate* aceitar o que o *hook*
    # recusa.
    (
        "fix(KAM-174): le as mensagens dos commits do intervalo\no corpo colado ao cabecalho",
        "corpo sem linha em branco",
    ),
    (
        "fix(KAM-174): le as mensagens dos commits do intervalo\n\n"
        "o corpo em condicoes\nRefs: KAM-002",
        "rodape sem linha em branco",
    ),
)

#: As mensagens que **tem** de passar. Um lint que recusasse tudo tambem passava
#: um canario que so tivesse negativos.
#:
#: Os quatro primeiros sao assuntos reais de `main`, sem o ` (#NN)` do GitHub. Os
#: quatro seguintes sao as `exemptHeaderPatterns` do `tools/conventions.json`,
#: que **nao** se reimplementam nem se endurecem aqui (criterio 8) — e o
#: `Merge branch ...` e o que o `git` escreve **por omissao** quando um PR traz a
#: `main` para dentro, pelo que ele passar e a diferenca entre uma regra pequena
#: e uma regra que morde uma operacao frequente. Medido a 2026-11-03: ha 12
#: desses nos ultimos 300 *commits* de `main`.
POSITIVOS: tuple[str, ...] = (
    "fix(KAM-173): a ordem de carregamento do unittest deixa de poder fazer uma suite passar",
    "chore(KAM-174): abre o ticket das mensagens de commit sem portao",
    "docs(KAM-161): o registo de entrega nas duas tabelas de versoes",
    "feat(KAM-034): handoff idempotente em dois nos e retoma por compare-and-set\n\n"
    "O corpo com a linha em branco antes, como o commitlint pede.\n\n"
    "Refs: KAM-019",
    "Merge branch 'main' into feature/KAM-174-mensagens-de-commit-no-gate-2",
    "Merge pull request #47 from albinoJimy/fix/KAM-149-codeowners-no-prefixo-removido",
    'Revert "chore(KAM-001): cria a arvore do monorepo"',
    "fixup! fix(KAM-174): le as mensagens dos commits do intervalo",
    # **Dois rodapes seguidos.** E a forma normal de os escrever, e e a que o
    # GitHub compoe na mensagem de *squash* — a do proprio KAM-174 (`c75d5234`)
    # leva dois `Co-authored-by` em linhas consecutivas. A versao anterior do
    # `_check_body_and_footer` exigia linha em branco antes de **cada** rodape e
    # recusava-os: um falso positivo que este ticket tornou bloqueante, porque
    # ate ele nenhum portao lia mensagens de *commit*. Sem este positivo, o dia
    # em que a regra voltar a apertar passa sem ninguem dar por isso.
    "fix(KAM-174): le as mensagens dos commits do intervalo\n"
    "\n"
    "O corpo em condicoes.\n"
    "\n"
    "Co-authored-by: Armando Albino <a@b.c>\n"
    "Co-authored-by: Claude Opus 5 <noreply@anthropic.com>",
    "fix(KAM-174): le as mensagens dos commits do intervalo\n"
    "\n"
    "O corpo em condicoes.\n"
    "\n"
    "Refs: KAM-002\n"
    "Signed-off-by: Alguem <a@b.c>",
)


def _canario_da_funcao(rules: conventions.Conventions) -> tuple[list[str], dict[str, int]]:
    """A primeira metade: cada regra do `check_commit_message` continua a morder.

    Corre a funcao **no modo do portao** (`tirar_comentarios=False`), que e o que
    o *gate* 2 usa sobre mensagens lidas da historia. Um canario que corresse o
    modo do *hook* nao provava nada sobre o caminho que morde — e era por ali que
    o achado A1 passava.
    """
    falhas: list[str] = []
    vistas: set[str] = set()

    for mensagem, regra in NEGATIVOS:
        padrao = _PADROES[regra]
        problemas = conventions.check_commit_message(
            mensagem, rules, tirar_comentarios=False
        )
        amostra = " ".join(mensagem.split())[:60]
        if not problemas:
            falhas.append(
                f"a mensagem {amostra!r} passou e tinha de ser recusada por {regra!r}"
            )
            continue
        if not any(padrao.match(problema) for problema in problemas):
            falhas.append(
                f"a mensagem {amostra!r} foi recusada, mas por {problemas} e nao "
                f"por {regra!r}: ser apanhado por outra regra e sorte, nao cobertura"
            )
            continue
        vistas.add(regra)

    for mensagem in POSITIVOS:
        problemas = conventions.check_commit_message(
            mensagem, rules, tirar_comentarios=False
        )
        if problemas:
            amostra = " ".join(mensagem.split())[:60]
            falhas.append(
                f"a mensagem conforme {amostra!r} foi recusada: {problemas}"
            )

    # O modo do *hook* tambem tem de continuar a morder e a nao morder: ele le o
    # `COMMIT_EDITMSG` **antes** do *cleanup*, com o bloco de comentarios que o
    # editor escreve, e esse bloco nao pode fazer uma mensagem conforme falhar.
    # Sem este par, a distincao entre os dois modos ficava sem prova nenhuma e
    # qualquer um deles podia desaparecer em silencio.
    com_bloco_do_editor = (
        "fix(KAM-174): le as mensagens dos commits do intervalo\n"
        "\n"
        "# Please enter the commit message for your changes. Lines starting\n"
        "# with '#' will be ignored, and an empty message aborts the commit.\n"
    )
    if conventions.check_commit_message(com_bloco_do_editor, rules):
        falhas.append(
            "no modo do hook, o bloco de comentarios do editor fez uma mensagem "
            "conforme falhar: a remocao de comentarios deixou de funcionar"
        )
    # E a prova de que os dois modos sao mesmo **diferentes**, na mensagem onde
    # eles divergem — que e a do achado A1. No modo do hook ela e conforme (a
    # linha do cardinal e tratada como comentario e salta-se); no modo do portao
    # nao e (essa linha e o assunto). Se os dois dessem o mesmo, o parametro nao
    # estaria a fazer nada e o A1 voltava sem ninguem dar por isso.
    como_hook = conventions.check_commit_message(A1_CARDINAL, rules)
    como_portao = conventions.check_commit_message(
        A1_CARDINAL, rules, tirar_comentarios=False
    )
    if como_hook:
        falhas.append(
            "no modo do hook a mensagem do A1 passou a ser recusada: a remocao "
            f"de comentarios deixou de funcionar ({como_hook})"
        )
    if not como_portao:
        falhas.append(
            "no modo do portao a mensagem do A1 passou: `tirar_comentarios` "
            "deixou de distinguir a entrada do hook da entrada da historia, e um "
            "assunto que comeca por `#` volta a ir para o main fora da forma"
        )

    for regra, _ in REGRAS_DA_MENSAGEM:
        if regra not in vistas:
            falhas.append(
                f"sem caso negativo que prove {regra!r}: a regra pode ter deixado "
                "de morder sem ninguem dar por isso"
            )

    if len(POSITIVOS) < 2:
        falhas.append("menos de dois positivos: um lint que recusa tudo tambem passava")

    return falhas, {"negativos": len(NEGATIVOS), "positivos": len(POSITIVOS)}


# ---------------------------------------------------------------------------
# A segunda metade: o intervalo
# ---------------------------------------------------------------------------

#: O assunto fora da forma que tem de ser encontrado **dentro** do intervalo.
ASSUNTO_MAU = "arrumacoes no modulo dos commits"

#: O assunto conforme que o acompanha no mesmo intervalo: o canario tem de
#: distinguir, nao de recusar tudo.
ASSUNTO_BOM = "fix(KAM-174): le as mensagens dos commits do intervalo"

#: Assunto **conforme** com o corpo colado ao cabecalho, isto e, mensagem fora
#: da forma. Existe para que as regras do corpo tenham prova **no portao**: sem
#: ele, trocar `%B` por `%s` deixava o canario verde (achado A11).
ASSUNTO_COM_CORPO_COLADO = (
    "fix(KAM-174): o assunto esta conforme e o corpo esta colado\n"
    "o corpo sem linha em branco antes"
)

#: Quantos *commits* o ramo da arvore descartavel acrescenta. Escrito aqui e
#: confrontado com o que o varrimento conta: se os dois pais vierem trocados ou
#: iguais, a contagem nao bate e o canario diz qual era.
COMMITS_DO_RAMO = 4

#: O assunto do *commit* que fica em `main`, isto e, **antes** da base do
#: intervalo. Esta fora da forma de proposito: se o varrimento o encontrasse,
#: estaria a ler o que o criterio 3 existe para nao ler.
#: O numero e o do exemplar real (`29778f3`, PR #75) e **nao** um inventado: o
#: `lint_refs` varre este ficheiro e exige que cada identificador de ticket exista
#: no §4 do `specs/INDICE.md`. Um numero inventado num literal e uma referencia
#: invalida como qualquer outra — medido, deu dois achados, e o comentario que o
#: explicava escrevendo-o deu um terceiro.
ASSUNTO_DE_MAIN = "KAM-038 — um assunto historico que ninguem pode corrigir"

#: O assunto do *merge* sintetico, na forma exacta em que o GitHub o escreve
#: (medido em `refs/pull/112/merge` a 2026-11-03: `Merge <cabeca> into <base>`).
#: Fica fora do intervalo **por construcao** — e a cabeca do `rev-list`, nao um
#: elemento dele —, e e isso que a passagem com as isencoes retiradas prova.
ASSUNTO_DO_MERGE = "Merge {cabeca} into {base}"


def _git(raiz: Path, *argumentos: str) -> None:
    subprocess.run(
        ["git", *argumentos],
        cwd=raiz,
        check=True,
        capture_output=True,
    )


def _commit(raiz: Path, ficheiro: str, mensagem: str) -> None:
    with (raiz / ficheiro).open("a", encoding="utf-8") as handle:
        handle.write(f"{mensagem}\n")
    _git(raiz, "add", ficheiro)
    # `--no-verify` de proposito: o repositorio descartavel nao tem hooks, mas um
    # `core.hooksPath` global de quem corre isto apanharia o canario e recusaria
    # o commit mau — que e precisamente o commit de que o canario precisa.
    _git(raiz, "commit", "--no-verify", "-m", mensagem)


def _arvore_descartavel(raiz: Path) -> str:
    """Um repositorio com a forma exacta de um *merge ref* do GitHub.

    Devolve o SHA do *merge*, cujo **pai 1 e a base** e cujo **pai 2 e a cabeca
    do ramo** — que e a ordem medida em `refs/pull/112/merge` e a que
    `commits.decidir_intervalo` assume. Construir ao contrario (`git merge main`
    com o ramo em `HEAD`) daria a ordem inversa, e ha um desses no proprio
    repositorio (`33af7f5`): e por isso que esta funcao faz o *merge* **a partir
    da base**.
    """
    _git(raiz, "init", "--initial-branch=main", "--quiet")
    _git(raiz, "config", "user.email", "canario@kamba.local")
    _git(raiz, "config", "user.name", "canario")
    # Sem assinatura: a maquina de quem corre isto pode ter `commit.gpgsign`
    # ligado, e o canario nao pede chaves a ninguem.
    _git(raiz, "config", "commit.gpgsign", "false")

    _commit(raiz, "historia.txt", ASSUNTO_DE_MAIN)
    _git(raiz, "checkout", "--quiet", "-b", "ramo")
    _commit(raiz, "ramo.txt", ASSUNTO_BOM)
    _commit(raiz, "ramo.txt", ASSUNTO_MAU)
    # **Achado A11.** Sem um *commit* com corpo na arvore, as regras do corpo
    # ficavam provadas so por `unittest` e nao pelo portao: trocar `%B` por `%s`
    # em `mensagens_do_intervalo` deixava o canario **verde**, porque nenhum dos
    # outros *commits* tem corpo e o assunto bastava. Este tem, e esta colado ao
    # cabecalho de proposito.
    _commit(raiz, "ramo.txt", ASSUNTO_COM_CORPO_COLADO)
    # **Achado A1.** O assunto que comeca por `#`, na arvore e nao so em memoria:
    # prova no portao que a leitura da historia o recusa.
    _commit(raiz, "ramo.txt", A1_CARDINAL)
    cabeca = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=raiz,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    _git(raiz, "checkout", "--quiet", "main")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=raiz,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(
        raiz,
        "merge",
        "--no-ff",
        "--no-verify",
        "-m",
        ASSUNTO_DO_MERGE.format(cabeca=cabeca, base=base),
        "ramo",
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=raiz,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


#: A arvore descartavel, construida **uma vez por processo**.
#:
#: Nao e optimizacao prematura: construi-la custa oito invocacoes do `git`, e em
#: Windows isso sao segundos. Medido a 2026-11-03: com uma arvore por chamada, a
#: suite deste modulo levava 88 s, e a maior parte era o mesmo repositorio
#: construido vinte vezes. E esta casa ja pagou por isto — o `test_conventions`
#: le o corpus uma vez «porque varrer a arvore duas vezes custava meio minuto num
#: `make ci-4` que corre a cada PR».
#:
#: **E seguro porque a arvore nao depende das regras.** O que varia entre
#: chamadas e o `Conventions` que se passa ao varrimento; os *commits* sao os
#: mesmos. O `TemporaryDirectory` fica guardado aqui para que o seu finalizador
#: nao corra antes do fim do processo.
_ARVORE: tuple[tempfile.TemporaryDirectory[str], Path, str] | None = None


def _arvore_em_cache() -> tuple[Path, str]:
    """`(raiz, sha do merge)` da arvore descartavel deste processo."""
    global _ARVORE
    if _ARVORE is None:
        # `ignore_cleanup_errors`: em Windows o `git` deixa objectos em
        # leitura-apenas e a limpeza levanta `PermissionError`. Um canario que
        # falhe a arrumar a casa dava vermelho sem nada ter deixado de morder.
        temporaria = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        raiz = Path(temporaria.name)
        merge = _arvore_descartavel(raiz)
        _ARVORE = (temporaria, raiz, merge)
    return _ARVORE[1], _ARVORE[2]


def _canario_do_intervalo(rules: conventions.Conventions) -> tuple[list[str], dict[str, int]]:
    """A segunda metade: a leitura do intervalo encontra o mau e so o mau."""
    falhas: list[str] = []
    raiz, merge = _arvore_em_cache()
    intervalo = commits_module.decidir_intervalo("pull_request", merge)
    if intervalo.modo != commits_module.MODO_INTERVALO:
        return (
            [
                f"com um merge ref resoluvel o modo devia ser "
                f"{commits_module.MODO_INTERVALO!r} e foi {intervalo.modo!r}"
            ],
            {"commits": 0},
        )

    resultado = commits_module.verificar_intervalo(
        raiz, intervalo.pai1, intervalo.pai2, rules
    )
    assuntos = {achado.assunto for achado in resultado.achados}

    if resultado.commits != COMMITS_DO_RAMO:
        falhas.append(
            f"o intervalo tinha de ter os {COMMITS_DO_RAMO} commits do ramo e teve "
            f"{resultado.commits}: pai 1 e pai 2 vieram trocados, ou iguais"
        )
    # Cada assunto mau tem de ser encontrado **pela sua propria razao**: um deles
    # prova a forma, outro as regras do corpo (A11) e o terceiro o assunto que
    # comeca por `#` (A1). Agrupa-los numa contagem deixava qualquer um deles
    # desaparecer sem o canario dar por isso.
    for esperado, porque in (
        (ASSUNTO_MAU, "a forma do assunto"),
        (ASSUNTO_COM_CORPO_COLADO.split("\n")[0], "as regras do corpo (%B e nao %s)"),
        (A1_CARDINAL.split("\n")[0], "o assunto que comeca por `#` (achado A1)"),
    ):
        if esperado not in assuntos:
            falhas.append(
                f"o assunto {esperado[:50]!r} nao foi encontrado no intervalo: "
                f"deixou de haver prova no portao de {porque}"
            )
    if ASSUNTO_BOM in assuntos:
        falhas.append(
            f"o assunto conforme {ASSUNTO_BOM!r} foi recusado: uma verificacao "
            "que recusa tudo nao distingue nada"
        )
    if ASSUNTO_DE_MAIN in assuntos:
        falhas.append(
            f"o assunto {ASSUNTO_DE_MAIN!r} esta **antes** da base e apareceu "
            "nos achados: o intervalo esta a ler o que o criterio 3 existe "
            "para nao ler"
        )

    # O *merge* sintetico fica fora **por construcao**, nao por isencao. Prova-
    # se correndo a mesma passagem com as `exemptHeaderPatterns` **retiradas**:
    # sem elas, um `Merge ...` que estivesse dentro do intervalo apareceria.
    sem_isencoes = dataclasses.replace(rules, exempt_header_patterns=())
    resultado_sem = commits_module.verificar_intervalo(
        raiz, intervalo.pai1, intervalo.pai2, sem_isencoes
    )
    if not sem_isencoes.exempt_header_patterns == ():
        falhas.append("as isencoes nao foram retiradas: a prova nao prova nada")
    for achado in resultado_sem.achados:
        if achado.assunto.startswith("Merge "):
            falhas.append(
                f"o merge sintetico {achado.assunto[:50]!r} apareceu nos "
                "achados com as isencoes retiradas: ele fica fora por "
                "construcao do intervalo, nao por cair na isencao `^Merge `"
            )
    if ASSUNTO_MAU not in {a.assunto for a in resultado_sem.achados}:
        falhas.append(
            "com as isencoes retiradas o assunto mau deixou de ser "
            "encontrado: a segunda passagem nao esta a varrer nada"
        )

    return falhas, {"commits": resultado.commits}


def canario(rules: conventions.Conventions) -> tuple[list[str], dict[str, int]]:
    """Devolve as falhas e as contagens. Lista vazia = a verificacao morde."""
    falhas_funcao, numeros = _canario_da_funcao(rules)
    falhas_intervalo, numeros_intervalo = _canario_do_intervalo(rules)
    # As duas metades correm **sempre**, e as falhas juntam-se: parar na primeira
    # escondia a outra, e quem corre o canario quer a lista toda de uma vez.
    return falhas_funcao + falhas_intervalo, {**numeros, **numeros_intervalo}
