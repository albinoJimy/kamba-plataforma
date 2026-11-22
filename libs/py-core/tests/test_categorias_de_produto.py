"""A lista fechada das categorias de produto e as suas copias (KAM-209).

O oraculo e `policy/categorias_de_produto.yaml`, lido aqui pelo `kamba_yaml`, e
nao nenhuma das copias: o `CHECK` da revisao, a constante de TypeScript e a de
Python leem-se do disco e comparam-se com ele. Mudar a lista num sitio so
avermelha este ficheiro.

E o mapeamento do texto livre da categoria para um `id` da lista, que e o que
o catalogo por IA manda ao COM e o que o resumo mostra ao dono.
"""

from __future__ import annotations

import re
import unittest
from decimal import Decimal
from pathlib import Path

import kamba_yaml

from kamba_core.catalogo import categorias
from kamba_core.catalogo.categorias import OUTRA, categoria_de_produto
from kamba_core.catalogo.extraccao import Campo
from kamba_core.catalogo.pipeline import resumo

RAIZ = Path(__file__).resolve().parents[3]
POLITICA = RAIZ / "policy" / "categorias_de_produto.yaml"
TYPESCRIPT = RAIZ / "packages" / "core-ts" / "src" / "trust" / "categorias.ts"
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_categoria_da_oferta.py"))


def _politica() -> dict:
    return kamba_yaml.load_file(POLITICA)


def _ids_do_typescript() -> list[str]:
    texto = TYPESCRIPT.read_text(encoding="utf-8")
    bloco = re.search(r"CATEGORIAS_DE_PRODUTO = \[(.*?)\] as const", texto, re.S)
    assert bloco is not None
    ids: list[str] = []
    for item in re.findall(r'"([a-z_]+)"|(CATEGORIA_OUTRA)', bloco.group(1)):
        ids.append(item[0] or OUTRA)
    outra = re.search(r'CATEGORIA_OUTRA = "([a-z_]+)"', texto)
    assert outra is not None and outra.group(1) == OUTRA
    return ids


def _ids_da_revisao() -> list[str]:
    texto = REVISAO.read_text(encoding="utf-8")
    bloco = re.search(r"^CHECK_DA_CATEGORIA = \((.*?)^\)$", texto, re.S | re.M)
    assert bloco is not None
    return re.findall(r"'([a-z_]+)'", bloco.group(1))


class TestAsCopiasSaoAPolitica(unittest.TestCase):
    def test_a_politica_tem_a_lista_da_decisao_do_fundador(self) -> None:
        """2026-11-21: as cinco familias do KYC, mais `servicos`, `material_construcao` e `outra`."""
        ids = [c["id"] for c in _politica()["categorias"]]
        self.assertEqual(
            ids,
            ["moda", "mercearia", "restauracao", "beleza", "electronica",
             "servicos", "material_construcao", "outra"],
        )

    def test_so_a_outra_nao_se_avalia(self) -> None:
        nao = [c["id"] for c in _politica()["categorias"] if not c["avalia_preco"]]
        self.assertEqual(nao, [OUTRA])

    def test_a_copia_python_e_a_politica(self) -> None:
        p = _politica()
        self.assertEqual(categorias.VERSAO, p["versao"])
        self.assertEqual(list(categorias.CATEGORIAS), [c["id"] for c in p["categorias"]])
        for c in p["categorias"]:
            with self.subTest(categoria=c["id"]):
                self.assertEqual(categorias.CATEGORIAS[c["id"]], frozenset(c["termos"]))
        self.assertEqual(
            categorias.AVALIA_PRECO, frozenset(c["id"] for c in p["categorias"] if c["avalia_preco"])
        )

    def test_a_copia_typescript_e_a_politica(self) -> None:
        p = _politica()
        self.assertEqual(_ids_do_typescript(), [c["id"] for c in p["categorias"]])
        versao = re.search(r'VERSAO_DAS_CATEGORIAS = "([0-9.]+)"', TYPESCRIPT.read_text(encoding="utf-8"))
        assert versao is not None
        self.assertEqual(versao.group(1), p["versao"])

    def test_o_check_da_revisao_e_a_politica(self) -> None:
        self.assertEqual(_ids_da_revisao(), [c["id"] for c in _politica()["categorias"]])

    def test_um_termo_nao_esta_em_duas_categorias(self) -> None:
        """O primeiro `id` ganha; um termo repetido seria uma categoria que nunca ganha por ele."""
        vistos: dict[str, str] = {}
        for c in _politica()["categorias"]:
            for t in c["termos"]:
                with self.subTest(termo=t):
                    self.assertNotIn(t, vistos, f"{t} em {vistos.get(t)} e em {c['id']}")
                    vistos[t] = c["id"]


class TestMapeamento(unittest.TestCase):
    def test_sem_texto_nao_ha_categoria(self) -> None:
        for vazio in (None, "", "   "):
            with self.subTest(texto=vazio):
                self.assertIsNone(categoria_de_produto(vazio))

    def test_um_id_da_lista_fica_ele_proprio(self) -> None:
        for c in categorias.CATEGORIAS:
            with self.subTest(categoria=c):
                self.assertEqual(categoria_de_produto(c), c)

    def test_o_texto_livre_vai_ao_id_pelas_palavras(self) -> None:
        casos = {
            "Vestuário": "moda",
            "camisa de homem": "moda",
            "Géneros alimentícios e bebidas": "mercearia",
            "Pastelaria": "restauracao",
            "Cosméticos": "beleza",
            "Telemóveis e acessórios": "electronica",
            "telemóvel": "electronica",
            "Reparação de electrodomésticos": "electronica",
            "Cimento e ferragens": "material_construcao",
            "artesanato": OUTRA,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(categoria_de_produto(texto), esperado)


class TestOResumoMostraACategoriaDaOferta(unittest.TestCase):
    """A confirmacao do dono cobre a categoria que a oferta leva."""

    def _campos(self, categoria: str) -> dict[str, Campo]:
        um = Decimal(1)
        return {
            "nome": Campo("Camisa polo", um, "dono_texto"),
            "categoria": Campo(categoria, um, "dono_texto"),
            "preco_tipo": Campo("fixo", um, "dono_texto"),
            "preco": Campo("1200000", um, "dono_texto"),
        }

    def test_o_texto_livre_leva_o_id_entre_parenteses(self) -> None:
        self.assertIn("categoria vestuario (moda)", resumo(self._campos("vestuario")))

    def test_um_id_da_lista_nao_se_repete(self) -> None:
        texto = resumo(self._campos("moda"))
        self.assertIn("categoria moda,", texto)
        self.assertNotIn("(moda)", texto)

    def test_o_que_nao_cabe_mostra_a_outra(self) -> None:
        self.assertIn("categoria artesanato (outra)", resumo(self._campos("artesanato")))


if __name__ == "__main__":
    unittest.main()
