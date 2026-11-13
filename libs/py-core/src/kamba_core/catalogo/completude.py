"""Perfis de completude e perguntas ao dono (KAM-049, criterio 6; `docs/tecnica/03` §8.3).

## As tres regras das perguntas

1. **No maximo tres por mensagem** (`MAXIMO_POR_MENSAGEM`), e **doze no
   total** (`MAXIMO_DE_PERGUNTAS`, o `CHECK (perguntas_feitas <= 12)` da `0052`).
   Ao chegar as doze, a ingestao deixa de perguntar e fica em `a_perguntar`
   com os campos em falta a vista: e um caso para o painel, nao para mais
   mensagens.
2. **Os campos criticos perguntam-se um de cada vez** (preco e stock, §8.3):
   uma resposta a «quanto custa e quantos tens?» numa so frase e o sitio
   onde um numero cai no campo errado. Enquanto houver um critico em falta, a
   mensagem leva so esse.
3. **A primeira pergunta e sempre o `preco_tipo`** (criterio 5). Nao ha
   excepcao para a etiqueta: um preco lido da foto e sugestao (`preco_sugerido`)
   e entra **na** pergunta do preco, nunca no lugar dela.

## Os perfis

| Perfil | Alem de `nome`, `categoria`, `preco_tipo` (+ `preco`) |
|---|---|
| `geral` | `stock_modo` (+ `stock`), `entrega` |
| `vestuario` | `stock_modo` (+ `stock`), `entrega`, `variantes` (tamanho/cor) |
| `alimentar` | `stock_modo` (+ `stock`), `entrega`, `variantes` (sabor/peso); validade e lote sao opcionais |
| `electronica` | `stock_modo` (+ `stock`), `entrega`, `variantes` (modelo/capacidade), `marca`, `garantia` |
| `servico` | `duracao`, `local`, `pre_aviso` — sem stock (a agenda e do `servicos`, `docs/tecnica/02`) |

O `preco` so falta quando o `preco_tipo` leva numero (`fixo`, `a_partir_de`;
o `sob_consulta` nao, pela `offer_terms` da `0028`); o `stock` so falta quando
o `stock_modo` e `garantido` ou `indicativo` (o `confirmar_dono` pergunta a
cada encomenda).

O perfil escolhe-se pela categoria (`perfil_da_categoria`), por palavras do
nome da categoria. As palavras sao *proposta*: o conjunto de avaliacao do
bloco e quem as calibra, e uma categoria que nenhuma apanha cai no `geral`,
que pede o minimo comum aos cinco.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from ..idx.normalizacao import passo_1
from .extraccao import Campo

MAXIMO_POR_MENSAGEM: Final = 3
MAXIMO_DE_PERGUNTAS: Final = 12

PRECO_TIPOS: Final = ("fixo", "a_partir_de", "sob_consulta")
PRECO_TIPOS_COM_NUMERO: Final = frozenset({"fixo", "a_partir_de"})
STOCK_MODOS: Final = ("garantido", "indicativo", "confirmar_dono")
STOCK_MODOS_COM_NUMERO: Final = frozenset({"garantido", "indicativo"})

#: Os campos criticos (§8.3): perguntam-se sozinhos.
CRITICOS: Final = ("preco_tipo", "preco", "stock_modo", "stock")

#: A ordem das perguntas, por impacto na venda. O `preco_tipo` e o primeiro.
ORDEM: Final = (
    "preco_tipo",
    "preco",
    "stock_modo",
    "stock",
    "nome",
    "categoria",
    "variantes",
    "marca",
    "entrega",
    "garantia",
    "duracao",
    "local",
    "pre_aviso",
)

_BASE: Final = ("nome", "categoria", "preco_tipo", "preco")
_COM_STOCK: Final = (*_BASE, "stock_modo", "stock", "entrega")

PERFIS: Final[Mapping[str, tuple[str, ...]]] = {
    "geral": _COM_STOCK,
    "vestuario": (*_COM_STOCK, "variantes"),
    "alimentar": (*_COM_STOCK, "variantes"),
    "electronica": (*_COM_STOCK, "variantes", "marca", "garantia"),
    "servico": (*_BASE, "duracao", "local", "pre_aviso"),
}

#: Palavras da categoria -> perfil. *Proposta*.
_PALAVRAS_DO_PERFIL: Final[Mapping[str, frozenset[str]]] = {
    "vestuario": frozenset(
        "vestuario roupa roupas moda calcado calcados sapato sapatos sapatilha sapatilhas "
        "camisa camisas vestido vestidos calcas saia blusa".split()
    ),
    "alimentar": frozenset(
        "alimentar alimentacao alimento alimentos comida mercearia bebida bebidas sumo "
        "sumos arroz oleo farinha".split()
    ),
    "electronica": frozenset(
        "electronica eletronica electronicos telemovel telemoveis telefone portatil "
        "computador televisor tv electrodomestico electrodomesticos".split()
    ),
    "servico": frozenset("servico servicos".split()),
}

#: O texto de cada pergunta. Fixo: nao leva texto da foto. A sugestao vai a
#: parte, em `Pergunta.sugestao`, para quem compoe a mensagem a mostrar como
#: dado e nao como instrucao.
TEXTOS: Final[Mapping[str, str]] = {
    "preco_tipo": "O preco e fixo, «a partir de», ou sob consulta?",
    "preco": "Qual e o preco, em Kz?",
    "stock_modo": "O stock e garantido, indicativo, ou confirmas a cada pedido?",
    "stock": "Quantas unidades tens?",
    "nome": "Como se chama o produto?",
    "categoria": "Em que categoria esta?",
    "variantes": "Que variantes ha (tamanho, cor, sabor, modelo)?",
    "marca": "Qual e a marca?",
    "entrega": "Fazes entrega, levantamento, ou os dois?",
    "garantia": "Tem garantia? Quanto tempo?",
    "duracao": "Quanto tempo dura o servico?",
    "local": "Onde se faz o servico?",
    "pre_aviso": "Com quanta antecedencia se marca?",
}


@dataclass(frozen=True)
class Pergunta:
    """Uma pergunta ao dono. `sugestao` e o valor da foto, quando ha."""

    campo: str
    texto: str
    critica: bool
    sugestao: str | None = None


def perfil_da_categoria(categoria: str | None) -> str:
    """O perfil de completude de uma categoria; `geral` se nenhum a reconhece."""
    if not categoria:
        return "geral"
    palavras = set(passo_1(categoria))
    for perfil, conhecidas in _PALAVRAS_DO_PERFIL.items():
        if palavras & conhecidas:
            return perfil
    return "geral"


def _valor(campos: Mapping[str, Campo], nome: str) -> str | None:
    campo = campos.get(nome)
    if campo is None or campo.abaixo_do_limiar or not isinstance(campo.valor, str):
        return None
    return campo.valor


def campos_em_falta(campos: Mapping[str, Campo], perfil: str) -> tuple[str, ...]:
    """Os campos do perfil por preencher, pela `ORDEM`.

    Um campo `ia_visao` abaixo do limiar conta como em falta: e perguntado.
    """
    exigidos = set(PERFIS[perfil])
    if _valor(campos, "preco_tipo") not in PRECO_TIPOS_COM_NUMERO and _valor(campos, "preco_tipo") is not None:
        exigidos.discard("preco")
    modo = _valor(campos, "stock_modo")
    if modo is not None and modo not in STOCK_MODOS_COM_NUMERO:
        exigidos.discard("stock")
    falta = []
    for nome in ORDEM:
        if nome not in exigidos:
            continue
        campo = campos.get(nome)
        if campo is None or campo.abaixo_do_limiar:
            falta.append(nome)
    return tuple(falta)


def proximas_perguntas(
    campos: Mapping[str, Campo],
    perfil: str,
    perguntas_feitas: int,
    *,
    preco_sugerido: str | None = None,
) -> tuple[Pergunta, ...]:
    """As perguntas da proxima mensagem: ate tres, ou um critico sozinho."""
    restantes = MAXIMO_DE_PERGUNTAS - perguntas_feitas
    if restantes <= 0:
        return ()
    falta = campos_em_falta(campos, perfil)
    if not falta:
        return ()

    def pergunta(nome: str) -> Pergunta:
        campo = campos.get(nome)
        sugestao: str | None = None
        if nome == "preco" and preco_sugerido:
            sugestao = preco_sugerido
        elif campo is not None and campo.abaixo_do_limiar:
            sugestao = campo.valor if isinstance(campo.valor, str) else ", ".join(campo.valor)
        return Pergunta(campo=nome, texto=TEXTOS[nome], critica=nome in CRITICOS, sugestao=sugestao)

    primeiro = falta[0]
    if primeiro in CRITICOS:
        return (pergunta(primeiro),)
    leves = [nome for nome in falta if nome not in CRITICOS]
    return tuple(pergunta(nome) for nome in leves[: min(MAXIMO_POR_MENSAGEM, restantes)])
