"""A API interna do AGR: `/internal/turn` e `/internal/resume` (criterio 1).

«Minima» e o adjectivo que o `docs/tecnica/02` §4.2 regra 4 usa, e e para se
cumprir a letra: duas rotas, nenhuma de leitura, nenhuma de administracao, e
nenhuma que exista «para depois». A `/healthz` fica onde estava (`app.py`,
KAM-001) e **nao** leva credencial: e a sonda do *rolling deploy* e do
`docs/tecnica/09` §7, e uma sonda que precisa de segredo e uma sonda que falha
no dia em que o segredo roda.

## O que «recusar 401 sem credencial interna» obriga

Tres coisas, e as tres estao testadas:

1. **Sem cabecalho e 401**, nao 403 nem 500. O criterio escreve o numero.
2. **Com o cabecalho errado e 401 tambem**, e a comparacao e em tempo
   constante (`hmac.compare_digest`). Um `==` sobre texto sai no primeiro
   caracter diferente, e isso mede-se de fora: e um oraculo que entrega o
   *token* caracter a caracter. Nao e teorico num servico que responde em
   milissegundos a uma rota que nao tem limite de tentativas.
3. **A autenticacao corre antes de se ler o corpo.** Quem nao tem credencial
   leva 401 sem que o corpo seja lido nem descodificado — senao a rota
   autenticada e tambem uma superficie de negacao de servico nao autenticada.
   **O que isto nao e:** um tecto de memoria. Depois da autenticacao, o
   `await pedido.body()` le o corpo inteiro antes de o `CORPO_MAXIMO` o medir,
   porque e o que o ASGI da; o `CORPO_MAXIMO` impede o **JSON** de ser
   construido, nao a leitura. Um tecto a serio pertence ao proxy de entrada
   (KAM-076), e isto fica dito em vez de ficar por dizer.

E uma quarta, que nao e de codigo: **as rotas nao estao publicadas fora da rede
interna**. Quem o garante e a porta de escuta (o `__main__.py` do KAM-001 escuta
em `127.0.0.1` e so o `Dockerfile` poe `0.0.0.0`, para que correr o servico a
mao nao abra uma porta na rede local) e o `infra/compose` nao mapear a porta do
AGR para o anfitriao. A aplicacao na rede e o KAM-076.

## O que a resposta diz, e porque e que dois casos dao 200

O chamador e o *shim* do BullMQ (`ADR-L004`, Decisao 1), e o que ele faz com a
resposta decide se o *job* se repete:

| Caso | Estado | O que o *shim* faz |
|---|---|---|
| turno correu, ou foi ao HND, ou nao havia conversa | 200 | completa o *job* |
| descartado por ritmo (criterio 5) | **200** | completa o *job* |
| corpo invalido | 400 | descarta o *job* — nao melhora com repeticao |
| tecto do *tenant* cheio | 503 + `Retry-After` | devolve o *job* a fila com atraso |
| nao ha grafo para a vertical (KAM-027) | 503 + `Retry-After` | devolve o *job* a fila com atraso |
| o turno levantou | 500 | devolve o *job* a fila |

E a `/internal/resume` tem a sua, com o chamador a ser o HND (KAM-034):

| Caso | Estado | O que o HND faz |
|---|---|---|
| a retoma venceu o *compare-and-set* | 200 `retomado` | completa |
| a passagem ja tinha saido de `waiting` (*webhook* duplicado) | **200** `repetido` | completa — e e o *no-op* do criterio 3 |
| a passagem nao e deste *thread* (isolamento) | **404** | nao repete; a metrica e o registo mostram-no |
| corpo invalido, ou `outcome` fora dos tres do §11.1 | 400 | descarta |
| `secret` do *agent bot* ausente ou errado | 401 | nao repete; `agr_resume_nao_autorizado_total` sobe |
| nao ha grafo para a *thread* (KAM-027) | 503 + `Retry-After` | repete — e **nada foi escrito** |
| o `Command(resume=...)` levantou | 500 | repete — e a passagem **ja voltou** a `waiting` |

**O 404 do `recusado` nao e 403**, e a diferenca e de privacidade: «existe mas
nao e tua» confirma a existencia de uma passagem de outro *tenant*, que e
exactamente o que o ADR-015 nao quer que esta rota diga.

**O descarte por ritmo da 200 de proposito**, e e o unico sitio onde isso
engana: um 429 fazia o BullMQ repetir a mensagem que acabamos de decidir
descartar, e um descarte que se repete nao e um descarte. O criterio 5 chama-lhe
«descarte silencioso»; silencioso e para o cliente, e o `outcome` do corpo di-lo
a quem le registos, com a contagem em `agr_admitted_rejected_total{motivo="ritmo"}`.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .admissao import Admissao, TectoDoTenantCheioError
from .contexto import InvocacaoInvalidaError, ler_invocacao
from .eventos import EntregaInvalidaError, EntregaPorRepetir, ler_entrega
from .handoff.autenticacao import CABECALHO_DO_BOT
from .handoff.maquina import DESFECHOS, DesfechoInvalidoError
from .handoff.retoma import ThreadInvalidoError, partes
from .metricas import (
    METRICA_RECUSADOS,
    METRICA_RETOMA_NAO_AUTORIZADA,
    METRICAS,
)
from .turno import GrafoNaoRegistadoError

#: O cabecalho que leva a credencial interna. Dicionario §3.24.
CABECALHO: Final = "x-kamba-interno"

#: O `id` do segredo no inventario (`ops/secrets-inventory.yaml`). Dicionario
#: §3.9 para a forma, §3.24 para este valor.
SEGREDO_DA_API: Final = "agr_internal_token"

#: Quanto tempo o *shim* deve esperar antes de voltar a tentar, em segundos.
#: *Proposta*: um turno dura 3–7 s (§15.1), e menos do que isso punha o *job* de
#: volta antes de haver vaga. Calibra-se em KAM-084.
ESPERAR_SEGUNDOS: Final = 5

#: Comprimento maximo do corpo de um pedido, em bytes. O contrato tem nove
#: campos de forma fechada e nao chega a 1 KB.
#:
#: **Mede depois de ler, e isso e uma limitacao e nao um descuido:** o
#: `await pedido.body()` ja trouxe tudo quando este tecto se aplica. O que ele
#: impede e o `json.loads` de um corpo grande — que e onde o custo cresce mais
#: do que linearmente —, e nao a leitura. Quem impede a leitura e o proxy de
#: entrada (KAM-076). A forma do tecto e a do `PAYLOAD_MAXIMO` da revisao
#: `0008`; a garantia e mais fraca, e diz-se.
CORPO_MAXIMO: Final = 8 * 1024

#: Os tres campos de `/internal/resume` (`docs/tecnica/02` §11 regra 3).
CAMPOS_DA_RETOMA: Final = ("thread_id", "handoff_id", "outcome")


class RetomaNaoImplementadaError(NotImplementedError):
    """A porta da retoma nao foi ligada.

    **Nasceu como «a retoma e o KAM-034» e esse ticket esta feito**: o
    *compare-and-set* e o `Command(resume=...)` vivem em
    `kamba_agr/handoff/retoma.py` e o `__main__.py` liga-os. A excepcao fica
    porque a porta continua a ser uma porta — quem monte estas rotas sem lhe dar
    um `retomar` tem de levantar, e nao devolver 200 a fingir que retomou.
    """


def _nao_autorizado() -> JSONResponse:
    """401 sem corpo informativo.

    Nao diz se faltava o cabecalho ou se o valor estava errado: as duas
    respostas juntas sao um oraculo sobre o formato da credencial.
    """
    return JSONResponse({"outcome": "nao_autorizado"}, status_code=401)


def autenticado(pedido: Request, credencial: Callable[[], str]) -> bool:
    """`True` se o pedido traz a credencial interna correcta.

    `credencial` e uma funcao e nao uma cadeia, de proposito: o segredo roda
    (`ops/secrets-inventory.yaml`), e um valor lido uma vez no arranque ficava a
    recusar pedidos legitimos depois da rotacao. Quem a liga ao cofre e o
    `__main__.py`; aqui e uma porta.
    """
    dado = pedido.headers.get(CABECALHO)
    if not dado:
        return False
    return hmac.compare_digest(dado.encode("utf-8"), credencial().encode("utf-8"))


async def _corpo(pedido: Request) -> Any:
    cru = await pedido.body()
    if len(cru) > CORPO_MAXIMO:
        raise InvocacaoInvalidaError("corpo_grande")
    try:
        return json.loads(cru)
    except (ValueError, UnicodeDecodeError):
        raise InvocacaoInvalidaError("corpo_nao_e_json") from None


def rotas(
    credencial: Callable[[], str],
    executar: Callable[..., Awaitable[Any]],
    admissao: Admissao,
    trancas: Any,
    retomar: Callable[[str, str, str], Awaitable[str]] | None = None,
    verificar_bot: Callable[[str | None, str], str | None] | None = None,
    aviso: Callable[[str], None] | None = None,
    eventos: Any = None,
) -> list[Route]:
    """As tres rotas internas, com as portas que elas precisam.

    `executar` e o `ExecutorDeTurnos.correr`; `trancas` e o
    `TrancaDeConversas`, que a **retoma** precisa de tomar (§11 regra 3) — o
    turno toma-a por dentro, no executor; `retomar` e o `Retomador.retomar` do
    KAM-034, que por omissao levanta `RetomaNaoImplementadaError` e nao devolve
    200 a fingir que retomou. `aviso` recebe o «aviso unico» do criterio 5; por
    omissao nao escreve nada, e quem o liga ao *logger* e o `__main__.py`.

    `eventos` e o `ConsumidorDeEventos` do KAM-038; por omissao e `None`, e nesse
    caso `/internal/event` responde **503** com `Retry-After` — «o evento nao se
    consome agora e fica na fila», que e a mesma linha do §14 que o
    `grafo_nao_registado` usa. Nao e 404: a rota existe, e o que falta e o
    consumidor. Um 200 a fingir que consumiu perdia o evento em silencio.

    **`verificar_bot` nao tem omissao segura, e por isso a omissao recusa.** E
    o `secret` do *agent bot* do criterio 4 do KAM-034; sem verificador, **toda**
    a retoma leva 401 com `secret_errado`. A alternativa — nao verificar quando
    ninguem deu verificador — era um argumento por omissao a desligar um
    controlo de seguranca, que e a mesma regra do `segredoConfere` do HND («uma
    configuracao sem segredo nao pode tornar-se uma porta aberta»).
    """

    async def turno(pedido: Request) -> JSONResponse:
        if not autenticado(pedido, credencial):
            return _nao_autorizado()
        try:
            invocacao = ler_invocacao(await _corpo(pedido))
        except InvocacaoInvalidaError as erro:
            METRICAS.contar(METRICA_RECUSADOS, "invocacao_invalida")
            return JSONResponse(
                {"outcome": "invocacao_invalida", "error_code": erro.codigo},
                status_code=400,
            )

        # **A vaga vem antes do ritmo**, e a ordem foi invertida de proposito:
        # uma recusa por tecto devolve o *job* a fila, e a entrega seguinte do
        # **mesmo** `wamid` nao pode gastar quota nova. Com a ordem anterior,
        # vinte 503 do mesmo *job* consumiam os vinte lugares do minuto e a
        # mensagem seguinte — legitima — era descartada em silencio. Achado da
        # revisao adversarial.
        try:
            async with admissao.vaga(invocacao):
                if not admissao.aceita_o_ritmo(invocacao):
                    if admissao.deve_avisar(invocacao) and aviso is not None:
                        aviso("ritmo_excedido")
                    return JSONResponse({"outcome": "descartado"}, status_code=200)
                desfecho = await executar(invocacao)
        except TectoDoTenantCheioError:
            return JSONResponse(
                {"outcome": "tecto_do_tenant"},
                status_code=503,
                headers={"Retry-After": str(ESPERAR_SEGUNDOS)},
            )
        except GrafoNaoRegistadoError:
            # 503 e nao 500: «o turno nao corre e a mensagem fica na fila»
            # (`docs/tecnica/02` §14). Enquanto o KAM-027 nao registar grafos,
            # e este o estado honesto do servico.
            return JSONResponse(
                {"outcome": "grafo_nao_registado"},
                status_code=503,
                headers={"Retry-After": str(ESPERAR_SEGUNDOS)},
            )

        return JSONResponse(
            {
                "outcome": desfecho.desfecho,
                "turn_id": desfecho.turn_id,
                "coalescidos": desfecho.coalescidos,
            },
            status_code=200,
        )

    async def retoma(pedido: Request) -> JSONResponse:
        if not autenticado(pedido, credencial):
            return _nao_autorizado()
        try:
            corpo = await _corpo(pedido)
        except InvocacaoInvalidaError as erro:
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": erro.codigo},
                status_code=400,
            )
        if not isinstance(corpo, dict) or set(corpo) != set(CAMPOS_DA_RETOMA):
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": "campos_da_retoma"},
                status_code=400,
            )
        if not all(isinstance(corpo[campo], str) and corpo[campo] for campo in CAMPOS_DA_RETOMA):
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": "campos_da_retoma"},
                status_code=400,
            )

        # **A segunda credencial: o `secret` do *agent bot* do HND** (KAM-034,
        # criterio 4). Corre **depois** de o corpo ser lido, e nao antes como a
        # primeira, porque o segredo e por bot — logo por *tenant* — e o
        # *tenant* vem do prefixo do `thread_id`. A propriedade que a
        # *docstring* deste modulo promete nao se perde: quem nao tem o
        # `x-kamba-interno` continua a levar 401 **sem** o corpo ser lido, e o
        # custo de ler um corpo para verificar a segunda credencial e um custo
        # que so quem passou a primeira consegue impor.
        #
        # E corre **antes** de se validar o vocabulario do `outcome`, de
        # proposito: senao um pedido sem segredo valido conseguia descobrir
        # quais os tres desfechos aceites pela diferenca entre 400 e 401.
        motivo = (
            verificar_bot(pedido.headers.get(CABECALHO_DO_BOT), corpo["thread_id"])
            if verificar_bot is not None
            else "secret_errado"
        )
        if motivo is not None:
            METRICAS.contar(METRICA_RETOMA_NAO_AUTORIZADA, motivo)
            return _nao_autorizado()

        if corpo["outcome"] not in DESFECHOS:
            # Um quarto desfecho e um corpo que nao conhecemos. **Recusa-se, nao
            # se ignora**: aceitar um desfecho que nao se sabe tratar e deixa-lo
            # passar sem efeito, e o §3.15 da ao `close` exactamente tres.
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": "desfecho_invalido"},
                status_code=400,
            )
        # **A forma do `thread_id` confere-se ANTES de se tomar a tranca**, e
        # nao e arrumacao: a tranca e um `pg_advisory_lock` por chave, e tomar
        # uma chave que nao corresponde a conversa nenhuma era deixar quem
        # tenha as duas credenciais prender chaves arbitrarias — uma negacao de
        # servico por conversa, de dentro. A primeira versao desta rota tomava a
        # tranca e deixava o `Retomador` recusar lá dentro.
        try:
            partes(corpo["thread_id"])
        except ThreadInvalidoError:
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": "thread_id_invalido"},
                status_code=400,
            )
        if retomar is None:
            raise RetomaNaoImplementadaError("retoma_sem_porta")

        # **Sob a tranca da conversa**, que e o que o `docs/tecnica/02` §11
        # regra 3 exige por escrito: «a invocacao `Command(resume=...)` corre
        # sob o *lock* da conversa». Tres sitios afirmavam que o KAM-025
        # entregava isto e o codigo chamava a porta directamente — achado da
        # revisao adversarial. Sem a tranca, um `resume` entrava no grafo ao
        # mesmo tempo que um turno novo, sobre o mesmo *thread*.
        #
        # **A tranca cobre o CAS, o `Command` e a compensacao**, e nao so o
        # `Command`: e ela que torna a reversao do `retoma.py` segura, porque
        # entre as duas escritas ninguem mais toca na linha.
        try:
            async with trancas.tomar(corpo["thread_id"]):
                desfecho = await retomar(
                    corpo["thread_id"], corpo["handoff_id"], corpo["outcome"]
                )
        except (ThreadInvalidoError, DesfechoInvalidoError) as erro:
            # **Nenhum dos dois devia chegar aqui** — o `partes` e o `DESFECHOS`
            # acima ja os filtraram —, e tratam-se de qualquer maneira porque
            # sao duas leituras do mesmo dominio em dois sitios, e um 500 por
            # divergencia entre elas punha o HND a repetir um pedido que nunca
            # vai passar. 400 e nao 404: o corpo esta mal, e a passagem nao
            # esta em causa.
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": type(erro).__name__},
                status_code=400,
            )
        except GrafoNaoRegistadoError:
            # A mesma linha do `/internal/turn`: 503 com `Retry-After`, para que
            # o *webhook* volte em vez de a retoma se perder. **E nada foi
            # escrito**: o `retoma.py` resolve o grafo **antes** do CAS, pelo
            # que esta excepcao sobe sem a base ser tocada — e repetir e seguro
            # porque nao ha nada para desfazer.
            return JSONResponse(
                {"outcome": "grafo_nao_registado"},
                status_code=503,
                headers={"Retry-After": str(ESPERAR_SEGUNDOS)},
            )

        # `recusado` e 404 e nao 403: a passagem nao e deste *thread*, e dizer
        # «existe mas nao e tua» era confirmar a existencia de uma passagem de
        # outro. O `repetido` e 200 porque e o *webhook* duplicado do criterio 3
        # — «o 2.º devolve *no-op* (200)» — e um 409 punha o Chatwoot a repetir
        # um pedido que esta tratado.
        estado = 404 if desfecho == "recusado" else 200
        return JSONResponse({"outcome": desfecho}, status_code=estado)

    async def evento(pedido: Request) -> JSONResponse:
        """`POST /internal/event` — a entrega de um evento (KAM-038).

        A casca da fila fica em TypeScript, pelo molde do `agr/shim.ts`
        (ADR-L004, Decisao 1): o que chega aqui e um pedido HTTP com o envelope
        e a tentativa, e a decisao toda esta no `ConsumidorDeEventos`.

        **Os codigos sao tres e cada um diz a fila o que fazer**: 200 «tratado,
        nao repitas» (inclui o que foi para a DLQ — foi tratado), 400 «o corpo
        nao e uma entrega, nao vale a pena repetir», e 503 com `Retry-After`
        «volta». Um evento que foi para a DLQ responder 500 punha o BullMQ a
        repetir o que ja esta registado e a abrir a mesma entrada seis vezes.
        """
        if not autenticado(pedido, credencial):
            return _nao_autorizado()
        try:
            corpo = await _corpo(pedido)
        except InvocacaoInvalidaError as erro:
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": erro.codigo},
                status_code=400,
            )
        if eventos is None:
            return JSONResponse(
                {"outcome": "consumidor_por_ligar"},
                status_code=503,
                headers={"Retry-After": str(ESPERAR_SEGUNDOS)},
            )
        try:
            entrega = ler_entrega(corpo)
        except EntregaInvalidaError as erro:
            return JSONResponse(
                {"outcome": "corpo_invalido", "error_code": erro.codigo},
                status_code=400,
            )

        # **A vaga vem antes do consumo**, como no `/internal/turn`, e o
        # `prioritario` e o criterio 8: um `payment.*` entra com a reserva
        # **acima** do tecto do *tenant*, pelo que nao espera atras de mensagens
        # de conversa. O `tenant_id` usado aqui e o **ponteiro da fila** e nao
        # autoridade: o contexto de RLS do consumo sai do envelope validado, la
        # dentro (criterio 4). Usa-se este porque a vaga tem de ser tomada antes
        # de se ler o envelope — e a leitura ja e trabalho.
        try:
            async with admissao.vaga_de(
                entrega.tenant_id,
                prioritario=eventos.e_prioritario(_tipo_da_entrega(entrega)),
            ):
                desfecho = await eventos.entregar(corpo)
        except TectoDoTenantCheioError:
            return JSONResponse(
                {"outcome": "tecto_do_tenant"},
                status_code=503,
                headers={"Retry-After": str(ESPERAR_SEGUNDOS)},
            )
        except EntregaPorRepetir as repetir:
            # O atraso vem de dentro — da escada do §6.4 ou do `Adiar` — e
            # converte-se a segundos **arredondando para cima**: um atraso de
            # 1 000 ms que virasse `Retry-After: 1` estava certo, mas um de
            # 1 500 ms que virasse 1 pedia a repeticao antes do tempo.
            segundos = max(1, -(-repetir.atraso_ms // 1_000))
            return JSONResponse(
                {"outcome": repetir.codigo},
                status_code=503,
                headers={"Retry-After": str(segundos)},
            )

        return JSONResponse(
            {
                "outcome": desfecho.desfecho,
                "por_consumidor": [
                    {"consumer": nome, "outcome": resultado}
                    for nome, resultado in desfecho.por_consumidor
                ],
            },
            status_code=200,
        )

    return [
        Route("/internal/turn", turno, methods=["POST"]),
        Route("/internal/resume", retoma, methods=["POST"]),
        Route("/internal/event", evento, methods=["POST"]),
    ]


def _tipo_da_entrega(entrega) -> str:
    """O `tipo` do envelope cru, **so** para decidir a prioridade da vaga.

    Le o campo sem validar nada: a validacao e la dentro, e so depois dela e que
    o envelope e autoridade sobre o que quer que seja. Aqui o pior que um `tipo`
    mentido consegue e pedir a reserva de pagamento para um evento que nao e de
    pagamento — isto e, **uma** vaga a mais num *tenant*, que a entrega seguinte
    larga. Validar antes de admitir era fazer o trabalho fora da vaga, que e o
    oposto do que o tecto existe para proteger.
    """
    bruto = entrega.envelope
    if isinstance(bruto, (str, bytes)):
        # **O `ler_envelope` aceita texto JSON**, e a primeira versao disto nao:
        # um `payment.*` entregue assim perdia a reserva de prioridade em
        # silencio. Achado da revisao adversarial. O `json.loads` aqui nao
        # valida nada — a validacao e la dentro — e o pior que um texto
        # malformado consegue e cair no `""`, que e nao ter prioridade.
        try:
            bruto = json.loads(bruto)
        except (ValueError, UnicodeDecodeError):
            return ""
    if isinstance(bruto, dict):
        tipo = bruto.get("tipo")
        if isinstance(tipo, str):
            return tipo
    return ""
