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
    """A condicao (d): nenhum ramo do nucleo **despacha** por vertical."""

    #: As excepcoes que esta arvore tem hoje, por `(ficheiro, nome)`.
    #:
    #: **Pina-se a lista e nao o numero**, e a razao e a licao mais cara deste
    #: ticket: o ensaio anterior afirmava `fluxo == 0` e dava verde porque o
    #: verificador nao sabia seguir uma constante de modulo — media a forma
    #: inline, que esta arvore nao usa. Com a lista, uma excepcao **nova** fica
    #: vermelha nomeada, e esta fica registada em vez de esquecida.
    #:
    #: **Esta vazia desde que o `AO_DONO` saiu do nucleo**, e e isso que faz a
    #: condicao (d) passar. O que ele era: uma tabela de pares `(vertical, tipo)`
    #: com entradas **so do Vendedor**, lida num `if` do `accoes_de` — o nucleo
    #: decidia ali, pelo nome da vertical, se o dono da loja era avisado, que e
    #: a letra do que o §5.4 (d) chama uma excepcao no core. Passou a
    #: `subscriptions[].notifica` do `registry/`, que o criterio exclui da busca
    #: por extenso.
    #:
    #: Medido a 2026-11-06: `python -m reuse_metric nucleo` → 110 ficheiros,
    #: `fluxo 0, dominio 1, conteudo 45, prosa 118`, saida **0**.
    #:
    #: **Vazia nao e o mesmo que ausente**, e por isso a lista fica: um conjunto
    #: vazio mantem o ensaio a dizer «nenhuma, e sei quais eram as que havia», e
    #: uma excepcao nova continua a ficar vermelha **nomeada**. Quem acrescentar
    #: uma a esta lista esta a registar uma excepcao no nucleo, nao a corrigir um
    #: ensaio.
    CONHECIDAS: set[tuple[str, str]] = set()

    @classmethod
    def setUpClass(cls) -> None:
        cls.bruto = load_file(DECLARACAO)
        cls.veredicto = verificar(RAIZ, cls.bruto)

    def test_as_excepcoes_do_nucleo_sao_exactamente_as_conhecidas(self) -> None:
        achadas = {(o.ficheiro, o.nome) for o in self.veredicto.de_classe("fluxo")}
        novas = sorted(achadas - self.CONHECIDAS)
        desaparecidas = sorted(self.CONHECIDAS - achadas)
        self.assertEqual(novas, [], f"excepcao nova no nucleo: {novas}")
        self.assertEqual(
            desaparecidas,
            [],
            "uma excepcao conhecida desapareceu: se foi corrigida, apaga-a do "
            f"`CONHECIDAS` no mesmo PR — {desaparecidas}",
        )

    def test_a_condicao_d_passa_nesta_arvore(self) -> None:
        """A condicao (d) do §5.4, dita pelo veredicto e nao pela lista.

        **Nao e o mesmo ensaio que o de cima.** Aquele compara conjuntos e
        responde «nenhuma excepcao nova»; este le o predicado que o portao leria,
        e ficaria vermelho se alguem mudasse o `passa` para
        `fluxo + dominio == 0` — que e a leitura que o §5.4 **nao** tem, e que
        tornava o criterio insatisfazivel por causa da lista fechada do
        `contexto.py`.
        """
        self.assertTrue(self.veredicto.passa)
        self.assertEqual(self.veredicto.fluxo, 0)
        self.assertGreater(self.veredicto.dominio, 0)

    def test_a_validacao_do_dominio_nao_conta_como_excepcao(self) -> None:
        """O `contexto.py` valida a vertical contra uma lista **fechada**.

        Isso nao distingue entre verticais — o criterio 5 do KAM-014 exige-o
        por escrito — e por isso e `dominio` e nao `fluxo`. Mede-se que ele
        **e** visto (nao e silencio) e que **nao** reprova.
        """
        dominios = {(o.ficheiro, o.forma) for o in self.veredicto.de_classe("dominio")}
        self.assertIn(
            ("services/agr/src/kamba_agr/contexto.py", "dominio_fechado"),
            dominios,
            "o verificador deixou de ver a validacao por lista fechada",
        )

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
