"""Convencoes de commit e de ramo, lidas de `tools/conventions.json`.

As regras vivem no JSON e nao aqui: `commitlint.config.cjs` le o mesmo ficheiro.
Duas implementacoes da mesma regra divergem — e a divergencia aparece no dia em
que alguem repara que o hook aceita o que o CI recusa.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path


class ConventionError(ValueError):
    """O ficheiro de convencoes esta malformado."""


@dataclasses.dataclass(frozen=True)
class Conventions:
    types: tuple[str, ...]
    scope_pattern: str
    subject_min_length: int
    subject_max_length: int
    header_max_length: int
    subject_starts_lowercase: bool
    subject_ends_without_period: bool
    body_leading_blank: bool
    footer_leading_blank: bool
    footer_tokens: tuple[str, ...]
    exempt_header_patterns: tuple[str, ...]
    branch_patterns: tuple[str, ...]
    branch_exempt: tuple[str, ...]

    @property
    def header_pattern(self) -> re.Pattern[str]:
        types = "|".join(re.escape(t) for t in self.types)
        return re.compile(rf"^(?P<type>{types})\((?P<scope>[^()]+)\): (?P<subject>.+)$")


def load(path: Path) -> Conventions:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConventionError(f"{path}: {exc}") from exc

    commit = data.get("commit") or {}
    branch = data.get("branch") or {}
    types = tuple(commit.get("types") or ())
    patterns = tuple(branch.get("patterns") or ())
    if not types:
        raise ConventionError(f"{path}: 'commit.types' tem de ser uma lista nao vazia")
    if not commit.get("scopePattern"):
        raise ConventionError(f"{path}: 'commit.scopePattern' em falta")
    if not patterns:
        raise ConventionError(f"{path}: 'branch.patterns' tem de ser uma lista nao vazia")

    return Conventions(
        types=types,
        scope_pattern=str(commit["scopePattern"]),
        subject_min_length=int(commit.get("subjectMinLength", 1)),
        subject_max_length=int(commit.get("subjectMaxLength", 100)),
        header_max_length=int(commit.get("headerMaxLength", 120)),
        subject_starts_lowercase=bool(commit.get("subjectStartsLowercase", True)),
        subject_ends_without_period=bool(commit.get("subjectEndsWithoutPeriod", True)),
        body_leading_blank=bool(commit.get("bodyLeadingBlank", True)),
        footer_leading_blank=bool(commit.get("footerLeadingBlank", True)),
        footer_tokens=tuple(commit.get("footerTokens") or ()),
        exempt_header_patterns=tuple(commit.get("exemptHeaderPatterns") or ()),
        branch_patterns=patterns,
        branch_exempt=tuple(branch.get("exempt") or ()),
    )


def check_commit_message(
    message: str, rules: Conventions, tirar_comentarios: bool = True
) -> list[str]:
    """Devolve a lista de problemas da mensagem. Lista vazia = conforme.

    **`tirar_comentarios` distingue as duas entradas, nao as duas regras.** A
    forma continua a vir toda de `tools/conventions.json`, e nao ha segunda
    implementacao de nada: o que muda e o que conta como **texto da mensagem**.

    * O *hook* `tools/githooks/commit-msg` recebe o `COMMIT_EDITMSG` **antes** do
      *cleanup* do `git`, com o bloco de comentarios que o editor escreve. Esses
      nao fazem parte da mensagem, e tiram-se — e tiram-se antes de tudo, para
      que o cabecalho e o corpo sejam contados do mesmo sitio. E a omissao.
    * Uma mensagem **ja guardada** num *commit* ja passou pelo *cleanup*: o `git`
      removeu os seus proprios comentarios, pelo que uma linha `#` que sobreviva
      ali e **conteudo**. Quem a le da historia passa `tirar_comentarios=False`,
      e e o que o *gate* 2 faz (`commits.py`).

    **A razao e um defeito medido.** Com `-m` ou `-F`, o *cleanup* por omissao e
    `whitespace`, que **nao** tira comentarios: um `git commit -m '#123
    arrumacoes no modulo' -m 'fix(KAM-174): …'` guarda `#123 arrumacoes no
    modulo` como assunto — e o `git` usa-o como `%s`. Com a remocao activa, esta
    funcao saltava essa linha, julgava a **seguinte**, e dava a mensagem por
    conforme; num PR de um so *commit*, com `squash_merge_commit_title:
    COMMIT_OR_PR_TITLE`, esse assunto ia para o `main` fora da forma. Medido a
    2026-11-03, achado A1 da revisao adversarial do KAM-174. O *hook* aceita-o
    pela mesma via — e nao e por isso que se salva o caso: o *hook* dispensa-se
    com `--no-verify`, e o ponto de imposicao e o *gate*.
    """
    linhas_cruas = message.replace("\r\n", "\n").split("\n")
    lines = (
        [line for line in linhas_cruas if not line.startswith("#")]
        if tirar_comentarios
        else list(linhas_cruas)
    )
    # Linhas vazias antes do cabecalho tambem nao contam.
    while lines and not lines[0].strip():
        lines.pop(0)

    header = lines[0].strip() if lines else ""
    if not header:
        return ["mensagem de commit vazia"]
    if any(re.match(pattern, header) for pattern in rules.exempt_header_patterns):
        return []

    problems = _check_header(header, rules)
    # **O corpo so se verifica se o cabecalho tiver forma.** Antes da extraccao
    # do `_check_header` isto era um `return` a seguir ao achado da forma, e
    # perdeu-se na extraccao: a saida do *hook* passou a trazer um
    # `body-leading-blank` por cima do «cabecalho fora de …», o que e ruido numa
    # mensagem que ainda nao tem cabecalho. Achado da revisao adversarial do
    # KAM-164, e preso por `test_cabecalho_sem_forma_nao_traz_achado_de_corpo`.
    if rules.header_pattern.match(header):
        problems += _check_body_and_footer(lines, rules)
    return problems


def _check_header(header: str, rules: Conventions, rotulo: str = "cabecalho") -> list[str]:
    """As regras da linha `tipo(KAM-NNN): descricao`, e so dela.

    Esta funcao existe porque a mesma linha e verificada em **duas** superficies:
    o cabecalho de uma mensagem de commit e o titulo de um PR
    (`check_pr_title`). Duas copias das regras divergiriam, e a divergencia e o
    defeito que `tools/conventions.json` existe para impedir — vale para a forma
    e vale igualmente para o que se faz com ela.

    `rotulo` so muda o substantivo das mensagens, para que quem le um achado
    sobre o titulo de um PR nao leia a palavra «cabecalho».
    """
    problems: list[str] = []
    if len(header) > rules.header_max_length:
        problems.append(
            f"{rotulo} com {len(header)} caracteres; o maximo e {rules.header_max_length}"
        )

    match = rules.header_pattern.match(header)
    if not match:
        problems.append(
            f"{rotulo} fora de 'tipo(KAM-NNN): descricao'; "
            f"tipos aceites: {', '.join(rules.types)}"
        )
        return problems

    scope = match.group("scope")
    if not re.match(rules.scope_pattern, scope):
        # O substantivo acompanha o `rotulo`: um achado sobre o titulo de um PR
        # que mandasse olhar para «todo o commit» remetia quem o le para a
        # superficie errada. Achado da revisao adversarial do KAM-164.
        sujeito = "todo o PR" if rotulo == "titulo" else "todo o commit"
        problems.append(
            f"ambito {scope!r} fora de {rules.scope_pattern}; "
            f"{sujeito} cita o ticket que o justifica (specs/01 §5)"
        )

    subject = match.group("subject").strip()
    if len(subject) < rules.subject_min_length:
        problems.append(
            f"descricao com {len(subject)} caracteres; o minimo e {rules.subject_min_length}"
        )
    if len(subject) > rules.subject_max_length:
        problems.append(
            f"descricao com {len(subject)} caracteres; o maximo e {rules.subject_max_length}"
        )
    if rules.subject_ends_without_period and subject.endswith("."):
        problems.append("descricao nao termina em ponto")
    if rules.subject_starts_lowercase and subject[:1].isupper():
        problems.append("descricao comeca em minuscula, no imperativo")
    # Siglas no meio da descricao sao permitidas de proposito (RLS, HMAC, BSUID,
    # Postgres, APD, AGT, BNA): e o vocabulario normal do projecto. So se recusa
    # a descricao **inteira** em maiusculas, que e o default do commitlint.
    letras = [c for c in subject if c.isalpha()]
    if letras and all(c.isupper() for c in letras):
        problems.append("descricao inteira em maiusculas")

    return problems


def _check_body_and_footer(lines: list[str], rules: Conventions) -> list[str]:
    """Linha em branco entre cabecalho e corpo, e antes do rodape.

    O commitlint impoe isto (`body-leading-blank`, `footer-leading-blank`) e sem
    estas verificacoes o hook aceitava mensagens que o CI recusa — a divergencia
    que `tools/conventions.json` existe para impedir.
    """
    problems: list[str] = []
    # `lines` ja vem sem comentarios e sem linhas vazias iniciais (ver
    # `check_commit_message`), pelo que o corpo comeca logo depois do cabecalho.
    corpo = lines[1:]

    if rules.body_leading_blank and corpo and corpo[0].strip():
        problems.append(
            "falta uma linha em branco entre o cabecalho e o corpo "
            "(body-leading-blank)"
        )

    if rules.footer_leading_blank and rules.footer_tokens:
        # Lista fechada de tokens. A deteccao por `<palavra>: ` apanhava prosa:
        # `importador: a raiz leva 91…` no meio do corpo era lido como rodape e
        # exigia linha em branco antes dele.
        alternativas = "|".join(re.escape(t) for t in rules.footer_tokens)
        rodape = re.compile(rf"^(?:{alternativas})(?::\s|\s#)", re.IGNORECASE)
        for index, line in enumerate(corpo):
            if index == 0 or not rodape.match(line.strip()):
                continue
            if corpo[index - 1].strip():
                problems.append(
                    f"falta uma linha em branco antes do rodape {line.strip()[:30]!r} "
                    "(footer-leading-blank)"
                )
                break
    return problems


#: O que o GitHub acrescenta ao assunto do *squash*: ` (#NNNN)`. Os seis assuntos
#: que estao no `main` trazem-no todos — de ` (#70)` a ` (#75)`. Reserva-se o
#: comprimento de **quatro** digitos (`#9999`) e nao o do numero do PR em curso,
#: que o evento traz mas que esta funcao nao recebe: uma reserva fixa e mais
#: estrita do que a conta exacta, e errar para o lado estrito e o que se quer num
#: limite. Hoje o repositorio esta no #107.
SUFIXO_DO_SQUASH = len(" (#9999)")


def normalizar_titulo(title: str) -> str:
    """O titulo como a verificacao o le: espaco em branco colapsado.

    Existe como funcao propria porque **duas** superficies precisam do mesmo
    valor: a verificacao e o bloco de ajuda que ecoa o titulo recusado. Ecoar o
    valor cru punha no registo do *runner*, no inicio de linha, o que quem
    escreveu o titulo quisesse — e no GitHub Actions uma linha que comece por
    `::error`, `::add-mask` ou `::stop-commands` e um *workflow command*, nao
    texto. Colapsar o espaco em branco tira as novas linhas, e com elas o inicio
    de linha. Achado da revisao adversarial do KAM-164.
    """
    return " ".join(title.split())


def check_pr_title(title: str, rules: Conventions) -> list[str]:
    """Devolve a lista de problemas do titulo de um PR. Lista vazia = conforme.

    **Porque e que o titulo de um PR tem a forma de um assunto de commit.** A
    definicao do repositorio e `squash_merge_commit_title: COMMIT_OR_PR_TITLE`
    (medido a 2026-11-03 em `gh api repos/albinoJimy/kamba-plataforma`), que
    significa: o assunto do commit quando o PR tem **um so**, e o **titulo do
    PR** quando tem mais do que um. Logo o titulo de um PR desta linha e, metade
    das vezes, o assunto que fica no `main` — e o `tools/githooks/commit-msg` nao
    lhe chega, porque ele nao vive no ramo. O `29778f3` (PR #75) e a prova de que
    isso aconteceu. (E nenhum portao de CI le mensagens de *commit*: medido a
    2026-11-03, o `make ci-2` corre `lint_arch all`, que nao as inclui, e nenhum
    *workflow* invoca o `commitlint`. Divida 173.)

    Tres diferencas face a `check_commit_message`, todas deliberadas:

    - **Verifica-se sempre**, tambem num PR com um so commit, onde o assunto nao
      vem do titulo. E a decisao aberta do KAM-164, e fecha-se assim por quatro
      razoes: o numero de commits nao vem no evento (exigiria uma chamada a API
      cuja resposta pode mudar entre a verificacao e a fusao); `allow_auto_merge`
      esta ligado desde 2026-10-27, pelo que um commit acrescentado depois de os
      portoes ficarem verdes transforma o titulo em assunto sem nada reavaliar;
      **nada do lado do servidor verifica o assunto de um commit** (ver acima),
      pelo que a alternativa nao e «ja esta coberto» mas «nao esta coberto por
      ninguem»; e a regra fica mais simples de escrever no `specs/01` §5 — «o
      titulo do PR obedece a mesma forma», sem condicao. O custo e um falso
      vermelho a quem titule de outra forma um PR de um commit, e esse custo e a
      regra, nao um defeito dela.
    - **Sem dispensas.** `exemptHeaderPatterns` dispensa o que o *git* gera
      sozinho (`Merge `, `Revert "`, `fixup! `, `squash! `). Nada no GitHub gera
      um titulo de PR dessas formas — quem o escreve e uma pessoa —, e um
      `Merge ...` dispensado acabaria no `main` como assunto, que e exactamente
      o que esta funcao existe para impedir.
    - **Uma linha.** Um titulo nao tem corpo nem rodape, pelo que as regras
      `body-leading-blank` e `footer-leading-blank` nao se lhe aplicam. O espaco
      em branco normaliza-se antes de verificar, para que um titulo colado com um
      espaco duplo ou com uma nova linha a mais falhe — se falhar — pela forma, e
      nao por um caractere invisivel que ninguem ve no diff.
    - **Uma regra a mais, que o cabecalho de um commit nao tem.** O que fica no
      `main` e o titulo **mais** o ` (#NNNN)` que o GitHub acrescenta, pelo que o
      limite de comprimento se verifica contra o assunto projectado e nao contra
      o titulo (`SUFIXO_DO_SQUASH`).
    """
    title = normalizar_titulo(title)
    if not title:
        return ["titulo de PR vazio"]
    problems = _check_header(title, rules, rotulo="titulo")
    # **O que a verificacao mede e o titulo; o que fica no `main` e o titulo mais
    # o ` (#NNNN)`.** Sem esta conta havia uma gama de titulos — 113 a 120
    # caracteres — que esta verificacao aprovava e que deixavam no `main`
    # exactamente a classe de assunto que o `check_commit_message` recusa: medido
    # com um titulo de 119, o assunto do *squash* fica em 126 e o maximo e 120.
    # Achado da revisao adversarial do KAM-164.
    projectado = len(title) + SUFIXO_DO_SQUASH
    if projectado > rules.header_max_length:
        problems.append(
            f"o assunto do squash ficaria com {projectado} caracteres "
            f"({len(title)} do titulo mais os {SUFIXO_DO_SQUASH} do ' (#NNNN)' "
            f"que o GitHub acrescenta); o maximo e {rules.header_max_length}"
        )
    return problems


def check_branch_name(name: str, rules: Conventions) -> list[str]:
    """Devolve a lista de problemas do nome do ramo. Lista vazia = conforme."""
    name = name.strip()
    if not name:
        return ["nome de ramo vazio"]
    if name in rules.branch_exempt:
        return []
    if any(re.match(pattern, name) for pattern in rules.branch_patterns):
        return []
    return [
        f"ramo {name!r} fora de feature/KAM-NNN-<slug> ou fix/KAM-NNN-<slug> (specs/01 §5)"
    ]
