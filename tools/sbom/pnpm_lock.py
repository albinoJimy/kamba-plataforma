"""Fecho de dependencias por *importador*, lido do `pnpm-lock.yaml`.

Existe porque a alternativa era pior. O `pnpm` guarda uma loja unica
(`node_modules/.pnpm`), pelo que «o que esta instalado» e sempre o workspace
inteiro: um SBOM por servico construido assim dava nove ficheiros com os mesmos
92 componentes — o que satisfaz a letra de «SBOM por servico» e nao a sua
utilidade. Um SBOM que nao distingue o que cada servico carrega nao responde a
pergunta a que um SBOM existe para responder.

O lockfile tem a informacao: a secçao `importers:` diz as dependencias directas
de cada pacote do workspace, e a secçao `snapshots:` diz as dependencias de cada
pacote resolvido. Daqui tira-se o fecho real, por travessia.

Nao se usa o `tools/kamba_yaml.py`: o `pnpm-lock.yaml` esta muito fora do
subconjunto que ele aceita (chaves com `@` e `/`, aninhamento profundo), e
alarga-lo para o ler tirar-lhe-ia a propriedade de ser recusado para tudo o que
nao seja configuracao nossa. Le-se por extraccao das chaves conhecidas, como o
`lint_arch/manifests.py` ja faz para a lista de bloqueio.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `importers:` / `snapshots:` / `packages:` — cabecalhos de secçao, sem indentacao.
_SECCAO = re.compile(r"^(?P<nome>[a-zA-Z][\w-]*):\s*$")

#: Um importador: `  .:` ou `  services/gwy:`
_IMPORTADOR = re.compile(r"^  '?(?P<caminho>[^\s:']+)'?:\s*$")

#: `    dependencies:` / `    devDependencies:` dentro de um importador.
_GRUPO = re.compile(r"^    (?P<grupo>dependencies|devDependencies|optionalDependencies):\s*$")

#: `      hono:` ou `      '@hono/node-server':` — dependencia directa.
#: As chaves com `@` ou `/` vem entre aspas simples no YAML do pnpm.
_DEP_DIRECTA = re.compile(r"^      '?(?P<nome>(?:@[^/\s:']+/)?[^\s:']+)'?:\s*$")

#: `        version: 4.13.13` — a versao resolvida dessa dependencia.
_VERSAO = re.compile(r"^        version:\s*(?P<versao>[^\s(]+)")

#: `  hono@4.13.13:` ou `  '@commitlint/cli@21.2.3':` — chave de um snapshot.
_SNAPSHOT = re.compile(r"^  '?(?P<chave>(?:@[^/\s']+/)?[^@\s']+@[^:\s']+)'?:\s*$")

#: `      hono: 4.13.13` ou `      '@commitlint/format': 21.2.3`.
_SNAPSHOT_DEP = re.compile(
    r"^      '?(?P<nome>(?:@[^/\s:']+/)?[^\s:']+)'?:\s*(?P<versao>\S+)\s*$"
)

#: `    dependencies:` / `    optionalDependencies:` dentro de um snapshot.
_SNAPSHOT_GRUPO = re.compile(
    r"^    (?P<grupo>dependencies|optionalDependencies|transitivePeerDependencies):\s*$"
)


def _limpar_versao(versao: str) -> str:
    """`4.13.13(peer@1.0.0)` -> `4.13.13`. Os pares nao fazem parte da versao."""
    return versao.split("(")[0].strip().strip("'\"")


def _normalizar_chave(chave: str) -> str:
    """`@commitlint/cli@21.2.3(@types/node@24.19.2)(typescript@5.9.3)` ->
    `@commitlint/cli@21.2.3`.

    As chaves de `snapshots:` carregam o sufixo dos pares resolvidos; os valores
    das dependencias nao. Sem normalizar as duas pontas, a travessia para no
    primeiro pacote com pares — e o `@commitlint/cli` tem tres, pelo que o fecho
    da raiz dava 12 componentes em vez dos ~70 reais.
    """
    return chave.split("(")[0].strip().strip("'\"")


def ler(caminho: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Devolve (directas_por_importador, dependencias_por_snapshot).

    As chaves de ambos os dicionarios sao `nome@versao`.
    """
    directas: dict[str, set[str]] = {}
    snapshots: dict[str, set[str]] = {}

    seccao = ""
    importador: str | None = None
    dentro_de_grupo = False
    dep_pendente: str | None = None
    snapshot: str | None = None

    for linha in caminho.read_text(encoding="utf-8").split("\n"):
        cabecalho = _SECCAO.match(linha)
        if cabecalho:
            nova = cabecalho.group("nome")
            # O lockfile tem **dois** blocos de seccoes. O primeiro descreve as
            # dependencias do proprio gestor de pacotes
            # (`packageManagerDependencies`: os binarios `@pnpm/exe.*` para 14
            # plataformas); o segundo e o projecto. Ao reencontrar `importers:`,
            # recomeca-se — vale o ultimo bloco, que e o que descreve o codigo.
            if nova == "importers" and directas:
                directas.clear()
                snapshots.clear()
            seccao = nova
            importador = snapshot = dep_pendente = None
            dentro_de_grupo = False
            continue

        if seccao == "importers":
            alvo = _IMPORTADOR.match(linha)
            if alvo:
                importador = alvo.group("caminho")
                directas.setdefault(importador, set())
                dentro_de_grupo = False
                dep_pendente = None
                continue
            if _GRUPO.match(linha):
                dentro_de_grupo = True
                continue
            if dentro_de_grupo and importador is not None:
                dep = _DEP_DIRECTA.match(linha)
                if dep:
                    dep_pendente = dep.group("nome")
                    continue
                versao = _VERSAO.match(linha)
                if versao and dep_pendente:
                    limpa = _limpar_versao(versao.group("versao"))
                    # Dependencias de workspace resolvem para `link:...`; nao sao
                    # componentes de terceiros e entram pelo proprio workspace.
                    if not limpa.startswith("link:"):
                        directas[importador].add(f"{dep_pendente}@{limpa}")
                    dep_pendente = None
            continue

        if seccao == "snapshots":
            chave = _SNAPSHOT.match(linha)
            if chave:
                snapshot = _normalizar_chave(chave.group("chave"))
                snapshots.setdefault(snapshot, set())
                dentro_de_grupo = False
                continue
            if _SNAPSHOT_GRUPO.match(linha):
                # `transitivePeerDependencies` e uma lista de nomes sem versao;
                # nao se segue, porque nao identifica um componente.
                dentro_de_grupo = (
                    _SNAPSHOT_GRUPO.match(linha).group("grupo") != "transitivePeerDependencies"
                )
                continue
            if snapshot is not None and dentro_de_grupo:
                dep = _SNAPSHOT_DEP.match(linha)
                if dep:
                    limpa = _limpar_versao(dep.group("versao"))
                    if limpa and not limpa.startswith("link:"):
                        snapshots[snapshot].add(f"{dep.group('nome')}@{limpa}")
            continue

    return directas, snapshots


def fecho(
    importador: str,
    directas: dict[str, set[str]],
    snapshots: dict[str, set[str]],
) -> set[str]:
    """Fecho transitivo das dependencias de um importador, por travessia.

    Travessia em largura com conjunto de visitados — o grafo tem ciclos (o npm
    permite dependencias mutuas) e uma recursao ingenua nao terminaria.
    """
    por_visitar = list(directas.get(importador, set()))
    visitados: set[str] = set()
    while por_visitar:
        actual = por_visitar.pop()
        if actual in visitados:
            continue
        visitados.add(actual)
        por_visitar.extend(snapshots.get(actual, set()) - visitados)
    return visitados
