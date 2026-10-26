"""Os aliases do servico, e a **paridade** com o `tools/llm_config` (KAM-030).

O `kamba_agr/llm/aliases.py` duplica quatro superficies do `tools/llm_config` —
os papeis, os fornecedores aprovados, o mapa de prefixos e a regra do nome do
grupo — porque o servico **nao pode importar de `tools/`**: aquele nao e um
pacote instalado e a imagem do AGR nao o leva.

E a mesma situacao do `db/ligacao.py`, e a resposta e a mesma: **o que impede as
duas copias de divergirem e uma maquina.** E esta. O `TestParidadeComOLlmConfig`
carrega o `tools/llm_config` pelo caminho e compara as quatro, uma a uma. Sem
este ficheiro, aquela duplicacao era um defeito a espera de acontecer.

**A regra do nome do grupo compara-se com varios argumentos e nao com um:** duas
funcoes que concordam em `(x, 1)` podem discordar em `(x, 3)`, e e precisamente
a ordem >= 2 que decide para onde o *fallback* vai.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

from kamba_agr.llm import aliases as servico
from kamba_agr.llm import destinos


def _raiz() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _llm_config():
    """O `tools/llm_config`, carregado **pelo caminho**."""
    raiz = _raiz()
    ferramentas = str(raiz / "tools")
    if ferramentas not in sys.path:
        sys.path.insert(0, ferramentas)
    spec = importlib.util.spec_from_file_location(
        "llm_config_para_paridade", raiz / "tools" / "llm_config" / "__init__.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestParidadeComOLlmConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.ferramenta = _llm_config()

    def test_os_papeis(self) -> None:
        self.assertEqual(servico.PAPEIS, self.ferramenta.PAPEIS)

    def test_os_fornecedores_aprovados(self) -> None:
        self.assertEqual(
            servico.FORNECEDORES_APROVADOS, self.ferramenta.FORNECEDORES_APROVADOS
        )

    def test_o_mapa_de_prefixos(self) -> None:
        self.assertEqual(servico.PREFIXO_LITELLM, self.ferramenta.PREFIXO_LITELLM)

    def test_todo_o_fornecedor_aprovado_tem_prefixo(self) -> None:
        """Um sem prefixo gera uma configuracao que o proxy recusa no arranque."""
        for fornecedor in servico.FORNECEDORES_APROVADOS:
            with self.subTest(fornecedor=fornecedor):
                self.assertIn(fornecedor, servico.PREFIXO_LITELLM)

    def test_o_nome_do_grupo_com_varias_ordens(self) -> None:
        for alias in ("kamba-chat", "kamba-router", "x"):
            for ordem in (1, 2, 3, 9):
                with self.subTest(alias=alias, ordem=ordem):
                    self.assertEqual(
                        servico.nome_do_grupo(alias, ordem),
                        self.ferramenta.nome_do_grupo(alias, ordem),
                    )

    def test_a_ordem_1_e_o_proprio_alias(self) -> None:
        """E o nome que o cliente chama; se mudar, nenhuma chamada resolve."""
        self.assertEqual(servico.nome_do_grupo("kamba-chat", 1), "kamba-chat")
        self.assertNotEqual(servico.nome_do_grupo("kamba-chat", 2), "kamba-chat")


class TestLerOFicheiroReal(unittest.TestCase):
    """O `llm/aliases.yaml` do repositorio, lido pelo servico."""

    def setUp(self) -> None:
        self.aliases = servico.ler(_raiz() / "llm")

    def test_os_quatro_papeis(self) -> None:
        self.assertEqual(sorted(self.aliases), sorted(servico.PAPEIS))

    def test_os_tectos_do_131(self) -> None:
        """Criterio 3: `timeout` 8 s no router e 20 s no chat."""
        self.assertEqual(self.aliases["router"].timeout, 8)
        self.assertEqual(self.aliases["chat"].timeout, 20)

    def test_o_chat_tem_dois_fornecedores(self) -> None:
        """Criterio 3: «`kamba-chat` (este com 2 fornecedores)»."""
        self.assertEqual(len(self.aliases["chat"].fornecedores), 2)
        self.assertEqual(len(set(self.aliases["chat"].fornecedores)), 2)

    def test_os_nomes_dos_aliases(self) -> None:
        self.assertEqual(self.aliases["router"].nome, "kamba-router")
        self.assertEqual(self.aliases["chat"].nome, "kamba-chat")
        self.assertEqual(self.aliases["vision"].nome, "kamba-vision")
        self.assertEqual(self.aliases["embed"].nome, "kamba-embed")

    def test_todos_os_fornecedores_estao_aprovados(self) -> None:
        for papel, alias in self.aliases.items():
            with self.subTest(papel=papel):
                for fornecedor in alias.fornecedores:
                    self.assertIn(fornecedor, servico.FORNECEDORES_APROVADOS)

    def test_nenhum_modelo_esta_escolhido(self) -> None:
        """Hoje e `por_decidir` em todas as linhas: a escolha e do KAM-040.

        Este teste **ha de falhar** quando o KAM-040 escolher, e e isso que se
        quer: a escolha de um modelo e um *release* e passa por aqui.
        """
        for papel, alias in self.aliases.items():
            with self.subTest(papel=papel):
                self.assertEqual(set(alias.modelos), {"por_decidir"})


class TestOLeitorFalhaFechado(unittest.TestCase):
    def test_um_fornecedor_fora_do_inventario_levanta(self) -> None:
        """Um destino que ninguem registou (ADR-008) nao passa do arranque."""
        pasta = self._pasta_com(
            """version: 1
versao: "1.0.0"
router_settings:
  num_retries: 1
aliases:
  - nome: kamba-router
    papel: router
    timeout: 8
    estado: declarada
    credor: KAM-040
fornecedores:
  - alias: kamba-router
    ordem: 1
    fornecedor: fornecedor_nao_aprovado
    modelo: por_decidir
    credor: KAM-040
"""
        )
        with self.assertRaises(servico.AliasesIndisponiveis) as apanhado:
            servico.ler(pasta)
        self.assertIn("inventario de subprocessadores", str(apanhado.exception))

    def test_um_papel_em_falta_levanta(self) -> None:
        pasta = self._pasta_com(
            """version: 1
versao: "1.0.0"
router_settings:
  num_retries: 1
aliases:
  - nome: kamba-router
    papel: router
    timeout: 8
    estado: declarada
    credor: KAM-040
fornecedores:
  - alias: kamba-router
    ordem: 1
    fornecedor: anthropic
    modelo: por_decidir
    credor: KAM-040
"""
        )
        with self.assertRaises(servico.AliasesIndisponiveis) as apanhado:
            servico.ler(pasta)
        self.assertIn("sem alias", str(apanhado.exception))

    def test_um_ficheiro_que_nao_existe_levanta(self) -> None:
        with self.assertRaises(servico.AliasesIndisponiveis):
            servico.ler(pathlib.Path("nao_existe_nenhuma_pasta_assim"))

    def _pasta_com(self, conteudo: str) -> pathlib.Path:
        import tempfile

        pasta = pathlib.Path(tempfile.mkdtemp())
        (pasta / servico.FICHEIRO).write_bytes(conteudo.encode("utf-8"))
        self.addCleanup(lambda: None)
        return pasta


class TestOGateDeDestinoPorSi(unittest.TestCase):
    """O *gate* sozinho, sem o cliente. Criterio 8 e a decisao do KAM-069."""

    def test_prod_nega_todos_os_fornecedores(self) -> None:
        porta = destinos.arrancar(destinos.AMBIENTE_PROD)
        for fornecedor in servico.FORNECEDORES_APROVADOS:
            with self.subTest(fornecedor=fornecedor):
                with self.assertRaises(destinos.DestinoNegado):
                    porta.autorizar("t", fornecedor, destinos.FINALIDADE_CONVERSA)

    def test_staging_e_dev_autorizam(self) -> None:
        for ambiente in (destinos.AMBIENTE_STAGING, destinos.AMBIENTE_DEV):
            with self.subTest(ambiente=ambiente):
                destinos.arrancar(ambiente).autorizar(
                    "t", "anthropic", destinos.FINALIDADE_CONVERSA
                )

    def test_um_ambiente_desconhecido_e_prod(self) -> None:
        """Um `KAMBA_ENV` escrito por engano nao pode servir a politica de dev."""
        for ambiente in ("producao", "PROD", "", "qa"):
            with self.subTest(ambiente=ambiente):
                with self.assertRaises(destinos.DestinoNegado):
                    destinos.arrancar(ambiente).autorizar(
                        "t", "anthropic", destinos.FINALIDADE_CONVERSA
                    )

    def test_uma_finalidade_fora_da_lista_nega_mesmo_em_staging(self) -> None:
        """Sem linha de `tenant_destinations` onde caiba, nao se autoriza."""
        porta = destinos.arrancar(destinos.AMBIENTE_STAGING)
        with self.assertRaises(destinos.DestinoNegado):
            porta.autorizar("t", "anthropic", "finalidade_inventada")

    def test_cada_papel_tem_finalidade(self) -> None:
        for papel in servico.PAPEIS:
            with self.subTest(papel=papel):
                self.assertIn(destinos.finalidade_de(papel), destinos.FINALIDADES)

    def test_um_papel_sem_finalidade_levanta(self) -> None:
        with self.assertRaises(destinos.DestinoNegado):
            destinos.finalidade_de("papel_inventado")

    def test_a_porta_cumpre_o_protocolo(self) -> None:
        self.assertIsInstance(
            destinos.arrancar(destinos.AMBIENTE_PROD), destinos.PortaDeDestinos
        )


if __name__ == "__main__":
    unittest.main()
