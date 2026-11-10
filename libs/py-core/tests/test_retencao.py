"""Retencao e purga por classe de dados (KAM-071), sem base de dados.

O que corre contra um PostgreSQL real esta em `db/tests/test_retencao_bd.py`.
Aqui provam-se as decisoes: as janelas com relogio simulado, a politica e as
recusas dela, e o *job* sobre uma base falsa.

## A base falsa le o TEXTO da instrucao

Pela licao do KAM-070: um duplo que filtrasse pelo argumento ficava verde com o
`tenant_id = %s` apagado da consulta, porque continuava a receber o tenant na
tupla. A `BaseFalsa` filtra pelo tenant **so se o texto o tiver**, exclui os
contactos retidos **so se o texto tiver** o `contact_id = ANY`, e o
`test_canario_a_base_falsa_morde` apaga o predicado de uma copia do caminho e
exige que a fuga aconteca.
"""

from __future__ import annotations

import copy
import re
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kamba_core.retencao import hold, jobs, politica, purge_log
from kamba_core.retencao.politica import Classe, Prazo, Tabela
from kamba_core.storage.port import ObjectoInexistenteError

RAIZ = Path(__file__).resolve().parents[3]
AGORA = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)
A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
JOAO = "33333333-3333-4333-8333-333333333333"
MARIA = "44444444-4444-4444-8444-444444444444"

_TABELA = re.compile(r"(?:FROM|DELETE FROM)\s+((?:platform|dat)\.\w+)")


class Falhou(RuntimeError):
    pass


class BaseFalsa:
    """Uma base em memoria. Ver a nota do modulo."""

    def __init__(self) -> None:
        self.tabelas: dict[str, list[dict]] = {}
        self.holds: list[tuple[str, str, str]] = []
        self.ledger: list[tuple[str, datetime]] = []
        self.purge_log: list[tuple] = []
        self.auditoria: list[tuple] = []
        self.particoes: dict[str, list[str]] = {}
        self.criadas: list[tuple] = []
        self.largadas: list[tuple] = []
        self.instrucoes: list[str] = []
        self.falhar_em: str | None = None
        self._copia = None

    def linhas(self, tabela: str, **kw) -> None:
        self.tabelas.setdefault(tabela, []).append(dict(kw))

    def contar(self, tabela: str, tenant: str | None = None) -> int:
        return sum(1 for r in self.tabelas.get(tabela, []) if tenant in (None, r.get("tenant")))

    # transaccoes por fotografia
    def comecar(self) -> None:
        self._copia = copy.deepcopy(
            (self.tabelas, self.purge_log, self.auditoria, self.particoes, self.largadas, self.criadas)
        )

    def reverter(self) -> None:
        (self.tabelas, self.purge_log, self.auditoria, self.particoes,
         self.largadas, self.criadas) = self._copia


class CursorFalso:
    def __init__(self, base: BaseFalsa) -> None:
        self.base = base
        self.linhas_: list[tuple] = []
        self.rowcount = -1

    def close(self) -> None:
        pass

    def fetchall(self):
        return list(self.linhas_)

    def fetchone(self):
        return self.linhas_[0]

    def execute(self, sql: str, parametros=()) -> None:
        b = self.base
        b.instrucoes.append(sql)
        if b.falhar_em and b.falhar_em in sql:
            raise Falhou(b.falhar_em)
        self.linhas_, self.rowcount = [], -1
        if "set_config" in sql:
            return
        if "audit_append" in sql:
            b.auditoria.append(tuple(parametros))
            return
        if "FROM platform.audit_log" in sql:
            self.linhas_ = list(b.holds)
            return
        if "FROM platform.erasure_ledger" in sql:
            self.linhas_ = list(b.ledger)
            return
        if "INSERT INTO platform.purge_log" in sql:
            b.purge_log.append(tuple(parametros))
            return
        if "FROM pg_inherits" in sql:
            self.linhas_ = [(n,) for n in b.particoes.get(parametros[0], [])]
            return
        tabela = _TABELA.search(sql).group(1)
        if "FILTER (WHERE tenant_id = ANY" in sql:
            retidos, desde, ate = parametros
            mes = [r for r in b.tabelas.get(tabela, []) if desde <= r["ts"] < ate]
            self.linhas_ = [(len(mes), sum(1 for r in mes if r["tenant"] in retidos))]
            return
        self._generica(sql, tabela, list(parametros))

    def _generica(self, sql: str, tabela: str, p: list) -> None:
        b = self.base
        rows = b.tabelas.get(tabela, [])
        com_tenant = re.search(r"tenant_id = %s::uuid", sql) is not None
        tenant = p.pop(0) if com_tenant else None
        if "asset_id = ANY" in sql:
            ids = set(p[0])
            fica = [r for r in rows if not (r["id"] in ids and tenant in (None, r["tenant"]))]
            self.rowcount = len(rows) - len(fica)
            b.tabelas[tabela] = fica
            return
        limite = p.pop(0)
        menor_ou_igual = "<= %s" in sql
        retidos = set(p.pop(0)) if "contact_id = ANY" in sql else set()

        def casa(r: dict) -> bool:
            if com_tenant and r["tenant"] != tenant:
                return False
            if not (r["ts"] <= limite if menor_ou_igual else r["ts"] < limite):
                return False
            if r.get("contacto") in retidos:
                return False
            if "HAVING max(greatest" in sql and not r.get("fecho", r["ts"]) < limite:
                return False
            return True

        if sql.lstrip().startswith("DELETE"):
            fica = [r for r in rows if not casa(r)]
            self.rowcount = len(rows) - len(fica)
            b.tabelas[tabela] = fica
        elif "SELECT DISTINCT tenant_id" in sql:
            self.linhas_ = [(t,) for t in sorted({r["tenant"] for r in rows if casa(r)})]
        elif "SELECT asset_id" in sql:
            self.linhas_ = [(r["id"], r.get("ref"), r.get("size", 1)) for r in rows if casa(r)]
        else:
            self.linhas_ = [(sum(1 for r in rows if casa(r)),)]


class LigacaoFalsa:
    autocommit = False

    def __init__(self, base: BaseFalsa) -> None:
        self.base = base

    def cursor(self) -> CursorFalso:
        self.base.comecar()
        return CursorFalso(self.base)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        self.base.reverter()

    def close(self) -> None:
        pass


class ParticoesFalsas:
    """O gestor do dono (`db/particoes.py`), sobre a base falsa."""

    def __init__(self, base: BaseFalsa, falhar: bool = False) -> None:
        self.base, self.falhar = base, falhar

    def criar(self, tabela, mes) -> None:
        if self.falhar:
            raise Falhou("criar particao")
        self.base.criadas.append((tabela, mes))

    def largar(self, tabela, mes) -> None:
        b = self.base
        b.largadas.append((tabela, mes))
        b.particoes[tabela].remove(f"{tabela.split('.')[1]}_{mes:%Y_%m}")
        b.tabelas[tabela] = [r for r in b.tabelas.get(tabela, []) if f"{r['ts']:%Y_%m}" != f"{mes:%Y_%m}"]


class StorageFalso:
    def __init__(self, falhar_na: int | None = None, inexistentes=()) -> None:
        self.apagados: list[tuple[str, str]] = []
        self.falhar_na = falhar_na
        self.inexistentes = set(inexistentes)

    def delete(self, ctx, ref) -> None:
        if self.falhar_na is not None and len(self.apagados) == self.falhar_na:
            raise Falhou("armazenamento")
        if ref.key in self.inexistentes:
            raise ObjectoInexistenteError()
        self.apagados.append((ctx.tenant_id, ref.key))


def so(*nomes: str) -> tuple[Classe, ...]:
    """A politica reduzida as classes nomeadas (as recusas das outras sao ruido)."""
    return tuple(c for c in politica.POLITICA if c.nome in nomes)


def execucao(base: BaseFalsa, *classes: str, **kw) -> jobs.Execucao:
    kw.setdefault("politica", so(*classes) if classes else politica.POLITICA)
    return jobs.Execucao(abrir_ligacao=lambda: LigacaoFalsa(base), agora=AGORA, **kw)


def registos(base: BaseFalsa, **filtro) -> list[dict]:
    campos = ("execucao_id", "classe", "tabela", "tenant_id", "modo", "resultado",
              "motivo", "linhas", "objectos", "janela_ate", "politica_versao", "iniciado_at")
    linhas = [dict(zip(campos, r)) for r in base.purge_log]
    return [r for r in linhas if all(r[k] == v for k, v in filtro.items())]


# --------------------------------------------------------------- a politica


class TestAPolitica(unittest.TestCase):
    """Criterio 1: as classes do `08` §11, com os valores do bloco, todos proposta."""

    ESPERADO = {
        "conversas": Prazo(dias=90),
        "audio": Prazo(horas=24),
        "assistant_queries": Prazo(meses=13),
        "assistant_query_texto": Prazo(dias=90),
        "logs_tecnicos": Prazo(dias=30),
        "events_outbox": Prazo(dias=7),
        "events_log": Prazo(meses=24),
        "events_consumed": Prazo(dias=90),
        "events_dlq": Prazo(dias=30),
        "backup_wal": Prazo(dias=7),
        "backup_diario": Prazo(dias=35),
    }

    def test_as_classes_do_criterio_1_com_os_prazos_do_bloco(self):
        for nome, prazo in self.ESPERADO.items():
            with self.subTest(nome):
                self.assertEqual(politica.classe(nome).prazo, prazo)

    def test_os_maximos_do_criterio_1(self):
        self.assertEqual(politica.classe("conversas").maximo, Prazo(dias=365))
        self.assertEqual(politica.classe("audio").maximo, Prazo(horas=72))

    def test_todos_os_prazos_sao_proposta(self):
        self.assertEqual({c.estado for c in politica.POLITICA}, {"proposta"})

    def test_a_politica_valida(self):
        politica.validar()

    def test_o_criterio_8_lg_e_chatwoot_estao_incluidos(self):
        self.assertEqual(politica.classe("lg_checkpoints").mecanismo, politica.DELEGADO)
        self.assertEqual(politica.classe("chatwoot").mecanismo, politica.EXTERNO)

    def test_um_prazo_a_facto_e_recusado(self):
        alterada = tuple(
            replace(c, estado="facto") if c.nome == "conversas" else c for c in politica.POLITICA
        )
        with self.assertRaisesRegex(politica.PoliticaInvalida, "proposta"):
            politica.validar(alterada)

    def test_o_erasure_ledger_nao_pode_ser_purgado(self):
        """Sem ele, um restauro devolve titulares apagados sem ninguem saber."""
        for intocavel in ("platform.erasure_ledger", "platform.purge_log"):
            with self.subTest(intocavel):
                outra = tuple(
                    replace(c, tabelas=tuple(t for t in c.tabelas if t.nome != intocavel))
                    if c.nome == "registo_de_conformidade"
                    else replace(c, tabelas=(*c.tabelas, Tabela(intocavel, True)))
                    if c.nome == "events_outbox"
                    else c
                    for c in politica.POLITICA
                )
                with self.assertRaisesRegex(politica.PoliticaInvalida, "ressuscitar"):
                    politica.validar(outra)

    def test_uma_classe_fiscal_com_prazo_e_recusada(self):
        alterada = tuple(
            replace(c, prazo=Prazo(meses=60)) if c.nome == "fiscal_pagamentos" else c
            for c in politica.POLITICA
        )
        with self.assertRaisesRegex(politica.PoliticaInvalida, "omissao"):
            politica.validar(alterada)

    def test_uma_tabela_em_duas_classes_e_recusada(self):
        alterada = tuple(
            replace(c, tabelas=(*c.tabelas, Tabela("platform.events_consumed", True)))
            if c.nome == "events_outbox" else c
            for c in politica.POLITICA
        )
        with self.assertRaisesRegex(politica.PoliticaInvalida, "mais do que uma"):
            politica.validar(alterada)

    def test_uma_tabela_numa_classe_e_sem_dados_e_recusada(self):
        sem = dict(politica.SEM_DADOS_PESSOAIS, **{"platform.events_outbox": "x"})
        with self.assertRaisesRegex(politica.PoliticaInvalida, "sem dados"):
            politica.validar(politica.POLITICA, sem)

    def test_por_ligar_sem_pendencia_e_recusada(self):
        alterada = tuple(
            replace(c, tabelas=(Tabela("platform.handoffs"),)) if c.nome == "conversas" else c
            for c in politica.POLITICA
        )
        with self.assertRaisesRegex(politica.PoliticaInvalida, "porque"):
            politica.validar(alterada)

    def test_uma_tabela_fiscal_nao_se_liga(self):
        alterada = tuple(
            replace(c, tabelas=(Tabela("platform.payment_events", True),))
            if c.nome == "fiscal_pagamentos" else c
            for c in politica.POLITICA
        )
        with self.assertRaisesRegex(politica.PoliticaInvalida, "decisao"):
            politica.validar(alterada)


class TestAsJanelas(unittest.TestCase):
    """Unit do bloco: calculo de janelas com relogio simulado, por classe."""

    def test_horas_dias_e_meses(self):
        casos = {
            "audio": AGORA - timedelta(hours=24),
            "events_outbox": AGORA - timedelta(days=7),
            "conversas": AGORA - timedelta(days=90),
            "assistant_queries": datetime(2025, 10, 10, 3, 0, tzinfo=timezone.utc),
            "events_log": datetime(2024, 11, 10, 3, 0, tzinfo=timezone.utc),
        }
        for nome, esperado in casos.items():
            with self.subTest(nome):
                self.assertEqual(politica.limite(politica.classe(nome), AGORA), esperado)

    def test_os_meses_nao_transbordam(self):
        fim_de_marco = datetime(2026, 3, 31, tzinfo=timezone.utc)
        self.assertEqual(politica.recuar_meses(fim_de_marco, 1).date().isoformat(), "2026-02-28")
        self.assertEqual(
            politica.recuar_meses(datetime(2025, 3, 31, tzinfo=timezone.utc), 13).date().isoformat(),
            "2024-02-29",
        )

    def test_um_instante_sem_fuso_e_recusado(self):
        with self.assertRaises(politica.PoliticaInvalida):
            Prazo(dias=1).antes_de(datetime(2026, 1, 1))

    def test_as_classes_que_nao_purgam_nao_tem_limite(self):
        self.assertIsNone(politica.limite(politica.classe("registo_de_conformidade"), AGORA))

    def test_o_fiscal_sem_parametro_nao_tem_limite(self):
        for nome in ("fiscal_encomendas", "fiscal_pagamentos", "fiscal_facturas"):
            with self.subTest(nome):
                self.assertIsNone(politica.limite(politica.classe(nome), AGORA))

    def test_o_fiscal_com_parametro_conta_anos(self):
        self.assertEqual(
            politica.limite(politica.classe("fiscal_pagamentos"), AGORA, anos_fiscais=10),
            datetime(2016, 11, 10, 3, 0, tzinfo=timezone.utc),
        )

    def test_o_alargamento_da_pme_ate_ao_maximo(self):
        conversas = politica.classe("conversas")
        self.assertEqual(
            politica.limite(conversas, AGORA, alargamento=Prazo(dias=365)),
            AGORA - timedelta(days=365),
        )
        with self.assertRaisesRegex(politica.PoliticaInvalida, "maximo"):
            politica.limite(conversas, AGORA, alargamento=Prazo(dias=366))
        with self.assertRaisesRegex(politica.PoliticaInvalida, "alargamento"):
            politica.limite(politica.classe("events_outbox"), AGORA, alargamento=Prazo(dias=8))

    def test_o_alargamento_exige_justificacao(self):
        with self.assertRaisesRegex(politica.PoliticaInvalida, "justificacao"):
            jobs.Alargamento(Prazo(dias=200), "  ")


class TestOParametroFiscal(unittest.TestCase):
    """Criterio 4: sem valor por omissao, e um valor mal escrito levanta."""

    def test_sem_variavel_e_nulo(self):
        self.assertIsNone(politica.fiscal_retention_years({}))
        self.assertIsNone(politica.fiscal_retention_years({politica.VARIAVEL_FISCAL: " "}))

    def test_um_inteiro(self):
        self.assertEqual(politica.fiscal_retention_years({politica.VARIAVEL_FISCAL: "10"}), 10)

    def test_um_valor_mal_escrito_levanta_e_nao_se_le_como_nulo(self):
        for valor in ("0", "31", "dez", "-5", "7.5"):
            with self.subTest(valor), self.assertRaises(politica.PoliticaInvalida):
                politica.fiscal_retention_years({politica.VARIAVEL_FISCAL: valor})


class TestAsSuperficiesConcordam(unittest.TestCase):
    """Duas leitoras da mesma pergunta divergem sem nenhum portao o ver (KAM-069)."""

    def test_as_ligadas_da_politica_sao_as_que_o_job_purga(self):
        no_job = {a.tabela for ks in jobs.CAMINHOS.values() for k in ks for a in (k, *k.antes)}
        no_job |= {"platform.media_assets"}
        no_job |= {p.tabela for p in jobs.PARTICIONADAS.values()}
        self.assertEqual(politica.tabelas_ligadas(), frozenset(no_job))

    def test_as_tabelas_fiscais_tem_coluna(self):
        fiscais = {t.nome for c in politica.POLITICA if c.fiscal for t in c.tabelas}
        self.assertEqual(fiscais, set(jobs.COLUNA_FISCAL))

    def test_os_backups_sao_os_da_cobertura(self):
        """O `infra/backup/cobertura.yaml` (KAM-079) e a outra superficie."""
        texto = (RAIZ / "infra" / "backup" / "cobertura.yaml").read_text(encoding="utf-8")
        pitr = int(re.search(r"^\s*pitr_dias:\s*(\d+)", texto, re.M).group(1))
        dias = int(re.search(r"^\s*retencao_dias:\s*(\d+)", texto, re.M).group(1))
        self.assertEqual(politica.classe("backup_wal").prazo, Prazo(dias=pitr))
        self.assertEqual(politica.classe("backup_diario").prazo, Prazo(dias=dias))

    def test_os_prazos_dos_eventos_sao_os_das_funcoes_da_0005(self):
        texto = (RAIZ / "db" / "migrations" / "versions" / "0005_consumo_dlq.py").read_text(encoding="utf-8")
        consumidos = int(re.search(r"evt_limpar_consumidos\(p_dias int DEFAULT (\d+)\)", texto).group(1))
        dlq = int(re.search(r"evt_limpar_dlq\(p_dias int DEFAULT (\d+)\)", texto).group(1))
        self.assertEqual(politica.classe("events_consumed").prazo, Prazo(dias=consumidos))
        self.assertEqual(politica.classe("events_dlq").prazo, Prazo(dias=dlq))

    def test_o_job_so_apaga_e_larga(self):
        """Sem `UPDATE` em massa nem `INSERT` em tabelas de dados (criterio 7)."""
        textos = [k.sql_apagar for ks in jobs.CAMINHOS.values() for k0 in ks for k in (k0, *k0.antes)]
        textos += [jobs.SQL_MIDIA_APAGAR]
        for texto in textos:
            with self.subTest(texto[:40]):
                self.assertTrue(texto.lstrip().startswith("DELETE"))
                self.assertNotIn("UPDATE", texto)
                self.assertNotIn("INSERT", texto)

    def test_o_purge_log_nao_tem_onde_por_um_titular(self):
        self.assertNotIn("contact", purge_log.SQL_ESCREVER)
        self.assertNotIn("storage_ref", purge_log.SQL_ESCREVER)

    def test_cada_instrucao_por_tenant_leva_o_tenant(self):
        for ks in jobs.CAMINHOS.values():
            for k0 in ks:
                for k in (k0, *k0.antes):
                    if k.global_:
                        continue
                    with self.subTest(k.tabela):
                        self.assertIn("tenant_id = %s::uuid", k.sql_contar)
                        self.assertIn("tenant_id = %s::uuid", k.sql_apagar)
        self.assertIn("tenant_id = %s::uuid", jobs.SQL_MIDIA_VENCIDA)
        self.assertIn("tenant_id = %s::uuid", jobs.SQL_MIDIA_APAGAR)


class TestORegisto(unittest.TestCase):
    def _r(self, **kw):
        base = dict(execucao_id="e", classe="c", tabela="t", tenant_id=None,
                    modo="efectiva", resultado="ok", motivo=None, linhas=1, objectos=0,
                    janela_ate=None, politica_versao="v", iniciado_at=AGORA)
        base.update(kw)
        return purge_log.Registo(**base)

    def test_um_ok_sem_motivo_e_o_resto_com_motivo(self):
        self._r()
        with self.assertRaises(ValueError):
            self._r(motivo="erro")
        with self.assertRaises(ValueError):
            self._r(resultado="falhou", linhas=0)

    def test_o_motivo_e_fechado(self):
        with self.assertRaises(ValueError):
            self._r(resultado="recusada", motivo="o joao pediu", linhas=0)

    def test_so_um_ok_apaga(self):
        with self.assertRaises(ValueError):
            self._r(resultado="retida", motivo="hold_tenant", linhas=3)


# ------------------------------------------------------------------- o job


class TestOJob(unittest.TestCase):
    def setUp(self):
        self.base = BaseFalsa()

    def test_a_sessao_de_lote_vai_ao_audit_log_primeiro(self):
        """Criterio 8: o papel `kamba_batch` com sessao registada."""
        jobs.executar(execucao(self.base, "events_outbox"))
        self.assertIn("audit_append", self.base.instrucoes[0])
        self.assertIn("'batch.run'", self.base.instrucoes[0])
        self.assertEqual(self.base.auditoria[0][0], jobs.ACTOR_DO_LOTE)

    def test_apaga_so_o_que_passou_a_janela(self):
        self.base.linhas("platform.events_outbox", tenant=A, ts=AGORA - timedelta(days=8))
        self.base.linhas("platform.events_outbox", tenant=A, ts=AGORA - timedelta(days=6))
        relatorio = jobs.executar(execucao(self.base, "events_outbox"))
        self.assertEqual(self.base.contar("platform.events_outbox"), 1)
        self.assertEqual(relatorio.linhas("events_outbox"), 1)
        [r] = registos(self.base, classe="events_outbox")
        self.assertEqual((r["tenant_id"], r["resultado"], r["linhas"]), (A, "ok", 1))
        self.assertEqual(r["janela_ate"], AGORA - timedelta(days=7))

    def test_o_hold_de_um_tenant_nao_deixa_tocar_nele_e_o_outro_sai(self):
        for t in (A, B):
            self.base.linhas("platform.events_outbox", tenant=t, ts=AGORA - timedelta(days=30))
        self.base.holds.append((B, hold.ENTIDADE_TENANT, B))
        jobs.executar(execucao(self.base, "events_outbox"))
        self.assertEqual(self.base.contar("platform.events_outbox", A), 0)
        self.assertEqual(self.base.contar("platform.events_outbox", B), 1)
        self.assertEqual(registos(self.base, tenant_id=B)[0]["motivo"], "hold_tenant")

    def test_canario_a_base_falsa_morde(self):
        """Sem o `tenant_id` no `DELETE`, a purga de A leva as linhas de B."""
        for t in (A, B):
            self.base.linhas("platform.events_outbox", tenant=t, ts=AGORA - timedelta(days=30))
        self.base.holds.append((B, hold.ENTIDADE_TENANT, B))
        sem_tenant = replace(
            jobs.CAMINHO_OUTBOX,
            sql_apagar="DELETE FROM platform.events_outbox WHERE publicado_at < %s",
        )
        with mock.patch.dict(jobs.CAMINHOS, {"events_outbox": (sem_tenant,)}), \
                mock.patch.object(jobs.Caminho, "parametros", lambda s, t, l, r: (l,)):
            jobs.executar(execucao(self.base, "events_outbox"))
        self.assertEqual(self.base.contar("platform.events_outbox", B), 0)

    def test_o_hold_de_contacto_tira_so_esse_contacto(self):
        velho = AGORA - timedelta(days=200)
        for c in (JOAO, MARIA):
            self.base.linhas("platform.outbound_messages", tenant=A, ts=velho,
                             contacto=c, fecho=velho)
        self.base.holds.append((A, hold.ENTIDADE_CONTACTO, JOAO))
        jobs.executar(execucao(self.base, "conversas"))
        ficou = [r["contacto"] for r in self.base.tabelas["platform.outbound_messages"]]
        self.assertEqual(ficou, [JOAO])

    def test_o_hold_de_contacto_retem_uma_tabela_sem_contact_id(self):
        self.base.linhas("platform.events_outbox", tenant=A, ts=AGORA - timedelta(days=30))
        self.base.holds.append((A, hold.ENTIDADE_CONTACTO, JOAO))
        jobs.executar(execucao(self.base, "events_outbox"))
        self.assertEqual(self.base.contar("platform.events_outbox"), 1)
        self.assertEqual(registos(self.base)[0]["motivo"], "hold_contacto")

    def test_a_conversa_conta_do_fecho_e_nao_da_mensagem(self):
        self.base.linhas("platform.outbound_messages", tenant=A, contacto=JOAO,
                         ts=AGORA - timedelta(days=200), fecho=AGORA - timedelta(days=10))
        jobs.executar(execucao(self.base, "conversas"))
        self.assertEqual(self.base.contar("platform.outbound_messages"), 1)

    def test_o_alargamento_da_pme_e_por_tenant(self):
        for t in (A, B):
            self.base.linhas("platform.outbound_messages", tenant=t, contacto=JOAO,
                             ts=AGORA - timedelta(days=120), fecho=AGORA - timedelta(days=120))
        x = execucao(self.base, "conversas",
                     alargamentos={B: jobs.Alargamento(Prazo(dias=300), "contencioso aberto")})
        jobs.executar(x)
        self.assertEqual(self.base.contar("platform.outbound_messages", A), 0)
        self.assertEqual(self.base.contar("platform.outbound_messages", B), 1)

    def test_o_dry_run_lista_e_nao_apaga(self):
        self.base.linhas("platform.events_consumed", tenant=A, ts=AGORA - timedelta(days=100))
        relatorio = jobs.executar(execucao(self.base, "events_consumed", dry_run=True))
        self.assertEqual(self.base.contar("platform.events_consumed"), 1)
        self.assertFalse(any(s.lstrip().startswith("DELETE") for s in self.base.instrucoes))
        [r] = registos(self.base, tabela="platform.events_consumed")
        self.assertEqual((r["modo"], r["linhas"]), ("dry_run", 1))
        self.assertEqual(relatorio.linhas(), 1)

    def test_repetir_a_janela_apaga_zero_e_nao_altera_o_resultado(self):
        self.base.linhas("platform.events_consumed", tenant=A, ts=AGORA - timedelta(days=100))
        jobs.executar(execucao(self.base, "events_consumed"))
        jobs.executar(execucao(self.base, "events_consumed"))
        linhas = [r["linhas"] for r in registos(self.base, tabela="platform.events_consumed")]
        self.assertEqual(linhas, [1])  # a segunda nao encontra tenant com linhas

    def test_uma_falha_nao_deixa_estado_parcial_e_e_sev2(self):
        """As aprovacoes e a DLQ saem juntas ou nenhuma (criterio 5)."""
        velho = AGORA - timedelta(days=40)
        self.base.linhas("platform.events_dlq", tenant=A, ts=velho)
        self.base.linhas("platform.evt_dlq_aprovacoes", tenant=A, ts=velho)
        self.base.falhar_em = "DELETE FROM platform.events_dlq"
        relatorio = jobs.executar(execucao(self.base, "events_dlq"))
        self.assertEqual(self.base.contar("platform.evt_dlq_aprovacoes"), 1)
        self.assertEqual(self.base.contar("platform.events_dlq"), 1)
        self.assertTrue(relatorio.sev2)
        self.assertEqual([r["resultado"] for r in registos(self.base)], ["falhou"])
        with self.assertRaisesRegex(jobs.PurgaFalhou, "Sev2"):
            jobs.exigir_sem_falhas(relatorio)

    def test_as_tabelas_por_ligar_sao_recusadas_e_nunca_ok(self):
        jobs.executar(execucao(self.base, "conversas"))
        recusadas = {r["tabela"] for r in registos(self.base, resultado="recusada")}
        por_ligar = {t.nome for t in politica.classe("conversas").tabelas if not t.ligada}
        self.assertEqual(recusadas, por_ligar)


class TestOFiscal(unittest.TestCase):
    """Criterio 4: dez anos de dados fiscais e o parametro nulo apagam zero."""

    def setUp(self):
        self.base = BaseFalsa()
        for anos in range(1, 11):
            self.base.linhas("platform.payment_events", tenant=A, ts=AGORA - timedelta(days=366 * anos))
            self.base.linhas("platform.orders_mirror", tenant=A, ts=AGORA - timedelta(days=366 * anos))

    def test_sem_parametro_recusa_regista_o_motivo_e_apaga_zero(self):
        relatorio = jobs.executar(execucao(self.base, "fiscal_encomendas", "fiscal_pagamentos"))
        self.assertEqual(self.base.contar("platform.payment_events"), 10)
        self.assertEqual(self.base.contar("platform.orders_mirror"), 10)
        self.assertEqual(relatorio.linhas(), 0)
        motivos = {r["motivo"] for r in registos(self.base)}
        self.assertEqual(motivos, {"fiscal_sem_prazo"})
        self.assertFalse(any(s.lstrip().startswith("DELETE") for s in self.base.instrucoes))

    def test_com_parametro_o_dry_run_lista_o_que_sairia(self):
        jobs.executar(execucao(self.base, "fiscal_pagamentos", dry_run=True, anos_fiscais=5))
        [r] = registos(self.base, tabela="platform.payment_events")
        # Anos de 366 dias contra um limite de calendario: a linha do quinto ano
        # (1830 dias) ja passou os cinco anos, e saem as do 5.o ao 10.o.
        self.assertEqual((r["resultado"], r["linhas"]), ("ok", 6))
        self.assertEqual(self.base.contar("platform.payment_events"), 10)

    def test_com_parametro_a_efectiva_recusa_por_imutavel(self):
        jobs.executar(execucao(self.base, "fiscal_pagamentos", anos_fiscais=5))
        self.assertEqual(self.base.contar("platform.payment_events"), 10)
        self.assertEqual({r["motivo"] for r in registos(self.base)}, {"fiscal_imutavel"})


class TestOsObjectos(unittest.TestCase):
    """Criterio 3: TTL no STO, o objecto primeiro e a linha depois."""

    def setUp(self):
        self.base = BaseFalsa()
        vencido = AGORA - timedelta(hours=1)
        for n in range(3):
            self.base.linhas("platform.media_assets", tenant=A, id=f"a{n}", ref=f"t/{A}/media_audio/{n}",
                             ts=vencido, contacto=JOAO)
        self.base.linhas("platform.media_assets", tenant=A, id="novo", ref="r", ts=AGORA + timedelta(hours=5))

    def test_apaga_os_vencidos_objecto_e_linha(self):
        storage = StorageFalso()
        jobs.executar(execucao(self.base, "audio", storage=storage))
        self.assertEqual(len(storage.apagados), 3)
        self.assertEqual([r["id"] for r in self.base.tabelas["platform.media_assets"]], ["novo"])
        [r] = registos(self.base, resultado="ok")
        self.assertEqual((r["linhas"], r["objectos"]), (3, 3))

    def test_uma_falha_no_armazenamento_deixa_a_linha_e_a_seguinte_acaba(self):
        storage = StorageFalso(falhar_na=1)
        relatorio = jobs.executar(execucao(self.base, "audio", storage=storage))
        self.assertTrue(relatorio.sev2)
        self.assertEqual(self.base.contar("platform.media_assets"), 4)
        segundo = StorageFalso(inexistentes={storage.apagados[0][1]})
        jobs.executar(execucao(self.base, "audio", storage=segundo))
        self.assertEqual(self.base.contar("platform.media_assets"), 1)

    def test_sem_armazenamento_a_efectiva_recusa(self):
        jobs.executar(execucao(self.base, "audio"))
        self.assertEqual(self.base.contar("platform.media_assets"), 4)
        self.assertEqual(registos(self.base)[0]["motivo"], "sem_caminho")

    def test_o_hold_de_contacto_guarda_o_audio(self):
        self.base.holds.append((A, hold.ENTIDADE_CONTACTO, JOAO))
        jobs.executar(execucao(self.base, "audio", storage=StorageFalso()))
        self.assertEqual(self.base.contar("platform.media_assets"), 4)


class TestAsParticoes(unittest.TestCase):
    """Criterio 7: `DROP` de particao, e a criacao de M+1 e M+2."""

    def setUp(self):
        self.base = BaseFalsa()
        self.base.particoes["platform.events_log"] = [
            "events_log_2024_09", "events_log_2024_10", "events_log_2024_11", "events_log_default",
        ]
        for mes in (9, 10, 11):
            self.base.linhas("platform.events_log", tenant=A, ts=datetime(2024, mes, 5, tzinfo=timezone.utc))

    def test_larga_os_meses_vencidos_e_cria_os_dois_seguintes(self):
        jobs.executar(execucao(self.base, "events_log", particoes=ParticoesFalsas(self.base)))
        # limite: 2024-11-10; o mes de Outubro acaba a 1 de Novembro, o de
        # Novembro so a 1 de Dezembro.
        self.assertEqual([m.month for _, m in self.base.largadas], [9, 10])
        self.assertEqual([m.isoformat() for _, m in self.base.criadas],
                         ["2026-12-01", "2027-01-01"])

    def test_um_hold_de_um_tenant_presente_retem_o_mes(self):
        self.base.holds.append((A, hold.ENTIDADE_CONTACTO, JOAO))
        jobs.executar(execucao(self.base, "events_log", particoes=ParticoesFalsas(self.base)))
        self.assertEqual(self.base.largadas, [])
        self.assertEqual({r["resultado"] for r in registos(self.base)} - {"recusada"}, {"retida"})

    def test_a_falha_ao_criar_m_mais_2_e_sev2(self):
        relatorio = jobs.executar(execucao(
            self.base, "events_log", particoes=ParticoesFalsas(self.base, falhar=True)))
        self.assertTrue(relatorio.sev2)
        self.assertIn("particao_por_criar", {r.motivo for r in relatorio.falhas})

    def test_sem_gestor_a_criacao_falha_e_nada_se_larga(self):
        relatorio = jobs.executar(execucao(self.base, "events_log"))
        self.assertTrue(relatorio.sev2)
        self.assertEqual(self.base.largadas, [])
        self.assertIn("sem_caminho", {r["motivo"] for r in registos(self.base, resultado="recusada")})

    def test_o_dry_run_nao_cria_nem_larga(self):
        jobs.executar(execucao(self.base, "events_log", dry_run=True,
                               particoes=ParticoesFalsas(self.base)))
        self.assertEqual((self.base.criadas, self.base.largadas), ([], []))
        self.assertEqual(sorted(r["linhas"] for r in registos(self.base, resultado="ok")), [1, 1])

    def test_a_default_nunca_se_larga(self):
        self.assertIsNone(jobs._mes_da_particao(jobs.PARTICIONADAS["events_log"], "events_log_default"))


class TestORestauro(unittest.TestCase):
    """O caso que tem de ficar vermelho: um restauro que traz de volta o que a
    purga e o *erasure ledger* tiraram."""

    def test_o_que_o_restauro_trouxe_sai_outra_vez(self):
        base = BaseFalsa()
        base.linhas("platform.events_consumed", tenant=A, ts=AGORA - timedelta(days=100))
        jobs.executar(execucao(base, "events_consumed"))
        self.assertEqual(base.contar("platform.events_consumed"), 0)
        # o restauro: a linha volta, e o purge_log fica a dizer que a janela
        # ja correu — o pior caso, o de um restauro logico de uma tabela.
        base.linhas("platform.events_consumed", tenant=A, ts=AGORA - timedelta(days=100))
        restaurado_de = AGORA - timedelta(days=95)
        base.ledger = [(JOAO, AGORA - timedelta(days=96)), (MARIA, AGORA - timedelta(days=2))]
        relatorio, sujeitos = jobs.reaplicar_apos_restauro(
            execucao(base, "events_consumed"), restaurado_de
        )
        self.assertEqual(base.contar("platform.events_consumed"), 0)
        self.assertEqual(relatorio.linhas(), 1)
        self.assertEqual([s.contact_id for s in sujeitos], [MARIA])

    def test_a_reaplicacao_nao_e_um_dry_run(self):
        with self.assertRaises(politica.PoliticaInvalida):
            jobs.reaplicar_apos_restauro(execucao(BaseFalsa(), dry_run=True), AGORA)


class TestOResto(unittest.TestCase):
    def test_o_delegado_corre_e_sem_ele_recusa(self):
        base = BaseFalsa()
        jobs.executar(execucao(base, "lg_checkpoints"))
        self.assertEqual({r["motivo"] for r in registos(base)}, {"sem_caminho"})
        base = BaseFalsa()
        jobs.executar(execucao(base, "lg_checkpoints", delegados={"lg_checkpoints": lambda lig, agora: 4}))
        self.assertEqual(registos(base)[0]["linhas"], 4)

    def test_a_verificacao_do_audio(self):
        """A base falsa nao interpreta o `FILTER`: mede-se que a consulta pede os
        dois limites e exclui os holds, pela ordem. A contagem real e da bateria
        de base de dados."""
        base = BaseFalsa()
        base.holds.append((B, hold.ENTIDADE_TENANT, B))
        base.holds.append((A, hold.ENTIDADE_CONTACTO, JOAO))
        pedidos = []

        class Cursor(CursorFalso):
            def execute(self, sql, parametros=()):
                if "media_audio" in sql:
                    pedidos.append(parametros)
                    self.linhas_ = [(2, 1)]
                    return
                super().execute(sql, parametros)

        with mock.patch.object(LigacaoFalsa, "cursor", lambda s: Cursor(base)):
            self.assertEqual(jobs.verificar_audio(lambda: LigacaoFalsa(base), AGORA), (2, 1))
        [p] = pedidos
        self.assertEqual(p, (AGORA - timedelta(hours=24), AGORA - timedelta(hours=72), [B], [JOAO]))

    def test_o_encerramento_e_aos_30_dias(self):
        self.assertTrue(jobs.encerramento_devido(AGORA - timedelta(days=30), AGORA))
        self.assertFalse(jobs.encerramento_devido(AGORA - timedelta(days=29), AGORA))

    def test_um_agora_sem_fuso_e_recusado(self):
        with self.assertRaises(politica.PoliticaInvalida):
            jobs.executar(jobs.Execucao(abrir_ligacao=lambda: None, agora=datetime(2026, 1, 1)))


if __name__ == "__main__":
    unittest.main()
