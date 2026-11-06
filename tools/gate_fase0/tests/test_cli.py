"""Os códigos de saída, que são parte do contrato e não detalhe (KAM-108).

Três códigos, e a razão de serem três está no `cli.py`: um `traceback` por uma
entrada que falta sai indistinguível de «o traço não fechou», e as duas
conclusões são opostas. Daí estes ensaios serem sobre o **código** e não só
sobre o texto.

E há um que vale por si: `traco` sai **1** quando a cadeia tem elos em falta.
Sem isso, um `&& echo verde` no guião do operador dizia verde sobre uma cadeia
que parou no evento de pagamento — que é exactamente o estado em que o esqueleto
está hoje.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_fase0 import cli
from gate_fase0.tests.test_recolha import CORRIDA, REUSO
from gate_fase0.tests.test_traco import cadeia_limpa


def _correr(argv: list[str]) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(saida), redirect_stderr(erro):
        codigo = cli.principal(argv)
    return codigo, saida.getvalue(), erro.getvalue()


class TestOsComandosQueSoImprimem(unittest.TestCase):
    def test_cenario_sai_zero_e_imprime_a_tabela(self) -> None:
        codigo, saida, _ = _correr(["cenario"])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("| P0 |", saida)
        self.assertIn("| P7 |", saida)

    def test_consulta_sai_zero_e_imprime_as_quatro(self) -> None:
        codigo, saida, _ = _correr(["consulta"])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        for nome in ("audit_log", "events_log", "events_consumed", "bookings"):
            self.assertIn(nome, saida)

    def test_decisoes_sai_zero_com_o_manifesto_do_repositorio(self) -> None:
        codigo, saida, _ = _correr(["decisoes"])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("7 linha(s), 0 `confirmada`(s)", saida)

    def test_decisoes_com_prefixo_resolve_do_documento(self) -> None:
        codigo, saida, _ = _correr(["decisoes", "--prefixo", "../../../"])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("(../../../docs/", saida)

    def test_decisoes_com_manifesto_quebrado_sai_um(self) -> None:
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(
                b'version: 1\nlida_em: "2026-11-06"\nponta: "fe40048"\nlinhas:\n'
                b'  - id: "X1"\n    assunto: "a"\n    tickets:\n      - "KAM-108"\n'
                b'    onde: "docs/nao-existe.md"\n    seccao: "1"\n'
                b'    estado: "inconclusiva"\n    plano_ou_pivo: "p"\n'
                b'    evidencia: "e"\n    credor: "fundador"\n'
            )
            codigo, _, erro = _correr(["decisoes", "--manifesto", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ACHADOS)
        self.assertIn("não existe na árvore", erro)

    def test_decisoes_com_manifesto_ilegivel_sai_dois(self) -> None:
        """Configuração e não achado: é a distinção que o módulo existe para manter."""
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "d.yaml"
            caminho.write_bytes(b'version: 1\nchave_inventada: "x"\n')
            codigo, _, erro = _correr(["decisoes", "--manifesto", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("decisoes:", erro)


class TestOTracoPelaLinhaDeComando(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def _escrever(self, nome: str, linhas: list[dict]) -> Path:
        caminho = self.raiz / nome
        caminho.write_bytes(
            ("\n".join(json.dumps(l, ensure_ascii=False) for l in linhas) + "\n").encode(
                "utf-8"
            )
        )
        return caminho

    def test_uma_cadeia_completa_sai_zero(self) -> None:
        caminho = self._escrever("limpo.jsonl", cadeia_limpa())
        codigo, saida, _ = _correr(["traco", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("consumo", saida)

    def test_uma_cadeia_com_elos_em_falta_sai_um(self) -> None:
        caminho = self._escrever("parcial.jsonl", cadeia_limpa()[:-1])
        codigo, saida, erro = _correr(["traco", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ACHADOS)
        self.assertIn("ELOS EM FALTA", saida)
        self.assertIn("1 de 1 cadeia(s) com elos em falta", erro)

    def test_o_json_sai_com_o_resumo(self) -> None:
        caminho = self._escrever("limpo.jsonl", cadeia_limpa())
        codigo, saida, _ = _correr(["traco", "--json", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertEqual(json.loads(saida)["resumo"]["completas"], 1)

    def test_uma_entrada_que_nao_existe_sai_dois(self) -> None:
        codigo, _, erro = _correr(["traco", str(self.raiz / "nada.jsonl")])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("não existe", erro)

    def test_uma_entrada_com_um_elo_mal_formado_sai_dois(self) -> None:
        """Entrada inválida é 2; cadeia incompleta é 1. Nunca o mesmo código."""
        caminho = self._escrever(
            "mau.jsonl", [{"tenant_id": "nao-e-um-uuid", "msg_id": "x"}]
        )
        codigo, _, erro = _correr(["traco", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("traco:", erro)

    def test_um_ficheiro_vazio_sai_um_e_nao_zero(self) -> None:
        """Zero cadeias não é «a cadeia fechou». Era o buraco mais fácil aqui."""
        caminho = self.raiz / "vazio.jsonl"
        caminho.write_bytes(b"")
        codigo, _, erro = _correr(["traco", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ACHADOS)
        self.assertIn("0 de 0", erro)


class TestARecolhaPelaLinhaDeComando(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = TemporaryDirectory()
        self.raiz = Path(self.pasta.name)
        self.addCleanup(self.pasta.cleanup)

    def _json(self, nome: str, documento: object) -> Path:
        caminho = self.raiz / nome
        caminho.write_bytes(json.dumps(documento, ensure_ascii=False).encode("utf-8"))
        return caminho

    def test_ci_sai_zero_quando_nenhum_vermelho_bloqueia(self) -> None:
        """O gate 5 está vermelho e **não bloqueia**: o código de saída é 0.

        É a decisão que mais se pode ler mal. Um 1 aqui punha o operador a
        tratar uma reserva declarada como um gate avariado, todos os dias.
        """
        caminho = self._json("corrida.json", CORRIDA)
        codigo, saida, _ = _correr(["ci", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("vermelho (failure)", saida)

    def test_ci_sai_um_quando_um_gate_que_bloqueia_falha(self) -> None:
        falha = json.loads(json.dumps(CORRIDA))
        falha["jobs"][0]["conclusion"] = "failure"
        caminho = self._json("falha.json", falha)
        codigo, _, _ = _correr(["ci", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ACHADOS)

    def test_ci_sem_ficheiro_sai_dois(self) -> None:
        codigo, _, erro = _correr(["ci", str(self.raiz / "nada.json")])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("não existe", erro)

    def test_ci_com_ficheiro_sem_jobs_sai_dois(self) -> None:
        caminho = self._json("vazio.json", {"headSha": "abc"})
        codigo, _, erro = _correr(["ci", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("jobs", erro)

    def test_reuso_sai_zero_acima_do_limiar(self) -> None:
        caminho = self._json("reuso.json", REUSO)
        codigo, saida, _ = _correr(["reuso", str(caminho), "--ponta", "fe40048"])
        self.assertEqual(codigo, cli.SAIDA_CONFORME)
        self.assertIn("88.30%", saida)

    def test_reuso_sai_um_abaixo_do_limiar(self) -> None:
        caminho = self._json("baixo.json", dict(REUSO, reuso_pct=69.9))
        codigo, saida, _ = _correr(["reuso", str(caminho)])
        self.assertEqual(codigo, cli.SAIDA_ACHADOS)
        self.assertIn("NÃO", saida)

    def test_reuso_de_outra_ponta_sai_dois(self) -> None:
        caminho = self._json("reuso.json", REUSO)
        codigo, _, erro = _correr(["reuso", str(caminho), "--ponta", "deadbee"])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("deadbee", erro)

    def test_reuso_sem_ficheiro_sai_dois(self) -> None:
        codigo, _, erro = _correr(["reuso", str(self.raiz / "nada.json")])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("não existe", erro)


class TestARaizNaoDependeDoCwd(unittest.TestCase):
    def test_a_raiz_por_omissao_tem_o_pnpm_workspace(self) -> None:
        """Um instrumento cujo significado muda com o `cwd` não é um instrumento."""
        raiz = cli._raiz_por_omissao()
        self.assertTrue((raiz / "pnpm-workspace.yaml").is_file())
        self.assertTrue((raiz / "ci" / "regra-de-dois.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
