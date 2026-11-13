"""A revisao da fila de revisao contra a base: review_case e review_decision_log (KAM-089).

O que so uma base prova, e por isso este ficheiro existe:

1. **As listas fechadas sao as do codigo.** Os seis dominios contra o
   `packages/core-ts/src/revisao/contrato.ts`, e a maquina de estados do
   *trigger* contra a `TRANSICOES` de la, par a par.
2. **A chave de abertura** (criterio 9) e idempotente com e sem onboarding: o
   `NULLS NOT DISTINCT` e o que impede reentregar sem limite um caso de saga.
3. **As FK compostas**: um caso nao junta o onboarding de um com o tenant de
   outro, e uma decisao nao junta o caso de um com o tenant de outro.
4. **O registo de decisoes e append-only** por privilegio e por *trigger*, e
   uma decisao de recurso so aprova ou rejeita.
5. **Privilegios e RLS**: o `kamba_app` nao le nada da fila (o motivo interno e
   so do T&S); o lote muda estado e prazo e nao a prioridade.
6. **O SQL do modulo de TypeScript**, executado tal como esta escrito: a
   abertura idempotente, a transicao condicionada, a quota por origem com o
   recuo para o dispositivo, a pagina, os alertas, os contadores por familia
   de motivo, a vista do SLA e a escrita no `audit_log`.
7. **O `downgrade`.**
"""

from __future__ import annotations

import hashlib
import itertools
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
    VIOLACAO_DE_FK,
    ComBase,
    ConsultaDoTypeScript,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "packages" / "core-ts" / "src" / "revisao" / "contrato.ts"
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "revisao" / "sql.ts"

CASO = "platform.review_case"
LOG = "platform.review_decision_log"
#: O `RAISE` do *trigger* de imutabilidade (`object_not_in_prerequisite_state`).
RECUSADO_PELO_TRIGGER = "55000"
AGORA = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def _lista_ts(nome: str) -> tuple[str, ...]:
    texto = CONTRATO.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {CONTRATO.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def _transicoes_ts() -> set[tuple[str, str]]:
    texto = CONTRATO.read_text(encoding="utf-8")
    bloco = re.search(r"export const TRANSICOES[^=]*= \{(.*?)\n\};", texto, re.S)
    if bloco is None:
        raise AssertionError("TRANSICOES nao encontrada")
    pares = set()
    for de, para in re.findall(r"(\w+): \[([^\]]*)\]", bloco.group(1)):
        for destino in re.findall(r'"([a-z_]+)"', para):
            pares.add((de, destino))
    return pares


def _dominio(cursor, restricao: str) -> tuple[str, ...]:
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
        (restricao,),
    )
    return tuple(sorted(re.findall(r"'([a-z0-9_]+)'", cursor.fetchone()[0])))


def _sha(texto: str) -> bytes:
    return hashlib.sha256(texto.encode("utf-8")).digest()


def onboarding(cursor, rede: bytes | None = None, dispositivo: bytes | None = None) -> tuple[str, str]:
    """Um caso de onboarding minimo. Devolve `(id, tenant_id)`."""
    cursor.execute(
        "INSERT INTO platform.onboarding_case "
        "(origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac, "
        " ip_prefix_hash, device_hash, fase) "
        "VALUES ('convite', 'negocio de ensaio', 'moda', '\\x01', %s, '\\x02', %s, %s, %s, "
        " 'em_revisao') RETURNING id::text, tenant_id::text",
        (_sha(str(uuid.uuid4())), _sha(str(uuid.uuid4())), rede, dispositivo),
    )
    linha = cursor.fetchone()
    return linha[0], linha[1]


def abrir(cursor, tenant_id: str, onboarding_id: str | None = None, **campos):
    """Um caso pelo `SQL_ABRIR` do modulo. Devolve a linha, ou `None` se ja existia."""
    valores = {
        "tipo": "kyc",
        "onboarding_id": onboarding_id,
        "tenant_id": tenant_id,
        "motivo_codigo": "kyc_k1",
        "motivo_interno": "marcas=nif_divergente;score=40",
        "motivo_publico": "nao_foi_possivel_validar",
        "evidencias": json.dumps([{"tipo": "kyc_check", "ref": str(uuid.uuid4())}]),
        "recomendacao": "investigar",
        "estado": "aberto",
        "prioridade": 5,
        "fila_at": AGORA,
        "sla_alerta_at": AGORA + timedelta(hours=19),
        "sla_due_at": AGORA + timedelta(hours=24),
    }
    valores.update(campos)
    q = ConsultaDoTypeScript("SQL_ABRIR", SQL_TS)
    cursor.execute(q.sql, q.args(*valores.values()))
    return cursor.fetchone()


def decidir(cursor, case_id: str, decisao: str = "aprovar", instancia: str = "primeira",
            revisor: str | None = None) -> None:
    q = ConsultaDoTypeScript("SQL_REGISTAR_DECISAO", SQL_TS)
    cursor.execute(q.sql, q.args(case_id, revisor or str(uuid.uuid4()), decisao, instancia, "r", None))


class TestDominios(ComBase):
    def test_os_dominios_sao_os_do_modulo(self) -> None:
        cursor = self.ligar("admin").cursor()
        for restricao, lista in (
            ("review_case_tipo_ck", "TIPOS_DE_CASO"),
            ("review_case_estado_ck", "ESTADOS"),
            ("review_case_motivo_publico_ck", "MOTIVOS_PUBLICOS"),
            ("review_case_recomendacao_ck", "RECOMENDACOES"),
            ("review_decision_log_decisao_ck", "DECISOES"),
            ("review_decision_log_instancia_ck", "INSTANCIAS"),
        ):
            with self.subTest(restricao=restricao):
                self.assertEqual(_dominio(cursor, restricao), tuple(sorted(_lista_ts(lista))))

    def test_o_dominio_do_audit_log_tem_as_duas_accoes_da_fila(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'"
        )
        definicao = cursor.fetchone()[0]
        texto = CONTRATO.read_text(encoding="utf-8")
        achado = re.search(r"export const ACCOES_DE_AUDITORIA = \[(.*?)\] as const;", texto, re.S)
        accoes = re.findall(r'"([a-z_.]+)"', achado.group(1))
        self.assertEqual(sorted(accoes), ["review.acesso", "review.recusa"])
        for accao in accoes:
            self.assertIn(f"'{accao}'", definicao)

    def test_a_maquina_do_trigger_e_a_do_modulo_par_a_par(self) -> None:
        admin = self.ligar("admin").cursor()
        permitidas = _transicoes_ts()
        estados = _lista_ts("ESTADOS")
        self.assertEqual(len(permitidas), 9)
        for de, para in itertools.permutations(estados, 2):
            with self.subTest(de=de, para=para):
                linha = abrir(admin, str(uuid.uuid4()), estado=de, motivo_codigo=f"t_{de}_{para}"[:40])
                sql = f"UPDATE {CASO} SET estado = %s WHERE id = %s"
                if (de, para) in permitidas:
                    admin.execute(sql, (para, linha[0]))
                else:
                    self.assertErroSql(VIOLACAO_DE_CHECK, admin, sql, (para, linha[0]))


class TestAbertura(ComBase):
    def test_a_chave_e_idempotente_com_e_sem_onboarding(self) -> None:
        cursor = self.ligar("admin").cursor()
        onb, tenant = onboarding(cursor)
        self.assertIsNotNone(abrir(cursor, tenant, onb))
        self.assertIsNone(abrir(cursor, tenant, onb), "reentregar nao cria segundo caso")
        saga = str(uuid.uuid4())
        self.assertIsNotNone(abrir(cursor, saga, None, tipo="saga", motivo_codigo="passo_3"))
        self.assertIsNone(abrir(cursor, saga, None, tipo="saga", motivo_codigo="passo_3"),
                          "sem onboarding, o NULLS NOT DISTINCT e que segura a chave")
        q = ConsultaDoTypeScript("SQL_POR_CHAVE", SQL_TS)
        cursor.execute(q.sql, q.args("saga", saga, None, "passo_3"))
        self.assertEqual(len(cursor.fetchall()), 1)
        cursor.execute(q.sql, q.args("kyc", tenant, onb, "kyc_k1"))
        self.assertEqual(len(cursor.fetchall()), 1)

    def test_o_onboarding_tem_de_ser_do_tenant_da_linha(self) -> None:
        cursor = self.ligar("admin").cursor()
        onb, _ = onboarding(cursor)
        q = ConsultaDoTypeScript("SQL_ABRIR", SQL_TS)
        args = q.args("kyc", onb, str(uuid.uuid4()), "kyc_k1", "x", "nao_foi_possivel_validar",
                      "[]", None, "aberto", 5, AGORA, AGORA, AGORA)
        self.assertErroSql(VIOLACAO_DE_FK, cursor, q.sql, args)

    def test_restricoes_do_caso(self) -> None:
        cursor = self.ligar("admin").cursor()
        q = ConsultaDoTypeScript("SQL_ABRIR", SQL_TS)
        base = ["kyc", None, str(uuid.uuid4()), "kyc_k1", "x", "nao_foi_possivel_validar", "[]",
                None, "aberto", 5, AGORA, AGORA, AGORA]
        for indice, valor, porque in (
            (5, "nif_divergente", "motivo publico fora da lista"),
            (3, "Kyc K1", "motivo_codigo fora da forma"),
            (3, "screening:" + "a" * 81, "motivo_codigo longo"),
            (4, "", "motivo interno vazio"),
            (6, '{"a": 1}', "evidencias que nao sao lista"),
            (9, 0, "prioridade 0"),
            (9, 10, "prioridade 10"),
            (11, AGORA + timedelta(hours=2), "alerta depois do prazo"),
        ):
            with self.subTest(porque=porque):
                args = list(base)
                args[indice] = valor
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, q.sql, q.args(*args))

    def test_os_motivos_das_portas_cabem_na_forma(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        for motivo in ("kyc_k1", "es_falhado", "screening:" + "ab" * 32, f"amostra:{uuid.uuid4()}"):
            with self.subTest(motivo=motivo):
                self.assertIsNotNone(abrir(cursor, tenant, None, motivo_codigo=motivo))


class TestDecisoes(ComBase):
    def test_ninguem_emenda_nem_apaga_uma_decisao(self) -> None:
        admin = self.ligar("admin").cursor()
        caso = abrir(admin, str(uuid.uuid4()))
        decidir(admin, caso[0], "rejeitar")
        self.assertErroSql(RECUSADO_PELO_TRIGGER, admin,
                           f"UPDATE {LOG} SET decisao = 'aprovar' WHERE case_id = %s", (caso[0],))
        self.assertErroSql(RECUSADO_PELO_TRIGGER, admin,
                           f"DELETE FROM {LOG} WHERE case_id = %s", (caso[0],))
        lote = self.ligar("batch").cursor()
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote, f"UPDATE {LOG} SET decisao = 'aprovar'")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote, f"DELETE FROM {LOG}")

    def test_a_decisao_leva_o_tenant_do_caso_e_nao_junta_outro(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        caso = abrir(admin, tenant)
        decidir(admin, caso[0])
        admin.execute(f"SELECT tenant_id::text FROM {LOG} WHERE case_id = %s", (caso[0],))
        self.assertEqual(admin.fetchone()[0], tenant)
        self.assertErroSql(
            VIOLACAO_DE_FK, admin,
            f"INSERT INTO {LOG} (case_id, tenant_id, revisor_id, decisao) VALUES (%s, %s, %s, 'aprovar')",
            (caso[0], str(uuid.uuid4()), str(uuid.uuid4())),
        )

    def test_um_recurso_so_aprova_ou_rejeita(self) -> None:
        admin = self.ligar("admin").cursor()
        caso = abrir(admin, str(uuid.uuid4()))
        decidir(admin, caso[0], "rejeitar", "recurso")
        q = ConsultaDoTypeScript("SQL_REGISTAR_DECISAO", SQL_TS)
        for decisao in ("escalar", "pedir_info"):
            with self.subTest(decisao=decisao):
                self.assertErroSql(VIOLACAO_DE_CHECK, admin, q.sql,
                                   q.args(caso[0], str(uuid.uuid4()), decisao, "recurso", None, None))

    def test_o_registo_sai_pela_ordem_de_gravacao_na_mesma_transaccao(self) -> None:
        admin = self.ligar("admin").cursor()
        caso = abrir(admin, str(uuid.uuid4()))
        for d in ("pedir_info", "aprovar", "aprovar"):
            decidir(admin, caso[0], d)
        q = ConsultaDoTypeScript("SQL_DECISOES", SQL_TS)
        admin.execute(q.sql, q.args(caso[0]))
        linhas = admin.fetchall()
        self.assertEqual([l[3] for l in linhas], ["pedir_info", "aprovar", "aprovar"])
        self.assertEqual(len({l[7] for l in linhas}), 3, "o clock_timestamp desempata")


class TestPrivilegios(ComBase):
    def test_a_aplicacao_nao_le_nada_da_fila(self) -> None:
        app = self.ligar("app").cursor()
        factories.contexto(app, str(uuid.uuid4()))
        for alvo in (CASO, LOG, "platform.v_review_sla"):
            with self.subTest(alvo=alvo):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, f"SELECT 1 FROM {alvo}")

    def test_o_lote_muda_estado_e_prazo_mas_nao_a_chave_nem_o_motivo_publico(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()), prioridade=1)
        for coluna, valor in (("motivo_publico", "'documento_expirado'"), ("tipo", "'trust'"),
                              ("tenant_id", "gen_random_uuid()"), ("motivo_codigo", "'outro'"),
                              ("onboarding_id", "gen_random_uuid()")):
            with self.subTest(coluna=coluna):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote,
                                   f"UPDATE {CASO} SET {coluna} = {valor} WHERE id = %s", (caso[0],))
        q = ConsultaDoTypeScript("SQL_TRANSITAR", SQL_TS)
        lote.execute(q.sql, q.args(caso[0], "aberto", "em_analise"))
        self.assertEqual(len(lote.fetchall()), 1)
        lote.execute(q.sql, q.args(caso[0], "aberto", "decidido"))
        self.assertEqual(len(lote.fetchall()), 0, "de um estado que ja nao e o actual, nada")

    def test_a_rls_esta_forcada_nas_duas(self) -> None:
        for tabela in ("review_case", "review_decision_log"):
            with self.subTest(tabela=tabela):
                [(ligada, forcada)] = self.consultar(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = %s::regclass", (f"platform.{tabela}",))
                self.assertEqual((ligada, forcada), (True, True))


class TestReforco(ComBase):
    def test_a_prioridade_so_fica_mais_urgente(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()), prioridade=5)
        lote.execute(f"UPDATE {CASO} SET prioridade = 1 WHERE id = %s", (caso[0],))
        self.assertErroSql(VIOLACAO_DE_CHECK, lote,
                           f"UPDATE {CASO} SET prioridade = 2 WHERE id = %s", (caso[0],))

    def test_o_reforco_traz_o_que_a_porta_sabe_e_nunca_baixa_a_urgencia(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()), prioridade=2)
        q = ConsultaDoTypeScript("SQL_REFORCAR", SQL_TS)
        novas = json.dumps([{"tipo": "kyc_check", "ref": "a"}, {"tipo": "kyc_check", "ref": "b"}])
        lote.execute(q.sql, q.args(caso[0], 5, "marcas=nif_divergente", novas, "rejeitar"))
        self.assertEqual(len(lote.fetchall()), 1)
        lote.execute(f"SELECT prioridade, motivo_interno, jsonb_array_length(evidencias), recomendacao "
                     f"FROM {CASO} WHERE id = %s", (caso[0],))
        self.assertEqual(tuple(lote.fetchone()), (2, "marcas=nif_divergente", 2, "rejeitar"))
        lote.execute(q.sql, q.args(caso[0], 1, "x", "[]", None))
        lote.execute(f"SELECT prioridade FROM {CASO} WHERE id = %s", (caso[0],))
        self.assertEqual(lote.fetchone()[0], 1)

    def test_um_caso_decidido_nao_se_reforca(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()), estado="decidido")
        q = ConsultaDoTypeScript("SQL_REFORCAR", SQL_TS)
        lote.execute(q.sql, q.args(caso[0], 1, "x", "[]", None))
        self.assertEqual(len(lote.fetchall()), 0)


class TestIsolamento(ComBase):
    """O teste cruzado do ADR-015: o `kamba_audit` le pela RLS, e so o seu tenant."""

    def test_a_auditoria_le_o_seu_tenant_e_nao_o_dos_outros(self) -> None:
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        conexao = ligacao.ligar("admin")
        try:
            caso = abrir(conexao.cursor(), a, None, tipo="trust", motivo_codigo=f"rls_{a[:8]}")
            decidir(conexao.cursor(), caso[0], "rejeitar")
            conexao.commit()
        finally:
            conexao.close()
        auditoria = self.ligar("audit").cursor()
        for contexto, esperado in ((a, 1), (b, 0), (None, 0)):
            factories.contexto(auditoria, contexto)
            for tabela, coluna in ((CASO, "id"), (LOG, "case_id")):
                with self.subTest(contexto=contexto, tabela=tabela):
                    auditoria.execute(f"SELECT count(*) FROM {tabela} WHERE {coluna} = %s", (caso[0],))
                    self.assertEqual(auditoria.fetchone()[0], esperado)
            with self.subTest(contexto=contexto, tabela="v_review_sla"):
                auditoria.execute("SELECT count(*) FROM platform.v_review_sla WHERE case_id = %s", (caso[0],))
                self.assertEqual(auditoria.fetchone()[0], esperado)


class TestConsultas(ComBase):
    def test_a_quota_conta_a_origem_e_recua_para_o_dispositivo(self) -> None:
        # Como administrador: o lote nao tem `INSERT` na `onboarding_case` (e do
        # registo), e os privilegios medem-se no `TestPrivilegios`.
        lote = self.ligar("admin").cursor()
        rede = _sha(str(uuid.uuid4()))
        dispositivo = _sha(str(uuid.uuid4()))
        for _ in range(3):
            onb, tenant = onboarding(lote, rede=rede)
            abrir(lote, tenant, onb)
        onb, tenant = onboarding(lote, rede=rede)
        abrir(lote, tenant, onb, estado="em_triagem_automatica")
        onb, tenant = onboarding(lote, rede=rede)
        abrir(lote, tenant, onb, fila_at=AGORA - timedelta(days=1),
              sla_alerta_at=AGORA, sla_due_at=AGORA)
        for _ in range(2):
            onb, tenant = onboarding(lote, rede=None, dispositivo=dispositivo)
            abrir(lote, tenant, onb)
        q = ConsultaDoTypeScript("SQL_CONTAR_NA_FILA", SQL_TS)
        lote.execute(q.sql, q.args(rede, AGORA - timedelta(hours=1)))
        self.assertEqual(lote.fetchone()[0], 3, "a triagem e o dia anterior nao contam")
        lote.execute(q.sql, q.args(dispositivo, AGORA - timedelta(hours=1)))
        self.assertEqual(lote.fetchone()[0], 2)

    def test_pagina_alertas_pendentes_e_triagem(self) -> None:
        # Como administrador: o lote nao tem `INSERT` na `onboarding_case` (e do
        # registo), e os privilegios medem-se no `TestPrivilegios`.
        lote = self.ligar("admin").cursor()
        onb, tenant = onboarding(lote)
        urgente = abrir(lote, tenant, onb, prioridade=1, motivo_codigo="a")
        normal = abrir(lote, tenant, onb, prioridade=5, motivo_codigo="b")
        triagem = abrir(lote, tenant, onb, estado="em_triagem_automatica", motivo_codigo="c")
        q = ConsultaDoTypeScript("SQL_PAGINA", SQL_TS)
        lote.execute(q.sql, q.args(None, None, 1000, 0))
        ids = [l[0] for l in lote.fetchall()]
        self.assertLess(ids.index(urgente[0]), ids.index(normal[0]))
        self.assertNotIn(triagem[0], ids)
        lote.execute(q.sql, q.args("kyc", "aberto", 1, 0))
        self.assertEqual(len(lote.fetchall()), 1)

        q = ConsultaDoTypeScript("SQL_CASOS_DO_ONBOARDING", SQL_TS)
        lote.execute(q.sql, q.args(onb))
        self.assertEqual(len(lote.fetchall()), 3)

        q = ConsultaDoTypeScript("SQL_ALERTAS_DEVIDOS", SQL_TS)
        lote.execute(q.sql, q.args(AGORA + timedelta(hours=20)))
        devidos = {l[0] for l in lote.fetchall()}
        self.assertIn(urgente[0], devidos)
        self.assertNotIn(triagem[0], devidos, "a triagem nao e vista humana")
        q = ConsultaDoTypeScript("SQL_MARCAR_ALERTADO", SQL_TS)
        lote.execute(q.sql, q.args(urgente[0], AGORA))
        q = ConsultaDoTypeScript("SQL_ALERTAS_DEVIDOS", SQL_TS)
        lote.execute(q.sql, q.args(AGORA + timedelta(hours=20)))
        self.assertNotIn(urgente[0], {l[0] for l in lote.fetchall()}, "o alerta sai uma vez")

        q = ConsultaDoTypeScript("SQL_TRANSITAR_COM_SLA", SQL_TS)
        dia = AGORA + timedelta(days=1)
        lote.execute(q.sql, q.args(triagem[0], "em_triagem_automatica", "aberto", dia,
                                   dia + timedelta(hours=19), dia + timedelta(hours=24)))
        self.assertEqual(len(lote.fetchall()), 1)

    def test_as_origens_nulas_partilham_a_quota_e_a_do_tenant_conta_so_sem_onboarding(self) -> None:
        admin = self.ligar("admin").cursor()
        for _ in range(2):
            onb, tenant = onboarding(admin, rede=None, dispositivo=None)
            abrir(admin, tenant, onb)
        q = ConsultaDoTypeScript("SQL_CONTAR_NA_FILA", SQL_TS)
        admin.execute(q.sql, q.args(None, AGORA - timedelta(hours=1)))
        self.assertGreaterEqual(admin.fetchone()[0], 2, "as nulas contam juntas")
        tenant = str(uuid.uuid4())
        for i in range(3):
            abrir(admin, tenant, None, tipo="catalogo", motivo_codigo=f"screening:c{i}")
        abrir(admin, tenant, None, tipo="auditoria", motivo_codigo="amostra:x")
        abrir(admin, tenant, None, tipo="catalogo", motivo_codigo="screening:t",
              estado="em_triagem_automatica")
        q = ConsultaDoTypeScript("SQL_CONTAR_NA_FILA_DO_TENANT", SQL_TS)
        admin.execute(q.sql, q.args(tenant, AGORA - timedelta(hours=1)))
        self.assertEqual(admin.fetchone()[0], 3, "sem a auditoria nem a triagem")

    def test_a_pagina_filtra_pelo_estado_e_os_alertas_cobrem_todos_os_pendentes(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        vencido = {"fila_at": AGORA - timedelta(days=2), "sla_alerta_at": AGORA - timedelta(days=1),
                   "sla_due_at": AGORA - timedelta(hours=1)}
        casos = {estado: abrir(admin, tenant, None, tipo="trust", motivo_codigo=f"e_{estado}",
                               estado=estado, **vencido)[0]
                 for estado in ("aberto", "em_analise", "escalado", "recurso_aberto", "decidido")}
        q = ConsultaDoTypeScript("SQL_PAGINA", SQL_TS)
        admin.execute(q.sql, q.args("trust", "escalado", 1000, 0))
        ids = {l[0] for l in admin.fetchall()}
        self.assertIn(casos["escalado"], ids)
        self.assertNotIn(casos["aberto"], ids, "o filtro de estado filtra")
        q = ConsultaDoTypeScript("SQL_ALERTAS_DEVIDOS", SQL_TS)
        admin.execute(q.sql, q.args(AGORA))
        devidos = {l[0] for l in admin.fetchall()}
        for estado in ("aberto", "em_analise", "escalado", "recurso_aberto"):
            self.assertIn(casos[estado], devidos, estado)
        self.assertNotIn(casos["decidido"], devidos)

    def test_reiniciar_o_prazo_repoe_o_alerta_e_o_recurso_mantem_a_entrada(self) -> None:
        admin = self.ligar("admin").cursor()
        caso = abrir(admin, str(uuid.uuid4()), None, tipo="trust", motivo_codigo="prazo",
                     estado="decidido")
        alertar = ConsultaDoTypeScript("SQL_MARCAR_ALERTADO", SQL_TS)
        admin.execute(alertar.sql, alertar.args(caso[0], AGORA))
        q = ConsultaDoTypeScript("SQL_TRANSITAR_COM_SLA", SQL_TS)
        novo = AGORA + timedelta(days=3)
        admin.execute(q.sql, q.args(caso[0], "decidido", "recurso_aberto", None,
                                    novo, novo + timedelta(hours=5)))
        admin.execute(f"SELECT fila_at, sla_alertado_at, sla_due_at FROM {CASO} WHERE id = %s", (caso[0],))
        fila_at, alertado, due = admin.fetchone()
        self.assertEqual(fila_at, AGORA, "o recurso nao apaga a entrada")
        self.assertIsNone(alertado, "o alerta volta a poder sair")
        self.assertEqual(due, novo + timedelta(hours=5))

    def test_a_decisao_grava_se_no_caso_pedido(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        a = abrir(admin, tenant, None, tipo="trust", motivo_codigo="a")
        b = abrir(admin, tenant, None, tipo="trust", motivo_codigo="b")
        decidir(admin, b[0], "rejeitar")
        admin.execute(f"SELECT case_id::text FROM {LOG} WHERE tenant_id = %s", (tenant,))
        self.assertEqual([l[0] for l in admin.fetchall()], [str(b[0])])

    def test_dentro_do_sla_e_da_instancia_em_curso(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        passado = {"fila_at": AGORA - timedelta(days=3), "sla_alerta_at": AGORA - timedelta(days=2),
                   "sla_due_at": AGORA - timedelta(days=1)}
        atrasado = abrir(admin, tenant, None, tipo="trust", motivo_codigo="atrasado", **passado)
        a_tempo = abrir(admin, tenant, None, tipo="trust", motivo_codigo="a_tempo")
        decidir(admin, a_tempo[0], "pedir_info")
        recurso = abrir(admin, tenant, None, tipo="trust", motivo_codigo="recurso",
                        estado="recurso_aberto", **passado)
        decidir(admin, recurso[0], "rejeitar")  # a primeira instancia, antes do prazo do recurso
        admin.execute("SELECT case_id::text, dentro_do_sla FROM platform.v_review_sla "
                      "WHERE tenant_id = %s", (tenant,))
        vista = {k: v for k, v in admin.fetchall()}
        self.assertIs(vista[str(atrasado[0])], False, "sem decisao e com o prazo passado")
        self.assertIs(vista[str(a_tempo[0])], True)
        self.assertIs(vista[str(recurso[0])], False, "a primeira instancia nao conta para o recurso")

    def test_os_casos_do_onboarding_sao_todos(self) -> None:
        admin = self.ligar("admin").cursor()
        onb, tenant = onboarding(admin)
        abrir(admin, tenant, onb, motivo_codigo="a")
        abrir(admin, tenant, onb, motivo_codigo="b", estado="decidido")
        q = ConsultaDoTypeScript("SQL_CASOS_DO_ONBOARDING", SQL_TS)
        admin.execute(q.sql, q.args(onb))
        self.assertEqual(sorted(l[9] for l in admin.fetchall()), ["aberto", "decidido"])

    def test_a_vista_do_sla_e_os_contadores(self) -> None:
        # Como administrador: o lote nao tem `INSERT` na `onboarding_case` (e do
        # registo), e os privilegios medem-se no `TestPrivilegios`.
        lote = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        a = abrir(lote, tenant, None, tipo="auditoria", motivo_codigo=f"amostra:{uuid.uuid4()}")
        b = abrir(lote, tenant, None, tipo="auditoria", motivo_codigo=f"amostra:{uuid.uuid4()}")
        abrir(lote, tenant, None, tipo="saga", motivo_codigo="passo_1", estado="em_triagem_automatica")
        decidir(lote, a[0], "pedir_info")
        decidir(lote, a[0], "rejeitar")
        decidir(lote, a[0], "aprovar", "recurso")
        q = ConsultaDoTypeScript("SQL_VISTA_SLA", SQL_TS)
        lote.execute(q.sql, q.args())
        vista = {l[0]: l for l in lote.fetchall()}
        self.assertIn(a[0], vista)
        self.assertIsNotNone(vista[a[0]][5], "a primeira decisao e a do pedir_info")
        self.assertIsNone(vista[b[0]][5])
        self.assertEqual(sum(1 for l in vista.values() if l[1] == "saga" and l[0] in vista), 0,
                         "a triagem nao entra na vista")
        q = ConsultaDoTypeScript("SQL_CONTADORES", SQL_TS)
        lote.execute(q.sql, q.args())
        contadores = {(l[0], l[1], l[2]): l[3] for l in lote.fetchall()}
        self.assertGreaterEqual(contadores[("auditoria", "amostra", "aprovar")], 1,
                                "o recurso decide, e o motivo conta-se pela familia")
        self.assertGreaterEqual(contadores[("auditoria", "amostra", None)], 1)
        [(opcoes,)] = self.consultar(
            "SELECT reloptions FROM pg_class WHERE oid = 'platform.v_review_sla'::regclass")
        self.assertIn("security_invoker=true", opcoes)

    def test_o_audit_log_recebe_as_duas_accoes_pelo_lote(self) -> None:
        lote = self.ligar("batch").cursor()
        tenant = str(uuid.uuid4())
        q = ConsultaDoTypeScript("SQL_AUDITAR", SQL_TS)
        for accao in ("review.acesso", "review.recusa"):
            lote.execute(q.sql, q.args(tenant, str(uuid.uuid4()), accao, "kyc_check",
                                       str(uuid.uuid4()), _sha("documento")))
        lote.execute("SELECT action, actor_type FROM platform.audit_log WHERE tenant_id = %s "
                     "ORDER BY id", (tenant,))
        self.assertEqual([tuple(l) for l in lote.fetchall()],
                         [("review.acesso", "staff"), ("review.recusa", "staff")])
        self.assertErroSql(VIOLACAO_DE_CHECK, lote, q.sql,
                           q.args(tenant, "x", "review.exportar", "kyc_check", "y", _sha("z")))


class TestDowngrade(unittest.TestCase):
    """«Migracao reversivel»: desce com linhas e volta a subir.

    A recusa por linhas `review.*` no `audit_log` **nao** se mede aqui: o
    `audit_log` e *append-only* e uma linha escrita com `commit` prendia todos
    os `downgrade` abaixo da `0048` das outras suites da mesma base.
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

    def _existe(self) -> tuple[int, int, int, bool]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                      "AND tablename IN ('review_case', 'review_decision_log')")
            tabelas = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN "
                      "('review_case_transicao', 'review_decision_log_imutavel')")
            funcoes = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_views WHERE viewname = 'v_review_sla'")
            vistas = c.fetchone()[0]
            c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                      "WHERE conname = 'audit_log_action'")
            return tabelas, funcoes, vistas, "review." in c.fetchone()[0]
        finally:
            conexao.close()

    def test_desce_com_linhas_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            caso = abrir(conexao.cursor(), str(uuid.uuid4()), None, tipo="trust",
                         motivo_codigo=f"downgrade_{uuid.uuid4().hex[:8]}")
            decidir(conexao.cursor(), caso[0], "rejeitar")
            conexao.commit()
        finally:
            conexao.close()
        # Para a `0047` e nao `-1`: quem puser uma revisao por cima nao parte isto.
        alembic_ok("downgrade", "0047")
        self.assertEqual(self._existe(), (0, 0, 0, False))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), (2, 2, 1, True))



class TestEfeitosPorReaplicar(ComBase):
    """A marca de «efeito por aplicar» da revisao `0053` (KAM-198).

    As tres consultas sao as do modulo (`SQL_MARCAR_EFEITO`, `SQL_EFEITOS_PENDENTES`,
    `SQL_RESOLVER_EFEITO`), lidas do `sql.ts` e nao copiadas.
    """

    def test_o_lote_marca_lista_e_resolve_ate_num_caso_decidido_final(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()))[0]
        # Um caso que ja nao sai do estado: o *trigger* so olha para o estado e a
        # prioridade, e a marca escreve-se na mesma.
        for de, para in (("aberto", "decidido"), ("decidido", "recurso_aberto"),
                         ("recurso_aberto", "decidido_final")):
            q = ConsultaDoTypeScript("SQL_TRANSITAR", SQL_TS)
            lote.execute(q.sql, q.args(caso, de, para))
        marcar = ConsultaDoTypeScript("SQL_MARCAR_EFEITO", SQL_TS)
        lote.execute(marcar.sql, marcar.args(caso))
        marca = lote.fetchone()[0]
        pendentes = ConsultaDoTypeScript("SQL_EFEITOS_PENDENTES", SQL_TS)
        lote.execute(pendentes.sql, pendentes.args(100))
        self.assertIn((caso, marca), [tuple(l) for l in lote.fetchall()])
        resolver = ConsultaDoTypeScript("SQL_RESOLVER_EFEITO", SQL_TS)
        lote.execute(resolver.sql, resolver.args(caso, marca))
        lote.execute(f"SELECT efeito_pendente_at FROM {CASO} WHERE id = %s", (caso,))
        self.assertIsNone(lote.fetchone()[0])

    def test_resolver_com_uma_marca_antiga_nao_apaga_a_nova(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()))[0]
        marcar = ConsultaDoTypeScript("SQL_MARCAR_EFEITO", SQL_TS)
        lote.execute(marcar.sql, marcar.args(caso))
        antiga = lote.fetchone()[0]
        lote.execute(marcar.sql, marcar.args(caso))
        nova = lote.fetchone()[0]
        self.assertNotEqual(antiga, nova, "marcar renova o instante")
        resolver = ConsultaDoTypeScript("SQL_RESOLVER_EFEITO", SQL_TS)
        lote.execute(resolver.sql, resolver.args(caso, antiga))
        lote.execute(f"SELECT efeito_pendente_at::text FROM {CASO} WHERE id = %s", (caso,))
        self.assertEqual(lote.fetchone()[0], nova)
        # Sem marca lida (`NULL`), limpa sem comparar.
        lote.execute(resolver.sql, resolver.args(caso, None))
        lote.execute(f"SELECT efeito_pendente_at FROM {CASO} WHERE id = %s", (caso,))
        self.assertIsNone(lote.fetchone()[0])

    def test_o_lote_so_ganhou_esta_coluna_e_a_aplicacao_nada(self) -> None:
        lote = self.ligar("batch").cursor()
        caso = abrir(lote, str(uuid.uuid4()))[0]
        lote.execute(f"UPDATE {CASO} SET efeito_pendente_at = now() WHERE id = %s", (caso,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote,
                           f"UPDATE {CASO} SET criado_at = now() WHERE id = %s", (caso,))
        app = self.ligar("app").cursor()
        factories.contexto(app, str(uuid.uuid4()))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"UPDATE {CASO} SET efeito_pendente_at = now()")


class TestDowngradeDa0053(unittest.TestCase):
    """O `downgrade` da `0053` recusa-se com um caso marcado, e sem ele desfaz tudo.

    **Desce pelo numero (`0052`) e nao por `-1`**, pela licao do KAM-071, e **nao
    exige `em_head()` depois de recusar**, pela do KAM-089: com outra revisao por
    cima, o Alembic desce-a primeiro e a base fica nesta.
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

    def _admin(self):
        conexao = ligacao.ligar("admin")
        self.addCleanup(conexao.close)
        return conexao

    def _coluna(self) -> int:
        c = self._admin().cursor()
        c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                  "AND table_name = 'review_case' AND column_name = 'efeito_pendente_at'")
        return int(c.fetchone()[0])

    def test_com_um_caso_marcado_recusa_e_sem_ele_desce_e_volta(self) -> None:
        conexao = self._admin()
        c = conexao.cursor()
        caso = abrir(c, str(uuid.uuid4()))[0]
        c.execute(f"UPDATE {CASO} SET efeito_pendente_at = now() WHERE id = %s", (caso,))
        conexao.commit()
        try:
            resultado = alembic("downgrade", "0052")
            self.assertNotEqual(resultado.returncode, 0, "o downgrade devia recusar")
            self.assertIn("downgrade da 0053 recusado", resultado.stderr)
            self.assertEqual(self._coluna(), 1, "a coluna ficou, com a marca")
        finally:
            if not em_head():
                alembic_ok("upgrade", "head")
            c.execute(f"DELETE FROM {CASO} WHERE id = %s", (caso,))
            conexao.commit()
        alembic_ok("downgrade", "0052")
        try:
            self.assertEqual(self._coluna(), 0)
            c2 = self._admin().cursor()
            c2.execute("SELECT count(*) FROM pg_indexes WHERE indexname = 'review_case_efeito_pendente_idx'")
            self.assertEqual(int(c2.fetchone()[0]), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._coluna(), 1)
        c3 = self._admin().cursor()
        c3.execute("SELECT has_column_privilege('kamba_batch', 'platform.review_case', "
                   "'efeito_pendente_at', 'UPDATE')")
        self.assertTrue(c3.fetchone()[0])


if __name__ == "__main__":
    unittest.main()
