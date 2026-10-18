"""O extractor e a metade que pode errar em silencio. Logo, tem bateria."""

from __future__ import annotations

import json
import io
import contextlib
import tempfile
import unittest
from pathlib import Path

from mermaid_lint.extrair import (
    CERCA,
    Bloco,
    BlocoPorFechar,
    alvos,
    blocos_de,
    blocos_de_ficheiros,
    main,
)


def documento(*partes: str) -> str:
    return "\n".join(partes) + "\n"


def cerca(linguagem: str = "mermaid") -> str:
    return CERCA + linguagem


class TestBlocosDe(unittest.TestCase):
    def test_um_bloco_simples(self) -> None:
        texto = documento("# Titulo", "", cerca(), "flowchart TD", "  A --> B", CERCA, "", "fim")
        blocos = blocos_de(texto, "x.md")
        self.assertEqual(len(blocos), 1)
        self.assertEqual(blocos[0].linha, 3)
        self.assertEqual(blocos[0].texto, "flowchart TD\n  A --> B")

    def test_a_linha_e_a_da_cerca_de_abertura_em_base_1(self) -> None:
        """E a linha para onde um editor salta. Trocar por 0 ou pela primeira
        linha do diagrama faz a mensagem apontar para o sitio errado."""
        texto = documento(cerca(), "flowchart TD", CERCA)
        self.assertEqual(blocos_de(texto, "x.md")[0].linha, 1)

    def test_dois_blocos_no_mesmo_ficheiro(self) -> None:
        texto = documento(
            cerca(), "flowchart TD", CERCA, "prosa", cerca(), "sequenceDiagram", CERCA
        )
        blocos = blocos_de(texto, "x.md")
        self.assertEqual([b.linha for b in blocos], [1, 5])
        self.assertEqual([b.texto for b in blocos], ["flowchart TD", "sequenceDiagram"])

    def test_bloco_de_outra_linguagem_nao_conta(self) -> None:
        texto = documento(cerca("sql"), "SELECT 1", CERCA, cerca("python"), "x = 1", CERCA)
        self.assertEqual(blocos_de(texto, "x.md"), [])

    def test_um_bloco_sql_entre_dois_mermaid_nao_os_junta(self) -> None:
        """A cerca de fecho e a primeira cerca nua. Um extractor que procurasse
        a **ultima** engoliria o SQL para dentro do primeiro diagrama."""
        texto = documento(
            cerca(), "flowchart TD", CERCA, cerca("sql"), "SELECT 1", CERCA, cerca(), "pie", CERCA
        )
        blocos = blocos_de(texto, "x.md")
        self.assertEqual([b.texto for b in blocos], ["flowchart TD", "pie"])

    def test_cerca_indentada_conta(self) -> None:
        texto = documento("- item:", "  " + cerca(), "  flowchart TD", "  " + CERCA)
        self.assertEqual(len(blocos_de(texto, "x.md")), 1)

    def test_cerca_no_meio_de_uma_linha_nao_conta(self) -> None:
        """`x = \"```mermaid\"` nao abre bloco nenhum."""
        texto = documento("o texto " + cerca() + " aqui", "flowchart TD")
        self.assertEqual(blocos_de(texto, "x.md"), [])

    def test_bloco_vazio(self) -> None:
        self.assertEqual(blocos_de(documento(cerca(), CERCA), "x.md")[0].texto, "")

    def test_cerca_sem_fecho_e_erro_e_nao_silencio(self) -> None:
        texto = documento("prosa", cerca(), "flowchart TD", "mais prosa sem fecho")
        with self.assertRaises(BlocoPorFechar) as capturado:
            blocos_de(texto, "docs/x.md")
        self.assertIn("docs/x.md:2", str(capturado.exception))

    def test_o_ficheiro_vai_em_cada_bloco(self) -> None:
        blocos = blocos_de(documento(cerca(), "pie", CERCA), "docs/tecnica/00.md")
        self.assertEqual(blocos[0].ficheiro, "docs/tecnica/00.md")


class TestOQueARevisaoEncontrou(unittest.TestCase):
    """Quatro buracos achados pela revisao adversarial do KAM-140.

    Dois deles eram **falsos verdes** — a pior especie num verificador: um
    diagrama partido escrito com cerca de tis, ou com uma *info string*, passava
    o `make mermaid` sem sequer ser lido. Nenhum existe hoje no conjunto, e e
    por isso que estao aqui: a proxima pessoa que escreva um deles nao fica sem
    rede.
    """

    def test_cerca_de_tils_e_um_diagrama(self) -> None:
        """`~~~mermaid` e CommonMark valido, e o GitHub renderiza-o."""
        texto = documento("~~~mermaid", "flowchart LR", "  A --> B", "~~~")
        blocos = blocos_de(texto, "d.md")
        self.assertEqual(len(blocos), 1)
        self.assertEqual(blocos[0].texto, "flowchart LR\n  A --> B")

    def test_a_cerca_de_fecho_e_do_mesmo_caracter(self) -> None:
        """Um `~~~` nao fecha um bloco aberto com crases."""
        texto = documento(cerca(), "flowchart LR", "~~~", "  A --> B", CERCA)
        self.assertEqual(blocos_de(texto, "d.md")[0].texto, "flowchart LR\n~~~\n  A --> B")

    def test_cerca_com_info_string(self) -> None:
        """A linguagem e a primeira palavra da *info string*, nao a linha toda."""
        texto = documento(cerca() + " {id=x}", "flowchart LR", "  A --> B", CERCA)
        self.assertEqual(len(blocos_de(texto, "d.md")), 1)

    def test_outra_linguagem_com_info_string_nao_conta(self) -> None:
        self.assertEqual(blocos_de(documento(CERCA + "mermaidjs algo", "x", CERCA), "d.md"), [])

    def test_cerca_indentada_por_quatro_espacos_nao_e_cerca(self) -> None:
        """Em CommonMark, quatro espacos fazem bloco **literal**. O extractor
        inventava um diagrama a partir de texto de exemplo."""
        texto = documento("Exemplo:", "", "    " + cerca(), "    literal", "    " + CERCA)
        self.assertEqual(blocos_de(texto, "d.md"), [])

    def test_bloco_literal_nao_engole_o_diagrama_seguinte(self) -> None:
        """O pior dos quatro: o diagrama real nunca era analisado isoladamente."""
        texto = documento(
            "    " + cerca(), "    exemplo", "", cerca(), "flowchart LR", "  A --> B", CERCA
        )
        self.assertEqual([b.texto for b in blocos_de(texto, "d.md")], ["flowchart LR\n  A --> B"])

    def test_cerca_mais_longa_fecha_so_com_uma_igual_ou_maior(self) -> None:
        """Quatro crases abrem um bloco que tres nao fecham (CommonMark)."""
        texto = documento("````mermaid", "flowchart LR", CERCA, "  A --> B", "````")
        blocos = blocos_de(texto, "d.md")
        self.assertEqual(len(blocos), 1)
        self.assertIn("A --> B", blocos[0].texto)

    def test_indentacao_ate_tres_espacos_continua_a_contar(self) -> None:
        """Tres espacos sao cerca; quatro sao literal. E a fronteira exacta."""
        texto = documento("   " + cerca(), "   flowchart LR", "   " + CERCA)
        self.assertEqual(len(blocos_de(texto, "d.md")), 1)


class TestSobreFicheiros(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "docs" / "tecnica").mkdir(parents=True)

    def escrever(self, caminho: str, texto: str) -> Path:
        destino = self.raiz / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        return destino

    def test_o_caminho_vai_relativo_e_com_barras_para_a_frente(self) -> None:
        """Um relatorio que imprime o caminho absoluto nao se compara entre
        duas maquinas — e no Windows nem com ele proprio."""
        caminho = self.escrever(
            "docs/tecnica/00.md", documento(cerca(), "flowchart TD", CERCA)
        )
        blocos = blocos_de_ficheiros([caminho], self.raiz)
        self.assertEqual(blocos[0].ficheiro, "docs/tecnica/00.md")

    def test_alvos_e_determinista_e_sem_repetidos(self) -> None:
        self.escrever("docs/tecnica/01.md", "")
        self.escrever("docs/tecnica/00.md", "")
        encontrados = alvos(self.raiz, ["docs/tecnica/*.md", "docs/tecnica/0*.md"])
        self.assertEqual([c.name for c in encontrados], ["00.md", "01.md"])

    def test_cli_devolve_json_na_saida_padrao(self) -> None:
        self.escrever("docs/tecnica/00.md", documento(cerca(), "flowchart TD", CERCA))
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = main(["--root", str(self.raiz), "--padrao", "docs/tecnica/*.md"])
        self.assertEqual(codigo, 0)
        dados = json.loads(saida.getvalue())
        self.assertEqual(dados, [{"ficheiro": "docs/tecnica/00.md", "linha": 1, "texto": "flowchart TD"}])

    def test_cli_recusa_um_bloco_por_fechar_com_codigo_2(self) -> None:
        """Codigo 2 e configuracao, nao achado: o ficheiro esta malformado.
        E a mesma postura do `lint_arch` — «um ficheiro de bloqueio malformado
        nao pode parecer um repositorio limpo»."""
        self.escrever("docs/tecnica/00.md", documento(cerca(), "flowchart TD"))
        erro = io.StringIO()
        with contextlib.redirect_stderr(erro), contextlib.redirect_stdout(io.StringIO()):
            codigo = main(["--root", str(self.raiz), "--padrao", "docs/tecnica/*.md"])
        self.assertEqual(codigo, 2)
        self.assertIn("aberto e nunca fechado", erro.getvalue())

    def test_cli_listar(self) -> None:
        self.escrever("docs/tecnica/00.md", documento(cerca(), "stateDiagram-v2", CERCA))
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = main(["--root", str(self.raiz), "--padrao", "docs/tecnica/*.md", "--listar"])
        self.assertEqual(codigo, 0)
        self.assertIn("docs/tecnica/00.md:1  stateDiagram-v2", saida.getvalue())
        self.assertIn("1 bloco(s) em 1 ficheiro(s)", saida.getvalue())


class TestSobreORepositorioReal(unittest.TestCase):
    """O extractor contra o conjunto, para que uma cerca partida num documento
    apareca como teste vermelho e nao como JSON vazio."""

    raiz = Path(__file__).resolve().parents[3]

    def test_os_dois_diagramas_do_tenant_sao_encontrados(self) -> None:
        """Sao os dois que o criterio 4 do KAM-140 nomeia. Se um deles mudar de
        sitio ou de forma, este teste di-lo."""
        caminhos = alvos(self.raiz, ["docs/tecnica/00_*.md", "docs/tecnica/10_*.md"])
        blocos = blocos_de_ficheiros(caminhos, self.raiz)
        estados = [b for b in blocos if b.texto.startswith("stateDiagram-v2")]
        por_ficheiro = {b.ficheiro for b in estados}
        self.assertIn("docs/tecnica/00_Arquitectura_Solucao.md", por_ficheiro)
        self.assertIn("docs/tecnica/10_Onboarding_Governanca.md", por_ficheiro)

    def test_nenhum_documento_do_ambito_tem_cerca_por_fechar(self) -> None:
        caminhos = alvos(self.raiz, ["docs/tecnica/*.md", "docs/*.md", "specs/*.md"])
        self.assertGreater(len(caminhos), 10, "a varredura nao encontrou documentos")
        blocos_de_ficheiros(caminhos, self.raiz)  # levanta se houver cerca aberta


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
