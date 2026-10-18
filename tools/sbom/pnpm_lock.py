"""Fecho de dependencias por *importador*, lido do `pnpm-lock.yaml`.

Existe porque a alternativa era pior. O `pnpm` guarda uma loja unica
(`node_modules/.pnpm`), pelo que «o que esta instalado» e sempre o workspace
inteiro: um SBOM por servico construido assim dava nove ficheiros com os mesmos
componentes — o que satisfaz a letra de «SBOM por servico» e nao a sua
utilidade. Um SBOM que nao distingue o que cada servico carrega nao responde a
pergunta a que um SBOM existe para responder.

O lockfile tem a informacao: a secçao `importers:` diz as dependencias directas
de cada pacote do workspace, e a secçao `snapshots:` diz as dependencias de cada
pacote resolvido. Daqui tira-se o fecho real, por travessia.

**A travessia atravessa um `link:` (KAM-133).** Uma dependencia de outro pacote
do proprio workspace resolve-se no lockfile como `link:../../packages/core-ts` —
um caminho relativo ao importador, e nao uma versao publicada. A primeira versao
deste modulo descartava essas linhas, e com isso o `services/gwy` levava tres
componentes e nao mostrava nem o `@kamba/core-ts` que carrega nem o `bullmq` que
o `core-ts` lhe traz. O caminho mapeia-se de volta a chave do importador
correspondente (`services/gwy` + `../../packages/core-ts` -> `packages/core-ts`)
e a travessia continua dali.

**Atravessar nao e copiar.** Ao entrar num pacote do workspace seguem-se so os
grupos que um consumidor herda — `dependencies` e `optionalDependencies` — e nao
as `devDependencies`, que sao as ferramentas com que esse pacote se constroi e
nao fazem parte do que o servico carrega. O `@kamba/core-ts` declara o `pg` em
`devDependencies`; o `pg` aparece na mesma no fecho do `services/gwy`, mas por
ser `optionalDependencies` do `bullmq` — que e o caminho verdadeiro, e e o que o
SBOM passa a mostrar. As `devDependencies` do **proprio** alvo continuam a
contar: sem isso a raiz, que so tem `devDependencies`, ficaria com zero.

Nao se usa o `tools/kamba_yaml.py`: o `pnpm-lock.yaml` esta muito fora do
subconjunto que ele aceita (chaves com `@` e `/`, aninhamento profundo), e
alarga-lo para o ler tirar-lhe-ia a propriedade de ser recusado para tudo o que
nao seja configuracao nossa. Le-se por extraccao das chaves conhecidas, como o
`lint_arch/manifests.py` ja faz para a lista de bloqueio.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re
from pathlib import Path

#: `importers:` / `snapshots:` / `packages:` — cabecalhos de secçao, sem indentacao.
_SECCAO = re.compile(r"^(?P<nome>[a-zA-Z][\w-]*):\s*$")

#: Um importador: `  .:`, `  services/gwy:` ou `  packages/contracts: {}`.
#:
#: O `{}` nao e decorativo. Um pacote do workspace **sem dependencias** escreve-se
#: assim no lockfile, e a primeira versao deste padrao exigia fim de linha logo
#: a seguir aos dois pontos: o `packages/contracts` nunca era registado como
#: importador, pelo que o `link:` que lhe apontava nao tinha destino conhecido e
#: o `@kamba/contracts` nao entrava no SBOM de nenhum dos quatro servicos que o
#: declaram (KAM-133). Nao se via porque, sem travessia de `link:`, nada o
#: procurava.
_IMPORTADOR = re.compile(r"^  '?(?P<caminho>[^\s:']+)'?:\s*(?:\{\s*\})?\s*$")

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

#: Os grupos que um consumidor **herda** ao ligar-se a um pacote do workspace.
#: As `devDependencies` ficam de fora de proposito: ver o cabecalho do modulo.
GRUPOS_HERDADOS = frozenset({"dependencies", "optionalDependencies"})

#: Prefixo que distingue, dentro de `Fecho.relacoes`, um no que e um importador
#: do workspace de um no que e um pacote de terceiros (`nome@versao`). Sem
#: prefixo, um importador chamado `hono` colidia com o pacote `hono`.
PREFIXO_WORKSPACE = "workspace:"


@dataclasses.dataclass(frozen=True)
class Grafo:
    """O que o `pnpm-lock.yaml` diz, na forma em que a travessia o usa.

    Era um par de dicionarios. Passou a ter nome porque o KAM-133 lhe
    acrescentou as ligacoes do workspace e a distincao entre o que um alvo
    declara e o que um consumidor dele herda — cinco valores posicionais num
    `return` seriam ilegiveis onde quatro ja eram.
    """

    #: importador -> `{nome@versao}` de terceiros declarados directamente, em
    #: **todos** os grupos. E o que o proprio alvo carrega.
    directas: dict[str, set[str]]
    #: O mesmo, so dos `GRUPOS_HERDADOS`. E o que um consumidor deste importador
    #: recebe ao ligar-se a ele.
    directas_herdadas: dict[str, set[str]]
    #: `nome@versao` -> `{nome@versao}` das dependencias de cada snapshot.
    snapshots: dict[str, set[str]]
    #: importador -> `{(nome do pacote, importador ligado)}`, de todos os grupos.
    ligacoes: dict[str, set[tuple[str, str]]]
    #: O mesmo, so dos `GRUPOS_HERDADOS`.
    ligacoes_herdadas: dict[str, set[tuple[str, str]]]


@dataclasses.dataclass(frozen=True)
class Fecho:
    """O que um alvo carrega, depois da travessia."""

    #: `{nome@versao}` dos pacotes de terceiros, transitivamente.
    terceiros: frozenset[str]
    #: Os importadores do workspace alcancados por `link:`, **sem** o de partida
    #: (esse e o proprio alvo, e entra pela sua identidade e nao pela travessia).
    importadores: frozenset[str]
    #: no -> nos de que depende. Um no e `nome@versao` (terceiro) ou
    #: `workspace:<caminho>` (importador). Serve o grafo `dependencies` do
    #: CycloneDX; sem ele o SBOM diria **que** o `bullmq` la esta e nao **porque**.
    relacoes: dict[str, frozenset[str]]


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


def resolver_ligacao(importador: str, especificador: str) -> str:
    """`services/gwy` + `link:../../packages/core-ts` -> `packages/core-ts`.

    O caminho de um `link:` e relativo a pasta do importador, e as chaves da
    secçao `importers:` sao relativas a raiz do repositorio. Normaliza-se em
    POSIX porque e nisso que o lockfile esta escrito, inclusive em Windows: um
    `os.path.normpath` daria `packages\\core-ts`, que nao e chave de importador
    nenhum e fazia a ligacao desaparecer em silencio no sistema operativo em que
    este repositorio mais se corre.
    """
    caminho = especificador[len("link:") :].strip()
    base = "" if importador in (".", "") else importador
    return posixpath.normpath(posixpath.join(base, caminho) if base else caminho)


def ler(caminho: Path) -> Grafo:
    """Le o `pnpm-lock.yaml` e devolve o `Grafo`."""
    directas: dict[str, set[str]] = {}
    directas_herdadas: dict[str, set[str]] = {}
    snapshots: dict[str, set[str]] = {}
    ligacoes: dict[str, set[tuple[str, str]]] = {}
    ligacoes_herdadas: dict[str, set[tuple[str, str]]] = {}

    seccao = ""
    importador: str | None = None
    grupo: str | None = None
    dep_pendente: str | None = None
    snapshot: str | None = None

    def recomecar() -> None:
        for mapa in (directas, directas_herdadas, snapshots, ligacoes, ligacoes_herdadas):
            mapa.clear()

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
                recomecar()
            seccao = nova
            importador = snapshot = dep_pendente = grupo = None
            continue

        if seccao == "importers":
            alvo = _IMPORTADOR.match(linha)
            if alvo:
                importador = alvo.group("caminho")
                directas.setdefault(importador, set())
                directas_herdadas.setdefault(importador, set())
                ligacoes.setdefault(importador, set())
                ligacoes_herdadas.setdefault(importador, set())
                grupo = None
                dep_pendente = None
                continue
            cabecalho_de_grupo = _GRUPO.match(linha)
            if cabecalho_de_grupo:
                grupo = cabecalho_de_grupo.group("grupo")
                continue
            if grupo is not None and importador is not None:
                dep = _DEP_DIRECTA.match(linha)
                if dep:
                    dep_pendente = dep.group("nome")
                    continue
                versao = _VERSAO.match(linha)
                if versao and dep_pendente:
                    limpa = _limpar_versao(versao.group("versao"))
                    herdado = grupo in GRUPOS_HERDADOS
                    if limpa.startswith("link:"):
                        # Dependencia de outro pacote do workspace. Guarda-se o
                        # par (nome, importador de destino): o nome serve para o
                        # erro ser legivel, o destino para a travessia continuar.
                        par = (dep_pendente, resolver_ligacao(importador, limpa))
                        ligacoes[importador].add(par)
                        if herdado:
                            ligacoes_herdadas[importador].add(par)
                    else:
                        directas[importador].add(f"{dep_pendente}@{limpa}")
                        if herdado:
                            directas_herdadas[importador].add(f"{dep_pendente}@{limpa}")
                    dep_pendente = None
            continue

        if seccao == "snapshots":
            chave = _SNAPSHOT.match(linha)
            if chave:
                snapshot = _normalizar_chave(chave.group("chave"))
                snapshots.setdefault(snapshot, set())
                grupo = None
                continue
            cabecalho_de_grupo = _SNAPSHOT_GRUPO.match(linha)
            if cabecalho_de_grupo:
                # `transitivePeerDependencies` e uma lista de nomes sem versao;
                # nao se segue, porque nao identifica um componente.
                nome_do_grupo = cabecalho_de_grupo.group("grupo")
                if nome_do_grupo == "transitivePeerDependencies":
                    grupo = None
                else:
                    grupo = nome_do_grupo
                continue
            if snapshot is not None and grupo is not None:
                dep = _SNAPSHOT_DEP.match(linha)
                if dep:
                    limpa = _limpar_versao(dep.group("versao"))
                    # Um `link:` dentro de `snapshots:` nao existe no pnpm 9 —
                    # as ligacoes do workspace vivem so em `importers:`. A
                    # guarda fica porque uma resolucao sem versao nao identifica
                    # componente nenhum, venha de onde vier.
                    if limpa and not limpa.startswith("link:"):
                        snapshots[snapshot].add(f"{dep.group('nome')}@{limpa}")
            continue

    return Grafo(
        directas=directas,
        directas_herdadas=directas_herdadas,
        snapshots=snapshots,
        ligacoes=ligacoes,
        ligacoes_herdadas=ligacoes_herdadas,
    )


def fecho(importador: str, grafo: Grafo) -> Fecho:
    """Fecho transitivo das dependencias de um importador, por travessia.

    Duas travessias em largura, cada uma com o seu conjunto de visitados:

    1. **Entre importadores**, pelas ligacoes `link:`. Do alvo seguem-se todos
       os grupos; de um pacote do workspace alcancado por `link:` seguem-se so
       os `GRUPOS_HERDADOS` (ver o cabecalho do modulo).
    2. **Entre pacotes de terceiros**, pelos `snapshots:`.

    Visitado e visitado nas duas: o grafo tem ciclos — o npm permite
    dependencias mutuas, e dois pacotes do workspace podem declarar-se um ao
    outro — e uma recursao ingenua nao terminaria.
    """
    relacoes: dict[str, set[str]] = {}
    alcancados: set[str] = set()
    sementes: set[str] = set()

    por_visitar_importadores: list[str] = [importador]
    visitados_importadores: set[str] = set()
    while por_visitar_importadores:
        actual = por_visitar_importadores.pop()
        if actual in visitados_importadores:
            continue
        visitados_importadores.add(actual)
        # O alvo conta com todos os grupos; quem se alcanca por `link:` so com
        # os herdados.
        if actual == importador:
            terceiros_aqui = grafo.directas.get(actual, set())
            ligacoes_aqui = grafo.ligacoes.get(actual, set())
        else:
            alcancados.add(actual)
            terceiros_aqui = grafo.directas_herdadas.get(actual, set())
            ligacoes_aqui = grafo.ligacoes_herdadas.get(actual, set())
        sementes |= terceiros_aqui
        relacoes[f"{PREFIXO_WORKSPACE}{actual}"] = {
            *terceiros_aqui,
            *(f"{PREFIXO_WORKSPACE}{destino}" for _, destino in ligacoes_aqui),
        }
        for _nome, destino in ligacoes_aqui:
            if destino in grafo.directas:
                por_visitar_importadores.append(destino)
            else:
                # Um `link:` para fora do workspace (uma pasta que o lockfile
                # nao declara como importador) nao se segue e nao se inventa.
                # Deixa-se o no na relacao para o documento dizer que existe.
                relacoes.setdefault(f"{PREFIXO_WORKSPACE}{destino}", set())

    por_visitar = list(sementes)
    visitados: set[str] = set()
    while por_visitar:
        actual = por_visitar.pop()
        if actual in visitados:
            continue
        visitados.add(actual)
        dependencias = grafo.snapshots.get(actual, set())
        relacoes[actual] = set(dependencias)
        por_visitar.extend(dependencias - visitados)

    return Fecho(
        terceiros=frozenset(visitados),
        importadores=frozenset(alcancados),
        relacoes={no: frozenset(destinos) for no, destinos in relacoes.items()},
    )
