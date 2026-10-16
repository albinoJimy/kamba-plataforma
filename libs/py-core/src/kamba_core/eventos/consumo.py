"""O consumidor idempotente (KAM-006, `docs/tecnica/06` §6.3).

Espelho de `packages/core-ts/src/eventos/consumo.ts`, com o SQL de
`packages/core-ts/src/eventos/consultas_consumo.ts`. Os dois lados existem
porque o Piloto tem consumidores nas duas linguagens; duas implementacoes do
mesmo contrato so se mantem honestas se houver uma maquina a confronta-las, e a
maquina e o `TestParidadeDoTypeScript` de `tests/test_eventos_consumo.py`.

## O que faz, e porque e esta a ordem

    BEGIN
      n = INSERT events_consumed ON CONFLICT (consumer, event_id) DO NOTHING
      se n == 0: COMMIT; duplicado — e nao se faz mais nada
      se exige_ordem: ler o ultimo seq do agregado
      se o tipo causa transicao: ler o estado do agregado
                      -> Adiar (pre-condicao por chegar)
                      -> ForaDeOrdem (seq atrasado E transicao invalida)
      efeito(bd)      <- na MESMA transaccao
    COMMIT

A pre-condicao de estado corre **fora** do `exige_ordem`, e isto e uma
correccao: com ela dentro, uma subscricao com `exige_ordem = False` sobre um
tipo que causa transicao aplicava-a **sem verificacao nenhuma**, e a restricao
do DDL so obriga `exige_ordem` em `payment.%`. A **ordem** e outra coisa, e
continua dependente de `exige_ordem`: sem o ultimo `seq` nao se sabe se o evento
vem atrasado, e sem isso a saida e sempre `Adiar` — nunca `fora_de_ordem`.

A marca e o efeito partilham a transaccao, e e isso que o torna
exactamente-uma-vez. Em duas transaccoes haveria dois modos de falha e os dois
acontecem: efeito sem marca (repete-se a proxima entrega) ou marca sem efeito
(perde-se para sempre). A entrega da fila continua *at-least-once* — o
publicador do KAM-005 republica tudo o que nao tenha `publicado_at` —, e e esse
o pressuposto.

## Adiar nao e falhar, e falhar nao e descartar

Tres saidas, e a diferenca entre elas e o que decide se um pagamento se perde:

- **`Adiar(s)`** — a pre-condicao ainda nao se verifica (`payment.confirmed`
  antes de a encomenda estar em `aguarda_pagamento`). Tenta-se outra vez. Uma
  pre-condicao que **nunca** se verifica esgota as tentativas e vai para a DLQ;
  nunca se aplica a transicao (§6.3).
- **`ForaDeOrdem`** — o evento vem atrasado **e** a transicao nao e valida na
  maquina de estados. Nao ha tentativa que resolva: vai directo para a DLQ, com
  `erro = 'fora_de_ordem'`.
- **qualquer outro erro** — recua pela escada e, esgotadas as seis tentativas,
  DLQ.

## A escada e a do §6.4 e nao a do publicador

1 s, 5 s, 30 s, 2 min, 10 min, sobre 1 + 5 tentativas. O publicador tem uma
escada **diferente** (tecto de 30 s) de proposito: ali o que recua e a
republicacao de um evento que ninguem consumiu, e meia hora de espera nao ajuda;
aqui o que recua e um efeito de negocio cuja pre-condicao pode levar minutos a
chegar.

## O que este modulo nao faz

- **Nao importa `psycopg`.** O cliente e injectado (`ClienteSql`), e e por isso
  que a transaccao se testa inteira sem PostgreSQL. Quem liga a base e quem
  chama; quem da contexto de tenant e o `kamba_core.tenant_guard`.
- **Nao trata de retentativas nem de DLQ.** Isso e politica, e vive no
  trabalhador. Aqui esta a transaccao e nada mais.
- **Nao registra nada.** Nem `tenant_id`, nem `event_id`, nem o erro: o
  envelope e o payload passam por aqui, e a allowlist do `kamba_core.logger`
  nao conhece nada disto. Quem decide registar e quem apanha a excepcao, com os
  campos que a politica permite.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .estados import ESTADO_PRETENDIDO, MaquinaDeEstados, pode_transitar

# ---------------------------------------------------------------------- o SQL
#
# O mesmo SQL do `consultas_consumo.ts`, com os mesmos parametros e pela mesma
# ordem. A unica diferenca e o marcador — `%s` em vez de `$1` —, porque e o que
# o `psycopg` le (o `tenant_guard` escreve-o igual); a posicao e o significado
# de cada parametro nao mudam, e o teste de paridade confirma-o reescrevendo os
# `$n` do TypeScript e comparando o texto.

#: A linha de deduplicacao. **E esta consulta que torna a entrega
#: *at-least-once* num efeito exactamente-uma-vez.**
#:
#: `ON CONFLICT (consumer, event_id) DO NOTHING` devolve `contagem = 0` quando a
#: linha ja existe, e e esse zero que diz «duplicado». Corre na **mesma
#: transaccao** que o efeito: se o efeito falhar, a linha desaparece com ele e a
#: re-entrega volta a tentar.
#:
#: **O alvo do conflito esta nomeado**, e nao e detalhe: com `DO NOTHING` sem
#: alvo, um conflito em *qualquer* indice unico que a tabela venha a ter devolve
#: zero linhas, e esse zero lia-se «duplicado» — um efeito saltado em silencio.
SQL_MARCAR_CONSUMIDO = """
  INSERT INTO platform.events_consumed
    (consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq)
  VALUES (%s, %s, %s, %s, %s, %s)
  ON CONFLICT (consumer, event_id) DO NOTHING
"""

#: O maior `seq` ja consumido deste agregado, **excluindo** o evento em mao.
#:
#: O `event_id <> %s` e do §6.3 e nao e decoracao: a linha do evento em curso ja
#: foi escrita acima, na mesma transaccao, e sem a exclusao o maximo incluia-a —
#: um evento nunca estaria «atrasado» em relacao a si mesmo e a verificacao de
#: ordem nao fazia nada.
SQL_ULTIMO_SEQ = """
  SELECT max(agregado_seq) AS ultimo
    FROM platform.events_consumed
   WHERE consumer = %s AND agregado_tipo = %s AND agregado_id = %s AND event_id <> %s
"""

# ------------------------------------------------------------------ a escada

#: A escada de recuo do consumidor (§6.4), em milissegundos.
#:
#: Cinco atrasos para cinco retentativas; com a primeira tentativa sao as **6**
#: do criterio 2.
ESCADA_DO_CONSUMIDOR: tuple[int, ...] = (1_000, 5_000, 30_000, 120_000, 600_000)

#: 1 + 5. O numero do criterio 2, derivado da escada e nao escrito ao lado.
TENTATIVAS = 1 + len(ESCADA_DO_CONSUMIDOR)

#: Quantos **segundos** adiar quando a pre-condicao ainda nao se verifica
#: (§6.3). Em segundos, e nao em milissegundos como a escada: e o numero que o
#: pseudocodigo do documento escreve (`throw Adiar(5 s)`) e que vai para o
#: `delay` de quem re-enfileira.
ADIAMENTO_POR_OMISSAO = 5

#: Desfecho de um consumo. Lista fechada: e sufixo de metrica. Um `adiado`
#: **nao** esta aqui — adiar nao e um desfecho do consumo, e uma retentativa.
DESFECHOS_DO_CONSUMO: tuple[str, ...] = ("aplicado", "duplicado")

#: Os nomes das duas metricas que este modulo move (KAM-006 CA5). A casa delas
#: e `packages/core-ts/src/eventos/metricas.ts`; nao ha ainda pilha de metricas
#: em Python, e por isso o que se injecta e um `Metricas` com `contar`.
METRICA_CONSUMIDOS = "evt_consumed_total"
METRICA_RETENTATIVAS = "evt_retry_total"


def atraso_da_tentativa_do_consumidor(tentativas: int) -> int:
    """O atraso, em milissegundos, antes da tentativa numero `tentativas + 1`.

    `tentativas` e quantas ja falharam. Acima da escada devolve o ultimo degrau,
    em vez de crescer para sempre: a sexta falha nao espera, vai para a DLQ.

    `type(...) is not int` e nao `isinstance`: `True` e um `int`, e uma tentativa
    numero `True` e um erro de chamada, nao a primeira tentativa.
    """
    if type(tentativas) is not int or tentativas < 1:
        raise ValueError(f"tentativas tem de ser um inteiro >= 1: {tentativas!r}")
    indice = min(tentativas, len(ESCADA_DO_CONSUMIDOR)) - 1
    return ESCADA_DO_CONSUMIDOR[indice]


class Adiar(Exception):
    """A pre-condicao ainda nao se verifica. Tenta-se outra vez."""

    def __init__(
        self,
        segundos: int = ADIAMENTO_POR_OMISSAO,
        porque: str = "pre-condicao de estado por verificar",
    ) -> None:
        super().__init__(f"adiar {segundos}s: {porque}")
        self.segundos = segundos
        self.porque = porque

    @property
    def atraso_ms(self) -> int:
        """O mesmo atraso em milissegundos, que e a unidade da fila.

        Existe porque a escada deste modulo esta em milissegundos e o `segundos`
        esta em segundos (o §6.3 fala em «Adiar(5 s)»): um `* 1000` esquecido na
        fronteira transformava 5 s em 5 ms e queimava as seis tentativas num
        instante. Quem re-enfileira usa isto e nao multiplica nada.
        """
        return self.segundos * 1_000


class ForaDeOrdem(Exception):
    """O evento vem atrasado e a transicao nao e valida. Nao ha tentativa que resolva."""

    #: O valor que vai para a coluna `erro` da DLQ, e que o criterio 4 exige.
    CODIGO = "fora_de_ordem"

    def __init__(self, detalhe: str) -> None:
        super().__init__(f"{ForaDeOrdem.CODIGO}: {detalhe}")
        self.detalhe = detalhe


class MaquinaEmFalta(RuntimeError):
    """O tipo causa uma transicao e nao foi dada maquina de estados.

    O TypeScript levanta aqui um `Error` generico; um erro com nome e o que o
    resto deste nucleo faz, e e o que permite ao chamador distinguir um defeito
    de configuracao (falta a maquina) de uma falha do efeito.
    """


@dataclass(frozen=True)
class Resultado:
    """O que um `executar` devolve: as linhas e quantas linhas mexeu.

    `contagem` e `None` quando o cliente nao a sabe (e o `rowCount` nulo do
    `pg`); o consumidor le-a como zero, que e o que diz «duplicado».
    """

    linhas: Sequence[Mapping[str, object]] = ()
    contagem: int | None = None


class ClienteSql(Protocol):
    """O minimo de um cliente SQL: **uma** ligacao, nao um *pool*.

    `BEGIN`, `COMMIT` e `ROLLBACK` passam por aqui como qualquer outra
    instrucao: a transaccao e deste modulo, e so com uma ligacao e que a marca e
    o efeito caem dentro dela.
    """

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> Resultado: ...


class Metricas(Protocol):
    """O que se conta. Nenhuma etiqueta leva identificadores (`OBS-I`)."""

    def contar(self, metrica: str, sufixo: str | None = None, quanto: int = 1) -> None:
        ...


#: O efeito de negocio. Corre **dentro** da transaccao, com o mesmo cliente.
Efeito = Callable[[ClienteSql], None]


@dataclass(frozen=True)
class ResultadoDoConsumo:
    """O desfecho, e o `seq` mais alto ja consumido deste agregado."""

    desfecho: str
    ultimo_seq: int | None


@dataclass(frozen=True)
class OpcoesDoConsumo:
    """O que o consumo precisa de saber. A ordem de leitura e a do TypeScript."""

    bd: ClienteSql
    consumer: str
    envelope: Mapping[str, object]
    #: Da subscricao. Para `payment.*` e sempre `True` (restricao da revisao
    #: 0005). Decide **so** a leitura da ordem, nao a pre-condicao de estado.
    exige_ordem: bool = False
    #: Obrigatoria sempre que o tipo causa transicao (`ESTADO_PRETENDIDO`),
    #: com ordem ou sem ela.
    maquina: MaquinaDeEstados | None = None
    metricas: Metricas | None = None


def _ler_seq(bruto: object) -> int | None:
    """O `seq` que a base devolveu, ou `None`.

    O `max(agregado_seq)` de um agregado sem linhas anteriores e `NULL`, e e
    esse o `None` — as tres colunas de agregado sao `NOT NULL` desde a 0005,
    pelo que um `NULL` aqui significa «nao ha anterior» e nao «veio vazio».

    **A assimetria com o TypeScript e deliberada.** Lado o lado, o `lerSeq` do
    `consumo.ts` recusa o que passe de `Number.MAX_SAFE_INTEGER`, porque um
    `bigint` acima de 2^53 arredonda em silencio num `number` e um `seq`
    arredondado compara-se mal — e a diferenca entre adiar e mandar para a DLQ.
    O `int` do Python e exacto e nao tem esse tecto, pelo que aqui nao ha tecto
    nenhum: recusa-se o que **nao e um inteiro**, e mais nada.
    """
    if bruto is None:
        return None
    # `bool` e um `int`, e um `seq` que valha `True` e um condutor a devolver
    # outra coisa, nao a primeira linha do agregado.
    if isinstance(bruto, bool) or not isinstance(bruto, (int, str)):
        raise ValueError(
            f"agregado_seq nao e um inteiro: {type(bruto).__name__}. Comparar um "
            "seq que nao se leu decidiria entre adiar e DLQ por adivinhacao"
        )
    try:
        return int(bruto)
    except ValueError:
        raise ValueError(
            "agregado_seq nao e um inteiro. Comparar um seq que nao se leu "
            "decidiria entre adiar e DLQ por adivinhacao"
        ) from None


def _contar(metricas: Metricas | None, metrica: str, sufixo: str) -> None:
    if metricas is not None:
        metricas.contar(metrica, sufixo)


def consumir(opcoes: OpcoesDoConsumo, efeito: Efeito) -> ResultadoDoConsumo:
    """Processa um evento uma so vez, com o efeito na mesma transaccao.

    Levanta `Adiar` quando a pre-condicao de estado ainda nao se verifica,
    `ForaDeOrdem` quando o evento vem atrasado e a transicao nao e valida, e
    propaga qualquer erro do efeito — sempre depois de `ROLLBACK`.
    """
    bd = opcoes.bd
    envelope = opcoes.envelope
    metricas = opcoes.metricas
    agregado: Mapping[str, object] = envelope["agregado"]  # type: ignore[assignment]

    bd.executar("BEGIN")
    try:
        marca = bd.executar(
            SQL_MARCAR_CONSUMIDO,
            (
                opcoes.consumer,
                envelope["id"],
                envelope["tenant_id"],
                agregado["tipo"],
                agregado["id"],
                agregado["seq"],
            ),
        )
        if (0 if marca.contagem is None else marca.contagem) == 0:
            # Duplicado. `COMMIT` e nao `ROLLBACK`: nao ha nada para desfazer, e
            # um `ROLLBACK` aqui lia-se como erro no registo de quem depurar.
            bd.executar("COMMIT")
            _contar(metricas, METRICA_CONSUMIDOS, "duplicado")
            return ResultadoDoConsumo(desfecho="duplicado", ultimo_seq=None)

        # A leitura do ultimo `seq` so interessa a quem exige ordem: e ela que
        # distingue «vem atrasado» de «vem cedo».
        ultimo_seq: int | None = None
        if opcoes.exige_ordem:
            leitura = bd.executar(
                SQL_ULTIMO_SEQ,
                (
                    opcoes.consumer,
                    agregado["tipo"],
                    agregado["id"],
                    envelope["id"],
                ),
            )
            ultimo_seq = _ler_seq(
                leitura.linhas[0].get("ultimo") if leitura.linhas else None
            )

        # A pre-condicao de estado e verificada **fora** do `exige_ordem`, e
        # isto e uma correccao: com ela dentro, uma subscricao com
        # `exige_ordem = False` sobre um tipo que causa transicao aplicava-a
        # **sem verificacao nenhuma**. A restricao do DDL so obriga
        # `exige_ordem` em `payment.%`, pelo que o buraco era alcancavel por
        # configuracao.
        pretendido = ESTADO_PRETENDIDO.get(str(envelope["tipo"]))
        if pretendido is not None:
            if opcoes.maquina is None:
                raise MaquinaEmFalta(
                    f"o tipo {envelope['tipo']} causa a transicao para "
                    f"{pretendido} e nao foi dada maquina de estados: sem ela "
                    "nao se verifica a pre-condicao, e o ADR-013 manda que o "
                    "paga so se alcance por evento autenticado"
                )
            estado = opcoes.maquina.estado_de(
                str(agregado["tipo"]), str(agregado["id"])
            )
            if estado is None:
                # O agregado ainda nao existe para este consumidor. Nao e
                # invalido: e cedo. `None` nunca e «pode».
                raise Adiar(
                    ADIAMENTO_POR_OMISSAO,
                    f"{agregado['tipo']} {agregado['id']} ainda nao existe "
                    "neste consumidor",
                )
            if not pode_transitar(estado, pretendido):
                # Sem o ultimo `seq` nao se sabe se o evento vem atrasado, e a
                # saida e sempre `Adiar` — nunca `fora_de_ordem`.
                atrasado = (
                    ultimo_seq is not None and int(agregado["seq"]) < ultimo_seq  # type: ignore[arg-type]
                )
                if atrasado:
                    raise ForaDeOrdem(
                        f"seq {agregado['seq']} < {ultimo_seq} e {estado} -> "
                        f"{pretendido} nao e transicao valida"
                    )
                raise Adiar(
                    ADIAMENTO_POR_OMISSAO,
                    f"{estado} -> {pretendido} ainda nao e valido",
                )

        efeito(bd)
        bd.executar("COMMIT")
        _contar(metricas, METRICA_CONSUMIDOS, "aplicado")
        return ResultadoDoConsumo(desfecho="aplicado", ultimo_seq=ultimo_seq)
    except BaseException as erro:
        # `ROLLBACK` sempre, e so depois se propaga: sem ele a ligacao fica numa
        # transaccao abortada e o trabalho seguinte falha com um erro que nao e
        # o dele. O `except` vazio e deliberado — se o proprio `ROLLBACK`
        # falhar, o erro que interessa e o de cima.
        try:
            bd.executar("ROLLBACK")
        except Exception:
            pass  # a ligacao ja morreu; o erro de cima e o que explica
        if isinstance(erro, Adiar):
            _contar(metricas, METRICA_RETENTATIVAS, "adiado")
        raise
