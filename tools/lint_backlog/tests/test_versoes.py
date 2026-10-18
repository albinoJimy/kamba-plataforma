"""O «Controlo de versoes»: sequencia, cabecalho, e o efeito das declaracoes.

Inclui a prova que o criterio pede por extenso: uma entrada de
`ci/backlog-allow.yaml` baixa a falha a aviso, e **remove-la repoe a falha**.
Sem o segundo metade, a lista podia nao estar ligada a nada.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lint_backlog import versoes
from lint_backlog.cli import verificar
from lint_backlog.tests.conjunto import Conjunto

MINIMO = 1

#: O cabecalho obrigatorio de `ci/backlog-allow.yaml`.
ALLOW_VAZIO = 'version: 1\n'


class Base(unittest.TestCase):
    def escrever(self, conjunto: Conjunto) -> Path:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        conjunto.escrever(pasta)
        return pasta

    def controlos(self, conjunto: Conjunto) -> dict[str, versoes.Controlo]:
        return {c.ficheiro: c for c in versoes.varrer(self.escrever(conjunto))}


class TestLeitura(Base):
    def test_le_as_duas_formas_de_cabecalho(self) -> None:
        """`| Versão | 1.2 |` nos epics e `**Versão do conjunto:**` no INDICE."""
        controlos = self.controlos(Conjunto())
        self.assertEqual(controlos['specs/INDICE.md'].forma, 'texto')
        self.assertEqual(
            controlos['specs/EPIC-01_Fundacoes_Dados.md'].forma, 'tabela')

    def test_documento_sem_campo_de_versao_passa(self) -> None:
        """A ausencia do campo nao e defeito, e o gate nao a inventa."""
        pasta = self.escrever(Conjunto())
        avulso = pasta / 'docs'
        avulso.mkdir(parents=True, exist_ok=True)
        (avulso / 'notas.md').write_text(
            '# Notas\n\n## Controlo de versões\n\n'
            '| Versão | Data | Descrição | Autor |\n|---|---|---|---|\n'
            '| 1.0 | Outubro 2026 | Emissão inicial. | Equipa KAMBÁ |\n'
            '| 1.1 | Outubro 2026 | Emenda. | Equipa KAMBÁ |\n',
            encoding='utf-8')
        controlo = versoes.ler_documento(avulso / 'notas.md', pasta)
        self.assertIsNone(controlo.cabecalho)
        self.assertFalse(controlo.atrasado)
        self.assertEqual(controlo.buracos, ())
        self.assertEqual(verificar(pasta, minimo=MINIMO).achados, [])

    def test_a_ordem_de_escrita_nao_faz_buraco(self) -> None:
        """O `specs/INDICE.md` real tem o 1.2 escrito antes do 1.1."""
        conjunto = Conjunto()
        conjunto.versoes['specs/INDICE.md'] = ['1.0', '1.2', '1.1']
        self.assertEqual(self.controlos(conjunto)['specs/INDICE.md'].buracos, ())

    def test_tabela_com_cabecalho_e_sem_linhas_e_ilegivel(self) -> None:
        pasta = self.escrever(Conjunto())
        (pasta / 'docs').mkdir(parents=True, exist_ok=True)
        alvo = pasta / 'docs' / 'vazio.md'
        alvo.write_text('# Vazio\n\n| Versão | Data | Descrição | Autor |\n'
                        '|---|---|---|---|\n', encoding='utf-8')
        with self.assertRaises(versoes.ControloIlegivel):
            versoes.ler_documento(alvo, pasta)

    def test_as_pastas_de_registo_ficam_de_fora(self) -> None:
        """`docs/analises/` e `docs/evidencia/` sao registos datados."""
        pasta = self.escrever(Conjunto())
        (pasta / 'docs' / 'analises').mkdir(parents=True, exist_ok=True)
        (pasta / 'docs' / 'analises' / 'uma.md').write_text(
            '# Uma\n\n| Versão | 1.0 |\n| Data | Outubro |\n\n'
            '## Controlo de versões\n\n'
            '| Versão | Data | Descrição | Autor |\n|---|---|---|---|\n'
            '| 1.0 | Outubro 2026 | Inicial. | Equipa |\n'
            '| 1.2 | Outubro 2026 | Emenda. | Equipa |\n', encoding='utf-8')
        lidos = {c.ficheiro for c in versoes.varrer(pasta)}
        self.assertNotIn('docs/analises/uma.md', lidos)


class TestSequencia(Base):
    def test_numero_saltado_falha_e_a_mensagem_diz_qual(self) -> None:
        conjunto = Conjunto()
        conjunto.versoes['specs/EPIC-01_Fundacoes_Dados.md'] = [
            '1.0', '1.1', '1.3']
        conjunto.cabecalhos['specs/EPIC-01_Fundacoes_Dados.md'] = '1.3'
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        achado = next(a for a in veredicto.achados if 'salta' in a)
        self.assertIn('1.2', achado)
        self.assertIn('specs/EPIC-01_Fundacoes_Dados.md', achado)


class TestCabecalho(Base):
    def test_cabecalho_atrasado_na_forma_de_tabela(self) -> None:
        conjunto = Conjunto()
        conjunto.versoes['specs/EPIC-02_Canais_WhatsApp_Handoff.md'] = [
            '1.0', '1.1']
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        achado = next(a for a in veredicto.achados if 'cabecalho' in a)
        self.assertIn('EPIC-02', achado)
        self.assertIn('1.0', achado)
        self.assertIn('1.1', achado)

    def test_cabecalho_atrasado_na_forma_de_texto_corrido(self) -> None:
        conjunto = Conjunto()
        conjunto.versoes['specs/INDICE.md'] = ['1.0', '1.1', '1.2']
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        achado = next(a for a in veredicto.achados
                      if 'cabecalho' in a and 'INDICE' in a)
        self.assertIn('1.2', achado)


class TestDeclaracoes(Base):
    """A entrada baixa de falha a aviso; tira-la repoe a falha."""

    def conjunto_com_cabecalho_atrasado(self) -> Conjunto:
        conjunto = Conjunto()
        conjunto.versoes['specs/EPIC-02_Canais_WhatsApp_Handoff.md'] = [
            '1.0', '1.1']
        return conjunto

    DECLARACAO = (
        'version: 1\n'
        'cabecalhos:\n'
        '  - ficheiro: specs/EPIC-02_Canais_WhatsApp_Handoff.md\n'
        '    origem: KAM-138\n'
        '    razao: >-\n'
        '      Residuo de renumeracao declarado no teste, com razao longa o\n'
        '      suficiente para passar o limiar.\n')

    def test_sem_declaracao_falha(self) -> None:
        conjunto = self.conjunto_com_cabecalho_atrasado()
        conjunto.allow = ALLOW_VAZIO
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        self.assertTrue(any('cabecalho' in a for a in veredicto.achados))
        self.assertEqual(veredicto.avisos, [])

    def test_com_declaracao_baixa_a_aviso(self) -> None:
        conjunto = self.conjunto_com_cabecalho_atrasado()
        conjunto.allow = self.DECLARACAO
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        self.assertEqual(veredicto.achados, [])
        self.assertEqual(veredicto.configuracao, [])
        self.assertTrue(any('cabecalho atrasado declarado' in a
                            for a in veredicto.avisos))

    def test_tirar_a_declaracao_repoe_a_falha(self) -> None:
        conjunto = self.conjunto_com_cabecalho_atrasado()
        conjunto.allow = self.DECLARACAO
        pasta = self.escrever(conjunto)
        self.assertEqual(verificar(pasta, minimo=MINIMO).achados, [])
        (pasta / 'ci' / 'backlog-allow.yaml').write_text(
            ALLOW_VAZIO, encoding='utf-8')
        self.assertTrue(any('cabecalho' in a
                            for a in verificar(pasta, minimo=MINIMO).achados))

    def test_declaracao_que_nao_casa_nada_e_erro_de_configuracao(self) -> None:
        """Uma declaracao esquecida abre uma porta que ninguem vigia."""
        conjunto = Conjunto()  # o cabecalho do EPIC-02 esta a dia
        conjunto.allow = self.DECLARACAO
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        self.assertTrue(any('ja esta a dia' in c for c in veredicto.configuracao))

    def test_declaracao_de_ficheiro_sem_tabela_e_erro(self) -> None:
        conjunto = Conjunto()
        conjunto.allow = (
            'version: 1\n'
            'sequencias:\n'
            '  - ficheiro: specs/nao-existe.md\n'
            '    falta: "1.4"\n'
            '    origem: KAM-138\n'
            '    razao: >-\n'
            '      Uma razao suficientemente longa para passar o limiar da\n'
            '      verificacao de razoes curtas.\n')
        veredicto = verificar(self.escrever(conjunto), minimo=MINIMO)
        self.assertTrue(any('nao tem tabela' in c for c in veredicto.configuracao))

    def test_razao_curta_e_recusada(self) -> None:
        from lint_backlog.cli import ConfiguracaoInvalida, ler_declaracoes
        conjunto = Conjunto()
        conjunto.allow = (
            'version: 1\n'
            'cabecalhos:\n'
            '  - ficheiro: specs/INDICE.md\n'
            '    origem: KAM-138\n'
            '    razao: curta\n')
        with self.assertRaises(ConfiguracaoInvalida):
            ler_declaracoes(self.escrever(conjunto))

    def test_chave_desconhecida_e_recusada(self) -> None:
        """A recusa do KAM-134: nenhum codigo le a chave, logo nao entra."""
        from lint_backlog.cli import ConfiguracaoInvalida, ler_declaracoes
        conjunto = Conjunto()
        conjunto.allow = 'version: 1\ninventada: 2\n'
        with self.assertRaises(ConfiguracaoInvalida) as capturado:
            ler_declaracoes(self.escrever(conjunto))
        self.assertIn('inventada', str(capturado.exception))

    def test_version_errada_e_recusada(self) -> None:
        from lint_backlog.cli import ConfiguracaoInvalida, ler_declaracoes
        conjunto = Conjunto()
        conjunto.allow = 'version: 2\n'
        with self.assertRaises(ConfiguracaoInvalida):
            ler_declaracoes(self.escrever(conjunto))

    def test_inversao_declarada_baixa_a_aviso_e_tirada_repoe_a_falha(self) -> None:
        conjunto = Conjunto()
        conjunto.substituir(1, prioridade='P1')
        conjunto.allow = (
            'version: 1\n'
            'inversoes:\n'
            '  - de: KAM-002\n'
            '    para: KAM-001\n'
            '    genero: prioridade\n'
            '    origem: KAM-138\n'
            '    razao: >-\n'
            '      Inversao conhecida e deliberada, declarada com uma razao\n'
            '      longa o suficiente para passar o limiar.\n'
            '  - de: KAM-003\n'
            '    para: KAM-001\n'
            '    genero: prioridade\n'
            '    origem: KAM-138\n'
            '    razao: >-\n'
            '      A segunda aresta que entra no mesmo ticket; declara-se uma\n'
            '      por aresta, e nao uma por ticket, de proposito.\n')
        pasta = self.escrever(conjunto)
        veredicto = verificar(pasta, minimo=MINIMO)
        self.assertEqual(veredicto.achados, [])
        self.assertTrue(any('inversao de prioridade declarada' in a
                            for a in veredicto.avisos))
        (pasta / 'ci' / 'backlog-allow.yaml').write_text(
            ALLOW_VAZIO, encoding='utf-8')
        self.assertTrue(any('inversao de prioridade' in a
                            for a in verificar(pasta, minimo=MINIMO).achados))


if __name__ == '__main__':
    unittest.main()
