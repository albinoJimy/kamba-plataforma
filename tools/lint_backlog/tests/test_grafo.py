"""O grafo: reciprocidade, ciclos, inversoes de prioridade e de fase.

E a metade do gate que nenhuma comparacao de tabelas faz, porque o §4 **nao tem
coluna `Bloqueia`**: tudo o que estes testes cobrem e invisivel a sincronia
linha<->bloco.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lint_backlog import modelo
from lint_backlog.cli import ciclos, inversoes, reciprocidade
from lint_backlog.tests.conjunto import Conjunto, kam

MINIMO = 1


class Base(unittest.TestCase):
    def ler(self, conjunto: Conjunto) -> modelo.Backlog:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        conjunto.escrever(pasta)
        return modelo.ler(pasta, minimo=MINIMO)


class TestReciprocidade(Base):
    def test_o_conjunto_coerente_da_zero(self) -> None:
        self.assertEqual(reciprocidade(self.ler(Conjunto())), [])

    def test_dependencia_declarada_de_um_so_lado(self) -> None:
        """O caso G5: `A` depende de `B` e o `Bloqueia` de `B` nao tem `A`.

        E o defeito que o KAM-144 teve de reparar oito vezes, e o unico que a
        sincronia linha<->bloco **nao pode** ver.
        """
        conjunto = Conjunto()
        conjunto.substituir(1, bloqueia=(3,))  # perde o 2
        achados = reciprocidade(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        self.assertIn(f'{kam(2)} depende de {kam(1)}', achados[0])
        self.assertIn('um so lado', achados[0])

    def test_bloqueia_sem_a_dependencia_do_outro_lado(self) -> None:
        """O sentido contrario conta na mesma: e a mesma aresta."""
        conjunto = Conjunto()
        conjunto.substituir(5, bloqueia=(3,))
        achados = reciprocidade(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        self.assertIn(f'{kam(5)} bloqueia {kam(3)}', achados[0])

    def test_a_sincronia_sozinha_nao_ve_a_aresta_perdida(self) -> None:
        """A razao de existir deste criterio, medida e nao afirmada."""
        from lint_backlog.cli import sincronia
        conjunto = Conjunto()
        conjunto.substituir(1, bloqueia=(3,))
        backlog = self.ler(conjunto)
        self.assertEqual(sincronia(backlog), [])
        self.assertEqual(len(reciprocidade(backlog)), 1)


class TestDependenciasExternas(Base):
    def test_ext_de_decisao_nao_exige_reciprocidade(self) -> None:
        """`ext:D6` e uma decisao aberta e nao tem bloco nenhum."""
        conjunto = Conjunto()
        conjunto.substituir(3, dependencias=f'{kam(1)}, ext:D6')
        conjunto.substituir(1, bloqueia=(2, 3))
        self.assertEqual(reciprocidade(self.ler(conjunto)), [])

    def test_ext_com_forma_de_ticket_nao_exige_reciprocidade(self) -> None:
        """`ext:KAM-NNN` e o que engana: tem forma de ticket e e espera externa.

        O ticket apontado **nao** e obrigado a declarar `Bloqueia`.
        """
        conjunto = Conjunto()
        conjunto.substituir(4, dependencias=f'{kam(2)}, ext:{kam(5)}')
        conjunto.substituir(2, bloqueia=(4,))
        self.assertEqual(reciprocidade(self.ler(conjunto)), [])

    def test_ext_satisfaz_o_bloqueia_que_o_outro_lado_escolha_declarar(self) -> None:
        """O contrario obrigava a apagar `Bloqueia` que estao certos."""
        conjunto = Conjunto()
        conjunto.substituir(4, dependencias=f'{kam(2)}, ext:{kam(5)}')
        conjunto.substituir(2, bloqueia=(4,))
        conjunto.substituir(5, bloqueia=(4,))
        self.assertEqual(reciprocidade(self.ler(conjunto)), [])

    def test_dependencia_de_um_ticket_sem_bloco_falha(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(3, tem_bloco=False)
        achados = reciprocidade(self.ler(conjunto))
        self.assertTrue(any('nao tem bloco nenhum' in a for a in achados))


class TestGralhaDeIdentificador(Base):
    """Uma entrada que nao se sabe ler **nao** desaparece em silencio.

    Ate a revisao adversarial do KAM-138, o ramo das dependencias fazia
    `continue` sobre tudo o que nao reconhecia enquanto o ramo do `Bloqueia`
    reportava. Escrita coerentemente nas tres superficies — que e como uma
    gralha viaja, porque se copia a celula —, a entrada dava conforme no 3c e
    conforme no gate 3: a aresta existia em prosa e nao existia para a
    reciprocidade, para os ciclos nem para as inversoes.
    """

    #: As formas que o revisor construiu, mais a que se escreve sem querer.
    #: Nenhuma se escreve por extenso com um numero de ticket inexistente: o
    #: gate 3 le o conteudo deste ficheiro e recusaria um identificador que nao
    #: esteja no backlog mestre.
    FORMAS = (
        'KAM-' + '19',          # dois digitos: a gralha mais provavel que ha
        'kam-' + '019',         # minusculas
        'KAM' + '019',          # sem o hifen
        'Kam-' + '019',         # capitalizada
        'ext:kam-' + '019',     # a mesma, dentro de um `ext:`
        'XPTO-1',               # outra serie
        'KAM-' + '0190',        # quatro digitos
    )

    def achados_com(self, valor: str, campo: str) -> list[str]:
        from lint_backlog.cli import malformadas
        conjunto = Conjunto()
        if campo == 'dependencias':
            conjunto.substituir(3, dependencias=valor)
            conjunto.substituir(1, bloqueia=(2,))
        else:
            conjunto.substituir(3, bloqueia=())
            conjunto.ticket(3).no_bloco['bloqueia'] = valor
        return malformadas(self.ler(conjunto))

    def test_cada_forma_falha_nas_dependencias(self) -> None:
        for valor in self.FORMAS:
            with self.subTest(valor=valor):
                achados = self.achados_com(valor, 'dependencias')
                self.assertEqual(len(achados), 1, achados)
                self.assertIn(repr(valor), achados[0])
                self.assertIn('Dependências', achados[0])

    def test_cada_forma_falha_no_bloqueia(self) -> None:
        """A simetria que faltava: os dois campos dizem a mesma coisa."""
        for valor in self.FORMAS:
            with self.subTest(valor=valor):
                achados = self.achados_com(valor, 'bloqueia')
                self.assertEqual(len(achados), 1, achados)
                self.assertIn(repr(valor), achados[0])
                self.assertIn('Bloqueia', achados[0])

    def test_a_mensagem_diz_as_formas_aceites(self) -> None:
        achados = self.achados_com('KAM-' + '19', 'dependencias')
        self.assertIn('ext:KAM-NNN', achados[0])
        self.assertIn('ext:D#', achados[0])

    def test_as_formas_validas_passam(self) -> None:
        from lint_backlog.cli import malformadas
        conjunto = Conjunto()
        conjunto.substituir(3, dependencias=f'{kam(1)}, ext:D6, ext:{kam(5)}')
        conjunto.substituir(1, bloqueia=(2, 3))
        self.assertEqual(malformadas(self.ler(conjunto)), [])

    def test_a_gralha_so_da_um_achado_e_nao_tres(self) -> None:
        """Os ciclos e as inversoes saltam-na em silencio, de propósito."""
        from lint_backlog.cli import verificar
        import shutil as _shutil
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, pasta, True)
        conjunto = Conjunto()
        conjunto.substituir(3, dependencias='KAM-' + '19')
        conjunto.substituir(1, bloqueia=(2,))
        conjunto.escrever(pasta)
        achados = verificar(pasta, minimo=MINIMO).achados
        gralhas = [a for a in achados if 'KAM-19' in a]
        self.assertEqual(len(gralhas), 1, achados)


class TestCiclos(Base):
    def test_sem_ciclos_no_conjunto_coerente(self) -> None:
        self.assertEqual(ciclos(self.ler(Conjunto())), [])

    def test_ciclo_de_tres_com_o_caminho_completo(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(1, depende_de=(3,), bloqueia=(2, 3))
        conjunto.substituir(2, depende_de=(1,), bloqueia=(3, 4))
        conjunto.substituir(3, depende_de=(2,), bloqueia=(1,))
        achados = ciclos(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        for identificador in (kam(1), kam(2), kam(3)):
            self.assertIn(identificador, achados[0])
        self.assertIn('→', achados[0])
        # O caminho fecha sobre si proprio: o primeiro ID repete-se no fim.
        percurso = achados[0].split(': ', 1)[1].split(' → ')
        self.assertEqual(percurso[0], percurso[-1])

    def test_um_ciclo_de_dois_tambem_conta(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(1, depende_de=(2,), bloqueia=(2, 3))
        conjunto.substituir(2, depende_de=(1,), bloqueia=(1, 4))
        achados = ciclos(self.ler(conjunto))
        self.assertEqual(len(achados), 1)


class TestInversoes(Base):
    def test_p0_a_depender_de_p1_e_reportado(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(1, prioridade='P1')
        encontradas = inversoes(self.ler(conjunto))
        generos = {genero for _, _, genero, _ in encontradas}
        self.assertIn('prioridade', generos)
        texto = next(t for _, _, g, t in encontradas if g == 'prioridade')
        self.assertIn('P0', texto)
        self.assertIn('P1', texto)

    def test_fase_0_a_depender_de_fase_1_e_reportado(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(1, fase='1')
        encontradas = inversoes(self.ler(conjunto))
        generos = {genero for _, _, genero, _ in encontradas}
        self.assertIn('fase', generos)

    def test_o_conjunto_coerente_nao_tem_inversoes(self) -> None:
        self.assertEqual(inversoes(self.ler(Conjunto())), [])

    def test_uma_inversao_nao_declarada_falha(self) -> None:
        """Nasce como aviso **so** para as declaradas; as outras falham."""
        from lint_backlog.cli import verificar
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        conjunto = Conjunto()
        conjunto.substituir(1, prioridade='P1')
        conjunto.escrever(pasta)
        veredicto = verificar(pasta, minimo=MINIMO)
        self.assertTrue(any('inversao de prioridade' in a
                            for a in veredicto.achados))


if __name__ == '__main__':
    unittest.main()
