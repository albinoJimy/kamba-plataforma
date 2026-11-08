"""A linha de comandos do inventario de subprocessadores (KAM-069).

Tres codigos de saida e tres caminhos, e a distincao entre eles e o que torna a
saida legivel num *gate*: **0** conforme, **1** divergencia, **2** inventario
invalido. E a distincao do `canon_lint`, e pela mesma razao que esse modulo
escreve — «um dicionario em falta nao pode parecer um repositorio limpo».

Cada caminho corre contra uma **arvore temporaria** com o inventario real
copiado, e nao contra a arvore do repositorio: um ensaio que escrevesse em
`docs/` deixava o repositorio alterado quando falhasse a meio, e o
`--check` do *gate* 2 passava a medir o que o ensaio escreveu.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from subprocessadores import cli, documentos
from subprocessadores.inventario import CAMINHO

RAIZ = Path(__file__).resolve().parents[3]


class Base(unittest.TestCase):
    """Uma arvore com o inventario real e sem os documentos gerados."""

    def setUp(self) -> None:
        self.temporaria = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temporaria.name)
        destino = self.raiz / CAMINHO
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RAIZ / CAMINHO, destino)
        self.addCleanup(self.temporaria.cleanup)

    def correr(self, *argumentos: str) -> tuple[int, str, str]:
        saida, erro = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erro):
            codigo = cli.main(["--root", str(self.raiz), *argumentos])
        return codigo, saida.getvalue(), erro.getvalue()


class TestEscrever(Base):
    def test_escreve_os_dois_documentos_e_sai_com_zero(self) -> None:
        codigo, saida, _ = self.correr()
        self.assertEqual(codigo, 0)
        for relativo in (documentos.CAMINHO_PUBLICO, documentos.CAMINHO_MAPA):
            with self.subTest(documento=relativo):
                self.assertTrue((self.raiz / relativo).is_file())
                self.assertIn(relativo, saida)

    def test_escrever_e_idempotente(self) -> None:
        """O `--check` depois do escrever tem de dar conforme.

        Sem isto, um gerador que escrevesse `\\r\\n` num lado e comparasse `\\n`
        no outro dava «divergente» sobre conteudo identico — e nesta maquina o
        Python traduz `\\n` ao escrever, pelo que o caso e real e nao hipotetico.
        """
        self.correr()
        codigo, saida, _ = self.correr("--check")
        self.assertEqual(codigo, 0, saida)
        self.assertIn("conforme", saida)
        self.assertIn("11 subprocessadores", saida)


class TestCheck(Base):
    def test_sem_os_documentos_sai_com_um(self) -> None:
        codigo, _, erro = self.correr("--check")
        self.assertEqual(codigo, 1)
        self.assertIn("nao existe", erro)
        self.assertIn("python -m subprocessadores", erro)

    def test_um_documento_editado_a_mao_sai_com_um(self) -> None:
        """O caso que o *gate* 2 existe para apanhar.

        A lista publica e um compromisso com titulares de dados: editada a mao,
        passa a nomear um subprocessador que o inventario nao tem.
        """
        self.correr()
        caminho = self.raiz / documentos.CAMINHO_PUBLICO
        caminho.write_text(
            caminho.read_text(encoding="utf-8").replace("Doppler", "Outro Qualquer"),
            encoding="utf-8",
        )
        codigo, _, erro = self.correr("--check")
        self.assertEqual(codigo, 1)
        self.assertIn(documentos.CAMINHO_PUBLICO, erro)

    def test_o_check_nao_escreve(self) -> None:
        """Um `--check` que escrevesse tornava-se sempre verde."""
        codigo, _, _ = self.correr("--check")
        self.assertEqual(codigo, 1)
        self.assertFalse((self.raiz / documentos.CAMINHO_PUBLICO).exists())


class TestVersao(Base):
    def test_imprime_a_versao_e_nada_mais(self) -> None:
        """O `--versao` existe para o *gate* de go-live (criterio 8).

        Quem activa um tenant tem de poder obter a referencia do mapa sem abrir
        o documento e copiar a mao.
        """
        codigo, saida, _ = self.correr("--versao")
        self.assertEqual(codigo, 0)
        self.assertRegex(saida.strip(), r"^[0-9]+\.[0-9]+\+[0-9a-f]{12}$")
        self.assertFalse((self.raiz / documentos.CAMINHO_PUBLICO).exists())


class TestInventarioInvalido(unittest.TestCase):
    def test_sai_com_dois_e_nao_com_um(self) -> None:
        """A distincao importa: **2** e «nao se conseguiu ler», **1** e «divergiu».

        Um inventario que nao se le a sair com 1 lia-se como um documento por
        regenerar, e o remedio obvio — correr o gerador — nao resolvia nada.
        """
        with tempfile.TemporaryDirectory() as nome:
            raiz = Path(nome)
            (raiz / CAMINHO).parent.mkdir(parents=True, exist_ok=True)
            (raiz / CAMINHO).write_text(
                "version: 1\nversao: \"1.0\"\nsubprocessadores:\n  - nome: so_um\n",
                encoding="utf-8",
            )
            saida, erro = io.StringIO(), io.StringIO()
            with redirect_stdout(saida), redirect_stderr(erro):
                codigo = cli.main(["--root", str(raiz)])
            self.assertEqual(codigo, 2)
            self.assertIn("inventario invalido", erro.getvalue())

    def test_sem_ficheiro_nenhum_tambem_sai_com_dois(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            erro = io.StringIO()
            with redirect_stderr(erro), redirect_stdout(io.StringIO()):
                codigo = cli.main(["--root", nome])
            self.assertEqual(codigo, 2)


if __name__ == "__main__":
    unittest.main()
