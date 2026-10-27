"""Os vinte e um nos do grafo do Vendedor (§7.3, §7.4).

## O que e Fase 0 aqui, e o que nao e atalho

O Objectivo do bloco diz «sobre as tools especificadas na TLS (backends *fake*
ate KAM-043/046/061), com nos de guardrail, STT e handoff como pontos de ligacao
a KAM-033, KAM-036 e KAM-034». Isso decide tres coisas, e as tres estao escritas
no no que as sofre:

* o `stt` **nao transcreve**: encaminha, e sem porta de STT o veredicto e
  `ask_repeat` — a linha que o §14 escreve para «STT indisponivel»;
* o `guard_in` e o `guard_out` sao **deterministicos minimos**: o PAN com Luhn, o
  IBAN, um punhado de padroes de injeccao e as frases vetadas sem numero. O
  classificador barato e a cobertura completa sao o KAM-033;
* o `handoff_prepare`/`handoff_wait`/`handoff_close` delegam numa porta
  `HandoffService`, com os efeitos idempotentes por `handoff_id` do §11. A
  implementacao idempotente do lado do HND e o KAM-034.

Nenhuma das tres e um atalho: sao as fronteiras que o ticket nomeia. O que **e**
atalho leva comentario `shortcut:` com o credor.

## O `classify` decide por regras primeiro, e o modelo so se elas nao decidirem

O §15.1 escreve-o pelo nome — «Router so se as regras nao decidem» — e o §8.4
repete-o para os guardrails. Um botao `confirm:*` **nunca** passa por modelo: e
dinheiro, e a intencao esta no identificador do botao, nao no texto.

## De onde vem o texto do cliente, e o que isso deixa em divida

O contrato `agent_invocation` (§3.13) tem **nove** campos fechados e nenhum
deles e o corpo da mensagem: o AGR recebe identificadores. O grafo le o texto da
janela `messages` do estado, que e o que o §12 manda guardar, e **quem a enche
e quem invoca o grafo**. Hoje ninguem invoca — a porta `grafos` do `turno.py`
levanta `GrafoNaoRegistadoError` de proposito —, pelo que a convencao nasce aqui
e o credor e quem ligar essa porta. Esta escrito na seccao de verificacao do
bloco e em `docs/agr.md`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from ...estado import reiniciar, versao_lida
from ...tls.contexto import Confirmation, ToolContext
from ...tls.erros import (
    LIMIT_EXCEEDED,
    NOT_FOUND,
    OUT_OF_STOCK,
    PRICE_CHANGED,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    VALIDATION_ERROR,
)
from ...validador.render import BlocoInvalidoError, Oferta, renderizar
from ...validador.veredicto import Policy, medir_validacao, validar
from .arestas import AVISOS, RECUSAS, STALE_CONFIRMATION, VERSAO_DO_GRAFO

# --------------------------------------------------------------------- tectos

#: O limiar do IDX abaixo do qual o `retrieve` vai a `unknown_reply` (§7.3 linha
#: 18). **Parametro, e o §7.3 chama-lhe isso** — «limiar de IDX, parametro».
#: Quem o calibra e o KAM-061, com indice real; o valor aqui faz o ramo existir.
LIMIAR_IDX: Final = 0.5

#: A validade de um carrinho, em segundos. **30 min, *proposta*** — o criterio 4
#: do bloco escreve «TTL do carrinho *proposta*: 30 min, a calibrar».
TTL_DO_CARRINHO_S: Final = 1_800

#: O `seq` do unico envio de um turno. Zero, e **nao e atalho**: o §15.1 fixa
#: «uma so mensagem por turno» e o §3.24 do dicionario diz que o `seq` conta
#: dentro do turno e reinicia em cada volta. Um segundo envio no mesmo turno
#: precisa de um campo de estado e de uma emenda — esta dito na emenda 1.40.
SEQ_DO_ENVIO: Final = 0

#: Quantas vezes se repete uma tool depois de um `UPSTREAM_*`. Um, como o §6.5
#: manda («1 retry com *backoff*; depois `handoff_prepare`»). O *backoff* nao
#: esta aqui: o tecto de tempo e da camada (§6.1 passo 7), e dormir dentro de um
#: no punha o turno a gastar o orcamento de latencia do §15.1 a espera.
REPETICOES_DE_UPSTREAM: Final = 1

#: As tools que este grafo pode chamar. E a lista fechada do
#: `registry/vendedor.yaml`, e o passo 1 do `invoke` recusa qualquer outra.
TOOLS_DO_VENDEDOR: Final = (
    "search_catalog",
    "get_price_stock",
    "propose_cart",
    "criar_pedido",
    "get_order_status",
    "get_store_info",
)

# ------------------------------------------------------------ textos estaticos
#
# **Nenhum leva digitos**, e nao e estilo: os quatro saem pelas arestas da linha
# 34, que passam ao lado do `validate`. Um numero aqui era um numero sem *fact*
# a chegar ao cliente por um caminho que o validador nao ve. Ha ensaio que o
# mede sobre todos os textos deste modulo.

MSG_NAO_ENTENDI: Final = (
    "Nao encontrei nada no catalogo da loja para o que pediu. Pode dizer de "
    "outra maneira, ou falar com um colega da loja."
)
MSG_REPETIR: Final = (
    "Nao consegui ouvir a nota de voz. Pode escrever a sua mensagem?"
)
MSG_FORA_DE_AMBITO: Final = (
    "So posso ajudar com os produtos, os precos e os pedidos desta loja. "
    "Prefere falar com um colega?"
)
MSG_HUMANO_A_CAMINHO: Final = (
    "Vou passar a conversa a um colega da loja. Ele responde-lhe aqui."
)
MSG_DEGRADADO: Final = (
    "Nao consigo passar a conversa a um colega agora. A loja responde-lhe aqui "
    "assim que puder."
)
MSG_ALTERNATIVAS: Final = (
    "Ainda nao houve resposta de um colega. Pode escrever outra vez, ou tentar "
    "mais tarde."
)

#: O que o `compose` diz por cada aviso. **Uma entrada por valor do dominio
#: fechado**, e ha ensaio que o prova: um aviso sem frase era um aviso que o
#: cliente nunca via, e o §6.5 manda explicar.
FRASE_DO_AVISO: Final = {
    NOT_FOUND: "Nao encontrei esse artigo no catalogo da loja.",
    OUT_OF_STOCK: "Nao ha unidades suficientes desse artigo neste momento.",
    PRICE_CHANGED: "O preco mudou desde que lhe mostrei. Confirme o novo valor.",
    LIMIT_EXCEEDED: "Este pedido passa o limite da loja. Um colega pode ajudar.",
    VALIDATION_ERROR: "Nao consegui tratar esse pedido como estava escrito.",
    UPSTREAM_TIMEOUT: "O sistema da loja demorou a responder.",
    UPSTREAM_DOWN: "O sistema da loja nao responde neste momento.",
    STALE_CONFIRMATION: (
        "Essa confirmacao ja nao esta valida. Vou mostrar-lhe o carrinho outra vez."
    ),
}

#: Os botoes do turno de confirmacao (§7.3, fluxo de dois turnos).
BOTAO_CONFIRMAR: Final = "confirm:{cart_id}"
BOTAO_CANCELAR: Final = "cancelar"
BOTAO_HUMANO: Final = "falar_com_humano"

# ------------------------------------------------------------------ guardrails

#: Padroes de injeccao (§8.4, primeira linha). Minimos e nomeados: o conjunto
#: completo e o KAM-033, e um conjunto grande aqui dava a ilusao de cobertura.
_INJECCAO: Final = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignora (?:as )?(?:tuas |suas )?instru",
        r"\besquece (?:tudo|as instru)",
        r"\brevela (?:o teu|o seu|as tuas|as suas) (?:prompt|instru|sistema)",
        r"\bage como\b",
        r"\bfinge (?:que|ser)\b",
        r"\bsystem prompt\b",
    )
)

#: Pedidos que atravessam a fronteira do tenant ou do contacto. **E a metade do
#: X-09 que vive na guarda**: a outra esta na tool, que so ve encomendas do
#: proprio contacto, e a terceira na RLS. Tres barreiras, e nenhuma sozinha.
_FRONTEIRA: Final = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:pedidos|encomendas|clientes|vendas)\b.{0,20}\b(?:da|de|do)\s+(?:loja|empresa|tenant)\b",
        r"\boutros? (?:clientes?|contactos?|lojas?)\b",
        r"\btodos os (?:pedidos|clientes|contactos)\b",
    )
)

#: Assunto sensivel (§8.4, quarta linha): saude, medicamentos, armas, alcool,
#: apostas e credito. Vai a **handoff** e nao a `safe_reply`, porque o §7.3
#: linha 10 o manda — e porque uma loja pode legitimamente vender alguns
#: destes, e quem decide e uma pessoa.
_SENSIVEL: Final = tuple(
    re.compile(rf"\b{p}\b", re.IGNORECASE)
    for p in (
        "medicament\\w*", "remedi\\w*", "receita medica", "doenca", "sintoma",
        "arma", "municao", "aposta\\w*", "credito", "emprestimo",
    )
)

#: Frases vetadas na saida (§8.4, «Promessas proibidas»). Minimas: a lista
#: completa e do KAM-033, e a emenda 1.39 ja o escreveu.
_PROMESSAS: Final = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bo mais barato\b", r"\bmais barato (?:da|do|que)\b",
        r"\bchega amanha\b", r"\bentrega(?:mos)? amanha\b",
        r"\bem promo[cç]ao\b", r"\btemos sempre\b",
        r"\bja (?:esta )?(?:pago|confirmado)\b",
    )
)

#: Um numero de telefone angolano em claro na saida (§8.4, «Fuga de PII»). O
#: padrao e o do `docs/logs.md` §2.1 reduzido ao essencial: nove digitos a
#: comecar por 9, com ou sem indicativo.
_TELEFONE: Final = re.compile(r"(?:\+?244[\s-]?)?9\d{2}[\s-]?\d{3}[\s-]?\d{3}")

#: Um PAN candidato: treze a dezanove digitos, com espacos ou tracos.
_PAN: Final = re.compile(r"(?:\d[ -]?){13,19}")

#: Um IBAN angolano ou generico.
_IBAN: Final = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

# -------------------------------------------------------------------- portas


class PortaDeStt(Protocol):
    """O que o `stt` precisa do fornecedor (§10). A implementacao e o KAM-036."""

    def transcrever(self, estado: Mapping[str, Any]) -> dict[str, Any]: ...


class PortaDeHandoff(Protocol):
    """O `HandoffService` do §11. A implementacao idempotente e o KAM-034."""

    def abrir(
        self, *, handoff_id: str, estado: Mapping[str, Any], motivo: str, resumo: str
    ) -> str: ...


class PortaDeSaida(Protocol):
    """O Outbound (`01` §8). O unico caminho para o cliente e o no `send`."""

    def enfileirar(
        self,
        estado: Mapping[str, Any],
        texto: str,
        *,
        chave: str,
        botoes: Sequence[str] = (),
    ) -> None: ...


class HandoffIndisponivel(RuntimeError):
    """O `HandoffUnavailable` do §11: o HND nao aceitou abrir o *handoff*."""


def _admite_sempre(_estado: Mapping[str, Any]) -> str | None:
    """A porta de admissao por omissao: o turno corre.

    **Nao e um `True` optimista — e a leitura de onde as tres condicoes da linha
    4 vivem hoje**, e as tres vivem fora do grafo:

    * o `turn_id` repetido e filtrado no GWY pelo `wamid` (§6.3 ponto i);
    * o ritmo e o `aceita_o_ligacao`... o `aceita_o_ritmo` do `admissao.py`
      (KAM-025), que corre em `api_interna.py` **antes** da tranca e antes do
      grafo — e que **registra a chegada**, pelo que chama-lo outra vez aqui
      gastava duas vagas das vinte por minuto e cortava o tecto a metade;
    * o contacto bloqueado vive em `contacts`, que este ticket nao le.

    Por isso o grafo e a **segunda** barreira e nao a primeira, e a porta e
    injectavel: o ensaio do criterio 7 passa uma que recusa, e mede que o turno
    acaba em `END` sem envio. Quem ligar a porta `grafos` do `turno.py` liga
    tambem esta, com a leitura de `contacts` e a desduplicacao por `turn_id`.
    """
    return None


@dataclass(frozen=True, slots=True)
class Dependencias:
    """O `Deps` do §7.4: as portas e os parametros de um grafo do Vendedor."""

    tools: Any
    saida: PortaDeSaida
    #: A persona do `registry/vendedor.yaml` (§5.1). O `apresentacao` e o que
    #: cumpre a identidade do §8.4 na primeira mensagem da conversa.
    persona: Mapping[str, str] = field(default_factory=dict)
    stt: PortaDeStt | None = None
    hnd: PortaDeHandoff | None = None
    #: O `kamba-router` do §15.1, chamado **so** se as regras nao decidirem.
    classificador: Callable[[str], str] | None = None
    metricas: Any | None = None
    admitir: Callable[[Mapping[str, Any]], str | None] = _admite_sempre
    #: Segundos desde a epoca. `time.time` e nao `monotonic`: o `expira_at` de um
    #: carrinho atravessa turnos e processos, e um relogio monotono nao e
    #: comparavel entre dois.
    relogio: Callable[[], float] = None  # type: ignore[assignment]
    limiar_idx: float = LIMIAR_IDX
    ttl_do_carrinho_s: int = TTL_DO_CARRINHO_S
    tools_permitidas: Sequence[str] = TOOLS_DO_VENDEDOR
    checkpointer: Any | None = None

    def __post_init__(self) -> None:
        if self.relogio is None:
            import time

            object.__setattr__(self, "relogio", time.time)


# ------------------------------------------------------------------ utilitarios


def _texto_do_cliente(estado: Mapping[str, Any]) -> str:
    """O texto da ultima mensagem do cliente, da janela `messages`.

    Le tanto o `dict` `{"role": …, "content": …}` como um objecto de mensagem do
    LangChain, porque o redutor `add_messages` converte o primeiro no segundo e
    um no que corra **antes** do redutor ve o primeiro.
    """
    for mensagem in reversed(list(estado.get("messages") or ())):
        papel = (
            mensagem.get("role")
            if isinstance(mensagem, Mapping)
            else getattr(mensagem, "type", None)
        )
        if papel in ("user", "human"):
            conteudo = (
                mensagem.get("content")
                if isinstance(mensagem, Mapping)
                else getattr(mensagem, "content", "")
            )
            return conteudo if isinstance(conteudo, str) else ""
    return ""


def _botao_do_turno(estado: Mapping[str, Any]) -> str:
    """O identificador do botao tocado, quando a entrada e interactiva."""
    if estado.get("input_kind") != "interactive":
        return ""
    return _texto_do_cliente(estado).strip()


def contexto_de_tool(estado: Mapping[str, Any]) -> ToolContext:
    """O `ToolContext` do turno (§6.1).

    O `run_id` e derivado do `thread_id` e do `turn_id` e **nao** e aleatorio: a
    `tool_audit` e append-only e duas linhas do mesmo turno tem de se poder
    juntar, inclusive quando o turno se repete a partir do checkpoint. Um
    `uuid4()` por execucao dava duas identidades ao mesmo turno.
    """
    cru = f"{estado['thread_id']}:{estado['turn_id']}".encode()
    return ToolContext(
        tenant_id=estado["tenant_id"],
        channel_id=estado["channel_id"],
        contact_id=estado["contact_id"],
        conversation_id=estado["conversation_id"],
        turn_id=estado["turn_id"],
        vertical=estado["vertical"],
        run_id=hashlib.sha256(cru).hexdigest()[:32],
        graph_version=VERSAO_DO_GRAFO,
    )


def chave_do_turno(estado: Mapping[str, Any]) -> str:
    """`idempotency_key = turn_id:seq` (§3.24 do dicionario, criterio 4 do KAM-025)."""
    from ...contexto import chave_de_envio

    return chave_de_envio(estado["turn_id"], SEQ_DO_ENVIO)


def _avisos_com(estado: Mapping[str, Any], *codigos: str) -> tuple[str, ...]:
    """Junta avisos aos que ja estao no estado, sem repetir e sem inventar.

    Um codigo fora do dominio fechado **levanta**: era a forma de uma cadeia
    livre chegar ao `compose`, que decide por valor conhecido.
    """
    fora = [c for c in codigos if c not in AVISOS]
    if fora:
        raise ValueError(f"{fora} nao sao avisos do dominio fechado: {list(AVISOS)}")
    juntos = list(estado.get("avisos") or ())
    for codigo in codigos:
        if codigo not in juntos:
            juntos.append(codigo)
    return tuple(juntos)


def _ofertas_de(estado: Mapping[str, Any]) -> tuple[Oferta, ...]:
    """As ofertas do estado como objectos `Oferta` do KAM-032."""
    convertidas = []
    for crua in estado.get("ofertas") or ():
        if isinstance(crua, Oferta):
            convertidas.append(crua)
        else:
            convertidas.append(
                Oferta(
                    sku=crua["sku"],
                    nome=crua["nome"],
                    preco_tipo=crua["preco_tipo"],
                )
            )
    return tuple(convertidas)


async def _com_retry(chamar: Callable[[], Any]) -> Any:
    """Uma tool, com **um** retry se o erro for `UPSTREAM_*` (§6.5).

    Nao repete nada que nao seja `UPSTREAM_*`: um `OUT_OF_STOCK` repetido da o
    mesmo, um `ENTITLEMENT_DENIED` repetido e uma segunda tentativa de
    atravessar fronteira — e o §6.5 diz **nunca** repetir uma violacao.
    """
    resultado = await chamar()
    for _ in range(REPETICOES_DE_UPSTREAM):
        if resultado.ok or resultado.error is None:
            return resultado
        if resultado.error.codigo not in (UPSTREAM_TIMEOUT, UPSTREAM_DOWN):
            return resultado
        resultado = await chamar()
    return resultado
