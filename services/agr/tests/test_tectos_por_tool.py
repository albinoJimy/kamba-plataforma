"""Os tectos por tool da ToolLayer (KAM-231; decisao do fundador P3, opcao A).

Uma lista **fechada** substitui o tecto da classe so para as tools nela: hoje o
`create_product_draft`, com 25 s, que e o tempo de uma foto pela fonte, a
limpeza, a qualidade, o *gate* e a visao. As outras escritas ficam nos 8 s do
§6.5, e uma `read` nunca pode ter tecto proprio.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from kamba_agr.tls import camada as camada_mod
from kamba_agr.tls.camada import (
    MARGEM_DO_TECTO_MS,
    TECTOS_POR_TOOL,
    TIMEOUT_ESCRITA_POR_OMISSAO_MS,
    ConfiguracaoDaCamadaError,
    ToolLayer,
)
from kamba_agr.tls.catalogo import catalogo_do_piloto


def _camada(catalogo=None) -> ToolLayer:  # type: ignore[no-untyped-def]
    return ToolLayer(catalogo or catalogo_do_piloto(), abrir_ligacao=mock.Mock())


class TestATabela(unittest.TestCase):
    def test_e_so_o_create_product_draft_a_vinte_e_cinco_segundos(self) -> None:
        self.assertEqual(dict(TECTOS_POR_TOOL), {"create_product_draft": 25_000})

    def test_o_da_foto_e_os_outros(self) -> None:
        c = _camada()
        self.assertEqual(c.tecto_de(c.catalogo.get("create_product_draft")), 25_000)
        self.assertEqual(c._espera_de("create_product_draft"), 25_000 + MARGEM_DO_TECTO_MS)
        # As outras escritas do dono continuam nos 8 s.
        for nome in ("publish_product", "submit_quote"):
            with self.subTest(nome=nome):
                self.assertEqual(c.tecto_de(c.catalogo.get(nome)), TIMEOUT_ESCRITA_POR_OMISSAO_MS)

    def test_uma_read_com_tecto_proprio_recusa_o_arranque(self) -> None:
        catalogo = catalogo_do_piloto()
        leitura = catalogo.get("get_catalog_status")
        self.assertEqual(leitura.klass, "read")
        with mock.patch.dict(camada_mod.TECTOS_POR_TOOL, {"get_catalog_status": 25_000}):
            with self.assertRaises(ConfiguracaoDaCamadaError):
                _camada(catalogo)

    def test_o_executor_recebe_o_tecto_da_tool(self) -> None:
        """A ligacao, e nao so a funcao: o `Pedido.timeout_ms` e o tecto da tabela."""
        texto = Path(camada_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("timeout_ms=self.tecto_de(especificacao)", texto)
        self.assertNotIn("timeout_ms=self.timeout_de(especificacao.klass)", texto)
        self.assertIn("inv.inicio_da_espera + self.tecto_de(especificacao) / 1000", texto)


if __name__ == "__main__":
    unittest.main()
