"""A travessia das ligacoes `link:` do workspace (KAM-133).

Sobre *fixtures* e nao sobre o `pnpm-lock.yaml` do repositorio, de proposito: o
caso que mais interessa — um pacote do workspace que toma uma dependencia de
terceiros — **ainda nao existe na arvore**, e e precisamente o dia em que vai
existir que o ticket paga. «Verificado com uma dependencia acrescentada de
proposito num teste, e nao so por leitura do codigo» (criterio 2 do KAM-133).

Os ciclos tambem nao existem na arvore de hoje, e o `npm` permite-os.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sbom import pnpm_lock


def escrever(texto: str) -> Path:
    """Escreve um `pnpm-lock.yaml` de fixture e devolve o caminho."""
    pasta = Path(tempfile.mkdtemp())
    destino = pasta / "pnpm-lock.yaml"
    destino.write_text(texto.lstrip("\n"), encoding="utf-8", newline="\n")
    return destino


#: Um servico que declara `hono` e liga-se a um pacote do workspace que declara
#: `biblioteca-de-terceiros` — a dependencia que o `@kamba/core-ts` ainda nao
#: tem. A `ferramenta-de-build` esta em `devDependencies` do pacote ligado: e o
#: controlo negativo, porque atravessar nao e copiar.
LOCK_COM_LIGACAO = """
lockfileVersion: '9.0'

importers:

  .:
    devDependencies:
      typescript:
        specifier: 5.9.3
        version: 5.9.3

  packages/nucleo:
    dependencies:
      biblioteca-de-terceiros:
        specifier: 1.2.3
        version: 1.2.3
    devDependencies:
      ferramenta-de-build:
        specifier: 9.9.9
        version: 9.9.9

  packages/contratos: {}

  services/servico:
    dependencies:
      '@kamba/contratos':
        specifier: workspace:*
        version: link:../../packages/contratos
      '@kamba/nucleo':
        specifier: workspace:*
        version: link:../../packages/nucleo
      hono:
        specifier: 4.13.13
        version: 4.13.13

packages:

  hono@4.13.13:
    resolution: {integrity: sha512-xxx}

snapshots:

  hono@4.13.13: {}

  typescript@5.9.3: {}

  ferramenta-de-build@9.9.9: {}

  biblioteca-de-terceiros@1.2.3:
    dependencies:
      dependencia-de-segundo-grau: 4.5.6

  dependencia-de-segundo-grau@4.5.6: {}
"""

#: Dois pacotes do workspace que se declaram um ao outro. O `npm` permite-o, e
#: uma travessia sem conjunto de visitados nao termina.
LOCK_COM_CICLO = """
lockfileVersion: '9.0'

importers:

  services/servico:
    dependencies:
      '@kamba/a':
        specifier: workspace:*
        version: link:../../packages/a

  packages/a:
    dependencies:
      '@kamba/b':
        specifier: workspace:*
        version: link:../b
      comum:
        specifier: 1.0.0
        version: 1.0.0

  packages/b:
    dependencies:
      '@kamba/a':
        specifier: workspace:*
        version: link:../a
      comum:
        specifier: 1.0.0
        version: 1.0.0

snapshots:

  comum@1.0.0: {}
"""


class TestLeitura(unittest.TestCase):
    def setUp(self) -> None:
        self.grafo = pnpm_lock.ler(escrever(LOCK_COM_LIGACAO))

    def test_um_importador_sem_dependencias_e_registado(self) -> None:
        """`packages/contratos: {}` tambem e um importador.

        O padrao exigia fim de linha a seguir aos dois pontos, pelo que um
        pacote do workspace sem dependencias nao existia para a leitura — e o
        `link:` que lhe apontava nao tinha destino. Nao se via porque, sem
        travessia de `link:`, nada procurava o destino.
        """
        self.assertIn("packages/contratos", self.grafo.directas)
        self.assertEqual(self.grafo.directas["packages/contratos"], set())

    def test_as_ligacoes_sao_resolvidas_para_importadores(self) -> None:
        self.assertEqual(
            self.grafo.ligacoes["services/servico"],
            {
                ("@kamba/contratos", "packages/contratos"),
                ("@kamba/nucleo", "packages/nucleo"),
            },
        )

    def test_um_link_nao_entra_como_pacote_de_terceiros(self) -> None:
        """`link:../../packages/nucleo` nao e uma versao publicada."""
        for referencia in self.grafo.directas["services/servico"]:
            self.assertNotIn("link:", referencia)

    def test_resolucao_do_caminho(self) -> None:
        casos = [
            ("services/gwy", "link:../../packages/core-ts", "packages/core-ts"),
            ("packages/core-ts", "link:../contracts", "packages/contracts"),
            (".", "link:packages/x", "packages/x"),
            ("libs/a", "link:../b", "libs/b"),
        ]
        for importador, especificador, esperado in casos:
            with self.subTest(importador=importador, link=especificador):
                self.assertEqual(
                    pnpm_lock.resolver_ligacao(importador, especificador), esperado
                )


class TestTravessia(unittest.TestCase):
    def setUp(self) -> None:
        self.grafo = pnpm_lock.ler(escrever(LOCK_COM_LIGACAO))
        self.fecho = pnpm_lock.fecho("services/servico", self.grafo)

    def test_a_o_pacote_do_workspace_aparece(self) -> None:
        self.assertEqual(
            self.fecho.importadores, {"packages/nucleo", "packages/contratos"}
        )

    def test_b_um_terceiro_do_pacote_ligado_aparece_transitivamente(self) -> None:
        """O caso que o ticket existe para pagar.

        O `biblioteca-de-terceiros` nao e declarado pelo servico: e declarado
        pelo pacote do workspace que o servico carrega. E a
        `dependencia-de-segundo-grau` nem por um nem por outro.
        """
        self.assertIn("biblioteca-de-terceiros@1.2.3", self.fecho.terceiros)
        self.assertIn("dependencia-de-segundo-grau@4.5.6", self.fecho.terceiros)
        self.assertIn("hono@4.13.13", self.fecho.terceiros)

    def test_as_devdependencies_do_pacote_ligado_nao_atravessam(self) -> None:
        """Atravessar nao e copiar.

        Quem carrega uma biblioteca nao carrega as ferramentas com que ela se
        constroi. Sem esta regra, o SBOM de um servico passaria a sobredeclarar
        — que e um erro de atribuicao como o outro, do lado contrario.
        """
        self.assertNotIn("ferramenta-de-build@9.9.9", self.fecho.terceiros)
        # E continuam a contar no SBOM do proprio pacote que as declara.
        do_nucleo = pnpm_lock.fecho("packages/nucleo", self.grafo)
        self.assertIn("ferramenta-de-build@9.9.9", do_nucleo.terceiros)

    def test_as_devdependencies_do_proprio_alvo_contam(self) -> None:
        """A raiz so tem `devDependencies`; sem elas ficava com zero."""
        self.assertEqual(pnpm_lock.fecho(".", self.grafo).terceiros, {"typescript@5.9.3"})

    def test_o_importador_de_partida_nao_entra_nos_alcancados(self) -> None:
        """O proprio alvo entra pela sua identidade, nao pela travessia."""
        self.assertNotIn("services/servico", self.fecho.importadores)

    def test_a_relacao_diz_porque_e_que_o_terceiro_la_esta(self) -> None:
        prefixo = pnpm_lock.PREFIXO_WORKSPACE
        self.assertEqual(
            self.fecho.relacoes[f"{prefixo}services/servico"],
            {f"{prefixo}packages/contratos", f"{prefixo}packages/nucleo", "hono@4.13.13"},
        )
        self.assertEqual(
            self.fecho.relacoes[f"{prefixo}packages/nucleo"],
            {"biblioteca-de-terceiros@1.2.3"},
        )


class TestCiclo(unittest.TestCase):
    """Visitado e visitado: o ciclo termina e nao duplica."""

    def setUp(self) -> None:
        self.grafo = pnpm_lock.ler(escrever(LOCK_COM_CICLO))

    def test_c_o_ciclo_termina(self) -> None:
        # Sem conjunto de visitados isto nao devolveria; o limite de tempo do
        # `unittest` nao existe, pelo que a prova de que termina e a execucao.
        fecho = pnpm_lock.fecho("services/servico", self.grafo)
        self.assertEqual(fecho.importadores, {"packages/a", "packages/b"})
        self.assertEqual(fecho.terceiros, {"comum@1.0.0"})

    def test_c_o_ciclo_nao_duplica(self) -> None:
        """`terceiros` e `importadores` sao conjuntos; as relacoes tambem.

        A prova de que nao duplica nao pode ser «e um `set`»: conta-se o numero
        de nos do grafo, que e o que um `dependsOn` repetido tornaria maior.
        """
        fecho = pnpm_lock.fecho("services/servico", self.grafo)
        prefixo = pnpm_lock.PREFIXO_WORKSPACE
        self.assertEqual(
            sorted(fecho.relacoes),
            [
                "comum@1.0.0",
                f"{prefixo}packages/a",
                f"{prefixo}packages/b",
                f"{prefixo}services/servico",
            ],
        )
        self.assertEqual(
            fecho.relacoes[f"{prefixo}packages/a"],
            {f"{prefixo}packages/b", "comum@1.0.0"},
        )

    def test_c_partir_de_dentro_do_ciclo_tambem_termina(self) -> None:
        fecho = pnpm_lock.fecho("packages/a", self.grafo)
        self.assertEqual(fecho.importadores, {"packages/b"})


class TestLigacaoParaForaDoWorkspace(unittest.TestCase):
    """Um `link:` para uma pasta que o lockfile nao declara como importador.

    Nao se segue e nao se inventa: nao ha de onde tirar as dependencias dessa
    pasta. O que nao se faz e rebentar — um `KeyError` aqui punha o gate 11 a
    imprimir *traceback* em vez de um veredicto.
    """

    LOCK = """
lockfileVersion: '9.0'

importers:

  services/servico:
    dependencies:
      '@fora/daqui':
        specifier: workspace:*
        version: link:../../../outro-repositorio/pacote

snapshots: {}
"""

    def test_nao_rebenta_e_nao_inventa(self) -> None:
        grafo = pnpm_lock.ler(escrever(self.LOCK))
        fecho = pnpm_lock.fecho("services/servico", grafo)
        self.assertEqual(fecho.terceiros, frozenset())
        self.assertEqual(fecho.importadores, frozenset())


if __name__ == "__main__":
    unittest.main()
