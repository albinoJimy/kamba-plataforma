"""Gate 17 — deploy *rolling*, reversao automatica e a reconciliacao do ensaio.

Tres criterios do bloco, e as tres decisoes que eles pedem vivem aqui:

1. **O *rolling*.** «GWY e *workers* (2 replicas: esvaziar, actualizar,
   verificar `/healthz` e metricas, passar a outra)», e «dois *workers* nunca
   ficam em actualizacao em simultaneo». `rolar` faz uma replica de cada vez,
   **por construcao**: nao ha paralelismo para desligar.
2. **A reversao.** «Uma release deliberadamente invalida (`/healthz` falha) e
   revertida para o `release.lock` anterior sem intervencao humana em ≤ 5 min
   (*proposta*)». Quando uma replica nao fica saudavel no prazo, `rolar` repoe a
   imagem do lock anterior em **todas** as replicas que ja tinha mudado,
   incluindo a que falhou, pela ordem inversa — e mede quanto demorou.
3. **A reconciliacao.** «Sob trafego sintetico de 5 msg/s durante 5 min (1.500
   mensagens): 0 perdidas, 0 duplicadas, ack < 500 ms em ≥ 99,9%». `reconciliar`
   e a conta, sobre os ids enviados, processados e respondidos.

## O que nao esta aqui, e porque

**A plataforma concreta.** `rolar` fala com o mundo pela porta `Plataforma` —
esvaziar, implantar, sondar, retomar. O adaptador que a implementa contra um
*host* (o Compose do KAM-076, as duas replicas do `gwy`) **nao existe**: nao ha
*host* de *staging* nem de producao (D1, KAM-077), e um adaptador que nunca
correu contra um *host* e uma afirmacao sobre um sistema que ninguem viu. Os
ensaios usam um duplo que regista a ordem das chamadas e a concorrencia.

**O ensaio sob carga.** A reconciliacao e a conta; as 1.500 mensagens a 5 msg/s
sao do simulador do KAM-024 contra o *host*. Ficam por medir com o *host*.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Callable, Protocol

from .lock import Lock

#: Quanto tempo uma replica tem para ficar saudavel depois de implantada.
#: *Proposta*: e o mesmo minuto da paragem graciosa do *worker* (Detalhes
#: Tecnicos do bloco), e calibra-se no *host*.
PRAZO_DE_SAUDE_S = 60.0

#: Intervalo entre sondas. *Proposta*.
INTERVALO_DE_SONDA_S = 2.0

#: O tecto da reversao automatica, do criterio 5. *Proposta* do bloco.
PRAZO_DE_REVERSAO_S = 300.0


class Plataforma(Protocol):
    def replicas(self, servico: str) -> list[str]: ...
    def esvaziar(self, replica: str) -> None: ...
    def implantar(self, replica: str, imagem: str) -> None: ...
    def saudavel(self, replica: str) -> bool: ...
    def retomar(self, replica: str) -> None: ...


@dataclasses.dataclass
class Desfecho:
    #: `implantado`, `revertido` ou `reversao_falhou`.
    estado: str
    registo: list[str]
    #: Segundos da deteccao da falha ao fim da reversao; `None` sem falha.
    segundos_de_reversao: float | None = None
    #: A replica que nao ficou saudavel.
    falhou_em: str | None = None

    @property
    def dentro_do_prazo_de_reversao(self) -> bool | None:
        if self.segundos_de_reversao is None:
            return None
        return self.segundos_de_reversao <= PRAZO_DE_REVERSAO_S


def _esperar_saude(
    plataforma: Plataforma,
    replica: str,
    relogio: Callable[[], float],
    dormir: Callable[[float], None],
    prazo: float,
) -> bool:
    limite = relogio() + prazo
    while True:
        if plataforma.saudavel(replica):
            return True
        if relogio() >= limite:
            return False
        dormir(INTERVALO_DE_SONDA_S)


def rolar(
    novo: Lock,
    anterior: Lock,
    servicos: list[str],
    plataforma: Plataforma,
    relogio: Callable[[], float],
    dormir: Callable[[float], None],
    prazo_de_saude: float = PRAZO_DE_SAUDE_S,
) -> Desfecho:
    """Implanta `novo` replica a replica; reverte para `anterior` se falhar.

    So os servicos de `servicos` cuja imagem mudou entre os dois locks. Um
    servico em `servicos` que nao esta no lock novo e erro de quem chama, e
    levanta antes de tocar em qualquer replica.
    """
    for servico in servicos:
        if servico not in novo.servicos:
            raise ValueError(f"{servico}: nao esta no lock novo")
    mudam = [
        s for s in servicos
        if anterior.servicos.get(s) is None
        or anterior.servicos[s].imagem != novo.servicos[s].imagem
    ]
    registo: list[str] = []
    feitas: list[tuple[str, str]] = []

    for servico in mudam:
        for replica in plataforma.replicas(servico):
            registo.append(f"esvaziar {replica}")
            plataforma.esvaziar(replica)
            feitas.append((servico, replica))
            registo.append(f"implantar {replica} {novo.servicos[servico].imagem}")
            plataforma.implantar(replica, novo.servicos[servico].imagem)
            if not _esperar_saude(plataforma, replica, relogio, dormir, prazo_de_saude):
                registo.append(f"falhou {replica}")
                inicio = relogio()
                ok = _reverter(anterior, feitas, plataforma, relogio, dormir, prazo_de_saude, registo)
                return Desfecho(
                    estado="revertido" if ok else "reversao_falhou",
                    registo=registo,
                    segundos_de_reversao=relogio() - inicio,
                    falhou_em=replica,
                )
            registo.append(f"retomar {replica}")
            plataforma.retomar(replica)
    return Desfecho(estado="implantado", registo=registo)


def _reverter(
    anterior: Lock,
    feitas: list[tuple[str, str]],
    plataforma: Plataforma,
    relogio: Callable[[], float],
    dormir: Callable[[float], None],
    prazo_de_saude: float,
    registo: list[str],
) -> bool:
    """Repoe o lock anterior, pela ordem inversa, uma replica de cada vez.

    **Continua depois de uma falha**, e devolve `False` no fim: parar a meio
    deixava as replicas que faltam na imagem que acabou de falhar, e e melhor
    ter mais replicas na imagem antiga do que menos. Uma replica cujo servico
    nao existe no lock anterior (um servico novo) nao tem para onde voltar:
    fica esvaziada, e a reversao conta como falhada — e humano.
    """
    tudo_bem = True
    for indice, (servico, replica) in enumerate(reversed(feitas)):
        if indice > 0:
            # A que falhou ja esta esvaziada; as outras estavam a servir.
            registo.append(f"esvaziar {replica}")
            plataforma.esvaziar(replica)
        entrada = anterior.servicos.get(servico)
        if entrada is None:
            registo.append(f"sem-anterior {replica}")
            tudo_bem = False
            continue
        registo.append(f"repor {replica} {entrada.imagem}")
        plataforma.implantar(replica, entrada.imagem)
        if not _esperar_saude(plataforma, replica, relogio, dormir, prazo_de_saude):
            registo.append(f"reposicao-falhou {replica}")
            tudo_bem = False
            continue
        registo.append(f"retomar {replica}")
        plataforma.retomar(replica)
    return tudo_bem


# --------------------------------------------------------------------------
# Reconciliacao do ensaio sob carga
# --------------------------------------------------------------------------

#: 5 msg/s durante 5 min, do criterio 4.
MENSAGENS_ESPERADAS = 1500
ACK_LIMIAR_MS = 500.0
ACK_FRACCAO_MINIMA = 0.999


@dataclasses.dataclass(frozen=True)
class Reconciliacao:
    enviadas: int
    perdidas: tuple[str, ...]
    sem_resposta: tuple[str, ...]
    duplicadas: tuple[str, ...]
    estranhas: tuple[str, ...]
    fraccao_ack_ok: float
    acks_em_falta: int
    esperadas: int

    @property
    def verde(self) -> bool:
        return (
            self.enviadas == self.esperadas
            and not self.perdidas
            and not self.sem_resposta
            and not self.duplicadas
            and not self.estranhas
            and self.acks_em_falta == 0
            and self.fraccao_ack_ok >= ACK_FRACCAO_MINIMA
        )

    def resumo(self) -> str:
        return (
            f"{'VERDE' if self.verde else 'VERMELHO'}: {self.enviadas}/{self.esperadas} "
            f"enviadas, {len(self.perdidas)} perdidas, {len(self.sem_resposta)} sem "
            f"resposta, {len(self.duplicadas)} duplicadas, {len(self.estranhas)} "
            f"estranhas, ack < {ACK_LIMIAR_MS:g} ms em {self.fraccao_ack_ok:.4%} "
            f"({self.acks_em_falta} acks em falta)"
        )


def _repetidos(ids: list[str]) -> set[str]:
    vistos: set[str] = set()
    repetidos: set[str] = set()
    for i in ids:
        if i in vistos:
            repetidos.add(i)
        vistos.add(i)
    return repetidos


def reconciliar(
    enviados: list[str],
    processados: list[str],
    respostas: list[str],
    acks_ms: dict[str, float],
    esperadas: int = MENSAGENS_ESPERADAS,
) -> Reconciliacao:
    """Enviados × processados × respostas, e o ack de cada enviado.

    * **perdida**: enviada e nunca processada;
    * **sem resposta**: processada e sem resposta — a perda a jusante;
    * **duplicada**: processada ou respondida mais de uma vez, que e o efeito
      de negocio duplicado que o DoD proibe;
    * **estranha**: processada ou respondida sem ter sido enviada — um id que
      nao e deste ensaio contamina a conta, e nao se ignora;
    * o ack conta-se **por enviado**: um enviado sem ack medido conta contra a
      fraccao, em vez de sair do denominador.
    """
    conjunto = set(enviados)
    processado = set(processados)
    respondido = set(respostas)
    ok = sum(1 for i in conjunto if acks_ms.get(i) is not None and acks_ms[i] < ACK_LIMIAR_MS)
    em_falta = sum(1 for i in conjunto if acks_ms.get(i) is None)
    fraccao = ok / len(conjunto) if conjunto else 0.0
    return Reconciliacao(
        enviadas=len(enviados),
        perdidas=tuple(sorted(conjunto - processado)),
        sem_resposta=tuple(sorted((conjunto & processado) - respondido)),
        duplicadas=tuple(sorted(_repetidos(processados) | _repetidos(respostas) | _repetidos(enviados))),
        estranhas=tuple(sorted((processado | respondido) - conjunto)),
        fraccao_ack_ok=math.floor(fraccao * 1_000_000) / 1_000_000,
        acks_em_falta=em_falta,
        esperadas=esperadas,
    )
