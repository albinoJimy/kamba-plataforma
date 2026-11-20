"""A revisao do canal do dono contra a base: papel, owner_actions e definir_dono (KAM-118).

O que so uma base prova, e por isso este ficheiro existe:

1. **O papel nasce `cliente`** e o dominio e fechado; o indice
   `contacts_um_dono` e **parcial** — dois clientes no mesmo tenant passam, um
   dono em cada tenant passa.
2. **A porta `definir_dono`** pelo caminho real: o papel `kamba_identity`, com
   o contexto do tenant. A reentrega do provisionamento e idempotente (3x -> 1
   dono, criterio 3), nao troca um dono existente (`23505`), a troca de
   telefone despromove o anterior e marca o `papel_mudou_at` nos dois
   (criterio 4), e as recusas: sem contexto, contacto de outro tenant ou
   apagado, origem desconhecida. **E duas trocas concorrentes nao deixam dois
   donos** — a unica classe que faz *commit*, e limpa o que escreveu.
3. **O papel so muda pela porta** (criterio 2): nenhum papel tem `UPDATE
   (papel)`, o `kamba_identity` nao insere um contacto ja `dono`, e so ele
   executa a porta.
4. **A ficha da accao sensivel** (criterio 5): RLS forcada, o `UPDATE ...
   RETURNING` da confirmacao corrido duas vezes da uma linha e depois zero
   (duplo toque), nao confirma depois do `expira_at` nem por outro contacto, a
   idempotencia da criacao e a coerencia `confirmada` <-> `confirmada_at`.
5. **O `downgrade`** e o regresso a `head`.

O SQL da confirmacao e o do desenho (`kamba_agr/dono/accoes.py`, por escrever
noutro ramo do mesmo ticket): quando la existir, este ensaio passa a le-lo de
la em vez de o repetir — fica dito para quem ligar as duas pontas.
"""

from __future__ import annotations

import re
import threading
import time
import unittest
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_canal_do_dono.py"))

PARAMETRO_INVALIDO = "22023"
PORTA = "SELECT platform.definir_dono(%s, %s)"

#: A confirmacao do desenho, tal como o portao do AGR a corre: so a ficha
#: pendente, do mesmo contacto, antes do prazo. E o predicado que faz o duplo
#: toque dar uma execucao.
CONFIRMAR = (
    "UPDATE platform.owner_actions SET estado = 'confirmada', confirmada_at = now() "
    "WHERE action_id = %s AND contact_id = %s AND estado = 'pendente' "
    "AND expira_at > now() RETURNING action_id"
)


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def _papel(cursor, papel: str | None, tenant: str | None = None) -> None:
    """Muda de papel **na transaccao** e define o contexto de tenant."""
    cursor.execute("RESET ROLE" if papel is None else f"SET LOCAL ROLE {papel}")
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
    cursor.fetchone()


class ComDono(ComBase):
    """Uma ligacao de administrador que nunca faz `commit`; os papeis por `SET LOCAL ROLE`.

    Os tenants e os contactos nascem pelo administrador (as fabricas), e o
    `papel` nasce na omissao. **Quem o muda e sempre a porta**, chamada como
    `kamba_identity` com o contexto do tenant — que e o caminho de producao.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cur = self.conexao.cursor()

    def definir(self, tenant: str, contacto: str, origem: str = "provisionamento"):
        _papel(self.cur, "kamba_identity", tenant)
        self.cur.execute(PORTA, (contacto, origem))
        devolvido = self.cur.fetchone()[0]
        _papel(self.cur, None)
        return None if devolvido is None else str(devolvido)

    def recusa(self, esperado: str, tenant: str | None, contacto: str,
               origem: str = "provisionamento", papel: str = "kamba_identity") -> None:
        _papel(self.cur, papel, tenant)
        self.assertErroSql(esperado, self.cur, PORTA, (contacto, origem))
        _papel(self.cur, None)

    def estado(self, tenant: str) -> dict[str, tuple]:
        """contacto -> (papel, papel_mudou_at nao nulo?), lido como administrador."""
        self.cur.execute(
            "SELECT contact_id::text, papel, papel_mudou_at IS NOT NULL "
            "FROM platform.contacts WHERE tenant_id = %s",
            (tenant,),
        )
        return {c: (p, m) for c, p, m in self.cur.fetchall()}

    def dono_do_tenant(self, tenant: str) -> str | None:
        self.cur.execute("SELECT owner_contact_id::text FROM platform.tenants WHERE id = %s", (tenant,))
        return self.cur.fetchone()[0]

    def donos(self, tenant: str) -> list[str]:
        return sorted(c for c, (p, _) in self.estado(tenant).items() if p == "dono")


class TestPapel(ComDono):
    """Criterio 2, a forma: nasce `cliente`, dominio fechado, um dono por tenant."""

    def test_o_papel_nasce_cliente_sem_data_de_mudanca(self) -> None:
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        self.assertEqual(self.estado(tenant), {contacto: ("cliente", False)})

    def test_o_check_recusa_um_papel_fora_do_dominio(self) -> None:
        """Uma afirmacao sobre o esquema, e por isso pelo administrador: nenhum
        escritor de producao escreve o `papel` a nao ser a porta."""
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur,
                           "UPDATE platform.contacts SET papel = 'administrador' WHERE contact_id = %s",
                           (contacto,))

    def test_dois_clientes_no_mesmo_tenant_e_um_dono_em_cada_tenant_passam(self) -> None:
        """O indice e parcial: so os `dono` contam, e contam por tenant.

        Os contactos nascem pelo `kamba_identity` com o contexto do tenant, e os
        donos pela porta: sem o `WHERE papel = 'dono'`, o segundo contacto de A
        ja nao nascia; sem o `tenant_id`, o dono de B recusava.
        """
        contactos = {}
        for nome in ("a", "b"):
            tenant = factories.tenant(self.cur)
            _papel(self.cur, "kamba_identity", tenant)
            par = []
            for _ in range(2):
                self.cur.execute(
                    "INSERT INTO platform.contacts (tenant_id) VALUES (%s) RETURNING contact_id::text",
                    (tenant,),
                )
                par.append(self.cur.fetchone()[0])
            _papel(self.cur, None)
            contactos[nome] = (tenant, par)
        for tenant, (dono, _) in contactos.values():
            self.assertIsNone(self.definir(tenant, dono))
        for tenant, (dono, cliente) in contactos.values():
            with self.subTest(tenant=tenant):
                self.assertEqual(self.estado(tenant), {dono: ("dono", False), cliente: ("cliente", False)})


class TestDefinirDono(ComDono):
    """Criterios 3 e 4: a porta, pelo `kamba_identity` com o contexto do tenant."""

    def test_o_provisionamento_tres_vezes_deixa_um_dono_sem_data_de_mudanca(self) -> None:
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        for _ in range(3):
            self.assertIsNone(self.definir(tenant, contacto))
        self.assertEqual(self.estado(tenant), {contacto: ("dono", False)})
        self.assertEqual(self.dono_do_tenant(tenant), contacto)

    def test_o_provisionamento_de_outro_contacto_nao_troca_o_dono(self) -> None:
        tenant = factories.tenant(self.cur)
        dono = factories.contacto(self.cur, tenant)
        outro = factories.contacto(self.cur, tenant)
        self.definir(tenant, dono)
        self.recusa(VIOLACAO_DE_UNICIDADE, tenant, outro)
        self.assertEqual(self.donos(tenant), [dono])
        self.assertEqual(self.dono_do_tenant(tenant), dono)

    def test_a_troca_de_telefone_despromove_o_anterior_e_marca_os_dois(self) -> None:
        tenant = factories.tenant(self.cur)
        antigo = factories.contacto(self.cur, tenant)
        novo = factories.contacto(self.cur, tenant)
        self.definir(tenant, antigo)
        self.assertEqual(self.definir(tenant, novo, "troca_de_telefone"), antigo)
        self.assertEqual(self.estado(tenant), {antigo: ("cliente", True), novo: ("dono", True)})
        self.assertEqual(self.dono_do_tenant(tenant), novo)

    def test_sem_app_tenant_id_a_porta_recusa(self) -> None:
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        self.recusa(PRIVILEGIO_INSUFICIENTE, None, contacto)
        self.assertEqual(self.donos(tenant), [])

    def test_o_contacto_de_outro_tenant_nao_se_encontra(self) -> None:
        a = factories.tenant(self.cur)
        b = factories.tenant(self.cur)
        de_b = factories.contacto(self.cur, b)
        self.recusa(VIOLACAO_DE_FK, a, de_b)
        self.assertEqual(self.donos(a), [])
        self.assertEqual(self.donos(b), [])

    def test_um_contacto_apagado_ou_fundido_nao_e_dono(self) -> None:
        tenant = factories.tenant(self.cur)
        vivo = factories.contacto(self.cur, tenant)
        apagado = factories.contacto(self.cur, tenant, erased_at="2026-01-01")
        fundido = factories.contacto(self.cur, tenant, merged_into=vivo, merged_at="2026-01-01")
        for contacto in (apagado, fundido):
            with self.subTest(contacto=contacto):
                self.recusa(VIOLACAO_DE_FK, tenant, contacto)
        self.assertEqual(self.donos(tenant), [])

    def test_um_dono_apagado_ou_fundido_nao_prende_o_lugar(self) -> None:
        """A lapide do dono passa a `cliente`, e o provisionamento seguinte entra.

        O `#fundir` nao leva o papel para o contacto que fica, e um apagamento
        a pedido do titular deixa a linha. O estado de lapide escreve-se aqui
        como administrador, porque o caminho que o escreve e de outro ticket; o
        `papel` so muda pela porta.
        """
        for coluna in ("erased_at", "merged_into"):
            with self.subTest(lapide=coluna):
                tenant = factories.tenant(self.cur)
                antigo = factories.contacto(self.cur, tenant)
                novo = factories.contacto(self.cur, tenant)
                self.definir(tenant, antigo)
                if coluna == "erased_at":
                    self.cur.execute(
                        "UPDATE platform.contacts SET erased_at = now() "
                        "WHERE tenant_id = %s AND contact_id = %s",
                        (tenant, antigo),
                    )
                else:
                    self.cur.execute(
                        "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
                        "WHERE tenant_id = %s AND contact_id = %s",
                        (novo, tenant, antigo),
                    )
                self.assertEqual(self.definir(tenant, novo), antigo)
                self.assertEqual(self.donos(tenant), [novo])
                self.assertEqual(self.estado(tenant)[antigo], ("cliente", True))
                self.assertEqual(self.dono_do_tenant(tenant), novo)

    def test_uma_origem_desconhecida_e_recusada(self) -> None:
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        for origem in ("texto_do_cliente", "", None):
            with self.subTest(origem=origem):
                self.recusa(PARAMETRO_INVALIDO, tenant, contacto, origem)
        self.assertEqual(self.donos(tenant), [])


class TestSoAPortaMudaOPapel(ComDono):
    """Criterio 2: o papel so muda pela porta, e so o `kamba_identity` a abre."""

    def test_nenhum_papel_de_aplicacao_escreve_o_papel(self) -> None:
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        for papel in ("kamba_app", "kamba_agr", "kamba_identity", "kamba_batch"):
            with self.subTest(papel=papel):
                _papel(self.cur, papel, tenant)
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                                   "UPDATE platform.contacts SET papel = 'dono' WHERE contact_id = %s",
                                   (contacto,))
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                                   "UPDATE platform.contacts SET papel_mudou_at = now() WHERE contact_id = %s",
                                   (contacto,))
                _papel(self.cur, None)
        self.assertEqual(self.estado(tenant), {contacto: ("cliente", False)})

    def test_a_identidade_nao_insere_um_contacto_ja_dono(self) -> None:
        tenant = factories.tenant(self.cur)
        _papel(self.cur, "kamba_identity", tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "INSERT INTO platform.contacts (tenant_id, papel) VALUES (%s, 'dono')",
                           (tenant,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "INSERT INTO platform.contacts (tenant_id, papel_mudou_at) VALUES (%s, now())",
                           (tenant,))
        _papel(self.cur, None)
        self.assertEqual(self.donos(tenant), [])

    def test_so_a_identidade_executa_a_porta(self) -> None:
        tenant = factories.tenant(self.cur)
        contacto = factories.contacto(self.cur, tenant)
        for papel in ("kamba_app", "kamba_agr", "kamba_batch", "kamba_resolver",
                      "kamba_audit", "kamba_pay", "kamba_pay_hooks"):
            with self.subTest(papel=papel):
                self.recusa(PRIVILEGIO_INSUFICIENTE, tenant, contacto, papel=papel)
        self.assertEqual(self.donos(tenant), [])
        self.cur.execute(
            "SELECT array_agg(r.rolname::text ORDER BY r.rolname) FROM pg_roles r "
            "WHERE r.rolname LIKE %s AND r.rolname <> 'kamba_migrator' "
            # Pelo nome e nao pela assinatura: a `0075` (KAM-216) acrescentou o
            # terceiro argumento, e a porta continua a ser uma so.
            "AND EXISTS (SELECT 1 FROM pg_proc p WHERE p.proname = 'definir_dono' "
            "AND has_function_privilege(r.oid, p.oid, 'EXECUTE'))",
            ("kamba\\_%",),
        )
        self.assertEqual(self.cur.fetchone()[0], ["kamba_identity"])

    def test_a_aplicacao_le_o_papel_do_seu_tenant_e_nao_o_de_outro(self) -> None:
        a = factories.tenant(self.cur)
        b = factories.tenant(self.cur)
        dono_a = factories.contacto(self.cur, a)
        dono_b = factories.contacto(self.cur, b)
        self.definir(a, dono_a)
        self.definir(b, dono_b)
        _papel(self.cur, "kamba_app", a)
        self.cur.execute(
            "SELECT contact_id::text, papel FROM platform.contacts WHERE papel = 'dono'"
        )
        self.assertEqual([tuple(x) for x in self.cur.fetchall()], [(dono_a, "dono")])


class TestDuasTrocasConcorrentes(unittest.TestCase):
    """Duas trocas ao mesmo tempo no mesmo tenant: duas trocas seguidas, um dono.

    **Faz *commit*, e e a unica classe deste ficheiro que o faz**: a segunda
    transaccao so ve o que a primeira fez depois de ela comprometer. Limpa no
    `tearDown` o tenant e os contactos que escreveu — nenhuma tabela
    *append-only* e tocada (a porta nao audita), pelo que a limpeza e um
    `DELETE` e as descidas da suite nao ficam presas.

    A porta tranca a linha do tenant antes de ler o dono: a segunda chamada
    espera pela primeira e, em `READ COMMITTED`, le o dono que ela deixou. Sem
    essa tranca a segunda nao ve o dono novo, tenta promover o seu e leva
    `23505` do `contacts_um_dono` — nao ficam dois donos, mas a troca legitima
    perde-se.
    """

    ESPERA = 1.5

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        admin = ligacao.ligar("admin")
        try:
            cur = admin.cursor()
            self.tenant = factories.tenant(cur)
            self.c1 = factories.contacto(cur, self.tenant)
            self.c2 = factories.contacto(cur, self.tenant)
            self.c3 = factories.contacto(cur, self.tenant)
            admin.commit()
        finally:
            admin.close()
        primeira = self._identidade()
        try:
            primeira.cursor().execute(PORTA, (self.c1, "provisionamento"))
            primeira.commit()
        finally:
            primeira.close()

    def tearDown(self) -> None:
        admin = ligacao.ligar("admin")
        try:
            cur = admin.cursor()
            cur.execute("UPDATE platform.tenants SET owner_contact_id = NULL WHERE id = %s", (self.tenant,))
            cur.execute("DELETE FROM platform.contacts WHERE tenant_id = %s", (self.tenant,))
            cur.execute("DELETE FROM platform.tenants WHERE id = %s", (self.tenant,))
            admin.commit()
        finally:
            admin.close()

    def _identidade(self):
        conexao = ligacao.ligar("identity")
        cur = conexao.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))
        cur.fetchone()
        return conexao

    def test_duas_trocas_concorrentes_nao_deixam_dois_donos(self) -> None:
        primeira, segunda = self._identidade(), self._identidade()
        resultado: dict[str, object] = {}

        def troca() -> None:
            try:
                cur = segunda.cursor()
                cur.execute(PORTA, (self.c3, "troca_de_telefone"))
                resultado["devolvido"] = str(cur.fetchone()[0])
                segunda.commit()
            except Exception as erro:  # noqa: BLE001 — guarda-se o SQLSTATE
                resultado["erro"] = sqlstate(erro)
                segunda.rollback()

        try:
            cur = primeira.cursor()
            cur.execute(PORTA, (self.c2, "troca_de_telefone"))
            self.assertEqual(str(cur.fetchone()[0]), self.c1)
            fio = threading.Thread(target=troca, daemon=True)
            fio.start()
            time.sleep(self.ESPERA)
            self.assertTrue(fio.is_alive(), "a segunda troca nao esperou pela primeira")
            primeira.commit()
            fio.join(timeout=30)
            self.assertFalse(fio.is_alive())
        finally:
            primeira.close()
            segunda.close()

        self.assertEqual(resultado, {"devolvido": self.c2})
        admin = ligacao.ligar("admin")
        try:
            cur = admin.cursor()
            cur.execute(
                "SELECT contact_id::text FROM platform.contacts WHERE tenant_id = %s AND papel = 'dono'",
                (self.tenant,),
            )
            self.assertEqual([x[0] for x in cur.fetchall()], [self.c3])
            cur.execute("SELECT owner_contact_id::text FROM platform.tenants WHERE id = %s", (self.tenant,))
            self.assertEqual(cur.fetchone()[0], self.c3)
        finally:
            admin.close()


class TestAccoesDoDono(ComDono):
    """Criterio 5: a ficha, pela aplicacao com o contexto do tenant."""

    def ficha(self, tenant: str, contacto: str, ref: str = "lote-1",
              expira: str = "now() + interval '15 minutes'") -> str:
        _papel(self.cur, "kamba_app", tenant)
        self.cur.execute(
            "INSERT INTO platform.owner_actions (tenant_id, contact_id, tipo, ref, expira_at) "
            f"VALUES (%s, %s, 'preco_stock_em_massa', %s, {expira}) RETURNING action_id::text",
            (tenant, contacto, ref),
        )
        accao = self.cur.fetchone()[0]
        _papel(self.cur, None)
        return accao

    def confirmar(self, tenant: str, accao: str, contacto: str) -> int:
        _papel(self.cur, "kamba_app", tenant)
        self.cur.execute(CONFIRMAR, (accao, contacto))
        linhas = len(self.cur.fetchall())
        _papel(self.cur, None)
        return linhas

    def com_dono(self) -> tuple[str, str]:
        tenant = factories.tenant(self.cur)
        dono = factories.contacto(self.cur, tenant)
        self.definir(tenant, dono)
        return tenant, dono

    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        self.cur.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.owner_actions'::regclass"
        )
        self.assertEqual(tuple(self.cur.fetchone()), (True, True))

    def test_o_duplo_toque_confirma_uma_vez(self) -> None:
        tenant, dono = self.com_dono()
        accao = self.ficha(tenant, dono)
        self.assertEqual([self.confirmar(tenant, accao, dono) for _ in range(2)], [1, 0])
        self.cur.execute("SELECT estado, confirmada_at IS NOT NULL FROM platform.owner_actions "
                         "WHERE action_id = %s", (accao,))
        self.assertEqual(tuple(self.cur.fetchone()), ("confirmada", True))

    def test_o_botao_expirado_nao_confirma(self) -> None:
        tenant, dono = self.com_dono()
        accao = self.ficha(tenant, dono, expira="now() - interval '1 second'")
        self.assertEqual(self.confirmar(tenant, accao, dono), 0)

    def test_outro_contacto_nao_confirma_a_ficha_do_dono(self) -> None:
        tenant, dono = self.com_dono()
        cliente = factories.contacto(self.cur, tenant)
        accao = self.ficha(tenant, dono)
        self.assertEqual(self.confirmar(tenant, accao, cliente), 0)
        self.assertEqual(self.confirmar(tenant, accao, dono), 1)

    def test_o_tenant_a_nao_ve_nem_confirma_a_ficha_de_b(self) -> None:
        a, dono_a = self.com_dono()
        b, dono_b = self.com_dono()
        de_b = self.ficha(b, dono_b)
        _papel(self.cur, "kamba_app", a)
        self.cur.execute("SELECT count(*) FROM platform.owner_actions WHERE action_id = %s", (de_b,))
        self.assertEqual(self.cur.fetchone()[0], 0)
        _papel(self.cur, None)
        self.assertEqual(self.confirmar(a, de_b, dono_b), 0)
        self.assertEqual(self.confirmar(b, de_b, dono_b), 1)

    def test_a_aplicacao_nao_escreve_a_ficha_no_tenant_de_outro(self) -> None:
        a, _ = self.com_dono()
        b, dono_b = self.com_dono()
        _papel(self.cur, "kamba_app", a)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                           "INSERT INTO platform.owner_actions (tenant_id, contact_id, tipo, ref, expira_at) "
                           "VALUES (%s, %s, 'enviar_proposta', 'p-1', now() + interval '15 minutes')",
                           (b, dono_b))
        _papel(self.cur, None)

    def test_a_mesma_accao_e_uma_ficha(self) -> None:
        tenant, dono = self.com_dono()
        self.ficha(tenant, dono, ref="lote-7")
        _papel(self.cur, "kamba_app", tenant)
        self.assertErroSql(VIOLACAO_DE_UNICIDADE, self.cur,
                           "INSERT INTO platform.owner_actions (tenant_id, contact_id, tipo, ref, expira_at) "
                           "VALUES (%s, %s, 'preco_stock_em_massa', 'lote-7', now() + interval '15 minutes')",
                           (tenant, dono))
        _papel(self.cur, None)

    def test_confirmada_e_confirmada_at_andam_juntas(self) -> None:
        tenant, dono = self.com_dono()
        accao = self.ficha(tenant, dono)
        _papel(self.cur, "kamba_app", tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur,
                           "UPDATE platform.owner_actions SET estado = 'confirmada' WHERE action_id = %s",
                           (accao,))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cur,
                           "UPDATE platform.owner_actions SET confirmada_at = now() WHERE action_id = %s",
                           (accao,))
        _papel(self.cur, None)

    def test_a_aplicacao_nao_apaga_nem_muda_o_que_define_a_ficha(self) -> None:
        tenant, dono = self.com_dono()
        accao = self.ficha(tenant, dono)
        _papel(self.cur, "kamba_app", tenant)
        for sql in (
            "DELETE FROM platform.owner_actions WHERE action_id = %s",
            "UPDATE platform.owner_actions SET expira_at = now() + interval '1 day' WHERE action_id = %s",
            "UPDATE platform.owner_actions SET contact_id = gen_random_uuid() WHERE action_id = %s",
        ):
            with self.subTest(sql=sql):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur, sql, (accao,))
        _papel(self.cur, None)

    def test_o_resolvedor_nao_le_as_fichas(self) -> None:
        tenant, dono = self.com_dono()
        self.ficha(tenant, dono)
        _papel(self.cur, "kamba_resolver", tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur, "SELECT count(*) FROM platform.owner_actions")
        _papel(self.cur, None)


class TestDowngradeDoCanalDoDono(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> tuple[int, int, int, int, bool]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' AND tablename = 'owner_actions'")
            tabelas = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                      "AND table_name = 'contacts' AND column_name IN ('papel', 'papel_mudou_at')")
            colunas = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_indexes WHERE indexname = 'contacts_um_dono'")
            indices = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'definir_dono'")
            funcoes = int(c.fetchone()[0])
            # O `INSERT` da identidade: por coluna em cima, de tabela em baixo.
            c.execute("SELECT has_table_privilege('kamba_identity', 'platform.contacts', 'INSERT')")
            insert_de_tabela = bool(c.fetchone()[0])
            return tabelas, colunas, indices, funcoes, insert_de_tabela
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        self.assertEqual(self._objectos(), (1, 2, 1, 1, False))
        alembic_ok("downgrade", _anterior())
        self.assertEqual(self._objectos(), (0, 0, 0, 0, True))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), (1, 2, 1, 1, False))


if __name__ == "__main__":
    unittest.main()
