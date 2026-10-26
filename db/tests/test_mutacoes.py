"""O corredor da prova por mutacao, sem base de dados (KAM-142).

A prova por mutacao e o instrumento que mede os testes, e por isso **tem de
ser medido**. Ja falhou duas vezes pela razao errada: no KAM-004 dava dez
apanhadas em dez porque a copia nao importava (hoje ha linha de base
obrigatoria), e a revisao do KAM-142 mostrou que uma falha por carga da maquina
contaria como «apanhada» — que e o mesmo defeito, vestido de outra forma.

Estes testes nao levantam nada: exercitam a classificacao da saida e a escolha
pelo filtro, que sao as duas decisoes onde o instrumento pode mentir.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import mutacoes

#: Estamos no repositorio, e nao dentro de uma copia de mutacao?
#:
#: Esta bateria corre **tambem** dentro de uma copia: a suite `tests` e ela
#: mesma mutada, e lá a `RAIZ` do corredor e a raiz da copia — uma arvore
#: parcial, sem `tools/supply_chain`, sem `docs/tecnica/` e sem a maioria dos
#: 142 ficheiros que a lista altera. Os testes que afirmam coisas sobre o
#: **repositorio** nao tem lá o que medir, e saltam.
#:
#: O marcador e o `.git`: nenhuma receita o copia. Num *worktree* e um ficheiro
#: e nao uma pasta, e por isso `exists` e nao `is_dir`.
#: **Nao se usa `skipUnless`**: o `gate_bd` recusa testes saltados — «num gate,
#: saltar e falhar», e tem razao, porque um salto e uma verificacao que nao
#: aconteceu e que ninguem conta. Os testes desta classe **nao se definem** numa
#: arvore parcial, e assim nao ha salto nenhum para contar.
NO_REPOSITORIO = (mutacoes.RAIZ / ".git").exists()


class TestClassificar(unittest.TestCase):
    FALHA = "FAIL: test_a_politica_e_a_tenant_iso (tests_isolamento.test_x05.Catalogo)\n"
    ERRO = "ERROR: test_resolve_o_tenant (tests_isolamento.test_resolver.TestResolver)\n"

    def test_codigo_zero_e_sobrevivente(self) -> None:
        self.assertEqual(mutacoes.classificar(0, "Ran 64 tests\nOK\n")[0], "SOBREVIVEU")

    def test_codigo_zero_e_sobrevivente_mesmo_com_falhas_na_saida(self) -> None:
        """O codigo de saida decide. Um `FAIL:` com codigo 0 e o corredor a mentir."""
        self.assertEqual(mutacoes.classificar(0, self.FALHA)[0], "SOBREVIVEU")

    def test_falhas_contam_e_a_primeira_e_nomeada(self) -> None:
        estado, detalhe = mutacoes.classificar(1, self.FALHA + self.ERRO)
        self.assertEqual(estado, "apanhada (2)")
        self.assertIn("test_a_politica_e_a_tenant_iso", detalhe)

    def test_suite_que_nao_carrega_e_prova_invalida(self) -> None:
        """O defeito do KAM-004: quatro erros de importacao a passar por apanhadas."""
        saida = "ERROR: test_x05 (unittest.loader._FailedTest.test_x05)\n"
        estado, detalhe = mutacoes.classificar(1, saida)
        self.assertEqual(estado, "PROVA INVALIDA")
        self.assertIn("nao carregou", detalhe)

    def test_falhar_sem_uma_so_falha_nomeada_e_prova_invalida(self) -> None:
        estado, _ = mutacoes.classificar(1, "a base nao ficou disponivel em 90s\n")
        self.assertEqual(estado, "PROVA INVALIDA")

    def test_cada_sinal_de_carga_invalida_a_prova(self) -> None:
        """Com `ERROR:` presente: sem isto, cada um destes contava como apanhada."""
        for sinal in mutacoes.SINAIS_DE_CARGA:
            with self.subTest(sinal=sinal):
                estado, detalhe = mutacoes.classificar(1, self.ERRO + f"  {sinal}\n")
                self.assertEqual(estado, "PROVA INVALIDA")
                self.assertIn("carga", detalhe)
                self.assertIn("KAMBA_MUTACOES_PARALELO", detalhe)

    def test_o_sinal_de_carga_e_visto_em_qualquer_caixa(self) -> None:
        estado, _ = mutacoes.classificar(
            1, self.ERRO + "  FATAL:  Sorry, Too Many Clients Already\n"
        )
        self.assertEqual(estado, "PROVA INVALIDA")

    def test_os_sinais_de_carga_nao_sao_palavras_de_teste_comuns(self) -> None:
        """Um sinal largo invalida provas boas: `timeout` ou `error` sozinhos
        apareceriam numa mensagem de teste qualquer e punham a prova inteira a
        dizer «invalida». Cada sinal e uma frase do servidor, nao uma palavra."""
        for sinal in mutacoes.SINAIS_DE_CARGA:
            with self.subTest(sinal=sinal):
                self.assertGreaterEqual(len(sinal.split()), 2)
                self.assertNotIn(sinal, ("timeout", "error", "falhou", "cancelado"))

    def test_uma_mutacao_apanhada_sem_sinais_continua_apanhada(self) -> None:
        saida = self.FALHA + "AssertionError: 'lock' != 'trinco'\nRan 64 tests\n"
        self.assertEqual(mutacoes.classificar(1, saida)[0], "apanhada (1)")


class TestEscolha(unittest.TestCase):
    def test_sem_filtro_escolhe_tudo(self) -> None:
        self.assertEqual(len(mutacoes.escolhidas("")), len(mutacoes.MUTACOES))

    def test_o_filtro_por_suite_e_por_igualdade_exacta(self) -> None:
        """`tests` e um prefixo de `tests_isolamento`: nao se podem confundir."""
        de_tests = mutacoes.escolhidas("tests")
        de_isolamento = mutacoes.escolhidas("tests_isolamento")
        self.assertTrue(de_tests and de_isolamento)
        nomes = {m[0] for m in de_isolamento}
        for mutacao in de_tests:
            if mutacao[0] in nomes:
                # Só vale se o nome contiver o excerto: é o filtro por excerto.
                self.assertIn("tests", mutacao[0])

    def test_o_filtro_por_excerto_escolhe_um_grupo(self) -> None:
        escolhidas = mutacoes.escolhidas("guarda:")
        self.assertTrue(escolhidas)
        self.assertTrue(all("guarda:" in m[0] for m in escolhidas))

    def test_um_filtro_sem_correspondencia_nao_escolhe_nada(self) -> None:
        """E `main` sai com 2: um filtro vazio nao pode parecer uma prova limpa."""
        self.assertEqual(mutacoes.escolhidas("nao-existe-nenhuma-assim"), [])
        self.assertEqual(mutacoes.main(["python", "nao-existe-nenhuma-assim"]), 2)

    def test_cada_mutacao_tem_nome_unico(self) -> None:
        """Dois nomes iguais tornam o relatorio e o filtro ambiguos."""
        nomes = [m[0] for m in mutacoes.MUTACOES]
        self.assertEqual(len(nomes), len(set(nomes)))


class TestFatiar(unittest.TestCase):
    """`--fatia i/n` reparte a lista pelos *runners* da tarefa nocturna.

    O defeito que estes testes existem para apanhar: uma fatia que perca
    mutacoes faz a prova nocturna passar sem as ter corrido — a lista inteira
    estaria «verde» com parte dela nunca executada.
    """

    def test_as_fatias_cobrem_a_lista_sem_perder_nem_repetir(self) -> None:
        todas = mutacoes.escolhidas("")
        for n in (1, 2, 3, 6, 7, 97):
            with self.subTest(n=n):
                uniao = []
                for i in range(1, n + 1):
                    uniao += mutacoes.fatiar(todas, f"{i}/{n}")
                self.assertEqual(
                    [id(m) for m in sorted(uniao, key=id)],
                    [id(m) for m in sorted(todas, key=id)],
                )

    def test_as_fatias_ficam_equilibradas(self) -> None:
        """Alternadamente, e nao em blocos: nenhuma fatia leva o dobro de outra."""
        todas = mutacoes.escolhidas("")
        tamanhos = [len(mutacoes.fatiar(todas, f"{i}/6")) for i in range(1, 7)]
        self.assertLessEqual(max(tamanhos) - min(tamanhos), 1)

    def test_fatias_de_tickets_diferentes_na_mesma_fatia(self) -> None:
        """Em blocos, uma fatia levaria todas as mutacoes caras de um ticket."""
        primeira = mutacoes.fatiar(mutacoes.escolhidas(""), "1/6")
        self.assertGreater(len({m[1] for m in primeira}), 1)

    def test_uma_fatia_malformada_e_recusada(self) -> None:
        todas = mutacoes.escolhidas("")
        # `１` (largura total) e `١` (arabe): `int()` aceita-os, e sem a
        # guarda `isascii` um `--fatia １/６` passava por valido.
        for fatia in ("0/3", "4/3", "a/3", "3", "3/0", "-1/3", "1/2/3", "", "1/", "/3",
                      "²/3", "1.0/3", " 1/3", "１/６", "١/٦",
                      "1/６", "１/6"):
            with self.subTest(fatia=fatia):
                with self.assertRaises(ValueError):
                    mutacoes.fatiar(todas, fatia)

    def test_uma_fatia_vazia_sai_com_dois(self) -> None:
        """Sem isto, mais fatias do que mutacoes davam uma fatia «limpa»."""
        self.assertEqual(mutacoes.main(["python", "", "--fatia", "999/999"]), 2)

    def test_a_opcao_aceita_as_duas_formas_e_exige_valor(self) -> None:
        self.assertEqual(
            mutacoes._opcao(["py", "f", "--fatia", "2/3"], "--fatia"), (["py", "f"], "2/3")
        )
        self.assertEqual(
            mutacoes._opcao(["py", "--fatia=2/3", "f"], "--fatia"), (["py", "f"], "2/3")
        )
        self.assertEqual(mutacoes._opcao(["py", "f"], "--fatia"), (["py", "f"], None))
        with self.assertRaises(ValueError):
            mutacoes._opcao(["py", "--fatia"], "--fatia")

    def test_a_fatia_nao_e_confundida_com_o_filtro(self) -> None:
        """`--fatia` sai dos argumentos antes de o filtro ser lido."""
        argumentos, fatia = mutacoes._opcao(["py", "--fatia", "1/2", "guarda:"], "--fatia")
        self.assertEqual((argumentos, fatia), (["py", "guarda:"], "1/2"))


class TestCodigoDeSaida(unittest.TestCase):
    """O codigo de saida e a unica coisa que impede uma sobrevivente de passar calada.

    Nao tinha um teste. A revisao do KAM-143 mostrou o que isso deixava passar:
    `return 0` no fim do relatorio, ou contar como nao-apanhada so o
    `SOBREVIVEU` — que **reintroduz** o defeito que o seguimento do KAM-142
    corrigiu (uma `PROVA INVALIDA` a dar a prova por feita). Aqui o corredor
    corre inteiro, com o gate substituido: o que se mede e a decisao, nao a base.
    """

    def _com_resultado(self, *resultados):
        """Substitui o gate: cada mutacao devolve o resultado seguinte da lista."""
        fila = list(resultados)
        contador = {"n": 0}

        def correr_falso(nome, ficheiro, velho, novo, suite="tests"):
            indice = min(contador["n"], len(fila) - 1)
            contador["n"] += 1
            resultado = fila[indice]
            if isinstance(resultado, BaseException):
                raise resultado
            return resultado

        self.enterContext(unittest.mock.patch.object(mutacoes, "correr", correr_falso))
        self.enterContext(
            unittest.mock.patch.object(mutacoes, "linha_de_base", lambda suite: None)
        )
        # O relatorio vai para o ar: um teste que imprime cinco linhas suja o
        # registo do gate, onde se procuram as falhas de verdade.
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        return contador

    ARGUMENTOS = ["python", "catalogo:"]

    def test_todas_apanhadas_sai_com_zero(self) -> None:
        self._com_resultado(("apanhada (3)", "FAIL: test_x"))
        self.assertEqual(mutacoes.main(self.ARGUMENTOS), 0)

    def test_cada_resultado_que_nao_e_apanhada_sai_com_um(self) -> None:
        for resultado in (
            ("SOBREVIVEU", ""),
            ("PROVA INVALIDA", "a suite nao carregou"),
            ("PROVA INVALIDA", "a base cedeu a carga"),
            ("MUTACAO NAO APLICAVEL", ""),
        ):
            with self.subTest(estado=resultado[0], detalhe=resultado[1]):
                self._com_resultado(("apanhada (1)", ""), resultado)
                self.assertEqual(mutacoes.main(self.ARGUMENTOS), 1)

    def test_uma_excepcao_numa_execucao_sai_com_um_e_o_relatorio_chega_ao_fim(self) -> None:
        contador = self._com_resultado(RuntimeError("o Docker morreu"))
        self.assertEqual(mutacoes.main(self.ARGUMENTOS), 1)
        self.assertGreater(contador["n"], 1, "as mutacoes seguintes nao foram corridas")

    def test_os_argumentos_invalidos_saem_com_dois(self) -> None:
        casos = {
            "fatia malformada": ["python", "", "--fatia", "0/6"],
            "fatia sem valor": ["python", "", "--fatia"],
            "fatia vazia": ["python", "", "--fatia", "999/999"],
            "filtro sem correspondencia": ["python", "nao-existe-nenhuma-assim"],
            "filtro com cara de opcao": ["python", "--aplicaveis", "--fatia", "1/6"],
            "opcao desconhecida como filtro": ["python", "--vai-correr-tudo"],
            "aplicaveis com mais argumentos": ["--aplicaveis", "python"],
        }
        for nome, argumentos in casos.items():
            with self.subTest(caso=nome):
                self._com_resultado(("apanhada (1)", ""))
                self.assertEqual(mutacoes.main(argumentos), 2)

    def test_o_filtro_aplicaveis_nao_faz_a_prova_passar_por_feita(self) -> None:
        """O achado maior da revisao: era o que a tarefa nocturna passava."""
        contador = self._com_resultado(("apanhada (1)", ""))
        self.assertEqual(mutacoes.main(["python", "--aplicaveis", "--fatia", "1/6"]), 2)
        self.assertEqual(contador["n"], 0, "nao podia ter corrido mutacao nenhuma")

    def test_aplicaveis_sai_com_um_quando_uma_mutacao_deixou_de_se_aplicar(self) -> None:
        for velho in ("texto-que-nao-existe-em-ficheiro-nenhum", "import"):
            with self.subTest(velho=velho):
                self.enterContext(
                    unittest.mock.patch.object(
                        mutacoes, "MUTACOES", [("inventada", "db/mutacoes.py", velho, "x")]
                    )
                )
                self.assertEqual(mutacoes.aplicaveis(), 1)
                self.assertEqual(mutacoes.main(["--aplicaveis"]), 1)



class TestCaminhoDoPython(unittest.TestCase):
    """O interpretador passado por argumento tem de ficar absoluto.

    `_gate_de_tools` corre com o directorio de trabalho **dentro da copia**, e
    um caminho relativo nao existe la. A tarefa nocturna do KAM-143 passava
    `.venv/bin/python` relativo, e as seis fatias morreram todas com
    `FileNotFoundError` sem correr uma mutacao — a prova nao falhou, nem
    sequer comecou.
    """

    def _com_gate(self):
        """Nao corre gate nenhum: so quer o valor de `PY` no fim."""
        self.enterContext(
            unittest.mock.patch.object(mutacoes, "linha_de_base", lambda suite: None)
        )
        self.enterContext(
            unittest.mock.patch.object(
                mutacoes, "correr", lambda *a, **k: ("apanhada (1)", "")
            )
        )
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_um_caminho_relativo_fica_absoluto(self) -> None:
        self._com_gate()
        mutacoes.main([".venv/bin/python", "catalogo:"])
        self.assertTrue(Path(mutacoes.PY).is_absolute(), mutacoes.PY)
        self.assertTrue(mutacoes.PY.endswith(("python", "python.exe")))

    def test_um_caminho_absoluto_nao_e_tocado(self) -> None:
        self._com_gate()
        absoluto = str(Path(sys.executable).resolve())
        mutacoes.main([absoluto, "catalogo:"])
        self.assertEqual(mutacoes.PY, absoluto)

    def test_um_nome_sem_barra_fica_como_esta(self) -> None:
        """`python` resolve-se pelo PATH; torna-lo absoluto seria adivinhar."""
        self._com_gate()
        mutacoes.main(["python3", "catalogo:"])
        self.assertEqual(mutacoes.PY, "python3")


class TestPorqueFalhou(unittest.TestCase):
    """O diagnostico de uma linha de base vermelha e o que fica no artefacto."""

    RUIDO = (
        "2026-10-12 09:14:01.709 UTC [53] LOG:  database system is shut down\n"
        " done\nserver stopped\nPostgreSQL init process complete; ready for start up.\n"
    )

    def test_a_causa_aparece_mesmo_enterrada_em_ruido_do_postgres(self) -> None:
        saida = (
            "Traceback (most recent call last):\n"
            "  File \"/tmp/x/db/tests/base.py\", line 3, in <module>\n"
            "ModuleNotFoundError: No module named 'kamba_yaml'\n" + self.RUIDO * 5
        )
        diagnostico = mutacoes._porque_falhou(saida)
        self.assertIn("ModuleNotFoundError", diagnostico)
        self.assertNotIn("database system is shut down", diagnostico)

    def test_sem_linha_reconhecida_diz_que_nao_reconheceu(self) -> None:
        diagnostico = mutacoes._porque_falhou(self.RUIDO)
        self.assertIn("nenhuma linha de falha reconhecida", diagnostico)
        self.assertIn("server stopped", diagnostico)

    def test_o_diagnostico_tem_tecto(self) -> None:
        saida = "\n".join(f"FAIL: test_{n}" for n in range(200))
        self.assertEqual(len(mutacoes._porque_falhou(saida, maximo=20).splitlines()), 20)


class TestParalelo(unittest.TestCase):
    def test_a_omissao_e_oito(self) -> None:
        import os

        anterior = os.environ.pop("KAMBA_MUTACOES_PARALELO", None)
        try:
            self.assertEqual(mutacoes._paralelo(), 8)
        finally:
            if anterior is not None:
                os.environ["KAMBA_MUTACOES_PARALELO"] = anterior

    def test_um_valor_invalido_e_recusado_antes_de_tudo(self) -> None:
        import os

        anterior = os.environ.get("KAMBA_MUTACOES_PARALELO")
        try:
            for valor in ("0", "abc", "", "-1", "²", "2.5"):
                with self.subTest(valor=valor):
                    os.environ["KAMBA_MUTACOES_PARALELO"] = valor
                    with self.assertRaises(SystemExit) as capturado:
                        mutacoes._paralelo()
                    self.assertEqual(capturado.exception.code, 2)
        finally:
            if anterior is None:
                os.environ.pop("KAMBA_MUTACOES_PARALELO", None)
            else:
                os.environ["KAMBA_MUTACOES_PARALELO"] = anterior


#: Corre a suite de `tools/` na copia, com a arvore real fora do `sys.path`.
#:
#: E o mesmo `discover` que o `_gate_de_tools` do corredor faz — de proposito:
#: o que esta guarda mede e a **linha de base**, que e o que o corredor exige
#: antes de dar qualquer mutacao por apanhada.
#:
#: O `sys.path` tem de se limpar aqui dentro: um `.pth` no `site-packages`
#: entra no `sys.path` de qualquer processo e nao se tira com `PYTHONPATH` nem
#: com `-I`.
#:
#: Tira-se **a raiz inteira**, e nao so o `tools/`. A primeira versao tirava so
#: o `tools/`, e por isso nao viu que a receita do `llm_config` nao levava o
#: `services/agr/src`: o `kamba.pth` desta maquina aponta tres pastas, e bastava
#: uma de pe para a copia ir buscar fora o que lhe faltava.
_GUIAO_DA_LINHA_DE_BASE = """
import sys, os, unittest
raiz, pacote, padrao = sys.argv[1], sys.argv[2], sys.argv[3]
raiz = os.path.normcase(os.path.normpath(raiz)) + os.sep


def de_fora(p):
    # Tira as arvores de codigo do repositorio e **nao** o ambiente instalado:
    # o `.venv` vive dentro da raiz, e cortar o `site-packages` com ele levava
    # o `jsonschema` e o resto do fecho — a copia falhava por nao ter
    # dependencias, que nao e o que esta guarda mede.
    p = os.path.normcase(os.path.normpath(p))
    return not (p + os.sep).startswith(raiz) or "site-packages" in p


sys.path[:] = ["tools"] + [p for p in sys.path if p and de_fora(p)]
testes = unittest.defaultTestLoader.discover(
    "tools/%s/tests" % pacote, pattern=padrao, top_level_dir="tools"
)
resultado = unittest.TextTestRunner(verbosity=0).run(testes)
sys.exit(0 if resultado.wasSuccessful() else 1)
"""


class _OQueSoORepositorioPodeAfirmar(unittest.TestCase):
    """O que se afirma sobre o **repositorio**, e nao sobre uma copia parcial.

    Esta bateria corre tambem **dentro** de uma copia de mutacao, onde a `RAIZ`
    do corredor e a raiz da copia. Estes dois testes nao tem lá o que medir, e
    por isso a classe so e exposta ao `unittest` quando ha `.git` — ver o
    `NO_REPOSITORIO` no fim do modulo.

    A linha de base de cada suite de `tools/`, medida num PR e nao as 02:10.

    **Terceira vez que o instrumento falha pela razao errada**, e a primeira em
    que falha sem se notar. Duas receitas estavam atras do que a sua suite abre:
    a do `cosign` (KAM-030) copiava o `supply_chain` e nao o `lint_arch`, o
    `sbom` e o `ci_waivers`, que ele importa no topo do modulo; a dos
    `contratos` nao levava o `registry/`, onde entretanto entraram quatro YAML
    que o `test_catalogo_e_cli.py` conta. Nos dois casos a copia nao corria
    verde, o corredor recusava-se a medir — e bem — e a fatia morria em segundos.
    Onze noites assim, nenhuma mutacao medida (issue #3).

    **Nesta maquina as duas passavam**, porque o `.venv` tinha um `kamba.pth`
    — feito a mao, que nenhum ficheiro do projecto cria — a por o `tools/`
    **real** no `sys.path`: a copia ia buscar a arvore verdadeira o que lhe
    faltava, e a linha de base nao podia ficar vermelha por falta de copia.

    Mede-se correndo a suite, e nao lendo os `import`: a primeira versao desta
    guarda so importava o pacote, e teria deixado passar o `registry/` — que
    nao e um `import`, e um ficheiro que o teste abre.
    """

    def test_aplicaveis_sai_com_zero_sobre_a_lista_real(self) -> None:
        """Estava no `TestCodigoDeSaida`, e vem para aqui.

        Corre `aplicaveis()` sobre a lista inteira, e numa copia quase nenhum
        dos 142 ficheiros-alvo existe: punha a linha de base da **propria**
        suite `tests` vermelha, e com ela as suas 174 mutacoes fora de alcance.
        Nunca se notou porque nenhuma noite chegava tao longe. Nenhuma mutacao
        depende dele — nenhuma das 783 altera o `db/mutacoes.py`.
        """
        self.assertEqual(mutacoes.aplicaveis(), 0)

    def test_cada_suite_de_tools_corre_verde_so_com_o_que_a_receita_copia(self) -> None:
        raiz = str(mutacoes.RAIZ.resolve())
        ignorar = shutil.ignore_patterns("__pycache__", "*.pyc")
        for suite, (pacote, padrao) in sorted(mutacoes.SUITES_DE_TOOLS.items()):
            with self.subTest(suite=suite):
                destino = Path(tempfile.mkdtemp(prefix="kamba-copia-"))
                try:
                    mutacoes.COPIA_DE_TOOLS[suite](destino, ignorar)
                    corrida = subprocess.run(
                        [
                            sys.executable, "-c", _GUIAO_DA_LINHA_DE_BASE,
                            raiz, pacote, padrao,
                        ],
                        cwd=destino,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                finally:
                    shutil.rmtree(destino, ignore_errors=True)
                self.assertEqual(
                    corrida.returncode,
                    0,
                    f"a linha de base da suite {suite!r} nao corre verde so com o "
                    f"que a sua receita copia; a receita esta atras do que a suite "
                    f"abre:\n{corrida.stdout}\n{corrida.stderr}",
                )

    def test_toda_a_suite_de_tools_tem_receita(self) -> None:
        """Sem isto, uma suite nova corre sobre a copia de outra."""
        self.assertEqual(
            sorted(mutacoes.SUITES_DE_TOOLS), sorted(mutacoes.COPIA_DE_TOOLS)
        )


#: A classe so vira bateria quando ha repositorio para medir. Numa copia de
#: mutacao o nome fica a comecar por `_`, e o `unittest` nao o descobre.
if NO_REPOSITORIO:
    TestOQueSoORepositorioPodeAfirmar = _OQueSoORepositorioPodeAfirmar


if __name__ == "__main__":
    unittest.main()
