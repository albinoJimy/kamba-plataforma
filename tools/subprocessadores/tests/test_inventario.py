"""O inventario de subprocessadores: o que o `ler` recusa (KAM-069, criterios 5 e 6).

**O inventario real entra nestes testes**, e nao so *fixtures*: o criterio 5 pede
«as 11 linhas de `docs/tecnica/08` §8.3.2», e uma suite que medisse apenas
*fixtures* ficava verde com o ficheiro do repositorio vazio. As *fixtures* estao
aqui para o resto — cada regra de validacao com o seu caso negativo —, porque
nenhuma delas se pode medir sobre um ficheiro conforme.

**E a paridade com `kamba_core.destinos` prova-se, e tem de ser.** As catorze
finalidades estao escritas duas vezes: aqui, porque `tools/` corre antes de
qualquer instalacao e nao depende de `libs/`, e la, porque e o codigo que decide
com elas. Duas copias sem teste divergem no dia em que uma delas mudar.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from subprocessadores import documentos
from subprocessadores.inventario import (
    CAMINHO,
    ESTADOS,
    FINALIDADES,
    LINHAS_ESPERADAS,
    Inventario,
    InventarioInvalido,
    Subprocessador,
    ler,
    validar,
)

RAIZ = Path(__file__).resolve().parents[3]


def _linha(**campos) -> Subprocessador:
    base = {
        "nome": "fornecedor_de_teste",
        "designacao": "Fornecedor de Teste",
        "funcao": "Teste",
        "dados_pessoais": "nenhum",
        "pais_hipotese": "US",
        "pais_verificado": False,
        "estado": "pendente",
        "finalidades": ("conversa",),
        "contrato_ref": None,
        "retencao_zero": False,
        "sem_treino": False,
        "apd_ref": None,
        "credor": "KAM-104",
        "nota": "uma frase que sobreviva a sair o autor",
    }
    base.update(campos)
    return Subprocessador(**base)


def _inventario(*linhas: Subprocessador) -> Inventario:
    return Inventario(versao="1.0", subprocessadores=linhas)


class TestInventarioDoRepositorio(unittest.TestCase):
    """O ficheiro que esta em `gov/`, lido e validado."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.inventario = ler(RAIZ)

    def test_tem_as_onze_linhas_do_doc_08(self) -> None:
        self.assertEqual(len(self.inventario.subprocessadores), LINHAS_ESPERADAS)
        self.assertEqual(LINHAS_ESPERADAS, 11)

    def test_as_onze_estao_pendentes_e_nenhuma_tem_apd_ref(self) -> None:
        """Medido, nao suposto.

        O `ext:KAM-105` fechou com **0 de 14** destinos com `apd_ref`
        (`docs/tecnica/evidencia/validacao/Seguimento_APD.md` §1): zero
        submetidos, zero com numero de protocolo. Este teste e o que torna essa
        ausencia visivel em vez de implicita — e e ele que **falha** no dia em
        que a primeira autorizacao chegar, que e o dia em que alguem tem de
        reler o bloco do KAM-069.
        """
        # As duas contagens, e hoje dao o mesmo numero: as onze estao
        # `pendente` **pelo estado** e nao por exclusao. O achado 8 da revisao
        # adversarial era o nome a mentir quando elas divergirem.
        self.assertEqual(len(self.inventario.nao_autorizados), LINHAS_ESPERADAS)
        self.assertEqual(len(self.inventario.pendentes), LINHAS_ESPERADAS)
        for s in self.inventario.subprocessadores:
            with self.subTest(nome=s.nome):
                self.assertIsNone(s.apd_ref)
                self.assertFalse(s.checklist_completa)

    def test_cada_finalidade_usada_existe_no_dominio(self) -> None:
        usadas = {f for s in self.inventario.subprocessadores for f in s.finalidades}
        self.assertEqual(usadas - set(FINALIDADES), set())

    def test_a_observabilidade_nao_tem_subprocessador_e_isso_e_declarado(self) -> None:
        """A finalidade existe no dominio e **nenhuma linha a declara**.

        Nao e um defeito do inventario: o §8.3.2 nao tem linha de
        observabilidade, e o criterio 4 nomeia-a como ponto de invocacao. A
        lacuna fica aqui, afirmada, e o mapa de tratamentos gerado escreve-a com
        o credor (KAM-080 e KAM-105) — em vez de ficar uma finalidade sem uso
        que ninguem explica.
        """
        usadas = {f for s in self.inventario.subprocessadores for f in s.finalidades}
        self.assertNotIn("observabilidade", usadas)
        mapa = documentos.mapa_de_tratamentos(self.inventario, "1.0+000000000000")
        self.assertIn("Observabilidade como destino", mapa)

    def test_os_documentos_gerados_estao_em_dia(self) -> None:
        """O `--check` do CLI, pelo mesmo caminho que o *gate* corre."""
        versao = self.inventario.versao_do_mapa()
        for relativo, conteudo in (
            (documentos.CAMINHO_PUBLICO, documentos.lista_publica(self.inventario, versao)),
            (documentos.CAMINHO_MAPA, documentos.mapa_de_tratamentos(self.inventario, versao)),
        ):
            with self.subTest(documento=relativo):
                actual = (RAIZ / relativo).read_text(encoding="utf-8")
                self.assertEqual(actual.replace("\r\n", "\n"), conteudo)

    def test_a_lista_publica_nao_leva_informacao_interna(self) -> None:
        """Audiencias diferentes, conteudo diferente — e esta e a metade publica.

        O credor, a referencia de contrato e a *checklist* sao informacao interna
        de conformidade: publica-las dizia ao mundo qual dos nossos contratos
        esta por assinar.
        """
        publico = documentos.lista_publica(self.inventario, "1.0+000000000000")
        for interno in ("credor", "contrato_ref", "retencao_zero", "sem_treino"):
            with self.subTest(campo=interno):
                self.assertNotIn(interno, publico)
        # E leva o que o titular precisa de saber.
        for s in self.inventario.subprocessadores:
            self.assertIn(s.designacao, publico)

    def test_nenhum_dos_dois_documentos_leva_um_numero_de_telefone(self) -> None:
        """A caixa de privacidade do DoD, e o *gate* 7 mede o mesmo na arvore.

        O varredor de `tools/meta-sim` le a arvore inteira e exige entrada no
        `INVENTARIO` com contagem exacta para qualquer `+244…` ou `9########`.
        Dois documentos **gerados** que o quebrassem eram um vermelho que
        aparecia longe da causa.
        """
        import re

        padrao = re.compile(r"\+?244|(?<!\d)9\d{8}(?!\d)")
        for relativo in (documentos.CAMINHO_PUBLICO, documentos.CAMINHO_MAPA):
            with self.subTest(documento=relativo):
                texto = (RAIZ / relativo).read_text(encoding="utf-8")
                self.assertEqual(padrao.findall(texto), [])


class TestVersaoDoMapa(unittest.TestCase):
    """Criterio 9: «alterar uma linha altera a versao»."""

    def test_a_mesma_entrada_da_a_mesma_versao(self) -> None:
        inventario = _inventario(_linha())
        self.assertEqual(inventario.versao_do_mapa(), inventario.versao_do_mapa())

    def test_mudar_um_campo_que_decide_muda_a_versao(self) -> None:
        base = _inventario(_linha())
        for campo, valor in (
            ("pais_hipotese", "ZA"),
            ("estado", "negado"),
            ("finalidades", ("conversa", "visao")),
            ("credor", "KAM-090"),
            ("retencao_zero", True),
        ):
            with self.subTest(campo=campo):
                outro = _inventario(_linha(**{campo: valor}))
                self.assertNotEqual(base.versao_do_mapa(), outro.versao_do_mapa())

    def test_reescrever_a_nota_nao_muda_a_versao(self) -> None:
        """O que se *hasheia* e o conteudo que decide, nao o texto que o descreve.

        E a mesma ideia do `ci/llm-aliases.lock` do KAM-030, que exclui os
        comentarios — e sem ela cada correccao de redaccao era uma versao nova
        do mapa de tratamentos, que e um documento que se submete a APD.
        """
        base = _inventario(_linha())
        outro = _inventario(_linha(nota="outra frase, igualmente verdadeira"))
        self.assertEqual(base.versao_do_mapa(), outro.versao_do_mapa())

    def test_os_destinos_entram_na_versao(self) -> None:
        """«Gerado do inventario **e** de `tenant_destinations`» (criterio 9).

        Uma versao que ignorasse a configuracao ficava igual depois de alguem
        autorizar um destino — e era precisamente essa mudanca que o mapa tem de
        registar.
        """
        inventario = _inventario(_linha())
        sem = inventario.versao_do_mapa()
        com = inventario.versao_do_mapa(({"provider": "openai", "status": "autorizado"},))
        self.assertNotEqual(sem, com)

    def test_a_versao_tem_a_forma_que_o_gate_de_go_live_exige(self) -> None:
        import re

        versao = _inventario(_linha()).versao_do_mapa()
        self.assertRegex(versao, r"^[0-9]+\.[0-9]+\+[0-9a-f]{12}$")


class TestValidacao(unittest.TestCase):
    """Cada regra com o seu caso negativo. Sem casos negativos, a validacao
    e uma funcao que devolve `None`."""

    def test_o_numero_de_linhas_e_fixo(self) -> None:
        with self.assertRaises(InventarioInvalido) as apanhado:
            validar(_inventario(_linha()))
        self.assertIn("§8.3.2", str(apanhado.exception))

    def test_nomes_repetidos_sao_recusados(self) -> None:
        linhas = tuple(_linha() for _ in range(LINHAS_ESPERADAS))
        with self.assertRaises(InventarioInvalido) as apanhado:
            validar(_inventario(*linhas))
        self.assertIn("repetido", str(apanhado.exception))

    def test_autorizado_sem_checklist_e_recusado(self) -> None:
        """Criterio 6, e **a mesma regra que o `CHECK` da revisao `0036` impoe**.

        As duas superficies tem de aceitar exactamente o mesmo conjunto de
        linhas, ou uma autoriza o que a outra recusa.
        """
        completo = {
            "estado": "autorizado",
            "apd_ref": "APD/2026/000",
            "contrato_ref": "contratos/2026/teste",
            "retencao_zero": True,
            "sem_treino": True,
        }
        for falta, valor in (
            ("apd_ref", None),
            ("contrato_ref", None),
            ("retencao_zero", False),
            ("sem_treino", False),
        ):
            with self.subTest(falta=falta):
                campos = dict(completo)
                campos[falta] = valor
                linhas = [_linha(nome=f"forn{n}") for n in range(LINHAS_ESPERADAS - 1)]
                linhas.append(_linha(nome="autorizado_incompleto", **campos))
                with self.assertRaises(InventarioInvalido) as apanhado:
                    validar(_inventario(*linhas))
                self.assertIn("checklist", str(apanhado.exception))

    def test_um_autorizado_completo_passa(self) -> None:
        """O canario: uma validacao que recusasse **tudo** passava os quatro
        casos acima."""
        linhas = [_linha(nome=f"forn{n}") for n in range(LINHAS_ESPERADAS - 1)]
        linhas.append(
            _linha(
                nome="autorizado_completo",
                estado="autorizado",
                apd_ref="APD/2026/000",
                contrato_ref="contratos/2026/teste",
                retencao_zero=True,
                sem_treino=True,
            )
        )
        validar(_inventario(*linhas))


class TestDominios(unittest.TestCase):
    def test_as_finalidades_sao_as_do_nucleo(self) -> None:
        """A paridade entre `tools/` e `libs/`, nos dois sentidos.

        `tools/` nao importa `libs/` — as ferramentas correm antes de qualquer
        instalacao, que e a razao de o `kamba_yaml` existir —, pelo que a lista
        esta escrita duas vezes. Este teste e o que faz as duas copias serem a
        mesma lista, e acrescenta o caminho a mao porque e assim que `tools/`
        alcanca `libs/` sem depender dele.
        """
        nucleo = str(RAIZ / "libs" / "py-core" / "src")
        if nucleo not in sys.path:
            sys.path.insert(0, nucleo)
        from kamba_core.destinos import ESTADOS as ESTADOS_DO_NUCLEO
        from kamba_core.destinos import FINALIDADES as FINALIDADES_DO_NUCLEO

        self.assertEqual(set(FINALIDADES), set(FINALIDADES_DO_NUCLEO))
        self.assertEqual(set(ESTADOS), set(ESTADOS_DO_NUCLEO))

    def test_sao_catorze_e_estao_ordenadas(self) -> None:
        self.assertEqual(len(FINALIDADES), 14)
        self.assertEqual(list(FINALIDADES), sorted(FINALIDADES))

    def test_o_caminho_do_inventario_e_o_que_o_canon_declara(self) -> None:
        self.assertEqual(CAMINHO, "gov/subprocessadores.yaml")
        self.assertTrue((RAIZ / CAMINHO).is_file())


if __name__ == "__main__":
    unittest.main()
