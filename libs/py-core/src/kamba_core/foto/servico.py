"""O `enhance_image` e o trabalhador do pipeline assincrono (KAM-120).

Duas entradas, e a separacao e o criterio 9:

| Entrada | O que faz | Rede |
|---|---|---|
| `enhance_image` | consome `imagens_mes`, cria o trabalho `pendente` e devolve «a preparar» | nenhuma para fora: base e TEN |
| `processar` | o trabalhador: *gate*, minimizacao, fornecedor, contingencia, STO | e aqui que a foto sai |

O `enhance_image` responde sem esperar pelo fornecedor, e e isso que faz a
confirmacao caber em 3 s; o `processar` corre no consumidor da fila. **A fila
nao esta ligada neste ticket**: a casca BullMQ → Python e o KAM-194 (a ponte
fila → consumidor Python), e o `processar` e o que essa casca chama.

## O original nunca muda

O `enhance_image` recebe a chave do original no STO e **nunca escreve nela**: a
versao vai para uma chave nova da classe `foto`, e a linha guarda as duas. O
original e o que vale enquanto o dono nao escolher a versao (`escolher`), e
continua recuperavel depois (`original`).

## A ordem do `processar`, e porque cada passo esta onde esta

1. Fora de `prod`, so imagens declaradas sinteticas (criterio 5).
2. O *gate* de transferencia, finalidade `imagem`, **para cada fornecedor**
   antes de lhe enviar (criterio 5, ADR-008). Um nao autorizado sai dos
   candidatos; sem nenhum, `bloqueada_gate`.
3. A carta: uma imagem real so vai a fornecedores com `real_data_ok`
   (criterio 8).
4. A minimizacao local (criterios 3 e 4): EXIF, tamanho, rostos e matriculas.
5. `a_processar`, escrito contra a versao lida: um segundo trabalhador com a
   mesma entrega perde aqui e **nao** chama o fornecedor.
6. O fornecedor, com a verificacao em bytes imediatamente antes; a falha ou o
   *timeout* passam para a contingencia **uma** vez.
7. A versao vai para o STO, e o resultado e apagado no fornecedor onde a API o
   permita (criterio 10).

## O custo

`custo_usd` soma **todas** as tentativas, incluindo a que falhou e se pagou. E
custo de fornecedor, nao cobranca ao tenant; a do tenant e o `imagens_mes`, e
consome-se **uma** vez por chave de idempotencia. A consolidacao do custo por
modulo e por tenant e do KAM-124, que le esta coluna.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

from ..catalogo.exif import formato
from ..destinos.porta import FINALIDADE_IMAGEM
from ..storage.chave import nova_chave
from ..storage.port import Ctx, ObjectMeta, ObjectoInexistenteError, ObjectRef, StorageProvider
from . import estados
from .fornecedor import (
    ETIQUETA_GERADA,
    GENERATIVAS,
    OPERACAO_VARIACAO_LIFESTYLE,
    OPERACOES,
    TIMEOUT_S,
    ErroDoFornecedor,
    ImageProvider,
    Melhoria,
    Opcoes,
    validar_configuracao,
)
from .minimizacao import TAMANHO_MAXIMO, DetectorLocal, Redimensionador, minimizar, pode_sair
from .repositorio import CLASSE_STO, ConflitoDeEstado, Repositorio, Trabalho, novo_id, validar

#: O ambiente em que entram imagens reais.
AMBIENTE_PROD: Final = "prod"

#: A chave de limite do TEN (`docs/ten.md`, contador por periodo).
CHAVE_DE_LIMITE: Final = "imagens_mes"
MODULO: Final = "foto"

#: *Proposta*: quanto tempo a versao fica no STO, o mesmo da foto da ingestao.
RETENCAO_DA_VERSAO: Final = timedelta(days=90)

#: O aviso da primeira utilizacao (criterio 10). Mostra-se uma vez por tenant e
#: regista-se na linha (`aviso_at`).
AVISO_ESTRANGEIRO: Final = "Esta foto vai ser processada por serviço de IA no estrangeiro."

#: Os motivos de um pedido que nao chega a ser trabalho.
MOTIVO_LIMITE: Final = "limite_excedido"
MOTIVO_SEM_ENTITLEMENT: Final = "sem_entitlement"

#: *Proposta*: um `a_processar` sem escrita ha mais disto esta preso. Maior do
#: que as duas tentativas do criterio 9 somadas (2 x 45 s), com folga.
PRESO_APOS: Final = timedelta(minutes=5)


class OperacaoRecusada(ValueError):
    """Operacao fora do dominio, ou a `variacao_lifestyle` com as variacoes desligadas."""


class ChaveReutilizada(ValueError):
    """A mesma chave de idempotencia com outra foto ou outra operacao."""


class TrabalhoInexistente(LookupError):
    """Nao ha esse trabalho **neste** tenant."""


@runtime_checkable
class PortaDeDestinos(Protocol):
    """O `autorizar` do KAM-069: levanta se o destino nao estiver autorizado."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None: ...


@dataclass(frozen=True)
class Consumo:
    aceite: bool
    motivo: str | None = None


@runtime_checkable
class PortaDeQuota(Protocol):
    """O `imagens_mes` do TEN. Idempotente pela chave: repetir nao conta outra vez."""

    def consumir(self, tenant_id: str, idempotency_key: str) -> Consumo: ...


@dataclass(frozen=True)
class Resultado:
    """O que o canal precisa para responder ao dono."""

    trabalho: Trabalho | None
    motivo: str | None = None
    #: O texto do aviso da primeira utilizacao, quando e para mostrar.
    aviso: str | None = None
    #: A falha final: o canal avisa o dono, e o original fica.
    avisar_dono: bool = False

    @property
    def estado(self) -> str | None:
        return self.trabalho.estado if self.trabalho is not None else None

    @property
    def etiqueta(self) -> str | None:
        """«gerada por IA» numa versao generativa; `None` nas outras."""
        if self.trabalho is not None and self.trabalho.gerado_por_ia:
            return ETIQUETA_GERADA
        return None


def _monotonico_ms() -> float:
    return time.monotonic() * 1000.0


def _custo(valor: object) -> Decimal:
    """O custo de uma tentativa, como `Decimal` finito e nao negativo.

    Um adaptador que devolva `float`, `NaN` ou lixo nao pode deixar o trabalho
    preso depois de o fornecedor ter sido pago (achado da revisao adversarial):
    o `float` converte-se pelo texto, e o resto conta como zero.
    """
    try:
        custo = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except Exception:  # noqa: BLE001
        return Decimal(0)
    if not custo.is_finite() or custo < 0:
        return Decimal(0)
    return custo


@dataclass
class ServicoDeFoto:
    """O pipeline. Todas as portas sao obrigatorias: nao ha omissao que deixe passar."""

    repositorio: Repositorio
    storage: StorageProvider
    fornecedores: Sequence[ImageProvider]
    destinos: PortaDeDestinos
    detector: DetectorLocal
    redimensionador: Redimensionador
    quota: PortaDeQuota
    ambiente: str
    #: A `variacao_lifestyle` (criterio 1): desligada por omissao.
    variacoes_ligadas: bool = False
    agora: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    relogio_ms: Callable[[], float] = _monotonico_ms

    def __post_init__(self) -> None:
        # O teste de arranque do criterio 6: a lista de recusa, o tier e a forma.
        self.fornecedores = validar_configuracao(self.fornecedores)

    # ------------------------------------------------------------ entradas

    def enhance_image(
        self,
        tenant_id: str,
        origem_ref: str,
        operacao: str,
        idempotency_key: str,
        *,
        sintetica: bool = False,
    ) -> Resultado:
        """A tool (write): pede uma versao nova. Nao chama o fornecedor."""
        if operacao not in OPERACOES:
            raise OperacaoRecusada(f"operacao `{operacao}` fora de {OPERACOES}")
        if operacao == OPERACAO_VARIACAO_LIFESTYLE and not self.variacoes_ligadas:
            raise OperacaoRecusada("as variacoes generativas estao desligadas nesta configuracao")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("um pedido leva a chave de idempotencia")

        pedido = Trabalho(
            image_job_id=novo_id(),
            tenant_id=tenant_id,
            origem_ref=origem_ref,
            operacao=operacao,
            provider=self.fornecedores[0].nome,
            idempotency_key=idempotency_key,
            # **Em `prod` nao ha imagens sinteticas**: a declaracao so vale
            # fora dele, onde e a barreira do criterio 5. Em `prod` uma foto
            # declarada sintetica passava ao lado do filtro da carta
            # (achado da revisao adversarial).
            sintetica=bool(sintetica) and self.ambiente != AMBIENTE_PROD,
        )
        # Primeiro valida-se, depois consome-se: um pedido que a base recusaria
        # (origem de outro tenant, chave comprida demais) nao gasta quota
        # (achado da revisao adversarial).
        validar(pedido)

        # O limite do mes: acima dele **nao nasce trabalho**. O consumo e
        # idempotente pela mesma chave, pelo que a repeticao de um pedido
        # aceite e aceite outra vez sem contar.
        consumo = self.quota.consumir(tenant_id, f"foto:{idempotency_key}")
        if not consumo.aceite:
            return Resultado(None, motivo=consumo.motivo or MOTIVO_LIMITE)

        primeiro = not self.repositorio.tem_trabalhos(tenant_id)
        linha = self.repositorio.inserir(replace(pedido, aviso_at=self.agora() if primeiro else None))
        if (linha.origem_ref, linha.operacao) != (origem_ref, operacao):
            # A mesma chave com outro pedido nao e repeticao: e um erro de quem
            # chama, e devolver o trabalho da primeira foto em silencio era
            # responder sobre outra coisa.
            raise ChaveReutilizada("a chave de idempotencia ja serviu outro pedido")
        return Resultado(linha, aviso=AVISO_ESTRANGEIRO if linha.aviso_at is not None else None)

    def processar(self, tenant_id: str, image_job_id: str) -> Resultado:
        """O trabalhador. Um `pendente` ou um `bloqueada_gate`; o resto devolve-se como esta.

        **Um `a_processar` nao se toca aqui**: outro trabalhador esta com ele, e
        voltar a escreve-lo fazia-o ganhar a versao e chamar o fornecedor duas
        vezes. Um que ficou preso por um processo morto e o `recuperar`.
        """
        linha = self._ler(tenant_id, image_job_id)
        if linha.estado not in (estados.PENDENTE, estados.BLOQUEADA_GATE):
            return Resultado(linha)
        return self._correr(linha)

    def recuperar(self, tenant_id: str, image_job_id: str) -> Resultado:
        """Um `a_processar` que ficou preso: sem escrita ha mais de `PRESO_APOS`.

        **O predicado e daqui, e nao de quem chama** (achado da revisao
        adversarial): com um trabalhador vivo dentro do `enhance`, um
        `recuperar` sem ele chamava o fornecedor outra vez. `PRESO_APOS` e
        maior do que as duas tentativas somadas, pelo que um trabalhador vivo
        nunca esta «preso».
        """
        linha = self._ler(tenant_id, image_job_id)
        if linha.estado != estados.A_PROCESSAR or linha.atualizado_at is None:
            return Resultado(linha)
        if self.agora() - linha.atualizado_at < PRESO_APOS:
            return Resultado(linha)
        return self._correr(linha)

    def escolher(self, tenant_id: str, image_job_id: str, *, versao: bool) -> Resultado:
        """O botao do dono: esta versao (`True`) ou o original (`False`).

        **Uma versao escolhida por original** (`image_jobs_escolhida_uq`):
        escolher outra desmarca primeiro a anterior. Se duas escolhas correrem
        ao mesmo tempo, a segunda perde no indice e sobe como erro — o dono
        carrega outra vez, e nao ficam duas marcadas.
        """
        linha = self._ler(tenant_id, image_job_id)
        if versao and linha.estado != estados.CONCLUIDO:
            raise estados.TransicaoRecusada(linha.estado, linha.estado)
        if linha.escolhida == versao:
            return Resultado(linha)
        if versao:
            anterior = self.repositorio.escolhida_de(tenant_id, linha.origem_ref)
            if anterior is not None and anterior.image_job_id != linha.image_job_id:
                self.repositorio.gravar(anterior, replace(anterior, escolhida=False))
        return Resultado(self.repositorio.gravar(linha, replace(linha, escolhida=versao)))

    def original(self, tenant_id: str, image_job_id: str) -> bytes:
        """Os bytes do original, tal como estao no STO. Recuperavel sempre."""
        linha = self._ler(tenant_id, image_job_id)
        return self._bytes(tenant_id, linha.origem_ref)

    def versao(self, tenant_id: str, image_job_id: str) -> bytes | None:
        linha = self._ler(tenant_id, image_job_id)
        return self._bytes(tenant_id, linha.versao_ref) if linha.versao_ref else None

    # ------------------------------------------------------------ o trabalhador

    def _correr(self, linha: Trabalho) -> Resultado:
        tenant = linha.tenant_id
        # 1. Fora de `prod`, so sinteticas.
        if self.ambiente != AMBIENTE_PROD and not linha.sintetica:
            return self._parar(linha, estados.BLOQUEADA_GATE, estados.MOTIVO_SO_SINTETICAS)

        # 2. O *gate*, fornecedor a fornecedor. Falha fechada: qualquer erro e
        # «nao autorizado».
        candidatos: list[ImageProvider] = []
        for fornecedor in self.fornecedores:
            try:
                self.destinos.autorizar(tenant, fornecedor.nome, FINALIDADE_IMAGEM)
            except Exception:  # noqa: BLE001
                continue
            candidatos.append(fornecedor)
        if not candidatos:
            return self._parar(linha, estados.BLOQUEADA_GATE, estados.MOTIVO_SEM_DESTINO)

        # 3. A carta de nao-treino, para imagens reais.
        if not linha.sintetica:
            candidatos = [f for f in candidatos if f.real_data_ok is True]
            if not candidatos:
                return self._parar(linha, estados.BLOQUEADA_GATE, estados.MOTIVO_SEM_CARTA)

        # 4. A minimizacao local, sobre o original relido do STO.
        try:
            original = self._bytes(tenant, linha.origem_ref)
        except ObjectoInexistenteError:
            # O original ja nao existe: pede-se outra foto. Uma falha
            # transitoria do STO **sobe**, e o trabalho fica onde estava para a
            # fila o tentar outra vez — nao e culpa da foto do dono.
            return self._parar(linha, estados.FALHADO, estados.MOTIVO_FORMATO)
        minimizada = minimizar(original, self.detector, self.redimensionador)
        if minimizada.imagem is None:
            return self._parar(linha, minimizada.estado or estados.BLOQUEADA_GATE,
                               minimizada.motivo or estados.MOTIVO_MINIMIZACAO)
        imagem = minimizada.imagem

        # 5. `a_processar`, contra a versao lida.
        try:
            linha = self.repositorio.gravar(
                linha, replace(linha, estado=estados.A_PROCESSAR, motivo=None, provider=candidatos[0].nome)
            )
        except ConflitoDeEstado:
            return Resultado(self._ler(tenant, linha.image_job_id))

        # 6. O fornecedor e, uma vez, a contingencia.
        custo = linha.custo_usd
        motivo = estados.MOTIVO_FORNECEDOR
        for fornecedor in candidatos[:2]:
            if not pode_sair(imagem):  # pragma: no cover — o passo 4 ja o garante
                return self._parar(linha, estados.BLOQUEADA_GATE, estados.MOTIVO_MINIMIZACAO, custo=custo)
            inicio = self.relogio_ms()
            try:
                melhoria = fornecedor.enhance(imagem, Opcoes(operacao=linha.operacao, timeout_s=TIMEOUT_S))
            except ErroDoFornecedor as erro:
                custo += _custo(getattr(erro, "custo_usd", 0))
                motivo = estados.MOTIVO_FORNECEDOR
                continue
            except Exception:  # noqa: BLE001 — `TimeoutError` e o resto: contingencia
                motivo = estados.MOTIVO_FORNECEDOR
                continue
            latencia = max(0, int(round(self.relogio_ms() - inicio)))
            custo += _custo(getattr(melhoria, "custo_usd", 0))
            if latencia > TIMEOUT_S * 1000:
                # **O *timeout* mede-se aqui, e nao so no adaptador** (achado
                # da revisao adversarial): uma resposta que chegou depois dos
                # 45 s conta como *timeout* — pagou-se, apaga-se la, e passa a
                # contingencia. Um adaptador que bloqueie para sempre continua
                # a ser defeito dele: o `Protocol` exige-lhe o `timeout_s`.
                motivo = estados.MOTIVO_FORNECEDOR
                self._apagar_no_fornecedor(fornecedor, melhoria)
                continue
            if not self._e_imagem(melhoria):
                motivo = estados.MOTIVO_RESULTADO_INVALIDO
                self._apagar_no_fornecedor(fornecedor, melhoria)
                continue
            return self._concluir(linha, fornecedor, melhoria, custo, latencia)
        return self._parar(linha, estados.FALHADO, motivo, custo=custo)

    def _concluir(
        self, linha: Trabalho, fornecedor: ImageProvider, melhoria: Melhoria, custo: Decimal, latencia: int
    ) -> Resultado:
        tenant = linha.tenant_id
        # 7. A versao para o STO, de imediato, numa chave nova: o original nao
        # se toca. **Nao se limpam os metadados da versao**: as marcas do
        # fornecedor (SynthID e afins) ficam, pela regra do bloco.
        chave = nova_chave(Ctx(tenant), CLASSE_STO, self.agora())
        self.storage.put(
            Ctx(tenant),
            chave,
            melhoria.imagem,
            ObjectMeta(
                content_type="image/png" if formato(melhoria.imagem) == "png" else "image/jpeg",
                classe=CLASSE_STO,
                retain_until=self.agora() + RETENCAO_DA_VERSAO,
            ),
        )
        self._apagar_no_fornecedor(fornecedor, melhoria)
        try:
            concluido = self.repositorio.gravar(
                linha,
                replace(
                    linha,
                    estado=estados.CONCLUIDO,
                    motivo=None,
                    provider=fornecedor.nome,
                    versao_ref=chave,
                    custo_usd=custo,
                    latencia_ms=latencia,
                ),
            )
        except ConflitoDeEstado:
            # Outro trabalhador escreveu primeiro: a versao desta tentativa nao
            # fica orfa no STO. O custo dela perde-se da linha, e e o limite
            # escrito no bloco — o `recuperar` com `PRESO_APOS` torna o caso raro.
            try:
                self.storage.delete(Ctx(tenant), ObjectRef(key=chave, tamanho=0))
            except Exception:  # noqa: BLE001 — a retencao apanha-a
                pass
            return Resultado(self._ler(tenant, linha.image_job_id))
        return Resultado(concluido)

    # ------------------------------------------------------------ apoio

    @staticmethod
    def _e_imagem(melhoria: Melhoria) -> bool:
        corpo = melhoria.imagem
        return isinstance(corpo, bytes) and 0 < len(corpo) <= TAMANHO_MAXIMO and formato(corpo) is not None

    @staticmethod
    def _apagar_no_fornecedor(fornecedor: ImageProvider, melhoria: Melhoria) -> None:
        if melhoria.ref_no_fornecedor is None:
            return
        try:
            fornecedor.apagar(melhoria.ref_no_fornecedor)
        except Exception:  # noqa: BLE001 — apagar la e o melhor esforco do criterio 10
            pass

    def _parar(self, linha: Trabalho, estado: str, motivo: str, *, custo: Decimal | None = None) -> Resultado:
        nova = replace(linha, estado=estado, motivo=motivo, custo_usd=linha.custo_usd if custo is None else custo)
        if (nova.estado, nova.motivo, nova.custo_usd) == (linha.estado, linha.motivo, linha.custo_usd):
            return Resultado(linha, motivo=motivo, avisar_dono=estado == estados.FALHADO)
        try:
            gravada = self.repositorio.gravar(linha, nova)
        except ConflitoDeEstado:
            return Resultado(self._ler(linha.tenant_id, linha.image_job_id))
        return Resultado(gravada, motivo=motivo, avisar_dono=estado == estados.FALHADO)

    def _ler(self, tenant_id: str, image_job_id: str) -> Trabalho:
        linha = self.repositorio.ler(tenant_id, image_job_id)
        if linha is None:
            raise TrabalhoInexistente("nao ha esse trabalho neste tenant")
        return linha

    def _bytes(self, tenant_id: str, chave: str) -> bytes:
        return b"".join(self.storage.get(Ctx(tenant_id), ObjectRef(key=chave, tamanho=0)))


class QuotaSobreTen:
    """O `PortaDeQuota` sobre o `consume_limit` do TEN (`platform.ten_consumir`).

    Uma recusa do TEN e um `Consumo(aceite=False)` com o motivo dele
    (`limite_excedido` ou `sem_entitlement`); um erro da base sobe, e o pedido
    nao nasce.
    """

    def __init__(self, bd: object) -> None:
        self._bd = bd

    def consumir(self, tenant_id: str, idempotency_key: str) -> Consumo:
        from ..ten.entitlements import consume_limit

        consumo = consume_limit(self._bd, tenant_id, CHAVE_DE_LIMITE, 1, idempotency_key, modulo=MODULO)  # type: ignore[arg-type]
        return Consumo(aceite=consumo.aceite, motivo=consumo.motivo)


__all__ = [
    "AMBIENTE_PROD",
    "AVISO_ESTRANGEIRO",
    "CHAVE_DE_LIMITE",
    "PRESO_APOS",
    "ChaveReutilizada",
    "GENERATIVAS",
    "MODULO",
    "Consumo",
    "OperacaoRecusada",
    "PortaDeDestinos",
    "PortaDeQuota",
    "QuotaSobreTen",
    "Resultado",
    "ServicoDeFoto",
    "TrabalhoInexistente",
]
