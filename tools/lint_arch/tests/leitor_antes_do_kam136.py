"""Copia congelada do `tools/kamba_yaml.py` **tal como estava antes do KAM-136**.

Nao e codigo de producao e nao se importa de fora dos testes. Existe por uma
razao so: o criterio de aceitacao do KAM-136 exige que os ficheiros de
configuracao reais se leiam **igual, campo a campo, antes e depois** da
correccao — e exige-o por comparacao da estrutura lida, nao por «os gates
continuam verdes», porque os gates podiam estar verdes por causa do defeito.

Um retrato da estrutura lida (um JSON de referencia) envelheceria a cada edicao
de um `ci/*.yaml` e obrigaria a regenera-lo; **um algoritmo nao envelhece**. Por
isso o oraculo e o leitor antigo, e o teste
`TestEquivalenciaAntesEDepois.test_cada_ficheiro_real_le_igual` compara os dois
sobre os ficheiros do repositorio.

O teste falhar **nao e um defeito do teste**: significa que a leitura de um
ficheiro real mudou de resultado. O DoD do KAM-136 diz o que fazer nesse caso —
«2 revisores se a leitura de algum `ci/*.yaml` mudar de resultado», porque
significaria que um limiar ou uma excepcao estava a ser lido errado. A
divergencia escreve-se, com a razao, em `_DIVERGENCIAS_ACEITES` no teste.

Os dois defeitos que esta copia preserva, de proposito:

1. `>-` como primeira chave de um item de lista engole as chaves seguintes
   (`indentacao_chave - 1` em `_ler_lista`);
2. item de lista nao citado que contenha `:` torna-se um mapa (o `_CHAVE` sem o
   `(?=[ \t]|$)`).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["YamlSubsetError", "load", "load_file"]


class YamlSubsetError(ValueError):
    """O ficheiro usa YAML fora do subconjunto aceite."""


_PROIBIDOS = {
    "&": "ancora",
    "*": "alias",
    "|": "escalar literal",
    "{": "mapa em estilo de fluxo",
    "!": "tag",
}

_CHAVE = re.compile(r"^(?P<chave>[A-Za-z_][A-Za-z0-9_.-]*|\"[^\"]+\"|'[^']+'):(?P<resto>.*)$")


def _escalar(bruto: str, onde: str):
    """Converte um escalar: nulo, booleano, inteiro, ou texto."""
    texto = bruto.strip()
    if texto == "":
        raise YamlSubsetError(f"{onde}: valor vazio (use \"\" para texto vazio)")

    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "\"'":
        return texto[1:-1]

    if texto[0] in _PROIBIDOS:
        raise YamlSubsetError(f"{onde}: {_PROIBIDOS[texto[0]]} nao suportado ({texto[0]!r})")
    if texto == "[]":
        return []
    if texto.startswith("["):
        raise YamlSubsetError(f"{onde}: lista em estilo de fluxo com conteudo nao suportada")

    if texto in ("null", "~"):
        return None
    if texto in ("true", "false"):
        return texto == "true"
    try:
        return int(texto)
    except ValueError:
        return texto


def _sem_comentario(linha: str) -> str:
    """Remove um comentario de fim de linha, respeitando aspas.

    `razao: "usa # para comentar"` nao perde o `#`.
    """
    fora_de_aspas = True
    aspa = ""
    for indice, caractere in enumerate(linha):
        if fora_de_aspas and caractere in "\"'":
            fora_de_aspas, aspa = False, caractere
        elif not fora_de_aspas and caractere == aspa:
            fora_de_aspas = True
        elif fora_de_aspas and caractere == "#":
            if indice == 0 or linha[indice - 1] in " \t":
                return linha[:indice]
    return linha


class _Linhas:
    """Linhas com indentacao, sem comentarios nem linhas vazias."""

    def __init__(self, texto: str) -> None:
        self.itens: list[tuple[int, int, str]] = []
        for numero, bruta in enumerate(texto.replace("\r\n", "\n").split("\n"), start=1):
            if "\t" in bruta[: len(bruta) - len(bruta.lstrip())]:
                raise YamlSubsetError(f"linha {numero}: tabulacao na indentacao")
            if bruta.strip() == "---":
                raise YamlSubsetError(f"linha {numero}: documentos multiplos nao suportados")
            limpa = _sem_comentario(bruta).rstrip()
            if not limpa.strip():
                continue
            indentacao = len(limpa) - len(limpa.lstrip(" "))
            self.itens.append((numero, indentacao, limpa.strip()))
        self.posicao = 0

    def olhar(self) -> tuple[int, int, str] | None:
        return self.itens[self.posicao] if self.posicao < len(self.itens) else None

    def seguinte(self) -> tuple[int, int, str]:
        item = self.itens[self.posicao]
        self.posicao += 1
        return item


def _ler_dobrado(linhas: _Linhas, indentacao_pai: int, onde: str) -> str:
    """Le um escalar dobrado (`>` ou `>-`): as linhas juntam-se com espaco."""
    partes: list[str] = []
    while True:
        item = linhas.olhar()
        if item is None:
            break
        _, indentacao, conteudo = item
        if indentacao <= indentacao_pai:
            break
        linhas.seguinte()
        partes.append(conteudo)
    if not partes:
        raise YamlSubsetError(f"{onde}: escalar dobrado sem conteudo")
    return " ".join(partes)


def _ler_mapa(linhas: _Linhas, indentacao: int) -> dict:
    mapa: dict = {}
    while True:
        item = linhas.olhar()
        if item is None:
            break
        numero, indentacao_actual, conteudo = item
        if indentacao_actual < indentacao:
            break
        if indentacao_actual > indentacao:
            raise YamlSubsetError(f"linha {numero}: indentacao inesperada")
        if conteudo.startswith("- "):
            break

        linhas.seguinte()
        onde = f"linha {numero}"
        correspondencia = _CHAVE.match(conteudo)
        if not correspondencia:
            raise YamlSubsetError(f"{onde}: esperava 'chave: valor' (lido {conteudo!r})")

        chave = correspondencia.group("chave").strip("\"'")
        if chave in mapa:
            raise YamlSubsetError(f"{onde}: chave repetida {chave!r}")
        resto = correspondencia.group("resto").strip()

        if resto in (">", ">-", ">+"):
            mapa[chave] = _ler_dobrado(linhas, indentacao, onde)
        elif resto == "":
            mapa[chave] = _ler_bloco(linhas, indentacao, onde)
        else:
            mapa[chave] = _escalar(resto, onde)
    return mapa


def _ler_lista(linhas: _Linhas, indentacao: int) -> list:
    lista: list = []
    while True:
        item = linhas.olhar()
        if item is None:
            break
        numero, indentacao_actual, conteudo = item
        if indentacao_actual < indentacao or not conteudo.startswith("- "):
            break
        if indentacao_actual > indentacao:
            raise YamlSubsetError(f"linha {numero}: indentacao de item inconsistente")

        linhas.seguinte()
        onde = f"linha {numero}"
        corpo = conteudo[2:].strip()
        correspondencia = _CHAVE.match(corpo)
        if correspondencia:
            # Item que e um mapa: a primeira chave esta na propria linha do `-`,
            # e as seguintes vem indentadas ao nivel dessa chave.
            indentacao_chave = indentacao + 2
            chave = correspondencia.group("chave").strip("\"'")
            resto = correspondencia.group("resto").strip()
            onde_chave = f"linha {numero}"
            if resto in (">", ">-", ">+"):
                primeiro = {chave: _ler_dobrado(linhas, indentacao_chave - 1, onde_chave)}
            elif resto == "":
                primeiro = {chave: _ler_bloco(linhas, indentacao_chave, onde_chave)}
            else:
                primeiro = {chave: _escalar(resto, onde_chave)}
            seguintes = _ler_mapa(linhas, indentacao_chave)
            repetidas = set(primeiro) & set(seguintes)
            if repetidas:
                raise YamlSubsetError(f"{onde}: chave repetida no item: {sorted(repetidas)}")
            primeiro.update(seguintes)
            lista.append(primeiro)
        else:
            lista.append(_escalar(corpo, onde))
    return lista


def _ler_bloco(linhas: _Linhas, indentacao_pai: int, onde: str):
    """Le o bloco indentado que vem depois de uma `chave:` sem valor."""
    item = linhas.olhar()
    if item is None:
        raise YamlSubsetError(f"{onde}: chave sem valor nem bloco")
    _, indentacao, conteudo = item
    if indentacao <= indentacao_pai:
        raise YamlSubsetError(f"{onde}: chave sem valor nem bloco")
    if conteudo.startswith("- "):
        return _ler_lista(linhas, indentacao)
    return _ler_mapa(linhas, indentacao)


def load(texto: str) -> dict:
    """Le o subconjunto e devolve um dicionario de topo."""
    linhas = _Linhas(texto)
    if linhas.olhar() is None:
        return {}
    numero, indentacao, _ = linhas.olhar()
    if indentacao != 0:
        raise YamlSubsetError(f"linha {numero}: o documento tem de comecar sem indentacao")
    documento = _ler_mapa(linhas, 0)
    sobra = linhas.olhar()
    if sobra is not None:
        raise YamlSubsetError(f"linha {sobra[0]}: conteudo nao consumido ({sobra[2]!r})")
    return documento


def load_file(caminho: Path) -> dict:
    """Le um ficheiro, com o nome do ficheiro na mensagem de erro."""
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as excepcao:
        raise YamlSubsetError(f"{caminho}: {excepcao}") from excepcao
    try:
        return load(texto)
    except YamlSubsetError as excepcao:
        raise YamlSubsetError(f"{caminho}: {excepcao}") from excepcao
