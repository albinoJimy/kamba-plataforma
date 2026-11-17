"""Os KPIs de churn do KAM-117, sem base de dados.

    TestLimiares   o `config/kpis.yaml` le-se, e tudo o resto falha fechado
    TestMetricas   os tres nomes, o dominio do `sinal` e a exposicao
    TestEnsaio     quando o *job* esta em modo de ensaio
    TestFluxo      a ordem dos passos, com uma ligacao roteirizada

**O que estes ensaios nao provam:** que os sinais estao certos. Quem o prova e
o `db/tests/test_kpis_churn_schema.py`, contra PostgreSQL, com relogio fixo. A
ligacao daqui devolve linhas escritas a mao e so serve para medir o que o
Python faz com elas: a porta chamada antes da marca, o tenant poupado, a falha
que nao para os outros, o ensaio que nao zera.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from kamba_core.kpis import churn, limiares, metricas

RAIZ = Path(__file__).resolve().parents[3]
CONFIG = RAIZ / "config" / "kpis.yaml"
AGORA = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)

VALIDO = """
version: 1
dono_sem_actividade_dias: 7
sem_pedidos_dias: 14
pagamento_em_atraso_dias: 5
catalogo_desactualizado_dias: 28
dormente_dias: 60
dormente_janela_clientes_dias: 30
dormente_aviso_dias: 7
modo_ensaio_dias: 14
"""


class TestLimiares(unittest.TestCase):
    def test_o_ficheiro_versionado_le_se_com_os_valores_do_bloco(self) -> None:
        l = limiares.ler(CONFIG)
        self.assertEqual(
            (l.dono_sem_actividade_dias, l.sem_pedidos_dias, l.pagamento_em_atraso_dias,
             l.catalogo_desactualizado_dias, l.dormente_dias, l.dormente_aviso_dias,
             l.modo_ensaio_dias),
            (7, 14, 5, 28, 60, 7, 14),
        )
        self.assertEqual(l.dormente_janela_clientes_dias, 30)

    def test_para_sql_tem_as_chaves_todas(self) -> None:
        self.assertEqual(sorted(limiares.interpretar(VALIDO).para_sql()), sorted(limiares.CHAVES))

    def test_tudo_o_que_nao_e_a_forma_falha_fechado(self) -> None:
        casos = {
            "chave desconhecida": VALIDO + "outra_dias: 3\n",
            "chave repetida": VALIDO + "sem_pedidos_dias: 3\n",
            "valor nao inteiro": VALIDO.replace("sem_pedidos_dias: 14", "sem_pedidos_dias: 1.5"),
            "valor zero": VALIDO.replace("sem_pedidos_dias: 14", "sem_pedidos_dias: 0"),
            "chave em falta": VALIDO.replace("sem_pedidos_dias: 14\n", ""),
            "sem versao": VALIDO.replace("version: 1\n", ""),
            "outra versao": VALIDO.replace("version: 1", "version: 2"),
            "linha que nao e chave": VALIDO + "- lista\n",
            "aviso depois do dormente": VALIDO.replace(
                "dormente_aviso_dias: 7", "dormente_aviso_dias: 60"),
        }
        for nome, texto in casos.items():
            with self.subTest(nome), self.assertRaises(limiares.LimiaresInvalidos):
                limiares.interpretar(texto)

    def test_comentarios_e_linhas_em_branco_passam(self) -> None:
        texto = "# cabecalho\n\n" + VALIDO.replace("sem_pedidos_dias: 14", "sem_pedidos_dias: 14  # n")
        self.assertEqual(limiares.interpretar(texto).sem_pedidos_dias, 14)


class TestMetricas(unittest.TestCase):
    def test_os_tres_nomes_do_bloco(self) -> None:
        self.assertEqual(
            sorted(metricas._AJUDA),
            ["churn_signal", "onboarding_activation_minutes", "tenants_dormentes"],
        )
        for nome, (tipo, ajuda) in metricas._AJUDA.items():
            with self.subTest(nome):
                self.assertEqual(tipo, "gauge")
                self.assertTrue(ajuda.strip())

    def test_o_dominio_e_fechado_em_cinco_e_casa_a_gramatica(self) -> None:
        self.assertEqual(len(metricas.SINAIS), 5)
        for sinal in metricas.SINAIS:
            self.assertRegex(sinal, metricas.ETIQUETA)
        m = metricas.MetricasDeKpis()
        with self.assertRaises(metricas.ValorInvalido):
            m.definir_sinais({"dormente": 1})
        with self.assertRaises(metricas.ValorInvalido):
            m.definir_sinais({"sem_pedidos": -1})
        with self.assertRaises(metricas.ValorInvalido):
            m.definir_dormentes(True)  # type: ignore[arg-type]

    def test_a_activacao_recusa_nan_e_negativos(self) -> None:
        m = metricas.MetricasDeKpis()
        for valor in (float("nan"), -1.0):
            with self.subTest(valor), self.assertRaises(metricas.ValorInvalido):
                m.definir_activacao(valor)

    def test_sem_corrida_nao_ha_valores_e_depois_os_cinco_aparecem(self) -> None:
        m = metricas.MetricasDeKpis()
        vazia = m.exposicao()
        self.assertIn("# TYPE churn_signal gauge", vazia)
        self.assertNotIn('churn_signal{', vazia)
        self.assertNotIn("\ntenants_dormentes ", vazia)
        m.definir_sinais({"sem_pedidos": 2})
        m.definir_dormentes(1)
        m.definir_activacao(42.5)
        cheia = m.exposicao()
        for sinal in metricas.SINAIS:
            self.assertIn(f'churn_signal{{sinal="{sinal}"}}', cheia)
        self.assertIn('churn_signal{sinal="sem_pedidos"} 2', cheia)
        self.assertIn('churn_signal{sinal="dono_inactivo"} 0', cheia)
        self.assertIn("tenants_dormentes 1", cheia)
        self.assertIn("onboarding_activation_minutes 42.5", cheia)
        m.definir_activacao(60.0)
        self.assertIn("onboarding_activation_minutes 60\n", m.exposicao())
        m.definir_activacao(None)
        self.assertNotIn("\nonboarding_activation_minutes ", m.exposicao())

    def test_nenhuma_etiqueta_e_um_identificador(self) -> None:
        m = metricas.MetricasDeKpis()
        m.definir_sinais({})
        texto = m.exposicao()
        for proibida in ("tenant", "contact", "phone", "telefone"):
            self.assertNotIn(proibida + "_id=", texto)
            self.assertNotIn(proibida + "=", texto)


class _Aviso:
    def __init__(self) -> None:
        self.avisados: list[str] = []

    def avisar_dormente(self, tenant_id: str) -> None:
        self.avisados.append(tenant_id)


class _Porta:
    def __init__(self, falha: set[str] | None = None) -> None:
        self.chamadas: list[tuple[str, str]] = []
        self.falha = falha or set()

    def zerar(self, tenant_id: str) -> None:
        if tenant_id in self.falha:
            raise ConnectionError("litellm em baixo")
        self.chamadas.append(("zerar", tenant_id))

    def repor(self, tenant_id: str) -> None:
        self.chamadas.append(("repor", tenant_id))


class _Cursor:
    """Responde por **qual** constante SQL foi executada, com linhas escritas."""

    def __init__(self, base: "_Base") -> None:
        self.base = base
        self._linhas: list[tuple] = []
        self.rowcount = 0

    def execute(self, sql: str, parametros: tuple = ()) -> None:
        self.base.registo.append((sql, parametros))
        self.rowcount = self.base.contagens.get(sql, 1)
        self._linhas = list(self.base.respostas.get(sql, []))
        if sql == churn.SQL_CLIENTES_NA_JANELA:
            # Pela **janela** e nao pelo tenant: o ultimo cliente de cada tenant
            # e um instante, e conta se cair entre o inicio dela e agora.
            tenant, desde, ate = parametros
            ultimo = self.base.ultimo_cliente.get(tenant)
            self._linhas = [(ultimo is not None and desde < ultimo <= ate,)]
        if sql == churn.SQL_ZERADO and self.base.falha_ao_marcar:
            raise RuntimeError("a marca falhou")
        if sql == churn.SQL_TRANCAR_EPISODIO:
            self._linhas = [self.base.episodios.get(parametros[0], (None, None, None))]

    def fetchall(self) -> list[tuple]:
        return self._linhas

    def fetchone(self) -> tuple | None:
        return self._linhas[0] if self._linhas else None


class _Ligacao:
    def __init__(self, base: "_Base") -> None:
        self.base = base

    def cursor(self) -> _Cursor:
        return _Cursor(self.base)

    def commit(self) -> None:
        self.base.commits += 1

    def rollback(self) -> None:
        self.base.rollbacks += 1

    def close(self) -> None:
        pass


class _Base:
    def __init__(self) -> None:
        self.registo: list[tuple[str, tuple]] = []
        self.respostas: dict[str, list[tuple]] = {}
        self.episodios: dict[str, tuple] = {}
        self.contagens: dict[str, int] = {}
        self.ultimo_cliente: dict[str, datetime] = {}
        self.falha_ao_marcar = False
        self.commits = 0
        self.rollbacks = 0

    def abrir(self) -> _Ligacao:
        return _Ligacao(self)

    def sqls(self) -> list[str]:
        return [s for s, _ in self.registo]


def _execucao(base: _Base, porta: _Porta, piloto: date | None = date(2026, 10, 1),
              m: metricas.MetricasDeKpis | None = None,
              aviso: _Aviso | None = None) -> churn.Execucao:
    return churn.Execucao(
        abrir_ligacao=base.abrir, agora=AGORA, limiares=limiares.interpretar(VALIDO),
        orcamento=porta, aviso=aviso, piloto_inicio=piloto, metricas=m,
    )


class TestEnsaio(unittest.TestCase):
    def test_sem_inicio_do_piloto_e_sempre_ensaio(self) -> None:
        self.assertTrue(_execucao(_Base(), _Porta(), piloto=None).ensaio)

    def test_os_primeiros_catorze_dias_sao_ensaio_e_o_decimo_quinto_nao(self) -> None:
        inicio = (AGORA - timedelta(days=14)).date()
        self.assertFalse(_execucao(_Base(), _Porta(), piloto=inicio).ensaio)
        self.assertTrue(_execucao(_Base(), _Porta(), piloto=inicio + timedelta(days=1)).ensaio)

    def test_o_relogio_sem_fuso_e_recusado(self) -> None:
        with self.assertRaises(ValueError):
            churn.Execucao(abrir_ligacao=_Base().abrir, agora=datetime(2026, 1, 1),
                           limiares=limiares.interpretar(VALIDO), orcamento=_Porta())


class TestFluxo(unittest.TestCase):
    def _base_com_dormente(self) -> _Base:
        base = _Base()
        base.respostas[churn.SQL_SINAIS] = [("t-a", "dormente", True), ("t-b", "sem_pedidos", None)]
        base.contagens[churn.SQL_ABRIR] = 2
        base.respostas[churn.SQL_POR_ZERAR] = [("e-a", "t-a"), ("e-x", "t-x")]
        base.episodios["e-a"] = (None, None, None)
        return base

    def test_abre_os_novos_fecha_os_velhos_e_zera_o_pleno(self) -> None:
        base = self._base_com_dormente()
        porta = _Porta()
        m = metricas.MetricasDeKpis()
        base.respostas[churn.SQL_ACTIVACAO] = [(1800.0,)]
        relatorio = churn.executar(_execucao(base, porta, m=m))
        self.assertFalse(relatorio.ensaio)
        self.assertEqual(relatorio.abertos, 2)
        self.assertEqual(relatorio.fechados, 1)
        # O `t-x` nao e pleno nesta corrida: nao se zera.
        self.assertEqual(relatorio.zerados, ["t-a"])
        self.assertEqual(porta.chamadas, [("zerar", "t-a")])
        sqls = base.sqls()
        self.assertEqual(sqls[0], churn.SQL_TRANCA)
        # A porta antes da marca, e a marca antes do registo.
        i = sqls.index(churn.SQL_ZERADO)
        self.assertLess(sqls.index(churn.SQL_CLIENTES_NA_JANELA), i)
        self.assertEqual(sqls[i + 1], churn.SQL_AUDITAR)
        auditoria = [p for s, p in base.registo if s == churn.SQL_AUDITAR][0]
        self.assertEqual(auditoria[2], churn.ACCAO_ZERADO)
        self.assertNotIn("contact", auditoria[4])
        estado = m.ler()
        self.assertEqual(estado["sinais"]["sem_pedidos"], 1)
        self.assertEqual(estado["dormentes"], 1)
        self.assertEqual(estado["activacao"], 30.0)

    def test_em_ensaio_nao_zera_nada_mas_regista_os_sinais(self) -> None:
        base = self._base_com_dormente()
        porta = _Porta()
        relatorio = churn.executar(_execucao(base, porta, piloto=None))
        self.assertTrue(relatorio.ensaio)
        self.assertEqual(porta.chamadas, [])
        self.assertNotIn(churn.SQL_POR_ZERAR, base.sqls())
        self.assertEqual(relatorio.sinais, [("t-a", "dormente"), ("t-b", "sem_pedidos")])
        abrir = [p for s, p in base.registo if s == churn.SQL_ABRIR]
        self.assertEqual(len(abrir), 1)  # uma instrucao para todos
        self.assertIs(abrir[0][1], True)
        self.assertEqual(json.loads(abrir[0][2]), [
            {"tenant_id": "t-a", "sinal": "dormente"},
            {"tenant_id": "t-b", "sinal": "sem_pedidos"}])

    def test_com_clientes_na_janela_e_poupado_e_fora_dela_nao(self) -> None:
        for quando, poupado in ((AGORA - timedelta(days=2), True),
                                (AGORA - timedelta(days=31), False),
                                (AGORA + timedelta(days=1), False)):
            with self.subTest(quando=quando):
                base = self._base_com_dormente()
                base.ultimo_cliente["t-a"] = quando
                porta = _Porta()
                relatorio = churn.executar(_execucao(base, porta))
                self.assertEqual(relatorio.poupados, ["t-a"] if poupado else [])
                self.assertEqual(porta.chamadas, [] if poupado else [("zerar", "t-a")])
        janela = [p for s, p in base.registo if s == churn.SQL_CLIENTES_NA_JANELA][0]
        self.assertEqual(janela[1:], (AGORA - timedelta(days=30), AGORA))

    def test_sem_porta_de_aviso_nao_avisa_e_com_ela_avisa_uma_vez(self) -> None:
        base = self._base_com_dormente()
        churn.executar(_execucao(base, _Porta()))
        self.assertNotIn(churn.SQL_POR_AVISAR, base.sqls())
        base = self._base_com_dormente()
        base.respostas[churn.SQL_POR_AVISAR] = [("e-a", "t-a")]
        aviso = _Aviso()
        relatorio = churn.executar(_execucao(base, _Porta(), aviso=aviso))
        self.assertEqual((aviso.avisados, relatorio.avisados), (["t-a"], ["t-a"]))
        sqls = base.sqls()
        self.assertLess(sqls.index(churn.SQL_AVISADO), sqls.index(churn.SQL_POR_ZERAR))
        # Em ensaio nao se avisa.
        base = self._base_com_dormente()
        base.respostas[churn.SQL_POR_AVISAR] = [("e-a", "t-a")]
        aviso = _Aviso()
        churn.executar(_execucao(base, _Porta(), piloto=None, aviso=aviso))
        self.assertEqual(aviso.avisados, [])

    def test_a_marca_que_falha_depois_da_porta_repoe_o_orcamento(self) -> None:
        base = self._base_com_dormente()
        base.falha_ao_marcar = True
        porta = _Porta()
        relatorio = churn.executar(_execucao(base, porta))
        self.assertEqual(porta.chamadas, [("zerar", "t-a"), ("repor", "t-a")])
        self.assertEqual(relatorio.zerados, [])
        self.assertEqual(relatorio.falhas, [("t-a", "RuntimeError")])

    def test_o_episodio_ja_zerado_nao_chama_a_porta(self) -> None:
        base = self._base_com_dormente()
        base.episodios["e-a"] = (None, AGORA, None)
        porta = _Porta()
        relatorio = churn.executar(_execucao(base, porta))
        self.assertEqual((relatorio.zerados, porta.chamadas), ([], []))

    def test_uma_porta_que_falha_reverte_esse_tenant_e_nao_para_os_outros(self) -> None:
        base = self._base_com_dormente()
        base.respostas[churn.SQL_SINAIS].append(("t-x", "dormente", True))
        base.episodios["e-x"] = (None, None, None)
        porta = _Porta(falha={"t-a"})
        relatorio = churn.executar(_execucao(base, porta))
        self.assertEqual(relatorio.falhas, [("t-a", "ConnectionError")])
        self.assertEqual(relatorio.zerados, ["t-x"])
        self.assertGreaterEqual(base.rollbacks, 1)

    def test_repor_chama_a_porta_marca_e_audita_e_a_reactivacao_so_repoe(self) -> None:
        base = _Base()
        base.respostas[churn.SQL_POR_REPOR] = [("e-a", "t-a"), ("e-b", "t-b")]
        base.episodios["e-a"] = (AGORA, AGORA, None)
        base.episodios["e-b"] = (None, AGORA, AGORA)  # ja reposto: nada
        porta = _Porta()
        relatorio = churn.reactivar(_execucao(base, porta))
        self.assertEqual(relatorio.repostos, ["t-a"])
        self.assertEqual(porta.chamadas, [("repor", "t-a")])
        self.assertNotIn(churn.SQL_SINAIS, base.sqls())
        accoes = [p[2] for s, p in base.registo if s == churn.SQL_AUDITAR]
        self.assertEqual(accoes, [churn.ACCAO_REPOSTO])

    def test_sem_metricas_nao_le_a_activacao(self) -> None:
        base = _Base()
        churn.executar(_execucao(base, _Porta()))
        self.assertNotIn(churn.SQL_ACTIVACAO, base.sqls())


if __name__ == "__main__":
    unittest.main()
