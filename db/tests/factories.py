"""Fabricas de tenants e canais para testes. Sem dados reais.

O ticket KAM-003 pede-as em `tests/factories`; vivem em `db/tests/` porque a
convencao deste repositorio (KAM-001) e testes por pacote, e nao existe um
`tests/` na raiz. O desvio esta registado no bloco do KAM-003.

Todos os valores sao gerados e obviamente sinteticos: nenhum NIF, nome, WABA ou
`phone_number_id` aqui corresponde a uma entidade real, e nada disto e um
telefone. O `token_ref` e uma referencia opaca, como o KAM-010 o define — nunca
um token.

**Cada fabrica define o contexto de tenant antes de inserir** (KAM-004). Com a
RLS `FORCE`, um `INSERT` so passa o `WITH CHECK` se `app.tenant_id` for o tenant
da linha; para `tenants`, isso significa pre-alocar o `id`, definir o contexto e
so depois inserir — que e a sequencia que o onboarding real segue (dicionario
§3.2, «pre-alocacao do tenant»). Depois de uma fabrica correr, o contexto da
transaccao e o do tenant dessa linha.
"""

from __future__ import annotations

import uuid


def _sufixo() -> str:
    return uuid.uuid4().hex[:12]


def contexto(cursor, tenant_id: str | None) -> None:
    """Define `app.tenant_id` para o resto da transaccao (equivale a `SET LOCAL`).

    `None` limpa-o: a cadeia vazia e o que a variavel vale depois de um
    `SET LOCAL` expirar, e a politica trata-a como ausencia de contexto.
    """
    cursor.execute(
        "SELECT set_config('app.tenant_id', %s, true)", (tenant_id or "",)
    )
    cursor.fetchone()


def _inserir(cursor, tabela: str, valores: dict, devolver: str | None = None):
    colunas = ", ".join(valores)
    marcadores = ", ".join(["%s"] * len(valores))
    sql = f"INSERT INTO platform.{tabela} ({colunas}) VALUES ({marcadores})"
    if devolver:
        sql += f" RETURNING {devolver}"
    cursor.execute(sql, tuple(valores.values()))
    return str(cursor.fetchone()[0]) if devolver else None


def tenant(cursor, **campos) -> str:
    """Insere um tenant e devolve o `id`. Deixa o contexto nesse tenant."""
    valores = {
        "id": str(uuid.uuid4()),
        "tipo": "pme",
        "nome": f"Loja de teste {_sufixo()}",
    }
    valores.update(campos)
    contexto(cursor, valores["id"])
    return _inserir(cursor, "tenants", valores, devolver="id")


def canal(cursor, tenant_id: str, **campos) -> str:
    """Insere um canal para o tenant e devolve o `id`. Deixa o contexto no tenant."""
    sufixo = _sufixo()
    valores = {
        "tenant_id": tenant_id,
        "waba_id": f"waba-teste-{sufixo}",
        "phone_number_id": f"pnid-teste-{sufixo}",
        "channel_mode": "coexistencia",
        "vertical": "vendedor",
        "token_ref": f"ref-opaca-de-teste/{sufixo}",
    }
    valores.update(campos)
    contexto(cursor, tenant_id)
    return _inserir(cursor, "tenant_channels", valores, devolver="id")


def entitlement(cursor, tenant_id: str, modulo: str = "catalogo", **campos) -> None:
    valores = {"tenant_id": tenant_id, "modulo": modulo}
    valores.update(campos)
    contexto(cursor, tenant_id)
    _inserir(cursor, "entitlements", valores)


# --------------------------------------------------------------------- KAM-008
# Identidade de contacto. Nada disto e um BSUID nem um telefone: os `bytea` sao
# octetos aleatorios com o comprimento certo, e a «cifra» e ruido. Quem prova a
# cifra verdadeira e a suite `tests_identidade`, que usa o modulo real.
#
# Estas fabricas **nao definem contexto**: as tabelas de identidade nao sao
# escritas por `kamba_app`, e quem as usa escolhe o papel (o administrador da
# instancia nos testes de restricoes; `kamba_identity`, com contexto, nos de
# isolamento).

#: Versao de chave que as fabricas registam. `retirada`: nao ocupa o lugar da
#: `actual` nem da `anterior`, de que so pode haver uma.
KID_DE_TESTE = "kid-de-teste"


def versao_de_chave(cursor, kid: str = KID_DE_TESTE, estado: str = "retirada") -> str:
    cursor.execute(
        "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES (%s, %s) "
        "ON CONFLICT (kid) DO NOTHING",
        (kid, estado),
    )
    return kid


def contacto(cursor, tenant_id: str, **campos) -> str:
    """Insere um contacto e devolve o `contact_id`."""
    valores = {"tenant_id": tenant_id}
    valores.update(campos)
    return _inserir(cursor, "contacts", valores, devolver="contact_id")


def dek(cursor, tenant_id: str, contact_id: str, **campos) -> str:
    """Insere uma DEK embrulhada (ruido) e devolve o `dek_id`."""
    valores = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "wrapped_dek": uuid.uuid4().bytes * 3,
        "kek_id": "kek-de-teste",
    }
    valores.update(campos)
    return _inserir(cursor, "contact_deks", valores, devolver="dek_id")


def endpoint_bsuid(cursor, tenant_id: str, contact_id: str, dek_id: str, **campos) -> str:
    """Insere um endpoint de BSUID e devolve o `id`. Regista a versao de chave."""
    valores = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "dek_id": dek_id,
        "tipo": "bsuid",
        "bsuid_hmac": uuid.uuid4().bytes * 2,
        "hmac_kid": KID_DE_TESTE,
        "bsuid_enc": uuid.uuid4().bytes * 4,
    }
    valores.update(campos)
    if valores.get("hmac_kid") == KID_DE_TESTE:
        versao_de_chave(cursor)
    return _inserir(cursor, "contact_endpoints", valores, devolver="id")


def endpoint_telefone(cursor, tenant_id: str, contact_id: str, dek_id: str, **campos) -> str:
    """Insere um endpoint de telefone (cifra de ruido) e devolve o `id`."""
    valores = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "dek_id": dek_id,
        "tipo": "telefone",
        "phone_enc": uuid.uuid4().bytes * 4,
        "finalidade": "entrega",
        "expira_at": "2099-01-01T00:00:00+00:00",
    }
    valores.update(campos)
    return _inserir(cursor, "contact_endpoints", valores, devolver="id")
