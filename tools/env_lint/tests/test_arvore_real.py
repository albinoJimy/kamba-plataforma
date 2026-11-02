"""Testes contra a arvore real do repositorio.

O `test_lint.py` prova que as regras funcionam sobre um `Dados` construido a
mao; estes provam que funcionam sobre **esta** arvore — que e a que o gate 2
verifica. As duas perguntas sao diferentes, e foi por confundir as duas que o
`canon_lint` teve superficies vazias a passar.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from env_lint import canario, cli, lint

RAIZ = Path(__file__).resolve().parents[3]


class TestVarrerAArvore(unittest.TestCase):
    def test_a_arvore_esta_limpa(self) -> None:
        achados, _ = lint.varrer(RAIZ)
        self.assertEqual([str(a) for a in achados], [])

    def test_le_os_tres_ambientes_e_nao_zero(self) -> None:
        _, numeros = lint.varrer(RAIZ)
        # O numero importa: um verde sobre zero ambientes nao diz nada.
        self.assertEqual(numeros["ambientes"], len(lint.AMBIENTES))
        self.assertGreater(numeros["segredos"], 0)
        self.assertGreater(numeros["ficheiros"], 0)
        self.assertEqual(
            numeros["linhas"], len(lint.CHAVES_DA_MATRIZ) + len(lint.CHAVES_ACRESCENTADAS)
        )


class TestCanarioNaArvore(unittest.TestCase):
    def test_todos_os_casos_mordem(self) -> None:
        falhas, numeros = canario.correr(RAIZ)
        self.assertEqual(falhas, [])
        self.assertEqual(numeros["cobertos"], numeros["casos"])

    def test_cada_regra_tem_pelo_menos_um_caso(self) -> None:
        # Sem isto, acrescentar uma regra sem canario passava sem ninguem ver —
        # e e esse o buraco por onde um lint deixa de morder.
        self.assertGreaterEqual(numeros_de_casos := len(canario.CASOS), len(lint.REGRAS))
        self.assertGreater(numeros_de_casos, 0)

    def test_os_codigos_dos_casos_nao_se_repetem(self) -> None:
        codigos = [caso.codigo for caso in canario.CASOS]
        self.assertEqual(sorted(codigos), sorted(set(codigos)))


class TestCli(unittest.TestCase):
    def test_lint_devolve_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "lint"]), 0)

    def test_canario_devolve_zero(self) -> None:
        self.assertEqual(cli.main(["--root", str(RAIZ), "canario"]), 0)

    def test_raiz_ilegivel_devolve_dois_e_nao_um(self) -> None:
        # A distincao que faz a diferenca: 2 e «nao se conseguiu verificar»,
        # 1 e «verificou-se e ha achados». Confundi-los faz um gate que nao
        # correu parecer um gate verde.
        self.assertEqual(cli.main(["--root", str(RAIZ / "nao-existe"), "lint"]), 2)
        self.assertEqual(cli.main(["--root", str(RAIZ / "nao-existe"), "canario"]), 2)

    def test_subcomando_obrigatorio(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(["--root", str(RAIZ)])


class TestDominiosPartilhados(unittest.TestCase):
    def test_os_ambientes_sao_os_do_secrets_inventory(self) -> None:
        # O dominio vive em dois sitios porque os dois modulos correm sozinhos.
        # Este teste e o que impede os dois de divergirem: um quarto ambiente
        # entra nos dois ou em nenhum.
        from secrets_inventory.inventario import AMBIENTES as DO_KAM_010

        self.assertEqual(lint.AMBIENTES, DO_KAM_010)

    def test_os_segredos_nomeados_pelo_criterio_existem(self) -> None:
        inventario = lint._ler_inventario(RAIZ)
        for identificador in lint.SEGREDOS_QUE_TEM_DE_SER_DISTINTOS:
            self.assertIn(identificador, inventario)


if __name__ == "__main__":
    unittest.main()
