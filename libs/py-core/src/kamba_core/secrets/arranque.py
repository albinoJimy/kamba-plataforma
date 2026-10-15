"""Comportamento de arranque e janela de tolerancia (KAM-010).

Espelho de `packages/core-ts/src/secrets/arranque.ts`. O criterio de aceitacao
do ticket pede tres coisas que nao sao do provedor — sao da politica de quem o
usa — e por isso vivem aqui:

1. um servico sem segredo obrigatorio **falha ao arrancar**, com mensagem que
   nomeia o segredo e nunca o valor;
2. em `prod`, cofre inacessivel no arranque => **nao arranca**;
3. depois do arranque, mantem o ultimo valor conhecido durante **15 minutos**
   (*proposta* — ver `TTL_ULTIMO_VALOR_S`).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence

from .port import (
    CofreInacessivelError,
    SecretAusenteError,
    SecretProvider,
    SecretRef,
    validar_ref,
)

#: Janela, em segundos, em que um valor ja conhecido continua a servir com o
#: cofre em baixo. Equivale aos 900 000 ms de `TTL_ULTIMO_VALOR_MS` do lado
#: TypeScript, e um teste verifica que os dois numeros nao divergem.
#:
#: **Valor de desenho, *proposta*.** Os 15 minutos vem do criterio de aceitacao
#: do KAM-010 e nao de uma medicao. Calibra-se quando houver dois numeros que
#: hoje nao existem: o tempo de recuperacao observado do cofre (contrato de
#: servico da Doppler, ou MTTR do OpenBao nos Clusters) e a duracao de uma
#: entrega da Meta com retentativas (`E1`: a Meta re-entrega ate 7 dias, o que
#: torna uma janela curta menos perigosa do que parece). O ensaio pertence ao
#: KAM-083 (runbook) e a rotacao do KAM-072.
#:
#: O sentido da escolha: a janela protege contra uma falha de
#: **disponibilidade** do cofre, nao contra uma **revogacao**. Ver `Secrets.get_ring`.
TTL_ULTIMO_VALOR_S = 15 * 60


class ArranqueAbortadoError(RuntimeError):
    """O arranque nao pode continuar. Nunca contem valores."""

    def __init__(
        self, servico: str, motivo: str, segredos: Sequence[SecretRef] = ()
    ) -> None:
        self.servico = servico
        self.motivo = motivo
        self.segredos = tuple(segredos)
        sufixo = f"; segredos: {', '.join(self.segredos)}" if self.segredos else ""
        super().__init__(f"arranque abortado ({servico}): {motivo}{sufixo}")


class Secrets:
    """Fachada de segredos de um servico: carrega ao arranque, serve depois."""

    def __init__(
        self,
        servico: str,
        provider: SecretProvider,
        obrigatorios: Iterable[SecretRef],
        ttl_ultimo_valor_s: float = TTL_ULTIMO_VALOR_S,
        agora: Callable[[], float] = time.monotonic,
        aviso: Callable[[str], None] | None = None,
    ) -> None:
        """Constroi sem tocar no cofre. Use `Secrets.arrancar`."""
        self._servico = servico
        self._provider = provider
        self._obrigatorios = frozenset(validar_ref(r) for r in obrigatorios)
        self._ttl = ttl_ultimo_valor_s
        self._agora = agora
        self._aviso = aviso if aviso is not None else (lambda _mensagem: None)
        self._cache: dict[str, tuple[tuple[str, str | None], float]] = {}

    @property
    def ambiente(self) -> str:
        """Ambiente do provedor subjacente."""
        return self._provider.ambiente

    @property
    def provedor(self) -> str:
        """Nome do provedor subjacente."""
        return self._provider.nome

    @classmethod
    def arrancar(
        cls,
        servico: str,
        provider: SecretProvider,
        obrigatorios: Iterable[SecretRef],
        ttl_ultimo_valor_s: float = TTL_ULTIMO_VALOR_S,
        agora: Callable[[], float] = time.monotonic,
        aviso: Callable[[str], None] | None = None,
    ) -> Secrets:
        """Verifica o cofre, carrega os obrigatorios, ou levanta
        `ArranqueAbortadoError`.
        """
        secrets = cls(
            servico=servico,
            provider=provider,
            obrigatorios=obrigatorios,
            ttl_ultimo_valor_s=ttl_ultimo_valor_s,
            agora=agora,
            aviso=aviso,
        )
        refs = sorted(secrets._obrigatorios)

        try:
            provider.health()
        except CofreInacessivelError as erro:
            if provider.ambiente == "prod":
                # A letra do criterio de aceitacao. Em `prod` nao ha arranque
                # optimista: um servico a servir pedidos da Meta sem conseguir
                # ler o App Secret devolve 4xx a tudo, e a Meta re-entrega
                # durante sete dias (`E1`) — o que transforma uma falha de cofre
                # num atraso recuperavel em vez de uma avaria silenciosa.
                raise ArranqueAbortadoError(servico, str(erro)) from None
            # Fora de `prod` avisa-se e segue-se. Nao e tolerancia a mais: se
            # algum obrigatorio nao se conseguir ler, o passo seguinte aborta de
            # qualquer modo — e aborta com uma mensagem melhor, porque nomeia o
            # segredo.
            secrets._aviso(
                f"cofre inacessivel no arranque, a continuar em "
                f"{provider.ambiente}: {erro}"
            )

        ausentes: list[SecretRef] = []
        inacessiveis: list[SecretRef] = []
        for ref in refs:
            try:
                anel = provider.get_ring(ref)
            except SecretAusenteError:
                ausentes.append(ref)
            except CofreInacessivelError:
                inacessiveis.append(ref)
            else:
                secrets._cache[ref] = (anel, secrets._agora())

        if ausentes:
            # Todos de uma vez, e nao o primeiro: quem configura um ambiente
            # novo corrige uma lista, nao descobre um segredo por reinicio.
            raise ArranqueAbortadoError(
                servico, "segredos obrigatorios ausentes", ausentes
            )
        if inacessiveis:
            raise ArranqueAbortadoError(
                servico,
                "cofre inacessivel ao carregar segredos obrigatorios",
                inacessiveis,
            )
        return secrets

    def get(self, ref: SecretRef) -> str:
        """Valor actual. Ver `get_ring` para a politica de cache."""
        return self.get_ring(ref)[0]

    def get_ring(self, ref: SecretRef) -> tuple[str, str | None]:
        """`(actual, anterior)`, com a janela de tolerancia.

        **A janela cobre indisponibilidade, nao revogacao.** Um
        `CofreInacessivelError` serve-se da cache enquanto ela for fresca; um
        `SecretAusenteError` — o segredo deixou de existir no cofre —
        propaga-se sempre. Se a cache tapasse os dois casos, apagar um token
        comprometido deixaria de o desactivar durante quinze minutos, e revogar
        e exactamente a acção que tem de ser imediata (`docs/tecnica/08` §10).
        """
        chave = validar_ref(ref)
        try:
            anel = self._provider.get_ring(chave)
        except CofreInacessivelError as erro:
            guardado = self._cache.get(chave)
            if guardado is None:
                raise
            anel_guardado, em = guardado
            idade = self._agora() - em
            if idade >= self._ttl:
                raise CofreInacessivelError(
                    self._provider.nome,
                    f"{erro.motivo}; ultimo valor conhecido de {chave} tem "
                    f"{int(idade)}s e a janela e de {int(self._ttl)}s",
                ) from None
            self._aviso(
                f"cofre inacessivel; a servir o ultimo valor conhecido de {chave} "
                f"({int(idade)}s de {int(self._ttl)}s)"
            )
            return anel_guardado
        else:
            self._cache[chave] = (anel, self._agora())
            return anel

    def versions(self, ref: SecretRef) -> tuple[str, ...]:
        """Delega no provedor; a cache nao guarda listas de versoes."""
        return self._provider.versions(validar_ref(ref))

    def e_obrigatorio(self, ref: SecretRef) -> bool:
        """`True` se `ref` foi declarado obrigatorio no arranque."""
        return ref in self._obrigatorios


__all__ = ["TTL_ULTIMO_VALOR_S", "ArranqueAbortadoError", "Secrets"]
