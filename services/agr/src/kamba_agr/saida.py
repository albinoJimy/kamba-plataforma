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
segunda transaccao na mesma ligacao, e uma tomada guardada pedia um trinco. O
`enfileirar` e **sincrono** (a `PortaDeSaida` do grafo e sincrona desde o
KAM-031) e corre a ida a base dentro do no, como a ToolLayer.

## O inicio do turno

O `PreSendGuard` do KAM-018 recusa um envio do bot sem `turnoIniciadoEm`
(`sem_turno`). O `turno.py` poe-no num `ContextVar` (`INICIO_DO_TURNO`) antes de
ler a palavra da conversa, e as tarefas dos nos herdam-no. Fora de um turno — a
retoma do *handoff* e a decisao do concierge, que nao passam pelo executor —
vale o instante do envio, que e quando a retoma comecou a responder.
"""

from __future__ import annotations

import contextvars
import datetime
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from kamba_core import tenant_guard

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
}

#: Os botoes de confirmacao levam a referencia no `id` (`confirm:{cart_id}`,
#: `confirm:{action_id}`, §3.31), e o titulo e um so.
PREFIXO_DE_CONFIRMACAO: Final = "confirm:"
TITULO_DE_CONFIRMACAO: Final = "Confirmar"

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
}


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


def canal_por_omissao(_estado: Mapping[str, Any]) -> str:
    """O canal de uma resposta: hoje, sempre o WhatsApp.

    **O painel nao tem entrada no AGR ainda.** A fonte persistida da mensagem do
    dono e a `OwnerPort` sao do KAM-223, e e ele que passa a esta porta um
    `canal_de` que reconheca o turno do painel. Ate la, nenhum turno chega pelo
    painel, e escrever aqui uma regra para ele era decidir pelo KAM-223.
    """
    return CANAL_WHATSAPP


def emitir_resposta(
    ligacao: Any,
    estado: Mapping[str, Any],
    texto: str,
    *,
    chave: str,
    botoes: Sequence[str] = (),
    canal: str = CANAL_WHATSAPP,
    turno_iniciado_em: datetime.datetime | None = None,
) -> str | None:
    """Grava a resposta e emite o `agent.replied`. Devolve o `reply_id`, ou `None`.

    `None` e a repeticao: a chave ja tinha uma resposta deste tenant, e nao se
    emite nada. Os identificadores vem **todos** do estado do turno, que os
    tirou da invocacao (`estado_inicial`): nenhum vem do texto.
    """
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

    tenant_id = estado["tenant_id"]
    contact_id = estado["contact_id"]
    conversation_id = estado["conversation_id"]
    thread_id = estado["thread_id"]
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(
            SQL_INSERIR,
            (
                tenant_id,
                chave,
                contact_id,
                conversation_id,
                canal,
                texto,
                json.dumps(pares, ensure_ascii=False),
                turno_iniciado_em,
            ),
        )
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

    def enfileirar(
        self,
        estado: Mapping[str, Any],
        texto: str,
        *,
        chave: str,
        botoes: Sequence[str] = (),
    ) -> None:
        # shortcut: a ligacao, as duas instrucoes e o COMMIT correm na event loop,
        # porque a `PortaDeSaida` do grafo e sincrona e os nos chamam-na sem
        # `await`; com a base lenta, o processo para. Passar a porta a `async`
        # (com `asyncio.to_thread`, como a `PortaDeConfirmacao`) muda os tres
        # nos e os duplos; revê-se no KAM-227, antes de o `outbound` arrancar.
        inicio = INICIO_DO_TURNO.get() or self._relogio()
        ligacao = self._abrir()
        try:
            reply_id = emitir_resposta(
                ligacao,
                estado,
                texto,
                chave=chave,
                botoes=botoes,
                canal=self._canal_de(estado),
                turno_iniciado_em=inicio,
            )
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a resposta ja ficou ou ja falhou
                pass
        if reply_id is None and self._aviso is not None:
            # Uma repeticao nao e erro: e o turno a voltar sobre a mesma chave.
            # Conta-se para se ver quantas vezes o *shim* repete um turno que ja
            # tinha respondido.
            self._aviso("resposta_repetida")


__all__ = [
    "AGREGADO",
    "CANAIS",
    "CANAL_PAINEL",
    "CANAL_WHATSAPP",
    "FINALIDADE",
    "INICIO_DO_TURNO",
    "RespostaInvalidaError",
    "SaidaPorEvento",
    "TIPO",
    "VERSAO",
    "TITULOS",
    "canal_por_omissao",
    "emitir_resposta",
    "titulo_do_botao",
]
