"""De onde o AGR le as chaves virtuais do LiteLLM (KAM-250).

## Porque nao e o `EnvSecretProvider` de todos os outros segredos

Em `staging` e `prod` os segredos chegam ao AGR por interpolacao do compose, e o
servico declara uma **lista fixa** de `KAMBA_SECRET_*`. A chave de um tenant le-se
como `litellm_virtual_key/<tenant_id>`, que vira
`KAMBA_SECRET_LITELLM_VIRTUAL_KEY__<uuid>`: um nome que nenhum compose consegue
declarar, porque depende do tenant. Ate ao KAM-250 o AGR nao conseguia ler a chave
de tenant nenhum, nem depois de reiniciar.

Pela decisao do fundador de 2026-11-24 (bloco do KAM-250, opcao 1), as duas chaves
virtuais — a do tenant e a do screening — vivem num **projecto Doppler so delas**,
e o AGR le-as pela API, com um *token* **so de leitura** desse projecto
(`doppler_llm_chaves_leitura`). Um tenant novo nao pede reinicio, e o AGR nao ganha
acesso a mais nenhum segredo. E a excepcao a (A) do `ADR-L002`, escrita no §7 dele.

## Falha fechada

* Em `staging` e `prod` sem o *token*, as chaves **nao** se leem do ambiente: o
  `get` levanta `SecretAusenteError`, a chamada ao proxy falha e grava a linha, e
  o turno degrada (ou o screening le `condicional`). Ler do ambiente era a via
  partida que o KAM-250 fecha, e uma chave posta a mao no compose passava por
  cima do projecto que o fundador escolheu.
* Em `dev` nao ha projecto das chaves (o LiteLLM nem esta na pilha de
  desenvolvimento), e le-se do ambiente, como antes.

## A cache, e a chave que acabou de nascer

O `DopplerSecretProvider` descarrega a configuracao inteira e guarda-a 60 s. Uma
chave gravada pela saga segundos antes do primeiro turno do tenant (o
`teste_ponta_a_ponta` do KAM-091) nao estaria na descarga guardada. Por isso uma
**ausencia** pede uma descarga nova — no maximo uma por `INTERVALO_DO_REFRESCO_S`,
para que um tenant sem chave nao ponha o AGR a bater no Doppler a cada turno.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Final

from kamba_core.secrets import (
    PROJECTO_DAS_CHAVES_POR_OMISSAO,
    VARIAVEL_DO_PROJECTO,
    DopplerSecretProvider,
    SecretAusenteError,
    Secrets,
    Transporte,
    transporte_http_de_leitura,
)

#: O *token* so de leitura do projecto das chaves (`ops/secrets-inventory.yaml`).
REF_DO_TOKEN_DE_LEITURA: Final = "doppler_llm_chaves_leitura"

#: Segundos entre duas descargas forcadas por uma ausencia. ***Proposta***.
INTERVALO_DO_REFRESCO_S: Final = 10.0

#: Os ambientes onde as chaves so se leem do projecto delas.
AMBIENTES_COM_PROJECTO: Final = ("staging", "prod")


class _ComRefresco:
    """Um `SecretProvider` que, numa ausencia, descarrega outra vez (com limite)."""

    def __init__(
        self,
        guardado: DopplerSecretProvider,
        fresco: DopplerSecretProvider,
        intervalo_s: float,
        agora: Callable[[], float],
    ) -> None:
        self.nome = guardado.nome
        self.ambiente = guardado.ambiente
        self._guardado = guardado
        self._fresco = fresco
        self._intervalo = intervalo_s
        self._agora = agora
        self._ultimo: float | None = None

    def health(self) -> None:
        self._guardado.health()

    def get(self, ref: str) -> str:
        return self.get_ring(ref)[0]

    def get_ring(self, ref: str) -> tuple[str, str | None]:
        try:
            return self._guardado.get_ring(ref)
        except SecretAusenteError:
            agora = self._agora()
            if self._ultimo is not None and agora - self._ultimo < self._intervalo:
                raise
            self._ultimo = agora
            return self._fresco.get_ring(ref)

    def versions(self, ref: str) -> tuple[str, ...]:
        return self._guardado.versions(ref)


def leitor_das_chaves(
    ambiente: str,
    segredos: Secrets,
    *,
    servico: str,
    ambiente_do_processo: Mapping[str, str] | None = None,
    transporte: Transporte = transporte_http_de_leitura,
    agora: Callable[[], float] = time.monotonic,
) -> tuple[Callable[[str], str], str]:
    """Devolve `(ler, motivo)`: a funcao que le uma chave e o codigo do arranque.

    O `motivo` vai para o *log* de arranque (`error_code`), e e uma de tres
    etiquetas fixas — nunca o *token* nem o projecto.
    """
    env = os.environ if ambiente_do_processo is None else ambiente_do_processo
    if ambiente not in AMBIENTES_COM_PROJECTO:
        return segredos.get, "chaves_do_ambiente_em_dev"
    try:
        token = segredos.get(REF_DO_TOKEN_DE_LEITURA)
    except SecretAusenteError:
        def sem_token(ref: str) -> str:
            raise SecretAusenteError(ref, "doppler")

        return sem_token, "chaves_sem_token_de_leitura"
    projecto = env.get(VARIAVEL_DO_PROJECTO, PROJECTO_DAS_CHAVES_POR_OMISSAO)
    guardado = DopplerSecretProvider(ambiente, projecto, ambiente, token, transporte)
    fresco = DopplerSecretProvider(
        ambiente, projecto, ambiente, token, transporte, ttl_descarga_s=0.0
    )
    # A fachada `Secrets` da a janela de ultimo valor conhecido com o Doppler em
    # baixo (KAM-010), e nao a da a uma chave **apagada**: revogar continua imediato.
    fachada = Secrets(
        servico=servico,
        provider=_ComRefresco(guardado, fresco, INTERVALO_DO_REFRESCO_S, agora),
        obrigatorios=(),
        agora=agora,
    )
    return fachada.get, "chaves_do_projecto_proprio"


__all__ = [
    "AMBIENTES_COM_PROJECTO",
    "INTERVALO_DO_REFRESCO_S",
    "REF_DO_TOKEN_DE_LEITURA",
    "leitor_das_chaves",
]
