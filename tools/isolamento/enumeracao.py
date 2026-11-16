"""A enumeracao das superficies: rotas, tools do REG, *jobs* e consumidores EVT.

Criterio 2 do KAM-066: «a enumeracao automatica cobre 100% das rotas, tools do
REG, *jobs* BullMQ e consumidores EVT; um item enumerado sem caso registado
falha o CI». Este modulo e a primeira metade — descobrir o que existe. A
segunda esta em `casos.py`.

## Le a fonte, e nao o processo a correr

Pela razao do `tools/lint_arch` (ver a *docstring* dele): importar os servicos
para lhes perguntar as rotas exigia as dependencias instaladas e dava a
resposta **do codigo a correr**; ler a fonte da a resposta do codigo escrito,
que e o que um PR traz. So a biblioteca padrao, mais o `kamba_yaml` desta casa
para os ficheiros de `registry/`.

## Falha fechada, e isso e metade do valor

Uma superficie que a enumeracao **nao consegue decidir** — o caminho de uma
rota que vem de uma constante que este modulo nao resolve, o nome de uma fila
calculado em execucao — nao e ignorada: entra como item com o **sitio** por
identificador (`...#<expressao>`), e passa a exigir um caso como qualquer
outra. Uma enumeracao que calasse o que nao entende dava a cobertura de 100%
pela razao errada, que e precisamente o defeito que este ticket fecha.

O identificador de um item desses leva o ficheiro e a **expressao**, nunca o
numero de linha: um caso registado contra `...:242` morria no dia em que alguem
acrescentasse um comentario acima.

## As quatro superficies, e de onde cada uma se le

| Superficie | Fonte | Forma |
|---|---|---|
| rotas | `services/*/src/**/*.py` | `Route("<caminho>", h, methods=[...])` (Starlette) |
| rotas | `services/*/src/**/*.ts` | `app.<verbo>("<caminho>", ...)` (Hono) |
| tools do REG | `registry/*.yaml` | a lista `tools:` de cada vertical |
| *jobs* BullMQ | `**/*.ts` | `new Queue(<nome>)` e `new Worker(<nome>)` |
| consumidores EVT | `registry/*.yaml` | `subscriptions:` x vertical |

As tools leem-se do **REG** e nao do catalogo da TLS, porque e o REG que o
criterio nomeia e e a lista `tools:` que a camada trata como fechada (KAM-028,
passo 1 do `invoke`). Ha um caso de meta que confronta as duas listas: uma tool
no catalogo da TLS que nenhuma vertical declare, ou o contrario, e um achado.

Os consumidores EVT sao **derivados**, e isso e do KAM-038: «um consumidor por
cada `{tipo, versao}` de cada vertical», com `consumer = "agr_" + id`
(`eventos/subscricoes.py`). Logo uma subscricao nova num YAML de `registry/`
entra aqui sozinha — e exige um caso sozinha.

## O que as particoes de fila fazem aqui

Um consumidor EVT e entregue por dezasseis filas, `evt.<consumer>.p0` a
`...p15` (`eventos/particao.ts`, `nomeDaFila`). Enumerar as dezaseis dava
dezasseis itens com o mesmo isolamento a provar e um caso a repetir-se
dezasseis vezes: o `tenant_id` do *job* e o do envelope, e a particao e uma
funcao dele. Enumera-se **o consumidor**, e o caso do consumidor cobre as suas
filas; a particao tem verificacao propria no KAM-038. O `new Queue(nome)` que
as cria aparece como item **indeciso** (o nome e calculado), e o caso dele e
que diz isto por escrito — nao ha aqui uma excepcao calada.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ / "tools") not in sys.path:
    sys.path.insert(0, str(RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

from .texto import sem_comentarios_ts  # noqa: E402

#: Os quatro tipos de superficie que o criterio 2 nomeia.
TIPOS = ("rota", "tool", "job", "consumidor")

#: O prefixo do `consumer` de uma vertical (`eventos/subscricoes.py`, §3.33).
PREFIXO_DO_CONSUMIDOR = "agr_"

#: Os verbos do Hono que registam uma rota. `all` entra: registra todos.
VERBOS_HONO = ("get", "post", "put", "patch", "delete", "options", "all")

#: `app.<verbo>(<primeiro argumento>` — o resto da chamada nao interessa.
_ROTA_HONO = re.compile(
    r"\b(?P<app>[A-Za-z_$][\w$]*)\.(?P<verbo>"
    + "|".join(VERBOS_HONO)
    + r")\(\s*(?P<alvo>\"[^\"]*\"|'[^']*'|`[^`]*`|[A-Za-z_$][\w$.]*)",
)

#: Os nomes ligados a uma aplicacao Hono, dentro de um ficheiro: `const app =
#: new Hono()` e os parametros anotados `app: Hono`.
#:
#: **Sem isto a varredura mede outra coisa.** `Map.get`, `Headers.get` e
#: `segredos.get("meta_verify_token")` sao todos `x.get(...)`, e a primeira
#: versao deste modulo enumerou seis «rotas» que eram isso — uma delas com o
#: caminho `meta_verify_token`. Uma enumeracao que inventa superficies e tao
#: inutil como uma que as perde: obriga a escrever casos para o que nao existe,
#: e quem os escreve aprende a tratar a lista como ruido.
_APP_HONO = re.compile(
    r"(?:(?:const|let|var)\s+(?P<ligado>[A-Za-z_$][\w$]*)[^=\n]*=\s*new\s+Hono\b)"
    r"|(?:(?P<parametro>[A-Za-z_$][\w$]*)\s*:\s*Hono\b)",
)

#: Um primeiro argumento que **parece** um caminho de rota: comeca por `/`. Um
#: `.get("/algo")` sobre um receptor que nao se reconheceu como Hono entra como
#: **indeciso** em vez de ser ignorado — falha fechada pelo lado que importa.
_PARECE_CAMINHO = re.compile(r"^/")

#: `function <nome>(` ou `const <nome> = (`, para saber **que app** monta a rota.
#:
#: Sem isto a enumeracao perde rotas por colisao de identificador, e perdeu:
#: `/healthz` existe em cinco apps do `worker-canal` e em duas do `gwy` — a
#: publica e a de metricas, no mesmo ficheiro —, e com o `id` a ser
#: `rota:<servico>:<metodo>:<caminho>` as cinco colapsavam numa. Dezassete rotas
#: de TypeScript apareciam como doze, e um caso escrito contra a `/healthz` da
#: app publica dava por coberta a da porta interna. A app e parte da identidade
#: da rota, e o nome da funcao que a monta e o que esta arvore tem para a nomear.
_FUNCAO_TS = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<nome>[A-Za-z_$][\w$]*)"
    r"|^\s*(?:export\s+)?const\s+(?P<constante>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE,
)

#: `new Queue(<expressao>` ou `new Worker(<expressao>`, ate a virgula ou ao
#: fecho. A expressao inteira e nao o primeiro identificador: esta casa escreve
#: `new Worker(opcoes.fila ?? FILA_AGR, …)`, e capturar so `opcoes.fila` punha
#: duas filas com nome conhecido — a `agr-inbound` e a `wa-inbound` — a aparecer
#: como indecisas, e a `wa-inbound` a nao aparecer de todo (so tem `Worker`,
#: nao tem `Queue`).
_FILA_BULLMQ = re.compile(
    r"\bnew\s+(?P<classe>Queue|Worker)\(\s*(?P<alvo>[^,)\n]+)",
)

#: Um identificador em maiusculas dentro de uma expressao: o candidato a
#: constante de nome de fila num `a ?? FILA_X`.
_IDENTIFICADOR = re.compile(r"\b([A-Z][A-Z0-9_]*)\b")

#: `const NOME = "literal"` (com ou sem `export`), que e como esta casa escreve
#: um caminho de rota e um nome de fila.
_CONSTANTE_TS = re.compile(
    r"^\s*(?:export\s+)?const\s+(?P<nome>[A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*"
    r"(?P<valor>\"[^\"]*\"|'[^']*'|`[^`]*`)\s*;?\s*$",
    re.MULTILINE,
)

#: O que nao se varre: testes, artefactos e dependencias.
_IGNORAR = ("node_modules", "__pycache__", "dist", ".venv")


class EnumeracaoInvalida(RuntimeError):
    """A arvore nao tem o que a enumeracao precisa de ler."""


@dataclasses.dataclass(frozen=True)
class Item:
    """Uma superficie enumerada. O `id` e o que um caso declara em `enumeravel`."""

    id: str
    tipo: str
    #: O componente: o nome do servico, ou `reg`/`evt` para o que vem do registo.
    camada: str
    #: `ficheiro:linha` — para quem le o relatorio, nunca para identificar.
    onde: str
    #: `True` quando o nome nao se resolveu estaticamente. O `id` leva o sitio.
    indeciso: bool = False

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS:
            raise EnumeracaoInvalida(f"tipo desconhecido: {self.tipo!r}")


def _sem_comentarios(fonte: str) -> str:
    """Retira `/* … */` e `// …` de TypeScript, preservando as linhas.

    **A implementacao esta em `texto.py` e nao aqui, e a razao esta medida la:**
    a versao por expressao regular era cega as cadeias de caracteres, e o
    `api.use("/internal/*", …)` que o KAM-178 acrescentou ao COM abriu um
    comentario falso que engoliu o ciclo logo abaixo — as **sete** rotas
    `POST /internal/...` ficaram invisiveis a esta funcao, nem como item nem
    como `indeciso`.
    """
    return sem_comentarios_ts(fonte)


#: `const <NOME> = [ "/a", "/b" ]` — uma **lista** de caminhos ao nivel do
#: modulo, para o padrao que o KAM-178 trouxe: as sete rotas internas do COM
#: registram-se num ciclo sobre a constante `ROTAS`, e nao uma a uma.
#:
#: Sem isto o ciclo dava **um** item indeciso em vez de sete itens com caminho,
#: e o criterio 2 passava a contar 1 superficie onde ha 7 — e uma oitava entrada
#: na lista nao mudava nada na enumeracao, que e exactamente o que este ticket
#: existe para impedir.
_LISTA_TS = re.compile(
    r"\bconst\s+(?P<nome>[A-Z][A-Z0-9_$]*)\s*(?::[^=\n]+)?=\s*\[(?P<corpo>[^\]]*)\]",
)

#: Um literal de cadeia, para ler os elementos de uma `_LISTA_TS`.
_LITERAL_TS = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`")

#: `for (const <variavel> of <LISTA>)`. So a forma `const`: um `let` pode ser
#: reatribuido dentro do ciclo e a resolucao deixava de valer.
_CICLO_TS = re.compile(
    r"\bfor\s*\(\s*const\s+(?P<variavel>[A-Za-z_$][\w$]*)\s+of\s+"
    r"(?P<lista>[A-Za-z_$][\w$.]*)\s*\)",
)

#: `const <nome> = <expressao>` ao nivel de uma funcao, para seguir um local uma
#: vez: `const fila = opcoes.fila ?? FILA_AGR`.
_LOCAL_TS = re.compile(
    r"\bconst\s+(?P<nome>[a-z][\w$]*)\s*=\s*(?P<valor>[^;\n]+)",
)


def _locais_ts(fonte: str) -> dict[str, str]:
    return {
        achado.group("nome"): achado.group("valor").strip()
        for achado in _LOCAL_TS.finditer(fonte)
    }


def _texto(literal: str) -> str:
    """O conteudo de um literal de cadeia de TypeScript (`"`, `'` ou crase)."""
    return literal[1:-1]


def _e_literal(alvo: str) -> bool:
    return len(alvo) >= 2 and alvo[0] in "\"'`" and alvo[-1] == alvo[0]


def _ficheiros(raiz: Path, padrao: str) -> list[Path]:
    return sorted(
        caminho
        for caminho in raiz.glob(padrao)
        if not any(parte in _IGNORAR for parte in caminho.parts)
        and "/tests/" not in caminho.as_posix()
        and not caminho.name.endswith((".test.ts", ".bd.test.ts", "_test.py"))
        and not caminho.name.startswith("test_")
    )


def _relativo(raiz: Path, caminho: Path) -> str:
    return caminho.relative_to(raiz).as_posix()


def _modulo_de(relativo: str) -> str:
    """`services/<nome>/src/a/b.ts` -> `a/b`. O que nomeia a **app** na chave.

    O nome da funcao nao chega: quatro processos do `worker-canal` montam a sua
    app numa funcao chamada `criarApp` (`publicador.ts`, `consumidor.ts`,
    `entrada.ts`, `agr_shim.ts`), e com a chave a ser
    `rota:<servico>:<funcao>:<metodo>:<caminho>` as quatro `/healthz`
    colapsavam numa — a mesma perda que o nome da funcao veio corrigir, uma
    volta depois. O modulo distingue-as, e muda so quando o ficheiro muda de
    sitio, que e quando o caso **deve** ser revisto.
    """
    partes = relativo.split("/")
    if len(partes) > 3 and partes[0] == "services" and partes[2] == "src":
        resto = "/".join(partes[3:])
    elif len(partes) > 3 and partes[0] in ("packages", "libs") and partes[2] == "src":
        resto = "/".join(partes[3:])
    else:
        resto = relativo
    for sufixo in (".ts", ".py", ".tsx"):
        if resto.endswith(sufixo):
            return resto[: -len(sufixo)]
    return resto


def _servico_de(relativo: str) -> str:
    """`services/<nome>/...` -> `<nome>`; fora de `services/`, o pacote."""
    partes = relativo.split("/")
    if partes[0] == "services" and len(partes) > 1:
        return partes[1]
    if partes[0] in ("packages", "libs") and len(partes) > 1:
        return partes[1]
    return partes[0]


# --------------------------------------------------------------- constantes TS


def _constantes_ts(raiz: Path) -> dict[str, set[str]]:
    """`NOME -> {valores}` das constantes de cadeia de todo o TypeScript lido.

    Um conjunto e nao um valor: duas definicoes do mesmo nome com valores
    diferentes tornam a resolucao **indecisa**, e um indeciso e um achado. Uma
    tabela que escolhesse a primeira dava um caminho de rota errado sem o dizer.
    """
    tabela: dict[str, set[str]] = {}
    for padrao in ("services/*/src/**/*.ts", "packages/*/src/**/*.ts"):
        for caminho in _ficheiros(raiz, padrao):
            fonte = caminho.read_text(encoding="utf-8")
            for achado in _CONSTANTE_TS.finditer(fonte):
                tabela.setdefault(achado.group("nome"), set()).add(
                    _texto(achado.group("valor"))
                )
    return tabela


def _listas_ts(raiz: Path) -> dict[str, set[tuple[str, ...]]]:
    """`NOME -> {tuplos de valores}` das listas de cadeias do TypeScript lido.

    Um conjunto de **tuplos**, pela razao de `_constantes_ts`: duas definicoes
    do mesmo nome com listas diferentes tornam a resolucao indecisa, e um
    indeciso e um achado. Uma tabela que escolhesse a primeira enumerava rotas
    de outro servico sem o dizer.

    So nomes em maiusculas (`_LISTA_TS`): uma lista de caminhos neste
    repositorio e uma constante de modulo, e deixar passar `const partes = [...]`
    de dentro de uma funcao trazia arrays que nao sao tabelas de rotas.
    """
    tabela: dict[str, set[tuple[str, ...]]] = {}
    for padrao in ("services/*/src/**/*.ts", "packages/*/src/**/*.ts"):
        for caminho in _ficheiros(raiz, padrao):
            fonte = _sem_comentarios(caminho.read_text(encoding="utf-8"))
            for achado in _LISTA_TS.finditer(fonte):
                valores = tuple(
                    _texto(literal.group(0))
                    for literal in _LITERAL_TS.finditer(achado.group("corpo"))
                )
                if valores:
                    tabela.setdefault(achado.group("nome"), set()).add(valores)
    return tabela


def _ciclos_ts(fonte: str) -> dict[str, str]:
    """`variavel -> LISTA` de cada `for (const x of LISTA)` do ficheiro."""
    return {
        achado.group("variavel"): achado.group("lista").rsplit(".", 1)[-1]
        for achado in _CICLO_TS.finditer(fonte)
    }


def _caminhos_do_ciclo(
    alvo: str,
    ciclos: dict[str, str],
    listas: dict[str, set[tuple[str, ...]]],
) -> tuple[str, ...] | None:
    """Os caminhos de `app.<verbo>(<variavel de ciclo>)`, ou `None` se indeciso.

    Uma so definicao da lista, todos os elementos com forma de caminho, e
    nenhum com interpolacao: qualquer outra coisa devolve `None` e o sitio fica
    **indeciso**, que e o lado seguro — um indeciso para o *gate* e um caminho
    inventado nao.
    """
    nome = ciclos.get(alvo)
    if nome is None:
        return None
    valores = listas.get(nome)
    if valores is None or len(valores) != 1:
        return None
    caminhos = next(iter(valores))
    if any("${" in caminho or not _PARECE_CAMINHO.match(caminho) for caminho in caminhos):
        return None
    return caminhos


def _resolver_ts(alvo: str, constantes: dict[str, set[str]]) -> str | None:
    """O valor de um argumento de rota ou de fila, ou `None` se indeciso."""
    if _e_literal(alvo):
        texto = _texto(alvo)
        # Uma crase com interpolacao nao e um literal.
        return None if "${" in texto else texto
    nome = alvo.rsplit(".", 1)[-1]
    valores = constantes.get(nome)
    if valores is None or len(valores) != 1:
        return None
    return next(iter(valores))


# ---------------------------------------------------------------------- rotas


def _apps_hono(fonte: str) -> set[str]:
    nomes: set[str] = set()
    for achado in _APP_HONO.finditer(fonte):
        nomes.add(achado.group("ligado") or achado.group("parametro"))
    return nomes


def _funcoes_ts(fonte: str) -> list[tuple[int, str]]:
    """`(posicao, nome)` de cada funcao de topo, por ordem de posicao."""
    return [
        (achado.start(), achado.group("nome") or achado.group("constante"))
        for achado in _FUNCAO_TS.finditer(fonte)
    ]


def _funcao_em(funcoes: list[tuple[int, str]], posicao: int) -> str:
    """A ultima funcao declarada antes de `posicao`, ou `modulo`."""
    nome = "modulo"
    for inicio, candidato in funcoes:
        if inicio > posicao:
            break
        nome = candidato
    return nome


def _rotas_ts(raiz: Path) -> list[Item]:
    constantes = _constantes_ts(raiz)
    listas = _listas_ts(raiz)
    itens: list[Item] = []
    for caminho in _ficheiros(raiz, "services/*/src/**/*.ts"):
        relativo = _relativo(raiz, caminho)
        servico = _servico_de(relativo)
        modulo = _modulo_de(relativo)
        # **Sem comentarios**, como em `jobs()`. A primeira versao varria a
        # fonte bruta, e a revisao adversarial mediu o resultado numa arvore
        # de ensaio: uma rota comentada (`// app.get("/morta", …)`) entrava
        # na enumeracao. O efeito e o inverso do que o ticket fecha e tem o
        # mesmo custo: o *gate* exige caso para uma rota que nao existe, ou
        # a «cobertura de 100%» passa a contar superficies fantasma.
        fonte = _sem_comentarios(caminho.read_text(encoding="utf-8"))
        apps = _apps_hono(fonte)
        funcoes = _funcoes_ts(fonte)
        ciclos = _ciclos_ts(fonte)
        for achado in _ROTA_HONO.finditer(fonte):
            linha = fonte.count("\n", 0, achado.start()) + 1
            onde_monta = _funcao_em(funcoes, achado.start())
            verbo = achado.group("verbo").upper()
            alvo = achado.group("alvo")
            caminho_resolvido = _resolver_ts(alvo, constantes)
            if achado.group("app") not in apps:
                # Receptor que nao e uma app Hono conhecida. Ignora-se, **excepto**
                # se o argumento parece um caminho de rota: nesse caso e uma rota
                # que este modulo nao sabe atribuir, e um indeciso e um achado.
                if caminho_resolvido is None or not _PARECE_CAMINHO.match(
                    caminho_resolvido
                ):
                    continue
                itens.append(
                    Item(
                        id=f"rota:{servico}:{modulo}:{onde_monta}:{verbo}:"
                        f"{relativo}#{achado.group('app')}:{caminho_resolvido}",
                        tipo="rota",
                        camada=servico,
                        onde=f"{relativo}:{linha}",
                        indeciso=True,
                    )
                )
                continue
            if caminho_resolvido is None:
                # **Um ciclo sobre uma lista de caminhos da um item por
                # caminho.** E o padrao que o KAM-178 trouxe (`for (const rota
                # of ROTAS) api.post(rota, …)`), e tratar o ciclo como um
                # indeciso so contava 1 superficie onde ha 7.
                do_ciclo = _caminhos_do_ciclo(alvo, ciclos, listas)
                if do_ciclo is not None:
                    for caminho_da_lista in do_ciclo:
                        itens.append(
                            Item(
                                id=f"rota:{servico}:{modulo}:{onde_monta}:"
                                f"{verbo}:{caminho_da_lista}",
                                tipo="rota",
                                camada=servico,
                                onde=f"{relativo}:{linha}",
                            )
                        )
                    continue
                itens.append(
                    Item(
                        id=f"rota:{servico}:{modulo}:{onde_monta}:{verbo}:{relativo}#{alvo}",
                        tipo="rota",
                        camada=servico,
                        onde=f"{relativo}:{linha}",
                        indeciso=True,
                    )
                )
                continue
            itens.append(
                Item(
                    id=f"rota:{servico}:{modulo}:{onde_monta}:{verbo}:{caminho_resolvido}",
                    tipo="rota",
                    camada=servico,
                    onde=f"{relativo}:{linha}",
                )
            )
    return itens


def _constantes_python(arvore: ast.Module) -> dict[str, str]:
    """`NOME = "literal"` ao nivel do modulo."""
    tabela: dict[str, str] = {}
    for no in arvore.body:
        alvos: list[ast.expr] = []
        if isinstance(no, ast.Assign):
            alvos = list(no.targets)
        elif isinstance(no, ast.AnnAssign):
            alvos = [no.target]
        else:
            continue
        valor = no.value
        if not isinstance(valor, ast.Constant) or not isinstance(valor.value, str):
            continue
        for alvo in alvos:
            if isinstance(alvo, ast.Name):
                tabela[alvo.id] = valor.value
    return tabela


def _metodos_de(chamada: ast.Call) -> list[str]:
    """Os `methods=[...]` da `Route`. Sem eles, o Starlette assume `GET`."""
    for palavra in chamada.keywords:
        if palavra.arg != "methods":
            continue
        if not isinstance(palavra.value, ast.List | ast.Tuple):
            return []
        metodos = [
            elemento.value.upper()
            for elemento in palavra.value.elts
            if isinstance(elemento, ast.Constant) and isinstance(elemento.value, str)
        ]
        return metodos
    return ["GET"]


def _funcoes_python(arvore: ast.Module) -> list[tuple[int, int, str]]:
    """`(primeira linha, ultima linha, nome)` de cada funcao, a qualquer nivel."""
    return [
        (no.lineno, no.end_lineno or no.lineno, no.name)
        for no in ast.walk(arvore)
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _funcao_python_em(funcoes: list[tuple[int, int, str]], linha: int) -> str:
    """A funcao mais interior que contem `linha`, ou `modulo`."""
    candidatas = [
        (fim - inicio, nome)
        for inicio, fim, nome in funcoes
        if inicio <= linha <= fim
    ]
    if not candidatas:
        return "modulo"
    return min(candidatas)[1]


def _rotas_python(raiz: Path) -> list[Item]:
    itens: list[Item] = []
    for caminho in _ficheiros(raiz, "services/*/src/**/*.py"):
        relativo = _relativo(raiz, caminho)
        servico = _servico_de(relativo)
        modulo = _modulo_de(relativo)
        try:
            arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=relativo)
        except SyntaxError as erro:
            raise EnumeracaoInvalida(f"{relativo}: nao compila: {erro}") from erro
        constantes = _constantes_python(arvore)
        funcoes = _funcoes_python(arvore)
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            nome = no.func.id if isinstance(no.func, ast.Name) else (
                no.func.attr if isinstance(no.func, ast.Attribute) else None
            )
            if nome != "Route" or not no.args:
                continue
            primeiro = no.args[0]
            if isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str):
                caminho_resolvido: str | None = primeiro.value
                expressao = primeiro.value
            elif isinstance(primeiro, ast.Name):
                caminho_resolvido = constantes.get(primeiro.id)
                expressao = primeiro.id
            else:
                caminho_resolvido = None
                expressao = ast.dump(primeiro)[:40]
            metodos = _metodos_de(no) or ["?"]
            onde_monta = _funcao_python_em(funcoes, no.lineno)
            for metodo in metodos:
                if caminho_resolvido is None:
                    itens.append(
                        Item(
                            id=f"rota:{servico}:{modulo}:{onde_monta}:{metodo}:"
                            f"{relativo}#{expressao}",
                            tipo="rota",
                            camada=servico,
                            onde=f"{relativo}:{no.lineno}",
                            indeciso=True,
                        )
                    )
                else:
                    itens.append(
                        Item(
                            id=f"rota:{servico}:{modulo}:{onde_monta}:{metodo}:"
                            f"{caminho_resolvido}",
                            tipo="rota",
                            camada=servico,
                            onde=f"{relativo}:{no.lineno}",
                        )
                    )
    return itens


#: A classe de pedido da biblioteca padrao. Quem a estende serve HTTP sem
#: `Route`, e por isso fica fora do `_rotas_python`.
_TRATADOR_STDLIB = "BaseHTTPRequestHandler"
_METODO_STDLIB = re.compile(r"^do_([A-Z]+)$")


def _rotas_python_stdlib(raiz: Path) -> list[Item]:
    """As rotas de um `BaseHTTPRequestHandler` da biblioteca padrao (KAM-194).

    NASCEU DE UMA ROTA QUE A ENUMERACAO NAO VIA. O processo do IDX
    (`libs/py-core/src/kamba_core/idx/processo.py`) serve `POST /internal/event`
    num `ThreadingHTTPServer`, e nao em Starlette: nao ha `Route(...)` para o
    `_rotas_python` encontrar, e o ficheiro vive em `libs/`, que ele nem le. Uma
    rota interna com credencial, que escreve no `idx.search_doc` de qualquer
    *tenant*, nascia sem caso e sem que nada ficasse vermelho.

    O predicado: uma classe que estende `BaseHTTPRequestHandler`; cada metodo
    `do_<VERBO>` dela; e, dentro dele, cada comparacao `self.path == X` ou
    `self.path != X`, com `X` literal ou constante de cadeia do modulo. A funcao
    que monta e a que contem a **classe** (a fabrica, `tratador`), e nao o
    `do_<VERBO>`. Uma `X` que nao se resolve da um item indeciso, como no resto
    desta enumeracao.
    """
    itens: list[Item] = []
    ficheiros = _ficheiros(raiz, "services/*/src/**/*.py") + _ficheiros(
        raiz, "libs/*/src/**/*.py"
    )
    for caminho in ficheiros:
        texto = caminho.read_text(encoding="utf-8")
        if _TRATADOR_STDLIB not in texto:
            continue
        relativo = _relativo(raiz, caminho)
        try:
            arvore = ast.parse(texto, filename=relativo)
        except SyntaxError as erro:
            raise EnumeracaoInvalida(f"{relativo}: nao compila: {erro}") from erro
        servico = _servico_de(relativo)
        modulo = _modulo_de(relativo)
        constantes = _constantes_python(arvore)
        funcoes = _funcoes_python(arvore)
        for classe in ast.walk(arvore):
            if not isinstance(classe, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                for base in classe.bases
            }
            if _TRATADOR_STDLIB not in bases:
                continue
            onde_monta = _funcao_python_em(funcoes, classe.lineno)
            for metodo_no in classe.body:
                if not isinstance(metodo_no, ast.FunctionDef):
                    continue
                verbo = _METODO_STDLIB.match(metodo_no.name)
                if verbo is None:
                    continue
                for no in ast.walk(metodo_no):
                    if not isinstance(no, ast.Compare) or len(no.comparators) != 1:
                        continue
                    if not isinstance(no.ops[0], ast.Eq | ast.NotEq):
                        continue
                    esquerda = no.left
                    if not (
                        isinstance(esquerda, ast.Attribute)
                        and esquerda.attr == "path"
                        and isinstance(esquerda.value, ast.Name)
                        and esquerda.value.id == "self"
                    ):
                        continue
                    direita = no.comparators[0]
                    if isinstance(direita, ast.Constant) and isinstance(direita.value, str):
                        resolvido: str | None = direita.value
                        expressao = direita.value
                    elif isinstance(direita, ast.Name):
                        resolvido = constantes.get(direita.id)
                        expressao = direita.id
                    else:
                        resolvido = None
                        expressao = ast.dump(direita)[:40]
                    caminho_da_rota = resolvido if resolvido is not None else (
                        f"{relativo}#{expressao}"
                    )
                    itens.append(
                        Item(
                            id=f"rota:{servico}:{modulo}:{onde_monta}:"
                            f"{verbo.group(1)}:{caminho_da_rota}",
                            tipo="rota",
                            camada=servico,
                            onde=f"{relativo}:{no.lineno}",
                            indeciso=resolvido is None,
                        )
                    )
    return itens


def rotas(raiz: Path = RAIZ) -> list[Item]:
    """Todas as rotas: TypeScript (Hono), Python (Starlette) e Python da
    biblioteca padrao (`BaseHTTPRequestHandler`, desde o KAM-194)."""
    return _rotas_ts(raiz) + _rotas_python(raiz) + _rotas_python_stdlib(raiz)


# ------------------------------------------------------- o que vem do registo


def _verticais(raiz: Path) -> list[tuple[str, str, dict]]:
    """`(id, ficheiro relativo, dados)` de cada `registry/*.yaml` de vertical.

    A primeira forma do `registry/` distingue-se pela chave de topo `id`
    (`registry/vendedor.yaml`); o `gates.yaml` e o `plans.yaml` nao a tem.
    """
    directorio = raiz / "registry"
    if not directorio.is_dir():
        raise EnumeracaoInvalida("registry/ nao existe: o REG e a fonte das tools")
    verticais: list[tuple[str, str, dict]] = []
    for caminho in sorted(directorio.glob("*.yaml")):
        dados = load_file(caminho)
        if not isinstance(dados, dict) or "id" not in dados:
            continue
        verticais.append((str(dados["id"]), _relativo(raiz, caminho), dados))
    if not verticais:
        raise EnumeracaoInvalida(
            "nenhum ficheiro de vertical em registry/: a enumeracao de tools e "
            "de consumidores ficaria vazia, e uma lista vazia passava a "
            "cobertura de 100% sem medir nada"
        )
    return verticais


def tools(raiz: Path = RAIZ) -> list[Item]:
    """As tools do REG: a uniao das listas `tools:` das verticais.

    Um item por **nome de tool**, nao por (vertical, tool): o X-02 prova que a
    tool nao devolve canario de outro tenant, e isso nao depende da vertical
    que a declara. A lista de cada vertical tem verificacao propria (a camada
    recusa uma tool fora dela, KAM-028 passo 1).
    """
    vistos: dict[str, Item] = {}
    for _, relativo, dados in _verticais(raiz):
        for nome in dados.get("tools") or []:
            vistos.setdefault(
                str(nome),
                Item(
                    id=f"tool:{nome}",
                    tipo="tool",
                    camada="reg",
                    onde=relativo,
                ),
            )
    return sorted(vistos.values(), key=lambda item: item.id)


def consumidores(raiz: Path = RAIZ) -> list[Item]:
    """Um consumidor por `{tipo, versao}` de cada vertical (KAM-038, criterio 1)."""
    itens: list[Item] = []
    for identificador, relativo, dados in _verticais(raiz):
        consumer = f"{PREFIXO_DO_CONSUMIDOR}{identificador}"
        for subscricao in dados.get("subscriptions") or []:
            if not isinstance(subscricao, dict):
                raise EnumeracaoInvalida(
                    f"{relativo}: uma subscricao que nao e um mapa: {subscricao!r}"
                )
            tipo = subscricao.get("tipo")
            versao = subscricao.get("versao")
            if tipo is None or versao is None:
                raise EnumeracaoInvalida(
                    f"{relativo}: subscricao sem `tipo` ou sem `versao`: "
                    f"{subscricao!r}"
                )
            itens.append(
                Item(
                    id=f"consumidor:{consumer}:{tipo}@{versao}",
                    tipo="consumidor",
                    camada="evt",
                    onde=relativo,
                )
            )
    return itens


# ----------------------------------------------------------------------- jobs


def jobs(raiz: Path = RAIZ) -> list[Item]:
    """As filas BullMQ: cada `new Queue` e cada `new Worker` do conjunto.

    Varre `services/` **e** `packages/`: as filas desta casa sao criadas na
    biblioteca (`packages/core-ts/src/chr/fila.ts`, `entrada/trabalhador.ts`,
    `eventos/filas_bullmq.ts`) e so usadas nos servicos. Uma varredura que se
    limitasse a `services/` nao via nenhuma.
    """
    constantes = _constantes_ts(raiz)
    vistos: dict[str, Item] = {}
    for padrao in ("services/*/src/**/*.ts", "packages/*/src/**/*.ts"):
        for caminho in _ficheiros(raiz, padrao):
            relativo = _relativo(raiz, caminho)
            # **Sem comentarios.** O `filas_bullmq.ts` explica, em prosa, porque
            # e que o cliente `ioredis` tem de ser passado ao `new Queue(...)` —
            # e essa frase entrava como uma fila com nome indeciso. Um
            # enumerador que inventa superficies ensina a ignorar a lista.
            fonte = _sem_comentarios(caminho.read_text(encoding="utf-8"))
            locais = _locais_ts(fonte)
            for achado in _FILA_BULLMQ.finditer(fonte):
                linha = fonte.count("\n", 0, achado.start()) + 1
                alvo = achado.group("alvo").strip()
                nome = _resolver_ts(alvo, constantes)
                if nome is None:
                    # `new Worker(fila, …)` com `const fila = opcoes.fila ??
                    # FILA_AGR` acima: segue-se o local uma vez e resolve-se a
                    # constante do lado direito, que e o nome da fila quando
                    # quem chama nao da outro. E assim que a `wa-inbound`
                    # aparece — ela so tem `Worker`, nunca `Queue`.
                    expressao = locais.get(alvo, alvo)
                    for candidato in _IDENTIFICADOR.findall(expressao):
                        nome = _resolver_ts(candidato, constantes)
                        if nome is not None:
                            break
                if nome is None:
                    chave = f"job:{relativo}#{alvo}"
                    indeciso = True
                else:
                    chave = f"job:{nome}"
                    indeciso = False
                vistos.setdefault(
                    chave,
                    Item(
                        id=chave,
                        tipo="job",
                        camada=_servico_de(relativo),
                        onde=f"{relativo}:{linha}",
                        indeciso=indeciso,
                    ),
                )
    return sorted(vistos.values(), key=lambda item: item.id)


# ------------------------------------------------------------------- a uniao


def enumerar(raiz: Path = RAIZ) -> list[Item]:
    """As quatro superficies, ordenadas por `id`. Nunca vazia.

    Uma enumeracao vazia faria a cobertura passar sem medir nada — o modo de
    falha que o criterio 2 existe para impedir —, pelo que e erro e nao
    resultado.
    """
    itens = rotas(raiz) + tools(raiz) + jobs(raiz) + consumidores(raiz)
    if not itens:
        raise EnumeracaoInvalida(
            "a enumeracao nao encontrou superficie nenhuma. Isto nao e uma "
            "arvore sem superficies: e a enumeracao a nao ler o que devia."
        )
    # O padrao da casa (`tools/canon_lint/superficies.py`, `lint_arch/medusa.py`):
    # **uma superficie com zero itens diz-se, nao passa por conforme**. Os quatro
    # tipos tem itens hoje; o dia em que um deixar de ter e, quase sempre, a
    # varredura a deixar de ler — nao o conjunto a deixar de ter rotas.
    vazios = [tipo for tipo, lista in por_tipo(itens).items() if not lista]
    if vazios:
        raise EnumeracaoInvalida(
            f"a enumeracao nao encontrou nenhum item de tipo {vazios}. Os quatro "
            "tipos tinham itens quando o KAM-066 fundiu; zero e, quase sempre, a "
            "varredura a deixar de ler a forma em que a superficie passou a estar "
            "escrita. Se a superficie foi mesmo retirada, retire o tipo de `TIPOS`."
        )
    # Um `id` repetido e sinal de que a chave nao distingue o que devia (duas
    # rotas com o mesmo metodo e caminho em servicos diferentes **nao** colidem,
    # porque o servico esta na chave). Fica com o primeiro sitio, e a repeticao
    # e reportada pela cobertura.
    #: Um `id` repetido **nao se cala**. A *docstring* desta funcao dizia que
    #: «a repeticao e reportada pela cobertura», e era falso: a `cobertura()`
    #: recebe a lista ja deduplicada e nunca a ve. Duas superficies distintas
    #: que colapsem na mesma chave contavam como um item, um caso cobria as
    #: duas, e uma delas nunca era atacada — com a cobertura a dizer 100%. A
    #: chave foi alargada duas vezes por esta classe de colapso (o nome da
    #: funcao, depois o modulo); o terceiro nivel nao tinha sentinela.
    #: Achado 17 da revisao adversarial.
    por_id: dict[str, Item] = {}
    repetidos: dict[str, list[str]] = {}
    for item in itens:
        if item.id in por_id:
            repetidos.setdefault(item.id, [por_id[item.id].onde]).append(
                item.onde
            )
            continue
        por_id[item.id] = item
    if repetidos:
        linhas = "; ".join(
            f"{chave} em {sitios}" for chave, sitios in sorted(repetidos.items())
        )
        raise EnumeracaoInvalida(
            f"duas ou mais superficies colapsaram na mesma chave: {linhas}. "
            "Uma delas nunca seria atacada, e a cobertura diria 100%. Alargue "
            "a chave em `enumeracao.py` para as distinguir."
        )
    return sorted(por_id.values(), key=lambda item: (item.tipo, item.id))


def por_tipo(itens: list[Item]) -> dict[str, list[Item]]:
    agrupado: dict[str, list[Item]] = {tipo: [] for tipo in TIPOS}
    for item in itens:
        agrupado[item.tipo].append(item)
    return agrupado
