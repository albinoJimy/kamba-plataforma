"""O gate 3 ponta a ponta: conjuntos canonicos, excepcoes e veredicto.

Inclui os tres casos que o ticket nomeia nos Testes Requeridos: «`lint_refs`
(referencias validas, `KAM-999`, `ADR-020`, `D13`)». Note-se que `ADR-020` e
`D13` sao os **ultimos validos** de cada serie — testes de limite superior, nao
de inexistencia.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lint_refs.cli import Excepcoes, verificar
from lint_refs.sets import FonteCanonicaAusente, ler

ROOT = Path(__file__).resolve().parents[3]


class TestConjuntosCanonicos(unittest.TestCase):
    def setUp(self) -> None:
        self.conjuntos = ler(ROOT)

    def test_kam_cobre_o_backlog_inteiro_sem_buracos(self) -> None:
        numeros = sorted(int(x[4:]) for x in self.conjuntos.kam)
        self.assertEqual(numeros[0], 1)
        self.assertEqual(
            numeros, list(range(1, numeros[-1] + 1)), "o backlog nao tem buracos"
        )

    def test_adr_tem_os_vinte_canonicos(self) -> None:
        numeros = sorted(int(x[4:]) for x in self.conjuntos.adr)
        self.assertEqual(numeros, list(range(1, 21)), "ADR-001 a ADR-020")

    def test_d_tem_as_treze(self) -> None:
        numeros = sorted(int(x[1:]) for x in self.conjuntos.d)
        self.assertEqual(numeros, list(range(1, 14)), "D1 a D13")

    def test_os_limites_superiores_sao_validos(self) -> None:
        """Os casos que o ticket nomeia: `ADR-020` e `D13` existem."""
        self.assertTrue(self.conjuntos.contem("ADR", "ADR-020"))
        self.assertTrue(self.conjuntos.contem("D", "D13"))

    def test_o_que_passa_do_limite_nao_e_valido(self) -> None:
        self.assertFalse(self.conjuntos.contem("ADR", "ADR-021"))
        self.assertFalse(self.conjuntos.contem("D", "D14"))

    def test_kam_999_nao_e_valido(self) -> None:
        """O caso que o ticket nomeia."""
        self.assertFalse(self.conjuntos.contem("KAM", "KAM-999"))

    def test_as_origens_apontam_para_as_fontes_canonicas(self) -> None:
        self.assertEqual(self.conjuntos.origens["KAM"], "specs/INDICE.md §4")
        self.assertIn("00_Arquitectura_Solucao.md §8", self.conjuntos.origens["ADR"])
        self.assertIn("§13.3", self.conjuntos.origens["D"])


class TestFonteEmFalta(unittest.TestCase):
    """Uma fonte canonica ausente nao pode degradar para conjunto vazio.

    Um conjunto vazio faria o gate reprovar **todas** as referencias — e, se
    alguem invertesse a logica um dia, aprovar todas.
    """

    def test_sem_backlog_levanta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FonteCanonicaAusente):
                ler(Path(tmp))

    def test_backlog_sem_linhas_levanta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "specs").mkdir()
            (raiz / "docs" / "tecnica").mkdir(parents=True)
            (raiz / "specs" / "INDICE.md").write_text(
                "## 4. Backlog mestre\n\nsem tabela\n\n## 5. Fim\n", encoding="utf-8"
            )
            shutil.copy(
                ROOT / "docs" / "tecnica" / "00_Arquitectura_Solucao.md",
                raiz / "docs" / "tecnica" / "00_Arquitectura_Solucao.md",
            )
            with self.assertRaises(FonteCanonicaAusente):
                ler(raiz)


class TestExcepcoes(unittest.TestCase):
    def setUp(self) -> None:
        self.excepcoes = Excepcoes.ler(ROOT)

    def test_os_placeholders_valem_em_qualquer_ficheiro(self) -> None:
        for token in ("KAM-NNN", "ADR-NNN", "D#"):
            with self.subTest(token=token):
                self.assertTrue(self.excepcoes.permite("qualquer/ficheiro.md", token))

    def test_a_excepcao_do_kam_999_e_so_no_ficheiro_do_ticket(self) -> None:
        """Esta e a excepcao que impede o ticket de reprovar o seu proprio gate.

        O ficheiro e o do KAM-002 em `specs/tickets/`: o KAM-155 tirou os blocos
        de ticket do `specs/EPIC-01_Fundacoes_Dados.md`, que ficou indice, e a
        excepcao seguiu o bloco. O epic deixou de a ter, e e isso que a segunda
        assercao fixa — senao a excepcao passava a cobrir um ficheiro onde o
        token nao aparece.
        """
        self.assertTrue(self.excepcoes.permite("specs/tickets/KAM-002.md", "KAM-999"))
        self.assertFalse(
            self.excepcoes.permite("specs/EPIC-01_Fundacoes_Dados.md", "KAM-999")
        )

    def test_uma_excepcao_nao_vale_noutro_ficheiro(self) -> None:
        self.assertFalse(self.excepcoes.permite("specs/EPIC-02_Canais_WhatsApp_Handoff.md", "ADR-021"))
        self.assertTrue(self.excepcoes.permite("docs/adr/README.md", "ADR-021"))

    def test_excepcao_sem_razao_e_recusada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "refs-allow.yaml").write_text(
                "version: 1\nexcepcoes:\n  - ficheiro: a.md\n    token: KAM-999\n",
                encoding="utf-8",
            )
            with self.assertRaises(FonteCanonicaAusente):
                Excepcoes.ler(raiz)

    def test_excepcao_com_razao_curta_e_recusada(self) -> None:
        """Uma razao de tres palavras nao sobrevive a saida do autor."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "refs-allow.yaml").write_text(
                "version: 1\nexcepcoes:\n  - ficheiro: a.md\n    token: KAM-999\n"
                "    razao: porque sim\n",
                encoding="utf-8",
            )
            with self.assertRaises(FonteCanonicaAusente) as capturado:
                Excepcoes.ler(raiz)
            self.assertIn("demasiado curta", str(capturado.exception))


class TestRepositorio(unittest.TestCase):
    def test_o_repositorio_passa_o_gate_3(self) -> None:
        achados, _ = verificar(ROOT)
        self.assertEqual(achados, [], "\n".join(achados))

    def test_varre_uma_quantidade_plausivel(self) -> None:
        """Se o varrimento encolher de repente, alguem quebrou a descoberta."""
        _, estatisticas = verificar(ROOT)
        self.assertGreater(estatisticas["ficheiros"], 100)
        self.assertGreater(estatisticas["ocorrencias"], 3000)
        for serie in ("KAM", "ADR", "D"):
            self.assertGreater(estatisticas["por_serie"][serie], 100, serie)

    def test_os_avisos_sao_so_prazos(self) -> None:
        """Os `D#` avisados estao fora do canon e **estao escritos no ficheiro**.

        A primeira versao deste teste fixava o conjunto `{D0, D30, D60}`, e
        isso era frageis por duas razoes. Quebrava quando a documentacao
        passou a citar `D14` e `D29` a falar do problema (`docs/ci.md`, gate 3)
        — uma citacao legitima, nao uma referencia. E nao verificava a
        propriedade que importa.

        O que importa e **nenhum token avisado ter sido inventado por
        expansao**: `Prazos D0-D30` nao pode produzir `D14`. Verifica-se lendo
        a linha de origem e exigindo que o token esteja la por extenso, o que
        distingue os dois casos sem congelar nenhuma lista.
        """
        _, estatisticas = verificar(ROOT)
        self.assertTrue(estatisticas["avisos"], "os prazos do canon nao desapareceram")

        for aviso in estatisticas["avisos"]:
            # Forma: "caminho:linha: TOKEN esta fora de D1-D13; ..."
            localizacao, resto = aviso.split(": ", 1)
            token = resto.split(" ")[0]
            caminho, numero = localizacao.rsplit(":", 1)
            with self.subTest(aviso=localizacao):
                self.assertFalse(
                    token[1:].isdigit() and 1 <= int(token[1:]) <= 13,
                    f"{token} esta dentro do canon e nao devia ser aviso",
                )
                linha = (ROOT / caminho).read_text(encoding="utf-8").splitlines()[
                    int(numero) - 1
                ]
                self.assertIn(
                    token,
                    linha,
                    f"{token} nao esta escrito em {localizacao}: o scanner "
                    "voltou a expandir intervalos de prazos",
                )

    def test_a_area_de_implementacao_nao_se_estende_ao_canon(self) -> None:
        """A dispensa e para quem fala de referencias, nao para o canon.

        Se `specs/**` ou `docs/**` entrassem nas areas, o gate deixava de
        proteger exactamente o que existe para proteger.
        """
        excepcoes = Excepcoes.ler(ROOT)
        for caminho in (
            "specs/INDICE.md",
            "specs/EPIC-02_Canais_WhatsApp_Handoff.md",
            "docs/tecnica/00_Arquitectura_Solucao.md",
            "docs/adr/ADR-L001-toolchain.md",
            "README.md",
        ):
            with self.subTest(ficheiro=caminho):
                self.assertFalse(
                    excepcoes.permite(caminho, "KAM-999"),
                    f"{caminho} nao pode estar dispensado",
                )

    def test_a_area_de_implementacao_cobre_o_gate_3(self) -> None:
        excepcoes = Excepcoes.ler(ROOT)
        for caminho in (
            "ci/refs-allow.yaml",
            "tools/lint_refs/scan.py",
            "tools/lint_refs/tests/test_cli.py",
        ):
            with self.subTest(ficheiro=caminho):
                self.assertTrue(excepcoes.permite(caminho, "ADR-021"), caminho)

    def test_os_worktrees_nao_sao_varridos(self) -> None:
        """`.claude/worktrees/*` sao copias do repo, cada uma com o seu KAM-999."""
        resultado = subprocess.run(
            ["git", "ls-files", "-z", ".claude"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        seguidos = resultado.stdout.decode().split("\0")
        self.assertFalse(
            [f for f in seguidos if "worktrees" in f],
            "o git nao segue os worktrees, e e por isso que se usa git ls-files",
        )


if __name__ == "__main__":
    unittest.main()
