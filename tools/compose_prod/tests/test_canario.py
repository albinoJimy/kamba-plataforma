"""O canario do `compose_prod` corre, morde, e nenhuma regra fica sem caso.

Este ficheiro e curto de proposito: o trabalho esta no proprio canario, que
aplica trinta e quatro mutacoes a arvore **real** e exige, de cada uma, o
achado da sua regra e **so** esse. Aqui prende-se que ele corre limpo, que nao
esta vazio, e que a sua propria rede de seguranca esta armada.

O caso que importa e o ultimo: um canario pode falhar por **nao medir nada** —
a arvore muda, a mutacao deixa de encontrar o texto que trocava, e o caso
passaria a verde. O canario trata isso como falha (`NaoSeAplica`), e o teste
`test_uma_mutacao_que_nao_se_aplica_e_falha` prova que trata.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from compose_prod import canario, cli, lint

RAIZ = Path(__file__).resolve().parents[3]


class TestCanario(unittest.TestCase):
    def test_todas_as_mutacoes_mordem(self) -> None:
        falhas, _ = canario.correr(RAIZ)
        self.assertEqual(falhas, [])

    def test_nao_esta_vazio(self) -> None:
        """Um canario sem casos passa sempre, e ja aconteceu no gate 3b."""
        _, numeros = canario.correr(RAIZ)
        self.assertGreaterEqual(numeros["casos"], 30)
        self.assertEqual(numeros["cobertos"], numeros["casos"])

    def test_exercita_todas_as_regras(self) -> None:
        _, numeros = canario.correr(RAIZ)
        self.assertEqual(numeros["regras_exercitadas"], numeros["regras"])
        self.assertEqual(numeros["regras"], len(lint.REGRAS))

    def test_toda_a_regra_tem_entrada_em_minimo_por_regra(self) -> None:
        """Uma regra nova sem canario tem de falhar, nao ficar em silencio."""
        self.assertEqual(
            sorted(r.__name__ for r in lint.REGRAS),
            sorted(canario.MINIMO_POR_REGRA),
        )

    def test_cada_caso_declara_as_regras_que_espera(self) -> None:
        for caso in canario.CASOS:
            self.assertTrue(caso.espera, caso.codigo)
            self.assertTrue(caso.descricao.strip(), caso.codigo)

    def test_os_codigos_dos_casos_nao_se_repetem(self) -> None:
        codigos = [c.codigo for c in canario.CASOS]
        self.assertEqual(len(codigos), len(set(codigos)))

    def test_os_achados_esperados_existem_em_minimo_por_regra(self) -> None:
        """Um caso que espere um achado que nenhuma regra produz nao mede nada."""
        conhecidos = set().union(*canario.MINIMO_POR_REGRA.values())
        for caso in canario.CASOS:
            for regra in caso.espera:
                self.assertIn(regra, conhecidos, f"{caso.codigo}: {regra}")

    def test_uma_mutacao_que_nao_se_aplica_e_falha(self) -> None:
        """A rede de seguranca do canario, armada.

        Sem isto, a arvore podia mudar por baixo das mutacoes e o canario
        ficava verde por nao medir nada — que e o defeito que o `money_lint`
        fecha ao recusar uma pasta de *fixtures* vazia.
        """
        with self.assertRaises(canario.NaoSeAplica):
            import tempfile

            with tempfile.TemporaryDirectory() as pasta:
                destino = Path(pasta)
                canario._copiar(RAIZ, destino)
                canario.Copia(destino).trocar(
                    lint.PROD, r"^  texto-que-nao-existe-em-lado-nenhum:$", "x"
                )

    def test_a_cli_do_canario_sai_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "canario"]), 0)


if __name__ == "__main__":
    unittest.main()
