"""A revisao do KYC contra a base: onboarding_case e kyc_check (KAM-087).

O que so uma base prova, e por isso este ficheiro existe:

1. **As listas fechadas sao as do codigo.** A `fase` contra o `FASES` da
   inscricao (KAM-086), as marcas, os tipos e os resultados contra o
   `packages/core-ts/src/kyc/contrato.ts`. Sao copias inevitaveis — a base impoe,
   o codigo decide —, e esta e a forma da casa de as prender.
2. **O `fase_at` e do *trigger* e de mais ninguem.** Quem insere com uma data
   antiga leva `now()`; mudar outra coluna nao o mexe; mudar a fase mexe. E o
   «D» dos D+30 do criterio 10, e um `fase_at` escrevivel purgava cedo.
3. **O indice unico do NIF so cobre casos vivos**, com o predicado que o
   `FASES_MORTAS` do codigo tem.
4. **As restricoes do `kyc_check`**: a unicidade `(onboarding_id, sha256)` que e
   a idempotencia da DoD 4; a FK composta que impede o caso de um com o tenant
   de outro; o `doc_ref` preso ao prefixo do tenant no STO; os dominios.
5. **O SQL do modulo de TypeScript**, executado tal como esta escrito: a
   insercao idempotente, a fronteira de Hamming 6/7 do `phash` e a exclusao do
   proprio caso, a decisao, o custo do caso e os mortos ate D+30.
6. **Privilegios e RLS**: o `kamba_app` nao escreve no `kyc_check` nem no
   `fase_at`, ninguem apaga, e um tenant nao ve o caso de outro.
7. **O `downgrade`.**
"""

from __future__ import annotations

import hashlib
import re
import unittest
import uuid
from pathlib import Path

import kyc
import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
INSCRICAO = RAIZ / "packages" / "core-ts" / "src" / "inscricao" / "contrato.ts"
CONTRATO = RAIZ / "packages" / "core-ts" / "src" / "kyc" / "contrato.ts"
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "kyc" / "sql.ts"

CASO = "platform.onboarding_case"
KYC = "platform.kyc_check"


def _lista_ts(ficheiro: Path, nome: str) -> tuple[str, ...]:
    texto = ficheiro.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {ficheiro.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def _dominio(cursor, restricao: str) -> tuple[str, ...]:
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
        (restricao,),
    )
    return tuple(sorted(re.findall(r"'([a-z0-9_]+)'", cursor.fetchone()[0])))


def caso(cursor, **campos) -> tuple[str, str]:
    """Um caso minimo. Devolve `(id, tenant_id)`."""
    valores = {
        "origem": "convite",
        "nome_negocio": "negocio de ensaio",
        "categoria_declarada": "moda",
        "nif_enc": b"\x01",
        "nif_hmac": hashlib.sha256(uuid.uuid4().bytes).digest(),
        "phone_enc": b"\x02",
        "phone_hmac": hashlib.sha256(uuid.uuid4().bytes).digest(),
    }
    valores.update(campos)
    colunas = ", ".join(valores)
    marcas = ", ".join(["%s"] * len(valores))
    cursor.execute(
        f"INSERT INTO {CASO} ({colunas}) VALUES ({marcas}) RETURNING id::text, tenant_id::text",
        tuple(valores.values()),
    )
    linha = cursor.fetchone()
    return linha[0], linha[1]


def verificacao(cursor, onboarding_id: str, tenant_id: str, **campos) -> str:
    valores = {
        "onboarding_id": onboarding_id,
        "tenant_id": tenant_id,
        "doc_tipo": "bi",
        "doc_ref": f"t/{tenant_id}/kyc_documento/2026/11/{uuid.uuid4()}",
        "sha256": hashlib.sha256(uuid.uuid4().bytes).digest(),
        "resultado": "pendente",
        "versao_regras": "1.0.0",
    }
    valores.update(campos)
    colunas = ", ".join(valores)
    marcas = ", ".join(["%s"] * len(valores))
    cursor.execute(
        f"INSERT INTO {KYC} ({colunas}) VALUES ({marcas}) RETURNING id::text", tuple(valores.values())
    )
    return cursor.fetchone()[0]


class TestDominios(ComBase):
    def test_as_duas_tabelas_existem_em_head(self) -> None:
        linhas = self.consultar(
            "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' "
            "AND tablename IN ('onboarding_case', 'kyc_check') ORDER BY 1"
        )
        self.assertEqual(linhas, [("kyc_check",), ("onboarding_case",)])

    def test_a_fase_e_a_do_codigo_da_inscricao_e_a_do_modulo(self) -> None:
        cursor = self.ligar("admin").cursor()
        self.assertEqual(_dominio(cursor, "onboarding_case_fase_ck"), tuple(sorted(_lista_ts(INSCRICAO, "FASES"))))
        self.assertEqual(tuple(sorted(kyc.FASES)), tuple(sorted(_lista_ts(INSCRICAO, "FASES"))))

    def test_os_dominios_do_kyc_sao_os_do_contrato(self) -> None:
        cursor = self.ligar("admin").cursor()
        marcas = sorted(
            _lista_ts(CONTRATO, "REGRAS_DURAS")
            + _lista_ts(CONTRATO, "REGRAS_PONDERADAS")
            + _lista_ts(CONTRATO, "OUTRAS_MARCAS")
        )
        self.assertEqual(_dominio(cursor, "kyc_check_flags_ck"), tuple(marcas))
        self.assertEqual(_dominio(cursor, "kyc_check_doc_tipo_ck"), tuple(sorted(_lista_ts(CONTRATO, "TIPOS_DE_DOCUMENTO"))))
        self.assertEqual(_dominio(cursor, "kyc_check_resultado_ck"), tuple(sorted(_lista_ts(CONTRATO, "RESULTADOS"))))


class TestCaso(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def test_o_fase_at_e_do_trigger(self) -> None:
        onboarding_id, _ = caso(self.cursor, fase_at="2020-01-01T00:00:00Z")
        self.cursor.execute(f"SELECT fase_at = now() FROM {CASO} WHERE id = %s", (onboarding_id,))
        self.assertTrue(self.cursor.fetchone()[0], "quem insere nao escolhe o fase_at")

    def test_mudar_outra_coluna_nao_mexe_no_fase_at_e_mudar_a_fase_mexe(self) -> None:
        onboarding_id, _ = caso(self.cursor)
        self.cursor.execute(f"UPDATE {CASO} SET fase_at = '2020-01-01', flags = '{{duplicado_ambiguo}}' WHERE id = %s", (onboarding_id,))
        self.cursor.execute(f"SELECT fase_at = now() FROM {CASO} WHERE id = %s", (onboarding_id,))
        self.assertTrue(self.cursor.fetchone()[0], "um UPDATE sem mudar a fase nao reescreve o fase_at")
        self.cursor.execute(f"UPDATE {CASO} SET fase = 'otp_pendente', fase_at = '2020-01-01' WHERE id = %s", (onboarding_id,))
        self.cursor.execute(f"SELECT fase_at = now(), fase FROM {CASO} WHERE id = %s", (onboarding_id,))
        self.assertEqual(self.cursor.fetchone(), [True, "otp_pendente"])

    def test_o_nif_e_unico_entre_casos_vivos_e_so_entre_eles(self) -> None:
        nif = hashlib.sha256(b"nif de ensaio").digest()
        caso(self.cursor, nif_hmac=nif)
        self.assertErroSql(VIOLACAO_DE_UNICIDADE, self.cursor, f"INSERT INTO {CASO} (origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac) VALUES ('convite', 'n', 'moda', '\\x01', %s, '\\x02', %s)", (nif, hashlib.sha256(b"t").digest()))
        self.cursor.execute(f"UPDATE {CASO} SET fase = 'rejeitado' WHERE nif_hmac = %s", (nif,))
        caso(self.cursor, nif_hmac=nif)

    def test_fase_fora_do_dominio_e_recusada(self) -> None:
        for fase in ("pronto", "ativo", "estado"):
            with self.subTest(fase=fase):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.cursor,
                    f"INSERT INTO {CASO} (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac) VALUES (%s, 'convite', 'n', 'moda', '\\x01', %s, '\\x02', %s)",
                    (fase, hashlib.sha256(fase.encode()).digest(), hashlib.sha256(b"p" + fase.encode()).digest()),
                )

    def test_o_preflight_e_um_array(self) -> None:
        onboarding_id, _ = caso(self.cursor)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, f"UPDATE {CASO} SET preflight = '{{}}'::jsonb WHERE id = %s", (onboarding_id,))
        self.cursor.execute(f"UPDATE {CASO} SET preflight = '[]'::jsonb WHERE id = %s", (onboarding_id,))


class TestVerificacao(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()
        self.caso, self.tenant = caso(self.cursor)

    def test_o_mesmo_ficheiro_no_mesmo_caso_e_uma_linha(self) -> None:
        soma = hashlib.sha256(b"ficheiro").digest()
        verificacao(self.cursor, self.caso, self.tenant, sha256=soma)
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, self.cursor,
            f"INSERT INTO {KYC} (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, resultado, versao_regras) VALUES (%s, %s, 'bi', %s, %s, 'pendente', '1.0.0')",
            (self.caso, self.tenant, f"t/{self.tenant}/kyc_documento/x", soma),
        )
        outro, outro_tenant = caso(self.cursor)
        verificacao(self.cursor, outro, outro_tenant, sha256=soma)

    def test_o_caso_de_um_com_o_tenant_de_outro_e_recusado(self) -> None:
        _, outro_tenant = caso(self.cursor)
        self.assertErroSql(
            VIOLACAO_DE_FK, self.cursor,
            f"INSERT INTO {KYC} (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, resultado, versao_regras) VALUES (%s, %s, 'bi', %s, %s, 'pendente', '1.0.0')",
            (self.caso, outro_tenant, f"t/{outro_tenant}/kyc_documento/x", b"\x00" * 32),
        )

    def test_o_doc_ref_tem_de_ser_do_tenant_da_linha(self) -> None:
        _, outro_tenant = caso(self.cursor)
        for ref in (f"t/{outro_tenant}/kyc_documento/x", f"t/{self.tenant}/media/x", "https://exemplo/x"):
            with self.subTest(ref=ref):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.cursor,
                    f"INSERT INTO {KYC} (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, resultado, versao_regras) VALUES (%s, %s, 'bi', %s, %s, 'pendente', '1.0.0')",
                    (self.caso, self.tenant, ref, hashlib.sha256(ref.encode()).digest()),
                )

    def test_dominios_e_formas(self) -> None:
        casos = {
            "flags": (["aprovar"],),
            "resultado": ("rejeitado",),
            "doc_tipo": ("passaporte",),
            "versao_regras": ("1.0",),
            "phash": (b"\x00" * 7,),
            "score": (-1,),
            "custo_micro_usd": (-1,),
        }
        for coluna, (valor,) in casos.items():
            with self.subTest(coluna=coluna):
                self.cursor.execute("SAVEPOINT dominio")
                try:
                    with self.assertRaises(Exception) as erro:
                        verificacao(self.cursor, self.caso, self.tenant, **{coluna: valor})
                    self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
                finally:
                    self.cursor.execute("ROLLBACK TO SAVEPOINT dominio")


class TestSqlDoModulo(ComBase):
    """O SQL de `packages/core-ts/src/kyc/sql.ts`, como `kamba_batch`."""

    def setUp(self) -> None:
        super().setUp()
        admin = self.ligar("admin")
        self.admin = admin.cursor()
        self.caso, self.tenant = caso(self.admin)
        self.outro, self.outro_tenant = caso(self.admin)
        admin.commit()
        self.addCleanup(self._limpar)
        self.lote = self.ligar("batch").cursor()

    def _limpar(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(f"DELETE FROM {KYC} WHERE onboarding_id IN (%s, %s)", (self.caso, self.outro))
            cursor.execute(f"DELETE FROM {CASO} WHERE id IN (%s, %s)", (self.caso, self.outro))
            conexao.commit()
        finally:
            conexao.close()

    def _inserir(self, onboarding_id: str, tenant_id: str, soma: bytes, phash: bytes | None):
        q = ConsultaDoTypeScript("SQL_INSERIR", SQL_TS)
        self.lote.execute(
            q.sql,
            q.args(onboarding_id, "bi", f"t/{tenant_id}/kyc_documento/2026/11/{uuid.uuid4()}", soma, phash, b"cifrado", ["software_de_edicao"], "pendente", "1.0.0", 30000),
        )
        return self.lote.fetchall()

    def test_a_insercao_e_idempotente_e_o_tenant_vem_do_caso(self) -> None:
        soma = hashlib.sha256(b"a").digest()
        primeira = self._inserir(self.caso, self.tenant, soma, None)
        self.assertEqual(len(primeira), 1)
        self.assertEqual(str(primeira[0][2]), self.tenant)
        self.assertEqual(len(self._inserir(self.caso, self.tenant, soma, None)), 0, "o conflito nao devolve linha")
        q = ConsultaDoTypeScript("SQL_POR_SHA", SQL_TS)
        self.lote.execute(q.sql, q.args(self.caso, soma))
        self.assertEqual(len(self.lote.fetchall()), 1)

    def test_o_phash_e_procurado_noutros_casos_com_fronteira_em_6(self) -> None:
        base = 0x0123456789ABCDEF
        self._inserir(self.outro, self.outro_tenant, hashlib.sha256(b"o").digest(), base.to_bytes(8, "big"))
        q = ConsultaDoTypeScript("SQL_PHASH_NOUTRO_CASO", SQL_TS)
        seis = (base ^ 0b111111).to_bytes(8, "big")
        sete = (base ^ 0b1111111).to_bytes(8, "big")
        self.lote.execute(q.sql, q.args(self.caso, seis, 6))
        self.assertTrue(self.lote.fetchone()[0], "Hamming 6 e a mesma imagem")
        self.lote.execute(q.sql, q.args(self.caso, sete, 6))
        self.assertFalse(self.lote.fetchone()[0], "Hamming 7 ja nao e")
        self.lote.execute(q.sql, q.args(self.outro, seis, 6))
        self.assertFalse(self.lote.fetchone()[0], "o proprio caso nao conta")

    def test_decidir_custo_e_esquecer(self) -> None:
        a = self._inserir(self.caso, self.tenant, hashlib.sha256(b"1").digest(), None)[0][0]
        b = self._inserir(self.caso, self.tenant, hashlib.sha256(b"2").digest(), None)[0][0]
        q = ConsultaDoTypeScript("SQL_DECIDIR", SQL_TS)
        self.lote.execute(q.sql, q.args([str(a), str(b)], "fila", 40))
        self.lote.execute(f"SELECT resultado, score, flags FROM {KYC} WHERE onboarding_id = %s", (self.caso,))
        # As `flags` ficam as do ficheiro: a decisao nao as reescreve (achado A1).
        self.assertEqual({tuple(map(str, l)) for l in self.lote.fetchall()}, {("fila", "40", "['software_de_edicao']")})
        q = ConsultaDoTypeScript("SQL_CUSTO_DO_CASO", SQL_TS)
        self.lote.execute(q.sql, q.args(self.caso))
        self.assertEqual(int(self.lote.fetchone()[0]), 60000)
        q = ConsultaDoTypeScript("SQL_ESQUECER", SQL_TS)
        self.lote.execute(q.sql, q.args([str(a)]))
        self.lote.execute(f"SELECT count(*) FROM {KYC} WHERE onboarding_id = %s AND extraido_enc IS NULL", (self.caso,))
        self.assertEqual(self.lote.fetchone()[0], 1)

    def test_os_mortos_ate_o_limite(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(f"UPDATE {CASO} SET fase = 'rejeitado' WHERE id = %s", (self.caso,))
            c.execute(f"SELECT fase_at FROM {CASO} WHERE id = %s", (self.caso,))
            instante = c.fetchone()[0]
            conexao.commit()
        finally:
            conexao.close()
        q = ConsultaDoTypeScript("SQL_MORTOS_ATE", SQL_TS)
        self.lote.execute("SELECT %s::timestamptz - interval '1 microsecond'", (instante,))
        antes = self.lote.fetchone()[0]
        self.lote.execute(q.sql, q.args(antes))
        self.assertNotIn(self.caso, [str(l[0]) for l in self.lote.fetchall()])
        self.lote.execute(q.sql, q.args(instante))
        self.assertIn(self.caso, [str(l[0]) for l in self.lote.fetchall()])

    def test_abandonado_tambem_e_morto_e_cancelado_nao(self) -> None:
        """As duas fases do criterio 10, no SQL e nao so no duplo (achado A6).

        O `cancelado` fica de fora pela letra do criterio, que nomeia duas; e
        a compensacao da saga (KAM-091), com retencao por decidir.
        """
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(f"UPDATE {CASO} SET fase = 'abandonado' WHERE id = %s", (self.caso,))
            c.execute(f"UPDATE {CASO} SET fase = 'cancelado' WHERE id = %s", (self.outro,))
            conexao.commit()
        finally:
            conexao.close()
        q = ConsultaDoTypeScript("SQL_MORTOS_ATE", SQL_TS)
        self.lote.execute(q.sql, q.args("2999-01-01T00:00:00Z"))
        mortos = [str(l[0]) for l in self.lote.fetchall()]
        self.assertIn(self.caso, mortos)
        self.assertNotIn(self.outro, mortos)


class TestPrivilegiosERls(unittest.TestCase):
    """Com ligacoes que confirmam: a pergunta e o que **outra** sessao ve."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    def test_quem_pode_o_que(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            esperado = {
                ("kamba_app", KYC, "INSERT"): False,
                ("kamba_app", KYC, "UPDATE"): False,
                ("kamba_app", KYC, "SELECT"): False,
                ("kamba_batch", KYC, "INSERT"): True,
                ("kamba_batch", KYC, "DELETE"): False,
                ("kamba_app", CASO, "DELETE"): False,
                ("kamba_batch", CASO, "DELETE"): False,
                ("kamba_batch", CASO, "INSERT"): False,
            }
            for (papel, tabela, privilegio), valor in esperado.items():
                with self.subTest(papel=papel, tabela=tabela, privilegio=privilegio):
                    c.execute("SELECT has_table_privilege(%s, %s, %s)", (papel, tabela, privilegio))
                    self.assertEqual(c.fetchone()[0], valor)
            for papel in ("kamba_app", "kamba_batch"):
                with self.subTest(papel=papel, coluna="fase_at"):
                    c.execute("SELECT has_column_privilege(%s, %s, 'fase_at', 'UPDATE')", (papel, CASO))
                    self.assertFalse(c.fetchone()[0])
            c.execute("SELECT has_column_privilege('kamba_batch', %s, 'tenant_id', 'UPDATE')", (KYC,))
            self.assertFalse(c.fetchone()[0], "o lote nao muda uma verificacao de tenant")
        finally:
            conexao.close()

    def test_um_tenant_nao_ve_o_caso_nem_as_verificacoes_de_outro(self) -> None:
        conexao = ligacao.ligar("admin")
        conexao.autocommit = True
        c = conexao.cursor()
        a, ta = caso(c)
        b, tb = caso(c)
        verificacao(c, a, ta)
        verificacao(c, b, tb)
        try:
            app = ligacao.ligar("app")
            try:
                cursor = app.cursor()
                factories.contexto(cursor, ta)
                cursor.execute(f"SELECT id::text FROM {CASO} WHERE id IN (%s, %s)", (a, b))
                self.assertEqual([l[0] for l in cursor.fetchall()], [a])
                factories.contexto(cursor, None)
                cursor.execute(f"SELECT count(*) FROM {CASO} WHERE id IN (%s, %s)", (a, b))
                self.assertEqual(cursor.fetchone()[0], 0, "sem contexto nao se ve nada")
            finally:
                app.rollback()
                app.close()
            # O `kyc_check` nao se le pela app (o motivo interno e do T&S), pelo
            # que a politica se prova pelo catalogo: a `tenant_iso` com o
            # `tenant_id` nos dois lados, e a RLS ligada e forcada.
            c.execute(
                "SELECT qual, with_check FROM pg_policies WHERE schemaname = 'platform' "
                "AND tablename = 'kyc_check' AND policyname = 'tenant_iso'"
            )
            qual, com_check = c.fetchone()
            self.assertIn("tenant_id", qual)
            self.assertIn("tenant_id", com_check)
            c.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (KYC,))
            self.assertEqual(list(c.fetchone()), [True, True])
        finally:
            c.execute(f"DELETE FROM {KYC} WHERE onboarding_id IN (%s, %s)", (a, b))
            c.execute(f"DELETE FROM {CASO} WHERE id IN (%s, %s)", (a, b))
            conexao.close()


class TestDowngrade(unittest.TestCase):
    """«Migracao reversivel»: desce com linhas e volta a subir."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _existe(self) -> tuple[int, int]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                "AND tablename IN ('onboarding_case', 'kyc_check')"
            )
            tabelas = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'onboarding_case_fase_at'")
            return tabelas, c.fetchone()[0]
        finally:
            conexao.close()

    def test_desce_com_linhas_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            a, ta = caso(c)
            verificacao(c, a, ta)
            conexao.commit()
        finally:
            conexao.close()
        # Para a `0042` e nao `-1`: quem puser uma revisao por cima nao parte isto.
        alembic_ok("downgrade", "0042")
        self.assertEqual(self._existe(), (0, 0))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), (2, 1))


if __name__ == "__main__":
    unittest.main()
