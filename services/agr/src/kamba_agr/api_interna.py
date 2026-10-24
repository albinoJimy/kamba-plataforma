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
from .metricas import METRICA_RECUSADOS, METRICAS
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
    """A retoma do *handoff* e o KAM-034.

    O que o KAM-025 entrega da retoma e a rota, a autenticacao, a validacao do
    corpo e o **lock da conversa** que o §11 regra 3 exige («a invocacao
    `Command(resume=...)` corre sob o *lock* da conversa»). O *compare-and-set*
    em `handoffs(status: waiting -> resumed)` e o `Command(resume=...)` sao o
    KAM-034, por nome, e o bloco deste ticket diz «nao expandas escopo».
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
    retomar: Callable[[str, str, str], Awaitable[None]] | None = None,
    aviso: Callable[[str], None] | None = None,
) -> list[Route]:
    """As duas rotas internas, com as portas que elas precisam.

    `executar` e o `ExecutorDeTurnos.correr`; `trancas` e o
    `TrancaDeConversas`, que a **retoma** precisa de tomar (§11 regra 3) — o
    turno toma-a por dentro, no executor; `retomar` e a porta do KAM-034, que
    por omissao levanta `RetomaNaoImplementadaError` e nao devolve 200 a fingir
    que retomou. `aviso` recebe o «aviso unico» do criterio 5; por omissao nao
    escreve nada, e quem o liga ao *logger* e o `__main__.py`.
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
        if retomar is None:
            raise RetomaNaoImplementadaError("retoma_e_kam_034")
        # **Sob a tranca da conversa**, que e o que o `docs/tecnica/02` §11
        # regra 3 exige por escrito: «a invocacao `Command(resume=...)` corre
        # sob o *lock* da conversa». Tres sitios afirmavam que o KAM-025
        # entregava isto e o codigo chamava a porta directamente — achado da
        # revisao adversarial. Sem a tranca, um `resume` entrava no grafo ao
        # mesmo tempo que um turno novo, sobre o mesmo *thread*.
        async with trancas.tomar(corpo["thread_id"]):
            await retomar(corpo["thread_id"], corpo["handoff_id"], corpo["outcome"])
        return JSONResponse({"outcome": "retomado"}, status_code=200)

    return [
        Route("/internal/turn", turno, methods=["POST"]),
        Route("/internal/resume", retoma, methods=["POST"]),
    ]
