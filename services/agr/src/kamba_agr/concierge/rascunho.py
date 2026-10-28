"""O servico que abre o rascunho: a linha e a publicacao ao operador (KAM-114).

E o que o no `draft_prepare` chama, e e a porta que o `ServicoDeHandoff` do
KAM-034 e para o `handoff_prepare`. Duas operacoes, nesta ordem, e a ordem e a
propriedade:

```text
1. INSERT ... ON CONFLICT (draft_id) DO NOTHING   a linha, no platform
2. publicar(...)                                  o rascunho, no HND
```

**A linha vem primeiro, e nao e indiferente.** E a mesma ordem que o
`openHandoff` do `docs/tecnica/01` §11.4 usa («a linha antes da chamada ao
terceiro, como o KAM-015 fez com o envio»), e aqui compra duas coisas: um
rascunho publicado que a base nao conhece era um pedido de aprovacao que nenhuma
varredura ve expirar — e portanto um operador a aprovar uma mensagem que o CAS
nao sabe que existe —, e o `RascunhoIndisponivel` do passo 2 encontra a linha ja
gravada, que e o que faz o prazo das 24 h apanhar o caso em que o HND esta em
baixo.

**As duas sao idempotentes por `draft_id`**, que e o criterio 2: o
`ON CONFLICT` e da base e a publicacao e do provedor. Nenhuma das duas e um
contador em memoria deste processo, que o reinicio perdia e a segunda replica
nao via.

## O `turn_seq` e o `turn_id` vem do estado, e nao daqui

O `draft_id` e `sha256(thread_id:turn_seq)` e tem de ser **estavel entre
re-execucoes do no**: derivado de um contador deste servico, uma repeticao do
*job* dava outro identificador e outro rascunho — exactamente o que o criterio 2
proibe. Por isso os dois chegam de fora, do estado do grafo, que e o que o
*checkpoint* restaura quando o *worker* repete.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kamba_core import tenant_guard

from ..metricas import METRICA_DRAFT_INDISPONIVEL, MetricasDoAgr
from .consultas import SQL_ABRIR_RASCUNHO
from .maquina import draft_id as derivar_draft_id
from .portas import PortaDeRascunho, RascunhoIndisponivel


class RascunhoAberto:
    """O que o no poe no estado depois de abrir o rascunho."""

    __slots__ = ("draft_id", "publicado", "referencia")

    def __init__(
        self, draft_id: str, publicado: bool, referencia: str | None = None
    ) -> None:
        self.draft_id = draft_id
        #: `False` quando o HND nao aceitou. O no interrompe de qualquer
        #: maneira — ver a nota do `portas.py` —, e o que isto diz ao estado e
        #: que **nenhum operador viu** este rascunho.
        self.publicado = publicado
        self.referencia = referencia


class ServicoDeRascunho:
    """Abre o rascunho: grava a linha e publica-o ao operador.

    `abrir_ligacao` devolve uma ligacao DB-API do papel `kamba_app`; `provedor` e
    a `PortaDeRascunho`.

    **Sincrono, como o `ServicoDeHandoff`**, porque e de dentro de um no sincrono
    que e chamado. A consequencia esta escrita no `portas.py` e nao e deste
    ticket: uma implementacao que faca E/S de rede nesta chamada prende a *event
    loop* do *worker* — restricao que o `abrir` do handoff ja tem, e que este
    ticket nao resolve nem agrava.

    **A ligacao abre e fecha por rascunho**, ao contrario da do `Decisor`: um no
    de grafo nao tem ciclo de vida onde guardar uma tomada, e uma tomada guardada
    num objecto partilhado por turnos concorrentes era o defeito que o
    `llm/cliente.py` do KAM-030 pagou (a segunda chamada transferia dados e nao
    gravava linha).
    """

    __slots__ = ("_abrir", "_provedor", "_metricas")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        provedor: PortaDeRascunho,
        metricas: MetricasDoAgr | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._provedor = provedor
        self._metricas = metricas

    def abrir(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        turn_seq: int,
        turn_id: str,
        graph_version: str,
        contact_id: str,
        conversation_id: str,
        texto: str,
        motivos: tuple[str, ...] = (),
    ) -> RascunhoAberto:
        """Grava a linha e publica. Nao levanta se o HND estiver em baixo."""
        draft_id = derivar_draft_id(thread_id, turn_seq)
        self._gravar(
            draft_id=draft_id,
            tenant_id=tenant_id,
            thread_id=thread_id,
            turn_seq=turn_seq,
            turn_id=turn_id,
            graph_version=graph_version,
        )
        try:
            referencia = self._provedor.publicar(
                draft_id=draft_id,
                tenant_id=tenant_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                texto=texto,
                motivos=motivos,
            )
        except RascunhoIndisponivel:
            # **Nao se envia nada ao cliente**, e e a nota do `portas.py`: uma
            # mensagem de degradacao e uma mensagem, e o criterio 1 conta zero
            # mensagens sem decisao. O que fica e a linha `pendente`, a contagem
            # e o prazo das 24 h.
            if self._metricas is not None:
                self._metricas.contar(METRICA_DRAFT_INDISPONIVEL)
            return RascunhoAberto(draft_id, publicado=False)
        return RascunhoAberto(draft_id, publicado=True, referencia=referencia)

    def _gravar(
        self,
        *,
        draft_id: str,
        tenant_id: str,
        thread_id: str,
        turn_seq: int,
        turn_id: str,
        graph_version: str,
    ) -> None:
        ligacao = self._abrir()
        try:
            with tenant_guard.tx(ligacao, tenant_id) as cursor:
                cursor.execute(
                    SQL_ABRIR_RASCUNHO,
                    (
                        draft_id,
                        tenant_id,
                        thread_id,
                        int(turn_seq),
                        turn_id,
                        graph_version,
                    ),
                )
                # Zero linhas e o `ON CONFLICT` a morder, e **nao e erro**: e a
                # re-execucao do no, que e o criterio 2. Nao se le o resultado
                # por isso — o que importa e que a linha existe quando isto
                # devolve.
                cursor.fetchone()
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a escrita ja confirmou
                pass


__all__ = ["RascunhoAberto", "ServicoDeRascunho"]
