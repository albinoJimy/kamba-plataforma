"""A porta de destinos sobre `tenant_destinations` (KAM-069, ADR-008).

O ADR-008 diz: nenhum dado pessoal de producao sai de Angola sem a notificacao
ou a autorizacao da APD aplicavel. Este modulo e a barreira que o impoe, e e
a implementacao da `PortaDeDestinos` que o KAM-030 declarou e deixou com credor.

## Fica no nucleo partilhado e nao no AGR, e a razao esta no criterio 4

Ele nomeia **sete** pontos de invocacao — LLM, STT, *embeddings*, copias de
seguranca, CDN, observabilidade e e-mail/SMS — e **um** deles e o *gateway* de
modelos. Uma porta que vivesse no AGR obrigava os outros seis a importar o AGR
ou a escrever a sua propria, e a segunda hipotese e a que esta casa paga caro:
duas leituras da mesma tabela que discordam no dia em que uma delas mudar.

## A regra, por extenso, porque nenhuma linha dela e obvia

Para um pedido `(tenant, fornecedor, finalidade)`:

1. **Se a finalidade nao esta no dominio, nega.** Nao e zelo: a coluna `purpose`
   da `0036` tem `CHECK` fechado com catorze valores desde a revisao
   `foto_de_produtos` (KAM-120), pelo que uma finalidade fora
   deles **nao tem linha onde caiba** — a consulta devolveria sempre vazio, e um
   erro do chamador lia-se como «destino nao registado».
2. **Se o tenant tem linha propria para esse par, so as dele contam.** As
   globais sao a configuracao de infra-estrutura; uma decisao especifica do
   tenant tapa-a. Sem esta precedencia, um tenant com o destino **negado** por
   decisao propria passava pela linha global `autorizado`, que e o inverso do
   que uma decisao especifica significa.
3. **Sem linha nenhuma, nega.** A ausencia de registo e a ausencia de
   autorizacao, e e o «por defeito negado» do `docs/tecnica/08` §8.3.1.
4. **Com linhas, exige que TODAS estejam `autorizado` com `apd_ref`.** Nao
   «alguma»: a chamada nao escolhe o pais, e um fornecedor registado com dois
   paises — `ZA` autorizado e `US` `pendente` — pode servir de qualquer um
   deles. E a mesma razao pela qual o §3.29 do dicionario fixa que o *gate*
   corre «para **todos** os fornecedores do alias»: falha fechada sobre a
   **uniao**, nao sobre a escolha.
5. **Erro da base, resposta ilegivel ou coluna em falta, nega** — e **nao
   guarda em *cache***. Uma indisponibilidade nao e uma politica, e grava-la por
   60 s transformava um blip da base num corte de servico com a duracao do TTL.

**Nenhum passo olha para o pais.** Nao ha lista de paises adequados em codigo
nenhum, e isto nao e uma omissao a corrigir: a lista nao existe publicamente
(NAO VERIFICADO, `docs/tecnica/08` §8.3.1), a UE e a Africa do Sul sao hipoteses
e os EUA provavelmente exigem autorizacao. O `country` sai da consulta **so para
a mensagem de recusa** — dizer «`openai` em `US` esta `pendente`» e accionavel e
dizer «o destino nao esta autorizado» nao e.

## A *cache* e o criterio 3, e o TTL e o unico mecanismo

O criterio 3 pede que revogar um destino faca a chamada seguinte falhar em
<= 60 s. A forma habitual de o conseguir e invalidar por evento; **aqui nao ha
evento equivalente** — o catalogo nao tem nenhum `destino.*` —, pelo que a unica
coisa que torna uma revogacao visivel e a expiracao, e o limite superior do
atraso e **exactamente** o TTL. E a mesma situacao da `CacheDeEntitlements`, e a
nota dela diz o mesmo com outras palavras.

Duas consequencias que quem usa isto tem de saber:

* um destino **revogado** continua a autorizar ate 60 s, e a unica forma de o
  apressar e chamar `invalidar`;
* uma recusa fica em *cache* como uma autorizacao fica, **excepto** a que vem de
  um erro da base. Guardar recusas e o lado seguro — nega-se de mais, nunca de
  menos — e evita que um destino por registar bata na base a cada turno.

## O que este modulo nao faz

Nao escreve. Autorizar um destino e um acto humano com papelada arquivada —
contrato, retencao zero, nao-treino, numero de procedimento da APD — e a `0036`
nao da `INSERT` ao `kamba_app` por isso mesmo. Nao decide quem e subprocessador:
isso e o `gov/subprocessadores.yaml`, e escolher um em codigo e exactamente o
que o ADR-008 existe para impedir. E nao sabe que existe um modelo do outro
lado: quem traduz a recusa para o `DestinoNegado` do *gateway* e o adaptador do
AGR.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from ..tenant_guard import normalizar_tenant

#: As **catorze** finalidades de transferencia, por ordem alfabetica: as treze
#: da `0036` e a `imagem`, que a revisao `foto_de_produtos` (KAM-120) acrescenta.
#:
#: **E o dominio de `platform.tenant_destinations.purpose`**, e a lista vive
#: aqui e no `CHECK` da revisao `0036`; o `test_dominio_de_purpose_bate_com_o_codigo`
#: de `db/tests/test_destinos_schema.py` confronta as duas contra a base real.
#: Lista fechada: uma finalidade nova e uma revisao de base de dados, nao uma
#: constante — pela licao que a `0022` pagou.
#:
#: Tres delas estao tambem em `FINALIDADES`, no
#: `services/agr/src/kamba_agr/llm/destinos.py` (KAM-030), que e onde viveram
#: enquanto esta coluna nao existia; o `otp_e_avisos_de_servico` esta em
#: `packages/core-ts/src/sms/fornecedor.ts` (KAM-116).
FINALIDADE_ALOJAMENTO: Final = "alojamento"
FINALIDADE_CANAL: Final = "canal"
FINALIDADE_CONVERSA: Final = "conversa"
FINALIDADE_COPIAS: Final = "copias_de_seguranca"
FINALIDADE_EMBEDDINGS: Final = "embeddings"
FINALIDADE_ENTREGA: Final = "entrega_de_conteudo"
FINALIDADE_FACTURACAO: Final = "facturacao"
FINALIDADE_IMAGEM: Final = "imagem"
FINALIDADE_OBSERVABILIDADE: Final = "observabilidade"
FINALIDADE_OTP: Final = "otp_e_avisos_de_servico"
FINALIDADE_PAGAMENTOS: Final = "pagamentos"
FINALIDADE_SEGREDOS: Final = "segredos"
FINALIDADE_TRANSCRICAO: Final = "transcricao"
FINALIDADE_VISAO: Final = "visao"

FINALIDADES: Final = (
    FINALIDADE_ALOJAMENTO,
    FINALIDADE_CANAL,
    FINALIDADE_CONVERSA,
    FINALIDADE_COPIAS,
    FINALIDADE_EMBEDDINGS,
    FINALIDADE_ENTREGA,
    FINALIDADE_FACTURACAO,
    FINALIDADE_IMAGEM,
    FINALIDADE_OBSERVABILIDADE,
    FINALIDADE_OTP,
    FINALIDADE_PAGAMENTOS,
    FINALIDADE_SEGREDOS,
    FINALIDADE_TRANSCRICAO,
    FINALIDADE_VISAO,
)

#: Os **quatro** estados de um destino, da revisao `0036`. Mesma confrontacao
#: contra a base que as finalidades.
ESTADO_PENDENTE: Final = "pendente"
ESTADO_AUTORIZADO: Final = "autorizado"
ESTADO_REVOGADO: Final = "revogado"
ESTADO_NEGADO: Final = "negado"

ESTADOS: Final = (ESTADO_PENDENTE, ESTADO_AUTORIZADO, ESTADO_REVOGADO, ESTADO_NEGADO)

#: O tecto do criterio 3, em milissegundos. **E o limite superior do atraso de
#: uma revogacao**, e nao um numero de desempenho — ver a nota do modulo.
TTL_POR_OMISSAO_MS: Final = 60_000

#: O mesmo tecto de entradas da `CacheDeEntitlements`, e pela mesma razao: uma
#: *cache* sem tecto e uma fuga de memoria com o nome trocado.
MAXIMO_DE_ENTRADAS: Final = 10_000


class LeitorDeDestinos(Protocol):
    """Quem le as linhas aplicaveis a um pedido.

    **Nao e um `ClienteSql` com `executar(sql, parametros)`**, e a diferenca e
    de desenho e nao de gosto. Esta consulta corre **sob o contexto de RLS do
    tenant** — sem ele a politica `tenant_iso` da `0036` nao devolve as linhas
    especificas e so as globais aparecem, pelo que um tenant com decisao propria
    caia em silencio na configuracao global, que e exactamente a precedencia que
    o passo 2 existe para impor. Um protocolo de SQL generico nao tem onde
    receber o tenant, e a versao que o lia de `parametros[0]` punha a correccao
    da RLS a depender da ordem dos argumentos de uma cadeia de texto.

    Com um leitor por pedido, quem o implementa traz consigo a disciplina de
    ligacao que ja tem — no AGR, uma ligacao por chamada dentro de
    `tenant_guard.tx`, que e o que o `registo.py` do KAM-030 faz — e o
    `kamba_core.destinos.dbapi` oferece a implementacao pronta.
    """

    def __call__(
        self, tenant: str, fornecedor: str, finalidade: str
    ) -> Sequence[Mapping[str, object]]: ...


class TransferenciaNegada(RuntimeError):
    """A porta nao autoriza. **Nao e o `DestinoNegado` do *gateway*.**

    Sao camadas diferentes, e o dicionario §3.49 escreve-o: o `DestinoNegado` e
    um `ErroDeLlm` — o contrato entre o grafo e o **modelo**, que degrada com
    motivo `destino_negado` e nao conta no disjuntor — e este e a recusa da
    porta, que nao sabe que existe um modelo do outro lado. Quem traduz um no
    outro e o adaptador do AGR, e e por isso que a mecanica de degradacao do
    §3.35 nao muda.

    O `TransferDenied` do bloco do KAM-069 e este conceito escrito em ingles no
    texto de um ticket, como o `assertDestinationAllowed`, e tambem nao e uma
    variante.
    """


class FinalidadeDesconhecida(TransferenciaNegada):
    """Uma finalidade fora do dominio da `0036`.

    **Subclasse de `TransferenciaNegada` e nao um `ValueError`**, e isso e
    decisao: e um erro do chamador, mas o efeito tem de ser o mesmo — nao sair
    nada. Um `ValueError` a subir por um caminho que apanha `TransferenciaNegada`
    escapava a barreira, e a barreira e o unico ponto deste modulo.
    """


@dataclass(frozen=True)
class Decisao:
    """A decisao sobre um par (fornecedor, finalidade), e a razao dela.

    Guarda-se em *cache* inteira — a razao incluida — porque a mensagem de
    recusa e o que torna o `destino_negado` diagnosticavel: sem ela, as cinco
    maneiras de negar produziam o mesmo texto.
    """

    #: `True` so quando **todas** as linhas aplicaveis estao autorizadas.
    autorizado: bool
    #: `None` quando autorizado. Senao, uma frase accionavel.
    motivo: str | None


def agora_ms() -> float:
    """O relogio da *cache*, em milissegundos, **monotonico**.

    `time.monotonic()` e nao `time.time()`, pela razao que o `agora_ms` do `ten`
    escreve: o relogio de parede anda para tras quando o NTP o corrige, e uma
    entrada guardada antes de um salto de dez minutos ficava dez minutos a mais
    em *cache*. O criterio 3 fala de 60 s e um salto de relogio nao e desculpa.
    """
    return time.monotonic() * 1000.0


class CacheDeDestinos:
    """*Cache* de decisoes com TTL. **Nunca devolve a decisao de outro tenant.**

    A chave e `<uuid canonico>\\0<fornecedor>\\0<finalidade>`. O tenant passa
    pelo `normalizar_tenant`, que so aceita a forma canonica — duas escritas do
    mesmo tenant seriam duas chaves, e uma escrita estranha podia ser construida
    para colidir com outra. O separador e `\\0`, que nem um UUID, nem um
    fornecedor (`^[a-z][a-z0-9_-]{1,62}$` na `0036`) nem uma finalidade do
    dominio podem conter.
    """

    def __init__(
        self,
        ttl_ms: float = TTL_POR_OMISSAO_MS,
        maximo: int = MAXIMO_DE_ENTRADAS,
    ) -> None:
        if not isinstance(ttl_ms, (int, float)) or isinstance(ttl_ms, bool):
            raise ValueError(f"o TTL tem de ser um numero: {ttl_ms!r}")
        if ttl_ms <= 0:
            raise ValueError(f"o TTL tem de ser positivo: {ttl_ms!r}")
        # **O tecto do criterio 3 e um maximo e nao uma sugestao.** Um TTL acima
        # de 60 s punha uma revogacao a demorar mais do que o criterio permite, e
        # um ficheiro de configuracao com um zero a mais era a forma natural de o
        # fazer sem ninguem dar por isso.
        if ttl_ms > TTL_POR_OMISSAO_MS:
            raise ValueError(
                f"o TTL de {ttl_ms!r} ms excede o tecto de "
                f"{TTL_POR_OMISSAO_MS} ms do criterio 3 do KAM-069: uma "
                "revogacao tem de ser visivel em <= 60 s"
            )
        if not isinstance(maximo, int) or isinstance(maximo, bool) or maximo <= 0:
            raise ValueError(f"o maximo tem de ser um inteiro positivo: {maximo!r}")
        self.ttl_ms = ttl_ms
        self.maximo = maximo
        self._trinco = threading.Lock()
        #: Ordenado por insercao, como o `Map` do TypeScript.
        self._entradas: dict[str, tuple[Decisao, float]] = {}

    @staticmethod
    def _chave(tenant: object, fornecedor: str, finalidade: str) -> str:
        return f"{normalizar_tenant(tenant)}\0{fornecedor}\0{finalidade}"

    def ler(
        self,
        tenant: object,
        fornecedor: str,
        finalidade: str,
        agora: float | None = None,
    ) -> Decisao | None:
        """A decisao guardada, ou `None` se nao ha ou ja expirou."""
        chave = self._chave(tenant, fornecedor, finalidade)
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
        fornecedor: str,
        finalidade: str,
        decisao: Decisao,
        agora: float | None = None,
    ) -> None:
        chave = self._chave(tenant, fornecedor, finalidade)
        instante = agora_ms() if agora is None else agora
        with self._trinco:
            # Primeiro as expiradas, como na `CacheDeEntitlements`: deitar fora
            # uma viva para dar lugar a uma nova enquanto ha mortas la dentro
            # era pagar duas idas a base por uma.
            if chave not in self._entradas and len(self._entradas) >= self.maximo:
                for existente in [
                    k for k, (_, exp) in self._entradas.items() if exp <= instante
                ]:
                    del self._entradas[existente]
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


def _texto(linha: Mapping[str, object], coluna: str) -> str:
    """Uma coluna de texto, ou levanta. Uma resposta ilegivel **nega**."""
    valor = linha.get(coluna)
    if not isinstance(valor, str) or valor == "":
        raise TransferenciaNegada(
            f"a coluna `{coluna}` de `platform.tenant_destinations` veio "
            f"{type(valor).__name__} e nao texto: resposta ilegivel, e uma "
            "resposta que nao se le nao autoriza nada (ADR-008)"
        )
    return valor


def _booleano(linha: Mapping[str, object], coluna: str) -> bool:
    """Uma coluna booleana, ou levanta. **Nao usa `bool(...)`.**

    `bool("false")` e `True`, e uma ligacao que devolvesse o booleano como texto
    punha um destino sem `apd_ref` a passar. Exige o tipo.
    """
    valor = linha.get(coluna)
    if not isinstance(valor, bool):
        raise TransferenciaNegada(
            f"a coluna `{coluna}` de `platform.tenant_destinations` veio "
            f"{type(valor).__name__} e nao booleano: resposta ilegivel, e uma "
            "resposta que nao se le nao autoriza nada (ADR-008)"
        )
    return valor


def estado_bloqueia(status: str) -> bool:
    """`True` para tudo o que nao seja `autorizado`, **incluindo o desconhecido**.

    Nao e `status in (PENDENTE, REVOGADO, NEGADO)`, e a diferenca e a que conta:
    um valor que o `CHECK` da `0036` ainda nao conheca — porque uma revisao
    futura o acrescentou e esta versao do codigo nao o sabe — cairia fora dessa
    lista e **autorizava**. A pergunta e «e `autorizado`?», e a resposta a
    qualquer outra coisa e nao.
    """
    return status != ESTADO_AUTORIZADO


def _tenant_ou_nega(tenant_id: object) -> str:
    """O tenant canonico, ou `TransferenciaNegada`.

    O `normalizar_tenant` levanta `ContextoEmFalta` ou `TenantInvalido`, e
    nenhum dos dois e `TransferenciaNegada` — pelo que escapavam ao `except` do
    chamador. O efeito continuava a ser fechado (nada sai), mas pelo caminho
    errado: no AGR, em vez de degradar com motivo `destino_negado`, o turno
    rebentava. Sem tenant identificavel nao se sabe de quem sao os destinos a
    ler, e isso e uma recusa como as outras.
    """
    try:
        return normalizar_tenant(tenant_id)
    except Exception as erro:  # noqa: BLE001 — falha fechada, e por desenho
        raise TransferenciaNegada(
            f"sem tenant identificavel ({type(erro).__name__}): nao se sabe "
            "que linhas de `platform.tenant_destinations` ler, e sem isso nao "
            "se autoriza a transferencia (falha fechada, ADR-008, KAM-069)"
        ) from erro


def avaliar_destino(
    linhas: Sequence[Mapping[str, object]], fornecedor: str, finalidade: str
) -> Decisao:
    """A regra dos cinco passos, sobre as linhas que a consulta devolveu.

    Funcao e nao metodo, e pura: e o unico sitio onde a decisao se toma, pelo que
    e tambem o unico sitio que a prova por mutacao tem de atingir. Um teste que
    a exercite nao precisa de base nenhuma.
    """
    especificas = []
    globais = []
    for linha in linhas:
        destino = (
            _texto(linha, "status"),
            _booleano(linha, "tem_apd_ref"),
            _texto(linha, "country"),
        )
        if _booleano(linha, "especifica"):
            especificas.append(destino)
        else:
            globais.append(destino)

    # Passo 2: uma decisao propria do tenant tapa a configuracao global. Ver a
    # nota do modulo — sem isto, um destino **negado** por decisao do tenant
    # passava pela linha global `autorizado`.
    aplicaveis = especificas or globais
    ambito = "do tenant" if especificas else "global"

    # Passo 3.
    if not aplicaveis:
        return Decisao(
            autorizado=False,
            motivo=(
                f"nao ha linha de `platform.tenant_destinations` para "
                f"`{fornecedor}` com finalidade `{finalidade}`: a ausencia de "
                "registo e a ausencia de autorizacao (ADR-008, KAM-069)"
            ),
        )

    # Passo 4: **todas**, nao alguma. Ver a nota do modulo.
    #
    # O ramo «`autorizado` sem `apd_ref`» e inalcancavel **atraves desta base**:
    # o `tenant_destinations_autorizado_com_apd_ref_ck` da `0036` recusa a linha.
    # Fica, e nao e codigo morto: o criterio 2 pede que a porta negue «quando o
    # estado e `pendente`, `revogado` ou `negado`» e o criterio 1 que o
    # `apd_ref` seja exigido — se a barreira da base caisse numa revisao futura,
    # esta linha e a que mantem a propriedade. Defesa em profundidade, e com a
    # razao escrita para ninguem a apagar por parecer morta.
    faltas = [
        f"`{pais}` esta `{status}`"
        if estado_bloqueia(status)
        else f"`{pais}` esta `{status}` sem `apd_ref`"
        for status, tem_apd_ref, pais in aplicaveis
        if estado_bloqueia(status) or not tem_apd_ref
    ]
    if faltas:
        return Decisao(
            autorizado=False,
            motivo=(
                f"transferencia para `{fornecedor}` com finalidade "
                f"`{finalidade}` recusada: no registo {ambito}, "
                f"{'; '.join(faltas)}. So `{ESTADO_AUTORIZADO}` com `apd_ref` "
                "liberta uma chamada (ADR-008, KAM-069)"
            ),
        )
    return Decisao(autorizado=True, motivo=None)


class PortaSobreDestinos:
    """A `PortaDeDestinos` do §3.29 sobre `platform.tenant_destinations`.

    A assinatura e a que o KAM-030 declarou — `autorizar(tenant_id, fornecedor,
    finalidade)`, que **levanta** em vez de devolver — e nao uma nossa: trocar a
    implementacao nao muda nada no chamador, que e o que o `destinos.py` do AGR
    prometeu por escrito.

    **O `relogio` e uma costura de ensaio e nao uma opcao de configuracao.** A
    omissao e o `agora_ms`, monotonico, e nenhum chamador de producao o passa; o
    que ele torna possivel e medir a expiracao da *cache* **atraves da porta**,
    que e a segunda metade do criterio 3. Ver a nota do `decidir`.
    """

    #: Para a mensagem de arranque e para o registo. Nunca um segredo.
    nome = "tenant-destinations"

    def __init__(
        self,
        ler: LeitorDeDestinos,
        cache: CacheDeDestinos | None = None,
        relogio: Callable[[], float] = agora_ms,
    ) -> None:
        self._ler = ler
        self._cache = cache if cache is not None else CacheDeDestinos()
        self._relogio = relogio

    @property
    def cache(self) -> CacheDeDestinos:
        """Para quem precisa de `invalidar` — ver a nota do modulo."""
        return self._cache

    def decidir(self, tenant_id: object, fornecedor: str, finalidade: str) -> Decisao:
        """A decisao, sem levantar. **Nao e a porta**: a porta e o `autorizar`.

        Existe porque o *gate* de go-live precisa de **listar** o que falta e
        nao de parar no primeiro, e porque um teste que queira ver a razao nao
        tem de a extrair de uma mensagem de excepcao.
        """
        # Passo 1. Antes de tocar na base: uma finalidade fora do dominio nao
        # tem linha onde caiba, e a consulta devolveria sempre vazio.
        if finalidade not in FINALIDADES:
            raise FinalidadeDesconhecida(
                f"finalidade `{finalidade}` fora do dominio de "
                f"`tenant_destinations.purpose` (revisoes `0036` e `foto_de_produtos`, "
                "catorze valores): "
                "nao ha linha onde ela caiba, e um erro de quem chama nao se "
                "pode ler como «destino nao registado» (KAM-069)"
            )
        tenant = _tenant_ou_nega(tenant_id)
        # **O instante le-se uma vez e passa para a *cache*.** Sem esta costura
        # nao havia como medir a expiracao **atraves da porta**: a `ler` e a
        # `guardar` usavam cada uma o seu `agora_ms()`, e um ensaio que a
        # quisesse exercitar so podia chamar `repor()` — que esvazia o
        # dicionario e **nao e o que o TTL faz**. A revisao adversarial mediu-o:
        # mutando a `ler` para ignorar a expiracao no caminho da porta, os 44
        # ensaios ficavam **verdes**, isto e, uma porta que guardasse uma
        # autorizacao revogada para sempre era indistinguivel desta.
        #
        # Le-se **uma** vez por decisao, e nao duas: com duas leituras, uma
        # entrada guardada podia expirar entre a leitura e a escrita e o TTL
        # efectivo deixava de ser o declarado.
        instante = self._relogio()
        guardada = self._cache.ler(tenant, fornecedor, finalidade, agora=instante)
        if guardada is not None:
            return guardada
        try:
            linhas = list(self._ler(tenant, fornecedor, finalidade))
        except TransferenciaNegada:
            raise
        except Exception as erro:  # noqa: BLE001 — falha fechada, e por desenho
            # Passo 5: **nao se guarda**. Uma indisponibilidade da base nao e uma
            # politica, e grava-la por 60 s transformava um blip num corte de
            # servico com a duracao do TTL.
            #
            # A mensagem leva a **classe** do erro e nunca o texto dele: uma
            # mensagem de driver pode trazer a cadeia de ligacao, e esta sobe
            # para um registo.
            raise TransferenciaNegada(
                f"nao se conseguiu ler `platform.tenant_destinations` "
                f"({type(erro).__name__}): sem poder verificar o destino nao se "
                "autoriza a transferencia (falha fechada, ADR-008, KAM-069)"
            ) from erro
        decisao = avaliar_destino(linhas, fornecedor, finalidade)
        self._cache.guardar(tenant, fornecedor, finalidade, decisao, agora=instante)
        return decisao

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        """Nao devolve nada; **levanta** `TransferenciaNegada` se nao autorizar."""
        decisao = self.decidir(tenant_id, fornecedor, finalidade)
        if decisao.autorizado:
            return
        raise TransferenciaNegada(decisao.motivo or "destino nao autorizado")
