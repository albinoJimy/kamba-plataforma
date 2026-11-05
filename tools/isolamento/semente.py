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
    # **Sem coluna de canario**: o `sku` e partilhado por X e Y (ver
    # `SKU_PARTILHADO`) e por isso nao distingue as linhas. O que as
    # distingue e o `id`, em `Contacto.ids`.
    ("platform", "price_quotes"): "id",
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


#: O modulo da vertical com que o X-02 invoca a ToolLayer. Tem de ser o `id` de
#: uma vertical do REG: a camada le o entitlement por ele (KAM-009, KAM-028).
MODULO_DA_VERTICAL = "vendedor"


def activar_tenant(cursor: Any, tenant_id: str) -> None:
    """Poe o tenant em `ativo`, para o X-02 chegar ao executor.

    **A segunda razao pela qual o X-02 nao media nada**, e a primeira execucao
    tambem a mostrou. A receita de `tenants` da suite da base insere `(id, tipo,
    nome)` e o `estado` fica no `DEFAULT 'onboarding'`; o `SQL_ENTITLEMENT` do
    TEN escreve, por SQL, que o estado do tenant tem de ser diferente de
    `onboarding`, `suspenso` e `encerrado`. Com o tenant em `onboarding`, **toda**
    a invocacao devolvia `ENTITLEMENT_DENIED` antes de chegar ao executor — e
    «zero canarios de B» era verde porque nenhuma tool respondia a ninguem.

    Nao ha reposicao: o tenant e desta classe de ensaio e o `apagar_tenant` da
    suite da base apaga-o inteiro no fim.
    """
    cursor.execute(
        "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant_id,)
    )


def semear_entitlement(cursor: Any, tenant_id: str) -> None:
    """Liga o modulo da vertical no tenant, para o X-02 chegar ao executor.

    **Sem isto, o X-02 nao mede o que diz medir**, e o primeiro ensaio
    mostrou-o: a receita de `entitlements` da suite da base poe o **canario** na
    coluna `modulo` — tem de o por, e a coluna onde ele cabe —, pelo que o
    tenant semeado nao tem nenhum modulo *real* activo. O passo 2 do pipeline
    de `invoke` recusa com `ENTITLEMENT_DENIED` antes de chegar ao executor, e
    entao «zero canarios de B» era verde porque **nenhuma** tool respondia a
    ninguem — a forma mais pura de passar pela razao errada.

    `ON CONFLICT DO NOTHING`: o tenant pode ja ter esta linha se alguem
    acrescentar a receita mais tarde, e duas execucoes da suite na mesma base
    nao se podem pisar.
    """
    cursor.execute(
        "INSERT INTO platform.entitlements (tenant_id, modulo, ativo) "
        "VALUES (%s, %s, true) ON CONFLICT (tenant_id, modulo) DO NOTHING",
        (tenant_id, MODULO_DA_VERTICAL),
    )


def retirar_entitlement(cursor: Any, tenant_id: str) -> None:
    cursor.execute(
        "DELETE FROM platform.entitlements WHERE tenant_id = %s AND modulo = %s",
        (tenant_id, MODULO_DA_VERTICAL),
    )


def _criar_contacto(cursor: Any, tenant_id: str, rotulo: str) -> str:
    """Um contacto novo no tenant, e devolve o `contact_id`."""
    marca = canario(rotulo)
    cursor.execute(
        "INSERT INTO platform.contacts (tenant_id, phone_hmac, hmac_kid) "
        "VALUES (%s, %s, %s) RETURNING contact_id::text",
        (tenant_id, hashlib.sha256(marca.encode("ascii")).digest(), KID_DE_SEMENTE),
    )
    return str(cursor.fetchone()[0])


def _encomenda(cursor: Any, tenant_id: str, contact_id: str, marca: str) -> str:
    """A encomenda do contacto, **com o recibo de intencao concluido**.

    O recibo nao e zelo: a leitura por contacto do repositorio
    (`SQL_PEDIDO_POR_PAGAR`) faz `JOIN platform.order_intents i ON m.id =
    i.order_id` com `i.estado = 'concluida'`, pelo que uma encomenda sem recibo
    ligado nao e lida por ninguem — e o `C-01/consultas` ficava verde sobre uma
    leitura que devolve `null` aos **dois** contactos. Medido na terceira
    execucao do *gate*.

    Devolve o `id` da encomenda: a projeccao daquela consulta nao inclui o
    `intent_key` (que e onde o canario cabe), pelo que o que o caso compara
    naquela leitura e o **identificador da linha**. Ver
    `COLUNA_DO_CANARIO` e `Contacto.ids`.
    """
    cursor.execute(
        "INSERT INTO platform.orders_mirror "
        "(tenant_id, contact_id, intent_key, total_minor, lines_snapshot) "
        "VALUES (%s, %s, %s, 0, '[]'::jsonb) RETURNING id::text",
        (tenant_id, contact_id, marca),
    )
    order_id = str(cursor.fetchone()[0])
    cursor.execute(
        "INSERT INTO platform.order_intents "
        "(tenant_id, intent_key, draft_hash, estado, order_id) "
        "VALUES (%s, %s, sha256(convert_to(%s, 'UTF8')), 'concluida', %s)",
        (tenant_id, marca, marca, order_id),
    )
    return order_id


#: O `(sku, qty)` que X **e** Y partilham nas cotacoes, e a razao pela qual ele
#: tem de ser o mesmo nos dois.
#:
#: O criterio 6 descreve o cenario: «o contacto X ... nao le ... `price_quotes`
#: de Y». Para um contacto ler a cotacao do outro, os dois tem de ter cotacao
#: para o **mesmo** `(sku, qty)` — e a `SQL_COTACAO_VALIDA` filtra por `sku` e
#: `qty` e mais nada. Com `sku` distinto por contacto, que e o que esta semente
#: fazia, X pedia o seu proprio `sku` e recebia a sua propria linha: o cenario
#: do criterio **nao podia ocorrer**, e a afirmacao «X nao ve Y» era verde por
#: construcao. Achado 8 da revisao adversarial.
#:
#: Com o `sku` partilhado, o canario deixa de poder viver nessa coluna — seria
#: o mesmo nos dois — e o que distingue as duas linhas passa a ser o **`id`**,
#: que aquela consulta projecta. Ver `COLUNA_DO_CANARIO` e `Contacto.ids`.
SKU_PARTILHADO = "canario_c01_sku_partilhado"

#: A quantidade, tambem partilhada: entra no predicado como o `sku`.
QTY_PARTILHADA = 1


def _cotacao(
    cursor: Any, tenant_id: str, contact_id: str, marca: str, ordem: int = 0
) -> str:
    """A cotacao do contacto, com o `(sku, qty)` **partilhado** com o outro.

    O `marca` nao vai para o `sku` (ver `SKU_PARTILHADO`): vai para o
    `emitida_por`? Nao — esse e um UUID. Fica **sem canario de texto**, e e o
    `id` devolvido que identifica a linha. E a unica das tres tabelas onde isso
    acontece, e a razao esta no comentario do `SKU_PARTILHADO`.

    ## O `ordem` existe porque `now()` nao serve para ordenar aqui

    A `SQL_COTACAO_VALIDA` faz `ORDER BY criado_at DESC LIMIT 1`, e o
    `criado_at` tem `DEFAULT now()`. **Em PostgreSQL o `now()` e o instante de
    inicio da transaccao**, nao do comando: as duas cotacoes semeadas na mesma
    transaccao ficam com `criado_at` **igual**, e qual delas aquela consulta
    devolve passa a ser arbitrario — decide o plano, nao o dado.

    Isso torna a fixacao do `C-01/consultas` instavel por construcao: ela afirma
    que a leitura de X devolve a linha de **Y** (a mais recente), e com empate
    nao ha mais recente. O `ordem` desempata com um deslocamento explicito, pelo
    que a linha de Y e inequivocamente a ultima. Sem isto, a mesma arvore podia
    dar verde numa maquina e vermelho noutra — e uma suite de isolamento que
    varia com o plano nao mede isolamento nenhum.
    """
    cursor.execute(
        "INSERT INTO platform.price_quotes "
        "(tenant_id, contact_id, sku, qty, preco_total_minor, valida_ate, "
        " emitida_por, criado_at) "
        "VALUES (%s, %s, %s, %s, 1000, now() + interval '24 hours', %s, "
        "        now() + (%s * interval '1 second')) "
        "RETURNING id::text",
        (tenant_id, contact_id, SKU_PARTILHADO, QTY_PARTILHADA, tenant_id, ordem),
    )
    return str(cursor.fetchone()[0])


def _consentimento(cursor: Any, tenant_id: str, contact_id: str, marca: str) -> str:
    cursor.execute(
        "INSERT INTO platform.consent_event "
        "(tenant_id, contact_id, purpose, text_version, accepted, canal, "
        " evidence_hash) "
        "VALUES (%s, %s, 'transacao', %s, true, 'whatsapp', "
        "        sha256(convert_to(%s, 'UTF8'))) RETURNING id::text",
        (tenant_id, contact_id, marca, marca),
    )
    return str(cursor.fetchone()[0])


#: A chave da tabela que precisa de desempate de ordem (ver `_cotacao`).
_COTACOES = ("platform", "price_quotes")

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
    for indice, rotulo in enumerate(("x", "y")):
        contact_id = _criar_contacto(cursor, tenant_id, rotulo)
        canarios: dict[tuple[str, str], str] = {}
        ids: dict[tuple[str, str], str] = {}
        for chave in TABELAS:
            marca = canario(f"{rotulo}_{chave[1]}")
            canarios[chave] = marca
            # O `ordem` so interessa a `price_quotes`, e porque: a
            # `SQL_COTACAO_VALIDA` ordena por `criado_at DESC` e o `now()` e o
            # mesmo nas duas linhas desta transaccao. Ver `_cotacao`. O `y` leva
            # o indice 1, pelo que e inequivocamente a mais recente.
            extra = {"ordem": indice} if chave == _COTACOES else {}
            ids[chave] = _RECEITAS[chave](
                cursor, tenant_id, contact_id, marca, **extra
            )
        par.append(
            Contacto(
                id=contact_id, tenant_id=tenant_id, canarios=canarios, ids=ids
            )
        )
    return ParDeContactos(x=par[0], y=par[1])


#: Os `consumer` que o registo deriva (`eventos/subscricoes.py`: `"agr_" + id`).
#: Repetidos aqui e nao importados porque este modulo nao importa o AGR; ha um
#: ensaio que os confronta com a enumeracao.
CONSUMIDORES = ("agr_vendedor", "agr_servicos")


def semear_marcas_de_consumo(cursor: Any, tenant_id: str, rotulo: str) -> dict[str, str]:
    """Uma marca de `events_consumed` por consumidor **real**, para este tenant.

    **Sem isto a bateria dos consumidores EVT passava por ausencia**, e a
    revisao adversarial mediu-o: a receita de semente da suite da base escreve
    `consumer = 'ensaio-iso'`, pelo que a pergunta «ha marca de B com
    `consumer = 'agr_vendedor'`?» contava **zero** — com a RLS ligada,
    desligada, ou com a politica apagada. A metade positiva que devia fechar
    isso deixava cair o predicado do `consumer`, e por isso nao o fechava.

    Devolve `{consumer: canario}` — o canario vai no `agregado_id`, que e texto
    e e o que o oraculo procura.
    """
    canarios: dict[str, str] = {}
    for consumer in CONSUMIDORES:
        marca = canario(f"{rotulo}_{consumer}")
        canarios[consumer] = marca
        cursor.execute(
            "INSERT INTO platform.events_consumed "
            "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq) "
            "VALUES (%s, gen_random_uuid(), %s::uuid, 'order', %s::text, 1)",
            (consumer, tenant_id, marca),
        )
    return canarios


def apagar_marcas_de_consumo(cursor: Any, tenant_id: str) -> None:
    cursor.execute(
        "DELETE FROM platform.events_consumed "
        "WHERE tenant_id = %s AND consumer = ANY(%s)",
        (tenant_id, list(CONSUMIDORES)),
    )


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
        # **O recibo primeiro.** A `order_intents` referencia a `orders_mirror`
        # pela FK composta `(tenant_id, order_id)`, e apagar a encomenda antes
        # do recibo dava violacao de FK no fim de **cada** execucao da suite —
        # medido, no `tearDownClass`. A chave do recibo e o mesmo canario da
        # encomenda (`intent_key`), que e como ele se encontra sem o guardar.
        cursor.execute(
            "DELETE FROM platform.order_intents "
            "WHERE tenant_id = %s AND intent_key = %s",
            (contacto.tenant_id, contacto.canarios[("platform", "orders_mirror")]),
        )
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
