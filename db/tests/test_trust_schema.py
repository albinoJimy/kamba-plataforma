"""A revisao de Trust & Safety contra a base: ts_signal e ts_sanction (KAM-097).

O que so uma base prova, e por isso este ficheiro existe:

1. **As listas fechadas sao as do codigo**: os tipos, a severidade fixa por
   tipo, as chaves do `detalhe`, os passos e os motivos publicos contra o
   `packages/core-ts/src/trust/`.
2. **Append-only**: ninguem emenda nem apaga um sinal ou uma sancao, nem o
   administrador (o *trigger*).
3. **A escada na base**: a suspensao e o encerramento so humanos e com caso, o
   salto sem justificacao recusado, e o `kamba_app` sem linhas humanas nem
   desfechos de recurso (o unico abuso com ganho: levantar a propria sancao).
4. **Privilegios e RLS**: o `kamba_app` le o passo e nao a heuristica; um tenant
   nao ve nem escreve os sinais de outro.
5. **O SQL do modulo de TypeScript**, tal como esta escrito: cada constante
   planeada pelo papel que a corre (o `EXPLAIN` verifica as colunas **e** os
   privilegios), e as que decidem alguma coisa executadas.
6. **O `downgrade`.**

Os papeis medem-se com `SET LOCAL ROLE` na transaccao do administrador, que
semeia e nunca confirma: o que o ensaio escreve desaparece com ele.
"""

from __future__ import annotations

import ast
import json
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
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "packages" / "core-ts" / "src" / "trust"
REGRAS = MODULO / "regras.ts"
CONTRATO = MODULO / "contrato.ts"
SQL_TS = MODULO / "sql.ts"

SINAL = "platform.ts_signal"
SANCAO = "platform.ts_sanction"
RECUSADO_PELO_TRIGGER = "55000"
AGORA = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def _lista(ficheiro: Path, nome: str) -> tuple[str, ...]:
    texto = ficheiro.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {ficheiro.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def _severidades_ts() -> dict[str, str]:
    texto = REGRAS.read_text(encoding="utf-8")
    bloco = re.search(r"export const SEVERIDADE_DO_TIPO[^=]*= \{(.*?)\n\};", texto, re.S)
    if bloco is None:
        raise AssertionError("SEVERIDADE_DO_TIPO nao encontrada")
    return dict(re.findall(r'(\w+): "(\w+)"', bloco.group(1)))


def _revisao() -> tuple[str, str]:
    """O numero desta revisao e o da anterior, pelo ficheiro: o numero e provisorio."""
    achadas = sorted((RAIZ / "db" / "migrations" / "versions").glob("*_trust_e_sancoes.py"))
    assert len(achadas) == 1, achadas
    arvore = ast.parse(achadas[0].read_text(encoding="utf-8"))
    valores = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Name):
            if no.targets[0].id in ("revision", "down_revision"):
                valores[no.targets[0].id] = ast.literal_eval(no.value)
    return valores["revision"], valores["down_revision"]


def _caso(cursor, tenant_id: str, tipo: str = "trust") -> str:
    """Um `review_case` minimo, como o lote o abriria."""
    cursor.execute(
        "INSERT INTO platform.review_case (tipo, tenant_id, motivo_codigo, motivo_interno, "
        " motivo_publico, recomendacao, sla_alerta_at, sla_due_at) "
        "VALUES (%s, %s, %s, 'auto-compra repetida', 'nao_foi_possivel_validar', 'rejeitar', "
        " now() + interval '19 hours', now() + interval '24 hours') RETURNING id::text",
        (tipo, tenant_id, f"sancao_suspensao:{uuid.uuid4().hex[:12]}"),
    )
    return cursor.fetchone()[0]


class Base(ComBase):
    """Uma transaccao do administrador com um tenant, e os papeis por `SET LOCAL ROLE`."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.cursor)

    def como(self, papel: str | None, tenant: str | None = None) -> None:
        self.cursor.execute("RESET ROLE")
        factories.contexto(self.cursor, tenant)
        if papel is not None:
            self.cursor.execute(f"SET LOCAL ROLE {papel}")

    def sinal(self, tipo: str = "auto_compra", severidade: str = "alta", ref: str | None = None,
              detalhe: dict | None = None, tenant: str | None = None):
        q = ConsultaDoTypeScript("SQL_GRAVAR_SINAL", SQL_TS)
        self.cursor.execute(q.sql, q.args(
            tenant or self.tenant, tipo, severidade, ref or str(uuid.uuid4()),
            json.dumps(detalhe or {}), AGORA,
        ))
        return list(self.cursor.fetchall())

    def sancao(self, **campos):
        valores = {
            "tenant_id": self.tenant,
            "chave": f"auto:aviso:{uuid.uuid4()}",
            "passo": "aviso",
            "origem": "automatica",
            "motivo_interno": "risco=35;limiar=30",
            "motivo_publico": "conduta_em_analise",
            "autor": "sistema:1.0.0",
            "regra": "risco_ts>=30",
            "sinais": "[]",
            "case_id": None,
            "justificacao_salto": None,
            "recurso_de": None,
            "recurso_estado": None,
        }
        valores.update(campos)
        q = ConsultaDoTypeScript("SQL_GRAVAR_SANCAO", SQL_TS)
        return q.sql, q.args(*valores.values())


class TestDominios(ComBase):
    def test_as_listas_fechadas_sao_as_do_modulo(self) -> None:
        cursor = self.ligar("admin").cursor()
        for restricao, ficheiro, lista in (
            ("ts_signal_tipo_ck", REGRAS, "TIPOS_DE_SINAL"),
            ("ts_signal_severidade_dominio_ck", REGRAS, "SEVERIDADES"),
            ("ts_sanction_passo_ck", REGRAS, "PASSOS"),
            ("ts_sanction_origem_ck", CONTRATO, "ORIGENS"),
            ("ts_sanction_motivo_publico_ck", CONTRATO, "MOTIVOS_PUBLICOS_DA_SANCAO"),
            ("ts_sanction_recurso_estado_ck", CONTRATO, "DESFECHOS_DO_RECURSO"),
            ("ts_signal_detalhe_ck", CONTRATO, "CHAVES_DO_DETALHE"),
        ):
            with self.subTest(restricao=restricao):
                cursor.execute(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
                    (restricao,),
                )
                definicao = cursor.fetchone()[0]
                achados = set(re.findall(r"'([a-z0-9_]+)'", definicao)) - {"object"}
                self.assertEqual(achados, set(_lista(ficheiro, lista)))

    def test_a_severidade_da_base_e_a_do_modulo_tipo_a_tipo(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = factories.tenant(cursor)
        for tipo, severidade in _severidades_ts().items():
            for tentada in ("baixa", "media", "alta"):
                with self.subTest(tipo=tipo, severidade=tentada):
                    q = ConsultaDoTypeScript("SQL_GRAVAR_SINAL", SQL_TS)
                    sql, args = q.sql, q.args(tenant, tipo, tentada, str(uuid.uuid4()), "{}", AGORA)
                    if tentada == severidade:
                        cursor.execute(sql, args)
                        self.assertEqual(len(cursor.fetchall()), 1)
                    else:
                        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)


class TestSinais(Base):
    def test_a_aplicacao_grava_no_seu_tenant_e_a_reentrega_nao_grava_segundo(self) -> None:
        self.como("kamba_app", self.tenant)
        ref = str(uuid.uuid4())
        self.assertEqual(len(self.sinal(ref=ref)), 1)
        self.assertEqual(self.sinal(ref=ref), [], "a mesma chave: zero linhas, e nao erro")
        q = ConsultaDoTypeScript("SQL_SINAL_POR_CHAVE", SQL_TS)
        self.cursor.execute(q.sql, q.args(self.tenant, "auto_compra", ref))
        self.assertEqual(len(self.cursor.fetchall()), 1)

    def test_o_detalhe_so_leva_chaves_de_referencia(self) -> None:
        self.como("kamba_app", self.tenant)
        q = ConsultaDoTypeScript("SQL_GRAVAR_SINAL", SQL_TS)
        for detalhe in ({"telefone": "x"}, {"order_id": "a", "nome": "b"}, []):
            with self.subTest(detalhe=detalhe):
                self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, q.sql, q.args(
                    self.tenant, "auto_compra", "alta", str(uuid.uuid4()), json.dumps(detalhe), AGORA))
        self.assertEqual(len(self.sinal(detalhe={"order_id": "a", "coincidencia": "contact_id"})), 1)

    def test_ninguem_emenda_nem_apaga_um_sinal(self) -> None:
        self.sinal()
        self.assertErroSql(RECUSADO_PELO_TRIGGER, self.cursor, f"UPDATE {SINAL} SET severidade = 'alta'")
        self.assertErroSql(RECUSADO_PELO_TRIGGER, self.cursor, f"DELETE FROM {SINAL}")
        for papel in ("kamba_app", "kamba_batch"):
            with self.subTest(papel=papel):
                self.como(papel, self.tenant)
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, f"DELETE FROM {SINAL}")
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor,
                                   f"UPDATE {SINAL} SET ocorrido_em = now()")


class TestEscadaNaBase(Base):
    def test_a_aplicacao_escreve_avisos_automaticos_e_nada_humano(self) -> None:
        caso = _caso(self.cursor, self.tenant)
        self.como("kamba_app", self.tenant)
        sql, args = self.sancao()
        self.cursor.execute(sql, args)
        aviso = self.cursor.fetchone()[0]
        for campos in (
            {"origem": "humana", "case_id": caso, "autor": str(uuid.uuid4()), "chave": f"caso:{caso}"},
            {"origem": "humana", "case_id": caso, "autor": str(uuid.uuid4()), "chave": f"recurso:{aviso}",
             "recurso_de": aviso, "recurso_estado": "provido", "motivo_publico": "recurso_aceite"},
        ):
            with self.subTest(campos=sorted(campos)):
                sql, args = self.sancao(**campos)
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, sql, args)

    def test_a_suspensao_e_o_encerramento_nunca_sao_automaticos(self) -> None:
        self.como("kamba_batch")
        for passo in ("suspensao", "encerramento"):
            with self.subTest(passo=passo):
                sql, args = self.sancao(passo=passo, chave=f"auto:{passo}:x", justificacao_salto="x")
                self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, sql, args)

    def test_a_humana_leva_caso_e_o_salto_leva_justificacao(self) -> None:
        caso = _caso(self.cursor, self.tenant)
        revisor = str(uuid.uuid4())
        self.como("kamba_batch")
        sem_caso = self.sancao(origem="humana", passo="aviso", autor=revisor, chave="caso:x")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, *sem_caso)
        salto = self.sancao(origem="humana", passo="suspensao", case_id=caso, autor=revisor,
                            chave=f"caso:{caso}", motivo_publico="loja_suspensa")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, *salto)
        com = self.sancao(origem="humana", passo="suspensao", case_id=caso, autor=revisor,
                          chave=f"caso:{caso}", motivo_publico="loja_suspensa",
                          justificacao_salto="venda de produto proibido provada")
        self.cursor.execute(*com)
        self.assertEqual(len(self.cursor.fetchall()), 1)

    def test_um_degrau_de_cada_vez_nao_e_salto(self) -> None:
        caso = _caso(self.cursor, self.tenant)
        self.como("kamba_batch")
        self.cursor.execute(*self.sancao(chave="auto:aviso:1"))
        self.cursor.execute(*self.sancao(chave="auto:limitacao:1", passo="limitacao",
                                         motivo_publico="actividade_limitada"))
        self.cursor.execute(*self.sancao(origem="humana", passo="suspensao", case_id=caso,
                                         autor=str(uuid.uuid4()), chave=f"caso:{caso}",
                                         motivo_publico="loja_suspensa"))
        self.assertEqual(len(self.cursor.fetchall()), 1)

    def test_um_recurso_provido_baixa_o_passo_em_vigor(self) -> None:
        caso = _caso(self.cursor, self.tenant, tipo="recurso")
        self.como("kamba_batch")
        self.cursor.execute(*self.sancao(chave="auto:aviso:1"))
        aviso = self.cursor.fetchone()[0]
        self.cursor.execute(*self.sancao(chave="auto:limitacao:1", passo="limitacao",
                                         motivo_publico="actividade_limitada"))
        limitacao = self.cursor.fetchone()[0]
        recurso = self.sancao(origem="humana", passo="limitacao", case_id=caso,
                              autor=str(uuid.uuid4()), chave=f"recurso:{limitacao}",
                              recurso_de=limitacao, recurso_estado="provido",
                              motivo_publico="recurso_aceite")
        self.cursor.execute(*recurso)
        self.assertEqual(len(self.cursor.fetchall()), 1)
        self.cursor.execute(*recurso)
        self.assertEqual(list(self.cursor.fetchall()), [], "o recurso e unico por sancao")
        # Com a limitacao levantada, so o aviso esta em vigor: uma suspensao e salto.
        caso2 = _caso(self.cursor, self.tenant)
        salto = self.sancao(origem="humana", passo="suspensao", case_id=caso2,
                            autor=str(uuid.uuid4()), chave=f"caso:{caso2}",
                            motivo_publico="loja_suspensa")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, *salto)
        self.assertTrue(aviso)

    def test_ninguem_emenda_nem_apaga_uma_sancao(self) -> None:
        self.cursor.execute(*self.sancao())
        self.assertErroSql(RECUSADO_PELO_TRIGGER, self.cursor, f"UPDATE {SANCAO} SET passo = 'limitacao'")
        self.assertErroSql(RECUSADO_PELO_TRIGGER, self.cursor, f"DELETE FROM {SANCAO}")
        self.como("kamba_batch")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, f"UPDATE {SANCAO} SET passo = 'aviso'")

    def test_o_caso_da_sancao_e_do_mesmo_tenant(self) -> None:
        outro = factories.tenant(self.cursor)
        caso = _caso(self.cursor, outro)
        self.como("kamba_batch")
        sql, args = self.sancao(origem="humana", case_id=caso, autor=str(uuid.uuid4()), chave=f"caso:{caso}")
        self.assertErroSql("23503", self.cursor, sql, args)


class TestAchadosDaRevisao(Base):
    """Os achados da revisao adversarial que so a base prova."""

    def test_a_chave_e_o_autor_estao_presos_a_origem(self) -> None:
        """Achado 8 e mutacao M9: o `kamba_app` nao ocupa a chave de um recurso."""
        caso = _caso(self.cursor, self.tenant)
        self.como("kamba_batch")
        self.cursor.execute(*self.sancao(chave="auto:aviso:1"))
        aviso = self.cursor.fetchone()[0]
        for nome, campos in (
            ("automatica com chave de recurso", {"chave": f"recurso:{aviso}"}),
            ("automatica com chave de caso", {"chave": f"caso:{caso}"}),
            ("automatica com autor de pessoa", {"autor": str(uuid.uuid4())}),
            ("automatica com recurso", {"chave": f"recurso:{aviso}", "recurso_de": aviso,
                                        "recurso_estado": "provido"}),
            ("humana com autor de sistema", {"origem": "humana", "case_id": caso,
                                             "chave": f"caso:{caso}"}),
            ("humana com chave de outro caso", {"origem": "humana", "case_id": caso,
                                                "autor": str(uuid.uuid4()), "chave": "caso:outro"}),
        ):
            with self.subTest(nome):
                self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, *self.sancao(**campos))
        self.como("kamba_app", self.tenant)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, *self.sancao(chave=f"recurso:{aviso}"))

    def test_o_instante_de_um_sinal_nao_se_recua_nem_se_adianta(self) -> None:
        """Achado 1: um sinal datado de 2000 pesava zero no risco."""
        self.como("kamba_app", self.tenant)
        q = ConsultaDoTypeScript("SQL_GRAVAR_SINAL", SQL_TS)
        for instante in (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc)):
            ref = str(uuid.uuid4())
            self.cursor.execute(q.sql, q.args(self.tenant, "auto_compra", "alta", ref, "{}", instante))
            self.cursor.execute(
                "SELECT ocorrido_em BETWEEN now() - interval '1 day' AND now() "
                f"FROM {SINAL} WHERE ref_evento = %s", (ref,))
            with self.subTest(instante=instante.year):
                self.assertIs(self.cursor.fetchone()[0], True)

    def test_a_aplicacao_nao_mexe_no_dono_e_os_confirmadores_dono_contam(self) -> None:
        """Achado 9 e mutacao M10."""
        self.como("kamba_app", self.tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor,
                           "UPDATE platform.tenants SET owner_contact_id = NULL WHERE id = %s",
                           (self.tenant,))
        self.como(None, self.tenant)
        dono = factories.contacto(self.cursor, self.tenant)
        funcionario = factories.contacto(self.cursor, self.tenant)
        for contacto, papel in ((dono, "dono"), (funcionario, "funcionario")):
            self.cursor.execute(
                "INSERT INTO platform.payment_confirmers (tenant_id, contact_id, papel) "
                "VALUES (%s, %s, %s)", (self.tenant, contacto, papel))
        self.como("kamba_app", self.tenant)
        q = ConsultaDoTypeScript("SQL_CONTACTOS_DO_DONO", SQL_TS)
        self.cursor.execute(q.sql, q.args(self.tenant))
        self.assertEqual({str(c) for (c,) in self.cursor.fetchall()}, {dono})

    def test_a_independencia_avaliada_e_sem_auto_compra_e_independente(self) -> None:
        """Mutacao M11: o caso positivo da independencia, e so com o `order.paid`."""
        pedido = str(uuid.uuid4())
        for tipo in ("order.created", "order.paid"):
            evento = str(uuid.uuid4())
            self.cursor.execute(
                "INSERT INTO platform.events_log (event_id, tipo, versao, tenant_id, agregado_tipo, "
                " agregado_id, agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
                "VALUES (%s, %s, 1, %s, 'order', %s, 1, now(), now(), 'P0', '{}')",
                (evento, tipo, self.tenant, pedido))
            self.cursor.execute(
                "INSERT INTO platform.events_consumed (consumer, event_id, tenant_id, agregado_tipo, "
                " agregado_id, agregado_seq) VALUES ('trust', %s, %s, 'order', %s, 1)",
                (evento, self.tenant, pedido))
            self.como("kamba_app", self.tenant)
            q = ConsultaDoTypeScript("SQL_INDEPENDENCIA", SQL_TS)
            self.cursor.execute(q.sql, q.args(self.tenant, pedido, "trust"))
            with self.subTest(consumido=tipo):
                self.assertEqual(tuple(self.cursor.fetchone()), (False, tipo == "order.paid"))
            self.como(None, self.tenant)

    def test_um_encerramento_em_recurso_nao_fecha(self) -> None:
        """Mutacao M12: o caso em `recurso_aberto` esta a ser recorrido."""
        caso = _caso(self.cursor, self.tenant)
        self.cursor.execute("UPDATE platform.review_case SET estado = 'decidido' WHERE id = %s", (caso,))
        self.cursor.execute("UPDATE platform.review_case SET estado = 'recurso_aberto' WHERE id = %s", (caso,))
        self.como("kamba_batch")
        self.cursor.execute(*self.sancao(origem="humana", passo="encerramento", case_id=caso,
                                         autor=str(uuid.uuid4()), chave=f"caso:{caso}",
                                         motivo_publico="loja_encerrada", justificacao_salto="x"))
        q = ConsultaDoTypeScript("SQL_ENCERRAMENTOS_POR_FECHAR", SQL_TS)
        self.cursor.execute(q.sql, q.args(datetime.now(timezone.utc) + timedelta(days=1)))
        self.assertEqual([l for l in self.cursor.fetchall() if str(l[1]) == self.tenant], [])


class TestPrivilegios(Base):
    def test_a_aplicacao_le_o_passo_e_nao_a_heuristica(self) -> None:
        self.cursor.execute(*self.sancao())
        self.sinal()
        self.como("kamba_app", self.tenant)
        q = ConsultaDoTypeScript("SQL_SANCOES_DO_TENANT_APP", SQL_TS)
        self.cursor.execute(q.sql, q.args(self.tenant))
        self.assertEqual(len(self.cursor.fetchall()), 1)
        for coluna, tabela in (("motivo_interno", SANCAO), ("regra", SANCAO), ("sinais", SANCAO),
                               ("autor", SANCAO), ("detalhe", SINAL)):
            with self.subTest(coluna=coluna):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, f"SELECT {coluna} FROM {tabela}")
        q = ConsultaDoTypeScript("SQL_SANCOES_DO_TENANT_LOTE", SQL_TS)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, q.sql, q.args(self.tenant))

    def test_a_rls_esta_ligada_e_forcada_nas_duas(self) -> None:
        for tabela in ("ts_signal", "ts_sanction"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = %s::regclass", (f"platform.{tabela}",))
                self.assertEqual(tuple(self.cursor.fetchone()), (True, True))


class TestIsolamento(Base):
    """O teste cruzado do ADR-015, pela ligacao da aplicacao."""

    def test_um_tenant_nao_ve_nem_escreve_os_sinais_e_sancoes_de_outro(self) -> None:
        b = factories.tenant(self.cursor)
        self.como("kamba_app", self.tenant)
        self.sinal()
        self.cursor.execute(*self.sancao())
        self.como("kamba_app", b)
        for tabela in (SINAL, SANCAO):
            with self.subTest(tabela=tabela):
                self.cursor.execute(f"SELECT count(*) FROM {tabela} WHERE tenant_id = %s", (self.tenant,))
                self.assertEqual(self.cursor.fetchone()[0], 0)
        q = ConsultaDoTypeScript("SQL_GRAVAR_SINAL", SQL_TS)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, q.sql, q.args(
            self.tenant, "auto_compra", "alta", str(uuid.uuid4()), "{}", AGORA))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, *self.sancao())
        self.como("kamba_app", None)
        self.cursor.execute(f"SELECT count(*) FROM {SINAL}")
        self.assertEqual(self.cursor.fetchone()[0], 0, "sem contexto, nada")


#: Cada constante, o papel que a corre e argumentos com o tipo certo.
_U = "00000000-0000-4000-8000-000000000000"
CONSTANTES = (
    ("SQL_SINAIS_DO_TENANT", "kamba_app", (_U,)),
    ("SQL_SANCOES_DO_TENANT_APP", "kamba_app", (_U,)),
    ("SQL_SANCOES_DO_TENANT_LOTE", "kamba_batch", (_U,)),
    ("SQL_ENCERRAMENTOS_POR_FECHAR", "kamba_batch", (AGORA,)),
    ("SQL_ESTADO_DO_TENANT", "kamba_batch", (_U,)),
    ("SQL_INDEPENDENCIA", "kamba_app", (_U, _U, "trust")),
    ("SQL_CONTACTOS_DO_DONO", "kamba_app", (_U,)),
    ("SQL_PEDIDO_E_COMPRADOR", "kamba_app", (_U, _U)),
    ("SQL_TENANT_E_TECTO", "kamba_app", (_U,)),
    ("SQL_PEDIDOS_MANUAIS", "kamba_app", (_U, AGORA)),
    ("SQL_QUEIXAS", "kamba_app", (_U, AGORA)),
    ("SQL_COMPRADORES_PAGOS", "kamba_app", (_U,)),
    ("SQL_NAO_ENTREGUES", "kamba_batch", (AGORA,)),
    ("SQL_FOTOS_REPETIDAS", "kamba_batch", ()),
)


class TestConsultas(Base):
    def test_cada_constante_planeia_com_o_papel_que_a_corre(self) -> None:
        """O `EXPLAIN` verifica as colunas e os privilegios sem executar nada."""
        for nome, papel, args in CONSTANTES:
            with self.subTest(constante=nome, papel=papel):
                q = ConsultaDoTypeScript(nome, SQL_TS)
                self.como(papel, _U)
                self.cursor.execute("SAVEPOINT plano")
                try:
                    self.cursor.execute("EXPLAIN " + q.sql, q.args(*args))
                    self.cursor.fetchall()
                finally:
                    self.cursor.execute("ROLLBACK TO SAVEPOINT plano")

    def test_o_dono_e_o_contacto_canonico_pela_cadeia_de_fusoes(self) -> None:
        dono = factories.contacto(self.cursor, self.tenant)
        absorvido = factories.contacto(self.cursor, self.tenant)
        self.cursor.execute(
            "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
            "WHERE contact_id = %s", (dono, absorvido))
        self.cursor.execute("UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s",
                            (absorvido, self.tenant))
        self.como("kamba_app", self.tenant)
        q = ConsultaDoTypeScript("SQL_CONTACTOS_DO_DONO", SQL_TS)
        self.cursor.execute(q.sql, q.args(self.tenant))
        self.assertEqual({str(c) for (c,) in self.cursor.fetchall()}, {dono, absorvido})

    def test_o_cas_do_estado_do_tenant_so_muda_de_onde_se_pede(self) -> None:
        self.como("kamba_batch")
        q = ConsultaDoTypeScript("SQL_TRANSITAR_TENANT", SQL_TS)
        self.cursor.execute(q.sql, q.args(self.tenant, ["ativo", "restrito"], "suspenso"))
        self.assertEqual(list(self.cursor.fetchall()), [], "um tenant em onboarding nao se suspende")
        self.cursor.execute(q.sql, q.args(self.tenant, ["onboarding"], "suspenso"))
        self.assertEqual(len(self.cursor.fetchall()), 1)
        self.como("kamba_app", self.tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cursor, q.sql,
                           q.args(self.tenant, ["suspenso"], "ativo"))

    def test_a_independencia_e_fail_closed(self) -> None:
        pedido = str(uuid.uuid4())
        self.como("kamba_app", self.tenant)
        q = ConsultaDoTypeScript("SQL_INDEPENDENCIA", SQL_TS)
        self.cursor.execute(q.sql, q.args(self.tenant, pedido, "trust"))
        self.assertEqual(tuple(self.cursor.fetchone()), (False, False), "sem avaliacao: por avaliar")
        self.sinal(ref=pedido)
        self.cursor.execute(q.sql, q.args(self.tenant, pedido, "trust"))
        self.assertEqual(tuple(self.cursor.fetchone()), (True, False))

    def test_os_encerramentos_por_fechar_sao_os_sem_recurso_e_com_caso_decidido(self) -> None:
        caso = _caso(self.cursor, self.tenant)
        self.cursor.execute("UPDATE platform.review_case SET estado = 'decidido' WHERE id = %s", (caso,))
        self.como("kamba_batch")
        self.cursor.execute(*self.sancao(origem="humana", passo="encerramento", case_id=caso,
                                         autor=str(uuid.uuid4()), chave=f"caso:{caso}",
                                         motivo_publico="loja_encerrada", justificacao_salto="x"))
        q = ConsultaDoTypeScript("SQL_ENCERRAMENTOS_POR_FECHAR", SQL_TS)
        self.cursor.execute(q.sql, q.args(datetime.now(timezone.utc) + timedelta(days=1)))
        self.assertEqual(len([l for l in self.cursor.fetchall() if str(l[1]) == self.tenant]), 1)
        self.cursor.execute(q.sql, q.args(datetime.now(timezone.utc) - timedelta(days=1)))
        self.assertEqual([l for l in self.cursor.fetchall() if str(l[1]) == self.tenant], [])


class TestDowngrade(unittest.TestCase):
    """«Migracao reversivel»: desce para a anterior e volta a subir."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _existe(self) -> tuple[int, int, bool]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                      "AND tablename IN ('ts_signal', 'ts_sanction')")
            tabelas = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('ts_imutavel', 'ts_sanction_regras')")
            funcoes = c.fetchone()[0]
            c.execute("SELECT has_column_privilege('kamba_batch', 'platform.catalog_ingestions', "
                      "'phash', 'SELECT')")
            return tabelas, funcoes, c.fetchone()[0]
        finally:
            conexao.close()

    def test_desce_e_volta_a_subir(self) -> None:
        _, anterior = _revisao()
        alembic_ok("downgrade", anterior)
        self.assertEqual(self._existe(), (0, 0, False))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), (2, 2, True))


if __name__ == "__main__":
    unittest.main()
