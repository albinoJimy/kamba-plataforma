"""Descoberta e leitura dos manifestos de dependencias do monorepo.

Cada manifesto devolve declaracoes `(ecossistema, nome, especificador)` com a
origem anotada, para que a mensagem de erro aponte para o ficheiro e a linha que
o autor tem de corrigir — e nao apenas para "o repositorio".

Duas notas de desenho que custaram defeitos reais:

1. **Le-se por extraccao estruturada, nao por varrimento de texto.** Um
   varrimento encontraria "minio" dentro de qualquer cadeia e o linter passaria a
   dar falsos positivos — e um gate em que ninguem confia e um gate que alguem
   acaba por desligar.
2. **Os campos que substituem dependencias contam tanto como os que as
   declaram.** `overrides`, `resolutions`, `pnpm.overrides`,
   `build-system.requires`, `-e ...#egg=`, `npm:` e `FROM --platform` sao todos
   formas de meter um pacote na arvore sem o declarar no sitio obvio. Se nao
   forem lidos, a lista de bloqueio cobre as formas que as *fixtures* escolheram
   e nao a classe do problema.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import tomllib
from pathlib import Path

from .names import npm_alias_target, requirement_from_url

NPM = "npm"
PYPI = "pypi"
IMAGE = "image"

_NPM_DEP_FIELDS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
    # Campos que **substituem** dependencias transitivas: o caminho mais
    # interessante para quem quer um pacote proibido na arvore sem o declarar.
    "overrides",
    "resolutions",
)

#: Directorios que nunca se analisam: nao sao fonte, sao resultado.
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pnpm-store",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
}

#: Caminhos (relativos a raiz) que se excluem do varrimento do repositorio.
#: As fixtures do proprio linter contem, de proposito, dependencias proibidas:
#: sao o teste do controlo, nao uma violacao dele. Se esta excepcao desaparecer,
#: `make check` passa a falhar sempre — e o teste `test_repositorio_esta_limpo`
#: falha se a excepcao for larga demais.
SKIP_PATHS = (
    "tools/lint_arch/tests/fixtures",
    # Arvores de trabalho que o Claude Code cria para tarefas paralelas. Sao
    # copias do repositorio: varre-las duplica todos os manifestos e traz as
    # fixtures de bloqueio de volta como se fossem violacoes reais.
    ".claude/worktrees",
)


@dataclasses.dataclass(frozen=True)
class Declaration:
    ecosystem: str
    name: str
    spec: str
    source: str
    detail: str

    def where(self) -> str:
        return f"{self.source} ({self.detail})"


def walk(root: Path):
    """Percorre o repositorio ignorando o que e artefacto.

    Usa `os.walk` com poda dos directorios **antes** de descer, e nao
    `Path.rglob`, por duas razoes que so aparecem num repositorio instalado:

    1. O `rglob` desce a `node_modules` inteiro antes de o filtro o rejeitar. Com
       a arvore do `pnpm` isso sao dezenas de milhares de entradas por nada.
    2. O `pnpm` enche `node_modules/.pnpm` de ligacoes simbolicas, e um
       `path.is_file()` sobre uma ligacao que o Windows nao consegue seguir
       levanta `OSError: [WinError 1920]`. Com o filtro a correr depois do
       `is_file()`, o linter rebentava — com codigo 2, erro de configuracao — em
       qualquer maquina onde alguem tivesse corrido `pnpm install`. Ou seja: em
       todas, depois do primeiro `make bootstrap`.
    """
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        base = Path(dirpath)
        relative_dir = base.relative_to(root).as_posix()
        prefix = "" if relative_dir == "." else f"{relative_dir}/"

        # Poda in-place: o `os.walk` nao desce ao que se retira de `dirnames`.
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRS
            and not any(f"{prefix}{name}".startswith(skip) for skip in SKIP_PATHS)
        )

        for name in sorted(filenames):
            path = base / name
            try:
                if not path.is_file():
                    continue
            except OSError:
                # Ligacao quebrada ou caminho que o sistema nao consegue abrir:
                # nao e um manifesto, e nao justifica parar o linter.
                continue
            yield path


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# ---------------------------------------------------------------------- npm


def _npm_declarations(deps: dict, field: str, source: str) -> list[Declaration]:
    out: list[Declaration] = []
    for name, spec in deps.items():
        spec = str(spec)
        out.append(Declaration(NPM, str(name), spec, source, field))
        # `"storage": "npm:minio@8.0.0"` instala o MinIO sob outro nome.
        alias = npm_alias_target(spec)
        if alias:
            target, version = alias
            out.append(
                Declaration(NPM, target, version, source, f"{field} (alias de {name!r})")
            )
    return out


def from_package_json(path: Path, root: Path) -> list[Declaration]:
    data = json.loads(path.read_text(encoding="utf-8"))
    source = _rel(path, root)
    out: list[Declaration] = []

    for field in _NPM_DEP_FIELDS:
        deps = data.get(field)
        if isinstance(deps, dict):
            out += _npm_declarations(deps, field, source)

    pnpm = data.get("pnpm")
    if isinstance(pnpm, dict):
        for field in ("overrides", "patchedDependencies", "packageExtensions"):
            deps = pnpm.get(field)
            if isinstance(deps, dict):
                out += _npm_declarations(deps, f"pnpm.{field}", source)
        only = pnpm.get("onlyBuiltDependencies")
        if isinstance(only, list):
            for name in only:
                out.append(
                    Declaration(NPM, str(name), "", source, "pnpm.onlyBuiltDependencies")
                )

    return out


# pnpm-lock v9: chaves `nome@versao:` sob `packages:` e `snapshots:`.
_LOCK_SECTION = re.compile(r"^(?P<name>[a-zA-Z][\w-]*):\s*$")
_LOCK_KEY = re.compile(r"^  (?P<key>(?:@[^/\s]+/)?[^@\s/][^@\s]*@[^:\s]+):\s*$")
_LOCK_SPECIFIER = re.compile(r"^\s{8}specifier:\s*(?P<spec>.+?)\s*$")
_LOCK_DEP_NAME = re.compile(r"^\s{6}(?P<name>(?:@[^/\s:]+/)?[^\s:]+):\s*$")


def from_pnpm_lock(path: Path, root: Path) -> list[Declaration]:
    """Extrai os pacotes resolvidos e os especificadores declarados pelos workspaces."""
    out: list[Declaration] = []
    section = ""
    pending_name: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        header = _LOCK_SECTION.match(line)
        if header:
            section = header.group("name")
            pending_name = None
            continue
        if section in ("packages", "snapshots"):
            key = _LOCK_KEY.match(line)
            if key:
                raw = key.group("key")
                name, _, version = raw.rpartition("@")
                out.append(
                    Declaration(NPM, name, version, _rel(path, root), f"{section}: {raw}")
                )
            continue
        if section == "importers":
            dep = _LOCK_DEP_NAME.match(line)
            if dep:
                pending_name = dep.group("name")
                continue
            spec = _LOCK_SPECIFIER.match(line)
            if spec and pending_name:
                out.append(
                    Declaration(
                        NPM,
                        pending_name,
                        spec.group("spec"),
                        _rel(path, root),
                        f"importers: {pending_name}",
                    )
                )
                pending_name = None
    return out


# -------------------------------------------------------------------- Python

# PEP 508 reduzido: nome, extras opcionais, especificador, marcador opcional.
_PEP508 = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[^\]]*\])?"
    r"(?P<spec>[^;#]*)"
)

#: Opcoes de `requirements` que nao sao requisitos e se ignoram sem ruido.
_PIP_OPTIONS = (
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--no-binary",
    "--only-binary",
    "--prefer-binary",
    "--require-hashes",
    "--no-index",
    "--trusted-host",
    "--use-feature",
    "--hash",
    "--pre",
    "-i",
    "-f",
    "-c",
    "--constraint",
    "-r",
    "--requirement",
)


def from_requirements(path: Path, root: Path) -> list[Declaration]:
    """Le um ficheiro de requirements, incluindo as formas que nao nomeiam o pacote.

    `-e git+https://...#egg=langgraph-api` e um URL de *wheel* instalam pacotes
    sem os declarar como requisitos. Qualquer linha que nao se consiga
    classificar devolve-se com o nome `?`, para que apareca como achado em vez de
    desaparecer — a postura fail-closed que `versions.py` declara.
    """
    out: list[Declaration] = []
    source = _rel(path, root)
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split(" #", 1)[0].strip()
        line = line.split("--hash=", 1)[0].strip().rstrip("\\").strip()
        if not line:
            continue

        where = f"linha {lineno}"
        if line.startswith(("-e ", "--editable ")):
            line = line.split(" ", 1)[1].strip()
        elif line.startswith("-"):
            head = line.split("=", 1)[0].split(" ", 1)[0]
            if head in _PIP_OPTIONS:
                continue
            out.append(
                Declaration(PYPI, "?", line, source, f"{where}: opcao desconhecida")
            )
            continue

        # `nome @ url` e a forma PEP 508 directa.
        if " @ " in line:
            name, _, url = line.partition(" @ ")
            match = _PEP508.match(name.strip())
            out.append(
                Declaration(
                    PYPI,
                    match.group("name") if match else name.strip(),
                    url.strip(),
                    source,
                    where,
                )
            )
            continue

        if "://" in line or line.startswith("git+"):
            name = requirement_from_url(line)
            out.append(
                Declaration(
                    PYPI,
                    name or "?",
                    line,
                    source,
                    f"{where}: {'egg/wheel' if name else 'URL sem nome identificavel'}",
                )
            )
            continue

        match = _PEP508.match(line)
        if not match:
            out.append(
                Declaration(PYPI, "?", line, source, f"{where}: nao classificada")
            )
            continue
        out.append(
            Declaration(PYPI, match.group("name"), match.group("spec").strip(), source, where)
        )
    return out


def from_pyproject(path: Path, root: Path) -> list[Declaration]:
    """Le um `pyproject.toml`, incluindo os sitios que nao sao PEP 621.

    `build-system.requires` e o mais importante dos que faltavam: e instalado por
    `pip` num ambiente de construcao isolado **antes** de tudo o mais, e sem
    `--require-hashes` — exactamente o risco que o `Dockerfile` do AGR descreve
    por escrito.
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    source = _rel(path, root)
    out: list[Declaration] = []

    def add(requirements, detail: str) -> None:
        for requirement in requirements or []:
            if not isinstance(requirement, str):
                continue
            match = _PEP508.match(requirement.strip())
            if match:
                out.append(
                    Declaration(
                        PYPI, match.group("name"), match.group("spec").strip(), source, detail
                    )
                )

    def add_mapping(mapping, detail: str) -> None:
        if not isinstance(mapping, dict):
            return
        for name, spec in mapping.items():
            value = str(spec.get("version", "")) if isinstance(spec, dict) else str(spec)
            out.append(Declaration(PYPI, str(name), value, source, detail))

    add((data.get("build-system") or {}).get("requires"), "build-system.requires")

    project = data.get("project") or {}
    add(project.get("dependencies"), "project.dependencies")
    for extra, requirements in (project.get("optional-dependencies") or {}).items():
        add(requirements, f"project.optional-dependencies.{extra}")

    for group, requirements in (data.get("dependency-groups") or {}).items():
        add(requirements, f"dependency-groups.{group}")

    tool = data.get("tool") or {}

    poetry = tool.get("poetry") or {}
    add_mapping(poetry.get("dependencies"), "tool.poetry.dependencies")
    add_mapping(poetry.get("dev-dependencies"), "tool.poetry.dev-dependencies")
    for group, body in (poetry.get("group") or {}).items():
        add_mapping((body or {}).get("dependencies"), f"tool.poetry.group.{group}.dependencies")

    uv = tool.get("uv") or {}
    for field in ("dev-dependencies", "constraint-dependencies", "override-dependencies"):
        add(uv.get(field), f"tool.uv.{field}")

    pdm = tool.get("pdm") or {}
    pdm_dev = pdm.get("dev-dependencies")
    if isinstance(pdm_dev, dict):
        for group, requirements in pdm_dev.items():
            add(requirements, f"tool.pdm.dev-dependencies.{group}")

    for env, body in ((tool.get("hatch") or {}).get("envs") or {}).items():
        add((body or {}).get("dependencies"), f"tool.hatch.envs.{env}.dependencies")

    return out


# -------------------------------------------------------------- Docker, compose

_COMPOSE_IMAGE = re.compile(
    r"""^\s*image:\s*["']?(?P<image>[^"'#\s]+)["']?\s*(?:\#.*)?$"""
)
#: Valores de `build.args` que parecem referencias de imagem. Um
#: `BASE_IMAGE: minio/minio:...` e um idioma natural num compose que ja
#: parametriza imagens por variavel, como este.
_COMPOSE_ARG = re.compile(
    r"""^(?P<indent>\s+)(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*["']?"""
    r"""(?P<value>[a-z0-9][\w.-]*(?:/[\w.-]+)+(?::[\w.-]+)?|[a-z0-9][\w.-]*:[\w.-]+)"""
    r"""["']?\s*(?:\#.*)?$"""
)
_DOCKER_FROM = re.compile(r"^\s*FROM\s+(?P<rest>.+?)\s*$", re.IGNORECASE)
_DOCKER_ARG = re.compile(
    r"^\s*ARG\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\S+)", re.IGNORECASE
)
_DOCKER_VAR = re.compile(r"^\$\{?(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}?$")


def _is_compose(path: Path) -> bool:
    """Um ficheiro de compose reconhece-se pelo conteudo, nao pelo nome.

    `stack.yml`, `kamba.yaml` e `dev.yml` sao nomes legitimos de compose, e um
    padrao ancorado em "compose" deixava-os invisiveis.
    """
    if path.suffix not in (".yml", ".yaml"):
        return False
    if re.fullmatch(r"(docker-)?compose.*", path.stem):
        return True
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return False
    return re.search(r"^services:\s*$", head, flags=re.MULTILINE) is not None


def from_compose(path: Path, root: Path) -> list[Declaration]:
    out: list[Declaration] = []
    source = _rel(path, root)
    args_indent: int | None = None

    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        image = _COMPOSE_IMAGE.match(line)
        if image:
            out.append(
                Declaration(IMAGE, image.group("image"), "", source, f"image: linha {lineno}")
            )
            args_indent = None
            continue

        opens_args = re.match(r"^(?P<indent>\s*)args:\s*$", line)
        if opens_args:
            args_indent = len(opens_args.group("indent"))
            continue

        if args_indent is not None:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= args_indent:
                args_indent = None
            else:
                arg = _COMPOSE_ARG.match(line)
                if arg:
                    out.append(
                        Declaration(
                            IMAGE,
                            arg.group("value"),
                            "",
                            source,
                            f"build.args.{arg.group('key')}: linha {lineno}",
                        )
                    )
                continue
    return out


#: `pip install` no **inicio de um segmento de shell**. Apanha `pip`, `pip3`,
#: `python -m pip` e `uv pip`, com ou sem `sudo` e com variaveis de ambiente a
#: frente (`PIP_NO_CACHE=1 pip install ...`).
#:
#: Ancorado no inicio do segmento de proposito: a primeira versao procurava
#: `pip install` em qualquer parte da linha e levava o **resto da linha toda**,
#: pelo que um `RUN pip install -r req.txt && pip3 install x` dava os nomes
#: `&&`, `pip3` e `install` como pacotes. Segmenta-se primeiro pelo shell
#: (`_SEPARADOR_DE_SHELL`) e so depois se procura, o que tambem apanha o
#: **segundo** `pip install` da mesma linha, que a primeira versao perdia.
_PIP_NA_BUILD = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:sudo\s+)?"
    r"(?:uv\s+pip|pip3?|python3?\s+-m\s+pip)\s+install\b(?P<resto>.*)$",
    re.IGNORECASE,
)

#: O que separa dois comandos numa linha de `RUN`.
_SEPARADOR_DE_SHELL = re.compile(r"&&|\|\||[;&|]")

#: Opcoes de `pip install` que levam valor: o token seguinte nao e um pacote.
_PIP_COM_VALOR = frozenset(
    {
        "-r", "--requirement", "-c", "--constraint", "-i", "--index-url",
        "--extra-index-url", "-f", "--find-links", "--target", "-t",
        "--platform", "--python-version", "--implementation", "--abi",
        "--prefix", "--root", "--cache-dir", "--log", "--proxy",
        "--trusted-host", "--only-binary", "--no-binary", "--hash",
    }
)

#: O que separa um nome de pacote do seu especificador de versao.
_FIM_DO_NOME = re.compile(r"[\[<>=!~;@\s]")


def _pacotes_de_pip(resto: str) -> list[str]:
    """Os nomes de pacote de uma linha `pip install`. So nomes, sem versao.

    `-r requirements.txt` nao da pacote nenhum: aquele ficheiro e varrido por si
    (`_is_requirements_file`), e contar o nome dele como pacote dava um achado
    por um ficheiro que o lint ja le.
    """
    nomes: list[str] = []
    saltar = False
    for token in resto.split():
        if saltar:
            saltar = False
            continue
        # As continuacoes de linha ja foram juntas por quem chama; o que sobra e
        # uma barra solta. **Nao se troca por espaco**: um `\` seguido de letra
        # dava um nome de pacote inventado (`\n` -> `n`), e um nome inventado
        # numa lista de bloqueio e ruido que um dia alguem desliga.
        if "\\" in token:
            continue
        if token in _PIP_COM_VALOR:
            saltar = True
            continue
        if token.startswith("-"):
            # `--no-cache-dir`, `-U`, `--upgrade`: opcoes sem valor, ou
            # `--opcao=valor`, que tambem nao e pacote.
            continue
        if token.startswith((".", "/", "git+", "http://", "https://")):
            # Um caminho ou um URL nao e um nome que a lista de bloqueio
            # reconheca; deixa-se passar em vez de inventar um nome.
            continue
        nome = _FIM_DO_NOME.split(token, 1)[0]
        if nome:
            nomes.append(nome)
    return nomes


def from_dockerfile(path: Path, root: Path) -> list[Declaration]:
    """Le os `FROM`, os `ARG` de imagem e os `pip install` dos `RUN`.

    `FROM --platform=linux/amd64 minio/minio:...` tem de ser apanhado: capturar o
    primeiro token depois de `FROM` daria a *flag* como nome da imagem, e a
    imagem real nunca seria examinada.

    **Os `RUN pip install` entram com o KAM-030**, e fecham metade de um critero
    de aceitacao que o lint nao cobria: «`pip install litellm` na *build* reprova
    o lint» (criterio 1). Antes desta leitura, um `RUN pip install litellm==1.82.7`
    num Dockerfile passava limpo — a entrada `litellm` de `tools/blocklist.yaml`
    e `kind: any` e estava la desde o KAM-067, mas nenhuma declaracao PyPI saia
    de um Dockerfile para ela se aplicar. Medido: era a unica das quatro clausulas
    do criterio 1 sem maquina a impo-la.

    Vale para qualquer pacote bloqueado, nao so o LiteLLM — e isso e o ponto: o
    `langgraph-api` do ADR-002 corria o mesmo risco.
    """
    out: list[Declaration] = []
    source = _rel(path, root)
    args: dict[str, str] = {}
    stages: set[str] = set()

    # Junta as continuacoes de linha: um `RUN pip install \\\n    pacote` e uma
    # instrucao so, e ler linha a linha perdia o nome do pacote.
    bruto = path.read_text(encoding="utf-8")
    linhas_juntas: list[tuple[int, str]] = []
    acumulado = ""
    inicio = 1
    for numero, linha in enumerate(bruto.splitlines(), start=1):
        if not acumulado:
            inicio = numero
        if linha.rstrip().endswith("\\"):
            acumulado += linha.rstrip()[:-1] + " "
            continue
        linhas_juntas.append((inicio, acumulado + linha))
        acumulado = ""
    if acumulado:
        linhas_juntas.append((inicio, acumulado))

    for lineno, linha in linhas_juntas:
        despido = linha.lstrip()
        if not despido.upper().startswith("RUN "):
            continue
        corpo = despido[4:]
        for segmento in _SEPARADOR_DE_SHELL.split(corpo):
            achado = _PIP_NA_BUILD.match(segmento)
            if not achado:
                continue
            for nome in _pacotes_de_pip(achado.group("resto")):
                out.append(
                    Declaration(
                        PYPI, nome, "", source, f"RUN pip install: linha {lineno}"
                    )
                )

    for lineno, line in enumerate(bruto.splitlines(), start=1):
        declared = _DOCKER_ARG.match(line)
        if declared:
            value = declared.group("value").strip("\"'")
            args[declared.group("name")] = value
            out.append(
                Declaration(
                    IMAGE, value, "", source, f"ARG {declared.group('name')}: linha {lineno}"
                )
            )
            continue

        match = _DOCKER_FROM.match(line)
        if not match:
            continue

        tokens = [t for t in match.group("rest").split() if not t.startswith("--")]
        if len(tokens) >= 3 and tokens[-2].lower() == "as":
            stages.add(tokens[-1].lower())
            tokens = tokens[:-2]
        if not tokens:
            out.append(
                Declaration(IMAGE, "?", line.strip(), source, f"FROM sem imagem: linha {lineno}")
            )
            continue

        image = tokens[0]
        variable = _DOCKER_VAR.match(image)
        if variable:
            if variable.group("name") in args:
                # Ja foi registada como ARG; nao se conta duas vezes.
                continue
            out.append(
                Declaration(IMAGE, image, "", source, f"FROM nao resolvido: linha {lineno}")
            )
            continue
        if image.lower() in stages:
            # `FROM deps AS runtime`: referencia a um andar, nao a uma imagem.
            continue
        out.append(Declaration(IMAGE, image, "", source, f"FROM: linha {lineno}"))

    return out


# ------------------------------------------------------------------- recolha


def _is_requirements_file(path: Path) -> bool:
    """`requirements.txt`, `requirements-dev.in`, e tambem `requirements/runtime.txt`.

    O segundo caso e o que o repositorio usa de facto (`services/agr/requirements/`)
    e e o que um padrao ancorado no nome do ficheiro deixaria passar: o lock do
    AGR ficaria fora do varrimento, que e precisamente onde uma dependencia
    proibida mais interessa apanhar.
    """
    if path.suffix not in (".txt", ".in"):
        return False
    if re.fullmatch(r"requirements.*", path.stem):
        return True
    return path.parent.name == "requirements"


def collect(root: Path) -> list[Declaration]:
    """Le todos os manifestos reconhecidos sob `root`."""
    out: list[Declaration] = []
    for path in walk(root):
        name = path.name
        if name == "package.json":
            out += from_package_json(path, root)
        elif name == "pnpm-lock.yaml":
            out += from_pnpm_lock(path, root)
        elif name == "pyproject.toml":
            out += from_pyproject(path, root)
        elif _is_requirements_file(path):
            out += from_requirements(path, root)
        elif _is_compose(path):
            out += from_compose(path, root)
        elif name == "Dockerfile" or name.startswith("Dockerfile."):
            out += from_dockerfile(path, root)
    return out
