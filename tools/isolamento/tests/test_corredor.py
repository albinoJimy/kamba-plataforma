"""O corredor nao salta em silencio, e um caso que levanta e um achado.

A regra e a de `db/correr_suite.py`: num *gate*, saltar e falhar. Um caso de
isolamento que nao corre e um caso que nao existe, e a diferenca entre as duas
coisas nao se ve no sumario de uma suite.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from isolamento import casos as registo
from isolamento import corredor
from isolamento.contexto import Contexto
from isolamento.oraculo import Oraculo

CANARIO = "canario_b_0123456789abcdef0123456789abcdef"


class ComRegisto(unittest.TestCase):
    """Troca o registo global por um proprio, e repoe-o no fim."""

    def setUp(self) -> None:
        self._antes = dict(registo.REGISTO)
        registo.REGISTO.clear()
        self._carregado = registo.carregar_casos

    def tearDown(self) -> None:
        registo.REGISTO.clear()
        registo.REGISTO.update(self._antes)
        registo.carregar_casos = self._carregado

    def registar(self, **argumentos) -> None:  # noqa: ANN003
        registo.registar_caso(**argumentos)
        registo.carregar_casos = lambda: dict(registo.REGISTO)


class TestNaoSaltaEmSilencio(ComRegisto):
    def test_um_caso_sem_dependencia_satisfeita_e_achado(self) -> None:
        self.registar(
            id="precisa-de-base",
            bateria="X-03",
            camada="rls",
            fn=lambda _c: [],
            precisa="postgres",
        )
        resultado = corredor.correr(Contexto(), precisa={"postgres"})
        self.assertEqual(len(resultado.achados), 1, resultado.achados)
        self.assertIn("saltar e falhar", resultado.achados[0])
        self.assertEqual(resultado.corridos, ())

    def test_com_permitir_salto_fica_na_lista_e_nao_e_achado(self) -> None:
        self.registar(
            id="precisa-de-base",
            bateria="X-03",
            camada="rls",
            fn=lambda _c: [],
            precisa="postgres",
        )
        resultado = corredor.correr(
            Contexto(), precisa={"postgres"}, permitir_salto=True
        )
        self.assertEqual(resultado.achados, [])
        self.assertEqual(resultado.saltados, ("precisa-de-base",))
        self.assertFalse(resultado.conforme)


class TestUmCasoQueSeEngana(ComRegisto):
    def test_um_caso_que_levanta_e_achado_e_nao_um_erro_de_suite(self) -> None:
        def rebenta(_ctx) -> list[str]:  # noqa: ANN001
            raise RuntimeError("a ligacao caiu")

        self.registar(id="rebenta", bateria="X-01", camada="rotas", fn=rebenta)
        resultado = corredor.correr(Contexto(), precisa={"nada"})
        self.assertEqual(len(resultado.achados), 1)
        self.assertIn("RuntimeError", resultado.achados[0])
        self.assertEqual(resultado.corridos, ("rebenta",))

    def test_um_fn_que_devolve_none_e_achado(self) -> None:
        """Um `fn` que devolve `None` faz o caso passar sempre."""
        self.registar(
            id="devolve-none",
            bateria="X-01",
            camada="rotas",
            fn=lambda _c: None,
        )
        resultado = corredor.correr(Contexto(), precisa={"nada"})
        self.assertEqual(len(resultado.achados), 1)
        self.assertIn("nao uma lista de achados", resultado.achados[0])

    def test_uma_origem_fora_das_cinco_e_achado(self) -> None:
        self.registar(
            id="origem-inventada",
            bateria="X-01",
            camada="rotas",
            fn=lambda _c: [],
            origens=("telepatia",),
        )
        resultado = corredor.correr(Contexto(), precisa={"nada"})
        self.assertTrue(
            any("criterio 9" in achado for achado in resultado.achados),
            resultado.achados,
        )


class TestOOraculoConfirmaSePrimeiro(ComRegisto):
    def test_um_oraculo_cego_falha_o_corredor_antes_de_qualquer_caso(self) -> None:
        corridos: list[str] = []

        class Cego(Oraculo):
            def varrer(self, origem, valor):  # noqa: ANN001, ANN201, ARG002
                return []

        self.registar(
            id="nunca-corre",
            bateria="X-01",
            camada="rotas",
            fn=lambda _c: corridos.append("corri") or [],
        )
        from isolamento.oraculo import OraculoCego  # noqa: PLC0415

        with self.assertRaises(OraculoCego):
            corredor.correr(
                Contexto(oraculo=Cego({"t": CANARIO})), precisa={"nada"}
            )
        self.assertEqual(corridos, [])


class TestORelatorio(ComRegisto):
    def test_leva_a_duracao_de_cada_caso(self) -> None:
        self.registar(id="rapido", bateria="X-01", camada="rotas", fn=lambda _c: [])
        resultado = corredor.correr(Contexto(), precisa={"nada"})
        self.assertIn("rapido", resultado.duracao)
        self.assertIn("rapido", corredor.relatorio(resultado))


class TestOContexto(unittest.TestCase):
    def test_tem_responde_por_dependencia(self) -> None:
        vazio = Contexto()
        self.assertTrue(vazio.tem("nada"))
        self.assertFalse(vazio.tem("postgres"))
        self.assertFalse(vazio.tem("node"))
        self.assertFalse(vazio.tem("agr"))
        self.assertFalse(vazio.tem("telepatia"))

    def test_postgres_pede_cursores_e_tenants(self) -> None:
        """Um `cursor_de` sem tenants semeados nao e uma base utilizavel."""
        self.assertFalse(Contexto(cursor_de=lambda *_: None).tem("postgres"))

    def test_a_raiz_por_omissao_e_a_do_repositorio(self) -> None:
        self.assertTrue((Contexto().raiz / "specs" / "INDICE.md").is_file())
        self.assertEqual(Contexto().raiz, Path(__file__).resolve().parents[3])


if __name__ == "__main__":
    unittest.main()
