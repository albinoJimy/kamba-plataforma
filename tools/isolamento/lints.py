"""O *lint* do `SET LOCAL`: nenhum contexto de tenant sobrevive a transaccao.

Criterio 7 do KAM-066, segunda metade: «um *lint* falha o *build* se existir
`SET app.tenant_id` de **sessao** em vez de `SET LOCAL`». Nao existia
(procurado em `tools/`, `ci/`, `.github/` e `db/`); o que existia era a regra
escrita em `docs/tecnica/08` §3.3 e repetida nas *docstrings* dos dois
`tenant_guard`, mais um mutante que prova que a suite a mata
(`db/mutacoes.py`, «helper: set_config de sessao (false)»). Uma regra em prosa
nao e um portao.

## Porque e que isto e a parte subtil do ticket

Um `SET` de sessao **funciona** em desenvolvimento e falha em producao da pior
maneira: o contexto sobrevive a devolucao da ligacao ao *pool* e o pedido
seguinte — de outro tenant — herda-o. Nao da erro; da as linhas do tenant
errado, com a RLS ligada e a parecer que protege. E o caso que o criterio 7
mede com cem transaccoes intercaladas, e este *lint* e a metade que o apanha
**antes** de alguem escrever as transaccoes.

## Tres regras, e a terceira e a que morde onde ninguem olhava

1. **`SET app.tenant_id` ou `SET SESSION app.tenant_id`** — texto de SQL que
   define a variavel sem `LOCAL`. Achado directo.
2. **`set_config('app.tenant_id', …, false)`** — a forma parametrizavel do
   mesmo defeito, com o `is_local` escrito a `false`.
3. **`set_config('app.tenant_id', …, <marcador>)`** — o `is_local` vem **por
   parametro** (`%s`, `$2`), e entao o *lint* vai ver o que os chamadores
   passam. E assim que ele apanha
   `packages/core-ts/src/eventos/trabalhador_bullmq.ts`, que passa `false` a
   `SQL_DEFINIR_TENANT` de propriedade — com a razao escrita na *docstring*
   dele — e que nenhuma das duas primeiras regras via. Um chamador que o *lint*
   nao consiga decidir e **achado**, nao silencio.

## As excepcoes tem ficheiro, dono e razao

`ci/isolamento-set-sessao.yaml`, na forma dos outros leitores de `ci/*.yaml`.
Uma entrada e por `(ficheiro, sitio)`, nomeia o **credor** — o ticket que a
fecha — e leva a razao por extenso. Uma entrada morta (para um sitio que ja nao
passa `false`) falha: senao a lista cresce e ninguem a le.

**Isto nao e uma dispensa generica**, e a diferenca importa: a entrada diz
«este sitio passa `false` e eu sei porque», nao «este ficheiro esta fora do
*lint*». O sitio que mudar de linha continua coberto (a chave e o nome do
ficheiro e o da funcao, nao o numero da linha); o que **acrescentar** um segundo
`false` no mesmo ficheiro e achado novo.

## Le a fonte, e so o que corre

O SQL desta casa vive em constantes de modulo, e as *docstrings* falam dele:
`tenant_guard/__init__.py` escreve `set_config('app.tenant_id', <tenant>,
true)` em prosa, e `consumo.py` escreve `SET LOCAL app.tenant_id =
envelope.tenant_id` num diagrama. Varrer o ficheiro inteiro dava achados em
comentarios — e um *lint* com falsos positivos em prosa e um *lint* que se
desliga. Por isso:

* **Python:** so os literais de cadeia que **nao** sao *docstrings*, pelo `ast`.
* **TypeScript:** o ficheiro com os comentarios (`//` e `/* */`) retirados.
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

from kamba_yaml import exigir_chaves, load_file  # noqa: E402

#: A variavel do ADR-015. Uma so, e e por isso que este *lint* e estreito.
VARIAVEL = "app.tenant_id"

#: Regra 1: `SET app.tenant_id` / `SET SESSION app.tenant_id`. O `SET LOCAL`
#: nao casa, porque `LOCAL` nao esta entre as alternativas.
_SET_DE_SESSAO = re.compile(
    r"\bSET\s+(?:SESSION\s+)?" + VARIAVEL.replace(".", r"\.") + r"\b",
    re.IGNORECASE,
)

#: Regras 2 e 3: `set_config('app.tenant_id', <valor>, <is_local>)`.
_SET_CONFIG = re.compile(
    r"set_config\(\s*'" + VARIAVEL.replace(".", r"\.") + r"'\s*,"
    r"\s*(?P<valor>[^,]+?)\s*,\s*(?P<is_local>[^)]+?)\s*\)",
    re.IGNORECASE,
)

#: O que conta como «verdadeiro» escrito a letra.
_VERDADE = ("true", "'true'", '"true"')
_FALSIDADE = ("false", "'false'", '"false"')

#: Um marcador de parametro: `%s` (psycopg), `$N` (pg), `?`.
_MARCADOR = re.compile(r"^(?:%s|\$\d+|\?)$")

#: O que o *lint* varre. Codigo que corre contra a base, e so esse.
CORPUS = (
    "libs/*/src/**/*.py",
    "packages/*/src/**/*.ts",
    "services/*/src/**/*.py",
    "services/*/src/**/*.ts",
    # **Todo o `db/*.py`, e nao tres ficheiros escolhidos a mao.** A primeira
    # versao desta lista levava `rls.py`, `bootstrap.py` e as revisoes, e
    # dizia-se «codigo que corre contra a base, e so esse» — mas `db/` tem mais
    # codigo que corre contra a base do que isso, e a revisao adversarial
    # mediu-o: `db/auditoria.py` tem um `set_config('app.tenant_id', %s,
    # false)` **escrito a letra**, que e a regra 1 deste *lint*, e ficava fora
    # da varredura. O «0 achados» media quatro *globs* e nao a arvore.
    #
    # Uma lista a mao de ficheiros a **incluir** falha para o lado errado: o
    # ficheiro novo fica de fora em silencio. Varre-se a pasta, e o que nao
    # pertence sai pelo `FORA_DO_CORPUS`, que falha para o lado certo — a
    # entrada tem de ser escrita.
    "db/*.py",
    "db/migrations/versions/*.py",
    # O proprio *harness*: a `semente.py` escreve contra a base, e um `SET` de
    # sessao numa semente contaminava a ligacao que os casos reutilizam.
    "tools/isolamento/*.py",
)

#: **O que fica de fora, e porque.** Nao e uma lista de conveniencia: cada
#: entrada e codigo que *escreve sobre* o `set_config` em vez de o executar.
#:
#: `db/mutacoes.py` e o caso exemplar: ele contem, como **dado**, o texto
#: `…, %s, false)` — e a mutacao «helper: set_config de sessao (false)», que
#: existe para provar que a suite mata a versao de sessao. Varrer a lista de
#: mutacoes fazia este *lint* acusar a prova de que o defeito e apanhado.
FORA_DO_CORPUS = (
    "db/mutacoes.py",
)


class LintInvalido(RuntimeError):
    """`ci/isolamento-set-sessao.yaml` malformado."""


@dataclasses.dataclass(frozen=True)
class Excepcao:
    ficheiro: str
    sitio: str
    credor: str
    razao: str
    #: Quantos sitios esta entrada cobre. **Existe porque a chave sozinha era um
    #: alvara**, e a revisao adversarial mediu-o: com a chave a ser
    #: `(ficheiro, sitio)` e sem contagem, uma segunda chamada com
    #: `is_local = false` na **mesma** constante e no mesmo ficheiro passava em
    #: silencio — e os dois documentos que descrevem este *lint* prometiam o
    #: contrario («um segundo `set_config(..., false)` no mesmo ficheiro e
    #: achado novo»). Com a contagem declarada, acrescentar um sitio faz a
    #: entrada deixar de bater e o *gate* diz qual e o numero novo.
    ocorrencias: int = 1

    @property
    def chave(self) -> str:
        return f"{self.ficheiro}#{self.sitio}"


_TICKET = re.compile(r"^KAM-[0-9]{3}$")
RAZAO_MINIMA = 80

#: As chaves de topo que `ci/isolamento-set-sessao.yaml` aceita. Constante
#: pela razao escrita no `CHAVES` de `casos.py`: o gate 4 confronta cada
#: `ci/*.yaml` com o conjunto que o seu leitor declara.
CHAVES = frozenset({"version", "excepcoes"})


def ler_excepcoes(raiz: Path = RAIZ) -> dict[str, Excepcao]:
    caminho = raiz / "ci" / "isolamento-set-sessao.yaml"
    if not caminho.is_file():
        raise LintInvalido(f"ficheiro em falta: {caminho}")
    dados = load_file(caminho)
    exigir_chaves(dados, set(CHAVES), caminho.name, erro=LintInvalido)
    if dados.get("version") != 1:
        raise LintInvalido(f"{caminho.name}: 'version' tem de ser 1")
    entradas: dict[str, Excepcao] = {}
    for indice, entrada in enumerate(dados.get("excepcoes") or [], start=1):
        exigir_chaves(
            entrada,
            {"ficheiro", "sitio", "credor", "razao", "ocorrencias"},
            f"{caminho.name}: entrada {indice}",
            erro=LintInvalido,
        )
        quantas = entrada.get("ocorrencias", 1)
        if not isinstance(quantas, int) or quantas < 1:
            raise LintInvalido(
                f"{caminho.name}: entrada {indice}: `ocorrencias` tem de ser um "
                f"inteiro >= 1, nao {quantas!r}"
            )
        excepcao = Excepcao(
            ficheiro=str(entrada["ficheiro"]),
            sitio=str(entrada["sitio"]),
            credor=str(entrada["credor"]),
            razao=str(entrada["razao"]),
            ocorrencias=quantas,
        )
        if not _TICKET.match(excepcao.credor):
            raise LintInvalido(
                f"{caminho.name}: {excepcao.chave}: `credor` tem de ser "
                f"KAM-NNN, nao {excepcao.credor!r}"
            )
        if len(excepcao.razao) < RAZAO_MINIMA:
            raise LintInvalido(
                f"{caminho.name}: {excepcao.chave}: a razao tem "
                f"{len(excepcao.razao)} caracteres e precisa de {RAZAO_MINIMA}. "
                "Escreva porque e que o contexto pode sobreviver a transaccao "
                "neste sitio, e o que impede outra ligacao de o ver."
            )
        if excepcao.chave in entradas:
            raise LintInvalido(f"{caminho.name}: {excepcao.chave} repetido")
        entradas[excepcao.chave] = excepcao
    return entradas


# ------------------------------------------------------------------- corpus


#: O corpus lido, por raiz. A regra 3 vai ver os chamadores de cada constante,
#: e sem isto cada achado relia a arvore inteira — 58 s de suite medidos. O
#: cache vive por execucao do processo e e invalidado por `limpar_cache()`, que
#: os testes chamam entre arvores de ensaio.
_LIDO: dict[tuple[str, str], str] = {}


def limpar_cache() -> None:
    _LIDO.clear()


def _ler(raiz: Path, relativo: str, caminho: Path) -> str:
    chave = (str(raiz), relativo)
    if chave not in _LIDO:
        fonte = caminho.read_text(encoding="utf-8")
        _LIDO[chave] = (
            _sem_comentarios_ts(fonte) if relativo.endswith(".ts") else fonte
        )
    return _LIDO[chave]


def _ficheiros(raiz: Path) -> list[Path]:
    vistos: dict[str, Path] = {}
    for padrao in CORPUS:
        for caminho in raiz.glob(padrao):
            relativo = caminho.relative_to(raiz).as_posix()
            if any(parte in ("node_modules", "__pycache__", "dist") for parte in caminho.parts):
                continue
            if "/tests/" in relativo or "/tests_" in relativo:
                continue
            if caminho.name.startswith("test_") or caminho.name.endswith(".test.ts"):
                continue
            if relativo in FORA_DO_CORPUS:
                continue
            vistos[relativo] = caminho
    return [vistos[chave] for chave in sorted(vistos)]


def _sem_comentarios_ts(fonte: str) -> str:
    """Retira `/* … */` e `// …`, **preservando o numero de linhas**.

    Preservar as linhas nao e cosmetico: o achado leva `ficheiro:linha`, e um
    numero errado manda quem o le para o sitio errado.
    """
    sem_bloco = re.sub(
        r"/\*.*?\*/",
        lambda achado: "\n" * achado.group(0).count("\n"),
        fonte,
        flags=re.DOTALL,
    )
    return re.sub(r"//[^\n]*", "", sem_bloco)


def _funcao_que_contem(arvore: ast.Module, linha: int) -> str | None:
    """A funcao mais interior que contem `linha`, ou `None`.

    Serve o `sitio` de uma excepcao quando o SQL **nao** esta numa constante
    nomeada: `db/auditoria.py#main` diz onde, e `#literal` nao dizia nada — e
    com `#literal` a entrada cobria qualquer literal daquele ficheiro, que e o
    alvara que o achado 6 da revisao descreve.
    """
    candidatas = [
        (no.end_lineno - no.lineno, no.name)
        for no in ast.walk(arvore)
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef)
        and no.end_lineno is not None
        and no.lineno <= linha <= no.end_lineno
    ]
    return min(candidatas)[1] if candidatas else None


def _literais_python(arvore: ast.Module) -> list[tuple[int, str, str | None]]:
    """`(linha, texto, constante)` de cada literal de cadeia que nao e docstring.

    `constante` e o nome da constante de modulo a que o literal esta atribuido,
    quando ha um: e por ele que a regra 3 encontra os chamadores.
    """
    docstrings: set[int] = set()
    for no in ast.walk(arvore):
        if not isinstance(
            no, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            continue
        corpo = getattr(no, "body", [])
        if (
            corpo
            and isinstance(corpo[0], ast.Expr)
            and isinstance(corpo[0].value, ast.Constant)
            and isinstance(corpo[0].value.value, str)
        ):
            docstrings.add(id(corpo[0].value))

    atribuido: dict[int, str] = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Constant):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    atribuido[id(no.value)] = alvo.id

    literais: list[tuple[int, str, str | None]] = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Constant) or not isinstance(no.value, str):
            continue
        if id(no) in docstrings:
            continue
        literais.append((no.lineno, no.value, atribuido.get(id(no))))
    return literais


_CONSTANTE_TS = re.compile(
    r"(?:export\s+)?const\s+(?P<nome>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
    r"(?P<valor>`[^`]*`|\"[^\"]*\"|'[^']*')",
)


def _constante_que_contem(fonte: str, posicao: int) -> str | None:
    """O nome da constante cujo literal cobre `posicao`, se houver."""
    for achado in _CONSTANTE_TS.finditer(fonte):
        inicio, fim = achado.span("valor")
        if inicio <= posicao <= fim:
            return achado.group("nome")
    return None


# --------------------------------------------------- os chamadores (regra 3)


def _is_local_dos_chamadores(
    raiz: Path, constante: str
) -> tuple[set[str], list[str]]:
    """Os valores de `is_local` que os chamadores de `constante` passam.

    Devolve `(valores, sitios_indecisos)`. Procura-se o uso da constante
    seguido da lista ou da tupla de parametros, e le-se o **ultimo** argumento:
    e a posicao do `is_local` nos dois SQL desta casa.
    """
    usos = re.compile(
        re.escape(constante) + r"\s*,\s*(?:\[(?P<lista>[^\]]*)\]|\((?P<tupla>[^)]*)\))"
    )
    valores: set[str] = set()
    indecisos: list[str] = []
    for caminho in _ficheiros(raiz):
        relativo = caminho.relative_to(raiz).as_posix()
        fonte = _ler(raiz, relativo, caminho)
        if constante not in fonte:
            continue
        encontrou = False
        for achado in usos.finditer(fonte):
            encontrou = True
            argumentos = achado.group("lista") or achado.group("tupla") or ""
            partes = [parte.strip() for parte in argumentos.split(",") if parte.strip()]
            linha = fonte.count("\n", 0, achado.start()) + 1
            if not partes:
                indecisos.append(f"{relativo}:{linha}: lista de parametros vazia")
                continue
            valores.add(partes[-1].lower())
        if not encontrou and re.search(
            r"\b" + re.escape(constante) + r"\b", fonte
        ):
            # A constante aparece mas nao numa chamada que este *lint* reconheca:
            # uma re-exportacao (`index.ts`) ou um `import` nao e um uso. So e
            # indeciso se o ficheiro a passar a alguma coisa.
            if re.search(
                r"(?:query|execute|executar)\s*\(\s*" + re.escape(constante),
                fonte,
            ):
                indecisos.append(
                    f"{relativo}: passa {constante} a uma consulta numa forma "
                    "que este lint nao sabe ler"
                )
    return valores, indecisos


# ------------------------------------------------------------------ o lint


def verificar(raiz: Path = RAIZ, excepcoes: dict[str, Excepcao] | None = None) -> list[str]:
    """Os achados. Lista vazia quer dizer que todo o contexto e de transaccao."""
    excepcoes = ler_excepcoes(raiz) if excepcoes is None else excepcoes
    # Cada execucao le a arvore de novo: uma arvore de ensaio que muda entre
    # chamadas (como nos testes deste pacote) nao pode herdar o cache da
    # anterior, ou o canario que se acabou de escrever nao e visto.
    limpar_cache()
    achados: list[str] = []
    usadas: set[str] = set()
    #: Os **sitios distintos** que cada excepcao cobriu. Confronta-se com o
    #: `ocorrencias` declarado: e o que faz do «um segundo `false` no mesmo
    #: ficheiro e achado novo» uma verdade e nao uma promessa.
    #:
    #: Sitios e nao suspensoes, e a diferenca mediu-se: a mesma constante
    #: `SQL_DEFINIR_TENANT` existe em Python **e** em TypeScript, com o
    #: `is_local` por parametro nas duas, pelo que a regra 3 corre duas vezes e
    #: encontra o mesmo chamador nas duas — contar suspensoes dava dois para um
    #: sitio so, e a entrada correcta aparecia como desactualizada.
    vistas: dict[str, set[str]] = {}

    for caminho in _ficheiros(raiz):
        relativo = caminho.relative_to(raiz).as_posix()
        bruto = caminho.read_text(encoding="utf-8")

        if relativo.endswith(".py"):
            try:
                arvore = ast.parse(bruto, filename=relativo)
            except SyntaxError as erro:
                achados.append(f"{relativo}: nao compila: {erro}")
                continue
            fragmentos = [
                (linha, texto, constante)
                for linha, texto, constante in _literais_python(arvore)
            ]
        else:
            fonte = _sem_comentarios_ts(bruto)
            fragmentos = [(1, fonte, None)]

        for linha_base, texto, constante in fragmentos:
            for achado in _SET_DE_SESSAO.finditer(texto):
                linha = linha_base + texto.count("\n", 0, achado.start())
                achados.append(
                    f"{relativo}:{linha}: `{achado.group(0).strip()}` e um SET de "
                    "**sessao**.\n"
                    "    O contexto sobrevive a devolucao da ligacao ao pool e o "
                    "pedido seguinte — de outro tenant — herda-o (`docs/tecnica/08` "
                    "§3.3, ADR-015).\n"
                    "    Use `SET LOCAL`, ou `set_config('app.tenant_id', …, true)`."
                )
            for achado in _SET_CONFIG.finditer(texto):
                linha = linha_base + texto.count("\n", 0, achado.start())
                is_local = achado.group("is_local").strip().lower()
                if is_local in _VERDADE:
                    continue
                if is_local in _FALSIDADE:
                    nome = constante or (
                        _constante_que_contem(texto, achado.start())
                        if not relativo.endswith(".py")
                        else _funcao_que_contem(arvore, linha)
                        if relativo.endswith(".py")
                        else None
                    )
                    sitio = nome or "literal"
                    chave = f"{relativo}#{sitio}"
                    if chave in excepcoes:
                        vistas.setdefault(chave, set()).add(f"{relativo}:{linha}")
                        usadas.add(chave)
                        continue
                    achados.append(
                        f"{relativo}:{linha}: `set_config('{VARIAVEL}', …, false)` "
                        "e um SET de **sessao** escrito a letra.\n"
                        f"    Se e deliberado, declare `{relativo}#{sitio}` em "
                        "ci/isolamento-set-sessao.yaml com o credor e a razao."
                    )
                    continue
                if not _MARCADOR.match(is_local):
                    achados.append(
                        f"{relativo}:{linha}: o `is_local` de `set_config` e "
                        f"{is_local!r}, que este lint nao sabe decidir.\n"
                        "    Falha fechada: um `is_local` que o lint nao le e um "
                        "`is_local` que ele nao verifica. Escreva `true`, ou passe-o "
                        "por parametro de uma constante nomeada."
                    )
                    continue

                # Regra 3: vem por parametro. Veem-se os chamadores.
                # **O mesmo texto que deu a posicao.** Procurar a constante no
                # ficheiro bruto com uma posicao medida no texto sem
                # comentarios punha a janela no sitio errado, e a constante
                # `SQL_DEFINIR_TENANT` de `consultas_consumo.ts` aparecia como
                # «SQL nao esta numa constante nomeada».
                nome = constante or _constante_que_contem(texto, achado.start())
                if nome is None:
                    achados.append(
                        f"{relativo}:{linha}: o `is_local` de `set_config` vem por "
                        "parametro e o SQL nao esta numa constante nomeada.\n"
                        "    Sem nome, o lint nao consegue ir ver o que os "
                        "chamadores passam. Ponha o SQL numa constante."
                    )
                    continue
                valores, indecisos = _is_local_dos_chamadores(raiz, nome)
                for indeciso in indecisos:
                    achados.append(
                        f"{indeciso}\n    `{nome}` leva o `is_local` por "
                        "parametro, e este lint tem de poder ler o que cada "
                        "chamador passa."
                    )
                if not valores and not indecisos:
                    achados.append(
                        f"{relativo}:{linha}: `{nome}` leva o `is_local` por "
                        "parametro e o lint nao encontrou um unico chamador.\n"
                        "    SQL de contexto de tenant sem chamador e SQL morto, "
                        "ou um chamador escrito numa forma que o lint nao le."
                    )
                for valor in sorted(valores):
                    if valor in _VERDADE:
                        continue
                    chave_literal = f"{relativo}#{nome}"
                    sitios = _chamadores_com(raiz, nome, valor)
                    for sitio in sitios:
                        # A chave da excepcao e `(ficheiro, constante)` e **nao**
                        # leva a linha: uma entrada com `:175` morria no dia em
                        # que alguem acrescentasse um comentario acima, e uma
                        # excepcao que morre sozinha reabre a porta em silencio.
                        chave = f"{sitio.rsplit(':', 1)[0]}#{nome}"
                        if chave in excepcoes:
                            vistas.setdefault(chave, set()).add(sitio)
                            usadas.add(chave)
                            continue
                        achados.append(
                            f"{sitio}: passa `is_local = {valor}` a `{nome}`, que "
                            f"define `{VARIAVEL}`.\n"
                            "    Um `is_local` falso e um SET de **sessao**: o "
                            "contexto sobrevive a transaccao e a ligacao leva-o "
                            "para o proximo pedido (`docs/tecnica/08` §3.3).\n"
                            f"    Se e deliberado, declare `{chave}` em "
                            "ci/isolamento-set-sessao.yaml com o credor e a razao."
                        )
                    if not sitios:
                        achados.append(
                            f"{chave_literal}: algum chamador passa "
                            f"`is_local = {valor}` e o lint nao conseguiu dizer "
                            "qual. Falha fechada."
                        )

    for chave in sorted(set(excepcoes) - usadas):
        achados.append(
            f"{chave}: esta em ci/isolamento-set-sessao.yaml e ja nao passa um "
            "`is_local` falso — a excepcao esta morta, retire-a."
        )
    for chave in sorted(usadas):
        declaradas = excepcoes[chave].ocorrencias
        encontradas = len(vistas.get(chave, set()))
        if encontradas != declaradas:
            achados.append(
                f"{chave}: a excepcao declara {declaradas} sitio(s) e o lint "
                f"encontrou {encontradas}.\n"
                "    Uma excepcao sem contagem era um alvara para o ficheiro "
                "inteiro: um `is_local` falso novo entrava debaixo dela em "
                "silencio. Se o sitio novo e deliberado, suba o `ocorrencias` "
                "**e** escreva a razao dele; se nao e, corrija-o."
            )
    return achados


def _chamadores_com(raiz: Path, constante: str, valor: str) -> list[str]:
    """Os ficheiros que passam `valor` como ultimo argumento de `constante`."""
    usos = re.compile(
        re.escape(constante) + r"\s*,\s*(?:\[(?P<lista>[^\]]*)\]|\((?P<tupla>[^)]*)\))"
    )
    sitios: list[str] = []
    for caminho in _ficheiros(raiz):
        relativo = caminho.relative_to(raiz).as_posix()
        fonte = _ler(raiz, relativo, caminho)
        for achado in usos.finditer(fonte):
            argumentos = achado.group("lista") or achado.group("tupla") or ""
            partes = [parte.strip() for parte in argumentos.split(",") if parte.strip()]
            if partes and partes[-1].lower() == valor:
                linha = fonte.count("\n", 0, achado.start()) + 1
                sitios.append(f"{relativo}:{linha}")
    return sitios
