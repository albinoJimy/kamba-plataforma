"""A orquestracao do apagamento, e o fecho pelo *ledger* (KAM-070, criterios 3 a 6).

O criterio 3 e uma frase com uma consequencia inteira dentro:

    «`privacy.erasure_requested` e consumido por cofre de contactos, AGR, STO,
    DAT, IDX e Chatwoot; cada um emite `privacy.erasure_applied`; o pedido so
    passa a `concluido` quando **todos** aplicaram.»

## Quem conta nao e o barramento, e isso nao foi escolha

O contrato publicado do `privacy.erasure_applied`
(`contratos/eventos/privacy.erasure_applied/v2.schema.json`) tem **um** campo de
`payload`, o `contact_id`: **nao diz quem aplicou**. Fechar o pedido a contar
eventos `applied` fechava-o ao sexto evento, viesse ele de seis componentes ou
seis vezes do mesmo — e o caso que importa e precisamente o segundo, porque uma
reentrega de fila e normal e o criterio 8 manda-a ser idempotente.

Quem conta e o `platform.erasure_ledger`, pela unicidade
`(tenant_id, dsar_id, escopo)`: seis linhas sao seis escopos, e a sexta
reentrega do mesmo nao e a sexta linha. A alternativa era uma `v3` do contrato
com o escopo dentro — uma mudanca de contrato publicado, com o `contract_diff`,
os esquemas gerados e o catalogo atras dela, para passar a informacao que a
tabela ja tem.

**E o ledger tinha de existir de qualquer maneira**, o que torna a escolha
barata: o criterio 6 pede um «*erasure ledger* (sem dado pessoal) reaplicado
apos restauro», e o `specs/EPIC-08_Topologia_Operacao.md` ja escreve o *hook*
que o le. Contar pelos eventos deixava duas estruturas a responder a mesma
pergunta — e a licao mais cara do KAM-069 e que duas leitoras da mesma coisa
divergem e nenhum portao o ve.

## O que este modulo **nao** faz, e o credor de cada coisa

Nao apaga nada. Cada escopo e apagado pelo processo que detem a loja:

* `cofre` — o `Identidade.eraseContact` do `packages/core-ts/src/identity/`, que ja
  existe desde o KAM-008 e ja faz o que o criterio 4 pede (`contact_endpoints` a
  zero, `erased_at` preenchido, DEK destruida). Este modulo **nao** escreve uma
  segunda versao disso: liga-se a ela;
* `agr`, `sto`, `dat`, `idx`, `chatwoot` — os consumidores de cada componente.
  O que este modulo entrega e o pedido, o evento, o registo e o fecho; cada
  consumidor chama o `registar_aplicacao` quando acabar.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .consultas import (
    SQL_EMITIR,
    SQL_ESCOPOS_APLICADOS,
    SQL_REGISTAR_APLICACAO,
    SQL_SUJEITOS_APAGADOS,
)
from .contrato import (
    CLASSE_PII,
    ESCOPOS,
    EVENTO_ERASURE_APPLIED,
    EVENTO_ERASURE_REQUESTED,
    FINALIDADES_DO_EVENTO,
    TIPO_ELIMINACAO,
    VERSAO_DOS_EVENTOS,
    Aplicacao,
    ApagamentoIncompleto,
    Pedido,
    Relogio,
    SujeitoApagado,
    exigir_escopo,
)


def pedir_apagamento(cursor: Any, pedido: Pedido) -> str:
    """Poe o `privacy.erasure_requested` no *outbox*. Devolve o `event_id`.

    **Recebe o `Pedido` e nao um `contact_id`**, e e a ligacao que o criterio 1
    exige: o unico `contact_id` que esta funcao pode anunciar e o de um pedido
    que o `receber` aceitou — isto e, o do proprio requerente. Com um
    `contact_id` solto no argumento, pedir o apagamento dos dados de outra
    pessoa era uma chamada bem formada, e o evento ja tinha saido quando alguem
    percebesse.

    Corre no **cursor de quem chama**, que e o mesmo da linha do pedido: e o
    *outbox* transaccional do ADR-009, pelo que o evento e o pedido ficam ou os
    dois ou nenhum. Com transaccoes separadas havia um instante em que seis
    componentes apagam dados por um pedido que nao existe.
    """
    if pedido.tipo != TIPO_ELIMINACAO:
        raise ValueError(
            f"pedir apagamento sobre um pedido de {pedido.tipo}: o tipo do pedido "
            "e que autoriza a operacao"
        )
    return _emitir(cursor, EVENTO_ERASURE_REQUESTED, pedido)


def anunciar_aplicacao(cursor: Any, pedido: Pedido) -> str:
    """Poe o `privacy.erasure_applied` no *outbox*. Devolve o `event_id`.

    E o anuncio do criterio 3, e **nao e o que fecha o pedido** — ver a nota do
    modulo. Quem fecha e o *ledger*.

    ## Corre no cursor da **aplicacao**, e nao no do escopo que aplicou

    A `0004` concede `EXECUTE` em `platform.evt_emitir` **so ao `kamba_app`** —
    nem ao `kamba_batch` nem ao `kamba_identity`. Logo o consumidor do `cofre`,
    que corre como `kamba_identity`, e o do `dat`, que corre como
    `kamba_batch`, **nao podem emitir**: levantam `42501`.

    Foi achado da revisao adversarial deste ramo, e a leitura que ele obriga e
    esta: os dois passos de um escopo tem papeis diferentes e nao se juntam numa
    transaccao.

        registar_aplicacao   no papel do escopo (`kamba_identity`,
                             `kamba_batch` ou `kamba_app`) — e a linha do
                             *ledger*, que e **o que conta** para o criterio 3
        anunciar_aplicacao   no papel da aplicacao — e o anuncio, que e o que o
                             criterio 3 pede a seguir

    **E essa ordem e a certa, nao um remedio.** A linha do *ledger* e o facto; o
    evento e a noticia. Anunciar primeiro deixava um `erasure_applied` publicado
    sobre um escopo que ainda nao aplicou, e o pedido continuava a nao fechar —
    o inverso nao perde nada, porque quem fecha le a tabela.

    Conceder `EXECUTE` aos outros dois papeis era **afrouxar o criterio de outro
    ticket** a partir deste, como no caso do `kamba_agr`, e nao e decisao de
    quem implementa os direitos do titular.
    """
    return _emitir(cursor, EVENTO_ERASURE_APPLIED, pedido)


def _emitir(cursor: Any, tipo: str, pedido: Pedido) -> str:
    """O `platform.evt_emitir` com o envelope dos contratos publicados.

    O `agregado.tipo` e `'contact'` — os dois esquemas declaram-no com `const` —
    e o `agregado.id` e o `contact_id`. O `id`, o `seq`, a `particao` e o
    `registado_em` sao da funcao SQL e nao deste modulo: e ela que serializa o
    agregado, e um `seq` calculado aqui era um `seq` que duas transaccoes
    simultaneas escolhiam igual.

    **O `payload` leva so o `contact_id`.** Nao e minimalismo: e o que os
    esquemas publicados declaram com `additionalProperties: false`, pelo que um
    `dsar_id` dentro dele fazia o envelope violar o contrato do proprio evento —
    e o consumidor recusava-o.

    **O `dsar_id` vai no `correlacao_id`**, que e o campo do **envelope** para
    isso e nao do `payload`. Sem ele, um consumidor que recebesse o evento tinha
    de procurar o pedido aberto daquele contacto — unico pelo indice
    `dsar_requests_aberto_uq`, mas uma leitura e uma suposicao em vez de um
    dado. Com ele, o escopo que acabou de apagar sabe exactamente em que linha
    do `erasure_ledger` escrever.
    """
    cursor.execute(
        SQL_EMITIR,
        (
            tipo,
            VERSAO_DOS_EVENTOS,
            pedido.tenant_id,
            pedido.contact_id,
            json.dumps({"contact_id": pedido.contact_id}),
            CLASSE_PII,
            list(FINALIDADES_DO_EVENTO),
            pedido.dsar_id,
        ),
    )
    return str(cursor.fetchone()[0])


def registar_aplicacao(
    cursor: Any, *, pedido: Pedido, escopo: str, relogio: Relogio
) -> Aplicacao | None:
    """Escreve a linha do escopo no ledger. `None` se ja estava escrita.

    O `None` **nao e erro**: e a repeticao que o criterio 8 manda ser
    idempotente. Um consumidor que receba a mesma entrega duas vezes chama isto
    duas vezes, e a segunda nao escreve — a unicidade
    `(tenant_id, dsar_id, escopo)` e que o garante, e nao uma leitura previa,
    que duas entregas simultaneas passavam as duas.
    """
    exigir_escopo(escopo)
    cursor.execute(
        SQL_REGISTAR_APLICACAO,
        (
            pedido.tenant_id,
            pedido.dsar_id,
            pedido.contact_id,
            escopo,
            relogio.agora(),
        ),
    )
    linha = cursor.fetchone()
    if linha is None:
        return None
    erasure_id, tenant_id, dsar_id, contact_id, escopo_lido, aplicado_at = linha
    return Aplicacao(
        erasure_id=str(erasure_id),
        tenant_id=str(tenant_id),
        dsar_id=str(dsar_id),
        contact_id=str(contact_id),
        escopo=str(escopo_lido),
        aplicado_at=aplicado_at,
    )


def escopos_aplicados(cursor: Any, dsar_id: str) -> tuple[str, ...]:
    """Os escopos que ja tem linha no ledger, por ordem alfabetica."""
    cursor.execute(SQL_ESCOPOS_APLICADOS, (dsar_id,))
    return tuple(str(linha[0]) for linha in cursor.fetchall())


def escopos_em_falta(cursor: Any, dsar_id: str) -> tuple[str, ...]:
    """Os escopos que faltam, pela ordem do `ESCOPOS`.

    Pela ordem da constante e nao alfabetica: a lista do criterio 3 esta escrita
    numa ordem — cofre, AGR, STO, DAT, IDX, Chatwoot — e uma mensagem que a siga
    le-se contra o criterio sem reordenar nada.
    """
    aplicados = set(escopos_aplicados(cursor, dsar_id))
    return tuple(escopo for escopo in ESCOPOS if escopo not in aplicados)


def apagamento_completo(cursor: Any, dsar_id: str) -> bool:
    """`true` quando os seis escopos tem linha (criterio 3)."""
    return not escopos_em_falta(cursor, dsar_id)


def exigir_apagamento_completo(cursor: Any, dsar_id: str) -> None:
    """Levanta `ApagamentoIncompleto` com **quem falta**, nao com quantos.

    A mensagem de um pedido que nao fecha tem de nomear os escopos em falta ou
    ninguem o resolve: «faltam dois» manda procurar, «faltam `sto` e `idx`»
    manda agir.
    """
    faltam = escopos_em_falta(cursor, dsar_id)
    if faltam:
        raise ApagamentoIncompleto(faltam)


def concluir_apagamento(cursor: Any, porta: Any, pedido: Pedido) -> Pedido | None:
    """Fecha o pedido de eliminacao **depois** de exigir os seis escopos.

    **E o impositor do criterio 3, e a primeira versao deste ramo nao o tinha.**
    A *docstring* do `PortaDeDireitos.concluir` dizia que esta funcao existia e
    era o unico caminho que fechava uma eliminacao; `grep` dava **uma**
    ocorrencia — a propria frase. O `concluir` fechava qualquer pedido, o
    `exigir_apagamento_completo` nao tinha chamador nenhum, e o criterio 3
    estava satisfeito por convencao: o titular era informado de que o
    apagamento estava feito com o `erasure_ledger` vazio. Foi o achado mais
    serio da revisao adversarial.

    **E nenhum ensaio o podia apanhar**, que e o que faz disto uma classe de
    defeito: os cinco ensaios sobre `apagamento_completo` e `escopos_em_falta`
    ficavam verdes qualquer que fosse o comportamento do `concluir`, porque
    **nao havia ligacao para mutar**. Hoje ha duas, e as duas tem ensaio: esta
    funcao le o *ledger* antes de escrever, e o `concluir` **recusa** um pedido
    de eliminacao (`FechoSemLedger`).

    A ordem nao e negociavel e e a razao de o `exigir` vir primeiro: com o fecho
    primeiro, um `ApagamentoIncompleto` levantado depois deixava a linha
    `concluido` escrita nesta transaccao — e se quem chama apanhasse a excepcao
    sem reverter, ficava fechada.

    Devolve `None` quando o pedido ja estava fechado, como o `concluir`: o
    segundo fecho nao e erro, e a idempotencia e do `WHERE estado <>
    'concluido'` do `SQL_CONCLUIR`.
    """
    if pedido.tipo != TIPO_ELIMINACAO:
        raise ValueError(
            f"concluir_apagamento sobre um pedido de {pedido.tipo}: os outros "
            "tres tipos fecham pelo `PortaDeDireitos.concluir`"
        )
    exigir_apagamento_completo(cursor, pedido.dsar_id)
    return porta._fechar(cursor, pedido.dsar_id)


def sujeitos_apagados(cursor: Any) -> tuple[SujeitoApagado, ...]:
    """O par `(contact_id, erased_at)` por contacto apagado (criterio 6).

    E o que o *hook* de reaplicacao apos restauro le — o
    `sujeitos_a_reaplicar(ledger, restaurado_de)` que o KAM-079 entrega — e a
    razao de ser `min(aplicado_at)` e o predicado do restauro, nao elegancia:
    uma copia tirada **antes** do primeiro apagamento tem o sujeito de certeza,
    uma tirada depois pode ja nao o ter. Com o `max`, as copias tiradas no meio
    de um apagamento — as que ficam com metade do titular dentro — saiam de
    fora.

    **Os nomes divergem do `specs/EPIC-08_Topologia_Operacao.md`**, que escreve
    o contrato como `erasure_ledger(subject_ref, erased_at)`. O `subject_ref`
    nao e canonico: o canonico e o `sujeito_ref` do dicionario §3, que e
    `HMAC(chave_mensal, contact_id)` — e **nao serve de chave de um ledger**,
    porque a chave roda ao mes e o mesmo contacto tem refs diferentes em meses
    diferentes. A chave e o `contact_id`, que e o que a DoD do bloco autoriza
    por escrito. A divergencia fica registada no bloco com credor; o `EPIC-08`
    nao se toca neste ramo: a reconciliacao dos dois nomes e de quem governa
    aquele contrato.
    """
    cursor.execute(SQL_SUJEITOS_APAGADOS)
    return tuple(
        SujeitoApagado(contact_id=str(contact_id), erased_at=erased_at)
        for contact_id, erased_at in cursor.fetchall()
    )


def sujeitos_a_reaplicar(
    ledger: Sequence[SujeitoApagado], restaurado_de: Any
) -> tuple[SujeitoApagado, ...]:
    """Os sujeitos que um restauro de `restaurado_de` faz voltar (criterio 6).

    O predicado, e a fronteira exacta: quem foi apagado em `T' > T` **volta**
    com o restauro e tem de ser reaplicado; quem foi apagado em `T' <= T` nao
    esta na copia. A fronteira (`T' == T`) e **nao reaplicar**, que e a mesma
    resposta que a *fixture* do KAM-079 declara para o caso
    `apagado-na-fronteira`.

    Puro e idempotente: nao le relogio e nao escreve nada. A ordem e cronologica,
    que e o que mantem o `audit_log` do restauro a contar a mesma historia que o
    original.

    **Nao reaplica o ledger inteiro, e isso nao e elegancia:** um passo que
    apagasse tudo faria `DELETE` sobre linhas inexistentes e, num ledger grande,
    transformava um restauro de 30 minutos num de horas.
    """
    return tuple(
        sujeito
        for sujeito in sorted(ledger, key=lambda s: (s.erased_at, s.contact_id))
        if sujeito.erased_at > restaurado_de
    )


__all__ = [
    "anunciar_aplicacao",
    "concluir_apagamento",
    "apagamento_completo",
    "escopos_aplicados",
    "escopos_em_falta",
    "exigir_apagamento_completo",
    "pedir_apagamento",
    "registar_aplicacao",
    "sujeitos_a_reaplicar",
    "sujeitos_apagados",
]
