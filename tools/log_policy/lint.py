"""Lint de arquitectura: nenhum servico escreve fora do *logger* (KAM-068).

O *logger* so garante «logs sem conteudo» se for o **unico** caminho ate ao
`stdout`. Um `console.log(pedido)` ou um `print(resposta)` ao lado dele anula a
*allowlist* inteira, e nenhum teste do *logger* o ve — nao passa por ele.

## Ambito

O codigo que corre dentro de um servico: tudo o que esta em `services/*`,
`packages/*` e `libs/*`, **menos** as pastas `tests`. Nao so `src/`: um
ficheiro ao lado dele corre no mesmo processo. Ficam de fora, de proposito,
`tools/` e `db/`: sao ferramentas de linha de comandos e orquestradores de
gates, cujo trabalho **e** escrever no terminal, e que nunca tratam dados de
clientes.

A unica excepcao dentro do ambito e o proprio *logger* (`ISENTOS`), e esta no
codigo e nao num ficheiro de configuracao: uma segunda excepcao e uma decisao
de arquitectura, nao uma linha de YAML.

## Regras

| Regra | Linguagem | O que apanha |
|---|---|---|
| `console_directo` | TS/JS | qualquer uso de `console` |
| `stdout_directo` | TS/JS | os nomes `stdout` e `stderr`, venham de onde vierem, e `emitWarning` |
| `print_directo` | Python | `print`, `pprint` |
| `logging_directo` | Python | importar `logging`, `loguru` ou `structlog` |
| `stdout_directo` | Python | `.stdout`, `.stderr` e os seus `__…__`, em qualquer objecto |
| `traceback_directo` | Python | importar `traceback` (imprime a pilha **com a mensagem**) |
| `saida_com_texto` | Python | `sys.exit`/`SystemExit` com texto: o interpretador escreve-o no `stderr` |
| `registar_directo` | ambas | chamar `.registar(...)`, a porta sem tipos do *logger* |
| `ficheiro_ilegivel` | ambas | o que nao se consegue ler ou analisar, e um `/*` que nao fecha |

As regras de `stdout`, `emitWarning`, `traceback`, `SystemExit`, `registar` e o
ambito alargado vem da revisao adversarial (`docs/analises/ANALISE-11`, A2 e
A3), que mostrou cada uma das evasoes a passar.

## O que nao apanha

E um lint, nao uma jaula. Nao segue `globalThis["con" + "sole"]`, nem
`getattr(builtins, "pr" + "int")`, nem `os.write(1, …)`, nem um alias
(`const p = process`), nem um modulo de terceiros que escreva por conta
propria — o Hono, por exemplo, faz `console.error` no seu tratador de erro por
omissao, e e por isso que cada servico o substitui. Em TypeScript os
comentarios sao retirados por um leitor simples: sabe que uma barra precedida
de uma barra invertida esta dentro de uma expressao regular, e pouco mais. O que isto fecha e o
descuido — que e como estas linhas aparecem —, e o que fica aberto esta em
`docs/logs.md` §7.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import re
from pathlib import Path

CONSOLE = "console_directo"
STDOUT = "stdout_directo"
PRINT = "print_directo"
LOGGING = "logging_directo"
TRACEBACK = "traceback_directo"
SAIDA = "saida_com_texto"
REGISTAR = "registar_directo"
UVICORN = "uvicorn_com_registo_proprio"
ILEGIVEL = "ficheiro_ilegivel"

#: As regras que o canario tem de ver morder, por linguagem. Fixas aqui e nao
#: lidas das *fixtures*: um manifesto que se esvazia dava «0 negativas, tudo
#: verde» (`docs/analises/ANALISE-05`, B1).
REGRAS_OBRIGATORIAS = {
    "ts": (CONSOLE, STDOUT, LOGGING, REGISTAR, ILEGIVEL),
    "py": (PRINT, LOGGING, STDOUT, TRACEBACK, SAIDA, REGISTAR, UVICORN, ILEGIVEL),
}

RAIZES = ("services", "packages", "libs")
EXTENSOES_TS = (".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx")
EXTENSOES_PY = (".py",)
IGNORADOS = ("node_modules", "dist", "__pycache__", ".venv", "tests")

#: O *logger*, nas duas linguagens. E o unico codigo de servico que pode
#: escrever no `stdout` e importar `logging`.
ISENTOS = (
    "packages/core-ts/src/logger/",
    "libs/py-core/src/kamba_core/logger/",
)

MENSAGENS = {
    CONSOLE: "uso de `console`: escreve-se pelo logger (`@kamba/core-ts/logger`)",
    STDOUT: "escrita directa no stdout/stderr: escreve-se pelo logger",
    PRINT: "uso de `print`/`pprint`: escreve-se pelo logger (`kamba_core.logger`)",
    LOGGING: "importa uma biblioteca de registo (`logging`, `pino`, `hono/logger`, …): escreve-se pelo logger",
    TRACEBACK: "importa `traceback`: a pilha traz a mensagem; regista-se por `log.excepcao`",
    SAIDA: "`sys.exit`/`SystemExit` com texto: o interpretador escreve-o no stderr",
    REGISTAR: "chama `.registar(...)`: e a porta sem tipos do logger; usam-se `info`, `error`, `excepcao`",
    UVICORN: "`uvicorn.run` sem `log_config=None`: o uvicorn instala os seus manipuladores e escreve texto livre",
    ILEGIVEL: "nao se conseguiu analisar o ficheiro; o que nao se le nao passa",
}


class ConfiguracaoInvalida(RuntimeError):
    """A arvore nao tem a forma que o lint precisa para dizer alguma coisa."""


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    linha: int
    regra: str

    def __str__(self) -> str:
        return f"{self.ficheiro}:{self.linha}: {self.regra} — {MENSAGENS[self.regra]}"


# ----------------------------------------------------------------- TypeScript

# Sem excluir o que vem depois de um ponto: `globalThis.console` e o mesmo
# objecto. Uma propriedade alheia chamada `console` tambem bate, e e falhar
# para o lado seguro.
_CONSOLE = re.compile(r"(?<![A-Za-z0-9_$])console(?![A-Za-z0-9_$])")
# Os nomes, e nao `process.<nome>`: `import { stdout } from "node:process"`,
# `const { stderr } = process` e `p.stdout` sao o mesmo fluxo por outro caminho.
# O `stdout` de um processo-filho tambem bate; e falhar para o lado seguro.
_PROCESS_STD = re.compile(r"(?<![A-Za-z0-9_$])(?:stdout|stderr|emitWarning)(?![A-Za-z0-9_$])")
_REGISTAR = re.compile(r"\.\s*registar\s*\(")
# Bibliotecas de registo de Node, pelo nome com que se importam ou se pedem.
# `hono/logger` e o *middleware* que escreve cada pedido na consola.
_BIBLIOTECAS_TS = re.compile(
    r"""["'`](?:pino(?:-[a-z-]+)?|winston|bunyan|loglevel|consola|signale|morgan|debug|hono/logger)["'`]"""
)


class ComentarioPorFechar(ValueError):
    """Um `/*` sem `*/`: o resto do ficheiro nao foi lido."""

    def __init__(self, posicao: int, linha: int) -> None:
        super().__init__(linha)
        self.posicao = posicao
        self.linha = linha


def sem_comentarios(fonte: str) -> str:
    """A fonte TS/JS com os comentarios trocados por espacos.

    Mantem os saltos de linha (os numeros de linha continuam certos) e o
    conteudo das cadeias: um `console.log` dentro de uma cadeia **e** reportado.
    E falhar para o lado seguro — o leitor nao tem de saber se a cadeia vai ser
    avaliada.

    Uma barra precedida de `\\` nao abre comentario: `/\\/*$/` e uma expressao
    regular, e le-la como `/*` apagava o resto do ficheiro. Um `/*` que nao fecha
    levanta `ComentarioPorFechar` — o que vem a seguir nao foi lido.
    """
    saida: list[str] = []
    i = 0
    n = len(fonte)
    aspas: str | None = None
    while i < n:
        c = fonte[i]
        par = fonte[i : i + 2]
        if aspas is not None:
            saida.append(c)
            if c == "\\" and i + 1 < n:
                saida.append(fonte[i + 1])
                i += 2
                continue
            if c == aspas or (c == "\n" and aspas != "`"):
                aspas = None
            i += 1
            continue
        escapada = i > 0 and fonte[i - 1] == "\\"
        if par == "//" and not escapada:
            fim = fonte.find("\n", i)
            fim = n if fim == -1 else fim
            saida.append(" " * (fim - i))
            i = fim
            continue
        if par == "/*" and not escapada:
            fim = fonte.find("*/", i + 2)
            if fim == -1:
                raise ComentarioPorFechar(i, fonte.count("\n", 0, i) + 1)
            fim += 2
            saida.append("".join("\n" if x == "\n" else " " for x in fonte[i:fim]))
            i = fim
            continue
        if c in "\"'`":
            aspas = c
        saida.append(c)
        i += 1
    return "".join(saida)


def analisar_ts(fonte: str) -> list[tuple[int, str]]:
    achados: set[tuple[int, str]] = set()
    try:
        limpa = sem_comentarios(fonte)
    except ComentarioPorFechar as erro:
        achados.add((erro.linha, ILEGIVEL))
        limpa = sem_comentarios(fonte[: erro.posicao])
    for regra, expressao in (
        (CONSOLE, _CONSOLE),
        (STDOUT, _PROCESS_STD),
        (REGISTAR, _REGISTAR),
        (LOGGING, _BIBLIOTECAS_TS),
    ):
        for ocorrencia in expressao.finditer(limpa):
            achados.add((limpa.count("\n", 0, ocorrencia.start()) + 1, regra))
    return sorted(achados)


# --------------------------------------------------------------------- Python

_NOMES_DE_PRINT = ("print", "pprint")
_MODULOS_DE_PRINT = ("pprint",)
_MODULOS_DE_LOGGING = ("logging", "loguru", "structlog")
_FLUXOS = ("stdout", "stderr", "__stdout__", "__stderr__")
_SAIDAS = ("exit", "quit", "SystemExit", "_exit")


def _e_texto(no: ast.expr) -> bool:
    """O argumento de uma saida e, ou constroi, texto?"""
    if isinstance(no, ast.Constant):
        return isinstance(no.value, (str, bytes))
    if isinstance(no, (ast.JoinedStr, ast.BinOp)):
        return True
    if isinstance(no, ast.Call):
        if isinstance(no.func, ast.Name) and no.func.id in ("str", "repr", "format"):
            return True
        if isinstance(no.func, ast.Attribute) and no.func.attr in ("format", "join"):
            return True
    return False


def _uvicorn_com_registo_proprio(no: ast.Call) -> bool:
    """`uvicorn.run(...)` (ou `uvicorn.Config(...)`) sem `log_config=None`."""
    alvo = no.func
    if not (isinstance(alvo, ast.Attribute) and alvo.attr in ("run", "Config")):
        return False
    if not (isinstance(alvo.value, ast.Name) and alvo.value.id == "uvicorn"):
        return False
    for argumento in no.keywords:
        if argumento.arg == "log_config":
            return not (isinstance(argumento.value, ast.Constant) and argumento.value.value is None)
    return True


def _saida_com_texto(no: ast.Call) -> bool:
    alvo = no.func
    nome = alvo.id if isinstance(alvo, ast.Name) else getattr(alvo, "attr", None)
    return nome in _SAIDAS and any(_e_texto(a) for a in no.args)


def analisar_py(fonte: str) -> list[tuple[int, str]]:
    try:
        arvore = ast.parse(fonte)
    except (SyntaxError, ValueError):
        return [(1, ILEGIVEL)]
    achados: list[tuple[int, str]] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Name) and no.id in _NOMES_DE_PRINT:
            achados.append((no.lineno, PRINT))
        elif isinstance(no, ast.Import):
            for alias in no.names:
                raiz = alias.name.split(".")[0]
                if raiz in _MODULOS_DE_LOGGING:
                    achados.append((no.lineno, LOGGING))
                elif raiz in _MODULOS_DE_PRINT:
                    achados.append((no.lineno, PRINT))
                elif raiz == "traceback":
                    achados.append((no.lineno, TRACEBACK))
        elif isinstance(no, ast.ImportFrom):
            raiz = (no.module or "").split(".")[0]
            if no.level == 0 and raiz in _MODULOS_DE_LOGGING:
                achados.append((no.lineno, LOGGING))
            elif no.level == 0 and raiz in _MODULOS_DE_PRINT:
                achados.append((no.lineno, PRINT))
            elif no.level == 0 and raiz == "traceback":
                achados.append((no.lineno, TRACEBACK))
            elif no.level == 0 and raiz == "sys":
                if any(alias.name in _FLUXOS or alias.name == "*" for alias in no.names):
                    achados.append((no.lineno, STDOUT))
        elif isinstance(no, ast.Attribute) and no.attr in _FLUXOS:
            # Em qualquer objecto, e nao so em `sys`: `import sys as _sys` e o
            # mesmo modulo. O `stdout` de um `subprocess` tambem bate.
            achados.append((no.lineno, STDOUT))
        elif isinstance(no, ast.Call):
            if _saida_com_texto(no):
                achados.append((no.lineno, SAIDA))
            if isinstance(no.func, ast.Attribute) and no.func.attr == "registar":
                achados.append((no.lineno, REGISTAR))
            if _uvicorn_com_registo_proprio(no):
                achados.append((no.lineno, UVICORN))
    return sorted(set(achados))


# ------------------------------------------------------------------ a arvore


def analisar_ficheiro(caminho: Path) -> list[tuple[int, str]]:
    try:
        fonte = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [(1, ILEGIVEL)]
    if caminho.suffix in EXTENSOES_PY:
        return analisar_py(fonte)
    return analisar_ts(fonte)


def ficheiros_em_ambito(raiz: Path) -> list[Path]:
    """`<services|packages|libs>/**`, sem testes, dependencias nem saidas."""
    encontrados: list[Path] = []
    for topo in RAIZES:
        base = raiz / topo
        if not base.is_dir():
            continue
        # `os.walk` com poda, e nao `rglob`: descer ao `node_modules` para
        # depois o deitar fora custava minutos num clone com dependencias.
        for pasta, subpastas, ficheiros in os.walk(base):
            subpastas[:] = sorted(s for s in subpastas if s not in IGNORADOS)
            for nome in sorted(ficheiros):
                caminho = Path(pasta) / nome
                if caminho.suffix in EXTENSOES_TS + EXTENSOES_PY:
                    encontrados.append(caminho)
    return encontrados


def verificar(raiz: Path) -> tuple[list[Achado], dict[str, int]]:
    """Os achados na arvore, e quantos ficheiros de cada linguagem se leram."""
    for isento in ISENTOS:
        if not (raiz / isento).is_dir():
            raise ConfiguracaoInvalida(
                f"o logger nao esta em {isento}: a isencao do lint aponta para "
                "um directorio que nao existe"
            )
    achados: list[Achado] = []
    lidos = {"ts": 0, "py": 0, "isentos": 0}
    for caminho in ficheiros_em_ambito(raiz):
        relativo = caminho.relative_to(raiz).as_posix()
        if any(relativo.startswith(isento) for isento in ISENTOS):
            lidos["isentos"] += 1
            continue
        lidos["py" if caminho.suffix in EXTENSOES_PY else "ts"] += 1
        for linha, regra in analisar_ficheiro(caminho):
            achados.append(Achado(relativo, linha, regra))
    if lidos["ts"] == 0 or lidos["py"] == 0:
        raise ConfiguracaoInvalida(
            "o lint nao encontrou codigo de servico numa das linguagens "
            f"(TS/JS: {lidos['ts']}, Python: {lidos['py']}): passar sem ter "
            "lido nada nao e passar"
        )
    return achados, lidos


# ----------------------------------------------------------------- o canario


def canario(pasta: Path) -> tuple[list[str], dict[str, int]]:
    """As negativas tem de dar a regra do seu nome; as positivas, nada.

    Uma negativa chama-se `<regra>__<descricao>.<ext>`. Devolve as falhas (lista
    vazia = o lint morde) e as contagens.
    """
    falhas: list[str] = []
    vistas: dict[str, set[str]] = {"ts": set(), "py": set()}
    numeros = {"negativas": 0, "positivas": 0}

    negativas = sorted((pasta / "negativas").glob("*")) if (pasta / "negativas").is_dir() else []
    positivas = sorted((pasta / "positivas").glob("*")) if (pasta / "positivas").is_dir() else []

    for caminho in negativas:
        if caminho.suffix not in EXTENSOES_TS + EXTENSOES_PY:
            continue
        numeros["negativas"] += 1
        esperada = caminho.name.split("__", 1)[0]
        linguagem = "py" if caminho.suffix in EXTENSOES_PY else "ts"
        regras = {regra for _, regra in analisar_ficheiro(caminho)}
        if regras != {esperada}:
            falhas.append(
                f"negativas/{caminho.name}: esperava so `{esperada}`, "
                f"deu {sorted(regras) or 'nada'}"
            )
        else:
            vistas[linguagem].add(esperada)

    for caminho in positivas:
        if caminho.suffix not in EXTENSOES_TS + EXTENSOES_PY:
            continue
        numeros["positivas"] += 1
        regras = sorted({regra for _, regra in analisar_ficheiro(caminho)})
        if regras:
            falhas.append(f"positivas/{caminho.name}: devia passar e deu {regras}")

    for linguagem, obrigatorias in REGRAS_OBRIGATORIAS.items():
        for regra in obrigatorias:
            if regra not in vistas[linguagem]:
                falhas.append(
                    f"sem negativa que prove `{regra}` em {linguagem}: a regra "
                    "pode ter deixado de morder sem ninguem dar por isso"
                )
    if numeros["positivas"] < 2:
        falhas.append("menos de duas positivas: um lint que recusa tudo tambem passava")
    return falhas, numeros
