"""Interface de linha de comando do `lint_arch`.

    python -m lint_arch deps [--root .]          lista de bloqueio
    python -m lint_arch structure [--root .]     arvore obrigatoria
    python -m lint_arch commit-msg <ficheiro>    mensagem de commit
    python -m lint_arch pr-title [<titulo>]      titulo de PR (KAM-164)
    python -m lint_arch pr-title-canario         prova que o pr-title morde
    python -m lint_arch commit-range             mensagens dos commits do PR (KAM-174)
    python -m lint_arch commit-range-canario     prova que o commit-range morde
    python -m lint_arch branch [<nome>]          nome de ramo
    python -m lint_arch base [<ramo>]            base do ramo, pela origem (KAM-180)
    python -m lint_arch tool-schema [--root .]   esquemas de tool (KAM-028)
    python -m lint_arch medusa [--root .]        Registo de comercio (KAM-042)
    python -m lint_arch all [--root .]           deps + structure + tool-schema + medusa

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao
importa: um ficheiro de bloqueio malformado nao pode parecer um repositorio limpo.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import base as base_module
from . import blocklist as blocklist_module
from . import canario_commits, canario_titulo
from . import commits as commits_module
from . import conventions as conventions_module
from . import manifests, medusa, names, structure, tool_schema, versions


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


#: Variavel de ambiente de onde o `pr-title` le o titulo quando nenhum e passado
#: na linha de comando. **Existe por seguranca, nao por conveniencia**: um titulo
#: de PR e texto que qualquer pessoa escreve, e interpola-lo num `run:` do
#: GitHub Actions (`${{ github.event.pull_request.title }}`) e injeccao de
#: *shell* na maquina do CI. Pelo ambiente, o titulo nunca passa pelo *shell*.
AMBIENTE_TITULO_PR = "KAMBA_PR_TITLE"

#: Variaveis de onde o `commit-range` le o accionamento e o *merge ref* quando
#: nenhum e passado na linha de comando (KAM-174). Os dois valores vao **em
#: bruto**, como o evento os traz, e quem decide o que fazer com eles e
#: `commits.decidir_intervalo`, que e uma funcao pura com testes. E a forma do
#: *gate* 9 (`GATE9_EVENTO`, `GATE9_BASE`, `GATE9_HEAD`), e existe pela mesma
#: razao: nao ha *lint* de *workflows* neste repositorio, pelo que uma condicao
#: escrita em YAML nao seria verificavel por teste nenhum.
AMBIENTE_EVENTO = "GATE2_EVENTO"
AMBIENTE_MERGE_REF = "GATE2_MERGE_REF"


def _ajuda_do_titulo(title: str, rules: conventions_module.Conventions) -> str:
    """O bloco de ajuda de um titulo recusado, no padrao do `tools/githooks/commit-msg`.

    Diz as quatro coisas que o criterio 6 do KAM-164 exige: a forma esperada, o
    titulo que foi recusado, um exemplo, e o sitio onde a regra esta escrita. Os
    tipos saem de `rules` e nao de uma lista escrita aqui, para que acrescentar um
    tipo ao `tools/conventions.json` nao deixe esta ajuda a mentir.

    **O titulo ecoa-se normalizado, e nao cru.** Um titulo de PR e texto que
    qualquer pessoa escreve; ecoado cru, uma nova linha seguida de `::error`,
    `::add-mask` ou `::stop-commands` chegava ao registo do *runner* no inicio de
    linha, onde o GitHub Actions a le como *workflow command* e nao como texto
    (medido: as anotacoes fabricadas apareciam). Nao ha escalada — `::set-env` e
    `::add-path` estao desligados desde 2020 e este *job* nao escreve em
    `GITHUB_OUTPUT` nem em `GITHUB_ENV` —, mas o registo e as anotacoes mentiam.
    Normalizar o espaco em branco tira o inicio de linha, e de passagem faz a
    ajuda ecoar **o que foi verificado**. Achado da revisao adversarial do
    KAM-164.
    """
    title = conventions_module.normalizar_titulo(title)
    return (
        "\n"
        f"  Titulo recusado:   {title}\n"
        "\n"
        "  Formato esperado:  tipo(KAM-NNN): descricao no imperativo\n"
        "  Exemplo:           feat(KAM-164): verifica o titulo do PR contra a convencao\n"
        f"  Tipos:             {', '.join(rules.types)}\n"
        "\n"
        "  Porque e que o titulo conta: o GitHub usa-o como assunto do squash quando o\n"
        "  PR traz mais do que um commit (squash_merge_commit_title:\n"
        "  COMMIT_OR_PR_TITLE), pelo que e ele — e nao a mensagem do commit — que fica\n"
        "  no main. Edita o titulo do PR no GitHub; nao e preciso tocar no ramo, e esta\n"
        "  verificacao corre outra vez no evento `edited`.\n"
        "\n"
        "  As regras estao em tools/conventions.json (specs/01 §5 e §7).\n"
    )


def _ajuda_da_mensagem(rules: conventions_module.Conventions) -> str:
    """O bloco de ajuda de um intervalo recusado (KAM-174).

    No padrao do `_ajuda_do_titulo` e do `tools/githooks/commit-msg`, com uma
    diferenca: **nao ecoa a mensagem**. Os assuntos recusados ja vao, um por
    linha, no relatorio do `_report`, e cada um deles passou pelo `!r` de
    `AchadoNoCommit.__str__` — que escapa a nova linha e com ela o inicio de
    linha de que um *workflow command* precisa. Ecoa-los aqui outra vez era
    repetir a lista e abrir a mesma porta duas vezes.

    O que esta ajuda diz, e que a do titulo nao pode dizer: **como se corrige**.
    Um assunto de *commit* vive no ramo, pelo que a correccao e reescrever o
    proprio ramo — que o autor pode fazer, ao contrario de um *commit* de `main`.
    """
    return (
        "\n"
        "  Formato esperado:  tipo(KAM-NNN): descricao no imperativo\n"
        "  Exemplo:           fix(KAM-174): le as mensagens dos commits do intervalo\n"
        f"  Tipos:             {', '.join(rules.types)}\n"
        "\n"
        "  Isentos (tools/conventions.json, exemptHeaderPatterns): "
        f"{', '.join(rules.exempt_header_patterns)}\n"
        "  — o `Merge branch ...` que o git escreve ao trazer a main para dentro do\n"
        "  ramo e isento, e nao precisa de ser baptizado a mao.\n"
        "\n"
        "  O que se varre: so os commits que este PR acrescenta (do primeiro ao segundo\n"
        "  pai do merge ref). Nenhum commit de main entra no intervalo, pelo que o que\n"
        "  esta vermelho e teu e corrige-se no teu ramo:\n"
        "\n"
        "      git rebase -i <primeiro pai>   # ou `git commit --amend` no ultimo\n"
        "\n"
        "  Porque e que o assunto do commit conta: com squash_merge_commit_title:\n"
        "  COMMIT_OR_PR_TITLE, num PR de um so commit o GitHub leva o assunto desse\n"
        "  commit para o main — e nenhum outro portao o le.\n"
        "\n"
        "  As regras estao em tools/conventions.json (specs/01 §5).\n"
    )


def _relatorio_da_base(veredicto: base_module.Veredicto) -> int:
    """Imprime o veredicto da base do ramo (KAM-180).

    Printer proprio e nao o `_report`: este tem **tres** estados e nao dois, e a
    diferenca e o ponto do ticket. Um `DESCONHECIDO` empurrado para a forma de
    «achado» ou de «conforme» era exactamente a confusao que o instrumento existe
    para fechar — «nao sei» tem de se ler como «nao sei».

    O estado vai para o `stdout` quando e `conforme` e para o `stderr` quando nao
    e, como no `_report`: quem corre isto num *pipe* quer o silencio no caso bom.
    """
    etiqueta = {
        base_module.CONFORME: "conforme",
        base_module.RECUSADO: "RECUSADO",
        base_module.DESCONHECIDO: "NAO SE SABE",
    }[veredicto.estado]

    if veredicto.estado == base_module.CONFORME:
        print(f"lint_arch: base do ramo: {etiqueta}")
        print(f"  ramo:       {veredicto.ramo}")
        print(f"  origem:     {veredicto.origem}")
        print(f"  porque:     {veredicto.razao}")
        return veredicto.codigo

    print(f"lint_arch: base do ramo: {etiqueta}", file=sys.stderr)
    print(f"  ramo:       {veredicto.ramo}", file=sys.stderr)
    if veredicto.origem is not None:
        print(f"  origem:     {veredicto.origem}", file=sys.stderr)
    print(f"  porque:     {veredicto.razao}", file=sys.stderr)
    print(base_module.texto_da_reparacao(veredicto), file=sys.stderr)
    return veredicto.codigo


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
    sub.add_parser(
        "medusa",
        help="SDK e base do Registo so no COM, e nenhuma flag Enterprise (KAM-042)",
    )
    sub.add_parser("all", help="deps, structure, tool-schema, aliases e medusa")
    commit = sub.add_parser("commit-msg", help="valida uma mensagem de commit")
    commit.add_argument("path", type=Path, help="ficheiro com a mensagem (COMMIT_EDITMSG)")
    pr_title = sub.add_parser(
        "pr-title",
        help="valida o titulo de um PR, que e o assunto do squash (KAM-164)",
    )
    pr_title.add_argument(
        "title",
        nargs="?",
        help=f"o titulo (omitido: le-se de ${AMBIENTE_TITULO_PR})",
    )
    sub.add_parser(
        "pr-title-canario",
        help="prova que o pr-title recusa o que tem de recusar (KAM-164)",
    )
    commit_range = sub.add_parser(
        "commit-range",
        help="valida as mensagens dos commits que o PR acrescenta (KAM-174)",
    )
    commit_range.add_argument(
        "--evento",
        default=None,
        help=f"o accionamento, em bruto (omitido: le-se de ${AMBIENTE_EVENTO})",
    )
    commit_range.add_argument(
        "--merge-ref",
        default=None,
        help=f"o merge ref do evento, em bruto (omitido: ${AMBIENTE_MERGE_REF})",
    )
    commit_range.add_argument(
        "--exigir-intervalo",
        action="store_true",
        help=(
            "esta invocacao e a do portao: dentro do CI, um accionamento vazio "
            "passa a ser erro em vez de modo local (passa-a so o alvo `ci-2`)"
        ),
    )
    sub.add_parser(
        "commit-range-canario",
        help="prova que o commit-range recusa o que tem de recusar (KAM-174)",
    )
    branch = sub.add_parser("branch", help="valida um nome de ramo")
    branch.add_argument("name", nargs="?", help="nome do ramo (omitido: o ramo actual)")
    # **Subcomando daqui e nao ferramenta nova em `tools/`**, e a escolha tem
    # razao: o `branch` ao lado responde a outra metade da mesma pergunta — «este
    # ramo esta em condicoes de se trabalhar nele?» —, e o `tools/conventions.json`
    # ja e a fonte unica da forma do nome que a reparacao sugere. Uma ferramenta
    # propria acrescentava superficie para a mesma pergunta e punha a mensagem de
    # reparacao a repetir, numa segunda copia, a forma que este pacote ja sabe.
    # O nome `base` e o substantivo que o ticket usa de ponta a ponta.
    base = sub.add_parser(
        "base",
        help="a base do ramo actual, lida pela origem e nao pelo estado (KAM-180)",
    )
    base.add_argument("name", nargs="?", help="nome do ramo (omitido: o ramo actual)")
    base.add_argument(
        "--referencia",
        default=base_module.REFERENCIA_PADRAO,
        help=f"a referencia que conta (omitida: {base_module.REFERENCIA_PADRAO})",
    )

    args = parser.parse_args(argv)
    root = (args.root or _default_root()).resolve()

    try:
        if args.command == "deps":
            return _report("lista de bloqueio", check_dependencies(root))
        if args.command == "structure":
            return _report("estrutura", structure.check(root))
        if args.command == "tool-schema":
            return _report("esquemas de tool", tool_schema.check(root))
        if args.command == "medusa":
            return _report("Registo de comercio", medusa.check(root))
        if args.command == "aliases":
            return _report("aliases de LLM", _check_aliases(root))
        if args.command == "base":
            # Nao carrega o `conventions.json`: a pergunta e sobre a historia do
            # ramo e nao sobre a forma do nome. Assim tambem responde num
            # repositorio a que falte o ficheiro das convencoes, que e um dos
            # estados em que um worktree cortado da linha errada pode estar.
            return _relatorio_da_base(
                base_module.avaliar(root, args.name, args.referencia)
            )
        if args.command == "all":
            # Os cinco correm **sempre**, e o codigo de saida e o maximo: parar
            # no primeiro achado escondia os outros, e quem corre `all` quer a
            # lista toda de uma vez.
            status = _report("lista de bloqueio", check_dependencies(root))
            status = max(status, _report("estrutura", structure.check(root)))
            status = max(status, _report("esquemas de tool", tool_schema.check(root)))
            status = max(status, _report("aliases de LLM", _check_aliases(root)))
            return max(status, _report("Registo de comercio", medusa.check(root)))

        rules = conventions_module.load(_conventions_path(root))
        if args.command == "commit-msg":
            message = args.path.read_text(encoding="utf-8")
            return _report("mensagem de commit", conventions_module.check_commit_message(message, rules))
        if args.command == "pr-title":
            # Fail-closed: sem titulo nenhum, isto e erro de configuracao (2) e
            # nao «conforme» (0). Um passo de CI a que a variavel de ambiente
            # falhasse ficaria verde sem ter verificado nada — que e o modo de
            # falha que esta verificacao existe para fechar, nao para repetir.
            title = args.title if args.title is not None else os.environ.get(AMBIENTE_TITULO_PR)
            if title is None:
                print(
                    f"lint_arch: titulo do PR em falta: passe-o como argumento ou em "
                    f"${AMBIENTE_TITULO_PR}",
                    file=sys.stderr,
                )
                return 2
            status = _report("titulo do PR", conventions_module.check_pr_title(title, rules))
            if status != 0:
                print(_ajuda_do_titulo(title, rules), file=sys.stderr)
            return status
        if args.command == "pr-title-canario":
            falhas, numeros = canario_titulo.canario(rules)
            for falha in falhas:
                print(f"canario: {falha}", file=sys.stderr)
            print(
                f"lint_arch pr-title canario: {numeros['negativos']} negativos e "
                f"{numeros['positivos']} positivos; {len(falhas)} falha(s)"
            )
            return 1 if falhas else 0
        if args.command == "commit-range":
            # Os dois valores vao em bruto. Quem decide e `decidir_intervalo`,
            # que levanta `IntervaloInvalido` — um ValueError, pelo que o
            # `except` abaixo o traduz em codigo 2. Fail-closed: um accionamento
            # que decide um merge e nao traz merge ref e configuracao quebrada,
            # nao um PR conforme.
            evento = (
                args.evento
                if args.evento is not None
                else os.environ.get(AMBIENTE_EVENTO, "")
            )
            merge_ref = (
                args.merge_ref
                if args.merge_ref is not None
                else os.environ.get(AMBIENTE_MERGE_REF, "")
            )
            # **A conjuncao das duas, e nenhuma delas sozinha.** A bandeira diz
            # «esta invocacao e a do portao» — o `ci-2` passa-a, o `bootstrap`
            # nao —, e o `CI` diz «ha um accionamento a chegar». Sem a bandeira,
            # a guarda punha vermelha a invocacao que o `make bootstrap` faz
            # dentro de **todos** os jobs que usam a accao `preparar`; sem o
            # `CI`, punha vermelho o `make ci-2` de quem desenvolve, que nao tem
            # PR. Juntas, restam os casos em que as variaveis deviam ter chegado
            # e nao chegaram.
            exigir = args.exigir_intervalo and bool(os.environ.get("CI", "").strip())
            intervalo = commits_module.decidir_intervalo(evento, merge_ref, exigir)
            if intervalo.modo == commits_module.MODO_SEM_PASSAGEM:
                # Declara-se o modo em vez de passar em silencio: uma execucao
                # local que nao varre nada nao pode ler-se como «os commits estao
                # conformes».
                print(
                    f"lint_arch: mensagens dos commits: NAO verificadas "
                    f"({intervalo.razao})"
                )
                return 0
            resultado = commits_module.verificar_intervalo(
                root, intervalo.pai1, intervalo.pai2, rules
            )
            commits_module.exigir_commits(evento, resultado.commits)
            status = _report(
                "mensagens dos commits",
                [str(achado) for achado in resultado.achados],
            )
            print(f"lint_arch: mensagens dos commits: {resultado.onde}")
            if status != 0:
                print(_ajuda_da_mensagem(rules), file=sys.stderr)
            return status
        if args.command == "commit-range-canario":
            falhas, numeros = canario_commits.canario(rules)
            for falha in falhas:
                print(f"canario: {falha}", file=sys.stderr)
            print(
                f"lint_arch commit-range canario: {numeros['negativos']} negativos, "
                f"{numeros['positivos']} positivos e {numeros['commits']} commit(s) "
                f"no intervalo descartavel; {len(falhas)} falha(s)"
            )
            return 1 if falhas else 0
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
