"""O envelope de evento v1, lido e recusado (KAM-038, `docs/tecnica/06` §4).

Espelho de `packages/core-ts/src/eventos/envelope.ts`, e so da metade que um
**consumidor** precisa: ler e recusar. Nao constroi envelope nenhum — quem os
constroi e o `platform.evt_emitir`, em SQL, na mesma transaccao que o dado —, e
e por isso que nao ha aqui um `escrever_envelope`: duas fontes para a mesma
forma divergiam no primeiro campo novo.

## Porque e que o consumidor valida o que a base escreveu

Pela mesma razao que o publicador: o `events_log.envelope` e `jsonb` e um
`INSERT` directo — por `kamba_batch`, por uma migracao, por um *replay*
operacional — nao passa por `evt_emitir`. E porque entre a base e este processo
ha uma fila e um pedido HTTP, e nenhum dos dois promete o que entrega.

**Catorze campos de topo, lista fechada**, e um campo a mais **recusa-se** em
vez de se ignorar: um produtor que comece a escrever um campo novo sem subir a
`versao` e um contrato quebrado em silencio, que e o que o §6.6 proibe. Campo
novo **opcional** mantem a versao — mas opcional quer dizer declarado aqui, nao
desconhecido. A lista e a do dicionario §3.5, corrigida na emenda 1.11.

## Tres recusas que valem a pena ver antes de as ler

**O `tenant_id` sai daqui e de mais lado nenhum.** E o criterio 4 do bloco e o
ADR-015: o `SET LOCAL app.tenant_id` do `kamba_core.eventos.consumir` le
`envelope["tenant_id"]`, e esse campo so existe depois de passar por este
modulo. Um `tenant_id` escrito no `payload` nao chega la: o contrato de cada
tipo e **fechado** (`validar_payload` do KAM-007 recusa campos a mais), e o
`payload` nunca e lido como contexto.

**`classe_pii` P2 e recusada.** O §7.1 proibe-a no envelope, e e a guarda que
impede o telefone de um cliente de chegar a uma DLQ que guarda o envelope
inteiro por trinta dias.

**O dominio de `finalidades` nao se duplica aqui**, e isso e deliberado. O
`envelope.ts` tem uma tabela `FINALIDADES_POR_VERSAO` porque e ele que faz o
**roteamento por finalidade** (§7.3): o publicador compara a finalidade de uma
subscricao com as do envelope. Um consumidor nao encaminha nada — ja recebeu —,
e uma segunda copia daquela tabela era uma copia a envelhecer no dia em que a
v3 abrisse uma finalidade nova. O que se exige e a **forma**: uma lista nao
vazia de textos nao vazios, que e o que o lado TypeScript tambem exige antes de
consultar o dominio.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final

#: Os catorze campos de topo (dicionario §3.5, emenda 1.11). Lista **fechada**.
#:
#: A ordem e a do `CAMPOS_DO_ENVELOPE` do `envelope.ts`, e ha um teste de
#: paridade que la a vai buscar como texto: duas listas da mesma forma so se
#: mantem honestas se houver uma maquina a confronta-las.
CAMPOS_DO_ENVELOPE: Final = (
    "id",
    "tipo",
    "versao",
    "tenant_id",
    "ocorrido_em",
    "registado_em",
    "produtor",
    "agregado",
    "correlacao_id",
    "causa_id",
    "trace_id",
    "classe_pii",
    "finalidades",
    "payload",
)

#: Classe de dado pessoal (`docs/tecnica/06` §7.1).
CLASSES_PII: Final = ("P0", "P1", "P2")

#: A classe que **nao** pode viajar em envelope. §7.1.
CLASSE_PROIBIDA: Final = "P2"

#: Os tres campos de `agregado`. O `seq` esta **dentro** dele e nao no topo —
#: a emenda 1.11 fechou-o pelo lado do codigo, que era o unico que ja corria.
CAMPOS_DO_AGREGADO: Final = ("tipo", "id", "seq")

_UUID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

#: `familia.verbo` em minusculas (dicionario §3.5).
_TIPO = re.compile(r"\A[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\Z")


class EnvelopeInvalidoError(ValueError):
    """Um envelope que nao se reconhece. Nao se consome.

    O `codigo` e o que vai para `events_dlq.erro` e para a etiqueta da metrica:
    tem forma de identificador e **nunca** leva o valor recusado. Um envelope
    invalido pode trazer qualquer coisa — um telefone no sitio de um UUID —, e a
    mensagem nao o repete (a licao do `InvocacaoInvalidaError` do KAM-025).
    """

    def __init__(self, detalhe: str) -> None:
        super().__init__(f"envelope invalido: {detalhe}")
        self.detalhe = detalhe


@dataclass(frozen=True, slots=True)
class Agregado:
    """`agregado = {tipo, id, seq}` — a chave de ordem (§4)."""

    tipo: str
    id: str
    seq: int


@dataclass(frozen=True, slots=True)
class Envelope:
    """Os catorze campos, validados. `frozen=True` pela razao do §5.3.

    O `tenant_id` e imutavel porque e ele que decide o contexto de RLS do
    consumo: uma reescrita depois da validacao era o furo que o ADR-015 fecha.
    """

    id: str
    tipo: str
    versao: int
    tenant_id: str
    ocorrido_em: str
    registado_em: str
    produtor: str | None
    agregado: Agregado
    correlacao_id: str | None
    causa_id: str | None
    trace_id: str | None
    classe_pii: str
    finalidades: tuple[str, ...]
    payload: dict[str, Any]

    def como_mapa(self) -> dict[str, Any]:
        """A forma que o `kamba_core.eventos.consumir` le.

        Ele le `envelope["id"]`, `envelope["tipo"]`, `envelope["tenant_id"]` e
        `envelope["agregado"]["tipo"|"id"|"seq"]` — um `Mapping`, nao esta
        classe. Converte-se **aqui** e nao em quem chama para que a forma de
        saida tenha um dono so; e e por aqui que o envelope vai tambem para a
        coluna `envelope jsonb` da DLQ, pelo que os dois caminhos nao podem
        divergir.
        """
        return {
            "id": self.id,
            "tipo": self.tipo,
            "versao": self.versao,
            "tenant_id": self.tenant_id,
            "ocorrido_em": self.ocorrido_em,
            "registado_em": self.registado_em,
            "produtor": self.produtor,
            "agregado": {
                "tipo": self.agregado.tipo,
                "id": self.agregado.id,
                "seq": self.agregado.seq,
            },
            "correlacao_id": self.correlacao_id,
            "causa_id": self.causa_id,
            "trace_id": self.trace_id,
            "classe_pii": self.classe_pii,
            "finalidades": list(self.finalidades),
            "payload": dict(self.payload),
        }


def _objecto(valor: object, campo: str) -> dict:
    if not isinstance(valor, dict):
        raise EnvelopeInvalidoError(f"`{campo}` tem de ser um objecto")
    return valor


def _texto(valor: object, campo: str) -> str:
    if not isinstance(valor, str) or valor == "":
        raise EnvelopeInvalidoError(f"`{campo}` tem de ser texto nao vazio")
    return valor


def _texto_ou_nulo(valor: object, campo: str) -> str | None:
    return None if valor is None else _texto(valor, campo)


def _uuid(valor: object, campo: str) -> str:
    bruto = _texto(valor, campo)
    if not _UUID.fullmatch(bruto):
        raise EnvelopeInvalidoError(f"`{campo}` nao e um UUID canonico")
    return bruto


def _uuid_ou_nulo(valor: object, campo: str) -> str | None:
    return None if valor is None else _uuid(valor, campo)


def _inteiro(valor: object, campo: str, minimo: int) -> int:
    # `bool` e um `int` em Python, e um `seq` que valha `True` e um envelope
    # construido por outra coisa que nao o `evt_emitir`. O TypeScript nao tem
    # este caso e por isso nao tem esta linha.
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
        raise EnvelopeInvalidoError(f"`{campo}` tem de ser um inteiro >= {minimo}")
    return valor


def ler_envelope(valor: object) -> Envelope:
    """Le e valida um envelope v1. Levanta `EnvelopeInvalidoError`.

    Aceita o objecto ja desserializado (o que uma coluna `jsonb` devolve) ou o
    texto JSON. Recusa, por esta ordem: o que nao e JSON, o que nao e objecto, o
    campo de topo desconhecido, o campo obrigatorio em falta, o tipo errado, a
    `classe_pii` P2 e as `finalidades` vazias.

    **A ordem importa para a mensagem e nao para a decisao**: todas recusam. O
    campo desconhecido vem antes do campo em falta porque um envelope de uma
    versao futura falha pelos dois, e o primeiro e o diagnostico util.
    """
    cru = valor
    if isinstance(cru, (str, bytes)):
        try:
            cru = json.loads(cru)
        except (ValueError, UnicodeDecodeError):
            raise EnvelopeInvalidoError("nao e JSON") from None
    bruto = _objecto(cru, "envelope")

    demais = sorted(set(bruto) - set(CAMPOS_DO_ENVELOPE))
    if demais:
        # Os **nomes** das chaves a mais cabem na mensagem: sao chaves e nao
        # valores. Um valor nunca entra, e e por isso que o `demais` se calcula
        # sobre as chaves e nao sobre os pares.
        raise EnvelopeInvalidoError(f"campo(s) de topo desconhecido(s): {demais}")
    em_falta = sorted(set(CAMPOS_DO_ENVELOPE) - set(bruto))
    if em_falta:
        raise EnvelopeInvalidoError(f"campo(s) de topo em falta: {em_falta}")

    classe = _texto(bruto["classe_pii"], "classe_pii")
    if classe not in CLASSES_PII:
        raise EnvelopeInvalidoError("`classe_pii` desconhecida")
    if classe == CLASSE_PROIBIDA:
        raise EnvelopeInvalidoError(
            f"`classe_pii` {CLASSE_PROIBIDA} e proibida no envelope "
            "(`docs/tecnica/06` §7.1)"
        )

    finalidades = bruto["finalidades"]
    if not isinstance(finalidades, list) or not finalidades:
        raise EnvelopeInvalidoError("`finalidades` tem de ter ao menos uma")
    finais = tuple(
        _texto(f, f"finalidades[{i}]") for i, f in enumerate(finalidades)
    )

    tipo = _texto(bruto["tipo"], "tipo")
    if not _TIPO.fullmatch(tipo):
        raise EnvelopeInvalidoError("`tipo` tem de ser `familia.verbo` em minusculas")

    agregado = _objecto(bruto["agregado"], "agregado")
    demais_do_agregado = sorted(set(agregado) - set(CAMPOS_DO_AGREGADO))
    if demais_do_agregado:
        raise EnvelopeInvalidoError(
            f"campo(s) desconhecido(s) em `agregado`: {demais_do_agregado}"
        )

    return Envelope(
        id=_uuid(bruto["id"], "id"),
        tipo=tipo,
        versao=_inteiro(bruto["versao"], "versao", 1),
        tenant_id=_uuid(bruto["tenant_id"], "tenant_id"),
        ocorrido_em=_texto(bruto["ocorrido_em"], "ocorrido_em"),
        registado_em=_texto(bruto["registado_em"], "registado_em"),
        produtor=_texto_ou_nulo(bruto["produtor"], "produtor"),
        agregado=Agregado(
            tipo=_texto(agregado.get("tipo"), "agregado.tipo"),
            id=_texto(agregado.get("id"), "agregado.id"),
            seq=_inteiro(agregado.get("seq"), "agregado.seq", 1),
        ),
        correlacao_id=_uuid_ou_nulo(bruto["correlacao_id"], "correlacao_id"),
        causa_id=_uuid_ou_nulo(bruto["causa_id"], "causa_id"),
        trace_id=_texto_ou_nulo(bruto["trace_id"], "trace_id"),
        classe_pii=classe,
        finalidades=finais,
        payload=dict(_objecto(bruto["payload"], "payload")),
    )
