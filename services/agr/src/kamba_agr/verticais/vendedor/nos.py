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

from ... import metricas as metricas_mod
from ...estado import reiniciar, versao_lida
from ...tls.contexto import PREFIXO_DE_CONFIRMACAO, Confirmation, ToolContext
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
from .arestas import AVISOS, INTENCOES, RECUSAS, STALE_CONFIRMATION, VERSAO_DO_GRAFO

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

#: A identificacao quando o nome da loja nao pode entrar num bloco `text` (ver
#: a `_apresentacao`). Identifica na mesma, que e o que o §8.4 pede.
MSG_APRESENTACAO_SEM_NOME: Final = (
    "Sou o assistente automatico desta loja. Posso ajudar com produtos, precos "
    "e pedidos."
)
MSG_CARTAO: Final = (
    "Por seguranca, nao envie dados de cartao ou de conta por aqui. A loja "
    "nunca os pede nesta conversa."
)
MSG_PEDIDO_REGISTADO: Final = (
    "O seu pedido ficou registado. A loja confirma o pagamento e avisa-o aqui."
)

#: Um digito, para as guardas que precisam de saber se um texto leva numeros.
_DIGITO: Final = re.compile(r"\d")

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
        "arma\\w*", "munic\\w*", "aposta\\w*", "credito\\w*", "emprestimo\\w*",
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
    # **Pelo `de_estado` e nao pelo construtor.** A *docstring* dele chama-lhe «o
    # unico caminho para dentro», e a razao e o `normalizar_tenant`: construido a
    # mao, um `tenant_id` em maiusculas dava um `ToolContext` valido que abria
    # uma transaccao a rebentar no `::uuid` — ou, pior, um que a RLS nao casava.
    return ToolContext.de_estado(
        dict(estado),
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


# ------------------------------------------------------------ motivos e avisos

#: Os motivos de *handoff*. Os tres primeiros sao os `handoff_triggers` do
#: `registry/vendedor.yaml`; os dois ultimos vem das linhas do §14 («validador
#: falha 2x» e «COM/PAY/IDX indisponivel»), que mandam ao *handoff* sem serem
#: gatilho de guardrail. Lista fechada: e o que o §11 poe no `interrupt` e o que
#: um humano le para saber porque foi chamado.
MOTIVO_PEDIDO: Final = "pedido_humano"
MOTIVO_RECLAMACAO: Final = "reclamacao_grave"
MOTIVO_SENSIVEL: Final = "saude"
MOTIVO_CITACAO: Final = "citacao"
MOTIVO_UPSTREAM: Final = "upstream"
MOTIVOS_DE_HANDOFF: Final = (
    MOTIVO_PEDIDO,
    MOTIVO_RECLAMACAO,
    MOTIVO_SENSIVEL,
    MOTIVO_CITACAO,
    MOTIVO_UPSTREAM,
)

#: O aviso que corresponde a cada codigo de erro do §6.5. Os que nao estao aqui
#: — as tres violacoes — **nao** viram aviso: o §6.5 manda bloquear e alertar, e
#: explicar ao cliente que o `tenant_id` nao bateu era dizer-lhe que a fronteira
#: existe e onde ela esta.
_AVISO_DO_CODIGO: Final = {
    NOT_FOUND: NOT_FOUND,
    OUT_OF_STOCK: OUT_OF_STOCK,
    PRICE_CHANGED: PRICE_CHANGED,
    LIMIT_EXCEEDED: LIMIT_EXCEEDED,
    VALIDATION_ERROR: VALIDATION_ERROR,
    UPSTREAM_TIMEOUT: UPSTREAM_TIMEOUT,
    UPSTREAM_DOWN: UPSTREAM_DOWN,
}


def _aviso_do_erro(resultado: Any) -> str:
    """O aviso que o `compose` recebe por um `ToolResult` que falhou.

    Uma **violacao** (`ENTITLEMENT_DENIED`, `TOOL_NOT_ALLOWED`,
    `TENANT_MISMATCH`) nao tem aviso proprio: cai em `VALIDATION_ERROR`, que diz
    ao cliente que o pedido nao se pode tratar e nao lhe diz mais nada. E
    deliberado — o §6.5 manda bloquear e levantar alerta de seguranca, e uma
    mensagem especifica era um oraculo sobre a fronteira.
    """
    codigo = getattr(resultado.error, "codigo", "") if resultado.error else ""
    return _AVISO_DO_CODIGO.get(codigo, VALIDATION_ERROR)


def _oferta_crua(dados: Mapping[str, Any]) -> dict[str, str]:
    """Uma oferta como vai para o estado: tres campos e nada mais.

    **Nao leva `score` nem descricao.** O `score` e do `retrieve` e nao diz
    respeito ao cliente; a descricao e texto da PME, e o criterio 5 do KAM-032
    diz que os digitos dela nao sao *facts* — a forma de o garantir e nao haver
    campo, que e a decisao que a `Oferta` do validador ja tomou.
    """
    return {
        "sku": str(dados["sku"]),
        "nome": str(dados.get("nome", "")),
        "preco_tipo": str(dados.get("preco_tipo", "fixo")),
    }


async def _invocar(
    deps: Dependencias,
    estado: Mapping[str, Any],
    nome: str,
    argumentos: dict[str, Any],
    *,
    confirmacao: Confirmation | None = None,
    chave: str | None = None,
) -> Any:
    """Uma tool, pela ToolLayer, com o contexto deste turno.

    A lista de permitidos vai **sempre**: o passo 1 do `invoke` confronta o nome
    com ela, e omiti-la era pedir a camada que confiasse no chamador.
    """
    return await deps.tools.invoke(
        contexto_de_tool(estado),
        nome,
        argumentos,
        allowed=tuple(deps.tools_permitidas),
        confirmation=confirmacao,
        idempotency_key=chave,
    )


# ---------------------------------------------------------------- guardrails


def _luhn(digitos: str) -> bool:
    """O algoritmo de Luhn (§8.4, «PAN com Luhn»).

    **Com Luhn e nao so pelo comprimento**: um `order_id` de dezasseis digitos
    ou um NIF colado a um codigo postal tem o comprimento de um PAN, e redigir a
    mensagem de um cliente que pediu o estado de uma encomenda era recusar o
    turno por nada. Luhn nao prova que e um cartao; prova que **pode** ser, e e
    o que o §8.4 pede.
    """
    soma = 0
    for posicao, caractere in enumerate(reversed(digitos)):
        valor = int(caractere)
        if posicao % 2 == 1:
            valor *= 2
            if valor > 9:
                valor -= 9
        soma += valor
    return soma % 10 == 0


def veredicto_de_entrada(texto: str) -> str:
    """O veredicto da guarda de entrada, por regras (§8.4).

    **A ordem nao e arbitraria.** Dados de cartao vem primeiro porque uma
    mensagem com um PAN e um pedido de credito ao mesmo tempo tem de ser tratada
    como cartao — o §8.4 manda nao guardar —, e o sensivel vem antes da injeccao
    porque uma pergunta sobre medicamentos escrita com «finge que» continua a
    ser uma pergunta sobre medicamentos, e quem decide sobre ela e uma pessoa.

    Publica (sem `_`) porque a bateria a mede caso a caso e porque o KAM-033 a
    substitui: um nome privado obrigava-o a mexer no no.
    """
    for candidato in _PAN.findall(texto):
        digitos = re.sub(r"\D", "", candidato)
        if 13 <= len(digitos) <= 19 and _luhn(digitos):
            return "card_data"
    if _IBAN.search(texto):
        return "card_data"
    if any(padrao.search(texto) for padrao in _SENSIVEL):
        return "sensitive"
    if any(padrao.search(texto) for padrao in _INJECCAO):
        return "injection"
    if any(padrao.search(texto) for padrao in _FRONTEIRA):
        # **Atravessar a fronteira do tenant e `injection`**, nao
        # `out_of_domain`. Os dois vao ao `safe_reply` pela linha 9, mas e o
        # `injection` que nomeia o que isto e: o X-09 do `docs/tecnica/08` §3.7.
        return "injection"
    return "ok"


def violacao_de_saida(texto: str) -> str | None:
    """O que a guarda de saida recusa (§8.4, linhas de saida).

    Devolve o nome da violacao ou `None`. **Nao devolve `bool`**: o caminho e o
    mesmo, mas um painel que conte violacoes sem saber de que tipo manda olhar
    para o sitio errado — a licao que o `get_store_info.py` escreveu ao separar
    o `UPSTREAM_TIMEOUT` do `UPSTREAM_DOWN`.
    """
    if any(padrao.search(texto) for padrao in _PROMESSAS):
        return "promessa"
    if _TELEFONE.search(texto):
        return "pii"
    return None


# --------------------------------------------------------------- classificacao

#: As regras do `classify`, **pela ordem em que correm**, e a ordem e a decisao:
#: «quero falar com uma pessoa sobre o preco» e um pedido de humano e nao uma
#: pergunta de preco. O §15.1 manda as regras primeiro e o modelo so se elas nao
#: decidirem, e e por isso que a lista e curta — cada padrao que entra aqui e um
#: caso que o modelo deixa de ver, e tambem um caso que ninguem reve.
_REGRAS_DE_INTENCAO: Final = (
    ("humano", r"\b(?:humano|pessoa|atendente|funcionari\w*|colega)\b"),
    ("info_loja", r"\b(?:horario|aberto|fecha\w*|morada|endereco|onde (?:fica|estao|e))\b"),
    ("encomenda", r"\b(?:encomenda|pedido|entrega)\b"),
    ("pagamento_estado", r"\b(?:pagamento|paguei|pago|referencia|transferenc\w*)\b"),
    ("comprar", r"\b(?:comprar|quero|levar|encomendar|adiciona\w*)\b"),
    ("preco_stock", r"\b(?:preco|precos|custa|quanto|stock|unidades|disponivel)\b"),
    ("produto", r"\b(?:tem|teem|vendem|procuro|ha)\b"),
)

_INTENCAO_COMPILADA: Final = tuple(
    (nome, re.compile(padrao, re.IGNORECASE)) for nome, padrao in _REGRAS_DE_INTENCAO
)


def intencao_por_regras(texto: str) -> str | None:
    """A intencao que as regras decidem, ou `None` se nenhuma decidir."""
    from ...validador.normalizacao import sem_acento

    normalizado = sem_acento(texto.lower())
    for nome, padrao in _INTENCAO_COMPILADA:
        if padrao.search(normalizado):
            return nome
    return None


#: Uma quantidade escrita pelo cliente: um ou dois digitos isolados. **Nao e um
#: *fact* e nao precisa de ser** — e um **argumento** que o cliente deu, nao um
#: numero que nos afirmamos, que e a distincao do ADR-007. O `propose_cart`
#: valida-o (`qty` entre 1 e 99) e o total vem do backend.
_QUANTIDADE: Final = re.compile(r"(?<!\S)(\d{1,2})(?!\S)")

#: A referencia de uma encomenda no texto do cliente.
_REFERENCIA: Final = re.compile(r"\b([A-Za-z]{1,4}-?\d{1,12})\b")


def quantidade_pedida(texto: str) -> int:
    """Quantas unidades o cliente pediu. Uma, se nao disser."""
    achado = _QUANTIDADE.search(texto)
    if achado is None:
        return 1
    quantos = int(achado.group(1))
    return quantos if 1 <= quantos <= 99 else 1


# --------------------------------------------------------------------- os nos
#
# Cada um e uma fabrica: recebe as dependencias e devolve a funcao que o
# LangGraph chama. E a forma do §7.4 (`g.add_node(name, fn(deps))`), e nao e
# estilo — e o que permite construir dois grafos com portas diferentes no mesmo
# processo, que e o que a bateria faz.
#
# Todos devolvem **so o delta** do estado. Um no que devolvesse o estado inteiro
# reescrevia campos que nao tocou, e com o redutor `add_messages` duplicava a
# janela de mensagens a cada passagem.


def _recorte_da_janela(estado: Mapping[str, Any]) -> dict[str, Any]:
    """O recorte da janela de mensagens, que o §12 atribui ao `ingest`.

    **Nao se faz cortando a lista.** O `messages` tem o redutor `add_messages`, e
    devolver uma lista mais curta **acrescenta-a** a que esta la: a janela
    crescia em vez de encolher. O que remove uma mensagem e um `RemoveMessage`
    com o `id` dela, que e o que o redutor entende.

    O tecto e o `JANELA_MAXIMA` do `checkpointer.py` e nao uma constante daqui:
    a *docstring* do `recortar_janela` do KAM-026 diz por extenso que o valor
    «vem de quem chama … para que a constante tenha **um** dono». E o mesmo
    tecto que faz o `aput` levantar, pelo que recortar com outro numero era
    garantir que um dos dois estava errado.
    """
    from langchain_core.messages import RemoveMessage

    from ...checkpointer import JANELA_MAXIMA

    mensagens = list(estado.get("messages") or ())
    if len(mensagens) <= JANELA_MAXIMA:
        return {}
    a_remover = mensagens[: len(mensagens) - JANELA_MAXIMA]
    # Uma mensagem sem `id` nao se pode remover, e isso nao e erro: o redutor
    # atribui `id` quando converte, pelo que as que ca estao ja o tem. As que
    # nao tiverem ficam, e o `aput` levanta — que e melhor do que remover outra.
    ids = [m.id for m in a_remover if getattr(m, "id", None)]
    return {"messages": [RemoveMessage(id=i) for i in ids]} if ids else {}


def ingest(deps: Dependencias):
    """Linha 1: a entrada do turno. Migra, reinicia e decide se o turno corre."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        # Levanta se o estado vier de uma versao mais recente (§12,
        # versionamento). Nao se degrada: o `VersaoDeEstadoAFrenteError` existe
        # para o turno **nao** correr e a mensagem ficar na fila.
        versao_lida(estado)
        delta = reiniciar()
        recusa = deps.admitir(estado)
        if recusa is not None:
            if recusa not in RECUSAS:
                raise ValueError(
                    f"{recusa!r} nao e uma recusa da linha 4: {list(RECUSAS)}"
                )
            delta["admissao"] = recusa
            return delta
        delta.update(_recorte_da_janela(estado))
        return delta

    return no


def stt(deps: Dependencias):
    """Linhas 5 a 7: a nota de voz. Em Fase 0 **encaminha**, nao transcreve."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        if deps.stt is None:
            # O §14: «STT indisponivel -> `ask_repeat` pedindo texto». A voz e o
            # KAM-036, e ate la este e o comportamento **declarado** — o `r_stt`
            # le isto e manda ao `ask_repeat`.
            return {"stt": {"disponivel": False}}
        try:
            lido = deps.stt.transcrever(estado)
        except Exception:  # noqa: BLE001
            # **Nao se propaga.** Uma excepcao do fornecedor de STT nao e defeito
            # nosso e nao devia matar o turno: o §14 da-lhe uma linha propria, e
            # o cliente recebe o pedido de escrever em texto.
            return {"stt": {"disponivel": False}}
        return {"stt": dict(lido, disponivel=True)}

    return no


def guard_in(deps: Dependencias):
    """Linhas 8 a 10: a guarda de entrada, deterministica minima (KAM-033)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        veredicto = veredicto_de_entrada(_texto_do_cliente(estado))
        delta: dict[str, Any] = {"guard": {"veredicto": veredicto}}
        if veredicto == "sensitive":
            delta["handoff_motivo"] = MOTIVO_SENSIVEL
        return delta

    return no


def classify(deps: Dependencias):
    """Linhas 11 a 17: a intencao. Regras primeiro, modelo so se preciso (§15.1)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        botao = _botao_do_turno(estado)
        if botao.startswith(PREFIXO_DE_CONFIRMACAO):
            # **Um botao de confirmacao nunca passa por modelo.** E dinheiro, e
            # a intencao esta no identificador do botao e nao no texto: um
            # classificador neste caminho era um modelo a decidir se uma
            # encomenda se cria.
            return {"intent": "confirmar"}
        if botao == BOTAO_HUMANO:
            return {"intent": "humano", "handoff_motivo": MOTIVO_PEDIDO}
        if botao == BOTAO_CANCELAR:
            # shortcut: o §7.3 **nao tem no de cancelamento** — nao esta nas
            # vinte e uma entradas —, pelo que o cancelar cai em `outro` e sai
            # com texto estatico. O que nao se pode deixar e o carrinho de pe:
            # um `confirm:` que chegasse depois encontrava `awaiting_confirm` e
            # criava a encomenda que o cliente acabou de cancelar. Larga-se o
            # carrinho. Credor: KAM-037, que desenha os menus por botoes.
            return {"intent": "outro", "cart": None, "stage": "browsing"}

        texto = _texto_do_cliente(estado)
        intencao = intencao_por_regras(texto)
        if intencao is None and deps.classificador is not None:
            escolhida = deps.classificador(texto)
            # Um valor fora das nove **nao** entra no estado: o `r_intent`
            # mandava-o a `other` de qualquer maneira, e escrever no estado uma
            # intencao que o dicionario nao tem punha-a a viajar no checkpoint.
            intencao = escolhida if escolhida in INTENCOES else None
        if intencao == "humano":
            return {"intent": "humano", "handoff_motivo": MOTIVO_PEDIDO}
        return {"intent": intencao or "outro"}

    return no


def retrieve(deps: Dependencias):
    """Linhas 18 e 19: a pesquisa, confrontada com o limiar do IDX."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        resultado = await _invocar(
            deps, estado, "search_catalog", {"query": _texto_do_cliente(estado)}
        )
        if not resultado.ok:
            # O §7.3 da ao `retrieve` **duas** arestas e nenhuma e `handoff`:
            # uma falha do IDX sai pelo `unknown_reply`, com o texto de «nao
            # encontrei». Fica dito porque e uma avaria a parecer-se com uma
            # ausencia; esta registado nas dividas documentais, com credor.
            return {
                "ofertas": (),
                "avisos": _avisos_com(estado, _aviso_do_erro(resultado)),
            }
        acima = [
            candidato
            for candidato in resultado.data.get("candidatos") or ()
            if float(candidato.get("score", 0)) >= deps.limiar_idx
        ]
        return {"ofertas": tuple(_oferta_crua(c) for c in acima)}

    return no


def tools_read(deps: Dependencias):
    """Linha 20: preco e stock das ofertas do turno, como *facts*."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        skus = tuple(o["sku"] for o in estado.get("ofertas") or ())
        if not skus:
            return {}
        resultado = await _com_retry(
            lambda: _invocar(deps, estado, "get_price_stock", {"skus": skus})
        )
        if not resultado.ok:
            return {"avisos": _avisos_com(estado, _aviso_do_erro(resultado))}
        por_sku = {linha["sku"]: linha for linha in resultado.data.get("linhas") or ()}
        ofertas = tuple(
            _oferta_crua(por_sku.get(o["sku"], o)) for o in estado.get("ofertas") or ()
        )
        return {"facts": tuple(resultado.facts), "ofertas": ofertas}

    return no


def cart_build(deps: Dependencias):
    """Linhas 21 e 22: o carrinho do primeiro turno da compra."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        texto = _texto_do_cliente(estado)
        pesquisa = await _invocar(deps, estado, "search_catalog", {"query": texto})
        if not pesquisa.ok:
            return {"avisos": _avisos_com(estado, _aviso_do_erro(pesquisa))}
        candidatos = [
            c
            for c in pesquisa.data.get("candidatos") or ()
            if float(c.get("score", 0)) >= deps.limiar_idx
        ]
        if not candidatos:
            return {"avisos": _avisos_com(estado, NOT_FOUND)}
        escolhido = candidatos[0]
        itens = ({"sku": escolhido["sku"], "qty": quantidade_pedida(texto)},)
        proposta = await _com_retry(
            lambda: _invocar(deps, estado, "propose_cart", {"items": itens})
        )
        if not proposta.ok:
            # Um `OUT_OF_STOCK` ou um `PRICE_CHANGED` **nao** e um carrinho: a
            # oferta fica no estado para o `compose` poder nomear o artigo e o
            # aviso diz o que aconteceu. E a linha 21 — «carrinho criado, **ou**
            # item sem stock/preco alterado (explicacao)».
            return {
                "ofertas": (_oferta_crua(escolhido),),
                "avisos": _avisos_com(estado, _aviso_do_erro(proposta)),
            }
        total = next((f for f in proposta.facts if f.kind == "total"), None)
        if total is None:
            # Um carrinho sem *fact* `total` nao se pode citar e o `compose` nao
            # tem como mostrar o valor. Trata-se como recusa do backend, em vez
            # de se inventar um total.
            return {"avisos": _avisos_com(estado, VALIDATION_ERROR)}
        return {
            "ofertas": (_oferta_crua(escolhido),),
            "facts": tuple(proposta.facts),
            "cart": {
                "cart_id": proposta.data["cart_id"],
                "items": tuple(proposta.data.get("items") or ()),
                "total_fact_id": total.fact_id,
                "expira_at": deps.relogio() + deps.ttl_do_carrinho_s,
            },
            "stage": "awaiting_confirm",
        }

    return no


def confirm_gate(deps: Dependencias):
    """Linhas 23 e 24: as tres perguntas do criterio 4, e as tres por `and`.

    **Nao se devolve qual delas falhou** — a mensagem ao cliente e a mesma, e
    dizer qual era um oraculo, pela razao que o `Confirmation.autoriza` do
    KAM-028 ja tinha escrito.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        carrinho = estado.get("cart")
        botao = _botao_do_turno(estado)
        no_estagio = estado.get("stage") == "awaiting_confirm"
        cita_o_carrinho = (
            isinstance(carrinho, Mapping)
            and bool(carrinho.get("cart_id"))
            and botao == f"{PREFIXO_DE_CONFIRMACAO}{carrinho['cart_id']}"
        )
        esta_valido = (
            isinstance(carrinho, Mapping)
            and float(carrinho.get("expira_at", 0)) > deps.relogio()
        )
        if no_estagio and cita_o_carrinho and esta_valido:
            return {}
        # O `stage` volta a `browsing`: sem isso, um segundo toque encontrava
        # `awaiting_confirm` outra vez e o unico obstaculo passava a ser o
        # `cart_id` — e dois toques no **mesmo** botao citam o mesmo carrinho.
        return {"avisos": _avisos_com(estado, STALE_CONFIRMATION), "stage": "browsing"}

    return no


def create_order(deps: Dependencias):
    """Linhas 25 e 26: a tool `money`, com o botao que o cliente tocou."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        carrinho = estado.get("cart") or {}
        confirmacao = Confirmation(
            # **O botao que o cliente tocou, e nao um reconstruido do carrinho.**
            # Reconstrui-lo fazia o passo 4 do `invoke` comparar o `cart_id`
            # consigo mesmo e dar sempre verdadeiro — a verificacao da
            # confirmacao ficava decorativa, que e o pior defeito possivel numa
            # tool `money`.
            botao=_botao_do_turno(estado),
            contact_id=estado["contact_id"],
            turn_id=estado["turn_id"],
        )
        resultado = await _com_retry(
            lambda: _invocar(
                deps,
                estado,
                "criar_pedido",
                {"cart_id": carrinho.get("cart_id", "")},
                confirmacao=confirmacao,
                chave=chave_do_turno(estado),
            )
        )
        if not resultado.ok:
            delta: dict[str, Any] = {
                "avisos": _avisos_com(estado, _aviso_do_erro(resultado))
            }
            if _e_upstream(resultado):
                delta["handoff_motivo"] = MOTIVO_UPSTREAM
            return delta
        # O `stage` passa a `awaiting_payment` **e o carrinho fica**: o `compose`
        # precisa do `total_fact_id` para mostrar o valor, e um segundo toque e
        # barrado pelo estagio e nao pela ausencia do carrinho.
        return {"stage": "awaiting_payment", "draft": {"dados": dict(resultado.data)}}

    return no


def order_status(deps: Dependencias):
    """Linha 27: o estado de uma encomenda do **proprio** contacto (§6.2)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        achado = _REFERENCIA.search(_texto_do_cliente(estado))
        if achado is None:
            return {"avisos": _avisos_com(estado, NOT_FOUND)}
        resultado = await _com_retry(
            lambda: _invocar(
                deps, estado, "get_order_status", {"order_id": achado.group(1)}
            )
        )
        if not resultado.ok:
            return {"avisos": _avisos_com(estado, _aviso_do_erro(resultado))}
        return {"draft": {"dados": dict(resultado.data)}}

    return no


def tools_info(deps: Dependencias):
    """Linha 27: horario, morada e Plus Code (§6.2, a unica tool ligada)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        resultado = await _com_retry(lambda: _invocar(deps, estado, "get_store_info", {}))
        if not resultado.ok:
            return {"avisos": _avisos_com(estado, _aviso_do_erro(resultado))}
        return {"draft": {"dados": dict(resultado.data)}}

    return no


def _e_upstream(resultado: Any) -> bool:
    return bool(
        resultado.error is not None
        and resultado.error.codigo in (UPSTREAM_TIMEOUT, UPSTREAM_DOWN)
    )


# ----------------------------------------------------------------- o compose


def _apresentacao(deps: Dependencias) -> str | None:
    """A frase que identifica o assistente automatico da loja (criterio 8, §8.4).

    Devolve `None` se a frase da persona nao puder ser um bloco `text` — e **a
    razao e real e foi medida**: o `renderizar` do KAM-032 levanta se um bloco
    `text` tiver digitos, e a frase do `registry/vendedor.yaml` e
    «Sou o assistente automatico de {loja}». Uma loja chamada «Kero 24» fazia o
    turno inteiro rebentar na camada 1, por causa do nome dela.

    Nao se mutila o nome (tirar os digitos dava outro nome) e nao se desliga a
    regra: cai-se para uma frase sem nome, que identifica na mesma — que e o que
    o §8.4 pede, «a 1.a mensagem identifica o assistente automatico da loja».
    O que fica em divida e **mostrar o nome da loja**, e o credor e quem der ao
    §9.1 um bloco para texto com digitos opacos.
    """
    bruta = str(deps.persona.get("apresentacao") or "")
    nome = str(deps.persona.get("loja") or "").strip()
    frase = bruta.replace("{loja}", nome) if nome else bruta.replace(" de {loja}", "")
    frase = frase.replace("{loja}", "")
    if frase and not _DIGITO.search(frase):
        return frase.strip()
    return MSG_APRESENTACAO_SEM_NOME


def _primeiro_turno(estado: Mapping[str, Any]) -> bool:
    """Se esta e a primeira mensagem **da conversa** (criterio 8).

    Conta as mensagens do assistente na janela: zero quer dizer que ainda nao
    respondemos nesta conversa. Nao se olha para o numero de mensagens do
    cliente — numa conversa que comeca com tres mensagens seguidas dele, as tres
    sao o primeiro turno nosso.
    """
    for mensagem in estado.get("messages") or ():
        papel = (
            mensagem.get("role")
            if isinstance(mensagem, Mapping)
            else getattr(mensagem, "type", None)
        )
        if papel in ("assistant", "ai"):
            return False
    return True


def _mostrar_de(oferta: Mapping[str, str], facts: Sequence[Any]) -> list[str]:
    """Que campos de um `item` se podem mostrar, **dados os *facts* que ha**.

    O `renderizar` levanta se o bloco pedir `price` e nao houver *fact* `price`
    para aquele `sku`. Pedir sempre os tres era mandar o `compose` produzir um
    bloco invalido sempre que o `tools_read` nao tivesse corrido — e o turno
    acabava em *handoff* por um defeito nosso.
    """
    mostrar = ["name"]
    sku = oferta["sku"]
    tem = {(f.kind, f.sku) for f in facts}
    if oferta.get("preco_tipo") == "sob_consulta" or ("price", sku) in tem:
        mostrar.append("price")
    if ("stock", sku) in tem:
        mostrar.append("stock")
    return mostrar


def compose(deps: Dependencias):
    """Linha 28: os blocos. **Nenhum numero em prosa** (ADR-007, DoD)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        facts = tuple(estado.get("facts") or ())
        ofertas = tuple(estado.get("ofertas") or ())
        avisos = tuple(estado.get("avisos") or ())
        blocos: list[dict[str, Any]] = []

        if _primeiro_turno(estado):
            apresentacao = _apresentacao(deps)
            if apresentacao:
                blocos.append({"type": "text", "text": apresentacao})

        for aviso in avisos:
            blocos.append({"type": "text", "text": FRASE_DO_AVISO[aviso]})

        for oferta in ofertas:
            blocos.append(
                {
                    "type": "item",
                    "sku": oferta["sku"],
                    "show": _mostrar_de(oferta, facts),
                }
            )

        carrinho = estado.get("cart")
        # **O `total` so se cita se o *fact* dele for deste turno.** O carrinho
        # sobrevive ao turno (tem de: o fluxo de dois turnos depende disso) e os
        # *facts* **nao** (§5.3: «so deste turno»), pelo que um `total` do turno
        # anterior nao tem *fact* para citar — e o `renderizar` levanta, com
        # razao. Citar um valor sem *fact* era precisamente o que o ADR-007
        # proibe, e e a linha «facts obsoletos entre turnos» do §9.2: quem o
        # quiser mostrar outra vez revalida no backend e ganha um *fact* novo.
        tem_o_total = isinstance(carrinho, Mapping) and any(
            f.kind == "total" and f.fact_id == carrinho.get("total_fact_id")
            for f in facts
        )
        if tem_o_total:
            blocos.append({"type": "total", "fact_id": carrinho["total_fact_id"]})
            if estado.get("stage") == "awaiting_confirm":
                blocos.append(
                    {
                        "type": "buttons",
                        "ids": [
                            f"{PREFIXO_DE_CONFIRMACAO}{carrinho['cart_id']}",
                            BOTAO_CANCELAR,
                            BOTAO_HUMANO,
                        ],
                    }
                )

        if estado.get("stage") == "awaiting_payment":
            blocos.append({"type": "text", "text": MSG_PEDIDO_REGISTADO})

        blocos.extend(_blocos_dos_dados(estado))

        if not blocos:
            blocos.append({"type": "text", "text": MSG_NAO_ENTENDI})
        return {"draft": {"blocos": tuple(blocos)}}

    return no


def _blocos_dos_dados(estado: Mapping[str, Any]) -> list[dict[str, Any]]:
    """O que o `tools_info` e o `order_status` deixaram para o `compose` dizer.

    **E aqui que uma lacuna do §9.1 aparece, e fica escrita.** Os cinco blocos
    do validador sao `text` (sem digitos), `item` (preso a um `sku`), `total`,
    `buttons` e `datetime` (preso a um *fact*). Uma morada, um Plus Code e uma
    referencia de encomenda **tem digitos e nao sao *facts* numericos**: nenhum
    dos cinco os leva, e escreve-los num `text` faz o `renderizar` levantar.

    Em Fase 0 diz-se o que **nao** tem digitos — o nome e a zona da loja, a
    palavra do estado da encomenda — e o resto fica em divida, com credor: quem
    der ao §9.1 um bloco para uma referencia opaca. Mutilar o valor (tirar-lhe
    os digitos) era pior do que o calar, porque parecia certo.
    """
    rascunho = estado.get("draft")
    dados = rascunho.get("dados") if isinstance(rascunho, Mapping) else None
    if not isinstance(dados, Mapping):
        return []
    blocos: list[dict[str, Any]] = []
    for campo in ("nome", "zona", "estado"):
        valor = str(dados.get(campo) or "").strip()
        if valor and not _DIGITO.search(valor):
            blocos.append({"type": "text", "text": valor})
    return blocos


# ---------------------------------------------------------------- o validate


def validate(deps: Dependencias):
    """Linhas 29 a 31: a camada 1 e a camada 2 do §9.1, nesta ordem."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        rascunho = estado.get("draft") or {}
        blocos = list(rascunho.get("blocos") or ())
        facts = tuple(estado.get("facts") or ())
        ofertas = _ofertas_de(estado)
        repeticoes = int(estado.get("citation_retries") or 0)

        try:
            saida = renderizar(blocos, facts, ofertas)
        except BlocoInvalidoError:
            # **Um bloco invalido e defeito do `compose`, nao veredicto do
            # validador**, e nao ha codigo para ele: os sete veredictos do §9.1
            # sao todos sobre numeros do texto, e o `Verdict` recusa-se a
            # existir sem um deles. Conta-se nos mesmos dois contadores a mao —
            # o `medir_validacao` pedia um `Verdict` que nao se pode construir —
            # e segue pelo caminho da falha, que e o certo: a resposta nao sai.
            _contar_validacao(deps, estado, ok=False, repetiu=repeticoes + 1 <= 1)
            return {
                "draft": dict(rascunho, ok=False, erros=("bloco_invalido",), texto="", botoes=()),
                "citation_retries": repeticoes + 1,
                "handoff_motivo": MOTIVO_CITACAO,
            }

        veredicto = validar(saida.texto, facts, Policy(), ofertas)
        novas = repeticoes + (0 if veredicto.ok else 1)
        if deps.metricas is not None:
            medir_validacao(
                deps.metricas,
                estado["vertical"],
                veredicto,
                repetiu=not veredicto.ok and novas <= 1,
                handoff=not veredicto.ok and novas > 1,
                # **Sempre `True` neste grafo, e e uma propriedade e nao uma
                # coincidencia**: o `compose` so produz blocos, nunca prosa
                # livre. O `render_only_ratio` do §9.2 mede isso, e o dia em que
                # alguem puser um modelo a escrever a resposta, este argumento
                # passa a depender de onde ela veio.
                so_blocos=True,
            )
        return {
            "draft": dict(
                rascunho,
                ok=veredicto.ok,
                erros=veredicto.codigos,
                texto=saida.texto,
                botoes=saida.botoes,
            ),
            "citation_retries": novas,
            **({} if veredicto.ok else {"handoff_motivo": MOTIVO_CITACAO}),
        }

    return no


def _contar_validacao(
    deps: Dependencias, estado: Mapping[str, Any], *, ok: bool, repetiu: bool
) -> None:
    """Os contadores do §9.2 quando nao ha `Verdict` para o `medir_validacao`."""
    if deps.metricas is None:
        return
    vertical = estado["vertical"]
    deps.metricas.contar(metricas_mod.METRICA_VALIDATE, vertical)
    if not ok:
        deps.metricas.contar(metricas_mod.METRICA_VALIDATE_FALHAS, vertical)
    if repetiu:
        deps.metricas.contar(metricas_mod.METRICA_VALIDATE_REPETICOES, vertical)
    else:
        deps.metricas.contar(metricas_mod.METRICA_VALIDATE_HANDOFF, vertical)
    deps.metricas.contar(metricas_mod.METRICA_RENDER_ONLY, vertical)


# ----------------------------------------------------------------- a saida


def guard_out(deps: Dependencias):
    """Linhas 32 e 33: promessas proibidas e fuga de PII (§8.4)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        rascunho = estado.get("draft") or {}
        violacao = violacao_de_saida(str(rascunho.get("texto") or ""))
        if violacao is None:
            return {}
        return {"draft": dict(rascunho, violacao=violacao)}

    return no


def _resposta_estatica(texto: str) -> dict[str, Any]:
    """Um rascunho ja pronto, que **nao** passa pelo `validate` (linha 34).

    E por isso que nenhum destes textos leva digitos: a aresta 34 vai direita ao
    `send`, pelo que um numero aqui era um numero sem *fact* a chegar ao cliente
    por um caminho que o validador nao ve. Ha ensaio que o mede sobre todos.
    """
    return {"draft": {"blocos": (), "texto": texto, "botoes": (), "ok": True, "erros": ()}}


def unknown_reply(deps: Dependencias):
    """Linha 19 -> 34: abaixo do limiar do IDX."""

    async def no(_estado: dict[str, Any]) -> dict[str, Any]:
        return _resposta_estatica(MSG_NAO_ENTENDI)

    return no


def ask_repeat(deps: Dependencias):
    """Linha 6 -> 34: a nota de voz que nao se percebeu (§10)."""

    async def no(_estado: dict[str, Any]) -> dict[str, Any]:
        return _resposta_estatica(MSG_REPETIR)

    return no


def safe_reply(deps: Dependencias):
    """Linhas 9, 17 e 33 -> 34: o texto seguro, escolhido pelo veredicto."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        guarda = estado.get("guard")
        veredicto = guarda.get("veredicto") if isinstance(guarda, Mapping) else None
        if veredicto == "card_data":
            # O §8.4 manda **avisar o cliente** e nao guardar: a mensagem e
            # outra, e e a unica das tres que diz ao cliente o que fazer.
            return _resposta_estatica(MSG_CARTAO)
        return _resposta_estatica(MSG_FORA_DE_AMBITO)

    return no


def send(deps: Dependencias):
    """Linha 35: o Outbound, com `idempotency_key = turn_id:seq`."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        rascunho = estado.get("draft") or {}
        texto = str(rascunho.get("texto") or "")
        if not texto:
            # Um envio vazio nao e um envio. Acontece se um no anterior falhar a
            # escrever o rascunho, e e melhor nao enviar nada do que enviar uma
            # mensagem em branco a um cliente.
            return {}
        deps.saida.enfileirar(
            estado,
            texto,
            chave=chave_do_turno(estado),
            botoes=tuple(rascunho.get("botoes") or ()),
        )
        # A resposta entra na janela: e o que faz o `_primeiro_turno` do turno
        # seguinte saber que ja falamos, e o que o §12 manda guardar.
        return {"messages": [{"role": "assistant", "content": texto}]}

    return no


# ---------------------------------------------------------------- o handoff


def _handoff_id(estado: Mapping[str, Any]) -> str:
    """`sha256(thread_id:handoff_seq)` — estavel entre re-execucoes (§11)."""
    cru = f"{estado['thread_id']}:{int(estado.get('handoff_seq') or 0)}"
    return hashlib.sha256(cru.encode()).hexdigest()


def handoff_prepare(deps: Dependencias):
    """Linhas 36 e 37: abre o *handoff*, idempotente por `handoff_id` (§11)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        hid = _handoff_id(estado)
        motivo = str(estado.get("handoff_motivo") or MOTIVO_PEDIDO)
        if deps.hnd is None:
            return _degradado(hid)
        try:
            referencia = deps.hnd.abrir(
                handoff_id=hid, estado=estado, motivo=motivo, resumo=_resumo(estado)
            )
        except HandoffIndisponivel:
            # O §11: `HandoffUnavailable` -> `degraded` -> aresta 37 -> `send`.
            # O §14 acrescenta a conversa em `pausada`, que e do CHR e nao daqui.
            return _degradado(hid)
        deps.saida.enfileirar(estado, MSG_HUMANO_A_CAMINHO, chave=f"{hid}:msg")
        # O `handoff_seq` sobe **aqui** e nao no `handoff_close`: e o que faz o
        # *handoff* seguinte da mesma conversa ter outro `handoff_id`. Se subisse
        # no fim, dois *handoffs* seguidos partilhavam o identificador e o
        # segundo era engolido pela idempotencia do primeiro.
        return {
            "handoff": {
                "id": hid,
                "external_id": referencia,
                "status": "waiting",
                "motivo": motivo,
            },
            "handoff_seq": int(estado.get("handoff_seq") or 0) + 1,
        }

    return no


def _degradado(hid: str) -> dict[str, Any]:
    """O ramo `degraded` da linha 37, com a mensagem que o `send` leva."""
    resposta = _resposta_estatica(MSG_DEGRADADO)
    resposta["handoff"] = {"id": hid, "status": "degraded"}
    return resposta


def _resumo(estado: Mapping[str, Any]) -> str:
    """O resumo que vai ao humano (§11, `summarise(state)`).

    **Sem o texto do cliente.** O que o colega precisa de saber e porque foi
    chamado e em que ponto estava a conversa; o conteudo esta no Chatwoot, que e
    onde ele o vai ler. Copiar a mensagem para aqui era passar texto do cliente
    por um campo que o §6.4 nao cobre.
    """
    partes = [f"motivo={estado.get('handoff_motivo') or MOTIVO_PEDIDO}"]
    if estado.get("intent"):
        partes.append(f"intencao={estado['intent']}")
    if estado.get("stage"):
        partes.append(f"estagio={estado['stage']}")
    if estado.get("avisos"):
        partes.append("avisos=" + ",".join(estado["avisos"]))
    return "; ".join(partes)


def handoff_wait(deps: Dependencias):
    """Linha 38: **so** o `interrupt`, na primeira linha e sem `try/except` (§11)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        from langgraph.types import interrupt

        # Primeira linha, e nada antes dela. Na retoma o no reinicia do
        # principio: um efeito antes do `interrupt` corria duas vezes, e e o
        # defeito 6 do §7.1 que este par de nos existe para corrigir.
        desfecho = interrupt(
            {
                "handoff_id": (estado.get("handoff") or {}).get("id"),
                "motivo": estado.get("handoff_motivo") or MOTIVO_PEDIDO,
            }
        )
        anterior = dict(estado.get("handoff") or {})
        resultado = desfecho.get("outcome") if isinstance(desfecho, Mapping) else desfecho
        return {"handoff": dict(anterior, status="resumed", outcome=resultado)}

    return no


def handoff_close(deps: Dependencias):
    """Linha 39: fecha o *handoff*; no `timeout` manda as alternativas (§11)."""

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        handoff = dict(estado.get("handoff") or {})
        if handoff.get("outcome") == "timeout":
            deps.saida.enfileirar(
                estado, MSG_ALTERNATIVAS, chave=f"{handoff.get('id')}:timeout"
            )
        return {"stage": "done"}

    return no


#: Os vinte e um nos pelo nome do §7.4. E a tabela que o `build_graph` percorre,
#: e e ela que faz «um no na tabela de arestas sem funcao» ser impossivel: o
#: `build_graph` levanta se as duas listas nao baterem.
NOS_DO_GRAFO: Final = {
    "ingest": ingest,
    "stt": stt,
    "guard_in": guard_in,
    "classify": classify,
    "retrieve": retrieve,
    "tools_read": tools_read,
    "cart_build": cart_build,
    "confirm_gate": confirm_gate,
    "create_order": create_order,
    "order_status": order_status,
    "tools_info": tools_info,
    "compose": compose,
    "validate": validate,
    "guard_out": guard_out,
    "unknown_reply": unknown_reply,
    "ask_repeat": ask_repeat,
    "safe_reply": safe_reply,
    "send": send,
    "handoff_prepare": handoff_prepare,
    "handoff_wait": handoff_wait,
    "handoff_close": handoff_close,
}
