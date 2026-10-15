"""Leitura das tabelas do §3 do dicionario.

So o que o dicionario usa: tabelas de *pipe* com cabecalho e separador, dentro
de subseccoes `### 3.N`. Tudo o resto levanta `DicionarioIlegivel` — uma tabela
que este leitor nao percebe nao pode parecer uma tabela vazia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class DicionarioIlegivel(ValueError):
    """O Markdown do dicionario nao tem a forma que a exportacao sabe ler."""


_SECCAO3 = re.compile(r"^## 3\. ")
_SECCAO_SEGUINTE = re.compile(r"^## (?!3\. )")
_SUBSECCAO = re.compile(r"^### (3\.\d+) (.*)$")
_SEPARADOR = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+\s*$")


@dataclass
class Linha:
    """Uma linha de uma tabela do §3."""

    seccao: str
    numero: int  # linha no ficheiro, para as mensagens
    celulas: dict[str, str] = field(default_factory=dict)


def partir_celulas(linha: str) -> list[str]:
    """Parte uma linha de tabela nos `|` que estao **fora** de crases.

    O dicionario nao tem hoje nenhum `|` dentro de codigo, mas uma expressao
    como `a | b` numa celula futura partia a linha em colunas a mais e
    deslocava o «Substitui» para a «Nota» sem erro nenhum.
    """
    texto = linha.strip()
    if not texto.startswith("|") or not texto.endswith("|"):
        raise DicionarioIlegivel(f"linha de tabela sem `|` nas pontas: {linha!r}")
    celulas: list[str] = []
    actual: list[str] = []
    em_crase = False
    for caractere in texto[1:-1]:
        if caractere == "`":
            em_crase = not em_crase
        if caractere == "|" and not em_crase:
            celulas.append("".join(actual).strip())
            actual = []
        else:
            actual.append(caractere)
    if em_crase:
        raise DicionarioIlegivel(f"crase por fechar numa linha de tabela: {linha!r}")
    celulas.append("".join(actual).strip())
    return celulas


def _papel(cabecalho: str) -> str:
    """O papel de uma coluna, pelo seu cabecalho."""
    texto = cabecalho.strip().lower()
    if texto.startswith("conceito"):
        return "conceito"
    if texto.startswith("nome"):
        return "nome"
    if texto.startswith("substitui"):
        return "substitui"
    if texto.startswith("nota"):
        return "nota"
    if texto.startswith("ticket"):
        return "ticket"
    raise DicionarioIlegivel(
        f"coluna de cabecalho desconhecido no §3: {cabecalho!r}. A exportacao "
        "precisa de saber se e conceito, nome, substitui, nota ou ticket."
    )


def ler_linhas(texto: str) -> list[Linha]:
    """Devolve todas as linhas de todas as tabelas do §3, pela ordem do ficheiro."""
    linhas = texto.replace("\r\n", "\n").split("\n")
    dentro = False
    seccao = ""
    resultado: list[Linha] = []
    indice = 0
    viu_seccao3 = False
    while indice < len(linhas):
        linha = linhas[indice]
        if _SECCAO3.match(linha):
            dentro, viu_seccao3 = True, True
        elif _SECCAO_SEGUINTE.match(linha):
            dentro = False
        if not dentro:
            indice += 1
            continue

        sub = _SUBSECCAO.match(linha)
        if sub:
            seccao = sub.group(1)
            indice += 1
            continue

        if linha[:1] in (" ", "\t") and linha.lstrip().startswith("|"):
            raise DicionarioIlegivel(
                f"linha {indice + 1}: tabela indentada no §3. A exportacao so le tabelas "
                "encostadas a margem; uma tabela indentada era ignorada sem aviso"
            )
        if linha.startswith("|"):
            if indice + 1 >= len(linhas) or not _SEPARADOR.match(linhas[indice + 1]):
                raise DicionarioIlegivel(
                    f"linha {indice + 1}: tabela sem linha de separacao depois do cabecalho"
                )
            if not seccao:
                raise DicionarioIlegivel(
                    f"linha {indice + 1}: tabela do §3 fora de uma subseccao `### 3.N`"
                )
            papeis = [_papel(c) for c in partir_celulas(linha)]
            if "conceito" not in papeis or "nome" not in papeis:
                raise DicionarioIlegivel(
                    f"linha {indice + 1}: tabela do §{seccao} sem coluna de conceito ou de nome"
                )
            if len(set(papeis)) != len(papeis):
                raise DicionarioIlegivel(
                    f"linha {indice + 1}: tabela do §{seccao} com duas colunas do mesmo papel"
                )
            indice += 2
            while indice < len(linhas) and linhas[indice].startswith("|"):
                celulas = partir_celulas(linhas[indice])
                if len(celulas) != len(papeis):
                    raise DicionarioIlegivel(
                        f"linha {indice + 1}: {len(celulas)} celulas numa tabela de "
                        f"{len(papeis)} colunas (§{seccao})"
                    )
                resultado.append(
                    Linha(seccao=seccao, numero=indice + 1, celulas=dict(zip(papeis, celulas)))
                )
                indice += 1
            continue
        indice += 1

    if not viu_seccao3:
        raise DicionarioIlegivel("o dicionario nao tem uma seccao `## 3. `")
    if not resultado:
        raise DicionarioIlegivel("o §3 do dicionario nao tem nenhuma linha de tabela")
    return resultado


_VERSAO = re.compile(r"^\| (\d+\.\d+) \|")


def ultima_versao(texto: str) -> str:
    """A ultima versao registada no «Controlo de versoes» (§6)."""
    em_versoes = False
    versao = ""
    for linha in texto.replace("\r\n", "\n").split("\n"):
        if linha.startswith("## 6. "):
            em_versoes = True
            continue
        if em_versoes and linha.startswith("## "):
            break
        if em_versoes:
            achado = _VERSAO.match(linha)
            if achado:
                versao = achado.group(1)
    if not versao:
        raise DicionarioIlegivel("nao encontrei nenhuma versao no §6 do dicionario")
    return versao
