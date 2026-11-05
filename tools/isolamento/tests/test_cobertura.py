"""A cobertura recusa uma superficie sem caso — e recusa um caso morto.

Criterio 2 do KAM-066. Quatro perguntas, e um teste por pergunta: a cobertura
nao e «todos os itens tem caso», e sim as quatro juntas. Uma delas em falta
deixa a contagem de 100% a dizer outra coisa:

* um item sem caso nem dispensa → falha (o criterio);
* um caso que aponta para um item que nao existe → falha (caso morto);
* uma dispensa para um item que nao existe → falha (dispensa morta);
* uma dispensa para um item que **ja tem** caso → falha (dispensa morta).

E os trincos do ficheiro de dispensas, que sao o que impede a valvula de virar
porta: credor com a forma de ticket, credor que **existe no backlog**, e razao
com corpo.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from isolamento import casos as registo
from isolamento import enumeracao
from isolamento.tests import apoio


def _item(identificador: str, tipo: str = "rota") -> enumeracao.Item:
    return enumeracao.Item(
        id=identificador, tipo=tipo, camada="ensaio", onde="ensaio.ts:1"
    )


def _caso(identificador: str, enumeravel: tuple[str, ...]) -> registo.Caso:
    return registo.Caso(
        id=identificador,
        bateria="X-01",
        camada="rotas",
        enumeravel=enumeravel,
        fn=lambda _ctx: [],
    )


class TestAsQuatroPerguntas(unittest.TestCase):
    def test_um_item_sem_caso_falha(self) -> None:
        problemas = registo.cobertura([_item("rota:a")], casos={}, dispensas={})
        self.assertEqual(len(problemas), 1)
        self.assertIn("sem caso registado", problemas[0])

    def test_um_item_com_caso_passa(self) -> None:
        self.assertEqual(
            registo.cobertura(
                [_item("rota:a")],
                casos={"c": _caso("c", ("rota:a",))},
                dispensas={},
            ),
            [],
        )

    def test_um_caso_morto_falha(self) -> None:
        problemas = registo.cobertura(
            [_item("rota:a")],
            casos={"c": _caso("c", ("rota:a", "rota:que-desapareceu"))},
            dispensas={},
        )
        self.assertEqual(len(problemas), 1)
        self.assertIn("que a enumeracao nao encontra", problemas[0])

    def test_uma_dispensa_morta_falha(self) -> None:
        problemas = registo.cobertura(
            [_item("rota:a")],
            casos={"c": _caso("c", ("rota:a",))},
            dispensas={
                "rota:ja-nao-existe": registo.Dispensa(
                    item="rota:ja-nao-existe", credor="KAM-001", razao="x" * 60
                )
            },
        )
        self.assertEqual(len(problemas), 1)
        self.assertIn("a dispensa esta morta", problemas[0])

    def test_uma_dispensa_sobre_um_item_com_caso_falha(self) -> None:
        """A valvula nao fica aberta depois de o caso existir."""
        problemas = registo.cobertura(
            [_item("rota:a")],
            casos={"c": _caso("c", ("rota:a",))},
            dispensas={
                "rota:a": registo.Dispensa(
                    item="rota:a", credor="KAM-001", razao="x" * 60
                )
            },
        )
        self.assertEqual(len(problemas), 1)
        self.assertIn("A dispensa esta morta", problemas[0])

    def test_um_item_dispensado_passa(self) -> None:
        self.assertEqual(
            registo.cobertura(
                [_item("rota:a")],
                casos={},
                dispensas={
                    "rota:a": registo.Dispensa(
                        item="rota:a", credor="KAM-001", razao="x" * 60
                    )
                },
            ),
            [],
        )


class TestOsTrincosDasDispensas(unittest.TestCase):
    def setUp(self) -> None:
        self._directorio = tempfile.TemporaryDirectory()
        self.raiz = apoio.arvore(Path(self._directorio.name))
        self.ficheiro = self.raiz / "ci" / "isolamento-dispensas.yaml"

    def tearDown(self) -> None:
        self._directorio.cleanup()

    def escrever(self, credor: str, razao: str) -> None:
        self.ficheiro.write_text(
            "version: 1\ndispensas:\n"
            "  - item: rota:a\n"
            f"    credor: {credor}\n"
            f"    razao: {razao}\n",
            encoding="utf-8",
        )

    def test_a_lista_vazia_e_valida(self) -> None:
        self.assertEqual(registo.ler_dispensas(self.raiz), {})

    def test_um_credor_sem_forma_de_ticket_falha(self) -> None:
        self.escrever("o-engenheiro-de-plataforma", "x" * 60)
        with self.assertRaises(registo.RegistoInvalido) as apanhado:
            registo.ler_dispensas(self.raiz)
        self.assertIn("KAM-NNN", str(apanhado.exception))

    def test_um_credor_que_nao_existe_no_backlog_falha(self) -> None:
        """`KAM-999` tem a forma de um ticket e nao e um ticket."""
        self.escrever("KAM-999", "x" * 60)
        with self.assertRaises(registo.RegistoInvalido) as apanhado:
            registo.ler_dispensas(self.raiz)
        self.assertIn("nao existe no §4", str(apanhado.exception))

    def test_uma_razao_curta_falha(self) -> None:
        self.escrever("KAM-001", "porque sim")
        with self.assertRaises(registo.RegistoInvalido) as apanhado:
            registo.ler_dispensas(self.raiz)
        self.assertIn("razao tem", str(apanhado.exception))

    def test_um_credor_do_backlog_com_razao_passa(self) -> None:
        self.escrever("KAM-001", "x" * 60)
        self.assertEqual(
            registo.ler_dispensas(self.raiz)["rota:a"].credor, "KAM-001"
        )


class TestORegisto(unittest.TestCase):
    def test_um_id_repetido_e_erro(self) -> None:
        nome = "caso-de-ensaio-repetido"
        registo.registar_caso(
            id=nome, bateria="X-01", camada="rotas", fn=lambda _c: []
        )
        try:
            with self.assertRaises(registo.RegistoInvalido):
                registo.registar_caso(
                    id=nome, bateria="X-01", camada="rotas", fn=lambda _c: []
                )
        finally:
            registo.REGISTO.pop(nome, None)

    def test_a_bateria_reservada_nao_pode_ter_caso(self) -> None:
        """O X-07 e a lacuna de `08` §3.7, e reservar e nao reutilizar."""
        with self.assertRaises(registo.RegistoInvalido) as apanhado:
            registo.Caso(
                id="x07",
                bateria="X-07",
                camada="rotas",
                enumeravel=(),
                fn=lambda _c: [],
            )
        self.assertIn("reservada", str(apanhado.exception))

    def test_uma_bateria_desconhecida_e_erro(self) -> None:
        with self.assertRaises(registo.RegistoInvalido):
            registo.Caso(
                id="x99",
                bateria="X-99",
                camada="rotas",
                enumeravel=(),
                fn=lambda _c: [],
            )


class TestORepositorio(unittest.TestCase):
    """A regressao: a arvore real tem 100% de cobertura e zero dispensas."""

    RAIZ = Path(__file__).resolve().parents[3]

    def test_cem_por_cento_sem_dispensas(self) -> None:
        itens = enumeracao.enumerar(self.RAIZ)
        self.assertEqual(registo.cobertura(itens), [])
        self.assertEqual(
            registo.ler_dispensas(self.RAIZ),
            {},
            "ha dispensas declaradas: o ficheiro nasceu vazio e cada entrada "
            "nova e uma superficie que ninguem ataca",
        )

    def test_todas_as_baterias_com_superficie_tem_caso(self) -> None:
        casos = registo.carregar_casos()
        por_bateria = {caso.bateria for caso in casos.values()}
        for bateria in ("X-01", "X-02", "X-03", "X-04", "X-05", "C-01", "P-01"):
            with self.subTest(bateria=bateria):
                self.assertIn(bateria, por_bateria)

    def test_o_x07_continua_sem_casos(self) -> None:
        casos = registo.carregar_casos()
        self.assertEqual(
            [caso.id for caso in casos.values() if caso.bateria == "X-07"], []
        )


if __name__ == "__main__":
    unittest.main()
