"""O executor do `search_catalog` sem base de dados (KAM-061).

O executor contra o indice real, e o `retrieve` do grafo sobre ele, medem-se em
`db/tests_produtos/test_indice.py` (`TestLigacaoDoAgr`). Aqui fica o que e
contrato do executor: o pontuador normalizado, a recusa dos filtros, o tenant
do contexto e a traducao do tecto do servidor.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from kamba_core.idx import normalizacao as norm
from kamba_core.idx.pesquisa import Procura

from kamba_agr.tls import idx
from kamba_agr.tls.especificacoes import ErroDeBackend
from kamba_agr.tls.vendedor import ArgumentosDeSearchCatalog
from kamba_agr.verticais.vendedor import nos

TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"


def _pedido(query: str = "arroz", filtros=None, ligacao=object()):
    return SimpleNamespace(
        ctx=SimpleNamespace(tenant_id=TENANT),
        args=ArgumentosDeSearchCatalog(query=query, filtros=filtros or {}),
        timeout_ms=2_000,
        ligacao=ligacao,
    )


class TestPontuador(unittest.TestCase):
    def test_o_maximo_teorico_e_o_dos_ramos_activos(self) -> None:
        self.assertAlmostEqual(idx.maximo_teorico(hibrido=False), 0.5 / 61)
        self.assertAlmostEqual(idx.maximo_teorico(hibrido=True), 1.0 / 61)

    def test_os_postos_que_importam(self) -> None:
        """Primeiro nos dois ramos lexicais 1,0; so no `fts` 0,4; so no `tri` 0,6."""
        casos = {
            (0.3 + 0.2) / 61: 1.0,
            0.2 / 61: 0.4,
            0.3 / 61: 0.6,
        }
        for bruto, esperado in casos.items():
            with self.subTest(bruto=bruto):
                self.assertAlmostEqual(idx.score_normalizado(bruto, hibrido=False), esperado)

    def test_fica_em_zero_um(self) -> None:
        self.assertEqual(idx.score_normalizado(1.0, hibrido=False), 1.0)
        self.assertEqual(idx.score_normalizado(-1.0, hibrido=False), 0.0)

    def test_o_limiar_do_rrf_deixa_passar_o_primeiro_do_fts(self) -> None:
        """O defeito da escala: o primeiro so do `fts` passa este e nao o do duplo."""
        so_fts = idx.score_normalizado(0.2 / 61, hibrido=False)
        self.assertGreaterEqual(so_fts, idx.LIMIAR_DO_RRF)
        self.assertLess(so_fts, nos.LIMIAR_IDX)
        # E o RRF cru, sem normalizar, nunca passava nenhum dos dois.
        self.assertLess((0.3 + 0.2) / 61, idx.LIMIAR_DO_RRF)


def _procura(linhas=(), texto: str = "arroz", lexico: norm.Lexico | None = None, vocabulario=None):
    """O que o `pesquisa.procurar` devolve, com a normalizacao feita a serio."""
    lex = lexico or norm.Lexico(TENANT)
    normalizacao = norm.normalizar(texto, TENANT, "texto", lexico=lex, vocabulario=vocabulario)
    return Procura(normalizacao, tuple(linhas))


class TestExecutor(unittest.TestCase):
    def setUp(self) -> None:
        # O executor escreve no registo global do IDX desde o KAM-193; estes
        # ensaios nao o leem, mas nao o deixam sujo para quem vier a seguir.
        from kamba_core.idx import metricas

        self.addCleanup(metricas.METRICAS.repor)

    def test_o_tenant_e_o_do_contexto_e_a_linha_leva_o_score(self) -> None:
        linha = {"sku": "a", "product_ref": "a", "nome": "A", "preco_tipo": "fixo"}
        with mock.patch.object(
            idx.pesquisa, "procurar", return_value=_procura(((linha, 0.2 / 61),))
        ) as candidatos:
            resposta = idx.executar(_pedido("arroz"))
        argumentos, opcoes = candidatos.call_args
        self.assertEqual(argumentos[1:], (TENANT, "arroz"))
        # Sem `LigacaoVectorial`, o vector nao e pedido: modo lexical (KAM-063).
        self.assertEqual(
            opcoes, {"max_preco_minor": None, "tecto_ms": 2_000, "vectorial": None}
        )
        self.assertEqual(resposta.data, {"candidatos": ({**linha, "score": 0.4},)})
        self.assertEqual(resposta.facts, ())

    def test_o_teto_de_preco_e_o_unico_filtro(self) -> None:
        with mock.patch.object(idx.pesquisa, "procurar", return_value=_procura()) as candidatos:
            idx.executar(_pedido(filtros={"max_preco_minor": "2500000"}))
        self.assertEqual(candidatos.call_args[1]["max_preco_minor"], 2_500_000)
        for filtros in (
            {"cor": "azul"},
            {"max_preco_minor": "12,5"},
            {"max_preco_minor": "-1"},
            {"max_preco_minor": "²"},
            {"max_preco_minor": "9" * 19},
        ):
            with self.subTest(filtros=filtros):
                with self.assertRaises(ErroDeBackend) as erro:
                    idx.executar(_pedido(filtros=filtros))
                self.assertEqual(erro.exception.codigo, "VALIDATION_ERROR")

    def test_sem_ligacao_e_defeito_de_registo(self) -> None:
        with self.assertRaises(RuntimeError):
            idx.executar(_pedido(ligacao=None))

    def test_o_tecto_do_servidor_volta_como_timeout(self) -> None:
        cancelada = Exception({"C": "57014", "M": "canceling statement"})
        with mock.patch.object(idx.pesquisa, "procurar", side_effect=cancelada):
            with self.assertRaises(TimeoutError):
                idx.executar(_pedido())
        outra = Exception({"C": "42501"})
        with mock.patch.object(idx.pesquisa, "procurar", side_effect=outra):
            with self.assertRaises(Exception) as erro:
                idx.executar(_pedido())
        self.assertIs(erro.exception, outra)

    def test_o_executor_e_o_do_search_catalog(self) -> None:
        self.assertEqual(idx.executores_do_idx(), {"search_catalog": idx.executar})


class TestPergunta(unittest.TestCase):
    """KAM-062: a normalizacao diz ao AGR o que perguntar, e so o codigo."""

    LEXICO = norm.Lexico.de_linhas(
        ({"tenant_id": None, "tipo": "sinonimo", "termo": "telefone",
          "canonico": "telemovel|telefone fixo"},),
        TENANT,
    )
    VOCABULARIO = norm.Vocabulario.de_frequencias({"telemovel": 2, "samsung": 1})

    def setUp(self) -> None:
        from kamba_core.idx import metricas

        self.addCleanup(metricas.METRICAS.repor)

    def executar(self, texto: str):
        procura = _procura(texto=texto, lexico=self.LEXICO, vocabulario=self.VOCABULARIO)
        with mock.patch.object(idx.pesquisa, "procurar", return_value=procura):
            return idx.executar(_pedido(texto))

    def test_as_tres_perguntas(self) -> None:
        casos = {
            "telefone": "TERMO_AMBIGUO",
            "samsung ate 300 dolares": "MOEDA_ESTRANGEIRA",
            "xyzq": "TERMO_DESCONHECIDO",
        }
        for texto, codigo in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(self.executar(texto).data["pergunta"], codigo)

    def test_a_ambiguidade_passa_a_frente_e_e_uma_so(self) -> None:
        self.assertEqual(self.executar("telefone xyzq ate 3 dolares").data["pergunta"], "TERMO_AMBIGUO")

    def test_sem_nada_a_perguntar_nao_ha_campo(self) -> None:
        self.assertNotIn("pergunta", self.executar("samsung").data)

    def test_a_palavra_desconhecida_vai_com_os_candidatos_e_o_grafo_decide(self) -> None:
        """«quero comprar samsung»: o executor diz, e o `retrieve` decide pelo limiar."""
        linha = {"sku": "s", "product_ref": "s", "nome": "Samsung", "preco_tipo": "fixo"}
        procura = _procura(((linha, 0.2 / 61),), texto="quero comprar samsung",
                           lexico=self.LEXICO, vocabulario=self.VOCABULARIO)
        self.assertIn("comprar", procura.normalizacao.tokens_nao_resolvidos)
        with mock.patch.object(idx.pesquisa, "procurar", return_value=procura):
            dados = idx.executar(_pedido("quero comprar samsung")).data
        self.assertEqual(dados["pergunta"], "TERMO_DESCONHECIDO")
        self.assertEqual([c["sku"] for c in dados["candidatos"]], ["s"])

    def test_o_codigo_e_do_dominio_do_grafo_e_nunca_a_palavra(self) -> None:
        self.assertEqual(
            {"TERMO_AMBIGUO", "MOEDA_ESTRANGEIRA", "TERMO_DESCONHECIDO"},
            set(nos.PERGUNTAS_DO_IDX),
        )
        self.assertNotIn("xyzq", repr(self.executar("xyzq").data))


class TestMetricasDoExecutor(unittest.TestCase):
    """KAM-193: a ligacao do executor ao registo do IDX, e nao so o registo."""

    PERGUNTA = "quero comprar nike air force 923456789"

    def setUp(self) -> None:
        from kamba_core.idx import metricas

        self.registo = metricas.METRICAS
        self.registo.repor()
        self.addCleanup(self.registo.repor)

    def test_uma_pesquisa_que_respondeu_escreve_as_tres_series(self) -> None:
        linha = {"sku": "a", "product_ref": "a", "nome": "A", "preco_tipo": "fixo"}
        # O relogio e fixo para que a **duracao** fique presa, e nao so a
        # existencia da serie: com `>= 0`, um executor que escrevesse 0 ou
        # segundos em vez de milissegundos passava (achado 2 da revisao).
        with mock.patch.object(
            idx.pesquisa, "procurar",
            return_value=_procura(((linha, 0.2 / 61), (linha, 0.1 / 61))),
        ), mock.patch.object(idx.time, "perf_counter", side_effect=(10.0, 10.25)):
            idx.executar(_pedido(self.PERGUNTA))
        lido = self.registo.ler()
        self.assertEqual(lido["idx_mode:lexical"], 1)
        self.assertEqual(lido["idx_results_total"], 2)
        self.assertEqual(lido["idx_query_ms:todos:lexical"], 250.0)
        self.assertEqual(
            set(lido),
            {"idx_mode:lexical", "idx_results_total", "idx_query_ms:todos:lexical"},
            "o executor de hoje e lexical: nenhuma serie hibrida",
        )

    def test_a_pergunta_nao_chega_a_exposicao(self) -> None:
        with mock.patch.object(idx.pesquisa, "procurar", return_value=_procura()):
            idx.executar(_pedido(self.PERGUNTA))
        texto = self.registo.exposicao()
        self.assertIn("idx_results_total 0", texto)
        for pedaco in (*self.PERGUNTA.split(), TENANT):
            with self.subTest(pedaco=pedaco):
                self.assertNotIn(pedaco, texto)

    def test_uma_pesquisa_que_falhou_nao_escreve(self) -> None:
        """O tecto e qualquer outro erro: a duracao seria a do tecto, nao a da pesquisa."""
        for erro in (Exception({"C": "57014"}), Exception({"C": "42501"})):
            with self.subTest(erro=erro):
                with mock.patch.object(idx.pesquisa, "procurar", side_effect=erro):
                    with self.assertRaises(Exception):
                        idx.executar(_pedido())
        self.assertEqual(self.registo.ler(), {})

    def test_um_filtro_recusado_nao_escreve(self) -> None:
        with self.assertRaises(ErroDeBackend):
            idx.executar(_pedido(filtros={"cor": "azul"}))
        self.assertEqual(self.registo.ler(), {})


if __name__ == "__main__":
    unittest.main()
