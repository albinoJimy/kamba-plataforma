"""A saida do AGR: o evento de resposta do turno (KAM-224).

Ate aqui a `PortaDeSaida` do grafo era a `SaidaPorLigar` (KAM-186): levantava,
a rota dava 503 `saida_por_ligar`, e nenhuma resposta saia. O fundador decidiu a
2026-11-19 (decisao 2 do bloco do KAM-217, opcao A) que a resposta sai como um
evento pela `platform.evt_emitir`, pelo barramento do KAM-006. Esta e essa porta.

## O que o `enfileirar` faz, numa transaccao so

    BEGIN; SET LOCAL app.tenant_id                    (tenant_guard.tx)
      INSERT agent_replies ... ON CONFLICT (tenant_id, chave) DO NOTHING
        RETURNING reply_id
      se nasceu: SELECT platform.evt_emitir('agent.replied', ..., payload)
    COMMIT

**O texto fica na `platform.agent_replies`, e o evento leva o `reply_id`.** O
lint de PII do *gate* 7 recusa um campo `texto` num *payload* (a regra do
`docs/tecnica/06` §7.1, «sem PII crua em eventos»), e uma resposta a um cliente
pode levar o nome dele. E a forma da decisao 1 do mesmo dia: uma fonte
persistida que se le por identificador. Os consumidores (o `outbound` do
`worker-canal` e o `painel` do `onboarding-web`) leem a linha pelo `reply_id`.

**Um turno repetido nao emite duas vezes.** A chave e a que o grafo ja calcula
para o envio (`turn_id:seq`, `{draft_id}:send`, `{handoff_id}:msg`), e e a
mesma na segunda volta (`turno.py`, «A repeticao e a chave»). O `UNIQUE
(tenant_id, chave)` faz o segundo `INSERT` nao inserir, e sem linha nova nao ha
evento: linha e evento nascem juntos ou nao nascem.

## «Na transaccao do turno», e o que isso pode querer dizer aqui

O turno do AGR nao e uma transaccao de base: o estado vai ao *checkpoint* pelo
papel `kamba_agr`, noutra ligacao, e um papel nao ve o esquema do outro
(KAM-026). O que fica atomico e o que a decisao pede que seja: **a resposta e o
evento**, na transaccao que o `send` do turno abre. Se o processo morrer depois
do `COMMIT` e antes de o *checkpoint* gravar o `send`, o turno repete-se, a
chave e a mesma, e o `INSERT` nao insere: a resposta sai uma vez.

## Uma ligacao por envio

Pela razao da `PortaDeConfirmacao` do KAM-211: o `tenant_guard` recusa uma
segunda transaccao na mesma ligacao, e uma tomada guardada pedia um trinco.

**A ida a base corre fora da *event loop*** (KAM-227). A `PortaDeSaida` do grafo
e `async`, os tres nos que enviam (`send`, `handoff_prepare`, `handoff_close`)
fazem `await`, e o `enfileirar` passa a ligacao, as duas instrucoes e o `COMMIT`
a uma *thread* com o `asyncio.to_thread` — a travessia do `conversa.py` e do
`checkpointer.py`. Uma base lenta atrasa o turno que envia e nao os outros. O
`emitir_resposta` continua sincrono: e o corpo que corre na *thread*.

Um cancelamento a meio nao corta a *thread* (o `to_thread` nao cancela), mas
nao ha nada partilhado a proteger: a ligacao e so deste envio, e a *thread*
fecha-a. Se o `COMMIT` chegou, o turno repete-se com a mesma chave e o `INSERT`
nao insere.

## O inicio do turno

O `PreSendGuard` do KAM-018 recusa um envio do bot sem `turnoIniciadoEm`
(`sem_turno`). O `turno.py` poe-no num `ContextVar` (`INICIO_DO_TURNO`) antes de
ler a palavra da conversa, e as tarefas dos nos herdam-no. Fora de um turno — a
retoma do *handoff* e a decisao do concierge, que nao passam pelo executor —
vale o instante do envio, que e quando a retoma comecou a responder.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.storage import ChaveForaDoTenantError, ChaveInvalidaError, Ctx
from kamba_core.storage.chave import chave_do_ctx

#: O tipo do evento. Dicionario §3.5 e §3.80 (emenda 1.118).
TIPO: Final = "agent.replied"

#: A versao que o AGR emite. A `v2` existe pela regra do KAM-159 (a ultima
#: versao cobre o dominio inteiro de finalidades), e o *payload* e o mesmo.
VERSAO: Final = 1

#: O agregado: a conversa, para que as respostas de uma conversa caiam na mesma
#: particao do barramento e saiam pela ordem em que se emitiram.
AGREGADO: Final = "conversation"

#: A finalidade do evento: responder a quem escreveu e atendimento.
FINALIDADE: Final = "atendimento"

#: Os dois canais. Iguais ao `CANAIS` da revisao `*_resposta_do_agr.py` e ao
#: `CANAIS_DA_RESPOSTA` de `packages/core-ts/src/resposta/contrato.ts`.
CANAIS: Final = ("whatsapp", "painel")
CANAL_WHATSAPP, CANAL_PAINEL = CANAIS

#: O tecto de botoes da Meta (CONFIRMADO, `E1` §5), o `MAX_BOTOES` do renderer.
MAXIMO_DE_BOTOES: Final = 3

#: O tecto de um texto da Cloud API, e o `CHECK` da coluna.
MAXIMO_DO_TEXTO: Final = 4096

#: O tecto da chave, e o `CHECK` da coluna.
MAXIMO_DA_CHAVE: Final = 300

#: O tecto do titulo de um *reply button* da Cloud API (CONFIRMADO, `E1` §5).
MAXIMO_DO_TITULO: Final = 20

#: O titulo de cada botao que os grafos emitem, em `pt` de Angola.
#:
#: **O `Corpo` do Outbound exige `{id, titulo}`, e o grafo so da o `id`**: o
#: `PortaDeSaida.enfileirar` recebe identificadores, e o titulo e texto que chega
#: ao cliente. O credor que o `degradado/textos.py` escreveu (KAM-015) e esta
#: tabela: a porta resolve o titulo antes de gravar, e o consumidor envia o par.
#: Os tres `menu:*` sao o `ROTULO_DA_OPCAO` do modo degradado, e um ensaio
#: confronta-os (`test_os_rotulos_do_menu_sao_os_do_modo_degradado`). Nenhum
#: leva digitos, pela regra dos textos.
TITULOS: Final = {
    "cancelar": "Cancelar",
    "falar_com_humano": "Falar com um colega",
    "menu:pedido": "O meu pedido",
    "menu:loja": "Horario e morada",
    "menu:humano": "Falar com um colega",
    # O modulo social do dono (KAM-121, `social/regras.py`): os tres tons do
    # perfil e as duas accoes do calendario. Os titulos dos tons sao os
    # `TITULO_DO_TOM`, e um ensaio confronta-os.
    "tom:proximo": "Proximo e caloroso",
    "tom:profissional": "Profissional",
    "tom:divertido": "Divertido",
    "social:ideias": "Ver as ideias",
    "social:nova": "Outras ideias",
}

#: Os botoes de confirmacao levam a referencia no `id` (`confirm:{cart_id}`,
#: `confirm:{action_id}`, §3.31), e o titulo e um so.
PREFIXO_DE_CONFIRMACAO: Final = "confirm:"
TITULO_DE_CONFIRMACAO: Final = "Confirmar"

#: O botao «Aceito» da proposta do Orcamento expresso leva a referencia da
#: proposta no `id` (`aceitar_orcamento:ORC-…`; decisao do fundador de
#: 2026-11-20, opcao B do KAM-226), e o titulo e um so, como o da confirmacao.
PREFIXO_DO_ACEITO: Final = "aceitar_orcamento:"
TITULO_DO_ACEITO: Final = "Aceito"

#: Os botoes do catalogo do dono (KAM-119) levam a ingestao no `id` (e o valor,
#: no do preco), pela razao do `confirm:`; o titulo e um por prefixo. Os
#: prefixos sao os de `catalogo/regras.py`, e um ensaio confronta-os.
TITULOS_POR_PREFIXO: Final = {
    "preco:": "Sim, esta certo",
    "preco_corrigir:": "Corrigir",
    "stock:": "Sim, esta certo",
    "stock_corrigir:": "Corrigir",
    "mesmo_produto:": "Sim, e o mesmo",
    "outro_produto:": "Nao, e outro",
    # KAM-244: uma ingestao que o screening nao chegou a decidir.
    "retomar:": "Tentar outra vez",
    # KAM-121: a legenda de um item do calendario, pela referencia `SOC-…`. O
    # titulo leva a referencia (`titulo_do_botao`); este e o de reserva.
    "legenda:": "Escrever a legenda",
}

#: O prefixo do botao de legenda do social (o `PREFIXO_DA_LEGENDA` de
#: `social/regras.py`, que um ensaio confronta).
PREFIXO_DA_LEGENDA: Final = "legenda:"


def titulo_do_botao(identificador: str) -> str:
    """O titulo de um botao. Um `id` que a tabela nao tem **levanta**.

    Enviar o `id` cru no ecra do cliente era o defeito que o `textos.py` deixou
    com credor, e escolher um titulo generico escondia um botao novo sem rotulo.
    Levantando, o turno nao acaba e repete-se ate falhar: **um botao novo sem
    titulo deixa a conversa sem resposta**. Os ensaios dos grafos usam um duplo
    de saida que nao resolve titulos, pelo que quem o apanha e a lista do
    `test_os_botoes_que_os_grafos_emitem_tem_titulo`: um botao novo entra la e
    aqui no mesmo PR.
    """
    if identificador.startswith(PREFIXO_DE_CONFIRMACAO) and len(identificador) > len(
        PREFIXO_DE_CONFIRMACAO
    ):
        return TITULO_DE_CONFIRMACAO
    if identificador.startswith(PREFIXO_DO_ACEITO) and len(identificador) > len(PREFIXO_DO_ACEITO):
        return TITULO_DO_ACEITO
    if identificador.startswith(PREFIXO_DA_LEGENDA):
        # KAM-121: os botoes de legenda saem dois a dois, e com o mesmo titulo o
        # dono nao sabia qual era a de cada ideia (achado M4 da revisao). A
        # referencia `SOC-` e oito letras: «Legenda SOC-ABCDEFGH» tem vinte.
        referencia = identificador[len(PREFIXO_DA_LEGENDA) :]
        titulo = f"Legenda {referencia}"
        if referencia and len(titulo) <= MAXIMO_DO_TITULO:
            return titulo
    for prefixo, titulo_do_prefixo in TITULOS_POR_PREFIXO.items():
        if identificador.startswith(prefixo) and len(identificador) > len(prefixo):
            return titulo_do_prefixo
    titulo = TITULOS.get(identificador)
    if titulo is None:
        raise RespostaInvalidaError(f"botao sem titulo: {identificador[:40]!r}")
    return titulo

SQL_INSERIR: Final = (
    "INSERT INTO platform.agent_replies "
    "(tenant_id, chave, contact_id, conversation_id, canal, texto, botoes, turno_iniciado_em) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s) "
    "ON CONFLICT (tenant_id, chave) DO NOTHING RETURNING reply_id"
)

#: A mesma linha **com** o *template* (KAM-221, revisao `0076`). Instrucao a
#: parte, e nao duas colunas a mais no `SQL_INSERIR`: a resposta de texto livre
#: de um turno continua a escrever exactamente o que escrevia, e as colunas do
#: *template* so aparecem quando quem notifica as escolheu.
SQL_INSERIR_COM_TEMPLATE: Final = (
    "INSERT INTO platform.agent_replies "
    "(tenant_id, chave, contact_id, conversation_id, canal, texto, botoes, turno_iniciado_em, "
    "template_nome, template_parametros) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::text[]) "
    "ON CONFLICT (tenant_id, chave) DO NOTHING "
    "RETURNING reply_id"
)

#: A mesma linha **com** a imagem (KAM-246): a chave do STO da arte, que o
#: consumidor do WhatsApp envia **antes** do texto. Instrucao a parte, pela razao
#: do *template*: a resposta de texto livre escreve exactamente o que escrevia.
#: Sem *template*: a base recusa os dois juntos (o `CHECK` da revisao do KAM-246).
SQL_INSERIR_COM_MEDIA: Final = (
    "INSERT INTO platform.agent_replies "
    "(tenant_id, chave, contact_id, conversation_id, canal, texto, botoes, turno_iniciado_em, media_ref) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) "
    "ON CONFLICT (tenant_id, chave) DO NOTHING "
    "RETURNING reply_id"
)

#: A classe do STO de uma imagem de resposta: so a arte do modulo social
#: (KAM-122, dicionario §3.82). A foto do dono, um documento de KYC ou o pacote
#: de um off-boarding nao saem por aqui.
CLASSE_DA_MEDIA: Final = "arte"


def media_da_resposta(media: str | None, tenant_id: Any) -> str | None:
    """A chave da imagem, conferida: do tenant da resposta e da classe `arte`.

    Levanta `RespostaInvalidaError` antes da base, que repete a regra no `CHECK`
    da coluna. **E uma chave, nunca um URL**: um URL nao tem a forma.
    """
    if media is None:
        return None
    try:
        # O tenant do estado pode vir em maiusculas ou como `UUID`; a chave e em minusculas.
        partes = chave_do_ctx(Ctx(tenant_guard.normalizar_tenant(tenant_id)), media, "media")
    except (ChaveInvalidaError, ChaveForaDoTenantError, ValueError):
        raise RespostaInvalidaError("a imagem nao e uma chave do STO deste tenant") from None
    if partes.classe != CLASSE_DA_MEDIA:
        raise RespostaInvalidaError("a imagem de uma resposta e so da classe arte")
    return media


#: A forma de um nome de *template* da Meta: minusculas, algarismos e `_`. A
#: mesma do `agent_replies_template_nome_ck` da `0076`.
FORMA_DO_TEMPLATE: Final = re.compile(r"[a-z0-9_]{1,512}")

#: Quantos parametros um *template* desta casa leva, no maximo (*proposta*).
MAXIMO_DE_PARAMETROS: Final = 10

#: O tamanho de um parametro (*proposta*). A Meta recusa um parametro vazio, e
#: recusa uma quebra de linha ou um tab dentro dele.
MAXIMO_DO_PARAMETRO: Final = 1024

#: O `evt_emitir` da `0004`, com classe `P0` e finalidade `atendimento`: o
#: *payload* leva identificadores, nunca o texto nem o telefone.
SQL_EMITIR: Final = (
    "SELECT platform.evt_emitir(%s, 1::smallint, %s::uuid, 'conversation', %s, %s::jsonb, "
    "'P0', '{atendimento}'::text[])"
)

class RespostaInvalidaError(ValueError):
    """A resposta nao tem a forma que a tabela aceita. Levanta antes da base."""


#: O instante em que o turno em curso comecou, em UTC. `None` fora de um turno.
INICIO_DO_TURNO: contextvars.ContextVar[datetime.datetime | None] = contextvars.ContextVar(
    "kamba_agr_inicio_do_turno", default=None
)


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


#: O canal da mensagem que o turno em curso leu (KAM-223), ou `None`.
#:
#: Posto pelo `ExecutorDeTurnos` com o `canal` da **ultima** mensagem que leu
#: da `platform.agent_messages` no lote, e reposto no fim do turno, como o
#: `INICIO_DO_TURNO`. Os nos herdam-no, e o `canal_do_turno` le-o. Um turno sem
#: mensagem lida (uma mensagem do WhatsApp que nao e `text`, que nao traz
#: `message_id`) deixa-o a `None`, e a resposta sai pelo WhatsApp.
CANAL_DO_TURNO: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kamba_agr_canal_do_turno", default=None
)


def canal_por_omissao(_estado: Mapping[str, Any]) -> str:
    """O canal de uma resposta quando ninguem sabe outro: o WhatsApp.

    Ja nao e o `canal_de` do processo: desde o KAM-223 o `main()` passa o
    `canal_do_turno`, que reconhece o turno do painel. Fica como omissao da
    `SaidaPorEvento` para quem a monta sem executor (os ensaios dos grafos), e
    e o que o `canal_do_turno` devolve fora de um turno.
    """
    return CANAL_WHATSAPP


def canal_do_turno(estado: Mapping[str, Any]) -> str:
    """O canal da resposta deste turno: o da mensagem que o turno leu (KAM-223).

    Le o `CANAL_DO_TURNO`, que o executor pos. **Fora de um turno, ou num turno
    sem mensagem lida, e o WhatsApp** — a retoma do *handoff* e a decisao do
    concierge nao passam pelo executor, e sao respostas a um cliente. Um valor
    fora dos `CANAIS` tambem cai no WhatsApp: nao pode, porque a coluna da
    `agent_messages` tem o mesmo `CHECK`, e se acontecer a `emitir_resposta`
    nao recebe um canal que a tabela recusava.
    """
    canal = CANAL_DO_TURNO.get()
    if canal in CANAIS:
        return canal
    return canal_por_omissao(estado)


def _parametros_do_template(
    template: str | None, parametros: Sequence[str], botoes: Sequence[str]
) -> list[str]:
    """Os parametros validados, em lista; levanta antes da base."""
    parametros = list(parametros)
    if template is None:
        if parametros:
            raise RespostaInvalidaError("parametros sem template")
        return parametros
    if not isinstance(template, str) or FORMA_DO_TEMPLATE.fullmatch(template) is None:
        raise RespostaInvalidaError("o nome do template nao tem a forma da Meta")
    if botoes:
        raise RespostaInvalidaError("um template nao leva botoes")
    if len(parametros) > MAXIMO_DE_PARAMETROS:
        raise RespostaInvalidaError("demasiados parametros no template")
    for valor in parametros:
        if (
            not isinstance(valor, str)
            or not 1 <= len(valor) <= MAXIMO_DO_PARAMETRO
            or "\n" in valor
            or "\t" in valor
        ):
            raise RespostaInvalidaError("um parametro do template sem a forma da Meta")
    return parametros


def _forma(
    texto: str,
    *,
    chave: str,
    botoes: Sequence[str],
    canal: str,
    template: str | None,
    parametros: Sequence[str],
) -> tuple[list[dict[str, str]], list[str]]:
    """Os pares `{id, titulo}` e os parametros validados; levanta antes da base."""
    if canal not in CANAIS:
        raise RespostaInvalidaError(f"canal fora de {CANAIS}: {canal!r}")
    if not isinstance(texto, str) or not 1 <= len(texto) <= MAXIMO_DO_TEXTO:
        raise RespostaInvalidaError("o texto tem de ter entre 1 e 4096 caracteres")
    if not isinstance(chave, str) or not 1 <= len(chave) <= MAXIMO_DA_CHAVE:
        raise RespostaInvalidaError("a chave tem de ter entre 1 e 300 caracteres")
    botoes = tuple(botoes)
    if len(botoes) > MAXIMO_DE_BOTOES or not all(isinstance(b, str) and b for b in botoes):
        raise RespostaInvalidaError("no maximo tres botoes, cada um um identificador")
    pares = [{"id": b, "titulo": titulo_do_botao(b)} for b in botoes]
    return pares, _parametros_do_template(template, parametros, botoes)


def emitir_resposta(
    ligacao: Any,
    estado: Mapping[str, Any],
    texto: str,
    *,
    chave: str,
    botoes: Sequence[str] = (),
    canal: str = CANAL_WHATSAPP,
    turno_iniciado_em: datetime.datetime | None = None,
    template: str | None = None,
    parametros: Sequence[str] = (),
    media: str | None = None,
) -> str | None:
    """Grava a resposta e emite o `agent.replied`. Devolve o `reply_id`, ou `None`.

    `None` e a repeticao: a chave ja tinha uma resposta deste tenant, e nao se
    emite nada. Os identificadores vem **todos** do estado do turno, que os
    tirou da invocacao (`estado_inicial`): nenhum vem do texto.

    Com `template` (KAM-221), a resposta sai como esse *template*, com os
    `parametros` pela ordem: **valores** ja resolvidos, que o consumidor poe no
    corpo sem os ler. O `texto` continua obrigatorio: e o que a notificacao
    diria com a janela aberta, e o consumidor do WhatsApp nao o envia com o
    *template*. Um *template* nao leva botoes.

    Com `media` (KAM-246), a chave do STO da arte: o consumidor do WhatsApp
    envia-a como imagem antes do texto. Nunca com *template*.
    """
    # A forma valida-se antes de abrir a transaccao, e outra vez no
    # `gravar_resposta`: o custo e nada, e a base nao ve uma resposta sem forma.
    # **Materializa-se uma vez**: um gerador passado aos dois chegava vazio ao
    # segundo, e a linha gravava-se sem botoes nem parametros (achado 3 da
    # revisao do KAM-226).
    botoes, parametros = tuple(botoes), tuple(parametros)
    _forma(texto, chave=chave, botoes=botoes, canal=canal, template=template, parametros=parametros)
    _media_sem_template(media, template, estado["tenant_id"])
    with tenant_guard.tx(ligacao, estado["tenant_id"]) as cursor:
        return gravar_resposta(
            cursor,
            estado,
            texto,
            chave=chave,
            botoes=botoes,
            canal=canal,
            turno_iniciado_em=turno_iniciado_em,
            template=template,
            parametros=parametros,
            media=media,
        )


def _media_sem_template(media: str | None, template: str | None, tenant_id: Any) -> str | None:
    if media is not None and template is not None:
        raise RespostaInvalidaError("uma imagem nao sai com template")
    return media_da_resposta(media, tenant_id)


def gravar_resposta(
    cursor: Any,
    estado: Mapping[str, Any],
    texto: str,
    *,
    chave: str,
    botoes: Sequence[str] = (),
    canal: str = CANAL_WHATSAPP,
    turno_iniciado_em: datetime.datetime | None = None,
    template: str | None = None,
    parametros: Sequence[str] = (),
    media: str | None = None,
) -> str | None:
    """O `emitir_resposta` sobre um cursor **ja** dentro do `tenant_guard.tx`.

    Para quem escreve a resposta na transaccao de outra coisa (KAM-226): o
    aviso ao dono nasce na transaccao do `quote.requested`, e o `tenant_guard`
    recusa uma segunda transaccao na mesma ligacao. A forma valida-se antes do
    `INSERT`, e quem chama leva o `ROLLBACK` se ela levantar.
    """
    pares, parametros = _forma(
        texto, chave=chave, botoes=botoes, canal=canal, template=template, parametros=parametros
    )
    tenant_id = estado["tenant_id"]
    media = _media_sem_template(media, template, tenant_id)
    contact_id = estado["contact_id"]
    conversation_id = estado["conversation_id"]
    thread_id = estado["thread_id"]
    linha_nova = (
        tenant_id,
        chave,
        contact_id,
        conversation_id,
        canal,
        texto,
        json.dumps(pares, ensure_ascii=False),
        turno_iniciado_em,
    )
    if media is not None:
        cursor.execute(SQL_INSERIR_COM_MEDIA, (*linha_nova, media))
    elif template is None:
        cursor.execute(SQL_INSERIR, linha_nova)
    else:
        cursor.execute(SQL_INSERIR_COM_TEMPLATE, (*linha_nova, template, parametros))
    linha = cursor.fetchone()
    if linha is None:
        return None
    reply_id = str(linha[0])
    payload = {
        "reply_id": reply_id,
        "thread_id": thread_id,
        "conversation_id": str(conversation_id),
        "contact_id": str(contact_id),
        "canal": canal,
    }
    cursor.execute(
        SQL_EMITIR,
        (TIPO, tenant_id, str(conversation_id), json.dumps(payload, sort_keys=True)),
    )
    cursor.fetchone()
    return reply_id


class SaidaPorEvento:
    """A `PortaDeSaida` do grafo, ligada: grava a resposta e emite o evento.

    Substitui a `SaidaPorLigar` no `main()`. Quem a monta passa a fabrica de
    ligacoes do `kamba_app` (`ligacao.ligar_para_saida`).
    """

    __slots__ = ("_abrir", "_canal_de", "_relogio", "_aviso")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        *,
        canal_de: Callable[[Mapping[str, Any]], str] = canal_por_omissao,
        relogio: Callable[[], datetime.datetime] = _agora,
        aviso: Callable[[str], None] | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._canal_de = canal_de
        self._relogio = relogio
        self._aviso = aviso

    async def enfileirar(
        self,
        estado: Mapping[str, Any],
        texto: str,
        *,
        chave: str,
        botoes: Sequence[str] = (),
        media: str | None = None,
    ) -> None:
        # O inicio e o canal leem-se aqui, na tarefa do no: o `to_thread` copia
        # o contexto, mas o `INICIO_DO_TURNO` fica lido onde o turno o pos, e a
        # *thread* recebe valores e nao um `ContextVar`.
        inicio = INICIO_DO_TURNO.get() or self._relogio()
        canal = self._canal_de(estado)
        reply_id = await asyncio.to_thread(
            self._gravar, estado, texto, chave, tuple(botoes), canal, inicio, media
        )
        if reply_id is None and self._aviso is not None:
            # Uma repeticao nao e erro: e o turno a voltar sobre a mesma chave.
            # Conta-se para se ver quantas vezes o *shim* repete um turno que ja
            # tinha respondido.
            self._aviso("resposta_repetida")

    def _gravar(
        self,
        estado: Mapping[str, Any],
        texto: str,
        chave: str,
        botoes: Sequence[str],
        canal: str,
        inicio: datetime.datetime,
        media: str | None = None,
    ) -> str | None:
        """O corpo sincrono do envio, na *thread*: abre, grava e emite, fecha."""
        ligacao = self._abrir()
        try:
            return emitir_resposta(
                ligacao,
                estado,
                texto,
                chave=chave,
                botoes=botoes,
                canal=canal,
                turno_iniciado_em=inicio,
                media=media,
            )
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a resposta ja ficou ou ja falhou
                pass


__all__ = [
    "AGREGADO",
    "CANAIS",
    "CANAL_PAINEL",
    "CANAL_DO_TURNO",
    "CANAL_WHATSAPP",
    "CLASSE_DA_MEDIA",
    "FINALIDADE",
    "FORMA_DO_TEMPLATE",
    "INICIO_DO_TURNO",
    "MAXIMO_DE_PARAMETROS",
    "MAXIMO_DO_PARAMETRO",
    "RespostaInvalidaError",
    "SaidaPorEvento",
    "TIPO",
    "VERSAO",
    "PREFIXO_DO_ACEITO",
    "TITULOS",
    "canal_do_turno",
    "canal_por_omissao",
    "emitir_resposta",
    "gravar_resposta",
    "media_da_resposta",
    "titulo_do_botao",
]
