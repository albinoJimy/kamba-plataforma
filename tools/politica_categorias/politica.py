"""Ler, validar e compilar a politica de categorias (KAM-088).

A fonte e `policy/categorias/politica.yaml`; o esquema, `politica.esquema.json`
ao lado; o registo das versoes, `versoes.lock`; e o compilado, o modulo
TypeScript que o motor importa. Tres invariantes que nenhum esquema exprime e
que este modulo impoe:

1. **Facto juridico marcado.** Uma `fonte_lei` que nao seja nula leva
   `(a confirmar por parecer)` — a DoD do bloco, mecanizada. Sem isto, uma lei
   lida por nos passava a facto por estar num ficheiro que o CI le.
2. **Bloquear exige fonte.** Uma entrada `bloqueada` sem `fonte_meta` nem
   `fonte_lei` e uma proibicao que ninguem consegue defender perante o dono.
3. **Um termo, uma entrada.** O mesmo termo em duas entradas faz a decisao
   depender da ordem do ficheiro, que nao e regra nenhuma.

E a regra do SemVer: o conteudo de uma versao fica fixado no `versoes.lock`.
Mudar o conteudo sem subir a `versao` **reprova** — e a mesma disciplina do
`ci/llm-aliases.lock` (KAM-030), porque a politica e um artefacto
comportamental: muda o que o produto deixa vender.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import kamba_yaml

from . import esquema as validador

PASTA = Path("policy/categorias")
FONTE = PASTA / "politica.yaml"
ESQUEMA = PASTA / "politica.esquema.json"
LOCK = PASTA / "versoes.lock"
GERADO = Path("packages/core-ts/src/screening/politica.gerada.ts")

PARECER = "(a confirmar por parecer)"

SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

#: A sintaxe de expressao regular que os dois motores leem da mesma maneira
#: (achado F07 da revisao adversarial). O gate compila em Python e o motor
#: em JavaScript, e ha formas que um aceita e o outro le de outra maneira ou
#: recusa: `\A`, `\Z` e `\z` nao sao ancoras em JS; `{,n}` e literal em JS;
#: `(?i)` e grupos `(?...)` rebentam o JS ou mudam o sentido; o `$` do Python
#: aceita um `\n` final. Recusam-se as formas, em vez de se traduzirem.
SINTAXE_PROIBIDA = (
    (re.compile(r"\\[AZz]"), "\\A, \\Z ou \\z (nao sao ancoras em JavaScript)"),
    (re.compile(r"\{,"), "{,n} (em JavaScript e literal)"),
    (re.compile(r"\(\?"), "grupo (?...) (sinalizadores e afirmacoes leem-se de outra maneira)"),
    (re.compile(r"[$^]"), "ancoras ^ e $ (o $ do Python aceita um fim de linha)"),
    (re.compile(r"\)[*+]|\)\{\d*,"), "quantificador sobre grupo (risco de retrocesso exponencial)"),
)


class PoliticaInvalida(ValueError):
    """A fonte nao cumpre o esquema ou um dos invariantes."""


@dataclass(frozen=True)
class Politica:
    versao: str
    documento: dict
    sha256: str


def _versao(texto: str) -> tuple[int, int, int]:
    if SEMVER.fullmatch(texto) is None:
        raise PoliticaInvalida(f"versao {texto!r} nao e SemVer sem sufixos")
    maior, menor, revisao = (int(parte) for parte in texto.split("."))
    return maior, menor, revisao


def _chave_do_termo(termo: str) -> str:
    """Minusculas e sem acentos: `cervêja` e `cerveja` sao o mesmo termo (F15)."""
    decomposto = unicodedata.normalize("NFKD", termo.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def conteudo_canonico(documento: dict) -> bytes:
    """O que o *hash* sela: tudo menos a `versao`, em JSON ordenado."""
    sem_versao = {chave: valor for chave, valor in documento.items() if chave != "versao"}
    return json.dumps(
        sem_versao, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def ler(raiz: Path) -> Politica:
    try:
        documento = kamba_yaml.load_file(raiz / FONTE)
    except kamba_yaml.YamlSubsetError as erro:
        raise PoliticaInvalida(str(erro)) from erro
    try:
        esquema = json.loads((raiz / ESQUEMA).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise PoliticaInvalida(f"{ESQUEMA}: {erro}") from erro
    problemas = validador.erros(documento, esquema)
    if problemas:
        raise PoliticaInvalida("; ".join(problemas))

    vistos_ids: set[str] = set()
    donos: dict[str, str] = {}
    for entrada in documento["categorias"]:
        ident = entrada["id"]
        if ident in vistos_ids:
            raise PoliticaInvalida(f"id repetido: {ident}")
        vistos_ids.add(ident)
        lei = entrada["fonte_lei"]
        if lei is not None and PARECER not in lei:
            raise PoliticaInvalida(f"{ident}: fonte_lei sem {PARECER!r}")
        if entrada["decisao"] == "bloqueada" and entrada["fonte_meta"] is None and lei is None:
            raise PoliticaInvalida(f"{ident}: bloqueada sem fonte_meta nem fonte_lei")
        for termo in entrada["termos"]:
            chave = _chave_do_termo(termo)
            if chave in donos:
                raise PoliticaInvalida(
                    f"termo {termo!r} em {donos[chave]} e em {ident}: a decisao "
                    "dependeria da ordem do ficheiro"
                )
            donos[chave] = ident
        for padrao in entrada["padroes"]:
            for forma, porque in SINTAXE_PROIBIDA:
                if forma.search(padrao):
                    raise PoliticaInvalida(f"{ident}: padrao {padrao!r} usa {porque}")
            try:
                re.compile(padrao)
            except re.error as erro:
                raise PoliticaInvalida(f"{ident}: padrao {padrao!r} invalido: {erro}") from erro

    sha = hashlib.sha256(conteudo_canonico(documento)).hexdigest()
    return Politica(versao=documento["versao"], documento=documento, sha256=sha)


def ler_lock(raiz: Path) -> list[tuple[str, str]]:
    caminho = raiz / LOCK
    if not caminho.exists():
        return []
    linhas = []
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = linha.split()
        if (
            len(partes) != 2
            or SEMVER.fullmatch(partes[0]) is None
            or not re.fullmatch(r"[0-9a-f]{64}", partes[1])
        ):
            raise PoliticaInvalida(f"{LOCK}:{numero}: esperado «<versao> <sha256>»")
        linhas.append((partes[0], partes[1]))
    return linhas


def problemas_do_lock(politica: Politica, lock: list[tuple[str, str]]) -> list[str]:
    """O que o lock diz contra a versao corrente. Lista vazia = conforme."""
    saida = []
    versoes = [versao for versao, _ in lock]
    for anterior, seguinte in zip(versoes, versoes[1:]):
        if _versao(seguinte) <= _versao(anterior):
            saida.append(f"o lock nao sobe: {anterior} antes de {seguinte}")
    fixado = dict(lock).get(politica.versao)
    if fixado is None:
        saida.append(f"a versao {politica.versao} nao esta no {LOCK}: corre `gerar`")
    elif fixado != politica.sha256:
        saida.append(
            f"o conteudo da versao {politica.versao} mudou sem a versao subir "
            f"(lock {fixado[:12]}, fonte {politica.sha256[:12]})"
        )
    if versoes and politica.versao in versoes and versoes[-1] != politica.versao:
        saida.append(f"a versao {politica.versao} nao e a mais recente do lock ({versoes[-1]})")
    return saida


def lock_com(politica: Politica, lock: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """O lock com a versao corrente acrescentada, ou recusa."""
    fixado = dict(lock).get(politica.versao)
    if fixado == politica.sha256:
        return lock
    if fixado is not None:
        raise PoliticaInvalida(
            f"a versao {politica.versao} ja esta fixada com outro conteudo: sobe a `versao`"
        )
    if lock and _versao(politica.versao) <= _versao(lock[-1][0]):
        raise PoliticaInvalida(
            f"a versao {politica.versao} nao e maior do que {lock[-1][0]}"
        )
    return [*lock, (politica.versao, politica.sha256)]


def texto_do_lock(lock: list[tuple[str, str]]) -> str:
    cabeca = (
        "# Gerado por `python -m politica_categorias gerar` (KAM-088). Uma linha por\n"
        "# versao publicada: o sha256 sela o conteudo, sem a `versao`. Nao se edita.\n"
    )
    return cabeca + "".join(f"{versao} {sha}\n" for versao, sha in lock)


def modulo_ts(politica: Politica) -> str:
    """O modulo TypeScript que o motor importa. Determinista byte a byte."""
    corpo = json.dumps(
        {
            "versao": politica.versao,
            "sha256": politica.sha256,
            "categorias": politica.documento["categorias"],
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        "/**\n"
        " * GERADO por `python -m politica_categorias gerar` a partir de\n"
        " * `policy/categorias/politica.yaml` (KAM-088). Nao se edita: o gate 4\n"
        " * recusa um gerado que nao corresponda a fonte.\n"
        " */\n"
        "\n"
        'import type { PoliticaFonte } from "./tipos.ts";\n'
        "\n"
        f"export const POLITICA: PoliticaFonte = {corpo};\n"
    )


def lock_da_base(raiz: Path, referencia: str) -> list[tuple[str, str]] | None:
    """O lock tal como esta em `referencia` (um ramo ou *commit*), ou `None` se la nao existir.

    Le pelo `git show`, sem tocar na arvore de trabalho.
    """
    resultado = subprocess.run(
        ["git", "-C", str(raiz), "show", f"{referencia}:{LOCK.as_posix()}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if resultado.returncode != 0:
        if "exists on disk, but not in" in resultado.stderr or "does not exist in" in resultado.stderr:
            return None
        raise PoliticaInvalida(f"git show {referencia}: {resultado.stderr.strip()}")
    linhas = []
    for linha in resultado.stdout.splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            versao, sha = linha.split()
            linhas.append((versao, sha))
    return linhas


def problemas_contra_a_base(lock: list[tuple[str, str]], base: list[tuple[str, str]] | None) -> list[str]:
    """O lock so cresce: cada versao publicada na base fica com o mesmo `sha256`.

    E o que fecha o achado F05: sem a base, o selo era auto-atestado — mudava-se
    o conteudo, apagava-se a linha do lock, corria-se `gerar`, e o `check`
    ficava verde com a mesma versao.
    """
    if base is None:
        return []
    actual = dict(lock)
    saida = []
    for versao, sha in base:
        if versao not in actual:
            saida.append(f"a versao {versao} saiu do lock (estava na base)")
        elif actual[versao] != sha:
            saida.append(f"a versao {versao} mudou de conteudo depois de publicada")
    return saida
