"""O executor sobre um pesquisador falso: as asercoes, o relatorio e a afinacao."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval_search import dataset, embeddings_falsos, runner


def _registo(qid, catalogo="c", graus=None, *, nr=False, tags=(), divisao=dataset.DEV):
    return dataset.Registo(
        qid=qid, tenant="t", catalogo=catalogo, origem="texto", texto=qid,
        tags=frozenset(tags), restricoes={}, graus=graus or {}, nao_resolvivel=nr, divisao=divisao,
    )


def _linha(ref, preco=100):
    return {"product_ref": ref, "sku": ref, "preco_minor": preco}


CATALOGOS = {"c": {"a": 100, "b": 200}}


class TestAsercoes(unittest.TestCase):
    def correr(self, linhas, *, tags=()):
        registo = _registo("q1", graus={"a": 3}, tags=tags)
        return runner.correr(
            [registo], lambda _r: runner.Resposta(tuple(linhas), "lexical"), CATALOGOS, modo="lexical"
        )

    def test_produto_de_fora_do_catalogo_conta(self) -> None:
        execucao = self.correr([(_linha("z"), 0.1)])
        self.assertEqual(execucao.citado_inexistente, ["q1:z"])

    def test_preco_diferente_do_semeado_conta(self) -> None:
        execucao = self.correr([(_linha("a", preco=99), 0.1)])
        self.assertEqual(execucao.preco_divergente, ["q1:a"])

    def test_preco_certo_nao_conta(self) -> None:
        execucao = self.correr([(_linha("a"), 0.1), (_linha("b", 200), 0.05)])
        self.assertEqual((execucao.citado_inexistente, execucao.preco_divergente), ([], []))

    def test_as_adversariais_contam_a_parte(self) -> None:
        dados = runner.relatorio(
            {"lexical": self.correr([(_linha("z"), 0.1)], tags=("adversarial",))}, contexto={}
        )
        adversarial = dados["modos"]["lexical"]["asercoes"]["adversarial"]
        self.assertEqual(adversarial, {"consultas": 1, "produto_citado_inexistente": 1, "preco_divergente": 0})

    def test_le_ate_a_profundidade_e_nao_mais(self) -> None:
        linhas = [(_linha("a"), 0.1)] * runner.PROFUNDIDADE + [(_linha("z"), 0.0)]
        self.assertEqual(self.correr(linhas).citado_inexistente, [])

    def test_o_produto_de_outro_tenant_e_inexistente_neste(self) -> None:
        """A fuga entre tenants: o `x` existe, mas no catalogo de outro tenant."""
        catalogos = {"c": {"a": 100}, "d": {"x": 100}}
        execucao = runner.correr(
            [_registo("q1", graus={"a": 3})],
            lambda _r: runner.Resposta(((_linha("x"), 0.1),), "lexical"), catalogos, modo="lexical",
        )
        self.assertEqual(execucao.citado_inexistente, ["q1:x"])

    def test_preco_em_falta_e_divergente(self) -> None:
        execucao = self.correr([(_linha("a", preco=None), 0.1)])
        self.assertEqual(execucao.preco_divergente, ["q1:a"])

    def test_a_profundidade_e_a_do_recall_at_10(self) -> None:
        """Um relevante no decimo lugar conta: com tres de profundidade, o recall caia."""
        self.assertEqual(runner.PROFUNDIDADE, 10)
        linhas = [(_linha("b", 200), 0.1)] * 9 + [(_linha("a"), 0.05)]
        execucao = self.correr(linhas)
        self.assertEqual(execucao.resultados[0].ordem[-1], "a")
        dados = runner.relatorio({"lexical": execucao}, contexto={})
        self.assertEqual(dados["modos"]["lexical"]["global"]["recall_at_10"], 1.0)


class TestModos(unittest.TestCase):
    def test_hibrido_que_caiu_em_lexical_conta(self) -> None:
        execucao = runner.correr(
            [_registo("q1", graus={"a": 3})],
            lambda _r: runner.Resposta((), "lexical"), CATALOGOS, modo="hibrido",
        )
        self.assertEqual(execucao.caiu_em_lexical, 1)

    def test_modo_desconhecido_recusa(self) -> None:
        with self.assertRaises(ValueError):
            runner.correr([], lambda _r: None, CATALOGOS, modo="semantico")


class TestRelatorio(unittest.TestCase):
    def setUp(self) -> None:
        self.registos = [
            _registo("q1", graus={"a": 3}, tags=("typo",)),
            _registo("q2", graus={"b": 3}, divisao=dataset.TESTE),
            _registo("q3", nr=True),
        ]
        respostas = {
            "q1": runner.Resposta(((_linha("a"), 0.02),), "lexical", ("aros",)),
            "q2": runner.Resposta((), "lexical", ("aros", "xyz")),
            "q3": runner.Resposta(((_linha("b", 200), 0.005),), "lexical"),
        }
        self.lexical = runner.correr(self.registos, lambda r: respostas[r.qid], CATALOGOS, modo="lexical")
        hib = {**respostas, "q2": runner.Resposta(((_linha("b", 200), 0.02),), "hibrido")}
        self.hibrido = runner.correr(self.registos, lambda r: hib[r.qid], CATALOGOS, modo="hibrido")
        self.dados = runner.relatorio({"lexical": self.lexical, "hibrido": self.hibrido}, contexto={"dataset": "x"})

    def test_global_por_divisao_e_por_catalogo(self) -> None:
        lexical = self.dados["modos"]["lexical"]
        self.assertEqual(lexical["global"]["success_at_3"], 0.5)
        self.assertEqual(lexical["por_divisao"]["dev"]["success_at_3"], 1.0)
        self.assertEqual(lexical["por_divisao"]["teste"]["success_at_3"], 0.0)
        self.assertEqual(lexical["por_catalogo"]["c"]["zero_result_rate"], 0.5)
        self.assertEqual(lexical["global"]["falso_positivo_nao_resolvivel"], 1.0)

    def test_compara_hibrido_e_lexical(self) -> None:
        self.assertEqual(self.dados["hibrido_menos_lexical"]["success_at_3"], 0.5)
        self.assertEqual(self.dados["hibrido_menos_lexical"]["zero_result_rate"], -0.5)

    def test_os_alvos_vem_com_o_desvio(self) -> None:
        alvo = self.dados["modos"]["lexical"]["alvos_do_piloto"]["success_at_3"]
        self.assertEqual(alvo, {"alvo": ">= 0.85", "medido": 0.5, "cumpre": False, "desvio": -0.35})

    def test_tokens_nao_resolvidos_contam_consultas_e_nao_texto(self) -> None:
        self.assertEqual(runner.tokens_nao_resolvidos(self.lexical), [
            {"token": "aros", "consultas": 2}, {"token": "xyz", "consultas": 1},
        ])
        self.assertEqual(self.dados["modos"]["lexical"]["tokens_nao_resolvidos"], [{"token": "aros", "consultas": 2}])

    def test_as_falhas_dizem_que_consultas_puxam_cada_metrica(self) -> None:
        falhas = self.dados["modos"]["lexical"]["falhas"]
        self.assertEqual(falhas["falso_positivo_nao_resolvivel"], [{"qid": "q3", "texto": "q3", "primeiro": "b"}])
        self.assertEqual(falhas["zero_resultado"], [{"qid": "q2", "texto": "q2", "primeiro": None}])
        self.assertEqual(falhas["sem_sucesso_at_3"], [])
        self.assertEqual([f["qid"] for f in falhas["recall_at_10_abaixo_de_1"]], ["q2"])
        self.assertEqual(self.dados["modos"]["hibrido"]["falhas"]["zero_resultado"], [])

    def test_a_afinacao_entra_no_markdown(self) -> None:
        dados = dict(self.dados)
        dados["afinacao"] = {
            "divisao": "dev", "consultas": 2, "limiar_pg_trgm_actual": 0.45, "limiar_do_rrf_actual": 0.3,
            "pg_trgm": [{"limiar_pg_trgm": 0.4, **self.dados["modos"]["lexical"]["global"]}],
            "rrf_lexical": [{"limiar": 0.3, "success_at_3": 1.0, "zero_result_rate": 0.0,
                             "falso_positivo_nao_resolvivel": 1.0}],
            "rrf_hibrido": [],
        }
        texto = runner.markdown(dados)
        self.assertIn("## Afinação (só `dev`, 2 consultas)", texto)
        self.assertIn("| 0.3 | 1.000 | 0.000 | 1.000 |", texto)

    def test_o_markdown_e_o_json_saem_lado_a_lado(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "r.json"
            runner.escrever(self.dados, destino)
            self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["dataset"], "x")
            texto = destino.with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("## Modo lexical", texto)
        self.assertIn("| success_at_3 | 0.500 | 1.000 | 0.000 | >= 0.85 | não |", texto)
        self.assertIn("## Híbrido menos lexical", texto)


class TestVarrerLimiar(unittest.TestCase):
    def test_o_corte_esvazia_o_falso_positivo_e_o_acerto(self) -> None:
        registos = [_registo("q1", graus={"a": 3}), _registo("q2", nr=True)]
        respostas = {
            "q1": runner.Resposta(((_linha("a"), 0.8),), "lexical"),
            "q2": runner.Resposta(((_linha("b", 200), 0.2),), "lexical"),
        }
        execucao = runner.correr(registos, lambda r: respostas[r.qid], CATALOGOS, modo="lexical")
        varrido = runner.varrer_limiar(execucao, (0.0, 0.5, 0.9), lambda s: s)
        self.assertEqual(
            [(v["limiar"], v["success_at_3"], v["falso_positivo_nao_resolvivel"]) for v in varrido],
            [(0.0, 1.0, 1.0), (0.5, 1.0, 0.0), (0.9, 0.0, 0.0)],
        )

    def test_so_le_as_tres_linhas_da_resposta(self) -> None:
        linhas = tuple((_linha("b", 200), 0.9) for _ in range(3)) + ((_linha("a"), 0.9),)
        execucao = runner.correr(
            [_registo("q1", graus={"a": 3})], lambda _r: runner.Resposta(linhas, "lexical"), CATALOGOS,
            modo="lexical",
        )
        self.assertEqual(runner.varrer_limiar(execucao, (0.0,), lambda s: s)[0]["success_at_3"], 0.0)


class TestAfinar(unittest.TestCase):
    """Criterio 3, pela funcao que o executor chama: so `dev` chega a pesquisa."""

    def afinar(self, ler):
        vistos: list[str] = []

        def pesquisador(registo):
            vistos.append(registo.divisao)
            return runner.Resposta(((_linha("a"), 0.02),), "lexical")

        catalogos = {r.catalogo: {"a": 100} for r in dataset.ler()}
        dados = runner.afinar(
            catalogos=catalogos,
            pesquisador_por_limiar=lambda _l: pesquisador,
            pesquisador_lexical=pesquisador,
            pesquisador_hibrido=lambda r: runner.Resposta(((_linha("a"), 0.02),), "hibrido"),
            limiares_de_palavra=(0.4, 0.45),
            limiares_do_rrf=(0.0, 0.5),
            pontuador_lexical=lambda s: s * 10,
            pontuador_hibrido=lambda s: s * 10,
            actuais={"pg_trgm": 0.45, "rrf": 0.3},
            ler=ler,
        )
        return dados, vistos

    def test_le_so_dev_e_pesquisa_so_dev(self) -> None:
        dados, vistos = self.afinar(dataset.ler)
        self.assertEqual(set(vistos), {dataset.DEV})
        self.assertEqual(dados["consultas"], len(dataset.ler(dataset.DEV)))
        self.assertEqual([l["limiar_pg_trgm"] for l in dados["pg_trgm"]], [0.4, 0.45])
        self.assertEqual([l["limiar"] for l in dados["rrf_lexical"]], [0.0, 0.5])

    def test_um_ler_que_devolve_o_teste_levanta_antes_de_pesquisar(self) -> None:
        teste = dataset.ler(dataset.TESTE)
        with self.assertRaises(dataset.LeituraDoTesteProibida):
            self.afinar(lambda _d: teste)

    def test_um_ler_que_pede_o_teste_levanta_dentro_da_guarda(self) -> None:
        with self.assertRaises(dataset.LeituraDoTesteProibida):
            self.afinar(lambda _d: dataset.ler(dataset.TESTE))

    def test_um_registo_marcado_dev_mas_do_teste_pelo_hash_levanta(self) -> None:
        intruso = next(iter(dataset.ler(dataset.TESTE)))
        forjado = dataset.Registo(**{**intruso.__dict__, "divisao": dataset.DEV})
        with self.assertRaises(dataset.LeituraDoTesteProibida):
            self.afinar(lambda _d: [forjado])


class TestEmbeddingsFalsos(unittest.TestCase):
    def test_deterministico_normalizado_e_da_dimensao(self) -> None:
        a = embeddings_falsos.vector("arroz agulha")
        self.assertEqual(a, embeddings_falsos.vector("arroz agulha"))
        self.assertEqual(len(a), embeddings_falsos.DIMENSAO)
        self.assertAlmostEqual(sum(x * x for x in a), 1.0)

    def test_textos_parecidos_ficam_mais_perto(self) -> None:
        def cosseno(x, y):
            return sum(p * q for p, q in zip(x, y))

        base = embeddings_falsos.vector("frigorifico duas portas")
        self.assertGreater(
            cosseno(base, embeddings_falsos.vector("frigorifco duas portas")),
            cosseno(base, embeddings_falsos.vector("sabonete de coco")),
        )

    def test_texto_vazio_nao_tem_vector(self) -> None:
        with self.assertRaises(ValueError):
            embeddings_falsos.vector("   ")


if __name__ == "__main__":
    unittest.main()
