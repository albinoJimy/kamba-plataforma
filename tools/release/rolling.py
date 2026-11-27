"""Gate 17 — deploy *rolling*, reversao automatica e a reconciliacao do ensaio.

Tres criterios do bloco, e as tres decisoes que eles pedem vivem aqui:

1. **O *rolling*.** «GWY e *workers* (2 replicas: esvaziar, actualizar,
   verificar `/healthz` e metricas, passar a outra)», e «dois *workers* nunca
   ficam em actualizacao em simultaneo». `rolar` faz uma replica de cada vez,
   **por construcao**: nao ha paralelismo para desligar.
2. **A reversao.** «Uma release deliberadamente invalida (`/healthz` falha) e
   revertida para o `release.lock` anterior sem intervencao humana em ≤ 5 min
   (*proposta*)». Quando uma replica nao fica saudavel no prazo, ou a
   plataforma levanta a meio, `rolar` repoe a imagem do lock anterior nas
   replicas que ja tinha mudado, incluindo a que falhou, pela ordem inversa — e
   para na primeira que nao volta, em vez de esvaziar as que servem. Mede quanto
   demorou.
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


def _tentar(accao: Callable[[], object], registo: list[str], nome: str) -> bool:
    """Uma excepcao da plataforma e uma falha, e nao um fim sem desfecho.

    A primeira versao deixava-a subir: um `pull` que falhasse na segunda replica
    saia com a primeira na imagem nova, a segunda esvaziada, e nenhuma reversao
    (achado da revisao adversarial). Contra «revertida sem intervencao humana».
    """
    try:
        accao()
    except Exception as excepcao:  # noqa: BLE001 — a plataforma e de terceiros
        registo.append(f"excepcao {nome}: {type(excepcao).__name__}: {excepcao}")
        return False
    return True


def _esperar_saude(
    plataforma: Plataforma,
    replica: str,
    relogio: Callable[[], float],
    dormir: Callable[[float], None],
    prazo: float,
    registo: list[str],
) -> bool:
    limite = relogio() + prazo
    while True:
        try:
            if plataforma.saudavel(replica):
                return True
        except Exception as excepcao:  # noqa: BLE001 — uma sonda que rebenta nao e saude
            registo.append(f"excepcao saudavel {replica}: {type(excepcao).__name__}")
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

    So os servicos de `servicos` cuja imagem mudou entre os dois locks. Levanta
    `ValueError` **antes de tocar em qualquer replica** quando um servico nao
    esta no lock novo, aparece duas vezes, ou nao tem replicas: as tres sao
    erro de quem chama, e um *rolling* que nao implanta nada nao e `implantado`.

    O tempo de reversao conta-se **do momento em que se esvaziou a replica que
    falhou**, e nao da deteccao: a espera pela saude e parte do que o cliente
    sente, e o criterio dos 5 min e sobre a release invalida no ar.
    """
    if len(set(servicos)) != len(servicos):
        raise ValueError(f"servicos repetidos: {servicos}")
    for servico in servicos:
        if servico not in novo.servicos:
            raise ValueError(f"{servico}: nao esta no lock novo")
    mudam = [
        s for s in servicos
        if anterior.servicos.get(s) is None
        or anterior.servicos[s].imagem != novo.servicos[s].imagem
    ]
    replicas = {s: list(plataforma.replicas(s)) for s in mudam}
    for servico, lista in replicas.items():
        if not lista or len(set(lista)) != len(lista):
            raise ValueError(f"{servico}: replicas vazias ou repetidas ({lista})")

    registo: list[str] = []
    feitas: list[tuple[str, str]] = []
    for servico in mudam:
        for replica in replicas[servico]:
            inicio = relogio()
            registo.append(f"esvaziar {replica}")
            if not _tentar(lambda: plataforma.esvaziar(replica), registo, f"esvaziar {replica}"):
                # Pode ter ficado meio esvaziada: entra nas que se repoem.
                feitas.append((servico, replica))
                return _falhar(anterior, feitas, plataforma, relogio, dormir, prazo_de_saude, registo, replica, inicio)
            feitas.append((servico, replica))
            imagem = novo.servicos[servico].imagem
            registo.append(f"implantar {replica} {imagem}")
            ok = _tentar(lambda: plataforma.implantar(replica, imagem), registo, f"implantar {replica}")
            if not ok or not _esperar_saude(plataforma, replica, relogio, dormir, prazo_de_saude, registo):
                return _falhar(anterior, feitas, plataforma, relogio, dormir, prazo_de_saude, registo, replica, inicio)
            registo.append(f"retomar {replica}")
            if not _tentar(lambda: plataforma.retomar(replica), registo, f"retomar {replica}"):
                return _falhar(anterior, feitas, plataforma, relogio, dormir, prazo_de_saude, registo, replica, inicio)
    return Desfecho(estado="implantado", registo=registo)


def _falhar(
    anterior: Lock,
    feitas: list[tuple[str, str]],
    plataforma: Plataforma,
    relogio: Callable[[], float],
    dormir: Callable[[float], None],
    prazo_de_saude: float,
    registo: list[str],
    replica: str,
    inicio: float,
) -> Desfecho:
    registo.append(f"falhou {replica}")
    ok = _reverter(anterior, feitas, plataforma, relogio, dormir, prazo_de_saude, registo)
    return Desfecho(
        estado="revertido" if ok else "reversao_falhou",
        registo=registo,
        segundos_de_reversao=relogio() - inicio,
        falhou_em=replica,
    )


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

    **Para na primeira replica que nao volta**, e devolve `False`. A primeira
    versao continuava, e a revisao adversarial mostrou o custo: com a segunda
    replica do `gwy` fora e sem voltar, ia esvaziar a primeira — a unica
    saudavel, na imagem nova — e deixava o servico com zero replicas a servir.
    Parar deixa as que faltam na imagem nova **e a servir**, que e o estado que
    um humano consegue ler e corrigir (`docs/runbooks/deploy-e-reversao.md`
    §4.2). Uma replica cujo servico nao existe no lock anterior (um servico novo)
    nao tem para onde voltar: fica esvaziada, e a reversao para ai.
    """
    for indice, (servico, replica) in enumerate(reversed(feitas)):
        if indice > 0:
            # A que falhou ja esta esvaziada; as outras estavam a servir.
            registo.append(f"esvaziar {replica}")
            if not _tentar(lambda: plataforma.esvaziar(replica), registo, f"esvaziar {replica}"):
                return False
        entrada = anterior.servicos.get(servico)
        if entrada is None:
            registo.append(f"sem-anterior {replica}")
            return False
        registo.append(f"repor {replica} {entrada.imagem}")
        if not _tentar(lambda: plataforma.implantar(replica, entrada.imagem), registo, f"repor {replica}"):
            registo.append(f"reposicao-falhou {replica}")
            return False
        if not _esperar_saude(plataforma, replica, relogio, dormir, prazo_de_saude, registo):
            registo.append(f"reposicao-falhou {replica}")
            return False
        registo.append(f"retomar {replica}")
        if not _tentar(lambda: plataforma.retomar(replica), registo, f"retomar {replica}"):
            return False
    return True


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
      fraccao, em vez de sair do denominador; e um ack negativo ou NaN nao e
      um ack medido, e conta contra.
    """
    conjunto = set(enviados)
    processado = set(processados)
    respondido = set(respostas)
    ok = sum(1 for i in conjunto if acks_ms.get(i) is not None and 0 <= acks_ms[i] < ACK_LIMIAR_MS)
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
