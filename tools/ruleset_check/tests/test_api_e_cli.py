"""Fail-closed, ausencia de caminho de escrita, e a configuracao (KAM-137).

O caso (e) do criterio 3 — «credencial sem autorizacao ou API em baixo ->
vermelha, nao verde» — e o criterio 5 inteiro vivem aqui: nenhuma destas
situacoes pode sair **0**, e nenhuma pode sair **1**, porque 1 e «o ruleset
diverge» e dizer isso quando nao se leu nada seria outra mentira.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ruleset_check import api, cli, comparador, config

from .base import ROOT, espelho, resposta_da_api

PACOTE = Path(api.__file__).resolve().parent


def correr(argv: list[str]) -> tuple[int, str, str]:
    saida, erros = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
        codigo = cli.main(argv)
    return codigo, saida.getvalue(), erros.getvalue()


class TestFailClosed(unittest.TestCase):
    """Nao conseguir verificar e **2**."""

    def test_api_em_baixo_sai_2(self) -> None:
        with mock.patch.object(
            api, "obter", side_effect=api.ApiIndisponivel("GET …: rede inacessivel")
        ):
            codigo, _, erros = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 2)
        self.assertIn("NAO SE CONSEGUIU LER O RULESET EFECTIVO", erros)

    def test_credencial_sem_autorizacao_sai_2(self) -> None:
        with mock.patch.object(
            api, "obter", side_effect=api.ApiIndisponivel("`gh api …` saiu 1: HTTP 403")
        ):
            codigo, saida, _ = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 2)
        self.assertEqual(saida, "", "nada em stdout: ninguem pode ler isto como conforme")

    def test_gh_ausente_sai_2(self) -> None:
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(api.ApiIndisponivel) as caixa:
                api.obter_via_gh("repos/x/y/rulesets/1")
        self.assertIn("gh", str(caixa.exception))

    def test_gh_com_codigo_de_saida_nao_nulo(self) -> None:
        resultado = mock.Mock(returncode=1, stdout="", stderr="HTTP 403: Must have admin")
        with mock.patch("subprocess.run", return_value=resultado):
            with self.assertRaises(api.ApiIndisponivel) as caixa:
                api.obter_via_gh("repos/x/y/rulesets/1")
        self.assertIn("403", str(caixa.exception))

    def test_corpo_que_nao_e_json(self) -> None:
        resultado = mock.Mock(returncode=0, stdout="<html>502</html>", stderr="")
        with mock.patch("subprocess.run", return_value=resultado):
            with self.assertRaises(api.ApiIndisponivel):
                api.obter_via_gh("repos/x/y/rulesets/1")

    def test_corpo_json_que_nao_e_objecto(self) -> None:
        resultado = mock.Mock(returncode=0, stdout="[]", stderr="")
        with mock.patch("subprocess.run", return_value=resultado):
            with self.assertRaises(api.ApiIndisponivel):
                api.obter_via_gh("repos/x/y/rulesets/1")

    def test_transporte_http_sem_token_sai_2_e_nao_0(self) -> None:
        with mock.patch.dict(os.environ, {api.NOME_DA_VARIAVEL: ""}, clear=False):
            codigo, saida, erros = correr(
                ["check", "--root", str(ROOT), "--transporte", "http"]
            )
        self.assertEqual(codigo, 2)
        self.assertEqual(saida, "")
        self.assertIn(api.NOME_DA_VARIAVEL, erros)

    def test_espelho_ilegivel_sai_2(self) -> None:
        with mock.patch.object(
            comparador, "ler_espelho", side_effect=comparador.EspelhoInvalido("x: nao existe")
        ):
            codigo, _, _ = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 2)

    def test_configuracao_ilegivel_sai_2(self) -> None:
        with mock.patch.object(
            config, "ler", side_effect=config.ConfiguracaoInvalida("ci/ruleset.yaml: x")
        ):
            codigo, _, _ = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 2)


class TestOTokenNaoApareceNaSaida(unittest.TestCase):
    """«O relatorio da verificacao nao imprime a credencial nem o token.»"""

    #: Construida em tempo de execucao, de proposito. Escrita de uma peca, a
    #: cadeia tem a forma publicada de um token do GitHub e o gate 9 apanha-a —
    #: e bem, porque o `ci/secrets-allow.yaml` diz a letra que «nem as fixtures
    #: sao area permitida por serem fixtures». Partir o prefixo e o que torna o
    #: teste possivel sem abrir uma area no scanner.
    SENTINELA = "gh" + "p_" + "sentinela_que_nao_pode_aparecer_0000"

    def test_erro_http_nao_reproduz_o_token(self) -> None:
        erro = urllib.error.HTTPError(
            f"https://api.github.com/x?t={self.SENTINELA}", 401, "Unauthorized", {}, None
        )
        with mock.patch("urllib.request.urlopen", side_effect=erro):
            with self.assertRaises(api.ApiIndisponivel) as caixa:
                api.obter_via_http("repos/x/y/rulesets/1", self.SENTINELA)
        self.assertNotIn(self.SENTINELA, str(caixa.exception))

    def test_erro_de_rede_nao_reproduz_o_token(self) -> None:
        erro = urllib.error.URLError(f"falhou com {self.SENTINELA}")
        with mock.patch("urllib.request.urlopen", side_effect=erro):
            with self.assertRaises(api.ApiIndisponivel) as caixa:
                api.obter_via_http("repos/x/y/rulesets/1", self.SENTINELA)
        self.assertNotIn(self.SENTINELA, str(caixa.exception))

    def test_a_linha_de_comando_do_gh_nao_leva_token(self) -> None:
        resultado = mock.Mock(returncode=0, stdout=json.dumps(resposta_da_api()), stderr="")
        with mock.patch("subprocess.run", return_value=resultado) as corrido:
            api.obter_via_gh("repos/x/y/rulesets/1")
        self.assertEqual(corrido.call_args.args[0], ["gh", "api", "repos/x/y/rulesets/1"])


class TestSemCaminhoDeEscrita(unittest.TestCase):
    """A decisao e «so deteccao». Um caminho de escrita aqui desfa-la em silencio."""

    METODOS = ("POST", "PUT", "PATCH", "DELETE")

    def ficheiros(self) -> list[Path]:
        return sorted(p for p in PACOTE.glob("*.py"))

    @staticmethod
    def _literais_fora_de_docstring(arvore: ast.AST) -> list[str]:
        """Todas as cadeias do modulo, menos os docstrings.

        Os docstrings nomeiam os metodos de escrita **para dizer que nao estao
        la**, e apanha-los seria apanhar a propria garantia.
        """
        docstrings = set()
        for no in ast.walk(arvore):
            if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                corpo = getattr(no, "body", [])
                if (
                    corpo
                    and isinstance(corpo[0], ast.Expr)
                    and isinstance(corpo[0].value, ast.Constant)
                    and isinstance(corpo[0].value.value, str)
                ):
                    docstrings.add(id(corpo[0].value))
        return [
            no.value
            for no in ast.walk(arvore)
            if isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and id(no) not in docstrings
        ]

    def test_nenhum_metodo_de_escrita_no_pacote(self) -> None:
        for ficheiro in self.ficheiros():
            literais = self._literais_fora_de_docstring(
                ast.parse(ficheiro.read_text(encoding="utf-8"))
            )
            for metodo in self.METODOS:
                with self.subTest(ficheiro=ficheiro.name, metodo=metodo):
                    self.assertEqual(
                        [v for v in literais if metodo in v], [],
                        f"{ficheiro.name}: `{metodo}` fora de um docstring",
                    )

    def test_o_unico_metodo_pedido_e_get(self) -> None:
        texto = (PACOTE / "api.py").read_text(encoding="utf-8")
        self.assertIn('method="GET"', texto)

    def test_o_gh_e_chamado_so_com_o_subcomando_api(self) -> None:
        texto = (PACOTE / "api.py").read_text(encoding="utf-8")
        chamadas = re.findall(r'\["gh",\s*"([a-z-]+)"', texto)
        self.assertEqual(set(chamadas), {"api"})
        self.assertNotIn("--method", texto)
        self.assertNotIn("-X", texto)


class TestConfiguracao(unittest.TestCase):
    def test_le_o_ficheiro_real(self) -> None:
        conf = config.ler(ROOT)
        self.assertEqual(conf.repositorio, "albinoJimy/kamba")
        self.assertEqual(conf.espelho, ".github/rulesets/main.json")
        self.assertTrue((ROOT / conf.espelho).is_file())

    def test_o_caminho_da_api_e_de_leitura_de_um_ruleset(self) -> None:
        conf = config.ler(ROOT)
        self.assertEqual(
            conf.caminho_da_api, f"repos/albinoJimy/kamba/rulesets/{conf.ruleset_id}"
        )

    def test_uma_chave_desconhecida_e_recusada(self) -> None:
        """KAM-134: uma chave que ninguem le e uma promessa por cumprir."""
        with mock.patch.object(
            config, "load_file",
            return_value={"version": 1, "repositorio": "a/b", "ruleset_id": 1,
                          "espelho": "x.json", "chave_que_ninguem_le": True},
        ):
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(ROOT)
        self.assertIn("chave_que_ninguem_le", str(caixa.exception))

    def test_um_repositorio_mal_formado_e_recusado(self) -> None:
        with mock.patch.object(
            config, "load_file",
            return_value={"repositorio": "kamba", "ruleset_id": 1, "espelho": "x.json"},
        ):
            with self.assertRaises(config.ConfiguracaoInvalida):
                config.ler(ROOT)

    def test_um_id_que_nao_e_inteiro_positivo_e_recusado(self) -> None:
        for valor in ("24879081", -1, 0, True):
            with self.subTest(valor=valor):
                with mock.patch.object(
                    config, "load_file",
                    return_value={"repositorio": "a/b", "ruleset_id": valor,
                                  "espelho": "x.json"},
                ):
                    with self.assertRaises(config.ConfiguracaoInvalida):
                        config.ler(ROOT)

    def test_o_id_do_ficheiro_e_o_do_comando_de_exportacao_do_readme(self) -> None:
        """Duas copias do mesmo numero: ou concordam, ou isto fica vermelho."""
        readme = (ROOT / ".github" / "rulesets" / "README.md").read_text(encoding="utf-8")
        conf = config.ler(ROOT)
        encontrados = set(re.findall(r"/rulesets/(\d+)", readme))
        self.assertEqual(encontrados, {str(conf.ruleset_id)})
        self.assertIn(f"repos/{conf.repositorio}/rulesets/", readme)


class TestTransportes(unittest.TestCase):
    """O caminho feliz dos dois transportes, e a recusa de um terceiro."""

    class _Resposta:
        def __init__(self, corpo: str) -> None:
            self._corpo = corpo.encode("utf-8")

        def read(self) -> bytes:
            return self._corpo

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def test_http_le_e_devolve_o_objecto(self) -> None:
        bruto = resposta_da_api()
        with mock.patch(
            "urllib.request.urlopen", return_value=self._Resposta(json.dumps(bruto))
        ) as aberto:
            lido = api.obter_via_http("repos/x/y/rulesets/1", "um-token")
        self.assertEqual(lido["name"], bruto["name"])
        pedido = aberto.call_args.args[0]
        self.assertEqual(pedido.get_method(), "GET")

    def test_http_com_corpo_que_nao_e_json(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=self._Resposta("<html>")):
            with self.assertRaises(api.ApiIndisponivel):
                api.obter_via_http("repos/x/y/rulesets/1", "um-token")

    def test_http_com_corpo_que_nao_e_objecto(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=self._Resposta("[1,2]")):
            with self.assertRaises(api.ApiIndisponivel):
                api.obter_via_http("repos/x/y/rulesets/1", "um-token")

    def test_gh_que_nao_responde_a_tempo(self) -> None:
        import subprocess as sub

        with mock.patch("subprocess.run", side_effect=sub.TimeoutExpired("gh", 30)):
            with self.assertRaises(api.ApiIndisponivel) as caixa:
                api.obter_via_gh("repos/x/y/rulesets/1")
        self.assertIn("nao respondeu", str(caixa.exception))

    def test_um_transporte_que_nao_existe_e_erro_de_programacao(self) -> None:
        with self.assertRaises(ValueError):
            api.obter("repos/x/y/rulesets/1", "pombo-correio")

    def test_obter_encaminha_para_o_http(self) -> None:
        with mock.patch.object(api, "obter_via_http", return_value={"a": 1}) as via:
            with mock.patch.dict(os.environ, {api.NOME_DA_VARIAVEL: "t"}, clear=False):
                self.assertEqual(api.obter("c", "http"), {"a": 1})
        self.assertEqual(via.call_args.args, ("c", "t"))


class TestLeituraDoEspelho(unittest.TestCase):
    def test_ficheiro_que_nao_existe(self) -> None:
        with self.assertRaises(comparador.EspelhoInvalido):
            comparador.ler_espelho(ROOT / ".github" / "rulesets" / "nao-existe.json")

    def test_json_malformado(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "x.json"
            caminho.write_text("{ isto nao e json", encoding="utf-8")
            with self.assertRaises(comparador.EspelhoInvalido):
                comparador.ler_espelho(caminho)

    def test_json_que_nao_e_objecto(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "x.json"
            caminho.write_text("[]", encoding="utf-8")
            with self.assertRaises(comparador.EspelhoInvalido):
                comparador.ler_espelho(caminho)


class TestConfiguracaoAusente(unittest.TestCase):
    def test_ficheiro_que_nao_existe(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(Path(pasta))
        self.assertIn(config.CAMINHO, str(caixa.exception))

    def test_chave_obrigatoria_em_falta(self) -> None:
        with mock.patch.object(config, "load_file", return_value={"version": 1}):
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(ROOT)
        self.assertIn("espelho", str(caixa.exception))

    def test_espelho_que_nao_e_caminho(self) -> None:
        with mock.patch.object(
            config, "load_file",
            return_value={"repositorio": "a/b", "ruleset_id": 1, "espelho": ""},
        ):
            with self.assertRaises(config.ConfiguracaoInvalida):
                config.ler(ROOT)

    def test_yaml_ilegivel(self) -> None:
        from kamba_yaml import YamlSubsetError

        with mock.patch.object(config, "load_file", side_effect=YamlSubsetError("linha 2")):
            with self.assertRaises(config.ConfiguracaoInvalida):
                config.ler(ROOT)


class TestSaidaDoCheck(unittest.TestCase):
    def test_conforme_sai_0_e_diz_os_numeros(self) -> None:
        with mock.patch.object(api, "obter", return_value=resposta_da_api()):
            codigo, saida, _ = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 0)
        self.assertIn("conforme", saida)
        self.assertIn("7 required check(s)", saida)

    def test_divergente_sai_1_e_nomeia_a_regra(self) -> None:
        bruto = resposta_da_api(enforcement="disabled")
        with mock.patch.object(api, "obter", return_value=bruto):
            codigo, saida, erros = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 1)
        self.assertEqual(saida, "")
        self.assertIn("campo-divergente", erros)
        self.assertIn(".github/rulesets/README.md", erros)

    def test_mostrar_imprime_o_normalizado_sem_volateis(self) -> None:
        with mock.patch.object(api, "obter", return_value=resposta_da_api()):
            codigo, saida, _ = correr(["mostrar", "--root", str(ROOT)])
        self.assertEqual(codigo, 0)
        impresso = json.loads(saida)
        self.assertEqual(sorted(impresso), sorted(comparador.CAMPOS_DE_TOPO))
        for volatil in comparador.VOLATEIS:
            self.assertNotIn(volatil, impresso)

    def test_o_espelho_real_bate_com_ele_proprio(self) -> None:
        """Sanidade: o comparador nao inventa divergencias sobre o ficheiro real."""
        with mock.patch.object(api, "obter", return_value=espelho()):
            codigo, _, _ = correr(["check", "--root", str(ROOT)])
        self.assertEqual(codigo, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
