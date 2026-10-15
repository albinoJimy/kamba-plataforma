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


def check_commit_message(message: str, rules: Conventions) -> list[str]:
    """Devolve a lista de problemas da mensagem. Lista vazia = conforme."""
    # Comentarios do `git commit` nao fazem parte da mensagem. Tiram-se **antes**
    # de qualquer outra coisa, para que o cabecalho e o corpo sejam contados a
    # partir do mesmo sitio: contar o corpo a partir da linha 1 do ficheiro bruto
    # trataria o proprio cabecalho como corpo quando o `git` prefixa comentarios.
    lines = [
        line
        for line in message.replace("\r\n", "\n").split("\n")
        if not line.startswith("#")
    ]
    # Linhas vazias antes do cabecalho tambem nao contam.
    while lines and not lines[0].strip():
        lines.pop(0)

    header = lines[0].strip() if lines else ""
    if not header:
        return ["mensagem de commit vazia"]
    if any(re.match(pattern, header) for pattern in rules.exempt_header_patterns):
        return []

    problems: list[str] = []
    if len(header) > rules.header_max_length:
        problems.append(
            f"cabecalho com {len(header)} caracteres; o maximo e {rules.header_max_length}"
        )

    match = rules.header_pattern.match(header)
    if not match:
        problems.append(
            "cabecalho fora de 'tipo(KAM-NNN): descricao'; "
            f"tipos aceites: {', '.join(rules.types)}"
        )
        return problems

    scope = match.group("scope")
    if not re.match(rules.scope_pattern, scope):
        problems.append(
            f"ambito {scope!r} fora de {rules.scope_pattern}; "
            "todo o commit cita o ticket que o justifica (specs/01 §5)"
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

    problems += _check_body_and_footer(lines, rules)
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
