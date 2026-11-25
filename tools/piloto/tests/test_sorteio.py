"""O sorteio de H8 reprodutivel, e a folha de auditoria (KAM-109)."""

from __future__ import annotations

import hashlib
import random
import unittest

from piloto import regras, sorteio

PRODUTOS = [
    sorteio.Produto(f"sku-{n:03d}", f"Produto sintetico {n}", 100 * n, n % 3 != 0)
    for n in range(1, 41)
]


class TestSorteio(unittest.TestCase):
    def test_e_o_sort_por_sha256_que_qualquer_um_refaz(self) -> None:
        # O oraculo e escrito aqui, com o hashlib, e nao importado do alvo.
        esperado = sorted(
            (p.produto_id for p in PRODUTOS),
            key=lambda i: hashlib.sha256(f"semente-de-ensaio:P03:{i}".encode()).hexdigest(),
        )[:20]
        amostra = sorteio.sortear("semente-de-ensaio", "P03", PRODUTOS)
        self.assertEqual([p.produto_id for p in amostra], esperado)

    def test_nao_depende_da_ordem_de_entrada(self) -> None:
        baralhados = PRODUTOS[:]
        random.Random(7).shuffle(baralhados)
        self.assertEqual(sorteio.sortear("s", "P01", PRODUTOS), sorteio.sortear("s", "P01", baralhados))

    def test_outra_semente_ou_outra_pme_da_outra_amostra(self) -> None:
        base = sorteio.sortear("s", "P01", PRODUTOS)
        self.assertNotEqual(base, sorteio.sortear("t", "P01", PRODUTOS))
        self.assertNotEqual(base, sorteio.sortear("s", "P02", PRODUTOS))

    def test_com_menos_de_20_sao_todos(self) -> None:
        self.assertEqual(len(sorteio.sortear("s", "P01", PRODUTOS[:7])), 7)
        self.assertEqual(len(sorteio.sortear("s", "P01", PRODUTOS)), regras.H8_AMOSTRA_POR_PME)

    def test_semente_vazia_e_produto_repetido_sao_erro(self) -> None:
        with self.assertRaises(ValueError):
            sorteio.sortear("  ", "P01", PRODUTOS)
        with self.assertRaises(ValueError):
            sorteio.sortear("s", "P01", PRODUTOS + PRODUTOS[:1])
        with self.assertRaises(ValueError):
            sorteio.sortear("s", "Loja da Ana", PRODUTOS)


def _preencher(folha: str, erros: int = 0, mudancas: str = "3") -> str:
    """Preenche a verdade igual ao sistema, com `erros` precos errados."""
    linhas = folha.splitlines()
    saida = [linhas[0]]
    for n, linha in enumerate(linhas[1:-1]):
        campos = linha.split(",")
        preco = campos[3] if n >= erros else str(int(campos[3] or 0) + 1)
        campos[5:8] = [preco, campos[4], "dono"]
        saida.append(",".join(campos))
    saida.append(f"mudancas,,,,,{mudancas},,")
    return "\n".join(saida) + "\n"


class TestFolha(unittest.TestCase):
    def setUp(self) -> None:
        self.folha = sorteio.folha(sorteio.sortear("s", "P01", PRODUTOS))

    def test_nasce_com_a_verdade_em_branco_e_e_recusada_assim(self) -> None:
        self.assertEqual(self.folha.splitlines()[0], ",".join(sorteio.COLUNAS_DA_FOLHA))
        with self.assertRaises(sorteio.FolhaInvalida):
            sorteio.ler_folha(self.folha, "P01")

    def test_ida_e_volta(self) -> None:
        auditoria = sorteio.ler_folha(_preencher(self.folha, erros=2), "P01", actualizacoes=4)
        self.assertEqual((auditoria.itens, auditoria.correctos), (20, 18))
        self.assertTrue(auditoria.correcto)
        self.assertEqual((auditoria.actualizacoes, auditoria.mudancas_declaradas), (4, 3))
        self.assertFalse(sorteio.ler_folha(_preencher(self.folha, erros=3), "P01").correcto)

    def test_a_disponibilidade_errada_tambem_conta(self) -> None:
        linhas = _preencher(self.folha).splitlines()
        campos = linhas[1].split(",")
        campos[6] = "nao" if campos[4] == "sim" else "sim"
        linhas[1] = ",".join(campos)
        self.assertEqual(sorteio.ler_folha("\n".join(linhas), "P01").correctos, 19)

    def test_preco_sob_consulta_compara_vazio_com_vazio(self) -> None:
        folha = sorteio.folha([sorteio.Produto("sku-x", "Bolo", None, True)])
        preenchida = folha.replace("sku-x,Bolo,,sim,,,", "sku-x,Bolo,,sim,,sim,visita")
        self.assertEqual(sorteio.ler_folha(preenchida, "P01").correctos, 1)

    def test_sem_coluna_de_notas(self) -> None:
        com_notas = self.folha.replace("fonte_verdade", "fonte_verdade,notas", 1)
        with self.assertRaises(sorteio.FolhaInvalida):
            sorteio.ler_folha(com_notas, "P01")

    def test_um_telefone_no_nome_recusa_a_folha(self) -> None:
        telefone = "9" + "23" + "456" + "789"  # montado em execucao, nao e literal
        for forma in (telefone, f"+244 {telefone}", f"{telefone[:3]} {telefone[3:6]} {telefone[6:]}"):
            with self.subTest(forma=forma), self.assertRaises(sorteio.FolhaInvalida):
                sorteio.folha([sorteio.Produto("sku-1", f"Bolo {forma}", 100, True)])

    def test_o_canario_do_telefone_morde_e_um_preco_nao(self) -> None:
        telefone = "9" + "1" * 8
        self.assertIsNotNone(sorteio._TELEFONE.search(f"ligue {telefone}"))
        self.assertIsNone(sorteio._TELEFONE.search("preco 912345"))
        self.assertIsNone(sorteio._TELEFONE.search("sku-a" + telefone + "b"))


if __name__ == "__main__":
    unittest.main()
