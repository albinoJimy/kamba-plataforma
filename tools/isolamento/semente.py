"""O *seed* do eixo do contacto: X e Y, os dois no mesmo tenant.

Criterio 1 do KAM-066: «o *seed* cria os tenants A e B **e os contactos X e Y
(ambos em A)** com um canario unico em cada tabela». O eixo do tenant ja existe
e nao se repete aqui: `db/tests_isolamento/sementes.py` semeia A e B com
canarios em todas as tabelas com `tenant_id` — 45 receitas, do KAM-004 e dos
treze tickets que o alargaram. Este modulo acrescenta **o segundo eixo**, que e
o que o ticket traz de novo.

## Porque e que o eixo do contacto nao e o mesmo problema

O isolamento de tenant e da **base**: a RLS `FORCE` com `app.tenant_id` recusa
sozinha, e um defeito na aplicacao nao chega a produzir leitura cruzada. O
isolamento de contacto nao tem essa rede: X e Y estao no **mesmo** tenant, a
politica `tenant_iso` deixa passar os dois, e o que separa um do outro e o
`WHERE contact_id = …` das funcoes de repositorio. Tirar esse predicado nao
avermelha nenhuma politica — avermelha este caso, ou nao avermelha nada.

E a razao de ser do criterio 6, e a razao pela qual ele se esquece: nada na
camada de baixo o obriga.

## Tres tabelas, e sao as que o criterio nomeia

`orders_mirror` (encomendas), `consent_event` (consentimentos) e `price_quotes`
— as tres com `(tenant_id, contact_id)` e as tres com FK composta ao contacto,
pela correccao de 2026-10-27 do `docs/tecnica/03` §5.4. Cada contacto leva, em
cada uma, uma linha com **o seu** canario: e o que permite perguntar «o que X le
contem o canario de Y?» em vez de «quantas linhas e que X ve», que e uma
pergunta que uma tabela vazia responde certo por acidente.

## Semeia com o administrador da instancia, e nao com `kamba_app`

Pela razao que a `ComDoisTenants` ja escreve: os casos leem noutras ligacoes e
com outros papeis, e nao veriam linhas por confirmar; e nenhum caso desta suite
confirma o que escreve. O administrador contorna a RLS, pelo que as receitas nao
definem contexto.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from typing import Any

from .contexto import Contacto

#: As tres tabelas do criterio 6, com a coluna onde o canario do contacto cabe.
#: A escolha da coluna e a mesma das receitas do eixo do tenant, e pela mesma
#: razao: a coluna tem de ser `text` livre, porque o oraculo procura **texto**.
#:
#:   orders_mirror.intent_key   texto livre, unico por tenant
#:   price_quotes.sku           texto livre, sem `UNIQUE`
#:   consent_event.text_version texto livre com `CHECK` de nao vazio
COLUNA_DO_CANARIO = {
    ("platform", "orders_mirror"): "intent_key",
    ("platform", "price_quotes"): "sku",
    ("platform", "consent_event"): "text_version",
}

TABELAS = tuple(COLUNA_DO_CANARIO)

#: A versao de chave que `db/tests_isolamento/sementes.py` registra. Repetida
#: aqui porque este modulo nao importa essa suite — ele corre antes de ela
#: existir no caminho de importacao, e um `import` circular entre o *harness* e
#: a suite da base era pior do que uma constante com a razao escrita.
KID_DE_SEMENTE = "kid-de-semente"


def canario(rotulo: str) -> str:
    """A forma do canario desta casa: minusculas e `snake_case`.

    **Nao e a forma que os Detalhes Tecnicos do bloco escrevem**
    (`CANARY-{tenant}-{tabela}-{uuid}`), e a razao e de coluna: um canario tem
    de caber em `platform.entitlements.modulo`, que o dicionario §3.2 fixa como
    identificador em minusculas. A forma abaixo e a que o KAM-004 escolheu e a
    que 45 receitas ja produzem; mudar a forma era reescrever as 45 para ganhar
    maiusculas que nenhuma coluna aceita.
    """
    return f"canario_{rotulo}_{uuid.uuid4().hex}"


@dataclasses.dataclass(frozen=True)
class ParDeContactos:
    x: Contacto
    y: Contacto


def _criar_contacto(cursor: Any, tenant_id: str, rotulo: str) -> str:
    """Um contacto novo no tenant, e devolve o `contact_id`."""
    marca = canario(rotulo)
    cursor.execute(
        "INSERT INTO platform.contacts (tenant_id, phone_hmac, hmac_kid) "
        "VALUES (%s, %s, %s) RETURNING contact_id::text",
        (tenant_id, hashlib.sha256(marca.encode("ascii")).digest(), KID_DE_SEMENTE),
    )
    return str(cursor.fetchone()[0])


def _encomenda(cursor: Any, tenant_id: str, contact_id: str, marca: str) -> None:
    cursor.execute(
        "INSERT INTO platform.orders_mirror "
        "(tenant_id, contact_id, intent_key, total_minor, lines_snapshot) "
        "VALUES (%s, %s, %s, 0, '[]'::jsonb)",
        (tenant_id, contact_id, marca),
    )


def _cotacao(cursor: Any, tenant_id: str, contact_id: str, marca: str) -> None:
    cursor.execute(
        "INSERT INTO platform.price_quotes "
        "(tenant_id, contact_id, sku, qty, preco_total_minor, valida_ate, "
        " emitida_por) "
        "VALUES (%s, %s, %s, 1, 1000, now() + interval '24 hours', %s)",
        (tenant_id, contact_id, marca, tenant_id),
    )


def _consentimento(cursor: Any, tenant_id: str, contact_id: str, marca: str) -> None:
    cursor.execute(
        "INSERT INTO platform.consent_event "
        "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
        " evidence_hash) "
        "VALUES (%s, %s, 'transacao', %s, true, 'whatsapp', "
        "        sha256(convert_to(%s, 'UTF8')))",
        (tenant_id, contact_id, marca, marca),
    )


_RECEITAS = {
    ("platform", "orders_mirror"): _encomenda,
    ("platform", "price_quotes"): _cotacao,
    ("platform", "consent_event"): _consentimento,
}


def semear_contactos(cursor: Any, tenant_id: str) -> ParDeContactos:
    """X e Y no mesmo tenant, cada um com o seu canario nas tres tabelas.

    `cursor` e do administrador da instancia, em *autocommit*: as linhas tem de
    ficar confirmadas antes de os casos as lerem noutras ligacoes.
    """
    par = []
    for rotulo in ("x", "y"):
        contact_id = _criar_contacto(cursor, tenant_id, rotulo)
        canarios: dict[tuple[str, str], str] = {}
        for chave in TABELAS:
            marca = canario(f"{rotulo}_{chave[1]}")
            canarios[chave] = marca
            _RECEITAS[chave](cursor, tenant_id, contact_id, marca)
        par.append(
            Contacto(id=contact_id, tenant_id=tenant_id, canarios=canarios)
        )
    return ParDeContactos(x=par[0], y=par[1])


def apagar_contactos(cursor: Any, par: ParDeContactos) -> None:
    """Apaga o que `semear_contactos` escreveu, pela ordem inversa das FK.

    Corre **antes** do `apagar_tenant` da suite da base: as linhas destas tres
    tabelas apontam para contactos que ele apaga, e deixar a ordem ao acaso
    dava uma violacao de FK no fim de cada execucao.

    A `consent_event` e *append-only* para `kamba_app` (a `0015` nao lhe da
    `DELETE`), mas nao para o administrador da instancia — que e quem semeia e
    quem limpa, e e por isso que esta limpeza nao precisa de desligar nada.
    Desligar um *trigger* numa limpeza repara o esquema na base viva e esconde
    regressoes de tudo o que corre a seguir.
    """
    for contacto in (par.y, par.x):
        for chave in reversed(TABELAS):
            cursor.execute(
                f"DELETE FROM {chave[0]}.{chave[1]} "
                "WHERE tenant_id = %s AND contact_id = %s",
                (contacto.tenant_id, contacto.id),
            )
        cursor.execute(
            "DELETE FROM platform.contacts "
            "WHERE tenant_id = %s AND contact_id = %s",
            (contacto.tenant_id, contacto.id),
        )
