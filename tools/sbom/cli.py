"""Interface de linha de comando do gate 11 (SCA, licencas e SBOM).

    python -m sbom generate [--root .] [--out ci/sbom]   gera os SBOM
    python -m sbom licenses [--root .]                    verifica as licencas
    python -m sbom check    [--root .]                    gera e verifica

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao.

O que este gate **nao** faz, por ser do KAM-067: digests de imagem, cosign,
quarentena obrigatoria e bloqueio de imagens. Aqui e SBOM e licencas **por PR**,
sobre o codigo-fonte e os lockfiles; la e por imagem e por release. A fronteira
esta em `docs/ci.md`.

A lista de bloqueio nao se reimplementa: o gate 11 chama `lint_arch deps`, que e
o que o KAM-001 ja entregou.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ci_waivers import ConfiguracaoIlegivel, WaiverInvalido
from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

#: As chaves de `ci/licenses.yaml` que este leitor conhece (KAM-134). Sairam
#: quatro que ninguem lia — `desconhecidas` (com `politica` e `razao`) e
#: `expressoes` (com `and`, `or`, `with`) —, e a razao de cada uma esta no
#: proprio ficheiro. A `version` fica, embora so se compare.
CHAVES_DE_LICENCAS = {
    "version", "permitidas", "negadas", "pendentes_de_decisao", "proprios",
}

from . import adr, collect, cyclonedx, spdx, vulns
from .collect import Componente, declaradas_e_nao_instaladas, recolher
from .spdx import DESCONHECIDA, NEGADA, PENDENTE, PERMITIDA, Politica


class ConfiguracaoInvalida(RuntimeError):
    """`ci/licenses.yaml` em falta ou malformado."""


def ler_politica(raiz: Path) -> tuple[Politica, frozenset[str]]:
    """Le `ci/licenses.yaml`. Devolve (politica, nomes dos pacotes proprios)."""
    caminho = raiz / "ci" / "licenses.yaml"
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"ficheiro em falta: {caminho}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao
    exigir_chaves(dados, CHAVES_DE_LICENCAS, str(caminho), erro=ConfiguracaoInvalida)
    if dados.get("version") != 1:
        raise ConfiguracaoInvalida(f"{caminho}: 'version' tem de ser 1")

    permitidas = dados.get("permitidas") or []
    if not permitidas:
        raise ConfiguracaoInvalida(
            f"{caminho}: 'permitidas' vazio — nada passaria, e isso parece "
            "configuracao em falta e nao politica"
        )

    negadas = []
    for indice, entrada in enumerate(dados.get("negadas") or [], start=1):
        exigir_chaves(
            entrada, {"prefixo", "razao"}, f"{caminho}: negada {indice}",
            erro=ConfiguracaoInvalida,
        )
        if not entrada.get("prefixo") or not entrada.get("razao"):
            raise ConfiguracaoInvalida(f"{caminho}: negada {indice} sem prefixo ou razao")
        negadas.append((str(entrada["prefixo"]), str(entrada["razao"])))

    pendentes = []
    excepcoes_de_nome: list[str] = []
    for indice, entrada in enumerate(dados.get("pendentes_de_decisao") or [], start=1):
        exigir_chaves(
            entrada, {"nome", "decisao", "razao", "excepcoes"},
            f"{caminho}: pendente {indice}", erro=ConfiguracaoInvalida,
        )
        faltam = [c for c in ("nome", "decisao", "razao") if not entrada.get(c)]
        if faltam:
            raise ConfiguracaoInvalida(
                f"{caminho}: pendente {indice} sem {', '.join(faltam)}"
            )
        pendentes.append(
            (str(entrada["nome"]).lower(), str(entrada["decisao"]), str(entrada["razao"]))
        )
        # As excepcoes a correspondencia parcial do nome. Cada uma exige `nome` e
        # `razao`: um nome sem razao e uma dispensa por omissao, e e isso que
        # este ficheiro existe para nao ter.
        for ordem, excepcao in enumerate(entrada.get("excepcoes") or [], start=1):
            exigir_chaves(
                excepcao, {"nome", "razao"},
                f"{caminho}: pendente {indice}, excepcao {ordem}",
                erro=ConfiguracaoInvalida,
            )
            em_falta = [c for c in ("nome", "razao") if not excepcao.get(c)]
            if em_falta:
                raise ConfiguracaoInvalida(
                    f"{caminho}: pendente {indice}, excepcao {ordem} sem "
                    f"{', '.join(em_falta)}"
                )
            excepcoes_de_nome.append(str(excepcao["nome"]).lower())

    politica = Politica(
        permitidas=frozenset(str(x) for x in permitidas),
        negadas=tuple(negadas),
        pendentes=tuple(pendentes),
        excepcoes_de_nome=frozenset(excepcoes_de_nome),
    )
    proprios = frozenset(str(x) for x in (dados.get("proprios") or []))
    return politica, proprios


def ler_waivers(raiz: Path) -> dict[str, dict]:
    """Waivers do gate 11, indexados pelo alvo. A validacao esta em `ci_waivers`."""
    from ci_waivers import ler as ler_todos

    return {
        str(w["alvo"]): w
        for w in ler_todos(raiz)
        if str(w.get("gate")) == "11"
    }


def _alvos(raiz: Path) -> list[tuple[str, str, Path]]:
    """Os alvos de SBOM: um por componente do monorepo, mais o conjunto."""
    alvos: list[tuple[str, str, Path]] = [("kamba", "0.1.0", raiz)]
    for familia in ("services", "packages", "libs"):
        base = raiz / familia
        if not base.is_dir():
            continue
        for pasta in sorted(p for p in base.iterdir() if p.is_dir()):
            versao = "0.1.0"
            manifesto = pasta / "package.json"
            if manifesto.is_file():
                try:
                    versao = json.loads(manifesto.read_text(encoding="utf-8")).get(
                        "version", versao
                    )
                except (OSError, json.JSONDecodeError):
                    pass
            alvos.append((f"{familia}/{pasta.name}", str(versao), pasta))
    return alvos


def _pins_python(raiz: Path, pastas: set[str]) -> set[str]:
    """Pacotes Python de um conjunto de pastas, lidos dos seus `requirements/*.in`.

    O `venv` e unico, como a loja do `pnpm`, pelo que a atribuicao por alvo vem
    dos pins e nao do que esta instalado.

    Recebe **pastas** e nao um alvo porque, desde o KAM-133, o alvo arrasta as
    pastas dos pacotes Python nossos que declara: se o `libs/py-core` ganhar um
    `requirements/`, os seus pins contam para o `services/agr`, que o declara.
    """
    ficheiros: list[Path] = []
    for pasta in sorted(pastas):
        if pasta == ".":
            ficheiros += list(raiz.glob("*/requirements/*.in"))
            ficheiros += list(raiz.glob("*/*/requirements/*.in"))
        else:
            ficheiros += list((raiz / pasta / "requirements").glob("*.in"))

    nomes: set[str] = set()
    for ficheiro in ficheiros:
        for linha in ficheiro.read_text(encoding="utf-8").splitlines():
            limpa = linha.split("#", 1)[0].strip()
            if "==" in limpa:
                nomes.add(limpa.split("==")[0].strip().lower().replace("_", "-"))
    return nomes


def _pasta_do_proprio(componente: Componente) -> str:
    """A pasta a que um pacote nosso pertence, a partir do seu manifesto.

    `services/gwy/package.json` -> `services/gwy`; o `package.json` da raiz ->
    `.`. E a chave que casa com os importadores do `pnpm-lock.yaml` e com as
    pastas do `ligacoes_python`, e substitui um `rsplit('/', 2)[-2]` que dava so
    o ultimo segmento (`gwy`) e por isso nao distinguia `services/gwy` de um
    `libs/gwy` que viesse a existir.
    """
    return componente.origem.rsplit("/", 1)[0] if "/" in componente.origem else "."


def pastas_do_alvo(raiz: Path, alvo: str) -> tuple[set[str], "pnpm_lock.Fecho | None"]:
    """As pastas de pacotes **nossos** que este alvo carrega, e o fecho npm.

    Devolve (pastas, fecho), onde `fecho` e um `pnpm_lock.Fecho` ou `None`
    quando nao ha lockfile. As pastas incluem a do proprio alvo, as dos pacotes
    do workspace alcancados por `link:` no lockfile, e as dos pacotes Python
    nossos declarados em `[project].dependencies` — as tres formas que a mesma
    ligacao toma neste repositorio.
    """
    from . import pnpm_lock

    importador = "." if alvo == "kamba" else alvo
    lockfile = raiz / "pnpm-lock.yaml"
    fecho = None
    pastas = {importador}

    if lockfile.is_file():
        grafo = pnpm_lock.ler(lockfile)
        if alvo == "kamba":
            # O alvo do conjunto carrega a uniao de todos os importadores.
            terceiros: set[str] = set()
            relacoes: dict[str, frozenset[str]] = {}
            for chave in grafo.directas:
                parcial = pnpm_lock.fecho(chave, grafo)
                terceiros |= parcial.terceiros
                for no, destinos in parcial.relacoes.items():
                    relacoes.setdefault(no, destinos)
                # O no do proprio importador vale sempre o que **ele** declara,
                # com todos os grupos. Sem esta linha, o `@kamba/core-ts` no
                # SBOM do conjunto ficava com a relacao que o `services/com`
                # dele herda — so `dependencies` —, e o conjunto perdia as
                # `devDependencies` do `core-ts` (`pg`, `@types/pg`), que estao
                # na lista de componentes. O grafo contradizia a lista.
                relacoes[f"{pnpm_lock.PREFIXO_WORKSPACE}{chave}"] = parcial.relacoes[
                    f"{pnpm_lock.PREFIXO_WORKSPACE}{chave}"
                ]
            fecho = pnpm_lock.Fecho(
                terceiros=frozenset(terceiros),
                importadores=frozenset(grafo.directas),
                relacoes=relacoes,
            )
        else:
            fecho = pnpm_lock.fecho(importador, grafo)
        pastas |= set(fecho.importadores)

    ligacoes = collect.ligacoes_python(raiz)
    if alvo == "kamba":
        pastas |= set(ligacoes)
    else:
        # Fecho transitivo do lado Python, com visitado-e-visitado: o
        # `kamba-core` nao declara nada hoje, mas a travessia nao pode depender
        # disso.
        por_visitar = [importador]
        vistos: set[str] = set()
        while por_visitar:
            actual = por_visitar.pop()
            if actual in vistos:
                continue
            vistos.add(actual)
            for destino in ligacoes.get(actual, set()):
                pastas.add(destino)
                por_visitar.append(destino)

    return pastas, fecho


def componentes_do_alvo(
    raiz: Path, alvo: str, todos: list[Componente]
) -> list[Componente]:
    """Os componentes que **este** alvo carrega.

    Nao e «o que esta instalado»: o `pnpm` tem uma loja unica e o `venv` e um so,
    pelo que isso daria o workspace inteiro em todos os ficheiros — nove SBOM
    iguais, o que satisfaz a letra de «SBOM por servico» e nao a pergunta a que
    um SBOM existe para responder.

    Para o lado npm, o fecho vem do `pnpm-lock.yaml`, por travessia a partir das
    dependencias directas do importador — **e atravessa as ligacoes `link:` do
    workspace** (KAM-133). Para o lado Python, vem dos pins do
    `requirements/*.in` do alvo e dos pacotes nossos que ele declara. Os pacotes
    do proprio monorepo entram pela sua pasta: o alvo e um deles.
    """
    pastas, fecho = pastas_do_alvo(raiz, alvo)
    fecho_npm: frozenset[str] = fecho.terceiros if fecho is not None else frozenset()
    pins = _pins_python(raiz, {"."} if alvo == "kamba" else pastas)

    seleccionados: list[Componente] = []
    for componente in todos:
        if componente.proprio:
            # Pacote do proprio monorepo: entra no seu alvo, nos alvos que o
            # declaram, e no do conjunto.
            if alvo == "kamba" or _pasta_do_proprio(componente) in pastas:
                seleccionados.append(componente)
            continue
        if componente.ecossistema == "npm":
            if f"{componente.nome}@{componente.versao}" in fecho_npm:
                seleccionados.append(componente)
        elif componente.nome.lower().replace("_", "-") in pins:
            seleccionados.append(componente)
    return seleccionados


def _relativo(destino: Path, raiz: Path) -> str:
    """O caminho relativo a raiz, ou o absoluto quando estiver fora dela."""
    try:
        return destino.relative_to(raiz).as_posix()
    except ValueError:
        return destino.as_posix()


def ids_spdx_curados(raiz: Path) -> frozenset[str]:
    """Os identificadores SPDX que `ci/licenses.yaml` nomeia.

    Serve para o `license.id` do CycloneDX, que esta restringido a enumeracao
    SPDX. Nao se vendoriza a enumeracao inteira (826 entradas) porque o gate
    tem de correr offline e porque uma cadeia fora deste conjunto vai em
    `license.name`, que e sempre valido: falha-se para o lado da validade.
    """
    politica, _proprios = ler_politica(raiz)
    ids = set(politica.permitidas)
    ids |= {decisao for _, decisao, _ in politica.pendentes if decisao}
    # As negadas sao **prefixos** (`AGPL`, `GPL-`), nao identificadores: nao
    # entram. Uma licenca negada nunca chega a um SBOM conforme de qualquer
    # forma, porque o gate falha antes.
    return frozenset(i for i in ids if i and " " not in i)


def waivers_do_gate_11(raiz: Path) -> set[str]:
    """Os `alvo` dispensados para o gate 11, lidos de `ci/waivers.yaml`.

    O criterio diz «falha com vulnerabilidade critica **sem excepcao
    registada**»: a excepcao e um waiver com `gate: 11` cujo `alvo` nomeia o
    `purl` do pacote ou o identificador da vulnerabilidade. Um waiver sem
    `alvo` nao dispensa nada — `alvo: tudo` nao existe, e o
    `ci/waivers.yaml` di-lo.
    """
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ci_waivers

    dispensados: set[str] = set()
    for waiver in ci_waivers.ler(raiz):
        if waiver["gate"] == "11" and waiver.get("alvo"):
            dispensados.add(str(waiver["alvo"]).strip())
    return dispensados


def verificar_vulnerabilidades(raiz: Path) -> tuple[list[str], dict]:
    """Metade do gate 11 que faltava. Devolve (achados que bloqueiam, resumo)."""
    componentes = recolher(raiz)
    dispensados = waivers_do_gate_11(raiz)
    encontradas = vulns.consultar(componentes)

    achados: list[str] = []
    informativas: list[vulns.Vulnerabilidade] = []
    dispensadas: list[vulns.Vulnerabilidade] = []
    for vulnerabilidade in encontradas:
        if (
            vulnerabilidade.purl in dispensados
            or vulnerabilidade.identificador in dispensados
        ):
            dispensadas.append(vulnerabilidade)
            continue
        if vulnerabilidade.bloqueia:
            achados.append(str(vulnerabilidade))
        else:
            informativas.append(vulnerabilidade)

    return achados, {
        "consultados": len([c for c in componentes if not c.proprio]),
        "encontradas": len(encontradas),
        "informativas": informativas,
        "dispensadas": dispensadas,
    }


def relacoes_do_alvo(
    raiz: Path, alvo: str, componentes: list[Componente]
) -> dict[str, set[str]]:
    """O grafo `bom-ref -> bom-refs` do SBOM de um alvo.

    Traduz os nos da travessia (`nome@versao` e `workspace:<pasta>`) para os
    `bom-ref` do documento, que sao os `purl`. So entram arestas cujas duas
    pontas sao componentes **deste** SBOM: um `dependsOn` que apontasse para
    fora deixava uma referencia pendurada, e um `bom-ref` que nao resolve e pior
    do que nao dizer nada. E o que acontece com o
    `@msgpackr-extract/...-darwin-arm64`, que esta no lockfile e nao esta
    instalado num runner Linux.
    """
    from . import pnpm_lock

    _pastas, fecho = pastas_do_alvo(raiz, alvo)

    ref_por_no: dict[str, str] = {}
    pastas_pypi: dict[str, str] = {}
    proprios_de_partida: set[str] = set()
    importador = "." if alvo == "kamba" else alvo
    for componente in componentes:
        if componente.proprio:
            pasta = _pasta_do_proprio(componente)
            if componente.ecossistema == collect.NPM:
                ref_por_no[f"{pnpm_lock.PREFIXO_WORKSPACE}{pasta}"] = componente.purl
            else:
                pastas_pypi[pasta] = componente.purl
            if alvo == "kamba" or pasta == importador:
                proprios_de_partida.add(componente.purl)
        elif componente.ecossistema == collect.NPM:
            ref_por_no[f"{componente.nome}@{componente.versao}"] = componente.purl

    arestas: dict[str, set[str]] = {}
    if fecho is not None:
        for no, destinos in fecho.relacoes.items():
            referencia = ref_por_no.get(no)
            if referencia is None:
                continue
            arestas.setdefault(referencia, set()).update(
                ref_por_no[destino] for destino in destinos if destino in ref_por_no
            )

    # O lado Python: a ligacao esta no `[project].dependencies`, nao no
    # lockfile, e **conta-se inteira**. A primeira versao registava so as
    # arestas entre pacotes nossos, e o `kamba-agr` saia com
    # `dependsOn: [kamba-core]` quando o `pyproject.toml` declara tres —
    # `starlette` e `uvicorn` estao no mesmo documento, com versao. Uma entrada
    # **parcial** e pior do que nenhuma: com entrada, quem le conclui que o
    # grafo e conhecido, e o grafo mente por omissao.
    #
    # Os terceiros `pypi` continuam sem entrada **propria** — nao ha grafo
    # resolvido deste lado, so pins —, e isso e outra coisa: e nao afirmar o
    # que nao se sabe. O que nao se pode e apagar uma aresta que o manifesto
    # declara.
    declaracoes = collect.declaracoes_python(raiz)
    por_nome_pypi: dict[str, str] = {
        collect.normalizar_pypi(c.nome): c.purl
        for c in componentes
        if c.ecossistema == collect.PYPI
    }
    for pasta, referencia in pastas_pypi.items():
        destinos = {
            por_nome_pypi[nome]
            for nome in declaracoes.get(pasta, frozenset())
            if nome in por_nome_pypi and por_nome_pypi[nome] != referencia
        }
        arestas.setdefault(referencia, set()).update(destinos)

    if proprios_de_partida:
        arestas[f"alvo:{alvo}"] = set(proprios_de_partida)
    return arestas


def gerar(raiz: Path, destino: Path) -> list[tuple[Path, int]]:
    """Gera um SBOM por alvo. Devolve (caminho, numero de componentes)."""
    todos = recolher(raiz)
    ids_spdx = ids_spdx_curados(raiz)
    escritos: list[tuple[Path, int]] = []
    for nome, versao, _ in _alvos(raiz):
        componentes = componentes_do_alvo(raiz, nome, todos)
        relacoes = relacoes_do_alvo(raiz, nome, componentes)
        documento = cyclonedx.construir(nome, versao, componentes, ids_spdx, relacoes)
        caminho = destino / f"{nome.replace('/', '__')}.cdx.json"
        cyclonedx.escrever(documento, caminho)
        escritos.append((caminho, len(componentes)))
    return escritos


def verificar_licencas(raiz: Path) -> tuple[list[str], dict]:
    """Classifica cada componente instalado. Devolve (achados, estatisticas)."""
    politica, proprios = ler_politica(raiz)
    waivers = ler_waivers(raiz)
    componentes = recolher(raiz)

    achados: list[str] = []
    contagem = {PERMITIDA: 0, NEGADA: 0, PENDENTE: 0, DESCONHECIDA: 0, "proprio": 0}

    for componente in componentes:
        if componente.nome in proprios:
            # Os nossos pacotes declaram `UNLICENSED` (convencao npm, nao SPDX).
            # Resolve-se por identidade e nao pela allowlist: acrescentar
            # `UNLICENSED` as permitidas deixaria passar qualquer dependencia de
            # terceiros que a declarasse.
            contagem["proprio"] += 1
            continue

        veredicto, razao = spdx.classificar_pacote(
            componente.nome, componente.licenca, politica
        )
        contagem[veredicto] += 1
        if veredicto == PERMITIDA:
            continue

        if componente.purl in waivers or componente.referencia in waivers:
            waiver = waivers.get(componente.purl) or waivers[componente.referencia]
            # KAM-067, criterio 6: uma licenca **proibida** (AGPL, BUSL, Elastic,
            # SSPL, FSL, SUL...) so entra com «excepcao registada em ADR». O
            # esquema dos waivers tambem aceita `aprovacao:<quem>@<data>`, que
            # serve para os outros gates e para as licencas por determinar — e
            # que aqui deixava uma BUSL entrar com a assinatura de uma pessoa.
            #
            # E o ADR tem de **existir**. A primeira versao desta condicao era
            # `startswith("ADR-")`, e um ADR com o numero 999 passava: o criterio ficava
            # satisfeito por um identificador que ninguem escreveu.
            referencia = str(waiver["adr_ou_aprovacao"])
            if veredicto == NEGADA and not adr.existe(raiz, referencia):
                motivo = (
                    "nao cita um ADR"
                    if not referencia.startswith("ADR-")
                    else "cita um ADR que nao existe"
                )
                achados.append(
                    f"{componente.referencia}: licenca proibida "
                    f"({componente.licenca}) com waiver que {motivo} "
                    f"({referencia}).\n"
                    f"    {razao}\n"
                    "    Uma licenca proibida so entra com excepcao registada em "
                    f"ADR: um `ADR-NNN` de {adr.ARQUITECTURA} §8 ou um `ADR-LNNN` "
                    f"de {adr.LOCAIS}/."
                )
                continue
            contagem[veredicto] -= 1
            contagem[PERMITIDA] += 1
            print(
                f"  waiver  {componente.referencia}: {veredicto} dispensado por "
                f"{waiver['adr_ou_aprovacao']} ate {waiver['expira_em']}"
            )
            continue

        prefixo = {
            NEGADA: "licenca proibida",
            PENDENTE: "licenca pendente de decisao",
            DESCONHECIDA: "licenca nao determinada",
        }[veredicto]
        achados.append(
            f"{componente.referencia}: {prefixo} ({componente.licenca or 'sem campo'}).\n"
            f"    {razao}\n"
            f"    Lido de: {componente.origem}\n"
            f"    Para dispensar: ci/waivers.yaml com gate 11, alvo "
            f"{componente.purl}, ADR e prazo."
        )

    return achados, {"componentes": len(componentes), "contagem": contagem}


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="sbom", description="Gate 11: SCA, licencas e SBOM"
    )
    analisador.add_argument("--root", type=Path, default=None)
    analisador.add_argument("--out", type=Path, default=None, help="destino dos SBOM")
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("generate", help="gera os SBOM CycloneDX")
    sub.add_parser("licenses", help="verifica as licencas dos componentes instalados")
    sub.add_parser("vulns", help="varre vulnerabilidades contra a OSV (precisa de rede)")
    sub.add_parser("check", help="gera os SBOM, verifica licencas e vulnerabilidades")

    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()
    # Resolve-se contra a raiz: `--out ci/sbom` (o exemplo do proprio
    # docstring) rebentava com `ValueError: not in the subpath`, porque
    # `relative_to(raiz)` corria sobre um caminho relativo ao cwd.
    destino = argumentos.out or (raiz / "ci" / "sbom")
    if not destino.is_absolute():
        destino = (raiz / destino).resolve()

    try:
        # A guarda corre para **os tres** subcomandos, e nao so para os que
        # geram SBOM: o `licenses` nao tinha guarda nenhuma, e e o que o
        # `make ci-11` usa para decidir se o PR passa.
        #
        # E compara-se contra o que esta declarado, nao contra zero. A guarda
        # anterior era `if not recolher(raiz)`, e `recolher` inclui os 9
        # pacotes do proprio monorepo, que vem dos `package.json` versionados:
        # a lista nunca estava vazia, a guarda nunca disparava, e o gate dava
        # verde com zero terceiros examinados.
        faltam = declaradas_e_nao_instaladas(raiz)
        if faltam:
            print(
                f"sbom: {len(faltam)} dependencia(s) directa(s) declarada(s) e nao "
                "instalada(s). O gate 11 le os metadados do disco, nao da rede, "
                "pelo que verificar sem elas seria dar verde sem ter visto nada:",
                file=sys.stderr,
            )
            for falta in faltam[:20]:
                print(f"  - {falta}", file=sys.stderr)
            if len(faltam) > 20:
                print(f"  (e mais {len(faltam) - 20})", file=sys.stderr)
            print("    Corra `make bootstrap` primeiro.", file=sys.stderr)
            return 2

        if argumentos.comando in ("generate", "check"):
            escritos = gerar(raiz, destino)
            print(
                f"sbom: {len(escritos)} SBOM CycloneDX {cyclonedx.VERSAO_SPEC} "
                f"-> {_relativo(destino, raiz)}/"
            )
            for caminho, quantos in escritos:
                print(f"    {quantos:>3} componentes  {caminho.name}")

        if argumentos.comando in ("licenses", "check"):
            achados, estatisticas = verificar_licencas(raiz)
            contagem = estatisticas["contagem"]
            if achados:
                print(
                    f"sbom: {len(achados)} problema(s) de licenca em "
                    f"{estatisticas['componentes']} componentes",
                    file=sys.stderr,
                )
                for achado in achados:
                    print(f"  - {achado}", file=sys.stderr)
                return 1
            print(
                f"sbom: licencas conformes — {estatisticas['componentes']} componentes "
                f"({contagem[PERMITIDA]} permitidas, {contagem['proprio']} nossos)"
            )

        if argumentos.comando in ("vulns", "check"):
            if vulns.sem_rede():
                # Nao e um `skip` silencioso: diz-se, e o `docs/ci.md` registra
                # que um PR validado assim nao conta. O CI nunca define a
                # variavel.
                print(
                    "sbom: KAMBA_SEM_REDE=1 — varrimento de vulnerabilidades "
                    "SALTADO. Esta execucao nao satisfaz o gate 11.",
                    file=sys.stderr,
                )
            else:
                try:
                    achados, resumo = verificar_vulnerabilidades(raiz)
                except vulns.RedeIndisponivel as erro:
                    # Fail-closed inclui a rede. Um gate de seguranca que passa
                    # quando nao consegue verificar e um gate que mente.
                    print(
                        f"sbom: {erro}\n"
                        "    O gate 11 falha quando nao consegue consultar a OSV. "
                        "Para correr sem rede, `KAMBA_SEM_REDE=1` — e essa execucao "
                        "nao satisfaz o gate.",
                        file=sys.stderr,
                    )
                    return 2
                for vulnerabilidade in resumo["dispensadas"]:
                    print(
                        f"    dispensada por waiver: {vulnerabilidade.identificador} "
                        f"em {vulnerabilidade.purl}"
                    )
                for vulnerabilidade in resumo["informativas"]:
                    print(f"    aviso: {vulnerabilidade}")
                if achados:
                    print(
                        f"sbom: {len(achados)} vulnerabilidade(s) {vulns.SEVERIDADE_QUE_BLOQUEIA} "
                        "sem excepcao registada",
                        file=sys.stderr,
                    )
                    for achado in achados:
                        print(f"  - {achado}", file=sys.stderr)
                    print(
                        "    Para dispensar: entrada em ci/waivers.yaml com "
                        "`gate: 11` e `alvo` igual ao purl ou ao identificador.",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    f"sbom: sem vulnerabilidades {vulns.SEVERIDADE_QUE_BLOQUEIA} — "
                    f"{resumo['consultados']} componentes de terceiros consultados na OSV "
                    f"({resumo['encontradas']} aviso(s) de severidade inferior)"
                )
        return 0

    # O `ConfiguracaoIlegivel` entra aqui porque este modulo le o
    # `ci/waivers.yaml` pelo `ci_waivers.ler` (KAM-134). Nao e `ConfiguracaoInvalida`
    # nem `YamlSubsetError` — e subclasse de `WaiverInvalido(RuntimeError)` —,
    # pelo que sem o nomear escapava, o interpretador imprimia *traceback* e o
    # gate saia **1**: um `ci/waivers.yaml` malformado passava por achado de
    # licenca. E a mesma classe de defeito que o `ci_gate_reservado` tinha, e
    # que uma correccao num so leitor nao resolveu.
    # O `WaiverInvalido` tambem, e nao so a sua subclasse `ConfiguracaoIlegivel`
    # (KAM-135). O KAM-134 nomeou a subclasse e deixou a mae, e com o
    # `criado_em` obrigatorio isto passou do caso raro ao caso **normal**:
    # qualquer waiver escrito antes do KAM-135 cai aqui, pelo que o primeiro
    # contacto de alguem com a mudanca seria um traceback de Python no gate 11.
    # Para este modulo, um `ci/waivers.yaml` que nao valida e configuracao: 2.
    except (
        ConfiguracaoInvalida, ConfiguracaoIlegivel, WaiverInvalido,
        YamlSubsetError, OSError,
    ) as excepcao:
        print(f"sbom: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
