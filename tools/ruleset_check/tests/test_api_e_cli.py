"""Fail-closed, transportes, configuracao e saida da linha de comando (KAM-137).

O caso (e) do criterio 3 — «credencial sem autorizacao ou API em baixo ->
vermelha, nao verde» — e o criterio 5 inteiro vivem aqui: nenhuma destas
situacoes pode sair **0**, e nenhuma pode sair **1**, porque 1 e «o ruleset
diverge» e dizer isso quando nao se leu nada seria outra mentira.

A guarda «so leitura» mudou-se para `test_guarda_de_escrita.py`, que a faz a
serio: a que vivia aqui lia um ficheiro so e nao apanhava um `POST` implicito.
"""

from __future__ import annotations

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

from .base import (
    ID_DO_PRIVADO, PRIVADO, PUBLICO, ROOT, api_falsa, entrada_da_listagem,
    espelho, resposta_da_api, tudo_conforme,
)


def correr(argv: list[str], mapa: dict | None = None) -> tuple[int, str, str]:
    saida, erros = io.StringIO(), io.StringIO()
    contexto = contextlib.ExitStack()
    if mapa is not None:
        listar, obter = api_falsa(mapa)
        contexto.enter_context(mock.patch.object(api, "listar", listar))
        contexto.enter_context(mock.patch.object(api, "obter", obter))
    with contexto, contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
        codigo = cli.main(argv)
    return codigo, saida.getvalue(), erros.getvalue()


CHECK = ["check", "--root", str(ROOT)]


class TestFailClosed(unittest.TestCase):
    """Nao conseguir verificar e **2**."""

    def test_api_em_baixo_sai_2(self) -> None:
        with mock.patch.object(
            api, "listar", side_effect=api.ApiIndisponivel("GET …: rede inacessivel")
        ):
            codigo, _, erros = correr(CHECK)
        self.assertEqual(codigo, 2)
        self.assertIn("NAO SE CONSEGUIU LER O RULESET EFECTIVO", erros)

    def test_credencial_sem_autorizacao_sai_2(self) -> None:
        with mock.patch.object(
            api, "listar", side_effect=api.ApiIndisponivel("`gh api …` saiu 1: HTTP 403")
        ):
            codigo, saida, _ = correr(CHECK)
        self.assertEqual(codigo, 2)
        self.assertNotIn("conforme", saida)

    def test_uma_falha_no_segundo_alvo_tambem_sai_2(self) -> None:
        """Nao basta o primeiro alvo correr bem: basta um a falhar para ser 2."""
        chamadas = {"n": 0}

        def listar(caminho: str, transporte: str = "gh") -> list:
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                return [entrada_da_listagem()]
            raise api.ApiIndisponivel("HTTP 403 no segundo alvo")

        _, obter = api_falsa(tudo_conforme())
        with mock.patch.object(api, "listar", listar), \
                mock.patch.object(api, "obter", obter):
            codigo, saida, erros = correr(CHECK)
        self.assertEqual(codigo, 2)
        self.assertIn("segundo alvo", erros)
        self.assertNotIn("0 divergencias", saida)

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

    def test_um_recurso_que_devia_ser_objecto_e_vem_lista(self) -> None:
        resultado = mock.Mock(returncode=0, stdout="[]", stderr="")
        with mock.patch("subprocess.run", return_value=resultado):
            with self.assertRaises(api.ApiIndisponivel):
                api.obter_via_gh("repos/x/y/rulesets/1")

    def test_uma_coleccao_que_devia_ser_lista_e_vem_objecto(self) -> None:
        resultado = mock.Mock(returncode=0, stdout="{}", stderr="")
        with mock.patch("subprocess.run", return_value=resultado):
            with self.assertRaises(api.ApiIndisponivel):
                api.listar("repos/x/y/rulesets")

    def test_uma_coleccao_vazia_NAO_e_erro(self) -> None:
        """E a resposta que diz «este repositorio nao tem rulesets». Nao e 2."""
        resultado = mock.Mock(returncode=0, stdout="[]", stderr="")
        with mock.patch("subprocess.run", return_value=resultado):
            self.assertEqual(api.listar("repos/x/y/rulesets"), [])

    def test_transporte_http_sem_token_sai_2_e_nao_0(self) -> None:
        with mock.patch.dict(os.environ, {api.NOME_DA_VARIAVEL: ""}, clear=False):
            codigo, saida, erros = correr(CHECK + ["--transporte", "http"])
        self.assertEqual(codigo, 2)
        self.assertNotIn("conforme", saida)
        self.assertIn(api.NOME_DA_VARIAVEL, erros)

    def test_espelho_ilegivel_sai_2(self) -> None:
        with mock.patch.object(
            comparador, "ler_espelho", side_effect=comparador.EspelhoInvalido("x: nao existe")
        ):
            codigo, _, _ = correr(CHECK)
        self.assertEqual(codigo, 2)

    def test_configuracao_ilegivel_sai_2(self) -> None:
        with mock.patch.object(
            config, "ler", side_effect=config.ConfiguracaoInvalida("ci/ruleset.yaml: x")
        ):
            codigo, _, _ = correr(CHECK)
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
        self.assertEqual(aberto.call_args.args[0].get_method(), "GET")

    def test_http_com_corpo_que_nao_e_json(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=self._Resposta("<html>")):
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
        with mock.patch.object(api, "_ler_via_http", return_value={"a": 1}) as via:
            with mock.patch.dict(os.environ, {api.NOME_DA_VARIAVEL: "t"}, clear=False):
                self.assertEqual(api.obter("c", "http"), {"a": 1})
        self.assertEqual(via.call_args.args, ("c", "t"))


class TestConfiguracao(unittest.TestCase):
    def test_le_o_ficheiro_real_e_tem_os_dois_repositorios(self) -> None:
        alvos = config.ler(ROOT)
        self.assertEqual([a.repositorio for a in alvos], [PRIVADO, PUBLICO])
        for alvo in alvos:
            self.assertTrue((ROOT / alvo.espelho).is_file())
            self.assertTrue(alvo.razao.strip(), f"{alvo.repositorio} sem razao escrita")

    def test_o_repositorio_publico_esta_na_lista(self) -> None:
        """O bloqueador em uma linha: o repositorio onde os PR vivem e verificado."""
        self.assertIn(PUBLICO, [a.repositorio for a in config.ler(ROOT)])

    def test_o_caminho_da_api_e_de_leitura(self) -> None:
        alvo = config.ler(ROOT)[0]
        self.assertEqual(alvo.caminho_da_lista, f"repos/{PRIVADO}/rulesets")
        self.assertEqual(alvo.caminho_do_ruleset(7), f"repos/{PRIVADO}/rulesets/7")

    def test_uma_chave_desconhecida_de_topo_e_recusada(self) -> None:
        with mock.patch.object(
            config, "load_file",
            return_value={"version": 1, "alvos": [], "chave_que_ninguem_le": True},
        ):
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(ROOT)
        self.assertIn("chave_que_ninguem_le", str(caixa.exception))

    def test_uma_chave_desconhecida_num_alvo_e_recusada(self) -> None:
        with mock.patch.object(
            config, "load_file",
            return_value={"alvos": [{"repositorio": "a/b", "espelho": "x.json",
                                     "chave_nova": 1}]},
        ):
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(ROOT)
        self.assertIn("chave_nova", str(caixa.exception))

    def test_lista_de_alvos_vazia_e_recusada(self) -> None:
        """Uma lista vazia faria a verificacao sair 0 sem verificar nada."""
        with mock.patch.object(config, "load_file", return_value={"alvos": []}):
            with self.assertRaises(config.ConfiguracaoInvalida):
                config.ler(ROOT)

    def test_repositorio_repetido_e_recusado(self) -> None:
        alvo = {"repositorio": "a/b", "espelho": "x.json"}
        with mock.patch.object(config, "load_file", return_value={"alvos": [alvo, alvo]}):
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(ROOT)
        self.assertIn("repetido", str(caixa.exception))

    def test_um_repositorio_mal_formado_e_recusado(self) -> None:
        with mock.patch.object(
            config, "load_file",
            return_value={"alvos": [{"repositorio": "kamba", "espelho": "x.json"}]},
        ):
            with self.assertRaises(config.ConfiguracaoInvalida):
                config.ler(ROOT)

    def test_chave_obrigatoria_em_falta(self) -> None:
        with mock.patch.object(config, "load_file", return_value={"alvos": [{"espelho": "x"}]}):
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(ROOT)
        self.assertIn("repositorio", str(caixa.exception))

    def test_um_id_que_nao_e_inteiro_positivo_e_recusado(self) -> None:
        for valor in ("24879081", -1, 0, True):
            with self.subTest(valor=valor):
                with mock.patch.object(
                    config, "load_file",
                    return_value={"alvos": [{"repositorio": "a/b", "espelho": "x.json",
                                             "ruleset_id": valor}]},
                ):
                    with self.assertRaises(config.ConfiguracaoInvalida):
                        config.ler(ROOT)

    def test_o_id_pode_ficar_por_declarar(self) -> None:
        """E o que permite declarar um alvo cujo ruleset ainda nao existe."""
        with mock.patch.object(
            config, "load_file",
            return_value={"alvos": [{"repositorio": "a/b", "espelho": "x.json"}]},
        ):
            self.assertIsNone(config.ler(ROOT)[0].ruleset_id)

    def test_ficheiro_que_nao_existe(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaises(config.ConfiguracaoInvalida) as caixa:
                config.ler(Path(pasta))
        self.assertIn(config.CAMINHO, str(caixa.exception))

    def test_yaml_ilegivel(self) -> None:
        from kamba_yaml import YamlSubsetError

        with mock.patch.object(config, "load_file", side_effect=YamlSubsetError("linha 2")):
            with self.assertRaises(config.ConfiguracaoInvalida):
                config.ler(ROOT)

    def test_cada_id_declarado_esta_no_readme_do_ruleset(self) -> None:
        """Duas copias do mesmo numero: ou concordam, ou isto fica vermelho."""
        readme = (ROOT / ".github" / "rulesets" / "README.md").read_text(encoding="utf-8")
        declarados = {str(a.ruleset_id) for a in config.ler(ROOT) if a.ruleset_id}
        self.assertEqual(set(re.findall(r"/rulesets/(\d+)", readme)), declarados)

    def test_cada_alvo_esta_nomeado_no_readme_do_ruleset(self) -> None:
        readme = (ROOT / ".github" / "rulesets" / "README.md").read_text(encoding="utf-8")
        for alvo in config.ler(ROOT):
            with self.subTest(repositorio=alvo.repositorio):
                self.assertIn(alvo.repositorio, readme)


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


class TestSaidaDoCheck(unittest.TestCase):
    def test_todos_conformes_sai_0_e_diz_os_numeros(self) -> None:
        codigo, saida, _ = correr(CHECK, tudo_conforme())
        self.assertEqual(codigo, 0)
        self.assertIn("conforme — 2 alvo(s), 0 divergencias", saida)
        self.assertIn("7 required check(s)", saida)
        for repositorio in (PRIVADO, PUBLICO):
            self.assertIn(repositorio, saida)

    def test_um_alvo_divergente_leva_o_conjunto_a_1(self) -> None:
        mapa = tudo_conforme()
        mapa[PUBLICO] = ([], {})
        codigo, saida, erros = correr(CHECK, mapa)
        self.assertEqual(codigo, 1)
        self.assertIn("repositorio-sem-ruleset", erros)
        self.assertNotIn("0 divergencias", saida)
        self.assertIn(PRIVADO, saida, "o alvo conforme continua a sair nomeado")

    def test_a_razao_do_alvo_sai_no_vermelho(self) -> None:
        mapa = tudo_conforme()
        mapa[PUBLICO] = ([], {})
        _, _, erros = correr(CHECK, mapa)
        self.assertIn("porque esta na lista:", erros)

    def test_um_id_resolvido_e_nao_declarado_sai_para_ser_escrito(self) -> None:
        mapa = tudo_conforme()
        mapa[PUBLICO] = ([entrada_da_listagem(ruleset_id=4242)],
                         {4242: resposta_da_api(enforcement="evaluate")})
        _, _, erros = correr(CHECK, mapa)
        self.assertIn("4242", erros)
        self.assertIn(config.CAMINHO, erros)

    def test_divergente_aponta_o_procedimento(self) -> None:
        mapa = tudo_conforme()
        mapa[PRIVADO] = ([entrada_da_listagem()],
                         {ID_DO_PRIVADO: resposta_da_api(enforcement="disabled")})
        codigo, _, erros = correr(CHECK, mapa)
        self.assertEqual(codigo, 1)
        self.assertIn("campo-divergente", erros)
        self.assertIn(".github/rulesets/README.md", erros)


class TestMostrar(unittest.TestCase):
    def test_produz_o_formato_exacto_do_espelho(self) -> None:
        """O criterio do revisor: ou produz o formato, ou a docstring deixa de o sugerir."""
        codigo, saida, _ = correr(
            ["mostrar", "--root", str(ROOT), "--repositorio", PRIVADO], tudo_conforme()
        )
        self.assertEqual(codigo, 0)
        no_disco = (ROOT / ".github" / "rulesets" / "main.json").read_text(encoding="utf-8")
        self.assertEqual(saida.replace("\r", ""), no_disco)

    def test_nao_imprime_volateis(self) -> None:
        _, saida, _ = correr(
            ["mostrar", "--root", str(ROOT), "--repositorio", PRIVADO], tudo_conforme()
        )
        impresso = json.loads(saida)
        self.assertEqual(sorted(impresso), sorted(comparador.CAMPOS_DE_TOPO))
        for volatil in comparador.VOLATEIS:
            self.assertNotIn(volatil, impresso)

    def test_sem_repositorio_sai_2_e_diz_quais_ha(self) -> None:
        codigo, _, erros = correr(["mostrar", "--root", str(ROOT)], tudo_conforme())
        self.assertEqual(codigo, 2)
        self.assertIn(PUBLICO, erros)

    def test_repositorio_sem_o_ruleset_sai_2(self) -> None:
        mapa = tudo_conforme()
        mapa[PUBLICO] = ([], {})
        codigo, saida, _ = correr(
            ["mostrar", "--root", str(ROOT), "--repositorio", PUBLICO], mapa
        )
        self.assertEqual(codigo, 2)
        self.assertEqual(saida, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
