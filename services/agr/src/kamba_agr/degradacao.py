"""O detector de degradacao do AGR (KAM-037, `docs/tecnica/02` §14).

«Degradar, nunca calar» (principio 12 do `docs/tecnica/00`): uma falha de LLM,
de canal ou de pagamento tem *fallback* deterministico ou fila. Este modulo
decide **quando** se degrada, **porque**, e e quem conta o `degraded_turns`.

## O que **nao** e degradacao, e a linha e a mais importante deste ficheiro

O bloco do ticket escreve-o por extenso: «Postgres/checkpointer indisponivel
**nao** e degradacao: o turno nao corre e a mensagem permanece na fila (alerta
critico)». Por isso este detector so reconhece **duas** familias de sinal:

* um `ErroDeLlm` (`llm/erros.py`), que e uma falha do **modelo**;
* os dois sinais de carga do `admissao.py` — tecto do *tenant* cheio e fila
  acima do limiar de contrapressao.

Qualquer outra excepcao **sobe**, e subir e o comportamento correcto: o
`ExecutorDeTurnos` conta `agr_turns_total{outcome="falhou"}`, o
`/internal/turn` responde 503 com `Retry-After` e o *job* volta a fila. Degradar
ali era responder **sem estado** — sem carrinho, sem `stage`, sem janela de
mensagens —, que e o oposto do que o modo deterministico existe para fazer. Nao
ha `except Exception` neste modulo, e a ausencia e o desenho.

## Os cinco motivos, e porque e que um deles mudou de nome

O criterio 6 nomeia-os `timeout`, `429`, `budget`, `breaker` e `backpressure`.
Quatro passam como estao; o **`429` nao pode ser etiqueta de metrica**, e a
razao e medida e nao estilistica: a gramatica de etiqueta do `metricas.py` e
`^[a-z][a-z0-9_]{1,62}$` (regra `OBS-I` de `docs/seguranca/ameacas_stride.md`,
imposta pela forma e nao por lista de proibidos), e `429` comeca por digito —
`METRICAS.contar(..., "429")` levanta `EtiquetaInvalida`. O nome canonico e
`http_429`, que diz a mesma coisa e casa a gramatica. Fica na secção de
verificacao do bloco, porque e uma divergencia entre a letra do criterio e uma
barreira que ja existia.

## Os limiares do disjuntor foram **medidos**, nao copiados

O bloco da-os como «a validar na versao fixada»: `allowed_fails: 3`,
`cooldown_time: 30`. Medidos na configuracao real do proxy — `llm/litellm.config.yaml`
§`router_settings` (linhas 55-56) e `llm/aliases.yaml` §`router_settings`
(linhas 43-45), os dois com `allowed_fails: 3` e `cooldown_time: 30` — e
**CONFIRMADOS** contra a imagem fixada pelo KAM-030
(`docs/evidencia/KAM-030-litellm.md` §4: `Router(num_retries=1, allowed_fails=3,
cooldown_time=30)` aceita os tres e os tres ficam efectivos). **Nao divergem**,
e e por isso que as constantes abaixo nao sao numeros novos: sao os do proxy,
com o ficheiro onde se leem escrito ao lado.

## Dois disjuntores para o mesmo backend, e porque e que **este** nao e o que o
## `llm/cliente.py` recusou

O cabecalho do `llm/cliente.py` recusa «o cliente a fazer o *fallback*,
consultando o *gate* a cada tentativa», porque isso «punha o cliente a
reimplementar o que o router faz (contagem de falhas, *cooldown* de 30 s,
`allowed_fails`)». A recusa e sobre **escolher fornecedor** — e continua de pe:
nada aqui escolhe fornecedor nenhum.

O que este disjuntor decide e outra pergunta, e e uma que o proxy nao pode
responder: **vale a pena chamar o LLM neste turno?** O proxy em *cooldown*
responde depressa e com erro, e tres turnos seguidos a pagar esse erro sao tres
clientes a esperar por nada. Abrir aqui poupa a ida; os limiares sao os mesmos
de proposito, para que os dois nao discordem sobre quando o modelo esta em
baixo.

## O alerta e uma **proposta**, e o limiar diz-se

«Alerta quando > 5% dos turnos de um *tenant* em 15 min» — o proprio criterio
escreve «limiar *proposta*». Fica aqui como constante nomeada e injectavel, e
quem o calibra e o KAM-084, com os outros cinco tectos do `admissao.py`.

**A proporcao e por *tenant* e vive em memoria, nao na metrica.** A convencao do
conjunto e que `tenant_id` nunca entra em etiqueta (`OBS-I`), e o `metricas.py`
impoe-a pela gramatica — um UUID tem hifenes e nao casa. A metrica leva o
`motivo`, que e lista fechada de cinco; a desagregacao por *tenant* e esta
janela deslizante, que e onde ela tem significado. E a mesma leitura que o
KAM-030 fez para o §13.4, o KAM-032 para o criterio 8 e a divida 54 para o
`meta_cost_usd_total{tenant}`.

**Por processo e nao por replica**, e fica dito: duas replicas do AGR tem duas
janelas e cada uma alerta sobre o que viu. Fechar isso pedia estado partilhado
— Redis ou uma tabela — para um alerta cujo limiar e *proposta*; o que se perde
e sensibilidade (um *tenant* repartido por duas replicas chega ao limiar mais
tarde em cada uma), e nao correccao. Escrito no runbook
(`docs/runbooks/degradacao-do-agr.md`).
"""

from __future__ import annotations

import collections
import threading
import time
from collections.abc import Callable
from typing import Any, Final

from .llm.erros import (
    RESULTADO_BUDGET,
    RESULTADO_DESTINO,
    RESULTADO_TIMEOUT,
    ErroDeLlm,
    FalhaDeMinimizacao,
)
from .metricas import (
    METRICA_DEGRADACAO_ALERTA,
    METRICA_DEGRADADOS,
    METRICA_DEGRADADOS_ACIMA,
    METRICAS,
)
from .tls.disjuntor import Disjuntor

#: Os cinco motivos do criterio 6. Lista **fechada**: e etiqueta de
#: `agr_degraded_turns_total`, e o dicionario §3.35 declara-a.
#:
#: `http_429` e nao `429`: ver a nota do modulo.
MOTIVO_TIMEOUT: Final = "timeout"
MOTIVO_429: Final = "http_429"
MOTIVO_BUDGET: Final = "budget"
MOTIVO_BREAKER: Final = "breaker"
MOTIVO_CONTRAPRESSAO: Final = "backpressure"

#: **O sexto, e o criterio 6 nao o previa.** O `DestinoNegado` do `llm/erros.py`
#: **e** um `ErroDeLlm` — a recusa do *gate* de destino por transferencia de
#: dados pessoais para fora de Angola sem autorizacao (ADR-008) — e a primeira
#: versao deste modulo deixava-o cair no `MOTIVO_BREAKER`, o ramo que o
#: comentario descreve como «avaria». O painel dizia «o modelo ficou
#: inalcancavel» e o que acontecera era **uma barreira de soberania a
#: funcionar**. Apanhado pela revisao adversarial (achado C4).
#:
#: Degrada-se — o cliente tem de receber resposta —, mas **nao conta no
#: disjuntor**: nao e uma avaria transitoria, e em `prod` a porta nega **tudo**
#: ate o KAM-069 existir, pelo que tres turnos abriam um disjuntor que nada
#: fecharia.
MOTIVO_DESTINO: Final = "destino_negado"

#: **O setimo, e o criterio 6 do KAM-037 tambem nao o previa.** E a falha fechada
#: do criterio 7 do KAM-112: a `FalhaDeMinimizacao` do `llm/erros.py` **e** um
#: `ErroDeLlm` — o detector de PII falhou ou passou o tecto de tempo, pelo que a
#: chamada ao LLM nao pode sair — e sem ramo proprio caia no `MOTIVO_BREAKER`, o
#: ramo que o comentario descreve como «avaria». O painel diria «o modelo ficou
#: inalcancavel» e o que aconteceu foi **uma barreira de minimizacao a
#: funcionar**. E o mesmo defeito que o `MOTIVO_DESTINO` corrigiu, pela mesma
#: razao, e esta aqui porque a licao dele estava escrita.
#:
#: Degrada-se — o cliente tem de receber resposta (`docs/tecnica/00` principio
#: 12, «degradar, nunca calar») —, mas **nao conta no disjuntor**: nao e uma
#: avaria transitoria do modelo, e um defeito nosso ou uma mensagem patologica, e
#: tres delas abriam um disjuntor que o fornecedor nada tem a ver com.
MOTIVO_MINIMIZACAO: Final = "minimizacao"

MOTIVOS: Final = (
    MOTIVO_TIMEOUT,
    MOTIVO_429,
    MOTIVO_BUDGET,
    MOTIVO_BREAKER,
    MOTIVO_CONTRAPRESSAO,
    MOTIVO_DESTINO,
    MOTIVO_MINIMIZACAO,
)

#: Os motivos que **nao** alimentam o disjuntor. Lista fechada de **dois**, e cada
#: entrada precisa da razao escrita: o disjuntor mede «o modelo esta em baixo
#: agora», e um motivo que nao seja isso suja a medida.
#:
#: O `MOTIVO_DESTINO` e a recusa do *gate* de destino; o `MOTIVO_MINIMIZACAO` e a
#: falha do detector de PII. Nenhum dos dois diz nada sobre o fornecedor — os dois
#: acontecem **antes** de haver chamada.
MOTIVOS_QUE_NAO_CONTAM: Final = (MOTIVO_DESTINO, MOTIVO_MINIMIZACAO)

#: O estado HTTP que o fornecedor devolve quando recusa por ritmo. O `classificar`
#: do `llm/erros.py` nao lhe da tipo proprio — e `FornecedorFalhou`, porque o
#: `resultado` e o dominio fechado de `dat.llm_call_log.resultado` e um valor
#: novo e uma revisao de base de dados. Quem o distingue e o `estado_http`.
ESTADO_DE_RITMO: Final = 429

#: O prefixo do backend do disjuntor. **Um por *tenant* e nao um global**, e a
#: primeira versao deste modulo tinha um so — o que era um defeito de
#: amplificacao entre *tenants*, apanhado pela revisao adversarial (achado C3).
#:
#: A razao e que **todas** as falhas que este detector ve chegam por uma chave
#: virtual **do *tenant***: o `llm/cliente.py` manda
#: `Authorization: Bearer {chave_virtual(ctx.tenant_id)}`, o §13.3 fixa
#: «orcamento mensal da **chave** = 15% x mensalidade», o ritmo e por chave, e o
#: *gate* de destino decide por `autorizar(ctx.tenant_id, ...)`. Com um
#: disjuntor global, tres turnos de um *tenant* sem orcamento punham **toda** a
#: replica em modo deterministico durante trinta segundos — e o ciclo repetia-se
#: a cada tentativa dele. E o oposto do anti-vizinho-ruidoso do §15.2 regra 2.
#:
#: **O que se paga por abrir por *tenant*** e, numa avaria real do proxy, ate
#: `allowed_fails` idas por *tenant* em vez de tres no total. E um tecto
#: pequeno, conhecido, e proporcional ao numero de *tenants* activos; o que se
#: compra e que a falha de um nao chega aos outros.
#:
#: **Nao se abre por alias**, e essa parte da leitura original mantem-se: o que
#: esta em baixo e o proxy, e abrir por alias deixava o `kamba-chat` a bater na
#: porta fechada depois de o `kamba-router` ja ter medido que ela esta.
PREFIXO_DO_BACKEND: Final = "llm"


def backend_de(tenant_id: str) -> str:
    """A chave do disjuntor deste *tenant*. Ver o `PREFIXO_DO_BACKEND`."""
    return f"{PREFIXO_DO_BACKEND}:{tenant_id}"

#: `allowed_fails` do proxy. **Medido** em `llm/litellm.config.yaml` §55 e
#: `llm/aliases.yaml` §44; CONFIRMADO contra a versao fixada em
#: `docs/evidencia/KAM-030-litellm.md` §4.
FALHAS_PARA_ABRIR: Final = 3

#: `cooldown_time` do proxy, em milissegundos. Medido nos mesmos dois ficheiros
#: (§56 e §45), em segundos: 30.
PAUSA_MS: Final = 30_000

#: A janela do alerta do criterio 6, em segundos. Quinze minutos.
JANELA_DO_ALERTA_S: Final = 900.0

#: A proporcao de turnos degradados de um *tenant* a partir da qual se alerta.
#: ***Proposta*** — o proprio criterio 6 o diz. Calibra-se em KAM-084.
LIMIAR_DO_ALERTA: Final = 0.05

#: Turnos minimos na janela antes de a proporcao valer. **Sem isto um unico
#: turno degradado da 100%** e alerta por um caso — que e ruido e nao sinal. O
#: valor e *proposta* pela mesma razao que o limiar, e calibra-se com ele.
MINIMO_PARA_ALERTAR: Final = 20


def motivo_do_erro(erro: ErroDeLlm) -> str:
    """O motivo de um `ErroDeLlm`. **Nao apanha outras excepcoes.**

    A assinatura e a barreira: um `OperationalError` do `psycopg` nao e um
    `ErroDeLlm` e nao tem motivo nenhum neste dominio — ver a nota do modulo.
    Quem lhe passar outra coisa leva `TypeError`, que e o lado certo de errar.

    **E funcao de modulo e nao metodo**, e isso tem razao medida nesta casa: o
    `DetectorDeDegradacao` e o `SemDegradacao` precisam os dois dela, e duas
    copias do mesmo corpo divergem no dia em que alguem corrigir uma (achado
    *Lean* da `ANALISE-33`, que o `inteiro_do_fact` do `validador/render.py`
    pagou).
    """
    if not isinstance(erro, ErroDeLlm):
        raise TypeError(
            "so um `ErroDeLlm` degrada: Postgres ou checkpointer em baixo "
            "nao e degradacao (bloco do KAM-037, `docs/tecnica/02` §14)"
        )
    if isinstance(erro, FalhaDeMinimizacao):
        # **Por `isinstance` e nao por `resultado`, e antes de todos os outros
        # ramos.** A `FalhaDeMinimizacao` nao tem `resultado` proprio de
        # proposito — um valor novo em `dat.llm_call_log.resultado` e uma revisao
        # de base de dados —, pelo que herda o `RESULTADO_ERRO` e cairia no
        # `breaker` tal como o `DestinoNegado` caia antes do achado C4. Ver o
        # `MOTIVO_MINIMIZACAO` e a *docstring* da excepcao.
        return MOTIVO_MINIMIZACAO
    if erro.resultado == RESULTADO_TIMEOUT:
        return MOTIVO_TIMEOUT
    if erro.resultado == RESULTADO_BUDGET:
        return MOTIVO_BUDGET
    if erro.resultado == RESULTADO_DESTINO:
        # **Antes do ramo de omissao, e e a correccao do achado C4.** Um
        # `DestinoNegado` cai no `else` com o `estado_http` a `None`, e o `else`
        # e o `breaker` — que diz «o modelo ficou inalcancavel» sobre uma recusa
        # de conformidade. Ver o `MOTIVO_DESTINO`.
        return MOTIVO_DESTINO
    if getattr(erro, "estado_http", None) == ESTADO_DE_RITMO:
        return MOTIVO_429
    # Um erro de fornecedor que nao e tempo, nem orcamento, nem ritmo, nem
    # destino conta como **avaria**, e a avaria e o que o disjuntor existe para
    # medir.
    return MOTIVO_BREAKER


class DetectorDeDegradacao:
    """Quando se degrada, porque, e quantas vezes.

    Nao abre ligacoes e nao chama o LLM: le o `admissao.py` (memoria deste
    processo), o disjuntor (idem) e os erros que lhe entregam. E injectavel por
    inteiro para que a bateria meca a **regra** e nao a paciencia de quem a
    corre — a mesma escolha do `Admissao`.
    """

    __slots__ = (
        "_admissao",
        "_disjuntor",
        "_janela_s",
        "_limiar",
        "_metricas",
        "_minimo",
        "_relogio",
        "_trinco",
        "_turnos",
    )

    def __init__(
        self,
        *,
        admissao: Any | None = None,
        disjuntor: Disjuntor | None = None,
        metricas: Any | None = None,
        relogio: Callable[[], float] = time.monotonic,
        limiar: float = LIMIAR_DO_ALERTA,
        janela_s: float = JANELA_DO_ALERTA_S,
        minimo_para_alertar: int = MINIMO_PARA_ALERTAR,
    ) -> None:
        self._admissao = admissao
        # **Os limiares do proxy, e nao os do `tls/disjuntor.py`.** Aquele le
        # `KAMBA_TLS_DISJUNTOR_FALHAS` (5 por omissao) e serve o COM, o PAY e o
        # IDX; este tem de concordar com o proxy, senao os dois discordam sobre
        # quando o modelo esta em baixo. Passam-se explicitos para que a omissao
        # do ambiente de outro subsistema nao chegue aqui.
        self._disjuntor = disjuntor or Disjuntor(
            falhas=FALHAS_PARA_ABRIR, pausa_ms=PAUSA_MS, relogio=relogio
        )
        self._metricas = metricas if metricas is not None else METRICAS
        self._relogio = relogio
        self._limiar = limiar
        self._janela_s = janela_s
        self._minimo = minimo_para_alertar
        self._trinco = threading.Lock()
        #: Por *tenant*, uma entrada por turno da janela: `[instante, turn_id,
        #: degradado]`. **Lista e nao tuplo** porque a entrada se promove de
        #: normal a degradada quando o modelo falha a meio do turno — ver o
        #: `registar_turno`.
        self._turnos: dict[str, collections.deque[list[Any]]] = {}

    # ------------------------------------------------------- antes do turno

    def motivo_antes_do_turno(self, tenant_id: str) -> str | None:
        """O motivo que se sabe **antes** de o turno correr, ou `None`.

        Dois, e pela ordem em que custam:

        * **`breaker`** — o disjuntor do LLM esta aberto. Pergunta-se com o
          `aberto()` e **nao** com o `permite()`: aquele consome a tentativa de
          meio-aberto, e um no do grafo que a consumisse fazia de uma leitura
          uma decisao sobre a saude do proxy. Quem a consome e quem **chama** o
          modelo (ver o `pode_chamar_o_llm`);
        * **`backpressure`** — o criterio 8: o *tenant* esta no tecto de
          concorrencia **e** a fila esta acima do limiar. As duas condicoes, e
          nao uma: a fila cheia sozinha e carga da plataforma e nao deste
          *tenant*, e o tecto cheio sozinho e o anti-vizinho-ruidoso a
          funcionar — degradar nesse caso punha um *tenant* ocupado a receber
          menus com a plataforma folgada.
        """
        if self._disjuntor.aberto(backend_de(tenant_id)):
            return MOTIVO_BREAKER
        if self._admissao is not None and self._contrapressao(tenant_id):
            return MOTIVO_CONTRAPRESSAO
        return None

    def _contrapressao(self, tenant_id: str) -> bool:
        tectos = self._admissao.tectos
        # Zero e «sem tecto» nas duas, como no ritmo (ver o `vaga_de` do
        # `admissao.py`): com o tecto desligado nao ha «estar no tecto», e com o
        # limiar a zero toda a fila estaria «acima do limiar» — nenhuma das duas
        # leituras e contrapressao.
        if tectos.tecto_por_tenant == 0 or tectos.limiar_de_contrapressao == 0:
            return False
        return (
            self._admissao.em_curso(tenant_id) >= tectos.tecto_por_tenant
            and self._admissao.a_espera >= tectos.limiar_de_contrapressao
        )

    def pode_chamar_o_llm(self, tenant_id: str) -> bool:
        """Se vale a pena ir ao proxy **por este *tenant***. Consome a tentativa.

        E o `permite()` do disjuntor, com o nome que diz o que a resposta
        significa aqui. Chama-se **imediatamente antes** da chamada, e nao num
        encaminhador: um encaminhador e uma funcao pura do estado, e esta
        pergunta muta o disjuntor.

        **Quem a chama tem de fechar o ciclo**, e e o achado C7 da revisao
        adversarial: esta chamada marca a tentativa de meio-aberto como
        entregue, e se quem a levou nao chamar depois `registar_falha` ou
        `registar_sucesso` ou `absolver`, a porta fica fechada pelo prazo da
        pausa — e os turnos desse intervalo degradam com `motivo="breaker"` por
        causa de uma excepcao que **nao era do modelo**. O `absolver` existe
        para esse caso e o `classify` chama-o num `finally`.
        """
        return self._disjuntor.permite(backend_de(tenant_id))

    def absolver(self, tenant_id: str) -> None:
        """A chamada acabou e **nao** diz nada sobre a saude do modelo.

        Larga a tentativa de meio-aberto sem tocar na contagem. E o caminho de
        uma excepcao que nao e um `ErroDeLlm` — um erro da base, um defeito
        nosso —, que **nao** e degradacao e por isso tambem nao e prova de
        avaria do modelo. Ver o `absolver` do `tls/disjuntor.py`, que foi escrito
        para esta distincao.
        """
        self._disjuntor.absolver(backend_de(tenant_id))

    # --------------------------------------------------------- o que falhou

    def motivo_do_erro(self, erro: ErroDeLlm) -> str:
        """O motivo de um `ErroDeLlm`. Ver o `motivo_do_erro` do modulo."""
        return motivo_do_erro(erro)

    def registar_falha(self, tenant_id: str, erro: ErroDeLlm) -> str:
        """Conta a falha no disjuntor **deste *tenant*** e devolve o motivo.

        **O orcamento esgotado conta**, e isso foi uma escolha: um
        `BUDGET_EXHAUSTED` nao e o proxy em baixo, mas e uma condicao que o
        turno seguinte vai encontrar igual — e tres turnos a pagar a ida para
        descobrir o mesmo sao tres clientes a esperar por nada. **E conta no
        disjuntor do *tenant* e nao num global**, que e o que torna isto
        defensavel: o orcamento e da chave virtual dele (ver o
        `PREFIXO_DO_BACKEND`). O disjuntor fecha-se ao primeiro sucesso, pelo que
        uma chave recarregada volta ao modo normal no turno seguinte (criterio 7).

        **O `destino_negado` nao conta**, e e a unica excepcao: ver o
        `MOTIVOS_QUE_NAO_CONTAM`. Mesmo assim larga-se a tentativa de
        meio-aberto, porque a chamada **aconteceu** e nao respondeu nada sobre a
        saude do modelo.
        """
        motivo = self.motivo_do_erro(erro)
        if motivo in MOTIVOS_QUE_NAO_CONTAM:
            self._disjuntor.absolver(backend_de(tenant_id))
            return motivo
        if self._disjuntor.registar_falha(backend_de(tenant_id)):
            self._metricas.contar(METRICA_DEGRADACAO_ALERTA)
        return motivo

    def registar_sucesso(self, tenant_id: str) -> None:
        """O modelo respondeu a este *tenant*. Fecha o disjuntor dele.

        E a metade do criterio 7 que vive aqui: a contagem e de falhas
        **consecutivas** (ver o `tls/disjuntor.py`), pelo que uma resposta boa
        apaga as anteriores e o turno seguinte nao encontra `breaker`.
        """
        self._disjuntor.registar_sucesso(backend_de(tenant_id))

    # ------------------------------------------------- contagem e proporcao

    def registar_turno(
        self, tenant_id: str, turn_id: str, motivo: str | None
    ) -> bool:
        """Conta **um** turno na janela deste *tenant*. Devolve se deve alertar.

        `motivo` e `None` num turno normal, e contar o turno normal nao e
        desperdicio: e o **denominador** que o criterio 6 pede («> 5% dos turnos
        de um *tenant*»). Sem ele a proporcao nao existe, e o que sobrava era uma
        contagem absoluta — que num *tenant* com muito trafego nunca alerta e num
        com pouco alerta sempre.

        ## O `turn_id` esta aqui para o turno nao contar duas vezes

        Um turno chama isto **uma ou duas** vezes, e nao e por descuido: o
        `ingest` chama-o sempre (com o motivo que se sabe antes de correr, que e
        quase sempre `None`) e o `classify` volta a chama-lo **se** o modelo
        falhar a meio do turno. Sem chave, as duas chamadas eram dois turnos: o
        denominador inflacionava e a proporcao do criterio 6 media um numero que
        nao existe.

        Com o `turn_id`, a segunda chamada **promove** a entrada da primeira de
        normal a degradada. E e por isso que a metrica se conta aqui e nao em
        quem chama: `agr_degraded_turns_total` passa a ser exactamente «turnos em
        modo deterministico», um por turno, e nao «vezes que alguem notou uma
        degradacao».

        **Nao se usa «a ultima entrada» em vez da chave**, e foi a primeira
        versao: com o tecto de concorrencia a tres, um *tenant* tem ate tres
        turnos em voo, e a ultima entrada podia ser de outro — a degradacao de um
        turno marcava o turno do lado.
        """
        if motivo is not None and motivo not in MOTIVOS:
            raise ValueError(f"{motivo!r} nao e um motivo de degradacao: {list(MOTIVOS)}")
        if not turn_id:
            # **Levanta em vez de aceitar um `turn_id` vazio** (achado P1 da
            # revisao adversarial). A entrada da janela e identificada pelo
            # `turn_id`, pelo que uma cadeia vazia fazia **todos** os turnos em
            # voo de um *tenant* valerem como **um** — e com o tecto de
            # concorrencia a tres isso encolhia o denominador do criterio 6 em
            # silencio. Um valor de omissao que transporta uma colisao e pior do
            # que um erro.
            raise ValueError("um turno sem `turn_id` nao se pode contar na janela")
        contar = False
        with self._trinco:
            # **O relogio le-se dentro do trinco** (achado P2): lido fora, duas
            # corrotinas do mesmo *tenant* podiam anexar fora de ordem, e o
            # `_podar` para na primeira entrada nao expirada — deixando presas
            # atras dela entradas mais velhas. A deque tem de ficar ordenada.
            agora = self._relogio()
            fila = self._turnos.setdefault(tenant_id, collections.deque())
            entrada = next((e for e in fila if e[1] == turn_id), None)
            if entrada is None:
                fila.append([agora, turn_id, motivo is not None])
                contar = motivo is not None
            elif motivo is not None and not entrada[2]:
                entrada[2] = True
                contar = True
            self._podar(agora)
            total = len(fila)
            degradados = sum(1 for entrada in fila if entrada[2])
        if contar:
            self._metricas.contar(METRICA_DEGRADADOS, motivo)
        if total < self._minimo:
            return False
        acima = degradados / total > self._limiar
        if acima:
            # **O alerta conta-se aqui e nao em quem chama**, e e a correccao do
            # achado C5 da revisao adversarial: a primeira versao devolvia o
            # booleano e os dois chamadores descartavam-no — o alerta do criterio
            # 6 era calculado e atirado fora, e o ensaio media o valor de retorno
            # de um metodo em vez de medir que alguma coisa acontece. Um efeito
            # que depende de quem chama se lembrar nao e um efeito.
            #
            # E a mesma forma que o KAM-027 deu ao «emite alerta» do seu criterio
            # 6 (`agr_registry_denied_total`) e o KAM-114 ao dele
            # (`agr_draft_pendentes`): nao ha sistema de alertas neste
            # repositorio, pelo que um alerta e uma metrica com nome mais a
            # pagina do runbook.
            self._metricas.contar(METRICA_DEGRADADOS_ACIMA)
        return acima

    def proporcao(self, tenant_id: str) -> float:
        """A proporcao de turnos degradados deste *tenant* na janela.

        **Nao muta nada** — ao contrario do `registar_turno`, que poda. Serve o
        painel e a bateria; uma leitura que podasse fazia de um observador um
        participante, que e a licao do `aberto()` contra o `permite()`.
        """
        agora = self._relogio()
        with self._trinco:
            fila = self._turnos.get(tenant_id)
            if not fila:
                return 0.0
            na_janela = [
                entrada[2] for entrada in fila if entrada[0] > agora - self._janela_s
            ]
        if not na_janela:
            return 0.0
        return sum(1 for d in na_janela if d) / len(na_janela)

    def _podar(self, agora: float) -> None:  # noqa: D401
        """Larga o que saiu da janela, em **todos** os *tenants*. Sob o trinco.

        **Todos e nao so o do turno**, e a diferenca e memoria: podando apenas o
        *tenant* que acabou de falar, a fila de quem deixou de falar nunca
        encolhia e o dicionario crescia com um *tenant* por chave para sempre —
        memoria ilimitada a custa de outrem, que e a razao do
        `del self._em_curso[tenant_id]` do `admissao.py` e do `MAXIMO_DE_CANAIS`
        do `chr/contrato.ts`.

        O custo e uma leitura da cabeca de cada fila por turno, que e O(1) por
        *tenant*; o que isso compra e um tecto de memoria igual aos turnos de
        quinze minutos, e nao ao numero de *tenants* que a replica ja viu.
        """
        limite = agora - self._janela_s
        vazios: list[str] = []
        for tenant_id, fila in self._turnos.items():
            while fila and fila[0][0] <= limite:
                fila.popleft()
            if not fila:
                vazios.append(tenant_id)
        for tenant_id in vazios:
            del self._turnos[tenant_id]


#: O detector que **nunca** degrada. E a omissao do grafo quando ninguem liga um
#: detector, e nao e um desligar de barreira: sem detector nao ha sinal de
#: degradacao nenhum, e o grafo comporta-se como o KAM-031 e o KAM-114 o
#: entregaram.
#:
#: E uma classe e nao um `lambda` para o ensaio poder afirmar a identidade — a
#: mesma razao da `SemPolitica` do `concierge/politica.py`.
class SemDegradacao:
    """O detector desligado, para quando o AGR corre sem ele."""

    __slots__ = ()

    def motivo_antes_do_turno(self, tenant_id: str) -> str | None:  # noqa: ARG002
        return None

    def pode_chamar_o_llm(self, tenant_id: str) -> bool:  # noqa: ARG002
        return True

    def absolver(self, tenant_id: str) -> None:  # noqa: ARG002
        return None

    def motivo_do_erro(self, erro: ErroDeLlm) -> str:
        # **Nao devolve `None`.** Um erro de LLM tem motivo mesmo com o detector
        # desligado: o que o `SemDegradacao` nao faz e **decidir** degradar, e
        # classificar nao e decidir. Devolver `None` aqui punha o `classify` a
        # escrever um `degradado` sem motivo no estado.
        return motivo_do_erro(erro)

    def registar_falha(self, tenant_id: str, erro: ErroDeLlm) -> str:  # noqa: ARG002
        return motivo_do_erro(erro)

    def registar_sucesso(self, tenant_id: str) -> None:  # noqa: ARG002
        return None

    def registar_turno(
        self, tenant_id: str, turn_id: str, motivo: str | None
    ) -> bool:  # noqa: ARG002
        return False

    def proporcao(self, tenant_id: str) -> float:  # noqa: ARG002
        return 0.0


__all__ = [
    "backend_de",
    "motivo_do_erro",
    "MOTIVOS_QUE_NAO_CONTAM",
    "MOTIVO_DESTINO",
    "PREFIXO_DO_BACKEND",
    "FALHAS_PARA_ABRIR",
    "JANELA_DO_ALERTA_S",
    "LIMIAR_DO_ALERTA",
    "MINIMO_PARA_ALERTAR",
    "MOTIVOS",
    "MOTIVO_429",
    "MOTIVO_BREAKER",
    "MOTIVO_BUDGET",
    "MOTIVO_CONTRAPRESSAO",
    "MOTIVO_TIMEOUT",
    "PAUSA_MS",
    "DetectorDeDegradacao",
    "SemDegradacao",
]
