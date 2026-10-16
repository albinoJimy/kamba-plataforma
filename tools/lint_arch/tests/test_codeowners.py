"""Os caminhos do `CODEOWNERS` resolvem contra a arvore (KAM-154).

Uma *fixture* por caso, em `fixtures/codeowners/`: cada uma e uma arvore
independente com o seu `CODEOWNERS`, varrida do disco. **O repositorio real
entra como caso proprio** — e e o unico que exercita o `git ls-files`, porque
uma *fixture* nao e um repositorio git (e um directorio vazio nao sobreviveria a
um *commit*: o git nao segue directorios).

A divisao entre `verificar(texto, caminhos)` e `ficheiros_do_git(raiz)` existe
para isto: a semantica de *glob* prova-se com arvores inventadas e
deterministas, e a fonte da arvore prova-se uma vez, contra o git.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from lint_arch import codeowners, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "codeowners"


def _arvore_do_disco(raiz: Path) -> list[str]:
    """Os ficheiros de uma *fixture*, em forma posix relativa a `raiz`."""
    return sorted(
        p.relative_to(raiz).as_posix() for p in raiz.rglob("*") if p.is_file()
    )


def _achados(nome: str) -> list[str]:
    raiz = FIXTURES / nome
    return codeowners.check(raiz, caminhos=_arvore_do_disco(raiz))


def _e_o_repositorio() -> bool:
    """`True` se `ROOT` for mesmo o repositorio, com git e `CODEOWNERS`.

    A prova por mutacao (`mutacoes_codeowners.py`) corre a bateria numa copia de
    `tools/` fora do repositorio: la nao ha `CODEOWNERS` na raiz nem arvore de
    git, e os dois casos que medem o ficheiro real nao tem o que medir. A
    condicao e **esta**, e nao «salta se falhar»: no repositorio as duas sao
    verdade, pelo que os casos correm sempre onde tem de correr.
    """
    if not (ROOT / "CODEOWNERS").is_file():
        return False
    return (
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


NO_REPOSITORIO = unittest.skipUnless(
    _e_o_repositorio(), "corre so no repositorio: precisa do git e do CODEOWNERS"
)


class TestFixtures(unittest.TestCase):
    """Um caso por *fixture*. Os nomes dizem o que cada uma prova."""

    def test_c1_regra_que_resolve_nao_e_acusada(self) -> None:
        self.assertEqual(_achados("c1-resolve"), [])

    def test_c2_regra_pendurada_reprova(self) -> None:
        """O defeito real, reproduzido: `/tecnica/` depois do KAM-128."""
        achados = _achados("c2-pendurada")
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("/tecnica/", achados[0])
        self.assertIn("CODEOWNERS:3", achados[0])
        # A mensagem tem de dizer o **efeito**, nao so que nao casa: foi a
        # ausencia desta frase que deixou o defeito passar por cosmetico.
        self.assertIn("sem dono", achados[0])
        self.assertIn("@kamba/plataforma", achados[0])

    def test_c3_a_estrela_resolve_sem_excepcao(self) -> None:
        """`*` casa com tudo; nao precisa de ser excepcionada."""
        self.assertEqual(_achados("c3-estrela"), [])

    def test_c4_curingas_que_casam_nao_sao_acusados(self) -> None:
        """Os tres casam com ficheiros reais e **nenhum** existe como caminho.

        E a diferenca que o ticket existe para fechar: o `[ -e ]` da medicao
        daria «pendurada» aos tres.
        """
        self.assertEqual(_achados("c4-curinga-casa"), [])

    def test_c4_o_teste_ingenuo_reprovaria_os_tres(self) -> None:
        """Prova que o caso c4 **distingue** as duas semanticas.

        Sem isto, a *fixture* c4 podia estar a passar por os padroes serem
        triviais, e nao por o resolvedor estar certo.
        """
        raiz = FIXTURES / "c4-curinga-casa"
        padroes = [
            r.padrao
            for r in codeowners.regras((raiz / "CODEOWNERS").read_text(encoding="utf-8"))
        ]
        self.assertEqual(len(padroes), 3)
        for padrao in padroes:
            with self.subTest(padrao=padrao):
                literal = padrao.lstrip("/").rstrip("/")
                self.assertFalse(
                    (raiz / literal).exists(),
                    f"{padrao} existe como caminho literal: a fixture deixou de "
                    "distinguir a semantica de glob da verificacao ingenua",
                )

    def test_c5_curingas_que_nao_casam_reprovam(self) -> None:
        achados = _achados("c5-curinga-pendurada")
        self.assertEqual(len(achados), 3, achados)
        for esperado in ("*.rst", "**/inexistente/", "/docs/*/nao-existe.md"):
            with self.subTest(padrao=esperado):
                self.assertTrue(
                    any(esperado in a for a in achados),
                    f"{esperado} nao foi acusado",
                )

    def test_c6_construcoes_nao_suportadas_reprovam_pelo_nome(self) -> None:
        """Fail-closed: nao se adivinha uma semantica que a fonte nao da."""
        achados = _achados("c6-nao-suportado")
        self.assertEqual(len(achados), 3, achados)
        texto = "\n".join(achados)
        self.assertIn("nao suporta", texto)
        for razao in ("`!` para negar", "`[ ]` para definir", "`?`"):
            with self.subTest(razao=razao):
                self.assertIn(razao, texto)

    def test_todas_as_fixtures_estao_cobertas(self) -> None:
        """Uma *fixture* nova sem teste proprio falha aqui, em vez de nao correr.

        E a licao do `test_makefile.py`: uma suite que desaparece do disco tem de
        falhar em algum sitio, nao deixar de correr calada.
        """
        no_disco = {d.name for d in FIXTURES.iterdir() if d.is_dir()}
        testadas = {
            nome.split("_")[1]
            for nome in dir(self)
            if nome.startswith("test_c")
        }
        prefixos = {d.split("-")[0] for d in no_disco}
        self.assertEqual(prefixos, testadas, f"fixtures no disco: {sorted(no_disco)}")


class TestSemantica(unittest.TestCase):
    """A traducao de padrao para expressao, caso a caso.

    Aqui a arvore e uma lista literal: e o que torna cada regra do gitignore
    verificavel sozinha, sem inventar ficheiros no disco.
    """

    ARVORE = [
        "CODEOWNERS",
        "docs/tecnica/00_Arquitectura.md",
        "docs/tecnica/evidencia/E1_Meta.md",
        "specs/00_Carta.md",
        "tools/lint_arch/structure.py",
        "x/y/logs/registo.txt",
    ]

    def _resolve(self, padrao: str) -> bool:
        ficheiros, directorios = codeowners.arvore(self.ARVORE)
        return codeowners.resolve(padrao, ficheiros, directorios)

    def test_barra_inicial_ancora_na_raiz(self) -> None:
        self.assertTrue(self._resolve("/docs/tecnica/"))
        self.assertFalse(self._resolve("/tecnica/"))

    def test_sem_barra_casa_em_qualquer_nivel(self) -> None:
        # `tecnica/` sem ancora casa com `docs/tecnica`; com ancora, nao.
        self.assertTrue(self._resolve("tecnica/"))
        self.assertFalse(self._resolve("/tecnica/"))

    def test_barra_no_meio_ancora_tambem(self) -> None:
        self.assertTrue(self._resolve("docs/tecnica/"))
        self.assertFalse(self._resolve("tecnica/evidencia/"))

    def test_estrela_nao_atravessa_barra(self) -> None:
        self.assertTrue(self._resolve("/docs/*/evidencia/"))
        self.assertFalse(self._resolve("/docs/*.md"))
        self.assertTrue(self._resolve("/docs/tecnica/*.md"))

    def test_estrela_dupla_atravessa(self) -> None:
        self.assertTrue(self._resolve("**/logs/"))
        self.assertTrue(self._resolve("**/E1_Meta.md"))
        self.assertTrue(self._resolve("/docs/**"))

    def test_estrela_dupla_vale_zero_segmentos(self) -> None:
        """`**/x` tem de casar com `x` na raiz, nao so com `a/x`."""
        self.assertTrue(self._resolve("**/CODEOWNERS"))

    def test_barra_final_exige_directorio(self) -> None:
        """Um ficheiro com o nome do directorio nao satisfaz a regra."""
        self.assertTrue(self._resolve("/specs/"))
        self.assertFalse(self._resolve("/CODEOWNERS/"))
        self.assertTrue(self._resolve("/CODEOWNERS"))

    def test_um_padrao_sem_barra_final_casa_com_directorio(self) -> None:
        self.assertTrue(self._resolve("/docs/tecnica"))

    def test_a_estrela_sozinha_casa_com_tudo(self) -> None:
        self.assertTrue(self._resolve("*"))

    def test_a_estrela_sozinha_nao_casa_numa_arvore_vazia(self) -> None:
        """E e verdade que nao atribui dono a nada: nao se excepciona."""
        ficheiros, directorios = codeowners.arvore([])
        self.assertFalse(codeowners.resolve("*", ficheiros, directorios))

    def test_um_prefixo_de_um_ficheiro_real_nao_resolve(self) -> None:
        """`/docs/tecnica/00_Arq` nao e o ficheiro, e nao atribui dono a nada.

        Sem ancora no fim da expressao, um padrao truncado — uma gralha, um
        caminho a meio de uma mudanca de nome — passava por resolvido.
        """
        self.assertTrue(self._resolve("/docs/tecnica/00_Arquitectura.md"))
        self.assertFalse(self._resolve("/docs/tecnica/00_Arq"))
        self.assertFalse(self._resolve("/docs/tec"))

    def test_e_sensivel_a_caixa(self) -> None:
        """O GitHub documenta que os caminhos sao sensiveis a caixa."""
        self.assertTrue(self._resolve("/specs/00_Carta.md"))
        self.assertFalse(self._resolve("/specs/00_carta.md"))

    def test_construcoes_nao_suportadas_levantam(self) -> None:
        for padrao in ("!/docs/", "/docs/[0-9]_x.md", "/docs/0?_x.md", "/docs/\\#x"):
            with self.subTest(padrao=padrao):
                with self.assertRaises(ValueError):
                    self._resolve(padrao)

    def test_um_directorio_sem_ficheiros_seguidos_nao_resolve(self) -> None:
        """E a diferenca entre a arvore do git e a do disco.

        O git nao segue directorios: uma pasta que existe no disco sem nada
        seguido nao atribui dono a nada, e o `[ -e ]` dava-a por boa. Nao ha
        *fixture* para este caso porque um directorio vazio nao sobrevive a um
        *commit*.
        """
        ficheiros, directorios = codeowners.arvore(["docs/tecnica/00.md"])
        self.assertTrue(codeowners.resolve("/docs/", ficheiros, directorios))
        self.assertFalse(codeowners.resolve("/vazio/", ficheiros, directorios))


class TestLeitura(unittest.TestCase):
    def test_comentarios_e_linhas_vazias_saem(self) -> None:
        texto = "# comentario\n\n   \n  # indentado\n/a/  @dono\n"
        lidas = codeowners.regras(texto)
        self.assertEqual(len(lidas), 1)
        self.assertEqual(lidas[0].padrao, "/a/")
        self.assertEqual(lidas[0].linha, 5)
        self.assertEqual(lidas[0].donos, ("@dono",))

    def test_varios_donos_na_mesma_linha(self) -> None:
        lidas = codeowners.regras("/a/  @um @dois\n")
        self.assertEqual(lidas[0].donos, ("@um", "@dois"))

    def test_uma_regra_sem_donos_ainda_e_uma_regra(self) -> None:
        """Quem pode ser dono e governacao (KAM-137, L-19), nao um caminho.

        A regra conta-se e resolve-se; a ausencia de dono nao e deste gate.
        """
        lidas = codeowners.regras("/a/\n")
        self.assertEqual(lidas[0].donos, ())

    def test_a_estrela_e_acusada_quando_nao_casa_com_nada(self) -> None:
        """`*` resolve **por casar**, nao por ser excepcionada.

        A diferenca so se ve numa arvore vazia, e e a que importa: uma
        excepcao pelo nome do padrao daria «conforme» a um `CODEOWNERS` que
        nao atribui dono a nada. Este teste e o que a torna impossivel.
        """
        achados = codeowners.verificar("*  @dono\n", [])
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("'*'", achados[0])

    def test_as_regras_vem_pela_ordem_do_ficheiro(self) -> None:
        """Em `CODEOWNERS` vence a **ultima** regra que casa."""
        lidas = codeowners.regras("/a/ @um\n/a/b/ @dois\n")
        self.assertEqual([r.padrao for r in lidas], ["/a/", "/a/b/"])


class TestRepositorio(unittest.TestCase):
    """O `CODEOWNERS` real, contra a arvore real seguida pelo git."""

    @NO_REPOSITORIO
    def test_o_codeowners_do_repositorio_esta_conforme(self) -> None:
        self.assertEqual(codeowners.check(ROOT), [])

    @NO_REPOSITORIO
    def test_a_arvore_vem_do_git_e_nao_do_disco(self) -> None:
        bruto = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        esperado = sorted(
            p for p in bruto.stdout.decode("utf-8", errors="replace").split("\0") if p
        )
        self.assertEqual(codeowners.ficheiros_do_git(ROOT), esperado)

    @NO_REPOSITORIO
    def test_as_dezoito_regras_continuam_dezoito(self) -> None:
        """Uma regra nova ou removida e uma alteracao visivel, nao silenciosa."""
        texto = (ROOT / "CODEOWNERS").read_text(encoding="utf-8")
        self.assertEqual(len(codeowners.regras(texto)), 18)

    def test_sem_git_o_gate_falha_em_vez_de_medir_o_disco(self) -> None:
        """Fail-closed: nao ha recurso a `os.walk` quando o git nao responde."""
        with self.assertRaises(OSError):
            codeowners.ficheiros_do_git(Path(__file__).resolve().parent / "nao-existe")

    def test_um_ficheiro_que_o_git_nao_segue_nao_conta(self) -> None:
        """A arvore e a **seguida pelo git**, nao a do disco.

        Num repositorio de verdade, feito aqui: um ficheiro seguido e outro por
        seguir. A regra que so casa com o segundo tem de ficar pendurada —
        senao bastava `git add` esquecido para o gate dar dono a uma area que o
        GitHub nao ve. E a razao pela qual nao se usa `--others`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            ambiente = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": str(raiz / "sem-config"),
                "GIT_CONFIG_SYSTEM": str(raiz / "sem-config"),
            }
            subprocess.run(
                ["git", "init", "-q"], cwd=raiz, check=True, env=ambiente,
                capture_output=True,
            )
            (raiz / "seguido").mkdir()
            (raiz / "seguido" / "a.md").write_text("a\n", encoding="utf-8")
            (raiz / "por-seguir").mkdir()
            (raiz / "por-seguir" / "b.md").write_text("b\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "seguido/a.md"], cwd=raiz, check=True, env=ambiente,
                capture_output=True,
            )

            self.assertEqual(codeowners.ficheiros_do_git(raiz), ["seguido/a.md"])

            (raiz / "CODEOWNERS").write_text(
                "/seguido/     @dono\n/por-seguir/  @dono\n", encoding="utf-8"
            )
            achados = codeowners.check(raiz)
            self.assertEqual(len(achados), 1, achados)
            self.assertIn("/por-seguir/", achados[0])

    def test_um_bom_no_inicio_nao_inventa_uma_regra(self) -> None:
        """Achado falso encontrado pela revisao, com reproducao.

        Com um BOM, a primeira linha deixava de comecar por `#`, passava a
        contar como regra, e o *gate* ficava vermelho a dizer que `'\\ufeff#'`
        nao casava com nada — uma mensagem que ninguem decifra.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "CODEOWNERS").write_bytes(
                "﻿# comentario\n/a/  @dono\n".encode("utf-8")
            )
            self.assertEqual(codeowners.check(raiz, caminhos=["a/x.md"]), [])

    def test_sem_codeowners_nao_se_acusa_duas_vezes(self) -> None:
        """A ausencia do ficheiro e ja acusada por `REQUIRED_FILES`."""
        self.assertEqual(codeowners.check(FIXTURES, caminhos=[]), [])


class TestLigacaoAoGate(unittest.TestCase):
    """O gate cresce dentro do `structure.check`, que ja conhecia o ficheiro."""

    def test_structure_check_acusa_uma_regra_pendurada(self) -> None:
        raiz = FIXTURES / "c2-pendurada"
        problemas = "\n".join(structure.check(raiz, caminhos=_arvore_do_disco(raiz)))
        self.assertIn("/tecnica/", problemas)
        self.assertIn("sem dono", problemas)

    def test_o_codeowners_continua_a_ser_ficheiro_obrigatorio(self) -> None:
        self.assertIn("CODEOWNERS", structure.REQUIRED_FILES)


if __name__ == "__main__":
    unittest.main()
