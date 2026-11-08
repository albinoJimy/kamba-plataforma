"""A fila num repositorio de *fixture*: o lote de 2026-11-08 em miniatura, e os
casos que a revisao adversarial do KAM-185 mostrou que a primeira versao errava.

Sobre uma `main` com a cadeia em 0002, o dicionario em 1.2, o INDICE em 1.2 (com o
cabecalho **em texto**) e o piso em `10 5`:

```text
a   revisao 0003 + dicionario 1.3 + uma seccao     pronto
c   dicionario 1.3 + tres seccoes                   pronto, passa a frente do b
d   uma seccao                                       pronto
b   revisao 0003 + dicionario 1.3, cabecalho 1.2    por integrar: vai para o fim
e   uma seccao e o piso a 5                          por integrar: 12 // 2 = 6
i1  INDICE 1.3      i2  INDICE 1.3                   os dois prontos, colidem
i3  INDICE 1.3 com o cabecalho em 1.2                por integrar
buraco   dicionario 1.4 sem 1.3                      por integrar
h   mexe na revisao 0002 sem a renumerar             nao e revisao nova
f   muda o g.txt, que a main2 tambem muda            conflito
s2  empilhado sobre s1, que a mains ja tem por squash
```

O piso vem de um `piso.txt` na arvore em vez do `lint_bloco` (que nao existe na
*fixture*): os ensaios medem a **ordem** e a **reserva**, e o `fonte.medir_piso`
mede-se a parte contra a arvore real.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fila  # noqa: E402
import fonte  # noqa: E402
import superficies as sup  # noqa: E402
from test_superficies import documento, indice, revisao  # noqa: E402

DIC = sup.DICIONARIO
IX = "specs/INDICE.md"
R = "db/migrations/versions"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def escrever(caminho: str, texto: str) -> None:
    alvo = Path(caminho)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(texto, encoding="utf-8", newline="\n")


def medir_pelo_ficheiro(ref: str) -> tuple[int, int]:
    medidos, piso = fonte.Arvore(ref).ler("piso.txt").split()
    return int(medidos), int(piso)


def piso_pelo_ficheiro(ref: str) -> int:
    return medir_pelo_ficheiro(ref)[1]


def juntas(av: fila.Avaliacao) -> str:
    return "\n".join(av.instrucoes)


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.antes = os.getcwd()
        cls.pasta = tempfile.mkdtemp(prefix="kam185-fila-")
        os.chdir(cls.pasta)
        git("init", "-q", "-b", "main")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "fixture")
        escrever(f"{R}/0001_a.py", revisao("0001", None))
        escrever(f"{R}/0002_b.py", revisao("0002", "0001"))
        escrever(DIC, documento("1.2", ["1.1", "1.2"]))
        escrever(IX, indice("1.2", ["1.1", "1.2"]))
        escrever("piso.txt", "10 5\n")
        escrever("g.txt", "base\n")
        cls.main = cls.commit("base")
        dic13 = documento("1.3", ["1.1", "1.2", "1.3"])
        cls.a = cls.ramo("a", cls.main, {f"{R}/0003_a.py": revisao("0003", "0002"),
                                         DIC: dic13, "piso.txt": "11 5\n"})
        cls.b = cls.ramo("b", cls.main, {f"{R}/0003_b.py": revisao("0003", "0002"),
                                         DIC: documento("1.2", ["1.1", "1.2", "1.3"])})
        cls.c = cls.ramo("c", cls.main, {DIC: dic13, "piso.txt": "13 6\n"})
        cls.d = cls.ramo("d", cls.main, {"piso.txt": "11 5\n"})
        cls.e = cls.ramo("e", cls.main, {"piso.txt": "12 5\n"})
        cls.i1 = cls.ramo("i1", cls.main, {IX: indice("1.3", ["1.1", "1.2", "1.3"])})
        cls.i2 = cls.ramo("i2", cls.main, {IX: indice("1.3", ["1.1", "1.2", "1.3"])})
        cls.i3 = cls.ramo("i3", cls.main, {IX: indice("1.2", ["1.1", "1.2", "1.3"])})
        cls.buraco = cls.ramo("buraco", cls.main, {DIC: documento("1.4", ["1.1", "1.2", "1.4"])})
        cls.h = cls.ramo("h", cls.main, {f"{R}/0002_b.py": revisao("0002", "0001") + "# nota\n"})
        cls.main2 = cls.ramo("main2", cls.main, {"g.txt": "main2\n"})
        cls.f = cls.ramo("f", cls.main, {"g.txt": "f\n"})
        s1_ficheiros = {f"{R}/0003_s.py": revisao("0003", "0002"), DIC: dic13}
        cls.s1 = cls.ramo("s1", cls.main, s1_ficheiros)
        cls.mains = cls.ramo("mains", cls.main, s1_ficheiros)     # o squash do s1
        cls.s2 = cls.ramo("s2", cls.s1, {f"{R}/0004_s2.py": revisao("0004", "0003"),
                                         DIC: documento("1.4", ["1.1", "1.2", "1.3", "1.4"])})

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls.antes)
        shutil.rmtree(cls.pasta, ignore_errors=True)

    @staticmethod
    def commit(mensagem: str) -> str:
        git("add", "-A")
        git("commit", "-q", "-m", mensagem)
        return git("rev-parse", "HEAD")

    @classmethod
    def ramo(cls, nome: str, de: str, ficheiros: dict[str, str]) -> str:
        git("checkout", "-q", "-b", nome, de)
        for caminho, texto in ficheiros.items():
            escrever(caminho, texto)
        sha = cls.commit(nome)
        git("checkout", "-q", "main")
        return sha

    def montar(self, *prs: tuple[int, str], main: str | None = None) -> list[fila.Avaliacao]:
        return fila.montar([fila.PR(n, f"feat(KAM-{n:03d}): x", sha) for n, sha in prs],
                           main or self.main, medir_pelo_ficheiro, piso_pelo_ficheiro)


class TestFila(Fixture):
    def test_um_ramo_coerente_sozinho_esta_pronto_e_sem_renumerar(self) -> None:
        (a,) = self.montar((1, self.a))
        self.assertEqual(a.veredicto, "PRONTO")
        self.assertEqual(a.problemas, [])
        self.assertIn("revisao 0003 fica", juntas(a))

    def test_o_cabecalho_atras_impede_o_pronto(self) -> None:
        (b,) = self.montar((2, self.b))
        self.assertEqual(b.veredicto, "INTEGRAR")
        self.assertTrue(any("cabecalho 1.2" in p for p in b.problemas), b.problemas)

    def test_os_prontos_vao_a_frente_e_quem_integra_vai_para_o_fim(self) -> None:
        fila_ = self.montar((1, self.a), (2, self.b), (3, self.c))
        self.assertEqual([av.pr.numero for av in fila_], [1, 3, 2])
        self.assertEqual([av.veredicto for av in fila_], ["PRONTO", "PRONTO", "INTEGRAR"])

    def test_quem_funde_depois_renumera_a_revisao_e_a_versao(self) -> None:
        _, _, b = self.montar((1, self.a), (2, self.b), (3, self.c))
        self.assertIn("0003_b.py` -> `0004`", juntas(b))
        self.assertIn('down_revision = "0003"', juntas(b))
        self.assertIn("1.3 -> 1.5", juntas(b))

    def test_a_reserva_impede_dois_renumerados_no_mesmo_numero(self) -> None:
        """O defeito que a reserva fecha: o KAM-070 e o KAM-184 mandados ambos para 1.69."""
        _, c, b = self.montar((1, self.a), (2, self.b), (3, self.c))
        self.assertIn("1.3 -> 1.4", juntas(c))
        self.assertIn("1.3 -> 1.5", juntas(b))

    def test_o_piso_conta_os_medidos_e_o_piso_dos_que_vao_a_frente(self) -> None:
        """main 10/5; a +1 = 11 (exige 5); c +3 = 14 (exige 7); d +1 = 15 (exige 7).

        Sem acumular os medidos, o c diria 13 e «sobe para 6»; sem guardar o piso
        da reserva, o d diria «sobe para 7» quando o c ja o subiu.
        """
        a, c, d = self.montar((1, self.a), (3, self.c), (4, self.d))
        self.assertIn("11 medidos -> fica em 5", juntas(a))
        self.assertIn("14 medidos -> sobe para 7", juntas(c))
        self.assertIn("15 medidos -> fica em 7", juntas(d))

    def test_a_emenda_do_piso_nomeia_o_literal_par(self) -> None:
        _, c = self.montar((1, self.a), (3, self.c))
        self.assertIn(sup.PAR_DO_PISO, juntas(c))

    def test_um_piso_abaixo_de_metade_na_fusao_impede_o_pronto(self) -> None:
        (e,) = self.montar((5, self.e))
        self.assertEqual(e.veredicto, "INTEGRAR")
        self.assertTrue(any("para 6" in p for p in e.problemas), e.problemas)

    def test_o_cabecalho_em_texto_do_indice_leva_a_instrucao_do_cabecalho(self) -> None:
        """Achado 1: o segundo a escrever a 1.3 do INDICE nao era mandado acertar o cabecalho."""
        i1, i2 = self.montar((6, self.i1), (7, self.i2))
        self.assertEqual((i1.veredicto, i2.veredicto), ("PRONTO", "PRONTO"))
        self.assertIn(f"`{IX}`: 1.3 -> 1.4 e o cabecalho", juntas(i2))

    def test_o_cabecalho_em_texto_atrasado_impede_o_pronto(self) -> None:
        (i3,) = self.montar((8, self.i3))
        self.assertEqual(i3.veredicto, "INTEGRAR")
        self.assertTrue(any(p.startswith(f"{IX}: cabecalho 1.2") for p in i3.problemas), i3.problemas)

    def test_um_buraco_impede_o_pronto(self) -> None:
        """Achado 2: o veredicto dizia PRONTO ao lado da instrucao «1.4 -> 1.3»."""
        (buraco,) = self.montar((9, self.buraco))
        self.assertEqual(buraco.veredicto, "INTEGRAR")
        self.assertTrue(any("falta a versao 1.3" in p for p in buraco.problemas), buraco.problemas)

    def test_mexer_numa_revisao_nao_e_acrescentar_uma(self) -> None:
        (h,) = self.montar((10, self.h))
        self.assertEqual(h.revisoes_novas, [])
        self.assertNotIn("revisao", juntas(h))

    def test_um_conflito_real_impede_o_pronto_e_e_nomeado(self) -> None:
        (f,) = self.montar((11, self.f), main=self.main2)
        self.assertEqual(f.conflitos, ["g.txt"])
        self.assertEqual(f.veredicto, "INTEGRAR")
        self.assertTrue(f.pela_base_do_ramo)

    def test_um_ramo_empilhado_nao_renumera_o_que_a_main_ja_tem(self) -> None:
        """Achado 4: o s2 nasceu do s1, e a main tem o s1 por squash."""
        (s2,) = self.montar((12, self.s2), main=self.mains)
        self.assertEqual(s2.revisoes_novas, [f"{R}/0004_s2.py"])
        self.assertEqual(s2.emendas, {DIC: ["1.4"]})
        self.assertIn("revisao 0004 fica", juntas(s2))
        self.assertNotIn("->", juntas(s2))

    def test_um_pronto_passa_a_frente_de_um_numero_mais_baixo(self) -> None:
        primeiro, segundo = self.montar((1, self.b), (2, self.a))
        self.assertEqual((primeiro.pr.numero, segundo.pr.numero), (2, 1))
        self.assertIn("0003_b.py` -> `0004`", juntas(segundo))

    def test_o_relatorio_diz_qual_fundir(self) -> None:
        relatorio = fila.relatorio(self.montar((1, self.a), (2, self.b)), self.main)
        self.assertIn("FUNDIR AGORA: #1", relatorio)
        self.assertIn("(depois de #1)", relatorio)

    def test_sem_nada_pronto_nao_manda_fundir(self) -> None:
        self.assertIn("FUNDIR AGORA: nenhum", fila.relatorio(self.montar((2, self.b)), self.main))

    def test_conflito_num_gerado_diz_para_regenerar(self) -> None:
        av = fila.Avaliacao(fila.PR(9, "x", self.a), [], {}, 0)
        av.conflitos = ["canon/dicionario.yaml"]
        self.assertIn("regenera", fila.relatorio([av], self.main))

    def test_fundir_recusa_reproducoes_e_cabecas_por_fechar(self) -> None:
        (b,) = self.montar((2, self.b))
        self.assertEqual(fila.fundir_cabeca([b], self.main), 1)
        (a,) = self.montar((1, self.a))
        self.assertEqual(fila.fundir_cabeca([a], self.main), 1)   # REPLAY nunca funde


class TestVeredicto(unittest.TestCase):
    """Achado 7: os estados do GitHub que a primeira versao nao conhecia."""

    def veredicto(self, estado: str, fundivel: str = "MERGEABLE", rascunho: bool = False,
                  vermelhas: tuple[str, ...] = (), pendentes: int = 0) -> str:
        pr = fila.PR(1, "x", "abc", estado, fundivel, rascunho,
                     {"pending": pendentes} if pendentes else {}, list(vermelhas))
        return fila.Avaliacao(pr, [], {}, 0).veredicto

    def test_unstable_limpo_e_pronto(self) -> None:
        self.assertEqual(self.veredicto("UNSTABLE"), "PRONTO")

    def test_uma_vermelha_real_nunca_e_pronto_nem_pendente(self) -> None:
        self.assertEqual(self.veredicto("UNSTABLE", vermelhas=("gate 9",)), "VERMELHO")
        self.assertEqual(self.veredicto("BLOCKED", vermelhas=("gate 2",), pendentes=2), "VERMELHO")

    def test_unknown_logo_a_seguir_a_uma_fusao_e_pendente(self) -> None:
        self.assertEqual(self.veredicto("UNKNOWN", fundivel="UNKNOWN"), "PENDENTE")

    def test_behind_pede_integrar(self) -> None:
        self.assertEqual(self.veredicto("BEHIND"), "INTEGRAR")

    def test_rascunho_nao_e_pronto(self) -> None:
        self.assertEqual(self.veredicto("CLEAN", rascunho=True), "RASCUNHO")
        self.assertEqual(self.veredicto("DRAFT"), "RASCUNHO")

    def test_bloqueado_com_e_sem_pendentes(self) -> None:
        self.assertEqual(self.veredicto("BLOCKED", pendentes=3), "PENDENTE")
        self.assertEqual(self.veredicto("BLOCKED"), "VERMELHO")

    def test_vermelho_vai_para_o_fim_da_fila(self) -> None:
        """Achado 3: um PR vermelho a frente ficava com a emenda do piso, e o seguinte
        esperava por ele para sempre."""
        vermelho = fila.Avaliacao(fila.PR(1, "x", "a", "BLOCKED", "MERGEABLE", False, {}, ["gate 2"]), [], {}, 0)
        integrar = fila.Avaliacao(fila.PR(2, "x", "b", "UNSTABLE"), [], {}, 0)
        integrar.problemas = ["piso"]
        self.assertEqual([av.pr.numero for av in fila.ordenar([vermelho, integrar])], [2, 1])


if __name__ == "__main__":
    unittest.main()
