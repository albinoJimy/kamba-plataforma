"""A exportacao portatil e a oposicao (KAM-070, criterios 2 e 7).

## O que faz a exportacao ser **do titular** e nao de um `contact_id` qualquer

A funcao recebe o `Pedido` e nao um `contact_id`. Nao e preferencia de
assinatura: e a unica ligacao que torna o criterio 1 verdadeiro tambem aqui. O
`contact_id` que esta funcao le so pode ser o de um pedido que o
`PortaDeDireitos.receber` aceitou — isto e, o do proprio requerente —, porque e
o `receber` que compara o requerente com o alvo e levanta quando divergem.

Com um `contact_id` no argumento, exportar os dados de outra pessoa era uma
chamada **bem formada**: passava os tipos, passava a RLS (o contacto e do mesmo
tenant) e devolvia tudo. E o ensaio que o apanha e o
`test_a_exportacao_so_aceita_um_pedido_aceite`, que nao mede a funcao — mede a
**assinatura** dela.

## O tecto do TTL nao esta aqui

Esta no `kamba_core.storage`, que ja o tinha, e este modulo **chama** quem o
verifica em vez de verificar outra vez. Ver a nota do `TTL_DA_EXPORTACAO_S` no
`contrato.py`: a primeira versao deste modulo declarava um tecto proprio, e isso
e a segunda leitora do mesmo predicado — o defeito mais serio que a revisao
adversarial do KAM-069 encontrou, e que nenhum portao deste repositorio ve.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .consultas import EXPORTACAO, SQL_EMITIR, SQL_REGISTAR_OPOSICAO
from .contrato import (
    CANAL_DO_CONSENTIMENTO,
    CLASSE_PII,
    EVENTO_CONSENT_WITHDRAWN,
    FINALIDADE_DA_OPOSICAO,
    FINALIDADES_DO_EVENTO,
    SEPARADOR,
    TEXTO_DA_OPOSICAO,
    TIPO_EXPORTACAO,
    TIPO_OPOSICAO,
    TTL_DA_EXPORTACAO_S,
    VERSAO_DOS_EVENTOS,
    Assinador,
    Pedido,
    Relogio,
)

#: A versao do formato do JSON portatil.
#:
#: Esta no documento e nao so no nome do ficheiro: quem recebe uma exportacao
#: guarda-a, e dentro de dois anos o que ele tem e o ficheiro — sem versao
#: dentro, nao ha como saber que formato ler. E o mesmo argumento pelo qual os
#: envelopes de evento levam `versao`.
VERSAO_DO_FORMATO = 1

#: A classe de dados da chave do STO onde a exportacao fica.
#:
#: **Nao e `media`**: uma exportacao e dado pessoal consolidado de um titular,
#: que e a coisa mais sensivel que esta plataforma produz num ficheiro — juntar
#: num objecto o contacto, as conversas, as encomendas e os consentimentos e
#: fazer um alvo que nenhuma das quatro tabelas era sozinha. A classe propria e
#: o que permite ao STO lhe dar retencao e politica propria.
CLASSE_DA_EXPORTACAO = "dsar"

#: A ordem por que as quatro consultas correm, e os nomes do criterio 2.
#:
#: **Nao e o que torna o `sha256` reproduzivel** — isso e o `sort_keys=True` do
#: `documento()`, e esta linha dizia o contrario antes desta emenda. O que esta
#: tupla faz e duas coisas mais pequenas e verdadeiras: fixa a **ordem de
#: execucao** (quatro consultas na mesma transaccao, sempre na mesma ordem, o
#: que torna um `log` de consultas lento comparavel entre corridas) e e a lista
#: que o `exportar` itera em vez de iterar o `EXPORTACAO` — pelo que uma
#: coleccao nova tem de entrar **aqui** para sair no documento, e o ensaio
#: `test_as_quatro_coleccoes_do_criterio_estao_na_saida` conta-as.
ORDEM_DAS_COLECCOES = ("contacto", "conversas", "encomendas", "consentimentos")


def _linhas(cursor: Any) -> tuple[Mapping[str, object], ...]:
    """As linhas como mapas, da `cursor.description`.

    **Nao assume um `row_factory`**, pela razao que o `destinos/dbapi.py` ja
    escreveu: com tuplos, um `linha["estado"]` levanta `TypeError` — que quem
    apanha excepcoes traduziria para «nao se conseguiu ler», escondendo um erro
    de configuracao atras de uma resposta vazia.
    """
    colunas = [descricao[0] for descricao in cursor.description]
    return tuple(dict(zip(colunas, linha, strict=True)) for linha in cursor.fetchall())


def exportar(cursor: Any, pedido: Pedido) -> dict[str, object]:
    """O JSON portatil das quatro coleccoes do criterio 2.

    Itera o `EXPORTACAO` do `consultas.py` e **nao** uma lista escrita aqui: uma
    consulta nova entra naquele mapa (senao a exportacao nao a chama) e e medida
    pelo ensaio do predicado do contacto sem ninguem se lembrar dela. Uma lista
    escrita a mao provava as coleccoes de que alguem se lembrou.

    Levanta se o pedido nao for de exportacao: o tipo do pedido e que autoriza a
    operacao, e um pedido de rectificacao nao autoriza uma copia de tudo.
    """
    if pedido.tipo != TIPO_EXPORTACAO:
        raise ValueError(
            f"exportar sobre um pedido de {pedido.tipo}: o tipo do pedido e que "
            "autoriza a operacao"
        )
    coleccoes: dict[str, object] = {}
    for nome in ORDEM_DAS_COLECCOES:
        cursor.execute(EXPORTACAO[nome], (pedido.contact_id,))
        coleccoes[nome] = [dict(linha) for linha in _linhas(cursor)]
    return {
        "formato": VERSAO_DO_FORMATO,
        "dsar_id": pedido.dsar_id,
        "contact_id": pedido.contact_id,
        "tenant_id": pedido.tenant_id,
        "recebido_at": pedido.recebido_at,
        "coleccoes": coleccoes,
    }


def documento(exportado: Mapping[str, object]) -> bytes:
    """O documento em bytes, canonico e reproduzivel.

    `sort_keys` e `separators` sem espacos: dois documentos com o mesmo conteudo
    tem de dar o mesmo `sha256`, senao a prova de que o titular recebeu **este**
    documento depende de quem o serializou. O `default=str` leva os
    `datetime` para ISO 8601, que e o que o conjunto usa.

    `ensure_ascii=False`: um nome com `ç` nao se escreve `\\u00e7` num ficheiro
    que uma pessoa pode abrir. O ficheiro e UTF-8, como todo o resto.
    """
    return json.dumps(
        exportado,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def resumo(documento_em_bytes: bytes) -> str:
    """O `sha256` do documento, em hexadecimal."""
    return hashlib.sha256(documento_em_bytes).hexdigest()


def entregar(
    armazenamento: Assinador,
    contexto: Any,
    referencia: Any,
    *,
    ttl_s: int = TTL_DA_EXPORTACAO_S,
) -> str:
    """O URL assinado da exportacao (criterio 2: «TTL <= 5 min»).

    **Nao valida o `ttl_s`**, e e deliberado: quem valida e o
    `ArmazenamentoPorTenant.sign_url`, que exige
    `1 <= ttl_seconds <= TTL_MAXIMO_S` e levanta `TtlInvalidoError`. Validar
    aqui tambem era a segunda leitora do mesmo predicado — ver a nota do modulo.

    A omissao e o tecto, e nao um valor mais curto: para um JSON que se
    descarrega uma vez, o prazo mais curto que serve e o unico que nao obriga o
    titular a repetir o pedido.
    """
    return armazenamento.sign_url(contexto, referencia, ttl_seconds=ttl_s)


def opor(cursor: Any, pedido: Pedido) -> tuple[bool, str]:
    """Registra a oposicao e anuncia o `consent.withdrawn` (criterio 7).

    Devolve `(escreveu, event_id)`: `escreveu` e `False` quando a oposicao ja
    estava registada.

    ## A lista de supressao nao e nova, e nao podia ser

    O criterio diz «inclui o contacto na lista de supressao de marketing
    («PARAR»)». Essa lista **e** `purpose = 'marketing'` com `accepted = false`
    no `platform.consent_event` — e o que o `parar.ts` do KAM-022 grava quando
    alguem escreve «PARAR», e o que a vista `consent_actual` devolve como estado
    actual. Escrever isso **e** entrar nessa lista. Uma tabela de supressao
    propria era uma segunda lista que teria de concordar com a primeira, e a
    primeira que divergisse deixava alguem a receber marketing depois de se ter
    oposto — com as duas superficies a dizer que estava suprimido.

    ## A idempotencia e da base, e sai de graca

    A `0015` tem `UNIQUE (tenant_id, contact_id, purpose, evidence_hash)`. O
    `evidence_hash` daqui e `sha256` do par (`dsar_id`, finalidade), que e
    **determinista**: opor-se duas vezes pelo mesmo pedido da o mesmo resumo e a
    segunda escrita nao acontece. Nao e um `ON CONFLICT` a tapar um descuido —
    e o criterio 8 («o pedido repetido e idempotente») satisfeito pela chave que
    a tabela ja tinha.

    **O evento publica-se de qualquer maneira**, mesmo quando a linha nao foi
    escrita, e isso e escolha com razao: o `event_id` e a chave de idempotencia
    global do *outbox*, pelo que um segundo anuncio do mesmo facto e um segundo
    evento que os consumidores processam uma vez cada — e calar o anuncio quando
    a linha ja existia deixava um consumidor que falhou na primeira vez sem
    nunca mais o ouvir.
    """
    if pedido.tipo != TIPO_OPOSICAO:
        raise ValueError(
            f"opor sobre um pedido de {pedido.tipo}: o tipo do pedido e que "
            "autoriza a operacao"
        )
    prova = hashlib.sha256(
        SEPARADOR.join((pedido.dsar_id, FINALIDADE_DA_OPOSICAO)).encode("utf-8")
    ).digest()
    cursor.execute(
        SQL_REGISTAR_OPOSICAO,
        (
            pedido.tenant_id,
            pedido.contact_id,
            FINALIDADE_DA_OPOSICAO,
            TEXTO_DA_OPOSICAO,
            CANAL_DO_CONSENTIMENTO,
            prova,
            pedido.recebido_at,
        ),
    )
    escreveu = cursor.fetchone() is not None
    cursor.execute(
        SQL_EMITIR,
        (
            EVENTO_CONSENT_WITHDRAWN,
            VERSAO_DOS_EVENTOS,
            pedido.tenant_id,
            pedido.contact_id,
            json.dumps(
                {
                    "contact_id": pedido.contact_id,
                    "finalidade": FINALIDADE_DA_OPOSICAO,
                }
            ),
            CLASSE_PII,
            list(FINALIDADES_DO_EVENTO),
            pedido.dsar_id,
        ),
    )
    return escreveu, str(cursor.fetchone()[0])


__all__ = [
    "CLASSE_DA_EXPORTACAO",
    "ORDEM_DAS_COLECCOES",
    "VERSAO_DO_FORMATO",
    "documento",
    "entregar",
    "exportar",
    "opor",
    "resumo",
]
