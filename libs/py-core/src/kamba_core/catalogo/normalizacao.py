"""A normalizacao PT-AO do Catalogo AI, sobre a do indice (KAM-049, criterio 5).

**Nao ha aqui lexico nenhum, nem gramatica de numeros.** Tudo vem do
`kamba_core.idx` do KAM-062:

* o lexico e o `idx.termo_canonico` versionado por `idx.norm_versao` (global e
  por tenant, o do tenant a prevalecer), lido pelo `kamba_core.idx.lexico`. E a
  tabela a que o §8.2 do `docs/tecnica/03` chama `lexico_pt_ao`: o nome do
  desenho ficou no desenho, e o canon tem um so lexico para o indice e para o
  catalogo — dois lexicos divergiam na primeira marca curada num e nao no outro;
* «45 mil», «45k», «45 000 kz» e «quarenta e cinco mil» leem-se pelo
  `passo_1`, pelo `por_extenso` e pelo `extrair_restricoes` do indice, que ja
  tem os seus ensaios e a sua revisao adversarial;
* as unidades (`un`, `unid`, `pcs`, `caixa`, `fardo`) sao termos do tipo
  `unidade`, e as marcas termos do tipo `marca`;
* a ortografia das marcas e a semelhanca de trigramas do `pg_trgm`, a mesma
  funcao que o indice cruza com o PostgreSQL no *gate* 8, com o mesmo limiar.

O que este modulo acrescenta e so a aplicacao a **campos de produto**: o nome
mostrado ao dono nao perde os acentos (so a marca e a unidade se canonizam), e
um preco e sempre um valor em Kz — uma moeda estrangeira nao se converte, e
devolve `None` para que se pergunte.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from ..idx.normalizacao import (
    LIMIAR_DE_CORRECCAO,
    Lexico,
    normalizar_documento,
    passo_1,
    semelhanca,
)
from ..idx.numeros import extrair_restricoes, por_extenso
from .extraccao import DONO_VOZ, Campo, Extraccao

#: A mesma do indice: corrige uma marca so com semelhanca >= 0,6.
LIMIAR_DA_MARCA: Final = LIMIAR_DE_CORRECCAO


@dataclass(frozen=True)
class Preco:
    """Um preco em unidade menor (AOA), lido de um texto."""

    minor: int
    moeda: str = "AOA"


def ler_preco(texto: str, *, origem: str | None = None) -> Preco | None:
    """O preco de um texto do dono ou de uma etiqueta, ou `None`.

    `None` quando nao ha numero, quando ha mais do que um, ou quando a moeda e
    estrangeira: em todos estes casos a resposta e uma pergunta, e nao um valor
    escolhido por nos.

    >>> ler_preco("45 mil").minor
    4500000
    >>> ler_preco("45k").minor
    4500000
    >>> ler_preco("12 000 Kz").minor
    1200000
    >>> ler_preco("20 dolares") is None
    True
    """
    tokens = passo_1(texto)
    if origem == DONO_VOZ:
        tokens = por_extenso(tokens)
    restricoes, _resto = extrair_restricoes(tokens)
    if restricoes.moeda is not None:
        return None
    valores = [
        v
        for v in (restricoes.alvo_preco_minor, restricoes.max_preco_minor, restricoes.min_preco_minor)
        if v is not None
    ]
    if len(valores) != 1 or valores[0] <= 0:
        return None
    return Preco(minor=valores[0])


def _canonico_unico(canonico: str) -> str:
    # Um termo com alternativas (`|`) e ambiguo: o indice pergunta, e aqui nao se
    # escolhe por ninguem — fica o texto como veio.
    return "" if "|" in canonico else canonico


def normalizar_marca(valor: str, lexico: Lexico) -> str | None:
    """A marca canonica do lexico, exacta ou por trigramas; `None` se nenhuma."""
    tokens = passo_1(valor)
    if not tokens:
        return None
    exacta = normalizar_documento(valor, lexico).marca_canon
    if exacta and _canonico_unico(exacta):
        return exacta
    alvo = " ".join(tokens)
    melhor: tuple[float, str] | None = None
    for termo in lexico.do_tipo("marca").values():
        canonico = _canonico_unico(termo.canonico)
        if not canonico:
            continue
        for candidato in (" ".join(termo.termo), canonico):
            s = semelhanca(alvo, candidato)
            if s >= LIMIAR_DA_MARCA and (melhor is None or (-s, canonico) < (-melhor[0], melhor[1])):
                melhor = (s, canonico)
    return melhor[1] if melhor else None


def normalizar_unidade(valor: str, lexico: Lexico) -> str | None:
    """A unidade canonica (`unid` -> `un`), ou `None` se o lexico nao a conhece."""
    tokens = tuple(passo_1(valor))
    termo = lexico.do_tipo("unidade").get(tokens)
    if termo is None:
        return None
    return _canonico_unico(termo.canonico) or None


def normalizar(extraccao: Extraccao, lexico: Lexico) -> Extraccao:
    """A extraccao com a marca e a unidade canonicas. O resto fica como veio.

    Um campo canonizado mantem a fonte e a confianca: canonizar `Niké` para
    `nike` nao e confirmar que a foto e de um produto Nike.
    """
    campos: dict[str, Campo] = dict(extraccao.campos)
    marca = campos.get("marca")
    if marca is not None and isinstance(marca.valor, str):
        canonica = normalizar_marca(marca.valor, lexico)
        if canonica:
            campos["marca"] = replace(marca, valor=canonica)
    unidade = campos.get("unidade")
    if unidade is not None and isinstance(unidade.valor, str):
        canonica = normalizar_unidade(unidade.valor, lexico)
        if canonica:
            campos["unidade"] = replace(unidade, valor=canonica)
    return replace(extraccao, campos=campos)
