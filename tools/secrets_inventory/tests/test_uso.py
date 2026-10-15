"""Deteccao de segredo pedido pelo codigo e ausente do inventario (KAM-010).

Esta e a ferramenta do criterio de aceitacao «uma verificacao de CI falha se o
codigo pedir um segredo ausente do inventario». Hoje ela nao tem consumidores
reais para analisar — nenhum servico le segredos ainda, e os ficheiros da propria
porta estao excluidos por `analise_excluir` — pelo que **a prova de que funciona
sao estes casos**, e nao uma execucao sobre o repositorio.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from secrets_inventory.inventario import Inventario, Segredo
from secrets_inventory.uso import analisar_texto, ficheiros, verificar


def segredo(
    identificador: str, instancias: str = "nenhuma", consumidores: tuple[str, ...] = ("GWY",)
) -> Segredo:
    return Segredo(
        id=identificador,
        fonte_08_5="Meta App Secret",
        owner="eng_canais",
        rotacao_dias=182,
        rotacao_gatilho="incidente",
        ambientes=("dev", "prod"),
        obrigatorio_em=("prod",),
        consumidores=consumidores,
        instancias=instancias,
        anel=False,
        kid=False,
    )


def inventario(*segredos: Segredo, raizes: tuple[str, ...] = ("services",)) -> Inventario:
    return Inventario(
        segredos=segredos, raizes=raizes, excluir=(), estado="proposta"
    )


class TestDeteccao(unittest.TestCase):
    def test_pedido_literal_por_receptor_conhecido(self) -> None:
        for linha in (
            'const v = await secrets.get("meta_app_secret");',
            "valor = segredos.get('meta_app_secret')",
            'const v = cofre.get("meta_app_secret")',
            "v = secret_provider.get('meta_app_secret')",
        ):
            with self.subTest(linha=linha):
                achados, problemas = analisar_texto("a.ts", linha)
                self.assertEqual([a.referencia for a in achados], ["meta_app_secret"])
                self.assertEqual(problemas, [])

    def test_pedido_literal_por_metodo_proprio_da_porta(self) -> None:
        for linha in (
            'await qualquerCoisa.getRing("meta_app_secret")',
            "provider.get_ring('meta_app_secret')",
            'await p.versions("meta_app_secret")',
        ):
            with self.subTest(linha=linha):
                achados, _ = analisar_texto("a.ts", linha)
                self.assertEqual([a.referencia for a in achados], ["meta_app_secret"])

    def test_get_de_dicionario_nao_e_um_pedido(self) -> None:
        # A primeira versao deste verificador marcou 27 acessos a dicionario do
        # `tools/` como segredos em falta. Um verificador que grita em acessos a
        # dicionario e um verificador que alguem desliga.
        for linha in (
            'versao = dados.get("version")',
            'if manifesto.get("dependencies"):',
            'cfg.get("types", [])',
        ):
            with self.subTest(linha=linha):
                achados, problemas = analisar_texto("a.py", linha)
                self.assertEqual(achados, [])
                self.assertEqual(problemas, [])

    def test_variavel_de_ambiente(self) -> None:
        achados, _ = analisar_texto(
            "docker-compose.yml", "      - KAMBA_SECRET_META_APP_SECRET=${X}"
        )
        self.assertEqual([a.referencia for a in achados], ["meta_app_secret"])
        self.assertEqual(achados[0].origem, "variavel")

    def test_variavel_de_ambiente_com_instancia(self) -> None:
        achados, _ = analisar_texto(
            "a.env", "KAMBA_SECRET_META_CLIENT_TOKEN__7f3cAb=valor"
        )
        self.assertEqual([a.referencia for a in achados], ["meta_client_token/7f3cAb"])
        self.assertEqual(achados[0].familia, "meta_client_token")

    def test_o_sufixo_do_anel_nao_e_uma_familia_nova(self) -> None:
        # `..._ANTERIOR` e a segunda posicao do anel do mesmo segredo. Sem este
        # corte, todo o `.env` com um anel definido falharia a verificacao com um
        # nome que o inventario nunca vai ter.
        achados, _ = analisar_texto(
            ".env.example", "KAMBA_SECRET_META_APP_SECRET_ANTERIOR=x"
        )
        self.assertEqual([a.familia for a in achados], ["meta_app_secret"])

    def test_lista_de_obrigatorios(self) -> None:
        for texto in (
            'obrigatorios: ["meta_app_secret", "meta_verify_token"],',
            "obrigatorios=['meta_app_secret', 'meta_verify_token'],",
            'obrigatorios: [\n  "meta_app_secret",\n  "meta_verify_token",\n]',
        ):
            with self.subTest(texto=texto):
                achados, _ = analisar_texto("a.ts", texto)
                self.assertEqual(
                    sorted(a.referencia for a in achados),
                    ["meta_app_secret", "meta_verify_token"],
                )
                self.assertTrue(all(a.origem == "obrigatorios" for a in achados))

    def test_pedido_dinamico_sem_marca_e_um_problema(self) -> None:
        achados, problemas = analisar_texto("a.ts", "await secrets.get(nome);")
        self.assertEqual(achados, [])
        self.assertEqual(len(problemas), 1)
        self.assertIn("nome dinamico", problemas[0])
        self.assertIn("a.ts:1", problemas[0])

    def test_pedido_dinamico_com_marca_e_razao_passa(self) -> None:
        achados, problemas = analisar_texto(
            "a.ts",
            "await secrets.get(ref);  // kamba:secrets-inventory dinamico "
            "ref vem de tenant_channels.token_ref (KAM-003)",
        )
        self.assertEqual(achados, [])
        self.assertEqual(problemas, [])

    def test_marca_sem_razao_nao_conta(self) -> None:
        _, problemas = analisar_texto(
            "a.ts", "await secrets.get(ref);  // kamba:secrets-inventory dinamico"
        )
        self.assertEqual(len(problemas), 1)


class TestVerificacaoContraOInventario(unittest.TestCase):
    def _verificar(self, nome: str, conteudo: str, inv: Inventario) -> list[str]:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            alvo = raiz / "services" / "gwy" / nome
            alvo.parent.mkdir(parents=True)
            alvo.write_text(conteudo, encoding="utf-8")
            _, erros = verificar(raiz, inv)
            return erros

    def test_segredo_no_inventario_passa(self) -> None:
        erros = self._verificar(
            "server.ts",
            'const v = await secrets.get("meta_app_secret");',
            inventario(segredo("meta_app_secret")),
        )
        self.assertEqual(erros, [])

    def test_segredo_ausente_do_inventario_falha(self) -> None:
        erros = self._verificar(
            "server.ts",
            'const v = await secrets.get("chave_inventada");',
            inventario(segredo("meta_app_secret")),
        )
        self.assertEqual(len(erros), 1)
        self.assertIn("'chave_inventada'", erros[0])
        self.assertIn("ops/secrets-inventory.yaml", erros[0])

    def test_familia_sem_instancias_pedida_com_instancia_falha(self) -> None:
        erros = self._verificar(
            "server.ts",
            'await secrets.get("meta_app_secret/abc");',
            inventario(segredo("meta_app_secret", instancias="nenhuma")),
        )
        self.assertEqual(len(erros), 1)
        self.assertIn("instancias: nenhuma", erros[0])

    def test_familia_com_instancias_pedida_sem_instancia_falha(self) -> None:
        # Pedir a familia devolveria o segredo de nenhum dos tenants.
        erros = self._verificar(
            "server.ts",
            'await secrets.get("meta_client_token");',
            inventario(segredo("meta_client_token", instancias="tenant")),
        )
        self.assertEqual(len(erros), 1)
        self.assertIn("instancias: tenant", erros[0])

    def test_variavel_de_ambiente_ausente_do_inventario_falha(self) -> None:
        erros = self._verificar(
            "docker-compose.yml",
            "environment:\n  - KAMBA_SECRET_CHAVE_INVENTADA=x\n",
            inventario(segredo("meta_app_secret")),
        )
        self.assertEqual(len(erros), 1)
        self.assertIn("chave_inventada", erros[0])


class TestSelecaoDeFicheiros(unittest.TestCase):
    def test_uma_raiz_pode_ser_um_ficheiro(self) -> None:
        # O `.env.example` esta na raiz do repositorio, e declarar `.` como raiz
        # para o apanhar varreria o repositorio inteiro.
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            (raiz / ".env.example").write_text(
                "KAMBA_SECRET_META_APP_SECRET=x\n", encoding="utf-8"
            )
            inv = Inventario(
                segredos=(segredo("meta_app_secret"),),
                raizes=(".env.example",),
                excluir=(),
                estado="proposta",
            )
            escolhidos = [c.name for c in ficheiros(raiz, inv)]
            self.assertEqual(escolhidos, [".env.example"])
            achados, erros = verificar(raiz, inv)
            self.assertEqual(erros, [])
            self.assertEqual([a.referencia for a in achados], ["meta_app_secret"])


    def test_respeita_raizes_e_excepcoes_e_poda_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            for relativo in (
                "services/gwy/src/server.ts",
                "services/gwy/tests/server.test.ts",
                "services/gwy/node_modules/x/index.js",
                "services/gwy/dist/server.js",
                "docs/nota.md",
                "packages/core-ts/src/a.ts",
            ):
                alvo = raiz / relativo
                alvo.parent.mkdir(parents=True, exist_ok=True)
                alvo.write_text("// vazio\n", encoding="utf-8")

            inv = Inventario(
                segredos=(),
                raizes=("services", "packages"),
                excluir=("services/gwy/tests",),
                estado="proposta",
            )
            escolhidos = [c.relative_to(raiz).as_posix() for c in ficheiros(raiz, inv)]
            # A ordem segue `analise_raizes`, nao o alfabeto: ler o inventario
            # de cima para baixo e o que torna a saida reproduzivel.
            self.assertEqual(
                escolhidos, ["services/gwy/src/server.ts", "packages/core-ts/src/a.ts"]
            )


if __name__ == "__main__":
    unittest.main()
