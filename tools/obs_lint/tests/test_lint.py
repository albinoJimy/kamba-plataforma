"""Testes do `obs_lint` — o *lint* de cardinalidade e runbooks do KAM-080.

Tres classes, e a ordem delas e a ordem das perguntas:

    TestPolitica       a politica e a que o criterio 3 escreve?
    TestCardinalidade  cada regra morde o que deve, e so isso?
    TestRegras         os alertas levam severidade e runbook que existe?
    TestCanario        as fixtures provam que o lint morde?
    TestRepositorio    a arvore real passa, tendo lido alguma coisa?
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from obs_lint import canario as canario_mod
from obs_lint import cli, lint

RAIZ = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "canario"

UUID = "3f2a1c8e-5b7d-4e91-a0c2-6d4f8b1e9a37"


def _etiqueta(**campos):
    return dict(campos)


def _regras(etiqueta: dict) -> list[lint.Achado]:
    return lint._verificar_etiqueta("m_total", etiqueta, "catalogo")


def _nomes(achados: list[lint.Achado]) -> set[str]:
    return {a.regra for a in achados}


class TestPolitica(unittest.TestCase):
    """O criterio 3, a letra: «`tenant_id` permitido; `contact_id`, telefone e
    BSUID proibidos»."""

    def test_o_tenant_id_e_permitido_pelo_nome_e_nao_esta_nos_proibidos(self) -> None:
        self.assertIn("tenant_id", lint.ETIQUETAS_PERMITIDAS_POR_NOME)
        self.assertNotIn("tenant_id", lint.ETIQUETAS_PROIBIDAS)

    def test_as_duas_listas_nao_se_cruzam(self) -> None:
        """Um nome nas duas listas fazia a politica depender da ordem de leitura."""
        for nome in lint.ETIQUETAS_PERMITIDAS_POR_NOME:
            self.assertNotIn(nome, lint.ETIQUETAS_PROIBIDAS, nome)

    def test_os_tres_nomes_do_criterio_estao_proibidos(self) -> None:
        self.assertIn("contact_id", lint.ETIQUETAS_PROIBIDAS)
        self.assertIn("bsuid", lint.ETIQUETAS_PROIBIDAS)
        for telefone in ("telefone", "phone", "msisdn"):
            self.assertIn(telefone, lint.ETIQUETAS_PROIBIDAS, telefone)

    def test_cada_nome_proibido_tem_razao_escrita(self) -> None:
        """Uma mensagem sem razao faz quem a le pensar que o lint e arbitrario."""
        for nome, razao in lint.ETIQUETAS_PROIBIDAS.items():
            self.assertTrue(razao.strip(), nome)

    def test_cada_regra_obrigatoria_tem_uma_negativa_no_disco(self) -> None:
        pastas = {p.name.split("__", 1)[0] for p in (FIXTURES / "negativas").iterdir()}
        for regra in lint.REGRAS_OBRIGATORIAS:
            self.assertIn(regra, pastas, regra)


class TestCardinalidade(unittest.TestCase):
    """Cada regra de etiqueta, uma a uma e isolada."""

    def test_um_nome_proibido_da_etiqueta_proibida_e_so_isso(self) -> None:
        achados = _regras(_etiqueta(nome="contact_id", dominio=["a"]))
        self.assertEqual(_nomes(achados), {"etiqueta_proibida"})

    def test_o_nome_proibido_ganha_a_falta_de_dominio(self) -> None:
        """Um `contact_id` sem dominio devia dizer «identificador».

        «Falta o dominio» tambem e verdade e **nao e a razao**; dizer a segunda
        manda quem le acrescentar uma lista de contactos.
        """
        achados = _regras(_etiqueta(nome="contact_id"))
        self.assertEqual(_nomes(achados), {"etiqueta_proibida"})

    def test_o_tenant_id_passa_o_nome_e_morre_no_dominio(self) -> None:
        """A prova em duas metades do criterio 3, no mesmo teste."""
        achados = _regras(_etiqueta(nome="tenant_id"))
        self.assertEqual(_nomes(achados), {"etiqueta_sem_dominio"})

    def test_o_tenant_id_com_dominio_fechado_de_valores_validos_passa(self) -> None:
        achados = _regras(_etiqueta(nome="tenant_id", dominio=["piloto_a", "piloto_b"]))
        self.assertEqual(achados, [])

    def test_um_uuid_no_dominio_nao_passa_mesmo_com_o_nome_permitido(self) -> None:
        """E a regra que fecha o buraco: o nome passa, o valor e que nao."""
        achados = _regras(_etiqueta(nome="tenant_id", dominio=[UUID]))
        self.assertEqual(_nomes(achados), {"valor_fora_da_gramatica"})

    def test_um_nome_fora_da_gramatica_nao_chega_a_regra_do_dominio(self) -> None:
        achados = _regras(_etiqueta(nome="Tenant-Id", dominio=["a"]))
        self.assertEqual(_nomes(achados), {"etiqueta_fora_da_gramatica"})

    def test_uma_etiqueta_sem_nome_e_defeito_de_gramatica(self) -> None:
        self.assertEqual(_nomes(_regras(_etiqueta())), {"etiqueta_fora_da_gramatica"})

    def test_um_dominio_acima_do_tecto_da_dominio_grande(self) -> None:
        grande = [f"v{n}" for n in range(lint.MAXIMO_DE_VALORES + 1)]
        self.assertEqual(_nomes(_regras(_etiqueta(nome="eixo", dominio=grande))), {"dominio_grande"})

    def test_um_dominio_exactamente_no_tecto_passa(self) -> None:
        """O tecto e inclusivo. Um limite por um e a classe de defeito tipica aqui."""
        no_tecto = [f"v{n}" for n in range(lint.MAXIMO_DE_VALORES)]
        self.assertEqual(_regras(_etiqueta(nome="eixo", dominio=no_tecto)), [])

    def test_um_tecto_explicito_substitui_a_lista(self) -> None:
        self.assertEqual(_regras(_etiqueta(nome="eixo", cardinalidade_maxima=16)), [])

    def test_um_tecto_acima_do_maximo_da_dominio_grande(self) -> None:
        achados = _regras(_etiqueta(nome="eixo", cardinalidade_maxima=lint.MAXIMO_DE_VALORES + 1))
        self.assertEqual(_nomes(achados), {"dominio_grande"})

    def test_um_tecto_invalido_conta_como_sem_dominio(self) -> None:
        for mau in (0, -3, "muitos"):
            with self.subTest(mau=mau):
                achados = _regras(_etiqueta(nome="eixo", cardinalidade_maxima=mau))
                self.assertEqual(_nomes(achados), {"etiqueta_sem_dominio"})

    def test_um_dominio_vazio_nao_e_um_dominio(self) -> None:
        self.assertEqual(_nomes(_regras(_etiqueta(nome="eixo", dominio=[]))), {"etiqueta_sem_dominio"})

    def test_nenhum_achado_repete_o_valor_da_etiqueta(self) -> None:
        """Um achado que imprime o identificador copia-o para o registo do CI.

        E a disciplina do `Achado` do X-11, e vale aqui pela mesma razao.
        """
        achados = _regras(_etiqueta(nome="tenant_id", dominio=[UUID]))
        self.assertTrue(achados)
        for achado in achados:
            self.assertNotIn(UUID, str(achado))


class TestExpressoes(unittest.TestCase):
    """A leitura de uma expressao PromQL, com o limite que ela tem."""

    def test_as_palavras_do_promql_nao_contam_como_metricas(self) -> None:
        citadas = lint._metricas_citadas("increase(gwy_requests_total[10m]) == 0")
        self.assertEqual(citadas, {"gwy_requests_total"})

    def test_o_sufixo_de_duracao_nao_vira_metrica(self) -> None:
        """`[10m]` nao pode dar `m`: nao ha fronteira de palavra entre `0` e `m`."""
        self.assertNotIn("m", lint._metricas_citadas("rate(x_total[10m])"))
        self.assertNotIn("h", lint._metricas_citadas("rate(x_total[1h])"))

    def test_um_valor_de_etiqueta_nao_vira_metrica(self) -> None:
        citadas = lint._metricas_citadas('agr_llm_erros_total{resultado="budget_exhausted"} > 0')
        self.assertEqual(citadas, {"agr_llm_erros_total"})

    def test_a_funcao_hour_e_os_operadores_nao_contam(self) -> None:
        citadas = lint._metricas_citadas(
            "increase(gwy_requests_total[10m]) == 0 and on() ((hour() >= 6) and (hour() < 22))"
        )
        self.assertEqual(citadas, {"gwy_requests_total"})

    def test_as_etiquetas_de_um_selector_leem_se(self) -> None:
        self.assertEqual(
            lint._etiquetas_citadas('x_total{a="1",b!~"2"} > 0'), {"a", "b"}
        )

    def test_uma_etiqueta_proibida_num_selector_morde(self) -> None:
        """E a porta por onde um `contact_id` entrava sem passar pelo catalogo."""
        achados = lint._verificar_regra(
            {
                "alert": "x",
                "expr": 'm_base_total{contact_id="abc"} > 0',
                "labels": {"severity": "P1"},
                "annotations": {"runbook_url": lint.PREFIXO_DO_RUNBOOK + "RB-K01-x.md"},
            },
            "regras/r.yml",
            {"m_base_total"},
            RAIZ,
        )
        self.assertIn("etiqueta_proibida", _nomes(achados))


class TestRegras(unittest.TestCase):
    """Severidade, runbook e metrica citada."""

    def _regra(self, **sobrepor) -> dict:
        regra = {
            "alert": "exemplo",
            "expr": "m_base_total > 0",
            "labels": {"severity": "P1"},
            "annotations": {
                "runbook_url": lint.PREFIXO_DO_RUNBOOK + "RB-K01-meta-em-baixo.md"
            },
        }
        regra.update(sobrepor)
        return regra

    def _correr(self, regra: dict, conhecidas=("m_base_total",)) -> set[str]:
        return _nomes(lint._verificar_regra(regra, "regras/r.yml", set(conhecidas), RAIZ))

    def test_a_regra_de_exemplo_passa_contra_um_runbook_real(self) -> None:
        self.assertEqual(self._correr(self._regra()), set())

    def test_sem_runbook_url_morde(self) -> None:
        self.assertEqual(self._correr(self._regra(annotations={})), {"alerta_sem_runbook"})

    def test_um_runbook_que_nao_existe_no_disco_morde(self) -> None:
        regra = self._regra(
            annotations={"runbook_url": lint.PREFIXO_DO_RUNBOOK + "RB-K99-nao-existe.md"}
        )
        self.assertEqual(self._correr(regra), {"runbook_inexistente"})

    def test_um_runbook_com_outro_prefixo_morde(self) -> None:
        """Um caminho relativo nao serve: o `runbook_url` e clicavel do Alertmanager."""
        regra = self._regra(annotations={"runbook_url": "../runbooks/RB-K01-meta-em-baixo.md"})
        self.assertEqual(self._correr(regra), {"runbook_inexistente"})

    def test_cada_severidade_do_doc_09_passa(self) -> None:
        for severidade in lint.SEVERIDADES:
            with self.subTest(severidade=severidade):
                regra = self._regra(labels={"severity": severidade})
                self.assertEqual(self._correr(regra), set())

    def test_uma_severidade_fora_das_tres_morde(self) -> None:
        for mau in ("P9", "critical", "", "p1"):
            with self.subTest(mau=mau):
                regra = self._regra(labels={"severity": mau})
                self.assertEqual(self._correr(regra), {"severidade_invalida"})

    def test_sem_labels_a_severidade_morde(self) -> None:
        self.assertEqual(self._correr(self._regra(labels={})), {"severidade_invalida"})

    def test_uma_metrica_fora_do_catalogo_morde(self) -> None:
        regra = self._regra(expr="m_que_ninguem_expoe_total > 0")
        self.assertEqual(self._correr(regra), {"metrica_fora_do_catalogo"})

    def test_uma_regra_de_gravacao_nao_precisa_de_runbook(self) -> None:
        """`record:` nao e um alerta; exigir-lhe runbook era exigir o impossivel."""
        regra = {"record": "x:soma", "expr": "sum(m_base_total)"}
        self.assertEqual(self._correr(regra), set())

    def test_uma_regra_de_gravacao_continua_sujeita_ao_catalogo(self) -> None:
        regra = {"record": "x:soma", "expr": "sum(m_desconhecida_total)"}
        self.assertEqual(self._correr(regra), {"metrica_fora_do_catalogo"})


class _ComCopia(unittest.TestCase):
    """Copia uma fixture para um temporario, para a poder estragar."""

    def copiar(self, origem: Path) -> Path:
        destino = Path(tempfile.mkdtemp(prefix="obs-lint-")) / origem.name
        shutil.copytree(origem, destino)
        self.addCleanup(shutil.rmtree, destino.parent, ignore_errors=True)
        return destino


class TestCanario(_ComCopia):
    """O canario, e o que o faz ficar vermelho."""

    def test_o_canario_esta_verde(self) -> None:
        falhas, numeros = canario_mod.canario(FIXTURES)
        self.assertEqual(falhas, [])
        # **Pelo menos** uma por regra obrigatoria, e nao exactamente uma: duas
        # regras tem negativa tambem na superficie dos paineis, porque a mesma
        # regra tem de morder nas tres superficies e nao so na que foi escrita
        # primeiro.
        self.assertGreaterEqual(numeros["negativas"], len(lint.REGRAS_OBRIGATORIAS))
        self.assertGreaterEqual(numeros["positivas"], canario_mod.MINIMO_DE_POSITIVAS)

    def test_uma_pasta_sem_as_duas_metades_e_erro_de_configuracao(self) -> None:
        vazia = Path(tempfile.mkdtemp(prefix="obs-lint-vazia-"))
        self.addCleanup(shutil.rmtree, vazia, ignore_errors=True)
        with self.assertRaises(lint.ConfiguracaoInvalida):
            canario_mod.canario(vazia)

    def test_sem_a_negativa_de_uma_regra_o_canario_fica_vermelho(self) -> None:
        for regra in lint.REGRAS_OBRIGATORIAS:
            with self.subTest(regra=regra):
                copia = self.copiar(FIXTURES)
                for pasta in (copia / "negativas").iterdir():
                    if pasta.name.split("__", 1)[0] == regra:
                        shutil.rmtree(pasta)
                falhas, _ = canario_mod.canario(copia)
                self.assertTrue(
                    any(regra in f and "sem negativa" in f for f in falhas),
                    f"{regra}: {falhas}",
                )

    def test_uma_negativa_que_deixa_de_morder_fica_vermelha(self) -> None:
        copia = self.copiar(FIXTURES)
        alvo = copia / "negativas" / "severidade_invalida__p9"
        regras = alvo / "infra" / "compose" / "prometheus" / "regras" / "r.yml"
        regras.write_text(
            regras.read_text(encoding="utf-8").replace("severity: P9", "severity: P2"),
            encoding="utf-8",
        )
        falhas, _ = canario_mod.canario(copia)
        self.assertTrue(any("NAO mordeu" in f for f in falhas), falhas)

    def test_uma_positiva_que_morde_fica_vermelha(self) -> None:
        copia = self.copiar(FIXTURES)
        alvo = copia / "positivas" / "minimo"
        regras = alvo / "infra" / "compose" / "prometheus" / "regras" / "r.yml"
        regras.write_text(
            regras.read_text(encoding="utf-8").replace("severity: P1", "severity: P9"),
            encoding="utf-8",
        )
        falhas, _ = canario_mod.canario(copia)
        self.assertTrue(any("devia passar" in f for f in falhas), falhas)

    def test_uma_negativa_que_morde_duas_regras_fica_vermelha(self) -> None:
        """Uma fixture que nao isola o defeito nao diz qual regra o apanhou."""
        copia = self.copiar(FIXTURES)
        alvo = copia / "negativas" / "severidade_invalida__p9"
        regras = alvo / "infra" / "compose" / "prometheus" / "regras" / "r.yml"
        regras.write_text(
            regras.read_text(encoding="utf-8").replace(
                "m_base_total > 0", "m_outra_total > 0"
            ),
            encoding="utf-8",
        )
        falhas, _ = canario_mod.canario(copia)
        self.assertTrue(any("esperava so" in f for f in falhas), falhas)


class TestRepositorio(_ComCopia):
    """A arvore real, e a exigencia de ter lido alguma coisa."""

    def test_a_arvore_real_passa(self) -> None:
        achados, numeros = lint.verificar(RAIZ)
        self.assertEqual([str(a) for a in achados], [])
        self.assertGreater(numeros["metricas"], 0)
        self.assertGreater(numeros["regras"], 0)
        self.assertGreater(numeros["alertas"], 0)

    def test_as_doze_series_do_criterio_2_estao_no_catalogo(self) -> None:
        """O criterio 2 nomeia doze series. Uma que desapareca daqui falha."""
        import kamba_yaml

        dados = kamba_yaml.load_file(RAIZ / lint.CATALOGO)
        self.assertEqual(len(dados["series_do_criterio_2"]), 12)
        for serie in dados["series_do_criterio_2"]:
            self.assertIn(
                serie["estado"], ("exposta", "declarada_nao_exposta", "inexistente"), serie
            )
            self.assertTrue(str(serie.get("nota", "")).strip(), serie)

    def test_cada_regra_por_escrever_nomeia_o_que_falta_e_o_credor(self) -> None:
        import kamba_yaml

        dados = kamba_yaml.load_file(RAIZ / lint.CATALOGO)
        self.assertTrue(dados["regras_por_escrever"])
        for regra in dados["regras_por_escrever"]:
            self.assertTrue(str(regra.get("falta", "")).strip(), regra)
            self.assertTrue(str(regra.get("credor", "")).strip(), regra)

    def test_cada_runbook_citado_por_uma_regra_existe(self) -> None:
        """A bijeccao de que o KAM-083 precisa, na metade que ja se pode medir."""
        import kamba_yaml

        pasta = RAIZ / lint.REGRAS
        citados = set()
        for ficheiro in pasta.glob("*.yml"):
            dados = kamba_yaml.load_file(ficheiro)
            for grupo in dados["groups"]:
                for regra in grupo.get("rules") or []:
                    url = (regra.get("annotations") or {}).get("runbook_url")
                    if url:
                        citados.add(url[len(lint.PREFIXO_DO_RUNBOOK) :])
        self.assertTrue(citados)
        for nome in citados:
            self.assertTrue((RAIZ / lint.RUNBOOKS / nome).is_file(), nome)

    def test_os_dez_stubs_rb_k_existem(self) -> None:
        for n in range(1, 11):
            achados = list((RAIZ / lint.RUNBOOKS).glob(f"RB-K{n:02d}-*.md"))
            self.assertEqual(len(achados), 1, f"RB-K{n:02d}")

    def test_sem_catalogo_nao_passa_em_silencio(self) -> None:
        copia = self.copiar(FIXTURES / "positivas" / "minimo")
        (copia / "ops" / "metricas" / "catalogo.yaml").unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(copia)

    def test_sem_ficheiros_de_regras_nao_passa_em_silencio(self) -> None:
        copia = self.copiar(FIXTURES / "positivas" / "minimo")
        for p in (copia / "infra" / "compose" / "prometheus" / "regras").iterdir():
            p.unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(copia)

    def test_um_catalogo_sem_metricas_nao_passa_em_silencio(self) -> None:
        copia = self.copiar(FIXTURES / "positivas" / "minimo")
        (copia / "ops" / "metricas" / "catalogo.yaml").write_text(
            "version: 1\nmetricas: []\n", encoding="utf-8"
        )
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(copia)

    def test_um_ficheiro_de_regras_sem_groups_nao_passa_em_silencio(self) -> None:
        copia = self.copiar(FIXTURES / "positivas" / "minimo")
        alvo = copia / "infra" / "compose" / "prometheus" / "regras" / "r.yml"
        alvo.write_text("version: 1\n", encoding="utf-8")
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(copia)

    def test_sem_paineis_nao_passa_em_silencio(self) -> None:
        copia = self.copiar(FIXTURES / "positivas" / "minimo")
        for p in (copia / "ops" / "paineis").iterdir():
            p.unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(copia)

    def test_um_painel_ilegivel_nao_passa_em_silencio(self) -> None:
        copia = self.copiar(FIXTURES / "positivas" / "minimo")
        (copia / "ops" / "paineis" / "p.json").write_text("{ nao e json", encoding="utf-8")
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(copia)

    def test_uma_consulta_dentro_de_uma_row_tambem_se_le(self) -> None:
        """Um painel aninhado e onde se esconderia a consulta que nao se quer vista."""
        expressoes = lint._expressoes_do_painel(
            [
                {
                    "type": "row",
                    "panels": [
                        {"targets": [{"expr": 'm_base_total{contact_id="x"}'}]}
                    ],
                }
            ]
        )
        self.assertEqual(expressoes, ['m_base_total{contact_id="x"}'])

    def test_os_quatro_paineis_do_criterio_6_existem(self) -> None:
        nomes = {p.stem for p in (RAIZ / lint.PAINEIS).glob("*.json")}
        self.assertEqual(
            nomes, {"caminho-de-venda", "meta", "pagamentos", "infraestrutura"}
        )


class TestCli(unittest.TestCase):
    """Os codigos de saida, que sao o que o `make` le."""

    def test_o_lint_na_arvore_real_sai_com_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "lint"]), 0)

    def test_o_canario_na_arvore_real_sai_com_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "canario"]), 0)

    def test_uma_arvore_sem_superficies_sai_com_dois_e_nao_com_um(self) -> None:
        """2 e «nao se conseguiu verificar», e nunca se le como verde."""
        vazia = Path(tempfile.mkdtemp(prefix="obs-lint-cli-"))
        self.addCleanup(shutil.rmtree, vazia, ignore_errors=True)
        self.assertEqual(cli.main(["--root", str(vazia), "lint"]), 2)
        self.assertEqual(cli.main(["--root", str(vazia), "canario"]), 2)

    def test_uma_arvore_com_achados_sai_com_um(self) -> None:
        fixture = FIXTURES / "negativas" / "severidade_invalida__p9"
        self.assertEqual(cli.main(["--root", str(fixture), "lint"]), 1)


if __name__ == "__main__":
    unittest.main()
