"""Dois tenants com canarios unicos em **todas** as tabelas isoladas.

O `docs/tecnica/08` §3.7 descreve o oraculo: «o canario de B nao aparece em
respostas». Um canario e uma cadeia unica, posta numa coluna de uma linha de B,
que nao pode aparecer em nada do que A consiga ler.

Cada tabela isolada tem aqui uma **receita**: como inserir uma linha de um
tenant (sem definir contexto — quem chama decide com que papel e contexto), que
coluna leva o canario, e que coluna a aplicacao pode alterar. A suite confronta
este registo com o catalogo: **uma tabela nova com `tenant_id` e sem receita
faz o gate 6 falhar**, porque uma tabela que a suite nao sabe semear e uma
tabela que a suite nao testa.

Desde o KAM-008 a receita diz tambem **com que papel** a tabela se le e escreve.
Ate ai era sempre `kamba_app`; as tres tabelas de identidade so sao lidas por
`kamba_identity`, e testa-las como `kamba_app` provava o privilegio em falta, nao
a politica. Cada tabela e atacada com o papel que **consegue** le-la — que e o
unico contra o qual a RLS e a ultima barreira.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from typing import Callable

#: Versao de chave que as sementes de identidade referem. `retirada`: nao ocupa
#: o lugar da `actual` nem da `anterior`, de que so pode haver uma.
KID_DE_SEMENTE = "kid-de-semente"


def _texto(canario: str) -> object:
    return canario


def _octetos(canario: str) -> object:
    """O canario numa coluna `bytea`: os mesmos caracteres, em octetos."""
    return canario.encode("ascii")


def _resumo(canario: str) -> object:
    """O canario numa coluna que so aceita 32 octetos (um HMAC): o SHA-256 dele.

    Continua unico por tenant e por tabela, e e isso que o oraculo precisa.
    """
    return hashlib.sha256(canario.encode("ascii")).digest()


def _uuid(canario: str) -> object:
    """O canario numa coluna `uuid`: os primeiros 16 octetos do SHA-256 dele.

    A `conversations` (KAM-014) e a primeira tabela isolada **sem coluna de
    texto livre**: as oito sao dois UUID de referencia, um UUID de chave, um
    dominio fechado (`mode`) e tres tempos. O canario vai na chave primaria,
    que e a unica que aceita um valor arbitrario — e continua unico por tenant
    e por tabela, que e o que o oraculo precisa.
    """
    return uuid.UUID(hashlib.sha256(canario.encode("ascii")).hexdigest()[:32])


@dataclasses.dataclass(frozen=True)
class Receita:
    #: Insere uma linha do tenant com o canario. Nao define contexto.
    inserir: Callable
    #: Coluna onde o canario fica.
    coluna_do_canario: str
    #: Coluna que o papel da tabela pode alterar (para os testes de escrita
    #: cruzada). `None` quando **nenhum** papel sujeito a RLS lhe pode escrever:
    #: `events_outbox` (o estado de publicacao e do publicador) e `events_log`
    #: (arquivo imutavel). Nesse caso o que se prova e que o papel **nao tem** o
    #: privilegio de `UPDATE` — que e mais forte do que provar que a politica o
    #: recusa, porque nao depende da politica estar certa.
    coluna_alteravel: str | None
    #: Um valor valido para essa coluna, ou `None` quando ela e `None`.
    valor_alteravel: object
    #: Identidade (de `ligacao.PAPEIS`) que le e escreve a tabela em producao.
    papel: str = "app"
    #: Identidade que semeia e apaga. `kamba_batch` onde ele tem privilegios; o
    #: administrador da instancia nas tabelas de identidade e de eventos, onde
    #: nao tem (ou onde o `INSERT` esta sob `WITH CHECK` e as receitas nao
    #: definem contexto).
    semeador: str = "batch"
    #: Como o canario fica guardado na coluna (texto, octetos ou resumo).
    guardado: Callable[[str], object] = _texto
    #: `True` quando o `papel` **insere** na tabela, e a RLS e a ultima barreira
    #: na escrita. `False` quando nenhum papel sujeito a RLS lhe escreve — e o
    #: caso do `events_log`, que so o `kamba_batch` arquiva (`BYPASSRLS`, *job*
    #: auditado): a politica dessa tabela protege a **leitura**, e o que
    #: protege a escrita e a falta de privilegio. Os testes de escrita cruzada
    #: trocam, nessas tabelas, «a politica recusa» por «o privilegio nem
    #: existe».
    escrita_do_papel: bool = True
    #: `False` quando o papel da tabela **nao a le**. A `events_dlq` e a
    #: primeira: `kamba_app` abre a entrada e nao tem `SELECT`, porque o `id` e
    #: sequencial e um papel sujeito a RLS que o lesse media pela sequencia
    #: quantas falhas o vizinho teve (dicionario §2, KAM-006). Nessas, o
    #: X-03/X-04 troca «a politica devolve zero linhas» por «o privilegio nem
    #: existe», que e mais forte: nao depende de a politica estar certa.
    leitura_do_papel: bool = True


def _linha_de_auditoria(cursor, tenant_id: str, canario: str) -> None:
    """Uma linha de `audit_log` com o canario no `entity_id` (KAM-012).

    Escreve-se pelo caminho normal: o trigger `audit_encadear` poe o
    `criado_at`, o `prev_hash` e o `row_hash`, e avanca a cabeca da cadeia.
    Semeada pelo administrador, porque o `INSERT` do `kamba_app` esta sob
    `WITH CHECK` e esta receita nao define contexto.
    """
    cursor.execute(
        "INSERT INTO platform.audit_log "
        "(tenant_id, actor_type, actor_id, action, entity, entity_id, payload_hash) "
        "VALUES (%s, 'staff', 'semente', 'price.update', 'produto', %s, sha256('x'))",
        (tenant_id, canario),
    )


def _tenant(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.tenants (id, tipo, nome) VALUES (%s, 'pme', %s)",
        (tenant_id, canario),
    )


def _canal(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.tenant_channels "
        "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, token_ref) "
        "VALUES (%s, %s, %s, 'coexistencia', 'vendedor', %s)",
        (tenant_id, canario, f"pnid-{uuid.uuid4().hex}", f"ref-opaca/{uuid.uuid4().hex}"),
    )


def _entitlement(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.entitlements (tenant_id, modulo) VALUES (%s, %s)",
        (tenant_id, canario),
    )


# As tres receitas de identidade (KAM-008). O contacto e a DEK de que a linha
# precisa vao buscar-se por subconsulta, com um UUID aleatorio de recurso: quando
# a receita e usada para **atacar** (inserir uma linha de B com o contexto de A),
# a subconsulta nao ve o contacto de B, e o que tem de recusar a linha e a
# politica — que se avalia antes das FK — e nao um valor nulo.


def _contacto(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.contacts (tenant_id, phone_hmac, hmac_kid) "
        "VALUES (%s, %s, %s)",
        (tenant_id, _resumo(canario), KID_DE_SEMENTE),
    )


_UM_CONTACTO = (
    "COALESCE((SELECT contact_id FROM platform.contacts WHERE tenant_id = %s "
    "ORDER BY criado_at LIMIT 1), gen_random_uuid())"
)
_UMA_DEK = (
    "COALESCE((SELECT dek_id FROM platform.contact_deks WHERE tenant_id = %s "
    "ORDER BY criado_at LIMIT 1), gen_random_uuid())"
)


def _dek(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.contact_deks (tenant_id, contact_id, wrapped_dek, kek_id) "
        f"VALUES (%s, {_UM_CONTACTO}, %s, %s)",
        (tenant_id, tenant_id, uuid.uuid4().bytes * 3, canario),
    )


def _endpoint(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.contact_endpoints "
        "(tenant_id, contact_id, dek_id, tipo, bsuid_hmac, hmac_kid, bsuid_enc) "
        f"VALUES (%s, {_UM_CONTACTO}, {_UMA_DEK}, 'bsuid', %s, %s, %s)",
        (
            tenant_id, tenant_id, tenant_id,
            _resumo(canario + ":bsuid"), KID_DE_SEMENTE, _octetos(canario),
        ),
    )


#: O canal do tenant, para a FK composta da conversa. Mesma forma do
#: `_UM_CONTACTO`, e pela mesma razao: quando a receita e usada para **atacar**
#: (inserir uma linha de B com o contexto de A), a subconsulta nao ve o canal de
#: B, e o que tem de recusar a linha e a politica — que se avalia antes das FK —
#: e nao um valor nulo.
_UM_CANAL = (
    "COALESCE((SELECT id FROM platform.tenant_channels WHERE tenant_id = %s "
    "ORDER BY phone_number_id LIMIT 1), gen_random_uuid())"
)


def _conversa(cursor, tenant_id: str, canario: str) -> None:
    """Uma conversa do tenant (KAM-014). O canario vai no `id`.

    A janela nasce aberta — `last_inbound_at` e `window_expires_at` juntos,
    porque o `conversations_janela_ck` exige os dois ou nenhum — e e isso que
    deixa a `window_expires_at` ser a coluna alteravel: o teste de escrita
    cruzada po-la em 2099, que continua depois do inicio.

    Semeia o administrador da instancia, como nas receitas de identidade e de
    eventos: o `INSERT` do `kamba_app` esta sob `WITH CHECK` e esta receita nao
    define contexto.
    """
    cursor.execute(
        "INSERT INTO platform.conversations "
        "(id, tenant_id, contact_id, channel_id, last_inbound_at, window_expires_at) "
        f"VALUES (%s, %s, {_UM_CONTACTO}, {_UM_CANAL}, now(), now() + interval '24 hours')",
        (_uuid(canario), tenant_id, tenant_id, tenant_id),
    )


#: A conversa do tenant, para a FK composta da mensagem de saida. Mesma forma do
#: `_UM_CONTACTO` e do `_UM_CANAL`, e pela mesma razao: quando a receita e usada
#: para **atacar**, a subconsulta nao ve a conversa do outro tenant, e o que tem
#: de recusar a linha e a politica — que se avalia antes das FK — e nao um valor
#: nulo.
_UMA_CONVERSA = (
    "COALESCE((SELECT id FROM platform.conversations WHERE tenant_id = %s "
    "ORDER BY id LIMIT 1), gen_random_uuid())"
)


def _envio(cursor, tenant_id: str, canario: str) -> None:
    """Uma mensagem de saida do tenant (KAM-015). O canario vai na chave.

    O canario vai na `idempotency_key` e nao no `id`: a `id` e um `uuid` e a
    chave e `text`, pelo que o canario cabe la **tal e qual**, sem passar por
    `_uuid`. E e a coluna certa — a unicidade e `(tenant_id, idempotency_key)`,
    logo dois tenants podem semear o mesmo canario, que e exactamente o que o
    X-03 precisa para provar que cada um so ve o seu.

    `kind` fica em `service`, que e o unico valor que dispensa `template_name`
    (`outbound_messages_template_ck`), e o estado fica na omissao (`queued`) —
    sem `delivered_at` nem `error_code`, que as outras duas coerencias proibem
    fora dos seus estados.

    Semeia o administrador da instancia, como a receita da conversa: o `INSERT`
    do `kamba_app` esta sob `WITH CHECK` e esta receita nao define contexto.
    """
    cursor.execute(
        "INSERT INTO platform.outbound_messages "
        "(tenant_id, channel_id, contact_id, conversation_id, "
        " idempotency_key, kind) "
        f"VALUES (%s, {_UM_CANAL}, {_UM_CONTACTO}, {_UMA_CONVERSA}, %s, 'service')",
        (tenant_id, tenant_id, tenant_id, tenant_id, canario),
    )


def _template(cursor, tenant_id: str, canario: str) -> None:
    """Um template do tenant (KAM-015). O canario vai no `name`.

    O `name` e parte da chave primaria `(tenant_id, name, lang)` e e `text`:
    o canario cabe la tal e qual. Dois tenants podem ter um template com o
    mesmo nome — e e isso que o X-03 precisa.

    A `category` fica em `utility`, que e a do conjunto padrao do Piloto, e o
    `status` na omissao (`pending`). O `body_hash` e obrigatorio e aqui e um
    resumo do canario: nao e o corpo, e de proposito — o texto aprovado nao vive
    nesta tabela.
    """
    cursor.execute(
        "INSERT INTO platform.message_templates "
        "(tenant_id, name, lang, category, body_hash) "
        "VALUES (%s, %s, 'pt_PT', 'utility', %s)",
        (tenant_id, canario, _resumo(canario + ":corpo")),
    )


def _handoff(cursor, tenant_id: str, canario: str) -> None:
    """Uma passagem a humano do tenant (KAM-019). O canario vai no `motivo`.

    **E no `motivo` e nao no `handoff_id`, e a razao e uma propriedade da
    tabela.** A chave primaria e o `handoff_id` derivado de
    `(thread_id, ordinal)` e **nao** leva `tenant_id`, logo e unica em toda a
    base: dois tenants nao podem semear a mesma cadeia la. E o X-03 precisa
    exactamente disso — semeia o **mesmo** canario nos dois tenants e exige que
    cada um veja so o seu.

    A primeira versao desta receita punha o canario no `handoff_id` com o
    `tenant_id` concatenado para nao colidir, e o X-03 recusou-a com razao: a
    consulta que procura o canario por valor deixava de o encontrar **nem no
    proprio tenant**, porque o que estava guardado nao era o canario. Guardar
    uma coisa diferente da que se procura e nao testar nada.

    O `motivo` e a unica coluna de texto livre desta tabela, e a `handoffs_motivo_ck`
    exige-a nao vazia — um canario serve-a. O `handoff_id` passa a derivar do
    `tenant_id`, que e o que a chave global obriga, e o `status` fica na omissao
    (`waiting`), sem `resumed_at` nem `resolver`: e o estado em que uma passagem
    nasce.

    Semeia o administrador da instancia, como a receita da conversa e a do
    envio: o `INSERT` do `kamba_app` esta sob `WITH CHECK` e esta receita nao
    define contexto.
    """
    cursor.execute(
        "INSERT INTO platform.handoffs "
        "(handoff_id, tenant_id, conversation_id, motivo) "
        f"VALUES (md5(%s || %s), %s, {_UMA_CONVERSA}, %s)",
        (canario, tenant_id, tenant_id, tenant_id, canario),
    )


def _conta_de_handoff(cursor, tenant_id: str, canario: str) -> None:
    """A conta de atendimento do tenant (KAM-019). O canario vai no `token_ref`.

    **Nao ha coluna de texto livre onde o canario caiba melhor**, e a escolha
    diz algo sobre a tabela: o `provedor` e de lista fechada, os tres
    identificadores sao `bigint`, e o `token_ref` e a unica coluna `text` que
    aceita uma cadeia arbitraria — e aceita-a sem mentir sobre o que guarda,
    porque e **referencia opaca** a um segredo e nao o segredo.

    Os **quatro** identificadores do provedor derivam do `tenant_id` para nao
    colidirem na `handoff_accounts_conta_uq` nem na
    `handoff_accounts_utilizador_uq`, que sao as unicidades que impedem a mesma
    conta — e o mesmo utilizador — em dois tenants — e que este X-03 nao pode violar por acidente,
    senao o que falha e a semeadura e nao a politica.
    """
    cursor.execute(
        "INSERT INTO platform.handoff_accounts "
        "(tenant_id, provedor, account_id, inbox_id, bot_id, "
        " provider_user_id, token_ref, user_token_ref) "
        "VALUES (%s, 'chatwoot', "
        "        ('x' || substr(md5(%s), 1, 8))::bit(32)::bigint, "
        "        ('x' || substr(md5(%s || ':inbox'), 1, 8))::bit(32)::bigint, "
        "        ('x' || substr(md5(%s || ':bot'), 1, 8))::bit(32)::bigint, "
        "        ('x' || substr(md5(%s || ':user'), 1, 8))::bit(32)::bigint, "
        "        %s, 'ref/do-utilizador')",
        (tenant_id, tenant_id, tenant_id, tenant_id, tenant_id, canario),
    )


def _transicao_de_qualidade(cursor, tenant_id: str, canario: str) -> None:
    """Uma transicao de qualidade do canal do tenant (KAM-021).

    O canario vai no `event_key`, e a escolha segue a do `_midia`: a
    `channel_quality_log_event_key_uq` e `(tenant_id, event_key)` e **leva o
    tenant**, pelo que os dois tenants podem semear o **mesmo** canario sem
    colidir — que e exactamente o que o X-03 precisa, porque semeia o mesmo
    valor nos dois e exige que cada um veja so o seu. Ao contrario da
    `handoffs`, cuja chave primaria e global e obrigou a receita a derivar o
    identificador do `tenant_id`.

    **Nao ha coluna alteravel, e e um privilegio e nao uma escolha.** A `0014`
    da a `kamba_app` `SELECT` e `INSERT` e mais nada: uma linha deste registo e
    o facto de a Meta ter dito uma coisa a uma hora, e um facto nao se corrige.
    E a mesma forma da `handoff_accounts` e da `events_outbox`, e o que se prova
    nessas tabelas e mais forte do que a politica — prova-se que o privilegio
    **nem existe**.

    O `valor_anterior` fica nulo de proposito: e o caso real da **primeira**
    linha de um canal, onde nao havia valor anterior, e e o unico valor que o
    `channel_quality_log_valor_anterior_ck` aceita para alem de texto nao vazio.

    Semeia o administrador da instancia, como a receita da conversa, a da
    passagem e a da midia.
    """
    cursor.execute(
        "INSERT INTO platform.channel_quality_log "
        "(tenant_id, channel_id, evento, valor_anterior, valor_novo, event_key) "
        f"VALUES (%s, {_UM_CANAL}, 'phone_number_quality_update', "
        "        NULL, 'GREEN', %s)",
        (tenant_id, tenant_id, canario),
    )


def _midia(cursor, tenant_id: str, canario: str) -> None:
    """Um objecto de midia do tenant (KAM-020). O canario vai no `media_id`.

    **E no `media_id` e nao no `wamid`, e a escolha diz algo sobre a tabela.**
    As duas sao `text` livre e as duas tem `CHECK` de nao-vazio, pelo que as
    duas serviam; o que decide e a `media_assets_origem_uq`, que e
    `(tenant_id, wamid, media_id)` e **leva o tenant**. Ao contrario da
    `handoffs`, cuja chave primaria e global e obrigou a receita a derivar o
    `handoff_id` do `tenant_id`, aqui os dois tenants podem semear o **mesmo**
    canario sem colidir — que e exactamente o que o X-03 precisa: semeia o mesmo
    valor nos dois e exige que cada um veja so o seu.

    O `asset_id` fica na omissao (`gen_random_uuid()`), e o `estado` nasce em
    `pendente`, que e o estado em que uma linha desta tabela nasce de verdade:
    antes da descarga. As quatro colunas que a descarga descobre
    (`content_type`, `size`, `sha256`, `storage_ref`) ficam nulas, e e por isso
    que a `media_assets_armazenado_ck` nao morde — ela so exige quando o estado
    e `armazenado`.

**Nao ha coluna alteravel**, e a razao e uma restricao e nao uma escolha.
    O que o `kamba_app` faz de verdade e um `UPDATE` que escreve
    `estado='armazenado'` **com** `storage_ref`, `size` e `sha256` na mesma
    instrucao, porque a `media_assets_armazenado_ck` nao deixa de outra maneira.
    Um `SET estado='armazenado'` sozinho sobre esta linha semeada — que tem as
    quatro colunas nulas — da `23514`.

    A primeira versao declarava o `estado` como alteravel com o valor
    `armazenado`, e **nao rebentava por sorte de forma**: o teste da escrita
    cruzada nao casa linha nenhuma (a RLS), pelo que o `CHECK` nunca era
    avaliado, e o da escrita propria faz `SET estado = estado`. Qualquer teste
    futuro que aplicasse o valor a linha do proprio tenant recebia uma violacao
    de `CHECK` onde esperava uma contagem. Encontrado pela revisao adversarial.

    Semeia o administrador da instancia, como a receita da conversa e a da
    passagem.
    """
    cursor.execute(
        "INSERT INTO platform.media_assets "
        "(tenant_id, contact_id, conversation_id, wamid, media_id, classe, estado) "
        f"VALUES (%s, {_UM_CONTACTO}, {_UMA_CONVERSA}, "
        "        'wamid.semente.' || substr(md5(%s), 1, 12), %s, "
        "        'media_audio', 'pendente')",
        (tenant_id, tenant_id, tenant_id, tenant_id, canario),
    )


def _identidade(inserir, coluna, alteravel, valor, guardado) -> Receita:
    return Receita(
        inserir, coluna, alteravel, valor,
        papel="identity", semeador="admin", guardado=guardado,
    )


# As duas receitas de eventos (KAM-005). O canario vai no `agregado_id`, que e
# `text` e e a unica coluna destas tabelas que aceita uma cadeia arbitraria sem
# mentir sobre o que guarda: as outras sao identificadores, tempos, contadores e
# o `envelope`.
#
# Semeia o **administrador da instancia**, e nao o `kamba_batch`: ele nao tem
# `INSERT` no `events_outbox` (o produtor e a aplicacao, sob `WITH CHECK`), e as
# receitas nao definem contexto de tenant. No `events_log` tem `INSERT`, mas
# semear as duas com o mesmo papel poupa uma ligacao e uma pergunta.
#
# O `envelope` e um envelope v1 minimo e **coerente com a linha**: o
# `tenant_id`, o `agregado` e o `seq` dentro dele sao os mesmos das colunas. Um
# envelope com outro `tenant_id` era um canario falso — o teste procura o
# identificador de B no texto de tudo o que A le, e encontrava-o na linha de A.

_ENVELOPE = (
    "jsonb_build_object("
    "'id', gen_random_uuid(), 'tipo', 'order.created', 'versao', 1, "
    "'tenant_id', %s::uuid, 'ocorrido_em', now(), 'registado_em', now(), "
    "'produtor', 'sementes@0', "
    "'agregado', jsonb_build_object('tipo', 'order', 'id', %s::text, 'seq', 1), "
    "'correlacao_id', NULL, 'causa_id', NULL, 'trace_id', NULL, "
    "'classe_pii', 'P1', 'finalidades', to_jsonb(ARRAY['transacao']), "
    "'payload', jsonb_build_object('order_id', %s::text))"
)


def _evento_no_outbox(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.events_outbox "
        "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
        " agregado_seq, particao, envelope) "
        "VALUES (gen_random_uuid(), 'order.created', 1, %s::uuid, 'order', %s::text, 1, 0, "
        f"{_ENVELOPE})",
        (tenant_id, canario, tenant_id, canario, canario),
    )


def _contador_do_agregado(cursor, tenant_id: str, canario: str) -> None:
    """O contador de `seq`. O canario vai no `agregado_id`.

    O `seq` nasce a 1, como o `evt_emitir` o poe. A tabela ganhou `tenant_id`
    com o KAM-005 — desvio ao DDL do documento, registado — e por isso entra na
    descoberta do X-05 como as outras.
    """
    cursor.execute(
        "INSERT INTO platform.evt_agregado_seq "
        "(tenant_id, agregado_tipo, agregado_id, seq) VALUES (%s, 'order', %s, 1)",
        (tenant_id, canario),
    )


def _evento_no_arquivo(cursor, tenant_id: str, canario: str) -> None:
    cursor.execute(
        "INSERT INTO platform.events_log "
        "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
        " agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
        "VALUES (gen_random_uuid(), 'order.created', 1, %s::uuid, 'order', %s::text, 1, "
        f"now(), now(), 'P1', {_ENVELOPE})",
        (tenant_id, canario, tenant_id, canario, canario),
    )


# As tres receitas do consumo (KAM-006). Semeia o administrador da instancia,
# pela mesma razao das de eventos: `kamba_app` escreve-as sob `WITH CHECK` e as
# receitas nao definem contexto de tenant.


def _consumo(cursor, tenant_id: str, canario: str) -> None:
    """Uma linha da janela de deduplicacao. O canario vai no `agregado_id`."""
    cursor.execute(
        "INSERT INTO platform.events_consumed "
        "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq) "
        "VALUES ('ensaio-iso', gen_random_uuid(), %s::uuid, 'order', %s::text, 1)",
        (tenant_id, canario),
    )


def _entrada_na_dlq(cursor, tenant_id: str, canario: str) -> None:
    """Uma entrada aberta da DLQ. O canario vai no `agregado_id` do envelope...

    ...e tambem na coluna `erro`, que e a unica de texto arbitrario desta
    tabela. O envelope e coerente com a linha, como nas receitas de eventos: um
    envelope com outro `tenant_id` era um canario falso.
    """
    cursor.execute(
        "INSERT INTO platform.events_dlq "
        "(consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas) "
        "VALUES ('ensaio-iso', gen_random_uuid(), 'order.created', 1, %s::uuid, "
        f"{_ENVELOPE}, %s::text, 6)",
        (tenant_id, tenant_id, canario, canario, canario),
    )


def _accao_externa(cursor, tenant_id: str, canario: str) -> None:
    """Uma accao externa registada. O canario vai na `accao`."""
    cursor.execute(
        "INSERT INTO platform.evt_acoes "
        "(idempotency_key, consumer, event_id, accao, tenant_id) "
        "VALUES (%s, 'ensaio-iso', gen_random_uuid(), %s, %s::uuid)",
        (f"ensaio-iso:{canario}", canario, tenant_id),
    )


def _uso(cursor, tenant_id: str, canario: str) -> None:
    """Uma linha do contador de uso (KAM-009). O canario vai na `chave_limite`.

    O `canario()` deste modulo devolve `canario_<rotulo>_<hex>`, que e
    exactamente a forma que o `tenant_usage_chave_limite_ck` exige
    (`^[a-z][a-z0-9_]*$`): nao ha coluna de texto livre nesta tabela, e esta e
    a unica que aceita um valor unico por tenant.

    O `periodo` vem da `platform.ten_periodo()` e nao de um literal: a coluna
    tem `CHECK (periodo = date_trunc('month', periodo)::date)`, e uma data a
    meio do mes escrita a mao fazia a semente falhar por uma razao que nada
    tem a ver com isolamento.
    """
    cursor.execute(
        "INSERT INTO platform.tenant_usage "
        "(tenant_id, chave_limite, periodo, valor) "
        "VALUES (%s::uuid, %s, platform.ten_periodo(), 0)",
        (tenant_id, canario),
    )


def _livro_de_uso(cursor, tenant_id: str, canario: str) -> None:
    """Uma entrada do livro de idempotencia (KAM-009), com o canario na chave.

    A `chave_limite` fica numa chave do registo (`msgs_ai_mes`) e nao no
    canario: o canario desta tabela e a `idempotency_key`, que e a coluna que
    o oraculo procura, e manter a chave de limite realista mantem a linha
    coerente com o que a `ten_consumir` escreveria.
    """
    cursor.execute(
        "INSERT INTO platform.usage_ledger "
        "(tenant_id, idempotency_key, chave_limite, periodo, quantidade) "
        "VALUES (%s::uuid, %s, 'msgs_ai_mes', platform.ten_periodo(), 1)",
        (tenant_id, canario),
    )


#: (schema, tabela) -> receita. A ordem de insercao respeita as FK.
RECEITAS: dict[tuple[str, str], Receita] = {
    ("platform", "tenants"): Receita(_tenant, "nome", "nome", "Nome alterado"),
    ("platform", "tenant_channels"): Receita(_canal, "waba_id", "estado", "ativo"),
    # Desde a revisao 0007 (KAM-009) `kamba_app` **nao altera** entitlements:
    # a revisao revogou-lhe o `UPDATE (limites, ativo)`, porque com a politica
    # `id = app.tenant_id` a linha que um contexto de tenant ve e a dele, e
    # subir os proprios limites era subir o tecto de dinheiro por pedido.
    #
    # **E depois da revisao adversarial nem insere**: o `INSERT` da `0001`
    # ficara de pe, e com `WITH CHECK (tenant_id = app.tenant_id)` um tenant
    # criava a propria linha com o tecto que quisesse — a mesma escalada por
    # outro verbo. Por isso `coluna_alteravel=None` **e**
    # `escrita_do_papel=False`: o que se prova nesta tabela passou a ser que
    # os privilegios nem existem, que e mais forte do que a politica recusar
    # — nao depende de a politica estar certa. Quem escreve e o `kamba_batch`.
    ("platform", "entitlements"): Receita(
        _entitlement, "modulo", None, None, escrita_do_papel=False
    ),
    ("platform", "contacts"): _identidade(
        _contacto, "phone_hmac", "hmac_kid", KID_DE_SEMENTE, _resumo
    ),
    ("platform", "contact_deks"): _identidade(
        _dek, "kek_id", "kek_id", "kek-alterada", _texto
    ),
    ("platform", "contact_endpoints"): _identidade(
        _endpoint, "bsuid_enc", "expira_at", "2099-01-01T00:00:00+00:00", _octetos
    ),
    # KAM-014. A primeira tabela isolada sem coluna de texto livre: o canario
    # vai na chave primaria (ver `_uuid`). O papel que a le e escreve e o
    # `kamba_app` — e o CHR —, e a coluna que ele pode alterar e a
    # `window_expires_at`: o `UPDATE` da revisao `0009` e por coluna e nao
    # inclui o `mode`, que e de KAM-018.
    ("platform", "conversations"): Receita(
        _conversa, "id", "window_expires_at", "2099-01-01T00:00:00+00:00",
        semeador="admin", guardado=_uuid,
    ),
    # KAM-005. O produtor (`kamba_app`) insere no outbox sob `WITH CHECK` e le as
    # suas linhas; nao altera nenhuma coluna, e e por isso que a alteravel e
    # `None`. O arquivo e imutavel e so o `kamba_batch` lhe escreve: a politica
    # protege a leitura do produtor, e a escrita esta protegida pela falta de
    # privilegio (`escrita_do_papel=False`).
    # KAM-015. O canario vai na `idempotency_key`, que e `text` e parte da
    # unicidade por tenant — dois tenants podem semear o mesmo canario, que e o
    # que o X-03 precisa. O papel que a le e escreve e o `kamba_app` (e o
    # adapter), e a coluna que ele pode alterar e o `state`: o `UPDATE` da
    # revisao `0010` e por coluna e nao inclui a chave nem o `kind`.
    #
    # O valor alteravel e `failed` e nao `sent`, e isso nao e indiferente: um
    # `delivered` ou um `read` pediam `delivered_at`, e um `failed` nao pede
    # `error_code` (a coerencia e so num sentido — o codigo exige o estado, nao
    # o contrario).
    ("platform", "outbound_messages"): Receita(
        _envio, "idempotency_key", "state", "failed", semeador="admin",
    ),
    # KAM-015. O canario vai no `name`, parte da chave primaria. O `kamba_app`
    # **le e nao insere** — quem submete templates e o onboarding (KAM-091) —,
    # e por isso `escrita_do_papel=False`: o que protege a escrita e a falta de
    # privilegio, e nao a politica, que e mais forte. A coluna alteravel e o
    # `status`, que e uma das seis que o `UPDATE` por coluna da revisao `0010`
    # concede, porque os webhooks de template escrevem-na.
    ("platform", "message_templates"): Receita(
        _template, "name", "status", "approved",
        semeador="admin", escrita_do_papel=False,
    ),
    # KAM-019. As duas do handoff. Na passagem, a coluna alteravel e o
    # `status`, que e uma das quatro que o `UPDATE` por coluna da revisao `0011`
    # concede — e e a que o ciclo de vida muda. Na conta, e o `token_ref`, que
    # muda na rotacao do segredo; e **a mesma coluna onde vai o canario**, o que
    # aqui nao e problema: o teste de escrita cruzada escreve um valor novo e o
    # que se afirma e que a escrita **nao acontece** na linha do outro tenant.
    ("platform", "handoffs"): Receita(
        _handoff, "motivo", "status", "cancelled", semeador="admin",
    ),
    ("platform", "handoff_accounts"): Receita(
        # **Sem coluna alteravel**, como a `events_outbox`: a `0011` deixou de
        # conceder `UPDATE` em `handoff_accounts` a `kamba_app`, porque o unico
        # caminho que o justificava (a reposicao do `01` §11.5) nao existe.
        _conta_de_handoff, "token_ref", None, None, semeador="admin",
    ),
    # KAM-020. O canario vai no `media_id` (ver `_midia`): a
    # `media_assets_origem_uq` leva o `tenant_id`, pelo que os dois tenants
    # podem semear o mesmo valor — ao contrario da `handoffs`, cuja chave
    # primaria e global. **Sem coluna alteravel**, e a razao e uma restricao e
    # nao uma escolha: ver a nota do `_midia`.
    ("platform", "media_assets"): Receita(
        _midia, "media_id", None, None, semeador="admin",
    ),
    # KAM-021. O canario vai no `event_key`, pela razao do `_midia`: a
    # `channel_quality_log_event_key_uq` leva o `tenant_id`, pelo que os dois
    # tenants podem semear o mesmo valor. **Sem coluna alteravel**, e aqui e um
    # privilegio e nao uma restricao: a `0014` nao concede `UPDATE` a
    # `kamba_app` — um registo de transicoes nao se corrige.
    ("platform", "channel_quality_log"): Receita(
        _transicao_de_qualidade, "event_key", None, None, semeador="admin",
    ),
    ("platform", "events_outbox"): Receita(
        _evento_no_outbox, "agregado_id", None, None, semeador="admin"
    ),
    # O contador e a unica tabela de eventos que `kamba_app` **altera** (so a
    # coluna `seq`, pelo `ON CONFLICT` do `evt_emitir`), e por isso e a unica em
    # que a coluna alteravel nao e `None`.
    ("platform", "evt_agregado_seq"): Receita(
        _contador_do_agregado, "agregado_id", "seq", 7, semeador="admin"
    ),
    ("platform", "events_log"): Receita(
        _evento_no_arquivo, "agregado_id", None, None,
        semeador="admin", escrita_do_papel=False,
    ),
    # KAM-006. `kamba_app` insere e le as suas linhas da janela de
    # deduplicacao, e nao altera nenhuma: apagar ou mexer numa linha daqui era
    # permitir que o efeito se repetisse, e isso e da retencao (`kamba_batch`).
    ("platform", "events_consumed"): Receita(
        _consumo, "agregado_id", None, None, semeador="admin"
    ),
    # A DLQ e o unico sitio onde `kamba_app` **escreve sem ler**: o `id` e
    # sequencial e um papel com RLS que o lesse media o volume de falhas do
    # vizinho. Por isso `leitura_do_papel=False` — e **`escrita_do_papel`
    # fica a `True`**, que e a omissao: a revisao 0005 da `INSERT` a
    # `kamba_app` nesta tabela, e a politica e a ultima barreira nessa escrita.
    #
    # Esteve `False`, e isso tirava a tabela de **todos** os testes de escrita
    # cruzada ao mesmo tempo que o comentario afirmava que o X-04 os corria.
    # Duas dimensoes independentes — ler e escrever — tratadas como uma.
    ("platform", "events_dlq"): Receita(
        _entrada_na_dlq, "erro", None, None,
        semeador="admin", leitura_do_papel=False,
    ),
    # As accoes externas: `kamba_app` regista e fecha a sua (o `UPDATE` e por
    # coluna, e o `estado` e uma delas).
    ("platform", "evt_acoes"): Receita(
        _accao_externa, "accao", "estado", "falhada", semeador="admin"
    ),
    # KAM-009. O contador e a unica das duas que `kamba_app` **altera**, e so
    # em duas colunas (`valor`, `actualizado_at`): e o que a `ten_consumir`
    # precisa para o `ON CONFLICT DO UPDATE`. Semeia-se com `kamba_batch`, que
    # tem as quatro operacoes nas duas tabelas desde a revisao 0007.
    ("platform", "tenant_usage"): Receita(_uso, "chave_limite", "valor", 42),
    # O livro **nao se altera**: `kamba_app` tem `SELECT` e `INSERT` e mais
    # nada, e e isso que torna a chave de idempotencia uma marca e nao um
    # estado. Por isso `coluna_alteravel=None` — o X-04 prova, nesta tabela,
    # que o privilegio de `UPDATE` nem existe, que e mais forte do que provar
    # que a politica o recusava.
    ("platform", "usage_ledger"): Receita(
        _livro_de_uso, "idempotency_key", None, None
    ),
}

#: As duas tabelas da auditoria **nao** entram nas receitas, e nenhuma das
#: razoes e esquecimento (KAM-012).
#:
#: `audit_heads` tem `tenant_id` e nao tem RLS — a unica tabela do schema nessa
#: situacao, declarada em `ci/rls_exceptions.yaml` com o ADR que a funda. Numa
#: tabela sem politica nao ha politica que provar.
#:
#: `audit_log` tem RLS, mas e **append-only**: um trigger `ENABLE ALWAYS`
#: recusa `DELETE`, e estas receitas semeiam e apagam. Semea-la aqui obrigava
#: a desligar o trigger na limpeza — que e exactamente o defeito que a revisao
#: adversarial deste ticket apanhou noutro sitio: DDL confirmado numa limpeza
#: repara o esquema na base viva e esconde regressoes de tudo o que corre a
#: seguir. O isolamento desta tabela prova-se em
#: `db/tests/test_auditoria.py::TestIsolamento`, que faz as mesmas perguntas
#: do X-04 (escrever no tenant de outro, escrever a cadeia de plataforma) sem
#: precisar de apagar nada.
SEM_RECEITA_COM_RAZAO = {("platform", "audit_heads"), ("platform", "audit_log")}

#: `tenants` primeiro: as outras referenciam-na. Depois, pela ordem das FK. As
#: de eventos nao tem FK para nada (o `agregado_id` e uma referencia logica, por
#: desenho: o agregado vive no Medusa ou noutro schema) e ficam no fim.
ORDEM = (
    ("platform", "tenants"),
    ("platform", "tenant_channels"),
    ("platform", "entitlements"),
    ("platform", "contacts"),
    ("platform", "contact_deks"),
    ("platform", "contact_endpoints"),
    # KAM-014: depende de `contacts` e de `tenant_channels`, e vem depois das
    # duas. Na ordem inversa, apaga-se antes delas.
    ("platform", "conversations"),
    # KAM-015: a mensagem de saida depende de `conversations`, de `contacts` e
    # de `tenant_channels`, e vem depois das tres. Na ordem inversa, apaga-se
    # antes delas. O template so depende de `tenants`.
    ("platform", "outbound_messages"),
    ("platform", "message_templates"),
    # KAM-019: a passagem depende de `conversations` e vem depois dela. Na ordem
    # inversa, apaga-se antes. A conta de atendimento so depende de `tenants`.
    ("platform", "handoffs"),
    ("platform", "handoff_accounts"),
    ("platform", "events_outbox"),
    ("platform", "evt_agregado_seq"),
    ("platform", "events_log"),
    ("platform", "events_consumed"),
    ("platform", "events_dlq"),
    ("platform", "evt_acoes"),
    # KAM-020: **a ultima das que tem FK**, e tem tres (`tenants`, `contacts` e
    # `conversations`). Vem depois da conversa e do contacto, que e o que as
    # duas FK compostas exigem; e vem antes das duas do KAM-009, que nao
    # dependem de nada senao do tenant.
    ("platform", "media_assets"),
    # KAM-021: tem duas FK (`tenants` e a composta para `tenant_channels`), e o
    # canal e semeado pelo proprio `ComDoisTenants` antes de qualquer receita —
    # logo basta vir depois do tenant. Fica aqui, a seguir a midia, porque a
    # ordem inversa e a de apagar e esta tabela nao e apontada por nenhuma.
    ("platform", "channel_quality_log"),
    # KAM-009: as duas so tem FK para `tenants`, e por isso ficam no fim.
    ("platform", "tenant_usage"),
    ("platform", "usage_ledger"),
)

#: As identidades com que as receitas semeiam.
SEMEADORES = tuple(sorted({receita.semeador for receita in RECEITAS.values()}))

#: As identidades com que as tabelas se leem em producao.
PAPEIS = tuple(sorted({receita.papel for receita in RECEITAS.values()}))


def canario(rotulo: str) -> str:
    """Cadeia unica, em minusculas e snake_case (cabe em `entitlements.modulo`)."""
    return f"canario_{rotulo}_{uuid.uuid4().hex}"


@dataclasses.dataclass(frozen=True)
class Tenant:
    id: str
    #: (schema, tabela) -> canario dessa tabela.
    canarios: dict[tuple[str, str], str]

    def guardado(self, chave: tuple[str, str]) -> object:
        """O canario da tabela, na forma em que esta na coluna."""
        return RECEITAS[chave].guardado(self.canarios[chave])


def registar_versao_de_chave(cursor) -> None:
    """A versao de chave que as sementes de identidade referem. Como administrador."""
    cursor.execute(
        "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES (%s, 'retirada') "
        "ON CONFLICT (kid) DO NOTHING",
        (KID_DE_SEMENTE,),
    )


def retirar_versao_de_chave(cursor) -> None:
    cursor.execute(
        "DELETE FROM platform.hmac_key_versions WHERE kid = %s", (KID_DE_SEMENTE,)
    )


def semear_tenant(cursores: dict, rotulo: str) -> Tenant:
    """Um tenant com uma linha — e um canario proprio — em cada tabela isolada.

    `cursores` da um cursor por semeador (`SEMEADORES`), todos de papeis que
    contornam a RLS: as receitas nao definem contexto.
    """
    identificador = str(uuid.uuid4())
    canarios: dict[tuple[str, str], str] = {}
    for chave in ORDEM:
        receita = RECEITAS[chave]
        canarios[chave] = canario(rotulo)
        receita.inserir(cursores[receita.semeador], identificador, canarios[chave])
    return Tenant(identificador, canarios)


def apagar_tenant(cursores: dict, tenant_id: str) -> None:
    """Pela ordem inversa das FK, cada tabela com quem a semeou."""
    for schema, tabela in reversed(ORDEM):
        coluna = "id" if tabela == "tenants" else "tenant_id"
        cursores[RECEITAS[(schema, tabela)].semeador].execute(
            f"DELETE FROM {schema}.{tabela} WHERE {coluna} = %s", (tenant_id,)
        )
