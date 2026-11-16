"""A guarda de orcamento da imagem (KAM-124, criterio 7).

«Nenhum trabalho de imagem e iniciado acima do orcamento.» O LiteLLM guarda o
orcamento do texto e **nao ve os fornecedores de imagem** (E5, B12): esta e a
guarda propria. Compoe-se por cima do `PortaDeQuota` do servico, sem mexer no
`ServicoDeFoto`:

    QuotaComOrcamento(orcamento, quota)   pergunta o orcamento; so se couber
                                          consome o `imagens_mes`

A ordem e a que torna o «0 em teste» verdade: um pedido recusado pelo
orcamento **nao gasta** `imagens_mes` e nao nasce trabalho, porque o
`enhance_image` so cria a linha depois de a quota aceitar.

**Falha fechada.** Um erro a ler o orcamento, uma chave em falta ou um valor
ilegivel recusam, com o motivo dito. A recusa nao e um erro: o canal mostra ao
dono a mensagem estatica do `kamba_core.modulos.mensagem_orcamento_esgotado`.

**O que esta guarda nao faz.** Nao mede o custo do trabalho que esta a nascer
(o fornecedor so o diz depois): deixa nascer enquanto o gasto do mes estiver
**abaixo** do tecto. E a pergunta e o consumo nao sao atomicos, e os trabalhos
ainda `pendente` ou `a_processar` contam zero: o excesso sobre o tecto e o
custo dos trabalhos **em voo** quando ele foi atingido, e o tecto duro desse
excesso e o `imagens_mes`, que esse sim e atomico (achado da revisao
adversarial, que corrigiu a promessa de «uma imagem a mais» que aqui estava).
E um pedido repetido depois de o orcamento acabar recebe a recusa, mesmo que o
trabalho da primeira tentativa ja exista — o trabalho segue o seu caminho, so a
resposta e que nao o devolve.

**Quem a liga.** Esta classe compoe-se no arranque do servico de foto, onde o
`ServicoDeFoto` recebe a quota; esse arranque e da vertical que regista o
`enhance_image` (KAM-119, KAM-122) e da ponte da fila (KAM-194).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..modulos.uso import MOTIVO_SEM_ORCAMENTO, Gasto, gasto_do_mes
from .servico import MODULO, Consumo, PortaDeQuota


@runtime_checkable
class PortaDeOrcamento(Protocol):
    """O gasto e o tecto do mes do modulo `foto` para um tenant."""

    def gasto(self, tenant_id: str) -> Gasto: ...


class OrcamentoSobreBase:
    """O `PortaDeOrcamento` sobre a base (`kamba_core.modulos.gasto_do_mes`)."""

    def __init__(self, bd: object) -> None:
        self._bd = bd

    def gasto(self, tenant_id: str) -> Gasto:
        return gasto_do_mes(self._bd, tenant_id, MODULO)  # type: ignore[arg-type]


class QuotaComOrcamento:
    """Um `PortaDeQuota` que so consome a quota se o orcamento do mes couber."""

    def __init__(self, orcamento: PortaDeOrcamento, quota: PortaDeQuota) -> None:
        self._orcamento = orcamento
        self._quota = quota

    def consumir(self, tenant_id: str, idempotency_key: str) -> Consumo:
        try:
            gasto = self._orcamento.gasto(tenant_id)
            motivo = gasto.motivo
        except Exception:  # noqa: BLE001 — falha fechada, seja qual for
            return Consumo(aceite=False, motivo=MOTIVO_SEM_ORCAMENTO)
        if motivo is not None:
            return Consumo(aceite=False, motivo=motivo)
        return self._quota.consumir(tenant_id, idempotency_key)


__all__ = ["OrcamentoSobreBase", "PortaDeOrcamento", "QuotaComOrcamento"]
