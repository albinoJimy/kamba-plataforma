"""Lint de arquitectura: nenhum servico escreve fora do *logger* (KAM-068).

O repositorio real passa; uma copia com um `console.log` ou um `print` num
servico fica vermelha, pela regra certa e na linha certa. As mutacoes fazem-se
numa copia, nunca na arvore.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from log_policy import cli, lint

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / cli.PASTA_DO_CANARIO


def _regras_ts(fonte: str) -> list[str]:
    return [regra for _, regra in lint.analisar_ts(fonte)]


def _regras_py(fonte: str) -> list[str]:
    return [regra for _, regra in lint.analisar_py(fonte)]


class TestTypeScript(unittest.TestCase):
    def test_console_em_todas_as_formas(self) -> None:
        for fonte in (
            "console.log(x);",
            "console.error(x)",
            "console . warn(x)",
            "console['info'](x)",
            "globalThis.console.debug(x)",
            "const c = console;",
            "const { log } = console;",
            "if (ok) console.table(x)",
            "import console from 'node:console';",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [lint.CONSOLE])

    def test_stdout_e_stderr(self) -> None:
        for fonte in (
            "process.stdout.write(x)",
            "process.stderr.write(x)",
            "process?.stdout.write(x)",
            "process . stdout . write(x)",
            'process["stdout"].write(x)',
            "process['stderr'].write(x)",
            "const saida = process.stdout;",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [lint.STDOUT])

    def test_o_fluxo_por_outros_caminhos(self) -> None:
        """Achado A2 da revisao: o mesmo `stdout`, sem escrever `process.stdout`."""
        for fonte in (
            'import { stdout } from "node:process";',
            "const { stdout } = process;",
            "const { stderr: erros } = process;",
            "const p = process; p.stdout.write(x)",
            "process.emitWarning(`cliente ${x}`)",
            "filho.stdout.on('data', f)",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [lint.STDOUT])

    def test_uma_expressao_regular_com_barras_nao_abre_comentario(self) -> None:
        """Achado A2: `/\\/*$/` apagava o resto do ficheiro."""
        barras = 'const limpo = x.replace(/\\/*$/, "");\nconsole.log(limpo);\nprocess.stdout.write(limpo);\n'
        self.assertEqual(lint.analisar_ts(barras), [(2, lint.CONSOLE), (3, lint.STDOUT)])
        duplas = "const limpo = x.replace(/\\/\\//g, '/'); console.log(limpo);"
        self.assertEqual(_regras_ts(duplas), [lint.CONSOLE])

    def test_bibliotecas_de_registo(self) -> None:
        """Primeira revisao: `pino` e o *middleware* `hono/logger` passavam."""
        for fonte in (
            'import pino from "pino";',
            "const pino = require('pino');",
            'import { logger } from "hono/logger";',
            'import winston from "winston";',
            'const m = await import("morgan");',
            'import pretty from "pino-pretty";',
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [lint.LOGGING])
        for fonte in ('import { Hono } from "hono";', 'import { instalar } from "@kamba/core-ts/logger";',
                      'const nome = "pinote";', 'import x from "hono/logger-de-outra-coisa";'):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [])

    def test_a_porta_sem_tipos_do_logger(self) -> None:
        for fonte in ('log.registar("info", [x], y)', "log . registar (a, b, c)", "this.log.registar(a)"):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [lint.REGISTAR])

    def test_nomes_parecidos_passam(self) -> None:
        for fonte in (
            "const consola = 1;",
            "const myconsole = 1;",
            "const console2 = 1;",
            "obj.consoleLog()",
            "const $console = 1;",
            "process.stdoutLivre",
            "const stdoutLivre = 1;",
            "obj.registarTudo()",
            "registar(x)",
            "process.env.HOST",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [])

    def test_comentarios_nao_contam(self) -> None:
        fonte = (
            "// console.log(x)\n"
            "/* process.stdout.write(x)\n   console.error(y) */\n"
            "const u = 'http://exemplo.invalid'; // console.log\n"
            "const v = 1; /** console.log */\n"
        )
        self.assertEqual(_regras_ts(fonte), [])

    def test_o_que_vem_depois_de_um_comentario_conta_e_a_linha_esta_certa(self) -> None:
        fonte = "/* um\n   comentario */\n// outro\nconsole.log(x);\nprocess.stdout.write(y);\n"
        self.assertEqual(lint.analisar_ts(fonte), [(4, lint.CONSOLE), (5, lint.STDOUT)])

    def test_uma_barra_dupla_dentro_de_uma_cadeia_nao_abre_comentario(self) -> None:
        for fonte in (
            'const u = "http://x"; console.log(u);',
            "const u = 'a//b'; console.log(u);",
            "const u = `a//b`; console.log(u);",
            'const u = "aspas \\" e // barras"; console.log(u);',
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_ts(fonte), [lint.CONSOLE])

    def test_dentro_de_uma_cadeia_e_reportado(self) -> None:
        """Falha para o lado seguro: nao se sabe se a cadeia vai ser avaliada."""
        self.assertEqual(_regras_ts('const s = "console.log(1)";'), [lint.CONSOLE])
        self.assertEqual(_regras_ts("const s = `${console.log(1)}`;"), [lint.CONSOLE])

    def test_um_comentario_por_fechar_nao_passa(self) -> None:
        self.assertEqual(
            lint.analisar_ts("console.log(1);\n/* por fechar\nconsole.log(2);"),
            [(1, lint.CONSOLE), (2, lint.ILEGIVEL)],
        )

    def test_uma_cadeia_por_fechar_acaba_na_linha(self) -> None:
        self.assertEqual(_regras_ts("const s = 'por fechar\n// comentario\nconsole.log(1);"), [lint.CONSOLE])


class TestPython(unittest.TestCase):
    def test_print_em_todas_as_formas(self) -> None:
        for fonte in (
            "print('x')",
            "escrever = print",
            "map(print, xs)",
            "from pprint import pprint",
            "import pprint",
            "pprint(x)",
            "def f():\n    print(x, file=y)",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [lint.PRINT])

    def test_logging(self) -> None:
        for fonte in (
            "import logging",
            "import logging.handlers",
            "import logging as registo",
            "from logging import getLogger",
            "from logging.config import dictConfig",
            "import os, logging",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [lint.LOGGING])

    def test_stdout_e_stderr(self) -> None:
        for fonte in (
            "import sys\nsys.stdout.write('x')",
            "import sys\nsys.stderr.write('x')",
            "import sys\nsaida = sys.__stdout__",
            "import sys\nsaida = sys.__stderr__",
            "from sys import stdout",
            "from sys import stderr as erros",
            "from sys import *",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [lint.STDOUT])

    def test_nomes_parecidos_passam(self) -> None:
        for fonte in (
            "imprimir = 1",
            "blueprint = 1",
            "x.print()",
            "import sys\nsys.argv",
            "from sys import argv",
            "import sys\nsys.exit(2)",
            "raise SystemExit(main())",
            "import sys\nsys.exit()",
            "registar(x)",
            "x.registar_tudo()",
            "from .logging import x",
            "import meu_logging",
            '"""print(x) e import logging numa docstring"""',
            "# print(x)",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [])

    def test_evasoes_por_descuido_da_revisao(self) -> None:
        """Achado A2: cada uma destas passava na primeira versao."""
        casos = (
            ("import sys as _sys\n_sys.stderr.write('x')", lint.STDOUT),
            ("processo.stdout.read()", lint.STDOUT),
            ("import traceback", lint.TRACEBACK),
            ("from traceback import print_exc", lint.TRACEBACK),
            ("import traceback as tb", lint.TRACEBACK),
            ("import sys\nsys.exit(f'PORT invalida: {porta}')", lint.SAIDA),
            ("import sys\nsys.exit('falhou')", lint.SAIDA),
            ("import sys\nsys.exit('a' + b)", lint.SAIDA),
            ("raise SystemExit(str(erro))", lint.SAIDA),
            ("raise SystemExit('{} falhou'.format(x))", lint.SAIDA),
            ("exit(repr(x))", lint.SAIDA),
            ("from loguru import logger", lint.LOGGING),
            ("import structlog", lint.LOGGING),
            ("log.registar('info', (), campos)", lint.REGISTAR),
        )
        for fonte, regra in casos:
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [regra])

    def test_uvicorn_sem_calar_o_registo_proprio(self) -> None:
        """Primeira revisao: tirar o `log_config=None` nao era visto por nada."""
        for fonte in (
            "import uvicorn\nuvicorn.run('a:app')",
            "import uvicorn\nuvicorn.run('a:app', host=h, port=p, access_log=False)",
            "import uvicorn\nuvicorn.run('a:app', log_config={'version': 1})",
            "import uvicorn\nuvicorn.run('a:app', log_config=config)",
            "import uvicorn\nc = uvicorn.Config('a:app')",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [lint.UVICORN])
        for fonte in (
            "import uvicorn\nuvicorn.run('a:app', log_config=None)",
            "import uvicorn\nc = uvicorn.Config('a:app', log_config=None, access_log=False)",
            "servidor.run('a:app')",
            "import uvicorn\nuvicorn.main()",
        ):
            with self.subTest(fonte=fonte):
                self.assertEqual(_regras_py(fonte), [])

    def test_o_que_nao_se_analisa_nao_passa(self) -> None:
        self.assertEqual(lint.analisar_py("def f(:\n    pass\n"), [(1, lint.ILEGIVEL)])
        self.assertEqual(lint.analisar_py("x = '\x00'"), [(1, lint.ILEGIVEL)])

    def test_a_linha_esta_certa_e_cada_regra_conta_uma_vez_por_linha(self) -> None:
        fonte = "import os\n\nimport logging\nprint(print)\n"
        self.assertEqual(lint.analisar_py(fonte), [(3, lint.LOGGING), (4, lint.PRINT)])


class TestCanario(unittest.TestCase):
    def test_o_canario_esta_verde(self) -> None:
        falhas, numeros = lint.canario(FIXTURES)
        self.assertEqual(falhas, [])
        self.assertEqual((numeros["negativas"], numeros["positivas"]), (29, 6))

    def test_uma_pasta_vazia_nao_passa(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            falhas, numeros = lint.canario(Path(pasta))
        self.assertEqual(numeros, {"negativas": 0, "positivas": 0})
        self.assertEqual(len(falhas), 14)

    def test_sem_a_negativa_de_uma_regra_o_canario_fica_vermelho(self) -> None:
        self.assertEqual(
            lint.REGRAS_OBRIGATORIAS,
            {
                "ts": ("console_directo", "stdout_directo", "logging_directo", "registar_directo",
                       "ficheiro_ilegivel"),
                "py": ("print_directo", "logging_directo", "stdout_directo", "traceback_directo",
                       "saida_com_texto", "registar_directo", "uvicorn_com_registo_proprio",
                       "ficheiro_ilegivel"),
            },
        )
        for regra in ("console_directo", "stdout_directo", "print_directo", "logging_directo",
                      "ficheiro_ilegivel", "traceback_directo", "saida_com_texto",
                      "registar_directo", "uvicorn_com_registo_proprio"):
            with self.subTest(regra=regra):
                with tempfile.TemporaryDirectory() as pasta:
                    copia = Path(pasta) / "lint"
                    shutil.copytree(FIXTURES, copia)
                    for ficheiro in (copia / "negativas").glob(f"{regra}__*"):
                        ficheiro.unlink()
                    falhas, _ = lint.canario(copia)
                self.assertTrue(any(f"`{regra}`" in falha for falha in falhas), falhas)

    def test_uma_negativa_que_deixa_de_morder_fica_vermelha(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            copia = Path(pasta) / "lint"
            shutil.copytree(FIXTURES, copia)
            (copia / "negativas" / "print_directo__print.py").write_text("x = 1\n", encoding="utf-8")
            (copia / "negativas" / "console_directo__log.ts").write_text(
                "process.stdout.write('x');\n", encoding="utf-8"
            )
            falhas, _ = lint.canario(copia)
        self.assertEqual(len(falhas), 2)
        self.assertIn("deu nada", falhas[0] + falhas[1])
        self.assertIn("stdout_directo", falhas[0] + falhas[1])

    def test_uma_positiva_que_morde_fica_vermelha(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            copia = Path(pasta) / "lint"
            shutil.copytree(FIXTURES, copia)
            (copia / "positivas" / "limpo.py").write_text("print('x')\n", encoding="utf-8")
            falhas, _ = lint.canario(copia)
        self.assertEqual(len(falhas), 1)
        self.assertIn("positivas/limpo.py", falhas[0])

    def test_ficheiros_que_nao_sao_codigo_nao_contam(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            copia = Path(pasta) / "lint"
            shutil.copytree(FIXTURES, copia)
            (copia / "negativas" / "LEIAME.md").write_text("x", encoding="utf-8")
            (copia / "positivas" / "LEIAME.md").write_text("x", encoding="utf-8")
            falhas, numeros = lint.canario(copia)
        self.assertEqual((falhas, numeros["negativas"], numeros["positivas"]), ([], 29, 6))


class _ComCopia(unittest.TestCase):
    """Uma copia do codigo de servico, para lhe por o defeito dentro."""

    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="log-policy-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        ignorar = shutil.ignore_patterns("node_modules", "dist", "__pycache__", ".venv", "*.egg-info")
        for topo in lint.RAIZES:
            shutil.copytree(ROOT / topo, self.raiz / topo, ignore=ignorar)

    def acrescentar(self, relativo: str, texto: str) -> int:
        caminho = self.raiz / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        antes = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
        caminho.write_bytes((antes + texto).encode("utf-8"))
        return antes.count("\n") + 1


class TestRepositorio(_ComCopia):
    def test_o_repositorio_real_passa_tendo_lido_os_servicos(self) -> None:
        achados, lidos = lint.verificar(ROOT)
        self.assertEqual([str(a) for a in achados], [])
        self.assertGreaterEqual(lidos["ts"], 21)
        self.assertGreaterEqual(lidos["py"], 15)
        self.assertGreaterEqual(lidos["isentos"], 5)

    def test_os_cinco_servicos_e_as_duas_bibliotecas_estao_no_ambito(self) -> None:
        relativos = {c.relative_to(ROOT).as_posix() for c in lint.ficheiros_em_ambito(ROOT)}
        for esperado in (
            "services/gwy/src/server.ts",
            "services/worker-canal/src/server.ts",
            "services/com/src/server.ts",
            "services/onboarding-web/src/server.ts",
            "services/agr/src/kamba_agr/__main__.py",
            "packages/core-ts/src/index.ts",
            "packages/contracts/src/index.ts",
            "libs/py-core/src/kamba_core/health.py",
            "libs/py-core/src/kamba_core/tenant_guard/__init__.py",
        ):
            self.assertIn(esperado, relativos)
        self.assertNotIn("packages/core-ts/tests/x11_conduzir.ts", relativos)
        for caminho in relativos:
            self.assertNotIn("/tests/", caminho)
            self.assertNotIn("node_modules", caminho)

    def test_um_console_log_num_servico_fica_vermelho(self) -> None:
        linha = self.acrescentar("services/gwy/src/app.ts", "console.log('pedido');\n")
        achados, _ = lint.verificar(self.raiz)
        self.assertEqual(
            [(a.ficheiro, a.linha, a.regra) for a in achados],
            [("services/gwy/src/app.ts", linha, lint.CONSOLE)],
        )
        self.assertIn("services/gwy/src/app.ts", str(achados[0]))
        self.assertIn("@kamba/core-ts/logger", str(achados[0]))

    def test_um_print_no_agr_fica_vermelho(self) -> None:
        linha = self.acrescentar("services/agr/src/kamba_agr/app.py", "print('pedido')\n")
        achados, _ = lint.verificar(self.raiz)
        self.assertEqual(
            [(a.ficheiro, a.linha, a.regra) for a in achados],
            [("services/agr/src/kamba_agr/app.py", linha, lint.PRINT)],
        )

    def test_cada_regra_em_cada_sitio_do_ambito(self) -> None:
        casos = (
            ("services/worker-canal/src/novo.ts", "process.stdout.write('x');\n", lint.STDOUT),
            ("packages/core-ts/src/secrets/novo.ts", "console.error('x');\n", lint.CONSOLE),
            ("packages/contracts/src/novo.mjs", "console.info('x');\n", lint.CONSOLE),
            ("libs/py-core/src/kamba_core/novo.py", "import logging\n", lint.LOGGING),
            ("libs/py-core/src/kamba_core/tenant_guard/novo.py", "import sys\nsys.stderr.write('x')\n", lint.STDOUT),
            ("services/agr/src/kamba_agr/partido.py", "def f(:\n", lint.ILEGIVEL),
            ("services/com/src/fundo/de/uma/pasta/novo.ts", "console.log(1)\n", lint.CONSOLE),
            # Fora de `src/`: corre no mesmo processo (achado A2 da revisao).
            ("services/gwy/arranque.ts", "console.log(1)\n", lint.CONSOLE),
            ("services/agr/gancho.py", "print(1)\n", lint.PRINT),
            ("services/gwy/scripts/novo.mjs", "process.stderr.write('x')\n", lint.STDOUT),
            ("libs/py-core/conftest.py", "import traceback\n", lint.TRACEBACK),
            ("services/agr/src/kamba_agr/sair.py", "raise SystemExit(str(1))\n", lint.SAIDA),
            ("services/gwy/src/porta.ts", "log.registar('info', [], x);\n", lint.REGISTAR),
        )
        for relativo, texto, regra in casos:
            with self.subTest(relativo=relativo):
                caminho = self.raiz / relativo
                self.acrescentar(relativo, texto)
                achados, _ = lint.verificar(self.raiz)
                self.assertEqual([(a.ficheiro, a.regra) for a in achados], [(relativo, regra)])
                caminho.unlink()

    def test_um_ficheiro_que_nao_e_utf8_nao_passa(self) -> None:
        caminho = self.raiz / "services/gwy/src/binario.ts"
        caminho.write_bytes(b"const x = '\xff\xfe';\n")
        achados, _ = lint.verificar(self.raiz)
        self.assertEqual([(a.ficheiro, a.regra) for a in achados], [("services/gwy/src/binario.ts", lint.ILEGIVEL)])

    def test_o_logger_e_a_unica_isencao(self) -> None:
        self.assertEqual(
            lint.ISENTOS,
            ("packages/core-ts/src/logger/", "libs/py-core/src/kamba_core/logger/"),
        )
        self.acrescentar("packages/core-ts/src/logger/index.ts", "console.log('x');\n")
        self.acrescentar("libs/py-core/src/kamba_core/logger/ponte.py", "print('x')\n")
        achados, _ = lint.verificar(self.raiz)
        self.assertEqual(achados, [])
        # Um directorio com um nome parecido nao herda a isencao.
        self.acrescentar("packages/core-ts/src/logger2/index.ts", "console.log('x');\n")
        achados, _ = lint.verificar(self.raiz)
        self.assertEqual([a.ficheiro for a in achados], ["packages/core-ts/src/logger2/index.ts"])

    def test_o_logger_real_escreve_mesmo_no_stdout(self) -> None:
        """A isencao existe porque e precisa: sem ela o lint apanhava o *logger*."""
        ts = (ROOT / "packages/core-ts/src/logger/index.ts").read_text(encoding="utf-8")
        py = (ROOT / "libs/py-core/src/kamba_core/logger/__init__.py").read_text(encoding="utf-8")
        self.assertIn(lint.STDOUT, [r for _, r in lint.analisar_ts(ts)])
        self.assertIn(lint.STDOUT, [r for _, r in lint.analisar_py(py)])

    def test_testes_dependencias_e_saidas_ficam_fora(self) -> None:
        for relativo in (
            "services/gwy/tests/novo.test.ts",
            "services/gwy/src/node_modules/pacote/index.js",
            "packages/core-ts/dist/index.js",
            "packages/core-ts/src/dist/index.js",
        ):
            self.acrescentar(relativo, "console.log('x');\n")
        achados, _ = lint.verificar(self.raiz)
        self.assertEqual(achados, [])

    def test_sem_o_logger_a_isencao_aponta_para_nada_e_e_erro(self) -> None:
        shutil.rmtree(self.raiz / "libs/py-core/src/kamba_core/logger")
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(self.raiz)

    def test_sem_codigo_de_uma_linguagem_nao_passa_em_silencio(self) -> None:
        shutil.rmtree(self.raiz / "services/agr")
        for caminho in (self.raiz / "libs/py-core/src/kamba_core").rglob("*.py"):
            if "logger" not in caminho.parts:
                caminho.unlink()
        with self.assertRaises(lint.ConfiguracaoInvalida):
            lint.verificar(self.raiz)


if __name__ == "__main__":
    unittest.main()
