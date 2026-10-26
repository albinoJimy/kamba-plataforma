"""A `ToolLayer`: `for_context`, `invoke` e os **oito passos** do §6.1.

O `docs/tecnica/02` §6.1 escreve o contrato e o pipeline, e o critero 1 do bloco
pede que `invoke` os percorra «por esta ordem» e «falhe fechada em cada um», com
«um teste por passo a provar que o passo seguinte nao corre».

## A ordem e dados, e nao a ordem em que estao escritos

Os oito passos sao funcoes e o `PASSOS` e a tupla delas, por ordem. Nao e
indirecao por gosto: e o que torna a **ordem** uma coisa que um teste pode
afirmar — `nomes_dos_passos()` contra os oito do §6.1 — e o que permite a um
teste por passo substituir os seguintes por espioes e provar que nenhum correu.
Escritos em linha dentro de um `invoke` de cem linhas, a ordem so se afirmava
lendo, e «o passo seguinte nao corre» provava-se por inspeccao.

Cada passo recebe a `Invocacao` (o estado desta chamada) e devolve `None` para
«passa» ou um `ToolResult` para «recusa». Quem recusa pára o pipeline.

## O registo nao e um passo que se possa saltar

O §6.1 poe o `tool_audit` no passo 7, depois da chamada ao backend. Mas o
critero 5 pede **cobertura 100%** das invocacoes `write`/`money`, e uma
invocacao recusada no passo 1 e uma invocacao. Por isso a escrita corre no
`finally` do pipeline e nao so no caminho feliz: a ordem do §6.1 cumpre-se (o
registo e depois do backend) **e** a cobertura tambem.

Com uma excepcao nomeada, e nao e um atalho: uma tool que o catalogo **nao
conhece** nao tem `klass`, e o `klass` da `tool_audit` e `NOT NULL`. Nao ha
linha possivel. Fica o contador `agr_tool_erros_total{tool_not_allowed}` e o
log; e a invocacao nao e de classe `write` nem `money`, porque nao e de classe
nenhuma — o critero 5 nao fala dela.

## O que nao se repete aqui

**O passo 2 e o `hook_de_tool` do KAM-009**, que o escreveu para esta camada
pelo nome (`kamba_core.ten.hook`, «o §6.1 passo 2 ... e este modulo»). Nao se
reimplementa: ele ja faz as tres verificacoes na ordem que protege cada uma
(entitlement, tecto por pedido, consumo) e ja devolve os codigos do §6.5.

**O passo 5 e um ponto de extensao do KAM-029**, e o que aqui esta e a regra que
o DoD pede por extenso: uma tool `write` ou `money` **nunca corre sem chave**. A
derivacao da chave (`sha256(tenant_id | contact_id | tool | cart_id)`, §6.3), a
tabela `tool_idempotency` e o `idempotent_replay=True` sao desse ticket.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from kamba_core import tenant_guard
from kamba_core.ten.entitlements import Resultado
from kamba_core.ten.hook import hook_de_tool

from ..metricas import (
    METRICA_TOOL_DISJUNTOR,
    METRICA_TOOL_ERROS,
    METRICA_TOOL_INVOCACOES,
    METRICA_TOOL_LATENCIA,
    METRICA_TOOL_TENANT_MISMATCH,
    MetricasDoAgr,
)
from . import auditoria, idempotency
from .contexto import Confirmation, ToolContext
from .disjuntor import Disjuntor
from .erros import (
    TENANT_MISMATCH,
    TOOL_NOT_ALLOWED,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    VALIDATION_ERROR,
    ErroDeTool,
    ToolResult,
    falha,
)
from .especificacoes import (
    Catalogo,
    ErroDeBackend,
    EspecificacaoDeTool,
    Pedido,
)

#: O tecto de tempo de uma tool `read`, em milissegundos (§6.5: «read 2 s»).
VARIAVEL_DE_TIMEOUT_READ: Final = "KAMBA_TLS_TIMEOUT_READ_MS"
TIMEOUT_READ_POR_OMISSAO_MS: Final = 2_000

#: O tecto de tempo de uma tool `write` ou `money` (§6.5: «write/money 8 s»).
VARIAVEL_DE_TIMEOUT_ESCRITA: Final = "KAMBA_TLS_TIMEOUT_ESCRITA_MS"
TIMEOUT_ESCRITA_POR_OMISSAO_MS: Final = 8_000

#: Quantas tomadas a camada abre. Dicionario §3.27.
#:
#: **Nao e uma.** A primeira versao tinha uma ligacao e um `asyncio.Lock`, como
#: o `leitor` do `conversa.py` — e ali a razao escrita e que «um *worker* faz uma
#: leitura por turno e os turnos do *worker* sao em serie». Aqui nao: um turno
#: invoca tools varias vezes e os turnos correm em concorrencia, pelo que uma
#: tomada so serializava **todos os tenants**. Medido: dez invocacoes de dez
#: tenants com um backend de 200 ms levavam 2,02 s em vez de ~0,2 s — bloqueio de
#: cabeca de fila a atravessar tenants, que e o defeito mais caro do KAM-025
#: repetido. Apanhado pela revisao adversarial.
VARIAVEL_DE_LIGACOES: Final = "KAMBA_TLS_LIGACOES"
LIGACOES_POR_OMISSAO: Final = 4

#: A folga do tecto que a camada impoe, sobre o tecto da classe.
#:
#: O tecto do §6.5 e do **backend**, e onde ha um tecto preciso do lado do
#: servidor — o `statement_timeout` do `get_store_info` — e esse que tem de
#: morder, porque e ele que tambem para a consulta na base. A espera da camada e
#: a **rede** por baixo: existe para um executor que ignore o tecto que recebeu,
#: e nesse caso o cliente deixa de ficar pendurado. Sem a folga, os dois
#: tectos corriam ao mesmo instante e qual ganhava dependia do escalonador.
MARGEM_DO_TECTO_MS: Final = 500


class ConfiguracaoDaCamadaError(ValueError):
    """Um tecto de tempo que nao serve. Codigo de saida `2` no arranque."""


def _timeout(variavel: str, omissao: int) -> int:
    bruto = os.environ.get(variavel)
    if bruto is None or bruto == "":
        return omissao
    try:
        valor = int(bruto)
    except ValueError as erro:
        raise ConfiguracaoDaCamadaError(f"{variavel}={bruto!r} nao e um inteiro") from erro
    if valor < 1:
        raise ConfiguracaoDaCamadaError(
            f"{variavel}={valor}: um tecto de zero recusava toda a invocacao, e um "
            "tecto negativo nao e um tecto"
        )
    return valor


@dataclass(frozen=True, slots=True)
class BoundTool:
    """Uma tool ja fechada sobre um `ToolContext` (§6.1, `for_context`).

    **O esquema vai ao modelo; o contexto nao.** E a razao pela qual este objecto
    existe em vez de se passar o `ToolContext` junto com o nome da tool: o que o
    modelo recebe e `nome`, `klass`, `versao` e `esquema`, e o `ctx` fica do lado
    de ca para o `invoke`.
    """

    nome: str
    klass: str
    versao: str
    esquema: dict[str, Any]


class _ClienteDeCursor:
    """Adapta um cursor DB-API ao `ClienteSql` que o `hook_de_tool` pede.

    O `hook` quer linhas como `Mapping`; o `pg8000` devolve tuplos. A traducao e
    pelo `cursor.description`, e nao por posicao: o `SQL` do TEN e dele, e uma
    ordem de colunas assumida aqui quebrava em silencio no dia em que ele
    acrescentasse uma.
    """

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> Resultado:
        self._cursor.execute(sql, tuple(parametros))
        descricao = self._cursor.description
        if not descricao:
            return Resultado(linhas=(), contagem=self._cursor.rowcount)
        nomes = [coluna[0] for coluna in descricao]
        linhas: list[Mapping[str, object]] = [
            dict(zip(nomes, linha, strict=True)) for linha in self._cursor.fetchall()
        ]
        return Resultado(linhas=linhas, contagem=self._cursor.rowcount)


@dataclass
class Invocacao:
    """O estado de uma invocacao a correr pelos oito passos."""

    camada: "ToolLayer"
    ctx: ToolContext
    nome: str
    args_crus: dict[str, Any]
    allowed: tuple[str, ...]
    confirmation: Confirmation | None = None
    idempotency_key: str | None = None
    #: `(chave_de_tecto, valor_deste_pedido)` para o passo 2. O §6.1 nomeia o
    #: `valor_max_pedido_kz`; a chave canonica e `valor_max_pedido_minor`
    #: (dicionario §3.26). Quem o traz e a tool que tem o valor — o
    #: `criar_pedido` do KAM-031.
    tecto: tuple[str, int] | None = None
    especificacao: EspecificacaoDeTool | None = None
    args: BaseModel | None = None
    #: A chave do §6.3, derivada no passo 5 (KAM-029). **Nao e a
    #: `idempotency_key` acima**, e a razao esta na nota do `idempotency.py`: a
    #: de cima e do turno (vai ao `usage_ledger` e a linha de auditoria), esta e
    #: do carrinho, e um segundo toque com `wamid` novo e um turno novo.
    chave: str | None = None
    #: Se a reserva do passo 5 nos fez donos da linha — e portanto se o
    #: `finally` do pipeline a tem de fechar.
    dono_da_chave: bool = False
    resposta: Any = None
    passos_corridos: list[str] = field(default_factory=list)
    #: Quando a invocacao entrou no pipeline, no relogio da camada. O passo 7
    #: mede a latencia a partir daqui — e nao de um valor que o `finally`
    #: escreva depois dele, que era zero no caminho feliz.
    #: A tomada que esta invocacao tem emprestada da fila da camada.
    ligacao: Any = None
    comecou: float = 0.0
    #: Se a linha de `tool_audit` ja foi escrita. O passo 7 escreve-a no caminho
    #: feliz e o `finally` escreve-a quando um passo anterior recusou; e esta
    #: marca que faz com que seja **uma** linha e nao duas.
    registada: bool = False


# --------------------------------------------------------------------- passo 1
def passo_1_allowlist(inv: Invocacao) -> ToolResult | None:
    """A tool pertence a lista `allowed` da vertical (§6.1 passo 1).

    Tres recusas com o mesmo codigo, e sao tres perguntas diferentes:

    * a tool nao esta no catalogo — nao existe;
    * esta no catalogo e nao esta no `allowed` desta vertical — existe e nao e
      para aqui. E a lista **fechada** que o `registry/*.yaml` declara;
    * esta nas duas e esta `declarada` — existe, e para aqui, e ainda nao tem
      executor. Recusa-se com o mesmo codigo porque, da parte do modelo, e
      indistinguivel de nao existir: nem sequer lhe foi oferecida no
      `for_context`.

    O codigo e o mesmo nos tres casos de proposito. Distingui-los dizia a quem
    provocou a recusa se a tool existe noutra vertical, que e um oraculo sobre
    a configuracao de outro tenant.
    """
    especificacao = inv.camada.catalogo.get(inv.nome)
    if especificacao is None:
        return falha(TOOL_NOT_ALLOWED, f"a tool `{inv.nome}` nao existe no catalogo")
    # Guarda-se antes de decidir o resto: e o `klass` desta especificacao que
    # torna possivel a linha de `tool_audit` da recusa.
    inv.especificacao = especificacao
    if inv.nome not in inv.allowed:
        return falha(
            TOOL_NOT_ALLOWED,
            f"a tool `{inv.nome}` nao esta na lista `allowed` de `{inv.ctx.vertical}`",
        )
    if not especificacao.ligada:
        return falha(
            TOOL_NOT_ALLOWED,
            f"a tool `{inv.nome}` esta declarada e por ligar ({especificacao.credor})",
        )
    return None


# --------------------------------------------------------------------- passo 2
def passo_2_entitlement(inv: Invocacao) -> ToolResult | None:
    """Entitlement activo e limites do TEN (§6.1 passo 2) — o `hook` do KAM-009.

    Corre **dentro** de uma transaccao com `app.tenant_id`: a
    `platform.entitlements` tem RLS, e sem contexto o `check_entitlement` lia
    zero linhas e negava toda a invocacao de todos os tenants. Falha fechada no
    sentido certo, mas pela razao errada — e um teste que a medisse ficava
    verde sem nunca ter lido um entitlement.
    """
    erro = inv.camada.verificar_entitlement(inv)
    if erro is None:
        return None
    return ToolResult(ok=False, error=erro)


# --------------------------------------------------------------------- passo 3
def passo_3_argumentos(inv: Invocacao) -> ToolResult | None:
    """Argumentos validados por Pydantic com `extra="forbid"` (§6.1 passo 3).

    O `extra="forbid"` esta garantido pela especificacao, que o recusa no
    arranque — aqui o que se faz e construir o modelo e traduzir o
    `ValidationError` no codigo do §6.5. O detalhe que vai para o log e o do
    Pydantic **sem os valores**: `errors()` traz o `input` de cada campo que
    falhou, e esse `input` e texto que o modelo produziu a partir da mensagem
    do cliente.
    """
    assert inv.especificacao is not None and inv.especificacao.modelo is not None
    try:
        inv.args = inv.especificacao.modelo(**inv.args_crus)
    except ValidationError as erro:
        campos = sorted(
            ".".join(str(parte) for parte in detalhe["loc"]) or "<raiz>"
            for detalhe in erro.errors()
        )
        return falha(
            VALIDATION_ERROR,
            f"os argumentos de `{inv.nome}` nao validam nos campos {campos}",
        )
    except TypeError as erro:
        # `modelo(**args)` com uma chave que nao e identificador — por exemplo
        # um `{"1": 2}` vindo de JSON — levanta `TypeError` e nao
        # `ValidationError`. E a mesma classe de defeito e leva o mesmo codigo.
        return falha(VALIDATION_ERROR, f"os argumentos de `{inv.nome}` nao se leem: {erro}")
    return None


# --------------------------------------------------------------------- passo 4
def passo_4_confirmacao(inv: Invocacao) -> ToolResult | None:
    """`write`/`money` exigem `Confirmation` valida (§6.1 passo 4, `08` §4.3).

    Tres perguntas, e **dois** codigos diferentes, porque sao duas naturezas:

    * sem botao, com botao mal formado, com botao de outra referencia, ou de um
      turno anterior → `VALIDATION_ERROR`. O tratamento do §6.5 e «uma
      correccao automatica, depois `unknown_reply`», e e o certo: o caminho de
      recuperacao e o runtime emitir o botao e o cliente carregar nele. O §6.3
      chama ao caso do turno anterior *stale*, e e isso que ele e;
    * botao de **outro contacto** → `TENANT_MISMATCH`. Nao e um erro de forma: e
      uma escrita no carrinho de uma pessoa autorizada por outra, que e a
      exfiltracao entre contactos do `docs/tecnica/08` §4.4. O §6.5 classifica-o
      como violacao — bloqueio, alerta, **nunca** repetir — e o critero 8 pede o
      alerta pelo nome.
    """
    assert inv.especificacao is not None and inv.args is not None
    if not inv.especificacao.exige_confirmacao:
        return None
    if inv.confirmation is None:
        return falha(
            VALIDATION_ERROR,
            f"`{inv.nome}` e de classe `{inv.especificacao.klass}` e nao veio "
            "confirmacao; a escrita so corre apos botao emitido pelo runtime",
        )
    if inv.confirmation.contact_id != inv.ctx.contact_id:
        return falha(
            TENANT_MISMATCH,
            f"a confirmacao de `{inv.nome}` veio de outro contacto desta conversa",
        )
    campo = inv.especificacao.campo_de_confirmacao
    assert campo is not None  # a especificacao exige-o para `write`/`money`
    referencia = getattr(inv.args, campo, None)
    if not inv.confirmation.autoriza(inv.ctx, str(referencia) if referencia else ""):
        return falha(
            VALIDATION_ERROR,
            f"a confirmacao de `{inv.nome}` nao cita `{campo}` deste turno",
        )
    return None


# --------------------------------------------------------------------- passo 5
def passo_5_idempotencia(inv: Invocacao) -> ToolResult | None:
    """A chave de idempotencia (§6.1 passo 5, §6.3). Preenchido pelo KAM-029.

    Uma tool `read` nao passa por aqui — repetir uma leitura nao tem efeito —, e
    exigir-lhe chave obrigava o grafo a derivar uma para cada pergunta de preco.

    Para `write`/`money` ha **duas** verificacoes, e a ordem importa:

    1. a regra que o KAM-028 deixou: sem a chave do **chamador** nao se corre.
       Ela nao e a chave do carrinho (ver o `idempotency.py`), mas e o que faz o
       passo 2 contar o turno uma vez so, e um chamador que a nao traga tem um
       defeito que e melhor descobrir aqui do que no `usage_ledger`;
    2. o protocolo do §6.3: deriva-se a chave do carrinho, reserva-se, e o que a
       reserva disser decide se o backend corre, se se devolve o resultado
       guardado, ou se se recusa sem executar.

    A referencia que entra na chave e a do botao que o passo 4 **ja** confrontou
    com os argumentos (`camada.py`, passo 4): usa-se a dos argumentos, que e a
    que o §6.3 nomeia, e chegar aqui e ter provado que as duas batem.
    """
    assert inv.especificacao is not None
    if not inv.especificacao.exige_confirmacao:
        return None
    if not isinstance(inv.idempotency_key, str) or not inv.idempotency_key.strip():
        return falha(
            VALIDATION_ERROR,
            f"`{inv.nome}` e de classe `{inv.especificacao.klass}` e nao traz chave de "
            "idempotencia do chamador (`docs/tecnica/02` §6.3)",
        )
    return inv.camada.reservar_idempotencia(inv)


# --------------------------------------------------------------------- passo 6
def passo_6_backend(inv: Invocacao) -> ToolResult | None:
    """A chamada ao backend, com o `tenant_id` no contexto (§6.1 passo 6).

    O disjuntor pergunta-se **antes**: o critero 7 pede `UPSTREAM_DOWN` «sem
    chamar o backend», e um disjuntor consultado depois da chamada nao poupa
    nada.
    """
    assert inv.especificacao is not None and inv.args is not None
    return inv.camada.chamar_backend(inv)


# --------------------------------------------------------------------- passo 7
def passo_7_auditoria(inv: Invocacao) -> ToolResult | None:
    """A linha em `tool_audit` (§6.1 passo 7).

    Devolve sempre `None` — nao recusa nada: o efeito ja aconteceu. O que faz e
    escrever, e se nao conseguir **levanta** (`AuditoriaIndisponivelError`): a
    razao esta no `auditoria.py`.

    Corre aqui **e** no `finally` do pipeline, e nao e duplicacao: quem escreve
    e o `ToolLayer._registar`, que escreve uma vez por invocacao. Este passo
    existe para que a ordem do §6.1 se leia nos `PASSOS` — o registo e depois do
    backend e antes dos `facts` — e para que um teste a possa afirmar.
    """
    inv.camada.registar_se_falta(inv)
    return None


# --------------------------------------------------------------------- passo 8
def passo_8_facts(inv: Invocacao) -> ToolResult:
    """A devolucao dos `facts` (§6.1 passo 8, ADR-007).

    E o unico passo que devolve sempre um `ToolResult`: chegar aqui e ter
    corrido os sete anteriores.
    """
    assert inv.resposta is not None
    return ToolResult(ok=True, data=inv.resposta.data, facts=inv.resposta.facts)


#: Os oito, pela ordem do §6.1. **A ordem e o critero 1** e ha um teste que
#: confronta esta tupla com os oito nomes desse documento.
PASSOS: Final = (
    passo_1_allowlist,
    passo_2_entitlement,
    passo_3_argumentos,
    passo_4_confirmacao,
    passo_5_idempotencia,
    passo_6_backend,
    passo_7_auditoria,
    passo_8_facts,
)


def nomes_dos_passos() -> tuple[str, ...]:
    """`("allowlist", "entitlement", …)` — para o teste da ordem."""
    return tuple(passo.__name__.split("_", 2)[2] for passo in PASSOS)


class ToolLayer:
    """A unica via de leitura e escrita dos agentes (§6.1, ADR-015)."""

    def __init__(
        self,
        catalogo: Catalogo,
        *,
        abrir_ligacao: Callable[[], Any],
        disjuntor: Disjuntor | None = None,
        metricas: MetricasDoAgr | None = None,
        relogio: Callable[[], float] = time.monotonic,
        passos: Sequence[Callable[[Invocacao], ToolResult | None]] = PASSOS,
        ligacoes: int | None = None,
        espera_de_idempotencia_ms: int = idempotency.TECTO_DE_ESPERA_MS,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.catalogo = catalogo
        self._abrir_ligacao = abrir_ligacao
        # O tecto do §6.3 (`poll <= 3 s`) e o `dormir` que o espera. Sao
        # parametros e nao variaveis de ambiente, ao contrario dos tectos das
        # classes: este valor vem do desenho (`docs/tecnica/03` §6.3) e nao da
        # afinacao de um ambiente, e quem o troca nos ensaios e o relogio
        # simulado do criterio 5.
        self._espera_de_idempotencia = espera_de_idempotencia_ms
        self._dormir = dormir
        self.disjuntor = disjuntor if disjuntor is not None else Disjuntor()
        self._metricas = metricas
        self._relogio = relogio
        self._passos = tuple(passos)
        self._timeout_read = _timeout(
            VARIAVEL_DE_TIMEOUT_READ, TIMEOUT_READ_POR_OMISSAO_MS
        )
        self._timeout_escrita = _timeout(
            VARIAVEL_DE_TIMEOUT_ESCRITA, TIMEOUT_ESCRITA_POR_OMISSAO_MS
        )
        self._quantas = (
            ligacoes
            if ligacoes is not None
            else _timeout(VARIAVEL_DE_LIGACOES, LIGACOES_POR_OMISSAO)
        )
        # **A fila e o pool, e e tambem o tecto de tomadas.** Nasce com uma
        # vaga por ligacao e cada vaga e `None` ate alguem precisar dela: a
        # camada constroi-se no arranque e nao se abrem quatro ligacoes a uma
        # base que ainda pode estar a subir.
        #
        # Todas as operacoes dela correm no **laco** e nunca na *thread*: um
        # `put_nowait` de dentro de um `asyncio.to_thread` nao e seguro.
        self._tomadas: asyncio.Queue[Any] = asyncio.Queue()
        for _ in range(self._quantas):
            self._tomadas.put_nowait(None)

    # ------------------------------------------------------------- contrato
    def for_context(self, ctx: ToolContext, allowed: Sequence[str]) -> list[BoundTool]:
        """As tools que o modelo ve neste turno (§6.1).

        **So as `ligadas`, e so as do `allowed`.** Uma entrada `declarada` nao
        entra: oferecer ao modelo uma tool que o `invoke` vai recusar era
        ensinar-lhe a chamar o que nao responde, e gastar um turno a explicar
        que nao da. O `ctx` nao vai no `BoundTool`: o modelo recebe o esquema e
        o esquema nao tem `tenant_id` (ha *lint* de CI a prova-lo).
        """
        ligadas = []
        for nome in allowed:
            especificacao = self.catalogo.get(nome)
            if especificacao is None or not especificacao.ligada:
                continue
            ligadas.append(
                BoundTool(
                    nome=especificacao.nome,
                    klass=especificacao.klass,
                    versao=especificacao.versao,
                    esquema=especificacao.esquema(),
                )
            )
        return ligadas

    async def invoke(
        self,
        ctx: ToolContext,
        name: str,
        args: dict[str, Any],
        *,
        allowed: Sequence[str],
        confirmation: Confirmation | None = None,
        idempotency_key: str | None = None,
        tecto: tuple[str, int] | None = None,
    ) -> ToolResult:
        """Os oito passos, pela ordem, falhando fechada em cada um.

        O trabalho que bloqueia — a base, o backend — corre em
        `asyncio.to_thread`, que e a forma do `conversa.py` do KAM-025: o
        `pg8000` nao e seguro para uso concorrente na mesma ligacao.

        **Mas a tomada vem de uma fila e nao e uma so**, e a diferenca e de
        isolamento: com uma tomada, dez invocacoes de dez tenants corriam em
        serie (medido: 2,02 s com um backend de 200 ms). A fila e o pool e e o
        tecto: no maximo `KAMBA_TLS_LIGACOES` ligacoes, e quem nao tem vaga
        espera — por uma vaga, e nao pelo turno de outro tenant.

        **E a camada impoe o tecto de tempo**, que e a outra metade do critero
        7. O `timeout_ms` que o executor recebe e o tecto *dele*; esta espera e
        a rede por baixo, para um executor que o ignore. Sem ela, um executor
        de 5 s contra um tecto de 2 s devolvia `ok=True` em 5 s — medido.

        Quando a espera estoura, a *thread* **continua**: nao se pode cancelar
        uma, e nao se quer. Ela tem a ligacao, acaba o pipeline e escreve a
        linha de `tool_audit` com a latencia real — pelo que a invocacao nao
        desaparece do registo. O que ela custa e a sua vaga, ate acabar, e isso
        e o tecto a funcionar: uma tool pendurada tira **uma** tomada das
        `KAMBA_TLS_LIGACOES`, e nao o processo.

        **O `allowed` vem por parametro e nao do registo.** A assinatura do §6.1
        poe-o no `for_context`, e quem o tem no `invoke` e o grafo, que o recebeu
        do `AgentRegistry` quando resolveu a vertical. Ler o registo aqui dava a
        esta camada uma segunda fonte para a mesma lista fechada.
        """
        vaga = await self._tomadas.get()
        tarefa = asyncio.create_task(
            asyncio.to_thread(
                self._correr,
                vaga,
                ctx,
                name,
                args,
                tuple(allowed),
                confirmation,
                idempotency_key,
                tecto,
            )
        )
        try:
            resultado, ligacao = await asyncio.wait_for(
                asyncio.shield(tarefa), self._espera_de(name) / 1000
            )
        except TimeoutError:
            # A vaga volta quando a *thread* acabar, e nao agora.
            tarefa.add_done_callback(self._devolver)
            return falha(
                UPSTREAM_TIMEOUT,
                f"`{name}` passou do tecto de {self._espera_de(name)} ms",
            )
        except BaseException:
            # **Duas situacoes com o mesmo `except`, e a diferenca e quem tem a
            # tomada.** Se a tarefa acabou, o pipeline levantou (auditoria
            # indisponivel, contexto invalido) e a ligacao ja foi fechada por
            # ela: a vaga volta vazia, agora. Se **nao** acabou — quem chamou
            # cancelou o `invoke`, e um `CancelledError` e uma `BaseException` —
            # a *thread* continua com a tomada, e devolve-la aqui punha na fila
            # uma vaga a mais e deixava uma ligacao a correr fora dela.
            if tarefa.done():
                self._tomadas.put_nowait(None)
            else:
                tarefa.add_done_callback(self._devolver)
            raise
        self._tomadas.put_nowait(ligacao)
        return resultado

    def _espera_de(self, nome: str) -> int:
        """O tecto da classe da tool, mais a folga. Em milissegundos.

        Uma tool que o catalogo nao conheca leva o tecto de `read`: o passo 1
        recusa-a de imediato e nada lento corre, e dar-lhe o tecto de escrita
        era deixar oito segundos a um nome inventado.
        """
        especificacao = self.catalogo.get(nome)
        klass = especificacao.klass if especificacao is not None else "read"
        return self.timeout_de(klass) + MARGEM_DO_TECTO_MS

    def _devolver(self, tarefa: "asyncio.Task[Any]") -> None:
        """Devolve a vaga de uma *thread* que acabou depois de a espera estourar.

        Corre no laco (e um `done_callback`), que e onde a fila se pode tocar.
        Uma *thread* que acabou mal nao devolve ligacao: a vaga volta vazia e a
        proxima invocacao abre outra.
        """
        try:
            _, ligacao = tarefa.result()
        except BaseException:  # noqa: BLE001 — a excepcao e de quem a espera
            ligacao = None
        self._tomadas.put_nowait(ligacao)

    async def fechar(self) -> None:
        """Fecha as tomadas que estao na fila. Para o `ao_encerrar` do `lifespan`.

        Fecha **as que estao livres**: uma que esteja numa *thread* a correr
        volta a fila depois e o processo esta a cair de qualquer forma. Nao
        espera por elas, porque o `SIGTERM` tem prazo.
        """
        while not self._tomadas.empty():
            ligacao = self._tomadas.get_nowait()
            if ligacao is None:
                continue
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a fechar, um erro nao muda nada
                pass

    # ------------------------------------------------------------- pipeline
    def _correr(
        self,
        vaga: Any,
        ctx: ToolContext,
        nome: str,
        args: dict[str, Any],
        allowed: tuple[str, ...],
        confirmation: Confirmation | None,
        idempotency_key: str | None,
        tecto: tuple[str, int] | None,
    ) -> tuple[ToolResult, Any]:
        """Corre na *thread*. Devolve o resultado **e** a ligacao, ou larga-a.

        A ligacao volta pelo valor de retorno e nunca pela fila: a fila e do
        laco. Uma ligacao quebrada nao volta — e a razao do `conversa.py` e do
        `trancas.py`: uma tomada em estado incerto que fique guardada faz
        **todas** as invocacoes seguintes falharem ate alguem reiniciar.
        """
        ligacao = vaga if vaga is not None else self._abrir_ligacao()
        inv = Invocacao(
            camada=self,
            ctx=ctx,
            nome=nome,
            args_crus=dict(args),
            allowed=allowed,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            tecto=tecto,
            ligacao=ligacao,
        )
        inv.comecou = self._relogio()
        resultado: ToolResult | None = None
        try:
            for passo in self._passos:
                inv.passos_corridos.append(passo.__name__)
                parou = passo(inv)
                if parou is not None:
                    resultado = parou
                    break
            if resultado is None:
                # Um conjunto de passos que nao devolva nada e um pipeline sem
                # passo 8. Levanta: devolver `ok` sem resposta era afirmar que a
                # tool correu.
                raise RuntimeError(
                    "o pipeline acabou sem resultado; o ultimo passo tem de devolver um"
                )
            return resultado, ligacao
        except BaseException:
            # **A reserva fecha-se aqui, antes de a ligacao cair.** Este caminho
            # fecha a ligacao — ela pode estar quebrada — e o `finally` corre
            # **depois** do `except`: deixar o fecho da reserva so para la era
            # tentar escrever numa ligacao ja fechada, e precisamente no caminho
            # em que a reserva mais precisa de fechar (o criterio 4 do KAM-029,
            # a falha entre o backend e o registo). Apanhado a correr a bateria
            # da falha injectada, que e a que percorre este caminho.
            #
            # Se o proprio fecho falhar, **nao se mascara a excepcao original**:
            # a linha fica `em_curso` e e o `shortcut` declarado no
            # `idempotency.py`. O que sobe tem de ser a falha que travou o turno.
            try:
                self.fechar_idempotencia(inv, resultado)
            except Exception:  # noqa: BLE001 — ver o paragrafo acima
                pass
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — ja esta quebrada
                pass
            raise
        finally:
            # O registo primeiro, as metricas depois: se a auditoria levantar, o
            # que tem de subir e isso — e um contador incrementado antes dela
            # dizia que a invocacao ficou registada.
            #
            # **As metricas correm mesmo que o registo levante**, e por isso vao
            # num `finally` proprio: sem ele, uma invocacao recusada cuja linha
            # nao se conseguiu escrever desaparecia dos dois lados, e um painel
            # com zero erros era indistinguivel de um sem trafego.
            # **A idempotencia primeiro, e a razao esta no `fechar_idempotencia`**:
            # a auditoria levanta por desenho, e uma linha de `tool_idempotency`
            # que ficasse aberta por causa disso punha a repeticao a cobrar outra
            # vez. Em cada `finally` proprio, para que nenhuma das tres falhas
            # engula as outras duas.
            try:
                self.fechar_idempotencia(inv, resultado)
            finally:
                try:
                    self.registar_se_falta(inv, resultado=resultado)
                finally:
                    self._contar(inv, resultado, self._latencia_de(inv))

    def _latencia_de(self, inv: Invocacao) -> int:
        return max(0, int((self._relogio() - inv.comecou) * 1000))

    # ------------------------------------------------------- passos, por dentro
    def reservar_idempotencia(self, inv: Invocacao) -> ToolResult | None:
        """O passo 5 do §6.3 (KAM-029): deriva, reserva, e decide.

        Devolver `None` e deixar o backend correr. Devolver um `ToolResult` e
        parar o pipeline — e nesse caminho o passo 6 **nao corre**, que e o que
        os criterios 1, 3 e 5 pedem por extenso («sem chamar o backend», «sem
        executar»).
        """
        assert inv.especificacao is not None and inv.args is not None
        campo = inv.especificacao.campo_de_confirmacao
        assert campo is not None, "o passo 4 nao deixa passar uma `write` sem campo"
        referencia = str(getattr(inv.args, campo))
        inv.chave = idempotency.derivar(inv.ctx, inv.especificacao.nome, referencia)
        reserva = idempotency.reservar(
            inv.ligacao,
            inv.ctx,
            inv.chave,
            inv.especificacao.nome,
            # **O modelo validado, e nao o `args_crus`.** O `args_crus` e o
            # dicionario como o modelo de linguagem o emitiu, e duas chamadas
            # semanticamente iguais podem nao ser iguais byte a byte: o segundo
            # toque e um **turno novo**, com geracao nova, e basta ele reemitir
            # um campo de omissao (`{"cart_id": "c-1"}` contra
            # `{"cart_id": "c-1", "nota": ""}`) ou dar `"2"` onde deu `2` para o
            # `args_hash` mudar — e o *replay* do criterio 8 virava
            # `INTENT_REUSED_WITH_DIFFERENT_CONTENT`. Achado 4 da revisao
            # adversarial (`ANALISE-31`).
            #
            # O `model_dump()` passa pela validacao: as omissoes estao
            # preenchidas e os tipos coagidos, pelo que o que se compara e a
            # **intencao** e nao a forma como ela foi escrita. O criterio 3 nao
            # se perde — um carrinho realmente diferente continua a dar hash
            # diferente.
            #
            # A `tool_audit.args_hash` continua a ser do `args_crus`, e as duas
            # colunas deixam de ser o mesmo valor: a auditoria registra o que
            # **chegou** (que e o que um registo deve guardar) e esta compara o
            # que **vale**. Esta dito no dicionario §3.28.
            auditoria.impressao(inv.args.model_dump()),
            tecto_ms=self._espera_de_idempotencia,
            relogio=self._relogio,
            dormir=self._dormir,
        )
        if reserva.dono:
            inv.dono_da_chave = True
            return None
        if reserva.codigo is not None:
            return falha(
                reserva.codigo,
                f"`{inv.especificacao.nome}` com a chave do §6.3 ja reservada: "
                f"{reserva.codigo}",
            )
        return ToolResult(
            ok=True, data=reserva.guardado or {}, idempotent_replay=True
        )

    def fechar_idempotencia(self, inv: Invocacao, resultado: ToolResult | None) -> None:
        """Fecha a linha de `tool_idempotency` que o passo 5 nos deu.

        Corre no `finally` do pipeline e **antes** da linha de auditoria, de
        propósito: se a auditoria levantar (ela levanta, por desenho) e o *job*
        voltar a fila, o que impede a repeticao de cobrar outra vez e esta linha
        estar fechada. E a janela que a `ANALISE-30` (achado 12) deixou aberta e
        nomeou este ticket para fechar.

        Uma linha so se fecha como `concluida` quando houve resultado **e** ele
        correu bem; em qualquer outro caminho fica `falhada`, que e o estado que
        a retoma do criterio 4 procura.
        """
        if not inv.dono_da_chave or inv.chave is None:
            return
        ok = resultado is not None and resultado.ok
        # **Tenta-se uma vez, e a marca limpa-se mesmo que a tentativa falhe.**
        #
        # Chama-se nos dois caminhos — no `except`, antes de a ligacao cair, e no
        # `finally` —, e a marca e o que faz da segunda chamada um `return`.
        # Limpar so **depois** de a escrita passar tinha um modo de falha pior do
        # que o que resolvia: com a ligacao ja quebrada, a tentativa do `except`
        # levantava (e e engolida ali, de proposito), a marca ficava de pe, e a
        # do `finally` levantava **de dentro do `finally`** — substituindo a
        # excepcao original por um `InterfaceError` do driver. Quem lesse o log
        # via o sintoma e nao a causa, numa tool `money`.
        #
        # Com a marca limpa a entrada, uma falha de fecho deixa a linha
        # `em_curso` e e o `shortcut` declarado no `idempotency.py` — que e o
        # desfecho que ja estava escrito para este caso.
        inv.dono_da_chave = False
        idempotency.fechar(
            inv.ligacao,
            inv.ctx,
            inv.chave,
            ok=ok,
            resultado=resultado.data if ok and resultado is not None else None,
        )

    def verificar_entitlement(self, inv: Invocacao) -> ErroDeTool | None:
        """O passo 2, dentro de uma transaccao com `app.tenant_id`."""
        chave, valor = (inv.tecto if inv.tecto is not None else (None, None))
        with tenant_guard.tx(inv.ligacao, inv.ctx.tenant_id) as cursor:
            erro = hook_de_tool(
                _ClienteDeCursor(cursor),
                inv.ctx,
                modulo=inv.ctx.vertical,
                idempotency_key=inv.idempotency_key,
                tecto_chave=chave,
                tecto_valor=valor,
            )
        if erro is None:
            return None
        detalhe = f"modulo `{erro.modulo}`"
        if erro.chave:
            detalhe += f", chave `{erro.chave}`"
        if erro.limite is not None:
            detalhe += f", tecto {erro.limite}"
        return ErroDeTool(codigo=erro.codigo, detalhe=detalhe)

    def chamar_backend(self, inv: Invocacao) -> ToolResult | None:
        """O passo 6: disjuntor, chamada, e traducao dos erros do §6.5."""
        assert inv.especificacao is not None and inv.args is not None
        especificacao = inv.especificacao
        backend = especificacao.backend
        if not self.disjuntor.permite(backend):
            return falha(
                UPSTREAM_DOWN,
                f"o disjuntor de `{backend}` esta aberto; a chamada nao foi feita",
            )
        assert especificacao.executor is not None
        pedido = Pedido(
            ctx=inv.ctx,
            args=inv.args,
            timeout_ms=self.timeout_de(especificacao.klass),
            ligacao=inv.ligacao if backend == "plataforma" else None,
            # A chave do §6.3 (KAM-029). E o que torna verdadeira a frase do
            # criterio 4 — «o backend e idempotente pela chave» —, e sem ela a
            # retoma de uma linha `falhada` duplicava o efeito em vez de o
            # reencontrar.
            chave=inv.chave,
        )
        try:
            inv.resposta = especificacao.executor(pedido)
        except ErroDeBackend as erro:
            # Um estado de negocio **nao** conta para o disjuntor: um
            # `NOT_FOUND` e o backend a responder, e um disjuntor que contasse
            # respostas abria-se com trafego normal de uma loja sem stock.
            #
            # **Mas tambem nao conta ao contrario.** A primeira versao chamava o
            # `registar_sucesso`, que **apaga** o estado: um backend a alternar
            # entre erro de negocio e *timeout* nunca abria o disjuntor, porque
            # cada resposta de negocio punha o contador a zero. «Nao conta» e
            # nao mexer, e e o que o `absolver` faz. Apanhado pela revisao.
            self.disjuntor.absolver(backend)
            return falha(erro.codigo, erro.detalhe)
        except TimeoutError as erro:
            self._contar_disjuntor(backend)
            return falha(UPSTREAM_TIMEOUT, f"`{backend}` nao respondeu: {erro}")
        except Exception as erro:  # noqa: BLE001 — qualquer outra e indisponibilidade
            self._contar_disjuntor(backend)
            return falha(UPSTREAM_DOWN, f"`{backend}` falhou: {type(erro).__name__}")
        self.disjuntor.registar_sucesso(backend)
        return None

    def timeout_de(self, klass: str) -> int:
        """2 s para `read`, 8 s para `write` e `money` (§6.5)."""
        return self._timeout_read if klass == "read" else self._timeout_escrita

    # ------------------------------------------------------------- auditoria
    def registar_se_falta(
        self, inv: Invocacao, *, resultado: ToolResult | None = None
    ) -> None:
        """Escreve a linha de `tool_audit`, uma vez por invocacao.

        Chamada duas vezes — pelo passo 7 e pelo `finally` — e escreve uma: o
        passo 7 e quem a escreve no caminho feliz, e o `finally` e quem a escreve
        quando um passo anterior recusou. A marca e `inv.registada`, e nao um
        `try/except` sobre uma unicidade: a tabela nao tem unicidade nenhuma
        (duas invocacoes iguais no mesmo turno sao duas linhas, de proposito).
        """
        if inv.registada:
            return
        especificacao = inv.especificacao
        if especificacao is None:
            # Uma tool que o catalogo nao conhece nao tem `klass`, e o `klass` e
            # `NOT NULL`. Nao ha linha possivel, e nao e uma invocacao de classe
            # `write` nem `money` — ver a *docstring* do modulo.
            inv.registada = True
            return
        if resultado is None and inv.resposta is None:
            # O pipeline levantou antes de haver desfecho. Escreve-se como erro
            # de indisponibilidade: a alternativa era nao escrever, e uma
            # invocacao que levantou a meio e precisamente a que se quer ver.
            resultado = falha(UPSTREAM_DOWN, "a invocacao levantou antes de concluir")
        if resultado is None:
            resultado = ToolResult(
                ok=True,
                data=inv.resposta.data if inv.resposta else {},
                facts=inv.resposta.facts if inv.resposta else (),
            )
        linha = auditoria.LinhaDeAuditoria(
            ctx=inv.ctx,
            tool=especificacao.nome,
            tool_version=especificacao.versao,
            klass=especificacao.klass,
            args=inv.args_crus,
            status=auditoria.STATUS_OK if resultado.ok else auditoria.STATUS_ERRO,
            latency_ms=self._latencia_de(inv),
            error=resultado.error,
            data=resultado.data if resultado.ok else None,
            facts=resultado.facts,
            idempotency_key=inv.idempotency_key,
            campos_declarados=tuple(sorted(especificacao.parametros_visiveis())),
        )
        # A marca poe-se **antes** de escrever: se a escrita levantar, o
        # `finally` nao tenta outra vez com a mesma ligacao em estado incerto —
        # o que dava duas linhas quando a primeira tinha passado e o `commit`
        # e que falhou.
        inv.registada = True
        auditoria.escrever(inv.ligacao, linha)

    # ------------------------------------------------------------- metricas
    def _contar(
        self, inv: Invocacao, resultado: ToolResult | None, latencia_ms: int
    ) -> None:
        if self._metricas is None:
            return
        if inv.especificacao is not None:
            self._metricas.contar(METRICA_TOOL_INVOCACOES, inv.especificacao.nome)
        self._metricas.medir(METRICA_TOOL_LATENCIA, latencia_ms)
        if resultado is None or resultado.error is None:
            return
        self._metricas.contar(METRICA_TOOL_ERROS, resultado.error.codigo.lower())
        if resultado.error.codigo == TENANT_MISMATCH:
            # O «gera alerta de seguranca» do critero 8. Sem etiqueta: o que um
            # painel precisa de saber e que **houve** um, e qual tool foi le-se
            # na `tool_audit`.
            self._metricas.contar(METRICA_TOOL_TENANT_MISMATCH)

    def _contar_disjuntor(self, backend: str) -> None:
        if self.disjuntor.registar_falha(backend) and self._metricas is not None:
            self._metricas.contar(METRICA_TOOL_DISJUNTOR, backend)
