"""A rota de entrega do IDX: do corpo do `/internal/event` ao efeito (KAM-194).

E a decisao toda, e testa-se sem fila nenhuma. A casca da fila e TypeScript
(`packages/core-ts/src/eventos/ponte.ts`): tira o *job* de `evt.idx.p<n>` e faz
`POST` com o corpo de `kamba_core.eventos.entrega`. O que corre aqui e, por
ordem:

    ler o corpo                     -> invalido: 400, e acabou
    ponteiros com forma de UUID     -> nao: 400
    o envelope (do corpo, ou do arquivo se o *job* e do reconciliador)
                                    -> o arquivo nao o tem: 503, e DLQ no fim
    a forma do envelope             -> ilegivel: DLQ sem envelope, 200
    confrontar os ponteiros         -> divergem: DLQ sem envelope, 200
    o tipo subscrito                -> nao: DLQ com envelope, 200
    consumir_evento (KAM-061)       -> aplicado | duplicado: 200
                                    -> falhou: 503 com `Retry-After`, e DLQ
                                       na sexta tentativa

## Tres codigos, e cada um diz a fila o que fazer

E a tabela do `/internal/event` do AGR (KAM-038), e de proposito a mesma: a
casca e uma so para os dois. **200** «tratado, nao repitas» — inclui o que foi
para a DLQ, que foi tratado; **400** «o corpo nao e uma entrega»; **503** com
`Retry-After` «volta». Um evento que foi para a DLQ e respondesse 5xx punha o
BullMQ a repetir o que ja esta registado.

## A idempotencia nao assenta na fila

As garantias de entrega do BullMQ continuam NAO VERIFICADAS (L6). Quem garante
«uma vez» e a marca em `platform.events_consumed`, dentro da transaccao do
`consumir` (KAM-006) — o efeito e a marca caem juntos. E **e por isso que a
casca nao toca na base**: se ela marcasse, o lado Python via sempre
`duplicado`, que e o defeito que o KAM-193 mediu no `worker-canal`.

## Quem conta as tentativas

A fila (`tentativas` do corpo, o `attemptsMade + 1` do *job*). Esgotadas as
seis da escada do §6.4 (`TENTATIVAS`), abre-se a DLQ e responde-se 200: o
evento fica visivel e reprocessavel, e a fila larga-o.

## O que este modulo nao faz

**Nao regista nada.** Nem o `event_id`, nem o `tenant_id`, nem o envelope, nem o
erro: o que sai daqui e o desfecho, que e constante deste codigo e de lista
fechada. Quem decide registar e o processo, com esse desfecho.

**Nao le texto de consulta**, que nao passa por aqui: o IDX recebe eventos do
catalogo e do *tenant*, e a pesquisa corre noutro processo.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.eventos.consumo import (
    ADIAMENTO_POR_OMISSAO,
    TENTATIVAS,
    Adiar,
    Metricas,
    atraso_da_tentativa_do_consumidor,
)
from kamba_core.eventos.entrega import (
    SQL_ENVELOPE_DO_ARQUIVO,
    Entrega,
    EntregaInvalidaError,
    exigir_ponteiros_uuid,
    ler_entrega,
)
from kamba_core.eventos.ligacao import ClienteDaLigacao

from . import consumidor

#: A entrada na DLQ. A mesma instrucao do `SQL_ABRIR_DLQ` do AGR e do `dlq.ts`:
#: repetir o mesmo par com a entrada aberta e *no-op*.
SQL_ABRIR_DLQ: Final = """
  INSERT INTO platform.events_dlq
    (consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas)
  VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
      ON CONFLICT (consumer, event_id) WHERE estado = 'aberta' DO NOTHING
"""

#: Os motivos que este consumidor escreve na coluna `erro`. Lista **fechada**:
#: nunca a mensagem de uma excepcao, que pode trazer conteudo.
MOTIVO_ENVELOPE_INVALIDO: Final = "envelope_invalido"
MOTIVO_TIPO_DESCONHECIDO: Final = "tipo_desconhecido"
MOTIVO_TENTATIVAS_ESGOTADAS: Final = "tentativas_esgotadas"
MOTIVOS_DA_DLQ: Final = (
    MOTIVO_ENVELOPE_INVALIDO,
    MOTIVO_TIPO_DESCONHECIDO,
    MOTIVO_TENTATIVAS_ESGOTADAS,
)

#: O `tipo` e a `versao` de uma entrada cujo envelope nao se leu. Os do AGR
#: (`kamba_agr/eventos/dlq.py`), para que uma varredura da DLQ os leia igual.
TIPO_ILEGIVEL: Final = "evt.ilegivel"
VERSAO_ILEGIVEL: Final = 0

#: Os desfechos de uma entrega. Lista fechada: e o que o processo regista.
DESFECHOS: Final = (
    "aplicado",
    "duplicado",
    "para_dlq",
    "adiado",
    "corpo_invalido",
    "nao_autorizado",
)


@dataclass(frozen=True, slots=True)
class Resposta:
    """O estado HTTP, o desfecho e, num 503, os segundos do `Retry-After`."""

    estado: int
    outcome: str
    retry_after: int | None = None
    error_code: str | None = None

    def corpo(self) -> dict[str, str]:
        corpo = {"outcome": self.outcome}
        if self.error_code is not None:
            corpo["error_code"] = self.error_code
        return corpo


def _segundos(atraso_ms: int) -> int:
    """Milissegundos para o `Retry-After`, arredondando **para cima**.

    Um atraso de 1 500 ms que virasse `Retry-After: 1` pedia a repeticao antes
    do tempo. E a regra do `/internal/event` do AGR.
    """
    return max(1, -(-int(atraso_ms) // 1_000))


def _envelope_legivel(envelope: Any) -> bool:
    """O minimo que o `consumir` e o efeito do IDX leem, com a forma certa.

    Nao e o contrato inteiro — esse e do produtor e do publicador, que o
    validam antes de o evento sair da base. E o que, a faltar, rebentava dentro
    da transaccao e repetia seis vezes o que se sabia a primeira.
    """
    if not isinstance(envelope, Mapping):
        return False
    for campo in ("id", "tipo", "tenant_id"):
        if not isinstance(envelope.get(campo), str) or not envelope.get(campo):
            return False
    versao = envelope.get("versao")
    if isinstance(versao, bool) or not isinstance(versao, int):
        return False
    agregado = envelope.get("agregado")
    if not isinstance(agregado, Mapping):
        return False
    seq = agregado.get("seq")
    return (
        isinstance(agregado.get("tipo"), str)
        and isinstance(agregado.get("id"), str)
        and isinstance(seq, int)
        and not isinstance(seq, bool)
    )


class EntregaAoIdx:
    """A entrega de um evento ao consumidor do indice.

    `abrir_ligacao` devolve uma ligacao DB-API **transaccional** (`kamba_app`,
    sem `BYPASSRLS`); abre-se uma por entrega e fecha-se sempre. Injectada pela
    razao de sempre: a decisao testa-se inteira sem PostgreSQL.
    """

    __slots__ = ("_abrir", "_metricas")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        metricas: Metricas | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._metricas = metricas

    def entregar(self, corpo: Any) -> Resposta:
        try:
            entrega = ler_entrega(corpo)
            exigir_ponteiros_uuid(entrega)
        except EntregaInvalidaError as erro:
            return Resposta(400, "corpo_invalido", error_code=erro.codigo)

        ligacao = self._abrir()
        try:
            return self._com_ligacao(ligacao, entrega)
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — o desfecho e o que importa
                pass

    # ------------------------------------------------------------- o caminho

    def _com_ligacao(self, ligacao: Any, entrega: Entrega) -> Resposta:
        envelope = entrega.envelope
        if envelope is None:
            # O *job* do reconciliador: so o `tenant_id`. O envelope le-se do
            # arquivo, com o contexto do *tenant* que a fila declarou.
            envelope = self._do_arquivo(ligacao, entrega)
            if envelope is None:
                # Pode ser cedo: o publicador enfileira **antes** do `COMMIT`
                # que arquiva. Repete-se; na ultima, abre-se a entrada com o
                # que se sabe — e a regra do `trabalhador_bullmq.ts`. O motivo
                # e o `tentativas_esgotadas`, o mesmo do AGR para o mesmo caso:
                # uma varredura da DLQ le-o igual nos dois consumidores.
                if entrega.tentativas >= TENTATIVAS:
                    self._dlq_sem_envelope(ligacao, entrega, MOTIVO_TENTATIVAS_ESGOTADAS)
                    return Resposta(200, "para_dlq")
                return Resposta(503, "adiado", retry_after=ADIAMENTO_POR_OMISSAO)

        if not _envelope_legivel(envelope):
            self._dlq_sem_envelope(ligacao, entrega, MOTIVO_ENVELOPE_INVALIDO)
            return Resposta(200, "para_dlq")
        if envelope["id"] != entrega.event_id or envelope["tenant_id"] != entrega.tenant_id:
            # **Os ponteiros da fila tem de bater com o envelope.** Sem isto,
            # uma entrega com o `tenant_id` de B e um envelope de A escrevia a
            # linha da DLQ no *tenant* B — o envelope de A dentro de B. Por isso
            # o caminho e o da DLQ **sem** envelope, que nao guarda o recusado.
            self._dlq_sem_envelope(ligacao, entrega, MOTIVO_ENVELOPE_INVALIDO)
            return Resposta(200, "para_dlq")
        if envelope["tipo"] not in consumidor.TIPOS:
            # Configuracao: a `evt_subscricoes` entrega ao `idx` um tipo que o
            # consumidor nao trata. Nenhuma tentativa o muda; a entrada guarda
            # o envelope inteiro, e e reprocessavel no dia em que o tratar.
            self._dlq(ligacao, envelope, MOTIVO_TIPO_DESCONHECIDO, entrega.tentativas)
            return Resposta(200, "para_dlq")

        try:
            resultado = consumidor.consumir_evento(
                ClienteDaLigacao(ligacao), envelope, self._metricas
            )
        except Adiar as adiamento:
            return self._repetir_ou_dlq(ligacao, envelope, entrega, adiamento.atraso_ms)
        except Exception:  # noqa: BLE001 — o desfecho e a escada, nunca a mensagem
            # O `consumir` ja fez `ROLLBACK`: nao ha marca sem efeito. A
            # ligacao pode estar morta; se estiver, a DLQ abaixo tambem falha e
            # o erro sobe ao processo, que responde 503.
            atraso = atraso_da_tentativa_do_consumidor(entrega.tentativas)
            return self._repetir_ou_dlq(ligacao, envelope, entrega, atraso)
        return Resposta(200, resultado.desfecho)

    def _repetir_ou_dlq(
        self,
        ligacao: Any,
        envelope: Mapping[str, Any],
        entrega: Entrega,
        atraso_ms: int,
    ) -> Resposta:
        if entrega.tentativas >= TENTATIVAS:
            self._dlq(ligacao, envelope, MOTIVO_TENTATIVAS_ESGOTADAS, entrega.tentativas)
            return Resposta(200, "para_dlq")
        return Resposta(503, "adiado", retry_after=_segundos(atraso_ms))

    # ------------------------------------------------------------- a base

    def _do_arquivo(self, ligacao: Any, entrega: Entrega) -> Any:
        with tenant_guard.tx(ligacao, entrega.tenant_id) as cursor:
            cursor.execute(SQL_ENVELOPE_DO_ARQUIVO, (entrega.event_id,))
            linha = cursor.fetchone()
        if linha is None:
            return None
        envelope = linha[0]
        # O `pg8000` devolve o `jsonb` ja decifrado; outro condutor pode dar
        # texto. Aceitam-se os dois, e o que nao se le cai na forma, a seguir.
        if isinstance(envelope, (str, bytes)):
            try:
                return json.loads(envelope)
            except ValueError:
                return envelope
        return envelope

    def _dlq(
        self,
        ligacao: Any,
        envelope: Mapping[str, Any],
        motivo: str,
        tentativas: int,
    ) -> None:
        self._escrever_dlq(
            ligacao,
            str(envelope["tenant_id"]),
            (
                consumidor.CONSUMIDOR,
                envelope["id"],
                envelope["tipo"],
                envelope["versao"],
                envelope["tenant_id"],
                json.dumps(dict(envelope), ensure_ascii=False),
                motivo,
                tentativas,
            ),
            motivo,
        )

    def _dlq_sem_envelope(self, ligacao: Any, entrega: Entrega, motivo: str) -> None:
        """A entrada de um evento cujo envelope nao se leu, ou nao bate.

        O `event_id` e o `tenant_id` sao os **ponteiros da fila**, e a coluna
        `envelope` leva um substituto — **nunca** o que foi recusado, que pode
        ser conteudo de outro *tenant*.
        """
        self._escrever_dlq(
            ligacao,
            entrega.tenant_id,
            (
                consumidor.CONSUMIDOR,
                entrega.event_id,
                TIPO_ILEGIVEL,
                VERSAO_ILEGIVEL,
                entrega.tenant_id,
                json.dumps(
                    {"id": entrega.event_id, "consumer": consumidor.CONSUMIDOR, "motivo": motivo}
                ),
                motivo,
                entrega.tentativas,
            ),
            motivo,
        )

    def _escrever_dlq(
        self, ligacao: Any, tenant_id: str, parametros: tuple[object, ...], motivo: str
    ) -> None:
        if motivo not in MOTIVOS_DA_DLQ:
            raise ValueError(f"motivo fora da lista fechada: {motivo!r}")
        with tenant_guard.tx(ligacao, tenant_id) as cursor:
            cursor.execute(SQL_ABRIR_DLQ, parametros)
