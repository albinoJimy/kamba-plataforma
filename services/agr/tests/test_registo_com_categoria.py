"""A categoria no corpo do `upsert-product-draft` (KAM-209).

O catalogo por IA manda ao COM o `id` da lista fechada que o resumo mostrou ao
dono, e nao o texto livre da ingestao. Sem categoria, a chave nao vai.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from kamba_core.catalogo.extraccao import Campo
from kamba_core.catalogo.pipeline import resumo

from kamba_agr.tls.registo_com import corpo_do_rascunho

UM = Decimal(1)


def _campos(**extra: str) -> dict[str, Campo]:
    base = {"nome": "Camisa polo", "preco_tipo": "fixo", "preco": "1200000"}
    return {n: Campo(v, UM, "dono_texto") for n, v in {**base, **extra}.items()}


class TestCategoriaNoRascunho(unittest.TestCase):
    def test_o_texto_livre_vai_como_o_id_da_lista(self) -> None:
        corpo = corpo_do_rascunho("cat-1", _campos(categoria="Vestuário de senhora"))
        self.assertEqual(corpo["categoria"], "moda")

    def test_vai_o_mesmo_id_que_o_resumo_mostrou_ao_dono(self) -> None:
        campos = _campos(categoria="cimento")
        self.assertIn("(material_construcao)", resumo(campos))
        self.assertEqual(corpo_do_rascunho("cat-1", campos)["categoria"], "material_construcao")

    def test_o_que_nao_cabe_vai_como_outra(self) -> None:
        self.assertEqual(corpo_do_rascunho("cat-1", _campos(categoria="artesanato"))["categoria"], "outra")

    def test_sem_categoria_a_chave_nao_vai(self) -> None:
        self.assertNotIn("categoria", corpo_do_rascunho("cat-1", _campos()))


if __name__ == "__main__":
    unittest.main()
