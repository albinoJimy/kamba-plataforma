"""As mensagens dos *commits* que um PR acrescenta — KAM-174.

A forma do assunto de um *commit* era imposta pelo *hook* local
`tools/githooks/commit-msg` e por mais nada: dispensa-se com `--no-verify` e nao
existe num clone antes de `make hooks`. E a definicao do repositorio e
`squash_merge_commit_title: COMMIT_OR_PR_TITLE`, pelo que num PR de **um so**
*commit* o assunto desse *commit* vai para o `main` sem nada do lado do servidor
o ler. O KAM-164 fechou o caminho do **titulo do PR**; este modulo fecha o
caminho do **assunto do *commit***, que e o outro.

Entra no *gate* 2 pelo alvo `lint-arch`, e **nao** num *job* novo: um *job* novo
acrescenta um contexto exigido ao *ruleset* de `main`, e isso e alteracao de
regra de bloqueio, que e decisao do fundador. E o caminho pelo qual o `log-lint`
(KAM-068), o `money-lint` (KAM-052), o `env-lint` (KAM-075) e o canario do
titulo (KAM-164) entraram no mesmo *gate*.

O intervalo, e porque e que **nao** e o do *gate* 9
-----------------------------------------------------

O que se varre sao os *commits* proprios do PR: do **primeiro** ao **segundo**
pai do *merge ref* que o `actions/checkout` traz no evento `pull_request`.

**A ordem dos pais foi medida, nao suposta.** Em `refs/pull/112/merge` do
`albinoJimy/kamba-plataforma`, a 2026-11-03: o pai 1 e `507532f`, que era a ponta
de `main`, e o pai 2 e `9af3d05`, que era a cabeca do ramo. O assunto do proprio
*merge ref* e `Merge <cabeca> into <base>`, que diz a mesma coisa por extenso.
**A medicao tem de ser sobre o *merge ref* do GitHub e sobre mais nada:** um
*merge* feito a mao de dentro do ramo — `git merge main` com o ramo em `HEAD` —
tem a ordem **inversa**, e ha um desses neste repositorio (`33af7f5`, no ramo do
KAM-044). Tomar um pelo outro daria um intervalo invertido, que e o modo de falha
A3 do *gate* 9: zero *commits*, nada varrido, verde. O que prende a ordem e a
linha `GATE2_MERGE_REF: ${{ github.sha }}` do *job*, confrontada por
`tests/test_ci_gate2.py`.

Com este intervalo o *commit* de *merge* sintetico fica fora **por construcao**:
ele e a cabeca do `rev-list`, nao um dos seus elementos. Nao depende da isencao
`^Merge ` das `exemptHeaderPatterns`, e e por isso que o canario prova a exclusao
tambem com as isencoes retiradas.

**O *gate* 9 usa outro intervalo, e aqui nao serve.** Ele parte de
`github.event.pull_request.base.sha`, a ponta de `main` no momento do evento;
quando `main` anda, o intervalo passa a incluir o que fundiu **depois** dessa
base (esta escrito em `docs/ci.md` §3, e la e aceite de proposito). Nenhum dos
dois intervalos varre os assuntos historicos de `main` — sao todos alcancaveis da
base, e o `rev-list base..head` exclui o alcancavel da base por construcao. O que
torna o do *gate* 9 inaceitavel aqui e o que funde **enquanto o PR esta aberto**:
um assunto fora da forma que chegue a `main` nesse intervalo de tempo avermelha
um PR alheio, e o autor desse PR nao tem autorizacao para corrigir um *commit* de
`main` (criterio 7) nem meio de o dispensar. Um portao que avermelha por acto de
terceiro e um portao que se aprende a ignorar.

O que este modulo **nao** cobre esta escrito em `docs/ci.md` §3, no *gate* 2.

So biblioteca padrao e `git`, pela mesma razao que o resto do `lint_arch`: o
*gate* 2 corre o `lint_arch` sem instalar nada do lado do Python.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

from . import conventions

#: O modo em que a passagem corre quando ha intervalo.
MODO_INTERVALO = "intervalo"

#: O modo em que ela **nao** corre, e diz porque.
MODO_SEM_PASSAGEM = "sem-passagem"

#: O que cada accionamento faz. Esta escrito aqui, e nao deixado ao caso, porque
#: e isso que o criterio de aceitacao 5 pede: cada accionamento pelo nome, com a
#: sua razao. E esta escrito em **Python** e nao em YAML porque nao ha *lint* de
#: *workflows* neste repositorio (`docs/ci.md` §7, lacuna 14), pelo que uma
#: condicao em YAML nao seria verificavel por teste nenhum. E a razao que o
#: KAM-131 ja pagou, e a forma e a do `SEM_INTERVALO` de
#: `tools/scan_secrets/historia.py`.
#:
#: `None` = o intervalo e **obrigatorio**: sem *merge ref* resoluvel o *gate*
#: fica vermelho. Sao os accionamentos que decidem um *merge*.
#:
#: Uma cadeia = a passagem **nao corre**, e diz-se a razao. Nenhum destes decide
#: um *merge*, e em nenhum deles existe um PR com *commits* proprios.
ACCIONAMENTOS: dict[str, str | None] = {
    # O accionamento para que esta verificacao existe. O ponto de imposicao e o
    # PR, **antes** da fusao, porque e o unico momento em que o autor ainda pode
    # reescrever os seus proprios *commits*.
    "pull_request": None,
    # Por antecipacao, como o *gate* 9 fez com o `merge_group`: decide um *merge*,
    # logo intervalo obrigatorio. Nao esta no `on:` de hoje.
    "pull_request_target": None,
    # Idem. Sem esta linha, no dia em que a fila de *merge* se ligar o *gate*
    # ficava vermelho em **todas** as execucoes, por um accionamento nao escrito.
    "merge_group": None,
    # O que chega por `push` **ja fundiu**. Um vermelho sobre `main` nao tem
    # correccao possivel: os *commits* de `main` nao se reescrevem (criterio 7, e
    # a divida 170 fica como esta). E o *gate* 2 e contexto obrigatorio do
    # *ruleset* de `main`, pelo que um vermelho aqui travava o repositorio
    # inteiro depois de cada *merge*, sem autor que o possa corrigir.
    "push": (
        "`push`: o que chega por push ja fundiu, e um commit de `main` nao se "
        "reescreve. O ponto de imposicao e o PR, antes da fusao"
    ),
    # O caminho que o proprio `ci.yaml` documenta para reexecutar sem abrir PR.
    # Nao traz *merge ref*, e um vermelho em toda a reexecucao manual nao teria
    # autor que o corrigisse.
    "workflow_dispatch": "reexecucao a mao: o accionamento nao traz merge ref",
    # `make ci-2` na maquina de quem desenvolve, onde nao existe PR. Declara-se o
    # modo em vez de passar em silencio.
    "": "execucao local: GATE2_MERGE_REF nao esta definido e nao existe PR",
}


class IntervaloInvalido(ValueError):
    """O accionamento, o *merge ref* ou o clone nao servem para varrer o intervalo.

    Codigo de saida 2 no `cli`, e nao 1: uma configuracao quebrada nao pode
    parecer um PR conforme. E a mesma distincao que o resto do `lint_arch` faz.
    """


@dataclasses.dataclass(frozen=True)
class Intervalo:
    #: `intervalo` (ha o que varrer) ou `sem-passagem` (nao ha, e diz-se porque).
    modo: str
    #: Referencias, **nao** SHA: a resolucao e do `git` e faz-se em
    #: `verificar_intervalo`, para que `decidir_intervalo` fique pura.
    pai1: str = ""
    pai2: str = ""
    razao: str = ""


def decidir_intervalo(evento: str | None, merge_ref: str | None) -> Intervalo:
    """O intervalo a varrer, ou o modo em que se corre quando nao existe.

    Funcao pura: o *workflow* passa os valores em bruto do evento e **nao decide
    nada**.

    **Quem decide primeiro e o accionamento, nao a presenca do *merge ref*** — e
    e aqui que esta funcao divergir do `decidir_intervalo` do *gate* 9 e
    deliberado. Em `push` o evento traz um `github.sha` perfeitamente valido, e
    se a presenca de um SHA decidisse, a passagem corria sobre `main` depois de
    cada *merge*: o *commit* de um *squash* tem **um** pai, nao ha segundo pai, e
    o *gate* 2 ficava vermelho sem autor que o pudesse corrigir. O criterio 5
    manda que em `push` a passagem nao corra, e o unico modo de o garantir e o
    accionamento mandar.
    """
    nome = (evento or "").strip()
    if nome not in ACCIONAMENTOS:
        raise IntervaloInvalido(
            f"accionamento {nome!r} e o que fazer nele nao esta escrito.\n"
            "    O gate fica vermelho de proposito: a escolha entre varrer e nao "
            "varrer\n"
            "    decide-se no ticket e escreve-se em `ACCIONAMENTOS`, nao se "
            "deixa ao caso.\n"
            f"    Accionamentos escritos: "
            f"{', '.join(sorted(k or '(local)' for k in ACCIONAMENTOS))}."
        )

    razao = ACCIONAMENTOS[nome]
    if razao is not None:
        return Intervalo(MODO_SEM_PASSAGEM, razao=razao)

    ref = (merge_ref or "").strip()
    if not ref or set(ref) == {"0"}:
        raise IntervaloInvalido(
            f"accionamento {nome!r} sem merge ref.\n"
            "    Este accionamento decide um merge, pelo que a passagem das "
            "mensagens e obrigatoria.\n"
            "    No CI o valor e `github.sha`, que no evento `pull_request` e o "
            "commit de merge\n"
            "    de teste; se chega vazio, o job esta quebrado.\n"
            "    Um gate que nao sabe o que varrer nao da passagem."
        )
    # `^1` e `^2` e nao `~1`: o que interessa sao os **pais** do merge ref, e o
    # `~` andaria pela primeira linha de ascendencia.
    return Intervalo(MODO_INTERVALO, pai1=f"{ref}^1", pai2=f"{ref}^2")


# ---------------------------------------------------------------------------
# Plumbing do git
# ---------------------------------------------------------------------------


def _git(raiz: Path, *argumentos: str) -> str:
    try:
        resultado = subprocess.run(
            ["git", *argumentos], cwd=raiz, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        erro = getattr(excepcao, "stderr", b"") or b""
        detalhe = erro.decode("utf-8", "replace").strip() or str(excepcao)
        raise IntervaloInvalido(
            f"`git {' '.join(argumentos)}` falhou em {raiz}: {detalhe}"
        ) from excepcao
    return resultado.stdout.decode("utf-8", "replace")


def _recusar_clone_raso(raiz: Path) -> None:
    """Um clone raso nao tem o intervalo, e **nao** se varre pela metade.

    E o modo de falha que o criterio de aceitacao 4 nomeia: o `actions/checkout`
    traz um so *commit* por omissao, e nesse clone o `rev-list` devolveria um
    conjunto truncado e um *gate* verde que nao significa nada.
    """
    if _git(raiz, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise IntervaloInvalido(
            "o clone e raso (*shallow*) e nao tem a historia do intervalo.\n"
            "    Ponha `fetch-depth: 0` no `actions/checkout` do job do gate 2.\n"
            "    Varrer um intervalo truncado daria um verde que nao significa "
            "nada."
        )


def _resolver(raiz: Path, referencia: str, papel: str) -> str:
    try:
        return _git(
            raiz, "rev-parse", "--verify", "--quiet", f"{referencia}^{{commit}}"
        ).strip()
    except IntervaloInvalido as excepcao:
        raise IntervaloInvalido(
            f"{papel} ({referencia!r}) nao existe neste clone.\n"
            "    Com um so pai, o merge ref nao e um merge: num evento "
            "`pull_request` isso\n"
            "    nao acontece, pelo que o valor que chegou em GATE2_MERGE_REF "
            "nao e o merge ref.\n"
            "    Com `fetch-depth` a 1 nem os pais chegam ao clone; ponha "
            "`fetch-depth: 0`.\n"
            "    Um intervalo que nao se resolve e um gate vermelho, nunca uma "
            "passagem em silencio."
        ) from excepcao


# ---------------------------------------------------------------------------
# O varrimento
# ---------------------------------------------------------------------------

#: Separador entre o SHA e a mensagem dentro de cada registo. O `-z` separa os
#: registos por NUL, pelo que o separador de campo tem de ser outro caractere —
#: e um que nao aparece numa mensagem de *commit*. Medido a 2026-11-03: com
#: `--format` e `-z`, o `git log` separa os *commits* por NUL.
_CAMPO = "\x1f"


def mensagens_do_intervalo(raiz: Path, pai1: str, pai2: str) -> list[tuple[str, str]]:
    """`[(sha, mensagem)]` dos *commits* que `pai1..pai2` acrescenta.

    Uma invocacao para o intervalo inteiro, e nao uma por *commit*: e a licao que
    o `historia.py` do *gate* 9 escreveu — um PR de 40 *commits* custava 40
    processos, e num `git` de Windows isso sozinho eram dezenas de segundos.

    A mensagem vai **inteira** (`%B`) e nao so o assunto, para que o que o *gate*
    verifica seja o mesmo que o *hook* verifica: o `check_commit_message` tambem
    le o corpo e o rodape (`body-leading-blank`, `footer-leading-blank`), e dar-
    lhe so o assunto fazia o *gate* aceitar o que o *hook* recusa. E a divergencia
    que `tools/conventions.json` existe para impedir.
    """
    saida = _git(
        raiz,
        "log",
        "-z",
        "--no-color",
        f"--format=%H{_CAMPO}%B",
        f"{pai1}..{pai2}",
    )
    mensagens: list[tuple[str, str]] = []
    for registo in saida.split("\0"):
        if not registo.strip():
            continue
        sha, separador, mensagem = registo.partition(_CAMPO)
        if not separador:
            continue
        mensagens.append((sha.strip(), mensagem))
    return mensagens


@dataclasses.dataclass(frozen=True)
class AchadoNoCommit:
    """Um *commit* do intervalo cuja mensagem esta fora da forma."""

    sha: str
    assunto: str
    problemas: tuple[str, ...]

    def __str__(self) -> str:
        detalhe = "; ".join(self.problemas)
        return f"{self.sha[:12]} {self.assunto!r}: {detalhe}"


@dataclasses.dataclass(frozen=True)
class Resultado:
    """O que a passagem fez — e o que **nao** fez.

    `commits` conta os *commits* lidos e nao os que se pretendia ler: e o
    contador de que a verificacao do intervalo vazio depende, e o `historia.py`
    ja pagou por somar o que pretendia em vez do que fez.
    """

    commits: int
    achados: tuple[AchadoNoCommit, ...]

    @property
    def onde(self) -> str:
        return f"{self.commits} commit(s) do intervalo do PR"


def verificar_intervalo(
    raiz: Path,
    pai1: str,
    pai2: str,
    rules: conventions.Conventions,
) -> Resultado:
    """As mensagens que `pai1..pai2` acrescenta, verificadas uma vez cada.

    O *merge* sintetico do *merge ref* **nao** entra: ele e a cabeca do
    `rev-list`, nao um dos seus elementos. Nao e a isencao `^Merge ` que o deixa
    de fora — e o canario prova-o com as isencoes retiradas.
    """
    _recusar_clone_raso(raiz)
    base = _resolver(raiz, pai1, "o primeiro pai do merge ref")
    cabeca = _resolver(raiz, pai2, "o segundo pai do merge ref")

    achados: list[AchadoNoCommit] = []
    mensagens = mensagens_do_intervalo(raiz, base, cabeca)
    for sha, mensagem in mensagens:
        problemas = conventions.check_commit_message(mensagem, rules)
        if not problemas:
            continue
        # O assunto que se mostra e o que o `check_commit_message` leu: a primeira
        # linha que nao e comentario nem vazia. Mostrar a linha 1 crua punha no
        # registo do *runner* o que um `git commit` tivesse prefixado.
        assunto = next(
            (
                linha.strip()
                for linha in mensagem.replace("\r\n", "\n").split("\n")
                if linha.strip() and not linha.startswith("#")
            ),
            "",
        )
        achados.append(
            AchadoNoCommit(sha=sha, assunto=assunto, problemas=tuple(problemas))
        )

    return Resultado(commits=len(mensagens), achados=tuple(achados))


#: Accionamentos em que um intervalo **sem commits** e configuracao quebrada, e
#: nao um PR sem novidades: um PR sem *commits* proprios nao existe. E a regra do
#: `EXIGEM_COMMITS` do *gate* 9, pela mesma razao — foi assim que a revisao
#: adversarial do KAM-131 pos um gate a nao varrer nada e a dizer-se limpo,
#: trocando duas linhas do YAML sem nenhum teste falhar (A3).
#:
#: Deriva de `ACCIONAMENTOS` e **nao** e uma segunda lista: duas listas de
#: accionamentos divergem, e a divergencia aparece no dia em que alguem
#: acrescenta um accionamento a uma delas.
EXIGEM_COMMITS = frozenset(
    nome for nome, razao in ACCIONAMENTOS.items() if razao is None
)


def exigir_commits(evento: str | None, commits: int) -> None:
    """Num accionamento que decide um *merge*, um intervalo vazio e erro."""
    if commits:
        return
    nome = (evento or "").strip()
    if nome not in EXIGEM_COMMITS:
        return
    raise IntervaloInvalido(
        f"accionamento {nome!r} com um intervalo de **zero** commits.\n"
        "    Um PR sem commits proprios nao existe: zero significa que os dois "
        "pais vieram\n"
        "    trocados, ou iguais — e um intervalo invertido varre nada e "
        "diz-se limpo.\n"
        "    Um gate que nao varreu nada nao se diz limpo."
    )
