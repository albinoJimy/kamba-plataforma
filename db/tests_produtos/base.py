"""Base da suite do preco opaco: tenants e ofertas semeadas e confirmadas.

O que esta suite prova e a **revisao `0028`** (KAM-043) — o
`offer_terms_preco_ck` do criterio 1, a RLS `FORCE` do criterio 7, a chave
composta `(tenant_id, sku)` que resolve a colisao de SKU entre tenants, a FK
**composta** do contacto de `price_quotes`, a auditoria e os eventos — e as
consultas do modulo `services/com/src/produtos/consultas.ts`, lidas de la.

**Nao prova** o `precoDisplay`, a validade do preco nem a semantica do
`stock_modo`: isso e funcao pura e mede-se em
`services/com/tests/produtos.formato.test.ts`, sem base de dados. Medir aqui o
que nao precisa de PostgreSQL era pagar o preco de uma suite por uma asercao que
corre em microssegundos.

## Porque e que as sementes sao confirmadas

Pela razao do `db/tests_servicos/base.py` e do `db/tests_ten/base.py`: uma
ligacao nao ve o que outra ainda nao confirmou. Os testes de isolamento correm
como `kamba_app` numa ligacao propria, e uma oferta semeada dentro de uma
transaccao aberta era **invisivel** para ela — com a suite verde e nada provado,
que e a forma mais caro de um teste passar.

Por isso as sementes vao por uma ligacao de administrador em `autocommit`, e
cada teste apaga o que semeou.

## Suite propria, e nao dentro de `tests`

Pela razao do `tests_servicos` e do `tests_ten`: uma suite custa relogio por cada
mutacao que a escolha, e o `tests` ja carrega o inventario, os privilegios e a
cadeia de auditoria. O que e **do catalogo fechado** — as colunas das duas
tabelas novas e a resposta a «guarda dados pessoais?» — fica onde o trinco esta,
em `db/tests/test_inventario.py`, e nao aqui.
"""

from __future__ import annotations

import datetime
import json
import uuid

import ligacao
from tests import factories
from tests.base import ComBase

#: O SKU que **existe nos dois tenants**, e e o ISO-33..38: a colisao de SKU
#: entre tenants nao e um problema porque a chave e `(tenant_id, sku)`.
SKU_PARTILHADO = "arroz-5kg"

#: 12 500 Kz em unidade menor. 1 Kz = 100 centimos (criterio 1).
PRECO = 1_250_000


class ComOfertas(ComBase):
    """Um tenant com ofertas, semeadas e confirmadas."""

    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        self._tenants: list[str] = []
        self._app: dict[str, object] = {}
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        try:
            for tenant in self._tenants:
                # Pela ordem inversa das FK. Nenhuma apaga em cascata, de
                # proposito — ver o `test_as_fk_nao_apagam_em_cascata`.
                for tabela in (
                    "price_quotes",
                    "offer_terms",
                    "events_outbox",
                    "contacts",
                ):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                        (tenant,),
                    )
                # **O `audit_log` nao se apaga, e e por desenho.** A revisao
                # `0006` poe-lhe um *trigger* `BEFORE UPDATE OR DELETE` que
                # recusa as duas — e tambem um `FOR EACH STATEMENT`, para o
                # `DELETE` sem linhas. Um registo append-only que o teste
                # conseguisse apagar nao era append-only, e a primeira versao
                # desta limpeza tentava, com oito erros a prova-lo.
                #
                # Nao acumula lixo que conte: cada teste cria o seu tenant e
                # todas as leituras filtram por ele, e a base do *gate* 8 e
                # descartavel. A `audit_log.tenant_id` **nao** tem FK para
                # `tenants` (o §6 do `docs/tecnica/08` deixa-a anulavel para a
                # cadeia de plataforma), pelo que apagar o tenant a seguir
                # funciona com as linhas dele ainda la — que e a ordem certa: o
                # rasto de quem mudou um preco sobrevive ao tenant.
                #
                # O `audit_heads` tambem nao: quem lhe escreve e o *trigger*
                # `audit_encadear`, e e a unica tabela do esquema na dispensa de
                # `ci/rls_exceptions.yaml`. A cabeca que fica e a do tenant
                # apagado, e nenhum tenant novo a herda — a chave e por tenant.
                _ = tenant
                self.semente.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            # **So a de administrador.** As de `self._app` vem do `ComBase.ligar`,
            # que as registra e as fecha no `tearDown` — e os `addCleanup` correm
            # **depois** dele, pelo que fecha-las aqui levantava
            # `InterfaceError: connection is closed`. E a mesma licao que o
            # `tests_servicos/base.py` escreveu, medida em 23 erros.
            self._admin.close()

    # --------------------------------------------------------------- sementes

    def criar_tenant(self) -> str:
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        return tenant

    def criar_contacto(self, tenant: str) -> str:
        return factories.contacto(self.semente, tenant)

    def criar_oferta(
        self,
        tenant: str,
        *,
        sku: str = SKU_PARTILHADO,
        nome: str | None = None,
        preco_tipo: str = "fixo",
        preco_minor: int | None = PRECO,
        stock_modo: str = "garantido",
        estado: str = "publicado",
        categoria_restrita: str | None = None,
        preco_valido_ate: object = None,
        stock_verificado_at: object = None,
        deleted_at: object = None,
    ) -> str:
        """Insere uma oferta e devolve o `sku`. Confirmada, por `autocommit`.

        O `deleted_at` entrou com o KAM-051: o criterio 2 da `v_oferta_viva`
        exige que um produto **apagado** nao chegue ao indice, e o *soft delete*
        do secao 5.6 e a unica das tres condicoes do `publicado` que nao se
        alcanca pelos outros parametros.
        """
        self.semente.execute(
            "INSERT INTO platform.offer_terms "
            "(tenant_id, sku, nome, preco_tipo, preco_minor, stock_modo, estado, "
            " categoria_restrita, preco_valido_ate, stock_verificado_at, deleted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                tenant,
                sku,
                nome if nome is not None else f"produto {sku}",
                preco_tipo,
                preco_minor,
                stock_modo,
                estado,
                categoria_restrita,
                preco_valido_ate,
                stock_verificado_at,
                deleted_at,
            ),
        )
        return sku

    def criar_cotacao(
        self,
        tenant: str,
        contacto: str,
        *,
        sku: str = SKU_PARTILHADO,
        qty: int = 10,
        preco_total_minor: int = PRECO * 10,
        valida_ate: object = None,
        estado: str = "emitida",
    ) -> str:
        prazo = valida_ate if valida_ate is not None else daqui_a(horas=24)
        self.semente.execute(
            "INSERT INTO platform.price_quotes "
            "(tenant_id, contact_id, sku, qty, preco_total_minor, valida_ate, "
            " estado, emitida_por) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                tenant,
                contacto,
                sku,
                qty,
                preco_total_minor,
                prazo,
                estado,
                str(uuid.uuid4()),
            ),
        )
        return str(self.semente.fetchone()[0])

    # ---------------------------------------------------------------- ligacao

    def cursor_app(self, tenant: str | None, *, papel: str = "app"):
        """Cursor do papel pedido com o contexto dado (ou sem nenhum).

        `kamba_app` e `NOBYPASSRLS`: e com ele que o modulo corre em producao, e
        **so com ele** e que um teste de isolamento quer dizer alguma coisa. Com
        o administrador a politica nao se aplica e o teste nao prova nada.

        A transaccao fica **aberta**, porque o `assertErroSql` precisa de um
        `SAVEPOINT`.
        """
        chave = f"{papel}:{tenant or ''}"
        conexao = self._app.get(chave)
        if conexao is None:
            conexao = self.ligar(papel)
            self._app[chave] = conexao
        cursor = conexao.cursor()  # type: ignore[attr-defined]
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
        cursor.fetchone()
        return cursor

    # --------------------------------------------------------------- leituras

    def ofertas(self, tenant: str) -> list[tuple]:
        """`(sku, preco_tipo, preco_minor, estado)`, lidas pelo administrador."""
        self.semente.execute(
            "SELECT sku, preco_tipo, preco_minor, estado FROM platform.offer_terms "
            " WHERE tenant_id = %s ORDER BY sku",
            (tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def auditoria(self, tenant: str) -> list[tuple]:
        """`(actor_type, actor_id, action, entity, entity_id)` pela ordem da cadeia."""
        self.semente.execute(
            "SELECT actor_type, actor_id, action, entity, entity_id "
            "  FROM platform.audit_log WHERE tenant_id = %s ORDER BY id",
            (tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def hashes_de_auditoria(self, tenant: str) -> list[bytes]:
        self.semente.execute(
            "SELECT payload_hash FROM platform.audit_log "
            " WHERE tenant_id = %s ORDER BY id",
            (tenant,),
        )
        return [bytes(linha[0]) for linha in self.semente.fetchall()]

    def eventos(self, tenant: str, tipo: str) -> list[dict]:
        """Os envelopes de um tipo no outbox deste tenant, pela ordem da sequencia."""
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox "
            " WHERE tenant_id = %s AND tipo = %s ORDER BY agregado_seq, event_id",
            (tenant, tipo),
        )
        return [
            linha[0] if isinstance(linha[0], dict) else json.loads(linha[0])
            for linha in self.semente.fetchall()
        ]

    def tipos_emitidos(self, tenant: str) -> list[str]:
        self.semente.execute(
            "SELECT tipo FROM platform.events_outbox WHERE tenant_id = %s "
            " ORDER BY agregado_seq, event_id",
            (tenant,),
        )
        return [str(linha[0]) for linha in self.semente.fetchall()]


def daqui_a(*, horas: int = 0, minutos: int = 0):
    """Um instante futuro com fuso.

    Com fuso porque o `timestamptz` sem fuso herda o `TimeZone` da sessao — e
    duas sessoes com `TimeZone` diferente escreviam instantes diferentes para o
    mesmo texto. E a mesma licao do `tests_servicos/base.py`.
    """
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        hours=horas, minutes=minutos
    )
