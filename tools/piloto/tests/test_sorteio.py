"""O sorteio de H8 reprodutivel, e a folha de auditoria (KAM-109)."""

from __future__ import annotations

import datetime as dt
import hashlib
import random
import unittest

from piloto import guarda, regras, sorteio

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


def preencher(folha: str, erros: int = 0, mudancas: str = "3",
              dia: str = "2027-01-27", fonte: str = "dono") -> str:
    """Preenche a verdade igual ao sistema, com `erros` precos errados."""
    linhas = folha.splitlines()
    saida = [linhas[0]]
    itens = [l for l in linhas[1:] if not l.startswith(("mudancas,", "auditado_em,"))]
    for n, linha in enumerate(itens):
        campos = linha.split(",")
        preco = campos[3] if n >= erros else str(int(campos[3] or 0) + 1)
        campos[5:8] = [preco, campos[4], fonte]
        saida.append(",".join(campos))
    saida.append(f"mudancas,,,,,{mudancas},,")
    saida.append(f"auditado_em,,,,,{dia},,")
    return "\n".join(saida) + "\n"


class TestFolha(unittest.TestCase):
    def setUp(self) -> None:
        self.amostra = sorteio.sortear("s", "P01", PRODUTOS)
        self.folha = sorteio.folha(self.amostra)

    def test_nasce_com_a_verdade_em_branco_e_e_recusada_assim(self) -> None:
        self.assertEqual(self.folha.splitlines()[0], ",".join(sorteio.COLUNAS_DA_FOLHA))
        self.assertEqual(self.folha.splitlines()[-2:], ["mudancas,,,,,,,", "auditado_em,,,,,,,"])
        with self.assertRaises(sorteio.FolhaInvalida):
            sorteio.ler_folha(self.folha, "P01")

    def test_ida_e_volta(self) -> None:
        lida = sorteio.ler_folha(preencher(self.folha, erros=2), "P01", actualizacoes=4)
        auditoria = lida.auditoria
        self.assertEqual((auditoria.itens, auditoria.correctos), (20, 18))
        self.assertTrue(auditoria.correcto)
        self.assertEqual((auditoria.actualizacoes, auditoria.mudancas_declaradas), (4, 3))
        self.assertEqual(auditoria.auditado_em, dt.date(2027, 1, 27))
        self.assertEqual(list(lida.produtos), [p.produto_id for p in self.amostra])
        self.assertFalse(sorteio.ler_folha(preencher(self.folha, erros=3), "P01").auditoria.correcto)

    def test_as_linhas_de_controlo_sao_obrigatorias(self) -> None:
        sem_mudancas = preencher(self.folha).replace("mudancas,,,,,3,,", "mudancas,,,,,,,")
        sem_dia = preencher(self.folha).replace("auditado_em,,,,,2027-01-27,,", "auditado_em,,,,,,,")
        dia_mau = preencher(self.folha, dia="27/01/2027")
        sem_linhas = "".join(l for l in preencher(self.folha).splitlines(keepends=True)
                             if not l.startswith(("mudancas,", "auditado_em,")))
        for texto in (sem_mudancas, sem_dia, dia_mau, sem_linhas):
            with self.subTest(), self.assertRaises(sorteio.FolhaInvalida):
                sorteio.ler_folha(texto, "P01")

    def test_a_numeracao_que_salta_e_recusada(self) -> None:
        linhas = preencher(self.folha).splitlines()
        del linhas[3]
        with self.assertRaises(sorteio.FolhaInvalida):
            sorteio.ler_folha("\n".join(linhas), "P01")

    def test_a_disponibilidade_errada_tambem_conta(self) -> None:
        linhas = preencher(self.folha).splitlines()
        campos = linhas[1].split(",")
        campos[6] = "nao" if campos[4] == "sim" else "sim"
        linhas[1] = ",".join(campos)
        self.assertEqual(sorteio.ler_folha("\n".join(linhas), "P01").auditoria.correctos, 19)

    def test_preco_sob_consulta_compara_vazio_com_vazio(self) -> None:
        folha = sorteio.folha([sorteio.Produto("sku-x", "Bolo", None, True)])
        lida = sorteio.ler_folha(preencher(folha), "P01")
        self.assertEqual(lida.auditoria.correctos, 1)

    def test_sem_coluna_de_notas(self) -> None:
        com_notas = self.folha.replace("fonte_verdade", "fonte_verdade,notas", 1)
        with self.assertRaises(sorteio.FolhaInvalida):
            sorteio.ler_folha(com_notas, "P01")

    def test_um_telefone_no_nome_recusa_a_folha(self) -> None:
        movel = "9" + "23" + "456" + "789"  # montado em execucao, nao e literal
        fixo = "2" + "22" + "123" + "456"
        formas = (
            movel, f"+244 {movel}", f"00244{movel}", f"tel{movel}",
            f"{movel[:3]} {movel[3:6]} {movel[6:]}", f"{movel[:3]} {movel[3:5]} {movel[5:7]} {movel[7:]}",
            f"({movel[:3]}) {movel[3:]}", fixo, f"+244 {fixo[:3]} {fixo[3:6]} {fixo[6:]}",
        )
        for forma in formas:
            with self.subTest(forma=forma), self.assertRaises(sorteio.FolhaInvalida):
                sorteio.folha([sorteio.Produto("sku-1", f"Bolo {forma}", 100, True)])


class TestGuarda(unittest.TestCase):
    def test_o_canario_morde_e_os_numeros_do_negocio_nao(self) -> None:
        movel = "9" + "1" * 8
        self.assertTrue(guarda.tem_telefone(f"ligue {movel}"))
        self.assertTrue(guarda.tem_telefone("indicativo +244 sozinho"))
        for texto in ("preco 912345", "2027-01-05 a 2027-01-11", "| 0.10 | 1h15 |",
                      "Pack de 6 garrafas de 1,5 L", "sku-0012"):
            with self.subTest(texto=texto):
                self.assertFalse(guarda.tem_telefone(texto))

    def test_o_uuid(self) -> None:
        self.assertTrue(guarda.tem_uuid("00000000-0000-4000-8000-000000000001"))
        self.assertFalse(guarda.tem_uuid("P01"))


if __name__ == "__main__":
    unittest.main()
