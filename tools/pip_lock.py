#!/usr/bin/env python3
"""Gera ficheiros `requirements` com hash a partir de pins exactos.

`pip install --require-hashes` e a metade Python do controlo de "dependencias
fixadas com hash" de `docs/tecnica/08` §4.8. Para funcionar exige duas coisas que
nenhum `requirements.in` escrito a mao tem: **todos** os pacotes da arvore
fixados com `==`, e o sha256 de cada distribuicao.

Esta ferramenta faz as duas, e faz uma terceira que importa mais: **verifica que
o fecho esta completo**. Se um pacote fixado depender de algo que nao esta
fixado, falha e diz qual — em vez de produzir um lock que parece valido e rebenta
no primeiro `pip install` noutra maquina.

Uso:
    python tools/pip_lock.py services/agr/requirements/runtime.in
    python tools/pip_lock.py --check services/agr/requirements/runtime.in

`--check` nao escreve: compara o ficheiro gerado com o que esta em disco e falha
se divergirem. E assim que `make check` prova que o lock nao tem drift.

Depende apenas da biblioteca padrao, pela mesma razao que `lint_arch`: tem de
poder correr antes de haver um ambiente instalado.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PYPI = "https://pypi.org/pypi/{name}/{version}/json"

#: Ambiente-alvo do lock. Os servicos Python da KAMBÁ correm em contentores
#: `python:3.12-*` (`docs/tecnica/09` §3.1); os marcadores avaliam-se contra isto.
TARGET_ENV = {
    "python_version": "3.12",
    "python_full_version": "3.12.12",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
}

_REQ_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[^\]]*)\])?"
    r"==(?P<version>[^;\s]+)"
    r"(?:\s*;\s*(?P<marker>.+))?$"
)
_DIST_REQ = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[^\]]*\])?"
    r"\s*(?P<spec>[^;]*)"
    r"(?:;\s*(?P<marker>.+))?$"
)
# Comparacao simples `chave op "valor"` ou `"valor" op chave`.
_MARKER_CLAUSE = re.compile(
    r"""(?P<left>[A-Za-z_][A-Za-z_0-9]*|"[^"]*"|'[^']*')"""
    r"""\s*(?P<op>==|!=|<=|>=|<|>)\s*"""
    r"""(?P<right>[A-Za-z_][A-Za-z_0-9]*|"[^"]*"|'[^']*')"""
)


def canonical(name: str) -> str:
    """PEP 503: nomes comparam-se em minusculas com `-`, `_` e `.` equivalentes."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in text.split("."):
        digits = re.match(r"^[0-9]+", chunk)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts)


class MarkerUndecided(Exception):
    """O marcador depende de algo que esta ferramenta nao sabe avaliar."""


_NUMERIC_VERSION = re.compile(r"[0-9]+(\.[0-9]+)*")
_WILDCARD_VERSION = re.compile(r"[0-9]+(\.[0-9]+)*\.\*")


def _compare(left: str, op: str, right: str) -> bool:
    """Compara dois valores de marcador, com semantica de versao quando ambos o sao.

    Dois casos que estavam errados e que importam:

    * **`X.*`** (PEP 440) e legal e comum em `requires_dist`. Comparado como
      texto, `"3.12" == "3.12.*"` e falso — o marcador dava-se por falso, a
      dependencia por desnecessaria, e ficava fora da verificacao de fecho. Era o
      unico ponto *fail-open* de um modulo que e todo *fail-closed*, e silencioso.
    * **tipos mistos** (um lado parece versao, o outro nao) comparavam-se como
      texto e devolviam uma resposta que ninguem pediu. Agora levantam
      `MarkerUndecided`, que obriga a fixar o pacote.
    """
    esquerda_versao = bool(_NUMERIC_VERSION.fullmatch(left))
    direita_versao = bool(_NUMERIC_VERSION.fullmatch(right))
    esquerda_wildcard = bool(_WILDCARD_VERSION.fullmatch(left))
    direita_wildcard = bool(_WILDCARD_VERSION.fullmatch(right))

    if (esquerda_versao or esquerda_wildcard) != (direita_versao or direita_wildcard):
        raise MarkerUndecided(f"{left!r} {op} {right!r}: tipos incomparaveis")

    if esquerda_wildcard or direita_wildcard:
        if op not in ("==", "!="):
            raise MarkerUndecided(f"{left!r} {op} {right!r}: wildcard so com == ou !=")
        prefixo, valor = (right, left) if direita_wildcard else (left, right)
        alvo = _version_tuple(prefixo[:-2])  # tira o `.*`
        atual = _version_tuple(valor)
        iguais = atual[: len(alvo)] == alvo
        return iguais if op == "==" else not iguais

    if esquerda_versao and direita_versao:
        a, b = _version_tuple(left), _version_tuple(right)
        width = max(len(a), len(b))
        a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    else:
        a, b = left, right
    return {
        "==": a == b,
        "!=": a != b,
        "<": a < b,
        "<=": a <= b,
        ">": a > b,
        ">=": a >= b,
    }[op]


def marker_is_true(marker: str | None) -> bool:
    """Avalia um marcador PEP 508 no ambiente-alvo, de forma deliberadamente limitada.

    Suporta `and` sobre comparacoes simples e trata `extra == ...` como falso
    (nao instalamos extras). Qualquer outra construcao levanta `MarkerUndecided`:
    e melhor parar e exigir uma decisao humana do que adivinhar e deixar um pacote
    de fora do lock.
    """
    if not marker:
        return True
    marker = marker.strip().strip("()")
    if " or " in marker:
        raise MarkerUndecided(marker)

    clausulas = [c.strip().strip("()") for c in marker.split(" and ")]

    # Um `extra == ...` em qualquer posicao torna a conjuncao falsa: nao se
    # instalam extras. Avalia-se **antes** do resto, porque numa cadeia `and`
    # uma clausula definitivamente falsa decide o resultado — e as outras podem
    # ser indecidiveis.
    #
    # O caso que obrigou a isto: `coverage` declara
    # `tomli; python_full_version <= "3.11.0a6" and extra == "toml"`. A primeira
    # clausula compara com `3.11.0a6`, que nao e numerica, e levantava
    # `MarkerUndecided`; o fecho passava a exigir `tomli`, que nunca e instalado.
    if any(
        (m := _MARKER_CLAUSE.fullmatch(c)) and "extra" in (m.group("left"), m.group("right"))
        for c in clausulas
    ):
        return False

    for clause in clausulas:
        match = _MARKER_CLAUSE.fullmatch(clause)
        if not match:
            raise MarkerUndecided(clause)
        left, op, right = match.group("left"), match.group("op"), match.group("right")

        def resolve(token: str) -> str | None:
            if token[:1] in "\"'":
                return token[1:-1]
            return TARGET_ENV.get(token, None) if token in TARGET_ENV else None

        if left == "extra" or right == "extra":
            return False
        if left in ("sys_platform", "platform_system", "os_name", "platform_machine"):
            # O lock e multi-plataforma: mantem-se a linha com o marcador intacto
            # e e o pip que decide. Para efeitos de fecho, conta como necessaria.
            continue
        resolved_left, resolved_right = resolve(left), resolve(right)
        if resolved_left is None or resolved_right is None:
            raise MarkerUndecided(clause)
        if not _compare(resolved_left, op, resolved_right):
            return False
    return True


def read_pins(path: Path) -> list[dict]:
    """Le um `.in` de pins exactos, preservando marcadores e comentarios de linha."""
    pins: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = _REQ_LINE.fullmatch(line)
        if not match:
            raise SystemExit(
                f"{path}:{lineno}: cada linha tem de ser 'nome==versao[; marcador]' "
                f"(lido: {line!r})"
            )
        pins.append(
            {
                "name": match.group("name"),
                "version": match.group("version"),
                "marker": (match.group("marker") or "").strip() or None,
            }
        )
    if not pins:
        raise SystemExit(f"{path}: nenhum pin encontrado")
    return pins


def fetch_release(name: str, version: str) -> dict:
    url = PYPI.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{name}=={version}: PyPI respondeu {exc.code} ({url})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"{name}=={version}: falha de rede ao consultar PyPI: {exc}") from exc


def hashes_for(release: dict, name: str, version: str) -> list[str]:
    digests = sorted(
        {
            file["digests"]["sha256"]
            for file in release.get("urls", [])
            if not file.get("yanked") and file.get("digests", {}).get("sha256")
        }
    )
    if not digests:
        raise SystemExit(
            f"{name}=={version}: nenhuma distribuicao com sha256 publicada "
            "(versao retirada do PyPI?)"
        )
    return digests


def required_names(release: dict) -> list[tuple[str, str]]:
    """Dependencias de runtime desta versao, no ambiente-alvo: [(nome, requisito)]."""
    out: list[tuple[str, str]] = []
    for requirement in release.get("info", {}).get("requires_dist") or []:
        match = _DIST_REQ.match(requirement.strip())
        if not match:
            continue
        try:
            if not marker_is_true(match.group("marker")):
                continue
        except MarkerUndecided:
            # Fail-closed: exige-se que esteja fixado, e o humano decide.
            pass
        out.append((canonical(match.group("name")), requirement.strip()))
    return out


def render(pins: list[dict], source: Path, releases: dict[str, dict]) -> str:
    lines = [
        "# GERADO POR tools/pip_lock.py — NAO EDITAR A MAO.",
        f"# Origem: {source.as_posix()}",
        "# Regenerar: make lock   |   Verificar: make check",
        "#",
        "# Instala-se exclusivamente com:",
        "#     pip install --require-hashes --no-deps -r <este ficheiro>",
        "#",
        f"# Ambiente-alvo do fecho: CPython {TARGET_ENV['python_version']} "
        "(contentores python:3.12-*, docs/tecnica/09 §3.1).",
        "# Os hashes cobrem todas as distribuicoes publicadas de cada versao, para",
        "# que o mesmo lock sirva Linux, macOS e Windows sem segunda resolucao.",
        "",
    ]
    for pin in sorted(pins, key=lambda p: canonical(p["name"])):
        digests = hashes_for(releases[canonical(pin["name"])], pin["name"], pin["version"])
        requirement = f"{pin['name']}=={pin['version']}"
        if pin["marker"]:
            requirement += f" ; {pin['marker']}"
        lines.append(f"{requirement} \\")
        for index, digest in enumerate(digests):
            suffix = "" if index == len(digests) - 1 else " \\"
            lines.append(f"    --hash=sha256:{digest}{suffix}")
    return "\n".join(lines) + "\n"


def build(source: Path) -> str:
    pins = read_pins(source)
    pinned = {canonical(pin["name"]): pin for pin in pins}
    if len(pinned) != len(pins):
        raise SystemExit(f"{source}: ha nomes repetidos nos pins")

    releases: dict[str, dict] = {}
    for pin in pins:
        releases[canonical(pin["name"])] = fetch_release(pin["name"], pin["version"])

    # Verificacao de fecho: nada depende de algo que nao esteja fixado aqui.
    gaps: list[str] = []
    for pin in pins:
        key = canonical(pin["name"])
        for dependency, requirement in required_names(releases[key]):
            if dependency not in pinned:
                gaps.append(
                    f"{pin['name']}=={pin['version']} exige {requirement!r}, "
                    f"mas {dependency!r} nao esta fixado em {source.name}"
                )
    if gaps:
        message = "\n".join(f"  - {gap}" for gap in gaps)
        raise SystemExit(f"{source}: fecho de dependencias incompleto:\n{message}")

    return render(pins, source, releases)


_LOCK_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)")
_LOCK_HASH = re.compile(r"^\s+--hash=sha256:(?P<digest>[0-9a-f]{64})\s*\\?\s*$")


def check_offline(source: Path, target: Path) -> list[str]:
    """Verifica o lock sem tocar na rede.

    Responde a pergunta que o `make check` precisa de responder a partir de um
    clone limpo e possivelmente sem egresso: **o `.txt` corresponde aos pins do
    `.in`, e cada pin tem hashes?** Nao responde a outra — se os hashes sao os
    que a PyPI publica hoje — que exige rede e vive em `make lock-verify`.

    A separacao e deliberada: o critério de aceitacao do KAM-001 diz que
    `make bootstrap && make check` termina verde "usando apenas lockfiles", e um
    gate que vai a PyPI por cada pin falha por ligacao e nao por codigo.
    """
    problems: list[str] = []
    if not target.exists():
        return [f"{target.name} nao existe; corra 'make lock'"]

    pins = {canonical(pin["name"]): pin for pin in read_pins(source)}

    encontrados: dict[str, dict] = {}
    atual: str | None = None
    for lineno, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if _LOCK_HASH.match(line):
            if atual is None:
                problems.append(f"{target.name}:{lineno}: hash sem pacote acima")
            else:
                encontrados[atual]["hashes"] += 1
            continue
        pin_match = _LOCK_PIN.match(line.strip())
        if pin_match:
            atual = canonical(pin_match.group("name"))
            encontrados[atual] = {
                "version": pin_match.group("version"),
                "hashes": 0,
                "lineno": lineno,
            }
            continue
        problems.append(f"{target.name}:{lineno}: linha nao reconhecida: {line.strip()!r}")

    for nome, pin in pins.items():
        if nome not in encontrados:
            problems.append(f"{pin['name']}=={pin['version']} esta no .in e falta no .txt")
            continue
        achado = encontrados[nome]
        if achado["version"] != pin["version"]:
            problems.append(
                f"{pin['name']}: o .in fixa {pin['version']} e o .txt tem "
                f"{achado['version']} (linha {achado['lineno']})"
            )
        if achado["hashes"] == 0:
            problems.append(
                f"{pin['name']}=={pin['version']} nao tem nenhum --hash "
                f"(linha {achado['lineno']}): sem hash, --require-hashes recusa"
            )

    for nome, achado in encontrados.items():
        if nome not in pins:
            problems.append(
                f"{nome}=={achado['version']} esta no .txt e nao esta fixado no .in "
                f"(linha {achado['lineno']})"
            )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="+", type=Path, help="ficheiros .in de pins exactos")
    parser.add_argument(
        "--check",
        action="store_true",
        help="nao escreve; reconstroi contra a PyPI e falha se divergir (precisa de rede)",
    )
    parser.add_argument(
        "--check-offline",
        action="store_true",
        help="nao escreve e nao usa rede; compara o .txt com os pins do .in",
    )
    args = parser.parse_args(argv)
    if args.check and args.check_offline:
        parser.error("--check e --check-offline excluem-se")

    status = 0
    for source in args.sources:
        if source.suffix != ".in":
            raise SystemExit(f"{source}: esperava um ficheiro .in")
        target = source.with_suffix(".txt")

        if args.check_offline:
            problems = check_offline(source, target)
            if problems:
                print(
                    f"pip_lock: {target.as_posix()}: {len(problems)} problema(s)",
                    file=sys.stderr,
                )
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                status = 1
            else:
                print(f"pip_lock: {target.as_posix()}: coerente com os pins")
            continue

        generated = build(source)
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != generated:
                print(
                    f"pip_lock: {target.as_posix()} esta dessincronizado de "
                    f"{source.as_posix()}; corra 'make lock'",
                    file=sys.stderr,
                )
                status = 1
            else:
                print(f"pip_lock: {target.as_posix()}: sincronizado")
        else:
            # Fins de linha LF explicitos: o .gitattributes fixa LF, e escrever
            # CRLF em Windows faria o ficheiro gerado diferir do que o git guarda.
            target.write_text(generated, encoding="utf-8", newline="\n")
            print(f"pip_lock: {target.as_posix()} escrito")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
