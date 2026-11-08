"""As metricas de backup do KAM-079.

    TestDeclaracao   os quatro nomes, o tipo e a ajuda sao o que o bloco pede?
    TestContador     o desfecho tem dominio fechado e aparece sempre?
    TestGauges       o que acontece quando ainda nao ha medicao?
    TestExposicao    o formato de exposicao e legivel por um raspador?
"""

from __future__ import annotations

import math
import unittest

from kamba_core.backup import metricas as m


class TestDeclaracao(unittest.TestCase):
    def test_os_quatro_nomes(self) -> None:
        self.assertEqual(
            sorted(m._AJUDA),
            [
                "backup_restauro_debito_mbps",
                "backup_restauro_desfecho_total",
                "backup_restauro_duracao_segundos",
                "backup_wal_idade_segundos",
            ],
        )

    def test_a_idade_do_wal_e_um_gauge_e_o_desfecho_um_counter(self) -> None:
        """Nao e cosmetica: somar uma idade de WAL nao quer dizer nada, e um
        *gauge* de restauros perdia a contagem das duas execucoes que o
        criterio 5 pede."""
        self.assertEqual(m._AJUDA[m.METRICA_WAL_IDADE][0], "gauge")
        self.assertEqual(m._AJUDA[m.METRICA_RESTAURO_DESFECHO][0], "counter")

    def test_toda_a_metrica_tem_ajuda_nao_vazia(self) -> None:
        for nome, (_, ajuda) in m._AJUDA.items():
            with self.subTest(nome=nome):
                self.assertTrue(ajuda.strip())

    def test_a_unidade_esta_no_nome(self) -> None:
        """Confundir megabits com megabytes da um factor de 8, e um factor de 8
        num orcamento de RTO e a diferenca entre 30 minutos e 4 horas."""
        self.assertTrue(m.METRICA_RESTAURO_DEBITO.endswith("_mbps"))
        self.assertTrue(m.METRICA_WAL_IDADE.endswith("_segundos"))
        self.assertTrue(m.METRICA_RESTAURO_DURACAO.endswith("_segundos"))

    def test_nenhum_nome_leva_etiqueta_de_tenant_nem_de_destino(self) -> None:
        """Um backup e do **cluster** e nao de um tenant (`OBS-I`), e o nome do
        `repo1` e um FQDN — a localizacao do repositorio num painel."""
        self.assertEqual(set(m._NOME_DA_ETIQUETA.values()), {"desfecho"})

    def test_a_gramatica_da_etiqueta_e_a_mesma_das_outras_bibliotecas(self) -> None:
        """A mesma do `ten/metricas.py:45`, repetida de proposito: as duas sao a
        mesma regra e nenhuma importa a outra."""
        self.assertEqual(m.ETIQUETA.pattern, r"^[a-z][a-z0-9_]{1,62}$")
        for desfecho in m.DESFECHOS:
            self.assertRegex(desfecho, m.ETIQUETA)


class TestContador(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = m.MetricasDeBackup()

    def test_conta_os_tres_desfechos(self) -> None:
        self.metricas.contar_desfecho("ok")
        self.metricas.contar_desfecho("ok")
        self.metricas.contar_desfecho("falhado")
        estado = self.metricas.ler()
        self.assertEqual(estado["desfechos"], {"ok": 2, "falhado": 1})

    def test_o_quanto_soma_o_que_lhe_dao_e_nao_um(self) -> None:
        """Achado da revisao adversarial: o parametro nunca foi exercitado.

        Trocar `+ quanto` por `+ 1` deixava as 22 provas deste modulo verdes, e
        um `job` que recuperasse varios desfechos de uma vez — a forma como um
        agendador relata o que correu enquanto esteve em baixo — contaria um.
        """
        self.metricas.contar_desfecho("ok", quanto=3)
        self.metricas.contar_desfecho("ok")
        self.metricas.contar_desfecho("falhado", quanto=2)
        self.assertEqual(
            self.metricas.ler()["desfechos"], {"ok": 4, "falhado": 2}
        )

    def test_o_quanto_tem_omissao_de_um(self) -> None:
        """A omissao e a chamada corrente, e fica prendida a parte do `quanto`."""
        self.metricas.contar_desfecho("ok")
        self.assertEqual(self.metricas.ler()["desfechos"], {"ok": 1})

    def test_um_desfecho_fora_dos_tres_recusa_se(self) -> None:
        """A lista e fechada porque e o vocabulario do criterio 5 e nao um campo
        livre: um `desfecho="talvez"` num painel nao se distingue de um erro de
        escrita."""
        with self.assertRaises(m.DesfechoInvalido):
            self.metricas.contar_desfecho("talvez")

    def test_o_inconclusivo_existe_e_e_distinto_de_falhado(self) -> None:
        """A razao e a do *smoke* da Meta no KAM-078: um restauro que nao correu
        porque o *host* descartavel nao arrancou nao e um restauro falhado, e
        juntar os dois casos apagava a diferenca entre «a rede de seguranca esta
        rota» e «nao a conseguimos testar»."""
        self.assertIn("inconclusivo", m.DESFECHOS)
        self.metricas.contar_desfecho("inconclusivo")
        self.assertEqual(
            self.metricas.ler()["desfechos"], {"inconclusivo": 1}
        )


class TestGauges(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = m.MetricasDeBackup()

    def test_sem_medicao_o_gauge_esta_ausente_e_nao_a_zero(self) -> None:
        """**O caso que mais importa deste modulo.**

        Um `backup_wal_idade_segundos 0` sem medicao nenhuma le-se como «acabou
        de arquivar» — a leitura mais errada possivel, e exactamente a que o
        alerta `> 300` nao apanharia. Ausente, o `absent()` do PromQL ve-o.
        """
        exposicao = self.metricas.exposicao()
        self.assertIn(f"# TYPE {m.METRICA_WAL_IDADE} gauge", exposicao)
        self.assertNotIn(f"\n{m.METRICA_WAL_IDADE} ", exposicao)

    def test_o_contador_aparece_a_zero_e_o_gauge_nao(self) -> None:
        """A assimetria e deliberada, e as duas metades tem razao propria: um
        contador a zero distingue «nenhum restauro falhou» de «o processo nao
        arrancou»; um *gauge* a zero mente."""
        exposicao = self.metricas.exposicao()
        self.assertIn(f'{m.METRICA_RESTAURO_DESFECHO}{{desfecho="ok"}} 0', exposicao)
        self.assertNotIn(f"\n{m.METRICA_RESTAURO_DURACAO} ", exposicao)

    def test_o_infinito_aceita_se_e_expoe_se_como_o_prometheus_quer(self) -> None:
        """`inf` e o valor com significado que a idade do WAL toma quando nunca
        se arquivou nada — e dispara o alerta, que e o que esse estado merece.
        A grafia e `+Inf`: `inf` seria recusado pelo raspador."""
        self.metricas.definir(m.METRICA_WAL_IDADE, math.inf)
        self.assertIn(f"{m.METRICA_WAL_IDADE} +Inf", self.metricas.exposicao())

    def test_o_nan_recusa_se(self) -> None:
        """Uma comparacao com `NaN` e sempre falsa, pelo que um alerta `> 300`
        deixaria de disparar **sem nada avisar**. O Prometheus aceita o `NaN` no
        formato de exposicao; a recusa tem de ser aqui."""
        with self.assertRaises(m.DesfechoInvalido) as caso:
            self.metricas.definir(m.METRICA_WAL_IDADE, float("nan"))
        self.assertIn("NaN", str(caso.exception))

    def test_um_gauge_que_nao_existe_recusa_se(self) -> None:
        with self.assertRaises(m.DesfechoInvalido):
            self.metricas.definir("backup_qualquer_coisa", 1.0)

    def test_o_contador_nao_se_define_como_gauge(self) -> None:
        with self.assertRaises(m.DesfechoInvalido):
            self.metricas.definir(m.METRICA_RESTAURO_DESFECHO, 1.0)

    def test_repor_limpa_as_duas_metades(self) -> None:
        self.metricas.contar_desfecho("ok")
        self.metricas.definir(m.METRICA_RESTAURO_DEBITO, 100.0)
        self.metricas.repor()
        estado = self.metricas.ler()
        self.assertEqual(estado["desfechos"], {})
        self.assertIsNone(estado["gauges"][m.METRICA_RESTAURO_DEBITO])


class TestExposicao(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = m.MetricasDeBackup()

    def test_tem_a_marca_que_o_inventario_do_obs_lint_procura(self) -> None:
        """O `tools/obs_lint/contar_metricas.py` define um modulo de metricas
        como «um ficheiro que contem `# TYPE`». Este ensaio prende a razao pela
        qual este modulo entrou naquele inventario."""
        self.assertIn("# TYPE", self.metricas.exposicao())

    def test_cada_metrica_tem_help_e_type(self) -> None:
        exposicao = self.metricas.exposicao()
        for nome in m._AJUDA:
            with self.subTest(nome=nome):
                self.assertIn(f"# HELP {nome} ", exposicao)
                self.assertIn(f"# TYPE {nome} ", exposicao)

    def test_um_inteiro_nao_sai_com_ponto(self) -> None:
        self.metricas.definir(m.METRICA_RESTAURO_DURACAO, 1600.0)
        self.assertIn(f"{m.METRICA_RESTAURO_DURACAO} 1600\n", self.metricas.exposicao())

    def test_um_decimal_sai_arredondado(self) -> None:
        self.metricas.definir(m.METRICA_RESTAURO_DEBITO, 100.123456789)
        self.assertIn(
            f"{m.METRICA_RESTAURO_DEBITO} 100.123457", self.metricas.exposicao()
        )

    def test_acaba_com_nova_linha(self) -> None:
        """Um raspador que receba a ultima linha sem `\\n` descarta-a."""
        self.assertTrue(self.metricas.exposicao().endswith("\n"))

    def test_nenhum_processo_do_repositorio_importa_este_modulo(self) -> None:
        """A premissa escrita no cabecalho do modulo, medida e nao afirmada.

        O dia em que um servico o importar, este ensaio fica vermelho — e e o
        sinal certo: o `exposta_por` das quatro no `ops/metricas/catalogo.yaml`
        deixa de poder estar vazio, e as duas entradas de `regras_por_escrever`
        passam a poder tornar-se regras de alerta.
        """
        import os
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        # Poda-se o `node_modules` **durante** a travessia e nao a filtrar
        # depois: um `rglob` que o atravesse le dezenas de milhares de ficheiros
        # e punha este ensaio em dezenas de segundos.
        ignoradas = {"node_modules", "__pycache__", ".venv", "dist", "tests"}
        encontrados: list[str] = []
        for pasta in ("services", "packages", "libs"):
            base = raiz / pasta
            if not base.is_dir():
                continue
            for actual, subpastas, ficheiros in os.walk(base):
                subpastas[:] = [d for d in subpastas if d not in ignoradas]
                for nome in ficheiros:
                    if not nome.endswith(".py"):
                        continue
                    caminho = Path(actual) / nome
                    if caminho.parts[-3:-1] == ("kamba_core", "backup"):
                        continue
                    texto = caminho.read_text(encoding="utf-8", errors="ignore")
                    if "kamba_core.backup" in texto:
                        encontrados.append(caminho.relative_to(raiz).as_posix())
        self.assertEqual(
            encontrados,
            [],
            "alguem passou a importar o modulo: as quatro metricas deixaram de "
            "estar `declarada_nao_exposta`",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
