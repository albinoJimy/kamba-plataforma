"""Sincronia linha<->bloco, orfaos, terceira superficie, e o fail-closed.

Cada teste negativo e «o conjunto bom, com **uma** coisa errada». O positivo
corre primeiro, e isso tambem e deliberado: um teste negativo so prova alguma
coisa se o caso bom passar — senao esta a confirmar que o gate falha sempre.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lint_backlog import modelo
from lint_backlog.cli import (sincronia, orfaos, terceira_superficie,
                              verificar)
from lint_backlog.modelo import BacklogIlegivel, normalizar_titulo
from lint_backlog.tests.conjunto import Conjunto, kam

#: A *fixture* tem cinco blocos de proposito; a guarda contra o vazio esta
#: calibrada para o conjunto real e aqui baixa-se, uma vez e por escrito.
MINIMO = 1


class Base(unittest.TestCase):
    def ler(self, conjunto: Conjunto) -> modelo.Backlog:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        conjunto.escrever(pasta)
        return modelo.ler(pasta, minimo=MINIMO)

    def verificar(self, conjunto: Conjunto):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        conjunto.escrever(pasta)
        return verificar(pasta, minimo=MINIMO)

    def falha_a_leitura(self, conjunto: Conjunto) -> str:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        conjunto.escrever(pasta)
        with self.assertRaises(BacklogIlegivel) as capturado:
            modelo.ler(pasta, minimo=MINIMO)
        return str(capturado.exception)

    @staticmethod
    def _apagar(pasta: Path) -> None:
        import shutil
        shutil.rmtree(pasta, ignore_errors=True)


class TestOCasoBom(Base):
    def test_o_conjunto_coerente_nao_da_achado_nenhum(self) -> None:
        veredicto = self.verificar(Conjunto())
        self.assertEqual(veredicto.achados, [])
        self.assertEqual(veredicto.configuracao, [])

    def test_le_as_duas_formas_de_bloco(self) -> None:
        """`specs/tickets/` (EPIC-01, KAM-155) e dentro do epic (os outros)."""
        backlog = self.ler(Conjunto())
        self.assertEqual(len(backlog.blocos), 5)
        self.assertTrue(backlog.blocos[kam(1)].ficheiro.startswith('specs/tickets/'))
        self.assertTrue(backlog.blocos[kam(4)].ficheiro.startswith('specs/EPIC-02'))


class TestCampoADivergir(Base):
    """Um teste por campo comparado — os seis do criterio de aceitacao."""

    def mutar(self, campo: str, valor: str) -> list[str]:
        conjunto = Conjunto()
        conjunto.ticket(2).no_bloco[campo] = valor
        return sincronia(self.ler(conjunto))

    def test_titulo(self) -> None:
        achados = self.mutar('titulo', 'Outro título qualquer')
        self.assertEqual(len(achados), 1)
        self.assertIn('`titulo` diverge', achados[0])
        self.assertIn('Outro título qualquer', achados[0])

    def test_tipo(self) -> None:
        achados = self.mutar('tipo', 'feature')
        self.assertEqual(len(achados), 1)
        self.assertIn('`tipo` diverge', achados[0])
        self.assertIn("'chore'", achados[0])
        self.assertIn("'feature'", achados[0])

    def test_estimativa(self) -> None:
        achados = self.mutar('estimativa', 'S')
        self.assertEqual(len(achados), 1)
        self.assertIn('`estimativa` diverge', achados[0])

    def test_prioridade(self) -> None:
        achados = self.mutar('prioridade', 'P2')
        self.assertEqual(len(achados), 1)
        self.assertIn('`prioridade` diverge', achados[0])

    def test_fase(self) -> None:
        achados = self.mutar('fase', '1')
        self.assertEqual(len(achados), 1)
        self.assertIn('`fase` diverge', achados[0])

    def test_dependencias(self) -> None:
        achados = self.mutar('dependencias', kam(3))
        self.assertEqual(len(achados), 1)
        self.assertIn('`dependencias` diverge', achados[0])

    def test_a_mensagem_diz_o_ticket_o_campo_e_os_dois_valores(self) -> None:
        """O criterio exige os quatro, e nao so «ha divergencia»."""
        achados = self.mutar('estimativa', 'XS')
        self.assertIn(kam(2), achados[0])
        self.assertIn('`estimativa`', achados[0])
        self.assertIn("'M'", achados[0])
        self.assertIn("'XS'", achados[0])
        self.assertIn('specs/INDICE.md', achados[0])
        self.assertIn('specs/tickets/', achados[0])


class TestTitulos(Base):
    def test_markup_igual_nos_dois_lados_passa(self) -> None:
        """Caso (m): `código` e *italico* comparam-se tal como estao escritos."""
        conjunto = Conjunto()
        conjunto.substituir(2, titulo='Pipeline de `CI` base e *gates* '
                                      'fail-closed — com travessão')
        self.assertEqual(sincronia(self.ler(conjunto)), [])

    def test_subida_de_directorio_no_titulo_nao_e_divergencia(self) -> None:
        """A regra escrita do `normalizar_titulo`, medida no conjunto real.

        O §4 escreve `../docs/tecnica/` e o bloco, que vive em
        `specs/tickets/`, escreve `../../docs/tecnica/`. Os dois estao certos.
        """
        conjunto = Conjunto()
        conjunto.substituir(2, titulo='Divergências de `../docs/tecnica/`')
        conjunto.ticket(2).no_bloco['titulo'] = (
            'Divergências de `../../docs/tecnica/`')
        conjunto.ticket(2).no_resumo['titulo'] = (
            'Divergências de `../docs/tecnica/`')
        self.assertEqual(sincronia(self.ler(conjunto)), [])

    def test_a_normalizacao_nao_toca_em_mais_nada(self) -> None:
        self.assertEqual(normalizar_titulo('a `b` *c* — d'), 'a `b` *c* — d')
        self.assertEqual(normalizar_titulo('x ../../../y'), 'x ../y')


class TestOrfaos(Base):
    def test_linha_sem_bloco_falha(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(3, tem_bloco=False)
        achados = orfaos(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        self.assertIn(kam(3), achados[0])
        self.assertIn('nao tem bloco', achados[0])

    def test_bloco_sem_linha_falha(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(5, no_indice=False)
        achados = orfaos(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        self.assertIn(kam(5), achados[0])
        self.assertIn('nao tem linha no §4', achados[0])


class TestTerceiraSuperficie(Base):
    def test_ticket_que_falta_na_tabela_resumo_falha(self) -> None:
        """O caso real: o §3 do EPIC-01 esteve meses sem tres tickets."""
        conjunto = Conjunto()
        conjunto.substituir(2, no_resumo_do_epic=False)
        achados = terceira_superficie(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        self.assertIn(kam(2), achados[0])
        self.assertIn('Tabela Resumo', achados[0])

    def test_campo_divergente_na_tabela_resumo_falha(self) -> None:
        conjunto = Conjunto()
        conjunto.ticket(4).no_resumo['prioridade'] = 'P0'
        achados = terceira_superficie(self.ler(conjunto))
        self.assertEqual(len(achados), 1)
        self.assertIn('entre o §4 e o §3', achados[0])

    def test_a_tabela_resumo_nao_tem_coluna_fase(self) -> None:
        """Mudar so a fase nao pode produzir achado na terceira superficie."""
        conjunto = Conjunto()
        conjunto.substituir(3, fase='1')
        self.assertEqual(terceira_superficie(self.ler(conjunto)), [])


class TestFailClosed(Base):
    """Codigo 2, e nao «nada a reportar»."""

    def test_bloco_sem_tabela_de_campos(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(1, sem_campos=True)
        self.assertIn('sem tabela de campos', self.falha_a_leitura(conjunto))

    def test_bloco_sem_um_campo_obrigatorio(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        Conjunto().escrever(pasta)
        alvo = pasta / 'specs' / 'tickets' / f'{kam(1)}.md'
        texto = alvo.read_text(encoding='utf-8')
        alvo.write_text(
            '\n'.join(l for l in texto.split('\n') if not l.startswith('| Bloqueia |')),
            encoding='utf-8')
        with self.assertRaises(BacklogIlegivel) as capturado:
            modelo.ler(pasta, minimo=MINIMO)
        self.assertIn('Bloqueia', str(capturado.exception))

    def test_epic_sem_tabela_resumo(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        Conjunto().escrever(pasta)
        alvo = pasta / 'specs' / 'EPIC-02_Canais_WhatsApp_Handoff.md'
        alvo.write_text(
            alvo.read_text(encoding='utf-8').replace(
                '## 3. Tabela Resumo de Tickets', '## 3. Outra coisa'),
            encoding='utf-8')
        with self.assertRaises(BacklogIlegivel) as capturado:
            modelo.ler(pasta, minimo=MINIMO)
        erro = str(capturado.exception)
        self.assertIn('Tabela Resumo de Tickets', erro)
        self.assertIn('EPIC-02', erro)

    def test_linha_do_indice_com_colunas_a_mais(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        Conjunto().escrever(pasta)
        alvo = pasta / 'specs' / 'INDICE.md'
        texto = alvo.read_text(encoding='utf-8')
        alvo.write_text(
            texto.replace(f'| {kam(1)} | Monorepo',
                          f'| {kam(1)} | a mais | Monorepo'), encoding='utf-8')
        erro = self.falha_a_leitura_em(pasta)
        self.assertIn('celula(s)', erro)

    def falha_a_leitura_em(self, pasta: Path) -> str:
        with self.assertRaises(BacklogIlegivel) as capturado:
            modelo.ler(pasta, minimo=MINIMO)
        return str(capturado.exception)

    def test_dois_blocos_para_o_mesmo_ticket(self) -> None:
        conjunto = Conjunto()
        # O mesmo ticket com bloco no EPIC-02 **e** em `specs/tickets/`.
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        conjunto.escrever(pasta)
        origem = pasta / 'specs' / 'EPIC-02_Canais_WhatsApp_Handoff.md'
        destino = pasta / 'specs' / 'tickets' / f'{kam(4)}.md'
        bloco = origem.read_text(encoding='utf-8').split(f'## {kam(4)} — ')[1]
        destino.write_text(f'## {kam(4)} — ' + bloco.split('\n## ')[0],
                           encoding='utf-8')
        self.assertIn('dois blocos', self.falha_a_leitura_em(pasta))

    def test_populacao_abaixo_do_minimo(self) -> None:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(self._apagar, pasta)
        Conjunto().escrever(pasta)
        with self.assertRaises(BacklogIlegivel) as capturado:
            modelo.ler(pasta, minimo=500)
        self.assertIn('esperam-se pelo menos', str(capturado.exception))

    def test_um_bloco_dentro_de_uma_cerca_nao_conta(self) -> None:
        """O *template* de PR do `specs/01` §7 e um bloco dentro de uma cerca."""
        conjunto = Conjunto()
        conjunto.extra_no_epic[2] = (
            f'\n```text\n## {kam(2)} — um título de exemplo\n```\n')
        backlog = self.ler(conjunto)
        self.assertEqual(backlog.blocos[kam(2)].ficheiro,
                         f'specs/tickets/{kam(2)}.md')


if __name__ == '__main__':
    unittest.main()
