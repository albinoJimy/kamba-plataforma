"""O *circuit breaker* por backend (`docs/tecnica/02` §6.5, critero 7 do bloco).

«*Circuit breaker* por backend»: a unidade e o backend e nao a tool, porque o
que esta em baixo e o COM, o PAY ou o IDX — e abrir por tool deixava as outras
quatro tools do mesmo backend a bater na porta fechada uma a uma, cada uma com o
seu *timeout*.

O critero pede tres coisas, e sao as tres que este modulo tem:

1. **abre apos falhas consecutivas configuraveis** — `KAMBA_TLS_DISJUNTOR_FALHAS`;
2. **devolve `UPSTREAM_DOWN`** — quem o traduz e o `invoke`, que e quem tem o
   `ToolResult`;
3. **sem chamar o backend** — e por isso que a pergunta e `permite()` e nao
   `registar_falha()` depois do facto.

## Consecutivas, e nao numa janela

Um contador que nao se reponha ao primeiro sucesso abre por acumulacao: vinte
falhas espalhadas por uma hora, com trafego normal pelo meio, abriam o disjuntor
de um backend que esta de pe. `registar_sucesso` poe o contador a zero, e e isso
que faz da contagem uma medida de «esta em baixo **agora**».

## Meio-aberto e **uma** tentativa, e nao um pulso

Passada a pausa, o disjuntor deixa passar **uma** chamada e volta a fechar-se a
espera do resultado dela. Sem isso, um backend em baixo recebia, no instante em
que a pausa acaba, todas as chamadas que entretanto se acumularam — que e o
oposto do que um disjuntor serve para fazer. Se essa chamada falhar, a pausa
recomeca.

## O trinco e de `threading` e nao de `asyncio`

O `invoke` corre o trabalho que bloqueia em `asyncio.to_thread` (a forma do
`conversa.py` do KAM-025), pelo que `permite` e `registar_*` sao chamados de
*threads* do executor e nao so do laco de eventos. Um `asyncio.Lock` nao protege
nada nesse caminho.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

#: Falhas consecutivas por backend ate abrir. Dicionario §3.27.
VARIAVEL_DE_FALHAS: Final = "KAMBA_TLS_DISJUNTOR_FALHAS"
FALHAS_POR_OMISSAO: Final = 5

#: Quanto tempo fica aberto antes de deixar passar uma tentativa.
VARIAVEL_DE_PAUSA: Final = "KAMBA_TLS_DISJUNTOR_PAUSA_MS"
PAUSA_POR_OMISSAO_MS: Final = 30_000


class ConfiguracaoDoDisjuntorError(ValueError):
    """Um valor de configuracao que nao serve.

    Levanta no arranque — e o codigo de saida `2`, configuracao invalida — em
    vez de cair na omissao: um `KAMBA_TLS_DISJUNTOR_FALHAS=zero` lido como 5
    punha o disjuntor a funcionar com um numero que ninguem escolheu, e quem o
    escreveu ficava a acreditar no que pôs.
    """


def _inteiro_do_ambiente(variavel: str, omissao: int, minimo: int) -> int:
    bruto = os.environ.get(variavel)
    if bruto is None or bruto == "":
        return omissao
    try:
        valor = int(bruto)
    except ValueError as erro:
        raise ConfiguracaoDoDisjuntorError(
            f"{variavel}={bruto!r} nao e um inteiro"
        ) from erro
    if valor < minimo:
        raise ConfiguracaoDoDisjuntorError(
            f"{variavel}={valor} e menor do que {minimo}"
        )
    return valor


@dataclass
class _Estado:
    falhas: int = 0
    aberto_ate: float = 0.0
    #: A tentativa de meio-aberto esta entregue e ainda sem resposta.
    a_experimentar: bool = False


class Disjuntor:
    """Um contador de falhas consecutivas por backend, com pausa."""

    def __init__(
        self,
        *,
        falhas: int | None = None,
        pausa_ms: int | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._falhas_para_abrir = (
            falhas
            if falhas is not None
            else _inteiro_do_ambiente(VARIAVEL_DE_FALHAS, FALHAS_POR_OMISSAO, 1)
        )
        self._pausa_ms = (
            pausa_ms
            if pausa_ms is not None
            else _inteiro_do_ambiente(VARIAVEL_DE_PAUSA, PAUSA_POR_OMISSAO_MS, 0)
        )
        if self._falhas_para_abrir < 1:
            raise ConfiguracaoDoDisjuntorError(
                "um disjuntor que abre com zero falhas esta sempre aberto"
            )
        self._relogio = relogio
        self._trinco = threading.Lock()
        self._por_backend: dict[str, _Estado] = {}

    def permite(self, backend: str) -> bool:
        """Se a chamada pode ir ao backend. **Pergunta-se antes de a fazer.**"""
        with self._trinco:
            estado = self._por_backend.get(backend)
            if estado is None or estado.aberto_ate == 0.0:
                return True
            if self._relogio() < estado.aberto_ate:
                return False
            if estado.a_experimentar:
                # A tentativa de meio-aberto ja foi entregue a alguem e ainda
                # nao respondeu. Deixar passar a segunda era abrir a porta toda.
                return False
            estado.a_experimentar = True
            return True

    def registar_sucesso(self, backend: str) -> None:
        """Fecha o disjuntor e poe o contador a zero."""
        with self._trinco:
            self._por_backend.pop(backend, None)

    def registar_falha(self, backend: str) -> bool:
        """Conta a falha. Devolve `True` se **esta** falha abriu o disjuntor."""
        with self._trinco:
            estado = self._por_backend.setdefault(backend, _Estado())
            estado.falhas += 1
            estado.a_experimentar = False
            if estado.falhas < self._falhas_para_abrir:
                return False
            ja_estava = estado.aberto_ate > self._relogio()
            estado.aberto_ate = self._relogio() + self._pausa_ms / 1000
            return not ja_estava

    def aberto(self, backend: str) -> bool:
        """Para o log e para os testes. **Nao muta nada**, ao contrario do
        `permite`: este consome a tentativa de meio-aberto, e um observador que
        a consumisse fazia de uma leitura de painel uma decisao.
        """
        with self._trinco:
            estado = self._por_backend.get(backend)
            if estado is None:
                return False
            return self._relogio() < estado.aberto_ate
