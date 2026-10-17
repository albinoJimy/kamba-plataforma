"""O registo de auditoria: imutabilidade, cadeia e privilegios (KAM-012).

A tabela existe para uma coisa so: **uma linha escrita aqui nao se altera nem
desaparece**, e se alguem a alterar por fora isso descobre-se. Tudo o que
segue e a verificacao dessa frase, por partes.

O que esta bateria **nao** cobre, e onde esta: as mil insercoes concorrentes
do criterio 3 estao em `db/tests_auditoria_carga/`, pela mesma razao que a
carga de eventos foi separada no KAM-005 — cada mutacao da prova por mutacao
paga o custo da suite inteira, e mil insercoes custam minutos.
"""

from __future__ import annotations

import hashlib
import json
import unittest
import uuid

from tests import factories
from tests.base import ComBase

#: «Sem tenant», para distinguir de «o tenant por omissao desta bateria».
#:
#: Um `None` por omissao significava «usa o meu tenant», e com isso nao
#: havia forma de pedir a cadeia de plataforma — o teste que a devia provar
#: escrevia no tenant normal e contava zero. Apanhado pela suite.
PLATAFORMA = object()

#: A genese de uma cadeia: trinta e dois zeros. Ver a revisao 0006.
GENESE = bytes(32)

#: A chave da cadeia de plataforma, para as accoes sem tenant.
CHAVE_DA_PLATAFORMA = "00000000-0000-0000-0000-000000000000"

#: O dominio de `action` (dicionario §3.2, emenda 1.14). Sao **sete**: o
#: `audit.read` entra porque o criterio 8 do ticket exige que a leitura do
#: registo seja ela propria registada, e chama-lhe assim.
ACCOES = (
    "price.update",
    "stock.adjust",
    "payment.manual_confirm",
    "access.conversation",
    "batch.run",
    "breakglass.open",
    "audit.read",
)

#: O dominio de `actor_type`.
TIPOS_DE_ATOR = ("contact", "owner", "staff", "agent", "system")

#: Os campos do `row_hash`, por ordem. A mesma tupla da revisao 0006 — e a
#: duplicacao e deliberada: se o hash muda de forma, estes testes tem de
#: falhar, e nao de acompanhar.
CAMPOS_DO_ROW_HASH = (
    "prev_hash", "tenant_id", "actor_type", "actor_id", "action",
    "entity", "entity_id", "turn_id", "payload_hash",
)


def row_hash(prev: bytes, tenant, actor_type, actor_id, action, entity,
             entity_id, turn_id, payload_hash: bytes) -> bytes:
    """A formula do elo, reimplementada **em Python**.

    Nao chama a funcao SQL de proposito: uma verificacao que use a mesma
    implementacao que escreveu o valor nao verifica nada. O separador e o
    `chr(31)` e os `bytea` entram em hexadecimal, como o SQL faz.
    """
    partes = (
        prev.hex(),
        "" if tenant is None else str(tenant),
        actor_type, actor_id, action, entity, entity_id,
        "" if turn_id is None else turn_id,
        payload_hash.hex(),
    )
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).digest()


class ComAuditoria(ComBase):
    """Um tenant e um atalho para escrever linhas de auditoria."""

    def setUp(self) -> None:
        super().setUp()
        self.ligacao = self.ligar("admin")
        self.cursor = self.ligacao.cursor()
        self.tenant = factories.tenant(self.cursor)

    def escrever(self, tenant=None, actor_type="staff", actor_id="op-1",
                 action="price.update", entity="produto", entity_id="sku-1",
                 turn_id=None, payload=b"x", cursor=None) -> bytes:
        alvo = cursor or self.cursor
        alvo.execute(
            "SELECT platform.audit_append(%s, %s, %s, %s, %s, %s, %s, sha256(%s))",
            (self._tenant(tenant), actor_type, actor_id,
             action, entity, entity_id, turn_id, payload),
        )
        return bytes(alvo.fetchone()[0])

    def _tenant(self, pedido):
        """`None` e «o meu»; `PLATAFORMA` e «nenhum»."""
        if pedido is PLATAFORMA:
            return None
        return self.tenant if pedido is None else pedido

    def linhas(self, tenant=None) -> list:
        self.cursor.execute(
            "SELECT id, tenant_id, actor_type, actor_id, action, entity, entity_id, "
            "       turn_id, payload_hash, prev_hash, row_hash "
            "  FROM platform.audit_log "
            " WHERE tenant_id IS NOT DISTINCT FROM %s ORDER BY id",
            (self._tenant(tenant),),
        )
        return [tuple(linha) for linha in self.cursor.fetchall()]

    def cabeca(self, tenant=None):
        self.cursor.execute(
            "SELECT last_hash FROM platform.audit_heads "
            " WHERE chave = coalesce(%s::uuid, %s::uuid)",
            (self._tenant(tenant), CHAVE_DA_PLATAFORMA),
        )
        linha = self.cursor.fetchone()
        return bytes(linha[0]) if linha else None


class TestImutabilidade(ComAuditoria):
    """O criterio 1: `UPDATE`, `DELETE` e `TRUNCATE` falham para tres papeis.

    **Falham tambem para o dono**, e isso nao vem do `REVOKE`: vem do
    *trigger*. O `REVOKE` tira o privilegio a quem o tem por omissao; o dono
    da tabela tem-no sempre. Medido na revisao 0006.
    """

    def test_o_dono_nao_altera_nem_apaga(self) -> None:
        self.escrever()
        for sql in (
            "UPDATE platform.audit_log SET actor_id = 'outro'",
            "DELETE FROM platform.audit_log",
            "TRUNCATE platform.audit_log",
        ):
            with self.subTest(sql=sql.split()[0]):
                self.assertErroSql("23000", self.cursor, sql)

    def test_a_aplicacao_e_o_batch_tambem_nao(self) -> None:
        self.escrever()
        self.ligacao.commit()
        self.addCleanup(self._limpar)
        for identidade in ("app", "batch"):
            cursor = self.ligar(identidade).cursor()
            if identidade == "app":
                cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (self.tenant,))
            for sql in (
                "UPDATE platform.audit_log SET actor_id = 'outro'",
                "DELETE FROM platform.audit_log",
                "TRUNCATE platform.audit_log",
            ):
                with self.subTest(identidade=identidade, sql=sql.split()[0]):
                    # 42501 quando o privilegio falta, 23000 quando o trigger
                    # recusa. Os dois sao «nao passou», e o teste nao escolhe
                    # por ele qual e — escolhe o que o servidor disser, desde
                    # que a linha fique.
                    with self.assertRaises(Exception):
                        cursor.execute(sql)
                    cursor.execute("ROLLBACK")
        self.assertEqual(len(self.linhas()), 1, "a linha tem de sobreviver aos seis ataques")

    def test_o_session_replication_role_nao_contorna_o_trigger(self) -> None:
        """O que a medicao da revisao 0006 mudou no criterio 5.

        O bloco do ticket propoe adulterar uma linha com
        `session_replication_role = replica`. Medido: isso contorna um
        *trigger* normal, e **nao** contorna um `ENABLE ALWAYS`. Escolheu-se o
        `ALWAYS`, pelo que este caminho de adulteracao deixou de existir — e
        este teste e o que o prende.
        """
        self.escrever()
        self.cursor.execute("SET session_replication_role = replica")
        self.assertErroSql(
            "23000", self.cursor, "UPDATE platform.audit_log SET actor_id = 'adulterado'"
        )
        self.cursor.execute("SET session_replication_role = origin")
        self.assertEqual(self.linhas()[0][3], "op-1")

    def _limpar(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute("ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_log")
        cursor.execute("ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_heads")
        cursor.connection.commit()


class TestCadeia(ComAuditoria):
    """O criterio 2: `payload_hash` sobre o JSON, `row_hash = H(prev || campos)`."""

    def test_o_primeiro_elo_parte_da_genese(self) -> None:
        self.escrever()
        (linha,) = self.linhas()
        self.assertEqual(bytes(linha[9]), GENESE)

    def test_cada_elo_aponta_para_o_anterior(self) -> None:
        for n in range(4):
            self.escrever(entity_id=f"sku-{n}")
        linhas = self.linhas()
        self.assertEqual(len(linhas), 4)
        for anterior, seguinte in zip(linhas, linhas[1:]):
            self.assertEqual(bytes(seguinte[9]), bytes(anterior[10]))

    def test_o_row_hash_recalcula_se_em_python(self) -> None:
        """A verificacao independente: a formula, reimplementada deste lado."""
        self.escrever(turn_id="t-1")
        self.escrever(entity_id="sku-2")
        for linha in self.linhas():
            with self.subTest(id=linha[0]):
                self.assertEqual(
                    bytes(linha[10]),
                    row_hash(bytes(linha[9]), linha[1], linha[2], linha[3], linha[4],
                             linha[5], linha[6], linha[7], bytes(linha[8])),
                )

    def test_a_cabeca_e_o_ultimo_elo(self) -> None:
        self.escrever()
        ultimo = self.escrever(entity_id="sku-2")
        self.assertEqual(self.cabeca(), ultimo)

    def test_duas_cadeias_nao_se_misturam(self) -> None:
        outro = factories.tenant(self.cursor)
        self.escrever()
        self.escrever(tenant=outro)
        self.escrever(entity_id="sku-2")
        self.assertEqual(len(self.linhas()), 2)
        self.assertEqual(len(self.linhas(outro)), 1)
        # O primeiro elo de cada cadeia parte da genese, e nao do ultimo elo
        # da outra — que e o defeito que uma cadeia global teria.
        self.assertEqual(bytes(self.linhas(outro)[0][9]), GENESE)

    def test_a_cadeia_de_plataforma_tem_tenant_nulo(self) -> None:
        """`batch.run` e `breakglass.open` nao tem tenant, e tem cadeia.

        A medicao da revisao 0006 mostrou que isto era **impossivel** com a
        primeira forma da funcao de hash: `STRICT` sobre um `uuid` nulo dava
        `NULL`, e o `NOT NULL` da cabeca recusava a linha.
        """
        cursor = self.ligar("batch").cursor()
        self.escrever(tenant=PLATAFORMA, actor_type="system", action="batch.run",
                      entity="retencao", entity_id="r-1", cursor=cursor)
        cursor.connection.commit()
        self.addCleanup(self._limpar_plataforma)
        self.cursor.execute(
            "SELECT count(*) FROM platform.audit_heads WHERE tenant_id IS NULL"
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)

    def test_o_payload_hash_e_do_hash_e_nao_do_conteudo(self) -> None:
        """A coluna e `bytea` de 32 bytes: nao cabe la texto de conversa."""
        antes = {"preco_minor": 1250000}
        depois = {"preco_minor": 1500000}
        canonico = json.dumps({"antes": antes, "depois": depois}, sort_keys=True,
                              separators=(",", ":"))
        esperado = hashlib.sha256(canonico.encode("utf-8")).digest()
        self.cursor.execute(
            "SELECT platform.audit_append(%s,'owner','o','price.update','produto','sku-1',"
            "NULL, %s)",
            (self.tenant, esperado),
        )
        (linha,) = self.linhas()
        self.assertEqual(bytes(linha[8]), esperado)
        self.assertEqual(len(bytes(linha[8])), 32)

    def _limpar_plataforma(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute("ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_log WHERE tenant_id IS NULL")
        cursor.execute("ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_heads WHERE tenant_id IS NULL")
        cursor.connection.commit()


class TestVocabulario(ComAuditoria):
    """O criterio 4: uma accao fora da lista e recusada."""

    def test_as_sete_accoes_passam(self) -> None:
        for n, accao in enumerate(ACCOES):
            with self.subTest(accao=accao):
                self.escrever(action=accao, entity_id=f"e-{n}")
        self.assertEqual(len(self.linhas()), len(ACCOES))

    def test_uma_accao_fora_da_lista_e_recusada(self) -> None:
        self.assertErroSql(
            "23514", self.cursor,
            "SELECT platform.audit_append(%s,'staff','o','accao.inventada','e','1',NULL,"
            "sha256('x'))",
            (self.tenant,),
        )

    def test_os_cinco_tipos_de_ator_passam_e_um_sexto_nao(self) -> None:
        for n, tipo in enumerate(TIPOS_DE_ATOR):
            with self.subTest(tipo=tipo):
                self.escrever(actor_type=tipo, entity_id=f"a-{n}")
        self.assertErroSql(
            "23514", self.cursor,
            "SELECT platform.audit_append(%s,'robot','o','price.update','e','1',NULL,"
            "sha256('x'))",
            (self.tenant,),
        )

    def test_o_dominio_do_check_e_o_desta_bateria(self) -> None:
        """O dominio esta escrito em tres sitios; aqui confrontam-se os tres.

        A revisao 0006 tem a tupla **e** os literais por extenso, porque o
        gate 3b nao sabe ler um `join`. Dois sitios que ninguem compara
        divergem; este teste e a comparacao, e le o terceiro — o catalogo.
        """
        self.cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE conname = 'audit_log_action'"
        )
        definicao = self.cursor.fetchone()[0]
        for accao in ACCOES:
            self.assertIn(f"'{accao}'", definicao)
        self.assertEqual(definicao.count("'::text"), len(ACCOES))


class TestPrivilegios(ComAuditoria):
    """O criterio 8: quem escreve nao le, e quem le e o papel de auditoria."""

    def test_a_aplicacao_escreve_e_nao_le(self) -> None:
        cursor = self.ligar("app").cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (self.tenant,))
        self.ligacao.commit()
        self.addCleanup(self._limpar_tudo)
        self.escrever(cursor=cursor)
        self.assertErroSql("42501", cursor, "SELECT 1 FROM platform.audit_log LIMIT 1")

    def test_o_papel_de_auditoria_le_e_nao_escreve(self) -> None:
        self.escrever()
        self.ligacao.commit()
        self.addCleanup(self._limpar_tudo)
        cursor = self.ligar("audit").cursor()
        cursor.execute("SELECT count(*) FROM platform.audit_log")
        self.assertGreaterEqual(cursor.fetchone()[0], 0)
        self.assertErroSql(
            "42501", cursor,
            "SELECT platform.audit_append(%s,'staff','o','audit.read','e','1',NULL,sha256('x'))",
            (self.tenant,),
        )

    def test_ninguem_tem_delete(self) -> None:
        """Nem o batch: a retencao do `audit_log` depende de um prazo fiscal
        que esta **NAO VERIFICADO** (dicionario §4, KAM-071), e uma funcao de
        limpeza escrita contra um prazo que ninguem confirmou apaga prova que
        a lei pode exigir."""
        concedidos = self.consultar(
            "SELECT grantee, privilege_type FROM information_schema.table_privileges "
            " WHERE table_schema = 'platform' AND table_name = 'audit_log' "
            "   AND privilege_type IN ('DELETE', 'TRUNCATE', 'UPDATE') "
            # O dono tem-nos sempre, e nao ha `REVOKE` que lhos tire: e por
            # isso que a imutabilidade nao pode assentar em privilegios. O que
            # o prende e o *trigger*, e quem o prova e o `TestImutabilidade`.
            "   AND grantee <> 'kamba_migrator'"
        )
        self.assertEqual(concedidos, [])

    def _limpar_tudo(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute("ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_log")
        cursor.execute("ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_heads")
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (self.tenant,))
        cursor.connection.commit()


class TestIsolamento(ComAuditoria):
    """A RLS: a aplicacao nao escreve no tenant de outro nem na plataforma."""

    def setUp(self) -> None:
        super().setUp()
        self.ligacao.commit()
        self.addCleanup(self._limpar_tudo)
        self.cursor_app = self.ligar("app").cursor()
        self.cursor_app.execute(
            "SELECT set_config('app.tenant_id', %s, false)", (self.tenant,)
        )

    def test_escreve_no_seu_tenant(self) -> None:
        self.assertEqual(len(self.escrever(cursor=self.cursor_app)), 32)

    def test_nao_escreve_no_tenant_de_outro(self) -> None:
        self.assertErroSql(
            "42501", self.cursor_app,
            "SELECT platform.audit_append(%s,'owner','o','price.update','e','1',NULL,"
            "sha256('x'))",
            (str(uuid.uuid4()),),
        )

    def test_nao_escreve_uma_accao_de_plataforma(self) -> None:
        """`tenant_id` nulo e invisivel a politica `tenant_iso`, para toda a
        gente. Nao e um furo: e a propriedade que se quer — quem escreve
        `batch.run` e o `kamba_batch`, que tem `BYPASSRLS`."""
        self.assertErroSql(
            "42501", self.cursor_app,
            "SELECT platform.audit_append(NULL,'system','j','batch.run','e','1',NULL,"
            "sha256('x'))",
        )

    def _limpar_tudo(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute("ALTER TABLE platform.audit_log DISABLE TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_log")
        cursor.execute("ALTER TABLE platform.audit_log ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete")
        cursor.execute("DELETE FROM platform.audit_heads")
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (self.tenant,))
        cursor.connection.commit()


if __name__ == "__main__":
    unittest.main()
