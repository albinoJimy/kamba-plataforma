"""Os dicionarios do detector: locais de Luanda, nomes proprios e digitos por extenso.

**A origem destes dicionarios e NAO VERIFICADA, e o bloco do KAM-112 di-lo pelo
nome:** «a origem dos dicionarios e NAO VERIFICADA (sem lista oficial):
constroem-se a partir do catalogo e de fontes abertas, como *proposta*». Nao ha
lista oficial de bairros de Luanda lida de fonte primaria neste repositorio — nao
existe ficheiro nenhum com ela, medido — pelo que o que esta aqui e conhecimento
geral escrito a mao e **calibra-se no Piloto** (KAM-109), contra as moradas que os
clientes reais escreverem.

O que isto significa para quem le o recall: um bairro que nao esteja nesta lista
**nao e detectado por dicionario**, e sobra-lhe o padrao de contexto
(«entregar em», «perto do»). E por isso que o limiar de moradas e 90% e nao 99%,
e o limiar e ele proprio *proposta*.

## Zero dados reais, e e um requisito e nao uma precaucao

Os Termos da Meta §4.7 proibem usar dados da plataforma para treinar ou melhorar
ML (ADR-018, `docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §4). Um dicionario
construido a partir de conversas de clientes era exactamente isso. Nada aqui vem
de uma conversa: sao toponimos publicos e nomes proprios comuns.

## Os nomes proprios sao a lista mais perigosa dos tres, e nao e por falhar

E por **acertar onde nao devia**. «Rosa», «Gloria», «Esperanca» e «Vitoria» sao
nomes de pessoa **e** palavras comuns; «Benfica» e «Alvalade» sao bairros de
Luanda **e** nomes de clubes; e o catalogo de um *tenant* pode ter um produto
chamado «Maria» (uma marca de bolachas existe com esse nome em Portugal). Dai as
duas barreiras que o `detector.py` poe por cima desta lista:

1. um nome so vira `PESSOA_n` quando aparece **capitalizado** e com um padrao de
   contexto de pessoa por perto, ou quando vem em par (nome + apelido);
2. um nome que esteja no catalogo do *tenant* **nunca** se mascara (criterio 5,
   `catalogo.py`).

A segunda e a que o criterio 5 pede e a que hoje so cobre o nome da loja; a
primeira e inteiramente nossa, e e o que impede «vendem agua da Rosa?» de virar
«vendem agua da PESSOA_1?».
"""

from __future__ import annotations

import unicodedata
from typing import Final

#: Os municipios da provincia de Luanda. **Conhecimento geral, NAO VERIFICADO**:
#: a divisao administrativa de Angola mudou em 2024 e nao ha aqui fonte primaria
#: lida. Entram em minusculas e sem acentos — a comparacao faz-se sobre a forma
#: normalizada (`dobrar`), porque um cliente escreve «Viana» e «viana» e
#: «Kilamba Kiaxi» e «kilamba kiaxi».
MUNICIPIOS: Final = (
    "belas",
    "cacuaco",
    "cazenga",
    "icolo e bengo",
    "kilamba kiaxi",
    "luanda",
    "quicama",
    "talatona",
    "viana",
)

#: Bairros e zonas de Luanda. **Conhecimento geral, NAO VERIFICADO**, e a lista
#: e deliberadamente curta: um bairro a mais que seja tambem palavra comum custa
#: um falso positivo numa morada que nao era morada, e o criterio 4 nao perdoa
#: falsos positivos sobre numeros mas tambem nao se ganha nada em mascarar
#: «centro» ou «praia».
#:
#: Os que sao **tambem nomes de clubes ou palavras comuns** ficam, porque num
#: contexto de morada sao morada: o que os protege de mascarar o que nao e
#: morada e a exigencia de contexto do `detector.py`, nao a ausencia da lista.
BAIRROS: Final = (
    "alvalade",
    "bairro operario",
    "benfica",
    "cacuaco",
    "camama",
    "cassenda",
    "catambor",
    "corimba",
    "futungo",
    "gamek",
    "golfe",
    "hoji ya henda",
    "ingombota",
    "kilamba",
    "maculusso",
    "maianga",
    "marginal",
    "miramar",
    "morro bento",
    "mussulo",
    "mutamba",
    "nova vida",
    "palanca",
    "patriota",
    "petrangol",
    "prenda",
    "rangel",
    "rocha pinto",
    "samba",
    "sambizanga",
    "terra nova",
    "vila alice",
    "zango",
)

#: Os dois juntos, que e o que o detector percorre. Ordenados por comprimento
#: **decrescente**: «bairro operario» tem de casar antes de «operario» ficar
#: orfao, e «nova vida» antes de «vida». Um detector que percorresse por ordem
#: alfabetica cortava o topónimo composto ao meio.
LOCAIS: Final = tuple(
    sorted({*MUNICIPIOS, *BAIRROS}, key=lambda nome: (-len(nome), nome))
)

#: Nomes proprios comuns em Angola e em Portugal. **Conhecimento geral, NAO
#: VERIFICADO e *proposta*.** Em minusculas e sem acentos, como os locais.
#:
#: A lista inclui nomes de origem bantu (`nzinga`, `kiala`, `lueji`) porque uma
#: lista so com nomes de origem portuguesa dava um recall sistematicamente mais
#: baixo para clientes angolanos — que e a populacao inteira do produto. E uma
#: lacuna que se calibra no Piloto, nao uma que se finja fechada.
NOMES_PROPRIOS: Final = (
    "alberto", "alexandre", "ana", "andre", "antonio", "augusto", "beatriz",
    "benedito", "bento", "carlos", "catarina", "celestino", "clara", "daniel",
    "domingos", "eduardo", "elias", "emanuel", "esperanca", "felicidade",
    "fernando", "filipe", "francisco", "gabriel", "gloria", "helena", "isabel",
    "joana", "joao", "joaquim", "jose", "kiala", "kudi", "lucas", "lueji",
    "luis", "manuel", "marcos", "maria", "mateus", "mbala", "miguel", "ndala",
    "nzinga", "paulo", "pedro", "rafael", "rosa", "samuel", "simao", "sofia",
    "tchize", "teresa", "tomas", "vitoria",
)

#: Apelidos comuns. Separados dos nomes proprios porque a regra de par —
#: «nome + apelido vira `PESSOA_n` sem precisar de contexto» — precisa de saber
#: qual e qual: «Maria Joao» sao dois nomes proprios e nao e mais pessoa do que
#: «Maria» sozinha, mas «Maria Gourgel» e um nome completo.
APELIDOS: Final = (
    "alves", "bengui", "chicoti", "correia", "costa", "dias", "domingos",
    "fernandes", "ferreira", "gomes", "goncalves", "gourgel", "kiluanje",
    "lopes", "martins", "matos", "mendes", "miguel", "monteiro", "neto",
    "nunes", "oliveira", "pereira", "pinto", "ribeiro", "rodrigues", "santos",
    "silva", "soares", "sousa", "van-dunem",
)

#: Os digitos por extenso, que o criterio 2 nomeia («por extenso»). Cada chave e
#: a forma **normalizada** (minusculas, sem acentos).
#:
#: **O `zero` nao e o unico nome do zero**: entra tambem `o` nenhum — nao, nao
#: entra. Um «o» a contar como zero fazia qualquer frase portuguesa parecer um
#: numero. O que entra sao as formas que alguem escreve ao ditar um telefone.
DIGITOS_POR_EXTENSO: Final = {
    "zero": "0",
    "um": "1",
    "uma": "1",
    "dois": "2",
    "duas": "2",
    "tres": "3",
    "quatro": "4",
    "cinco": "5",
    "seis": "6",
    "meia": "6",
    "sete": "7",
    "oito": "8",
    "nove": "9",
}

#: Palavras de contexto que indicam **morada ou local** a seguir. O bloco
#: nomeia-as («entregar em», «perto do»).
CONTEXTO_DE_LOCAL: Final = (
    "entregar em",
    "entrega em",
    "entregar no",
    "entregar na",
    "entrega no",
    "entrega na",
    "moro em",
    "moro no",
    "moro na",
    "vivo em",
    "vivo no",
    "vivo na",
    "perto do",
    "perto da",
    "perto de",
    "ao lado do",
    "ao lado da",
    "em frente do",
    "em frente da",
    "rua ",
    "avenida ",
    "av. ",
    "largo ",
    "praca ",
    "travessa ",
    "bairro ",
    "predio ",
    "casa n",
    "morada ",
    "endereco ",
    "zona ",
)

#: Gatilhos de pessoa **fortes**: o que vem depois e uma pessoa, esteja ou nao
#: no dicionario.
#:
#: **A separacao entre fortes e fracos e a correccao do achado 9 da revisao
#: adversarial**, que mediu o recall de `PESSOA` e de `MORADA` a ser uma
#: tautologia: o corpus nao tinha **um unico** nome fora de `NOMES_PROPRIOS` nem
#: um unico toponimo fora de `LOCAIS`, pelo que o limiar de 90% media que o
#: dicionario contem as suas proprias entradas.
#:
#: Pôr nomes de fora no corpus obrigava a esta via, que e a simetrica da que o
#: `_locais` ja tinha: um gatilho forte **basta**, e e o unico mecanismo que
#: apanha um nome que a lista nao tem. Sem ela, acrescentar casos honestos ao
#: corpus so fazia o limiar falhar — isto e, media-se melhor e detectava-se
#: igual.
#:
#: São **fortes** estes e nao outros: cada um nomeia uma pessoa de forma
#: inequivoca. O custo e mascarar um papel («fala com o Gerente» -> `PESSOA_1`),
#: que e barato e do lado certo.
CONTEXTO_DE_PESSOA_FORTE: Final = (
    "fala com",
    "falar com",
    "falei com",
    "pergunta ao",
    "pergunta a",
    "o senhor",
    "a senhora",
    "sr.",
    "sra.",
    "dona ",
    "doutor",
    "doutora",
    "dr.",
    "dra.",
    "meu nome e",
    "chamo-me",
    "diz ao",
    "diz a",
    "entregar ao",
    "pedido e para a",
    "pedido e para o",
)

#: Gatilhos **fracos**: so mascaram o que esta no dicionario.
#:
#: «com o», «para a» e «sou o» aparecem em texto portugues a toda a hora («com o
#: desconto», «para a loja»), e um gatilho forte feito deles mascarava qualquer
#: palavra capitalizada a seguir — que e o defeito que a nota do `_pessoas`
#: descreve («Tenho Interesse Naquele Produto» com quatro `PESSOA_n`).
CONTEXTO_DE_PESSOA_FRACO: Final = (
    "sou o",
    "sou a",
    "para o",
    "para a",
    "com o",
    "com a",
    "entregar a",
)

#: Os dois juntos, para quem precise de saber se **ha** contexto de pessoa.
CONTEXTO_DE_PESSOA: Final = (
    *CONTEXTO_DE_PESSOA_FORTE,
    *CONTEXTO_DE_PESSOA_FRACO,
)


def dobrar(texto: str) -> str:
    """A forma normalizada em que as comparacoes deste modulo se fazem.

    Minusculas, sem acentos e com os digitos Unicode reduzidos a ASCII. **O
    comprimento tem de se preservar caracter a caracter**, e e a propriedade que
    faz isto servir para procurar posicoes: o detector encontra uma ocorrencia na
    forma dobrada e mascara o intervalo **no texto original**, pelo que um
    normalizador que encolhesse o texto (um `NFKD` que parta «a» em dois pontos
    de codigo, um `casefold` que transforme «ß» em «ss») dava intervalos
    deslocados e mascarava o caracter errado.

    Por isso:

    * decompoe-se com `NFD` e **descartam-se as marcas** (`Mn`), que e o que tira
      o acento sem mexer na letra de base — e cada letra de base ocupa uma
      posicao, como ocupava antes;
    * usa-se `lower()` e nao `casefold()`, porque o `casefold` do «ß» tem dois
      caracteres;
    * os digitos Unicode trocam-se **um por um** pelo seu valor ASCII.

    Ha um teste que exige `len(dobrar(t)) == len(t)` sobre o corpus inteiro: e a
    unica forma de isto se manter verdadeiro quando alguem acrescentar um caso.
    """
    saida: list[str] = []
    for caracter in texto:
        decomposto = unicodedata.normalize("NFD", caracter)
        # As marcas combinatorias saem; o que sobra e a letra de base. Quando a
        # decomposicao da mais do que uma letra de base (nao acontece em
        # portugues, mas acontece em ligaduras), fica **a primeira** — porque o
        # que nao se pode perder e a contagem de posicoes.
        base = "".join(parte for parte in decomposto if not unicodedata.combining(parte))
        if not base:
            # Um caracter que **e** so uma marca combinatoria (um acento solto).
            # Nao se pode descartar: isso encolhia o texto. Fica como estava.
            saida.append(caracter)
            continue
        letra = base[0].lower()
        if letra.isdigit():
            # `unicodedata.digit` resolve os digitos Unicode do criterio 2
            # (arabes-indicos, devanagari, de largura total) sem tabela nossa.
            #
            # **O `except` e defensivo e nao se consegue alcancar por aqui, e
            # isso esta medido e nao suposto.** Em CPython, `str.isdigit()` e
            # verdadeiro exactamente para os caracteres que tem valor decimal ou
            # de digito, e para esses o `unicodedata.digit` responde: medi
            # `²` (isdigit, digit=2), `①` (isdigit, digit=1) e `٣` (isdigit,
            # digit=3); os que levantam — `½` e `Ⅻ` — **nao** passam o
            # `isdigit()` e nunca chegam aqui.
            #
            # Fica porque o custo de o tirar nao e zero: a relacao entre os dois
            # e detalhe de implementacao do CPython, nao contrato, e uma
            # excepcao aqui **nao** da um `dobrar` errado — da uma
            # `FalhaDeMinimizacao`, isto e, um turno degradado por um metro
            # quadrado numa mensagem. Retirar uma barreira nunca e o minimo.
            try:
                letra = str(unicodedata.digit(letra))
            except ValueError:  # pragma: no cover — ver a nota acima
                pass
        saida.append(letra)
    return "".join(saida)
