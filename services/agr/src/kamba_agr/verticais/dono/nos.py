"""Os nos do grafo do dono: os quatro proprios, e a tabela com os reutilizados.

## Doze importados, quatro escritos

Os doze do `NOS_REUTILIZADOS` vem do `verticais/vendedor/nos.py` tal como
estao: importam-se, nao se copiam nem se envolvem. Os quatro deste ficheiro sao
os que o §5.4 poe na coluna do que e **proprio** — o texto de persona
(`compose`, `safe_reply`, `ask_repeat`) — e a decisao da intencao (`classify`),
porque as intencoes do dono nao sao as de um cliente.

**As `Dependencias` sao as do Vendedor**, pela razao que o `nos.py` de Servicos
escreveu: doze nos recebem aquele tipo, e um tipo proprio era um adaptador por
no. O que muda por persona — a `persona` e a `tools_permitidas` — sao campos,
vindos do `registry/dono.yaml` pelo `grafos.compilar`, como nas verticais.

## O catalogo (KAM-119)

As quatro tools do modulo `catalogo` estao ligadas, e a conversa delas e o
`catalogo.py` deste pacote: o `classify` da as intencoes `modulos` (palavras do
catalogo) e `catalogo` (um botao do catalogo, uma foto, uma referencia `PRD-…`,
ou uma resposta a um rascunho a espera), e as duas vao ao `confirm`, como a
resposta a um orcamento. Num tenant sem o modulo, as tools recusam no passo 2 e
o dono e avisado. **Nenhum texto deste ficheiro leva digitos** (o
`_resposta_estatica` nao passa pelo validador), e ha ensaio que o mede.

## O botao chega; o texto ainda nao

O `id` de um botao chega ao estado pelo `agent_invocation.botao` (KAM-211), e o
`confirm` — o quinto no proprio — chama o portao das accoes sensiveis
(`kamba_agr/dono/accoes.py`) com ele. **O texto continua a nao chegar** (o
`estado_inicial` nasce com `messages: []`, decisao do KAM-186): as regras do
`classify` leem a janela `messages` como todas as verticais, e no processo um
turno de texto do dono cai em `outro` pela mesma razao que o de um cliente.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Final, NamedTuple

from ...dono import accoes
from ...tls import orcamento as orcamento_repo
from ...tls.erros import (
    ENTITLEMENT_DENIED,
    LIMIT_EXCEEDED,
    NOT_FOUND,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    VALIDATION_ERROR,
)
from ..vendedor.nos import (
    BOTAO_HUMANO,
    Dependencias,
    botoes_seguros_da_guarda,
    draft_prepare,
    draft_wait,
    guard_in,
    guard_out,
    handoff_close,
    handoff_prepare,
    handoff_wait,
    ingest,
    send,
    stt,
    texto_seguro_da_guarda,
    tools_info,
    validate,
)
from ..vendedor.nos import (
    MOTIVO_PEDIDO,
    _blocos_dos_dados,
    _invocar,
    _primeiro_turno,
    _resposta_estatica,
    _texto_do_cliente,
)
from ...orcamento import regras
from ...orcamento.regras import NOME_NEUTRO
from . import catalogo
from .arestas import INTENCOES

#: As tools do Assistente do Dono, pela ordem do `registry/dono.yaml`. So para
#: os ensaios e para quem compile o grafo sem o registo: o processo usa as do
#: registo, pelo `grafos.compilar`.
TOOLS_DO_DONO: Final = (
    "get_store_info",
    "create_product_draft",
    "ask_missing_fields",
    "publish_product",
    "get_catalog_status",
    "submit_quote",
)

#: As palavras que decidem cada intencao, **pela ordem em que correm**: «quero
#: falar com uma pessoa sobre o catalogo» e um pedido de humano. Sem acentos —
#: o texto compara-se sem eles.
REGRAS_DE_INTENCAO: Final = (
    ("humano", ("falar com uma pessoa", "falar com alguem", "atendente", "humano")),
    ("info_loja", ("horario", "onde fica", "morada", "endereco", "aberto")),
    # KAM-220. **Antes do `modulos`**, que tem «preco»: «que pedidos de
    # orcamento tenho?» e uma pergunta pelos pendentes, e nao pelo catalogo.
    ("orcamento", ("orcamento", "pendente", "proposta")),
    (
        "modulos",
        (
            "produto",
            "catalogo",
            "publica",
            "artigo",
            "preco",
            "stock",
            "foto",
            "rascunho",
            "campos",
        ),
    ),
)


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def intencao_por_regras(texto: str) -> str | None:
    """A intencao pelas palavras, ou `None` se nenhuma regra decidir."""
    limpo = _sem_acentos(texto)
    for intencao, palavras in REGRAS_DE_INTENCAO:
        if any(palavra in limpo for palavra in palavras):
            return intencao
    return None


def _botao_do_turno(estado: Mapping[str, Any]) -> str:
    """O `id` do botao deste turno: o `botao` do estado (KAM-211), e so num turno
    `interactive`. **Nunca o texto da janela**: a janela acumula as mensagens de
    turnos anteriores pelo *checkpoint*, e um `confirm:{uuid}` escrito antes
    valia como toque num `interactive` sem `botao` — o «texto que imita um
    botao» do criterio (achado 2 da revisao adversarial do KAM-211)."""
    if estado.get("input_kind") != "interactive":
        return ""
    botao = estado.get("botao")
    return botao if isinstance(botao, str) else ""


# ---------------------------------------------------------------- o classify


def classify(deps: Dependencias):
    """Transicoes 11 a 14: a intencao. Regras primeiro, modelo so se preciso.

    **Nenhuma intencao chama uma tool de escrita**: um texto («sim», «confirmo,
    podes publicar») nunca confirma nada — so o botao `confirm:{action_id}` do
    mesmo contacto, e isso e o `dono/accoes.py`, fora do grafo. As leituras
    do catalogo (KAM-119) decidem so se ha um rascunho a espera de resposta.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        botao = _botao_do_turno(estado)
        # **So a forma de um botao `confirm:{uuid}` da a intencao `confirmar`**,
        # e so num turno `interactive`: um texto com a mesma forma nao passa
        # pelo `_botao_do_turno` (KAM-211, «texto que imita um botao»).
        if accoes.accao_do_botao(botao) is not None:
            return {"intent": "confirmar"}
        if botao == BOTAO_HUMANO:
            return {"intent": "humano", "handoff_motivo": MOTIVO_PEDIDO}
        texto = _texto_do_cliente(estado)
        if catalogo.e_do_catalogo(estado, texto):
            # KAM-119: um botao do catalogo, uma foto, ou uma referencia `PRD-…`.
            return {"intent": "catalogo"}
        if e_resposta_de_orcamento(texto):
            # KAM-220. **Antes das palavras e do modelo**: um valor escrito pelo
            # dono e a resposta a um pedido, e um classificador aqui era um
            # modelo a decidir se um numero e um preco.
            #
            # KAM-119: **sem referencia `ORC-…`, sem pedido de orcamento a
            # espera e com um rascunho do catalogo a espera de resposta**, o
            # valor e o preco desse rascunho — vai ao eco, e nao se grava.
            partes = _partes_da_resposta(texto)
            if (
                partes.referencia is None
                # Com condicoes e um orcamento, e nunca o preco de um rascunho
                # (achado 11 da revisao): o catalogo lia o texto todo como valor.
                and partes.condicoes is None
                and partes.erro is None
                and not await _ha_pendentes(deps, estado)
                and await catalogo.ha_resposta_a_dar(deps, estado)
            ):
                return {"intent": "catalogo"}
            return {"intent": "responder_orcamento"}
        intencao = intencao_por_regras(texto)
        if intencao is None and deps.classificador is not None:
            escolhida = deps.classificador(texto)
            # Um valor fora da lista **nao** entra no estado: o `r_intent`
            # mandava-o a `other` de qualquer maneira.
            intencao = escolhida if escolhida in INTENCOES else None
        resolvida = intencao or "outro"
        if resolvida == "outro" and _primeiro_turno(estado) and await _ha_pendentes(deps, estado):
            # KAM-220, criterio 2 do KAM-123: **os pendentes aparecem na
            # primeira mensagem do dono**, que e quase sempre um cumprimento.
            # So no lugar do `outro`: um pedido de humano, de informacao ou do
            # catalogo continua a ser respondido pelo que e.
            resolvida = "orcamento"
        if (
            resolvida == "outro"
            and catalogo.regras.parece_resposta(texto)
            and await catalogo.ha_resposta_a_dar(deps, estado)
        ):
            # KAM-119: o dono a responder as perguntas de um rascunho («camisa
            # polo», «azul») nao tem palavra que o diga. So no lugar do `outro`,
            # e **nunca** um cumprimento ou uma pergunta (achado 3 da revisao):
            # «bom dia» ia parar a `entrega`. A leitura custa uma linha de
            # `tool_audit` por turno destes, e num tenant sem o modulo e um
            # `ENTITLEMENT_DENIED` — o preco de nao guardar estado proprio.
            resolvida = "catalogo"
        delta: dict[str, Any] = {"intent": resolvida}
        if resolvida == "humano":
            delta["handoff_motivo"] = MOTIVO_PEDIDO
        return delta

    return no


#: Uma referencia `ORC-…` no texto do dono: oito das dezasseis letras do
#: `regras.referencia_interna`, sem distinguir maiusculas.
_REFERENCIA_NO_TEXTO: Final = re.compile(r"\bORC-([A-HJ-NP-R]{8})\b", re.IGNORECASE)

#: Sem referencia, so e resposta um valor com algarismos ou com o multiplicador
#: (achado 10 da revisao): «dois» ou «uma» sozinhos sao conversa, e nao um preco.
_FORMA_DE_VALOR: Final = re.compile(r"\d|\bmil\b|\bmilh", re.IGNORECASE)

#: As palavras de ligacao que o dono escreve a volta do valor e que o *parser*
#: do KAM-123 nao tem de ler: «120 mil para o ORC-…», «ORC-…: 120 mil».
_LIGACAO: Final = re.compile(r"\b(?:para|pro|o|do|ao|pedido|referencia|ref)\b|[:;,\-]", re.IGNORECASE)


#: A marca que separa o valor das condicoes (KAM-230). **Decisao do fundador de
#: 2026-11-20, opcao A**: o dono escreve «Condições:», com ou sem acento e sem
#: distinguir maiusculas, e o que vem antes e o valor, e o que vem depois sao as
#: condicoes. Recusadas a mudanca de linha (B), que uma quebra acidental mudava
#: de sentido, e a separacao automatica (C), que era adivinhar onde acaba o valor.
_MARCA_DAS_CONDICOES: Final = re.compile(r"\bcondi[cç][oõ]es\s*:", re.IGNORECASE)

#: As duas formas de escrever mal a marca: duas vezes, ou sem nada a seguir.
CONDICOES_REPETIDAS: Final = "condicoes_repetidas"
CONDICOES_VAZIAS: Final = "condicoes_vazias"


class _Resposta(NamedTuple):
    """A resposta do dono partida: a referencia, o texto do valor, as condicoes.

    `erro` e um de `CONDICOES_REPETIDAS` ou `CONDICOES_VAZIAS` quando a marca esta
    mal escrita; entao o valor e as condicoes nao contam, e nada vai a tool.
    """

    referencia: str | None
    valor: str
    condicoes: str | None = None
    erro: str | None = None


def _partes_da_resposta(texto: str) -> _Resposta:
    """A referencia, o texto do valor e as condicoes, separados pela marca.

    **O valor e o que vem antes da marca, e so ele passa pelas palavras de
    ligacao e pelo *parser***: as condicoes ficam como o dono as escreveu, e quem
    as le e a guarda do KAM-033 e o `screen`. A referencia `ORC-…` tira-se do
    texto inteiro, dos dois lados: e um identificador para o sistema, e nao
    conteudo para o cliente.
    """
    # NFC antes de procurar a marca (achado 9 da revisao): «Condições» composta
    # por letra e acento combinante nao casava, e o texto ia ao modelo.
    texto = unicodedata.normalize("NFC", texto)
    achada = _REFERENCIA_NO_TEXTO.search(texto)
    referencia = f"ORC-{achada.group(1).upper()}" if achada else None
    sem_referencia = _REFERENCIA_NO_TEXTO.sub(" ", texto)
    pedacos = _MARCA_DAS_CONDICOES.split(sem_referencia)
    antes = pedacos[0]
    if len(pedacos) > 1:
        # O ponto que fecha a frase do valor antes da marca («120 mil.
        # Condições: …») e pontuacao, e nao parte do valor: o *parser* lia
        # «120 mil.» como ambiguo. Um so, e so com a marca.
        antes = antes.rstrip()
        antes = antes[:-1] if antes.endswith(".") else antes
    valor = " ".join(_LIGACAO.sub(" ", antes).split())
    if len(pedacos) > 2:
        return _Resposta(referencia, valor, erro=CONDICOES_REPETIDAS)
    if len(pedacos) == 2:
        condicoes = " ".join(pedacos[1].split())
        if not condicoes:
            return _Resposta(referencia, valor, erro=CONDICOES_VAZIAS)
        return _Resposta(referencia, valor, condicoes)
    return _Resposta(referencia, valor)


def e_resposta_de_orcamento(texto: str) -> bool:
    """Se o texto do dono e a resposta a um pedido: uma referencia, ou um valor so.

    **Um valor so**: o mesmo *parser* deterministico que o `submit_quote` usa, e
    nao uma pergunta ao modelo. «120 mil» e uma resposta; «quanto vendi hoje?»
    nao e, e segue o caminho de sempre.
    """
    partes = _partes_da_resposta(texto)
    if partes.referencia is not None:
        return True
    if not _FORMA_DE_VALOR.search(partes.valor):
        return False
    try:
        regras.ler_valor_do_dono(partes.valor)
    except regras.ValorRecusadoError:
        return False
    return True


async def _qual_pedido(deps: Dependencias, estado: Mapping[str, Any], referencia: str | None) -> str | None:
    """A referencia `ORC-…` a que a resposta se refere, ou `None` se nao der para saber.

    Com referencia escrita, e essa: quem a resolve **dentro do tenant** e o
    executor do `submit_quote`, e uma de outro tenant ou inventada da
    `NOT_FOUND`. Sem ela, **so** se houver um pedido a espera e um so: com dois,
    a resposta ia para o cliente errado, e o dono escolhe pela referencia.
    """
    if referencia is not None:
        return referencia
    ler = getattr(deps.orcamentos, "pendentes", None)
    if ler is None:
        return None
    # **O filtro antes de contar, e a lista inteira** (achado 4 da revisao): com
    # um `LIMIT 2` antes do filtro, um `aguarda_janela` mais novo tirava um dos
    # dois `pedido` da conta, e a resposta ia para o outro. Uma lista cortada
    # pelo limite tambem nao decide: pode haver outro a espera fora dela.
    lidos = await ler(estado["tenant_id"], limite=LIMITE_DA_ESCOLHA)
    if len(lidos) >= LIMITE_DA_ESCOLHA:
        return None
    abertos = [p for p in lidos if p.estado in (regras.PEDIDO, regras.RESPONDIDO)]
    return abertos[0].referencia if len(abertos) == 1 else None


#: Quantos abertos se leem para escolher o pedido de uma resposta sem
#: referencia. Com tantos ou mais, pede-se a referencia. *Proposta*.
LIMITE_DA_ESCOLHA: Final = 20


async def _responder_orcamento(deps: Dependencias, estado: Mapping[str, Any]) -> dict[str, Any]:
    """O texto do dono ao `submit_quote`, e o eco com o botao (KAM-220, criterio 3).

    **Pela ToolLayer**, com os oito passos do §6.1: o entitlement `orcamento`, os
    argumentos sem o tenant nem o contacto, a `tool_audit` com o *fact*
    `quote_price`. O passo 4 esta dispensado para esta tool (decisao do fundador
    de 2026-11-19, opcao C): ela **so grava**, e o que envia e o botao
    `confirm:{action_id}` que este eco leva.

    O sistema nao le o valor aqui: passa o **texto** a tool, e e o *parser* do
    KAM-123 quem o le ou o recusa.

    **As condicoes vem depois da marca «Condições:»** (KAM-230, decisao do
    fundador de 2026-11-20): vao a tool no argumento `condicoes`, e a tool passa-as
    pela guarda do KAM-033 e pelo `screen`. Uma marca repetida ou sem nada a
    seguir recusa antes de chamar a tool, e nada se grava.
    """
    partes = _partes_da_resposta(_texto_do_cliente(estado))
    if partes.erro is not None:
        return _resposta_estatica(MSG_CONDICOES_MAL_ESCRITAS)
    try:
        qual = await _qual_pedido(deps, estado, partes.referencia)
    except Exception:  # noqa: BLE001 — a base em baixo diz-se, e nao rebenta
        return _resposta_estatica(MSG_PENDENTES_INDISPONIVEIS)
    if qual is None:
        return _resposta_estatica(MSG_QUAL_PEDIDO)
    if not partes.valor:
        return _resposta_estatica(MSG_VALOR_POR_REESCREVER)
    argumentos = {"referencia": qual, "valor": partes.valor}
    if partes.condicoes is not None:
        argumentos["condicoes"] = partes.condicoes
    resultado = await _invocar(deps, estado, "submit_quote", argumentos)
    if not resultado.ok:
        return _resposta_estatica(_frase_da_recusa(resultado.error))
    resposta = _resposta_estatica(
        "\n".join((MSG_ECO, str(resultado.data["previsao"]), MSG_ECO_BOTAO))
    )
    resposta["draft"]["botoes"] = (f"confirm:{resultado.data['action_id']}",)
    return resposta


def _frase_da_recusa(erro: Any) -> str:
    codigo = getattr(erro, "codigo", "")
    detalhe = getattr(erro, "detalhe", "")
    if codigo == VALIDATION_ERROR and detalhe in regras.RECUSAS_DO_VALOR:
        return MSG_VALOR_POR_REESCREVER
    if codigo == VALIDATION_ERROR and detalhe in regras.RECUSAS_DAS_CONDICOES:
        # KAM-230: as condicoes tem frase propria; o valor estava certo.
        return MSG_CONDICOES_POR_REESCREVER
    if codigo == VALIDATION_ERROR and detalhe == orcamento_repo.FECHADO:
        return MSG_PEDIDO_FECHADO
    if codigo == NOT_FOUND:
        return MSG_PEDIDO_NAO_ENCONTRADO
    if codigo == ENTITLEMENT_DENIED:
        return MSG_SEM_MODULO_DE_ORCAMENTO
    return MSG_NAO_CONSEGUI


async def _ha_pendentes(deps: Dependencias, estado: Mapping[str, Any]) -> bool:
    ler = getattr(deps.orcamentos, "pendentes", None)
    if ler is None:
        return False
    try:
        return bool(await ler(estado["tenant_id"], limite=1))
    except Exception:  # noqa: BLE001 — uma leitura que falha nao rebenta o turno
        return False


async def _blocos_dos_pendentes(deps: Dependencias, estado: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Os blocos da lista dos pendentes e as ofertas que o `validate` precisa.

    **Nenhum valor e nenhuma quantidade**: cada pendente e a referencia `ORC-…`
    (letras) num bloco `text` e o `sku` num bloco `item` so com o `sku`, que e
    a forma que o *renderer* do KAM-032 deixa citar. A quantidade tem digitos e
    nao e *fact*: nenhum dos cinco blocos do §9.1 a leva (a divida 124), e fica
    escrita como limite no bloco do KAM-220.
    """
    ler = getattr(deps.orcamentos, "pendentes", None)
    if ler is None:
        return [{"type": "text", "text": MSG_PENDENTES_INDISPONIVEIS}], []
    try:
        pendentes = await ler(estado["tenant_id"], limite=LIMITE_DE_PENDENTES)
    except Exception:  # noqa: BLE001 — a base em baixo diz-se, e nao rebenta
        return [{"type": "text", "text": MSG_PENDENTES_INDISPONIVEIS}], []
    if not pendentes:
        return [{"type": "text", "text": MSG_SEM_PENDENTES}], []
    blocos: list[dict[str, Any]] = [{"type": "text", "text": MSG_PENDENTES}]
    ofertas: dict[str, dict[str, str]] = {}
    for pendente in pendentes:
        blocos.append({"type": "text", "text": pendente.referencia})
        blocos.append({"type": "item", "sku": pendente.sku, "show": []})
        ofertas[pendente.sku] = {
            "sku": pendente.sku,
            "nome": NOME_NEUTRO,
            "preco_tipo": "sob_consulta",
        }
    blocos.append({"type": "text", "text": MSG_COMO_RESPONDER})
    return blocos, list(ofertas.values())


#: Quantos pendentes a lista mostra, dos mais novos (o `pendentes` ordena
#: assim). *Proposta*: cabe numa mensagem do WhatsApp sem a cortar.
LIMITE_DE_PENDENTES: Final = 5


# ---------------------------------------------------------------- o confirm


def confirm(deps: Dependencias):
    """Transicoes 33 -> 34 (KAM-211): o botao `confirm:{action_id}` ate ao portao.

    Chama o `confirmar` pela porta `accoes_do_dono`, com o tenant e o contacto
    **do estado** — os da invocacao — e o `id` do botao. O portao faz o resto: a
    forma, o papel, o bloqueio de vinte e quatro horas depois de uma troca, o
    mesmo contacto, a validade e o *compare-and-set* que faz o duplo toque dar
    uma confirmacao. Este no **nao decide nada** sobre a accao.

    **A resposta nao distingue o que um estranho nao deve saber.** `desconhecida`,
    `outro_contacto`, `nao_e_dono` e `nao_e_botao` dizem a mesma frase: dizer
    «esse botao e de outro contacto» era um oraculo sobre as accoes de outros.

    Sem porta ligada, nada se confirma e o dono e avisado — o lado seguro.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        if estado.get("intent") == "responder_orcamento":
            # KAM-220, aresta 36: o texto do dono com o valor de um pedido. E o
            # outro lado do mesmo botao — o eco que este ramo devolve e o botao
            # que o ramo de baixo confirma.
            return await _responder_orcamento(deps, estado)
        if estado.get("intent") in ("modulos", "catalogo"):
            # KAM-119, arestas 11 e 37: a conversa do catalogo (`catalogo.py`).
            return await catalogo.tratar(deps, estado)
        porta = deps.accoes_do_dono
        if porta is None:
            return _resposta_estatica(MSG_CONFIRMACAO_INDISPONIVEL)
        botao = _botao_do_turno(estado)
        desfecho = await porta.confirmar(estado["tenant_id"], estado["contact_id"], botao)
        if desfecho in (accoes.CONFIRMADA, accoes.JA_CONFIRMADA):
            # **A accao executa aqui** (KAM-123), e tambem num `ja_confirmada`:
            # o botao gasta-se na confirmacao, e um envio que falhou a seguir
            # (Outbound em baixo, `sem_template`) tem de poder repetir-se com o
            # mesmo botao — achado da revisao adversarial. O envio e que e
            # idempotente: tranca o pedido, so anda de `respondido`, e o
            # Outbound tem a chave `orcamento:{quote_id}:{marca}`. O duplo
            # toque continua a dar **uma** proposta, e o segundo le `ja_enviado`.
            envio = await _enviar_orcamento(deps, estado, botao)
            if envio is not None:
                return _resposta_estatica(FRASE_DO_ENVIO.get(envio, MSG_CONFIRMADA))
            # KAM-119: nao e uma proposta; se for um produto, publica-se. Tambem
            # num `ja_confirmada`, pela razao do envio: uma publicacao que o
            # Registo nao recebeu repete-se com o mesmo botao, e e idempotente.
            action_id = accoes.accao_do_botao(botao)
            if action_id is not None:
                frase = await catalogo.publicar(deps, estado, botao, action_id)
                if frase is not None:
                    return _resposta_estatica(frase)
        return _resposta_estatica(FRASE_DA_CONFIRMACAO.get(desfecho, MSG_PEDIDO_NAO_ENCONTRADO))

    return no


async def _enviar_orcamento(deps: Dependencias, estado: Mapping[str, Any], botao: str) -> str | None:
    """O desfecho do envio de uma proposta, ou `None` se a accao nao for uma.

    Sem porta ligada **nada se envia** e fica a frase da confirmacao, que nao
    diz que a proposta saiu; uma accao de outro tipo devolve `None` tambem.
    """
    action_id = accoes.accao_do_botao(botao)
    porta = deps.orcamentos
    if action_id is None or porta is None:
        return None
    try:
        envio = await porta.enviar(estado["tenant_id"], estado["contact_id"], action_id)
    except Exception:  # noqa: BLE001 — o turno do dono nao rebenta por isto
        # A base ou o Outbound falharam a meio. O pedido so muda depois de o
        # Outbound responder (KAM-221: o registo e outra transaccao), e o mesmo
        # botao tenta outra vez com a mesma chave; a frase nao diz que a
        # proposta saiu, e serve a qualquer tipo de accao.
        return FALHA_DO_ENVIO
    if envio.desfecho == orcamento_repo.NAO_E_ORCAMENTO:
        return None
    return envio.desfecho


# ------------------------------------------------- os tres de texto de persona


def ask_repeat(deps: Dependencias):
    """Transicao 6 -> 22: a nota de voz que nao se percebeu."""

    async def no(_estado: dict[str, Any]) -> dict[str, Any]:
        return _resposta_estatica(MSG_REPETIR)

    return no


def safe_reply(deps: Dependencias):
    """Transicoes 9, 14 e 21 -> 23: o texto seguro, escolhido pelo veredicto.

    O fora de ambito e **deste** grafo; os outros (cartao, abuso, pausa, saida
    bloqueada) sao da plataforma e vem da funcao partilhada, como em Servicos.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        resposta = _resposta_estatica(texto_seguro_da_guarda(estado, MSG_FORA_DE_AMBITO))
        resposta["draft"]["botoes"] = botoes_seguros_da_guarda(estado)
        return resposta

    return no


def compose(deps: Dependencias):
    """Transicao 16: os blocos. **Nenhum numero em prosa** (ADR-007).

    Tres fontes, por esta ordem: os avisos do turno, o pedido sobre o catalogo
    (que hoje so tem uma resposta honesta) e o que a `get_store_info` deixou no
    rascunho. Um aviso que este grafo nao conhece **nao levanta** — ao contrario
    do `compose` de Servicos —, porque o unico no de tool que corre aqui e o
    `tools_info` do Vendedor, e um aviso novo do dominio dele nao pode rebentar
    o turno do dono: diz-se a frase generica.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        rascunho = estado.get("draft") or {}
        blocos: list[dict[str, Any]] = []
        for aviso in tuple(estado.get("avisos") or ()):
            blocos.append({"type": "text", "text": FRASE_DO_AVISO.get(aviso, MSG_NAO_CONSEGUI)})
        delta: dict[str, Any] = {}
        if estado.get("intent") == "orcamento":
            # KAM-220. As ofertas vao ao estado porque o `validate` reutilizado
            # so deixa citar um `sku` que esteja nelas.
            dos_pendentes, ofertas = await _blocos_dos_pendentes(deps, estado)
            blocos.extend(dos_pendentes)
            delta["ofertas"] = tuple(ofertas)
        blocos.extend(_blocos_dos_dados(estado))
        if not blocos:
            blocos.append({"type": "text", "text": MSG_NAO_ENTENDI})
        # Preserva o rascunho em vez de o substituir — a licao do achado 9 da
        # revisao do KAM-031, que o `compose` de Servicos tambem escreve.
        delta["draft"] = dict(rascunho, blocos=tuple(blocos))
        return delta

    return no


# ------------------------------------------------------------------ os textos
#
# **Sem digitos**, todos: os do `ask_repeat` e do `safe_reply` vao direitos ao
# `send` sem passar pelo validador, e os do `compose` sao blocos `text`, que o
# *renderer* recusa com digitos.

MSG_FORA_DE_AMBITO: Final = (
    "Por aqui trato da sua loja: o catalogo e a informacao da loja. Prefere "
    "falar com uma pessoa?"
)
MSG_REPETIR: Final = (
    "Nao consegui ouvir bem a nota de voz. Pode escrever o que precisa?"
)
MSG_NAO_ENTENDI: Final = (
    "Nao percebi o que precisa. Posso dar a informacao da loja e tratar do "
    "catalogo: para um produto novo, mande uma foto dele."
)
MSG_NAO_CONSEGUI: Final = "Nao consegui tratar esse pedido por aqui."

#: Os pendentes do Orcamento expresso (KAM-220). Sem digitos, como os outros.
MSG_PENDENTES: Final = "Tem pedidos de orcamento em aberto:"
MSG_SEM_PENDENTES: Final = "Nao tem pedidos de orcamento a espera de resposta."
MSG_PENDENTES_INDISPONIVEIS: Final = (
    "Nao consigo ver os pedidos de orcamento neste momento. Tente outra vez daqui a pouco."
)
#: O eco da resposta do dono (KAM-220, criterio 3). Antes e depois da
#: pre-visualizacao, que e o texto exacto que o cliente vai ler.
MSG_ECO: Final = "O cliente vai receber esta proposta:"
MSG_ECO_BOTAO: Final = "Se estiver certa, confirme no botao para a enviar."
MSG_VALOR_POR_REESCREVER: Final = (
    "Nao percebi o valor sem duvidas. Escreva so o valor final em kwanzas, sem "
    "contas, e a referencia do pedido."
)
MSG_QUAL_PEDIDO: Final = (
    "Nao sei a que pedido se refere. Escreva o valor com a referencia ORC do pedido."
)
MSG_PEDIDO_FECHADO: Final = "Esse pedido ja esta fechado e nao se responde."
MSG_SEM_MODULO_DE_ORCAMENTO: Final = "O Orcamento expresso nao esta activo para a sua loja."
MSG_COMO_RESPONDER: Final = (
    "Para responder, escreva o valor final e a referencia do pedido. Se quiser "
    "juntar condicoes, escreva-as no fim, a seguir a Condicoes: (por exemplo, "
    "entrega combinada consigo). O valor so segue ao cliente depois de o "
    "confirmar no botao."
)
#: KAM-230: a marca das condicoes escrita duas vezes, ou sem nada a seguir.
MSG_CONDICOES_MAL_ESCRITAS: Final = (
    "Nao percebi as condicoes. Escreva Condicoes: uma so vez, no fim, com o "
    "texto a seguir, ou envie so o valor e a referencia."
)
#: KAM-230: as condicoes recusadas — numeros, tamanho, a guarda, o `screen`, ou
#: o `screen` indisponivel (sem destino autorizado, o COM em baixo, sem prazo).
#: **Nao culpa o texto**, porque a tool nao distingue as recusas para o no
#: (achado 6 da revisao): diz o que o dono pode fazer nos dois casos. Nunca diz
#: porque, pela razao da recusa do `screen`: a regra nao sai.
MSG_CONDICOES_POR_REESCREVER: Final = (
    "Nao consegui aceitar essas condicoes. Pode enviar o orcamento sem elas, so "
    "com o valor e a referencia, ou reescreve-las sem numeros."
)

#: As frases do `confirm` (KAM-211). Sem digitos, pela razao dos outros textos.
#: **A confirmacao regista-se; a accao em si e do modulo** (KAM-119, KAM-121,
#: KAM-123), e por isso a frase nao diz que a accao foi feita.
MSG_CONFIRMADA: Final = "Confirmacao registada."
MSG_JA_CONFIRMADA: Final = "Este pedido ja estava confirmado."
MSG_EXPIRADA: Final = (
    "Este botao ja nao vale. Peca outra vez e confirme no botao novo."
)
MSG_BLOQUEADA_PELA_TROCA: Final = (
    "Por seguranca, depois de mudar o telefone as accoes sensiveis ficam "
    "bloqueadas durante um dia."
)
MSG_PEDIDO_NAO_ENCONTRADO: Final = (
    "Nao encontrei esse pedido. Peca outra vez e confirme no botao novo."
)
MSG_CONFIRMACAO_INDISPONIVEL: Final = (
    "Nao consigo confirmar pedidos neste momento. Tente outra vez daqui a pouco."
)

#: O desfecho do `confirmar` -> a frase. Os que um estranho nao deve distinguir
#: ficam de fora e caem no `MSG_PEDIDO_NAO_ENCONTRADO` — ver o `confirm`.
FRASE_DA_CONFIRMACAO: Final = {
    accoes.CONFIRMADA: MSG_CONFIRMADA,
    accoes.JA_CONFIRMADA: MSG_JA_CONFIRMADA,
    accoes.EXPIRADA: MSG_EXPIRADA,
    accoes.BLOQUEADA_PELA_TROCA: MSG_BLOQUEADA_PELA_TROCA,
}

#: As frases do envio de uma proposta de orcamento (KAM-123). Sem digitos, e
#: **sem o valor**: o dono ja o viu no eco, e repeti-lo aqui era um numero sem
#: *fact* no texto do dono.
MSG_PROPOSTA_ENVIADA: Final = "Proposta enviada ao cliente."
MSG_PROPOSTA_A_ESPERA: Final = (
    "O cliente nao fala connosco ha mais de um dia. Mandei-lhe um aviso de que o "
    "orcamento esta pronto, e o valor segue quando ele responder."
)
MSG_PROPOSTA_NAO_ENVIADA: Final = (
    "Nao consegui enviar a proposta agora. O pedido continua pendente; tente "
    "outra vez mais tarde."
)
MSG_PROPOSTA_JA_ENVIADA: Final = "Esta proposta ja tinha sido enviada."
MSG_PROPOSTA_DESACTUALIZADA: Final = (
    "Este botao era de um valor anterior. Use o botao da ultima resposta."
)
MSG_CONFIRMACAO_SEM_CONCLUSAO: Final = (
    "Confirmacao registada, mas nao consegui concluir o pedido agora. Toque outra "
    "vez no mesmo botao daqui a pouco."
)

#: O desfecho do no quando a porta levanta. Nao e da lista do `enviar`: e do no.
FALHA_DO_ENVIO: Final = "falha_do_envio"

FRASE_DO_ENVIO: Final = {
    FALHA_DO_ENVIO: MSG_CONFIRMACAO_SEM_CONCLUSAO,
    orcamento_repo.ENVIADO: MSG_PROPOSTA_ENVIADA,
    orcamento_repo.AGUARDA_JANELA: MSG_PROPOSTA_A_ESPERA,
    orcamento_repo.NAO_ENVIADO: MSG_PROPOSTA_NAO_ENVIADA,
    orcamento_repo.JA_ENVIADO: MSG_PROPOSTA_JA_ENVIADA,
    orcamento_repo.DESACTUALIZADO: MSG_PROPOSTA_DESACTUALIZADA,
}

#: Os avisos que o `tools_info` pode deixar (o `_aviso_do_erro` do Vendedor).
FRASE_DO_AVISO: Final = {
    UPSTREAM_TIMEOUT: "O sistema demorou a responder. Tente outra vez daqui a pouco.",
    UPSTREAM_DOWN: "O sistema nao responde neste momento. Tente outra vez daqui a pouco.",
    LIMIT_EXCEEDED: "Este pedido passa o limite do plano da loja.",
}


#: Os dezassete nos pelo nome. E a tabela que o `build_graph` percorre.
NOS_DO_GRAFO: Final = {
    # Reutilizados sem uma linha nova (ADR-012, §21.4).
    "ingest": ingest,
    "stt": stt,
    "guard_in": guard_in,
    "tools_info": tools_info,
    "validate": validate,
    "guard_out": guard_out,
    "send": send,
    "handoff_prepare": handoff_prepare,
    "handoff_wait": handoff_wait,
    "handoff_close": handoff_close,
    "draft_prepare": draft_prepare,
    "draft_wait": draft_wait,
    # Proprios desta persona.
    "classify": classify,
    "confirm": confirm,
    "compose": compose,
    "safe_reply": safe_reply,
    "ask_repeat": ask_repeat,
}
