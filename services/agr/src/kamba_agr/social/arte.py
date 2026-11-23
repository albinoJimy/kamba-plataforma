"""O compositor das artes do social (KAM-122, criterios 1 e 2): o texto e do codigo.

    dados_da_arte(perfil, item, dia)            -> DadosDaArte, so dos factos validos
    compor(dados, template, formato)            -> Composicao, as linhas exactas
    texto_composto(composicao)                  -> a cadeia que vai a arte

Pelo `E5` (§2), o modelo de imagem gera **so o fundo**, e o texto da arte — o
nome, o preco em Kz e os contactos — **e composto por codigo**: nao ha *benchmark*
de texto em portugues gerado por modelos (NAO VERIFICADO), e um modelo que
escreve «12.5OO Kz» numa arte e um preco inventado.

## De onde vem cada linha

| Linha | Fonte |
|---|---|
| nome | `brand_profile.nome` |
| destaque | o facto do item: a promocao valida num item `promocao`, o primeiro facto com preco num `produto`; sem o valor |
| preco | o valor desse facto, lido pelo `para_centimos` do validador (KAM-032), em «12.500 Kz» |
| contactos | os telefones dos factos validos, em grupos de tres |

**Nada vem do tema, da legenda nem de uma instrucao do dono.** E no fim a guarda
de numeros do KAM-121 corre sobre o texto composto contra os factos: um numero
que nenhum facto tem (algarismos **e** unidade) recusa a arte (criterio 2).

## O formato do preco

«12.500 Kz», com o ponto, e «12.500,50 Kz» com centimos: e a letra do bloco e a
do dicionario §1 («Apresentacao ao cliente»). O `kz_display` do validador usa o
espaco («12 500 Kz», §3.40), porque o que ele escreve volta a entrar pelo
extractor; o que esta aqui vai para uma imagem e nao volta. A divergencia entre
o §1 e o §3.40 e anterior a este ticket e fica escrita no bloco.

## Os *templates* e os formatos (*proposta*)

Tres por tipo de negocio, em codigo, nos dois formatos do bloco (1080 x 1080 e
1080 x 1350). O tipo de negocio sai da categoria do perfil por palavras; sem
casar, e `produtos`. Cada *template* diz o fundo (liso ou gradiente, nas cores
do perfil), as caixas de texto e a largura em caracteres de cada uma. Desenhar
os pixeis e da porta `Renderizador`.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from ..validador.normalizacao import NaoEDinheiroError, para_centimos
from .numeros import numeros_fora_dos_factos
from .regras import Facto, Perfil, sem_acentos

CENTIMOS_POR_KZ: Final = 100

#: Os dois formatos do bloco (*proposta*), em pixeis.
FORMATOS: Final = {"quadrado": (1080, 1080), "retrato": (1080, 1350)}

#: Os tipos de negocio e as palavras da categoria que os escolhem (*proposta*).
TIPOS_DE_NEGOCIO: Final = {
    "alimentacao": ("comida", "restaura", "bolo", "doce", "docaria", "pastel", "padaria", "lanche", "bebida", "sumo", "churrasc", "catering", "mercearia", "fruta"),
    "servicos": ("servico", "salao", "cabeleir", "barbear", "estetica", "unha", "reparac", "oficina", "lavand", "costura", "explicac", "aulas", "transporte", "limpeza", "fotografia"),
    "produtos": (),
}
TIPO_POR_OMISSAO: Final = "produtos"

LINHAS_DO_NOME: Final = 2
LINHAS_DO_DESTAQUE: Final = 3
MAXIMO_DE_CONTACTOS: Final = 2


class Recusa(ValueError):
    """A arte nao se compoe; o `motivo` e um codigo, nunca o texto."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Template:
    template_id: str
    tipo_de_negocio: str
    fundo: str  # "liso" ou "gradiente"
    #: Caracteres por linha de cada papel, no formato quadrado; o retrato tem mais altura e a mesma largura.
    largura_do_nome: int
    largura_do_destaque: int
    alinhamento: str  # "centro" ou "esquerda"


def _tres(tipo: str) -> tuple[Template, ...]:
    return (
        Template(f"{tipo}_destaque", tipo, "gradiente", 18, 26, "centro"),
        Template(f"{tipo}_faixa", tipo, "liso", 22, 30, "esquerda"),
        Template(f"{tipo}_cartaz", tipo, "gradiente", 16, 24, "centro"),
    )


#: Os *templates*: tres por tipo de negocio (*proposta*; o bloco pede 3 a 5).
TEMPLATES: Final = {t.template_id: t for tipo in TIPOS_DE_NEGOCIO for t in _tres(tipo)}


def templates_do_tipo(tipo: str) -> tuple[Template, ...]:
    return tuple(t for t in TEMPLATES.values() if t.tipo_de_negocio == tipo)


def tipo_de_negocio(categoria: str | None) -> str:
    """O tipo de negocio de uma categoria do perfil, pelas palavras; `produtos` por omissao."""
    limpo = sem_acentos(categoria or "")
    for tipo, palavras in TIPOS_DE_NEGOCIO.items():
        if any(p in limpo for p in palavras):
            return tipo
    return TIPO_POR_OMISSAO


# ------------------------------------------------------------------ o preco e os telefones


def formatar_kz(centimos: int) -> str:
    """Centimos -> «12.500 Kz», ou «12.500,50 Kz» com centimos. Nunca negativo."""
    if centimos < 0:
        raise ValueError("dinheiro negativo nao se apresenta")
    inteiro, resto = divmod(centimos, CENTIMOS_POR_KZ)
    grupos = f"{inteiro:,}".replace(",", ".")
    return f"{grupos},{resto:02d} Kz" if resto else f"{grupos} Kz"


#: Um valor em Kz num facto: algarismos com separadores e a marca da moeda.
_VALOR_EM_KZ: Final = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(kz|kwanzas?|aoa)\b",
    re.IGNORECASE,
)
#: Um telefone angolano num facto: nove algarismos a comecar por 9, com ou sem espacos.
_TELEFONE: Final = re.compile(r"(?<!\d)(?:\+?244\s?)?(9\d{2})\s?(\d{3})\s?(\d{3})(?!\d)")


def preco_do_facto(texto: str) -> tuple[int, tuple[int, int]] | None:
    """`(centimos, (inicio, fim))` do primeiro valor em Kz do facto, ou `None`."""
    for casado in _VALOR_EM_KZ.finditer(texto):
        try:
            return para_centimos(casado.group(0)), casado.span()
        except (NaoEDinheiroError, ValueError):
            continue
    return None


def formatar_telefone(texto: str) -> str | None:
    """«999123456» -> «999 123 456». So o numero nacional, sem o indicativo."""
    casado = _TELEFONE.search(texto)
    return " ".join(casado.groups()) if casado else None


#: O espaco que une as partes de um valor ou de um telefone, para a quebra de
#: linha nao os partir. Sai como espaco normal na linha composta.
_UNE: Final = "\u00a0"
_PERCENTAGEM: Final = re.compile(r"\d+(?:[.,]\d+)?\s*%")


def normalizar_valores(texto: str) -> str:
    """Os valores em Kz no formato da arte e os telefones em grupos, **indivisiveis**.

    «Desconto de 5000 kwanzas» -> «Desconto de 5.000 Kz»; «999123456» ->
    «999 123 456». O texto do dono fica como esta; so a forma dos numeros muda,
    e os algarismos sao os mesmos (a guarda compara-os sem separadores).
    """

    def valor(casado: re.Match[str]) -> str:
        try:
            return formatar_kz(para_centimos(casado.group(0))).replace(" ", _UNE)
        except (NaoEDinheiroError, ValueError):
            return casado.group(0)

    com_valores = _VALOR_EM_KZ.sub(valor, " ".join(texto.split()))
    return _TELEFONE.sub(lambda c: _UNE.join(c.groups()), com_valores)


# ------------------------------------------------------------------ os dados


@dataclass(frozen=True)
class DadosDaArte:
    nome: str
    destaque: str | None = None
    preco_minor: int | None = None
    contactos: tuple[str, ...] = ()


def _sem_o_valor(texto: str, intervalo: tuple[int, int]) -> str:
    """O facto sem o valor e sem o conector **logo antes dele**.

    «Camisas a 8.000 Kz» -> «Camisas»; «Sumos por 500 Kz cada» -> «Sumos cada»;
    «Bolo de chocolate a 12.500 Kz» -> «Bolo de chocolate» (o «de» do meio fica).
    """
    inicio, fim = intervalo
    antes = re.sub(r"(?:\s+(?:a|por)|\s*[:\-—])\s*$", "", texto[:inicio].rstrip(), flags=re.IGNORECASE)
    return " ".join(f"{antes} {texto[fim:]}".split()).strip(" :-—,")


def dados_da_arte(perfil: Perfil, tipo_do_item: str, dia: datetime.date) -> DadosDaArte:
    """Os dados da arte de um item, **so** dos factos do dono validos no `dia`."""
    if perfil.nome is None:
        raise Recusa("perfil_incompleto")
    factos = perfil.factos_validos(dia)
    escolhido: Facto | None = None
    if tipo_do_item == "promocao":
        escolhido = next((f for f in factos if f.promocao), None)
        if escolhido is None:
            raise Recusa("faltam_factos")
    elif tipo_do_item == "produto":
        escolhido = next((f for f in factos if not f.promocao and preco_do_facto(f.texto)), None)
    destaque, preco = None, None
    if escolhido is not None and escolhido.promocao:
        # A promocao vai inteira, com os valores normalizados: o valor de uma
        # promocao pode ser o desconto («desconto de 5.000 Kz»), e nao o preco.
        destaque = normalizar_valores(escolhido.texto)
    elif escolhido is not None:
        lido = preco_do_facto(escolhido.texto)
        assert lido is not None  # escolhido por ter preco
        preco = lido[0]
        destaque = normalizar_valores(_sem_o_valor(escolhido.texto, lido[1])) or None
    contactos: list[str] = []
    for facto in factos:
        telefone = formatar_telefone(facto.texto)
        if telefone and telefone not in contactos:
            contactos.append(telefone)
    return DadosDaArte(perfil.nome, destaque, preco, tuple(contactos[:MAXIMO_DE_CONTACTOS]))


# ------------------------------------------------------------------ a composicao


@dataclass(frozen=True)
class Linha:
    papel: str  # "nome", "destaque", "preco", "contacto"
    texto: str


@dataclass(frozen=True)
class Composicao:
    template: Template
    formato: str
    linhas: tuple[Linha, ...]

    @property
    def dimensoes(self) -> tuple[int, int]:
        return FORMATOS[self.formato]


def quebrar(texto: str, largura: int, maximo_de_linhas: int) -> tuple[str, ...]:
    """Quebra por palavra; uma palavra maior do que a largura fica inteira numa linha.

    **Nunca parte um valor nem um telefone**: o `normalizar_valores` uniu-os
    com um espaco indivisivel, e a quebra so corta no espaco normal. Mais linhas
    do que o maximo e recusa, e nao corte: uma arte com o nome cortado e uma
    arte errada.
    """
    linhas: list[str] = []
    for palavra in texto.split(" "):
        if not palavra:
            continue
        if linhas and len(linhas[-1]) + 1 + len(palavra) <= largura:
            linhas[-1] = f"{linhas[-1]} {palavra}"
        else:
            linhas.append(palavra)
    if len(linhas) > maximo_de_linhas:
        raise Recusa("texto_nao_cabe")
    return tuple(linha.replace(_UNE, " ") for linha in linhas)


def compor(dados: DadosDaArte, template: Template, formato: str) -> Composicao:
    if formato not in FORMATOS:
        raise Recusa("formato_desconhecido")
    linhas = [Linha("nome", t) for t in quebrar(dados.nome, template.largura_do_nome, LINHAS_DO_NOME)]
    if dados.destaque:
        linhas += [
            Linha("destaque", t) for t in quebrar(dados.destaque, template.largura_do_destaque, LINHAS_DO_DESTAQUE)
        ]
    if dados.preco_minor is not None:
        linhas.append(Linha("preco", formatar_kz(dados.preco_minor)))
    linhas += [Linha("contacto", c) for c in dados.contactos]
    return Composicao(template, formato, tuple(linhas))


def texto_composto(composicao: Composicao) -> str:
    """A cadeia que vai a arte: as linhas, uma por linha."""
    return "\n".join(linha.texto for linha in composicao.linhas)


def verificar_numeros(composicao: Composicao, factos: Sequence[Facto], nome: str) -> None:
    """A guarda de numeros do KAM-121 sobre o texto composto (criterio 2).

    Um numero que nenhum facto valido nem o nome da marca tem (os mesmos
    algarismos **e** a mesma unidade) recusa a arte com `faltam_factos`.
    """
    # Cada facto entra como o dono o escreveu **e** na forma da arte: «1.500,00 Kz»
    # sai «1.500 Kz» e «+244 999 432 100» sai «999 432 100», e os algarismos
    # mudam. A forma da arte e derivada do facto, e nao abre a porta a outro numero.
    # **O nome so cobre o que nao e dinheiro**: «Tudo a 2.500 Kz» como nome da
    # marca punha um preco na arte sem facto nenhum (achado 7 da revisao). Os
    # valores em Kz e as percentagens saem do nome antes de ele servir de fonte.
    nome_sem_dinheiro = _PERCENTAGEM.sub(" ", _VALOR_EM_KZ.sub(" ", nome))
    fontes = [f.texto for f in factos] + [normalizar_valores(f.texto).replace(_UNE, " ") for f in factos] + [nome_sem_dinheiro]
    # **Linha a linha**: a guarda junta algarismos separados por um espaco antes
    # de um grupo de tres, e a quebra de linha e um espaco — «30/12» e um
    # telefone na linha seguinte liam-se como um so numero, que nenhum facto tem.
    for linha in composicao.linhas:
        if numeros_fora_dos_factos(linha.texto, fontes):
            raise Recusa("faltam_factos")


# ------------------------------------------------------------------ a porta do desenho


class Renderizador(Protocol):
    """Desenha a composicao num JPEG sem metadados de captura (criterio 4).

    O fundo e do *template* (liso ou gradiente, nas cores do perfil); o texto e o
    da composicao, letra a letra. Devolve os bytes do JPEG.
    """

    def desenhar(self, composicao: Composicao, cores: Sequence[str]) -> bytes: ...
