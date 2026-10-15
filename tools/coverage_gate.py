"""Gate 4: cobertura de linhas contra os limiares de `ci/thresholds.yaml`.

## O que nao existia

O §4.1 do Engineering Standards nomeia os estratos — «>= 90% em codigo de
dinheiro, isolamento e validador; >= 75% no restante» — e **nao diz como
classificar** um ficheiro num deles, nem com que ferramenta se mede, nem em que
formato. Nenhum documento do conjunto o diz. O KAM-002 tem de inventar a
taxonomia, e a escolha esta em `ci/thresholds.yaml`: por *glob* de caminho,
avaliado na ordem escrita.

## Como se mede

Duas linguagens, dois medidores, um formato comum:

* **Node** — `node --test --experimental-test-coverage`, que emite um resumo em
  texto. Pede-se-lhe `--test-reporter=lcov`, e le-se LCOV.
* **Python** — `coverage.py`, com `coverage lcov`.

LCOV e o denominador comum, e e por isso que foi escolhido: e o unico formato que
as duas ferramentas emitem sem traducao nossa. Um formato proprio obrigaria a
escrever dois geradores e a confiar em ambos.

## A regua dos dois lados (KAM-132)

Os dois medidores nao mediam o mesmo universo, e era o defeito mais caro deste
gate. Do lado Python, `coverage run --source=.` mede **o que nao e importado**:
um modulo sem testes entra no denominador com 0%. Do lado Node, o V8 so reporta
os ficheiros que os testes **carregaram** — pelo que nenhuma quantidade de
TypeScript sem testes movia a percentagem, e um servico Node inteiro sem um
unico teste mantinha o gate verde por nao ser medido.

`--test-coverage-include` **nao** resolve isto, ao contrario do que a lacuna 10
de `docs/ci.md` supunha: e um **filtro** sobre o que o V8 reportou, nao uma
busca no disco. Esta medido no PR do KAM-132 e esta escrito no proprio Node
(`lib/internal/test_runner/coverage.js`): «This check filters out files that do
not match the include globs». Serve para o relatorio ficar igual ao ambito, e e
para isso que o `make coverage-node` o passa.

Quem fecha a assimetria e este modulo: `universo()` le do disco os ficheiros que
o `ci/thresholds.yaml` poe num estrato, e `main()` **injecta a 0%** os que
nenhum relatorio mediu. O denominador passa a crescer com codigo sem testes,
como no lado Python, e os ficheiros injectados sao sempre impressos pelo nome —
um numero que desce sem se saber por que ficheiro nao e medicao.

## O que este modulo nao faz

Nao corre os testes. Le os ficheiros LCOV que o `make ci-4` produziu e aplica os
limiares. A separacao e deliberada: assim o relatorio pode ser reexaminado sem
voltar a correr nada, e um limiar alterado nao obriga a repetir a suite.
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import os
import re
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

#: As extensoes que entram no universo lido do disco: **tudo o que o Node 24
#: executa**, e nao so `.ts`. A primeira versao deste ficheiro so contava `.ts`,
#: e a revisao adversarial mostrou a fuga por execucao: um
#: `packages/core-ts/src/fuga.mts` com 50 declaracoes e sem teste nenhum deixava
#: os tres numeros do estrato **iguais**, e `.mts`, `.cts` e `.tsx` sao
#: TypeScript tanto como `.ts`. O `module: nodenext` do `tsconfig.base.json`
#: corre-os sem configuracao nenhuma.
#:
#: Os `.py` **nao** entram por omissao, e a razao e a regua: sabe-se qual e o
#: `LF` que o Node daria a um ficheiro que nao mediu (`linhas_do_ficheiro`), e
#: injectar um `.py` exigia contar **instrucoes**, que e a regua do
#: `coverage.py`. Do lado Python nao e preciso: o `coverage run --source=<pasta>`
#: percorre o disco e mede o que nao e importado, pelo que o universo do Python
#: garante-se **por cablagem do alvo** — ha um `--source=` em
#: `make coverage-python` por cada pasta de `.py` do ambito. O que faltava era um
#: para `services/agr/src/`, e a falta nao tinha gate: e a lacuna 25 de
#: `docs/ci.md` §7, fechada pelo KAM-151, que poe
#: `tools/lint_arch/tests/test_makefile.py::TestCoberturaPythonMedeOAmbito` a
#: falhar quando uma pasta de `.py` do ambito nao tem `--source=` que a meca. E
#: para esse teste que o `universo()` aceita outras `extensoes`: a lista de quem
#: tem de ser medido sai do mesmo `ci/thresholds.yaml` que classifica o que foi
#: medido, e nao de uma segunda lista escrita no Makefile que pudesse divergir.
EXTENSOES_DO_UNIVERSO = (
    ".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx",
)

#: Pastas que o universo nao percorre **dentro** das raizes. Dependencias de
#: terceiros, saida de compilacao e bytecode nao sao codigo de execucao deste
#: repositorio; as pastas com ponto a cabeca sao ferramentas, nao fontes.
PASTAS_FORA_DO_UNIVERSO = frozenset({"__pycache__", "dist", "node_modules"})


class ConfiguracaoInvalida(RuntimeError):
    """`ci/thresholds.yaml` em falta ou malformado."""


@dataclasses.dataclass(frozen=True)
class Estrato:
    nome: str
    minimo: int
    razao: str
    padroes: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Limiares:
    estratos: tuple[Estrato, ...]
    excluidos: tuple[str, ...]

    def esta_excluido(self, caminho: str) -> bool:
        """Esta em `excluidos`?

        Separado de `classificar` de proposito: «excluido» e «sem estrato» sao
        estados diferentes. O primeiro e uma decisao escrita; o segundo e um
        ficheiro que escapou ao limiar sem ninguem decidir isso. Confundi-los
        fazia o `dist/` compilado contar como defeito de configuracao.
        """
        normalizado = caminho.replace("\\", "/")
        return any(fnmatch.fnmatch(normalizado, p) for p in self.excluidos)

    def classificar(self, caminho: str) -> Estrato | None:
        """O estrato de um ficheiro. `None` quando nao bate em nenhum.

        **O primeiro padrao que bater decide**, e e por isso que a ordem do
        ficheiro importa: os estratos mais exigentes vem primeiro, para que um
        ficheiro de dinheiro dentro de `services/*/src/**` nao caia no estrato
        dos 75% por o padrao generico aparecer antes.
        """
        normalizado = caminho.replace("\\", "/")
        for estrato in self.estratos:
            for padrao in estrato.padroes:
                if fnmatch.fnmatch(normalizado, padrao):
                    return estrato
        return None


def ler_limiares(raiz: Path) -> Limiares:
    caminho = raiz / "ci" / "thresholds.yaml"
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"ficheiro em falta: {caminho}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao
    if dados.get("version") != 1:
        raise ConfiguracaoInvalida(f"{caminho}: 'version' tem de ser 1")

    estratos = []
    for indice, bruto in enumerate(dados.get("estratos") or [], start=1):
        faltam = [c for c in ("nome", "minimo_linhas", "razao", "padroes") if not bruto.get(c)]
        if faltam:
            raise ConfiguracaoInvalida(
                f"{caminho}: estrato {indice} sem {', '.join(faltam)}"
            )
        minimo = int(bruto["minimo_linhas"])
        if not 0 <= minimo <= 100:
            raise ConfiguracaoInvalida(
                f"{caminho}: estrato {bruto['nome']} tem minimo {minimo}"
            )
        estratos.append(
            Estrato(
                nome=str(bruto["nome"]),
                minimo=minimo,
                razao=str(bruto["razao"]),
                padroes=tuple(str(p) for p in bruto["padroes"]),
            )
        )
    if not estratos:
        raise ConfiguracaoInvalida(f"{caminho}: nenhum estrato definido")

    return Limiares(
        estratos=tuple(estratos),
        excluidos=tuple(str(x) for x in (dados.get("excluidos") or [])),
    )


def raizes_do_universo(limiares: Limiares) -> tuple[str, ...]:
    """As pastas por onde o universo comeca a procurar, lidas dos `padroes`.

    De cada padrao tira-se o primeiro segmento, e fica se for um nome literal:
    `services/*/src/**` da `services`, `tools/**` da `tools`, e `*/identity/*`
    **nao da nada** — e procura-se dentro das raizes que os outros deram.

    **Sem isto o gate media o disco inteiro, e a revisao adversarial reproduziu
    o custo:** uma copia de `packages/core-ts/src/` dentro de `tmp/` — que o
    `.gitignore` ignora, e que o proprio ambiente de medicao deste ticket tinha
    — levava o estrato `critico` de 94% para **46%**, porque o `*` do `fnmatch`
    atravessa barras e `*/storage/*` apanha `tmp/.../src/storage/s3.ts`. O mesmo
    valia para `rascunho/storage/x.ts` e `docs/exemplos/identity/x.ts`. O numero
    do gate passava a depender de ficheiros por versionar em qualquer parte da
    arvore, contra o principio 1 do `docs/ci.md` §1: o mesmo *commit* dava
    numeros diferentes no CI e na maquina de quem trabalha.

    Nenhuma raiz literal e **erro de configuracao** e nao universo vazio: um
    ficheiro de limiares cujos padroes comecem todos por `*` nao diz por onde
    comecar, e medir zero ficheiros em silencio e o defeito que este gate
    existe para nao ter.
    """
    raizes: set[str] = set()
    for estrato in limiares.estratos:
        for padrao in estrato.padroes:
            primeiro = padrao.replace("\\", "/").lstrip("./").split("/", 1)[0]
            if primeiro and not any(c in primeiro for c in "*?["):
                raizes.add(primeiro)
    if not raizes:
        raise ConfiguracaoInvalida(
            "ci/thresholds.yaml: nenhum padrao de estrato comeca por um nome de "
            "pasta literal, pelo que nao ha por onde procurar o universo. Pelo "
            "menos um estrato precisa de um padrao como `services/*/src/**`."
        )
    return tuple(sorted(raizes))


def _percorrer(
    raiz: Path,
    limiares: Limiares,
    extensoes: tuple[str, ...] = EXTENSOES_DO_UNIVERSO,
):
    """Os ficheiros medíveis dentro das raizes, em caminho relativo a `raiz`."""
    for nome_da_raiz in raizes_do_universo(limiares):
        base = raiz / nome_da_raiz
        if not base.is_dir():
            continue
        for pasta, subpastas, ficheiros in os.walk(base):
            subpastas[:] = sorted(
                s
                for s in subpastas
                if s not in PASTAS_FORA_DO_UNIVERSO and not s.startswith(".")
            )
            for nome in sorted(ficheiros):
                if nome.endswith(extensoes):
                    yield (Path(pasta) / nome).relative_to(raiz).as_posix()


def universo(
    raiz: Path,
    limiares: Limiares,
    extensoes: tuple[str, ...] = EXTENSOES_DO_UNIVERSO,
) -> list[str]:
    """Os ficheiros do disco que `ci/thresholds.yaml` poe num estrato.

    **E a lista que o lado Node nao media** (ver o cabecalho deste modulo). Sai
    do mesmo ficheiro de limiares que classifica o que foi medido — os `padroes`
    dos estratos menos os `excluidos` —, e nao de uma segunda lista de inclusao
    que pudesse divergir dele. E a razao pela qual os `excluidos` passam a valer
    **duas** vezes: mantem um ficheiro fora da injeccao, como ja o mantinham
    fora da avaliacao.

    Um ficheiro que nenhum estrato classifica **nao** entra. A regra de «medido
    e nao classificado falha o gate» e sobre o que foi medido; inventar aqui uma
    medicao para o fazer falhar era o gate a fabricar o seu proprio achado. Um
    ficheiro fora de qualquer estrato e que nenhum teste carrega continua
    invisivel, e isso esta declarado em `docs/ci.md` §7.
    """
    return sorted(
        c
        for c in _percorrer(raiz, limiares, extensoes)
        if not limiares.esta_excluido(c) and limiares.classificar(c) is not None
    )


def excluidos_no_disco(raiz: Path, limiares: Limiares, pacote: str) -> list[str]:
    """Os ficheiros de `pacote` que os `excluidos` retiram da medicao.

    E o que o `make coverage-node` passa em `--test-coverage-exclude`: o
    relatorio do Node deixa de levar o que o `ci/thresholds.yaml` ja nao conta,
    e a lista sai do mesmo ficheiro de limiares, em caminhos exactos.

    **Passa-se a exclusao e nao a inclusao, e a razao esta medida.** A primeira
    versao deste ticket passava `--test-coverage-include` com o universo, e a
    *flag* de inclusao retira do relatorio tudo o que nao esteja na lista —
    incluindo um ficheiro que **nenhum estrato classifica**, que e precisamente
    o que tem de chegar ao `avaliar()` para falhar o gate. A revisao adversarial
    reproduziu-o: um `packages/core-ts/fora.ts` carregado por um teste falhava o
    gate sem a *flag* e passava com ela. A regra que impede um directorio novo
    de deixar de ter cobertura exigida em silencio tinha ficado inalcancavel do
    lado Node.
    """
    prefixo = pacote.replace("\\", "/").strip("/") + "/"
    return sorted(
        c
        for c in _percorrer(raiz, limiares)
        if c.startswith(prefixo) and limiares.esta_excluido(c)
    )


#: Os terminadores de linha do JavaScript (ECMA-262: LF, CR, LS e PS). **Nao**
#: sao os do `str.splitlines`, que divide tambem em `\x0b`, `\x0c` e `\x85`: um
#: ficheiro de cinco linhas com um *form feed* dentro de um literal dava 8 pelo
#: `splitlines` e `LF:5` pelo Node (medido pela revisao adversarial).
_TERMINADORES_DE_LINHA = re.compile("[\n\r\u2028\u2029]")


def linhas_do_ficheiro(caminho: Path) -> int:
    """O numero de linhas de um ficheiro — que e o `LF` que o Node emite.

    O `LF` do LCOV do Node **nao** e uma contagem de instrucoes: e o numero de
    linhas do ficheiro, comentarios e linhas vazias incluidos. Medido no PR do
    KAM-132 nos 26 registos de `packages/core-ts/src/` em medicao, onde o `LF`
    deu exactamente o numero de linhas de cada um — `src/storage/motor.ts`, que
    e so tipos e comentarios, sai `67/67` depois de ser carregado.

    E por isso que um ficheiro do ambito sem medicao nenhuma entra com este
    numero no denominador e zero no numerador: e o numero que o proprio Node lhe
    daria, e nao uma regua nossa. (A consequencia, que vale dizer em vez de
    descobrir: do lado Node um ficheiro muito comentado tem a cobertura
    inflacionada, porque as linhas de comentario contam como atingidas quando o
    ficheiro e carregado. Ver `docs/ci.md` §7.)
    """
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    if not texto:
        return 0
    # `\r\n` e **um** terminador e nao dois, e o ultimo terminador do ficheiro
    # nao abre uma linha nova: um ficheiro de duas linhas tem `LF:2`.
    texto = texto.replace("\r\n", "\n")
    if texto[-1] in "\n\r\u2028\u2029":
        texto = texto[:-1]
    return len(_TERMINADORES_DE_LINHA.split(texto))


def _normalizar(bruto: str, raiz: Path, base: str) -> str:
    """Caminho relativo a raiz, que e a lingua de `ci/thresholds.yaml`."""
    # So se resolve como absoluto quando **e** absoluto. `Path("cli.py").resolve()`
    # resolve contra o directorio actual, que no `make` e a raiz — e devolvia
    # `cli.py` como se fosse relativo a raiz, sem nunca chegar ao prefixo do
    # pacote. Era por isso que 36 ficheiros de `tools/` ficavam sem estrato.
    if Path(bruto).is_absolute():
        try:
            return Path(bruto).resolve().relative_to(raiz).as_posix()
        except (ValueError, OSError):
            pass
    limpo = bruto.lstrip("./")
    if base and not limpo.startswith(base):
        # Caminho relativo ao pacote: prefixa-se com o pacote do relatorio.
        candidato = f"{base}/{limpo}"
        if (raiz / candidato).exists():
            return candidato
    # `../../packages/core-ts/dist/index.js` e afins: tira-se o que sobe.
    partes = [p for p in limpo.split("/") if p != ".."]
    return "/".join(partes)


@dataclasses.dataclass
class Medicao:
    ficheiro: str
    linhas_encontradas: int = 0
    linhas_cobertas: int = 0

    @property
    def percentagem(self) -> float:
        if self.linhas_encontradas == 0:
            return 100.0
        return 100.0 * self.linhas_cobertas / self.linhas_encontradas


def base_do_nome(caminho: Path) -> str:
    """O pacote a que um relatorio pertence, lido do nome do ficheiro.

    `ci/coverage/node-services-gwy.lcov` -> `services/gwy`.

    Existe porque o Node emite caminhos `SF:` **relativos ao pacote**
    (`src/app.ts`), e sem saber a que pacote pertencem nao ha como classifica-los
    contra `ci/thresholds.yaml` — todos cairiam como «nao classificados». O
    `make coverage-node` poe o caminho do pacote no nome do ficheiro
    precisamente para isto.
    """
    nome = caminho.stem
    for prefixo in ("node-", "python-"):
        if nome.startswith(prefixo):
            resto = nome[len(prefixo) :]
            break
    else:
        return ""
    for familia in ("services", "packages", "libs"):
        if resto.startswith(familia + "-"):
            return f"{familia}/{resto[len(familia) + 1:]}"
    # `python-tools.lcov` -> `tools`: o `coverage` corre de dentro de `tools/`,
    # pelo que os caminhos saem relativos a essa pasta.
    return resto


def ler_lcov(caminho: Path, raiz: Path) -> dict[str, Medicao]:
    """Le um ficheiro LCOV. So interessam `SF`, `LF` e `LH`.

    `SF` e o ficheiro, `LF` as linhas instrumentadas e `LH` as atingidas. Os
    registos de ramos e de funcoes ignoram-se: o limiar do §4.1 e de **linhas**.
    """
    medicoes: dict[str, Medicao] = {}
    actual: Medicao | None = None
    base = base_do_nome(caminho)
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        if linha.startswith("SF:"):
            bruto = linha[3:].strip().replace("\\", "/")
            relativo = _normalizar(bruto, raiz, base)
            actual = medicoes.setdefault(relativo, Medicao(relativo))
        elif actual is not None and linha.startswith("LF:"):
            actual.linhas_encontradas += int(linha[3:].strip() or 0)
        elif actual is not None and linha.startswith("LH:"):
            actual.linhas_cobertas += int(linha[3:].strip() or 0)
        elif linha.strip() == "end_of_record":
            actual = None
    return medicoes


def avaliar(
    medicoes: dict[str, Medicao], limiares: Limiares
) -> tuple[list[str], dict]:
    """Aplica os limiares. Devolve (achados, resumo por estrato)."""
    por_estrato: dict[str, dict] = {
        estrato.nome: {"encontradas": 0, "cobertas": 0, "ficheiros": 0, "minimo": estrato.minimo}
        for estrato in limiares.estratos
    }
    nao_classificados: list[str] = []
    achados: list[str] = []

    excluidos = 0
    for caminho, medicao in sorted(medicoes.items()):
        if limiares.esta_excluido(caminho):
            excluidos += 1
            continue
        estrato = limiares.classificar(caminho)
        if estrato is None:
            nao_classificados.append(caminho)
            continue
        agregado = por_estrato[estrato.nome]
        agregado["encontradas"] += medicao.linhas_encontradas
        agregado["cobertas"] += medicao.linhas_cobertas
        agregado["ficheiros"] += 1

    if nao_classificados:
        # **Falha**, nao nota. Um ficheiro medido que nenhum estrato classifica
        # escapa ao limiar em silencio, e um directorio novo passava a nao ter
        # cobertura exigida sem ninguem decidir isso. Foi assim que a primeira
        # versao deste gate passou com os **dois** estratos vazios e 52
        # ficheiros medidos.
        amostra = "\n".join(f"      {c}" for c in nao_classificados[:10])
        resto = (
            f"\n      (e mais {len(nao_classificados) - 10})"
            if len(nao_classificados) > 10
            else ""
        )
        achados.append(
            f"{len(nao_classificados)} ficheiro(s) medidos e nao classificados por "
            f"nenhum estrato de ci/thresholds.yaml:\n{amostra}{resto}\n"
            "    Acrescente-os a um estrato, ou a `excluidos` com a razao. Um "
            "ficheiro medido e nao classificado escapa ao limiar em silencio."
        )

    for estrato in limiares.estratos:
        agregado = por_estrato[estrato.nome]
        if agregado["ficheiros"] == 0:
            continue
        # Trunca-se, nao se arredonda: o ticket diz "descer 1 ponto abaixo do
        # limiar falha o gate", pelo que 89,9% nao e 90%.
        percentagem = int(100 * agregado["cobertas"] / max(agregado["encontradas"], 1))
        if percentagem < estrato.minimo:
            achados.append(
                f"estrato `{estrato.nome}`: {percentagem}% de cobertura de linhas, "
                f"minimo {estrato.minimo}% "
                f"({agregado['cobertas']}/{agregado['encontradas']} linhas em "
                f"{agregado['ficheiros']} ficheiros).\n"
                f"    {estrato.razao}"
            )

    return achados, {
        "por_estrato": por_estrato,
        "nao_classificados": nao_classificados,
        "excluidos": excluidos,
    }


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="coverage_gate", description="Gate 4: cobertura contra ci/thresholds.yaml"
    )
    analisador.add_argument("--root", type=Path, default=None)
    analisador.add_argument(
        "lcov",
        nargs="*",
        type=Path,
        help="ficheiros LCOV; por omissao, todos os de ci/coverage/",
    )
    analisador.add_argument(
        "--permitir-vazio",
        action="store_true",
        help=(
            "nao falha quando nao ha nada medido. So para o arranque: hoje o "
            "estrato critico esta vazio porque nao existe codigo de dinheiro."
        ),
    )
    analisador.add_argument(
        "--exclusoes-node",
        metavar="PACOTE",
        default=None,
        help=(
            "imprime, um por linha, os ficheiros de PACOTE que os `excluidos` "
            "retiram da medicao, relativos a ele, e sai. E o que o `make "
            "coverage-node` passa em --test-coverage-exclude: caminhos exactos, "
            "e nao globs, para nao haver traducao entre o fnmatch deste ficheiro "
            "e o glob do Node. Falha se PACOTE nao tiver ficheiro nenhum no "
            "ambito."
        ),
    )
    analisador.add_argument(
        "--sem-universo",
        action="store_true",
        help=(
            "nao injecta a 0% os ficheiros do ambito que nenhum relatorio mediu. "
            "So para inspeccionar um LCOV a mao: o gate corre sem isto."
        ),
    )
    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parent.parent).resolve()

    try:
        limiares = ler_limiares(raiz)
    except ConfiguracaoInvalida as excepcao:
        print(f"coverage_gate: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2

    if argumentos.exclusoes_node is not None:
        pacote = argumentos.exclusoes_node.replace("\\", "/").strip("/")
        if not (raiz / pacote).is_dir():
            print(f"coverage_gate: {pacote} nao e um directorio", file=sys.stderr)
            return 2
        prefixo = pacote + "/"
        if not any(c.startswith(prefixo) for c in universo(raiz, limiares)):
            # Um pacote de `PACOTES_NODE` sem um unico ficheiro no ambito e erro
            # de configuracao, nao «nada a medir»: ou falta um padrao em
            # ci/thresholds.yaml, ou o pacote nao devia estar na lista.
            print(
                f"coverage_gate: nenhum ficheiro do ambito em {pacote} — "
                "acrescente-o a um estrato de ci/thresholds.yaml ou retire-o de "
                "PACOTES_NODE",
                file=sys.stderr,
            )
            return 2
        relativos = [
            c[len(prefixo) :] for c in excluidos_no_disco(raiz, limiares, pacote)
        ]
        # O `make coverage-node` expande esta lista **sem aspas** para construir
        # os argumentos do `node --test`. Um caminho com espaco partia-se em dois
        # e o padrao deixava de bater, em silencio: recusa-se aqui, onde se ve.
        com_espaco = [c for c in relativos if c != "".join(c.split())]
        if com_espaco:
            print(
                "coverage_gate: caminho com espaco em branco, que o "
                f"`make coverage-node` nao sabe passar ao node: {com_espaco[0]}",
                file=sys.stderr,
            )
            return 2
        for caminho in relativos:
            print(caminho)
        return 0

    ficheiros = argumentos.lcov or sorted((raiz / "ci" / "coverage").glob("*.lcov"))
    if not ficheiros:
        mensagem = (
            "coverage_gate: nenhum ficheiro LCOV. Corra `make ci-4`, que mede antes "
            "de avaliar."
        )
        if argumentos.permitir_vazio:
            print(mensagem)
            return 0
        print(mensagem, file=sys.stderr)
        return 2

    medicoes: dict[str, Medicao] = {}
    for ficheiro in ficheiros:
        if not ficheiro.is_file():
            print(f"coverage_gate: {ficheiro} nao existe", file=sys.stderr)
            return 2
        for caminho, medicao in ler_lcov(ficheiro, raiz).items():
            existente = medicoes.setdefault(caminho, Medicao(caminho))
            existente.linhas_encontradas += medicao.linhas_encontradas
            existente.linhas_cobertas += medicao.linhas_cobertas

    # O passo que fecha a assimetria entre os dois lados (KAM-132): o que esta
    # no ambito e nenhum relatorio mediu entra a 0%, como no lado Python.
    injectados: list[str] = []
    if not argumentos.sem_universo:
        for caminho in universo(raiz, limiares):
            if caminho in medicoes:
                continue
            medicoes[caminho] = Medicao(
                caminho,
                linhas_encontradas=linhas_do_ficheiro(raiz / caminho),
                linhas_cobertas=0,
            )
            injectados.append(caminho)

    achados, resumo = avaliar(medicoes, limiares)

    print(f"coverage_gate: {len(medicoes)} ficheiros medidos em {len(ficheiros)} relatorio(s)")
    if injectados:
        # Pelo nome, sempre, e nao so a contagem: uma percentagem que desce sem
        # se saber por que ficheiro nao e uma medicao, e um ficheiro que entra
        # a 0% sem ninguem o ver e a mesma falta de transparencia que este
        # ticket fechou do outro lado.
        print(
            f"  {len(injectados)} do ambito de ci/thresholds.yaml sem medicao "
            "nenhuma, contados a 0% das suas linhas:"
        )
        for caminho in injectados:
            print(f"    . {caminho}")
    for nome, agregado in resumo["por_estrato"].items():
        if agregado["ficheiros"] == 0:
            print(
                f"  {nome:<10} vazio — nenhum ficheiro bate nos padroes deste estrato"
            )
            continue
        percentagem = int(100 * agregado["cobertas"] / max(agregado["encontradas"], 1))
        print(
            f"  {nome:<10} {percentagem:>3}%  (minimo {agregado['minimo']}%)  "
            f"{agregado['cobertas']}/{agregado['encontradas']} linhas, "
            f"{agregado['ficheiros']} ficheiros"
        )
    if resumo["excluidos"]:
        print(f"  {resumo['excluidos']} ficheiro(s) excluidos por ci/thresholds.yaml")
    if resumo["nao_classificados"]:
        print(
            f"  {len(resumo['nao_classificados'])} ficheiro(s) medidos e nao "
            "classificados por nenhum estrato (nem excluidos)"
        )
        for caminho in resumo["nao_classificados"][:5]:
            print(f"    . {caminho}")

    if achados:
        print(f"coverage_gate: {len(achados)} estrato(s) abaixo do limiar", file=sys.stderr)
        for achado in achados:
            print(f"  - {achado}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
