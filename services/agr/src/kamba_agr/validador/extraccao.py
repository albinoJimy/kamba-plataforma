"""O extractor PT-AO: texto -> numeros classificados (`docs/tecnica/02` §9.1).

O pseudocodigo do §9.1 chama-lhe `extract(text)` e pede cinco classes —
«dinheiro, quantidades, percentagens, SKUs, datas/horas, numeros por extenso
(pt)». Este modulo e isso, e a parte dificil **nao** e encontrar digitos: e
decidir o que cada numero **e**, porque o veredicto depende da classe.

## A ordem de classificacao e a decisao mais importante do ficheiro

Um `10%` lido como dinheiro nunca daria `discount_unbacked`; um `14/11` lido
como dois numeros nunca daria `datetime_unbacked`. A ordem e, por isso, da
classe mais marcada para a menos marcada:

    percentagem -> data/hora -> dinheiro -> quantidade -> outro

e `outro` e o saco de onde sai o `number_unbacked`: tudo o que nao se reconheceu
cai la e **tem de estar em `allowed_literals`**. E *fail-closed* por construcao,
que e o que o ADR-007 pede — um numero que o extractor nao entende e um numero
que o validador recusa, e nao um numero que passa.

## «um» e um artigo, e isto custou a regra mais chata daqui

Um numero por extenso reconhece-se pelas palavras, e `um`/`uma` sao as mais
comuns da lingua. Um extractor que leia «um produto» como o numero 1 poe
`number_unbacked` em metade das respostas legitimas. Uma sequencia de palavras
so conta como numero se:

* tiver uma palavra de escala (`mil`, `milhao`, `cem`, `duzentos`, …); **ou**
* tiver duas ou mais palavras de numero (`vinte e cinco`); **ou**
* vier imediatamente seguida de marca de moeda ou de palavra de contagem.

Fora disso, `um` e artigo: «encontrei **um** produto para si» nao tem numero
nenhum, e «tenho **um** em stock» tem — porque o `em stock` o reclama.

**O limite que fica e so o `um`/`uma`, e esta medido.** «Levo dois» extrai-se
(da `number_unbacked`); «Levo um» **nao**, porque a unica forma de o distinguir
de «levo um produto» era entender a frase. Uma quantidade de 1 escrita por
extenso e sem palavra de contagem passa sem `fact` — falso aceite real, da
familia «numeros por extenso, formatos regionais, abreviaturas» do §9.2, no
conjunto adversarial com o nome `limite:artigo_um_sem_contexto`. Esta nos casos
que **documentam** o limite e nao nos que o gate conta como 0 falsos aceites.

O custo deste limite e pequeno por uma razao que vale dizer: o que ele deixa
passar e a quantidade **1**, e um pedido de uma unidade e o que o `propose_cart`
confirma com um total que **e** *fact*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .normalizacao import (
    MARCAS_DE_KZ,
    MULTIPLICADORES,
    MoedaEstrangeiraError,
    NaoEDinheiroError,
    PALAVRAS_DE_NUMERO,
    para_centimos,
    sem_acento,
)

#: As classes de um numero extraido. Lista **fechada**: cada uma mapeia num
#: veredicto do §3.30, e uma classe nova sem veredicto era um numero sem regra.
CLASSES: Final = ("dinheiro", "percentagem", "datahora", "quantidade", "outro")

#: Marcas de moeda em texto corrido, de qualquer dos lados do numero.
_KZ: Final = r"(?:Kz|KZ|kz|AOA|kwanzas?|Kwanzas?)"

#: Um grupo de digitos PT-AO. A primeira alternativa apanha os separadores de
#: milhares (`12.500`, `12 500`, `12,500`, `12.500,00`); a segunda o decimal
#: simples (`12,5`); a terceira o inteiro nu.
_DIGITOS: Final = r"\d{1,3}(?:[ .,]\d{3})+(?:,\d{1,2})?|\d+,\d{1,2}|\d+"

#: Palavras de escala: a presenca de uma delas faz de uma sequencia um numero.
_ESCALAS: Final = frozenset(
    set(MULTIPLICADORES)
    | {
        "cem", "cento", "duzentos", "duzentas", "trezentos", "trezentas",
        "quatrocentos", "quatrocentas", "quinhentos", "quinhentas",
        "seiscentos", "seiscentas", "setecentos", "setecentas",
        "oitocentos", "oitocentas", "novecentos", "novecentas",
        "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
        "oitenta", "noventa",
    }
)

#: `um`/`uma` isolados sao artigos (ver o cabecalho).
_ARTIGOS: Final = frozenset({"um", "uma"})

#: Palavras que fazem de um numero uma **quantidade**. Nao e uma lista de tudo o
#: que se conta: e a lista do que o Piloto vende e marca, e o que ficar fora cai
#: em `outro`, isto e, em `number_unbacked` — *fail-closed*.
PALAVRAS_DE_CONTAGEM: Final = (
    "unidade", "unidades", "peca", "pecas", "caixa", "caixas", "pares", "par",
    "em stock", "disponivel", "disponiveis", "restam", "resta", "temos",
    "quantidade", "exemplar", "exemplares", "litro", "litros", "kg", "metros",
)

#: Uma percentagem: `10%`, `10 %`, `10 por cento`.
_PERCENTAGEM: Final = re.compile(
    rf"(?P<n>{_DIGITOS})\s*(?:%|por\s+cento)", re.IGNORECASE
)

#: Uma data ou uma hora. Cobre `14/11`, `14/11/2026`, `14-11-2026`, `2026-11-14`,
#: `14h`, `14h30`, `14:30`, e `14 de Novembro`.
_DATAHORA: Final = re.compile(
    r"\b(?:"
    r"\d{4}-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?"
    r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
    r"|\d{1,2}\s*[:h]\s*\d{2}"
    r"|\d{1,2}\s*h\b"
    r"|\d{1,2}\s+de\s+[A-Za-zÀ-ÿ]+"
    r")",
    re.IGNORECASE,
)

#: Dinheiro: o numero com marca de moeda de um dos lados, ou com multiplicador.
#: O multiplicador e insensivel a maiusculas porque o modelo escreve «2 MIL Kz».
_MULT: Final = r"(?i:mil|milhao|milhoes|milh[õo]es)"
_DINHEIRO: Final = re.compile(
    rf"(?:{_KZ}\s*(?P<a>{_DIGITOS})"
    rf"|(?P<b>{_DIGITOS})(?:\s+(?P<mult>{_MULT}))?\s*{_KZ}"
    rf"|(?P<c>{_DIGITOS})\s+(?P<mult2>{_MULT})\b)"
)

#: Um numero com marca de moeda **estrangeira** ao lado. Existe em separado
#: porque o `_DINHEIRO` so casa o que tem Kz ou multiplicador, e sem isto «100
#: USD» caia no varrimento de `outro` e um `Policy(allowed_literals=(100,))`
#: **perdoava-o** — medido pela revisao adversarial. Uma moeda estrangeira e
#: dinheiro que nao se consegue sustentar (nao ha `kind` de moeda, divida 105),
#: e tem de dar `money_unbacked` e nao `number_unbacked`.
_MOEDA_ESTRANGEIRA: Final = re.compile(
    rf"(?:(?P<sim>[$€£¥₦₹]|R\$)\s*(?P<v1>{_DIGITOS})"
    rf"|(?P<v2>{_DIGITOS})\s*(?P<cod>[A-Z]{{3}}|[$€£¥₦₹]|R\$)(?![A-Za-z]))"
)

#: Qualquer corrida de digitos, para o varrimento final de `outro`.
_QUALQUER_NUMERO: Final = re.compile(_DIGITOS)

#: Um token de palavra, para construir as corridas de numero por extenso.
_PALAVRA: Final = re.compile(r"[a-zA-ZÀ-ÿ]+")

#: O marcador do modo `a_partir_de` no texto (`docs/tecnica/03` §7.1).
A_PARTIR_DE: Final = "a partir de"


@dataclass(frozen=True, slots=True)
class Numero:
    """Um numero encontrado no texto, com a classe que decide o seu veredicto."""

    bruto: str
    inicio: int
    fim: int
    classe: str
    #: Em centimos, quando a classe e `dinheiro`. `None` nas outras.
    value_minor: int | None = None
    #: O inteiro, quando a classe e `percentagem`, `quantidade` ou `outro`.
    valor: int | None = None

    def __post_init__(self) -> None:
        if self.classe not in CLASSES:
            raise ValueError(f"{self.classe!r} nao e uma das classes: {list(CLASSES)}")


@dataclass(frozen=True, slots=True)
class Linha:
    """Uma linha do texto — a unidade do vinculo `sku`<->preco (§9.2).

    O §9.1 diz «por linha/bloco», e a linha e o que existe no texto final: o
    *renderer* escreve um `item` por linha, e a prosa livre vem em paragrafos.
    """

    texto: str
    numeros: tuple[Numero, ...]
    skus: tuple[str, ...]
    nomes: tuple[str, ...]

    @property
    def dinheiro(self) -> tuple[Numero, ...]:
        return tuple(n for n in self.numeros if n.classe == "dinheiro")

    @property
    def tem_a_partir_de(self) -> bool:
        return A_PARTIR_DE in sem_acento(self.texto)


def _marca(ocupado: list[bool], inicio: int, fim: int) -> bool:
    """Reserva o intervalo. `False` se ja estava ocupado por classe mais forte."""
    if any(ocupado[inicio:fim]):
        return False
    for i in range(inicio, fim):
        ocupado[i] = True
    return True


def _e_quantidade(texto: str, fim: int, inicio: int) -> bool:
    """Se o numero esta junto a uma palavra de contagem, de um dos lados."""
    depois = sem_acento(texto[fim : fim + 24])
    antes = sem_acento(texto[max(0, inicio - 24) : inicio])
    for palavra in PALAVRAS_DE_CONTAGEM:
        if re.match(rf"\s*{re.escape(palavra)}\b", depois):
            return True
        if re.search(rf"\b{re.escape(palavra)}\s*$", antes):
            return True
    return False


def _corridas_de_extenso(texto: str) -> list[tuple[int, int]]:
    """As corridas maximas de palavras de numero, com os `e` pelo meio.

    **Nao e um `re` so**, e a razao esta medida: um padrao guloso sobre palavras
    apanhava «doze mil e quinhentos Kz» com o `Kz` dentro, a validacao de
    «todas as palavras sao de numero» falhava, e o numero **desaparecia** — um
    falso aceite, porque o que nao se extrai nao se valida. Com os tokens, a
    corrida fecha na primeira palavra que nao e de numero.
    """
    corridas: list[tuple[int, int]] = []
    inicio: int | None = None
    #: O fim da ultima palavra que **nao** e `e`: e onde a corrida acaba, para
    #: que «doze mil e caixas» de «doze mil» e nao «doze mil e».
    fim = 0
    for achado in _PALAVRA.finditer(texto):
        palavra = sem_acento(achado.group(0))
        if palavra in PALAVRAS_DE_NUMERO:
            if inicio is None:
                if palavra == "e":
                    continue  # uma corrida nao comeca por `e`
                inicio = achado.start()
            if palavra != "e":
                fim = achado.end()
        elif inicio is not None:
            corridas.append((inicio, fim))
            inicio = None
    if inicio is not None:
        corridas.append((inicio, fim))
    return corridas


def _extenso_conta(cru: str, texto: str, inicio: int, fim: int) -> bool:
    """Se uma sequencia de palavras de numero conta como numero (cabecalho).

    **Uma palavra so precisa de contexto**, seja ela qual for — e nao apenas o
    `um`/`uma`, como a primeira versao fazia. A revisao adversarial mediu o
    preco dessa versao: «Mil desculpas, ja corrijo», «Cem por cento de certeza»,
    «Dois minutos e volto» e um nome de marca com «Zero» davam todos
    `number_unbacked`, isto e, respostas legitimas da loja recusadas, cada uma a
    custar uma repeticao do modelo e, ao esgotar o tecto, um *handoff*.

    O que **nao** se perde: duas ou mais palavras de numero contam sempre
    («doze mil», «vinte e cinco»), e uma palavra so conta assim que a moeda ou
    uma palavra de contagem a reclame («mil Kz», «cem unidades»). O que fica
    aceite e uma palavra de numero isolada sem nada que a reclame — e nao e uma
    citacao de *fact*, e conversa.
    """
    palavras = [p for p in re.split(r"[\s-]+", sem_acento(cru)) if p and p != "e"]
    if not palavras:
        return False
    if len(palavras) >= 2:
        return True
    # Uma palavra so: a moeda ou a contagem tem de a reclamar.
    #
    # shortcut: uma palavra de numero **isolada**, sem moeda e sem palavra de
    # contagem, nao se extrai — «levo dois» passa sem *fact*. O tecto e uma
    # quantidade de uma palavra (ate «noventa e nove» sao duas e contam), e o
    # gatilho e o KAM-033: o classificador de saida tem o contexto da frase, que
    # e o que falta aqui para distinguir «levo dois» de «dois minutos e volto».
    # Medido nos `LIMITES` do conjunto adversarial.
    depois = texto[fim : fim + 24]
    return bool(re.match(rf"\s*{_KZ}\b", depois)) or _e_quantidade(texto, fim, inicio)


def extrair(texto: str, skus: tuple[str, ...] = (), nomes: tuple[str, ...] = ()) -> tuple[Linha, ...]:
    """O texto partido em linhas, com os numeros classificados e os `sku`/nomes.

    Os `skus` e os `nomes` vem do *output* da tool (`docs/tecnica/05` §6.3) e
    procuram-se **literalmente**: um padrao de `sku` era uma segunda gramatica a
    manter, e o que o §6.3 manda e «aceita so `sku` … presentes neste *output*».
    """
    linhas: list[Linha] = []
    for cru in texto.split("\n"):
        linhas.append(_linha(cru, skus, nomes))
    return tuple(linhas)


def _linha(texto: str, skus: tuple[str, ...], nomes: tuple[str, ...]) -> Linha:
    ocupado = [False] * len(texto)
    achados: list[Numero] = []

    # Um `sku` ocupa o seu intervalo **antes** de tudo: os digitos de `SKU-123`
    # nao sao um numero citado, sao o identificador do produto.
    #
    # **Do mais longo para o mais curto**, e a revisao adversarial mediu porque:
    # com `SKU-10` e `SKU-100` no catalogo, o curto reservava primeiro e o longo
    # falhava o `_marca`, pelo que a linha do `SKU-100` ficava com `skus =
    # ("SKU-10",)` e o preco certo dava `sku_price_mismatch` — o *renderer* a
    # falhar o seu proprio validador por um prefixo.
    presentes_sku = []
    for sku in sorted(skus, key=len, reverse=True):
        for achado in re.finditer(re.escape(sku), texto):
            if _marca(ocupado, achado.start(), achado.end()):
                if sku not in presentes_sku:
                    presentes_sku.append(sku)

    # E um **nome** de produto ocupa o seu, pela mesma razao e com um custo que
    # se escreve. «Vestido 2 pecas» e o nome que a tool devolveu: o `2` nao e um
    # numero citado, e o controlo positivo do conjunto adversarial apanhou-o a
    # dar `qty_unbacked` em todas as respostas sobre esse produto.
    #
    # Tambem do mais longo para o mais curto: com «Coca-Cola» e «Coca-Cola
    # Zero», o curto reservava primeiro e o longo nunca era visto.
    #
    # **O que isto abre, e onde se fecha:** um nome e texto escrito pela PME, e
    # reservar-lhe o intervalo deixaria um nome como «Camisa 99 999 Kz» citar um
    # preco sem *fact*. Nao se fecha aqui — fecha-se no `render.py`, que **recusa
    # renderizar** um nome com marca de moeda ou com valor monetario.
    presentes_nome = []
    for nome in sorted(nomes, key=len, reverse=True):
        for achado in re.finditer(re.escape(nome), texto, re.IGNORECASE):
            if _marca(ocupado, achado.start(), achado.end()):
                if nome not in presentes_nome:
                    presentes_nome.append(nome)

    # Daqui para baixo **marca-se so depois de o achado existir**, e a ordem
    # inversa foi um dos defeitos mais caros deste ticket: a primeira versao
    # reservava o intervalo antes de saber se o conseguia ler, e quando o ramo
    # desistia o intervalo ficava ocupado — o varrimento 5 saltava-o e o numero
    # **desaparecia**. Tres entradas medidas pela revisao adversarial, todas
    # aceites: «SKU-9 - Camisa 12 500 Kz» com um *fact* de 500 Kz (o cliente le
    # 12 500 num produto de 500), «SKU-700 - Tinta 250 unidades» com stock 2, e
    # «2 milhões de Kz» sem *fact* nenhum. O que nao se extrai nao se valida.
    def _guardar(inicio: int, fim: int, numero: Numero) -> None:
        if _marca(ocupado, inicio, fim):
            achados.append(numero)

    # 1. percentagem
    for achado in _PERCENTAGEM.finditer(texto):
        if any(ocupado[achado.start() : achado.end()]):
            continue
        _guardar(
            achado.start(),
            achado.end(),
            Numero(
                bruto=achado.group(0),
                inicio=achado.start(),
                fim=achado.end(),
                classe="percentagem",
                valor=_inteiro(achado.group("n")),
            ),
        )

    # 2. data/hora
    for achado in _DATAHORA.finditer(texto):
        if any(ocupado[achado.start() : achado.end()]):
            continue
        _guardar(
            achado.start(),
            achado.end(),
            Numero(
                bruto=achado.group(0),
                inicio=achado.start(),
                fim=achado.end(),
                classe="datahora",
            ),
        )

    # 2.5. moeda estrangeira — **antes** do dinheiro em Kz, para que «100 USD»
    #      nao caia em `outro` e seja perdoado por um `allowed_literals`.
    for achado in _MOEDA_ESTRANGEIRA.finditer(texto):
        if any(ocupado[achado.start() : achado.end()]):
            continue
        marca = achado.group("sim") or achado.group("cod") or ""
        if sem_acento(marca) in MARCAS_DE_KZ or sem_acento(marca) in PALAVRAS_DE_NUMERO:
            continue
        _guardar(
            achado.start(),
            achado.end(),
            Numero(
                bruto=achado.group(0),
                inicio=achado.start(),
                fim=achado.end(),
                classe="dinheiro",
                value_minor=None,  # nao ha `kind` de moeda onde a sustentar
            ),
        )

    # 3. dinheiro
    for achado in _DINHEIRO.finditer(texto):
        if any(ocupado[achado.start() : achado.end()]):
            continue
        digitos = achado.group("a") or achado.group("b") or achado.group("c")
        mult = achado.group("mult") or achado.group("mult2") or ""
        try:
            centimos: int | None = para_centimos(f"{digitos} {mult}".strip())
        except MoedaEstrangeiraError:
            # **Dinheiro que nao se consegue sustentar, e nao um numero solto.**
            # Nao ha `kind` de moeda (divida 105), pelo que uma moeda
            # estrangeira e sempre `money_unbacked` — e nao `number_unbacked`,
            # que o `allowed_literals` podia perdoar: a revisao mediu
            # `Policy(allowed_literals=(100,))` a aceitar «100 USD».
            centimos = None
        except NaoEDinheiroError:
            continue  # deixa o intervalo livre para o varrimento 5
        _guardar(
            achado.start(),
            achado.end(),
            Numero(
                bruto=achado.group(0),
                inicio=achado.start(),
                fim=achado.end(),
                classe="dinheiro",
                value_minor=centimos,
            ),
        )

    # 4. numeros por extenso — dinheiro se a moeda os reclamar, senao quantidade
    #    ou `outro`.
    for comeco, acaba in _corridas_de_extenso(texto):
        if any(ocupado[comeco:acaba]):
            continue
        cru = texto[comeco:acaba]
        if not _extenso_conta(cru, texto, comeco, acaba):
            continue
        depois = texto[acaba : acaba + 24]
        if re.match(rf"\s*{_KZ}\b", depois):
            try:
                centimos = para_centimos(cru)
            except (NaoEDinheiroError, MoedaEstrangeiraError):
                continue
            _guardar(
                comeco,
                acaba,
                Numero(
                    bruto=cru, inicio=comeco, fim=acaba,
                    classe="dinheiro", value_minor=centimos,
                ),
            )
            continue
        try:
            valor = para_centimos(cru) // 100
        except (NaoEDinheiroError, MoedaEstrangeiraError):
            continue
        classe = "quantidade" if _e_quantidade(texto, acaba, comeco) else "outro"
        _guardar(
            comeco,
            acaba,
            Numero(bruto=cru, inicio=comeco, fim=acaba, classe=classe, valor=valor),
        )

    # 5. o resto: quantidade se a contagem o reclamar, senao `outro`.
    for achado in _QUALQUER_NUMERO.finditer(texto):
        if any(ocupado[achado.start() : achado.end()]):
            continue
        classe = (
            "quantidade"
            if _e_quantidade(texto, achado.end(), achado.start())
            else "outro"
        )
        _guardar(
            achado.start(),
            achado.end(),
            Numero(
                bruto=achado.group(0),
                inicio=achado.start(),
                fim=achado.end(),
                classe=classe,
                valor=_inteiro(achado.group(0)),
            ),
        )

    return Linha(
        texto=texto,
        numeros=tuple(sorted(achados, key=lambda n: n.inicio)),
        skus=tuple(presentes_sku),
        nomes=tuple(presentes_nome),
    )


def _inteiro(bruto: str) -> int | None:
    """O inteiro de uma corrida de digitos, ou `None` se tiver decimais."""
    limpo = re.sub(r"[ .]", "", bruto)
    if "," in limpo:
        inteiro, _, decimal = limpo.rpartition(",")
        if len(decimal) == 3:
            return int(inteiro + decimal) if (inteiro + decimal).isdigit() else None
        return None
    return int(limpo) if limpo.isdigit() else None
