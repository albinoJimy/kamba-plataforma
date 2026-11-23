"""A correlacao entre tenants por comprador, contra a base (KAM-208, revisao `0087`).

As decisoes do fundador de 2026-11-21 (bloco do KAM-208), medidas onde so a
base as prova:

* **D2** — a `platform.contact_xtenant_pseudonym` so a escreve e le o
  `kamba_identity`, no tenant do contexto; o `kamba_app` e o `kamba_batch` nao a
  leem; o lote so a compara pela `ts_compradores_noutra_loja_do_dono`, que
  devolve **so** `(tenant_id, contagem)` e de que so ele tem `EXECUTE`;
* **D3** — pseudonimos de `kid` diferentes nunca se comparam;
* **D4** — o que foi visto antes do instante nao conta, e a purga apaga-o;
* **D5** — «mesmo dono» e o `owner_contact_id` com o mesmo pseudonimo;
* o **ensaio adversarial** do bloco: o anel de tres tenants do mesmo dono a
  comprar entre si da sinal; o mesmo numero em tenants de donos diferentes nao.

O SQL corrido e o do modulo (`packages/core-ts/src/trust/sql.ts`, lido do
ficheiro), e nao uma copia. Os pseudonimos sao octetos aleatorios: a base
nao calcula nada, compara.

**Desce pelo `down_revision` da revisao, lido do ficheiro, e nao por `-1`**: o
numero da `0087` e provisorio.
"""

from __future__ import annotations

import os
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ligacao
from tests import factories
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

RAIZ = Path(__file__).resolve().parents[2]
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "trust" / "sql.ts"
CONSULTAS_DA_IDENTIDADE = RAIZ / "packages" / "core-ts" / "src" / "identity" / "consultas.ts"
VERSOES = RAIZ / "db" / "migrations" / "versions"

TABELA = "platform.contact_xtenant_pseudonym"
COMPARACAO = "platform.ts_compradores_noutra_loja_do_dono(uuid[])"
PURGA = "platform.contact_xtenant_purgar(uuid[], timestamptz)"

AGORA = datetime.now(timezone.utc)
#: O corte da purga, como o lote o passa: 90 dias (D4). As janelas da
#: comparacao sao da funcao, e nao argumento (achado 3 da revisao).
VISTO_DESDE = AGORA - timedelta(days=90)


def _revisao() -> tuple[str, str]:
    """`(revision, down_revision)` desta revisao, lidos do ficheiro."""
    [ficheiro] = list(VERSOES.glob("*_correlacao_entre_tenants.py"))
    texto = ficheiro.read_text(encoding="utf-8")
    revisao = re.search(r'^revision = "(\d{4})"$', texto, re.M)
    abaixo = re.search(r'^down_revision = "(\d{4})"$', texto, re.M)
    assert revisao and abaixo, "a revisao nao declara revision e down_revision"
    return revisao.group(1), abaixo.group(1)


def _identidade(nome: str) -> str:
    """Uma instrucao de `consultas.ts` (concatenada em `"..." +`), pronta para o pg8000.

    **Os `%s` ligam-se pela ordem do texto**, e nao pela numeracao: quem chama
    passa os valores pela ordem em que os `$n` aparecem (o `MARCAR_FUNDIDO` e o
    `DEFINIR_TELEFONE` escrevem o `$3` antes do `$1`).
    """
    texto = CONSULTAS_DA_IDENTIDADE.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} =\s*(.*?);\n", texto, re.S)
    assert achado, nome
    partes = re.findall(r'"((?:[^"\\]|\\.)*)"', achado.group(1))
    return re.sub(r"\$\d+", "%s", "".join(partes))


def _pseudonimo() -> bytes:
    return os.urandom(32)


class Base(ComBase):
    """Uma transaccao do administrador, e os papeis por `SET LOCAL ROLE`."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def como(self, papel: str | None, tenant: str | None = None) -> None:
        self.cursor.execute("RESET ROLE")
        factories.contexto(self.cursor, tenant)
        if papel is not None:
            self.cursor.execute(f"SET LOCAL ROLE {papel}")

    def loja(self, pseudonimo_do_dono: bytes | None, kid: str = "x1") -> str:
        """Um tenant com dono; o dono tem o pseudonimo dado (ou nenhum)."""
        self.como(None)
        tenant = factories.tenant(self.cursor)
        dono = factories.contacto(self.cursor, tenant)
        self.cursor.execute(
            "UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s", (dono, tenant)
        )
        if pseudonimo_do_dono is not None:
            self.pseudonimo(tenant, dono, pseudonimo_do_dono, kid)
        return tenant

    def pseudonimo(self, tenant: str, contacto: str, valor: bytes, kid: str = "x1",
                   visto: datetime | None = None) -> None:
        self.como(None, tenant)
        self.cursor.execute(
            f"INSERT INTO {TABELA} (tenant_id, contact_id, pseudonimo, kid, visto_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tenant, contacto, valor, kid, visto or AGORA),
        )

    def compra(self, tenant: str, pseudonimo: bytes | None, kid: str = "x1",
               paga: datetime | None = None, contacto: str | None = None,
               entregue: datetime | None = None) -> str:
        """Uma encomenda paga (ou so entregue) de um comprador; devolve o contacto."""
        self.como(None, tenant)
        if contacto is None:
            contacto = factories.contacto(self.cursor, tenant)
            if pseudonimo is not None:
                self.pseudonimo(tenant, contacto, pseudonimo, kid)
        self.como(None, tenant)
        if entregue is not None:
            # Uma encomenda nasce sem `entregue_at` (o *trigger* da `0071`, que e
            # `ENABLE ALWAYS` e por isso nao cede ao `session_replication_role`),
            # e o ensaio precisa de uma entregue sem `paga_at` na janela: os
            # *triggers* da tabela ficam de fora so nesta transaccao do
            # administrador, que o `tearDown` desfaz com o resto.
            self.cursor.execute("ALTER TABLE platform.orders_mirror DISABLE TRIGGER USER")
            self.cursor.execute(
                "INSERT INTO platform.orders_mirror (tenant_id, contact_id, intent_key, total_minor, "
                "lines_snapshot, entregue_at, entrega_confirmada_por) "
                "VALUES (%s, %s, %s, 1000, '[]'::jsonb, %s, 'cliente')",
                (tenant, contacto, f"ik-{uuid.uuid4().hex[:12]}", entregue),
            )
            return contacto
        self.cursor.execute(
            "INSERT INTO platform.orders_mirror (tenant_id, contact_id, intent_key, total_minor, "
            "lines_snapshot, paga_at) VALUES (%s, %s, %s, 1000, '[]'::jsonb, %s)",
            (tenant, contacto, f"ik-{uuid.uuid4().hex[:12]}", paga or AGORA - timedelta(days=1)),
        )
        return contacto

    def comparar(self, tenants: list[str], papel: str = "kamba_batch") -> dict[str, int]:
        """A funcao, chamada como o lote a chama, sobre estes tenants."""
        self.como(papel)
        self.cursor.execute(
            "SELECT tenant_id::text, contagem FROM platform.ts_compradores_noutra_loja_do_dono("
            "%s::uuid[])",
            (tenants,),
        )
        return {t: n for t, n in self.cursor.fetchall()}


class TestATabela(Base):
    """D2: so o `kamba_identity`, so no seu tenant, e a forma fechada."""

    def test_a_rls_esta_ligada_e_forcada_com_a_politica(self) -> None:
        self.cursor.execute(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
            "       (SELECT count(*) FROM pg_policies p WHERE p.schemaname = 'platform' "
            "          AND p.tablename = 'contact_xtenant_pseudonym' AND p.policyname = 'tenant_iso') "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'contact_xtenant_pseudonym'"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True, 1))

    def test_so_o_kamba_identity_tem_privilegio_na_tabela(self) -> None:
        papeis = (*sorted(ligacao.PAPEIS.values()), "public")
        for papel in papeis:
            for privilegio in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                with self.subTest(papel=papel, privilegio=privilegio):
                    self.cursor.execute(
                        "SELECT has_table_privilege(%s, %s, %s)", (papel, TABELA, privilegio)
                    )
                    if papel == "kamba_migrator":
                        esperado = True
                    elif papel == "kamba_identity":
                        esperado = privilegio in ("SELECT", "INSERT", "UPDATE", "DELETE")
                    else:
                        esperado = False
                    self.assertEqual(self.cursor.fetchone()[0], esperado)

    def test_o_kamba_app_e_o_kamba_batch_nao_leem_o_pseudonimo(self) -> None:
        tenant = self.loja(_pseudonimo())
        for papel in ("kamba_app", "kamba_batch"):
            with self.subTest(papel=papel):
                self.como(papel, tenant)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, self.cursor, f"SELECT pseudonimo FROM {TABELA}"
                )

    def test_o_kamba_identity_escreve_e_le_so_no_tenant_do_contexto(self) -> None:
        a = self.loja(None)
        b = self.loja(None)
        self.como(None, a)
        contacto_a = factories.contacto(self.cursor, a)
        self.como(None, b)
        contacto_b = factories.contacto(self.cursor, b)
        definir = _identidade("DEFINIR_PSEUDONIMO_SEM_TENANT")
        valor = _pseudonimo()

        self.como("kamba_identity", a)
        self.cursor.execute(definir, (a, contacto_a, valor, "x1", AGORA))
        # A mesma linha outra vez renova e nao duplica: e a resolucao seguinte.
        self.cursor.execute(definir, (a, contacto_a, valor, "x2", AGORA))
        self.cursor.execute(f"SELECT kid FROM {TABELA}")
        self.assertEqual([tuple(x) for x in self.cursor.fetchall()], [("x2",)])
        # Escrever no tenant de outro, com o contexto de A, e recusado pela RLS.
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, definir, (b, contacto_b, valor, "x1", AGORA))

        # Com o contexto de B nao se ve a linha de A.
        self.como("kamba_identity", b)
        self.cursor.execute(f"SELECT count(*) FROM {TABELA}")
        self.assertEqual(self.cursor.fetchone()[0], 0)
        # Sem contexto, zero linhas.
        self.como("kamba_identity", None)
        self.cursor.execute(f"SELECT count(*) FROM {TABELA}")
        self.assertEqual(self.cursor.fetchone()[0], 0)

        # E apaga-o, como a identidade o apaga ao tirar o numero ou apagar o contacto.
        self.como("kamba_identity", a)
        self.cursor.execute(_identidade("APAGAR_PSEUDONIMO_SEM_TENANT"), (a, contacto_a))
        self.cursor.execute(f"SELECT count(*) FROM {TABELA}")
        self.assertEqual(self.cursor.fetchone()[0], 0)

    def test_a_forma_e_fechada(self) -> None:
        tenant = self.loja(None)
        self.como(None, tenant)
        contacto = factories.contacto(self.cursor, tenant)
        sql = f"INSERT INTO {TABELA} (tenant_id, contact_id, pseudonimo, kid) VALUES (%s, %s, %s, %s)"
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, sql, (tenant, contacto, os.urandom(16), "x1"))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, sql, (tenant, contacto, _pseudonimo(), "X 1"))
        # O contacto tem de ser deste tenant (FK composta).
        outro = self.loja(None)
        self.como(None, outro)
        alheio = factories.contacto(self.cursor, outro)
        self.como(None, tenant)
        self.assertErroSql("23503", self.cursor, sql, (tenant, alheio, _pseudonimo(), "x1"))


class TestAFuncao(Base):
    """So o `kamba_batch` a executa, e ela devolve so o tenant e a contagem."""

    def test_so_o_kamba_batch_e_o_dono_executam_as_duas(self) -> None:
        for funcao in (COMPARACAO, PURGA):
            self.cursor.execute(
                "SELECT r.papel FROM unnest(%s::text[]) AS r(papel) "
                " WHERE has_function_privilege(r.papel, %s, 'EXECUTE') ORDER BY 1",
                (list((*sorted(ligacao.PAPEIS.values()), "public")), funcao),
            )
            with self.subTest(funcao=funcao):
                self.assertEqual([x[0] for x in self.cursor.fetchall()], ["kamba_batch", "kamba_migrator"])

    def test_o_kamba_app_nao_a_chama(self) -> None:
        tenant = self.loja(_pseudonimo())
        self.como("kamba_app", tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.cursor,
            "SELECT * FROM platform.ts_compradores_noutra_loja_do_dono(%s::uuid[])",
            ([tenant],),
        )

    def test_devolve_so_duas_colunas_e_repoe_o_contexto(self) -> None:
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x)
        self.compra(b, x)
        self.como("kamba_batch")
        antes = str(uuid.uuid4())
        factories.contexto(self.cursor, antes)
        q = ConsultaDoTypeScript("SQL_COMPRADORES_NOUTRA_LOJA_DO_DONO", SQL_TS)
        self.cursor.execute(q.sql, q.args())
        linhas = [tuple(x) for x in self.cursor.fetchall()]
        self.assertEqual([d[0] for d in self.cursor.description], ["tenant_id", "contagem"])
        self.assertIn((a, 1), linhas)
        self.assertIn((b, 1), linhas)
        for linha in linhas:
            self.assertEqual(len(linha), 2)
            self.assertNotIn(x, linha, "o pseudonimo nunca sai")
        self.cursor.execute("SELECT current_setting('app.tenant_id', true)")
        self.assertEqual(self.cursor.fetchone()[0], antes, "o contexto de quem chama foi reposto")

    def test_as_janelas_nao_sao_argumento(self) -> None:
        """Achado 3: com os instantes do chamador, o lote bissectava uma encomenda."""
        self.cursor.execute(
            "SELECT pg_get_function_identity_arguments('platform.ts_compradores_noutra_loja_do_dono'::regproc)"
        )
        self.assertEqual(self.cursor.fetchone()[0], "p_tenants uuid[]")

    def test_sem_contexto_previo_fica_sem_contexto(self) -> None:
        """Uma ligacao nova, que nunca pos o `app.tenant_id`, sai sem tenant nenhum."""
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x)
        self.compra(b, x)
        self.cursor.execute("RESET ROLE")
        self.cursor.execute("RESET app.tenant_id")
        self.cursor.execute("SET LOCAL ROLE kamba_batch")
        self.cursor.execute(
            "SELECT count(*) FROM platform.ts_compradores_noutra_loja_do_dono(%s::uuid[])", ([a, b],)
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)
        self.cursor.execute("SELECT coalesce(current_setting('app.tenant_id', true), '')")
        self.assertEqual(self.cursor.fetchone()[0], "", "o contexto do ultimo tenant ficou posto")


class TestOAnel(Base):
    """O ensaio adversarial do bloco, e cada fronteira que a funcao promete."""

    def test_o_anel_de_tres_lojas_do_mesmo_dono_da_sinal(self) -> None:
        dono = _pseudonimo()
        a, b, c = self.loja(dono), self.loja(dono), self.loja(dono)
        x, y, z = _pseudonimo(), _pseudonimo(), _pseudonimo()
        # x compra em A e B; y em B e C; z so em C (nao conta).
        self.compra(a, x)
        self.compra(b, x)
        self.compra(b, y)
        self.compra(c, y)
        self.compra(c, z)
        self.assertEqual(self.comparar([a, b, c]), {a: 1, b: 2, c: 1})

    def test_o_mesmo_numero_em_lojas_de_donos_diferentes_nao_da(self) -> None:
        d, e = self.loja(_pseudonimo()), self.loja(_pseudonimo())
        x = _pseudonimo()
        self.compra(d, x)
        self.compra(e, x)
        self.assertEqual(self.comparar([d, e]), {})

    def test_um_dono_sem_pseudonimo_nao_junta_lojas(self) -> None:
        d, e = self.loja(None), self.loja(None)
        x = _pseudonimo()
        self.compra(d, x)
        self.compra(e, x)
        self.assertEqual(self.comparar([d, e]), {})

    def test_kids_diferentes_nunca_se_comparam(self) -> None:
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x, kid="x1")
        self.compra(b, x, kid="x2")
        self.assertEqual(self.comparar([a, b]), {}, "comprador sob kids diferentes")
        c, d = self.loja(dono, kid="x1"), self.loja(dono, kid="x2")
        y = _pseudonimo()
        self.compra(c, y)
        self.compra(d, y)
        self.assertEqual(self.comparar([c, d]), {}, "dono sob kids diferentes")

    def test_compras_fora_da_janela_e_pseudonimos_vencidos_nao_contam(self) -> None:
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x, paga=AGORA - timedelta(days=31))
        self.compra(b, x)
        self.assertEqual(self.comparar([a, b]), {}, "compra fora dos 30 dias")
        c, d = self.loja(dono), self.loja(dono)
        y = _pseudonimo()
        self.compra(c, y)
        self.como(None, d)
        vencido = factories.contacto(self.cursor, d)
        self.pseudonimo(d, vencido, y, visto=AGORA - timedelta(days=91))
        self.compra(d, None, contacto=vencido)
        self.assertEqual(self.comparar([c, d]), {}, "pseudonimo visto ha mais de 90 dias")

    def test_o_comprador_fundido_conta_pelo_contacto_que_ficou(self) -> None:
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x)
        self.como(None, b)
        fica = factories.contacto(self.cursor, b)
        sai = factories.contacto(self.cursor, b)
        self.compra(b, None, contacto=sai)
        self.cursor.execute(
            "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
            "WHERE tenant_id = %s AND contact_id = %s", (fica, b, sai)
        )
        self.pseudonimo(b, fica, x)
        self.assertEqual(self.comparar([a, b]), {a: 1, b: 1})

    def test_uma_encomenda_so_entregue_na_janela_conta(self) -> None:
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x, entregue=AGORA - timedelta(days=2))
        self.compra(b, x)
        self.assertEqual(self.comparar([a, b]), {a: 1, b: 1})

    def test_o_dono_visto_ha_mais_de_90_dias_continua_a_juntar_lojas(self) -> None:
        """O do dono nao vence enquanto ele for dono (decisao do fundador de 2026-11-22, B)."""
        dono = _pseudonimo()
        a = self.loja(dono)
        self.como(None)
        b = factories.tenant(self.cursor)
        velho = factories.contacto(self.cursor, b)
        self.cursor.execute("UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s", (velho, b))
        self.pseudonimo(b, velho, dono, visto=AGORA - timedelta(days=91))
        x = _pseudonimo()
        self.compra(a, x)
        self.compra(b, x)
        self.assertEqual(self.comparar([a, b]), {a: 1, b: 1})

    def test_o_dono_absorvido_numa_fusao_conta_pelo_contacto_que_ficou(self) -> None:
        dono = _pseudonimo()
        a = self.loja(dono)
        self.como(None)
        b = factories.tenant(self.cursor)
        absorvido = factories.contacto(self.cursor, b)
        fica = factories.contacto(self.cursor, b)
        self.cursor.execute("UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s", (absorvido, b))
        self.cursor.execute(
            "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
            "WHERE tenant_id = %s AND contact_id = %s", (fica, b, absorvido)
        )
        self.pseudonimo(b, fica, dono)
        x = _pseudonimo()
        self.compra(a, x)
        self.compra(b, x)
        self.assertEqual(self.comparar([a, b]), {a: 1, b: 1})

    def test_um_tenant_fora_da_lista_nao_entra(self) -> None:
        dono = _pseudonimo()
        a, b = self.loja(dono), self.loja(dono)
        x = _pseudonimo()
        self.compra(a, x)
        self.compra(b, x)
        self.assertEqual(self.comparar([a]), {})


class TestOEsquecimento(Base):
    """D4 na base: o pseudonimo vai quando o contacto perde o numero, e fundido ou e apagado."""

    def contacto_com_numero(self, tenant: str) -> str:
        self.como(None, tenant)
        kid = factories.versao_de_chave(self.cursor)
        contacto = factories.contacto(self.cursor, tenant, phone_hmac=os.urandom(32), hmac_kid=kid)
        self.pseudonimo(tenant, contacto, _pseudonimo())
        return contacto

    def resta(self, tenant: str, contacto: str) -> bool:
        self.como(None, tenant)
        self.cursor.execute(f"SELECT count(*) FROM {TABELA} WHERE contact_id = %s", (contacto,))
        return self.cursor.fetchone()[0] == 1

    def test_apagar_fundir_ou_tirar_o_numero_leva_o_pseudonimo(self) -> None:
        tenant = self.loja(None)
        for nome, sql in (
            ("apagar", _identidade("MARCAR_APAGADO")),
            ("tirar o numero", _identidade("LIMPAR_TELEFONE")),
        ):
            with self.subTest(caminho=nome):
                contacto = self.contacto_com_numero(tenant)
                self.como("kamba_identity", tenant)
                self.cursor.execute(sql, (tenant, contacto))
                self.assertFalse(self.resta(tenant, contacto))
        fica = self.contacto_com_numero(tenant)
        sai = self.contacto_com_numero(tenant)
        self.como("kamba_identity", tenant)
        # Pela ordem do texto, que e a do pg8000: `merged_into = $3` vem antes do
        # `tenant_id = $1 AND contact_id = $2`.
        self.cursor.execute(_identidade("MARCAR_FUNDIDO"), (fica, tenant, sai))
        self.assertFalse(self.resta(tenant, sai), "o absorvido perde o pseudonimo")
        self.assertTrue(self.resta(tenant, fica), "quem fica nao perde o seu")

    def test_trocar_o_hmac_por_outro_nao_o_leva(self) -> None:
        """A rotacao e o numero novo sobem o `phone_hmac`; o pseudonimo e da resolucao."""
        tenant = self.loja(None)
        contacto = self.contacto_com_numero(tenant)
        self.como("kamba_identity", tenant)
        # Pela ordem do texto: `phone_hmac = $3, hmac_kid = $4` antes do `WHERE`.
        self.cursor.execute(
            _identidade("DEFINIR_TELEFONE"), (os.urandom(32), factories.KID_DE_TESTE, tenant, contacto)
        )
        self.assertTrue(self.resta(tenant, contacto))

    def test_a_purga_do_cofre_no_encerramento_leva_os_do_tenant_e_nao_os_de_outro(self) -> None:
        import sys

        nucleo = str(RAIZ / "libs" / "py-core" / "src")
        if nucleo not in sys.path:
            sys.path.insert(0, nucleo)
        from kamba_core.offboarding.cofre import SQL_MARCAR_APAGADOS

        a, b = self.loja(None), self.loja(None)
        de_a, de_b = self.contacto_com_numero(a), self.contacto_com_numero(b)
        self.como("kamba_identity", a)
        self.cursor.execute(SQL_MARCAR_APAGADOS, (a,))
        self.assertFalse(self.resta(a, de_a))
        self.assertTrue(self.resta(b, de_b), "o encerramento de A nao toca em B")


class TestAPurga(Base):
    """D4: apaga os vistos antes do instante, so esses, e diz quantos."""

    def test_apaga_os_vencidos_e_deixa_os_vivos(self) -> None:
        a = self.loja(None)
        self.como(None, a)
        velho, novo = factories.contacto(self.cursor, a), factories.contacto(self.cursor, a)
        self.pseudonimo(a, velho, _pseudonimo(), visto=AGORA - timedelta(days=91))
        self.pseudonimo(a, novo, _pseudonimo(), visto=AGORA - timedelta(days=89))
        self.como("kamba_batch")
        q = ConsultaDoTypeScript("SQL_PURGAR_PSEUDONIMOS", SQL_TS)
        self.cursor.execute(q.sql, q.args(VISTO_DESDE))
        apagados = self.cursor.fetchone()[0]
        self.assertGreaterEqual(apagados, 1)
        self.como(None, a)
        self.cursor.execute(f"SELECT contact_id::text FROM {TABELA}")
        self.assertEqual([x[0] for x in self.cursor.fetchall()], [novo])

    def test_o_dono_nao_vence_e_depois_da_troca_de_dono_o_antigo_passa_a_vencer(self) -> None:
        """Opcao B de 2026-11-22: enquanto for dono, a purga nao o leva; na troca, volta aos 90 dias."""
        a = self.loja(None)
        self.como(None, a)
        [antigo] = [x[0] for x in self.consultar_dono(a)]
        self.pseudonimo(a, antigo, _pseudonimo(), visto=AGORA - timedelta(days=200))
        q = ConsultaDoTypeScript("SQL_PURGAR_PSEUDONIMOS", SQL_TS)
        self.como("kamba_batch")
        self.cursor.execute(q.sql, q.args(VISTO_DESDE))
        self.assertTrue(self._existe(a, antigo), "o dono venceu sendo dono")

        self.como(None, a)
        novo = factories.contacto(self.cursor, a)
        self.cursor.execute("UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s", (novo, a))
        self.como("kamba_batch")
        self.cursor.execute(q.sql, q.args(VISTO_DESDE))
        self.assertFalse(self._existe(a, antigo), "o antigo dono nao voltou aos 90 dias")

    def consultar_dono(self, tenant: str):
        self.como(None, tenant)
        self.cursor.execute("SELECT owner_contact_id::text FROM platform.tenants WHERE id = %s", (tenant,))
        return self.cursor.fetchall()

    def _existe(self, tenant: str, contacto: str) -> bool:
        self.como(None, tenant)
        self.cursor.execute(f"SELECT count(*) FROM {TABELA} WHERE contact_id = %s", (contacto,))
        return self.cursor.fetchone()[0] == 1

    def test_o_kamba_app_nao_purga(self) -> None:
        self.como("kamba_app")
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.cursor,
            "SELECT platform.contact_xtenant_purgar('{}'::uuid[], %s)", (AGORA,),
        )


class TestDowngradeDaCorrelacao(unittest.TestCase):
    """O `downgrade` recusa com um sinal do tipo novo, e sem ele desce e volta."""

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

    def _existe(self) -> tuple[bool, int, bool]:
        c = self._admin().cursor()
        c.execute(
            "SELECT to_regclass('platform.contact_xtenant_pseudonym') IS NOT NULL, "
            "       (SELECT count(*) FROM pg_proc WHERE proname IN "
            "          ('ts_compradores_noutra_loja_do_dono', 'contact_xtenant_purgar')), "
            "       (SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "         WHERE conname = 'ts_signal_tipo_ck') LIKE '%comprador_noutra_loja_do_dono%'"
        )
        return tuple(c.fetchone())

    def test_com_um_sinal_recusa_e_sem_ele_desce_e_volta(self) -> None:
        revisao, abaixo = _revisao()
        conexao = self._admin()
        c = conexao.cursor()
        tenant = factories.tenant(c)
        c.execute(
            "INSERT INTO platform.ts_signal (tenant_id, tipo, severidade, ref_evento, ocorrido_em) "
            "VALUES (%s, 'comprador_noutra_loja_do_dono', 'baixa', %s, now())",
            (tenant, str(uuid.uuid4())),
        )
        conexao.commit()
        try:
            resultado = alembic("downgrade", abaixo)
            self.assertNotEqual(resultado.returncode, 0, "o downgrade devia recusar")
            self.assertIn(f"downgrade da {revisao} recusado", resultado.stderr)
            self.assertEqual(self._existe(), (True, 2, True), "ficou tudo, com o sinal")
        finally:
            if not em_head():
                alembic_ok("upgrade", "head")
            # A `ts_signal` e append-only: tira-se o sinal de ensaio com os
            # *triggers* desligados, como administrador, e repoem-se. Os dois
            # da `0056` sao `ENABLE` simples (nenhum `ALWAYS`), e e essa a forma
            # em que voltam.
            c.execute("ALTER TABLE platform.ts_signal DISABLE TRIGGER USER")
            c.execute("DELETE FROM platform.ts_signal WHERE tenant_id = %s", (tenant,))
            c.execute("ALTER TABLE platform.ts_signal ENABLE TRIGGER USER")
            factories.contexto(c, tenant)
            c.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
            conexao.commit()
        alembic_ok("downgrade", abaixo)
        try:
            self.assertEqual(self._existe(), (False, 0, False))
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), (True, 2, True))


if __name__ == "__main__":
    unittest.main()
