"""Quando a rede morde, o portao tem de **nomear** o caso (KAM-182).

A rede e do KAM-173 e nao se toca: se o `wasSuccessful()` do `TestResult` e a
classificacao por teste discordarem, o portao recusa o verde. O que o KAM-182
fechou e o que ele **imprime** nesse momento — ate aqui dizia «o instrumento
perdeu informacao» quando a informacao estava no processo, e o `relato`
impresso logo a seguir tinha o nome e o *traceback*.

Medido a 2026-11-05 no *gate* 4 do PR #137: `corridos=1402,
classificados=1402, sucesso=False`. A contagem fecha, e nenhum vermelho e
nomeado; o que falhou foi a **atribuicao**. O vermelho daquele dia era o
KAM-181 e esta corrigido, pelo que nao se reproduz: as tres hipoteses que a
mensagem nomeava fabricam-se de proposito, uma *fixture* por hipotese, e cada
uma delas **reproduz o defeito com o corredor de antes deste ticket** —
medido, com as tres a dar `perdeu informacao` sem nome.

A quarta *fixture* e a que impede a correccao de se transformar no defeito
simetrico: um `tearDownModule` que levanta nao tem `id()` de teste para
nomear, e ai o portao **continua** a sair com 2. Nomear melhor e o objectivo;
dar verde quando nao se sabe seria pior do que o ponto de partida.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from ordem_dos_ensaios import canario
from ordem_dos_ensaios.cli import main

#: As quatro *fixtures* deste ticket, e o que cada uma encena.
FIXTURES_DO_TICKET = {
    'tardio': 'hipotese 3 — erro atribuido a um caso ja fechado como verde',
    'id_repetido': 'hipotese 2 — dois casos com o mesmo id()',
    'sem_derrubar': 'hipotese 1 — sinal do unittest que o Registo nao derruba',
    'sem_caso': 'nenhum id() de teste a nomear (_ErrorHolder)',
}


def _check(pasta: str) -> tuple[int, str, str]:
    fora, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(fora), redirect_stderr(erro):
        codigo = main(
            [
                '--root',
                str(canario.FIXTURES),
                'check',
                '--suite',
                pasta,
                '--padrao',
                canario.PADRAO,
                '--nome',
                f'fixture {pasta}',
            ]
        )
    return codigo, fora.getvalue(), erro.getvalue()


class TestOsDoisLadosSaemLadoALado(unittest.TestCase):
    """O comando que distingue as hipoteses e um so, e e este.

    Imprimir os `id()` que o `TestResult` acusa, os que o `Registo`
    classificou como vermelhos, e a diferenca entre os dois conjuntos. Sem os
    dois lados na saida, a hipotese fica no raciocinio de quem le — que foi o
    custo medido no dia: ir ao *traceback* em bruto para descobrir o teste, e a
    um `rerun` do mesmo *commit* para descobrir que a falha era
    nao-deterministica.
    """

    def test_a_saida_tem_os_dois_conjuntos_e_a_diferenca(self) -> None:
        _, _, erro = _check('tardio')
        self.assertIn('TestResult acusa', erro)
        self.assertIn('Registo classificou vermelho', erro)
        self.assertIn('acusados que o Registo nao viu comecar:', erro)
        self.assertIn('acusados que o Registo deu por verdes:', erro)
        self.assertIn('entradas sem id() de teste:', erro)

    def test_a_mensagem_nao_afirma_mais_do_que_sabe(self) -> None:
        """A frase antiga era falsa: a informacao estava no processo."""
        for pasta in FIXTURES_DO_TICKET:
            with self.subTest(pasta=pasta):
                _, _, erro = _check(pasta)
                self.assertNotIn('O instrumento perdeu informacao', erro)
                self.assertIn('NAO e verde da suite', erro)


class TestCadaHipoteseFicaIdentificadaNaSaida(unittest.TestCase):
    """O critério 3: a saida diz **qual** dos tres casos se verificou.

    E a partir da comparacao dos conjuntos e nao de uma suposicao — por isso
    cada caso prende tambem a medicao de onde a hipotese sai, e nao so o
    rotulo.
    """

    def test_o_erro_tardio_e_nomeado_pelo_verde_no_registo(self) -> None:
        codigo, _, erro = _check('tardio')
        self.assertEqual(codigo, 2)
        self.assertIn(
            'caso_erro_tardio.TestTardio.test_passa_e_o_erro_chega_depois',
            erro,
        )
        self.assertIn(
            'erro atribuido a um caso que o Registo ja fechou como verde', erro
        )
        self.assertNotIn('hipotese: id() repetido', erro)
        self.assertNotIn('hipotese: sinal do unittest', erro)

    def test_o_id_repetido_e_nomeado_pelos_dois_numeros(self) -> None:
        """A prova e `corridos` contra `classificados`, e nao o rotulo.

        E tambem como a hipotese fica **excluida** no exemplar de 2026-11-05,
        onde os dois numeros eram 1402 e 1402.
        """
        codigo, _, erro = _check('id_repetido')
        self.assertEqual(codigo, 2)
        self.assertIn('hipotese: id() repetido', erro)
        self.assertIn('o testsRun conta 3 e o estado tem 1 chave', erro)
        self.assertIn('caso_id_repetido.TestColapso.test_o_mesmo_id', erro)

    def test_o_sinal_nao_derrubado_sai_pela_via_nova(self) -> None:
        """O acusado nao esta no `estado`: o `Registo` nunca o viu comecar.

        E a forma do falso verde do `addSubTest` que o KAM-173 mediu, com o
        `hook` de hoje derrubado e um sinal novo no lugar dele.
        """
        codigo, _, erro = _check('sem_derrubar')
        self.assertEqual(codigo, 2)
        self.assertIn(
            'hipotese: sinal do unittest que o Registo nao derruba', erro
        )
        self.assertIn('sinal-que-ninguem-derruba', erro)
        self.assertIn('sem nunca passar pelo startTest', erro)


class TestARedeContinuaLa(unittest.TestCase):
    """O critério 2, e e o que a mutacao protege.

    Mudar o `return 2` do ramo da discordancia para `return 0` — ou condicionar
    a recusa a ter conseguido nomear alguem — faz esta classe ficar vermelha. E
    a unica das mutacoes que importa: um corredor que nomeie melhor mas de
    verde quando nao sabe e pior do que o que havia.
    """

    def test_sem_id_de_teste_para_nomear_continua_a_recusar(self) -> None:
        codigo, _, erro = _check('sem_caso')
        self.assertEqual(codigo, 2)
        self.assertIn('nenhum id() de teste a nomear', erro)
        self.assertIn('tearDownModule (caso_sem_caso)', erro)
        self.assertIn('TestResult acusa (0): []', erro)

    def test_e_nao_inventa_um_caso_que_nao_existe(self) -> None:
        """O `id()` do `_ErrorHolder` e uma frase, nao um identificador.

        Ate ao KAM-182 ela entrava no `estado` como se fosse um teste
        vermelho, e o portao dava-a por «vermelho nas duas ordens» — mandando
        procurar no `coverage-python` um teste que nao existe. O teste verde da
        *fixture* tambem nao e acusado de nada.
        """
        _, _, erro = _check('sem_caso')
        self.assertNotIn('TestPassa', erro)
        self.assertNotIn('vermelho(s) nas **duas** ordens', erro)

    def test_nomear_nunca_baixa_o_codigo_de_saida(self) -> None:
        for pasta, encenacao in FIXTURES_DO_TICKET.items():
            with self.subTest(pasta=pasta, encenacao=encenacao):
                self.assertEqual(_check(pasta)[0], 2)


class TestAViaDeSempreServeEANovaNaoADuplica(unittest.TestCase):
    """O critério 1, a outra direccao: um vermelho normal sai pela via de sempre.

    A *fixture* `vermelha/` falha pelo caminho normal nas duas ordens, pelo que
    o `Registo` a nomeia e a comparacao entre ordens apanha-a antes da rede. A
    saida nova nao pode aparecer la — duas explicacoes para um vermelho so
    mandam corrigir a coisa errada, que e o achado que fez este portao correr
    as duas ordens.
    """

    def test_um_vermelho_normal_nao_passa_pela_atribuicao(self) -> None:
        codigo, _, erro = _check('vermelha')
        self.assertEqual(codigo, 1)
        self.assertIn('vermelho(s) nas **duas** ordens', erro)
        self.assertIn('test_falha_em_qualquer_ordem', erro)
        self.assertNotIn('hipotese:', erro)
        self.assertNotIn('TestResult acusa', erro)

    def test_uma_suite_verde_continua_verde(self) -> None:
        codigo, fora, _ = _check('independente')
        self.assertEqual(codigo, 0)
        self.assertIn('0 mudancas de resultado', fora)


class TestOCanarioDoKam173FicaIntacto(unittest.TestCase):
    """O critério 5: as *fixtures* novas sao material da suite, nao do canario.

    O canario tem duas metades e e isso que o prova — uma que **tem** de morder
    e uma que **tem** de distinguir. Acrescentar-lhe casos mudava o que ele
    mede, e um corredor que mude de forma e deixe o canario a passar por outra
    razao nao esta provado.
    """

    def test_o_canario_tem_as_duas_metades_e_so_elas(self) -> None:
        self.assertEqual(
            {caso.pasta for caso in canario.CASOS},
            {'dependente', 'independente'},
        )

    def test_as_fixtures_deste_ticket_estao_fora_do_canario(self) -> None:
        pastas_do_canario = {caso.pasta for caso in canario.CASOS}
        for pasta in FIXTURES_DO_TICKET:
            with self.subTest(pasta=pasta):
                self.assertTrue((canario.FIXTURES / pasta).is_dir())
                self.assertNotIn(pasta, pastas_do_canario)
