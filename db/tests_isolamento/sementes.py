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
    # subir os proprios limites era subir o tecto de dinheiro por pedido. Por
    # isso `coluna_alteravel=None`: o que se prova nesta tabela passou a ser
    # que o privilegio **nem existe** — mais forte do que a politica recusar.
    ("platform", "entitlements"): Receita(_entitlement, "modulo", None, None),
    ("platform", "contacts"): _identidade(
        _contacto, "phone_hmac", "hmac_kid", KID_DE_SEMENTE, _resumo
    ),
    ("platform", "contact_deks"): _identidade(
        _dek, "kek_id", "kek_id", "kek-alterada", _texto
    ),
    ("platform", "contact_endpoints"): _identidade(
        _endpoint, "bsuid_enc", "expira_at", "2099-01-01T00:00:00+00:00", _octetos
    ),
    # KAM-005. O produtor (`kamba_app`) insere no outbox sob `WITH CHECK` e le as
    # suas linhas; nao altera nenhuma coluna, e e por isso que a alteravel e
    # `None`. O arquivo e imutavel e so o `kamba_batch` lhe escreve: a politica
    # protege a leitura do produtor, e a escrita esta protegida pela falta de
    # privilegio (`escrita_do_papel=False`).
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
    ("platform", "events_outbox"),
    ("platform", "evt_agregado_seq"),
    ("platform", "events_log"),
    ("platform", "events_consumed"),
    ("platform", "events_dlq"),
    ("platform", "evt_acoes"),
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
