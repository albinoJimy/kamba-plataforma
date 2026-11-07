"""O corredor: a ordem que produz, e o estado que registra."""

from __future__ import annotations

import unittest
from pathlib import Path

from ordem_dos_ensaios import canario, corredor

FIXTURES = canario.FIXTURES


class _Falso(unittest.TestCase):
    """Casos descartaveis, para exercitar `achatar` e `ordenar`."""

    def test_a(self) -> None:
        pass

    def test_b(self) -> None:
        pass


class TestAchatar(unittest.TestCase):
    def test_achata_suites_encaixadas(self) -> None:
        interior = unittest.TestSuite([_Falso('test_a'), _Falso('test_b')])
        exterior = unittest.TestSuite([interior, _Falso('test_a')])
        self.assertEqual(len(list(corredor.achatar(exterior))), 3)

    def test_uma_suite_vazia_da_lista_vazia(self) -> None:
        self.assertEqual(list(corredor.achatar(unittest.TestSuite())), [])


class TestOrdenar(unittest.TestCase):
    def setUp(self) -> None:
        self.testes = [_Falso('test_a'), _Falso('test_b')]

    def test_normal_preserva(self) -> None:
        self.assertEqual(
            [t.id() for t in corredor.ordenar(self.testes, 'normal')],
            [t.id() for t in self.testes],
        )

    def test_normal_devolve_uma_lista_nova(self) -> None:
        """Ordenar nao pode mutar a lista de quem chama."""
        ordenados = corredor.ordenar(self.testes, 'normal')
        ordenados.clear()
        self.assertEqual(len(self.testes), 2)

    def test_inversa_inverte(self) -> None:
        self.assertEqual(
            [t.id() for t in corredor.ordenar(self.testes, 'inversa')],
            [t.id() for t in reversed(self.testes)],
        )

    def test_uma_ordem_desconhecida_levanta(self) -> None:
        """Nunca cair na ordem de omissao em silencio: isso media outra coisa."""
        with self.assertRaises(ValueError):
            corredor.ordenar(self.testes, 'embaralhada')

    def test_as_ordens_declaradas_sao_as_aceitas(self) -> None:
        for ordem in corredor.ORDENS:
            corredor.ordenar(self.testes, ordem)


class TestCorrerAFixtureDependente(unittest.TestCase):
    """A *fixture* que morde, corrida **neste** processo.

    Aqui as duas ordens correm no mesmo processo, e e por isso que estes casos
    sao sobre a *fixture* e nao sobre a propriedade: o `cli` e que corre cada
    ordem no seu, que e a unica forma de a medir. Ver o `corredor`.
    """

    def correr(self, pasta: str, ordem: str) -> corredor.Resultado:
        caminho = str(FIXTURES / pasta)
        return corredor.correr(caminho, caminho, canario.PADRAO, ordem)

    def test_descobre_os_dois_casos(self) -> None:
        self.assertEqual(self.correr('dependente', 'normal').corridos, 2)

    def test_a_ordem_normal_poe_a_leitura_primeiro(self) -> None:
        caminho = str(FIXTURES / 'dependente')
        suite = unittest.defaultTestLoader.discover(
            start_dir=caminho, pattern=canario.PADRAO, top_level_dir=caminho
        )
        nomes = [t.id() for t in corredor.achatar(suite)]
        self.assertLess(
            nomes.index('caso_registo.TestALeitura.test_o_registo_comeca_vazio'),
            nomes.index(
                'caso_registo.TestZEscrita.test_escreve_no_registo_e_nao_o_repoe'
            ),
            'a ordem de omissao do unittest deixou de ser alfabetica; a fixture '
            'deste canario depende disso',
        )

    def test_a_fixture_independente_nao_tem_vermelhos(self) -> None:
        self.assertEqual(self.correr('independente', 'inversa').vermelhos(), [])


class TestOsSinaisDoUnittest(unittest.TestCase):
    """Cada sinal do `unittest`, passado **atraves** do `Registo`.

    E o caso que faltava, e a sua ausencia e a razao pela qual o buraco do
    `addSubTest` escapou: nenhum teste deste modulo produzia um vermelho pelo
    caminho real. Os que havia corriam combinacoes verdes ou construiam um
    `Resultado` a mao, pelo que um `hook` em falta nao dava erro — dava um
    teste classificado `ok` que tinha falhado.
    """

    @classmethod
    def setUpClass(cls) -> None:
        caminho = str(FIXTURES / 'sinais')
        cls.resultado = corredor.correr(
            caminho, caminho, canario.PADRAO, 'normal'
        )

    def estado(self, sufixo: str) -> str:
        casa = [i for i in self.resultado.estado if i.endswith(sufixo)]
        self.assertEqual(len(casa), 1, f'{sufixo}: {casa}')
        return self.resultado.estado[casa[0]]

    def test_classifica_os_sete_sinais(self) -> None:
        self.assertEqual(self.estado('TestOk.test_passa'), 'ok')
        self.assertEqual(self.estado('TestFalha.test_falha'), 'failure')
        self.assertEqual(self.estado('TestErro.test_erro'), 'error')
        self.assertEqual(self.estado('TestSaltado.test_saltado'), 'skip')
        self.assertEqual(
            self.estado('TestFalhaEsperada.test_falha_esperada'),
            'expected-failure',
        )
        self.assertEqual(
            self.estado('TestSucessoInesperado.test_sucesso_inesperado'),
            'unexpected-success',
        )

    def test_uma_falha_dentro_de_subtest_nao_fica_ok(self) -> None:
        """O buraco medido: o `unittest` entrega isto a `addSubTest`, e sem ele
        derrubado o teste saia `ok` com a suite a dizer `FAILED`."""
        self.assertEqual(
            self.estado('TestSubTest.test_falha_dentro_de_subtest'),
            'subtest-failure',
        )
        self.assertIn('FALHA (subTest)', self.resultado.relato)

    def test_o_veredicto_vem_do_testresult_e_nao_do_dicionario(self) -> None:
        """`sucesso` e `corridos` sao do `TestResult`, nao do `estado`."""
        self.assertFalse(self.resultado.sucesso)
        self.assertEqual(self.resultado.corridos, 7)
        self.assertEqual(len(self.resultado.estado), 7)

    def test_o_relato_leva_o_traceback_e_nao_a_cadeia_de_pontos(self) -> None:
        """A primeira versao devolvia `'.F'`: o `printErrors` so e chamado pelo
        `TextTestRunner`, que este corredor nao usa."""
        self.assertIn('Traceback', self.resultado.relato)
        self.assertIn('vermelho de proposito', self.resultado.relato)
        self.assertIn('erro de proposito', self.resultado.relato)
        self.assertNotEqual(self.resultado.relato.strip(), '.F')


class TestRegisto(unittest.TestCase):
    def test_classifica_cada_estado(self) -> None:
        caminho = str(FIXTURES / 'independente')
        resultado = corredor.correr(
            caminho, caminho, canario.PADRAO, 'normal'
        )
        self.assertEqual(set(resultado.estado.values()), {'ok'})

    def test_vermelhos_ignora_os_estados_verdes(self) -> None:
        resultado = corredor.Resultado(
            estado={
                'a': 'ok',
                'b': 'skip',
                'c': 'expected-failure',
                'd': 'failure',
            },
            corridos=4,
            sucesso=False,
            relato='',
        )
        self.assertEqual(resultado.vermelhos(), ['d'])

    def test_um_sucesso_inesperado_conta_como_vermelho(self) -> None:
        """`unexpected-success` e um `expectedFailure` que passou: o teste
        deixou de medir o que diz medir."""
        resultado = corredor.Resultado(
            estado={'a': 'unexpected-success'},
            corridos=1,
            sucesso=False,
            relato='',
        )
        self.assertEqual(resultado.vermelhos(), ['a'])


class TestAcusacoes(unittest.TestCase):
    """O lado do `TestResult`, que o dicionario nao perde (KAM-182).

    Sao os ensaios da metade que faltava a rede: quando o `wasSuccessful()` e o
    `estado` discordam, e daqui que sai o nome. Correm pelo caminho real — por
    `correr` sobre as *fixtures* — e nao por um `TestResult` montado a mao, pela
    mesma razao que levou a *fixture* `sinais/` a existir: um `hook` em falta
    nao da erro num duplo, da um teste classificado `ok` que falhou.
    """

    def correr(self, pasta: str, ordem: str = 'normal') -> corredor.Resultado:
        caminho = str(FIXTURES / pasta)
        return corredor.correr(caminho, caminho, canario.PADRAO, ordem)

    def test_com_os_sinais_todos_derrubados_os_dois_lados_concordam(
        self,
    ) -> None:
        """A condicao de base: sem buraco, `acusados` e `vermelhos()` sao iguais.

        E o caso que da sentido a diferenca. Se eles divergissem numa suite
        saudavel, qualquer divergencia deixava de nomear hipotese nenhuma — e a
        saida do ramo da discordancia passava a apontar sempre para a hipotese
        1, que e um diagnostico constante e portanto nenhum.
        """
        resultado = self.correr('sinais')
        self.assertEqual(list(resultado.acusados), resultado.vermelhos())
        self.assertEqual(resultado.sem_caso, ())

    def test_um_subtest_vermelho_dobra_no_caso_pai(self) -> None:
        """O `id()` do sub-caso nunca passa pelo `startTest`.

        Sem a dobra, um `subTest` vermelho aparecia como um `id()` que o
        `Registo` nunca viu — a hipotese 1 — quando o `addSubTest` esta
        derrubado e classificou o pai. Era um diagnostico falso sobre os 332
        usos de `subTest` que o KAM-173 contou.
        """
        acusados = self.correr('sinais').acusados
        self.assertIn(
            'caso_todos_os_sinais.TestSubTest.test_falha_dentro_de_subtest',
            acusados,
        )
        self.assertEqual([i for i in acusados if '[' in i], [])

    def test_um_sucesso_inesperado_e_acusado(self) -> None:
        """O `wasSuccessful()` conta-o, logo tem de poder ser nomeado."""
        self.assertIn(
            'caso_todos_os_sinais.TestSucessoInesperado.'
            'test_sucesso_inesperado',
            self.correr('sinais').acusados,
        )

    def test_um_erro_de_teardown_de_modulo_nao_e_um_id_de_teste(self) -> None:
        """O `_ErrorHolder` sai pelo `sem_caso`, e **nao** pelo `estado`.

        Ate ao KAM-182 a frase `tearDownModule (modulo)` entrava no `estado`
        como se fosse um teste vermelho: o portao dava-a por «vermelho nas duas
        ordens» e mandava procurar no `coverage-python` um caso que nao existe.
        O erro nao se perde — esta no `wasSuccessful()`, no `relato` e aqui.
        """
        resultado = self.correr('sem_caso')
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.vermelhos(), [])
        self.assertEqual(resultado.acusados, ())
        self.assertEqual(resultado.sem_caso, ('tearDownModule (caso_sem_caso)',))
        self.assertIn('tearDownModule vermelho de proposito', resultado.relato)

    def test_um_sinal_por_derrubar_fica_fora_do_estado_e_dentro_do_acusa(
        self,
    ) -> None:
        """A hipotese 1, medida nos dois lados ao mesmo tempo."""
        resultado = self.correr('sem_derrubar')
        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.vermelhos(), [])
        self.assertEqual(len(resultado.acusados), 1)
        self.assertNotIn(resultado.acusados[0], resultado.estado)

    def test_o_id_repetido_colapsa_o_estado_e_nao_o_testsRun(self) -> None:
        """A hipotese 2 e a diferenca entre os dois numeros, e so ela.

        No exemplar de 2026-11-05 eles eram 1402 e 1402, e e assim que esta
        hipotese fica excluida la sem ser por preferencia.
        """
        resultado = self.correr('id_repetido')
        self.assertEqual(resultado.corridos, 3)
        self.assertEqual(len(resultado.estado), 1)
        self.assertEqual(resultado.vermelhos(), [])
        self.assertEqual(
            resultado.acusados,
            ('caso_id_repetido.TestColapso.test_o_mesmo_id',),
        )


class TestAsFixturesNaoEntramNaSuiteDeTools(unittest.TestCase):
    """O padrao `test*.py` do `coverage-python` nao pode apanhar as *fixtures*.

    A *fixture* `dependente/` e vermelha de proposito. Descoberta pela suite de
    `tools/`, fazia o *gate* 4 vermelho por desenho — e a unica coisa que o
    impede e o nome dos ficheiros.
    """

    def test_nenhuma_fixture_casa_o_padrao_das_suites(self) -> None:
        from ordem_dos_ensaios.cli import PADRAO_PADRAO

        self.assertEqual(PADRAO_PADRAO, 'test*.py')
        for ficheiro in FIXTURES.rglob('*.py'):
            self.assertFalse(
                Path(ficheiro.name).match(PADRAO_PADRAO),
                f'{ficheiro} casa o padrao das suites reais',
            )

    def test_as_fixtures_nao_sao_pacotes(self) -> None:
        """Sem `__init__.py`, o `discover` nem desce a pasta."""
        for pasta in (FIXTURES, *[p for p in FIXTURES.iterdir() if p.is_dir()]):
            self.assertFalse(
                (pasta / '__init__.py').exists(), f'{pasta} e um pacote'
            )

    def test_as_fixtures_vivem_debaixo_de_tests(self) -> None:
        """E a terceira propriedade, e sem este caso nao estava presa.

        O `coverage-python` mede `tools/` com `--omit="*/tests/*"`. Fora de
        `tests/`, estas *fixtures* entravam no denominador do estrato
        `restante` a 0% — correm em processos filhos, que a medicao do pai nao
        ve — e afundavam a cobertura sem nada avisar. A revisao adversarial
        apanhou o bloco a afirmar que esta classe prendia duas propriedades
        quando prendia a outra.
        """
        for ficheiro in FIXTURES.rglob('*.py'):
            partes = ficheiro.relative_to(FIXTURES.parents[1]).parts
            self.assertIn(
                'tests', partes, f'{ficheiro} esta fora de tests/'
            )
