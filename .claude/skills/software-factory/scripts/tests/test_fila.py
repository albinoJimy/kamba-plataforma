"""A fila num repositorio de *fixture*: o lote de 2026-11-08 em miniatura.

Tres ramos sobre uma `main` com a cadeia em 0002 e o dicionario em 1.2:

```text
A   revisao 0003 + emenda 1.3 + uma seccao        pronto: funde primeiro, fica com tudo
C   emenda 1.3 + duas seccoes                      pronto: passa a frente do B, toma 1.4
                                                   e e quem sobe o piso
B   revisao 0003 + emenda 1.3, cabecalho em 1.2   por integrar: vai para o fim, toma
                                                   0004 e 1.5
```

O C passa a frente do B **porque esta pronto e o B nao**: a ordem da fila e o
estado, nao o numero do PR (o #158 abriu antes do #159 e renumerou).

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
from test_superficies import documento, revisao  # noqa: E402

DIC = sup.DICIONARIO


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
        escrever("db/migrations/versions/0001_a.py", revisao("0001", None))
        escrever("db/migrations/versions/0002_b.py", revisao("0002", "0001"))
        escrever(DIC, documento("1.2", ["1.1", "1.2"]))
        escrever("piso.txt", "10 5\n")
        cls.main = cls.commit("base")
        cls.a = cls.ramo("a", {
            "db/migrations/versions/0003_a.py": revisao("0003", "0002"),
            DIC: documento("1.3", ["1.1", "1.2", "1.3"]),
            "piso.txt": "11 5\n"})
        cls.b = cls.ramo("b", {
            "db/migrations/versions/0003_b.py": revisao("0003", "0002"),
            DIC: documento("1.2", ["1.1", "1.2", "1.3"])})
        cls.c = cls.ramo("c", {
            DIC: documento("1.3", ["1.1", "1.2", "1.3"]),
            "piso.txt": "12 6\n"})

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
    def ramo(cls, nome: str, ficheiros: dict[str, str]) -> str:
        git("checkout", "-q", "-b", nome, cls.main)
        for caminho, texto in ficheiros.items():
            escrever(caminho, texto)
        sha = cls.commit(nome)
        git("checkout", "-q", "main")
        return sha

    def montar(self, *prs: tuple[int, str]) -> list[fila.Avaliacao]:
        return fila.montar([fila.PR(n, f"feat(KAM-{n:03d}): x", sha) for n, sha in prs],
                           self.main, medir_pelo_ficheiro)


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

    def test_o_piso_sobe_no_pr_que_cruza_a_fronteira(self) -> None:
        a, c, _ = self.montar((1, self.a), (2, self.b), (3, self.c))
        # main 10 medidos piso 5; A +1 = 11 (exige 5); C +2 = 13 (exige 6)
        self.assertIn("fica em 5", juntas(a))
        self.assertIn("sobe para 6", juntas(c))

    def test_um_pronto_passa_a_frente_de_um_numero_mais_baixo(self) -> None:
        primeiro, segundo = self.montar((1, self.b), (2, self.a))
        self.assertEqual((primeiro.pr.numero, segundo.pr.numero), (2, 1))
        self.assertIn("0003_b.py` -> `0004`", juntas(segundo))

    def test_o_relatorio_diz_qual_fundir(self) -> None:
        relatorio = fila.relatorio(self.montar((1, self.a), (2, self.b)), self.main)
        self.assertIn("FUNDIR AGORA: #1", relatorio)
        self.assertIn("ao integrar (depois de #1)", relatorio)

    def test_sem_nada_pronto_nao_manda_fundir(self) -> None:
        self.assertIn("FUNDIR AGORA: nenhum", fila.relatorio(self.montar((2, self.b)), self.main))

    def test_conflito_num_gerado_diz_para_regenerar(self) -> None:
        av = fila.Avaliacao(fila.PR(9, "x", self.a), None, [], {}, 0)
        av.conflitos = ["canon/dicionario.yaml"]
        self.assertIn("regenera", fila.relatorio([av], self.main))

    def test_fundir_recusa_reproducoes_e_cabecas_por_fechar(self) -> None:
        (b,) = self.montar((2, self.b))
        self.assertEqual(fila.fundir_cabeca([b]), 1)
        (a,) = self.montar((1, self.a))
        self.assertEqual(fila.fundir_cabeca([a]), 1)   # REPLAY nunca funde


if __name__ == "__main__":
    unittest.main()
