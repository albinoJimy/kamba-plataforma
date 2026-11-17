"""Os KPIs de onboarding, os sinais de churn e os dormentes contra a base (KAM-117).

O que so uma base prova, e por isso este ficheiro existe:

1. **As fronteiras com relogio fixo** (criterio 3): 6 d 23 h nao dispara e 7 d
   dispara, e o mesmo para os pedidos, o catalogo, o pagamento e o dormente; o
   canal desligado e imediato; um tenant fora de `ativo` nao tem sinais.
2. **Os limiares falham fechado**: um em falta, zero ou nao inteiro levanta
   `22023`, e nao devolve zero sinais.
3. **O *job* contra a base**: duas corridas dao um episodio (idempotencia); o
   episodio fecha com a primeira actividade posterior; um dormente pleno so e
   zerado depois do aviso, uma vez, com `llm.orcamento_zerado` no `audit_log`;
   um tenant com mensagens de clientes recentes nunca e zerado; a actividade
   nova repoe o orcamento, uma vez, com `llm.orcamento_reposto`; o ensaio nao
   zera nada; cem tenants em menos de 60 s.
4. **O isolamento** (X-03): os sinais de A nao afectam B; a aplicacao nao le
   nada; a auditoria so ve o seu tenant.
5. **A vista semanal** (criterio 1): uma *fixture* de vinte casos bate
   exactamente com o calculo feito aqui, a mao, em Python.
6. **O `downgrade`** para a revisao de baixo, lida do ficheiro, e volta.

Tudo o que escreve corre numa transaccao do administrador que **nunca
confirma**; o *job* corre por *savepoints* com `SET ROLE kamba_batch`, como no
`test_retencao_bd.py`. Os instantes contam-se a partir do `now()` da
transaccao (`T0`), que e o `criado_at` de tudo o que nasce nela.
"""

from __future__ import annotations

import ast
import json
import statistics
import sys
import time
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import bootstrap
import ligacao

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

from kamba_core.kpis import churn, limiares, metricas  # noqa: E402
from tests import factories  # noqa: E402
from tests.base import (  # noqa: E402
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_kyc_schema import caso as novo_caso  # noqa: E402
from tests.test_revisao_schema import abrir as abrir_revisao  # noqa: E402
from tests.test_revisao_schema import decidir as decidir_revisao  # noqa: E402

#: Por *glob* e nao pelo numero: o numero e provisorio.
REVISAO = next((_RAIZ / "db" / "migrations" / "versions").glob("*_kpis_de_churn.py"))
CONFIG = _RAIZ / "config" / "kpis.yaml"
VALOR_INVALIDO = "22023"

#: Os limiares do bloco, escritos aqui e nao lidos do alvo.
LIMIARES = {
    "dono_sem_actividade_dias": 7,
    "sem_pedidos_dias": 14,
    "pagamento_em_atraso_dias": 5,
    "catalogo_desactualizado_dias": 28,
    "dormente_dias": 60,
    "dormente_janela_clientes_dias": 30,
    "dormente_aviso_dias": 7,
}

D = timedelta(days=1)
H = timedelta(hours=1)


def _anterior() -> str:
    for no in ast.parse(REVISAO.read_text(encoding="utf-8")).body:
        if isinstance(no, ast.Assign) and any(
            isinstance(alvo, ast.Name) and alvo.id == "down_revision" for alvo in no.targets
        ):
            return no.value.value  # type: ignore[attr-defined]
    raise AssertionError("a revisao nao declara down_revision")


class LigacaoDeEnsaio:
    """Uma transaccao do *job* com um papel, dentro da transaccao do ensaio."""

    def __init__(self, conexao, papel: str = "kamba_batch") -> None:
        self.conexao = conexao
        self.papel = papel

    def _executar(self, *instrucoes: str) -> None:
        cursor = self.conexao.cursor()
        for instrucao in instrucoes:
            cursor.execute(instrucao)

    def cursor(self):
        self._executar("SAVEPOINT unidade", f"SET ROLE {self.papel}")
        return self.conexao.cursor()

    def commit(self) -> None:
        self._executar("RESET ROLE", "RELEASE SAVEPOINT unidade")

    def rollback(self) -> None:
        self._executar("ROLLBACK TO SAVEPOINT unidade", "RELEASE SAVEPOINT unidade", "RESET ROLE")

    def close(self) -> None:
        pass


class PortaFalsa:
    """O orcamento LiteLLM falso: conta as chamadas e guarda o estado."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, str]] = []
        self.a_zero: set[str] = set()

    def zerar(self, tenant_id: str) -> None:
        self.chamadas.append(("zerar", tenant_id))
        self.a_zero.add(tenant_id)

    def repor(self, tenant_id: str) -> None:
        self.chamadas.append(("repor", tenant_id))
        self.a_zero.discard(tenant_id)


class AvisoFalso:
    """O aviso ao dono falso (KAM-115): conta quem foi avisado."""

    def __init__(self) -> None:
        self.avisados: list[str] = []

    def avisar_dormente(self, tenant_id: str) -> None:
        self.avisados.append(tenant_id)


class ComKpis(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cur = self.conexao.cursor()
        self.cur.execute("SELECT now()")
        self.t0: datetime = self.cur.fetchone()[0]
        self.cur.execute("SELECT (now() AT TIME ZONE 'Africa/Luanda')::date")
        self.hoje: date = self.cur.fetchone()[0]

    # -- sementes -----------------------------------------------------------
    def ativo(self, desde: datetime | None = None, estado: str = "ativo") -> str:
        """Um tenant `ativo`; `desde` e o instante da entrada em `ativo`."""
        tenant = factories.tenant(self.cur)
        factories.aceitar_contratos_vigentes(self.cur, tenant)
        self.cur.execute("UPDATE platform.tenants SET estado = %s WHERE id = %s",
                         (estado, tenant))
        if desde is not None:
            self.cur.execute(
                "INSERT INTO platform.tenant_state_log (tenant_id, de, para, motivo, actor, em) "
                "VALUES (%s, 'onboarding', 'ativo', 'ensaio', 'ensaio', %s)",
                (tenant, desde),
            )
        return tenant

    def canal(self, tenant: str, estado: str | None = None) -> str:
        campos = {"estado": estado} if estado else {}
        return factories.canal(self.cur, tenant, **campos)

    def echo(self, tenant: str, em: datetime) -> None:
        canal = self.canal(tenant)
        self.cur.execute(
            "INSERT INTO platform.channel_coexistence (tenant_id, channel_id, prazo_em, "
            "ultimo_echo_em) VALUES (%s, %s, now() + interval '1 day', %s)",
            (tenant, canal, em),
        )

    def pedido(self, tenant: str, em: datetime) -> None:
        contacto = factories.contacto(self.cur, tenant)
        self.cur.execute(
            "INSERT INTO platform.orders_mirror (tenant_id, contact_id, intent_key, "
            "total_minor, lines_snapshot, criado_at) VALUES (%s, %s, %s, 1000, '[]'::jsonb, %s)",
            (tenant, contacto, f"ik-{uuid.uuid4().hex[:12]}", em),
        )

    def cliente(self, tenant: str, em: datetime) -> None:
        contacto = factories.contacto(self.cur, tenant)
        canal = self.canal(tenant)
        self.cur.execute(
            "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id, "
            "last_inbound_at, window_expires_at) VALUES (%s, %s, %s, %s, %s)",
            (tenant, contacto, canal, em, em + 24 * H),
        )

    def dono_no_painel(self, tenant: str, accao: str = "stock.adjust") -> None:
        """Uma accao do dono no painel: `owner` no `audit_log`, `criado_at` = T0."""
        self.cur.execute(
            "SELECT platform.audit_append(%s, 'owner', 'dono', %s, 'offer_terms', 'sku-1', "
            "NULL, sha256('ensaio'::bytea))",
            (tenant, accao),
        )

    def ciclo(self, tenant: str, inicio: date, estado: str = "cobranca_emitida") -> None:
        self.cur.execute(
            "INSERT INTO platform.subscriptions (tenant_id, plano) VALUES (%s, 'basico') "
            "RETURNING id", (tenant,))
        assinatura = self.cur.fetchone()[0]
        self.cur.execute(
            "INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, "
            "valor_minor) VALUES (%s, %s, daterange(%s, %s), 100) RETURNING id",
            (assinatura, tenant, inicio, inicio + 30 * D),
        )
        ciclo = self.cur.fetchone()[0]
        if estado != "aberto":
            self.cur.execute("UPDATE platform.billing_cycles SET estado = %s WHERE id = %s",
                             (estado, ciclo))

    # -- leituras -----------------------------------------------------------
    def sinais(self, agora: datetime, tenant: str, **outros) -> dict[str, bool | None]:
        valores = dict(LIMIARES, **outros)
        self.cur.execute(
            "SELECT sinal, dormente_pleno FROM platform.churn_sinais(%s, %s::jsonb) "
            "WHERE tenant_id = %s",
            (agora, json.dumps(valores), tenant),
        )
        return {s: p for s, p in self.cur.fetchall()}

    def episodios(self, tenant: str) -> list[tuple]:
        self.cur.execute(
            "SELECT sinal, aberto_at, fechado_at, ensaio, orcamento_zerado_at, "
            "orcamento_reposto_at FROM platform.churn_signal_episode WHERE tenant_id = %s "
            "ORDER BY sinal, aberto_at",
            (tenant,),
        )
        return [tuple(linha) for linha in self.cur.fetchall()]

    def accoes(self, tenant: str) -> list[str]:
        self.cur.execute(
            "SELECT action FROM platform.audit_log WHERE tenant_id = %s "
            "AND action LIKE 'llm.%%' ORDER BY id", (tenant,))
        return [linha[0] for linha in self.cur.fetchall()]

    def execucao(self, agora: datetime, porta: PortaFalsa, ensaio: bool = False,
                 m: metricas.MetricasDeKpis | None = None,
                 aviso: AvisoFalso | None = None, sem_aviso: bool = False) -> churn.Execucao:
        return churn.Execucao(
            abrir_ligacao=lambda: LigacaoDeEnsaio(self.conexao),
            agora=agora,
            limiares=limiares.ler(CONFIG),
            orcamento=porta,
            aviso=None if sem_aviso else (aviso or AvisoFalso()),
            piloto_inicio=None if ensaio else date(2000, 1, 1),
            metricas=m,
        )

    def como(self, papel: str, tenant: str | None) -> None:
        self.cur.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.cur, tenant)

    def largar(self) -> None:
        self.cur.execute("RESET ROLE")


class TestEsquema(ComKpis):
    def test_o_dominio_do_sinal_e_o_das_metricas_mais_o_dormente(self) -> None:
        self.cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'churn_signal_episode_sinal_ck'")
        definicao = self.cur.fetchone()[0]
        for sinal in metricas.SINAIS + ("dormente",):
            self.assertIn(f"'{sinal}'", definicao)
        self.assertEqual(definicao.count("'::text"), 6)

    def test_o_config_versionado_e_o_do_bloco(self) -> None:
        lido = limiares.ler(CONFIG).para_sql()
        self.assertEqual({k: lido[k] for k in LIMIARES}, LIMIARES)

    def test_um_episodio_aberto_por_tenant_e_sinal(self) -> None:
        tenant = self.ativo()
        sql = ("INSERT INTO platform.churn_signal_episode (tenant_id, sinal, aberto_at, ensaio) "
               "VALUES (%s, 'sem_pedidos', now(), false)")
        self.cur.execute(sql, (tenant,))
        self.assertErroSql(VIOLACAO_DE_UNICIDADE, self.cur, sql, (tenant,))
        self.cur.execute("UPDATE platform.churn_signal_episode SET fechado_at = now() "
                         "WHERE tenant_id = %s", (tenant,))
        self.cur.execute(sql, (tenant,))  # o episodio seguinte abre

    def test_as_restricoes_do_orcamento_e_do_fecho(self) -> None:
        tenant = self.ativo()
        for sinal, extra in (
            ("sem_pedidos", "orcamento_zerado_at = now()"),
            ("sem_pedidos", "avisado_at = now()"),
            ("dormente", "orcamento_zerado_at = now()"),  # sem aviso, nao
            ("dormente", "orcamento_reposto_at = now()"),
            ("dormente", "fechado_at = now() - interval '1 day'"),
        ):
            with self.subTest(sinal=sinal, extra=extra):
                self.cur.execute(
                    "INSERT INTO platform.churn_signal_episode (tenant_id, sinal, aberto_at, "
                    "ensaio) VALUES (%s, %s, now(), false) RETURNING id", (tenant, sinal))
                episodio = self.cur.fetchone()[0]
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.cur,
                    f"UPDATE platform.churn_signal_episode SET {extra} WHERE id = %s",
                    (episodio,))
                self.cur.execute("DELETE FROM platform.churn_signal_episode WHERE id = %s",
                                 (episodio,))

    def test_as_vistas_nao_tem_colunas_de_pessoa(self) -> None:
        esperado = {
            "v_churn_signals": ["tenant_id", "sinal", "aberto_at", "ensaio"],
            "v_tenant_dormente": ["tenant_id", "aberto_at", "avisado_at",
                                  "orcamento_zerado_at", "orcamento_a_zero", "ensaio"],
            "v_onboarding_kpis_semanal": [
                "acumulado", "semana", "casos_activados", "owner_active_minutos_mediana",
                "dias_calendario_mediana", "sem_intervencao_ratio",
                "saga_primeira_tentativa_ratio", "fila_casos", "fila_no_sla_ratio"],
        }
        for vista, colunas in esperado.items():
            with self.subTest(vista=vista):
                self.cur.execute(
                    "SELECT column_name::text FROM information_schema.columns "
                    "WHERE table_schema = 'platform' AND table_name = %s "
                    "ORDER BY ordinal_position", (vista,))
                self.assertEqual([c for (c,) in self.cur.fetchall()], colunas)


class TestFronteiras(ComKpis):
    def test_dono_seis_dias_e_vinte_e_tres_horas_nao_sete_dias_sim(self) -> None:
        tenant = self.ativo(desde=self.t0 - 100 * D)
        self.echo(tenant, self.t0 - 10 * D)
        self.assertNotIn("dono_inactivo", self.sinais(self.t0 - 10 * D + 7 * D - H, tenant))
        self.assertIn("dono_inactivo", self.sinais(self.t0 - 10 * D + 7 * D, tenant))

    def test_o_painel_conta_como_actividade_do_dono(self) -> None:
        tenant = self.ativo(desde=self.t0 - 100 * D)
        self.assertIn("dono_inactivo", self.sinais(self.t0 + H, tenant))
        self.dono_no_painel(tenant)
        self.assertNotIn("dono_inactivo", self.sinais(self.t0 + H, tenant))

    def test_um_tenant_activado_ha_pouco_nao_esta_inactivo(self) -> None:
        tenant = self.ativo(desde=self.t0 - 6 * D)
        self.assertNotIn("dono_inactivo", self.sinais(self.t0, tenant))
        self.assertNotIn("sem_pedidos", self.sinais(self.t0, tenant))

    def test_pedidos_catorze_dias(self) -> None:
        tenant = self.ativo(desde=self.t0 - 100 * D)
        self.pedido(tenant, self.t0 - 14 * D + H)
        self.assertNotIn("sem_pedidos", self.sinais(self.t0, tenant))
        self.assertIn("sem_pedidos", self.sinais(self.t0 + H, tenant))

    def test_catalogo_vinte_e_oito_dias_e_a_actualizacao_o_fecha(self) -> None:
        tenant = self.ativo(desde=self.t0 - 28 * D + H)
        self.assertNotIn("catalogo_desactualizado", self.sinais(self.t0, tenant))
        self.assertIn("catalogo_desactualizado", self.sinais(self.t0 + H, tenant))
        self.dono_no_painel(tenant, "price.update")
        self.assertNotIn("catalogo_desactualizado", self.sinais(self.t0 + H, tenant))

    def test_canal_desligado_e_imediato_e_um_canal_vivo_o_apaga(self) -> None:
        tenant = self.ativo(desde=self.t0)
        self.canal(tenant, "desligado")
        self.assertIn("canal_desligado", self.sinais(self.t0, tenant))
        self.canal(tenant, "ativo")
        self.assertNotIn("canal_desligado", self.sinais(self.t0, tenant))

    def test_pagamento_cinco_dias_de_calendario_de_luanda(self) -> None:
        quatro, cinco, anulado = self.ativo(), self.ativo(), self.ativo()
        self.ciclo(quatro, self.hoje - 4 * D)
        self.ciclo(cinco, self.hoje - 5 * D)
        self.ciclo(anulado, self.hoje - 40 * D, estado="anulado")
        self.assertNotIn("pagamento_em_atraso", self.sinais(self.t0, quatro))
        self.assertIn("pagamento_em_atraso", self.sinais(self.t0, cinco))
        self.assertNotIn("pagamento_em_atraso", self.sinais(self.t0, anulado))

    def test_dormente_aviso_aos_cinquenta_e_tres_e_pleno_depois_dos_sessenta(self) -> None:
        tenant = self.ativo(desde=self.t0 - 60 * D)
        self.assertNotIn("dormente", self.sinais(self.t0 - 7 * D - H, tenant))
        self.assertIs(self.sinais(self.t0 - 7 * D, tenant)["dormente"], False)
        self.assertIs(self.sinais(self.t0, tenant)["dormente"], False)  # «> 60», e nao >=
        self.assertIs(self.sinais(self.t0 + H, tenant)["dormente"], True)

    def test_clientes_ou_pedidos_na_janela_tiram_a_marca(self) -> None:
        com_cliente, com_pedido, sem_nada = (
            self.ativo(desde=self.t0 - 90 * D) for _ in range(3))
        self.cliente(com_cliente, self.t0 - 29 * D)
        self.pedido(com_pedido, self.t0 - 29 * D)
        self.cliente(sem_nada, self.t0 - 31 * D)
        self.assertNotIn("dormente", self.sinais(self.t0, com_cliente))
        self.assertNotIn("dormente", self.sinais(self.t0, com_pedido))
        self.assertIs(self.sinais(self.t0, sem_nada)["dormente"], True)

    def test_fora_de_ativo_nao_ha_sinais(self) -> None:
        tenant = self.ativo(desde=self.t0 - 90 * D)
        self.cur.execute("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s",
                         (tenant,))
        self.assertEqual(self.sinais(self.t0, tenant), {})

    def test_um_limiar_invalido_falha_fechado(self) -> None:
        sql = "SELECT count(*) FROM platform.churn_sinais(%s, %s::jsonb)"
        for nome, valores in (
            ("em falta", {k: v for k, v in LIMIARES.items() if k != "sem_pedidos_dias"}),
            ("zero", dict(LIMIARES, sem_pedidos_dias=0)),
            ("texto", dict(LIMIARES, sem_pedidos_dias="7 dias")),
            ("negativo", dict(LIMIARES, sem_pedidos_dias=-1)),
            ("aviso depois do dormente", dict(LIMIARES, dormente_aviso_dias=60)),
            ("lista", [1, 2]),
        ):
            with self.subTest(nome):
                self.assertErroSql(VALOR_INVALIDO, self.cur, sql, (self.t0, json.dumps(valores)))
        self.assertErroSql(VALOR_INVALIDO, self.cur, sql, (None, json.dumps(LIMIARES)))


class TestJob(ComKpis):
    def test_duas_corridas_um_episodio_e_o_fecho_com_a_primeira_actividade(self) -> None:
        tenant = self.ativo(desde=self.t0 - 20 * D)
        porta = PortaFalsa()
        for _ in range(2):
            churn.executar(self.execucao(self.t0 - H, porta))
        abertos = [e for e in self.episodios(tenant) if e[0] == "dono_inactivo"]
        self.assertEqual(len(abertos), 1)
        self.assertIsNone(abertos[0][2])
        self.dono_no_painel(tenant)
        churn.executar(self.execucao(self.t0 + H, porta))
        fechado = [e for e in self.episodios(tenant) if e[0] == "dono_inactivo"]
        self.assertEqual(len(fechado), 1)
        self.assertEqual(fechado[0][2], self.t0 + H)
        self.cur.execute("SELECT count(*) FROM platform.v_churn_signals "
                         "WHERE tenant_id = %s AND sinal = 'dono_inactivo'", (tenant,))
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_o_dormente_e_zerado_depois_do_aviso_uma_vez_e_reposto_uma_vez(self) -> None:
        tenant = self.ativo(desde=self.t0 - 100 * D)
        porta = PortaFalsa()
        aviso = self.t0 - 10 * D
        churn.executar(self.execucao(aviso, porta))
        self.assertEqual(porta.chamadas, [])  # o aviso ainda nao tem sete dias
        for _ in range(2):  # duas execucoes, um efeito
            churn.executar(self.execucao(aviso + 7 * D, porta))
        self.assertEqual(porta.chamadas, [("zerar", tenant)])
        self.assertEqual(self.accoes(tenant), ["llm.orcamento_zerado"])
        self.cur.execute("SELECT orcamento_a_zero FROM platform.v_tenant_dormente "
                         "WHERE tenant_id = %s", (tenant,))
        self.assertEqual(self.cur.fetchone()[0], True)

        self.dono_no_painel(tenant)  # actividade nova, em T0
        for _ in range(2):
            churn.reactivar(self.execucao(self.t0 + timedelta(minutes=1), porta))
        self.assertEqual(porta.chamadas, [("zerar", tenant), ("repor", tenant)])
        self.assertEqual(self.accoes(tenant), ["llm.orcamento_zerado", "llm.orcamento_reposto"])
        self.assertNotIn(tenant, porta.a_zero)
        dormente = [e for e in self.episodios(tenant) if e[0] == "dormente"]
        self.assertEqual(len(dormente), 1)
        self.assertIsNotNone(dormente[0][2])  # fechado
        self.assertEqual(dormente[0][5], self.t0 + timedelta(minutes=1))

    def test_um_dormente_suspenso_nao_ve_o_orcamento_reposto(self) -> None:
        """Sair de `ativo` fecha o episodio, e fechar nao e voltar: fica a zero."""
        tenant = self.ativo(desde=self.t0 - 100 * D)
        porta = PortaFalsa()
        churn.executar(self.execucao(self.t0 - 10 * D, porta))
        churn.executar(self.execucao(self.t0 - 3 * D, porta))
        self.assertEqual(porta.chamadas, [("zerar", tenant)])
        self.cur.execute("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s",
                         (tenant,))
        churn.executar(self.execucao(self.t0 - 2 * D, porta))
        churn.reactivar(self.execucao(self.t0 - 2 * D, porta))
        self.assertEqual(porta.chamadas, [("zerar", tenant)])
        self.assertEqual(self.accoes(tenant), ["llm.orcamento_zerado"])

    def test_com_mensagens_de_clientes_recentes_nunca_e_posto_a_zero(self) -> None:
        """A mensagem e **anterior** a cada corrida (2, 9 e 16 dias), na janela."""
        tenant = self.ativo(desde=self.t0 - 100 * D)
        self.cliente(tenant, self.t0 - 2 * D)
        porta = PortaFalsa()
        for dias in (0, 7, 14):
            churn.executar(self.execucao(self.t0 + dias * D, porta))
        self.assertEqual(porta.chamadas, [])
        self.assertEqual(self.accoes(tenant), [])
        self.assertNotIn("dormente", [e[0] for e in self.episodios(tenant)])

    def test_sem_porta_de_aviso_nada_vai_a_zero(self) -> None:
        """O bloco: «aviso ao dono 7 dias antes; depois o orcamento passa a 0»."""
        tenant = self.ativo(desde=self.t0 - 100 * D)
        porta = PortaFalsa()
        for dias in (0, 7, 14):
            churn.executar(self.execucao(self.t0 - 20 * D + dias * D, porta, sem_aviso=True))
        self.assertEqual(porta.chamadas, [])
        self.cur.execute("SELECT avisado_at, orcamento_a_zero FROM platform.v_tenant_dormente "
                         "WHERE tenant_id = %s", (tenant,))
        self.assertEqual(tuple(self.cur.fetchone()), (None, False))

    def test_em_ensaio_regista_e_nao_zera(self) -> None:
        tenant = self.ativo(desde=self.t0 - 100 * D)
        porta = PortaFalsa()
        aviso = AvisoFalso()
        for dias in (0, 7):
            relatorio = churn.executar(self.execucao(self.t0 - 10 * D + dias * D, porta,
                                                     ensaio=True, aviso=aviso))
        self.assertTrue(relatorio.ensaio)
        self.assertIn((tenant, "dormente"), relatorio.sinais)
        self.assertEqual((porta.chamadas, aviso.avisados), ([], []))
        # Fora do ensaio: avisa na primeira corrida, e so zera sete dias depois.
        churn.executar(self.execucao(self.t0 - 2 * D, porta, aviso=aviso))
        self.assertEqual((porta.chamadas, aviso.avisados), ([], [tenant]))
        self.assertTrue(all(e[3] for e in self.episodios(tenant)))

    def test_os_sinais_de_a_nao_afectam_b(self) -> None:
        a = self.ativo(desde=self.t0 - 100 * D)
        b = self.ativo(desde=self.t0 - 4 * D)
        self.echo(b, self.t0 - 4 * D)
        self.pedido(b, self.t0 - 4 * D)
        self.dono_no_painel(b)
        porta = PortaFalsa()
        churn.executar(self.execucao(self.t0 - 3 * D, porta))
        churn.executar(self.execucao(self.t0 + 5 * D, porta))
        self.assertEqual(porta.chamadas, [("zerar", a)])
        self.assertEqual([e[0] for e in self.episodios(b)], [])
        self.assertEqual(self.accoes(b), [])
        # A auditoria so ve o seu tenant; a aplicacao nao le nada.
        self.como("kamba_audit", b)
        try:
            self.cur.execute("SELECT count(*) FROM platform.v_churn_signals")
            self.assertEqual(self.cur.fetchone()[0], 0)
            self.cur.execute("SELECT count(*) FROM platform.churn_signal_episode "
                             "WHERE tenant_id = %s", (a,))
            self.assertEqual(self.cur.fetchone()[0], 0)
        finally:
            self.largar()

    def test_as_metricas_publicam_sem_tenant(self) -> None:
        tenant = self.ativo(desde=self.t0 - 100 * D)
        m = metricas.MetricasDeKpis()
        churn.executar(self.execucao(self.t0, PortaFalsa(), m=m))
        texto = m.exposicao()
        self.assertNotIn(tenant, texto)
        self.assertRegex(texto, r'churn_signal\{sinal="dono_inactivo"\} [1-9]')
        self.assertRegex(texto, r"\ntenants_dormentes [1-9]")

    def test_cem_tenants_em_menos_de_sessenta_segundos(self) -> None:
        for i in range(100):
            tenant = self.ativo(desde=self.t0 - (i % 90) * D)
            if i % 3 == 0:
                self.pedido(tenant, self.t0 - (i % 20) * D)
            if i % 5 == 0:
                self.cliente(tenant, self.t0 - (i % 40) * D)
        inicio = time.monotonic()
        churn.executar(self.execucao(self.t0, PortaFalsa()))
        self.assertLess(time.monotonic() - inicio, 60.0)


class TestPrivilegios(ComKpis):
    def test_a_aplicacao_nao_le_nada(self) -> None:
        tenant = self.ativo()
        for alvo in ("platform.churn_signal_episode", "platform.v_churn_signals",
                     "platform.v_tenant_dormente", "platform.v_onboarding_kpis_semanal"):
            with self.subTest(alvo):
                self.como("kamba_app", tenant)
                try:
                    self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur,
                                       f"SELECT count(*) FROM {alvo}")
                finally:
                    self.largar()

    def test_o_lote_nao_apaga_nem_reescreve_o_sinal(self) -> None:
        tenant = self.ativo()
        self.cur.execute(
            "INSERT INTO platform.churn_signal_episode (tenant_id, sinal, aberto_at, ensaio) "
            "VALUES (%s, 'sem_pedidos', now(), false)", (tenant,))
        for sql in ("DELETE FROM platform.churn_signal_episode WHERE tenant_id = %s",
                    "UPDATE platform.churn_signal_episode SET sinal = 'dormente' "
                    "WHERE tenant_id = %s",
                    "UPDATE platform.churn_signal_episode SET aberto_at = now() "
                    "WHERE tenant_id = %s"):
            with self.subTest(sql):
                self.como("kamba_batch", None)
                try:
                    self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.cur, sql, (tenant,))
                finally:
                    self.largar()


class TestSemanal(ComKpis):
    """A *fixture* de vinte casos, e o oraculo feito aqui."""

    SEMANAS = (date(2020, 1, 6), date(2020, 1, 13))

    def _neutralizar(self) -> None:
        # A base e partilhada pela suite: o que outro ensaio tenha confirmado
        # sai das vistas nesta transaccao (desfeita no fim), e o oraculo e
        # exacto. A mesma tecnica do `test_eventos_do_tenant.TestKpis`.
        self.cur.execute("UPDATE platform.onboarding_case SET fase = 'cancelado' "
                         "WHERE fase = 'activo'")
        self.cur.execute("UPDATE platform.review_case SET onboarding_id = NULL "
                         "WHERE onboarding_id IS NOT NULL")

    def test_vinte_casos_batem_com_o_calculo_a_mao(self) -> None:
        self._neutralizar()
        fixture = []
        for i in range(20):
            semana = self.SEMANAS[i % 2]
            activo = datetime.combine(semana, datetime.min.time(), timezone.utc) + timedelta(
                days=1, hours=9 + i % 5)
            if i == 1:
                # Domingo as 23:30 UTC e segunda as 00:30 em Luanda: a semana e
                # a segunda (`SEMANAS[1]`), e so o e no fuso de Luanda.
                activo = datetime.combine(semana, datetime.min.time(), timezone.utc) - timedelta(
                    minutes=30)
            fixture.append({
                "semana": semana,
                "activo": activo,
                "criado": activo - timedelta(days=1 + i % 4, hours=i % 3),
                "segundos": 600 + 180 * i,
                "humano": i % 5 == 0,
                "tentativas": 2 if i % 7 == 0 else 1,
                # a fila: dentro do SLA, fora, ou por decidir e vencido
                "fila": ("no_sla", "fora", "vencido", None)[i % 4] if i % 5 == 0 else None,
            })
        for f in fixture:
            caso_id, tenant = novo_caso(
                self.cur, fase="activo", criado_at=f["criado"], activo_at=f["activo"],
                owner_active_seconds=f["segundos"])
            self.cur.execute(
                "INSERT INTO platform.provisioning_step (onboarding_id, tenant_id, step, "
                "status, attempt) VALUES (%s, %s, 'tenant_e_caso', 'concluido', %s)",
                (caso_id, tenant, f["tentativas"]))
            if f["humano"]:
                fila_at = datetime.combine(f["semana"], datetime.min.time(), timezone.utc) + 9 * H
                if f["fila"] in ("no_sla", None):
                    due = self.t0 + D
                else:
                    due = fila_at + D
                linha = abrir_revisao(self.cur, tenant, caso_id, motivo_codigo="ensaio",
                                      fila_at=fila_at, sla_alerta_at=fila_at, sla_due_at=due)
                if f["fila"] in ("no_sla", "fora"):
                    decidir_revisao(self.cur, linha[0], "aprovar")

        self.cur.execute(
            "SELECT acumulado, semana, casos_activados, owner_active_minutos_mediana, "
            "dias_calendario_mediana, sem_intervencao_ratio, saga_primeira_tentativa_ratio, "
            "fila_casos, fila_no_sla_ratio FROM platform.v_onboarding_kpis_semanal "
            "ORDER BY acumulado, semana")
        linhas = [tuple(l) for l in self.cur.fetchall()]

        def oraculo(casos: list[dict]) -> tuple:
            fila = [c for c in casos if c["fila"] in ("no_sla", "fora", "vencido")]
            return (
                len(casos),
                statistics.median(c["segundos"] for c in casos) / 60,
                statistics.median(
                    (c["activo"] - c["criado"]).total_seconds() / 86400 for c in casos),
                sum(not c["humano"] for c in casos) / len(casos),
                sum(c["tentativas"] == 1 for c in casos) / len(casos),
                len(fila),
                (sum(c["fila"] == "no_sla" for c in fila) / len(fila)) if fila else None,
            )

        esperado = [(False, s) + oraculo([c for c in fixture if c["semana"] == s])
                    for s in self.SEMANAS]
        esperado.append((True, None) + oraculo(fixture))
        self.assertEqual(len(linhas), 3)
        for obtida, certa in zip(linhas, esperado):
            with self.subTest(semana=certa[1]):
                self.assertEqual(obtida[:3], certa[:3])
                for o, c in zip(obtida[3:], certa[3:]):
                    if c is None:
                        self.assertIsNone(o)
                    else:
                        self.assertAlmostEqual(float(o), float(c), places=9)


class TestDowngradeDosKpis(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        # Os papeis primeiro: corrida sozinha, esta classe vem antes das outras
        # (ordem alfabetica) e o `kamba_migrator` ainda nao tem palavra-passe.
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_class WHERE relnamespace = 'platform'::regnamespace "
                      "AND relname IN ('churn_signal_episode', 'v_churn_signals', "
                      "'v_tenant_dormente', 'v_onboarding_kpis_semanal')")
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname IN "
                      "('churn_sinais', 'churn_dono_at')")
            n += int(c.fetchone()[0])
            c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                      "WHERE conname = 'audit_log_action'")
            return n + int("llm.orcamento_zerado" in c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._objectos(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), 7)


if __name__ == "__main__":
    unittest.main()
