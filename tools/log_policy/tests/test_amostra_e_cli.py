"""A amostragem e a linha de comandos do `log_policy` (KAM-068)."""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from log_policy import amostra, cli, fixtures, x11

ROOT = Path(__file__).resolve().parents[3]
SEM_NIF = x11.Configuracao.criar()
QUANDO = datetime.datetime(2026, 10, 12, 8, 0, 0, tzinfo=datetime.timezone.utc)


def _linha(numero: int, **campos) -> str:
    base = {"ts": "2026-01-01T00:00:00.000Z", "level": "info", "svc": "gwy", "latency_ms": numero}
    base.update(campos)
    return json.dumps(base, separators=(",", ":"))


def _correr(*argumentos: str) -> tuple[int, str, str]:
    saida, erros = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
        codigo = cli.main(list(argumentos))
    return codigo, saida.getvalue(), erros.getvalue()


class _ComPasta(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = Path(tempfile.mkdtemp(prefix="log-policy-"))
        self.addCleanup(shutil.rmtree, self.pasta, True)

    def escrever(self, nome: str, linhas: list[str]) -> Path:
        caminho = self.pasta / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return caminho


class TestAmostra(_ComPasta):
    def test_cem_linhas_por_servico_e_o_valor_por_omissao(self) -> None:
        self.assertEqual(amostra.LINHAS_POR_SERVICO, 100)

    def test_amostra_limpa(self) -> None:
        self.escrever("logs/gwy.log", [_linha(n, outcome="ok") for n in range(500)])
        self.escrever("logs/agr.log", [_linha(n, outcome="ok") for n in range(40)])
        registo = amostra.amostrar(self.pasta / "logs", SEM_NIF, semente=1, agora=QUANDO)
        self.assertEqual(
            registo,
            {
                "quando": "2026-10-12T08:00:00Z",
                "linhas_por_servico": 100,
                "nif_medido": False,
                "identificadores_directos": 0,
                "desvios_de_formato": 0,
                "servicos": {
                    "agr": {
                        "linhas_disponiveis": 40,
                        "linhas_amostradas": 40,
                        "amostra_completa": False,
                        "identificadores_directos": 0,
                        "desvios_de_formato": 0,
                        "por_padrao": {},
                    },
                    "gwy": {
                        "linhas_disponiveis": 500,
                        "linhas_amostradas": 100,
                        "amostra_completa": True,
                        "identificadores_directos": 0,
                        "desvios_de_formato": 0,
                        "por_padrao": {},
                    },
                },
            },
        )

    def test_conta_identificadores_e_desvios_a_parte_e_nunca_repete_o_valor(self) -> None:
        linhas = [_linha(n, outcome="ok") for n in range(20)]
        linhas += [_linha(1, outcome="923456789"), _linha(2, telefone="+244 923 456 789")]
        linhas += ["INFO: texto livre de uma biblioteca"]
        self.escrever("logs/gwy.log", linhas)
        registo = amostra.amostrar(self.pasta / "logs", SEM_NIF, agora=QUANDO)
        servico = registo["servicos"]["gwy"]
        self.assertEqual(servico["linhas_amostradas"], 23)
        self.assertEqual(servico["desvios_de_formato"], 2)
        self.assertEqual(
            servico["por_padrao"],
            {
                "campo_fora_da_allowlist": 1,
                "linha_fora_do_formato": 1,
                "sequencia_de_digitos": 2,
                "telefone_ao_internacional": 1,
                "telefone_ao_nacional": 2,
            },
        )
        self.assertEqual(servico["identificadores_directos"], 5)
        self.assertEqual(registo["identificadores_directos"], 5)
        texto = json.dumps(registo)
        self.assertNotIn("923", texto)
        self.assertNotIn("texto livre", texto)

    def test_a_amostra_e_aleatoria_e_a_semente_repete_a(self) -> None:
        linhas = [_linha(n, outcome="ok") for n in range(300)]
        linhas[137] = _linha(137, outcome="923456789")
        self.escrever("logs/gwy.log", linhas)
        com = [
            amostra.amostrar(self.pasta / "logs", SEM_NIF, quantas=30, semente=s, agora=QUANDO)
            for s in range(40)
        ]
        vistos = [r["identificadores_directos"] > 0 for r in com]
        self.assertIn(True, vistos)
        self.assertIn(False, vistos)
        outra_vez = amostra.amostrar(self.pasta / "logs", SEM_NIF, quantas=30, semente=7, agora=QUANDO)
        self.assertEqual(outra_vez, com[7])

    def test_sem_semente_usa_o_sorteio_do_sistema(self) -> None:
        self.escrever("logs/gwy.log", [_linha(n, outcome="ok") for n in range(300)])
        registo = amostra.amostrar(self.pasta / "logs", SEM_NIF, quantas=10)
        self.assertEqual(registo["servicos"]["gwy"]["linhas_amostradas"], 10)
        self.assertRegex(registo["quando"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_o_nif_so_e_medido_se_houver_padrao(self) -> None:
        self.escrever("logs/gwy.log", [_linha(1, outcome="NIF 1234")])
        sem = amostra.amostrar(self.pasta / "logs", SEM_NIF, agora=QUANDO)
        self.assertEqual((sem["nif_medido"], sem["identificadores_directos"]), (False, 0))
        com = amostra.amostrar(
            self.pasta / "logs", x11.Configuracao.criar(nif_padroes=(r"NIF [0-9]{4}",)), agora=QUANDO
        )
        self.assertEqual((com["nif_medido"], com["identificadores_directos"]), (True, 1))
        self.assertEqual(com["servicos"]["gwy"]["por_padrao"], {"nif": 1})

    def test_uma_amostragem_sem_linhas_nao_diz_que_deu_zero(self) -> None:
        for pasta in (self.pasta / "nao-existe", self.pasta):
            with self.assertRaises(x11.ConfiguracaoInvalida):
                amostra.amostrar(pasta, SEM_NIF)
        self.escrever("logs/gwy.log", [_linha(1)])
        with self.assertRaises(x11.ConfiguracaoInvalida):
            amostra.amostrar(self.pasta / "logs", SEM_NIF, quantas=0)

    def test_um_servico_com_o_log_vazio_nao_da_zero(self) -> None:
        """Primeira revisao: `gwy.log` vazio saia com rc=0 e `linhas_amostradas: 0`."""
        self.escrever("logs/agr.log", [_linha(1, outcome="ok")])
        for vazio in ("", "\n\n", "   \n"):
            (self.pasta / "logs" / "gwy.log").write_text(vazio, encoding="utf-8")
            with self.assertRaises(x11.ConfiguracaoInvalida) as capturado:
                amostra.amostrar(self.pasta / "logs", SEM_NIF, agora=QUANDO)
            self.assertIn("gwy.log", str(capturado.exception))
        registo = self.pasta / "r.jsonl"
        codigo, _, erros = _correr("amostra", str(self.pasta / "logs"), "--registo", str(registo))
        self.assertEqual(codigo, 2)
        self.assertIn("gwy.log nao tem linhas", erros)
        self.assertFalse(registo.exists())

    def test_o_registo_acumula_uma_linha_por_execucao(self) -> None:
        self.escrever("logs/gwy.log", [_linha(1, outcome="ok")])
        destino = self.pasta / "registos" / "amostragem.jsonl"
        for _ in range(3):
            amostra.registar(amostra.amostrar(self.pasta / "logs", SEM_NIF, agora=QUANDO), destino)
        linhas = destino.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(linhas), 3)
        self.assertEqual(json.loads(linhas[0])["quando"], "2026-10-12T08:00:00Z")


class TestLinhaDeComandos(_ComPasta):
    def test_lint_e_canario_no_repositorio_real(self) -> None:
        codigo, saida, erros = _correr("--root", str(ROOT), "lint")
        self.assertEqual((codigo, erros), (0, ""))
        self.assertIn("0 achado(s)", saida)
        codigo, saida, erros = _correr("--root", str(ROOT), "canario")
        self.assertEqual((codigo, erros), (0, ""))
        self.assertIn("29 negativas e 6 positivas; 0 falha(s)", saida)

    def test_lint_vermelho_sai_com_1_e_diz_onde(self) -> None:
        for topo in ("services", "packages", "libs"):
            shutil.copytree(
                ROOT / topo,
                self.pasta / topo,
                ignore=shutil.ignore_patterns("node_modules", "dist", "__pycache__"),
            )
        with (self.pasta / "services/gwy/src/app.ts").open("a", encoding="utf-8") as ficheiro:
            ficheiro.write("console.log('pedido');\n")
        codigo, saida, erros = _correr("--root", str(self.pasta), "lint")
        self.assertEqual(codigo, 1)
        self.assertIn("services/gwy/src/app.ts", erros)
        self.assertIn("console_directo", erros)
        self.assertIn("1 achado(s)", saida)

    def test_canario_vermelho_sai_com_1(self) -> None:
        codigo, saida, erros = _correr("--root", str(self.pasta), "canario")
        self.assertEqual(codigo, 1)
        self.assertIn("sem negativa que prove", erros)

    def test_lint_sem_arvore_e_erro_de_configuracao(self) -> None:
        codigo, _, erros = _correr("--root", str(self.pasta), "lint")
        self.assertEqual(codigo, 2)
        self.assertIn("log_policy: erro:", erros)

    def test_do_gerador_ao_varrimento(self) -> None:
        f = self.pasta / "x11" / "fixtures.json"
        log, contadores, ponte = (self.pasta / n for n in ("py.log", "py.json", "ponte.log"))
        self.assertEqual(_correr("fixtures", "--saida", str(f), "--quantas", "220")[0], 0)
        self.assertEqual(json.loads(f.read_text(encoding="utf-8")), fixtures.gerar(220))
        completo = self.pasta / "x11" / "completo.json"
        codigo, saida, _ = _correr("fixtures", "--saida", str(completo))
        self.assertIn("1030 fixtures", saida)
        self.assertEqual(
            json.loads(completo.read_text(encoding="utf-8")),
            fixtures.gerar() + fixtures.gerar_extras(),
        )
        codigo, saida, _ = _correr(
            "conduzir", str(f), "--saida", str(log), "--contadores", str(contadores),
            "--ponte", str(ponte),
        )
        self.assertEqual(codigo, 0)
        self.assertIn("220 chamadas", saida)
        self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 220)
        self.assertGreater(sum(json.loads(contadores.read_text(encoding="utf-8")).values()), 150)

        codigo, saida, erros = _correr(
            "x11", "--fixtures", str(f), "--linhas-esperadas", "220", str(log)
        )
        self.assertEqual((codigo, erros), (0, ""))
        self.assertIn("PADRAO DE NIF NAO DEFINIDO", saida)
        self.assertIn("220 linhas em 1 ficheiro(s)", saida)
        self.assertIn("0 achado(s)", saida)
        self.assertIn("telefone 22/22", saida)

        codigo, saida, _ = _correr("x11", "--fixtures", str(f), "--nif-padrao", r"\b[0-9]{10}\b", str(ponte))
        self.assertEqual(codigo, 0)
        self.assertNotIn("PADRAO DE NIF NAO DEFINIDO", saida)

        self.assertEqual(_correr("iguais", str(log), str(log))[0], 0)

    def test_x11_com_um_canario_no_log_sai_com_1_sem_o_repetir(self) -> None:
        f = self.pasta / "fixtures.json"
        _correr("fixtures", "--saida", str(f), "--quantas", "110")
        conjunto = json.loads(f.read_text(encoding="utf-8"))
        nome = next(x for x in conjunto if x["classe"] == "nome")
        log = self.escrever("gwy.log", [_linha(1, outcome="ok"), "cliente " + nome["canarios"][0]])
        codigo, saida, erros = _correr("x11", "--fixtures", str(f), str(log))
        self.assertEqual(codigo, 1)
        self.assertIn("gwy.log:2: canario em <linha>", erros)
        self.assertNotIn(nome["canarios"][0], saida + erros)

    def test_x11_resume_quando_ha_muitos_achados(self) -> None:
        log = self.escrever("gwy.log", [_linha(n, outcome="923456789") for n in range(60)])
        codigo, saida, erros = _correr("x11", str(log))
        self.assertEqual(codigo, 1)
        self.assertEqual(erros.count("x11: gwy.log:"), cli.MAXIMO_IMPRESSO)
        self.assertIn("e mais 80", erros)
        self.assertIn("120 achado(s)", saida)
        self.assertNotIn("923456789", saida + erros)

    def test_x11_exige_o_numero_de_linhas_e_pelo_menos_uma(self) -> None:
        log = self.escrever("gwy.log", [_linha(1, outcome="ok")])
        codigo, _, erros = _correr("x11", "--linhas-esperadas", "2", str(log))
        self.assertEqual(codigo, 1)
        self.assertIn("tem 1 linhas, esperava 2", erros)
        vazio = self.escrever("vazio.log", [""])
        codigo, _, erros = _correr("x11", str(vazio))
        self.assertEqual(codigo, 1)
        self.assertIn("nenhuma linha lida", erros)

    def test_x11_falha_se_o_controlo_positivo_falhar(self) -> None:
        """Se os padroes deixarem de ver os telefones, o zero nao vale."""
        conjunto = fixtures.gerar(110)
        for fixture in conjunto:
            if fixture["classe"] == "telefone":
                fixture["valor"] = "sem numero nenhum"
        f = self.pasta / "fixtures.json"
        f.write_text(json.dumps(conjunto), encoding="utf-8")
        log = self.escrever("gwy.log", [_linha(1, outcome="ok")])
        codigo, _, erros = _correr("x11", "--fixtures", str(f), str(log))
        self.assertEqual(codigo, 1)
        self.assertIn("controlo positivo falhou em `telefone`: os padroes veem 0 de 11", erros)

    def test_x11_erros_de_configuracao_saem_com_2(self) -> None:
        log = self.escrever("gwy.log", [_linha(1)])
        self.assertEqual(_correr("x11", "--nif-padrao", "[0-9", str(log))[0], 2)
        self.assertEqual(_correr("x11", str(self.pasta / "nao-existe.log"))[0], 2)
        self.assertEqual(_correr("x11", "--fixtures", str(self.pasta / "nao.json"), str(log))[0], 2)
        vazias = self.escrever("vazias.json", ["[]"])
        self.assertEqual(_correr("x11", "--fixtures", str(vazias), str(log))[0], 2)

    def test_iguais_diz_a_linha_e_nunca_o_conteudo(self) -> None:
        a = self.escrever("a.log", [_linha(1), _linha(2), _linha(3, outcome="ok")])
        b = self.escrever("b.log", [_linha(1), _linha(2), _linha(3, outcome="923456789")])
        c = self.escrever("c.log", [_linha(1), _linha(2)])
        codigo, _, erros = _correr("iguais", str(a), str(b))
        self.assertEqual(codigo, 1)
        self.assertIn("divergem a partir da linha 3", erros)
        self.assertNotIn("923456789", erros)
        codigo, _, erros = _correr("iguais", str(a), str(c))
        self.assertEqual(codigo, 1)
        self.assertIn("a partir da linha 3", erros)

    def test_amostra_regista_e_sai_com_1_se_houver_achados(self) -> None:
        self.escrever("logs/gwy.log", [_linha(n, outcome="ok") for n in range(10)])
        registo = self.pasta / "amostragem.jsonl"
        codigo, saida, _ = _correr(
            "amostra", str(self.pasta / "logs"), "--registo", str(registo), "--semente", "3"
        )
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(saida)["servicos"]["gwy"]["linhas_amostradas"], 10)
        self.escrever("logs/agr.log", [_linha(1, outcome="923456789")])
        codigo, saida, _ = _correr(
            "amostra", str(self.pasta / "logs"), "--registo", str(registo), "--linhas", "5",
            "--nif-padrao", "NIF [0-9]{4}",
        )
        self.assertEqual(codigo, 1)
        self.assertNotIn("923456789", saida)
        linhas = registo.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(linhas), 2)
        self.assertEqual(json.loads(linhas[1])["linhas_por_servico"], 5)
        self.assertTrue(json.loads(linhas[1])["nif_medido"])

    def test_amostra_sem_ficheiros_e_erro_de_configuracao(self) -> None:
        codigo, _, erros = _correr("amostra", str(self.pasta), "--registo", str(self.pasta / "r.jsonl"))
        self.assertEqual(codigo, 2)
        self.assertIn("nao mediu nada", erros)


if __name__ == "__main__":
    unittest.main()
