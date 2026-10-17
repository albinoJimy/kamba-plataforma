"""O catalogo real, e o gate como um todo (KAM-007).

Os outros dois ficheiros testam a logica com schemas construidos para o efeito.
Este corre sobre **os trinta e oito contratos do repositorio** e sobre o CLI,
que e o que o `make ci-7` chama. Uma logica certa com um catalogo que nao
carrega nao serve de nada.
"""

from __future__ import annotations

import io
import contextlib
import unittest
from pathlib import Path

from contract_diff import catalogo, cli, exemplos, pii, subscricoes

RAIZ = Path(__file__).resolve().parents[3]

#: Os trinta e oito do dicionario §3.5, emenda 1.11. Escritos aqui a mao e nao
#: lidos do dicionario: se alguem apagar um contrato **e** a linha do
#: dicionario, uma contagem derivada dos dois continuava a bater.
ESPERADOS = 38


class TestOCatalogoDoRepositorio(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contratos = catalogo.todos(RAIZ)

    def test_sao_trinta_e_oito_e_carregam_todos(self) -> None:
        self.assertEqual(len(self.contratos), ESPERADOS)

    def test_cada_um_e_a_versao_1(self) -> None:
        """Enquanto nao houver v2, todos sao v1 — e o teste diz quando deixar de ser."""
        self.assertEqual({c.versao for c in self.contratos}, {1})

    def test_o_tipo_do_caminho_bate_com_o_const_do_schema(self) -> None:
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                propriedades = contrato.documento["properties"]
                self.assertEqual(propriedades["tipo"]["const"], contrato.tipo)
                self.assertEqual(propriedades["versao"]["const"], contrato.versao)

    def test_todos_tem_os_catorze_campos_de_topo(self) -> None:
        """A emenda 1.11: nem um a mais, nem um a menos."""
        esperados = {
            "id", "tipo", "versao", "tenant_id", "ocorrido_em", "registado_em",
            "produtor", "agregado", "correlacao_id", "causa_id", "trace_id",
            "classe_pii", "finalidades", "payload",
        }
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                self.assertEqual(set(contrato.documento["properties"]), esperados)
                self.assertEqual(set(contrato.documento["required"]), esperados)

    def test_todos_sao_fechados_a_cabeca_e_no_payload(self) -> None:
        """`additionalProperties: false` nos dois niveis (criterio 2)."""
        for contrato in self.contratos:
            with self.subTest(tipo=contrato.tipo):
                self.assertIs(contrato.documento["additionalProperties"], False)
                self.assertIs(contrato.payload["additionalProperties"], False)

    def test_o_dinheiro_e_inteiro_e_a_moeda_e_explicita(self) -> None:
        """Criterio 2: «valores monetarios sao inteiros; moeda explicita»."""
        com_dinheiro = 0
        for contrato in self.contratos:
            propriedades = contrato.payload.get("properties") or {}
            monetarios = [n for n in propriedades if n.endswith("_minor")]
            if not monetarios:
                continue
            com_dinheiro += 1
            with self.subTest(tipo=contrato.tipo):
                for nome in monetarios:
                    tipos = propriedades[nome].get("type")
                    tipos = tipos if isinstance(tipos, list) else [tipos]
                    self.assertIn("integer", tipos, f"{nome} nao e inteiro")
                    self.assertNotIn("number", tipos, f"{nome} aceita virgula flutuante")
                self.assertIn(
                    "currency", propriedades,
                    f"{contrato.tipo} tem dinheiro e nao diz a moeda",
                )
                self.assertEqual(propriedades["currency"]["enum"], ["AOA"])
        self.assertGreaterEqual(com_dinheiro, 6, "o teste deixou de ver os contratos de dinheiro")

    def test_nenhum_nome_de_campo_e_de_pii(self) -> None:
        self.assertEqual([str(a) for a in pii.nomes(RAIZ)], [])

    def test_nenhum_ficheiro_tem_telefone(self) -> None:
        self.assertEqual([str(a) for a in pii.fixtures(RAIZ)], [])

    def test_cada_contrato_tem_exemplo_valido(self) -> None:
        self.assertEqual([str(a) for a in exemplos.validar(RAIZ)], [])
        self.assertEqual([str(a) for a in exemplos.coerencia(RAIZ)], [])


class TestSubscricoesVazias(unittest.TestCase):
    """A verificacao que hoje passa sobre um conjunto vazio, e di-lo."""

    def test_nao_ha_subscricoes_declaradas(self) -> None:
        """Se isto falhar, o KAM-038 chegou — e o teste de cima passa a morder."""
        self.assertEqual(subscricoes.ler(RAIZ), [])

    def test_mas_a_verificacao_morde_com_uma_inventada(self) -> None:
        inventada = [subscricoes.Subscricao("(teste)", "ensaio", "order.created", 99)]
        (achado,) = subscricoes.verificar(RAIZ, inventada)
        self.assertIn("versao_max=99", achado.porque)
        self.assertIn("[1]", achado.porque)

    def test_e_morde_um_tipo_que_nao_existe(self) -> None:
        inventada = [subscricoes.Subscricao("(teste)", "ensaio", "nao.existe", 1)]
        (achado,) = subscricoes.verificar(RAIZ, inventada)
        self.assertIn("nao tem contrato nenhum", achado.porque)


class TestCli(unittest.TestCase):
    def correr(self, *argumentos: str) -> tuple[int, str]:
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--root", str(RAIZ), *argumentos])
        return codigo, saida.getvalue()

    def test_o_canario_prova_que_as_quatro_mordem(self) -> None:
        codigo, texto = self.correr("canario")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)
        self.assertIn("0 falha(s)", texto)

    def test_o_lint_de_pii_esta_conforme(self) -> None:
        codigo, texto = self.correr("pii")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)
        self.assertIn(f"{ESPERADOS} contrato(s)", texto)

    def test_os_exemplos_validam(self) -> None:
        codigo, texto = self.correr("exemplos")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)

    def test_as_subscricoes_dizem_que_sao_zero(self) -> None:
        """Zero e um numero visivel, e nao um silencio."""
        codigo, texto = self.correr("subscricoes")
        self.assertEqual(codigo, cli.SAIDA_OK, texto)
        self.assertIn("0 subscricoes declaradas", texto)

    def test_sem_base_diz_que_nao_correu(self) -> None:
        """Uma verificacao que se desliga tem de o dizer na saida."""
        codigo, texto = self.correr("--sem-base", "diff")
        self.assertEqual(codigo, cli.SAIDA_OK)
        self.assertIn("**nao correu**", texto)

    def test_uma_base_que_nao_existe_e_erro_de_ambiente_e_nao_silencio(self) -> None:
        codigo, texto = self.correr("--base", "nao/existe/de/certeza", "diff")
        self.assertEqual(codigo, cli.SAIDA_ERRO, texto)
        self.assertIn("fetch-depth", texto)


if __name__ == "__main__":
    unittest.main()
