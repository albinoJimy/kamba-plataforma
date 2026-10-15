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
    #: Coluna que o papel da tabela pode alterar (para os testes de escrita cruzada).
    coluna_alteravel: str
    #: Um valor valido para essa coluna.
    valor_alteravel: object
    #: Identidade (de `ligacao.PAPEIS`) que le e escreve a tabela em producao.
    papel: str = "app"
    #: Identidade que semeia e apaga. `kamba_batch` onde ele tem privilegios; o
    #: administrador da instancia nas tabelas de identidade, onde nao tem.
    semeador: str = "batch"
    #: Como o canario fica guardado na coluna (texto, octetos ou resumo).
    guardado: Callable[[str], object] = _texto


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


#: (schema, tabela) -> receita. A ordem de insercao respeita as FK.
RECEITAS: dict[tuple[str, str], Receita] = {
    ("platform", "tenants"): Receita(_tenant, "nome", "nome", "Nome alterado"),
    ("platform", "tenant_channels"): Receita(_canal, "waba_id", "estado", "ativo"),
    ("platform", "entitlements"): Receita(_entitlement, "modulo", "ativo", False),
    ("platform", "contacts"): _identidade(
        _contacto, "phone_hmac", "hmac_kid", KID_DE_SEMENTE, _resumo
    ),
    ("platform", "contact_deks"): _identidade(
        _dek, "kek_id", "kek_id", "kek-alterada", _texto
    ),
    ("platform", "contact_endpoints"): _identidade(
        _endpoint, "bsuid_enc", "expira_at", "2099-01-01T00:00:00+00:00", _octetos
    ),
}

#: `tenants` primeiro: as outras referenciam-na. Depois, pela ordem das FK.
ORDEM = (
    ("platform", "tenants"),
    ("platform", "tenant_channels"),
    ("platform", "entitlements"),
    ("platform", "contacts"),
    ("platform", "contact_deks"),
    ("platform", "contact_endpoints"),
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
