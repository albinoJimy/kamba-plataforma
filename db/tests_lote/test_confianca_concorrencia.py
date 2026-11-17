"""A concorrencia no limite do tecto de confianca, contra o PostgreSQL (KAM-096).

A cobranca e a escrita do nivel tomam a mesma tranca consultiva da transaccao,
chaveada pelo tenant: a cobranca em modo partilhado (o *trigger*
`payment_charges_dentro_do_tecto`), a escrita em exclusivo (o
`trust_level_guardar`). O que se mede, com duas ligacoes reais:

```text
a descida primeiro    as cobrancas esperam; depois do commit da descida o limite e
                      o tecto novo: o exacto entra, um centimo acima nao
a cobranca primeiro   a descida espera; a cobranca fica, e a seguinte ja nao cabe
vinte no limite       vinte cobrancas de exactamente o tecto entram, vinte de
                      tecto + 1 centimo nao
o controlo            com a tranca retirada da funcao, a cobranca **nao** espera
                      e passa com o tecto velho enquanto a descida esta a meio —
                      que e o que prova que a tranca e o que faz a diferenca
```

A escrita do nivel e o `SQL_DEFINIR_NIVEL` do modulo de TypeScript, executado tal
como esta escrito, e corre como `kamba_batch`; a cobranca corre como `kamba_app`,
com o contexto do tenant.

**Porque e nesta suite.** Medir a corrida pede *commit*, e um *commit* da
escrita do nivel deixa uma linha `trust.tecto` no `audit_log` *append-only* — o
que tira a descida a qualquer suite com ensaios de `downgrade` (`tests`,
`tests_pagamentos`, `tests_encomendas`). A `tests_lote` nao tem nenhum.
"""

from __future__ import annotations

import datetime
import threading
import uuid
from pathlib import Path

import ligacao
from tests import factories
from tests.base import ComBase, ConsultaDoTypeScript, sqlstate
from tests.test_kyc_schema import caso as novo_caso
from tests.test_kyc_schema import verificacao

SQL_TS = Path(__file__).resolve().parents[2] / "packages" / "core-ts" / "src" / "confianca" / "sql.ts"
VERSAO = factories.VERSAO_DA_CONFIGURACAO_DE_ENSAIO
NIVEL_UM = 15_000_000
NIVEL_ZERO = 5_000_000
#: Entre os dois tectos: cabe no nivel 1 e nao no 0.
NO_MEIO = 6_000_000
#: Quanto se espera para dizer que uma ligacao esta parada na tranca.
ESPERA = 1.5


def _definir(cursor, tenant: str, nivel: int, tecto: int, motivo: str) -> int:
    q = ConsultaDoTypeScript("SQL_DEFINIR_NIVEL", SQL_TS)
    cursor.execute(q.sql, q.args(tenant, nivel, str(tecto), motivo, f"sistema:{VERSAO}", VERSAO))
    return len(cursor.fetchall())


class Ligacao:
    """Uma ligacao com papel e contexto, numa transaccao que se fecha a mao."""

    def __init__(self, identidade: str, tenant: str | None = None) -> None:
        self.conexao = ligacao.ligar(identidade)
        self.cursor = self.conexao.cursor()
        if tenant is not None:
            self.cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            self.cursor.fetchone()

    def fechar(self) -> None:
        try:
            self.conexao.rollback()
        finally:
            self.conexao.close()


class EmFundo(threading.Thread):
    """Corre `fn` numa thread e guarda o resultado ou o SQLSTATE do erro."""

    def __init__(self, fn) -> None:
        super().__init__(daemon=True)
        self.fn = fn
        self.resultado: object = None
        self.erro: str | None = None

    def run(self) -> None:
        try:
            self.resultado = self.fn()
        except Exception as e:  # noqa: BLE001 — o ensaio le o SQLSTATE
            self.erro = sqlstate(e) or repr(e)


class TestConcorrenciaNoLimiteDoTecto(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        self.addCleanup(self._admin.close)
        self.tenant = factories.tenant(self.semente)
        caso, _ = novo_caso(self.semente, tenant_id=self.tenant, fase="activo")
        verificacao(self.semente, caso, self.tenant, resultado="k1_ok")
        self.contacto = factories.contacto(self.semente, self.tenant)
        self.conta = str(uuid.uuid4())
        self.semente.execute(
            "INSERT INTO platform.payment_accounts (id, beneficiary_kind, tenant_id, provider, "
            "entidade, estado, webhook_token) VALUES (%s, 'pme', %s, 'fakeprovider', '00123', 'ativo', %s)",
            (self.conta, self.tenant, uuid.uuid4().hex),
        )
        # O nivel nasce e sobe pelo caminho do modulo, como `kamba_batch`.
        lote = Ligacao("batch")
        self.assertEqual(_definir(lote.cursor, self.tenant, 0, NIVEL_ZERO, "k1_completo"), 1)
        self.assertEqual(_definir(lote.cursor, self.tenant, 1, NIVEL_UM, "historico_independente"), 1)
        lote.conexao.commit()
        lote.conexao.close()

    def encomenda(self, total: int) -> str:
        self.semente.execute(
            "INSERT INTO platform.orders_mirror (tenant_id, contact_id, intent_key, total_minor, "
            "lines_snapshot) VALUES (%s, %s, %s, %s, '[]'::jsonb) RETURNING id",
            (self.tenant, self.contacto, f"ik-{uuid.uuid4().hex[:16]}", total),
        )
        return str(self.semente.fetchone()[0])

    def cobrar(self, cursor, valor: int, encomenda: str | None = None) -> int:
        """Uma cobranca de encomenda. A encomenda semeia-se **antes** de uma thread:
        a ligacao da semente nao e partilhavel entre threads."""
        encomenda = self.encomenda(valor) if encomenda is None else encomenda
        cursor.execute(
            "INSERT INTO platform.payment_charges (id, tenant_id, account_id, order_id, provider, "
            "metodo, referencia, amount_minor, valid_until) "
            "VALUES (%s, %s, %s, %s, 'fakeprovider', 'referencia', %s, %s, %s)",
            (
                str(uuid.uuid4()), self.tenant, self.conta, encomenda,
                f"REF{uuid.uuid4().hex[:12]}", valor,
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
            ),
        )
        return cursor.rowcount

    def tecto(self) -> int:
        self.semente.execute("SELECT tecto_pedido_minor FROM platform.trust_level WHERE tenant_id = %s",
                             (self.tenant,))
        return int(self.semente.fetchone()[0])

    # ------------------------------------------------------------- as corridas

    def test_a_descida_primeiro_as_cobrancas_esperam_e_o_limite_e_o_novo(self) -> None:
        """No limite do tecto **novo**: o tecto exacto entra, um centimo acima nao.

        Tres cobrancas param na tranca enquanto a descida esta a meio — o tecto
        novo exacto, o tecto novo mais um centimo, e uma entre os dois tectos —, e
        so se decidem depois do *commit* dela, com o tecto que ela gravou.
        """
        lote = Ligacao("batch")
        apps = [Ligacao("app", self.tenant) for _ in range(3)]
        try:
            self.assertEqual(_definir(lote.cursor, self.tenant, 0, NIVEL_ZERO, "sancao"), 1)
            valores = (NIVEL_ZERO, NIVEL_ZERO + 1, NO_MEIO)
            pedidos = [self.encomenda(v) for v in valores]
            cobrancas = [
                EmFundo(lambda c=c, v=v, p=p: self.cobrar(c.cursor, v, p))
                for c, v, p in zip(apps, valores, pedidos)
            ]
            for c in cobrancas:
                c.start()
            for c in cobrancas:
                c.join(ESPERA)
            self.assertTrue(all(c.is_alive() for c in cobrancas), "uma cobranca nao esperou pela descida")
            lote.conexao.commit()
            for c in cobrancas:
                c.join(30)
            self.assertEqual(
                [(c.erro, c.resultado) for c in cobrancas],
                [(None, 1), ("23514", None), ("23514", None)],
                "com a descida confirmada, o limite e o do nivel 0, e o exacto entra",
            )
        finally:
            for a in apps:
                a.fechar()
            lote.fechar()

    def test_a_cobranca_primeiro_a_descida_espera_e_a_seguinte_ja_nao_cabe(self) -> None:
        app = Ligacao("app", self.tenant)
        lote = Ligacao("batch")
        try:
            self.assertEqual(self.cobrar(app.cursor, NO_MEIO), 1)
            descida = EmFundo(lambda: _definir(lote.cursor, self.tenant, 0, NIVEL_ZERO, "sancao"))
            descida.start()
            descida.join(ESPERA)
            self.assertTrue(descida.is_alive(), "a descida nao esperou pela cobranca em curso")
            app.conexao.commit()
            descida.join(30)
            self.assertEqual((descida.erro, descida.resultado), (None, 1))
            lote.conexao.commit()
            self.assertEqual(self.tecto(), NIVEL_ZERO)
            depois = Ligacao("app", self.tenant)
            try:
                with self.assertRaises(Exception) as recusa:
                    self.cobrar(depois.cursor, NO_MEIO)
                self.assertEqual(sqlstate(recusa.exception), "23514")
            finally:
                depois.fechar()
        finally:
            app.fechar()
            lote.fechar()

    def test_vinte_no_limite_entram_e_vinte_um_centimo_acima_nao(self) -> None:
        """A fronteira sob carga paralela, **sem** escritor do nivel a correr.

        Nao mede a tranca — cada cobranca e independente, e passaria sem ela; o
        que a mede e a corrida acima e o controlo. Mede que quarenta ligacoes ao
        mesmo tempo nao mudam o veredicto de nenhuma.
        """
        def uma(valor: int):
            pedido = self.encomenda(valor)

            def correr() -> int:
                c = Ligacao("app", self.tenant)
                try:
                    n = self.cobrar(c.cursor, valor, pedido)
                    c.conexao.commit()
                    return n
                finally:
                    c.fechar()
            return correr

        trabalhos = [EmFundo(uma(NIVEL_UM)) for _ in range(20)] + [EmFundo(uma(NIVEL_UM + 1)) for _ in range(20)]
        for t in trabalhos:
            t.start()
        for t in trabalhos:
            t.join(60)
        self.assertEqual([(t.erro, t.resultado) for t in trabalhos[:20]], [(None, 1)] * 20)
        self.assertEqual([t.erro for t in trabalhos[20:]], ["23514"] * 20)

    def test_controlo_sem_a_tranca_a_cobranca_passa_com_o_tecto_velho(self) -> None:
        """Sem a tranca partilhada, a mesma corrida da a resposta errada.

        Retira-se a linha da tranca da funcao do *trigger* (`CREATE OR REPLACE`
        com o corpo lido do catalogo), corre-se a corrida da descida, e repoe-se
        a funcao no fim, corra bem ou mal.
        """
        self.semente.execute(
            "SELECT pg_get_functiondef('platform.payment_charge_dentro_do_tecto()'::regprocedure)"
        )
        original = self.semente.fetchone()[0]
        tranca = (
            "PERFORM pg_advisory_xact_lock_shared(\n"
            "            hashtextextended('platform.trust_level:' || NEW.tenant_id::text, 0));"
        )
        self.assertIn(tranca, original, "a funcao ja nao tem a tranca que este controlo retira")
        self.semente.execute(original.replace(tranca, "NULL;"))
        try:
            lote = Ligacao("batch")
            app = Ligacao("app", self.tenant)
            try:
                self.assertEqual(_definir(lote.cursor, self.tenant, 0, NIVEL_ZERO, "sancao"), 1)
                pedido = self.encomenda(NO_MEIO)
                cobranca = EmFundo(lambda: self.cobrar(app.cursor, NO_MEIO, pedido))
                cobranca.start()
                cobranca.join(ESPERA * 4)
                self.assertFalse(cobranca.is_alive(), "sem a tranca, a cobranca nao tinha por que esperar")
                self.assertEqual((cobranca.erro, cobranca.resultado), (None, 1))
                lote.conexao.commit()
                app.conexao.commit()
                self.assertEqual(self.tecto(), NIVEL_ZERO)
            finally:
                app.fechar()
                lote.fechar()
        finally:
            self.semente.execute(original)
