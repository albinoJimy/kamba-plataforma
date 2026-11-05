"""As duas medidas sobre o repositorio VERDADEIRO (KAM-039).

As outras baterias correm sobre uma arvore sintetica, que e onde se consegue
escolher a resposta e medir os casos limite. Esta corre sobre o repositorio, e e
a unica que responde a pergunta do ticket: **a regra de dois verifica-se aqui?**

O que se pina e o que o criterio diz, e nao o numero do dia:

```text
fluxo == 0            a condicao (d) do §5.4. E a propriedade, e nao a medida
reuso >= limiar       o limiar do ADR-012, lido da declaracao
duas corridas iguais  o criterio 6 do bloco
```

**Nao se pina `reuso == 87,58`**, e e deliberado: um numero exacto parte-se em
cada *commit* que toque uma linha do nucleo, e um teste que falha por razoes que
nao tem nada a ver com o que afirma e um teste que alguem vai desligar. O numero
do dia vai no `docs/evidencia/KAM-039.md`, que e onde um numero datado pertence.

A suite do `tools/` corre com o `cwd` em `tools/` (ver o `coverage-python` do
`Makefile`), pelo que a raiz do repositorio deriva-se do `__file__` e nao do
directorio de trabalho.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from kamba_yaml import load_file

from reuse_metric.caminho import Declaracao, medir
from reuse_metric.nucleo import verificar

#: `tests/` -> `reuse_metric/` -> `tools/` -> a raiz.
RAIZ = Path(__file__).resolve().parents[3]
DECLARACAO = RAIZ / "ci" / "regra-de-dois.yaml"


class TestADeclaracaoEstaNoSitio(unittest.TestCase):
    def test_existe(self) -> None:
        self.assertTrue(
            DECLARACAO.is_file(),
            f"{DECLARACAO} nao existe: a raiz derivada do __file__ esta errada",
        )


class TestCriterioD(unittest.TestCase):
    """A condicao (d): nenhum ramo do nucleo decide por nome de vertical."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bruto = load_file(DECLARACAO)
        cls.veredicto = verificar(RAIZ, cls.bruto)

    def test_zero_ramos_decididos_por_nome_de_vertical(self) -> None:
        culpados = [
            f"{o.ficheiro}:{o.linha} ({o.forma}) {o.trecho}"
            for o in self.veredicto.de_classe("fluxo")
        ]
        self.assertEqual(self.veredicto.fluxo, 0, "excepcoes no nucleo: " + "; ".join(culpados))
        self.assertTrue(self.veredicto.passa)

    def test_varreu_o_nucleo_e_nao_uma_pasta_vazia(self) -> None:
        """**O canario do varrimento.** Zero achados sobre zero ficheiros e zero.

        Era a forma de este teste passar sem medir nada: um padrao errado na
        declaracao devolvia uma lista vazia e o `fluxo` dava 0 por ausencia.
        """
        self.assertGreater(self.veredicto.ficheiros, 50)
        self.assertGreater(
            self.veredicto.prosa + self.veredicto.conteudo,
            0,
            "o nucleo deste repositorio nomeia verticais em prosa: se nem isso "
            "aparece, o varrimento nao leu os ficheiros",
        )

    def test_ha_conteudo_e_isso_e_para_o_relatorio_e_nao_para_o_portao(self) -> None:
        """As tabelas e os identificadores que nomeiam uma vertical existem.

        Contam-se e vao ao relatorio; nao reprovam a condicao (d) por si. Onde
        passa a fronteira e decisao de quem assina o ADR-012 — ver
        `docs/reuse-metric.md` §4.
        """
        self.assertGreater(self.veredicto.conteudo, 0)
        formas = {o.forma for o in self.veredicto.de_classe("conteudo")}
        self.assertTrue(formas <= {"literal", "identificador"}, formas)


class TestMetricaDeReuso(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bruto = load_file(DECLARACAO)
        cls.medicao = medir(RAIZ, cls.bruto)
        cls.limiar = Declaracao.de_mapa(cls.bruto, onde="teste").limiar

    def test_passa_o_limiar_do_adr_012(self) -> None:
        self.assertGreaterEqual(
            self.medicao.reuso,
            self.limiar,
            f"reuso {self.medicao.reuso:.2f}% abaixo de {self.limiar:.2f}%",
        )

    def test_mediu_as_duas_pontas(self) -> None:
        """Um numerador ou um denominador vazios dao um reuso que nao diz nada."""
        self.assertGreater(self.medicao.especifico, 0)
        self.assertGreater(self.medicao.partilhado, 0)

    def test_os_doze_nos_reutilizados_contam_como_simbolos(self) -> None:
        """A ligacao a lista que o KAM-035 deixou para este ticket medir.

        O `NOS_REUTILIZADOS` do `verticais/servicos/arestas.py` tem doze nomes.
        Aqui mede-se que cada um deles aparece na conta como **simbolo** de um
        ficheiro misto — e nao que o `nos.py` do Vendedor inteiro conta como
        partilhado, que seriam 2 168 linhas de reuso que ninguem reutilizou.
        """
        esperados = {
            "ingest",
            "stt",
            "guard_in",
            "tools_info",
            "validate",
            "guard_out",
            "send",
            "handoff_prepare",
            "handoff_wait",
            "handoff_close",
            "draft_prepare",
            "draft_wait",
        }
        simbolos = {e.simbolo for e in self.medicao.entradas if e.simbolo}
        self.assertEqual(esperados - simbolos, set())
        do_vendedor = [
            e
            for e in self.medicao.entradas
            if e.simbolo and e.caminho.endswith("verticais/vendedor/nos.py")
        ]
        # Sao mais do que doze porque a vertical tambem importa de la o
        # `Dependencias`, tres constantes e duas utilitarias privadas.
        self.assertGreaterEqual(len(do_vendedor), 12)
        self.assertLess(
            sum(e.sloc for e in do_vendedor),
            1000,
            "contou o ficheiro inteiro do Vendedor em vez dos simbolos",
        )

    def test_e_reproduzivel(self) -> None:
        self.assertEqual(medir(RAIZ, self.bruto).como_mapa(), self.medicao.como_mapa())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
