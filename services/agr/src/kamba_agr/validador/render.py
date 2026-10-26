"""O *renderer* por referencia — camada 1 do §9.1 (proposta 02-A).

O modelo **nao escreve numeros**: devolve blocos e este modulo preenche-os a
partir dos *facts*. E a camada que torna «0 numeros divergentes» verificavel por
construcao, em vez de verificavel por inspeccao; o validador do `veredicto.py` e
a rede de seguranca que vem depois.

Os cinco blocos sao os do §3.30 do dicionario (emenda 1.39): `text`, `item`,
`total`, `buttons` e `datetime`. O exemplo do §9.1 tem quatro; o quinto vem do
§8.2, que estende o validador a «datas, horas e duracoes».

## Tres decisoes que o exemplo do §9.1 nao escreve

**1. Os `buttons` saiem ao lado do texto, e nao dentro dele.** Um id de botao e
`confirm:c_77`, e o `77` e estrutura e nao um numero citado: posto no corpo da
mensagem, o extractor le-o e da `number_unbacked` — o *renderer* a falhar o seu
proprio validador. Alem disso e o que o canal faz: numa mensagem interactiva os
botoes sao payload proprio e nao texto (`docs/tecnica/01` §8).

**2. Um bloco `item` leva **sempre** o `sku`.** O §6.3 do `docs/tecnica/05` diz
«o validador aceita so `sku` e numeros presentes neste *output*; resposta com
`sku` ausente e rejeitada». Um `item` com `show: ["name", "price"]` e sem `sku`
visivel seria recusado pela camada 2 — e seria recusado com razao, porque e
exactamente a forma do «produto errado com preco certo».

**3. Um bloco `text` com digitos **levanta**.** E a regra do §9.1 («o modelo nao
escreve numeros em prosa») imposta no sitio onde e barata. Degradar em silencio —
renderizar o texto e deixar a camada 2 recusar — gastava uma repeticao do modelo
para descobrir o que esta funcao sabe de imediato.

## O fuso: `Africa/Luanda` por desvio fixo, e nao por `ZoneInfo`

A apresentacao e em `Africa/Luanda` e o armazenamento em UTC (convencao do
conjunto). O `zoneinfo.ZoneInfo("Africa/Luanda")` **levanta** nesta maquina
(`ZoneInfoNotFoundError`: nao ha `tzdata`), e por-lo a funcionar era uma
dependencia nova para resolver um fuso que nunca teve horario de verao: Angola
esta em WAT (UTC+1) sem transicoes. O desvio fixo e **exacto** para este fuso e
nao arrasta dependencia nenhuma.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any, Final

from .normalizacao import kz_display

#: Os cinco blocos do dicionario §3.30. Lista **fechada**.
BLOCOS: Final = ("text", "item", "total", "buttons", "datetime")

#: Os campos que um `item` pode mostrar (§9.1, `show`). **Nao tem
#: `description`**, e e isso que torna o criterio 5 estrutural em vez de uma
#: regra: nao ha bloco por onde um digito de uma descricao escrita pela PME
#: possa chegar ao cliente.
CAMPOS_DE_ITEM: Final = ("name", "price", "stock")

#: O maximo de opcoes numa lista interactiva (`docs/tecnica/02` §8.2, limite da
#: Meta, CONFIRMADO).
MAX_BOTOES: Final = 10

#: `Africa/Luanda` = WAT = UTC+1, sem horario de verao (ver o cabecalho).
LUANDA: Final = datetime.timezone(datetime.timedelta(hours=1), "WAT")

#: Os tres modos de preco (`specs/02` §3.3; `docs/tecnica/03` §7.1).
PRECO_FIXO: Final = "fixo"
PRECO_A_PARTIR_DE: Final = "a_partir_de"
PRECO_SOB_CONSULTA: Final = "sob_consulta"
MODOS_DE_PRECO: Final = (PRECO_FIXO, PRECO_A_PARTIR_DE, PRECO_SOB_CONSULTA)

#: O que se mostra quando nao ha preco publicado (EPIC-04, criterio 2).
SOB_CONSULTA_DISPLAY: Final = "preco sob consulta"

_DIGITO: Final = re.compile(r"\d")

#: Um nome de produto que traz preco dentro. O `extraccao.py` reserva o
#: intervalo de um nome — senao «Vestido 2 pecas» dava `qty_unbacked` —, e e
#: **aqui** que se fecha o que isso abriria: um nome escrito pela PME como
#: «Camisa 99 999 Kz» citaria um preco sem *fact*. Recusa-se a renderizar, no
#: sitio onde o dado entra, em vez de confiar que a camada 2 o apanha (nao
#: apanha: o intervalo esta reservado).
#: **Inclui um nome que acaba em digitos**, e a razao e um falso aceite medido
#: pela revisao adversarial: com a oferta `("SKU-9", "Camisa 12")` e um *fact* de
#: 500 Kz, o texto «SKU-9 - Camisa 12 500 Kz» era **aceite** — o intervalo do
#: nome engolia o `12`, sobrava «500 Kz» que casa o *fact*, e o cliente lia
#: 12 500 Kz num produto de 500 Kz. Digitos **no meio** de um nome nao tem este
#: problema («Vestido 2 pecas»), porque nao se colam ao numero seguinte; no fim,
#: colam-se sempre.
_PRECO_NO_NOME: Final = re.compile(
    r"(?:Kz|KZ|kz|AOA|kwanzas?|Kwanzas?)|\d{1,3}(?:[ .,]\d{3})+|\d{4,}|\d\s*$",
    re.IGNORECASE,
)


class NomeComPrecoError(ValueError):
    """Um nome de produto com moeda ou valor monetario dentro (ver `_PRECO_NO_NOME`).

    Levanta na `Oferta` e nao no `renderizar`: o `veredicto.py` tambem recebe
    ofertas, e uma que so rebentasse no *renderer* deixava a camada 2 a reservar
    o intervalo de um nome que traz preco. Recusa-se a construir o objecto.
    """


class BlocoInvalidoError(ValueError):
    """Um bloco que o §3.30 nao admite, ou que nao se consegue preencher.

    Levanta em vez de degradar: um *renderer* que omite em silencio o que nao
    sabe preencher produz uma mensagem **mais curta e plausivel** do que a que
    se pediu, e e a classe de defeito que ninguem ve ao ler o resultado.
    """


@dataclass(frozen=True, slots=True)
class Oferta:
    """O que a tool devolveu sobre um produto (`docs/tecnica/05` §6.3).

    **Tres campos e nao o contrato inteiro**, e a ausencia e o desenho: nao ha
    `descricao` aqui. O criterio 5 do KAM-032 diz «digitos de descricoes de
    produto escritas pela PME nao contam como *facts*; o modelo nao os pode
    repetir», e a forma de o garantir nao e uma regra que alguem tem de lembrar:
    e nao haver campo. O preco **nao** esta aqui tambem — vem de um `Fact`.
    """

    sku: str
    nome: str
    preco_tipo: str

    def __post_init__(self) -> None:
        if self.preco_tipo not in MODOS_DE_PRECO:
            raise ValueError(
                f"{self.preco_tipo!r} nao e um modo de preco: {list(MODOS_DE_PRECO)}"
            )
        if _PRECO_NO_NOME.search(self.nome):
            raise NomeComPrecoError(
                f"o nome {self.nome!r} traz marca de moeda ou valor monetario: um "
                "nome e texto da PME e o seu intervalo nao e validado (ADR-007)"
            )


@dataclass(frozen=True, slots=True)
class Renderizacao:
    """O que o *renderer* produziu: o corpo da mensagem e os botoes, ao lado."""

    texto: str
    botoes: tuple[str, ...] = ()


def em_luanda(iso_utc: str) -> datetime.datetime:
    """Um instante UTC do armazenamento, no fuso da apresentacao."""
    texto = iso_utc.strip().replace("Z", "+00:00")
    quando = datetime.datetime.fromisoformat(texto)
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=datetime.timezone.utc)
    return quando.astimezone(LUANDA)


def datahora_display(iso_utc: str) -> str:
    """«14/11/2026 as 14h30» — a forma que o *renderer* escreve."""
    quando = em_luanda(iso_utc)
    return f"{quando:%d/%m/%Y} as {quando:%H}h{quando:%M}"


def formas_de_datahora(iso_utc: str) -> tuple[str, ...]:
    """As formas que a camada 2 aceita para o mesmo instante.

    O extractor parte «14/11/2026 as 14h30» em **dois** achados — uma data e uma
    hora —, pelo que o validador tem de reconhecer cada um por si. Sem isto, o
    texto do proprio *renderer* dava `datetime_unbacked` duas vezes.
    """
    quando = em_luanda(iso_utc)
    return (
        datahora_display(iso_utc),
        f"{quando:%d/%m/%Y}",
        f"{quando:%d/%m}",
        f"{quando:%H}h{quando:%M}",
        f"{quando:%H}:{quando:%M}",
    )


def _fact(facts: tuple[Any, ...], *, kind: str, sku: str | None = None, fact_id: str | None = None):
    for f in facts:
        if f.kind != kind:
            continue
        if fact_id is not None and f.fact_id != fact_id:
            continue
        if sku is not None and f.sku != sku:
            continue
        return f
    return None


def inteiro_do_fact(valor: Any) -> int | None:
    """O `value` de um *fact*, se for um inteiro. `None` fecha a porta.

    Publica porque o `veredicto.py` precisa da mesma leitura, e tinha uma copia
    identica: duas funcoes com o mesmo nome e o mesmo corpo divergem no dia em
    que alguem corrigir uma (achado *Lean* da `ANALISE-33`).
    """
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


#: O nome curto, para quem le este ficheiro.
_inteiro = inteiro_do_fact


def _exigir_fact_id(bloco: dict) -> str:
    """O `fact_id` de um bloco `total` ou `datetime`. **Obrigatorio.**

    Sem isto, um `fact_id` ausente dava `None` no `_fact`, que casava **qualquer**
    *fact* daquele `kind` — e a revisao adversarial mediu o resultado: com dois
    *facts* `total` na mesa, `{"type": "total"}` escolhia o primeiro e escrevia
    «Total: 5 000 Kz» quando o carrinho era de 21 500 Kz. A camada 1 a produzir o
    numero errado em silencio e precisamente a divergencia que o ADR-007 proibe,
    e a *docstring* do `BlocoInvalidoError` diz que aqui se levanta em vez de
    degradar.
    """
    fact_id = bloco.get("fact_id")
    if not isinstance(fact_id, str) or not fact_id:
        raise BlocoInvalidoError(
            f"um bloco `{bloco.get('type')}` precisa de `fact_id`: sem ele, qualquer "
            "*fact* do mesmo `kind` serviria"
        )
    return fact_id


def preco_display(centimos: int, preco_tipo: str) -> str:
    """O `precoDisplay` do `docs/tecnica/03` §7.1, **com o modo**."""
    if preco_tipo == PRECO_SOB_CONSULTA:
        return SOB_CONSULTA_DISPLAY
    valor = kz_display(centimos)
    return f"a partir de {valor}" if preco_tipo == PRECO_A_PARTIR_DE else valor


def _item(bloco: dict, facts: tuple[Any, ...], por_sku: dict[str, Oferta]) -> str:
    sku = bloco.get("sku")
    if not isinstance(sku, str) or not sku:
        raise BlocoInvalidoError("um bloco `item` sem `sku` nao se pode citar")
    oferta = por_sku.get(sku)
    if oferta is None:
        raise BlocoInvalidoError(f"o `sku` {sku!r} nao esta no *output* da tool")

    mostrar = bloco.get("show", list(CAMPOS_DE_ITEM))
    if not isinstance(mostrar, (list, tuple)):
        raise BlocoInvalidoError("`show` tem de ser uma lista")
    desconhecidos = [c for c in mostrar if c not in CAMPOS_DE_ITEM]
    if desconhecidos:
        raise BlocoInvalidoError(
            f"{desconhecidos} nao sao campos de `item`: {list(CAMPOS_DE_ITEM)}"
        )

    # O `sku` vem sempre primeiro (ver a decisao 2 do cabecalho).
    partes = [sku]
    for campo in mostrar:
        if campo == "name":
            partes.append(oferta.nome)
        elif campo == "price":
            if oferta.preco_tipo == PRECO_SOB_CONSULTA:
                partes.append(SOB_CONSULTA_DISPLAY)
                continue
            fact = _fact(facts, kind="price", sku=sku)
            centimos = _inteiro(fact.value) if fact is not None else None
            if centimos is None:
                raise BlocoInvalidoError(f"sem *fact* `price` inteiro para {sku!r}")
            partes.append(preco_display(centimos, oferta.preco_tipo))
        elif campo == "stock":
            fact = _fact(facts, kind="stock", sku=sku)
            quantos = _inteiro(fact.value) if fact is not None else None
            if quantos is None:
                raise BlocoInvalidoError(f"sem *fact* `stock` inteiro para {sku!r}")
            partes.append(f"{quantos} unidades")
    return " - ".join(partes)


def renderizar(
    blocos: list[dict],
    facts: tuple[Any, ...] = (),
    ofertas: tuple[Oferta, ...] = (),
) -> Renderizacao:
    """Os blocos do `compose`, preenchidos com *facts*. Uma linha por bloco."""
    por_sku = {o.sku: o for o in ofertas}
    linhas: list[str] = []
    botoes: list[str] = []

    for bloco in blocos:
        if not isinstance(bloco, dict):
            raise BlocoInvalidoError("cada bloco e um objecto")
        tipo = bloco.get("type")
        if tipo not in BLOCOS:
            raise BlocoInvalidoError(f"{tipo!r} nao e um bloco: {list(BLOCOS)}")

        if tipo == "text":
            texto = bloco.get("text", "")
            if not isinstance(texto, str):
                raise BlocoInvalidoError("`text` tem de ser uma cadeia")
            # **Nao basta procurar digitos.** A revisao adversarial mediu-o: um
            # bloco `text` com «A camisa custa doze mil Kz» renderizava sem
            # erro, e com um *fact* `total` de 12 000 Kz passava a camada 2 —
            # prosa monetaria escrita pelo modelo a chegar ao cliente, no sitio
            # onde esta regra existe para o impedir. Pergunta-se ao extractor,
            # que e quem sabe o que e um numero.
            from .extraccao import extrair

            if _DIGITO.search(texto) or any(
                linha.numeros for linha in extrair(texto)
            ):
                raise BlocoInvalidoError(
                    "um bloco `text` nao leva numeros, nem em digitos nem por "
                    "extenso: citam-se por referencia (§9.1, proposta 02-A)"
                )
            linhas.append(texto)
        elif tipo == "item":
            linhas.append(_item(bloco, facts, por_sku))
        elif tipo == "total":
            fact = _fact(facts, kind="total", fact_id=_exigir_fact_id(bloco))
            centimos = _inteiro(fact.value) if fact is not None else None
            if centimos is None:
                raise BlocoInvalidoError(
                    f"sem *fact* `total` inteiro com `fact_id` {bloco.get('fact_id')!r}"
                )
            linhas.append(f"Total: {kz_display(centimos)}")
        elif tipo == "datetime":
            fact = _fact(facts, kind="datetime", fact_id=_exigir_fact_id(bloco))
            if fact is None or not isinstance(fact.value, str):
                raise BlocoInvalidoError(
                    f"sem *fact* `datetime` com `fact_id` {bloco.get('fact_id')!r}"
                )
            linhas.append(datahora_display(fact.value))
        else:  # buttons
            ids = bloco.get("ids", [])
            if not isinstance(ids, (list, tuple)) or not all(isinstance(i, str) for i in ids):
                raise BlocoInvalidoError("`ids` tem de ser uma lista de cadeias")
            if not ids:
                raise BlocoInvalidoError("um bloco `buttons` sem `ids` nao e um bloco")
            if len(ids) > MAX_BOTOES:
                raise BlocoInvalidoError(
                    f"{len(ids)} botoes passa o limite de {MAX_BOTOES} da Meta (§8.2)"
                )
            botoes.extend(ids)

    return Renderizacao(texto="\n".join(linhas), botoes=tuple(botoes))
