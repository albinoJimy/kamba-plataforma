"""A mensagem de texto de um turno, lida pelo identificador (KAM-223).

O fundador decidiu a 2026-11-19 (decisao 1 do bloco do KAM-217, opcao A) que o
texto que o dono escreve no painel fica numa fonte persistida, e que a
invocacao do AGR leva o **identificador** dele e nunca o corpo — a decisao do
KAM-186 («o `agent_invocation` nao leva texto») mantem-se. A fonte e a
`platform.agent_messages`; o identificador e o `message_id` do contrato. A
mesma rota serve o WhatsApp: a tabela e o campo sao genericos.

    SELECT m.texto, m.canal FROM platform.agent_messages m
     WHERE m.message_id = %s AND m.tenant_id = %s
       AND m.contact_id = %s AND m.conversation_id = %s
       AND (%s <> 'dono' OR EXISTS (o contacto e o dono vivo do tenant))

## Os quatro filtros, e porque nenhum e redundante

O `message_id` e um UUID aleatorio e a tabela tem RLS por `app.tenant_id`, e
mesmo assim a instrucao confere **os tres** identificadores da invocacao. O RLS
fecha o tenant; o `contact_id` e o `conversation_id` fecham o resto: um
`message_id` de outra conversa do mesmo tenant — de outro contacto, ou do
mesmo contacto noutro canal — **nao se encontra**, e o turno desta conversa nao
le o texto daquela. Sem eles, quem tivesse um `message_id` alheio punha o texto
de outra conversa na janela desta. O `tenant_id` explicito e a segunda barreira
do RLS, pela regra do `SQL_PALAVRA_DA_CONVERSA`: a politica pode estar errada, e
a instrucao nao depende dela.

## Com a persona `dono`, o contacto tem de ser o dono

O `do_turno` confia na `persona` da invocacao (a do CHR vem resolvida contra
`contacts.papel`), e a credencial do painel (`agr_painel_token`) so corre turnos
com `persona` `dono`. Sem mais nada, quem tivesse essa credencial corria as
tools do dono para **qualquer** contacto com uma linha na tabela. Por isso,
quando a persona e `dono`, a instrucao exige que o contacto seja o dono **vivo**
do tenant (`papel = 'dono'`, nem apagado nem fundido — a regra do
`SQL_PAPEL_DO_CONTACTO`); senao a linha nao se encontra e o turno da
`invocacao_invalida`. Com `cliente` a condicao nao restringe nada: um cliente
nao ganha tools nenhumas por o ser.

## Zero linhas e recusa, nao janela vazia

Uma invocacao com `message_id` cuja linha nao se encontra **nao entra no
grafo** (`MensagemNaoEncontradaError`): e o `invocacao_invalida` da lista
fechada de desfechos (400, o *job* nao se repete). Correr o turno sem o texto
era o grafo a responder a uma mensagem que nao leu.

## Uma ligacao por leitura

Pela razao da `PortaDeConfirmacao` do KAM-211 e da `SaidaPorEvento` do KAM-224:
o `kamba_core.tenant_guard` recusa uma segunda transaccao na mesma ligacao, e
uma tomada guardada pedia um trinco. A ida a base corre fora da *event loop*
(`asyncio.to_thread`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from kamba_core import tenant_guard

from .contexto import InvocacaoDoAgente, InvocacaoInvalidaError

#: A leitura da mensagem de um turno. Parametros: `message_id`, `tenant_id`,
#: `contact_id`, `conversation_id` e `persona` — os cinco da invocacao, por esta
#: ordem. O `EXISTS` sobre `platform.contacts` so pesa com a persona `dono`.
SQL_LER_MENSAGEM: Final = """
  SELECT m.texto, m.canal
    FROM platform.agent_messages m
   WHERE m.message_id = %s
     AND m.tenant_id = %s
     AND m.contact_id = %s
     AND m.conversation_id = %s
     AND (%s <> 'dono'
          OR EXISTS (
            SELECT 1
              FROM platform.contacts c
             WHERE c.tenant_id = m.tenant_id
               AND c.contact_id = m.contact_id
               AND c.papel = 'dono'
               AND c.erased_at IS NULL
               AND c.merged_into IS NULL
          ))
"""

#: O codigo da recusa. Tem a forma de identificador da *allowlist* do *logger*
#: e nunca leva o `message_id`.
CODIGO_NAO_ENCONTRADA: Final = "mensagem_nao_encontrada"


class MensagemNaoEncontradaError(InvocacaoInvalidaError):
    """A invocacao traz um `message_id` que nao se le com o tenant, o contacto e
    a conversa dela. O turno nao entra no grafo, e a rota responde 400
    `invocacao_invalida`, como a um corpo invalido: nenhuma repeticao a muda.
    """

    def __init__(self) -> None:
        super().__init__(CODIGO_NAO_ENCONTRADA)


class LeituraDeMensagensPorLigarError(RuntimeError):
    """A invocacao traz `message_id` e o executor nao tem porta para o ler.

    E configuracao e nao contrato: levanta (500, o *job* volta a fila) em vez
    de correr o turno sem o texto ou de descartar a mensagem com um 400.
    """


@dataclass(frozen=True, slots=True)
class MensagemLida:
    """O que o `SQL_LER_MENSAGEM` devolve. O `texto` ainda **nao** e seguro."""

    texto: str
    canal: str


def ler_mensagem_sincrono(ligacao: Any, invocacao: InvocacaoDoAgente) -> MensagemLida | None:
    """A mensagem da invocacao, ou `None` se nao se encontra com os quatro
    identificadores — ou, com a persona `dono`, se o contacto nao e o dono."""
    if invocacao.message_id is None:
        return None
    with tenant_guard.tx(ligacao, invocacao.tenant_id) as cursor:
        cursor.execute(
            SQL_LER_MENSAGEM,
            (
                invocacao.message_id,
                invocacao.tenant_id,
                invocacao.contact_id,
                invocacao.conversation_id,
                invocacao.persona,
            ),
        )
        linha = cursor.fetchone()
    if linha is None:
        return None
    texto, canal = linha[0], linha[1]
    if not isinstance(texto, str) or not isinstance(canal, str):
        # A tabela tem `NOT NULL` e `CHECK` nas duas; uma linha assim e uma
        # base que nao e a da revisao, e o turno nao corre sobre ela.
        raise RuntimeError("linha da agent_messages fora da forma")
    return MensagemLida(texto=texto, canal=canal)


# ---------------------------------------------------------------------------
# A foto do dono pelo painel (KAM-243)
#
# O turno da foto nao traz `message_id`, e por isso nao passa pelo
# `SQL_LER_MENSAGEM` — que e onde o turno do painel prova que o contacto e o
# dono. Sem esta leitura, quem tivesse o `agr_painel_token` corria as tools do
# dono para **qualquer** contacto do tenant, com qualquer foto dele (achado 1 da
# revisao adversarial do KAM-243). A linha da `media_assets` tem de ser a que o
# painel guardou para **esta** invocacao: o tenant, o contacto e a conversa dela,
# `armazenado`, da classe `media_imagem` e com o `media_id` do painel — e o
# contacto tem de ser o dono vivo do tenant, pela condicao do texto.

#: A leitura da foto de um turno do painel. Parametros: `asset_id`, `tenant_id`,
#: `contact_id` e `conversation_id` da invocacao, por esta ordem.
SQL_LER_FOTO_DO_PAINEL: Final = """
  SELECT 1
    FROM platform.media_assets a
   WHERE a.asset_id = %s::uuid
     AND a.tenant_id = %s::uuid
     AND a.contact_id = %s::uuid
     AND a.conversation_id = %s::uuid
     AND a.estado = 'armazenado'
     AND a.classe = 'media_imagem'
     AND starts_with(a.media_id, 'painel.')
     AND EXISTS (
       SELECT 1
         FROM platform.contacts c
        WHERE c.tenant_id = a.tenant_id
          AND c.contact_id = a.contact_id
          AND c.papel = 'dono'
          AND c.erased_at IS NULL
          AND c.merged_into IS NULL
     )
"""

#: O codigo da recusa da foto. Forma de identificador, e nunca leva o `asset_id`.
CODIGO_FOTO_NAO_ENCONTRADA: Final = "foto_do_painel_nao_encontrada"


class FotoDoPainelNaoEncontradaError(InvocacaoInvalidaError):
    """O turno de uma foto do painel traz um `asset_id` que nao e uma foto do
    painel desta conversa, ou um contacto que nao e o dono. 400
    `invocacao_invalida`, como a mensagem que nao se encontra."""

    def __init__(self) -> None:
        super().__init__(CODIGO_FOTO_NAO_ENCONTRADA)


def ler_foto_do_painel_sincrono(ligacao: Any, invocacao: InvocacaoDoAgente) -> bool:
    """`True` se a foto do turno e a que o painel guardou para esta conversa do dono."""
    asset_id = getattr(invocacao, "asset_id", None)
    if asset_id is None:
        return False
    with tenant_guard.tx(ligacao, invocacao.tenant_id) as cursor:
        cursor.execute(
            SQL_LER_FOTO_DO_PAINEL,
            (asset_id, invocacao.tenant_id, invocacao.contact_id, invocacao.conversation_id),
        )
        return cursor.fetchone() is not None


class LeitorDeMensagens:
    """As portas `ler_mensagem` e `ler_foto_do_painel` do `ExecutorDeTurnos`: uma
    ligacao `kamba_app` por leitura (`ligacao.ligar_para_mensagens`), fechada no
    fim."""

    __slots__ = ("_abrir",)

    def __init__(self, abrir_ligacao: Callable[[], Any]) -> None:
        self._abrir = abrir_ligacao

    def _numa_ligacao(self, leitura: Callable[[Any, InvocacaoDoAgente], Any], invocacao: InvocacaoDoAgente) -> Any:
        ligacao = self._abrir()
        try:
            return leitura(ligacao, invocacao)
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a leitura ja ficou ou ja falhou
                pass

    def _ler(self, invocacao: InvocacaoDoAgente) -> MensagemLida | None:
        return self._numa_ligacao(ler_mensagem_sincrono, invocacao)

    async def ler(self, invocacao: InvocacaoDoAgente) -> MensagemLida | None:
        return await asyncio.to_thread(self._ler, invocacao)

    async def foto_do_painel(self, invocacao: InvocacaoDoAgente) -> bool:
        """KAM-243. A foto do turno e a que o painel guardou para o dono?"""
        return await asyncio.to_thread(self._numa_ligacao, ler_foto_do_painel_sincrono, invocacao)


__all__ = [
    "CODIGO_FOTO_NAO_ENCONTRADA",
    "CODIGO_NAO_ENCONTRADA",
    "FotoDoPainelNaoEncontradaError",
    "LeitorDeMensagens",
    "LeituraDeMensagensPorLigarError",
    "MensagemLida",
    "MensagemNaoEncontradaError",
    "SQL_LER_FOTO_DO_PAINEL",
    "SQL_LER_MENSAGEM",
    "ler_foto_do_painel_sincrono",
    "ler_mensagem_sincrono",
]
