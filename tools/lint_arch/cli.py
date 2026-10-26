"""Interface de linha de comando do `lint_arch`.

    python -m lint_arch deps [--root .]          lista de bloqueio
    python -m lint_arch structure [--root .]     arvore obrigatoria
    python -m lint_arch commit-msg <ficheiro>    mensagem de commit
    python -m lint_arch branch [<nome>]          nome de ramo
    python -m lint_arch tool-schema [--root .]   esquemas de tool (KAM-028)
    python -m lint_arch all [--root .]           deps + structure + tool-schema

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao
importa: um ficheiro de bloqueio malformado nao pode parecer um repositorio limpo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import blocklist as blocklist_module
from . import conventions as conventions_module
from . import manifests, names, structure, tool_schema, versions


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _blocklist_path(root: Path) -> Path:
    return root / "tools" / "blocklist.yaml"


def _conventions_path(root: Path) -> Path:
    return root / "tools" / "conventions.json"


def _candidate_names(declaration: manifests.Declaration) -> list[str]:
    """Nomes pelos quais uma declaracao pode ser reconhecida.

    Para imagens geram-se todos os sufixos do caminho, para que
    `ghcr.io/berriai/litellm:main-v1.82.7` bata numa entrada `litellm`. Sem isto,
    **escrever o registo fazia o bloqueio desaparecer** — e a referencia oficial
    do LiteLLM, o pacote que originou o ADR-005, e precisamente
    `ghcr.io/berriai/litellm`.
    """
    if declaration.ecosystem == manifests.IMAGE:
        return names.image_candidates(declaration.name)
    return [declaration.name.lower()]


def _effective_spec(declaration: manifests.Declaration) -> str:
    """Versao a avaliar contra um limiar `forbidden_below`.

    Para imagens, extrai-se a versao da tag: `main-v1.104.2` da `1.104.2`, que e
    a forma em que o LiteLLM publica. Um digest sozinho **nao** prova versao
    nenhuma — resolve-lo exigiria rede — pelo que uma imagem com limiar tem de
    trazer a versao na tag, mesmo quando esta fixada por digest
    (`litellm:v1.104.2@sha256:...` e a forma legal que cumpre as duas coisas).
    """
    if declaration.ecosystem == manifests.IMAGE:
        _, tag = names.image_parts(declaration.name)
        return names.version_in_tag(tag) or ""
    return declaration.spec


def check_dependencies(root: Path, blocklist_path: Path | None = None) -> list[str]:
    """Aplica a lista de bloqueio a todos os manifestos sob `root`.

    `blocklist_path` existe para que as fixtures possam ser varridas como raizes
    independentes, sem terem de carregar uma copia da lista.
    """
    entries = blocklist_module.load_entries(blocklist_path or _blocklist_path(root))
    declarations = manifests.collect(root)
    findings: list[str] = []

    for declaration in declarations:
        # Uma declaracao que o leitor nao conseguiu classificar e um achado por
        # si: fail-closed, porque pode ser qualquer coisa.
        if declaration.name == "?":
            findings.append(
                f"{declaration.where()}: nao foi possivel identificar o pacote ou a "
                f"imagem em {declaration.spec!r}.\n"
                "    A lista de bloqueio nao se aplica ao que nao se consegue ler: "
                "escreva a dependencia numa forma reconhecivel (nome e versao)."
            )
            continue

        candidates = _candidate_names(declaration)
        for entry in entries:
            if not entry.applies_to_kind(declaration.ecosystem):
                continue
            if not any(
                entry.matches_name(candidate, declaration.ecosystem)
                for candidate in candidates
            ):
                continue

            if entry.forbidden_below:
                allowed, why = versions.satisfies_floor(
                    _effective_spec(declaration), entry.forbidden_below
                )
                if allowed:
                    continue
                como_corrigir = (
                    "    Para imagens: traga a versao na tag, mesmo quando fixa o "
                    f"digest (ex.: ...:v{entry.forbidden_below}@sha256:...).\n"
                    if declaration.ecosystem == manifests.IMAGE
                    else ""
                )
                findings.append(
                    f"{declaration.where()}: {declaration.name!r} e proibido abaixo de "
                    f"{entry.forbidden_below} — {why}.\n"
                    f"{como_corrigir}"
                    f"    Fundamento: {entry.adr} — {entry.reason}\n"
                    f"    Evidencia: {entry.evidence}"
                )
            else:
                findings.append(
                    f"{declaration.where()}: {declaration.name!r} esta na lista de bloqueio.\n"
                    f"    Fundamento: {entry.adr} — {entry.reason}\n"
                    f"    Evidencia: {entry.evidence}"
                )
    return findings


def _current_branch(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _check_aliases(root: Path) -> list[str]:
    """O passo `aliases` (KAM-030, criterio 7).

    Delega no `tools/llm_config`, que e quem gera a configuracao do proxy: o
    *lint* e o gerador tem de concordar por construcao, e nao por duas leituras
    do mesmo ficheiro. Importa-se **aqui dentro** e nao no topo porque o
    `lint_arch` corre como primeiro passo do `make bootstrap`, antes de qualquer
    instalacao, e um `ImportError` no topo deixava os outros tres passos sem
    correr.

    Um `llm/aliases.yaml` que nao exista nao e achado deste passo: um
    repositorio sem aliases ainda nao chegou ao KAM-030, e um *lint* que
    falhasse por um ficheiro que o ticket ainda nao criou e um *lint* que alguem
    desliga.
    """
    if not (root / "llm" / "aliases.yaml").is_file():
        return []
    import sys as _sys

    ferramentas = str(root / "tools")
    if ferramentas not in _sys.path:
        _sys.path.insert(0, ferramentas)
    from llm_config import AliasesInvalidos
    from llm_config.cli import check as check_llm

    try:
        return check_llm(root)
    except AliasesInvalidos as excepcao:
        return [f"llm/aliases.yaml invalido: {excepcao}"]


def _report(title: str, findings: list[str]) -> int:
    if not findings:
        print(f"lint_arch: {title}: conforme")
        return 0
    print(f"lint_arch: {title}: {len(findings)} achado(s)", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lint_arch", description="Linter de arquitectura do monorepo KAMBÁ"
    )
    parser.add_argument("--root", type=Path, default=None, help="raiz do repositorio")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("deps", help="aplica tools/blocklist.yaml aos manifestos")
    sub.add_parser("structure", help="verifica a arvore obrigatoria")
    sub.add_parser(
        "tool-schema",
        help="esquemas de tool sem parametro proibido e escrita so na TLS (KAM-028)",
    )
    sub.add_parser(
        "aliases",
        help="llm/aliases.yaml com SemVer, lock em dia e config gerada (KAM-030)",
    )
    sub.add_parser("all", help="deps, structure, tool-schema e aliases")
    commit = sub.add_parser("commit-msg", help="valida uma mensagem de commit")
    commit.add_argument("path", type=Path, help="ficheiro com a mensagem (COMMIT_EDITMSG)")
    branch = sub.add_parser("branch", help="valida um nome de ramo")
    branch.add_argument("name", nargs="?", help="nome do ramo (omitido: o ramo actual)")

    args = parser.parse_args(argv)
    root = (args.root or _default_root()).resolve()

    try:
        if args.command == "deps":
            return _report("lista de bloqueio", check_dependencies(root))
        if args.command == "structure":
            return _report("estrutura", structure.check(root))
        if args.command == "tool-schema":
            return _report("esquemas de tool", tool_schema.check(root))
        if args.command == "aliases":
            return _report("aliases de LLM", _check_aliases(root))
        if args.command == "all":
            # Os quatro correm **sempre**, e o codigo de saida e o maximo: parar
            # no primeiro achado escondia os outros, e quem corre `all` quer a
            # lista toda de uma vez.
            status = _report("lista de bloqueio", check_dependencies(root))
            status = max(status, _report("estrutura", structure.check(root)))
            status = max(status, _report("esquemas de tool", tool_schema.check(root)))
            return max(status, _report("aliases de LLM", _check_aliases(root)))

        rules = conventions_module.load(_conventions_path(root))
        if args.command == "commit-msg":
            message = args.path.read_text(encoding="utf-8")
            return _report("mensagem de commit", conventions_module.check_commit_message(message, rules))
        if args.command == "branch":
            name = args.name or _current_branch(root)
            if name is None:
                print(
                    "lint_arch: nao foi possivel determinar o ramo actual; "
                    "passe o nome explicitamente",
                    file=sys.stderr,
                )
                return 2
            return _report("nome de ramo", conventions_module.check_branch_name(name, rules))
    except (ValueError, OSError) as exc:
        print(f"lint_arch: erro de configuracao: {exc}", file=sys.stderr)
        return 2

    parser.error(f"comando desconhecido: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
