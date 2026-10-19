"""Recolha dos componentes instalados, com a licenca de cada um.

Le **do disco**, nao da rede: os metadados de licenca estao nos pacotes
instalados pelo `make bootstrap`, e um gate que fosse a registo publico por cada
componente falharia por ligacao e nao por licenca — o mesmo defeito que levou a
separar `make lock-check` de `make lock-verify` no KAM-001.

Consequencia a assumir: **sem `make bootstrap`, nao ha componentes para varrer**.
O gate 11 depende do gate 1, e o `Makefile` encadeia-os.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

NPM = "npm"
PYPI = "pypi"


@dataclasses.dataclass(frozen=True)
class Componente:
    ecossistema: str
    nome: str
    versao: str
    licenca: str | None
    #: De onde se leu a licenca, para o relatorio poder ser verificado a mao.
    origem: str
    #: `True` para os pacotes do proprio monorepo.
    #:
    #: E um campo e nao uma inferencia do caminho: os componentes de terceiros
    #: tambem vem de um `package.json` (o de
    #: `node_modules/.pnpm/<pkg>/node_modules/<pkg>/`), e distingui-los pelo
    #: sufixo do caminho classificava-os **todos** como nossos — o que fazia o
    #: SBOM de cada servico ter um componente em vez de tres.
    proprio: bool = False

    @property
    def purl(self) -> str:
        """Package URL, como o CycloneDX espera."""
        if self.ecossistema == NPM:
            if self.nome.startswith("@"):
                ambito, _, resto = self.nome.partition("/")
                return f"pkg:npm/{ambito}/{resto}@{self.versao}"
            return f"pkg:npm/{self.nome}@{self.versao}"
        return f"pkg:pypi/{self.nome}@{self.versao}"

    @property
    def referencia(self) -> str:
        return f"{self.ecossistema}:{self.nome}@{self.versao}"


def _licenca_de_package_json(dados: dict) -> str | None:
    """O campo `license` do npm, nas tres formas que existem."""
    licenca = dados.get("license")
    if isinstance(licenca, str):
        return licenca
    if isinstance(licenca, dict):
        return licenca.get("type")
    # Forma antiga: `licenses: [{type: ...}]`
    licencas = dados.get("licenses")
    if isinstance(licencas, list):
        tipos = [l.get("type") for l in licencas if isinstance(l, dict) and l.get("type")]
        if tipos:
            return " OR ".join(tipos)
    return None


def recolher_npm(raiz: Path) -> list[Componente]:
    """Componentes npm, lidos de `node_modules/.pnpm/*/node_modules/*/package.json`.

    O `pnpm` guarda cada versao uma vez em `.pnpm/<nome>@<versao>/node_modules/`,
    o que torna esta a listagem exacta do que esta instalado — sem duplicados e
    sem depender da arvore de ligacoes simbolicas.
    """
    loja = raiz / "node_modules" / ".pnpm"
    if not loja.is_dir():
        return []

    componentes: dict[str, Componente] = {}
    for pasta in sorted(loja.iterdir()):
        interior = pasta / "node_modules"
        if not interior.is_dir():
            continue
        for manifesto in sorted(interior.rglob("package.json")):
            # So o manifesto de topo de cada pacote; ignora-se o de subpastas
            # (`dist/package.json` e afins).
            relativo = manifesto.relative_to(interior).parts
            if len(relativo) > 3 or (len(relativo) == 3 and not relativo[0].startswith("@")):
                continue
            try:
                dados = json.loads(manifesto.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            nome, versao = dados.get("name"), dados.get("version")
            if not nome or not versao:
                continue
            chave = f"{nome}@{versao}"
            if chave in componentes:
                continue
            componentes[chave] = Componente(
                ecossistema=NPM,
                nome=str(nome),
                versao=str(versao),
                licenca=_licenca_de_package_json(dados),
                origem=manifesto.relative_to(raiz).as_posix(),
            )
    return sorted(componentes.values(), key=lambda c: (c.nome, c.versao))


_CLASSIFICADOR = re.compile(r"^Classifier:\s*License\s*::\s*(?P<resto>.+)$")

#: Classificadores do PyPI traduzidos para SPDX. Lista curta, de proposito: so
#: os que aparecem nas dependencias deste repositorio. Um classificador fora
#: desta lista fica `None` e e tratado como desconhecido — fail-closed.
_CLASSIFICADOR_PARA_SPDX = {
    "OSI Approved :: MIT License": "MIT",
    "OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "OSI Approved :: Apache Software License": "Apache-2.0",
    "OSI Approved :: BSD License": "BSD-3-Clause",
    "OSI Approved :: ISC License (ISCL)": "ISC",
    "OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "OSI Approved :: PostgreSQL License": "PostgreSQL",
}


def _licenca_de_metadata(texto: str) -> tuple[str | None, str]:
    """A licenca de um `METADATA`, pela ordem de fiabilidade dos campos."""
    expressao = None
    antiga = None
    classificadores: list[str] = []

    for linha in texto.split("\n"):
        if linha.startswith("License-Expression:"):
            expressao = linha.split(":", 1)[1].strip()
        elif linha.startswith("License:") and not antiga:
            antiga = linha.split(":", 1)[1].strip()
        else:
            correspondencia = _CLASSIFICADOR.match(linha)
            if correspondencia:
                classificadores.append(correspondencia.group("resto").strip())
        if linha.strip() == "":
            break  # o corpo comeca aqui; os cabecalhos acabaram

    if expressao:
        return expressao, "License-Expression"
    for classificador in classificadores:
        if classificador in _CLASSIFICADOR_PARA_SPDX:
            return _CLASSIFICADOR_PARA_SPDX[classificador], f"Classifier: {classificador}"
    if antiga and len(antiga) < 60:
        # O campo `License` antigo e texto livre. Aceita-se so quando e curto o
        # suficiente para ser um identificador, nunca um paragrafo de licenca.
        return antiga, "License (campo antigo)"
    return None, "sem campo de licenca legivel"


def recolher_pypi(raiz: Path, venv: Path | None = None) -> list[Componente]:
    """Componentes Python, lidos dos `*.dist-info/METADATA` do venv."""
    venv = venv or (raiz / ".venv")
    pastas = [
        venv / "Lib" / "site-packages",            # Windows
        # Ordenado, como todos os outros varrimentos deste ficheiro: um `glob`
        # devolve pela ordem do sistema de ficheiros, e com dois `python3.*` no
        # mesmo `venv` — que acontece ao mudar de minor sem recriar — a versao
        # que ganhava um empate de nome dependia dessa ordem. O SBOM tem de ser
        # determinista, e determinista inclui qual das duas arvores se leu.
        *sorted((venv / "lib").glob("python3.*/site-packages")),  # POSIX
    ]
    componentes: dict[str, Componente] = {}
    for pasta in pastas:
        if not pasta.is_dir():
            continue
        for dist_info in sorted(pasta.glob("*.dist-info")):
            metadata = dist_info / "METADATA"
            if not metadata.is_file():
                continue
            try:
                texto = metadata.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            nome = versao = None
            for linha in texto.split("\n"):
                if linha.startswith("Name:"):
                    nome = linha.split(":", 1)[1].strip()
                elif linha.startswith("Version:"):
                    versao = linha.split(":", 1)[1].strip()
                if nome and versao:
                    break
            if not nome or not versao:
                continue
            licenca, origem = _licenca_de_metadata(texto)
            chave = f"{nome}@{versao}"
            if chave in componentes:
                continue
            componentes[chave] = Componente(
                ecossistema=PYPI,
                nome=nome,
                versao=versao,
                licenca=licenca,
                origem=f"{dist_info.name}/METADATA ({origem})",
            )
    return sorted(componentes.values(), key=lambda c: (c.nome, c.versao))


def recolher_workspace(raiz: Path) -> list[Componente]:
    """Os pacotes do proprio monorepo.

    Nao estao em `node_modules/.pnpm` — essa loja e so de terceiros — e por isso
    nao apareciam no SBOM nenhum. Mas sao componentes da aplicacao, e um SBOM que
    omite o proprio software nao serve para a auditoria a que se destina.

    Declaram `license: UNLICENSED`, que e convencao do npm e nao SPDX. A
    classificacao trata-os por **identidade** (a lista `proprios` de
    `ci/licenses.yaml`), nao pela allowlist: acrescentar `UNLICENSED` as
    permitidas deixaria passar qualquer dependencia de terceiros que a
    declarasse.
    """
    componentes: list[Componente] = []

    for manifesto in sorted(raiz.glob("package.json")) + sorted(
        raiz.glob("*/*/package.json")
    ):
        if "node_modules" in manifesto.parts:
            continue
        try:
            dados = json.loads(manifesto.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        nome, versao = dados.get("name"), dados.get("version")
        if not nome or not versao:
            continue
        componentes.append(
            Componente(
                ecossistema=NPM,
                nome=str(nome),
                versao=str(versao),
                licenca=_licenca_de_package_json(dados),
                origem=manifesto.relative_to(raiz).as_posix(),
                proprio=True,
            )
        )

    # Os pacotes Python do monorepo, dos `pyproject.toml`.
    for manifesto in sorted(raiz.glob("*/*/pyproject.toml")) + sorted(
        raiz.glob("*/pyproject.toml")
    ):
        # A mesma guarda que o varrimento dos `package.json` tem logo acima, e
        # que faltava aqui: um `pyproject.toml` dentro de `node_modules` e de
        # terceiros, e entrava marcado `proprio=True` — isto e, com a licenca
        # dispensada por identidade. Nao ha nenhum hoje; a assimetria e que era
        # o defeito. Encontrada pela revisao adversarial do KAM-133, ao reparar
        # que a funcao nova tinha a guarda e a vizinha nao.
        if "node_modules" in manifesto.parts:
            continue
        texto = manifesto.read_text(encoding="utf-8", errors="replace")
        nome = re.search(r'(?m)^name\s*=\s*"([^"]+)"', texto)
        versao = re.search(r'(?m)^version\s*=\s*"([^"]+)"', texto)
        if not nome or not versao:
            continue
        componentes.append(
            Componente(
                ecossistema=PYPI,
                nome=nome.group(1),
                versao=versao.group(1),
                licenca=None,
                origem=manifesto.relative_to(raiz).as_posix(),
                proprio=True,
            )
        )

    return sorted(componentes, key=lambda c: (c.ecossistema, c.nome))


#: `dependencies = [ ... ]` de um `[project]` de `pyproject.toml`.
_DEPENDENCIAS_PYPROJECT = re.compile(r"(?ms)^dependencies\s*=\s*\[(?P<corpo>.*?)\]")

#: `"kamba-core"`, `'starlette>=1.0'` — uma entrada dessa lista.
_ENTRADA_DE_DEPENDENCIA = re.compile(r"""['"]\s*([^'"]+?)\s*['"]""")


def normalizar_pypi(nome: str) -> str:
    """PEP 503: `-`, `_` e `.` sao equivalentes num nome de pacote PyPI."""
    return nome.strip().lower().replace("_", "-").replace(".", "-")


def declaracoes_python(raiz: Path) -> dict[str, frozenset[str]]:
    """Pasta de um pacote Python nosso -> nomes que o seu `[project]` declara.

    **Todos** os nomes, nossos e de terceiros, normalizados por PEP 503. Quem
    quiser so os nossos usa o `ligacoes_python`, que se constroi daqui: ha um
    unico leitor de `pyproject.toml` de proposito, para que as duas vistas nao
    possam divergir.
    """
    declaracoes: dict[str, set[str]] = {}
    for manifesto in sorted(raiz.glob("*/*/pyproject.toml")) + sorted(
        raiz.glob("*/pyproject.toml")
    ):
        if "node_modules" in manifesto.parts:
            continue
        texto = manifesto.read_text(encoding="utf-8", errors="replace")
        if not re.search(r'(?m)^name\s*=\s*"([^"]+)"', texto):
            continue
        pasta = manifesto.parent.relative_to(raiz).as_posix()
        nomes: set[str] = set()
        bloco = _DEPENDENCIAS_PYPROJECT.search(texto)
        if bloco:
            for entrada in _ENTRADA_DE_DEPENDENCIA.findall(bloco.group("corpo")):
                # `kamba-core>=0.1` -> `kamba-core`. Separa-se no primeiro
                # caracter que nao pode estar num nome de pacote (PEP 508).
                bruto = re.split(r"[<>=!~;\[\s]", entrada, maxsplit=1)[0]
                nomes.add(normalizar_pypi(bruto))
        declaracoes[pasta] = nomes
    return {pasta: frozenset(nomes) for pasta, nomes in declaracoes.items()}


def pacotes_python_proprios(raiz: Path) -> dict[str, str]:
    """Nome normalizado -> pasta, para os pacotes Python do proprio monorepo."""
    nossos: dict[str, str] = {}
    for manifesto in sorted(raiz.glob("*/*/pyproject.toml")) + sorted(
        raiz.glob("*/pyproject.toml")
    ):
        if "node_modules" in manifesto.parts:
            continue
        texto = manifesto.read_text(encoding="utf-8", errors="replace")
        nome = re.search(r'(?m)^name\s*=\s*"([^"]+)"', texto)
        if nome:
            nossos[normalizar_pypi(nome.group(1))] = (
                manifesto.parent.relative_to(raiz).as_posix()
            )
    return nossos


def ligacoes_python(raiz: Path) -> dict[str, set[str]]:
    """Pasta de um pacote Python nosso -> pastas dos nossos que ele declara.

    E o equivalente Python do `link:` do `pnpm`, e o mesmo defeito existia deste
    lado (KAM-133): o `services/agr/pyproject.toml` declara `kamba-core` em
    `[project].dependencies`, e o `kamba-core` nao aparecia no SBOM do
    `services/agr`.

    **Nao e instalacao editavel.** O `make bootstrap` instala os tres
    `requirements/*.txt` com `--require-hashes --no-deps` e **nao** instala
    `kamba-core` nem `kamba-agr` em modo nenhum: chegam ao SBOM pelo
    `pyproject.toml` versionado, que e o que o `recolher_workspace` le. A
    ligacao esta na declaracao, nao no disco — e e por isso que se le daqui.

    So devolve os **nossos**, porque e isso que a travessia por pastas precisa;
    os terceiros declarados saem do `declaracoes_python`, e entram no grafo do
    documento (um `dependsOn` que nomeasse so os nossos dizia que o `kamba-agr`
    depende de um pacote quando o `pyproject.toml` declara tres).
    """
    nossos = pacotes_python_proprios(raiz)
    return {
        pasta: {nossos[n] for n in nomes if n in nossos and nossos[n] != pasta}
        for pasta, nomes in declaracoes_python(raiz).items()
    }


def recolher(raiz: Path, venv: Path | None = None) -> list[Componente]:
    return recolher_workspace(raiz) + recolher_npm(raiz) + recolher_pypi(raiz, venv)


def declaradas_e_nao_instaladas(raiz: Path, venv: Path | None = None) -> list[str]:
    """Dependencias **directas** declaradas que nao estao no disco.

    O gate 11 le os metadados do disco, e por isso o seu modo de falha natural
    e passar: `recolher()` devolvia sempre os 9 pacotes do proprio monorepo
    (que vem dos `package.json` versionados, instalados ou nao), a guarda
    `if not componentes` nunca disparava, e `verificar_licencas` dava verde com
    **zero** terceiros examinados. Um `pnpm install` que nao povoasse o
    `.pnpm`, um `.venv` noutro caminho, ou um `make ci-11` sem `bootstrap`
    davam «licencas conformes» em vez de erro.

    Compara-se contra o que esta **declarado**, que e exacto e nao uma fraccao
    arbitraria: as dependencias directas de cada importador do
    `pnpm-lock.yaml` e os pins dos `requirements/*.in`. Transitivas ficam de
    fora de proposito — uma `optionalDependencies` com `os: [win32]` nao esta
    instalada num runner Linux, e exigi-la daria vermelho por plataforma.
    """
    from . import pnpm_lock

    # PEP 503: `-`, `_` e `.` sao equivalentes num nome de pacote PyPI, e os
    # dois lados tem de ser normalizados. Normalizar so o lado declarado dava
    # `typing-extensions` em falta enquanto `typing_extensions` estava
    # instalado — o CI apanhou-o, a leitura nao.
    def _chave(componente: Componente) -> tuple[str, str]:
        nome = componente.nome.lower()
        if componente.ecossistema == PYPI:
            nome = nome.replace("_", "-").replace(".", "-")
        return (componente.ecossistema, nome)

    instalados = {
        _chave(c) for c in (*recolher_npm(raiz), *recolher_pypi(raiz, venv))
    }
    proprios = {_chave(c) for c in recolher_workspace(raiz)}
    faltam: list[str] = []

    lock = raiz / "pnpm-lock.yaml"
    if lock.is_file():
        grafo = pnpm_lock.ler(lock)
        for pacotes in grafo.directas.values():
            for referencia in pacotes:
                nome, _, _versao = referencia.rpartition("@")
                chave = (NPM, nome.lower())
                if chave not in instalados and chave not in proprios:
                    faltam.append(f"npm:{nome} (declarado no pnpm-lock.yaml)")

    for origem in sorted(raiz.glob("*/requirements/*.in")) + sorted(
        raiz.glob("*/*/requirements/*.in")
    ):
        for linha in origem.read_text(encoding="utf-8").splitlines():
            linha = linha.split("#")[0].strip()
            if not linha or "==" not in linha:
                continue
            nome = linha.split("==")[0].strip()
            normalizado = nome.lower().replace("_", "-").replace(".", "-")
            if (PYPI, normalizado) not in instalados:
                relativo = origem.relative_to(raiz).as_posix()
                faltam.append(f"pypi:{nome} (declarado em {relativo})")

    return sorted(set(faltam))
