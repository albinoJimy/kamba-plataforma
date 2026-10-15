"""Segredo pedido pelo codigo que nao esta no inventario (KAM-010).

Este modulo e a parte do criterio de aceitacao que diz «uma verificacao de CI
falha se o codigo pedir um segredo ausente do inventario». A ferramenta e deste
ticket; **ligar o *job* ao pipeline e do KAM-002**, que ainda nao fundiu — ver
`tools/secrets_inventory/README.md` §4 para o alvo e o nome do *job*.

## O que conta como "pedir um segredo"

Tres coisas, todas detectadas por texto e nao por AST — porque uma analise de
AST precisava de um parser de TypeScript, e a dependencia nao se justifica para
o que tem de apanhar:

1. **Pedido literal:** `.getRing("x")`, `.get_ring("x")`, `.versions("x")` — que
   so a porta tem — ou `.get("x")` quando o receptor e um dos nomes de
   `RECEPTORES`. O `get` sem receptor conhecido nao conta: `dados.get("version")`
   e um acesso a dicionario.
2. **Lista de obrigatorios:** as referencias dentro de `obrigatorios: [...]`
   (TypeScript) ou `obrigatorios=[...]` (Python).
3. **Nome de variavel de ambiente:** qualquer `KAMBA_SECRET_...` nos ficheiros
   analisados — inclui `docker-compose`, `.env.example` e Dockerfiles, que e
   onde um segredo entra sem passar pela porta.

E uma quarta coisa que **nao** e um pedido mas falha de qualquer modo:

4. **Pedido dinamico:** `secrets.get(nome)` ou `.getRing(nome)` com um argumento
   que nao e um literal. Nao
   se consegue verificar contra o inventario, pelo que fica proibido. A saida e
   escrever o literal, ou marcar a linha com

       kamba:secrets-inventory dinamico <razao>

   num comentario. Uma marca sem razao nao conta: uma excepcao sem razao escrita
   e uma excepcao que ninguem revoga.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .inventario import Inventario

EXTENSOES = frozenset({".ts", ".tsx", ".js", ".mjs", ".py", ".yaml", ".yml", ".env", ""})

#: Nomes de ficheiro sem extensao que valem a pena analisar.
NOMES = frozenset({"Dockerfile", ".env.example"})

#: Directorios que nunca se analisam, em qualquer profundidade.
IGNORAR_SEMPRE = frozenset({"node_modules", "dist", "__pycache__", ".venv", ".git"})

PREFIXO_ENV = "KAMBA_SECRET_"

#: Sufixo da variavel que guarda a versao anterior (ver `_familia_de_variavel`).
SUFIXO_ANEL = "_ANTERIOR"

#: Metodos que so a porta de segredos tem, e que por isso identificam um pedido
#: por si sos.
_METODOS_PROPRIOS = r"(?:getRing|get_ring|versions)"

#: Nomes de receptor que qualificam um `get` como pedido de segredo.
#:
#: `get` sozinho **nao** serve: `dados.get("version")` e um acesso a dicionario,
#: e a primeira versao deste verificador marcou 27 desses como segredos em falta
#: — um verificador que grita em acessos a dicionario e um verificador que
#: alguem desliga. Por isso o `get` conta so quando o receptor diz que e o cofre.
RECEPTORES = ("secrets", "segredos", "cofre", "secret_provider", "secretProvider")

_RECEPTORES = r"(?:" + "|".join(RECEPTORES) + r")"
_REF = r"[a-z][a-z0-9_]{2,63}(?:/[A-Za-z0-9._:-]{1,128})?"

#: `secrets.get("x")`, `cofre.get('x')`, `qualquerCoisa.getRing("x")`.
PEDIDO_LITERAL = re.compile(
    rf"(?:\b{_RECEPTORES}\.get|\.{_METODOS_PROPRIOS})\(\s*[\"']({_REF})[\"']\s*\)"
)

#: O mesmo, com um argumento que nao e um literal.
PEDIDO_DINAMICO = re.compile(
    rf"(?:\b{_RECEPTORES}\.get|\.{_METODOS_PROPRIOS})\(\s*(?![\"']|\s*\))"
)

#: `obrigatorios: [...]` e `obrigatorios=[...]`.
BLOCO_OBRIGATORIOS = re.compile(r"obrigatorios\s*[:=]\s*\[([^\]]*)\]", re.DOTALL)

LITERAL_EM_LISTA = re.compile(rf"[\"']({_REF})[\"']")

#: `KAMBA_SECRET_META_APP_SECRET`, `KAMBA_SECRET_META_CLIENT_TOKEN__7f3cAb`.
VARIAVEL = re.compile(rf"{PREFIXO_ENV}([A-Z][A-Z0-9_]*?)(?:__([A-Za-z0-9_]+))?\b")

MARCA = re.compile(r"kamba:secrets-inventory\s+dinamico\s+(\S.*)$")


@dataclass(frozen=True)
class Achado:
    """Um pedido de segredo encontrado no codigo."""

    caminho: str
    linha: int
    referencia: str
    familia: str
    origem: str


def _analisavel(caminho: Path) -> bool:
    if caminho.name in NOMES:
        return True
    return caminho.suffix in EXTENSOES and caminho.suffix != ""


def ficheiros(raiz: Path, inventario: Inventario) -> list[Path]:
    """Ficheiros a analisar, segundo `analise_raizes` e `analise_excluir`.

    Usa `os.walk` e **poda** os directorios de `IGNORAR_SEMPRE` em vez de os
    filtrar depois. Nao e desempenho: um `rglob("*")` desce para dentro de
    `node_modules`, onde o pnpm deixa ligacoes simbolicas que o Windows recusa
    estatizar — e o verificador morria com `WinError 1920` antes de chegar a
    verificar coisa nenhuma.
    """
    excluidos = tuple(inventario.excluir)
    encontrados: list[Path] = []
    for nome_raiz in inventario.raizes:
        base = raiz / nome_raiz
        if base.is_file():
            # Uma raiz pode ser um ficheiro: o `.env.example` esta na raiz do
            # repositorio, e declarar `.` como raiz para o apanhar varreria o
            # repositorio inteiro.
            if _analisavel(base):
                encontrados.append(base)
            continue
        if not base.is_dir():
            continue
        for pasta, subpastas, nomes in os.walk(base):
            subpastas[:] = sorted(s for s in subpastas if s not in IGNORAR_SEMPRE)
            pasta_relativa = Path(pasta).relative_to(raiz).as_posix()
            if any(
                pasta_relativa == e or pasta_relativa.startswith(e + "/") for e in excluidos
            ):
                subpastas[:] = []
                continue
            for nome in sorted(nomes):
                caminho = Path(pasta) / nome
                if not _analisavel(caminho):
                    continue
                relativo = caminho.relative_to(raiz).as_posix()
                if any(relativo == e or relativo.startswith(e + "/") for e in excluidos):
                    continue
                encontrados.append(caminho)
    return encontrados


def _familia_de_variavel(nome: str) -> str:
    """Familia de um nome de variavel, ja sem o sufixo do anel.

    `KAMBA_SECRET_META_APP_SECRET_ANTERIOR` e a **segunda posicao** do anel do
    mesmo segredo, nao um segredo chamado `meta_app_secret_anterior`. Sem este
    corte, todo o `.env` com um anel definido falharia a verificacao com um nome
    que o inventario nunca vai ter.
    """
    if nome.endswith(SUFIXO_ANEL):
        nome = nome[: -len(SUFIXO_ANEL)]
    return nome.lower()


def analisar_texto(caminho: str, texto: str) -> tuple[list[Achado], list[str]]:
    """Achados e problemas de um ficheiro.

    `problemas` cobre o pedido dinamico sem marca: nao e um achado (nao ha
    referencia para comparar com o inventario) mas falha a verificacao.
    """
    achados: list[Achado] = []
    problemas: list[str] = []
    linhas = texto.splitlines()

    for numero, linha in enumerate(linhas, start=1):
        for encontro in PEDIDO_LITERAL.finditer(linha):
            referencia = encontro.group(1)
            achados.append(
                Achado(
                    caminho=caminho,
                    linha=numero,
                    referencia=referencia,
                    familia=referencia.split("/", 1)[0],
                    origem="pedido",
                )
            )
        for encontro in VARIAVEL.finditer(linha):
            familia = _familia_de_variavel(encontro.group(1))
            instancia = encontro.group(2)
            achados.append(
                Achado(
                    caminho=caminho,
                    linha=numero,
                    referencia=familia if instancia is None else f"{familia}/{instancia}",
                    familia=familia,
                    origem="variavel",
                )
            )
        if PEDIDO_DINAMICO.search(linha) and PEDIDO_LITERAL.search(linha) is None:
            marca = MARCA.search(linha)
            if marca is None:
                problemas.append(
                    f"{caminho}:{numero}: pedido de segredo com nome dinamico; "
                    "use um literal ou marque a linha com "
                    "`kamba:secrets-inventory dinamico <razao>`"
                )

    for encontro in BLOCO_OBRIGATORIOS.finditer(texto):
        numero = texto[: encontro.start()].count("\n") + 1
        for literal in LITERAL_EM_LISTA.finditer(encontro.group(1)):
            referencia = literal.group(1)
            achados.append(
                Achado(
                    caminho=caminho,
                    linha=numero,
                    referencia=referencia,
                    familia=referencia.split("/", 1)[0],
                    origem="obrigatorios",
                )
            )

    return achados, problemas


def verificar(raiz: Path, inventario: Inventario) -> tuple[list[Achado], list[str]]:
    """Analisa o repositorio. Devolve os achados e os erros encontrados."""
    todos: list[Achado] = []
    erros: list[str] = []

    for caminho in ficheiros(raiz, inventario):
        relativo = caminho.relative_to(raiz).as_posix()
        try:
            texto = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # Binario ou ilegivel: nao e codigo a pedir segredos.
        achados, problemas = analisar_texto(relativo, texto)
        todos.extend(achados)
        erros.extend(problemas)

    for achado in todos:
        segredo = inventario.por_id.get(achado.familia)
        if segredo is None:
            erros.append(
                f"{achado.caminho}:{achado.linha}: o codigo pede o segredo "
                f"{achado.referencia!r}, que nao esta em ops/secrets-inventory.yaml"
            )
            continue
        tem_instancia = "/" in achado.referencia
        if segredo.instancias == "nenhuma" and tem_instancia:
            erros.append(
                f"{achado.caminho}:{achado.linha}: {achado.familia!r} esta declarado com "
                "`instancias: nenhuma` e foi pedido com instancia"
            )
        if segredo.instancias != "nenhuma" and not tem_instancia:
            erros.append(
                f"{achado.caminho}:{achado.linha}: {achado.familia!r} tem "
                f"`instancias: {segredo.instancias}` e foi pedido sem instancia — "
                "pedir a familia devolveria o segredo de nenhum deles"
            )

    return todos, erros
