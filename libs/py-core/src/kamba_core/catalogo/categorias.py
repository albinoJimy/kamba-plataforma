"""A categoria de produto de uma oferta, da lista fechada (KAM-209).

A fonte e `policy/categorias_de_produto.yaml`; isto e a copia que o catalogo
por IA usa, e o `tests/test_categorias_de_produto.py` recusa-a se divergir.

**A categoria do catalogo e texto livre** (o campo `categoria` da visao ou do
dono, KAM-049), e a oferta precisa de um `id` da lista: o `categoria_de_produto`
leva um ao outro, palavra a palavra depois do `passo_1`. Um texto que ja e um
`id` fica esse `id`; um texto que nenhum termo apanha cai na `outra`, que nao se
avalia. O resultado aparece no resumo que o dono confirma (`pipeline.resumo`),
e e ai que a confirmacao do dono cobre a categoria que a oferta leva.

Os termos sao *proposta* — ver o cabecalho do ficheiro da politica.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ..idx.normalizacao import passo_1

VERSAO: Final = "1.0.0"

#: A categoria de quem nao cabe nas outras. Nao se avalia.
OUTRA: Final = "outra"

#: `id` -> termos, pela ordem da politica. A ordem desempata: o primeiro `id`
#: com um termo no texto ganha.
CATEGORIAS: Final[Mapping[str, frozenset[str]]] = {
    "moda": frozenset(
        "moda roupa roupas vestuario calcado calcados sapato sapatos sapatilha sapatilhas "
        "camisa camisas vestido vestidos calcas saia blusa".split()
    ),
    "mercearia": frozenset(
        "mercearia alimentacao alimentar alimento alimentos supermercado congelados bebida "
        "bebidas sumo sumos arroz oleo farinha".split()
    ),
    "restauracao": frozenset(
        "restaurante restauracao comida refeicao refeicoes pastelaria padaria".split()
    ),
    "beleza": frozenset(
        "beleza cabeleireiro estetica salao cosmetica cosmeticos perfume perfumes".split()
    ),
    "electronica": frozenset(
        "electronica eletronica electronicos telemovel telemoveis telefone portatil "
        "computador informatica televisor electrodomestico electrodomesticos".split()
    ),
    "servicos": frozenset("servico servicos reparacao manutencao instalacao limpeza".split()),
    "material_construcao": frozenset(
        "construcao cimento tijolo tijolos ferragens tinta tintas".split()
    ),
    OUTRA: frozenset(),
}

#: As que a varredura do preco anomalo avalia: todas menos a `outra`.
AVALIA_PRECO: Final = frozenset(c for c in CATEGORIAS if c != OUTRA)


def categoria_de_produto(texto: str | None) -> str | None:
    """O `id` da lista para o texto livre da categoria; `None` sem texto.

    >>> categoria_de_produto("Vestuário de homem")
    'moda'
    >>> categoria_de_produto("material_construcao")
    'material_construcao'
    >>> categoria_de_produto("artesanato")
    'outra'
    """
    if texto is None or not texto.strip():
        return None
    if texto.strip() in CATEGORIAS:
        return texto.strip()
    palavras = set(passo_1(texto))
    for categoria, termos in CATEGORIAS.items():
        if palavras & termos:
            return categoria
    return OUTRA


__all__ = ["AVALIA_PRECO", "CATEGORIAS", "OUTRA", "VERSAO", "categoria_de_produto"]
