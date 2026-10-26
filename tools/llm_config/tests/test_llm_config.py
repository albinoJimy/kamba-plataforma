"""O gerador e o *lint* dos aliases (KAM-030, criterio 7).

O criterio 7 diz: «Alterar o modelo atras de um alias exige *bump* SemVer em
`llm/aliases.yaml` e passa pelo Gate 13; CI falha se o *hash* do ficheiro mudar
sem nova versao». A segunda metade e o que estas baterias medem; a primeira — o
Gate 13, eval golden PT-AO — **nao existe** e nasce com o KAM-040.

**O canario que importa:** `test_conteudo_mudado_sem_bump_falha`. Sem ele, um
*lint* que devolvesse sempre `[]` passava, e era exactamente o que a primeira
versao deste mecanismo fazia — o *hash* incluia a `versao` no texto que
hasheava, pelo que «mudou o conteudo e nao a versao» nunca se distinguia de
«mudou a versao». Esta e a razao de `test_o_hash_nao_depende_da_versao`.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

import llm_config
from llm_config import cli as llm_cli


def _raiz_do_repositorio() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


class _ComCopia(unittest.TestCase):
    """Cada bateria trabalha numa copia da arvore: nada toca no repositorio."""

    def setUp(self) -> None:
        origem = _raiz_do_repositorio()
        self.raiz = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        (self.raiz / "llm").mkdir()
        (self.raiz / "ci").mkdir()
        shutil.copy(origem / "llm" / "aliases.yaml", self.raiz / "llm" / "aliases.yaml")
        shutil.copy(origem / "llm" / "precos.yaml", self.raiz / "llm" / "precos.yaml")
        self._escrever_calado()

    def _escrever_calado(self) -> None:
        """O `escrever` diz o que fez; vinte e duas baterias dizem-no vinte e duas vezes."""
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            llm_cli.escrever(self.raiz)

    def _texto(self, rel: str) -> str:
        return (self.raiz / rel).read_text(encoding="utf-8")

    def _reescrever(self, rel: str, velho: str, novo: str) -> None:
        caminho = self.raiz / rel
        texto = caminho.read_text(encoding="utf-8")
        self.assertIn(velho, texto)
        caminho.write_bytes(texto.replace(velho, novo, 1).encode("utf-8"))


class TestOEstadoGeradoEstaEmDia(_ComCopia):
    def test_depois_de_escrever_esta_conforme(self) -> None:
        self.assertEqual(llm_cli.check(self.raiz), [])

    def test_a_config_apagada_e_achado(self) -> None:
        (self.raiz / llm_config.CONFIG).unlink()
        achados = llm_cli.check(self.raiz)
        self.assertTrue(any(llm_config.CONFIG in a for a in achados))

    def test_o_lock_apagado_e_achado(self) -> None:
        (self.raiz / llm_config.LOCK).unlink()
        achados = llm_cli.check(self.raiz)
        self.assertTrue(any(llm_config.LOCK in a for a in achados))

    def test_a_config_editada_a_mao_e_achado(self) -> None:
        """O proxy serviria um modelo que o artefacto versionado nao nomeia."""
        self._reescrever(llm_config.CONFIG, "timeout: 20", "timeout: 99")
        self.assertTrue(llm_cli.check(self.raiz))


class TestOBumpSemVer(_ComCopia):
    """Criterio 7, a parte que existe."""

    def test_conteudo_mudado_sem_bump_falha(self) -> None:
        """O canario central deste ticket."""
        self._reescrever("llm/aliases.yaml", "    timeout: 8", "    timeout: 9")
        achados = llm_cli.check(self.raiz)
        self.assertTrue(achados)
        self.assertTrue(
            any("bump" in a.lower() or "versao" in a.lower() for a in achados),
            f"a mensagem tem de dizer o que fazer: {achados}",
        )

    def test_conteudo_mudado_com_bump_e_lock_novo_passa(self) -> None:
        self._reescrever("llm/aliases.yaml", "    timeout: 8", "    timeout: 9")
        self._reescrever("llm/aliases.yaml", 'versao: "1.0.0"', 'versao: "1.1.0"')
        self._escrever_calado()
        self.assertEqual(llm_cli.check(self.raiz), [])

    def test_versao_mudada_sem_lock_novo_falha(self) -> None:
        """Subir a versao e metade: o *lock* tem de ir no mesmo *commit*."""
        self._reescrever("llm/aliases.yaml", 'versao: "1.0.0"', 'versao: "1.1.0"')
        self.assertTrue(llm_cli.check(self.raiz))

    def test_o_hash_nao_depende_da_versao(self) -> None:
        """Com a versao dentro do hash, o mecanismo nao distinguia nada.

        Era o defeito da primeira versao: o cabecalho gerado nomeia a `versao`, e
        hashear o texto inteiro punha-a dentro do hash.
        """
        antes = llm_config.impressao(llm_config.ler(self.raiz))
        self._reescrever("llm/aliases.yaml", 'versao: "1.0.0"', 'versao: "2.0.0"')
        depois = llm_config.impressao(llm_config.ler(self.raiz))
        self.assertEqual(antes, depois)

    def test_uma_versao_que_nao_e_semver_e_recusada(self) -> None:
        self._reescrever("llm/aliases.yaml", 'versao: "1.0.0"', 'versao: "ultima"')
        with self.assertRaises(llm_config.AliasesInvalidos):
            llm_cli.check(self.raiz)


class TestAValidacaoDosAliases(_ComCopia):
    def test_um_fornecedor_fora_do_inventario_e_recusado(self) -> None:
        self._reescrever("llm/aliases.yaml", "    fornecedor: openai", "    fornecedor: cohere")
        with self.assertRaises(llm_config.AliasesInvalidos) as apanhado:
            llm_config.ler(self.raiz)
        self.assertIn("subprocessadores", str(apanhado.exception))

    def test_um_declarada_sem_credor_e_recusado(self) -> None:
        self._reescrever("llm/aliases.yaml", "    credor: KAM-040\n    razao:", "    razao:")
        with self.assertRaises(llm_config.AliasesInvalidos) as apanhado:
            llm_config.ler(self.raiz)
        self.assertIn("credor", str(apanhado.exception))

    def test_um_papel_fora_da_lista_e_recusado(self) -> None:
        self._reescrever("llm/aliases.yaml", "    papel: router", "    papel: encaminhador")
        with self.assertRaises(llm_config.AliasesInvalidos):
            llm_config.ler(self.raiz)

    def test_duas_linhas_com_a_mesma_ordem_sao_recusadas(self) -> None:
        self._reescrever("llm/aliases.yaml", "    ordem: 2", "    ordem: 1")
        with self.assertRaises(llm_config.AliasesInvalidos) as apanhado:
            llm_config.ler(self.raiz)
        self.assertIn("ordem", str(apanhado.exception))


class TestAConfiguracaoGerada(_ComCopia):
    """O que o proxy vai ler. Os numeros do criterio 3, e o *fallback* medido."""

    def setUp(self) -> None:
        super().setUp()
        self.config = self._texto(llm_config.CONFIG)

    def test_os_tres_router_settings(self) -> None:
        for linha in ("num_retries: 1", "allowed_fails: 3", "cooldown_time: 30"):
            with self.subTest(linha=linha):
                self.assertIn(linha, self.config)

    def test_os_dois_tectos(self) -> None:
        self.assertIn("timeout: 8", self.config)
        self.assertIn("timeout: 20", self.config)

    def test_o_fallback_e_entre_grupos_distintos(self) -> None:
        """Medido: um grupo so, com `simple-shuffle`, falhou 3 de 20 corridas.

        Ver `docs/evidencia/KAM-030-litellm.md` §4. Um `fallbacks` que apontasse
        um grupo a si mesmo era decoracao.
        """
        self.assertIn("- kamba-chat: [kamba-chat-fallback2]", self.config)
        self.assertNotIn("- kamba-chat: [kamba-chat]", self.config)
        self.assertIn("model_name: kamba-chat-fallback2", self.config)

    def test_o_google_vai_como_gemini(self) -> None:
        """Medido: `google/` da `BadRequestError` na versao fixada."""
        self.assertIn("model: gemini/", self.config)
        self.assertNotIn("model: google/", self.config)

    def test_nenhum_segredo_na_config(self) -> None:
        """So nomes de variavel; o valor vive no cofre (KAM-010)."""
        self.assertIn("api_key: os.environ/", self.config)
        self.assertIn("master_key: os.environ/", self.config)
        for suspeito in ("sk-", "Bearer ", "password"):
            self.assertNotIn(suspeito, self.config)

    def test_o_nome_da_chave_e_do_inventario(self) -> None:
        """`llm_provider_key/<provedor>`, como `ops/secrets-inventory.yaml` diz."""
        self.assertIn("os.environ/KAMBA_SECRET_LLM_PROVIDER_KEY__anthropic", self.config)
        self.assertIn("os.environ/KAMBA_SECRET_LITELLM_MASTER_KEY", self.config)

    def test_o_registo_de_mensagens_fica_desligado(self) -> None:
        self.assertIn("turn_off_message_logging: true", self.config)

    def test_e_determinista(self) -> None:
        """Duas geracoes dao o mesmo texto, senao o *lock* nunca assentava."""
        primeiro = self._texto(llm_config.CONFIG)
        self._escrever_calado()
        self.assertEqual(primeiro, self._texto(llm_config.CONFIG))

    def test_cada_alias_tem_uma_entrada_com_o_seu_nome(self) -> None:
        for alias in ("kamba-router", "kamba-chat", "kamba-vision", "kamba-embed"):
            with self.subTest(alias=alias):
                self.assertIn(f"model_name: {alias}\n", self.config)


if __name__ == "__main__":
    unittest.main()
