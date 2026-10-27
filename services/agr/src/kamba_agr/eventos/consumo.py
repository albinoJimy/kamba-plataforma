"""A entrega de um evento ao AGR, do corpo ao efeito (KAM-038).

E a decisao toda, e testa-se sem fila nenhuma — a casca do BullMQ fica em
TypeScript, pelo molde do `agr/shim.ts` (ADR-L004, Decisao 1). O que corre aqui
e, por ordem:

    ler o corpo da entrega          (quatro campos, forma fechada)
    ler o envelope                  -> invalido: DLQ sem envelope, e acabou
    confrontar os ponteiros da fila -> divergem: DLQ sem envelope, e acabou
    rotear por `(tipo, versao)`     -> sem rota: DLQ com alerta (criterio 3)
    validar o payload               -> fora do contrato: DLQ sem envelope
    filtrar por entitlement         -> nenhum: `sem_entitlement`, sem DLQ
    por consumidor:
      resolver o contacto           (fora da tranca)
      async with tranca(thread_id): (criterio 5)
        ler quem tem a palavra
        consumir(..., efeito)       (KAM-006: marca + efeito, uma transaccao)

## O efeito corre **dentro** da transaccao, e a razao e o criterio 2

O §6.3 escreve «aplicar efeitos na BD (mesma transaccao); COMMIT; efeitos
externos: tabela de accoes com `Idempotency-Key`». A notificacao e um efeito
externo — mas o Outbound e uma **fila** e nao uma chamada a Meta (quem fala com
a Meta e o trabalhador dele), pelo que enfileirar e curto e cabe na transaccao.
Poe-se la de proposito, e o que isso compra e simetrico:

* se a notificacao falhar, o `ROLLBACK` leva a marca com ela e a re-entrega
  volta a tentar — **nao ha marca sem efeito**. E «falhar» inclui o
  `sem_template`, que **levanta** (`NotificacaoNaoEntregue`): a primeira versao
  contava-o e seguia, e deixava uma linha em `events_consumed` sem mensagem
  nenhuma — no dia em que o KAM-024 aprovasse os *templates*, a re-entrega dava
  `duplicado` e o cliente nunca era avisado. Achado da revisao adversarial, e era
  o unico caminho que hoje corre;
* se o `COMMIT` falhar depois de a notificacao passar, a re-entrega repete a
  notificacao com a **mesma** chave `consumer:event_id:accao`, e a
  `UNIQUE (tenant_id, idempotency_key)` de `outbound_messages` nao enfileira
  nada — **nao ha efeito duplicado**.

A alternativa — efeito depois do `COMMIT` — deixava a primeira janela aberta: um
processo que morresse ali marcava o evento como consumido e ninguem era
notificado. E a janela que a `evt_acoes` do §6.3 existe para fechar, e ela
continua **sem escritor** (credor: KAM-006). Fechamo-la por desenho em vez de
por tabela.

## A prioridade dos eventos de pagamento

O criterio 8 e a regra 2 do §15.2. Ela nao se faz aqui: faz-se na **admissao**,
que e quem tem o tecto por *tenant* — um evento `payment.*` entra com a reserva
`AGR_RESERVA_DE_PAGAMENTO` **acima** do tecto, e nao dentro dele. O que este
modulo da e o `prioritario` do `Consumidor`, derivado do prefixo do tipo, e o
*lag* medido por consumidor para que o p99 do criterio seja mensuravel.

## O que este modulo nao faz

**Nao conta tentativas.** O `tentativas` vem do corpo, que o traz do
`attemptsMade` do *job*: com duas replicas do consumidor, um contador nosso
contava metade cada uma e o evento ia para a DLQ ao dobro das tentativas — ou
nunca ia. E a mesma razao que o `trabalhador_bullmq.ts` do KAM-006 escreve.

**Nao registra conteudo.** Nem `payload`, nem `event_id`, nem `tenant_id`: o que
vai a registo e o desfecho e o motivo, que sao constantes deste codigo e de
lista fechada.
"""

from __future__ import annotations

import asyncio
import datetime
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from kamba_core.eventos import (
    TENTATIVAS,
    Adiar,
    OpcoesDoConsumo,
    Resultado,
    atraso_da_tentativa_do_consumidor,
    consumir,
)
from kamba_core.eventos.contratos import (
    PayloadInvalidoError,
    TipoDesconhecidoError,
    VersaoDesconhecidaError,
    validar_payload,
)

from ..metricas import METRICA_EVT_CONSUMIDOS, METRICA_EVT_LAG, MetricasDoAgr
from . import handlers
from .desfechos import (
    DESFECHOS_DO_EVENTO,
    MOTIVO_ENVELOPE_INVALIDO,
    MOTIVO_SEM_TEMPLATE,
    MOTIVO_TIPO_DESCONHECIDO,
    MOTIVO_VERSAO_DESCONHECIDA,
)
from .dlq import TENTATIVAS_ESGOTADAS, FilaDeMortos
from .envelope import Envelope, EnvelopeInvalidoError, ler_envelope
from .notificacao import NotificacaoNaoEntregue, Notificador
from .subscricoes import Consumidor, por_tipo_e_versao, versoes_subscritas
from .turnos import LeitorDeConversas, thread_do_evento

#: Os quatro campos do corpo de `/internal/event` (dicionario §3.33). Lista
#: **fechada**: um campo a mais e um corpo que nao conhecemos, e recusa-se.
#:
#: **O `event_id` e o `tenant_id` sao ponteiros da fila e nao autoridade.** A
#: unica coisa que fazem e permitir abrir uma entrada na DLQ quando o envelope
#: **nao se le** — sem eles, esse evento desaparecia em silencio, porque as
#: colunas `event_id` e `tenant_id` da `events_dlq` sao `NOT NULL`. Quando o
#: envelope se le, confrontam-se com ele e uma divergencia recusa a entrega: o
#: contexto de *tenant* do consumo sai **sempre** do envelope validado
#: (criterio 4, ADR-015).
CAMPOS_DA_ENTREGA: Final = ("event_id", "tenant_id", "envelope", "tentativas")

#: Os desfechos que merecem linha de registo. O caminho feliz **nao** escreve
#: nada: uma linha por evento consumido enchia o registo com o que ja esta na
#: metrica, e a *allowlist* de `docs/tecnica/08` §7.3 nao tem onde levar o que
#: distinguiria uma linha da outra.
DESFECHOS_QUE_AVISAM: Final = ("para_dlq", "adiado", "sem_entitlement")


class EntregaInvalidaError(ValueError):
    """O corpo nao e uma entrega de evento. O chamador leva 400.

    O `codigo` tem forma de identificador e **nunca** leva o valor recusado,
    pela razao do `InvocacaoInvalidaError` do KAM-025: um corpo invalido pode
    ser qualquer coisa.
    """

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class Entrega:
    """O corpo lido: os dois ponteiros da fila, o envelope cru e a tentativa."""

    event_id: str
    tenant_id: str
    envelope: Any
    tentativas: int


def ler_entrega(corpo: Any) -> Entrega:
    """Le o corpo de `/internal/event`. Levanta `EntregaInvalidaError`.

    Recusa — e nao corrige — por esta ordem: o que nao e objecto, campos a mais,
    campos a menos, e campos com a forma errada. **Campos a mais recusam-se**
    pela razao do `ler_invocacao` do KAM-025: o contrato e fechado, e correr com
    metade de um contrato novo e pior do que recusar e deixar a fila repetir.

    O `tentativas` conta a partir de **1**: e o numero da tentativa em curso, e
    um zero aqui era uma entrega que nunca aconteceu.
    """
    if not isinstance(corpo, dict):
        raise EntregaInvalidaError("corpo_nao_e_objecto")
    chaves = set(corpo)
    if chaves - set(CAMPOS_DA_ENTREGA):
        raise EntregaInvalidaError("campo_desconhecido")
    if set(CAMPOS_DA_ENTREGA) - chaves:
        raise EntregaInvalidaError("campo_em_falta")
    for campo in ("event_id", "tenant_id"):
        valor = corpo[campo]
        if not isinstance(valor, str) or not valor:
            raise EntregaInvalidaError(f"campo_invalido_{campo}")
    tentativas = corpo["tentativas"]
    if isinstance(tentativas, bool) or not isinstance(tentativas, int) or tentativas < 1:
        raise EntregaInvalidaError("campo_invalido_tentativas")
    return Entrega(
        event_id=corpo["event_id"],
        tenant_id=corpo["tenant_id"],
        envelope=corpo["envelope"],
        tentativas=tentativas,
    )


@dataclass(frozen=True, slots=True)
class DesfechoDaEntrega:
    """O desfecho agregado e o de cada consumidor.

    `atraso_ms` vem preenchido so quando ha retentativa a pedir: e o `delay` que
    quem re-enfileira usa, e vem do `Adiar.atraso_ms` ou da escada do §6.4.
    Nunca se multiplica nada em quem chama — a licao do `× 1000` esquecido que o
    `consumo.py` do KAM-006 escreve.
    """

    desfecho: str
    por_consumidor: tuple[tuple[str, str], ...] = ()
    atraso_ms: int | None = None


class EntregaPorRepetir(RuntimeError):
    """A entrega nao concluiu e **tem** de voltar. O chamador devolve 503.

    Nao e um desfecho: um desfecho diz o que aconteceu ao evento, e aqui nada
    aconteceu. Leva o `atraso_ms` para que quem re-enfileira nao tenha de o
    calcular — e o `desfecho` que o painel conta (`adiado`) ja foi contado antes
    de ela subir.
    """

    def __init__(self, atraso_ms: int, codigo: str) -> None:
        super().__init__(codigo)
        self.atraso_ms = atraso_ms
        self.codigo = codigo


class _Entitlement(Protocol):
    """A fatia de `kamba_core.ten.Entitlement` de que o roteamento depende.

    A mesma do `AgentRegistry` do KAM-027, e de proposito: quem decide se um
    *tenant* tem uma vertical activa e a mesma leitura nos dois caminhos — o
    turno de conversa e o turno por evento —, e duas leituras diferentes davam
    uma vertical activa num e inactiva no outro.
    """

    permitido: bool


class LigacaoDoConsumo:
    """Adapta uma ligacao DB-API ao `ClienteSql` do KAM-006.

    O `consumir` manda `BEGIN`, `COMMIT` e `ROLLBACK` como instrucoes, porque do
    lado TypeScript o cliente e um `pg` em bruto. O `pg8000` em modo
    transaccional **abre a transaccao sozinho** na primeira instrucao, e um
    `BEGIN` explicito dentro de uma transaccao aberta e um aviso do servidor e
    mais nada — o `COMMIT` seguinte fechava a transaccao de fora. Por isso as
    tres traduzem-se na API do condutor em vez de passarem.

    **E uma palavra desconhecida de controlo de transaccao levanta**, em vez de
    passar: se o KAM-006 vier a mandar um `SAVEPOINT` ou um `START TRANSACTION`,
    um adaptador que o deixasse passar punha a marca e o efeito em transaccoes
    diferentes **sem dar erro** — os dois modos de falha que o
    `consumo.py` daquele ticket nomeia por extenso.
    """

    #: As tres que se traduzem.
    TRADUZIDAS: Final = ("BEGIN", "COMMIT", "ROLLBACK")
    #: As que, se aparecerem, significam que o contrato mudou.
    PROIBIDAS: Final = ("START", "END", "SAVEPOINT", "RELEASE", "ABORT")

    __slots__ = ("_ligacao",)

    def __init__(self, ligacao: Any) -> None:
        self._ligacao = ligacao

    def executar(self, sql: str, parametros: tuple[object, ...] = ()) -> Resultado:
        primeira = sql.strip().split(maxsplit=1)[0].upper() if sql.strip() else ""
        if primeira in self.TRADUZIDAS:
            if primeira == "COMMIT":
                self._ligacao.commit()
            elif primeira == "ROLLBACK":
                self._ligacao.rollback()
            # O `BEGIN` nao faz nada: o condutor abre a transaccao na instrucao
            # seguinte, que e precisamente o `set_config` do contexto.
            return Resultado()
        if primeira in self.PROIBIDAS:
            raise RuntimeError(
                f"instrucao de transaccao nao traduzida: {primeira}. Ver a docstring "
                "de `LigacaoDoConsumo`: deixa-la passar punha a marca e o efeito em "
                "transaccoes diferentes sem dar erro"
            )
        cursor = self._ligacao.cursor()
        try:
            cursor.execute(sql, parametros)
            if cursor.description is None:
                return Resultado(contagem=cursor.rowcount)
            colunas = [coluna[0] for coluna in cursor.description]
            linhas = [
                {
                    (nome.decode() if isinstance(nome, bytes) else str(nome)): valor
                    for nome, valor in zip(colunas, linha, strict=True)
                }
                for linha in cursor.fetchall()
            ]
            return Resultado(linhas=linhas, contagem=cursor.rowcount)
        finally:
            cursor.close()


def lag_ms(ocorrido_em: str, agora: float) -> int | None:
    """O *lag* em milissegundos, do `ocorrido_em` ate agora. `None` se nao se le.

    Mede-se do **`ocorrido_em`** e nao do `registado_em` (dicionario §3.33): o
    primeiro e quando o facto aconteceu, que e o que o cliente espera, e o
    segundo esconde o atraso entre o facto e a transaccao que o gravou.

    **Nunca devolve negativo.** O `ocorrido_em` e o relogio do **produtor** (§4)
    e pode estar a frente do nosso; um *lag* negativo num painel le-se como um
    defeito do painel. Corta-se a zero, e um relogio a frente aparece como zero
    e nao como um numero impossivel.

    `None` quando o instante nao se le: o campo e texto nao vazio pelo envelope,
    mas nada no envelope promete ISO-8601 — e uma medida que nao se mede nao se
    inventa.
    """
    try:
        instante = datetime.datetime.fromisoformat(ocorrido_em)
    except ValueError:
        return None
    if instante.tzinfo is None:
        # Sem fuso nao se sabe de que instante se fala, e assumir UTC errava por
        # uma hora em Luanda (UTC+1) — a mesma razao pela qual o §2 do
        # dicionario exige `timestamptz`.
        return None
    return max(0, int((agora - instante.timestamp()) * 1_000))


class ConsumidorDeEventos:
    """Os consumidores registados, e a entrega de um evento a cada um.

    As portas sao injectadas pela razao de sempre: assim a decisao testa-se
    inteira sem PostgreSQL, sem Redis e sem Outbound, e o que a *suite* do
    *gate* 8 prova e o que so a base pode provar.
    """

    def __init__(
        self,
        *,
        tabela: tuple[Consumidor, ...],
        trancas: Any,
        conversas: LeitorDeConversas,
        abrir_ligacao: Callable[[], Any],
        fila_de_mortos: FilaDeMortos,
        notificador: Notificador,
        ler_entitlement: Callable[[str, str], _Entitlement],
        contactos: handlers.PortaDeContacto | None = None,
        metricas: MetricasDoAgr | None = None,
        aviso: Callable[[str, str], None] | None = None,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self._tabela = tabela
        self._por_par: Mapping[tuple[str, int], tuple[Consumidor, ...]] = {}
        self._versoes: Mapping[str, frozenset[int]] = {}
        self._trancas = trancas
        self._conversas = conversas
        self._abrir = abrir_ligacao
        self._dlq = fila_de_mortos
        self._notificador = notificador
        self._ler_entitlement = ler_entitlement
        self._contactos = (
            handlers.ContactoPorLigar() if contactos is None else contactos
        )
        self._metricas = metricas
        self._aviso = aviso
        self._agora = relogio
        if not tabela:
            # **Um consumidor sem consumidores nao e um consumidor.** Sem esta
            # guarda, cada entrega devolvia 200 «tratado» sem escrever linha
            # nenhuma: o evento desaparecia em silencio, que e exactamente o que
            # a DLQ existe para evitar. Quem monta o processo so liga a rota se
            # houver subscricoes (`__main__.py`); sem elas, `/internal/event`
            # responde 503 e o evento fica na fila. Achado da revisao
            # adversarial.
            raise ValueError(
                "tabela de consumidores vazia: uma entrega nao teria onde ser "
                "registada, e 200 sem linha nenhuma perde o evento em silencio"
            )
        self._indexar()

    @property
    def conversas(self) -> LeitorDeConversas:
        """O leitor de conversas, que e quem tem a **unica** tomada que fica.

        Em propriedade e nao so em campo privado porque ha quem precise de a
        fechar: o `ao_encerrar` do processo. As outras duas ligacoes que este
        consumidor usa — a do consumo e a da DLQ — abrem e fecham por entrega.
        """
        return self._conversas

    def _indexar(self) -> None:
        self._por_par = por_tipo_e_versao(self._tabela)
        self._versoes = versoes_subscritas(self._tabela)

    def e_prioritario(self, tipo: str) -> bool:
        """O tipo tem prioridade sobre mensagens de conversa? Criterio 8.

        Pergunta-se **antes** de admitir: quem decide a vaga e a `Admissao`, e
        ela precisa de saber se pode usar a reserva. Deriva-se da tabela e nao
        do prefixo outra vez, para que a resposta seja a do consumidor
        registado e nao uma segunda regra a dizer o mesmo.
        """
        return any(
            consumidor.prioritario
            for consumidor in self._tabela
            if consumidor.tipo == tipo
        )

    async def entregar(self, corpo: Any) -> DesfechoDaEntrega:
        """Entrega um evento aos consumidores que o subscrevem.

        Levanta `EntregaInvalidaError` (400) e `EntregaPorRepetir` (503); todos
        os outros caminhos devolvem desfecho, porque um evento que foi para a
        DLQ **foi tratado** e a fila nao o deve repetir.
        """
        entrega = ler_entrega(corpo)
        envelope = await self._envelope_ou_dlq(entrega)
        if envelope is None:
            return self._contado("para_dlq")

        candidatos = self._por_par.get((envelope.tipo, envelope.versao))
        if candidatos is None:
            return await self._sem_rota(entrega, envelope)

        try:
            validar_payload(envelope.tipo, envelope.versao, envelope.payload)
        except (TipoDesconhecidoError, VersaoDesconhecidaError, PayloadInvalidoError):
            # Chegar aqui com tipo ou versao desconhecidos e impossivel — o
            # arranque confronta as subscricoes com o mesmo catalogo —, pelo
            # que o que resta e o payload fora do contrato. Trata-se como
            # envelope invalido e **nao se guarda o que foi recusado**: um
            # payload com campos a mais pode trazer qualquer coisa.
            await self._dlq.abrir_sem_envelope(
                consumidor=candidatos[0].nome,
                event_id=entrega.event_id,
                tenant_id=entrega.tenant_id,
                motivo=MOTIVO_ENVELOPE_INVALIDO,
                tentativas=entrega.tentativas,
            )
            return self._contado("para_dlq")

        # **A leitura vai a um executor**, como **todas** as idas a base deste
        # modulo — a leitura da conversa, a transaccao do consumo e a entrada na
        # DLQ: o `pg8000` e sincrono, e chama-lo na *event loop* serializava o
        # AGR inteiro na latencia da base (que tambem serve o `/internal/turn`).
        # A razao esta escrita no `conversa.py` do KAM-025, e as tres primeiras
        # versoes deste modulo abriam tres das quatro tomadas na *loop* — medido
        # pela revisao adversarial.
        activos = await asyncio.to_thread(self._activos, envelope, candidatos)
        if not activos:
            # **Marca-se, e so depois se devolve o desfecho.** Devolver 200 sem
            # linha em `events_consumed` nem em `events_dlq` punha o evento no
            # ciclo que o §6.5 descreve: o reconciliador varre o que foi
            # publicado ha mais de dez minutos **sem registo de consumo nem
            # DLQ** e re-enfileira-o de cinco em cinco minutos durante as 24 h
            # da janela. Para um *tenant* sem entitlement activo isso era um
            # ciclo silencioso por **cada** evento dele. Achado da revisao
            # adversarial, e e a mesma lacuna que o `abrir_sem_envelope` nomeia.
            #
            # A marca e por **candidato**, com efeito vazio: a `events_consumed`
            # e a janela de deduplicacao, e «este consumidor viu este evento e
            # nao tinha nada a fazer» e exactamente o que ela responde.
            for candidato in candidatos:
                await self._marcar_sem_efeito(candidato, envelope, entrega)
            return self._contado("sem_entitlement")

        desfechos: list[tuple[str, str]] = []
        for consumidor in activos:
            desfechos.append(
                (consumidor.nome, await self._um(consumidor, envelope, entrega))
            )
        return DesfechoDaEntrega(
            desfecho=_agregar(tuple(d for _, d in desfechos)),
            por_consumidor=tuple(desfechos),
        )

    async def _marcar_sem_efeito(
        self, consumidor: Consumidor, envelope: Envelope, entrega: Entrega
    ) -> None:
        """Consome o evento com efeito vazio, para o reconciliador parar.

        **Nao conta desfecho nenhum**, e isso e deliberado: quem conta e quem
        chama, uma vez por entrega. Um contador por candidato fazia uma entrega
        a dois candidatos contar dois `sem_entitlement` e o painel ler o dobro
        das entregas que houve.

        Uma falha aqui **nao** se engole: sobe, a entrega e tentada outra vez, e
        e isso que se quer — o que esta a falhar e a escrita da marca, e sem ela
        o ciclo do reconciliador volta.
        """
        tarefa = asyncio.ensure_future(
            asyncio.to_thread(
                self._correr_consumo, consumidor, envelope, lambda _bd, _env: None
            )
        )
        try:
            await asyncio.shield(tarefa)
        except asyncio.CancelledError:
            await asyncio.wait([tarefa])
            raise

    def _activos(
        self, envelope: Envelope, candidatos: tuple[Consumidor, ...]
    ) -> tuple[Consumidor, ...]:
        """Os consumidores cuja vertical este *tenant* tem activa.

        Os dois `registry/*.yaml` subscrevem os mesmos dois eventos de
        pagamento, e sem esta leitura um pagamento de um *tenant* que so tem o
        Vendedor era consumido tambem pelo consumidor de Servicos.

        **Isto por si nao faz «1 mensagem», e a primeira versao afirmava que
        fazia.** Um *tenant* com as **duas** verticais activas — que e
        precisamente o do *gate* da Fase 0 (ADR-012, KAM-108) — tem dois
        consumidores, e o que impede os dois de mandarem a **mesma** mensagem e
        o *handler* ser por `(vertical, tipo)` e nao por tipo: o
        `payment.confirmed` fala com o cliente pelo Vendedor, e nos Servicos a
        accao e outra — «confirma uma marcacao com sinal» —, que o KAM-047 ainda
        nao escreveu e que o desfecho `sem_accao` nomeia. Achado da revisao
        adversarial.
        """
        return tuple(
            consumidor
            for consumidor in candidatos
            if self._ler_entitlement(envelope.tenant_id, consumidor.modulo).permitido
        )

    # ------------------------------------------------------------ o envelope

    async def _envelope_ou_dlq(self, entrega: Entrega) -> Envelope | None:
        """O envelope validado, ou `None` depois de abrir entrada na DLQ."""
        try:
            envelope = ler_envelope(entrega.envelope)
        except EnvelopeInvalidoError:
            await self._dlq_sem_envelope(entrega)
            return None
        if envelope.id != entrega.event_id or envelope.tenant_id != entrega.tenant_id:
            # **Os ponteiros da fila tem de bater com o envelope.** Nao e zelo:
            # sem esta verificacao, uma entrega com o `tenant_id` de B e um
            # envelope de A escrevia a linha da DLQ no *tenant* B — isto e,
            # punha o envelope de A dentro do *tenant* de B, numa coluna que
            # uma auditoria le e que fica trinta dias depois da resolucao. Por
            # isso o caminho e o `_dlq_sem_envelope`, que **nao guarda** o que
            # recusou.
            await self._dlq_sem_envelope(entrega)
            return None
        return envelope

    # **O `ForaDeOrdem` do KAM-006 nao se apanha aqui, e nao e esquecimento.**
    # Ele e levantado dentro da pre-condicao de estado, que este consumidor nao
    # corre (`aplica_transicao=False`): apanha-lo era escrever um `except` para
    # um caminho que nenhuma execucao alcanca, e declarar o motivo dele era uma
    # etiqueta sempre a zero. Ver `desfechos.py`. Se um dia ele chegar, cai no
    # `except Exception` e recua pela escada — o que e seguro, porque o efeito
    # nao chegou a correr.

    async def _dlq_sem_envelope(self, entrega: Entrega) -> None:
        #: O consumidor nao se sabe — nao se leu o tipo —, e a coluna e
        #: `NOT NULL`. Usa-se o nome do primeiro consumidor registado por ordem,
        #: e isso tem de ser dito: a entrada **nao** atribui culpa a essa
        #: vertical, atribui-lhe a varredura. Com a tabela vazia nao ha nome
        #: nenhum, e nesse caso nao ha consumidor para quem a DLQ sirva.
        if not self._tabela:
            return
        await self._dlq.abrir_sem_envelope(
            consumidor=self._tabela[0].nome,
            event_id=entrega.event_id,
            tenant_id=entrega.tenant_id,
            motivo=MOTIVO_ENVELOPE_INVALIDO,
            tentativas=entrega.tentativas,
        )

    async def _sem_rota(
        self, entrega: Entrega, envelope: Envelope
    ) -> DesfechoDaEntrega:
        """Criterio 3: tipo ou versao sem rota **nao** passa em silencio.

        Dois motivos e nao um, porque mandam olhar para sitios diferentes: o
        `tipo_desconhecido` e configuracao de entrega (`evt_subscricoes`,
        KAM-005) e o `versao_desconhecida` e ordem de *deploy* (§6.6,
        «consumidores antes de produtores»).

        **Vai para a DLQ com o envelope inteiro**, ao contrario do envelope
        invalido: aqui o envelope **leu-se**, o `tipo` casa a gramatica e a
        entrada e reprocessavel no dia em que o consumidor existir — que e
        precisamente o que o §6.6 quer («sem conversor, o evento fica bloqueado
        com alerta»).
        """
        motivo = (
            MOTIVO_VERSAO_DESCONHECIDA
            if envelope.tipo in self._versoes
            else MOTIVO_TIPO_DESCONHECIDO
        )
        if self._tabela:
            await self._dlq.abrir(
                consumidor=self._tabela[0].nome,
                envelope=envelope,
                motivo=motivo,
                tentativas=entrega.tentativas,
            )
        return self._contado("para_dlq")

    # -------------------------------------------------------- um consumidor

    async def _um(
        self, consumidor: Consumidor, envelope: Envelope, entrega: Entrega
    ) -> str:
        """Consome o evento para **um** consumidor, sob a tranca se houver conversa."""
        if not handlers.fala_com_o_cliente(consumidor.vertical, envelope.tipo):
            # Aviso ao dono, ou accao por ligar: nao ha conversa, nao ha
            # `thread_id`, e nao ha nada para serializar. Ver o `turnos.py`.
            return await self._consumir(consumidor, envelope, entrega, conversa=None)

        contact_id = handlers.contacto_do_evento(envelope, self._contactos)
        thread_id = thread_do_evento(envelope.tenant_id, contact_id)
        async with self._trancas.tomar(thread_id):
            conversa = await self._conversas.ler(envelope.tenant_id, contact_id)
            return await self._consumir(
                consumidor, envelope, entrega, conversa=conversa, contact_id=contact_id
            )

    async def _consumir(
        self,
        consumidor: Consumidor,
        envelope: Envelope,
        entrega: Entrega,
        *,
        conversa,
        contact_id: str | None = None,
    ) -> str:
        """A transaccao do KAM-006, com o efeito deste ticket dentro dela."""
        do_humano = conversa is not None and conversa.do_humano
        credor = handlers.accao_por_ligar(consumidor.vertical, envelope.tipo)
        efeito = self._efeito(
            consumidor,
            envelope,
            conversa=conversa,
            contact_id=contact_id,
            do_humano=do_humano,
        )
        tarefa = asyncio.ensure_future(
            asyncio.to_thread(self._correr_consumo, consumidor, envelope, efeito)
        )
        try:
            resultado = await asyncio.shield(tarefa)
        except asyncio.CancelledError:
            # **O `to_thread` nao cancela a *thread***: sem este `wait`, o
            # `await` levantava, o `finally` fechava a tomada, e a *thread*
            # ficava a meio da transaccao do `consumir` sobre uma tomada
            # fechada — com a marca inserida e o efeito possivelmente ja
            # enfileirado. E o tratamento do `checkpointer.py` do KAM-026.
            await asyncio.wait([tarefa])
            raise
        except Adiar as adiamento:
            return await self._adiar(consumidor, envelope, entrega, adiamento.atraso_ms)
        except NotificacaoNaoEntregue:
            # **Nao e uma falha e nao se repete.** A janela esta fechada e nao ha
            # *template* aprovado: a mensagem nao pode sair hoje nem daqui a
            # treze minutos. Vai para a DLQ, onde fica visivel e
            # **reprocessavel** no dia em que o KAM-024 a aprovar — e o `efeito`
            # levantou **dentro** da transaccao, pelo que o `ROLLBACK` levou a
            # marca com ele e nao ha marca sem efeito.
            await self._dlq.abrir(
                consumidor=consumidor.nome,
                envelope=envelope,
                motivo=MOTIVO_SEM_TEMPLATE,
                tentativas=entrega.tentativas,
            )
            return self._contado_so("para_dlq")
        except Exception:
            return await self._falhou(consumidor, envelope, entrega)

        if resultado.desfecho == "aplicado":
            self._medir_lag(consumidor, envelope)
            # O `aplicado` do KAM-006 diz que a marca e o efeito passaram; qual
            # foi o efeito e deste ticket, e um evento que acordou uma conversa
            # com um humano conta como `entregue_ao_hnd` para que o painel
            # distinga «o cliente foi avisado» de «o agente foi avisado». Um
            # `duplicado` fica `duplicado` nos dois casos: nao houve efeito.
            if do_humano:
                return self._contado_so("entregue_ao_hnd")
            if credor is not None:
                return self._contado_so("sem_accao")
        return self._contado_so(resultado.desfecho)

    def _correr_consumo(self, consumidor: Consumidor, envelope: Envelope, efeito):
        """A transaccao, na *thread*: abre a tomada, consome, e fecha-a sempre.

        **A tomada abre aqui e nao na *event loop***, e a primeira versao
        abria-a lá: um `connect` do `pg8000` e uma ida a rede com apresentacao e
        autenticacao. Medido pela revisao adversarial, e contra o que a
        *docstring* deste modulo afirmava.
        """
        ligacao = self._abrir()
        try:
            return consumir(
                OpcoesDoConsumo(
                    bd=LigacaoDoConsumo(ligacao),
                    consumer=consumidor.nome,
                    envelope=envelope.como_mapa(),
                    exige_ordem=consumidor.exige_ordem,
                    # **O AGR nao aplica transicao nenhuma** (dicionario §3.33):
                    # quem transita a encomenda e o COM (`03` §6) e quem decide
                    # o pagamento e o PAY (ADR-013). Sem isto, o consumo de
                    # `payment.confirmed` levantava `MaquinaEmFalta` — ou, com
                    # uma maquina sobre uma tabela de encomendas que o KAM-041
                    # ainda nao escreveu, adiava seis vezes e mandava para a DLQ
                    # **todos** os pagamentos confirmados.
                    aplica_transicao=False,
                ),
                efeito,
            )
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — o desfecho e o que importa
                pass

    def _efeito(
        self,
        consumidor: Consumidor,
        envelope: Envelope,
        *,
        conversa,
        contact_id: str | None,
        do_humano: bool,
    ):
        """O efeito que corre **dentro** da transaccao do consumo.

        Ignora o cliente SQL que recebe, e isso e deliberado: o efeito deste
        ticket nao escreve na base — escreve numa fila, pelo Outbound ou pelo
        HND. O argumento fica na assinatura porque e o contrato do `Efeito` do
        KAM-006, e mudar o contrato para um consumidor era pedir ao nucleo que
        se adaptasse a um chamador.
        """

        def aplicar(_bd, _envelope) -> None:
            # **Nao ha aqui guarda para a accao por ligar, e isso e uma
            # correccao.** A primeira versao tinha uma — `if credor is not
            # None: return` —, e a prova por mutacao mediu que ela **nao mudava
            # nada**: o `accoes_de` ja devolve accoes vazias para um par de
            # `ACCOES_POR_LIGAR`, porque o `fala_com_o_cliente` responde `False`
            # e o par nao esta em `AO_DONO`. A mutacao que a apagava sobreviveu,
            # que e como se descobre codigo morto. O que decide o desfecho
            # `sem_accao` e o `credor` do `_consumir`, e esse tem mutacao que o
            # mata.
            if do_humano:
                # Criterio 5: a conversa esta com um humano. **Notifica-se o
                # HND** e nao o cliente — e o evento consome-se, porque repetir
                # seis vezes para dizer sempre o mesmo nao e tentar outra vez.
                self._notificador.ao_dono(
                    consumidor=consumidor.nome,
                    event_id=envelope.id,
                    tenant_id=envelope.tenant_id,
                    motivo=envelope.tipo,
                )
                return
            accoes = handlers.accoes_de(
                envelope,
                vertical=consumidor.vertical,
                contact_id=contact_id,
                conversation_id=None if conversa is None else conversa.id,
            )
            if accoes.cliente is not None:
                self._notificador.ao_cliente(
                    consumidor=consumidor.nome,
                    event_id=envelope.id,
                    tenant_id=envelope.tenant_id,
                    notificacao=accoes.cliente,
                )
            if accoes.dono_por is not None:
                self._notificador.ao_dono(
                    consumidor=consumidor.nome,
                    event_id=envelope.id,
                    tenant_id=envelope.tenant_id,
                    motivo=accoes.dono_por,
                )

        return aplicar

    # ------------------------------------------------------- retentativa e DLQ

    async def _adiar(
        self,
        consumidor: Consumidor,
        envelope: Envelope,
        entrega: Entrega,
        atraso_ms: int,
    ) -> str:
        if entrega.tentativas >= TENTATIVAS:
            await self._dlq.abrir(
                consumidor=consumidor.nome,
                envelope=envelope,
                motivo=TENTATIVAS_ESGOTADAS,
                tentativas=entrega.tentativas,
            )
            return self._contado_so("para_dlq")
        self._contado_so("adiado")
        raise EntregaPorRepetir(atraso_ms, "adiado")

    async def _falhou(
        self, consumidor: Consumidor, envelope: Envelope, entrega: Entrega
    ) -> str:
        """Qualquer outro erro: recua pela escada e, esgotada, abre a DLQ.

        **O atraso vem da escada do §6.4 e nao do erro.** Quem o calcula e o
        `atraso_da_tentativa_do_consumidor` do KAM-006, com a tentativa em curso;
        escrever um numero aqui era uma segunda escada a divergir da primeira.
        """
        if entrega.tentativas >= TENTATIVAS:
            await self._dlq.abrir(
                consumidor=consumidor.nome,
                envelope=envelope,
                motivo=TENTATIVAS_ESGOTADAS,
                tentativas=entrega.tentativas,
            )
            return self._contado_so("para_dlq")
        self._contado_so("adiado")
        raise EntregaPorRepetir(
            atraso_da_tentativa_do_consumidor(entrega.tentativas), "falhou"
        )

    # ------------------------------------------------------------- metricas

    def _medir_lag(self, consumidor: Consumidor, envelope: Envelope) -> None:
        """O *lag* do evento que **acabou de ser aplicado**, por consumidor.

        So no `aplicado`: o *lag* de um duplicado mede o tempo ate uma entrega
        que nao fez nada, e um painel que os misturasse via o p99 subir sem que
        cliente nenhum tivesse esperado mais.
        """
        medida = lag_ms(envelope.ocorrido_em, self._agora())
        if medida is not None and self._metricas is not None:
            self._metricas.medir(METRICA_EVT_LAG, medida, consumidor.nome)

    def _contado(self, desfecho: str) -> DesfechoDaEntrega:
        """Conta e devolve o desfecho agregado de uma entrega sem consumidores."""
        self._contado_so(desfecho)
        return DesfechoDaEntrega(desfecho=desfecho)

    def _contado_so(self, desfecho: str) -> str:
        if desfecho not in DESFECHOS_DO_EVENTO:
            raise ValueError(f"desfecho fora da lista fechada: {desfecho!r}")
        if self._metricas is not None:
            self._metricas.contar(METRICA_EVT_CONSUMIDOS, desfecho)
        if self._aviso is not None and desfecho in DESFECHOS_QUE_AVISAM:
            self._aviso("evt_entrega", desfecho)
        return desfecho


#: A ordem de gravidade de um desfecho, para agregar varios consumidores.
#: O agregado e o **pior**, e nao o primeiro: uma entrega em que um consumidor
#: aplicou e outro foi para a DLQ nao e uma entrega aplicada.
_GRAVIDADE: Final = (
    "para_dlq",
    "adiado",
    "sem_entitlement",
    # **O `sem_accao` e mais grave do que o `entregue_ao_hnd`**, e a ordem nao e
    # arbitraria: o segundo quer dizer «avisou-se quem tinha de ser avisado» e o
    # primeiro quer dizer «ninguem foi avisado, e ha um ticket a deve-lo». Numa
    # entrega as duas verticais, o agregado tem de ser o que manda olhar.
    "sem_accao",
    "entregue_ao_hnd",
    "aplicado",
    "duplicado",
)


def _agregar(desfechos: tuple[str, ...]) -> str:
    """O pior desfecho de um conjunto. Com um so, e ele."""
    for desfecho in _GRAVIDADE:
        if desfecho in desfechos:
            return desfecho
    raise ValueError(f"desfechos desconhecidos: {desfechos!r}")
