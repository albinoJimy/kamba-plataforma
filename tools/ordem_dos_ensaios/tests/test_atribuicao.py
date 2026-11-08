"""Quando a rede morde, o portao tem de **nomear** o caso (KAM-182).

A rede e do KAM-173 e nao se toca: se o `wasSuccessful()` do `TestResult` e a
classificacao por teste discordarem, o portao recusa o verde. O que o KAM-182
fechou e o que ele **imprime** nesse momento — ate aqui dizia «o instrumento
perdeu informacao» quando a informacao estava no processo, e o `relato`
impresso logo a seguir tinha o nome e o *traceback*.

Medido a 2026-11-05 no *gate* 4 do PR #137: `corridos=1402,
classificados=1402, sucesso=False`. A contagem fecha, e nenhum vermelho e
nomeado; o que falhou foi a **atribuicao**. O vermelho daquele dia era o
KAM-181 e esta corrigido, pelo que nao se reproduz: as causas fabricam-se de
proposito, uma *fixture* por causa, e cada uma delas **reproduz o defeito com o
corredor de antes deste ticket** — medido.

**Tres das oito nasceram da revisao adversarial**, e vale dizer o que cada uma
fecha, porque sem elas a correccao tinha tres buracos:

    skip_tardio        a hipotese 3 pelo caminho **publico** do `unittest`. O
                       mecanismo que o Contexto do bloco supoe — um erro que
                       chega depois — nao produz discordancia nenhuma: entra
                       pelo `addError` e o Registo derruba o caso. O que a
                       produz e uma escrita posterior, e o texto da hipotese
                       diz isso desde que isto foi medido.
    colapso_mascarado  a hipotese 2 ficava **calada** quando entradas que nao
                       sao casos enchiam o `len(estado)`. Hoje a conta e contra
                       o `corridos_distintos`, que so conta o que passou pelo
                       `startTest`.
    so_na_normal       um vermelho **so na ordem de omissao** nao cai em
                       nenhuma das tres comparacoes entre ordens e chega a
                       rede. O Registo nomeia-o, e a saida tem de o dizer.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from ordem_dos_ensaios import canario
from ordem_dos_ensaios.cli import main

#: As *fixtures* deste ticket, o que cada uma encena, e **o codigo de saida que
#: cada uma tem de dar**. O `sem_caso` e o unico que sai com 1, e isso nao e
#: fraqueza: um erro de `tearDownModule` passa pelo `addError`, pelo que a frase
#: do `_ErrorHolder` entra no `estado` e a comparacao entre as duas ordens
#: apanha-a **antes** da rede. Esta na lista para o 1 ficar preso: tirar a frase
#: do `estado` para a trazer ao ramo da discordancia foi tentado e desfez-se,
#: porque cegava o canario (ver o `addError` do `corredor`).
FIXTURES_DO_TICKET = {
    'tardio': (2, 'hipotese 3 — classificacao sobrescrita, pela forma do bloco'),
    'skip_tardio': (2, 'hipotese 3 — a mesma, por caminho publico do unittest'),
    'id_repetido': (2, 'hipotese 2 — dois casos com o mesmo id()'),
    'colapso_mascarado': (2, 'hipotese 2 mascarada por entradas sem caso'),
    'sem_derrubar': (2, 'hipotese 1 — sinal que o Registo nao derruba'),
    'so_na_normal': (2, 'vermelho so na ordem de omissao: nenhuma das tres'),
    'sem_nome': (2, 'nada a nomear: a recusa que nao se negocia'),
    'sem_caso': (1, 'tearDownModule: apanhado pela via de sempre, com 1'),
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

    def test_as_tres_contagens_saem_separadas(self) -> None:
        """`corridos`, `corridos_distintos` e `len(estado)` sao **tres**.

        Confundir os dois ultimos foi o que calou a hipotese 2 na
        `colapso_mascarado`, pelo que os tres numeros saem na cara de quem le.
        """
        _, _, erro = _check('colapso_mascarado')
        self.assertIn(
            'corridos=3, casos distintos iniciados=1, entradas no estado=3',
            erro,
        )

    def test_a_mensagem_nao_afirma_mais_do_que_sabe(self) -> None:
        """A frase antiga era falsa: a informacao estava no processo."""
        for pasta in FIXTURES_DO_TICKET:
            with self.subTest(pasta=pasta):
                _, _, erro = _check(pasta)
                self.assertNotIn('O instrumento perdeu informacao', erro)


class TestCadaHipoteseFicaIdentificadaNaSaida(unittest.TestCase):
    """O critério 3: a saida diz **qual** dos tres casos se verificou.

    E a partir da comparacao dos conjuntos e nao de uma suposicao — por isso
    cada caso prende tambem a medicao de onde a hipotese sai, e **cada um nega
    as hipoteses que nao se verificaram**. Sem essas negativas, uma hipotese a
    mais na saida passava calada, que e como o diagnostico enganador da
    `colapso_mascarado` escapou a primeira versao desta bateria.
    """

    #: As tres etiquetas, para cada caso poder negar as que nao sao dele.
    ETIQUETAS = {
        'repetido': 'hipotese: id() repetido',
        'sobrescrita': 'hipotese: classificacao sobrescrita',
        'nao_derrubado': 'hipotese: sinal do unittest que o Registo nao derruba',
    }

    def so_estas(self, erro: str, *presentes: str) -> None:
        for chave, etiqueta in self.ETIQUETAS.items():
            if chave in presentes:
                self.assertIn(etiqueta, erro)
            else:
                self.assertNotIn(etiqueta, erro)

    def test_a_classificacao_sobrescrita_e_nomeada_pelo_verde_no_registo(
        self,
    ) -> None:
        codigo, _, erro = _check('tardio')
        self.assertEqual(codigo, 2)
        self.assertIn(
            'caso_erro_tardio.TestTardio.test_passa_e_o_erro_chega_depois',
            erro,
        )
        self.so_estas(erro, 'sobrescrita')

    def test_e_pelo_caminho_publico_do_unittest_da_o_mesmo(self) -> None:
        """Um caso que falha e cuja limpeza salta: o `addSkip` escreve por cima.

        E a forma real da hipotese 3, e e o que obriga o texto dela a dizer
        «sobrescrita» em vez de «uma thread ou um done_callback» — por essa via
        o erro entra pelo `addError` e nao ha discordancia nenhuma. Achado da
        revisao adversarial.
        """
        codigo, _, erro = _check('skip_tardio')
        self.assertEqual(codigo, 2)
        self.assertIn(
            'caso_skip_depois_da_falha.TestFalhaEDepoisSalta.'
            'test_falha_e_a_limpeza_salta',
            erro,
        )
        self.so_estas(erro, 'sobrescrita')
        self.assertIn('skip de limpeza', erro)
        self.assertNotIn('thread', erro)

    def test_o_id_repetido_e_nomeado_pelos_dois_numeros(self) -> None:
        """A prova e `corridos` contra o que o `startTest` viu, nao o rotulo."""
        codigo, _, erro = _check('id_repetido')
        self.assertEqual(codigo, 2)
        self.assertIn('o testsRun conta 3 e o startTest viu 1 id()', erro)
        self.assertIn('caso_id_repetido.TestColapso.test_o_mesmo_id', erro)
        self.so_estas(erro, 'repetido', 'sobrescrita')

    def test_o_id_repetido_nao_se_cala_por_entradas_que_nao_sao_casos(
        self,
    ) -> None:
        """O defeito que a revisao adversarial mediu, e que esta preso aqui.

        Com `corridos - len(estado)` como medida, dois `setUpModule` a levantar
        `SkipTest` enchiam a conta que o colapso tinha esvaziado: dava zero, a
        hipotese 2 ficava calada, e o portao anunciava a 3 sem dizer quem
        sobrescreveu. **E desmonta a frase do Contexto do bloco** segundo a
        qual `1402 == 1402` exclui o `id()` repetido: o numero da direita era
        `len(estado)`.
        """
        codigo, _, erro = _check('colapso_mascarado')
        self.assertEqual(codigo, 2)
        self.assertIn('o testsRun conta 3 e o startTest viu 1 id()', erro)
        self.so_estas(erro, 'repetido', 'sobrescrita')

    def test_o_sinal_nao_derrubado_sai_pela_via_nova(self) -> None:
        """O acusado nao esta no `estado`: o `Registo` nunca o viu comecar."""
        codigo, _, erro = _check('sem_derrubar')
        self.assertEqual(codigo, 2)
        self.assertIn('sinal-que-ninguem-derruba', erro)
        self.assertIn('sem nunca passar pelo startTest', erro)
        self.so_estas(erro, 'nao_derrubado')

    def test_um_vermelho_so_na_ordem_de_omissao_e_nomeado(self) -> None:
        """Nenhuma das tres, e a saida diz **isso** em vez de uma das tres.

        As tres comparacoes entre ordens olham para os vermelhos da inversa ou
        para os inventarios; um teste verde na inversa e vermelho na de omissao
        nao cai em nenhuma e chega a rede, com o Registo a nomea-lo. Achado da
        revisao adversarial: a bateria nao media esta direccao, e uma mutacao
        que a apagasse sobrevivia.
        """
        codigo, _, erro = _check('so_na_normal')
        self.assertEqual(codigo, 2)
        self.assertIn('hipotese: nenhuma das tres', erro)
        self.assertIn(
            'caso_vermelho_so_na_omissao.TestZLeitura.'
            'test_o_registo_comeca_vazio',
            erro,
        )
        self.assertIn('quem suja o estado de processo repoe-no', erro)
        self.so_estas(erro)


class TestARedeContinuaLa(unittest.TestCase):
    """O critério 2, e e o que a mutacao protege.

    Mudar o `return 2` do ramo da discordancia para `return 0` — ou condicionar
    a recusa a ter conseguido nomear alguem — faz esta classe ficar vermelha. E
    a unica das mutacoes que importa: um corredor que nomeie melhor mas de
    verde quando nao sabe e pior do que o que havia.
    """

    def test_sem_nada_a_nomear_continua_a_recusar(self) -> None:
        codigo, _, erro = _check('sem_nome')
        self.assertEqual(codigo, 2)
        self.assertIn('nenhum id() de teste a nomear', erro)
        self.assertIn('TestResult acusa (0): []', erro)
        self.assertIn('tearDownModule (caso_sem_nome)', erro)

    def test_e_a_mensagem_continua_a_dizer_que_a_falha_e_do_portao(
        self,
    ) -> None:
        """A segunda metade do critério, e esteve em falta por uma versao.

        O critério pede duas coisas — codigo nao-zero **e** a mensagem a dizer
        que a falha e do portao — e a primeira versao desta entrega tirou a
        frase sem o declarar. Achado da revisao adversarial.
        """
        _, _, erro = _check('sem_nome')
        self.assertIn('nem o TestResult nomeia um caso', erro)
        self.assertIn('a falha e do portao, nao da suite', erro)
        self.assertIn('nao e negociavel', erro)

    def test_quando_nomeia_nao_diz_que_a_falha_e_do_portao(self) -> None:
        """E a outra metade da honestidade: com nome, a falha e da suite.

        A frase antiga dizia sempre «falha do portao», e nos casos em que o
        caso e nomeado isso e falso — o que falhou do portao foi a atribuicao,
        e essa ja esta feita.
        """
        _, _, erro = _check('tardio')
        self.assertIn('falha do portao a atribuir', erro)
        self.assertNotIn('nem o TestResult nomeia um caso', erro)

    def test_nomear_nunca_baixa_o_codigo_de_saida(self) -> None:
        for pasta, (codigo, encenacao) in FIXTURES_DO_TICKET.items():
            with self.subTest(pasta=pasta, encenacao=encenacao):
                self.assertEqual(_check(pasta)[0], codigo)
                self.assertNotEqual(_check(pasta)[0], 0)


class TestOTearDownModuleSaiPelaViaDeSempre(unittest.TestCase):
    """O `_ErrorHolder` continua no `estado`, e o preco esta medido aqui.

    O `id()` de um `_ErrorHolder` e uma frase (`tearDownModule (modulo)`) e nao
    um identificador de caso, pelo que o portao a trata como um teste vermelho
    e manda procurar no `coverage-python` um caso que nao existe. **E fica
    assim de propósito.** Tirar a frase do `estado` parece a limpeza certa, e
    esta entrega tirou-a por uma versao: o `canario.verificar` le o
    `vermelhos()` e nunca o `sucesso`, pelo que uma *fixture* do canario que
    rebentasse num `setUpClass` passava a dar **verde** em vez de
    `precondicao` — verde onde antes havia recusa, no unico sitio que prova
    que este portao morde. Achado da revisao adversarial, e desfez-se.

    Mexer nisto e mexer no que o portao recusa, e isso e do fundador. Estes
    casos prendem o comportamento de hoje para que a proxima tentativa tenha de
    os mudar de propósito.
    """

    def test_sai_com_1_pelo_ramo_das_duas_ordens(self) -> None:
        codigo, _, erro = _check('sem_caso')
        self.assertEqual(codigo, 1)
        self.assertIn('vermelho(s) nas **duas** ordens', erro)
        self.assertIn('tearDownModule (caso_sem_caso)', erro)

    def test_e_nenhum_id_de_teste_e_nomeado(self) -> None:
        """O que os «Testes Requeridos» do bloco pedem: nenhum caso inventado.

        O teste verde da *fixture* nao e acusado de nada; o que aparece e a
        frase, que nao e um `id()` de caso.
        """
        _, _, erro = _check('sem_caso')
        self.assertNotIn('TestPassa', erro)


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
