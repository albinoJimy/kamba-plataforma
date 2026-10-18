"""TEN — entitlements e consumo de limites (KAM-009, criterios 2 a 5 e 7).

Espelho de `packages/core-ts/src/ten/entitlements.ts`. Duas perguntas, e
nenhuma das duas se responde aqui dentro:

    check_entitlement(bd, tenant, modulo)          pode usar o modulo?
    consume_limit(bd, tenant, chave, n, chave_id)  cabe mais n nesta chave?

A primeira responde-se com o `SQL_ENTITLEMENT`, cuja coluna `permitido` ja e a
conjuncao do criterio 2 escrita em SQL. A segunda responde-se com
`platform.ten_consumir`, da revisao `0007`. **Nenhuma linha deste ficheiro
soma, subtrai ou compara um limite**: o bloco do ticket pede «o Python chama a
mesma regra SQL», e duas implementacoes da mesma aritmetica de limites
divergem — foi o que a `0002` ja escreveu sobre a RLS.

## Atomico e idempotente porque a funcao o e

O criterio 3 pede que 1 000 chamadas paralelas de 1 unidade contra um limite de
100 aceitem exactamente 100, e o criterio 4 que repetir a mesma chave de
idempotencia nao consuma duas vezes. Nada disso se consegue em Python:
consegue-se no `ON CONFLICT ... WHERE valor + n <= limite` e na chave unica de
`usage_ledger`, que serializam no lock da linha. O que este modulo acrescenta e
**nao estragar**: uma chamada, uma transaccao, sem leitura previa e sem cache
nenhuma no caminho do consumo.

**O consumo nunca passa pela cache.** A cache e so dos entitlements; um
contador em cache era um contador errado, e um tecto decidido sobre um contador
errado deixa passar o que devia negar.

## O `tenant_id` vem do contexto

As funcoes recebem o tenant como argumento, mas quem o fornece e sempre o
contexto de quem chama — o `ToolContext` da ToolLayer (`docs/tecnica/02` §6.1),
construido «a partir de ConversaState, nunca de texto» —, e **nunca** um
argumento que o modelo possa produzir. O §5.2 do mesmo documento ja o impoe na
validacao de arranque: «nenhuma tool tem parametro `tenant_id`/`merchant_id` no
esquema visivel ao modelo». O `hook_de_tool` deste modulo recebe o contexto
inteiro e nao os `args` da tool, que e a forma de nao haver caminho nenhum.

Defesa em profundidade por cima disso: o `normalizar_tenant` do `tenant_guard`
recusa o que nao seja um UUID canonico, e a RLS de `platform.tenants`
(`id = app.tenant_id`) faz a consulta devolver zero linhas quando o contexto da
transaccao e de outro tenant — que este modulo le como negado.

## O que este modulo nao faz

* **Nao abre transaccoes.** Recebe um cliente; quem da contexto de tenant e o
  `kamba_core.tenant_guard` (`tx`).
* **Nao importa nenhum controlador.** O cliente e injectado, como no
  `kamba_core.eventos.consumo`: o `pyproject.toml` deste pacote tem
  `dependencies = []` de proposito.
* **Nao regista nada.** Nem o tenant, nem a chave, nem o erro. So conta.
* **Nao sabe precos.** Um limite e um inteiro vindo de `entitlements.limites` e
  nada aqui o interpreta como dinheiro.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..tenant_guard import normalizar_tenant
from .consultas import SQL_CONSUMIR, SQL_ENTITLEMENT, SQL_PERIODO
from .metricas import (
    METRICA_ENTITLEMENT_NEGADO,
    METRICA_LIMITE_NEGADO,
    METRICAS,
)

#: Os codigos de erro. **Os tres estao em proposta, e de maneiras diferentes.**
#:
#: `LIMIT_EXCEEDED` e o unico escrito num documento tecnico: `docs/tecnica/02`
#: §6.5, na tabela de erros tipados da ToolLayer. **Sem estado HTTP associado**
#: — o §6.5 e sobre erros de *tool*, nao sobre uma API —, pelo que o `429` do
#: lado TypeScript e proposta do ticket e nada mais.
#:
#: `ENTITLEMENT_DENIED` tambem esta no §6.5, e e o nome que a ToolLayer usa.
#:
#: `ENTITLEMENT_DISABLED` **nao esta em documento nenhum**: vem do criterio 2
#: do bloco do KAM-009, que o marca «em proposta», e nao e o mesmo nome que o
#: §6.5 escreve para a mesma situacao. Os dois ficam aqui, cada um no seu
#: caminho, e **a decisao de os unificar devolve-se ao dono do `02` §6.5**.
CODIGO_ENTITLEMENT_HTTP = "ENTITLEMENT_DISABLED"
#: O mesmo caso, no vocabulario da ToolLayer (`docs/tecnica/02` §6.5).
CODIGO_ENTITLEMENT_TOOL = "ENTITLEMENT_DENIED"
#: `docs/tecnica/02` §6.5. O unico dos tres que um documento tecnico escreve.
CODIGO_LIMITE = "LIMIT_EXCEEDED"

#: Estado HTTP de cada recusa. **Proposta**: o §6.5 nao associa nenhum.
HTTP_ENTITLEMENT = 403
#: Estado HTTP de cada recusa. **Proposta**: o §6.5 nao associa nenhum.
HTTP_LIMITE = 429

#: A gramatica de um modulo e de uma chave de limite (`CHECK` da `0001`/`0007`).
NOME_CANONICO = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

#: TTL da cache, em milissegundos. **Proposta**: o criterio 6 pede «<= 60 s».
TTL_POR_OMISSAO_MS = 60_000

#: Quantas entradas a cache guarda antes de deitar fora as mais velhas.
MAXIMO_DE_ENTRADAS = 10_000


@dataclass(frozen=True)
class Resultado:
    """O que um `executar` devolve: as linhas e quantas linhas mexeu.

    A mesma forma do `kamba_core.eventos.consumo.Resultado`, repetida de
    proposito em vez de importada: `ten` nao depende de `eventos`, e um pacote
    partilhado que se cruza consigo proprio por causa de um *dataclass* de dois
    campos ganha um ciclo e nao ganha nada.
    """

    linhas: Sequence[Mapping[str, object]] = ()
    contagem: int | None = None


class ClienteSql(Protocol):
    """O minimo de um cliente SQL: **uma** ligacao, nao um *pool*."""

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> Resultado: ...


class Metricas(Protocol):
    """O que se conta. Nenhuma etiqueta leva identificadores (`OBS-I`)."""

    def contar(self, metrica: str, etiqueta: str, quanto: int = 1) -> None: ...


class NomeInvalido(ValueError):
    """Um nome que nao casa a gramatica de `modulo` ou de `chave_limite`."""


class QuantidadeInvalida(ValueError):
    """A quantidade a consumir nao e um inteiro positivo."""


class ChaveDeIdempotenciaInvalida(ValueError):
    """A chave de idempotencia esta vazia ou nao e texto."""


class RespostaIlegivel(RuntimeError):
    """A base devolveu uma coluna com uma forma que nao se consegue ler."""


def exigir_nome(campo: str, valor: object) -> str:
    if not isinstance(valor, str) or not NOME_CANONICO.match(valor):
        raise NomeInvalido(
            f"{campo} tem de casar ^[a-z][a-z0-9_]{{1,62}}$ (recebido: "
            f"{type(valor).__name__} com {len(str(valor))} caracteres)"
        )
    return valor


def inteiro(coluna: str, valor: object) -> int:
    """Um `bigint` do PostgreSQL como inteiro.

    O `pg8000` devolve `int`; o `pg` do lado TypeScript devolve **texto**, para
    nao perder precisao acima de 2^53. Os dois passam pela mesma regra, e o que
    nao seja inteiro exacto levanta em vez de ser arredondado em silencio — um
    tecto de dinheiro arredondado e dinheiro errado (`specs/01` §6, principio
    4).

    **`bool` nao conta.** Em Python `True` e um `int`, e um `isinstance(valor,
    int)` desprevenido lia um `aceite` booleano como o numero 1.

    **Uma divergencia declarada face ao TypeScript**, a unica deste modulo: um
    inteiro acima de 2^53 e aceite aqui e **recusado** do outro lado. Nao e
    descuido — o `int` do Python e exacto e o `number` do JavaScript nao e, e
    obrigar este lado a recusar um valor que representa sem perda seria
    inventar um defeito para o espelhar. Nenhum dos dois arredonda em silencio,
    que e a propriedade que interessa. Um tecto acima de 2^53 nao existe hoje:
    o `bigint` de `entitlements.limites` chega a ~9,2 x 10^18, mas um limite de
    mensagens ou de kwanzas nessa ordem de grandeza nao e um limite.
    """
    if isinstance(valor, bool):
        raise RespostaIlegivel(
            f"a coluna {coluna} veio como bool e nao se le como inteiro"
        )
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and re.match(r"^-?\d+$", valor):
        return int(valor)
    raise RespostaIlegivel(
        f"a coluna {coluna} veio como {type(valor).__name__} e nao se consegue "
        "ler como inteiro. Um limite mal lido e um tecto errado: recusa-se em "
        "vez de adivinhar."
    )


def _booleano(valor: object) -> bool:
    """Tudo o que nao seja verdadeiro conta como falso."""
    return valor is True or valor == "t" or valor == "true"


@dataclass(frozen=True)
class Entitlement:
    """O que a base respondeu sobre um entitlement."""

    modulo: str
    permitido: bool
    #: `None` quando nao ha linha de tenant.
    estado_tenant: str | None
    ativo: bool
    #: `None` exactamente quando `permitido`. Um de `sem_tenant`,
    #: `sem_entitlement`, `entitlement_inactivo`, `estado_do_tenant`.
    motivo: str | None


@dataclass(frozen=True)
class Consumo:
    """O desfecho de um consumo, tal como `platform.ten_consumir` o devolve."""

    #: Aceite (ou repeticao de um consumo ja aceite).
    aceite: bool
    #: O uso no periodo depois desta chamada.
    valor: int
    #: Esta chamada e a repeticao de uma anterior com a mesma chave.
    repetido: bool
    #: O tecto efectivo. **`None` quando nenhum entitlement activo declara a
    #: chave** — e `None` nega, pela `0007`: «sem tecto» nao quer dizer «sem
    #: limite».
    limite: int | None
    #: `None` quando aceite. Senao, `sem_entitlement` ou `limite_excedido`.
    motivo: str | None


def agora_ms() -> float:
    """O relogio da cache, em milissegundos, **monotonico**.

    `time.monotonic()` e nao `time.time()`: o relogio de parede anda para tras
    quando o NTP o corrige, e uma entrada guardada com `expira_em` calculado
    antes de um salto de dez minutos ficava dez minutos a mais em cache — o
    criterio 6 fala de 60 s e um salto de relogio nao e desculpa. O espelho em
    TypeScript usa `performance.now()` pela mesma razao. As duas epocas sao
    diferentes e nao precisam de coincidir: cada processo so compara este
    relogio consigo proprio.
    """
    return time.monotonic() * 1000.0


class CacheDeEntitlements:
    """Cache de entitlements com TTL. **Nunca devolve dados de outro tenant.**

    ## A visibilidade e so pelo TTL, e isso tem de ficar escrito

    O criterio 6 pede que uma alteracao de entitlement seja visivel em <= 60 s.
    A forma habitual de o conseguir e invalidar por evento — e o que o `01`
    §7.2 faz com a cache do CHR, «invalidado por evento `channel.updated`».
    **Aqui nao ha evento equivalente**: o catalogo de eventos nao tem nenhum
    `entitlement.*` (verificado; os tipos existentes sao de canal, encomenda,
    pagamento, marcacao e stock). Logo a unica coisa que torna uma alteracao
    visivel e a expiracao, e o limite superior do atraso e **exactamente** o
    TTL.

    Duas consequencias que quem usa isto tem de saber: um entitlement
    **retirado** continua a permitir ate 60 s, e nao ha forma de o apressar a
    nao ser chamar `invalidar`. Criar o evento `entitlement.updated` e trabalho
    do catalogo (KAM-007) e do provisionamento (KAM-091), e fica **proposto
    aqui, nao feito**.

    ## Porque e que a chave nao pode misturar tenants

    A chave e `<uuid canonico>\\0<modulo>`. O tenant passa pelo
    `normalizar_tenant`, que so aceita a forma canonica — duas escritas do
    mesmo tenant seriam duas chaves, e uma escrita estranha podia ser
    construida para colidir com outra. O separador e `\\0`, que nem um UUID nem
    um modulo (`^[a-z][a-z0-9_]*$`) podem conter.

    O `invalidar(tenant)` apaga **so** as entradas desse tenant, pelo prefixo.

    ## Guarda-se tambem o que **negou**, e isso tem uma consequencia

    Uma recusa fica em cache como uma permissao fica. O caso a conhecer e o
    `sem_tenant`: a consulta devolve zero linhas tanto para um tenant que nao
    existe como para um pedido feito com o **contexto de RLS de outro
    tenant** — e, nesse segundo caso, a recusa guardada e consequencia de um
    defeito de quem chama e sobrevive-lhe ate 60 s. Guarda-se na mesma, por
    duas razoes: o sentido do erro e o seguro (nega-se de mais, nunca de
    menos), e nao guardar deixava um tenant inexistente a bater na base a cada
    pedido. Quem corrige o contexto chama `invalidar`.
    """

    def __init__(
        self,
        ttl_ms: float = TTL_POR_OMISSAO_MS,
        maximo: int = MAXIMO_DE_ENTRADAS,
    ) -> None:
        if not isinstance(ttl_ms, (int, float)) or ttl_ms <= 0:
            raise ValueError(f"o TTL tem de ser positivo: {ttl_ms!r}")
        if not isinstance(maximo, int) or isinstance(maximo, bool) or maximo <= 0:
            raise ValueError(f"o maximo tem de ser um inteiro positivo: {maximo!r}")
        self.ttl_ms = ttl_ms
        self.maximo = maximo
        self._trinco = threading.Lock()
        #: Ordenado por insercao, como o `Map` do TypeScript.
        self._entradas: dict[str, tuple[Entitlement, float]] = {}

    @staticmethod
    def _chave(tenant: object, modulo: object) -> str:
        return f"{normalizar_tenant(tenant)}\0{exigir_nome('modulo', modulo)}"

    def ler(
        self, tenant: object, modulo: object, agora: float | None = None
    ) -> Entitlement | None:
        """A decisao guardada, ou `None` se nao ha ou ja expirou."""
        chave = self._chave(tenant, modulo)
        instante = agora_ms() if agora is None else agora
        with self._trinco:
            entrada = self._entradas.get(chave)
            if entrada is None:
                return None
            decisao, expira_em = entrada
            if expira_em <= instante:
                del self._entradas[chave]
                return None
            return decisao

    def guardar(
        self,
        tenant: object,
        modulo: object,
        decisao: Entitlement,
        agora: float | None = None,
    ) -> None:
        chave = self._chave(tenant, modulo)
        instante = agora_ms() if agora is None else agora
        with self._trinco:
            # Primeiro as expiradas: numa cache de entitlements a maioria das
            # entradas velhas ja nao vale nada, e deitar fora uma viva para dar
            # lugar a uma nova enquanto ha mortas la dentro era pagar duas idas
            # a base por uma.
            if chave not in self._entradas and len(self._entradas) >= self.maximo:
                for existente in [
                    k for k, (_, exp) in self._entradas.items() if exp <= instante
                ]:
                    del self._entradas[existente]
            # Ainda cheia: sai a mais antiga a entrar, que e a primeira do dict.
            while chave not in self._entradas and len(self._entradas) >= self.maximo:
                del self._entradas[next(iter(self._entradas))]
            self._entradas[chave] = (decisao, instante + self.ttl_ms)

    def invalidar(self, tenant: object) -> None:
        """Esquece tudo o que e deste tenant, e so dele."""
        prefixo = f"{normalizar_tenant(tenant)}\0"
        with self._trinco:
            for chave in [k for k in self._entradas if k.startswith(prefixo)]:
                del self._entradas[chave]

    def repor(self) -> None:
        with self._trinco:
            self._entradas.clear()

    @property
    def tamanho(self) -> int:
        with self._trinco:
            return len(self._entradas)


def _montar(modulo: str, linha: Mapping[str, object]) -> Entitlement:
    """A linha da base como decisao.

    O `permitido` **vem da coluna**, e nao se recalcula: recalcular era a
    segunda implementacao da regra. O `motivo` deriva-se, e repare-se que a
    unica coisa que a derivacao sabe sobre estados e que, se o entitlement esta
    activo e mesmo assim negou, so pode ter sido o estado do tenant. A lista
    dos tres estados continua a existir num sitio so: no `SQL_ENTITLEMENT`.
    """
    permitido = _booleano(linha.get("permitido"))
    ativo = _booleano(linha.get("ativo"))
    tem_linha = _booleano(linha.get("tem_linha"))
    bruto = linha.get("estado_tenant")
    estado_tenant = bruto if isinstance(bruto, str) else None
    motivo: str | None = None
    if not permitido:
        if not tem_linha:
            motivo = "sem_entitlement"
        elif not ativo:
            motivo = "entitlement_inactivo"
        else:
            motivo = "estado_do_tenant"
    return Entitlement(
        modulo=modulo,
        permitido=permitido,
        estado_tenant=estado_tenant,
        ativo=ativo,
        motivo=motivo,
    )


def check_entitlement(
    bd: ClienteSql,
    tenant: object,
    modulo: object,
    *,
    cache: CacheDeEntitlements | None = None,
    metricas: Metricas | None = None,
) -> Entitlement:
    """O entitlement de um modulo para um tenant. **Falha fechada** (criterio 2).

    Nega quando nao ha linha, quando `ativo = false` e quando o tenant esta
    `onboarding`, `suspenso` ou `encerrado` — e a lista dos tres estados vive
    no `SQL_ENTITLEMENT`, nao aqui, para que o TypeScript nao possa ter outra.

    Conta `ten_entitlement_denied_total{modulo}` em **cada** recusa, incluindo
    as que vem da cache: o que o painel mostra e quantos acessos foram negados,
    e nao quantas vezes a base foi consultada.
    """
    canonico = normalizar_tenant(tenant)
    nome = exigir_nome("modulo", modulo)
    contador = METRICAS if metricas is None else metricas

    if cache is not None:
        em_cache = cache.ler(canonico, nome)
        if em_cache is not None:
            if not em_cache.permitido:
                contador.contar(METRICA_ENTITLEMENT_NEGADO, nome)
            return em_cache

    resultado = bd.executar(SQL_ENTITLEMENT, (canonico, nome))
    linhas = list(resultado.linhas)
    if linhas:
        decisao = _montar(nome, linhas[0])
    else:
        decisao = Entitlement(
            modulo=nome,
            permitido=False,
            estado_tenant=None,
            ativo=False,
            motivo="sem_tenant",
        )

    if cache is not None:
        cache.guardar(canonico, nome, decisao)
    if not decisao.permitido:
        contador.contar(METRICA_ENTITLEMENT_NEGADO, nome)
    return decisao


def consume_limit(
    bd: ClienteSql,
    tenant: object,
    chave: object,
    quantidade: object,
    idempotency_key: object,
    *,
    limite: int | None = None,
    agora: object | None = None,
    modulo: str | None = None,
    metricas: Metricas | None = None,
) -> Consumo:
    """Consome `quantidade` da chave, atomica e idempotentemente.

    Uma unica chamada a `platform.ten_consumir`. Sem leitura previa: entre um
    `SELECT` e um `INSERT` cabe a chamada repetida inteira, e e por isso que a
    `0007` escreve a chave de idempotencia **antes** de contar.

    O `limite` opcional e o tecto de quem chama, e so **desce**: a `0007` faz
    `least` com o do plano. Serve um tecto de confianca (`EPIC-09`) mais
    apertado, nunca um mais largo — passar um limite alto nao abre nada.

    O `agora` opcional existe para o criterio 5: com relogio fixo em
    `2026-11-30T23:59:59+01:00` o consumo conta para Novembro e em
    `2026-12-01T00:00:00+01:00` para Dezembro. Quem decide isso e
    `platform.ten_periodo`, em `Africa/Luanda`; aqui so se passa o instante.

    Conta `ten_limit_denied_total{key}` quando o tecto recusa. Uma recusa por
    **falta** de entitlement conta em `ten_entitlement_denied_total{modulo}`
    apenas se quem chama passar o `modulo`: a funcao SQL nao o sabe, porque o
    tecto e o minimo entre os modulos que declaram a chave.
    """
    canonico = normalizar_tenant(tenant)
    nome = exigir_nome("chave", chave)
    if (
        not isinstance(quantidade, int)
        or isinstance(quantidade, bool)
        or quantidade <= 0
    ):
        raise QuantidadeInvalida(
            f"a quantidade tem de ser um inteiro positivo, veio {quantidade!r}. "
            "A mesma recusa existe em `platform.ten_consumir`; esta poupa a ida "
            "a base."
        )
    if not isinstance(idempotency_key, str) or idempotency_key.strip() == "":
        raise ChaveDeIdempotenciaInvalida(
            "a chave de idempotencia tem de ser texto nao vazio: e ela que "
            "torna a repeticao segura (`usage_ledger`, criterio 4). A mensagem "
            "nao repete o valor."
        )
    if limite is not None and (
        not isinstance(limite, int) or isinstance(limite, bool) or limite < 0
    ):
        raise QuantidadeInvalida(
            f"o tecto de quem chama tem de ser um inteiro >= 0, veio {limite!r}"
        )
    contador = METRICAS if metricas is None else metricas

    resultado = bd.executar(
        SQL_CONSUMIR,
        (canonico, nome, quantidade, idempotency_key, limite, agora),
    )
    linhas = list(resultado.linhas)
    if not linhas:
        # `ten_consumir` devolve sempre uma linha. Zero linhas significa que a
        # chamada nao chegou a funcao — e tratar isso como «aceite» seria
        # consumir sem contar.
        raise RespostaIlegivel(
            "platform.ten_consumir devolveu zero linhas: a chamada nao chegou a "
            "funcao, e um consumo que nao se sabe se aconteceu nao se aceita."
        )
    linha = linhas[0]
    aceite = _booleano(linha.get("aceite"))
    bruto = linha.get("limite")
    tecto = None if bruto is None else inteiro("limite", bruto)
    if aceite:
        motivo = None
    elif tecto is None:
        motivo = "sem_entitlement"
    else:
        motivo = "limite_excedido"
    consumo = Consumo(
        aceite=aceite,
        valor=inteiro("valor", linha.get("valor")),
        repetido=_booleano(linha.get("repetido")),
        limite=tecto,
        motivo=motivo,
    )
    if motivo == "limite_excedido":
        contador.contar(METRICA_LIMITE_NEGADO, nome)
    elif motivo == "sem_entitlement" and modulo is not None:
        contador.contar(METRICA_ENTITLEMENT_NEGADO, exigir_nome("modulo", modulo))
    return consumo


def periodo(bd: ClienteSql, agora: object | None = None) -> object:
    """O periodo de um instante, perguntado a base.

    Nao decide nada — a `ten_consumir` chama a mesma funcao la dentro. Existe
    para quem precisa de **mostrar** o periodo e para os testes de fronteira de
    mes poderem perguntar a base o que ela conta, em vez de o reescreverem.
    """
    resultado = bd.executar(SQL_PERIODO, (agora,))
    linhas = list(resultado.linhas)
    if not linhas or "periodo" not in linhas[0]:
        raise RespostaIlegivel("platform.ten_periodo nao devolveu `periodo`")
    return linhas[0]["periodo"]
