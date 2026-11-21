"""Zero publicacao em redes sociais no repositorio (KAM-122, criterio 7).

Os textos proibidos estao escritos **por partes**, como no modulo: este ensaio
tambem e varrido, e nao se exclui.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lint_arch import redes_sociais

RAIZ = Path(__file__).resolve().parents[3]

#: Um caso que tem de morder por padrao. Montados por partes.
MORDE = {
    "caminho de publicacao": (
        'url = f"/{conta}/' + "media" + "_publish" + '"',
        'requests.post(f"https://x/{pagina}/' + "fe" + 'ed")',
        'cliente.post("/me/' + "pho" + 'tos", dados)',
        # Achado 5 da revisao adversarial: os que passavam.
        'f"https://graph.facebook.com/{pagina}/' + "vid" + 'eos"',
    ),
    "anfitriao de rede": (
        'UPLOAD = "https://rupl' + 'oad.facebook.com/x"',
        'BASE = "https://graph.' + "insta" + 'gram.com"',
        'BASE = "https://open.' + "tiktok" + 'apis.com/v2"',
    ),
    "permissao de publicacao": (
        'scopes = ["pages_manage_' + 'posts"]',
        'scopes = ["instagram_business_content_' + 'publish"]',
        'scopes = ["threads_content_' + 'publish"]',
    ),
    "segredo de rede": (
        "INSTA" + "GRAM_ACCESS_TOK" + "EN=abc",
        "FACE" + "BOOK_PAGE_SEC" + "RET: ${X}",
        "TIK" + "TOK_CLIENT_KEY=",
        "PAGE_ACCESS_TOK" + "EN",
        "IG_ACCESS_TOK" + "EN=x",
        "FB_APP_SEC" + "RET=x",
        "FB_ACCESS_TOK" + "EN=x",
        "META_PAGE_TOK" + "EN=x",
        "insta" + "gram_tok" + "en: ${X}",
    ),
}

#: O que **nao** pode morder: o que o repositorio usa legitimamente.
NAO_MORDE = (
    'GRAPH = "https://graph.facebook.com/v21.0"',  # a Cloud API do WhatsApp
    "META_ACCESS_TOKEN=",  # o segredo do WhatsApp
    "WHATSAPP_TOKEN=",
    "# o dono publica a mao no Instagram",  # a palavra solta nao e um caminho
    'feedback = "/feedback"',  # um segmento que comeca por feed
    "fotos/produto.jpg",
    "CONFIG_TOKEN=x",  # tem «IG» por dentro, e nao e de rede
    "BIG_SECRET_KEY",
    "WA_PAGE_SIZE=10",
)


class TestRepositorio(unittest.TestCase):
    def test_o_repositorio_nao_tem_publicacao_em_redes(self) -> None:
        self.assertEqual(redes_sociais.check(RAIZ), [])

    def test_a_varredura_le_o_git_e_nao_o_disco(self) -> None:
        # Uma varredura de zero ficheiros reportava conforme; a do git nao e zero.
        seguidos = redes_sociais._do_git(RAIZ)
        self.assertGreater(len(seguidos), 1000)
        self.assertIn("tools/lint_arch/destinos.py", seguidos)

    def test_este_modulo_e_o_ensaio_sao_varridos_e_estao_limpos(self) -> None:
        proprios = ["tools/lint_arch/redes_sociais.py", "tools/lint_arch/tests/test_redes_sociais.py"]
        self.assertEqual(redes_sociais.check(RAIZ, proprios), [])


class TestCanario(unittest.TestCase):
    def test_cada_padrao_morde(self) -> None:
        for tipo, linhas in MORDE.items():
            for linha in linhas:
                with self.subTest(linha=linha):
                    achados = redes_sociais.achados_no_texto("x.py", linha)
                    self.assertTrue(achados, linha)
                    self.assertTrue(any(tipo in a for a in achados), achados)

    def test_o_legitimo_nao_morde(self) -> None:
        for linha in NAO_MORDE:
            with self.subTest(linha=linha):
                self.assertEqual(redes_sociais.achados_no_texto("x.py", linha), [])

    def test_codigo_e_configuracao_mordem_e_os_documentos_nao(self) -> None:
        segredo = "INSTA" + "GRAM_ACCESS_TOK" + "EN=abc\n"
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            for nome in (".env.example", "infra/compose/x.yml", "services/a/src/b.ts", "docs/nota.md"):
                caminho = raiz / nome
                caminho.parent.mkdir(parents=True, exist_ok=True)
                caminho.write_text(segredo, encoding="utf-8")
            achados = redes_sociais.check(
                raiz, [".env.example", "infra/compose/x.yml", "services/a/src/b.ts", "docs/nota.md"]
            )
        self.assertEqual(
            sorted(a.split(":")[0] for a in achados),
            [".env.example", "infra/compose/x.yml", "services/a/src/b.ts"],
        )

    def test_uma_falha_do_git_levanta_e_nao_da_conforme(self) -> None:
        falha = mock.Mock(returncode=128, stdout="")
        with mock.patch.object(redes_sociais.subprocess, "run", return_value=falha):
            with self.assertRaises(RuntimeError):
                redes_sociais.check(RAIZ)


if __name__ == "__main__":
    unittest.main()
