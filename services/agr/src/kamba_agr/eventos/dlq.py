"""A fila de mortos do consumidor do AGR (KAM-038, criterios 2 e 3).

O `consumo.py` do KAM-006 escreve por extenso o que nao faz: «nao trata de
retentativas nem de DLQ — isso e politica, e vive no trabalhador». Este modulo e
essa politica do lado do AGR, e e tudo o que ele e: abrir uma entrada, contar, e
deixar linha de registo.

## Quando se abre, e porque nem sempre se esperam seis tentativas

O §6.4 da seis tentativas (1 + 5) com a escada de 1 s, 5 s, 30 s, 2 min e
10 min. Essa escada existe para pre-condicoes que **podem** passar a verificar-se
— a encomenda que ainda nao chegou, o provedor que esta em baixo. Tres dos cinco
motivos de `MOTIVOS_DA_DLQ` nao sao desses:

* `envelope_invalido` — o envelope nao muda entre tentativas;
* `tipo_desconhecido` — nenhuma vertical subscreve o tipo, e isso e
  configuracao;
* `versao_desconhecida` — a versao nao existe no catalogo, e isso e ordem de
  *deploy* (§6.6: «consumidores antes de produtores»).

O quarto e o `tentativas_esgotadas`, que por definicao vem **depois** da escada.
Nao ha um quinto: o `fora_de_ordem` do KAM-006 nasce dentro da pre-condicao de
estado, que este consumidor nao corre — ver `desfechos.py`.

Gastar treze minutos de escada com qualquer um deles era adiar o alerta por
treze minutos para chegar a mesma conclusao. Vao para a DLQ **a primeira
entrega**, e o alerta e imediato — que e o que o criterio 3 pede («falha
visivel... e emite alerta», e nao «falha visivel treze minutos depois»).

## Uma entrada de pagamento e Sev1, e isto nao e quem o decide

O §6.4 e o comentario da tabela na revisao `0005` dizem que uma entrada de
`payment.*` ou `order.paid` e **Sev1** — cliente que pagou sem confirmacao.
Quem a classifica e o alerta, que le `tipo` da linha; este modulo nao tem
severidades. O que ele faz e nao deixar nenhuma entrada passar sem contador e
sem linha de registo, porque uma DLQ que cresce em silencio e uma DLQ que
ninguem varre.

## O que nao se escreve no registo

Nem o `payload`, nem o `event_id`, nem o `tenant_id`. O `erro` e o `tipo` sao
constantes deste codigo e de lista fechada e cabem em `error_code` e em
`outcome`; o resto le-se na linha da DLQ, onde as colunas existem e a RLS as
protege. E a mesma regra do `consumo.py` do KAM-006 («nao registra nada»).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, Final

from kamba_core import tenant_guard

from ..metricas import METRICA_EVT_DLQ, MetricasDoAgr
from .consultas import SQL_ABRIR_DLQ
from .desfechos import MOTIVO_COM_RETENTATIVA, MOTIVOS_DA_DLQ
from .envelope import Envelope

#: O motivo de quem esgotou a escada do §6.4. **Importado** do `desfechos.py`,
#: que e quem tem a lista fechada: escrever o texto a segunda vez dava duas
#: cadeias a divergir, e uma delas ia para uma coluna.
TENTATIVAS_ESGOTADAS: Final = MOTIVO_COM_RETENTATIVA

#: O `tipo` de uma entrada aberta **sem** envelope legivel. Espelho do
#: `TIPO_ILEGIVEL` do `dlq.ts`: casa a gramatica `familia.verbo` que a etiqueta
#: de `evt_dlq_open` exige e **nao** e um tipo do catalogo, para que ninguem o
#: confunda com um evento reprocessavel sem olhar.
TIPO_ILEGIVEL: Final = "evt.ilegivel"

#: A `versao` de uma entrada sem envelope: nao se sabe, e zero nao e versao.
VERSAO_ILEGIVEL: Final = 0

#: O aviso que fica no lugar do envelope. **Nao se guarda o que foi recusado**,
#: e essa e a decisao que importa: um envelope ilegivel pode trazer qualquer
#: coisa — conteudo de outro *tenant*, um telefone, texto de uma mensagem — e a
#: DLQ guarda a coluna `envelope` por trinta dias depois da resolucao. Guardar o
#: que se recusou era por num *tenant* dados que podem nao ser dele, numa tabela
#: que uma auditoria le. O que fica e o que se sabe: o `event_id`, o consumidor
#: e o motivo.
AVISO_SEM_ENVELOPE: Final = (
    "o envelope nao se leu: isto nao e um envelope, e o que foi recusado nao se "
    "guarda (pode ser conteudo de outro tenant)"
)


class MotivoDesconhecidoError(ValueError):
    """Um motivo fora de `MOTIVOS_DA_DLQ`.

    Levanta em vez de escrever: o `erro` e etiqueta de metrica **e** coluna, e
    um valor novo escrito a passagem fazia o painel ganhar uma serie que
    ninguem declarou. A lista fechada e o dicionario §3.33.
    """




class FilaDeMortos:
    """Abre entradas em `platform.events_dlq`, sobre uma ligacao propria.

    `abrir_ligacao` e injectada pela razao do `consumo.py` do KAM-006: com o
    cliente injectado, a decisao testa-se inteira sem PostgreSQL, e o que a
    *suite* do *gate* 8 prova e o que so a base pode provar.
    """

    __slots__ = ("_abrir", "_metricas", "_aviso")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        metricas: MetricasDoAgr | None = None,
        aviso: Callable[[str, str], None] | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._metricas = metricas
        self._aviso = aviso

    async def abrir(
        self,
        *,
        consumidor: str,
        envelope: Envelope,
        motivo: str,
        tentativas: int,
    ) -> None:
        """Abre a entrada, conta e alerta. Repetir o mesmo par e *no-op*.

        **Conta e alerta mesmo quando o `INSERT` nao escreve linha nenhuma**, e
        isso e deliberado: zero linhas quer dizer que ja ha uma entrada aberta
        para este par, isto e, que a entrega **voltou** a falhar. Um contador
        que so subisse na primeira dizia que o problema aconteceu uma vez.
        """
        await self._escrever(
            tenant_id=envelope.tenant_id,
            motivo=motivo,
            parametros=(
                consumidor,
                envelope.id,
                envelope.tipo,
                envelope.versao,
                envelope.tenant_id,
                json.dumps(envelope.como_mapa(), ensure_ascii=False),
                motivo,
                tentativas,
            ),
        )

    async def abrir_sem_envelope(
        self,
        *,
        consumidor: str,
        event_id: str,
        tenant_id: str,
        motivo: str,
        tentativas: int,
    ) -> None:
        """Abre a entrada de um evento cujo envelope **nao se leu**.

        Existe porque sem ela esse evento desaparecia em silencio: a validacao
        corre antes do consumo, e um erro ali nunca chegava ao `abrir`. A
        entrega esgotava as tentativas e ficava em `failed` no Redis — sem linha
        na DLQ, sem metrica, sem alerta —, e como nao ha linha em
        `events_consumed` nem em `events_dlq`, o reconciliador voltava a
        enfileira-la de cinco em cinco minutos durante as 24 h da janela. E a
        mesma razao que o `paraDlqSemEnvelope` do `dlq.ts` escreve.

        O `event_id` e o `tenant_id` vem do **corpo da entrega** e nao do
        envelope, por definicao: sao os ponteiros da fila. Nao sao autoridade
        nenhuma — a linha fica no *tenant* que a fila declarou, e o que fica na
        coluna `envelope` e um substituto e **nunca** o que foi recusado.
        """
        await self._escrever(
            tenant_id=tenant_id,
            motivo=motivo,
            parametros=(
                consumidor,
                event_id,
                TIPO_ILEGIVEL,
                VERSAO_ILEGIVEL,
                tenant_id,
                json.dumps(
                    {
                        "id": event_id,
                        "consumer": consumidor,
                        "motivo": motivo,
                        "aviso": AVISO_SEM_ENVELOPE,
                    },
                    ensure_ascii=False,
                ),
                motivo,
                tentativas,
            ),
        )

    async def _escrever(
        self, *, tenant_id: str, motivo: str, parametros: tuple[object, ...]
    ) -> None:
        """O `INSERT`, o contador e o alerta. Um sitio so para as duas entradas.

        Duas copias divergiam na que se esquecesse de uma delas — e o que se
        esquece e sempre o contador.

        **Tudo o que toca a base vai a um executor**, e a primeira versao disto
        corria na *event loop*: abrir a tomada, o `BEGIN`, o `set_config`, o
        `INSERT`, o `COMMIT` e o `close` — meia dúzia de idas a rede a serializar
        o processo inteiro, que tambem serve o `/internal/turn`. Medido pela
        revisao adversarial, e contra o que este modulo afirmava. O `pg8000` e
        sincrono (`db/requirements/migrations.in`) e chama-lo na *loop* e a
        classe de defeito que o `conversa.py` do KAM-025 nomeia por extenso.

        **O cancelamento espera pela *thread*.** O `asyncio.to_thread` nao
        cancela nada: um `CancelledError` no `await` deixava a *thread* a meio do
        protocolo do `pg8000` sobre uma tomada que este metodo ia fechar no
        caminho de saida. E o mesmo tratamento do `checkpointer.py` do KAM-026,
        e pela mesma razao.
        """
        if motivo not in MOTIVOS_DA_DLQ:
            raise MotivoDesconhecidoError(
                f"{motivo!r} nao e um motivo de DLQ; os cinco sao {list(MOTIVOS_DA_DLQ)}"
            )
        tarefa = asyncio.ensure_future(
            asyncio.to_thread(self._escrever_sincrono, tenant_id, parametros)
        )
        try:
            await asyncio.shield(tarefa)
        except asyncio.CancelledError:
            await asyncio.wait([tarefa])
            raise
        if self._metricas is not None:
            self._metricas.contar(METRICA_EVT_DLQ, motivo)
        if self._aviso is not None:
            self._aviso("evt_dlq", motivo)

    def _escrever_sincrono(
        self, tenant_id: str, parametros: tuple[object, ...]
    ) -> None:
        """A tomada, a transaccao e o `INSERT`, numa *thread*."""
        ligacao = self._abrir()
        try:
            with tenant_guard.tx(ligacao, tenant_id) as cursor:
                cursor.execute(SQL_ABRIR_DLQ, parametros)
        finally:
            # A ligacao fecha-se sempre, e abre-se por entrada: a DLQ e rara, e
            # uma tomada guardada entre duas entradas e uma tomada que o
            # servidor pode ter fechado entretanto — a mesma escolha que o
            # `llm/cliente.py` do KAM-030 fez pela mesma razao.
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — o que importa e a entrada escrita
                pass
