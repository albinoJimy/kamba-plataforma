"""O traco por identificadores: mensagem -> pedido -> evento -> consumo (KAM-108).

O critério G0-1 pede «traço por identificadores (mensagem -> pedido -> evento de
pagamento -> consumo) **sem conteúdo nem telefone**». Este módulo é esse traço, e
três decisões explicam a forma que ele tem.

## 1. A cadeia não cabe nos *logs*, e isso mediu-se antes de se escrever código

A tentação era ler só as linhas de *log* da pilha. Não dá, e a razão é a política
desta casa e não uma falta: o ADR-010 e o `docs/logs.md` §2 fixam uma *allowlist*
de **doze** campos, e `order_id`, `event_id`, `booking_id` e `conversation_id`
**não são nenhum deles** — o §2.2 do mesmo documento recusa o `contact_id` pelo
nome. Dos quatro elos da cadeia, os *logs* dão o primeiro (`turn_id`, `msg_id`,
`tenant_id`) e mais nada.

Os outros três vivem na base, em colunas que o dicionário canónico §3 já nomeia:
o `audit_log(turn_id, entity, entity_id)` liga o turno ao pedido, o
`events_log(event_id, tipo, agregado_id)` liga o pedido ao evento de pagamento, e
o `events_consumed(consumer, event_id, processado_at)` liga o evento ao consumo.
Daí este módulo juntar **duas** entradas e não uma, e daí o `consulta.py`
existir: as consultas são `SELECT` de leitura que projectam **só** colunas de
identificador, o que faz da propriedade «sem conteúdo» uma consequência da
projecção e não uma promessa de quem a escreveu.

## 2. A *allowlist* é pela **forma do valor**, não pelo nome da chave

É o precedente do `spikes/h3/registo.py` (KAM-100), e a razão dele vale aqui
inteira: uma guarda por nome de campo fica verde com uma mensagem inteira
guardada num campo chamado `nota`, `ref` ou `fase`. No KAM-100 isso foi um
achado de revisão adversarial a sério — a única chave que admitia dígitos
admitia um telefone.

Por isso cada entrada de `PERMITIDOS` diz a forma exacta do valor, e um valor
que não casa a forma **não é aparado**: ou a chave cai (se for acessória), ou a
leitura falha com `ConteudoRecusado` (se for um elo da cadeia). Não existe
«o telefone com asteriscos».

## 3. Carimbos não entram como inteiro, e é por causa do telefone

Um móvel angolano tem nove dígitos. Um carimbo Unix em segundos também tem nove
dígitos, hoje e até 2033. Logo um campo de carimbo declarado `int` aceita um
telefone **com a forma certa**, e nenhum detector de telefone o apanharia, porque
ele já passou a guarda como número. Os carimbos aceitam-se por isso só na forma
do `docs/logs.md` §2 — ISO-8601 em UTC com sufixo `Z` —, e um inteiro é
recusado com essa razão escrita na excepção.

## O que este módulo não faz

Não observa a conversa real, não decide se a cadeia está completa «o suficiente»,
e não escreve nenhuma linha da checklist. Devolve a cadeia que as entradas
sustentam e nomeia o elo que falta; quem lê a demonstração é uma pessoa.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

#: Os dois padrões canónicos de telefone, **importados do sítio onde já vivem**
#: e não recopiados: `tools/contract_diff/pii.py`, que é também o do
#: `packages/core-ts/src/eventos/pii.ts` e o da guarda de `platform.evt_emitir`.
#: Um padrão que divergisse apanhava um conjunto diferente, e o que se quer é
#: que as superfícies recusem exactamente o mesmo.
from contract_diff.pii import E164_ENTRE_ASPAS, TELEFONE_AO

#: A forma **local** de nove dígitos, que nenhum dos dois acima apanha.
#:
#: `\+?244 ?9[0-9]{8}` exige o indicativo e `"\+[0-9]{9,15}"` exige as aspas e o
#: `+`; um `912345678` nu passa pelos dois. Num ficheiro de evidência continuaria
#: a ser um dado pessoal, e é o terceiro detector que o KAM-100 teve de
#: acrescentar pela mesma razão. Exige-se fronteira para não apanhar os nove
#: dígitos do meio de um UUID ou de um `m_…`, que são hexadecimais e têm os
#: dígitos que tiverem (`docs/logs.md` §7, ponto 3).
MOVEL_LOCAL = re.compile(r"(?<![0-9a-zA-Z])9[0-9]{8}(?![0-9a-zA-Z])")

#: Os três detectores, pela ordem em que se corre.
DETECTORES: Sequence[tuple[str, re.Pattern[str]]] = (
    ("telefone_ao", TELEFONE_AO),
    ("e164_entre_aspas", E164_ENTRE_ASPAS),
    ("movel_local", MOVEL_LOCAL),
)

#: O alfabeto de um valor **estrutural**: hexadecimais, dígitos, hífenes,
#: sublinhados, pontos, dois-pontos, o `+` e as letras minúsculas e maiúsculas de
#: um nome de evento ou de um carimbo ISO. Um caractere fora dele é texto livre,
#: e é o terceiro detector do KAM-100: um espaço, uma vírgula ou um acento num
#: valor que devia ser um identificador quer dizer que entrou prosa.
FORA_DO_ALFABETO = re.compile(r"[^0-9A-Za-z_.:+\-]")

#: A forma de um carimbo, a do `docs/logs.md` §2: UTC, com sufixo `Z`.
CARIMBO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")

#: UUID canónico em minúsculas. Não se aceita maiúsculas: o `docs/logs.md` §2 diz
#: que o `tenant_id` «sai em minúsculas», e duas grafias do mesmo identificador
#: fazem duas cadeias onde há uma.
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: O `id_opaco` do `docs/logs.md` §2.1: `m_` mais 32 hexadecimais.
ID_OPACO = re.compile(r"^m_[0-9a-f]{32}$")

#: Um nome de evento do catálogo: `payment.manual_confirmed`, `booking.created`.
TIPO_DE_EVENTO = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: Um identificador curto no sentido do `docs/logs.md` §2: palavras em minúsculas
#: separadas por `_`. Serve o `consumer`, a `entity` e o `estado`.
IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


class ConteudoRecusado(ValueError):
    """Um valor não casa a forma declarada para a sua chave.

    **A mensagem não leva o valor.** Se o valor for conteúdo de uma conversa ou
    um telefone, a excepção punha-o no registo da execução — que é exactamente o
    sítio de onde este módulo o quer tirar. Leva a chave, o comprimento e o nome
    da forma que falhou. É o precedente do `spikes/h3/registo.py`.
    """


class EloEmFalta(LookupError):
    """A cadeia parou num elo, e o traço diz qual.

    Não é a mesma coisa que `ConteudoRecusado`: ali a entrada traz o que não
    devia, aqui a entrada não traz o que a cadeia precisa. Separam-se porque as
    consequências na checklist são opostas — a primeira é um defeito do
    instrumento ou da consulta, a segunda é o resultado da demonstração.
    """


@dataclasses.dataclass(frozen=True)
class Forma:
    """A forma exacta que o valor de uma chave tem de ter."""

    nome: str
    aceita: Callable[[Any], bool]
    descricao: str


def _casa(padrao: re.Pattern[str]) -> Callable[[Any], bool]:
    return lambda valor: isinstance(valor, str) and bool(padrao.match(valor))


def _inteiro_nao_negativo(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0


FORMA_UUID = Forma("uuid", _casa(UUID), "UUID canónico em minúsculas")
FORMA_ID_OPACO = Forma("id_opaco", _casa(ID_OPACO), "`m_` e 32 hexadecimais")
FORMA_UUID_OU_OPACO = Forma(
    "uuid_ou_id_opaco",
    lambda v: FORMA_UUID.aceita(v) or FORMA_ID_OPACO.aceita(v),
    "UUID canónico ou `m_` e 32 hexadecimais (`docs/logs.md` §2)",
)
FORMA_TIPO = Forma("tipo_de_evento", _casa(TIPO_DE_EVENTO), "`dominio.acontecimento`")
FORMA_IDENTIFICADOR = Forma(
    "identificador", _casa(IDENTIFICADOR), "palavras em minúsculas separadas por `_`"
)
FORMA_CARIMBO = Forma("carimbo", _casa(CARIMBO), "ISO-8601 em UTC com sufixo `Z`")
FORMA_CONTAGEM = Forma("contagem", _inteiro_nao_negativo, "inteiro >= 0")

#: As chaves que entram no traço, e a forma de cada uma.
#:
#: A lista é fechada: uma chave fora dela é **descartada** e contada. É a mesma
#: aposta do `spikes/h3/registo.py` e da política de *logs* — uma lista de campos
#: a apagar é uma aposta em conhecer o formato de quem produz os dados, e a base
#: ganha colunas como a Meta ganha campos.
PERMITIDOS: Mapping[str, Forma] = {
    # O elo 1, dos *logs*: o turno e a mensagem.
    "tenant_id": FORMA_UUID,
    "turn_id": FORMA_UUID_OU_OPACO,
    "msg_id": FORMA_UUID_OU_OPACO,
    # O elo 2, do `audit_log`: o pedido que o turno criou.
    "entity": FORMA_IDENTIFICADOR,
    "entity_id": FORMA_UUID,
    "order_id": FORMA_UUID,
    "estado": FORMA_IDENTIFICADOR,
    # O elo 3, do `events_log`: o evento de pagamento.
    "event_id": FORMA_UUID,
    "tipo": FORMA_TIPO,
    "versao": FORMA_CONTAGEM,
    "agregado_tipo": FORMA_IDENTIFICADOR,
    "agregado_id": FORMA_UUID,
    # O elo 4, do `events_consumed` e do efeito: o consumo.
    "consumer": FORMA_IDENTIFICADOR,
    "booking_id": FORMA_UUID,
    "desfecho": FORMA_IDENTIFICADOR,
    # Carimbos, para a ordem. Nunca inteiros — ver o docstring do módulo.
    "ts": FORMA_CARIMBO,
    "ocorrido_em": FORMA_CARIMBO,
    "processado_at": FORMA_CARIMBO,
    "criado_at": FORMA_CARIMBO,
}

#: As chaves que, se vierem com a forma errada, fazem a leitura **falhar** em vez
#: de perderem a chave. São os elos: um `order_id` mal formado não é um campo
#: acessório a menos, é uma cadeia que se cala sobre o pedido que existiu.
ELOS: frozenset[str] = frozenset(
    {"tenant_id", "turn_id", "msg_id", "order_id", "entity_id", "event_id", "agregado_id"}
)


@dataclasses.dataclass(frozen=True)
class Linha:
    """Uma linha de entrada, já reduzida ao que o traço pode levar."""

    origem: str
    numero: int
    campos: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class Descarte:
    """Uma chave que caiu, e porquê. Sem o valor, pela razão do `ConteudoRecusado`."""

    origem: str
    numero: int
    chave: str
    razao: str


def detectar(texto: str) -> list[str]:
    """Os detectores que disparam neste texto. Vazio é «nenhum disparou».

    Existe como função pública de propósito: é o que o ensaio corre **primeiro
    sobre a entrada**, como canário. Sem esse par de metades, um detector que
    devolvesse sempre zero passava tudo — que é o modo de falha desta classe de
    ensaio, e o que o KAM-100 teve de corrigir.
    """
    return [nome for nome, padrao in DETECTORES if padrao.search(texto)]


def _reduzir(
    bruta: Mapping[str, Any], origem: str, numero: int, descartes: list[Descarte]
) -> Mapping[str, Any]:
    campos: dict[str, Any] = {}
    for chave, valor in bruta.items():
        forma = PERMITIDOS.get(chave)
        if forma is None:
            descartes.append(
                Descarte(origem, numero, chave, "a chave não está na lista fechada")
            )
            continue
        if forma.aceita(valor):
            campos[chave] = valor
            continue
        razao = (
            f"o valor não casa a forma `{forma.nome}` ({forma.descricao}); "
            f"comprimento {len(str(valor))}"
        )
        if chave in ELOS:
            raise ConteudoRecusado(f"{origem}:{numero}: `{chave}`: {razao}")
        descartes.append(Descarte(origem, numero, chave, razao))
    return campos


def ler_jsonl(
    caminho: Path, descartes: list[Descarte] | None = None
) -> tuple[list[Linha], list[Descarte]]:
    """Lê um ficheiro JSON-lines e reduz cada linha ao que o traço pode levar.

    Uma linha em branco salta-se; uma linha que não seja um objecto JSON falha,
    e falha alto: um ficheiro de entrada meio escrito produz uma cadeia que
    parece curta por falta de dados, e uma cadeia curta por engano é a conclusão
    errada mais fácil de tirar aqui.
    """
    caidos = [] if descartes is None else descartes
    linhas: list[Linha] = []
    origem = caminho.name
    texto = caminho.read_text(encoding="utf-8")
    for numero, bruta in enumerate(texto.splitlines(), start=1):
        if not bruta.strip():
            continue
        try:
            documento = json.loads(bruta)
        except json.JSONDecodeError as excepcao:
            raise ConteudoRecusado(
                f"{origem}:{numero}: não é um objecto JSON ({excepcao.msg})"
            ) from None
        if not isinstance(documento, dict):
            raise ConteudoRecusado(
                f"{origem}:{numero}: a linha é {type(documento).__name__}, "
                "e uma linha de JSON-lines é um objecto"
            )
        linhas.append(Linha(origem, numero, _reduzir(documento, origem, numero, caidos)))
    return linhas, caidos


@dataclasses.dataclass(frozen=True)
class Cadeia:
    """Os quatro elos de uma execução, por identificadores.

    `em_falta` é a parte que importa na demonstração: nomeia os elos que as
    entradas não sustentam, em vez de devolver uma cadeia com buracos calados.
    """

    tenant_id: str
    msg_id: str | None
    order_id: str | None
    event_id: str | None
    tipo_do_evento: str | None
    consumidores: tuple[str, ...]
    booking_id: str | None
    em_falta: tuple[str, ...]

    def completa(self) -> bool:
        return not self.em_falta


#: Os tipos de evento de pagamento que o gate da Fase 0 aceita, à letra do
#: critério G0-1: «recebe `payment.manual_confirmed` (ou `payment.confirmed` no
#: *sandbox*)». Lista fechada: um terceiro tipo não é este gate.
PAGAMENTO: frozenset[str] = frozenset({"payment.manual_confirmed", "payment.confirmed"})

#: O consumidor que o critério G0-1 exige, pelo nome com que o `events_consumed`
#: o registra. O critério é «esse evento é consumido pela vertical Serviços».
CONSUMIDOR_EXIGIDO = "agr_servicos"


def _primeiro(linhas: Iterable[Linha], chave: str) -> Any | None:
    for linha in linhas:
        if chave in linha.campos:
            return linha.campos[chave]
    return None


def encadear(linhas: Sequence[Linha]) -> list[Cadeia]:
    """Junta as linhas numa cadeia por `tenant_id`, e nomeia o que falta.

    Agrupa-se por `tenant_id` e não por conversa porque a conversa não aparece
    nas entradas: o `conversation_id` não é campo de *log* (`docs/logs.md` §2.2)
    e as consultas não o projectam. Numa demonstração há **um** *tenant* e uma
    execução, que é o cenário do `cenario.py`; com mais do que um, o agrupamento
    separa-os e o operador vê duas cadeias em vez de uma misturada.
    """
    por_tenant: dict[str, list[Linha]] = {}
    for linha in linhas:
        tenant = linha.campos.get("tenant_id")
        if isinstance(tenant, str):
            por_tenant.setdefault(tenant, []).append(linha)
    cadeias: list[Cadeia] = []
    for tenant in sorted(por_tenant):
        dele = por_tenant[tenant]
        msg_id = _primeiro(dele, "msg_id") or _primeiro(dele, "turn_id")
        order_id = _primeiro(dele, "order_id")
        if order_id is None:
            order_id = next(
                (
                    linha.campos["entity_id"]
                    for linha in dele
                    if linha.campos.get("entity") in {"order", "encomenda"}
                    and "entity_id" in linha.campos
                ),
                None,
            )
        pagamento = next(
            (linha for linha in dele if linha.campos.get("tipo") in PAGAMENTO), None
        )
        event_id = pagamento.campos.get("event_id") if pagamento else None
        tipo = pagamento.campos.get("tipo") if pagamento else None
        consumidores = tuple(
            sorted(
                {
                    linha.campos["consumer"]
                    for linha in dele
                    if "consumer" in linha.campos
                    and (event_id is None or linha.campos.get("event_id") == event_id)
                }
            )
        )
        booking_id = _primeiro(dele, "booking_id")
        em_falta: list[str] = []
        if msg_id is None:
            em_falta.append("mensagem")
        if order_id is None:
            em_falta.append("pedido")
        if event_id is None:
            em_falta.append("evento de pagamento")
        if CONSUMIDOR_EXIGIDO not in consumidores:
            em_falta.append(f"consumo por `{CONSUMIDOR_EXIGIDO}`")
        cadeias.append(
            Cadeia(
                tenant_id=tenant,
                msg_id=msg_id,
                order_id=order_id,
                event_id=event_id,
                tipo_do_evento=tipo,
                consumidores=consumidores,
                booking_id=booking_id,
                em_falta=tuple(em_falta),
            )
        )
    return cadeias


def como_json(cadeias: Sequence[Cadeia], descartes: Sequence[Descarte]) -> str:
    """O traço em JSON, com a guarda final antes de devolver o texto.

    **A guarda corre sobre o texto de saída, não sobre os campos.** Um telefone
    partido por duas chaves continua a aparecer no texto, e é assim que o
    `evt_emitir` e o `contract_diff` o fazem (`p_payload::text ~ padrao`). É a
    terceira barreira: a lista fechada é a primeira, a forma do valor é a
    segunda, e esta existe porque as duas primeiras são código que alguém pode
    alargar sem reparar.
    """
    documento = {
        "cadeias": [dataclasses.asdict(cadeia) for cadeia in cadeias],
        "descartes": [dataclasses.asdict(descarte) for descarte in descartes],
        "resumo": {
            "cadeias": len(cadeias),
            "completas": sum(1 for cadeia in cadeias if cadeia.completa()),
            "chaves_descartadas": len(descartes),
        },
    }
    texto = json.dumps(documento, ensure_ascii=False, indent=2, sort_keys=True)
    disparados = detectar(texto)
    if disparados:
        raise ConteudoRecusado(
            "a saída do traço casa os detectores "
            f"{disparados}: a lista fechada ou uma forma deixou passar um valor "
            "que não devia sair. A saída **não** é devolvida"
        )
    for cadeia in cadeias:
        for campo, valor in _identificadores(cadeia):
            fora = FORA_DO_ALFABETO.findall(valor)
            if fora:
                raise ConteudoRecusado(
                    f"`{campo}`: {len(fora)} caractere(s) fora do alfabeto "
                    "estrutural — entrou texto livre num campo que devia ser "
                    "identificador"
                )
    return texto


#: Os campos da `Cadeia` que levam valores **vindos da entrada**.
#:
#: O detector de alfabeto corre só sobre estes, e não sobre o documento inteiro.
#: Correu sobre o documento inteiro na primeira versão e o ensaio da mutação
#: apanhou-o: o `em_falta` e a `razao` de um descarte são prosa escrita por este
#: módulo — levam espaços, acentos e crases —, pelo que o detector disparava
#: sempre e **tapava** o achado que ele existe para dar. Um detector que grita
#: por tudo não distingue nada.
CAMPOS_DE_ENTRADA = (
    "tenant_id",
    "msg_id",
    "order_id",
    "event_id",
    "tipo_do_evento",
    "booking_id",
)


def _identificadores(cadeia: Cadeia) -> Iterable[tuple[str, str]]:
    for campo in CAMPOS_DE_ENTRADA:
        valor = getattr(cadeia, campo)
        if isinstance(valor, str):
            yield campo, valor
    for consumidor in cadeia.consumidores:
        yield "consumer", consumidor


def como_texto(cadeias: Sequence[Cadeia]) -> str:
    """O traço para a folha do operador: uma linha por elo, por identificadores."""
    linhas: list[str] = []
    for cadeia in cadeias:
        linhas.append(f"tenant {cadeia.tenant_id}")
        linhas.append(f"  mensagem            {cadeia.msg_id or '— em falta'}")
        linhas.append(f"  pedido              {cadeia.order_id or '— em falta'}")
        evento = (
            f"{cadeia.event_id} ({cadeia.tipo_do_evento})"
            if cadeia.event_id
            else "— em falta"
        )
        linhas.append(f"  evento de pagamento {evento}")
        consumo = ", ".join(cadeia.consumidores) if cadeia.consumidores else "— em falta"
        linhas.append(f"  consumo             {consumo}")
        linhas.append(f"  marcacao            {cadeia.booking_id or '— nao criada'}")
        if cadeia.em_falta:
            linhas.append(f"  ELOS EM FALTA: {', '.join(cadeia.em_falta)}")
    return "\n".join(linhas)


def tracar(caminhos: Sequence[Path]) -> tuple[list[Cadeia], list[Descarte]]:
    """Lê as entradas, junta-as e devolve as cadeias. Sem caminhos, `EloEmFalta`."""
    if not caminhos:
        raise EloEmFalta(
            "nenhuma entrada: o traço precisa das linhas de *log* (o elo da "
            "mensagem) e da saída das consultas do `consulta.py` (os outros três)"
        )
    todas: list[Linha] = []
    descartes: list[Descarte] = []
    for caminho in caminhos:
        linhas, _ = ler_jsonl(caminho, descartes)
        todas.extend(linhas)
    return encadear(todas), descartes
