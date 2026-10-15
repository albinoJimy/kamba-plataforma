"""Leitura de `Dockerfile`: instrucoes logicas, com continuacoes de linha juntas."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

__all__ = ["DockerfileIlegivel", "Instrucao", "e_dockerfile", "instrucoes", "directiva_syntax"]


class DockerfileIlegivel(ValueError):
    """O ficheiro tem uma forma que este leitor nao segue ate ao fim."""


@dataclasses.dataclass(frozen=True)
class Instrucao:
    nome: str  # em maiusculas: FROM, RUN, CMD, ...
    argumentos: str
    linha: int


def e_dockerfile(caminho: Path) -> bool:
    # Sem distinguir maiusculas, e com qualquer separador: `dockerfile`,
    # `Dockerfile-base`, `Dockerfile_dev` e `base.Dockerfile` sao todos nomes
    # que o `docker build -f` aceita e que as pessoas escrevem.
    nome = caminho.name.lower()
    if nome.endswith((".md", ".txt", ".py", ".dockerignore")):
        return False
    return (
        nome in ("dockerfile", "containerfile")
        or nome.startswith(("dockerfile.", "dockerfile-", "dockerfile_", "containerfile.", "containerfile-", "containerfile_"))
        or nome.endswith((".dockerfile", ".containerfile", "-dockerfile", "_dockerfile"))
    )


_SYNTAX = re.compile(r"^#\s*syntax\s*=\s*(?P<imagem>\S+)\s*$", re.IGNORECASE)
_ESCAPE = re.compile(r"^#\s*escape\s*=\s*(?P<caractere>\S)\s*$", re.IGNORECASE)
#: `<<EOF`, `<<-EOF`, `<<"EOF"`. **Nao** `<<<` (here-string) nem `1<<n`
#: (deslocamento): a primeira versao casava os dois, e o resto do ficheiro —
#: `FROM` e `CMD` incluidos — passava a ser «corpo» de um `RUN`.
_HEREDOC = re.compile(r"""(?<![<\w$)\]])<<(?!<)-?\s*["']?(?P<fim>[A-Za-z_][A-Za-z0-9_]*)["']?""")


def directiva_syntax(texto: str) -> tuple[str, int] | None:
    """`# syntax=docker/dockerfile:1` descarrega e executa um *frontend*.

    E uma referencia de imagem como outra qualquer, e a mais facil de esquecer:
    nao tem `FROM` a frente. So conta antes da primeira instrucao.
    """
    for numero, linha in enumerate(texto.split("\n"), start=1):
        limpa = linha.strip()
        if not limpa:
            continue
        if not limpa.startswith("#"):
            return None
        directiva = _SYNTAX.match(limpa)
        if directiva:
            return directiva.group("imagem"), numero
    return None


def instrucoes(texto: str) -> list[Instrucao]:
    escape = "\\"
    for linha in texto.split("\n"):
        limpa = linha.strip()
        if not limpa:
            continue
        if not limpa.startswith("#"):
            break
        directiva = _ESCAPE.match(limpa)
        if directiva:
            escape = directiva.group("caractere")

    resultado: list[Instrucao] = []
    acumulado = ""
    inicio = 0
    #: Delimitadores de *here-documents* por fechar (`RUN <<EOF`). O corpo e
    #: codigo que corre na construcao, e tem de ser lido como parte do `RUN`:
    #: tratado como instrucoes, um `pip install` la dentro passava sem ser visto.
    por_fechar: list[str] = []
    for numero, linha in enumerate(texto.split("\n"), start=1):
        limpa = linha.strip()
        if por_fechar:
            if limpa == por_fechar[0]:
                por_fechar.pop(0)
            else:
                anterior = resultado[-1]
                resultado[-1] = Instrucao(
                    anterior.nome, f"{anterior.argumentos}\n{limpa}", anterior.linha
                )
            continue
        if not acumulado:
            if not limpa or limpa.startswith("#"):
                continue
            inicio = numero
        elif limpa.startswith("#"):
            # Comentario no meio de uma continuacao: o Docker ignora-o.
            continue
        if limpa.endswith(escape):
            acumulado += limpa[: -len(escape)].rstrip() + " "
            continue
        acumulado += limpa
        partes = acumulado.strip().split(None, 1)
        # `ONBUILD RUN pip install x` corre na construcao de quem herdar desta
        # imagem: le-se como a instrucao que transporta.
        while partes and partes[0].upper() == "ONBUILD" and len(partes) > 1:
            partes = partes[1].strip().split(None, 1)
        if partes:
            resultado.append(
                Instrucao(partes[0].upper(), partes[1] if len(partes) > 1 else "", inicio)
            )
            if partes[0].upper() in ("RUN", "COPY", "ADD") and len(partes) > 1:
                por_fechar = [m.group("fim") for m in _HEREDOC.finditer(partes[1])]
        acumulado = ""
    if por_fechar:
        raise DockerfileIlegivel(
            f"linha {resultado[-1].linha}: here-document `<<{por_fechar[0]}` por fechar; "
            "o resto do ficheiro seria lido como corpo dele"
        )
    if acumulado.strip():
        partes = acumulado.strip().split(None, 1)
        resultado.append(
            Instrucao(partes[0].upper(), partes[1] if len(partes) > 1 else "", inicio)
        )
    return resultado
