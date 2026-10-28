"""A varredura dos rascunhos: o prazo das 24 h e a politica desligada.

E **uma** passagem e nao duas, e a razao e que as duas perguntas se fazem sobre a
mesma lista — «que rascunhos estao `pendente`?» — e tratar cada uma na sua
varredura lia a tabela duas vezes para decidir sobre as mesmas linhas.

```text
pendente ha mais de 24 h            -> expirado      (criterio 1)
politica do tenant desligada        -> substituido   (criterio 8)
nenhuma das duas                    -> fica, e conta para o alerta (criterio 6)
```

**Nao escreve.** Lista com o papel `kamba_batch`, que e o que atravessa
*tenants* (com contexto de um, a RLS devolvia so os rascunhos desse), e a
escrita de cada rascunho vai pelo `Decisor.decidir_pelo_sistema` — o mesmo CAS e
a mesma tranca que um clique usa. E a forma do `handoff/prazos.py`, e pela razao
que ele escreveu: uma segunda via de escrita era uma segunda implementacao do
criterio 2, e perdia a corrida contra o operador que decide no mesmo instante.

## Nao ha agendador, e isso e a mesma linha que o KAM-034 e o KAM-026 escreveram

Entrega-se o corpo da varredura e prova-se com relogio simulado; quem a chama a
horas e o *scheduler* do EVT (KAM-071). Agendar sem agendador era escrever um que
ninguem pediu.

**A consequencia para o criterio 8 escreve-se em vez de se descobrir:** sem
agendador, desactivar a politica repoe o envio automatico **no turno seguinte**
de cada conversa (o grafo le a politica em cada turno, sem *cache* — ver
`politica.py`), mas os rascunhos ja `pendente` de conversas **sem** turno
seguinte so passam a `substituido` quando esta varredura correr. Ate la, o
prazo das 24 h apanha-os como `expirado`. Nenhum deles chega a ser enviado, que
e a barreira que importa.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

from kamba_core import tenant_guard

from ..metricas import METRICA_DRAFT_PENDENTES, MetricasDoAgr
from .consultas import SQL_PENDENTES, SQL_PENDENTES_HA_MAIS_DE
from .maquina import ALERTA_MINUTOS, PRAZO_HORAS

#: O prazo em segundos, derivado do `PRAZO_HORAS` da maquina. **Derivado e nao
#: um segundo literal**: duas constantes para o mesmo prazo divergiam no dia em
#: que uma delas mudasse, e o `PRAZO_HORAS` e o que o dicionario declara.
PRAZO_SEGUNDOS: Final = PRAZO_HORAS * 60 * 60

#: Quantos rascunhos uma varredura trata. Tecto e nao «todos», pela razao do
#: `TECTO_POR_VARREDURA` do KAM-034: uma varredura que acordasse com dez mil
#: pendentes prendia a *event loop* do *worker* e nenhuma retoma passava.
TECTO_POR_VARREDURA: Final = 500

#: O nome do *job* para o `tx_batch`. Snake_case, que e o que ele exige, e
#: existe para que nao haja «uso sem nome nem sem contagem» do `kamba_batch`.
JOB: Final = "agr_draft_prazos"


class Varredura:
    """A passagem pelos rascunhos pendentes.

    `abrir_ligacao` devolve uma ligacao DB-API **do papel `kamba_batch`**, e nao
    a do `kamba_app` que o `Decisor` usa: sao dois papeis e duas ligacoes, porque
    a listagem atravessa *tenants* e a escrita nao.

    `politica` e a **mesma** `PoliticaDeConcierge` que o grafo usa, de proposito:
    duas leituras da mesma politica podiam divergir, e a que decide se um
    rascunho se substitui tem de ser a que decide se o proximo turno rascunha.
    """

    __slots__ = (
        "_abrir",
        "_trancas",
        "_decidir",
        "_politica",
        "_relogio",
        "_tecto",
        "_metricas",
    )

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        trancas: Any,
        decidir_pelo_sistema: Callable[[str, str, str], Awaitable[str]],
        politica: Any,
        relogio: Callable[[], float] = time.time,
        tecto: int = TECTO_POR_VARREDURA,
        metricas: MetricasDoAgr | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._trancas = trancas
        self._decidir = decidir_pelo_sistema
        self._politica = politica
        self._relogio = relogio
        self._tecto = tecto
        self._metricas = metricas

    def limite(self) -> dt.datetime:
        """O instante antes do qual um rascunho pendente ja expirou.

        Em UTC e com fuso, porque a coluna e `timestamptz`: um `datetime` sem
        fuso comparado com `timestamptz` e interpretado no `TimeZone` da sessao,
        e a varredura passava a depender de uma configuracao do servidor. E a
        mesma nota do `handoff/prazos.py`.
        """
        return dt.datetime.fromtimestamp(
            self._relogio() - PRAZO_SEGUNDOS, tz=dt.timezone.utc
        )

    def pendentes(self, ligacao: Any) -> list[tuple[str, str, str, dt.datetime]]:
        """Os rascunhos pendentes: `(draft_id, tenant_id, thread_id, criado_at)`.

        Sincrona e com a ligacao de fora, para que a *suite* do *gate* 8 a corra
        contra a base com a sua propria ligacao.
        """
        with tenant_guard.tx_batch(ligacao, JOB) as cursor:
            cursor.execute(SQL_PENDENTES, (self._tecto,))
            return [
                (str(linha[0]), str(linha[1]), str(linha[2]), linha[3])
                for linha in cursor.fetchall()
            ]

    def a_espera(self, ligacao: Any, minutos: int = ALERTA_MINUTOS) -> int:
        """Quantos rascunhos estao pendentes ha mais de `minutos`, em todos os
        *tenants*. E o alerta (*proposta*) do criterio 6.
        """
        with tenant_guard.tx_batch(ligacao, JOB) as cursor:
            cursor.execute(SQL_PENDENTES_HA_MAIS_DE, (minutos,))
            return int(cursor.fetchone()[0])

    async def varrer(self) -> dict[str, int]:
        """Uma passagem. Devolve a contagem por acção tomada.

        **Uma falha num rascunho nao para os outros**, pela razao do
        `handoff/prazos.py`: a excepcao conta-se como `falhou` e a varredura
        continua. O que se perde e aquele rascunho nesta volta, e a volta
        seguinte volta a encontra-lo — porque a compensacao do `servico.py` o
        devolveu a `pendente`.

        Devolve um `dict` e nao `None` para que quem a agenda consiga registar o
        que ela fez. Uma varredura que trate zero rascunhos devolve zeros, que e
        diferente de nao ter corrido.
        """
        ligacao = self._abrir()
        try:
            lista = await asyncio.to_thread(self.pendentes, ligacao)
            demorados = await asyncio.to_thread(self.a_espera, ligacao)
        finally:
            # Abre e fecha **por varredura**, ao contrario da ligacao do
            # `Decisor`: a varredura corre de hora a hora e uma tomada aberta
            # nesse intervalo e uma tomada que o PostgreSQL conta no
            # `max_connections` para nada.
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a varredura acabou de qualquer forma
                pass

        if self._metricas is not None:
            self._metricas.medir(METRICA_DRAFT_PENDENTES, demorados)

        limite = self.limite()
        contagem = {"expirado": 0, "substituido": 0, "ficaram": 0, "falhou": 0}
        #: A politica le-se **uma vez por *tenant* por varredura** e nao uma vez
        #: por rascunho: um *tenant* do Piloto com cinquenta pendentes dava
        #: cinquenta leituras da mesma linha. Nao e *cache* entre varreduras —
        #: isso era o TTL que a `politica.py` recusa —, e o alcance e esta
        #: passagem.
        politica_do_tenant: dict[str, bool] = {}

        for draft_id, tenant_id, thread_id, criado_at in lista:
            if criado_at < limite:
                decisao = "expirado"
            else:
                if tenant_id not in politica_do_tenant:
                    try:
                        politica_do_tenant[tenant_id] = await asyncio.to_thread(
                            self._politica.activa, tenant_id
                        )
                    except asyncio.CancelledError:
                        raise
                    except BaseException:  # noqa: BLE001 — ver docstring
                        # **Nao se assume nada sobre a politica que nao se
                        # conseguiu ler.** Assumir «desligada» substituia os
                        # rascunhos de um *tenant* que esta no Piloto; assumir
                        # «ligada» era inventar. Conta-se como falha e o
                        # rascunho fica — o prazo apanha-o de qualquer maneira.
                        contagem["falhou"] += 1
                        continue
                if politica_do_tenant[tenant_id]:
                    contagem["ficaram"] += 1
                    continue
                decisao = "substituido"

            try:
                async with self._trancas.tomar(thread_id):
                    await self._decidir(thread_id, draft_id, decisao)
            except asyncio.CancelledError:
                raise
            except BaseException:  # noqa: BLE001 — ver docstring
                contagem["falhou"] += 1
                continue
            contagem[decisao] += 1
        return contagem


__all__ = [
    "JOB",
    "PRAZO_SEGUNDOS",
    "TECTO_POR_VARREDURA",
    "Varredura",
]
