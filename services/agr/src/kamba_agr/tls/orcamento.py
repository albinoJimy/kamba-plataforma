"""O Orcamento expresso contra a base: pedir, responder, enviar (KAM-123).

**Vive na ToolLayer, e nao ao lado das regras**, pela regra do §6.1 e do
ADR-015 que o `lint_arch` (`tool_schema.py`) impoe: a TLS e a unica via de
escrita dos agentes no `platform`. A `quote_requests` guarda o preco que o dono
fixou, que e dado de negocio e nao plano de controlo — e o KAM-118 escreveu-o
ao dispensar a `owner_actions`: as escritas dos modulos «passam pela
ToolLayer». As regras puras ficam em `kamba_agr/orcamento/regras.py`.

    pedir(ligacao, tenant, contacto, conversa, sku, quantidade, agora)  -> Pedido
    pendentes(ligacao, tenant)                                          -> [Pendente]
    responder(ligacao, tenant, dono, quote_id, valor, validade, condicoes, agora)
                                                                        -> Resposta
    enviar(ligacao, tenant, dono, action_id, porta, agora)              -> Envio
    libertar_da_janela(ligacao, tenant, contacto, porta, agora)         -> [Envio]
    expirar_vencidos(ligacao, tenant, agora)                            -> int
    cancelar(ligacao, tenant, dono, quote_id)                           -> bool

## A idempotencia e da base

* **Pedir duas vezes da o mesmo `quote_id`** (criterio 1). A pergunta «ha um
  pedido aberto deste contacto e deste `sku` nos ultimos dez minutos?» e a
  escrita correm sob uma tranca consultiva **da transaccao**, com a chave
  `tenant|contacto|sku`: duas mensagens concorrentes serializam-se ali, e a
  segunda le a linha que a primeira deixou. O evento `quote.requested` e o
  consumo de `orcamentos_mes` vao na **mesma** transaccao que a linha — um
  pedido repetido nao emite nem consome.
* **Enviar duas vezes envia uma** (criterio 5). O botao passa primeiro pelo
  `confirmar` do KAM-118, que e um *compare-and-set*; e o envio tranca a linha
  (`FOR UPDATE`) e so anda de `respondido`. O Outbound recebe a chave
  `orcamento:{quote_id}:{marca}`, pelo que uma reentrega nao duplica a mensagem.

## O botao antigo nao envia o valor novo

O `ref` da accao `enviar_proposta` e `{quote_id}/{marca}`, e a `marca` e o
`respondido_at` da resposta em microssegundos. Se o dono corrigir o valor, a
resposta nova tem outra marca e pede botao novo; o botao velho, mesmo
confirmado, encontra outra marca na linha e devolve `desactualizado` — nunca
envia o valor que o dono nao confirmou.

## O tenant vem do contexto, e vai nas duas barreiras

Cada instrucao corre dentro de `tenant_guard.tx` (a RLS `FORCE` da revisao) e
leva o `tenant_id` no predicado, pela disciplina do `dono/accoes.py`.

## O que nao se escreve em registo nenhum

Nada deste modulo escreve *logs*, e as excepcoes levam um codigo e nunca um
valor nem um texto do dono ou do cliente.
"""

from __future__ import annotations

import datetime
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.ten.entitlements import Resultado, consume_limit

from ..dono import accoes
from ..eventos.notificacao import Notificacao
from ..orcamento import regras
from ..validador.render import PRECO_SOB_CONSULTA, Oferta
from ..validador.veredicto import Policy, validar
from .erros import Fact

#: O modulo e a chave de limite do TEN (`kamba_core/modulos/uso.py`).
MODULO: Final = "orcamento"
CHAVE_DE_LIMITE: Final = "orcamentos_mes"

#: Os dois eventos do dicionario §3.7.
EVENTO_PEDIDO: Final = "quote.requested"
EVENTO_ENVIADO: Final = "quote.sent"
#: O `agregado.tipo` dos dois contratos.
AGREGADO: Final = "quote"

#: O *template utility* que substitui a proposta com a janela do cliente fechada
#: (criterio 8): «o seu orcamento esta pronto, responda para ver», **sem
#: numero**. O nome e *proposta*; a aprovacao pela Meta e a classificacao como
#: utility sao NAO VERIFICADAS, e o `config/templates_por_modulo.yaml` so o
#: lista quando houver catalogo de *templates* (credor no bloco).
TEMPLATE_ORCAMENTO_PRONTO: Final = "orcamento_pronto"

#: O tipo de accao do KAM-118 que este modulo usa.
TIPO_DA_ACCAO: Final = "enviar_proposta"

# Os desfechos do `enviar`. Lista **fechada**: o grafo do dono escolhe a frase.
ENVIADO: Final = "enviado"
AGUARDA_JANELA: Final = "aguarda_janela"
NAO_ENVIADO: Final = "nao_enviado"
JA_ENVIADO: Final = "ja_enviado"
DESACTUALIZADO: Final = "desactualizado"
NAO_E_ORCAMENTO: Final = "nao_e_orcamento"
DESFECHOS_DO_ENVIO: Final = (
    ENVIADO,
    AGUARDA_JANELA,
    NAO_ENVIADO,
    JA_ENVIADO,
    DESACTUALIZADO,
    NAO_E_ORCAMENTO,
)

# Os codigos de recusa do `responder` e do `pedir`.
NAO_E_DONO: Final = "nao_e_dono"
DESCONHECIDO: Final = "desconhecido"
FECHADO: Final = "fechado"
VALIDADE_NO_PASSADO: Final = "validade_no_passado"
SEM_ORCAMENTOS: Final = "sem_orcamentos"
FORA_DO_CATALOGO: Final = "fora_do_catalogo"

_UUID: Final = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_REF: Final = re.compile(
    r"\A([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(\d{1,20})\Z"
)

# ------------------------------------------------------------------- o SQL
#
# Em constantes de modulo, pela razao do `dono/accoes.py`: a suite de BD
# (`db/tests_agr/test_quote_requests.py`) corre **estas**.

#: A tranca da repeticao: uma por `tenant|contacto|sku`, ate ao fim da
#: transaccao.
SQL_TRANCA: Final = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"

#: So se pede orcamento de um produto do **catalogo deste tenant**, publicado e
#: `sob_consulta` (criterio 10: bens fora do catalogo nao sao ingeridos). Um
#: `fixo` ou um `a_partir_de` tem preco publicado, e um `sku` que nao existe nao
#: e um pedido: e texto de alguem.
SQL_OFERTA_SOB_CONSULTA: Final = (
    "SELECT 1 FROM platform.offer_terms "
    "WHERE tenant_id = %s AND sku = %s AND preco_tipo = 'sob_consulta' "
    "AND estado = 'publicado' AND deleted_at IS NULL"
)

SQL_PEDIDO_RECENTE: Final = (
    "SELECT quote_id FROM platform.quote_requests "
    "WHERE tenant_id = %s AND contact_id = %s AND sku = %s "
    "AND estado IN ('pedido', 'respondido', 'aguarda_janela') AND criado_at > %s "
    "ORDER BY criado_at DESC LIMIT 1"
)

SQL_INSERIR: Final = (
    "INSERT INTO platform.quote_requests "
    "(tenant_id, contact_id, conversation_id, sku, quantidade) "
    "VALUES (%s, %s, %s, %s, %s) RETURNING quote_id"
)

#: O `evt_emitir` da `0004`, com classe `P0` e finalidade `transacao`: o
#: *payload* leva identificadores e o valor, nunca texto nem telefone.
SQL_EMITIR: Final = (
    "SELECT platform.evt_emitir(%s, 1::smallint, %s::uuid, 'quote', %s, %s::jsonb, "
    "'P0', '{transacao}'::text[])"
)

SQL_PENDENTES: Final = (
    "SELECT quote_id, sku, quantidade, estado, criado_at FROM platform.quote_requests "
    "WHERE tenant_id = %s AND estado IN ('pedido', 'respondido', 'aguarda_janela') "
    "ORDER BY criado_at LIMIT %s"
)

SQL_TRANCAR_PEDIDO: Final = (
    "SELECT estado, contact_id, conversation_id, sku, valor_minor, validade_ate, "
    "condicoes, respondido_at FROM platform.quote_requests "
    "WHERE tenant_id = %s AND quote_id = %s FOR UPDATE"
)

SQL_RESPONDER: Final = (
    "UPDATE platform.quote_requests SET estado = 'respondido', valor_minor = %s, "
    "validade_ate = %s, condicoes = %s, respondido_at = %s "
    "WHERE tenant_id = %s AND quote_id = %s AND estado IN ('pedido', 'respondido') "
    "RETURNING respondido_at"
)

SQL_MARCAR_ENVIADO: Final = (
    "UPDATE platform.quote_requests SET estado = 'enviado', enviado_at = %s "
    "WHERE tenant_id = %s AND quote_id = %s AND estado IN ('respondido', 'aguarda_janela')"
)

SQL_MARCAR_JANELA: Final = (
    "UPDATE platform.quote_requests SET estado = 'aguarda_janela' "
    "WHERE tenant_id = %s AND quote_id = %s AND estado = 'respondido'"
)

SQL_A_ESPERA_DA_JANELA: Final = (
    "SELECT quote_id FROM platform.quote_requests "
    "WHERE tenant_id = %s AND contact_id = %s AND estado = 'aguarda_janela' "
    "ORDER BY criado_at"
)

#: Uma resposta cuja validade passou expira. Um `pedido` sem resposta **nao**
#: expira aqui: continua visivel ao dono (criterio 2), e o que lhe acontece ao
#: fim de vinte e quatro horas e a mensagem neutra do criterio 9.
SQL_EXPIRAR: Final = (
    "UPDATE platform.quote_requests SET estado = 'expirado' "
    "WHERE tenant_id = %s AND estado IN ('respondido', 'aguarda_janela') "
    "AND validade_ate < %s"
)

SQL_CANCELAR: Final = (
    "UPDATE platform.quote_requests SET estado = 'cancelado' "
    "WHERE tenant_id = %s AND quote_id = %s "
    "AND estado IN ('pedido', 'respondido', 'aguarda_janela') RETURNING quote_id"
)

#: A accao confirmada do dono: o tipo e o `ref` dizem que pedido e que resposta.
SQL_ACCAO_CONFIRMADA: Final = (
    "SELECT tipo, ref FROM platform.owner_actions "
    "WHERE tenant_id = %s AND action_id = %s AND contact_id = %s AND estado = 'confirmada'"
)

#: O ultimo pedido de um cliente, para o «aceito» do criterio 9.
SQL_ULTIMO_DO_CLIENTE: Final = (
    "SELECT quote_id, estado FROM platform.quote_requests "
    "WHERE tenant_id = %s AND contact_id = %s ORDER BY criado_at DESC LIMIT 1"
)


class OrcamentoRecusadoError(ValueError):
    """O pedido ou a resposta nao se fazem. O `codigo` nunca leva valores."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class Pedido:
    quote_id: str
    #: `False` quando o pedido repetido devolveu o que ja havia.
    novo: bool


@dataclass(frozen=True, slots=True)
class Pendente:
    quote_id: str
    referencia: str
    sku: str
    quantidade: int | None
    estado: str
    criado_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class Resposta:
    quote_id: str
    valor_minor: int
    validade_ate: datetime.date
    condicoes: str | None
    #: O `action_id` do botao `confirm:{action_id}` que envia esta resposta.
    action_id: str
    #: A pre-visualizacao: o texto exacto que o cliente vai ler.
    previsao: str


@dataclass(frozen=True, slots=True)
class Envio:
    desfecho: str
    quote_id: str | None = None


class _ClienteDeCursor:
    """O `ClienteSql` do TEN sobre um cursor DB-API (a forma do `tls/camada.py`)."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> Resultado:
        self._cursor.execute(sql, tuple(parametros))
        descricao = self._cursor.description
        if not descricao:
            return Resultado(linhas=(), contagem=self._cursor.rowcount)
        nomes = [coluna[0] for coluna in descricao]
        linhas: list[Mapping[str, object]] = [
            dict(zip(nomes, linha, strict=True)) for linha in self._cursor.fetchall()
        ]
        return Resultado(linhas=linhas, contagem=self._cursor.rowcount)


def _texto(valor: Any) -> str:
    return str(valor).lower() if valor is not None else ""


def _emitir(cursor: Any, tipo: str, tenant_id: str, quote_id: str, payload: dict) -> None:
    cursor.execute(
        SQL_EMITIR, (tipo, tenant_id, quote_id, json.dumps(payload, sort_keys=True))
    )


def _marca(respondido_at: datetime.datetime) -> str:
    """O `respondido_at` em microssegundos UTC: a versao da resposta."""
    return str(int(respondido_at.timestamp() * 1_000_000))


def ref_da_resposta(quote_id: str, respondido_at: datetime.datetime) -> str:
    """O `ref` da accao `enviar_proposta`: `{quote_id}/{marca}`."""
    return f"{quote_id}/{_marca(respondido_at)}"


def _exigir_dono(cursor: Any, tenant_id: str, contact_id: str) -> None:
    cursor.execute(accoes.SQL_PAPEL_DO_CONTACTO, (tenant_id, contact_id))
    linha = cursor.fetchone()
    if linha is None or linha[0] != accoes.PAPEL_DONO:
        raise OrcamentoRecusadoError(NAO_E_DONO)


# ------------------------------------------------------------------- pedir


def pedir(
    ligacao: Any,
    tenant_id: str,
    contact_id: str,
    conversation_id: str,
    sku: str,
    quantidade: int | None,
    agora: datetime.datetime,
) -> Pedido:
    """O `request_quote`: abre o pedido ou devolve o aberto ha menos de dez minutos.

    So para um `sku` publicado `sob_consulta` do catalogo do tenant
    (`fora_do_catalogo` em qualquer outro caso). Um pedido novo consome **um** de `orcamentos_mes` (chave de idempotencia
    `orcamento:{quote_id}`) e emite `quote.requested`, na mesma transaccao. Sem
    entitlement ou com o balde esgotado levanta `sem_orcamentos` e nada fica.
    """
    if not isinstance(sku, str) or not sku.strip():
        raise OrcamentoRecusadoError(DESCONHECIDO)
    if quantidade is not None and (
        not isinstance(quantidade, int) or isinstance(quantidade, bool) or quantidade < 1
    ):
        quantidade = None
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_OFERTA_SOB_CONSULTA, (tenant_id, sku))
        if cursor.fetchone() is None:
            raise OrcamentoRecusadoError(FORA_DO_CATALOGO)
        cursor.execute(SQL_TRANCA, (f"{tenant_id}|{contact_id}|{sku}",))
        cursor.execute(
            SQL_PEDIDO_RECENTE,
            (tenant_id, contact_id, sku, agora - regras.JANELA_DE_REPETICAO),
        )
        linha = cursor.fetchone()
        if linha is not None:
            return Pedido(quote_id=_texto(linha[0]), novo=False)
        cursor.execute(SQL_INSERIR, (tenant_id, contact_id, conversation_id, sku, quantidade))
        quote_id = _texto(cursor.fetchone()[0])
        consumo = consume_limit(
            _ClienteDeCursor(cursor),
            tenant_id,
            CHAVE_DE_LIMITE,
            1,
            f"orcamento:{quote_id}",
            modulo=MODULO,
        )
        if not consumo.aceite:
            raise OrcamentoRecusadoError(SEM_ORCAMENTOS)
        payload: dict[str, Any] = {"quote_id": quote_id, "contact_id": _texto(contact_id), "sku": sku}
        if quantidade is not None:
            payload["quantidade"] = quantidade
        _emitir(cursor, EVENTO_PEDIDO, tenant_id, quote_id, payload)
        return Pedido(quote_id=quote_id, novo=True)


def pendentes(ligacao: Any, tenant_id: str, limite: int = 20) -> list[Pendente]:
    """Os pedidos que esperam o dono, do mais antigo para o mais novo (criterio 2)."""
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_PENDENTES, (tenant_id, limite))
        linhas = cursor.fetchall()
    return [
        Pendente(
            quote_id=_texto(q),
            referencia=regras.referencia_interna(q),
            sku=sku,
            quantidade=quantidade,
            estado=estado,
            criado_at=criado_at,
        )
        for q, sku, quantidade, estado, criado_at in linhas
    ]


def por_referencia(ligacao: Any, tenant_id: str, referencia: str) -> str | None:
    """O `quote_id` de um `ORC-…` aberto deste tenant, ou `None`.

    A referencia sao trinta e dois bits do `quote_id`: casa-se contra os abertos
    deste tenant, e mais de um e `None` — o dono escolhe pela lista.
    """
    for pendente in pendentes(ligacao, tenant_id, limite=500):
        if pendente.referencia == referencia.strip().upper():
            return pendente.quote_id
    return None


# --------------------------------------------------------------- responder


def responder(
    ligacao: Any,
    tenant_id: str,
    contact_id: str,
    quote_id: str,
    valor_minor: int,
    validade_ate: datetime.date | None,
    condicoes: str | None,
    agora: datetime.datetime,
) -> Resposta:
    """O `submit_quote`: o dono fixa o valor; devolve o eco e o botao de envio.

    O `valor_minor` ja vem do `regras.ler_valor_do_dono`; as `condicoes` passam
    aqui pelo `conferir_condicoes`. A validade por omissao e a do
    `regras.validade_por_omissao`. **O sistema nao calcula nada**: o valor
    gravado e o valor recebido.
    """
    if not isinstance(quote_id, str) or not _UUID.fullmatch(quote_id):
        raise OrcamentoRecusadoError(DESCONHECIDO)
    if not isinstance(valor_minor, int) or isinstance(valor_minor, bool) or not (
        0 < valor_minor <= regras.VALOR_MAXIMO_MINOR
    ):
        raise OrcamentoRecusadoError(regras.VALOR_FORA_DO_INTERVALO)
    limpas = regras.conferir_condicoes(condicoes)
    validade = validade_ate or regras.validade_por_omissao(agora)
    if validade <= regras.hoje_em_luanda(agora):
        raise OrcamentoRecusadoError(VALIDADE_NO_PASSADO)
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        _exigir_dono(cursor, tenant_id, contact_id)
        cursor.execute(SQL_TRANCAR_PEDIDO, (tenant_id, quote_id))
        linha = cursor.fetchone()
        if linha is None:
            raise OrcamentoRecusadoError(DESCONHECIDO)
        if linha[0] not in (regras.PEDIDO, regras.RESPONDIDO):
            raise OrcamentoRecusadoError(FECHADO)
        sku = linha[3]
        cursor.execute(
            SQL_RESPONDER, (valor_minor, validade, limpas, agora, tenant_id, quote_id)
        )
        respondido_at = cursor.fetchone()[0]
    action_id = accoes.propor(
        ligacao, tenant_id, contact_id, TIPO_DA_ACCAO, ref_da_resposta(quote_id, respondido_at), agora
    )
    previsao = texto_da_proposta(quote_id, sku, valor_minor, validade, limpas, agora)
    return Resposta(
        quote_id=quote_id,
        valor_minor=valor_minor,
        validade_ate=validade,
        condicoes=limpas,
        action_id=action_id,
        previsao=previsao,
    )


# ------------------------------------------------------------- a proposta


def facts_da_proposta(
    quote_id: str, sku: str, valor_minor: int, validade_ate: datetime.date, agora: datetime.datetime
) -> tuple[Fact, Fact]:
    """Os dois *facts* da proposta: o `quote_price` e a data de validade."""
    instante = agora.astimezone(datetime.UTC).isoformat()
    return (
        Fact(fact_id=quote_id, kind="quote_price", value=valor_minor, retrieved_at=instante, sku=sku),
        Fact(
            fact_id=f"{quote_id}:validade",
            kind="datetime",
            value=regras.instante_da_validade(validade_ate),
            retrieved_at=instante,
        ),
    )


class PropostaInvalidaError(RuntimeError):
    """A proposta preenchida nao passa o validador. Defeito, e nunca sai."""


def texto_da_proposta(
    quote_id: str,
    sku: str,
    valor_minor: int,
    validade_ate: datetime.date,
    condicoes: str | None,
    agora: datetime.datetime,
) -> str:
    """O texto da proposta, pelo *renderer* por referencia **e** pelo validador.

    O validador corre com o produto como `sob_consulta` — que e o que ele e —,
    pelo que o unico valor aceite na linha do `sku` e o do *fact* `quote_price`
    daquele `sku`: um total, um desconto ou outro numero recusam.
    """
    facts = facts_da_proposta(quote_id, sku, valor_minor, validade_ate, agora)
    modelo = regras.modelo_da_proposta(quote_id=quote_id, sku=sku, condicoes=condicoes)
    texto = regras.preencher(modelo, facts)
    ofertas = (Oferta(sku=sku, nome=regras.NOME_NEUTRO, preco_tipo=PRECO_SOB_CONSULTA),)
    veredicto = validar(texto, facts, Policy(), ofertas)
    if not veredicto.ok:
        raise PropostaInvalidaError(",".join(veredicto.codigos))
    return texto


# ------------------------------------------------------------------ enviar


def _entregar(
    cursor: Any,
    tenant_id: str,
    quote_id: str,
    linha: tuple,
    porta: Any,
    agora: datetime.datetime,
) -> str:
    """Envia a proposta de uma linha trancada e muda o estado pelo desfecho."""
    _estado, contact_id, conversation_id, sku, valor, validade, condicoes, respondido_at = linha
    texto = texto_da_proposta(quote_id, sku, valor, validade, condicoes, agora)
    desfecho = porta.notificar(
        tenant_id=tenant_id,
        notificacao=Notificacao(
            contact_id=_texto(contact_id),
            conversation_id=_texto(conversation_id),
            texto=texto,
            template=TEMPLATE_ORCAMENTO_PRONTO,
        ),
        chave=f"orcamento:{quote_id}:{_marca(respondido_at)}",
    )
    if desfecho == "livre":
        cursor.execute(SQL_MARCAR_ENVIADO, (agora, tenant_id, quote_id))
        _emitir(
            cursor,
            EVENTO_ENVIADO,
            tenant_id,
            quote_id,
            {
                "quote_id": quote_id,
                "contact_id": _texto(contact_id),
                "sku": sku,
                "valor_minor": valor,
                "currency": "AOA",
                "validade_ate": validade.isoformat(),
            },
        )
        return ENVIADO
    if desfecho == "template":
        cursor.execute(SQL_MARCAR_JANELA, (tenant_id, quote_id))
        return AGUARDA_JANELA
    # `sem_template` (ou qualquer outro): nada saiu, e o pedido fica como estava.
    return NAO_ENVIADO


def enviar(
    ligacao: Any,
    tenant_id: str,
    contact_id: str,
    action_id: str,
    porta: Any,
    agora: datetime.datetime,
) -> Envio:
    """O `send_quote`, depois de o botao ter dado `confirmada` no portao do KAM-118.

    Le a accao confirmada **deste** dono; se for `enviar_proposta`, tranca o
    pedido e envia **so** se a resposta for a mesma que o botao confirmou.
    """
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_ACCAO_CONFIRMADA, (tenant_id, action_id, contact_id))
        accao = cursor.fetchone()
        if accao is None or accao[0] != TIPO_DA_ACCAO:
            return Envio(NAO_E_ORCAMENTO)
        casado = _REF.fullmatch(accao[1] or "")
        if casado is None:
            return Envio(NAO_E_ORCAMENTO)
        quote_id, marca = casado.group(1), casado.group(2)
        cursor.execute(SQL_TRANCAR_PEDIDO, (tenant_id, quote_id))
        linha = cursor.fetchone()
        if linha is None:
            return Envio(NAO_E_ORCAMENTO)
        if linha[0] in (regras.ENVIADO, regras.AGUARDA_JANELA):
            return Envio(JA_ENVIADO, quote_id)
        if linha[0] != regras.RESPONDIDO or _marca(linha[7]) != marca:
            return Envio(DESACTUALIZADO, quote_id)
        return Envio(_entregar(cursor, tenant_id, quote_id, linha, porta, agora), quote_id)


def libertar_da_janela(
    ligacao: Any, tenant_id: str, contact_id: str, porta: Any, agora: datetime.datetime
) -> list[Envio]:
    """O valor sai **depois** de o cliente responder (criterio 8).

    Chama-se quando chega uma mensagem do cliente: cada proposta dele em
    `aguarda_janela` tenta sair outra vez, agora com a janela aberta. A chave do
    Outbound e outra (`…:janela`) da do *template*, que ja saiu.
    """
    envios: list[Envio] = []
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_A_ESPERA_DA_JANELA, (tenant_id, contact_id))
        ids = [_texto(q) for (q,) in cursor.fetchall()]
        for quote_id in ids:
            cursor.execute(SQL_TRANCAR_PEDIDO, (tenant_id, quote_id))
            linha = cursor.fetchone()
            if linha is None or linha[0] != regras.AGUARDA_JANELA:
                continue
            texto = texto_da_proposta(quote_id, linha[3], linha[4], linha[5], linha[6], agora)
            desfecho = porta.notificar(
                tenant_id=tenant_id,
                notificacao=Notificacao(
                    contact_id=_texto(linha[1]),
                    conversation_id=_texto(linha[2]),
                    texto=texto,
                    template=TEMPLATE_ORCAMENTO_PRONTO,
                ),
                chave=f"orcamento:{quote_id}:{_marca(linha[7])}:janela",
            )
            if desfecho != "livre":
                envios.append(Envio(AGUARDA_JANELA, quote_id))
                continue
            cursor.execute(SQL_MARCAR_ENVIADO, (agora, tenant_id, quote_id))
            _emitir(
                cursor,
                EVENTO_ENVIADO,
                tenant_id,
                quote_id,
                {
                    "quote_id": quote_id,
                    "contact_id": _texto(linha[1]),
                    "sku": linha[3],
                    "valor_minor": linha[4],
                    "currency": "AOA",
                    "validade_ate": linha[5].isoformat(),
                },
            )
            envios.append(Envio(ENVIADO, quote_id))
    return envios


# ------------------------------------------------- expirar, cancelar, aceitar


def expirar_vencidos(ligacao: Any, tenant_id: str, agora: datetime.datetime) -> int:
    """Fecha `expirado` as respostas cuja validade passou. Devolve quantas."""
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_EXPIRAR, (tenant_id, regras.hoje_em_luanda(agora)))
        return max(cursor.rowcount, 0)


def cancelar(ligacao: Any, tenant_id: str, contact_id: str, quote_id: str) -> bool:
    """O dono cancela um pedido aberto. `False` se ja estava fechado."""
    if not isinstance(quote_id, str) or not _UUID.fullmatch(quote_id):
        raise OrcamentoRecusadoError(DESCONHECIDO)
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        _exigir_dono(cursor, tenant_id, contact_id)
        cursor.execute(SQL_CANCELAR, (tenant_id, quote_id))
        return cursor.fetchone() is not None


def ultimo_do_cliente(ligacao: Any, tenant_id: str, contact_id: str) -> tuple[str, str] | None:
    """`(quote_id, estado)` do ultimo pedido do cliente, ou `None`.

    E o que o grafo precisa para o «aceito» do criterio 9: **nenhuma** aceitacao
    cria pedido; um orcamento `expirado` ou `cancelado` nao se aceita, e um
    `enviado` vai ao dono com o contexto (o *handoff*), que e quem fecha.
    """
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_ULTIMO_DO_CLIENTE, (tenant_id, contact_id))
        linha = cursor.fetchone()
    return None if linha is None else (_texto(linha[0]), linha[1])


__all__ = [
    "CHAVE_DE_LIMITE",
    "DESFECHOS_DO_ENVIO",
    "EVENTO_ENVIADO",
    "EVENTO_PEDIDO",
    "Envio",
    "MODULO",
    "OrcamentoRecusadoError",
    "Pedido",
    "Pendente",
    "PropostaInvalidaError",
    "Resposta",
    "TEMPLATE_ORCAMENTO_PRONTO",
    "cancelar",
    "enviar",
    "expirar_vencidos",
    "facts_da_proposta",
    "libertar_da_janela",
    "pedir",
    "pendentes",
    "por_referencia",
    "ref_da_resposta",
    "responder",
    "texto_da_proposta",
    "ultimo_do_cliente",
]
