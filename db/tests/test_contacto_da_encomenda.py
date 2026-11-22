"""O contacto da encomenda ao dono: a auditoria pelo `kamba_identity` (KAM-206, revisao `0082`).

A decisao do fundador de 2026-11-20 (opcao A): o COM decifra o telefone como
`kamba_identity`, e a linha de `audit_log` `order.contact_view` escreve-se na
transaccao da decifra. Para isso o papel ganhou **so** o `EXECUTE` no
`audit_append` e o `INSERT` nas oito colunas que ele escreve. Contra a base:

* o SQL do COM (`SQL_AUDITAR_CONTACTO` de `services/com/src/orders/contacto.ts`,
  lido do proprio ficheiro) escreve a linha como `kamba_identity`, no tenant do
  contexto, encadeada pelo *trigger*, e sem o telefone;
* sem contexto, ou com o tenant de outro, a RLS recusa;
* o `kamba_identity` continua sem ler o `audit_log` e a `audit_heads`, sem
  `UPDATE` nem `DELETE`, sem escolher o `criado_at` nem o `row_hash`, e sem o
  `audit_row_hash` — e as concessoes dele no `audit_log` sao exactamente as oito;
* o `downgrade` da `0082` recusa com uma linha escrita, e sem ela desce e volta.

**Desce pelo `down_revision` da revisao, lido do ficheiro, e nao por `-1`**, e
**nao exige `em_head()` depois de recusar**, pela razao do
`test_rotacao_de_chaves.py`: o numero da `0082` e provisorio.
"""

from __future__ import annotations

import hashlib
import re
import unittest
import uuid
from pathlib import Path

import ligacao
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    ConsultaDoTypeScript,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_auditoria import ACCOES, _desligar, _religar

RAIZ = Path(__file__).resolve().parents[2]
CONTACTO_TS = RAIZ / "services" / "com" / "src" / "orders" / "contacto.ts"
VERSOES = RAIZ / "db" / "migrations" / "versions"

#: As oito colunas que o `audit_append` escreve, e as unicas que o
#: `kamba_identity` pode inserir.
COLUNAS_DO_AUDIT_APPEND = {
    "tenant_id", "actor_type", "actor_id", "action",
    "entity", "entity_id", "turn_id", "payload_hash",
}

#: Um telefone ficticio, com o 999 que a UIT nao atribui.
TELEFONE = "+244 999 000 789"


def _revisao() -> tuple[str, str]:
    """`(revision, down_revision)` da revisao desta suite, lidos do ficheiro."""
    [ficheiro] = [p for p in VERSOES.glob("*_contacto_da_encomenda.py")]
    texto = ficheiro.read_text(encoding="utf-8")
    revisao = re.search(r'^revision = "(\d{4})"$', texto, re.M)
    abaixo = re.search(r'^down_revision = "(\d{4})"$', texto, re.M)
    assert revisao and abaixo, "a revisao nao declara revision e down_revision"
    return revisao.group(1), abaixo.group(1)


def _texto(order_id: str, estado: str) -> str:
    """O texto canonico do `payload_hash`, como o `textoDaAuditoria` do COM."""
    return "\x1f".join(("order.contact_view", order_id, estado))


def _contexto(cursor, tenant: str | None) -> None:
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))


def _limpar(cursor, tenant: str) -> None:
    """Apaga as linhas do tenant de ensaio e a cabeca dele. Como administrador."""
    _desligar(cursor)
    cursor.execute("DELETE FROM platform.audit_log WHERE tenant_id = %s::uuid", (tenant,))
    _religar(cursor)
    cursor.execute("DELETE FROM platform.audit_heads WHERE tenant_id = %s::uuid", (tenant,))


class TestAuditoriaPeloKambaIdentity(ComBase):
    """O SQL do COM escreve a linha como `kamba_identity`, no tenant do contexto."""

    def test_o_sql_do_com_escreve_a_linha_encadeada_e_sem_o_telefone(self) -> None:
        tenant = str(uuid.uuid4())
        ordem = str(uuid.uuid4())
        identidade = ligacao.ligar("identity")
        admin = ligacao.ligar("admin")
        try:
            c = identidade.cursor()
            _contexto(c, tenant)
            q = ConsultaDoTypeScript("SQL_AUDITAR_CONTACTO", CONTACTO_TS)
            c.execute(q.sql, q.args(tenant, "caso-a", ordem, _texto(ordem, "paga").encode("utf-8")))
            c.fetchall()
            identidade.commit()

            a = admin.cursor()
            a.execute(
                "SELECT actor_type, actor_id, action, entity, entity_id, turn_id, "
                "       payload_hash, prev_hash IS NOT NULL, row_hash IS NOT NULL "
                "  FROM platform.audit_log WHERE tenant_id = %s::uuid",
                (tenant,),
            )
            [linha] = [tuple(x) for x in a.fetchall()]
            self.assertEqual(linha[:6], ("owner", "caso-a", "order.contact_view", "order", ordem, None))
            self.assertEqual(bytes(linha[6]), hashlib.sha256(_texto(ordem, "paga").encode("utf-8")).digest())
            self.assertEqual(linha[7:], (True, True), "o trigger encadeou a linha")
            # Adversarial: nenhuma coluna da linha leva o telefone, nem o resumo dele.
            a.execute(
                "SELECT count(*) FROM platform.audit_log WHERE tenant_id = %s::uuid "
                "   AND (actor_id LIKE '%%999%%' OR entity_id LIKE '%%999%%' "
                "        OR payload_hash = sha256(convert_to(%s, 'UTF8')))",
                (tenant, TELEFONE),
            )
            self.assertEqual(a.fetchone()[0], 0)
            a.execute("SELECT count(*) FROM platform.audit_heads WHERE tenant_id = %s::uuid", (tenant,))
            self.assertEqual(a.fetchone()[0], 1)
        finally:
            identidade.rollback()
            identidade.close()
            _limpar(admin.cursor(), tenant)
            admin.commit()
            admin.close()

    def test_sem_contexto_ou_com_o_tenant_de_outro_a_rls_recusa(self) -> None:
        c = self.ligar("identity").cursor()
        q = ConsultaDoTypeScript("SQL_AUDITAR_CONTACTO", CONTACTO_TS)
        tenant_a, tenant_b, ordem = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        args = q.args(tenant_b, "caso-a", ordem, b"x")
        _contexto(c, None)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, c, q.sql, args)
        _contexto(c, tenant_a)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, c, q.sql, args)

    def test_uma_accao_fora_do_dominio_e_recusada_tambem_ao_kamba_identity(self) -> None:
        c = self.ligar("identity").cursor()
        tenant = str(uuid.uuid4())
        _contexto(c, tenant)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, c,
            "SELECT platform.audit_append(%s::uuid, 'owner', 'caso-a', 'order.contact_export', "
            "'order', 'x', NULL, sha256('x'))",
            (tenant,),
        )


class TestPrivilegiosDoKambaIdentity(ComBase):
    """O que a `0082` deu, e mais nada (o pedido do fundador: ensaiar o «so isso»)."""

    def test_as_concessoes_no_audit_log_sao_so_o_insert_das_oito_colunas(self) -> None:
        colunas = self.consultar(
            "SELECT column_name::text, privilege_type::text FROM information_schema.column_privileges "
            " WHERE grantee = 'kamba_identity' AND table_schema = 'platform' AND table_name = 'audit_log'"
        )
        self.assertEqual({c for c, _ in colunas}, COLUNAS_DO_AUDIT_APPEND)
        self.assertEqual({p for _, p in colunas}, {"INSERT"})
        tabela = self.consultar(
            "SELECT privilege_type::text FROM information_schema.table_privileges "
            " WHERE grantee = 'kamba_identity' AND table_schema = 'platform' "
            "   AND table_name IN ('audit_log', 'audit_heads')"
        )
        self.assertEqual(tabela, [])
        funcoes = self.consultar(
            "SELECT has_function_privilege('kamba_identity', "
            "  'platform.audit_append(uuid, text, text, text, text, text, text, bytea)', 'EXECUTE'), "
            "  has_function_privilege('kamba_identity', "
            "  'platform.audit_row_hash(bytea, timestamptz, text, text, text, text, text, text, text, bytea)', 'EXECUTE')"
        )
        self.assertEqual(funcoes, [(True, False)])

    def test_o_kamba_identity_nao_le_nem_altera_a_cadeia(self) -> None:
        c = self.ligar("identity").cursor()
        _contexto(c, str(uuid.uuid4()))
        for instrucao in (
            "SELECT count(*) FROM platform.audit_log",
            "SELECT count(*) FROM platform.audit_heads",
            "UPDATE platform.audit_log SET actor_id = 'outro'",
            "DELETE FROM platform.audit_log",
            "TRUNCATE platform.audit_log",
            "UPDATE platform.audit_heads SET last_hash = NULL",
            "INSERT INTO platform.audit_log (tenant_id, actor_type, actor_id, action, entity, "
            "  entity_id, payload_hash, criado_at) VALUES (gen_random_uuid(), 'owner', 'x', "
            "  'order.contact_view', 'order', 'x', sha256('x'), now())",
            "INSERT INTO platform.audit_heads (tenant_id, last_hash) VALUES (gen_random_uuid(), sha256('x'))",
        ):
            with self.subTest(instrucao=instrucao[:60]):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, c, instrucao)

    def test_o_dominio_tem_as_vinte(self) -> None:
        [(definicao,)] = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'"
        )
        self.assertIn("'order.contact_view'", definicao)
        # Vinte com a da `0082`; desde a `0086` (KAM-233), as da lista fechada.
        self.assertEqual(definicao.count("'::text"), len(ACCOES))


class TestDowngradeDoContacto(unittest.TestCase):
    """O `downgrade` recusa com uma linha `order.contact_view`, e sem ela desce e volta."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _admin(self):
        conexao = ligacao.ligar("admin")
        self.addCleanup(conexao.close)
        return conexao

    def _definicao(self) -> str:
        c = self._admin().cursor()
        c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'")
        return c.fetchone()[0]

    def _concessoes(self) -> tuple[int, bool]:
        c = self._admin().cursor()
        c.execute(
            "SELECT (SELECT count(*) FROM information_schema.column_privileges "
            "         WHERE grantee = 'kamba_identity' AND table_schema = 'platform' "
            "           AND table_name = 'audit_log'), "
            "       has_function_privilege('kamba_identity', "
            "         'platform.audit_append(uuid, text, text, text, text, text, text, bytea)', 'EXECUTE')"
        )
        return tuple(c.fetchone())

    def test_com_uma_linha_recusa_e_sem_ela_desce_e_volta(self) -> None:
        revisao, abaixo = _revisao()
        conexao = self._admin()
        c = conexao.cursor()
        tenant = str(uuid.uuid4())
        c.execute(
            "SELECT platform.audit_append(%s::uuid, 'owner', 'caso-a', 'order.contact_view', "
            "'order', %s, NULL, sha256('descida'))",
            (tenant, str(uuid.uuid4())),
        )
        conexao.commit()
        try:
            resultado = alembic("downgrade", abaixo)
            self.assertNotEqual(resultado.returncode, 0, "o downgrade devia recusar")
            self.assertIn(f"downgrade da {revisao} recusado", resultado.stderr)
            self.assertIn("'order.contact_view'", self._definicao(), "o dominio ficou, com a linha")
            self.assertEqual(self._concessoes(), (8, True), "as concessoes ficaram, com a linha")
        finally:
            if not em_head():
                alembic_ok("upgrade", "head")
            _limpar(c, tenant)
            conexao.commit()
        alembic_ok("downgrade", abaixo)
        try:
            definicao = self._definicao()
            # Descer a `0082` desce primeiro a `0086` (KAM-233), que tira a sua.
            esperadas = [a for a in ACCOES if a not in {"order.contact_view", "privacy.telefones_exportados"}]
            for accao in esperadas:
                self.assertIn(f"'{accao}'", definicao)
            self.assertEqual(definicao.count("'::text"), len(esperadas))
            self.assertEqual(self._concessoes(), (0, False))
        finally:
            alembic_ok("upgrade", "head")
        self.assertIn("'order.contact_view'", self._definicao())
        self.assertEqual(self._concessoes(), (8, True))


if __name__ == "__main__":
    unittest.main()
