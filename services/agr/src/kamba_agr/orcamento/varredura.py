"""As duas varreduras do Orcamento expresso: as 24 h e a expiracao (KAM-221).

| *Job* | O que faz | Corpo |
|---|---|---|
| `agr_orcamento_sem_resposta` | um pedido sem resposta do dono ha 24 h recebe **uma** mensagem neutra e a oferta de humano | `tls.orcamento.avisar_sem_resposta` |
| `agr_orcamento_expirar` | uma resposta cuja validade passou fecha `expirado`, sem ninguem tocar | `tls.orcamento.expirar_vencidos` |

## Porque e que a listagem e dos `tenants` e nao dos pedidos

O `kamba_batch` atravessa *tenants*, e e o papel do `tx_batch` — mas **nao
tem privilegio nenhum** na `platform.quote_requests` (revisao `0072`: so o
`kamba_app`, e a matriz do `test_privilegios.py` fixa-o). Dar-lho era uma
revisao de base de dados, e este ticket nao leva migracao. Por isso o lote so
lista os *tenants* (a pergunta do `kamba_core.idx.processo`), e cada
*tenant* corre no caminho normal: `kamba_app`, `tenant_guard.tx` com o contexto
dele, e a RLS `FORCE` da tabela como guarda. E a forma do `handoff/prazos.py`
ao contrario: la a listagem le as passagens e a escrita e por *tenant*; aqui as
duas sao por *tenant*, porque a tabela so e do `kamba_app`.

## Nao ha agendador, e nao se escreve um

A mesma linha do `Prazos.varrer` (KAM-034) e da varredura dos rascunhos
(KAM-114): o corpo entrega-se aqui, prova-se com relogio fixo, e quem o chama a
horas e o *scheduler* do EVT. O `__main__` nao o constroi.

## Uma falha num tenant nao para os outros

Conta-se `falhou`, e a volta seguinte volta a encontrar o mesmo trabalho: a
expiracao e um `UPDATE` idempotente, e a mensagem das 24 h tem a chave do
Outbound.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any, Final

from kamba_core import tenant_guard

from ..eventos.notificacao import OutboundPorLigar
from ..tls import orcamento as repositorio

#: Os nomes dos dois *jobs*, para o `tx_batch`. Snake_case, que e o que ele exige.
JOB_SEM_RESPOSTA: Final = "agr_orcamento_sem_resposta"
JOB_EXPIRAR: Final = "agr_orcamento_expirar"

#: Os *tenants* a quem a mensagem das 24 h pode sair: so os activos, a
#: pergunta do `idx/processo.py`. Um *tenant* suspenso ou restrito nao fala com
#: clientes por esta via.
SQL_TENANTS_ACTIVOS: Final = (
    "SELECT id::text FROM platform.tenants WHERE estado = 'ativo' ORDER BY id"
)

#: Os *tenants* cuja expiracao corre: todos menos os encerrados. Expirar nao
#: envia nada, e uma proposta vencida de um *tenant* suspenso tambem ja nao
#: se pode aceitar quando ele voltar.
SQL_TENANTS_POR_EXPIRAR: Final = (
    "SELECT id::text FROM platform.tenants WHERE estado <> 'encerrado' ORDER BY id"
)


class VarreduraDeOrcamentos:
    """`sem_resposta()` e `expirar()`, uma volta cada.

    `abrir_lote` devolve uma ligacao do `kamba_batch` (so lista os *tenants*) e
    `abrir_app` uma do `kamba_app` (o trabalho de cada um). Sao duas ligacoes e
    dois papeis, abertas e fechadas por volta: a varredura corre de hora a hora,
    e uma tomada guardada nesse intervalo e uma tomada para nada.
    """

    __slots__ = ("_lote", "_app", "_saida", "_relogio")

    def __init__(
        self,
        abrir_lote: Callable[[], Any],
        abrir_app: Callable[[], Any],
        saida: Any | None = None,
        relogio: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._lote = abrir_lote
        self._app = abrir_app
        self._saida = saida if saida is not None else OutboundPorLigar()
        self._relogio = relogio or (lambda: datetime.datetime.now(datetime.UTC))

    def tenants(self, job: str, sql: str) -> list[str]:
        ligacao = self._lote()
        try:
            with tenant_guard.tx_batch(ligacao, job) as cursor:
                cursor.execute(sql)
                return [str(linha[0]) for linha in cursor.fetchall()]
        finally:
            _fechar(ligacao)

    def _por_tenant(
        self, job: str, sql: str, trabalho: Callable[[Any, str], dict[str, int]]
    ) -> dict[str, int]:
        agregado: dict[str, int] = {"falhou": 0}
        tenants = self.tenants(job, sql)
        ligacao = self._app()
        try:
            for tenant_id in tenants:
                try:
                    parcial = trabalho(ligacao, tenant_id)
                except Exception:  # noqa: BLE001 — ver a nota do modulo
                    agregado["falhou"] += 1
                    continue
                for chave, valor in parcial.items():
                    agregado[chave] = agregado.get(chave, 0) + valor
        finally:
            _fechar(ligacao)
        return agregado

    def sem_resposta(self) -> dict[str, int]:
        """A volta das 24 h. Devolve a contagem por desfecho do Outbound."""
        agora = self._relogio()
        return self._por_tenant(
            JOB_SEM_RESPOSTA,
            SQL_TENANTS_ACTIVOS,
            lambda ligacao, tenant_id: repositorio.avisar_sem_resposta(
                ligacao, tenant_id, self._saida, agora
            ),
        )

    def expirar(self) -> dict[str, int]:
        """A volta da expiracao. Devolve `{"expirados": n, "falhou": m}`."""
        agora = self._relogio()
        return self._por_tenant(
            JOB_EXPIRAR,
            SQL_TENANTS_POR_EXPIRAR,
            lambda ligacao, tenant_id: {
                "expirados": repositorio.expirar_vencidos(ligacao, tenant_id, agora)
            },
        )


def _fechar(ligacao: Any) -> None:
    try:
        ligacao.close()
    except Exception:  # noqa: BLE001 — a volta ja acabou de qualquer forma
        pass


__all__ = [
    "JOB_EXPIRAR",
    "JOB_SEM_RESPOSTA",
    "SQL_TENANTS_ACTIVOS",
    "SQL_TENANTS_POR_EXPIRAR",
    "VarreduraDeOrcamentos",
]
