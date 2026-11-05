"""A classificacao e a conta do reuso, sobre o repositorio de exemplo.

O que esta bateria mede, e porque cada familia existe:

**A conta.** Sobre uma arvore com tamanhos escolhidos, o numero tem de ser o que
a aritmetica da — e nao «mais ou menos isso». Com tamanhos controlados, um erro
de classificacao nao se esconde num numero plausivel.

**O simbolo contra o ficheiro.** Num ficheiro misto conta-se o simbolo
importado. Medir isto e o que impede a metrica de contar como reuso 2 168 linhas
do `nos.py` do Vendedor por causa de doze nos importados.

**As mutacoes.** Copiar um no em vez de o importar tem de **baixar** o numero
nas duas pontas. Um teste que so confirme o verde nao prova que a metrica mede
reuso: prova que ela devolve um numero.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kamba_yaml import load_file

from reuse_metric.caminho import Declaracao, DeclaracaoInvalidaError, classificar, medir
from reuse_metric.tests import arvore


class _ComArvore(unittest.TestCase):
    #: Os tamanhos, em linhas de codigo. Escolhidos para a conta ser redonda.
    NUCLEO = 60
    ESPECIFICO = 20
    SIMBOLO = 5
    MIGRACAO_BASE = 10
    MIGRACAO_NOVA = 5
    #: O `__init__.py` da vertical nova: uma linha de codigo, o `import` do
    #: grafo. E `especifico` como o resto da pasta.
    INICIALIZADOR = 1

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = arvore.montar(
            Path(self._tmp.name),
            nucleo=self.NUCLEO,
            especifico=self.ESPECIFICO,
            simbolo_partilhado=self.SIMBOLO,
            migracao_base=self.MIGRACAO_BASE,
            migracao_nova=self.MIGRACAO_NOVA,
        )
        self.addCleanup(self._tmp.cleanup)

    @property
    def declaracao(self) -> dict:
        return load_file(self.raiz / "ci" / "regra-de-dois.yaml")

    def medir(self):
        return medir(self.raiz, self.declaracao, onde="teste")


class TestAConta(_ComArvore):
    def test_o_especifico_e_o_grafo_mais_a_migracao_da_vertical(self) -> None:
        medicao = self.medir()
        self.assertEqual(
            medicao.especifico,
            self.ESPECIFICO + self.MIGRACAO_NOVA + self.INICIALIZADOR,
        )

    def test_o_partilhado_leva_o_nucleo_os_simbolos_e_a_migracao_antepassada(
        self,
    ) -> None:
        medicao = self.medir()
        # O `__init__.py` da vertical e `especifico`; o do `pkg` esta vazio. O
        # partilhado e: o nucleo, os dois simbolos do misto, e a migracao
        # antepassada. O `outro.py` da outra vertical **nao** entra, apesar de
        # o nucleo o importar — e o que a classe `outra_vertical` existe para.
        self.assertEqual(
            medicao.partilhado,
            self.NUCLEO + 2 * self.SIMBOLO + self.MIGRACAO_BASE,
        )

    def test_o_reuso_e_a_formula(self) -> None:
        medicao = self.medir()
        esperado = 100.0 * (1 - medicao.especifico / medicao.total)
        self.assertAlmostEqual(medicao.reuso, esperado, places=9)

    def test_o_artefacto_leva_as_parcelas_e_nao_so_o_numero(self) -> None:
        """Um reuso sem a lista de onde ele vem nao se pode contestar."""
        mapa = self.medir().como_mapa()
        for chave in (
            "loc_especifico",
            "loc_partilhado",
            "loc_total",
            "reuso_pct",
            "entradas",
            "fora_da_conta",
        ):
            self.assertIn(chave, mapa)
        self.assertTrue(all("razao" in e for e in mapa["entradas"]))

    def test_e_reproduzivel_na_segunda_execucao(self) -> None:
        """O criterio 6 do bloco pede duas execucoes iguais."""
        self.assertEqual(self.medir().como_mapa(), self.medir().como_mapa())


class TestOSimboloContraOFicheiro(_ComArvore):
    def test_do_misto_contam_so_os_simbolos_importados(self) -> None:
        medicao = self.medir()
        do_misto = [e for e in medicao.entradas if e.simbolo is not None]
        self.assertEqual(
            {e.simbolo for e in do_misto}, {"partilhado_um", "partilhado_dois"}
        )
        # O `so_da_velha` tem 41 linhas e **nao** entra: nenhum `import` o traz.
        self.assertNotIn("so_da_velha", {e.simbolo for e in do_misto})

    def test_a_outra_vertical_fica_fora_da_conta_e_nomeada(self) -> None:
        medicao = self.medir()
        fora = {e.caminho for e in medicao.fora}
        self.assertIn("pkg/verticais/velha/outro.py", fora)


class TestMutacaoACopiaBaixaOReuso(_ComArvore):
    """**O canario da metrica.** Copiar em vez de importar tem de doer.

    E a propriedade que faz desta metrica uma medida do que o ADR-012 afirma: se
    a vertical nova copiar um no partilhado para dentro de si, o reuso **desce**
    — o simbolo sai do denominador e as linhas entram no numerador. Se esta
    propriedade cair, a metrica passa a premiar a duplicacao.
    """

    def test_copiar_um_no_baixa_o_reuso(self) -> None:
        antes = self.medir().reuso

        # A mutacao: o `grafo.py` deixa de importar o `partilhado_um` e passa a
        # ter uma copia dele dentro de si.
        grafo = self.raiz / "pkg" / "verticais" / "nova" / "grafo.py"
        texto = grafo.read_text(encoding="utf-8")
        copiado = texto.replace(
            "from ..velha.n import partilhado_dois, partilhado_um",
            "from ..velha.n import partilhado_dois\n\n\ndef partilhado_um():\n"
            + "".join(["    _ = 1\n"] * (self.SIMBOLO - 1)),
        )
        grafo.write_text(copiado, encoding="utf-8")

        depois = self.medir()
        self.assertLess(
            depois.reuso,
            antes,
            "a metrica nao viu uma copia: ela premia a duplicacao",
        )
        # E desce pelas duas pontas, que e a razao de descer tanto.
        self.assertEqual(
            depois.especifico,
            self.ESPECIFICO + self.MIGRACAO_NOVA + self.INICIALIZADOR + self.SIMBOLO,
        )
        self.assertEqual(
            depois.partilhado, self.NUCLEO + self.SIMBOLO + self.MIGRACAO_BASE
        )

    def test_apagar_prosa_do_especifico_nao_muda_o_reuso(self) -> None:
        """A outra direccao: o numero nao se move com comentarios.

        Sem isto, baixar o reuso bastava escrever comentarios — e subi-lo
        bastava apaga-los.
        """
        grafo = self.raiz / "pkg" / "verticais" / "nova" / "grafo.py"
        antes = self.medir().reuso
        grafo.write_text(
            '"""Prosa nova.\n\nEm varias linhas.\n"""\n# e um comentario\n'
            + grafo.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.assertAlmostEqual(self.medir().reuso, antes, places=9)


class TestClassificacao(_ComArvore):
    def test_uma_sobreposicao_com_o_excluido_NAO_declarada_levanta(self) -> None:
        """**O achado mais perigoso da revisao adversarial, fechado.**

        O `excluido` era a **unica** classe isenta do guarda de ambiguidade, e a
        **unica** que consegue retirar do numerador. Medido no repositorio
        verdadeiro: uma linha `excluido: - "*/verticais/servicos/nos.py"` subia o
        reuso de 87,58% para **91,75%** em silencio, enquanto a mesma linha em
        `outra_vertical` levantava. Num portao, era o botao de o premir.
        """
        declaracao = Declaracao.de_mapa(self.declaracao, onde="teste")
        with self.assertRaises(DeclaracaoInvalidaError) as erro:
            classificar("pkg/verticais/nova/test_x.py", declaracao)
        self.assertIn("mais de uma classe", str(erro.exception))
        self.assertIn("sobreposicoes", str(erro.exception))

    def test_uma_sobreposicao_declarada_e_excluida_com_a_razao(self) -> None:
        """E o par positivo: sem ele, o guarda tornava a declaracao inescrivel.

        No repositorio verdadeiro a sobreposicao legitima e o
        `verticais/servicos/fakes.py` — duplos de ensaio que vivem em `src/`, e
        o §5.4 manda excluir testes seja onde for que vivam.
        """
        declaracao = Declaracao.de_mapa(self.declaracao, onde="teste")
        classe, razao = classificar(
            "pkg/verticais/nova/test_declarado.py", declaracao
        )
        self.assertEqual(classe, "excluido")
        self.assertIn("sobreposicao declarada", razao)
        self.assertIn("legitima", razao)

    def test_uma_sobreposicao_sem_razao_levanta(self) -> None:
        """Sem razao nao e dispensa, e um buraco — a regra do `backlog-allow`."""
        bruto = self.declaracao
        bruto["caminho"]["sobreposicoes"] = [{"caminho": "pkg/nucleo.py"}]
        with self.assertRaises(DeclaracaoInvalidaError):
            Declaracao.de_mapa(bruto, onde="teste")

    def test_dupla_classificacao_levanta(self) -> None:
        """A ordem das linhas nao pode decidir se um ficheiro vai ao numerador."""
        bruto = self.declaracao
        bruto["caminho"]["outra_vertical"] = ["*/verticais/nova/*"]
        declaracao = Declaracao.de_mapa(bruto, onde="teste")
        with self.assertRaises(DeclaracaoInvalidaError) as erro:
            classificar("pkg/verticais/nova/grafo.py", declaracao)
        self.assertIn("mais de uma classe", str(erro.exception))

    def test_o_que_o_fecho_alcanca_e_ninguem_reclama_e_partilhado(self) -> None:
        declaracao = Declaracao.de_mapa(self.declaracao, onde="teste")
        classe, razao = classificar("pkg/nucleo.py", declaracao)
        self.assertEqual(classe, "partilhado")
        self.assertIn("nao reclamado", razao)


class TestDeclaracaoMalformada(_ComArvore):
    def test_entrada_que_nao_existe_no_disco_levanta(self) -> None:
        bruto = self.declaracao
        bruto["caminho"]["entradas"] = ["pkg/nao_existe.py"]
        with self.assertRaises(DeclaracaoInvalidaError):
            medir(self.raiz, bruto, onde="teste")

    def test_sem_migracoes_levanta(self) -> None:
        bruto = self.declaracao
        del bruto["caminho"]["migracoes"]
        with self.assertRaises(DeclaracaoInvalidaError):
            medir(self.raiz, bruto, onde="teste")

    def test_limiar_que_nao_e_numero_levanta(self) -> None:
        bruto = self.declaracao
        bruto["caminho"]["limiar"] = "setenta"
        with self.assertRaises(DeclaracaoInvalidaError):
            Declaracao.de_mapa(bruto, onde="teste")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
