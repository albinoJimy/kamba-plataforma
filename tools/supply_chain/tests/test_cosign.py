"""A forma do comando `cosign verify` (KAM-030, criterio 1).

O inventario de imagens ganhou uma entrada com `cosign: verificar` — o proxy
LiteLLM, a primeira imagem assinada que o repositorio referencia — e isso
obrigou a corrigir uma suposicao que estava no `cosign.py` desde o KAM-067: ele
montava sempre o comando do fluxo *keyless* do Fulcio
(`--certificate-identity`, `--certificate-oidc-issuer`), com a nota a dizer que
a forma era «lida de memoria: NAO VERIFICADO».

Mediu-se, e estava errada para esta imagem: o LiteLLM assina **com uma chave**
(ECDSA P-256) e a sua assinatura nao tem certificado nenhum, pelo que nao existe
identidade OIDC nem emissor para escrever (`docs/evidencia/KAM-030-litellm.md`
§1).

**O canario desta bateria** e `test_uma_entrada_com_as_duas_formas_e_recusada`:
sem ele, declarar identidade **e** chave passava, e ninguem saberia qual delas o
`cosign verify` usou — uma entrada que parece verificar duas coisas e verifica
uma e pior do que uma que verifica uma so.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from supply_chain import cosign, imagens
from supply_chain.base import ConfiguracaoInvalida


def _entrada(**trocas) -> imagens.Entrada:
    campos = {
        "nome": "ghcr.io/exemplo/imagem",
        "etiqueta": "v1.0.0",
        "digest": "sha256:" + "a" * 64,
        "lido_em": "2026-10-26",
        "lido_de": "ensaio",
        "componentes": ("exemplo",),
        "cosign": imagens.COSIGN_VERIFICAR,
        "cosign_razao": "ensaio" * 10,
        "cosign_identidade": "",
        "cosign_emissor": "",
        "cosign_chave_publica": "",
    }
    campos.update(trocas)
    return imagens.Entrada(**campos)


class TestAFormaDoComando(unittest.TestCase):
    def test_com_chave_publica_usa_key(self) -> None:
        comando = cosign.comando_para(_entrada(cosign_chave_publica="ci/x.pub"))
        self.assertIn("--key", comando)
        self.assertIn("ci/x.pub", comando)
        self.assertNotIn("--certificate-identity", comando)
        self.assertNotIn("--certificate-oidc-issuer", comando)

    def test_com_identidade_usa_os_dois_certificate(self) -> None:
        comando = cosign.comando_para(
            _entrada(
                cosign_identidade="https://exemplo.ao/.github/workflows/x.yml@refs/tags/v1",
                cosign_emissor="https://token.actions.githubusercontent.com",
            )
        )
        self.assertIn("--certificate-identity", comando)
        self.assertIn("--certificate-oidc-issuer", comando)
        self.assertNotIn("--key", comando)

    def test_verifica_o_digest_e_nunca_a_etiqueta(self) -> None:
        """A etiqueta e o que se move; o digest e o que fixa o conteudo."""
        entrada = _entrada(cosign_chave_publica="ci/x.pub")
        comando = cosign.comando_para(entrada)
        self.assertEqual(comando[-1], f"{entrada.nome}@{entrada.digest}")
        self.assertNotIn(entrada.etiqueta, comando[-1])

    def test_a_chave_resolve_contra_a_raiz_quando_ha_raiz(self) -> None:
        """O `cosign` corre no *runner*, com o caminho absoluto da arvore."""
        raiz = pathlib.Path("/tmp/arvore")
        comando = cosign.comando_para(_entrada(cosign_chave_publica="ci/x.pub"), raiz)
        self.assertIn(str(raiz / "ci/x.pub"), comando)


class TestOLeitorExigeUmaFormaSo(unittest.TestCase):
    """O leitor do inventario e quem garante a invariante do `comando_para`."""

    def setUp(self) -> None:
        self.raiz = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        (self.raiz / "ci" / "supply-chain").mkdir(parents=True)
        (self.raiz / "ci" / "supply-chain" / "chave.pub").write_bytes(b"-----BEGIN\n")

    def _escrever(self, extra: str) -> None:
        texto = (
            "version: 1\n"
            "imagens:\n"
            "  - nome: ghcr.io/exemplo/imagem\n"
            "    etiqueta: v1.0.0\n"
            f"    digest: \"sha256:{'a' * 64}\"\n"
            '    lido_em: "2026-10-26"\n'
            "    lido_de: ensaio\n"
            "    componentes:\n"
            "      - exemplo\n"
            "    cosign: verificar\n"
            + extra
            + "fontes_adicionais: []\n"
        )
        (self.raiz / imagens.INVENTARIO).write_bytes(texto.encode("utf-8"))

    def _ler(self):
        return imagens.ler_inventario(self.raiz)

    def test_so_com_chave_publica_passa(self) -> None:
        self._escrever("    cosign_chave_publica: ci/supply-chain/chave.pub\n")
        entradas = self._ler().entradas
        self.assertEqual(entradas[0].cosign_chave_publica, "ci/supply-chain/chave.pub")

    def test_so_com_identidade_passa(self) -> None:
        self._escrever(
            "    cosign_identidade: https://exemplo.ao/x\n"
            "    cosign_emissor: https://token.actions.githubusercontent.com\n"
        )
        self.assertEqual(self._ler().entradas[0].cosign_emissor.startswith("https://"), True)

    def test_uma_entrada_com_as_duas_formas_e_recusada(self) -> None:
        """O canario desta bateria."""
        self._escrever(
            "    cosign_chave_publica: ci/supply-chain/chave.pub\n"
            "    cosign_identidade: https://exemplo.ao/x\n"
            "    cosign_emissor: https://token.actions.githubusercontent.com\n"
        )
        with self.assertRaises(ConfiguracaoInvalida) as apanhado:
            self._ler()
        self.assertIn("uma forma so", str(apanhado.exception))

    def test_uma_entrada_sem_nenhuma_forma_e_recusada(self) -> None:
        self._escrever("")
        with self.assertRaises(ConfiguracaoInvalida) as apanhado:
            self._ler()
        self.assertIn("cosign_chave_publica", str(apanhado.exception))

    def test_uma_chave_que_nao_existe_e_recusada(self) -> None:
        """Um caminho que nao existe fazia o `cosign verify` falhar no runner."""
        self._escrever("    cosign_chave_publica: ci/supply-chain/nao_existe.pub\n")
        with self.assertRaises(ConfiguracaoInvalida) as apanhado:
            self._ler()
        self.assertIn("nao existe", str(apanhado.exception))

    def test_identidade_sem_emissor_e_recusada(self) -> None:
        self._escrever(
            "    cosign_identidade: https://exemplo.ao/x\n"
            "    cosign_chave_publica: ci/supply-chain/chave.pub\n"
        )
        with self.assertRaises(ConfiguracaoInvalida):
            self._ler()


class TestFalhaFechado(unittest.TestCase):
    """Uma verificacao que nao corre **nao passa**. Ja era assim; mede-se aqui."""

    def test_sem_binario_falha(self) -> None:
        inventario = imagens.Inventario(
            entradas=(_entrada(cosign_chave_publica="ci/x.pub"),), fontes={}
        )
        achados, resumo = cosign.verificar(
            inventario, executor=lambda c: (0, ""), tem_binario=lambda: False
        )
        self.assertEqual(len(achados), 1)
        self.assertEqual(achados[0].regra, "cosign-sem-binario")
        self.assertEqual(resumo["verificadas"], 0)

    def test_o_binario_a_falhar_e_achado(self) -> None:
        inventario = imagens.Inventario(
            entradas=(_entrada(cosign_chave_publica="ci/x.pub"),), fontes={}
        )
        achados, _ = cosign.verificar(
            inventario,
            executor=lambda c: (1, "no matching signatures"),
            tem_binario=lambda: True,
        )
        self.assertEqual(len(achados), 1)
        self.assertEqual(achados[0].regra, "cosign-falhou")

    def test_sem_imagens_a_verificar_passa(self) -> None:
        inventario = imagens.Inventario(
            entradas=(_entrada(cosign=imagens.COSIGN_POR_APURAR),), fontes={}
        )
        achados, resumo = cosign.verificar(inventario, tem_binario=lambda: False)
        self.assertEqual(achados, [])
        self.assertEqual(resumo["a_verificar"], 0)


class TestOInventarioRealDoRepositorio(unittest.TestCase):
    def test_o_litellm_verifica_se_por_chave(self) -> None:
        raiz = pathlib.Path(__file__).resolve().parents[3]
        inventario = imagens.ler_inventario(raiz)
        litellm = [e for e in inventario.entradas if "litellm" in e.nome]
        self.assertEqual(len(litellm), 1)
        entrada = litellm[0]
        self.assertEqual(entrada.cosign, imagens.COSIGN_VERIFICAR)
        self.assertTrue(entrada.cosign_chave_publica)
        self.assertFalse(entrada.cosign_identidade)
        self.assertTrue((raiz / entrada.cosign_chave_publica).is_file())

    def test_a_etiqueta_traz_a_versao_para_o_piso_do_blocklist(self) -> None:
        """Um digest sozinho nao prova versao nenhuma sem rede."""
        raiz = pathlib.Path(__file__).resolve().parents[3]
        litellm = [
            e for e in imagens.ler_inventario(raiz).entradas if "litellm" in e.nome
        ][0]
        self.assertTrue(litellm.etiqueta.startswith("v1."))
        maior, menor = litellm.etiqueta.lstrip("v").split(".")[:2]
        self.assertGreaterEqual((int(maior), int(menor)), (1, 83))


if __name__ == "__main__":
    unittest.main()
