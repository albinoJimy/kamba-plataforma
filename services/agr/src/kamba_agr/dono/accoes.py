"""As accoes sensiveis do dono: propor, e confirmar so por botao (KAM-118).

O criterio 5 do bloco: alterar preco/stock em massa, aprovar conteudo para
terceiros e enviar proposta a cliente **so executam** com o botao
`confirm:{action_id}` do mesmo `contact_id`; duplo toque x2 -> **1**; um botao
com mais de quinze minutos expira; «sim»/«ok» por texto **nao** confirmam
(0/20). E o criterio 4: depois de uma troca de telefone do dono, as accoes
sensiveis ficam bloqueadas vinte e quatro horas.

    propor(ligacao, tenant, contacto, tipo, ref, agora)     -> action_id
    confirmar(ligacao, tenant, contacto, botao, agora)      -> desfecho

## A idempotencia e da base, e nao deste codigo

* **Propor duas vezes a mesma coisa da a mesma accao.** O `INSERT ... ON
  CONFLICT ON CONSTRAINT owner_actions_uq DO NOTHING` e a `UNIQUE (tenant_id,
  tipo, ref)` da revisao `0070`; sem linha devolvida, le-se a que la esta. Duas
  reentregas do mesmo *job* nao pedem dois botoes.
* **Confirmar duas vezes confirma uma.** O `UPDATE ... WHERE estado =
  'pendente' AND expira_at > %s AND contact_id = %s RETURNING` e um
  *compare-and-set*: o segundo toque nao encontra a linha `pendente` e cai no
  diagnostico, que diz `ja_confirmada`. Dois toques concorrentes serializam-se
  na tranca de linha do PostgreSQL, e so um recebe a linha de volta.

## So um botao conta, e o texto nunca

O `confirmar` recebe o **identificador do botao** e nao o texto da mensagem, e
o primeiro passo e a forma: `confirm:` seguido de um UUID canonico. Um «sim»,
um «ok», um «confirmo», ou um `confirm:` com outra coisa atras sao
`nao_e_botao` **antes** de a base ser tocada — e o 0/20 do criterio, por
construcao e nao por uma lista de palavras. O prefixo e o do
`tls/contexto.py`, o mesmo do carrinho e da marcacao: um segundo literal era
uma segunda fonte para o mesmo contrato.

**Hoje nenhum `id` de botao chega ao AGR** (o `estado_inicial` nasce com
`messages: []`, decisao do KAM-186). O portao entrega-se e ensaia-se; ligar o
botao ao turno e do KAM-211.

## O `tenant_id` vem do contexto, e vai nas duas barreiras

Cada instrucao corre dentro de `tenant_guard.tx` (a RLS `FORCE` da `0070`) **e**
leva o `tenant_id` no predicado, pela disciplina do `consultas.py`: com a
politica desligada por engano, o predicado continua a separar tenants.

## O que nao se escreve em registo nenhum

Nada deste modulo escreve *logs*: o desfecho volta a quem chamou, que e quem
sabe se o conta. O `ref` e opaco mas e do dono (o identificador de um rascunho,
de uma proposta), e o telefone nem sequer passa por aqui — o contacto e um
`contact_id`.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Final

from kamba_core import tenant_guard

from ..tls.contexto import PREFIXO_DE_CONFIRMACAO

#: Quanto tempo um botao de confirmacao vale. *Proposta* — o criterio 5 do
#: KAM-118 escreve «mais de 15 min (*proposta*)», e o bloco manda os limiares
#: ser configuraveis.
VALIDADE_DO_BOTAO: Final = datetime.timedelta(minutes=15)

#: Quanto tempo as accoes sensiveis ficam bloqueadas depois de uma troca de
#: telefone do dono (`contacts.papel_mudou_at`). *Proposta* — criterio 4 do
#: KAM-118. Uma troca de SIM e INDICIO de risco (`docs/tecnica/08` §18), e o
#: bloqueio e o que separa «o atacante tem o numero» de «o atacante publica».
BLOQUEIO_DEPOIS_DA_TROCA: Final = datetime.timedelta(hours=24)

#: Os tres tipos do `CHECK` de `owner_actions.tipo` (revisao `0070`).
TIPOS: Final = ("preco_stock_em_massa", "aprovar_conteudo", "enviar_proposta")

#: O papel que confirma. O `CHECK` de `contacts.papel`.
PAPEL_DONO: Final = "dono"

#: Os desfechos do `confirmar`. Lista **fechada**: quem a conta usa-a como
#: etiqueta, e cada um diz uma coisa diferente ao dono.
CONFIRMADA: Final = "confirmada"
JA_CONFIRMADA: Final = "ja_confirmada"
EXPIRADA: Final = "expirada"
OUTRO_CONTACTO: Final = "outro_contacto"
NAO_E_BOTAO: Final = "nao_e_botao"
BLOQUEADA_PELA_TROCA: Final = "bloqueada_pela_troca"
NAO_E_DONO: Final = "nao_e_dono"
DESCONHECIDA: Final = "desconhecida"
DESFECHOS: Final = (
    CONFIRMADA,
    JA_CONFIRMADA,
    EXPIRADA,
    OUTRO_CONTACTO,
    NAO_E_BOTAO,
    BLOQUEADA_PELA_TROCA,
    NAO_E_DONO,
    DESCONHECIDA,
)

_UUID: Final = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

# ------------------------------------------------------------------- o SQL
#
# Em constantes de modulo, pela razao do `consultas.py`: a suite de BD
# (`db/tests_agr/test_owner_actions.py`) importa-as e corre **estas**, e nao uma
# copia delas.

#: O papel de quem escreve. So um contacto vivo (nem apagado nem fundido) conta.
SQL_PAPEL_DO_CONTACTO: Final = (
    "SELECT papel, papel_mudou_at FROM platform.contacts "
    "WHERE tenant_id = %s AND contact_id = %s "
    "AND erased_at IS NULL AND merged_into IS NULL"
)

SQL_PROPOR: Final = (
    "INSERT INTO platform.owner_actions (tenant_id, contact_id, tipo, ref, expira_at) "
    "VALUES (%s, %s, %s, %s, %s) "
    "ON CONFLICT ON CONSTRAINT owner_actions_uq DO NOTHING "
    "RETURNING action_id"
)

SQL_ACCAO_DA_REF: Final = (
    "SELECT action_id FROM platform.owner_actions "
    "WHERE tenant_id = %s AND tipo = %s AND ref = %s"
)

#: O *compare-and-set*. Os quatro predicados sao o criterio: pendente, dentro
#: do prazo, do mesmo contacto, deste tenant.
SQL_CONFIRMAR: Final = (
    "UPDATE platform.owner_actions SET estado = 'confirmada', confirmada_at = %s "
    "WHERE tenant_id = %s AND action_id = %s AND contact_id = %s "
    "AND estado = 'pendente' AND expira_at > %s "
    "RETURNING action_id"
)

SQL_DIAGNOSTICO: Final = (
    "SELECT estado, contact_id, expira_at FROM platform.owner_actions "
    "WHERE tenant_id = %s AND action_id = %s"
)

#: Uma `pendente` cujo prazo passou fecha-se `expirada` quando alguem a tenta
#: confirmar: o estado passa a dizer o que ela e. Nao ha varrimento — uma accao
#: que ninguem toca nao precisa de ser fechada para nao valer, porque o
#: `SQL_CONFIRMAR` ja exige o prazo.
SQL_EXPIRAR: Final = (
    "UPDATE platform.owner_actions SET estado = 'expirada' "
    "WHERE tenant_id = %s AND action_id = %s AND estado = 'pendente' AND expira_at <= %s"
)


class AccaoRecusadaError(ValueError):
    """O `propor` nao cria a accao. O `codigo` e um dos `DESFECHOS`, sem valores."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


def accao_do_botao(botao: object) -> str | None:
    """O `action_id` de um botao `confirm:{uuid}`, ou `None` se nao for um.

    **Por forma, e nao por lista de palavras**: o que passa e exactamente o
    prefixo seguido de um UUID canonico em minusculas. E por isso que nenhum
    texto confirma — um texto nao tem esta forma, e quem a escrever a mao
    escreve um `action_id` que tem de ser deste contacto, pendente e dentro do
    prazo.
    """
    if not isinstance(botao, str) or not botao.startswith(PREFIXO_DE_CONFIRMACAO):
        return None
    resto = botao[len(PREFIXO_DE_CONFIRMACAO) :]
    return resto if _UUID.fullmatch(resto) else None


def _texto(valor: Any) -> str:
    return str(valor).lower() if valor is not None else ""


def _papel(cursor: Any, tenant_id: str, contact_id: str) -> tuple[str | None, Any]:
    cursor.execute(SQL_PAPEL_DO_CONTACTO, (tenant_id, contact_id))
    linha = cursor.fetchone()
    if linha is None:
        return None, None
    return linha[0], linha[1]


def _bloqueada(papel_mudou_at: Any, agora: datetime.datetime) -> bool:
    """Se a troca de telefone e recente demais. `None` e um dono de sempre.

    O `papel_mudou_at` so se escreve na **troca** (no provisionamento fica
    `NULL`, pela `definir_dono` da `0070`), pelo que um dono que nunca trocou de
    telefone nunca esta bloqueado.
    """
    if papel_mudou_at is None:
        return False
    return agora < papel_mudou_at + BLOQUEIO_DEPOIS_DA_TROCA


def propor(
    ligacao: Any,
    tenant_id: str,
    contact_id: str,
    tipo: str,
    ref: str,
    agora: datetime.datetime,
) -> str:
    """Cria a accao pendente, ou devolve a que ja existe para `(tipo, ref)`.

    **So para o dono**: um contacto que nao e o `papel='dono'` deste tenant
    levanta `AccaoRecusadaError("nao_e_dono")` e nada se escreve. O `ref` e o
    identificador do que se vai confirmar (um rascunho, uma proposta) e e do
    chamador garantir que muda quando o conteudo muda: a `UNIQUE` devolve a
    accao antiga a um `ref` repetido, seja qual for o estado dela.

    O `tipo` fora dos tres levanta antes da base — o `CHECK` recusava-o tambem,
    mas com um `23514` no meio de uma transaccao.
    """
    if tipo not in TIPOS:
        raise ValueError("tipo_desconhecido")
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        papel, _mudou = _papel(cursor, tenant_id, contact_id)
        if papel != PAPEL_DONO:
            raise AccaoRecusadaError(NAO_E_DONO)
        cursor.execute(
            SQL_PROPOR, (tenant_id, contact_id, tipo, ref, agora + VALIDADE_DO_BOTAO)
        )
        linha = cursor.fetchone()
        if linha is None:
            cursor.execute(SQL_ACCAO_DA_REF, (tenant_id, tipo, ref))
            linha = cursor.fetchone()
        return _texto(linha[0])


def confirmar(
    ligacao: Any,
    tenant_id: str,
    contact_id: str,
    botao: object,
    agora: datetime.datetime,
) -> str:
    """O desfecho de um toque no botao. Um dos `DESFECHOS`, e so `confirmada` executa.

    A ordem das perguntas e a de quem tem de saber o que: a forma do botao sem
    base; depois **quem escreve** (dono, e fora do bloqueio da troca); depois o
    *compare-and-set*; e so se ele falhar, o diagnostico. No diagnostico o
    `outro_contacto` vem **antes** do `ja_confirmada`: a quem nao e dono da
    accao nao se diz em que estado ela esta.
    """
    action_id = accao_do_botao(botao)
    if action_id is None:
        return NAO_E_BOTAO
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        papel, mudou = _papel(cursor, tenant_id, contact_id)
        if papel != PAPEL_DONO:
            return NAO_E_DONO
        if _bloqueada(mudou, agora):
            return BLOQUEADA_PELA_TROCA
        cursor.execute(SQL_CONFIRMAR, (agora, tenant_id, action_id, contact_id, agora))
        if cursor.fetchone() is not None:
            return CONFIRMADA
        cursor.execute(SQL_DIAGNOSTICO, (tenant_id, action_id))
        linha = cursor.fetchone()
        if linha is None:
            return DESCONHECIDA
        estado, dono_da_accao, expira_at = linha
        if _texto(dono_da_accao) != _texto(contact_id):
            return OUTRO_CONTACTO
        if estado == CONFIRMADA:
            return JA_CONFIRMADA
        if estado == "pendente" and expira_at <= agora:
            cursor.execute(SQL_EXPIRAR, (tenant_id, action_id, agora))
        # `expirada`, `cancelada`, ou uma `pendente` fora de prazo: nenhuma
        # executa, e ao dono diz-se o mesmo — o botao ja nao vale.
        return EXPIRADA


__all__ = [
    "AccaoRecusadaError",
    "BLOQUEIO_DEPOIS_DA_TROCA",
    "DESFECHOS",
    "TIPOS",
    "VALIDADE_DO_BOTAO",
    "accao_do_botao",
    "confirmar",
    "propor",
]
