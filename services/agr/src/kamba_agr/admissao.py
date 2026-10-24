"""A admissao: ritmo, coalescencia, tecto por *tenant* e contrapressao.

Criterios 3 e 5 do KAM-025, e as regras 2, 3 e 4 do `docs/tecnica/02` §15.2.
Isto corre **antes** da tranca, e e o que decide se um turno chega a esperar por
ela. A tranca espera sempre (`trancas.py`); quem desiste e quem recusa e este
modulo.

## A tensao entre o criterio 2 e o criterio 3, escrita porque e real

O criterio 2 pede que «20 mensagens concorrentes da mesma `thread_id`» dem
«20 turnos **em serie** (0 execucoes sobrepostas, ordem de chegada
preservada)». O criterio 3 pede que «mensagens que chegam durante um turno
ficam em fila e sao **coalescidas** se distarem < 1,5 s».

**Vinte mensagens concorrentes distam muito menos de 1,5 s uma da outra.** Com
a coalescencia ligada no valor *proposta*, as vinte do criterio 2 davam **um**
turno, nao vinte — e o criterio 2 ficava impossivel de cumprir a letra.

A leitura que se adopta, e que o proprio criterio 3 autoriza ao dizer
«configuravel»: **a coalescencia e uma janela configuravel, e o criterio 2 e a
propriedade da tranca, medida com a janela a zero.** Os dois provam-se, e nao o
mesmo:

- com `AGR_COALESCENCIA_MS = 0`, vinte mensagens dao vinte turnos em serie e por
  ordem — e o que a tranca garante, sem a coalescencia a mascarar;
- com `AGR_COALESCENCIA_MS = 1500` (a omissao *proposta*), as que distam menos
  de 1,5 s juntam-se num turno, e o `agr_coalesced_total` conta-as.

Sem a janela a zero, um defeito na tranca ficava invisivel: um turno a correr
sozinho passa o teste da serializacao por nao haver segundo turno nenhum. A
tensao fica registada em `docs/dividas-documentais.md` para quem escrever o
criterio da proxima vez; nao se marca uma caixa com a outra leitura.

## O que cada tecto e, e porque e esta a forma

**Ritmo por contacto — 20 msgs/min, *descarte silencioso* (criterio 5).**
Janela deslizante e nao *token bucket*: o criterio conta «msgs/min», e um
*bucket* com a mesma media aceita vinte de rajada e depois nada. O descarte e
**silencioso para o cliente** e nao para nos: conta em
`agr_admitted_rejected_total{motivo="ritmo"}` e escreve **um** aviso por
contacto por janela — o «aviso unico» do criterio. Um aviso por mensagem
descartada era o atacante a escolher quantas linhas de registo escrevemos.

**Tecto de concorrencia por *tenant* — 3 (criterio 5).** E o anti-vizinho-ruidoso
da regra 2 do §15.2. **E por processo**, e isso fica dito: com N replicas do
AGR o tecto efectivo e 3xN. Um tecto verdadeiramente distribuido pede um
contador em Redis, que e um ticket que ninguem abriu; o que este tecto compra, e
que a *suite* mede, e que um *tenant* com mil mensagens em fila nao esgota os
*workers* do processo. A calibracao e do KAM-084.

**Contrapressao (regra 4 do §15.2).** Passado o limiar, conta-se em
`agr_backpressure_total`. **Nao se activa o modo deterministico**, que e o
KAM-037 e nao existe: o que aqui nasce e o sinal que ele vai consumir. Dizer
«activa» era afirmar um comportamento que nenhum codigo tem.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Final

from .contexto import InvocacaoDoAgente
from .metricas import (
    METRICA_COALESCIDAS,
    METRICA_CONTRAPRESSAO,
    METRICA_FILA,
    METRICA_RECUSADOS,
    METRICAS,
)

#: Mensagens por minuto e por contacto. *Proposta* — o criterio 5 escreve-a
#: como omissao proposta, e calibra-se em KAM-084.
RITMO_POR_CONTACTO: Final = 20
#: A janela do ritmo, em segundos. Um minuto, que e a unidade do criterio.
JANELA_DO_RITMO_S: Final = 60.0
#: Turnos em curso por *tenant*, neste processo. *Proposta* (criterio 5).
TECTO_POR_TENANT: Final = 3
#: Distancia maxima entre duas mensagens para se juntarem. *Proposta*
#: (criterio 3): 1,5 s.
COALESCENCIA_MS: Final = 1_500
#: Turnos a espera a partir dos quais se conta contrapressao. *Proposta*; e o
#: «limiar» da regra 4 do §15.2, que nenhum documento numera.
LIMIAR_DE_CONTRAPRESSAO: Final = 100

#: As variaveis que mexem nos quatro numeros acima. Dicionario §3.24.
VAR_RITMO: Final = "AGR_RITMO_POR_CONTACTO"
VAR_TECTO: Final = "AGR_TECTO_POR_TENANT"
VAR_COALESCENCIA: Final = "AGR_COALESCENCIA_MS"
VAR_LIMIAR: Final = "AGR_LIMIAR_DE_CONTRAPRESSAO"


class RitmoExcedidoError(RuntimeError):
    """O contacto passou o limite de mensagens por minuto. Descarte silencioso."""


class TectoDoTenantCheioError(RuntimeError):
    """O tecto de concorrencia do *tenant* esta cheio. O chamador recebe 503."""


def _inteiro(variavel: str, omissao: int, ambiente: dict[str, str] | None = None) -> int:
    """Le um inteiro >= 0 do ambiente, ou a omissao.

    Um valor que nao e inteiro **levanta** em vez de cair na omissao, pela
    razao do `port()` do `kamba_core`: um tecto mal escrito que caia em silencio
    na omissao e um tecto que ninguem configurou a parecer configurado. A
    mensagem nao repete o valor — ele vem do ambiente e pode ser qualquer coisa.
    """
    cru = (ambiente if ambiente is not None else os.environ).get(variavel)
    if cru is None or cru.strip() == "":
        return omissao
    try:
        valor = int(cru.strip())
    except ValueError:
        raise ValueError(f"{variavel} nao e um inteiro") from None
    if valor < 0:
        raise ValueError(f"{variavel} e negativo")
    return valor


@dataclass(frozen=True, slots=True)
class Tectos:
    """Os quatro numeros, lidos uma vez no arranque."""

    ritmo_por_contacto: int = RITMO_POR_CONTACTO
    tecto_por_tenant: int = TECTO_POR_TENANT
    coalescencia_ms: int = COALESCENCIA_MS
    limiar_de_contrapressao: int = LIMIAR_DE_CONTRAPRESSAO

    @classmethod
    def do_ambiente(cls, ambiente: dict[str, str] | None = None) -> Tectos:
        return cls(
            ritmo_por_contacto=_inteiro(VAR_RITMO, RITMO_POR_CONTACTO, ambiente),
            tecto_por_tenant=_inteiro(VAR_TECTO, TECTO_POR_TENANT, ambiente),
            coalescencia_ms=_inteiro(VAR_COALESCENCIA, COALESCENCIA_MS, ambiente),
            limiar_de_contrapressao=_inteiro(
                VAR_LIMIAR, LIMIAR_DE_CONTRAPRESSAO, ambiente
            ),
        )


@dataclass(slots=True)
class Pendente:
    """Uma invocacao a espera de entrar num turno, com a hora a que chegou.

    O `espera` e um `Future` do *loop* a correr, e nao um `asyncio.Future()` a
    seco: o construtor sem argumentos vai ao `get_event_loop()`, que em Python
    3.12 ja avisa e em 3.14 levanta fora de uma corrotina. Criar pelo *loop*
    corrente diz, no sitio, de quem e o `Future`.
    """

    invocacao: InvocacaoDoAgente
    chegou_em: float
    espera: asyncio.Future = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )


class Admissao:
    """Ritmo, coalescencia, tecto por *tenant* e contrapressao, num objecto.

    `relogio` e injectado para que a janela do ritmo e a da coalescencia se
    testem com um relogio fixo em vez de com `sleep` — a mesma escolha que o
    `tests_eventos_consumo` fez com a escada de recuo, e pela mesma razao: o
    teste mede a regra, nao a paciencia de quem o corre.
    """

    def __init__(
        self,
        tectos: Tectos | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tectos = tectos or Tectos()
        self._agora = relogio
        self._chegadas: dict[str, collections.deque[float]] = {}
        self._avisado: dict[str, float] = {}
        self._em_curso: dict[str, int] = {}
        self._a_espera = 0

    # ---------------------------------------------------------------- ritmo

    def aceita_o_ritmo(self, invocacao: InvocacaoDoAgente) -> bool:
        """`True` se o contacto ainda tem quota na janela. Criterio 5.

        A chave e `thread_id`, que **ja e** `(tenant_id, contact_id)`: um
        contacto do *tenant* A e outro do B nunca partilham quota, e o mesmo
        contacto em dois canais do mesmo *tenant* partilha-a — que e o que «por
        contacto» quer dizer.
        """
        if self._tectos.ritmo_por_contacto == 0:
            return True
        agora = self._agora()
        chegadas = self._chegadas.setdefault(invocacao.thread_id, collections.deque())
        limite = agora - JANELA_DO_RITMO_S
        while chegadas and chegadas[0] <= limite:
            chegadas.popleft()
        if len(chegadas) >= self._tectos.ritmo_por_contacto:
            METRICAS.contar(METRICA_RECUSADOS, "ritmo")
            return False
        chegadas.append(agora)
        return True

    def deve_avisar(self, invocacao: InvocacaoDoAgente) -> bool:
        """`True` uma vez por contacto por janela. O «aviso unico» do criterio 5."""
        agora = self._agora()
        ultimo = self._avisado.get(invocacao.thread_id)
        if ultimo is not None and agora - ultimo < JANELA_DO_RITMO_S:
            return False
        self._avisado[invocacao.thread_id] = agora
        return True

    # ------------------------------------------------------- tecto e fila

    @contextlib.asynccontextmanager
    async def vaga(self, invocacao: InvocacaoDoAgente) -> AsyncIterator[None]:
        """Uma vaga no tecto do *tenant*, ou `TectoDoTenantCheioError`.

        **Nao espera.** O criterio 5 quer que um *tenant* com mil mensagens em
        fila nao mexa no p95 de outro, e uma espera dentro do pedido punha as
        mil a ocupar *workers* a dormir. Recusar devolve o *job* a fila com
        atraso, que e contrapressao a funcionar.
        """
        tenant = invocacao.tenant_id
        if self._tectos.tecto_por_tenant == 0:
            # Zero e **sem tecto**, como no ritmo. E o modo em que o criterio 2
            # se mede: vinte mensagens concorrentes da mesma `thread_id` com o
            # tecto a 3 davam dezessete recusas e tres turnos, nao vinte turnos
            # em serie. O criterio 5 mede o tecto em bateria propria. E a mesma
            # leitura que a janela da coalescencia: o que o criterio 2 prova e a
            # tranca, e os tectos desligam-se para a deixar ver.
            yield
            return
        if self._em_curso.get(tenant, 0) >= self._tectos.tecto_por_tenant:
            METRICAS.contar(METRICA_RECUSADOS, "tecto_do_tenant")
            raise TectoDoTenantCheioError("tecto_do_tenant")
        self._em_curso[tenant] = self._em_curso.get(tenant, 0) + 1
        try:
            yield
        finally:
            restantes = self._em_curso[tenant] - 1
            if restantes:
                self._em_curso[tenant] = restantes
            else:
                # Sem isto, o dicionario cresce com um *tenant* por chave e
                # nunca encolhe — memoria ilimitada a custa de outrem, a razao
                # do `MAXIMO_DE_CANAIS` do `chr/contrato.ts`.
                del self._em_curso[tenant]

    @contextlib.contextmanager
    def na_fila(self):
        """Conta um turno a espera, e a contrapressao quando passa o limiar."""
        self._a_espera += 1
        METRICAS.medir(METRICA_FILA, self._a_espera)
        if self._a_espera == self._tectos.limiar_de_contrapressao:
            # No igual e nao no maior, para contar a **passagem** do limiar e
            # nao cada turno acima dele: um contador que soma a cada turno sob
            # carga mede a carga, nao as vezes que a fila transbordou.
            METRICAS.contar(METRICA_CONTRAPRESSAO)
        try:
            yield
        finally:
            self._a_espera -= 1
            METRICAS.medir(METRICA_FILA, self._a_espera)

    @property
    def a_espera(self) -> int:
        return self._a_espera

    def em_curso(self, tenant_id: str) -> int:
        return self._em_curso.get(tenant_id, 0)

    # ------------------------------------------------------- coalescencia

    def coalescer(
        self, pendentes: list[Pendente]
    ) -> tuple[list[Pendente], list[Pendente]]:
        """Parte os pendentes no lote que corre agora e no que fica.

        Entra o primeiro; entram os seguintes enquanto distarem menos do que a
        janela **do anterior admitido**, e nao do primeiro. A diferenca
        importa: com a distancia ao primeiro, uma rajada de dez mensagens a
        1,4 s de intervalo dava dois lotes; com a distancia ao anterior da um,
        que e o que «distarem < 1,5 s» diz — a frase fala de duas mensagens
        consecutivas.

        Com a janela a zero, nada coalesce: cada mensagem e um turno. E o modo
        em que o criterio 2 se mede (ver a *docstring* do modulo).
        """
        if not pendentes:
            return [], []
        janela = self._tectos.coalescencia_ms / 1_000.0
        if janela <= 0:
            return pendentes[:1], pendentes[1:]
        lote = [pendentes[0]]
        for pendente in pendentes[1:]:
            if pendente.chegou_em - lote[-1].chegou_em >= janela:
                break
            lote.append(pendente)
        if len(lote) > 1:
            METRICAS.contar(METRICA_COALESCIDAS, quanto=len(lote) - 1)
        return lote, pendentes[len(lote) :]
