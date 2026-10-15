"""Copia congelada do `tools/secrets_inventory/yamlsubset.py` **tal como estava antes do KAM-148**.

Nao e codigo de producao e nao se importa de fora dos testes. Existe por uma
razao so: o criterio de aceitacao do KAM-148 exige que os ficheiros reais que
este leitor le se leiam **igual, campo a campo, antes e depois** da correccao —
e exige-o por comparacao da estrutura lida, nao por «os gates continuam
verdes», porque os gates podiam estar verdes por causa do defeito.

Um retrato da estrutura lida (um JSON de referencia) envelheceria a cada edicao
do ficheiro lido e obrigaria a regenera-lo; **um algoritmo nao envelhece**. Por
isso o oraculo e o leitor antigo. O padrao e o do KAM-136
(`tools/lint_arch/tests/leitor_antes_do_kam136.py`).

O teste falhar **nao e um defeito do teste**: significa que a leitura de um
ficheiro real mudou de resultado, e o DoD do KAM-148 diz o que fazer nesse caso
— «2 revisores se a leitura do `ops/secrets-inventory.yaml` ou de uma fixture de
`registry` mudar de resultado».

O *docstring* original do modulo foi substituido por esta nota; o resto do
ficheiro e copia textual. Os defeitos que esta copia preserva, de proposito,
estao em `tools/secrets_inventory/tests/corpus_yamlsubset.py` — e ha um teste que prova que ela **ainda** os tem: se os
perder, deixou de ser oraculo.
"""

from __future__ import annotations


class YamlSubsetError(ValueError):
    """O ficheiro usa YAML fora do subconjunto aceite."""


Escalar = str | int | bool | None


def _escalar(bruto: str, onde: str) -> Escalar:
    """Converte um escalar: texto, inteiro, booleano ou `null`."""
    texto = bruto.strip()
    if texto == "":
        raise YamlSubsetError(f"{onde}: valor vazio (use \"\" ou null)")
    if texto[0] in "{|>&*!":
        raise YamlSubsetError(
            f"{onde}: ancora, mapa de fluxo ou escalar de bloco nao suportado ({texto[0]!r})"
        )
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "\"'":
        return texto[1:-1]
    if texto in ("true", "false"):
        return texto == "true"
    if texto in ("null", "~"):
        return None
    try:
        return int(texto)
    except ValueError:
        return texto


def _lista_de_fluxo(bruto: str, onde: str) -> list[Escalar]:
    """Converte `[a, b, c]` e `[]`."""
    interior = bruto.strip()[1:-1].strip()
    if interior == "":
        return []
    if "[" in interior or "]" in interior:
        raise YamlSubsetError(f"{onde}: lista de listas nao suportada")
    return [_escalar(parte, onde) for parte in interior.split(",")]


def _valor(bruto: str, onde: str) -> Escalar | list[Escalar]:
    texto = bruto.strip()
    if texto.startswith("["):
        if not texto.endswith("]"):
            raise YamlSubsetError(f"{onde}: lista de fluxo sem fecho")
        return _lista_de_fluxo(texto, onde)
    return _escalar(texto, onde)


def _sem_comentario(linha: str) -> str:
    """Remove um comentario de fim de linha, se for seguro faze-lo."""
    corpo = linha.strip()
    if corpo.startswith("#"):
        return ""
    _, _, valor = corpo.partition(":")
    if valor.strip().startswith(("\"", "'")):
        # Valor entre aspas: o cardinal, se existir, pertence ao valor.
        return linha.rstrip()
    indice = linha.find(" #")
    return (linha[:indice] if indice != -1 else linha).rstrip()


def load(texto: str) -> dict[str, object]:
    """Le o subconjunto e devolve um dicionario de topo."""
    raiz: dict[str, object] = {}
    lista_actual: list[dict[str, object]] | None = None
    item_actual: dict[str, object] | None = None
    indent_item: int | None = None

    for numero, linha_bruta in enumerate(texto.splitlines(), start=1):
        onde = f"linha {numero}"
        if "\t" in linha_bruta:
            raise YamlSubsetError(f"{onde}: tabulacao na indentacao")
        linha = _sem_comentario(linha_bruta)
        if linha.strip() == "":
            continue

        indent = len(linha) - len(linha.lstrip(" "))
        corpo = linha.strip()

        if corpo.startswith("- "):
            if lista_actual is None:
                raise YamlSubsetError(f"{onde}: item de lista sem chave de lista acima")
            if indent_item is None:
                indent_item = indent
            elif indent != indent_item:
                raise YamlSubsetError(f"{onde}: indentacao de item inconsistente")
            item_actual = {}
            lista_actual.append(item_actual)
            corpo = corpo[2:].strip()
            chave, sep, valor = corpo.partition(":")
            if sep == "" or valor.strip() == "":
                raise YamlSubsetError(f"{onde}: item de lista tem de ser 'chave: valor'")
            item_actual[chave.strip()] = _valor(valor, onde)
            continue

        chave, sep, valor = corpo.partition(":")
        if sep == "":
            raise YamlSubsetError(f"{onde}: esperava 'chave: valor'")
        chave = chave.strip()
        if chave == "":
            raise YamlSubsetError(f"{onde}: chave vazia")

        if valor.strip() == "":
            # Chave que abre uma lista de mapas.
            if indent != 0:
                raise YamlSubsetError(f"{onde}: lista aninhada nao suportada")
            lista_actual = []
            item_actual = None
            indent_item = None
            raiz[chave] = lista_actual
            continue

        if indent == 0:
            raiz[chave] = _valor(valor, onde)
            lista_actual = None
            item_actual = None
            indent_item = None
        else:
            if item_actual is None:
                raise YamlSubsetError(f"{onde}: chave indentada fora de um item de lista")
            if indent_item is not None and indent != indent_item + 2:
                raise YamlSubsetError(f"{onde}: indentacao de chave inconsistente")
            if chave in item_actual:
                raise YamlSubsetError(f"{onde}: chave repetida no mesmo item ({chave})")
            item_actual[chave] = _valor(valor, onde)

    return raiz
